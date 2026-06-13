"""SACOMA Ultra BLE wire protocol: raw bytes <-> structured frames/messages.

Scale -> App notifications (FFB2 weight / FFB3 result). Every 20-byte BLE frame::

    [0]   sequence counter
    [1]   total payload length
    [2]   fragment index (0,1,...)
    [3..] payload chunk (<=16 bytes)
    [-1]  1-byte additive check

Messages longer than one frame are split across fragments and reassembled by concatenating
payload chunks until ``length`` bytes are collected.

Reassembled message payloads, by ``type`` (payload byte 0):

* ``0xA2`` real-time weight stream      — weight, big-endian, grams.
* ``0xA3`` BIA result                   — weight + **10 segmental impedances**.
* ``0xA1`` / ``0xA0`` status / counters — ignored.

A3 result layout::

    [0]    type 0xA3
    [1]    marker 0x19
    [2]    0x00
    [3-4]  weight   uint16 big-endian -> /1000 = kg
    [5]    0x00
    [6..]  imp1..imp10  uint16 big-endian each -> /10 = ohms
    [..]   trailing 0x00 padding

All multi-byte fields are big-endian (ez-packet's default).
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Dict, List, Optional

from ezpacket import Packet, Section

from .models import Measurement

FRAME_LEN = 20
NUM_IMPEDANCES = 10

TYPE_COUNTER = 0xA0
TYPE_STATUS = 0xA1
TYPE_WEIGHT = 0xA2
TYPE_RESULT = 0xA3

WEIGHT_MASK = 0x3FFFF  # weight is an 18-bit field in the A2 stream


# --- ez-packet structure of the reassembled A3 result (documentation + parser) ----------
def a3_result_packet() -> Packet:
    """ez-packet template for the A3 result message (big-endian sections)."""
    sections = [
        Section.Template(1),   # type (0xA3)
        Section.Template(1),   # marker (0x19)
        Section.Template(1),   # 0x00
        Section.Template(2),   # weight (grams)
        Section.Template(1),   # 0x00
    ]
    sections += [Section.Template(2) for _ in range(NUM_IMPEDANCES)]  # imp1..imp10
    return Packet(sections)


@dataclass
class Frame:
    sequence: int
    length: int
    fragment: int
    payload: bytes
    checksum: int

    @classmethod
    def parse(cls, data: bytes) -> "Frame":
        if len(data) != FRAME_LEN:
            raise ValueError(f"expected {FRAME_LEN}-byte frame, got {len(data)}")
        return cls(data[0], data[1], data[2], bytes(data[3:19]), data[19])


def additive_checksum(body: bytes) -> int:
    """Trailing check byte used by the FFB1 command envelope: ``sum(body[2:8]) & 0xFF``."""
    return sum(body[2:8]) & 0xFF


class FrameAssembler:
    """Stitches the scale's fragmented BLE notification frames back into whole messages.

    A long result message is split across several 20-byte frames, each carrying a
    ``[seq][len][frag]`` header. Feed every received frame; the payload chunks are buffered
    per sequence and concatenated until ``length`` bytes have arrived, at which point the
    complete message payload is returned.
    """

    def __init__(self) -> None:
        self._buf: Dict[int, bytearray] = {}
        self._len: Dict[int, int] = {}

    def add_frame(self, data: bytes) -> Optional[bytes]:
        """Add one raw frame; return the assembled message payload when complete, else ``None``."""
        frame = Frame.parse(data)
        if frame.fragment == 0:
            self._buf[frame.sequence] = bytearray(frame.payload)
            self._len[frame.sequence] = frame.length
        else:
            self._buf.setdefault(frame.sequence, bytearray()).extend(frame.payload)
        total = self._len.get(frame.sequence, frame.length)
        if len(self._buf.get(frame.sequence, b"")) >= total:
            payload = bytes(self._buf.pop(frame.sequence)[:total])
            self._len.pop(frame.sequence, None)
            return payload
        return None


def decode_message(payload: bytes) -> Optional[Measurement]:
    """Decode a reassembled message payload into a :class:`Measurement` (or ``None``)."""
    if not payload:
        return None
    mtype = payload[0]

    if mtype == TYPE_WEIGHT:
        # [type][state][marker][00][weight 18-bit BE, grams ...]
        weight_g = int.from_bytes(payload[4:7], "big") & WEIGHT_MASK
        return Measurement(weight_kg=weight_g / 1000.0, impedances_ohm=[],
                           is_stabilized=(payload[1] == 0x02))

    if mtype == TYPE_RESULT:
        return decode_a3_result(payload)

    return None  # status / counter / unknown


def decode_a3_result(payload: bytes) -> Measurement:
    """Decode an A3 result payload using the ez-packet structure.

    Section indices: 0=type, 1=marker, 2=pad, 3=weight, 4=pad, 5..14=imp1..imp10.
    """
    pkt = a3_result_packet()
    size = pkt.byte_size()
    pkt.decode(bytes(payload).ljust(size, b"\x00")[:size])
    weight_g = pkt[3].value                            # big-endian u16
    impedances: List[float] = [pkt[5 + i].value / 10.0 for i in range(NUM_IMPEDANCES)]
    return Measurement(weight_kg=weight_g / 1000.0, impedances_ohm=impedances)


def decode_frame(data: bytes, assembler: FrameAssembler) -> Optional[Measurement]:
    """Feed one raw frame; return a :class:`Measurement` when a message completes."""
    payload = assembler.add_frame(data)
    return decode_message(payload) if payload is not None else None
