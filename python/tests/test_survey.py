"""The survey report must say which options its counts were taken under.

This exists because `docs/SURVEY.md` and `presets.json` legitimately disagree
about how many corpus files convert -- SURVEY converts on the DEFAULTS plus
whatever flags the run was given, `presets.json` records a per-song option set,
and options that are not defaults (`--prune-patterns`, `--dedup-patterns`, a
raised `--max-rows`) rescue files that hit a Goattracker limit at the defaults.
Measured at v0.5.455: SURVEY read 86 of 89 in reach while presets.json and
build/fidelity.json carried 89, and the three-file gap was Delta,
Dragons_Lair_Part_II and W_A_R. Both artefacts were right; nothing said so.

The report states the option SET rather than that count, because the count
decays with the corpus and the set does not.
"""
from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import survey  # noqa: E402


def _report(**kw) -> str:
    return survey.build_report([], Path("corpus"), **kw)


def test_report_names_the_option_set_its_count_was_taken_under():
    text = _report()
    assert "Counted under:" in text
    assert "default conversion options" in text
    # It must say what it is NOT, or a reader still cannot place the number.
    assert "presets.json" in text


def test_the_option_state_is_reported_rather_than_assumed():
    off = _report(dedup=False, prune=False)
    on = _report(dedup=True, prune=True)
    assert "`--dedup-patterns` off" in off and "`--prune-patterns` off" in off
    assert "`--dedup-patterns` on" in on and "`--prune-patterns` on" in on
    # A report that printed the same line either way would pass the test above
    # while telling the reader nothing.
    assert off != on


def test_max_rows_is_carried_into_the_option_line():
    assert "`--max-rows 94`" in _report(max_rows=94)
    assert "`--max-rows 128`" in _report(max_rows=128)


def test_the_blockquote_explains_why_presets_can_convert_more():
    text = _report()
    assert "generally" in text and "larger" in text
    # The point of the paragraph is that neither artefact is wrong.
    assert "both are" in text and "right" in text


def test_build_report_still_accepts_its_old_positional_signature():
    # The two new parameters are keyword-only in practice: every existing caller
    # passes four positionals, and a signature change that broke them would be a
    # silent regression in survey.py's own main().
    text = survey.build_report([], Path("corpus"), 94, survey.DEFAULT_FORMAT, True)
    assert "Counted under:" in text
