"""`--rest-park-twin`: a rest on a LOOPING wave program points at a silent stepping
twin of the loop, not at the stop program (`goatwriter/rest_park.py`,
`twin_loops`).

The original's rest does not stop a record's pitch loop; it keeps stepping it
with the voice at wave `$08` and ADSR `$0000`, so its frequency register keeps
reversing across the rest. The stop program freezes the register where the park
lands. I_Ball, `rest_wave_silence` + `rest_envelope_silence`, `-t 180` at
v0.5.685 (historical): vib 1.0056 -> .9438 with the stop program, .9943 with the
twin; hold 67 -> 83, holdnf 75 -> 92, ctrl 70 -> 92 either way
(C:/t/listen-r2-i-ball, arms rwsenv / twenv).

The first tests transcribe the part of gplay.c's WAVEEXEC (:520-535, :697-712)
that decides it; the rest read the pass and the converter's output.
"""
import json
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

# goatwriter first: importing h2g.patterns first trips a pre-existing circular
# import (patterns -> goatwriter -> counter_fall -> patterns).
from h2g.goatwriter import rest_park as RP  # noqa: E402
from h2g import patterns as P  # noqa: E402
from corpus import CORPUS, needs_corpus  # noqa: E402

PRESETS = Path(__file__).resolve().parents[2] / "presets.json"
KEYOFF, NO_NOTE = P.GT_KEYOFF, P.GT_NO_NOTE
SETWAVE, SETWAVEPTR = P.CMD_SETWAVE, P.CMD_SETWAVEPTR
PARK = RP.REST_PARK_PROGRAM
SILENT = 0xE8
SETSR_ROW = (RP.WAVECMD_BASE | RP.CMD_SETSR, 0x00)

# I_Ball instrument 3: wave $41, note column base, base, +24 (period 3).
LOOP = [(0x41, 0x00), (0x41, 0x00), (0x41, 0x18), (0xFF, 0x01)]


class Voice:
    """`cptr->wave`, `ptr[WTBL]`, `wavetime` and the notes WAVEEXEC writes.
    `table` is 1-based like the player's."""

    def __init__(self, table, ptr=0):
        self.table, self.ptr, self.wave, self.wavetime = table, ptr, 0x41, 0
        self.notes = []

    def command(self, cmd, data):                         # gplay.c:433-445
        assert cmd == SETWAVEPTR
        assert not data or self.table[data - 1][0] != 0xFF, \
            "gplay.c:442 stops the song on a jump target"
        self.ptr, self.wavetime = data, 0

    def waveexec(self):                                   # gplay.c:520-535, 709
        if not self.ptr:
            return
        wave, note = self.table[self.ptr - 1]
        if 0xF0 <= wave <= 0xFE:                          # a command row:
            note = 0x80                                   # its right byte is data
        elif wave > 0x0F:
            if wave < 0xE0:
                self.wave = wave
            if 0xE0 <= wave <= 0xEF:
                self.wave = wave & 0xF
        elif self.wavetime != wave:
            self.wavetime += 1
            return
        self.wavetime = 0
        self.ptr += 1
        if self.table[self.ptr - 1][0] == 0xFF:
            self.ptr = self.table[self.ptr - 1][1]
        if note != 0x80:
            self.notes.append(note)

    def run(self, calls):
        for _ in range(calls):
            self.waveexec()


def _pat(*rows):
    return [b for row in rows for b in row] + [0xFF, 0, 0, 0]


REST = (KEYOFF, 0, SETWAVE, 0x08)
HOLD = (NO_NOTE, 0, 0, 0x08)


def _song():
    """Instrument 1 loops (I_Ball's LOOP), 2 has a program that STOPS, 3 none."""
    entries = LOOP + [(0x41, 0x00), (0xFF, 0x00)]
    starts = {1: 1, 2: 5, 3: 0}
    pats = [_pat((0x60, 1, 0, 0), REST, HOLD),
            _pat((0x60, 2, 0, 0), REST, HOLD),
            _pat((0x60, 3, 0, 0), REST, HOLD)]
    return pats, [[0, 1, 2, 0xFF, 0]], entries, starts


def test_the_stop_park_freezes_the_loop_and_the_twin_keeps_stepping():
    loops = RP.twin_loops(LOOP, {1: 1})
    body, lead = loops[1]
    assert lead == 0
    base = len(LOOP) + 1
    ptr, rows = RP.twin_layout(loops, {1}, base + len(PARK))
    table = LOOP + list(PARK) + rows

    stopped = Voice(table, ptr=1)
    stopped.run(4)
    stopped.command(SETWAVEPTR, base)
    before = len(stopped.notes)
    stopped.run(30)
    assert stopped.wave == 0x08 and stopped.ptr == 0
    assert len(stopped.notes) == before, \
        "the stop program's `E8 80` carries no note: the register freezes"

    twinned = Voice(table, ptr=1)
    twinned.run(4)
    twinned.command(SETWAVEPTR, ptr[1])
    before = len(twinned.notes)
    twinned.run(30)
    assert twinned.wave == 0x08, "silent: below siddump's note threshold"
    assert twinned.ptr != 0, "the table keeps running"
    assert twinned.notes[before:] == [0x00, 0x00, 0x18] * 10, \
        "the original's own cycle"


def test_the_prefix_runs_once_and_the_loop_jumps_past_it():
    loops = RP.twin_loops(LOOP, {1: 1})
    base = len(LOOP) + 1
    ptr, rows = RP.twin_layout(loops, {1}, base, (SETSR_ROW,))
    assert ptr[1] == base and rows[0] == SETSR_ROW
    assert rows[-1] == (0xFF, base + 1), "past the SR row, onto the first step"
    table = LOOP + rows
    v = Voice(table, ptr=1)
    v.command(SETWAVEPTR, ptr[1])
    v.run(1 + 3 * 5)
    assert v.notes == [0x00, 0x00, 0x18] * 5
    assert v.wave == 0x08


def test_twin_loops_walks_to_the_cycle_and_declines_what_it_cannot_copy():
    # a lead-in then a loop: the twin is the LOOP only, the lead-in is gone
    lead_in = [(0x11, 0x00), (0x41, 0x05), (0x41, 0x07), (0xFF, 0x02)]
    body, _ = RP.twin_loops(lead_in, {1: 1})[1]
    assert body == ((SILENT, 0x05), (SILENT, 0x07))
    # delays and the note column are kept
    assert RP.twin_loops([(0x41, 0x00), (0x02, 0x0C), (0xFF, 0x01)],
                         {1: 1})[1][0] == ((SILENT, 0x00), (0x02, 0x0C))
    # a stop, a command row, a cycle that opens on a delay, no program
    assert RP.twin_loops([(0x41, 0x00), (0xFF, 0x00)], {1: 1}) == {}
    assert RP.twin_loops([(0x41, 0x00), (0xF4, 0x10), (0xFF, 0x01)],
                         {1: 1}) == {}
    assert RP.twin_loops([(0x01, 0x00), (0x41, 0x00), (0xFF, 0x01)],
                         {1: 1}) == {}
    assert RP.twin_loops(LOOP, {1: 0}) == {}


def test_instruments_sharing_a_loop_share_the_twin_rows():
    entries = [(0x41, 0x00), (0xFF, 0x01), (0x11, 0x00), (0xFF, 0x01)]
    loops = RP.twin_loops(entries, {1: 1, 2: 3})
    ptr, rows = RP.twin_layout(loops, {1, 2}, 5)
    assert ptr[1] == ptr[2] == 5 and len(rows) == 2


def test_the_plan_points_the_looping_instruments_rest_at_its_twin():
    pats, tracks, entries, starts = _song()
    stop_pats, stop_entries = RP.rest_park_plan(pats, tracks, entries, starts)
    new_pats, new_entries = RP.rest_park_plan(pats, tracks, entries, starts,
                                              twin=True)
    park = len(entries) + 1
    # instrument 1 -> the twin, appended after the stop program
    assert new_entries[:len(stop_entries)] == stop_entries
    twin_at = park + len(PARK)
    assert new_entries[twin_at - 1:] == [(SILENT, 0x00), (SILENT, 0x00),
                                         (SILENT, 0x18), (0xFF, twin_at)]
    assert new_pats[0][4 + 2:4 + 4] == [SETWAVEPTR, twin_at]
    # instrument 2 (a program that stops) keeps the stop park; 3 has none
    assert new_pats[1][4 + 2:4 + 4] == [SETWAVEPTR, park]
    assert new_pats[2][4 + 2:4 + 4] == [SETWAVE, 0x08]
    assert stop_pats[0][4 + 2:4 + 4] == [SETWAVEPTR, park]


def test_the_option_off_is_the_plan_it_was():
    pats, tracks, entries, starts = _song()
    a = RP.rest_park_plan(pats, tracks, entries, starts)
    b = RP.rest_park_plan(pats, tracks, entries, starts, twin=False)
    assert a == b


def test_only_the_twins_a_rest_points_at_are_appended():
    pats, tracks, entries, starts = _song()
    # instrument 1's rest is not played: the orderlist reaches 2 and 3 only
    t2 = RP.rest_park_plan([pats[1], pats[2]], [[0, 1, 0xFF, 0]], entries,
                           starts, twin=True)
    assert t2[1] == entries + list(PARK), "no twin rows without a twinned rest"


def test_no_room_keeps_the_stop_program():
    pats, tracks, entries, starts = _song()
    full = entries + [(0x41, 0x00)] * (RP.GT_MAX_TABLELEN - len(entries) - 2)
    new_pats, new_entries = RP.rest_park_plan(pats, tracks, full, starts,
                                              twin=True)
    plain = RP.rest_park_plan(pats, tracks, full, starts)
    assert (new_pats, new_entries) == plain


def test_the_envelope_twin_zeroes_sr_once_and_keeps_the_hold_row_ad():
    pats, tracks, entries, starts = _song()
    hold_sr = (NO_NOTE, 0, P.CMD_SETSR, 0)
    pats[0] = _pat((0x60, 1, 0, 0), REST, hold_sr)
    new_pats, new_entries = RP.rest_park_plan(pats, tracks, entries, starts,
                                              envelope=True, vib=frozenset({1}),
                                              twin=True)
    at = new_pats[0][4 + 3]
    assert new_pats[0][4 + 2] == SETWAVEPTR
    assert new_entries[at - 1] == SETSR_ROW
    assert new_entries[-1] == (0xFF, at + 1)
    assert new_pats[0][8 + 2] == P.CMD_SETAD, "the AD stays on the hold row"


# --- the converter's own output ------------------------------------------------

def _convert(**extra):
    from fidelity import _preset_opts
    from h2g.convert import convert
    doc = json.loads(PRESETS.read_text(encoding="utf-8"))
    opts = _preset_opts(doc, "I_Ball.sid")
    opts.update(rest_wave_silence=True, rest_envelope_silence=True)
    opts.update(extra)
    lines = []
    blob = convert(str(CORPUS / "I_Ball.sid"), log=lines.append, **opts)
    return blob, lines


@needs_corpus
def test_i_ball_rests_step_a_silent_copy_of_instrument_3s_pitch_loop():
    import songview as S
    off, _ = _convert()
    on, lines = _convert(rest_park_twin=True)
    assert off != on
    assert any("silent stepping twin" in m for m in lines)
    song = S.parse_sng(on)
    w = song.tables["WTBL"]
    ptrs = {pat[r + 3] for pat in song.patterns
            for r in range(0, len(pat) - 3, 4)
            if pat[r] != 0xFF and pat[r + 2] == SETWAVEPTR}
    stepping = []
    for p in sorted(ptrs):
        v = Voice(w, ptr=1)
        v.command(SETWAVEPTR, p)
        v.run(60)
        assert v.wave == 0x08, "every parked rest is silent"
        if v.ptr:
            stepping.append(len(v.notes))
    # instrument 3's loop steps on every call; the others' twins carry delays
    assert stepping and min(stepping) > 10 and max(stepping) >= 59, stepping
    # ...and the stop park, which the option leaves on the other instruments,
    # does not
    off_ptrs = {pat[r + 3] for pat in S.parse_sng(off).patterns
                for r in range(0, len(pat) - 3, 4)
                if pat[r] != 0xFF and pat[r + 2] == SETWAVEPTR}
    assert off_ptrs


@needs_corpus
def test_the_option_is_inert_without_rest_wave_silence():
    base, _ = _convert(rest_wave_silence=False, rest_envelope_silence=False)
    twin, _ = _convert(rest_wave_silence=False, rest_envelope_silence=False,
                       rest_park_twin=True)
    assert base == twin
