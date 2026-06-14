"""Minimal Windows BLE connection test for a SACOMA Ultra scale, using only the
``sacoma`` library for all encode/decode (bleak handles the radio).

Usage (PowerShell):

    py -3 scripts\ble_test.py --scan                         # find the scale's address
    py -3 scripts\ble_test.py --address AA:BB:..             # stream decoded weight + result
    py -3 scripts\ble_test.py --address AA:BB:.. --drive     # also run the sync handshake
    py -3 scripts\ble_test.py --address AA:BB:.. --seconds 45

Requires:  py -3 -m pip install bleak
"""
from __future__ import annotations

import argparse
import asyncio
import time

from bleak import BleakClient, BleakScanner

from sacoma import FrameAssembler, decode_message, frame_is_valid, encoder

SVC_FFB0 = "0000ffb0-0000-1000-8000-00805f9b34fb"
CHR_WRITE_FFB1 = "0000ffb1-0000-1000-8000-00805f9b34fb"
CHR_NOTIFY_FFB2 = "0000ffb2-0000-1000-8000-00805f9b34fb"  # A2 weight stream
CHR_NOTIFY_FFB3 = "0000ffb3-0000-1000-8000-00805f9b34fb"  # A3 result / A0,A1 control

TYPE_COUNTER, TYPE_STATUS, TYPE_RESULT = 0xA0, 0xA1, 0xA3


async def cmd_scan(timeout: float) -> None:
    print(f"scanning {timeout:.0f}s ...")
    devices = await BleakScanner.discover(timeout=timeout)
    for d in sorted(devices, key=lambda x: (x.name or "~")):
        print(f"  {d.address}   {d.name or '(no name)'}")
    print(f"{len(devices)} device(s). Re-run with --address.")


class Stream:
    """Reassembles per-characteristic frames, decodes them, and tracks the
    control events the driver needs to ack."""

    def __init__(self) -> None:
        self._asm = {CHR_NOTIFY_FFB2: FrameAssembler(), CHR_NOTIFY_FFB3: FrameAssembler()}
        self.weight = 0.0
        self.result = None
        self.control_events = 0      # bumped on each incoming A0/A3 (things to ack)

    def on_frame(self, uuid: str, data: bytearray) -> None:
        frame = bytes(data)
        if not frame_is_valid(frame):
            print(f"<- {uuid[4:8]} BAD {frame.hex()}")
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
        else:
            self.weight = m.weight_kg
            print(f"   == weight {m.weight_kg:.2f}kg ({'stable' if m.is_stabilized else 'live'})")


class Driver:
    """Replays the app's sustained sync so the scale unlocks its body-comp screen:
    a continuous BA heartbeat, BB/BD user sync, and B0 acks of the scale's A0/A3
    control frames (reply index increments per B0)."""

    def __init__(self, client: BleakClient, stream: Stream) -> None:
        self.client, self.stream = client, stream
        self.seq = 0
        self.reply = 0
        self._synced = False
        self._acked = 0

    async def _send(self, frames) -> None:
        for f in frames:
            await self.client.write_gatt_char(CHR_WRITE_FFB1, f, response=False)
        self.seq = (self.seq + 1) & 0xFF

    async def _ack(self) -> None:
        await self._send(encoder.encode_reply(self.seq, self.reply, 0))
        self.reply = (self.reply + 1) & 0xFF

    async def run(self) -> None:
        await self._ack()                                   # initial B0 after A1 hello
        while True:
            w = self.stream.weight
            if w > 0:
                await self._send(encoder.encode_sync(self.seq, w, unix_time=int(time.time())))
                if not self._synced:
                    await self._send(encoder.encode_user_list(self.seq, w))
                    await self._send(encoder.encode_other(self.seq, 0x09))
                    self._synced = True
            if self.stream.control_events > self._acked:    # ack new A0/A3 frames
                self._acked = self.stream.control_events
                await self._ack()
            await asyncio.sleep(0.4)


async def cmd_connect(address: str, drive: bool, seconds: float | None) -> None:
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
        until = f"for {seconds:.0f}s" if seconds else "until Ctrl-C"
        print(f"connected; {'DRIVING' if drive else 'listening'} {until}. Step on the scale.\n", flush=True)

        driver_task = asyncio.create_task(Driver(client, stream).run()) if drive else None
        deadline = (asyncio.get_event_loop().time() + seconds) if seconds else None
        try:
            while deadline is None or asyncio.get_event_loop().time() < deadline:
                await asyncio.sleep(0.5)
        except (KeyboardInterrupt, asyncio.CancelledError):
            pass
        finally:
            if driver_task:
                driver_task.cancel()
            for c in (CHR_NOTIFY_FFB2, CHR_NOTIFY_FFB3):
                try:
                    await client.stop_notify(c)
                except Exception:
                    pass
    print("disconnected.")


def main() -> None:
    ap = argparse.ArgumentParser(description="SACOMA Ultra BLE connection test")
    ap.add_argument("--scan", action="store_true", help="list nearby BLE devices and exit")
    ap.add_argument("--address", help="BLE address of the scale")
    ap.add_argument("--drive", action="store_true", help="run the sync handshake (unlocks the scale screen)")
    ap.add_argument("--timeout", type=float, default=8.0, help="scan timeout seconds")
    ap.add_argument("--seconds", type=float, default=None, help="run for N seconds then stop")
    args = ap.parse_args()

    if args.scan or not args.address:
        asyncio.run(cmd_scan(args.timeout))
        return
    asyncio.run(cmd_connect(args.address, args.drive, args.seconds))


if __name__ == "__main__":
    main()
