# TODO

Hand-written, unlike `whats-next.md` (a session handoff) and
`.claude/tasks/whattask.json` (generated, and rewritten whole by `/whattask`).
`/whattask` reads this file as one of its sources, so an item here survives a
replan and reaches the next plan on its own.

Keep items actionable: what to run, and what makes it done.

## Open

- **PRIORITY (user, 2026-11-09): IK_plus first among the sub-99% songs.** It
  reads gate 58%, wave 65%, instr 35%, onset 75%, adsr 76% and aud .8718 at
  v0.5.654, with melody and hold at 100%. Three of the "Sub-99% mechanisms"
  entries below name it. The largest is "Instr: IK_plus (35.3%) never sounds
  the original's noise tick": 1333 of its 1888 unmatched notes. The others are
  the attack scatter (gate M5, wave onset jitter) and the `$08` test-bit
  parking (wave/hold deselect, 2320 frames). Work the noise tick first, then
  re-measure the other two on top of it. Earlier IK_plus attempts are closed
  in `.claude/tasks/closed.jsonl` (`explain-why-parking-08-on-ik-plus`,
  `ik-plus-rest-toggle-search`, `ik-plus-record2-program-stop`), so read those
  before re-trying the parking. Plan task: `ik-plus-sub99-priority`.

  added: 2026-11-09

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

  **CORRECTED, and the function name above was wrong too.** The sentence
  "The band and the rate carry over; the phase cannot." lived in
  `_pulse_tri_program`'s docstring, not `_pulse_triangle`'s --
  `_pulse_triangle` is the shared triangle-shape helper both pulse engines
  call, and the per-file approximation and its measurement belong to the
  caller that owns this file's engine. **It was rewritten at v0.5.379**: THE
  RATE CARRIES OVER; THE BAND DOES NOT, whenever notes are short against the
  sweep period, and `_pulse_tri_program`'s docstring now carries this file's
  own figures (449/771/899 against 1536/1536/1408) and voice 2's exact proof
  in place of the old sentence. `_pulse_triangle`'s own docstring now states
  the same rule for a reader who lands there instead, pointing at
  `_pulse_tri_program` for the measurement. **ONE RESIDUAL STAYS OPEN, do not
  close it without deriving it**: per-note excursion is not exactly gap x
  speed (predicted 256/512/1024 against the measured 449/771/899), so the
  turn-around arithmetic is unaccounted for.

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

- **DONE (v0.5.604, 2026-10-25): the full suite runs in ~14 minutes.**
  `python -m pytest tests/ -n 12 --dist worksteal` (from `python/`, needs
  `pytest-xdist`, installed 3.6.1) took 834.89 s on a quiet machine against
  3079.86 s serial at the same tree: 7148 passed, 25 skipped in both, with the
  same skip locations; 0 failed. The floor is one test --
  `test_instrument_bound.py::test_every_search_combination_of_the_fullest_files_converts`
  takes 417 s alone -- so more workers buy little. `tests/conftest.py` makes
  `sound.render_cached` take a lock file in the cache directory under xdist,
  because the cache writes its WAV in place and two workers could otherwise read
  each other's half-written render; a serial run is untouched. No assertion was
  changed and no cache was added. A plain `python -m pytest tests/ -q` still
  works and still takes ~51 minutes.

  added: 2026-10-24

- **Keep the heard-instrument census current: restage `build/listen` and re-run
  `heard.py` after each converter or presets commit.** `python/heard.py` scores
  the pairs staged in `build/listen`. Those were staged from the v0.5.621 builds,
  so after the v0.5.623 `aligned_firstwave` adoption (six songs) its `instr`
  figure describes conversions that no longer ship. The last census was taken
  at 65c516a over those pairs: 169,881 notes, `instr` .612. Nothing in the plan
  refreshes it, so the measure behind "instrument decoding is the gap" goes
  stale silently.

  ```sh
  cd python
  cp ../build/heard.json C:/t/heard-refresh/prev.json   # keep the previous census
  # one process per shard, I = 0..5, then join their notes (MEASURING.md § Listening)
  python listen.py <sid_dir> --all -t 180 --presets ../presets.json --from-json ../build/fidelity.json --shard I/6
  python listen.py --merge-notes
  python heard.py <sid_dir> --json ../build/heard.json
  ```

  Run it after the FIDELITY refresh that follows the commit: `listen.py` stages
  from `build/fidelity.json`, so staging before that refresh reads the old
  builds. Use `-t 180`, the window the current staging and the census used.
  Do not use `--traces-only`: it is faster, but it leaves the old WAVs beside
  the new `.sid` files, and the listening pages would play stale audio. Needs
  `python/tools/magplay-rt` built (its README). Traces are cached by file bytes
  in `build/heard/`, so only the moved conversions are re-traced.

  Done when each staged `build/listen/<song>.h2g.sng` hashes (sha1, first 12 hex
  characters) to its `output_sha` in `build/fidelity.json`. Then
  `C:/t/heard-refresh/delta.md` lists every song whose `instr`, or any CORE
  attribute count (gate/wave/ad/sr_hi/pitch), moved against `prev.json`, with
  before and after. A song whose `instr` fell is named as a regression to
  attribute.

  `[main]`: it rewrites `build/listen` (a plan hazard), plus `build/heard/` and
  `build/heard_census.md`.

  added: 2026-10-29

- **A/B pages, from MagPlaySID's ideas (`docs/MAGPLAYSID-ANALYSIS.md`
  § 4): five page features.** All of them are `python/abpage.py` work, pinned
  in `tests/test_abpage.py`. Each one is done only when a rebuilt page renders
  in a real browser (Playwright) with no console errors, on Commando and on one
  multispeed song. Ordered by cost:

  1. **The heard score on the pages.** An `instr` column in the index, sortable
     like the others. On each song's page, a card with that song's attribute
     counts (gate/wave/ad/sr_hi/pitch; the known-equivalent ones apart) and its
     worst paired notes: time, voice, and which attributes differ. It reads
     `build/heard.json` (`python heard.py ... --json`), so it needs the refresh
     task's census first, and it shows `-` where a song has no row. Needs no
     design pass. `[subagent]`.
  2. **A live spectrum and oscilloscopes while a pair plays.** The page already
     has a static "Both sides, by frequency" spectrogram. This adds a WebAudio
     `AnalyserNode` on each `<audio>` element, drawn per animation frame, with
     original and ours overlaid. It must work on pages served by
     `build/listen/Listen.cmd` (`abpage.serve`, port 8730), and must not break
     a page opened directly from disk. Needs no design pass.
     `[subagent]`.
  3. **A side-by-side piano roll, original against ours.** `notes_strip_card`
     says outright that it has no per-note timeline to draw. **Needs a design
     choice first**, between two data sources:
     - add `freq` to `listen.trace_json`, which that function's docstring
       drops on purpose because frequency changes every frame and would dominate
       the file;
     - or emit `heard.notes` per song (start frame, held pitch, voice) as a
       sidecar JSON beside the page.

     The sidecar is the smaller change, and it is already paired note to note.
     `[subagent]` after the choice.
  4. **An instrument panel that lights each wavetable step as it plays.** It
     builds on `tracker_card` / `row_schedule` (which rows play when) and
     `songview.wave_program` (each step's first and last call). **Needs a design
     pass first**: how a step's call range maps to the audio clock at -S>1, and
     which voice's step to light when the selector shows all three. `[subagent]`
     after the design.
  5. **The original shown as a tracker**, beside our GoatTracker view, from
     MagPlaySID's own transcription (`MagPlay.Transcribe.Music`: notes,
     instruments, patterns). **Needs your decision first:** it means
     `tools/magplay-rt` emitting that score as JSON and the pages showing a GPL
     tool's output. It is also the largest of the five. Leave it until 1-3 have
     proved useful. `[user]` then `[subagent]`.

  added: 2026-10-29

- **Sharpen `heard.py` with four of MagPlaySID's rules, before attributing more
  shapes.** These ideas come from a review of MagPlaySID's source on
  2026-10-29. They are re-implemented here, not copied (GPL). Line numbers are
  MagPlaySID's, under `src/`:
  1. **Pitch in several forms.** Each frame's pitch is held as relative to the
     note, absolute note, offset from the note's frequency, and raw frequency;
     two frames agree if any form matches (`MagPlay.Transcribe/Music.cs`
     545-548, 656-667, 724-742). Report `pitch` split into "relative differs
     but absolute agrees" and "differs in every form". `pitch` is the largest
     attribute (25.4% of notes at 65c516a), and part of it may be a naming
     artefact, such as a fixed-frequency drum noise frame.
  2. **No pitch reading on silent frames or in the release.** A silent frame
     (test bit set, or no waveform) takes the next frame's pitch, and pitch is
     read only while the gate is on (`MagSid.Core/SidImport/SidTranscriber.cs`
     1143-1157, 1178-1184, 1505-1513).
  3. **Restrikes are not new notes.** A gate that is on for at most 2 frames,
     then off for at most 2 frames, with the waveform running and the envelope
     unchanged, is one note striking twice (`SidTranscriber.cs` 263-325).
  4. **Gate-off inside the program, compared to the end of its release.**
     A gate-off inside the note's first row, except its last 2
     frames, belongs to the instrument. The note is compared only up to
     gate-off plus the release time, or up to the first silent frame
     (`SidTranscriber.cs` 1124-1140, 1233-1238). This is the `tail_len`
     versus `gate` split that `docs/MAGPLAYSID-ANALYSIS.md` lists as not done.
  5. Optional: **vibrato told from a slide** (`SidTranscriber.cs`
     1442-1496), so a vibrato wobble stops counting as `pitch`.

  Done when each rule has a synthetic test in `tests/test_heard.py` that fails
  with the rule removed, and a census over the staged pairs is written to
  `C:/t/heard-measure/` (traces cached there too, `-o` there, never
  `build/heard_census.md`). For each attribute, the census gives before and
  after, and names the songs where `instr` moved by more than 2 points.
  `[subagent]`.

  added: 2026-10-29

- **Drums on fixed notes versus drums that move with the note: does our
  converter choose the same as the original?** Group the original's notes by
  control-byte sequence plus envelope. A family whose pitch steps are the same
  on different row notes is a drum on fixed notes; one whose strike shifts with
  the note is relative (MagPlaySID `SidTranscriber.cs` 992-1031, 1098-1116).
  Compare each Hubbard record's verdict against the fixed-or-relative choice
  our wavetable makes for it (`goatwriter/drums.py`, `wave_program.py`,
  `wavetable.py`). A mismatch is a candidate cause of the "noise frame played
  as tone" and attack-pitch shapes. Done when `C:/t/drum-fixed-relative/finding.md`
  lists, per song, every record where the two disagree, with the record's
  bytes, the trace evidence, and the emitting function. Findings only.
  `[subagent]`.

  added: 2026-10-29

- **Listening pages: make each song's A/B page 50% wider.** The user asked
  for it after the new cards landed (piano roll, live spectrum and scope,
  wavetable-step panel, worst-notes list), which are cramped at the current
  width. The song page's `.wrap` is capped at `max-width:62rem`
  (`python/abpage.py`); 50% wider is 93rem. The index already uses
  `.wrap.wide` (96rem) and stays as it is (user, 2026-10-30). Keep the phone
  layout working. Done when a test in `tests/test_abpage.py` pins 93rem on a
  song page and 96rem on the index, fails with the change reverted, the pages
  are rebuilt (`python abpage.py`), and Commando's page, served, renders at
  the new width with no console errors. `[main]` (rebuilds `build/listen`).
  touches: rw:python/abpage.py, rw:python/tests/test_abpage.py, rw:build/listen

  added: 2026-10-30

- **Nineteen: emit the hi-hat's per-frame band-pass toggle.** The original
  player's hat code at `$94DD` writes cutoff `$60` and mode `$2F` (band-pass)
  on each hat frame, then low-pass on the next. That makes 66 band/low pairs
  per 400 frames. Our conversion never leaves low-pass. Over 119-125 s, with
  every voice muted, the original still renders RMS .0354 from the filter
  alone, while ours renders .0002. Removing the toggle from the original, as an
  oracle edit, raises aud from .9082 to .9157 over the whole song and from
  .851 to .864 over 117-124 s. That is the ceiling an emitter could reach. No
  emitter has been tried. A Goattracker filter-table row firing in phase with
  the hat is the obvious route, and whether it can fire in phase is the open
  question. Evidence: `C:/t/nineteen-aud-dip-117/finding.md` (diagnosis of
  QUEUE `dip-nineteen-117`, v0.5.654). Done when a patch that applies to a
  fresh worktree of HEAD lifts Nineteen's aud over 117-124 s in a
  `fidelity.py -t 180 --presets ../presets.json --sound` A/B, with no printed
  column falling more than its noise. The corpus byte-hash must also name
  every file the patch moves. A finding that the toggle cannot be emitted in
  phase also counts as done. `[subagent]`.

  added: 2026-11-08

- **Corpus: lift the listening index's sub-99% columns.** The user pointed at
  `build/listen/index.html` (2026-11-08): plenty of its melody, gate, wave,
  hold and instr cells sit below 99%. The page was staged on 2026-10-31, and
  the same columns in `docs/FIDELITY.md` at v0.5.654 still read below 99% on
  most of the 81 songs not on hold:

  | column | songs below 99% | worst |
  |---|---|---|
  | melody | 6 | Sun_Never_Shines 91, Lion_Heart 92, Lakers_vs_Celtics 93 |
  | gate | 62 | Wiz 18, Dragons_Lair_Part_II 33, Mozart 35, I_Ball 41 |
  | wave | 55 | Bangkok_Knights 56, I_Ball 61, IK_plus 65, Nineteen 77 |
  | hold | 33 | eight songs at 0%, Commando among them (fixture-held) |

  The instr column comes from `build/heard.json`, dated 2026-10-30, where 77 of
  93 songs sit below 99%. Restage before reading that column:
  `listen.py --all -t 180`, then `heard.py`. Plan all five columns at once
  (user, 2026-11-08), one grouping pass per column, worst song first. Then
  merge the proposed entries into this file. For each song, name the mechanism from the trace pair
  (`fidelity.py --diagnose` first, because a low score is a claim about the
  harness until diagnose says otherwise). Then census that mechanism over the
  corpus and fix it for every song that shares it. Done when every song not
  on hold reads at least 99% in each of melody, gate, wave and hold in
  `docs/FIDELITY.md`, or carries a named reason it cannot (a refuted or
  measured-ceiling finding). A fixture-held song like Commando counts as
  carrying a reason. One `[subagent]` per column to group its songs by
  mechanism, `[main]` to merge the proposed entries into this file, then one
  `[subagent]` per mechanism. The per-mechanism entries are under
  "Sub-99% mechanisms" below (merged 2026-11-08).

  added: 2026-11-08

## Sub-99% mechanisms (from the five column passes, 2026-11-08)

Each entry below came out of the five column passes the user asked for on 2026-11-08 (gate, wave, hold, melody, instr). The evidence lives under `C:/t/corpus-<column>-column-sub99-mechanisms/` (plan.md and the per-song files). A cause that more than one column found is merged into one entry, with each column's proposal kept beneath its title.

- **Gate and wave: the first-wave `$09` test frame lands inside the original's gate-off gap.** Merged from the gate, wave column passes.

  From the gate column:

  **Gate M3: add `gate_off_firstwave_instruments` for the 14 songs whose gate
  misses are the `$09` first-wave frame.** At v0.5.654 these read gate
  Mozart 35, Lightforce 56, Pandora 62, Rasputin 74, Last_V8_C128_version 75,
  Hunter_Patrol 81, Mega_Apocalypse 81, Chimera 82, Nineteen 82, Commando 84,
  Commando_2 86, Gerry_the_Germ 86, Las_Vegas_Video_Poker 92, Zoids 94. In each
  the dominant miss is ours `$09` (gate bit set) where the original is
  gate-off, so our gate rises one frame before the original's (gate-off runs
  `o3>u2 s+0 e-1`; Hunter_Patrol 84% of 1766 runs). A copy of `presets.json`
  with `gate_off_firstwave_instruments` = 1..62 added to the song's entry,
  `fidelity.py -t 180` (no `--sound`), moved gate Hunter_Patrol 81 -> 100,
  Gerry 86 -> 100, Zoids 94 -> 100, Mega 81 -> 99, Commando 84 -> 99, Chimera
  82 -> 97, Las_Vegas 92 -> 97, Last_V8_C128 75 -> 90, Rasputin 74 -> 89,
  Nineteen 82 -> 88, Lightforce 56 -> 75, Pandora 62 -> 73, Mozart 35 -> 68, and
  hold 0 -> 100 on eight of them; melody, seq and retrig did not move. The costs
  seen: Mega onset 100 -> 90, Chimera tail 100 -> 88, Rasputin holdnf 100 -> 90,
  Nineteen holdnf 86 -> 79, Gerry ctrl 91 -> 87; `aud` was not measured.
  Mozart is a special case: its gate reads 100% one frame earlier (lag 6 of 7),
  so no lever on the `$09` byte reaches it. First read why
  `gate-off-firstwave-per-song-adoption` left these 14 out (`runs.jsonl`), and
  note `gate-off-firstwave-gate-loss` (the loss on 20 files comes from the
  note-init call's phase). Evidence:
  `C:/t/corpus-gate-column-sub99-mechanisms/plan.md` M3, `ab/m3_*.out`,
  `ab/hp_gofw.out`, `diag/Mozart.*`, `diag/Hunter_Patrol.*`. Done when each of
  the 14 is either adopted in `presets.json` with `fidelity.py -t 180 --sound`
  showing no printed column falling past its noise and gate >= 99% (or the
  Mozart ceiling written down), or carries the named column that refuses it
  (Commando counts as fixture-held). `[main]` (it writes `presets.json`).

  added: 2026-11-08

  From the wave column:

  **Wave: adopt `gate_off_firstwave_instruments` per song on the firstwave-`$09` songs where it is clean.** 13 songs lose 1.9-12.6 pp of `wave` to one
  frame per note: the init call before each attack writes `$09` (test bit,
  class none) where the original keeps the previous note's waveform. Worst
  Pandora 87.4%, then Last_V8_C128_version 89.3%, Rasputin 89.5%,
  Mega_Apocalypse 89.8%, Gerry_the_Germ 89.9%, Lightforce 90.3%, Mozart 90.3%,
  Hunter_Patrol 91.7%, Chimera 92.4%, Commando_2 93.4%, Zoids 95.6%,
  Las_Vegas_Video_Poker 98.1%, Commando 90.9% (fixture-held, and Commando_2 is
  a page of Commando.sid, so neither was forced). The other 11 were measured by forcing
  `gate_off_firstwave_instruments` 1..62 on a private presets copy at `-t 180
  --sound` (`C:/t/corpus-wave-column-sub99-mechanisms/abF/gof_vs_shipped.txt`):
  Las_Vegas_Video_Poker .981 -> 1.000, Mozart .903 -> .998 (gate .353 -> .677,
  no printed column falls), Lightforce .903 -> .990 (gate .564 -> .746, ctrl
  .988 -> 1.000), Zoids .956 -> .987 but aud .942 -> .895, Gerry_the_Germ .899
  -> .979 but ctrl .914 -> .870, Mega_Apocalypse .898 -> .973 but onset 1.00 ->
  .90, Rasputin .895 -> .942 and Last_V8_C128_version .893 -> .934 (aud and ctrl
  within .002), Hunter_Patrol .917 -> .971 (aud -.007), Chimera .924 -> .958
  (aud -.006), Pandora .874 -> .909. `no_test_restart` is not the route: it
  lifts wave on three of them and drops melody to .335-.871 on all 11
  (`abF/ab_all.txt`). Nothing in closed.jsonl records an adoption verdict for
  these 13. Done when `presets.json` carries `gate_off_firstwave_instruments`
  for each of Mozart, Lightforce and Las_Vegas_Video_Poker (and for any other
  of the 13 where `presets.py --fidelity` finds no printed column falling past
  its noise), the `-t 180 --presets ../presets.json --sound` refresh shows the
  wave rise, and the corpus byte-hash names exactly the files moved; each
  refused song carries the column that refused it. The remaining wave on these
  songs is the G mechanism below, not a failure of this entry. `[main]`
  (preset search, `presets.json` and artefact regeneration); the verdict on
  Zoids' aud drop and Gerry's ctrl drop is `[user]`.

  added: 2026-11-08

  added: 2026-11-08

- **Gate and instr: drum noise ticks are written gate-on where the original writes them gate-off.** Merged from the gate, instr column passes.

  From the gate column:

  **Gate M1: the drum noise tick is written gate-on (`$81`) where the
  original's is gate-off (`$80`), on 16 multispeed songs.** Bump_Set_Spike 73,
  One_Man_and_his_Droid 87, Thrust 87, Game_Killer 89, Thing_on_a_Spring 89,
  International_Karate 90, Last_V8 90, Phantoms_of_the_Asteroid 90, Proteus 91,
  Warhawk 91, Formula_1_Simulator 92, Spellbound 92, Devils_Galop 94,
  Monty_on_the_Run 94, Master_of_Magic 95, Battle_of_Britain 98. On Game_Killer
  98% of 1622 miss frames are `$80` vs `$81` at offset 1 (`orig 41 80 40 ...` /
  `ours 41 81 40 ...`, 3461 gate-off runs, no `$09`); Phantoms and
  One_Man_and_his_Droid are 100% that byte pair. Bump_Set_Spike's original
  drum is 3 frames of `$80`, ours 2 frames of `$81`. Forcing `drum_gate_off` +
  `drum_sustain_gate_off` on in a copy of its preset leaves gate at 73%, and
  nine of the 16 already carry `drum_gate_off` and still miss, so the existing
  drum options do not reach the tick. Related, not duplicates:
  `thrust-drum-noise-gate` (pruned as a scoring choice) and
  `heard-shapes-noise-frame-and-late-gate-attributed`. Evidence:
  `C:/t/corpus-gate-column-sub99-mechanisms/plan.md` M1, `diag/Bump_Set_Spike.*`,
  `diag/Game_Killer.*`, `attr/<song>.misses.json`. Done when a patch that
  applies to a fresh worktree of HEAD takes the tick to the original's gate
  bit and length, lifts Bump_Set_Spike and Game_Killer gate in a
  `fidelity.py -t 180 --presets ../presets.json --sound` A/B with no printed
  column falling past its noise, and the corpus byte-hash names every file it
  moves; or a measured finding that the first frame of a Goattracker note cannot
  be written gate-off. Also decide whether the tick is audible (the original's
  `$80` releases the voice; ours re-gates the envelope) -- a listening verdict
  is `[user]`. `[subagent]`.

  added: 2026-11-08

  From the instr column:

  **Instr: two-frame drum ticks are written with the gate on where the
  original has it off (7 songs, Thrust 36.3% worst).** The original's noise
  tick is `ctl 80, 80` for two frames, ours the same frames `81, 81`, same
  length and frequency: Thrust 921 of 1168 unmatched notes, Bump_Set_Spike
  1095/1265, International_Karate 561/735, Zoolook 247/262, Thing_on_a_Spring
  209/346, Deep_Strike 119/119, Commando 107/116 (fixture-held, cannot move).
  `heard.py`'s `gated_tick` exempts only a difference on the tick's first frame,
  and `wavetable._drum_tick_noise` keeps the gate on deliberately because a
  gate-off tick above -S1 releases the voice before the ADSR delay lets the
  attack start, so this is a trade-off to measure, not a plain bug. Related
  closed: `drum-release-and-adparam` (0d4a2e5),
  `the-drum-tick-leading-gate-count-is-per-file-and-nobody-knows-what-the-player-reads`
  (f0fd20c). Evidence: `C:/t/corpus-instr-column-sub99-mechanisms/plan.md` H,
  `pairs/Thrust.DRUM_OURS_GATE_LONGER.txt`. Done when a two-frame tick is
  emitted gate-off on Thrust in an A/B and the audible envelope is compared
  (`--sound`, no printed column falling more than its noise), with the
  byte-hash naming every moved file, or a finding says the second frame cannot
  be emitted gate-off without losing the attack. `[subagent]`.

  added: 2026-11-08

  added: 2026-11-08

- **Gate and instr: drum noise ticks are written gate-off where the original raises the gate.** Merged from the gate, instr column passes.

  From the gate column:

  **Gate M2: the drum noise tick is written gate-off (`$80`) where the
  original gates it (`$81`) on Knucklebusters, Delta and Sun_Never_Shines.**
  Delta's 225 miss frames are all one record (`AD$0F SR$09`, offset 2, `$81`
  vs `$80`) and 92% of its 2937 gate-off runs are exact; Knucklebusters is 50%
  that pair (one gated tick per cycle: `orig ... 11 11 81 10 80 10` / `ours
  ... 11 11 80 10 80 10`) and 46% M4's shape; Sun_Never_Shines 51%. It is the
  mirror of the M1 entry: an option that ungates every tick of a record whose
  original gates some of them. Which option decides the tick is unproven.
  Evidence: `C:/t/corpus-gate-column-sub99-mechanisms/plan.md` M2,
  `diag/Knucklebusters.*`, `attr/Delta.misses.json`. Done when the option or
  record that ungates the tick is named and Delta reads gate >= 99% in a
  `-t 180` A/B with the corpus byte-hash naming what moves, or a measured
  reason it cannot. `[subagent]`.

  added: 2026-11-08

  From the instr column:

  **Instr: drum ticks the original raises the gate on are written gate-off in
  ours, so those notes are missing (9 songs, Knucklebusters_1 53.1% worst).**
  The original's noise tick is `ctl 81`, ours `80`: the notes whose gate rise is
  that tick have no counterpart. Sun_Never_Shines 150 of 151 missing notes,
  Thundercats 111/112, Mega_Apocalypse 71/72, Bangkok_Knights 97/267 are
  exactly that; gate-diff counts Knucklebusters 243 of 275, Delta 225/226,
  Delta_13 150/151, W_A_R_Preview 96/164, Knucklebusters_1 93/159. Related
  closed: `monty-v3-surplus-drum-ticks` (a5ea6d1), `mega-apocalypse-age-gated-second-effect`
  (963d5c9). Evidence: `C:/t/corpus-instr-column-sub99-mechanisms/plan.md` I,
  `pairs/Knucklebusters_1.DRUM_OURS_GATE_SHORTER.txt`,
  `pairs/Sun_Never_Shines.MISSING.txt`, `pairs/missing_breakdown.txt`. Done
  when the drum record or flag that makes ours write the tick gate-off is named
  for Knucklebusters_1 and a patch gives Sun_Never_Shines' 150 notes their gate
  rise, with the byte-hash naming every moved file; the census over the nine
  songs must say how many of them share the record. `[subagent]`.

  added: 2026-11-08

  added: 2026-11-08

- **Gate and instr: the gate-off gap starts one frame late.** Merged from the gate, instr column passes.

  From the gate column:

  **Gate M4: the gate-off gap starts one frame late on 12 songs.** Ninja 75,
  W_A_R 77, Kings_of_the_Beach_ingame 78, Radio_ACE 79,
  Commodore_64_Music_Examples 80, Lion_Heart 83, Pygmies_Revenge 84,
  Pacific_Coast 85, Saboteur_II 86, Kentilla 90, Human_Race 93, ACE_II 94. All
  of Ninja's 2373 gate-off runs pair as `o4>u3 s+1 e+0`: the original's gap is
  4 frames, ours 3, ending together; 2369 of its 2427 miss frames are that one
  frame. Placement is right (`otime` >= 98% on all twelve). Setting
  `hard_restart_frames` 4 on Ninja in a copy of the preset leaves gate at 75%,
  so the lever `kotb-5tt-multirate-gate-diagnose` points at does not move this
  cluster; the cause is unproven. Four of the twelve carry `no_test_restart`
  (Ninja, Radio_ACE, Pacific_Coast, Pygmies_Revenge), where
  `init-call-gate-early-under-ntr` already moved the gate envelope; the other
  eight do not. Evidence: `C:/t/corpus-gate-column-sub99-mechanisms/plan.md` M4,
  `diag/Ninja.*`, `attr/<song>.runs.json`. Done when a finding names what
  starts the gate-off a frame late (the call, the counter or the option) with a
  trace pair on Ninja and a second song from the list, and either a patch that
  lifts Ninja gate over 99% with the corpus byte-hash naming every file moved,
  or a measured ceiling. `[subagent]`.

  added: 2026-11-08

  From the instr column:

  **Instr: one-frame-late gate-off (6 songs, Ninja 22.3% worst).** On Ninja,
  Pandora, Pygmies_Revenge, Commodore_64_Music_Examples, Human_Race and
  Auf_Wiedersehen_Monty the original gates a note off at note frame 4 (3 on
  Auf_Wiedersehen_Monty) and zeroes AD/SR the same frame, and ours gates off
  exactly one frame later: +1 frame on 1710 of 1710 Ninja notes, 576/576,
  318/318, 455/455, 10/10, and 220 of 225 for Pandora. Ninja has 1710 of its
  1854 unmatched notes here. It is not `hard_restart_frames`: 3 -> 4 on Ninja,
  Human_Race, Pygmies_Revenge and 5_Title_Tunes (all `max_hard_restart`)
  changes no instr and no gate count. This is the "one frame of surplus
  ringing per release" the 5 Title Tunes entry already records, found on five
  more files. Evidence: `C:/t/corpus-instr-column-sub99-mechanisms/plan.md` A,
  `pairs/Ninja.TONAL_OURS_GATE_LONGER.txt`, `pairs/gate_off_frame_orig_vs_ours.txt`.
  Done when the emitter that writes the gate-off row and the loop that
  consumes it are named with the frame count each side lands on, and a patch
  that applies to a fresh worktree of HEAD moves Ninja's gate-off to frame 4
  with instr up in a `heard.py` re-score of the restaged pair, no printed
  `fidelity.py` column falling more than its noise, and the corpus byte-hash
  naming every file it moves. A finding that the packed player cannot gate off
  a call earlier at this row length also counts as done. `[subagent]`.

  added: 2026-11-08

  added: 2026-11-08

- **5 Title Tunes: amend the open entry with the gate and instr findings.** Merged from the gate, instr column passes.

  From the gate column:

  **Gate M9: amend "5 Title Tunes fidelity" -- its gate 75% is one uniform
  gate-rise-one-frame-early, and `hard_restart_frames` 4 does not move it.**
  Not a new defect: the open entry already says "one frame of surplus ringing
  per release, and `max_hard_restart` has SATURATED it". Measured now at
  v0.5.655: all 2807 gate-off runs pair as `o4>u3 s+0 e-1` (the original's gap
  is 4 frames, ours 3, starting together, ours rising a frame early), 86% of
  the miss frames are tone-waveform ring (`40>41` 73%, `10>11` 14%), only 14% is
  the `$09` byte (so this is not M3), and `hard_restart_frames` 4 in a copy of
  the preset leaves gate at 75%. Evidence:
  `C:/t/corpus-gate-column-sub99-mechanisms/plan.md` M9, `diag/5_Title_Tunes.*`,
  `ab/5tt_hr4.out`. Done when that entry carries these three figures and the
  `gplay.c:334` arithmetic for this song's rows, or states the measured
  ceiling in one line. `[main]` (a docs edit).

  added: 2026-11-08

  From the instr column:

  **Instr: the attack frame carries the previous note's pitch on 5 Title
  Tunes (13.6% instr).** At the gate-rise frame ours still holds the old
  note's frequency (`2714` where the original has `49b8`) and the new
  frequency lands one frame later: 2370 of the 2370 pitch-different notes,
  and 95 of 199 on Trans-Atlantic_Balloon_Challenge, whose other 123 notes
  open with an empty frame (`ctl 01 fr 0000`) and put waveform and pitch at
  f+1. No other song reaches 10% on the one-frame test. 5 Title Tunes also
  carries the one-frame-late gate-off on the same notes (gate+pitch 1806,
  pitch only 564, gate only 64), so this alone lifts it to about 34%; the
  gate-off entry must land beside it. Related closed: `monty-v3-plus-one-lag`
  (87b4cf5). Evidence: `C:/t/corpus-instr-column-sub99-mechanisms/plan.md` C,
  `pairs/5_Title_Tunes.PITCH_ATTACK_FRAME.txt`,
  `pairs/pitch_lands_1_frame_late.txt`. Done when the writer of the frame-0
  frequency is named and a patch makes ours' f+0 pitch equal the original's on
  5 Title Tunes in a re-score, with the byte-hash naming every moved file; a
  finding that the first wavetable step cannot carry the note's pitch also
  counts. `[subagent]`.

  added: 2026-11-08

  added: 2026-11-08

- **Gate and instr: attack placement scatters and drifts in phase (Wiz worst).** Merged from the gate, instr column passes.

  From the gate column:

  **Gate M5: attack-placement scatter on 10 songs; split regrid's
  quantisation from the rest.** Wiz 18, I_Ball 41, Sanxion 42, Sigma_Seven 54,
  IK_plus 58, Star_Paws 65, Trans-Atlantic_Balloon_Challenge 73,
  Auf_Wiedersehen_Monty 77, Bangkok_Knights 77, Knucklebusters_1 82. `otime`
  reads 0-50% on all ten and nine carry `regrid`. On Wiz the nearest-attack
  offset of ours against the original is spread over -4..+3 frames on all three
  voices (voice 0: +1 x127, 0 x121, +2 x86, -1 x77, -2 x67 of 673) and gate at
  lag -4..+4 never exceeds 23%; no neighbouring lag of any of the ten reaches
  99%, so it is scatter and not a shift (best: Star_Paws .798 at lag -1,
  Knucklebusters_1 .866 at +1). Knucklebusters_1 is the odd member: not
  `regrid`, 334 of 335 paired attacks late, none early. Much of this is on
  record piecemeal (`aligned-firstwave-nonuniform-ntr-files`,
  `wiz-pattern-1-is-shared-by-voices`, `bangkok-knights-drift-wander`,
  `regrid-per-play-per-song-adoption`, and the open "Auf Wiedersehen Monty:
  voice 2 enters 15 frames early" entry); this entry exists to say what the
  gate column costs and to stop the ten being chased one by one. Evidence:
  `C:/t/corpus-gate-column-sub99-mechanisms/plan.md` M5, `diag/Wiz.*`,
  `attr/*.lags.json`. Done when, for each of the ten, the attack-offset
  histogram is written down with the cause that places each attack
  (row length not a whole number of frames, shared pattern, or other), and
  the share of the gate miss that a perfect placement would remove is
  measured on at least Wiz and Star_Paws. `[subagent]`.

  added: 2026-11-08

  From the instr column:

  **Instr: Wiz and Sanxion drift in and out of phase by up to 4 frames with
  exact rows.** `--pace` reads row 3.00 frames, ratio 1.000 and drift
  +0.00 / -0.33 per 1000 on both, yet the nearest-note offset per 500 frames
  moves together on all three voices: Wiz -3, -2, -1, **-4** (frames 1500-2000,
  0 of 75 notes pair), -1, 0, 0, 0, +1, +2, +1, -1, 0, **-4**: a ramp of
  about +1 frame per 500 that resets by 3-4. 488 Wiz and 867 Sanxion notes
  fall outside the 2-frame pairing slack, so Wiz reads 63.0% and Sanxion
  71.7%. A skew at pattern or section boundaries is the candidate, not shown.
  Evidence: `C:/t/corpus-instr-column-sub99-mechanisms/plan.md` F,
  `pairs/phase_offsets_by_500frames.txt`. Done when the frames where the
  original gains or loses a call against ours are located (a boundary, a
  tempo record, a `$FE`) and a patch removes the sawtooth in a `heard.py`
  re-score, byte-hash named, or a finding that Goattracker rows cannot hold
  it. `[subagent]`.

  added: 2026-11-08

  added: 2026-11-08

- **Knucklebusters_3: its subtune clock runs about 6% off, so no edge lines up.** Merged from the gate, hold, instr column passes.

  From the gate column:

  **Gate M10: Knucklebusters_3's clock runs fast, so no gate edge lines up.**
  Gate 49: `drift` -58.8 per 1000 (160 frames across 2720, the corpus worst
  in `FIDELITY.md`'s Summary); attack counts are equal (481 / 481) but the
  nearest-attack offsets spread over -12..+8 on all three voices; gate by lag
  -4..+4 is flat at .490-.499; 166 of its 478 gate-off runs (35%) have no
  counterpart within 4 frames; `-S3`, 56 s window. Closed
  `dragons-lair-part-ii-tempo-remap-decision` (DL2 plays 6.25% fast, landed)
  is a sibling by size only (-5.9% here); no record names the cause. Evidence:
  `C:/t/corpus-gate-column-sub99-mechanisms/plan.md` M10,
  `diag/Knucklebusters_3.*`. Done when a finding names the call-rate or
  tempo source of the -58.8/1000 for subtune 2 (`fidelity.py --pace` on
  Knucklebusters_3 read at its median, per CLAUDE.md) and a fix brings
  `drift` inside the corpus norm with gate re-measured in a `-t 180` A/B, or a
  measured reason it cannot. `[subagent]`.

  added: 2026-11-08

  From the hold column:

  **Knucklebusters_3 ticks 1/17 early: can its row be packed corrected?**
  Subtune 2 of Knucklebusters.sid reads `hold` 29% at -S3 with melody 100%,
  retrig 1.00, `drift_per_1000` -58.8235 (exactly -1/17, the outer gate's
  skipped call with skip 16), `len -3.1 s`, 160 frames across the 56 s window.
  Its census is five `slot` and two `match`: $DCAD one 204-frame note, ours 192;
  $2A7B 16 of 32 notes and $48C9 25 of 45 unpaired within 12 frames; $0C09 -18 on 10
  notes and -26 on 8. $00F8 (240 notes) agrees 100% on sorted slot, an M2 flip,
  so the hold loss is the clock and not the notes. `FIDELITY.md` states the cause
  for 8 files: `effective_frames` declines to correct when the corrected row
  cannot be packed. Prior art: `sanxion-and-knucklebusters-end-2-4-s-early-under-presets`
  (done 760f401), `multiplier-does-not-explain-slot` (the later-subtune-clock
  exception in `pack_subtune`), `rasputin-clock-drift`. Find, for this subtune,
  the row value `effective_frames` would need and the exact packing limit that
  refuses it (a CMD_SETTEMPO range, a 256-byte pattern, the multiplier's
  divisibility), by running `convert` on subtune 2 with the correction forced
  and reading the refusal. Done when that refusal is named with its line, and
  either Knucklebusters_3 reads `drift` 0.0 and `len` within 5 s with `melody`,
  `retrig` and `wave` not falling more than their noise and a corpus byte-hash
  naming every file the patch moves (the other seven `-1/(skip+1)` files are
  expected movers), or the correction is recorded as impossible at the packed
  player with the bound. `[subagent]` for the refusal, `[main]` for any change.
  touches: r:python/h2g, r:python/fidelity.py, r:presets.json, r:build/fidelity.json

  added: 2026-11-08

  From the instr column:

  **Instr: Knucklebusters subtune 2 runs 6% slow.** The listening page
  Knucklebusters_3 (`Knucklebusters.sid` subtune 2, 56 s) has equal note
  counts (79/161/241) but 301 of 481 notes unpaired: `--pace` at -m3 reads
  ours/theirs 0.941, drift -58.82 frames/1000, 160 frames early over 2720.
  `FIDELITY.md` has no row for this subtune (its Knucklebusters row is
  subtune 1); the closed `knucklebusters-subtune0-underplay` (862f703) is the
  same file's other subtune. Evidence:
  `C:/t/corpus-instr-column-sub99-mechanisms/plan.md` E,
  `diag/Knucklebusters_3.pace.txt`. Done when the row-length error (2.12 frames
  against 2.26) is traced to the tempo or gatetimer record that produces it and
  a patch brings `--pace` to within its noise on subtune 2 with the byte-hash
  naming every moved file. `[subagent]`.

  added: 2026-11-08

  added: 2026-11-08

- **Wave and hold: the original deselects the waveform at a note end and ours keeps it selected.** Merged from the wave, hold column passes.

  From the wave column:

  **Wave: the original deselects the waveform and ours keeps ringing on 3 songs
  (9 more carry it).** Kings_of_the_Beach_ingame 96.6% (the 36 frames after the
  original writes `$00` on every voice at frame 345; already diagnosed in
  closed `silent-park-final-waveform-zero` and `fbs-kotb-ingame-rest-wave-silence`),
  Tarzan 97.6% (original `$01` gate-only for 326 frames and `$00` for 147 where
  ours holds `$19/$18`), ACE_II 98.2% (original `$08` test bit from frame 1709
  for about 362 frames, ours `$40`). The same original bytes sit under the
  second mechanism of Bangkok_Knights (`08` 2559 frames), IK_plus (`08` 2320),
  Trans-Atlantic_Balloon_Challenge (`00` 1150, `08` 552), I_Ball (`01` 566, `08`
  345), Nemesis_the_Warlock, Nineteen, Chain_Reaction, Star_Paws and Pandora.
  This can be audible, because ours rings through its release. The option that
  targets it, `rest_wave_silence`, is adopted on zero songs, refused on Pandora
  ($0C99), does not reach Kings_of_the_Beach_ingame's lead and is defeated by a
  looping wavetable (closed `rest-wave-silence-is-adopted-on-zero-songs-and-the-shared-schedule-makes-it-worth-re-searching`,
  `pandora-0c99-rest-wave-silence-alone-cuts`, `looping-wavetable-defeats-rest-wave-park`).
  Evidence: `C:/t/corpus-wave-column-sub99-mechanisms/plan.md` section L,
  `diag/ACE_II.diag.txt`, `traces/ACE_II.*`. Done when a patch that applies to a
  fresh worktree of HEAD makes ACE_II and Tarzan select no waveform on the
  frames where the original does, lifting their `wave` over .99 in a
  `fidelity.py -t 180 --presets ../presets.json --sound` A/B with no printed
  column falling more than its noise and the corpus byte-hash naming every file
  moved, or a finding shows which of the two cannot be reached and why.
  `[subagent]`.

  added: 2026-11-08

  From the hold column:

  **Hold column: the original ends five songs' notes with `$00`/TEST, ours leaves
  a waveform selected.** Mega_Apocalypse $0CFC (voice 2, two notes): `$D404` goes
  `$14` at frame 382 and `$00` at 385 in the original, so it sounds `held 192`
  of a 768-frame slot; ours writes `$14` and nothing more, `held 767`
  (`delta +575`, `thin`). Auf_Wiedersehen_Monty $0ADF: orig `held 581`, tail
  `8 8 8`; ours `held 968`, tail `10 10 40`. Thundercats $07B7: the 16-frame
  slots end `40 40 8 8 8 8 8` in the original and `40 40 40 40 40 40 40` in ours
  (note-level held +5 on 47 and +6 on 22 of 251). Trans-Atlantic $0AF8 (140
  notes, `rest_program_stop` already on): orig `11 11 11 11 11 0 0 ...`, ours
  `11 11 11 11 11 18 18 ...` and `$18` is triangle plus TEST, silent, which
  `wf & 0xF0` counts as sounding. Chain_Reaction $09F9: the last slot frame is
  `0` against ours `18`/`10`, `long +1` on 132 of 197 at -S3. Songs:
  Mega_Apocalypse 10, Trans-Atlantic_Balloon_Challenge 89, Auf_Wiedersehen_Monty
  90, Chain_Reaction 90, Thundercats 91. The gate is off on every one of these
  frames, so the difference is a release tail; `wave` already exempts it
  (`wave_tail_frames`, `wave-column-charges-a-latched-waveform-after-the-tune-ends`)
  and `hold` does not. Two steps. First make `sound_note_runs` treat a frame with
  the TEST bit set, or with the gate off after its release has run out, as not
  sounding (the same predicate `wave_tail_frames` uses), and re-read the five.
  Then, only for what still reads below 99%, A/B `rest_wave_silence` /
  `rest_program_stop` per song; `pandora-0c99-rest-wave-silence-alone-cuts` and
  `add-rest-program-stop-true-to-the` (refused for IK_plus, Bangkok_Knights,
  I_Ball) say the emitter side has cost before. Done when the five rows are
  re-read under the new predicate with before and after beside each, a test pins
  a `$18` frame and a gate-off tail past release as not sounding, `hold`'s own
  figure for every other file is byte-identical or each mover is named, and any
  emitter A/B is recorded as adopted or refused with the column that falls.
  `[subagent]` for the predicate and the re-read, `[main]` for regenerating
  `FIDELITY.md` and any preset change.
  touches: rw:python/fidelity.py, rw:python/tests/test_fidelity.py, r:python/h2g, r:presets.json, r:build/fidelity.json

  added: 2026-11-08

  added: 2026-11-08

- **Wave and instr: noise runs and noise ticks are one frame short or early.** Merged from the wave, instr column passes.

  From the wave column:

  **Wave: our noise runs are one frame shorter than the original's on Thrust
  and Spellbound.** Thrust 97.6%: of 869 matched noise runs ours starts on the
  same frame in all and is one frame shorter on 31% (3-4 frames shorter on
  5%); Spellbound 98.4%: 1597 runs, 20% one frame short. Only 36 and 22
  original noise runs have no counterpart, so it is length, not missing
  drums. This is the known next-note fetch -1 (closed
  `fetch-minus-one-shows-up-in-three-columns`,
  `the-fetch-deficit-eats-the-last-frame-of-every-note-at-s1-and-nothing-has-tried-to-close-it`),
  now measured on the wave column for these two. Commando_2 shows it on 702 of
  702 runs but is a Commando.sid page and fixture-held. Done when the shorter
  runs are traced to the instrument records that produce them (`--hold-census`
  on both songs), and a patch that applies to a fresh worktree of HEAD lifts
  Thrust's `wave` over .99 and Spellbound's over .99 in a `fidelity.py -t 180
  --presets ../presets.json --sound` A/B, with no printed column falling more
  than its noise and the corpus byte-hash naming every file moved; or the
  fetch -1 is recorded as a measured ceiling for these records. `[subagent]`.

  added: 2026-11-08

  From the instr column:

  **Instr: the noise tick is one frame short or early in ours (6 songs,
  Commando_2 54.2% worst).** Commando_2 original `80,80,80` then sawtooth,
  ours `80,80` then `20` (564 of 564 unmatched, all voice 1); Proteus and
  Warhawk (-S7) and Spellbound (-S5) original `80,80`, ours `81,40`, i.e. a
  missing second noise frame once the exempt first-frame gate difference is
  set aside (204/442, 179/389, 270/330); Crazy_Comets 189 notes one frame too
  long and 152 too short; Rasputin ours at f+1, original at f+2 (130 of 308).
  Commando_2 is a subtune of the byte-exact fixture, so it cannot move.
  Related closed: `nrun-outer-gate-skip-floor` (a6ccf89),
  `spellbound-sweep-gap-hr-frame` (3512e76). Evidence:
  `C:/t/corpus-instr-column-sub99-mechanisms/plan.md` J1,
  `pairs/Commando_2.WAVE_ORIG_NOISE_OURS_NOT.txt`,
  `pairs/Spellbound.WAVE_ORIG_NOISE_OURS_NOT.txt`. Done when the drum run
  length is read off the player for Proteus (the worst non-fixture song) and a
  patch gives the second noise frame, with `nrun` and the byte-hash named, or
  a finding that the multispeed noise run cannot be that long. `[subagent]`.

  added: 2026-11-08

  added: 2026-11-08

- **Gate M6: long rests are released at the hard-restart frame, not at the
  original's.** Dragons_Lair_Part_II 33, Tarzan 82, Hollywood_or_Bust 97.
  Tarzan: 92% of 2740 gate-off runs are exact, and the 8% that are not
  (`o9>u3 s+6`, `o15>u3 s+12`, `o33>u3 s+30`) hold 1992 of its 2155 miss
  frames -- ours releases in the last 3 frames before the next note, the
  original at the start of the rest. Hollywood_or_Bust: 12 runs of 3251 carry
  all 168 miss frames. Dragons_Lair_Part_II is the same shape at -S3 with the
  original's 3-frame gap shortened to 1 (`o3>u1 s+2 e+0`, 648 of 1662 runs),
  plus 24% `$01` over `$00`, and a one-sided lateness (556 late attacks, none
  early; gate .459 at lag +1). This is the record
  `the-conversion-emits-no-rest-for-the-players-release` ("every gate-off
  stretch we emit is the hard restart, a constant, where the player rests 8 to
  1069 frames"), which has no reason text. Evidence:
  `C:/t/corpus-gate-column-sub99-mechanisms/plan.md` M6, `diag/Dragons_Lair_Part_II.*`,
  `attr/Tarzan.runs.json`. Done when the rest's start is emitted as a release
  for Tarzan and Hollywood_or_Bust (gate >= 99% with no printed column falling
  past its noise, corpus byte-hash naming every file moved), and Dragons_Lair
  is either lifted or carries its measured reason. `[subagent]`.

  added: 2026-11-08

- **Gate M7: Nemesis_the_Warlock holds `$01` where the original is parked at
  `$00` -- decide whether to emit `$00`, or score it as inaudible.** Nemesis
  gate 59: 61% of its 3356 miss frames are ours `$01` over the original's
  `$00` (voice 0, frames 0..32 and 1362..1402: `orig 00 00 00 ...` / `ours 00
  01 01 01 ...`), 66% of all its misses at offset 32+ or before the first
  attack. A gate bit with waveform 0 makes no sound, so this costs the column
  and not the ear. The bytes are the free-running `$01` first wave that
  `sanxion-free-running-first-wave-adoption` gives every `gate_off_firstwave`
  adopter (Nemesis carries it; Dragons_Lair_Part_II 24% and Sanxion 8% show the
  same bytes) -- the attribution is a reading of the bytes and the flag, not a
  measurement. Emitting `$00` risks undoing the gain that adoption
  recorded (Sanxion 81-88 s .749 -> .889, from its closed title). Evidence: `C:/t/corpus-gate-column-sub99-mechanisms/plan.md`
  M7, `diag/Nemesis_the_Warlock.*`. Done when a column rule (a `gatenf`-style
  forgiveness for ours-`$01`/orig-`$00` frames, with its own blindness stated in
  `Dimension`) or an emitter change is A/B-measured on Nemesis and Sanxion,
  with no printed column falling past its noise. The choice between the two is
  `[user]`; the measurement is `[subagent]`.

  added: 2026-11-08

- **Gate M8: Delta_13 releases the gate partway through a held note.**
  Delta_13 gate 85: 1084 of 1234 miss frames are voice 0 (`AD$0C SR$99`) at
  offset 32+, in 17 runs of 32, 62 or 122 frames (frames 1140, 1380, 1620,
  2040, ...), where the original's voice stays `$41` and ours falls to `$40`
  about 12-29 frames into the note while its frequency and pulse keep moving
  (`diag/Delta_13.orig.dump` / `.ours.dump`, frames 1128..1190). The other 150
  frames are M2's `$81`/`$80` byte pair on voice 2. Probably audible (a note
  that should sustain falls into its release); not listened to. The cause is
  unproven and no record names it. Evidence:
  `C:/t/corpus-gate-column-sub99-mechanisms/plan.md` M8,
  `diag/Delta_13.diagnose.txt` (`Delta.sid --diagnose -a 12`). Done when a
  finding names what ends the gate (a pattern row, a rest, a counter) in
  `songview` terms for the first run at frame 1140 and the fix lifts Delta_13
  gate over 99% in a `-t 180` A/B with the corpus byte-hash naming what moves,
  or a measured ceiling. `[subagent]`.

  added: 2026-11-08

- **Wave: the gate-off firstwave frame writes the next note's class one frame
  early, on 16 songs.** With `gate_off_firstwave_instruments` or
  `aligned_firstwave` already adopted, the init call before an attack shows the
  next record's waveform while the original still shows the previous one (O
  `80 80 80 41*`, U `80 80 40 41*` on Phantoms_of_the_Asteroid voice 2, frames
  369-376). Share of each song's disagreeing frames: Hollywood_or_Bust,
  One_Man_and_his_Droid 100%, Lakers_vs_Celtics 99%, Delta 99%, Shockway_Rider
  95%, Pacific_Coast 93%, Formula_1_Simulator 76%, Radio_ACE 72%, Gremlins 71%,
  Last_V8 70%, Phantoms_of_the_Asteroid 62% (worst: 92.5%), Zoolook 57%,
  Crazy_Comets 54%, Chain_Reaction 52%, Chicken_Song 39%, Thundercats 35%. The
  other available spelling, the `$FF` firstwave that keeps the previous
  waveform (`no_test_restart`, gate-off off), was forced on eight of them
  (`C:/t/corpus-wave-column-sub99-mechanisms/abG/ntr.json`): wave rises on
  Phantoms .925 -> .972, Last_V8 .934 -> .980, One_Man .979 -> 1.000 but melody
  falls to .989, .759 and .202, and wave falls on Delta .983 -> .750,
  Formula_1 .952 -> .867, Lakers .975 -> .853, Shockway .969 -> .899, because
  the init call then sounds the previous note's last frequency and siddump names
  the attack by it (`docs/OPTIONS.md` `--aligned-firstwave`). So at present this
  is a measured ceiling of the two firstwave spellings. Done when either a
  patch that applies to a fresh worktree of HEAD gives the init frame the
  previous waveform without the stale-pitch attack (Phantoms_of_the_Asteroid
  and One_Man_and_his_Droid wave up, melody and gate flat, corpus byte-hash
  naming every file moved), or a finding shows Goattracker's note-init call
  cannot do it and the 16 songs are recorded as carrying that ceiling.
  `[subagent]`.

  added: 2026-11-08

- **Wave: our attacks sit 1-4 frames off the original's on 11 songs.** Worst
  Bangkok_Knights 56.4%, I_Ball 60.9%, IK_plus 65.4%, Nineteen 77.1%, Sanxion
  79.0%, Trans-Atlantic_Balloon_Challenge 83.3%, Knucklebusters_3 83.3%,
  Nemesis_the_Warlock 87.3%, Auf_Wiedersehen_Monty 90.4%, Sigma_Seven 91.6%,
  Dragons_Lair_Part_II 94.7%. Matched-attack delta against the original (nearest
  attack, all voices): Bangkok +1 53% / +2 19% / 0 12%; I_Ball -2 30% / -1 24% /
  -3 23%; IK_plus 0 24% / -1 23% / -2 18%; Sanxion spread over -3..+2; Nemesis
  -1 on about 52%; Dragons_Lair +1 on 33%. A 4-12 frame drum waveform program
  turns that into a class swap on every frame of the note (Nemesis and
  Dragons_Lair swaps sit under a displaced attack 2260 of 2260 and 945 of
  1048). No single lag shift fixes any of them (Bangkok's best per-voice shift
  gives .564 -> .685). Known sub-cause, Monty only: the fractional row
  (3.0236 frames, see "Auf Wiedersehen Monty: voice 2 enters 15 frames early").
  The causes elsewhere are not named; the first step is to name them per song
  from the offset histogram (`C:/t/corpus-wave-column-sub99-mechanisms/offs.py`
  and `plan.md`), checking against closed `rasputin-fractional-row-tempo-drift`,
  `skip-gate-song-call-phase` and `aligned-firstwave-nonuniform-ntr-files`
  before measuring again. Done when each of the 11 carries a named cause with a
  `--diagnose` and trace pair, and for each cause a patch that applies to a
  fresh worktree of HEAD moves the matched-attack delta on that song toward
  0 and lifts its `wave`, with no printed column falling more than its noise
  and the corpus byte-hash naming every file moved; or the cause is recorded
  as unrepresentable at that song's rate. `[subagent]`, one per cause.

  added: 2026-11-08

- **Wave: Star_Paws and Knucklebusters_1 sit one frame off the original after
  the first row.** Star_Paws voice 1 attacks at orig 1,10,18,26 and ours
  1,9,17,25: the first attack lines up, the original's first row is 9 frames
  and ours 8, and every later attack is one frame early (delta -1 on 80%,
  n=2803). The harness lag shifted 6 -> 5 lifts wave .768 -> .933.
  Knucklebusters_1 is the same shape the other way: delta +1 on 100% of 335
  attacks, voice 0 matches at frame 1 and voices 1 and 2 start one frame later,
  and lag +1 lifts wave .847 -> .997 (the per-frame `$80/$15` toggle runs
  anti-phase because the note starts one frame late). Whether it is the first
  row's length, a per-voice start phase, or the harness lag for these two is
  not proven. Evidence: `C:/t/corpus-wave-column-sub99-mechanisms/plan.md`
  sections P1, `diag/Star_Paws.diag.txt`, `traces/Star_Paws.*`. Done when the
  cause is named from both traces, a patch that applies to a fresh worktree of
  HEAD (or a harness change, if the lag is what is wrong) lifts Star_Paws wave
  over .93 and Knucklebusters_1 over .99 in a `fidelity.py -t 180 --presets
  ../presets.json --sound` A/B, with no printed column falling more than its
  noise and the corpus byte-hash naming every file moved. `[subagent]`.

  added: 2026-11-08

- **Wave: the original latches a waveform on a voice before its first note and
  we stay `$00` (12 songs, 4 of them the whole loss).** Pygmies_Revenge voice 0
  selects `$40` from frame 2 with the gate off and sounds first at frame 1026;
  ours is `$00` until then. Over the frames before each voice's first original
  attack the original's gate is on in 0 of them for all 12 songs, so none of it
  is audible. Frames: Pygmies_Revenge 1535, Chimera 868, Phantoms_of_the_Asteroid
  766, Master_of_Magic 766, Kentilla 634, Crazy_Comets 574, Last_V8 542,
  Last_V8_C128_version 542, Hunter_Patrol 469, Samantha_Fox_Strip_Poker 209,
  Formula_1_Simulator 159, Gremlins 143. Not charging them gives Pygmies .930 ->
  .986, Master_of_Magic .967 -> .995, Kentilla .971 -> .994, Samantha_Fox .985
  -> .9999, and lifts eight more by 0.5-2.5 pp. Two ways to close it: have the
  conversion write the init waveform, or have `wave_compare` not charge
  gate-never-risen frames and say so in the column's `Dimension` (CLAUDE.md:
  a column that documents what it ignores is a list of things you cannot ship
  on evidence, so the exclusion has to be counted in the row, as
  `wave_tail_frames` is). Evidence:
  `C:/t/corpus-wave-column-sub99-mechanisms/plan.md` section S,
  `diag/Pygmies_Revenge.diag.txt`, `traces/Pygmies_Revenge.*`. Done when the
  choice is made and, for the chosen route, the 12 songs' `wave` values in a
  `-t 180 --presets ../presets.json --sound` refresh match the figures above
  (harness route: with the excluded count printed per row), with every other
  column unchanged. The harness route touches `fidelity.py` and regenerates
  `FIDELITY.md`, so `[main]`; whether an inaudible latch is worth emitting at
  all is `[user]`.

  added: 2026-11-08

- **Wave: a per-frame noise/triangle toggle runs in anti-phase on 3 songs.**
  Knucklebusters 96.5%, W_A_R 98.0%, W_A_R_Preview 98.3% (Zoolook carries 173
  more frames under G). Knucklebusters voice 1 alternates `$80/$10` every
  frame; the original's alternation slips a phase now and then (`10 10`), ours
  never does, so every frame up to the next attack disagrees. Onsets are
  identical (matched-attack delta 0 on 99-100%) and all 784 anti-phase swap
  frames sit under the same attack on both sides. W_A_R voice 2 is the clearest:
  a free-running toggle with no attack for more than 50 frames and ours exactly
  opposite (O `10 80 10 80`, U `80 10 80 10`; 280 of 280 swap frames under a
  same-frame attack, 280 of 280 on W_A_R_Preview). Why the original slips and
  what sets its phase is not proven; a call-counter parity is the hypothesis
  (closed `the-seven-file-adc-0c-family-is-per-frame-octave-alternation-and-commando-is-in-it`,
  `rasputin-eor-toggle-emit`). Evidence:
  `C:/t/corpus-wave-column-sub99-mechanisms/plan.md` section A,
  `diag/Knucklebusters.diag.txt`, `traces/Knucklebusters.*`. Done when the
  original's toggle code is read to name what sets the phase and where it slips,
  and a patch that applies to a fresh worktree of HEAD lifts Knucklebusters'
  `wave` over .99 in a `fidelity.py -t 180 --presets ../presets.json --sound`
  A/B, with the three songs' other printed columns not falling more than their
  noise and the corpus byte-hash naming every file moved; or a finding shows the
  phase cannot be emitted. `[subagent]`.

  added: 2026-11-08

- **Hold column, fetch-only songs: name the ceiling where the column is read.**
  Eleven songs read `hold` below 99% and every instrument of each is the
  next-note fetch frame: Chimera 0 (9 of 9 `fetch`), Commando_2 0 (4), Gerry_the_Germ
  0 (10), Hunter_Patrol 0 (14), Last_V8_C128_version 0 (13), Lightforce 0 (10),
  Mozart 0 (13), Zoids 0 (11), Rasputin 10 (9 of 10), Bangkok_Knights 25 (6 of 8),
  5_Title_Tunes 86 (1 of 7); `holdnf` reads 100% on all eleven. Commando is the
  twelfth and is fixture-held. On Chimera's $0C00 (voice 0, 35 notes) the
  original holds 36 frames of a 36-frame slot and ours 35: the last frame is
  `$09`, which `wf & 0xF0` reads as not sounding. The deficit is bounded by the
  target player (`gatetimer & $3f` calls early, `player.s:1090-1098`; at -S1 a
  call is a frame; `_hard_restart_ticks` never returns 0, 3840 calls swept) and
  is priced in `closed.jsonl`: `the-fetch-deficit-eats-the-last-frame-of-every-note-at-s1`,
  `hold-at-s1-is-bounded-by-the-target-player-and-the-open-question-is-whether-it-can-move-at-all`.
  The only lever is `--no-test-restart` per song, which the preset search
  already prices. Nothing here is a converter defect; what is missing is that
  the 99% goal still reads `hold` for these songs. Make the generated report
  carry `holdnf` as the graded figure and `hold` as the ceiling for a song whose
  every non-matching instrument is `fetch`, with the song list and the reason in
  the `hold` Dimension text. Done when `docs/FIDELITY.md` marks these eleven as
  "fetch-only: graded on holdnf" and a test in `tests/test_fidelity.py` pins the
  marker on a synthetic census (all `fetch` -> marked, one `slot` -> not marked),
  fails with the change reverted, and Chimera's row reads `hold 0% (ceiling) /
  holdnf 100%`. Evidence: `C:/t/corpus-hold-column-sub99-mechanisms/plan.md` M1,
  `Chimera/hold_census.md`, `Chimera/trace_{orig,ours}.txt`. `[main]` (edits
  `fidelity.py`, regenerates `FIDELITY.md`).
  touches: rw:python/fidelity.py, rw:python/tests/test_fidelity.py, rw:docs/FIDELITY.md, rw:build/fidelity.json

  added: 2026-11-08

- **Hold column: the modal reduction mislabels nine songs whose notes agree.**
  `hold` takes the mode of each side's per-note held length and calls the
  instrument matched only if the two modes are equal. On a key with two or
  three near-equal bins, sub-frame jitter picks different winners: Wiz $0909
  (144 notes, 12/36 alternation) is {12: 65, 36: 52, 37: 20, 13: 7} in the
  original and {36: 72, 12: 54, 13: 18} in ours, mode 12 against 36, `slot +24`.
  Sorted-slot agreement within one frame is 100% on every instrument of Sigma_Seven,
  Wiz, Knucklebusters, Knucklebusters_1, Nemesis_the_Warlock, Sanxion and I_Ball,
  and 94-96% held on Pandora; the note-level held delta is within +-1 on 98%
  (Wiz), 97-100% (Knucklebusters), 100% (Sigma_Seven, Nemesis, Sanxion).
  Two more reduction limits sit in the same nine: `classify_hold` lets `slot`
  outrank `fetch` (I_Ball $09F7 and both Pandora instruments are note-level -1,
  labelled `slot`), and `held` stops at the first hole (I_Ball $0909, `gap`, slot
  multiset 100%, held 26%). Songs: I_Ball 9, Pandora 12, Nineteen 21, Sigma_Seven
  50, Knucklebusters 78, Wiz 83, Nemesis_the_Warlock 88, Knucklebusters_1 89,
  Sanxion 92. Prior art, not a fix: `sigma-seven-and-wiz-lose-half-their-hold-agreement-under-the-regrid-fix`
  (done 7969d85), `multiplier-does-not-explain-slot` (done eae8d8d). Build the
  column the note says is missing, not another census: add `holdn`, the share of
  an instrument's notes whose held length is within one frame of the paired
  note's, paired by sorted slot (n equal) or nearest attack, next to `hold`, and
  leave `hold` alone (it is an acceptance term of `fidelity_better`). Done when
  `holdn` is in the report with a Dimension text, reads at least 94% on every
  instrument named above (I_Ball $0909 stays low and is named `gap`), a test pins
  it on a bimodal synthetic key where `hold` is 0 and `holdn` is 100%, and
  `docs/FIDELITY.md` shows it. A finding that a Wiz-class flip also hides a real
  defect on any of the nine counts as done once named. `[main]`.
  touches: rw:python/fidelity.py, rw:python/tests/test_fidelity.py, rw:docs/FIDELITY.md, rw:build/fidelity.json

  added: 2026-11-08

- **Hold column: `--cut-release` splits the pairing key on Human_Race, Thrust and
  Las_Vegas_Video_Poker.** `hold` pairs instruments by ADSR key, exact first.
  Human_Race $0A09: the original has 509 notes under it; ours keeps $0A09 on 92
  and carries $0A00 (release zeroed) on 417, so the exact pair compares 509 with
  92 (note-level held is within one frame on 370 of 509 at delta 0, 139 at -8
  from the other half). Thrust $0FFF: 165 original notes, ours $0FFF on 20 and
  $0FF0 on 101; note-level delta is 0 on 127 and -1 on 38 of 165. Las Vegas
  $0A0C: ours has no note under that key at all; the release-masked fallback maps
  it to $0A00 and merges the whole $0A0x family (426 vs 426 notes, sorted slot
  within one frame on 17%, held on 0%). Songs: Las_Vegas_Video_Poker 83,
  Human_Race 86, Thrust 94. Prior art: `paired_keys` (v0.5.292), the instrmap fix in
  `cut-release-splits-the-adsr-key-so-instrument-matched-columns-lose-the-instrument`
  (done 89df05e) and `adsr-column-cannot-credit-a-fix-under-cut-release`: the
  hold reduction was not given the same treatment. Pair `sound_note_runs` notes
  across the two sides by attack (same voice, within 12 frames) and key each
  instrument on the original's key, so a key that `cut_release` splits is read
  whole. Done when Human_Race, Thrust and Las_Vegas_Video_Poker each read at
  least 94% on `hold` under the new pairing, or the remainder is named per
  instrument; a test pins a synthetic split key (orig 10 notes under K, ours 4
  under K and 6 under K & 0xFFF0 -> matched, where the exact pairing reads 0);
  and a corpus A/B names every file whose `hold` moves (expected: only files
  with `cut_release` and a split key). `[subagent]` for the reduction and the A/B,
  `[main]` for regenerating `FIDELITY.md`.
  touches: rw:python/fidelity.py, rw:python/tests/test_fidelity.py, r:build/fidelity.json, r:docs/FIDELITY.md

  added: 2026-11-08

- **Sun_Never_Shines, Pacific_Coast and Lion_Heart re-strike a long held note
  mid-note.** The cause is not found. Sun_Never_Shines $606A (voice 1): the
  original has 20 notes of {120: 8, 90: 3, 60: 3, 150: 2, 30: 2}, ours 31 notes
  of {30: 8, 90: 6, 60: 6, 120: 4, 40: 1, 15: 1}; a 120-frame note at f1412
  becomes 30 + 40 + 15 + 35 from f1418. The same file's $00C8 goes the other
  way: 300 original attacks at slot 5 (`11 81 41 41 80 | 81 40 80 80 80`)
  against 150 of ours at slot 10, so the second gate rise is missing. Pacific_Coast
  $0AA9 (voice 2): 12 notes against 14; the original's 156-frame note at f4418
  keeps bending at frame 4490 (`1148 1167 1186 ... (+ 001F)`, no attack) where
  ours strikes C-4 at f4496 and resets the pulse; 192 becomes 96 + 96 at the end.
  Lion_Heart $0AF9 (voice 0): 165 notes against 173, a 27-frame note is 16 + 11
  and a 21-frame note 16 + 5. Melody reads 91, 95 and 92 on the same three, so
  this overlaps the melody grouping. Songs: Sun_Never_Shines hold 67 (retrig
  0.93), Pacific_Coast 91, Lion_Heart 92. Prior art, symptom only:
  `sun-never-shines-and-lion-heart-voice-0-undershoot-by-fifty-and-forty-four-attacks`,
  `lion-heart-call-phase-note-row-aware`. A tie or legato spelling lost at a row
  boundary fits the Pacific_Coast frames but is a guess: read the row bytes
  of the first split on each file (`songview.py`, the three `.sng` in a private
  `--workdir`), name what the original has at the split (tie, legato, or a
  duration extension) and what we emit there, then census the same row shape
  over the corpus. Done when each of the three has the split row named with its
  record bytes, and either an emitter change shows all three `hold` rows at or
  above 99% with no printed column falling more than its noise and a corpus
  byte-hash naming every mover, or the cause is recorded as refuted. `[subagent]`
  for the reading, `[main]` for any emitter change and the refresh.
  touches: r:python/h2g, r:python/songview.py, r:python/fidelity.py, r:presets.json, r:build/fidelity.json

  added: 2026-11-08

- **Melody: the hard-restart window swallows Sun_Never_Shines' drum strike.**
  Sun_Never_Shines reads melody 91.13% at v0.5.654. Voice 0 loses 150 of its
  921 attacks, all `F-6` every 60 frames, and nothing else (difflib: 150
  deletes). The original strikes the drum as `5F0B (F-6 CD) 80` then
  `5F0B F-6 CD 81` (the gate rise is the attack). Ours writes `80` and the next
  write is the following note's `40`: the `81` row of the drum's wavetable
  (`80 CD / 81 CD / 40 77`) runs and its gate bit never reaches the chip. With
  `hard_restart_frames: 4` removed from Sun's preset (a copy, no patch) ours
  makes 1921 attacks against the original's 1898, voice 0 matches 921 of 921,
  and melody goes 91 -> 99%, seq 95 -> 99%; the price is gate 97 -> 68%. So a
  2-frame strike inside a 4-frame window loses its rise. Closed
  `hard-restart-floor-swallows-short-notes` (1e534e0) fixed the default window,
  not this preset. Evidence: `C:/t/corpus-melody-column-sub99-mechanisms/plan.md`
  M1 and `work/sns/`. Done when a patch that applies to a fresh worktree of
  HEAD keeps the window but lets a fixed-note strike shorter than it rise, and
  Sun_Never_Shines reads at least 99% melody in a
  `fidelity.py -t 180 --presets ../presets.json --sound` A/B with gate not
  falling more than its noise; the corpus byte-hash names every file the patch
  moves, and every song sharing the mechanism is censused first. A finding that
  the window cannot be kept and the strike restored also counts as done.
  `[subagent]`.

  added: 2026-11-08

- **Melody: the sfx drum has no gate edge on I_Ball and Bangkok_Knights.**
  I_Ball (96.50%) loses exactly 54 voice-2 attacks and Bangkok_Knights (96.79%)
  exactly 99, every one a `C#6`; their other voices match to within one attack.
  The original's strike is a test-bit frame (`08`) and then `C#6 C9 81`, a
  rising gate. Ours is either an ungated tick (I_Ball frame 1458,
  `(C#6 C9) 80` then `40`) or an `81` written while the gate is already high
  (I_Ball 1470, Bangkok 1293, printed as a tie), so no gate edge exists and no
  attack is counted. `drum_gate_off`, `drum_sustain_gate_off` and `drum_long`
  change no printed column on either song; `sfx_drum` off is worse (I_Ball
  melody 94%, retrig 0.70). Earlier closed diagnoses: `i-ball-melody-shortfall`
  and `bangkok-knights-melody-shortfall` (2026-11-01, findings under
  `C:/t/<id>/`, not re-read here). I_Ball's gate (41%) and wave (61%) and
  Bangkok_Knights' wave (56%) are the worst cells of those columns, so the same
  tick is the first thing to check there. Evidence:
  `C:/t/corpus-melody-column-sub99-mechanisms/plan.md` M2, `work/ib/`,
  `work/bk/`. Done when a patch that applies to a fresh worktree of HEAD gives
  the sfx drum a falling and a rising gate edge (or the original's test-bit
  frame), both songs read at least 99% melody, and no printed column of the
  other sfx_drum files falls more than its noise in a
  `fidelity.py -t 180 --presets ../presets.json --sound` A/B; the corpus
  byte-hash names every file the patch moves. `[subagent]`.

  added: 2026-11-08

- **Melody: Lion_Heart's noise drum is one fixed note, the original's moves.**
  Lion_Heart reads melody 91.53% (`-S3`). 123 of its mismatching tokens are the
  noise drum, `F#6` in the original and `F-6` in ours (92 on voice 0, 30 on
  voice 1, 1 on voice 2; every delta -1 semitone). Original frames 38-39:
  `5FBB (F#6 CE) 80`, `5FBB F#6 CE 81`; ours 42-43: `5CF1 (F-6 CD) 80`,
  `5CF1 F-6 CD 81`, from the constant `CD` in our wavetable. The original's
  frequency varies (5FBB x265, 5F67 x140, 5FA0 x73 over 180 s), so the drum
  follows the row note and ours is pinned; Sun_Never_Shines has the same shape
  (orig 5F0B, ours 5CF1) but both label F-6, so only Lion_Heart's melody
  sees it. About 30 more tokens are extra attacks (orig prints a tie at frame
  594, ours re-gates at 598); fix the drum first, then re-read that remainder.
  This overlaps the open entry "Drums on fixed notes versus drums that move
  with the note", which asks only for findings; do that one first or fold this
  in. Evidence: `C:/t/corpus-melody-column-sub99-mechanisms/plan.md` M3 and
  `work/lh/`. Done when a patch that applies to a fresh worktree of HEAD makes
  the Lion_Heart drum follow the original's pitch rule, Lion_Heart reads at
  least 99% melody in a `fidelity.py -t 180 --presets ../presets.json --sound`
  A/B (or the residual attacks are named as a separate measured ceiling), and
  the corpus byte-hash names every file the patch moves. `[subagent]`.

  added: 2026-11-08

- **Melody: transposed phrases sit a fixed interval off on Lakers_vs_Celtics
  and Pacific_Coast.** Lakers (93.24%) voice 0 has 24 tokens +2 semitones
  from the original and voice 1 has 52 at -2 and 5 at -5; Pacific_Coast
  (95.47%) voice 1 plays the phrase `G-3 C#4` as `C-4 F#4` (+5) from frame
  4226 and as `A#3 E-4` (+3) from 4490. In both, the offset equals a transpose
  our final orderlist carries (Lakers voice 0 `F2` at positions 17, 22, 37,
  voice 1 `EE` and `EB`; Pacific_Coast voice 1 +5, +3, -2 at positions 23, 25,
  27 after an initial +9 that matches for 4,200 frames). So the original
  plays these phrases without the transpose we apply, or applies it under a
  rule we do not model; which, is not proven (the early transposes of both
  songs do match). `fold_transpose` off is not the cause: Pacific_Coast melody
  95 -> 93, Lakers unchanged. About 19 further Lakers voice-2 tokens (`A#5`
  pairs rendered as `C-4`/`D#4`) are unexplained. Evidence:
  `C:/t/corpus-melody-column-sub99-mechanisms/plan.md` M4, `work/lk/`,
  `work/pc/`. Done when the original player's orderlist transpose handling is
  read from its disassembly and written down per instrument kind (arpeggio
  base, plain note, fixed drum), a patch that applies to a fresh worktree of
  HEAD follows it, both songs read at least 99% melody in a
  `fidelity.py -t 180 --presets ../presets.json --sound` A/B, and the other
  ILV files carrying `FD` transposes (the six listed in
  `tests/test_ilv_grammar.py`) are censused and byte-hashed first. A finding
  that our transposes are right and a different step is wrong also counts as
  done. `[subagent]`.

  added: 2026-11-08

- **Instr: gate-off lost for a whole row on Lightforce and Tarzan.** The
  original gates a note off at frame 3; ours has no gate-off there and keeps
  the gate on until a later row's own: Lightforce (-S2, row 7) off at frame 10
  on 193 notes and 17 on 97, Tarzan (-S1, row 6) at 9 on 136, 15 on 76 and 33
  on 12. That is 291 of Lightforce's 321 and 224 of Tarzan's 297 unmatched
  notes (instr 87.4% and 89.5%). A closed entry names a candidate not shown
  for these two: `gate-clear-untied-landing`, the $40 legato bit on a
  gate-clear record being exact only for tied landings. Evidence:
  `C:/t/corpus-instr-column-sub99-mechanisms/plan.md` B,
  `pairs/Lightforce.TONAL_OURS_GATE_LONGER.txt`. Done when the record or row
  that drops the gate-off is named for both songs and a patch lifts
  Lightforce's and Tarzan's instr in a `heard.py` re-score with the corpus
  byte-hash naming every moved file, or a finding says why the gate-off cannot
  be kept. `[subagent]`.

  added: 2026-11-08

- **Instr: Las_Vegas_Video_Poker (6.4%) and Phantoms_of_the_Asteroid (17.4%)
  re-gate their arpeggio block every 4 rows, the original every 4.8.**
  `fidelity.py --pace` reads both pitch streams as exact (row 3.75 and 2.00
  frames, ours/theirs 1.000) and attacks as equal (1051/1051, 2592/2592), yet
  the gate-rise gaps differ by 6/5: Phantoms voice 2 original 9,10,10,9,10
  against ours 8,8,8; Las_Vegas original 27,27,18,27,27,18,9 against ours
  23,22,15,23,22,15,8. Ours therefore has 17% and 24% more gate rises than the
  original (1051 against 896; 2598 against 2089), and 629 and 991 original
  notes find no partner. Phantoms has a second shape on top (paired notes'
  AD/SR/wave differ at frame 0), not diagnosed. Evidence:
  `C:/t/corpus-instr-column-sub99-mechanisms/plan.md` D,
  `pairs/gate_rise_period_Phantoms_LasVegas.txt`, `diag/*.pace.txt`. Done when
  the player's re-gate counter is read for both songs and a patch puts ours'
  gate rises on the original's schedule in a `heard.py` re-score, byte-hash
  named, or a finding that the schedule cannot be a Goattracker row count.
  `[subagent]`.

  added: 2026-11-08

- **Instr (harness): `heard.restruck` merges ours but not the original on a
  re-strike, so Game_Killer reads 98.0% and Master_of_Magic 98.8%.** Rule 3
  merges a gate rise into the previous note only when AD/SR are unchanged
  across the gate-off; the original clears them on its gate-off frames (the
  envelope cut `sr_rel`/`tail_env` already call known-equivalent), ours keeps
  them. So the same re-strike is two notes on the original and one on ours:
  63 of Game_Killer's 65 missing notes and 16 of Master_of_Magic's 17 are
  ours-has-a-gate-rise-but-unpaired. Measured by ignoring AD/SR in `restruck`
  in a private script: Game_Killer 98.0% -> 99.8% (missing 65 -> 2),
  Master_of_Magic 98.8% -> 99.9% (17 -> 1); Star_Paws and Rasputin do not move,
  Spellbound .819 -> .828. The converter is not at fault. Evidence:
  `C:/t/corpus-instr-column-sub99-mechanisms/plan.md` G,
  `pairs/restrike_envelope_experiment.txt`, `pairs/Game_Killer.MISSING.txt`.
  Done when `heard.py` treats the known-equivalent envelope cut the same on
  both sides in `restruck`, a test in `tests/test_heard.py` fails with the
  change removed, and the full `build/heard.json` is re-taken with every moved
  song named and no song's instr falling by more than 2 points without a named
  reason. `[subagent]`.

  added: 2026-11-08

- **Instr: IK_plus (35.3%) never sounds the original's noise tick.** Voice 2
  of the original strikes `ctl 81` (frequency `485a`) at f+1 and f+7 of every
  6-frame row; ours has `ctl 01` (gate, no waveform) there. 1333 of 1888
  unmatched notes are the missing noise, with pitch+wave on 1450 of 2919.
  `--diagnose` also reads ours travelling 130,326 on voice 1 and 4,186 on voice
  2 where the original travels 0 (pitches 93% on voice 2); whether that is the
  same defect is not shown. Closed, same song:
  `ik-plus-voice-2-strikes-222-attacks-against-the-originals-481` (7969d85).
  Evidence: `C:/t/corpus-instr-column-sub99-mechanisms/plan.md` J2,
  `pairs/IK_plus.WAVE_ORIG_NOISE_OURS_NOT.txt`, `diag/IK_plus.diagnose.txt`.
  Done when the record that carries the tick is named and a patch emits the
  noise frame at f+1 in a re-score with the byte-hash naming every moved file.
  `[subagent]`.

  added: 2026-11-08

- **Instr: the original's octave arpeggio inside the note is missing or out of
  phase in ours (7 songs, Radio_ACE 38.3% worst).** Radio_ACE voice 2 original
  `173a, 173a, 2e75, 173a, 2e75, 173a` (ring-modulated), ours flat: 782 of 1320
  unmatched notes. Pacific_Coast the same (202/323); Lakers_vs_Celtics toggles
  from f+2 in the original and from f+5 in ours (157/270); Saboteur_II and
  Last_V8 toggle one step off (174/366 and 150/164); Samantha_Fox_Strip_Poker
  19/19; Nineteen is mixed (29 of 81) and has its own entries. Related closed:
  `rasputin-eor-toggle-emit` (c402e79). Evidence:
  `C:/t/corpus-instr-column-sub99-mechanisms/plan.md` K,
  `pairs/Radio_ACE.PITCH_OCTAVE.txt`, `pairs/Lakers_vs_Celtics.PITCH_OCTAVE.txt`.
  Done when the Radio_ACE octave toggle's source (a player counter or a
  table) is named and a patch emits it, with the toggle's phase compared on
  Lakers_vs_Celtics as the second file and the byte-hash naming every moved
  file. `[subagent]`.

  added: 2026-11-08

- **Test column: "No legato" on 10 songs -- the original changes notes without a re-trigger and ours re-attacks them.** Not a percentage column, so no column pass covered it. The listening index's `test` cell reads "No legato" on ACE_II, Chain_Reaction, Dragons_Lair_Part_II, Flash_Gordon, Food_Feud, Knucklebusters, Mozart, Saboteur_II, Tarzan and Zoolook (index rebuilt at v0.5.656, 2026-11-09; held DIGI files excluded). The flag is `listen.py`'s slow-tie check: it fires when the original has at least 20 slow ties (more than `RAPID_TIE_FRAMES` frames after the voice's previous note event) and ours has under a quarter of that, and names the voices. Flash_Gordon and Food_Feud are in no other entry; the other eight are, for other causes. Every other sub-99% cell on the index (melody, gate, wave, hold, instr) is already under an entry above, and the five `length` mismatches (Geoff_Capes, Kings_of_the_Beach_ingame, Knucklebusters, Knucklebusters_3, Sanxion) are all within the ±5 s rule. Done when the 10 songs are grouped by the mechanism that drops each one's slow ties (which voice, which instrument, what the original writes at the tie and what we emit), each group with an emitter change named, or the flag shown to fire on a shape that is not legato. `[subagent]` for the grouping pass.

  added: 2026-11-09

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
