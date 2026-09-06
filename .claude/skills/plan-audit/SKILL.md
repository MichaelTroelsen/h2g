---
name: plan-audit
description: Check .claude/tasks/whattask.json for the grant defects that block runs — absent paths, missing test grants, verify paths not in touches, lane arithmetic, dangling deps, ungraded shas.
disable-model-invocation: true
---

# plan-audit

```
python .claude/skills/plan-audit/plan_audit.py
```

Read-only. Exits 1 when anything is found, so it can gate a regeneration.

**Run it after every `/whattask` regeneration, before any `/runtask`.** Every
check exists because the defect it names shipped in a real plan and cost at
least one cycle.

## What each finding means

**A — a granted repo path that is not in the tree.** Ambiguous by design: a
task that CREATES a file legitimately grants a path that does not exist yet.
The census is cheap (296 granted paths, 3 absent when first measured) and the
one real typo it caught was `test_drum.py` where `test_drum_return.py` is the
file — a runner would have created a second test file beside the existing one.
Intent cannot be read off the prose: plan authors do not name the file they
mean to create in the verify text. Judge each by hand.

**B — `rw:` on a source file whose test file is not also `rw:`.** A behaviour
change necessarily changes the test that pins it, so a runner finding the test
ungranted must either widen its own lock mid-run or drop the assertion to dodge
it. Five sightings. Mechanical: `rw:<dir>/<name>.py` implies
`rw:python/tests/test_<name>.py` where that exists.

**C — a path named in `verify` but not covered by `touches`.** The variety that
keeps recurring is not an absent path but one granted **too weakly** — `r:` on
a path the verify must write, which a presence-only check waves through. Three
tasks were blocked on it in one session; the sharpest was a task whose own
human decision required writing two files it held `r:` on, so it could not do
what it had been told to do.

**D — two `parallel` tasks overlapping with at least one writer.** Not a
judgement call, an arithmetic error. Lane is derived from `touches`; if the
derivation and the recorded lane disagree, the recorded one is wrong.

**E — a dangling `depends_on`.** Silently never resolves, so the dependent
never becomes ready and nothing says why. Usually a truncated id.

**F — a `verify` quoting a sha HEAD has moved past.** Not automatically wrong,
but ungraded: a figure pinned to a tree that has moved reads as current and
gets cited as current. Either name the commit it was measured at — CLAUDE.md's
own rule for this repo's prose — or replace it with "check X against Y".

## What it deliberately does not do

It does not fix anything. `whattask.json` is a snapshot keyed to a commit and
the supported way to change it is `/whattask`; a hand-patched plan whose
`generated_from.head` still points at the old commit is worse than the defect,
because it looks current.

It also cannot see **unnamed tool output** — a path some tool writes that
appears in no verify string. That half has to be asked, not scanned: for every
tool a verify invokes, ask what that tool writes. The case that taught this was
`build/sound_calibration.json`, the `--json` default of `sound_calibrate.py`,
which appeared in no task's grant at all.
