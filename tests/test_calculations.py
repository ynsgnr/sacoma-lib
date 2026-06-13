"""WLA25 algorithm tests: the pure-Python port vs captured device values.

Bit-for-bit equivalence to the device library is verified separately against the
arm64 oracle (see base/raw/validate_*.py); these tests pin the port to the
captured/reference vectors and exercise the public ``compute`` API.
"""
import pytest

from sacoma.calculations import body_mass_index, compute, round1
from sacoma.models import Measurement, PeopleType, Sex, UserProfile
from tests import vectors

ADULTS = [v for v in vectors.ALL if v.age >= 18]

# expected fields and the tolerance to use (device values are float32, app-rounded)
_TOL = {"bmr_kcal": 1.0, "metabolic_age": 1.0}
_FIELDS = [
    "bmi", "body_fat_percent", "muscle_percent", "subcutaneous_fat_percent",
    "visceral_fat", "bone_mass_kg", "body_water_percent", "protein_percent",
    "skeletal_muscle_percent", "bmr_kcal", "metabolic_age", "body_score",
]


def _inputs(vec):
    meas = Measurement(weight_kg=vec.weight_kg, impedances_ohm=vec.impedances_ohm)
    prof = UserProfile(height_cm=vec.height_cm, age=vec.age, sex=Sex(vec.sex),
                       people_type=PeopleType(vec.people_type))
    return meas, prof


@pytest.mark.parametrize("vec", vectors.ALL, ids=[v.name for v in vectors.ALL])
def test_bmi(vec):
    assert body_mass_index(vec.weight_kg, vec.height_cm) == pytest.approx(vec.bmi, abs=0.05)


def test_round1_half_up():
    assert round1(23.79) == pytest.approx(23.8)
    assert round1(23.88) == pytest.approx(23.9)
    assert round1(10.04) == pytest.approx(10.0)
    assert round1(10.06) == pytest.approx(10.1)


@pytest.mark.parametrize("vec", ADULTS, ids=[v.name for v in ADULTS])
def test_compute_matches_device(vec):
    bc = compute(*_inputs(vec))
    for field in _FIELDS:
        exp = getattr(vec, field, None)
        if exp is None:
            continue
        # 0.2 absorbs app display rounding (e.g. bone 3.6 shown as 3.7)
        assert getattr(bc, field) == pytest.approx(exp, abs=_TOL.get(field, 0.2)), \
            f"{vec.name}.{field}"


def test_segment_fat_masses_exact():
    """Full-precision segment fat masses from the EXACT device capture."""
    bc = compute(*_inputs(vectors.EXACT))
    got = [bc.segments.left_arm.fat_mass_kg, bc.segments.right_arm.fat_mass_kg,
           bc.segments.left_leg.fat_mass_kg, bc.segments.right_leg.fat_mass_kg,
           bc.segments.trunk.fat_mass_kg]
    assert got == pytest.approx(vectors.EXACT.segment_fat_kg, abs=1e-6)


def test_segment_muscle_masses_exact():
    bc = compute(*_inputs(vectors.EXACT))
    got = [bc.segments.left_arm.muscle_mass_kg, bc.segments.right_arm.muscle_mass_kg,
           bc.segments.left_leg.muscle_mass_kg, bc.segments.right_leg.muscle_mass_kg,
           bc.segments.trunk.muscle_mass_kg]
    assert got == pytest.approx(vectors.EXACT.segment_muscle_kg, abs=1e-6)


def test_under_18_not_supported():
    prof = UserProfile(height_cm=160, age=15, sex=Sex.MALE)
    meas = Measurement(weight_kg=55.0, impedances_ohm=vectors.EXACT.impedances_ohm)
    with pytest.raises(NotImplementedError):
        compute(meas, prof)
