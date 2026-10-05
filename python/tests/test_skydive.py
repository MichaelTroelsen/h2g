"""Bit $02's skydive: detected as a fallback to Warhawk's rise, and emitted as
a CMD_SETWAVEPTR program on the row each long note's window opens.

Hunter_Patrol $A2C9 (`detect._find_skydive`): in the last 9 ticks of a note
of at least 12, on every frame whose play-entry counter `$A426` is odd, the
player stores the note's frequency high byte into $D401 and decrements it.
Before this, `effect_rise` read False and nothing was emitted: siddump of the
original names 67A1 66DA 654C ... 5BA1 on alternate frames of every such
window and we played the vibrato straight through it (no high byte of 77
store frames on voice 1 agreed at -t 180, v0.5.510 + the merged drain).
"""
import pathlib
import sys

import pytest

from corpus import CORPUS, needs_corpus

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[1]))

import fidelity                                              # noqa: E402
from h2g import detect as D                                  # noqa: E402
from h2g.detect import Skydive, detect                       # noqa: E402
from h2g.goatwriter import skydive as S                      # noqa: E402
from h2g.goatwriter.constants import (CMD_SETWAVEPTR,        # noqa: E402
                                      GT_FIRST_NOTE, GT_LAST_NOTE, GT_REST)
from h2g.sidfile import load_sid                             # noqa: E402

PYTHON_ROOT = pathlib.Path(__file__).resolve().parents[1]

needs_siddump = pytest.mark.skipif(
    not pathlib.Path(fidelity.SIDDUMP).exists(),
    reason="no siddump on this machine (tools/siddump-rt, see its README)")
needs_gt2reloc = pytest.mark.skipif(
    not pathlib.Path(fidelity.GT2RELOC).exists(),
    reason="no gt2reloc on this machine")

# (MIN, LAST) read from each file's own block -- `CMP #MIN / BCC`, `CMP #LAST
# / BCS`. The block is byte-identical otherwise in all ten.
BLOCKS = {
    "5_Title_Tunes": (0x0C, 0x08),
    "Formula_1_Simulator": (0x10, 0x18),
    "Gremlins": (0x0C, 0x08),
    "Hunter_Patrol": (0x0C, 0x09),
    "Last_V8": (0x1F, 0x1E),
    "Last_V8_C128_version": (0x1F, 0x1E),
    "Master_of_Magic": (0x10, 0x12),
    "One_Man_and_his_Droid": (0x10, 0x18),
    "Proteus": (0x10, 0x18),
    "Zoids": (0x10, 0x18),
}


def _det(name):
    sid = load_sid(str(CORPUS / f"{name}.sid"))
    return sid, detect(sid, lambda *a, **k: None)


@needs_corpus
def test_the_block_is_read_in_exactly_the_ten_files_that_carry_it():
    found = {}
    for path in sorted(CORPUS.glob("*.sid")):
        sid = load_sid(str(path))
        try:
            det = detect(sid, lambda *a, **k: None)
        except Exception:
            continue                      # a file detect refuses has no block
        if det.skydive is not None:
            assert not det.effect_rise, path.name
            found[path.stem] = (det.skydive.min_length,
                                det.skydive.last_ticks)
    assert found == BLOCKS


@needs_corpus
def test_hunter_patrols_operands_and_counter():
    _sid, det = _det("Hunter_Patrol")
    assert det.skydive == Skydive(counter=0xA426, min_length=12,
                                  last_ticks=9)


@needs_corpus
def test_the_skydive_is_consulted_only_where_the_rise_matched_nothing(
        monkeypatch):
    """Warhawk has the rise and no skydive; and Hunter_Patrol, made to read
    a rise, no longer reads its skydive -- the fallback order, not just the
    shape, is what is pinned."""
    _sid, det = _det("Warhawk")
    assert det.effect_rise and det.skydive is None
    real = D._find_effect_routines

    def with_rise(sid, det):
        return (True,) + tuple(real(sid, det))[1:]
    monkeypatch.setattr(D, "_find_effect_routines", with_rise)
    _sid, det = _det("Hunter_Patrol")
    assert det.effect_rise and det.skydive is None


def test_the_store_count_stops_at_a_zero_high_byte():
    assert S.skydive_writes(27, 0, 0x68) == 14
    assert S.skydive_writes(27, 1, 0x68) == 13
    # `LDA savehi / BEQ out`: the stores read savehi .. 1
    assert S.skydive_writes(27, 0, 5) == 5


def _index(k):
    return 0x40 + k


def test_the_alternating_program_falls_from_the_note_and_comes_back():
    """Phase 1: frame 0 is the row's first call, the original's tick frame
    is frame 1 (store 0) -- so frames 0-2 sit on the note, store k is a
    `F2 k` on frame 1 + 2k and the frame after it a `F1 k` back up."""
    got = S.skydive_program(1, 4, True, _index)
    assert got == [(0x00, 0x00), (0x00, 0x00), (0x00, 0x00),
                   (0xF2, 0x41), (0xF1, 0x41),
                   (0xF2, 0x42), (0xF1, 0x42),
                   (0xF2, 0x43), (0xF1, 0x43),
                   (0xFF, 0x00)]


def test_the_holding_program_steps_once_and_leaves_the_frame_between():
    got = S.skydive_program(0, 4, False, _index)
    # store 0 and the frame after it move nothing (one 2-frame delay), then
    # `F2 1` on each store and a one-frame no-op between
    assert got == [(0x01, 0x80), (0xF2, 0x41), (0x00, 0x80),
                   (0xF2, 0x41), (0x00, 0x80), (0xF2, 0x41), (0xFF, 0x00)]


def _converted(name):
    import json
    import h2g.convert as C
    doc = json.loads((PYTHON_ROOT.parent / "presets.json").read_text())
    lines = []
    sng = C.convert(str(CORPUS / f"{name}.sid"), log=lines.append,
                    **fidelity._preset_opts(doc, f"{name}.sid"))
    return sng, lines


@needs_corpus
def test_hunter_patrol_points_each_long_note_nine_rows_before_its_end():
    """Fourteen notes on record 4 (GT 5) are 17 or 16 ticks long, seven a
    voice; each gets the pointer on the row 9 ticks before the next event,
    and every pointer names the one program (phase 1, 14 stores,
    alternating) the original's trace asks for."""
    import songview
    sng, lines = _converted("Hunter_Patrol")
    song = songview.parse_sng(sng)
    hits = []
    for vi, track in enumerate(song.tracks):
        rows = list(S._lap_rows(track, song.patterns))
        current = 0
        note_at = None
        for a, (p, r, _t) in enumerate(rows):
            n, i, cmd, dat = song.patterns[p][4 * r:4 * r + 4]
            if i:
                current = i
            if GT_FIRST_NOTE <= n <= GT_LAST_NOTE:
                note_at = (a, current)
            if cmd == CMD_SETWAVEPTR:
                end = next(e for e in range(a + 1, len(rows))
                           if song.patterns[rows[e][0]][4 * rows[e][1]]
                           != GT_REST)
                hits.append((vi, end - a, note_at[1], a - note_at[0], dat))
    assert len(hits) == 14, hits
    assert {h[0] for h in hits} == {0, 1}
    assert {h[1] for h in hits} == {9}           # the last 9 ticks
    assert {h[2] for h in hits} == {5}           # record 4
    assert {h[3] for h in hits} == {8, 9}        # dur 16 and 17, less 8
    (start,) = {h[4] for h in hits}
    wt = song.tables["WTBL"]
    stbl = song.tables["STBL"]
    prog = []
    for left, right in wt[start - 1:]:
        prog.append((left, right))
        if left == 0xFF:
            break

    def index(k):
        return stbl.index((k, 0x00)) + 1
    assert prog == S.skydive_program(1, 14, True, index)
    assert any("Skydive (bit $02).......: 14 window row(s)" in m
               for m in lines), lines


def _store_frames(trace, nframes):
    """{voice: {frame: high byte}} for every frame on which the ORIGINAL's
    gated high byte sits below the one its note attacked with."""
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
def test_the_packed_fall_names_the_originals_high_byte_frame_for_frame(
        tmp_path, monkeypatch):
    """Through gt2reloc and siddump, 30 s: every frame the original sits
    below its note's high byte (the stores 1..13 of three windows a voice)
    reads the same high byte in ours at the startup lag -- and without the
    plan (`skydive_plan` returning None) almost none does."""
    seconds = 30
    n = seconds * 50
    orig = fidelity.run_siddump(CORPUS / "Hunter_Patrol.sid", seconds, 0)
    stores = _store_frames(orig, n)
    assert len(stores[0]) >= 30 and len(stores[1]) >= 30, \
        {v: len(s) for v, s in stores.items()}

    def agree(sub):
        sng, _ = _converted("Hunter_Patrol")
        work = tmp_path / sub
        work.mkdir()
        packed = fidelity.pack_sid(sng, work)
        assert packed is not None and packed.exists(), sub
        ours = fidelity.run_siddump(packed, seconds, 0)
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
