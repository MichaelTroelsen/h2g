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

- **5 Title Tunes fidelity.** Like Action Biker, the sequence is already exact —
  `melody`, `seq`, `pitch` all 100%, `retrig` 1.00, `drift` +0.0, `onset` 100%,
  938 original notes against 935. So nothing here is about the notes. The row
  (`docs/FIDELITY.md:25`):

  | column | 5_Title_Tunes | reading |
  |---|---|---|
  | `pul` | **4459/2240 = 1.99x** | we move the duty cycle almost exactly TWICE as often as the original |
  | `pspan` | **0.47x** | and each move is about HALF as wide |
  | `gate` | 50% | |
  | `adsr` | 58% | |
  | `wave` | 90% | |
  | `hold` | 0% | check against `--hold-census` FIRST, per the Action Biker precedent |

  **CENSUSED at v0.5.376 — `pul` is NOT a defect and the claim once written
  here that "1.99 x 0.47 = 0.94, so the total travel is about right" was wrong:
  `pspan` is the max-min BAND, not a per-step size, so multiplying the two
  decomposes nothing.** Measured, our travel is 1.64-1.85x the original's.

  `pul` 1.99x is the documented half-step substitution and is correct. The
  records confirm it exactly: `rec+6` `$41` -> step 64 / delay 2 -> speed 32,
  and `$81` -> step 128 / delay 2 -> speed 64, which are precisely the step
  sizes observed on the trace (32, and 64/65). Same average sweep rate, taken
  in half-size steps twice as often. `fidelity._span`'s own docstring already
  says so: "the count doubles while the sound is the same".

  THE REAL DEFECT IS `pspan` 0.47x — our band is 449/771/899 against the
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
