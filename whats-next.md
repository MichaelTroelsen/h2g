<original_task>
Continuation of long-running work on **H2G**, a signature-based ripper that
converts Rob Hubbard `.sid` files into GoatTracker `.sng`, at
`C:\Users\mit\claude\h2g`. The session opened against the previous handoff
(then at v0.5.136) and ran to **v0.5.208**.

There was no single up-front task. The session was driven as a sequence of
short imperative directives, each answered before the next was given, in a
dominant working mode that became the project's method:

> load a conversion in GoatTracker (or `vsid`), report by ear what sounds
> wrong, then diagnose the cause in the 6502 player, fix it, measure it
> against the corpus, and ship or refuse to ship on the measurement.

The directives, in order, were roughly: push pending commits; extend
`instrmap.py`; fix GT 1's pulse sweep; fix the `$09` firstwave; teach
`presets.py` to search structure-invisible options per song; audition
selections; read and emit the byte-code wave program; fix the `-O0` packing
default; find the drum noise-run mechanism; build position-independent
measures; fix the arpeggio onset delay; measure `vibdelay 1` across the
corpus and ship the closer; do the pattern-level vibrato command; explain
pattern 12; fix the note endings; fix the tie; fix the balloon song's snare
overshoot; find and decode effect bits `$20` and `$40`; emit them; fix the
vibrato rate; build the oscillation scorer.

Scope note: everything below is inside the existing Python port
(`python/h2g/`) plus its measurement harness (`python/fidelity.py`,
`python/presets.py`). The VB6 original is reference only and was not touched.
</original_task>

<work_completed>

## Summary of the whole session

**72 commits, v0.5.137 → v0.5.208, all pushed.** HEAD is `d5f1cea`, master in
sync with `origin/master`. `818 passed, 2 skipped`. `Commando.sng` remains
byte-exact throughout (it is the project's only fidelity anchor).

The pre-compaction half (v0.5.137–v0.5.197) is summarised briefly; the
post-compaction half (v0.5.198–v0.5.208) is documented in full, because that
is where the live threads are.

---

## Part 1 — v0.5.137 to v0.5.197 (earlier in the session, condensed)

Shipped in this range:

- **`instrmap.py`** — a per-song instrument map with `annotate_dump()`, which
  appends `Ins1 Ins2 Ins3` columns to both siddump tables. The instrument is
  decided **once per note at attack+1 and held**, so a hard-restart ADSR
  cannot relabel it.
- **A third pulse engine** (`_pulse_tri_program`, 24 files): fixed-bound
  triangle, whose rate byte packs the step in `& $E0` and the frames between
  steps in `& $1F` at the same record `+6` the other two engines read as a
  plain per-frame rate.
- **Startup-lag alignment** (`fidelity.startup_lag`) — gt2reloc's player
  reaches its first note 3–8 frames after the original, and every per-frame
  column was being charged for it. Mean `wave` 67.0 → 70.2%, `adsr`
  71.9 → 76.4%. Estimated from the signal, **never fitted**.
- **`pspan`** (pulse span), **`nrun`** (noise-run agreement), **`vib`**
  (reversal ratio) dimensions.
- **`--two-stage`** (the bit-`$04` attack waveform, 34 files),
  **`--sfx-drum`** (the bit-`$80` fixed-pitch drum), **`--wave-program`**
  (the byte-code wave program, 29 files), **`--no-test-restart`** (measured
  and rejected as a default), **`--rest-instrument`**,
  **`--compact-instruments`**.
- **`gt2reloc -O0` at all three packing sites** — its pulse-optimisation
  skipping is default-on and made the packed player skip the pulse table on
  the note-fetch tick. Mean `pspan` 0.61 → 0.65x.
- **`presets.py --fidelity`** — the per-song search for structure-invisible
  options, with `FIDELITY_VETOED` for listening-test overrides and
  carry-forward on plain runs.
- **The report moved to `-t 60`** from `-t 10`: at 10 s, 17 of 82 rows showed
  `0/0` slides and two corpus A/Bs read "identical on every file" from a
  window that contained no slides.
- **`fidelity.noise_runs`** — the position-independent shape (run *lengths*,
  attributed by the ADSR at the run's midpoint, runs touching a window edge
  dropped). This shape recurs three more times later in the session and is
  the single most useful measurement idea in the project.
- **The arpeggio phase fix** (v0.5.197) — put the first swing on the call the
  player uses.

---

## Part 2 — v0.5.198 to v0.5.208 (in full)

### v0.5.198 — `65250b2` — measure `vibdelay 1`; 8 stays, and 12 is a trap

The directive was *"measure vibdelay 1 across the corpus and ship the
closer"*, arising from a diagnosis that Commando's vibrato starts 10 frames
late (`_vibrato_delay` emits `vibdelay = 8` for the global-triangle dialect
to stand in for the player's per-note length gate).

Built a per-note agreement harness: for each note of an instrument whose
*only* pitch movement is the vibrato (effect byte `& $05 == 0`, so no drum
and no arpeggio), does each side's pitch move at all? Paired **by note index
per voice**. 25 files, 2487 notes, the original moving 435 of them.

| gate | moves/still agrees | still notes we wobble | onset late (median) |
|---|---|---|---|
| 1 | 65.9% | 826 of 2052 | +0 |
| **8 (kept)** | **85.5%** | 207 | +10 |
| 12 | 88.6% | 114 | +15 |
| 14 | 88.6% | 113 | +17 |

Kept 8: `vibdelay 1` fixes the onset exactly but wobbles 40% of the notes
that should be still. **Refused to ship 12** even though it scores best — the
moves/still column cannot see the 5 extra frames of lateness it costs, and it
*plateaus* at 14 rather than peaking, which is a count being maximised by
destroying the events it counts. 8 is read out of the player's `CMP #$08`; 12
would be fitted to a blind proxy. Pinned in `tests/test_vibrato.py`.

Two harness errors, both recorded:
1. The first pairing found **zero** notes — keyed by absolute frame, which
   cannot match across the startup lag.
2. Two sweeps' "8" disagreed (85.5% vs 83.2%) because one called the real
   `_vibrato_delay` (which returns `gate × multiplier`) and the other passed
   a literal 8. The multiplier scaling is worth 2.3pp by itself.

### v0.5.199 — `ea5f540` — the vibrato length gate as a per-note pattern command

`--vibrato-command`, **on by default** via `presets.json`. No-op outside the
global-triangle dialect (25 files) and outside `--format gts5`.

The mechanism was already in `gplay.c`:

```c
case CMD_DONOTHING:
  if ((!cptr->cmddata) || (!cptr->vibdelay)) break;
  if (cptr->vibdelay > 1) { cptr->vibdelay--; break; }
case CMD_VIBRATO:          // <-- fallthrough target, entered directly
```

The `vibdelay` countdown lives **inside `case CMD_DONOTHING`**, so a row
carrying `$04` oscillates from the note's first call whatever `vibdelay`
holds. And `$04 00` gives `cmddata = 0`, which still enters the case but adds
nothing — a per-note **damping**. Long note gets `$04 <speed index>`, short
note gets `$04 00`.

- The gate needs **no unit conversion**: `patterns._build_raw_pattern`
  computes `wait = b1 & 0x1F` from the same status byte with the same mask
  the player's `AND #$1F` uses, so `wait >= gate` is a row count. It is the
  one rate-like quantity in the writer that must *not* be divided by the
  multiplier.
- Hold rows already repeat the note row's command, so the oscillation runs to
  the end of the note.
- `$BD` is "no new note", not a rest (gplay.c:925 assigns `newnote` only for
  `<= LASTNOTE`).

**The gate constant was wrong for the file that matters.**
`TRIANGLE_VIBRATO_GATE = 8` was read from one player's `CMP #$08`, which
Commando does not contain at all — it compares against **6**. Read at a fixed
**+56 bytes** from `TRIANGLE_VIBRATO_SHAPE`'s match (`detect._find_triangle_gate`,
`TRIANGLE_GATE_SHAPE`), the thresholds are **8 in 20 of 25 files, then 6
(Commando), 5, 4, 4, 2**. The +56 anchor matters: every one of these players
has a *second* gate on the same duration cell 377 bytes further on.
Commando's 6 is checkable rather than fitted — its durations are in units of
3 frames, so `wait >= 6` is "24 frames or longer", and voice 1 has 27 notes
of 24 frames plus 4 of 30 = exactly the **31** notes the original is measured
to vibrate.

Results over 2487 notes:

```
delay, gate 8 (v0.5.198)     85.5%   miss 153   invent 207   onset +10
delay, the file's own gate    78.9%   miss 109   invent 417   onset +10
command + damp, file's gate   92.1%   miss 129   invent  68   onset  +0
```

The middle row is deliberate: the correct per-file threshold is an
improvement as a *command* and a regression as a *delay*, because a delay is
also doing the suppressing the damping took over. Hence
`_vibrato_delay(det, multiplier, commanded=False)` — **a number can be right
for a mechanism and wrong for the approximation of it.**

Commando 97.8 → **100.0**; Battle of Britain, Crazy Comets, Hunter Patrol,
Ninja, One Man and his Droid all reach 100.0.

### v0.5.200 — `27f855b` — drop the release nibble on players that kill the envelope

Answered *"pattern 12 plays too many notes"*. The notes were right (voice 1
matched at difflib ratio 1.00, 231 attacks vs 230; every byte of the Hubbard
pattern decoded; no slide in it). The **note endings** were wrong.

Commando `$517C`:

```
LDA duration,X / AND #$20 / BNE skip   ; status bit 5 -- a tie flag
LDA counter,X  / BNE skip              ; only on the note's last row
LDA wave,X / AND #$FE / STA $D404,Y    ; gate off
LDA #$00 / STA $D405,Y / STA $D406,Y   ; envelope destroyed
```

91% of 53308 notes across the 72 classic-dialect files are "cut" (Commando
708 to 21). The envelope is destroyed, so the record's release nibble never
sounds — but we copied it in, and with `$5F` on Commando's lead every note of
a staccato figure rang through the gap.

New **`tail`** column: `fidelity.release_tails` /
`release_tail_agreement`, per instrument, gated on
`detect.ENVELOPE_CUT_SHAPES` (which requires the gate-clear, because the bare
zeroing also matches a startup init: 33 files claimed, 9 loose ones not).

Also recorded: corpus mean `adsr` fell 75% → 58%, attributed as **−47.1 pp on
the 29 files with the routine and 0.0 pp on the 50 without**. Not a
regression in the sound (the SID consults the release nibble only when the
gate falls, by which point the player has zeroed it), and `adsr` was **not**
redefined to make the change score well — the generated report prints the
attribution beside the number instead.

### v0.5.201 — `ba2bcbd` — gate the envelope cut per instrument

**A regression I shipped and a listener caught**: *"something bad happened to
the drums, perhaps the previous version sounded better."* It had.

The trace had said so all along. Per instrument on Commando, in the gap after
a note:

```
rec  eff   first frames of the gap
  0   00   0000 0000 0000          <- cut on the gate-off frame
  2   08   0000 0000 0000          <- cut
  1   05   064B 064B 064B 064B     <- never cut: a real release
  7   05   0DFB 0DFB 0DFB 0DFB     <- never cut
 12   01   090A 090A 090A 090A     <- never cut
  3   05   0A09 0A09 0000 0000     <- holds 2 frames, then the NEXT note's zero
  4   03   0FC4 0FC4 0000 0000     <- likewise
```

Only 2 of 7 are cut. The cut is one write on the note's last row, and an
instrument whose effect routine runs every frame overwrites it. Gated on
`goatwriter.EFFECT_PER_FRAME = 0x01`.

**Two harness errors made v0.5.200 look like an improvement:**

1. `release_tails` took the release as the **minimum over the gap** to the
   next note. That cannot tell this note's cut from the *next* note's
   preparation. It scored all seven instruments as cut and reported
   "27.6% → 99.2%, better on 27 and worse on 0" for a change making files
   worse. Read on the gate-off frame the three builds measure
   **64.6% / 62.1% / 97.4%** — v0.5.200 was a net regression published as an
   improvement. v0.5.200's write-up had justified the wide window by citing
   the edge reading as the error (20.7% vs 100%); it was the other way round.
2. "Effect bit `$01` clear" was dismissed at **59.8%** accuracy as a mere
   correlation — computed over all 95 files, where the 62 without the routine
   can only contribute false positives. Over the 33 that have it: **98.6%**,
   **no false negatives**. It was the mechanism.

Mean `adsr` recovered 58% → 64%.

### v0.5.202 — `3cc921e` — honour the tie flag

Answered *"note E-5 on pos 16 should not be played as a note but the glide
from F#5 should stop at E-5 ... maybe the attack on E-5 is too strong."*
Exactly right. At frame 3896:

```
          ORIGINAL                  OURS
row 15    2E7A 2E2C 2DDE 41         2F43 2EDE 40 -> 09   we close the gate
row 16    2BD6 41   no attack       2BDD 41  * ATTACK
```

**Status bit 5 is a tie flag** — the same bit as the envelope cut. It means
*don't close the gate at this note's end*, and the consequence had never been
drawn: the note that **follows** a tied event arrives with the gate already
open, so the player's note-on writes a frequency and nothing else. No gate
edge, no attack. The bit had been parsed for years as `no_adsr` and emitted
`CMD_TONEPORTA` on the tied row *itself*, where the slide branch overwrote
it — inert.

GoatTracker says it in one command: **`CMD_TONEPORTA` with parameter 0**.
`gplay.c:811` assigns `freq = targetfreq` in one call (a jump, not a slide —
any speed makes it a slide); `:930` skips the hard-restart gate-off *because*
the command is TONEPORTA; `:355` skips the firstwave testbit for the same
reason; and it zeroes `vibtime`, so the vibrato restarts on the landing as
the original's does. It goes on the note **after** the tied event — the
original does attack on the slide row.

- Commando voice 1: attacks **511 → 501** against the original's 502;
  waveform through the landing `41 41 41 41`, frame for frame.
- 64 classic files carry tied events: median `retrig` 1.008 → **0.999**, mean
  `melody` 82.3% → **84.1%**, 19 better and 5 worse.
- **Delta_Mix-E-Load_loader 6% → 100%** (retrig 2.133 → 1.067).
- Worst regression Kentilla, melody 95% → 85%, whose retrigger *improves*.
- Corpus report: melody 83% → **85%**, sequence 83% → 84%, pitch 91% → 92%,
  median retrigger 1.01 → **1.00**.

Also: `_vibrato_command_pass` now fills the free rows of a block whose note
row is taken, instead of skipping the block, so a tied landing keeps its
vibrato from the next row.

**Two discoveries that cost real time**, both now in `CLAUDE.md`:
GoatTracker **numbers patterns in hex**, so a listener's "PATT.12" is pattern
**18** (three dumps of `new_patterns[12]` disagreed with the screenshot
first); and the editor's pattern is post-dedup (GT 18 = Hubbard 15) with a
transposing orderlist (`D3`), so neither index nor pitch matches the source.
**Identify a pattern by its note-row positions and read the final `.sng`.**

### v0.5.203 — `a25237c` — fix the wave program's noise overshoot

The snare existed but sounded 670 noise frames against the original's 387.
**Run lengths** named both causes at once:

```
instrument 0729 (43 notes)  original: 43 runs of 1, 43 runs of 8
                            ours:     43 of 1, 36 of 6, 3 of 30, 2 of 54, 1 of 78
```

1. **6 instead of 8** — a `slide` opcode was emitted as *two* wavetable
   entries (waveform, then a portamento command), so the program ran 13
   frames where the player's runs 11, and the closing burst was truncated.
   One entry per opcode now; the two frames of pitch movement are dropped.
2. **30, 54, 78** — the program ended holding noise. Its own docstring
   asserted GoatTracker "keeps the last waveform, as the player does". The
   player does not: its note-end routine writes the stored waveform with the
   gate cleared, `LDA $54F8,X / AND #$FE` — the *same routine* read three
   sections earlier for the envelope cut. The record's own waveform is
   emitted before the stop now.

Result: the snare's runs are **identical to the original's** — `{1: 43, 8: 43}`
on each side, 387 noise frames against 387. `nrun` 50% → 67%.

Introduced **`presets.FIDELITY_CONFIRMED`**, the mirror of `FIDELITY_VETOED`,
because `fidelity_better` scored the fixed program as *worse* structurally:
its `finds_noise` test requires the reference to have **no** audible noise,
and this file has plenty from another instrument — a per-file test for a
per-instrument defect.

### v0.5.204 — `bd284eb` — decode effect bits `$20` and `$40`

Answered *"I do hear sound where the drums are but not snare drums"*: the
snare was right, a **second** drum was not, and it runs two effect bits never
read.

**Why they were never found:** detection looks for `AND #$xx`, and bit 6 has
its own idiom — `BIT cell / BVC`. Anchored on the effect cell (the address
tested with at least two masks whose meaning is known):

- **`$20` — a filter cutoff sweep, 35 of 95 files.** A per-voice accumulator
  advanced by a per-instrument step into `$D416`, with `$D417` from a second
  byte. An independent shape census (an accumulate then `STA $D416`) finds 31.
- **`$40` — a fixed pitch out of the player's own note table, 41 files.**

`$40`'s derivation, after two wrong turns: the two cells it writes feed
`$D400`/`$D401`, so they are the voice frequency; `find_freq_table`
independently returns the address the routine indexes, so the value is a
note; and **`Y` is the record *offset*, not its number** — read as a number
the byte is 129 (→ `$1A03`, not a pitch the trace shows), read as
`index × stride` it is `$34` = 52, and `freqtable[52]` = `$15EB` is what the
original sounds on **226 of 226** frames. The array is `det.wave_program`
itself: a pointer low byte under `$08`, a note index under `$40`.

**The emission was deliberately not wired.** On the attack's first frame the
pitch is exactly right and `melody` falls **85% → 39%**. The original's
per-offset profile says why:

```
offset 0   the PLAYED note's pitch   <- what melody reads
offset 1   noise at freq-hi 56       ($80, sfx_pitch = 56)
offset 2   noise at freq-hi 21       ($40, freqtable[52])
```

216 records set `$20` and 204 set `$40`, across 57 files.

### v0.5.205 — `5c671bf` — compose the drum's two pitches; not shipped

Raw frames gave the exact profile, identical on every note of instrument
`0A99`:

```
+0  wf 41  the played note
+1  wf 81  freq $38CE / $38B4 / $389C  NOISE   <- keeps the played note's LOW byte
+2  wf 81  freq $15EB                  NOISE   <- exactly freqtable[52]
+3..+6  wf 41  the played note
+7  wf 81  freq $38xx                  NOISE   (6 frames on = sfx_period)
```

Two open questions closed: the `$38xx` frames keeping the played note's low
byte confirms `$80` as a **high-byte-only write**; and `$15EB` is `$40`'s
pitch — which `_sfx_drum_entries`' own docstring had recorded for years as
*"a fixed `$15EB` from somewhere this reader has not found"*.

Passing it as the burst's second note made Trans-Atlantic exact
(`{21: 226, 55: 452}` vs `{21: 226, 56: 452}`, `nrun` 100%) — **and Pandora
refuted it**: `{69: 281, 73: 339}` where the original has only 35 frames at
that pitch. The `$40` pitch fires once per **note**; the drum block's entries
loop once per **period**. Trans-Atlantic happens to have one burst per note,
so the two coincide there. Not shipped; `second_note` implemented and tested,
nothing passing it.

### v0.5.206 — `1eca6da` — the prologue-plus-loop restructure

`_sfx_drum_entries` now returns `(left, right, loop)` and the caller's jump
targets `start + loop`, so a prologue can precede a looping body:

```
0  wave|1  00        played note        offset 0
1  noise   drumnote  drum's high byte   offset 1
2  noise   $40 note  freqtable[index]   offset 2   <- prologue ends
3  wave|1  00                           offset 3
4  delay 2                              offsets 4-6
5  noise   drumnote                     offset 7   <- loop starts
6  wave|1  00                           offset 8
7  delay 3                              offsets 9-12
   FF -> entry 5                        offset 13, every 6 thereafter
```

The plain shape returns `loop = 0` and is byte-identical to before.

**One defect caught before shipping:** the first cut regressed Thundercats
(melody 77% → 72%, 99 noise frames at a pitch its original never sounds)
because `_fixed_attack_note` checked `det.effect_bit40` — which says the
*player reads* the bit — and never whether *this record sets* it. Now gated
on `data[rec + 7] & $40`.

| file | ours | original | `nrun` |
|---|---|---|---|
| Trans-Atlantic (forced) | `{21: 226, 55: 452}` | `{21: 226, 56: 452}` | 100% |
| **Pandora** | `{69: 35, 73: 375}` | `{69: 35, 72: 364}` | **0% → 100%** |
| Thundercats | unchanged | — | 100% |

Pandora's `wave` 68% → 70%. Its `noise` count read 620 → 410, which is not a
fall: that instrument now sounds 410 against the original's 420 for it, where
620 was over-production.

### v0.5.207 — `ca3e5e5` — read and emit effect bit `$10`'s arpeggio; off by default

The directive was *"fix the vibrato rate"* (the balloon song's `vib` was
0.17x) and **the first measurement falsified the premise**:

| instrument | original | ours | effect byte |
|---|---|---|---|
| `0A09` | 1175 | **31** | `$10` |
| `0A99` | 904 | 112 | `$E4` (the drum) |
| `0AF8` | 637 | **16** | `$14` |
| `0A88` | 317 | 257 | `$00` — the only record *with* a vibrato byte |

The vibrato was fine (bound 4 emits `cmp 2`, period 8 calls against a 4-frame
half-period — exact). The deficit was 1812 reversals of a mechanism never
read.

**Bit `$10` is a three-step arpeggio, in 34 of 95 files:**

```
LDA effect / AND #$10 / BEQ out
LDA index,Y / ASL / TAY          ; the record's byte, doubled
LDA pairs,Y / STA base+1         ; this instrument's two offsets
LDA pairs+1,Y / STA base+2
LDY phase                        ; a GLOBAL counter, DEC'd once per frame
CLC / LDA note,X / ADC base,Y    ; played note + this step
ASL / TAY / LDA freqtbl,Y ...
```

`seq[0]` is a byte nothing writes (0 everywhere checked); `seq[1..2]` are the
pair. Trans-Atlantic's records 0 and 3 hold `18 00` — the note, two octaves
up, the note, on a three-frame cycle. The phase length is **read** from the
reload (`DEC phase / BPL / LDA #$02 / STA phase`). The index array is
`det.wave_program` for the **third** time.

Emitted: record 0 goes 31 → 1365 reversals against 1175, and the file's `vib`
0.17x → **0.61x** with melody unchanged. Across the 26 files that use it:

```
              median vib   mean melody
off                0.22x         81.5%
--pitch-seq        0.58x         76.3%
```

Seven lose melody, After_8 by 40 points, **because the phase is global** and
a wavetable restarts at every note. Leading with the modal step (likeliest
under a uniform unknown phase, attack frame kept on the pattern's note) was
tried and moved the mean by −1 point, trading After_8 for Chain Reaction. No
rotation is right more than a third of the time. So it ships **off**.

### v0.5.208 — `d5f1cea` — the oscillation and noise-pitch criteria

`presets.fidelity_better` gained two terms, on the same one-sided footing as
the existing pair:

- **Oscillation** — `reversal_ratio` against 1.0, compared **in log space**
  via the new `presets._closer`, because 2.0x and 0.5x are the same size of
  wrong where `abs(r − 1)` calls one twice the other.
- **Noise pitch** — the median frequency each side spends its noise frames
  at, likewise a log-space ratio. **No new measurement**: `_noise_pitch` was
  already computed for the audibility guard and the numbers were in the tuple,
  unread.

Both keep `keeps_notes`, which is what makes them safe — it accepts the
arpeggio on the balloon song and rejects it where it costs melody. Verified:

```
Trans-Atlantic   two_stage, sfx_drum, pitch_seq
After_8          defaults      (pitch_seq would cost 40 points of melody)
Chain Reaction   defaults      (100% -> 78%)
```

`fidelity_better` also tolerates a 4-element state (built before these
terms): an absent dimension reads as unmeasurable, not as a zero.

**`FIDELITY_VETOED` is now empty.** The scorer selecting `sfx_drum` put the
"beeping" veto back in question, and the listener had already answered — asked
to A/B the two builds, they reported **no audible difference at all**. The
verdict had been recorded when the file had no snare (fixed v0.5.203) and the
burst sounded one pitch for every frame (fixed v0.5.206). Kept as a comment.

`pitch_seq` joined `FIDELITY_TOGGLES` (now five toggles = **31 combinations
per song**). Today's three measurements are in `FIDELITY_CONFIRMED` so the
balloon song benefits now.

Balloon song's row: **`vib` 0.17x → 0.72x**, **`noise` 1315/1089 →
1089/1089 exactly**, **`nrun` 67% → 100%**, melody unchanged at 85%. Corpus
aggregates unmoved.

---

## New code surface added in Part 2

**`python/h2g/detect.py`**
- `Detection.triangle_gate`, `.envelope_cut`, `.effect_bit40`, `.pitch_seq`
- `TRIANGLE_GATE_SHAPE`, `TRIANGLE_GATE_DELTA = 56`,
  `TRIANGLE_GATE_IMMEDIATE = 6`, `_find_triangle_gate`
- `ENVELOPE_CUT_SHAPES` (2 shapes, Y- and X-indexed), `find_envelope_cut`
- `EFFECT_KNOWN_MASKS`, `EFFECT_BIT40_MASK`, `_effect_cells`,
  `_find_effect_bit40`
- `PitchSeq` dataclass (`index`, `pairs`, `base`, `steps`),
  `PITCH_SEQ_SHAPE`, `PITCH_SEQ_AT_INDEX/PAIRS/PHASE/BASE`,
  `PITCH_SEQ_STEPS`, `_find_pitch_seq`

**`python/h2g/search.py`** — `match_at(data, at, pattern)`, for a shape whose
position is known from another match rather than searched for.

**`python/h2g/goatwriter.py`**
- `CMD_VIBRATO = 0x04`, `GT_FIRST_NOTE/GT_LAST_NOTE/GT_REST`,
  `WAVE_GATE_BIT`, `EFFECT_PER_FRAME = 0x01`,
  `EFFECT_PITCH_SEQ_MASK = 0x10`
- `_vibrato_command_pass(det, patterns, vib_ptrs, lead, log)`
- `_vibrato_delay(det, multiplier, commanded=False)`
- `_fixed_attack_note(sid, det, i)` — bit `$40`'s absolute-note byte
- `_pitch_seq_entries(sid, det, i, wave)` — bit `$10`'s arpeggio
- `_two_stage_entries(..., attack_note=None)` — accepts the note, unwired
- `_sfx_drum_entries(..., second_note=None)` → now returns
  `(left, right, loop)`
- `_write_instruments(..., cut_release=False)` — `sr &= 0xF0` gated on
  `det.envelope_cut and not data[base+7] & EFFECT_PER_FRAME`

**`python/h2g/patterns.py`** — `_build_raw_pattern(..., tie=False)` with the
`pending_tie` latch; `decode_entry(..., tie=False)`;
`convert_patterns(..., tie=False)`

**`python/h2g/convert.py`** — new options `vibrato_command`, `cut_release`,
`tie`, `pitch_seq`

**`python/h2g/cli.py`** — `--vibrato-command`, `--cut-release`, `--tie`,
`--pitch-seq`, all in the presets-override list

**`python/fidelity.py`** — `release_tails`, `release_tail_agreement`, the
`tail` Dimension (`$D405/$D406`), and the generated note beside the `adsr`
summary line

**`python/presets.py`** — `FIDELITY_CONFIRMED`, `_closer`, the two new win
conditions, `pitch_seq` in `FIDELITY_TOGGLES` and
`EXCLUDED_FROM_ALWAYS`, `FIDELITY_VETOED` emptied, `always` gained
`vibrato_command`, `cut_release`, `tie`

**Tests** — extended `test_vibrato.py`, `test_fidelity.py`,
`test_effects.py`, `test_effect_bit80.py`, `test_wave_program.py`,
`test_preset_passthrough.py`. 818 pass, 2 skipped.

**Docs** — `H2G-CONVERSION-METHOD.md` §§ 7.kkk–7.uuu; README sections for
`--vibrato-command`, `--cut-release`, `--tie`; ~14 new rules in `CLAUDE.md`.
</work_completed>

<work_remaining>

Ordered by value. Items 1 and 2 are the ones the last two commits explicitly
set up.

### 1. A full `--fidelity` run (mechanical, hours)

```sh
cd python
python presets.py "C:\Users\mit\claude\c64server\SIDM2\SID\Hubbard_Rob" \
    -o ../presets.json --fidelity -t 60
```

**Why:** v0.5.208's oscillation and noise-pitch criteria only apply on a
`--fidelity` run. Every other file keeps a carried-forward entry decided by
the old scorer. Five toggles = 31 combinations per song × ~80 files, each a
convert + pack + two traces.

**Prerequisites:** `python/tools/siddump-rt` must be built (the harness
refuses a multiplier > 1 song without it); `gt2reloc` on PATH.

**Validation:** diff `presets.json` and check that `pitch_seq` appears only
where melody holds; re-run `python -m pytest tests/ -q`; regenerate
`FIDELITY.md`. Expect Trans-Atlantic to keep all four settings (it is also
pinned in `FIDELITY_CONFIRMED`, so that is not a test of the scorer).

**Note:** once this runs, the three `FIDELITY_CONFIRMED` entries for
Trans-Atlantic (`wave_program`, `pitch_seq`, `sfx_drum`) become redundant if
the search selects them independently — check and consider removing, with the
comment's history preserved.

### 2. Emit effect bit `$20`, the filter cutoff sweep (35 files)

Decoded in v0.5.204 (§ 7.qqq) and unemitted. The routine:

```
LDA effect / AND #$20 / BEQ out
LDA accum,X / CLC / ADC step,Y / STA accum,X
STA $D416                       ; cutoff high byte
LDA res,Y / STA $D417           ; resonance and routing
```

**Not yet read:** the offsets of `step` and `res` within the per-instrument
table (both are `,Y` reads, so the same record-offset convention as `$40` and
`$10` — expect them to be fields of the `det.wave_program` table or another
parallel array). Add a `FilterSweep` dataclass alongside `PitchSeq`.

**Emission target:** GoatTracker's filter table (`FTBL`), which
`--filter`/`_filter_layout` already writes. A per-frame cutoff ramp is
expressible there. The balloon song's record 1 sets `$20`, and its `cut`
column is 0.82x — so there is measurable headroom.

**Verification (do not skip):** measure on **at least two** files that use
the mechanism differently, and prefer files whose options are already
enabled — that is the lesson of v0.5.205/206.

### 3. Commando's drum sweep — 7 steps where the original runs 5

Rows 44/48 of GT pattern 18 (Hubbard 15), instrument 13:

```
original  0DD0 0CD0 0BD0 0AD0 09D0 08D0 | 08D0 08D0 08D0   <- stops, envelope -> 0000
ours      0DD1 0CD1 0BD1 0AD1 09D1 08D1 | 07D1 06D1 06D1   <- two steps too far
```

The original's sweep runs **5 steps and stops**; ours runs 7. Likely a budget
or step-count read in `_drum_entries`. **Caution:** v0.5.134 investigated a
drum-sweep *floor* and concluded none exists — this is a *length* claim, a
different thing. Check against the routine, not against the trace alone.

### 4. `0AF8` on the balloon song — 637 reversals unreached

Record 3, effect `$14` = `$10 + $04`. `_pitch_seq_entries` declines it
because its `+2` waveform is `$00` (the `not wave & 0xF0` guard), so the
two-stage path owns it. Needs a decision about precedence when both bits
apply — in the player they are *sequential tests*, not exclusive, so `$04`
sets the waveform and `$10` sets the note. Emitting both means one block
carrying the attack waveform *and* the arpeggio's relative notes.

### 5. Commando pattern 12's pulse sweep (free-running vs per-note reset)

Diagnosed and never fixed. Our duty cycle restarts at `0AC0` on every note
where the original's runs continuously across them:

```
original  0D60 0C80 0BA0 0AC0 09E0 0900 | 0900 0820 0900 09E0 ...
ours      0AC0 0B3F 0BBE 0C3D 0CBC 0CBC | 0AC0 0B3F 0BBE 0C3D ...
                                          ^^^^ reset
```

Three differences: the phase resets per note; the step is `0x7F` where the
player's is `0xE0` (= the record's `+6`), because GoatTracker's pulse step is
a **signed byte capped at ±127 per call** and 224/frame is unreachable at
multiplier 1; and the range is narrower (`0AC0`–`0DBA` vs `0820`–`0E40`).
The phase reset is likely a hard format limit (GT reloads `ptr[PTBL]` on
every new note); confirm in `gplay.c` before attempting.

### 6. Older, still open

- **The speed gate is under-read by a tune-specific 1.1–1.5×** across the
  corpus (`goatwriter.find_song_speeds`); right for 26 of 43 multiplier-1
  files, so not a constant to correct. Per-file targets in `build/pace.txt`;
  `tests/test_pace.py` pins the estimator. Use `fidelity.py <file> --pace`
  before saying anything about tempo.
- **`FIDELITY.md` still has no noise-pitch column.** Both v0.5.205's win and
  its Thundercats regression were invisible to the report and found by
  hand-rolled pitch histograms. The scorer now weighs it; the report does not
  show it.
- **`instrmap.py`'s pulse section** and the untracked `6581.pdf` (left alone
  deliberately all session).

### 7. Listening verdicts pending

- Whether the balloon song is now right — it ships four settings it did not
  have this morning (`two_stage`, `wave_program`, `sfx_drum`, `pitch_seq`).
- Commando's pattern 12 after the tie fix.
</work_remaining>

<attempted_approaches>

## Shipped, then reverted or refused

1. **`vibdelay = 12`** (v0.5.198). Scored best (88.6% vs 85.5%) and was
   refused: the moves/still column cannot see the 5 extra frames of onset
   lateness it costs, and it plateaus at 14 rather than peaking — a count
   maximised by destroying the events it counts.
2. **The per-file gate as a plain `vibdelay`** (v0.5.199). Correct constant,
   worse outcome: 78.9% vs 85.5%, inventions 207 → 417. A delay is also doing
   the suppressing, so a lower threshold gives that up. Hence the `commanded`
   parameter.
3. **`cut_release` on every record** (v0.5.200 → reverted in v0.5.201). A
   listener heard the drums break one build later. The corrected measure
   scores the shipped v0.5.200 at **62.1% against 64.6% for off** — a net
   regression published as an improvement.
4. **`release_tails` as a minimum over the gap** (v0.5.200 → v0.5.201). It
   admits the *next* note's envelope write and scored all seven instruments
   as cut. Read on the gate-off frame instead. **Widening a window is not
   automatically the safer reduction.**
5. **Bit `$40`'s pitch on the attack's first frame** (v0.5.204). Pitch
   exactly right, `melody` 85% → **39%**, because frame 0 belongs to the
   played note. Not wired.
6. **The `$40` pitch inside the looping drum block** (v0.5.205). Exact on
   Trans-Atlantic, **8× over-applied on Pandora** (281 frames where 35
   belong). The pitch fires once per note; the block loops per period.
7. **`_fixed_attack_note` gated on the file only** (v0.5.206, caught before
   commit). Reached Thundercats' drum, whose records are `$80`/`$A0` — 99
   noise frames at a pitch its original never sounds, melody 77% → 72%.
8. **`pitch_seq` as a default** (v0.5.207). Median `vib` 0.22x → 0.58x but
   mean melody 81.5% → 76.3%, seven files losing. Ships off.
9. **Rotating the arpeggio so the modal step follows the attack**
   (v0.5.207). Principled (maximum likelihood under a uniform unknown phase)
   and empirically neutral-to-worse: mean melody 77.3% → 76.3%, trading
   After_8 (92% → 52%) for Chain Reaction. **The global phase is not
   reproducible by a per-note wavetable at all.**

## Investigative dead ends

- **"Effect bit `$01` clear" dismissed at 59.8%** (v0.5.200) — computed over
  all 95 files instead of the 33 with the routine, where it is 98.6% with no
  false negatives. It *was* the mechanism.
- **Two hypotheses fitted Commando's seven instruments perfectly** (`eff &
  $01` and `release == $F`) and scored 59.8% / 79.0% corpus-wide. The answer
  was six lines of 6502. **A correlation over instruments is not a
  mechanism.**
- **Chasing `new_patterns[12]`** for three dumps against a listener's
  screenshot. GoatTracker numbers patterns in **hex**; "PATT.12" is 18.
- **Searching for `AND #$40`** — bit 6 uses `BIT`/`BVC`. Nothing could match.
- **Reading `$116B,Y` with `Y` as the record number** — gives 129 → `$1A03`,
  not a pitch in the trace. `Y` is `index × stride`.
- **A synthetic `_build_raw_pattern` test at `addr = 1`** — the decoder
  rejects `addr + i2 <= 1` outright and returns `None`.
- **Reading the emitted SR at a fixed buffer offset** — Clear Voice's name
  field is 16 bytes, not 32, so the arithmetic read the name and reported no
  change. Locate the record by its AD byte.
- **A `str.replace`-style scripted edit whose search string spanned a
  docstring terminator** — produced `""""""` and an unterminated-string
  syntax error; and a test asserting `"second_note=_fixed_attack_note" not in
  src` tripped on the *comment* that names the omitted argument.

## Considered and not pursued

- **Redefining `adsr`** so `--cut-release` scores well. Refused; the report
  prints an attribution beside the number instead.
- **Scoring `finds_noise` per instrument off `noise_runs`** — the principled
  fix for the criterion's per-file blindness. Deferred because it re-decides
  every file's toggles; v0.5.208's log-space median-pitch term addresses the
  same gap more cheaply.
- **`gt2reloc -R0`** as a fix for the slide deficit — settled negatively
  earlier: `patterns._scaled_step`'s `row_calls` correction already
  compensates, so disabling the skip double-corrects.
</attempted_approaches>

<critical_context>

## Environment

- Repo `C:\Users\mit\claude\h2g`, branch `master`, HEAD `d5f1cea`, pushed.
- Corpus (95 files):
  `C:\Users\mit\claude\c64server\SIDM2\SID\Hubbard_Rob`
- GoatTracker 2.77 source (the version this builds against):
  `C:\Users\mit\Downloads\GoatTracker_2.77\src` — `gplay.c`, `gsong.c`,
  `gcommon.h`. Cited constantly; keep it to hand.
- Build outputs in `build/` (gitignored). `6581.pdf` untracked, deliberately.
- Python 3.14, stdlib only at runtime; `pytest` dev-only.

## Non-obvious behaviours discovered this session

- **`gplay.c:770`** — the `vibdelay` countdown is inside `case
  CMD_DONOTHING`, so a pattern `CMD_VIBRATO` skips it entirely.
- **`gplay.c:811`** — `CMD_TONEPORTA` with parameter **0** is an instant
  pitch jump, not a slide, and zeroes `vibtime`.
- **`gplay.c:930`** — the hard-restart gate-off is skipped when the row's
  command is `CMD_TONEPORTA`, or when the instrument's gatetimer has bit
  `$40`.
- **`gplay.c:925`** — only `$60`–`$BC` assign `newnote`; `$BD` (REST) is
  "no new note", not a stop.
- **GoatTracker numbers patterns in hex** in the editor. Clear Voice's
  instrument-name field is **16 bytes**, not 32.
- **A wavetable delay entry holds the *current waveform*** — a delay after a
  noise entry keeps sounding noise.
- **GoatTracker's pulse step is a signed byte, ±127 per call**; a player
  wanting 224/frame is unreachable at multiplier 1.
- **Status bit 5 of a Hubbard pattern status byte is a tie flag** — three
  separate defects came out of that one bit (§§ 7.mmm, 7.nnn, 7.ooo).
- **`det.wave_program`'s array is read three different ways** depending on
  the effect bit: a pointer low byte under `$08`, a note index under `$40`, a
  sequence index under `$10`.
- **`Y` in these players is a record *offset*** (`index × instr_stride`), not
  a record number.

## Standing project rules that bit this session

All are in `CLAUDE.md`; these are the ones that actually mattered:

- Regenerate `SURVEY.md` and `presets.json` **every commit** (they embed the
  version); `FIDELITY.md` only after a commit that changes what the converter
  emits, and never from a tree with unrelated edits.
- **Check the fixture's bytes, not its length** — `len(...) == 15193` passes
  for most single-byte moves.
- **A scripted edit must assert its match**; verify the change appears in
  `git diff`.
- `--vice`/`FIDELITY.md` numbers either side of v0.5.195 are not comparable
  (the window changed from 10 s to 60 s).
- **Never launch `goattrk2.exe` directly** — use `.\play.ps1 <file>
  -Presets presets.json`, which prints the SHIFT+F6 multiplier hint. 37 of 82
  files advance a row every 2–3 frames and play at 1/multiplier speed
  otherwise. `play.ps1` also accepts a `.sng` directly, which is how A/B
  builds were launched.
- A new `convert()` option is inert until it is in **three** places: the
  signature, `presets.py`'s `FIXED`, and `_preset_opts`.
  `tests/test_preset_passthrough.py` enforces it via
  `EXCLUDED_FROM_ALWAYS`.

## Rules added this session (all in `CLAUDE.md`)

1. A constant read from one player is a constant about one player.
2. The same number can be right for a mechanism and wrong for its
   approximation.
3. An attribution key must not contain the quantity being attributed.
4. A correlation over instruments is not a mechanism.
5. Widening a window is not automatically the safer reduction.
6. A discriminator is only meaningful on the population the behaviour occurs
   in.
7. GoatTracker numbers patterns in hex; the editor's pattern is not the
   converter's intermediate — identify by note-row positions.
8. Reading a bit is not drawing its consequence.
9. A bit tested with `BIT`/`BVC` is invisible to an `AND #$xx` scan.
10. Where an effect's frames *land* is part of the mechanism.
11. A per-frame profile measured on one file can encode that file's structure
    rather than the mechanism's — verify on a second file that uses it
    differently, preferring files whose options are already enabled.
12. A detection flag about a player is not a fact about a record.
13. A rate that looks wrong may be a mechanism that is absent — attribute a
    ratio per instrument first.
14. A mechanism driven by a global counter cannot be put in a per-note
    wavetable.
15. Compare a ratio in log space.

## Assumptions that still need validation

- `PitchSeq.base`'s `seq[0]` is 0 in **every file checked**, not proven for
  all 34.
- `$40`'s note index is validated by measurement on **one** instrument
  (Trans-Atlantic record 1). Records 15 and 18 hold 174 and 132, past the
  95-entry note table, and `_fixed_attack_note` declines them rather than
  guessing.
- `_two_stage_entries`' `frames` byte is 4 for Trans-Atlantic record 1, but
  the measured attack occupies offsets +1..+2 (two frames). The relationship
  between that byte and the shared `$0FAA,X` counter is **not** established.
- The `$20` filter sweep's per-instrument `step`/`res` offsets are unread.
</critical_context>

<current_state>

## Repository

- **HEAD `d5f1cea` (v0.5.208), pushed; `master` in sync with `origin/master`.**
- Working tree clean except untracked `6581.pdf` (deliberate).
- `python -m pytest tests/ -q` → **818 passed, 2 skipped**.
- `Commando.sng` byte-exact (`convert('Commando.sid') == Commando.sng`).
- `SURVEY.md`, `presets.json`, `FIDELITY.md` all regenerated at v0.5.208 and
  committed.

## Shipped on by default (in `presets.json`'s `always`)

`--vibrato-command`, `--cut-release`, `--tie`, plus everything from before.

## Shipped off by default

- `--pitch-seq` — in `FIDELITY_TOGGLES` (searched per song), never in
  `always`.
- `--sfx-drum`, `--two-stage`, `--wave-program`, `--no-test-restart` — all
  per-song `FIDELITY_TOGGLES`.

## Read but not emitted

- **Effect bit `$20`** — the filter cutoff sweep, 35 files. Fully decoded
  (§ 7.qqq), no detector fields, no emitter.
- **Bit `$40`'s `_fixed_attack_note`** is wired only into
  `_sfx_drum_entries`' prologue. `_two_stage_entries(attack_note=...)`
  accepts it and **nothing passes it** — deliberate, with the reason in a
  comment at the call site.

## Per-song overrides in `presets.py`

- `FIDELITY_VETOED` — **empty**, kept as a comment recording the retired
  Trans-Atlantic `sfx_drum` veto and why.
- `FIDELITY_CONFIRMED` —
  `{"Trans-Atlantic_Balloon_Challenge.sid": {"wave_program", "pitch_seq",
  "sfx_drum"}}`. These are hand-recorded measurements standing in for a
  `--fidelity` run that has not happened.

## Balloon song (Trans-Atlantic) — the file most worked on

Ships `two_stage`, `wave_program`, `sfx_drum`, `pitch_seq`. Its
`FIDELITY.md` row at v0.5.208: 494/494 notes, retrig 1.00, melody 85%, seq
86%, pitch 91%, `vib` **0.72x**, wave 63%, noise **1089/1089**, `nrun`
**100%**, tail 100%, adsr 87%, pul 6505/6890, pspan 0.98x, filt 2992/2996,
cut 0.82x.

Known-remaining on it: instrument `0AF8` (637 reversals unreached), the `$20`
filter sweep unemitted, `wave` at 63%.

## Open questions for the user

1. Whether the balloon song now sounds right — four settings changed today.
2. Whether Commando's pattern 12 is fixed by the tie (last heard before it).
3. The last listening report was **"I cannot hear any difference on the
   drums"** between the shipping build and one with `--sfx-drum`. That
   retired the veto; it is *not* an endorsement, and is recorded as such.

## Immediate next action

The user's last message asked whether the session can run on Sonnet. My
answer: I cannot switch my own model (`/model sonnet` is theirs to set), and
my read is that the long `--fidelity` run and the Commando drum-sweep fix are
fine on Sonnet, while the `$20` emission and the `0AF8` precedence decision
would benefit from Opus — because today's pattern showed that the work in
those is not writing the emitter but disbelieving it (three regressions were
caught only by checking a second file). **No model switch has occurred; no
work is mid-flight; nothing is uncommitted.**
</current_state>
