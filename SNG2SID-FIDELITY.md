# Packing `.sng` to `.sid` from the command line, and using it as a fidelity test

**Question:** GoatTracker's **F9** packs a loaded song into a SID file. Can that be
driven from the command line, so the result can be compared against the original
`.sid` we converted from?

**Answer: yes, and it already ships.** `gt2reloc.exe` is the standalone
packer/relocator — the same code path F9 uses — and it writes `.sid` directly.
The pipeline works end to end today, but only after clearing **two blockers in
our own output**, both found and proven below. With those cleared, **all 78
convertible corpus files pack to SID and 75 of them play**.

Everything here was measured against GoatTracker 2.77
(`C:\Users\mit\Downloads\GoatTracker_2.77`), `siddump.exe` from
`SIDM2\tools`, and the `.sng` files this converter produces.

---

## 1. `gt2reloc` is F9

`readme.txt:326` — `F9  Pack, relocate & save PRG,SID etc.`
`readme.txt:1204` — *"This is a standalone version of the packer/relocator. It
converts .sng files into .bin, .prg or .sid depending on outfiles extension."*

```
gt2reloc <songname> <outfile> [options]
```

The output format is taken from the **extension**, so `out.sid` gets a PSID
header with no extra work. `win32/gt2reloc.exe` is prebuilt — no compilation
needed (which matters: building the GUI needs real SDL 1.2 dev libraries).

Options that bear on fidelity:

| Option | Meaning |
|---|---|
| `-Sxx` | speed multiplier (`0`=25Hz, `1`=1x, `2`=2x…), default 1 |
| `-P` / `-N` | PAL (default) / NTSC timing |
| `-Lxx` | SID address, default `D400` |
| `-Wxx` | player address high byte, default `1000` |
| `-Hx` | store author info |
| `-Ix` | optimisations, default **on** |

The relocator also *removes* unused patterns, unused instruments, unused table
entries and unreachable player code. That is worth knowing before comparing:
the packed SID is deliberately not a byte-level image of the `.sng`.

---

## 2. Blocker 1 — illegal restart position (blocks 26 of 67 outright)

Symptom: `gt2reloc` exits **0**, prints nothing, writes **no file**. This is the
"gt2reloc silently writes nothing for our files" note from earlier work; it is
real, but it was over-generalised — 41 of 67 files did relocate.

Cause, `greloc.c:244`:

```c
if (songorder[c][d][songlen[c][d]+1] >= songlen[c][d])
{
  sprintf(textbuffer, "ILLEGAL SONG RESTART POSITION! (SUBTUNE %02X, CHANNEL %d)", ...);
  ...
  goto PRCLEANUP;          // no file written
}
```

The restart position that follows `$FF` must be **less than the track's length**.
`tracks.py` deliberately emits `[0xFF, 0xFD]` for the version 0/1/2/3 `$FE`
marker — the comment says *"illegal repeat position -> stop"* — which is exactly
what this check rejects. It is a deliberate trick that the editor tolerates and
the relocator does not.

Correlation across our 67 build outputs is essentially perfect:

| | files | containing an out-of-range restart |
|---|---:|---:|
| relocated | 41 | 1 |
| failed | 26 | **26** |

(The single outlier, `Rasputin`, relocates despite four such tracks — presumably
those subtunes are optimised away.)

Proven by patching the restart byte to `0` and re-running:

```
Commando:    original=FAIL   restart-patched=OK (3999 B)
Warhawk:     original=FAIL   restart-patched=OK (3585 B)
Delta:       original=FAIL   restart-patched=OK (5615 B)
Saboteur_II: original=FAIL   restart-patched=OK (2363 B)
Sanxion:     original=FAIL   restart-patched=OK (3363 B)
```

Across the corpus the patch takes relocation from 41/67 to **66/67**
(`Phantoms_of_the_Asteroid` still fails; it has 0 patterns).

**Recommended fix in the converter:** emit a legal restart position. `$FD` was
chosen to mean "stop rather than loop", but Goattracker has no legal way to say
that in an orderlist, and the cost of the trick is that the song cannot be
packed at all. Emitting `0` loops instead — audible difference at the end of a
subtune, versus not being exportable.

---

## 3. Blocker 2 — `--tempo` makes the packed SID silent

With blocker 1 cleared, files pack — and play **nothing**. 0 note events in 20
seconds, across every subtune, for every file tested.

It is not the pipeline: the shipped example `dojo.sng` packs and yields 26 note
events. It is not `--terminate-patterns` either (tested, still silent).

It is **`--tempo`**. Converting the same tune without it:

```
--tempo auto : 0 note events
(no tempo)   : 22 note events at -S2, 44 at -S1
```

`--tempo` works by writing the tempo into **instrument 63's** attack/decay and
padding the instrument list out to 63 entries. The relocator strips unused
instruments and remaps the rest, and that padding does not survive it. The
mechanism is an editor-playback trick; the packer is a different consumer.

**This one does not need a converter fix**, because `gt2reloc` has the right
knob already: `-Sxx`. Use `--tempo` for files you open in the editor, omit it
for files you pack.

---

## 4. The working pipeline

```sh
# 1. convert, WITHOUT --tempo
python -m h2g <song>.sid -o song.sng --max-rows 128 --pack-repeats --format gts5

# 2. legalise restart positions (until the converter does it)
python fixrestart.py song.sng song_fixed.sng

# 3. pack to SID  — this is F9
gt2reloc song_fixed.sng converted.sid -S1

# 4. trace both and compare
siddump original.sid  -a0 -c1 -t60 > a.txt
siddump converted.sid -a0 -c1 -t60 > b.txt
```

Measured over the whole corpus at v0.5.36:

```
relocated to SID: 78 / 78 convertible   (0 failures)
  producing notes in subtune 0: 75      (3 silent)
```

The 3 silent ones are not necessarily broken — a subtune 0 that is genuinely
quiet, or a placeholder subtune, looks the same to this check.

---

## 5. What a comparison can and cannot show

`siddump` emits per-frame SID register state — frequency, note, waveform, ADSR,
pulse, filter, volume — which is exactly the right granularity: it compares what
the chip is *told to do*, independent of pattern structure. Two files that
encode the same music differently still produce the same register trace.

Four things must be reconciled before a diff means anything:

**Tempo.** Currently unresolved and the largest obstacle. Over 10 seconds of
Commando: the original produces **61** note events, ours at `-S1` produces
**30** — about half speed. This matches the known result that the converter
emits one pattern row per player tick while Goattracker's startup default is 6
calls per row. `-S` moves in the wrong direction for this (higher = slower:
`-S1`→30, `-S2`→16, `-S3`→9, `-S4`→7), and `gt2reloc` has no tempo flag, so
there is currently **no way to set the packed player's tempo from the command
line**.

> The clean fix is to stop using instrument 63 and emit `CMD_SETTEMPO` (`$0F`)
> in the first row of the song instead. A pattern command is song data, so it
> survives relocation, and it is how a tracker song would normally carry its
> tempo. That would fix the editor and the packed player at once, and remove
> the "press SHIFT+F6 for 2×" caveat.

**Subtune mapping.** Both sides take `-aN`, but our subtune numbering shifts
when phantom subtunes are trimmed or an over-long one is dropped. Map explicitly
rather than assuming `N == N`.

**Transpose and note spelling.** The original player may transpose in its
orderlist where we bake it into `TRANSUP`; the *absolute* frequency column is
the reliable field, not the note name.

**Relocator optimisation.** `-I0` disables optimisations, which is worth using
for a first comparison so that unused-data removal cannot be confused with a
conversion fault.

A practical scoring approach: parse both dumps, extract per-frame
`(freq, waveform, ADSR)` per voice, align on the first frame where either side
gates a note, and report the fraction of frames that agree. Exact equality is
not the goal — this converter re-encodes rather than emulates, and drops the
digi channel entirely on 9 files.

---

## 6. Sharp edges worth recording

- **`gt2reloc` swallows its own error messages.** It opens `STDOUT`/`STDERR` as
  `fopen("CON", "w")` (`gt2reloc.c:130`), so nothing reaches a pipe or a
  redirect. Worse, the relocator's failure paths use the *screen* routines
  (`clearscreen`/`printtextc`/`fliptoscreen`/`waitkeynoupdate`) which do nothing
  useful headless. A fatal error is therefore indistinguishable from success at
  the shell: **exit code 0, no output, no file.** Always test for the output
  file's existence, never the exit status.
- **To read the real error, use the GUI.** Load the `.sng` in `goattrk2.exe` and
  press F9; the same message is printed on screen.
- **`MAX_FILENAME` is 60** and `gt2reloc` `strcpy`s `argv[1]` into it without
  reducing to a basename, so long paths smash the buffer. Work in a short
  directory (`C:\t\`).
- **Patterns over 256 bytes packed are rejected** (`greloc.c:720`, readme
  §5) — not a problem for us in practice: measured, it does not correlate with
  our failures, because rest runs pack to a single byte.
- `-S0` means 25 Hz, not "half speed".

---

## 7. Recommended converter changes

1. **Emit a legal restart position** instead of `$FD`. Unblocks 26 files for
   packing; the only cost is that a subtune loops instead of stopping.
2. **Move tempo from instrument 63 to `CMD_SETTEMPO` in pattern data.** Fixes
   the silence, survives relocation, and removes the editor's 2× caveat.
3. Consider a `--for-sid` preset that combines the two, so the packing path is
   one flag rather than a remembered list of caveats.
