"""The DIGI hold (python/hold.py): the set is derived, and the index parks it."""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import abpage as A  # noqa: E402
import hold  # noqa: E402
from corpus import CORPUS, needs_corpus  # noqa: E402
from h2g.convert import _detect_tables  # noqa: E402
from h2g.sidfile import load_sid  # noqa: E402


@needs_corpus
def test_on_hold_is_exactly_the_files_whose_player_drives_a_fourth_voice():
    """hold.ON_HOLD names `track_voices > 3`, survey.py's own "digi channel
    dropped" test. Re-derived over the corpus through convert()'s detection
    path, so a hand edit to the list, or a detection change that moves a file
    across the line, fails here rather than silently changing what is held."""
    four = set()
    for path in sorted(CORPUS.glob("*.sid")):
        try:
            _sid, det = _detect_tables(load_sid(path), log=lambda m: None)
        except Exception:  # noqa: BLE001 -- a file that does not detect is not held
            continue
        if det.track_voices > 3:
            four.add(path.name)
    assert four, "no corpus file detected a fourth voice: this checked nothing"
    assert four == set(hold.FOURTH_VOICE) | set(hold.RELEASED)


@needs_corpus
def test_every_named_hold_is_still_sidid_tagged_digi():
    """The user's by-name additions have no predicate behind them; this pins
    the one property they share, so a name that stops matching (a renamed
    corpus file, a changed SIDId database) fails rather than holding nothing."""
    from h2g.sidid import find_database
    db = find_database()
    if db is None:
        import pytest
        pytest.skip("no sidid.cfg on this machine")
    assert hold.NAMED, "no named holds: this checked nothing"
    for name in hold.NAMED:
        path = CORPUS / name
        assert path.is_file(), f"{name} is not in the corpus"
        names = db.identify(load_sid(path).data)   # the tag reads "(Rob_Hubbard_Digi)"
        assert any("Rob_Hubbard_Digi" in n for n in names), (name, names)
    assert not set(hold.NAMED) & set(hold.FOURTH_VOICE)


@needs_corpus
def test_the_hold_covers_every_sidid_digi_file_and_nothing_else():
    """As of 2026-09-30 the hold is exactly every corpus file SIDId tags
    `(Rob_Hubbard_Digi)` (Pygmies_Revenge, fourth voice but tagged plain
    Rob_Hubbard, was released). A new digi file, or a hold on anything else,
    fails here instead of silently widening or narrowing the rule."""
    from h2g.sidid import find_database
    db = find_database()
    if db is None:
        import pytest
        pytest.skip("no sidid.cfg on this machine")
    digi = {p.name for p in CORPUS.glob("*.sid")
            if any("Rob_Hubbard_Digi" in n for n in db.identify(load_sid(p).data))}
    assert digi, "no digi-tagged corpus file: this checked nothing"
    assert digi == set(hold.ON_HOLD)
    assert not digi & set(hold.RELEASED)


def test_held_accepts_a_stem_or_a_filename():
    assert hold.held("Rikky") == hold.held("Rikky.sid") == hold.DIGI_REASON
    assert hold.held("Commando") is None


def test_the_index_parks_held_tunes_in_their_own_card():
    html = A.index(["Commando", "Rikky"], {}, "0.5.493")
    staged, _, parked = html.partition("On hold: DIGI (1)")
    assert parked, "no On hold card rendered"
    assert 'href="Rikky.html"' in parked and 'href="Rikky.html"' not in staged
    assert 'href="Commando.html"' in staged and 'href="Commando.html"' not in parked
    assert '<span class="onhold"' in parked
    assert "(1 on hold)" in staged


def test_no_held_tune_means_no_on_hold_card():
    html = A.index(["Commando"], {}, "0.5.493")
    assert "On hold" not in html and "on hold)" not in html
