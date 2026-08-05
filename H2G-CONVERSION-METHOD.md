# How H2G Converts a Rob Hubbard `.SID` into a Goattracker `.sng`

A detailed walkthrough of the conversion method used by **H2G** ("Hubbard 2
Goattracker", Stilianos "Stello" Doussis, Aug 2005), as reconstructed from the
original VB6 source (`VB6 Sourcecode/h2g.frm`) and the byte-exact Python port in
`python/h2g/`.

Written as **learning material** — the target audience is someone building a
different SID→tracker converter (e.g. SIDM2 / SID Factory II) who wants to
understand a *static* ripping strategy and what it costs.

> **Provenance note.** Everything below marked as fact was read out of the VB6
> source or the verified Python port. The Python port reproduces
> `Commando.sng` byte-for-byte from `Commando.sid`, so the described behaviour
> is empirically confirmed for at least one real tune. Where I am inferring
> *intent* (especially Goattracker's own table semantics, which I did not
> verify against Goattracker's source), I say so explicitly.

---

## 1. The problem: a `.SID` file has no song format

A PSID/RSID file is a ~120-byte metadata header wrapped around **a blob of 6502
machine code**. Inside that blob there is a player routine and some data, but:

- there is no standard layout,
- there is no table of contents,
- the boundary between "code" and "data" is not marked,
- and every composer — often every *tune* — uses a different encoding.

The music exists only as "whatever this particular 6502 routine happens to do
to the SID registers 50 times a second". So any SID→tracker converter has to
pick one of two strategies:

| Strategy | How | Gives you | Costs you |
|---|---|---|---|
| **A. Emulate & capture** | Run the 6502, log all writes to `$D400-$D418` per frame, re-derive musical structure from the register trace | Works on *any* tune, no prior knowledge needed | You get a *performance*, not a *score*. Patterns, instruments and repeats must be re-inferred from a flat frame log. Structure is lossy/heuristic. |
| **B. Locate & re-encode** | Statically find the player's data tables in the blob and translate them into the target format | You get the *actual authored structure* — real patterns, real instrument records, real orderlists. Highly editable output. | Only works on player engines you already know. Zero generalisation. |

**H2G is a pure strategy-B tool.** It never emulates a single instruction. It
is, in the CLAUDE.md's phrasing, a *signature-based disassembly ripper*.

SIDM2 is primarily strategy A (`SIDTracer` + register traces) with strategy-B
elements for specific known players. So H2G is worth studying precisely because
it is the *unmixed* version of the half SIDM2 uses less.

---

## 2. The central trick: use the player's code as an address oracle

This is the single idea worth taking away.

Rob Hubbard did not ship one player. He shipped a *family* of hand-edited
assembly routines — one per game, each relocated and tweaked. So:

- The **addresses** of the data tables differ in every tune. Useless to hardcode.
- The **code that reads those tables** is nearly identical across tunes, because
  it's the same routine copy-pasted and lightly edited.

And in 6502, `LDA table,X` encodes the table's base address **directly in the
instruction's operand bytes**. So:

> Find the instruction that reads the table → read its operand → you have
> the table's address.

You don't need to know where the data is. You need to know what the *code that
touches it* looks like. That's a far more stable fingerprint.

### Worked example — locating the instrument table

`detect.py` tries this pattern first (the "Chimera" fingerprint):

```
BD ?? ?? 99 02 D4 48 BD ?? ?? 99 03 D4
```

Disassembled (`??` = wildcard, matches any byte):

```
BD lo hi     LDA $hilo,X      ; read a byte from some table
99 02 D4     STA $D402,Y      ; -> SID voice pulse width LOW
48           PHA
BD lo hi     LDA $hilo,X      ; read another table byte
99 03 D4     STA $D403,Y      ; -> SID voice pulse width HIGH
```

`$D402`/`$D403` are the SID pulse-width registers. Any code writing those from
an indexed table is, by construction, the **instrument playback routine**. So
the operand of the first `LDA abs,X` — file bytes `i+1` and `i+2` relative to
the match — is the instrument table base address:

```python
addr = data[i + 2] * 256 + data[i + 1]      # 6502 is little-endian
det.instr_start = sid.to_offset(addr)
```

That's the whole method. Everything else is variations on it.

### Why the offsets (`so`) differ per signature

Each fallback signature has an associated `so` ("signature offset") saying
where in the match the operand lives. It is always just "count the bytes".
Example — the Warhawk/IK+ track-table fingerprint, `so = 3`:

```
offset 0:  D0 ??        BNE rel
offset 2:  BD lo hi     LDA trackLO,X     <- operand at offset 3,4   => so = 3
offset 5:  85 ??        STA zp
offset 7:  BD lo hi     LDA trackHI,X     <- operand at offset 8,9   => so + 5
offset 10: 85 ??        STA zp
offset 12: DE ?? ??     DEC abs,X
offset 15: 30 ??        BMI rel
offset 17: 4C           JMP
```

The recurring `so + 5` you see all over `detect.py` is not magic — it is
literally "the *next* `LDA abs,X` operand, five bytes further on", because
`LDA abs,X` + `STA zp` is 3 + 2 = 5 bytes. The LO-byte table and HI-byte table
of a 16-bit pointer array are always read by two adjacent instructions, so one
match yields **both** table addresses.

The same shape appears in the pattern chain with `B9` (`LDA abs,Y`) instead of
`BD`:

```
A8            TAY
B9 lo hi      LDA patternLO,Y
85 ??         STA zp
B9 lo hi      LDA patternHI,Y
85 ??         STA zp
```

---

## 3. Address-space translation (C64 address → file offset)

The operands you extract are **C64 addresses** ($5591, $56F9...). You need
**file offsets** to index the blob. `sidfile.py`:

```python
HLEN = 0x7F
def to_offset(self, addr):
    return addr - self.load_addr + HLEN - 1     # == (addr - load_addr) + 0x7E
```

Derivation:

- The tool assumes a fixed **v2NG PSID header of `0x7C` bytes**.
- It assumes `loadAddress` in the header is 0, meaning the real load address is
  embedded PRG-style as the **first two bytes of the data section**, at file
  offsets `0x7C`/`0x7D`.
- Therefore the first *actual C64 byte* is at file offset `0x7C + 2 = 0x7E`,
  and it lives at C64 address `load_addr`.
- So `offset(addr) = (addr - load_addr) + 0x7E`. ✔ matches the formula.

### The fragility here is worth internalising

H2G **never reads the PSID `dataOffset` field** (at offset `0x06`) and **never
reads the PSID `loadAddress` field**. It hardcodes both assumptions:

```python
load_addr = data[0x7D] * 256 + data[0x7C]   # embedded load address
subtunes  = data[0x0F]                      # low byte of the 16-bit "songs" field
```

For a v1 PSID (`dataOffset = 0x76`) or any file with a non-zero header
`loadAddress`, every extracted address is silently wrong by a constant — and the
tool will happily produce garbage rather than fail. The Python port preserves
this deliberately (fidelity was the goal) and documents it, rather than
"fixing" it.

**Lesson:** if you ever build a strategy-B ripper, parse `dataOffset` properly
and *validate* that your extracted table addresses land inside the data
section. A cheap sanity check (`load_addr <= addr < load_addr + len(data)`)
would have turned a class of silent-corruption bugs into clean errors.

---

## 4. What gets located, and how sizes are derived without any length field

Five detection passes run in `detect.py`, each an
`if not found: try next signature` chain. Real output for `Commando.sid`:

```
Found Instruments at....: $5591
Instruments used........: $D
Found Tracks LO at......: $56F9
Found Tracks HI at......: $56FC
Found Music selector....: $56FF
Found Pattern LO at.....: $5711
Found Pattern HI at.....: $573E
Pattern used............: $2C
Player Trackread version: 0
```

None of these tables has a stored length. Each count is derived by a **different
heuristic**, and each heuristic is a different kind of fragile:

### 4.1 Instrument count — content sniffing

Walk the table in stride 8, checking whether byte `+2` of each record still
looks like a SID **control-register value**:

```python
WAVEFORMS = {0x00, 0x01, 0x09, 0x11, 0x13, 0x15, 0x17,
             0x21, 0x23, 0x25, 0x27, 0x41, 0x43, 0x45, 0x47,
             0x51, 0x53, 0x55, 0x57, 0x81}
```

These are exactly the plausible `$D404` values: waveform bits
(`$10` triangle, `$20` saw, `$40` pulse, `$80` noise) OR'd with gate (`$01`)
and optionally sync (`$02`) / ring (`$04`), plus `$00`, `$01`, `$09`.
The table "ends" where the bytes stop looking like waveforms.

> This is a **type-guess terminator**, not a real one. A tune whose instrument
> table is immediately followed by a byte that happens to be `$41` will
> over-read by one instrument. A tune using a legitimate waveform value not in
> this 20-entry set (e.g. `$31`, tri+pulse+gate) truncates early.

**A large count is not evidence of over-reading** — a trap worth naming,
because it looks like one. Several corpus tunes report 56–59 instruments where
the music plays a dozen, which reads as a runaway terminator. It isn't: those
records are real. Bangkok Knights and Thundercats share **29 byte-identical
8-byte records**, and entries such as `00 81 81 05 63 fd 00 00` recur unchanged
across Bangkok Knights, Thundercats and Knucklebusters — a shared Hubbard
instrument bank appended to the player, of which any one tune uses a subset.
Only 2 of 58 records are all-zero.

The real constraint is downstream: each instrument costs 5 wavetable entries
against a 255-entry table with a one-byte length, so **at most 51 instruments
are representable at all** regardless of how many the table holds. That, not
`MAX_INSTR` (64), is why the writer clamps.

### 4.2 Pattern count — table-adjacency arithmetic

```python
det.pattern_used = (det.pattern_hi - det.pattern_lo) - 1
```

This works **only because the LO-byte array and HI-byte array are contiguous in
memory**: the distance between them *is* the length of the LO array. Elegant,
and free — but it silently produces nonsense the moment a player interleaves
the arrays, pads between them, or orders them HI-then-LO.

### 4.3 Track/orderlist count — from the PSID header

Subtune count comes from the PSID header (`data[0x0F]`), and voices are assumed
to be 3 (or 2 for the "Human Race" player). Indexing:

```python
so   = voice + i * (det.track_voices * 2)
addr = data[det.track_hi + so] * 256 + data[det.track_lo + so]
```

The `track_voices * 2` stride, combined with the track-selector case where
`track_hi = track_lo + track_voices`, implies the memory layout is:

```
subtune 0:  lo[v0] lo[v1] lo[v2]   hi[v0] hi[v1] hi[v2]
subtune 1:  lo[v0] lo[v1] lo[v2]   hi[v0] hi[v1] hi[v2]
...
```

i.e. `voices*2` bytes per subtune, with `track_lo` pointing at the first LO
byte and `track_hi` at the first HI byte of subtune 0. Both indexing schemes
fall out of that one layout consistently.

### 4.4 The track selector overwrite

A separate pass looks for a "music selector" (Rasputin / Human Race
fingerprints). If found, it **overwrites** the `track_lo`/`track_hi` found by
the earlier subsong pass:

```python
det.track_selector = True
det.track_lo = sid.to_offset(addr)
det.track_hi = det.track_lo + det.track_voices
```

Order matters. This is the kind of "later pass silently invalidates an earlier
pass's result" coupling that is very easy to break by reordering code.

### 4.5 Player variant — behavioural, not structural

The fifth pass identifies **which dialect the orderlist bytes are in**, by
fingerprinting the player's *track-reading* loop (`read_track_version`, 0–7):

```
BC ?? ?? B1 ?? C9 FF F0 ?? C9 FE      -> version 0   (Warhawk)
     LDY abs,X / LDA (zp),Y / CMP #$FF / BEQ / CMP #$FE
```

You can read the semantics straight out of the fingerprint: this player
compares each orderlist byte against `$FF` **and** `$FE`, so both are markers
in that dialect. Versions 2, 4, 6 and 7 instead begin with `10 rr` (`BPL`), so
bit 7 of an orderlist byte is a flag rather than part of the pattern number —
which is exactly why those versions carry commands.

The corollary bit the original tool: it grouped version 2 with 0/1/3, which
have **no** `BPL`, and so read version 2's command bytes as pattern numbers.
See §6.

**This is a genuinely nice pattern:** rather than guessing the data format from
the data, fingerprint the *interpreter* and let it tell you which format the
data is in.

---

## 5. The Hubbard pattern format (the actual payload)

This is the part most transferable to any other Hubbard-family work.
Implemented in `patterns.py::_build_raw_pattern`.

A pattern is a byte stream of variable-length events. Each event starts with a
**status byte**:

```
bit 7  0x80  GetNext   -> a second byte follows (instrument or pitch bend)
bit 6  0x40  NoNote    -> no note byte follows
bit 5  0x20  NoADSR    -> reuse ADSR (legato / tone-portamento candidate)
bits 0-4 0x1F  Wait    -> number of extra rows to hold before the next event
0xFF          end of pattern
```

Decoding order:

**1. Optional second byte** (only if `GetNext`):

```python
if b2 & 0x80:                       # pitch bend
    cmd1 = 1 if (b2 & 1) else 2     # GT command $1 / $2 (portamento)
    cmd2 = (b2 & 0x7F) // 4         # parameter, scaled down by 4
    g_instrument = 0
else:
    g_instrument = (b2 & 0x7F) + 2  # instrument number, +2 for GT's 1-based
                                    # table with slot 1 reserved
```

The `+2` is because Goattracker instrument 1 is reserved by H2G as an empty
"Clear Voice" slot, so Hubbard instrument 0 becomes GT instrument 2.

**2. Optional note byte** (if `GetNext` *or* not `NoNote`):

```python
g_note = data[addr + i2]
if g_note >= 0x5C: g_note = 0x5C    # clamp
g_note += 0x60                      # rebase into GT's note range
```

The `+0x60` rebasing is strong evidence that Hubbard's note numbering is a plain
semitone index from the same origin as Goattracker's: GT2 encodes notes as
`$60`–`$BC`, with `$BD` = rest, `$FF` = pattern end. Hubbard `0x00..0x5C` maps
onto `$60..$BC` by a constant bias. Clean 1:1.

**3. Legato → tone portamento.** If `NoADSR` is set and the *same instrument
was used twice in a row*, emit GT command `$3` (tone portamento):

```python
if no_adsr:
    if g_old_instr1 == g_old_instr2:
        cmd1, cmd2 = 3, 0x00
    g_old_instr2 = g_old_instr1
```

This is the tool **inferring a musical intent** ("this is a slide, not a
retrigger") from an encoding detail. Note it takes a two-event history to do it.

**4. "Instrument change with no note" rescue.** If no note byte was read but an
instrument is active, H2G emits a silencing row and then restores state:

```python
if g_note == GT_NO_NOTE and g_instrument != 0:
    g_note = 0x60           # C-0
    resc_instr = g_instrument
    g_instrument = 1        # the empty "Clear Voice" instrument
# ... emit rows ...
if resc_instr != -1:
    g_instrument = resc_instr   # restore for the next event
```

Because Goattracker has no "change instrument without triggering a note" row,
the closest representable thing is "play C-0 with a silent instrument".
A lossy but musically-invisible substitution.

**5. Row expansion (the RLE unroll).** One Hubbard event becomes `wait + 1`
Goattracker rows:

```python
events += [g_note, g_instrument, cmd1, cmd2]     # the real row
if cmd1 == 3: cmd1 = 0                           # portamento fires once...
for _ in range(wait):
    events += [GT_NO_NOTE, 0x00, cmd1, cmd2]     # ...bends repeat
```

Two things worth noticing:

- **A `wait` of 0 is a legitimate one-frame event**, not a no-op. Both the VB6
  original (`h2g.frm:984`) and the first version of this port guarded the whole
  block with `If nWait >= 1`, which silently dropped the note of every zero-wait
  event — 2562 of them across 43 corpus files, and Chimera's pattern `$6` (96
  consecutive one-frame events) converted to nothing at all.

  Settled by disassembling Commando's player rather than by reasoning about the
  format. The wait field is loaded into a per-voice counter (`$54F2,X`) and
  sequenced by:

  ```
  $5078  DEC $54F2,X    ; decrement the wait counter
  $507B  BMI $5086      ; only when it goes NEGATIVE, fetch the next event
  $507D  JMP $5174      ; otherwise keep sustaining
  ```

  `DEC`+`BMI` requires the counter to pass *below* zero, so a stored wait `W`
  occupies **W+1 frames** and `wait == 0` means one frame. The inner
  `If nWait >= 1` at `h2g.frm:996`, which gates only the *hold* rows, is the
  guard that actually belongs; the outer one was the mistake.
- **Command `$3` is cleared after the first row, but `$1`/`$2` are not.** So a
  tone portamento fires once, while a pitch bend repeats on every held row —
  giving a continuous slide. That asymmetry looks deliberate.

Goattracker's in-memory row is 4 bytes — `note, instrument, command, command
value` — which is why every event above appends exactly 4 bytes, and why the
`.sng` row count is `len(pattern) // 4`.

---

## 6. The orderlist / track format and its 8 dialects

`tracks.py::_build_track` walks the raw orderlist byte stream and rewrites it.
Four behaviours, selected by `read_track_version`:

```python
version == 4:                 # ACE 2
    b1 >= 0x80  -> end

version == 5:                 # Battle of Britain / Gremlins / Thing on a Spring
    0xFF        -> end
    everything else -> pattern number  (this player has no command set at all,
                       and unlike 0/1/3 it does not test 0xFE either)

version in (2, 6, 7, 8):      # AWM / Saboteur II / Mega Apocalypse / IK+
    0xFF        -> end, restart 0x00
    0xFE        -> end, restart 0xFD          (version 2 only -- 6/7 don't test it)
    0x80..0xFD  -> transpose (absolute, per voice):
                     one-byte form:  semitones = b1 & 0x7F
                     two-byte form:  semitones = the *following* byte (AWM only)
                   emit 0xF0 + min(semitones, 14)
    <= 0x7F     -> pattern number, emit as-is

version in (0, 1, 3):         # Warhawk / Last V8 / Samantha Fox
    0xFE        -> end, with restart position 0xFD (deliberately illegal = stop)
    0xFF        -> end, with restart position 0x00 (loop to start)
    <= 0xFD     -> pattern number, emit as-is
```

**Version 2 is a correction to the original**, which lumped it in with 0/1/3
and emitted its command bytes as pattern references — they dangled past the end
of the pattern table and were dropped, so the affected voices played
untransposed, and in the two-byte form the operand byte was played as a real
but wrong pattern. Ground truth is Saboteur II at `$F097`:

```
F09C  10 27      BPL $F0C5      ; < $80 -> pattern number
F09E  C9 FF/FE   ...            ; markers
F0A6  29 7F      AND #$7F
F0A8  9D B2 F5   STA $F5B2,X    ; per-voice transpose
F0AB  FE 51 F5   INC $F551,X    ; one byte consumed
F0AE  4C 97 F0   JMP $F097      ; ...and read the next byte
```

`$F5B2,X` is read in exactly one place, `$F125`: `AND #$7F` / `CLC` /
`ADC $F5B2,X`, added to the note before the frequency-table lookup. Goattracker's
`cptr->trans` is the same thing — assigned at `gplay.c:979`, added to the note at
`:927` — so in-range values map exactly. The ceiling is **+14, not +15**: the
transpose range is `$E0..$FE` because `$FF` is `LOOPSONG` (`gplay.c:977` gates on
`< LOOPSONG`, and `gorder.c:70` rewrites a typed `$FF` back to `$FE`). Larger
values are clamped rather than dropped, since dropping one would leave the voice
at the *previous* transpose for the rest of the track.

Two sub-variants share the version-2 fingerprint, told apart by the first
instruction after the marker tests: `$29` (`AND #$7F`, value in the command
byte) in 13 of the 14 corpus files, `$C8` (`INY`, value in the next byte) in
Auf Wiedersehen Monty alone.

**Versions 6 and 7 are the same idiom**, verified at Mega Apocalypse `$4B15` /
`$4B7D` and IK+ `$E09B` / `$E11E` — `BPL` / `AND #$7F` / `STA transpose,X`,
read back as `CLC` / `ADC transpose,X`. So one player dialect covers four
games, and the original's separate "Mega Apocalypse family" branch was wrong
about all of it in four distinct ways:

| Original | Reality |
|---|---|
| `$80-$8F` → `$F0..$FF` | `$8F` is +15, and `$FF` is `LOOPSONG` — the track restarts instead of transposing. 3 in real subtunes, 22 more in Mega Apocalypse's later ones |
| `$90-$EE` discarded | Transposes, lost outright. 16 in real subtunes across six files |
| `$EF-$FE` → negative transpose | The player has no negative form; `AND #$7F` makes these +$6F..+$7E |
| version 5 included | That player has no `BPL` and no `AND #$7F` anywhere — no command set at all |

The version-5 error was the costly one. `Commodore_64_Music_Examples` is the
only version-5 file with bytes ≥ `$80` in a real subtune, and its pattern table
holds 145 entries while those bytes are `$80`–`$90` (128–144) — genuine pattern
numbers, in range, that the transpose branch was destroying. Reading them
correctly is what makes that file convert.

Every track is terminated with a two-byte `[0xFF, restart_position]` pair —
Goattracker's `RST` orderlist command. The stored length byte is therefore
`len(track) - 1`, because GT's count excludes the restart-position operand.

There's also a hard safety valve: once a track reaches 254 bytes the next byte
is forced to `0xFF`, truncating the track rather than overflowing.

> `version == 8` in the Python branch list is unreachable — `detect()` only ever
> produces 0–7 or `0xFF`. Harmless dead condition, carried over from the VB
> `Select Case` (which likewise has an unreachable literal `4` in its second
> case list, because `Case 4` appears earlier and VB takes the first match).

### An undetected/`0xFF` version is a real hazard

`Detection.can_convert` only checks that the track and pattern tables were
found. It does **not** require `read_track_version` to have been identified. So
a file with recognisable tables but an unrecognised player loop reaches
`_build_track` with `version == 0xFF`, where the VB original's `Select Case`
matches no branch — meaning the loop never terminates and never advances its
length counter, reading off the end of its fixed array until VB throws a
runtime error. The Python port deliberately diverges here and raises a clear
`ValueError` instead. This is the one place the port intentionally *doesn't*
reproduce the original.

---

## 7. Instruments: an 8-byte record, and two synthesized tables

Each Hubbard instrument is an 8-byte record. H2G interprets five bytes and
punts on the rest:

| Offset | Used as |
|---|---|
| `+0` | pulse width LOW → pulse table right column |
| `+1` | pulse width HIGH → pulse table left column, OR'd with `$80` |
| `+2` | SID control/waveform value (also the table-end sniff byte) |
| `+3` | AD (attack/decay) → GT instrument byte 0 |
| `+4` | SR (sustain/release) → GT instrument byte 1, clamped: `if sr >= 0xF0: sr &= 0xEF` |
| `+5` | **not interpreted** — printed in the instrument name |
| `+6` | **not interpreted** — printed in the instrument name |
| `+7` | arpeggio-style byte (see below) — *and* printed in the name |

### The instrument-name trick — steal this

```python
name = f"{i + 2:02X}:{b5:02X}-{b6:02X}-{b7:02X}"
```

H2G doesn't understand bytes `+5`, `+6`, `+7`, so it **renders them as hex into
the Goattracker instrument name**, where a human sees them while editing.

That's a genuinely good design move for a reverse-engineering converter: rather
than dropping unknown data on the floor, surface it in the output where the
next person can correlate it with what they hear. Cheap to implement, and it
turns every converted tune into a small research artifact.

### Synthesizing wavetables that don't exist in the source

Hubbard's format here has a single waveform byte and an "arp style" byte — not
a Goattracker-style wavetable. So H2G **fabricates** a 5-entry GT wavetable per
instrument from those two bytes (`_write_wavetable`):

```python
arp_set_keybit = 0 if (arp_style & 1) == 1 else 1
wave = data[base + 2]

out.append(wave)                                  # tick 1: raw waveform
if (arp_style & 1) == 1:
    out.append(0x80 | arp_set_keybit)             # tick 2: noise
else:
    out.append((wave & 0xFE) | arp_set_keybit)    # tick 2: same wave, gate on

tail = (wave & 0xFE) | arp_set_keybit
if (arp_style & 4) == 4:
    out += bytes([tail, tail, 0xFF])              # 2-step loop
else:
    out += bytes([tail, 0xFF, 0xFF])              # settle and stop
```

So each instrument gets: *attack waveform* → *optional noise transient* →
*sustain waveform* → *stop, or loop back for an arpeggio*. In the arpeggio case
the right-hand column carries the arp note and the final entry jumps back to
index `((i + 2) * 5) - 2`, i.e. the 3rd of that instrument's 5 slots, producing
a two-step alternation.

> **Unverified:** I did not check Goattracker's own source for the exact
> semantics of the wavetable right-hand column, so the note/transpose encoding
> (`0x80 - arp_note`, default `arp_note = 0x74` → `0x0C`) is reported as written
> rather than interpreted. The `$FF`-left + `$00`-right = stop convention is
> confirmed by instrument 1's fixed `09 FF 00 00 00` / `00 00 00 00 00` pair.

**Lesson:** when the source format is *poorer* than the target format, you have
to synthesize plausible target-side structure. That synthesis is a creative
choice, not a translation — and it is where converted output stops being
"the original" and starts being "an interpretation of the original".

---

## 8. Impedance mismatch: slicing and re-indexing

Goattracker imposes limits Hubbard's format does not (values from
`goattracker2 src/gcommon.h`):

| Limit | Goattracker | What H2G uses |
|---|---|---|
| Rows per pattern (`MAX_PATTROWS`) | **128** | 94 by default — see below |
| Patterns (`MAX_PATT`) | 208 (`0xD0`) | 208 |
| Orderlist length (`MAX_SONGLEN`) | **254** | aborts at 255, so 254 max |

**94 is not a Goattracker limit** — it is what the 2005 tool chose, and
GoatTracker v2.32 raised `MAX_PATTROWS` to 128. The default stays at 94 only
because the byte-exact fixture encodes it; `--max-rows 128` produces fewer,
longer patterns and therefore shorter orderlists.

Hubbard patterns are unbounded, so long ones must be **split** — and every
orderlist reference to a split pattern must then be **expanded into a run of
references**. Two passes:

```python
# pass 1: one original pattern -> N new patterns
slices = _slice_pattern(events)
track_index.append(list(range(start, len(new_patterns))))

# pass 2: splice, don't substitute
new_track.extend(track_index[b])
```

The `track_index` maps *one* old pattern number to a *list* of new ones. This
is the general shape of the problem: **any time a target-format constraint
forces you to split an object, every reference to it becomes a reference to a
sequence, and the reference-rewriting pass is a separate pass.**

`Commando.sid` hits this 20 times ("Extending Pattern: ...").

### The `$D0` sentinel and its latch

`reindex_tracks` must not re-index bytes that aren't pattern numbers. Since
patterns can't exceed `$D0`, anything `>= 0xD0` is a command:

The original — both the VB6 (`h2g.frm`) and the first version of this port —
used a **sticky** flag:

```python
for b in track:
    if b >= 0xD0 or end_marker:
        end_marker = True          # <-- latches, permanently
        new_track.append(b)
    else:
        new_track.extend(track_index[b] if b < len(track_index) else [])
```

### Why that latch was wrong — and what replaced it

The latch is correct for its intended case: after `$FF` (restart) the *next*
byte is a restart position, not a pattern number, and must pass through
untouched. But it conflates two different questions.

Goattracker's orderlist has three byte classes, and only one of them takes an
operand: `$00-$CF` pattern number, `$D0-$FE` command (repeat / transpose, **no**
operand), `$FF` restart (operand follows). Mega Apocalypse-family transpose
commands (`read_track_version` 5–7) emit `$E0..$FF` — all `>= $D0`. So the first
transpose in a track latched the flag permanently and every pattern number after
it passed through *un-re-indexed*, pointing at the wrong patterns.

It reached further than the transposing players alone: **17 corpus files** carry
mid-track command bytes that were being mis-indexed, including several at
`read_track_version` 0. `Commando.sid` is not among them, which is why the
byte-exact regression test never caught it.

The fix replaces the sticky flag with a single-byte lookahead — only `$FF`
consumes an operand:

```python
for b in track:
    if expect_operand:                  # restart position -- copy verbatim
        new_track.append(b)
        expect_operand = False
    elif b == GT_ORDER_RESTART:         # $FF -- the only byte taking an operand
        new_track.append(b)
        expect_operand = True
    elif b >= MAX_PATTERNS:             # $D0-$FE command; does NOT stop re-indexing
        new_track.append(b)
    else:
        new_track.extend(track_index[b] if b < len(track_index) else [])
```

> **The transferable lesson:** "is this byte a command?" and "does this command
> take an operand?" are two different questions. One boolean answering both is
> the bug.

---

## 9. The `.sng` output layout

`build_sng` writes, in order:

| Section | Bytes |
|---|---|
| Magic | `"GTS2"` (4) |
| Song name | 32, null-padded |
| Author | 32, null-padded |
| Released | 32, null-padded |
| Subtune count | 1 |
| Tracks | `subtunes × 3`, each: 1 length byte (`len-1`) + data |
| Instruments | 1 count byte, then N × (9 data bytes + 16-byte name) |
| Wavetable | 1 length byte, then `left[len]`, then `right[len]` |
| Pulse table | 1 length byte, then `left[len]`, then `right[len]` |
| Filter table | fixed 5 bytes: `02 11 FF 22 01` (an empty table) |
| Patterns | 1 count byte, then per pattern: 1 row-count byte (`len // 4`) + data |

Header is exactly `0x64` = 100 bytes. Instrument 1 is always the hardcoded
empty "Clear Voice" slot; real instruments start at 2. Instrument count is
clamped to 50.

### Write the modern format, not the one the tool was built for

`GTS2` is the 3-table format the 2005 tool emitted. GoatTracker still loads it —
but through a **legacy import path that overruns its own pattern array**
(`src/gsong.c`, GoatTracker 2.77):

```c
length = fread8(handle) * 4;        // length is now BYTES (rows * 4)
fread(pattern[c], length, 1, handle);

for (d = 0; d < length; d++)        // but d indexes ROWS
    switch (pattern[c][d*4+2]) { case CMD_PORTAUP: ... }
```

For a 94-row pattern `length` is 376, so the loop runs to `d = 375` and touches
`pattern[c][1503]` — in a row declared `MAX_PATTROWS*4+4` = **516 bytes**. It
*writes* wherever it finds command `$1`/`$2`/`$3`/`$4`/`$0E`, which are exactly
the portamento commands this converter emits. The modern **GTS3/4/5** loader
has no such conversion loop.

The observable consequence: a GTS2 file loads fine, then **crashes GoatTracker
when you press play**. The same tune written as GTS5 plays.

The format delta is tiny — different magic, plus an empty fourth (speed) table.
Instrument bytes 5 and 6 swap meaning between the two, but this converter emits
`0x00` for both, so nothing needs converting. One extra byte in the file.

> **Lesson worth more than the bug:** the target format had *two* loaders, and
> the one matching the era of the source tool was the broken one. Writing what
> the old tool wrote is not automatically the safe choice. Check whether your
> target still exercises that path.

Note the two-parallel-arrays layout used by both the wave and pulse tables
(`length, left[], right[]`) — that's Goattracker's native table shape, and it's
why `_write_wavetable` writes all left-column bytes for every instrument before
writing any right-column bytes.

---

## 10. Failure modes, ranked by how quietly they fail

Worth reading as a checklist of "what a static ripper gets wrong":

Still open:

1. **Pattern-count arithmetic** (§4.2) → wrong if the LO/HI arrays aren't
   contiguous. No error.
2. **Instrument-count under-read** (§4.1) → a tune using a waveform value
   outside the 20-entry set truncates its instrument table early. No error.
   (Over-read is *not* the common case — see the note in §4.1.)
3. **Undetected player version** (§6) → crash (VB) or clean exception (Python).
   *This one is loud, which is why it's least dangerous.*
4. **No signature match at all** → clean `"NO HUBBARD PLAYER DETECTED"`. Also
   loud, also fine.

Closed since this document was first written — each was exactly the predicted
shape, "wrong output, no diagnostic":

| Was | Now |
|---|---|
| Silent wrong-address corruption; no validation existed | `detect.py` range-checks every extracted table address and logs `*** … ADDRESS OUT OF RANGE ***` (`test_address_validation.py`) |
| The transpose latch (§8) | Replaced by a single-byte operand lookahead; 17 corpus files were affected |
| `wait == 0` events dropped (§5) | Emitted as one-frame events; 2562 restored across 43 files |
| Version 2 grouped with 0/1/3, so its transpose commands were read as pattern numbers (§6) | Decoded as transposes; 6 corpus files played untransposed before, one of them with a wrong pattern spliced in |
| `reindex_tracks` split commands from pattern numbers at Goattracker's `$D0`, whatever the dialect | Split at `command_floor(version)`. Versions 0/1/3 have no command but `$FF`, so a pattern number of `$D0`–`$FD` was being emitted verbatim as a repeat or transpose — losing the reference *and* inventing a command. 146 bytes across 7 files |

The pattern is stark: **the failure modes that produce no diagnostic are the
dangerous ones, and they all stem from unvalidated inference.** Every one of
them was caught by a cheap assertion the original tool simply doesn't make —
and none was caught by the byte-exact fixture, because a fixture only tests the
one file it encodes.

Also note the quirk preserved deliberately in `_slice_pattern`: a pattern whose
event stream is an *exact* multiple of 376 bytes produces one extra zero-length
trailing pattern, which is then referenced by the orderlist. Almost certainly
unintended in the original; reproduced for byte-exactness.

---

## 11. Takeaways for SIDM2

Things this 2005 VB6 tool does that are worth borrowing, and things worth
avoiding.

**Borrow:**

1. **Fingerprint the code, not the data.** The player's read-loop is a far more
   stable signature than any data layout, and the instruction operand *is* the
   answer. If SIDM2 needs to locate structure in a known player family, this is
   cheaper and more precise than inferring it from a register trace.
2. **Fingerprint the interpreter to learn the data dialect.** H2G's
   `read_track_version` pass identifies *which encoding the orderlist uses* by
   matching the loop that decodes it. That's a clean separation between "where
   is the data" and "how is the data encoded".
3. **One match, two tables.** Because LO/HI pointer arrays are read by adjacent
   instructions, a single signature match yields both base addresses. Design
   your fingerprints to span as much of the read sequence as possible.
4. **Surface unknown bytes in the output.** The `NN:xx-yy-zz` instrument name is
   the best idea in this codebase. Undecoded bytes rendered into a
   human-visible field turn every conversion into an experiment.
5. **Keep a byte-exact regression fixture — and know what it cannot tell you.**
   The `Commando.sid` → `Commando.sng` pair caught a genuine wavetable bug
   during the Python port that reading the source twice had not.

   But it is one file, and it only proves you still match the *old tool* — not
   that the output is correct. Every bug in the "closed" table of §10 passed the
   fixture. So did a file that **crashed GoatTracker the moment you pressed
   play** (§9), and so did a tune that played at the wrong speed. Three
   independent checks were needed, in increasing order of what they can catch:

   | Check | Catches |
   |---|---|
   | Byte-exact fixture | regressions against the reference implementation |
   | Load through the target's own loader | structurally invalid output |
   | **Actually play it** | everything else — crashes on play, wrong tempo |

   The third is the one this project deferred longest and learned most from.
   For a converter, "it plays OK" is not a weaker test than a byte diff; it is
   a *different* test, and it is the only one that validates the whole chain.

**Avoid:**

6. **Inference without validation.** Every silent failure mode in §10 is an
   unchecked assumption. If you extract an address, assert it's in range. If
   you derive a count, assert it's plausible. The cost is a few lines; the
   benefit is that failures become loud.
7. **Sticky flags doing double duty.** The `PEndMarker` latch conflates "this
   byte is a command" with "everything after here is an operand". Two
   questions, one boolean, one bug.
8. **Assuming symmetry between branches.** The one bug the byte-diff test
   caught was assuming the `else` branch of the wavetable writer mirrored the
   `if` branch. It did not. Read both branches independently.

**And the structural point:**

H2G's whole approach has a hard ceiling: it converts a tune **only if that
tune's player is already known**. Sixteen games are fingerprinted; the
seventeenth is unconvertible and the README says so. Strategy A (emulate and
trace) has no such ceiling but yields a performance rather than a score.

The interesting design space is the middle: use a trace to *find* the
structures (which frames write which registers, which memory reads correlate
with note changes), then use strategy-B-style structural extraction to recover
the authored data — getting generality from the emulator and editability from
the static rip. That is, roughly, what SIDM2's native-driver work is already
reaching toward.

---

## Appendix: reading the code

| Concern | File |
|---|---|
| PSID header, address translation | `python/h2g/sidfile.py` |
| Wildcard opcode search | `python/h2g/search.py` |
| All signature chains | `python/h2g/detect.py` |
| Orderlist decode, 8 dialects | `python/h2g/tracks.py` |
| Pattern decode, slicing, re-indexing | `python/h2g/patterns.py` |
| `.sng` serialization, table synthesis | `python/h2g/goatwriter.py` |
| Pipeline | `python/h2g/convert.py` |

Original VB6 (ground truth): `VB6 Sourcecode/h2g.frm`, ~1300 lines, one form.
Key ranges: `loadfile()` 193–481, `GoatSave()` 482–772,
`GoatConvertPattern()` 818–1097, `GoatConvertTracks()` 1100–1231.

Run: `python -m h2g <input.sid> [-o out.sng]` from `python/`, or
`.\convert.ps1 <input.sid>` from the repo root; `.\play.ps1 <input.sid>`
converts and opens the result in GoatTracker. See `README.md` for the options,
and `python -m h2g --help` for the authoritative list.
Test: `python -m pytest tests/ -q` from `python/`.
