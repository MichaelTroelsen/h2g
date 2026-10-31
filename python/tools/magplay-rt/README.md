# magplay-rt — every SID write, call by call

A 30-line console front end to [MagPlaySID](https://github.com/MagnarHarestad/MagPlaySID)'s `MagPlay.Transcribe`, a
cycle-exact C64 (CIA timers, IRQ/NMI, RSID) that records every SID write with its cycle and
the play call it belongs to. `python/heard.py` reads its output.

```
magplay-rt <sid> <seconds> <song, 1-based; 0 = start song> <out.json> [--score <score.json>]
```

## Why, beside siddump

siddump calls the play routine once a frame and samples the registers at the end of it. That
hides two things:

- **the real call rate.** A CIA-timed tune is called on its own clock. MagPlay measured
  Confuzion's period at 16422 cycles, 60 Hz, which is what `call_rate.py` works out.
- **what happens inside a frame on a multispeed side.** Every call of ours is recorded, so
  `heard.py` can read the end state of each frame from the writes themselves.

Checked against our siddump traces at v0.5.621, the end-of-frame states agree on ≥98% of
frames on 183 of 186 traces. The three that do not are Las_Vegas_Video_Poker and
Phantoms_of_the_Asteroid (originals, not traced further) and Skate_or_Die_intro (a held DIGI file).

## Build

Needs the .NET 8 SDK and a MagPlaySID checkout:

```
dotnet build python/tools/magplay-rt -c Release -p:MagPlaySrc=<checkout>/src
```

`MagPlaySrc` defaults to `C:\Users\mit\Downloads\MagPlaySID-main\MagPlaySID-main\src`. The exe
lands in `bin/Release/net8.0/magplay-rt.exe`; `heard.py` looks there, or at `$H2G_MAGPLAY`.

## `--score`: the transcription, for the A/B pages

`--score PATH` also writes MagPlaySID's *transcription* of the tune (`Transcriber.Transcribe`,
the `Score` it returns) as JSON. `python/abpage.py` renders it as a tracker card, "The pattern, as
the original plays it", beside `tracker_card` (ours) on each song page, and caches it as
`build/listen/<name>.original.score.json`. Nothing is emitted that MagPlaySID's own types do not
already hold; this repo's code only flattens them:

| Key | Contents |
|---|---|
| `machine`, `clock_hz`, `calls`, `cycles_per_call`, `tempo`, `funk_tempo` | the recording's clock, from the score |
| `music_share` | the fraction of the tune's register changes the score's music makes (`Report.Music`) |
| `instruments[]` | `number`, `ad`, `sr`, `wave_program`, `pulse_program`, `filter_program` |
| `patterns[]` | `number`, `rows` (a count; the rows themselves are in `voices`) |
| `voices[v][]` | per voice, every row **in the order it plays** (`ScoreTimeline.Rows`): `t` seconds from the first play call, `call`, `pattern`, `row`, `note` (`C-4`, `---` gate off, `+++` gate on, `...` hold; the order entry's transpose is applied), `instr` (0 = keep), `fx[]` (effect labels) |

The instruments are **heard** ones, numbered by the transcriber, not the player's own
instrument records, and its pattern boundaries are its own; the page says so. Wave, pulse and
filter *table steps* and the raw layer are not emitted.

The flag adds to the GPL boundary below without moving it: the transcription is MagPlaySID's output
and the code that writes it here is a call into its public types. `abpage.py` calls the exe when
it is present and otherwise uses a matching cache; with neither it draws no card.

## Licence

MagPlaySID is GPL-2.0-or-later. **None of its code is in this repo**: the project file
references a checkout outside it, and `bin/`/`obj/` are gitignored. A built `magplay-rt.exe`
links MagPlaySID and so is GPL; do not commit or distribute it with this repo. `heard.py`
re-implements MagPlaySID's note-hearing ideas in its own code and only reads the JSON.
