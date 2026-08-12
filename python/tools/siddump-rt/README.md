# siddump-rt — siddump 1.08 with a call rate

SIDDump by Lasse Öörni and Stein Pedersen, vendored at V1.08 (see `readme.txt`
for the authors' BSD licence, which the patch leaves in force), plus one
option.

## Why

`fidelity.py` compares a Hubbard original against our conversion frame by
frame. The original is a 50 Hz VBI tune; **33 of the 83 preset songs are packed
with `gt2reloc -S2`**, which puts a CIA stub at the packed file's *init*
address that reprograms timer A to 50.125 × 2 Hz and leaves the play address
alone (`greloc.c:140` for the stub, `:1616` for `0x4cc7/multiplier`, `:1636`
for the play address). Those files' tempo values are written in units of that
faster call, so at 100.25 Hz they play in real time.

Stock siddump cannot play them that way. It calls the play routine
`seconds × 50` times whatever the PSID speed field says
(`siddump.c:309/325` — the string "speed" does not appear in the file), so
every one of those 33 was traced at half its real rate, and half a tune's notes
fell outside the window. `-S` changed the packed bytes and not one number in
the report; the option was passed for years to a measurement that could not see
it.

## The option

```
-m<value> Playroutine calls per displayed frame, default 1.
```

A row of the dump stays **one PAL frame of real time** whatever the value, so a
multispeed trace lands on the same axis as a single-speed one and the two can
be compared frame for frame. Give the tune's real call rate divided by 50 —
which for anything this repo packs is exactly `gt2reloc`'s `-S`.

`-v<0|1>` sets `$02A6`, the KERNAL's PAL/NTSC flag, before init. Default 0,
which is what a bare emulated machine looks like — and **three corpus players
branch on it to compensate for NTSC**, skipping a frame periodically when it
reads 0. Tracing them without `-v1` measures their NTSC behaviour: Phantoms of
the Asteroid skips one frame in six that a PAL machine never skips, and Las
Vegas Video Poker picks a reload of 2 where PAL picks 4 (verified: its skip
period goes 3 → 5 under `-v1`). A fourth, Skate or Die's intro, uses the flag
to select tuning constants instead, so it changes pitch rather than rate.

Also: the `-z` cycle column now sums the frame's calls instead of reporting the
last one (`initcpu` zeroes `cpucycles`).

`-m` was spelled that way because siddump's `-s` already means "time in
minutes:seconds:frame" and the option switch upper-cases, so `-S` was taken.

## Faithfulness

The stub runs **once**, at init, and does not sit in the play path — so
entering the play routine *n* times per frame is what the CIA does, not an
approximation of it. Two things were measured rather than assumed:

- `-m1` output is **byte-identical** to the shipped `siddump.exe` on
  `Commando.sid`. The patch is inert at the default.
- The same `.sng` packed at `-S1` and at `-S2` traces **identically** at the
  same `-m` (Deep_Strike, Ricochet, Game_Killer). The stub is invisible to
  siddump either way; `-m` is the only knob that moves the rate.

What it still is not: a cycle-accurate machine. Calls inside a frame are run
back to back rather than at timer intervals, and the sampled registers are the
state at end of frame — a gate raised and dropped within one frame is not seen.
Raster timing, badlines and the 0.25% between 100.25 Hz and 2 × 50 Hz are all
outside it.

## The second option: `-w`, watching player memory

```
-w<adr>[,<adr>...]  Dump player memory at these addresses, one column each.
```

Every other column in a siddump row is a **SID register** — what the player
wrote to the chip. That is the right thing to compare two tunes on, and it is
what the whole of `FIDELITY.md` rests on. But it can only ever show what a
wavetable entry *produced*, never *which entry* produced it, because the
pointer lives in the player's own memory. So a conversion whose wavetable holds
exactly the right waveforms in exactly the right order, executed one frame
early, is indistinguishable from one holding the wrong waveforms — the registers
disagree either way, and no amount of staring at them says which.

That question has cost this repo real time more than once (the drum sweep's
depth, the delay entry's `value + 1` length, the vibrato gate). `-w` answers it
directly:

```sh
./siddump.exe song.sid -a0 -t2 -w0fa0,0fa1,0fa2
```

appends a column per address, sampled from the same `mem` and at the same point
in the frame as the SID registers beside them, so a pointer and the register it
produced sit on one time axis. Up to 16 addresses; hex, comma-separated.

**The columns are printed verbatim every frame, never elided to `..`** the way
the register columns elide an unchanged value. A pointer that stops moving is
precisely the signal being looked for, and repeat-elision would hide it.

Inert without the flag: the header, the separator and the per-row text are all
inside `if (numwatch)`, so a run without `-w` produces the same bytes it did
before the patch.

## Build

```sh
make                      # needs gcc; w64devkit's is what this was built with
```

`fidelity.py` prefers `python/tools/siddump-rt/siddump.exe` when it exists and
falls back to the stock binary otherwise. It probes the binary's usage text for
`-m<value>` and **refuses to trace** a multiplier > 1 song without it, rather
than accept the silently-half-speed dump a stock siddump would return —
siddump's option switch has no `default:` case, so an unknown letter is dropped
without a word.

The built `siddump.exe` and `.o` files are not committed; the patched source is.
