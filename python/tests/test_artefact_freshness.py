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

from artefact_freshness import (artefact_commit_from_rows, check_freshness,
                                 parse_label)


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
