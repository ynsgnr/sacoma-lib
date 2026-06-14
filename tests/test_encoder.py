"""Byte-exact validation of the FFB1 command encoder against real device captures
(base/logs/frida-6.txt and the account-less "test mode" frida-7.txt)."""
from sacoma import encoder
from sacoma.models import PeopleType, Sex, UserProfile

# the real paired user (frida-6): height 165, male, 30, athlete, account 101044071
REAL = UserProfile(height_cm=165, age=30, sex=Sex.MALE, people_type=PeopleType.SPORTMAN)
REAL_UID = 101044071
# the account-less test user (frida-7): height 170, female, 31, normal, userId 0
TEST = UserProfile(height_cm=170, age=31, sex=Sex.FEMALE, people_type=PeopleType.NORMAL)


def test_checksum_is_5bit_additive():
    payload = bytes.fromhex("ba6a2e4eaa00780605cf67a5995a9e0f")
    assert encoder.frame_checksum(payload) == 0x08
    assert encoder.frame_checksum(bytes((0xB0,)).ljust(16, b"\x00")) == 0x10


def test_ba_sync_real_user_byte_exact():
    # frida-6: stabilized weight 64.90 kg, account 101044071
    frames = encoder.encode_sync(0x00, REAL, 64.90, REAL_UID, unix_time=0x6A2E4EAA)
    assert len(frames) == 1
    assert frames[0].hex() == "001000ba6a2e4eaa00780605cf67a5995a9e0f08"


def test_ba_sync_test_user_byte_exact():
    # frida-7 test mode: no account, weight 0 (not stabilized), height 170 / female / 31
    frames = encoder.encode_sync(0x03, TEST, 0.0, user_id=0, unix_time=0x6A2E696D, stabilized=False)
    assert frames[0].hex() == "031000ba6a2e696d007800000000aa00001f2f18"


def test_ba_fields_decode_back():
    # height byte, age|sex byte, flags byte
    p = encoder.sync_payload(0, REAL, 64.90, REAL_UID)
    assert p[11] == 165                       # height
    assert p[14] == (0x80 | 30)               # male + age 30
    assert p[15] == 0x0F                      # sportman flags
    q = encoder.sync_payload(0, TEST, 0.0, 0, stabilized=False)
    assert q[11] == 170 and q[14] == 31 and q[15] == 0x2F   # female, age 31, normal


def test_b0_reply_frame_byte_exact():
    assert encoder.encode_reply(0x01, 0, 0)[0].hex() == "010300b000000000000000000000000000000010"
    assert encoder.encode_reply(0x04, 1, 0)[0].hex() == "040300b001000000000000000000000000000011"


def test_bb_user_list_record_layout():
    # one record reuses the BA profile record (userId+height+weight+age|sex)
    frames = encoder.encode_user_list(0x06, [(REAL, 64.90, REAL_UID)])
    payload = bytes.fromhex("bb010605cf67a5995a9e")            # count=1 + record
    assert frames[0][3:3 + len(payload)] == payload


def test_bd_other_frame_byte_exact():
    assert encoder.encode_other(0x07, 0x09)[0].hex() == "070200bd09000000000000000000000000000006"


def test_weight_field_stabilized_high_bit():
    assert encoder._weight_field(64.90).hex() == "995a"
    assert encoder._weight_field(64.90, stabilized=False).hex() == "195a"
    assert encoder._weight_field(0.0).hex() == "0000"          # weight 0 carries no flag
