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

`--slides` reads the second operand byte in the 41 players that fetch one —
and since v0.5.83 it reads it under the right dialect. Two players disagree
about which byte is which half of the 16-bit step behind the *same* fetch
shape: Warhawk takes the operand as the low half with bit 0 as the direction,
and 22 corpus files take it as the high half with `CMP #$BF` as the direction.
Detection picks per file. Read the wrong way round the step came out ~256×
too large and then saturated the 8-bit pattern column, which is what 39% of
the corpus's portamento parameters were doing. In a `gts5` file the column now
carries a speed-table index and the step keeps its full width; a `gts2` file
keeps the packed byte, because its loader reads that column as the value.

The flag now covers all three pattern grammars. The **digi** engine's slide is
effect `$82`, a signed 16-bit per-frame step with the first operand as the high
half (v0.5.86) — present in all nine digi players, used by five of them, 128
columns in total. The **command-table** engine's is command 1, low half first
with the high half masked and the direction in bit 7 (v0.5.87) — present in
both players and used by **neither**, so it changes no corpus byte. Both are
complete readings; only the classic one moves numbers.

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
this: it traces one subtune per file, and three of the four fixed files carry
the defect in voices whose attacks the metric already scores at 0%. The modal
delta above is the measurement that sees it.

### `--initial-instrument` (the instrument a voice starts on)

Hubbard's player keeps a per-voice instrument *index* in a three-byte array
and writes it only when a pattern carries an instrument byte. A voice whose
first note is reached before any pattern names one therefore sounds whatever
that array held. Goattracker has the same carry-forward rule --
`gplay.c:914` assigns `cptr->instr` only when the row's instrument column is
non-zero -- but a different starting point: `gplay.c:223` sets every channel
to instrument **1**, which this writer emits as the empty "Clear Voice"
record (attack/decay 0, sustain/release 0). Those voices came out silent.

`Delta_Mix-E-Load_loader` is the clear case. Its orderlists are one pattern
per voice, patterns `$18` and `$17` carry no instrument byte at all, and the
array at `$C535` reads `03 09 00` -- exactly the three records whose ADSR
siddump shows the original playing (`3A98`, `BC5D`, `0CF8`). Voice 1 is the
control: its pattern selects `$09` explicitly, and the array agrees. With the
flag its waveform agreement goes 33% → 97% and its melody 10% → 29%.

The flag copies the pattern and repoints that one orderlist step at the copy,
rather than patching in place: the same pattern is played again later in half
these files, where the voice already has an instrument, and a column written
into the shared copy would re-select it every time round. Costs one
pattern-table entry per distinct (pattern, instrument) pair. It reaches 11
corpus files.

**Not in `presets.json`'s `always` block, and this is the reason.** The array
is mutable player state, so its file-image value is the starting instrument
only for a rip of a single tune. `Commodore_64_Music_Examples` has fifteen
subtunes, and its array (`00 07 05`) names records whose ADSR is `4764`,
`2524` and `2740` while the original plays `5C3A`, `1858` and `0868` -- the
snapshot caught the array mid-tune, and no static read can recover what each
subtune starts from. Turning the flag on there raises melody 15% → 19% and
drops waveform agreement 29% → 0%. Use it on single-tune rips; the two files
it was derived from are both of those.

### `--filter` (the filter, which was never emitted at all)

Hubbard drives the SID filter in **32 of the 95 corpus files**, and every one
of them has always been converted with the filter switched off: `goatwriter.py`
wrote a hard-coded empty filter table for every file it has ever produced.
The notes were right and the sound was not.

The data is per instrument, in a two-byte array parallel to the instrument
table and indexed by the same `i * instr_stride`. One routine reads it, and it
is the same routine in every player that has it -- Deep Strike `$C376`, and 23
more files identical apart from the operands:

```
C376  BD E9 C4  LDA cutoff,X      ; per-VOICE running cutoff
C379  18        CLC
C37A  79 56 C5  ADC step,Y        ; += this instrument's sweep step
C37D  9D E9 C4  STA cutoff,X      ; accumulate back
C380  8D 16 D4  STA $D416         ; cutoff HIGH byte only
C383  B9 55 C5  LDA resctl,Y      ; this instrument's resonance/routing
C386  8D 17 D4  STA $D417
```

`resctl` is always exactly `step - 1` -- one array, byte +0 resonance and
routing, byte +1 the signed per-frame step. That held in **24 of 24** files the
shape matched, which is what proves the layout rather than assuming it. Only
`$D416` is written; the low three bits of cutoff at `$D415` are untouched in 26
of the 32 filter-using files, and Goattracker's filter-table cutoff is likewise
a single byte, so the value transfers without scaling.

Goattracker expresses that as three steps -- set passband and resonance, set
cutoff, modulate -- which is what this flag emits, one block per filtered
instrument.

**The gate is the player's own.** The routine runs only for an instrument whose
status byte has bit `$20` set (`LDA status / AND #$20 / BEQ past`). Reading the
array without that test invents a filter: Powerplay Hockey and Wiz both carry
the routine *and* plausible-looking array data while their originals never turn
the filter on, and an earlier version of this flag gave Powerplay five filtered
instruments and 497 cutoff writes against an original that writes it once.
With the gate, both come out untouched.

Applied only where the routine, its passband and the cutoff each note starts
from can all be read. That is 15 files; 10 of them gain an audible filter and
the other 5 have no instrument with the bit set. Measured against the original
over 60 s, in cutoff writes:

| file | original | before | after |
|---|---:|---:|---:|
| I_Ball | 2752 | 1 | 2993 |
| IK_plus | 2916 | 1 | 2993 |
| Pandora | 2831 | 1 | 2993 |
| Trans-Atlantic_Balloon_Challenge | 2759 | 1 | 2961 |
| Nemesis_the_Warlock | 2105 | 1 | 1969 |
| ACE_II | 2860 | 1 | 1915 |
| Nineteen | 2224 | 1 | 1841 |
| Star_Paws | 2777 | 1 | 1674 |
| Thundercats | 2489 | 1 | 1371 |
| Deep_Strike | 481 | 1 | 1515 |
| **Powerplay_Hockey** (never filters) | **1** | **1** | **1** |

Deep Strike is the one that overshoots: a Goattracker modulation step runs for
a fixed number of ticks and the player's sweep is bounded by its own counter,
so a file whose sweep is short gets a longer one here. The others land in the
right order of magnitude.

**What this cannot express.** The player accumulates the cutoff *per voice*;
Goattracker has one filter and one cutoff for the whole tune. That is the SID
chip's limit rather than the format's -- the original has the same single
filter and the same last-writer-wins race between voices -- but it does mean
two instruments sweeping at once come out as whichever was struck last. The
passband is also fixed per file here, so the files that alternate lowpass and
bandpass per note (I_Ball, IK+, Pandora, Star_Paws, Thundercats,
Trans-Atlantic, Nineteen) keep whichever the mode register was set to.

**What `FIDELITY.md` can see of this.** Nothing, until v0.5.78: `wave`
compares the waveform *class* and ignores the filter, and melody, sequence and
pitch compare note attacks, so the evidence this flag worked was the
cutoff-write table above and the disassembly rather than the report. The
report now carries a `filt` column — frames on which a voice is routed into
the filter *and* a passband is selected, ours over the original's, in the
one-sided form that catches an invented filter — and a *Filter* section
comparing how far the cutoff travels on each side, which is the question a
write count cannot answer. What it still cannot see is the two limits named
above: the per-voice cutoff collapsed into one, and the fixed passband.

Off by default: it changes the output bytes of the 15 files it reaches, and
`Commando.sng` -- which has no filter routine -- is byte-identical either way.

### `--vibrato` (the pitch movement that never happened)

Goattracker runs a per-instrument vibrato with no pattern command at all: on
every new note `gplay.c:352-354` loads the instrument's `vibdelay` and its
speed-table pointer, and a channel with no command of its own falls through
into `CMD_VIBRATO`. Those are instrument-record bytes 5 and 6 — and this writer
emitted `0x00, 0x00` there from the day the port began, so **no `.sng` this
project has ever produced vibrated**. 33 of 95 corpus files moved the pitch not
at all where the original does, and 20 of those originals are vibrato-shaped:
their movement returns rather than travels.

**56 of 95 players carry it in one instrument-record byte** (`+5`): bits 3-6 an
amplitude bound, bits 0-2 a right-shift applied to the semitone interval at the
current note. Goattracker's note-relative speed form is the same arithmetic
(`gplay.c:786-792`), so the mapping is close to literal — the period gives
`cmp = 2 × bound × multiplier` and the excursion then gives
`rshift = shift + 1 + log2(multiplier)`. Detection is gated on finding both the
parameter split and the depth derivation, which the corpus never separates (all
56, no exceptions), so the flag is a no-op in the other 39 files.

| | before | after |
|---|---:|---:|
| corpus median `bend` | 0.06x | **0.33x** |
| files bending nothing where the original bends | 33 | **11** |
| moved toward the original / away | — | **29 / 6** |

No other column moved. All six that moved away were already overshooting for an
unrelated reason (Thrust 3.74x, Bump_Set_Spike 11.45x) — a correct vibrato
added to a file that already bends ten times too far is still correct.

**Needs `--format gts5`.** A GTS2 file stores no speed table; its loader packs
the vibrato into a single instrument byte and reads bytes 5 and 6 the other way
round (`gsong.c:284-285`). Off by default because it changes the output bytes;
`presets.json`'s `always` block sets it. `Commando.sng` is byte-identical
either way — its player has no such routine.

### `--pulse` (the duty cycle that never moved)

Hubbard has **two** pulse engines and no file uses both: 34 corpus files sweep
the width between two bounds, 21 accumulate into its low byte, and the flag now
reads both. The sweep is described first; the accumulate engine follows under
*The other engine* below.

Hubbard sweeps the pulse width every frame in **43 of the 95 corpus files**,
and until this flag every one of them came out with the duty cycle frozen at
its starting value. `goatwriter.py` wrote one "set pulse width" per instrument
and stopped -- correct for the 328 records whose sweep rate is zero, wrong for
the 414 that sweep. A static duty cycle under otherwise correct notes is a
flat, lifeless lead; it is the second half of the same defect `--filter`
covers, and it was reported by ear before any metric showed it.

The routine is one block, self-modifying, and identical in all 43 files apart
from operands -- Flash Gordon `$128F`:

```
128F  AC 35 15  LDY $1535         ; instrument index * 8, saved at note start
1292  B9 F4 15  LDA bounds,Y      ; ONE byte holding both turning points
1295  29 0F     AND #$0F          ; low nibble  -> lower bound
1297  8D D4 12  STA $12D4         ; self-modifies the CMP below
129A  B9 F4 15  LDA bounds,Y
129D  4A 4A 4A 4A  LSR x4         ; high nibble -> upper bound
12A1  8D BA 12  STA $12BA         ; self-modifies the other CMP
12A4  BD 07 15  LDA dir,X         ; per-voice direction flag
12A7  D0 1A     BNE $12C3         ; set -> descend
12A9  AD 03 15  LDA rate          ; instrument byte +6, copied here at note start
12AC  18        CLC
12AD  7D 47 15  ADC pulse_lo,X    ; 12-bit per-voice accumulator
...
12B9  C9 04     CMP #$04          ; <- upper bound, patched at $12A1
12BB  D0 1D     BNE $12DA
12BD  FE 07 15  INC dir,X         ; hit the top: turn around
```

That the routine **writes its own bounds into its own operands** is what makes
the reading unambiguous: both nibbles of one byte are provably the turning
points and nothing else. The accumulator is written to `$D402`/`$D403` every
frame -- a triangle wave on the duty cycle.

Goattracker's pulse table says exactly this (`readme.txt:887-891`): a "set
pulse width", an ascending step, a descending step, and a jump back. Two
things are approximations, and both are stated in `_pulse_program`:

* the player turns around when the high nibble *equals* a bound, so a rate
  that does not divide the span overshoots by up to one step; the tick count
  here turns around a fraction of a step early instead.
* Goattracker steps the pulse table once per play **call** (`gplay.c:872`)
  where the player steps once per **frame**, so at `-S2` the speed is halved
  and the tick count doubled. An odd rate at `-S2` cannot be halved exactly;
  the ticks are recomputed from the speed actually emitted, so the sweep still
  covers the right band.

Where the rate is zero, or the bounds leave no band to travel, the static
width is kept -- an under-read never invents movement.

**No metric in this repo could see this flag** when it shipped, for the same
reason as `--filter`: `wave` compares the waveform *class*, and pulse is pulse
whatever its width. Measured on the 37 files it reaches, mean melody and mean
wave agreement are **identical to the decimal** before and after. The evidence
that it worked was siddump's `Pul` column, read by a script written for the
occasion: **757 changes to 35892** against the originals' 60056 — **1% of the
original's pulse movement to 60%**. That reading is now the report's `pul`
column, ours over the original's, and it is a movement count rather than an
agreement percentage on purpose: two players sweeping the same duty cycle from
different phases share almost no frame values, and the defect this flag fixes
is a *frozen* width rather than a wrong one.

Off by default: it changes the output bytes of the 37 files it reaches.
`Commando.sng` -- whose player has no sweep block -- is byte-identical either
way.

#### The other engine (effect bit `$08`)

The sweep block is absent from 21 files that nonetheless move the duty cycle.
They select a second engine with bit `$08` of the instrument's effect byte, and
it is simpler: add record `+6` to the width's **low byte** every frame and write
`$D402` alone, never `$D403`. The duty cycle races around one 256-wide band
while the high nibble stays where the note put it. Commando `$52AC`:

```
52AC  AD 23 55  LDA $5523        ; the effect byte
52AF  29 08     AND #$08
52B1  F0 15     BEQ skip
52B3  AC 18 55  LDY $5518        ; instrument index * stride
52B6  B9 91 55  LDA rec+0,Y      ; the accumulator: the record's own low byte
52B9  6D 07 55  ADC $5507        ; the rate, self-modified at note fetch
52BC  99 91 55  STA rec+0,Y      ; written back, so a static read sees the seed
52BF  AC EB 54  LDY $54EB        ; voice
52C2  99 02 D4  STA $D402,Y      ; LOW byte only
```

Three facts establish the field layout rather than assuming it. The rate is not
in that block -- `$5507` is absolute and self-modified at note fetch from
record `+6`, which holds in **21 of 21** files and agrees with the independent
SF2 reading in `SIDM2-HUBBARD-KNOWLEDGE.md`. The width is seeded per note by
`PLA / STA rec+1,Y / STA $D403,X / PLA / STA rec+0,Y / STA $D402,X`, giving
`+0` low and `+1` high -- the same two bytes the static path has always written
as a fixed width. And the block indexes the instrument table itself, which the
finder requires: a match naming any other array is rejected.

In a Goattracker pulse table this is a set to the seeded width, one ascending
leg long enough to cross the low byte, and a jump back to **the set** rather
than to the leg. Jumping to the set is what pins the high nibble: Goattracker's
modulation carries into it (`gplay.c:888-900`) and the player never does. The
approximation is the phase -- the player's accumulator wraps mod 256 and carries
its position into the next cycle, where restarting at the seed does not. The
band and the period are right.

**Bit `$08` is per instrument, not per file**, and it is sparse: 5 of the 21
files carry the routine with no instrument using it at all (Bump Set Spike,
Formula 1 Simulator, Las Vegas Video Poker, Mozart, Thrust), so their flat duty
cycle has some other cause. Measured against the previous release, five files
move the `pul` column and nothing else moves anywhere:

| file | before | after | original |
|---|---:|---:|---:|
| One Man and his Droid | 18 | **724** | 991 |
| Geoff Capes Strongman Challenge | 27 | **771** | -- |
| Zoids | 23 | **343** | -- |
| Commando | 29 | **397** | 376 |
| Gerry the Germ | 25 | **196** | -- |

Sixteen files change bytes; eleven of them move no number, because the records
the engine reaches do not play inside the traced ten seconds.

### `--sustain-exact` (the sustain nibble as the SID reads it)

The VB6 original masked bit `$10` out of any sustain/release byte `>= $F0`
(`h2g.frm:578-579`), with the comment *"&SSSXRRRR (S=Sustain, R=Release,
X=Cut this bit out)"*. There is no X bit. SID register 6 is `SSSS RRRR` --
four bits of sustain, four of release -- so clearing `$10` does not remove a
spare flag, it lowers a sustain of F to E. That is the level the note holds
at for its entire length, on every instrument that asked for full sustain.

The port inherited the mask and this flag removes it. It reaches **64 of the
83 convertible files**, which is why it is opt-in rather than simply fixed:
it changes the bytes of the `Commando.sng` fixture too.

### `--no-hard-restart` (stop resetting the envelope before every note)

Goattracker writes its hard-restart value into `$D405`/`$D406` for one frame
ahead of each note unless the instrument sets `gatetimer` bit `$80`
(`gplay.c:930-937`, flag at `gsong.c:381`). The value is the editor's `HR`
parameter, default `$0F00` (`goattrk2.c:49`), baked into the packed player as
`ADPARAM`/`SRPARAM` (`greloc.c:1138`).

Hubbard's players never do this. `$0F00` appears in **none** of the corpus
originals and is the **most common ADSR value in every conversion** without
this flag -- an envelope reset on every note that the music being converted
does not contain. The flag sets bit `$80` on every instrument read from the
file. It does not set bit `$40`, which would suppress the gate-off as well
and stop notes releasing at all.

**Together the two options take per-frame ADSR agreement from 54.2% to
66.2%** across the 83 convertible files (`--sustain-exact` +6.3,
`--no-hard-restart` +5.0, measured separately). Both are in `presets.json`'s
`always` block.

**The cost is one file.** Hard restart exists because the SID's envelope
generator does not always retrigger cleanly without it, and Confuzion goes
from 82% to 78% melody similarity with `--no-hard-restart` on. Nothing else
in the corpus moves on melody, sequence, pitch or waveform.

**No column in `FIDELITY.md` could see either change when they shipped.**
`wave` compares the waveform class and ignores ADSR entirely; melody, sequence
and pitch are attack comparisons. The 54.2% → 66.2% figure above comes from a
separate per-frame comparison of siddump's `ADSR` column written for the
occasion, not from the report. Since v0.5.78 that comparison **is** a column —
`adsr`, per frame and per voice, built the same way `wave` is — so the two
options are measurable in place; the historical figures here are kept as
measured and are not restated from the report. Both options were prompted by a
listening pass -- "the notes sound correct, but the sounds are not correct" --
which is still the only check in the project that could have raised them.

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
own reading or a no-op in the files it does not reach (`--initial-instrument`
is deliberately *not* among them -- see its section above) — which is what lets a
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

**The multiplier changes more than the tempo.** Everything this converter
reads out of a player is a rate *per frame* — a slide's step, the drum's
sweep, the chromatic rise, the length of an instrument's attack waveform —
and everything Goattracker applies them with runs *per play call*
(`gplay.c:707/748/758`). At `-S2` those are not the same unit, so until
v0.5.82 every one of them ran at twice the player's rate in exactly the 33
songs that pack at `-S2`. Since v0.5.82 the converter divides each rate by
the multiplier it wrote the tempo for, so the file is correct at the `-S`
value `presets.json` records — and only at that value. Packing a
`multiplier: 2` song at `-S1` was always wrong (it plays half speed); it is
now wrong in the slides as well. Three rates keep a stated residual — the
arpeggio alternation, the drum's own attack, and the rise at a non-power-of-two
multiplier — see H2G-CONVERSION-METHOD.md § 7.bb.

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

Attacks are not all of it. Six further columns compare the registers
themselves, each frame-by-frame with the last written value carried forward,
because siddump prints a register only when it changes: **wave** (the
waveform-select nibble), **noise** (frames of noise, ours over the
original's), **adsr** (the envelope pair `$D405`/`$D406`), **pul** (how often
the duty cycle moved, ours over the original's), **filt** (frames with a voice
routed into the filter and a passband selected, ours over the original's) and
**cut** (how far the cutoff travels, over the original's travel). The three
counted ones are one-sided on purpose: they answer "did we invent this" or
"did we drop it", which no agreement percentage can say — and `cut` is a
ratio rather than a count because a sweep taken in finer steps writes twice as
often and goes exactly as far. `FIDELITY.md`'s own legend defines each, a
*Filter* section there carries both sides' raw figures, and *What this run
compared* names the registers no column reads (with these six, none).

[`FIDELITY.md`](FIDELITY.md) is the committed report, and the single place
fidelity figures are quoted — as with `SURVEY.md`, do not restate its numbers
elsewhere. Regenerate it after any commit that changes conversion.

**Which subtune gets traced.** One per file, and it is the one the PSID
header's `startSong` field names — the subtune a player selects when the user
selects none — not subtune 0. Seven corpus files set it past 1, and for those,
subtune 0 is not the tune: *Samantha Fox Strip Poker* has fourteen subtunes,
`startSong` 10, and a one-note stub at 0. Tracing that stub scored a correct
conversion at 5%; its own default subtune scores 89%. `-a N` forces a
particular one, `-a auto` (the default) reads the header.

Our subtune numbering does not have to line up with the original's — a subtune
whose orderlist exceeds Goattracker's limit costs itself and shifts every later
one down — so `--search-subtunes` tries a window of ours around the traced
index and keeps the best match. The default window is 3, one either side, which
is what a single dropped subtune can displace. That window moves exactly two
corpus files and widening it moves none, so it identifies the counterpart
rather than trawling for a flattering score; the report names the files it
moved.

That option varies **our** index and holds the original's at its `startSong`,
which fixes a displacement on our side and nothing else. It cannot fix a
displacement on the original's side, and two corpus files have one: their
`.sid` carries an init wrapper that renumbers the subtune before the player
sees it. *Dragon's Lair Part II* (`init $AF00`) sends PSID subtune 0 to song
9, 1 to song 7 and 9 to song 8; *Rasputin* (`init $CFB5`) sends 0 and 1 to a
different entry point altogether and maps n to song n-2 above that. No window
size reaches those, because the number that moved is the one the search holds
fixed. `--diagnose` is what finds them.

### Diagnosing one file

```sh
python fidelity.py <one.sid> --diagnose -t 10
```

One file, explained instead of scored. It prints, in the order the questions
have to be asked in:

* **the subtune correspondence matrix** — melody % for every one of the
  original's subtunes against every one of ours, with the traced row marked,
  followed by the correspondence stated in words. Until this is settled, every
  other number about the file may be comparing two different pieces of music,
  and for three of the four files the report used to file under *plays
  something else* that is exactly what it was doing. Dragon's Lair Part II
  scores 7% on the diagonal and **94%, 98% and 97%** at its real counterparts.
* **a per-voice cause** for the traced pairing, and again at the best
  counterpart when that is a different subtune. Each voice comes back as one
  of: *matches*, *silent in both*, *absent*, *invented*, *transposed k
  semitones*, *under-produced*, *over-produced*, or *different music*. The
  transposition test is a constant-shift sweep over ±24 semitones taking the
  sequence ratio at each — robust where a position-aligned modal delta is not,
  because the alignment slips as soon as either side drops a note, which is
  the regime every low-scoring file is in. A peak must beat the unshifted
  ratio by a margin *and* be worth something absolutely, so unrelated music
  comes back as unrelated rather than as a transposition that is not there.

The shift is signed as **ours against the original's**: `-7` means we play the
tune a fifth low, not that adding seven would fix it.

It writes no report and takes no `-o`/`--json`/`--baseline`; the output is an
argument about one file, not a row.

A short trace is its own hazard in the same family. `BMX_Kidz.sid` opens with
about thirteen seconds of rest, so at `-t 10` neither side has played a note
and the file scored 0% — at `-t 60` it scores 95%. Rows where **both** sides
are empty are now reported as *window empty* and left out of the averages
instead of being scored as a failed conversion.

`siddump` names a note from the SID frequency register, so both sides have to
be read on the same tuning or the comparison is measuring a key change. Four
corpus files (Kings of the Beach intro, One on One, Powerplay Hockey, Rock
Tells the Tale) carry frequency tables computed for the **NTSC** C64's faster
clock, which puts every register value 0.647 semitones below the PAL
equivalent — near enough a whole semitone that `siddump` names the original in
a different key and scores four files that play the right notes at 0%. The
harness reads each player's own frequency table (`sidfile.find_freq_table`) and
recalibrates the *original's* dump to it with `siddump -c`; ours is always
Goattracker-tuned, so nothing on our side moves. A row that needed it says so.
This is a naming correction, not an allowance: a table whose *index* is shifted
rather than its tuning is a converter defect and is fixed in the converter.

### What a run says it compared

Every report ends with a **What this run compared** section, generated from the
rows rather than written by hand: each dimension, the number of files it was
actually computed on, and the SID registers it is derived from. Underneath it
are the registers *no* dimension in that run reads. When the section was built
that was five of the seven — `$D402/$D403` (pulse width), `$D405/$D406`
(envelope), `$D415/$D416`, `$D417` and `$D418` (filter and volume) — and
v0.5.78's `adsr`, `pul`, `filt` and `cut` columns are those five becoming
dimensions, so a full run now lists none. A run that loses a dimension still
lists its registers, which is the point of generating the section rather than
writing it. Register coverage is not total coverage: note length, tempo,
master volume and anything outside the traced window are listed beside it as
unseen, and none of them is a register nobody reads.

That list is the report stating its own reach. A change confined to it cannot
move a single number here whatever it does to the sound, so a flat table is not
evidence the change did nothing. This has been the most repeated misreading in
the project's history and it was previously prevented only by authors
remembering to write the caveat.

### A/B against a previous run

```sh
python fidelity.py <sid_dir> -t 10 --presets ../presets.json --json before.json
# ... change something ...
python fidelity.py <sid_dir> -t 10 --presets ../presets.json \
    --baseline before.json --ab-output ../build/AB.md
```

`--baseline` compares a saved `--json` run against the one just taken and
prints, sorted by the largest movement on any one dimension, which files moved
and by how much. It is deliberately not only a delta table: each row also
carries a hash of the converter's own output, which is what separates the two
readings of a table that did not move.

| verdict | what it means |
|---|---|
| **no dimension this report measures can see this change** | the converted bytes changed and no number moved — the change is real and landed in a register named above |
| **this change reaches nothing** | the converted bytes are identical too, which is the shape of `--slides` (dead for four versions) and `--filter` (wired into `convert()` and README and into neither the presets nor the harness) |
| **every movement is below the precision the report prints** | the numbers moved and `FIDELITY.md` would have looked identical |
| *n* **files move the printed report** | plus, always, how many of the files whose output changed moved *nothing* |

A comparison **refuses** (exit 2) when the two runs were traced at different
`-t` seconds or different subtunes: those are numbers about different music. A
difference in *conversion options* is not refused — an option A/B is what the
mode is mostly for — but it is named at the head of the output as the change
under test, which is the same protection against presets silently drifting
between two runs.

`--label` now defaults to `git rev-parse --short HEAD` plus `-dirty` when this
project's files are modified, and is recorded in every row. A measurement taken
from a half-applied tree has cost this repo two re-runs and the report had no
way to say it happened.

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

**RSID originals render through VICE.** `SID2WAV` is from 1997 and predates
RSID, so it refused 18 of the 95 corpus files — including all four NTSC ones
and `Skate_or_Die_intro`. Since v0.5.92 those fall back to VICE's `vsid`, and
both sides of the pair then go through *it* rather than one renderer each,
because two emulations differ in level and filter enough to colour a listening
judgement. The trick, after three earlier attempts produced a 44-byte
header-only file, is that **`-warp` suppresses the sound device's output**
whatever `-soundwarpmode` says; without warp it renders, in realtime.

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
