<original_task>
Continuation of long-running work on **H2G**, a signature-based ripper that
converts Rob Hubbard `.sid` files into GoatTracker `.sng`, at
`C:\Users\mit\claude\h2g`. The session opened at **v0.5.233** by being asked to
"read what's next" — the handoff then described v0.5.225 and was twelve
versions stale — and ran to **v0.5.251**.

There was no up-front task. The session was driven by short directives — "read
what next", "continue", "do 2", "push", "what tasks next", and one round of six
`/subtask` forks — each answered before the next was given. The working mode is
the project's established one:

> measure the conversion against the original, find where they differ, read the
> 6502 to learn why, fix it, re-measure across the corpus, and ship or refuse to
> ship on the measurement.

Scope: `python/h2g/` (detect.py, goatwriter.py, tracks.py) plus the measurement
harness (`python/fidelity.py`, `python/presets.py`, `python/songview.py`) and
one new tool (`python/dis6502.py`). The VB6 original was not touched.
</original_task>

<work_completed>

## Summary

**18 commits, v0.5.234 → v0.5.251, all pushed.** HEAD is `f136cf2`, master in
sync with `origin/master`. `977 passed, 2 skipped` at v0.5.250 (the two skips
are environment-gated on `H2G_GT2RELOC`). `Commando.sng` byte-exact throughout.
Working tree clean but for the deliberately untracked `6581.pdf`.

Corpus at v0.5.251: **83 of 95 convertible**, mean melody **88%**, mean wave
**78%**, noise **75904 / 82742**, 45 songs carrying a `--fidelity` setting.
Onset census: **408 of 433 matched (93.8%)**, `flat` 13, `short` 6, `phase` 3,
`partial` 3, `invented` 1, `wrong` 1 — from `372 / 433 (85.9%)` and `flat` 50 at
the session's start.

## The through-line

**Three separate commits began the same way**: an option the preset search had
measured and never selected, where a byte-hash over the corpus showed it was
changing nothing. That check — `hashlib` over `convert()` with shipped presets,
or `--baseline`'s `output_sha` — is now the first move CLAUDE.md prescribes when
a setting is offered and declined.

## Commit by commit

### v0.5.234 `eee5868` — the onset census becomes a mode
`fidelity.py --census PATH`. New: `classify_onset`, `onset_shift`,
`onset_census`, `census_report`, `instrument_stamps`, `ONSET_KINDS`. Computed
inside `_measure` from the traces the `onset` column just scored, so its `match`
count *is* `onset_matched` (a second pipeline would resolve its own subtune —
`--search-subtunes` defaults to 3 — and disagree for reasons unrelated to the
conversion). `flat` misses are grouped by the effect byte recovered from the
instrument name stamp `NN:b5-b6-b7` via `songview.parse_sng`.
Found a defect underneath: the phase test `ours[:-1] == orig[1:]` is vacuously
true on a shape the original holds **constant**, so a note of ours that merely
*ends* inside the window (`noi noi noi --`) read as a one-frame phase error — 3
of the corpus's 6. `onset_shift` now requires the shift to explain something the
unshifted reading does not; the remainder is a new `short` kind.
New `tests/test_onset_census.py` (19), plus one in `test_onset.py`.

### v0.5.235 `d86b15e` — the wave program runs at the player's rate
The census's `$01 x19`: nine files, none with `effect_drum`; in eight, bit `$01`
is the **wave-program gate** and the gated records are exactly the flagged
instruments. Forced on, `--wave-program` changed 1 of 9 files' bytes —
`_wave_program_entries` refused every `multiplier > 1`, and seven of the nine
pack at `-S2`/`-S3`/`-S5`. Each opcode now takes a hold entry
(`_hold_wave_program_entry`, using `_wave_hold_byte`); the lead comes from
`_first_frame_lead` (this was the **fourth** emitter never to call it); the
hold's right side is `$00` because `$80` would re-assert the pattern's note over
an absolute pitch. Also fixed a budget guard I introduced in the same edit
(`len(left) + 3` where an opcode now costs two entries).
Two harness defects fixed in the same commit:
* **the search's window was 10 s while the report's is 60 s** — Sanxion's 10 s
  window holds 1 comparable instrument and 0 original noise frames against 8 and
  1669 at 60 s, so `fidelity_better`'s noise and onset terms were blind. Default
  is 60 now, `presets.build_parser()` extracted so a test can pin it.
* **a failed search silently reverted a song to structural defaults** — W_A_R
  lost a measured `two_stage` to a `ValueError`. A candidate that will not
  convert is skipped and named; a song whose search fails keeps the previous
  entry.
Result: 8 files gain `wave_program`, `onset` to 100% on five, noise landing
within 3% of the original on Shockway Rider (404/404) and Saboteur II (748/753).

### v0.5.236 `3059b3c` — one guard, nine files, every effect-byte routine
`detect._effect_byte_address` opened with `if det.instr_stride != 8: return
None`, switching off **every** routine that reads the instrument effect byte for
the 9 corpus files whose records are 16 bytes, across six call sites. The probe
computes record 0's `+7` and searches for `LDA base,Y`; neither step depends on
the stride. Rikky's block is `TWO_STAGE_SHAPE` byte for byte with its two bytes
at record `+9`/`+11` instead of in a trailing table, and `duration == attack + 2`
holds either way. Five files land within 3% of the original's noise from zero;
`onset` reaches 100% on seven of nine.
Two things checked rather than assumed: bit `$80`'s drum is now detected in six
of the nine and **emits nothing**, because no record there sets the bit; and
`_bound_instruments` found the counter-example its docstring said could not
exist (Powerplay Hockey — patterns name instrument 8 against a bound of 6,
melody 72% → 66%), so it is restricted to `instr_stride == 8`.

### v0.5.237 `e624a09` — a wave-program opcode in the command range is not a jump
Wiz's silent pack failure, unexplained for the project's life. Replicating
`gtable.c:1008`'s `exectable` names it: `OVERFLOW: instrument 2 WTBL from ptr 6`.
`_wave_program_entries` copied an opcode's waveform into the wavetable's left
column, where `$F0`-`$FF` are commands and `$FF` is the jump — Wiz's
`set $FF, 250` became `FF/DE`, a jump to row 222 of a 112-row table. `_wave_byte`
now routes the command range through the `$E0`-`$EF` encoding it already used
below `$10`. New `tests/test_table_validation.py` walks every corpus conversion's
tables by `exectable`'s rules.

### v0.5.238 `f1c2525` — the previous handoff rewrite (superseded by this one)

### v0.5.239 `9469f69` — the wavetable budget is a number the emitters keep
`_wavetable_layout` reserves `WAVE_ENTRIES_PER_INSTR` = 5 per later record;
handed a budget of 5, **197 records across 40 files emitted 6, 7 or 8**.
`_drum_entries` checked the budget only for its sweep; the tick block checked
nothing. Both now decline what does not fit, and the order of surrender is
chosen: the tick block keeps the five-entry shape, `_drum_entries` gives up its
multiplier padding first and only then the tick's hold (at index `len(lead)+1` —
the first draft deleted the noise entry instead, unreachable and wrong).
Byte-identical on all 83 files. **Three test helpers had been pinning shapes only
reachable by overrunning the budget** (`test_noise_tick.py`, `test_effects.py`,
`test_call_rate.py`) and now pass `budget=32`.

### v0.5.240 `af3fbe5` / v0.5.241 `9154ae9` — task tagging
CLAUDE.md gained a rule that every proposed task carries `[subagent]`,
`[main]` or `[user]`, with the criteria; then a correction that a **worktree is
the isolation flag, not a kind of delegation** — the choice is one report or
many, and `isolation: "worktree"` is a property either can carry.

### v0.5.242 `a8ec208` — `dis6502.py`
The scratch disassembler that read Rikky's `AND #$04` block, committed as a tool
with `--at` / `--offset` / `--find` (the last taking `detect.py`'s wildcard
syntax). Pinned against `search_file` and against the ten instructions
§ 7.nnnn quotes. 13 tests. **From fork #7.**

### v0.5.243 `b294e8e` — songview's comparison overlay
`songview.py --compare` traces both sides, joins on ADSR, and renders a table
above the instrument cards with a **declares** column read from our own `.sng`.
Built on `fidelity.onset_shapes`/`classify_onset` so a row cannot disagree with
`FIDELITY.md`. Two defects it found in itself: the join key contained
`--cut-release`'s output (Commando `$295F` vs `$2950`), and `.flag` had no CSS
rule. **From fork #6. The live render check is still owed** — the Chrome
extension reports not connected and Playwright is unavailable here.

### v0.5.244 `7f23df3` — the `hold` column
`sound_runs` / `sound_run_agreement`: how many frames each note keeps a waveform
selected, capped at the next attack, keyed by the ADSR one frame after the
attack. The first measure of note length this repo has had. `--no-test-restart`
moves it 0/6 → 6/6 on Commando, 0/7 → 7/7 on Devils Galop, 0/9 → 9/9 on Monty on
the Run. 9 tests. **From fork #3.**

### v0.5.245 `33c2338` — record what the six forks found
§ 7.pppp (bit `$80`'s phase), § 7.qqqq (the version-0 track dialect and
Rasputin's subtune remap), § 7.rrrr (the outer gate's `RTS` spelling), and
**CLAUDE.md's speed-gate paragraph corrected**: it named eight files as proof the
mechanism "has to be found in the players" after `--skip-gate` had found it in
v0.5.119, and every one of those files now measures 0% out. Artefacts regenerated
**once**, after all six forks landed.

### v0.5.246 `18dc706` — the bit-`$80` drum fires on the note's second frame
`_sfx_drum_entries` fired at offsets 4-5 of a 6-frame period, two frames long,
**on purpose** — a docstring, a constant's comment and three tests all recorded
that the counter was "per voice and free-running". It is zeroed at note start in
both dialects (Bangkok `STA $8934,X` at `$80CE`, Trans-Atlantic `STA $0FAD,X` at
`$08D2`). The measurement that belief rested on was real and misread: opening on
noise at **frame 0** put the drum's pitch on the attack frame. Five files change;
`onset` 80 → 100% (Bangkok) and 86 → 100% (Thundercats), `nrun` 67 → 100% on two.
**The `noise` count moves away from the original on four of five and that is the
fix working** — one frame per period where we emitted two. Star Paws then accepted
`--sfx-drum`, which the search had declined at every previous run: a falsifiable
prediction that held.

### v0.5.247 `6112974` — `hold` becomes a search term
Forced corpus-wide, `--no-test-restart` gains 49 points of `hold` and costs **21
of melody on 68 files with none improving**, so it stays per-song. `hold` is an
**acceptance** term (not in `gave_back`). The guard took three attempts: exact
melody non-decrease blocked seven of eight files over thousandths; the
justification was stitched from two different comparisons; `_closer` sized the
veto wrongly. `_oscillation_lost` holds: the candidate may not end up **more than
twice as far** from the original's rate (After_8 17×, Chicken Song 1.09×).
7 files gained, 0 lost.

### v0.5.248 `764dcb1` — the outer gate's `RTS` spelling
`OUTER_GATE` matched only the `JMP past-the-gate` form; nine files end the same
counter in `RTS` with `BPL +6`. `OUTER_GATE_RTS` added; none of the nine carries
both forms. Formula 1 Simulator melody 88 → 100% (retrig 1.28 → **1.00**), Thrust
75 → 94%, Bump Set Spike 96 → 97%. **Both apparent refutations were misread
instruments**: `--pace` prints a median *and* a least-squares fit and I quoted the
median (2.25 vs the fit's 2.286 = 2 × 8/7); and Bump Set Spike's 96 → 68%
"collapse" is the `-S5` sampling artefact — `--equal-calls` reads 97%.

### v0.5.249 `887baa6` — the `hold` tail is three things
415 instruments measured: −1 × 231, 0 × 90, −2 × 25, +5…+23 × ~38, and six
beyond +50. Grouped by the rate each file packs at, the deficit **vanishes at
`-S4`** (17 of 17 at zero) because it is `gatetimer & $3f` **play calls** early
and a call is a quarter-frame there. **A zero above `-S3` means "not visible",
not "correct"** — now declared in the `hold` Dimension's own description. It
predicted, before the list was looked at, that no file above `-S3` can carry
`--no-test-restart`: all nine are `-S1` but for Delta at `-S2`. The far tail is
other defects wearing a length costume.

### v0.5.250 `6e4f45d` — `$FD` ends a voice's list
Rasputin's `$C094`: `$FD` ends a voice's list (we read anything `<= $FD` as a
pattern number) and `$FE nn` is a **two-byte command that continues** it, its
operand feeding a second gate — a **tempo change mid-orderlist**, decoded and not
emitted. First attempt applied it to all of versions 0/1/3 and **rewrote 23 files
including the byte-exact fixture**; `$FE` really is "tune ended" elsewhere. Gated
on each player's own reader, anchored on the 48 bytes after its `CMP #$FF`: three
files test `$FD` (Knucklebusters, Rasputin, Tarzan) and only Rasputin has the
two-byte `$FE`. Rasputin melody 39 → 71%, seq 38 → 71%; corpus mean melody
87 → 88%. New `tests/test_tracks.py`.

### v0.5.251 `f136cf2` — partition the census remainder
The thirteen remaining `flat` instruments are four situations: 3 decoded and
deliberately unemitted (bit `$02`'s derived dialect), 4 an option detected and
declined (IK+ `$14`, Wiz's two `$01`), 1 a detection gap (Mega Apocalypse
`$0848`, `+7 $44`, `effect_two_stage` False), and **3 one new mechanism in one
player** — Ninja's bit `$02`, a two-stage attack with per-**voice** parameters in
static tables (`alt $CC63 = 11 81 15`, `thresh $CC66 = 04 06 04`,
`mask $CC5D = FE FE FE`). Not emitted: it needs an instrument→voice map that does
not exist.

## The fork round (six `/subtask` agents, one shared working tree)

Three landed as code (#7 dis6502, #6 overlay, #3 hold) and three as findings
(#2 bit `$80`, #4 the track dialect, #5 the speed gate). Notable:
* **The forks shared one working tree.** #7 and #4 declined to commit rather than
  sweep in siblings' work; #6 ran its tests against a half-applied sibling edit
  and said so. I verified #6 and #3 by applying their diffs to a **clean worktree
  at HEAD with `siddump.exe` copied in**, not against the shared tree.
* **Two of my own verification attempts were wrong before they were right** — a
  blast-radius scan that double-applied `to_offset` (5 → 18 files once fixed),
  and a flagged-row regex assuming double quotes where the HTML uses single.
</work_completed>

<work_remaining>

Ordered by value. Tags per CLAUDE.md: `[subagent]` = one agent in its own
worktree (brief it to copy `python/tools/siddump-rt/siddump.exe` in, touch none
of the three generated files, return a `git diff`); `[main]` = this session
only; `[user]` = needs a human.

### 1. Listen — `[user]`
**Nothing has been auditioned since v0.5.209, and eighteen commits now rest on
register evidence alone.** Six WAV pairs are staged in gitignored
`build/listen/` (Shockway Rider, Kings of the Beach intro, Rikky, Mr Meaner,
Saboteur II, Ricochet) as `<name>.original.wav` against `<name>.h2g.wav`, 30 s
each, plus the packed `.sid` and the `.sng`. Regenerate or extend with
`python listen.py <sid_dir> --files A.sid B.sid -t 30 --presets ../presets.json`.
For interactive listening use `.\play.ps1 <file> -Presets presets.json` —
**never launch `goattrk2.exe` directly**.

### 2. Ninja's per-voice two-stage — `[main]` (needs a new capability)
§ 7.wwww. Bit `$02` in Ninja's player is an attack waveform held for a threshold
number of frames, both parameters **per voice** in static tables. Emitting it
requires an **instrument→voice map** built from the patterns, which the converter
does not have. That map would also unlock other per-voice mechanisms, so it is
worth building for its own sake. 1 file, 3 instruments.

### 3. `$FE nn` as a real tempo command — `[main]`
§ 7.vvvv decoded it (Rasputin only): the operand becomes a second gate's reload
mid-orderlist. Emitting it needs a Goattracker tempo command in the pattern.
Note Rasputin's `retrig` is now **1.81** (1332 attacks against 735) where it was
0.27 — over-triggering, possibly related.

### 4. The `hold` remainder — `[subagent]`
46 instruments at −2…−7 and ~38 at +5…+23, neither explained by the call-rate
story of § 7.uuuu. Recompute with
`scratchpad/holdtail.py` (recreate: it converts, packs, traces both sides, and
diffs modal `sound_runs` per instrument).

### 5. Mega Apocalypse's `$44` — `[subagent]`
`$0848` carries bit `$04` and `effect_two_stage` is False for that file. A
detection gap in a file that has other routines; probably a second
`TWO_STAGE_SHAPE` spelling.

### 6. songview's live render check — `[user]` or `[main]`
Owed since v0.5.243. Chrome extension reports not connected; Playwright
unavailable. Serve `build/` over `127.0.0.1` (Chrome MCP cannot open `file://`).

### 7. Nineteen's `$0B06` — `[subagent]`
The census's only `wrong`. Its `+7` is `$A0` and its original hits at offset
**0**, not 1 — a second placement rule for the bit-`$80` drum, on 115 of our
notes against the original's 267, so the modal shape is thin evidence.

### 8. Older, still open
* `songview.py`'s per-instrument original-vs-ours tables exist now; `instrmap.py`
  is still a separate tool doing an overlapping job.
* No noise-pitch column.
* Two mechanisms decoded and unemitted: bit `$02`'s derived dialect (§ 7.iiii,
  gains Chicken Song, costs Hollywood or Bust 11 points of melody) and bit `$10`'s
  global arpeggio (§ 7.ttt).
</work_remaining>

<attempted_approaches>

## Refuted, reverted, or corrected during this session

1. **Applying Rasputin's `$FD`/`$FE` reading to all of versions 0/1/3** — rewrote
   23 files and broke the byte-exact `Commando.sng`. `$FE` genuinely means "tune
   ended" in the rest of the family. **The hash count said the rule was scoped
   wrongly before any fidelity number was read.** Fixed by gating on each
   player's own reader.
2. **Reading `(R+1)/R` as refuted by `--pace`** — twice. `--pace` prints a median
   *and* a least-squares fit; the median quantises (2.25) where the fit is exact
   (2.286 = 2 × 8/7). Then Bump Set Spike's melody 96 → 68% was read as a
   regression when it is the `-S5` sampling artefact (`--equal-calls` → 97%).
   Both hazards were already documented in the repo.
3. **`hold`'s guard, three times** — exact melody non-decrease (blocked 7 of 8
   files over thousandths); a justification assembled from two different
   comparisons (After_8's melody from a *swap*, its oscillation from a *stack*);
   `_closer` sizing the veto by a fraction of the remaining gap (Chicken Song's
   0.32 → 0.29 blocked a 100-point gain).
4. **A `[worktree]` tag** — named the sandbox, not the mechanism. Corrected to
   `[subagent]`, with the worktree as a property of the brief.
5. **A v0.5.234 baseline search in a fresh git worktree** — invalid: a worktree
   has no `python/tools/siddump-rt/siddump.exe` (gitignored), and the harness
   *refuses* a multiplier > 1 song rather than tracing it at the wrong rate, so it
   silently scored only single-speed files (15 selected songs against the real 30).
6. **Shipping the 10 s search's `presets.json`** — it moved 22 files, 24 settings
   lost. Read as "the converter changed under a stale presets.json"; it was the
   window. The 60 s search reproduces every shipped setting and adds only what the
   fix earns.
7. **My own budget-degradation fallback** deleted the noise entry rather than the
   tick's hold. Unreachable (the layout floors budgets at 5) and wrong; found by
   writing the ladder out rather than trusting the comment.
8. **Two verification scans of my own** — one double-applied `to_offset` to a
   file offset (three times across the session, in different guises); one used a
   double-quote regex against single-quoted HTML.
9. **Reverted entirely**: the `RTS` gate was reverted once as "not shippable"
   before the two misreadings above were untangled, then reinstated.

## Not pursued

* Emitting Ninja's per-voice two-stage (needs the instrument→voice map).
* Emitting `$FE nn` as a tempo command.
* A workflow fan-out for the census leftovers — proposed, and the user asked for
  the work directly instead.
</attempted_approaches>

<critical_context>

## Environment

* Repo `C:\Users\mit\claude\h2g`, branch `master`, HEAD `f136cf2`, pushed.
* Corpus (95 files): `C:\Users\mit\claude\c64server\SIDM2\SID\Hubbard_Rob`
* GoatTracker 2.77 source: `C:\Users\mit\Downloads\GoatTracker_2.77\src`
  (`gplay.c`, `gsong.c`, `gtable.c`, `greloc.c`, `gcommon.h`). `exectable` is
  `gtable.c:1008`; the next-note fetch is `gplay.c:905`.
* `build/` is gitignored; `6581.pdf` untracked deliberately.
* **Timings**: `presets.py --fidelity` over the corpus ≈ **1 hour** (60 s
  window); `fidelity.py` over the corpus ≈ 5 minutes; the test suite ≈ 2.5
  minutes.
* `python -m pytest` must be run from `python/` — from the repo root it silently
  finds no tests.
* A **heredoc mangles backslashes**: patch scripts containing regex escapes must
  be written with the Write tool, not `python - <<'PY'`. Line-wise splicing
  (find the line, insert after it) avoids the problem entirely.

## Rules added to CLAUDE.md this session

1. A census of what a column misses is a queue — and it is `--census` now.
2. A degenerate match is not evidence (`ours[:-1] == orig[1:]` on a constant).
3. `presets.py --fidelity` searches at the window the report is published at.
4. A search that fails is not a search that says no.
5. Forcing one option on top of a preset measures the pair.
6. A guard that reads like a sanity check can be a population filter.
7. A byte copied from the player into a Goattracker table is in Goattracker's
   encoding now (`$F0`-`$FF` are commands).
8. A worktree has no build artefacts, and this harness needs one.
9. A guarantee written in the caller is a comment (the budget).
10. A veto on a ratio must be sized, not merely signed.
11. A symptom can be diagnosed right and explained wrong, and the explanation is
    what propagates (the bit-`$80` drum).
12. A column can read 100% because the trace cannot see the defect (`hold` above
    `-S3`).
13. A terminator is a dialect, like a constant — and when a fix's blast radius is
    an order of magnitude larger than the evidence for it, the rule is scoped
    wrongly.
14. Every proposed task carries `[subagent]` / `[main]` / `[user]`.

## Gotchas worth carrying

* **`_voice_addr` returns a file offset, not an address**, as does
  `det.track_lo`/`track_hi`. Running `to_offset` on them again is a mistake I
  made three times in one session and it silently produces a plausible
  population.
* **`--pace` prints a median and a least-squares fit.** Read the fit.
* **A file packed above `-S4` cannot be judged on a normal trace** — siddump
  samples once per frame. Use `--equal-calls`.
* **`fidelity.py --diagnose` before calling any row a conversion bug**;
  Rasputin's subtunes are remapped by its init, so its diagonal comparison is
  different music.
* `presets.py`'s `carried N settings forward` message is suppressed under
  `--fidelity` since v0.5.247 (it described the opposite of what happened).

## Assumptions needing validation

* `onset`'s 4-frame window and exact-match rule are choices, not measurements.
* The `short` kind assumes a class-0 frame inside the window means the note
  ended; it could be a waveform we fail to write.
* Ninja's per-voice tables are read as static because nothing writes them in the
  file image — an init routine writing them through a pointer would not have been
  seen.
* Rasputin's 32-point melody gain is measured on its **remapped** subtune, so the
  level is unreliable even though the movement is not.
</critical_context>

<current_state>

## Repository

* **HEAD `f136cf2` (v0.5.251), pushed; master in sync with `origin/master`.**
* Working tree clean but for untracked `6581.pdf`.
* `SURVEY.md`, `presets.json`, `FIDELITY.md` all regenerated at v0.5.251.
* `Commando.sng` byte-exact.
* Last full suite: **977 passed, 2 skipped** (at v0.5.250; v0.5.251 changed no
  code).

## New surface added this session

* `python/dis6502.py` + `tests/test_dis6502.py` — a 6502 disassembler with
  `--at`/`--offset`/`--find`
* `fidelity.py` — `--census`, `classify_onset`, `onset_shift`, `onset_census`,
  `census_report`, `instrument_stamps`, `sound_runs`, `sound_run_agreement`, the
  `hold` Dimension
* `presets.py` — `build_parser()`, `-t` default 60, skip-and-name on a failed
  candidate, carry-forward on a failed search, the `hold` acceptance term,
  `_oscillation_lost`
* `songview.py` — `--compare` overlay, `pair_by_adsr`
* `goatwriter.py` — `_hold_wave_program_entry`, `WAVECMD_BASE`, `OUTER_GATE_RTS`,
  budget guards in the tick and drum shapes, the corrected `_sfx_drum_entries`
  phase
* `detect.py` — `_effect_byte_address` without the stride guard,
  `_find_track_terminators`, `track_fd_ends`, `track_fe_command`,
  `_bound_instruments` restricted to stride 8, `import re`
* `tracks.py` — `_build_track(fd_ends=, fe_command=)`
* New tests: `test_onset_census.py`, `test_table_validation.py`,
  `test_sound_runs.py`, `test_tracks.py`, `test_dis6502.py`, plus additions to
  `test_onset.py`, `test_wave_program.py`, `test_call_rate.py`,
  `test_preset_passthrough.py`, `test_two_stage.py`, `test_effect_bit80.py`,
  `test_instrument_bound.py`, `test_effects.py`, `test_noise_tick.py`

## Method-doc sections added

§ 7.jjjj through § 7.wwww — the census as a mode, the wave program's rate, the
stride guard, the `$FF` opcode, the budget, the drum's phase, `hold` as a search
term, the `RTS` gate, the `hold` tail, the track dialect, and the census
partition.

## Open questions for the user

1. **Nothing has been listened to for eighteen commits.** Six pairs are staged.
2. Whether to build the **instrument→voice map**, which is the prerequisite for
   Ninja's mechanism and probably others.
3. Whether the songview render check matters enough to connect Chrome for.

## Immediate next action

**Listen.** Every remaining code item is a ship-or-refuse decision resting on
columns that have twice this session been shown to measure the wrong thing —
`hold` reading 100% where the trace is blind, and `melody` reading 68% where the
conversion is right. A listener is the only instrument here that has never been
wrong.
</current_state>
