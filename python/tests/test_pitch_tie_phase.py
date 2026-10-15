"""`pitch_tie_phase`: a legato tie on a bit-$10 record restarts the wavetable
block of the phase cell's state on the tie's fetch call.

Star_Paws' legato clones are all bit-$10 records (tests/
test_legato_clone_records.py). In the original a tie restarts no phase cell:
the 3-step pitch sequence runs on a GLOBAL cell (`DEC $B44C`, once per play
call), so the second frame of a 2-frame row sits an octave up on one row in
three (`X..X..X..`). A legato clone restarts its record's wavetable, whose one
block carries ONE phase, so on every tie row the program started over: the
octave went up on EVERY row's second frame (`XXXXXXXX`), GT 15's vibrato
reversals read 952 against the original's 414, and the `travel` column's 0.969
was cancellation (voice 0's arpeggio travel missing, voices 1 and 2's extra).

`goatwriter.pitch_seq_tie_plan` reads each tie row's state from the clock
(`_pitch_seq_tie_grid`), copies patterns and writes repeats out so every row is
fetched in ONE state, tags the rows whose state is not the record's own, and
`build_sng` lays out one block per (record, phase tuple) and points each
tagged clone at it. Off by default and per song (`presets.EXCLUDED_FROM_ALWAYS`).

HISTORICAL figures (-t 180, presets, Star_Paws subtune 0, 4833cff + the
change, forced on): GT 15 reversals 952 -> 408 (original 414), the whole
file's reversal ratio 1.101 -> 1.002; octave-up frames in the two long
arpeggio notes 208/203 -> 69/68 (original 70/68); rows with the octave on
their second frame in the first note's 54 rows 54 -> 18 (original 18), with
all 54 rows agreeing in position. Voice 0's travel 356,056 -> 805,164
(original 938,967), and no 300-frame window of it off by more than 40,000
(four were, by 74-179k). The file's `travel` column reads 0.969 -> 1.447: its
voice-1 half, 553,696, is the drum step the original's cutoff rule counts as
a note change and ours as a bend (docs/H2G-CONVERSION-METHOD.md, `travel` is
read per voice), so the 0.969 was that artefact cancelling the voice-0
shortfall this removes.
"""
import json
import math
import pathlib

import pytest

import fidelity
from h2g import goatwriter as G
from h2g.convert import convert
from h2g.goatwriter import arpeggio as GA
from songview import parse_sng

from corpus import CORPUS, needs_corpus

REPO_ROOT = pathlib.Path(__file__).resolve().parents[2]
GATETIMER_LEGATO = 0x40
EFFECT_PITCH_SEQ = 0x10

needs_siddump = pytest.mark.skipif(
    not pathlib.Path(fidelity.SIDDUMP).exists(), reason="no siddump")
needs_gt2reloc = pytest.mark.skipif(
    not pathlib.Path(fidelity.GT2RELOC).exists(),
    reason="no gt2reloc on this machine")


def _opts(name="Star_Paws.sid", **extra):
    doc = json.loads((REPO_ROOT / "presets.json").read_text(encoding="utf-8"))
    opts = fidelity._preset_opts(doc, name)
    opts.update(extra)
    return opts


def _convert(name="Star_Paws", **extra):
    return convert(str(CORPUS / f"{name}.sid"), **_opts(f"{name}.sid", **extra))


@pytest.fixture(scope="module")
def planned():
    """(sid-side inputs, plan) as `build_sng` handed them to the planner."""
    seen = {}
    real = GA.pitch_seq_tie_plan

    def spy(sid, det, tracks, patterns, rows, lead, instr_used, own, log=None):
        seen["in"] = (sid, det, [list(t) for t in tracks],
                      [list(p) for p in patterns], set(rows), dict(own))
        plan = real(sid, det, tracks, patterns, rows, lead, instr_used, own,
                    log)
        seen["plan"] = plan
        return plan

    GA.pitch_seq_tie_plan = spy
    try:
        sng = _convert(pitch_tie_phase=True)
    finally:
        GA.pitch_seq_tie_plan = real
    return seen, sng


def test_the_option_is_off_by_default():
    import inspect
    assert inspect.signature(convert).parameters[
        "pitch_tie_phase"].default is False


@needs_corpus
def test_off_is_the_default_build():
    assert _convert(pitch_tie_phase=False) == _convert()


@needs_corpus
def test_commando_is_byte_identical_with_the_option_on():
    """Commando is not a legato-marker file: the option is inert there."""
    commando = str(CORPUS / "Commando.sid")
    assert convert(commando, pitch_tie_phase=True) == convert(commando)


@needs_corpus
def test_each_tagged_row_is_fetched_in_exactly_its_tags_state(planned):
    seen, _sng = planned
    plan = seen["plan"]
    sid, det = seen["in"][0], seen["in"][1]
    assert plan is not None and plan.tags
    grid = GA._pitch_seq_tie_grid(sid, det, plan.tracks, plan.patterns,
                                  set(plan.tags))
    heard = 0
    for _place, (p, res) in grid.items():
        for k, tup in res.items():
            heard += 1
            assert tup == plan.tags[(p, k)][1], (p, k)
    assert heard >= len(plan.tags)


@needs_corpus
def test_the_copies_are_needed_a_tie_row_is_played_in_more_than_one_state(
        planned):
    seen, _sng = planned
    sid, det, tracks, patterns, rows, own = seen["in"]
    states = GA.pitch_seq_tie_phases(sid, det, tracks, patterns, rows)
    assert any(len(v) > 1 for v in states.values())
    plan = seen["plan"]
    assert plan.copies and len(plan.patterns) <= 208
    assert sum(map(len, plan.tracks)) > sum(map(len, tracks))   # repeats out


@needs_corpus
def test_the_orderlists_still_play_the_same_patterns_with_the_same_bytes(
        planned):
    seen, _sng = planned
    tracks, patterns = seen["in"][2], seen["in"][3]
    plan = seen["plan"]
    for before, after in zip(tracks, plan.tracks):
        assert ([p for _pos, p in GA._orderlist_occurrences(before)]
                == [plan.copies.get(p, p)
                    for _pos, p in GA._orderlist_occurrences(after)])
    assert plan.patterns[:len(patterns)] == patterns
    for n, src in plan.copies.items():
        assert plan.patterns[n] == patterns[src]


@needs_corpus
def test_the_file_carries_a_block_per_state_and_the_option_off_one(planned):
    """Each bit-$10 record's legato clones start on several wavetable
    blocks (one per phase tuple a tie lands on), each opening differently;
    off, every clone of a record shares the record's block."""
    _seen, sng = planned

    def starts(blob):
        song = parse_sng(blob)
        out = {}
        for i in song.instruments:
            if (i.gatetimer & GATETIMER_LEGATO
                    and (i.effect_byte or 0) & EFFECT_PITCH_SEQ):
                key = (i.name, i.ad, i.sr, i.pulse_ptr, i.firstwave)
                out.setdefault(key, set()).add(i.wave_ptr)
        return song, out

    on_song, on = starts(sng)
    _off_song, off = starts(_convert())
    assert on and off
    assert all(len(v) == 1 for v in off.values()), off
    assert max(len(v) for v in on.values()) >= 3, on
    wave = on_song.tables["WTBL"]
    for key, ptrs in on.items():
        heads = {tuple(wave[s - 1:s + 1]) for s in ptrs}
        assert len(heads) == len(ptrs) or len(ptrs) == 1, (key, ptrs)


# --- through the packed player ------------------------------------------

SEG = (5263, 5682)       # the first long arpeggio note, original frames
LAG = 36                 # ours attacks this many frames earlier (-S2 startup)


def _sem(f):
    return round(12 * math.log2(f)) if f > 0 else -99


def _octave_rows(trace_voice, start, rows):
    fq = fidelity.register_timeline(trace_voice.freq_events, 9000)
    out = []
    for k in range(rows):
        a = start + 2 * k
        out.append(_sem(fq[a + 1]) - _sem(fq[a]) == 12)
    return out


def _up_frames(trace_voice, a, b):
    fq = fidelity.register_timeline(trace_voice.freq_events, 9000)
    return sum(1 for f in range(a + 1, b)
               if _sem(fq[f]) - _sem(fq[f - 1]) == 12)


@needs_corpus
@needs_siddump
@needs_gt2reloc
def test_the_octave_rises_on_the_originals_rows_through_the_packed_player(
        tmp_path):
    """Star_Paws voice 0, the first long arpeggio note: the original's second
    frame of a row is an octave up on rows 0, 3, 6, ... The restarted
    program put it on every row; with the option it is on the same rows."""
    orig = fidelity.run_siddump(CORPUS / "Star_Paws.sid", 130, 0, calls=1)[0]
    so = _octave_rows(orig, SEG[0], 54)
    assert sum(so) == 18 and so == [k % 3 == 0 for k in range(54)]

    def ours(opt, sub):
        work = tmp_path / sub
        work.mkdir()
        packed = fidelity.pack_sid(_convert(pitch_tie_phase=opt), work,
                                   multiplier=2)
        assert packed is not None and packed.exists(), sub
        v = fidelity.run_siddump(packed, 130, 0, calls=2)[0]
        near = [a for a in v.attack_frames
                if SEG[0] - LAG - 9 <= a <= SEG[0] - LAG + 11]
        assert near, (sub, SEG)
        return v, near[0]

    on, a_on = ours(True, "on")
    off, a_off = ours(False, "off")
    rows_on = _octave_rows(on, a_on, 54)
    rows_off = _octave_rows(off, a_off, 54)
    assert sum(1 for x, y in zip(rows_on, so) if x == y) >= 52, rows_on
    assert sum(rows_off) >= 50, rows_off          # the defect: every row
    ref = _up_frames(orig, *SEG)
    got = _up_frames(on, SEG[0] - LAG, SEG[1] - LAG)
    assert abs(got - ref) <= 0.2 * ref, (got, ref)
    assert _up_frames(off, SEG[0] - LAG, SEG[1] - LAG) > 2 * ref
