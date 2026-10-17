"""A drum zeroes voice 3's frame counter, and the 1920-frame note stops falling.

Mega_Apocalypse's 640-row note on voice 3 (lap row 6720, frame 20161 of the
original, record 9 = GT 10, threshold 31) falls and swells for 1152 frames and
then sits at `$59xx` to its end, with a noise blip every 6 frames
(`C#6`, waveform `81`). Measured with a py65 trace of the player (subtune 0,
`$4AA6` per frame, `$02A6` = 1, v0.5.572; the frames agree with `siddump -v1`
register for register):

* at frame 1153 of the note voice 1 (X = 0) fetches a row with instrument
  record 14 (`0D 01 09 98 00 00 80`: effect byte `$80`), the voice-3 drum;
* from the next frame `$4E43` (`LDA $EC / BPL`, `$EC` = this voice's effect
  byte) reaches `LDA $BE / CMP #1 / BEQ fire / CMP #6 / BCC out / LDA #0 /
  STA $BE` for voice 1 on every frame it runs its effects;
* `$BE` is the cell the drum counts its period on AND voice 3's own frame
  counter (`$BC,X` with X = 2), which the fall tests against its threshold. At
  frame 1154 it holds `$82`, is past the period 6 and is zeroed, and from then
  on it counts 1..6 and is zeroed again: never near 31. No store follows (the
  frequency holds `$5905` for 766 frames) and the vibrato gate (19) is never
  reached either, so the swell is still;
* the drum blip itself is `$4E57`: `$48` into `$D40F` and `$81` into `$D412`.

So the model's 840 stores of that note are right to frame 1153 and no further.
"""
import json
import pathlib
import sys

import pytest

from corpus import CORPUS, needs_corpus

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[1]))

import fidelity                                              # noqa: E402
from h2g import detect as D, sidfile                         # noqa: E402
from h2g.goatwriter import counter_fall as C                 # noqa: E402
from h2g.goatwriter import counter_fall_laps as L            # noqa: E402

PYTHON_ROOT = pathlib.Path(__file__).resolve().parents[1]
MEGA = CORPUS / "Mega_Apocalypse.sid"

needs_siddump = pytest.mark.skipif(
    not pathlib.Path(fidelity.SIDDUMP).exists(),
    reason="no siddump on this machine (tools/siddump-rt, see its README)")
needs_gt2reloc = pytest.mark.skipif(
    not pathlib.Path(fidelity.GT2RELOC).exists(),
    reason="no gt2reloc on this machine")

DRUM = 15            # GT instrument number of record 14, a drum
NOTE_INSTR = 10      # record 9, GT 10


def _converted(**extra):
    import h2g.convert as Cv
    doc = json.loads((PYTHON_ROOT.parent / "presets.json").read_text())
    lines = []
    opts = fidelity._preset_opts(doc, "Mega_Apocalypse.sid")
    opts.update(extra)
    sng = Cv.convert(str(MEGA), log=lines.append, **opts)
    return sng, lines


def _counter_line(lines):
    said = [m for m in lines if m.startswith("Counter fall (bit $02)..:")
            and "row(s)" in m]
    assert len(said) == 1, lines
    return said[0]


# --- the drum's cell is a frame counter --------------------------------------

@needs_corpus
def test_mega_drum_counts_on_voice_3s_frame_counter():
    sid = sidfile.load_sid(str(MEGA))
    det = D.detect(sid, lambda *_: None)
    assert det.counter_fall.counter == 0xBC
    assert D.find_sfx_cell(sid, det) == 0xBE
    assert C.drum_counter_voice(sid, det) == 2
    # records 0 and 14 carry effect bit $80, and no fall record does
    assert C.drum_records(sid, det, 21) == {0, 14}
    assert not C.drum_records(sid, det, 21) & set(
        C.counter_fall_records(sid, det, 21))


@needs_corpus
def test_the_cell_the_drum_loads_must_be_the_cell_it_zeroes():
    """`LDA $BE ... STA $BE`: a store to another cell is not the shape."""
    import dataclasses
    sid = sidfile.load_sid(str(MEGA))
    det = D.detect(sid, lambda *_: None)
    at = sid.data.find(bytes.fromhex("A9 00 85 BE".replace(" ", "")))
    assert at > 0 and sid.data.count(bytes.fromhex("A5BEC901F00AC906")) == 1
    other = sid.data[:at + 3] + bytes([0xBF]) + sid.data[at + 4:]
    assert D.find_sfx_cell(dataclasses.replace(sid, data=other), det) == -1


@needs_corpus
@pytest.mark.parametrize("name", ["Thundercats.sid", "Bangkok_Knights.sid",
                                  "Nineteen.sid", "Commando.sid"])
def test_a_drum_cell_that_is_not_a_counter_cuts_nothing(name):
    """The other sfx-drum files have no counter fall at all, so the cell is
    not read for them as a counter."""
    path = CORPUS / name
    if not path.exists():
        pytest.skip(f"{name} not in the corpus")
    sid = sidfile.load_sid(str(path))
    det = D.detect(sid, lambda *_: None)
    assert C.drum_counter_voice(sid, det) is None


@needs_corpus
@pytest.mark.parametrize("cell, voice", [(0xBC, 0), (0xBD, 1), (0xBE, 2),
                                         (0xBB, None), (0xBF, None),
                                         (0x10, None), (-1, None)])
def test_the_drum_cell_names_the_voice_whose_counter_it_is(monkeypatch, cell,
                                                           voice):
    """Only a cell inside `$BC..$BE` is a frame counter; elsewhere (the
    other eight sfx-drum files) the drum counts on a cell of its own."""
    sid = sidfile.load_sid(str(MEGA))
    det = D.detect(sid, lambda *_: None)
    monkeypatch.setattr(C, "find_sfx_cell", lambda *_: cell)
    assert C.drum_counter_voice(sid, det) == voice


@needs_corpus
def test_no_period_read_no_drum_reading(monkeypatch):
    sid = sidfile.load_sid(str(MEGA))
    det = D.detect(sid, lambda *_: None)
    assert C.drum_counter_voice(sid, det) == 2
    monkeypatch.setattr(det, "sfx_period", 0)
    assert C.drum_counter_voice(sid, det) is None
    monkeypatch.setattr(det, "sfx_period", 6)
    monkeypatch.setattr(det, "effect_bit80", "pitch")
    assert C.drum_counter_voice(sid, det) is None


# --- drum_stops --------------------------------------------------------------

def _tracks(drum_row=None, drum_track=0, drum_end=None, rows=40, other=0,
            instr=DRUM):
    """Three tracks of one pattern each: track 2 a fall note from row 0,
    `drum_track` switching to `instr` at `drum_row` (back to a plain
    instrument at `drum_end`)."""
    pats = []
    lap = {}
    for ti in range(3):
        cells = []
        for r in range(rows):
            ins = 0
            if ti == 2 and r == 0:
                ins = NOTE_INSTR
            if ti == drum_track and drum_row is not None and r == drum_row:
                ins = instr
            if ti == drum_track and drum_end is not None and r == drum_end:
                ins = other or 3
            cells += [189, ins, 0, 0]
        pats.append(cells)
        lap[ti] = [(ti, r, 0, 0, 0) for r in range(rows)]
    return pats, lap


def _seg(track=2, rows=40, frames=3):
    return C._Segment(track, 0, rows, NOTE_INSTR, frames, 1, set(), [])


def _stops(pats, lap, seg, voice=2, drums=frozenset({DRUM}), period=6,
           thresholds=None):
    declined = {}
    n = C.drum_stops([seg], lap, pats, set(drums), voice, period,
                     {NOTE_INSTR: 31} if thresholds is None else thresholds,
                     declined)
    return n, declined


def test_a_drum_on_a_lower_voice_leaves_the_frame_after_its_fetch_its_store():
    """Voice 3 is processed first in a frame, so the frame after the drum's
    fetch still stores (the 1920-frame note's frame 1153: `$5A -> $59`)."""
    pats, lap = _tracks(drum_row=12, drum_track=0)
    seg = _seg()
    n, declined = _stops(pats, lap, seg)
    assert n == 1 and not declined
    assert seg.stop == 12 * 3 + 2
    assert seg.length == 38


def test_a_drum_on_a_higher_voice_takes_that_frames_store_too():
    pats, lap = _tracks(drum_row=12, drum_track=2)
    # the fall voice is voice 1 (counter $BD) and the drum is voice 3's
    pats[1][0 + 1] = NOTE_INSTR
    seg = _seg(track=1)
    n, declined = _stops(pats, lap, seg, voice=1)
    assert n == 1 and seg.stop == 12 * 3 + 1


def test_a_drum_already_playing_when_the_note_starts_stops_every_store():
    pats, lap = _tracks(drum_row=0, drum_track=1)
    seg = _seg()
    assert _stops(pats, lap, seg)[0] == 1
    assert seg.stop == 2
    assert C.fall_stores(seg.length, 31) == []


def test_the_earliest_drum_of_two_voices_is_the_stop():
    pats, lap = _tracks(drum_row=20, drum_track=0)
    for r in range(5, 40):
        pats[1][4 * r + 1] = DRUM
    seg = _seg()
    assert _stops(pats, lap, seg)[0] == 1
    assert seg.stop == 5 * 3 + 2


def test_a_drum_that_ends_inside_the_note_is_left_alone():
    """The counter starts over from zero and stores again once it is back at
    the threshold; that schedule is not modelled, so nothing is cut."""
    pats, lap = _tracks(drum_row=12, drum_track=0, drum_end=30)
    seg = _seg()
    n, declined = _stops(pats, lap, seg)
    assert n == 0 and seg.stop is None
    assert declined == {"a drum ends inside the note": 1}


def test_a_plain_instrument_on_the_other_voices_cuts_nothing():
    pats, lap = _tracks(drum_row=12, drum_track=0, instr=3)
    seg = _seg()
    assert _stops(pats, lap, seg) == (0, {})
    assert seg.stop is None and seg.length == 120


def test_a_threshold_the_counter_can_reach_under_the_drum_cuts_nothing():
    """The zeroed counter still counts to the period: a record whose
    threshold is that low stores between the drum's resets."""
    pats, lap = _tracks(drum_row=12, drum_track=0)
    seg = _seg()
    assert _stops(pats, lap, seg, thresholds={NOTE_INSTR: 6})[0] == 0
    assert seg.stop is None


def test_only_the_voice_whose_counter_the_drum_zeroes_is_cut():
    """The drum zeroes voice 2's counter (index 2); a note on track 2 read
    as voice 1's would be cut by the drum on track 1 if the voice were not
    checked."""
    pats, lap = _tracks(drum_row=12, drum_track=1)
    seg = _seg(track=2)
    assert _stops(pats, lap, seg, voice=1)[0] == 0
    assert seg.stop is None


def test_a_drum_in_another_subtune_is_not_this_notes():
    pats, lap = _tracks(drum_row=12, drum_track=0)
    # the note is subtune 1's voice 3 (track 5); the drum is subtune 0's
    seg = _seg(track=5)
    lap[5] = lap[2]
    assert _stops(pats, lap, seg)[0] == 0


def test_the_stop_leaves_the_stores_before_it_exactly_as_they_were():
    full = C.fall_stores(1920, 31)
    seg = _seg(rows=640)
    seg.stop = 1154
    cut = C.fall_stores(seg.length, 31)
    assert cut == [j for j in full if j < 1154]
    # four laps of 113 stores (frames 31..255) and 50 of the fifth (1055..1153)
    assert cut[-1] == 1153 and len(cut) == 4 * 113 + 50


# --- the final hold ----------------------------------------------------------

def _note_rows(stop=1154, usable=lambda e: True, holds=None, final=True):
    saved = L.ALTERNATION_FINAL_HOLD
    L.ALTERNATION_FINAL_HOLD = final
    try:
        return L.alternation_note_rows(
            1154 if stop is not None else 1920, 31, 19,
            {96 * k for k in range(1, 13)}, 1, 3, usable, 640, holds, stop)
    finally:
        L.ALTERNATION_FINAL_HOLD = saved


def test_the_cut_note_ends_in_a_hold_at_the_last_stores_count():
    """Store 501 (index; 4 laps of 113 and 50 of the fifth) is at frame 1153:
    count 245, call 1154 = row 384 tick 2, held through the note's last row
    with no exit row."""
    rows = _note_rows()
    final = [a for a in rows if a.kind == 'X' and a.final]
    assert [(a.e, a.delay, a.n, a.tied) for a in final] == \
        [(384, 2, 245, False)]
    assert [a.e for a in rows if a.kind == 'H' and a.e > 384] \
        == list(range(385, 640))
    assert not [a for a in rows if a.kind == 'Q' and a.e > 384]
    # the first lap's own hold is not final
    xs = [a for a in rows if a.kind == 'X']
    assert xs[-1].final and not any(a.final for a in xs[:-1])


def test_the_final_hold_moves_two_rows_back_where_its_row_takes_no_pointer():
    """Row 384 carries the pattern's tempo command. Two rows (six calls, the
    same parity in the loop that alternates on every call), not one."""
    rows = _note_rows(usable=lambda e: e != 384)
    final = [a for a in rows if a.kind == 'X' and a.final]
    assert [(a.e, a.delay) for a in final] == [(382, 2)]
    rows = _note_rows(usable=lambda e: e not in (384, 382))
    assert not [a for a in rows if a.final]


def test_no_final_hold_without_a_stop_or_with_it_switched_off():
    assert not [a for a in _note_rows(stop=None) if a.final]
    assert not [a for a in _note_rows(final=False) if a.final]


def test_a_final_hold_is_made_only_where_its_program_is_funded():
    rows = _note_rows(holds={(112, 1, False)})
    assert not [a for a in rows if a.final]
    rows = _note_rows(holds={(112, 1, False), (245, 2, False)})
    assert [a.n for a in rows if a.final] == [245]


def test_a_count_of_128_is_not_held_at_the_end_either():
    """`$8000`: no speed row says it. The store whose index is 128 (the
    count it leaves the voice at) is the last one of a note cut there."""
    j = C.fall_stores(600, 31)[128]
    rows = L.alternation_note_rows(j + 1, 31, 19, set(), 1, 3,
                                   lambda e: True, 200, None, j + 1)
    assert not [a for a in rows if a.final]
    rows = L.alternation_note_rows(j + 3, 31, 19, set(), 1, 3,
                                   lambda e: True, 200, None, j + 3)
    assert [a.n for a in rows if a.final] == [129]


# --- Mega_Apocalypse, end to end ---------------------------------------------

@needs_corpus
def test_mega_apocalypse_cuts_one_note_and_holds_it():
    _sng, lines = _converted()
    said = _counter_line(lines)
    assert "1 note(s) cut where a drum zeroes the counter" in said, said
    assert "(245, 2, False)" in said, said
    assert "7 dip size(s)" in said, said


@needs_corpus
def test_without_the_drum_reading_the_note_is_not_cut(monkeypatch):
    monkeypatch.setattr(C, "drum_counter_voice", lambda *_: None)
    _sng, lines = _converted()
    said = _counter_line(lines)
    assert "cut where a drum" not in said, said
    assert "(245, 2, False)" not in said, said


@needs_corpus
def test_the_swell_loses_no_loop_to_the_final_hold():
    _sng, lines = _converted()
    swell = [m for m in lines if m.startswith("Expanding vibrato loops")][0]
    assert "table full" not in swell, swell
    import re
    assert int(re.search(r" on (\d+) wavetable loop", swell).group(1)) >= 42


@needs_corpus
@needs_siddump
@needs_gt2reloc
def test_packed_the_note_holds_the_originals_high_byte_to_its_end(tmp_path):
    """Through gt2reloc and siddump, 450 s: the 1920-frame note's frames
    1154-1919 are `$59` in the original but for the drum's blip (`$48`, every
    6 frames, 128 of them), and ours is `$59` on every one of the others.
    Before the cut and the hold: 0 of 766 frames agreed (the swell sat
    around `$33`)."""
    work = tmp_path / "packed"
    work.mkdir()
    packed = fidelity.pack_sid(_converted()[0], work)
    assert packed is not None and packed.exists()
    ours = fidelity.run_siddump(packed, 452, 0)
    orig = fidelity.run_siddump(MEGA, 450, 0)
    lag = fidelity.startup_lag(orig, ours)[0]
    fo = fidelity.register_timeline(orig[2].freq_events, 22500)
    fu = fidelity.register_timeline(ours[2].freq_events, 22600)
    start = 20160
    best = 0
    blips = 0
    for off in range(-3, 4):
        same = other = 0
        for d in range(1154, 1920):
            o = fo[start + d] >> 8
            if o == 0x48:
                continue
            other += 1
            same += o == (fu[start + d + lag + off] >> 8)
        if same > best:
            best, n = same, other
    for d in range(1154, 1920):
        blips += (fo[start + d] >> 8) == 0x48
    assert blips == 128
    assert best == n == 638, (best, n)
