"""A skydive window that opens on the note row itself.

Zoids' block (`$1322`, MIN 16, LAST 24) runs while the ticks-left counter
`$144D,X` is below 24, so on a note of 16-23 ticks it runs from the fetch on.
The fetch frame skips every effect (`$116A JMP $137C`), so the first store is
on the note's frame 1 or 2: siddump of the original, voice 1, note at frame
8473 (F-6, `$5CE4`), stores `$5C0D $5BAA $5AE4 ... ` on 8475, 8477, 8479 ...
35 of them, alternating with the vibrato. `skydive_plan` declined these ("5
opens on the note row") until the pointer learned to take the NOTE row's
command column and carry the instrument's own wave program in its program
(`instrument_calls`, `_merge_instrument`, `skydive_note_row_program`).

Measured on the v0.5.513 tree with cycle 3's uncommitted merge, under
presets, siddump at the startup lag (7): the 35 store frames of each window
agreed on 1 high byte before, 35 after -- subtune 0 windows at frames 8475
and 9243 (-t 240), subtune 2 at frame 411. The two windows on tied notes
(`3 00` on the note row, frames 10371 and 10587) stay declined.
"""
import pathlib
import sys

import pytest

from corpus import CORPUS, needs_corpus

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[1]))

import fidelity                                              # noqa: E402
from h2g.goatwriter import skydive as S                      # noqa: E402
from h2g.goatwriter.constants import (CMD_SETWAVEPTR,        # noqa: E402
                                      GT_FIRST_NOTE, GT_LAST_NOTE)

PYTHON_ROOT = pathlib.Path(__file__).resolve().parents[1]

needs_siddump = pytest.mark.skipif(
    not pathlib.Path(fidelity.SIDDUMP).exists(),
    reason="no siddump on this machine (tools/siddump-rt, see its README)")
needs_gt2reloc = pytest.mark.skipif(
    not pathlib.Path(fidelity.GT2RELOC).exists(),
    reason="no gt2reloc on this machine")

# Zoids GT 9 and GT 11 (records 8 and 10): pulse with gate on, on the note,
# for three calls, then stop.
ZOIDS_INSTRUMENT = [(0x41, 0x00)] * 3


def _index(k):
    return 0x40 + k


def test_an_instrument_program_reads_call_by_call():
    entries = [(0x41, 0x00), (0x02, 0x0C), (0x00, 0x80), (0x21, 0x80),
               (0xFF, 0x00)]
    # `$02 $0C`: two still calls, then the right side; `$00 $80` writes
    # nothing; the stop takes no call.
    assert S.instrument_calls(entries, 1) == [
        (0x41, 0x00), None, None, (0x00, 0x0C), None, (0x21, 0x80)]
    assert S.instrument_calls([(0x41, 0x00), (0xFF, 0x01)], 1) is None


def test_the_note_row_program_starts_on_the_rows_second_frame():
    """Store 0 on row frame 3 (the note's frame 2, one frame of test-bit
    lead): the program's first call is the row's frame 1, so its frames 0-2
    are the instrument's, frame 3 is on the note, and store 1 is frame 4."""
    got = S.skydive_note_row_program(ZOIDS_INSTRUMENT, 3, 3, True, _index)
    assert got == [(0x41, 0x00), (0x41, 0x00), (0x41, 0x00), (0x00, 0x00),
                   (0xF2, 0x41), (0xF1, 0x41), (0xF2, 0x42), (0xF1, 0x42),
                   (0xFF, 0x00)]


def test_a_fall_never_overwrites_a_waveform_the_instrument_changes():
    # a fall frame on a call that switches the waveform is a conflict
    assert S.skydive_note_row_program(
        [(0x41, 0x00), (0x41, 0x00), (0x21, 0x00), (0x21, 0x00), (0x41, 0x00)],
        1, 3, True, _index) is None
    # ...as is any instrument command
    assert S.skydive_note_row_program(
        [(0x41, 0x00), (0xF4, 0x01)], 1, 3, True, _index) is None
    # the same waveform again is not a change: the fall takes the call
    got = S.skydive_note_row_program(
        [(0x41, 0x00), (0x41, 0x00), (0x41, 0x00), (0x41, 0x00)],
        2, 2, True, _index)
    assert got == [(0x41, 0x00), (0x41, 0x00), (0x41, 0x00), (0xF2, 0x41),
                   (0xF1, 0x41), (0xFF, 0x00)]


def test_the_holding_program_refuses_a_note_after_the_fall_started():
    # holding (no vibrato): store 1 on frame 2; an instrument step putting
    # the voice back on its note on frame 3 would undo it
    assert S.skydive_note_row_program(
        [(0x41, 0x00), None, None, (0x00, 0x00)], 1, 3, False,
        _index) is None


def test_a_tie_or_an_unreset_command_keeps_the_note_rows_column():
    """Empty: free. Portamento or vibrato: free only where the next event is
    a note whose init resets it. Toneporta on the note row is the tie:
    never -- Zoids' two tied windows are kept off it by this, and not only
    by the wavetable running out first."""
    assert S.note_row_column_free(0, False)
    for cmd in (1, 2, 4):
        assert S.note_row_column_free(cmd, True)
        assert not S.note_row_column_free(cmd, False)
    assert not S.note_row_column_free(3, True)
    for cmd in range(5, 16):
        assert not S.note_row_column_free(cmd, True)


def _converted(name, **extra):
    import json
    import h2g.convert as C
    doc = json.loads((PYTHON_ROOT.parent / "presets.json").read_text())
    lines = []
    opts = fidelity._preset_opts(doc, f"{name}.sid")
    opts.update(extra)
    sng = C.convert(str(CORPUS / f"{name}.sid"), log=lines.append, **opts)
    return sng, lines


@needs_corpus
def test_zoids_points_its_two_untied_short_notes_at_one_program():
    """Pattern $1E row 73 (subtune 0, played twice) and pattern $31 row 9
    (subtune 2): F-6 on GT 9, 23 ticks, `4 09` on the row. Each carries the
    pointer, and both name the one program the original's trace asks for
    (store 0 on row frame 3, 35 stores, alternating), built from GT 9's own
    wave program. The two tied notes keep their `3 00`."""
    import songview
    sng, lines = _converted("Zoids")
    song = songview.parse_sng(sng)
    hits, ties = [], []
    for vi, track in enumerate(song.tracks):
        current = 0
        for a, (p, r, _t) in enumerate(S._lap_rows(track, song.patterns)):
            n, i, cmd, dat = song.patterns[p][4 * r:4 * r + 4]
            if i:
                current = i
            if not GT_FIRST_NOTE <= n <= GT_LAST_NOTE:
                continue
            if cmd == CMD_SETWAVEPTR and current in (9, 11):
                hits.append((vi, p, r, current, dat))
            if cmd == 3 and current == 11 and (p, r) in ((0x26, 64),
                                                         (0x27, 9)):
                ties.append((p, r))
    assert sorted((h[1], h[2]) for h in hits) == [(0x1E, 73), (0x1E, 73),
                                                  (0x31, 9)], hits
    assert {h[3] for h in hits} == {9}
    (start,) = {h[4] for h in hits}
    assert sorted(ties) == [(0x26, 64), (0x27, 9)]
    wt = song.tables["WTBL"]
    stbl = song.tables["STBL"]
    prog = []
    for left, right in wt[start - 1:]:
        prog.append((left, right))
        if left == 0xFF:
            break

    def index(k):
        return stbl.index((k, 0x00)) + 1
    instr = S.instrument_calls(wt, song.instruments[8].wave_ptr)
    assert instr == ZOIDS_INSTRUMENT
    assert prog == S.skydive_note_row_program(instr, 3, 35, True, index)
    assert any("on the note row: 2 row(s), 1 program(s) [(3, 35, 9)]" in m
               for m in lines), [m for m in lines if "Skydive" in m]


def _store_frames(trace, nframes):
    """{voice: {frame: high byte}} for the original's skydive stores: a
    carried high byte exactly one below the one two frames earlier, in a
    run of at least four such frames two apart, plus the store before it."""
    out = {}
    for vi, v in enumerate(trace):
        fq = fidelity.register_timeline(v.freq_events, nframes)
        hits = {f for f in range(2, nframes)
                if fq[f] >> 8 == (fq[f - 2] >> 8) - 1 and fq[f - 2] >> 8}
        got = {}
        for f in sorted(hits):
            if f - 2 in hits:
                continue
            g = f
            while g + 2 in hits:
                g += 2
            if (g - f) // 2 + 1 >= 4:
                for x in range(f - 2, g + 1, 2):
                    got[x] = fq[x] >> 8
        out[vi] = got
    return out


@needs_corpus
@needs_siddump
@needs_gt2reloc
def test_the_packed_fall_from_the_note_row_names_the_originals_high_byte(
        tmp_path, monkeypatch):
    """Through gt2reloc and siddump, subtune 2, 15 s: the one window (35
    stores from frame 411) reads the original's high byte on every store
    frame at the startup lag -- and without the note-row program
    (`skydive_note_row_calls` returning None) on almost none."""
    seconds, sub = 15, 2
    n = seconds * 50
    orig = fidelity.run_siddump(CORPUS / "Zoids.sid", seconds, sub)
    stores = _store_frames(orig, n)
    assert len(stores[0]) == 35, len(stores[0])

    def agree(tag):
        sng, _ = _converted("Zoids")
        work = tmp_path / tag
        work.mkdir()
        packed = fidelity.pack_sid(sng, work)
        assert packed is not None and packed.exists(), tag
        ours = fidelity.run_siddump(packed, seconds, sub)
        lag = fidelity.startup_lag(orig, ours)[0]
        fq = fidelity.register_timeline(ours[0].freq_events, n + lag)
        return sum(fq[f + lag] >> 8 == hi for f, hi in stores[0].items())

    assert agree("emitted") == 35
    monkeypatch.setattr(S, "skydive_note_row_calls", lambda *a, **k: None)
    assert agree("without") <= 3
