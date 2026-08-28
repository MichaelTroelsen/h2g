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
  python survey.py <sid_dir> -o ../docs/SURVEY.md --legal-restart --gt2reloc   # corpus report
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
  `python fidelity.py <sid_dir> -t 60 --presets ../presets.json -o ../docs/FIDELITY.md`
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
  **They also disagree about the wavetable's right-side byte -- and the packer
  inverts it, which is the half this paragraph got wrong for eight versions.**
  In the packed player `$00` is **no frequency write at all**
  (`player.s:976-977` tests `bne`) and `$80` is `adc chnnote / and #$7f` --
  `(128+n) & 127 == n`, a no-op transposition that still writes. Both true,
  and both about the byte **after** `gt2reloc` has touched it:
  `greloc.c:1340-1341` does `insertbyte(rtable[c][d] ^ 0x80)`, commented "For
  normal notes, reverse all right side high bits". So for anything **writing a
  `.sng`** the mapping is inverted, and the byte that leaves a bend alone is
  **`$80`**, not `$00`:

      .sng $80 -> packed $00 -> no frequency write
      .sng $00 -> packed $80 -> writes the pattern's own note

  `_hold_wave_program_entry` wrote `$00` on the strength of the old reading, so
  a `>= $80` opcode's absolute pitch was re-asserted away by the base note one
  call later; at `-S2` an opcode is entry+hold, so the pitch landed on the
  frame's first call and was gone by its second, and siddump -- one sample a
  frame -- read a flat pitch and reported no defect. Fixed at v0.5.336: 8
  files move, exactly `{wave_program AND multiplier > 1}`, `vib` is the only
  dimension that moves on any of them, and the `program` bucket's missing
  reversals go 2021 -> 549. Confirmed on bytes rather than argued -- Ricochet's
  `.sng` right column against the same run in its packed `.sid` differs by
  exactly bit 7 ($00<->$80, $C2->$42). This is the same lesson as the
  `$E0`-`$EF` range two bullets down: **read `greloc.c` beside `player.s`, and
  settle it on the packed bytes**, because every rule here is a rule about what
  to *emit* and the packer sits in between.

  **RETRACTED, and it is v0.5.336's own commit message that says it.** That
  message closes "two whose programs are made entirely of `slide` opcodes and
  so carry no absolute pitch to keep (Saboteur_II `$0888`, Shockway_Rider
  `$0889`)". Both halves are false, and the sentence never reached a doc --
  which is why it is written down here rather than corrected in place: it is
  in the history, greppable, and the next reader of that commit needs the
  retraction to be findable from the same words. Decoded from the players'
  own bytes, **every** wave program in the five files opens with a `set`
  opcode, and a `set` carries the absolute frequency high byte:

      Saboteur_II   rec 4 ($0888)  set $81 $2C / set $81 $20 / slide $11 $0180 ...
      Shockway      rec 2 ($0889)  set $81 $30 / slide $41 $01C0 / slide $40 $0140 ...

  We emit that pitch, and have since before the sentence was written. The real
  defect was the *slide's* right byte, fixed at v0.5.341 -- a `< $80` opcode
  subtracts from a frequency accumulator and exits through a path that writes
  it, so the slide returns to the note, not to the last `set`.

  **The same message's second error is inherited by anything quoting it**:
  neither record is single-speed. Saboteur II packs at `-S3` and Shockway
  Rider at `-S2` (`presets.json`). The three single-speed wave-program records
  are Pandora `$0C99`, IK+ `$0505` and Nemesis `$0CC8`, and after v0.5.341 all
  five have the same one remaining cause -- the slide's *travel*, which is a
  linear frequency subtraction and so wants `WAVECMD_PORTADOWN` rather than a
  right-side note byte, whose semitone size depends on the note played
  (Saboteur's first slide is -1.16 st under `$1739` and -0.36 st under
  `$49B8`). The general rule: **a commit message is not a doc, and it is also
  not erasable** -- when one turns out to carry a wrong mechanism, retract it
  somewhere a grep for its own words will land.

  **The travel is emitted now, above `-S1`** (`_wave_program_travel_entry`).
  What made it look impossible was reading the wavetable's right column as the
  only place a pitch can live: it names notes, so a linear frequency
  subtraction cannot go there. `WAVECMD_PORTADOWN` can, and a slide opcode is
  one of the player's *frames* -- `multiplier` play calls -- so at `-S2` and
  above the waveform entry does not need them all and the spare call carries
  the portamento inside the same frame. 8 corpus files move, exactly
  `{wave_program AND multiplier > 1}`; the 13 single-speed ones are
  byte-identical, because at `-S1` a second entry would halve the program's
  rate (the trade v0.5.203 measured and refused). ACE II `$EB0A` now
  reproduces the original frequency for frequency -- `0EA3 40A3 0B23 0923
  03CE` -- where it held the base note and rang its whole release two octaves
  high. A/B over the 8: `melody`, `seq`, `pitch`, `retrig`, `wave`, `noise`,
  `adsr`, `gate`, `nrun`, `hold`, `onset`, `tail`, `pul`, `filt`, `cut` and
  `drift` all flat on all 8, `vib` moves on 7 (Ricochet 0.78 -> 1.02, Star
  Paws 0.89 -> 1.04, three others within 0.07 of 1 either way).

  **And the entry that re-anchors is the one to watch, not the portamento.**
  The first version wrote `WAVE_NOTE_BASE` plus a portamento of the whole
  running sum on *every* slide -- exact in the player's terms, and it read as
  a completely flat pitch on the trace, because the note lands on the frame's
  first call and the correction on its second while siddump samples once a
  frame. The shipped form anchors only where it must (the first slide, and
  any slide after a `>= $80` opcode, which leaves an absolute pitch in the
  register) and otherwise carries that opcode's own operand from where the
  last one left off, so the frequency only ever moves the way the player
  moves it. **Two encodings can be equally correct per call and differ
  entirely in what a per-frame instrument can see.**

  The Hollywood or Bust case that produced the old wording is still real and is
  a different one: choosing `$80` there took melody to 25% against 47% by
  re-asserting the base note every frame -- but that was a *waveform* entry
  reasoned from `gplay.c`, the editor, with no packer transform in the
  argument. On a **delay** entry the two are equivalent: `player.s` reads as
  though the jump path leaves carry set (a semitone up), and tracing W_A_R both
  ways gives 0 of 1500 frames differing on all three voices.
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
- **A PSID header's subtune count is not a promise, and there are now THREE
  bounds on it.** The track table has no length field, so the header routinely
  over-declares and reading past the end yields whatever bytes follow. Applied
  in order, tighter wins: the player's own init dispatch
  (`detect.find_music_subtunes`, a `CMP #imm / BCS / JMP` at the entry — 8
  files, 97 subtunes), the digi engine's `subtunes_available`, and the layout
  extent (`tracks.track_table_extent`, where the track table runs into the
  pattern table — 22 files, 204 subtunes). Each dropped subtune is attributed
  to the bound that dropped it, which is what makes `SUBTUNES.md`'s by-cause
  table readable rather than a single bucket.
  **Two things worth carrying.** The dispatch and the extent were derived
  independently, by agents that never saw each other's work, and they AGREE on
  seven of the eight files that carry both; Spellbound is the one disagreement
  (layout 4, dispatch 3) and the dispatch wins, because it says what the player
  *does* where the extent says only what the table has *room for*. And the
  census's old headline — "essentially all of the loss is reading past the
  end" — is now three quarters true rather than all: 97 subtunes have a
  positive, player-derived cause. **That sentence is still in
  `python/survey.py`'s template and therefore in every regenerated
  `SUBTUNES.md`**; fixing it is a code edit, not a doc edit.
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
- **"No column moved" has two causes, and a third: the register is one every
  column deliberately ignores.** `--rest-keyoff` moves 19 files' bytes and one
  file's report row, because a Goattracker KEYOFF clears the *gate* and
  nothing else -- and `wave` excludes the gate bit by construction, `hold`
  counts frames with a waveform selected, `adsr` reads registers it does not
  write. The blindness is structural rather than accidental, and it made a
  whole class of change unscoreable without anyone deciding that. **When a
  column documents what it ignores, read that list as a list of things you
  will not be able to ship on evidence** -- and then *build the column*
  rather than shipping on a hand-rolled probe. `gate` (v0.5.270) took
  `--rest-keyoff` from "flat on 18 of 19 files" to "12 files, all 12 upward"
  and moved it into `presets.FIXED`. The gap between correct-by-the-player
  and shippable was one dimension, not a listening session. See § 7.fffff.
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
- **"No dimension can see this change" can be true of the report and false of
  the file, when the bytes that moved are in a subtune `--baseline` never
  traced.** A row's `output_sha` hashes the *whole* `.sng`, so it correctly
  says the converter's output changed, but every `Dimension` reads only the
  one subtune the run traced -- so a change confined to another subtune
  prints the same "structurally incapable of registering it" verdict as a
  change genuinely invisible to every register, and a reader has no way to
  tell the two apart. This is not hypothetical: `boundary-tie-loop-around-
  restart-position` (cycle 4) cost Star_Paws -38pp of melody in a subtune
  outside the traced one, and the verdict read as though nothing could be
  said. Fixed by `subtune_content_shas()` -- one sha1 per subtune, over its
  own three orderlist tracks plus the raw bytes of every pattern those
  tracks reach (a pattern several subtunes share folds into all of their
  hashes, so a shared-pattern change is attributed to every subtune that
  plays it, not just the first one that names it). `compare_runs()` now
  prints which subtune(s) actually differ per file, in the "no dimension
  sees this" branch and in the partial "blind" case alike, and says loudly
  when the traced subtune is **not** among them. A row from before this
  field existed (`subtune_shas` absent) falls back to naming the traced
  subtune rather than asserting silence it has not earned -- the same
  backward-compatibility shape `output_sha` itself uses.
- **A low score in `FIDELITY.md` is a claim about the harness until it is a
  claim about the converter.** Six separate defects have now been *in the
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
  matrix first, then a per-voice cause. **All four** of the files the report
  filed under "plays something else" were the harness, and they were three
  different harness defects. Two were the correspondence: Dragons_Lair_Part_II
  is 14% on the diagonal and **88%** at its real counterpart o9, all three
  voices matching (0.89/0.89/0.88, pitches 96/81/95%), and
  Commodore_64_Music_Examples is a clean off-by-one, s1→o0 at 93%.
  Flash_Gordon's traced subtune is its worst of nine.
  **The 60%-and-"voice 2 still reads different music" this paragraph carried
  from v0.5.325 was a THIRD harness defect, in `--diagnose` itself.**
  `subtune_matrix` and the per-voice section traced OUR side with siddump's
  default 1 call a frame while `_measure` traces it at the packed `-S`, so
  every cell for a multispeed file compared the original at speed against our
  conversion at 1/multiplier of it. Spellbound's diagonal read 57% where the
  report's own row for the same pair reads 93%, and its voice 0 was filed as
  "under-produced: 18 attacks against 93" — half-speed, not under-produced.
  Fixed by passing `multiplier` through; the original stays at `-m1`, which is
  the rule of *The multiplier belongs to our side only* two bullets up. The
  lesson is that one: a diagnostic that re-derives what the harness already
  resolved will get one of the three inputs wrong, and here the wrong number
  reached a doc and stood for two sessions as evidence of a converter defect. The other two were
  **the original ending inside the window**: Hubbard's `$FE` means *tune
  ended*, a Goattracker orderlist cannot say that, so our conversion restarts
  and every sequence column was charged for a loop the original never plays.
  Geoff Capes read `retrig` 3.21 / `melody` 49% and reads **1.02 / 100%** over
  the 17 s the rule gives it; Kings of the Beach ingame **7.82 / 23% → 1.04 /
  98%** over 8 s. `fidelity.original_ended` is the rule, and it is gated on the
  original *stopping* — a trailing silence longer than twice its own largest
  gap between attacks, and 5 s outright — never on the two sides disagreeing,
  because shortening a window can only remove our surplus and so flatters every
  column it touches. The report names the rows it shortened. See v0.5.328.
  `--search-subtunes` cannot substitute: it varies *our* index while holding
  the original's fixed, and in these files the original's is the one that
  moved. On the per-voice question, a modal semitone delta's share degrades
  when either side drops notes, so a *low* share is not evidence of
  scrambling — `--diagnose` sweeps a constant transposition through a difflib
  alignment instead and reports the peak, signed as ours against the
  original's.
- **A register zeroed at a *rest* is not a register zeroed at a *note end*,
  and the option that fixes one destroys the other.** ACE_II's lead rings a
  release-9 tail through 575 of voice 1's 2996 frames where the original's
  ADSR reads `$0000` -- and `--cut-release` is inert on it, because
  `det.envelope_cut` is false. The reflex is to widen `ENVELOPE_CUT_SHAPES`
  until it matches. That would be wrong: `cut_release` zeroes the release
  nibble in the *instrument*, so it applies at **every** note end, and this
  player cuts only at the bit-6 rest -- its ordinary note end just clears the
  gate (`$E1E6 LDA #$FE` into the mask `AND`ed at `$E464`) and the release
  really does sound. Two mechanisms, two populations, and they are
  **disjoint**: `envelope_cut` 33 files, `rest_silence_envelope` 21, zero
  overlap, which is the check that says they are different players rather
  than one probe missing a spelling. The faithful write is a `CMD_SETSR $00`
  on the rest row, self-restoring exactly as the player's is (the next note
  reloads it, gplay.c:398 / player.s:882). See README § `--rest-envelope-
  silence`. **The same reading corrected an old name**: `_rest_silence_kind`'s
  `"testbit"`/`"envelope"` split is over the *waveform* byte left in A at the
  store; the envelope zero is the half all 21 share, and reading the two
  names as two families put 17 files in the wrong bucket for as long as they
  existed.
- **Row 0's command column belongs to the subtune's clock, and nothing else
  may take it.** `apply_tempo`/`apply_tempos` *skip* a pattern whose command
  column is occupied, so a row-0 command silently costs that subtune its
  `CMD_SETTEMPO` and it plays at Goattracker's default 6. This has now caught
  three changes -- v0.5.284's rest waveform (melody -43pp over 8 files),
  `_apply_boundary_ties` on Star_Paws (`drift` -111 -> +1667), and the rest's
  `CMD_SETSR` (ACE_II `drift` 0.00 -> **1250**, mean melody **-47pp** over 12
  of 19 files, on a change whose real reach is one register between notes).
  It is `patterns.TEMPO_OVERWRITABLE` now, one named set, and **a new row-0
  command must declare itself there as well as in `ONE_SHOT_COMMANDS`** --
  the two are different questions (does it repeat down the hold rows / may
  the tempo take it back) and the second is the one that looks like a
  catastrophe.
- **A per-subtune value written into a global structure is read by every
  subtune that reaches it.** Goattracker's patterns are global, its orderlists
  are per subtune, and a `CMD_SETTEMPO` under `$80` sets all three channels
  (`gplay.c:494`) — so `apply_tempo`'s "a pattern shared by several positions
  simply re-applies the same tempo, which is harmless" was true within one
  subtune and false across two. Seven corpus files and eleven subtunes were
  executing another subtune's clock, Human_Race's by 25%: **note gaps of 24
  frames against the original's 32**, on an identical note sequence. Fixed at
  v0.5.330 by `apply_tempos`, which compares the values before writing any of
  them and clones a contested entry pattern. Two lessons beyond the fix. **A
  guard tested on one variant does not cover the other**: v0.5.320 tested
  exactly this hypothesis — "the value lands on a row another subtune plays" —
  found the *widened* write byte-identical when restricted to exclusive
  patterns, and concluded sharing was not the cause; the **default** write had
  the same exposure and was never tested. And **read all three voices before
  concluding what a subtune does**: v0.5.323 read Knucklebusters' subtune 0 as
  "`CMD_SETTEMPO` row 0 → 6" from voice 0 alone, where the three entry patterns
  read `[6, 3, 3]` and the player executes 3. That misreading is why its
  50 → 81 pp melody gain stood for two sessions as a lever with "no identified
  mechanism".
- **A wrong clock masks the defects underneath it.** Correcting Human_Race's
  tempo took its `drift` −250 → **0.00**, `wave` 63 → 92% and voice 0 to exact
  (40 attacks against 40, the same gap histogram) — and its `melody` 65 → 56%,
  because voice 1 turns out to re-strike on nearly every row and the right clock
  is what made that audible to the trace. The subtune's pattern bytes are
  identical either side of the change, which is how you tell an unmasked defect
  from an introduced one: **diff the structure, not the score**.
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
- **A `-` in the report is a finding, not a gap.** Powerplay Hockey printed
  `-` for `onset`, `nrun`, `hold` and `tail` from the day each was written,
  and `adsr` 0%, while `melody` said 72% and `--diagnose` confirmed the
  traced pair was the right music. Those four columns key instruments by
  their ADSR pair, so `-` means *no shared key*: the original sounded four
  envelope pairs that appear at no offset of any record in the table
  detection had found. The file carries **two copies of the player** and the
  chains took the orderlists from one and the instruments from the other --
  right notes, wrong instruments. Picking the table nearest the pattern
  pointers (the rule `find_song_speeds` already uses for gates) takes it to
  melody 99%, `adsr` 99.9%, `retrig` 1.01, and moves no other file. See
  § 7.iiiii.
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
- **The vibrato DEPTH is about 2.4x too shallow, no column can see it, and the
  obvious repair is refuted twice over.** A listener reported ACE II's lead as
  under-vibratoed; measured within notes (segmented on GATE RISING EDGES, not
  on note names -- siddump prints the *nearest* note, which flickers during
  vibrato and chops every note into fragments too short to measure), its
  instruments 9/10 and 6 swing 1.6% of pitch against the original's 5.6%.
  Restricted to the population that carries a vibrato byte at all --
  `record + det.vibrato_offset` non-zero, the § "a discriminator is only
  meaningful on the population the behaviour occurs in" rule -- the corpus
  median is **2.39x over 33 files, and every multiplier group exceeds 1**,
  including `-S1` at 1.91x where the multiplier term is zero. **A first pass
  that did NOT restrict to that population is worthless and was discarded**:
  it reported "depths" of 273% and 397% of pitch, which are portamento slides
  and drum sweeps, and its by-multiplier medians all sat at ~1.0.
  `vib` cannot see any of this -- it counts pitch *reversals*, i.e. the RATE,
  which we already get right (ACE II reads 1.09x). This is the § "prefer a
  travel measure to a count whenever the change is to a step size" case, still
  unbuilt for oscillation depth.
  **Dropping the `+1` from `rshift = shift + 1 + _rate_shift(multiplier)` is
  not the fix**, and the second refutation is now on the record with numbers.
  It moves exactly the 55 files carrying this engine and reproduces v0.5.129's
  rejection *to three decimals* -- Powerplay 0.993 -> 0.922 and Sigma Seven
  0.990 -> 0.972, the figures already written down -- while adding two
  casualties that were not: International Karate 0.980 -> 0.826 and
  **One_on_One_Jordan_vs_Bird 0.986 -> 0.299**. Zero files improve on melody,
  sequence or pitch. The cause is that a deeper swing has already moved the
  pitch by the frame siddump names the attack on, so it renames attacks. The
  Commando fixture is unaffected either way (`vibrato_offset` is None on both
  its rips), so the fixture is not what blocks this.
  **The lead was right, and it is now the fix (v0.5.369).** If the swing renames
  attacks because it is already deep AT the attack, the lever is `vibdelay`, not
  `rshift`: siddump names a note from the frequency on the frame the gate rises,
  so delaying the oscillator until frame 0 is over removes the CAUSE rather than
  paying for it -- the attack keeps the note's own pitch and the deeper swing is
  then free. `rshift` loses its `+ 1` and the classic engine's `vibdelay` becomes
  `multiplier + 1` calls. The four files the rshift-only route destroyed are
  UNMOVED: One_on_One_Jordan_vs_Bird 0.9864, International Karate 0.9800,
  Powerplay 0.9930, Sigma Seven 0.9903, against 0.299/0.826/0.922/0.972 under
  rshift alone. Corpus: 55 of 83 files move -- exactly this engine's population --
  depth median **0.399 -> 0.817**, `vib` |log ratio| median 0.199 -> 0.171, and
  **zero files worse on any of melody, seq, pitch, wave, onset, hold, gate, adsr,
  nrun or tail**. **Scope it to the classic engine**: the first cut delayed the
  LFO table too and broke its documented "starts on the note" property.
  **AND THE COST IS ONE NO COLUMN CAN SEE.** The oscillator now starts
  `multiplier` calls later -- 1 frame at `-S1`, 1.33 at `-S3` -- and nothing in
  FIDELITY.md measures when an oscillation STARTS, so the corpus A/B that
  justifies this change is structurally blind to its only downside.
  `_vibrato_delay`'s docstring already records a listener reporting the vibrato
  starting late. A clean sweep on every column is not evidence here; it is the
  shape of a measure that cannot look. If a late onset is ever reported, the
  delay is tunable below `multiplier + 1`, trading depth back for onset.
  **That measure now exists**: `depth` (`depth_ratio`), the column immediately
  right of `vib`, added because this deficit was invisible to every other one.
  It reads $D400/$D401, segments on gate rising edges, and is restricted to the
  records that carry the mechanism -- which turned out to need MORE than the
  vibrato byte being non-zero: a record also setting a bit the player reads as
  a pitch mover reported Commando at 59% of pitch and Zoids at 67%, eight
  semitones and an octave, which no vibrato is. Excluding those takes them to
  2.19% and 2.18% and leaves ACE_II untouched. ACE_II reads **0.27x** where
  `vib` reads a flat 1.09x, and the 15-file subset median is 0.399 = 2.51x,
  against the 2.39x this paragraph recorded from a scratch probe. Two rows are
  unexplained and were not chased: Thrust reads an original depth of 22.44% and
  Warhawk 11.24% on clean populations.
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
- **The multiplier belongs to our side only.** `_measure` traces the original
  at `-m1` and the conversion at `-m{multiplier}`, because the original is a
  50 Hz VBI tune and the `-S` factor is a property of what `gt2reloc` packed.
  A probe of mine traced *both* at the multiplier, which plays the original
  three times too fast, and reported a clean bimodal distribution of
  one-frame gate edges that does not exist -- with a mechanism-shaped story
  already attached to it. The tool's own census says zero such edges on that
  file. **What caught it was that two numbers could not both be true**, not
  that either looked wrong. Add the question to the harness, which already
  resolves the subtune, the multiplier and the startup lag; a probe
  re-derives all three and need only get one wrong. See § 7.ggggg.
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
- **A value written into a counter is not a quantity until you know what the
  counter does.** Rasputin's orderlist `$FE nn` writes the counter *above* its
  speed gate, not the gate -- so the operand scales the row by `(R+1)/R` where
  reading it as the row itself gives 121 frames against a neighbour's 3, a 60x
  error on the same byte. The two gates sit 78 bytes apart and differ only in
  where the reload comes from (`LDA abs` against `LDA #imm`, which is also why
  `OUTER_GATE` does not match this one). What separated the readings was not
  more disassembly: it was asking whether the music the operand implies could
  be the music the patterns around it contain. See § 7.ddddd.
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
- **Keep the *command* short; put the long text in a file.** A commit message
  or a probe script piped through `git commit -F -` / `python - <<'PY'` makes
  the command itself thousands of characters long, and past a limit the
  harness cannot security-scan it: it stops and asks a human, in the middle of
  work a fork was supposed to do unattended. Write the message or the script
  with the Write tool and pass a path -- `git commit -F <path>`,
  `python <path>`. This is the same fix as the heredoc-mangling rule below and
  the permission-allowlist one: a short command with a fixed script name is
  also the only shape an allowlist entry can generalise over.
- **A probe that wraps `convert()` must assert its own success rate.** A
  scratch byte-hash script passed `quiet=True`, which `convert` does not
  accept, so it recorded `ERR TypeError` for all 95 files and every comparison
  was between two identical sets of error strings -- publishing "0 of 95 files
  move" as evidence in **two** commits that had measured nothing. Both claims
  turned out to be true (re-verified from clean worktrees with presets held
  constant), which is exactly why it survived: a vacuous check and a correct
  conclusion look identical from the outside. It is the third probe in one
  session to fail by not reproducing the harness's calling convention -- the
  others omitted `--tempo auto` (§ 7.kkkkk) and the frequency-table
  calibration (§ 7.mmmmm), each producing a confident wrong reading. Refuse to
  write a result where most conversions failed, and prefer a *test* over a
  probe: v0.5.279's identical claim was sound because
  `test_engine_zero_is_byte_identical_across_the_corpus` is a test.
- **A probe reading a SUBSET of a report's columns must assert every column
  it names exists.** A narrower failure than the one above, and it shipped
  and was retracted (v0.5.352/353, 864d096): the probe DID follow the "assert
  your own success rate" rule -- it went through `fidelity._preset_opts` with
  the right keys and every conversion succeeded. What it did not do is check
  that the *columns* it compared exist. It asked each row for `pitch`, `seq`,
  `hold`, `retrig`, `noise`, `onset`, `tail` and `nrun`; the real keys are
  `pitch_jaccard` and `sequence`, and the rest are absent from `--json`
  entirely (see `fidelity-json-omits-retrig-hold-tail`). `dict.get` returned
  `None` for all eight and the loop skipped them in silence, so a 14-column
  comparison reported on six and announced "5 better, 1 worse" -- on which an
  adoption was made and then retracted. Silently comparing fewer columns is
  indistinguishable from comparing all of them and finding no movement, which
  is the same shape of lie as the probe above, one level down: that rule
  guards *whether the conversions ran*, this one guards *whether the report
  actually read what it claims to have compared*. What caught it was not the
  probe -- it was regenerating `FIDELITY.md` and reading the row, which
  showed `pitch 100% -> 93%` and `seq 100% -> 99%`, columns the probe had
  never looked at. Regenerating the artefact is a second, independent reader
  of the same measurement; prefer it *before* adopting a candidate, not
  after.
- **An explanation that fits the shape of a regression is not thereby its
  cause -- turn the proposed cause off and see if the effect survives.** A
  bit-6 rest parks `$08` in the stored waveform on 17 files and a Goattracker
  KEYOFF cannot express that (it is a gate mask, `wave & gate`), so the rest
  emitted `CMD_SETWAVE $08`. It cost **melody -43pp over 8 files**. § 7.ooooo
  attributed that to `gplay.c` reloading `firstwave` and the wavetable pointer
  only `if (newcommand != CMD_TONEPORTA)` -- a slide landing after the rest
  never taking the `$08` back. The reading was correct about `gplay.c`,
  predicted the right shape (worst where slides are most common), and is
  **wrong**: suppressing TONEPORTA after a rest changes **zero bytes** on all
  fifteen files, so the mechanism occurs nowhere in the population it was
  meant to explain. One run would have falsified it before publishing.
  **And count what you emitted**: the change wrote 673 command bytes where 61
  were designed -- a bit-6 event's `wait` hold rows reuse `cmd1`/`cmd2` -- so
  the A/B measured something other than the change as described. That is
  visible from the output in one query. See §§ 7.ooooo and 7.ppppp; the real
  cause is not yet known.
- **A trace that shows what is wrong does not tell you what writes it.** IK+'s
  wave-program instruments end their notes on `$08` where ours latch `$40`,
  visible frame by frame -- and emitting that silence directly took Nemesis
  the Warlock's `wave` from 75% to 30% while gaining at most 3 points on four
  files. The mechanism was never located (`$E44C` restores
  `LDA $E58F,X / AND $E5E0,X`, and `$40 AND anything` is not `$08`, so a
  second write path exists and was not found); what shipped would have been an
  approximation standing in for it. Reverted. See § 7.nnnnn -- and note the
  related trap that **`$18` is not `$08`**: both are silent to the ear, but
  `wave` scores the waveform class, `hold` counts frames with a waveform
  selected, and siddump needs a frame below `$10` to name the next attack, so
  the `$18` version moved not one column on any file.
- **A scripted edit must assert its match.** `str.replace` with a search string
  that does not match returns the input unchanged and raises nothing, so a
  `python - <<PY` rewrite can report success while changing no bytes. v0.5.192
  and v0.5.193 both shipped commit messages describing edits that never applied
  — including "`_noise_tick_frames` is now wired", which it was not — and
  neither the test suite nor the byte-exact fixture could catch it, because the
  affected file's derived value happened to equal the constant it replaced.
  `assert old in s` before every replace, and check the change is in
  `git diff`, not merely that the tests still pass.
- **THE CONVERSION MUST BE THE SAME LENGTH AS THE ORIGINAL, WITHIN ±5 SECONDS.**
  A listener's rule, and it is an invariant no column enforces. Where the
  original *ends*, ours must end too. This is not about tempo — `drift`,
  `retrig` and `--pace` all measure the rate of a row and are all satisfied by
  a conversion that plays the right music at the right speed **forever**.
  Measured on Action_Biker at v0.5.375, traced 180 s both sides: the original
  makes 291 attacks, its last at frame 2977 = **59.54 s**, and then 120 s of
  silence — it STOPS. Ours makes 856 and never stops, looping with period
  **61.44 s**. Per loop it carries exactly 52/52/187 attacks per voice against
  the original's 52/52/187 *in total*, so the music is right and only the
  ending is wrong. A listener hears this as "the H2G song is longer", which is
  the only instrument that reports it.
  The cause is documented and is a property of the target format: Hubbard's
  `$FE` track byte means *tune ended*, a Goattracker orderlist cannot say that,
  and `--legal-restart` turns it into a restart at position 0 — which is what
  makes the file packable at all. The repair is not a new mechanism but a
  choice of restart target: an orderlist can loop a SILENT pattern instead of
  position 0, which ends the tune in every way a listener can hear.
  **And note where this rule bites the harness, because it is the same failure
  this project has now hit twice.** `fidelity.original_ended` already detects
  the condition and uses it to SHORTEN the comparison window so our surplus is
  not charged — the score is protected and the shipped `.sng` still plays
  forever. That is exactly the `--search-subtunes` shape corrected in v0.5.375
  (*a shim that hides a defect from the score does not hide it from the file*),
  one level over. Any tune whose window `original_ended` shortens is a tune
  that FAILS this rule; the report names them, and that list should be read as
  a defect queue rather than as a methodology note. Action Biker is not among
  them only because its 60 s window happens to end where the tune does, so its
  `melody` 100% is honest — the surplus is entirely outside the window.
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
  gap looked like a refutation of the factor twice. **And neither can see a
  row wrong by a *fraction* of a frame** — a Goattracker row is whole play
  calls, so such an error is zero on most gaps and one whole frame on the
  occasional one, and the median of those ratios is exactly 1.000. That is
  structural, not a threshold to tune: the fix was a different statistic of
  the same two traces, `--pace`'s `drift` line, which integrates the offset
  instead of averaging ratios. 37 corpus files drift by zero and 29 drift,
  and the cause is exact — **`drift = -1/(skip + 1)`**, the outer gate's
  skipped call, which `effective_frames` corrects only when the corrected
  row can be packed (Delta 5/2 at `-S2`) and declines when it cannot (IK+'s
  3 x 113/112 wants 339 calls at `-S112`). So it is a known limitation with
  a number on it, not a new defect; the fix is re-gridding, not a tempo.
  **`--regrid` is that fix, and it shipped in v0.5.397.** A row is a whole
  number of play calls, so a player whose row is 384/127 = 3.0236 frames
  (Monty subtune 0) ships at 3 and runs 0.78% fast -- and 3 is the nearest
  ratio at *every* denominator up to 10, so no tempo can do better and the
  exact value wants `-S127`. The option gives one row in 42 an extra call
  with `CMD_SETTEMPO` and takes it back on the next row. It reaches 18 corpus
  files, drift improves on 14 and five land on exactly 0.00 (After_8
  -12.35 -> 0.00, Arcade Classics -7.79 -> 0.00, Nemesis -7.75 -> 0.00);
  Monty goes -9.30 -> -1.56 with `hold` +12.5, `adsr` +5.9, `gate` +3.1 and
  `pitch` -2.7. **Per song, never a default** -- `melody` collapses on
  One_on_One (-37.0pp) and Sanxion (-19.9pp).
  Three things worth carrying beyond the option. **The schedule is one voice
  per subtune**, because `CMD_SETTEMPO` under $80 sets all three channels --
  compensating in all three lengthens the same row three times, which turned
  Monty's 15-frame deficit into a 21-frame surplus and read, wrongly, as the
  mechanism not working. **The compensation is a property of the PATTERN, not
  the orderlist position**, which is what makes it affordable: patterns are
  global and 56 of Monty's 153 are replayed, so a per-position schedule would
  need a copy per phase -- the cost that stopped the pulse-phase work. And
  **the restoring row must stay inside the pattern**: the row after the last
  is whatever the orderlist plays next, and a first version let the restore
  land on the `GT_END_PATTERN` marker, leaking the raised tempo into the
  next pattern. A test caught that one, not a listener.
  **And nothing in `FIDELITY.md` can adjudicate this option** -- every column
  compares *what* is played, so a tune playing the right music 0.78% fast
  forever scores perfectly. `--pace`'s `drift` line is the only instrument
  that reads it, and it is not a report column, so each of the 12 adoptions
  in `presets.json` is a hand-recorded measurement rather than a search
  result. `fidelity_better` cannot select it and must not be given it.
  Its intercept is the startup lag as a free by-product, and **that
  by-product is what caught two wrong estimators** — a least-squares fit
  reporting +38 frames of lag where the harness measures 5 was the signal
  it was fitting difflib's outliers. See § 7.mmmmm. **And a file packed
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
- **A bound the codebase KNOWS is not a bound the emitter ENFORCES, and
  gt2reloc will not tell you.** `patterns.MAX_PATTERNS` is 208, matching
  GoatTracker's own `MAX_PATT` (gcommon.h:30), and three call sites already
  respect it -- `apply_tempos` drops a clone rather than exceed it,
  `reindex_tracks` refuses a copy at the limit. `legalise_restarts` did not:
  `--silent-park` appends one silent pattern per file, and W_A_R converts to
  exactly 208, so it shipped **209**. Nothing anywhere reported that. gt2reloc
  packed it and returned success, the byte-exact fixture was unaffected, the
  suite was green, and `survey.py` counted it as converted -- while the packed
  player ran subtune 0 at gplay.c:198's DEFAULT tick (`6 * multiplier - 1`)
  instead of the `CMD_SETTEMPO 9` sitting on row 0 of the pattern its orderlist
  enters on. 24 calls a row against 9 is the 8/3 that a previous session
  measured and could not explain.
  Fixing the one condition took the corpus's third-worst melody row to a
  perfect one: **melody 18.6% -> 100%, sequence 19.4% -> 100%, pitch 73.7% ->
  100%, adsr 25.7% -> 100%, wave 59.6% -> 97.9%, gate 14.7% -> 79.9%, and the
  attack count 70 -> 327 against the original's 327 exactly.** One corpus file
  moves and it is W_A_R.
  Three things generalise. **The failure was silent in every channel this repo
  has** -- an overrun one index past a table's end is the same class as the
  `exectable` case that `tests/test_table_validation.py` exists for, and the
  pattern COUNT had no such test. **The right failure was already written down
  beside the missing guard**: the `MAX_TRACK_LEN` branch declines to park
  "because an unpackable file is worse than a looping one", and a file one
  pattern over the limit is worse still, because it is not unpackable and so
  nothing announces it. And **the previous session's frame was the trap**: it
  had located the symptom exactly ("subtune 0 runs at the default tick") and
  named the next step as reading `greloc.c`'s tempo handling -- which is
  correct code doing nothing wrong (`greloc.c:1823-1830` keeps a global tempo
  and merely decrements it). A correctly located symptom can still point at
  the wrong file; the census that found it was "which files exceed a limit the
  code already names", not more disassembly.
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
- **Read `--pace`'s spread before its number: a tight ratio is a constant, a
  loose one is a mechanism.** Ninja measured `0.750` with an interquartile
  range of `0.750-0.750` over 858 gaps -- three quarters on *every* gap, which
  no musical irregularity can produce and only a wrong constant can. It was
  the fallback tempo, taken because `SPEED_GATE` missed the player's gate by
  **one byte of branch offset**: `DEC / BPL +5 / LDA #$02 / STA` against the
  pattern's `BPL +6 / LDA abs`, because `LDA #imm` is two bytes where
  `LDA abs` is three. A signature that encodes an addressing mode encodes an
  instruction length, and that length is in every branch offset around it --
  so two spellings of one idiom differ in two places at once, and matching
  neither is indistinguishable from the player not having the feature.
  Reading it took Ninja to melody/seq/pitch 100% and `retrig` 1.00 from
  85/86/79% and 1.33. `SPEED_GATE_IMM` is a **fallback**, consulted only
  where the absolute form found nothing: 35 files carry its shape and 33 of
  them already read a gate, and a wrong tempo is worse than the old constant.
  See § 7.eeeee.
- **The same lesson, one table over: the "music selector" signature encoded an
  addressing mode, and what it read was the DESTINATION of a copy.** Three
  players (Action Biker `$C2AB`, Samantha Fox `$7D35`, Spellbound `$EF9A`)
  copy the six bytes of the selected subtune's three pointers out of the track
  table into a fixed six-byte scratch buffer, and the rest of the player reads
  the buffer. The subsong chain fingerprints that reader (`LDA buf,X / STA $4B
  / LDA buf+3,X / STA $4C`), so it names the **buffer**; the selector
  signature exists to correct it to the table. See § 4.4. It opened on `CLC / ADC $abs / TAX` (`18 6D lo hi AA`), which
  these three spell `ASL / STA $zp / ASL / CLC / ADC $zp / TAX`, one of them
  with four more instructions before the load -- so all three kept the buffer,
  which holds whatever subtune the *ripper* last inited. That is the header's
  `startSong`, and it shows: Action Biker (startSong 2) had our o0 = the
  original's s1 and its o2 duplicating it, Samantha Fox (startSong 10) was
  shifted by one across all fourteen with our o0 = the original's s9, and
  Spellbound (startSong 1) got the harmless case where the buffer happens to
  equal entry 0 and only its later subtunes shifted. The invariant is the copy
  loop the arithmetic feeds, not the arithmetic: `BD ?? ?? 99 ?? ?? E8 C8 C0
  06 D0 F4` names the same address as the old shape in all 38 files that
  carried both, and rescues exactly these three. **Anchor a signature on the
  instruction that names the address you want, never on the arithmetic in
  front of it** -- and when a load and a store in the same idiom both name a
  table, ask which one the *player* reads.
  Two things fell out of it. `--diagnose`'s correspondence matrix had been
  reporting the defect correctly for as long as it existed, while the report's
  rows were fine, because `--search-subtunes 3` (the default) was silently
  compensating: **a shim that hides a defect from the score does not hide it
  from the file**, and the shipped `.sng` played its subtunes in the wrong
  order the whole time. And Spellbound was the single file where the init
  dispatch (3) and `track_table_extent` (4) disagreed; reading the table one
  entry early is what gave the layout one row more of room. **A standing
  disagreement between two independent readings is a lead, not a tie to be
  broken by preference** -- they now agree on all eight files that carry both,
  and `tests/test_tracks.py` pins the count at 8.
- **To ask whether a constant matters, hash the output -- do not re-derive
  the quantity it is bounded by.** Two scripts asked whether
  `HARD_RESTART_FRAMES` changes anything by reconstructing each song's row:
  one parsed it out of a log line and swept up the "in N pattern(s)" count,
  the other took the header's subtune count where the converter uses the
  emitted one. They answered 0 files and 2 files; converting at each value
  and hashing answers 3, needs no row, and cannot drift. Same shape as the
  probe of § 7.ggggg: a re-derivation has to get every input right, and the
  tool already has them.
- **The option that removes a defect is not always the fix for it.**
  `--no-test-restart` deletes the testbit frame on every note's first frame,
  and that frame is the only one our conversions spend below `$10` -- which
  is what siddump requires to print a note at all (siddump.c:434-437). Forced
  corpus-wide it takes `hold` +69.9pp and `melody` **-26.3pp on 68 files**,
  Delta Mix-E-Load to 0%: four columns collapse because the instrument can no
  longer see our attacks, not because the music changed. The frame is
  standing in for the release the players make at the end of every untied
  note and we never made. What was wanted was the release --
  `HARD_RESTART_FRAMES`, Goattracker's own gate-off before a note, which was
  **2 calls** where every other rate here is `frames * multiplier` and is now
  2 frames. Five files gain 25-45 points of melody and none loses half a
  point on anything. See § 7.hhhhh.
- **A rate read out of the player is per *frame*; every table Goattracker
  applies it with steps per *play call*.** They agree only at `gt2reloc -S1`,
  and 33 of the 83 preset songs pack at `-S2`. Anything new that carries a
  rate — a slide step, a sweep, a table delay, a transient length — must be
  divided by `multiplier` at the point it is encoded, the way
  `build_speed_table`, `_drum_speed`, `_rise_speed_index`, `_wave_hold_byte`
  and the pulse programs now are -- and `_wave_program_entries` since
  v0.5.235, which until then simply *refused* every multispeed file rather
  than dividing, and **`_filter_entries` only since v0.5.363**. That one is
  the cautionary case for this whole bullet: the list above was *written down*
  and the filter emitter was simply never added to it, so the rule sat two
  paragraphs from an emitter that broke it for the life of the project. It was
  not even given a `multiplier` parameter to ignore -- the call site passed
  four arguments and the fifth did not exist. A listener reported ACE II's
  filter as "missing"; it was routed correctly (`filt` 2994/2997) and sweeping
  **three times too far**, 2304 a frame against the player's 768, which is
  exactly its `-S3`. `cut` had been reporting it all along, at 2.39x. **When a
  rule names the functions that obey it, that list is a checklist to re-run
  against the tree, not a record to append to** -- grep for what writes a rate
  byte, not for what already calls `multiplier`. Fixing it moved 9 files, zero
  of them `-S1`, and `cut` was the ONLY column that moved on any of them:
  Saboteur II 3.99x -> 1.48x, Thundercats 3.13x -> 1.13x, Food Feud
  2.96x -> 1.13x, ACE II 2.39x -> 0.79x. **A restriction is not a neutral default.** That one was
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
- **NEVER `git stash` in a fan-out. A worktree is not a whole repo, and
  `refs/stash` is one of the refs it does not get its own copy of.** Two agents
  stashed concurrently to snapshot their work before an A/B; one `git stash
  pop` returned a *sibling's* diff — a 47-line `goatwriter.py` change that
  belonged to another task entirely — and afterwards `git stash list` was
  empty while `git fsck --unreachable` showed **100+ dangling stash-shaped
  commits** in the object store. So this has been happening unnoticed across
  earlier sessions, not just once. Both agents concluded the other's work had
  been destroyed and opened recovery tasks; **neither was right** — the
  surviving worktree held a superset and the only lines that differed were
  docstring prose. That is the part worth fearing: the failure is silent, the
  diagnosis from inside one worktree is *wrong in both directions*, and the
  recovery was luck. Snapshot with `git diff > x.patch` and `git apply -R`, or
  copy the file, or use a scratch branch. The same caution applies to anything
  else stored per-repo rather than per-worktree — `refs/stash`, the object
  store, `.git/config`, and the index of any worktree you did not create.
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
  `presets.py --fidelity` (it writes `presets.json`), or commits. Cost scales
  with the toggle count: **8 minutes** at five toggles, 15 at six, and about a
  minute a song at seven (127 combinations), which is 80 serially.
  **`--shard I/N` splits it across processes** and `--merge` recombines them —
  each song's walk is independent of every other's, and `fidelity.py` has had
  a private scratch directory per run since v0.5.66 precisely so concurrent
  runs cannot read each other's intermediates. Six shards take the
  seven-toggle search from 80 minutes to about 15. This paragraph used to say
  "there is no reason to run them in parallel", which was true of two whole
  searches contending and wrong about shards; the equivalence is checked
  rather than assumed (three structural shards merged reproduce the unsharded
  run's `songs` dict exactly).
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

- **A staleness skip keyed on the version fires on every commit, because the
  version changes on every commit.** That guard skipped unless
  `presets.json`'s `generator` stamp contained the running `__version__`. The
  skip is *right* — the artefact is regenerated after a conversion-changing
  commit, not during one, so between the two it legitimately lacks the option
  it should carry, and asserting against it would fail for the one reason the
  test is not about. But `bump_version.py` rewrites `__init__.py` and
  `CHANGELOG.md` and **never touches `presets.json`**, so the stamp fell
  behind on the next commit whatever that commit did. The guard was therefore
  live only in the commit that regenerated the artefact — and not even then,
  because `bump_version.py` runs *after* `presets.py`, so that commit ships a
  stamp one version behind. That is the likeliest reading of this file's own
  note that the guard once stayed off for ten versions, and at v0.5.337 it was
  watched happening again inside a single commit.
  The version was only ever a **proxy** for "could the option set have changed
  since this file was written". Ask that directly: `_always()` now skips only
  when an option is genuinely unaccounted for in the artefact **and** the
  stamp predates the running version. Every current option accounted for → the
  test runs whatever version stamped the file; an option missing while the
  versions match → it fails, which is the defect it exists to catch. All three
  branches are exercised in `tests/test_preset_passthrough.py`.
  The general rule: **a skip condition must be keyed on the thing that would
  make the assertion lie, never on a proxy that moves more often.** A guard
  that goes dark on a schedule nobody chose is worse than no guard, because
  the suite still reports green.

**`presets.py --fidelity` searches at `-t 60` since v0.5.235, and the ten
seconds before it were choosing settings blind.** v0.5.195 moved the *report*
to 60 s because a fifth of the corpus contributed nothing to some columns at
10 s; the search kept its own default for forty versions. Sanxion's 10 s window
holds one comparable instrument and zero noise frames against eight and 1669 at
60 s — two of `fidelity_better`'s terms are noise terms and a third is `onset`,
so the criterion was not disagreeing, it was blind, and five files lost a
`two_stage` that a 60 s A/B scores at onset 40-83% -> 100% with melody unmoved.
A corpus search at 60 s is **8 minutes** — timed twice at v0.5.300, 8m11s and
~8m, both over 83 songs with zero failures. The figures this paragraph carried
for forty versions ("about four hours rather than forty minutes") were never
timed and were wrong by a factor of about thirty; the 10 s cost has still not
been measured, so no ratio is claimed here. **A cost written down but never
timed is a planning input, and this one refused a feature** — see
`presets.py`'s sixth-toggle note. When a window is found to be too short, the
finding is about the window: grep for every other place the same one is
chosen — and when a cost is quoted as a reason, time it before it decides
anything.

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

## graphify

This project has a knowledge graph at graphify-out/ with god nodes, community structure, and cross-file relationships.

Rules:
- For codebase questions, first run `graphify query "<question>"` when graphify-out/graph.json exists. Use `graphify path "<A>" "<B>"` for relationships and `graphify explain "<concept>"` for focused concepts. These return a scoped subgraph, usually much smaller than GRAPH_REPORT.md or raw grep output.
- If graphify-out/wiki/index.md exists, use it for broad navigation instead of raw source browsing.
- Read graphify-out/GRAPH_REPORT.md only for broad architecture review or when query/path/explain do not surface enough context.
- After modifying code, run `graphify update .` to keep the graph current (AST-only, no API cost).
- **`graphify update` is the orchestrator's job, not a delegated agent's.** A
  fan-out task's declared `touches` list is what makes concurrent agents safe
  to run at once (rule 1 in every dispatched task), and `graphify-out/` is
  essentially never in it — so an agent that ran `graphify update .` anyway
  would be writing an undeclared path, exactly the failure mode `touches`
  exists to prevent. One agent in this repo hit that and correctly refused to
  update the graph rather than grant itself the path. Nothing else ran it
  either, and the graph rotted silently across the whole fan-out: found once
  15.5 hours stale with six modified files unreflected in it. The fix is not
  to make the rule looser for agents — it is to put the refresh where the
  contention control already lives: whoever owns the cycle (the orchestrator
  or the main session, after the fan-out's writes have landed) runs
  `graphify update .` once, the same way `SURVEY.md`/`presets.json`/
  `FIDELITY.md` are regenerated once on `master` after merges rather than by
  each branch.
