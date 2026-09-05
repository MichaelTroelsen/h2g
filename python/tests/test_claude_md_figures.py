"""CLAUDE.md's live population figures, re-derived from the generated artefacts.

CLAUDE.md is largely numbers and nothing re-derives them. Its own rule is that a
figure is either HISTORICAL, carrying the version it was measured at, or LIVE
and re-checked -- and the ungraded middle is what gets cited as current. The
v0.5.455 pass did this by hand in a script and found three of five "re-verified
live" entries stale; the pass was entirely mechanical, which is the argument for
committing it.

WHAT THIS CANNOT DO. It checks the figures that `presets.json`,
`build/fidelity.json` and `docs/SURVEY.md` can derive. Most of CLAUDE.md's
numbers are before/after percentages from one-off A/Bs and have no artefact to
check against; those stay a human's job and the grading rule stays the defence.

Skips rather than fails when an artefact is absent -- `build/fidelity.json` is
gitignored, so a clean checkout legitimately has none, and asserting against a
missing artefact would fail for the one reason this test is not about.
"""
from __future__ import annotations

import collections
import json
import re
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]
CLAUDE_MD = ROOT / "CLAUDE.md"
PRESETS = ROOT / "presets.json"
FIDELITY = ROOT / "build" / "fidelity.json"
SURVEY = ROOT / "docs" / "SURVEY.md"


def _text():
    if not CLAUDE_MD.exists():
        pytest.skip("CLAUDE.md absent")
    return CLAUDE_MD.read_text(encoding="utf-8")


def _songs():
    if not PRESETS.exists():
        pytest.skip("presets.json absent")
    return json.loads(PRESETS.read_text(encoding="utf-8"))["songs"]


def _rows():
    if not FIDELITY.exists():
        pytest.skip("build/fidelity.json absent -- it is gitignored")
    return json.loads(FIDELITY.read_text(encoding="utf-8"))


# CLAUDE.md's per-file figures are stamped with the version they were measured
# at, and every version before v0.5.459 measured at `-t 60`. An artefact taken
# at another window holds a DIFFERENT QUANTITY, not a corrected one -- attack
# counts scale with the window almost linearly (Skate_or_Die 1020 -> 3151) and
# `drift_per_1000` is an integrated offset, the most window-sensitive number
# the report carries. So each such figure declares the window it was taken at
# and its check SKIPS elsewhere, exactly as the file already skips a missing
# artefact. A POPULATION figure from `presets.json` has no window and is
# always checked.
FIGURE_WINDOW = 60


def _window(rows):
    """The `-t` seconds this artefact was generated at."""
    for r in rows:
        if r.get("seconds") is not None:
            return r["seconds"]
    pytest.skip("build/fidelity.json rows carry no `seconds`")


def _needs_window(rows, taken_at=FIGURE_WINDOW):
    got = _window(rows)
    if got != taken_at:
        pytest.skip(
            f"artefact is -t {got} and this CLAUDE.md figure was taken at "
            f"-t {taken_at}: comparing them would compare two different "
            f"quantities, not find a stale one. Regenerate the artefact at "
            f"-t {taken_at}, or re-grade the figure at -t {got} and move "
            f"FIGURE_WINDOW.")


def _says(text, *fragments):
    """Assert CLAUDE.md contains each fragment, quoting what to fix if not."""
    for f in fragments:
        assert f in text, (
            f"CLAUDE.md no longer says {f!r} -- either the figure moved and the "
            f"file needs correcting, or the wording changed and this test needs "
            f"the new wording")


# ------------------------------------------------------------ presets.json

def test_the_wave_program_split_is_what_presets_says():
    songs, text = _songs(), _text()
    wp = [k for k, o in songs.items() if o.get("wave_program")]
    multi = sum(1 for k in wp if (songs[k].get("multiplier") or 1) > 1)
    _says(text, f"**{multi} multispeed / {len(wp) - multi} single-speed**")


def test_the_regrid_adoption_count_is_what_presets_says():
    songs, text = _songs(), _text()
    _says(text, f"**{sum(1 for o in songs.values() if o.get('regrid'))} adoptions**")


def test_the_multiplier_population_is_what_presets_says():
    songs, text = _songs(), _text()
    m = collections.Counter((o.get("multiplier") or 1) for o in songs.values())
    above = sum(v for k, v in m.items() if k > 1)
    _says(text,
          f"{above} of the {len(songs)} preset songs",
          f"{m[2]} at `-S2`, {m[2] + m[3]} at")


# ------------------------------------------------------- build/fidelity.json

def test_the_drift_split_is_what_the_artefact_says():
    rows, text = _rows(), _text()
    _needs_window(rows)
    have = [r for r in rows
            if r.get("status") == "measured" and r.get("drift_per_1000") is not None]
    zero = sum(1 for r in have if abs(r["drift_per_1000"]) < 1e-9)
    _says(text, f"**{zero} zero / {len(have) - zero} drifting of {len(have)} rows")


def test_skate_or_die_intros_attack_counts_are_what_the_artefact_says():
    rows, text = _rows(), _text()
    _needs_window(rows)
    r = next((r for r in rows if r["file"] == "Skate_or_Die_intro.sid"), None)
    if r is None or r.get("our_attacks") is None:
        pytest.skip("Skate_or_Die_intro not in this artefact")
    _says(text, f"{r['our_attacks']} attacks against the original's\n    {r['orig_attacks']}")


def test_kings_of_the_beach_ingame_reads_what_the_artefact_says():
    rows, text = _rows(), _text()
    _needs_window(rows)
    r = next((r for r in rows if r["file"] == "Kings_of_the_Beach_ingame.sid"), None)
    if r is None or r.get("wave") is None:
        pytest.skip("Kings_of_the_Beach_ingame not in this artefact")
    _says(text, f"`wave` {r['wave'] * 100:.1f}% / `gate` {r['gate'] * 100:.1f}%")


# ------------------------------- the two artefacts that answer different questions

def test_the_corpus_counts_name_both_option_sets():
    """95 tested / 89 on presets / 86 on defaults -- and the file must say which."""
    rows, text = _rows(), _text()
    if not SURVEY.exists():
        pytest.skip("docs/SURVEY.md absent")
    sur = SURVEY.read_text(encoding="utf-8")
    m = re.search(r"Converted: \*\*(\d+)\*\* of (\d+) in reach", sur)
    if not m:
        pytest.skip("SURVEY.md header not in the expected shape")
    on_defaults, in_reach = int(m.group(1)), int(m.group(2))
    measured = sum(1 for r in rows if r.get("status") == "measured")
    _says(text,
          f"**{measured} convert",
          f"**{on_defaults} convert on DEFAULT",
          f"leaving {in_reach} in reach")


def test_this_file_checks_only_what_an_artefact_can_derive():
    """A guard on the guard: it must not silently shrink to nothing.

    If every assertion above were skipped, the suite would go green while
    checking no figure at all -- the vacuous-check failure this repo records.
    """
    assert PRESETS.exists() or FIDELITY.exists(), (
        "neither artefact present: this file checked NOTHING, which is not a pass")
    # ...and the window guard must not be able to hollow the file out. The
    # three `presets.json` population checks carry no window and so cannot be
    # skipped by it; if they ever could, every artefact check in this file
    # could go quiet at once while the suite stayed green.
    assert PRESETS.exists(), (
        "presets.json absent: the window-free population checks are the only "
        "ones that cannot be skipped by _needs_window, so without them this "
        "file can go entirely quiet while reporting green")
