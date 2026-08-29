<original_task>
**Adopt the gate search result** — the tail of
`fidelity-better-has-no-gate-term` (`.claude/tasks/whattask.json`), whose
premise was false and whose real defect was fixed in v0.5.406. What remained
was to regenerate the artefacts against the adjudicated `presets.json`,
confirm the gate column moves on the files it should and nowhere else, and
commit.

This file is **state, not a knowledge store** — the design decision shipped in
v0.5.404. Durable facts belong in `CLAUDE.md`, which loads into every session;
the open-task list is `.claude/tasks/whattask.json`. What is here is what is
IN FLIGHT and would otherwise have to be re-derived.
</original_task>

<work_completed>
## Committed

- **v0.5.404 `8d45bdd`** — `whats-next.md` stops being a knowledge store.
- **v0.5.405 `9b939a6`** — the `MAX_PATTERNS` guard gets a corpus test;
  `melody`'s description gains what collapsing *hides*.
- **v0.5.406 `4d9d9f2`** — `HARD_RESTART_ENABLERS` (the search can now reach
  a pair), the `--fidelity` carry-forward fix, and a retraction of v0.5.403's
  false claim.
- **v0.5.407 (this commit)** — the adjudicated search result adopted:
  `presets.json`, the three hand adjudications in `python/presets.py`, the two
  test guards they require, and a regenerated `docs/FIDELITY.md`.

## What v0.5.407 contains

`presets.json` diff against the pre-search snapshot, adjudicated by hand:
**LOST 2 / GAINED 24 across 16 files / CHANGED 1**.

`FIDELITY_CONFIRMED` (three `no_test_restart` settings the fresh search drops
and should not have — the melody/pitch gain is siddump's artefact and the
`hold` loss is real): Arcade_Classics, Powerplay, Pygmies_Revenge.

`FIDELITY_VETOED` (ACE_II `hard_restart_frames`): +15.1 gate and nothing
worse, but it changes a `.sng` a listener approved. Withheld pending item 1
below. `max_hard_restart` is NOT vetoed — it was already in the approved
bytes, and a first version that vetoed it too changed the very file the entry
exists to protect.

## The regeneration, verified

`docs/FIDELITY.md` and `build/fidelity.json` regenerated at `-t 60` against
the adopted presets, then A/B'd against a snapshot of the previous run.

- **`output_sha` moved on exactly 17 files** — the 16 that gained a setting,
  plus `Dragons_Lair_Part_II` (documented LOST #1). Nothing else moved.
- **`melody`, `sequence`, `pitch` and both attack counts are identical to
  three decimals on all 16.** Only `gate` moves, which is the shape a
  hard-restart change is supposed to have.
- Largest gains: Thanatos 49.0 → 96.0, Las Vegas 51.7 → 91.2,
  Delta_Mix-E-Load_loader 59.6 → 93.6, Kings_of_the_Beach_intro 76.6 → 91.9,
  Ninja 50.1 → 74.7, Samantha_Fox_Strip_Poker 32.6 → 65.4.
  The four the previous session spot-measured by hand reproduce exactly.
- **One cell worse corpus-wide**: `Dragons_Lair_Part_II` `wave` 73.1 → 70.4,
  from the adjudicated `no_test_restart` loss, on a row that is a known
  harness artefact (melody 14%, 359 attacks against the original's 556).
- **`len`: zero breaches of the ±5 s rule**, measured on 6 of 83 rows both
  before and after — unchanged coverage, so nothing regressed.
</work_completed>

<work_remaining>
1. **`[user]` ACE_II carries TWO withheld gains awaiting one listening
   session** — `rest_envelope_silence` (+3 adsr, v0.5.394) and
   `hard_restart_frames` (+15.1 gate, v0.5.407). Both are recorded with their
   numbers, so the ask is one question rather than a re-measurement. Stage the
   pair with `listen.py`.
2. **`[subagent]` Add a CLAUDE.md line about the `cd X && …` short-circuit.**
   It has now bitten three times: twice in the previous session (the edit
   never ran and the following `pytest` passed against the unmodified file),
   once in this one (the whole `fidelity.py` regeneration silently did
   nothing, `cd: python: No such file or directory`, exit 1). The session cwd
   persists across Bash calls, so a `cd python` that succeeded once fails the
   next time. Use absolute paths, or assert the command ran.
3. **`[main]` `.claude/tasks/runs.jsonl` has no line for either half of this
   work.** Both halves were run directly rather than through `/runtask`, so
   the lock was claimed and released without a record. The lock registry
   (`.claude/tasks/serial.lock`) is empty; nothing is held.
</work_remaining>

<attempted_approaches>
- **`cd python && <cmd>` when the session cwd is already `python/`** — the
  `cd` fails, `&&` short-circuits, and the command reports exit 1 having done
  nothing. Third sighting. See item 2 above.
- **An A/B probe asserting `status == "ok"`** — the real value is
  `"measured"`, and the assertion is the only reason that surfaced instead of
  the probe silently comparing zero rows. Same class as the two probe failures
  CLAUDE.md records; the fix is that the probe asserts the columns and rows it
  claims to read, before reading them.
- **`gate` and the other columns in `build/fidelity.json` are fractions
  (0.0–1.0), not percentages** — the report prints percentages.
- **`build/` is gitignored**, so `build/fidelity.json` is not committed;
  only `docs/FIDELITY.md` is. `docs/SURVEY.md` carries no version stamp and is
  presets-independent, so it did not need regenerating for this change.
</attempted_approaches>

<critical_context>
Durable repo knowledge is in `CLAUDE.md` and is not repeated here.

- **`FIDELITY_CONFIRMED` / `FIDELITY_VETOED`** (`python/presets.py`) are the
  repo's mechanism for a setting the search gets wrong, and each entry says
  WHICH reason. `test_wave_program.py` pins `FIDELITY_VETOED` by whole-dict
  equality — adding an entry requires updating that assertion, deliberately.
- **A veto/confirmation may name only a searchable option.**
  `test_preset_passthrough.py` asserts `keys <= set(FIDELITY_TOGGLES)`,
  widened in v0.5.406 to `| {"hard_restart_frames"}` because the frame pass
  made it searchable.
- **The search's `base` excludes the per-song options** (`regrid`,
  `real_firstwave_instruments`, `pulse_phase`, `rest_envelope_silence`), so a
  setting the search measured was measured WITHOUT them. The 24 gains were
  spot-checked with full presets on 4 of the 16 files, and the regenerated
  report — which does use full presets — now confirms all 16.
- **A `--fidelity` search costs ~30 min**, not the ~10 an earlier note
  claimed; the joint frame pass tripled the integer-pass cost.
- Corpus: `C:/Users/mit/claude/c64server/SIDM2/SID/Hubbard_Rob` (95 files,
  83 convert). Full suite ~6 min. GoatTracker sources:
  `C:/Users/mit/Downloads/GoatTracker_2.76/src`.
</critical_context>

<current_state>
HEAD v0.5.407, everything above committed. Working tree clean.

**Verified before committing:** full suite green; the A/B above; all three
human approvals (ACE_II, Action_Biker, 5_Title_Tunes) HOLD by sha256.

**Open for the user:** the ACE_II listening question in item 1.
</current_state>
