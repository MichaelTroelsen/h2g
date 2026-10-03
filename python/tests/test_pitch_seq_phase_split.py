"""Bit $10's divided phase, split per NOTE (`pitch_seq_phase_split_plan`).

`pitch_seq_phases` gives each bit-$10 record ONE phase, the majority of its
notes'. On Food_Feud a row is 8/3 frames against the counter's 8-frame cycle,
so a record's notes attack in three states, one per row mod 3, nearly evenly
(GT 4: 102 / 100 / 95 at v0.5.496) -- one wavetable per record is right for
a third of them. The split clones each record once per minority state (the
fixed arp's `_note_phase_split`, its residue a phase tuple) and renames each
note to its state's clone; a repeated orderlist entry whose plays want
different states is unrolled (`_expand_repeats`), because a repeat plays one
pattern's bytes and so one spelling.

Measured (C:/t/pitch-seq-per-note-phase/measure.py, Food_Feud on its preset
with `pitch_seq` forced, 180 s, voice 2's 466 notes under the original's
ADSR $29F9): attack-relative frame agreement 2588/4028 (64.3%) -> 4027/4028,
those notes' ties 1310 -> 1139 against the original's 1139. Without the
unroll the split alone reached 3578/4028 (88.8%): 72 of the records' 805
notes sat on a repeat's later play.
"""
import functools
import json
import pathlib
import sys
import warnings

from corpus import CORPUS as _CORPUS, needs_corpus  # noqa: E402

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[1]))

from h2g import goatwriter as G
from h2g.convert import _detect_tables, convert
from h2g.sidfile import load_sid

CORPUS = _CORPUS
ROOT = pathlib.Path(__file__).resolve().parents[2]


def _opts(name, **extra):
    sys.path.insert(0, str(ROOT / "python"))
    import fidelity as F
    doc = json.loads((ROOT / "presets.json").read_text())
    with warnings.catch_warnings():
        warnings.simplefilter("ignore")
        opts = F._preset_opts(doc, name)
    opts.update(extra)
    return opts


@functools.lru_cache(maxsize=None)
def _food_feud_split():
    """(sid, det, tracks in, patterns in, plan, log) from one conversion of
    Food_Feud on its preset with `pitch_seq` forced."""
    cap, lines = {}, []
    real = G.pitch_seq_phase_split_plan

    def spy(sid, det, tracks, patterns, *a, **k):
        plan = real(sid, det, tracks, patterns, *a, **k)
        cap.update(sid=sid, det=det, tracks=tracks, patterns=patterns,
                   plan=plan)
        return plan
    G.pitch_seq_phase_split_plan = spy
    try:
        convert(str(CORPUS / "Food_Feud.sid"), log=lines.append,
                **_opts("Food_Feud.sid", pitch_seq=True))
    finally:
        G.pitch_seq_phase_split_plan = real
    return (cap["sid"], cap["det"], cap["tracks"], cap["patterns"],
            cap["plan"], tuple(lines))


# --- _expand_repeats ---------------------------------------------------------

def test_a_repeat_is_written_out_one_entry_per_play():
    track = [0x05, 0xD2, 0x0D, 0xD3, 0x10, 0x12, 0xFF, 0x05]
    # only the entry at position 4 (`D3 10`, four plays) is asked for
    got = G._expand_repeats(track, {4})
    assert got == [0x05, 0xD2, 0x0D, 0x10, 0x10, 0x10, 0x10, 0x12, 0xFF, 0x07]
    # the restart operand followed its byte (old 5 -> new 7)
    assert got[got.index(0xFF) + 1] == 7


def test_the_restart_operand_lands_where_the_old_one_played():
    """A restart on the repeat byte replays the whole repeat (first copy); one
    on the pattern byte plays it once (the last copy)."""
    track = [0x01, 0xD2, 0x0D, 0x02, 0xFF, 0x01]          # restart at `D2`
    got = G._expand_repeats(track, {2})
    assert got == [0x01, 0x0D, 0x0D, 0x0D, 0x02, 0xFF, 0x01]
    track = [0x01, 0xD2, 0x0D, 0x02, 0xFF, 0x02]          # restart at `0D`
    got = G._expand_repeats(track, {2})
    assert got == [0x01, 0x0D, 0x0D, 0x0D, 0x02, 0xFF, 0x03]
    track = [0x01, 0xD2, 0x0D, 0x02, 0xFF, 0x03]          # after it: shifted
    assert G._expand_repeats(track, {2})[-1] == 0x04


def test_an_unroll_past_the_orderlist_limit_declines():
    track = [0xDF, 0x01] * 20 + [0xFF, 0x00]              # 42 bytes, 320 plays
    assert G._expand_repeats(track, {2 * k + 1 for k in range(20)}) is None
    assert G._expand_repeats(track, {1}) is not None      # 16 + 40: fits


# --- the layout carries a tuple residue as `pitch_phase` ---------------------

@needs_corpus
def test_a_tuple_residue_reaches_the_clone_as_its_pitch_phase():
    """`_wavetable_layout`'s phase clones dispatch on the residue's type: a
    tuple is bit $10's phase cells. Food_Feud record 2 (GT 3 at lead 0),
    -S3: the clone's block opens as `_wavetable_entries` opens with that
    phase, and not as the record's own (majority) block does."""
    sid = load_sid(str(CORPUS / "Food_Feud.sid"))
    sid, det = _detect_tables(sid, lambda *a, **k: None)
    major = (1, 0, 0, 0, 0, 1, 1, 1)
    other = (1, 1, 1, 0, 0, 0, 0, 1)
    table = [(0, 0)] * 16
    instr_used = G._instruments_used(det, None, 0)
    starts = []
    entries, rec_starts, _ = G._wavetable_layout(
        sid, det, instr_used, True, G.FORMAT_GTS5, list(table), 3, None, 0,
        two_stage=True, pitch_seq=True, pitch_phases={3: major},
        phase_clones=[(3, 40, other)], phase_clone_starts=starts)
    assert len(starts) == 1 and starts[0] > 0, starts
    s = starts[0]

    def opening(phase, start):
        left, right = G._wavetable_entries(
            sid, det, 2, True, G.FORMAT_GTS5, list(table), 3, None, 0,
            start=start, budget=200, two_stage=True, pitch_seq=True,
            pitch_phase=phase)
        loop = G._loop_of(left, right, start)
        assert loop is not None
        return list(zip(left[:loop[0]], right[:loop[0]]))
    want = opening(other, s)
    assert entries[s - 1:s - 1 + len(want)] == want
    assert want != opening(major, s)
    # the record itself still carries the majority
    rs = rec_starts[2]
    mine = opening(major, rs)
    assert entries[rs - 1:rs - 1 + len(mine)] == mine


# --- Food_Feud end to end ----------------------------------------------------

@needs_corpus
def test_food_feud_clones_each_record_per_minority_state():
    sid, det, tracks, patterns, plan, lines = _food_feud_split()
    assert plan is not None
    phases = G.pitch_seq_phases(sid, det, tracks, patterns)
    assert phases[3] == (1, 0, 0, 0, 0, 1, 1, 1)
    assert phases[4] == (1, 1, 1, 0, 0, 0, 0, 1)
    by_record = {}
    for record, clone, residue in plan.clones:
        assert isinstance(residue, tuple) and residue != phases[record]
        by_record.setdefault(record, set()).add(residue)
    # two clones each: with the majority, all three row-mod-3 states
    assert {r: len(v) for r, v in by_record.items()} == {3: 2, 4: 2}
    for record, states in by_record.items():
        assert len(states | {phases[record]}) == 3
    assert any(l.startswith("pitch phase split: 4 clone(s)") for l in lines)


@needs_corpus
def test_every_food_feud_bit10_note_plays_its_own_phase():
    """After the rename every untied note of a bit-$10 record sits on an
    instrument (record or clone) whose phase is the note's own -- all 805,
    including those on a repeat's later plays, which the unroll exists for."""
    sid, det, tracks, patterns, plan, _ = _food_feud_split()
    phases = G.pitch_seq_phases(sid, det, tracks, patterns)
    carried = {3: phases[3], 4: phases[4]}
    carried.update({clone: r for _, clone, r in plan.clones})
    res = G.pitch_seq_note_phases(sid, det, plan.tracks, plan.patterns)
    renamed = G.apply_tempo_duty_edits(plan.patterns, plan)
    right = wrong = on_clone = 0
    for ti, track in enumerate(plan.tracks):
        seen, cur = {}, 0
        for pos, p in G._orderlist_occurrences(track):
            if p >= len(renamed):
                continue
            play = seen.get(pos, 0)
            seen[pos] = play + 1
            r, pat = res.get((ti, pos, play), {}), renamed[p]
            for k in range(len(pat) // 4):
                if pat[4 * k] == 0xFF:
                    break
                if pat[4 * k + 1]:
                    cur = pat[4 * k + 1]
                tied = (pat[4 * k + 2] == G.CMD_TONEPORTA
                        and pat[4 * k + 3] == 0)
                if k not in r or tied or cur not in carried:
                    continue
                if carried[cur] == r[k]:
                    right += 1
                    on_clone += cur not in (3, 4)
                else:
                    wrong += 1
    assert (right, wrong) == (805, 0), (right, wrong)
    assert on_clone > 805 // 2
    # the unroll happened: voice 2's track grew, and it is still a lap
    assert len(plan.tracks[1]) > len(tracks[1])
    assert len(plan.tracks[1]) <= 254


@needs_corpus
def test_the_shipped_preset_and_unclocked_files_do_not_split():
    """No `pitch_seq` (Food_Feud's shipped preset) never asks; a file whose
    bit-$10 phase is not divided (Trans-Atlantic) has no clock and no plan."""
    lines = []
    convert(str(CORPUS / "Food_Feud.sid"), log=lines.append,
            **_opts("Food_Feud.sid"))
    assert not any("pitch phase split" in l for l in lines)
    name = "Trans-Atlantic_Balloon_Challenge"
    sid = load_sid(str(CORPUS / f"{name}.sid"))
    sid, det = _detect_tables(sid, lambda *a, **k: None)
    assert det.pitch_seq is not None
    lines = []
    convert(str(CORPUS / f"{name}.sid"), log=lines.append,
            **_opts(f"{name}.sid", pitch_seq=True))
    assert not any("pitch phase split" in l for l in lines)
