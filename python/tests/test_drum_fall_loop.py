"""`drum_fall_loop`: the bit-$01 drum's fall on a note longer than the record's
own sweep.

Formula_1_Simulator's record 10 (`$0F0F`, `10:00-00-01`) is played on E-6
(`$57AC`) in a 64-row pattern. The player's drum block subtracts one from the
frequency high byte a frame until it reaches zero, so the original falls
`$57AC -> $01AC` over 115 frames while `_drum_max_steps` caps the record's own
program at `DRUM_MAX_SWEEP_STEPS` player frames: 8 frames, `bend` 0.64x. A
chain of the whole fall is a wavetable entry per play call -- 216 at -S2
against 56 free in a 199-entry table -- so the fall is a two-entry loop and its
LENGTH is a second `CMD_SETWAVEPTR` on the row where it ends.

A per-song `convert()` option, off by default and shipped by no song.
"""
import json
import pathlib
import sys

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[1]))

import fidelity                                              # noqa: E402
from corpus import CORPUS, needs_corpus                      # noqa: E402
from h2g.convert import convert                              # noqa: E402
from h2g.goatwriter import drum_long                         # noqa: E402
from h2g.goatwriter.constants import (CMD_SETWAVEPTR,       # noqa: E402
                                      DRUM_MAX_SWEEP_STEPS,
                                      GT_FIRST_NOTE, GT_LAST_NOTE,
                                      GT_WAVE_JUMP, WAVECMD_PORTADOWN,
                                      _drum_speed)
from h2g.goatwriter.primitives import _gate_calls, _note_freq  # noqa: E402
from songview import parse_sng                                # noqa: E402

F1 = CORPUS / "Formula_1_Simulator.sid"
REPO_ROOT = pathlib.Path(__file__).resolve().parents[2]
M, ROW_CALLS = 2, 5            # Formula_1_Simulator: -S2, 2.5-frame rows
STEP = (lambda hi_lo: (hi_lo[0] << 8) | hi_lo[1])(_drum_speed(M, 4))


def _note_for(freq_at_least: int) -> int:
    """A GT note byte whose frequency is the lowest one past the argument."""
    for n in range(GT_LAST_NOTE - GT_FIRST_NOTE):
        if _note_freq(n) >= freq_at_least:
            return GT_FIRST_NOTE + n
    raise AssertionError("no note that high")


def _rows(length: int, note: int):
    rows = [[note, 1, 0, 0]] + [[0xBD, 0, 0, 0] for _ in range(length - 1)]
    rows.append([0xFF, 0, 0, 0])            # the pattern's end
    return rows


def _fall(length: int, note: int, gate_skip=4):
    declined = []
    got = drum_long._long_fall(_rows(length, note), 0, length, note, 0,
                               ROW_CALLS, M, STEP, gate_skip,
                               declined.append)
    return got, declined


def test_a_long_note_falls_to_its_floor_and_stops_on_a_row():
    note = _note_for(0x57AC)
    got, _ = _fall(64, note)
    assert got is not None
    head, stop, calls = got
    freq = _note_freq(note - GT_FIRST_NOTE)
    assert head == 1
    # The loop runs from the head's first call, after `multiplier +
    # HOLD_EXTRA` held calls, until the stop row's first call.
    fall = (stop - head) * ROW_CALLS - (M + drum_long.HOLD_EXTRA)
    assert 0 < fall <= calls
    # Never past the floor (it would wrap to a high note) ...
    assert freq - fall * STEP >= drum_long.DRUM_FALL_FLOOR
    # ... and within two rows of it (the stop is row-granular).
    assert freq - fall * STEP - drum_long.DRUM_FALL_FLOOR < 2 * ROW_CALLS * STEP


def test_a_fall_the_records_own_program_carries_is_left_alone():
    own = DRUM_MAX_SWEEP_STEPS * _gate_calls(M, 4)
    # Eight rows at five calls a row: (8 - 2) * 5 - 2 = 28 calls of fall.
    got, declined = _fall(8, _note_for(0x57AC))
    assert got is not None and 28 >= 1.5 * own
    # Battle_of_Britain's 22 calls (1.4x the cap) cost its drum a noise frame.
    got, declined = _fall(7, _note_for(0x57AC))
    assert (7 - 2) * ROW_CALLS - M < 1.5 * own
    assert got is None and declined == [
        "the record's own program already sweeps"]


def test_a_note_without_a_fall_gets_none():
    got, declined = _fall(64, _note_for(0x80))
    assert got is None


def _doc() -> dict:
    return json.loads((REPO_ROOT / "presets.json").read_text(encoding="utf-8"))


def _convert(**kw):
    opts = fidelity._preset_opts(_doc(), F1.name)
    return convert(str(F1), log=lambda m: None, **{**opts, **kw})


def _loops(blob):
    """(pattern, head row, stop row) of every loop head: a SETWAVEPTR into
    held gate-off entries that jump to a PORTADOWN which jumps to itself, and
    a later SETWAVEPTR in the same pattern into a held entry then the end."""
    song = parse_sng(blob)
    wave = song.tables["WTBL"]
    found = []
    for pi, pat in enumerate(song.patterns):
        heads, stops = [], []
        for r in range(0, len(pat) - 3, 4):
            if pat[r + 2] != CMD_SETWAVEPTR:
                continue
            at = pat[r + 3] - 1
            holds = 0
            while wave[at + holds] == (wave[at][0], 0x80):
                holds += 1
            left, right = wave[at + holds]
            if left != GT_WAVE_JUMP:
                continue
            if (wave[right - 1][0] == WAVECMD_PORTADOWN
                    and wave[right] == (GT_WAVE_JUMP, right)):
                heads.append(r // 4)
            elif right == 0 and holds == 1:
                stops.append(r // 4)
        for h in heads:
            later = [s for s in stops if s > h]
            if later:
                found.append((pi, h, later[0]))
    return found


@needs_corpus
def test_off_emits_no_loop():
    assert _loops(_convert(drum_fall_loop=False)) == []
    # presets.json turns it on for Formula_1_Simulator (adopted v0.5.677):
    # the shipped file is the option-on one, and off is a different file.
    assert _convert(drum_fall_loop=True) == _convert()
    assert _convert(drum_fall_loop=False) != _convert()


@needs_corpus
def test_formula_1_long_note_gets_a_loop_and_a_stop():
    loops = _loops(_convert(drum_fall_loop=True))
    # The 64-row E-6 note: head on row 1, stop on row 45 -- 44 rows of five
    # calls less the held entries, 216 calls of $0066 from $57AC. Six
    # eight-row notes fall 28 calls on the same loop.
    spans = sorted(s - h for _p, h, s in loops)
    assert spans == [6] * 6 + [44]
