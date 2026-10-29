# magplay-rt — every SID write, call by call

A 30-line console front end to [MagPlaySID](https://github.com/MagnarHarestad/MagPlaySID)'s `MagPlay.Transcribe`, a
cycle-exact C64 (CIA timers, IRQ/NMI, RSID) that records every SID write with its cycle and
the play call it belongs to. `python/heard.py` reads its output.

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

## Licence

MagPlaySID is GPL-2.0-or-later. **None of its code is in this repo**: the project file
references a checkout outside it, and `bin/`/`obj/` are gitignored. A built `magplay-rt.exe`
links MagPlaySID and so is GPL; do not commit or distribute it with this repo. `heard.py`
re-implements MagPlaySID's note-hearing ideas in its own code and only reads the JSON.
