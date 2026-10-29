# MagPlaySID — what h2g can take from it

Analysis of `C:\Users\mit\Downloads\MagPlaySID-main\MagPlaySID-main` (Magnar Harestad / Censor
Design, started 2026-10-26, C# / .NET 8 / Avalonia), written 2026-10-29 against h2g v0.5.621.

**How this was checked.** §1–§6 are a static reading, with every claim about MagPlaySID citing its
file. **§0 was measured** once the user allowed a build (2026-10-29). MagPlaySID's own figures (the
471-file agreement, the 95.4% music share) are still quoted from its `docs/PLAN.md` and were not
reproduced here.

---

## 0. Measured: MagPlaySID side by side with h2g on the 93 staged pairs

### Setup

All scratch, nothing in the repo:

- **Probe:** `C:/t/magplay-probe/probe` is a console program referencing `MagPlay.Transcribe`,
  built with `dotnet build -c Release` against the .NET 8 runtime. It writes, per song, every call's
  cycle and every write in it (`[offset, register, value]`), the `Transcriber.Report` and
  `Agreement.Measure`.
- **Inputs:** for each `build/listen/<song>.trace.json`, the probe runs on the original at
  `sub_orig` and on our packed `build/listen/<song>.h2g.sid` at `sub_ours`, for the page's window
  (180 s for most). That is 186 runs in **47 s** (`runall.py`, 12 at a time).

### MagPlay against siddump

`valid.py` checks each run's end-of-frame state (our side grouped by its multiplier) against the
same song's siddump `trace.json`: waveform, ADSR and pulse per voice, best lag in ±3.

- **183 of 186 agree on at least 98% of frames.**
- The three that don't are `Las_Vegas_Video_Poker`, `Phantoms_of_the_Asteroid` (originals; not yet
  investigated) and `Skate_or_Die_intro` (held DIGI).
- `Transcriber`'s own `Agreement` was exact on all three songs checked by hand (Commando,
  Thundercats, Confuzion).
- Confuzion's measured call period is **16,422 cycles**, the CIA `$4025` timer, i.e. 60 Hz. That is
  the rate `call_rate.py` infers from the header, so the C64 *measures* what siddump is blind to.

### The heard-instrument comparison

`heard.py`, `census.py` and `shapes.py` re-implement MagPlay's `Music` ideas in Python, copying no
code:

- A note starts at a gate rise, including off→on inside one call.
- A note is anchored at its first frame with a waveform, so GoatTracker's `$09` gate+test frame
  before the attack is counted separately (`testpre`) instead of shifting the note.
- Each note is described over its first 6 frames: control byte, pitch relative to the note, onset
  AD/SR, and the hard-restart tail.
- Original notes are paired with ours at the best global lag, within ±2 frames.

**169,881 original notes were paired.** Per attribute, independently (not first-difference):

| Attribute | Notes | Share | Songs | Status |
|---|---:|---:|---:|---|
| `testpre` (our `$09` frame before the attack) | 43,810 | 25.8% | 32 | GoatTracker's hard restart. Its audibility is the A3 question. |
| `sr_rel` (release nibble differs at onset) | 18,415 | 10.8% | 45 | **Deliberate**: the envelope cut, `goatwriter/instruments.py:93-139`. Inaudible by measurement. |
| `tail_env` (original writes ADSR `$0000` before the next note) | 16,327 | 9.6% | 21 | **Deliberate**, same decision. |
| `tail_len` (gate-off frames before the next note differ) | 54,697 | 32.2% | 82 | Overlaps the `gate` column. Not yet split. |
| **`gate`** (gate bit differs within frames 0–5) | **32,479** | **19.1%** | **66** | Real. Shapes below. |
| **`pitch`** (relative pitch differs within frames 0–5) | **43,117** | **25.4%** | **90** | Real. Spot-checked, see below. |
| **`wave`** (waveform differs within frames 0–5) | **12,204** | **7.2%** | **52** | Real. Shapes below. |
| `ad` / `sr_hi` | 1,612 / 1,554 | 0.9% / 0.9% | 17 / 16 | Real, small. |
| `missing` / `invented` | 11,866 / 11,780 | 7.0% / 6.9% | 69 / 35 | Mostly the known melody-miss songs. |

On the attributes judged real (gate, wave, pitch, AD, sustain), **54.4% of original notes are
played by an identical instrument in our conversion, and 65.5% when gate is ignored.** That is
against a corpus melody average in the high .90s: **melody is not where the gap is; the attack is.**

### The largest shapes

These come from `shapes.py`. Each is a candidate fix, a census over every song that shares it (the
cross-song rule).

1. **Gate held one frame too long after the attack** (`orig 100000 / ours 110000`): **13,627
   notes**. Game_Killer 1,596, One_Man_and_his_Droid 1,534, Spellbound 1,518, Last_V8 1,340, … The
   original writes the second frame with the gate off (`$80`, noise); ours writes `$81`.
   - **Retracted as a fix target (2026-10-29): this is the deliberate gated tick, not a defect.**
     An earlier draft called it drum shape A1 and the highest-leverage fix. Both were wrong.
     - It is `wavetable._drum_tick_noise`'s rule: the tick is gate-off at -S1 and gated above it.
       Above -S1 the SID's ADSR delay makes a gate-off tick release the voice before its attack
       has started. That docstring measures the cost of clearing it at v0.5.510: `loud` down on
       10 of 22 multispeed files, and the Rasputin drum voice 1.4 dB quieter.
     - The original avoids the delay by writing ADSR `$0000` before every rise. Several attempts
       at that are refused in the same docstring.
     - Re-counted with the same pairing and the noise-frame test (frame 1 has noise, gate off in
       the original, gate on in ours): 18,670 notes are on -S>1 songs. The 107 on -S1 are all
       Commando's, held by the byte-exact fixture.
     - Excusing this shape lifts the instrument match from **54.4% to 61.2%**.
   - Related shapes: `100000 / 111000` (2,266: Bump_Set_Spike, Thrust, International_Karate) and
     `100000 / 111111` (708: Proteus). These are not yet checked against the same rule.
2. **Stale pitch on the attack frame** (`pitch@0`). The original's attack frame already holds the
   new note's frequency; ours holds the previous note's for one frame.
   - Radio_ACE: original `$03E0/41`, ours `$03D3/41`. Then both have `$52C8/81`.
   - Radio_ACE 1,444, Auf_Wiedersehen_Monty 1,354, Hollywood_or_Bust 1,262, Pacific_Coast 545,
     5_Title_Tunes 564, Pygmies 547, …
   - This is the Hollywood agent's "mechanism 1" (`C:/t/hollywood-melody-root-cause/finding.md`), and
     it is a corpus-wide shape, not a Hollywood one.
3. **Noise frame replaced by tone** (`frame 1: orig 8 ours 1`, 2,504, and `orig 8 ours 4`, 1,321 +
   988 + 625). Hollywood 1,503 (the derived-arpeggio/`wave_alternate` finding), Pacific_Coast,
   Radio_ACE, IK_plus 933, Spellbound, Proteus, Warhawk. This is drum shape **A2**.
4. **Gate dropped one frame early at the end of the window** (`11110 / 11111`, 5,223:
   5_Title_Tunes, Ninja, Pygmies) and its mirror (`11111 / 11110`, 1,559: Mozart).
5. **A whole drum program missing.** On Radio_ACE the original plays `11 81 41 40 80 80 …` on the
   drum record and ours holds `$11` throughout. Seen on one pair; not yet censused.

### Not yet done

- `tail_len` is not yet split from what the `gate` column already scores.
- Pairing is greedy within ±2 frames at one global lag. Songs with drifting clocks (Dragons_Lair,
  Phantoms) inflate `missing`/`invented`.
- Pitch is relative to each side's own fitted tuning (circular mean). Wobbles shorter than 6
  frames, such as a vibrato phase, also count as `pitch`.
- Audibility is not judged here. The census says *which* register shapes differ, not whether a
  listener hears each one; that is the listening pass.

---

---

## 1. What MagPlaySID is

| Project | Lines | Role |
|---|---|---|
| `MagPlay.C64` | ~1,350 | A C64 that is cycle-exact enough for SID tunes. It covers CIA 1/2 timers, IRQ/NMI, the VIC raster IRQ and a stub KERNAL, and runs RSIDs. Each SID write is recorded with its **cycle** and its **context**: IRQ call, NMI or main loop. |
| `MagPlay.Transcribe` | ~1,240 | `Recording` cuts the writes into *calls*. `Music` hears notes and instruments. `Transcriber` adds a raw layer so the score is lossless, and `Agreement` scores a score by replaying it. |
| `MagPlay.Score` | ~1,540 | A tracker-shaped score format that is a GoatTracker superset, plus a C# player for it. Time is counted in CPU cycles. |
| `MagPlaySID` (app) | ~1,700 | The player window. It has a spectrum, one scope per voice, a piano, and a scrolling tracker view with the selected instrument's wave, pulse and filter programs lit. This is the screenshot. |
| `MagSid.*` | large | Shared with the MagSID editor: a reSID port, the 6502 core, PortAudio output, and grid fitting (`SidTranscriber.SuggestGrid`). |

**Licence: GPL-2.0-or-later**, because its reSID port is GPL (README, `LICENSE`). h2g has no
`LICENSE` file; README § Licence only quotes the VB6 author's "used freely". This matters for every
option below; see §6.

---

## 2. `MagPlay.Transcribe` against siddump

### What our trace is today

`fidelity.py` reads `siddump` (`run_siddump`, `parse_dump`), which gives **one sample per frame**: the
register values at the end of the frame, printed sparsely. We patch around that sampling with three
fixes, each recorded as a rule in CLAUDE.md:

- `tools/siddump-rt` adds `-m` (calls per frame) for multispeed.
- `vicetrace.py` reads VICE's per-raster-line `dump` for anything finer than a frame.
- `call_rate.py`, because **siddump is blind to the call rate**: it calls both sides once a row,
  whatever the PSID header says. That blindness is how five CIA-timed tunes packed 1.1969x slow went
  unnoticed until 2026-10-17.

### What `Recording` gives instead

From `Recording.cs` and `Transcriber.cs`:

- **Every write, with its cycle.** Not one sample per frame. A player that writes `$D404` twice in a
  call, such as the gate-off then gate-on of a hard restart, is visible. `Transcriber.Report.Detail`
  counts exactly these "values on the way".
- **Calls are the tune's own IRQs.** Their cycles are recorded, so the **call period is measured, not
  assumed**:
  - `Transcriber.Time` takes the median gap between calls.
  - `CallJitter` of 64 cycles separates "even" calls from listed ones.
  - A CIA-timed tune shows its real period directly. That is the quantity `call_rate.py` has to infer
    from the header and gt2reloc's stub.
- **Multispeed needs no `-m`.** Each IRQ is its own call, so a `-S5` pack shows five calls a frame
  with no flag.
- **The playing context is found automatically.** Players running from the main loop or an NMI are
  found by burst detection (`Recording.PlayerOf`, `Framed`). Corpus impact unmeasured; our digi files
  are on hold anyway.
- **Both sides through one tracer.** Our packed `.sid` is an ordinary PSID, so the original and our
  conversion would go through the same tracer and the same call model. Today siddump and siddump-rt
  differ in how they call the play routine.

### What it does *not* give us

- **It is not our trace format.** `fidelity.Voice` wants `attacks`, `freq_events`, `wf_events` and
  so on, built from siddump's notion of an attack: a gate rise seen at frame end (`siddump.c:376-380`).
  - A per-write tracer sees gate rises that siddump never sees, for example off→on within one call.
  - So **every column would move** if the tracer were swapped. CLAUDE.md's rule applies: translate
    the old rule exactly first, then switch. Numbers before and after the switch are not comparable.
- **`Agreement` is not a fidelity score between two different players.** It compares a score with
  the tune *it was transcribed from*, call by call (`Agreement.Measure`). Original-vs-ours needs lag
  alignment and our multiplier (`startup_lag`, `--equal-calls`). Its per-register "value sequence
  per call, no-op writes dropped" idea (`Agreement.Values`) is still a good metric definition to
  borrow.
- **The C64 is not VICE.** Per PLAN.md § 2 it leaves out bad-line and sprite cycle stealing and the
  CIA start delay. For tunes that only use timer IRQs this is probably irrelevant; it is unverified
  here.

**Verdict:** worth having as a **third trace backend**, beside siddump and vicetrace, with two jobs:
1. An exact per-write, per-cycle trace without driving VICE.
2. A measured call period for both sides, to cross-check `call_rate.py`.

It should not replace siddump for the published columns until a corpus A/B shows what moves.

---

## 3. `Music` instrument decoding against ours

### How each side decodes an instrument

**h2g** decodes **from the player's code and data**. Signatures (`detect.py`) locate Hubbard's
instrument records, the eight bytes per record, and `goatwriter/*` re-encodes the *intent*: effect
bits, drums, skydive, two-stage, arpeggio. `instrmap.py` already reads the other end. It joins both
sides' traces on onset ADSR and waveform class, but only at the **first frame** of each note.

**MagPlay** decodes **from the sound alone** (`Music.cs`), player-agnostic:

| Step | Code | What it does |
|---|---|---|
| Notes | `Frames`, `rises` | A note starts at each gate rise: off→on, or off-and-on inside one call. |
| Note table | `NoteTable`, `Tuning` | Takes the frequencies held while gated and tonal. Their **circular mean** offset from a standard table gives the tune's tuning. Each note's frequency is the one held most often near that semitone. |
| Note name | `Sound.BaseNote` | The table pitch **held longest**, with ties going to the first. So a kick-plus-bass note is named after the bass, not the kick's first pitch. |
| Wave program | `Sound.Hear`, `WaveCall` | Per call while the note sounds: the control byte, AD/SR where they change, and **every way the pitch fits**: relative semitones, absolute note, offset from the note's frequency, or raw frequency. |
| Pulse program | `PulseCall`, `CarriesPulseOn` | Per call: the width "set" or "moved by". A note whose first calls continue the previous sweep leaves the running program alone, like GoatTracker's pulse pointer 0. |
| Hard restart | `Tail` | The calls (at most 4) with the gate off before the next note, plus whether that tail changes AD/SR. This is the "hard restart 0007, 1 before" line in the screenshot. |
| First frame | `KeepsFirstCall` | A note whose first call keeps frequency and pulse from the previous one gets `FirstControl`, i.e. the first-frame waveform. |
| Sharing | `Sound.Plays`, `Fits`, `Join` | Two notes share an instrument when, call by call, *some* pitch encoding fits both. The program's last step holds past its end. Sets are narrowed as notes join. |

### What we can use, and what we cannot

1. **Not as the converter's instrument source.**
   - A heard instrument is "one per way a note is played". PLAN.md's own table reports 14,329
     instruments for 74,893 notes over 471 tunes, about 30 a tune, and many more on dense tunes
     (Demo_Coder_tune_1 has 118).
   - GoatTracker has 63 instruments and 255-row tables. Moreover, instrument 63 is ours: it is
     gt2reloc's startup row.
   - The converter's value is that it carries **Hubbard's** record structure, and the Commando
     byte-exact fixture depends on that.
2. **Yes, as an oracle against our wavetables.** This is the strongest use, and it is what the
   melody-99 work did by hand.
   - The drum shapes in `C:/t/melody99-attribute-misses/mechanisms.md` are all first-frame or
     first-calls disagreements between the original's heard wave program and ours:
     - A1: gate held through the noise burst.
     - A2: the first frame is not noise.
     - A3: a `$09` hard-restart frame thins fast hits.
   - Thundercats' rest click is likewise a **heard note with ADSR $0000**, which we never emitted.
   - A tool that runs `Music.Sound.Hear` over both sides and diffs per Hubbard record would have
     produced that census mechanically.
3. **Borrowable ideas, re-implemented in Python, no code copied:**
   - **Held-longest note naming** (`BaseNote`). This is a candidate second melody naming. Our melody
     column names a note by the pitch at its attack frame, which is exactly why drum-prefixed notes
     count as misses (the A1/A2 families). Run it as a *diagnostic* column beside melody, never as a
     replacement. Melody's definition is what every published figure means.
   - **Circular-mean tuning.** This is a sanity check for `sidfile.find_freq_table`, in particular
     for the six files where no table validates and for two-table files like Powerplay.
   - **Hard-restart tail detection** (`Tail`), to census the original's hard restart per record
     against what `hard_restart.py` emits. That bears on shape A3.
   - **`KeepsFirstCall`**, the trace-side counterpart of our `aligned_firstwave` and
     `gate_off_firstwave` questions.

---

## 4. The visual player

### What MagPlaySID shows (the screenshot)

| Element | Code | Notes |
|---|---|---|
| Spectrum, 96 log bands from 40 Hz to 11 kHz, with peak marks and a reflection | `Player/SpectrumView.cs` | A Hann-windowed FFT of the live scope samples. Peaks fall 0.006 a frame, levels 0.055. |
| One scope per voice | `Player/VoiceScopeView.cs` | Reads `IScopeSource`, the engine's per-voice samples. |
| Piano C-0 to B-7, each voice's key in its colour, brightness following the envelope | `PianoView.cs` | Reads the chip's frequency, control byte and envelope at the sample being heard (`VoiceAt`, `NoteOf`). So it shows arpeggios, slides and drums too. |
| Tracker rows scrolling with the tune, pattern starts marked | `ScoreView.cs` | Driven by `ScoreTimeline` (`PositionOf`, `RowAt`, `FilterStepAt`). |
| Instrument panel: AD/SR, hard restart, wave / pulse / filter program with the sounding step lit | `ScoreView.cs` | |
| "36 instruments, 52 patterns, rows of 7 calls — the score makes 96.0% of the tune's register changes" | `Transcriber.Report.Music` | |

### What our listening page (`abpage.py`) already has

- **Audio and drawn comparisons:** A/B audio players, a static log-frequency spectrogram
  (`spectrogram_card`) and per-voice amplitude overlays (`voicewave_card`, from `listen.py --voices`
  solo renders).
- **Register views:** a per-voice register panel (`panel_card`).
- **Our side as a tracker:** `tracker_card`, **our** `.sng`'s rows scrolling with our render, clickable.
- **Missing:** a live spectrum, scopes, a piano, the **original** shown as a tracker, and an
  instrument/program panel with the sounding step lit.

### How to bring the visual across

Rewrite in JavaScript, not a port of the C# (§6).

1. **Live spectrum and scopes, browser-only.**
   - A WebAudio `AnalyserNode` on the existing `<audio>` elements gives the FFT (`getFloatFrequencyData`)
     and the scope (`getFloatTimeDomainData`).
   - Group the bins into 96 log bands from 40 Hz to 11 kHz with peak hold, as `SpectrumView` does.
   - Scopes come from the six solo renders when staged; otherwise one scope per side.
   - About 150 lines of JS. No new data needed.
2. **Piano.**
   - Needs per-frame frequency, gate and ADSR for both sides. `listen.trace_json` stages
     `wf`/`adsr`/`pulse` per voice but **not frequency**, even though `fidelity.Voice.freq_events`
     already holds it.
   - So: add `freq` to `trace.json`, then light the key from the frequency of the frame under the
     playhead. Show the original and ours as two key colours, which a single-tune player cannot do.
     An A/B piano shows a wrong note at a glance.
3. **Instrument panel with the step lit, for our side.**
   - `songview.py` already decodes our `.sng`'s instruments and tables, and `abpage.row_schedule`
     already maps playhead to row.
   - Extend the schedule to the wavetable and pulse-table position per frame. The rule is
     `gplay.c:697-704`: a delay entry is current for `value + 1` calls. Then highlight that step.
     This would be the screenshot's right-hand panel, for GoatTracker's own tables.
4. **The original as a tracker.** Only possible with a transcription of the original, i.e.
   MagPlaySID's `Music`. The output would be a column "as Hubbard plays it", heard-instrument numbers
   included, beside our "as we play it". It needs step 0, and the instruments are *heard* ones, not
   Hubbard's record numbers, which the page must say.
5. **Zero-code option, now.** MagPlaySID opens any `.sid`, and our packed `.sid` is one. Opening the
   original and `build/listen/<song>.h2g.sid` side by side gives the whole screenshot view for both,
   today. The "music makes N%" line is also a rough, player-agnostic readability figure for the two.

---

## 5. Recommended plan

Tags as CLAUDE.md § "Tag every proposed task".

| # | Task | Tag | Depends on |
|---|---|---|---|
| 0a | **Land the measured tooling in the repo** (§0): a build recipe for `tools/magplay-rt` (out of tree, like `siddump-rt`), plus `python/heard.py` with the `instr` metric (the share of original notes whose first 6 frames of gate, wave and pitch, plus onset AD/sustain, match ours), and the per-attribute and per-shape census written to `build/heard_census.md`. Add it to the on-demand refresh beside the other censuses. | [main] | **landed v0.5.622** (`python/tools/magplay-rt`, `python/heard.py`, `tests/test_heard.py`, MEASURING.md § heard); not yet in the refresh command |
| 0b | ~~Fix the gate-held-one-frame drum shape~~. **Withdrawn**: it is the deliberate gated tick (`wavetable._drum_tick_noise`, §0 shape 1). Instead, mark it known-equivalent in the `instr` metric. | — | 0a |
| 0c | **Fix the stale attack-frame pitch** (§0 shape 2). It is the Hollywood mechanism 1 seen corpus-wide. Census its emitter first: no_test_restart vs the firstwave path. | [main] | 0a |
| 0 | **Permission plus a headless dump.** (Done in scratch: `C:/t/magplay-probe`.) Allow building and running MagPlaySID locally. Add a small console project *outside* the repo (as `tools/siddump-rt` is a build of an external tool) that writes JSON per song: call cycles, writes per call with cycle, `Transcriber.Report`, and the heard instruments (`Music.Of`). Run it over the corpus at `-t 180`, originals and our packed `.sid`. | [user] then [main] | — |
| 1 | **Validate against siddump.** For every corpus file at multiplier 1, compare the end-of-call register state with siddump's per-frame state, reporting agreement per register and naming every file that disagrees. For the CIA-timed files (Confuzion, Human_Race, Battle_of_Britain, C64 Music Examples, 5_Title_Tunes s3), compare the measured call period against `call_rate.py`. | [subagent] | 0 |
| 2 | **Live spectrum and scopes in `abpage.py`.** WebAudio only, no new data. Verify the rendering with Playwright. | [subagent] | — |
| 3 | **A/B piano.** Add `freq` to `listen.trace_json`, then add the piano to `abpage.py`. | [subagent] | — |
| 4 | **Lit-step instrument panel for our `.sng`.** Extend `row_schedule` with the wave and pulse table position, then add a panel card. | [subagent] | — |
| 5 | **Heard-instrument oracle `instrhear.py`.** For each song, take the original's heard wave/pulse program and hard-restart tail per note, pair it with our note, and census the disagreements by Hubbard record, ranked by melody notes lost. This is the mechanical version of `mechanisms.md`. | [main] | 0, 1 |
| 6 | **Diagnostic "held-longest" melody naming** beside melody, never instead of it. | [subagent] | 0 |
| 7 | **Original-as-tracker column** on the listening page, from task 0's JSON. | [subagent] | 0, 1 |
| 8 | **Third trace backend `--tracer magplay`** in `fidelity.py`, with a full A/B against siddump. It is never the default without an explicit comparability note in FIDELITY.md. | [main] | 1 |

Tasks 2–4 need nothing from MagPlaySID and can start now. They take the *ideas* from the
screenshot, using data we already stage.

---

## 6. Licensing — a decision for you

- **Running MagPlaySID as an external tool** (tasks 0, 1, 5, 7, 8), the way we run siddump, VICE and
  gt2reloc, does not make h2g a derivative work. Keep it out of the repo and build it like
  `siddump-rt`.
- **Re-implementing ideas** (tasks 2–4, 6: held-longest naming, log-band spectrum, piano) copies no
  code and needs nothing.
- **Translating its C# into Python inside h2g** (`Music.cs` and the rest) would make those parts a
  GPL-2+ derivative. h2g would then need to be GPL-compatible. The VB6 author's "used freely" grant
  likely permits that, but it is your call to make, not mine.

**Recommendation:** use it as an external tool and re-implement only ideas. That keeps the licence
question closed, and it keeps the oracle *independent* of our converter, which is the point of an
oracle.
