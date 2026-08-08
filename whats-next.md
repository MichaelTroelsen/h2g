<original_task>
Continuation of work on **H2G**, a converter from Rob Hubbard `.sid` files to
GoatTracker `.sng`. The session opened with `read what next` against the
previous handoff (then at v0.5.95, in `c64server/hubbard/`) and was driven as a
sequence of single-item directives, each answered before the next was given:

1. `read what next` → summarise the open items and recommend
2. `do 7` → §7, measuring the `-S2` group at its real call rate
3. `/subtask do 4`, `do 5`, `do 6` → three forks in parallel
4. `merge them all and regenerate`
5. `commit and push`
6. `what about the improvements you did to the fidelity tools?`
7. `do both PRs` → upstream siddump, and SIDM2conv
8. `we should work on H2G` → drop the SIDM2 thread
9. `what github` / `why can this repo be its own repo?` / `prepare the split` /
   `make it public and do the cutover` / `delete the hubbard folder` /
   `rm -rf hubbard and clean up the worktrees`
10. `work on 7b in the new repo`, then `loosen the shape`, `run --ticks on
    those five`, `do spellbound next`, `do action_biker next`, `check the
    sticky duration dialect`, `do the static check`, `go on`
11. `do 1, start with tarzan` → encode the skip counter
12. `do 8` → the fractional-row problem
13. `why does -S5 regress?` → `check the gatetimer` → `check the wavetable` →
    `do the equal-calls mode` → `do the vice per-call trace`

Standing rules from `CLAUDE.md` that shaped every commit: bump the version on
every commit; regenerate `SURVEY.md`/`presets.json`/`FIDELITY.md` on a settled
tree, once; never ship a fake success; keep `Commando.sng` byte-exact; stage
only project paths by pathspec.
</original_task>

<work_completed>

## Headline

| | start (v0.5.95) | now (v0.5.127) |
|---|---:|---:|
| corpus mean melody | 78% | **78%** as traced, **86.3%** at equal sampling |
| files "playing the same music" (95-100%) | 27 | **34** |
| files "playing something else" (0-50%) | 17 | **14** |
| tests | 547 pass / 3 skip | **651 pass / 3 skip** |
| home | `c64server/hubbard/` subdirectory | **its own public repo** |

`Commando.sid` → `Commando.sng` **byte-exact** throughout.

## The repository moved — this is the most structural change

H2G now lives at **https://github.com/MichaelTroelsen/h2g** (public, `master`
at `fe79a92`, v0.5.127, 121 commits). It was extracted from
`SIDDetector2/hubbard/` with `git subtree split --prefix=hubbard`, so the whole
history came with it.

- Local clone: **`C:\Users\mit\claude\h2g`** — this is where work happens now.
- `SIDDetector2` `master` (`4ebf6ca`) has `hubbard/` **deleted**. Verified
  before removal: all 106 tracked files present in the new repo, a fresh clone
  green, no tracked file elsewhere referencing it.
- An **empty `C:\Users\mit\claude\c64server\hubbard` directory** remains only
  because this session's shell is parked in it. `rmdir` it from any other
  shell.
- Three stale worktrees removed (`c64server-s7`, `c64server-corpus`,
  `scratchpad/wt-vibrato`).

**The corpus did not move.** It is HVSC-derived and belongs to the SIDM2
submodule. `H2G_CORPUS` points at it; default
`C:\Users\mit\claude\c64server\SIDM2\SID\Hubbard_Rob` (95 files, 832 KB).
Before v0.5.103 fourteen test files hard-coded that absolute path and five had
no existence check, so a corpus-less clone **failed**; now it skips (579 pass,
32 skip on a corpus-less checkout).

## Upstream PR

**https://github.com/cadaver/siddump/pull/9 — OPEN.** Adds `-m<n>`,
playroutine calls per displayed frame. Rebased onto upstream **V1.10** (the
vendored copy was 1.08; the main loop was unchanged so it applied cleanly),
rebuilt and verified there: default *and* `-m1` byte-identical to stock 1.10.
Head branch `calls-per-frame` on the `MichaelTroelsen/siddump` fork.

A second PR against `SIDM2conv` was **investigated and deliberately not
opened** — see attempted_approaches.

## §7 — the `-S2` group, measured at its real rate (v0.5.98/0.5.99)

`python/tools/siddump-rt/` is siddump 1.08 vendored (BSD, notice retained)
plus `-m<n>`. A dump row stays one PAL frame of real time whatever the call
rate. `fidelity.py` passes each song its multiplier and **refuses** a
multiplier > 1 song on a binary without `-m`.

Verified rather than assumed: `-m1` byte-identical to stock; the `-S` stub is
at the packed file's **init** address, writes `0x4cc7/multiplier` to timer A
and falls through to the player, with the play address being the player itself
(`greloc.c:140`, `:1616`, `:1636`); the same `.sng` packed at `-S1` and `-S2`
traces identically at a given `-m`.

## §7b — the speed gate is under-read, and why (v0.5.105 onward)

**The mechanism.** Three instructions above the speed gate sits a second
counter of the same shape:

```
DEC outer / BPL +8 / LDA #O / STA outer / JMP past-the-gate
DEC gate  / BPL +6 / LDA reload / STA gate
```

On the frame the outer counter underflows the gate's own `DEC` is jumped over,
so **frames per row = (reload + 1) × (O + 1) / O**. `(O+1)/O` is exactly the
`N/(N−1)` family the measurements kept producing (9/8, 5/4, 4/3, 3/2 are
O = 8, 4, 3, 2) and it yields the non-integer rows no whole skip count
explained. **Validated on 15 independently timed files: within 5% on all 15,
within 1% on 10** — and re-checked under v0.5.114's confidence gate, where 13
still report and all 13 agree.

**The decoy that broke v0.5.102.** `O` is an *immediate operand* and the init
self-modifies it from a second per-subtune table (Tarzan `LDA $59EA,X /
STA $5561`). The byte in the file image is whatever the last init left — 11 for
Tarzan against a real 2. **32 of the 51 files carrying the counter take it from
a table.**

**Four dialects, two sites** (v0.5.108): above the gate with a `JMP`; at the
play entry with an `RTS` (Warhawk `$1012`); zero-page at the play entry
(Spellbound, `C6`/`85` not `CE`/`8D`); a runtime-chosen reload then `STY/RTS`
(Las_Vegas); `BMI` to a lighter routine (Action_Biker). `OUTER_GATE` still
matches only the first — widening it is unfinished work.

**`$02A6`, the PAL/NTSC flag** (v0.5.109/0.5.110). Four corpus files read it;
three branch on it to skip frames in NTSC compensation. siddump starts it at 0
(NTSC), so those were traced on the wrong machine. `siddump-rt` gained
`-v<0|1>`; `fidelity.py` sets 1 by default, `--ntsc` reverts, and the
requirement is scoped by `reads_video_flag()` to just those four files.
**Phantoms_of_the_Asteroid left the defect list entirely** — its row is 2.00,
exactly its gate. Skate_or_Die_intro selects *tuning constants* by machine, so
its 100% was scored against the wrong machine and is now 90%.

## §7b tooling — three instruments, each catching the one before

- **`--pace`** (v0.5.101): times the conversion against the original over
  difflib-matched notes; reports the **median** ratio (a least-squares fit
  follows one resting voice — 0.727 against a true 1.509 on ACE_II).
- **`--ticks`** (v0.5.103, by a fork): reads the sequencer period out of the
  *original alone* via `siddump -z` cycles per frame. Gated hard; speaks on 31
  of 95 and agrees with `--pace` on 18 of 18.
- **`--equal-calls`** (v0.5.125): traces our conversion at one call per frame
  over `multiplier × seconds` — same music, same play calls, sampled as finely
  as the original. Frame-aligned dimensions are **dropped, not approximated**.
- **`python/vicetrace.py`** (v0.5.126): VICE's `dump` sound device writes the
  whole SID state **on every rasterline**, 312 samples a PAL frame, no monitor
  scripting. Block index ÷ 312 is the frame.

**Confidence gating** (v0.5.114): `pace()` requires `MIN_PACE_GAPS = 40`
matched gaps, `MAX_PACE_IQR = 0.10`, and `MIN_PACE_COVERAGE = 0.30`. 59-60 of
95 files report a row; the rest refuse with a reason.

## §7b/§7c — what the measurements actually settled

| file | outcome |
|---|---|
| Tarzan | row 3.00 (three methods agree); gate reads 2 |
| Deep_Strike | 2.67, alternating 3,3,2 tick pattern |
| Ricochet | 2.00, the control — O=127, one skip in 128 |
| Warhawk | play-entry `RTS`, period 8 → 2.29 vs measured 2.25 |
| Las_Vegas | PAL period 5 → 3.75 (the 4.50 was NTSC) |
| Bump_Set_Spike | `$02A6` block sits *past* the play address; period 10 → 3.33 exactly |
| Human_Race | CIA-timed; `--ticks` says 3.98 against a gate of 4 — **gate right** |
| Spellbound | row **2.20**, by mod-N over running frames |
| Action_Biker | no skip at all (`$C000` reloads 0); ticks every 3 = its gate |

**§7c (rows per note) is dead.** The static check decoded every pattern from
Spellbound's own fetch rules and compared against what the converter emits:
**41/41 patterns exact, ratio 1.0000**, with Warhawk 49/49 and Commando 44/44
as controls. Our rows equal the player's units.

## §1 (of the old numbering) — the skip counter encoded (v0.5.119/0.5.120)

`convert(skip_gate=True)` / `--skip-gate` writes the corrected row.
`SongSpeeds` gained `exact_row()`, `encodable_frames()`, `skip`,
`skip_table_addr`; `goatwriter` gained `effective_frames()` and
`MAX_ROW_DENOMINATOR`. **On by default** via `presets.json`'s `always` block.

- Tarzan melody 73% → **96%**, timing 0.667 → **1.000**
- Pygmies_Revenge 80% → **93%**

## §8 — solved by discarding its own premise (v0.5.121)

§8 framed a fractional row as needing *re-gridding*. It does not: a row lasts
`tempo / multiplier` frames, so **a row of `p/q` frames is exact at `-Sq` with
a tempo of `p`**. 8/3 frames is `-S3` at tempo 8, with the note count
untouched.

Twenty files changed. Deep_Strike **14% → 100%**, Saboteur_II **25% → 98%**,
Chain_Reaction/Thundercats/W_A_R/W_A_R_Preview/Shockway_Rider/Lightforce to
100%, Zoolook 43% → 77%. Corpus mean melody **74.8% → 78.3%**; files playing
the same music 27 → 35.

`MAX_ROW_DENOMINATOR = 6`, bounded by **playability**: six calls a frame is
~9k cycles of a PAL frame's 19656; ten would be three quarters of it, and rows
beyond six are within ~1.3% of a whole number and round.

## Merges, artefacts and the other forks

Three `/subtask` forks ran in isolated worktrees and were merged:

- **§4** (`d558474`, v0.5.96) — effect bit `$80` is three blocks, not one:
  nine files' is the game's sound effect (dead in a rip), two a per-instrument
  wave program (ACE II `$E357`, Auf Wiedersehen Monty `$E743`), one a stepped
  frequency table. Read, not encoded.
- **§5** (v0.5.97) — Hollywood or Bust's LFO-table vibrato, and a correction:
  gplay's vibrato half-period is `cmp + 2` calls, not `cmp / 2`, so the
  shipped classic mapping oscillates at ~half the player's rate for all 56
  files it covers. **Flagged, not fixed.**
- **§6** (v0.5.97 → renumbered) — three of four "plays something else" files
  are the harness: `fidelity.py --diagnose` was built, and two files carry
  subtune-remapping wrappers in their own init.

Version collisions were resolved at merge time (§6 kept 0.5.97, §5 became
0.5.98, §7 became 0.5.99, regeneration 0.5.100).

</work_completed>

<work_remaining>

## 1. The listening pass — still never performed

**The one item that requires a human.** Staged WAV pairs were in the deleted
`hubbard/build/listen/` and must be re-staged:

```sh
cd python
python fidelity.py <corpus> --from-json ../build/fidelity.json -n 1 -t 20   # listen.py
```

In ~45 versions of fidelity work, exactly one file has ever been listened to.
Every instrument built this session measures registers; none hears anything.
Blocks §2 and §3 below.

## 2. The drum is under-rendered — `W−1` steps, we emit one

The gate is understood (v0.5.90/91); the open question is *how much*. All five
wavetable entries are in use, so lengthening the sweep costs the gate-off
waveform or the sweep itself. `bend` cannot adjudicate it.

## 3. The drum's noise is its attack — two shelved results are suspect

The `BCC` direction was backwards until v0.5.90, so the shelved "noise ending"
measurement tested the wrong end, and the inherited leading noise tick is back
in question. Neither re-measured.

## 4. Wavetable Phase 2

- Bit `$08`'s pulse-width variant shipped in v0.5.80 (§4's fork verified this;
  the handoff had carried it as open for five handoffs).
- **The only open piece**: the two per-instrument wave programs §4 found
  (ACE II `$E357`, Auf Wiedersehen Monty `$E743`) — 16-bit pointer per record,
  per-voice PC, one entry per frame. `detect._find_effect_bit80` reads them;
  nothing encodes them. Wants a `--baseline` A/B on those two files.

## 5. §7b's remaining mechanism work

- **Widen `OUTER_GATE` to the other three dialects.** It matches only
  `DEC abs / BPL +8 / LDA #O / STA abs / JMP`. The zero-page, `STY/RTS` and
  `BMI`-to-light-path forms are documented with addresses in §7b's history
  (`git log -p --follow whats-next.md`). Test cases exist: Warhawk period 8,
  Spellbound 11, Las_Vegas 3 (NTSC) / 5 (PAL).
- **`_rate_shift` is exact only for powers of two** and now matters more, since
  the multiplier can be 3, 5 or 6.
- **The wavetable body is unscaled.** `_wave_delay` holds only entry 1, so
  entries 2-5 advance one per call and run `m` times faster per row at `-Sm`.
  A real defect; not what the attack counts were showing.

## 6. Wire `vicetrace.py` into the register dimensions

The trace exists and is validated; the wiring is not done. `wave_compare`,
`adsr_compare`, `pulse_compare` and `filter_compare` walk two **frame-indexed**
timelines, so feeding them a 312× finer one requires choosing the reduction:

- last-sample-in-frame is what siddump does and is **precisely the lossy step**;
- any-sample-in-frame and majority are both defensible and different.

**Measure the choice, do not pick one.** And trace **both** sides this way —
the original reads 102 gate edges under VICE against siddump's 90, so a
one-sided change trades one bias for another.

## 7. Spellbound's residual

Row 2.20 (solid), rows-per-note exact (solid), yet `--pace` reads 1.333 where
1.82 follows. Both factors it conflates are measured and correct, so whatever
is left is in *which* notes difflib matches at 11% melody agreement. It is the
only known case where a figure passing every confidence gate is still wrong,
which makes it the best available test of any future gate.

## 8. The `-S5` question is closed but its consequence is not

The regression was siddump's frame sampling (v0.5.124), not the conversion.
**The report is a lower bound**: corpus mean melody is 78.3% as traced and
**86.3%** under `--equal-calls`, and the gap widens as the converter uses the
multiplier more. Item 6 above is what would close it for the register
dimensions.

## 9. Smaller items

- **§5's vibrato half-period fix** — one line (`cmp = bound × multiplier − 2`,
  `rshift = shift + log2(multiplier)`), moves 56 files, wants its own measured
  commit.
- `Kings_of_the_Beach_ingame` plays 138 noise frames where the original plays
  none. Uninvestigated.
- Seven files whose vibrato byte is reached by unrecognised addressing; six
  whose frequency table is indexed by an idiom `find_freq_table` misses.
- Two files need `-S10` (a row of 3.30) and stay unencoded; three players run
  *v* of every *v+1* calls (Mozart, Ninja, Mega Apocalypse) and are untouched.
- **Report the GTS2 pattern-array overrun upstream** — LoadTracker is the fork
  most likely to take it.
- `SURVEY.md`'s `Ver` column shows the orderlist family for digi files, so the
  digi engine is invisible there.
- 3 files still fail at survey defaults (`Delta`, `Dragons_Lair_Part_II`,
  `W_A_R`) but convert under presets.

</work_remaining>

<attempted_approaches>

## Refuted this session — do not resurrect

1. **"17 files score better at 50 Hz, so something is a factor of two out."**
   (v0.5.99) `--pace` refuted it: 32 of 33 are closest to the original at the
   rate they are packed for. `melody` is a sequence ratio in a fixed window and
   the two errors are not symmetric — too fast overruns the window and is
   charged for the surplus.
2. **"The outer counter's reload is a per-player constant."** (v0.5.102) It is
   an immediate operand the init self-modifies from a per-subtune table.
   Reading the file image gave Tarzan 11 against a real 2.
3. **"`OUTER_GATE` is too strict; loosen it."** (v0.5.105) Disassembly showed
   the five files that missed have **no outer counter at all** — the gate is
   the first thing their play routine does.
4. **"§7c: we emit more rows per note than the player."** Backwards — the ratio
   is below 1. Then the whole hypothesis died: the static count is 41/41 exact.
5. **"Spellbound closes at 2.20."** (v0.5.111) Right answer, **circular
   method** — it counted frames above the block mean, and half of any series
   sits above its own mean by construction. Re-established properly in
   v0.5.116 by mod-N over running frames.
6. **"`--skip-gate` is harmful (Tarzan 73% → 59%)."** (v0.5.119) My own harness:
   correcting the row moves the `-S` multiplier and `fidelity.py` packed at the
   multiplier still in `presets.json`. I then invented a coherent, mechanistic
   and entirely fictional coupling to explain it. The give-away was
   `multiplier=2` on both sides of an A/B where one side was tempo'd for 1.
7. **"`-S5` regresses; cap the denominator at 4."** (v0.5.121) The regression
   was siddump's once-per-frame sampling. Kings_of_the_Beach_intro, the
   "worst case" at 96% → 61%, is **96%**.
8. **"gatetimer is why `-S5` loses notes."** Eliminated by reading
   (`gplay.c:905` fetches on the one call where `tick == gatetimer`, once per
   row for any tempo above it) *and* by measurement (forcing it to 10 calls
   gives 52 attacks, identical to 2).
9. **A PR against `SIDM2conv`.** My claim was that
   `bin/batch_validate_galway.py` picks multispeed by score-argmax, the same
   mistake `melody` made. Reading `bin/sf2ii_vs_real.py` first killed it: its
   freq metric is a per-frame register comparison with a ±8 alignment search
   and a 0-400 global offset, not a windowed sequence ratio, so argmax is
   legitimate there. Not opened.

## Tooling failures to avoid repeating

- **`\n` inside a quoted heredoc does not survive**, so a Python patch script
  written that way silently edits nothing. Hit at least four times this
  session, and once it made a fork report a calibration from a build that did
  not contain the change. Write patch scripts to a **file** and run them.
- **An asserting patch script is only a guard if the commit waits for it.**
  v0.5.126's doc edit asserted and aborted while the commit went through
  anyway, so the message described a section that did not exist (fixed in
  v0.5.127).
- **`FIXED` is not what `presets.json` emits.** The `always` block is a
  hand-written dict, so `skip_gate` sat in `FIXED`, the suite passed, and the
  regenerated presets did not carry it — reaching nothing, exactly as
  `--filter` did in v0.5.72. `test_the_shipped_always_block_carries_every_gated_option`
  catches it but only against the *shipped* file, so it stays green until
  someone regenerates.
- **`presets.pack_multiplier` must pass the same options as the conversion**,
  or `presets.json` records a multiplier that disagrees with the tempo.
- `vsid -sounddev help` hangs (GUI app). Probe capabilities another way.
- Windows will not unlink a directory that is a live shell's cwd.

</attempted_approaches>

<critical_context>

## Where things are

| | |
|---|---|
| **Repo (work here)** | `C:\Users\mit\claude\h2g` → github.com/MichaelTroelsen/h2g |
| Corpus (95 files) | `C:\Users\mit\claude\c64server\SIDM2\SID\Hubbard_Rob`, or `H2G_CORPUS` |
| `gt2reloc.exe` | `C:\Users\mit\Downloads\GoatTracker_2.77\win32\`, or `H2G_GT2RELOC` |
| GoatTracker source | `C:\Users\mit\Downloads\GoatTracker_2.77\src\` (`gplay.c`, `greloc.c`) |
| VICE 3.9 (`vsid`) | `C:\Users\mit\Downloads\GTK3VICE-3.9-win64\GTK3VICE-3.9-win64\bin\` |
| `siddump-rt` | `python/tools/siddump-rt/` — **must be built**, `make` with w64devkit gcc |
| Short scratch | `C:\t\` (gt2reloc's 60-byte filename buffer) |
| gcc | `C:\Users\mit\Downloads\w64devkit\bin\` |

## Invariants

- **`Commando.sng` byte-exact.** `--max-rows` 94 and `--format` gts2 stay the
  defaults.
- **Bump the version every commit**; regenerate all three artefacts on a
  **settled** tree, once, in the order survey → presets → fidelity.
- A new `convert()` option is inert until it is in **four** places: the
  signature, `presets.FIXED`, the hand-written `always` dict, and (if it moves
  the rate) `pack_multiplier`.
- **Build `tools/siddump-rt` before taking any fidelity number.** The harness
  refuses a multiplier > 1 song without `-m` rather than trace it at half
  speed.

## Instrument limits — the hard-won part

- **siddump samples the registers once per frame whatever the call rate.** A
  multiplier-`m` file loses `m−1` of every `m` calls and the gate edges inside
  them. This produced three separate wrong conclusions.
- **`--pace` measures `rows per note` × `row length` and cannot separate
  them.** A uniform rows-per-note error looks exactly like a row-length error,
  with a tight IQR either way.
- **A confidence gate cannot substitute for a measurement of a different
  kind.** Spellbound's wrong figure passes all three gates (100 gaps, 5.9%
  IQR, 59% coverage). Only the static count settled it.
- **Where `--pace` and a cycle profile disagree, the profile wins** — it
  measures the original alone.
- **Audit the method even when the answer looks right.** Spellbound's 2.20 was
  correct from a circular measure that could not have been wrong.

## Verified facts

- `greloc.c:140` speedcode `{a2,00,8e,04,dc,a2,00,8e,05,dc}` at the **init**
  address; `:1616` latch `0x4cc7/multiplier` (PAL); `:1636` play address is
  `playeradr+3`.
- `gplay.c:905` new notes fetched on the one call where `tick == gatetimer`;
  `:334` `stopsong()` when `gatetimer > tick`; `:707` wavetable advances one
  entry per call.
- `siddump.c:309/325` calls play `seconds × 50` times regardless of the PSID
  speed field. The string "speed" does not appear in the file.
- PAL: 985248 cycles/s, 19656 cycles/frame, **312 rasterlines/frame**.
- `$02A6` is the KERNAL PAL/NTSC flag; VICE/siddump start it at 0 = NTSC.

## Commands

```sh
cd python
python -m pytest tests/ -q                                    # 651 pass, 3 skip
python fidelity.py <corpus> -t 10 --presets ../presets.json -o ../FIDELITY.md
python fidelity.py <file> --pace|--ticks|--diagnose -t 30 --presets ../presets.json
python fidelity.py <corpus> --equal-calls ...                 # sequence dims only
python survey.py <corpus> -o ../SURVEY.md --legal-restart --gt2reloc
python presets.py <corpus> -o ../presets.json
cd tools/siddump-rt && make                                   # needs w64devkit gcc
```

</critical_context>

<current_state>

## Everything is committed and pushed; tree clean

- **`h2g` `master` = `fe79a92`, v0.5.127**, public, 121 commits. Working tree
  clean.
- **651 tests pass, 3 skipped.** `Commando.sng` byte-exact.
- All three artefacts regenerated at **v0.5.125** on a settled tree
  (`SURVEY.md`, `presets.json`, `FIDELITY.md`). v0.5.126 and v0.5.127 changed
  no converter byte, so they are current.
- `SIDDetector2` `master` = `4ebf6ca`, `hubbard/` deleted.
- **cadaver/siddump#9 open**, awaiting the maintainer.

## Current numbers (FIDELITY.md, v0.5.125)

- measured **82** of 95; mean melody **78%**, sequence 76%, pitch 82%,
  wave 64%, ADSR 69%; median retrigger **0.98**
- 34 files play the same music (95-100%); 14 play something else (0-50%)
- **37** of the 82 are packed above `-S1` and traced at their packed rate
- under `--equal-calls` the mean melody is **86.3%** — the report is a lower
  bound

## Two things a fresh session must know first

1. **The old working directory is gone.** `C:\Users\mit\claude\c64server\hubbard`
   is an empty shell (literally — this session's shell is parked in it). Work
   in `C:\Users\mit\claude\h2g`.
2. **`tools/siddump-rt` is not built in a fresh clone** (its `.exe` is
   gitignored). `make` it before any fidelity run, or the 37 multiplier > 1
   files refuse.

## Open questions carried forward

- The reduction choice for wiring `vicetrace.py` into the register dimensions
  (item 6) — **measure it, do not pick one**.
- Why Spellbound's `--pace` figure is wrong despite passing every gate.
- Whether `MAX_ROW_DENOMINATOR` could exceed 6 — bounded by playability now,
  not by evidence; `-S10` would be three quarters of a PAL frame.
- §5's vibrato half-period fix, which moves 56 files and is unmeasured.

</current_state>
