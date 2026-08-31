# TODO

Hand-written, unlike `whats-next.md` (a session handoff) and
`.claude/tasks/whattask.json` (generated, and rewritten whole by `/whattask`).
`/whattask` reads this file as one of its sources, so an item here survives a
replan and reaches the next plan on its own.

Keep items actionable: what to run, and what makes it done.

## Open

- **Rebuild `build/instrmap`.** The dumps on disk are stale against HEAD:
  `build/instrmap/*.md` has mtime `2026-08-23 14:03`, while `428ca07` — which
  enables `--rest-envelope-silence` for ACE_II, Thundercats, Shockway_Rider,
  BMX_Kidz and Auf_Wiedersehen_Monty — landed at `15:38`. So every dump
  predates the conversion change for those five files.

  This matters because the instrument maps are the input to every read-only
  diagnosis in the current plan, and to the vibrato-depth measurements recorded
  in CLAUDE.md. A sibling agent regenerated ACE_II's map fresh and found its
  figures matched the stale ones to within rounding (voice 1 78.9%/97.5% against
  79%/98%), so nothing measured so far is known to be wrong — but that is one
  file checked, not a guarantee, and the next diagnosis should not have to
  re-establish it.

  ```sh
  cd python
  python abpage.py --instrmap "C:/Users/mit/claude/c64server/SIDM2/SID/Hubbard_Rob"
  ```

  That regenerates `build/instrmap/` **and** rebuilds the listening pages,
  copying each report beside them. Done when every `build/instrmap/*.md` is
  newer than the most recent commit that changed conversion output.

  `[main]` — it rebuilds `build/instrmap` and `build/listen`, both of which the
  plan lists as hazards, so it must not run beside anything reading them.

- **Action Biker: confirm the subtune pairing by ear, and keep it confirmable.**
  A listener reported "the original's channel 3 is channel 2 in H2G". The
  channels were never wrong — our `.sng` played its *subtunes* in the wrong
  order, so the two sides were different pieces of music. `f63caa1` fixed the
  converter (the selector named a six-byte scratch buffer, `$C3F3`, where the
  table is `$C3F9`).

  Measured state at `f1dab41`: `Action_Biker` traces at subtune **1** with
  `matched_subtune 1`, and **0 of 95** rows in `build/fidelity.json` now have
  `matched_subtune != subtune`, so the `--search-subtunes` shim has nothing
  left to compensate for. `--diagnose` reads the correspondence as the
  identity, all three voices `ratio 1.00, pitches 100%`.

  What is NOT yet true is the thing the listener would check: the staged
  audio in `build/listen` predates `f63caa1`, so the WAV pair on the page is
  still the wrong-order conversion. Re-stage, then listen.

  ```sh
  cd python
  python listen.py "<sid_dir>" --files Action_Biker.sid --voices -t 120 --presets ../presets.json
  ```

  Done when a listener confirms the channel complaint is gone on freshly
  staged audio. Note `listen.py --all` without `--from-json` pairs both sides
  by the *same* index — correct now that no file needs `matched_subtune`, but
  it is correct by coincidence rather than by construction, and a future
  correspondence defect would silently return to staging mismatched music.

  `[user]` for the verdict; the re-stage itself is `[main]`.

- **Action Biker's fidelity is not 99%.** Its sequence columns are perfect —
  `melody`, `seq`, `pitch` all 100%, `retrig` 1.00, `drift` +0.0, 291 notes
  against 291 — so whatever is left is not the notes. The deficit is in the
  register columns:

  | column | Action_Biker | reading |
  |---|---|---|
  | `nrun` | **0%** | 682/744 noise frames present, i.e. 92% of the original's, yet *zero* agreement on run LENGTHS |
  | `hold` | **0%** | at `-S1`, where CLAUDE.md records 106 of 121 instruments reading -1 — likely the known `gatetimer & $3f` fetch deficit, not a defect |
  | `adsr` | 69% | |
  | `gate` | 72% | |
  | `wave` | 97% | |

  `nrun` is the one to chase: getting the noise frame *count* almost exactly
  right while getting every run *length* wrong is a specific, mechanical
  signature, not noise. Start with `fidelity.py Action_Biker.sid --census` and
  classify the misses by cause before touching an emitter — CLAUDE.md's *a
  census of what a column misses is a queue, not a report*.

  Check `hold` against `--hold-census` FIRST and expect it to be `fetch`/`slot`
  rather than `short`/`long`; if so it is not a note-length defect and no
  wavetable edit can move it (the same refutation ACE_II's `hold` got).

  Done when `nrun` is either materially above 0% or refuted with a named cause.
  `[subagent]` for the census, `[main]` for any emitter change.

- **The conversion must be the same length as the original, ±5 seconds.**
  A listening rule (recorded in CLAUDE.md as an invariant). Where the original
  ENDS, ours must end too. No column enforces it: `drift`, `retrig` and
  `--pace` all measure the rate of a row, and every one of them is satisfied by
  a conversion that plays the right music at the right speed *forever*.

  Measured on Action_Biker at v0.5.375, both sides traced 180 s:

  | | attacks | last attack | after that |
  |---|---:|---|---|
  | original | 291 | 59.54 s | 120 s of silence — it stops |
  | ours | 856 | 179.68 s | never stops, loops every 61.44 s |

  Per loop ours carries 52/52/187 attacks per voice against the original's
  52/52/187 in total, so the music is right and only the ending is wrong.

  CAUSE, already documented: Hubbard's `$FE` track byte means *tune ended*; a
  Goattracker orderlist cannot say that, and `--legal-restart` rewrites it as a
  restart at position 0, which is what makes the file packable at all.

  TWO PIECES OF WORK, and they are separable:

  1. **A `len` dimension** in `FIDELITY.md`: seconds of music ours plays
     against the original's, flagged when the ratio leaves ±5 s. The detector
     already exists — `fidelity.original_ended` returns the second the original
     stops — so this is reporting a number the harness already computes rather
     than deriving a new one. `[subagent]`, touches `python/fidelity.py` and
     `python/tests/test_fidelity.py`.
  2. **An option to end rather than loop**: restart into a SILENT pattern
     instead of position 0, so the tune stops in every way a listener can hear.
     Must be opt-in — a looping tracker song is often what is wanted, and this
     changes the bytes of every file whose original ends. `[main]`, touches
     `python/h2g/tracks.py` / `goatwriter.py` and the presets search.

  READ `original_ended`'s USE AS A DEFECT QUEUE. It currently shortens the
  comparison window so our surplus is not charged, which protects the score
  while the shipped `.sng` still plays forever — the same shape as the
  `--search-subtunes` line corrected in v0.5.375. Every file whose window it
  shortens fails this rule. Action Biker is not one of them only because its
  60 s window happens to end where the tune does.

  Done when the report names every file failing the ±5 s rule, and a listener
  confirms one of them ends.

- **5 Title Tunes fidelity.** Like Action Biker, the sequence is essentially
  exact — `melody` and `seq` 100%, `retrig` 1.00, `drift` +0.0, `onset` 100%,
  and **938 original notes against 938** (this read "against 935" when written).
  `pitch` is **98%**, not the 100% once claimed here — one distinct pitch in
  sixty-one, too small to be this entry's subject but not nothing. So almost
  nothing here is about the notes. The row (`docs/FIDELITY.md:25`):

  **EVERY FIGURE BELOW WAS RE-READ AT v0.5.421 AND MOST OF THEM HAD MOVED.**
  The old column is kept beside the new one because this entry's argument was
  built on the old numbers and a reader needs to see which of it survives.

  | column | was | NOW | reading |
  |---|---|---|---|
  | `pul` | 4459/2240 = 1.99x | **4318/2240 = 1.93x** | still about twice as many duty-cycle moves as the original |
  | `pspan` | 0.47x | **1.05x** | **RESOLVED.** The band is right now; see below |
  | `pphase` | — | 1.00x | |
  | `gate` | 50% | **75%** | one frame of surplus ringing per release, and `max_hard_restart` has SATURATED it |
  | `adsr` | 58% | 58% | unchanged, and 75% of the deficit is inaudible gated-off frames |
  | `wave` | 90% | **99%** | |
  | `hold` | 0% | **86%** | one instrument of seven, kind `fetch` |
  | `nrun` | — | `-` | correct: the tune sounds no noise at all |

  **CENSUSED at v0.5.376 — `pul` is NOT a defect and the claim once written
  here that "1.99 x 0.47 = 0.94, so the total travel is about right" was wrong:
  `pspan` is the max-min BAND, not a per-step size, so multiplying the two
  decomposes nothing.** Measured, our travel is 1.64-1.85x the original's.

  `pul` 1.93x (1.99x when written) is the documented half-step substitution
  and is correct. The
  records confirm it exactly: `rec+6` `$41` -> step 64 / delay 2 -> speed 32,
  and `$81` -> step 128 / delay 2 -> speed 64, which are precisely the step
  sizes observed on the trace (32, and 64/65). Same average sweep rate, taken
  in half-size steps twice as often. `fidelity._span`'s own docstring already
  says so: "the count doubles while the sound is the same".

  **`pspan` IS NO LONGER A DEFECT AND THIS PARAGRAPH IS HISTORY.** It read
  0.47x when written and reads **1.05x** at v0.5.421 — the band now matches the
  original's. `pulse_phase` is in this song's presets, which is the change that
  closed it. What follows is kept as the record of the diagnosis, not as an open
  item; do not re-derive from the 449/771/899 figures, which are gone.

  THE REAL DEFECT WAS `pspan` 0.47x — our band was 449/771/899 against the
  original's 1536/1536/1408, and the band the engine is told to sweep is
  `$800..$E00` = 1536. CAUSE: Goattracker reloads the pulse pointer at every
  note (`gplay.c:375-379`) while the player's 12-bit accumulator FREE-RUNS
  across notes. Voice 2 proves it exactly — 186 notes, 186 reset jumps of 899,
  and a band of 899, all three the same number. Our sweep gets a fraction of
  the way up and is snapped back at the next note; the player keeps climbing.
  Note gaps here are rigidly uniform (8, 8 and 16 frames), where crossing the
  band at speed 32 needs 48.

  `_pulse_triangle`'s docstring claims "The band and the rate carry over; the
  phase cannot." THE RATE CARRIES OVER; THE BAND DOES NOT, whenever notes are
  short against the sweep period. That sentence should be corrected with the
  fix. Residual not closed: per-note excursion is not exactly gap x speed
  (predicted 256/512/1024 against 449/771/899), so the arithmetic of the
  turn-around is not fully accounted for.

  RULED OUT ALREADY, so do not spend the session on it: this is NOT the
  "a rate read out of the player is per frame, every table applies it per play
  call" family that produced the v0.5.363 `_filter_entries` bug. That one moves
  only multispeed files, and `presets.json` records 5_Title_Tunes at
  **multiplier 1**, where the correction is the identity. Look at the pulse
  program's own step encoding instead — and check `--pulse` / the triangle
  pulse engine's `& $E0` step vs `& $1F` frames-between-steps packing, since
  reading one field as the other is exactly a double-rate/half-step error.

  Expect `hold` and possibly `gate` to be measurement artefacts rather than
  defects — that has now been the answer four times running (ACE_II `slides`,
  `bend`, `hold`; Action Biker `hold`, `nrun`). Census before emitting.

  `[subagent]` for the pulse census and the hold refutation; `[main]` for any
  emitter change.

## Auf Wiedersehen Monty to 99%

Requested by the listener after the note-flag fix landed. Where it stands at
v0.5.393 (`docs/FIDELITY.md`, `-t 60`, subtune traced as the PSID `startSong`):

    melody 98%   seq 97%   pitch 95%   onset 100%   retrig 1.00
    wave   75%   hold 75%  gate  48%   adsr  75%    pspan 0.98x  pphase 0.75x

Two fixes already landed on this file and both are in `presets.json`:
`note_flag`'s transposing spelling (v0.5.391 — 155 notes had been clamping to
G#7, melody 90 -> 98%) and `real_firstwave_instruments` 1..16 (v0.5.392 —
hold 0 -> 75%). THE SECOND ONE IS NOT YET SIGNED OFF: it costs seq 99 -> 97%
and pitch 97 -> 95%, and the open task
`monty-firstwave-trade-needs-a-listen` is waiting on an ear. Settle that
before chasing the remainder, because dropping it moves three of the six
numbers above.

WHERE THE REMAINING GAP IS, largest first, and none of it is melody:

* `gate 48%` is the biggest and is NOT a known format limit here. 5 Title
  Tunes' 75% ceiling came from `gplay.c:334` on a 4-call row; Monty's rows are
  not 4 calls, so the same arithmetic does not apply and the ceiling has not
  been derived. Start with `fidelity.py <file> --gate-census`, which splits by
  voice since v0.5.386 — this file was the case that motivated the split
  (voice gates read 48.06% / 56.90% / 15.08%, and voice 3 at 15% is the one to
  explain).
* `wave 75%` and `adsr 75%` are the same population seen twice, on the
  evidence of every other file this session. Census before emitting.
* `pphase 0.75x` — the pulse phase is emitted for this file only where
  `multiplier == 1`; check whether Monty is single-speed and if so why three
  of its sweeping records still open on the wrong duty cycle.

DO NOT chase `melody 98%` or `seq 97%` directly: 36 files score better and the
two points here are downstream of the firstwave trade above, so they move when
that verdict does.

`[main]` — every item writes `presets.json` or an emitter and needs a corpus
A/B; the gate census itself is `[subagent]`, read-only.

## Auf Wiedersehen Monty: the drums play four octaves too low

Listener report after v0.5.394: "Drums and perc are not there." They ARE there
— every column says so — at a pitch that makes them inaudible as percussion.

**INDEXING CONVENTION FOR EVERYTHING BELOW: 0-indexed, the convention
`fidelity.py` uses (voices 0, 1, 2).** The original MEASURED line here read
"voice 3" — that was 1-indexed (the third voice), which is voice **2** below.
State this explicitly because the re-measurement's "voice 1" is a *different*
physical voice from the entry's old "voice 3"/voice 2 — do not conflate them.

MEASURED AT v0.5.394, HISTORICAL — 60 s, both sides traced through the
harness, voice 2 (this entry's original "voice 3"):

    original   240 noise frames, frequency CONSTANT at 26700 on every one
    ours       213 noise frames, frequency FOLLOWS THE PATTERN NOTE
                                 (1404, 2501, 2807, ... median 1404)

26700 is frequency-table index **79**; 1404 is index **28**. Fifty-one
semitones — four octaves and a minor third — below where the drum belongs.

**THE DEFECT MOVED RATHER THAN CLOSED. Re-measured live at v0.5.434**, same
60 s harness trace, both voices, raw noise-frame frequencies:

    voice 2  original  210 frames, CONSTANT 26700 (entry 79)
             ours      209 frames: 26707 x179, then 1404 x16, 1250 x6,
                                   993 x4, 835 x4
    voice 1  original  420 frames, 16 distinct values spanning 4112-16547
             ours      413 frames, 5 distinct: 12604 x140, 8412 x121,
                                   5299 x70, 4206 x60, 16824 x22
    voice 0  no noise on either side

Voice 2 — the voice this entry was written about — is now mostly RIGHT: 179 of
209 frames sit on the original's constant, and **30 frames remain wrong** (not
22; 179 + 22 does not equal 209, and the 22 was propagated through two records
before anyone added it up). Those 30 are spread over FOUR wrong values, not
one.

**Voice 1 now carries the defect, and it is a different defect.** Ours puts
140 frames at 12604, 70 at 5299, 60 at 4206 and 22 at 16824, against only 121
near the original's cluster — 292 of 413 wrong. But note what the original's voice 1 actually
does: **16 distinct pitches from 4112 to 16547, i.e. it FOLLOWS THE MUSIC.**
It is not a fixed-pitch drum like voice 2's, so the voice-2 story — "the
original holds one constant and we follow the pattern note" — is NOT the story
here, and an attempt to fix voice 1 by pinning a constant attack pitch would be
wrong by construction. What is wrong on voice 1 is that we sound 5 distinct
pitches where the original sounds 16.

A run that trusted "do not re-derive" and started from the v0.5.394 figures
alone would have spent itself hunting a bit-`$40` reader for voice 2, where 30
frames are at stake, instead of voice 1, where 292 are.

NO COLUMN CAN SEE THIS, which is why it took an ear. `noise` counts frames
(634/660, 96%), `nrun` compares run LENGTHS and is position- and
pitch-independent (1.00, 4 of 4 instruments matched), `melody` reads the note
NAME at an attack. CLAUDE.md already records the blind spot — "no report column
sees a noise frame's pitch" — and this is the first time it has cost a listener
report rather than a silent regression.

WHAT IS KNOWN ABOUT THE MECHANISM:

* The two drum records are 0 and 3 (`00 02 41 09 B9 00 30 64` and
  `00 02 41 0A F9 00 50 64`). Both carry effect byte **`$64`** = bits `$04`,
  `$20` and **`$40`**.
* `det.effect_bit40` is **True** for this file — CORRECTED, measured at
  v0.5.435 and re-verified live at v0.5.437. This bullet previously said
  **False**, "detection found no bit-$40 reader in this player", and every
  bullet under it was reasoned from that. The reader IS found and IS used:
  `goatwriter._fixed_attack_note(sid, det, i)` returns **207** (= note 79 |
  `0x80`) for records 0 and 3, and `None` for the other six — i.e. exactly the
  two drum records above, at exactly the frequency-table index 79 this entry
  identifies as where the drum belongs. So do not go hunting a reader; it is
  already located and already emitting.
* WHAT IS ACTUALLY MISSING IS A DIFFERENT THING, and conflating the two is
  what produced the wrong bullet. `det.effect_byte_address` is **None** on
  this file (measured at v0.5.437), which is the PER-RECORD effect byte, where
  `effect_bit40` is a FILE-level flag saying the player reads the bit at all.
  CLAUDE.md's rule cuts the other way from how this entry used it: "a
  detection flag about a player is not a fact about a record" — here the
  player-level flag is true and the record-level address is the unlocated one.
* THE LIKELY REASON `_effect_byte_address` FINDS NOTHING (re-pointed, not
  removed — the observation is sound, only its subject was wrong): this player
  reaches its instrument records **through a pointer**, not indexed loads, so
  `_effect_byte_address` has nothing to anchor on. That is the same shape as
  `INSTRUMENT_INDEX_SHAPE`, which exists because "a player that reaches the SID
  through subroutines matched none of them". The scan figure this bullet used
  to quote is NOT restated here, because it was recorded alongside the false
  claim and has not been re-measured.
* `--sfx-drum` is NOT the fix: forced on, voice 2's noise pitch was unchanged
  (213 frames, median 1404, byte-identical trace) — measured at v0.5.394, and
  written there as "voice-3" in the 1-indexed convention this entry has now
  dropped. Not re-checked since, and voice 1 was never tested this way at all.

WHERE TO START — REWRITTEN at v0.5.437, because the old text was premised on
the same false claim as the bullet above and pointed at work that is already
done. It read: "find how this player loads a record ... then look for the
bit-6 test near the frequency write." There is no reader left to find:
`effect_bit40` is True and `_fixed_attack_note` already returns 207 for the two
drum records. Start instead from **which source is wrong for voice 1**, whose
292 wrong frames are the ones at stake — the fixed attack pitch is already
correct for voice 2's constant-pitch drum, and voice 1 FOLLOWS THE MUSIC, so a
fixed pitch is wrong there by construction. The still-true caution from the old
text, kept because it is about the general scan and not about this file:
`BIT`/`BVC`/`BVS` is invisible to an `AND #$40` scan, which is how bit `$40`
went unread across the whole project once already.

DO NOT guess an emitter change from the symptom. The fix is a fixed attack
pitch on two records, and CLAUDE.md records that emitting bit `$40`'s pitch on
the wrong FRAME cost Pandora 281 frames at a wrong pitch and took melody
85% → 39% on the balloon song. Measure the original's per-offset-from-attack
profile before emitting anything.

`[main]`, opus — spans detection and emission, and a plausible-but-wrong answer
is both cheap to produce and inaudible to every column.

## Auf Wiedersehen Monty: voice 2 enters 15 frames early at 38 s (the row is 3.0236 frames, we emit 3)

A listener: "monty around 38 second voice 2 is not fidelity", with voices 1 and
3 reported as sounding good.

DIAGNOSED EXACTLY, and the prediction matches the trace to the frame. Voice 2
plays the RIGHT notes, in the RIGHT order, with the RIGHT instruments and the
RIGHT spacing -- it is 15 frames (0.30 s) early. It rests from 26.6 s and the
original re-enters at 38.74 s where we enter at 38.44 s.

    subtune 0   frames_for 3   exact_row 384/127 = 3.0236   effective 3

`MAX_ROW_DENOMINATOR = 10` refuses a denominator of 127, so `effective_frames`
falls back to 3 and we lose 0.0236 frames a row. At 38 s that is 1900 x 0.78%
= 14.8 frames predicted against 15 observed. `--pace` reads the same thing from
the other end: ratio 1.000 over 436 gaps (the row length is right) with
**drift -9.30 frames/1000, 27.8 frames early across 2987**.

Visible in the gap histograms as the original spending gaps we never spend:

    orig  6x8  7x2  12x76  13x6  24x45  25x10  605x1
    ours  6x10      12x83        24x55         600x1

An 8-row note is 8 x 3.0236 = 24.19 frames, so siddump prints 24 most of the
time and 25 about 19% of the time -- observed 10 of 55, i.e. 18%. All three
voices carry it (16/19/19 off-grid gaps in the original, 0 in ours).

THE TEMPO LEVER IS EXHAUSTED, checked rather than assumed: 3 is the best
rational approximation to 3.0236 at EVERY denominator up to 10 (the next
candidate, 31/10, is three times worse). The exact row needs `-S127`, which is
the same refusal IK+ gets for 3 x 113/112 wanting `-S112`. So this is the
documented `drift = -1/(skip+1)` limitation with a number on it, not a new
defect, and CLAUDE.md already says of it: **the fix is re-gridding, not a
tempo.**

WHY VOICE 2 AND NOT 1 OR 3. All three drift identically, so they stay in sync
with EACH OTHER and the tune merely runs 0.78% fast -- which is inaudible.
Voice 2 is the one reported because it re-enters after a 12.1-second rest at
38 s, and an entry after a long rest is where an accumulated 0.3 s offset is
audible against voices that never stopped. The defect is global; the SYMPTOM is
wherever a voice re-enters late in a section.

THE FIX, if it is wanted: re-gridding. One extra frame every 42.3 rows absorbs
the drift exactly -- a row given `CMD_SETTEMPO 3` (4 calls, gplay.c:325 makes a
row last tempo+1) instead of 2 (3 calls), on 1 row in 42. It is expressible in
the format we already emit and needs no new player state.

Three hazards, all already recorded in CLAUDE.md and all of which have bitten:
  * it consumes the command column on the rows it lands on, so it must declare
    itself in `patterns.TEMPO_OVERWRITABLE` and `ONE_SHOT_COMMANDS` -- the pair
    that has caught three changes, and row 0 belongs to the subtune's clock;
  * a `CMD_SETTEMPO` under $80 sets all three channels and Goattracker's
    patterns are GLOBAL, so a compensating row in a shared pattern is played by
    every subtune that reaches it (the v0.5.330 `apply_tempos` defect);
  * no column in FIDELITY.md measures cumulative drift -- `melody` is a difflib
    ratio, `retrig` and `--pace`'s ratio are both satisfied by a tune running
    0.78% fast forever. `--pace`'s `drift` line is the only instrument that
    reads it, and it is not a report column. Build the column or A/B on
    `--pace` output; a flat table here would mean nothing.

Population: every file whose `exact_row` has a denominator over
MAX_ROW_DENOMINATOR. Census it before building -- 37 corpus files drift and 29
do not, per CLAUDE.md, so this is not a one-file fix.

[main], touches python/h2g/patterns.py, python/h2g/goatwriter.py,
python/h2g/convert.py, python/tests/test_pace.py.
