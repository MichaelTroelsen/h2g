<original_task>
Drive the open-task backlog of the H2G repo (VB6 -> Python port converting Rob
Hubbard `.SID` files to GoatTracker `.sng`), one task per iteration, with every
claim measured rather than asserted.

The session was driven by repeated `/loop N /runtask next` series and two
`/mit-setup:runqueue` drains, interleaved with `/mit-setup:whattask` plan
regeneration. The user made every publish decision themselves ("commit this"
x8, "push it" x2). No task command ever commits, merges, pushes or branches --
that is the user's, deliberately, and it was honoured throughout.

**A NOTE ON THIS FILE'S SCOPE.** v0.5.404 established that `whats-next.md` is
STATE, not a knowledge store. Durable facts belong in `CLAUDE.md` (loaded every
session), the open-task list is `.claude/tasks/whattask.json`, and the run
history is `.claude/tasks/runs.jsonl` (259 lines). This document POINTS AT those
rather than copying them; duplicated prose is what drifts. The previous
`whats-next.md` was declared spent at v0.5.426 and this replaces it.
</original_task>

<work_completed>

## Ten commits, v0.5.424 through v0.5.433

Four are UNPUSHED (see `<current_state>`). Every one carries its evidence in the
commit message; `git log` is the authority, not this summary.

    d3d7e3f  v0.5.433  --force-park declines a subtune whose voices do not end together
    2367f03  v0.5.432  the report's shortening clause is read off the data, not asserted
    8bff6bc  v0.5.431  --force-park ends Confuzion, the corpus's last length failure
    8a9ba0d  v0.5.430  a quarter of the preset search is pruned, two corpus invariants get tests
    9b382b9  v0.5.429  two option docs corrected on measurement, a pruning claim retracted
    82e2d48  v0.5.428  the 5 Title Tunes adsr attribution is retracted
    6c99816  v0.5.427  Powerplay's --regrid loss is 94% a naming artefact
    c9fa41a  v0.5.426  5 Title Tunes fully attributed
    987a254  v0.5.425  no_hard_restart moves bytes and no column can see it
    25ae324  v0.5.424  Bangkok's no-instrument gate settled by patching the file

## Conversion behaviour that changed (two commits only)

**`--force-park` (v0.5.431, `python/h2g/tracks.py`)** -- parks every voice on the
silent pattern even where the restart is ALREADY legal. `--silent-park` acts only
on an out-of-range restart, which `convert_tracks` writes only for Hubbard's
`$FE`; a tune that ends and never says so keeps a legal restart 0 and plays
forever. Confuzion's track region is six bytes containing **no `$FE` at all**.

  * Confuzion `len` **294.92 s -> 0.12 s**, with melody 1.0, sequence 1.0,
    pitch 1.0, gate 0.7850, adsr 0.2194, wave 0.9631 and attacks 298/298 all
    IDENTICAL between the arms -- the shape a pure ending fix must have.
  * Corpus byte-hash: **MOVED 1 (Confuzion)**. Forced on everywhere it reaches
    **73 of 83**, which is why it is per song.
  * Adopted in `presets.json` for Confuzion only. `docs/FIDELITY.md` regenerated;
    its summary now states NO file breaches the +-5 s rule.

**The `voices_end_together` guard (v0.5.433, same file)** -- v0.5.431 shipped
`--force-park` with its safety condition documented and UNCHECKED. Censused:
**76 of 237 subtunes across 28 files (32%)** have voices that do not end
together, so parking would silence the short voice early. Now declined per
SUBTUNE. Corpus byte-hash **MOVED 0** (Confuzion's one subtune is safe).

## Search, harness and documentation changes

  * **`presets._redundant_combination` (v0.5.430)** -- skips the 32 of 127
    combinations setting both `max_hard_restart` and `wide_hard_restart`.
    Measured both ways: with max forced ON, `wide` changes bytes on **0 of 83**;
    with max OFF, on **36 of 83**. Byte-identical to a combination still
    visited, so the search result cannot change. A quarter of the walk.
  * **`fidelity.shortening_fate` (v0.5.432)** -- the report used to assert of
    every window-shortened row that "the shipped `.sng` still plays forever".
    True while the only repair was restart-at-0, false once one is parked. Now
    read off `length_bounded`.
  * **`sound_runs` docstring (v0.5.430)** -- carried the PRE-v0.5.410 census
    (415 instruments) that `--hold-census` had superseded. Replaced with the
    re-measured table, old figures named as superseded.
  * **README + `apply_initial_instruments` docstring (v0.5.429)** -- both said
    Delta was `--initial-instrument`'s beneficiary. Delta's voices now read
    99.4/99.9/99.9 WITHOUT it; forced on, voice 2 goes 99.9% -> 0.5% with 1488
    noise frames against an original with none. The option has no measured
    beneficiary. Also records that the hazard's criterion is the EMITTED subtune
    count, not the header's (Delta declares 16, emits 1).
  * **README `--no-hard-restart` (v0.5.429)** -- it changes the conversion on
    **83 of 83** files and no column reads it on the three examined.

## Tests added (9, suite 1657 -> 1666)

    test_pack_subtune.py    no corpus file packs for a subtune it does not start on
                            every derivation site agrees on every corpus file
    test_presets.py         the only pruned combination is wide under max
                            no combination without max is pruned
    test_original_ended.py  the shortening clause reads whether the file stops
    test_legal_restart.py   force_park parks a track whose restart is already legal
                            force_park needs the pattern table
                            force_park declines a subtune whose voices differ
                            the end-together test is taken before anything is parked
                            voice_rows counts rows not orderlist entries

## Measurements and findings worth keeping (all in runs.jsonl)

  * **Powerplay's `--regrid` loss is 94% a naming artefact.** Its whole -2.88pp
    is seven attacks on voice 0, all within 0.13 semitones of the original.
    Per pitch the no-regrid arm sits **+0.38 st** from the original and the
    regrid arm **+0.12 st** -- the arm we ship is three times further away and
    scores better, because a quarter-tone drop crosses a naming boundary. The
    refusal recorded at v0.5.412 rests on that.
  * **The pre-instrument discriminator, by ablation.** NOPing Bangkok's `$802A`
    makes voice 0 keep `$41` and attack at frame 1 instead of 2145; NOPing
    Delta's counterpart `$C032` changes nothing. Ground truth for all **44
    corpus files carrying the idiom**: **20 clear / 24 do not**, agreeing
    **3 of 3** with the independent pre-instrument census.
  * **Bangkok's pre-instrument silence is the TEST BIT `$08`**, held 1949 of
    2145 frames -- not `$00`, and `$41 AND anything` cannot be `$08`.
  * **No corpus file packs for a subtune it does not start on** (0 of 83), and
    0 ship a multiplier differing from the recommendation. The task claiming
    otherwise was backwards.
  * **14 rows carry a `length_delta` and `length_bounded` is false on all 14** --
    every measurable conversion stops. 69 rows have an original that never ends
    even at 10x the window.
  * **`hold`'s fetch deficit is refused with its reason**: the lost frame is
    Goattracker's own next-note fetch (gplay.c:905), not anything this converter
    writes. `--no-test-restart` removes it and costs melody -26.3pp over 68 files.

## Seven of my own published claims retracted

Listed because each is greppable from its own words and a reader will otherwise
trust the older record:

  1. v0.5.426's "the 932 gated-ON adsr frames are cut_release's residual" -- the
     original's gate is OFF on all 3742; the 937 are the gate surplus seen
     through another register, checked frame by frame.
  2. v0.5.426's retraction of the 932/935 coincidence as "chance" -- they are
     the same frames.
  3. v0.5.426's "$C032 is inside the PSID header" -- `to_offset` maps the header
     BELOW `load_addr`; Delta's strings are at `$BF98-$BFF7`.
  4. v0.5.426's "with no_hard_restart set the hard-restart axes are byte-level
     no-ops" -- generalised from ONE file; `hard_restart_frames=8` moves 15 of
     83 and `wide_hard_restart` 14 of 83.
  5. v0.5.433's "the INIT clear loop" -- init reaches that store on **0 of 20**
     files; it is on the play path.
  6. "clears the cell" throughout -- the value is `$08`, not `$00`.
  7. The Bangkok idiom's address: `$8539` was a raw search INDEX printed as an
     address; it is at **`$84BD`** with its store at `$84C3`.

## Plan regenerated once

`/mit-setup:whattask` at `c9fa41a` -- 27 tasks, 15 closed, 12 ready. Two verify
strings were CORRECTED rather than carried (`rikky`'s named a dead candidate as
untested; `a-note-before`'s carried three dead static readings).
</work_completed>

<work_remaining>

## 0. FIRST: regenerate the plan

`.claude/tasks/whattask.json` is stamped `c9fa41a`; HEAD is `d3d7e3f`. **7 of its
27 tasks are now `done`**, and `runs.jsonl` carries opened ids that are not in it
(including `force-park-has-no-voices-end-together-check...`, which was run
OFF-PLAN and is now done). Run `/mit-setup:whattask` before another drain.

## 1. `[main]` The pre-instrument task -- SHIP THE DATA TABLE

`a-note-before-its-voices-first-instrument-must-not-sound-on-bangkok-but-must-on-delta`
was run FOUR times this session and is `partial`. The diagnosis is finished; only
the emitter remains, and the route is now a recommendation rather than an open
question.

**Do NOT try to derive the flag again.** Three routes are refuted, each scored
against the same 44-file ablation ground truth (see `<attempted_approaches>`).
Ship the 20/24 split as a DATA TABLE keyed by file, which is what
`ENVELOPE_CUT_SHAPES` and the gate spellings already are in spirit. Regenerate
the ground truth with the ablation rather than trusting the scratchpad JSON --
44 files x 2 traces at `-t 30` is a few minutes and is cheap enough to be a test.

Then: a note before its voice's first instrument must not sound on the 20, and
Delta's 8 must stay exact. Expected reach -- Bangkok 20 notes, Dragons_Lair 32
(subtunes 5 and 6, untraced), Gremlins 1. Closes `bangkok-knights-voice-0-...`
and `bangkok-voice-0-orderlist-...` behind it. Verify: Bangkok voice 0 >= 0.96
ratio under `--diagnose` with voices 1 and 2 unmoved, a test that fails with only
the call site reverted, and a byte-hash naming exactly the files that move.

## 2. `[user]` Five listening and adoption decisions

None is settleable by measurement. **The A/B server is NOT running** -- it was
killed mid-session and the user asked for it once already.

  * `ace-ii-has-two-withheld-gains-awaiting-one-listen`
  * `monty-firstwave-trade-needs-a-listen` (blocks `firstwave-set-across-...`)
  * `action-biker-subtune-pairing-needs-an-ear`
  * `pandora-regresses-under-the-two-sided-attack-guard` -- adoption call
  * `regrid-is-not-in-fidelity-toggles-...` -- cost decision
  * NEW: **should Powerplay's `--regrid` refusal be reversed?** Its -2.87pp is
    now known to be 94% a naming artefact of a pitch that moved TOWARD the
    original. `presets.json` still records `regrid: false`.

## 3. `[main]` `monty-drums-play-four-octaves-too-low`

The defect MOVED since todo.md was written. Voice 2 is now 179 of 209 frames at
the right pitch (entry 79); **voice 1 carries the mechanism now** -- 140 frames
at +7.16 st and 70 at -7.84 st, only 121 correct. Aim at voice 1 (210 wrong
frames), not voice 2 (22). todo.md's entry is stale in its numbers and names the
wrong voice; it was NOT edited (not in that task's `touches`).

## 4. `[main]` `commando-voice-1-plays-g-sharp-7`

One well-posed question left: what does the player do with a note byte for
RECORD 4? The 50 clamped `$68` bytes are confirmed from the converter's own
reader; the player's 96-entry table gives `$0000` for index 104 while the
original sounds index 71. Transposes are ruled out (nine empty maps) and the
command-byte reading is inverted by ADSR attribution. **Constraint the task never
stated: Commando is the byte-exact fixture.**

## 5. `[main]` Smaller, well-specified

  * `hard-restart-frames-is-not-searchable` -- still nothing scores it.
  * `action-bikers-fidelity-is-not-99-percent` -- `gate` 72% / `wave` 97%,
    localised to voice 2; its adsr is a REAL envelope defect (4631 both-gates-on
    frames), not a gate artefact.
  * `convert-through-preset-opts-and-the-harness-produce-different-bytes` --
    opened and untouched; see `<critical_context>`, it deserves a session.
</work_remaining>

<attempted_approaches>

## Refuted for the pre-instrument discriminator (do not repeat)

  1. **Four cheap static rules**, scored against the 44-file ground truth: cell
     file image == 0 catches 4/20 with 14 false positives; store within `$30` of
     `load_addr` catches 14/20 with 8 false positives; `$40` and `$50` are worse;
     store count useless. Offsets overlap almost completely.
  2. **An init interpreter** (~130 lines, decodes 42 of 44 init blocks). It is a
     CONSTANT CLASSIFIER -- predicts "no clear" for everything, and its 23/42
     "accuracy" is just the files whose truth is False. Its real contribution
     was reachability: init reaches the store on **0 of 20**.
  3. **A play interpreter** (~200 lines). 6/20 decided, 24 undecidable. Two
     structural blockers: an unsupported addressing mode, and **at least six
     files install their own IRQ and carry no `playAddress` at all** -- no
     interpreter can reach the store on those, however complete.
  4. Earlier and already recorded: the guard-byte reading (bit 6 of a run-once
     latch), refuted by ablation; the cell's file image (`$41` on both
     endpoints).

## Refuted elsewhere this session

  * **`--rest-envelope-silence`-style widening for 5_Title_Tunes' adsr** -- there
    is no `cut_release` residual there at all; the deficit is the gate surplus.
  * **The hard-restart family for Action_Biker's gate** -- seven arms, all
    identical to four decimals.
  * **Ties as `--regrid`'s damage mechanism** -- impossible on Powerplay, whose
    mid-glide share is 0.0%.
  * **Fifteen candidates for Rikky's `--regrid` immunity**, the last being the
    persistent pitch offset, which looked decisive on a BIASED SUBSET (all
    damaged voices plus three arbitrary immune ones) and overlaps totally across
    all 21 voices.

## Probe errors made and corrected (each cost a run)

  * **Omitted the frequency-table calibration** -- read Powerplay at 22% where
    the harness reads 99%. `engine_freq_table`'s docstring names Powerplay as
    its worked example and says which table you pick "decides whether a row
    reads 99% or 12%".
  * **Traced OUR side at subtune 0** while `_measure` resolves the pairing with
    `--search-subtunes`. Produced gate 0.28 / adsr 0.00 against the artefact's
    0.72 / 0.69 and I was one step from filing a severe live regression.
  * **A guard evaluated per TRACK inside the parking loop** -- parking appends a
    position, so the group became unequal and the guard declined the voices it
    had just unbalanced. Every test still passed; the sha caught it.
  * **`-x` on a whole test file as a non-vacuousness check** -- it stopped on a
    PRE-EXISTING test and said nothing about the ones being proved.
  * **A hand-edit of `presets.json` at `indent=1`** -- `test_presets_format.py`
    requires byte-identity with `json.dumps(doc, indent=2)`.
  * **Heredoc mangling** (`\\n` collapsing, embedded quotes) broke three scripted
    edits. Asserts caught all three. Use the Write tool for anything long.
</attempted_approaches>

<critical_context>

## The rule this session paid for repeatedly

**An ablation tells you THAT a byte matters, never WHERE it runs and never WHAT
it writes.** Three labels in a row were wrong while every measurement held: the
guard byte, "the init clear loop", "clears the cell". Both corrections are cheap
-- reachability is a set of PCs, the value is one memory read -- and both must be
instrumented in the same run as the ablation.

**Recompute a number a task tells you to trust.** Six task figures were stale or
wrong. The sharpest case: a record saying work was "NOT PUSHED, NOT MERGED" on a
branch -- read today that invites a cherry-pick onto a tree that already has the
work. It had landed rebased; `find_gate_hold` is in master and returns True on
68 of 83 exactly as recorded. **A record claiming work is stranded is the most
urgent kind to re-verify, not the least.**

**A verify string is load-bearing and nothing re-checks one.** Three plan
verifies were stale; `/whattask` regeneration carries the old text forward rather
than re-deriving it from the newest record. Opened as
`whattask-regeneration-carries-stale-verify-text-forward-instead-of-re-deriving-it`.

## An unexplained discrepancy that touches a technique used all session

`convert()` called with `fidelity._preset_opts(doc, name)` gives Action_Biker sha
**3554a89bc1c0**; the harness's own row for the same file at the same settings
records **51256f225818**. My path disagrees with the artefact on **all 83** files.

Every byte-hash conclusion this session is DIFFERENTIAL -- arm A against arm B
through the same path -- so a systematic offset cancels and they stand. What is
NOT valid is comparing a sha from that path against one the harness recorded.
v0.5.425's record quotes 3554a89bc1c0 as Action_Biker's shipped sha, which by
this measurement is not what the harness converts. Opened as its own task.

## Non-vacuousness is per test, not per change

Repeatedly this session a change had two or three tests and only ONE was
non-vacuous for it. State which, and prove each against the defect it guards:
`--force-park`'s pattern-table guard passes under the call-site revert (it
declines for a different reason); the wide-under-max converse guard holds
trivially when nothing is pruned; a derivation deliberately computed FROM a
predicate adapts instead of detecting.

## Environment and conventions

  * Corpus: `C:/Users/mit/claude/c64server/SIDM2/SID/Hubbard_Rob`, 95 files,
    83 convertible. Override with `H2G_CORPUS`.
  * Suite: `python -m pytest tests/ -q` from `python/` -- ~6 minutes, 1666
    passed / 2 skipped at `d3d7e3f`.
  * `docs/FIDELITY.md` regeneration: ~12 minutes at `-t 60`. It stamps the
    version it was generated at, which is one behind the commit because
    `bump_version.py` runs after -- the ordering CLAUDE.md records.
  * **`cd python && <cmd>` short-circuits** because the Bash cwd persists. Use
    absolute paths. Hit ~4 times.
  * Scratchpad probes are prefixed per task (`nb3_`, `fp1_`, `cz2_`) because
    the scratchpad is SHARED between agents even when worktrees are not.
  * `graphify update .` was run once, at the `/whattask` pass; the graph is
    stale again by ten commits.
</critical_context>

<current_state>

## Repository

`HEAD = d3d7e3f` (v0.5.433), branch `master`, **working tree CLEAN**.

**4 commits are UNPUSHED**: `8a9ba0d`, `8bff6bc`, `2367f03`, `d3d7e3f`.
`origin/master` is at `9b382b9`. Pushing is the user's call and has not been
asked for since v0.5.429.

Suite green (1666 passed, 2 skipped). `docs/FIDELITY.md` and
`build/fidelity.json` are CURRENT -- regenerated at v0.5.432 and confirmed by
running the CLI on Action_Biker and reproducing the artefact digit for digit.
`presets.json` is current and carries Confuzion's `force_park: true`.

## Generated artefacts

  * `docs/FIDELITY.md` -- current, stamped 0.5.432.
  * `build/fidelity.json` -- current, gitignored.
  * `presets.json` -- current; the only hand-recorded change this session is
    Confuzion's `force_park`.
  * `docs/SURVEY.md`, `docs/SUBTUNES.md` -- NOT regenerated this session and not
    known stale (no detection change landed).
  * `graphify-out/` -- stale by ten commits.

## Task machinery

  * `.claude/tasks/runs.jsonl` -- 259 lines, append-only, committed.
  * `.claude/tasks/whattask.json` -- **STALE**, stamped `c9fa41a`, 7 of 27 tasks
    done, missing several opened ids. Byte-identical to how the last `/whattask`
    wrote it (no drain ever patched it).
  * `.claude/tasks/serial.lock` -- `[]`, no holders, no mutex directory.
  * `.claude/tasks/decisions.jsonl` -- does not exist; no `/runhuman` has run.

## Running processes

  * **The A/B listening server is NOT running.** It was killed mid-session
    (background task `b9c954u4j`); port 8000 does not respond. The staged pages
    are on disk under `build/`. The user asked for it once and will need it for
    the five listening decisions.
  * Three orphaned `tail -f` processes from PREVIOUS sessions survive; killing
    them is a `requires-user` task, deliberately not done.

## Open questions

  * Should Powerplay's `--regrid` refusal be reversed given its loss is 94%
    naming artefact? (user's call, not recorded anywhere but runs.jsonl)
  * Data table vs. derived flag for the pre-instrument rule -- recommendation
    made, decision not taken.
  * Why do `convert()` via `_preset_opts` and the harness produce different
    bytes on all 83 files?
</current_state>
