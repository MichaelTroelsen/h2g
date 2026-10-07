# Measuring a conversion

The survey, the fidelity harness, listening, and the tools around them
(`survey.py`, `fidelity.py`, `listen.py`, `abpage.py`, `instrmap.py`,
`songview.py`, `fidelity_queue.py`). Moved out of `README.md` at v0.5.492;
the wording is unchanged.

## Corpus survey

`python/survey.py` runs the converter over a directory of `.sid` files and writes
a Markdown report recording *why* each file fails, not just that it did:

```sh
cd python
python survey.py <sid_dir> -o ../docs/SURVEY.md      # see --help for all options
```

It accepts the same output-shaping flags as the converter, so a report can be
generated for any combination of settings; the report header records which ones
were used and echoes the exact command that reproduces it.

[`SURVEY.md`](SURVEY.md) is the committed report for the Rob Hubbard corpus and
the single place conversion rates are quoted — it carries the pass/fail count,
the failure breakdown by stage, the detected player-variant spread and per-file
detail, all regenerated from the code. Deliberately **do not** restate those
figures here or in `CLAUDE.md`: they move whenever detection or capacity handling
changes, and a second copy goes stale silently.

"Converted" there means the converter produced a `.sng` without erroring — it
does **not** mean the output is musically correct. That question is
[`FIDELITY.md`](FIDELITY.md)'s, below.

### The subtune census

`SURVEY.md` says which *files* convert. It has never said what became of the
subtunes inside them, and the gap is wide: across the corpus the PSID headers
declare **553** and the converter emits **312**.

```sh
cd python
python survey.py <sid_dir> --subtune-census ../SUBTUNES.md
```

[`SUBTUNES.md`](SUBTUNES.md) is the committed census. It is generated on demand
rather than every commit, like `FIDELITY.md`, and it reads the record
`convert_tracks` fills in as it decides each subtune's fate — not a second pass
re-deriving the same decision from a `Detection`.

Its result is a **negative** one, and that is the useful kind. A PSID header
count is not a promise: the track table has no length field, Hubbard rips
routinely declare more subtunes than the table holds, and reading past the end
yields whatever bytes follow. 167 of the 227 lost subtunes have no voice
pointer that resolves inside the file at all.

The remaining 59 resolve one or two pointers of three, which reads like a queue
of partly recoverable music and is not. The census prints the raw pointers
because the counts cannot settle it — BMX_Kidz's subtune 1 "resolves" on
`$B4FF`, which is subtune 0's own voice 0, and Warhawk's subtune 9 on `$1840`,
seven bytes below the first real orderlist. Their pattern-reference counts are
clean (56 and 86, none dangling) because a garbage pointer reads bytes that
happen to be small, and a small number is a valid pattern index.

So the converter is already right here and `SURVEY.md`'s subtune counts are not
a shortfall to be closed. The one file that really did hide music behind a
readable table hid it behind a second *player* — see [`--engine`](OPTIONS.md#--engine-n-a-file-that-carries-two-players)
and H2G-CONVERSION-METHOD.md § 7.lllll.

## Fidelity — does it play like the original?

`python/fidelity.py` answers the question every other check in this repo
sidesteps. It converts a `.sid`, packs the `.sng` back to a `.sid` with
`gt2reloc` (Goattracker's F9 packer), traces **both** files with `siddump`, and
compares what the two players tell the SID chip to do:

```sh
cd python
python fidelity.py <sid_dir> -t 180 --presets ../presets.json -o ../docs/FIDELITY.md
python fidelity.py --pair original.sid ours.sid        # two files you already have
```

It needs `siddump.exe` and `gt2reloc.exe` (`H2G_SIDDUMP` / `H2G_GT2RELOC`
override the paths) and is otherwise stdlib-only. A serial `-t 180 --sound`
pass over the corpus took 58 minutes with a cold render cache (v0.5.459,
`docs/LESSONS.md`). `--jobs N` measures N songs at once, each in its own
process and private scratch directory; the rows, report and censuses are
written once, in the serial order, so N changes only the wall clock. Each row
records `measure_seconds`, its own convert-pack-trace-render time, which the
listening pages print beside the tune's length.

### The window is a prefix, and that limits what a single run can settle

**Since v0.5.489 `-t` is a floor.** When the length probe finds the original
ending past `-t`, the register columns are traced over that length instead
(the row records `window_seconds`, the header and a notes bullet name each
widened file, and `--baseline` refuses across differing windows);
`--no-window-floor` restores the fixed prefix. Measured on the eight
prefix rows: every one reads `cov` 1.00 with its `output_sha` unchanged
(Food_Feud 0.73 -> 1.00 over 247 s), for +22 s over the eight. Files whose
original ends inside `-t`, or never ends, are unchanged, so the paragraph
below still describes them.

`-t 180` is the window every generated artefact uses since v0.5.459, and it
is **still not long enough to contain the music** -- the census below is the
60 s one that made the case for widening, and widening did not remove the
limit, it reduced it. Measured at v0.5.453 over the 89 files that
score in both windows: exactly **2 of 89** originals end inside 60 seconds. A
dozen more are known prefixes whose originals run to a median of 247 s and a
maximum of 381 s, and the remaining 75 have no measurable ending at all. So on
essentially the whole corpus the report is scoring the first minute of a tune
that keeps going.

That matters more than "the numbers are approximate", because the window's own
contribution is the same size as the effects the preset search selects on.
Comparing `-t 60` against `-t 180` on the *same* conversions, **87 of 89 files
have a scored column move, 81 move by 5 points or more, and 76 by 10 or
more** — median movements of 0.12 for `pphase`, 0.14 for `nrun`, 0.11 for
`tail` and `onset`, with extremes past 1.9 for `bend` and 2.7 for `pspan`.

The two columns that barely move are **`melody` (median 0.005) and `seq`
(0.004)**, which is precisely why this stayed hidden: they are the columns read
first, so a window-sensitive verdict on a register column looks stable when
checked the usual way.

Three concrete verdicts flipped on this in one session. `Mega_Apocalypse` under
`--pitch-seq` is identical on *every* numeric column at 60 s while its
`output_sha` differs, and at 180 s shows a near-exact oscillation fix bought
with 12.7 points of pitch. `BMX_Kidz` under `--regrid` has bit-identical drift
at 60 s and reads −7.81 against +72.18 at 120. And `Flash_Gordon` under
`--pitch-seq` **changes sign**: its `vib` is slightly worse at 60 s and much
better at 180.

The default stays at 60 on **cost**, not because it is sufficient: the report
is already 15m46s with `--sound`, and the option search 8 minutes, so 180 s
means roughly 45 and 24. `presets.py --shard I/N` splits the search. Until that
is paid, the rule in practice is per-song: **before adopting or refusing an
option for one file, re-measure that file at `-t 180`.** All three flips above
were caught that way.

For siddump it prefers `python/tools/siddump-rt/siddump.exe` when that has been
built, because a song packed at `gt2reloc -S2` is traced at half speed without
it. It **refuses** such a song on a binary lacking `-m` rather than return the
half-speed dump, which is indistinguishable from a bad conversion — siddump's
option switch has no `default:` case, so an unknown letter is dropped without a
word. `--calls-per-frame N` overrides the rate; `1` reproduces every number
taken before v0.5.99.

**A row is compared over the music the original has, not over a fixed window**
(v0.5.328). Hubbard's `$FE` track byte means *tune ended*; a Goattracker
orderlist has no way to say that, so `--legal-restart` turns it into a restart
at position 0 — which is what makes the file packable at all — and our
conversion plays the tune again where the original has stopped. Every sequence
column was then charged for a loop the original never plays:
`Geoff_Capes_Strongman_Challenge` read `retrig` **3.21** and `melody` **49%**
over 60 s and reads **1.02** and **100%** over the 17 s this rule gives it;
`Kings_of_the_Beach_ingame` **7.82 / 23% → 1.04 / 98%** over 8 s. Both sat in the
report's *plays something else* bucket on that arithmetic.

The rule is `fidelity.original_ended`, and it is deliberately conservative in
one direction: shortening a window can only remove *our* surplus notes, so it
flatters every column it touches. It is therefore gated on the original
**stopping** — a trailing silence longer than twice that tune's own largest gap
between attacks, and five seconds outright — never on the two sides
disagreeing, and it never shortens below five seconds (a short window is its
own hazard: `BMX_Kidz` opens with thirteen seconds of rest). A rest is not an
ending: `Human_Race`'s 144-frame tail keeps its full-length row. The report
names every row it shortened, with the window used, and
`tests/test_original_ended.py` pins the rule — including the three cases where
it must decline.

Traces set **`$02A6` to 1 (PAL)** since v0.5.110. siddump starts that cell at
0, which is NTSC, and three corpus players branch on it to skip frames in
compensation — tracing without it measures behaviour a PAL C64 never has, and
carried `Phantoms_of_the_Asteroid` as a converter defect for several versions
when its row is simply what its gate says. `--ntsc` reverts. Only four files
read the cell and only they can move; the `-v`-capable build is required for
those four alone.

`--ticks` asks the same question of the **original alone**. `siddump -z` prints
the cycles the play routine burned on each frame; a Hubbard player does
markedly more work on the frame its sequencer steps, so the gaps between those
frames are its row period — no conversion, no packing, no note matching. That
makes it a check on `goatwriter.find_song_speeds` against the player itself,
where `--pace` can only say our row and theirs disagree. It **refuses** rather
than guess: ungated it agreed with `--pace` on 53% of the files both can
measure, and gated on gap regularity it speaks on 31 of 95 and agrees on 18 of
the 18 `--pace` can check. It cannot see a player whose row alternates (3, 3, 2
frames), which is what `--pace` is for.

What it counts is **note attacks** — the notes `siddump` prints bare, which it
does only after a gate rising edge (`siddump.c:376-380`). A note in parentheses
is the same voice moving to another pitch *without* re-triggering, and
`(+ 0034)` is a slide inside one note. That distinction is the whole point: a
plain `grep` for note names over the dump counts all three alike, and mistakes
one vibrato cycle for a re-struck note.

| metric | |
|---|---|
| **melody** | similarity of the attack sequence with consecutive repeats collapsed — the right notes in the right order |
| **seq** | the same, uncollapsed, so a note struck eight times where the original struck it once counts against it |
| **retrig** | our attacks over the original's; 1.0 is right |
| **pitch** | overlap of the distinct pitches played |

Attacks are not all of it. Seven further columns compare the registers
themselves, each frame-by-frame with the last written value carried forward,
because siddump prints a register only when it changes: **wave** (the
waveform-select nibble), **noise** (frames of noise, ours over the
original's), **adsr** (the envelope pair `$D405`/`$D406`), **pul** (how often
the duty cycle moved, ours over the original's), **pspan** (how wide a band
the duty cycle covers, over the original's), **filt** (frames with a voice
routed into the filter and a passband selected, ours over the original's) and
**cut** (how far the cutoff travels, over the original's travel). The three
counted ones are one-sided on purpose: they answer "did we invent this" or
"did we drop it", which no agreement percentage can say.

`cut` and `pspan` are ratios rather than counts because **a sweep taken in
finer steps writes twice as often and goes exactly as far**. `pspan` was added
in v0.5.174 for that case in its purest form: a Goattracker pulse speed is a
signed byte, so a player step of 224 a frame is emitted as 127 twice, and
`pul` moved from 3/236 to 338/236 on `5_Title_Tunes` for a band that came out
*narrower* than the original's. It excludes a width of `$000` on both sides —
Goattracker writes `$D402/$D403` on every frame from the first call where the
player writes them at its first note, and that leading zero otherwise reads as
a spurious jump on all three voices of every file (Commando: 3.96x for a sweep
that covers less). `$000` is 0% duty, so nothing audible is dropped.

**aud** and **loud** are the only two columns in the report that read no SID
register at all. Every other one goes through `siddump`; these two render both
sides to WAV with `sidplayfp` and compare the audio, so they see what a
register trace structurally cannot — timbre, filter movement, envelope shape,
and in `loud`'s case the master-volume nibble, which nothing else here has ever
compared. **aud** is the per-frame agreement of a 64-band log-mel spectrum with
the level removed; **loud** is the agreement of the loudness envelope, and
`--json` carries `loud_ratio`, our overall level over the original's. Both are
absent (`-`) unless the run was taken with `--sound`, and absent rather than
zero when a render fails — an absent dimension recommends nothing.

Two things are deliberately excluded from **aud**, both for the same reason
`pspan` excludes a width of `$000`: frames where both sides are silent, and mel
bands where both sides sit at the floor. The second matters more than it
sounds. A harmonically sparse signal — a sine, or a SID voice — leaves most of
a 64-band spectrum at the floor, so counting those bands as agreement scored
two tones **an octave apart** at 0.90; over the bands that actually sound the
same pair reads 0.45.

**Read `docs/SOUND-CALIBRATION.md` before trusting either column.** It is
generated by `python/sound_calibrate.py`, which measures the floors rather than
typing them. Its checks 2, 3 and 4 score only the first `CHECK_WINDOW_S` = 60 s
of the aligned 180 s render (the alignment is found on the whole render; only
the scoring is cut): `aud` and `loud` are means over frames, so a defect of
fixed length is diluted in proportion to the window it is averaged into, and a
margin that shrinks as the render grows is a fact about the render length,
not the metric. The generated document carries the whole-window figure beside
each prefix one, and its header stamps the version and the verdict — read that
stamp, not this paragraph, for the current state. When the calibration was
first taken, at v0.5.453, it reported **`pass: false`**: a one-frame delay of
either side moved `aud` by 0.034, while the three documented conversion fixes
it was tested against moved it by +0.012, −0.019 and −0.005 — all under that
floor, and two of them the *wrong sign*. The wrong sign is explicable rather
than mysterious: a per-frame agreement falls when a fix unmasks a defect the
old behaviour was hiding, which is exactly what `Human_Race`'s clock fix did to
`melody` (65 → 56%). Whenever the document reads `pass: false`, these are a
coarse guard against gross breakage, not a verdict.

**onset** (instruments whose notes *open* on the original's waveforms). The
column that sees a mechanism emitted one frame out of phase, which two others
read the same register and cannot: `wave` averages per-frame agreement over the
whole window, so a wrong opening frame on a 43-note instrument is a rounding
error against 3000 frames, and `nrun` compares the *lengths* of noise runs and
is position-independent by design, so a run that is right but starts a frame
early scores 100%.

It compares the first four frames from each attack as waveform classes
(`wave`'s own reduction, so the two cannot disagree about what a frame's timbre
is), keyed by the ADSR pair one frame after the attack — `instrmap.py`'s rule,
because the attack frame can still hold a hard restart's envelope. The key is
`$D405/$D406` and the measured value is `$D404`, so the attribution cannot
contain the quantity being attributed, which is the trap `tail` fell into.

**No startup-lag correction, and none is wanted**: each side is read at its own
attack frames, so the packed player's 3–8 frame latency cancels by
construction, exactly as it does for `noise_runs`. The first wiring of this
column passed the lag in anyway and would have manufactured the phase error it
exists to detect.

It reports the *direction*, because a wrong waveform and a right waveform a
frame out have entirely different fixes. Over the corpus that split is
**one-sided: 32 instruments early, 0 late** — which is what a systematic
emitter defect looks like and what noise does not.

**The two per-frame agreements — `wave` and `adsr` — are aligned on the packed
player's startup lag.** gt2reloc's player reaches its first note some 3–8
frames after the original does, and comparing frame *k* to frame *k* charged
that constant to the converter on every file: Commando's `wave` read 65% for a
file whose waveforms agree 92% of the time once aligned, and v0.5.174's drum
fix looked like a 4.6pp regression while taking noise coverage from 49% to 92%.
Corpus-wide the alignment moves mean `wave` 67.0 → 70.2% and mean `adsr`
71.9 → 76.4% — a change to the measure, with no converter change behind it, so
figures either side of v0.5.175 are not comparable.

The lag is **estimated, never fitted**: it is the difference between the two
sides' first attack frames, one number from a defined signal. A shift chosen to
maximise agreement would be a free parameter that can only raise the score. It
was validated against exactly that search over 36 corpus files — it lands on
the fitted optimum for 20 of them and gives a mean `wave` of 77.0% against the
fit's 77.1%, so the search buys a tenth of a point and costs the column its
meaning. Our first attack is taken where its pitch lands
(`fidelity.pitched_attack_frame`; the original's as it stands): a gated real-waveform firstwave
(`no_test_restart`, `real_firstwave_instruments`) opens the gate on GT's init
call at the previous frequency, one frame before the note's pitch, and
anchoring on that rise read the lag one frame short (see
H2G-CONVERSION-METHOD.md, *Estimated, not fitted*). A lag past `MAX_STARTUP_LAG` is not a latency (Chimera measures 438
frames, an opening one side does not have) and is clamped and reported rather
than applied. `noise`, `pul`, `pspan`, `filt` and `cut` are one-sided counts or
travels over each side's own window, so they are shift-invariant and are taken
before the alignment.

`FIDELITY.md`'s own legend defines each, a *Filter* section there carries both
sides' raw figures, and *What this run compared* names the registers no column
reads.

[`FIDELITY.md`](FIDELITY.md) is the committed report, and the single place
fidelity figures are quoted — as with `SURVEY.md`, do not restate its numbers
elsewhere. Regenerate it after any commit that changes conversion.

**Which subtune gets traced.** One per file, and it is the one the PSID
header's `startSong` field names — the subtune a player selects when the user
selects none — not subtune 0. Seven corpus files set it past 1, and for those,
subtune 0 is not the tune: *Samantha Fox Strip Poker* has fourteen subtunes,
`startSong` 10, and a one-note stub at 0. Tracing that stub scored a correct
conversion at 5%; its own default subtune scores 89%. `-a N` forces a
particular one, `-a auto` (the default) reads the header.

Our subtune numbering does not have to line up with the original's — a subtune
whose orderlist exceeds Goattracker's limit costs itself and shifts every later
one down — so `--search-subtunes` tries a window of ours around the traced
index and keeps the best match. The default window is 3, one either side, which
is what a single dropped subtune can displace. That window moves exactly two
corpus files and widening it moves none, so it identifies the counterpart
rather than trawling for a flattering score; the report names the files it
moved.

That option varies **our** index and holds the original's at its `startSong`,
which fixes a displacement on our side and nothing else. It cannot fix a
displacement on the original's side, and two corpus files have one: their
`.sid` carries an init wrapper that renumbers the subtune before the player
sees it. *Dragon's Lair Part II* (`init $AF00`) sends PSID subtune 0 to song
9, 1 to song 7 and 9 to song 8; *Rasputin* (`init $CFB5`) sends 0 and 1 to a
different entry point altogether and maps n to song n-2 above that. No window
size reaches those, because the number that moved is the one the search holds
fixed. `--diagnose` is what finds them.

### Diagnosing one file

```sh
python fidelity.py <one.sid> --diagnose -t 10
```

One file, explained instead of scored. It prints, in the order the questions
have to be asked in:

* **the subtune correspondence matrix** — melody % for every one of the
  original's subtunes against every one of ours, with the traced row marked,
  followed by the correspondence stated in words. Until this is settled, every
  other number about the file may be comparing two different pieces of music,
  and for three of the four files the report used to file under *plays
  something else* that is exactly what it was doing. Dragon's Lair Part II
  scores 7% on the diagonal and **94%, 98% and 97%** at its real counterparts.
* **a per-voice cause** for the traced pairing, and again at the best
  counterpart when that is a different subtune. Each voice comes back as one
  of: *matches*, *silent in both*, *absent*, *invented*, *transposed k
  semitones*, *under-produced*, *over-produced*, or *different music*. The
  transposition test is a constant-shift sweep over ±24 semitones taking the
  sequence ratio at each — robust where a position-aligned modal delta is not,
  because the alignment slips as soon as either side drops a note, which is
  the regime every low-scoring file is in. A peak must beat the unshifted
  ratio by a margin *and* be worth something absolutely, so unrelated music
  comes back as unrelated rather than as a transposition that is not there.

The shift is signed as **ours against the original's**: `-7` means we play the
tune a fifth low, not that adding seven would fix it.

It writes no report and takes no `-o`/`--json`/`--baseline`; the output is an
argument about one file, not a row.

### Timing one file — `--pace`

```sh
python fidelity.py <one.sid> --pace -t 30
```

Every column of the report is a *what*, never a *when*. `melody` is a
sequence ratio over a fixed window, so it says whether the same notes arrive
in the same order and not whether they arrive at the same time — and the two
errors are not symmetric there. A conversion playing **too fast** reaches past
the end of the window and difflib is charged for the surplus; one playing
**too slow** returns a prefix. So a score can prefer the wrong call rate, and
in v0.5.99 it did: 17 files scored better traced at 50 Hz, the report called
it "a factor of two out", and timing them showed **32 of those 33 are closest
to the original's speed at the rate they are packed for**, with errors between
1% and 33%.

`--pace` measures it directly. It pairs notes with difflib (never by index —
index alignment is meaningful only where the sequences already agree, which is
never true of a file whose speed is in question), takes the ratio of each
consecutive gap, and reports:

* **the median ratio**, not the least-squares fit. A few very long gaps — a
  voice resting through a section — dominate a fit: on ACE II it comes out
  0.727 where the median of the same ratios is 1.509, disagreeing about which
  side is even faster. The fit is printed beside it because the two parting
  company is itself a sign the material has diverged.
* **the interquartile range**. Tight means a row of the wrong length, which
  compresses every gap alike. Spread means the pacing is *irregular* — a gate
  whose interval alternates (ACE II runs 5 frames then 6), or material dropped
  often enough to move a quartile. It is deliberately blind to a single
  omission: one dropped section leaves the quartiles where they were and the
  median still correctly reports the row length as right.
* **the original's row in frames**, derived by dividing our row length by that
  ratio. It comes out the same whichever call rate it is taken at, which is
  what makes it worth printing over a ratio — and it is directly comparable
  with what `goatwriter.find_song_speeds` read out of the player.

That last number is the one that found something. Across the corpus the
speed gate is **under-read**, in both multiplier groups: where it says 2 the
measured row is 2.5–3.0 (Tarzan, Delta, ACE II, Deep Strike, Spellbound,
Chain Reaction), where it says 3 it is 3.5–4.5 (Lightforce, Thanatos,
Pygmies Revenge, Las Vegas Video Poker), where it says 4 it is 4.5–5.33
(Mr Meaner, Human Race), and Rock Tells the Tale reads 5 and plays 6. It is
right for most files — 26 of 43 at multiplier 1 and 10 of 32 at multiplier 2
are within 5% — and where it is wrong the error is a tune-specific factor
between 1.1 and 1.5, never 2. Our own row length is not in question: Ricochet's
gaps land on exactly 8 and 16 frames, so Goattracker honours the tempo as
written.

**That finding is closed.** The mechanism is the counter above the gate, and
[`--skip-gate`](OPTIONS.md#--skip-gate-the-row-length-the-gate-alone-under-reads)
(v0.5.119, on via `presets.json`) reads it: every file named above as evidence
of the under-read — Tarzan, Delta, ACE II, Deep Strike, Lightforce, Thanatos,
Pygmies Revenge, Human Race — now measures 0% out, packed exactly via the `-S`
multiplier. As recorded in CLAUDE.md at v0.5.248: of 63 timed files, **47 exact
and 50 within 2%**. The paragraph above is kept because it is how the mechanism
was found — a number measured before anything in the players explained it.

A short trace is its own hazard in the same family. `BMX_Kidz.sid` opens with
about thirteen seconds of rest, so at `-t 10` neither side has played a note
and the file scored 0% — at `-t 60` it scores 95%. Rows where **both** sides
are empty are now reported as *window empty* and left out of the averages
instead of being scored as a failed conversion.

`siddump` names a note from the SID frequency register, so both sides have to
be read on the same tuning or the comparison is measuring a key change. Four
corpus files (Kings of the Beach intro, One on One, Powerplay Hockey, Rock
Tells the Tale) carry frequency tables computed for the **NTSC** C64's faster
clock, which puts every register value 0.647 semitones below the PAL
equivalent — near enough a whole semitone that `siddump` names the original in
a different key and scores four files that play the right notes at 0%. The
harness reads each player's own frequency table (`sidfile.find_freq_table`) and
recalibrates the *original's* dump to it with `siddump -c`; ours is always
Goattracker-tuned, so nothing on our side moves. A row that needed it says so.
This is a naming correction, not an allowance: a table whose *index* is shifted
rather than its tuning is a converter defect and is fixed in the converter.

#### `drift` — the report's first timing column

Every other column compares *what* is played at aligned frames. None of them
can see two copies of the right music parting company, and this report said so
in its own "What this does not say" for its whole life. `drift` is that gap
closed, in one respect: the accumulated phase error between the two sides, in
frames per 1000.

It is a Theil–Sen fit of `ours[k] − orig[k]` against `orig[k]` over
difflib-matched onsets, per voice, over the voices whose match is thick enough
to be the same music. Negative is early. The slope is the drift; **the
intercept is the startup lag**, so unlike every frame-aligned column above it
needs no lag correction — the lag falls out of the fit rather than having to be
estimated and subtracted.

`0.0` and `-` mean different things and both are common. Zero is a measurement:
45 files hold the original's timing exactly. A dash is one of two refusals —
too little matched material to fit a line, or a fit that explains nothing.

**The second refusal is what makes the column trustworthy.** A rate of
divergence is only a reading if the divergence is a *line*. The first
regeneration printed a corpus-worst `+1151` for Knucklebusters, derived from
one voice whose offsets scattered 82 frames about the fit, and `0.0` for Rock
Tells the Tale at a scatter of 93. Both are two sides wandering. The bound is
the scatter as a share of the traced window, capped at 1% — about 30 frames in
a 3000-frame trace, past which the two copies are not in a stable phase
relationship at all. The corpus agrees without being asked: 90% of files sit
under 0.02%, the genuine large drifts (Rasputin 0.33%, Spellbound 0.67%) well
inside it, and the two artefacts at 3.1% and 5.2%. A refused row keeps its
diagnostics and says why.

Corpus: **46 of 79 files hold the original's timing exactly**; the other 34
part company at a median 12.3 frames per 1000. On 17 of them the figure is
exactly `−1/(skip + 1)` — the outer gate's skipped call, which
`goatwriter.effective_frames` corrects when the corrected row can be packed
(Delta's 5/2 at `-S2`) and declines when it cannot, because 3 × 113/112 wants
339 calls at `-S112`.

What it cannot do: separate *why*. A row a fraction too short and a row of the
right length played from the wrong place read alike. It is a rate of
divergence, not a tempo — `--pace` scores the row length, and `--audio` and
`--register` settle the rest.

#### Drift — the error `--pace` cannot see

`--pace` compares one gap to one gap. That is exactly right for a row of the
wrong *length*, and structurally unable to see a row that is a **fraction** of
a frame wrong: a Goattracker row is a whole number of play calls, so a
sub-frame error lands as zero on most gaps and one whole frame on the
occasional one. Powerplay Hockey reads `median 1.000, IQR 0.980–1.000 over 348
gaps` while its notes arrive 24 frames early across the window. Both numbers
are right about what they measure.

So `--pace` also prints a `drift` line, which integrates instead of averaging —
a Theil–Sen fit of the *offset* between difflib-matched onsets against elapsed
time, per voice, over the voices whose match is thick enough to be reading the
same music. The slope is the drift; the intercept is the startup lag, so the
lag falls out of the fit rather than having to be estimated and subtracted.
`MAD` beside it says whether the offset is accumulating (small — a straight
line) or merely wandering (large).

Measured at each file's packed rate, **37 corpus files drift by exactly zero
and 29 drift.** Where `--pace` can also see the error the two agree to three
figures — and they agree on its *least-squares fit* rather than its median,
which is independent support for the "read the fit, not the median" rule
above.

The group `--pace` calls correct has an exact cause: **`drift = −1 / (skip +
1)`**, where `skip` is the outer gate — the counter that makes the player miss
one call in `skip + 1`.

| skip | true row | emitted | predicted | measured | files |
|---:|---:|---:|---:|---:|---|
| 108 | 3.0278 | 3 | −9.174 | **−9.17** | Sanxion, Sigma Seven |
| 112 | 3.0268 | 3 | −8.850 | **−8.85** | IK+, Nineteen, Bangkok Knights, Pandora, I_Ball |
| 127 | 2.0157 | 2 | −7.813 | **−7.81** | Ricochet, Star Paws, Wiz, Nemesis, BMX Kidz … |

`goatwriter.effective_frames` already corrects a row for that skip **when the
corrected value can be packed** — Delta's 5/2 ships at `-S2`, Thrust's 10/3 at
`-S3`, and both read 0.00 — and falls back to the raw gate when it cannot,
because `3 × 113/112` wants 339 calls at `-S112`. The drift is exactly the
correction that was declined, so this puts a number on a known limitation
rather than reporting a new defect. Its honest fix is re-gridding the rows,
not a tempo.

Scale: 0.8–0.9% on seventeen files — about 25 frames, half a second, of
accumulated lead over a 60-second window — and 8–25% on the eight files
`--pace` already flagged, of which International Karate (−90.91, ≈9% fast) is
the worst that still converts cleanly.

### What a run says it compared

Every report ends with a **What this run compared** section, generated from the
rows rather than written by hand: each dimension, the number of files it was
actually computed on, and the SID registers it is derived from. Underneath it
are the registers *no* dimension in that run reads. When the section was built
that was five of the seven — `$D402/$D403` (pulse width), `$D405/$D406`
(envelope), `$D415/$D416`, `$D417` and `$D418` (filter and volume) — and
v0.5.78's `adsr`, `pul`, `filt` and `cut` columns are those five becoming
dimensions, so a full run now lists none. A run that loses a dimension still
lists its registers, which is the point of generating the section rather than
writing it. Register coverage is not total coverage: note length, tempo,
master volume and anything outside the traced window are listed beside it as
unseen, and none of them is a register nobody reads.

That list is the report stating its own reach. A change confined to it cannot
move a single number here whatever it does to the sound, so a flat table is not
evidence the change did nothing. This has been the most repeated misreading in
the project's history and it was previously prevented only by authors
remembering to write the caveat.

### `--vice` (the register dimensions at 312 samples a frame)

siddump reads the SID **once per frame**, so a value written and overwritten
inside a frame is not in its trace, and on a multiplier-`m` file the `m - 1`
intermediate play calls leave no mark. `--vice` computes `wave`, `adsr`,
`pul`, `pspan`, `filt` and `cut` from VICE's `dump` sound device instead, which writes
the whole chip state on **every rasterline** — 312 samples a PAL frame. Both
sides are traced that way; tracing only ours would trade one bias for another.

```sh
python fidelity.py <sid_dir> -t 10 --presets ../presets.json --vice
python fidelity.py <file> --vice --vice-reduce last   # what siddump reports
```

**The reduction back to a frame is forced, and it was measured rather than
chosen.** The two sides write at different rasterlines within the frame — an
original's player near the top of the screen, our packed file wherever
`gt2reloc`'s CIA stub lands — so a rasterline-against-rasterline comparison
would report that offset. Shifting one side by an inaudible 0–48 rasterlines
moves each candidate rule by:

| rule | mean sd | worst range | |
|---|---:|---:|---|
| `last` | 0.18 | 2.64 pp | what siddump reports — samples one instant, so a write crossing the frame edge flips it |
| `any` | 0.09 | 1.67 pp | disqualified: reads Deep_Strike at 98.8% where every other rule reads ~75% |
| `majority` | 0.02 | 0.09 pp | stable, but a hard vote |
| **`overlap`** | **0.02** | **0.13 pp** | stable and graded — **the default** |

So the rule the report has always used is the least stable of the four. The
counting dimensions still take the duration-weighted majority, because a count
needs one definite value per frame.

**Shared silence leaves both numerator and denominator.** `wave_compare` drops
a frame both sides spend silent so that a silent voice cannot inflate the
score; at 312 samples a frame the graded form of that rule is to remove the
*overlapping silent share*, `min(share_a(0), share_b(0))`. v0.5.131 removed
the frame only when both whole histograms were silent, which scored a frame
one side flickered through as a full agreement — fixed in v0.5.133. See
H2G-CONVERSION-METHOD.md § 7.nn.

Not the default: two emulator runs a row, at about 1.3x real time each. `vsid`
is found at `--vice-exe` or `H2G_VSID`; a row whose trace fails is marked
`vice_failed` rather than quietly falling back to the coarser one.

### The onset census — `--census`

```sh
python fidelity.py <sid_dir> -t 180 --presets ../presets.json --census ../build/CENSUS.md
```

`onset` reports a rate, and a rate says how much is wrong without saying what
to do about it. `--census` classifies the same comparison — the same two
traces, the same modal reduction, so its `match` count *is* the column's
numerator — by the **kind** of each disagreement, and groups the largest kind
by the source record's effect byte.

| kind | what it means | what to do |
|---|---|---|
| `match` | the four opening frames agree | — |
| `phase` | the original's sequence, one frame out | move the emitter, not its waveforms (§ 7.www) |
| `short` | our note stops selecting a waveform inside the window | a note-*length* difference — `hold` measures it and `--hold-census` classifies it |
| `flat` | we hold one waveform where the original moves | a mechanism we do not render — read the player |
| `invented` | we move where the original holds | emitter quality |
| `partial` / `wrong` | some or no frames agree | emitter quality |

The `flat` group is the work list, and grouping it by the record's `+7` is what
makes it one: the first run of this turned "18% disagree" into `$01 x19,
$04 x11, $80 x6, $0A x6`, and `$0A` was a decoded and emitted mechanism (21
files, 98 records) within the same session. A group whose bit is already
implemented points at *option selection*; one whose bit is not points at the
player. The effect byte comes from the instrument's own name in the converted
`.sng` — the converter's provenance stamp `NN:b5-b6-b7` — so no second
detection pass is involved.

The document goes to the path given and nothing else about the run changes; it
is written beside `-o`/`--json` rather than inside the report, because a report
says how the corpus scores and this says which file to open next.

### The hold census — `--hold-census`

```sh
python fidelity.py <sid_dir> -t 180 --presets ../presets.json --hold-census ../build/HOLDCENSUS.md
```

The same idea for the `hold` column: the same two traces and the same modal
reduction, so its `match` count *is* the column's numerator, with each
instrument classified by **why** its modal note length differs.

The distinction the column itself cannot draw is whether the note is shorter or
its *slot* is. `sound_runs` measures the frames a note keeps a waveform selected
within its own slot, so a note that fills the room it is given is not a
note-length defect at all — what differs is when the next note arrives, which is
a timing question.

| kind | what it means | what to do |
|---|---|---|
| `match` | the same number of frames | — |
| `fetch` | one frame short, equal slot | Goattracker's next-note fetch; `--no-test-restart` removes it |
| `slot` | the length difference *is* the slot's | a timing question — read `--pace` and `retrig` |
| `thin` | fewer than four notes a side | a mode over one note is that note |
| `sparse` | one side plays twice the notes | two modes over different music |
| `gap` | equal total frames, one side holed | the reduction stops at the first hole, not a real difference |
| `short` / `long` | equal slot, equal population, wrong length | the residue that is actually about note length |

Corpus at v0.5.259, 433 instruments across 81 files: `fetch` 211, `slot` 117,
`match` 92, and a residue of nine — `short` 3 and `long` 6. Five of those nine
are one mechanism, a terminating `$00`/`$08` wavetable step the emitters do not
write. See H2G-CONVERSION-METHOD.md § 7.xxxx.

### The gate census — `--gate-census`

```sh
python fidelity.py <sid_dir> -t 180 --presets ../presets.json --gate-census ../build/GATECENSUS.md
```

The same idea for `gate`. One record per release the **original** makes, on
the frames it makes it, classified by what the conversion did there.

| kind | what it means | what to do |
|---|---|---|
| `matched` | we release for at least half of it | — |
| `short` | we release, but cut it off early | we re-attack too soon; the next-note fetch, from the other side |
| `held` | we never release at all | the queue: the original rests and we sustain through it |
| `retrigger` | one frame long | the edge at an untied note's end; mostly invisible at one sample a frame |

Corpus at v0.5.274, 46996 releases across 83 files: `matched` 51.4%, `held`
23.7%, `short` 22.9%, `retrigger` 2.0%. **Half of every release the originals
make, we already make** — which reframes the 44% mean overlap, since a
release made one frame late costs a frame-overlap at both ends.

`held` has no tail left: its longest run in the corpus is 29 frames, and
11145 runs over 36851 frames average **3.3**. Those are not rests we failed
to read — v0.5.273 reads them — but notes ending a few frames before the next
one starts, which is the axis `hold` already measures from the other side.
See H2G-CONVERSION-METHOD.md § 7.ggggg.

**`fetch` is invisible above `-S3`**, and the report says so in its own
per-rate table: the deficit is a fixed number of play *calls*, and siddump
samples once a frame, so a low count up there is the trace's resolution rather
than the converter's. The same blindness `hold` itself carries.

The document goes to the path given and nothing else about the run changes, as
with `--census`.

### A/B against a previous run

```sh
python fidelity.py <sid_dir> -t 10 --presets ../presets.json --json before.json
# ... change something ...
python fidelity.py <sid_dir> -t 10 --presets ../presets.json \
    --baseline before.json --ab-output ../build/AB.md
```

`--baseline` compares a saved `--json` run against the one just taken and
prints, sorted by the largest movement on any one dimension, which files moved
and by how much. It is deliberately not only a delta table: each row also
carries a hash of the converter's own output, which is what separates the two
readings of a table that did not move.

| verdict | what it means |
|---|---|
| **no dimension this report measures can see this change** | the converted bytes changed and no number moved — the change is real and landed in a register named above |
| **this change reaches nothing** | the converted bytes are identical too, which is the shape of `--slides` (dead for four versions) and `--filter` (wired into `convert()` and README and into neither the presets nor the harness) |
| **every movement is below the precision the report prints** | the numbers moved and `FIDELITY.md` would have looked identical |
| *n* **files move the printed report** | plus, always, how many of the files whose output changed moved *nothing* |

A comparison **refuses** (exit 2) when the two runs were traced at different
`-t` seconds or different subtunes: those are numbers about different music. A
difference in *conversion options* is not refused — an option A/B is what the
mode is mostly for — but it is named at the head of the output as the change
under test, which is the same protection against presets silently drifting
between two runs.

`--label` now defaults to `git rev-parse --short HEAD` plus `-dirty` when this
project's files are modified, and is recorded in every row. A measurement taken
from a half-applied tree has cost this repo two re-runs and the report had no
way to say it happened.

Two further comparisons are wired up behind flags, both shelling out to
[SIDM2](SIDM2-FIDELITY-TESTER.md)'s tools and inheriting their dependencies:
`--audio` (onset-aligned audio, tolerates our tempo offset) and `--register`
(frame-exact register comparison, only meaningful once tempo is reconciled).

**`--sound` is not `--audio`, and the two are easy to confuse.** `--audio`
shells out to SIDM2 and scores onset *jitter*, tolerating a tempo offset;
`--sound` is this repo's own, needs only `sidplayfp`, and adds the **aud** and
**loud** columns described above — the rendered *timbre* and *level*, not the
timing. Renders are cached under `build/audio/` keyed on the content of the
`.sid` being rendered, so re-running an unchanged conversion re-renders
nothing; the first corpus pass renders both sides of every file. A failed
render names its side in `sound_failed` rather than scoring a silent WAV
against music. Since v0.5.492 every render passes sidplayfp `--delay=0`
(`listen.SIDPLAYFP_POWER_ON_DELAY`), so two renders of the same bytes
reproduce to the calibration's grid floor; a WAV cached before that version
was rendered with a random power-on delay and is still served from the
cache, because the key is the `.sid` bytes, not the command line.

Because the key is the *content*, every converter change leaves the previous
`ours.*` render behind for good (measured at v0.5.489: 256 superseded renders,
2.9 GB, against 89 live ones). `python sound.py --prune <sid_dir> --quarantine
DIR --apply` moves them out: a render is live when its key is in
`build/fidelity.json`'s rows, is one of the calibration's historical builds
(rebuilt through `convert_at` and packed, since the calibration JSON does not
record most of them), or is a recoverable approved build. It **refuses** while
a calibration build cannot be rebuilt (its render would cost a cold re-render)
and only **reports** an unrecoverable approved build (no reader can construct
its key, so its render was unreachable already). It never deletes -- without
`--apply` it lists.

A row can also say **not comparable**. `gt2reloc` exports only the subtunes
whose three voices all have nonzero length, and a subtune that fails that test
keeps its index and comes back as an entry that plays nothing — so comparing
against it measures our converter against silence. Those rows are marked and
left out of the averages rather than scored as bad conversions; the report
lists every affected file, including the subtunes that are silently dropped off
the end of the list. See [`SNG2SID-FIDELITY.md`](SNG2SID-FIDELITY.md) §7.

### Listening

`python/listen.py` stages the part no measurement covers:

```sh
cd python
python fidelity.py <sid_dir> -t 180 --presets ../presets.json -o ../docs/FIDELITY.md \
    --json ../build/fidelity.json
python listen.py <sid_dir> --from-json ../build/fidelity.json -t 30
```

It picks one tune from each band of `FIDELITY.md` — the median of the band, not
the extreme — renders the original and our packed conversion to WAV with the
same emulator at the same settings, and writes `build/listen/LISTENING.md`
saying what the measurement predicts for each. Needs one of the three
renderers below; output is gitignored, because it is for ears rather than for
review.

**Each tune is staged at its own subtune** -- `-a/--subtune` defaults to
`auto`, the PSID header's own `startSong`, the same rule `fidelity.py` traces
by. Seven corpus files name something other than 0 there, and Samantha Fox
Strip Poker's subtune 0 is a one-note stub: staging that would ask a listener
about music no measurement in the repo ever compared. Where a `--from-json`
row recorded a `matched_subtune` -- our numbering shifts when `gt2reloc` drops
a subtune -- our side follows it, so the pair is the same piece of music at two
different indices. Pass a number to force one for every file.

`LISTENING.md`'s header states the renderer and the subtune **from what the run
did**, not from a constant. It named `SID2WAV` for four versions after the
renderer moved to `sidplayfp`, which is the one claim in that document a
listener has to be able to trust -- the whole premise is that a difference
heard is a difference in the music and not in the emulator. A pass that fell
back for some pairs names every engine it used and says the comparison holds
within a pair rather than across the pass. Under `--shard` it states the same
two facts as policy rather than as totals: `--merge-notes` keeps the first
part's header, so a count taken over one shard would be published as a count
over the whole pass.

**The renderer is `sidplayfp`, libsidplayfp's own frontend** (v0.5.308).
`SID2WAV` is a 1997 build of that same lineage, and being twenty-eight years
old costs three things: it refuses every RSID (18 of the 95 corpus files,
including all four NTSC ones and `Skate_or_Die_intro`), it **fades the last
seconds out**, which quietly corrupts the end of any comparison, and it exposes
no chip model — Hubbard is 6581-era and the difference is audible. `sidplayfp`
renders the whole corpus with one engine, at exactly the length asked for, with
`-fo0` for no fade.

**RSID files need the C64 ROMs**, and the failure is silent-looking: without a
KERNAL, libsidplayfp runs the tune to an illegal instruction having already
written a 44-byte header, which reads as a tune that renders silence. Point
`Kernal Rom` / `Basic Rom` / `Chargen Rom` in `sidplayfp.ini` at VICE's `C64/`
directory (`kernal-901227-03.bin`, `basic-901226-01.bin`,
`chargen-901225-01.bin`). `listen.py` checks the output size and falls back
rather than staging an empty pair.

`SID2WAV` and VICE's `vsid` remain behind it, so a machine with either can
still stage a pass. **The choice is made once per pair, never per side**
(`pick_renderer`): two emulations differ in level and filter enough to colour a
listening judgement, so a pair split across two engines is worse than one that
fails to render. If you do fall back to `vsid`, note it is driven by
`-limitcycles` and overshot a 20 s request by 1.76 s in testing — its output is
not the length you asked for.

The reason it exists: `fidelity.py` compares note attacks and nothing else. It
cannot hear an envelope, a filter, a tempo or a timbre, and it scored *zero*
change for a correctness fix that rewrote 66 rows of one file (v0.5.46). Its
number is a floor on how wrong a conversion is, never a ceiling. Each staged
entry states what the numbers predict precisely so that a listen can contradict
them — a contradiction is the useful outcome.

#### `abpage.py` — A/B the staged pairs in a browser

Playing two WAVs in a media player is not an A/B: the switch costs a click and
a seek, and by the time the other file starts you are comparing a sound to a
memory of one. `python/abpage.py` builds a page per staged tune that plays
**both renders at once and swaps which one is audible**, so a switch is gapless
and lands on the same instant of the music.

```sh
cd python
# stage the pairs -- ~95 min for the corpus at 120 s, or ~16 across six shards
python listen.py <sid_dir> --all -t 120 --presets ../presets.json

# or sharded, one process per shard, then join their notes
python listen.py <sid_dir> --all -t 120 --presets ../presets.json --shard 0/6
python listen.py --merge-notes

python abpage.py                    # one page per tune + build/listen/index.html
python abpage.py --embed W_A_R      # one self-contained page, WAVs inlined
python abpage.py --instrmap <sid_dir>   # ...and refresh the instrument map first
```

Tunes on hold (`python/hold.py`, since v0.5.493 the twelve DIGI files) keep
their pages, but the index lists them in a separate *On hold* card below the
staged tunes, each badged, and the header counts them apart, so they are
never read as awaiting a verdict. See CLAUDE.md § On hold.

`--instrmap` regenerates `build/instrmap.json` for the **staged** tunes before
building, and each page then carries an *Instrument map* card at the bottom
(see [`instrmap.py`](#the-instrument-map--instrmappy)). Scoped to what is
staged rather than to the corpus, because the tool traces two emulations a
song — that is what makes it affordable inside a listening build at all.
Without the flag the pages reuse whatever `build/instrmap.json` already holds,
and omit the card entirely if there is none; the build prints which staged
tunes had no map rather than leaving a silently absent card, since "nothing to
report" and "never measured" look identical on the page.

Each source button also carries the **render time** of the WAV behind it. A
stale pair plays perfectly and sounds subtly wrong, and the first suspicion
falls on the converter rather than on the file's age — which has already cost
this project one wrong diagnosis. It is hidden under blind mode, where two
differing timestamps would otherwise say which side is which.

In the *Both sides, drawn* card, the legend keys (`original`, `H2G`,
`|difference|`) are **buttons**: click one to hide that trace. The two bands
are drawn over each other at 62% alpha, so where they agree neither is legible
on its own. The `mean |Δ|` figure keeps counting hidden traces — it is a
property of the two renders, not of what is currently on screen.

**A sharded pass writes `LISTENING.part<I>.md`, not `LISTENING.md`.** Every run
writes the whole notes document, so shards sharing an output directory would
leave only the last one's -- and `abpage.py` reads that file for each tune's
"what to listen for", so the loss is silent and reads as tunes that were never
staged. `--merge-notes` joins the parts and folds in whatever was already
there, so adding a few tunes to an existing pass keeps the notes it had.

Open `build/listen/index.html`, or any `<tune>.html` beside the WAVs. <kbd>Space</kbd>
plays, <kbd>1</kbd>/<kbd>2</kbd> switch, <kbd>L</kbd> loops. **Blind mode**
hides which side is which, randomises the assignment, asks you to name the
original and keeps a tally — if you cannot beat chance over a dozen tries on a
tune, that is a stronger result than any column in `FIDELITY.md`.

Each page quotes that tune's row from `FIDELITY.md` and its bullets from the
`LISTENING.md` `listen.py` wrote, rather than restating them, so a page cannot
tell a listener to listen for something the report does not say. A `-` column
is dropped rather than printed, because in that report it means *no shared
instrument key* and not zero.

The default pages reference the WAVs beside them, so a page is about 13 KB and
carries a tune of any length — which is the mode to use, since 30 s is rarely
enough to judge a tune and two minutes of inlined audio exceeds what any single
file should carry. `--embed` inlines both renders for publishing somewhere the
WAVs cannot follow, at 4/3 the size of the audio: about 14 MB for a minute a
side at 44.1 kHz mono, which is the practical ceiling. If a browser refuses
`file://` media, serve `build/listen/` over http.

**Opening the pass: run `build/listen/Listen.cmd`.** The build writes it beside
`Listen.ps1`, and the `.cmd` is the one to double-click — Windows has no "run"
default verb for `.ps1` (Explorer opens it in an editor) and even the
right-click *Run with PowerShell* can be refused by the execution policy, so
the PowerShell script alone could not be started by the gesture its own header
recommended. The shim passes `-ExecutionPolicy Bypass` for that one invocation
and changes no machine setting.

It serves with `--no-build`, which matters: a plain `--serve` rebuilds every
staged page *before* it binds the port — about 3.4 s a tune, five minutes over
a full corpus — so the window sat silent and read as hung, and a browser opened
against it got `ERR_CONNECTION_REFUSED`. `--no-build` serves what is already
staged and binds at once. Rebuild with a plain `python abpage.py` when the
pages are actually stale.

### The instrument map — `instrmap.py`

Every other instrument-level check in this project reads the *player's own
instrument table* and then argues about what its bytes mean. This reads the
other end: what the SID registers actually hold, in the original and in our
conversion, side by side. **It is the one place in the repo that makes this
comparison** — `songview.py` (below) used to carry a second, overlapping
`--compare` mode; it was removed because it duplicated this tool and broke
`songview.py`'s own "judges nothing and scores nothing" promise.

```sh
cd python
python instrmap.py <sid-or-dir> -o ../build/instrmap -t 60 --presets ../presets.json
python instrmap.py <sid> -o ../build/instrmap --json ../build/instrmap.json
```

One Markdown file per song plus an index. On demand, not a build artefact — it
traces two emulations per song. `abpage.py --instrmap` runs it over the staged
tunes and surfaces the per-song summary on each listening page.

`--json` writes the same per-song counts as a machine-readable list, which is
what `abpage.py` reads. Deliberately not scraped from the Markdown index: a
table-scraper breaks the next time a column is added or reordered, and it does
so **silently**, reading nothing for every column it no longer finds — the
exact failure that cost this project an adoption and a retraction at v0.5.352.
The window travels in the file beside the rows, because these counts are
window-dependent: an instrument a tune introduces late is "only original" at
10 s and matched at 60 s, and a reader who cannot see the window cannot tell
those two apart.

#### Both traces, aligned — and why it is not a `diff`

Each report opens with the two siddumps **interleaved frame by frame**, one
voice per fold, with only genuine differences marked. The obvious thing —
running the two dumps through `diff` side by side — does not work, and not
marginally: on ACE II, **2 of 3001 lines match and difflib scores 0.001**, on a
conversion whose `melody`, `seq` and `pitch` are all 100%. Three reasons, all
of which the aligned view corrects and none of which a text diff can:

* **`....` means *unchanged*.** siddump prints a register only when it changes,
  so the text is a list of write-events, not of states, and two traces holding
  identical values differ on nearly every line. Both sides are resolved to
  per-frame state before anything is compared.
* **The packed player starts late.** gt2reloc reaches its first note 3–8 frames
  after the original (corpus median 6). Frame *k* against frame *k* disagrees
  everywhere by construction, so our side is shifted by `fidelity.startup_lag`
  — the same estimator every per-frame column in `FIDELITY.md` uses, taken from
  the two first attack frames and never fitted to maximise agreement.
* **The traces drift** by `-1/(skip+1)` a frame, and one frame of slip makes
  every later line differ with nothing for a diff to realign on.

**The per-voice percentages it prints are not `FIDELITY.md`'s columns.** They
count frames on which a register holds the same value on both sides; `melody`
is a difflib ratio over a note *sequence* and does not care when a note lands,
and `wave` excludes the gate bit and corrects the lag before averaging. A voice
reads 56% here and 100% there without either being wrong — the same notes in
the same order, each arriving a frame or two out. Use this to find **where** two
traces part company, and the report's own columns to judge whether it matters.

The join is **ADSR**. It is a verbatim per-instrument copy of the record (0 of
1635 corpus records differ), so it identifies an instrument where waveform and
pulse cannot: several instruments share a waveform, and a swept pulse has no
single value. Each report gives one row per instrument of ours — what the
original sounds under that ADSR against what we sound — then the original's
per-frame behaviour over the first 8 frames of each note (the spec the `.sng`
should meet), what we actually wrote into the wavetable, and pulse width per
instrument.

**Both full siddump tables are folded into every report, with three instrument
columns appended.** `Ins1`–`Ins3` name the GT instrument sounding on each
voice, `*` marks a note's onset and `.` a voice with nothing yet; an ADSR no
instrument of ours carries gets a lowercase letter, named in a legend. On the
*original's* dump this is what labels Hubbard's trace with our instrument
numbers, so the summary tables can be read down the trace rather than taken on
trust — and the frames our instruments do not cover are visible rather than
counted. The instrument is decided on the frame *after* the attack and held for
the note, for the same reason the tables above are: the attack frame can still
hold a hard restart's ADSR, which is the player's transition and not the
instrument. `--no-dump` leaves the tables out.

**The pulse column reports the band each note covers, not the width at its
onset.** A pulse program restarts with the note (`gplay.c:375-379`), so it is
at the same place on every onset however far it travels afterwards — an
onset-only reading calls a working sweep static, and did, for the whole of
v0.5.174's first draft. The verdict is the *median travel within one note*
rather than the union of the bands across notes: a player sweep that free-runs
visits every phase, so comparing unions would score that difference as
agreement.

It has already found what no score did. Commando's drum was silent because our
first-frame waveform `$09` carries the testbit and the tick cleared the gate on
top of it (v0.5.172, 14 onsets against 0); the alternating rows under one
instrument number are the arpeggio the ear had guessed at; and GT 1's flat duty
cycle turned out to be a third pulse engine nothing had read, in 24 corpus
files (v0.5.174, § `--pulse`).

### The song view — `songview.py`

`instrmap.py` reads what the SID registers *held*; this reads what the `.sng`
*says*. Goattracker's editor can show the same bytes, but it shows a wavetable
as a narrow column of hex pairs and a pattern sixteen rows at a time, so
answering "which entry is instrument 3 opening on, and what does that byte
mean" costs a dozen keystrokes and a page of held state.

```sh
cd python
python songview.py <song.sng|song.sid> -o ../build/song.html --presets ../presets.json
```

One self-contained HTML file, no external assets. Give it a `.sid` and it
converts first, with the song's own preset options (via `fidelity._preset_opts`,
so it cannot drift from what every measurement in the repo is taken with).

It **judges nothing and scores nothing**, which is the point: every metric this
project has added could be, and several were, silently wrong in a way that
changed a decision. A renderer of bytes already on disk has no such failure
mode. Three things it does that the editor cannot:

- **Every pattern carries all three of its identities** — Goattracker's hex
  number (what the editor and a listener say), the converter's post-dedup
  index, and the Hubbard pattern behind it. A listener's "PATT.12" is pattern
  18 is Hubbard's 15, with the orderlist transposing on top; § 7 records three
  separate debugging attempts lost to exactly that confusion.
- **Wavetable entries carry cumulative timing** — a delay entry is current for
  `value + 1` play calls (`gplay.c:697-704`), not `value`, and reading it the
  other way left every multispeed file's attack a call too long from v0.5.82 to
  v0.5.130. The table prints "covers calls 5-7" rather than `02 80`, so the
  arithmetic is visible instead of remembered.
- **Instruments carry their provenance** — `_write_instruments` stamps each
  record `NN:b5-b6-b7`, and byte 7 is the player's own effect byte, so the
  `.sng` alone says which effect bits (`$01` drum, `$04` two-stage, `$08`
  program, `$10` arpeggio, `$20` filter, `$40` fixed pitch, `$80` sfx-drum) the
  source record set. They are decoded into tags on each instrument.

`tests/test_songview.py` checks the parser against `build_sng`'s output and
against the byte-exact `Commando.sng` fixture. The parser is deliberately a
*second* reader rather than a re-use of the writer's internals — one that
shared code could not disagree with the writer, and disagreeing is the value.

### The queue — `fidelity_queue.py`

`python fidelity_queue.py --from-json ../build/fidelity.json -o ../docs/QUEUE.md
--json ../build/queue.json` turns the report's misses into a ranked queue of
*causes* rather than a table of files: the same reduction the onset census
made by hand ("18% disagree" into "`$01` x19, `$04` x11, `$80` x6"), applied
across every source this repo already measures. It reads `build/fidelity.json`,
`build/approvals.json` and `build/search_refusals.json` and sorts what it finds
into six tiers, ranked for what each means rather than fitted to a score: **1**
stale approvals (a human verdict the tool could not carry forward — `[user]`,
nothing else closes these), **2** length rule failures (`len` outside ±5 s, or
unbounded — `[main]`), **3** search refusals (a measured gain a criterion
refused — `[main]`), **4** voice deficits (one voice's `aud` well below the
file's others — `[main]`), **5** census buckets (onset/hold kinds grouped by
cause across the whole corpus — `[subagent]` to confirm the bucket shares one
mechanism, then `[main]` to fix it), and **6** column outliers (a file far
below the corpus median on some column — the lowest tier, a lead rather than a
finding). Within a tier, entries are ordered by how many files a shared cause
reaches, never by a weighted scalar across tiers. Each entry is deduplicated by
*annotation*, not by dropping it: one a plan task already names is marked
`already_tracked`, one a done run record already refuted is marked
`already_refuted`, so a regeneration cannot silently re-propose a cause that
was already ruled out. `docs/QUEUE.md` is a `/whattask` source beside
`todo.md`, and `build/queue.json` carries `first_seen`/`last_seen` per entry
plus a `closed since last run` list once a prior run exists to compare against.

