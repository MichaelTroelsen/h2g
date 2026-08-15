"""`fidelity_better`'s gate term -- what makes a gate-only change selectable.

Every other term here reads a register `--rest-keyoff` does not touch. A
Goattracker KEYOFF clears $D404's gate bit and nothing else; `wave` excludes
that bit by construction, `hold` counts frames with a waveform *selected*,
`adsr` and `tail` read the envelope pair. So the option moved 19 corpus files'
bytes, moved one number on one file, and had to ship on a hand-rolled probe
(v0.5.269) before `gate` existed to score it (v0.5.270).

The two properties this file pins are the ones that could go wrong quietly:
the term is guarded by `keeps_notes`, because a conversion with fewer notes
has more gate-off frames and would score higher for it; and it is an
acceptance term only, never a veto, because `gate` is scored over the frames
*either* side has the voice released -- a denominator the setting under test
changes.
"""
import presets


def _state(melody=0.9, seq=0.9, attacks=100, noise=(0, 0, 0, 0),
           osc=1.0, onset=0.5, hold=0.5, gate=0.4):
    return (melody, seq, attacks, noise, osc, onset, hold, gate)


def test_a_better_gate_wins_on_its_own():
    """Nothing else moves: no new note, no new register, same waveforms."""
    ref = _state(gate=0.40)
    cand = _state(gate=0.85)
    assert presets.fidelity_better(cand, ref)


def test_a_worse_gate_does_not():
    assert not presets.fidelity_better(_state(gate=0.30), _state(gate=0.40))


def test_an_unchanged_gate_recommends_nothing():
    assert not presets.fidelity_better(_state(gate=0.40), _state(gate=0.40))


def test_it_is_guarded_by_the_attack_count():
    """The gaming vector: fewer notes means more gate-off frames.

    A candidate that deletes a fifth of the notes and scores better on `gate`
    for it must be refused -- the same guard section 7.eee added when a
    candidate reached `wave` 99.5% on Commando by deleting 79 notes.
    """
    ref = _state(attacks=100, gate=0.40)
    cand = _state(attacks=80, gate=0.95)
    assert not presets.fidelity_better(cand, ref)


def test_it_is_guarded_by_melody_and_sequence():
    ref = _state(gate=0.40)
    assert not presets.fidelity_better(_state(melody=0.5, gate=0.95), ref)
    assert not presets.fidelity_better(_state(seq=0.5, gate=0.95), ref)


def test_it_may_not_be_bought_with_the_oscillation():
    """The trade `hold` had to learn to refuse, on the same terms."""
    ref = _state(osc=0.93, gate=0.40)
    cand = _state(osc=0.05, gate=0.90)
    assert not presets.fidelity_better(cand, ref)
    # ...but a rate that was already absent is not a rate given up.
    ref2 = _state(osc=0.32, gate=0.40)
    assert presets.fidelity_better(_state(osc=0.29, gate=0.90), ref2)


def test_a_state_without_the_term_recommends_nothing():
    """A run from before the term existed must not be read as an improvement."""
    old = (0.9, 0.9, 100, (0, 0, 0, 0), 1.0, 0.5, 0.5)
    assert not presets.fidelity_better(old, old)
    assert not presets.fidelity_better(old, _state(gate=0.1))


def test_the_margin_applies():
    ref = _state(gate=0.400)
    assert not presets.fidelity_better(_state(gate=0.401), ref)


def test_it_is_not_a_veto():
    """A candidate better elsewhere is not blocked by a lower gate.

    `gate`'s denominator is the frames either side has the voice released, so
    a setting that adds releases changes the sample it is judged on -- the
    same reason the oscillation and the noise pitch are kept out of
    `gave_back`, where a veto once cost seven measured settings.
    """
    ref = _state(gate=0.80, noise=(0, 100, 0, 0))
    cand = _state(gate=0.40, noise=(90, 100, 200, 200))
    assert presets.fidelity_better(cand, ref)
