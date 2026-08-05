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
means it only works on tunes whose player matches one of 16 hard-coded game
fingerprints — see [`H2G-CONVERSION-METHOD.md`](H2G-CONVERSION-METHOD.md) for the
full method write-up.

## Usage

From `python/`:

```sh
python -m h2g <input.sid> [-o output.sng] [-q] [--max-rows N] [--terminate-patterns]
                          [--format {gts2,gts5}] [--tempo N|auto]
                          [--dedup-patterns] [--prune-patterns] [--pack-repeats]
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
right for every song rather than searched per song — `gts5` and `--tempo auto`
— which is what lets a preset reproduce the exact bytes it records.

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
[`play.ps1`](#playing-a-song--playps1) for that.

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
does **not** mean the output is musically correct. Only `Commando.sid` is
verified byte-exact.

## Repository layout

| Path | |
|---|---|
| `python/h2g/` | the Python port — active development target |
| `python/tests/` | regression tests |
| `python/survey.py`, `python/bump_version.py` | tooling |
| `convert.ps1`, `play.ps1` | PowerShell wrappers: convert, and convert + open in GoatTracker |
| `build/` | converted output (gitignored); never written next to an input |
| `VB6 Sourcecode/h2g.frm` | the original VB6 tool; still the ground truth for behaviour |
| `arkiv/` | archived VB6 build and sample `.sid` files |
| `Commando.sid` / `Commando.sng` | byte-exact regression fixture pair |
| `H2G-CONVERSION-METHOD.md` | detailed explanation of how the conversion works |
| `CHANGELOG.md`, `SURVEY.md` | version history, corpus results |

## Licence

The original tool was released as free/open source — "can be modified and
republished ... used freely by others without notice".
