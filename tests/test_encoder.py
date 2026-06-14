"""Byte-exact validation of the FFB1 command encoder against real device captures.

The expected frames are lifted verbatim from base/logs/frida-6.txt (a complete
measurement session). Each command is reproduced from its parameters and must
match the bytes the official app put on the wire.
"""
from sacoma import encoder


def test_checksum_is_5bit_additive():
    # sum(payload) & 0x1F, validated across 153/153 captured frames
    payload = bytes.fromhex("ba6a2e4eaa00780605cf67a5995a9e0f")
    assert encoder.frame_checksum(payload) == 0x08
    # b0 00 00 padded to 16 bytes -> sum 0xB0 -> & 0x1F = 0x10
    assert encoder.frame_checksum(bytes((0xB0,)).ljust(16, b"\x00")) == 0x10


def test_ba_sync_frame_byte_exact():
    frames = encoder.encode_sync(0x00, weight_kg=64.90, unix_time=0x6A2E4EAA)
    assert len(frames) == 1
    assert frames[0].hex() == "001000ba6a2e4eaa00780605cf67a5995a9e0f08"


def test_b0_reply_frame_byte_exact():
    frames = encoder.encode_reply(0x01, reply_package_index=0, state=0)
    assert len(frames) == 1
    assert frames[0].hex() == "010300b000000000000000000000000000000010"


def test_b0_reply_index_increments_checksum():
    # b0 00 00 -> cksum 0x10 ; b0 01 00 -> 0x11 ; b0 02 00 -> 0x12  (from capture)
    assert encoder.encode_reply(0x04, 1, 0)[0].hex() == "040300b001000000000000000000000000000011"
    assert encoder.encode_reply(0x0C, 2, 0)[0].hex() == "0c0300b002000000000000000000000000000012"


def test_bb_user_list_two_fragments_byte_exact():
    frames = encoder.encode_user_list(0x06, weight_kg=64.90)
    assert len(frames) == 2
    assert frames[0].hex() == "061200bb020605cf67a5995a9e0605cfb2a51a1f"
    assert frames[1].hex() == "0612015e9e00000000000000000000000000001c"


def test_bd_other_frame_byte_exact():
    frames = encoder.encode_other(0x07, sub_cmd=0x09)
    assert len(frames) == 1
    assert frames[0].hex() == "070200bd09000000000000000000000000000006"


def test_weight_field_stabilized_high_bit():
    # 64.90 kg -> 6490 -> 0x195A, with stabilized flag -> 0x995A
    assert encoder._weight_field(64.90).hex() == "995a"
    assert encoder._weight_field(64.90, stabilized=False).hex() == "195a"
