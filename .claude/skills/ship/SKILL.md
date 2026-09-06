---
name: ship
description: The full commit sequence for this repo — suite, version bump, generated artefacts, staged-path check, trailers, push, graph refresh. Knows which commits skip the bump and why.
disable-model-invocation: true
---

# ship

The commit sequence CLAUDE.md specifies, in order, with the judgements it
requires. Run it instead of assembling the steps by hand — they were assembled
by hand six times in one session and the ordering is not obvious.

## First: decide which shape this commit is

**This is the step people skip, and it changes what runs.**

| what changed | bump? | artefacts? | suite? |
|---|---|---|---|
| anything under `python/` (except the cases below) | **yes** | **yes** | **yes** |
| only `.claude/tasks/*` | **no** | no | no |
| only `.claude/` tooling (hooks, agents, skills, settings) | **no** | no | no* |
| only generated artefacts (`docs/FIDELITY.md`, `docs/QUEUE.md`) | **no** | no | no |
| only docs a human writes (`CLAUDE.md`, `README.md`) | **yes** | **yes** | yes |

The task-file-only exception has precedent — `8b7b218`, `fd286a5`, `ea9e12a`,
`c490b72` — and a reason: `bump_version.py` rewrites `__init__.py` and
`CHANGELOG.md`, and the sequence then regenerates `SURVEY.md` and
`presets.json`, which would stamp both artefacts with a converter change that
did not happen. `FIDELITY.md`/`QUEUE.md` are **on demand**, not part of the
per-commit set, so a commit that only refreshes them bumps nothing.

`.claude/` tooling bumps nothing for the same reason `.claude/tasks/` does not: the version stamps `SURVEY.md` and `presets.json`, both derived from CONVERSION behaviour, and agent tooling reaches neither. *The suite still does not apply, but any hook or script added there must be exercised on a real input before it ships -- a guard that never fires is worse than none, because it reads as cover.

Check with `git status --porcelain` before choosing. If it is mixed, the
strongest applicable row wins.

## The sequence, when a bump is owed

Every step from `python/`, and **absolute paths or a single `cd`** — the Bash
tool's working directory persists, so a second `cd python && …` fails and `&&`
silently swallows what follows. That has cost this project a whole
regeneration that never ran.

1. **Full suite.** `python -m pytest tests/ -q`. It takes about 7m20s and must
   be green. Note the count: a change to the test files should move it by
   exactly the number of tests added, and a mismatch is worth reconciling
   before going on rather than after.
2. **Bump.** `python python/bump_version.py "short description"` from the repo
   root. Writes `python/h2g/__init__.py` and `docs/CHANGELOG.md`.
3. **`SURVEY.md`**, from `python/`:
   `python survey.py <sid_dir> -o ../docs/SURVEY.md --legal-restart --gt2reloc`
   Both flags are load-bearing: without `--gt2reloc` the pack-back column comes
   out empty and silently; without `--legal-restart` `greloc.c:244` refuses
   every tune ending on Hubbard's `$FE`, so the column measures the option's
   absence rather than the converter.
4. **`presets.json`**, from `python/`:
   `python presets.py <sid_dir> -o ../presets.json`
   **Read the carry line it prints.** A plain run carries forward whatever
   `--fidelity` recorded and says how many; if that number drops, measured
   per-song decisions have been lost and the commit should stop.
5. **Read both diffs.** On a commit that changes no conversion behaviour they
   should move by their version line ALONE. If either moved further, something
   reached the converter that you did not think had — find out what before
   committing.
6. **Verify the staged path list.** `git add -A && git diff --cached --name-only`
   and look at it. A fork once committed nine duplicate files at the repo root
   this way.
7. **Commit** with a message written to a file and passed as `git commit -F
   <path>` — never a long `-m`, which can exceed what the harness will
   security-scan and stops for a human mid-run. End with both trailers:
   `Co-Authored-By:` and `Claude-Session:`.
8. **Push**, then **`graphify update .`** from the repo root. The graph refresh
   is the orchestrator's job, not a delegated agent's: `graphify-out/` is in
   nobody's `touches`, so an agent that ran it would be writing an undeclared
   path. It has rotted 15.5 hours unnoticed before.

## What the message should carry

State what was measured, with the number and where it came from. A figure
without a version or a commit beside it decays into a false one — that is this
repo's own grading rule, and commit messages are not exempt just because they
are immutable. If a claim in an earlier message turns out wrong, retract it
here in words a grep for the original will find; the history cannot be edited,
so the retraction has to be findable from the same terms.
