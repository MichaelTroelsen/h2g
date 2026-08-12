"""`fidelity_better`'s onset term -- the only one that can select --two-stage.

The scorer's own docstring records that it is *deliberately* not scored on
`wave`, because restoring a 1-4 frame attack transient moves `wave` the wrong
way even when the transient is right. That reasoning is sound, and it left the
setting unselectable: the attack strikes no new note, sounds no new register
and leaves `melody` untouched, so not one of the other four terms could see it.

Measured over the corpus at v0.5.220: 45 files sound an attack transient at 109
instruments -- about 13,700 notes -- that the conversion holds flat, and 42 of
those files have `--two-stage` off.
"""
import presets


def _state(melody=0.9, seq=0.9, attacks=100, noise=(0, 0, 0, 0),
           osc=1.0, onset=0.5):
    return (melody, seq, attacks, noise, osc, onset)


def test_a_better_opening_wins_on_its_own():
    """Nothing else moves: same notes, same registers, same oscillation."""
    ref = _state(onset=0.50)
    cand = _state(onset=0.75)
    assert presets.fidelity_better(cand, ref)


def test_a_worse_opening_does_not():
    assert not presets.fidelity_better(_state(onset=0.50),
                                       _state(onset=0.75))


def test_it_is_still_guarded_by_keeps_notes():
    """Every term in this function is one-sided *and* guarded. An opening that
    improves while the tune loses notes is the section 7.eee trade the whole
    scorer exists to refuse."""
    ref = _state(onset=0.50, attacks=100)
    assert not presets.fidelity_better(_state(onset=1.0, attacks=80), ref)
    assert not presets.fidelity_better(_state(onset=1.0, melody=0.5), ref)


def test_a_state_without_the_term_recommends_nothing():
    """A tuple built before this term existed carries no onset figure, and an
    absent dimension must read as unmeasurable rather than as zero -- the same
    rule the oscillation term follows."""
    old = (0.9, 0.9, 100, (0, 0, 0, 0), 1.0)
    assert not presets.fidelity_better(old, old)
    # ...and a new candidate against an old reference cannot win on onset alone
    assert not presets.fidelity_better(_state(onset=1.0), old)


def test_the_margin_applies():
    """A hair's movement is not a decision; FIDELITY_MARGIN is what makes the
    search reproducible rather than noise-following."""
    ref = _state(onset=0.50)
    tiny = _state(onset=0.50 + presets.FIDELITY_MARGIN / 2)
    assert not presets.fidelity_better(tiny, ref)


def test_two_stage_stays_a_per_song_toggle():
    """This term makes the setting *selectable*, not global. The transient is a
    property of the record's own effect byte, and 3 of the 45 files already
    carry it -- the search decides the rest per song."""
    assert "two_stage" in presets.FIDELITY_TOGGLES
    assert "two_stage" in presets.EXCLUDED_FROM_ALWAYS
