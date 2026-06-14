"""Windows BLE runner for a SACOMA Ultra scale, using only the ``sacoma`` library
for encode/decode (bleak handles the radio).

Flow: connect -> read the stabilized weight -> pick the matching user profile from
WEIGHT_PROFILES -> publish that profile so the scale shows its body-comp screen.

    py -3 scripts\ble_test.py --scan
    py -3 scripts\ble_test.py --address AA:BB:..            # read weight + auto-select + publish
    py -3 scripts\ble_test.py --address AA:BB:.. --listen   # just decode, no writes

Requires:  py -3 -m pip install bleak
"""
from __future__ import annotations

import argparse
import asyncio
import time
from dataclasses import dataclass
from typing import List, Optional, Tuple

from bleak import BleakClient, BleakScanner

from sacoma import FrameAssembler, decode_message, frame_is_valid, encoder, compute
from sacoma.models import PeopleType, Sex, UserProfile

CHR_WRITE_FFB1 = "0000ffb1-0000-1000-8000-00805f9b34fb"
CHR_NOTIFY_FFB2 = "0000ffb2-0000-1000-8000-00805f9b34fb"  # A2 weight stream
CHR_NOTIFY_FFB3 = "0000ffb3-0000-1000-8000-00805f9b34fb"  # A3 result / A0,A1 control
TYPE_COUNTER, TYPE_RESULT = 0xA0, 0xA3


@dataclass
class User:
    """A user model: the account id (0 = none/test) + the profile the scale needs."""
    user_id: int
    profile: UserProfile


# ---- weight range -> user profile -------------------------------------------------------
# Edit for your household. First matching range wins. (kg, inclusive)
# Split around ~65 kg so a normal weigh-in picks USER_A and a +10 kg hold picks USER_B.
WEIGHT_PROFILES: List[Tuple[float, float, User]] = [
    (62.0, 67.0, User(101044071, UserProfile(height_cm=165, age=30, sex=Sex.MALE,
                                             people_type=PeopleType.SPORTMAN))),  # ~65 kg normal
    (67.0, 75.0, User(0, UserProfile(height_cm=170, age=31, sex=Sex.FEMALE,
                                     people_type=PeopleType.NORMAL))),           # ~75 kg (+10) test
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


# ---- BLE plumbing -----------------------------------------------------------------------
class Stream:
    """Reassembles per-characteristic frames, decodes them, and tracks what the
    driver needs: the latest (stabilized) weight and incoming control events."""

    def __init__(self) -> None:
        self._asm = {CHR_NOTIFY_FFB2: FrameAssembler(), CHR_NOTIFY_FFB3: FrameAssembler()}
        self.weight = 0.0
        self.stable_weight: Optional[float] = None
        self.result = None
        self.control_events = 0          # bumped on each incoming A0/A3 (things to ack)

    def on_frame(self, uuid: str, data: bytearray) -> None:
        frame = bytes(data)
        if not frame_is_valid(frame):
            return
        if frame[3] in (TYPE_COUNTER, TYPE_RESULT):
            self.control_events += 1
        payload = self._asm[uuid.lower()].add_frame(frame) if uuid.lower() in self._asm else None
        if payload is None:
            return
        m = decode_message(payload)
        if m is None:
            return
        if m.impedances_ohm:
            self.result = m
            print(f"   == RESULT weight={m.weight_kg:.2f}kg imps={m.impedances_ohm}")
            user = select_user(m.weight)
            if user is not None:
                print(f" Calculation Result = {compute(m, user)}")
        else:
            self.weight = m.weight_kg
            if m.is_stabilized:
                self.stable_weight = m.weight_kg
            print(f"   == weight {m.weight_kg:.2f}kg ({'stable' if m.is_stabilized else 'live'})")


class Conn:
    """A connected scale: owns the rolling sequence / reply counters and writes FFB1."""

    def __init__(self, client: BleakClient) -> None:
        self.client = client
        self.seq = 0
        self.reply = 0

    async def send(self, frames) -> None:
        for f in frames:
            await self.client.write_gatt_char(CHR_WRITE_FFB1, f, response=False)
        self.seq = (self.seq + 1) & 0xFF

    async def ack(self) -> None:
        await self.send(encoder.encode_reply(self.seq, self.reply, 0))
        self.reply = (self.reply + 1) & 0xFF


# ---- the two functions ------------------------------------------------------------------
async def read_weight(conn: Conn, stream: Stream, *, timeout: float = 60.0,
                      settle: int = 8, min_kg: float = 20.0) -> Optional[float]:
    """Wait for the live weight to settle at its peak and return it (kg).

    The weight climbs as you step on, so we track the running peak: each time a
    new higher stabilized value appears the settle counter resets; only when the
    value holds (±0.05 kg) at the peak for ``settle`` reads (and is >= ``min_kg``)
    do we trust it. Acks control frames meanwhile so the scale stays engaged.
    """
    deadline = asyncio.get_event_loop().time() + timeout
    acked = 0
    last: Optional[float] = None
    peak = 0.0
    count = 0
    while asyncio.get_event_loop().time() < deadline:
        if stream.control_events > acked:
            acked = stream.control_events
            await conn.ack()
        w = stream.stable_weight
        if w is not None and w >= min_kg:
            if w > peak + 0.05:                       # still climbing -> new peak
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
    return stream.stable_weight or (stream.weight or None)


async def publish(conn: Conn, stream: Stream, user: User, *, seconds: float = 20.0) -> None:
    """Drive the scale to display body-comp for ``user``: a sustained BA profile
    heartbeat plus B0 acks of the scale's control frames (this is what unlocks
    the screen — a one-shot is not enough)."""
    print(f">>> PUBLISH {_describe(user)}  (BA heartbeat + B0 acks for {seconds:.0f}s)", flush=True)
    deadline = asyncio.get_event_loop().time() + seconds
    acked = stream.control_events
    beats = 0
    while asyncio.get_event_loop().time() < deadline:
        weight = stream.stable_weight or stream.weight
        if weight and weight > 0:
            frames = encoder.encode_sync(conn.seq, user.profile, weight,
                                         user.user_id, unix_time=int(time.time()))
            await conn.send(frames)
            beats += 1
            if beats % 5 == 1:
                print(f"   [publish] BA #{beats} weight={weight:.2f} -> {frames[0].hex()}")
        if stream.control_events > acked:
            acked = stream.control_events
            await conn.ack()
        await asyncio.sleep(0.4)
    print(f">>> PUBLISH done ({beats} BA frames sent)")


# ---- orchestration ----------------------------------------------------------------------
async def cmd_scan(timeout: float) -> None:
    print(f"scanning {timeout:.0f}s ...")
    for d in sorted(await BleakScanner.discover(timeout=timeout), key=lambda x: (x.name or "~")):
        print(f"  {d.address}   {d.name or '(no name)'}")


async def cmd_run(address: str, listen: bool, seconds: float) -> None:
    stream = Stream()
    print(f"looking for {address} (step on the scale to wake it) ...")
    device = await BleakScanner.find_device_by_address(address, timeout=30.0)
    if device is None:
        print("not found while advertising. Wake the scale (step on it) and retry.")
        return
    print(f"found {device.name or '(no name)'}; connecting ...")
    async with BleakClient(device) as client:
        await client.start_notify(CHR_NOTIFY_FFB2, lambda _s, d: stream.on_frame(CHR_NOTIFY_FFB2, d))
        await client.start_notify(CHR_NOTIFY_FFB3, lambda _s, d: stream.on_frame(CHR_NOTIFY_FFB3, d))
        print("connected. Step on the scale.\n", flush=True)

        if listen:
            await asyncio.sleep(seconds)
        else:
            conn = Conn(client)
            print(">>> reading stabilized weight (hold still) ...", flush=True)
            weight = await read_weight(conn, stream)
            if weight is None:
                print(">>> no stable weight read.")
                return
            print(f">>> WEIGHT {weight:.2f}kg", flush=True)
            user = select_user(weight)
            if user is not None:
                await publish(conn, stream, user, seconds=seconds)

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
    args = ap.parse_args()

    if args.scan or not args.address:
        asyncio.run(cmd_scan(args.timeout))
        return
    asyncio.run(cmd_run(args.address, args.listen, args.seconds))


if __name__ == "__main__":
    main()
