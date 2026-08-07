<original_task>
Continuation of work on `C:\Users\mit\claude\c64server\hubbard` — **H2G**, a
converter from Rob Hubbard `.sid` files to Goattracker `.sng`. This session
began from a handoff at **v0.5.60** and ran to **v0.5.68**.

The user read the handoff, then drove four waves of concurrent `/subtask`
forks at its open decisions, asking after each wave what to do next:

1. the +14 transpose clamp, wavetable Phase 2, the three residuals;
2. the <50% bucket re-partition, the `$10`–`$80` effect-bit census;
3. the fidelity workdir + instrument count, a duplicate bucket fork that
   stood down, and a re-run of the census item;
4. the call-rate hypothesis (proposed by the main thread, and refuted).

Then: regenerate all three artefacts, update the docs, commit and push.

The serialisation discipline held across all four waves: forks work in
scratchpad copies or stage reconstructed HEAD+own-hunks blobs, one version
bump per commit, everything staged by pathspec, artefacts regenerated exactly
once on a settled tree. Two forks collided (both sent at the instrument
count); the second detected it, committed nothing, and spent its budget
checking the first's result instead — which is how the `detect.py:918`
guard bug and the false `SURVEY.md` paragraph were found.
</original_task>

<work_completed>

## Headline result

| | session start (v0.5.60) | now (v0.5.68) |
|---|---:|---:|
| corpus at defaults | 80/95 | 80/95 (80/83 in reach = 96%) |
| best per-song options | 83/95 | 83/95 |
| files measured | 83 | 82 |
| mean melody similarity | 68% | **78%** |
| excluding the 33 siddump cannot rate | 71% | **85%** (49 files) |
| mean sequence / pitch | — | **76% / 79%** |
| mean waveform agreement | 61% | **62%** |
| plays the same music (95–100%) | 19 | **25** |
| plays something else (<50%) | 18 | **7** |
| noise frames, ours/original | 5680/11641 | 4795/12128 |
| tests | 326 | **397** (+2 skipped) |

`Commando.sid` → `Commando.sng` remains **byte-exact (15193 B)**.

## Commits this session

```
76530c9 v0.5.61  fold the transposes Goattracker's +14 ceiling threw away
8fe026f v0.5.62  read the effect byte's drum and arpeggio only where the player has them
87030aa v0.5.63  read the player's own note frequency table
8f02c06 v0.5.64  trace each file's own default subtune, not subtune 0
6f23063 v0.5.65  the effect byte has eight flags, and two formats
106c1e2 v0.5.66  end the instrument count at the records, not at the array after them
3b13524 v0.5.67  read the instrument table through the index load
        v0.5.68  regenerate the artefacts on the settled tree
```

## v0.5.61 — the transpose clamp, closed

A transpose is a pitch offset applied on both sides of the frequency lookup
(`CLC / ADC transpose,X` in the player; `newnote + trans` at gplay.c:927), so
`T` and `(T mod 12) + 12k` are the same interval. `--fold-transpose` keeps
the remainder (always 0..11) in the orderlist and folds the whole octaves
into the note column of a *copy* of each pattern the step plays.

**Where the notes have no headroom the step keeps its clamp.** A partial fold
is only a different wrong pitch — and for T=24 a *worse* one. Each step is
exactly right or exactly as it was.

Deep_Strike −10@100% → **+0@100%** (melody 78% → 100%); Kings_of_the_Beach_intro,
Rock_Tells_the_Tale and One_on_One go from −21/−21/−9 to +1@100%. Cost: 725
(pattern, octaves) pairs against the 208-pattern limit; no file stops
converting. The previous handoff's list of victims was wrong in both
directions — Powerplay_Hockey and Skate_or_Die_intro were never in this class,
and Deep_Strike was unnamed.

## v0.5.62 — wavetable Phase 2, the gating half

Under `--effects`, bits `$01` (drum) and `$04` (arpeggio) are read only where
`det.effect_drum` / `det.effect_arp` found the block: **159 of 450 drum
records and 544 of 683 arpeggio records** stop getting a fabricated effect.
Where the drum routine *is* present the shape is Warhawk `$1366`'s — attack,
own waveform with the gate released, one step of a 256-units/frame downward
sweep, stop.

**The player's own noise ending is worse to write**: GT latches a gated-off
voice's last waveform until the next note, so it would stand for the whole
rest of the note, while the player simply stops writing `$D404`. 58.1% vs
60.6%. Recorded, not shipped.

## v0.5.63 — the frequency table, and the residuals it dissolved

`sidfile.find_freq_table` places each player's note table against
Goattracker's and returns two numbers that mean **opposite** things:

- a **shift** — the note byte is offset, a converter defect. One file:
  **Skate_or_Die_intro** (`$0000` at entry 0), **melody 5% → 100%**. Applied.
- a **detune** — the whole table is tuned elsewhere, which no Goattracker
  file can express. Four files carry **NTSC** tables (`$010C` where PAL has
  `$0116`; 268/278 is the clock ratio to within 1.3 cents). The notes were
  right and *siddump* was naming the originals a semitone flat, scoring
  matching music at 0%. Corrected in the **harness** (`siddump -c`), not the
  output. Two of the four are header-flagged NTSC and two are not.

A shifted table sits within 7 cents of the semitone grid, an NTSC one 65
cents off it. `I_Ball` also has `$0000` at entry 0 but its entry 1 *is* GT
note 1 — the naive rule would have detuned it. Pinned in a test.

## v0.5.64 — trace the file's own default subtune

The PSID header's `startSong` names the subtune a player picks by default;
seven corpus files set it past 1 and the harness had always traced subtune 0.
Samantha Fox Strip Poker has fourteen subtunes, `startSong` 10, and a
one-note stub at 0 — a correct conversion was being compared against that
stub for the project's whole history.

Samantha_Fox 5% → 92%, Knucklebusters 30% → 85%, Action_Biker 13% → 78%,
Hollywood_or_Bust 49% → 63%; BMX_Kidz's ~13 s of opening rest is now
`window empty` and excluded rather than scored 0%. Mean melody 73% → 77% at
the time. Two fixes fell out of the same cause: `--search-subtunes` centres
on the traced index (Action_Biker went 13% → 3% on the subtune change alone),
and windows where neither side played are excluded.

`start_song` is read for measurement only, pinned by a test that converts a
file with the field altered and requires identical bytes.

## v0.5.65 — the effect byte has eight flags, and two formats

Phase 1 covered `$01`/`$02`/`$04`/`$08` on the assumption the high nibble was
Warhawk's arpeggio interval. Searching for `BIT/BVC` and `LDA/BPL` as well as
`AND #$xx` — without which `$40` and `$80` are invisible — shows all eight
bits are real flags in some player. Sorting the 77 resolvable files by which
reading they use partitions them exactly: **13 read the high nibble as a
number, 41 as four more flags, 23 neither, and zero do both.**

In the second format **bit `$04` is not an arpeggio**: it holds an attack
waveform for a per-instrument number of frames, then drops to the record's
own `+2`. The expired branch loads `instr+2` in all 34 files sharing the
shape. Duration lives in a second 8-byte-per-instrument array parallel to the
records, corroborated from the note-start push chain (last `PHA` = first
`PLA` into the counter the block decrements) in 34 of 34.

**The reading ships; the encoding does not** — writing the attack as a
wavetable prefix moves 18 files for −82 points of wave agreement. A test pins
that `goatwriter` contains no reference to it. This also **retires the
IK+/I_Ball residual**: their `$A0`/`$A4` percussion is this attack waveform,
readable and rejected by measurement.

## v0.5.66 — the instrument count ended in the wrong array

`_bound_instruments` ends the walk at `two_stage_wave - 1`. The sniffer had
been walking straight from the records into the parallel attack array and
counting its rows as instruments — IK+ 30 where 15 are real, Wiz 40/20,
Delta 44/22. Before the bound, 10 files counted over the 51-slot ceiling;
after, **zero**.

**`H2G-CONVERSION-METHOD.md` §4.1 had argued for eleven versions that the
count could not be an over-read**, citing 29 byte-identical records shared by
Bangkok Knights and Thundercats as proof of a shared Hubbard bank. 16 of the
29 are records; 13 are rows of the attack array. The bank is real and it is
16 records — the figure quoted as proof was half player data. Corrected at
the source in both the method doc and `survey.py`'s prose, not just in the
generated output. **No real instrument was ever dropped to that limit.**

Also: `fidelity.py` and `listen.py` shared a fixed workdir with fixed
filenames (`a.sng`, `b.sid`, `o.sid`), so two forks measuring at once
silently corrupted each other — it contaminated one fork's first A/B this
session. Each run now gets its own scratch directory.

And a latent bug at `detect.py:918`: `if not 0 <= off and off + span + 2 <=
len(data):` parses as `(not (0 <= off)) and (...)`, so it rejected only a
negative offset that was *in* range and let an out-of-range one through. Zero
byte differences corpus-wide — genuinely latent, and the commit says so.

## v0.5.67 — the two silent files, which shared one cause

**Phantoms of the Asteroid was a detection blind spot.** Every signature in
the instrument chain fingerprints the *store* into the SID
(`LDA record,X / STA $D40x,Y`). This player reaches the SID through
trampolines (`$E112 LDA $E467,X / JSR $F04E`), matched none of them, wrote
**zero** instruments, and every note named an instrument the `.sng` did not
contain. Fingerprinting the *load* is dialect-independent, because the
index-to-offset arithmetic is the same wherever the bytes go:
`BD ?? ?? 8E ?? ?? 0A 0A 0A AA BD ?? ??`, trailing operand minus two. Present
in 70 corpus files and naming the same base the existing chain already found
in **68** of them, so it is consulted last: **94 of 95 conversions
byte-identical**, and the 95th is Phantoms — `silent` → **melody 53%**. On by
default.

**Delta Mix-E-Load's two dead voices are a missing initial instrument.** The
player keeps a per-voice instrument index and writes it only when a pattern
carries an instrument byte; Mix-E-Load's patterns carry none and `$C535`
holds `03 09 00` — the three records whose ADSR siddump shows the original
playing. Goattracker carries instruments forward the same way (gplay.c:914)
but starts every channel on instrument 1 (gplay.c:223), which this writer
emits as an empty record. 41 of the corpus's 821 voice orderlists begin that
way. `--initial-instrument` copies the pattern and repoints that one
orderlist step rather than patching in place. Mix-E-Load wave **33% → 97%**.

**It is deliberately not in the `always` block.** That array is *mutable
player state* — its image value is the starting instrument only for a rip of
a single tune. `Commodore_64_Music_Examples` has fifteen subtunes and its
array names records whose ADSR does not match what the original plays; the
snapshot caught it mid-tune. Enabling it there takes melody 15% → 19% and
wave 29% → **0%**. Opt-in, with the boundary documented.
</work_completed>

<work_remaining>

## 1. The multiplier is a per-frame rate written into a per-call table

**CLOSED in v0.5.82** (the pulse table's half of it landed earlier, in
v0.5.80). Slides, the drum sweep, the chromatic rise and the attack transient
are each divided by the `-S` multiplier at the point they are encoded. Exactly
the 33 multiplier-2 corpus songs change bytes and none of the 50 multiplier-1
songs do; `FIDELITY.md` is flat by construction and says why. Three residuals
remain and are named in H2G-CONVERSION-METHOD.md § 7.bb: the arpeggio
alternation and the drum's own attack have no free wavetable slot, and the
rise's shift is exact only for power-of-two multipliers (no corpus file asks
for `-S3`). The audible confirmation — RetroDebugger or a listening pass —
has still not been done. The original statement of the defect follows.

**Found while refuting the call-rate hypothesis (see attempted_approaches);
nothing is committed for it.** `multiplier` never appears in `goatwriter.py`
past line 328 — it reaches the tempo path and nothing else. But Goattracker
advances the wavetable one entry per *play call* (gplay.c:707) and applies
speed-table deltas once per *play call* (gplay.c:748/758, inside the
per-call `TICKNEFFECTS`). So in the 33 files that pack at `-S2`:

- the non-drum instrument transient `left = [wave, 0x00, tail, …]` lasts
  2 calls = **1 frame**, where the same encoding gives 2 frames at `-S1`;
- every slide and the drum sweep travel **twice as far per frame** as the
  player's.

The repo states the mismatch in its own words without noticing it —
`goatwriter.py:85-88`: *"The drum block decrements the frequency HIGH byte
once per **frame** … which is exactly 256 units per frame.
`DRUM_SPEED = (0x01, 0x00)`"* — a per-frame rate in a per-call table.

Size: 33 of 83 preset songs pack at ×2, carrying **920 of the converter's
1201 slide-frames (77%)** and **24 of the 45 files with a detected drum
routine**. Two notes for whoever takes it: wavetable values `$01`–`$0F` are
native delays holding the previous waveform for N calls (gcommon.h:56-57),
and the non-drum path's entry 1 is a literal `0x00` placeholder, so
`2 × multiplier − 2` costs no table space and is byte-identical at ×1 — the
drum path has no free slot, all five entries are in use.

**Invisible to the harness by construction** (siddump ignores the speed
field), so RetroDebugger is the only way to confirm it. This is the largest
identified-but-unfixed defect on the list.

## 1b. The slide step saturates an 8-bit column — 39% of the corpus's

**New in v0.5.82, found in the trace taken to check §1.** `patterns.py` packs
a 16-bit player slide step as `min(speed // 4, 0xFF)` in the pattern data
column, and **2189 of the corpus's 5566 portamento parameters (39%, in 15
files) sit on that clamp**: ACE_II, Arcade_Classics, Auf_Wiedersehen_Monty,
Delta, Flash_Gordon, IK_plus, Knucklebusters, Nineteen, Ninja, Pandora,
Sanxion, Shockway_Rider, Thanatos, Trans-Atlantic_Balloon_Challenge and W_A_R.
A clamped parameter is not a slide that is slightly fast, it is a slide whose
speed was never read.

Flash_Gordon is the worked example: its original moves the frequency about
`$0063` a frame and ours `$01FE` — and `$03FC` (what it emitted before §1) is
exactly `0xFF * 4`, so the file was saturating rather than reading 1020.
Whether the underlying read is right at all is a second question that example
does not answer.

A **GTS5 speed table stores the step at full 16 bits** (`build_speed_table`
writes `(hi, lo)`), so the format can carry every one of these — the value
reaches it through the 8-bit column, which is a GTS2 constraint applied to a
GTS5 file. The fix is to keep the raw 16-bit steps beside the patterns and let
the column stay what it becomes anyway, a table index. Unlike §1 this one is
**visible to the harness**: the `slides` column moved on 8 files for a halving,
so an order-of-magnitude correction should move it much further.

## 2. The listening pass — never performed, now eighteen versions overdue

`build/listen/` predates v0.5.49. Regenerate with
`python listen.py <sid_dir> --from-json ../build/fidelity.json` and play four
files. Everything the attack metric is blind to — slides, effects, gate
lengths, tempo feel, waveform, the folded transposes, the new drum shape —
has only ever been checked by disassembly. **It needs a human; an agent can
only stage it.** The workdir collision that made concurrent runs unsafe is
fixed, so staging is now reliable.

## 3. Build the metrics that cannot see what is left

The report measures attacks, pitch, and waveform *class*. It does **not**
measure ADSR, volume, filter, pulse width, or timing — and the converter
actively remaps ADSR. Every remaining defect is concentrated in exactly what
is unmeasured, which is why the report keeps landing flat on real fixes:
**six changes this session were real and invisible** (the digi rest, slides,
effects gating, 544 gated arpeggio records, three of four folded transposes,
the instrument bound at ±0.00 on every decimal).

- **Pulse width** (siddump's `Pul` column) is next and blocks §4's bit-`$08`
  work. Noted in `fidelity.py`, not built.
- **Envelope** is untouched and cheap from the same dumps.

## 4. Wavetable Phase 2 — what is left

- **Bit `$08`'s pulse-width variant.** Selects between a triangle sweep into
  `$D403` and an `ADC`-accumulate of `+6` into the instrument's own `+0`
  written to `$D402`, storing the total **back into the record** — so `+0`
  cannot be read statically in those 21 files. Needs the pulse table's
  two-entries-per-instrument layout changed, and blocks on §3.
- **Bit `$80`** drives a hard-coded voice-3 noise hit plus global
  filter/volume off a global state byte, which no per-instrument wavetable
  can express.
- **Do not re-derive and re-ship the shelved encodings.** The drum's noise
  ending (58.1% vs 60.6%) and the attack-waveform prefix (−82 points across
  18 files) were both measured. Method-doc §7 carries the per-file table.

## 5. Four files still play something else

`Commodore_64_Music_Examples` (12%) and `Dragons_Lair_Part_II` (5%) are
**genuinely scrambled** — both peak at 18–25% at a *different* constant shift
per voice. `Flash_Gordon` (92 of 142 attacks) and `Rasputin` (38 of 330, and
voice 2 absent) are severe under-production with pitches exact — they peak at
`k=0`. `IK_plus` and `I_Ball` are the retired percussion item (§work_completed
v0.5.65); `Delta_Mix-E-Load_loader` scores 10% at presets because
`--initial-instrument` is opt-in and would take it to 97% wave.

Method note worth keeping: the position-aligned modal delta degrades when
either side drops notes, because the alignment slips. A *high* share is
sufficient evidence of a transposition; a *low* share is **not** evidence of
scrambling. Sweep a constant shift k over ±24 and take the difflib ratio at
each — a transposed file peaks sharply away from 0, a scrambled one is flat.

## 6. Measuring the `-S2` group needs a cycle-accurate trace

33 of 82 measured files score below their real fidelity and no rerun fixes
it. They pack correctly with `gt2reloc -S2` (CIA stub, timer A at 100.25 Hz,
verified in the emitted bytes at latch `$2663`), but **siddump ignores the
PSID speed field entirely** (siddump.c:309/325), calling the play routine
`seconds × 50` times regardless. `-S` changes the bytes and not the trace.
Tracing our side for `seconds × multiplier` is not a substitute (helps 2
files, hurts 1). RetroDebugger is the tool and has confirmed two files at
their correct rate.

## 7. Four players have no expressible rate

Mozart, Ninja and Mega Apocalypse run the player *v* of every *v+1* calls
(1.5×, 4×-with-jitter, unknown). Chain_Reaction needs 5.5 calls per row —
22 player calls per note over 4 rows. Chain_Reaction is the tractable one: a
different rows-per-note reaches it exactly (2 rows at tempo 11, or 11 rows at
tempo 2, at `-S1`), so it is a re-gridding decision rather than an
impossibility.

## 8. Smaller items

- **`Kings_of_the_Beach_ingame` plays 138 noise frames where the original
  plays none** — the report's new `!` marker, and the only file flagged.
  Uninvestigated.
- **`listen.py` cannot render an RSID original.** `SID2WAV` is version 1.8
  (1997), predating RSID, and answers `ERROR: Could not determine file
  format`; our own side always renders because gt2reloc writes PSID. **18 of
  the 95 corpus files are RSID** — After_8, Arcade_Classics, BMX_Kidz,
  Chimera, I_Ball, Kings_of_the_Beach_intro, Last_V8, Last_V8_C128_version,
  Mega_Apocalypse, Mr_Meaner, Off_the_Cuff, One_on_One, Powerplay_Hockey,
  Ricochet, Rikky, Rock_Tells_the_Tale, Skate_or_Die_intro, Tarzan. That set
  includes Skate_or_Die_intro (the v0.5.63 shift fix) and all four NTSC
  files, so the one check that covers the unmeasured region structurally
  cannot reach the files this session changed most. `listen.py` does detect
  the failure and says so rather than staging a half pair. VICE 3.9's
  `vsid.exe` is present at
  `C:\Users\mit\Downloads\GTK3VICE-3.9-win64\GTK3VICE-3.9-win64\bin\` and
  handles RSID, but three attempts at `-sounddev wav` produced a 44-byte
  (header-only) file on **both** an RSID and a PSID input, so the invocation
  is wrong, not the format. Worth solving — it would nearly double the
  listenable corpus.
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
  Capacity, not comprehension — splitting the orderlist across subtunes
  would convert them.
</work_remaining>

<attempted_approaches>

## Premises refuted — do not resurrect

From this session:

1. **"The transient fixes were rejected because they were encoded at the
   wrong call rate in the `-S2` files"** — proposed by the main thread and
   refuted. The shelved attack-waveform encoding's losses are **−57 across 9
   multiplier-1 files and −24 across 8 multiplier-2 files**; the five largest
   are all multiplier 1. The mechanism says it could not have been otherwise:
   siddump calls play `seconds × 50` times regardless of the speed field, so
   in the trace every file behaves as multiplier 1, and **a
   multiplier-dependent effect cannot bias a multiplier-blind measurement.**
   The shelved encodings stay shelved for the recorded reason — onset
   alignment, not rate. (It did surface the real defect in §1.)
2. **"The instrument tables over 50 records are genuine"** — the method doc's
   own evidence was half player data (16 of 29 shared records are records).
   No real instrument was ever dropped to the ceiling.
3. **"The <50% bucket is files that play something else"** — five of thirteen
   were the harness reading the wrong music (four traced at subtune 0 where
   the header names another default, one through a window shorter than its
   opening silence). Two are genuinely scrambled.
4. **"A low modal-delta share means the music is scrambled"** — the alignment
   slips whenever either side drops notes, which is exactly the regime that
   bucket is in. Sweep a constant shift instead.
5. **"The `$04` bit is an arpeggio in every player"** — in the 41 files
   reading the high nibble as flags it is an attack waveform with a duration.
6. **"The high nibble of the effect byte is an arpeggio interval"** — true in
   13 files, false in 41, and zero files do both. Two formats.
7. **"IK+/I_Ball share a version-7 orderlist bug"** — the orderlists and
   patterns are fine; it is the `$A0`/`$A4` attack waveform, and the
   identical 83 is because both files carry the same figure.
8. **"The +1 semitone is one residual"** — two defects with opposite fixes.
   A rule keyed on "`$0000` at entry 0" gets `I_Ball` wrong.
9. **"Chain_Reaction's 0.66× is a multiplier error"** — 5.5 player calls per
   row, which no integer tempo expresses.
10. **"Powerplay_Hockey and Skate_or_Die_intro are transpose-clamp victims"**
    — they measure +1@100% before and after.
11. **"Ending the drum on noise, as the player does, will improve the wave
    score"** — 58.1% vs 60.6%. GT latches a gated-off voice's waveform.
12. **"A looser probe will find the drum routine in more files"** — of the 25
    files testing bit `$01` without Warhawk's block, only 2 write noise to
    `$D404` near the test, and neither regresses.

Carried forward (still refuted): the "~7× re-triggers" miscount; `$BD` as a
re-trigger (it is a no-op, gplay.c:908-941); `gatetimer` as a note length (it
is a compare value capped at `tempo`, gplay.c:334); "the fabricated wavetable
invents noise" (misplaced class — both errors at once); "Devils Galop needs a
table-copy reader" (its init writes over its own operands); "GT's gate mask is
sticky" (`firstwave = 0x09` re-opens it, gplay.c:356-363); "the tempo scatter
is per-file variance" (four values); "wiring `-S` will unblock the 33
mis-scored files"; "the slide gap explains the low melody scores" (no
correlation); "instrument +6 is vibrato" (pulse-width sweep); "3 calls per row
is a corpus-wide constant"; "gt2reloc renumbers subtunes" (stubs + tail
truncation); "Delta has a pattern-table undercount" (interleaved repeats).

## Process lessons

- **A metric that cannot see a change is not evidence the change did
  nothing** — six times this session. Say in the doc, next to the fix, which
  metric is blind to it.
- **A measurement that scores correct music at 0% is a harness bug until
  proven otherwise.** Two independent instances this session (NTSC naming,
  subtune 0) accounted for nine files between them.
- **Run the falsification the way round that can fail.** v0.5.66 asked "does
  any file *gain* a dangling reference" as a differential test — the absolute
  check would have failed, because four files dangle regardless.
- **When a doc argues a thing cannot be wrong, check its evidence.** §4.1's
  proof stood for eleven versions and was half player data.
- **When one number has two possible causes, find the discriminant in the
  6502 before choosing** — shift vs detune is 7 cents vs 65 cents, and a
  header flag would have got half of them wrong.
- **A colliding fork is worth more checking the first than duplicating it.**
  That is how the `detect.py:918` guard and the false §4.1 paragraph surfaced.
- **Re-measure a fork's numbers on the settled tree before quoting them** —
  a fork measuring against a pre-v0.5.64 harness saw four files with
  byte-identical output move by up to 87 melody points.
- **When two readings of a table are both plausible, the one under which the
  three voices agree in length is the player's** (Delta v10 proof).
- Fork hygiene: scratchpad trees + unified diffs against a pristine copy;
  reconstructed HEAD+own-hunks blobs for shared files; re-basing onto landed
  siblings and re-verifying before committing; refusing to regenerate
  artefacts from a half-applied tree.
- **Bash here-strings with `->` arrows create stray files.** Multi-line
  commit messages go in a scratchpad file, `git commit -F`.

## Environment gotchas (cumulative)

- `dis6502.py` (never `dis.py`) in `$TMP` — usage:
  `python dis6502.py <sid> <hex addr> <count>`.
- pytest from `python/`; PowerShell scripts need the PowerShell tool.
- gt2reloc: test for the output file, never the exit code; short paths
  (`C:\t\`); bare filenames with cwd set.
- `fidelity.py` / `listen.py` now take a per-run scratch directory — before
  v0.5.66 two concurrent runs silently corrupted each other.
- SIDM2 tools run with cwd = SIDM2 root.
- RetroDebugger: stop/start does not reset; hand-assemble via memory writes;
  it honours CIA timing (siddump does not).
- `siddump -c<clock>` recalibrates note naming — this is what the NTSC fix
  uses. `siddump.c:413` prints `note|0x80`, which makes an abs column look an
  octave off.
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
  ending, the attack-waveform prefix, `--initial-instrument`'s multi-subtune
  boundary).
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
- Transpose $E0..$FE → −16..+14; applied as `newnote + trans` (gplay.c:927),
  which is why folding octaves into the notes is exact.
- Tempo 0/1 = funktempo; fastest steady row = tempo 2 = 3 calls.
- CMD_SETTEMPO value & $7F, ≥$80 = this channel only (gplay.c:494).
- **The wavetable advances one entry per play call** (gplay.c:707) and
  speed-table deltas apply per play call (gplay.c:748/758) — not per frame.
  Values `$01`–`$0F` are native delays holding the previous waveform for N
  calls (gcommon.h:56-57).
- Instruments carry forward per channel (gplay.c:914); every channel starts
  on instrument 1 (gplay.c:223).
- GTS3+ portamento data = 1-based speed-table index (gplay.c:740); GTS2
  loader converts on read (gsong.c:311-321).
- greloc.c: restart ≥ songlen rejected (:244); zero-length voice = subtune
  stub + tail truncation (:200-255, :653, :701-706); `-S` sets a CIA stub
  (:1595) **and** DEFAULTTEMPO = 6×multiplier−1 (:1143); instrument 63's AD
  can override DEFAULTTEMPO (:1141).
- siddump calls play seconds×50 times regardless of PSID speed
  (siddump.c:309/325) — blind to the multiplier.
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
  status_bit6, reject_phantoms, fold_transpose, gt2reloc. **`initial_instrument`
  is deliberately absent** — see v0.5.67.
- `Detection.frames_per_row` ≠ 1 only in the cmdtable dialect.
- `Detection.effect_drum` / `effect_arp` gate the wavetable;
  `effect_pulse_lo` exists, is logged, and nothing consumes it.
- `find_freq_table` returns a **shift** (applied) and a **detune** (reported,
  consumed by `fidelity.py` only) — they mean opposite things.
- The instrument-record walk must stop at `two_stage_wave - 1`; past that
  point it is reading the parallel attack array.
- Opening output in GoatTracker requires gts5 (GTS2 importer overrun).
- The dialect registry: 0/1/3 Warhawk-family, 2 AWM (two-byte transpose
  sub-variant), 4 ACE 2, 5 BoB, 6 Mega Apocalypse, 7 IK+, 8 digi,
  9 Chain Reaction, 10 Delta, plus the cmdtable pattern grammar.
</critical_context>

<current_state>

## Status: all work committed and pushed; tree clean

- **v0.5.68** on `origin/master`,
  `https://github.com/MichaelTroelsen/SIDDetector2.git` (private).
- **397 tests pass, 2 skipped** (from `python/`). `Commando.sng` byte-exact.
- `SURVEY.md`, `presets.json`, `FIDELITY.md` regenerated **once**, on the
  settled tree, after all seven conversion commits landed.

## Open decisions

1. **The per-call/per-frame multiplier defect** (§1) — the largest
   identified-but-unfixed defect, affecting 77% of the converter's slide
   frames. Needs RetroDebugger to confirm; the harness cannot see it.
2. **The listening pass** (§2) — eighteen conversion-changing versions
   unheard. The only item that requires the user rather than an agent.
3. **Pulse-width and envelope metrics** (§3) — six real changes were
   invisible this session; the unmeasured region is where the remaining
   defects live.
4. **The two genuinely scrambled files** (§5).

## The gap, restated

At v0.5.43 the corpus converted and nobody knew whether it played the right
music. At v0.5.60 two metrics existed and the two largest known defects had
been named. Both were fixed this session, and the bucket labelled "plays
something else" went from 18 files to 7.

But the through-line of this session is not the fixes. **Three separate times,
the thing that was wrong turned out to be the measurement or the
documentation rather than the converter**: siddump naming NTSC originals in
the wrong key, the harness tracing subtune 0 where the header named another
default, and a method-doc paragraph whose proof was half player data. Between
them they had misrepresented nine files and one hard limit for eleven
versions or more.

The corollary is uncomfortable and worth carrying: the remaining defects are
concentrated in what is *not* measured — envelope, filter, pulse width,
timing — and the one check that covers all of it has still never been run.
In twenty-five versions of fidelity work, exactly one file has ever been
listened to.
</current_state>
