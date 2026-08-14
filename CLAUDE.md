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
  result in GoatTracker.
- **Open a song for listening with `.\play.ps1 -Presets presets.json`, never by
  launching `goattrk2.exe` yourself.** 37 of the 82 measured files advance a row
  every 2-3 frames, and the editor calls the player once a frame, so a bare
  launch plays them at 1/multiplier speed. The `.sng` cannot encode the rate —
  Goattracker's fastest steady row is 3 calls (`TEMPO_FASTEST_STEADY`) — but the
  *editor* can be set to it with **SHIFT+F6**, and `play.ps1` reads the song's
  multiplier and prints how many presses. Bypassing it in v0.5.177 produced a
  half-speed audition of Last_V8, a listening verdict that reversed the
  measurement, and a `vsid` re-test that reversed it back: at speed, the
  187-note version is right and the 71-note one is not. A packed `.sid` played
  in `vsid` is the other correct way, and the only one for a `.sng` you cannot
  set the multiplier on. Output-shaping flags are documented in README.md;
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

  `presets.py` also has a `--fidelity` mode, for options that change no
  *structure* and so are invisible to its scoring (currently
  `--no-test-restart`). Do not add it to the routine command: it traces four
  emulations a song. A plain run **carries forward** whatever `--fidelity`
  already recorded and prints how many, so the fast path cannot silently
  revert a measured per-song decision — but a run with `--no-carry`, or an
  output path with no previous file, will drop them.

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
  `python fidelity.py <sid_dir> -t 60 --presets ../presets.json -o ../FIDELITY.md`
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
  frames, cutoff travel and (v0.5.83) pitch travel. It still cannot see tempo
  or the volume nibble — note *length* it does see, since v0.5.196's `hold`,
  though only below `-S4` — and none of the register columns is a
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
- **A lesson recorded in one emitter is not a lesson in the file.**
  `_drum_entries` was corrected in v0.5.172 to put the record's own `+2`
  waveform on the note's first frame, because the player writes it there and
  reaches the effect block only from the second -- and its docstring says so at
  length. `_wave_program_entries` and `_two_stage_entries` sit in the same file
  and carried the identical defect for 45 more versions, because nothing
  measured it and the fix had been written as prose about one function rather
  than as a shared helper. When a fix is really a *rule about the player*, give
  it a name every emitter has to call, and a column that fails when one of them
  stops -- `_first_frame_entry`/`_first_frame_lead` and `onset` are that pair.
  **And the rule had a second half nobody had stated**: one frame is
  `multiplier` play *calls*, so `_drum_entries` -- which had opened on the
  record's waveform correctly since v0.5.172 -- still put the drum tick inside
  frame 0 on every multispeed file, because its lead was one call at every
  `-S`. Its docstring said so outright ("its attack entry lasts one play call
  at every -S value") and read as a description rather than as the bug it was.
  20 of the 23 instruments still reading a frame early after v0.5.218 were on
  `-S2` files against 3 on the 45 single-speed ones; fixing it took corpus
  onset agreement 237 -> 254 matched with **melody, seq, adsr, nrun, tail and
  pitch all exactly unchanged**, which is the signature of a change that moves
  a waveform *within* frame 0 and nothing else. **And a fourth emitter still
  did not call it**: v0.5.226 found the plain `tick` block of
  `_wavetable_entries` reading its tick length from a hardcoded constant where
  `_drum_entries` derived it, and opening it one *call* into frame 0 where
  `_first_frame_lead` exists to open it one frame in. Extracting a helper is
  not the same as every caller using it -- grep for the constant the helper
  replaced, not just for the helper.
- **This repo has two players, and they do not agree about the schedule.**
  Every number here comes from `gt2reloc`'s packed player (`player.s`); the
  editor's `gplay.c` is the more readable and the more often read. The packed
  one does **not** execute the wavetable on a note's first call -- it jumps
  straight to the register writes after the init (`player.s:908-911`) where
  `gplay.c` falls through to `WAVEEXEC` on the same call. So `firstwave` is
  what reaches `$D404` on frame 0 and wavetable entry 0 lands on frame 1. That
  is invisible with the default `$09` firstwave and costs a frame with
  `--no-test-restart`, which writes the record's own waveform there: the
  frame-0 lead then repeats it and every effect runs one frame late. Read
  `player.s` before concluding anything about *when* a table entry lands.
  **They also disagree about the wavetable's right-side byte.** `$00` is "the
  base note, +0" in the editor and **no frequency write at all** in the packed
  player (`player.s:976-977` tests `bne`); `$80` is "no change" in the editor
  and `adc chnnote / and #$7f` -- `(128+n) & 127 == n`, a no-op transposition
  that still writes -- in the packed one. So the byte that leaves a bend alone
  is `$00`, not `$80`. Choosing `$80` from `gplay.c` took Hollywood or Bust's
  melody to 25% against 47%, by re-asserting the base note every frame -- on a
  *waveform* entry. On a **delay** entry the two are equivalent: `player.s`
  reads as though the jump path leaves carry set (a semitone up), and tracing
  W_A_R both ways gives 0 of 1500 frames differing on all three voices. Two
  readings of the same file, one right and one wrong, and only the trace
  separated them.
- **A fixture is not the corpus.** `_noise_tick_frames` took the modal speed
  gate over a file's subtunes; the corpus rip of Commando carries 19 (four
  songs and fourteen one-frame sound effects, which outvote the music) where
  the repo's `Commando.sid` fixture carries 3. The test pinning the derivation
  reads the fixture, so it passed for as long as the defect existed while
  every fidelity number for that file -- and the drum a listener validated by
  ear -- was emitted at the wrong length. The rule is now the gate at the
  subtune the file *starts* on (`resolve_subtune`'s rule), which is exact on
  27 of the 28 corpus files whose run is short against the mode's 24. When a
  reduction over per-subtune data is pinned by a fixture, check the corpus
  copy of the same tune has the same subtunes.
- **`onset` is the column that sees a mechanism emitted one frame out of
  phase**, and until v0.5.217 nothing could. `wave` averages per-frame
  agreement over the whole window, so a wrong opening frame on a 43-note
  instrument is a rounding error against 3000; `nrun` compares run *lengths*
  and is position-independent by design, so a run that is right but a frame
  early scores 100%. Both read `$D404` and neither could see that
  `_wave_program_entries` and `_two_stage_entries` opened on the effect where
  the player opens on the record's own `+2` waveform. It reports the
  *direction* (`onset_ours_early` / `_late`), because a wrong waveform and a
  right one a frame out have different fixes -- and the corpus split is
  **32 early, 0 late**, which is what a systematic defect looks like and what
  noise does not. It takes **no startup-lag correction**: each side is read at
  its own attack frames, so the latency cancels, and the first wiring of the
  column passed a lag in and would have manufactured the error it detects.
- **To read what a conversion *says* rather than what it measured, use
  `songview.py`** (`python songview.py <sng|sid> -o out.html --presets
  ../presets.json`). It decodes the whole `.sng` to one self-contained HTML
  page: orderlists with transposes resolved, wavetable entries with
  **cumulative call timing** (a delay entry is current for `value + 1` calls,
  the off-by-one that stood from v0.5.82 to v0.5.130), instruments tagged with
  the effect bits recovered from their provenance stamp, and every pattern
  labelled with **all three** of its identities — GT's hex number, the
  post-dedup index and the Hubbard source. It scores nothing, so unlike a new
  dimension it cannot be silently wrong in a way that changes a decision; when
  a column disagrees with a wavetable, read the wavetable here before
  theorising. Its parser is a *second* reader of the format, not a re-use of
  `build_sng` — `tests/test_songview.py` checks the two against each other and
  against the byte-exact fixture, which is the only thing making the
  independence worth anything.
- **`--vice` is the register dimensions at 312 samples a frame** (v0.5.131),
  from VICE's per-rasterline `dump` device, both sides. Use it for any change
  that moves a register *within* a frame -- siddump samples once per frame, so
  v0.5.130's attack fix moved `wave` on 0 of 82 files. The per-frame reduction
  is forced (the two sides write at different rasterlines, so rasterline
  against rasterline would report that offset) and was **measured, not
  chosen**: under an inaudible 0-48 rasterline shift `last` -- what siddump
  reports -- moves up to 2.64pp and `overlap` 0.13pp, so the default is
  `overlap` and `any` is disqualified for saturating. Resolution and stability
  are different properties; do not assume the coarser instrument is the
  steadier one.
  **And translate the old rule exactly before believing a difference.**
  `wave_compare` drops a frame both sides spend silent; v0.5.131's `--vice`
  translated that as "both whole histograms silent", which scored a frame one
  side flickered through as a full agreement and inflated Bangkok_Knights from
  2.3% to 14.8%. v0.5.132 then published that inflation as evidence of the
  finer trace. The graded rule is that the *overlapping silent share* leaves
  numerator and denominator alike (`_graded_agreement`), and the check that
  catches this class is: run the new instrument under the old instrument's
  rule and confirm it reproduces the old number first. See
  H2G-CONVERSION-METHOD.md section 7.nn.
- **Do not conclude a change did nothing from a flat table — make the tool
  say it.** Since v0.5.77 every dimension declares the SID registers it reads,
  every row records which dimensions it actually compared, and the report ends
  with *What this run compared* naming the registers nothing in it reads —
  regenerated from the rows, so read it there rather than from any list
  written down elsewhere. `fidelity.py --baseline old.json` A/Bs a
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
  claim about the converter.** Five separate defects have now been *in the
  measurement*, the largest being that **every per-frame column was charged
  for the packed player's startup lag** until v0.5.175: gt2reloc's player
  reaches its first note some 3-8 frames after the original, and comparing
  frame k to frame k made that a disagreement on every file (mean `wave`
  67.0 → 70.2%, `adsr` 71.9 → 76.4%, Commando's `wave` +32pp). It is
  `startup_lag`, the difference between the two sides' first attack frames —
  **estimated from that signal, never fitted**, because a shift chosen to
  maximise agreement can only raise the score. The estimator was validated
  against that search: it lands on the fitted optimum for 20 of 36 files and
  gives a mean within 0.1pp of it. **And the same columns can be too kind:**
  `wave` reached 99.5% on Commando for a v0.5.176 candidate that deleted 79
  notes, because fewer attacks mean fewer transitions to disagree about. Read
  any register agreement next to both sides' note counts — a change that
  removes the events a column scores will always appear to improve it. Also: NTSC originals named in the wrong key (v0.5.63), subtune 0
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
- **A bit tested with `BIT`/`BVC` is invisible to an `AND #$xx` scan.** Effect
  bit `$40` went unread for the whole project because detection looks for
  `AND #$40`; bit 6 (and bit 7, via `BPL`/`BMI`) have 6502 idioms of their own.
  When a record byte's bits are being catalogued, scan for all three forms. And
  identify the cell before trusting a hit: `BIT addr / BVC` is everywhere, so the
  address only counts as the effect byte if the player also tests it with masks
  whose meaning is already known.
- **An encoding is only as good as the *packer's* reading of it.** `$E0`-`$EF`
  is "set the waveform to `$00`-`$0F`" in the editor (`gplay.c:527`) and this
  converter believed that for the packed player too. `gt2reloc` rewrites the
  range (`greloc.c:1270-1271`): low nibble, then `+$10` back **only if the song
  uses a wavetable delay at all** (`nowavedelay`, over the rows an instrument
  reaches). A song without one ships `$E0` as a literal `$00`, which
  `player.s:944` reads as *no wave change* -- so the entry writes nothing and
  the previous waveform keeps sounding, while the identical entry in a song
  that does use delays works. Skate or Die intro's terminating `slide $00` and
  Nineteen's `$E1` drum tick are the two outcomes. Silence from a wavetable is
  `$18` -- triangle with the test bit, which both players write and which
  outputs nothing. Read `greloc.c` beside `player.s` before trusting a range,
  and settle it on the packed bytes. See § 7.bbbbb.
- **A byte copied from the player into a Goattracker table is in Goattracker's
  encoding now.** `_wave_program_entries` writes a program opcode's waveform
  into the wavetable's left column, where `$F0`-`$FF` are *commands*: an
  opcode of `$FF` becomes a **jump** and its pitch byte becomes the jump
  target. Wiz's is `$FF`/`$DE` -- 222 in a 112-row table -- and `gt2reloc`
  refuses the file with exit code 0 and no message. Three corpus files carry
  such opcodes and two of them (Kings of the Beach intro, Mega Apocalypse)
  shipped with `--wave-program` on. Fixed in v0.5.237 by routing the command
  range through the `$E0`-`$EF` encoding `_wave_byte` already used for
  waveforms below `$10` -- and **the general form is now
  `tests/test_table_validation.py`**, which replicates `exectable` over every
  corpus conversion. When a pack fails silently, walk the tables: it turns
  "gt2reloc will not pack it" into an instrument and a row.
- **A guard that reads like a sanity check can be a population filter.**
  `detect._effect_byte_address` opened with `if det.instr_stride != 8: return
  None`, which switched off *every* routine that reads the instrument effect
  byte -- two-stage attack, bit $02's alternation, bit $40's pitch -- for the
  9 corpus files whose records are 16 bytes. It computes record 0's `+7` and
  searches for `LDA base,Y`; neither step depends on the stride, so it
  excluded a dialect rather than an error, and behind it sat the onset
  census's largest remaining group. Lifting it took `onset` to 100% on seven
  of the nine and landed five files within 3% of the original's noise-frame
  count from zero. When a probe declines, ask whether it declined the *file*
  or the *family*.
- **A walk that steps a fixed number of bytes over an instruction has assumed
  its addressing mode.** `find_wave_program` stepped 3 for the `STX save`
  between the gate's branch and the pointer load -- `STX abs`, which 28 of the
  29 files carry. Mega Apocalypse stores to zero page, so the walk looked for
  the branch opcode inside the `AND`'s operand and reported the gate as
  *unread* -- and unread is `_wave_program_entries`' refusal condition, so
  forcing `--wave-program` on that file changed nothing on any measure and it
  was filed for two sessions as an unimplemented mechanism. Same shape as
  `detect._burst_cutoff_start` (v0.5.210). When a fix widens a walk, run the
  old one beside the new one over the corpus and require the difference to be
  exactly the files you meant.
- **A veto on a ratio must be sized, not merely signed.** `presets`'
  oscillation guard first asked "is the candidate worse", via `_closer` --
  whose margin is a fraction of the *remaining* gap, so on a ratio already far
  from 1 any wobble clears it. Chicken Song's 0.32 -> 0.29 blocked a 100-point
  `hold` gain while After_8's 0.93 -> 0.29, the same absolute move, is the one
  that matters. `_oscillation_lost` asks whether the candidate ends up **more
  than twice as far** from the original's rate (17x against 1.09x) -- a claim
  about audibility rather than a constant fitted to the corpus. And when a
  guard needs a bound, check the quantity's noise floor first: requiring melody
  not to fall *at all* blocked seven of eight files over thousandths of a
  difflib ratio.
- **Compare a ratio in log space.** `presets._closer` scores how near a ratio
  sits to 1 logarithmically, because 2.0x and 0.5x are the same size of wrong
  where `abs(r - 1)` calls one twice the other. Applies to every `x`-suffixed
  column in `FIDELITY.md`, not just the scorer.
- **A rate that looks wrong may be a mechanism that is absent.** `vib` 0.17x on
  the balloon song was read as a vibrato-rate bug; the one instrument that *has*
  a vibrato byte was within 20% of the original, and the missing 1812 reversals
  belonged to effect bit `$10` -- an arpeggio never read at all. **Attribute a
  ratio per instrument before tuning the mechanism you assume produces it.**
- **A mechanism driven by a *global* counter cannot be put in a per-note
  wavetable.** Bit `$10`'s phase is global; a wavetable restarts at every note,
  so which step a note opens on is unreproducible and no rotation is right more
  than 1/steps of the time. Emitting it takes median `vib` 0.22x -> 0.58x and
  costs 5 points of mean melody. That is a per-song trade, not a fix -- and
  `fidelity_better` cannot select it, because it scores a melody *gain*. Two
  mechanisms now wait on a scorer that weighs oscillation and noise pitch. See
  § 7.ttt.
- **A column can read 100% because the trace cannot see the defect.** `hold`
  measures a note-length deficit that is a fixed number of play *calls* -- the
  next-note fetch is `gatetimer & $3f` calls early -- so at `-S4` it is a
  quarter of a frame and siddump, sampling once per frame, reports zero. The
  corpus splits exactly that way: `-S1` 106 of 121 instruments at -1, `-S4`
  17 of 17 at 0. **A zero up there means "not visible", not "correct"**, and it
  predicts that the preset search can never take `--no-test-restart` above
  `-S3` -- all nine files that carry it are `-S1` but for Delta. State the
  blindness in the Dimension itself; a column reading well for the wrong reason
  is worse than one reading badly.
- **A census of what a column misses is a queue, not a report.** Grouping
  `onset`'s disagreeing instruments by the record byte that causes them turned
  "18% disagree" into "$01 x19, $04 x11, $80 x6, $0A x6" -- and the `$0A` entry
  was a decoded mechanism (bit `$02`'s alternating waveform, 21 files, 98
  records) within the same session. When a dimension's level is unexplained,
  classify its misses by cause before trying to move it. It is
  `fidelity.py --census PATH` since v0.5.234, written from the traces the
  column itself scored rather than from a second pipeline -- **a scratch
  script that answers a question twice is a tool that was not committed**, and
  this one had to be rewritten from scratch a session after it earned its keep.
  Promoting it found a defect in the column beneath it: `$01 x19` is one cause
  and one fix, and the census is what says so.
- **A modal shape over a key two records share compares two instruments.**
  `onset`'s key is the ADSR pair, which is a verbatim copy of the record and so
  a good key -- but not a unique one. Nineteen's records 0 and 4 both carry
  `$0B06`/`$A0`; split by shape the original's voice 3 is 113 bass notes
  (`pul noi pul pul`, exactly ours) and 151 drum ticks (`noi -- -- --`, all one
  note), and the mode picked the drum on one side and the bass on the other and
  called it the census's only `wrong`. Two things follow. **Split a population
  before reducing it** -- `instrument_stamps` already flags `ambiguous` on our
  side and the census does not print it, and the original's side is not checked
  at all. And **siddump's "notes" are not all note onsets**: its keyoff-keyon
  test fires when the waveform reaches `>= $10` with the gate set after a frame
  below `$10` (`siddump.c:434-437`), so a drum whose instrument holds `$01`
  between hits prints one note per hit. Underneath it was a real defect --
  `_sfx_drum_entries` *declined* a record with no waveform of its own, which is
  the drum alone, and Nineteen's 58 pattern rows of percussion emitted three
  delays and a stop. See H2G-CONVERSION-METHOD.md § 7.zzzz.
- **A degenerate match is not evidence.** `onset`'s phase test asks whether
  `ours[:-1] == orig[1:]`, which on a shape the original holds *constant* is
  true of anything agreeing in its first three frames -- so a note of ours that
  merely *ends* inside the window (`noi noi noi --`) was reported as a one-frame
  phase error, on 3 of the corpus's 6. The fix is to require the shifted
  reading to explain something the unshifted one does not; the remainder is the
  `short` kind, a note-*length* difference no column here measures. A
  diagnostic naming the wrong cause is worse than one naming none.
- **A symptom can be diagnosed right and explained wrong, and the explanation
  is what propagates.** `_sfx_drum_entries` put the bit-$80 drum's hit at the
  *end* of its period because a measurement showed melody collapsing 94.7% ->
  50.4% when the noise opened the block. The collapse was real; the reason
  written down for it -- "the player's counter is per voice and free-running"
  -- was not. It is zeroed at note start in both dialects (`STA $8934,X` at
  Bangkok `$80CE`), and the collapse was the noise landing on **frame 0**,
  where siddump names the note. One misread cause reached a docstring, a
  constant's comment and three tests, all agreeing with each other, and the
  drum fired three frames late for as long as it existed. When a fix rests on
  "we measured that the other way is worse", check that the *other way* is the
  one you would fix next -- there were three placements here and only two were
  ever tried.
- **A detection flag about a player is not a fact about a record.**
  `det.effect_bit40` says the player *reads* bit $40; only a record's own effect
  byte says it is *set*. Gating the fixed attack pitch on the file alone reached
  Thundercats' drum, whose records carry $80 and $A0 -- 99 noise frames at a
  pitch its original never sounds, and melody 77% -> 72%. Every per-record effect
  bit needs both checks, and the per-record one is the one easy to forget because
  the file-level flag is what detection hands you.
- **A per-frame profile measured on one file can encode that file's structure
  rather than the mechanism's.** Bit `$40`'s pitch fires once per *note*; the
  drum block loops once per *period*. Trans-Atlantic has one burst per note, so
  the two coincide there and the composed emission measured exact -- on Pandora
  the same change put 281 frames at that pitch where the original has 35. It
  surfaced only because Pandora ships with `--sfx-drum` on and had to be checked
  before committing. **Verify a newly derived shape on a second file that uses
  the mechanism differently**, and prefer the one whose options are already
  enabled, since that is where a regression actually reaches. Also: `nrun`
  compares run lengths and `melody` reads the attack frame, so **no report
  column sees a noise frame's pitch** -- both the gain and the regression here
  were invisible to `FIDELITY.md`. See § 7.rrr.
- **Where an effect's frames *land* is part of the mechanism.** The balloon
  song's second drum is bits `$04`, `$80` and `$40` interleaved by frame --
  played note at offset 0, `$80`'s pitch at offset 1, `$40`'s at offset 2. Each
  bit alone puts its pitch on a frame that belongs to another: emitting `$40`
  correctly derived but on frame 0 took melody 85% -> 39%. **Before emitting a
  newly decoded effect, measure the original's per-offset-from-attack profile**,
  not just the aggregate it contributes. See H2G-CONVERSION-METHOD.md § 7.qqq.
- **Goattracker numbers patterns in hex, and the editor's pattern is not the
  converter's intermediate.** A listener's "PATT.12" is pattern **18**; three
  dumps of `new_patterns[12]` disagreed with the screenshot before that landed,
  and each looked plausible enough to keep chasing. The editor's pattern is also
  post-dedup (GT 18 was Hubbard 15) and the orderlist's leading `D3` transposes,
  so neither the index nor the pitches match the source bytes. **Identify a
  pattern by its note-row positions**, and read the final `.sng` rather than an
  intermediate when comparing against what a listener sees.
- **Reading a bit is not drawing its consequence.** Status bit 5 was decoded for
  years as `no_adsr` and emitted a `CMD_TONEPORTA` on the tied row itself, where
  the slide branch overwrote it a few lines later -- inert. Its actual meaning is
  "don't close the gate at this note's end", whose consequence lands on the
  *next* note (no gate edge, so no attack). Three separate defects came out of
  that one bit (§ 7.mmm, 7.nnn, 7.ooo). When a flag is already parsed but
  nothing observable depends on it, that is a lead, not a finished feature.
- **A minimum is the reduction for a safety bound; a median is the reduction
  for an approximation.** `_drum_max_steps` said "the safety bound and the
  musical target turn out to be the same number" -- they coincide only when
  the note is long enough that the player's wrap guard fires before its
  *duration* guard, and Commando's instrument 13 has room for 13 steps, was
  capped at 8, and gets 5 because its note is four rows long. One wavetable
  sweep stands for every note an instrument plays, so the value that minimises
  the total error against that distribution is its **median**. Taking the
  minimum -- by analogy with `min_played_notes`, which really is a safety
  bound -- would have emitted **zero** steps for Bump_Set_Spike's record 0,
  whose original sweeps 5 steps 221 times in 240 s, because it is also played
  at two rows in a third of its occurrences. Corpus L1 error: 320070 (pitch
  bound alone), 117806 (minimum), 99983 (median). And weight the distribution
  by how often the orderlist *plays* each pattern -- a duration in a pattern
  played sixteen times is not one occurrence. See § 7.ccc.
- **`bend` counts our drum sweep and not the original's**, because a 256-unit
  step is more than a semitone and siddump names the player's steps as *notes*,
  which `bend` excludes as ties (§ 7.ii). So any change to sweep depth moves
  our numerator alone: over-1 files march toward 1 and under-1 files away, and
  neither is evidence. Settle a sweep change by comparing the frames at
  gate-edge onsets on both sides -- and take those onsets from siddump's
  *bare* note (`siddump.c:376-380`), never from a waveform change, which the
  drum's own noise tick fires three times a note.
- **Widening a window is not automatically the safer reduction.** v0.5.200
  measured a note's release as the minimum over the whole gap to the next note,
  on the reasoning that a minimum cannot depend on which frame the player writes
  on. True, but it also cannot tell this note's cut from the *next* note's
  setup: the column scored every instrument as cut, the writer zeroed every
  release, Commando's drums lost their tails and a listener heard it one build
  later. Read on the gate-off frame the same three builds score 64.6% / 62.1% /
  97.4% -- v0.5.200 was a net regression published as an improvement. **When two
  reductions of one signal disagree by 5x, one of them is counting a different
  event**; settle it by looking at the frames, not by picking the more plausible
  number. See H2G-CONVERSION-METHOD.md § 7.nnn.
- **A discriminator is only meaningful on the population the behaviour occurs
  in.** "Effect bit $01 clear" scored 59.8% over all 95 files and was dismissed
  as a correlation; over the 33 files that actually have the routine it is 98.6%
  with zero false negatives -- it was the mechanism. The 62 files where the
  phenomenon cannot occur could only contribute false positives. A **necessary**
  condition with no false negatives is worth more than its raw accuracy implies.
- **An attribution key must not contain the quantity being attributed.** The
  `tail` column keys each note ending by the instrument's ADSR pair and
  measures the release nibble in that pair; keyed on the whole pair, emitting a
  zero release moved every one of our keys, no instrument was shared with the
  original, and the column reported "nothing to compare" for the one change it
  was built to measure. Mask the measured field out of the key. Same trap as
  reading a duration at a fixed offset from the event whose duration changed,
  in the other axis.
- **A correlation over instruments is not a mechanism.** Two hypotheses fitted
  Commando's seven instruments perfectly and scored 59.8% and 79.0% corpus-wide;
  the answer was in six lines of player code (`AND #$20 / BNE` on a tie flag).
  When a per-instrument split looks clean, that is the moment to go read the
  routine, not to generalise the split. And **check the reduction before
  believing a rate**: the same behaviour measured 20.7% read at the gate-off
  edge frame and 100% read as a minimum over the gap, because the player does
  not write on the edge frame. See H2G-CONVERSION-METHOD.md § 7.mmm.
- **So is a terminator.** `tracks.py` read `$FE` as "tune ended" for all of
  versions 0/1/3 and anything below it as a pattern number. Rasputin's reader
  says otherwise -- `$FD` ends a voice's list, and `$FE nn` is a two-byte
  tempo command that *continues* it -- and applying that reading to the whole
  version rewrote **23 files and broke the byte-exact fixture**. Only three
  players test `$FD` at all (Knucklebusters, Rasputin, Tarzan) and only
  Rasputin has the two-byte `$FE`, so both are flags read from each player's
  own reader, anchored on the 48 bytes after its `CMP #$FF` -- anchoring on the
  file is too loose, `CMP #$FD` occurs all over the corpus. **When a fix's
  blast radius is an order of magnitude larger than the evidence for it, the
  rule is scoped wrongly**, and that is visible before any score is read.
- **A constant read from one player is a constant about one player.**
  `TRIANGLE_VIBRATO_GATE = 8` was read from a single file's `CMP #$08` and used
  for all 25 in the dialect; 5 compare against something else, and Commando --
  the file listening sessions use -- compares against 6. Assuming 8 there
  damped 695 of its 705 notes and vibrated 10, the opposite of the intent.
  Before generalising an immediate, **search the other files for the same
  shape and print the operand**; where several copies of a shape exist, anchor
  at a fixed delta from something already located rather than scanning (these
  players carry a second gate on the same cell 377 bytes on). And prefer a
  constant that can be *checked* against the trace: Commando's 6 selects the
  24-and-30-frame notes, of which voice 1 has exactly the 31 the original is
  measured to vibrate. See H2G-CONVERSION-METHOD.md § 7.lll.
- **The same number can be right for a mechanism and wrong for its
  approximation.** The per-file gate above improves the pattern-command path
  (92.1% vs 90.3%) and *degrades* the `vibdelay` fallback it replaces (78.9%
  vs 85.5%), because a delay is also doing the suppressing that the commands
  took over. `_vibrato_delay` takes a `commanded` flag for exactly this
  reason -- when a fix moves work from one place to another, re-measure the
  constants left behind rather than propagating the new one to both.
- **When a change alters an event's *duration*, do not measure it at a fixed
  offset from an attack.** Four boundary errors in one session came from asking
  what a register held at `a + k` for a gate-edge attack `a`: GT 4's "one frame
  short" was the next note's `$09`, the drum's frames 1-2 against its routine's
  "first vbl" was the init path writing `$D404` after it, and the noise-tick
  comparison came back flat twice — once blamed on a pitch sweep that budget
  testing then exonerated. `fidelity.noise_runs` is the shape that works: find
  maximal runs of the register, record their *lengths*, drop any run touching the
  window edge, attribute by the ADSR at the run's midpoint. It took the drum
  tick from "flat, cause unknown" to 19/74 → 43/74 in one run. `nrun` reports it.
- **The report is generated at `-t 60`, not `-t 10`** (v0.5.195). At 10 s
  `slides` and `bend` were near-vacuous: 17 of 82 rows showed `0/0` slides and
  19 had no `bend` at all, so a fifth of the corpus contributed nothing to those
  columns — and
  two corpus A/Bs in one session read "identical on every file" from a window
  that simply contained no slides. The same comparison at 60 s had 75 files with
  slide activity and a clear verdict. Check what a window contains before
  comparing settings in it. Every figure in the report moved when the window
  did, so **numbers either side of v0.5.195 are not comparable**; the header
  records the window that produced them. Settled by the same measurement: **`gt2reloc -R0` is
  not the fix for the slide deficit** — `patterns._scaled_step`'s `row_calls`
  correction already compensates for the dropped call, so disabling the skip
  double-corrects (median slide ratio 1.04 → 1.23, worse on 47 of 75 files).
- **Check the fixture's bytes, not its length.** `len(convert(...)) == 15193`
  passes for any edit that moves a byte between two wavetable entries, which is
  most of them: v0.5.197's first attempt cleared that check and broke 26
  byte-exactness tests. Read `Commando.sng` and compare — `got == ref`.
- **A scripted edit must assert its match.** `str.replace` with a search string
  that does not match returns the input unchanged and raises nothing, so a
  `python - <<PY` rewrite can report success while changing no bytes. v0.5.192
  and v0.5.193 both shipped commit messages describing edits that never applied
  — including "`_noise_tick_frames` is now wired", which it was not — and
  neither the test suite nor the byte-exact fixture could catch it, because the
  affected file's derived value happened to equal the constant it replaced.
  `assert old in s` before every replace, and check the change is in
  `git diff`, not merely that the tests still pass.
- **A score is not a clock.** Every column of `FIDELITY.md` compares
  *what* is played, never *when*: `melody` is a difflib ratio over a note
  sequence in a fixed window, and a conversion playing too fast overruns that
  window and is charged for the surplus while one playing too slow returns a
  prefix. So a score can prefer the wrong call rate, and in v0.5.99 one did —
  17 files were written up as "a factor of two out" on that evidence and
  `fidelity.py <file> --pace` refuted it: timed over difflib-matched notes,
  32 of those 33 are closest to the original at the rate they are packed for.
  **Use `--pace` before saying anything about speed, tempo or `-S`.** What it
  found instead was the speed-gate under-read, and **`--skip-gate` (v0.5.119)
  is its mechanism**: every file this paragraph used to cite as proof — Tarzan,
  Delta, ACE II, Deep Strike, Lightforce, Thanatos, Pygmies Revenge, Human
  Race — now measures **0% out**, packed exactly via the multiplier (Delta's
  row is 5/2 at `-S2`, Deep Strike's 8/3 at `-S3`). Corpus today: of 63 timed
  files, **47 exact and 50 within 2%**. That idiom — an outer gate ending in
  `RTS` rather than `JMP past-the-gate`, which `OUTER_GATE` did not match, in
  **9 files** — is read since v0.5.248: Formula 1 Simulator's melody went
  88 → 100% and Thrust's 75 → 94%, both with `retrig` landing on 1.00 and
  0.92 from 1.28 and 1.26. See §§ 7.rrrr and 7.tttt. **Read `--pace`'s
  least-squares fit, not its median**: the original's gaps are whole frames,
  so a row of 2.286 quantises to a mix whose median reads 2.25, and that
  gap looked like a refutation of the factor twice. **And a file packed
  above `-S4` cannot be judged on a normal trace** — Bump Set Spike reads
  68% at `-S5` and 97% under `--equal-calls`, which is the first time that
  caveat has decided a ship-or-refuse. Both of those reversals were
  instruments read wrongly, not measurements. It changes
  packing, so it is `[main]` work. **This paragraph told two sessions the
  mechanism "has to be found in the players" after it had been found** — the
  fix landed and the note did not move. Write evidence with filenames in it:
  it decays loudly instead of quietly. Per-file targets are in
  `build/pace.txt`; `tests/test_pace.py` pins the estimator.
- **Update the docs as part of the build, not afterwards.** `SURVEY.md` and
  `presets.json` are generated, but `README.md`, `CLAUDE.md` and
  `H2G-CONVERSION-METHOD.md` are not — if a change alters behaviour those
  files describe (an option's effect, a player dialect, a limit), the edit
  belongs in the same commit. Docs that drift are worse than absent ones: the
  method write-up is used as reference material by another project.
- **Packing passes `gt2reloc -O0`, and that is not optional.** Its
  pulse-optimization skipping is default-on and makes the packed player execute
  no pulse table on the note-fetch tick, so a duty cycle advances on two calls
  in three where the player advances it every frame. All three packing sites
  (`fidelity.pack_sid`, `survey.py`'s own packer, `convert.ps1`) pass it;
  `pack_sid(pulse_skip=True)` restores the default for an A/B. A pulse
  measurement taken before v0.5.189 is not comparable to one after.
- **Packing back to a `.sid` needs `--legal-restart`.** Hubbard's `$FE` track
  byte means "tune ended", and the only way an orderlist can say that is an
  out-of-range restart position — which `greloc.c:244` rejects, so `gt2reloc`
  writes nothing and reports nothing (its error path goes to a console that
  does not exist headless; **test for the output file, never the exit code**).
  Off by default because it changes the bytes and the fixture carries three
  such tracks; `presets.json`'s `always` block sets it. See README.md
  § `--legal-restart`.
- **`multiplier` is not the only thing between the player's calls and ours.**
  Two more stand there, they point in opposite directions, and Ninja's bit
  `$02` had both. A call the player *skips* -- the outer gate, `RTS` spelling
  or not -- is a call our wavetable steps anyway, so `n` of its working calls
  occupy `n * (O + 1) / O` of ours (`goatwriter._gate_calls`; **not**
  conditional on `--skip-gate`, which is about how long a row lasts). And a
  call it *makes without running the block* -- the note-start path jumping
  past the effect code -- means a per-note counter reads 1, not 0, on the
  first call that reaches it, so a threshold of `t` buys `t - 1` calls. Both
  readings look reasonable and both were settled by tracing patched copies of
  the file rather than by reading the 6502 again: `threshold = 1` sounds the
  attack for zero frames, and redirecting one `LDA` printed the counter into
  `$D404`, where it read `1 1 2 3 4 4 5` and named the gate. See § 7.aaaaa.
- **A rate read out of the player is per *frame*; every table Goattracker
  applies it with steps per *play call*.** They agree only at `gt2reloc -S1`,
  and 33 of the 83 preset songs pack at `-S2`. Anything new that carries a
  rate — a slide step, a sweep, a table delay, a transient length — must be
  divided by `multiplier` at the point it is encoded, the way
  `build_speed_table`, `_drum_speed`, `_rise_speed_index`, `_wave_hold_byte`
  and the pulse programs now are -- and `_wave_program_entries` since
  v0.5.235, which until then simply *refused* every multispeed file rather
  than dividing. **A restriction is not a neutral default.** That one was
  written down honestly in its own docstring, stood for 32 versions, and was
  holding back the largest group of the onset census: seven files whose
  `--wave-program` the preset search had measured twice and could never
  select, because at `-S2` and above the option changed no bytes at all. When
  an option is offered and never chosen, hash the output before theorising
  about the criterion (`--baseline` prints it). **Encode the rate against the
  loop that consumes it, not the constant that names it**: a wavetable delay entry is
  current for `value + 1` calls, not `value` (gplay.c:697-704), and reading
  the range out of `gcommon.h` instead left every multispeed file's attack a
  call too long from v0.5.82 to v0.5.130. `tests/test_call_rate.py` now
  transcribes that loop and times the shapes against it. **And check that a
  rate byte is only a rate**: the triangle pulse engine (v0.5.174, 24 files)
  packs the step in `& $E0` and the frames between steps in `& $1F` at the
  same record `+6` the other two pulse engines read as a plain per-frame rate,
  so reading it as one would make a slow sweep frantic and a static record
  swept. Until v0.5.99 **no number in `FIDELITY.md` could
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
- **A worktree has no build artefacts, and this harness needs one.**
  `python/tools/siddump-rt/siddump.exe` is gitignored, `fidelity.SIDDUMP`
  resolves it relative to the module, and a multiplier > 1 song is *refused*
  rather than traced at the wrong rate — so a `--fidelity` search run in a
  fresh worktree silently scores only the single-speed files. It produced a
  clean-looking baseline of 15 selected songs against the real 30, and the
  difference was read as a converter change for a while before the missing
  binary turned up. Copy or build it in the worktree first, and sanity-check a
  known multispeed file before trusting anything a fresh checkout measured.

### Say, for every proposed task, whether it can be delegated

**Whenever you list next steps — in a handoff, in a "what next", in a plan —
tag each item with how it can be run.** The three tags, and what qualifies:

* **`[subagent]`** — safe to hand to one agent (the Agent tool, `/subtask`).
  Qualifies when the change is confined to `python/h2g/` or one harness module,
  is verified by a corpus byte-hash plus a targeted A/B, and **touches none of
  `SURVEY.md`, `presets.json`, `FIDELITY.md`**. Always give it
  `isolation: "worktree"`, and brief it to copy
  `python/tools/siddump-rt/siddump.exe` into that worktree first — the binary
  is gitignored, and without it the harness silently measures only the
  single-speed files (v0.5.235 read a whole invalid baseline that way).

  **A worktree is not a third kind of delegation.** It is the isolation flag,
  and a subagent *and* an agent inside a workflow can each take it
  (`isolation: "worktree"` on the Agent tool, `opts.isolation` in a workflow
  script). What it buys is one checkout per agent, which is what stops two of
  them corrupting a shared working tree. The choice to make is subagent vs
  workflow — one report, or many.
* **`[main]`** — this session only. Anything that regenerates an artefact, runs
  `presets.py --fidelity` (serial, about an hour, and it writes
  `presets.json`), or commits. Two searches at once are deterministic but
  contend; there is no reason to run them in parallel.
* **`[user]`** — needs a human. Every listening verdict, and any decision about
  what a tune should sound like. Stage the material with `listen.py` so the ask
  is a link rather than a task.

A **workflow** (multi-agent fan-out) is worth proposing only for *independent
investigations that return findings rather than patches* — "classify these 18
census misses by cause, one agent per effect byte", "read the `$80` routine in
each of these four players". It is the wrong tool for anything that ends in a
measurement of the whole corpus, because those serialise on the same binaries
and the same generated files. And it is never started without the user asking.

The point of the tag is that the user can hand a `[subagent]` item to a fork
and keep the session for the `[main]` ones. An untagged list makes everything
look like it needs this session.

A new `convert()` option is inert until it is in **three** places: the
signature, `presets.py`'s `FIXED`, and `_preset_opts`. `_preset_opts` now
derives its keys from `inspect.signature(convert)` and
`tests/test_preset_passthrough.py` fails if any option escapes, with
`presets.EXCLUDED_FROM_ALWAYS` naming deliberate omissions. Do not hand-edit
that list back into existence.

**`presets.py --fidelity` searches at `-t 60` since v0.5.235, and the ten
seconds before it were choosing settings blind.** v0.5.195 moved the *report*
to 60 s because a fifth of the corpus contributed nothing to some columns at
10 s; the search kept its own default for forty versions. Sanxion's 10 s window
holds one comparable instrument and zero noise frames against eight and 1669 at
60 s — two of `fidelity_better`'s terms are noise terms and a third is `onset`,
so the criterion was not disagreeing, it was blind, and five files lost a
`two_stage` that a 60 s A/B scores at onset 40-83% -> 100% with melody unmoved.
A corpus search now costs about four hours rather than forty minutes. When a
window is found to be too short, the finding is about the window: grep for
every other place the same one is chosen.

**Forcing one option on top of a preset measures the pair.** Star Paws with
`--wave-program` forced over its shipped settings loses 39 points of melody and
looks like a broken emitter; the actual cause is `--no-test-restart`, which that
preset carried and which owns frame 0, so the program's first opcode lands *in*
frame 0 at `-S2` and renames every attack. Left to vary all five toggles, the
search drops `no_test_restart`, keeps `wave_program`, and the song gains (onset
56% -> 78%, noise 944 -> 1614 of 2372) with melody unmoved. When a forced option
produces a *collapse* rather than a shortfall, suspect the combination before
the mechanism.

**A search that fails is not a search that says no.** One combination of
W_A_R's overflowed Goattracker's 255-entry wavetable, the exception escaped
`play()`, and `presets.py` abandoned the whole 31-combination walk for that
song and fell back to the *structural* defaults -- silently dropping the
`two_stage` an earlier search had measured. Two rules come out of it: a
candidate that will not convert is one unplayable candidate (`play` returns
None for it, exactly as it already did for a `.sng` gt2reloc refuses), and a
song whose search genuinely fails keeps what the previous run recorded rather
than reverting to a default that then looks like a decision. Read the search's
stderr for `will not convert` and `search failed` before adopting its output --
`presets.json` is a record of measurements, and a missing entry and a measured
"no" are indistinguishable in the file.

**A guarantee written in the caller is a comment.** `_wavetable_layout`
reserves `WAVE_ENTRIES_PER_INSTR` = 5 per later record and calls it "nobody
starves" -- but handed a budget of 5, **197 records across 40 corpus files
emitted 6, 7 or 8**: `_drum_entries` checked the budget for its *sweep* and not
its base, and the tick block checked nothing. Above `-S1` the frame-0 lead is
two entries and the tick's delay a third, so the five-entry assumption stopped
being true when multispeed timing arrived and nothing said so. Fixed in
v0.5.239, byte-identical on all 83 files, with the order of surrender chosen
rather than incidental: the tick block keeps the five-entry shape, and
`_drum_entries` gives up its multiplier padding before its tick. If an
invariant spans two functions, test it across both -- `tests/
test_instrument_bound.py` now does.

And an option can be inert in the other direction: **`fidelity_better` is not a
total order**, so the 31-combination `--fidelity` walk is a greedy path rather
than a maximum. Two consequences, and they needed separate fixes. It can stop
on a combination carrying a flag that changes nothing — `presets.prune_inert`
re-converts once per selected flag and drops any whose removal leaves the bytes
identical, because a preset entry is a record of a measured decision and a flag
that changes nothing was not one. And **the path can run downhill**: IK+
accepted `--wave-program` (noise 140 -> 1170 of 1517, onset 0.45 -> 0.75) and
then replaced it with a candidate worse on both, which won on a fourth term.
`fidelity_better` now also requires the candidate to be no worse than the
reference on `onset`, and never to lose the noise outright. **Two vetoes, not
five**: written to cover every comparable term it rejected the candidate it was
built to protect, because the oscillation ratio and the noise *pitch* are
estimated over the frames the setting itself creates (IK+: 140 noise frames
without `--wave-program`, 1170 with) -- the veto form of "read a register
agreement next to both sides' note counts". That version lost seven measured
settings corpus-wide and gained one; it was caught by diffing the search result
against the shipped presets before adopting it, which is the check to run on
every search. Do not read the greedy path itself as a defect to fix with a
single scalar score — five incommensurable dimensions collapsed into one number
would be the worse lie. **"Any one improving" is a sound acceptance rule and an
unsound replacement rule**, and that distinction generalises past this repo.

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
