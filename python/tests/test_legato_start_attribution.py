"""A note an instrument switch starts with the gate held is its own note.

`Voice.attack_frames` are gate rises, and fidelity's per-note splits keyed
every note on one. Spellbound switches `$0FFF` -> `$0F0A` 13 times with the
gate held (no rise): the original's 159 `$0F0A` reversals were counted under
`$0FFF` (172 vs 0) while our conversion, which re-attacks, counted them under
`$0F0A` (375 vs 228) -- an apparent 1.5x excess that was the split's. Read at
3b1c66d (HISTORICAL) by spellbound-0f0a-extra-alternation.

`legato_starts` finds those frames; `reversals_by_instrument`,
`oscillation_depths` and `moving_frames` use them. The totals the column
reports (`pitch_motion`) are unchanged, and a test here pins that.
"""
import pathlib
import sys

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[1]))

import fidelity as F  # noqa: E402

OLD, NEW = 0x0FFF, 0x0F0A
SWITCH = 40


def _osc(start, n, step=0x40, centre=0x1000):
    return [(start + i, centre + (step if i % 2 else 0)) for i in range(n)]


def _voice(adsr_events, wf_events, freqs, attacks=(0,)):
    v = F.Voice()
    v.attack_frames = list(attacks)
    v.attacks = [f"n{i}" for i in range(len(attacks))]
    v.freq_events = list(freqs)
    v.adsr_events = list(adsr_events)
    v.wf_events = list(wf_events)
    return v


def _legato(wf_after=0x15, adsr_at=SWITCH):
    """One gate rise at 0 on $0FFF; at SWITCH the instrument becomes $0F0A."""
    return _voice([(0, OLD), (adsr_at, NEW)],
                  [(0, 0x11), (SWITCH, wf_after)],
                  _osc(0, SWITCH) + _osc(SWITCH, 40, centre=0x2000))


def _trace(v):
    return F.Trace([v, F.Voice(), F.Voice()], F.FilterState())


def test_a_switch_with_the_gate_held_is_a_note_start():
    assert F.legato_starts(_legato(), 100) == [SWITCH]
    assert F.note_starts(_legato(), 100) == [0, SWITCH]


def test_the_new_notes_reversals_go_to_its_own_instrument():
    got = F.reversals_by_instrument(_trace(_legato()), 100)
    assert got[OLD] > 10 and got[NEW] > 10
    # Before the fix every reversal of the second note sat under $0FFF.
    assert got[NEW] >= 35


def test_the_split_still_adds_up_to_the_column():
    t = _trace(_legato())
    assert sum(F.reversals_by_instrument(t, 100).values()) == \
        F.pitch_motion(t, 100)["reversals"]


def test_a_gate_off_gap_is_not_a_legato_start():
    """The ADSR is rewritten while the gate is clear: that is a release
    edit, not a note start."""
    v = _voice([(0, OLD), (SWITCH, NEW)], [(0, 0x11), (SWITCH - 1, 0x10)],
               _osc(0, 80))
    assert F.legato_starts(v, 100) == []
    assert set(F.reversals_by_instrument(_trace(v), 100)) == {OLD}


def test_a_gate_that_rises_with_the_rewrite_is_not_a_held_gate():
    """A gate rise siddump printed at freq $0000 is dropped from
    `attack_frames` (`unnamed_attack_frames`): the gate is clear on the
    frame before, so the rewrite is not one with the gate HELD."""
    v = _voice([(0, OLD), (SWITCH, NEW)],
               [(0, 0x11), (SWITCH - 1, 0x10), (SWITCH, 0x11)], _osc(0, 80))
    assert F.legato_starts(v, 100) == []


def test_a_voice_with_no_waveform_trace_has_no_legato_starts():
    v = _voice([(0, OLD), (SWITCH, NEW)], [], _osc(0, 80))
    assert F.legato_starts(v, 100) == []


def test_a_rewrite_on_an_attack_frame_is_the_attacks_own():
    v = _voice([(0, OLD), (SWITCH, NEW)], [(0, 0x11)], _osc(0, 80),
               attacks=(0, SWITCH))
    assert F.legato_starts(v, 100) == []
    assert F.note_starts(v, 100) == [0, SWITCH]


def test_a_write_before_the_first_attack_is_not_a_note():
    v = _voice([(0, OLD), (5, NEW)], [(0, 0x11)], _osc(0, 80),
               attacks=(10,))
    assert F.legato_starts(v, 100) == []


def test_the_depth_split_reads_the_legato_note_under_its_own_key():
    v = _legato()
    got = F.oscillation_depths([v], 100, keys={NEW},
                               audible_only=False)
    assert NEW in got and got[NEW] > 0
    mv = F.moving_frames([v], 100, keys={NEW}, audible_only=False)
    assert mv.get(NEW, 0) > 30
    # the first note alone is not attributed to the new instrument
    only_old = _voice([(0, OLD)], [(0, 0x11)], _osc(0, SWITCH))
    assert F.moving_frames([only_old], 100, keys={NEW},
                           audible_only=False) == {}
