"""Algorithm tests against captured device vectors and reference profiles."""
import pytest

from sacoma.calculations import (
    body_mass_index,
    body_water_percent,
    fat_mass_kg,
    muscle_percent,
    round1,
)
from tests import vectors


@pytest.mark.parametrize("vec", vectors.ALL, ids=[v.name for v in vectors.ALL])
def test_bmi(vec):
    assert body_mass_index(vec.weight_kg, vec.height_cm) == pytest.approx(vec.bmi, abs=0.05)


def test_round1_half_up():
    assert round1(23.79) == pytest.approx(23.8)
    assert round1(23.88) == pytest.approx(23.9)
    assert round1(10.04) == pytest.approx(10.0)
    assert round1(10.06) == pytest.approx(10.1)


# Derived metrics are computed from body-fat %; since they take the rounded fat % they
# inherit up to ~0.2 of rounding slack vs the device (exact once fat % is ported unrounded).
@pytest.mark.parametrize("vec", [v for v in vectors.ALL if v.body_water_percent is not None],
                         ids=lambda v: v.name)
def test_body_water_derived_from_fat(vec):
    assert body_water_percent(vec.body_fat_percent) == pytest.approx(vec.body_water_percent, abs=0.25)


@pytest.mark.parametrize("vec", [v for v in vectors.ALL if v.muscle_percent is not None],
                         ids=lambda v: v.name)
def test_muscle_derived_from_fat_and_bone(vec):
    got = muscle_percent(vec.body_fat_percent, vec.bone_mass_kg, vec.weight_kg)
    assert got == pytest.approx(vec.muscle_percent, abs=0.25)


def test_fat_mass():
    assert fat_mass_kg(15.2, 65.0) == pytest.approx(9.9, abs=0.05)
