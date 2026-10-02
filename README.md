# H2G — Hubbard 2 Goattracker

> This repository is the home of H2G. Its history up to v0.5.104 was extracted
> from the `hubbard/` directory of
> [SIDDetector2](https://github.com/MichaelTroelsen/SIDDetector2), where the
> copy is now a tombstone — do not edit it.
>
> The 95-tune Hubbard corpus the tests and reports are built against is **not**
> in this repository; it is an HVSC-derived collection that lives elsewhere.
> Point `H2G_CORPUS` at it. Without it the suite still runs and passes — the
> corpus sweeps skip.

Converts Commodore 64 `.sid` files containing music by **Rob Hubbard** into
Bitops **Goattracker** (`.sng`, v2.34+) format.

Originally a VB6 desktop tool by Stilianos "Stello" Doussis (Aug 2005), released
as free/open source. This repository keeps that original as reference and adds a
from-scratch Python CLI port, which is where development happens.

It is a **static signature ripper**: it never emulates the 6502. It scans the raw
SID bytes for known player-engine opcode fingerprints, reads the data-table
addresses straight out of the matched instructions' operands, and re-encodes the
instrument/pattern/orderlist data into Goattracker's binary song format. That
means it only works on tunes whose player matches one of 17 hard-coded game
fingerprints — see [`H2G-CONVERSION-METHOD.md`](docs/H2G-CONVERSION-METHOD.md) for the
full method write-up.

Everything except this file, `CLAUDE.md` and `whats-next.md` lives in
[`docs/`](docs/inventory.md) — the inventory there says what each document is,
which ones are **generated** (and by which command, so a hand edit is not lost
to the next run), and which are plans or audits dated to a version and to be
checked before they are believed.

## Usage

From `python/`:

```sh
python -m h2g <input.sid> [-o output.sng] [-q] [--max-rows N] [--terminate-patterns]
                          [--format {gts2,gts5}] [--tempo N|auto]
                          [--dedup-patterns] [--prune-patterns] [--pack-repeats]
                          [--legal-restart] [--presets presets.json]
python -m h2g --version
```

`--presets FILE` applies the entry for this `.sid` (plus the file's `always` block): every option
`fidelity._preset_opts` forwards to `convert()`, not only `--max-rows` and the pattern switches.
Explicit command-line flags still win; see [Per-song presets](docs/OPTIONS.md#per-song-presets--presetsjson).

Or from the repository root (PowerShell wrapper — resolves paths, then delegates):

```powershell
.\convert.ps1 <input.sid> [-OutputFile out.sng] [-Quiet] [-MaxRows N] [-TerminatePatterns]
```

Plain-stdlib Python 3; no third-party runtime dependencies (`pytest` is dev-only).

### Playing a song — `play.ps1`

Converts (if given a `.sid`) and opens the result in GoatTracker:

```powershell
.\play.ps1 Commando.sid                                  # convert + launch
.\play.ps1 arkiv\Crazy_Comets.sid -MaxRows 128           # pass converter options through
.\play.ps1 build\Commando.sng                            # already converted
.\play.ps1 Commando.sid -NoLaunch                        # convert + stage only
```

The song is loaded at startup but does **not** auto-play — press **F1** in the
window to play from the beginning (F2 from the current position).

Defaults to `-Format gts5`, since the whole point of opening a file here is that
GoatTracker's legacy GTS2 importer is buggy (see [`--format`](docs/OPTIONS.md#--format-gts2--gts5)).
Pass `-Format gts2` if you specifically want the original tool's output.

Converted files go to `build/` (gitignored) — never next to the input, because
`Commando.sng` at the repo root is the regression fixture.

GoatTracker is located via `-GoatTracker <path>`, else `$env:H2G_GOATTRACKER`,
else a default install path. An explicit override that doesn't resolve is a hard
error rather than a silent fallback.

### Options

Each option's behaviour, and the measurement behind it, is in
[`docs/OPTIONS.md`](docs/OPTIONS.md):

- [`--max-rows` (pattern slicing)](docs/OPTIONS.md#--max-rows-pattern-slicing)
- [`--terminate-patterns` (explicit pattern end markers)](docs/OPTIONS.md#--terminate-patterns-explicit-pattern-end-markers)
- [`--format` (gts2 / gts5)](docs/OPTIONS.md#--format-gts2--gts5)
- [`--tempo` (playback speed)](docs/OPTIONS.md#--tempo-playback-speed)
- [`--prune-patterns` and `--dedup-patterns` (size)](docs/OPTIONS.md#--prune-patterns-and---dedup-patterns-size)
- [`--pack-repeats` (coverage)](docs/OPTIONS.md#--pack-repeats-coverage)
- [Fitting Goattracker's orderlist limit](docs/OPTIONS.md#fitting-goattrackers-orderlist-limit)
- [`--legal-restart` (packing back to `.sid`)](docs/OPTIONS.md#--legal-restart-packing-back-to-sid)
- [`--slides` (pitch bends)](docs/OPTIONS.md#--slides-pitch-bends)
- [`--effects` (the instrument effect byte)](docs/OPTIONS.md#--effects-the-instrument-effect-byte)
- [`--compact-instruments` (the wasted instrument slot)](docs/OPTIONS.md#--compact-instruments-the-wasted-instrument-slot)
- [`--rest-instrument` (the instrument change that clicked)](docs/OPTIONS.md#--rest-instrument-the-instrument-change-that-clicked)
- [`--status-bit6` (the skipped operand and note)](docs/OPTIONS.md#--status-bit6-the-skipped-operand-and-note)
- [`--reject-phantoms` (pattern-table validation)](docs/OPTIONS.md#--reject-phantoms-pattern-table-validation)
- [`--skip-gate` (the row length the gate alone under-reads)](docs/OPTIONS.md#--skip-gate-the-row-length-the-gate-alone-under-reads)
- [`--fold-transpose` (transposes past Goattracker's ceiling)](docs/OPTIONS.md#--fold-transpose-transposes-past-goattrackers-ceiling)
- [`--initial-instrument` (the instrument a voice starts on)](docs/OPTIONS.md#--initial-instrument-the-instrument-a-voice-starts-on)
- [A note before its voice's first instrument (no flag; per player)](docs/OPTIONS.md#a-note-before-its-voices-first-instrument-no-flag-per-player)
- [`--engine N` (a file that carries two players)](docs/OPTIONS.md#--engine-n-a-file-that-carries-two-players)
- [`--filter` (the filter, which was never emitted at all)](docs/OPTIONS.md#--filter-the-filter-which-was-never-emitted-at-all)
- [`--vibrato` (the pitch movement that never happened)](docs/OPTIONS.md#--vibrato-the-pitch-movement-that-never-happened)
- [`--tie` (the note that should not be struck)](docs/OPTIONS.md#--tie-the-note-that-should-not-be-struck)
- [`--cut-release` (the release nibble that never sounds)](docs/OPTIONS.md#--cut-release-the-release-nibble-that-never-sounds)
- [`--vibrato-command` (the length gate, expressed exactly)](docs/OPTIONS.md#--vibrato-command-the-length-gate-expressed-exactly)
- [`--pulse` (the duty cycle that never moved)](docs/OPTIONS.md#--pulse-the-duty-cycle-that-never-moved)
- [`--wave-program` (the player's byte-code wave program)](docs/OPTIONS.md#--wave-program-the-players-byte-code-wave-program)
- [`--sfx-drum` (the drum that was filed as a game sound effect)](docs/OPTIONS.md#--sfx-drum-the-drum-that-was-filed-as-a-game-sound-effect)
- [`--two-stage` (the attack waveform, and the drums that were missing)](docs/OPTIONS.md#--two-stage-the-attack-waveform-and-the-drums-that-were-missing)
- [`--voice-two-stage` (the same attack, with per-voice parameters)](docs/OPTIONS.md#--voice-two-stage-the-same-attack-with-per-voice-parameters)
- [`--rest-keyoff` (the rest that silences)](docs/OPTIONS.md#--rest-keyoff-the-rest-that-silences)
- [`--no-test-restart` (the silent frame on every note)](docs/OPTIONS.md#--no-test-restart-the-silent-frame-on-every-note)
- [`--rest-wave-silence` (the rest that parks a waveform)](docs/OPTIONS.md#--rest-wave-silence-the-rest-that-parks-a-waveform)
- [`--rest-envelope-silence` (the rest that zeroes the envelope)](docs/OPTIONS.md#--rest-envelope-silence-the-rest-that-zeroes-the-envelope)
- [One subtune's tempo reaching another's clock (fixed v0.5.330)](docs/OPTIONS.md#one-subtunes-tempo-reaching-anothers-clock-fixed-v05330)
- [`--wide-hard-restart` (two thirds of the row, not half)](docs/OPTIONS.md#--wide-hard-restart-two-thirds-of-the-row-not-half)
- [`--max-hard-restart` (the player's own limit)](docs/OPTIONS.md#--max-hard-restart-the-players-own-limit)
- [`--sustain-exact` (the sustain nibble as the SID reads it)](docs/OPTIONS.md#--sustain-exact-the-sustain-nibble-as-the-sid-reads-it)
- [`--no-hard-restart` (stop resetting the envelope before every note)](docs/OPTIONS.md#--no-hard-restart-stop-resetting-the-envelope-before-every-note)
- [`--regrid` (a row that is not a whole number of play calls)](docs/OPTIONS.md#--regrid-a-row-that-is-not-a-whole-number-of-play-calls)
- [Per-song presets — `presets.json`](docs/OPTIONS.md#per-song-presets--presetsjson)

## Versioning

**Bump the version on every commit**, not just on releases.

The single source of truth is `__version__` in `python/h2g/__init__.py`, exposed
as `h2g --version`. There is deliberately **no** `.version` file, so nothing can
drift out of sync.

Before each commit:

```sh
python python/bump_version.py "short description"     # bumps the patch
python python/bump_version.py --minor "description"   # feature release
```

That rewrites `__version__` and prepends a [`CHANGELOG.md`](docs/CHANGELOG.md) entry.
Never hand-edit the version in more than one place. If a document embeds the
version string (`SURVEY.md` records the converter version in its header),
regenerate it after bumping so the committed docs match the committed version.

## Testing

```sh
cd python && python -m pytest tests/ -q
```

**The 95-tune Hubbard corpus is not in this repository.** It is an
HVSC-derived collection belonging elsewhere, so the tests point at it rather
than vendor it: set `H2G_CORPUS` to the directory holding the `.sid` files.
Without it the fourteen test files that sweep the corpus **skip** and the rest
still run — 579 pass, 32 skip on a corpus-less checkout — so a fresh clone is
green. Before v0.5.104 each of those files spelled out one machine's absolute
path and five of them had no existence check at all, which made a clone
without the corpus fail rather than skip.

`tests/corpus.py` is the single definition. A new corpus-dependent test wants
`from corpus import CORPUS, needs_corpus` and the `@needs_corpus` marker — not
a bare `if not CORPUS.is_dir(): return`, which passes a test that never ran.

The suite runs the real CLI as a subprocess, in three layers of increasing
strength:

- **Byte-exact** — `test_commando.py` asserts `Commando.sid` converts
  byte-for-byte identically to `Commando.sng` (produced by the original
  `h2g.v1.2.exe`).
- **Structural** — `test_max_rows.py` and `test_format.py` parse the emitted
  `.sng` the way Goattracker's own loader walks it, checking pattern rows,
  pattern count and orderlist lengths against the format's limits.
- **Against Goattracker itself** — `test_goattracker_loads.py` feeds the output
  through GoatTracker's real `loadsong()` via `sngspli2`, and skips when that
  tool is absent (`H2G_SNGSPLI2` overrides its location).

Note what none of them prove: that a song *plays* correctly. A file can be
byte-exact and structurally valid and still crash Goattracker on play (see
[`--format`](docs/OPTIONS.md#--format-gts2--gts5)) or run at the wrong tempo. Use
[`play.ps1`](#playing-a-song--playps1) to hear one, and
[`fidelity.py`](docs/MEASURING.md#fidelity--does-it-play-like-the-original) to measure the
corpus.

Treat any output-changing edit as a regression unless it is an intentional
feature — in which case extend the fixtures rather than deleting the assertion.

## Survey, fidelity and listening

How a conversion is measured against its original — the corpus survey,
`fidelity.py`, the censuses, A/B runs, listening and the song view — is in
[`docs/MEASURING.md`](docs/MEASURING.md):

- [Corpus survey](docs/MEASURING.md#corpus-survey)
  - [The subtune census](docs/MEASURING.md#the-subtune-census)
- [Fidelity — does it play like the original?](docs/MEASURING.md#fidelity--does-it-play-like-the-original)
  - [The window is a prefix, and that limits what a single run can settle](docs/MEASURING.md#the-window-is-a-prefix-and-that-limits-what-a-single-run-can-settle)
  - [Diagnosing one file](docs/MEASURING.md#diagnosing-one-file)
  - [Timing one file — `--pace`](docs/MEASURING.md#timing-one-file----pace)
  - [What a run says it compared](docs/MEASURING.md#what-a-run-says-it-compared)
  - [`--vice` (the register dimensions at 312 samples a frame)](docs/MEASURING.md#--vice-the-register-dimensions-at-312-samples-a-frame)
  - [The onset census — `--census`](docs/MEASURING.md#the-onset-census----census)
  - [The hold census — `--hold-census`](docs/MEASURING.md#the-hold-census----hold-census)
  - [The gate census — `--gate-census`](docs/MEASURING.md#the-gate-census----gate-census)
  - [A/B against a previous run](docs/MEASURING.md#ab-against-a-previous-run)
  - [Listening](docs/MEASURING.md#listening)
  - [The instrument map — `instrmap.py`](docs/MEASURING.md#the-instrument-map--instrmappy)
  - [The song view — `songview.py`](docs/MEASURING.md#the-song-view--songviewpy)
  - [The queue — `fidelity_queue.py`](docs/MEASURING.md#the-queue--fidelity_queuepy)

## Repository layout

| Path | |
|---|---|
| `python/h2g/` | the Python port — active development target |
| `python/tests/` | regression tests |
| `python/survey.py`, `python/presets.py`, `python/bump_version.py` | tooling |
| `python/fidelity.py` | measures a conversion against the .sid it came from |
| `python/listen.py` | stages WAV pairs and a guide for a listening pass |
| `python/abpage.py` | builds gapless A/B pages from what `listen.py` staged |
| `convert.ps1`, `play.ps1` | PowerShell wrappers: convert, and convert + open in GoatTracker |
| `build/` | converted output (gitignored); never written next to an input |
| `VB6 Sourcecode/h2g.frm` | the original VB6 tool; still the ground truth for behaviour |
| `arkiv/` | archived VB6 build and sample `.sid` files |
| `Commando.sid` / `Commando.sng` | byte-exact regression fixture pair |
| `docs/H2G-CONVERSION-METHOD.md` | detailed explanation of how the conversion works |
| `docs/OPTIONS.md`, `docs/MEASURING.md` | every converter option in full; the survey, fidelity and listening tools |
| `CHANGELOG.md`, `SURVEY.md`, `FIDELITY.md` | version history, corpus results, playback fidelity |

## Links

- **[Hubbard2Goattracker V1.2 on CSDb](https://csdb.dk/release/?id=33670)** —
  the original release this repository is built on, dated **5 May 2006** and
  credited entirely to Stello Doussis (code, graphics, design, idea). Listed as
  an "Other Platform C64 Tool"; the download is `h2g.v1.2.zip`, the same
  version as the archived build in [`arkiv/`](arkiv/).

  A 2006 comment on that page by *arch0N* is worth knowing about: it lists
  tunes **not** written by Rob Hubbard that the converter nonetheless handles —
  Thomas E. Petersen (Laxity) and Jeroen Kimmel (Red) among them. This tool
  fingerprints *player engines*, not composers, so any tune built on a
  recognised engine converts regardless of who wrote the music. The corpus here
  is Hubbard-only, so that reach is untested — see
  [`SURVEY.md`](docs/SURVEY.md) § Out of scope for the inverse case, Hubbard tunes
  whose player is somebody else's.

## Licence

The original tool was released as free/open source — "can be modified and
republished ... used freely by others without notice".
