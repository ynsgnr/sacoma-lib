"""Body-composition algorithm (WLA25).

Turns a decoded :class:`~sacoma.models.Measurement` (weight + segmental impedances) plus a
:class:`~sacoma.models.UserProfile` into a :class:`~sacoma.models.BodyComposition`.

The model is bioelectrical impedance analysis (BIA): lean tissue conducts well (low impedance),
fat poorly (high impedance). Each metric is a regression of the form
``c0 + c1*(height**2/Z) + c2*weight + c3*age + c4*sex (+ ...)`` with min/max clamps, where
``Z`` is impedance. See ``docs/algorithm.md`` for the derivation and coefficient sources.

Values are reported rounded to one decimal, matching the device.
"""
from __future__ import annotations

import math

from .models import BodyComposition, Measurement, UserProfile


def clamp(value: float, low: float, high: float) -> float:
    return low if value < low else high if value > high else value


def round1(x: float) -> float:
    """Round to one decimal, half-up at the second decimal (the device's rounding)."""
    base = math.floor(x)
    tenths = (x - base) * 10.0
    if (tenths - math.floor(tenths)) > 0.5:
        tenths = math.floor(tenths) + 1.0
    else:
        tenths = math.floor(tenths)
    return base + tenths / 10.0


def body_mass_index(weight_kg: float, height_cm: float) -> float:
    """BMI = weight / height_m**2, rounded to one decimal."""
    return round1(weight_kg * 10000.0 / (height_cm * height_cm))


def impedance_index(height_cm: float, impedance_ohm: float) -> float:
    """height**2 / Z — the core BIA predictor of fat-free mass / body water."""
    return (height_cm * height_cm) / impedance_ohm


def compute(measurement: Measurement, profile: UserProfile) -> BodyComposition:
    """Compute body composition from a measurement + profile.

    NOTE: only BMI is implemented so far; the impedance-based metrics are being ported from
    the reference algorithm and validated metric-by-metric.
    """
    bmi = body_mass_index(measurement.weight_kg, profile.height_cm)
    raise NotImplementedError(
        "Impedance-derived metrics (body fat, muscle, water, ...) are not ported yet; "
        f"BMI is available via body_mass_index() (= {bmi})."
    )
