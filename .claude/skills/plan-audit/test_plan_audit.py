"""Tests for plan_audit's three classifiers -- check_g ("verify needs a
person but mode is not requires-user"), check_h (a verify promising to
create an artefact that already exists) and check_i (a prerequisite stated
only in prose, with no depends_on edge).

THIS IS THE PERMANENT LOCATION: next to the module it tests, following
this repo's test-beside-source convention -- see plan_audit.py's own
check B. Run it with:

    python -m pytest .claude/skills/plan-audit/test_plan_audit.py -q

from the repo root; it puts .claude/skills/plan-audit on sys.path below.

The header here USED to say "Tests for plan_audit.check_g" and "This copy
lives in scratch", naming a `C:/t/plan-audit-check-g/` path, because the
task that wrote it was granted rw: on plan_audit.py alone. Both facts
stopped being true when a later task was granted this file and added two
more checks to it, and the prose survived the change -- the third
stale-docstring find of one session. A file header is a claim about the
file that nothing in the suite reads.
"""
import copy
import importlib
import pathlib
import sys

REPO = pathlib.Path(r"C:/Users/mit/claude/h2g")
SKILL_DIR = REPO / ".claude/skills/plan-audit"
sys.path.insert(0, str(SKILL_DIR))
import plan_audit  # noqa: E402


def base_task(**kw):
    t = {
        "id": "t",
        "mode": "main",
        "lane": "serial",
        "touches": ["rw:python/h2g/foo.py"],
        "depends_on": [],
        "verify": "",
    }
    t.update(kw)
    return t


# ---------------------------------------------------------------------
# 0 findings on the real, current plan (the invariant the verify names).
# ---------------------------------------------------------------------
def test_real_plan_has_zero_findings():
    plan = importlib.import_module("json").loads(
        (REPO / ".claude/tasks/whattask.json").read_text(encoding="utf-8"))
    findings = plan_audit.check_g(plan["tasks"])
    assert findings == [], findings


# ---------------------------------------------------------------------
# (a) the ILV scope sentence is a PRIORITY statement, not a done-condition.
# ---------------------------------------------------------------------
def test_ilv_scope_sentence_is_exempt():
    t = base_task(
        id="ilv-scope-task",
        verify="The user has set these to LOW PRIORITY behind the 83 "
               "Rob_Hubbard files, so do not chase this until they clear.")
    assert plan_audit.check_g([t]) == []


# ---------------------------------------------------------------------
# (b) build/listen is a PATH -- "listen" there is a directory, not a verb.
# ---------------------------------------------------------------------
def test_build_listen_path_is_exempt():
    t = base_task(
        id="path-task",
        verify="Every tune in build/listen renders at the same window, "
               "checked with wave.open().")
    assert plan_audit.check_g([t]) == []


# ---------------------------------------------------------------------
# (c) a task about plan-audit itself necessarily quotes this vocabulary.
# ---------------------------------------------------------------------
def test_selfref_plan_audit_task_is_exempt():
    t = base_task(
        id="selfref-task",
        touches=["rw:.claude/skills/plan-audit/plan_audit.py"],
        verify="Add a check for a task whose verify's done-condition "
               "needs a person, not mode requires-user.")
    assert plan_audit.check_g([t]) == []


# ---------------------------------------------------------------------
# (d) "requires-user" is a MODE TOKEN, not the decomposed word "user".
# ---------------------------------------------------------------------
def test_mode_token_reference_is_exempt():
    t = base_task(
        id="mode-token-task",
        verify="Every open main-mode task's verify is reachable once "
               "requires-user tasks are excluded from the count.")
    assert plan_audit.check_g([t]) == []


# ---------------------------------------------------------------------
# The positive case: a genuine unsatisfiable done-condition on a task that
# is NOT mode requires-user IS a real defect and must be reported.
# ---------------------------------------------------------------------
def test_genuine_unsatisfiable_condition_is_reported():
    t = base_task(
        id="mislabeled-task",
        mode="main",
        verify="DONE means a person has listened to the render and "
               "confirmed it sounds right -- no script can check this.")
    findings = plan_audit.check_g([t])
    assert [f[0] for f in findings] == ["mislabeled-task"]


def test_same_condition_under_requires_user_mode_is_not_reported():
    t = base_task(
        id="correctly-labeled-task",
        mode="requires-user",
        verify="DONE means a person has listened to the render and "
               "confirmed it sounds right -- no script can check this.")
    assert plan_audit.check_g([t]) == []


# =======================================================================
# check_h -- "verify PROMISES to create an artefact that already exists"
# =======================================================================

# ---------------------------------------------------------------------
# 0 findings on the real, current plan (the invariant the verify names).
# ---------------------------------------------------------------------
def test_check_h_real_plan_has_zero_findings():
    plan = importlib.import_module("json").loads(
        (REPO / ".claude/tasks/whattask.json").read_text(encoding="utf-8"))
    findings = plan_audit.check_h(plan["tasks"])
    assert findings == [], findings


# ---------------------------------------------------------------------
# A GRANTS-CORRECTED bookkeeping clause negating a write ("...which this
# task only READS") is administrative narration, not a creation promise.
# This is the exact ab-7/ab-9 shape.
# ---------------------------------------------------------------------
def test_grants_corrected_negation_is_exempt():
    t = base_task(
        id="grants-negation-task",
        verify="RE-READ that document first.  || GRANTS CORRECTED at "
               "fd286a5 from the design document's own **Files:** block; "
               "the previous grant named python/h2g/convert.py, which "
               "this task only READS. || GRADED at d3775b4: fd286a5 is "
               "5 commit(s) behind.")
    assert plan_audit.check_h([t]) == []


# ---------------------------------------------------------------------
# Prose ABOUT a path, inside the same GRANTS-CORRECTED clause, is also
# exempt -- it is not the task's own deliverable.
# ---------------------------------------------------------------------
def test_grants_corrected_prose_about_a_path_is_exempt():
    t = base_task(
        id="grants-prose-task",
        verify="RE-READ that document first.  || GRANTS CORRECTED at "
               "fd286a5 from the design document's own **Files:** block; "
               "the previous grant named python/h2g/convert.py, which "
               "this task only READS. NOTE the design document writes "
               "`docs/README.md` WITHOUT its real prefix.")
    assert plan_audit.check_h([t]) == []


# ---------------------------------------------------------------------
# A task about plan-audit itself necessarily quotes this vocabulary.
# ---------------------------------------------------------------------
def test_check_h_selfref_plan_audit_task_is_exempt():
    t = base_task(
        id="h-selfref-task",
        touches=["rw:.claude/skills/plan-audit/plan_audit.py"],
        verify="Add a check for a verify that creates python/h2g/convert.py "
               "which already exists.")
    assert plan_audit.check_h([t]) == []


# ---------------------------------------------------------------------
# The positive case: a genuine promise to create a path that already
# exists, OUTSIDE any GRANTS-clause, IS a real defect and must be reported.
# ---------------------------------------------------------------------
def test_check_h_genuine_spent_promise_is_reported():
    t = base_task(
        id="spent-promise-task",
        verify="DONE means this task creates python/h2g/convert.py with "
               "the new option wired through.")
    findings = plan_audit.check_h([t])
    assert [f[0] for f in findings] == ["spent-promise-task"]


def test_check_h_promise_to_create_absent_path_is_not_reported():
    t = base_task(
        id="genuine-create-task",
        verify="DONE means this task creates python/h2g/does_not_exist.py "
               "with the new option wired through.")
    assert plan_audit.check_h([t]) == []


# =======================================================================
# check_i -- "a PREREQUISITE stated only in prose" (no depends_on edge)
# =======================================================================

# ---------------------------------------------------------------------
# 0 findings on the real, current plan (the invariant the verify names --
# ab-9's GATE case is now clean because its depends_on edge was added).
# ---------------------------------------------------------------------
def test_check_i_real_plan_has_zero_findings():
    plan = importlib.import_module("json").loads(
        (REPO / ".claude/tasks/whattask.json").read_text(encoding="utf-8"))
    findings = plan_audit.check_i(plan["tasks"], plan.get("closed") or [])
    assert findings == [], findings


# ---------------------------------------------------------------------
# Prerequisite-shaped prose naming NO id at all can never become an edge --
# this is the ILV/interleaved-classic "ahead of an RH task" shape, pasted
# into over a dozen tasks in the live plan.
# ---------------------------------------------------------------------
def test_prerequisite_prose_naming_no_id_is_exempt():
    t = base_task(
        id="ilv-prereq-task",
        verify="The user has set these to LOW PRIORITY. Do not start this "
               "ahead of an RH task; re-confirm before trusting this line.")
    assert plan_audit.check_i([t], []) == []


# ---------------------------------------------------------------------
# A named token that is NOT a real plan id (open or closed) cannot become
# an edge either, however prerequisite-shaped the prose around it reads.
# ---------------------------------------------------------------------
def test_prerequisite_prose_naming_unknown_id_is_exempt():
    t = base_task(
        id="unknown-id-task",
        verify="This must wait on `some-task-that-was-never-planned` "
               "finishing first.")
    assert plan_audit.check_i([t], []) == []


# ---------------------------------------------------------------------
# A real id that IS already a depends_on edge is not "only in prose".
# ---------------------------------------------------------------------
def test_prerequisite_with_existing_edge_is_not_reported():
    other = base_task(id="other-task")
    t = base_task(
        id="edged-task",
        depends_on=["other-task"],
        verify="This must wait on `other-task` finishing first.")
    assert plan_audit.check_i([t, other], []) == []


# ---------------------------------------------------------------------
# The positive case: ab-9's actual shape before its edge was added -- a
# GATE naming a real, open plan id, with no depends_on edge -- IS a real
# defect and must be reported.
# ---------------------------------------------------------------------
def test_check_i_genuine_missing_edge_is_reported():
    other = base_task(id="regrid-could-be-searchable-from-repeated-attack")
    t = base_task(
        id="ab-9-drift-as-acceptance-term",
        verify="GATE (design document line 2415): "
               "`regrid-could-be-searchable-from-repeated-attack` must "
               "read outcome done in runs.jsonl before a line is written.")
    findings = plan_audit.check_i([t, other], [])
    assert findings == [
        ("ab-9-drift-as-acceptance-term",
         "regrid-could-be-searchable-from-repeated-attack")]


# ---------------------------------------------------------------------
# The same GATE naming a real id that is now CLOSED (not open) is still
# reported -- closed ids are valid depends_on targets too (check E's
# model), so the missing edge is still a real gap.
# ---------------------------------------------------------------------
def test_check_i_missing_edge_to_a_closed_id_is_reported():
    t = base_task(
        id="closed-gate-task",
        verify="GATE: `some-closed-task` must read outcome done in "
               "runs.jsonl before a line is written.")
    closed = [{"id": "some-closed-task", "closed_by": "abc1234"}]
    findings = plan_audit.check_i([t], closed)
    assert findings == [("closed-gate-task", "some-closed-task")]


if __name__ == "__main__":
    import traceback
    tests = [v for k, v in list(globals().items()) if k.startswith("test_")]
    failed = 0
    for fn in tests:
        try:
            fn()
            print("PASS", fn.__name__)
        except AssertionError:
            failed += 1
            print("FAIL", fn.__name__)
            traceback.print_exc()
    print("\n%d/%d passed, %d failed" % (len(tests) - failed, len(tests), failed))
    sys.exit(1 if failed else 0)
