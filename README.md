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

This converter emits **one pattern row per Hubbard player tick** — and a tick
is not a frame. The classic players gate their sequencer behind a countdown
(Commando `$5054`: `DEC $5513 / BPL / LDA $5517 / STA $5513`, with the
per-voice duration DEC running only on the reload frame), so one tick lasts
`reload+1` frames: 3 for Commando's main tune, 2 for Thing on a Spring, 4 for
Nemesis the Warlock. The reload value is **per subtune** where init loads it
from a table (Commando `$5F0F`: `TAX / LDA $5514,X / STA $5517` — speeds
2,3,2), and a static data byte where init never writes it (Zoids `$146F`).
The digi engine carries the same gate.

`--tempo auto` reads that value out of the player and writes it as each
subtune's `CMD_SETTEMPO` — a row of `frames` calls is exactly one tick of
`frames` frames. The value goes in pattern data because it survives
`gt2reloc`; the old instrument-63 Attack/Decay route did not (the ~1.2 KB of
padding it needed was stripped by the packer, leaving the tune at
Goattracker's 6-calls-per-row default).

```sh
python -m h2g song.sid --tempo auto     # derive per subtune from the player
python -m h2g song.sid --tempo 6        # explicit calls-per-row, all subtunes
```

Two limits, both from the Goattracker player:

- The fastest steady row is **three calls** (`gplay.c:325` reads tempo 0/1 as
  funktempo, and `gplay.c:334` stops the song outright if an instrument's
  gatetimer — always 2 here — exceeds the tick). A tune ticking every 1-2
  frames therefore cannot play at speed in a 1× Goattracker: `--tempo auto`
  writes `frames × multiplier` calls and the log names the `gt2reloc -S`
  value to pack with. See [presets](#per-song-presets--presetsjson) — the
  recommended multiplier is recorded per song. 30 of the 80 converting corpus
  files tick every 2 frames and need `-S2`; none tick every frame.
- Where no speed gate is found (the command-table dialect derives its row
  from the duration table instead; Mozart/Ninja/Mega Apocalypse use a
  *prescaler* — run the player v of every v+1 calls — whose jittery rate no
  steady tempo can express), auto falls back to the old constant of 3.

`--tempo` is **off by default** to keep the byte-exact `Commando.sng` fixture
intact — an untempo'd file plays at 6 calls per row. `play.ps1` passes
`-Tempo auto`, since that path exists to actually play the file.

**On the PSID speed field:** it is a per-subtune bitmap saying only *whether*
a subtune is CIA-timed rather than VBI-driven — never at what rate. It cannot
yield the tick length; the player's own speed gate is what does.

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

So `--effects` reads each bit **only where the routine that reads it is
present**, found by resolving the address the instrument-load routine stores
`+7` to and requiring the test block to name that address. 44 of the 88 files
that reach a wavetable have the drum routine, 13 the arpeggio one, 4 the
chromatic rise, 21 the pulse-width variant.

- **Bit `$02`, the chromatic rise** — the note climbs a semitone every four
  frames while it is held. Written as a looping note-relative portamento in the
  wavetable, which needs `--format gts5`; a GTS2 file stores no speed table.
  Continuous glide rather than four-frame steps: the rate is exact, the
  stepping is not.
- **Bit `$04` with a zero interval nibble is silent** in the player, because
  the nibble is written into the operand of an `SBC`. The original substitutes
  a `+12` relative note, inventing an octave-up arpeggio — for **315 of the
  corpus's 660** arpeggio instrument records, including all six of Commando's.
- **Bits `$01` and `$04` mean nothing at all in a player that has no such
  routine**, and the original synthesizes both for every file regardless:
  **159 of 450** records setting the drum bit and **544 of 683** setting the
  arpeggio bit are in such a file. Nothing is written for them now.
- **Where the drum routine is present the gesture is written the way the
  player plays it** (Warhawk `$1366`): the voice's own waveform with the gate
  released, then the frequency falling one high byte per frame — not the
  leading noise tick the original wrote, which is in no player. The drum's
  *noise ending* is measured and deliberately left out; see below.

An earlier version applied Warhawk's reading corpus-wide and was caught by
measurement: it put 287 frames of pitch movement into `W.A.R. Preview` and 256
into `Mega Apocalypse`, whose originals have **none**. Gated, the flag changes
no melody score and no corpus slide total in a 10 s window — only `Thrust`
exercises it at all within 60 s (0 → 76 slide frames against the original's
536). It is shipped narrow and verified rather than broad and plausible.

Corpus effect of the drum/arpeggio work, measured over the 82 scored files:
mean **wave** agreement 60.5% → **60.6%**, mean melody unchanged, no file's
convert-or-pack status changed; 22 files up, 16 down. The arpeggio half of it
is invisible to both metrics by construction — an arpeggio moves pitch, and
`melody` compares note attacks while `wave` compares waveform class — so 544
records of invention were removed for a change of 0.0 points. That it does not
show is not evidence it did nothing.

Two shapes were tried and rejected on the corpus rather than on argument:

- **Ending the drum on noise**, as `$139D` does, costs **2.4 points** of wave
  agreement (60.5% → 58.1%) and takes corpus noise frames from 5680 to 10666
  against the originals' 11641. Goattracker latches the last waveform of a
  gated-off voice until the next note, so a trailing noise entry stands for the
  rest of the note; the player stops writing `$D404` when its counter runs out.
- **Keeping the fabricated noise tick** where no drum routine was found is
  worth +0.3 points, and that is about what chance pays: in the files that lose
  the most (`Bangkok_Knights`, `Nineteen`, `Ricochet`) the originals are 46%
  noise by frame, so a tick lands on noise roughly half the time whatever it
  means. Removing it takes corpus noise frames further from the original's
  total (5680 → 4548) while raising agreement — the under-production is real
  and is a separate defect from the invention.

Off by default: it changes the output bytes of the files it reaches, the
fixture among them.

### `--status-bit6` (the skipped operand and note)

In 61 of the 95 corpus players the status-byte fetch tests **bit 6 first,
and alone**: Commando `$50CF` is `BIT status / BVS`, and the branch lands
past *both* the operand read and the note read, whatever bit 7 says. A
status byte of `$C0-$FE` therefore consumes nothing but itself — where this
decoder read an operand and a note the player never fetched, putting every
byte after them one or two positions out. Gated on the `BIT`/`BVS` shape
(`detect.STATUS_BIT6_SHAPE`); the digi and cmdtable engines fetch
differently and are untouched.

Commando has the shape but its played patterns contain no `$C0-$FE` byte, so
the byte-exact fixture does not move even with the flag on (pinned by a
test). Corpus-wide the bytes it reaches are almost all in *phantom* table
entries and unplayed remainders — at each song's presets only `Last_V8` and
`W_A_R` change at all — which is why this flag shipped **blocked** for two
versions: decoding Last V8's phantom entry `$1C` differently poisoned the
packed file's speed table and took its measured melody from 71% to 3%. Use
it together with `--reject-phantoms`, which removes that hazard; measured
with both flags at each song's presets, no corpus file moves by a point.

### `--reject-phantoms` (pattern-table validation)

The pattern count is inferred as `hi - lo - 1` — the gap between the LO and
HI pointer tables (`H2G-CONVERSION-METHOD.md` §4.2). Nothing says every byte
of that gap is an authored entry, so the table can claim **phantom** entries
whose "pointer" is whatever bytes sit in the cells. `Last_V8`'s entry `$1C`
points one byte past the last real pattern's terminator, straight into the
player's own track-selector routine.

The pass judges entries on the player's own terms, never statistically: an
entry is rejected if its cell or address lies outside the file, if decoding
it under the file's own grammar (dialect, `--slides`, `--status-bit6`) runs
off the end of the file, or if the bytes it would decode overlap the pointer
tables themselves or code that detection matched a player signature in
(`Detection.code_spans` — bytes *known* to be the player). A rejected entry
becomes the same one-rest placeholder an unresolvable address gets, so
orderlists that name it still resolve. Reachability is deliberately not a
criterion — unreferenced patterns are `--prune-patterns`' business, and
orderlists naming entries beyond the table (dangling references, see
`SURVEY.md`) are a separate phenomenon.

Corpus-wide the pass flags entries in 10 files, none of them referenced by
any clean subtune's orderlist; 7 of the 10 are digi-engine files whose
flagged entries already decoded to the placeholder, so bytes actually change
only for `Last_V8`, `Last_V8_C128_version` and `Kings_of_the_Beach_ingame`.
Off by default: it changes the output bytes of those files.

### `--fold-transpose` (transposes past Goattracker's ceiling)

Goattracker's orderlist transpose runs `$E0`–`$FE`, i.e. −16..+14: `$FF` is
`LOOPSONG`, and `gorder.c:70` rewrites a typed `$FF` back to `$FE` for exactly
that reason. Hubbard's players have no such limit and use **24, 36 and 48**
semitones — two to four octaves — in 17 corpus files. Those steps were
clamped to +14, so every note under one played 10 to 34 semitones flat.

A transpose is a pitch offset and nothing else on either side of the
frequency lookup (`CLC` / `ADC transpose,X` in the player, `newnote + trans`
at `gplay.c:927`), so `T` and `(T mod 12) + 12k` are the same interval. This
flag keeps the remainder — always 0..11 — in the orderlist and folds the
whole octaves into the note column of a copy of each pattern the step plays.
Pitches span `$60`–`$BC`, so there is usually room; where there is not, the
step keeps its clamp rather than being *partly* folded, which would only be a
different wrong pitch (and for a transpose of 24, a worse one). The
unfoldable remainder is almost entirely phantom subtunes carrying transposes
of 96 and more.

The cost is one pattern-table entry per distinct (pattern, octaves) pair
against Goattracker's 208; no corpus file stops converting at its presets.
Measured by position-aligned modal semitone delta against the original's
trace: `Deep_Strike` voice 0 `-10@100%` → `+0@100%` (and its melody
similarity 78% → 100%), `Kings_of_the_Beach_intro` and `Rock_Tells_the_Tale`
`-21@100%` → `+1@100%`, `One_on_One_Jordan_vs_Bird` `-9@100%` → `+1@100%`.
The remaining `+1` is a separate unexplained residual those files already
showed on their untransposed voices — not introduced here. Controls
(`Commando`, `Zoids`, `Crazy_Comets`, `Kings_of_the_Beach_ingame`) do not
move. Off by default: it changes the output bytes of the files it reaches.

Note that the file-wide **melody similarity** in `FIDELITY.md` can be blind to
this: it traces subtune 0 only, and three of the four fixed files carry the
defect in voices whose attacks the metric already scores at 0%. The modal
delta above is the measurement that sees it.

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
right for every song rather than searched per song — `gts5`, `--tempo auto`,
`--legal-restart`, `--slides`, `--effects`, `--status-bit6`,
`--reject-phantoms` and `--fold-transpose`, each of them either the player's
own reading or a no-op in the files it does not reach — which is what lets a
preset reproduce the exact bytes
it records, and what makes the `gt2reloc` step at the end of the block
succeed for all 78.

Each song also records a **`multiplier`** — the `gt2reloc -S` value its
`.sng` is tempo'd for. It is not a searched option but a property of the
tune's player: the classic players gate their sequencer behind a countdown
(`DEC counter / BPL / LDA reload / STA counter`), so one pattern row lasts
`reload+1` frames, per subtune where init loads the reload from a table.
`--tempo auto` reads that value out of the file and writes it as each
subtune's `CMD_SETTEMPO`. A tune ticking every 3+ frames plays exactly right
at `multiplier` 1; one ticking every 1–2 frames cannot (Goattracker's fastest
steady row is three calls), so its tempo is written as `frames × multiplier`
calls and the packing step must raise the call rate to match:

```powershell
gt2reloc song.sng song.sid -S2      # when "multiplier": 2
```

**Options go after both filenames.** `gt2reloc` reads `argv[1]` and `argv[2]`
positionally, so `gt2reloc -S2 song.sng song.sid` takes `-S2` as the input
name and writes nothing — silently, the same way every other `gt2reloc`
refusal looks.

`convert.ps1 -Sid` and `play.ps1` both apply the recorded multiplier when
given `-Presets`: the first passes `-S{n}` to the packer, the second prints
the number of `SHIFT+F6` presses the editor needs, which is the same setting
reached a different way. A `.sng` packed without it plays uniformly
`multiplier` times too slow.

**siddump cannot check this** — it ignores the PSID speed field and calls the
play routine 50 times a second regardless (`siddump.c:309/325`), so `-S`
changes the packed bytes and not the trace. Measured A/B on `Chain_Reaction`:
identical melody, sequence, retrigger ratio and attack counts with and
without it; corpus-wide, applying it moves two files by one point (the CIA
stub's one-time startup shift) and nothing else. `FIDELITY.md` therefore
understates every `multiplier > 1` row and says so in its summary. Only a
cycle-counting emulator can score them.

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
