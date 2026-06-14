"""Decoder validation against real captured Scale -> App frames (frida-2 / frida-6)."""
from sacoma.protocol import (
    FrameAssembler, decode_a3_result, decode_message, frame_checksum, frame_is_valid,
)


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


# real A3 fragments use DIFFERENT, inconsistent sequence numbers (0c then 0d here),
# so reassembly must NOT key on sequence. (checksum is over payload only, not seq.)
A3_FRAG0 = bytes.fromhex("0c1a00a31900ffbe0000c60b0e0aef098f0a2518")
A3_FRAG1 = bytes.fromhex("0d1a01007f098b0996087809110000000000000c")
A3_IMPS = [19.8, 283.0, 279.9, 244.7, 259.7, 12.7, 244.3, 245.4, 216.8, 232.1]


def test_a3_two_fragment_reassembly_cross_sequence():
    asm = FrameAssembler()
    assert asm.add_frame(A3_FRAG0) is None          # frag 0 alone must NOT decode
    payload = asm.add_frame(A3_FRAG1)               # frag 1 has a different seq, must still join
    assert payload is not None
    m = decode_message(payload)
    assert m.impedances_ohm == A3_IMPS
    assert abs(m.weight_kg - 65.470) < 1e-6


def test_a3_reassembly_survives_interleaved_control_frame():
    # an A0 counter (single-frame) lands between the two A3 fragments
    asm = FrameAssembler()
    assert asm.add_frame(A3_FRAG0) is None
    assert asm.add_frame(bytes.fromhex("230300a000000000000000000000000000000000")) == bytes.fromhex("a00000")
    payload = asm.add_frame(A3_FRAG1)               # in-flight A3 not corrupted by the A0
    assert decode_message(payload).impedances_ohm == A3_IMPS


def test_weight_over_65kg_no_u16_overflow():
    # 70.268 kg = 70268 g = 0x01127c — needs the 3-byte field (u16 would wrap to ~4.73)
    a2 = decode_message(bytes.fromhex("a2031901127c00"))
    assert abs(a2.weight_kg - 70.268) < 1e-6 and a2.is_stabilized
    a3 = decode_a3_result(bytes.fromhex("a319" "01127c" "00" "c60b0e0aef098f0a25007f098b099608780911"))
    assert abs(a3.weight_kg - 70.268) < 1e-6 and len(a3.impedances_ohm) == 10
