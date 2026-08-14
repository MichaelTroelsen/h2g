"""What the `hold` column's disagreements are made of.

§ 7.uuuu measured the column's tail per instrument and could name only two of
its three parts: a call-rate artefact at `-1`, six far outliers that are other
defects wearing a length costume, and 46 instruments at -2..-7 plus ~38 at
+5..+23 that were left unattributed. The histogram could not attribute them
because it asked one question -- how many frames does the note sound -- where
there are two: **is the note shorter, or is its slot?**

A note as long as the room it is given is not a note-length defect; it is a
timing difference, which `--pace` and `retrig` measure and no wavetable edit
fixes. Separating the two is what turns the tail into a queue.

The property these tests hold is the one `test_onset_census.py` holds for its
column: the census cannot drift from the column it classifies -- same
population, same modal reduction, `match` is the column's numerator.
"""
import pathlib
import sys
from collections import Counter

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[1]))

import fidelity as F  # noqa: E402


def _voice(adsr, slot, held, n, wave=0x11):
    """`n` measured notes of `held` sounding frames in a `slot`-frame slot.

    A trailing attack terminates the last measured note; the note it opens is
    dropped by the window rule, exactly as a real trace's final note is.
    """
    wf, at = [], []
    for i in range(n + 1):
        a = i * slot
        at.append(a)
        wf.append((a, wave))
        if held < slot:
            wf.append((a + held, 0x09))
    return (wf, [(0, adsr)], at)


def _gapped(adsr, slot, hole, n, wave=0x11):
    """`n` notes that sound the whole slot but for one frame at `hole`."""
    wf, at = [], []
    for i in range(n + 1):
        a = i * slot
        at.append(a)
        wf += [(a, wave), (a + hole, 0x09), (a + hole + 1, wave)]
    return (wf, [(0, adsr)], at)


def _voices(*event_lists):
    vs = [F.Voice(wf_events=list(wf), adsr_events=list(ad),
                  attack_frames=list(at))
          for wf, ad, at in event_lists]
    return vs + [F.Voice()] * (3 - len(event_lists))


NF = 200


def _one(orig, ours):
    return F.hold_census(_voices(orig), _voices(ours), NF)[0]


# -- the four kinds -----------------------------------------------------------

def test_one_frame_short_in_an_equal_slot_is_the_next_note_fetch():
    """Goattracker fetches the next note `gatetimer & $3f` calls early and
    writes `firstwave` there, so the note before it loses its last frame."""
    rec = _one(_voice(0x0A09, 8, 8, 6), _voice(0x0A09, 8, 7, 6))
    assert (rec["delta"], rec["slot_delta"], rec["kind"]) == (-1, 0, "fetch")


def test_a_note_as_long_as_a_shorter_slot_is_a_timing_difference():
    """The note fills the room it is given; what differs is when the next one
    arrives. `hold` cannot see the difference and nothing in the wavetable can
    fix it -- this is the group § 7.uuuu counted at -2..-7."""
    rec = _one(_voice(0x0A09, 8, 8, 6), _voice(0x0A09, 6, 6, 6))
    assert (rec["delta"], rec["slot_delta"], rec["kind"]) == (-2, -2, "slot")


def test_a_longer_slot_filled_is_a_timing_difference_too():
    """The +5..+23 group, from the other side: our notes are longer because
    our rows are."""
    rec = _one(_voice(0x0A09, 8, 8, 6), _voice(0x0A09, 14, 14, 6))
    assert (rec["delta"], rec["slot_delta"], rec["kind"]) == (6, 6, "slot")


def test_the_fetch_frame_on_top_of_a_slot_difference_is_still_a_slot():
    """A one-frame tolerance, because the fetch rides on top of everything."""
    rec = _one(_voice(0x0A09, 8, 8, 6), _voice(0x0A09, 6, 5, 6))
    assert (rec["delta"], rec["slot_delta"], rec["kind"]) == (-3, -2, "slot")


def test_stopping_early_in_an_equal_slot_is_short():
    rec = _one(_voice(0x0A09, 12, 12, 6), _voice(0x0A09, 12, 5, 6))
    assert (rec["delta"], rec["slot_delta"], rec["kind"]) == (-7, 0, "short")


def test_sounding_on_where_the_original_stops_is_long():
    rec = _one(_voice(0x0A09, 12, 5, 6), _voice(0x0A09, 12, 12, 6))
    assert (rec["delta"], rec["slot_delta"], rec["kind"]) == (7, 0, "long")


def test_equal_lengths_match():
    rec = _one(_voice(0x0A09, 8, 8, 6), _voice(0x0A09, 8, 8, 6))
    assert (rec["delta"], rec["kind"]) == (0, "match")


def test_a_population_one_side_barely_plays_is_sparse_not_short():
    """Two modes taken over different music. The same caveat as reading a
    register agreement next to both sides' note counts -- Knucklebusters
    sounds 959 frames over 2 notes against the original's 9 over 94."""
    rec = _one(_voice(0x0A09, 12, 12, 12), _voice(0x0A09, 12, 5, 5))
    assert (rec["orig_notes"], rec["our_notes"]) == (12, 5)
    assert rec["kind"] == "sparse"


def test_a_mode_over_one_note_is_that_note():
    """§ 7.uuuu's far tail is mostly this: Auf_Wiedersehen's `$0ADF` is one
    held note a side, and the +378 between them is a fact about the window."""
    rec = _one(_voice(0x0A09, 40, 20, 1), _voice(0x0A09, 40, 39, 1))
    assert rec["kind"] == "thin"


def test_a_hole_in_the_middle_of_a_note_is_a_gap_not_a_length():
    """`held` stops at the first deselected frame, so a player that drops the
    waveform for one frame and resumes reads as a note ending there. Counted
    in total the two sides agree, and the difference is in the reduction."""
    rec = _one(_gapped(0x0A09, 24, 6, 4), _voice(0x0A09, 24, 23, 4))
    assert (rec["orig_held"], rec["orig_total"]) == (6, 23)
    assert (rec["our_held"], rec["kind"]) == (23, "gap")


def test_sparse_does_not_outrank_a_slot_explanation():
    """A note count can differ for the same reason the slot does; the slot is
    the more specific answer and stays the answer."""
    rec = _one(_voice(0x0A09, 12, 12, 8), _voice(0x0A09, 6, 6, 2))
    assert rec["kind"] == "slot"


# -- it classifies the column it reports on -----------------------------------

def test_the_population_is_the_columns_denominator():
    o = _voices(_voice(0x0A09, 8, 8, 4), _voice(0x0F00, 8, 8, 4))
    u = _voices(_voice(0x0A09, 8, 7, 4))
    assert (len(F.hold_census(o, u, NF))
            == F.sound_run_agreement(o, u, NF)["sound_run_instruments"] == 1)


def test_the_match_count_is_the_columns_numerator():
    o = _voices(_voice(0x0A09, 8, 8, 4), _voice(0x0F00, 8, 8, 4))
    u = _voices(_voice(0x0A09, 8, 8, 4), _voice(0x0F00, 8, 7, 4))
    census = F.hold_census(o, u, NF)
    agree = F.sound_run_agreement(o, u, NF)
    assert sum(1 for r in census if r["kind"] == "match") == agree["sound_run_matched"] == 1
    assert Counter(r["kind"] for r in census)["fetch"] == 1


def test_the_reduction_is_the_columns_own():
    """`sound_runs` is now derived from `sound_note_runs`, so the two cannot
    disagree about a note's length even if one of them is edited."""
    v = _voices(_voice(0x0A09, 8, 5, 4))
    assert F.sound_runs(v, NF) == {
        0x0A09: Counter(h for h, _, _ in F.sound_note_runs(v, NF)[0x0A09])}


def test_the_kinds_the_report_prints_are_the_kinds_it_can_produce():
    kinds = {F.classify_hold(d, s, no, nu, o, u)
             for d in (-7, -2, -1, 0, 3, 9) for s in (-2, 0, 6)
             for no, nu in ((8, 8), (12, 5), (8, 2))
             for o, u in (((6, 6), (6, 6)), ((6, 23), (23, 23)))}
    assert kinds == set(F.HOLD_KINDS)


def test_the_report_names_the_rate_a_deficit_is_invisible_at():
    """A zero above `-S3` is the trace's resolution, not the converter's, and
    the report has to say so where the counts are read."""
    rows = [{"file": "x.sid", "multiplier": 4, "options": {},
             "hold_census": [{"adsr": 0x0A09, "orig_held": 8, "our_held": 8,
                              "delta": 0, "orig_slot": 8, "our_slot": 8,
                              "slot_delta": 0, "orig_notes": 4,
                              "our_notes": 4, "kind": "match"}]}]
    text = F.hold_census_report(rows)
    assert "invisible above `-S3`" in text
    assert "| 4 | no | 1 | 0 | 0 | 0 | 0 | 0 |" in text
