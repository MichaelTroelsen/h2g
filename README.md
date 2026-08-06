# H2G — Hubbard 2 Goattracker

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
fingerprints — see [`H2G-CONVERSION-METHOD.md`](H2G-CONVERSION-METHOD.md) for the
full method write-up.

## Usage

From `python/`:

```sh
python -m h2g <input.sid> [-o output.sng] [-q] [--max-rows N] [--terminate-patterns]
                          [--format {gts2,gts5}] [--tempo N|auto]
                          [--dedup-patterns] [--prune-patterns] [--pack-repeats]
                          [--legal-restart]
python -m h2g --version
```

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
GoatTracker's legacy GTS2 importer is buggy (see [`--format`](#--format-gts2--gts5)).
Pass `-Format gts2` if you specifically want the original tool's output.

Converted files go to `build/` (gitignored) — never next to the input, because
`Commando.sng` at the repo root is the regression fixture.

GoatTracker is located via `-GoatTracker <path>`, else `$env:H2G_GOATTRACKER`,
else a default install path. An explicit override that doesn't resolve is a hard
error rather than a silent fallback.

### `--max-rows` (pattern slicing)

Goattracker caps patterns at `MAX_PATTROWS`, raised to **128** in GoatTracker
v2.32 (verified in its `src/gcommon.h` and `readme.txt`). The 2005 tool predates
that change and slices at **94**.

94 remains the default because it is what the byte-exact `Commando.sng` fixture
encodes — that fixture is the project's only fidelity anchor, so **the default
must not change**.

Pass `--max-rows 128` for fewer, longer patterns and therefore shorter
orderlists, which brings some tunes back under Goattracker's capacity limits. It
changes pattern granularity only — no subtune is dropped and no file that
converts at 94 fails at 128.

For the current measured effect, generate both reports and compare their
headline counts (see [Corpus survey](#corpus-survey) below):

```sh
cd python
python survey.py <sid_dir> -o ../SURVEY.md                       # default, 94 rows
python survey.py <sid_dir> -o survey-128.md --max-rows 128       # scratch, not committed
```

### `--terminate-patterns` (explicit pattern end markers)

Goattracker does not trust a pattern's stored length. On load it rescans the
note column for `ENDPATT` and recomputes the length (`countpatternlengths()` in
`gsong.c`), and its own saver always writes `pattlen+1` rows — the data plus one
`ENDPATT` row.

H2G omits that terminator on every pattern slice but the last, so a sliced
pattern's length is whatever the loader's pre-fill left behind. `clearpattern()`
fills rows from `defaultpatternlength` (64 out of the box) onward with `ENDPATT`,
so slicing at 94 happens to work — 94 > 64. Run Goattracker with a default
pattern length above the slice length and every sliced pattern silently gains
trailing empty rows.

`--terminate-patterns` appends an explicit `ENDPATT` row to any slice lacking
one, making the output self-describing and matching what Goattracker itself
writes. It is opt-in because it changes the output bytes, and the byte-exact
`Commando.sng` fixture encodes the original tool's unterminated output. It costs
one row per slice and does not affect how many tunes convert.

### `--format` (gts2 / gts5)

GoatTracker 2.77 loads both, but its **legacy GTS2 import path contains a
buffer overrun** that the modern path does not. In `src/gsong.c:306`:

```c
length = fread8(handle) * 4;        // length is now BYTES (rows * 4)
for (d = 0; d < length; d++)        // but d indexes ROWS
    switch (pattern[c][d*4+2]) { case CMD_PORTAUP: ... }
```

For a 94-row pattern it walks to `pattern[c][1503]` in a row of
`MAX_PATTROWS*4+4` = 516 bytes, writing into following patterns wherever it
finds command `$1`/`$2`/`$3`/`$4`/`$0E` — exactly the portamento commands this
converter emits. The GTS3/4/5 loader has no such conversion loop.

`gts2` stays the default because it is what the byte-exact `Commando.sng`
fixture encodes. **Use `--format gts5` for anything you intend to open in
GoatTracker.** The two outputs differ only by the magic bytes and one extra
byte: an empty fourth (speed) table, which GTS2 has no slot for.

### `--tempo` (playback speed)

This converter emits **one pattern row per Hubbard player tick**, so a row must
last one tick. Goattracker makes a row last `tempo+1` play-routine calls and
defaults to **6**, so an untempo'd conversion plays 6× too slow.

Raising Goattracker's speed multiplier alone does not fix it: the default tempo
is computed as `6*multiplier-1` (`gplay.c:212`), which cancels out exactly. The
only lever stored *in the file* is the last instrument's Attack/Decay
(`gplay.c:221`), and that one does **not** scale:

```c
if ((instr[MAX_INSTR-1].ad >= 2) && (!(instr[MAX_INSTR-1].ptr[WTBL])))
    cptr->tempo = instr[MAX_INSTR-1].ad - 1;
```

So `instr[63].ad = A` means A calls per row, i.e. `A/multiplier` frames per row.
Goattracker treats `A < 2` as funktempo, so the fastest expressible row is 2
calls — **one frame per row therefore requires speed multiplier 2**. That is
exactly the "2×" a converted tune needs.

```sh
python -m h2g song.sid --tempo auto     # derive from the PSID speed field
python -m h2g song.sid --tempo 6        # explicit calls-per-row
```

Writing a tempo pads the instrument list out to 63 entries (the padding is
inert — no table pointers, ~1.2 KB), so it is **off by default** to keep the
byte-exact `Commando.sng` fixture intact. `play.ps1` passes `-Tempo auto`
by default, since that path exists to actually play the file.

**On the PSID speed field:** it is a per-subtune bitmap saying only *whether* a
subtune is CIA-timed rather than VBI-driven — never at what rate. It therefore
cannot yield a multispeed factor, and 90 of the 95 corpus files have it set to
zero. It is parsed and reported (`SidFile.speed`, `is_cia_timed()`), but the
tempo is one tick per row either way.

### `--prune-patterns` and `--dedup-patterns` (size)

The pattern table's size is inferred from the gap between the SID's pattern
LO and HI address tables, so it counts every entry the table has room for —
not every entry the song plays. `--prune-patterns` drops the ones no track's
orderlist references. Across the 95-file corpus it removes **11%** of total
output, and individual tunes far more:

| File | plain | pruned | |
|---|---:|---:|---:|
| `BMX_Kidz` | 30998 | 4059 | −86% |
| `Kings_of_the_Beach_ingame` | 35733 | 9434 | −73% |
| `Ricochet` | 46266 | 12668 | −72% |
| `Skate_or_Die_intro` | 14015 | 4850 | −65% |

It is also a **diagnostic**. `ACE_II.sid` drops from 15596 bytes to 626: its
three orderlists are 2 bytes each and reference *no* valid pattern, so the 38
patterns it emitted were all unreachable. That conversion was already empty —
pruning only stops it looking like 15 KB of music.

Alone among the output-shaping options it **cannot change playback** — a
pattern no orderlist names is unreachable — but it renumbers the survivors, so
it stays off by default like the rest. Because the skipped patterns are never
decoded, it also counts against Goattracker's 208-pattern limit: it converts
`Dragons_Lair_Part_II`, which otherwise aborts.

`--dedup-patterns` is the complementary saving: byte-identical slices share one
Goattracker pattern. It shrinks 43 of 62 convertible files by up to 37%. It
cannot shorten orderlists (sharing renumbers entries, it never removes them),
so unlike pruning it rescues capacity failures only via the pattern limit.

Both compose with each other and with `--max-rows` / `--format`.

### `--pack-repeats` (coverage)

Goattracker's orderlist can say "play the next pattern n+1 times" in two bytes
(`$D0`–`$DF`, `gplay.c:983`), so a run of L identical consecutive patterns
costs `ceil(L/16)*2` instead of L. Hubbard orderlists are full of such runs —
a drum bar held under a melody — and pattern slicing multiplies them, since
every slice of a repeated pattern repeats too.

This is the **only** option that shortens an *orderlist* rather than the
pattern data, and therefore the only one that can rescue a tune from
Goattracker's 254-byte orderlist limit. Measured over the 95-file corpus:

| Options | Converted |
|---|---:|
| defaults | 60 |
| `--pack-repeats` | **63** |
| `--max-rows 128 --prune-patterns --dedup-patterns` | 62 |
| `--max-rows 128 --pack-repeats` | **67** |

It saves little space on its own (0.5% overall — an orderlist is a small part
of a `.sng`); its value is coverage.

The one hazard is that a repeat command is *positional*: Goattracker parses an
orderlist step as `[transpose][repeat][pattern]`, so a repeat emitted directly
after another repeat would be read as that step's pattern number. Version
0/1/3 orderlists can carry Hubbard pattern numbers in `$D0`–`$FD` that pass
through as commands, so this case is real and is handled — see
`test_pack_repeats.py`, which reconstructs what every orderlist plays and
asserts packing does not change it.

### Fitting Goattracker's orderlist limit

An orderlist may be 254 bytes. Three corpus subtunes exceed it — Gremlins 23,
Knucklebusters 0, Monty on the Run 11 — and each used to abort its whole file,
discarding every other subtune with it.

Two mechanisms now keep them:

- an over-long subtune is **dropped on its own**, so the rest of the tune
  converts (it is dropped rather than truncated: cutting one voice short while
  its neighbours play on makes it loop early and drift, which sounds wrong
  rather than absent);
- before that, the orderlist is **compacted by merging** consecutive patterns
  whose rows fit one pattern, which trades a pattern-table slot for an
  orderlist byte.

With `--max-rows 128 --pack-repeats`, merging rescues all three: **no subtune
is dropped anywhere in the corpus.** Knucklebusters' first voice comes down
from 263 bytes to 211.

Merging is attempted **only** for a track that would otherwise cost its
subtune, so nothing that already fits is rewritten and `Commando.sng` cannot
move. It is costed against the packed result rather than applied before it:
identical neighbours are never merged, because a run of one repeated pattern
is `--pack-repeats`' job and it does that in two bytes however long the run
is. Knucklebusters' middle voice is exactly that case — 261 bytes packing to
56 — and merging its pairs first would have made them distinct and cost ~224.

### `--legal-restart` (packing back to `.sid`)

Hubbard's `$FE` track byte means *this tune has ended*. Every dialect
implements it the same way — it calls the player's jump-table entry +3, which
is `LDA #$C0` / `STA flag` / `RTS`, and the `BIT flag` / `BMI` at the top of
the play routine then stops fetching notes (Warhawk `$109F`, Last V8 `$809B`,
Saboteur II `$F0A2`).

Goattracker's orderlist has no "stop". The original VB6 tool worked around
that by writing `$FF $FD` — a song-loop whose restart position is out of
range, which makes `gplay.c:969` call `stopsong()`. That is exactly right in
the editor and fatal outside it: `greloc.c:244` **refuses to export** a song
whose restart position is `>= songlen`, and `gt2reloc` reports the refusal to
a console that does not exist headless, so you get exit 0, no message and no
file.

`--legal-restart` rewrites that position to 0. Measured over the corpus with
each song's presets:

| | `.sid` written by `gt2reloc` |
|---|---:|
| without | 50 of 78 |
| with `--legal-restart` | **78 of 78** |

The cost is real: the tune loops from the top instead of ending, so a one-shot
jingle becomes a round. That is why it is opt-in — but without it those 28
tunes cannot be packed at all, which is what blocks the `.sng` → `.sid`
fidelity comparison for them.

Restart position 0 is the only value that can be chosen without knowing the
finished orderlist, since slicing, packing, merging and splitting all change
its length after the track data is built. The rewrite therefore runs last, on
the completed orderlists.

It also repairs a second, quieter case: a voice whose orderlist is nothing but
a marker (`[$FF, $00]`, `songlen` 0) has no legal restart position either.
`greloc.c:201` does not reject those — it **skips the whole subtune**, and
`greloc.c:653` writes the accepted ones consecutively, so the subtune numbers
in the packed `.sid` no longer match the `.sng` it came from. A `siddump`
comparison then quietly measures the wrong tune. Such voices get the same
placeholder orderlist every other unrepresentable subtune gets.

### `--slides` (pitch bends)

Hubbard's pitch-bend command carries a **16-bit** step split across two pattern
bytes. This converter only ever read the first. The second was then decoded as
the note, and every byte after it in that pattern was read one position out —
so a bend did not merely come out at the wrong depth, it desynchronised the
rest of the pattern.

The players do not all agree, so this is gated on detection rather than on the
dialect number: 41 of the 95 corpus files have the second fetch
(`detect.SLIDE_OPERAND_SHAPE`, matched against the player's own
`INY / LDA (patt),Y / STA slidehi,X`), none has a one-byte variant of the same
shape, and for the other 54 the flag does nothing at all. `Commando` is one of
the 54, which is why the original tool never needed it and why the byte-exact
fixture does not move.

Measured over the corpus with each song's presets, 10 s per file:

| | mean melody |
|---|---:|
| without | 67.0% |
| with `--slides` | **67.6%** |

Three files improve — `Flash_Gordon` 8% → **52%**, `Arcade_Classics` 92% →
100%, `International_Karate` 86% → 87% — and one, `ACE_II`, drops 3 points.
Off by default because it changes the output bytes of the 41 files it reaches.

**The related fix is not optional and has no flag.** A portamento's data byte
is a packed value in a GTS2 file but a *1-based index into the speed table* in
GTS3+ (`gplay.c:740`), and this writer emitted an empty speed table — so every
bend it wrote was silently inert in the `gts5` output the presets use. Writing
the table took the corpus from **7** slide frames to **1214** against the
originals' 22876. It changes no melody score, because an attack-based
comparison cannot see pitch movement at all; `FIDELITY.md` now carries a
**slides** column so that class of change is measurable.

The remaining gap is not in the pattern data. Most of what the originals bend
comes from per-instrument effects — the `+7` effect byte, and a pulse-width
sweep in `+6` that is *not* vibrato (see `H2G-CONVERSION-METHOD.md` §7).

### `--effects` (the instrument effect byte)

Instrument byte `+7` has always been read as an "arp style" bit-field — bit
`$01` a drum, bit `$04` an arpeggio whose interval is the high nibble — and a
five-entry wavetable fabricated from it for **every** converted file.

**That reading is one player's.** Warhawk tests the byte with `AND #$08` /
`#$01` / `#$02` / `#$04` and `LSR`×4. Mega Apocalypse tests the whole byte with
`LDA` / `BEQ`. W.A.R. Preview does `LDA` / `BEQ` then `CLC` / `ADC`. One Man and
his Droid does `AND #$E0`. Chicken Song does have an `AND #$02` on it, but its
block `ORA #$80`s into the waveform register — a noise swap, not a pitch
change. Five players, five meanings.

So `--effects` decodes two bits **only where the routine that reads them is
present**, found by resolving the address the instrument-load routine stores
`+7` to and requiring the test block to name that address. 4 of the 83
convertible files have the chromatic-rise routine; 13 have the arpeggio one.
For every other file the flag does nothing.

- **Bit `$02`, the chromatic rise** — the note climbs a semitone every four
  frames while it is held. Written as a looping note-relative portamento in the
  wavetable, which needs `--format gts5`; a GTS2 file stores no speed table.
  Continuous glide rather than four-frame steps: the rate is exact, the
  stepping is not.
- **Bit `$04` with a zero interval nibble is silent** in the player, because
  the nibble is written into the operand of an `SBC`. The original substitutes
  a `+12` relative note, inventing an octave-up arpeggio — for **315 of the
  corpus's 660** arpeggio instrument records, including all six of Commando's.

An earlier version applied Warhawk's reading corpus-wide and was caught by
measurement: it put 287 frames of pitch movement into `W.A.R. Preview` and 256
into `Mega Apocalypse`, whose originals have **none**. Gated, the flag changes
no melody score and no corpus slide total in a 10 s window — only `Thrust`
exercises it at all within 60 s (0 → 76 slide frames against the original's
536). It is shipped narrow and verified rather than broad and plausible.

Off by default: it changes the output bytes of the files it reaches, the
fixture among them.

### Per-song presets — `presets.json`

No single setting is right for the whole corpus: `--max-rows 128` fits tunes
that 94 cannot, `--pack-repeats` rescues others from the orderlist limit, and
`--prune-patterns` / `--dedup-patterns` only ever shrink. `python/presets.py`
searches the combinations per song and records the winner:

```sh
cd python
python presets.py <sid_dir> -o ../presets.json     # search
python -m h2g song.sid --presets ../presets.json   # apply
```

```powershell
.\convert.ps1 song.sid -Presets presets.json
.\play.ps1    song.sid -Presets presets.json
```

"Best" is, in order: **most subtunes that actually play**, then **most rows
actually played**, then **smallest file**. The second is measured by walking
the orderlists rather than counting stored rows — counting storage would
punish pruning for removing patterns nothing can reach, and dedup for making
identical ones share. With playback as the measure both become free, and the
size tie-break picks them up: 76 of 78 songs take dedup, 73 take packing.

Options given on the command line always beat the stored preset. A song with
no entry converts at the defaults. The file's `always` block carries what is
right for every song rather than searched per song — `gts5`, `--tempo auto`
and `--legal-restart` — which is what lets a preset reproduce the exact bytes
it records, and what makes the `gt2reloc` step at the end of the block
succeed for all 78.

[`presets.json`](presets.json) is the committed result for the Hubbard corpus:
78 songs, every one reproducing its recorded size exactly.

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

That rewrites `__version__` and prepends a [`CHANGELOG.md`](CHANGELOG.md) entry.
Never hand-edit the version in more than one place. If a document embeds the
version string (`SURVEY.md` records the converter version in its header),
regenerate it after bumping so the committed docs match the committed version.

## Testing

```sh
cd python && python -m pytest tests/ -q
```

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
[`--format`](#--format-gts2--gts5)) or run at the wrong tempo. Use
[`play.ps1`](#playing-a-song--playps1) to hear one, and
[`fidelity.py`](#fidelity--does-it-play-like-the-original) to measure the
corpus.

Treat any output-changing edit as a regression unless it is an intentional
feature — in which case extend the fixtures rather than deleting the assertion.

## Corpus survey

`python/survey.py` runs the converter over a directory of `.sid` files and writes
a Markdown report recording *why* each file fails, not just that it did:

```sh
cd python
python survey.py <sid_dir> -o ../SURVEY.md      # see --help for all options
```

It accepts the same output-shaping flags as the converter, so a report can be
generated for any combination of settings; the report header records which ones
were used and echoes the exact command that reproduces it.

[`SURVEY.md`](SURVEY.md) is the committed report for the Rob Hubbard corpus and
the single place conversion rates are quoted — it carries the pass/fail count,
the failure breakdown by stage, the detected player-variant spread and per-file
detail, all regenerated from the code. Deliberately **do not** restate those
figures here or in `CLAUDE.md`: they move whenever detection or capacity handling
changes, and a second copy goes stale silently.

"Converted" there means the converter produced a `.sng` without erroring — it
does **not** mean the output is musically correct. That question is
[`FIDELITY.md`](FIDELITY.md)'s, below.

## Fidelity — does it play like the original?

`python/fidelity.py` answers the question every other check in this repo
sidesteps. It converts a `.sid`, packs the `.sng` back to a `.sid` with
`gt2reloc` (Goattracker's F9 packer), traces **both** files with `siddump`, and
compares what the two players tell the SID chip to do:

```sh
cd python
python fidelity.py <sid_dir> -t 10 --presets ../presets.json -o ../FIDELITY.md
python fidelity.py --pair original.sid ours.sid        # two files you already have
```

It needs `siddump.exe` and `gt2reloc.exe` (`H2G_SIDDUMP` / `H2G_GT2RELOC`
override the paths) and is otherwise stdlib-only. The whole 95-file corpus
takes a few seconds.

What it counts is **note attacks** — the notes `siddump` prints bare, which it
does only after a gate rising edge (`siddump.c:376-380`). A note in parentheses
is the same voice moving to another pitch *without* re-triggering, and
`(+ 0034)` is a slide inside one note. That distinction is the whole point: a
plain `grep` for note names over the dump counts all three alike, and mistakes
one vibrato cycle for a re-struck note.

| metric | |
|---|---|
| **melody** | similarity of the attack sequence with consecutive repeats collapsed — the right notes in the right order |
| **seq** | the same, uncollapsed, so a note struck eight times where the original struck it once counts against it |
| **retrig** | our attacks over the original's; 1.0 is right |
| **pitch** | overlap of the distinct pitches played |

[`FIDELITY.md`](FIDELITY.md) is the committed report, and the single place
fidelity figures are quoted — as with `SURVEY.md`, do not restate its numbers
elsewhere. Regenerate it after any commit that changes conversion.

Two further comparisons are wired up behind flags, both shelling out to
[SIDM2](SIDM2-FIDELITY-TESTER.md)'s tools and inheriting their dependencies:
`--audio` (onset-aligned audio, tolerates our tempo offset) and `--register`
(frame-exact register comparison, only meaningful once tempo is reconciled).

A row can also say **not comparable**. `gt2reloc` exports only the subtunes
whose three voices all have nonzero length, and a subtune that fails that test
keeps its index and comes back as an entry that plays nothing — so comparing
against it measures our converter against silence. Those rows are marked and
left out of the averages rather than scored as bad conversions; the report
lists every affected file, including the subtunes that are silently dropped off
the end of the list. See [`SNG2SID-FIDELITY.md`](SNG2SID-FIDELITY.md) §7.

### Listening

`python/listen.py` stages the part no measurement covers:

```sh
cd python
python fidelity.py <sid_dir> -t 10 --presets ../presets.json -o ../FIDELITY.md \
    --json ../build/fidelity.json
python listen.py <sid_dir> --from-json ../build/fidelity.json -t 30
```

It picks one tune from each band of `FIDELITY.md` — the median of the band, not
the extreme — renders the original and our packed conversion to WAV with the
same emulator at the same settings, and writes `build/listen/LISTENING.md`
saying what the measurement predicts for each. Needs `SID2WAV.EXE`
(`--sid2wav`); output is gitignored, because it is for ears rather than for
review.

The reason it exists: `fidelity.py` compares note attacks and nothing else. It
cannot hear an envelope, a filter, a tempo or a timbre, and it scored *zero*
change for a correctness fix that rewrote 66 rows of one file (v0.5.46). Its
number is a floor on how wrong a conversion is, never a ceiling. Each staged
entry states what the numbers predict precisely so that a listen can contradict
them — a contradiction is the useful outcome.

## Repository layout

| Path | |
|---|---|
| `python/h2g/` | the Python port — active development target |
| `python/tests/` | regression tests |
| `python/survey.py`, `python/presets.py`, `python/bump_version.py` | tooling |
| `python/fidelity.py` | measures a conversion against the .sid it came from |
| `python/listen.py` | stages WAV pairs and a guide for a listening pass |
| `convert.ps1`, `play.ps1` | PowerShell wrappers: convert, and convert + open in GoatTracker |
| `build/` | converted output (gitignored); never written next to an input |
| `VB6 Sourcecode/h2g.frm` | the original VB6 tool; still the ground truth for behaviour |
| `arkiv/` | archived VB6 build and sample `.sid` files |
| `Commando.sid` / `Commando.sng` | byte-exact regression fixture pair |
| `H2G-CONVERSION-METHOD.md` | detailed explanation of how the conversion works |
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
  [`SURVEY.md`](SURVEY.md) § Out of scope for the inverse case, Hubbard tunes
  whose player is somebody else's.

## Licence

The original tool was released as free/open source — "can be modified and
republished ... used freely by others without notice".
