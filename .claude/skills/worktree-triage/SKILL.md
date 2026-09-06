---
name: worktree-triage
description: Group the linked worktrees into those holding unique work and those prunable with nothing lost, so a human is asked about the few rather than all 44.
disable-model-invocation: true
---

# worktree-triage

```
python .claude/skills/worktree-triage/worktree_triage.py
```

Read-only. Reports; removes nothing.

`twenty-four-worktrees-hold-uncommitted-work-from-past-sessions` asks for "a
decision per worktree: land it, discard it, or leave it". The count is **44**
now, not 24 — it is growing, not waiting — and 44 decisions is not one
sitting's work. This does the mechanical half so the human question shrinks to
the ones that matter. Measured at `e28179a`: **29 hold work, 15 are prunable**.

## The two traps this had to avoid, both hit while writing it

**`git rev-list master..HEAD` counts the DIVERGENCE, not the work.** These
branches were cut from an old master, so it reports "147 files changed, 40980
deletions" for a branch whose real contribution is one commit — and every
worktree then looks like it holds something. `git cherry` compares PATCHES and
marks `-` for a change already upstream, which is what separates "landed under
a different sha" from "exists nowhere else". That single change moved the
answer from a useless *44 of 44* to *29 of 44*.

**"Dirty" is not "holds work".** A worktree dirty only in `runs.jsonl`,
`whats-next.md`, `build/` or a generated doc holds session bookkeeping. One
dirty in `python/h2g/` holds something only it has. The script splits those;
without the split the report re-lists the problem instead of narrowing it.

## Reading the output

- **HOLDS WORK** — uncommitted source paths, or commits `git cherry` marks as
  unlanded. These need you. The detail lines name the actual files.
- **BOOKKEEPING ONLY / EMPTY** — prunable with `git worktree remove`, nothing
  lost.
- **PATH MISSING** — `git worktree prune`.

## Before recovering anything

**Never `git stash`.** `refs/stash` is shared across every worktree of this
repo, and doing it here has already returned another task's diff — 92
unreachable `WIP on worktree-…` commits are still in the object store from it,
while `git stash list` reads empty. The `stash_guard` hook now blocks it.

Snapshot with `git diff > x.patch` (restore with `git apply -R`), a file copy,
or a scratch branch.
