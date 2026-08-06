<original_task>
Continuation of work on `C:\Users\mit\claude\c64server\hubbard` — **H2G**, a
converter from Rob Hubbard `.sid` files to Goattracker `.sng`. This session
began from a handoff at **v0.5.60** and ran to **v0.5.63**.

The user read the handoff, then forked three concurrent `/subtask` agents at
its three open decisions — "do 1" (the +14 transpose clamp), "do 2"
(wavetable Phase 2), "do 4" (the three unexplained residuals) — and finally
asked to push and update this file. Item 3 (the listening pass) was not
forked, because it is the one item an agent cannot finish alone.

The serialisation discipline carried over from the previous session and held:
forks work in scratchpad copies or stage reconstructed HEAD+own-hunks blobs,
one version bump per commit, everything staged by pathspec, artefacts
regenerated exactly once on a settled tree. All three forks landed cleanly
into one tree with no lost hunks.
</original_task>

<work_completed>

## Headline result

| | v0.5.60 | now (v0.5.63) |
|---|---:|---:|
| corpus at defaults | 80/95 | 80/95 (80/83 in reach = 96%) |
| best per-song options | 83/95 | 83/95 |
| mean melody similarity | 68% | **73%** |
| excluding the 33 the harness mis-scores | 71% | **78%** (50 files) |
| mean waveform agreement | 61% | 61% |
| plays the same music (95–100%) | 19 | **23** |
| plays something else (<50%) | 18 | **13** |
| noise frames, ours/original | 5680/11641 | **4548/11641** |
| tests | 326 | **355** (+2 skipped) |

`Commando.sid` → `Commando.sng` remains **byte-exact (15193 B)**.

## Commits this session (pushed to `MichaelTroelsen/SIDDetector2`)

```
76530c9 v0.5.61  fold the transposes Goattracker's +14 ceiling threw away
8fe026f v0.5.62  read the effect byte's drum and arpeggio only where the player has them
87030aa v0.5.63  read the player's own note frequency table
```

Artefacts (`SURVEY.md`, `presets.json`, `FIDELITY.md`) were regenerated
**once**, in `87030aa`, on the settled tree with all three changes applied.
`presets.json`'s `always` block gained `fold_transpose`.

## v0.5.61 — the transpose clamp, closed

A transpose is a pitch offset applied on both sides of the frequency lookup
(`CLC / ADC transpose,X` in the player; `newnote + trans` at gplay.c:927), so
`T` and `(T mod 12) + 12k` are the same interval. `--fold-transpose` keeps
the remainder (always 0..11) in the orderlist and folds the whole octaves
into the note column of a *copy* of each pattern the step plays.

`_build_track` records the true semitones beside the clamped byte — positions
are stable only there, since reindexing, packing, merging and splitting all
move them afterwards. `fold_transposes` rewrites the orderlists and returns
`(pattern, octaves)` pairs; `convert_patterns` appends them as entries
`pattern_used + 1 + j`.

**Where the notes have no headroom the step keeps its clamp.** A partial fold
is only a different wrong pitch — and for T=24 a *worse* one (24 flat rather
than 10). Each step is exactly right or exactly as it was.

| file | before | after |
|---|---|---|
| Deep_Strike v0 | −10@100% | **+0@100%** (melody 78% → 100%) |
| Kings_of_the_Beach_intro | −21@100% | +1@100% |
| Rock_Tells_the_Tale | −21@100% | +1@100% |
| One_on_One v1 | −9@100% | +1@100% |

Cost: 725 (pattern, octaves) pairs corpus-wide against the 208-pattern limit;
79/95 byte-identical, **no file stops converting**.

**The previous handoff's §1 list was wrong in both directions.**
Powerplay_Hockey and Skate_or_Die_intro were never clamp victims (+1@100%
before *and* after); Deep_Strike, unnamed there, is the one file whose melody
score moves.

## v0.5.62 — wavetable Phase 2, the gating half

Under `--effects`, bits `$01` (drum) and `$04` (arpeggio) are now read only
where `det.effect_drum` / `det.effect_arp` found the block: **159 of 450 drum
records and 544 of 683 arpeggio records** stop getting a fabricated effect.

Where the drum routine *is* present the shape is now Warhawk `$1366`'s:
attack, the voice's own waveform with the gate released (`$1390
LDA $157C,X / AND #$FE`), one step of a downward sweep at 256 units/frame
(`$1387`'s `DEC counter / STA $D401,Y`), stop. The leading noise tick is gone
from every path, including the 62 records that also arpeggiate.

| shape | mean wave | our noise (orig 11641) |
|---|---:|---:|
| inherited | 60.5% | 5680 |
| gate both bits, keep the tick | 60.2% | 5383 |
| gate + end the drum on noise as `$139D` does | 58.1% | 10666 |
| **gate + gate-off waveform + sweep (shipped)** | **60.6%** | 4548 |

**Two readings lost to measurement and are recorded, not shipped.** The noise
*ending* is unambiguously in the player and unambiguously worse to write: GT
latches a gated-off voice's last waveform until the next note, so it would
stand for the whole rest of the note, while the player stops writing `$D404`
when its counter expires. And keeping the fabricated tick where no routine
was found is worth +0.3 points — about what chance pays, since the files that
lose most (Bangkok_Knights, Nineteen, Ricochet) have originals that are 46%
noise by frame.

The arpeggio half (544 records) is **invisible to both metrics by
construction** — it moves pitch; melody counts attacks, wave counts waveform
class — and moved the report by 0.0 points. Stated beside the fix in both docs.

## v0.5.63 — the frequency table, and the residuals it dissolved

`sidfile.find_freq_table` locates each player's own note frequency table
(`ASL / TAY / LDA tbl,Y` and two sibling idioms) and places it against
Goattracker's. It returns two numbers that mean **opposite** things:

- a **shift** — the note byte is offset, i.e. a converter defect. One corpus
  file: **Skate_or_Die_intro**, whose table at `$4A2C` has `$0000` at entry 0,
  so note byte *n* is Goattracker's note *n−1*. We emitted `$60+n` and played
  the whole tune a semitone sharp with every note in the right place:
  **melody 5% → 100%** (seq and pitch likewise). Applied.
- a **detune** — the whole table is tuned elsewhere, which no Goattracker
  file can express. Four files carry **NTSC** tables: entry 0 is `$010C`
  where every PAL player has `$0116`, and 268/278 is the clock ratio
  985248/1022727 to within 1.3 cents. The notes were right; *siddump* names
  from register values, so it was naming these originals a semitone flat and
  scoring matching music at 0%. Corrected in the **harness** (`siddump -c`),
  not in the output. Two of the four are header-flagged NTSC and two are not
  — the table is the evidence, the header alone misses half of them.

Telling the two apart is the whole job and they are not close: a shifted
table sits within 7 cents of the semitone grid, an NTSC one 65 cents off it.
`I_Ball` also has `$0000` at entry 0 but its entry 1 *is* Goattracker's
note 1 — a naive "starts with `$0000`, subtract one" rule would have detuned
it. Pinned in a test.

**The other two residuals were re-classified, not fixed:**

- **IK+ / I_Ball's 83 lost attacks on voice 2** are not a version-7 orderlist
  bug. Both channels carry the same noise-percussion figure: gate on at a
  sub-audible base frequency with waveform `$01` (gate, no waveform bits),
  one frame at `freq_hi + $40` with `$81` (noise), gate off — siddump names
  that burst `C#6`. We play the base pitch (`$045A`, `$08B4`) with waveform
  `$09`, never the jump and never the noise, so every note falls below
  siddump's nameable range and the harness records the voice as *absent*
  rather than as wrong timbre. The instruments are IK+ `$07`/`$08` (effect
  byte `$A0`/`$A4`) and I_Ball `$09`/`$0A` (`$A0`) — **high bits the Phase 1
  census never inventoried**. Folds into §1 below and enlarges it.
- **Chain_Reaction's 0.66×** is a row grid that is not expressible, not a
  multiplier error. Original: one note every 10.97 frames = 22 player calls
  at the 100.25 Hz its CIA stub runs at. Ours: 4 GT rows at tempo 4 = 16
  calls. 22 calls over 4 rows is 5.5 calls/row and no integer tempo hits it;
  only a different rows-per-note reaches it exactly (2 rows at tempo 11, or
  11 rows at tempo 2, at `-S1`). Note order is identical (`delta 0 @ 100%`).
  Belongs with §5 below, not with the `-S2` measurement problem.
</work_completed>

<work_remaining>

## 1. Wavetable Phase 2 — the half that is left, plus a bit the census missed

Shipped in v0.5.62: gating `$01`/`$04` on detection, and the real drum shape.
Not shipped:

- **Bit `$08`'s pulse-width variant.** It selects between a triangle sweep
  into `$D403` and an `ADC`-accumulate of `+6` into the instrument's own `+0`
  written to `$D402`, storing the running total **back into the record** — so
  `+0` cannot be read statically in those 21 files. It needs the pulse
  table's two-entries-per-instrument layout changed, and **there is no metric
  here that can see a duty cycle**: siddump's `Pul` column comes first (§6).
- **The high effect bits.** Phase 1 inventoried `$01`/`$02`/`$04`/`$08` only.
  IK+ and I_Ball's percussion instruments carry `$A0`/`$A4`, and
  `Detection.effect_drum` is `False` for both files. A census of bits
  `$10`–`$80` across the corpus is the same shape of work Phase 1 was, and it
  has one known payoff already (two files, one voice each, currently scored
  as absent).
- **The noise ending stays unshipped** unless someone changes how a
  gated-off voice's latched waveform is handled — see work_completed. Do not
  re-derive it from the player and re-ship it; it was measured, at 58.1%.

## 2. The listening pass — never performed, now fourteen versions overdue

`build/listen/` predates v0.5.49. Regenerate with
`python listen.py <sid_dir> --from-json ../build/fidelity.json` and play four
files. Everything the attack metric is blind to — slides, effects, gate
lengths, tempo feel, waveform, and now the folded transposes and the new
drum shape — has only ever been checked by disassembly. It is the one check
that can catch an error shared by the reading *and* the metric, which this
project has hit repeatedly. **It needs a human; an agent can only stage it.**

## 3. The <50% bucket — 13 files, and the old partition no longer describes it

`Action_Biker, BMX_Kidz, Commodore_64_Music_Examples, Delta_Mix-E-Load_loader,
Dragons_Lair_Part_II, Flash_Gordon, Hollywood_or_Bust, IK_plus, I_Ball,
Knucklebusters, Phantoms_of_the_Asteroid, Rasputin, Samantha_Fox_Strip_Poker`

The previous handoff partitioned an 18-file bucket into named causes. Five of
those (the transposition class) left via v0.5.61 and the composition has
shifted, so **that partition is stale — do not quote it**. What is still
known file-by-file:

- `Action_Biker`, `Commodore_64_Music_Examples`, `Dragons_Lair_Part_II`,
  `Hollywood_or_Bust` (partial — v1 is `+0@100%`) were confirmed **genuinely
  scrambled** and nothing since has touched them.
- `IK_plus`, `I_Ball` are the percussion-figure case in §1.
- `Phantoms_of_the_Asteroid` converts to silence (`rows: 0`).
- `Flash_Gordon` was a rate artefact (`+0@100%`).
- `Rasputin` is the one file whose packed subtune 0 is a zero-length stub.
- `BMX_Kidz`, `Delta_Mix-E-Load_loader`, `Knucklebusters`,
  `Samantha_Fox_Strip_Poker` have **not** been partitioned. Samantha_Fox's
  row (orig 2 attacks, ours 116, retrig 58.0) says the original is
  near-silent in the window, which is a harness artefact, not a defect.

Re-running the per-voice modal-delta partition on the current bucket is
cheap and is the right first step here.

## 4. Measuring the `-S2` group needs a cycle-accurate trace

33 of 83 measured files score below their real fidelity and no rerun fixes
it. Their player advances one row every 2 frames, reachable only by calling
Goattracker twice a frame. They pack correctly with `gt2reloc -S2` (the CIA
stub reprograms timer A to 100.25 Hz — verified in the emitted bytes, latch
`$2663`), but **siddump ignores the PSID speed field entirely**
(siddump.c:309/325), calling the play routine `seconds × 50` times
regardless. So `-S` changes the bytes and not the trace; A/B is identical to
the digit. Tracing our side for `seconds × multiplier` is not a substitute
(helps 2 files, hurts 1). RetroDebugger is the tool and has confirmed two
files at their correct rate; the driver pattern is in critical_context.

## 5. Four players have no expressible rate

Mozart, Ninja and Mega Apocalypse run the player *v* of every *v+1* calls
(effective 1.5×, 4×-with-jitter, unknown). Chain_Reaction needs 5.5 calls per
row. No steady Goattracker tempo expresses any of them; they keep the
constant. Chain_Reaction is the tractable one — a different rows-per-note
reaches it exactly (2 rows at tempo 11, or 11 rows at tempo 2, at `-S1`), so
it is a re-gridding decision rather than an impossibility.

## 6. Smaller items

- **Pulse-width tracking** (siddump's `Pul` column) is the next fidelity
  dimension after wave, and it blocks §1's bit-`$08` work. Noted in
  `fidelity.py`, not built.
- **Six players index their frequency table through an idiom
  `find_freq_table` does not recognise** — `Casio_Extended`,
  `Dont_Step_on_My_Wire`, `Era_of_Eidolon`, `Robs_Life`, `Task_Force`,
  `Up_up_and_Away`. They return `None` and keep the mapping they had. An
  under-read: it cannot introduce a wrong shift, only miss one.
- **The four NTSC files still sound 65 cents flat** next to our conversions
  on real hardware. That is what the files play; the fix makes the metric
  stop calling it wrong notes. README says so.
- Per-subtune tempo applies only while group numbering matches the PSID
  header; a split subtune falls back to subtune 0's timebase.
- `find_init_writes` steps over `JSR`s, so a helper's writes are missed.
  Under-read: it can fail to rescue a file, never invent a rescue.
- `SURVEY.md`'s `Ver` column shows the *orderlist* family for digi files
  (they detect as version 2 or 7 with `dialect=digi`), so the digi engine is
  invisible there. Cosmetic, but it has cost a fork a detour.
- 3 files still fail at survey defaults (`Delta`, `Dragons_Lair_Part_II`,
  `W_A_R`, all `TOO MANY NEW PATTERN CREATED`) but convert under presets.
  They are capacity, not comprehension — splitting the orderlist across
  subtunes would convert them.
</work_remaining>

<attempted_approaches>

## Premises refuted — do not resurrect

From this session:

1. **"The +1 semitone is one residual"** — it is two defects with opposite
   fixes. One is ours and correctable in the `.sng` (a shifted table); four
   are NTSC tuning, correctable only in the harness. A rule keyed on
   "`$0000` at entry 0" gets `I_Ball` wrong.
2. **"IK+/I_Ball share a version-7 orderlist bug"** — the orderlists and
   patterns are fine. It is an uncensused effect bit on a percussion
   instrument, and the identical 83 is because both files carry the same
   figure.
3. **"Chain_Reaction's 0.66× is a multiplier error"** — it is 5.5 player
   calls per row, which no integer tempo expresses.
4. **"Powerplay_Hockey and Skate_or_Die_intro are transpose-clamp victims"**
   — they measure +1@100% before and after; they were in the other class.
5. **"Ending the drum on noise, as the player does, will improve the wave
   score"** — 58.1% vs 60.6%. GT latches a gated-off voice's waveform; the
   player simply stops writing `$D404`.
6. **"A looser probe will find the drum routine in more files"** — of the 25
   files that test bit `$01` without matching Warhawk's block, only 2 write
   noise to `$D404` near the test, and neither regresses.

Carried forward from previous sessions (still refuted):

7. **"~7× too many re-triggers"** — real ratio 0.78/0.98 median.
8. **"`0xBD` hold rows re-trigger"** — `$BD` is a no-op in the note column
   (gplay.c:908-941); the editor writes it into blank rows itself.
9. **"`gatetimer` holds a note length"** — it is a compare value against a
   per-row countdown, capped at `tempo` (gplay.c:334).
10. **"The fabricated wavetable invents noise"** — misplaced class. We
    produce *half* the original's noise while inventing it elsewhere; both
    errors at once, which is why the aggregate looked like under-production.
11. **"Devils Galop needs a table-copy reader"** — its init writes over the
    *operands in its own code*.
12. **"GT's gate mask is sticky, so per-note `$BE` collapses attacks"** —
    `firstwave = 0x09` re-opens the gate on every note (gplay.c:356-363).
13. **"The tempo scatter is per-file variance"** — per-voice medians over a
    mixed-voice measurement; the real distribution is four values.
14. **"Wiring `-S` will unblock the 33 mis-scored files"** — nothing at the
    packing step can; siddump is blind to the PSID speed field.
15. **"The slide gap explains the low melody scores"** — no correlation
    (47 slide-heavy files: 67%; 21 slide-free: 66%).
16. **"Instrument +6 is vibrato"** — it is a pulse-width sweep
    (`$12BF → STA $D403,Y`).
17. **"3 calls per row is the floor" as a corpus-wide constant** — per-file
    scatter; 19 files are already exact and a global `-S3` would wreck them.
18. **"gt2reloc renumbers subtunes"** — invalid subtunes become in-place
    zero-length stubs and the count truncates the tail. The repair MUST
    legalise the revived subtune's restart or greloc.c:244 aborts the whole
    export.
19. **"Delta has a pattern-table undercount"** — the orderlist was carrying
    interleaved repeat counts.

## Process lessons

- **A metric that cannot see a change is not evidence the change did
  nothing** — hit five separate times now (digi rest, slides, effects, the
  544 gated arpeggio records, three of the four folded transposes). Say in
  the doc, next to the fix, which metric is blind to it.
- **A measurement that scores correct music at 0% is a harness bug until
  proven otherwise.** The NTSC four sat in the "plays something else" bucket
  for eighteen versions.
- **When one number has two possible causes, find the discriminant in the
  6502 before choosing** — the shift/detune split is 7 cents vs 65 cents and
  a header flag would have got half of them wrong.
- **Re-measure a fork's numbers on the settled tree before quoting them.**
- **When two readings of a table are both plausible, the one under which the
  three voices agree in length is the player's** (Delta v10 proof).
- **Phantom table entries make correct fixes net-negative** — check what an
  unreferenced entry decodes to before changing how bytes decode.
- Fork hygiene that worked, three-way this time: scratchpad trees + unified
  diffs against a pristine copy; reconstructed HEAD+own-hunks blobs for
  shared files (`cli.py`, `README.md` were touched by two forks each);
  re-basing onto the landed siblings and re-verifying before committing;
  refusing to regenerate artefacts from a half-applied tree.
- **Bash here-strings with `->` arrows create stray files.** Multi-line
  commit messages go in a scratchpad file, `git commit -F`.

## Environment gotchas (cumulative)

- `dis6502.py` (never `dis.py`) in `$TMP` — usage:
  `python dis6502.py <sid> <hex addr> <count>`.
- pytest from `python/`; PowerShell scripts need the PowerShell tool.
- gt2reloc: test for the output file, never the exit code; short paths
  (`C:\t\`); bare filenames with cwd set.
- SIDM2 tools run with cwd = SIDM2 root.
- RetroDebugger: stop/start does not reset; hand-assemble via memory writes;
  it honours CIA timing (siddump does not).
- `siddump -c<clock>` recalibrates note naming — this is what the NTSC fix
  uses.
- csdb.dk 503s automated fetches.
</attempted_approaches>

<critical_context>

## Invariants

- **`Commando.sng` byte-exact (15193 B).** Every output-changing option is
  opt-in; `--max-rows` 94 and `--format` gts2 stay the defaults.
- **Bump the version every commit** (`python python/bump_version.py "…"`);
  regenerate `SURVEY.md` (with `--legal-restart --gt2reloc`),
  `presets.json`, and `FIDELITY.md` on every conversion-changing commit,
  from `python/`, **only on a settled tree** and only once.
- **Never ship a fake success**; a correct fix that is net-negative on the
  corpus gets recorded, not shipped (the bit-6 status byte, the drum's noise
  ending).
- Every orderlist-structure change needs the playback-equivalence check
  (`test_pack_repeats.py` harness).
- Stage `hubbard/` paths only, by pathspec — the repo also contains
  unrelated sibling projects (`siddetector2/`, `SIDM2`).

## Verified Goattracker facts (from source)

```
MAX_PATT 208  MAX_PATTROWS 128  MAX_SONGLEN 254  MAX_INSTR 64
FIRSTNOTE $60 LASTNOTE $BC  REST $BD (no-op)  KEYOFF $BE  KEYON $BF
REPEAT $D0    TRANSDOWN $E0  TRANSUP $F0  LOOPSONG $FF
```
- Transpose $E0..$FE → −16..+14; +15 unrepresentable. Applied as
  `newnote + trans` (gplay.c:927), which is why folding octaves into the
  notes is exact.
- Tempo 0/1 = funktempo; fastest steady row = tempo 2 = 3 calls.
- CMD_SETTEMPO value & $7F, ≥$80 = this channel only (gplay.c:494).
- GTS3+ portamento data = 1-based speed-table index (gplay.c:740); GTS2
  loader converts on read (gsong.c:311-321).
- greloc.c: restart ≥ songlen rejected (:244); zero-length voice = subtune
  stub + tail truncation (:200-255, :653, :701-706); `-S` sets a CIA stub
  (:1595) **and** DEFAULTTEMPO = 6×multiplier−1 (:1143); instrument 63's AD
  can override DEFAULTTEMPO (:1141).
- siddump calls play seconds×50 times regardless of PSID speed — blind to
  the multiplier (siddump.c:309/325).
- A gated-off voice keeps its last waveform latched until the next note.
- Effective instrument ceiling 51, clamped at 50.

## Key paths

| | |
|---|---|
| Corpus (95 files) | `C:\Users\mit\claude\c64server\SIDM2\SID\Hubbard_Rob` |
| GoatTracker 2.77 + source | `C:\Users\mit\Downloads\GoatTracker_2.77` |
| `gt2reloc.exe` / `siddump.exe` | `…\GoatTracker_2.77\win32\`, `SIDM2\tools\` |
| Short scratch for gt2reloc | `C:\t\` |
| SIDM2 accuracy tools | `SIDM2\pyscript\audio_tightness_tool.py`, `SIDM2\scripts\validate_sid_accuracy.py` |

## Non-obvious behaviours

- `command_floor(version)`: $FF for 0/1/3/4/5, $F0 for 2/6/7/8, $FE for 9;
  version 10 shares version 0's floor.
- `presets.json` `always` = gts5, tempo auto, legal_restart, slides, effects,
  status_bit6, reject_phantoms, fold_transpose, gt2reloc — what makes a
  preset reproduce its recorded bytes. Per-song `multiplier` is consumed by
  all three packing paths.
- `Detection.frames_per_row` ≠ 1 only in the cmdtable dialect.
- `Detection.effect_drum` / `effect_arp` now gate the wavetable;
  `effect_pulse_lo` exists and is logged, and nothing consumes it.
- `find_freq_table` returns a **shift** (applied) and a **detune**
  (reported, consumed by `fidelity.py` only) — they mean opposite things.
- Opening output in GoatTracker requires gts5 (GTS2 importer overrun).
- The dialect registry: 0/1/3 Warhawk-family, 2 AWM (two-byte transpose
  sub-variant), 4 ACE 2, 5 BoB, 6 Mega Apocalypse, 7 IK+, 8 digi,
  9 Chain Reaction, 10 Delta, plus the cmdtable pattern grammar.
</critical_context>

<current_state>

## Status: all work committed and pushed; tree clean

- **HEAD `87030aa` (v0.5.63)** on `origin/master`,
  `https://github.com/MichaelTroelsen/SIDDetector2.git` (private).
- **355 tests pass, 2 skipped** (from `python/`). `Commando.sng` byte-exact.
- `SURVEY.md`, `presets.json`, `FIDELITY.md` are **current as of v0.5.63** —
  regenerated once, on the settled tree, after all three forks landed.

## Open decisions

1. **Wavetable Phase 2's remainder** (§1) — bit `$08` is blocked on pulse
   tracking (§6); the `$10`–`$80` census is not blocked on anything and has
   a known payoff in IK+/I_Ball.
2. **The listening pass** (§2) — fourteen conversion-changing versions have
   shipped unheard, including the two largest fixes in the project. This is
   the only item that requires the user rather than an agent.
3. **Re-partition the <50% bucket** (§3) — cheap, and the standing partition
   is stale after v0.5.61.
4. **Chain_Reaction's re-gridding** (§5) — the one inexpressible-rate file
   with an exact solution available.

## The gap, restated

At v0.5.43 the corpus converted and nobody knew whether it played the right
music. At v0.5.60 two metrics existed and the two largest known defects had
been named but not fixed. Both are now fixed: the transpose clamp is gone,
and the wavetable no longer invents an arpeggio for 544 instrument records
whose players have no arpeggio routine.

What v0.5.63 adds is a third thing, and it may matter more than either: the
harness was **wrong about four files**, scoring correct music at 0% because
siddump named NTSC-tuned originals in the wrong key. The project's habit of
trusting a number it built itself cost eighteen versions there. The bucket
labelled "plays something else" is now 13 files, and the honest statement
about it is that four are confirmed scrambled, five have named non-scrambled
causes, and four have not been looked at since the bucket changed shape.

And in twenty-one versions of fidelity work, exactly one file has ever been
listened to.
</current_state>
