# GoatTracker 2.77 — reference, distilled for H2G

Read out of `GoatTracker_2.77/readme.txt` (2001 lines) rather than inferred from
`gplay.c`. Line citations are `readme:NNN` so any claim here can be checked
against the source text.

**Why this file exists.** This project's knowledge of the target format has been
assembled almost entirely by reading `gplay.c` and `gsong.c` and simulating
them. That is the right instrument for *what the player does*, and it has caught
real defects — but it has also produced three documented mistakes that the
official documentation would have prevented outright (see *What this changes*
below). The C is the authority on behaviour; this document is the authority on
**intent and on the switches that exist**.

---

## 1. What this changes for H2G — read this part first

Three findings here bear directly on work already shipped or in progress.

### 1.1 The slide deficit has a switch: `gt2reloc -R0`

`H2G-CONVERSION-METHOD.md` § 7.uu/§ 7.vv measured every pitch slide delivering
only `(rc-1)/rc` of its encoded movement, matched it to one call per row not
sliding, and said the mechanism was *"consistent, not read out of the binary
that ran"*. **It is documented, and it is a default-on optimization with a flag
to turn it off:**

```
-Rxx Set realtime-effect optimization/skipping (0 = off, 1 = on) DEFAULT=on
```
readme:1227

and the playback model states it plainly — realtime commands `1XY-4XY` run from
tick 1 onward, while **tick 0 has only the one-shot commands** (readme:1009-1030):

| Tick | Actions (tempo 6, gateoff timer 2) |
|---|---|
| 0 | new-note init, orderlist advance, wavetable, **one-shot commands 5XY-FXY** |
| 1 | notes become audible, pulsetable, **wavetable or realtime 1XY-4XY** |
| 2,3 | pulsetable, wavetable or realtime 1XY-4XY |
| 4 | notes fetched, gateoff/hard restart, **no pulsetable**, wavetable or realtime |
| 5 | pulsetable, wavetable or realtime 1XY-4XY |

> "with the commandline parameter /R0 ... you can disable realtime pattern
> command skipping on tick 0" — readme:1039-1040

**So v0.5.150's step scaling by `rc/(rc-1)` is a compensation for something
that can simply be switched off.** The two are not equivalent:
>
> - `-R0` is *exact* — no lost call, so no rounding, and no per-file `rc` needed.
>   Costs rastertime, and changes the packed player for every file.
> - Step scaling is approximate (integer rounding on the speed value) but free.
>
> **`-O0` is now passed at every packing site** (v0.5.189). The default-on pulse
> skipping makes the packed player execute no pulse table on the note-fetch tick,
> so at tempo 3 the duty cycle advances on two calls in three where the player
> advances it every frame — Trans-Atlantic's lead covered 762 of the original's
> 1584 with it on and 1143 with it off. Over the 74 files that pack: mean `pspan`
> 0.61x → 0.65x, mean melody and mean `wave` unchanged to the decimal, no file
> losing melody. readme:1078-1081 already says to disable it for a fast tempo,
> and every row this converter emits is one player tick. It costs raster time on
> real hardware, which is what the optimization is for.
>
> Also note `-Oxx` (readme:1225) is the same kind of switch for pulse skipping,
> default on, and `Filtertable is executed on each tick regardless` while
> `Wavetable is never skipped` (readme:1032-1033) — which is why the drum sweep
> (§ 7.tt, a wavetable effect) never showed this deficit and the slides did.

### 1.2 Vibrato delay is in *ticks*, and `$00` means off

```
Vibrato Delay   How many ticks until instrument vibrato starts. Value $00
                turns instrument vibrato off.
```
readme:725-726

H2G writes a constant `VIBRATO_DELAY = 0x01` for every instrument. The
global-triangle player (§ 7.aaa) gates its vibrato behind a per-voice counter
reaching **8**, so the faithful value is a delay of about 8 ticks, scaled by the
call-rate multiplier — not 1. This is the facility the unimplemented gate needs,
and `$00` being "off" rather than "no delay" is a trap worth noting.

### 1.3 `CMD_TONEPORTA` from a wavetable is legal — confirmed

§ 7.zz corrected § 7.oo's claim that toneportamento is unreachable from a
wavetable. The documentation is explicit about which commands are illegal there,
and `3XY` is not among them:

> "You can execute pattern commands from the wavetable ... Note that commands
> 0XY (do nothing), 8XY (set wavetable pointer) and EXY (funktempo) are illegal
> and should not be used. When executing a command, no wave/note will be changed
> on the same frame." — readme:828-831

So the correction was right, and the remaining obstacle is the one § 7.zz
identified from the C: the target is `cptr->note`, which a wavetable cannot
move.

---

## 2. Song structure

### 2.1 Orderlist (readme:573-598)

- Up to **32 subtunes**; one orderlist per channel per subtune.
- Max length **254** pattern numbers/commands **+ the endmark**.
- `TRANSPOSE` in halftones: up `+0`..`+14`, down `-1`..`-15`.
  **"Transpose is automatically reset only when starting the song, not when
  looping."**
- `REPEAT` (`RX`) repeats the *following* pattern 1-16 times; 16 shows as `R0`.
- Ordering rules, and the editor **halts playback** if they are broken —
  meaning the packed song would play wrong:
  - if both TRANSPOSE and REPEAT precede a pattern number, **TRANSPOSE first**;
  - **the last thing before the RST endmark must be a pattern number.**

Byte values (readme:1374-1378): `$00-$CF` pattern, `$D0-$DF` repeat,
`$E0-$FE` transpose, `$FF` RST followed by the restart position byte.

### 2.2 Patterns (readme:600-637)

- Single-channel, variable length, **up to 128 rows**, **208 distinct patterns**.
- Row = note, instrument (`$01-$3F`, `$00` = no change), command `$0-$F`, databyte.
- Highest note in a pattern is **G#7**; the top three (A-7..B-7) need transpose.
- Special notes: `...` rest, `---` key off (clear gatebit mask), `+++` key on.
- **"The actual state of the gatebit will be the gatebit mask ANDed with data
  from the wavetable. A key on cannot set the gatebit if it was explicitly
  cleared at the wavetable."**
- **No "databyte $00 means reuse last databyte"** behaviour, unlike Protracker.

Stored form (readme:1426-1434): note `$60-$BC` = C-0..G#7, `$BD` rest, `$BE`
keyoff, `$BF` keyon, `$FF` pattern end; then instrument, command, databyte.

### 2.3 Pattern commands (readme:639-698)

| Cmd | Meaning |
|---|---|
| `0XY` | Do nothing; databyte always `$00`. **Stops a running realtime command.** |
| `1XY` | Portamento up — XY indexes a 16-bit speedtable value |
| `2XY` | Portamento down — likewise |
| `3XY` | **Toneportamento** — glide until the target note is reached; `$00` = tie (jump instantly) |
| `4XY` | Vibrato — speedtable: left = speed (ticks to direction change), right = depth |
| `5XY` | Set attack/decay |
| `6XY` | Set sustain/release |
| `7XY` | Set waveform register (ineffective if a wavetable is driving the waveform) |
| `8XY` | Set wavetable pointer; `$00` stops wavetable execution |
| `9XY` | Set pulsetable pointer; `$00` stops |
| `AXY` | Set filtertable pointer; `$00` stops |
| `BXY` | Set filter control — X resonance, Y channel bitmask; `$00` filter off |
| `CXY` | Set filter cutoff |
| `DXY` | Master volume to Y when X is `$0`; otherwise XY goes to the timing mark at playeraddress+`$3F` |
| `EXY` | Funktempo — speedtable entry, alternating left/right per row, **all channels** |
| `FXY` | Set tempo — `$03-$7F` all channels, `$83-$FF` current channel only (subtract `$80`); `$00-$01` recall funktempo |

Two rules H2G depends on:

- **"If the command is not 1XY-4XY, instrument vibrato will be active."**
  (readme:694) — so emitting a portamento *suppresses* the instrument vibrato on
  that row.
- **"the one-shot commands 5XY-FXY allow the previous 1XY-4XY command or
  instrument vibrato to continue underneath them"** (readme:696) — but `0XY`
  kills it (readme:1076).

### 2.4 Instruments (readme:700-771, stored form readme:1389-1399)

Nine parameters, stored in this order (+9 is a 16-byte name):

| | Field | Notes |
|---|---|---|
| +0 | Attack/Decay | `$0` fastest, `$F` slowest |
| +1 | Sustain/Release | sustain `$0` silent..`$F` loudest; release like A/D |
| +2 | Wavetable pos | `$00` stops wavetable execution ("not very useful") |
| +3 | Pulsetable pos | `$00` leaves pulse execution untouched |
| +4 | Filtertable pos | `$00` leaves filter untouched |
| +5 | Vibrato param | speedtable index, as command `4XY` |
| +6 | **Vibrato delay** | **ticks until instrument vibrato starts; `$00` = off** |
| +7 | HR/Gate timer | ticks before note start for fetch/gateoff/hard restart. **At most tempo-1**; `$80` disables hard restart, `$40` disables gateoff |
| +8 | 1st frame wave | usually `$09` (gate+test). `$00`/`$FE`/`$FF` = leave waveform, and set gate off / on / unchanged |

- **"In case of illegal (too high) gateoff timer values, the song playback is
  stopped."** (readme:738)
- **Legato**: gate timer bit `$40` set (no hard restart/gateoff) *and* 1st frame
  wave `$00` → no first-frame waveform, gate untouched; wave/pulse/filter
  pointers and ADSR still initialise (readme:767-771).
- Instrument **63** doubles as the song's startup default tempo via its
  Attack/Decay, if otherwise unused (readme:1083-1086).

---

## 3. Tables

All four tables share the shape: left side drives, right side parameterises
(readme:776-778). **"you should never jump directly onto a table jump command
(FF)"** — undefined results (readme:780-782).

Stored form (readme:1404-1410), repeated for wave, pulse, filter, speed: one
length byte `n`, then `n` left bytes, then `n` right bytes.

### 3.1 Wavetable (readme:787-831)

Left side:

| Range | Meaning |
|---|---|
| `00` | leave waveform unchanged |
| `01-0F` | **delay this step by 1-15 frames** |
| `10-DF` | waveform values |
| `E0-EF` | inaudible waveform values `$00-$0F` |
| `F0-FE` | **execute command `0XY`-`EXY`**, right side is the parameter |
| `FF` | jump; right side is the position (`$00` = stop) |

Right side: `00-5F` relative notes, `60-7F` negative relative notes, `80` keep
frequency, `81-DF` absolute notes C#0-B-7.

- **"Wavetable delay or no wavechange should not be used in the first step of
  instrument wavetable. Otherwise, missing notes may be caused."** (readme:819)
  — but it is allowed when jumped into with `8XY`.
- Delay or a no-frequency-change step is what lets realtime commands and
  instrument vibrato run *alongside* the wavetable (readme:824-826).
- Illegal from a wavetable: `0XY`, `8XY`, `EXY` (readme:829-830).

### 3.2 Speedtable (readme:945-992)

**Shared by vibrato, portamento and funktempo. No jump commands.**

| Use | Left / right |
|---|---|
| Vibrato | left = ticks until direction changes (speed); right = value added to pitch per tick (depth) |
| Portamento | 16-bit value added per tick; left MSB, right LSB |
| Funktempo | two 8-bit tempos, alternated per row, left first |

**The note-independent form** (what H2G calls `SPEED_NOTE_RELATIVE`):

> "For both vibrato and portamento, if XX has the high bit ($80) set, note
> independent vibrato depth / portamento speed calculation is enabled, and YY
> specifies the divisor (higher value -> lower result and more rastertime
> taken)." — readme:961-963

Worked examples from the text: `83 04` = "speed $03, note-independent depth
enabled, depth divisor 4 rightshifts (division by 16)"; `80 01` =
"note-independent speed enabled, speed divisor 1 rightshift (division by 2)".

Old-style conversions: portamento `00 20` ↔ old parameter `$08` (`4 × $08`), so
the stored 16-bit step is **four times** the old pattern-column value — which is
the `value * 4` H2G's `build_speed_table` uses.

### 3.3 Tempo floor

**"Normally tempo 3 is the fastest you can use. However, by using the funktempo
command you can get tempo 2"** — needs a `02 02` speedtable entry, gateoff timer
1 in every instrument, and pulse-optimization skipping disabled (readme:1078-1081).

---

## 4. `GT2RELOC.EXE` options (readme:1204-1232)

```
-Axx ADSR for hardrestart (hex)          DEFAULT=0F00
-Bx  buffered SID writes                 DEFAULT=disabled
-Cx  zeropage ghost registers            DEFAULT=disabled
-Dx  sound effect support                DEFAULT=disabled
-Ex  volume change support                DEFAULT=disabled
-Fxx custom SID clock cycles/sec (0=default)
-Gxx pitch of A-4 in Hz (0 = default frequencytable, close to 440Hz)
-Hx  store author info                    DEFAULT=disabled
-Ix  optimizations                        DEFAULT=enabled
-Jx  full buffering                       DEFAULT=disabled
-Lxx SID memory location (hex)            DEFAULT=D400
-N   NTSC timing
-Oxx pulse optimization/skipping          DEFAULT=on
-P   PAL timing                           (DEFAULT)
-Rxx realtime-effect optimization/skipping DEFAULT=on     <-- see 1.1
-Sxx speed multiplier (0=25Hz, 1=1x, 2=2x) DEFAULT=1
-Vxx finevibrato conversion               DEFAULT=on      <-- affects vibrato depth
-Wxx player memory location highbyte      DEFAULT=1000
-Zxx zeropage location (hex)              DEFAULT=FC
```

`-Gxx` is worth noting against `sidfile.find_freq_table`'s **detune** finding:
four corpus files carry NTSC-tuned tables that no `.sng` note number can
express, and this is the switch that could — at the cost of retuning the whole
file.

`-Vxx finevibrato` is unexplained in the readme beyond its name; it is on by
default and plausibly interacts with the vibrato depth mapping, so it belongs on
the list of things to check before trusting a depth comparison.

### Packing limits

- **"Each pattern row can be 0-4 bytes packed, and the total amount of bytes per
  one pattern may not exceed 256"** — patterns longer than 64 rows may fail
  relocation for being too complex (readme:1242-1244). H2G slices at 94 and 128.
- Tables overflowing past row 255 without a jump is a hard error (readme:1246).
- The relocator removes unused patterns, instruments, table entries,
  self-contained duplicate table parts, and unneeded player code
  (readme:1249-1254).

### Calling the packed player

```
LDA #subtune   ; from 0
JSR start      ; init
JSR start+3    ; play one frame
```
readme:1261-1268

---

## 5. Editor keys worth knowing (readme:318-560)

General: `F1` play from start, `F4` stop & silence, `F5` pattern editor,
`F6` song editor, `F7` instrument/table editor, `F8` songname.

| Keys | Action |
|---|---|
| `SHIFT+Q` / `SHIFT+A` | transpose halfstep up / down |
| `SHIFT+W` / `SHIFT+S` | transpose octave up / down |
| `SHIFT+F4` | **mute current channel** |
| `SHIFT+F5` / `SHIFT+F6` | decrease / increase **speed multiplier** |
| `SHIFT+F7` | edit hard-restart ADSR |
| `SHIFT+SPACE` | play from cursor |
| `SHIFT+RETURN` | convert an old-style portamento/vibrato/funktempo parameter **into a speedtable entry** |
| `SHIFT+H` | calculate a "hifi" left/right-shifted speedtable entry |
| `SHIFT+L` | convert limit-based modulation steps to time-based |
| `SHIFT+O` / `SHIFT+P` | shrink / expand pattern (÷2, ×2) |
| `SHIFT+J` / `SHIFT+K` | join with next pattern / split at cursor |
| `-` / `+` (song editor) | insert transpose down / up command |

**Trap:** `SHIFT+Q/A/W/S` transpose *notes* in the pattern editor but transpose
**speedtable portamento speeds** in the table editor (readme:521-522). Same keys,
different target.

For listening tests, the useful trio is `SHIFT+F4` to solo a voice, `-`/`+` in
the song editor to shift one channel's pitch by a constant, and
`SHIFT+F5`/`SHIFT+F6` to find the true speed by ear.

---

## 6. Things this document does **not** settle

- **`-V` finevibrato's actual arithmetic.** Named only.
- **Whether `-R0`'s rastertime cost is acceptable** for the corpus, and whether
  turning it on would change `pack_multiplier`'s arithmetic.
- **The 6581 vs 8580 divergence** on combined waveforms (readme:811-812) —
  relevant to any waveform comparison, and not modelled anywhere in H2G.
- **Sound-effect and ghost-register modes**, which change the player's SID
  writes and so would change what a register trace sees.
