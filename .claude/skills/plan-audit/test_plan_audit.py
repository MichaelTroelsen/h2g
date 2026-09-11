"""Tests for plan_audit's classifiers -- check_f (a verify quoting a sha
HEAD has moved past, with nothing to date it), check_g ("verify needs a
person but mode is not requires-user"), check_h (a verify promising to
create an artefact that already exists), check_i (a prerequisite stated
only in prose, with no depends_on edge) and check_j (a task that declares
itself a recurring obligation but appears in `closed` or reads a `done`
last runs.jsonl record).

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

# REPO used to be a hard-coded absolute path to the main checkout
# (C:/Users/mit/claude/h2g), which reads a DIFFERENT plan_audit.py and a
# DIFFERENT whattask.json than the one sitting next to this test file
# whenever the two diverge -- exactly what a git worktree does on
# purpose (CLAUDE.md's "Parallel work" section). A worktree agent editing
# plan_audit.py and this file together could never see its own change
# take effect under `python -m pytest`: the import silently picked up the
# main checkout's stale copy instead, and "real plan" tests silently
# graded the main checkout's plan against the main checkout's (possibly
# dirty) code -- not this worktree's. Resolve both from this file's own
# location instead, matching plan_audit.ROOT's own convention.
SKILL_DIR = pathlib.Path(__file__).resolve().parent
REPO = SKILL_DIR.parents[2]
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


# =======================================================================
# check_f -- "a verify quotes a sha HEAD has moved past, with nothing to
# date it". behind_of is injected so this is testable without a git
# subprocess or a real stale sha; it only needs to say "not 0/empty".
# =======================================================================
def _always_behind(sha):
    return "5"


def _never_behind(sha):
    return "0"


def _behind_except_grade_anchor(sha):
    # "GRADED at d3775b4:" names the sha the GRADING was taken AT, not a
    # sha being graded -- it is its own separate token and irrelevant to
    # these tests, which are about the GRADED sha (fd286a5) only.
    return "0" if sha == "d3775b4" else "5"


# ---------------------------------------------------------------------
# sha_occurrences is the slice: a sha inside a GRADED clause's own
# "<sha> is N commit(s) behind" body is graded at ITS OWN offset; the
# same digits appearing again, bare, elsewhere in the same verify are a
# SEPARATE occurrence and must classify False on their own.
# ---------------------------------------------------------------------
def test_sha_occurrences_classifies_graded_and_bare_copies_separately():
    v = ("GRADED at d3775b4: fd286a5 is 5 commit(s) behind. || re-check "
         "fd286a5 again before trusting the count above.")
    occ = plan_audit.sha_occurrences(v)
    assert [s for s, _ in occ].count("fd286a5") == 2
    # the sha named inside the GRADED clause's own body is graded True;
    # the bare re-quote later in the same string is graded False.
    fd_flags = [g for s, g in occ if s == "fd286a5"]
    assert fd_flags == [True, False], occ


# ---------------------------------------------------------------------
# The positive, historical bug: a set-of-sha-strings collapse would let
# the bare (ungraded) copy hide behind the graded one and report nothing.
# check_f must still report the pair as ungraded -- there is at least one
# occurrence nothing has dated.
# ---------------------------------------------------------------------
def test_check_f_bare_occurrence_beside_a_graded_one_is_still_reported():
    t = base_task(
        id="mixed-grading-task",
        verify="GRADED at d3775b4: fd286a5 is 5 commit(s) behind. || "
               "re-check fd286a5 again before trusting the count above.")
    ungraded, graded = plan_audit.check_f(
        [t], behind_of=_behind_except_grade_anchor)
    assert [(i, s) for i, s, b in ungraded] == [("mixed-grading-task",
                                                  "fd286a5")]
    assert graded == []


# ---------------------------------------------------------------------
# A sha graded on EVERY one of its occurrences is graded, not ungraded.
# ---------------------------------------------------------------------
def test_check_f_sha_graded_on_every_occurrence_is_graded():
    t = base_task(
        id="fully-graded-task",
        verify="GRADED at d3775b4: fd286a5 is 5 commit(s) behind, "
               "fd286a5 is 5 commit(s) behind.")
    ungraded, graded = plan_audit.check_f(
        [t], behind_of=_behind_except_grade_anchor)
    assert ungraded == []
    assert [(i, s) for i, s, b in graded] == [("fully-graded-task",
                                                "fd286a5")]


# ---------------------------------------------------------------------
# A sha nobody has moved past (behind_of returns "0") is not a finding at
# all, graded or ungraded.
# ---------------------------------------------------------------------
def test_check_f_sha_not_behind_head_is_not_reported():
    t = base_task(
        id="not-stale-task",
        verify="Compare against fd286a5 before adopting the change.")
    ungraded, graded = plan_audit.check_f([t], behind_of=_never_behind)
    assert ungraded == []
    assert graded == []


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


# =======================================================================
# check_j: a task that DECLARES ITSELF a recurring obligation must not
# appear in `closed`, and must not carry a `done` last runs.jsonl record.
# =======================================================================

# ---------------------------------------------------------------------
# check_j returns 0 findings on the real, current plan -- the invariant
# the verify names (checked against runs.jsonl too, not just whattask.json).
# ---------------------------------------------------------------------
def test_check_j_real_plan_has_zero_findings():
    plan = importlib.import_module("json").loads(
        (REPO / ".claude/tasks/whattask.json").read_text(encoding="utf-8"))
    runs_last = plan_audit.load_runs_last(REPO / ".claude/tasks/runs.jsonl")
    findings = plan_audit.check_j(
        plan["tasks"], plan.get("closed") or [], runs_last)
    assert findings == [], findings


# ---------------------------------------------------------------------
# A generic recurrence-vocabulary word ("recurring") alone is NOT enough:
# a sibling plan-audit task DISCUSSING the defect class, without an
# operational instruction to a runner about its own closure, is exempt --
# this is a-done-run-record-describes-one-commit-and-a-later-commit-can-
# expire-it's actual verify text.
# ---------------------------------------------------------------------
def test_discussing_recurrence_without_self_declaration_is_exempt():
    t = base_task(
        id="a-done-run-record-describes-one-commit-and-a-later-commit-"
           "can-expire-it",
        verify="A recurring obligation is not readable as permanently "
               "done. regenerate-fidelity-artefacts read done from "
               "v0.5.459 through two emission commits while its artefact "
               "was stale.")
    assert plan_audit.check_j_declared([t]) == []
    assert plan_audit.check_j([t], [], {}) == []


# ---------------------------------------------------------------------
# A closed entry whose title/reason merely say "recurring" -- without the
# operational phrase -- is exempt too: this is the real closed record for
# regenerate-fidelity-artefacts-is-a-recurring-obligation-modelled-as-a-
# one-shot-task, whose own job was retiring the one-shot mistake, not
# declaring recurrence for itself.
# ---------------------------------------------------------------------
def test_closed_entry_merely_naming_recurring_is_exempt():
    closed = [{
        "id": "regenerate-fidelity-artefacts-is-a-recurring-obligation-"
              "modelled-as-a-one-shot-task",
        "title": "The fidelity regeneration is recurring and was "
                  "modelled as one-shot",
        "closed_by": "uncommitted:2026-09-08",
        "reason": "The version-pinned artefact regeneration is replaced "
                  "by a version-less recurring obligation whose "
                  "done-condition is test_output_sha reading 0 "
                  "disagreeing, and which says in its own verify that "
                  "it cannot be closed.",
    }]
    assert plan_audit.check_j([], closed, {}) == []


# ---------------------------------------------------------------------
# The positive case, appearing in `closed`: a task whose own verify uses
# the real self-declaring phrase (as
# regenerate-the-fidelity-artefacts-whenever-the-converter-emission-
# changes's verify does) must be flagged if it is ALSO in `closed` --
# a recurring obligation must never be closeable.
# ---------------------------------------------------------------------
def test_declared_recurring_task_in_closed_is_reported():
    t = base_task(
        id="regen-fidelity",
        verify="A RECURRING OBLIGATION, DELIBERATELY VERSION-LESS: after "
               "any commit that changes what the converter emits, the "
               "suite reads 0 disagreeing. THIS TASK CANNOT BE SATISFIED "
               "ONCE. A runner that finds it done and the suite green "
               "should leave it open, not close it.")
    closed = [{"id": "regen-fidelity", "title": t["id"], "reason": "x"}]
    findings = plan_audit.check_j([t], closed, {})
    assert ("regen-fidelity", "in `closed`") in findings


# ---------------------------------------------------------------------
# The positive case, a `done` last run: the exact failure this repo lived
# through once already (regenerate-fidelity-artefacts-at-v0-5-459's
# successor task exists specifically to name this) -- reported even when
# the task is still open (not in `closed`).
# ---------------------------------------------------------------------
def test_declared_recurring_task_with_done_last_run_is_reported():
    t = base_task(
        id="regen-fidelity",
        verify="THIS TASK CANNOT BE SATISFIED ONCE: a runner that finds "
               "it done and the suite green should leave it open, not "
               "close it.")
    runs_last = {"regen-fidelity": {"id": "regen-fidelity",
                                     "outcome": "done"}}
    findings = plan_audit.check_j([t], [], runs_last)
    assert ("regen-fidelity",
            'runs.jsonl last record is outcome "done"') in findings


# ---------------------------------------------------------------------
# The same declared task with a non-"done" last run (e.g. "partial") and
# not in `closed` is not reported at all -- this is the correct steady
# state for a live recurring task being worked.
# ---------------------------------------------------------------------
def test_declared_recurring_task_with_partial_last_run_is_not_reported():
    t = base_task(
        id="regen-fidelity",
        verify="THIS TASK CANNOT BE SATISFIED ONCE: leave it open, not "
               "close it.")
    runs_last = {"regen-fidelity": {"id": "regen-fidelity",
                                     "outcome": "partial"}}
    assert plan_audit.check_j([t], [], runs_last) == []


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
