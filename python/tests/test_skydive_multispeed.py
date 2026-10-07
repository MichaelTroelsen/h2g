"""Bit $02's skydive above -S1 (`goatwriter.skydive`).

Until this, `skydive_plan` declined every file packed above -S1 ("not
emitted (-S2)"): Last_V8, Last_V8_C128_version, Master_of_Magic and
One_Man_and_his_Droid, all rows of 2 frames packed at -S2. A rate read out of
a player is per frame and a wavetable steps per play call, so each frame of
the program is now `multiplier` calls and each speed `1/multiplier` of the
frame's movement -- and the frame the program counts as 0 is short by the
call the packed player's init spent (`skydive_row_offset`).

Measured at -t 180 under presets, siddump lag-aligned, frames on which the
original's gated high byte sits below its note's (tests/test_skydive.py's
`_store_frames`), our high byte agreeing, before -> after:
Master_of_Magic voice 0 0/264 -> 264/264; One_Man_and_his_Droid voice 0
14/308 -> 266/308 (the 42 left are the one row the log calls mixed or
occupied), voice 1 12/264 -> 264/264. Both Last_V8s are declined (the program
needs 124 / 122 wavetable steps with 38 free) and do not move.
"""
import json
import pathlib
import sys

import pytest

from corpus import CORPUS, needs_corpus

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[1]))

import fidelity                                              # noqa: E402
from h2g.goatwriter import skydive as S                      # noqa: E402
from h2g.goatwriter.constants import CMD_SETWAVEPTR          # noqa: E402

PYTHON_ROOT = pathlib.Path(__file__).resolve().parents[1]

needs_siddump = pytest.mark.skipif(
    not pathlib.Path(fidelity.SIDDUMP).exists(),
    reason="no siddump on this machine (tools/siddump-rt, see its README)")
needs_gt2reloc = pytest.mark.skipif(
    not pathlib.Path(fidelity.GT2RELOC).exists(),
    reason="no gt2reloc on this machine")


def test_a_frames_fall_is_divided_by_the_multiplier_where_it_is_encoded():
    assert S.skydive_speed(3) == (3, 0x00)          # -S1: the old (k, $00)
    assert S.skydive_speed(3, 2) == (1, 0x80)       # $300 a frame, $180 a call
    assert S.skydive_speed(30, 2) == (15, 0x00)
    assert S.skydive_speed(1, 3) is None            # $100 / 3 is no speed
    assert S.skydive_speed(0x80) is None            # $8000 reads as calculated


def test_the_rows_first_call_is_the_last_of_its_frame_at_s2():
    assert S.skydive_row_offset(1) == 0
    assert S.skydive_row_offset(2) == 1
    assert S.skydive_row_offset(3) == 1


def _index(k):
    return 0x40 + k


def test_the_alternating_program_spends_two_calls_a_frame_but_one_on_frame_0():
    got = S.skydive_program(1, 3, True, _index, 2)
    note = (0x00, 0x00)
    assert got == [note,                             # frame 0: one call
                   note, note, note, note,           # frames 1, 2
                   (0xF2, 0x41), (0xF2, 0x41), (0xF1, 0x41), (0xF1, 0x41),
                   (0xF2, 0x42), (0xF2, 0x42), (0xF1, 0x42), (0xF1, 0x42),
                   (0xFF, 0x00)]
    # and at -S1 it is the program tests/test_skydive.py pins
    assert S.skydive_program(1, 3, True, _index) == S.skydive_program(
        1, 3, True, _index, 1)


def test_the_holding_programs_still_frames_are_delays_counted_in_calls():
    got = S.skydive_program(0, 3, False, _index, 2)
    # frames 0-1 still (1 + 2 calls), F2 on frame 2, frame 3 still, F2 on 4
    assert got == [(0x02, 0x80), (0xF2, 0x41), (0xF2, 0x41), (0x01, 0x80),
                   (0xF2, 0x41), (0xF2, 0x41), (0xFF, 0x00)]


def _converted(name):
    import h2g.convert as C
    doc = json.loads((PYTHON_ROOT.parent / "presets.json").read_text())
    lines = []
    sng = C.convert(str(CORPUS / f"{name}.sid"), log=lines.append,
                    **fidelity._preset_opts(doc, f"{name}.sid"))
    return sng, lines


def _sky(lines):
    return [m for m in lines if m.startswith("Skydive (bit $02)")]


@needs_corpus
@pytest.mark.parametrize("name,rows,program", [
    ("Master_of_Magic", 4, (1, 18, True)),
    ("One_Man_and_his_Droid", 8, (2, 24, True)),
])
def test_the_s2_files_get_their_program_at_two_calls_a_frame(
        name, rows, program):
    import songview
    sng, lines = _converted(name)
    (msg,) = _sky(lines)
    assert f"{rows} window row(s)" in msg and str(program) in msg, msg
    song = songview.parse_sng(sng)
    starts = {p[r + 3] for p in song.patterns for r in range(0, len(p), 4)
              if p[r + 2] == CMD_SETWAVEPTR}
    stbl = song.tables["STBL"]
    wt = song.tables["WTBL"]

    def index(k):
        return stbl.index(S.skydive_speed(k, 2)) + 1
    want = S.skydive_program(*program, index, 2)
    found = [s for s in starts
             if [tuple(e) for e in wt[s - 1:s - 1 + len(want)]] == want]
    assert len(found) == 1, (starts, want)


@needs_corpus
@pytest.mark.parametrize("name", ["Last_V8", "Last_V8_C128_version"])
def test_last_v8_is_declined_on_the_wavetable_not_the_multiplier(name):
    _sng, lines = _converted(name)
    (msg,) = _sky(lines)
    assert "past MAX_TABLELEN, not emitted" in msg, msg
    assert "-S2" not in msg, msg


def _store_frames(trace, nframes):
    out = {}
    for vi, v in enumerate(trace):
        fq = fidelity.register_timeline(v.freq_events, nframes)
        wf = fidelity.register_timeline(v.wf_events, nframes)
        onset, got = 0, {}
        for f in range(1, nframes):
            if wf[f] & 1 and not wf[f - 1] & 1:
                onset = fq[f] >> 8
            hi = fq[f] >> 8
            if wf[f] & 1 and hi < onset and onset - hi <= 0x20:
                got[f] = hi
        out[vi] = got
    return out


@needs_corpus
@needs_siddump
@needs_gt2reloc
def test_the_s2_fall_names_the_originals_high_byte_frame_for_frame(
        tmp_path, monkeypatch):
    """One_Man_and_his_Droid, 30 s, packed at -S2 and traced at -m2: every
    frame the original sits below its note's high byte reads the same high
    byte in ours at the startup lag, on both voices -- and without the plan
    almost none does."""
    seconds = 30
    n = seconds * 50
    orig = fidelity.run_siddump(CORPUS / "One_Man_and_his_Droid.sid",
                                seconds, 0)
    stores = _store_frames(orig, n)
    assert len(stores[0]) >= 60 and len(stores[1]) >= 60, \
        {v: len(s) for v, s in stores.items()}

    def agree(sub):
        sng, _ = _converted("One_Man_and_his_Droid")
        work = tmp_path / sub
        work.mkdir()
        packed = fidelity.pack_sid(sng, work, multiplier=2)
        assert packed is not None and packed.exists(), sub
        # one second longer: the window cut at frame 1500 is read at f + lag
        ours = fidelity.run_siddump(packed, seconds + 1, 0, calls=2)
        lag = fidelity.startup_lag(orig, ours)[0]
        out = {}
        for vi in (0, 1):
            fq = fidelity.register_timeline(ours[vi].freq_events, n + lag)
            out[vi] = sum(fq[f + lag] >> 8 == hi
                          for f, hi in stores[vi].items())
        return out

    emitted = agree("emitted")
    assert emitted == {0: len(stores[0]), 1: len(stores[1])}, (
        emitted, {v: len(s) for v, s in stores.items()})
    monkeypatch.setattr(S, "skydive_plan", lambda *a, **k: None)
    without = agree("without")
    assert all(without[v] <= len(stores[v]) // 10 for v in (0, 1)), without
