"""App -> Scale command frames (FFB1 writes) — the encode counterpart of
:mod:`sacoma.protocol`. Builds the ``BA/BB/B0/BD`` frames that sync the user
profile so the scale shows body-composition on its own screen.

See ``docs/protocol.md`` for the full wire spec. Frame layout and checksum are
shared with the decode side: ``checksum = sum(frame[3:19]) & 0x1F``.

The ``BA`` profile sync (16-byte payload) was reverse-engineered from device
captures (incl. account-less "test" mode, which exposes the fields directly)::

    ba │ time(4 BE) │ 00 78 │ userId(4 BE) │ height(1) │ weight(2 BE) │ age|sex(1) │ flags(1)
                                                          0x8000=stable   bit7=male

The ``00 78`` mid field is constant in every capture, and ``flags`` only varied
with ``peopleType`` (0x0f sportman / 0x2f normal) — both kept as best-known
constants; everything else is real profile data.
"""
from __future__ import annotations

import struct
import time as _time
from typing import List, Sequence

from .models import PeopleType, Sex, UserProfile

FRAME_LEN = 20
PAYLOAD_PER_FRAME = 16

CMD_SYNC = 0xBA          # encodeUserInfo_BA      (profile sync / heartbeat)
CMD_USER_LIST = 0xBB     # encodeUserInfoList_BB  (list of profile records)
CMD_REPLY = 0xB0         # encodeReplyPackage_B0  (ack)
CMD_OTHER = 0xBD         # encodeSendOtherCMD_BD

BA_MID = bytes((0x00, 0x78))     # constant field after the timestamp
STABILIZED_FLAG = 0x8000         # high bit of the weight field


def frame_checksum(padded_payload16: bytes) -> int:
    """The 5-bit additive checksum: ``sum(payload[0:16]) & 0x1F``."""
    return sum(padded_payload16[:PAYLOAD_PER_FRAME]) & 0x1F


def build_frames(sequence: int, payload: bytes) -> List[bytes]:
    """Split ``payload`` into one or more 20-byte BLE frames (zero-padded last)."""
    total = len(payload)
    frames: List[bytes] = []
    offset = 0
    frag = 0
    while True:
        padded = payload[offset:offset + PAYLOAD_PER_FRAME].ljust(PAYLOAD_PER_FRAME, b"\x00")
        body = bytes((sequence & 0xFF, total & 0xFF, frag)) + padded
        frames.append(body + bytes((frame_checksum(padded),)))
        offset += PAYLOAD_PER_FRAME
        frag += 1
        if offset >= total:
            return frames


def _weight_field(weight_kg: float, *, stabilized: bool = True) -> bytes:
    """2-byte weight: ``round(kg*100)`` (15-bit) big-endian, bit 15 = stabilized."""
    raw = int(round(weight_kg * 100.0)) & 0x7FFF
    if stabilized and raw:
        raw |= STABILIZED_FLAG
    return struct.pack(">H", raw)


def _age_sex(profile: UserProfile) -> int:
    """One byte: low 7 bits = age, bit 7 set for male."""
    return (int(profile.age) & 0x7F) | (0x80 if profile.sex == Sex.MALE else 0x00)


def _flags(profile: UserProfile) -> int:
    """Trailing flags byte (only ``peopleType`` dependence is reversed so far)."""
    return 0x0F if profile.people_type == PeopleType.SPORTMAN else 0x2F


def _record(profile: UserProfile, weight_kg: float, user_id: int, *, stabilized: bool) -> bytes:
    """8-byte profile record shared by BA and each BB entry:
    ``userId(4) + height(1) + weight(2) + age|sex(1)``."""
    return (struct.pack(">I", user_id & 0xFFFFFFFF)
            + bytes((int(profile.height_cm) & 0xFF,))
            + _weight_field(weight_kg, stabilized=stabilized)
            + bytes((_age_sex(profile),)))


# --- payload builders (return the reassembled payload, before framing) -------------------
def sync_payload(unix_time: int, profile: UserProfile, weight_kg: float,
                 user_id: int = 0, *, stabilized: bool = True) -> bytes:
    """``0xBA`` payload: timestamp + the user's profile record + flags."""
    return (bytes((CMD_SYNC,)) + struct.pack(">I", unix_time & 0xFFFFFFFF) + BA_MID
            + _record(profile, weight_kg, user_id, stabilized=stabilized)
            + bytes((_flags(profile),)))


def user_list_payload(records: Sequence[tuple], *, stabilized: bool = True) -> bytes:
    """``0xBB`` payload: count + one 8-byte record per ``(profile, weight, user_id)``."""
    body = bytes((CMD_USER_LIST, len(records) & 0xFF))
    for profile, weight_kg, user_id in records:
        body += _record(profile, weight_kg, user_id, stabilized=stabilized)
    return body


def reply_payload(reply_package_index: int = 0, state: int = 0) -> bytes:
    """``0xB0`` ack payload."""
    return bytes((CMD_REPLY, reply_package_index & 0xFF, state & 0xFF))


def other_payload(sub_cmd: int = 0x09) -> bytes:
    """``0xBD`` payload (single sub-command byte)."""
    return bytes((CMD_OTHER, sub_cmd & 0xFF))


# --- convenience: full frames for each command -------------------------------------------
def encode_sync(sequence: int, profile: UserProfile, weight_kg: float, user_id: int = 0,
                unix_time: int | None = None, *, stabilized: bool = True) -> List[bytes]:
    if unix_time is None:
        unix_time = int(_time.time())
    return build_frames(sequence, sync_payload(unix_time, profile, weight_kg, user_id,
                                               stabilized=stabilized))


def encode_user_list(sequence: int, records: Sequence[tuple], *, stabilized: bool = True) -> List[bytes]:
    return build_frames(sequence, user_list_payload(records, stabilized=stabilized))


def encode_reply(sequence: int, reply_package_index: int = 0, state: int = 0) -> List[bytes]:
    return build_frames(sequence, reply_payload(reply_package_index, state))


def encode_other(sequence: int, sub_cmd: int = 0x09) -> List[bytes]:
    return build_frames(sequence, other_payload(sub_cmd))
