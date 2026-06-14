"""Decoder validation against real captured Scale -> App frames (frida-2 / frida-6)."""
from sacoma import protocol
from sacoma.protocol import decode_message, decode_a3_result, frame_checksum, frame_is_valid


def test_frame_checksum_matches_captures():
    # real 20-byte frames; trailing byte is the checksum
    ba = bytes.fromhex("001000ba6a2e4eaa00780605cf67a5995a9e0f08")
    a3 = bytes.fromhex("021a00a31900fd700000cd0ac20aa709d20a3b13")
    assert frame_checksum(ba) == ba[19] == 0x08
    assert frame_checksum(a3) == a3[19] == 0x13
    assert frame_is_valid(ba)
    assert not frame_is_valid(ba[:19] + b"\x00")


def test_a2_weight_stream_live_vs_stabilized():
    live = decode_message(bytes.fromhex("a2011900fd7000"))
    assert live is not None
    assert abs(live.weight_kg - 64.88) < 1e-6
    assert live.is_stabilized is False

    stable = decode_message(bytes.fromhex("a2031900fd7000"))
    assert stable.is_stabilized is True
    assert abs(stable.weight_kg - 64.88) < 1e-6


def test_a3_result_weight_and_ten_impedances():
    # frida-2 A3, reassembled (weight 65.47 kg)
    payload = bytes.fromhex("a31900ffbe0000c60b0e0aef098f0a25007f098b099608780911")
    m = decode_a3_result(payload)
    assert abs(m.weight_kg - 65.470) < 1e-6
    assert m.impedances_ohm == [19.8, 283.0, 279.9, 244.7, 259.7,
                                12.7, 244.3, 245.4, 216.8, 232.1]


def test_a3_via_message_dispatch():
    payload = bytes.fromhex("a31900ffbe0000c60b0e0aef098f0a25007f098b099608780911")
    m = decode_message(payload)
    assert len(m.impedances_ohm) == 10
