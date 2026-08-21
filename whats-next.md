<original_task>
Drive this repo's task queue with the mit-setup plugin commands, in the order
the user issued them:

  /whattask            regenerate the open-task list with a model and execution
                       mode per task, as prose plus .claude/tasks/whattask.json
  /runbatch  x2        run several eligible `subtask` records as one Workflow
  /runqueue  x3        run both lanes at once -- delegable tasks fanned out to
                       agents, one `main` task in this session beside them
  "merge" / "commit and push"  at the user's direction, repeatedly
  "regenerate the artefacts"
  "run the fidelity search" -> "adopt if it gains" -> "adopt just the
                       W_A_R_Preview gain, keep Delta as shipped"

No converter feature was requested directly. The scope is the queue machinery
and whatever the queue surfaced. The session ran from v0.5.331 to v0.5.343.

THIS FILE WAS REWRITTEN WHOLE. Its previous 122 KB covered runs one to seven
and was spent -- every item in its work_remaining was closed or superseded and
its narrative stopped around v0.5.325. Recover it with
`git show 5b4581a:whats-next.md` if any of that history is wanted.
</original_task>

<work_completed>

## Headline

Twelve branches merged, five artefacts regenerated twice, suite 1239 -> 1353,
and the corpus's vibrato shortfall cut from 102 instruments to 80. Master went
0725f71 -> 5b4581a and every commit is pushed to
github.com/MichaelTroelsen/h2g.

## Commits, in order

    1fbb1ac a7ee019 1e534e0   instrmap/songview de-duplication (pre-existing,
                              pushed for the first time this session)
    b670faa  v0.5.332  the eight-task batch recorded, plan regenerated
    d3c84b6  v0.5.333  plan regenerated; the ready pool is one complete
                       conflict graph
    eb71f82 5176a07 c01ca98  v0.5.334  the two subtune bounds compose
    8994fe9  the two fidelity-harness branches
    35b87a5  the SongSpeeds bound and the C64ME regression test
    fd9065c 2cdc3f6 699b745  v0.5.335  the four owed merges land
    bf03e52 ee2a717 db4f5d5 c6119ab 386e746 d312ff0 62403c9 0ae00a6 a31dc31
             v0.5.336  the six batch branches land; the wavetable right byte is
                       the packer's inverse
    990582a  v0.5.337  the artefacts regenerated; passthrough guard re-armed
    b1470eb ce00467 bde94cd dd1818d 2c7f317  the FIDELITY.md stamp chased to
                       clean, and the cause found
    ab7901f  the plan regenerated at ce00467
    899480d 5030dc9 e21995a  presets re-searched: 4 gained, 1 substituted
    9018dcf  runqueue cycle 1
    5ca37bb  v0.5.338  the passthrough guard keyed on the option set
    fb7f03b fba0949 d73a33b  v0.5.339  a tie survives a pattern boundary
    0725f71  v0.5.340  the subtune census's headline is three quarters true
    2695c43  runqueue cycle 3 recorded
    74f4d3f 5aec5db 082e962  v0.5.341  a wave program's slide returns to the
                       note
    b327970 76b7632 2564a8d  the two test-only branches
    c0ee1a5 62f40e0 ec00aa8 8d5356a  v0.5.342  bit $08's two-note alternation
    b481b0a  v0.5.343  the artefacts regenerated across three merges
    5b4581a  FIDELITY.md's stamp names the commit that carries the other four

## The four owed merges (v0.5.334-335)

**merge-subtune-branches** (f2c86f2 + 0c748bb -> eb71f82/5176a07). Two bounds on
the PSID header's subtune count, derived INDEPENDENTLY by agents that never saw
each other's work: the track table's layout extent (where it runs into the
pattern table) and the player's own init dispatch (`CMP #imm / BCS / JMP`).
They AGREE on seven of the eight files carrying both -- Crazy Comets 2, Geoff
Capes 8, Gerry the Germ 7, Hollywood or Bust 3, Knucklebusters 3, Thing on a
Spring 1, Warhawk 9. Spellbound is the one disagreement: layout 4 against
dispatch 3, and the dispatch wins because it says what the player DOES where
the extent says only what the table has ROOM for. Three bounds now apply in
order (dispatch, digi `subtunes_available`, layout extent), tighter wins, and
each dropped subtune is attributed to the bound that dropped it. 17 files move.

Three tests broke when the branches met, all for one reason: each pinned its own
bound by measuring the EMITTED count, which the other bound also moves. Each now
isolates its own bound with `dataclasses.replace(det, music_subtunes=None)`, and
a new assertion pins that the two agree on exactly seven of eight -- if that
number falls, the bounds have drifted. Also did the two edits the branches owed
but could not make: `test_empty_voice.py:149` 17 -> 2 (Rasputin, independently
re-measured from its $C72B/$C737 gap) and a SYNTHETIC fixture for
`test_subtune_census`, because after the bound no corpus file has an interior
`placeholder` subtune at all.

**merge-fidelity-branches** (87156c2 + d2bca79 -> 8994fe9). `find_freq_table`
gains a `near=` tie-break (Powerplay's two tables differ by one entry in 96) and
drift's "-1/(skip+1)" count is derived rather than a stale literal. ZERO files
move -- both measurement-only, which only a hash can confirm. Ran the clause
d2bca79's agent never ran: its agent returned a stub (every field the literal
string "test"), so the derived count had never been observed. Verified on four
subsets: prints 3, prints 2, and correctly omits the sentence at zero, where the
old code printed the literal 17 in all four cases.

**merge-goatwriter-and-test-branches** (0493e16 + fc84d67 -> 35b87a5). Zero
files move. RE-TAKING THE HASH CHANGED WHAT IT MEANT: 0493e16 measured "zero
byte differences" on a tree where Knucklebusters emitted eleven subtunes and
indices 8-10 over-read its eight-byte skip table; the subtune merge had since
cut that file to three, so those indices are unreachable and the bound is now
defensive rather than corrective. Same number, different claim.

**merge-gate-hold-zero-wait-branch** (56f3a04 -> fd9065c/2cdc3f6). ADOPTED
DESPITE ITS DoD FAILING, with the reasoning stated. 23 files move; A/B at -t 60
over all 23: melody 4 up 1 down, seq 5 up 2 down, pitch 3 up 1 down, gate 5 up
0 down. Human_Race 492 attacks -> 103 against the original's 48, retrig
5.59 -> 1.17, melody 56 -> 96%, onset 67 -> 100%. Chimera wave 50 -> 80%, gate
29 -> 83%, adsr 44 -> 57%. The two falls (Nineteen melody -3pp, Trans-Atlantic
pitch -2pp) are single-column dips on files gaining elsewhere in the same run.
IT SUBSUMED TWO PLANNED TASKS: `find_gate_hold` is True for Chimera, so the
mechanism the Chimera investigation derived independently is covered, WITH the
row-clock discriminator that proposal lacked and which correctly excludes
Saboteur_II.

## The six batch branches (v0.5.336)

Composed and re-measured AS A SET, which none had been. 23 files move; `vib`
mean |ln(ratio)| 1.04 -> 0.66 over 13 files, `bend` 0.73 -> 0.10 over 7, and
EVERY other dimension exactly unchanged on all 23.

THE CORRECTION THAT MATTERS: `greloc.c:1340-1341` does
`insertbyte(rtable[c][d] ^ 0x80)` -- "For normal notes, reverse all right side
high bits". CLAUDE.md stated the PACKED player's semantics correctly and then
drew the EMITTER's rule from them without the packer's XOR in between, so "the
byte that leaves a bend alone is `$00`" is backwards for anything writing a
`.sng`. Verified in greloc.c directly before believing the branch, because
CLAUDE.md said the opposite and records that choosing `$80` once cost Hollywood
or Bust 22 points of melody (that case is real and differently scoped: a
WAVEFORM entry reasoned from gplay.c, the editor, with no packer transform in
the argument).

## The three runqueue cycles

**Cycle 1** (9018dcf): main `fix-7kkkkk-cue-stall-claim`; delegated
`saboteur-ii-regates-on-wait0-rows` (done), `chicken-song-command-arpeggio`
(done), `nineteen-tie-spelling-melody-loss` (partial).
- 7.kkkkk's "further stall of one call per cycle" RETRACTED, verified against
  the code: `SongSpeeds.exact_row` is `Fraction(f * (o + 1), o)` -- literally
  (reload+1)*(O+1)/O with the skip already in it, so the section double-counted
  one counter seen from two sides.
- Saboteur_II: all 425 voice-0 attacks are genuine gate rising edges, not an
  instrument dipping below $10 -- $D404 never goes there on that voice.
- Chicken_Song: right that bit $01 is not Warhawk's drum (44 of the 45 files the
  old signature matched carry `LDA #$80` within 55 bytes; Chicken_Song has none
  within 256), WRONG that the arpeggio is 0/+3/+7 -- 38 events carry 6 distinct
  signed offset pairs, so it is a per-note chord.
- nineteen-tie: turned its own proposed cause OFF two independent ways and the
  fall SURVIVED at 1.07pp of 2.84pp, so it reported partial rather than claiming
  the win. Established that a 3-call row gives an untied note a budget of
  2+1 = 3 calls, so the whole row is inaudible and the tie UN-swallows notes --
  which is why attacks rise 69 -> 74, something a tie cannot otherwise do.
  38 of 83 corpus files have such a row, Commando included.

**Cycle 2** (5ca37bb): main `passthrough-guard-disarmed-by-every-bump`;
delegated `pending-tie-across-pattern-boundaries` (done), `emit-bit08` (partial),
`abpage-charset-regression-test` (done).
- THE GUARD WAS LIVE IN NO COMMIT AT ALL. `bump_version.py` rewrites
  `__init__.py` and `CHANGELOG.md` and NEVER touches presets.json, and it runs
  AFTER presets.py, so even the commit that regenerates the artefact ships a
  stamp one version behind. `_always()` now skips only when an option is
  genuinely unaccounted for AND the stamp predates the version. All three
  branches exercised by mutating scratch copies: versions differ + all accounted
  -> 24 passed (old code SKIPPED); option missing + versions differ -> skip
  naming it; option missing + versions MATCH -> FAILS.
- pending-tie: Human_Race voice 1 63 -> 48 attacks, EXACTLY the original's;
  melody 95.8 -> 100.0%, retrig 1.170 -> 1.000. 30 files move, a strict subset
  of the 34 with a tied boundary. Its own 2x2 showed the fix contributes
  EXACTLY ZERO on Human_Race without the wait==0 tie while 22 of 30 still move
  corpus-wide -- it reported both halves.

**Cycle 3** (2695c43): main `subtune-census-doc-refresh`; delegated
`wave-program-single-speed-absent-pitch` (done),
`phantom-subtunes-nemesis-thundercats` (partial, salvaged).
- 7.lllll was stale in every figure: 553 declared / 312 emitted where it now
  reads 237, and a by-cause table whose two largest entries were `placeholder`
  rows. All 139 placeholder rows are gone. Its headline reversed: three quarters
  of the loss, not all, because 97 subtunes across 8 files have a POSITIVE
  player-derived cause.
- wave-program: REFUTED v0.5.336's own commit message. A `< $80` opcode
  subtracts from a frequency ACCUMULATOR and exits through a path that writes
  it; a `>= $80` opcode writes the registers directly and never touches it. So
  the slide's right byte had to be WAVE_NOTE_BASE, not WAVE_NOTE_KEEP, which
  had frozen Saboteur_II an octave and a half below. 21 files move, `vib` the
  only dimension that moves.
- phantom-subtunes: its agent died on "StructuredOutput retry cap (5) exceeded"
  AFTER committing 169 lines of tests. Salvaged rather than stranded: read the
  commit, ran its tests (8 passed), recorded `partial` -- artefact verified,
  process not.

## Artefact regenerations

Twice. First at 990582a (after the four merges), again at b481b0a (after the
three later merges). The second is the informative one:

    FIDELITY.md summary   flat except noise 74527 -> 74493 and pulse +11
    VIBRATO.md  plain     25 absent / 38 instr / 16096 missing -> 18 / 30 / 9120
                drum      13 / 14 / 6302                       ->  3 /  3 /  926
                program    7 / 11 / 1449                       ->  8 /  9 /  871
                bit80      2 /  3 /   94                       ->  2 /  2 /   17
                headline  "81 of 102 emit nothing" -> "65 of 80"

22 instruments left the shortfall entirely; the drum bucket's missing reversals
fell 85%. NONE of it appears in FIDELITY.md's averaged block, because `vib` is
not one of the columns it averages. A reader checking only the summary would
conclude three merges did nothing.

## The preset searches

Two full `presets.py --fidelity -t 60` runs, six disjoint shards each (~15 min
against ~80 serial), `--merge`d and DIFFED against the shipped file before
adoption.

Run 1 (899480d): 4 gained, 1 substituted -> adopted. ACE_II gate 83 -> 88%,
Food_Feud gate 44 -> 64%, Chain_Reaction vib 0.40 -> 0.51x, Zoolook vib
0.12 -> 0.21x. Zoolook $0F09 went 674 orig / 0 ours -> 674 / 267 and
Chain_Reaction $00F8's pitchseq row left the absent list entirely.

Run 2 (in progress at the session's end): only 3 changes across 2 songs --
81 of 83 songs' settings confirmed unchanged against a tree where 69 files'
bytes had moved. W_A_R_Preview gains `pitch_seq`; Delta loses
`no_test_restart` and `max_hard_restart`. The user directed: adopt
W_A_R_Preview only, keep Delta as shipped. Applied and verified: exactly 1 file
moves.
</work_completed>

<work_remaining>

## IMMEDIATE -- an unfinished sequence, in order

1. **The reports are mid-regeneration.** `fidelity.py <corpus> -t 60 --presets
   ../presets.json -o ../FIDELITY.md --vib-census ../VIBRATO.md` was launched
   from `python/` and was at 59 of 95 files. Log:
   `<scratchpad>/fidgen8.log`. Wait for "wrote" in that log.
2. **Commit the selective adoption**: presets.json, SURVEY.md, FIDELITY.md,
   VIBRATO.md. Bump the version first (`python python/bump_version.py "..."`) --
   the bump is routine again since v0.5.338's guard fix.
3. **The FIDELITY.md stamp will read `-dirty`**, because the other artefacts
   were uncommitted while it ran. The fix, done twice already this session: run
   `fidelity.py ... -o ../FIDELITY.md` ALONE on the clean tree left by that
   commit, then commit the one-line stamp change. Confirm the diff is exactly
   one line before committing -- if more moved, something else changed.
4. **Push.**

## THE DELTA DECISION -- requires-user, and it is a real one

The re-search wants to drop Delta's `no_test_restart` and `max_hard_restart`.
Measured both ways at -t 60:

    column      shipped   re-searched
    melody          92%          100%
    seq             92%          100%
    pitch           94%          100%
    slides    2513/2766     2632/2766
    bend          0.35x         0.38x
    vib           0.86x         0.89x
    wave           100%           89%
    hold           100%            0%
    gate            84%           42%
    adsr           100%           98%

Six up, four down, and CLAUDE.md documents THIS FLAG as distorting the report in
BOTH directions: `--no-test-restart` deletes the testbit frame, which is the
only frame our conversions spend below $10, and that is what siddump requires to
print an attack at all. So with the flag ON melody/seq/pitch are UNDERSTATED
(the instrument cannot see our attacks); with it OFF, `hold` and `gate` lose the
frames that were flattering them. The report cannot settle its own distortion.

This is a listening question. `build/listen` has A/B pages staged (83 pairs at
120 s, startup lag corrected, voice selector, register panel, tracker view).
Delta is one file. Open `build/listen/Listen.ps1` or run `python abpage.py
--serve`.

## THE PLAN IS STALE -- run /whattask before any runner

`.claude/tasks/whattask.json` is keyed to `e21995a`; HEAD is `5b4581a` and 12
tasks have completed since. `runs.jsonl` has 71 lines. Specifically:

- `nineteen-tie-spelling-melody-loss` NEEDS RE-SCOPING, not re-running. Three
  cycles picked it first because `partial` keeps it ready, and each time I
  excluded it: its own agent turned the proposed cause off two independent ways
  and the fall SURVIVED, so the DoD's first clause is REFUTED rather than unmet.
  Rewrite the verify before any runner sees it again.
- `phantom-subtunes-nemesis-thundercats`'s verify names the WRONG BOUND: it says
  `det.subtunes_available`, which belongs to the digi engine and reads 0 on both
  files, with `det.music_subtunes` None on both. The operative bound is
  `tracks.track_table_extent`. Opened as
  `phantom-subtunes-verify-names-the-wrong-bound`.
- Ids opened and not yet in the plan: `hard-restart-budget-three-call-row`,
  `melody-collapsed-ratio-mis-orders-a-shorter-truer-sequence`,
  `fidelity-hardcodes-s2-in-multispeed-summary`,
  `find-gate-hold-docstring-names-wrong-branch-address`,
  `cmdtable-chord-arpeggio-emission`,
  `regenerate-vibrato-and-fidelity-after-chicken-drum-fix`,
  `retake-wave-alternate-noise-trade`,
  `boundary-tie-loop-around-restart-position`,
  `boundary-tie-four-files-retrig-below-one`,
  `trackindex-subclass-replace-with-explicit-convert-parameter`,
  `first-frame-lead-written-multispeed`,
  `freq-table-length-off-by-one-at-the-grid-edge`,
  `bit08-alternate-with-no-wave-pair`,
  `survey-template-carries-the-superseded-census-headline`,
  `prune-worktrees-conflicts-with-the-runner-itself`.

## TWO DEFECTS IN THE RUNNER ITSELF

1. **The serial.lock stamp is wrong and will bite.** Records are stamped with
   the CLAIMING SCRIPT's pid, which exits in under a second, so the protocol's
   reap rule ("this host, pid not running -> orphan") sees every live record as
   reapable. In cycle 3 it would have freed `tracks.py`, `python/tests` and
   `goatwriter.py` while two agents were writing them -- and those agents ran a
   further twenty minutes after that pid was already dead. I refused to start
   cycle 4 on that basis. THE FIX: stamp something that outlives the cycle --
   the workflow run id is the natural candidate, since a session-based
   orchestrator has no long-lived pid of its own. Belongs in the plugin's
   LOCKING.md.
2. **Two conflicts the `touches` arithmetic cannot see**, both excluded by hand
   every cycle: `prune-merged-worktrees` writes `.claude/worktrees`, which is
   where the Workflow runner CREATES agent worktrees (the conflict is with the
   runner, not a task); and `task-touches-under-declared-for-investigations`
   writes `.claude/tasks`, where the orchestrator holds serial.lock and
   runs.jsonl, and its job is to rewrite whattask.json which /runqueue requires
   to stay byte-identical. Put the first in the plan's `hazards`.

## OWED CODE FIXES NAMED THIS SESSION

- `python/survey.py:624` still carries "essentially all of the loss is reading
  past the end", which the sfx dispatch made three-quarters true. It is a
  GENERATED template, so it reaches every regenerated SUBTUNES.md and no doc
  edit can fix it.
- `task-touches-under-declared-for-investigations` is measurably capping the
  fan-out: one task declaring the bare directory `rw:python/tests` is a prefix
  of every specific test file, and it held cycle 1's fan-out to 3 of 28.
</work_remaining>

<attempted_approaches>

## Dead ends -- do not repeat

**Three regeneration runs chasing a clean FIDELITY.md stamp, two of them on a
wrong diagnosis.** I blamed my own concurrent `runs.jsonl` append, then proved
otherwise with a frozen tree. The stamp is `git status --porcelain -- .` being
non-empty (fidelity.py:3165) and THAT COMMAND COUNTS UNTRACKED FILES.
`.claude/worktrees/`, `monlog_out.txt` and `6581.pdf` marked every report dirty
however clean the tracked tree was. All three are now gitignored. The 0.5.330
report that opened the task could never have had a clean stamp either.

**A `--fidelity` search pointed at a subset directory.** `presets.py` has NO
per-file flag, so a subset directory writes a presets.json holding ONLY those
songs and silently drops the rest. Shard the whole corpus instead.

**Copying `MAX_SANE_SPEED_RELOAD` onto the skip table**, which is what
`songspeeds-skip-reads-past-its-table`'s DoD literally asked for. It broke
`test_ricochet_has_no_table_and_takes_the_image_byte`: skip's legitimate range
is 0-127 against frames' 0-8-ish. An extent, not a magnitude.

**Including the instrument table in the not-track-data set** for the track-table
extent. It over-runs and swallows subtune 0's own cells on Battle_of_Britain and
Las_Vegas_Video_Poker, driving the bound to 0 on 22 files.

**Delegating `nineteen-tie-spelling-melody-loss` again.** Three cycles picked it
first; each time its DoD's first clause is already refuted.

## Probe errors -- all four were the harness's calling convention

1. `fidelity._measure` called with raw values where it takes an args object.
   Threw. Used the CLI instead, which is the harness's own path.
2. A byte-hash keyed presets.json by the bare stem ("Sanxion") where its keys
   carry ".sid". Every per-song entry silently dropped; the diff read 15 files
   where the truth was 18. Caught only by the probe's own success assert.
3. My A/B comparison script dropped EVERY ratio column, because they print with
   a trailing "x" (`0.17x`) and `float()` threw. It reported "no dimension moved
   on any file" -- a flat table produced by the probe, not the report. `vib` had
   moved on 13 files. The script now prints which columns it could not parse.
4. A byte-hash for the selective adoption compared against the PREVIOUS search's
   merged file rather than the shipped presets.json, and reported 14 files
   moving for a one-key edit. Re-run against `HEAD:presets.json` it reads 1.

## Alternatives considered and not taken

- `--untracked-files=no` for the provenance stamp. Rejected: an untracked file
  CAN change what the report measures -- `python/tools/siddump-rt/siddump.exe`
  is gitignored and load-bearing. Left open as
  `fidelity-stamp-is-dirty-by-construction`.
- Running `/runbatch` on the strict `--ready 8` set. Refused once with the
  arithmetic: 28 conflicting pairs out of 28, a complete graph, so 8 stages of
  1 -- strictly worse than 8 `/runtask` runs. The largest pairwise-disjoint set
  among all 17 eligible tasks was TWO.
- Reaping cycle 3's lock records to start cycle 4. Refused: the rule permits it
  (dead pid) and it would have corrupted a live run.
</attempted_approaches>

<critical_context>

## Rules this session paid for, beyond what CLAUDE.md already says

**A skip condition must be keyed on the thing that would make the assertion lie,
never on a proxy that moves more often.** A guard that goes dark on a schedule
nobody chose is worse than no guard, because the suite still reports green.
Written into CLAUDE.md beside the option-passthrough paragraph.

**A lesson recorded in one emitter is not a lesson in the file.**
`goatwriter.py` carried THREE comments about the wavetable's right byte. Two
were corrected independently -- by v0.5.341's slide fix and by cbf80a7's
alt_note work -- and neither knew about the other, so a superseded reading
survived beside two correct ones at a third site. Worse, the ORIGINAL wording
the first correction replaced was nearer the truth than its correction. When
that byte's meaning is restated, grep for `greloc.c` and `976-977` and fix every
site.

**Re-take a measurement on the base you are merging onto, not the base it was
measured on.** It changed what a number MEANT once this session (the SongSpeeds
bound went from corrective to defensive because the subtune merge removed the
indices it guarded) even though the number itself was identical.

**Two agents deriving one mechanism independently is a signal, not a
coincidence.** It happened twice: the subtune bounds (agreeing on 7 of 8 files)
and the zero-wait tie (Human_Race's $09E4 and Chimera's $C267, a week apart, as
two separate plan tasks). Where the two versions differed, the difference was
the whole value -- one had a discriminator and the other did not.

**A "failed" agent is not necessarily failed work.** The harness reported
`phantom-subtunes-nemesis-thundercats` as returning nothing usable; it had
already committed 169 lines of tests. Read the worktree before recording.

**The `partial` outcome is doing real work.** Four of this session's tasks
returned it, every one because the agent refused a DoD it had not literally met
-- and in two cases the refusal WAS the finding (nineteen-tie turning its own
cause off; emit-bit08's "only the 22 files" holding on the `only` half and not
the count).

## Environment

- Windows 11, PowerShell primary with a Bash tool alongside. `rtk` proxies bash
  output. The Bash tool's working directory PERSISTS between calls -- a `cd`
  into a worktree silently redirected several later `git status` calls, one of
  which read as master having moved.
- Corpus: `C:/Users/mit/claude/c64server/SIDM2/SID/Hubbard_Rob`, 95 files, 83
  convertible, 12 permanently `UnsupportedSidError`.
- Tests: `python -m pytest tests/ -q` from `python/`, ~4.5 minutes, 1353 tests.
- `gt2reloc`: `C:\Users\mit\Downloads\GoatTracker_2.77\win32\gt2reloc.exe`; its
  source (including `greloc.c`) is at `...\GoatTracker_2.77\src\`.
- `python/tools/siddump-rt/siddump.exe` is GITIGNORED and load-bearing. A fresh
  worktree lacks it, and without it the harness REFUSES multiplier>1 songs.
  Every agent brief must open with copying it in.
- Agent worktrees have twice been cut at an OLDER commit than the brief named.
  Always have agents report `git log --oneline -1`.
- No reachable forge: `gh issue list` and `gh pr list` returned empty every time.

## Numbers worth carrying

- suite 1239 -> 1353; corpus melody 93 -> 94%, seq 93 -> 94%, gate 53 -> 54%
- Human_Race: melody 56 -> 100%, retrig 5.59 -> 1.00, across THREE mechanisms
  (the subtune tempo fix, the zero-wait tie, the boundary carry)
- vibrato shortfall: 102 instruments -> 80; drum bucket 6302 -> 926 missing
  reversals
- 69 files moved bytes across three merges before the second regeneration
</critical_context>

<current_state>

## Repository

- HEAD `5b4581a`, pushed. `origin/master` == HEAD.
- WORKING TREE DIRTY, deliberately, mid-sequence:
      M presets.json    the selective W_A_R_Preview adoption
      M SURVEY.md       regenerated against it
      M whats-next.md   this file
  FIDELITY.md and VIBRATO.md are being rewritten by a running `fidelity.py`.
- NO unmerged branches. All twelve merged.
- `.claude/tasks/serial.lock` does NOT exist -- cycle 3's records were released
  through the mutex and the registry emptied.

## Deliverables

| item | state |
|---|---|
| the four owed merges | COMPLETE, pushed |
| the six batch branches | COMPLETE, pushed |
| the three runqueue cycles | COMPLETE, recorded, pushed |
| artefact regeneration | COMPLETE for v0.5.343; a second pass is IN FLIGHT for the selective adoption |
| preset re-search run 1 | COMPLETE, adopted, pushed |
| preset re-search run 2 | COMPLETE; selectively adopted, NOT yet committed |
| whattask.json | STALE at e21995a -- 12 tasks done since |

## Open questions

1. **Delta** -- the listening decision above. Nothing else blocks on it.
2. Whether `fidelity.py`'s stamp should ignore untracked files. The safe-looking
   fix hides a real hazard (siddump.exe).
3. Whether `presets.json` should carry a marker that it is no longer the output
   of a single search run. It is now the v0.5.343 regeneration plus one
   hand-picked setting, and its `generator` stamp (`h2g 0.5.342 presets.py`)
   cannot convey that. Every entry is individually a measurement; the FILE is
   not one run.

## Exact next command

    # 1. wait for the running regeneration
    tail -f <scratchpad>/fidgen8.log      # until "wrote"
    # 2. from the repo root
    python python/bump_version.py "the W_A_R_Preview pitch_seq gain adopted"
    git add presets.json SURVEY.md FIDELITY.md VIBRATO.md CHANGELOG.md \
            python/h2g/__init__.py whats-next.md
    git commit && git push
    # 3. then re-run FIDELITY.md alone on the clean tree for a clean stamp,
    #    confirm the diff is exactly one line, commit, push
    # 4. then /whattask -- the plan is 12 tasks stale
</current_state>
