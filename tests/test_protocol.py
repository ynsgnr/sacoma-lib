"""Decode tests against the two real captured vectors."""
import pytest

from sacoma.protocol import FrameAssembler, decode_frame, decode_a3_result, a3_result_packet
from tests import vectors


@pytest.mark.parametrize("vec", vectors.ALL, ids=[v.name for v in vectors.ALL])
def test_reassemble_and_decode_a3(vec):
    assembler = FrameAssembler()
    measurement = None
    for frame in vec.a3_frames:
        out = decode_frame(frame, assembler)
        if out is not None:
            measurement = out
    assert measurement is not None, "A3 result never completed"
    assert measurement.weight_kg == pytest.approx(vec.weight_kg, abs=0.01)
    assert len(measurement.impedances_ohm) == 10
    for got, exp in zip(measurement.impedances_ohm, vec.impedances_ohm):
        assert got == pytest.approx(exp, abs=0.05)


@pytest.mark.parametrize("vec", vectors.ALL, ids=[v.name for v in vectors.ALL])
def test_decode_payload_directly(vec):
    # reassemble payload by hand (strip [seq,len,frag] + checksum, concat to length)
    total = vec.a3_frames[0][1]
    payload = b"".join(f[3:19] for f in vec.a3_frames)[:total]
    m = decode_a3_result(payload)
    assert m.weight_kg == pytest.approx(vec.weight_kg, abs=0.01)
    assert m.impedances_ohm == pytest.approx(vec.impedances_ohm, abs=0.05)
    assert m.impedance == pytest.approx(vec.impedances_ohm[0], abs=0.05)


def test_a3_packet_size():
    # type + marker + pad + weight(2) + pad + 10 impedances(2 each)
    assert a3_result_packet().byte_size() == 1 + 1 + 1 + 2 + 1 + 10 * 2
