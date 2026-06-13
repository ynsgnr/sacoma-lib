"""Immutable value objects: the "values" side of the BLE bytes <-> values contract.

Nothing here performs I/O.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from enum import IntEnum
from typing import List, Optional


class Sex(IntEnum):
    FEMALE = 0
    MALE = 1


class PeopleType(IntEnum):
    """Body model. ``SPORTMAN`` (athlete) is what the Fitdays "fit" mode uses."""

    NORMAL = 0
    SPORTMAN = 1


class Unit(IntEnum):
    KG = 0
    JIN = 1
    LB = 2
    ST = 3


@dataclass(frozen=True)
class UserProfile:
    """Inputs the algorithm needs that are not in the packet."""

    height_cm: float
    age: int
    sex: Sex
    people_type: PeopleType = PeopleType.NORMAL


@dataclass(frozen=True)
class Measurement:
    """Decoded contents of a result (A3) frame — raw, before the algorithm."""

    weight_kg: float
    impedances_ohm: List[float]   # 10 segmental impedances, ohms
    is_stabilized: bool = True

    @property
    def impedance(self) -> float:
        """Primary (whole-body / first) impedance in ohms."""
        return self.impedances_ohm[0] if self.impedances_ohm else 0.0


@dataclass(frozen=True)
class SegmentResult:
    fat_mass_kg: float
    fat_percent: float
    muscle_mass_kg: float
    muscle_percent: float


@dataclass(frozen=True)
class Segments:
    left_arm: SegmentResult
    right_arm: SegmentResult
    left_leg: SegmentResult
    right_leg: SegmentResult
    trunk: SegmentResult


@dataclass(frozen=True)
class BodyComposition:
    """Everything the scale/app reports for one measurement (WLA25)."""

    weight_kg: float
    bmi: float
    body_fat_percent: float
    subcutaneous_fat_percent: float
    visceral_fat: float
    muscle_percent: float
    skeletal_muscle_percent: float
    body_water_percent: float
    protein_percent: float
    bone_mass_kg: float
    bmr_kcal: int
    metabolic_age: float
    body_score: float
    whr: float
    segments: Optional[Segments] = None
    impedances_ohm: List[float] = field(default_factory=list)
