"""The digi engine's no-release flag: bit 5 of a $C0-$FF duration byte.

`_build_raw_pattern_digi` used to drop it, so every note the player lands on
with the gate still open was re-struck. Read in Pygmies_Revenge:

    11FE  LDA $164E,X / STA $1651,X     ; the event's byte, latched
    1204  AND #$20 / BNE $1212          ; bit 5 -> the gate is NOT closed at
    120D  LDA #$FE / STA $165D,X        ;   the note's end (else it is)
    1190  LDA $1651,X / AND #$20        ; the next note start reads the latch
    11AC  BNE $11E9                     ;   and skips pulse, AD and SR

so an event with the flag ties into the note after it: a frequency change and
no attack, which is `CMD_TONEPORTA 00`. Pygmies voice 0 played 302 attacks
against the original's 233 over 180 s, the surplus being exactly these.
"""
import json
import pathlib
import sys

import pytest

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[1]))

from corpus import CORPUS, needs_corpus  # noqa: E402
from h2g import detect  # noqa: E402
from h2g.convert import convert  # noqa: E402
from h2g.patterns import (CMD_TONEPORTA, DIGI_END, DIGI_TIE,  # noqa: E402
                          GT_END_PATTERN, GT_KEYOFF, GT_NO_NOTE,
                          _build_raw_pattern_digi, decode_entry,
                          digi_tie_family)
from h2g.sidfile import load_sid  # noqa: E402

PAD = [0x00, 0x00]          # _build_raw_pattern_digi rejects addr <= 1
TIED = 0xE1                 # duration prefix, wait 1, bit 5
PLAIN = 0xC1                # duration prefix, wait 1
TIED0 = 0xE0                # bit 5 but wait 0: no hold frame to latch it on
SLIDE = [0x82, 0x00, 0x20]  # +$20 a frame -> CMD_PORTAUP 8
END = [GT_END_PATTERN, 0x00, 0x00, 0x00]


def _decode(stream, tie=True, slides=False, exits=None):
    return _build_raw_pattern_digi(bytes(PAD + stream + [DIGI_END]),
                                   len(PAD), tie=tie, slides=slides,
                                   exits_tied=exits)


def _cmds(events):
    return [(events[k], events[k + 2], events[k + 3])
            for k in range(0, len(events), 4)]


def test_the_flag_is_bit_5_of_the_duration_byte():
    assert DIGI_TIE == 0x20 and TIED == 0xC0 | DIGI_TIE | 1


def test_a_note_after_a_flagged_event_ties():
    rows = _cmds(_decode([TIED, 0x17, PLAIN, 0x23]))
    assert rows[0] == (0x77, 0, 0)                          # the first attacks
    assert rows[1][0] == GT_NO_NOTE
    assert rows[2] == (0x83, CMD_TONEPORTA, 0x00)           # the tie
    assert rows[3][0] == GT_NO_NOTE


def test_the_option_off_is_the_old_stream():
    off = _decode([TIED, 0x17, PLAIN, 0x23], tie=False)
    assert all(c == 0 for _, c, _ in _cmds(off))
    assert len(off) == len(_decode([TIED, 0x17, PLAIN, 0x23]))


def test_an_unflagged_event_does_not_tie_the_next_note():
    rows = _cmds(_decode([PLAIN, 0x17, PLAIN, 0x23]))
    assert rows[2] == (0x83, 0, 0)


def test_a_flagged_event_with_no_hold_frame_does_not_tie():
    # wait 0: the latch ($11FE) runs on a hold frame and there is none, so the
    # flag is never read at the next note start and the gate-off test never
    # runs either. Left as the old reading rather than guessed.
    rows = _cmds(_decode([TIED0, 0x17, PLAIN, 0x23]))
    assert rows[1] == (0x83, 0, 0)


def test_a_rest_ends_the_tie():
    # $1184 closes the gate on its own, so the note after a rest attacks.
    rows = _cmds(_decode([TIED, 0x17, 0x60, PLAIN, 0x23]))
    assert rows[2][0] == GT_KEYOFF
    assert rows[4] == (0x83, 0, 0)
    assert rows[2][1:] == (0, 0)


def test_the_duration_byte_is_sticky_so_the_flag_is_too():
    # One prefix governs every following event: the second and third notes
    # carry the flag as well, so the second AND third are tied.
    rows = _cmds(_decode([TIED, 0x17, 0x23, 0x2F]))
    notes = [r for r in rows if r[0] not in (GT_NO_NOTE, GT_END_PATTERN)]
    assert [n[1] for n in notes] == [0, CMD_TONEPORTA, CMD_TONEPORTA]


def test_a_slide_that_follows_a_tied_note_keeps_its_hold_row():
    # One command column: row 0 ties and the HOLD row carries the slide, as
    # the classic decoder splits it.
    ev = _decode([TIED, 0x17, PLAIN] + SLIDE + [0x23], slides=True)
    rows = _cmds(ev)
    assert rows[2] == (0x83, CMD_TONEPORTA, 0x00)
    assert rows[3] == (GT_NO_NOTE, 1, 8)


def test_a_slide_with_no_hold_row_keeps_the_slide_and_not_the_tie():
    ev = _decode([TIED, 0x17, 0xC0] + SLIDE + [0x23], slides=True)
    rows = _cmds(ev)
    assert rows[2] == (0x83, 1, 8)


def test_the_exit_state_follows_the_last_event():
    for stream, tied in (([TIED, 0x17], True), ([PLAIN, 0x17], False),
                         ([TIED0, 0x17], False), ([TIED, 0x60], False)):
        exits = []
        _decode(stream, exits=exits)
        assert exits == [tied], stream
        exits = []
        _decode(stream, tie=False, exits=exits)
        assert exits == [False], stream


# --- the player-shape guard --------------------------------------------------

HOLD = bytes.fromhex("BD4E16 9D5116 2920 D00A BD4816 D005 A9FE 9D5D16")
START = bytes.fromhex("BD5116 2920 8D8916 BD5A16 8E6216 0A0A0A0A AA")
JUNK = bytes([0xEA] * 8)


def test_the_guard_wants_both_readers_on_one_cell():
    assert digi_tie_family(JUNK + HOLD + JUNK + START + JUNK)
    # the start block reads a DIFFERENT cell than the hold block latches
    other = bytes.fromhex("BD5216") + START[3:]
    assert not digi_tie_family(JUNK + HOLD + JUNK + other + JUNK)
    assert not digi_tie_family(JUNK + HOLD + JUNK)
    assert not digi_tie_family(JUNK + START + JUNK)


# --- the corpus -------------------------------------------------------------

# decode_entry over every pattern of the nine digi files, tie on against off:
# how many rows gained `CMD_TONEPORTA 00`, and how many patterns end tied.
# MEASURED at 4c9dab5 plus this change; Powerplay and One_on_One carry the
# flag on 0 and 1 events and gain nothing.
DIGI_TIES = {
    "After_8": (328, 6),
    "Kings_of_the_Beach_intro": (12, 0),
    "Mr_Meaner": (123, 2),
    "Off_the_Cuff": (109, 1),
    "One_on_One_Jordan_vs_Bird": (0, 0),
    "Powerplay_Hockey_USA_vs_USSR": (0, 0),
    "Pygmies_Revenge": (102, 1),
    "Rikky": (201, 3),
    "Rock_Tells_the_Tale": (65, 0),
}


def _load(name):
    sid = load_sid(str(CORPUS / (name + ".sid")))
    return sid, detect.detect(sid, lambda x: None)


@needs_corpus
@pytest.mark.parametrize("name", sorted(DIGI_TIES))
def test_the_nine_digi_files_carry_both_readers_of_the_flag(name):
    sid, det = _load(name)
    assert det.pattern_dialect == "digi"
    assert digi_tie_family(sid.data)


@needs_corpus
def test_a_classic_player_is_not_in_the_family():
    sid, _ = _load("Commando")
    assert not digi_tie_family(sid.data)


@needs_corpus
@pytest.mark.parametrize("name", sorted(DIGI_TIES))
def test_tie_rows_per_digi_file(name):
    sid, det = _load(name)
    ties = exits_tied = 0
    for i in range(det.pattern_used + 1):
        off = decode_entry(sid, det, i, tie=False)
        ex = []
        on = decode_entry(sid, det, i, tie=True, exits_tied=ex)
        if off is None or on is None:
            continue
        assert len(on) == len(off)
        for k in range(0, len(off), 4):
            if on[k:k + 4] != off[k:k + 4]:
                # only the command column moves, and only to a tie
                assert on[k:k + 2] == off[k:k + 2]
                assert on[k + 2:k + 4] == [CMD_TONEPORTA, 0x00]
                ties += 1
        exits_tied += bool(ex and ex[0])
    assert (ties, exits_tied) == DIGI_TIES[name]


@needs_corpus
def test_the_tie_reaches_pygmies_conversion():
    # Under the song's own preset the option is on: tie rows are in the .sng.
    from fidelity import _preset_opts
    from songview import parse_sng
    root = pathlib.Path(__file__).resolve().parents[2]
    doc = json.loads((root / "presets.json").read_text(encoding="utf-8"))
    opts = _preset_opts(doc, "Pygmies_Revenge.sid")
    assert opts["tie"]

    def tie_rows(**over):
        sng = convert(str(CORPUS / "Pygmies_Revenge.sid"), lambda *a: None,
                      **{**opts, **over})
        pats = parse_sng(bytes(sng)).patterns
        return sum(1 for p in pats for k in range(0, len(p), 4)
                   if p[k] != GT_END_PATTERN and p[k + 2] == CMD_TONEPORTA
                   and p[k + 3] == 0)

    assert tie_rows() - tie_rows(tie=False) >= 90
