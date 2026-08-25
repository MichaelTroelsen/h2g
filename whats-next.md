<original_task>
Two threads, both driven by the user in one session.

**A. Make 5 Title Tunes' fidelity understood and, where possible, better.**
Opened as "add to todo: work on song 5 Title Tunes fidelity", sharpened by two
screenshots of the A/B page's pattern view. The user's own framing: *"This is
important for me to report back to which instrument on which channel do not have
fidelity."* Later narrowed by a direct claim to test: *"so it is instrument 5
that is not fidelity."*

**B. Drain `.claude/tasks/whattask.json` with `/runqueue`**, regenerating the
plan with `/whattask` between drains, committing and pushing each cycle when the
user asked.

A third thread arrived mid-session from the same screenshots: the pattern view
showed `instr 00` on note rows and the user read it as *"The instruments are
missing."*

NOT in scope, and deliberately untouched: committing without being asked
(every commit in this session was an explicit user instruction), and anything
`requires-user`.
</original_task>

<work_completed>

## Commits shipped (all pushed to origin/master)

| sha | version | what |
|---|---|---|
| `f1dab41` | v0.5.374 | staleness banner keyed on the `.sng` sha |
| `80baad8` | v0.5.375 | the shifted-subtune line stops explaining the defect away; `listen.py` recovers `matched_subtune` |
| `c038484` | v0.5.376 | the ±5 s length rule; Action Biker approved |
| `c014057` | v0.5.377 | 5 Title Tunes pulse census — `pul` artefact, `pspan` defect |
| `2371f16` | v0.5.378 | atomic page build; pulse free-run census says two voices |
| `be06971` | v0.5.379 | pulse free-run **declined**; the docstring that hid it corrected |
| `adb5f07` | v0.5.380 | the `wave` 90% frame named |
| `788f0bf` | v0.5.381 | the `adsr` deficit is half the gate task and half inaudible |
| `4a34457` | v0.5.382 | `--hard-restart-frames`; 5TT gate 50 → 75 |
| `a10419f` | v0.5.383 | FIDELITY.md regenerated |
| `5b2f3f3` | v0.5.384 | a note row shows the instrument that sounds |

## 5 Title Tunes — fully accounted for

**One population, three registers.** 935 original release runs of 4 frames each;
every remaining column is a different view of them:

```
wave  90%    935 frames  = the trigger tick's $09 firstwave byte
gate  50%   1873 frames  = 2 wrong frames per run + 3 short runs   -> now 75%
adsr  58%   3743 frames  = those same 1873 + 1870 inaudible AD frames
```

melody, seq, pitch, onset, retrig, drift were already exact (100/100/100/100/1.00/+0.0).

- **`wave`** — the LAST frame of each 4-frame run, position `(4,-1)` on all 935,
  carrying `FIRSTWAVE_TESTBIT = 0x09` (`goatwriter.py:263`, written at `:2594`).
  The packed player doesn't run the wavetable on a note's first call
  (`player.s:908-911`), so `$D404` there is entirely the firstwave byte. It is
  also the only frame below `$10`, which is what lets siddump name our attacks
  (`siddump.c:434-437`). **The price of attack alignment, not a wrong waveform.**
- **`gate`** — `HARD_RESTART_FRAMES = 2` against a uniformly 4-frame original
  gap. **Fixed to 75%** via `--hard-restart-frames 4` + `max_hard_restart`.
  **75% is the ceiling**: `gplay.c:334` stops the song if the gatetimer exceeds
  the channel tick, so a 4-call row can never gate off for 4.
- **`adsr`** — the register is **AD (`$D405`), not SR**: AD-only differs 1509,
  SR-only **0**, both **0**. The task's proposed `CMD_SETSR $00` would change
  nothing. Splits 1870 both-gated-off (inaudible) + 1873 = the gate deficit
  restated.
- **`hold` 0% / `nrun` 0%** — both **refuted**. `hold`: 7/7 instruments `fetch`,
  zero short/long. `nrun`: one instrument, 62 runs each side, 12 vs 11 frames;
  `noise 682/744` **is** 11/12, so noise and nrun are one fact twice.

**Per instrument per channel, re-measured at HEAD on a fresh conversion** — the
direct answer to the user's question:

| ch | GT instr | ADSR | frames | wave | adsr | gate |
|---|---|---|---:|---:|---:|---:|
| 1 | 1 | `$2400` | 1024 | 87.6% | 50.0% | 87.5% |
| 1 | **5** | `$5700` | 945 | 87.4% | 49.9% | 87.4% |
| 1 | 7 | `$0400` | 1024 | 87.5% | 50.0% | 87.5% |
| 2 | 2 / 8 / 6 | — | — | 87.4–87.6% | 49.9–50.0% | 87.4–87.5% |
| 3 | 3 | `$5830` | 2993 | 93.8% | 75.0% | 93.7% |

**No instrument is worse than any other.** Instrument 5 trails 1 and 7 by
0.1–0.2 pp purely because it sounds on 945 frames against 1024 — same integer
error, smaller denominator. The deficit is **per note**: 1 wrong wave frame,
1 wrong gate frame (was 2), 4 wrong adsr frames. Channel 3 looks better only
because its notes are 16 frames against 8.

## Features shipped

- **`--hard-restart-frames N`** (v0.5.382) — per song, sets `want` in
  `_hard_restart_ticks`. Threaded through `_hard_restart_ticks`,
  `_write_instruments`, `build_sng`, `convert()`, the CLI,
  `fidelity._preset_opts` and `presets.EXCLUDED_FROM_ALWAYS`.
  `presets.json` gives 5TT `hard_restart_frames: 4` + `max_hard_restart: true`.
- **Staleness banner** (v0.5.374) — `staged_sng_sha`, `audio_provenance`,
  `audio_banner`, index column. Keyed on the **conversion**, never `__version__`.
- **Atomic page build** (v0.5.378) — `_atomic_write`, per-build `build_id`,
  `check_build_consistency`, `_instrmap_is_fresh` + `--instrmap-force`.
- **Inherited-instrument display** (v0.5.384) — `row_schedule` carries the last
  non-zero instrument forward per channel and flags it; the view shows what
  sounds, dimmed/italic, keeping the literal `00` in the data.
- **`--search-subtunes` line rewritten** (v0.5.375) — it had *asserted* the
  benign cause and explained a real defect away for the converter's whole life.
- **`listen.py` recovers `matched_subtune`** from `build/fidelity.json`
  (v0.5.375) — first observed working in the wild during this session's restage.

## Artefacts rebuilt

- **`build/listen`** — all 83 tunes restaged (`--voices -t 120`, 6 shards).
  Provenance went **77 behind → 83 current**. Measured 1m22s/tune, ~20 min
  sharded — the plan's "hours, ~28 GB" estimate was wrong by ~30×.
- **`build/instrmap`** — 84/84 `.md` rebuilt; the run was killed mid-way and
  finished with a plain `abpage.py` (the tracing is cached in `instrmap.json`).
- **`docs/FIDELITY.md`** (v0.5.383) — one row moved, mean gate 54 → 55%, corpus
  ringing 110475 → 109540 (a drop of exactly 935).

## Refutations (the session's dominant output)

Six columns across three files turned out to be **measurement artefacts, not
converter defects**: ACE_II `slides` 1.61x, `bend` 0.48x, `hold` 43%;
Action Biker `hold` 0%, `nrun` 0%; 5TT `hold` 0%. Plus:

- **pulse free-run declined** — mechanism confirmed in both players
  (`player.s:859-866`, `gplay.c:375-379`), but the census found **2 of 72
  voices** qualify = 0.76% of corpus pulse movement.
- **`f2c86f2` superseded** — 98% of its added lines already in master; its only
  unique content asserts **Spellbound = 4** where `f63caa1` settled **3**.
  Third superseded branch this session (with `4663ffa`, `55f5f12`).

## Selection gaps found

- **`rest_envelope_silence` is unreachable** — in `EXCLUDED_FROM_ALWAYS` *and*
  absent from `FIDELITY_TOGGLES`; 0 of 83 songs carry it against a commit titled
  "five songs take the rest-envelope silence". Proven a *selection* gap (forcing
  it moved `output_sha`). `rest_wave_silence` sits identically.
- **`_preset_opts` coerced every option to `bool`** — fixed by the last cycle
  (annotation-driven), uncommitted.

## Uncommitted right now

`python/fidelity.py`, `python/h2g/sidfile.py`, `python/tests/test_fidelity.py`,
`python/tests/test_freq_table.py`, `.claude/tasks/runs.jsonl`,
`.claude/tasks/whattask.json`. **Verified**: full suite 1508 passed / 2 skipped;
corpus byte-identical 83/83 against a clean `git archive HEAD` export.
</work_completed>

<work_remaining>

## 0. COMMIT THE LAST CYCLE — do this first
Six files above. Everything is verified; nothing is running; locks are empty.
The next cycle would otherwise run on top of unreviewed work.

## The plan
`.claude/tasks/whattask.json` at HEAD `5b2f3f3` — **15 tasks, 14 ready**, all
`serial` (`python/fidelity.py` and `presets.json` appear nearly everywhere).
Delegable and mutually compatible: `gate-census-is-file-level-not-per-voice`,
`per-instrument-sweeps-should-print-every-scored-column`,
`skate-or-die-intro-drift-plus-200-is-not-the-gate-skip`.

Highest value, in order:
1. **`rest-envelope-silence-is-unreachable-through-presets`** [main, opus] — a
   whole feature nothing can select. Check `rest_wave_silence` in the same pass.
2. **`hard-restart-frames-is-not-searchable`** [main, opus] — the option is an
   int and `--fidelity` walks booleans. 17 songs carry `max_hard_restart` and
   **zero are multiplier 1**, so single-speed files are the unclaimed gain.
3. **`len-dimension-original-vs-ours`** [main, sonnet] → unblocks
   `orderlist-silent-park-for-fe` [main, opus], the ±5 s rule's emitter half.
4. **`adsr-counts-inaudible-gate-off-attack-decay`** [main, sonnet].
5. **`international-karate-voices-never-set-an-instrument`** [main, opus] — the
   *real* "instruments are missing" case (below).

## Carried forward from the PREVIOUS handoff — still open, do not lose
These were in the 440-line version of this file and are **not** in the plan:
- **`vibrato-cmp-quantisation-limits-the-tick0-correction`** [main] — `ebc9d1a`
  pushes 15 files further from the original's oscillation rate (Mozart 2.03x).
  The `row_calls` fix is REFUTED (12 of 15 cannot move); the correction is
  QUANTISED (half-period is `cmp + 2` calls, so at cmp 0 none is possible);
  `vib` is a STEP function, so judge candidates against that, not a ratio.
- **`fidelity-window-loses-startup-lag-frames-of-the-original`** [main] —
  `_measure` traces both sides for `nframes = seconds * 50` (`fidelity.py:3374`)
  and passes `lag` only as an alignment offset; the window is never extended, so
  the original's last 3–8 frames have no counterpart and are scored against us
  on EVERY file. Two fixes: trace ours for `seconds + lag/50`, or truncate the
  original at `nframes - lag`. Either moves every sequence figure, so the report
  must say numbers either side are not comparable.
- **`vib-census-shape-classifier`** [subagent].
- **`stale-worktree-branches-hold-nothing-unique`** [main] — now with three
  confirmed-superseded branches (`4663ffa`, `55f5f12`, `f2c86f2`).

## Smaller, cheap
- **Re-stage 5 Title Tunes** — its page is `behind` (staged `70f66233`, today
  `9c289239`); the page predates the gate fix so its numbers are the old
  conversion. ~90 s + a page rebuild.
- **`vibrato-plain`'s verify cites content that no longer exists** — it says the
  four-way split is "in whats-next.md item 3". That file was rewritten whole at
  `c787ac9` and item 3 is now a census helper. **Recover the split from
  `c787ac9^:whats-next.md` or re-derive it**, and fix the verify.
- **`-t 120` has no written rationale** — `listen.py`'s own default is 30
  ("long enough to reach a second section"). 120 appears in `README.md:3162`
  and `listen.py:652` with its cost but no reason. Worth a sentence.
</work_remaining>

<attempted_approaches>

## Refuted by measurement (do not retry)
- **`CMD_SETSR $00` at note end for 5TT `adsr`** — SR agrees on every frame.
  The differing register is AD.
- **Raising `HARD_RESTART_FRAMES`** — byte-identical at 2, 3, 4, 5
  (`sha b49462e6553e`). `bound = row_calls // 2` = 2 caps `min(want, bound)`
  before the constant is read.
- **Pulse free-run via zero pulse pointer** — works, reaches 2 of 72 voices.
- **Merging `f2c86f2`** — superseded, and its unique content is wrong.
- **`--rest-envelope-silence` for AWM's gate** — moves `output_sha`, leaves
  gate/ringing/melody/sequence **bit-identical**. It zeroes the envelope at a
  bit-6 rest; a Goattracker gate is a different register.
- **"Fixing the gate will move `adsr`"** — my own prediction, refuted: at ticks 3
  `adsr` stays 0.5831. The frame changes bucket and still disagrees.

## My own errors, each caught and each cheap to repeat
1. **Compared frame k to frame k without `startup_lag`** — reported 0% of the
   adsr disagreement on gate-off frames, the exact opposite of the truth.
   Applying `lag=5` reproduced the census's 3743 exactly. *Caught by
   disbelieving the answer.*
2. **`grep -l staleaudio`** matched 84 pages — that's the CSS class name, present
   in every stylesheet. Grep the banner's visible text.
3. **A substring anchor** (14 spaces + `max_hard_restart: bool = False,`) matched
   INSIDE the more-indented line, patching the wrong function. SyntaxError.
4. **A bare `%` in argparse help** — `--help` raised "badly formed help string",
   54 subprocess tests failed. Escape as `%%`.
5. **`pack_sid(path)`** — it takes bytes and a multiplier.
6. **`find_music_subtunes(sid, det)`** — takes one argument.
7. **`_span` includes zero** — my first band measurement contradicted the shipped
   row; `_span` excludes zero by design.
8. **Python wrote CRLF** into a workflow script — "control characters" rejection.
   Write with `newline="\n"`.
9. **Heredoc quoting** broke on an apostrophe — use the Write tool for scripts.

## Agent errors caught by verification
- **A subset-column sweep** omitted `pitch`, which falls 1.0000 → 0.9836 on the
  combination it recommended. **Second occurrence** (v0.5.352/353 was the first,
  shipped and retracted). Now a task.
- **An agent returned `evidence: "See prior analysis in transcript"`** — thin
  where the reasoning mattered; its numbers held on re-check.
- **An agent skipped the full suite**; the orchestrator ran it.

## Infrastructure failures
- **An agent died on API 500** after 52 tool calls, leaving good work and no
  record. Recovered by inspecting the tree.
- **A background `--instrmap` was killed** mid-way, leaving 33 of 83 pages
  claiming stale audio that was current. Finished cheaply with a plain
  `abpage.py` — the tracing is cached in `instrmap.json`.
</attempted_approaches>

<critical_context>

## The rule the user added this session
**A conversion must be the same length as the original, within ±5 s.** Now a
CLAUDE.md invariant. No column enforces it: `drift`, `retrig` and `--pace` all
measure the rate of a ROW and are satisfied by a conversion that plays the right
music at the right speed **forever**. Action Biker: `drift +0.0`, `retrig 1.00`,
three times too long. Cause: Hubbard's `$FE` = tune ended, which a Goattracker
orderlist cannot say.

**`original_ended` is a defect queue, not a methodology note** — it shortens the
comparison window so our surplus is not charged, protecting the score while the
shipped `.sng` plays on. Same shape as the `--search-subtunes` line.

## Verification patterns that earned their keep
- **Corpus byte-hash against `git archive HEAD` in a scratch tree** — never a
  stash (banned here). Caught two defects that would have shipped silently:
  the option not inert when unset (24 files moved, because `_preset_opts` passes
  `False` not `None`), and the option reaching nothing once set (`bool(4)` → 1).
- **AST comparison with docstrings stripped** — proves a docstring-only change
  cannot move bytes. Stronger than a corpus hash, which a missed file can defeat.
- **Deriving a row-level number from frame-level structure** — 935 × 2 + 3 =
  1873 = the shipped `gate_ours_ringing`. The strongest evidence in the session.
- **Assert your own success rate before comparing** — `test_row_budget.py`'s
  `converted >= 80` refused to conclude from 0 successful conversions.

## Gotchas
- **`instr 00` means "keep the current instrument"**, not "no instrument".
- **Instrument numbering**: `songview`'s `instruments[0]` has `number = 1`.
- **`_preset_opts` passes `False` for absent keys**, not `None`.
- **Ints must be in `_PER_SONG_OPTS`** — until the (uncommitted) fix.
- **`gplay.c:334`** stops the song if the gatetimer exceeds the channel tick.
- **`_span` excludes zero**; `wave_compare` ignores the gate bit.
- **The staged `.h2g.sng` is the audio's provenance** — `listen.py` packs the
  same object it writes (`listen.py:686-703`).
- **Every unmerged branch checked this session was superseded** — hash the
  branch's ADDED lines against master's current file; don't read the diff.

## Two genuinely different "instruments missing" cases
- **5 Title Tunes** — inheritance. 160/160/32 note rows carry `00` and inherit.
  Fixed in the display at v0.5.384. **Not a defect.**
- **International Karate** — channels 1 and 3 set **no instrument on any row**,
  91 rows each. **A real defect**, and what `--initial-instrument` exists for —
  off by default because the index array is mutable player state and a
  multi-subtune snapshot catches it mid-tune.
- **Pygmies Revenge** — 256/4/128 zero rows, all *before* that channel's first
  setter. Correct as-is.

## Environment
- Corpus: `C:/Users/mit/claude/c64server/SIDM2/SID/Hubbard_Rob` (95 files, 83 convert)
- `sidplayfp`: `C:/Users/mit/Downloads/sidplayfp-2.15.2-32bit-mmx/sidplayfp.exe`
- GoatTracker sources: `C:/Users/mit/Downloads/GoatTracker_2.76/src` and
  `goattracker2/src` (has `player.s`)
- `build/` is gitignored. 12 CPUs. Full suite ≈ 5m40s.
- Locking: `serial.lock` + `serial.lock.d` mutex; `.tmp` + `mv -f`, never truncate.
</critical_context>

<current_state>

**HEAD `5b2f3f3` (v0.5.384), pushed. 11 commits this session, all user-authorised.**

**Uncommitted (verified, ready to commit):**
`python/fidelity.py`, `python/h2g/sidfile.py`, `python/tests/test_fidelity.py`,
`python/tests/test_freq_table.py`, `.claude/tasks/runs.jsonl`,
`.claude/tasks/whattask.json`. Suite 1508/2; corpus byte-identical 83/83.

**Untracked and NOT mine — never stage these:** `.claude/settings.json.graphify-bak`,
`arkiv/BMX Kidz.sng`, `arkiv/Hubbard_Rob/`, `arkiv/The Chicken Song.sng`,
`arkiv/Zoids.sid`, `arkiv/Zoids.sng`, `graphify-out/`.

**Locks:** `serial.lock` is `[]`. Nothing running. No orphaned children.

**Artefact freshness:**
- `docs/FIDELITY.md` — current at `a10419f`, **stale against the uncommitted
  cycle only if that cycle moved bytes; it did not** (byte-identical).
- `presets.json` / `docs/SURVEY.md` — current. **Do not regenerate `presets.json`
  blindly**: its carry-forward is keyed on `FIDELITY_TOGGLES`, and
  `hard_restart_frames` is an int the boolean search cannot represent, so a
  regeneration could silently drop 5TT's measured `4`.
- `build/listen` — 82 of 83 current; **5 Title Tunes is `behind`** (staged
  `70f66233`, today `9c289239`), predating the gate fix.
- `build/instrmap` — current at `2371f16`.

**Open questions / pending decisions:**
- `hard-restart-frames-is-not-searchable`: derive the release length from the
  player, or let the search try a small set of values? Not decided.
- `max-hard-restart-should-perhaps-ignore-want`: the cheaper route to the same
  gain, but it moves multiplier-2 row-8 files 4 → 7, so all 17
  `max_hard_restart` songs re-convert and presets must be re-searched. **Decide
  between this and the per-song lever before building either.**
- `adsr-counts-inaudible-gate-off-attack-decay`: drop the frames or document
  them? Not a shim either way — the difference is provably inaudible.

**Backlog not in the plan:** `runs.jsonl` holds ~161 opened-but-never-run ids.
The plan carries the 29 from recent commits that are actionable plus the
partials; the rest stay in the log deliberately.

**This file replaces a 440-line handoff from an earlier session.** Its four
still-live items are carried into `work_remaining` above. Everything else in it
was closed by commits since — including the `--baseline` verdict line
(`73354bd`) and the `retrig`/`hold`/`tail` probe reachability (`c787ac9`).
</current_state>
