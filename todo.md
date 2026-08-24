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
