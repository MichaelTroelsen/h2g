"""How long a note keeps a waveform selected -- the column for note length.

CLAUDE.md has recorded for most of this project's life that no dimension
measures note length, and the `onset` census's `short` kind named five
instruments where our note stops selecting a waveform inside the four-frame
opening window while the original still does. This is that observation turned
into a measurement.

The mechanism it sees, Commando voice 0 on twelve-frame notes:

    ORIGINAL  15 80 80 14 14 14 14 14 14 14 14 14 | next attack
    OURS      15 81 81 15 15 15 15 15 15 14 14 09 | next attack

Goattracker fetches the next note `gatetimer & $3f` ticks early
(gplay.c:905) and writes the instrument's `firstwave` -- `$09`, test bit and
gate, no waveform -- so the note before it loses its final frame.
"""
import pathlib
import sys
from collections import Counter

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[1]))

import fidelity as F  # noqa: E402


def _voices(*event_lists):
    vs = [F.Voice(wf_events=list(wf), adsr_events=list(ad),
                  attack_frames=list(at))
          for wf, ad, at in event_lists]
    return vs + [F.Voice()] * (3 - len(event_lists))


def test_a_note_sounds_until_its_waveform_is_deselected():
    """Four frames of triangle, then `$09` -- three sounding frames, and the
    fourth is the one Goattracker spends on the next note's reset."""
    v = _voices(([(0, 0x11), (3, 0x09)], [(0, 0x0A09)], [0, 8]))
    assert F.sound_runs(v, 16) == {0x0A09: Counter({3: 1})}


def test_a_latched_waveform_sounds_to_the_end_of_the_slot():
    """A gated-off voice keeps its waveform, which is what the original does:
    `80` held to the next attack counts every frame of the slot."""
    v = _voices(([(0, 0x81), (1, 0x80)], [(0, 0x0A09)], [0, 8]))
    assert F.sound_runs(v, 16) == {0x0A09: Counter({8: 1})}


def test_the_slot_is_capped_at_the_next_attack():
    """Without the cap the original's run would cross every note to the end of
    the window and be dropped as window-cut, which is the "nothing to compare"
    trap `release_tails` fell into."""
    v = _voices(([(0, 0x11)], [(0, 0x0A09)], [0, 4, 8]))
    assert F.sound_runs(v, 16) == {0x0A09: Counter({4: 2})}


def test_a_note_whose_slot_reaches_the_window_is_dropped():
    """Its length would be a fact about the window, not about the note."""
    v = _voices(([(0, 0x11)], [(0, 0x0A09)], [0, 4]))
    assert F.sound_runs(v, 16) == {0x0A09: Counter({4: 1})}


def test_the_key_is_the_adsr_after_the_attack():
    v = _voices(([(0, 0x11)], [(0, 0x0000), (1, 0x0A09)], [0, 4]))
    assert list(F.sound_runs(v, 16)) == [0x0A09]


# ---- the agreement --------------------------------------------------------

def test_matching_lengths_agree_and_the_delta_is_zero():
    o = _voices(([(0, 0x11)], [(0, 0x0A09)], [0, 4]))
    u = _voices(([(0, 0x11)], [(0, 0x0A09)], [0, 4]))
    got = F.sound_run_agreement(o, u, 16)
    assert got["sound_run_agreement"] == 1.0
    assert got["sound_run_delta"] == 0


def test_a_note_one_frame_short_reads_as_a_delta_of_minus_one():
    """The corpus-wide signature as shipped: nothing matches, and the number
    worth reading is the delta rather than the zero."""
    o = _voices(([(0, 0x11)], [(0, 0x0A09)], [0, 4]))
    u = _voices(([(0, 0x11), (3, 0x09)], [(0, 0x0A09)], [0, 4]))
    got = F.sound_run_agreement(o, u, 16)
    assert got["sound_run_matched"] == 0
    assert got["sound_run_delta"] == -1


def test_an_instrument_only_one_side_plays_is_absent_rather_than_wrong():
    """`melody` already reports a dropped instrument; counting it here too
    would let one defect move two columns."""
    o = _voices(([(0, 0x11)], [(0, 0x0A09)], [0, 4]),
                ([(0, 0x41)], [(0, 0x0F00)], [0, 4]))
    u = _voices(([(0, 0x11)], [(0, 0x0A09)], [0, 4]))
    assert F.sound_run_agreement(o, u, 16)["sound_run_instruments"] == 1


def test_the_dimension_is_registered_and_printed():
    """`tests/test_fidelity.py` fails if the registry and the header disagree;
    this is the same check from the other end."""
    keys = [d.key for d in F.DIMENSIONS]
    assert "sound_run_agreement" in keys
    assert [d for d in F.DIMENSIONS if d.key == "sound_run_agreement"][0].column == "hold"


# --- v0.5.247: `hold` as an acceptance term in the preset search ------------

def _state(melody, seq, attacks, hold, *, noise=(10, 10, 100, 100),
           osc=1.0, onset=0.5):
    """A `presets.play()` result: the 7-tuple `fidelity_better` reads."""
    return (melody, seq, attacks, noise, osc, onset, hold)


def test_a_candidate_that_only_holds_longer_is_accepted():
    """The five files this term exists for -- Chicken Song, Delta, Tarzan, Wiz,
    Sanxion -- gain `hold` 0 -> 100% with melody, onset and everything else
    unmoved, so no other term can see them."""
    import presets as P
    ref = _state(0.9, 0.9, 100, 0.0)
    cand = _state(0.9, 0.9, 100, 1.0)
    assert P.fidelity_better(cand, ref)


def test_it_cannot_buy_a_hold_gain_with_notes():
    """Forced corpus-wide, `--no-test-restart` gains 49 points of hold and
    costs 21 of melody on 68 files with none improving. `keeps_notes` refuses
    every one of them, and this term must not override that."""
    import presets as P
    ref = _state(0.9, 0.9, 100, 0.0)
    cand = _state(0.6, 0.6, 100, 1.0)
    assert not P.fidelity_better(cand, ref)


def test_hold_is_not_a_veto():
    """Asymmetric on purpose: a new veto cost seven measured settings the last
    time one was widened (v0.5.230), so a candidate winning on another term is
    not blocked by holding for less."""
    import presets as P
    ref = _state(0.9, 0.9, 100, 1.0)
    cand = _state(0.95, 0.9, 100, 0.0)      # plays_more, holds worse
    assert P.fidelity_better(cand, ref)


def test_a_state_without_the_term_still_compares():
    """`play()` grew a seventh element; a tuple from before it must not raise."""
    import presets as P
    old_ref = (0.9, 0.9, 100, (10, 10, 100, 100), 1.0, 0.5)
    assert not P.fidelity_better(old_ref, old_ref)


def test_hold_will_not_buy_note_length_with_anything_else():
    """After_8 swapped `pitch_seq` for `no_test_restart` on this term: hold
    0 -> 50% and wave +3, paid for with melody 92 -> 91%, pitch 97 -> 95% and
    its arpeggio ratio collapsing 0.93 -> 0.29. `keeps_notes` allows a melody
    slip inside the margin and `gave_back` does not watch oscillation, so the
    weak form is what stops it."""
    import presets as P
    ref = _state(0.92, 0.91, 100, 0.0, osc=0.93)
    cand = _state(0.91, 0.90, 100, 0.5, osc=0.29)
    assert not P.fidelity_better(cand, ref)
    # ...but the veto is about a change of *rate*, not about any move. Chicken
    # Song's 0.32 -> 0.29 is the same absence of an oscillation measured twice,
    # and blocked a hold gain of 0 -> 100% while `_closer` sized the veto.
    weak = _state(0.62, 0.63, 100, 0.0, osc=0.32)
    assert P.fidelity_better(_state(0.619, 0.628, 100, 1.0, osc=0.29), weak)
    # ...while a melody move of a few thousandths is the noise floor of a
    # difflib ratio and must not block a hold gain of 0 -> 100%. Requiring
    # melody not to fall at all blocked seven of the eight files this term
    # reaches; `keeps_notes` governs melody, with its margin.
    assert P.fidelity_better(_state(0.916, 0.906, 100, 1.0, osc=0.93), ref)


def test_the_oscillation_veto_asks_about_rate_not_direction():
    """0.93 -> 0.29 is a different rate; 0.32 -> 0.29 is the same absence of
    one. The bound is a factor of two from the original's rate -- a statement
    about audibility rather than a threshold fitted to the corpus."""
    from presets import _oscillation_lost
    assert _oscillation_lost(0.29, 0.93)
    assert not _oscillation_lost(0.29, 0.32)
    assert not _oscillation_lost(0.48, 0.51)
    assert not _oscillation_lost(None, 0.93), "unmeasurable cannot veto"
    assert not _oscillation_lost(0.9, 0.5), "nor may a move toward the rate"
    # ...and crossing over still counts as leaving it: 0.9 is 10% under the
    # original's rate and 1.4 is 40% over, which is further away, not nearer.
    assert _oscillation_lost(1.4, 0.9)
