<original_task>
Resume h2g work at HEAD `a5335f9` (v0.5.403).

**This file is not the open-task list and is not a knowledge store.**
`.claude/tasks/whattask.json` is the list — `/whattask` regenerates it,
`/whattask --dry-run` prints it without paying for a pass. The durable
knowledge is in `CLAUDE.md`, which is loaded into every session automatically
and is therefore the only place a fact cannot quietly rot.

What is left here is the one thing neither of those holds: what is IN FLIGHT
right now, and what a fresh session would otherwise have to re-derive about
the state of the tree.

This file has twice been read as an open backlog after its contents landed —
once for fifteen commits. If the section below is long, check it against
`git log` before believing a word of it.
</original_task>

<work_completed>
Nothing is in flight. The tree is clean at `a5335f9` and everything through
v0.5.403 is pushed.

The recent stretch, newest first — read `git log` for the rest:

- **v0.5.403** — `hard_restart_frames` is searchable, and the search still
  cannot select it: `fidelity_better` has no `gate` term, so a value worth
  gate 50→75% with every other column identical reads as a tie.
- **v0.5.402** — the outer-gate rescue spellings are anchored at the PSID play
  address. Zero corpus files move; the anchor is what makes them safe rather
  than lucky.
- **v0.5.401** — three unread speed gates (two zero-page spellings and a
  PAL/NTSC-selected reload). **The corpus now has ZERO files failing the ±5 s
  length rule**, from two.
- **v0.5.400** — W_A_R shipped 209 patterns into a 208-pattern format and
  nothing said so. melody 18.6 → 100%, attacks 327/327.
- **v0.5.397** — `--regrid`, for the fractional part of a row the tempo cannot
  express.
</work_completed>

<work_remaining>
**Read `.claude/tasks/whattask.json`.** It is generated, keyed to a commit, and
`/whattask --dry-run` prints it without regenerating.

At `a5335f9` it held 18 tasks, 10 ready. The two waiting on a human, which no
amount of work resolves:

- **`monty-firstwave-trade-needs-a-listen`** — Monty's
  `real_firstwave_instruments` [1..16] buys `hold` 0→88% and costs `pitch`
  (95→92). Three columns hang on which sounds closer.
- **`ace-ii-rest-envelope-awaits-a-listen`** — ACE_II measures adsr 93→96 with
  `rest_envelope_silence`, but its human approval pins the no-flag bytes.

The highest-value ready one is **`fidelity-better-has-no-gate-term`**: it is
the measured blocker for `hard_restart_frames`, and the common cause behind
three options (`silent_park`, `regrid`, `hard_restart_frames`) that all sit
outside the preset search for the same reason.
</work_remaining>

<attempted_approaches>
Refutations live in `CLAUDE.md` beside the mechanisms they refute, because
that is where someone about to repeat one will be reading. The ones from the
most recent work, so a fresh session does not re-run them:

- **Three dead hypotheses for `--regrid`'s melody collapse** on One_on_One
  (−37pp) and Sanxion (−20pp): funktempo restore value (Monty has tempo 2 and
  *gains*), over-delivery (delivered/owed is 1.08/1.01/1.07/0.93 across gainers
  and losers alike), and slide-heaviness (Rikky carries 5982 slides and gains).
  The surviving symptom is a per-voice **collapsed-sequence lengthening**, and
  any candidate must also explain why Rikky is unaffected.
- **`greloc.c` is innocent of W_A_R's tempo loss.** Lines 1823-1830 keep a
  global tempo and merely decrement it. Two sessions pointed there; the cause
  was a pattern-count overrun.
- **Forcing `tempo=N` is not a valid A/B lever for a rate question.** It skips
  the branch assigning `multiplier`, leaving every per-call rate at the −S1
  scaling. It read melody 0.0% and that was the probe breaking.
</attempted_approaches>

<critical_context>
Everything durable that used to live here is now in `CLAUDE.md` — the
verification patterns, the gotchas, the two-genuinely-different-cases note.
It is loaded automatically every session, which this file is not.

## Environment
- Corpus: `C:/Users/mit/claude/c64server/SIDM2/SID/Hubbard_Rob` (95 files, 83 convert)
- `sidplayfp`: `C:/Users/mit/Downloads/sidplayfp-2.15.2-32bit-mmx/sidplayfp.exe`
- GoatTracker sources: `C:/Users/mit/Downloads/GoatTracker_2.76/src` — this is
  where `gplay.c`, `greloc.c` and `gcommon.h` are read from, and
  `goattracker2/src` has `player.s`, the PACKED player, which is the one that
  ships and which disagrees with `gplay.c` about the first call.
- `build/` and `graphify-out/` are gitignored. 12 CPUs. Full suite ≈ 5m45s.
- Locking: `serial.lock` + `serial.lock.d` mutex; `.tmp` + `mv -f`, never
  truncate; a helper that records its own pid reaps its own live records, so
  record `null`.
</critical_context>

<current_state>
Clean at `a5335f9` (v0.5.403), pushed, `git status --porcelain` empty.
Suite 1615 passed / 2 skipped. All three human approvals (ACE_II,
Action_Biker, 5_Title_Tunes) verify HOLDS by sha256.

Artefacts are current as of v0.5.401's conversions. `presets.json` is
unchanged since v0.5.401 — v0.5.402 and v0.5.403 moved no conversion bytes.

The open list is `.claude/tasks/whattask.json`. This file is state, not a queue.
</current_state>
