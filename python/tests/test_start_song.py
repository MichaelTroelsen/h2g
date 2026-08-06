"""Which subtune is *the tune*, and why the fidelity harness must ask.

The PSID header carries `startSong` at 0x10: the subtune a player selects when
the user selects none. Nothing in the conversion pipeline needs it -- every
subtune is emitted and none is reordered -- but the fidelity harness does,
because it compares one subtune per file and had always compared subtune 0.

For seven corpus files subtune 0 is not the tune. Samantha Fox Strip Poker is
the extreme: fourteen subtunes, `startSong` 10, and subtune 0 is a one-note
stub. The harness traced that stub against a conversion playing real music and
scored the file 5%; at its own startSong the same conversion scores 89%. Every
one of the seven scores the same or better at its header's subtune, so this is
not a tuning knob -- it was a measurement reading the wrong music.
"""
import pathlib
import sys

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[1]))

from fidelity import resolve_subtune
from h2g.sidfile import load_sid

CORPUS = pathlib.Path(r"C:/Users/mit/claude/c64server/SIDM2/SID/Hubbard_Rob")
COMMANDO = pathlib.Path(__file__).resolve().parents[2] / "Commando.sid"

# Every corpus file whose header names a default other than the first subtune,
# with its raw 1-based startSong. Pinned as a set because the harness's
# behaviour changes for exactly these files and for no others.
OFF_DEFAULT = {
    "Action_Biker": 2,
    "Delta": 12,
    "Gerry_the_Germ": 7,
    "Hollywood_or_Bust": 3,
    "Kings_of_the_Beach_ingame": 5,
    "Knucklebusters": 2,
    "Samantha_Fox_Strip_Poker": 10,
}


def test_commando_defaults_to_its_first_subtune():
    # The fixture, so this runs wherever the repo does.
    assert load_sid(str(COMMANDO)).start_song == 1
    assert resolve_subtune(COMMANDO, "auto") == 0


def test_start_song_is_one_based_and_resolves_zero_based():
    if not CORPUS.is_dir():
        return
    sid = CORPUS / "Samantha_Fox_Strip_Poker.sid"
    assert load_sid(str(sid)).start_song == 10
    # siddump's -a is 0-based; the header's field is not.
    assert resolve_subtune(sid, "auto") == 9


def test_the_off_default_files_are_exactly_these():
    if not CORPUS.is_dir():
        return
    found = {}
    for p in sorted(CORPUS.glob("*.sid")):
        s = load_sid(str(p)).start_song
        if s != 1:
            found[p.stem] = s
    assert found == OFF_DEFAULT


def test_an_explicit_subtune_still_wins():
    # `-a0` must keep meaning "subtune 0", so a measurement can be reproduced
    # against the way the report used to be generated.
    if not CORPUS.is_dir():
        return
    sid = CORPUS / "Samantha_Fox_Strip_Poker.sid"
    assert resolve_subtune(sid, 0) == 0
    assert resolve_subtune(sid, 3) == 3


def test_an_out_of_range_start_song_falls_back_to_the_first():
    # A header claiming a subtune the file does not have would otherwise send
    # the harness to trace silence and score a good conversion at zero.
    raw = bytearray(COMMANDO.read_bytes())
    raw[0x10:0x12] = (99).to_bytes(2, "big")
    tmp = pathlib.Path(__file__).with_name("_start_song_tmp.sid")
    try:
        tmp.write_bytes(bytes(raw))
        assert load_sid(str(tmp)).start_song == 1
        assert resolve_subtune(tmp, "auto") == 0
    finally:
        tmp.unlink(missing_ok=True)


def test_a_zero_start_song_falls_back_to_the_first():
    # 0 is not a legal value for a 1-based field; some rips carry it anyway.
    raw = bytearray(COMMANDO.read_bytes())
    raw[0x10:0x12] = (0).to_bytes(2, "big")
    tmp = pathlib.Path(__file__).with_name("_start_song_zero.sid")
    try:
        tmp.write_bytes(bytes(raw))
        assert load_sid(str(tmp)).start_song == 1
        assert resolve_subtune(tmp, "auto") == 0
    finally:
        tmp.unlink(missing_ok=True)


def test_an_unreadable_file_does_not_stop_the_harness():
    # resolve_subtune is called before anything else knows whether the file is
    # usable; a parse failure here must not be the thing that skips it.
    missing = pathlib.Path(__file__).with_name("_no_such_file.sid")
    assert resolve_subtune(missing, "auto") == 0


def test_conversion_does_not_consult_start_song():
    # The field is read for measurement only. If a future change makes the
    # converter branch on it, this fixture stops being byte-exact and that is
    # the wrong way to find out.
    from h2g.convert import convert

    base = convert(str(COMMANDO), log=lambda m: None)
    raw = bytearray(COMMANDO.read_bytes())
    raw[0x10:0x12] = (3).to_bytes(2, "big")
    tmp = pathlib.Path(__file__).with_name("_start_song_conv.sid")
    try:
        tmp.write_bytes(bytes(raw))
        assert convert(str(tmp), log=lambda m: None) == base
    finally:
        tmp.unlink(missing_ok=True)
