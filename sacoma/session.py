"""Transport-agnostic SACOMA protocol session.

A thin protocol layer that sits between your BLE transport and the rest of the
library. It does the two stateful, framing-level jobs so the transport code (a
script, a Home Assistant component, ...) doesn't have to:

* **decode** — reassembles incoming notification frames (per characteristic) and
  decodes the completed message into a :class:`~sacoma.models.Measurement`;
* **encode** — builds the outgoing command frames with managed sequence numbers.

It deliberately does **not** do body-composition maths or pick user profiles —
call :func:`sacoma.compute` and your own profile selection separately and wire
them together at the transport layer. No I/O happens here: feed it the bytes you
receive, write the bytes it returns.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Dict, Hashable, List, Optional, Sequence, Tuple

from . import encoder
from .models import Measurement, UserProfile
from .protocol import FrameAssembler, decode_message, frame_is_valid

# scale -> app frame types the scale expects the app to acknowledge (keeps the
# session "alive" so it unlocks its body-comp display): A0 counters and A3 result.
_CONTROL_TYPES = (0xA0, 0xA3)


@dataclass(frozen=True)
class Received:
    """Outcome of feeding one received frame to :meth:`Session.feed`."""
    measurement: Optional[Measurement]   # set when an A2 weight / A3 result completes
    control: bool                        # True for a frame that should be acked


class Session:
    """Per-connection protocol state: incoming reassembly + outgoing sequencing."""

    def __init__(self) -> None:
        self._asm: Dict[Hashable, FrameAssembler] = {}
        self._seq = 0
        self._reply = 0

    # --- decode: scale -> app ------------------------------------------------------------
    def feed(self, channel: Hashable, frame: bytes) -> Received:
        """Reassemble + decode one received 20-byte frame.

        ``channel`` is any hashable identifying the notify characteristic (so the
        weight stream and result stream reassemble independently). Bad-checksum
        frames are dropped. Returns a :class:`Received`.
        """
        frame = bytes(frame)
        if not frame_is_valid(frame):
            return Received(None, False)
        control = frame[3] in _CONTROL_TYPES
        asm = self._asm.get(channel)
        if asm is None:
            asm = self._asm[channel] = FrameAssembler()
        payload = asm.add_frame(frame)
        measurement = decode_message(payload) if payload is not None else None
        return Received(measurement, control)

    # --- encode: app -> scale (each call consumes one sequence number) --------------------
    def sync(self, profile: UserProfile, weight_kg: float, user_id: int = 0,
             *, unix_time: Optional[int] = None) -> List[bytes]:
        """``BA`` profile/weight sync (the heartbeat that drives the display)."""
        return self._emit(encoder.encode_sync(self._seq, profile, weight_kg, user_id,
                                              unix_time=unix_time))

    def user_list(self, records: Sequence[Tuple[UserProfile, float, int]]) -> List[bytes]:
        """``BB`` user-list sync: one ``(profile, weight, user_id)`` record each."""
        return self._emit(encoder.encode_user_list(self._seq, records))

    def other(self, sub_cmd: int = 0x09) -> List[bytes]:
        """``BD`` misc command."""
        return self._emit(encoder.encode_other(self._seq, sub_cmd))

    def ack(self) -> List[bytes]:
        """``B0`` reply that acknowledges the scale's control frames."""
        frames = encoder.encode_reply(self._seq, self._reply, 0)
        self._reply = (self._reply + 1) & 0xFF
        return self._emit(frames)

    def _emit(self, frames: List[bytes]) -> List[bytes]:
        self._seq = (self._seq + 1) & 0xFF
        return frames
