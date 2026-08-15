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

**Except in one player.** Rasputin reads `$FE nn` as a two-byte command that
*continues* the list — its operand reloads the counter above the speed gate,
so it scales the row rate from that step on — and `$FD` as the end of a
voice's list. That is read from each player's own orderlist reader rather than
from the file's version number: applying it to the whole of version 0 rewrote
23 files and broke the byte-exact fixture. Three corpus files test `$FD`
(Knucklebusters, Rasputin, Tarzan) and only Rasputin has the two-byte `$FE`.

The tempo change is emitted as a `CMD_SETTEMPO` in the pattern played at that
step — Goattracker's orderlist has no tempo command — into a *copy* of that
pattern, since the same pattern is played at other tempos elsewhere. Rasputin
gains `melody` 71% → 75%, `retrig` 1.81 → 1.66 and `wave` 43% → 46%, with no
dimension worse and no other file's bytes moved. See
H2G-CONVERSION-METHOD.md § 7.ddddd, which also records why the operand is
*not* the row length: read that way its `$FE 78` would be 121 frames a row
against its neighbours' 3.

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
  player plays it** (Warhawk `$1366`): the record's own waveform on the note's
  first frame, then noise while the block's duration counter is still large,
  then the voice's waveform with the gate released and the frequency falling
  one high byte per frame. The noise is the block's own `BCC` branch, not the
  fabricated tick the original wrote; its length is the player's speed gate
  less one, read at the subtune the file starts on. A record that *also*
  arpeggiates gets it too — the drum block falls through into the arpeggio's
  bit test rather than branching around it, so both run — but loses the sweep,
  which the arpeggio needs the slots for. The drum's *noise ending* is
  measured and deliberately left out; see below.
- **Bit `$02` is the rise in one dialect and an alternating waveform in
  twenty-one others** (W_A_R `$E759`): the voice's waveform swaps every frame
  between the record's `+2` and a second per-instrument table, chosen by the
  low bit of a per-voice frame counter. In 20 of the 21 files the alternate is
  `$81`, noise with the gate on, so it sounds a noise frame every other frame
  under the note. Emitted since v0.5.231, gated on the *routine* being found
  rather than on the bit — no file has both blocks. The note's first frame
  belongs to the init path, so the shape is the frame-0 lead and then the pair
  looping, each half held for `multiplier` calls. Corpus `onset` 82.8% →
  86.7%, and the noise-frame counts land on the originals' (Flash Gordon
  1142/1144, W.A.R. 818/820, Tarzan 1254/1255) with melody, seq, pitch,
  retrig, adsr and the rest unmoved on every file. See
  H2G-CONVERSION-METHOD.md § 7.hhhh.
- **The sweep is as deep as the note is long, and no deeper.** The routine has
  two exits — `LDA freqhi,X / BEQ out`, the frequency reaching zero, and
  `LDA remaining,X / BEQ out`, the note ending — and for a long time only the
  first was expressed, as the distance a `CMD_PORTADOWN` chain can fall before
  wrapping. On a short note the second fires long before it: Commando's
  instrument 13 had room for thirteen steps, was capped at eight, and its
  original takes **five**, because the note is four rows long. A note of `n`
  rows sweeps `(n - 2) * frames_per_row - 1` steps, and the number written is
  the **median** over the notes the instrument is actually played at — one
  wavetable entry chain has to stand for all of them, and the median is what
  minimises the total error against a spread. Traced end to end on two files:
  the dominant sweep now matches the original frame for frame. See
  H2G-CONVERSION-METHOD.md § 7.ccc.

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

### `--compact-instruments` (the wasted instrument slot)

The VB6 original reserved instrument 1 for a hardcoded **Clear Voice**
placeholder — `AD $00 / SR $00` with a wavetable of `$09`, gate plus testbit —
and started the player's own records at instrument 2. Goattracker reserves
nothing: its format stores instruments from 1, and a pattern column of 0
already means "no change". The placeholder therefore costs an instrument slot,
five wavetable entries, and one of offset between every Goattracker instrument
number and the player's own record number.

With this flag the player's record 0 goes into slot 1 (`goatwriter`'s
`instr_base`) and the numbering matches the player's. Off by default: it
renumbers every instrument in every file, the byte-exact `Commando.sng` fixture
included. `presets.json`'s `always` block sets it, so every conversion made
through `--presets` is compacted. Added in v0.5.161, after the listening
session that established what the placeholder sounds like
(`H2G-CONVERSION-METHOD.md` § 7.bbb).

### `--rest-instrument` (the instrument change that clicked)

An instrument change landing on a rest used to be emitted as a fake `C-0` on
instrument 1 — the Clear Voice above — on the assumption that Goattracker
cannot latch an instrument without a note. It can: `gplay.c:912-914` latches
the instrument column whenever it is non-zero, *before and independently of*
the note test, so a rest row carries the change and sounds nothing. The
placeholder is an all-zero envelope with the testbit set, i.e. a click **and a
retrigger of whatever was sounding** — and 12 rows of Commando played it, 1422
rows across 64 corpus files.

With this flag the change rides the rest itself. Off by default because it
moves the output bytes, the fixture among them — which is the anchor doing its
job, since the VB6 original is what emitted the placeholder. In
`presets.json`'s `always` block. It was found by ear rather than by a column:
no dimension of `FIDELITY.md` reports it (§ 7.bbb).

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

### `--skip-gate` (the row length the gate alone under-reads)

The speed gate is a counter reloaded once per row, so a row looks like
`reload + 1` frames. Most Hubbard players decrement it on only *some* frames —
a second counter jumps past the gate, or returns from the play call outright —
so a row really lasts `(reload + 1) × (O + 1) / O` frames. Reading the gate
alone under-reads the row, and the corpus said so before the mechanism was
found: measured against the original, tunes whose gate says 2 played 2.5–3.0
and tunes whose gate says 3 played 3.5–4.5.

This flag reads the outer counter too (`goatwriter.OUTER_GATE`, and since
v0.5.248 the `RTS` spelling `OUTER_GATE_RTS` that nine files use), and applies
it only where the corrected row is expressible — a whole number, or a fraction
Goattracker can carry through the `-S` multiplier (`effective_frames`,
`MAX_ROW_DENOMINATOR`). Tarzan goes from 0.67 of the original's pace to 1.00
and its melody from 73% to 96%; Delta's row is 5/2 at `-S2`, Deep Strike's 8/3
at `-S3`.

**It moves the recommended `-S` value**, so whatever packs the result has to
pack it at the new one — the converter logs it and `presets.json` records it
per song. On by default via `presets.json`'s `always` block: v0.5.119 shipped
it opt-in and v0.5.120 turned it on, once the regression that had held it back
turned out to be a harness bug. See §§ 7.rrrr and 7.tttt, and `--pace` below
for how the row length is measured against the original.

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
`cmp = bound × multiplier − 2` and the excursion then gives
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


#### The other form: an LFO table (2 files)

The command-table engine — Hollywood or Bust and Chicken Song — carries no byte
in that format at all, which is why both stayed at `bend` 0.00x after the flag
landed. Its parameter byte (the same record `+5`) is a pair of nibbles: the
high one picks **one of four LFO tables**, the low one says how many units of
`interval >> 4` a single table step is worth. The player walks the table one
entry per frame, `$FF` wrapping to the start, and applies

```
table[i] * count * (interval >> 4)
```

as an absolute offset from the note's own frequency. Both files carry the same
four tables and all four are triangles — `0 1 0 -1`, `0 1 2 1 0 -1`,
`0 1 2 1 0 -1 -2 -1`, `0 1 2 3 2 1 0 -1 -2 -1` — which is the only reason a
fixed triangle can stand in for them. The table's **length** is the period and
its **peak** the excursion, so

```
cmp    = length × multiplier / 2 − 2
rshift = log2((cmp + 2) × 2**4 / (2 × peak × count))     rounded in log space
```

Five of Hollywood or Bust's seven vibrato records ask for a ratio that is
already a power of two; two round, the worse of them by a third. The interval
here is `freq(note+1) − freq(note)`, the one *above* the note — exactly what
Goattracker computes — so this mapping does not carry the classic form's 6%
error.

| at `-t 10` | before | after |
|---|---:|---:|
| Hollywood_or_Bust `bend` | 0.00x | **0.41x** |
| Chicken_Song | — | unchanged (nothing it emits falls in the window) |

At `-t 40`, where both files' vibrato instruments are reached, Hollywood or
Bust reads 0.00x → **0.58x** and Chicken_Song 0.79x → **2.07x**. Chicken's
overshoot is not explained by the rounding above (its four reachable records
ask for 1.33x, 1.6x, 1.14x and 0.5x) and is not investigated here; its `bend`
mixes the vibrato with a pre-existing drum-sweep contribution, which is what
already put it at 0.79x with no vibrato emitted at all.

Detection is gated on the parameter split, the table walk and the shift count
all three, and it is consulted **only where the classic form found nothing** —
so it can rescue a file that vibrates not at all and can never disturb one that
already reads. No other corpus file matches the shape (`tests/
test_table_vibrato.py` checks all 95).

#### The half-period both forms are matched against (corrected in v0.5.129)

Simulating `gplay.c:795-801` rather than reading its constants gives a
peak-to-peak of `(cmpvalue + 2) × speed` over a period of `2 × (cmpvalue + 2)`
calls — so the **half-period is `cmp + 2` calls, not `cmp / 2`**. Until
v0.5.129 the classic mapping used the `cmp / 2` reading and emitted
`cmp = 2 × bound × multiplier`, which oscillated at roughly **half** the
player's rate in all 49 files it reaches.

`rshift` did **not** change with the correction, and that is not a coincidence.
The old derivation equated the player's `(bound >> 1) × depth` — which the
player's apply loop only ever *subtracts*, so it is a peak-to-peak — with a
Goattracker *amplitude*. A period twice too long and an excursion convention
off by two cancelled in the shift exactly. Only `cmp` was ever wrong.

**`FIDELITY.md` cannot adjudicate the correction, and it is worth being precise
about why.** No dimension it prints measures an oscillation *rate*:
`melody`/`seq`/`pitch`/`retrig` read which notes are struck, and
`wave`/`adsr`/`pul`/`filt`/`cut` read registers vibrato never touches. It moved
`slides` and `bend` on 30 files — 15 toward the original and 15 away, with
corpus mean `melody` unchanged — and even that movement is second-order rather
than a verdict: the old oscillation drifted more than a semitone before
reversing, so **siddump re-read it as a note change rather than a bend** and
dropped those frames from both counts. One_on_One frame 102 is the site (old
`245C (C#5 BD)`, new `2354 (- 0084)`). What makes the correction right is the
derivation and the gplay simulation, not the table. The LFO-table form was
derived from the simulated semantics from the start and is unchanged.

### `--tie` (the note that should not be struck)

**On by default via `presets.json`.** 64 classic-dialect files carry tied
events.

A listener pointed at pattern `$12` of Commando: *"note E-5 on pos 16 should not
be played as a note, the glide from F#5 should stop at E-5 — the attack is too
strong."* Exactly right, and the trace shows it:

```
          ORIGINAL                  OURS (before)
row 15    2E7A 2E2C 2DDE 41         2F43 2EDE 40 → 09    we close the gate
row 16    2BD6 41   no attack       2BDD 41  * ATTACK
```

**Status bit 5 is a tie flag.** It is the same bit as the envelope cut
(`--cut-release`): `LDA duration,X / AND #$20 / BNE skip` at Commando `$517F`
means *don't close the gate at this note's end*. So the original reaches row 16
with the gate still open, and a note event with an open gate only changes the
frequency — no new attack. The glide lands on E-5 and the vibrato takes over on
the same sounding note. We closed the gate and hard-restarted, manufacturing the
attack.

GoatTracker expresses it in one command. `CMD_TONEPORTA` with parameter **0**:

- `gplay.c:811` — `if (!cptr->cmddata) { cptr->freq = targetfreq; ... }`, an
  instant pitch jump rather than a slide;
- `gplay.c:930` — the hard-restart gate-off is skipped *because* the row's
  command is `CMD_TONEPORTA`;
- `gplay.c:355` — the `firstwave` testbit is skipped for the same reason;
- and it zeroes `vibtime`, so the vibrato restarts on the landing, which is what
  the original does.

It goes on the note **following** the tied event, not on the tied event itself —
the original does attack on the slide row; it is the landing that must not.

On Commando, voice 1's attacks go **511 → 501** against the original's 502, and
the waveform through the landing becomes a continuous `41 41 41 41` matching the
original frame for frame. Across the 64 files:

| | median `retrig` | mean `melody` |
|---|---|---|
| off | 1.008 | 82.3% |
| `--tie` | **0.999** | **84.1%** |

Nineteen files improve on `melody`, five lose. The largest single gain is
**Delta_Mix-E-Load_loader, 6% → 100%** (retrigger 2.133 → 1.067) — it was being
re-struck on almost every note. Chimera 86% → 98%, Confuzion 93% → 99%, Action
Biker's retrigger 1.333 → 0.990. The worst regression is Kentilla, `melody`
95% → 85%, whose retrigger nonetheless improves 1.127 → 1.035; `melody` is a
difflib ratio over a fixed window, so removing attacks can shift its alignment
(see *A score is not a clock* in CLAUDE.md).

### `--cut-release` (the release nibble that never sounds)

**On by default via `presets.json`.** A no-op in the 62 corpus files whose
player has no cut routine.

A listener said pattern 12 of Commando "plays too many notes". The notes were
right — voice 1 matches the original at ratio 1.00 over 60 s, and every byte of
the Hubbard pattern decodes to exactly what GoatTracker shows. What was wrong
was the note *endings*. Found at Commando `$517C`:

```
517F  BD F5 54  LDA duration,X
5182  29 20     AND #$20      ; bit 5 -- the tie flag
5184  D0 15     BNE skip      ; set -> hold, no cut
5186  BD F2 54  LDA counter,X
5189  D0 10     BNE skip      ; not the note's last row yet
518B  BD F8 54  LDA wave,X / AND #$FE / STA $D404,Y   ; gate off
5193  A9 00     LDA #$00
5195  99 05 D4  STA $D405,Y   ; attack/decay = 0
5198  99 06 D4  STA $D406,Y   ; sustain/release = 0
```

**Status-byte bit 5 is a tie flag**, and when it is clear the player destroys
the envelope on the note's final row. So the note stops dead, and the record's
release nibble is never audible. This writer copied that nibble into the
GoatTracker instrument, where it *is* — 1298 of 1723 records carry a non-zero
one. Commando's lead has `SR = $5F`, release `F`: every note of a staccato
figure rang through the gap that should separate it from the next, ~5 frames of
sound where the original has 3 and then silence. The gate-off frame itself was
already correct.

Reach: **Commando is 708 cut notes to 21 tied; across the 72 classic-dialect
files 91% of 53308 notes are cut.**

Gated on the routine being *found*, not assumed — `detect.ENVELOPE_CUT_SHAPES`
requires the gate-clear as part of the shape, because a bare
`LDA #$00 / STA $D405 / STA $D406` also matches an init routine clearing the
chip at startup. 33 files match; 9 more have only the loose shape and are
deliberately not claimed.

**Per instrument, not per file.** The cut is a single write on the note's last
row, so an instrument whose effect routine runs every frame overwrites it and
its release *is* audible. On Commando only records 0, 2, 6 and 8 are cut; the
ones carrying the drum bit hold their envelope across the whole gap. Over the
143 unambiguous instruments of the 33 files with the routine, `effect & $01 == 0`
predicts the cut with **98.6%** accuracy, no false negatives and 2 false
positives (`& $07` scores 86.0%, `== 0` 78.3%).

Measured with the `tail` column over the 30 measurable files:

| | mean `tail` | melody |
|---|---|---|
| off | 64.6% | 78.2% |
| every record (v0.5.200) | 62.1% | 78.2% |
| **gated per instrument** | **97.4%** | 78.2% |

Commando goes 71% → 100%. `melody` is unchanged, so no notes are lost — the
change is entirely in what happens after the gate closes. The sustain nibble is
left alone: it governs the note while it plays, which is not what the cut
destroys.

The middle row is what v0.5.200 shipped, and it was a net regression: applying
the cut to every record destroyed the drums, which a listener heard at once
(Commando 71% → 29%, Zoids 83% → 17%, Rasputin 80% → 20%). It scored 27.6% →
99.2% at the time because the `tail` measure then took the release as a *minimum
over the gap* to the next note, which cannot tell this note's cut from the next
note's setup and so counted every instrument as cut. See § 7.nnn.

**It costs `adsr`, and that cost is the metric's.** The `adsr` column compares
the register pair literally, and those players write the record verbatim at the
attack — `295F` where we write `2950` — so an affected instrument reads as a
mismatch. The nibble it disagrees about is one the SID consults only when the
gate falls, by which point the player has already zeroed it; attack, decay and
sustain are identical on both sides. So the sound is the same and the byte is
not. The generated report states this next to the number, and `tail` is the
column that tracks what the envelope does.

Tied notes (9%) keep no release, since GoatTracker's release is per instrument
where the flag is per note. In the player a tied note never gates off at all,
and our decoder already maps bit 5 to `CMD_TONEPORTA`, which skips
GoatTracker's own retrigger — so the two behave alike.

### `--vibrato-command` (the length gate, expressed exactly)

**On by default via `presets.json`.** A no-op outside the global-triangle
dialect (25 files) and outside `--format gts5`.

That player gates the vibrato on the note's own stored duration and nothing
else:

```
BD F5 54  LDA duration,X
29 1F     AND #$1F
C9 06     CMP #$06         ; Commando: shorter than 6 -> no vibrato
90 1C     BCC out
```

A Goattracker *instrument* cannot say "only notes this long", because
`vibdelay` is per instrument, so v0.5.198 measured the two ways of
approximating it with one number and shipped the less-bad one — `vibdelay 8`,
which suppresses short notes correctly and starts every long one ten frames
late. This is the exact form, and it works because of where `gplay.c` puts the
countdown:

```c
case CMD_DONOTHING:
  if ((!cptr->cmddata) || (!cptr->vibdelay)) break;
  if (cptr->vibdelay > 1) { cptr->vibdelay--; break; }
case CMD_VIBRATO:          // <-- fallthrough target, entered directly
```

The countdown lives *inside* `case CMD_DONOTHING`. A row carrying `$04`
oscillates from the note's first call whatever `vibdelay` holds, and `$04 00`
gives `cmddata = 0`, which still enters the case but adds nothing — a per-note
*damping*. So a long note gets `$04 <speed index>`, a short note gets `$04 00`,
and the gate is reproduced note by note. Hold rows already repeat the note
row's command, which is what keeps the oscillation running to the end of the
note.

The gate needs no unit conversion: `patterns._build_raw_pattern` computes
`wait = b1 & 0x1F` from the same status byte with the same mask the player's
`AND #$1F` uses, so a note occupies `wait + 1` rows and `wait >= gate` is a row
count. It is the one rate-like quantity in the writer that is *not* divided by
the multiplier.

**The threshold is read per file, and it is not always 8.** The constant came
from one player and is right for 20 of the 25; the others compare against 6
(Commando), 5, 4, 4 and 2. Assuming 8 on Commando damped 695 of its 705 notes
and vibrated 10. Its own 6 vibrates 50 — and that number is checkable rather
than fitted: Commando's durations are in units of three frames, so `wait >= 6`
means "24 frames or longer", and voice 1 has 27 notes of 24 frames plus 4 of
30, exactly the 31 the original's trace moves the pitch on.

Measured over 2487 notes of the 25 files, on instruments whose only pitch
movement is the vibrato:

| | note agreement | we miss | we invent | onset (median) |
|---|---|---|---|---|
| `vibdelay 8` (v0.5.198) | 85.5% | 153 | 207 | +10 frames |
| the file's gate as a `vibdelay` | 78.9% | 109 | 417 | +10 frames |
| `--vibrato-command` | **92.1%** | 129 | **68** | **+0** |

Better on both axes at once, which no single `vibdelay` could manage: Commando
97.8% → 100.0%, and Battle of Britain, Crazy Comets, Hunter Patrol, Ninja and
One Man and his Droid all reach 100.0%. The middle row is the warning — the
file's own threshold is an improvement as a *command* and a regression as a
*delay*, because a delay is also doing the suppressing and a lower threshold
gives that up. The instrument keeps its speed-table pointer, so a note this
pass cannot reach (its command column already carrying a portamento, or its
instrument not yet named in the pattern) falls back to the v0.5.198
approximation rather than losing its vibrato: zeroing the pointer scores
higher on the agreement column alone but silences 60 notes that qualify.

No dimension of `FIDELITY.md` measures an oscillation *onset*, so the report
cannot adjudicate this one either — see `--vibrato` above for the same problem
with v0.5.129's period fix.

### `--pulse` (the duty cycle that never moved)

Hubbard has **three** pulse engines: 34 corpus files sweep the width between
two per-record bounds, 21 accumulate into its low byte, and 24 run a triangle
between two bounds fixed in the routine. The flag reads all three. The
per-record sweep is described first; the accumulate engine follows under *The
other engine*, and the triangle under *The third engine*.

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

**The sweep opens at the record's own width, not at a bound** (v0.5.188). The
player reseeds its accumulator from record `+0`/`+1` at each note and sweeps from
there, so the width the record names is the duty cycle every attack is heard on —
and it may legitimately sit *outside* the bounds, in which case the player sweeps
into the band rather than clamping. Trans-Atlantic's lead opens on `$880` with
bounds `$D00`/`$F00`, giving the original a band of `$880`–`$F40`; starting at the
low bound gave 508 of that 1728, and clamping the width into the band gave the
same 508. Keeping it gives **1651**. The fixed-bound triangle engine was given
this treatment in v0.5.174 and this path was not; both now share
`_pulse_triangle`.

In a Goattracker pulse table the accumulate engine is a set to the seeded width,
one ascending leg long enough to cross the low byte, and a jump back to **the set** rather
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

#### The third engine (the triangle with fixed bounds)

**24 corpus files** run a third engine, and in 19 of them it is the `else` of
the bit-`$08` test above — so finding the accumulate engine was never a reason
to stop looking. It is a triangle across the whole 12-bit width, like the
per-record sweep, but its turnaround nibbles are constants in the routine and
its rate byte packs **two** fields. Commando `$524B`:

```
524B  AD 07 55  LDA rate          ; self-modified from record +6 at note fetch
524E  F0 62     BEQ done
5253  29 1F     AND #$1F          ; low five bits: frames between steps
5255  DE 0D 55  DEC counter,X     ; per voice
5258  10 58     BPL done
525A  9D 0D 55  STA counter,X     ; so the period is (rate & $1F) + 1
5260  29 E0     AND #$E0          ; high three bits: the step
526E  79 91 55  ADC record,Y      ; the width lives in the INSTRUMENT RECORD
5277  29 0F     AND #$0F
527A  C9 0E     CMP #$0E          ; the upper turnaround, an operand
527E  FE 10 55  INC dir,X
      ...       descend: the same with SBC, ending CMP #$08
```

A rate of `$44` is therefore 64 every five frames, and a rate of `$1F` is
nothing, thirty-two times — reading it as a plain rate, which is what both
other engines do with the same `+6`, would make a slow sweep frantic and a
static record swept. The bounds are `$08`/`$0E` in all 24 files, which is
exactly why they are read from the two `CMP` operands: a constant that holds
everywhere is indistinguishable from one nobody checked. **Five of the 24 have
no bit-`$08` test at all** and sweep every record, so the gate is honoured only
where it was found; 23 files change bytes, and the 24th (Hunter Patrol) has bit
`$08` set on every record with a nonzero step, so all of them correctly go to
the accumulate engine instead.

Two things carry over and one cannot. The width lives in the instrument record,
shared by every voice sounding it, and nothing reseeds it at note start — the
sweep **free-runs across notes**, where Goattracker reloads a pulse pointer
whenever its instrument is triggered (`gplay.c:375-379`). So the program is
written to start at the record's own width rather than at a bound: that is the
one duty cycle the player is known to open on, and it is what every attack will
be heard on. And a Goattracker pulse speed is a **signed byte**
(`readme.txt:887-889`), so at `-S1` the width cannot move more than 127 a call
where the player moves up to 224. The band still comes out right — the tick
counts are recomputed from the speed actually emitted — but the sweep runs up
to 1.76x slow, and no option can fix that at multiplier 1.

Commando's lead, GT 1, is the example: `$A00` frozen before, `$845`–`$DBA`
after, against the original's `$820`–`$E40`. Note that **`instrmap.py`'s pulse
column could not see this fix** as it stood — it sampled one frame per onset,
and a sweep that restarts with the note is at the same place on every onset
however far it travels. It now reports the band each note covers on both sides,
judged on median travel *within* one note; see § *The instrument map*.

### `--wave-program` (the player's byte-code wave program)

29 corpus files give an instrument a **byte-code program** rather than a plain
waveform, run by an interpreter with three opcodes: `$85` holds (the program's
end), a byte `>= $80` sets a waveform and an absolute frequency, and a byte
`< $80` sets a waveform and subtracts a 16-bit pitch step. It is what carries
Trans-Atlantic's snare — `81 30`, noise at `$30xx`, 43 notes.

Each opcode becomes wavetable entries: one for the absolute form (the pitch
quantised to the nearest semitone, since a wavetable names notes where the
player writes `$D401` directly), one for a `< $80` opcode with a zero operand,
and two where its operand is nonzero — the waveform, then a portamento whose
speed-table entry is the operand itself, taken as `CMD_PORTAUP` with the two's
complement where the player's subtraction is a rise. Needs `--format gts5`.

**One opcode is one frame, and one frame is `multiplier` play calls**, so every
opcode takes a hold entry after it and the program runs at the player's rate at
every `-S`. Until v0.5.235 the emitter refused a multiplier above 1 outright,
which left the option selectable, measured and **inert** for seven of the nine
files that most needed it — they pack at `-S2`, `-S3` or `-S5`. Emitting it
took `onset` to 100% on five files and brought Shockway Rider (404/404) and
Saboteur II (748/753) within 3% of the original's noise-frame count.

An opcode's waveform is copied into the wavetable's left column, where
`$F0`–`$FF` are Goattracker *commands*: Wiz's `$FF` opcode became a jump to row
222 of a 112-row table, which `gt2reloc` refused silently until v0.5.237 routed
the command range through the same `$E0`–`$EF` encoding waveforms below `$10`
already use.

**`$85` does not freeze the last waveform**, which is what this emitter assumed
until v0.5.260. The two opcode kinds write different cells — `>= $80` writes the
one the player copies to `$D404` each frame, `< $80` writes the voice's *stored*
waveform — and the hold reverts to the stored one, i.e. to the last `< $80`
opcode. IK+'s `$08D8` is the proof: its program is `81 11 40 80 80 80 80 80` and
the original plays `11 81 11 40 80 80 80 80 80 40 40 40`, three frames of the
`$40` that opcode 2 stored, where the conversion restored the record's own `$11`
released. Restoring the stored cell instead moves `wave` on 16 files for a mean
**+1.2 pp** (ACE II 83 → 87%, Saboteur II 84 → 88%, Bangkok Knights 40 → 43%).

Where that stored waveform selects nothing — Skate or Die intro and Arcade
Classics both end on `slide $00` — the original goes **silent** for the rest of
the note, and saying so needs `$18` rather than `$E0`: see § 7.bbbbb for why the
packed player never writes the `$E0`–`$EF` range as a waveform.

Off by default; `presets.py --fidelity` selects it per song, and
21 songs carry it in `presets.json`. See §§ 7.fff, 7.kkkk and 7.bbbbb.

### `--sfx-drum` (the drum that was filed as a game sound effect)

Seven corpus files fire a **fixed-pitch noise hit** from the effect byte's bit
`$80`, and it was left unconverted for years on the grounds that it was the
*game's* sound effect — dead code in a rip. It is not. The gate is
`LDA effect / BPL` on the playing instrument's own `+7`, the counter it tests is
that voice's own frame counter (`INC base,X`, written by the player in six of
the seven), and in Trans-Atlantic it fires **226 times in 60 seconds, on the
beat**. See § 7 of the method write-up for the full correction.

```
41 05CE   the note, pulse
81 38CE   noise — frequency HIGH replaced by $38, the note's low byte kept
81 15EB   noise — a second fixed pitch
41 05CE   the note again
```

**The pitch is the point.** `#$38` is an immediate, identical under C-3, E-2,
G-2 and A-2, and `$48` in five of the other six files. The SID's noise is an
LFSR clocked by the frequency register, so noise at the note's own `$05CE`
writes the register and makes *no sound* — which is exactly what shipped in
v0.5.179 before this landed.

A wavetable names notes, not registers, so the pitch becomes the nearest
absolute note: `$3800` → index 68 (`$375C`), inside a quarter-tone, which for
noise nobody can hear. The block is five entries and loops, as the player does:

```
41 00   the instrument's own waveform, at the played note
81 C4   noise at the drum's pitch — the note's SECOND frame
41 00   the note again
03 80   hold for the rest of the period
FF nn   back to the noise
```

**The note comes first, and that is not cosmetic.** Opening on the noise puts
the drum's pitch on the note's own first frame, where siddump names the note,
and the played note never sounds at all — measured, that took Trans-Atlantic's
melody from 94.7% to **50.4%**. Opening on the note keeps both: melody 94.7%,
`wave` 61.1% → 62.4%, and the median noise pitch moves from an inaudible
`$0685` to `$3744` against the original's `$302B`.

**The hit is on the second frame, not at the end of the period** (v0.5.222).
The reason first written down for the measurement above — that the player's
counter is per-voice and free-running, so no wavetable can place the hit — is
wrong: it is zeroed at note start (`LDA #$00 / STA $8934,X`) and the player
fires at `CMP #$01`. The phase is reproducible and note-locked, so the collapse
was an argument against frame 0 and not against frame 1; the drum fired three
frames late for as long as the misreading stood. See § 7 of the method write-up.

Off by default and selected per song by `presets.py --fidelity`. Two files take
it — **Pandora and Thundercats** — and Pandora is the one that has been
auditioned: distinct hits, on the beat, which is what validates the encoding.

**An instrument whose record waveform selects nothing is the drum on its own**
(v0.5.253). `(wave & 0xFE) | 0x01` is `$01` for a `+2` of `$00` or `$01`, and
`$01`–`$0F` are *delays* in a wavetable, not waveforms — `readme.txt` warns
against a delay in an instrument's first step for exactly this reason. Written
literally the instrument set no waveform at all: it inherited noise from
whatever played before and its delay entry applied a *relative* note, so Bangkok
Knights sounded 40 of its 79 noise frames at `freqtbl[0]` = `$0117` where the
drum belongs at `$49E5`.

The conclusion drawn from that was to **decline** such a record, which silenced
the drum instead of mis-pitching it — for the project's life. Nineteen's record
4 is 58 pattern rows and 151 of its original's 267 voice-3 attacks in 60
seconds, and it shipped as `01/00 01/00 01/00 FF/00`: three one-call delays and
a stop. The held byte now goes through the same `$E0`–`$EF` encoding every other
sub-`$10` waveform uses (`gplay.c:527`), so `$E1` writes the `$01` the player
holds between hits:

```
E1 00   gate alone, at the played note      <- the record's own $01
81 C9   noise at the drum's pitch (C#6 = $482D)   <- loop target
E1 00
03 80   ...for the rest of the six-frame period
FF 1D   back to the noise
```

Five corpus files carry such a record and the change reaches exactly those five.
Three of them play one, and none of them moved a dimension down:

| file | melody | seq | retrig | onset | noise |
|---|---|---|---|---|---|
| Nineteen | 77% → **96%** | 78% → 97% | 0.76 → **1.00** | 80% → **100%** | 1502 → 1657 / 1865 |
| Bangkok Knights | 96% | 88% → **97%** | 0.86 → **1.01** | 100% | 1447 → 1543 / 1640 |
| Pandora | 96% → **98%** | 96% → 99% | 0.97 → 1.03 | 86% | 812 → **839** / 877 |

The remaining two carry `+2 $00` in a record **no pattern row names**, so what a
`$00` record's gate should do between hits is still unmeasured — the held frames
gate on, as they do for every other record, rather than on a guess.

**Trans-Atlantic was selected and then vetoed by a listening test**, which is
what `presets.FIDELITY_VETOED` is for. `wave` rose for it and the pitch matched,
and it was still heard as a beep rather than a drum. The snare that file is
actually missing is GT 3's **byte-code wave program** — effect bit `$08`,
pointers at `$116B`, and its first two bytes are `81 30`, "noise at `$30xx`" —
which nothing reads yet. Adding a wrong drum while the right one is absent makes
the tune worse, and no column in the report can see the difference. Vetoes live
in `presets.py` rather than hand-edited into the generated `presets.json`, so the
reason survives the next regeneration; `tests/test_preset_passthrough.py` fails
if a shipped preset still carries one.

#### The snare, and the overshoot that hid inside it (v0.5.203)

`--wave-program` reads that program in the 29 corpus files that carry the
interpreter. It emits nothing for a file whose *gate* — the effect-byte bit
selecting the program — could not be read, because a guessed bit would invent a
program for every record carrying it; until v0.5.227 that silently covered Mega
Apocalypse, whose gate the walk missed by two bytes because it stores the saved
index to zero page where the other 28 store absolute. There are now none.

Reading the program was for a long time not
enough: with it on, the snare *existed* but sounded 670 noise frames against the
original's 387. Comparing **run lengths** rather than totals named both causes at
once (`fidelity.noise_runs`):

```
instrument 0729 (43 notes)   original: 43 runs of 1, 43 runs of 8
                             ours:     43 of 1, 36 of 6, 3 of 30, 2 of 54, 1 of 78
```

The program is `81 30` (noise, 1 frame), two slides under released waveforms
(2 frames), then eight `80` opcodes (8 frames of noise), then hold.

1. **A slide opcode cost two wavetable entries** — the waveform, then a
   portamento command — so the program ran 13 frames where the player's runs 11.
   Everything after was late and the closing burst was truncated to 6 frames. It
   is one entry now, and the two frames of pitch movement are dropped: the frame
   count is what a percussion transient is made of, the movement under a released
   waveform is not.
2. **The program ended holding noise.** The comment claimed GoatTracker "keeps
   the last waveform, as the player does" — the player does not. Its note-end
   routine writes the *stored* waveform with the gate cleared (`LDA $54F8,X /
   AND #$FE`, the same routine as `--cut-release`), so a program ending on noise
   stops sounding noise. Holding it let the burst run into the gap before the
   next note: the 30-, 54- and 78-frame runs. The record's own waveform is now
   emitted before the stop.

With both, the snare's runs came out **identical to the original's** —
`{1: 43, 8: 43}` on each side, 387 noise frames against 387, where without the
program voice 2 sounds none at all.

**Both of those numbers move again in v0.5.217**, and the trade is worth stating
rather than hiding. The program was being emitted from wavetable entry 0, where
the player reaches it only on a note's *second* frame — see
[the first frame](#the-notes-first-frame-belongs-to-the-record) below. Corrected,
frames 0..10 of every note match the original exactly, but our note here is one
frame shorter than the original's, so the burst's last frame no longer fits:
`{1: 43, 7: 36, 8: 7}`, 351 noise frames against 387. A run in the right place
and one frame short, in place of a run of the right length one frame early.

The same correction settles the melody objection below. `melody` used to fall
95% → 85% with the program on, because the program's noise landed on the note's
own attack frame and siddump named 43 notes by the snare's pitch instead of the
played note's; with the record's waveform back on frame 0 the gate edge carries
the played note again and `melody` returns to **95%** (`seq` 86% → 94%) at
unchanged note counts.

The search still scores it as worse, and structurally rather than by a margin:
`fidelity_better`'s `finds_noise` test requires the *reference* to have no
audible noise, and this file has plenty from another instrument — a per-file test
for a per-instrument defect, so a missing snare is masked by a present hi-hat.
So it is recorded in
`presets.FIDELITY_CONFIRMED`, the mirror of the veto above: a listening verdict
that the search disagrees with, kept in `presets.py` with its reason rather than
hand-edited into the generated file. Scoring `finds_noise` per instrument off
`noise_runs` is the real fix and would re-decide every file's toggles, so it
wants its own commit and its own corpus run.

#### It ran at one speed only, and that hid nineteen instruments (v0.5.235)

Until v0.5.235 this emitted nothing at all for a song packed above `-S1`:

```python
if fmt != FORMAT_GTS5 or max(1, multiplier) != 1:
    return None
```

The reasoning was sound — one opcode is one of the player's frames, a wavetable
steps once per *call*, so at `-S2` the program would run twice as fast — and the
consequence was not. Eight of the nine files whose `$01` records the onset
census flags as opening on a noise transient we hold flat carry a wave program,
and seven of them pack at `-S2`, `-S3` or `-S5`. The option was offered to
`presets.py --fidelity`, measured across two corpus searches, and could never be
chosen, because it changed no bytes.

Each opcode now gets a hold entry after it (`_wave_hold_byte`, the same
encoding `_first_frame_lead` uses), so the program lasts the same number of
*frames* at every `-S`, at the cost of a table roughly twice as long — which
nothing starves for, since the caller's budget already reserves five entries for
every later record and the loop already stops on it.

With the option forced on, the noise-frame counts land on the original's:
Shockway Rider 404 against 404, Saboteur II 748 against 753, Kings of the Beach
1975 against 2143, and `onset` reaches 100% on four of them.

**Star Paws is the one that needed the search rather than a forced A/B.**
Forced on over that song's existing preset it collapses — voice 1 keeps every
attack and renames every one, the signature of an absolute pitch landing on the
attack frame. The cause is `--no-test-restart`, which that preset carried: it
owns frame 0, so the emitters leave it alone, the program's first opcode
becomes wavetable entry 0, and at `-S2` that is still inside frame 0. The
search varies all five toggles together and simply drops `no_test_restart`;
Star Paws ships `wave_program` alone at melody 97% (unmoved), `onset` 56% →
78%, noise 944 → 1614. Forcing one option on top of a preset measures the pair.

`Wiz` is the one file of the nine at `-S1`, so it was already emitting the
program; `gt2reloc` writes no `.sid` for the result, with exit code 0 and no
message. Pre-existing, and not about the multiplier.

**One combination that will not convert no longer costs a song its search.**
Four of W_A_R's 31 overflow Goattracker's 255-entry wavetable at `-S4`, the
exception escaped, and the song fell back to the structural defaults — losing
the `two_stage` an earlier search had measured. A candidate that will not
convert is now skipped and named on stderr, like a `.sng` `gt2reloc` refuses;
a song whose search fails outright keeps what the previous run recorded. The
overflow itself is open: above `-S1` a drum record takes six entries and only
its sweep is checked against the budget.

### `--two-stage` (the attack waveform, and the drums that were missing)

In **44 corpus files** the instrument effect byte's bit `$04` is not an arpeggio
but a *second waveform*: an attack waveform held for a per-instrument number of
frames, then the record's own `+2` (IK+ `$E38B`). `detect._find_two_stage` has
read it since v0.5.66 and the writer ignored it, so all 34 played the second
stage from frame one — and a record whose `+2` is `$00` was **silent
altogether**, the attack being the only waveform it ever has.

**Nine of those 44 arrived in v0.5.236, from one line.**
`detect._effect_byte_address` probed `instr_stride == 8`, which switched off
every routine that reads `+7` for the nine corpus files whose records are 16
bytes — the two-stage attack among them. The probe computes record 0's `+7` and
searches for the player's own `LDA base,Y`, so it never needed the stride: the
guard excluded a dialect rather than an error. Rikky's block is
`TWO_STAGE_SHAPE` byte for byte; what differs is that its two bytes live at
record `+9` and `+11` instead of in a table after the records. Forced on, ours
against the original's noise frames: After 8 **218**/210, Mr Meaner **307**/309,
Rikky **270**/264, One on One **765**/744, Off the Cuff **1331**/1358 — five
files within 3% from a standing start of zero, with `onset` reaching 100% on
seven of the nine and `melody` unmoved.

A listener found it: Trans-Atlantic's drums are gone, and the trace agrees —
**0 frames of noise against the original's 1089**. Its GT 2 is `$81` noise for
four frames before its pulse, 226 notes of drum played as a pulse; its GT 4 is
one of the silent ones, 70 notes of nothing.

```sh
python -m h2g song.sid --two-stage --format gts5
```

**Off by default, and that is a measurement not a hedge.** Encoding it was tried
before and cost 82 points of `wave` agreement across 18 files. The obvious
suspect was the startup misalignment fixed in v0.5.175 — a 1–4 frame transient
is exactly what a 3–8 frame offset destroys — so it was re-measured under the
aligned harness and came back the same: −0.6pp mean, Tarzan −14.

What that measurement does not capture is what the cost buys. `wave` is an
agreement percentage, and restoring the transient moves it the wrong way *even
when the transient is right*: Trans-Atlantic gains its 250 missing noise onsets
at exactly the original's per-instrument counts and `wave` falls 71% → 65%.
"We sound no noise at all where the original sounds 1089 frames" is not
something an agreement percentage can say, because there is nothing on our side
to disagree with.

So `presets.py --fidelity` selects it per song on that one-sided criterion —
the original sounds noise and we sound none — and four files take it: **ACE II,
Pandora, Thundercats and Trans-Atlantic**. The search still refuses
any candidate that loses notes.

#### With `--pitch-seq`: a record setting both bits gets both

Bit `$04` and bit `$10` (the arpeggio, `--pitch-seq`) are **sequential,
independent tests on the same effect byte** — `$04` at `$0B9C` writes the
voice's waveform cell and falls straight through to `$10` at `$0BB8`, which
writes its frequency. So a record setting `$14` plays its attack waveform *and*
has its pitch stepped through the arpeggio on the same frames, and with both
options on the converter emits one block carrying both: the attack's frames,
then the sustain stage, then a jump back to the sustain stage looping the cycle
for as long as the note is held.

Only Trans-Atlantic ships both options, and only its record 3 (`0AF8`) is
reached: **0 pitch reversals in a 60 s trace before, 392 after, against the
original's 411**, on unchanged note counts, moving `vib` 0.72x → 0.87x with
every other column of its row identical. Both bits are checked **per record**,
never per file. Requires `--format gts5`; a record whose block will not fit its
wavetable budget falls back to the plain two-stage shape.

See H2G-CONVERSION-METHOD.md § 7.vvv — including why the block must open on a
zero step, which cost Thundercats 11.6 points of `melody` before it did.

#### The note's first frame belongs to the record

**The player writes the record's own `+2` waveform on a note's first frame and
reaches the effect block only from the second.** `--sfx-drum`'s emitter learned
that in v0.5.172; `--two-stage` and `--wave-program` did not, and both put their
mechanism's first entry at wavetable entry 0, so everything they emitted ran one
frame early and the opening frame was lost.

Measured as the modal waveform class over frames 0..7 from each note onset, per
instrument, at **identical note counts on both sides**:

```
Trans-Atlantic GT 5 (+7 $24, the two-stage attack), 24 onsets a side
  ORIGINAL  pulse noise pulse pulse pulse pulse pulse pulse
  OURS      noise pulse pulse pulse pulse pulse pulse pulse
Thundercats GT 4/5/6/10 (+7 $34), 148 onsets each — the same shape
```

Prepending that byte with the gate on makes all of them frame-exact. A record
whose `+2` is `$00` is the exception and takes no such entry: it has no waveform
and no gate on its first frame, so the trace's onset *is* its second frame and
the block is already aligned (`$00`–`$0F` are delays in a wavetable, so there is
nothing faithful to put there in any case). One frame is `multiplier` calls, so
a multispeed file's lead covers that many.

Over the 8 corpus files shipping either option — the only files whose bytes
move — onset-frame agreement goes **66.3% → 71.7%**, none regressing;
Trans-Atlantic's `melody` 85% → 95% and `seq` 86% → 94%; `wave` moves on 7 files
for a mean **+2.1 pp** (Tarzan 64% → 77%, Thanatos 94% → 100%, ACE_II −2 and
Saboteur_II −3). The one number that moves away from the original is
Trans-Atlantic's noise-frame count, for the reason given under `--wave-program`
above. See H2G-CONVERSION-METHOD.md § 7.www.

### `--voice-two-stage` (the same attack, with per-voice parameters)

**One corpus file**, and the first mechanism here whose parameters are indexed
by *voice* rather than by instrument. Ninja's bit `$02` is a two-stage attack
like `--two-stage`'s bit `$04`, but its waveform and duration come from two
static three-byte tables the player indexes by whichever voice it is servicing
(`$CC63` = `11 81 15`, `$CC66` = `04 06 04`, neither ever written).

```sh
python -m h2g song.sid --effects --voice-two-stage
```

A Goattracker wavetable belongs to an instrument, so emitting this needs a map
from instrument to voice, which `tracks.instrument_voices` builds from the
finished orderlists and patterns. An instrument two voices share takes its
busier one — refusing those outright was tried first and is 20 points of `onset`
worse, and the wrong half of the guess here is wrong about a ring-mod bit and
right about the waveform.

Two corrections turn the player's threshold into a number of our play calls,
and neither is the threshold itself: `- 1`, because the note's first call jumps
straight past the effect block, and `× (O + 1) / O`, because the player's outer
gate does nothing at all on one call in four while ours has no such gate. Both
were settled by tracing patched copies of the file rather than by reading the
6502 twice — see H2G-CONVERSION-METHOD.md § 7.aaaaa.

Measured at `-t 60`: `onset` **40% → 80%**, `slides` 986 → 1026 of the original's
1338, `bend` 0.71x → 0.75x, `vib` 0.58x → 0.79x, `wave` 59% → 58%, and `melody`,
`seq`, `pitch`, `retrig`, `noise`, `adsr`, `nrun`, `hold`, `tail`, `pul`, `filt`
and `cut` unmoved. **On by default** (`presets.FIXED`), unlike `--two-stage`:
with it off no corpus file's bytes move and with it forced on every file exactly
`Ninja.sid` does, so a sixth `--fidelity` toggle would double a four-hour search
to settle a one-file question.

#### The same player's bit `$01`: `wave_alternate` with a per-voice table

25 bytes above that block, Ninja reads bit `$01` the way twenty-one other files
read bit `$02` — the voice's waveform alternates every call between the record's
own `+2` and a second table — except that the table is indexed by **voice**
(`$CC60` = `81 81 81`, noise with the gate on) rather than by instrument. Three
of its records set the bit and the conversion emitted no noise for any of them:
`FIDELITY.md` read `noise 0/219` for the file.

It rides `--effects` rather than taking a flag of its own, exactly as the
per-instrument spelling does, and it is gated on the drum block being absent —
bit `$01` is the percussive drum in Warhawk's dialect, which is the established
reading of that bit and wins.

**The branch runs the opposite way round from W_A_R's**, so the note's second
call sounds the alternate here where it sounds the record's own there; that is
`_wave_alternate_entries(alt_first=True)`, read off the branch and confirmed on
the trace (onset frame `41`, next frame `81`). Measured at `-t 60`: `noise` 0 →
387 of the original's 219 and `nrun` "nothing to compare" → **100%**, with
`melody`, `seq`, `retrig`, `onset`, `adsr`, `hold`, `tail` and the rest unmoved
and `wave` 58% → 57%. The overshoot was the file's own tempo defect — an
unread speed gate that played it 1.33× too fast — plus 30 frames on a voice the
original does not reach inside the window. Reading the gate (§ 7.eeeee) took
the same emission to **205 frames against 219**, without touching the emitter.
See H2G-CONVERSION-METHOD.md §§ 7.ccccc and 7.eeeee.

### `--rest-keyoff` (the rest that silences)

A status byte with bit 6 set is a **rest**, and in 21 of the 61 corpus files
whose player tests that bit with `BIT`/`BVS`, the branch it takes silences the
voice — the testbit written into the stored waveform (IK+ `$E138`) or the
envelope pair zeroed (Ricochet `$914A`). The other 40 write no register there
and really do hold. This writer emitted a hold row for all 61.

```sh
python -m h2g song.sid --effects --rest-keyoff
```

What that cost is visible in IK+'s `$08D8`: it sounds its wave program for 6
or 12 frames of an 18- or 24-frame slot and rests for the remainder, and the
conversion played straight through. The rest is an event of its own — the
program length plus the silence after it adds up exactly to the next onset,
and the split varies between notes of the same instrument, which is why it
could never have been a property of the instrument.

19 files' bytes move, exactly the ones detection flags. **Off by default, and
not because it measures badly — because it cannot be measured here at all.** A
Goattracker KEYOFF clears the gate bit and nothing else; `wave` ignores that
bit by construction, `hold` counts frames with a waveform *selected*, and
`adsr` reads registers this does not write. The corpus A/B is flat on 18 of
the 19 files and 3 points of `pitch` worse on the 19th. On the one axis that
does see it — frames where the original has the voice gated off and we do not
— IK+ voice 1 goes 330 → 141 and Arcade Classics voice 1 250 → 89. See
H2G-CONVERSION-METHOD.md § 7.fffff.

### `--no-test-restart` (the silent frame on every note)

Every instrument this tool has ever written carries `$09` in record byte +8, the
waveform Goattracker writes on a note's first frame — testbit plus gate. The
testbit holds the oscillator's phase accumulator and the noise LFSR at zero, so
**that frame makes no sound**, and there is one on every note. Hubbard's players
spend 4273 such frames across 12 of the 83 corpus files; conversions spend
**9179 across 79**, so most of ours are invented.

The flag writes the record's own waveform with the gate on instead, which is
what the player's first frame actually holds — Commando's noise record traces
`81 80 80 80 80`. Anything below `$FE` is assigned to the waveform and forces
the gate on (`gplay.c:355-363`), so one byte buys both a real attack and no
silent frame.

**And it then owns the note's first frame, so the effect emitters must not.**
The packed player does not execute the wavetable on a note's first call — it
jumps straight to the register writes after the init (`player.s:908-911`),
unlike the editor, which falls through to `WAVEEXEC` on the same call. So
`firstwave` is what reaches `$D404` on frame 0 and wavetable entry 0 lands on
frame 1. With the default `$09` that is invisible and the frame-0 lead every
effect block emits is correct; with this flag the lead repeats what `firstwave`
already wrote and pushes the whole effect a frame late. Since v0.5.229
`_first_frame_entry` is gated on it. See H2G-CONVERSION-METHOD.md § 7.ffff.

**It is off by default, and not in `presets.json`'s `always` block, because the
measurement went the other way.** Over the 82 files both settings convert:

| | off | on |
|---|---:|---:|
| mean `melody` | 79.6% | **63.9%** |
| mean `wave` | 69.8% | 73.9% |
| testbit frames | 9179 | 55 |

The frame is what makes a re-struck note retrigger — the same thing
`--no-hard-restart`'s note says about hard restart. Zoids loses 89 points of
melody and Thrust 87. Three files gain 16–17 (`Last_V8` in both rips and
`Trans-Atlantic_Balloon_Challenge`), which is why this is an option rather than
a comment.

One reading was tried and rejected on the way, and it is worth recording because
the number was seductive: a firstwave of `$FF` sets the gate and leaves the
waveform alone, and scored `wave` **99.5%** on Commando — while losing 79 notes.
A per-frame agreement *rewards* losing notes, because fewer attacks mean fewer
transitions to disagree about. `tests/test_first_wave.py` pins that so the
number cannot be rediscovered as a success.

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

#### `--fidelity`: the options no structural score can see

**It searches at `-t 60`, the window `FIDELITY.md` is published at** (v0.5.235;
it was 10 s before). v0.5.195 had already found 10 s too short for the report —
a fifth of the corpus contributed nothing to some columns — and the search kept
its own default for forty versions. Sanxion's 10 s window holds one comparable
instrument and zero noise frames against eight and 1669 at 60 s, so two of the
criterion's five terms had nothing to read; five files lost a `two_stage` that a
60 s A/B scores at `onset` 40–83% → 100% with `melody` unmoved. A full corpus
search now takes about four hours.

Those three criteria are all structural, and some options change no structure at
all — same subtunes, same rows, **same byte count**. `_score` cannot tell them
apart, so putting one in the searched set would tie every time and silently pick
the default. `--no-test-restart` is the first of them.

```sh
python presets.py <sid_dir> -o ../presets.json --fidelity
```

This plays both settings: converts, packs with `gt2reloc`, traces both against
the original with siddump, and records the setting only where it demonstrably
plays better. Seven files take something: `--no-test-restart` for `Last_V8` in
both rips, and `--two-stage` for ACE II, Pandora, Thundercats and Trans-Atlantic.

There are **two ways to win**, both one-sided questions rather than agreement
percentages. Either the setting **plays more of the tune** — a `melody` gain of
at least `FIDELITY_MARGIN`, which is what `--no-test-restart` offers its two
files — or it **sounds a register the original sounds and we do not**, which is
the only thing that can select `--two-stage`, whose files have *no noise at
all* without it. Neither may cost notes.

The first form is scored on `melody` **and guarded on both `sequence` and our
own attack count**, which is not belt and braces. The candidate this search exists for
reached `wave` 99.5% on Commando by deleting 79 notes: any per-frame agreement
rewards losing the events it scores, and `melody` collapses consecutive repeats
so it cannot see a re-struck note lost either. A setting must gain on what is
played *and* drop no note. `FIDELITY_MARGIN` (2 points) keeps difflib noise out.

**What it accepted for those three is a trade, not a clean win**, and the report
shows both halves. `Last_V8` goes from 41 attacks to 79 against the original's
77 — `retrig` 0.53 → 1.03, `melody` 46 → 62%, `seq` 45 → 61%, `wave` 54 → 59% —
but `pitch` falls 91 → 56%, because it played a strict *subset* of ten correct
pitches before and now plays fourteen, nine shared and **five the original never
plays**. `pitch` is a set overlap that ignores order and count, so a conversion
playing less always scores well on it; that is why it does not veto here, and
why the guard is `melody`, `seq` and the attack count. Half the notes missing is
the worse fault, but the five invented pitches are real and a listen is the only
thing that can settle it.

It is **off by default** — it traces four emulations per song and needs
`siddump` and `gt2reloc`, where the structural search is stdlib-only and runs on
every commit. So a plain run **carries forward** whatever `--fidelity` settings
the output file already records, and says how many; `--no-carry` opts out.
Without that, the next routine regeneration would quietly return those three
files to the default and nothing would report it.

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
now wrong in the slides as well. Two rates keep a stated residual — the
drum's own attack, and the rise at a non-power-of-two multiplier — see
H2G-CONVERSION-METHOD.md § 7.bb. The arpeggio alternation was the third until
v0.5.130 (§ 7.mm), which also corrected the attack transient: a wavetable
delay entry is current for `value + 1` calls, not `value`, so the attack had
been running a call long in every multispeed file since the rates were first
divided.

**Stock siddump cannot check this** — it ignores the PSID speed field and
calls the play routine 50 times a second regardless (`siddump.c:309/325`), so
`-S` changes the packed bytes and not the trace. Measured A/B on
`Chain_Reaction`: identical melody, sequence, retrigger ratio and attack counts
with and without it; and the same `.sng` packed at `-S1` and `-S2` traces
byte-identically at a given rate. So for six versions `FIDELITY.md` scored
every `multiplier > 1` row against a file played at half its speed.

**Since v0.5.99 it can.** `python/tools/siddump-rt` is siddump 1.08 plus
`-m<n>`, "playroutine calls per displayed frame", and `fidelity.py` passes each
song its own multiplier — a dump row stays one PAL frame of real time, so the
two sides share a time axis whatever the call rate. The result is not the
uniform lift it was expected to be: **15 of the 33 score better at the packed
rate** (Ricochet 70% → 100%, Flash_Gordon 30% → 75%, Warhawk 68% → 96%) and
**17 score better at 50 Hz**.

That second group was written up in v0.5.99 as "a factor of two out". It is
not, and `--pace` refuted it: **32 of the 33 are closest to the original's
speed at the rate they are packed for**, with errors of 1–33%. `melody` is a
sequence ratio inside a fixed window and the two errors are not symmetric
there — see [`--pace`](#timing-one-file----pace), which is now the mode to
use before saying anything about speed. `--calls-per-frame 1` reproduces the
old numbers. See `python/tools/siddump-rt/README.md`.

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
python fidelity.py <sid_dir> -t 60 --presets ../presets.json -o ../FIDELITY.md
python fidelity.py --pair original.sid ours.sid        # two files you already have
```

It needs `siddump.exe` and `gt2reloc.exe` (`H2G_SIDDUMP` / `H2G_GT2RELOC`
override the paths) and is otherwise stdlib-only. The whole 95-file corpus
takes a few seconds.

For siddump it prefers `python/tools/siddump-rt/siddump.exe` when that has been
built, because a song packed at `gt2reloc -S2` is traced at half speed without
it. It **refuses** such a song on a binary lacking `-m` rather than return the
half-speed dump, which is indistinguishable from a bad conversion — siddump's
option switch has no `default:` case, so an unknown letter is dropped without a
word. `--calls-per-frame N` overrides the rate; `1` reproduces every number
taken before v0.5.99.

Traces set **`$02A6` to 1 (PAL)** since v0.5.110. siddump starts that cell at
0, which is NTSC, and three corpus players branch on it to skip frames in
compensation — tracing without it measures behaviour a PAL C64 never has, and
carried `Phantoms_of_the_Asteroid` as a converter defect for several versions
when its row is simply what its gate says. `--ntsc` reverts. Only four files
read the cell and only they can move; the `-v`-capable build is required for
those four alone.

`--ticks` asks the same question of the **original alone**. `siddump -z` prints
the cycles the play routine burned on each frame; a Hubbard player does
markedly more work on the frame its sequencer steps, so the gaps between those
frames are its row period — no conversion, no packing, no note matching. That
makes it a check on `goatwriter.find_song_speeds` against the player itself,
where `--pace` can only say our row and theirs disagree. It **refuses** rather
than guess: ungated it agreed with `--pace` on 53% of the files both can
measure, and gated on gap regularity it speaks on 31 of 95 and agrees on 18 of
the 18 `--pace` can check. It cannot see a player whose row alternates (3, 3, 2
frames), which is what `--pace` is for.

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

Attacks are not all of it. Seven further columns compare the registers
themselves, each frame-by-frame with the last written value carried forward,
because siddump prints a register only when it changes: **wave** (the
waveform-select nibble), **noise** (frames of noise, ours over the
original's), **adsr** (the envelope pair `$D405`/`$D406`), **pul** (how often
the duty cycle moved, ours over the original's), **pspan** (how wide a band
the duty cycle covers, over the original's), **filt** (frames with a voice
routed into the filter and a passband selected, ours over the original's) and
**cut** (how far the cutoff travels, over the original's travel). The three
counted ones are one-sided on purpose: they answer "did we invent this" or
"did we drop it", which no agreement percentage can say.

`cut` and `pspan` are ratios rather than counts because **a sweep taken in
finer steps writes twice as often and goes exactly as far**. `pspan` was added
in v0.5.174 for that case in its purest form: a Goattracker pulse speed is a
signed byte, so a player step of 224 a frame is emitted as 127 twice, and
`pul` moved from 3/236 to 338/236 on `5_Title_Tunes` for a band that came out
*narrower* than the original's. It excludes a width of `$000` on both sides —
Goattracker writes `$D402/$D403` on every frame from the first call where the
player writes them at its first note, and that leading zero otherwise reads as
a spurious jump on all three voices of every file (Commando: 3.96x for a sweep
that covers less). `$000` is 0% duty, so nothing audible is dropped.

**onset** (instruments whose notes *open* on the original's waveforms). The
column that sees a mechanism emitted one frame out of phase, which two others
read the same register and cannot: `wave` averages per-frame agreement over the
whole window, so a wrong opening frame on a 43-note instrument is a rounding
error against 3000 frames, and `nrun` compares the *lengths* of noise runs and
is position-independent by design, so a run that is right but starts a frame
early scores 100%.

It compares the first four frames from each attack as waveform classes
(`wave`'s own reduction, so the two cannot disagree about what a frame's timbre
is), keyed by the ADSR pair one frame after the attack — `instrmap.py`'s rule,
because the attack frame can still hold a hard restart's envelope. The key is
`$D405/$D406` and the measured value is `$D404`, so the attribution cannot
contain the quantity being attributed, which is the trap `tail` fell into.

**No startup-lag correction, and none is wanted**: each side is read at its own
attack frames, so the packed player's 3–8 frame latency cancels by
construction, exactly as it does for `noise_runs`. The first wiring of this
column passed the lag in anyway and would have manufactured the phase error it
exists to detect.

It reports the *direction*, because a wrong waveform and a right waveform a
frame out have entirely different fixes. Over the corpus that split is
**one-sided: 32 instruments early, 0 late** — which is what a systematic
emitter defect looks like and what noise does not.

**The two per-frame agreements — `wave` and `adsr` — are aligned on the packed
player's startup lag.** gt2reloc's player reaches its first note some 3–8
frames after the original does, and comparing frame *k* to frame *k* charged
that constant to the converter on every file: Commando's `wave` read 65% for a
file whose waveforms agree 92% of the time once aligned, and v0.5.174's drum
fix looked like a 4.6pp regression while taking noise coverage from 49% to 92%.
Corpus-wide the alignment moves mean `wave` 67.0 → 70.2% and mean `adsr`
71.9 → 76.4% — a change to the measure, with no converter change behind it, so
figures either side of v0.5.175 are not comparable.

The lag is **estimated, never fitted**: it is the difference between the two
sides' first attack frames, one number from a defined signal. A shift chosen to
maximise agreement would be a free parameter that can only raise the score. It
was validated against exactly that search over 36 corpus files — it lands on
the fitted optimum for 20 of them and gives a mean `wave` of 77.0% against the
fit's 77.1%, so the search buys a tenth of a point and costs the column its
meaning. A lag past `MAX_STARTUP_LAG` is not a latency (Chimera measures 438
frames, an opening one side does not have) and is clamped and reported rather
than applied. `noise`, `pul`, `pspan`, `filt` and `cut` are one-sided counts or
travels over each side's own window, so they are shift-invariant and are taken
before the alignment.

`FIDELITY.md`'s own legend defines each, a *Filter* section there carries both
sides' raw figures, and *What this run compared* names the registers no column
reads.

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

### Timing one file — `--pace`

```sh
python fidelity.py <one.sid> --pace -t 30
```

Every column of the report is a *what*, never a *when*. `melody` is a
sequence ratio over a fixed window, so it says whether the same notes arrive
in the same order and not whether they arrive at the same time — and the two
errors are not symmetric there. A conversion playing **too fast** reaches past
the end of the window and difflib is charged for the surplus; one playing
**too slow** returns a prefix. So a score can prefer the wrong call rate, and
in v0.5.99 it did: 17 files scored better traced at 50 Hz, the report called
it "a factor of two out", and timing them showed **32 of those 33 are closest
to the original's speed at the rate they are packed for**, with errors between
1% and 33%.

`--pace` measures it directly. It pairs notes with difflib (never by index —
index alignment is meaningful only where the sequences already agree, which is
never true of a file whose speed is in question), takes the ratio of each
consecutive gap, and reports:

* **the median ratio**, not the least-squares fit. A few very long gaps — a
  voice resting through a section — dominate a fit: on ACE II it comes out
  0.727 where the median of the same ratios is 1.509, disagreeing about which
  side is even faster. The fit is printed beside it because the two parting
  company is itself a sign the material has diverged.
* **the interquartile range**. Tight means a row of the wrong length, which
  compresses every gap alike. Spread means the pacing is *irregular* — a gate
  whose interval alternates (ACE II runs 5 frames then 6), or material dropped
  often enough to move a quartile. It is deliberately blind to a single
  omission: one dropped section leaves the quartiles where they were and the
  median still correctly reports the row length as right.
* **the original's row in frames**, derived by dividing our row length by that
  ratio. It comes out the same whichever call rate it is taken at, which is
  what makes it worth printing over a ratio — and it is directly comparable
  with what `goatwriter.find_song_speeds` read out of the player.

That last number is the one that found something. Across the corpus the
speed gate is **under-read**, in both multiplier groups: where it says 2 the
measured row is 2.5–3.0 (Tarzan, Delta, ACE II, Deep Strike, Spellbound,
Chain Reaction), where it says 3 it is 3.5–4.5 (Lightforce, Thanatos,
Pygmies Revenge, Las Vegas Video Poker), where it says 4 it is 4.5–5.33
(Mr Meaner, Human Race), and Rock Tells the Tale reads 5 and plays 6. It is
right for most files — 26 of 43 at multiplier 1 and 10 of 32 at multiplier 2
are within 5% — and where it is wrong the error is a tune-specific factor
between 1.1 and 1.5, never 2. Our own row length is not in question: Ricochet's
gaps land on exactly 8 and 16 frames, so Goattracker honours the tempo as
written.

**That finding is closed.** The mechanism is the counter above the gate, and
[`--skip-gate`](#--skip-gate-the-row-length-the-gate-alone-under-reads)
(v0.5.119, on via `presets.json`) reads it: every file named above as evidence
of the under-read — Tarzan, Delta, ACE II, Deep Strike, Lightforce, Thanatos,
Pygmies Revenge, Human Race — now measures 0% out, packed exactly via the `-S`
multiplier. As recorded in CLAUDE.md at v0.5.248: of 63 timed files, **47 exact
and 50 within 2%**. The paragraph above is kept because it is how the mechanism
was found — a number measured before anything in the players explained it.

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

### `--vice` (the register dimensions at 312 samples a frame)

siddump reads the SID **once per frame**, so a value written and overwritten
inside a frame is not in its trace, and on a multiplier-`m` file the `m - 1`
intermediate play calls leave no mark. `--vice` computes `wave`, `adsr`,
`pul`, `pspan`, `filt` and `cut` from VICE's `dump` sound device instead, which writes
the whole chip state on **every rasterline** — 312 samples a PAL frame. Both
sides are traced that way; tracing only ours would trade one bias for another.

```sh
python fidelity.py <sid_dir> -t 10 --presets ../presets.json --vice
python fidelity.py <file> --vice --vice-reduce last   # what siddump reports
```

**The reduction back to a frame is forced, and it was measured rather than
chosen.** The two sides write at different rasterlines within the frame — an
original's player near the top of the screen, our packed file wherever
`gt2reloc`'s CIA stub lands — so a rasterline-against-rasterline comparison
would report that offset. Shifting one side by an inaudible 0–48 rasterlines
moves each candidate rule by:

| rule | mean sd | worst range | |
|---|---:|---:|---|
| `last` | 0.18 | 2.64 pp | what siddump reports — samples one instant, so a write crossing the frame edge flips it |
| `any` | 0.09 | 1.67 pp | disqualified: reads Deep_Strike at 98.8% where every other rule reads ~75% |
| `majority` | 0.02 | 0.09 pp | stable, but a hard vote |
| **`overlap`** | **0.02** | **0.13 pp** | stable and graded — **the default** |

So the rule the report has always used is the least stable of the four. The
counting dimensions still take the duration-weighted majority, because a count
needs one definite value per frame.

**Shared silence leaves both numerator and denominator.** `wave_compare` drops
a frame both sides spend silent so that a silent voice cannot inflate the
score; at 312 samples a frame the graded form of that rule is to remove the
*overlapping silent share*, `min(share_a(0), share_b(0))`. v0.5.131 removed
the frame only when both whole histograms were silent, which scored a frame
one side flickered through as a full agreement — fixed in v0.5.133. See
H2G-CONVERSION-METHOD.md § 7.nn.

Not the default: two emulator runs a row, at about 1.3x real time each. `vsid`
is found at `--vice-exe` or `H2G_VSID`; a row whose trace fails is marked
`vice_failed` rather than quietly falling back to the coarser one.

### The onset census — `--census`

```sh
python fidelity.py <sid_dir> -t 60 --presets ../presets.json --census ../build/CENSUS.md
```

`onset` reports a rate, and a rate says how much is wrong without saying what
to do about it. `--census` classifies the same comparison — the same two
traces, the same modal reduction, so its `match` count *is* the column's
numerator — by the **kind** of each disagreement, and groups the largest kind
by the source record's effect byte.

| kind | what it means | what to do |
|---|---|---|
| `match` | the four opening frames agree | — |
| `phase` | the original's sequence, one frame out | move the emitter, not its waveforms (§ 7.www) |
| `short` | our note stops selecting a waveform inside the window | a note-*length* difference — `hold` measures it and `--hold-census` classifies it |
| `flat` | we hold one waveform where the original moves | a mechanism we do not render — read the player |
| `invented` | we move where the original holds | emitter quality |
| `partial` / `wrong` | some or no frames agree | emitter quality |

The `flat` group is the work list, and grouping it by the record's `+7` is what
makes it one: the first run of this turned "18% disagree" into `$01 x19,
$04 x11, $80 x6, $0A x6`, and `$0A` was a decoded and emitted mechanism (21
files, 98 records) within the same session. A group whose bit is already
implemented points at *option selection*; one whose bit is not points at the
player. The effect byte comes from the instrument's own name in the converted
`.sng` — the converter's provenance stamp `NN:b5-b6-b7` — so no second
detection pass is involved.

The document goes to the path given and nothing else about the run changes; it
is written beside `-o`/`--json` rather than inside the report, because a report
says how the corpus scores and this says which file to open next.

### The hold census — `--hold-census`

```sh
python fidelity.py <sid_dir> -t 60 --presets ../presets.json --hold-census ../build/HOLDCENSUS.md
```

The same idea for the `hold` column: the same two traces and the same modal
reduction, so its `match` count *is* the column's numerator, with each
instrument classified by **why** its modal note length differs.

The distinction the column itself cannot draw is whether the note is shorter or
its *slot* is. `sound_runs` measures the frames a note keeps a waveform selected
within its own slot, so a note that fills the room it is given is not a
note-length defect at all — what differs is when the next note arrives, which is
a timing question.

| kind | what it means | what to do |
|---|---|---|
| `match` | the same number of frames | — |
| `fetch` | one frame short, equal slot | Goattracker's next-note fetch; `--no-test-restart` removes it |
| `slot` | the length difference *is* the slot's | a timing question — read `--pace` and `retrig` |
| `thin` | fewer than four notes a side | a mode over one note is that note |
| `sparse` | one side plays twice the notes | two modes over different music |
| `gap` | equal total frames, one side holed | the reduction stops at the first hole, not a real difference |
| `short` / `long` | equal slot, equal population, wrong length | the residue that is actually about note length |

Corpus at v0.5.259, 433 instruments across 81 files: `fetch` 211, `slot` 117,
`match` 92, and a residue of nine — `short` 3 and `long` 6. Five of those nine
are one mechanism, a terminating `$00`/`$08` wavetable step the emitters do not
write. See H2G-CONVERSION-METHOD.md § 7.xxxx.

**`fetch` is invisible above `-S3`**, and the report says so in its own
per-rate table: the deficit is a fixed number of play *calls*, and siddump
samples once a frame, so a low count up there is the trace's resolution rather
than the converter's. The same blindness `hold` itself carries.

The document goes to the path given and nothing else about the run changes, as
with `--census`.

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
python fidelity.py <sid_dir> -t 60 --presets ../presets.json -o ../FIDELITY.md \
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

### The instrument map — `instrmap.py`

Every other instrument-level check in this project reads the *player's own
instrument table* and then argues about what its bytes mean. This reads the
other end: what the SID registers actually hold, in the original and in our
conversion, side by side.

```sh
cd python
python instrmap.py <sid-or-dir> -o ../build/instrmap -t 60 --presets ../presets.json
```

One Markdown file per song plus an index. On demand, not a build artefact — it
traces two emulations per song.

The join is **ADSR**. It is a verbatim per-instrument copy of the record (0 of
1635 corpus records differ), so it identifies an instrument where waveform and
pulse cannot: several instruments share a waveform, and a swept pulse has no
single value. Each report gives one row per instrument of ours — what the
original sounds under that ADSR against what we sound — then the original's
per-frame behaviour over the first 8 frames of each note (the spec the `.sng`
should meet), what we actually wrote into the wavetable, and pulse width per
instrument.

**Both full siddump tables are folded into every report, with three instrument
columns appended.** `Ins1`–`Ins3` name the GT instrument sounding on each
voice, `*` marks a note's onset and `.` a voice with nothing yet; an ADSR no
instrument of ours carries gets a lowercase letter, named in a legend. On the
*original's* dump this is what labels Hubbard's trace with our instrument
numbers, so the summary tables can be read down the trace rather than taken on
trust — and the frames our instruments do not cover are visible rather than
counted. The instrument is decided on the frame *after* the attack and held for
the note, for the same reason the tables above are: the attack frame can still
hold a hard restart's ADSR, which is the player's transition and not the
instrument. `--no-dump` leaves the tables out.

**The pulse column reports the band each note covers, not the width at its
onset.** A pulse program restarts with the note (`gplay.c:375-379`), so it is
at the same place on every onset however far it travels afterwards — an
onset-only reading calls a working sweep static, and did, for the whole of
v0.5.174's first draft. The verdict is the *median travel within one note*
rather than the union of the bands across notes: a player sweep that free-runs
visits every phase, so comparing unions would score that difference as
agreement.

It has already found what no score did. Commando's drum was silent because our
first-frame waveform `$09` carries the testbit and the tick cleared the gate on
top of it (v0.5.172, 14 onsets against 0); the alternating rows under one
instrument number are the arpeggio the ear had guessed at; and GT 1's flat duty
cycle turned out to be a third pulse engine nothing had read, in 24 corpus
files (v0.5.174, § `--pulse`).

### The song view — `songview.py`

`instrmap.py` reads what the SID registers *held*; this reads what the `.sng`
*says*. Goattracker's editor can show the same bytes, but it shows a wavetable
as a narrow column of hex pairs and a pattern sixteen rows at a time, so
answering "which entry is instrument 3 opening on, and what does that byte
mean" costs a dozen keystrokes and a page of held state.

```sh
cd python
python songview.py <song.sng|song.sid> -o ../build/song.html --presets ../presets.json
```

One self-contained HTML file, no external assets. Give it a `.sid` and it
converts first, with the song's own preset options (via `fidelity._preset_opts`,
so it cannot drift from what every measurement in the repo is taken with).

It **judges nothing and scores nothing**, which is the point: every metric this
project has added could be, and several were, silently wrong in a way that
changed a decision. A renderer of bytes already on disk has no such failure
mode. Three things it does that the editor cannot:

- **Every pattern carries all three of its identities** — Goattracker's hex
  number (what the editor and a listener say), the converter's post-dedup
  index, and the Hubbard pattern behind it. A listener's "PATT.12" is pattern
  18 is Hubbard's 15, with the orderlist transposing on top; § 7 records three
  separate debugging attempts lost to exactly that confusion.
- **Wavetable entries carry cumulative timing** — a delay entry is current for
  `value + 1` play calls (`gplay.c:697-704`), not `value`, and reading it the
  other way left every multispeed file's attack a call too long from v0.5.82 to
  v0.5.130. The table prints "covers calls 5-7" rather than `02 80`, so the
  arithmetic is visible instead of remembered.
- **Instruments carry their provenance** — `_write_instruments` stamps each
  record `NN:b5-b6-b7`, and byte 7 is the player's own effect byte, so the
  `.sng` alone says which effect bits (`$01` drum, `$04` two-stage, `$08`
  program, `$10` arpeggio, `$20` filter, `$40` fixed pitch, `$80` sfx-drum) the
  source record set. They are decoded into tags on each instrument.

`tests/test_songview.py` checks the parser against `build_sng`'s output and
against the byte-exact `Commando.sng` fixture. The parser is deliberately a
*second* reader rather than a re-use of the writer's internals — one that
shared code could not disagree with the writer, and disagreeing is the value.

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
