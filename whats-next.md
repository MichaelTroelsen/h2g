<original_task>
Drive this repo's task queue with the mit-setup plugin commands, in the order the
user issued them:

  /whattask         x4   regenerate the open-task list with a model, execution mode
                         and lane per task, as prose plus .claude/tasks/whattask.json
  /runqueue         x4   run both lanes at once -- delegable tasks fanned out to
                         agents in their own worktrees, one `main` task in this
                         session beside them
  "merge the worktrees" / "commit and push"   at the user's direction, after each cycle
  "regenerate the artefacts"
  "run the fidelity preset search" -> "adopt if it gains"   (twice)

No converter feature was requested directly. The scope is the queue machinery and
whatever the queue surfaced. The session ran from v0.5.344 (fc691a4) to v0.5.356
(4cebef8), 40 commits, all pushed.

THIS FILE REPLACES the previous handoff, which covered the session ending at
350851e and was spent -- every item in its work_remaining was closed. Recover it
with `git show 9ec3133:whats-next.md` if any of that history is wanted.
</original_task>

<work_completed>

## Headline

Four /runqueue cycles, 16 tasks, 40 commits, suite 1353 -> 1415. Master went
fc691a4 -> 4cebef8 and everything is pushed to github.com/MichaelTroelsen/h2g.

The session's most valuable output is NEGATIVE results -- four tasks closed by
refuting their own premises, and two measurement defects found in the harness
rather than the converter. One preset adoption was made and then RETRACTED.

## The four cycles

**Cycle 1** (fan-out at fc691a4, 6 agents + main `doc-retract-slide-only-wave-programs-claim`)
- `find-gate-hold-docstring-names-wrong-branch-address` (9e52802): $F080 is the
  CMP's address, the branch is $F083, and Saboteur_II reaches $F094 by TWO
  branches ($F083 BNE and $F07B BEQ). Byte-inert.
- `abpage-prune-stale-pages` (f4e8c41): `prune_stale_pages()` removes pages a
  rebuild no longer produces; 6 tests, staged WAV pairs untouched.
- `fidelity-hardcodes-s2-in-multispeed-summary` (7b1a6f2): the summary said
  "-S2 / every 2 frames" for EVERY multiplier while interpolating -m{traced}
  correctly a clause later. 23 of 42 multispeed files were misdescribed.
- `freq-table-length-off-by-one-at-the-grid-edge` (161de13): entry 95
  SATURATES (63520 * 2**(1/12) = 67297 does not fit 16 bits), so a 96-entry
  table validated only 95. `FreqTable.length` is now the table and the new
  `.run` is the semitone run; BOTH tie-breaks rank on `run`, which is
  load-bearing (Powerplay's two players differ by exactly this entry).
  Returned `partial` because its DoD's "only two files" cannot hold alongside
  its own "_fixed_attack_note has the identical exposure" -- Ricochet is the
  third. I made the four assertion retargets it named but could not reach.
- `boundary-tie-four-files-retrig-below-one` (ad8a19c): a bit-6 REST closes the
  gate on its own branch unconditionally, without consulting status bit 5, read
  in two players (BoB $8065/$80C0/$80D9, Devils_Galop $1399/$13FA/$1418). So
  `pending_tie` must be False after ANY bit-6 event and must CLEAR a tie.
  12 files move, no file loses on any dimension.
- `powerplay-vibrato-rate-still-two-thirds` (ebc9d1a): gt2reloc's packed player
  skips continuous effects on tick 0 (player.s:982-987, REALTIMEOPTIMIZATION,
  confirmed by packing the same .sng with -R0: 0.658 -> 1.015). `cmp` shortened
  by (row_calls-1)/row_calls. **48 files reached, 27 toward 1 and 15 away** --
  adopted on the aggregate with the regression named. Mozart 1.468 -> 2.031.
- MAIN `doc-retract-slide-only-wave-programs-claim` (c566058): v0.5.336's commit
  message claim was false in both halves and had reached NO doc, so the
  retraction is written where a grep for its own words lands.

**Cycle 2** (fan-out at 0e9f254, 4 agents + main `shared-refs-stash-races-across-worktrees`)
- `wave-program-all-slide-portamento` (3508ddb): `$85` does not stop the
  interpreter -- it jumps to the per-frame writer whose tail reads the frequency
  ACCUMULATOR, so a held note sounds at the pitch the program slid TO. One byte
  (WAVE_NOTE_KEEP -> WAVE_NOTE_BASE). **21 files move, set-equal to the 21
  `wave_program` presets.** `program` bucket 870 -> 596 missing reversals.
- `note-freq-extrapolates-past-the-16-bit-ceiling` (57763ef): answered NO. The
  11 index-99 records are ONE boilerplate record copied across 11 tunes; the
  player reads freqtbl+198 and what is there differs per file (two are $0000);
  none is played. Docstring + 4 tests, 0 files move.
- `abpage-piano-roll` (a7e3160): notes-per-voice card; per-voice attack sums
  equal the row aggregate on 95/95 rows.
- `crazy-comets-last-missing-attack` (2c13d0a, no code): **there is no missing
  attack.** 642 = 640 paired + 2 cut by the window edge; in the region both
  traces can express OURS has a surplus at 60 s, 66 s and 80 s alike.
- MAIN `shared-refs-stash-races-across-worktrees` (48822c0): the rule in
  CLAUDE.md and in the plugin's LOCKING.md.

**Cycle 3** (fan-out at c6944d4, 2 agents + main `classic-vibrato-row-calls-...`)
- `survey-template-carries-the-superseded-census-headline` (627a10b): the
  headline is now COMPUTED from the same rows the by-cause table uses -- "31% of
  the 316 lost below; the remaining 69% is still read-past-the-end".
- `listen-merge-notes-stale-header` (closed by 96298cc): **never open.** Fixed at
  v0.5.317; carried as open through three plans (see Attempted Approaches).
- MAIN `classic-vibrato-row-calls-wants-the-mean-row-not-the-shortest`
  (9ec3133, no code): **premise refuted.** 12 of the 15 regressed files have ONE
  row length, so every reduction over the tempo values is the same number and
  the proposed play-weighted rule is provably inert -- including Mozart and
  One_on_One, the two the task named to start from.

**Cycle 4** (fan-out at 9ec3133, 3 agents + main `reversal-ratio-may-be-nonlinear...`)
- `bit08-alternate-with-no-wave-pair` (e4b2f58): needed NO second emitter. Of 12
  candidates, **11 sit past `det.instr_used` -- dead cells**. The one real record
  is fixed by relaxing one clause to `(alt == wave and alt_note is None)`.
  1 file moves (Dragons_Lair_Part_II).
- `boundary-tie-loop-around-restart-position` (268cae4, `partial`): the wrap tie
  is blocked by `apply_tempos`, which owns row 0 of voice 0's ENTRY REFERENCE,
  and every corpus restart position is 0. First build cost Star_Paws 38pp of
  melody; vetoed there, it ships **correct and inert (0 files move)**.
- `abpage-spectrogram` (510b098): FFT precomputed in Python (pure stdlib, no
  numpy), base64 into the page; draw sub-10 ms, build ~3.4 s per tune.
- MAIN `reversal-ratio-may-be-nonlinear-in-oscillation-rate` (73c7cd1):
  **hypothesis refuted, conclusion confirmed by a different mechanism.**

## The two preset searches, and the retraction

Both were six-shard `presets.py --fidelity -t 60` runs, merged and DIFFED
against the shipped file before adoption. Zero failures and zero "will not
convert" in either -- checked, because a failed search keeps the old entry and a
missing entry is indistinguishable from a measured "no".

Run 1 (v0.5.349, 3c74767): five candidates, ONE adopted -- Flash_Gordon drops
`pitch_seq`, its only moving column being `vib` 1.039 -> 0.987. Verified: exactly
1 file moves, and the regenerated report printed 1.04 -> 0.99 as predicted.

Run 2 (v0.5.352, bd12a51): six candidates, ALL SIX turning on `no_test_restart`.
One adopted (Arcade_Classics) -- **and retracted at v0.5.353 (864d096)**. See
Attempted Approaches; this is the session's most important process failure.

## The artefacts

Regenerated four times (0cdf47f/d13205b, aab3799/4cebef8, and twice between),
always with the same discipline: commit SURVEY/SUBTUNES/presets FIRST, then run
fidelity.py against the clean tree, so its stamp names a real commit rather than
`-dirty`. That ordering was learned in an earlier session at the cost of three
runs and two wrong diagnoses; it worked first time on every attempt here.
</work_completed>

<work_remaining>

## 1. THE PLAN IS STALE -- run /whattask before any runner

`.claude/tasks/whattask.json` is keyed to `9ec3133`; HEAD is `4cebef8` and four
tasks have closed since (the whole of cycle 4). `runs.jsonl` has 92 lines.

Ids opened by cycle 4 and not yet in the plan:
`vib-figures-are-step-quantised-reread-past-decisions`, plus the four the
`bit08` and `boundary-tie` agents opened (a [user] listening check on
Dragons_Lair_Part_II subtune 7 voice 1; the `--baseline` subtune caveat; the
"could the opening tempo live on voice 1 or 2" question; and the wrap tie's
unmeasured first-play-vs-loop trade).

## 2. `--baseline`'s verdict line can state the opposite of the truth  [main]

`python/fidelity.py`. It printed **"No dimension this report measures can see
this change"** for a change worth **-38pp of melody** (Star_Paws, cycle 4),
because the change lived outside the traced subtune. That sentence is trusted
across this project and has justified shipping decisions. It should name the
subtunes whose bytes moved, or caveat itself when the differing rows' change is
not in the traced subtune. This is the highest-value open item.

## 3. A shared `instr_used`-bounded census helper  [subagent]

TWO tasks in two cycles had their candidate population collapse once bounded by
`det.instr_used`: 11 of 12 bit-$08 records and 11 index-99 frequency cells were
all dead table cells. A third will start from the unbounded table unless a
helper makes the bound the default.

## 4. The vibrato regression is still live  [main]

`ebc9d1a` is on master and pushes 15 files further from the original's
oscillation rate (Mozart 2.03x). Two things are now known that were not:
- the proposed `row_calls` fix is REFUTED (12 of 15 files cannot move);
- the correction is QUANTISED -- the realised half-period is `cmp + 2` calls, so
  at cmp 0 none is possible and Mozart's four instruments receive 1.000, 0.750,
  0.667 and 0.700 for one intended 0.667;
- and `vib` itself is a STEP function, so any candidate must be judged against
  that rather than a continuous ratio.
Open as `vibrato-cmp-quantisation-limits-the-tick0-correction`.

## 5. The harness window bias  [main]

`fidelity._measure` traces BOTH sides for `nframes = seconds * 50`
(fidelity.py:3374) and passes `lag` only INTO wave_compare/adsr_compare/
gate_compare as an alignment offset -- the window is never extended. So the
original's last `startup_lag` frames (3-8) have no counterpart region in our
trace, on EVERY file, always scored against us. Confirmed by reading, and
demonstrated on Crazy_Comets. Two candidate fixes: trace ours for
`seconds + lag/50`, or truncate the original at `nframes - lag`. Either moves
every sequence figure in FIDELITY.md, so the report must say numbers either side
are not comparable.

## 6. `retrig`, `hold` and `tail` are reachable by no probe  [subagent]

They are computed and printed but carried under no key in `fidelity.py --json`.
`pitch` is `pitch_jaccard` and `seq` is `sequence`. Any A/B tooling is blind to
three columns by construction -- this is what caused the v0.5.352 retraction.

## 7. Worktree hygiene, with a CORRECTED check  [main]

40 worktree entries (33 `wf_*`), 18 unmerged branch refs. A naive "no line in
the worktree is absent from master" check FLAGS 11 files across 8 worktrees --
but every one is SUPERSEDED content, not unlanded work: master has moved past
them. Verified by example: `wf_deb47f97-915-1`'s flagged goatwriter.py line is
the OLD bit-$08 refusal clause that e4b2f58 replaced, and
`wf_55f332af-99a-5`'s test_abpage.py flags 252 lines while its prune tests ARE
on master (11 references). **The check must compare against the commit the
worktree's work landed in, not current master** -- `prune-merged-worktrees`'s
verify currently says the latter and will produce false positives.
Also remove the scratch byte-hash worktrees under the scratchpad
(base-fc691a4, base-d13205b, base-0e9f254, base-9ec3133).

## 8. Standing [user] items, none of them answerable by any column

- `delta-no-test-restart-verdict` -- refused at the user's direction at v0.5.344
  and offered again by BOTH searches; still open.
- `no-test-restart-three-more-refused-candidates` (Wiz, Powerplay, Dragons Lair).
- A listening check on Dragons_Lair_Part_II subtune 7 voice 1 for the bit-$08
  change: no column reads a noise frame's pitch, its traced subtune is the
  known-wrong music, and the record sounds only in an untraced subtune.
- `method-doc-section-scheme` -- H2G-CONVERSION-METHOD.md's 5-letter section
  scheme is EXHAUSTED at 7.zzzzz, and four tasks are blocked behind it.
</work_remaining>

<attempted_approaches>

## THE RETRACTION -- the session's most important failure

At v0.5.352 I adopted `no_test_restart` for Arcade_Classics on a comparison
reporting "5 better, 1 worse". **The comparison covered 6 of the 14 columns it
claimed to.** It asked `fidelity.py --json` rows for `pitch`, `seq`, `hold`,
`retrig`, `noise`, `onset`, `tail` and `nrun`; the real keys are
`pitch_jaccard`, `sequence`, and for the rest ABSENT. `dict.get` returned None
for all eight and the loop skipped them in silence.

WHAT CAUGHT IT was not the script -- it was regenerating FIDELITY.md and reading
the row, which showed `pitch 100% -> 93%` and `seq 100% -> 99%`, columns the
probe had never looked at. Re-keyed, Arcade_Classics has the same signature as
the five candidates I had refused. Retracted at v0.5.353; presets.json's songs
dict is byte-identical to v0.5.351's and FIDELITY.md differs by exactly its
stamp.

THE RULE THIS EARNS is narrower than "assert the calling convention", which that
probe DID follow: **a probe reading a SUBSET of a report's columns must assert
every column it names exists.** Silently comparing fewer is indistinguishable
from comparing them all and finding no movement. And: regenerating the artefact
is a second, independent reader of the same measurement -- prefer it BEFORE
adopting, not after.

## Probe failures -- nine of the same class this session

1. `quiet=True` passed to `convert()`, which does not accept it (earlier session).
2. presets.json keyed by bare stem where its keys carry ".sid".
3. Ratio columns dropped because they print a trailing "x" and float() threw.
4. The frequency-table calibration omitted.
5. `detect()` called without its `log` argument (mine).
6. `Detection.instr` read where the field is `.instr_start` (mine).
7. The column-subset failure above (mine).
8. A spy on `h2g.patterns.apply_tempos` when `convert` binds the name at import
   (`from .patterns import apply_tempos`) -- it patched nothing and reported
   "0 of 95 files reach the tempo path". Caught only because 0 of 95 is
   obviously wrong (mine).
9. The run-log joiner dropped its raw-record fallback and wrote `inconclusive`
   for two SUCCESSFUL tasks; corrected by APPENDING the right records, since
   runs.jsonl is append-only and read last-line-per-id (mine).

## The rot detector that was vacuous

Built a check for carry-over tasks whose `verify` quotes code that no longer
exists. First run: 26 tokens, 0 absent -- a clean bill. Then validated it
against the ONE string known to have rotted (`head = head or h`) and it reported
that string as PRESENT. `git grep` searches all tracked files including
`.claude/tasks/whattask.json` and `runs.jsonl`, **which quote the verify strings
themselves**. Excluding `.claude/` and `CHANGELOG.md` makes it fire correctly.
That is exactly how the original rot went unnoticed for three plans.
Known false-positive kinds: language builtins (`dict.get`), PROPOSED code a
verify asks someone to write, and abbreviations containing `...`.

## A synthetic test that was under-powered

The first linearity test for `reversals_by_instrument` used ONE 600-frame note
and reported counted/true = 1.000 at every rate -- it would have closed the
question as "linear, no problem". The effect lives at SHORT note lengths, where
`floor(L/p) - 1` is a step function. Re-run at realistic lengths it is
unmissable (x1.951 at L=10 for a x1.333 rate change).

## A test that passed in its worktree and failed on master

`test_the_page_embeds_null_spectrogram_when_none_is_staged` called `page()`
without monkeypatching `LISTEN`, so it read the REAL build/listen -- empty in a
fresh agent worktree, 83 staged pairs on master, including the tune it names.
Its own sibling three lines below already used tmp_path. Fixed at merge.

## Dead ends and refuted premises -- do not retry

- **The `{a-1, a, a+1}` attack skip as the cause of `vib` non-linearity.** The
  counter is exact against a known count at every rate and amplitude-independent
  down to one frequency unit. The skip is innocent.
- **`row_calls` as the cause of the 15 vibrato regressions.** 12 of the 15 have
  one row length; the change is provably inert on them.
- **Crazy_Comets having a missing attack.** It does not; the deficit is the
  trace window, and in-region OURS has a surplus.
- **Both stash "recovery" tasks.** Two agents each concluded the other's work
  was destroyed. Neither was right -- no code was lost either way, verified by
  diffing (the 13 differing lines were all docstring prose).
- **`listen-merge-notes-stale-header`.** Fixed at 96298cc; its verify quoted the
  BUGGY expression as though present.
- **The wrap tie's "moves more files" premise.** It reaches 2 candidate files,
  1 after Chimera declines, and 0 after the tempo veto.

## Considered and not taken

- Running the vibrato regression task in cycles 1-3. Deferred three times: twice
  by the CPU rule (heavy A/B opposite heavy fan-out) and once because
  `goatwriter.py` was held by an unmerged worktree. It finally ran in cycle 3
  and refuted itself.
- Widening a task's declared `touches` mid-run. The vibrato task needed
  `convert.py`, which was outside its writable set; I did not widen it. It was
  moot -- the change is inert on 12 of the 15 target files.
</attempted_approaches>

<critical_context>

## Rules this session paid for, beyond what CLAUDE.md already says

**A probe reading a subset of a report's columns must assert every column it
names exists.** Written up in the v0.5.353 commit; NOT yet in CLAUDE.md (the
task `docs-probe-must-assert-every-column-it-names` is open and ready).

**`vib` is a STEP function of the rate, not proportional to it.** Reversals per
note are `floor(L / p) - 1`, so a rate change registers only when it carries the
note across a whole half-cycle boundary. Measured through the real function for
a x1.333 rate change: 600-frame note x1.336, 64 x1.333, 16 x1.333, 12 x1.500,
10 x1.951, 6 x40.0. This is in the `vib` Dimension's own comment and reaches the
published FIDELITY.md legend -- which is the argument for putting a column's
blindness in the Dimension rather than a doc, demonstrated.

**A worktree does not isolate `refs/stash`.** It is shared. `git fsck
--unreachable` shows 100+ dangling stash commits from earlier sessions. In
CLAUDE.md and the plugin's LOCKING.md as of 48822c0. Every fan-out brief this
session carried it as hard rule 1 and no agent used stash.

**A commit message is not a doc and is also not erasable.** When one carries a
wrong mechanism, retract it somewhere a grep for its own words will land --
correcting the docs is not enough when the docs never carried it.

**Re-measure on the base you are merging onto.** Cycle 4 re-measured four preset
candidates that a previous search had refused, because 21 files' bytes had moved
under them. Their verdicts held, but that had to be established.

## Environment

- Windows 11, PowerShell primary with a Bash tool. `rtk` proxies bash output.
- Corpus: `C:/Users/mit/claude/c64server/SIDM2/SID/Hubbard_Rob`, 95 files,
  83 convertible, 12 permanently `UnsupportedSidError`.
- Tests: `python -m pytest tests/ -q` from `python/`, ~5.5 min, **1415 passed,
  2 skipped**.
- `python/tools/siddump-rt/siddump.exe` is GITIGNORED and load-bearing; every
  agent brief must open by copying it into the worktree.
- `build/fidelity.json` is GITIGNORED but feeds a COMMITTED feature (abpage's
  notes-per-voice card). A fresh clone renders that card empty until
  `fidelity.py --json` runs. It is currently a 0.5.356 trace.
- The plugin's `LOCKING.md` lives OUTSIDE this repo
  (`C:/Users/mit/.claude/plugins/marketplaces/mit-claude-setup/plugins/mit-setup/`)
  and carries half the refs/stash rule, so it is in no commit here.
- No reachable forge: `gh issue list` and `gh pr list` returned empty every time.

## Orchestration facts worth carrying

- The workflow JOURNAL carries each agent's RAW record; the
  `{dispatched, model, record}` wrapper exists only in the workflow's return
  value. A joiner must handle both.
- `serial.lock` records are stamped with the CLAIMING SCRIPT's pid, which dies
  in a second, so the protocol's reap rule would see every live record as an
  orphan. Only safe because this session was the sole orchestrator. Open as
  `serial-lock-pid-stamp`.
- Two tasks conflict with the RUNNER rather than with each other and must never
  be scheduled inside a cycle: `prune-merged-worktrees` (writes
  `.claude/worktrees`, where the Workflow runner creates agent worktrees) and
  anything writing `.claude/tasks` (where serial.lock lives and whattask.json
  must stay byte-identical).
- A bare `rw:python/tests` in a task's touches is a prefix of every specific
  test file and collapses the fan-out.

## Numbers worth carrying

- suite 1353 -> 1415; corpus melody 94%, seq 94%, pitch 95%, wave 83%, gate 55%,
  adsr 66% (all flat across the session's merges)
- VIBRATO.md `program` bucket 870 -> 596 missing reversals; `plain` 8382
- 63 of 83 files moved bytes at v0.5.345, 21 at v0.5.350, 1 at v0.5.355
- two full `--fidelity` searches, 11 candidates offered, 1 adopted and kept
</critical_context>

<current_state>

## Repository

- HEAD `4cebef8`, **pushed**; `origin/master` == HEAD, 0 ahead / 0 behind.
- Working tree **CLEAN**.
- Version **0.5.356**.
- All five artefacts (SURVEY.md, SUBTUNES.md, presets.json, FIDELITY.md,
  VIBRATO.md) regenerated against a clean tree; FIDELITY.md's stamp reads
  `h2g 0.5.356, aab3799` with no `-dirty`.

## Deliverables

| item | state |
|---|---|
| /runqueue cycles 1-4 | COMPLETE, recorded, merged, pushed |
| the 16 tasks they ran | 14 done, 2 partial (freq-table clause; wrap tie) |
| artefact regeneration | COMPLETE at 4cebef8 |
| preset search run 1 | COMPLETE, one of five adopted |
| preset search run 2 | COMPLETE, one of six adopted then RETRACTED |
| whattask.json | STALE at 9ec3133 -- four tasks done since |
| worktree pruning | NOT STARTED (33 wf_ worktrees, 18 unmerged refs) |

## Open questions

1. **Delta** -- the listening decision, refused at the user's direction at
   v0.5.344 and offered again by both searches. Nothing else blocks on it.
2. **The method doc's section scheme** is exhausted at 7.zzzzz and four tasks
   are blocked behind that decision.
3. **Whether `presets.json` should record per-entry provenance.** It is again a
   whole-search regeneration plus a hand-picked adoption, and its `generator`
   stamp cannot convey that.
4. **Whether the wrap tie should have been merged at all.** It is correct,
   tested and inert; I kept it because the constraint it documents (Goattracker
   cannot express both a subtune's clock and a tie in one command column) is the
   finding. Reversible with `git revert 268cae4`.

## Exact next command

    /whattask            # the plan is four tasks stale at 9ec3133

then, in preference order, and all of them are [main]:

    # 1. the --baseline verdict line that can state the opposite of the truth
    # 2. the fidelity window bias (every file, always against us)
    # 3. the vib quantisation ceiling, now that vib is known to be a step function
</current_state>
