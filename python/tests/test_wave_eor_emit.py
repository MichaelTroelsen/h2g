"""Effect bit $02's EOR toggle (Rasputin $C35A), EMITTED with a per-note phase.

The block EORs `#$18` (triangle + TEST) into the voice's stored waveform on
every second effect call, counted on a per-voice cell nothing resets, and
stops on the note's last tick. A note of L ticks spends `2(L-1) - 1` effect
calls -- odd -- so each bit-$02 note of two ticks or more flips the voice's
phase: the residue is the event PARITY, the period one tick, which is the
row's tempo in our calls (`goatwriter.wave_eor`). These tests pin:

* the parity walk against the original's own trace, note by note;
* each block's call-by-call shape;
* that every bit-$02 note of the converted song plays the program its own
  residue names, and that nothing else in the song moves;
* the emission against the trace, frame by frame from each paired attack.

The A/B under presets at -t 180 is in docs/H2G-CONVERSION-METHOD.md beside
`detect.WAVE_EOR_SHAPE`.
"""
import json
import pathlib
import sys

import pytest

from corpus import CORPUS, needs_corpus  # noqa: E402

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[1]))

from h2g.convert import convert  # noqa: E402
from h2g.detect import detect  # noqa: E402
from h2g.goatwriter import _wavetable_entries  # noqa: E402
from h2g.goatwriter import wave_eor as W  # noqa: E402
from h2g.sidfile import load_sid  # noqa: E402

ROOT = pathlib.Path(__file__).resolve().parents[2]
RASPUTIN = CORPUS / "Rasputin.sid"
MULT = 2                                  # Rasputin packs at -S2
REC4, REC10 = 0x05, 0x0B                  # their GT numbers (compact)
KEY = {REC10: (0, 0x0A89), REC4: (1, 0x0706)}   # voice, original's AD/SR


def _rasputin():
    sid = load_sid(str(RASPUTIN))
    return sid, detect(sid, log=lambda m: None)


def _opts():
    sys.path.insert(0, str(ROOT / "python"))
    import fidelity as F
    doc = json.loads((ROOT / "presets.json").read_text(encoding="utf-8"))
    return F._preset_opts(doc, "Rasputin.sid")


def _convert(monkeypatch, enabled=True):
    """(song bytes, the plan's arguments, the plan) under presets."""
    seen = {}
    plan = W.wave_eor_split_plan

    def spy(*args, **kw):
        seen["args"], seen["kw"] = args, kw
        seen["plan"] = plan(*args, **kw)
        return seen["plan"]
    monkeypatch.setattr(W, "wave_eor_split_plan", spy)
    if not enabled:
        monkeypatch.setattr(W, "wave_eor_note_residues",
                            lambda *a, **k: None)
    blob = convert(str(RASPUTIN), log=lambda *a, **k: None, **_opts())
    return blob, seen


def _walk(seen):
    sid, det, tracks, patterns, instr_used, lead = seen["args"][:6]
    return W.note_parities(sid, det, tracks, patterns, instr_used, lead,
                           seen["kw"].get("aliases"))


def _calls(left, right, start, n):
    """The waveform on each of `n` calls of a block entered at `start`
    (1-based): a waveform entry is one call, a delay `$01-$0F` holds for
    `value + 1` (gplay.c:697-704), `$00` keeps the waveform, `$FF xx`
    jumps at no cost, `$FF 00` stops (the waveform holds)."""
    out, wave, k, guard = [], None, start - 1, 0
    while len(out) < n:
        guard += 1
        assert guard < 10 * n + 100
        if k < 0:                        # stopped
            out.append(wave)
            continue
        b = left[k]
        if b == 0xFF:
            k = right[k] - 1 if right[k] else -1
            continue
        if 0x01 <= b <= 0x0F:
            out += [wave] * (b + 1)
        else:
            if b:
                wave = b
            out.append(wave)
        k += 1
    return out[:n]


def _frames(calls):
    """What siddump samples: the waveform after each frame's last call."""
    return [calls[k] for k in range(MULT - 1, len(calls), MULT)]


def _program(sid, det, rec, res, base, n):
    """The `n` calls of the program `res` gives record `rec`, laid out the
    way the song lays it: the library first (position 1), then the block --
    or, for a residue the library holds whole, from its entry."""
    lib = W.eor_library([(0x41, 0x59)], MULT, 1)
    start = len(lib.left) + 1
    got = W.wave_eor_block(sid, det, rec, res, base, MULT, start, 64,
                           library=lib)
    if isinstance(got, int):
        return _calls(lib.left, lib.right, got, n)
    return _calls(lib.left + got[0], lib.right + got[1], start, n)


def _song_wave(song):
    left = [l for l, _ in song.tables["WTBL"]]
    right = [r for _, r in song.tables["WTBL"]]
    return left, right


# --- the walk against the original ------------------------------------------

@needs_corpus
def test_the_parity_walk_predicts_the_original_s_phase(monkeypatch):
    """Phase 0 (toggle on the first effect call) ends a note of an even
    number of ticks toggled -- `$58`/`$5A` in the release tick -- and phase
    1 untoggled (`$40`/`$42`). The walk over the finished orderlists names
    the phase of EVERY record-10 and record-4 note of subtune 0 in 180 s:
    416 of 416 and 128 of 128 at 862f703 (v0.5.522)."""
    sys.path.insert(0, str(ROOT / "python"))
    import fidelity as F
    _blob, seen = _convert(monkeypatch)
    walked = _walk(seen)
    trace = F.run_siddump(RASPUTIN, 180, 0)
    for gt, (v, key) in KEY.items():
        ours = [(phase, length) for ti, _key, _k, g, _i, length, phase,
                quiet, _t in walked if ti == v and g == gt and not quiet]
        tl_w = F.register_timeline(trace[v].wf_events, 180 * 50)
        tl_e = F.register_timeline(trace[v].adsr_events, 180 * 50)
        att = sorted(trace[v].attack_frames)
        seen_phase = []
        for j, a in enumerate(att):
            if tl_e[a] != key:
                continue
            end = att[j + 1] if j + 1 < len(att) else 180 * 50
            seen_phase.append(0 if tl_w[end - 1] in (0x58, 0x5A) else 1)
        assert len(seen_phase) >= (400 if gt == REC10 else 120), \
            len(seen_phase)
        assert all(length % 2 == 0 for _p, length in ours[:len(seen_phase)])
        got = [p for p, _l in ours[:len(seen_phase)]]
        bad = [j for j, (x, y) in enumerate(zip(got, seen_phase)) if x != y]
        assert not bad, (hex(gt), len(bad), bad[:10])
        # ...and the parity really alternates: half and half.
        assert abs(got.count(0) - got.count(1)) <= 1


# --- the blocks --------------------------------------------------------------

@needs_corpus
@pytest.mark.parametrize("eor,want", [
    # phase 0: frame 0 (2 calls) of $41, then halves of `period` calls
    (W.EorPhase(0, 4), [0x41] * 2 + [0x59] * 4 + [0x41] * 4 + [0x59] * 4),
    # phase 1: the whole first tick of $41 first
    (W.EorPhase(1, 4), [0x41] * 4 + [0x59] * 4 + [0x41] * 4 + [0x59] * 4),
    (W.EorPhase(1, 5), [0x41] * 5 + [0x59] * 5 + [0x41] * 5 + [0x59] * 3),
    # three frames a tick (R = 2): the skip sits after the fetch, so the
    # first toggle is two frames in
    (W.EorPhase(0, 6), [0x41] * 4 + [0x59] * 6 + [0x41] * 6 + [0x59] * 2),
    # a two-tick note on phase 0: one toggle, held
    (W.EorPhase(0, 0), [0x41] * 2 + [0x59] * 16),
])
def test_record_10_s_blocks(eor, want):
    sid, det = _rasputin()
    base = _wavetable_entries(sid, det, 10, True, "gts5", [], MULT,
                              start=7, budget=40)
    left, right = W.wave_eor_block(sid, det, 10, eor, base, MULT, 7, 40)
    # Laid out at entry 7: the loop jumps into the block's own entries.
    pad_l, pad_r = [0] * 6 + left, [0] * 6 + right
    assert _calls(pad_l, pad_r, 7, len(want)) == want


@needs_corpus
def test_no_toggle_and_written_leads():
    sid, det = _rasputin()
    base = _wavetable_entries(sid, det, 10, True, "gts5", [], MULT,
                              start=1, budget=40)
    assert W.wave_eor_block(sid, det, 10, W.NO_TOGGLE, base, MULT, 1,
                            40) == base
    # With the firstwave owning the init call the entries start a call
    # later, so they hold the lead one call shorter.
    left, right = W.wave_eor_block(sid, det, 10, W.EorPhase(0, 4), base,
                                   MULT, 1, 40, written=True)
    assert _calls(left, right, 1, 6) == [0x41, 0x59, 0x59, 0x59, 0x59, 0x41]


@needs_corpus
def test_record_4_s_toggle_replaces_the_drum_s_noise_tick():
    """Record 4 (`80 01 43 07 06 00 00 07`, drum + $02 + arpeggio): the
    toggle runs after the drum and overwrites its noise frame. Traced:
    `43 5B 5A 5A` on phase 0, the drum alone `43 80 42 42` on phase 1 --
    which is the record's own block, unchanged."""
    sid, det = _rasputin()
    base = _wavetable_entries(sid, det, 4, True, "gts5", [], MULT,
                              start=1, budget=40)
    assert _frames(_calls(*base, 1, 8))[:3] == [0x43, 0x81, 0x42]
    eor = W.wave_eor_block(sid, det, 4, W.EorPhase(0, 0), base, MULT, 1, 40)
    assert _frames(_calls(*eor, 1, 8)) == [0x43, 0x5B, 0x5A, 0x5A]
    assert W.wave_eor_block(sid, det, 4, W.NO_TOGGLE, base, MULT, 1,
                            40) == base


# --- the converted song -------------------------------------------------------

@needs_corpus
def test_every_bit02_note_plays_its_own_residue(monkeypatch):
    """Each untied record-10 / record-4 note of the converted song, in play
    order, plays an instrument whose wavetable program is the one
    `wave_eor_note_residues` names for it -- the record's own block for
    the majority, a clone for the rest. Compared call by call over 24
    calls, so a loop shared into the record's block counts as the same."""
    import songview
    blob, seen = _convert(monkeypatch)
    plan = seen["plan"]
    assert plan is not None and len(plan.clones) >= 6
    sid, det = seen["args"][:2]
    phases, residues = W.wave_eor_note_residues(*seen["args"][:6],
                                                seen["kw"].get("aliases"))
    assert phases[REC4] == W.NO_TOGGLE           # 64 / 64, the lower wins
    assert phases[REC10].phase in (0, 1) and phases[REC10].period
    song = songview.parse_sng(blob)
    left, right = _song_wave(song)
    family = {REC10: {REC10}, REC4: {REC4}}
    for rec, clone, _res in plan.clones:
        family[rec].add(clone)
    drum_base = _calls(left, right, song.instruments[REC4 - 1].wave_ptr, 24)

    def expected(gt, res):
        if gt == REC4:
            if res == W.NO_TOGGLE:
                return drum_base
            return [0x5B if w in (0x80, 0x81) else 0x5A if w == 0x42 else w
                    for w in drum_base]
        if res == W.NO_TOGGLE:
            return [0x41] * 24
        return _program(sid, det, 10, res, ([0xFF], [0]), 24)

    walked = [(ti, key, k, gt) for ti, key, k, gt, _i, _l, _p, quiet, _t
              in _walk(seen) if not quiet]
    want = [(ti, gt, residues[key][k]) for ti, key, k, gt in walked
            if k in residues.get(key, {})]
    checked = 0
    for ti in (0, 1):
        got = []
        cur = 0
        for b in _lap(song.tracks[ti]):
            pat = song.patterns[b]
            for k in range(len(pat) // 4):
                nb, ins, cmd, op = pat[4 * k:4 * k + 4]
                if nb == 0xFF:
                    break
                if ins:
                    cur = ins
                if 0x60 <= nb <= 0xBC and not (cmd == 3 and op == 0):
                    for rec, members in family.items():
                        if cur in members:
                            got.append(cur)
        mine = [(gt, res) for t, gt, res in want if t == ti]
        assert len(got) == len(mine), (ti, len(got), len(mine))
        for number, (gt, res) in zip(got, mine):
            ptr = song.instruments[number - 1].wave_ptr
            assert _calls(left, right, ptr, 24) == expected(gt, res), \
                (ti, number, res)
            checked += 1
    assert checked >= 416 + 128


def _lap(track):
    """Pattern numbers of one lap, repeats expanded."""
    out, rep, operand = [], 1, False
    for b in track:
        if operand:
            break
        if b == 0xFF:
            operand = True
            continue
        if 0xE0 <= b < 0xFF:
            continue
        if 0xD0 <= b < 0xE0:
            rep = b - 0xD0 + 1
            continue
        out += [b] * rep
        rep = 1
    return out


@needs_corpus
def test_nothing_but_the_bit02_notes_moves(monkeypatch):
    """Against the same conversion with the split turned off: every row of
    every voice carries the same note and command, and the same instrument
    -- except a bit-$02 note, which names its record or one of its clones,
    and the instruments numbered after the clones, which shift by their
    count. Holds the tempo split's renames inside this plan's pattern
    copies (they get that plan's edits). The one other change is
    `wave_eor.eor_stop_pass`'s: a `CMD_SETWAVEPTR` on the empty command
    column of a rest row, the last row of a toggling note
    (tests/test_wave_eor_stop.py)."""
    import songview
    off, _ = _convert(monkeypatch, enabled=False)
    monkeypatch.undo()
    on, seen = _convert(monkeypatch)
    plan = seen["plan"]
    instr_used = seen["args"][4]
    first = seen["args"][6]
    shift = len(plan.clones)
    family = {REC10: {REC10}, REC4: {REC4}}
    for rec, clone, _res in plan.clones:
        family[rec].add(clone)
    a, b = songview.parse_sng(off), songview.parse_sng(on)
    assert len(a.tracks) == len(b.tracks)
    rows = stops = 0
    for ti in range(len(a.tracks)):
        def stream(song):
            cur, out = 0, []
            for p in _lap(song.tracks[ti]):
                pat = song.patterns[p]
                for k in range(len(pat) // 4):
                    if pat[4 * k] == 0xFF:
                        break
                    if pat[4 * k + 1]:
                        cur = pat[4 * k + 1]
                    out.append((pat[4 * k], pat[4 * k + 2], pat[4 * k + 3],
                                cur))
            return out
        sa, sb = stream(a), stream(b)
        assert len(sa) == len(sb), ti
        for (na, ca, oa, ia), (nb, cb, ob, ib) in zip(sa, sb):
            if (ca, oa) != (cb, ob):
                assert (na, ca, oa) == (0xBD, 0, 0) and cb == 8, ti
                assert na == nb
                stops += 1
            else:
                assert (na, ca, oa) == (nb, cb, ob), ti
            if ia in family:
                assert ib in family[ia], (ti, ia, ib)
            elif ia >= first:
                assert ib == ia + shift, (ti, ia, ib)
            else:
                assert ib == ia, (ti, ia, ib)
            rows += 1
    assert rows > 6000
    assert stops > 200
    assert first > instr_used                      # after the duty clones


# --- the emission against the trace ---------------------------------------

@needs_corpus
def test_the_emission_matches_the_original_frame_by_frame(monkeypatch):
    """Each original record-10 / record-4 note, paired in order with the
    residue the walk gives it, against that residue's program sampled per
    frame from the attack, over the note but its last tick (where the
    original holds and the gate is off). Measured at 862f703 (v0.5.522),
    every residue a fixed loop of (phase, tick): 3614 of 4082 record-10
    frames (0.885) and 251 of 266 record-4 frames (0.944) agree on
    `wave & $FE`, where each record's own first waveform held throughout
    agrees on 2299 (0.563) and 138 (0.519). The weakest residues were the
    five-call ticks (0.84 / 0.83): R = 3, 5 and 6 rows are 5.33, 4.8 and
    4.67 calls, and where the skip falls moves the first toggle by a frame
    from note to note. With the residue read off the original's gate clock
    (`wave_eor.clock_residue`, tests/test_wave_eor_clock.py) record 10 reads
    3876 of 4088 (0.948) here; record 4 is unchanged."""
    sys.path.insert(0, str(ROOT / "python"))
    import fidelity as F
    _blob, seen = _convert(monkeypatch)
    sid, det = seen["args"][:2]
    _phases, residues = W.wave_eor_note_residues(*seen["args"][:6],
                                                 seen["kw"].get("aliases"))
    walked = [(ti, gt, residues[key][k]) for ti, key, k, gt, _i, _l, _p, q,
              _t in _walk(seen) if not q and k in residues.get(key, {})]
    base4 = _wavetable_entries(sid, det, 4, True, "gts5", [], MULT,
                               start=1, budget=40)
    base10 = _wavetable_entries(sid, det, 10, True, "gts5", [], MULT,
                                start=1, budget=40)
    trace = F.run_siddump(RASPUTIN, 180, 0)
    n = 180 * 50
    for gt, (v, key) in KEY.items():
        rec, base = (4, base4) if gt == REC4 else (10, base10)
        mine = [res for ti, g, res in walked if ti == v and g == gt]
        tl_w = F.register_timeline(trace[v].wf_events, n)
        tl_e = F.register_timeline(trace[v].adsr_events, n)
        att = sorted(trace[v].attack_frames)
        notes = [(a, att[j + 1] if j + 1 < len(att) else n)
                 for j, a in enumerate(att) if tl_e[a] == key]
        agree = total = flat = 0
        for (a, e), res in zip(notes, mine):
            ours = _frames(_program(sid, det, rec, res, base,
                                    MULT * (e - a)))
            tick = 3 if (res.family == 2 or res.period == 3 * MULT) else 2
            for k in range(max(0, e - a - tick)):
                total += 1
                agree += (ours[k] & 0xFE) == (tl_w[a + k] & 0xFE)
                flat += (base[0][0] & 0xFE) == (tl_w[a + k] & 0xFE)
        assert total > (3000 if gt == REC10 else 200), total
        floor = 0.94 if gt == REC10 else 0.93
        assert agree / total >= floor, (hex(gt), agree, total)
        assert agree > flat, (hex(gt), agree, flat)


@needs_corpus
def test_a_two_tick_note_toggles_at_most_once(monkeypatch):
    """A two-tick note's second tick is its last, where the block does not
    run: on phase 0 it toggles once, on the first effect call, and holds
    (`41 59 58 58`); on phase 1 it never toggles (`41 41 40 40`). Compared
    over the WHOLE note, release tick included, gate bit aside -- the one
    place a looping block would toggle again."""
    sys.path.insert(0, str(ROOT / "python"))
    import fidelity as F
    _blob, seen = _convert(monkeypatch)
    sid, det = seen["args"][:2]
    _phases, residues = W.wave_eor_note_residues(*seen["args"][:6],
                                                 seen["kw"].get("aliases"))
    walked = [(ti, gt, length, residues[key][k]) for ti, key, k, gt, _i,
              length, _p, q, _t in _walk(seen)
              if not q and k in residues.get(key, {})]
    base = _wavetable_entries(sid, det, 10, True, "gts5", [], MULT,
                              start=1, budget=40)
    trace = F.run_siddump(RASPUTIN, 180, 0)
    n = 180 * 50
    tl_w = F.register_timeline(trace[0].wf_events, n)
    tl_e = F.register_timeline(trace[0].adsr_events, n)
    att = sorted(trace[0].attack_frames)
    notes = [(a, att[j + 1] if j + 1 < len(att) else n)
             for j, a in enumerate(att) if tl_e[a] == KEY[REC10][1]]
    mine = [(length, res) for ti, gt, length, res in walked
            if ti == 0 and gt == REC10]
    agree = total = 0
    kinds = set()
    for (a, e), (length, res) in zip(notes, mine):
        if length != 2:
            continue
        kinds.add(res)
        block = W.wave_eor_block(sid, det, 10, res, base, MULT, 1, 40)
        ours = _frames(_calls(*block, 1, MULT * (e - a)))
        for k in range(e - a):
            total += 1
            agree += (ours[k] & 0xFE) == (tl_w[a + k] & 0xFE)
    assert kinds == {W.NO_TOGGLE, W.EorPhase(0, 0)}
    assert total > 300 and agree / total >= 0.95, (agree, total)


def test_a_copied_pattern_takes_the_other_split_s_edits():
    """The tempo duty split keys its instrument bytes by pattern before this
    split copies any; a copy gets its source's edits, an untouched pattern
    keeps its own, and the other plan's dict is not mutated."""
    edits = {2: {0: (7, 15)}, 3: {4: (14, 16)}}
    tracks = [[1, 2, 0xFF, 0], [3, 2, 0xFF, 0]]
    copied = [[1, 9, 0xFF, 0], [3, 2, 0xFF, 0]]
    got = W.carry_split_edits(tracks, copied, edits)
    assert got == {2: {0: (7, 15)}, 3: {4: (14, 16)}, 9: {0: (7, 15)}}
    assert edits == {2: {0: (7, 15)}, 3: {4: (14, 16)}}
    assert W.carry_split_edits(tracks, tracks, edits) == edits
