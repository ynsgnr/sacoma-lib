"""App -> Scale command frames (FFB1 writes) — the encode counterpart of
:mod:`sacoma.protocol`. Builds the ``BA/BB/B0/BD`` frames that sync time, weight
and profile so the scale shows body-composition on its own screen.

See ``docs/protocol.md`` for the full wire spec. Frame layout and checksum are
shared with the decode side: ``checksum = sum(frame[3:19]) & 0x1F``.

The ``BA_TOKEN``/``BB_RECORD2``/``BA_MID``/``BA_SEP``/``BA_TAIL`` constants are
stable across every capture for the test device; their derivation from the
profile is not yet reversed, so they are kept verbatim to stay byte-exact.
"""
from __future__ import annotations

import struct
import time as _time
from typing import List

FRAME_LEN = 20
PAYLOAD_PER_FRAME = 16

# command bytes
CMD_SYNC = 0xBA          # encodeUserInfo_BA
CMD_USER_LIST = 0xBB     # encodeUserInfoList_BB
CMD_REPLY = 0xB0         # encodeReplyPackage_B0
CMD_OTHER = 0xBD         # encodeSendOtherCMD_BD

# observed-constant payload fields (see module docstring)
BA_TOKEN = bytes.fromhex("0605cf67a5")          # user/scale token in BA + BB record 1
BA_MID = bytes((0x00, 0x78))                     # fixed field after the timestamp
BA_SEP = 0x9E                                    # record separator / suffix
BA_TAIL = 0x0F                                   # trailing byte of the BA payload
BB_RECORD2 = bytes.fromhex("0605cfb2a51a5e9e")   # second 8-byte record in BB
STABILIZED_FLAG = 0x8000                          # high bit set on the weight field


def frame_checksum(padded_payload16: bytes) -> int:
    """The 5-bit additive checksum: ``sum(payload[0:16]) & 0x1F``."""
    return sum(padded_payload16[:PAYLOAD_PER_FRAME]) & 0x1F


def build_frames(sequence: int, payload: bytes) -> List[bytes]:
    """Split ``payload`` into one or more 20-byte BLE frames.

    Each frame carries up to 16 payload bytes; the last frame is zero-padded.
    ``length`` (byte 1) is the *total* payload length in every fragment.
    """
    total = len(payload)
    frames: List[bytes] = []
    offset = 0
    frag = 0
    while True:
        chunk = payload[offset:offset + PAYLOAD_PER_FRAME]
        padded = chunk.ljust(PAYLOAD_PER_FRAME, b"\x00")
        body = bytes((sequence & 0xFF, total & 0xFF, frag)) + padded
        frames.append(body + bytes((frame_checksum(padded),)))
        offset += PAYLOAD_PER_FRAME
        frag += 1
        if offset >= total:
            break
    return frames


def _weight_field(weight_kg: float, *, stabilized: bool = True) -> bytes:
    """2-byte weight: ``round(kg*100)`` (15-bit) big-endian, bit 15 = stabilized."""
    raw = int(round(weight_kg * 100.0)) & 0x7FFF
    if stabilized:
        raw |= STABILIZED_FLAG
    return struct.pack(">H", raw)


# --- payload builders (return the reassembled payload, before framing) -------------------
def sync_payload(unix_time: int, weight_kg: float) -> bytes:
    """``0xBA`` payload: timestamp (BE u32) + stabilized weight."""
    return (bytes((CMD_SYNC,)) + struct.pack(">I", unix_time & 0xFFFFFFFF)
            + BA_MID + BA_TOKEN + _weight_field(weight_kg) + bytes((BA_SEP, BA_TAIL)))


def user_list_payload(weight_kg: float) -> bytes:
    """``0xBB`` payload: count + two 8-byte user records (record 1 carries weight)."""
    record1 = BA_TOKEN + _weight_field(weight_kg) + bytes((BA_SEP,))
    return bytes((CMD_USER_LIST, 0x02)) + record1 + BB_RECORD2


def reply_payload(reply_package_index: int = 0, state: int = 0) -> bytes:
    """``0xB0`` ack payload."""
    return bytes((CMD_REPLY, reply_package_index & 0xFF, state & 0xFF))


def other_payload(sub_cmd: int = 0x09) -> bytes:
    """``0xBD`` payload (single sub-command byte)."""
    return bytes((CMD_OTHER, sub_cmd & 0xFF))


# --- convenience: full frames for each command -------------------------------------------
def encode_sync(sequence: int, weight_kg: float, unix_time: int | None = None) -> List[bytes]:
    if unix_time is None:
        unix_time = int(_time.time())
    return build_frames(sequence, sync_payload(unix_time, weight_kg))


def encode_user_list(sequence: int, weight_kg: float) -> List[bytes]:
    return build_frames(sequence, user_list_payload(weight_kg))


def encode_reply(sequence: int, reply_package_index: int = 0, state: int = 0) -> List[bytes]:
    return build_frames(sequence, reply_payload(reply_package_index, state))


def encode_other(sequence: int, sub_cmd: int = 0x09) -> List[bytes]:
    return build_frames(sequence, other_payload(sub_cmd))
