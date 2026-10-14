"""Nineteen and Rock_Tells_the_Tale: a note an orderlist transpose lifts past
Goattracker's 96-entry table, traced against the original.

`gt2reloc` keeps the frequency table to `firstnote..lastnote` with `lastnote`
capped at 95 (`greloc.c:314-315`, `:887`), so a wavetable step `+0` played on a
note whose pattern byte plus orderlist transpose is 96 or more reads whatever
the packer put after `mt_freqtblhi`. `past_table_wave.retarget_mixed_steps`
(a pinned copy of the wave program for the note row, `CMD_SETWAVEPTR` to it)
answers it for both files; this file is the trace that says it answers the
right NOTES, and pins the figures the trace produced.

**The task title's "note 100" is the note column.** Nineteen's row is pattern
21 row 57: raw pattern byte 93 (`$5D`), which Goattracker's note column (92
at most) clamps and `convert_patterns` records as a top row (`top_cols`), plus
orderlist transpose +8 = index 101. `_walk` adds the recorded delta; a census
over the finished song's note column alone reads 92 + 8 = 100.

**What the original does, traced (py65 on the .sid, init then the play entry,
every instruction that names the frequency table with an index; 15000 frames
of Nineteen, 22000 of Rock_Tells_the_Tale, subtune 1 each):**

* Nineteen: ONE lookup past the table in 300 s, frame 4242, index 101
  (`LDA $94CC,Y` at `$9126`). The cell is `$9596/$9597`, two per-voice
  counters the player increments every frame; they read `2E 32` there, so the
  voice sounds `$322E` (siddump frame 4242 voice 0 `322E`) and falls
  `$0A07` a frame from it. The load-time cell is `$000D`. Nothing a wavetable
  can follow: the pin is a stand-in (C#0, entry 1) for a coincidence of
  counters, and the original's fall reaches `$000B` at 4247 and wraps at 4248
  where the conversion wraps at 4245 (3 frames early; pinning F#5 instead
  wraps at 4249, 1 frame late -- measured, not shipped).
* Rock_Tells_the_Tale: THREE lookups past the table in 440 s, frames 13407,
  13780, 14153, all index 96, always `00 07`: `$0700`, the head of the
  per-voice offset table that follows the note table, which nothing writes.
  The load-time cell IS the value, the pin (entry 33) is the original's pitch
  to within the file's own 70-cent detune, and siddump frame 13407 voice 0
  reads `0700 ... 15 0B99`.

The conversion plays exactly as many of them: one pinned visit in Nineteen,
three in Rock_Tells_the_Tale (pattern 77 row 58, pattern 78 rows 28 and 92).
The figures are history of a trace; the tests below pin the conversion's side
of it (counts, notes, cells, pins), not the trace itself.
"""
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent))

from h2g import past_table_wave as W                       # noqa: E402
from h2g.goatwriter.appending import _parse_song           # noqa: E402
from test_past_table_split import _corpus_convert          # noqa: E402

# name -> (index the original reads, load-time cell, table entry nearest it,
#          pinned note, visits that play the pinned copy). Nineteen's cell
#          is nearest entry 0 (C-0), which has no absolute spelling: the pin
#          is entry 1 (C#0), the lowest there is.
_TRACED = {
    "Nineteen.sid": (101, 0x000D, 0, 1, 1),
    "Rock_Tells_the_Tale.sid": (96, 0x0700, 33, 33, 3),
}


def _overflow(song, top) -> int:
    """(note row, orderlist visit) pairs that still send a relative wave step
    to index 96 or more, counted with the walk's own notes (top rows
    included) and nothing of `_pin_target`."""
    wave = song.tables[0]
    n = 0
    for visits in W._reach(song, top).values():
        for start, note, _instr in visits:
            for step in W._program(wave, start):
                left, right = wave[step - 1]
                if left < W._WAVE_CMD and right < W._KEEP \
                        and (note + right) & 0x7F >= W.GT_NOTES:
                    n += 1
                    break
    return n


def _views(name):
    _out, seen = _corpus_convert(name)
    assert seen, "the pass never ran"
    return seen


@pytest.mark.parametrize("name", sorted(_TRACED))
def test_the_unpinned_song_does_overflow_and_the_pinned_one_does_not(name):
    for before, after, _sid, det in _views(name):
        top = W.top_rows_of(getattr(det, "top_cols", None))
        assert _overflow(_parse_song(before), top) > 0
        assert _overflow(_parse_song(after), top) == 0


@pytest.mark.parametrize("name", sorted(_TRACED))
def test_pinned_visits_are_the_notes_the_original_reads_past_its_table(name):
    index, _cell, _near, _pin, visits = _TRACED[name]
    for before, after, _sid, det in _views(name):
        top = W.top_rows_of(getattr(det, "top_cols", None))
        old, new = _parse_song(before), _parse_song(after)
        pinned = [note for rows in W._reach(new, top).values()
                  for start, note, _i in rows if start > len(old.tables[0])]
        assert len(pinned) == visits
        assert set(pinned) == {index - det.note_base}


@pytest.mark.parametrize("name", sorted(_TRACED))
def test_the_pin_is_the_entry_nearest_the_cell_the_original_reads(name):
    index, cell, near, pin, _visits = _TRACED[name]
    for before, after, sid, det in _views(name):
        ft = det.freq_table
        base = sid.to_offset(ft.addr) + 2 * index
        assert sid.data[base] | sid.data[base + 1] << 8 == cell
        assert W._cell_entry(sid, det, index) == near
        assert W._pin_target(sid, det, index - det.note_base, 0) == pin
        old, new = _parse_song(before), _parse_song(after)
        added = new.tables[0][len(old.tables[0]):]
        absolute = {right for left, right in added if left < W._WAVE_CMD}
        assert absolute == {0x80 | pin}
        assert new.tables[0][:len(old.tables[0])] == old.tables[0]


def test_nineteens_note_is_a_top_row_the_note_column_cannot_say():
    """The note column holds 92; the walk's note is 101 = 92 + 1 + 8."""
    for before, _after, _sid, det in _views("Nineteen.sid"):
        top = W.top_rows_of(det.top_cols)
        assert top, "Nineteen has a row above the note column"
        song = _parse_song(before)
        by_column = {note for rows in W._reach(song).values()
                     for _s, note, _i in rows}
        by_walk = {note for rows in W._reach(song, top).values()
                   for _s, note, _i in rows}
        assert 100 in by_column and 101 not in by_column
        assert 101 in by_walk
