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


# TWO KINDS OF EMPTINESS, AND ONLY ONE MAY BE QUIET. A guard that reads a
# file the checkout legitimately lacks -- a GITIGNORED artefact, absent on
# every clean clone -- may `pytest.skip`: nothing is wrong, there is nothing
# to read. A guard that reads a TRACKED file, or a shape inside a file it did
# open, must FAIL when it finds nothing: the file was moved, the artefact's
# format changed, or a regex stopped matching, and each of those is the check
# breaking, not the input being absent. Skipping there leaves a green run
# that says nothing, which is the shape
# `test_a_window_mismatch_fails_loudly_instead_of_skipping_quietly` was
# written against for the window guard; this applies the same rule to every
# other guard in the file. `test_every_quiet_skip_names_a_gitignored_artefact`
# reads the source and refuses any new skip that is not of the first kind.
def _broken(what):
    pytest.fail(f"{what} -- this is the check breaking, not an input being "
                f"legitimately absent, so it fails rather than skips; see the "
                f"two-kinds-of-emptiness note above _broken()")


def _text():
    if not CLAUDE_MD.exists():
        _broken(f"{CLAUDE_MD.relative_to(ROOT)} is tracked and absent")
    return CLAUDE_MD.read_text(encoding="utf-8")


def _songs():
    if not PRESETS.exists():
        _broken("presets.json is tracked and absent")
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
    _broken("build/fidelity.json exists but no row carries `seconds`: the "
            "artefact's shape changed under this guard")


def _needs_window(rows, taken_at=FIGURE_WINDOW):
    got = _window(rows)
    if got != taken_at:
        pytest.skip(
            f"artefact is -t {got} and this CLAUDE.md figure was taken at "
            f"-t {taken_at}: comparing them would compare two different "
            f"quantities, not find a stale one. Regenerate the artefact at "
            f"-t {taken_at}, or re-grade the figure at -t {got} and move "
            f"FIGURE_WINDOW.")


# A QUOTED SENTENCE IS NOT A LINE. Every check in this file asserts that a
# quoted phrase is present in prose, and prose wraps: the moment someone
# re-flows a paragraph, a phrase that was on one line is on two, and a bare
# `f in text` reads 0 for a sentence that is right there. That is CLAUDE.md's
# own "line-based search finds nothing for a quotation that wraps across a
# newline" -- and this guard hit it twice on one afternoon at v0.5.481-482:
# a retraction guard asserted `"applied to the record" in source` against a
# comment wrapped as `is applied to the` / `# record unconditionally`, and
# the corrected Kings of the Beach figure below wrapped across a line and
# failed until the phrase was hand-placed on one line (commit 760f401).
# So both sides are normalised before matching: line-leading comment and
# blockquote markers go (`#`, `//`, `>` -- the retraction case lives in a
# Python comment, the figure case in Markdown), and every whitespace run,
# newlines included, collapses to one space. Nothing else is touched --
# `*` and `-` are NOT stripped as list markers, because `**` is how every
# bold figure in the file begins and a stripped asterisk would break it.
_LINE_MARKERS = re.compile(r"^[ \t]*(?:#+|//|>)+[ \t]?", re.MULTILINE)
_WHITESPACE = re.compile(r"\s+")


def _normalise(text):
    """Strip line-leading comment/blockquote markers and collapse whitespace."""
    return _WHITESPACE.sub(" ", _LINE_MARKERS.sub("", text)).strip()


def _says(text, *fragments, where="docs/LESSONS.md"):
    """Assert the prose contains each fragment, quoting what to fix if not.

    Matches on the NORMALISED text and fragment, so a phrase that wraps
    across a line, or across a comment marker, is still found.
    """
    norm = _normalise(text)
    for f in fragments:
        assert _normalise(f) in norm, (
            f"{where} no longer says {f!r} -- either the figure moved "
            f"and the file needs correcting, or the wording changed and this "
            f"test needs the new wording")


# A PRESENCE GUARD MUST ASSERT AGAINST THE SLICE, NOT THE FILE. `_says` on
# the whole file passes as long as the words are ANYWHERE in it, and this
# repo's grading rule guarantees they are somewhere else too: a corrected
# figure is required to quote the wording it corrects, and a lesson about a
# duplicated figure has to name the figure to make its point. Measured at
# 5a2fa2d (docs/LESSONS.md, "A presence guard must assert against the slice,
# not the file"): three guarded figures each occurred twice in their file,
# so deleting the guarded line left the guard green -- `49 of the 89 preset
# songs` sat in both the rate bullet and the section that documents the
# duplication; Kings of the Beach's `wave`/`gate` pair sat in the STALE
# entry and in the 180 s re-take that retracts it; `no-calibration` sat in
# approvals.py's cause table and in the sentence retracting the
# calibration-only wording. So every figure caller below slices FIRST --
# `_item_from` to the markdown list item the figure lives in, `_section` to
# a heading's body -- and asserts against the slice. The fix was written in
# a worktree at 5a2fa2d and never reached master; `_item_from` in this file
# is what says it has.
_LIST_MARKER = re.compile(r"^([ \t]*)(?:[*+-]|\d+[.)])[ \t]+")
_HEADING = re.compile(r"^(#+)[ \t]+(.*?)[ \t]*$")


def _anchor_re(anchor):
    """`anchor` with every whitespace run matching any whitespace run, so an
    anchor sentence that wraps across a line in the file is still found --
    the wrapped-quotation rule `_says` obeys, applied to the slice too."""
    return re.compile(r"\s+".join(re.escape(w) for w in anchor.split()))


def _indent(line):
    return len(line) - len(line.lstrip(" \t"))


def _item_from(text, anchor):
    """The slice of `text` from `anchor` to the end of its markdown list item.

    `anchor` must occur EXACTLY ONCE (whitespace-insensitively): an anchor
    found twice would silently pick one of two items, which is the defect
    this helper exists to remove, one level up. The item is the nearest
    list-marker line at or above the anchor, not crossing a blank line; it
    ends at the first later line that is blank, a heading, or indented no
    deeper than the marker (the next sibling item, or the paragraph that
    follows the list). An anchor in a plain paragraph slices to the
    paragraph's end. Anchor mid-item and the slice starts mid-item: the
    figure has to be AFTER the anchor.
    """
    hits = list(_anchor_re(anchor).finditer(text))
    if len(hits) != 1:
        _broken(f"anchor {anchor!r} occurs {len(hits)} times, not once, so "
                f"the slice it names is ambiguous")
    start = hits[0].start()
    lines = text.splitlines(keepends=True)
    offsets, pos = [], 0
    for ln in lines:
        offsets.append(pos)
        pos += len(ln)
    at = max(i for i, o in enumerate(offsets) if o <= start)
    marker_indent = _indent(lines[at])
    for i in range(at, -1, -1):
        ln = lines[i]
        if not ln.strip() or _HEADING.match(ln):
            break
        m = _LIST_MARKER.match(ln)
        if m:
            marker_indent = len(m.group(1))
            break
    end = len(text)
    for j in range(at + 1, len(lines)):
        ln = lines[j]
        if not ln.strip() or _HEADING.match(ln) or _indent(ln) <= marker_indent:
            end = offsets[j]
            break
    return text[start:end]


def _section(text, heading):
    """The body of the markdown section titled `heading`, up to the next
    heading of the same or a higher level. `heading` must occur once."""
    hits = [(i, len(m.group(1))) for i, ln in enumerate(text.splitlines())
            for m in [_HEADING.match(ln)]
            if m and m.group(2) == heading]
    if len(hits) != 1:
        _broken(f"heading {heading!r} occurs {len(hits)} times, not once")
    lines = text.splitlines(keepends=True)
    at, level = hits[0]
    end = len(lines)
    for j in range(at + 1, len(lines)):
        m = _HEADING.match(lines[j])
        if m and len(m.group(1)) <= level:
            end = j
            break
    return "".join(lines[at:end])


# The anchors, named once so a moved paragraph is fixed in one place. Each
# is a sentence of the item that carries the figure and none contains the
# figure it guards (an attribution key must not contain the quantity being
# attributed): an anchor that quoted the number would find the number.
POPULATION_ITEM = "RE-GRADED AGAIN AT v0.5.459, AND BOTH HAVE MOVED"
RATE_ITEM = "every table Goattracker applies it with steps per"
CORPUS_ITEM = ("the replacement needs TWO numbers because the two artefacts "
               "answer DIFFERENT QUESTIONS")
DRIFT_ITEM = "The drift split at 180 s is"
SKATE_ITEM = "Skate or Die intro at 180 s is"
KOTB_ITEM = "RE-GRADED AT v0.5.481: the pair"


# ------------------------------------------------------------ presets.json

def _wave_program_fragment(songs):
    wp = [k for k, o in songs.items() if o.get("wave_program")]
    multi = sum(1 for k in wp if (songs[k].get("multiplier") or 1) > 1)
    return f"**{multi} multispeed / {len(wp) - multi} single-speed**"


def _regrid_fragment(songs):
    return f"**{sum(1 for o in songs.values() if o.get('regrid'))} adoptions**"


def _multiplier_fragments(songs):
    m = collections.Counter((o.get("multiplier") or 1) for o in songs.values())
    above = sum(v for k, v in m.items() if k > 1)
    return (f"{above} of the {len(songs)} preset songs",
            f"{m[2]} at `-S2`, {m[2] + m[3]} at")


def test_the_wave_program_split_is_what_presets_says():
    songs, text = _songs(), _text()
    _says(_item_from(text, POPULATION_ITEM), _wave_program_fragment(songs),
          where=f"docs/LESSONS.md's {POPULATION_ITEM!r} item")


def test_the_regrid_adoption_count_is_what_presets_says():
    songs, text = _songs(), _text()
    _says(_item_from(text, POPULATION_ITEM), _regrid_fragment(songs),
          where=f"docs/LESSONS.md's {POPULATION_ITEM!r} item")


def test_the_multiplier_population_is_what_presets_says():
    """The measured duplicate: `49 of the 89 preset songs` is ALSO in the
    LESSONS section that documents its own duplication, so the whole-file
    check passed with the rate bullet deleted. Sliced to the bullet."""
    songs, text = _songs(), _text()
    _says(_item_from(text, RATE_ITEM), *_multiplier_fragments(songs),
          where=f"docs/LESSONS.md's {RATE_ITEM!r} bullet")


# ------------------------------------------- the guard survives a re-wrap

def test_says_finds_a_sentence_wrapped_across_a_comment_marker():
    """The measured instance: a retraction guard asserted the quoted sentence
    was present in source and FAILED against a correct retraction, because
    the comment wrapped it as `is applied to the` / `# record unconditionally`.
    The bare check reads 0; the normalised one finds it."""
    src = ("    # ... so the census entry is applied to the\n"
           "    # record unconditionally, where every other cause is gated.\n")
    assert "applied to the record" not in src, "the bare check should still fail"
    _says(src, "applied to the record unconditionally", where="src")
    # The FRAGMENT may wrap too -- a test that quotes a file's line break
    # verbatim (this file did, at the Skate_or_Die figure) must not break
    # when the file re-flows, so both sides are normalised, not one.
    _says(src, "applied to the\n    # record", where="src")
    # ...and normalising must not make an ABSENT sentence present.
    with pytest.raises(AssertionError):
        _says(src, "applied to the pattern unconditionally", where="src")


def test_the_population_figures_survive_a_rewrap_of_the_file():
    """Re-flow docs/LESSONS.md as aggressively as any editor could -- every
    space becomes a line break plus indent, every line a blockquote -- and
    each figure fragment this file checks must still be found. A fragment
    that only matched because the file happened to wrap elsewhere is the
    exposure this test closes; the KotB figure was that at v0.5.482."""
    songs, text = _songs(), _text()
    # Slice first, exactly as the guards do, then re-flow the SLICE: the
    # item boundaries are what `_item_from` reads and a rewrap that
    # destroyed them would be testing a file no editor produces.
    regions = [(_item_from(text, POPULATION_ITEM),
                [_wave_program_fragment(songs), _regrid_fragment(songs)]),
               (_item_from(text, RATE_ITEM), list(_multiplier_fragments(songs)))]
    for region, frags in regions:
        rewrapped = "> " + region.replace(" ", "\n>    ")
        for f in frags:
            assert f not in rewrapped, (
                f"{f!r} survived the rewrap verbatim, so this test proves "
                f"nothing about it -- the fragment contains no space to break on")
        _says(rewrapped, *frags)


# --------------------------------------------- the guard asserts on the slice

_TWO_ITEMS = (
    "## Figures\n"
    "\n"
    "- **STALE -- the split is 84.8% / 85.2%** at v0.5.454, and this\n"
    "  entry is kept saying so.\n"
    "- **RE-TAKEN at 180 s: the split\n"
    "  is 94.4% / 85.2%** after the pulse writer reached it; the 84.8%\n"
    "  above is HISTORY.\n"
    "  * a nested item, deeper than its parent, stays inside it\n"
    "- **Another item** that also says 94.4% / 85.2% by accident.\n"
    "And a paragraph after the list that says 94.4% / 85.2% too.\n"
    "\n"
    "## Next\n"
    "\n"
    "Nothing here.\n"
)


def test_item_from_slices_the_anchors_item_and_nothing_past_it():
    """The synthetic shape of all three measured instances: the figure a
    guard wants is in one item, and a copy of the same words is in another
    item, in the paragraph after the list, and in a section further down.
    The slice from the anchor to the end of its item sees exactly one."""
    item = _item_from(_TWO_ITEMS, "RE-TAKEN at 180 s: the split is")
    assert item.startswith("RE-TAKEN at 180 s: the split\n  is 94.4%")
    assert item.endswith("stays inside it\n"), item
    assert "Another item" not in item and "paragraph after" not in item
    # An anchor sentence that wraps across a line is still one anchor.
    assert "\n" in "RE-TAKEN at 180 s: the split\n  is"
    _says(item, "94.4% / 85.2%", where="item")
    # The guard is on the SLICE: delete the guarded figure from this item
    # and the copies elsewhere in the file do not rescue it.
    sabotaged = _TWO_ITEMS.replace("  is 94.4% / 85.2%** after", "  is xx** after")
    assert "94.4% / 85.2%" in sabotaged, "the other copies must survive"
    with pytest.raises(AssertionError):
        _says(_item_from(sabotaged, "RE-TAKEN at 180 s: the split is"),
              "94.4% / 85.2%", where="item")
    # A mid-item anchor starts mid-item: what is before it is not seen.
    tail = _item_from(_TWO_ITEMS, "after the pulse writer reached it")
    assert tail.startswith("after the pulse") and "RE-TAKEN" not in tail
    # A plain-paragraph anchor slices to the paragraph's end.
    para = _item_from(_TWO_ITEMS, "And a paragraph after the list")
    assert para == "And a paragraph after the list that says 94.4% / 85.2% too.\n"


def test_item_from_and_section_refuse_an_ambiguous_anchor():
    """Two matches would silently pick one item -- the whole-file defect
    one level up -- so the helpers fail loudly instead of choosing."""
    with pytest.raises(pytest.fail.Exception, match="occurs 2 times"):
        _item_from(_TWO_ITEMS, "85.2%**")
    with pytest.raises(pytest.fail.Exception, match="occurs 0 times"):
        _item_from(_TWO_ITEMS, "not in the text at all")
    with pytest.raises(pytest.fail.Exception, match="occurs 0 times"):
        _section(_TWO_ITEMS, "Figure")            # exact title, not a prefix


def test_section_runs_to_the_next_heading_of_the_same_or_higher_level():
    body = _section(_TWO_ITEMS, "Figures")
    assert body.startswith("## Figures\n") and body.endswith("too.\n\n")
    assert "Nothing here" not in body
    nested = "# Top\n\n## A\n\ntext a\n\n### A.1\n\ntext a1\n\n## B\n\ntext b\n"
    assert _section(nested, "A") == "## A\n\ntext a\n\n### A.1\n\ntext a1\n\n"
    assert _section(nested, "A.1") == "### A.1\n\ntext a1\n\n"
    assert _section(nested, "Top") == nested


def test_every_lessons_figure_guard_asserts_on_a_slice():
    """Read this module's own source: no test may call `_says(text, ...)`
    or `_says(claude_md, ...)` on a whole file again. The three measured
    instances each passed a whole-file check with their guarded line
    deleted; a new caller that reaches for the file instead of a slice
    reopens exactly that, silently, and this is the check that says so."""
    import inspect
    import sys

    src = inspect.getsource(sys.modules[__name__])
    body = src[:src.index("def test_every_lessons_figure_guard_asserts_on_a_slice")]
    # `(?<!def )`: the helper's own signature is `_says(text, ...)`, and a
    # scan that could not tell it from a call would be this file's lesson.
    whole = re.findall(r"(?<!def )_says\((?:text|claude_md|_text\(\))\b", body)
    assert not whole, (
        f"{len(whole)} `_says` call(s) assert against a whole file; slice "
        f"with _item_from or _section first")
    assert "_item_from(" in body and "_section(" in body


# ------------------------------------------------------- build/fidelity.json

def test_the_drift_split_is_what_the_artefact_says():
    rows, text = _rows(), _text()
    _needs_window(rows)
    have = [r for r in rows
            if r.get("status") == "measured" and r.get("drift_per_1000") is not None]
    zero = sum(1 for r in have if abs(r["drift_per_1000"]) < 1e-9)
    _says(_item_from(text, DRIFT_ITEM),
          f"**{zero} zero / {len(have) - zero} drifting of {len(have)} rows",
          where=f"docs/LESSONS.md's {DRIFT_ITEM!r} item")


def test_skate_or_die_intros_attack_counts_are_what_the_artefact_says():
    rows, text = _rows(), _text()
    _needs_window(rows)
    r = next((r for r in rows if r["file"] == "Skate_or_Die_intro.sid"), None)
    if r is None or r.get("our_attacks") is None:
        _broken("Skate_or_Die_intro has no attack row in build/fidelity.json, "
                "so the figure LESSONS.md carries for it is unchecked")
    # This fragment used to carry the file's line break (`original's\n    N`)
    # verbatim -- a wrapped quotation baked into the test, which passed only
    # while LESSONS.md wrapped at exactly that word. `_says` normalises now.
    _says(_item_from(text, SKATE_ITEM),
          f"{r['our_attacks']} attacks against the original's {r['orig_attacks']}",
          where=f"docs/LESSONS.md's {SKATE_ITEM!r} item")


def test_kings_of_the_beach_ingame_reads_what_the_artefact_says():
    rows, text = _rows(), _text()
    _needs_window(rows)
    r = next((r for r in rows if r["file"] == "Kings_of_the_Beach_ingame.sid"), None)
    if r is None or r.get("wave") is None:
        _broken("Kings_of_the_Beach_ingame has no wave row in "
                "build/fidelity.json, so the figure LESSONS.md carries for it "
                "is unchecked")
    # The structural duplicate: the STALE v0.5.454 entry and the 180 s
    # re-take that quotes it to retract it both carry a `wave` / `gate`
    # pair, and the retraction is REQUIRED to quote the wording it
    # retracts. Sliced from the v0.5.481 re-grade to the end of its item,
    # so only the live figure can satisfy it.
    _says(_item_from(text, KOTB_ITEM),
          f"`wave` {r['wave'] * 100:.1f}% / `gate` {r['gate'] * 100:.1f}%",
          where=f"docs/LESSONS.md's {KOTB_ITEM!r} item")


# ------------------------------- the two artefacts that answer different questions

def test_the_corpus_counts_name_both_option_sets():
    """95 tested / 89 on presets / 86 on defaults -- and the file must say which."""
    rows, text = _rows(), _text()
    if not SURVEY.exists():
        _broken("docs/SURVEY.md is tracked and absent")
    sur = SURVEY.read_text(encoding="utf-8")
    m = re.search(r"Converted: \*\*(\d+)\*\* of (\d+) in reach", sur)
    if not m:
        _broken("SURVEY.md header no longer matches `Converted: **N** of M in "
                "reach` -- the regex stopped matching, which is "
                "indistinguishable from the format changing under this test")
    on_defaults, in_reach = int(m.group(1)), int(m.group(2))
    measured = sum(1 for r in rows if r.get("status") == "measured")
    _says(_item_from(text, CORPUS_ITEM),
          f"**{measured} convert",
          f"**{on_defaults} convert on DEFAULT",
          f"leaving {in_reach} in reach",
          where=f"docs/LESSONS.md's {CORPUS_ITEM!r} item")


def _survey_not_converted():
    """The `Not converted` table of docs/SURVEY.md as {file: reason}.

    Read from the table itself, never from the header count, so the set is
    what is checked and the count is derived from it.
    """
    if not SURVEY.exists():
        _broken("docs/SURVEY.md is tracked and absent")
    sur = SURVEY.read_text(encoding="utf-8")
    m = re.search(r"^## Not converted \((\d+)\)\s*\n(.*?)(?=^## |\Z)",
                  sur, re.M | re.S)
    if not m:
        _broken("SURVEY.md no longer carries a `## Not converted (N)` section "
                "-- the regex stopped matching, which is indistinguishable "
                "from the format changing under this test")
    rows = {}
    for line in m.group(2).splitlines():
        cells = [c.strip() for c in line.strip().strip("|").split("|")]
        if len(cells) < 11 or not cells[0].startswith("`"):
            continue
        rows[cells[0].strip("`")] = cells[-1]
    if len(rows) != int(m.group(1)):
        _broken(f"SURVEY.md says `Not converted ({m.group(1)})` but its table "
                f"lists {len(rows)} files")
    return rows


def test_the_three_file_gap_is_the_presets_rescuing_the_survey_failures():
    """The 89-on-presets / 86-on-defaults pair is ONE figure with two halves,
    and the gap between them is a named set, not a count: every file the
    survey fails on defaults must (a) be a presets.json song, (b) be
    rescued by an option that defaults off and is NOT in the `always`
    block, so that a default run really does lack it, and (c) be named in
    docs/LESSONS.md beside the pair. `test_the_corpus_counts_name_both_
    option_sets` checks the two counts; this checks the set between them,
    because a count decays whenever an unrelated song moves and the set is
    what the claim is about (CLAUDE.md, "State the SET, not the count").
    """
    songs, text = _songs(), _text()
    doc = json.loads(PRESETS.read_text(encoding="utf-8"))
    failed = _survey_not_converted()
    assert failed, "SURVEY.md lists no default failure; the pair collapsed"
    not_in_presets = sorted(set(failed) - set(songs))
    assert not not_in_presets, (
        f"{not_in_presets} fail on defaults and have no preset either -- "
        f"the gap is no longer 'rescued by presets'")
    rescue = {"prune", "dedup", "max_rows"}
    for f, reason in failed.items():
        assert "TOO MANY NEW PATTERN" in reason, (
            f"{f} fails on defaults for {reason!r}, not the pattern limit "
            f"the LESSONS bullet attributes the whole gap to")
        opts = songs[f]
        used = {k for k in rescue
                if opts.get(k) and (k != "max_rows" or opts[k] != 94)}
        assert used, f"{f}'s preset carries none of {sorted(rescue)}"
        assert not (used & set(doc["always"])), (
            f"{f} is rescued by {sorted(used & set(doc['always']))}, which "
            f"is in the `always` block, so a default run would have it too")
    stems = sorted(f[:-len(".sid")] for f in failed)
    _says(_item_from(text, CORPUS_ITEM),
          f"leaving {len(songs)} in reach",
          "The three-file gap is **" + ", ".join(stems[:-1])
          + " and " + stems[-1] + "**"
          if len(stems) == 3 else
          "The three-file gap is **",
          where=f"docs/LESSONS.md's {CORPUS_ITEM!r} item")
    if len(stems) != 3:
        pytest.fail(f"the default failures are {stems}, {len(stems)} files; "
                    f"docs/LESSONS.md still says 'three-file gap'")


# --------------------------------------------------- grep-zero-on-a-quotation

def test_the_grep_zero_rule_cites_its_measured_instances():
    """CLAUDE.md's rule about a counter that cannot see its own container
    must carry its evidence in docs/LESSONS.md, not just an assertion."""
    claude_md = (ROOT / "CLAUDE.md").read_text(encoding="utf-8")
    _says(_section(claude_md, "Reading the players"),
          "evidence about the counter, not about the file",
          "grep for a retracted sentence",
          where="CLAUDE.md section Reading the players")
    _says(_section(claude_md, "Grading measured figures"),
          "normalise both sides before matching",
          where="CLAUDE.md section Grading measured figures")
    grep_zero = "A grep returning 0 is evidence about the counter, not about the file"
    _says(_section(_text(), grep_zero),
          "survey.py:669-670",
          "fidelity.py:2780-2781",
          "H2G-CONVERSION-METHOD.md:4511",
          "NAMING ARTEFACTS",
          "a grep for a retracted sentence hits the retraction itself",
          where=f"docs/LESSONS.md section {grep_zero}")


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


def test_every_quiet_skip_names_a_gitignored_artefact():
    """Read this module's own source: every `pytest.skip(` left in it must be
    the legitimately-absent kind. The permitted reasons are listed by the
    substring the skip message carries, not by line number, so re-flowing
    the file cannot silently un-cover a site -- and a NEW skip has to be
    added to this list with its justification, which is the moment someone
    asks whether it is the quiet kind at all.
    """
    import inspect
    import sys

    src = inspect.getsource(sys.modules[__name__])
    # Everything from the marker on is this test's own body and docstring.
    body = src[:src.index("def test_every_quiet_skip_names_a_gitignored_artefact")]
    sites = re.findall(r'pytest\.skip\(\s*(f?"[^"]*")', body)
    assert sites, "no pytest.skip call found in this module: the scan itself broke"
    permitted = (
        "build/fidelity.json absent -- it is gitignored",   # _rows: clean clone
        "artefact is -t ",                                   # _needs_window: the
                                                             # loud guard covers it
    )
    unjustified = [x for x in sites if not any(p in x for p in permitted)]
    assert not unjustified, (
        f"quiet skip(s) whose reason is not a gitignored artefact: "
        f"{unjustified}. A tracked file that is absent, or a shape that "
        f"stopped matching, is the check breaking and must go through "
        f"_broken() instead")
