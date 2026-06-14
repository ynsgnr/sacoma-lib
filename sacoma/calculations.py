"""Body-composition algorithm (WLA25).

Thin adapter over :mod:`sacoma.wla25` — the bit-for-bit pure-Python port of
``ICBodyFatAlgorithmWLA25::calc`` (validated against the device library). This
module maps a decoded :class:`~sacoma.models.Measurement` + :class:`UserProfile`
onto a :class:`~sacoma.models.BodyComposition`.

Values are reported as the device reports them: float32, half-up at one decimal
(``wla25.ceil``). ``round1`` is kept as an alias for backwards compatibility.
"""
from __future__ import annotations

from . import wla25
from .models import (
    BodyComposition, Measurement, SegmentResult, Segments, UserProfile,
)

#: Device rounding (float32, half-up at one decimal). Single source of truth.
round1 = wla25.ceil


def body_mass_index(weight_kg: float, height_cm: float) -> float:
    """BMI = weight / height_m**2, rounded the way the device rounds."""
    return round1(weight_kg * 10000.0 / (height_cm * height_cm))


def _segments(raw: list) -> Segments:
    seg = {}
    for name, (fkg, fpct, mkg, mpct) in wla25.SEGMENT_SLOTS.items():
        seg[name] = SegmentResult(
            fat_mass_kg=raw[fkg], fat_percent=raw[fpct],
            muscle_mass_kg=raw[mkg], muscle_percent=raw[mpct],
        )
    return Segments(**seg)


def compute(measurement: Measurement, profile: UserProfile) -> BodyComposition:
    """Compute body composition from a measurement + profile (WLA25).

    Raises ``ValueError`` if the measurement fails the algorithm's validation
    gates, or ``NotImplementedError`` for under-18 subjects (the standard-BMI
    height tree is not ported yet).
    """
    m = wla25.calc(
        weight=measurement.weight_kg,
        height=int(profile.height_cm),
        sex=int(profile.sex),
        age=profile.age,
        people=int(profile.people_type),
        imps=measurement.impedances_ohm,
    )
    if m is None:
        raise ValueError("measurement failed the WLA25 validation gates")

    return BodyComposition(
        weight_kg=measurement.weight_kg,
        bmi=m.bmi,
        body_fat_percent=m.body_fat_percent,
        subcutaneous_fat_percent=m.subcutaneous_fat_percent,
        visceral_fat=m.visceral_fat,
        muscle_percent=m.muscle_percent,
        skeletal_muscle_percent=m.skeletal_muscle_percent,
        body_water_percent=m.body_water_percent,
        protein_percent=m.protein_percent,
        bone_mass_kg=m.bone_mass_kg,
        bmr_kcal=m.bmr_kcal,
        metabolic_age=m.metabolic_age,
        body_score=m.body_score,
        whr=0.0,  # WHR (predictWHR) not ported yet
        segments=_segments(m.raw),
        impedances_ohm=list(measurement.impedances_ohm),
    )
