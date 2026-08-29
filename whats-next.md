<original_task>
A second `/runqueue --until-blocked` drain at HEAD `ef7caee`, against the plan
`/whattask` regenerated there. Two cycles ran, both lanes used; this commit is
their merged result.

This file is **state, not a knowledge store** — the design decision shipped in
v0.5.404. Durable facts belong in `CLAUDE.md`, the open-task list is
`.claude/tasks/whattask.json`, and the run history is
`.claude/tasks/runs.jsonl`. What is here is what is IN FLIGHT.
</original_task>

<work_completed>
## Committed

- **v0.5.407 `8967b3f`** — the adjudicated gate search result adopted.
- **v0.5.408 `ef7caee`** — the first drain: four cycles.
- **v0.5.409 (this commit)** — the second drain: two cycles, four tasks.

## The drain

| cycle | lane | task | outcome |
| --- | --- | --- | --- |
| 5 | delegated | `not-measured-note-length-claim-is-stale-…` | done |
| 5 | delegated | `cd-then-heredoc-short-circuits-…` | done |
| 5 | main | `lock-records-with-a-null-pid-…` | done |
| 6 | main | `sanxion-regrid-collapse-has-a-second-per-call-pitch-source` | done |

## Cycle 6 retracts cycle 4, and that is the headline

v0.5.408 concluded "the two files do not share one cause" from a vibrato A/B.
**Wrong.** Turning `no_test_restart` off erases the collapse on both:

    Sanxion     -19.9pp -> +0.2pp    voice 2 collapsed 346 -> 343 (orig 344)
    One_on_One  -37.0pp -> +0.5pp    voice 3 collapsed 188 -> 186 (orig 186)

`slides`, `vibrato` and `two_stage` each leave Sanxion's figure unmoved to a
tenth of a point. Vibrato masks One_on_One's — a **co-factor**, not the cause,
and one A/B that removes a symptom is not an attribution.

The mechanism is the option's own documented behaviour: `--no-test-restart`
deletes the testbit frame, the only frame our conversions spend below `$10`,
and siddump needs one below `$10` to name an attack. It **owns frame 0**, and a
compensating row moves the boundary underneath it. Not a pitch generator at
all — two options contending for one frame.

**Necessary but not sufficient**, which is the open question and also the Rikky
question sharpened: six files carry `no_test_restart` and could take
`--regrid`; four are fine (Arcade_Classics, Rikky, Sigma_Seven, Wiz), two
collapse. All `-S1`; row counts interleave, so neither multiplier nor size is
the discriminator.

## Verification

- Suite **1626 passed, 2 skipped** — unchanged across the merge, because the
  delegated change added assertions inside an existing test rather than tests.
- **Corpus byte-hash 0 of 83 moved.**
- `docs/FIDELITY.md` regenerated (the report's own summary prose changed):
  **4 lines changed, ZERO table rows.**
- Non-vacuousness proven for both delegated changes by reverting the source;
  for the `NOT_MEASURED` one the failure output quotes the stale sentence
  verbatim, which confirms the diagnosis rather than a guess.
</work_completed>

<work_remaining>
1. **`[user]` Three listening verdicts are owed**, none of which any measurement
   can settle: ACE_II's two withheld gains (`hard_restart_frames` +15.1 gate,
   `rest_envelope_silence` +3 adsr), Monty's firstwave trade (hold 0→88% against
   pitch 95→92), and Action Biker's subtune pairing, whose converter fix landed
   but whose ear check was never retaken.
2. **`[main]` Nine tasks were waiting on this commit** because they read or
   regenerate through `python/fidelity.py`. With the tree coherent they are
   unblocked; `multiplier-is-chosen-from-subtune-0-but-belongs-to-the-subtune`
   is the one to take first, since it unblocks Kings of the Beach and must
   precede the other `presets.json` writers.
3. **`[main]` `--regrid` + `--no-test-restart` needs a guard or a documented
   incompatibility**, now that the collision is attributed. Note four files
   carry both happily, so a blanket veto would be wrong.
4. **`[main]` `build/instrmap` is stale again** — the dumps predate v0.5.407,
   which moved the bytes of 17 files. Second time this artefact has drifted.
5. **`[main]` 51 registered worktrees**, none prunable. NOTE the hazard found
   this drain: `rw:.claude/worktrees` collides with every delegated agent's own
   isolation worktree, so this task must never run beside a fan-out.
</work_remaining>

<attempted_approaches>
- **Two tooling findings, recorded in `runs.jsonl`, not yet fixed.**
  *Agent scratchpads are not isolated from the orchestrator's*: an agent's
  byte-hash probe and a full scratch export appeared in this session's
  scratchpad and the orchestrator's identically-purposed script had vanished.
  Two concurrent agents doing corpus work in one directory is the
  shared-fixed-filename failure this repo already fixed once inside
  `fidelity.py` (v0.5.66). *And the `serial.lock` null-pid fix has two obvious
  forms that are both wrong* — the writing shell's pid dies in milliseconds so
  every record becomes instantly reapable (worse than null, which fails safe),
  and a lookup by process name is useless because **13 `claude.exe` processes**
  were running at once. The parent-chain walk to the first `claude.exe`
  ancestor is the answer; it is now in the plugin's `LOCKING.md`, OUTSIDE this
  repo and not in this commit.
- **A scripted edit's assert fired on line endings**, not on content:
  `patterns.py` is CRLF and the search string used `\n`. Read in
  universal-newline mode and write in default text mode so the file's own
  endings round-trip.
- **A nested heredoc mangled a patch script's escapes** (`\r\n` became literal
  newlines). The repo's own rule covers it: put the script in a file with the
  Write tool and run `python <path>` — do not build one inside a heredoc.
- **`whattask.json`'s `external_locks` used to name the registry itself**
  (`.claude/tasks/serial.lock`), which exists permanently — read literally the
  queue had to stop every time. The `ef7caee` regeneration reduced it to the
  mutex directory alone.
- Three orphaned `tail -f` processes from PREVIOUS sessions are still running,
  one since Aug 22. Not this drain's children, so reported rather than killed.
</attempted_approaches>

<critical_context>
Durable repo knowledge is in `CLAUDE.md` and is not repeated here.

- **`regrid_tempos`' docstring is where the regrid findings live**, including
  the retraction of v0.5.408's reading — deliberately there rather than in a
  commit message, because the wrong sentence is the kind that gets quoted
  forward.
- **`NOT_MEASURED`'s note-length bullet now carries a retraction pin**: a test
  asserts the phrase "never as a duration" never returns.
- Corpus: `C:/Users/mit/claude/c64server/SIDM2/SID/Hubbard_Rob` (95 files,
  83 convert). Full suite ~6 min. `FIDELITY.md` regeneration ~12 min.
- Forcing an option for an A/B means writing a patched `presets.json` copy
  OUTSIDE the repo and passing `--presets`; `fidelity.py` has no per-option
  flags. Check the option is actually ON in the shipped entry first — Rikky
  already ships `regrid: true`, so a naive "control" arm compares two
  identical runs.
</critical_context>

<current_state>
HEAD v0.5.409, everything above committed. Working tree clean, and both agent
worktrees are merged — their content is in this commit, so those two
checkouts are now redundant.

The lock registry (`.claude/tasks/serial.lock`) is `[]` and the mutex
directory is absent; nothing is held.

One change remains UNCOMMITTED and OUTSIDE this repo: `LOCKING.md` in
`C:/Users/mit/.claude/plugins/marketplaces/mit-claude-setup`, which also
carries a pre-existing uncommitted edit about `refs/stash` being shared
across worktrees.
</current_state>
