# GoatTracker and its forks

This converter targets **GoatTracker 2**, so which build a `.sng` is opened in
is not a detail — the forks differ in SID count, file dialogs, key handling and
build system, and at least one difference decides whether a file this project
writes loads at all.

Compiled 7 August 2026. Every claim below was checked against the linked
repository on that date; where something is inference rather than observation
it says so, following the convention in [GOATTRACKER.md](GOATTRACKER.md).

## The family

| | link | base | licence | platform | in one line |
|---|---|---|---|---|---|
| **GoatTracker 2** | [SourceForge](https://sourceforge.net/projects/goattracker2/) | — the original | GPL-2.0 | Linux, Windows | Lasse Öörni's editor; 2.77 is what this repo builds against |
| **LoadTracker** | [libsidplayfp/loadtracker](https://github.com/libsidplayfp/loadtracker) | GT2, synced to 2.77 | GPL-2.0 | CMake + SDL3 | the modernised fork: dual SID, JACK, MIDI, reSIDfp/exSID |
| **GTUltra** | [jpage8580/GTUltra](https://github.com/jpage8580/GTUltra) | GT Stereo **2.76** | GPL-2.0 | SDL, Win32 binaries | Jason Page's; up to **12 SID channels**, detune, palettes |
| **Silver Fork** | [joelricci/goattracker2](https://github.com/joelricci/goattracker2) · [CSDb](https://csdb.dk/release/?id=219300) | GT **2.76** | GPL-2.0 | macOS focus | RaveGuru's macOS keyboard fixes — Insert/Delete on a MacBook |
| **GTMobile** | [2bt/GTMobile](https://github.com/2bt/GTMobile) | GT2-compatible | GPL-2.0 | Android | the tracker on a phone |

## What each one is

### GoatTracker 2 — the baseline

Cross-platform C64 music editor by Lasse Öörni (Cadaver of Covert Bitops),
using Dag Lem's reSID and supporting HardSID and CatWeasel hardware. SourceForge
lists **2.77** as current, updated 16 May 2026, GPL-2.0, Linux and Windows.

This is what `python -m h2g` writes for and what `GOATTRACKER.md` reports five
issues against. Its `gt2reloc` is the packer every measurement in this repo goes
through.

### LoadTracker — the one to watch

> "A fork of goattracker2 with the following features: ported to CMake build
> system, ported to SDL3, scrollwheel support, dual SID support…"

The most actively maintained fork of the five: `pushed_at` was **7 August
2026** — the day this file was written. It is a real modernisation rather than a
patch set:

- **CMake** build and **SDL3**, replacing the hand-rolled makefiles and SDL1
- **Dual SID** support (Alt+M), a rewritten instrument view, better pattern and
  orderlist display during playback
- **JACK** output, cross-platform **MIDI** input
- **reSIDfp** and **exSID** engines beside reSID
- XDG compliance, C64-authentic palette
- Ported to **C++** — the sources are `src/*.cpp`, and the binaries are renamed
  `loadtrk` and `ltreloc` (so scripts that call `gt2reloc` need adjusting)

Small project — 3 stars, 355 commits — but it is the only one of these tracking
2.77 rather than 2.76.

### GTUltra — the most changed

"Extensively modified GoatTracker Stereo (2.76) version", by Jason Page, with
both editor and 6510 player changes. Configurable **3, 6, 9 or 12 SID
channels**, master volume, detune, UI palette presets, stereo HardSID with dual
SID addressing. Documentation is a PDF in the repository rather than a README.

It is the furthest from stock, which cuts both ways: a `.sng` using its extra
channels is not a stock GoatTracker file.

### Silver Fork — the narrow one

GoatTracker V2.76 Silver Fork V1.0, by RaveGuru of Booze Design, released
3 July 2022. Its scope is one platform's ergonomics: Insert via
`option+backspace` or `fn+shift+backspace`, working row delete and `fn+backspace`
Delete on MacBook keyboards, better backspace during filename entry, a guard
against stray characters from some USB keyboards, plus macOS build instructions.
Tested on Intel macOS 11 and later.

If you are on a Mac and the stock build eats your keystrokes, this is the fix.
It changes nothing about the format or the player.

### GTMobile — a different question

An Android SID tracker, GT2-compatible, by 2bt. Not a fork of the C sources in
the sense the others are; listed because it reads the same songs and is the only
way to open one on a phone. 25 stars, pushed 28 July 2026 — the most-starred of
the set.

## The thing that matters for this converter

`GOATTRACKER.md` issue #1 is a buffer overrun in the **GTS2 importer**:
`gsong.c` reads a pattern's length in *bytes* and then walks it as *rows*.

```c
int length = fread8(handle) * 4;          /* length is now a BYTE count */
std::fread(song.pattern[c], length, 1, handle);

for (int d = 0; d < length; d++)          /* ...but d indexes ROWS */
{
  switch (song.pattern[c][d*4+2])         /* so this runs 4x past the end */
```

It matters here because the commands it corrupts on the way past — `$1`–`$4`,
`$0E` — are exactly the portamento commands this converter emits, which is why
[README.md](README.md) requires `--format gts5` for anything you intend to open
in the editor.

**Every fork checked still has it**, in the same shape:

| | GTS2 importer overrun | checked |
|---|---|---|
| GoatTracker 2.77 | present | `src/gsong.c:306` (local 2.77 tree) |
| **LoadTracker** | **present** | `src/song.cpp:607` — ported to C++ unchanged |
| GTUltra | present | `src/gsong.c` |
| Silver Fork | present | `src/gsong.c` |
| GTMobile | not checked | different codebase |

Reproduce with:

```sh
curl -sL https://raw.githubusercontent.com/libsidplayfp/loadtracker/master/src/song.cpp \
  | grep -n -A 12 'length = fread8(handle) \* 4'
```

So the `--format gts5` rule holds against all of them. **No fork in this list is
a reason to relax it.** The GTS3+ loader has no such conversion pass, which is
why gts5 is safe everywhere.

Two smaller consequences for anyone pointing this repo at a fork:

- `play.ps1` and `convert.ps1` invoke `gt2reloc`. LoadTracker renames it
  **`ltreloc`**; the packing flags this project relies on (`-S`, and the
  restart-position behaviour behind `--legal-restart`) have **not** been checked
  against it. Inference, not observation: the reloc source is a port rather than
  a rewrite, so they probably behave the same — but the fidelity harness has
  only ever run stock `gt2reloc`.
- Dual SID (LoadTracker) and 6–12 channels (GTUltra) are outside what this
  converter emits. It writes three voices, because that is what a Hubbard tune
  has.

## Which to use

- **Opening this converter's output:** stock **GoatTracker 2.77** with
  `--format gts5`, which is what every number in `FIDELITY.md` was measured
  through. Nothing here changes that recommendation.
- **On a Mac, if the keyboard misbehaves:** **Silver Fork**.
- **If you want a maintained build, dual SID, or a modern toolchain:**
  **LoadTracker** — and if you hit the GTS2 overrun, it is worth reporting there,
  since it is the fork most likely to take the fix.
- **For more than three SID channels:** **GTUltra**, accepting that the result
  is no longer a stock GoatTracker song.

## Sources

- <https://sourceforge.net/projects/goattracker2/>
- <https://github.com/libsidplayfp/loadtracker>
- <https://github.com/jpage8580/GTUltra>
- <https://github.com/joelricci/goattracker2> · <https://csdb.dk/release/?id=219300>
- <https://github.com/2bt/GTMobile>
