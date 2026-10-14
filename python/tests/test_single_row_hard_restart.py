"""A note ONE row long keeps the floor hard restart, not the instrument-wide one.

Goattracker fetches the next row `gatetimer & $3F` calls early and, when that
row is a note or a KEYOFF, clears the gate (gplay.c:905, 921-937). The
instrument-wide hard restart is sized for the music's shape -- a note, then a
rest row, then the next note -- and `max_hard_restart` pushes it to
`row_calls - 1`. On a note whose very next row is itself a gate event that
leaves ONE call of gate.

Las_Vegas_Video_Poker subtunes 14 and 15 are sound effects of exactly that
shape: one note per voice, then the silent pattern's KEYOFF. The original
holds the gate for the whole 4-frame row ($41/$43); the conversion packed with
`max_hard_restart` + `hard_restart_frames` 4 (gatetimer 14, row 15 calls)
wrote the waveform with the gate already cleared ($10/$42), so `fidelity -a 14`
and `-a 15` reported *silent*. Subtunes 6 and 7 (instruments 16, 17) shared it.
`tracks.single_row_note_instruments` finds the instruments whose every note is
one row long and `goatwriter.instruments` caps their hard restart at
`SINGLE_ROW_HARD_RESTART_TICKS`.
"""
import json
import pathlib
import re
import sys

import pytest

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[1]))

from corpus import CORPUS, needs_corpus  # noqa: E402
import h2g.convert  # noqa: E402,F401  (first: h2g.tracks alone hits a circular import)
from h2g.tracks import (InstrumentRowCalls, instrument_row_calls,  # noqa: E402
                        single_row_note_instruments)

NOTE = 0x80
REST = 0xBD
KEYOFF = 0xBE
END = [0xFF, 0, 0, 0]
TIE = (3, 0)          # CMD_TONEPORTA 00


def pat(*rows):
    """rows: (note, instr, cmd, data) tuples, then ENDPATT."""
    out = []
    for r in rows:
        out += list(r)
    return out + END


def note(instr=0, cmd=(0, 0)):
    return (NOTE, instr, cmd[0], cmd[1])


def rest(instr=0, cmd=(0, 0)):
    return (REST, instr, cmd[0], cmd[1])


def keyoff():
    return (KEYOFF, 0, 0, 0)


# --------------------------------------------------------------------------
# the classifier, on synthetic orderlists
# --------------------------------------------------------------------------
def test_a_note_followed_by_a_keyoff_pattern_is_one_row_long():
    patterns = [pat(note(5)), pat(keyoff(), rest())]
    assert single_row_note_instruments([[0, 1, 0xFF, 1]], patterns) == {5}


def test_a_note_followed_by_a_rest_row_is_two_rows_long():
    """The music's shape: the next row fetched early is a REST, no gate event."""
    patterns = [pat(note(5), rest(), note(5)), pat(keyoff())]
    assert single_row_note_instruments([[0, 1, 0xFF, 1]], patterns) == set()


def test_a_note_followed_by_a_note_in_the_same_pattern_is_one_row_long():
    patterns = [pat(note(5), note(0))]
    # the last note wraps to row 0, a note
    assert single_row_note_instruments([[0, 0xFF, 0]], patterns) == {5}


def test_a_tie_row_is_not_a_gate_event():
    """gplay.c:926 exempts CMD_TONEPORTA from the hard restart."""
    patterns = [pat(note(5), rest(cmd=TIE)), pat(keyoff())]
    assert single_row_note_instruments([[0, 1, 0xFF, 1]], patterns) == set()
    patterns = [pat(note(5)), pat(note(0, cmd=TIE))]
    assert single_row_note_instruments([[0, 1, 0xFF, 1]], patterns) == set()


def test_the_loop_wraps_to_the_restart_position():
    patterns = [pat(note(5)), pat(note(0))]
    # [p0, p1, loop to 1]: p1's note wraps to p1's own row 0, a note
    assert single_row_note_instruments([[0, 1, 0xFF, 1]], patterns) == {5}
    patterns = [pat(note(5)), pat(note(6), rest())]
    # the last note (6) wraps to p1 row 0 = a note: one row; 6 is then followed by rest
    got = single_row_note_instruments([[0, 1, 0xFF, 1]], patterns)
    assert got == {5}     # 6's next row is its own pattern's rest


def test_an_orderlist_that_does_not_loop_cannot_resolve_the_last_note():
    patterns = [pat(note(5))]
    assert single_row_note_instruments([[0]], patterns) == set()


def test_a_repeat_looks_at_the_pattern_again_before_the_next_entry():
    # $D1: play p0 twice. Rep 1 of its last note is followed by p0's own row 0
    # (a rest here), rep 2 by p1's KEYOFF.
    patterns = [pat(rest(), note(5)), pat(keyoff())]
    assert single_row_note_instruments([[0xD1, 0, 1, 0xFF, 0]], patterns) == set()
    patterns = [pat(note(5)), pat(rest())]
    assert single_row_note_instruments([[0xD1, 0, 1, 0xFF, 0]], patterns) == set()
    patterns = [pat(note(5)), pat(keyoff())]
    assert single_row_note_instruments([[0xD1, 0, 1, 0xFF, 0]], patterns) == {5}


def test_one_long_note_disqualifies_the_instrument():
    patterns = [pat(note(5)), pat(keyoff()), pat(note(5), rest(), keyoff())]
    assert single_row_note_instruments([[0, 1, 2, 0xFF, 1]], patterns) == set()


def test_the_instrument_column_is_sticky():
    patterns = [pat(note(5), note(0), keyoff())]
    # note(5) -> note(0) is one row; the second note plays under 5 too, and is
    # followed by KEYOFF: one row; so 5 is single
    assert single_row_note_instruments([[0, 0xFF, 0]], patterns) == {5}


def test_a_note_under_no_instrument_is_not_attributed():
    patterns = [pat(note(0)), pat(keyoff())]
    assert single_row_note_instruments([[0, 1, 0xFF, 1]], patterns) == set()


def test_instrument_row_calls_carries_the_set_beside_its_dict():
    patterns = [pat(note(5)), pat(keyoff())]
    out = instrument_row_calls([[0, 1, 0xFF, 1], [], []], patterns, [15])
    assert isinstance(out, InstrumentRowCalls)
    assert out.single_row == {5}
    assert InstrumentRowCalls().single_row == frozenset()


# --------------------------------------------------------------------------
# Las_Vegas_Video_Poker, end to end
# --------------------------------------------------------------------------
LVVP = "Las_Vegas_Video_Poker.sid"
ROOT = pathlib.Path(__file__).resolve().parents[2]


def _convert():
    import fidelity as F
    from h2g.convert import convert
    doc = json.loads((ROOT / "presets.json").read_text(encoding="utf-8"))
    sng = convert(str(CORPUS / LVVP), log=lambda m: None,
                  **F._preset_opts(doc, LVVP))
    return F, doc, sng


def _instruments_of(song, subtune, first_only=False):
    used = set()
    for v in range(3):
        for p in song.tracks[subtune * 3 + v]:
            if p < 0xD0 and p < len(song.patterns):
                rows = song.patterns[p]
                used |= {rows[k] for k in range(1, len(rows), 4) if rows[k]}
                if first_only:
                    break
    return used


@needs_corpus
def test_lvvp_sound_effect_instruments_keep_the_floor_and_the_music_does_not():
    import songview
    _F, _doc, sng = _convert()
    song = songview.parse_sng(sng)
    ticks = {i.number: i.gatetimer & 0x3F for i in song.instruments}
    # the effect itself: the first pattern of each voice, one note long
    effects = (_instruments_of(song, 14, True)
               | _instruments_of(song, 15, True))
    music = _instruments_of(song, 13) - effects
    assert effects and music
    assert {ticks[i] for i in effects} == {2}, ticks
    assert max(ticks[i] for i in music) > 2, "the music's hard restart moved"


def _gated_frames(dump: str):
    """{voice: [(frame, ctrl)]} for every ctrl write in siddump's table."""
    out = {0: [], 1: [], 2: []}
    for line in dump.splitlines():
        cells = line.split("|")
        if len(cells) < 6 or not cells[1].strip().isdigit():
            continue
        frame = int(cells[1])
        for v in range(3):
            toks = cells[2 + v].split()
            if len(toks) >= 3 and re.fullmatch(r"[0-9A-F]{2}", toks[-3]):
                out[v].append((frame, int(toks[-3], 16)))
    return out


@needs_corpus
@pytest.mark.parametrize("subtune", [14, 15])
def test_lvvp_sound_effect_subtunes_raise_the_gate(tmp_path, subtune):
    F, doc, sng = _convert()
    if not pathlib.Path(F.GT2RELOC).exists():
        pytest.skip("gt2reloc not available")
    if not pathlib.Path(F.SIDDUMP_RT).exists():
        pytest.skip("tools/siddump-rt/siddump.exe not built")
    mult = F._preset_multiplier(doc, LVVP)
    sng, _ = F.legalise_restarts(sng)
    packed = F.pack_sid(sng, tmp_path, multiplier=mult)
    assert packed is not None and packed.exists()
    capture = []
    F.run_siddump(packed, 2, subtune, str(F.SIDDUMP_RT), calls=mult,
                  capture=capture)
    ours = _gated_frames(capture[1])
    # every voice writes a waveform with the gate bit set on its first note
    for v in range(3):
        writes = [c for _f, c in ours[v] if c]
        assert writes, f"voice {v} wrote no waveform"
        assert writes[0] & 1, \
            f"voice {v} opens on ${writes[0]:02X}: the gate is never raised"
