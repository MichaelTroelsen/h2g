# Per-song fidelity plan, and improvements to the listening tool

Written at v0.5.318 (uncommitted tree). Two asks: a working plan that takes
**one song at a time** and drives it by the fidelity score, and an audit of
**what the metrics still miss** plus **what the A/B pages could add**
(overlaid waveforms, per-voice comparison).

---

## 1. The per-song loop

Every real win in this repo's history had the same shape: one file measured,
one mechanism read out of its player, one fix verified corpus-wide. The corpus
sweeps exist to *catch regressions*, not to find work. So the loop below picks
one song and stays on it until it either moves or is refused with numbers.

Each step uses a tool that already exists — nothing here needs building:

| step | command (from `python/`) | what it settles |
|---|---|---|
| 1. Score it | `python fidelity.py <song>.sid -t 60 --presets ../presets.json` | which columns are low — the *symptom list* |
| 2. Suspect the harness first | `python fidelity.py <song>.sid --diagnose` | subtune correspondence + per-voice cause. Five defects have been in the measurement; a low row is a claim about the harness until this says otherwise |
| 3. Timing before timbre | `python fidelity.py <song>.sid --pace` | row length, drift, startup lag. A wrong clock poisons every per-frame column |
| 4. Classify the misses | `--census`, `--hold-census`, `--vib-census`, `--gate-census` | turns "wave 63%" into "$01 ×19, $04 ×11" — a queue, not a number |
| 5. Read what we said | `python songview.py <song>.sng -o v.html --presets ../presets.json` | the conversion as data: wavetables with call timing, all three pattern identities |
| 6. Listen | `build/listen/<song>.html` (A/B page) | the only check that covers what no column sees |
| 7. Read the player | disassemble the routine the census blames | the mechanism — never generalise a per-instrument correlation without this |
| 8. Fix + A/B | corpus byte-hash (only intended files move) + `fidelity.py --baseline` at `-t 60` | the fix reaches what it should and nothing else |
| 9. Ship or refuse | tests pass, `Commando.sng` byte-exact, artefacts regenerated once, numbers in the commit message | either way the outcome is recorded |

Rules that keep the loop honest (all learned expensively, all in CLAUDE.md):
a file above `-S4` is judged with `--equal-calls`; a ratio is compared in log
space; a flat report is checked with `--baseline` before concluding "no
effect"; a per-file profile is verified on a second file before shipping.

### Which song first — a shortlist, in order

1. ~~**Knucklebusters**~~ — **worked at v0.5.322, and the tempo write is not
   its lever.** Refused for scoping, with the numbers, because the premise did
   not survive the file's own bytes:
   * Every subtune's entry pattern **already carries a tempo** — subtune 0 and
     2 share pattern 29 at value 6, the traced subtune 1 has pattern 0 at
     value 3, all at row 0. Nothing is missing for a widened scan to add, so
     the A/B's 50→81 pp gain has **no identified mechanism** — the same
     position Human_Race reached, and not a basis for shipping.
   * The traced subtune wants **7/3 = 2.33 frames** a row and is given 3:
     28.6% slow, which predicts about 0.78 of the original's attacks. `retrig`
     measures **0.39**, so the row explains at most half of it.
   * `--pace` refuses the file outright (IQR spans 56% of the median), which
     by this repo's own rule is a mechanism rather than a constant.
   * The subtunes want **mutually incompatible multipliers** — 1, 3, 8, 8, 8,
     4 for subtunes 0–5 — and the file is packed `-S1`, so five of six play at
     a rate no single `-S` can express.
   * **Our `.sng` carries 3 subtunes against the original's 11.**
   * On the traced pair: voice 0 **under-produced, 16 attacks against 48**;
     voice 1 matches at ratio 0.69; voice 2 is **different music** (pitches
     14% the same).

   So this file's melody is limited by structure — dropped subtunes, a wrong
   voice, an unexpressible rate — not by a tempo command. It should re-enter
   the loop as a subtune/structure question, not a tempo one.
2. **Human_Race** (melody 65%) — the same lever fixes its lost clock (drift
   −250 → −7.8, wave 63→89) while costing melody. The only file where the two
   readings point opposite ways; understanding it is understanding the lever.
3. **Geoff_Capes** (melody 49%) — third file in the same cluster, gains from
   the same write.
4. **Dragons_Lair_Part_II / Commodore_64_Music_Examples** (14% / 16%) —
   "plays something else". Step 2 first, and only step 2: DLP2 was already
   shown once to be 94–98% against its *real* counterpart subtunes.
5. **Auf_Wiedersehen_Monty** (melody 90%, voice 3 at 77%) — carries the open
   bit-6 `$41` fact; a listen verdict is already queued on it.

One song per session. The corpus A/B at the end of each is the guard rail.

---

## 2. Metrics: what is missing

`FIDELITY.md`'s generated tail states: **every SID register is read by some
dimension** — the register-coverage question is closed. What remains missing
is *within* registers already read, and the report documents most of it
itself. In rough order of value:

| gap | where it hides | status |
|---|---|---|
| **Sync + ring-mod bits** | `$D404` bits 1–2. `wave` compares `x & 0xF0` and its comment says outright the low nibble is excluded; `gate` reads bit 0 only. A conversion could drop every ring-mod effect and no column moves | **genuinely unscored — best candidate for a new column** |
| **Noise pitch** | `$D400/01` during noise frames. Two decoded mechanisms (bit `$10` arp, sfx drum pitch) already wait on it | already queued (`noise-pitch-column`) |
| **Resonance** | `$D417` high nibble. `filt` reads the routing bits of the same byte and never separates resonance | documented in the report's own limits |
| **Master volume** | `$D418` low nibble — parsed, never compared | documented |
| **Sweep direction/phase** | `pul` counts duty movement "without judging the sweep"; `cut` counts travel, not direction. A pulse swept the wrong way at the right rate scores 100% | documented; fix is a signed-travel or correlation variant, same shape as `bend` vs `slides` |
| **Row length as a column** | only `--pace` (a mode) and `drift` (accumulated phase) see tempo | acceptable — drift catches the audible case |
| **Note length above `-S3`** | `hold`'s declared blindness (deficit is in play calls, sub-frame at `-S4`) | structural; declared in the Dimension |

On the GT-documentation angle (track effects `1XY–FXY`, wavetable, pulsetable,
filtertable, bitmasks): the harness deliberately measures **register outcomes,
not GT commands** — a command is a means, the register trace is the sound, and
scoring commands would mark a correct-sounding alternative encoding as wrong.
The two places GT-side structure *is* worth checking are already covered:
`tests/test_table_validation.py` replicates GT's `exectable` over every corpus
conversion, and `songview.py` decodes every table for eyes. The gaps worth
taking from the GT docs are the SID-side ones in the table above.

Any new column follows the repo's Dimension rules: declare its registers,
reproduce an existing number under the old rule before being trusted
(§ 7.nn's lesson), and state what it ignores.

Suggested first build: **one `ctrl` column for sync/ring** (cheap, closes the
last unscored bits of `$D404`), then the queued noise-pitch column. `[main]`
— each changes every row of the generated report.

---

## 3. Listening-tool improvements

### 3a. Per-voice A/B — *feasible today, verified*

`sidplayfp -u<num>` mutes a voice (checked against the installed 2.15.2:
`-u1 -u2` leaves voice 3 solo). So per-voice pairs need **no new renderer**:

- `listen.py --voices <song>`: render each side 3 more times (`-u2 -u3`,
  `-u1 -u3`, `-u1 -u2`) → `<name>.v1/v2/v3.{original,h2g}.wav`.
- `abpage.py`: a voice selector row (All / V1 / V2 / V3) that swaps the A/B
  sources; blind mode unchanged.
- Cost is 4× render time and disk, so **per-song on demand, never `--all`**
  (the full corpus is already 1.7 GB). Fits the per-song loop at step 6.
- Caveat to verify on first use: muting must not change what the *player*
  does (it shouldn't — it gates the emulator's output, not the code), and
  digi-engine files' sample channel is `-g`, not `-u`.

This also pairs naturally with `--diagnose`'s per-voice cause: the column
says *which* voice, the solo pair lets you hear *what*.

### 3b. Overlaid waveform display — *feasible, self-contained*

The A/B pages are plain local HTML in `build/listen/`, so Web Audio is
available: `decodeAudioData` both WAVs, downsample to peak envelopes, draw
both on one `<canvas>` (original in one colour, ours in another, difference
shaded). No external libraries needed.

What it will and won't show — worth stating on the page itself:
- **Will**: dropped/extra notes, wrong note lengths, tempo drift (the
  envelopes visibly shear apart), missing drums, silence.
- **Won't**: pitch, timbre, filter — amplitude hides all three. A
  **spectrogram overlay** (FFT per window, two hues, same canvas) covers
  pitch/timbre and is the better second step; costlier to draw but still
  self-contained.
- A click on the canvas should seek both players to that position — that
  turns the display from a picture into a navigation tool for the A/B.

### 3c. Small, cheap additions

- Per-voice **piano-roll strips from the siddump traces we already have**
  (fidelity's `--json` carries per-voice notes): a visual note-by-note diff
  under the audio, no rendering cost at all, and it shows pitch — the thing
  the waveform can't.
- Show the song's FIDELITY row on the A/B page next to the blind-score box
  (LISTENING.md text is already quoted; add the numeric row) so a listen and
  its prediction sit on one screen.

Build order: **3a first** (verified flag, pure staging change, `[subagent]`
candidate — `listen.py`/`abpage.py` only, no generated files), then the
envelope overlay, then spectrogram/piano-roll as wanted. Each is independently
shippable.

---

## 4. What this plan displaces

Nothing is deleted, but the vibrato bucket fan-out is **paused as designed**:
the `plain` bucket decomposition (v0.5.318 run log) showed its largest group
is an undecoded mechanism, not an emitter fix, so it re-enters through the
per-song loop when a chosen song's `vib` column is the low one. The listening
verdicts (`[user]`) remain the standing highest-value item and are unchanged
by any of this — the per-voice pairs of 3a exist to make them easier.
