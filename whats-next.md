<original_task>
Continuation of long-running work on **H2G**, a signature-based ripper that
converts Rob Hubbard `.sid` files into GoatTracker `.sng`, at
`C:\Users\mit\claude\h2g`. The session opened by reading the previous handoff
(then at v0.5.225, twelve versions stale) and ran to **v0.5.237**.

There was no up-front task. The session was driven by "read what's next",
"continue", "push" — each answered before the next was given. The working mode
is the project's established one:

> measure the conversion against the original, find where they differ, read the
> 6502 to learn why, fix it, re-measure across the corpus, and ship or refuse to
> ship on the measurement.

Scope: `python/h2g/` (detect.py, goatwriter.py) plus the measurement harness
(`python/fidelity.py`, `python/presets.py`). The VB6 original was not touched.
</original_task>

<work_completed>

## Summary

**4 commits, v0.5.234 → v0.5.237, all pushed.** HEAD is `e624a09`, master in
sync with `origin/master`. `934 passed, 2 skipped`. `Commando.sng` byte-exact
throughout. Working tree clean but for the deliberately untracked `6581.pdf`.

The through-line: **three of the four commits began with an option the preset
search had measured and never selected, where a byte-hash showed it was
changing nothing.** That check — `--baseline`'s `output_sha`, or a direct
`hashlib` sweep over the corpus — is now the first thing CLAUDE.md tells you to
run when a setting is offered and declined.

## v0.5.234 (`eee5868`) — the onset census becomes a mode

`fidelity.py --census PATH` classifies every `onset` disagreement by kind and
groups the `flat` misses by the source record's effect byte. Computed inside
`_measure` from the traces the column just scored, so its `match` count *is*
`onset_matched`; a second pipeline would have resolved its own subtune
(`--search-subtunes` defaults to 3) and disagreed with the report for reasons
unrelated to the conversion.

Promoting the previous session's lost scratch script found a defect in the
column beneath it: the phase test `ours[:-1] == orig[1:]` is vacuously true on
a shape the original holds **constant**, so a note of ours that merely *ends*
inside the four-frame window (`noi noi noi --`) was reported as a one-frame
phase error — 3 of the corpus's 6. `onset_shift` now requires the shift to
explain something the unshifted reading does not, both readings share that one
function, and the remainder is a new `short` kind. Converter untouched.

## v0.5.235 (`d86b15e`) — the wave program runs at the player's rate

The census's `$01 x19` group: nine files, none with `effect_drum`; in eight,
bit `$01` is the **wave-program gate** and the gated records are exactly the
flagged instruments. Forced on, `--wave-program` changed 1 of 9 files' bytes —
`_wave_program_entries` refused every multiplier above 1, and seven of the nine
pack at `-S2`/`-S3`/`-S5`. Each opcode now takes a hold entry
(`_wave_hold_byte`), the lead comes from `_first_frame_lead` (this was the
fourth emitter never to call it), and the hold's right side is `$00` because
`$80` would re-assert the pattern's note over an absolute pitch.

Two harness defects came out of running the search, both fixed in the same
commit:

* **The search's window was 10 s while the report's is 60 s.** v0.5.195 moved
  `FIDELITY.md` to 60 s and the finding was filed as being about the report.
  Sanxion's 10 s window holds 1 comparable instrument and 0 original noise
  frames against 8 and 1669 at 60 s — two of `fidelity_better`'s terms are
  noise terms and a third is `onset`, so the criterion was blind, not
  disagreeing, and five files lost a `two_stage` a 60 s A/B scores at onset
  40–83% → 100%. Default is 60 now, pinned by a test. **A corpus search takes
  about an hour rather than forty minutes.**
* **A failed search silently reverted a song to structural defaults.** W_A_R
  lost a measured `two_stage` to a `ValueError` in 4 of its 31 combinations. A
  candidate that will not convert is now skipped and named; a song whose search
  fails keeps what the previous run recorded.

## v0.5.236 (`3059b3c`) — one guard, nine files, every effect-byte routine

The next census group, `$04 x11`, was not an encoding problem and not option
selection: `detect._effect_byte_address` opened with `if det.instr_stride != 8:
return None`, switching off **every** routine that reads the instrument effect
byte for the nine corpus files whose records are 16 bytes, across six call
sites. The probe computes record 0's `+7` and searches for the player's own
`LDA base,Y` — neither step depends on the stride.

Rikky's block is `TWO_STAGE_SHAPE` byte for byte; what differs is that its two
bytes live at record `+9` and `+11` rather than in a table after the records,
and `duration == attack + 2` holds either way, so the data model needed
nothing. Five files land within 3% of the original's noise-frame count from
zero; `onset` reaches 100% on seven of the nine.

`_bound_instruments` found the counter-example its docstring promised could not
exist (Powerplay Hockey: patterns name instrument 8 against a bound of 6,
melody 72% → 66%), and is now restricted to the stride-8 population it was
measured on.

## v0.5.237 (`e624a09`) — a waveform byte that was a jump

Wiz's silent pack failure, unexplained for the project's life. Replicating
`gtable.c:1008`'s `exectable` over the emitted tables names it in one line:
`OVERFLOW: instrument 2 WTBL from ptr 6`. `_wave_program_entries` copied an
opcode's waveform into the wavetable's left column, where `$F0`-`$FF` are
commands and `$FF` is the **jump** — Wiz's `set $FF, 250` became `FF/DE`, a
jump to row 222 of a 112-row table. Routed through the `$E0`-`$EF` encoding
`_wave_byte` already used below `$10`.

`tests/test_table_validation.py` is the general form: it walks every corpus
conversion's tables by `exectable`'s rules and asserts neither TYPE_JUMP nor
TYPE_OVERFLOW.

## Where the corpus stands

    census   match 403 of 433 (93.1%)   flat 18   short 5   phase 3
             partial 3   invented 1   wrong 0
    report   mean melody 87%   mean wave 76%   noise 75409 / 82742
             83 of 95 measured, 44 songs carry a --fidelity setting

The census's two largest groups at the start of the session — `$01 x19` and
`$04 x11` — are both closed. `flat` went 50 → 18.
</work_completed>

<work_remaining>

Ordered by value. The census work list (`build/CENSUS6.md`, regenerate with
`fidelity.py ... --census`) is the queue for items 3-4.

### 1. The wavetable budget — profiled, not fixed

`_wavetable_layout` reserves `WAVE_ENTRIES_PER_INSTR` = 5 for every later
record and floors each budget at 5, but **handed a budget of 5, 197 records
across 40 corpus files emit 6, 7 or 8 entries**: several emitters check the
budget only for their optional part (`_drum_entries` for its sweep) or not at
all. So "nobody starves" is a property the layout asserts and the emitters do
not hold up.

It bites only near the ceiling, which is why one file crashes and not forty.
Natural lengths against the 255 limit: W_A_R **177**, Thundercats **228**, Mr
Meaner 196 — and **only Mega Apocalypse (391) exceeds it**. Today it costs
W_A_R 4 of its 31 search combinations.

Two separable halves: reserve each later record's *natural* length instead of 5
(a pre-pass, affordable for every file but Mega Apocalypse), and make the
emitters degrade honestly where the budget genuinely binds. Own commit, own
corpus A/B, and `tests/test_table_validation.py` is the guard.

### 2. Nothing has been listened to since v0.5.209

**Fifty files changed settings across these four commits and none has been
heard.** Every argument in all four is a register argument. Use
`.\play.ps1 <file> -Presets presets.json` — **never launch `goattrk2.exe`
directly** (37 of 82 files advance a row every 2-3 frames; `play.ps1` prints
how many SHIFT+F6 presses the song needs). The files where a listener would
learn most: Shockway Rider (noise now 404/404), Kings of the Beach intro
(melody 61% → 67%), and any of the seven stride-16 files from v0.5.236.

### 3. `$80 x4` and the rest of the census

    $80  4   Bangkok_Knights, Mega_Apocalypse, Star_Paws, Thundercats
    $01  4   Hollywood_or_Bust, Ninja, Wiz
    $02  2   Chicken_Song, Ninja
    $14  2   IK_plus, I_Ball
    $A0  2   I_Ball, Nineteen

The `$01` survivors are named: Hollywood or Bust and Ninja have no wave program
at all (`det.wave_program == -1`, so bit `$01` there is a third mechanism), and
Wiz's `--wave-program` is measured and declined for 12 points of melody.

### 4. `short x5` is the first pointer at note length

CLAUDE.md has said for a long time that no column measures note length. The
`short` kind names five instruments where our note stops selecting a waveform
inside the four-frame window — Devils Galop and Monty on the Run at 114 notes
each, both exact on the first three frames. That is a concrete starting set for
a note-length dimension.

### 5. Rasputin's three `phase` instruments

The only genuine one-frame shifts left in the corpus, all on one file, all
`$01`: `pul pul noi pul` against `pul noi pul pul`. Our note counts are less
than half the original's (55/24, 70/31, 46/20), so there is a second defect on
the same file.

### 6. Older, still open

* The speed gate `goatwriter.find_song_speeds` reads is under-read by a
  tune-specific 1.1–1.5x. Per-file targets in `build/pace.txt`; use
  `fidelity.py <file> --pace` before saying anything about tempo.
* No noise-pitch column, and none for note length (see 4).
* `songview.py`'s comparison overlay — the designed selling point never built.
</work_remaining>

<attempted_approaches>

## Refuted, reverted, or corrected mid-session

1. **"Star Paws is refused; the wave program reaches a melodic record."**
   Published, then corrected. Forcing `--wave-program` over that song's
   *existing* preset measured the pair: its preset carried `--no-test-restart`,
   which owns frame 0, so the program's first opcode became wavetable entry 0
   and at `-S2` that is still inside frame 0, renaming every attack. The search
   drops `no_test_restart` and keeps `wave_program`; melody unmoved at 97%.
   **Forcing one option on top of a preset measures the pair.**
2. **A v0.5.234 baseline search in a fresh git worktree.** Invalid: a worktree
   has no `python/tools/siddump-rt/siddump.exe` (gitignored), and the harness
   *refuses* a multiplier > 1 song rather than tracing it at the wrong rate, so
   it silently scored only the single-speed files — 15 selected songs against
   the real 30. The difference was read as a converter change for a while.
   Copy or build the binary in the worktree first.
3. **Shipping the 10 s search's `presets.json`.** It moved 22 files, 24
   settings lost and 10 gained, and was read as "the converter changed under a
   stale presets.json". It had not — the churn was the window (see v0.5.235).
   The 60 s search reproduces every shipped setting exactly and adds only what
   the fix earns. **Diff a regenerated search against the shipped file before
   adopting it.**
4. **A budget guard I introduced and caught.** `_wave_program_entries`' loop
   checked `len(left) + 3 > budget` where an opcode now costs two entries, so a
   program filling the table overran by one. Caught by writing the test first
   and checking it fails against the old guard.
5. **`presets.py`'s "carried N settings forward" message under `--fidelity`.**
   My own change made `carried` populate on every run; the message then
   described the opposite of what happened. Gated on `not args.fidelity`.

## What worked

* **Byte-hash the corpus before theorising about a criterion.** Three of four
  commits started there.
* **A minimal 6502 disassembler in the scratchpad** (`dis6502.py`, ~120 lines,
  worth recreating) — reading Rikky's `AND #$04` block directly is what turned
  `$04 x11` from a statistic into a one-line fix.
* **Replicating GoatTracker's own validation in Python.** `exectable` is twenty
  lines and turned a silent refusal into an instrument and a row.
</attempted_approaches>

<critical_context>

## Environment

* Repo `C:\Users\mit\claude\h2g`, branch `master`, HEAD `e624a09`, pushed.
* Corpus (95 files): `C:\Users\mit\claude\c64server\SIDM2\SID\Hubbard_Rob`
* GoatTracker 2.77 source: `C:\Users\mit\Downloads\GoatTracker_2.77\src`
  (`gplay.c`, `gsong.c`, `gtable.c`, `greloc.c`, `gcommon.h`).
* `build/` is gitignored; `6581.pdf` untracked deliberately.
* A corpus `presets.py --fidelity` run now takes **about an hour** (60 s
  window). `fidelity.py` over the corpus takes about five minutes.

## Rules added to CLAUDE.md this session

1. A census of what a column misses is a queue — and it is `--census` now.
   A scratch script that answers a question twice is a tool that was not
   committed.
2. A degenerate match is not evidence (`ours[:-1] == orig[1:]` on a constant
   shape).
3. `presets.py --fidelity` searches at the window the report is published at.
4. A search that fails is not a search that says no.
5. Forcing one option on top of a preset measures the pair.
6. A guard that reads like a sanity check can be a population filter.
7. A byte copied from the player into a Goattracker table is in Goattracker's
   encoding now.
8. A worktree has no build artefacts, and this harness needs one.

## Assumptions needing validation

* `onset`'s 4-frame window and its exact-match rule are choices, not
  measurements (unchanged from the previous handoff).
* The `short` kind assumes a class-0 frame inside the window means the note
  ended; it could also be a waveform we simply fail to write.
* v0.5.236's stride lift was validated by corpus hash and by measurement on the
  nine files. The six new bit-`$80` detections emit nothing today because no
  record sets the bit — if a future change makes them emit, they are unvalidated.
</critical_context>

<current_state>

## Repository

* **HEAD `e624a09` (v0.5.237), pushed; master in sync with origin/master.**
* `python -m pytest tests/ -q` → **934 passed, 2 skipped** (both gated on
  `H2G_GT2RELOC`).
* `SURVEY.md`, `presets.json`, `FIDELITY.md` all regenerated at v0.5.237.
* `Commando.sng` byte-exact.

## New surface added this session

* `fidelity.py` — `--census`, `onset_shift`, `classify_onset`,
  `instrument_stamps`, `onset_census`, `census_report`, `ONSET_KINDS`
* `presets.py` — `build_parser()`, `-t` default 60, the skip-and-name failure
  path, carry-forward on failure
* `goatwriter.py` — `_hold_wave_program_entry`, `WAVECMD_BASE`, `_wave_byte`
  covering both unwritable ranges
* `detect.py` — `_effect_byte_address` without the stride guard,
  `_bound_instruments` restricted to stride 8
* New tests: `test_onset_census.py` (19), `test_table_validation.py` (3), plus
  additions to `test_onset.py`, `test_wave_program.py`, `test_call_rate.py`,
  `test_preset_passthrough.py`, `test_two_stage.py`, `test_effect_bit80.py`,
  `test_instrument_bound.py`

## Immediate next action

**Item 2 — listen.** Fifty files have changed settings across four commits on
register evidence alone, and the project's history has a listener reversing a
register verdict more than once. After that, item 1 (the wavetable budget) is
fully scoped and has its guard test already in place.
</current_state>
