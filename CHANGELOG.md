# Changelog

Versioning: the single source of truth is `__version__` in
`python/h2g/__init__.py`. Bump the patch on every commit with
`python python/bump_version.py "short description"`.

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
