# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## What this is

H2G ("Hubbard 2 Goattracker") — a VB6 desktop tool that converts C64 `.SID` files
containing music by Rob Hubbard into Bitops Goattracker (`.sng`, v2.34+) format.
Originally written by Stilianos "Stello" Doussis in Aug 2005, released as free/open
source ("can be modified and republished ... used freely by others without notice").

The tool is a **signature-based disassembly ripper**: it does not emulate the 6502 or
run the SID player code. Instead it scans the raw SID file bytes for known 6502 opcode
byte-patterns ("fingerprints") specific to each Rob Hubbard player-engine variant, uses
matches to locate the tune's instrument table, pattern table, and track table in memory,
then re-encodes that data into Goattracker's native binary song format.

Repository layout:
- `python/h2g/` — **active development target**: a from-scratch Python CLI port of the
  VB6 tool (see "Python port" below). This is what new features should be built on.
- `VB6 Sourcecode/h2g.frm` — the original VB6 application (UI + logic) in a single form
  file (~1300 lines), kept as the reference implementation the Python port was derived
  from and is verified against. `h2g.frx` is VB6's companion binary resource file
  (icon/picture blobs referenced from `.frm` — not human-readable).
- `VB6 Sourcecode/h2g.vbp` / `.vbw` — VB6 project files (target: Win32 EXE, `h2g.v1.2.exe`).
- `arkiv/` — archived VB6 build (`h2g.v1.2.exe`, `h2g.v1.2.zip`) and sample `.sid` test files.
- `Commando.sid` / `Commando.sng` — reference input/output pair used for regression
  testing: `Commando.sng` was produced by the original `h2g.v1.2.exe` and the Python
  port must reproduce it byte-for-byte (`python/tests/test_commando.py`).

There is no build script, test suite, or CI for the VB6 side — it's a legacy GUI app
that would be maintained by hand-editing `h2g.frm` in the VB6 IDE if ever needed again.

## Python port (`python/h2g/`)

Plain-stdlib Python 3 CLI, no third-party runtime dependencies (`pytest` is a dev-only
test dependency).

- Run: `python -m h2g <input.sid> [-o output.sng] [-q]` (from `python/`), or
  `python -m h2g "../Commando.sid" -o out.sng`. From the repo root, `.\convert.ps1
  <input.sid> [-OutputFile out.sng] [-Quiet]` wraps the same thing.
- **Versioning — bump on every commit.** The single source of truth is `__version__`
  in `python/h2g/__init__.py` (exposed as `h2g --version`); there is no `.version`
  file, deliberately, so nothing can drift out of sync. Before each commit run
  `python python/bump_version.py "short description"` (add `--minor` for a feature
  release), which bumps the patch and prepends a `CHANGELOG.md` entry. Do not
  hand-edit the version in two places.
- Test: `python -m pytest tests/ -q` (from `python/`). The one test currently in place
  converts `Commando.sid` and asserts the output is byte-identical to `Commando.sng`;
  treat any output-changing edit as a regression unless it's an intentional new feature
  (in which case update/extend the reference fixtures, don't just delete the assertion).
- Module layout mirrors the VB6 pipeline 1:1, each stage in its own file:
  - `sidfile.py` — PSID/RSID header parsing (`load_sid`).
  - `search.py` — wildcard opcode-pattern search (`search_file`, port of `SSearchfile`).
  - `detect.py` — player-engine signature chains (`detect`, port of the
    `FindInstruments`/`FindSubSongs`/`FindTrackSelector`/`FindPattern`/
    `FindPlayerVersion` blocks in `loadfile()`). Returns a `Detection` dataclass.
  - `tracks.py` — `convert_tracks`, port of `GoatConvertTracks`.
  - `patterns.py` — `convert_patterns` + `reindex_tracks`, port of `GoatConvertPattern`
    (pattern decode, >376-byte pattern slicing, track pattern-number re-indexing).
  - `goatwriter.py` — `build_sng`, port of `GoatClear` + `GoatSave` (assembles the
    final `.sng` byte buffer: header, tracks, instruments, wave/pulse tables, patterns).
  - `convert.py` — orchestrates the above into one `convert(sid_path) -> bytes` call.
  - `cli.py` / `__main__.py` — argparse entry point.
- Unlike the VB6 original (which uses giant pre-sized, zero-initialized 2D arrays and
  1-indexed loop quirks), the port models data as plain Python lists/dataclasses. Where
  that required reasoning through non-obvious VB behavior (off-by-one loop bounds that
  read one past written data and rely on implicit zero-fill, e.g. the pattern-slicing
  loop in `GoatConvertPattern`), the equivalence is explained in a docstring/comment at
  the point it matters — see `patterns.py`'s `_slice_pattern`. When extending this port,
  re-derive from `h2g.frm` rather than from the Python code's comments alone if the two
  ever appear to disagree; the VB6 source is still the ground truth for what the
  original tool did, even though the Python port is now where new work happens.

## VB6 original — build / run (reference only, not actively developed)

Requires Visual Basic 6.0 (IDE or `VB6.EXE` command-line compiler) on Windows, plus the
`COMDLG32.OCX` common-dialog control referenced by the project.

- Open in IDE: open `VB6 Sourcecode/h2g.vbp` in the VB6 IDE, then Run (F5).
- Command-line compile: `VB6.EXE /make "VB6 Sourcecode\h2g.vbp"` (requires VB6 installed
  and `COMDLG32.OCX` registered via `regsvr32`).
- No automated test suite. Manual verification = load a known-Hubbard `.sid` file (e.g.
  `Commando.sid`, or the samples in `arkiv/`), confirm the status log detects a player
  and produces a `.sng`, then load that `.sng` in Goattracker to check playback.

## Architecture (all in `h2g.frm`)

Everything lives in one `Form1` code-behind file, organized as a top-to-bottom pipeline
triggered by `loadfile()` (from `Command1_Click`, drag-and-drop, or Browse):

1. **`loadfile()`** — the core driver.
   - Parses the PSID/RSID header (name/author/release strings, load address, subtune
     count) from fixed offsets (`&H17`, `&H37`, `&H57`, `&H7D`, `&H10`) per the PSID spec.
   - Loads the whole file into the `SIDfile()` byte array (max 64KB, C64 address space).
   - Calls `SSearchfile()` repeatedly with wildcard opcode-pattern strings (`??` = any
     byte) to locate, in order: the instrument table, the track/subsong table, an
     optional track-selector, the pattern table, and finally the specific Hubbard
     player-engine variant (`SIDRHreadTrackVersion`, 0–7) — each `If i <= -1 Then i =
     SSearchfile(...)` chain tries one known game's byte signature at a time (patterns
     are commented with the game they came from: IK+, Warhawk, Mega Apocalypse,
     Ricochet, Last V8, Delta, Battle of Britain, Samantha Fox, SaboteurII, ACE2,
     Chimera, Rasputin, Human Race, Hollywood or Bust, Harvey Smith Show Jumper, Auf
     Wiedersehen Monty). Every player variant needs its own hard-coded byte pattern
     here — adding support for a new game means adding a new signature + offset (`so`)
     to one of these chains.
   - If instrument/track/pattern locations were all found, calls the conversion
     pipeline: `GoatClear` → `GoatConvertTracks` → `GoatConvertPattern` → `GoatSave`.
2. **`GoatConvertTracks()`** — rewrites Hubbard's track data (which references
   pattern numbers with format/version-specific end/repeat markers, `$FE`/`$FF`,
   depending on `SIDRHreadTrackVersion`) into `GoatTracks()`.
3. **`GoatConvertPattern()`** — rewrites Hubbard's note/pattern data into
   `GoatPattern()` / `GoatPLength()`, including waveform/pulse table extraction
   (`GoatTableWave`, `GoatTablePulse`) and ADSR remapping for instruments.
4. **`GoatSave()`** — serializes `Goatfile()` header bytes + tracks + instruments +
   patterns into the on-disk Goattracker `.sng` binary structure via a file dialog
   (`FS`, the `MSComDlg.CommonDialog` control) and raw `Put #fsff` byte writes.

Helpers: `SSearchfile` (wildcard byte-pattern search over `SIDfile()`), `HexToDec`/
`FormHex` (hex string helpers used both for pattern parsing and instrument naming),
`FileExist`/`TrimPath` (filesystem helpers for the save dialog).

### Key constraint to know before editing

Because detection is entirely pattern-matching against known games' compiled player
code, **the tool only works on SID files whose player binary happens to match one of
the hard-coded signatures** — it explicitly cannot handle arbitrary/unknown Hubbard
player revisions, and README/UI text says so ("some RH tunes are not convertable to
Goattracker at all"). When modifying detection logic, preserve the existing
`If i <= -1 Then i = SSearchfile(...)` fallback chains — each entry is a distinct game
fingerprint and removing/reordering one can silently break detection for that game.
