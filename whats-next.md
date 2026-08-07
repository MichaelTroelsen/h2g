<original_task>
Continuation of work on `C:\Users\mit\claude\c64server\hubbard` — **H2G**, a
converter from Rob Hubbard `.sid` files to Goattracker `.sng`. This session
began at **v0.5.81** (HEAD `46ba1f8`) from the previous handoff and ran to
**v0.5.94**.

The user drove it as a sequence of single-item directives, each answered before
the next was given:

1. `continue` → pick up the largest open item (§1, the per-call/per-frame
   multiplier defect)
2. `what next` → recommend and start §1b (the slide-step clamp)
3. `start on 1b with the 6502 check`
4. `do the digi decoder next`
5. `do the cmdtable slide next`
6. `now do the overshoot`
7. `now do the drum gate`
8. `now do the retrodebugger run on bump_set_spike`
9. `continue` → (RetroDebugger dead) the listening pass / RSID rendering
10. `/subtask` → add LoadTracker to a linked comparison of GoatTracker clones

Standing rules from `CLAUDE.md` that shaped every commit: bump the version on
every commit, regenerate `SURVEY.md`/`presets.json`/`FIDELITY.md` on a settled
tree, never ship a fake success, keep `Commando.sng` byte-exact, stage only
`hubbard/` paths by pathspec.
</original_task>

<work_completed>

## Headline

| | start (v0.5.81) | now (v0.5.94) |
|---|---:|---:|
| corpus at defaults | 80/95 | 80/95 |
| best per-song options | 83/95 | 83/95 |
| tests | 520 | **547 pass, 3 skipped** |
| mean melody / wave (82 measured) | 78% / 62% | 78% / 62% |
| **corpus median `bend`** | — (did not exist) | **0.25x** |
| **files bending nothing** | 33 (once measurable) | **18** |

`Commando.sid` → `Commando.sng` **byte-exact** throughout.

## Commits (all pushed to origin/master)

```
03df994 v0.5.82  divide every per-frame rate by the -S multiplier
b87db99 v0.5.83  read the second slide dialect, and index the step at full width
a506c27 v0.5.84  exclude ties from bend, and name the vibrato as the missing movement
e0db4b0 v0.5.85  emit the vibrato every player runs and no output ever had
baf7e5a v0.5.86  read the digi engine's own pitch slide, effect $82
4c8d428 v0.5.87  read the command-table engine's pitch slide
f7011c3 v0.5.88  take bend from siddump's own delta, not the frequency column
76a49c2 v0.5.89  explain Thrust -- bend cannot compare a stepped sweep to a glided one
1776474 v0.5.90  read the drum gate in full -- cross-voice state, noise is the attack
bea3feb v0.5.91  run the player -- the drum does fire, and bend cannot see it
185b38d v0.5.92  render RSID originals through VICE, both sides of the pair
5fd1cbd v0.5.93  compare GoatTracker's forks; the GTS2 overrun is in all of them
cfbc941 v0.5.94  the forks LoadTracker merged -- gt2fork, leafo, Langner's GTUltra
```

Conversion output changed in v0.5.82, .83, .85, .86 only. v0.5.87 changed no
bytes (see below). v0.5.84, .88–.94 are harness or documentation.

## v0.5.82 — every per-frame rate divided by the `-S` multiplier

Every rate read out of a Hubbard player is **per frame**; every table
Goattracker applies them with steps **per play call** (`gplay.c:707` wavetable,
`:748/758` speed-table deltas inside per-call `TICKNEFFECTS`). Identical only at
`gt2reloc -S1`, and **33 of 83 preset songs pack at -S2**.

| rate | site | at `-S{m}` |
|---|---|---|
| slide, GTS5 | `patterns.build_speed_table` | 16-bit step ÷ m — exact |
| slide, GTS2 | `patterns.scale_portamento_data` | ÷ m rounded, never 0 |
| drum sweep | `goatwriter._drum_speed` | 256 ÷ m floored, never 0 |
| chromatic rise | `goatwriter._rise_speed_index` | +1 shift per doubling (`_rate_shift`) |
| attack transient | wavetable delay `$01-$0F` | `_wave_delay`, held m calls |

Differential over the corpus: **exactly the 33 multiplier-2 songs changed
bytes; none of the 50 multiplier-1 songs did.** New file
`python/tests/test_call_rate.py` (21 tests).

Residuals recorded, not fixed: the arpeggio alternation and the drum's own
attack have no free wavetable slot; the rise's shift is exact only for
power-of-two multipliers (nothing asks for `-S3`).

## v0.5.83 — the second slide dialect, and a 16-bit step index

The two-byte slide fetch (`SLIDE_OPERAND_SHAPE`, 41 files) says a second byte
exists, not which half of the step it is. **Two players disagree behind the
same fetch shape:**

```
Warhawk $1320       operand & $7E = LOW half, bit 0 = direction,
                    fetched byte = HIGH half
Flash Gordon $12EB  operand & $3F = HIGH half (self-modified into an
                    immediate), fetched byte = LOW half,
                    direction = CMP #$BF / BCC
```

Verified byte-for-byte in Flash Gordon `$12EB`, Sanxion `$B2E1`, Delta `$C0D6`.
Census partitions cleanly: **25 Warhawk, 22 this, none both**; `CMP` immediate
`$BF` and mask `$3F` in all 22. Read the wrong way round the step is ~256×
too large — which is why **2189 of 5566 portamento parameters (39%, 15 files)**
sat on the `min(step // 4, 0xFF)` clamp. All 15 are in the swapped dialect.

Correcting the dialect alone pushed 250 columns *under* 4, which `gplay.c`
reads as no parameter — the same mistake from the other end. So the column now
carries a **1-based index** into a per-file list of full-width 16-bit steps
(`patterns._step_index`, `MAX_SLIDE_STEPS = 255`; worst corpus file uses 40).
GTS2 keeps the packed byte (its loader reads the column as the value,
`gsong.c:311-321`).

New: `detect.SLIDE_HIGH_FIRST_SHAPE`, `Detection.slide_high_first`,
`patterns._scaled_step`. Tests appended to `tests/test_slides.py`.

## v0.5.84 — `bend` excludes ties; the vibrato named

`bend` (added v0.5.83) excluded only *attack* frames, so a **tie** — a note
change with no re-gate — counted its whole pitch jump. Pygmies_Revenge (493
ties in 10 s) read **21.7 million** units against ~12 thousand of real bending.
Corrected: `Voice.tie_frames` recorded and excluded.

The v0.5.83 verdict survived, its magnitude did not: Flash_Gordon's dialect fix
reads **1.67x → 1.51x**, not 0.30x → 0.66x. Both docs corrected in place.

Then the diagnosis: **33 of 95 files move the pitch not at all** where the
original does. Splitting those originals by net÷total movement (a sweep
travels, a vibrato returns) gives **20 vibrato, 11 mixed, 2 sweep**.

## v0.5.85 — vibrato emitted for the first time

`gplay.c:352-354` loads `cptr->vibdelay = iptr->vibdelay` and
`cptr->cmddata = iptr->ptr[STBL]` on every new note; a channel with no command
falls through `CMD_DONOTHING` into `CMD_VIBRATO`. Those are instrument-record
bytes 5 and 6 in a GTS5 file (`gsong.c:224-225`) and
`_write_instruments` had written `0x00, 0x00` since the port began. **No `.sng`
this project ever produced vibrated.**

The parameter is one instrument-record byte at **+5**: bits 3-6 an amplitude
bound, bits 0-2 a right-shift on the semitone interval at the current note
(Warhawk `$11EF` splits it; `$1221` derives the depth as
`freq(note) − freq(note−1) >> shift` — which is `gplay.c:786-792` in 6502).

**Census with no exceptions**: 56 of 95 files match the split, masks `$78`/`$07`
in all 56, record `+5` in 49 (7 use addressing the reader doesn't recognise and
are skipped), and **all 56 also carry the note-relative depth**.

Mapping derived, not fitted: match the half-period → `cmp = 2·bound·multiplier`;
match the excursion under it → `rshift = shift + 1 + log2(multiplier)`. Entry
`($80 | cmp, rshift)`, `vibdelay = 1`.

| | before | after |
|---|---:|---:|
| corpus median `bend` (old metric) | 0.06x | **0.33x** |
| files bending nothing | 33 | **11** |
| moved toward original / away | — | **29 / 6** |

No other dimension moved. All six that moved away were already overshooting.
GTS5 only. New: `detect.VIBRATO_SHAPE`, `_find_vibrato`,
`Detection.vibrato_offset`, `goatwriter._vibrato_layout`, `--vibrato` CLI flag,
`presets.FIXED["vibrato"]`, `tests/test_vibrato.py` (13 tests).

## v0.5.86 — the digi engine's `$82` slide

Effect `$82` is a **signed 16-bit per-frame step**, first operand HIGH, second
LOW (Off the Cuff handler `$1133`, consumer `$134C`, one `CLC/ADC` and no
direction test). Gate cleared at note start (`$10F4`), which is what
`gplay.c:351` does with a channel's command.

Effect `$83` turned out to be a **vibrato** in the identical `$78`/`$07` format
(`$1229`, falling back to the instrument byte at `$1704,Y`) — left untranslated.

All nine digi files carry both shapes; **the music uses `$82` in only five, 128
columns total**, and no report number moved.

**The better finding from that chase:** `bend` cannot tell a pitch bend from a
voice used as a **sample channel**. Off_the_Cuff's three voices travel 3,032 /
8,855 / **5,426,086** units in 10 s — 99.8% is digi playback. An octave guard
(reject a frame whose frequency ratio exceeds 2) was **tried and rejected**: it
removed a sixth of the sample movement and cost real signal (Delta 56,531 →
40,429, two voices zeroed). Documented in the report instead.

## v0.5.87 — the cmdtable slide, which reaches nothing

Command 1 in both cmdtable players (Hollywood or Bust `$071B`, Chicken Song
`$1301`, byte for byte identical): operand 1 = step LOW, operand 2 = HIGH under
`$3F` with **bit 7 the direction**, operand 3 = an onset delay Goattracker
cannot express (read and dropped). The command index is derived by linking the
consumer's cells to the handler that fills them, in order — not assumed.

**Neither tune uses it.** Hollywood or Bust reaches commands 0, 2, 4, 5, 6;
Chicken Song 0, 2, 4, 5. All 83 preset songs byte-identical; the A/B mode
reported *"this change reaches nothing"*, which is the correct reading. Kept
because a *misread* command byte would desynchronise where an unread one does
not, and the reading is now pinned by tests.

Hollywood or Bust's missing bend is a **table-driven vibrato** —
`(interval >> 4) × table[i]`, the table walked one entry per frame with `$FF`
wrapping (`$05F3`, `$0630`) — a third form, not implementable as GT's fixed
triangle. Not attempted.

## v0.5.88 — `bend` taken from siddump's own delta

Chasing the overshoot found the **fourth** defect in `bend` before it found
anything in the converter. It was differencing the frequency column and
excluding frames siddump marked as a note — but **a Goattracker wavetable entry
whose right side is a relative note rewrites the frequency without touching the
gate**, and siddump prints that as a frequency with an empty note field. Every
note onset in our own output counted as bending. Zoolook: 121,107 units against
~3,400 of printed bends.

Fixed by not re-deriving it. `bend` now sums the magnitudes of siddump's own
`(+ xxxx)` / `(- xxxx)` lines, so `bend` and `slides` are a sum and a count of
the same lines, as `cut` is to `filt`.

| | before | after |
|---|---:|---:|
| Delta_Mix-E-Load_loader | 10.80x | **0.96x** |
| Zoolook | 9.65x | **0.26x** |
| Confuzion | 8.96x | **0.00x** |
| Thing_on_a_Spring | 3.36x | **0.35x** |
| Chain_Reaction | 2.19x | **0.26x** |
| Knucklebusters | 1.64x | **0.00x** |

Rule added to `CLAUDE.md`: **take the measurement from the tool rather than
re-deriving it.** Four corrections in six versions; the three wrong ones all
re-computed pitch travel from raw registers.

The drum sweep was also re-measured against pitch (not waveform): removing it
is **right for one file and wrong for eight** (Game_Killer 1.08x and
Crazy_Comets 1.03x drop to 0.00x), at zero cost in `wave`. Kept.

## v0.5.89 — Thrust explained

Thrust's tune **is** the chromatic rise; both sides play it. The player *steps*
on exact semitones (`INC noteindex,X` + a table re-read) so siddump names every
frame — **443 tie lines against 25 bends**. We *glide* (a note-relative
portamento; GT cannot step a note from the wavetable without one entry per
semitone) — **125 ties against 89**. `bend` counts only bend-labelled frames, so
the original's sweep is invisible and ours is fully visible: 43x, while both
travel comparable distances over the same notes.

No converter change. `--fold-transpose` refuted as a cause (identical bytes with
it on and off). This file's `pitch = 100%` rests on **4 attacks against 2**.

## v0.5.90 / v0.5.91 — the drum gate, read and then run

The block is byte-identical in Warhawk `$1366`, Bump_Set_Spike `$B34B`,
Gerry_the_Germ `$E2FA`. Condition: bit `$01` on the effect cell, nonzero
frequency-hi, nonzero remaining duration, then `CMP`/`BCC` where `A = W−1` and
`M` counts down from `W` — so the branch fires while the counter is **large**:
**the noise is the attack, and the sweep runs after it for `W−1` frames**
against the one this writer emits. *That direction had been recorded backwards
since v0.5.62.*

**The gate is not a property of the instrument.** `LDA effect` is `AD` —
absolute, not `,X` — and the cell (`$15BD` Warhawk, `$B504` Bump_Set_Spike) is
written in exactly one place, the note-start path, as `STA abs`. All three
voices share it.

Three static proxies tried and **all refuted**: note duration (no drum note
lasts 1 tick; lengths 2–9), drum share of note-starts (30/14/39% overshooting
vs 14/34/23/32/19% benefiting — overlapping), the `freqhi` guard
(Bump_Set_Spike sits at `$02B9`+).

**v0.5.91 ran the player** (VICE; RetroDebugger had crashed). Bump_Set_Spike's
drum **fires**: 78 sweep-branch hits vs 61 noise in 400 stops, bit `$01` set at
226 of 261 block entries, and the voice-2 frequency-hi shadow walking
`0D 0C 0B 0A 09 08 07` one per play call with `$D401` following. **What it does
not do is register as a bend** — 256 units at those frequencies is more than a
semitone, so siddump names each step a note and `bend` excludes ties. So
Bump_Set_Spike's 11.79x is Thrust's artefact again, and the converter
*under*-renders the drum. The earlier "right for one file, wrong for eight" was
scored on a dimension blind to the original's drum in every one of them.

## v0.5.92 — RSID originals render

`SID2WAV` is v1.8 (1997) and predates RSID; it refused **18 of 95 corpus
files**, a set including all four NTSC files and Skate_or_Die_intro. **The
blocker was `-warp`**, which suppresses VICE's sound device output entirely —
the 44-byte header-only file from three earlier attempts. `-soundwarpmode 1`
does *not* rescue it (tested, refuted). Without warp it renders, in realtime.

`listen.py` gains `render_vsid` + `_sid2wav_can_read` (decides from the magic,
not a trial render). **Both sides of a pair go through one renderer**, because
gt2reloc always writes PSID and two emulations differ enough in level and
filter to colour a listening judgement. Verified on Last_V8 and Off_the_Cuff
(both sides 959,788 bytes).

**The listening pass is staged** in `build/listen/` (gitignored), one tune per
band at 20 s, with `LISTENING.md`:

| band | tune |
|---|---|
| plays something else | Flash_Gordon |
| recognisable | Formula_1_Simulator |
| close | International_Karate |
| plays the same music | Crazy_Comets |

plus Last_V8 and Off_the_Cuff staged separately at 10 s as the RSID proof.
20 WAV files present.

## v0.5.93 / v0.5.94 — `GOATTRACKER-FORKS.md`

New file comparing GoatTracker 2 and seven relatives, with links, base version,
licence, platform and what each adds — every claim checked against the linked
repository. Pointer added from `GOATTRACKER.md`.

**The finding that earns it a place:** `GOATTRACKER.md` issue #1, the GTS2
importer overrun (`length` is a byte count, `d` indexes rows), is present in
**six of six** forks checked:

```
GoatTracker 2.77   src/gsong.c:306        LoadTracker   src/song.cpp:607
gt2fork            src/song.c:359         leafo         src/gsong.c:306
GTUltra            src/gsong.c            Silver Fork   src/gsong.c
```

So `--format gts5` holds against all of them.

v0.5.94 corrected an attribution gap: LoadTracker's README credits its headline
features to *other* forks — dual SID from **gt2fork** (SpiderJ / Jan
Wassermann), JACK+MIDI from **leafo**, instrument view from **Daniel Langner's
GTUltra fork**. Three rows added. **`2bt` is Daniel Langner**, who also
maintains GTMobile — so two rows are one person. LoadTracker's real
contribution is the *integration* (CMake, SDL3, C++ port, reSIDfp/exSID, 2.77
sync). Also recorded: CSDb credits Silver Fork to RaveGuru, the repo to Joel
Ricci, with identical change lists.
</work_completed>

<work_remaining>

## 1. The listening pass — staged, never performed

**The one item that requires a human and cannot be delegated.** Four pairs at
20 s in `build/listen/`, `LISTENING.md` says what to decide in each. About
three minutes of listening. In ~30 versions of fidelity work, exactly one file
has ever been listened to.

The most informative is **Crazy_Comets** (band: plays the same music): its
`bend` sits at 1.03x *because* of the drum sweep, and it is the first chance to
hear whether one 256-unit step where the player takes six or more is audible.

Re-stage after any conversion-changing commit:
`python listen.py <sid_dir> --from-json ../build/fidelity.json -n 1 -t 20`

## 2. The drum is under-rendered — `W−1` steps, we emit one

Now that the gate is understood (v0.5.90/91), the open question is not *when*
but *how much*. The player sweeps for the note's duration less one; the
wavetable emits a single step. All five wavetable entries are in use, so
lengthening it costs the gate-off waveform or the sweep itself — a trade never
tried. **`bend` cannot adjudicate it** (it does not see the player's stepped
sweep at all), so this needs the listening pass or a VICE A/B.

## 3. The drum's noise is its attack — two shelved results are now suspect

The `BCC` direction was backwards since v0.5.62, so:
- the shelved "noise ending" measurement (58.1% vs 60.6%) was testing noise at
  the **wrong end** and is not evidence about the player's shape;
- the *inherited* leading noise tick, which method-doc §7 dismissed as "not in
  the player at all", is **back in question**.

Neither re-measured. Five wavetable entries are full, so an attack tick costs
something else.

## 4. Wavetable Phase 2 — what is left

- ~~**Bit `$08`'s pulse-width variant.**~~ **Shipped in v0.5.80**, one version
  before this session began; the bullet below it was carried stale for five
  handoffs. `goatwriter._pulse_lo_program` fires on **294 records across 21
  files**, and **no file** carries both it and the triangle sweep. The
  two-entries-per-instrument layout it needed changed in the same version
  (`_pulse_layout` returns start positions, not a stride).
- ~~**Bit `$80`** … which no per-instrument wavetable can express.~~ **That
  sentence was true of 9 of the 12 files and false of 3.** All twelve blocks
  are now disassembled — method-doc § 7.jj, `detect._find_effect_bit80`,
  `tests/test_effect_bit80.py`:
  - **9 files — the *game's* sound effect, not the tune's.** A global counter
    cell driving fixed writes to `$D40F`/`$D412`/`$D416`/`$D418` (voice-3
    noise + filter + master volume). Nothing in a rip ever writes that cell,
    so the block is dead code, and converting it would be wrong even if the
    format allowed it. **Closed: the right encoding is no encoding.**
  - **2 files — a real per-instrument byte-code wave program** (ACE II
    `$E357`, Auf Wiedersehen Monty `$E743`). 16-bit pointer per record, per-
    voice PC, one entry per frame: `$85` holds, `>= $80` is (waveform →
    `$D404`, next → `$D401`), `< $80` is (waveform, 16-bit `SBC` off the
    frequency). **This is the one open piece of Phase 2.** The waveform column
    maps to a Goattracker wavetable exactly; the pitch column is a raw
    frequency delta against a note-named right side, so it can only be
    approximated. Encode it behind `--effects`, A/B the two files with
    `fidelity.py --baseline`, ship only if it wins. Do not ship it unmeasured.
  - **1 file — a stepped frequency table** (Delta `$C1EC`): per-voice counter,
    on expiry reload duration from `$C43E,Y` and add `$C43F,Y` to the voice's
    frequency high. Same family as § 7.ee's vibrato. One file; low priority.
- **Do not re-derive and re-ship the shelved encodings** — but see §3: one of
  the two measurements is now known to have tested the wrong thing.

## 5. Hollywood or Bust's table-driven vibrato

`(interval >> 4) × table[i]`, the table walked one entry per frame with `$FF`
wrapping (`$05F3`, `$0630`). Goattracker's vibrato is a fixed triangle, so this
can only be approximated: the table's **peak** gives the excursion and its
**length** the period. Derivation is in method-doc § 7.gg. Affects two files
(Hollywood_or_Bust at 0.00x, Chicken_Song whose original has zero slide
frames), so the payoff is one file.

## 6. Files that still play something else

`Commodore_64_Music_Examples` and `Dragons_Lair_Part_II` are **genuinely
scrambled** — both peak at 18–25% at a *different* constant shift per voice.
`Flash_Gordon` and `Rasputin` are severe under-production with pitches exact
(peak at `k=0`). `Delta_Mix-E-Load_loader` scores low at presets because
`--initial-instrument` is deliberately opt-in.

Method note: the position-aligned modal delta degrades when either side drops
notes. A *high* share is sufficient evidence of a transposition; a *low* share
is **not** evidence of scrambling. Sweep a constant shift k over ±24 and take
the difflib ratio at each.

## 7. ~~Measuring the `-S2` group needs a cycle-accurate trace~~ — done in v0.5.99, and it found something

The 33 `-S2` files are now traced at the rate they are packed for.
**`python/tools/siddump-rt`** is siddump 1.08 vendored plus one option,
`-m<n>` = playroutine calls per displayed frame; a dump row stays one PAL
frame of real time, so both sides share a time axis whatever the call rate.
`fidelity.py` passes each song its own multiplier and **refuses** a
multiplier > 1 song on a binary without `-m` — siddump's option switch has no
`default:`, so a stock binary handed `-m2` drops it silently and returns half
the tune.

The VICE harness was not needed. Verified rather than assumed:

- `-m1` output is **byte-identical** to the shipped `siddump.exe`.
- The `-S` stub is at the packed file's **init** address, writes
  `0x4cc7/multiplier` to timer A and falls through to the player; the play
  address is the player itself (`greloc.c:140`, `:1616`, `:1636`). So entering
  play *n* times a frame is what the CIA does, not a model of it.
- The same `.sng` packed at `-S1` and `-S2` traces identically at a given
  `-m`, on three files. `-S` really is invisible to siddump; `-m` is the knob.

**What it found is not the uniform lift this item expected.** Of the 33:
**15 score better at the packed rate** — Ricochet 70% → 100%, Flash_Gordon
30% → 75%, Warhawk 68% → 96%, W_A_R_Preview 73% → 95%, Star_Paws 62% → 91% —
and **17 score better at 50 Hz**, some steeply (Deep_Strike 100% → 14%,
Game_Killer 71% → 5%, Spellbound 78% → 11%). One is flat. Corpus mean melody
78% → 74% because the report now scores the file that ships.

Ricochet is the confirmation §7 was after: at 100 Hz its attacks land within
0.4% of the original's frames, per voice. v0.5.82's multiplier fix does reach
real time — for that half of the group.

**The other 17 are the new open item, and it is the largest one in the
converter.** Something in them is a factor of two out: `find_song_speeds`
reads `frames = 2` for all 33 alike, and the source kind (static reload byte
vs per-subtune table) does not separate the groups, so it is not simply a
mis-read gate. Candidates: the rows the converter gives a note (a doubled
rows-per-unit would cancel the multiplier exactly), `tempo_command_value`'s
floor at `TEMPO_FASTEST_STEADY`, or the `-S` choice itself. **Not
attributed** — do not assume the direction. A caution from doing this: the
attack-frame slope is only meaningful where the two note sequences align, so
it reads as garbage on exactly the files in dispute; `melody_at_1x` in the
JSON is the number to work from, and `--calls-per-frame 1` reproduces every
pre-v0.5.99 measurement.

Still not cycle-accurate: calls inside a frame run back to back rather than at
timer intervals, registers are sampled at end of frame, and the 0.25% between
100.25 Hz and 2 × 50 Hz is ignored. The VICE harness remains the tool if any
of that starts to matter.

**`FIDELITY.md` is deliberately not in this commit** (the concurrency rule:
generated files are regenerated once on `master`, after the merges). The
numbers above were taken from a run of this branch. Regenerate on the merged
tree — **and build the tool first, or the run will refuse the 33 files**:

```sh
cd python/tools/siddump-rt && make && cd ../..
python fidelity.py <sid_dir> -t 10 --presets ../presets.json -o ../FIDELITY.md
```

## 8. Four players have no expressible rate

Mozart, Ninja and Mega Apocalypse run the player *v* of every *v+1* calls.
Chain_Reaction needs 5.5 calls per row — tractable, since a different
rows-per-note reaches it exactly (2 rows at tempo 11, or 11 rows at tempo 2, at
`-S1`): a re-gridding decision rather than an impossibility.

## 9. Smaller items

- **`Kings_of_the_Beach_ingame` plays 138 noise frames where the original plays
  none** — the report's `!` marker, the only file flagged. Uninvestigated.
- **The 7 files whose vibrato byte is reached by unrecognised addressing**
  (Go_Go_Dash, I_Ball, Lakers_vs_Celtics, Lion_Heart, Pacific_Coast, Radio_ACE,
  Sun_Never_Shines). An under-read; only I_Ball converts today.
- **Six players index their frequency table through an idiom
  `find_freq_table` does not recognise** (Casio_Extended, Dont_Step_on_My_Wire,
  Era_of_Eidolon, Robs_Life, Task_Force, Up_up_and_Away). Under-read only.
- **The cmdtable grammar's slide is read but unused by both tunes** — nothing
  to do unless a new file turns up.
- `find_init_writes` steps over `JSR`s, so a helper's writes are missed.
- `SURVEY.md`'s `Ver` column shows the *orderlist* family for digi files, so
  the digi engine is invisible there. Cosmetic; has cost a fork a detour.
- 3 files still fail at survey defaults (`Delta`, `Dragons_Lair_Part_II`,
  `W_A_R`, all `TOO MANY NEW PATTERN CREATED`) but convert under presets.
- **Report the GTS2 overrun upstream** — LoadTracker is the fork most likely to
  take the fix (actively maintained, 2.77-synced).
- Two `MTEngine-crash-*.dmp/.txt` files sit **untracked in the repo root** from
  the RetroDebugger crash. Delete or keep; not mine to remove.

</work_remaining>

<attempted_approaches>

## Refuted this session — do not resurrect

1. **"`-soundwarpmode 1` is why VICE renders no audio."** Tested first; still
   44 bytes. It is `-warp` itself that suppresses the sound device.
2. **"An octave guard fixes `bend` on the digi files."** Rejecting frames whose
   frequency ratio exceeds 2 removed only a sixth of Off_the_Cuff's sample
   movement (5.43M → 901k) and cost real signal elsewhere (Delta 56,531 →
   40,429, two voices zeroed). A threshold separating vibrato from sample
   playback is two orders of magnitude wide.
3. **"The drum overshoot is a false-positive probe."** Bump_Set_Spike's block
   is Warhawk's byte for byte, 27 of 60 records set bit `$01`.
4. **"The drum fires only on notes longer than 1 tick."** No drum-instrument
   note in any of the three overshooting files lasts 1 tick (lengths 2–9).
5. **"Files overshoot when drum instruments make a large share of
   note-starts."** 30/14/39% overshooting against 14/34/23/32/19% benefiting —
   overlapping.
6. **"The `freqhi` guard rejects the sweep on low notes."** Bump_Set_Spike's
   originals sit at `$02B9` and above.
7. **"Bump_Set_Spike's player never triggers its drum."** Ran it: 78 sweep
   hits, and the frequency shadow walks down one per call. It fires.
8. **"Thrust's vibrato is computed at a note two octaves too high."** Its
   movement is monotonic, not oscillating — it is the rise, not vibrato.
9. **"`--fold-transpose` causes Thrust's overshoot."** Identical bytes with it
   on and off.
10. **"The digi files bend nothing because the decoder has no slide path."**
    They bend nothing because there was no vibrato; v0.5.85 fixed it before the
    digi slide was written, and `$82` turned out to be used by only five files.
11. **"Removing the drum sweep is right because it overshoots."** Right for one
    file, wrong for eight — and that measurement was itself taken on a
    dimension blind to the original's drum.
12. **"`bend` can be computed by differencing siddump's frequency column."**
    Three attempts, three failures: attacks, then ties, then bare frequency
    writes at note onset. Take siddump's own `(+ xxxx)` instead.
13. **"Daniel Langner's GTUltra fork could not be located."** (A sibling agent's
    conclusion.) LoadTracker's README links it directly:
    `github.com/2bt/GTUltra`, and `2bt` resolves to Daniel Langner.

## Carried forward, still refuted

The "~7× re-triggers" miscount; `$BD` as a re-trigger (a no-op,
`gplay.c:908-941`); `gatetimer` as a note length; "the fabricated wavetable
invents noise"; "Devils Galop needs a table-copy reader"; "GT's gate mask is
sticky"; "the tempo scatter is per-file variance"; "wiring `-S` will unblock
the 33 mis-scored files"; "the slide gap explains the low melody scores";
"instrument +6 is vibrato"; "3 calls per row is a corpus-wide constant";
"gt2reloc renumbers subtunes"; "Delta has a pattern-table undercount"; "the
instrument tables over 50 records are genuine"; "a low modal-delta share means
the music is scrambled"; "the `$04` bit is an arpeggio in every player".

## Tooling failures

- **RetroDebugger crashed** and its window became an `MTEngine Crash` dialog,
  which is why every `mcp__retrodebugger__*` call hung past 120 s and queued
  behind `retro_start_platform`. Killing and relaunching the app fixed the app
  but **the MCP server disconnected and could not be reloaded in-session**.
  Diagnose with `Get-Process -Id <pid> | Select MainWindowTitle`.
- Two silent-failure edits: a Python `str.replace` that did not match wrote
  nothing to `whats-next.md` in v0.5.90 and shipped an empty change. **Use the
  Edit tool, which errors on a miss**, not a non-verifying replace.
- Writing a file with `pathlib.write_text()` on Windows encodes cp1252 and
  corrupts UTF-8 em dashes. Always pass `encoding="utf-8"`, and validate with
  `read_bytes().decode("utf-8")` before committing.
</attempted_approaches>

<critical_context>

## Invariants

- **`Commando.sng` byte-exact.** Every output-changing option opt-in;
  `--max-rows` 94 and `--format` gts2 stay the defaults.
- **Bump the version every commit** (`python python/bump_version.py "…"`);
  regenerate `SURVEY.md` (with `--legal-restart --gt2reloc`), `presets.json`
  and `FIDELITY.md` on a **settled** tree, once, from `python/`.
- A new `convert()` option is inert until it is in **three** places: the
  signature, `presets.py`'s `FIXED`, and the emitted `always` block.
  `tests/test_preset_passthrough.py` fails otherwise.
- Stage `hubbard/` paths only, by pathspec.

## The VICE harness (built v0.5.91 — the session's most reusable artefact)

RetroDebugger is unavailable; VICE does the same job over its text monitor.

```
x64sc.exe -remotemonitor -remotemonitoraddress ip4://127.0.0.1:PORT
          -warp -sounddev dummy -console
```

Connect a socket, read until the `(C:$xxxx)` prompt, then `l "file.prg" 0`,
`> ADDR bytes`, `break ADDR`, `g ADDR`, `m a b`, `quit`. Working scripts are in
the scratchpad (`vice_drum.py`, `vice_drum2.py`, `vice_drum3.py`) and the
protocol is also used by `siddetector2/scripts/vice_monitor.py`.

To run a `.sid` player: strip the PSID header (`dataOffset` at `0x06`), prepend
the load address, write `C:\t\bss.prg`, and poke a driver at `$0810`:

```
78 A9 35 85 01 A9 00 AA A8 20 00 B0 20 16 B0 4C 1C 08
SEI / LDA #$35 / STA $01 / LDA #$00 / TAX / TAY / JSR init / loop: JSR play / JMP loop
```

`$35` keeps CHAREN set so the SID stays visible — the ZP `$01` hazard is about
*clearing* it. A tight `JSR play` loop advances the player's counters per call,
which is what the logic keys on, so reachability is faithful; only real raster
timing would need an IRQ driver.

**Audio rendering:** `vsid.exe -console -sounddev wav -soundarg out.wav
-limitcycles N -tune T file.sid`, **no `-warp`**. PAL is 985248 cycles/s;
`-tune` is 1-based.

## What `bend` is, and is not

`bend` = the summed magnitude of siddump's `(+ xxxx)` / `(- xxxx)` lines, ours
over the original's; `slides` is the count of the same lines. **It cannot:**

- tell a pitch bend from a **sample channel** (the nine digi files rewrite a
  voice's frequency every frame; Off_the_Cuff is 99.8% digi);
- compare a **stepped** sweep against a **glided** one — the player lands on
  exact semitones and siddump names those frames, so the player's rise and its
  drum sweep are both nearly invisible to it while ours are fully visible.
  Thrust (43x) and Bump_Set_Spike (11.79x) are both this, not overshoots.

Both limits are in the report's *What this does not say*.

## Verified Goattracker facts (from source)

```
MAX_PATT 208  MAX_PATTROWS 128  MAX_SONGLEN 254  MAX_INSTR 64  MAX_TABLELEN 255
FIRSTNOTE $60 LASTNOTE $BC  REST $BD (no-op)  KEYOFF $BE  KEYON $BF
REPEAT $D0    TRANSDOWN $E0  TRANSUP $F0  LOOPSONG $FF
```
- Instrument record (GTS5, `gsong.c:224-225`): ad, sr, WTBL, PTBL, FTBL,
  **STBL**, **vibdelay**, gatetimer, firstwave. **GTS2 swaps bytes 5 and 6**
  and packs the vibrato (`gsong.c:284-285`).
- The wavetable advances one entry per play **call** (`gplay.c:707`); speed-table
  deltas apply per call (`:748/758`). Values `$01`–`$0F` are delays.
- A wavetable command entry applies **once** (`gplay.c:528+`), it does not set
  `cptr->command`.
- Note-relative speed: left side `>= $80` → speed = semitone interval at
  `lastnote` shifted right by the right byte (`gplay.c:786-792`).
- Per-instrument vibrato: `gplay.c:352-354` + `CMD_DONOTHING` fallthrough at
  `:769-780`.
- greloc.c: restart ≥ songlen rejected (`:244`); `-S` sets a CIA stub (`:1595`)
  and DEFAULTTEMPO = 6×multiplier−1 (`:1143`).
- siddump calls play `seconds × 50` times regardless of the PSID speed field
  (`siddump.c:309/325`).

## Player facts established this session

- **Slide dialects**: Warhawk-style (operand = low half, bit 0 direction) in 25
  files; high-first (operand & `$3F` = high half, `CMP #$BF` direction) in 22;
  none both. 13 files have the fetch but neither consumer and default to
  Warhawk's reading — **an unverified default, worth revisiting**.
- **Vibrato**: instrument record `+5`, bits 3-6 bound, bits 0-2 shift, 56 files,
  no exceptions.
- **Drum**: noise on the note's first frames, sweep for `W−1` after; gated on a
  **single global effect cell** written only at note start.
- **Digi engine**: `$82` = signed 16-bit slide (first operand high), `$83` =
  vibrato in the standard format; instrument stride 16, vibrato at `+5`.
- **cmdtable engine**: command 1 = slide (low, high|dir, delay), unused by both
  tunes; its vibrato is a table-driven LFO.

## Key paths

| | |
|---|---|
| Corpus (95 files) | `C:\Users\mit\claude\c64server\SIDM2\SID\Hubbard_Rob` |
| GoatTracker 2.77 + source | `C:\Users\mit\Downloads\GoatTracker_2.77` |
| `gt2reloc.exe` / `siddump.exe` | `…\GoatTracker_2.77\win32\`, `SIDM2\tools\` |
| VICE 3.9 (`x64sc`, `vsid`) | `C:\Users\mit\Downloads\GTK3VICE-3.9-win64\GTK3VICE-3.9-win64\bin\` |
| RetroDebugger | `C:\Users\mit\Downloads\RetroDebugger-v1.0.0\…\RetroDebugger-notsigned.exe` |
| Short scratch for gt2reloc | `C:\t\` |
| `dis6502.py` | scratchpad; `python dis6502.py <sid> <hex addr> <count>` |

## Concurrency

`/subtask` forks share this working tree. During v0.5.93 a sibling bumped the
version and regenerated artefacts, then reverted — my own bump and regeneration
vanished mid-flight, and its `git checkout --` on `GOATTRACKER.md` discarded my
uncommitted pointer (it restored it verbatim and said so). **Give concurrent
agents their own worktree** (`isolation: "worktree"`), and verify
`git status --porcelain` immediately before staging.
</critical_context>

<current_state>

## Status: all work committed and pushed; tree clean but for crash dumps

- **v0.5.94** on `origin/master` (`cfbc941`).
- **547 tests pass, 3 skipped** from `python/`. (The third skip is
  corpus/`H2G_GT2RELOC`-dependent and varies run to run; 548/2 is the same
  tree.) `Commando.sng` byte-exact.
- Working tree has **only** two untracked `MTEngine-crash-*` files in
  `hubbard/`. Nothing else modified.

## Artefacts

`SURVEY.md`, `presets.json` and `FIDELITY.md` were last regenerated at
**v0.5.92** and are current: the converter has not changed since v0.5.87 —
v0.5.88–.94 touched the harness and documentation only. `FIDELITY.md`'s header
therefore reads `h2g 0.5.92, bea3feb-dirty`, which is correct rather than
stale. **v0.5.93 and v0.5.94 deliberately did not regenerate**, both because
nothing about conversion changed and because a sibling agent was active in the
tree.

Current report: 82 measured rows, mean melody 78%, mean wave 62%, **median
`bend` 0.25x over 63 rows, 18 files bending nothing**.

## Deliverables

| | state |
|---|---|
| per-call rate scaling (v0.5.82) | complete, shipped, in `always` by construction |
| slide dialect + 16-bit index (v0.5.83) | complete, shipped |
| `--vibrato` (v0.5.85) | complete, shipped, in `presets.json`'s `always` |
| digi `$82` slide (v0.5.86) | complete, shipped (small footprint) |
| cmdtable slide (v0.5.87) | complete, shipped, **reaches no corpus file** |
| `bend` dimension | complete after four corrections; limits documented |
| RSID rendering (v0.5.92) | complete, verified end to end |
| **listening pass** | **staged and waiting for a human** |
| `GOATTRACKER-FORKS.md` | complete |

## Open questions

1. **Does the under-rendered drum sound wrong?** Not answerable by any metric
   here — `bend` cannot see the player's stepped sweep. Crazy_Comets is staged
   for exactly this.
2. **Is v0.5.82's multiplier fix audible/correct at the real CIA rate?** No
   number in `FIDELITY.md` can move on it. The VICE harness can now answer it.
3. **The 13 files with the two-byte fetch and neither known slide consumer**
   default to Warhawk's reading with no positive identification. Zoolook
   (0.26x) and Chain_Reaction (0.26x) are among them.
4. Whether to spend the drum's fifth wavetable entry on a longer sweep or an
   attack tick — a trade never measured, and §3 makes the prior evidence
   suspect.
</current_state>
