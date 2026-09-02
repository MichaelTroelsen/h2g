<original_task>
Drive the open-task backlog of the H2G repo (VB6 -> Python port converting Rob
Hubbard `.SID` files to GoatTracker `.sng`), with every claim measured rather
than asserted.

The session ran as a sequence of user-issued commands rather than one brief:
`/mit-setup:whattask` x3 (plan regenerations), `/mit-setup:runqueue` x2,
`/mit-setup:runtask next` x4, `/loop /runtask next` x2, plus one design
excursion (`superpowers:brainstorming` -> `writing-plans`) that produced the
A/B automation spec and plan committed at `fc931c1`. The user made every
publish decision themselves ("commit this and push" x5). No task command ever
commits, merges, pushes or branches -- that is the user's, deliberately, and
it was honoured throughout.

**THIS FILE IS STATE, NOT A KNOWLEDGE STORE** (the rule the previous handoff
set, still binding). Durable facts belong in `CLAUDE.md`, the open-task list
is `.claude/tasks/whattask.json`, the run history is
`.claude/tasks/runs.jsonl` (304 lines). This document POINTS AT those rather
than copying them; duplicated prose is what drifts. Read the LAST line per id
in runs.jsonl -- it is append-only and several ids have three or four lines.
</original_task>

<work_completed>
**FIVE COMMITS, `fc931c1..6441cf3` (v0.5.447 - v0.5.451), ALL PUSHED.**
`git log --oneline be759f0..HEAD` is the authoritative list; each message
carries its own evidence and is written to be read years later.

**THE HEADLINE: SIX FILES THAT HAD NEVER CONVERTED NOW DO.** Go_Go_Dash,
Lion_Heart, Pacific_Coast, Radio_ACE, Sun_Never_Shines and
Lakers_vs_Celtics. `docs/SURVEY.md` goes **80/95 -> 86/95**. This took three
commits and is the largest single detection gain in the backlog.

  * `bd28b6a` v0.5.448 -- Commando's octave is a waveform byte; the five-file
    build is read for the first time.
  * `bdb20c1` v0.5.449 -- `_detect_interleaved_classic`: their tables are
    found (interleaved, init-written) and their track reader decoded.
  * `2ebf1a4` v0.5.450 -- the `ilv` pattern grammar; all six convert.
  * `6441cf3` v0.5.451 -- presets entries and FIDELITY rows for the six.

**THE COMMANDO DIAGNOSIS (bd28b6a), closed after five prior partial attempts.**
Note byte `$68` = 104 overruns the player's 96-entry frequency table; the
player then reads `$54F8`/`$54F9` -- voices 0 and 1's STORED WAVEFORM bytes --
as the frequency. Instruments carrying `$41` reduce to table entry 71 and the
one carrying `$21` to entry 59, which is exactly the original's measured 95/1
split, and they are an octave apart only because `$41` is about twice `$21`.
The prediction was made from the instrument table BEFORE being checked against
the trace. Our side's "index 92" is `patterns.py:495` clamping every note byte
>= 92 to `GT_LASTNOTE`.

**THE INTERLEAVED ENGINE, three commits' worth.** `DIGI_TRACKS` and
`DIGI_PATTERN` already matched all six files; one line rejected them
(`pattern != tracks + DIGI_TRACK_TO_PATTERN`, an adjacency that is a property
of the digi BUILD rather than the engine). `_detect_interleaved_classic` takes
only the interleaved-TABLE half, gated `not engine and not digi` and on the
classic chains having found nothing. The track reader is version 0's shape
with `$FD nn` as a two-byte TRANSPOSE where the others have `$FE`. The pattern
grammar is a fourth dialect, `pattern_dialect "ilv"`, fully documented in
`patterns.py`.

**THE A/B AUTOMATION DESIGN (fc931c1).** `docs/superpowers/specs/
2026-09-01-ab-fidelity-automation-design.md` and `.../plans/
2026-09-01-ab-fidelity-automation.md` -- a nine-task plan for a rendered-audio
fidelity measure (`aud`/`loud`), approvals that survive a change by
measurement, a preset search that respects approvals computationally, and a
ranked queue of causes. **NOT STARTED.** Its Task 1 (`sound.py` core, synthetic
tests only) needs no corpus and is the natural first delegation.

**THREE PLAN REGENERATIONS**, at `80456df`, `bd28b6a` and `bdb20c1`. Each
fixed `touches` defects that had blocked a task; see <attempted_approaches>.

**THE UNCOMMITTED WORK** (the last `/runqueue` cycle, task
`hard-restart-frames-is-not-searchable`, recorded `done`):
`python/presets.py` gains `_hard_restart_grid_inert`, a pre-check that skips
the nine-point hard-restart pass where no point moves a byte -- **26 of 89
files, 234 of 801 grid points**, measured. `python/tests/
test_hard_restart_grid.py` is new (7 tests). `python/tests/
test_preset_passthrough.py` has two assertions amended.

Suite went **1695 -> 1763 passed, 2 skipped** across the session, by exactly
the new tests. `Commando.sng` byte-exactness held throughout.
</work_completed>

<work_remaining>
## 0. FIRST: commit the tree, then regenerate the plan

The working tree holds the finished `hard-restart-frames` task (see
<current_state>). `.claude/tasks/whattask.json` is stamped `bdb20c1`; HEAD is
`6441cf3`. **Two of its 32 tasks are now `done` and still listed**
(`five-non-converting-files-...`, `hard-restart-frames-is-not-searchable`) and
**seven ids opened since are absent**. Run `/mit-setup:whattask` before another
drain.

One of those absent ids is already CLOSED by work that shipped:
`interleaved-classic-instrument-stride-is-16-in-the-player-and-8-in-detection`
was fixed inside `2ebf1a4` and has no `done` record. The regeneration should
close it rather than list it.

## 1. `[main]` The decision the last cycle surfaced

`a-corpus-fidelity-refresh-is-owed-and-would-move-six-old-songs-hard-restart-settings`.
A full `--fidelity` search was run and diffed but **NOT adopted**; the
candidate is at `C:/t/hr1_candidate.json`. Against the shipped presets, with
the carry applied, it moves six previously-searched songs on the hard-restart
axis (Knucklebusters, Mr_Meaner, Off_the_Cuff, Pandora, Shockway_Rider,
Spellbound) and gives the six new files their first-ever toggles. That is a
corpus-wide preset refresh; it wants its own decision, not a side effect.

## 2. `[main]` The six new files are not finished

* `seven-ilv-commands-are-parsed-for-length-and-dropped-and-nobody-knows-what-they-do`
  -- `$82 $83 $84 $86 $87 $88 $89` are consumed correctly and translated not at
  all. FIDELITY.md already quantifies the gap: all six read `slides 0/nnn`,
  `bend 0.00x`, `vib 0.00x` and zero filtered frames. They play the right notes
  with no pitch movement, no vibrato and no filter.
* `go-go-dash-drops-58-percent-of-its-attacks-and-its-duration-unit-is-3-75-frames`
  -- melody 36%, retrig 0.42, and `--pace` says **0% out, drift +0.00** so it is
  NOT tempo. Its speed gate reads 15/4 frames per duration unit, the only
  non-integer of the six and the only `-S4` file: the `--regrid` family.
* Nobody has LISTENED to any of the six.

## 3. `[main]/[subagent]` The A/B automation plan

Nine tasks in `docs/superpowers/plans/2026-09-01-ab-fidelity-automation.md`,
in rollout order, none started. Tasks 1, 2, 4, 5, 8 are subagent-shaped.

## 4. `[user]` Eleven decisions

Unchanged from the previous handoff except that ONE is now fully prepared:
`powerplay-regrid-refusal-rests-on-a-naming-artefact-and-should-be-re-decided`
has its measurement complete -- **naming share 94% on 7 renames**, by
positional difflib with arm A's names substituted into arm B and re-scored;
2.71pp of the 2.88pp loss is recovered by repairing names alone. Its
`blocked_on` carries the figure and its method. It is a clean yes/no.

The three listening verdicts still share the same blocker: **the A/B server is
on port 8730** (`abpage.py --serve`), and its staged audio is stale, so
re-stage with `listen.py` first.
</work_remaining>

<attempted_approaches>
**THE SESSION'S RECURRING SHAPE: a plan defect, not a code defect.** FOUR
sightings of ONE class -- a `touches` list that does not cover what its own
`verify` requires -- and they cost three `/runtask` invocations:

  1. a verify demanding a corpus byte-hash with no scratch path declared;
  2. `r:docs/SURVEY.md` on a verify requiring that file's count to RISE;
  3. a verify requiring another task's `blocked_on` to change -- a
     `whattask.json` edit `/runtask` is forbidden to make;
  4. `five-non-converting-files` blocked because its remaining work was a
     pattern grammar and `python/h2g/patterns.py` was not granted.

(1) and (4) are the instructive pair: the path is implied by the WORK, not
written in the verify text, so a string scan cannot find it. All four are
recorded as defects (10)-(13) on
`whattask-regeneration-carries-stale-verify-text-forward-instead-of-re-deriving-it`.

**FIVE ERRORS OF MINE, ALL CAUGHT BY SOMETHING, recorded so they are not
repeated.**

  * **A version-chain block inserted mid-chain captured the NEXT block's
    body.** `detect.py`'s version chain threads `i` between a signature and
    its follow-on test; my `if i <= -1:` block landed between version 2's find
    and its `transpose_operand` test, and **Auf_Wiedersehen_Monty silently
    lost the flag and changed bytes**. The corpus byte-hash caught it (MOVED 7,
    one a converting file). Fixed by gating on the resolved
    `read_track_version == 0xFF` at the END of the chain.
  * **`not digi` is not the same as "the digi engine was not declined".**
    `engine=1` sets `digi = False` deliberately, so eight digi-only files fell
    through my new chain and got interleaved tables under the classic grammar
    -- a plausible wrong song.
    `test_engine_one_refuses_the_files_that_have_only_a_digi_player` failed,
    which is exactly what it exists for. Gate is now `not engine and not digi`.
  * **A flag cleared where the version is chosen was overwritten 116 lines
    later** by `_find_track_terminators`. `test_tracks.py`'s
    Knucklebusters/Rasputin/Tarzan population caught it.
  * **A byte-hash probe that did not exist reported success.** My first
    invocation printed `can't open file 'C:/t/ab_bytehash.py'` AND EXITED 0 --
    the script only ever lived inside the plan document. The replacement
    (`C:/t/fv2_bytehash.py`) refuses to report when more than 20 conversions
    error.
  * **I wrote 41/369 into a docstring before measuring it** (the real figures
    are 26/234). It stood about four minutes.

**THE DIFF THAT LIED, AND IT IS THE ONE MOST WORTH CARRYING.** I ran the
corpus `--fidelity` search to `-o C:/t/hr1_candidate.json` -- a path with NO
PREVIOUS FILE -- and the first diff said my change had destroyed 20 measured
settings. It had not: CLAUDE.md states that an output path with no previous
file drops the carried settings, and the 23 "changes" were exactly the
carry-forward set (`regrid` x12, `rest_envelope_silence` x4,
`real_firstwave_instruments` x2, `pulse_phase` x1, `force_park` x1).
**Anyone repeating this must write the search to a COPY of presets.json.**

**A HYPOTHESIS THAT LOOKED ALARMING AND WAS EXONERATED BY ONE QUERY.** After
the carry was applied, six previously-searched files still moved, all on the
hard-restart axis my pre-check guards. Rather than argue, I asked whether the
pre-check had fired on them: **four had LIVE grids** (the pass ran; the
pre-check did nothing), and the two that were skipped gained only
`max_hard_restart` -- which the boolean walk selects -- and gained **no
`hard_restart_frames`**, the one setting the frame pass writes. The direction
exonerates it too: a wrongly-skipped pass would LOSE settings and every
residual is a GAIN.

**TWO TESTS THAT WERE WRONG RATHER THAN THE CODE.** One expected instrument 5
where the fixture's `$80` operand is `$00` (so 0 + instr_base = 2). One
asserted on Commando, whose hard-restart grid is LIVE at the defaults, so it
**skipped itself and pinned nothing** -- rewritten to take files the census
actually finds inert. A green check that cannot fire is worse than none.

**ONE LOOP STOPPED DELIBERATELY.** `/loop /runtask next` was ended rather than
re-armed when the next task's verify would have run a corpus `--fidelity`
search and written `presets.json` and both fidelity artefacts against a tree
holding an uncommitted converter change that had just added six files to the
corpus. That is CLAUDE.md's "a run taken mid-edit records a state that never
existed". The blocker was a human action, not time, so re-arming would have
hit it again in twenty minutes.
</attempted_approaches>

<critical_context>
**THE `ilv` GRAMMAR IS DOCUMENTED IN `patterns.py` AND SHOULD BE READ THERE,
not re-derived.** Summary only: `$00-$5F` note (frequency-table index
directly), `$60` REST, `$80-$BF` command dispatched on the EXACT value,
`$C0-$FF` duration (low five bits, emits no row of its own), `$81` ends the
pattern. Operand counts are a TABLE (`ILV_COMMAND_OPERANDS`) rather than a
rule because one wrong count desynchronises everything after it. An
unrecognised `$80-$BF` returns None rather than skipping -- the player's own
dispatch would spin there, so a skip would invent music.

**HOW TO TELL A RIGHT GRAMMAR FROM AN ACCEPTED ONE.** The evidence that
settled `ilv` was structural, not a score: zero undecodable patterns (the
classic reading left 28 of Lion_Heart's 114), row counts landing on **33/49/65
-- 32+1, 48+1, 64+1, i.e. bar lengths**, note spans well inside the table, and
nothing clamped at `GT_LASTNOTE`. A wrong grammar does not produce bar-length
patterns. `test_interleaved_classic.py` asserts all four.

**THE CORPUS IS NOW 89 CONVERTING FILES, NOT 83.** Every figure in CLAUDE.md
computed over "83 converting" is stale by six. This already bit once: the
`hard-restart-frames` task carried "36 of 83 inert" and the measurement is
26 of 89 -- and **the gap is NOT the corpus**, it is that the old census asked
about the shipped preset while the pre-check asks about `out`, the boolean
winner the pass it guards actually runs from.

**THE BYTE-HASH IS STILL THE CHECK THAT SETTLES REACH**, and the working
recipe is `C:/t/fv2_bytehash.py`: `git archive HEAD` to a scratch dir, copy
the gitignored `siddump.exe` in, convert both sides through
`fidelity._preset_opts`, compare, and REFUSE to report if more than 20
conversions error.

**PROBES, all in `C:/t`, prefixed per task.** `fv2_dis.py` (disassemble ADDR
COUNT FILE) and `fv1_ptr.py` (a generic `LDA abs,X|Y / STA zp` pointer-table
finder) are the two worth keeping. `fv2_diffdet.py` diffs a file's whole
`Detection` against a clean export and is what found the Monty regression.
`hr1_census.py` measures the hard-restart grid split.

**THE CORPUS** is at `C:/Users/mit/claude/c64server/SIDM2/SID/Hubbard_Rob`,
95 files, 89 converting. Scratch is `C:/t`.

**THE A/B SERVER IS ON PORT 8730** (`abpage.py --serve`), not 8000, and its
staged audio is stale and correctly withheld -- re-stage with `listen.py`
first.

**LOCK DISCIPLINE WORKED AND SHOULD BE KEPT.** `.claude/tasks/serial.lock` is
`[]` and the mutex directory does not exist. Every claim/release went through
`mkdir .claude/tasks/serial.lock.d`, re-read the registry from disk inside the
hold, and wrote via `.tmp` + `os.replace`.
</critical_context>

<current_state>
**HEAD is `6441cf3` (v0.5.451). All five commits are pushed; `git log
@{u}..HEAD` is empty.**

**THE WORKING TREE HOLDS ONE FINISHED, UNCOMMITTED TASK** --
`hard-restart-frames-is-not-searchable`, recorded `done` in runs.jsonl:

    M python/presets.py                        (_hard_restart_grid_inert)
    M python/tests/test_preset_passthrough.py  (two assertions amended)
    ?? python/tests/test_hard_restart_grid.py  (new, 7 tests)
    M .claude/tasks/runs.jsonl                 (the run record)

Suite **1763 passed / 2 skipped** with those in place. `presets.json`,
`docs/FIDELITY.md` and `build/fidelity.json` are deliberately NOT modified by
it -- the `--fidelity` candidate it produced sits at `C:/t/hr1_candidate.json`
awaiting the refresh decision (work_remaining #1).

**Nothing is half-applied.** No source file carries an experiment; every
change in the tree belongs to that one task.

**`.claude/tasks/whattask.json` is stamped `bdb20c1` and is two commits and
seven ids behind** -- 32 tasks, 17 ready, 11 requires-user, and two of the 32
are now `done`. Regenerating it is step 0.

**Deliverable status.** Converter: six new conversions shipped and byte-hashed;
one pattern grammar, one detection chain, one track-reader version. Tooling:
a search pre-check (uncommitted). Docs: `SURVEY.md` at 86/95 and
`FIDELITY.md` covering 89 files, both committed. Design: the A/B automation
spec and nine-task plan committed and unstarted.

**Open questions nobody has answered.** Whether the six sound right (nobody
has listened). What the seven dropped `ilv` commands do. Whether the corpus
`--fidelity` refresh should be adopted. Whether Powerplay's `--regrid` refusal
should be reversed now that its 94% naming share is settled.
</current_state>
