"""sacoma — decode SACOMA Ultra BLE packets and compute body composition.

Public API::

    from sacoma import (
        SacomaScale, UserProfile, Sex, PeopleType,
        Measurement, BodyComposition,
    )

The library is pure ``bytes <-> values``: no Bluetooth, no I/O.
"""
from .models import (
    BodyComposition,
    Measurement,
    PeopleType,
    SegmentResult,
    Segments,
    Sex,
    Unit,
    UserProfile,
)
from .protocol import (
    FrameAssembler,
    decode_a3_result,
    decode_frame,
    decode_message,
    frame_checksum,
    frame_is_valid,
)
from . import encoder

__all__ = [
    "UserProfile",
    "Sex",
    "PeopleType",
    "Unit",
    "Measurement",
    "BodyComposition",
    "Segments",
    "SegmentResult",
    "FrameAssembler",
    "decode_frame",
    "decode_message",
    "decode_a3_result",
    "frame_checksum",
    "frame_is_valid",
    "encoder",
]

__version__ = "0.1.0"
