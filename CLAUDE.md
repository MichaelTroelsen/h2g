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

User-facing docs live in `README.md` (usage, versioning, testing, survey) and
`H2G-CONVERSION-METHOD.md` (how the ripping method works). This file covers only
what an agent working in the repo needs that those don't say.

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

- Run: `python -m h2g <input.sid> [-o output.sng] [-q]` (from `python/`). From the
  repo root, `.\convert.ps1` wraps the same thing and `.\play.ps1` also opens the
  result in GoatTracker. Output-shaping flags are documented in README.md;
  `python -m h2g --help` is the authoritative list — don't restate it here, it
  drifts.
- **Opening output in GoatTracker requires `--format gts5`.** GoatTracker's legacy
  GTS2 importer overruns its pattern array on the portamento commands this
  converter emits, so a GTS2 file loads and then crashes on play. `gts2` stays the
  default because the byte-exact fixture encodes it; `play.ps1` defaults to gts5.
  See README.md § `--format`.
- **Versioning — bump on every commit** (not just releases): run
  `python python/bump_version.py "short description"` before staging, and
  regenerate any doc embedding the version. See README.md § Versioning.
- **Regenerate the generated artefacts on every commit**, in this order, from
  `python/`:

  ```sh
  python survey.py <sid_dir> -o ../SURVEY.md --legal-restart --gt2reloc   # corpus report
  python presets.py <sid_dir> -o ../presets.json                          # per-song best options
  ```

  `--gt2reloc` is what fills the report's pack-back column at all — omit it
  and the column comes out empty, silently. `--legal-restart` is part of the
  same command because without it `greloc.c:244` refuses every tune that ends
  on Hubbard's `$FE` marker — the column would measure the option's absence
  rather than the converter. The report states which setting produced it.

  Both embed the version and both are derived from conversion behaviour, so a
  commit that changes either leaves them stating something that is no longer
  true. `presets.json` is the easier one to forget because it is not
  human-facing — but it is what `--presets` applies, so a stale entry silently
  converts a song with the wrong options. Regenerate **after** the tree is
  coherent and the tests pass, never while another change is half-applied: a
  run taken mid-edit records a state that never existed.
- **`FIDELITY.md` is generated too, but on demand rather than every commit.**
  `python fidelity.py <sid_dir> -t 10 --presets ../presets.json -o ../FIDELITY.md`
  packs each conversion back to a `.sid` with gt2reloc and compares SID register
  traces against the original. It is the closest thing in the repo to a measure
  of whether a conversion *sounds* right, so regenerate it after a commit that
  changes what the converter emits — and never from a working tree with
  unrelated edits in `h2g/`, for the same reason as the artefacts above.
  Since v0.5.66 each run gets its own scratch directory, so two of them (or a
  `fidelity.py` and a `listen.py`) can run at once. Before that they shared
  one directory with fixed filenames and silently measured each other's
  files — plausible numbers about the wrong tune. Pass `--workdir` only to
  keep the intermediates, and never pass the same one twice concurrently.
- **Do not treat `FIDELITY.md` as the last word on fidelity.** It compares note
  *attacks* and, since v0.5.78, every SID register beside them — waveform
  class, noise frames, the envelope pair, duty-cycle movement, filtered
  frames, cutoff travel and (v0.5.83) pitch travel. It still cannot see tempo,
  note length or the volume nibble, and none of the register columns is a
  listening test: `pul`
  counts movement without judging the sweep, `adsr` scores a register value
  and not when it arrives. **Prefer a travel measure to a count whenever the
  change is to a step *size*** — `slides` reported v0.5.83's slide-dialect fix
  as a regression because siddump splits pitch movement between two printed
  forms and it counts one; `bend` (travel) reads the same fix as 0.30x → 0.66x.
  `cut` exists next to `filt` for the identical reason. **And take the
  measurement from the tool rather than re-deriving it**: `bend` needed four
  corrections in six versions, and the three wrong ones all re-computed pitch
  travel by differencing siddump's frequency column (counting first attacks,
  then ties, then the bare frequency write a note onset makes on its own
  frame). The version that sums siddump's own `(+ xxxx)` lines needed none.
  v0.5.46 fixed a
  real defect that rewrote 66 rows of one file and moved the report by zero
  percent. A flat report is not evidence a change did nothing — when a fix is
  invisible to the metric, say so in the doc beside the fix.
  `python listen.py <sid_dir> --from-json ../build/fidelity.json` stages WAV
  pairs for the only check that covers the rest; it needs `--json` from a
  `fidelity.py` run and writes to gitignored `build/listen/`.
- **Do not conclude a change did nothing from a flat table — make the tool
  say it.** Since v0.5.77 every dimension declares the SID registers it reads,
  every row records which dimensions it actually compared, and the report ends
  with *What this run compared* naming the registers nothing in it reads
  (`$D402/$D403`, `$D405/$D406`, `$D415/$D416`, `$D417`, `$D418` — pulse
  width, envelope, filter, volume). `fidelity.py --baseline old.json` A/Bs a
  saved `--json` run against the current tree and hashes the converter's
  output per row, so it distinguishes **"no dimension this report measures can
  see this change"** from **"this change reaches nothing"** — the two readings
  of one flat table, and this repo has shipped the second believing the first
  twice. It refuses (exit 2) across different `-t` or subtunes, and *names*
  rather than refuses a conversion-option difference, because an option A/B is
  the mode's main use. Adding a report column means adding a `Dimension` entry;
  `tests/test_fidelity.py` fails if the registry and the printed header
  disagree. See README.md § *A/B against a previous run*.
- **A low score in `FIDELITY.md` is a claim about the harness until it is a
  claim about the converter.** Four separate defects have now been *in the
  measurement*: NTSC originals named in the wrong key (v0.5.63), subtune 0
  traced where the header names another default (v0.5.64), a 10 s window
  shorter than a file's opening rest, and (v0.5.97) **rows whose two sides are
  not the same piece of music**, because the `.sid`'s own init routine
  renumbers the subtune before the player sees it. **Run `fidelity.py
  <file> --diagnose` before calling any row a conversion bug.** It asks the
  questions in the order they have to be asked: the subtune correspondence
  matrix first, then a per-voice cause. Three of the four files the handoff
  filed under "plays something else" were the harness — Dragons_Lair_Part_II
  is 7% on the diagonal and 94/98/97% at its real counterparts, and
  Flash_Gordon's traced subtune is its worst of nine.
  `--search-subtunes` cannot substitute: it varies *our* index while holding
  the original's fixed, and in these files the original's is the one that
  moved. On the per-voice question, a modal semitone delta's share degrades
  when either side drops notes, so a *low* share is not evidence of
  scrambling — `--diagnose` sweeps a constant transposition through a difflib
  alignment instead and reports the peak, signed as ours against the
  original's.
- **A score is not a clock.** Every column of `FIDELITY.md` compares
  *what* is played, never *when*: `melody` is a difflib ratio over a note
  sequence in a fixed window, and a conversion playing too fast overruns that
  window and is charged for the surplus while one playing too slow returns a
  prefix. So a score can prefer the wrong call rate, and in v0.5.99 one did —
  17 files were written up as "a factor of two out" on that evidence and
  `fidelity.py <file> --pace` refuted it: timed over difflib-matched notes,
  32 of those 33 are closest to the original at the rate they are packed for.
  **Use `--pace` before saying anything about speed, tempo or `-S`.** What it
  found instead is live: the speed gate `goatwriter.find_song_speeds` reads
  is **under-read across the corpus** by a tune-specific 1.1–1.5x (gate 2 vs a
  measured 2.5–3.0 on Tarzan, Delta, ACE II, Deep Strike; gate 3 vs 3.5–4.5 on
  Lightforce, Thanatos, Pygmies Revenge; gate 4 vs 5.33 on Human Race). It is
  right for 26 of 43 multiplier-1 files, so it is not a constant to correct —
  the mechanism has to be found in the players. Per-file targets are in
  `build/pace.txt`; `tests/test_pace.py` pins the estimator.
- **Update the docs as part of the build, not afterwards.** `SURVEY.md` and
  `presets.json` are generated, but `README.md`, `CLAUDE.md` and
  `H2G-CONVERSION-METHOD.md` are not — if a change alters behaviour those
  files describe (an option's effect, a player dialect, a limit), the edit
  belongs in the same commit. Docs that drift are worse than absent ones: the
  method write-up is used as reference material by another project.
- **Packing back to a `.sid` needs `--legal-restart`.** Hubbard's `$FE` track
  byte means "tune ended", and the only way an orderlist can say that is an
  out-of-range restart position — which `greloc.c:244` rejects, so `gt2reloc`
  writes nothing and reports nothing (its error path goes to a console that
  does not exist headless; **test for the output file, never the exit code**).
  Off by default because it changes the bytes and the fixture carries three
  such tracks; `presets.json`'s `always` block sets it. See README.md
  § `--legal-restart`.
- **A rate read out of the player is per *frame*; every table Goattracker
  applies it with steps per *play call*.** They agree only at `gt2reloc -S1`,
  and 33 of the 83 preset songs pack at `-S2`. Anything new that carries a
  rate — a slide step, a sweep, a table delay, a transient length — must be
  divided by `multiplier` at the point it is encoded, the way
  `build_speed_table`, `_drum_speed`, `_rise_speed_index`, `_wave_hold_byte`
  and the pulse programs now are. **Encode the rate against the loop that
  consumes it, not the constant that names it**: a wavetable delay entry is
  current for `value + 1` calls, not `value` (gplay.c:697-704), and reading
  the range out of `gcommon.h` instead left every multispeed file's attack a
  call too long from v0.5.82 to v0.5.130. `tests/test_call_rate.py` now
  transcribes that loop and times the shapes against it. Until v0.5.99 **no number in `FIDELITY.md` could
  move on such a change**: stock siddump calls the play routine `seconds × 50`
  times whatever the PSID speed field says (`siddump.c:309/325`), so the trace
  saw every file as multiplier 1. `python/tools/siddump-rt` (vendored siddump
  1.08 plus `-m<n>`, calls per displayed frame) closes that, and `fidelity.py`
  now traces each conversion at the rate it was packed for. **Build it before
  taking a fidelity number** — the harness refuses a multiplier > 1 song
  without it rather than trace one at half speed. A differential hash over the
  corpus is still the check that a multiplier-dependent edit *reaches*
  anything (the multiplier-2 songs must change bytes and the multiplier-1 ones
  must not); the trace now says whether it lands in real time. It also said
  something new: 17 of the 33 *score* better at 50 Hz than at the rate they
  are packed for. **That is a fact about `melody`, not about the files** —
  see the bullet above; timed with `--pace`, 32 of the 33 are closest to the
  original at their packed rate. See H2G-CONVERSION-METHOD.md § 7.bb,
  `tests/test_call_rate.py`, `tests/test_calls_per_frame.py` and
  `tests/test_pace.py`.
- **`--max-rows` defaults to 94 — do not change the default.** It is what the
  byte-exact `Commando.sng` fixture encodes, and that fixture is the project's only
  fidelity anchor. See README.md § `--max-rows`.
- Test: `python -m pytest tests/ -q` (from `python/`). Treat any output-changing edit
  as a regression unless it's an intentional new feature (in which case update/extend
  the reference fixtures, don't just delete the assertion).
- Module layout mirrors the VB6 pipeline 1:1, each stage in its own file:
  - `sidfile.py` — PSID/RSID header parsing (`load_sid`), plus
    `find_relocation`, which reads the page-copy loop of a file that moves
    part of itself at init (I, Ball) so `to_offset` can resolve the
    addresses its player names. Consulted only when the plain formula
    lands outside the file, so it cannot change a file that already works.
    Also `find_init_writes`, for a player whose table addresses are not in
    its instructions at all but written over them by the init routine
    (Devils Galop). Applied only to a file whose tables as they stand name
    no patterns, so — like the relocation — it can rescue a file that reads
    nothing and never disturb one that reads correctly.
    Also `find_freq_table`, which locates the player's own note frequency
    table and places it against Goattracker's. It returns two numbers that
    mean opposite things: a `shift` (the note byte is offset, a converter
    defect — one corpus file, Skate or Die intro, whose table has a `$0000`
    at entry 0) and a `detune` (the whole table is tuned elsewhere, which
    no Goattracker file can express — four files carrying NTSC tables).
    Only the shift is applied; the detune is reported and used by
    `fidelity.py` to name the original's notes on its own tuning.
  - `search.py` — wildcard opcode-pattern search (`search_file`, port of `SSearchfile`).
  - `detect.py` — player-engine signature chains (`detect`, port of the
    `FindInstruments`/`FindSubSongs`/`FindTrackSelector`/`FindPattern`/
    `FindPlayerVersion` blocks in `loadfile()`). Returns a `Detection` dataclass.
    Every signature in the instrument chain fingerprints the *store* into the
    SID (`LDA record,X / STA $D40x,Y`), which is why a player that reaches the
    SID through subroutines matched none of them. `INSTRUMENT_INDEX_SHAPE`
    fingerprints the *load* instead (`LDA idx,X / STX / ASL ASL ASL / TAX /
    LDA record+2,X`) and is consulted last, so it can rescue a file that finds
    nothing and never disturb one that reads correctly — the same rule as
    `find_relocation` and `find_init_writes`. The one match it yields names
    two things: the instrument table, and the per-voice instrument index array
    (`Detection.initial_instruments`).
    `_find_table_vibrato` follows the same rule for the *other* vibrato: the
    command-table engine (Hollywood or Bust, Chicken Song) parameterises it
    with an LFO table rather than the `$78`/`$07` pair every other player
    shares, so it is consulted only where `_find_vibrato` returned None.
    Note what finding it turned up about the target: Goattracker's vibrato
    half-period is `cmp + 2` play calls, **not** `cmp / 2` -- simulated from
    `gplay.c:795-801` rather than read off it. `_classic_vibrato_entry` was
    built on the `cmp / 2` reading and oscillated at about half the player's
    rate until **v0.5.129**, which corrected `cmp` to
    `bound * multiplier - VIBRATO_CMP_BIAS` across 49 files. `rshift` was
    *not* touched: the old derivation equated the player's peak-to-peak with
    a Goattracker amplitude, and that error cancelled the doubled period
    exactly -- correcting both would have doubled every file's depth. **No
    dimension of `FIDELITY.md` measures an oscillation rate**, so the report
    could not adjudicate the fix (15 files toward the original, 15 away, mean
    melody unchanged); `--baseline` byte-hashing settled its reach instead.
    See H2G-CONVERSION-METHOD.md sections 7.kk and 7.ll -- and note that the
    two sections formerly both numbered 7.jj are now 7.jj and 7.kk.
  - `tracks.py` — `convert_tracks`, port of `GoatConvertTracks`. Also
    `apply_initial_instruments` (behind `--initial-instrument`), which gives a
    voice the instrument the player starts it on where no pattern names one.
    **Off by default and deliberately not in `presets.json`'s `always`
    block**: the index array is mutable player state, so its file-image value
    is the starting instrument only for a rip of a single tune — right for
    `Delta_Mix-E-Load_loader`, wrong for a fifteen-subtune demo. See
    README.md § `--initial-instrument`.
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

## Parallel work: branches, worktrees, PRs

Several agents have repeatedly worked this repo at once. Sharing one working
tree does not survive that, and the failures are not theoretical — both of
these happened:

- A fork had to **blob-stage** its commit because siblings held uncommitted
  edits in the same files. That left `cli.py`/`convert.py`/`goatwriter.py` in
  the tree *without* its hunks while the committed `presets.py` referenced
  options those copies did not accept. For a while, no measurement taken from
  the working tree was valid — and nothing announced that.
- v0.5.72 shipped `--filter` wired into `convert()` and README but into
  neither `presets.py` nor `_preset_opts`. It reached nothing. A regeneration
  taken in that window would have written an `always` block without it and
  shipped the feature inert.

So, for any work that runs concurrently:

- **One branch per unit of work, one PR per branch.** Branch from a pushed
  `master`, never from a tree holding someone else's uncommitted edits.
- **Each concurrent agent gets its own git worktree** (`isolation: "worktree"`
  on the Agent tool). There is then no shared working tree to corrupt, and a
  sibling's half-finished edit cannot silently enter your measurement.
- **No PR touches `SURVEY.md`, `presets.json` or `FIDELITY.md`.** They are
  generated; parallel branches conflict on every line of them, and a
  per-branch regeneration records a tree state that never existed.
  `master` regenerates **once**, after the merges, per the rule above.
- **Re-take every number after rebasing onto what landed.** HEAD moving under
  a fork has invalidated measurements more than once; numbers from the tree
  you started on are not numbers about the tree you are merging into.
- **Verify the staged path list before committing** (`git diff --cached
  --name-only`). One fork committed nine duplicate files at the repo root and
  then swept a sibling's uncommitted work in while trying to amend it.
- Worktree checkouts can be CRLF against LF blobs, which shows up as bogus
  whole-file merge conflicts. Normalise before concluding the conflict is
  real — and note that it usually is real anyway.

A new `convert()` option is inert until it is in **three** places: the
signature, `presets.py`'s `FIXED`, and `_preset_opts`. `_preset_opts` now
derives its keys from `inspect.signature(convert)` and
`tests/test_preset_passthrough.py` fails if any option escapes, with
`presets.EXCLUDED_FROM_ALWAYS` naming deliberate omissions. Do not hand-edit
that list back into existence.

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
     Wiedersehen Monty, Delta Mix-E-Load loader). Every player variant needs its own hard-coded byte pattern
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
