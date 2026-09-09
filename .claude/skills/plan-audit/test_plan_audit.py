"""Tests for plan_audit.check_g -- the "verify needs a person but mode is
not requires-user" classifier.

INTENDED PERMANENT LOCATION: .claude/skills/plan-audit/test_plan_audit.py
(next to the module it tests, following this repo's test-beside-source
convention -- see plan_audit.py's own check B). This copy lives in scratch
because the dispatched task's `touches` grants rw: on
`.claude/skills/plan-audit/plan_audit.py` only, not on a sibling test file
in that directory or on anything under python/tests/ -- writing a new file
there is outside the granted paths. Run against the live module with:

    python -m pytest C:/t/plan-audit-check-g/test_plan_audit_check_g.py -q

after putting .claude/skills/plan-audit on sys.path (done below).
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
