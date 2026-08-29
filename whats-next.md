<original_task>
**"Read what next", then "regenerate the artefacts."** The session opened by
reading the previous handoff and picking up its `<work_remaining>` item 1:
regenerate `docs/FIDELITY.md` and `build/fidelity.json` against the already-
adjudicated `presets.json` sitting uncommitted in the tree, confirm the `gate`
column moved on the 16 files that had gained a hard-restart setting and nowhere
else, then bump and commit.

Everything after that was requested explicitly, one instruction at a time:
`bump and commit` -> `push it` -> `/runqueue --until-blocked` ->
`commit this` -> `push it` -> `/whattask` -> `/runqueue --until-blocked` ->
`merge both worktrees and commit` -> `push it` -> this handoff.

**A NOTE ON THIS FILE'S SCOPE.** v0.5.404 established that `whats-next.md` is
STATE, not a knowledge store: durable facts belong in `CLAUDE.md` (loaded every
session), the open-task list is `.claude/tasks/whattask.json`, and the run
history is `.claude/tasks/runs.jsonl`. This document is written comprehensively
as requested, but it deliberately POINTS AT those files rather than copying
them — duplicated prose is what drifts. Where a fact is durable it says where
it now lives.
</original_task>

<work_completed>

## Three commits, all pushed to `origin/master`

### v0.5.407 `8967b3f` — the gate search result adopted

The tree already held an adjudicated `presets.json` (LOST 2 / GAINED 24 across
16 files / CHANGED 1) plus three hand adjudications in `python/presets.py`.
What this session added was the *verification* and the commit.

- Regenerated `docs/FIDELITY.md` + `build/fidelity.json` at `-t 60` against the
  adopted presets.
- **A/B'd against a snapshot of the previous run** rather than eyeballing the
  new table. `output_sha` moved on **exactly 17 files** — the 16 that gained a
  setting plus `Dragons_Lair_Part_II`, the documented LOST #1. Nothing else.
- On all 16, `melody` / `sequence` / `pitch_jaccard` and **both attack counts
  are identical to three decimals**. Only `gate` moves. That is the shape a
  hard-restart change must have, and it is what distinguishes this from a
  change that merely scores better.
- Gate gains: Thanatos 49.0→96.0, Las_Vegas 51.7→91.2, Delta_Mix-E-Load
  59.6→93.6, Kings_of_the_Beach_intro 76.6→91.9, Ninja 50.1→74.7,
  Samantha_Fox_Strip_Poker 32.6→65.4, Rock_Tells_the_Tale 48.1→61.7,
  Mr_Meaner 63.3→75.1, Food_Feud 64.2→74.6, Human_Race 59.8→67.4,
  Chain_Reaction 62.8→67.0, Deep_Strike 49.6→55.7, Pygmies_Revenge 49.1→55.0,
  Lightforce 41.0→61.5, Thundercats 87.5→92.5, Zoolook 33.1→38.6.
  **The four the previous session had spot-measured by hand reproduce
  exactly** — an independent second reading of the same decision.
- Exactly one cell worse corpus-wide: `Dragons_Lair_Part_II` `wave`
  0.731→0.704, from the adjudicated `no_test_restart` loss, on a row that is a
  known harness artefact (melody 14%, 359 attacks vs the original's 556).
- `len`: **zero breaches** of the ±5s rule, measured on 6 of 83 rows both
  before and after — unchanged coverage.
- Suite 1620 passed / 2 skipped. All three human approvals **HOLD by sha256**,
  recomputed through `abpage.conversion_shas()` rather than inherited:
  5_Title_Tunes `762b0457ae84`, ACE_II `7bc6dfad62f1`, Action_Biker
  `3554a89bc1c0`.

### v0.5.408 `ef7caee` — a `/runqueue --until-blocked` drain, four cycles

| cycle | lane | task | outcome |
| --- | --- | --- | --- |
| 1 | delegated | `report-text-can-be-invalidated-by-the-change-that-regenerates-it` | done |
| 1 | main | `claude-md-states-measured-numbers-in-the-present-tense` | **partial** |
| 2 | main | `forcing-tempo-bypasses-multiplier-assignment` | done |
| 3 | main | `record-the-gate-term-task-in-the-run-log` | done |
| 4 | main | `regrid-lengthened-row-may-extend-an-in-progress-slide` | done |

- **`convert()` now derives its own pack factor.** `multiplier` was assigned
  only on the fully-derived tempo branch, so `convert(tempo=N)` left it at 1
  while `fidelity._skip_gate_multiplier` INDEPENDENTLY re-derives the factor and
  packs at it — every per-call rate encoded for `-S1` while the file ran at
  `-SM`. New helper `_derived_multiplier(sid, det, skip_gate)` in
  `python/h2g/convert.py`, called from both branches that skipped it. A census
  scoped the fix: **0 of 95 corpus files take the `det.frames_per_row > 1`
  branch**, so only the forced path was live.
- **`fidelity.py`'s report prose pinned to its own rows** (delegated): two
  claims were hardcoded English never read from `rows`.
- **CLAUDE.md's measured figures graded** (partial): a new rule plus three
  stale figures corrected, five re-verified live.
- **The regrid investigation**: refuted the task's own title (see
  `<attempted_approaches>`).

### v0.5.409 `cd2db79` — a second drain, two cycles, merged from worktrees

| cycle | lane | task | outcome |
| --- | --- | --- | --- |
| 5 | delegated | `not-measured-note-length-claim-is-stale-…` | done |
| 5 | delegated | `cd-then-heredoc-short-circuits-…` | done |
| 5 | main | `lock-records-with-a-null-pid-…` | done |
| 6 | main | `sanxion-regrid-collapse-has-a-second-per-call-pitch-source` | done |

**The headline is a retraction of this session's own earlier work.** v0.5.408
concluded, from a vibrato A/B, that One_on_One's and Sanxion's `--regrid`
collapses "do not share one cause". Wrong. Turning `no_test_restart` off erases
both:

    Sanxion     -19.9pp -> +0.2pp    voice 2 collapsed 346 -> 343 (orig 344)
    One_on_One  -37.0pp -> +0.5pp    voice 3 collapsed 188 -> 186 (orig 186)

`slides`, `vibrato` and `two_stage` each leave Sanxion's figure unmoved to a
tenth of a point. Vibrato masks One_on_One's — a **co-factor**, not the cause.
Mechanism: `--no-test-restart` deletes the testbit frame, the only frame our
conversions spend below `$10`, and siddump needs one below `$10` to name an
attack (siddump.c:434-437). It **owns frame 0**; a compensating row moves the
boundary underneath it. Not a pitch generator — two options contending for one
frame. Written into `regrid_tempos`' docstring, replacing the paragraph it
retracts.

**Necessary but not sufficient**, which is the live open question: six corpus
files carry `no_test_restart` and could take `--regrid`; four ship with it
adopted and are fine (Arcade_Classics, **Rikky**, Sigma_Seven, Wiz), two
collapse. All are `-S1` and their row counts interleave (Sigma_Seven 3599 vs
One_on_One 5584; Wiz 20373 vs Sanxion 17660), so neither multiplier nor size is
the discriminator.

### `/whattask` regeneration at `ef7caee`

Rewrote `.claude/tasks/whattask.json` whole: **23 open tasks, 17 closed**.
Sources: `whats-next.md`, `todo.md`, the whole `runs.jsonl` (154 distinct ids),
the previous plan, `docs/FIDELITY.md`, `presets.json`, `build/fidelity.json`,
`graphify-out/graph.json`, and the commits. `gh` was authenticated and the repo
has **zero open issues and zero open PRs**. No `decisions.jsonl` exists.

Reconciliations worth keeping:
- **`todo.md`'s "Rebuild `build/instrmap`" reopened.** Closed at `9b939a6`, but
  the dumps are mtime *2026-08-28 18:03* while v0.5.407 landed after them and
  moved the bytes of 17 files. Tracked as a NEW id
  (`instrmap-is-stale-against-v0-5-407`) rather than reopening one whose run
  log reads `done`.
- **`external_locks` fixed.** The previous plan named
  `.claude/tasks/serial.lock` — the registry itself, which exists permanently —
  so read literally every `/runqueue` had to stop before starting. Now only
  `.claude/tasks/serial.lock.d`, the mutex directory.
- **`cd-then-heredoc`'s bogus `depends_on` removed** — its only real relation to
  the CLAUDE.md task was that both write that file, which is contention
  `touches` already handles. As a dependency, a `partial` blocked it forever.
- **Two counts corrected from live data**: the firstwave task said "45+ files
  read hold 0%"; it is **39**. Skate or Die's 829-against-1021 and Kings of the
  Beach ingame's wave 57.3% / gate 11.0% were re-verified live, so both those
  tasks remain judgeable.
- **`touches` widened from the graph.** The mechanical `test_<name>.py` rule
  finds nothing for `patterns.py` and `goatwriter.py` — this repo names tests by
  FEATURE. `graphify query` showed 20+ test files depending on `goatwriter.py`,
  so tasks writing a core module declare `rw:python/tests` as a directory.
- Only ONE of 23 tasks is `parallel`. That is arithmetic, not laziness: nearly
  everything reads or writes `presets.json` and `docs/FIDELITY.md`.

## Durable knowledge added to CLAUDE.md (do not duplicate here)

- The **grading rule** for measured figures (historical-with-a-version, or live
  and re-checked; the ungraded middle is what gets cited after the tree moves).
- The **`cd X && <edit>` short-circuit** rule, beside the `str.replace` rule it
  generalises, with all three sightings named.
</work_completed>

<work_remaining>

## 0. FIRST: the plan is stale — re-run `/whattask`

`.claude/tasks/whattask.json` has `generated_from.head = ef7caee`; HEAD is
`cd2db79`. **Four of its 23 tasks are now `done`** in `runs.jsonl` and the file
still lists them as open:

    sanxion-regrid-collapse-has-a-second-per-call-pitch-source
    not-measured-note-length-claim-is-stale-since-hold-column-partially-reaches-it
    cd-then-heredoc-short-circuits-and-the-next-check-passes-anyway
    lock-records-with-a-null-pid-cannot-be-reaped-by-the-pid-rule

Also missing from it: the ids opened during the second drain —
`agent-scratchpads-are-not-isolated-from-the-orchestrators`,
`regrid-and-no-test-restart-need-a-guard-or-a-documented-incompatibility`,
`orphaned-tail-processes-survive-their-sessions`. A `/runqueue` will still work
(it recomputes readiness from `runs.jsonl`) but the table will mislead a human.

Current standing: **19 open — 13 ready main, 3 requires-user, 3 blocked.**

## 1. `[main]` The highest-value ready task

`multiplier-is-chosen-from-subtune-0-but-belongs-to-the-subtune` (opus,
`needs_main`). One call rate is picked from subtune 0 and 12 corpus files have
a subtune needing a higher one. It unblocks `kings-of-the-beach-wants-
multiplier-3`, and it must precede the other `presets.json` writers because
each regenerates the report the others would invalidate.
Verify: Kings of the Beach reaches wave 72.8% / gate 33.1% (against 57.3/11.0
at `-S1`, melody/seq/pitch unchanged at 100%), and a corpus byte-hash moves
only files whose per-subtune `recommended_multiplier` exceeds their recorded
one. Take the 12 ONE AT A TIME with `--search-subtunes`; Delta wants `-S10` and
CLAUDE.md records that a file above `-S4` cannot be judged on a normal trace.

## 2. `[user]` Three listening verdicts, none settleable by measurement

- **ACE_II** carries TWO withheld gains, both changing the `.sng` sha256 a
  listener approved: `hard_restart_frames` (gate 78.3→93.4%, every other column
  identical, in `presets.FIDELITY_VETOED` since v0.5.407) and
  `rest_envelope_silence` (adsr 93→96, withheld at v0.5.394). **One session
  settles both.** Stage the approved build against one carrying both.
- **Monty**: `real_firstwave_instruments [1..16]` buys hold 0→88% and some
  wave, costs pitch 95→92.
- **Action Biker**: the subtune-order fix landed (`f63caa1`) but the ear check
  was never retaken. Its sha in `approved.json` should be confirmed as the
  post-fix one.

## 3. `[main]` `--regrid` + `--no-test-restart` needs a guard or a documented incompatibility

Now that the collision is attributed. **A blanket veto would be wrong** — four
files carry both happily. The discriminator is unknown; see
`rikky-immunity-to-regrid-is-unexplained`, which is the same question.

## 4. `[main]` `build/instrmap` is stale, second time

Dumps predate v0.5.407, which moved 17 files' bytes.
`python abpage.py --instrmap <corpus>` from `python/` — use ABSOLUTE paths.
Rebuilds `build/instrmap` AND `build/listen`, both hazards, so it must not run
beside anything reading them.

## 5. `[main]` 51 registered worktrees, none prunable

Including the two merged this session, now redundant (their content is in
`cd2db79`). **HAZARD FOUND THIS SESSION:** `rw:.claude/worktrees` collides with
every delegated agent's own isolation worktree, which no task declares — so
this must never run beside a fan-out. Check `git -C <wt> status --short` and
`git log` against master before removing anything.

## 6. Outside this repo, uncommitted

`plugins/mit-setup/LOCKING.md` in
`C:/Users/mit/.claude/plugins/marketplaces/mit-claude-setup` (its own git repo,
plugin v1.9.5) — my parent-chain-walk fix for the null-pid problem, 43 lines,
sitting alongside a **pre-existing uncommitted 27-line edit from an earlier
session** about `refs/stash` being shared across worktrees. Both verified
intact. The cache copy at `plugins/cache/mit-claude-setup/mit-setup/1.9.5/` was
deliberately NOT edited — a reinstall would overwrite it.
</work_remaining>

<attempted_approaches>

## Refuted hypotheses (do not redo)

- **"`fidelity_better` has no gate term"** — FALSE, and it was this project's
  own claim. `gates_right` has existed since v0.5.271. Retracted in v0.5.406's
  message; recorded in `runs.jsonl`.
- **"A lengthened regrid row extends an in-progress slide"** — the task's own
  TITLE. Refuted: with `slides` off entirely the collapse is IDENTICAL
  (−37.0pp, −19.9pp; 189→211, 346→357), and `slides: False` demonstrably moves
  both files' bytes so the arm is not vacuous.
- **"The two regrid casualties do not share one cause"** — my own v0.5.408
  conclusion, refuted in v0.5.409 (above). The lesson: **one A/B that removes a
  symptom is not an attribution.** Vibrato removed One_on_One's symptom while
  being a co-factor, not the cause.
- Four hypotheses were already dead before this session (funktempo restore
  value, over-delivery, slide-heaviness, and the slide extension) — recorded
  under `regrid-melody-collapse-on-the-six-refused-files`.

## Probe and tooling failures hit this session

- **`cd python && <cmd>` when the shell was already in `python/`.** The `cd`
  fails, `&&` short-circuits, and a 12-minute `FIDELITY.md` regeneration
  silently did not run (exit 1, `cd: python: No such file or directory`). THIRD
  sighting; now a CLAUDE.md rule.
- **An A/B probe asserting `status == "ok"`.** The real value in
  `build/fidelity.json` is `"measured"`. The assertion fired; without it the
  probe would have compared ZERO rows and reported a clean corpus.
- **A scripted edit whose assert fired on LINE ENDINGS, not content.**
  `patterns.py` is CRLF and the search string used `\n`. Fix: read in
  universal-newline mode, write in default text mode, so the file's endings
  round-trip.
- **A nested heredoc mangled a patch script's escapes** (`\r\n` became literal
  newlines, producing a SyntaxError). The repo's own rule covers it: write the
  script to a file with the Write tool and run `python <path>`.
- **`tar -x -C` cannot take a Windows drive-letter path.** The corpus byte-hash
  recipe needs `git archive HEAD -o <tarball>` plus Python's `tarfile`.
- **A stray `cp ... /tmp/...` succeeded**, so an `||` fallback to the scratchpad
  never ran and a backup landed outside the session directory.

## Orchestration findings (recorded in `runs.jsonl`, NOT fixed)

- **`serial.lock` was NOT empty** when this session's first drain started,
  contrary to the previous handoff's claim: it held a record for
  `fidelity-better-has-no-gate-term` (`pid: null`, host `TDZASUS`, head
  `c376622`) — a task `whattask.json` lists as CLOSED. It holds
  `r:python/fidelity.py` and would have blocked the drain's only delegable
  task. **A null-pid record cannot be reaped by the pid rule at all**; it was
  cleared only by a second signal (the task being closed in the plan), which
  LOCKING.md explicitly says not to guess at.
- **The null-pid fix's two obvious forms are BOTH wrong.** (1) The writing
  shell's pid dies within milliseconds — every tool call is its own shell — so
  every later run would reap a holder whose task is still running; strictly
  worse than null, which fails safe. (2) A lookup by process name is useless:
  **13 `claude.exe` processes** were running at once. The answer is to walk the
  parent chain to the FIRST `claude.exe` ancestor; verified chain
  `pwsh.exe -> claude.exe -> pwsh.exe -> WindowsTerminal.exe -> explorer.exe`.
- **Agent scratchpads are NOT isolated from the orchestrator's.** An agent's
  `bh_probe.py` and a full `bh_scratch/` export appeared in this session's
  scratchpad, and the orchestrator's own identically-purposed `bytehash.py` had
  vanished by the time it was next needed. Two concurrent agents doing corpus
  byte-hashes in one directory is the shared-fixed-filename failure this repo
  already fixed once inside `fidelity.py` (v0.5.66).
- **Three orphaned `tail -f` processes** from PREVIOUS sessions are still
  running, one since Aug 22. Not this session's children, so reported rather
  than killed.
- **The Edit tool refuses the shared checkout path from inside an isolated
  agent**, directing it to the worktree copy. So a `touches` path is implicitly
  rewritten to the agent's worktree.

## Deliberately not pursued

- Adding a new term to `fidelity_better` — unnecessary (the term existed), and
  CLAUDE.md records a version of that change which lost seven measured settings
  and gained one.
- Deleting any worktree, despite 51 being registered — CLAUDE.md records
  worktrees swapping agents' work, and two held unmerged work until this
  session's final commit.
- Committing anything during a `/runqueue` drain — the command forbids it, and
  both drains reported and stopped instead.
</attempted_approaches>

<critical_context>

## Verification standards actually applied (and worth keeping)

- **Non-vacuousness was proven for every new test**, not asserted. The strongest
  form used: for `_derived_multiplier`, the helper was left in place and only
  its CALL SITE removed — the byte test still failed, which is the regression
  that actually matters. (Reverting the whole file only proves the test touches
  new code.)
- **Corpus byte-hash after every change**: 83 converted / 12 refused / 0 errors
  both sides, compared 83, **moved 0** for all three commits.
- **Report regeneration as a second, independent reader.** Regenerating
  `docs/FIDELITY.md` and finding *4 lines changed, ZERO table rows* is what
  confirmed the delegated prose fix works on the real corpus rather than only in
  a test.
- **Agent records were verified, never trusted**: id equality first, then scope
  (`git status` in the worktree), then re-running the reported numbers, then
  non-vacuousness.

## Repo facts that bit this session

- `build/fidelity.json` rows use `status == "measured"` (NOT `"ok"`), and its
  columns are FRACTIONS (0.0–1.0) where the report prints percentages.
- `fidelity.py` has **no per-option flags**. Forcing an option for an A/B means
  writing a patched `presets.json` copy OUTSIDE the repo and passing
  `--presets`. **Check the option is actually ON in the shipped entry first** —
  Rikky already ships `regrid: true`, so a naive "control" arm compared two
  identical runs.
- `build/` is gitignored, so `build/fidelity.json` is never committed; only
  `docs/FIDELITY.md` is. `docs/SURVEY.md` carries no version stamp and is
  presets-independent.
- `bump_version.py` runs AFTER artefact regeneration, so a commit ships an
  artefact stamped one version behind. Known and accepted.

## Timings (measured this session, not estimated)

- Full suite: **~6 min** (1626 passed, 2 skipped at `cd2db79`).
- `docs/FIDELITY.md` regeneration at `-t 60`: **~12 min**.
- A single-file `fidelity.py` run at `-t 60`: ~40 s.

## Environment

- Corpus: `C:/Users/mit/claude/c64server/SIDM2/SID/Hubbard_Rob` — 95 files, 83
  convert, 12 correctly refused (`UnsupportedSidError`).
- `python/tools/siddump-rt/siddump.exe` is **gitignored**; any clean export or
  fresh worktree must have it copied in first, or the harness silently measures
  only the single-speed files.
- GoatTracker sources: `C:/Users/mit/Downloads/GoatTracker_2.76/src`.
- `gh` is installed and authenticated as `MichaelTroelsen`; the repo has no
  issues or PRs.
- `graphify update` reports "No code-graph topology changes detected" when
  current; it warns that `python/tools/siddump-rt/cpu.c` is partially extracted
  (C syntax error at line 31), so C nodes there are incomplete.
</critical_context>

<current_state>

## Finalised

- **HEAD `cd2db79` (v0.5.409), pushed. Local and `origin/master` are level.
  Working tree CLEAN.**
- Three commits this session, all pushed: `8967b3f`, `ef7caee`, `cd2db79`.
- `.claude/tasks/runs.jsonl`: **189 lines**, 8 appended this session.
- Lock registry `.claude/tasks/serial.lock` is `[]`; the mutex directory
  `.claude/tasks/serial.lock.d` does not exist. **Nothing is held.**
- `graphify-out/` refreshed after the final commit.
- Both agent worktrees from the second drain are MERGED — their content is in
  `cd2db79`, so those checkouts are redundant duplicates now.

## Draft / temporary / outside this repo

- **`.claude/tasks/whattask.json` is STALE** — `generated_from.head = ef7caee`
  against HEAD `cd2db79`, with 4 tasks it lists as open now `done`. It is
  committed in that stale form. Re-run `/whattask`.
- **`plugins/mit-setup/LOCKING.md` is uncommitted**, in the plugin marketplace
  repo outside this tree, carrying two independent edits (mine + an earlier
  session's).
- 51 registered worktrees, none pruned.
- Session scratchpad holds ~75 files including probe scripts, presets A/B
  copies and corpus exports — all disposable, and it is shared with delegated
  agents (see `<attempted_approaches>`).

## Open questions

1. **What gates the `--regrid` + `--no-test-restart` collision?** Necessary but
   not sufficient; four files carry both and are fine. Same question as
   `rikky-immunity-to-regrid-is-unexplained`.
2. **Three listening verdicts** (ACE_II ×2, Monty, Action Biker) — no
   measurement can settle any of them.
3. `claude-md-states-measured-numbers-in-the-present-tense` is `partial` by
   design: the cheaply checkable figures and every figure an open task's verify
   keys on are graded; the rest need corpus sweeps.

## Recommended next action

Run `/whattask` to refresh the stale plan, then take
`multiplier-is-chosen-from-subtune-0-but-belongs-to-the-subtune`.
</current_state>
