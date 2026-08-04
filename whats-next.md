<original_task>
Two sequential requests from the user in this conversation:

1. `/init` — analyze the repository and create a `CLAUDE.md` file for future Claude
   Code instances working in this repo.
2. "the goal is to create a python commandline version that can be redeveloped with
   new features. we will use the song command.sid and commando.sng as orignals for
   testing." — i.e. port the existing VB6 SID→Goattracker converter to a Python CLI
   that future feature work will build on top of, and validate it against the existing
   `Commando.sid` / `Commando.sng` pair as ground truth.

No further feature request has been made yet — the user's closing message just asked
"what feature you want to build first" and the conversation ended before they answered.
</original_task>

<work_completed>

## 1. Repository analysis + CLAUDE.md

Explored the repo at `C:\Users\mit\claude\c64server\hubbard` (note: this directory is
itself *inside* a larger parent git repo rooted at `C:\Users\mit\claude\c64server`,
which is why `git log`/`git status` from within `hubbard` show unrelated history from
a sibling project `siddetector2` — `hubbard` was untracked/new at session start, per
the initial `gitStatus` block showing `?? ./` for the hubbard directory).

Read the entire original VB6 source, `VB6 Sourcecode/h2g.frm` (1311 lines), in full,
including every Sub/Function:
- `Form_Load`, `ShowAboutText`, `DoShow`, `Picture1_Click`, `Text1_OLEDragDrop`,
  `Frame1_OLEDragDrop`, `Command1_Click`, `AddTextS` (lines 152-192)
- `loadfile()` (193-481) — the main driver: PSID header parse, signature-based
  detection, dispatch to conversion+save
- `GoatSave()` (482-772) — writes the final `.sng` binary
- `FormHex`, `FileExist`, `TrimPath` (773-793)
- `GoatClear()` (794-817) — header/table zeroing + GTS2 magic + name/author/released
- `GoatConvertPattern()` (818-1097) — pattern decode + slicing + track re-indexing
- `GoatConvertTracks()` (1100-1231) — track/subsong byte-stream decode
- `GoatAddString`, `SSearchfile`, `HexToDec` (1232-1310)

Wrote `C:\Users\mit\claude\c64server\hubbard\CLAUDE.md` (created fresh — no prior
CLAUDE.md existed). Content, in order:
- **What this is**: H2G = "Hubbard 2 Goattracker", VB6 tool by Stilianos "Stello"
  Doussis (Aug 2005), free/open source per the in-app about text. Described as a
  **signature-based disassembly ripper** — does not emulate the 6502, scans raw SID
  bytes for known player-engine opcode fingerprints per game.
- **Repository layout** section (later revised — see below).
- **Build/run** section for the VB6 side (VB6 IDE, `VB6.EXE /make`, `COMDLG32.OCX`
  dependency, no automated tests, manual verification via Goattracker playback).
- **Architecture** section walking through `loadfile()` → `GoatConvertTracks` →
  `GoatConvertPattern` → `GoatSave`, naming every game whose signature appears in the
  detection chains (IK+, Warhawk, Mega Apocalypse, Ricochet, Last V8, Delta, Battle of
  Britain, Samantha Fox, SaboteurII, ACE2, Chimera, Rasputin, Human Race, Hollywood or
  Bust, Harvey Smith Show Jumper, Auf Wiedersehen Monty).
- **Key constraint** callout: detection only works for SID files whose player binary
  matches one of the hard-coded signatures; adding a new game means adding a new
  signature+offset to the fallback chains.

After the Python port was built (see below), `CLAUDE.md` was **revised** (not
rewritten from scratch) to:
- Reframe `python/h2g/` as the **active development target** in the repo-layout list,
  with the VB6 source repositioned as "reference implementation the Python port was
  derived from and is verified against".
- Add `Commando.sid`/`Commando.sng` to the repo-layout list explicitly as the
  regression-test fixture pair, noting `Commando.sng` was produced by the original
  `h2g.v1.2.exe` and the Python port must reproduce it byte-for-byte.
- Insert a new **"Python port (`python/h2g/`)"** section (placed before the VB6
  build/run section) documenting: how to run (`python -m h2g <input.sid> [-o out.sng]
  [-q]`), how to test (`python -m pytest tests/ -q` from `python/`), and a per-module
  breakdown mapping each `.py` file to the VB6 function(s) it ports, plus a note about
  the one non-obvious equivalence proof (`patterns.py`'s `_slice_pattern`, see below)
  and an explicit instruction that **the VB6 source remains ground truth** — re-derive
  from `h2g.frm` rather than trusting the Python port's own comments if they ever seem
  to disagree.
- Relabeled the old VB6 build/run section header to "VB6 original — build/run
  (reference only, not actively developed)".

The final `CLAUDE.md` is complete and was not touched again after this revision.
Current full content is in the file itself; no further changes pending.

## 2. Python port: `python/h2g/` package

Created fresh at `C:\Users\mit\claude\c64server\hubbard\python\h2g\`. Plain-stdlib
Python 3 (developed/tested against Python 3.14.0 on Windows), no third-party runtime
dependencies. `pytest` (9.0.1, already installed in the environment) used as a
dev-only test dependency.

### Files created (all under `python/`):

**`h2g/__init__.py`** — one-line package docstring, no exports.

**`h2g/sidfile.py`** — PSID/RSID header parsing.
- `HLEN = 0x7F` constant — documented as `dataOffset(0x7C for v2NG) + 2-byte embedded
  load address, then -1 applied in to_offset()`. Explicit design note in the module
  docstring: the original VB6 tool does **not** read the PSID `dataOffset` header
  field at all — it hardcodes a fixed v2NG (124-byte) header size. This is preserved
  exactly rather than "fixed", since fidelity to the original was the priority.
- `SidFormatError` exception class.
- `SidFile` dataclass: `path, data (raw file bytes), name, author, released,
  load_addr, subtunes`, plus a `to_offset(addr)` method implementing the VB formula
  `addr - load_addr + HLEN - 1` (C64 address → byte offset into `data`).
- `_read_padded_string(data, offset, length)` — replicates the VB behavior of
  filtering out **all** zero bytes in the field range (not just trailing padding) and
  concatenating the rest as chars.
- `load_sid(path)` — reads the whole file into `data`; validates size (`< 65536`,
  `MAX_SID_SIZE` constant) and magic (`data[1:4] == b"SID"`, matching both "PSID" and
  "RSID"); a length guard `len(data) < 0x7E` was added defensively (not in the
  original, which would just crash with an index error on truncated files — this is a
  minor, harmless improvement, explicitly noted as such rather than silently
  diverging). Reads: name at `data[0x16:0x36]`, author at `data[0x36:0x56]`, released
  at `data[0x56:0x76]` (all 32-byte fields, matches PSID spec offsets exactly once you
  account for VB's 1-based `Get` file positions — this was hand-verified against the
  PSID spec during analysis, see Critical Context below); `load_addr =
  data[0x7D]*256 + data[0x7C]` (embedded PRG-style load address, little-endian, read
  from the first 2 bytes of the *data* section under the fixed-header assumption, NOT
  from the PSID `loadAddress` header field); `subtunes = data[0x0F]` (low byte of the
  big-endian "songs" field at 0x0E-0x0F, assumes song count < 256).

**`h2g/search.py`** — wildcard byte-pattern search, port of `SSearchfile`
(h2g.frm:1243).
- `search_file(data: bytes, pattern: str) -> int`. Pattern syntax: space-separated
  2-hex-digit tokens or `"??"` for a single-byte wildcard (e.g.
  `"BD ?? ?? 99 02 D4"`).
- Implementation note: the VB original has a real off-by-one quirk (loop condition
  `ix <= inumb` instead of `ix < inumb`, reading one token past the wildcard array,
  which defaults to VB's zero-initialized `Long` array element = 0 instead of the
  sentinel -1) — this was analyzed in depth and **proven to be dead/unreachable code**
  (the early-exit `If ixf >= findnumbers Then Exit Function` always fires before that
  extra index is reached, for every pattern actually used in the codebase, including
  the degenerate all-wildcard case). It was deliberately **not** replicated; the
  Python implementation just does correct bounds-checked token matching. This
  simplification is safe and was reasoned through carefully, not guessed.
- The search still starts at `i = 1` (not 0) to match the VB original's behavior of
  never testing offset 0 as a match start (harmless in practice — all real signatures
  are found well past the ~0x7F-byte PSID header).

**`h2g/detect.py`** — player-engine signature detection, port of the
`FindInstruments`/`FindSubSongs`/`FindTrackSelector`/`FindPattern`/
`FindPlayerVersion` blocks inside `loadfile()` (h2g.frm:300-473).
- `WAVEFORMS` set — the 20 known Hubbard waveform-byte values (0x00, 0x01, 0x09, 0x11,
  0x13, 0x15, 0x17, 0x21, 0x23, 0x25, 0x27, 0x41, 0x43, 0x45, 0x47, 0x51, 0x53, 0x55,
  0x57, 0x81) used to find the instrument table's end.
- `Detection` dataclass: `instr_start, instr_used, track_voices (default 3),
  track_selector (bool), track_hi, track_lo, pattern_hi, pattern_lo, pattern_used,
  read_track_version (default 0xFF = "undetected")`, plus a `can_convert` property
  checking `track_lo/hi > 0 and pattern_lo/hi > 0` (matches the VB `DoRip` gating
  logic exactly — notably this does **not** require `instr_start` or
  `read_track_version` to have been found, matching the original's — arguably buggy —
  behavior).
- `detect(sid, log) -> Detection` — ports all five detection chains verbatim,
  including every signature string and every `so` (byte offset) value, with inline
  comments naming the source game for each signature (carried over from the VB
  comments). Each chain was individually hand-traced against the VB single-line
  `If...Then a: b` colon-chaining semantics (see Critical Context — this was a
  significant source of potential transcription error that was worked through
  carefully) to confirm behavior matches, including the subtlety that the
  track-selector block (Rasputin/"Human Race") **overwrites** `track_lo`/`track_hi`
  found by the earlier subsong-table search when a selector is present.

**`h2g/tracks.py`** — port of `GoatConvertTracks` (h2g.frm:1100-1231).
- `DEFAULT_TRACK = [0x00, 0xFF, 0x00]` — the fallback 3-byte track content used when a
  voice is absent or its address is out of range.
- `_build_track(data, addr, version) -> List[int]` — decodes one voice's raw Hubbard
  track byte-stream into Goattracker track bytes, branching on
  `det.read_track_version` (0-3 = "Warhawk"-style, 4 = "ACE 2"-style, 5-7 =
  "Mega Apocalypse"-style with transpose commands). Raises `ValueError` for any other
  version value — this is a **deliberate deviation** from the original: if
  `read_track_version` is 0xFF (undetected), the VB code's `Select Case` has no
  matching branch and the `Do` loop **never terminates and never advances its length
  counter**, eventually reading past the fixed-size `SIDfile` array and crashing with
  a VB runtime error. This was identified as an unintended crash bug, not a real
  behavior to replicate, so the Python port raises a clear exception instead. This
  case is reachable in practice (`det.can_convert` doesn't check
  `read_track_version`), so it's a real code path, just deliberately hardened rather
  than faithfully broken.
- `convert_tracks(sid, det, log) -> List[List[int]]` — outer driver: for each subtune
  × 3 voices, computes `so = voice + i*(track_voices*2)`, reads the 16-bit address
  from the `track_hi`/`track_lo` tables, converts via `sid.to_offset`-equivalent
  arithmetic, and calls `_build_track` (or falls back to `DEFAULT_TRACK` with a
  logged warning if out of range or voice index >= `track_voices`).

**`h2g/patterns.py`** — port of `GoatConvertPattern` (h2g.frm:818-1097). This was the
most analytically intensive part of the port — see Critical Context for the full
derivation.
- Constants: `GT_MAX_PATTERN_LEN = 376` (94 rows × 4 bytes), `GT_NO_NOTE = 0xBD`,
  `MAX_PATTERNS = 0xD0` (208), `MAX_TRACK_LEN = 0xFF`, `ERROR_PATTERN = [0xBD, 0x00,
  0x00, 0x00, 0xFF, 0x00, 0x00, 0x00]` (the fixed 8-byte pattern substituted when a
  pattern's address is out of range).
- `ConversionAbort` exception (for the two `Exit Function` "too many patterns" /
  "tracklist too long" abort paths in the original).
- `_build_raw_pattern(data, addr) -> Optional[List[int]]` — decodes one Hubbard
  pattern into a flat Goattracker event stream (4 bytes/row: note, instrument,
  command, command-value), returns `None` if the address (or any mid-pattern read) is
  out of bounds. Faithfully ports every bit of the VB status-byte decoding: `nGetNext`
  (bit 0x80), `nNoNote` (0x40), `nNoADSR` (0x20), `nWait` (0x1F); the pitch-bend vs
  instrument-change branching in the second byte; the `gOLDInstrument1`/`2` tracking
  used to detect "same instrument repeated" for portamento (command 3); the
  `RescInstrNr` rescue-and-restore dance for the "note is silence but instrument
  changed" case; the note-clamping (`>= 0x5C → 0x5C`, then `+= 0x60`).
- `_slice_pattern(events) -> List[List[int]]` — a from-scratch, algebraically-derived
  equivalent of the VB slicing loop (see Critical Context for the derivation). Chunks
  a flat event stream into ≤376-byte pieces via `while n - pos >= GT_MAX_PATTERN_LEN`,
  **always appending a trailing slice even if empty** — this reproduces a genuine VB
  quirk where a pattern whose length is an *exact* multiple of 376 bytes produces one
  extra zero-length trailing pattern that gets referenced in the track list. This was
  proven correct by hand-simulating the VB loop across three cases (simple/no-split,
  split-with-remainder, split-exact-multiple) and is documented in the function's
  docstring.
- `convert_patterns(sid, det, log) -> (new_patterns, track_index)` — outer driver:
  decodes all `det.pattern_used + 1` raw patterns (substituting `ERROR_PATTERN` +
  logging on out-of-range), then slices each one via `_slice_pattern`, appending to a
  flat `new_patterns` list and building `track_index[i] = list(range(start, end))`
  (the list of new pattern numbers original pattern `i` was split into). Logs
  `"Extending Pattern: $i ($n)"` once per non-final slice (matching original log
  cadence exactly) and raises `ConversionAbort` if `len(new_patterns) >= 0xD0`.
- `reindex_tracks(tracks, track_index) -> List[List[int]]` — port of the track
  re-indexing block (h2g.frm:1062-1096): for each track byte, if it's `>= 0xD0`
  (already a special/end-marker byte, e.g. `0xFF`, `0xFD`, or a Mega-Apocalypse
  transpose byte) or an "end marker" flag is already set, pass it through literally
  (and latch the end-marker flag so everything *after* it — e.g. the repeat-position
  byte following `0xFF` — also passes through unmodified); otherwise, look up
  `track_index[b]` and splice in that list of new pattern numbers. Includes a
  defensive `if b < len(track_index) else []` guard for the case where a track
  references a pattern index beyond what was decoded (matches the VB original's
  behavior of silently producing zero entries for out-of-range `TrackIndex` lookups,
  since that array is pre-initialized to -1 sentinels).

**`h2g/goatwriter.py`** — port of `GoatClear` + `GoatSave` (h2g.frm:482-772,
794-817).
- Explicit docstring note: `GoatTableWave`/`GoatTablePulse` (h2g.frm:132-133) are dead
  arrays in the original (written by `GoatClear`, never read anywhere else — verified
  via a targeted grep of the whole `.frm` file) and are correctly **not** modeled.
- `_field_bytes(text) -> bytes` — encodes a string latin-1, truncates/pads to exactly
  `FIELD_LEN = 0x20` (32) bytes with zero padding — this is what makes the header
  fields byte-exact (an earlier draft used `.ljust(0, b"")`, a no-op bug, caught and
  fixed before first test run — see Attempted Approaches).
- `_build_header(sid) -> bytearray` — builds the 100-byte (`HEADER_LEN = 0x64`) GTS2
  header: magic (4 bytes) + name/author/released (32 bytes each, at fixed offsets
  0x04/0x24/0x44).
- `_padded_name_bytes(name, width=16)` — pads/truncates instrument names to 16 bytes.
- `_write_instruments(out, sid, det) -> int` — writes instrument count byte
  (`det.instr_used + 1`, clamped to `MAX_INSTRUMENTS = 50`), the fixed "Clear Voice"
  empty instrument-1 slot, then each real instrument's 9 data bytes + 16-byte name
  (format `f"{i+2:02X}:{b5:02X}-{b6:02X}-{b7:02X}"` — **this three-part format was
  originally transcribed missing the third `-{b7:02X}` component and was caught and
  fixed** before the byte-diff test, see Attempted Approaches). SR byte clamping
  (`if sr >= 0xF0: sr &= 0xEF`) ported verbatim.
- `_write_wavetable(out, sid, det, instr_used)` — writes the LEFT-side then
  RIGHT-side wavetable data. **This function contained the one real bug found during
  verification** (see Attempted Approaches / Critical Context): the VB `Else` branch
  of the "3rd-5th Tick Wavetable" write (h2g.frm:665-670) writes `[tail, 0xFF, 0xFF]`
  — not `[tail, 0xFF, tail]` — because `b1` is reassigned to `&HFF` once and then
  `Put`  a second time *without being reassigned back*. Fixed at
  `goatwriter.py` (search for `tail, 0xFF, 0xFF` in `_write_wavetable`'s
  else-branch). Also ports the arp-note "jump to" instrument-loop byte
  (`((i+2)*5) - 2`) for the RIGHT-side ArpStyle-bit-2 (`&4`) case, and preserves a
  literal dead-code note: the VB condition `((ArpStyle And 1) = 1) Or ((ArpStyle And
  4) = 1)` — the second disjunct is **always false** (bitwise AND with 4 yields 0 or
  4, never 1) — the Python port keeps only the equivalent `(arp_style & 1) == 1` check
  with an inline comment flagging the dead VB disjunct, rather than replicating dead
  code.
- `_write_pulsetable(out, sid, det, instr_used)` — pulse-hi table (with bit 7 forced
  set, `0xFF` end markers) then pulse-lo table (with `0x00` "no transpose" / end
  markers).
- `build_sng(sid, det, tracks, patterns) -> bytes` — top-level assembly: header +
  subtunes byte + tracks (length-byte + data per track) + instruments + wavetable +
  pulsetable + fixed 5-byte empty filter table (`02 11 FF 22 01`) + pattern count byte
  + patterns (length-nibble byte = `len(pattern)//4`, then data).

**`h2g/convert.py`** — orchestrator, port of the `FindEnd:` block in `loadfile()`.
- `UnsupportedSidError` exception (raised when `det.can_convert` is false — the VB
  `"NO HUBBARD PLAYER DETECTED, CAN'T CONVERT"` case).
- `convert(sid_path, log=print) -> bytes` — calls `load_sid` → logs SID info → `detect`
  → logs status → (if convertible) `convert_tracks` → `convert_patterns` →
  `reindex_tracks` → `build_sng`, returning the final `.sng` bytes. Log messages
  mirror the original's section-header formatting (`"---SID INFO---"` etc.) closely
  enough to be recognizable but were not required to match character-for-character
  (only the *file output* was required to be byte-exact, not the console log text).

**`h2g/cli.py`** — argparse CLI: `h2g <sid_file> [-o/--output OUT] [-q/--quiet]`.
Default output path = input path with `.sid` extension replaced by `.sng`
(`_default_output`). Catches `SidFormatError`, `UnsupportedSidError`,
`ConversionAbort` and prints `"error: {msg}"` to stderr with exit code 1; otherwise
writes the file and prints a byte-count confirmation to stderr, exit code 0.

**`h2g/__main__.py`** — thin `python -m h2g` entry point delegating to `cli.main()`.

**`python/tests/test_commando.py`** — the regression test:
```python
def test_commando_matches_reference():
    sng = convert(str(REPO_ROOT / "Commando.sid"), log=lambda msg: None)
    reference = (REPO_ROOT / "Commando.sng").read_bytes()
    assert sng == reference
```
`REPO_ROOT` resolved via `pathlib.Path(__file__).resolve().parents[2]` (i.e.
`python/tests/test_commando.py` → up 2 levels → `hubbard/`). **This test currently
passes** (confirmed via `python -m pytest tests/ -q` → "1 passed", run from
`python/`).

**`python/.gitignore`** — created with `__pycache__/`, `*.pyc`, `.pytest_cache/`, and
those directories were subsequently deleted from disk (see Current State) so they
don't show up as untracked cruft.

## 3. Verification work performed

1. First end-to-end run: `python -m h2g "../Commando.sid" -o "out_commando.sng" -q`
   from `python/` — succeeded, produced a file of exactly 15193 bytes (matching
   `Commando.sng`'s size exactly).
2. Byte-diff script (inline Python, not saved as a file) found **7 single-byte
   differences**, all following the pattern "mine has a tail-wave byte (e.g. 0x41),
   reference has 0xFF" at offsets 0x322, 0x32c, 0x336, 0x340, 0x34a, 0x359, 0x35e.
3. Root-caused by: (a) computing exactly which output section each offset fell into
   by replaying the write-order arithmetic inline in Python (header 0x64 bytes +
   subtunes byte + per-track lengths → landed in the "left wavetable" section,
   0x318-0x35f); (b) dumping per-instrument `ArpStyle` values directly from
   `det`/`sid.data` for all 13 real instruments in Commando.sid; (c) correlating: every
   diverging offset corresponded to an instrument with `arp_style & 4 == 0` (the
   "Else" branch); (d) dumping the full raw byte sections from both files side by side
   and confirming instrument-by-instrument that mine produced `[tail, 0xFF, tail]` and
   reference produced `[tail, 0xFF, 0xFF]` for every else-branch instrument; (e)
   re-reading h2g.frm lines 658-670 character-by-character and finding the actual bug:
   `Put #fsff, , b1` appears **twice** after `b1 = &HFF` in the Else branch (writes FF
   twice), not once-tail-once-FF as originally (mis)transcribed.
4. Applied the one-line fix in `goatwriter.py`'s `_write_wavetable` (else branch:
   `bytes([tail, 0xFF, tail])` → `bytes([tail, 0xFF, 0xFF])`).
5. Re-ran the conversion + diff: **0 differences, both files 15193 bytes** — exact
   match confirmed.
6. Smoke-tested (no reference `.sng` available for these, just checked for crashes)
   against the two other sample files in `arkiv/`: `Bump_Set_Spike.sid` (→ 19770
   bytes, many "Extending Pattern" log lines, exit 0) and `Crazy_Comets.sid` (→ 19651
   bytes, exit 0). Both completed without errors. (Note: output was written to a file
   literally named `nul` due to Git-Bash mangling `/dev/null` — this was cleaned up
   immediately after, see Attempted Approaches. This is unrelated to a **pre-existing**
   stray `nul` file at `C:\Users\mit\claude\c64server\nul`, dated Dec 16 2025, which
   was present before this session started per the initial `gitStatus` block and was
   correctly left untouched.)
7. Added the formal `pytest` regression test (`test_commando.py`) and confirmed it
   passes standalone.
8. Cleaned up `python/.pytest_cache/`, `python/h2g/__pycache__/`,
   `python/tests/__pycache__/`, and the stray `out_commando.sng` test-output file from
   disk (kept the repo tree clean of generated artifacts).

Used `TaskCreate`/`TaskUpdate` to track two tasks during this work, both now marked
`completed`:
- Task #1: "Port track/pattern conversion + goattracker writer + CLI"
- Task #2: "Verify byte-exact output against Commando.sng"

</work_completed>

<work_remaining>
No further work was explicitly requested. The conversation ended with the assistant
asking the user what feature they want to build first — **that answer was not yet
given** when this handoff was generated. Candidate next steps, none confirmed:

1. **Await/elicit the user's first feature request** for the Python port. The user's
   stated goal was "a python commandline version that can be redeveloped with new
   features" — the port itself was step one; no specific feature has been named yet.
2. **Optional hardening / follow-ups noticed but not requested, so not done:**
   - No `setup.py`/`pyproject.toml`/`requirements.txt` exists for the `python/`
     package — it currently only runs via `python -m h2g` from inside the `python/`
     directory (relies on Python's implicit `sys.path` handling of the current
     directory for the `h2g` package to be importable). If the user wants it
     installable (`pip install -e .`) or runnable from any CWD, that would need a
     packaging file added.
   - Only one regression fixture exists (`Commando.sid`/`Commando.sng`). The two other
     sample SIDs in `arkiv/` (`Bump_Set_Spike.sid`, `Crazy_Comets.sid`) were only
     smoke-tested (checked for crash-free execution), **not** verified byte-exact
     against any reference `.sng`, because no reference `.sng` exists for them. If
     byte-exact confidence beyond Commando is wanted, the user would need to either
     (a) run the original `arkiv/h2g.v1.2.exe` against those two files to produce
     reference `.sng` outputs (the exe is present and this is a native Windows exe, so
     it's runnable in this environment, but doing so requires either GUI automation —
     drag-and-drop or the Browse/Load dialog — or discovering/adding a headless mode,
     neither of which was attempted this session), or (b) accept lower confidence for
     those two.
   - No git commit has been made. All new files (`CLAUDE.md`, entire `python/`
     directory) are currently **untracked/uncommitted** in the parent git repo (recall
     `hubbard/` itself was untracked at session start too — `?? ./` in the initial
     `gitStatus`). If the user wants this committed, that's a distinct, not-yet-taken
     step (the assistant explicitly said "Nothing has been committed" in its last
     message and asked whether to commit).
   - CLI currently only supports single-file conversion. No batch/directory-mode, no
     `--verbose`/log-level control beyond `-q`, no way to dump intermediate
     representations (e.g. decoded patterns/tracks) for debugging — all plausible
     future "redevelop with new features" directions but none requested yet.
3. If the user's next feature touches `patterns.py` or `goatwriter.py`, re-read the
   relevant `h2g.frm` line ranges fresh (don't rely solely on the Python
   docstrings/comments) given how many subtle transcription pitfalls were found there
   already (see Attempted Approaches) — this is explicitly called out as guidance in
   the new CLAUDE.md Python-port section too.
</work_remaining>

<attempted_approaches>

## Bugs found and fixed during this session (both caught via the byte-diff
regression test against Commando.sng, i.e. the testing methodology worked exactly as
intended):

1. **`_field_bytes` header-padding no-op bug** (caught and fixed *before* the first
   test run, during code review of the just-written `goatwriter.py`, not via the
   diff): an early version of `_build_header` used
   `sid.name.encode(...)[:FIELD_LEN].ljust(0, b"")` — `.ljust(0, ...)` is a no-op
   (padding to width 0 never extends anything), and worse, **direct bytearray slice
   assignment with a shorter replacement shrinks the bytearray** (Python slice
   assignment changes length when replacement length differs from the slice length),
   which would have silently corrupted the header layout for any name/author/released
   string shorter than 32 characters. Fixed by introducing `_field_bytes(text)` which
   explicitly does `raw.ljust(FIELD_LEN, b"\x00")` before assignment. This was caught
   by code self-review, not by running anything — worth knowing in case the same
   shrink-via-slice-assignment footgun recurs elsewhere.

2. **Missing third hex component in instrument name** (also caught pre-test, via
   comparing the freshly-written Python against the VB source read earlier in the
   session): initial `_write_instruments` built the instrument name as
   `f"{i+2:02X}:{b5:02X}-{b6:02X}"`, omitting the VB original's third `-{b7:02X}`
   segment (`iStr = FormHex(SIDfile(SIDRHinstrStart + i2 + 7)); iName = iName + iStr`
   at h2g.frm:602-603). Fixed before running the diff test. Note: this particular bug
   would **not** have been caught by the Commando.sng byte-diff if it had shipped,
   because instrument names are stored in a 16-byte fixed field and a shorter name
   just changes the zero-padding count — the string content itself doesn't affect the
   binary length, only which bytes are 0x00 vs a hex digit, so a diff WOULD actually
   catch it (confirmed post-hoc: it would show up as extra 0x00 bytes at the tail of
   each instrument-name field replacing hex-digit ASCII bytes). It's flagged here
   because it was actually caught by manual code review before ever running the test,
   not because it was invisible to the test.

3. **The one bug that *did* surface via the byte-diff test**: `_write_wavetable`'s
   Else-branch (ArpStyle bit 4 not set) originally wrote `[tail, 0xFF, tail]`. Full
   root-cause chain documented in Work Completed §3 above. This was a genuine
   misreading of h2g.frm lines 665-669 on first pass — the VB `Put #fsff, , b1`
   appearing twice in a row after `b1 = &HFF` (writing the *same* just-reassigned FF
   value twice) reads, at a skim, like it might write `[tail, 0xFF]` then something
   else, and it's easy to assume symmetry with the `If` branch (which does
   `Put b1(tail); Put b1(tail); b1=FF; Put b1(FF)` = `[tail,tail,FF]`) and guess the
   Else branch is `[tail, FF, tail]` by "obvious" symmetry — it is not; both `Put`s
   after the reassignment write FF. **Lesson for future work in this codebase:
   never assume symmetry between VB If/Else branches — re-read both branches
   line-by-line independent of what the other branch does.**

## Approaches considered and explicitly rejected (with reasoning), not because they
failed but because deeper analysis showed a simpler equivalent was correct:

1. **Literally modeling `GoatPattern`/`NewGoatPattern`/`TrackIndex` as VB-style
   giant sparse zero-initialized 2D arrays** (via a Python helper class with
   `__getitem__`/`__setitem__` defaulting to 0) was seriously considered as the
   "safest" (most literal, lowest-transcription-risk) approach for `patterns.py`,
   given how many off-by-one/implicit-zero-fill subtleties were found in
   `GoatConvertPattern`'s slicing loop. Ultimately **not** used — instead, the
   behavior was derived algebraically to a closed-form equivalent
   (`_slice_pattern`'s plain chunking-with-trailing-slice approach), verified by hand
   across three cases (see Critical Context below), because it produces much cleaner,
   more maintainable code and was provably equivalent for all cases considered. If a
   future divergence is ever found in `patterns.py` behavior, **this is the first
   place to suspect** — the derivation was careful but not exhaustively tested against
   every possible original-pattern-length residue mod 376 in a real file, only proven
   by symbolic/hand-trace argument plus the one successful Commando.sng byte-exact
   match (which did exercise many "Extending Pattern" boundary-crossings — 19 of them
   for Commando.sid alone per the log output — lending real empirical confidence, but
   didn't specifically hit the "exact multiple of 376" edge case since no log line
   suggests a zero-length trailing pattern occurred in that file).
   
2. **Per-iteration `TrackIndex(i, i4)`-style incremental list building** for
   `track_index[i]` in `convert_patterns` was drafted first (appending on every `i2`
   iteration, mirroring the VB "overwrite every iteration" pattern literally) and was
   caught as **wrong** during code review before ever running: it would produce a list
   of length `plen+1` instead of one entry per slice. Replaced with the much simpler
   and correct `track_index.append(list(range(start, end)))` using the fact that new
   pattern numbers are assigned consecutively.

3. **Running the original `arkiv/h2g.v1.2.exe` directly** to generate reference
   outputs for the other two sample SIDs (`Bump_Set_Spike.sid`, `Crazy_Comets.sid`)
   was considered (the exe is a native Windows binary present in the repo, so this is
   technically feasible in this environment) but **not attempted**, because the app's
   only file-input paths are a Browse dialog and drag-and-drop OLE handling
   (`Frame1_OLEDragDrop`/`Text1_OLEDragDrop`), both of which require GUI automation
   that wasn't set up this session. Time/scope tradeoff, not a technical failure.

4. **First diff-debugging attempt used `/tmp_out.sng` as an output path** for the
   very first end-to-end CLI run — this failed with
   `PermissionError: [Errno 13] Permission denied: 'C:/Program Files/Git/tmp_out.sng'`
   because Git Bash (the Bash tool's shell) mangles absolute-looking Unix paths like
   `/tmp_out.sng` into a path under the Git-for-Windows install directory. Fixed by
   using a plain relative filename (`out_commando.sng`) instead. **Lesson: always use
   relative paths or explicit Windows-style paths when writing output files via the
   Bash tool in this environment, never a bare `/xxx` absolute-looking path.**

5. Similarly, smoke-testing against the `arkiv/` sample SIDs used
   `-o "/dev/null"` intending to discard output, which Git Bash mangled into a
   literal file named `nul` in the current directory (not a symlink to the real
   null device) — this created a 0-byte-content-but-nonzero-length stray file that
   was manually `rm -f`'d afterward. **Lesson: don't rely on `/dev/null` working as
   expected through this Bash tool on Windows; if truly discarding output, write to a
   scratch filename and delete it afterward, or check output size only.**
</attempted_approaches>

<critical_context>

## PSID header format facts, hand-verified against the VB source (not just assumed
from convention — per the user's global CLAUDE.md instruction to verify identifiers/
specs/facts against real sources before stating them):

- VB's `Get #fsff, position, var` for Binary-mode files uses **1-based** file
  positions (position 1 = the first byte of the file, offset 0).
- The original `loadfile()` loop `For i = 1 To fslen: Get #fsff, i, b1:
  SIDfile(i - 1) = b1` therefore maps `SIDfile(k)` (0-based) directly onto file byte
  offset `k` (0-based) — i.e. `SIDfile` and a Python `data: bytes` read via
  `open(path,'rb').read()` are **identical**, index-for-index. This is why
  `sidfile.py`'s `SidFile.data` is just the raw file bytes with no transformation.
- Header field offsets, cross-checked against 1-based VB `Get` positions → 0-based
  byte offsets → standard PSID spec offsets: name field at 1-based `&H17`
  (=0-based 0x16, spec: name), author at 1-based `&H37` (=0-based 0x36, spec: author),
  released/copyright at 1-based `&H57` (=0-based 0x56, spec: copyright). All three
  match the documented PSID header layout exactly (magic 4B, version 2B, dataOffset
  2B, loadAddress 2B, initAddress 2B, playAddress 2B, songs 2B, startSong 2B, speed
  4B = 22 bytes total header-so-far = 0x16, then name(32)/author(32)/released(32)).
- **Load address is NOT read from the PSID `loadAddress` header field.** It's read
  from 1-based positions `&H7D`/`&H7E` (0-based 0x7C/0x7D), which is the *start of
  the music data section* under the assumption of a fixed v2NG header length (0x7C =
  124 bytes). This only makes sense if the PSID's `loadAddress` header field is 0
  (meaning "load address is embedded as the first 2 bytes of the data, PRG-style") —
  the tool doesn't check this, it just always reads those 2 bytes as the load
  address, ignoring the real `loadAddress` header field entirely and ignoring the
  actual `dataOffset` field (it hardcodes 0x7C instead of reading the field at
  0-based offset 0x06). This is a genuine limitation/assumption baked into the
  original tool (works for how these particular old Hubbard-conversion SID files were
  packaged, not necessarily for arbitrary PSID files) and was **preserved exactly**
  in the Python port, documented explicitly in `sidfile.py`'s module docstring rather
  than silently "fixed" to be spec-correct — because the goal was fidelity to the
  original tool's actual behavior, which the byte-exact Commando.sng test validates.
- `HLEN = 0x7F` = `dataOffset(0x7C) + 2 (embedded load-addr bytes) + 1` — derived
  algebraically from matching the VB `to_offset` formula `addr - load_addr + HLEN - 1`
  against the requirement that a C64 address equal to `load_addr` should map to file
  offset `dataOffset + 2` (the first real code byte after the embedded load address
  word). Confirmed: `load_addr - load_addr + 0x7F - 1 = 0x7E = 0x7C + 2`. ✓.
- Subtune count is read as a **single byte** from 0-based offset 0x0F (1-based `&H10`)
  — this is the *low byte* of the PSID "songs" field, which spec-wise occupies
  0x0E-0x0F as a big-endian 16-bit value. The tool implicitly assumes song count <
  256 (never reads the high byte at 0x0E). Preserved as-is (`data[0x0F]`).

## VB6 language semantics that mattered for correct porting (worth knowing if editing
detect.py/tracks.py/patterns.py further):

- **Single-line `If cond Then stmt1: stmt2` colon-chaining**: all statements after
  `Then` on one line are the full conditional body — ALL of them execute together iff
  `cond` was true, none execute otherwise. This is easy to misread as "stmt1 is
  conditional, stmt2 always runs" if skimming. This pattern appears throughout the
  detection chains in `detect.py` (e.g. `If i <= -1 Then i = SSearchfile(...): so = 5`
  — both the search AND the `so` reassignment are gated on the same condition) and was
  hand-verified statement-by-statement for every chain during porting.
- **`Select Case` evaluates in order, first match wins** — used in
  `GoatConvertTracks`' `Select Case SIDRHreadTrackVersion`, where `Case 4` (ACE2)
  appears *before* `Case 0, 1, 2, 3, 4` (Warhawk-style) — meaning the literal `4` in
  the second case list is **dead/unreachable** (version 4 always matches the first
  `Case 4` first). Confirmed by re-reading VB `Select Case` semantics and reflected in
  `tracks.py`'s `_build_track`: `version == 4` is its own branch, and the "Warhawk"
  branch's condition is `version in (0, 1, 2, 3)` — deliberately **not** including 4,
  correctly matching the VB's actual reachable behavior rather than the misleading
  literal case-list text.
- **VB `For x = A To B` with `B < A` executes zero times** (no error, just skipped) —
  relevant to e.g. `GoatSave`'s instrument-writing loops (`For i = 0 To
  SIDRHinstrUsed - 2`, which is skipped entirely when `SIDRHinstrUsed <= 1`) and to
  the pattern data-write loop when `GoatPLength(i) - 1 < 0`. The Python port's `max(n,
  0)`/`range()` usage throughout `goatwriter.py` and elsewhere relies on Python's
  `range()` having the same "empty if end <= start" semantics, so no special-casing
  was needed beyond using `range()` naturally — but this was explicitly reasoned
  through rather than assumed.
- **VB `Byte` array elements silently truncate/error on out-of-range assignment**
  (0-255 only; a `Long` value outside that range raises an Overflow error, doesn't
  silently wrap) — but every value actually assigned to a `Byte` slot in this codebase
  is guaranteed by construction to be in 0-255 range (verified by tracing the max
  possible value of each computed quantity, e.g. `gInstrument = (b1b & 0x7F) + 2` maxes
  at 129), so the Python port doesn't need explicit masking/overflow simulation
  anywhere it writes final bytes — this was a deliberate simplification decision,
  reasoned through rather than defensively masked everywhere "just in case".

## The `_slice_pattern` equivalence derivation (the single most intricate piece of
analysis in this session — if this function is ever modified, this reasoning should
be redone, not assumed to still hold):

The VB slicing loop (h2g.frm:1013-1044) iterates `i2` from 0 to `GoatPLength(i)`
**inclusive** (one past the real data, i.e. `plen + 1` total iterations), reading a
"phantom" zero byte on the last iteration (since `GoatPattern(i, plen)` was never
written for pattern `i` but the array was globally zero-initialized at function
start). Separately, whenever the in-progress slice's local counter `i3` reaches
`GT_MAX_PATTERN_LEN` (376) — which, since `i3` increments by exactly 1 per iteration
starting at 0, always happens at *exactly* 376, never overshooting — the VB code
**explicitly records the current slice's length as exactly 376** (before the
phantom-byte issue can affect it), appends a real `[0xFF,0,0,0]` end-marker into the
array (dead weight, since the *next* pattern's `GoatSave` write loop uses the
recorded length of 376, excluding those 4 marker bytes), resets `i3`, and starts a
new slice. For the *final* trailing slice of each original pattern (the one active
when the outer `i2` loop ends, whether or not any 376-boundary was ever crossed), the
recorded length is **not** explicitly set in a boundary block — it's whatever `i3`
was as of the last write, which due to the "record-length-before-increment" ordering
always equals `(actual bytes written to that slice) - 1`, canceling out exactly
against the "+1 phantom byte" from the inclusive loop bound. Hand-simulating three
cases (length = exact multiple of 4 with no split; length requiring one split with a
nonzero remainder; length that's an *exact* multiple of 376) proved that after all
this bookkeeping cancels out, the **actual file-visible content** of every
produced slice is *exactly* its real (non-phantom, non-dead-marker) byte content —
i.e., **plain chunking of the true event stream into pieces of `GT_MAX_PATTERN_LEN`,
with a trailing slice always appended even if that trailing slice is empty**
(exact-multiple case) is provably equivalent to the VB original's actual on-disk
output, without needing to replicate any of the phantom-byte/array-zero-fill
machinery. This is what `_slice_pattern` implements. The empty-trailing-slice case
means: for a Hubbard pattern whose Goattracker-encoded event stream is *exactly*
94, 188, 282, 376... rows long, the Python port (matching the VB original) emits one
extra zero-row pattern referenced at the end of that pattern's slice sequence — this
is almost certainly an unintended VB quirk, not a deliberate design choice, but
preserving it was judged correct because the stated goal is byte-exact fidelity to
the original tool.

## Repository/environment facts:

- `hubbard/` is nested inside a **larger parent git repo** at
  `C:\Users\mit\claude\c64server` (confirmed: `git log`/`git remote -v` run from
  inside `hubbard/` return `siddetector2` project history and the
  `MichaelTroelsen/SIDDetector2` GitHub remote — this is the *parent* repo's history,
  not something wrong with `hubbard/` itself). `hubbard/` was entirely untracked
  (`?? ./`) at the very start of the session.
- The `rtk` (Rust Token Killer) CLI proxy wrapper is configured in this user's global
  environment (per `~/.claude/RTK.md`) but its git-hook auto-rewrite is **not
  installed** in this session (every `rtk proxy` invocation printed `[rtk] /!\ No hook
  installed — run 'rtk init -g' for automatic token savings`) — this is a persistent,
  harmless warning, not an error, seen on every `Bash` tool call in this session that
  used `rtk proxy`.
- Python environment: Python 3.14.0, pytest 9.0.1, both pre-installed and available
  via the plain `python` command on PATH — no venv was created or needed since the
  port has zero third-party runtime dependencies.
- The `Grep` tool was observed to fail with `EUNKNOWN: unknown error, uv_spawn` for
  regex patterns containing certain characters/anchors when targeting a path with a
  space in it (`VB6 Sourcecode/h2g.frm`) early in the session — worked around by
  falling back to `Bash` with `rtk proxy grep -n -E "..." "VB6 Sourcecode/h2g.frm"`,
  which succeeded. If the `Grep` tool is needed again against that same file/path,
  be aware it may need this same bash-grep fallback.
</critical_context>

<current_state>

## Deliverables status: all COMPLETE for the two requests actually made.

1. **`CLAUDE.md`** (`C:\Users\mit\claude\c64server\hubbard\CLAUDE.md`) — finalized,
   fully written, includes both the original VB6-focused content and the later
   Python-port revision. Not a draft; no further edits pending or planned.

2. **`python/h2g/` package** — complete, all 9 modules written
   (`__init__.py`, `sidfile.py`, `search.py`, `detect.py`, `tracks.py`, `patterns.py`,
   `goatwriter.py`, `convert.py`, `cli.py`, `__main__.py` — that's actually 10 files).
   Verified **byte-exact** against `Commando.sng` (0 differences across all 15193
   bytes). No known bugs remaining as of last verification.

3. **`python/tests/test_commando.py`** — complete, passing (`1 passed` via
   `python -m pytest tests/ -q`).

4. **`python/.gitignore`** — complete (`__pycache__/`, `*.pyc`, `.pytest_cache/`).

## What's temporary / cleaned up (not left behind):
- `out_commando.sng` (test-run output file) — deleted after verification.
- Stray `nul` file created by a Git-Bash `/dev/null` path-mangling issue during
  smoke-testing — deleted.
- `python/.pytest_cache/`, `python/h2g/__pycache__/`, `python/tests/__pycache__/` —
  all deleted from disk after the test run that generated them (kept the tree clean;
  `.gitignore` added so they won't be an issue if regenerated).

## Git state: NOTHING has been committed.
All of `CLAUDE.md` and the entire `python/` directory are new, untracked files in the
parent `c64server` git repo (working directory `hubbard/` was untracked at session
start, and no `git add`/`git commit` was run at any point this session). The
assistant's final message to the user explicitly stated this and asked whether to
commit — **no answer was received before the session ended**. A fresh instance
picking this up should either wait for explicit confirmation before committing (per
the standing instruction in this environment's system prompt: never commit unless
the user explicitly asks) or ask directly if that's ambiguous.

## Open question the conversation ended on:
The assistant's last message asked the user what feature they'd like to build first
on top of the new Python port. **This was not answered before the conversation
ended/context was handed off.** This is the natural resumption point: a fresh
instance should either wait for the user to specify a feature, or (if this handoff
doc is being read because the user already said something in a follow-up not
captured here) proceed based on whatever the user's next message actually says.

## No blockers, no unresolved errors, no failing tests as of hand-off.
</current_state>
