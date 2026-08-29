<original_task>
**A `/runqueue --until-blocked` drain** at HEAD `8967b3f`, following the
v0.5.407 adoption of the gate search result. Four cycles ran; this commit is
their combined result.

This file is **state, not a knowledge store** — the design decision shipped in
v0.5.404. Durable facts belong in `CLAUDE.md`, which loads into every session;
the open-task list is `.claude/tasks/whattask.json` and the run history is
`.claude/tasks/runs.jsonl`. What is here is what is IN FLIGHT.
</original_task>

<work_completed>
## Committed

- **v0.5.407 `8967b3f`** — the adjudicated gate search result adopted.
- **v0.5.408 (this commit)** — four `/runqueue` cycles, below.

## The drain

| cycle | lane | task | outcome |
| --- | --- | --- | --- |
| 1 | delegated | `report-text-can-be-invalidated-by-the-change-that-regenerates-it` | done |
| 1 | main | `claude-md-states-measured-numbers-in-the-present-tense` | **partial** |
| 2 | main | `forcing-tempo-bypasses-multiplier-assignment` | done |
| 3 | main | `record-the-gate-term-task-in-the-run-log` | done |
| 4 | main | `regrid-lengthened-row-may-extend-an-in-progress-slide` | done |

`adopt-the-gate-search-result` was also recorded `done` — it had been run
directly in the session before the queue and so had no `runs.jsonl` line,
which left its three dependents reading as blocked on disk.

## Cycle 4 is the substantive one, and its headline is a refutation

The task's own **title** named the lead: a lengthened row extending an
in-progress slide. It is **dead**. With `slides` off entirely the collapse is
identical — One_on_One −37.0pp, Sanxion −19.9pp, damaged voices 189→211 and
346→357 — and `slides: False` demonstrably moves both files' bytes, so the arm
is not vacuous. That is the **fourth** dead hypothesis for this defect.

What replaced it, bounded from both sides:

- **It is the extra call, not the command.** The same `CMD_SETTEMPO` pair
  written with `base` instead of `base + 1` costs **0.0pp on both files** and
  returns each damaged voice's collapsed count exactly to baseline.
- **The damage is wrong pitches, not extra attacks.** Attacks *fall* in the
  damaged voice (One_on_One v3 375→371) while the collapsed count *rises*.
- **Never voice 0** — regrid's occupied-column guard checks the pattern it
  writes into, which is voice 0's, but `CMD_SETTEMPO` under `$80` sets all
  three channels.
- **The two files do not share one cause.** Vibrato-off takes One_on_One from
  −37.0pp to −0.2pp and leaves Sanxion at −19.9pp.

Written into `regrid_tempos`' docstring, not left in the run log.

## Verification

- Suite **1626 passed, 2 skipped** (1622 + the 4 tests the delegated agent
  added).
- **Corpus byte-hash: 0 of 83 files moved**, with the `convert.py` and
  `patterns.py` changes both in the tree.
- `docs/FIDELITY.md` regenerated: **6 lines changed, ZERO table rows** — the
  version stamp plus exactly the two prose bullets cycle 1 rewired. The
  agent's fix is visible working on the real corpus: the example names and
  deltas are now read from rows, and the previously unbacked "It is reached
  now" claim now reads `probed 4 file(s) ... and measured 4 of them`.
- Non-vacuousness proven for both new test sets by reverting the source and
  confirming failure — and for cycle 2, by the sharper version: the helper
  left in place with only its call site removed still fails the byte test.
</work_completed>

<work_remaining>
1. **`[user]` ACE_II carries TWO withheld gains awaiting one listening
   session** — `rest_envelope_silence` (+3 adsr, v0.5.394) and
   `hard_restart_frames` (+15.1 gate, v0.5.407, in `FIDELITY_VETOED`). Both
   recorded with their numbers; the ask is one question. Also open:
   `monty-firstwave-trade-needs-a-listen`.
2. **`[main]` Four ready tasks all write `presets.json`** —
   `multiplier-is-chosen-from-subtune-0`, `skate-or-die-row-is-5-halves-not-3`,
   `international-karate-voices-never-set-an-instrument` and (newly unblocked)
   `regrid-melody-collapse-on-the-six-refused-files`. This is why the drain
   stopped with work still runnable: the queue cannot commit, and regenerating
   a hazard artefact on top of an uncommitted tree records a state that never
   existed. With this commit landed they are unblocked in practice.
3. **`[subagent]` `cd-then-heredoc-short-circuits-and-the-next-check-passes-anyway`**
   is blocked only because its `depends_on` names a task recorded `partial`.
   Its real relationship to that task is that both write `CLAUDE.md`, which is
   contention `touches` already handles. Fix the plan, then it runs.
4. **`[main]` 49 registered worktrees**, none prunable, several sharing old
   commits. CLAUDE.md's parallel-work section records these swapping agents'
   work before now.
</work_remaining>

<attempted_approaches>
- **The `serial.lock` registry was NOT empty**, contrary to the previous
  handoff's claim: it held a record for `fidelity-better-has-no-gate-term`
  (`pid: null`, host TDZASUS) for a task `whattask.json` lists as closed. It
  holds `r:python/fidelity.py` and would have blocked cycle 1's only delegable
  task. A null-pid record cannot be reaped by the pid rule at all — it needed
  a second signal (the task being closed in the plan).
- **`whattask.json`'s `external_locks` names the registry itself**
  (`.claude/tasks/serial.lock`), which exists permanently. Read literally the
  queue must stop every time, forever. Proceeded on the arithmetic; the real
  signal is the mutex directory, which was absent.
- **The delegated agent's worktree was based at `4d9d9f2`, not HEAD.**
  Immaterial here — `git diff 4d9d9f2 8967b3f -- python/fidelity.py
  python/tests/test_fidelity.py` is empty — but it was checked rather than
  assumed, and its patch was applied with `git apply --check` first.
- **`fidelity.py` has no `--regrid` flag**; forcing an option for an A/B means
  writing a patched `presets.json` copy OUTSIDE the repo and passing
  `--presets`. Rikky already ships `regrid: true`, so its "control" arm needed
  a regrid-REMOVED copy — the first attempt compared two identical arms.
- **`tar -x -C` cannot take a Windows drive-letter path**; the corpus
  byte-hash recipe needs `git archive -o <tarball>` plus Python `tarfile`.
- **`cd X && <cmd>` bit again** — the session cwd was already `python/`, the
  `cd` failed, `&&` short-circuited, and a 12-minute regeneration silently did
  not run. Third sighting. Use absolute paths.
- **An A/B probe asserting `status == "ok"`** — the real value in
  `build/fidelity.json` is `"measured"`, and its columns are FRACTIONS where
  the report prints percentages.
</attempted_approaches>

<critical_context>
Durable repo knowledge is in `CLAUDE.md` and is not repeated here.

- **`CLAUDE.md` now carries a grading rule for measured figures** — historical
  and carrying the version it was measured at, or live and re-checked. Three
  figures were corrected as stale ("37 of the 82 measured files", "33 of the
  83 preset songs pack at `-S2`", "37 corpus files drift by zero and 29
  drift") and five re-verified live. `test_call_rate.py` had inherited one of
  the stale ones, which is the propagation the rule predicts.
- **`claude-md-states-measured-numbers-in-the-present-tense` is `partial` on
  purpose.** Its verify asks that EACH figure be graded; the pass covered the
  cheaply checkable ones and every figure an open task's verify keys on. The
  rest need corpus sweeps.
- **`convert()` now derives its own pack factor** (`_derived_multiplier`) on
  all three tempo branches. Zero corpus files take the
  `det.frames_per_row > 1` branch, so only the forced-tempo path was live.
- Corpus: `C:/Users/mit/claude/c64server/SIDM2/SID/Hubbard_Rob` (95 files,
  83 convert). Full suite ~6 min. `FIDELITY.md` regeneration ~12 min.
</critical_context>

<current_state>
HEAD v0.5.408, everything above committed. Working tree clean.

**Verified:** suite 1626 passed / 2 skipped; corpus byte-hash 0 of 83 moved;
`FIDELITY.md` regenerated with zero table rows changed.

The lock registry (`.claude/tasks/serial.lock`) is `[]` and the mutex
directory is absent; nothing is held.
</current_state>
