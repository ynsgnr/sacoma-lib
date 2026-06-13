"""Algorithm tests against the captured vectors."""
import pytest

from sacoma.calculations import body_mass_index, round1
from sacoma.protocol import decode_a3_result
from tests import vectors


def _payload(vec):
    total = vec.a3_frames[0][1]
    return b"".join(f[3:19] for f in vec.a3_frames)[:total]


@pytest.mark.parametrize("vec", vectors.ALL, ids=[v.name for v in vectors.ALL])
def test_bmi_matches_device(vec):
    m = decode_a3_result(_payload(vec))
    # height 165 cm for both vectors
    assert body_mass_index(m.weight_kg, 165) == pytest.approx(vec.bmi, abs=0.05)


def test_round1_half_up():
    assert round1(23.79) == pytest.approx(23.8)
    assert round1(23.88) == pytest.approx(23.9)
    assert round1(10.04) == pytest.approx(10.0)
    assert round1(10.06) == pytest.approx(10.1)
