# Changelog

Versioning: the single source of truth is `__version__` in
`python/h2g/__init__.py`. Bump the patch on every commit with
`python python/bump_version.py "short description"`.

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
