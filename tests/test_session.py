"""The transport-agnostic Session: incoming reassembly/decode + outgoing sequencing."""
from sacoma import Session
from sacoma.models import PeopleType, Sex, UserProfile

REAL = UserProfile(height_cm=165, age=30, sex=Sex.MALE, people_type=PeopleType.SPORTMAN)
REAL_UID = 101044071

A3_FRAG0 = bytes.fromhex("0c1a00a31900ffbe0000c60b0e0aef098f0a2518")   # seq 0c, type a3
A3_FRAG1 = bytes.fromhex("0d1a01007f098b0996087809110000000000000c")   # seq 0d (different!)


def test_feed_reassembles_result_across_sequences():
    s = Session()
    rx0 = s.feed("ffb3", A3_FRAG0)
    assert rx0.measurement is None and rx0.control is True        # A3 start: control, not done
    rx1 = s.feed("ffb3", A3_FRAG1)                                # frag 1 has a different seq
    assert rx1.measurement.impedances_ohm == [19.8, 283.0, 279.9, 244.7, 259.7,
                                              12.7, 244.3, 245.4, 216.8, 232.1]


def test_feed_decodes_a2_weight_and_drops_bad_checksum():
    s = Session()
    rx = s.feed("ffb2", bytes.fromhex("150700a2031900fae6000000000000000000001e"))
    assert abs(rx.measurement.weight_kg - 64.23) < 1e-6 and rx.measurement.is_stabilized
    assert rx.control is False
    bad = s.feed("ffb2", bytes.fromhex("150700a2031900fae6000000000000000000001f"))
    assert bad.measurement is None


def test_encode_methods_manage_sequence_numbers():
    s = Session()
    # first command uses seq 0, byte-exact to the captured BA
    assert s.sync(REAL, 64.90, REAL_UID, unix_time=0x6A2E4EAA)[0].hex() \
        == "001000ba6a2e4eaa00780605cf67a5995a9e0f08"
    # seq advances to 1; acks carry reply index 0 then 1
    assert s.ack()[0].hex() == "010300b000000000000000000000000000000010"   # seq 01 reply 00
    assert s.ack()[0].hex() == "020300b001000000000000000000000000000011"   # seq 02 reply 01
    # a two-fragment user-list keeps one sequence for both frames, then advances
    ul = s.user_list([(REAL, 64.90, REAL_UID)])
    assert ul[0][0] == 0x03
    assert s.other()[0][0] == 0x04
