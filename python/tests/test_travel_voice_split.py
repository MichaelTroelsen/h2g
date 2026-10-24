"""`travel` per voice: the file-level ratio sums the voices and can cancel.

Star_Paws (v0.5.548, -t 180, presets; historical, re-measure before quoting)
reads `travel` 0.969: 909,752 against the original's 938,967. The original's
938,967 is all voice 0; ours is 356,056 on voice 0 plus 553,696 on voice 1.
Voice 1 is the drum voice. Its fall `14176 -> 12384` in the original is 1792
units, 1.011 of `fidelity.TRAVEL_NOTE_STEP`'s 1/8 cutoff, so it counts as a
note change and adds nothing. Ours is `14177 -> 12604`, 1573 units, 0.888 of
the cutoff, so the SAME step of the same drum counts as a bend: 352 drums x
1573 = 553,696. The two sides agree on the music; one step straddles a
threshold. Nothing in the conversion's voices 1 and 2 moves pitch that the
original's does not.
"""
import json
import pathlib
import sys

import pytest

PYTHON_ROOT = pathlib.Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PYTHON_ROOT))
sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent))

import fidelity  # noqa: E402
from corpus import CORPUS, needs_corpus  # noqa: E402


def _drum(fall_to: int, before: int = 14176) -> "fidelity.Voice":
    """Four 8-frame drums like Star_Paws voice 1's: an attack, the program's
    frequency steps, then its fall `before -> fall_to` (the original's is
    14176 -> 12384, ours 14177 -> 12604)."""
    v = fidelity.Voice()
    v.freq_events = [(0, 0)]
    for k in range(4):
        a = 10 + 8 * k
        v.attack_frames.append(a)
        v.freq_events += [(a, 17824), (a + 1, 18592), (a + 2, 17824),
                          (a + 3, before), (a + 4, fall_to),
                          (a + 5, 5472), (a + 6, 8288)]
    return v


def _three(v0, v1=None, v2=None):
    return [v0, v1 or fidelity.Voice(), v2 or fidelity.Voice()]


def test_compare_carries_travel_per_voice_and_the_file_total_is_their_sum():
    out = fidelity.compare(
        _three(_drum(12384), _drum(12384)), _three(_drum(12604, 14177), _drum(12604, 14177)))
    per = [(v["orig_travel"], v["our_travel"]) for v in out["voices"]]
    assert per == [(0, 0), (0, 0), (0, 0)]
    assert out["orig_travel"] == sum(p[0] for p in per)
    assert out["our_travel"] == sum(p[1] for p in per)


def test_a_cancelling_total_is_split_by_voice():
    # Equal file totals, wholly different voices: the shape of Star_Paws'
    # 0.969, where the original travels on voice 0 and ours on voice 1.
    def bender(step):
        v = fidelity.Voice()
        v.attack_frames = [0]
        v.freq_events = [(0, 0x1000)] + [(10 + k, 0x1000 + (step if k % 2 else 0))
                                          for k in range(8)]
        return v
    out = fidelity.compare(_three(bender(10)), _three(fidelity.Voice(), bender(10)))
    assert out["travel_ratio"] == pytest.approx(1.0)
    assert [(v["orig_travel"], v["our_travel"]) for v in out["voices"]] == [
        (70, 0), (0, 70), (0, 0)]


def test_the_drum_fall_straddles_the_note_change_cutoff_and_hysteresis_joins_it():
    # 1792 * 8 = 14336 > 14176: the original's fall is a note change.
    # 1573 * 8 = 12584 < 14177: under the bare threshold ours was a bend,
    # 4 drums x 1573. It follows a note-change step on the next frame, the
    # same way, at 0.888 of the cutoff, so the hysteresis takes it too.
    orig, ours = _drum(12384), _drum(12604, 14177)
    assert fidelity.within_note_travel(orig) == 0
    assert fidelity.within_note_travel(ours) == 0
    assert fidelity.travel_step_census(orig) == []
    assert fidelity.travel_step_census(ours) == []


def _fall_after(first_to, second_to, gap=1):
    v = fidelity.Voice()
    v.attack_frames = [0]
    v.freq_events = [(0, 0), (10, 17824), (10 + gap, first_to),
                     (10 + 2 * gap, second_to)]
    return v


def test_hysteresis_needs_a_preceding_note_change_the_next_frame_the_same_way():
    # 17824 -> 14176 (note change), then 14176 -> 12604 (0.888): joined.
    assert fidelity.within_note_travel(_fall_after(14176, 12604)) == 0
    # Same second step two frames later: a bend.
    assert fidelity.within_note_travel(_fall_after(14176, 12604, gap=2)) == 1572
    v = fidelity.Voice()
    v.attack_frames = [0]
    # Only the ONE step after the note change: a second near-cutoff step in
    # the chain (14176 -> 12604 -> 11100, 0.88 of the cutoff) is a bend.
    v = fidelity.Voice()
    v.attack_frames = [0]
    v.freq_events = [(0, 0), (10, 17824), (11, 14176), (12, 12604), (13, 11200)]
    assert fidelity.within_note_travel(v) == 1404
    # Opposite direction: a bend.
    v.freq_events = [(0, 0), (10, 17824), (11, 14176), (12, 15749)]
    assert fidelity.within_note_travel(v) == 1573
    # Under half the cutoff (0.4): a bend, however it follows.
    v.freq_events = [(0, 0), (10, 17824), (11, 14176), (12, 14176 - 700)]
    assert fidelity.within_note_travel(v) == 700
    # No preceding note change: a lone 0.888 step stays a bend.
    v.freq_events = [(0, 0), (10, 14177), (11, 12604)]
    assert fidelity.within_note_travel(v) == 1573


def test_census_ranks_steps_by_the_distance_they_add_not_their_count():
    v = fidelity.Voice()
    v.attack_frames = [0]
    # 4096 -> 4196 once (100), and 4096 <-> 4106 five times each way (10 x 10).
    v.freq_events = [(0, 4096), (10, 4196), (11, 4096)]
    for k in range(5):
        v.freq_events += [(20 + 2 * k, 4106), (21 + 2 * k, 4096)]
    got = fidelity.travel_step_census(v, 4)
    assert {g[:2] for g in got[:2]} == {(4096, 4196), (4196, 4096)}
    assert {g[:3] for g in got[2:]} == {(4096, 4106, 5), (4106, 4096, 5)}
    assert fidelity.within_note_travel(v) == 100 + 100 + 10 * 5 * 2


def test_diagnose_line_names_the_counted_step_and_its_margin():
    lone = fidelity.Voice()
    lone.attack_frames = [0]
    lone.freq_events = [(0, 0), (10, 14177), (11, 12604)]
    line = fidelity.describe_voice_travel(_drum(12384), lone)
    assert "original 0, ours 1,573" in line
    assert "1x 14177->12604" in line and "0.888 of the 1/8 cutoff" in line
    assert fidelity.describe_voice_travel(
        fidelity.Voice(), fidelity.Voice()) == "travel: none on either side"


def test_equal_calls_rows_drop_the_per_voice_travel_too():
    src = (PYTHON_ROOT / "fidelity.py").read_text(encoding="utf8")
    i = src.index('for k in ("bend_ratio", "slides_ratio"')
    tail = src[i:i + 900]
    assert 'pv.pop("orig_travel", None)' in tail
    assert 'pv.pop("our_travel", None)' in tail


@needs_corpus
@pytest.mark.skipif(not pathlib.Path(fidelity.SIDDUMP).exists(),
                    reason="no siddump")
def test_star_paws_voice_1_travel_is_the_drum_fall(tmp_path):
    """Real trace, 30 s: the original travels on voice 0 only; ours no longer
    adds the voice-1 drum falls (the hysteresis joins them to their note
    change)."""
    sid = CORPUS / "Star_Paws.sid"
    assert sid.is_file(), "Star_Paws is not in the corpus"
    out = tmp_path / "f.json"
    pre = json.loads((PYTHON_ROOT.parent / "presets.json")
                     .read_text(encoding="utf-8"))
    for k in ("regrid", "regrid_full_debt", "regrid_per_play"):
        pre["songs"]["Star_Paws.sid"].pop(k, None)      # pre-v0.5.595 arm
    pp = tmp_path / "pre.json"
    pp.write_text(json.dumps(pre), encoding="utf-8")
    rc = fidelity.main([str(sid), "-t", "30", "--jobs", "1", "--presets", str(pp),
                        "--workdir", str(tmp_path / "w"),
                        "--json", str(out), "-o", str(tmp_path / "f.md")])
    assert rc in (0, None)
    doc = json.loads(out.read_text(encoding="utf8"))
    row = next(r for r in (doc["rows"] if isinstance(doc, dict) else doc)
               if r.get("status") == "measured")
    (o0, u0), (o1, u1), (o2, u2) = [(v["orig_travel"], v["our_travel"])
                                    for v in row["voices"]]
    assert o0 > 0 and u0 > 0
    assert o1 == 0 and u1 == 0
    assert o2 == u2 == 0
    assert row["orig_travel"] == o0 + o1 + o2
    assert row["our_travel"] == u0 + u1 + u2
