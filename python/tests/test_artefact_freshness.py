"""`artefact_freshness.check_freshness` is the whole staleness rule, and it
must not need git to be exercised: every case here hands it plain path lists.

The rule under test (CLAUDE.md, and the docstring at the top of the module):
EMISSION-CHANGING commits under python/h2g/ make the artefact stale; a pure
`__init__.py` version bump does not; an uncommitted change under python/h2g/
right now makes it stale even with no new commits at all; and nothing outside
python/h2g/ counts, however large.
"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from artefact_freshness import (EXACT_GUARANTEE_NOTE, OVERRIDE_NOTE,
                                 UPPER_BOUND_NOTE, artefact_commit_from_rows,
                                 check_freshness, parse_label)


# --- the measured real-world case this task exists for -------------------

def test_665939c_case_is_not_stale():
    """At 665939c, six commits separate a hypothetical label from HEAD, and
    the only python/h2g/ change in that range is __init__.py's version
    string. CLAUDE.md is explicit this must read NOT STALE."""
    changed = [
        "python/h2g/__init__.py",
        "docs/LESSONS.md",
        "CLAUDE.md",
        ".claude/tasks/whattask.json",
    ]
    result = check_freshness(changed, dirty_files=[])
    assert result.stale is False
    assert result.version_only_changed == ["python/h2g/__init__.py"]
    assert result.emission_changed == []


def test_current_head_state_is_not_stale():
    """The actual state measured today: only __init__.py moved under
    python/h2g/ between the artefact's commit (20bc88d) and HEAD, and the
    working tree is clean there."""
    changed = ["python/h2g/__init__.py"]
    result = check_freshness(changed, dirty_files=[])
    assert result.stale is False


# --- emission-changing commit ---------------------------------------------

def test_emission_changing_commit_is_stale():
    changed = ["python/h2g/patterns.py", "python/h2g/__init__.py"]
    result = check_freshness(changed, dirty_files=[])
    assert result.stale is True
    assert result.emission_changed == ["python/h2g/patterns.py"]


def test_no_h2g_changes_at_all_is_not_stale():
    changed = ["docs/LESSONS.md", "python/fidelity.py"]
    result = check_freshness(changed, dirty_files=[])
    assert result.stale is False
    assert result.emission_changed == []
    assert result.version_only_changed == []


# --- dirty working tree -----------------------------------------------

def test_dirty_emitter_file_is_stale_even_with_no_new_commits():
    result = check_freshness(changed_files=[], dirty_files=["python/h2g/goatwriter.py"])
    assert result.stale is True
    assert result.dirty_emitter_files == ["python/h2g/goatwriter.py"]


def test_dirty_file_outside_h2g_does_not_make_it_stale():
    result = check_freshness(changed_files=[], dirty_files=["docs/LESSONS.md", "build/fidelity.json"])
    assert result.stale is False
    assert result.dirty_emitter_files == []


def test_dirty_init_py_alone_does_not_make_it_stale():
    """Dirty __init__.py is still just the version stamp -- consistent with
    the committed-change rule (a version bump is not emission-changing) and
    with the pre-existing regen guard (.claude/hooks/artefact_guard.py),
    which excludes __init__.py from its own converter-dirty check."""
    result = check_freshness(changed_files=[], dirty_files=["python/h2g/__init__.py"])
    assert result.stale is False
    assert result.dirty_emitter_files == []


# --- combined ---------------------------------------------------------

def test_both_stale_reasons_reported_together():
    result = check_freshness(
        changed_files=["python/h2g/tracks.py"],
        dirty_files=["python/h2g/convert.py"],
    )
    assert result.stale is True
    assert result.emission_changed == ["python/h2g/tracks.py"]
    assert result.dirty_emitter_files == ["python/h2g/convert.py"]


# --- label parsing ------------------------------------------------------

def test_parse_label_plain():
    assert parse_label("20bc88d") == ("20bc88d", False)


def test_parse_label_dirty():
    assert parse_label("665939c-dirty") == ("665939c", True)


def test_artefact_commit_from_rows_single_label():
    rows = [{"label": "20bc88d"}, {"label": "20bc88d"}]
    assert artefact_commit_from_rows(rows) == ("20bc88d", False)


def test_artefact_commit_from_rows_disagreeing_labels_raises():
    rows = [{"label": "20bc88d"}, {"label": "aaaaaaa"}]
    try:
        artefact_commit_from_rows(rows)
        assert False, "expected ValueError"
    except ValueError:
        pass


def test_artefact_commit_from_rows_no_label_raises():
    try:
        artefact_commit_from_rows([{"file": "x.sid"}])
        assert False, "expected ValueError"
    except ValueError:
        pass


# --- the asymmetry: STALE is an upper bound, NOT STALE is exact ----------
#
# Measured at c2cb76a: a docstring-only edit to python/h2g/tracks.py (36
# changed lines, 0 of them code) makes this tool report STALE, while
# tests/test_commando.py -- the byte-exact fixture -- still passes: no
# emitted byte moved. check_freshness keys on PATHS, which can only answer
# "did a file change", never "did an emitted byte change". So the two
# verdicts carry different certainty, and the tool must say so.

def test_docstring_only_edit_is_still_stale_but_flagged_as_upper_bound():
    """The correct, conservative behaviour: a path-only signal cannot tell a
    docstring edit from a code edit, so it stays STALE (this is NOT the bug
    to fix). What must change is that the verdict says it is only a bound."""
    changed = ["python/h2g/tracks.py"]  # docstring-only in the real case
    result = check_freshness(changed, dirty_files=[])
    assert result.stale is True
    assert result.emission_changed == ["python/h2g/tracks.py"]
    assert UPPER_BOUND_NOTE in result.reasons


def test_stale_reason_names_both_ways_to_confirm():
    """STALE must not print as a bare, equally-certain verdict: it must name
    the two things that CAN settle it -- the corpus byte-hash check and
    tests/test_commando.py, the byte-exact fixture."""
    result = check_freshness(["python/h2g/patterns.py"], dirty_files=[])
    assert result.stale is True
    joined = " ".join(result.reasons)
    assert "byte-hash" in joined
    assert "tests/test_commando.py" in joined
    assert "upper bound" in joined.lower() or "UPPER BOUND" in joined


def test_stale_reason_does_not_read_as_certain():
    """The STALE explanation must not claim it proved a byte changed."""
    result = check_freshness(["python/h2g/patterns.py"], dirty_files=[])
    joined = " ".join(result.reasons)
    assert "does not prove" in joined


def test_not_stale_reason_is_exact_not_hedged():
    """NOT STALE is a real guarantee and must read as one -- not hedged with
    the same uncertainty language used for STALE."""
    result = check_freshness(["docs/LESSONS.md"], dirty_files=[])
    assert result.stale is False
    assert EXACT_GUARANTEE_NOTE in result.reasons
    joined = " ".join(result.reasons)
    assert "exact" in joined.lower()
    # NOT STALE's own certainty note must not be the STALE hedge language.
    assert UPPER_BOUND_NOTE not in result.reasons


def test_verdicts_carry_different_certainty_wording():
    """Direct check of the asymmetry: the STALE note and the NOT STALE note
    must be textually distinct, and neither verdict emits the other's note."""
    stale_result = check_freshness(["python/h2g/patterns.py"], dirty_files=[])
    fresh_result = check_freshness(["docs/LESSONS.md"], dirty_files=[])
    assert UPPER_BOUND_NOTE in stale_result.reasons
    assert UPPER_BOUND_NOTE not in fresh_result.reasons
    assert EXACT_GUARANTEE_NOTE in fresh_result.reasons
    assert EXACT_GUARANTEE_NOTE not in stale_result.reasons


# --- explicit, caller-driven override -------------------------------------

def test_confirmed_unchanged_downgrades_stale_to_not_stale():
    """The override exists for a caller who has ALREADY run the corpus
    byte-hash check or tests/test_commando.py and confirmed no byte moved."""
    result = check_freshness(
        ["python/h2g/tracks.py"], dirty_files=[], confirmed_unchanged=True)
    assert result.stale is False
    assert result.overridden is True
    assert OVERRIDE_NOTE in result.reasons
    # emission_changed still records what actually moved -- the override
    # downgrades the verdict, it does not erase the evidence.
    assert result.emission_changed == ["python/h2g/tracks.py"]
    # EXACT_GUARANTEE_NOTE claims "no file under python/h2g/ changed" --
    # false here (a file DID change; that's what was overridden). Printing
    # it alongside OVERRIDE_NOTE would put a false claim next to a true one.
    assert EXACT_GUARANTEE_NOTE not in result.reasons


def test_confirmed_unchanged_is_inert_when_nothing_is_stale():
    """The override must not fabricate an override note when there was
    nothing to downgrade -- it only ever fires against an actual STALE."""
    result = check_freshness(
        ["docs/LESSONS.md"], dirty_files=[], confirmed_unchanged=True)
    assert result.stale is False
    assert result.overridden is False
    assert OVERRIDE_NOTE not in result.reasons


def test_confirmed_unchanged_defaults_to_off():
    """The override is opt-in: omitting it must not silently change the
    verdict for an ordinary emission-changing path."""
    result = check_freshness(["python/h2g/tracks.py"], dirty_files=[])
    assert result.stale is True
    assert result.overridden is False
