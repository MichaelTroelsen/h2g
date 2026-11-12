"""pre_note_wave: the waveform a voice shows before its first note.

The original's player writes the held instrument's control byte (gate clear on
a rest) to $D404 every frame, so a voice that opens on rests shows that
waveform from frame 1-2 while Goattracker shows $00 (`h2g/pre_note_wave.py`).
The prediction `control(starting instrument) & $FE` is checked below against
the first pre-gate waveform a siddump of the original shows, measured at
-t60 / subtune 0 on the twelve files of the todo.md entry.
"""
import io
import contextlib

import pytest

from corpus import CORPUS, needs_corpus
from h2g.convert import convert
from h2g.detect import detect
from h2g.patterns import MAX_PATTERNS
from h2g.pre_note_wave import (CMD_SETWAVE, _entry, apply_pre_note_waves,
                               start_waves)
from h2g.sidfile import load_sid
from songview import parse_sng

REST, KEYOFF = 0xBD, 0xBE

# siddump of the ORIGINAL, subtune 0: the waveform written before each voice's
# first gate-on, None where the voice's first event is already a note. Kentilla
# voice 1 holds $14 for two frames and then alternates with $80, which the
# static latch does not reproduce; only its first value is pinned.
MEASURED = {
    "Pygmies_Revenge": (0x40, 0x40, 0x40),
    "Chimera": (None, 0x40, 0x40),
    "Crazy_Comets": (0x80, None, 0x40),
    "Formula_1_Simulator": (None, 0x40, None),
    "Gremlins": (None, 0x40, None),
    "Hunter_Patrol": (0x10, 0x10, None),
    "Kentilla": (None, 0x14, None),
    "Last_V8": (0x40, None, 0x80),
    "Last_V8_C128_version": (0x40, None, 0x40),
    "Master_of_Magic": (0x10, None, 0x40),
    "Phantoms_of_the_Asteroid": (0x40, None, 0x40),
}


def row(note=REST, instr=0, cmd=0, data=0):
    return [note, instr, cmd, data]


def pattern(*rows):
    return [b for r in rows for b in r] + [0xFF, 0, 0, 0]


def _det(stem):
    with contextlib.redirect_stdout(io.StringIO()):
        return detect(load_sid(str(CORPUS / f"{stem}.sid")), lambda m: None)


# ---- the emitter, on synthetic songs --------------------------------------

def played(track, n):
    """The first `n` pattern numbers an orderlist plays (no repeats or
    transposes in these fixtures), following the restart."""
    out, i = [], 0
    while len(out) < n:
        b = track[i]
        if b == 0xFF:
            i = track[i + 1]
            continue
        out.append(b)
        i += 1
    return out


def test_first_lap_gets_a_copy_and_the_loop_runs_the_plain_entry():
    """SABOTAGE TARGET: latching the entry pattern itself re-latches at every
    loop, under whatever the original's voice is still holding (Last_V8
    voice 0: a `$16` ring note spans the restart)."""
    pats = [pattern(row(KEYOFF, 0, 0x0F, 4), row(), row(), row(0x70, 3)),
            pattern(row(0x70, 3))]
    tracks = [[0, 1, 0xFF, 0], [], []]
    out, new, n = apply_pre_note_waves(pats, tracks, (0x40, None, None),
                                       MAX_PATTERNS)
    assert n == 1
    copy = 2
    assert out[0] == pats[0]                           # the entry is untouched
    assert out[copy][4:8] == [REST, 0, CMD_SETWAVE, 0x40]
    assert out[copy][0:4] == [KEYOFF, 0, 0x0F, 4]      # the tempo cell is kept
    assert new[0] == [copy, 1, 0, 0xFF, 1]
    # lap by lap the plain entry plays everywhere but the first position
    old_seq = played(tracks[0], 8)
    new_seq = [0 if x == copy else x for x in played(new[0], 8)]
    assert new_seq == old_seq


def test_a_prefix_is_repeated_before_the_entry_at_the_end():
    pats = [pattern(row(KEYOFF), row(), row())]
    tracks = [[0xE1, 0, 0xFF, 0], [], []]               # transpose, then E
    out, new, n = apply_pre_note_waves(pats, tracks, (0x40, None, None),
                                       MAX_PATTERNS)
    assert n == 1
    assert new[0] == [0xE1, 1, 0xE1, 0, 0xFF, 2]


def test_a_restart_past_the_entry_latches_the_entry_in_place():
    """The park loop never re-enters the entry, so no copy is needed."""
    pats = [pattern(row(KEYOFF), row(), row(0x70, 3)), pattern(row())]
    tracks = [[0, 1, 0xFF, 1], [], []]
    out, new, n = apply_pre_note_waves(pats, tracks, (0x40, None, None),
                                       MAX_PATTERNS)
    assert n == 1 and new[0] == tracks[0]
    assert out[0][0:4] == [KEYOFF, 0, CMD_SETWAVE, 0x40]


def test_a_shared_entry_past_the_restart_is_copied():
    pats = [pattern(row(KEYOFF), row(), row(0x70, 3)), pattern(row())]
    tracks = [[0, 1, 0xFF, 1], [0, 1, 0xFF, 1], []]
    out, new, n = apply_pre_note_waves(pats, tracks, (0x40, None, None),
                                       MAX_PATTERNS)
    assert n == 1
    assert out[0] == pats[0]
    assert new[0] == [2, 1, 0xFF, 1] and new[1] == tracks[1]
    assert out[2][0:4] == [KEYOFF, 0, CMD_SETWAVE, 0x40]


def test_a_restart_into_the_prefix_is_left_alone():
    pats = [pattern(row(KEYOFF), row(), row(0x70, 3))]
    tracks = [[0xE1, 0, 0xFF, 1], [], []]
    out, new, n = apply_pre_note_waves(pats, tracks, (0x40, None, None),
                                       MAX_PATTERNS)
    assert n == 0 and out == pats and new == tracks


def test_a_voice_that_opens_on_a_note_is_left_alone():
    pats = [pattern(row(0x70, 3), row(), row())]
    out, new, n = apply_pre_note_waves(pats, [[0, 0xFF, 0], [], []],
                                       (0x40, None, None), MAX_PATTERNS)
    assert n == 0 and out == pats and new[0] == [0, 0xFF, 0]


def test_a_cell_holding_a_command_is_never_overwritten():
    pats = [pattern(row(KEYOFF, 0, 0x0F, 4), row(REST, 0, 3, 9), row(),
                    row(0x70, 3))]
    out, new, n = apply_pre_note_waves(pats, [[0, 0xFF, 0], [], []],
                                       (0x40, None, None), MAX_PATTERNS)
    assert n == 1
    assert out[1][4:8] == [REST, 0, 3, 9]
    assert out[1][8:12] == [REST, 0, CMD_SETWAVE, 0x40]


def test_no_free_cell_before_the_note_writes_nothing():
    pats = [pattern(row(KEYOFF, 0, 0x0F, 4), row(REST, 0, 3, 9),
                    row(0x70, 3))]
    out, new, n = apply_pre_note_waves(pats, [[0, 0xFF, 0], [], []],
                                       (0x40, None, None), MAX_PATTERNS)
    assert n == 0 and out == pats


def test_a_copy_past_the_pattern_ceiling_is_dropped():
    pats = [pattern(row(KEYOFF), row(), row(0x70, 3))]
    tracks = [[0, 0xFF, 0], [], []]
    out, new, n = apply_pre_note_waves(pats, tracks, (0x40, None, None),
                                       max_patterns=1)
    assert n == 0 and out == pats and new == tracks


def test_a_repeated_entry_with_a_note_is_left_alone():
    pats = [pattern(row(KEYOFF), row(), row(0x70, 3))]
    out, new, n = apply_pre_note_waves(pats, [[0xD1, 0, 0xFF, 0], [], []],
                                       (0x40, None, None), MAX_PATTERNS)
    assert n == 0 and out == pats


def test_an_all_rest_entry_takes_the_first_free_row():
    pats = [pattern(row(KEYOFF, 0, 0x0F, 4), row(), row())]
    out, new, n = apply_pre_note_waves(pats, [[0, 0xFF, 0], [], []],
                                       (0x40, None, None), MAX_PATTERNS)
    assert n == 1 and out[1][4:8] == [REST, 0, CMD_SETWAVE, 0x40]


# ---- the reader, on the corpus ---------------------------------------------

@needs_corpus
@pytest.mark.parametrize("stem", sorted(MEASURED))
def test_the_start_waves_equal_the_traced_latch(stem):
    """SABOTAGE TARGET: reading the record's byte 3 instead of byte 2, or not
    clearing the gate bit, moves every value."""
    det = _det(stem)
    sid = load_sid(str(CORPUS / f"{stem}.sid"))
    got = start_waves(sid, det)
    for v, want in enumerate(MEASURED[stem]):
        if want is not None:
            assert got[v] == want, (stem, v)


# ---- the option, end to end --------------------------------------------------

def _both(stem):
    off = parse_sng(convert(str(CORPUS / f"{stem}.sid"), log=lambda m: None))
    lines = []
    on = parse_sng(convert(str(CORPUS / f"{stem}.sid"), log=lines.append,
                           pre_note_wave=True))
    return off, on, lines


def _setwave_cells(song):
    return [(p, r, pat[4 * r + 3])
            for p, pat in enumerate(song.patterns)
            for r in range(len(pat) // 4) if pat[4 * r + 2] == CMD_SETWAVE]


@needs_corpus
def test_pygmies_latches_40_on_each_voice_and_nothing_else_moves():
    """SABOTAGE TARGET: `pre_note_wave` ignored in build_sng leaves no cell."""
    off, on, lines = _both("Pygmies_Revenge")
    assert [c for c in _setwave_cells(off) if c[2] == 0x40] == []
    cells = _setwave_cells(on)
    assert len([c for c in cells if c[2] == 0x40]) == 3
    assert all(c[1] <= 1 for c in cells)                 # before any note
    assert any("latches $40" in m for m in lines)
    assert on.instruments == off.instruments
    assert on.subtunes == off.subtunes
    carrying = {p for p, _r, _w in cells}
    for v in range(3):
        t = on.tracks[v]
        assert t[0] in carrying                         # lap one latches ...
        assert t[-3] not in carrying and t[-2] == 0xFF  # ... the loop does not
        assert t[-1] == 1                               # and restarts after it
        assert t[-3] == off.tracks[v][0]                # on the plain entry


@needs_corpus
def test_the_option_off_changes_no_byte():
    a = convert(str(CORPUS / "Pygmies_Revenge.sid"), log=lambda m: None)
    b = convert(str(CORPUS / "Pygmies_Revenge.sid"), log=lambda m: None,
                pre_note_wave=False)
    assert a == b


# ---- the idle voice's instrument ------------------------------------------

def test_row_0_names_a_vibrato_free_instrument_until_the_first_note():
    """SABOTAGE TARGET: the packed player vibrates a voice that holds
    instrument 1 at delay 0 (`mt_effect_0`), which a latched waveform turns
    into ties the original does not have (Phantoms tiefr .645 -> .599)."""
    pats = [pattern(row(KEYOFF), row(), row()), pattern(row(0x70, 3))]
    tracks = [[0, 1, 0xFF, 0], [], []]
    out, new, n = apply_pre_note_waves(pats, tracks, (0x40, None, None),
                                       MAX_PATTERNS,
                                       vibrato={1: 11, 2: 0, 3: 0})
    assert n == 1
    assert out[2][1] == 2                       # first-lap copy, quiet
    assert out[0] == pats[0] and out[1] == pats[1]


def test_an_instrument_1_without_vibrato_is_left_alone():
    pats = [pattern(row(KEYOFF), row(), row()), pattern(row(0x70, 3))]
    out, new, n = apply_pre_note_waves(pats, [[0, 1, 0xFF, 0], [], []],
                                       (0x40, None, None), MAX_PATTERNS,
                                       vibrato={1: 0, 2: 0})
    assert out[2][1] == 0


def test_a_first_note_that_names_no_instrument_keeps_the_held_one():
    pats = [pattern(row(KEYOFF), row(), row()), pattern(row(0x70, 0))]
    out, new, n = apply_pre_note_waves(pats, [[0, 1, 0xFF, 0], [], []],
                                       (0x40, None, None), MAX_PATTERNS,
                                       vibrato={1: 11, 2: 0})
    assert out[2][1] == 0


def test_a_row_0_that_names_an_instrument_is_kept_and_no_quiet_one_means_none():
    pats = [pattern(row(KEYOFF, 4), row(), row()), pattern(row(0x70, 3))]
    out, new, n = apply_pre_note_waves(pats, [[0, 1, 0xFF, 0], [], []],
                                       (0x40, None, None), MAX_PATTERNS,
                                       vibrato={1: 11, 2: 0})
    assert out[2][1] == 4
    pats = [pattern(row(KEYOFF), row(), row()), pattern(row(0x70, 3))]
    out, new, n = apply_pre_note_waves(pats, [[0, 1, 0xFF, 0], [], []],
                                       (0x40, None, None), MAX_PATTERNS,
                                       vibrato={1: 11, 2: 5})
    assert out[2][1] == 0


@needs_corpus
def test_phantoms_idles_on_a_vibrato_free_instrument_first_lap_only():
    """Phantoms' instrument 1 vibrates (vib_ptr 11 under the shipped presets):
    the first-lap copy of each latching voice's entry names a vibrato-free one
    on row 0, the loop's plain entry does not, and no instrument record
    moves."""
    import json
    from pathlib import Path
    import fidelity
    name = "Phantoms_of_the_Asteroid.sid"
    doc = json.loads((Path(__file__).resolve().parents[2]
                      / "presets.json").read_text(encoding="utf-8"))
    opts = fidelity._preset_opts(doc, name)
    opts.pop("pre_note_wave", None)
    path = str(CORPUS / name)
    off = parse_sng(convert(path, log=lambda m: None, **opts))
    lines = []
    on = parse_sng(convert(path, log=lines.append, pre_note_wave=True, **opts))
    assert on.instruments == off.instruments
    assert on.instruments[0].vib_ptr != 0
    assert any("vibrato-free instrument" in m for m in lines)
    for v in (0, 2):
        first = on.tracks[v][_entry(on.tracks[v])]
        last = on.tracks[v][-3]
        quiet = on.patterns[first][1]
        assert quiet != 0 and on.instruments[quiet - 1].vib_ptr == 0
        assert on.patterns[last][1] == 0
