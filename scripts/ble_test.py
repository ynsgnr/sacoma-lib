"""Minimal Windows BLE connection test for a SACOMA Ultra scale, using only the
``sacoma`` library for all encode/decode (bleak handles the radio).

Usage (PowerShell):

    # 1) find your scale's address
    py -3 scripts\ble_test.py --scan

    # 2) connect and stream decoded weight + body-impedance result
    py -3 scripts\ble_test.py --address AA:BB:CC:DD:EE:FF

    # 3) also push the handshake so the scale wakes its body-comp screen (experimental)
    py -3 scripts\ble_test.py --address AA:BB:CC:DD:EE:FF --drive

Requires:  py -3 -m pip install bleak
"""
from __future__ import annotations

import argparse
import asyncio
import time

from bleak import BleakClient, BleakScanner

from sacoma import FrameAssembler, decode_message, frame_is_valid, encoder

# SACOMA / icomon "General scale" GATT (FFB0 service)
SVC_FFB0 = "0000ffb0-0000-1000-8000-00805f9b34fb"
CHR_WRITE_FFB1 = "0000ffb1-0000-1000-8000-00805f9b34fb"
CHR_NOTIFY_FFB2 = "0000ffb2-0000-1000-8000-00805f9b34fb"  # A2 weight stream
CHR_NOTIFY_FFB3 = "0000ffb3-0000-1000-8000-00805f9b34fb"  # A3 result / A1,A0 status


async def cmd_scan(timeout: float) -> None:
    print(f"scanning {timeout:.0f}s ...")
    devices = await BleakScanner.discover(timeout=timeout)
    for d in sorted(devices, key=lambda x: (x.name or "~")):
        print(f"  {d.address}   rssi={getattr(d, 'rssi', '?'):>4}   {d.name or '(no name)'}")
    print(f"{len(devices)} device(s). Look for your scale, then re-run with --address.")


class Stream:
    """Reassembles per-characteristic frames and prints decoded measurements."""

    def __init__(self) -> None:
        self._asm = {CHR_NOTIFY_FFB2: FrameAssembler(), CHR_NOTIFY_FFB3: FrameAssembler()}
        self.last_weight = None
        self.last_result = None

    def on_frame(self, uuid: str, data: bytearray) -> None:
        frame = bytes(data)
        tag = "  ok" if frame_is_valid(frame) else " BAD"
        print(f"<- {uuid[4:8]} {tag} {frame.hex()}")
        asm = self._asm.get(uuid.lower())
        if asm is None:
            return
        payload = asm.add_frame(frame)
        if payload is None:
            return
        m = decode_message(payload)
        if m is None:
            return
        if m.impedances_ohm:
            self.last_result = m
            print(f"   == RESULT  weight={m.weight_kg:.2f} kg  imps={m.impedances_ohm}")
        else:
            self.last_weight = m.weight_kg
            flag = "stable" if m.is_stabilized else "live"
            print(f"   == weight {m.weight_kg:.2f} kg ({flag})")


async def drive_handshake(client: BleakClient, weight_kg: float) -> None:
    """Replay the app's B0/BA/BB/BD handshake so the scale shows its body-comp screen.

    Experimental: the exact trigger sequence is still being characterised. Frames
    are byte-exact to the captured protocol; sequence numbers increment per write.
    """
    seq = 0

    async def send(frames):
        nonlocal seq
        for fr in frames:
            print(f"-> ffb1 {fr.hex()}")
            await client.write_gatt_char(CHR_WRITE_FFB1, fr, response=False)
            await asyncio.sleep(0.05)
        seq = (seq + 1) & 0xFF

    now = int(time.time())
    await send(encoder.encode_reply(seq, reply_package_index=0, state=0))
    await send(encoder.encode_sync(seq, weight_kg, unix_time=now))
    await send(encoder.encode_user_list(seq, weight_kg))
    await send(encoder.encode_other(seq, sub_cmd=0x09))
    print("handshake sent.")


async def cmd_connect(address: str, drive: bool) -> None:
    stream = Stream()
    print(f"connecting to {address} ...")
    async with BleakClient(address) as client:
        print(f"connected={client.is_connected}; subscribing to FFB2/FFB3 ...")
        await client.start_notify(CHR_NOTIFY_FFB2, lambda _s, d: stream.on_frame(CHR_NOTIFY_FFB2, d))
        await client.start_notify(CHR_NOTIFY_FFB3, lambda _s, d: stream.on_frame(CHR_NOTIFY_FFB3, d))
        print("subscribed. Step on the scale. Ctrl-C to stop.\n")

        try:
            while True:
                await asyncio.sleep(1.0)
                if drive and stream.last_result is not None:
                    await drive_handshake(client, stream.last_result.weight_kg)
                    drive = False  # once
        except (KeyboardInterrupt, asyncio.CancelledError):
            pass
        finally:
            for c in (CHR_NOTIFY_FFB2, CHR_NOTIFY_FFB3):
                try:
                    await client.stop_notify(c)
                except Exception:
                    pass
    print("disconnected.")


def main() -> None:
    ap = argparse.ArgumentParser(description="SACOMA Ultra BLE connection test")
    ap.add_argument("--scan", action="store_true", help="list nearby BLE devices and exit")
    ap.add_argument("--address", help="BLE address of the scale to connect to")
    ap.add_argument("--drive", action="store_true",
                    help="after a result arrives, push the handshake (experimental)")
    ap.add_argument("--timeout", type=float, default=8.0, help="scan timeout seconds")
    args = ap.parse_args()

    if args.scan or not args.address:
        asyncio.run(cmd_scan(args.timeout))
        return
    asyncio.run(cmd_connect(args.address, args.drive))


if __name__ == "__main__":
    main()
