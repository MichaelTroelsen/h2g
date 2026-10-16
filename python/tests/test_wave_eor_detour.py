"""Rasputin's R = 10 and R = 60 notes: the gate's skip, mended by a detour.

The EOR toggle follows the original's outer gate, which `$FE nn` restarts and
which skips one frame in R + 1 (`wave_eor.gate_tick`). R = 2, 3 and 5 skip so
often that a ring of the toggles' schedule is laid out for them
(`GATE_FAMILIES`); every other R (10, 60, 120, 6) is read as a gate that does
not skip inside a note, and a note whose window holds a skip has every toggle
after it a frame off. The skip lands on a ROW when R is even, so a
`CMD_SETWAVEPTR` on that row (`eor_skip_detours`) puts the R = 0 ring back on
the original's frames; a note whose FETCH is the skip row (`m` on a multiple of
R) takes a late first toggle from `clock_residue` instead.

These tests pin the library's detour programs, the residues, the pass on
synthetic patterns, its placement on the converted Rasputin, and -- on the
packed song, traced -- the frames it moves.
"""
import pathlib
import sys
from types import SimpleNamespace

import pytest

from corpus import CORPUS, needs_corpus  # noqa: E402

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[1]))

from h2g.detect import detect  # noqa: E402
from h2g.goatwriter import _wavetable_entries  # noqa: E402
from h2g.goatwriter import wave_eor as W  # noqa: E402
from h2g.goatwriter.constants import (CMD_SETTEMPO, CMD_SETWAVEPTR,  # noqa: E402
                                      CMD_VIBRATO, GT_REST)
from h2g.sidfile import load_sid  # noqa: E402

RASPUTIN = CORPUS / "Rasputin.sid"
MULT = 2
N = 0x60
REST = [GT_REST, 0, 0, 0]
WAVE, ALT = 0x41, 0x59


def _calls(entries, start, n, firstwave=0, initial=0):
    """`W.program_waves` is the unit under test elsewhere; this is the same
    reading written out again from gplay.c:697-712 so the tests do not check
    it against itself."""
    out, wave, at = [], initial, start
    if firstwave:
        out.append(firstwave)
        wave = firstwave
    guard = 0
    while len(out) < n:
        guard += 1
        assert guard < 50 * n
        left, right = entries[at - 1]
        if left == 0xFF:
            at = right
            assert at, "stopped"
            continue
        if 1 <= left <= 0x0F:
            out += [wave] * (left + 1)
        else:
            wave = left or wave
            out.append(wave)
        at += 1
    return out[:n]


# --- the library -----------------------------------------------------------------

def test_the_second_ring_of_r2_is_the_first():
    """R = 2's nodes are all three frames, so its two rings (the toggle's
    working call keeps its parity) hold what one holds: the second is the
    first, and the library is five rows shorter than it was."""
    lib = W.eor_library([(WAVE, ALT)], MULT, 1)
    assert len(lib.left) == 44
    for s in (0, 1):
        assert lib.nodes[(WAVE, 2, s, 0)] == lib.nodes[(WAVE, 2, s, 1)]
    # ...and no other R shares: R 3 and R 5 have a different hold in each node
    for R in (3, 5):
        ats = [at for (_w, r, _s, _x), at in lib.nodes.items() if r == R]
        assert len(set(ats)) == len(ats)


def test_the_detours_hold_the_state_three_frames_then_enter_the_ring():
    lib = W.eor_library([(WAVE, ALT)], MULT, 1, detours=True)
    assert len(lib.left) == 44 + 6
    entries = list(zip(lib.left, lib.right))
    for s, (held, other) in enumerate(((WAVE, ALT), (ALT, WAVE))):
        at = lib.detours[(WAVE, s)]
        got = _calls(entries, at, 6 + 8)
        # the state written and held 3 frames (6 calls), then the ring's
        # other node (2 frames a node) and back
        assert got == [held] * 6 + [other] * 4 + [held] * 4, s
        # entered a row in, it is the plain wait: 5 calls of the state the
        # voice already holds (nothing is written)
        wait = _calls(entries, at + 1, 5 + 4, initial=held)
        assert wait == [held] * 5 + [other] * 4, s
        assert lib.owner[at - 1] == ("d", WAVE, s)
    # without them the library is the rings alone
    assert not W.eor_library([(WAVE, ALT)], MULT, 1).detours


def test_ring0_waves_finds_the_instruments_that_toggle_with_no_ring_of_their_own():
    lib = W.eor_library([(WAVE, ALT)], MULT, 1, detours=True)
    entries = list(zip(lib.left, lib.right))
    own = len(entries) + 1
    entries += [(WAVE, 0), (WAVE, 0), (0xFF, lib.nodes[(WAVE, 0, 1, 0)])]
    starts = {1: own,                                    # lead, jump into R 0
              2: lib.nodes[(WAVE, 0, 0, 0)],             # the node itself
              3: lib.detours[(WAVE, 0)] + 1,             # a detour, past a row
              4: lib.nodes[(WAVE, 3, 0, 1)],             # R 3's ring: not R 0
              5: len(entries) + 1}
    entries += [(WAVE, 0), (0xFF, 0)]                    # stops: no ring
    assert W.ring0_waves(entries, starts, lib) == {1: WAVE, 2: WAVE, 3: WAVE}


def test_program_waves_reads_the_wavetable_as_gplay_does():
    entries = [(0x41, 0), (0x02, 0), (0x59, 0), (0x00, 0), (0xFF, 1)]
    # waveform (1 call), delay 2 (3 calls), waveform, keep (1 call), jump
    assert W.program_waves(entries, 1, 8) == [0x41] * 4 + [0x59] * 2 + [0x41] * 2
    # a firstwave owns the attack call and the entries begin the next
    assert W.program_waves(entries, 1, 3, firstwave=9) == [9, 0x41, 0x41]
    # a stop holds the waveform for ever
    assert W.program_waves([(0x41, 0), (0xFF, 0)], 1, 4) == [0x41] * 4


# --- the residue -------------------------------------------------------------------

def _clock(R, restart_row=0):
    return SimpleNamespace(gate_restarts={
        "groups": 1, "rows": [100, 100, 100],
        "restarts": {0: [(restart_row, 2, R)]}})


@pytest.mark.parametrize("R,row,phase,want", [
    # R = 10: the skip falls after working call 10, i.e. between the fetch and
    # its first toggle when the note fetches ON it (m = 10): two frames, not
    # one, on phase 0, and three, not two, on phase 1
    (10, 5, 0, W.EorPhase(0, 2, 0, 0)),
    (10, 5, 1, W.EorPhase(1, 3, 0, 0)),
    # anywhere else in the cycle the first toggle is on time
    (10, 4, 0, W.EorPhase(0, 1, 0, 0)),
    (10, 4, 1, W.EorPhase(1, 2, 0, 0)),
    (10, 6, 0, W.EorPhase(0, 1, 0, 0)),
    # R = 60 the same, one note in thirty
    (60, 30, 0, W.EorPhase(0, 2, 0, 0)),
    (60, 30, 1, W.EorPhase(1, 3, 0, 0)),
    (60, 29, 1, W.EorPhase(1, 2, 0, 0)),
    # a ring's R keeps its own phase and position
    (5, 3, 0, W.EorPhase(0, 1, 5, 2)),
])
def test_a_note_fetched_on_the_skip_row_toggles_late(R, row, phase, want):
    assert W.clock_residue(_clock(R), 0, row, phase) == want


def test_the_residue_follows_the_restart_not_the_song():
    det = _clock(10, restart_row=1792)
    assert W.clock_residue(det, 0, 1792 + 5, 0) == W.EorPhase(0, 2, 0, 0)
    assert W.clock_residue(det, 0, 1792 + 4, 0) == W.EorPhase(0, 1, 0, 0)


@needs_corpus
def test_the_late_first_toggle_enters_the_library_by_a_row():
    """Phase 0 two frames to the toggle is the R = 0 ring's own node; phase 1
    three frames is the detour -- neither needs a block of its own."""
    sid = load_sid(str(RASPUTIN))
    det = detect(sid, log=lambda m: None)
    lib = W.eor_library([(WAVE, ALT)], MULT, 1, detours=True)
    base = _wavetable_entries(sid, det, 10, True, "gts5", [], MULT,
                              start=80, budget=40)
    for eor, want in ((W.EorPhase(0, 2, 0, 0), lib.nodes[(WAVE, 0, 0, 0)]),
                      (W.EorPhase(1, 3, 0, 0), lib.detours[(WAVE, 0)])):
        got = W.wave_eor_block(sid, det, 10, eor, base, MULT, 80, 40,
                               library=lib)
        assert got == want, eor
        # one row in where the firstwave has sounded the attack call
        assert W.wave_eor_block(sid, det, 10, eor, base, MULT, 80, 40,
                                written=True, library=lib) == want + 1
        entries = list(zip(lib.left, lib.right))
        calls = _calls(entries, got, 12)
        if eor.phase == 0:
            assert calls == [WAVE] * 4 + [ALT] * 4 + [WAVE] * 4
        else:
            assert calls == [WAVE] * 6 + [ALT] * 4 + [WAVE] * 2


# --- the pass on synthetic patterns --------------------------------------------------

def _fixture(R=10, first_tempo=4, note_tempo=4, rest_tempo=4, phase=0,
             extra=None, twice=False):
    """One subtune whose gate restarts at row 0 with `R`, voice 0 playing a
    record-1 note of four rows on row 4 (working call 8: its second row is
    the skip row at R = 10). `phase` 1 puts a four-row note of instrument 1
    before it, flipping the counter, and the note itself is instrument 2,
    whose program is the ring entered whole. Returns (args, library, rows)."""
    lib = W.eor_library([(WAVE, ALT)], MULT, 1, detours=True)
    entries = list(zip(lib.left, lib.right))
    own = len(entries) + 1
    entries += [(WAVE, 0), (WAVE, 0), (0xFF, lib.nodes[(WAVE, 0, 1, 0)])]
    starts = {1: own, 2: lib.nodes[(WAVE, 0, 0, 0)]}
    data = bytearray(16)
    data[2], data[7] = WAVE, 0x02
    data[10], data[15] = WAVE, 0x02
    sid = SimpleNamespace(data=bytes(data))
    det = SimpleNamespace(
        wave_eor=SimpleNamespace(mask=ALT ^ WAVE), instr_start=0,
        instr_stride=8, effect_drum=False,
        gate_restarts={"groups": 1, "rows": [8, 8, 8],
                       "restarts": {0: [(0, 2, R)]}})
    rows = [list(REST) for _ in range(8)]
    if phase:
        rows[0] = [N, 1, 0, 0]
        rows[4] = [N + 1, 2, 0, 0]
    else:
        rows[4] = [N + 1, 1, 0, 0]
    for k, cmd in (extra or {}).items():
        rows[k][2:] = cmd
    pat0 = [b for r in rows for b in r] + [0xFF, 0, 0, 0]
    # the tempos ride voice 1, as they do in the converted song: global ones
    # (operand below $80) set every voice's row length
    trows = [list(REST) for _ in range(8)]
    trows[0][2:] = [CMD_SETTEMPO, first_tempo]
    trows[4][2:] = [CMD_SETTEMPO, note_tempo]
    trows[5][2:] = [CMD_SETTEMPO, rest_tempo]
    tempo = [b for r in trows for b in r] + [0xFF, 0, 0, 0]
    quiet = [b for r in [list(REST) for _ in range(8)] for b in r] + [0xFF, 0, 0, 0]
    patterns = [pat0, tempo, quiet]
    plays = [0, 0] if twice else [0]
    if twice:
        det.gate_restarts["rows"] = [16, 16, 16]
    tracks = [plays + [0xFF, 0], [1] * len(plays) + [0xFF, 0],
              [2] * len(plays) + [0xFF, 0]]
    args = (None, None, tracks, patterns, 2, 0, None)
    return sid, det, args, entries, starts, {1: 9, 2: 9}, lib, None


def _run(**kw):
    sid, det, a, entries, starts, fw, lib, _ins = _fixture(**kw)
    got = W.eor_skip_detours(sid, det, a[2], a[3], 2, 0, None, entries,
                             starts, fw, lib, MULT)
    return got, a, lib


def _cmd(pat, k):
    return pat[4 * k + 2], pat[4 * k + 3]


def test_phase_0_skip_row_waits_out_the_frame_in_the_detour():
    """The toggle on the skip row's second call is a frame late: the voice
    holds the state it has five calls and the ring goes on from the other."""
    (patterns, tracks), a, lib = _run()
    assert _cmd(patterns[0], 5) == (CMD_SETWAVEPTR,
                                    lib.detours[(WAVE, 1)] + 1)
    # nothing else moves, the original is a copy
    assert [_cmd(patterns[0], k) for k in range(8) if k != 5] \
        == [_cmd(a[3][0], k) for k in range(8) if k != 5]
    assert _cmd(a[3][0], 5) == (0, 0)


def test_a_row_that_starts_a_call_late_enters_the_ring_instead():
    """Our tempo runs round to whole calls, so the skip row starts 0 to 2
    calls after the original's. One late: the ring's own node already holds
    four calls; two late: its delay row holds three."""
    for note_tempo, want in ((5, 0), (6, 1)):
        (patterns, _t), _a, lib = _run(note_tempo=note_tempo)
        ring = lib.nodes[(WAVE, 0, 1, 0)]
        assert _cmd(patterns[0], 5) == (CMD_SETWAVEPTR, ring + want), \
            note_tempo


def test_a_row_too_far_off_the_original_is_left_alone():
    (patterns, tracks), a, _lib = _run(note_tempo=7)         # 3 calls late
    assert patterns == a[3]


def test_phase_1_skip_row_writes_the_state_and_holds_it_three_frames():
    (patterns, _t), _a, lib = _run(phase=1, note_tempo=5)    # one call late
    assert _cmd(patterns[0], 5) == (CMD_SETWAVEPTR,
                                    lib.detours[(WAVE, 1)])
    (patterns, _t), _a, lib = _run(phase=1, note_tempo=6)    # two late
    assert _cmd(patterns[0], 5) == (CMD_SETWAVEPTR,
                                    lib.detours[(WAVE, 1)] + 1)


def test_a_gate_with_a_ring_of_its_own_is_not_touched():
    for R in (2, 3, 5):
        (patterns, tracks), a, _lib = _run(R=R)
        assert patterns == a[3], R


def test_a_note_whose_window_holds_no_skip_is_not_touched():
    (patterns, _t), a, _lib = _run(R=60)
    assert patterns == a[3]


def test_the_column_in_use_is_kept():
    (patterns, _t), a, _lib = _run(extra={5: [3, 7]})        # a tone portamento
    assert patterns == a[3]


def test_a_running_effect_is_not_ended_by_the_pointer():
    """An empty column ends a vibrato set on the row before; the pointer does
    not, so the row is left alone."""
    (patterns, _t), a, _lib = _run(extra={4: [CMD_VIBRATO, 0x24]})
    assert all(_cmd(patterns[0], k) == _cmd(a[3][0], k) for k in range(8))


def test_a_program_that_is_not_the_one_the_walk_names_is_not_mended():
    """Instrument 2's program is phase 1's; the walk says phase 0 (counter 0
    on a first note): the toggles are not where the clock puts them, and a
    jump into the middle would only add a second error."""
    sid, det, a, entries, starts, fw, lib, _ins = _fixture()
    starts[1] = lib.nodes[(WAVE, 0, 0, 0)]
    got = W.eor_skip_detours(sid, det, a[2], a[3], 2, 0, None, entries,
                             starts, fw, lib, MULT)
    assert got[0] == a[3]


def test_nothing_is_done_off_the_two_call_frame():
    """The detours' lengths are calls of a -S2 frame."""
    sid, det, a, entries, starts, fw, lib, _ins = _fixture()
    got = W.eor_skip_detours(sid, det, a[2], a[3], 2, 0, None, entries,
                             starts, fw, lib, 1)
    assert got[0] == a[3] and got[1] == a[2]
    assert W.has_skip_rows(det) and W.has_skip_rows(det, 2)
    assert not W.has_skip_rows(det, 1) and not W.has_skip_rows(det, 3)
    assert not W.has_skip_rows(_clock(5)) and not W.has_skip_rows(_clock(3))
    assert W.has_skip_rows(_clock(60))


def test_a_pattern_wanted_two_ways_is_copied():
    """Played twice with only the first play's window holding a skip row: the
    second play keeps the original, the first is repointed at a copy."""
    (patterns, tracks), a, lib = _run(twice=True)
    assert len(patterns) == len(a[3]) + 1
    assert tracks[0][1] == 0 and tracks[0][0] == len(a[3])
    assert patterns[0] == a[3][0]
    assert _cmd(patterns[len(a[3])], 5)[0] == CMD_SETWAVEPTR


# --- the converted Rasputin ------------------------------------------------------------

def _convert_spied(monkeypatch):
    from test_wave_eor_emit import _opts
    from h2g.convert import convert
    seen = {}
    real = W.eor_skip_detours

    def spy(sid, det, tracks, patterns, *args, **kw):
        seen["det"], seen["before"], seen["tracks_before"] = det, patterns, tracks
        out = real(sid, det, tracks, patterns, *args, **kw)
        seen["after"], seen["tracks"] = out
        seen["library"] = args[6]
        return out
    monkeypatch.setattr(W, "eor_skip_detours", spy)
    log = []
    blob = convert(str(RASPUTIN), log=log.append, **_opts())
    return blob, seen, log


@pytest.fixture(scope="module")
def converted():
    mp = pytest.MonkeyPatch()
    try:
        yield _convert_spied(mp)
    finally:
        mp.undo()


@needs_corpus
def test_rasputin_places_the_detours_on_skip_rows_only(converted):
    """Every row the pass changed is a rest row whose empty command column
    became a `CMD_SETWAVEPTR` into the library, and sits on a row of its note
    where the gate (R 10, 60, 120 or 6) skips."""
    _blob, seen, log = converted
    lib, det = seen["library"], seen["det"]
    before, after = seen["before"], seen["after"]
    lo, hi = lib.start, lib.start + len(lib.left)
    changed = []
    for p, (pb, pa) in enumerate(zip(before, after)):
        assert len(pb) == len(pa)
        for k in range(len(pb) // 4):
            if pb[4 * k:4 * k + 4] != pa[4 * k:4 * k + 4]:
                assert pb[4 * k] == GT_REST and pb[4 * k + 2:4 * k + 4] == [0, 0]
                assert pa[4 * k + 2] == CMD_SETWAVEPTR
                assert lo <= pa[4 * k + 3] < hi
                changed.append((p, k))
    # copies are appended, never inserted
    assert after[:len(before)] != before or not changed
    assert any("EOR skip rows" in line for line in log)
    placed = sum(1 for pa in after for k in range(len(pa) // 4)
                 if pa[4 * k] != 0xFF and pa[4 * k + 2] == CMD_SETWAVEPTR
                 and lo <= pa[4 * k + 3] < hi)
    assert placed >= 40, placed
    # on a skip row: rebuild each pattern copy's rows from the finished
    # orderlists and ask the clock
    tracks = seen["tracks"]
    laps = {}
    skip_rows = 0
    for ti, track in enumerate(tracks):
        row = 0
        for _t, pos, play, p in W._plays([track], after):
            pat = after[p]
            for k in range(len(pat) // 4):
                if pat[4 * k] == 0xFF:
                    break
                if (pat[4 * k + 2] == CMD_SETWAVEPTR
                        and lo <= pat[4 * k + 3] < hi):
                    m, R, frames = W.skip_clock(det, ti // 3, row)
                    assert R % 2 == 0 and R not in W.GATE_FAMILIES
                    assert m % R == 0, (ti, row, m, R)
                    skip_rows += 1
                row += 1
        laps[ti] = row
    assert skip_rows >= 40


def _agreement(seen, tmp_path, seconds=180):
    """Lost frames of the packed song's record-10 notes, by the R of their
    window, against the original: the waveform (`& $FE`) on every frame from
    the attack up to the note's last tick, at the song's startup lag."""
    import fidelity as F
    from test_wave_eor_emit import KEY, MULT as M, REC10, RASPUTIN as SID, _walk
    blob = seen["blob"]
    det = seen["det"]
    tracks, patterns = seen["args"][2], seen["args"][3]
    rows, _ = W._event_rows(tracks, patterns, 0)
    sng, _patched = F.legalise_restarts(blob)
    tmp_path.mkdir(parents=True, exist_ok=True)
    packed = F.pack_sid(sng, tmp_path, F.GT2RELOC, M)
    assert packed is not None
    orig = F.run_siddump(SID, seconds, 0)
    ours = F.run_siddump(packed, seconds, 0, calls=M)
    lag = F.startup_lag(orig, ours)[0]
    n = seconds * 50
    v, key = KEY[REC10]
    tlo = F.register_timeline(orig[v].wf_events, n)
    tlu = F.register_timeline(ours[v].wf_events, n)
    tle = F.register_timeline(orig[v].adsr_events, n)
    att = sorted(orig[v].attack_frames)
    notes = [(a, att[j + 1] if j + 1 < len(att) else n)
             for j, a in enumerate(att) if tle[a] == key]
    walked = [(k_, key_, length) for ti, key_, k_, gt, _i, length, _p, q, _t
              in _walk(seen) if ti == 0 and gt == REC10 and not q]
    lost, total = {}, {}
    for (a, e), (k_, key_, length) in zip(notes, walked):
        if e + lag + 2 >= n:
            continue
        m, R = W.gate_phase(det, 0, rows[(key_, k_)])
        lo = a + W.gate_tick(R, m + 2 * (length - 1)) - W.gate_tick(R, m)
        for k in range(a, min(lo, e)):
            total[R] = total.get(R, 0) + 1
            lost[R] = lost.get(R, 0) + ((tlo[k] & 0xFE) != (tlu[k + lag] & 0xFE))
    return lost, total


@needs_corpus
def test_the_packed_song_follows_the_original_through_the_skip(monkeypatch,
                                                              tmp_path):
    """Packed and traced (180 s of subtune 0). The R = 10 and R = 60 notes of
    record 10 lost 100 and 111 of their 422 and 1348 frames to the gate's skip
    at 881bbe1 (the ring and loop read as a gate that never skips); with the
    late first toggle and the detours they lose 38 and 22."""
    import fidelity as F
    if not pathlib.Path(F.GT2RELOC).exists():
        pytest.skip("gt2reloc not found")
    if not pathlib.Path(F.SIDDUMP).exists():
        pytest.skip("siddump not found")
    from test_wave_eor_emit import _convert
    blob, seen = _convert(monkeypatch)
    seen["blob"] = blob
    seen["det"] = seen["args"][1]
    lost, total = _agreement(seen, tmp_path)
    assert total[10] >= 400 and total[60] >= 1300, total
    assert lost[10] <= 60, lost
    assert lost[60] <= 40, lost
