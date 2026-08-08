# Changelog

Versioning: the single source of truth is `__version__` in
`python/h2g/__init__.py`. Bump the patch on every commit with
`python python/bump_version.py "short description"`.

## 0.5.133 — 2026-08-08

- fix the --vice denominator: shared silence must leave numerator and denominator

## 0.5.132 — 2026-08-08

- record the corpus --vice run and decompose resolution from rule

## 0.5.131 — 2026-08-08

- wire VICE per-rasterline traces into the register dimensions

## 0.5.130 — 2026-08-08

- wavetable timing: the attack's off-by-one and the arpeggio's call-rate body

## 0.5.129 — 2026-08-08

- correct the classic vibrato half-period: cmp = bound*multiplier - 2

## 0.5.128 — 2026-08-08

- rewrite the handoff for the split repository

## 0.5.127 — 2026-08-08

- record the vicetrace section that v0.5.126's commit described but did not write

## 0.5.126 — 2026-08-08

- per-rasterline SID trace from VICE; 312 samples a frame

## 0.5.125 — 2026-08-08

- equal-calls mode; the cap was an artefact, raise it to 6

## 0.5.124 — 2026-08-08

- the -S5 attack loss is siddump's frame sampling, not the conversion

## 0.5.123 — 2026-08-08

- eliminate gatetimer as the -S5 cause; name the sampling limit

## 0.5.122 — 2026-08-08

- investigate -S5: attack loss, not mistiming

## 0.5.121 — 2026-08-08

- a fractional row is exact at the right multiplier; corpus melody 74.8% -> 78.3%

## 0.5.120 — 2026-08-08

- skip_gate on by default; v0.5.119's regression was a harness bug

## 0.5.119 — 2026-08-08

- encode the skip counter behind --skip-gate; opt-in, and the reason

## 0.5.118 — 2026-08-08

- complete the static check: rows per note are exact, 41/41

## 0.5.117 — 2026-08-07

- start the static check; record what blocks it rather than guess the decode

## 0.5.116 — 2026-08-07

- Spellbound's row is 2.20, by a method that is not circular

## 0.5.115 — 2026-08-07

- re-check 7b's conclusions under the confidence gate; none moves

## 0.5.114 — 2026-08-07

- gate --pace on sample size and spread; withdraw 7c

## 0.5.113 — 2026-08-07

- correct 7c: we emit fewer rows per note, not more

## 0.5.112 — 2026-08-07

- Action_Biker closes: its skip counter reloads 0 and is inert

## 0.5.111 — 2026-08-07

- Spellbound closes; --pace cannot separate rows-per-note from row length

## 0.5.110 — 2026-08-07

- trace as PAL by default; re-measure the four $02A6 files

## 0.5.109 — 2026-08-07

- scan for $02A6 readers; siddump-rt -v traces as PAL

## 0.5.108 — 2026-08-07

- the frame-skip idiom has a second site and four dialects; $02A6 makes one measurement NTSC

## 0.5.107 — 2026-08-07

- ticks clears Human_Race and declines the other four

## 0.5.106 — 2026-08-07

- the five files that missed have no outer counter -- checked, not assumed

## 0.5.105 — 2026-08-07

- find the counter above the speed gate, and the per-subtune table that fills it

## 0.5.104 — 2026-08-07

- point the corpus tests at H2G_CORPUS instead of one machine's path

## 0.5.103 — 2026-08-07

- read the player's own tick period out of its cycle count (--ticks)

## 0.5.102 — 2026-08-07

- locate the second counter above the speed gate

## 0.5.101 — 2026-08-07

- pace: time the conversion against the original, and correct v0.5.99's reading

## 0.5.100 — 2026-08-07

- regenerate SURVEY, presets and FIDELITY on the merged tree

## 0.5.99 — 2026-08-07

- trace each conversion at the call rate it was packed for

## 0.5.98 — 2026-08-07

- read the LFO-table vibrato, the second form Hollywood or Bust uses

## 0.5.97 — 2026-08-07

- fidelity --diagnose: subtune correspondence first, then per-voice cause

## 0.5.96 — 2026-08-07

- read effect bit $80 in full: nine files' block is the game's sound effect, two are a wave program

## 0.5.95 — 2026-08-07

- hand off at v0.5.94

## 0.5.94 — 2026-08-07

- the forks LoadTracker merged: gt2fork, leafo, Langner's GTUltra

## 0.5.93 — 2026-08-07

- compare GoatTracker's forks; the GTS2 overrun is in all of them

## 0.5.92 — 2026-08-07

- render RSID originals through VICE, both sides of the pair

## 0.5.91 — 2026-08-07

- run the player: the drum does fire, and bend cannot see it

## 0.5.90 — 2026-08-07

- read the drum gate in full: cross-voice state, and the noise is the attack

## 0.5.89 — 2026-08-07

- explain Thrust: bend cannot compare a stepped sweep to a glided one

## 0.5.88 — 2026-08-07

- take bend from siddump's own delta, not the frequency column

## 0.5.87 — 2026-08-07

- read the command-table engine's pitch slide

## 0.5.86 — 2026-08-07

- read the digi engine's own pitch slide, effect $82

## 0.5.85 — 2026-08-07

- emit the vibrato every player runs and no output ever had

## 0.5.84 — 2026-08-07

- exclude ties from bend, and name the vibrato as the missing movement

## 0.5.83 — 2026-08-07

- read the second slide dialect, and index the step at full width

## 0.5.82 — 2026-08-07

- divide every per-frame rate by the -S multiplier

## 0.5.81 — 2026-08-07

- regenerate after the accumulate pulse engine

## 0.5.80 — 2026-08-07

- read the accumulate pulse engine, effect bit $08

## 0.5.79 — 2026-08-07

- regenerate with the four register columns

## 0.5.78 — 2026-08-07

- the report spends the registers: adsr, pul, filt and cut columns

## 0.5.77 — 2026-08-07

- state which dimensions a run compared, and A/B against a baseline

## 0.5.76 — 2026-08-07

- read every siddump register, not two fields of three

## 0.5.75 — 2026-08-07

- record the branch/worktree/PR convention for parallel work

## 0.5.74 — 2026-08-07

- regenerate the artefacts on the settled tree

## 0.5.73 — 2026-08-07

- read the player's pulse-width sweep into the pulse table

## 0.5.72 — 2026-08-07

- read the player's filter into Goattracker's filter table

## 0.5.71 — 2026-08-07

- read the envelope: the sustain nibble, and Goattracker's hard restart

## 0.5.70 — 2026-08-07

- pack the listening pass at the multiplier its player needs

## 0.5.69 — 2026-08-07

- record the RSID gap in the listening harness

## 0.5.68 — 2026-08-06

- regenerate the artefacts on the settled tree; record the per-call multiplier defect

## 0.5.67 — 2026-08-06

- read the instrument table through the index load; the instrument a voice starts on

## 0.5.66 — 2026-08-06

- end the instrument count at the records; give each fidelity run its own scratch directory
- the instrument-count walk had nothing to stop it at the end of the records.
  In the 34 files carrying the two-stage attack array it ran straight into
  that array -- same 8-byte rows, and its `+2` is a frame count that is a
  legal waveform often enough to keep going -- and reported roughly twice the
  truth: IK+ 30 where 15 are real, Wiz 40/20, Delta 44/22, Bangkok 58/29.
  `detect._bound_instruments` ends the count at the array, only where the gap
  is a whole number of records (three files are not, and keep their count).
  29 conversions change; **no file gains a dangling instrument reference**
  under the shipped options, and in eight the bound lands on exactly the
  highest instrument the music plays.
- **This refutes what H2G-CONVERSION-METHOD.md §4.1 argued for eleven
  versions**: that a 56-59 instrument count could not be an over-read because
  Bangkok Knights and Thundercats share 29 byte-identical records, i.e. a
  shared bank appended to the player. The bank is real but it is 16 records;
  the other 13 of those 29 are rows of the attack array, which recurs across
  these files because they share a player. No corpus file was ever over
  Goattracker's 51-instrument ceiling -- ten were detected over it and the
  nine of those that convert were listed in `SURVEY.md` as losing real
  instruments to it. That paragraph is now gone, and the prose behind it in
  `survey.py` corrected rather than only its output.
- **Invisible to both metrics, and that is expected**: the removed records
  were never referenced, so nothing that plays changed. Measured base vs
  fix at presets over 10 s -- mean melody, sequence, pitch, wave and noise
  frames identical to every decimal on all 81 scored files, no status
  changes. The fix is to what the file *contains*, not to what it sounds
  like.
- fixed the bounds guard the bound is computed from: `not 0 <= off and ...`
  binds as `(not (0 <= off)) and (...)`, so it rejected only a negative
  offset that was also in range -- nothing -- and passed a table running off
  the end of the file. No corpus file changes; it was latent.
- `fidelity.py` and `listen.py` now take a private scratch directory per run.
  They shared one path with fixed filenames (`a.sng`, `b.sid`, `o.sid`), so
  two concurrent runs overwrote each other between write and read and each
  measured whichever file won -- silently, with plausible numbers about the
  wrong tune. It has already contaminated one A/B in this repo. `--workdir`
  still names one for debugging.

## 0.5.65 — 2026-08-06

- census the effect byte's high bits; read the two-stage waveform

## 0.5.64 — 2026-08-06

- trace each file's own default subtune, not subtune 0

## 0.5.63 — 2026-08-06

- read the player's note frequency table: fix Skate or Die's shifted note base, name NTSC-tuned originals on their own tuning

## 0.5.62 — 2026-08-06

- read the effect byte's drum and arpeggio only where the player has them

## 0.5.61 — 2026-08-06

- fold orderlist transposes past Goattracker's +14 into the notes

## 0.5.60 — 2026-08-06

- pack at the speed multiplier the player needs

## 0.5.59 — 2026-08-06

- census the instrument effect byte's real consumers

## 0.5.58 — 2026-08-06

- regenerate on the settled tree

## 0.5.57 — 2026-08-06

- reject phantom patterns, honour the status byte, derive tempo per file

## 0.5.56 — 2026-08-06

- measure waveform agreement

## 0.5.55 — 2026-08-06

- read a player whose table addresses its init writes over the code

## 0.5.54 — 2026-08-06

- regenerate artefacts at v0.5.53; rewrite the handoff

## 0.5.53 — 2026-08-06

- audit fixes: CLI bounds, help text, equals-form flags, effects preset

## 0.5.52 — 2026-08-06

- Delta orderlist repeats, bit-7 note flag, cmdtable dialect

## 0.5.51 — 2026-08-06

- decode the instrument effect byte where the player has it

## 0.5.50 — 2026-08-06

- map Hubbard pitch bends onto Goattracker's speed table

## 0.5.49 — 2026-08-06

- repair empty voice orderlists unconditionally

## 0.5.48 — 2026-08-05

- convert ACE 2 and Chain Reaction

## 0.5.47 — 2026-08-05

- mark fidelity rows gt2reloc could not export

## 0.5.46 — 2026-08-05

- digi rest is a key-off, not a hold

## 0.5.45 — 2026-08-05

- --legal-restart and the fidelity harness

## 0.5.44 — 2026-08-05

- convert the Delta loader and I, Ball: a pattern signature and a self-relocating file

## 0.5.43 — 2026-08-05

- assess SIDM2's fidelity tester for use here

## 0.5.42 — 2026-08-05

- set tempo via CMD_SETTEMPO; add gt2reloc column and packing step

## 0.5.41 — 2026-08-05

- identify the CSDb release and record its non-Hubbard converts note

## 0.5.40 — 2026-08-05

- document the .sng -> .sid packing route and its two blockers

## 0.5.39 — 2026-08-05

- add CSDb release link to README

## 0.5.38 — 2026-08-05

- record the regenerate-artefacts convention; refresh SURVEY.md and presets.json

## 0.5.37 — 2026-08-05

- split an over-long subtune in phase instead of dropping it

## 0.5.36 — 2026-08-05

- add per-song option presets: presets.py and --presets

## 0.5.35 — 2026-08-05

- compact over-long orderlists by merging patterns

## 0.5.34 — 2026-08-05

- drop an over-long subtune instead of aborting the whole file

## 0.5.33 — 2026-08-05

- report the dropped digi sample channel in the log and survey

## 0.5.32 — 2026-08-05

- recognise the interleaved-table digi engine, converting 8 more files

## 0.5.31 — 2026-08-05

- list non-Hubbard-player files in their own SURVEY.md section

## 0.5.30 — 2026-08-05

- report SIDId identification split by converted/not converted

## 0.5.29 — 2026-08-05

- decode version 5/6/7 orderlist commands from the players' actual code

## 0.5.28 — 2026-08-05

- reindex orderlists at the player dialect's command boundary, not Goattracker's

## 0.5.27 — 2026-08-05

- add --pack-repeats: collapse repeated patterns into REPEAT commands

## 0.5.26 — 2026-08-05

- reject unsound detections and subtunes that play no existing pattern

## 0.5.25 — 2026-08-05

- decode version-2 orderlist transposes instead of reading them as pattern numbers

## 0.5.24 — 2026-08-04

- survey: report dangling pattern references

## 0.5.23 — 2026-08-04

- add --prune-patterns: drop patterns no track references

## 0.5.22 — 2026-08-04

- Add SIDId player identification column to SURVEY.md

## 0.5.21 — 2026-08-04

- Add --dedup-patterns: share byte-identical pattern slices

## 0.5.20 — 2026-08-04

- SURVEY.md: report the source file's own header version; name both output formats

## 0.5.19 — 2026-08-04

- Add GOATTRACKER.md: five verified upstream issues with suggested fixes

## 0.5.18 — 2026-08-04

- Doc audit: correct resolved-bug claims, document GTS5, de-duplicate CLI flag lists

## 0.5.17 — 2026-08-04

- Read the PSID speed field; add --tempo to write a startup tempo into instrument 63

## 0.5.16 — 2026-08-04

- Housekeeping: correct the instrument over-read claim, drop stale whats-next.md

## 0.5.15 — 2026-08-04

- Add play.ps1 launcher; fix absolute -OutputFile in convert.ps1

## 0.5.14 — 2026-08-04

- Report output format (GTS2/GTS5) in SURVEY.md header

## 0.5.13 — 2026-08-04

- Add --format gts5: modern 4-table output avoiding GoatTracker's legacy GTS2 importer overrun

## 0.5.12 — 2026-08-04

- Add GoatTracker loader validation tests (sngspli2)

## 0.5.11 — 2026-08-04

- SURVEY.md: add player-variant name and real emitted subtune count per file

## 0.5.10 — 2026-08-04

- Regenerate SURVEY.md after all fork work landed

## 0.5.9 — 2026-08-04

- Fix wait==0 events being dropped: an event lasts wait+1 frames, always >=1 row

## 0.5.8 — 2026-08-04

- Derive instrument clamp from Goattracker's wavetable limit; report dropped instruments and dangling references

## 0.5.7 — 2026-08-04

- Validate extracted table addresses; reject out-of-range detections instead of emitting empty .sng

## 0.5.6 — 2026-08-04

- Add --terminate-patterns: explicit ENDPATT row per pattern slice

## 0.5.5 — 2026-08-04

- README cites SURVEY.md for conversion rates instead of hardcoding them

## 0.5.4 — 2026-08-04

- Move version/usage docs from CLAUDE.md into a new README.md

## 0.5.3 — 2026-08-04

- Add --max-rows pattern slicing (94 default, 128 = Goattracker's real MAX_PATTROWS); 65/95 at 128

## 0.5.2 — 2026-08-04

- Bounds-guard the instrument-table walk (`detect.py`) and the pattern-table
  index (`patterns.py`). Both read before checking, crashing with `IndexError`
  on `I_Ball.sid`; a negative offset would have silently indexed from the end
  of the file.
- Re-index orderlists correctly after a command byte. The old sticky
  `end_marker` latched on any byte `>= $D0`, so the first Mega Apocalypse-family
  transpose (`$E0-$FF`) left every following pattern number pointing at
  pre-split indices. Only `$FF` (restart) now consumes an operand; repeat and
  transpose commands pass through without stopping re-indexing. Affects 17
  corpus files. Inherited from the VB6 original, which has the same latch.

## 0.5.1 — 2026-08-04

- Corpus survey harness (survey.py) + SURVEY.md: 60/95 Hubbard SIDs convert

## 0.5.0 — 2026-08-04

- Version tracking added (`h2g --version`, this changelog, `bump_version.py`).
- `H2G-CONVERSION-METHOD.md`: detailed write-up of the ripping method
  (signature matching, address extraction, Hubbard pattern format, pattern
  slicing/re-indexing, `.sng` layout, failure modes).
- `convert.ps1`: PowerShell wrapper for running a conversion from the repo root.

## 0.4.0 — initial Python port (committed as 127b2fa)

- From-scratch Python CLI port of the VB6 H2G tool: `sidfile`, `search`,
  `detect`, `tracks`, `patterns`, `goatwriter`, `convert`, `cli`.
- Verified byte-exact against `Commando.sng` (15193 bytes, 0 differences).
- Fixed one transcription bug found by the byte-diff: `_write_wavetable`'s
  else-branch writes `[tail, 0xFF, 0xFF]`, not `[tail, 0xFF, tail]`.
- `tests/test_commando.py` regression test.
