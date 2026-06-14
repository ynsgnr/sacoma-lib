"""Windows BLE runner for a SACOMA Ultra scale.

This script owns only the **transport + OS + user config**: BLE (via bleak),
timing, and the weight->profile map. All protocol work — frame reassembly,
decoding, command encoding and sequencing — lives in the ``sacoma`` library
(:class:`sacoma.Session`); body-composition maths is :func:`sacoma.compute`.
That split is what makes the same library reusable from e.g. a Home Assistant
component: bring your own BLE, feed bytes to a ``Session``, wire in a profile.

Flow: connect -> read the stabilized weight -> pick the matching user profile
from WEIGHT_PROFILES -> publish it so the scale shows its body-comp screen, and
decode the A3 result into a BodyComposition when the scale measures.

    py -3 scripts\ble_test.py --scan
    py -3 scripts\ble_test.py --address AA:BB:..            # read weight + select + publish
    py -3 scripts\ble_test.py --address AA:BB:.. --listen   # decode only, no writes
    py -3 scripts\ble_test.py --address AA:BB:.. --debug    # raw TX/RX frame logs

Requires:  py -3 -m pip install bleak
"""
from __future__ import annotations

import argparse
import asyncio
import time
from dataclasses import dataclass
from typing import List, Optional, Tuple

from bleak import BleakClient, BleakScanner

from sacoma import Session, compute
from sacoma.models import PeopleType, Sex, UserProfile

CHR_WRITE_FFB1 = "0000ffb1-0000-1000-8000-00805f9b34fb"
CHR_NOTIFY_FFB2 = "0000ffb2-0000-1000-8000-00805f9b34fb"  # A2 weight stream
CHR_NOTIFY_FFB3 = "0000ffb3-0000-1000-8000-00805f9b34fb"  # A3 result / A0,A1 control


# ---- user config: weight range -> user profile ------------------------------------------
@dataclass
class User:
    """A user model: the account id (0 = none/test) + the profile the scale needs."""
    user_id: int
    profile: UserProfile


# Edit for your household. First matching range wins (kg, inclusive). In a Home
# Assistant component this would come from configured users instead.
WEIGHT_PROFILES: List[Tuple[float, float, User]] = [
    (62.0, 67.0, User(101044071, UserProfile(height_cm=165, age=30, sex=Sex.MALE,
                                             people_type=PeopleType.SPORTMAN))),
    (67.0, 75.0, User(0, UserProfile(height_cm=170, age=31, sex=Sex.FEMALE,
                                     people_type=PeopleType.NORMAL))),
]


def _describe(user: User) -> str:
    p = user.profile
    return f"uid={user.user_id} height={p.height_cm} sex={p.sex.name} age={p.age} type={p.people_type.name}"


def select_user(weight_kg: float) -> Optional[User]:
    """Pick the user whose weight range contains ``weight_kg`` (None if no match)."""
    for low, high, user in WEIGHT_PROFILES:
        if low <= weight_kg <= high:
            print(f"   [select] {weight_kg:.2f}kg in [{low},{high}] -> {_describe(user)}")
            return user
    print(f"   [select] {weight_kg:.2f}kg matched NO range in WEIGHT_PROFILES")
    return None


# ---- transport glue (thin: the protocol lives in sacoma.Session) ------------------------
class Monitor:
    """Tracks decoded state and prints results. Decoding is done by ``session``;
    with ``--debug`` it prints raw RX frames instead of decoded results."""

    def __init__(self, session: Session, debug: bool) -> None:
        self.session = session
        self.debug = debug
        self.weight = 0.0
        self.stable_weight: Optional[float] = None
        self.result = None
        self.pending_control = 0      # incoming A0/A3 frames awaiting a B0 ack
        self.user: Optional[User] = None   # set once selected -> enables compute on result
        self._logged_w = None

    def on_frame(self, channel: str, data: bytearray) -> None:
        frame = bytes(data)
        if self.debug:
            print(f"<- RX {channel[4:8]} seq={frame[0]:02x} len={frame[1]:02x} "
                  f"frag={frame[2]} type={frame[3]:02x}  {frame.hex()}")
        rx = self.session.feed(channel, frame)
        if rx.control:
            self.pending_control += 1
        m = rx.measurement
        if m is None:
            return
        if m.impedances_ohm:
            self.result = m
            if not self.debug:
                print(f"== RESULT weight={m.weight_kg:.2f}kg imps={m.impedances_ohm}")
                user = self.user or select_user(m.weight_kg)
                if user is not None:
                    print(f"   body composition -> {compute(m, user.profile)}")
        else:
            self.weight = m.weight_kg
            if m.is_stabilized:
                self.stable_weight = m.weight_kg
            tag = (round(m.weight_kg, 1), m.is_stabilized)
            if not self.debug and tag != self._logged_w:
                self._logged_w = tag
                print(f"== weight {m.weight_kg:6.2f}kg {'STABLE' if m.is_stabilized else 'live'}")


class Scale:
    """BLE writer: pushes the frames a ``Session`` builds to FFB1."""

    def __init__(self, client: BleakClient, session: Session, debug: bool) -> None:
        self.client = client
        self.session = session
        self.debug = debug

    async def _write(self, frames: List[bytes]) -> None:
        for f in frames:
            if self.debug:
                print(f"-> TX ffb1 seq={f[0]:02x} type={f[3]:02x}  {f.hex()}")
            await self.client.write_gatt_char(CHR_WRITE_FFB1, f, response=False)

    async def sync(self, user: User, weight_kg: float) -> None:
        await self._write(self.session.sync(user.profile, weight_kg, user.user_id,
                                            unix_time=int(time.time())))

    async def user_list(self, user: User, weight_kg: float) -> None:
        await self._write(self.session.user_list([(user.profile, weight_kg, user.user_id)]))

    async def other(self, sub_cmd: int = 0x09) -> None:
        await self._write(self.session.other(sub_cmd))

    async def ack(self) -> None:
        await self._write(self.session.ack())


# ---- the two operations the consumer wires together -------------------------------------
async def read_weight(scale: Scale, monitor: Monitor, *, timeout: float = 60.0,
                      settle: int = 8, min_kg: float = 20.0) -> Optional[float]:
    """Wait for the live weight to settle at its peak and return it (kg).

    The weight climbs as you step on, so we track the running peak and only trust
    a stabilized value that holds (±0.05 kg) at the peak for ``settle`` reads and
    is >= ``min_kg``. Acks the scale's control frames meanwhile so it stays awake.
    """
    deadline = asyncio.get_event_loop().time() + timeout
    acked = 0
    last: Optional[float] = None
    peak = 0.0
    count = 0
    while asyncio.get_event_loop().time() < deadline:
        if monitor.pending_control > acked:
            acked = monitor.pending_control
            await scale.ack()
        w = monitor.stable_weight
        if w is not None and w >= min_kg:
            if w > peak + 0.05:
                peak, count = w, 0
                print(f"   [read] new peak {w:.2f}kg")
            elif last is not None and abs(w - last) <= 0.05:
                count += 1
                if count >= settle:
                    print(f"   [read] settled at {w:.2f}kg")
                    return w
            else:
                count = 0
            last = w
        await asyncio.sleep(0.3)
    return monitor.stable_weight or (monitor.weight or None)


async def publish(scale: Scale, monitor: Monitor, user: User, *, seconds: float = 20.0) -> None:
    """Drive the scale to show body-comp for ``user``: a sustained BA profile
    heartbeat + one-time BB/BD sync + B0 acks (a one-shot is not enough)."""
    print(f">>> PUBLISH {_describe(user)}  for {seconds:.0f}s", flush=True)
    monitor.user = user                       # let the monitor compute when a result lands
    deadline = asyncio.get_event_loop().time() + seconds
    acked = monitor.pending_control
    synced = False
    beats = 0
    while asyncio.get_event_loop().time() < deadline:
        weight = monitor.stable_weight or monitor.weight
        if weight and weight > 0:
            await scale.sync(user, weight)
            beats += 1
            if not synced:                    # one-time user-list + misc cmd, like the app
                await scale.user_list(user, weight)
                await scale.other(0x09)
                synced = True
        if monitor.pending_control > acked:
            acked = monitor.pending_control
            await scale.ack()
        await asyncio.sleep(0.4)
    print(f">>> PUBLISH done: {beats} syncs, result={'YES' if monitor.result else 'NONE'}")
    if monitor.result is None:
        print("    (the scale emits an A3 result only on a FRESH measurement — "
              "step off, let it reset, then step on barefoot to capture one)")


# ---- orchestration ----------------------------------------------------------------------
async def cmd_scan(timeout: float) -> None:
    print(f"scanning {timeout:.0f}s ...")
    for d in sorted(await BleakScanner.discover(timeout=timeout), key=lambda x: (x.name or "~")):
        print(f"  {d.address}   {d.name or '(no name)'}")


async def cmd_run(address: str, listen: bool, seconds: float, debug: bool = False) -> None:
    session = Session()
    monitor = Monitor(session, debug=debug)
    print(f"looking for {address} (step on the scale to wake it) ...")
    device = await BleakScanner.find_device_by_address(address, timeout=30.0)
    if device is None:
        print("not found while advertising. Wake the scale (step on it) and retry.")
        return
    print(f"found {device.name or '(no name)'}; connecting ...")
    async with BleakClient(device) as client:
        await client.start_notify(CHR_NOTIFY_FFB2, lambda _s, d: monitor.on_frame(CHR_NOTIFY_FFB2, d))
        await client.start_notify(CHR_NOTIFY_FFB3, lambda _s, d: monitor.on_frame(CHR_NOTIFY_FFB3, d))
        print("connected. Step on the scale.\n", flush=True)

        if listen:
            await asyncio.sleep(seconds)
        else:
            scale = Scale(client, session, debug=debug)
            print(">>> reading stabilized weight (hold still) ...", flush=True)
            weight = await read_weight(scale, monitor)
            if weight is None:
                print(">>> no stable weight read.")
                return
            print(f">>> WEIGHT {weight:.2f}kg", flush=True)
            user = select_user(weight)
            if user is not None:
                await publish(scale, monitor, user, seconds=seconds)

        for c in (CHR_NOTIFY_FFB2, CHR_NOTIFY_FFB3):
            try:
                await client.stop_notify(c)
            except Exception:
                pass
    print("disconnected.")


def main() -> None:
    ap = argparse.ArgumentParser(description="SACOMA Ultra BLE runner")
    ap.add_argument("--scan", action="store_true", help="list nearby BLE devices and exit")
    ap.add_argument("--address", help="BLE address of the scale")
    ap.add_argument("--listen", action="store_true", help="only decode; never write to the scale")
    ap.add_argument("--seconds", type=float, default=25.0, help="publish/listen duration")
    ap.add_argument("--timeout", type=float, default=8.0, help="scan timeout seconds")
    ap.add_argument("--debug", action="store_true", help="raw TX/RX frame logs instead of decoded results")
    args = ap.parse_args()

    if args.scan or not args.address:
        asyncio.run(cmd_scan(args.timeout))
        return
    asyncio.run(cmd_run(args.address, args.listen, args.seconds, args.debug))


if __name__ == "__main__":
    main()
