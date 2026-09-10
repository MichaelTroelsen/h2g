"""CLAUDE.md's live population figures, re-derived from the generated artefacts.

Reads `docs/LESSONS.md`, which since v0.5.475 holds CLAUDE.md's own text and all
of its numbers -- see the comment on CLAUDE_MD below.

That text is largely numbers and nothing re-derives them. CLAUDE.md's rule is that a
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
# WHERE THE FIGURES LIVE NOW. CLAUDE.md was compacted at v0.5.475 into an index
# of rules, and its 2300 lines of evidence moved VERBATIM to `docs/LESSONS.md`.
# Every figure this guard reads went with them, so it reads that file. The
# test's name is kept because the rule it enforces is CLAUDE.md's own grading
# rule and the archive is CLAUDE.md's own text; a figure that comes BACK into
# CLAUDE.md needs its own check here against `ROOT / "CLAUDE.md"`.
CLAUDE_MD = ROOT / "docs" / "LESSONS.md"
PRESETS = ROOT / "presets.json"
FIDELITY = ROOT / "build" / "fidelity.json"
SURVEY = ROOT / "docs" / "SURVEY.md"


def _text():
    if not CLAUDE_MD.exists():
        pytest.skip(f"{CLAUDE_MD.name} absent")
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
# Moved 60 -> 180 at v0.5.460, when the three figures the guard was
# skipping were RE-MEASURED at 180 rather than re-labelled. Moving
# this constant without re-measuring is the one thing it must never
# be used for: it would turn every 60 s figure in the file into a
# claim about a window nobody measured it in.
FIGURE_WINDOW = 180


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
    """Assert docs/LESSONS.md contains each fragment, quoting what to fix if not."""
    for f in fragments:
        assert f in text, (
            f"docs/LESSONS.md no longer says {f!r} -- either the figure moved "
            f"and the file needs correcting, or the wording changed and this "
            f"test needs the new wording")


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


# --------------------------------------------------- grep-zero-on-a-quotation

def test_the_grep_zero_rule_cites_its_measured_instances():
    """CLAUDE.md's rule about a counter that cannot see its own container
    must carry its evidence in docs/LESSONS.md, not just an assertion."""
    claude_md = (ROOT / "CLAUDE.md").read_text(encoding="utf-8")
    assert "evidence about the counter, not about the file" in claude_md
    assert "grep for a retracted sentence" in claude_md
    text = _text()
    _says(text,
          "survey.py:669-670",
          "fidelity.py:2780-2781",
          "H2G-CONVERSION-METHOD.md:4511",
          "NAMING ARTEFACTS",
          "a grep for a retracted sentence hits the retraction itself")


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


def _window_guarded_figures():
    """The tests in this module whose body calls `_needs_window`.

    DERIVED, not listed. A hand-written roster is a second place to forget:
    a new window-guarded figure would skip silently and the roster would
    still read complete. Reading the source means the registry cannot be
    out of date with the tests it describes.
    """
    import inspect
    import sys

    mod = sys.modules[__name__]
    found = set()
    for name, fn in vars(mod).items():
        if not name.startswith("test_") or not callable(fn):
            continue
        try:
            src = inspect.getsource(fn)
        except OSError:            # pragma: no cover -- source always present here
            continue
        if "_needs_window(" in src:
            found.add(name)
    return found


def test_a_window_mismatch_fails_loudly_instead_of_skipping_quietly():
    """The guard on the window guard: a skip must not be able to hide staleness.

    `_needs_window` is RIGHT to skip -- two windows are two quantities, and
    comparing them would manufacture a stale figure rather than find one.
    But a skip is invisible: `5 passed, 3 skipped` reads as a healthy run,
    and it says nothing about whether those three figures are correct, only
    that they could not be compared. Measured at 826dec8, the file sat at
    exactly that -- three figures unchecked behind a green run, and the only
    reason anyone noticed was that a task named it.

    So the SKIP stays (it is the honest thing to do with the assertion) and
    the INVISIBILITY goes: when the artefact's window and `FIGURE_WINDOW`
    disagree, this test fails once, names both windows, and names every
    figure that has gone quiet. One red line instead of N silent skips.
    """
    guarded = _window_guarded_figures()
    # Not vacuous: if the guarded set is empty, either every window-guarded
    # figure was deleted or `_needs_window` was renamed out from under this
    # check -- both of which would make the assertion below pass by having
    # nothing to say.
    assert guarded, (
        "no test in this module calls _needs_window: either the "
        "window-guarded figures are gone or the helper was renamed, and "
        "either way this guard is now checking nothing")

    if not FIDELITY.exists():
        pytest.skip(
            "build/fidelity.json absent -- it is gitignored, so a clean "
            "checkout legitimately has none. That is a different emptiness "
            "from a window mismatch and is not what this guard is about")

    got = _window(_rows())
    assert got == FIGURE_WINDOW, (
        f"build/fidelity.json is -t {got} and FIGURE_WINDOW is "
        f"{FIGURE_WINDOW}, so {len(guarded)} figure check(s) are being "
        f"SKIPPED and the run would otherwise report green: "
        f"{', '.join(sorted(guarded))}. Those figures are not wrong and are "
        f"not right -- they are unchecked. Fix it by regenerating the "
        f"artefact at -t {FIGURE_WINDOW}, or by RE-MEASURING each figure at "
        f"-t {got} and then moving FIGURE_WINDOW; never by moving "
        f"FIGURE_WINDOW alone, which relabels every figure as a claim about "
        f"a window nobody measured it in")
