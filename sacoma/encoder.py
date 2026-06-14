"""App -> Scale command frames (FFB1 writes) — the encode counterpart of
:mod:`sacoma.protocol`.

Like the decode side, the wire layout is declared as ``ez-packet`` ``Section``
lists, so the structure definition *is* the documentation. Each ``Section`` is a
big-endian field of a fixed byte width; ``Packet([...]).to_bytes()`` lays them
out in order. See ``docs/protocol.md`` for the prose spec.

The ``BA`` profile sync (16-byte payload) was reverse-engineered from device
captures (incl. account-less "test" mode, which exposes the fields directly)::

    ba │ time(4) │ 00 78 │ userId(4) │ height(1) │ weight(2) │ age|sex(1) │ flags(1)
                                                   0x8000=stable   bit7=male

``00 78`` is constant in every capture; ``flags`` only varied with ``peopleType``
(0x0f sportman / 0x2f normal) — both kept as best-known constants, everything
else is real profile data. Frame envelope and checksum are shared with the
decode side: ``checksum = sum(frame[3:19]) & 0x1F``.
"""
from __future__ import annotations

import time as _time
from typing import List, Optional, Sequence, Tuple

from ezpacket import Packet, Section

from .models import PeopleType, Sex, UserProfile

FRAME_LEN = 20
PAYLOAD_PER_FRAME = 16

CMD_SYNC = 0xBA          # encodeUserInfo_BA      (profile sync / heartbeat)
CMD_USER_LIST = 0xBB     # encodeUserInfoList_BB  (list of profile records)
CMD_REPLY = 0xB0         # encodeReplyPackage_B0  (ack)
CMD_OTHER = 0xBD         # encodeSendOtherCMD_BD

BA_MID = 0x0078          # constant field after the timestamp
STABILIZED_FLAG = 0x8000  # high bit of the weight field


def frame_checksum(padded_payload16: bytes) -> int:
    """The 5-bit additive checksum: ``sum(payload[0:16]) & 0x1F``."""
    return sum(padded_payload16[:PAYLOAD_PER_FRAME]) & 0x1F


def _weight_raw(weight_kg: float, *, stabilized: bool = True) -> int:
    """15-bit weight (``round(kg*100)``) with bit 15 set when stabilized."""
    raw = int(round(weight_kg * 100.0)) & 0x7FFF
    if stabilized and raw:
        raw |= STABILIZED_FLAG
    return raw


def _weight_field(weight_kg: float, *, stabilized: bool = True) -> bytes:
    """2-byte big-endian weight field."""
    return Section(_weight_raw(weight_kg, stabilized=stabilized), 2).to_bytes()


def _age_sex(profile: UserProfile) -> int:
    """One byte: low 7 bits = age, bit 7 set for male."""
    return (int(profile.age) & 0x7F) | (0x80 if profile.sex == Sex.MALE else 0x00)


def _flags(profile: UserProfile) -> int:
    """Trailing flags byte (only ``peopleType`` dependence is reversed so far)."""
    return 0x0F if profile.people_type == PeopleType.SPORTMAN else 0x2F


def _record(profile: UserProfile, weight_kg: float, user_id: int,
            *, stabilized: bool) -> List[Section]:
    """The 8-byte profile record shared by BA and each BB entry."""
    return [
        Section(user_id & 0xFFFFFFFF, 4),                   # userId (BE u32)
        Section(int(profile.height_cm) & 0xFF, 1),          # height (cm)
        Section(_weight_raw(weight_kg, stabilized=stabilized), 2),  # weight (0x8000=stable)
        Section(_age_sex(profile), 1),                      # age | sex<<7
    ]


# --- payload definitions (declarative; .to_bytes() gives the reassembled payload) --------
def sync_payload(unix_time: int, profile: UserProfile, weight_kg: float,
                 user_id: int = 0, *, stabilized: bool = True) -> bytes:
    """``0xBA`` payload: timestamp + the user's profile record + flags."""
    return Packet([
        Section(CMD_SYNC, 1),                               # command 0xBA
        Section(unix_time & 0xFFFFFFFF, 4),                 # timestamp (BE u32)
        Section(BA_MID, 2),                                 # constant 0x0078
        *_record(profile, weight_kg, user_id, stabilized=stabilized),
        Section(_flags(profile), 1),                        # peopleType flags
    ]).to_bytes()


def user_list_payload(records: Sequence[Tuple[UserProfile, float, int]],
                      *, stabilized: bool = True) -> bytes:
    """``0xBB`` payload: count + one 8-byte record per ``(profile, weight, user_id)``."""
    sections = [Section(CMD_USER_LIST, 1), Section(len(records) & 0xFF, 1)]
    for profile, weight_kg, user_id in records:
        sections += _record(profile, weight_kg, user_id, stabilized=stabilized)
    return Packet(sections).to_bytes()


def reply_payload(reply_package_index: int = 0, state: int = 0) -> bytes:
    """``0xB0`` ack payload."""
    return Packet([
        Section(CMD_REPLY, 1),
        Section(reply_package_index & 0xFF, 1),
        Section(state & 0xFF, 1),
    ]).to_bytes()


def other_payload(sub_cmd: int = 0x09) -> bytes:
    """``0xBD`` payload (single sub-command byte)."""
    return Packet([Section(CMD_OTHER, 1), Section(sub_cmd & 0xFF, 1)]).to_bytes()


# --- framing -----------------------------------------------------------------------------
def build_frames(sequence: int, payload: bytes) -> List[bytes]:
    """Split ``payload`` into one or more 20-byte BLE frames (zero-padded last).

    Frame = ``[seq][len][frag][16 payload bytes][checksum]``; ``len`` is the
    *total* payload length in every fragment.
    """
    total = len(payload)
    frames: List[bytes] = []
    offset = 0
    frag = 0
    while True:
        chunk = payload[offset:offset + PAYLOAD_PER_FRAME].ljust(PAYLOAD_PER_FRAME, b"\x00")
        frames.append(Packet([
            Section(sequence & 0xFF, 1),                # sequence
            Section(total & 0xFF, 1),                   # total payload length
            Section(frag, 1),                           # fragment index
            Section(int.from_bytes(chunk, "big"), PAYLOAD_PER_FRAME),  # payload chunk
            Section(frame_checksum(chunk), 1),          # checksum = sum(payload) & 0x1F
        ]).to_bytes())
        offset += PAYLOAD_PER_FRAME
        frag += 1
        if offset >= total:
            return frames


# --- convenience: full frames for each command -------------------------------------------
def encode_sync(sequence: int, profile: UserProfile, weight_kg: float, user_id: int = 0,
                unix_time: Optional[int] = None, *, stabilized: bool = True) -> List[bytes]:
    if unix_time is None:
        unix_time = int(_time.time())
    return build_frames(sequence, sync_payload(unix_time, profile, weight_kg, user_id,
                                               stabilized=stabilized))


def encode_user_list(sequence: int, records: Sequence[Tuple[UserProfile, float, int]],
                     *, stabilized: bool = True) -> List[bytes]:
    return build_frames(sequence, user_list_payload(records, stabilized=stabilized))


def encode_reply(sequence: int, reply_package_index: int = 0, state: int = 0) -> List[bytes]:
    return build_frames(sequence, reply_payload(reply_package_index, state))


def encode_other(sequence: int, sub_cmd: int = 0x09) -> List[bytes]:
    return build_frames(sequence, other_payload(sub_cmd))
