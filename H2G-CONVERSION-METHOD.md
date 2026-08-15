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

Two dialects can share that whole shape and differ only in the instruction
*after* it. The Mega Apocalypse and Delta (Mix-E-Load loader) pattern
fingerprints are identical for sixteen bytes and then diverge in one:

```
A9 00         LDA #$00
95 ??         STA zp,X       <- Mega Apocalypse
9D ?? ??      STA abs,X      <- Delta loader
```

That byte was the whole difference between converting and
`*** CAN'T FIND PATTERN ***`. Widening it to a wildcard would be the wrong
fix: the tail is part of what identifies the *dialect*, and a chain that
matches a rough shape rather than a specific player is exactly how a
fingerprint starts naming code that is not the player at all (§10). Add the
variant as its own entry at the **end** of the chain instead, where it can
only speak for a file every earlier signature has already declined.

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

### When the file moves itself

The formula assumes a single mapping between C64 addresses and file offsets.
That breaks on a file which relocates part of itself before the player runs.
I, Ball loads at `$9000`, but its init copies `$9000-$9FFF` up to `$E000` and
the tune lives *there*, so every address its player names is an `$Exxx` one --
past the end of a file that stops at `$C2CF`. Detection located all four
tables and then rejected all four as out of range.

The copy is a plain page loop, and the pointers it walks are set up
immediately before it, so the block and its destination can be read out of the
init code the same way everything else here is -- as an oracle:

```
C20C  A9 00     LDA #$00
C20E  85 FD     STA $FD        ; destination lo
C210  85 FB     STA $FB        ; source lo -- shares the same LDA
C212  A9 90     LDA #$90       ; source page
C216  A9 E0     LDA #$E0       ; destination page
C21A  A2 10     LDX #$10       ; 16 pages
C21E  B1 FB     LDA ($FB),Y
C220  91 FD     STA ($FD),Y
```

`sidfile.find_relocation` matches that loop and reads back the three numbers.
What keeps it safe is that `to_offset` consults the result **only for an
address that does not resolve inside the file at all**. A misread copy loop
can therefore fail to rescue a file, but it can never move an address in a
file that already works -- which is also why reading just the page numbers,
and assuming the copy is page-aligned, is good enough.

### When the address isn't in the instruction at all

The whole method (§2) rests on the table's address being *in the operand of
the instruction that reads it*. Devils Galop breaks that assumption outright.
Its player reads

```
1359  BD 95 17  LDA $1795,X      ; orderlist pointer lo, per voice
135E  BD 96 17  LDA $1796,X      ;                    hi
138C  B9 97 17  LDA $1797,Y      ; pattern pointer lo
1391  B9 98 17  LDA $1798,Y      ;                 hi
```

and `$1790-$1798` is nine bytes of zeroes that nothing ever stores to. Read
literally, every one of those pointers is `$0000`, and the pattern count
arithmetic of §4.2 gives `$1798 - $1797 - 1` = **no patterns** — a file that
detects perfectly and converts to nothing.

The operands are placeholders. The init routine writes the real addresses
over them, one byte at a time, before the first play call:

```
18B3  A9 1E     LDA #$1E
18B5  8D 5A 13  STA $135A        ; the lo operand byte of the LDA at $1359
18B8  A9 0A     LDA #$0A
18BA  8D 5B 13  STA $135B        ; ...and its hi byte -> $0A1E
18BD  8D 60 13  STA $1360        ; one LDA feeds several stores
18C0  8D 8E 13  STA $138E
18C3  8D 93 13  STA $1393
```

leaving orderlists at `$0A1E`/`$0A21` and patterns at `$0A24`/`$0A50` — 44
entries. `sidfile.find_init_writes` walks the routine from the PSID
`initAddress`, following the leading `JMP` chain (the near-universal
`init: JMP realinit` indirection) and stopping at the first `JMP` taken after
the routine has started, which in this file is the `JMP $12EB` into the
player. Going further would read the play routine's per-frame `LDA #imm /
STA abs` state writes as though they were patches. `JSR`s are stepped over
rather than followed, so writes a helper makes are missed — an under-read,
which costs a rescue at worst and can never invent one.

The same routine ends with a block copy that moves the authored instrument
records over a stale set sitting at the address the player reads:

```
18E7  A2 00     LDX #$00
18E9  BD 3B 18  LDA $183B,X
18EC  9D 99 17  STA $1799,X
18EF  E8        INX
18F0  E0 78     CPX #$78         ; 15 records x 8 bytes
18F2  D0 F5     BNE $18E9
```

That one is pure fidelity rather than a blocker, and it is not a small
effect: without it the tune converts with the disk records, whose waveform
bytes are wrong, and plays as noise — waveform-class agreement 6% with 2842
invented noise frames against an original that has none. With it, 76% and
zero. The melody columns are identical either way, since instruments do not
change which notes are struck.

**The safety rule mirrors the relocation's**, and has to, because unlike a
relocation these writes *overwrite* bytes: init writes are applied only to a
file whose tables, read as they stand, name **no patterns at all**. A file
that already reads its tables never sees a patched byte. That gate is doing
real work rather than being theoretical — 45 of the 95 corpus files have a
findable set of init writes, and exactly one has them applied.

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

**A large count *was* evidence of over-reading, and this document argued the
opposite for eleven versions.** The reasoning ran: several corpus tunes report
56–59 instruments where the music plays a dozen, which looks like a runaway
terminator, but cannot be — because Bangkok Knights and Thundercats share 29
byte-identical 8-byte records, so the table must be a shared Hubbard bank
appended to the player, of which any tune uses a subset.

The recurrence is real. It is not evidence for the count. In the 35 stride-8
files that carry the two-stage attack array (§7), a second table of the same
8-byte rows
begins immediately after the records, and the walk goes straight through it:
its own `+2` is the low byte of a frame counter, which is a legal waveform
often enough to keep going. So the count came out at roughly twice the truth —
IK+ 30 where 15 are real, Wiz 40/20, Delta 44/22, Bangkok Knights 58/29 — and
the 29 recurring rows are **16 instrument records and 13 rows of the attack
array**, which recurs across these files for the obvious reason that they
share a player. The shared bank exists; it is 16 records, not 29, and the
figure that was quoted as proof was half of it player data.

`_bound_instruments` ends the count at the array. It applies only where the
gap is a whole number of records — three files put something between the two
tables and keep the count they had — and it never cuts an instrument any
pattern reaches. Corroboration beyond the arithmetic: in several files
(Dragon's Lair II, Kings of the Beach ingame, Lightforce, Nemesis, Star Paws,
Sigma Seven, IK+, Thanatos) the boundary lands on *exactly* the highest
instrument the music plays.

The downstream constraint is unchanged: each instrument costs 5 wavetable
entries against a 255-entry table with a one-byte length, so **at most 51 are
representable at all** regardless of how many the table holds. That, not
`MAX_INSTR` (64), is why the writer clamps. What changed is that no corpus
file reaches it: the ten that were reported as losing real instruments to that
ceiling were all counting the array.

### 4.2 Pattern count — table-adjacency arithmetic

```python
det.pattern_used = (det.pattern_hi - det.pattern_lo) - 1
```

This works **only because the LO-byte array and HI-byte array are contiguous in
memory**: the distance between them *is* the length of the LO array. Elegant,
and free — but it silently produces nonsense the moment a player interleaves
the arrays, pads between them, or orders them HI-then-LO.

It also over-counts, and the over-count has a concrete victim. Nothing says
the whole gap between the arrays is *authored* entries; any padding becomes a
**phantom pattern** whose pointer is whatever bytes happen to sit there.
Last V8's entry `$1C` points into the middle of the player's own track
selector (`8D 17 85 / 0A / 18 / 6D 17 85 / AA / …`), and both possible
decodings of that code-as-pattern are garbage. Harmless-looking while no real
subtune references it — but the garbage feeds *global* structures: its
portamento commands become speed-table entries, and gt2reloc re-encodes the
speed table for the whole file (`tablemap[STBL]`, content-dependent choices
like `nocalculatedspeed`, greloc.c:2184), so a change that alters how the
garbage decodes (the bit-6 status byte, below §5) swings the *measured
subtune's* portamento wildly. That was the actual mechanism behind the
71% → 3% regression that blocked the bit-6 fix: not the phantom being
played, but the phantom's garbage perturbing a table every subtune shares.

`--reject-phantoms` (patterns.phantom_patterns) now disarms this on the
player's own terms, never statistically: an entry is rejected when its cell
or address lies outside the file, when decoding it under the file's own
grammar runs off the end of the file, or when the bytes it would decode
overlap the pointer tables themselves or a run of code the detection
signatures matched (`Detection.code_spans` — the match *is* the proof those
bytes are the player). Last V8's `$1C` is caught by the last rule: its
decode span contains the very track-selector signature detect.py located.
A rejected entry becomes the one-rest `ERROR_PATTERN` placeholder, so
references to it still resolve. Reachability is deliberately not a
criterion — unreferenced entries are `--prune-patterns`' business, and
dangling *references* (orderlists naming entries beyond the table) are a
separate phenomenon this pass leaves alone. Corpus-wide the pass flags
entries in 10 files, none referenced by any clean subtune.

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

**The bend operand is two bytes, in most players.** The step is 16-bit and the
second half is the *next* pattern byte — Warhawk `$10EC`:

```
10EC  INY / LDA (patt),Y      ; the operand
10EF  BPL instrument          ; < $80 -> an instrument number, one byte only
10F1  STA slidelo,X           ; >= $80 -> step LOW, with bit 0 the direction
10F4  INY / LDA (patt),Y      ; <- a second byte
10F7  STA slidehi,X           ; step HIGH
```

and `$1320` adds `(slidehi,X << 8) | (slidelo,X & $7E)` to the voice frequency
every frame, up or down according to bit 0 (`AND #$01 / BEQ add`). Reading only
the first byte therefore gets half the parameter *and* leaves the other half to
be decoded as the note, putting every byte after it in that pattern one
position out.

41 of the 95 corpus players have that second fetch and none has a one-byte
variant of the same shape; the other 54 have a differently shaped fetch routine
entirely. `Commando` is among the 54, which is why the original tool never
needed it and why honouring it does not move the byte-exact fixture. It is
`--slides`, gated on `detect.SLIDE_OPERAND_SHAPE`.

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

**Except that in 14 corpus players, bit 7 of the note byte is a legato flag,
not part of the note.** Delta `$BEFF`:

```
BEFF  LDA (patt),Y / STA $C33D    ; keep the raw byte
      AND #$7F / STA note,X       ; the note is the low 7 bits
BF31  LDA $C33D / BMI ...         ; flag set -> skip the pulse/ADSR retrigger
```

Same idiom in Sanxion `$B11C`, W.A.R. `$E536`, Zoolook `$411D`; the shape
`C8 B1 ?? 8D ?? ?? 29 7F 9D ?? ?? 0A A8` matches 14 files. Clamping the raw
byte — what the VB6 did and the port copied — collapses every flagged note
onto `$BC`: Delta's pattern `$01` is six distinct notes (`$B4 $B2 $B4 $AF $AD
$AF`, confirmed by siddump) that all came out as one repeated top note. The
flag itself is dropped on conversion (Goattracker has no tie in the note
column) but the note survives; detection is `det.note_flag`, gated on the
`AND #$7F` shape being present in the player.

**A bit-6 status byte skips the operand *and* the note** — `BIT status / BVS`
at Commando `$50CF` and Last V8 `$80DC` branches over both reads, so a status
byte of `$C0-$FE` consumes nothing but itself, where the bit-7-first reading
consumes three bytes. Verified in the 6502 (the AND #$1F / STA wait sits
*before* the BVS, so the skipped event still holds its rows), and now
implemented as `--status-bit6`, gated on the `BIT`/`BVS` shape
(`detect.STATUS_BIT6_SHAPE`, 61 of 95 corpus files). It shipped **blocked**
for two versions: the only file it moved significantly was Last V8, where it
dropped melody 71% → 3% — not because the decoding is wrong but because it
changed how Last V8's *phantom* pattern `$1C` (§4.2) decodes, and the
phantom's garbage feeds the file-global speed table. With
`--reject-phantoms` disarming that entry the two flags together move no
corpus file's melody by a point at its presets; Commando has the shape but
no `$C0-$FE` byte in any played pattern, so the byte-exact fixture holds
even with the flag on.

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

## 6. The orderlist / track format and its 10 dialects

`tracks.py::_build_track` walks the raw orderlist byte stream and rewrites it.
Six behaviours, selected by `read_track_version`:

```python
version == 4:                 # ACE 2
    b1 >= 0x80  -> end, restart 0x00
    <= 0x7F     -> pattern number, emit as-is

version == 9:                 # Chain Reaction
    0xFE        -> end, restart 0x00   (the ONLY marker -- no stop form exists)
    <= 0xFD     -> pattern number, emit as-is

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
    0xFE        -> end, with restart position 0xFD (deliberately illegal = stop;
                       see "$FE means stop" below -- this is what blocks export)
    0xFF        -> end, with restart position 0x00 (loop to start)
    <= 0xFD     -> pattern number, emit as-is

version == 10:                # Delta
    layout is  P0, r1, P1, r2, P2, ... marker  -- version 0's read with a
    repeat count woven between the pattern numbers; each pattern is emitted
    r times (a stored 0 counts 256: the player's DEC wraps and BNE replays)
    0xFE / 0xFF -> as version 0 (the BMI leaves markers unconsumed)
```

**Version 4 emitted nothing at all until v0.5.48.** Its branch tested the end
condition and then fell through without appending the pattern number, so every
ACE 2 orderlist came out empty and the file failed as `NO PLAYABLE SUBTUNE`.
The fault was inherited rather than introduced: `h2g.frm:1152` `Case 4` is the
same empty branch, and the later `Case 0, 1, 2, 3, 4` at `:1199` that *would*
have appended is unreachable for 4, because VB's `Select Case` takes the first
match. ACE 2 is the corpus's only version-4 file, so nothing else ever showed
the fault — which is the general hazard of a per-dialect `Select Case` verified
against a corpus with one sample of some dialects.

**Version 9 is a reminder that a dialect can differ by a single constant.** Its
player at `$089A` is version 0's shape with `$FE` where version 0 expects
`$FF`, and no second marker at all — the tune can only loop, never stop. It
even carries a dead `CMP #$FE` on the fall-through path, which the first test
has already made unreachable. Because version 0's signature is
`C9 FF F0 ?? C9 FE` and this file is `C9 FE F0 ?? C9 FE`, nothing matched and
it fell through to `version $FF`. Note what that means for `command_floor`:
`$FE` is the only reserved byte, so `$FD` is still a pattern number here where
in a version-2 dialect it would be a transpose.

**Version 10 hid in plain sight as "half the orderlist dangles".** Delta's
player at `$BF85` replays a pattern while a per-voice counter counts down and
only then steps the orderlist — twice, because the byte it lands on is the
*next* pattern's repeat count:

```
BF85  DEC $C354,X / BNE      ; still repeating -> replay, orderlist unmoved
BF8A  INC $C2EC,X            ; else step to the repeat byte
BF90  LDA (track),Y / BMI    ; $FE/$FF: a marker, leave it to be read as one
BF94  STA $C354,X            ; otherwise it is a repeat count
BF97  INC $C2EC,X            ; and step past it to the pattern number
```

Warhawk's equivalent (`$115D`) has a plain `INC` where this has the `DEC`;
Delta is the only corpus file with the DEC form. Read flat — what version 0
does — every second byte is a repeat count played as a pattern number, which
is what Delta's famous "2 dangling refs of 337" and its 2% melody really
were. The confirmation is structural, not aural: decoded this way, all 13
subtunes come out with their three voices **exactly** equal in frames
(subtune 0 is 13632 in all three), while the equally plausible
`(pattern, repeat)` pairing disagrees by up to 12×. When two readings of a
table are both syntactically fine, the one under which the voices agree in
length is the player's.

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

Hubbard uses larger values freely — **24, 36 and 48 semitones**, two to four
octaves, in 17 corpus files — so the clamp was not a corner case: every note
under such a step played 10 to 34 semitones flat, and on four files that is
the whole tune in the wrong key. `--fold-transpose`
(`tracks.fold_transposes`) recovers it. The transpose is a pitch offset and
nothing else on either side of the lookup, so `T` and `(T mod 12) + 12k` are
the same interval; the remainder — always `0..11`, comfortably inside the
format — stays in the orderlist, and the whole octaves are added to the note
column of a *copy* of each pattern the step plays. The note column has the
room: pitches span `$60`–`$BC` and a decoded Hubbard note tops out wherever
the tune's own melody does.

Where it does not have the room the step keeps its clamp. A partial fold is
only a different wrong pitch, and for a transpose of 24 (remainder 0) it is a
worse one — the note would come out 24 flat rather than 10 — so each step is
either exactly right or exactly as it was. The unfoldable steps are almost
all in phantom subtunes carrying transposes of 96 and more, which no
frequency table has entries for. The cost is one pattern-table entry per
distinct (pattern, octaves) pair against Goattracker's 208; variants are
numbered from `pattern_used + 1`, extending the table rather than displacing
anything, and stop at the dialect's command floor.

Measured by position-aligned modal semitone delta against the original's
siddump trace, with files that were already right as controls: Deep Strike's
voice 0 `-10@100%` → `+0@100%`, Kings of the Beach (intro) and Rock Tells the
Tale `-21@100%` → `+1@100%`, One on One `-9@100%` → `+1@100%`. The `+1` is a
separate, still-unexplained residual those files already showed on their
untransposed voices (§ "Three unexplained residuals" in the handoff); it is
not introduced here, and it is now the *only* constant offset left on them.
Commando, Zoids, Crazy Comets and Kings of the Beach (ingame) stay at
`+0@100%` on every voice.

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

### `$FE` means *stop*, and Goattracker cannot say that

The `0xFD` restart position above is not arbitrary. Hubbard's `$FE` marker
means **this tune has ended**, and every dialect implements it the same way:
it calls the player's jump-table entry +3, which is `LDA #$C0` / `STA flag` /
`RTS`, and the `BIT flag` / `BMI` at the top of the play routine then branches
away and stops fetching notes.

```
Warhawk      $109F  C9 FE / D0 17 / 20 03 10   ->  $1003 = JMP $1F30
Last V8      $809B  C9 FE / D0 03 / 4C 13 80   ->  $8013 = JMP $8C71
Saboteur II  $F0A2  C9 FE / F0 19 / 20 0C F0   ->  $F00C = JMP $F589

$1F30 / $F589:  A9 C0  LDA #$C0 / 8D .. ..  STA flag / 60  RTS
```

Goattracker's orderlist has no stop, so the VB6 original wrote a song-loop
whose restart position is out of range (`'make repeat illegal, so goattracker
stops`, `h2g.frm:1206`). `gplay.c:969` reads the operand, finds it
`>= songlen`, and calls `stopsong()` — exactly the intended behaviour.

**It is also unexportable.** `greloc.c:244` rejects any song whose restart
position is `>= songlen`, so `gt2reloc` — the packed-`.sid` exporter, and
therefore the only route to a fidelity test against the original — refuses the
file. It refuses *silently*: its error path writes to `fopen("CON")`, so
headless you get exit 0, no message, and no output file. 28 of the corpus's 78
convertible files were unpackable for this reason alone.

`--legal-restart` rewrites the position to 0, trading the stop for a loop. The
rewrite has to run **after** re-indexing, packing, merging and splitting,
because all four change an orderlist's length and "is this position in range"
is a question about the finished list — position 0 is the only answer available
before that.

A quieter defect sits next to it: a voice whose orderlist is nothing but a
marker (`[$FF, $00]`, so `songlen == 0`) has no legal restart position either,
but the length is the problem, not the position.
`greloc.c:201` does not reject such a subtune; it counts only the
subtunes whose three channels all have nonzero length, and the writing loop at
`greloc.c:653` then runs over the **original** indices `c < songs`. So nothing
is renumbered — an invalid subtune keeps its slot and is written with
`songsize 0` (`:701-706`), and every subtune whose index is at or past the
count is never written at all. Seven corpus files lose subtunes this way;
`Rasputin` loses its subtunes 15 and 16, carrying 309 and 621 sounding rows,
with no error from any layer. `fidelity.py` reads this before packing so a
comparison against an empty stub is reported rather than scored — see
`SNG2SID-FIDELITY.md` §7.

`tracks.ensure_playable_orderlists` repairs it, and **unconditionally**: a
zero-length voice is silent data loss whatever the restart positions are, so it
must not depend on an opt-in flag. Until v0.5.49 the repair happened only as a
side effect of `--legal-restart`, which meant the default conversion quietly
dropped subtunes from its packed `.sid`.

The two repairs turn out to be one repair. `greloc.c:244`'s restart check runs
*inside* the all-voices-nonzero guard, so an invalid subtune's illegal restart
was never looked at; reviving the empty voice alone exposes it and turns
`Rasputin` from "packs 15 of 17 subtunes" into "packs nothing". So the function
also legalises the restart positions of the voices in the subtunes it revives —
and only those. Their alternative is not a stop; it is not being exported at
all. Subtunes that were already valid keep their stop markers and remain
`--legal-restart`'s business. Measured with the flag off: `Rasputin` 15 → 17
packed subtunes, `One_Man_and_his_Droid` 11 → 13, `Mega_Apocalypse` 10 → 11,
and with the flag on not one byte of the corpus changes.

> The `version == 8` branch was unreachable when this was written, because
> `detect()` then produced only 0–7 or `0xFF`. It is live now: 8 is the digi
> engine and 9 is Chain Reaction.

### A second engine: interleaved tables and a different pattern grammar

Nine corpus files use a later Hubbard engine that none of the classic
signatures can read. It is worth studying because both of its differences are
things a strategy-B ripper will meet again.

**1. The pointer tables are interleaved.** Every classic player keeps a LO
table and a HI table, which is what makes `count = HI - LO - 1` work at all.
This one holds `lo,hi,lo,hi` and doubles the index:

```
10E5  0A A8     ASL / TAY          ; pattern number * 2
10E7  B9 41 18  LDA $1841,Y        ; low
10EC  B9 42 18  LDA $1842,Y        ; high -- one byte on, not a table away
```

Read with the classic formula that yields **zero** patterns. And because the
two halves are no longer separated, nothing in the file records the entry
count: it has to be recovered by walking entries until one stops resolving
inside the file.

**2. The table the code names is not the table the data is in.** The
orderlist-read instruction points at a *runtime* table, all zeroes on disk and
filled in at init. The authored pointers sit 8 bytes past it (4 voices x 2),
and the pattern table 10 past those. Those offsets are identical in all nine
files, and the pattern table found independently by the other signature lands
exactly there — two reads confirming each other.

That relation is also the **discriminator**. Six further files match both code
shapes but fail it; SIDId identifies every one of them as
`Jason_Page/RobTracker`, a related engine whose tables sit elsewhere. Matching
the instruction shape is not enough — the layout has to agree too.

The pattern grammar is new as well ($1104):

```
< $80         a note; $60 is a rest, everything else is a semitone offset
bit 7+6 set   duration prefix, wait = b & $1F -- and it is *sticky*
$80 n         set instrument
$82 a b       effect (two operands)      $83 a b   effect (two operands)
$81           end of pattern
```

with one twist: `$81` is never read at the fetch point. The note path peeks
the *following* byte for it, so a decoder that only looks at fetched bytes
runs past every pattern's end into the next `$FF` anywhere in the file. That
is what made an early attempt decode 22 patterns of Off the Cuff into 112747
rows.

`$60` is a **key-off**, not a hold. `$1184` does `DEC $165D,X`, taking the
gate mask just set to `$FF` at `$10FF` down to `$FE` — the same value the
end-of-note release path writes — and `$165D,X` is ANDed into the `$D404`
write at `$148D`, so bit 0 (GATE) is cleared. The converter emitted a hold
row (`$BD`) for it until v0.5.46, which sustained the previous note through
every rest. Off the Cuff alone gains 66 `$BE` rows from the correction.

Note that `FIDELITY.md` cannot see this class of fix: it compares note
*attacks*, and closing a gate adds none. The report did not move by a single
percent on any of the nine digi files. The fix rests on the disassembly, not
on the metric.

Instrument records are 16 bytes rather than 8, but the fields this converter
reads — waveform `+2`, attack/decay `+3`, sustain/release `+4` — sit at the
same offsets in both, so only the stride differs.

The engine drives **four** voices; the fourth is the sample channel these
files are named for, and Goattracker has no place for it.

### A third engine: a command jump table and a duration table

Chicken Song (`$10A0`) and Hollywood or Bust (`$04A9`) share version 0's
orderlist and the classic separate-LO/HI table layout, but nothing inside a
pattern — a third grammar, the `"cmdtable"` dialect
(`patterns.py::_build_raw_pattern_cmdtable`):

- `b >= $80` is a **command**: `AND #$0F / TAX / LDA $1738,X / STA $10B7`
  indexes a jump table and self-modifies the dispatch. Each handler eats a
  fixed number of operand bytes and returns to the fetch. One of them sets
  the instrument — there is no per-event instrument operand at all.
- `b < $80` is a note event whose low 5 bits index a **duration table**
  (`AND #$1F / TAX / LDA $14BE,X` → `6 12 24 36 72 48 96 18`), not a frame
  count. Bit 6 = no note follows; the note byte's bit 7 is the same legato
  flag as §5.
- `$FF` is only ever *peeked* (`$1169`), never fetched — the same trap as the
  digi engine's `$81`, and why 15 of Chicken Song's 37 patterns previously
  ran off the end of the file.

Everything is derived from the player, nothing hardcoded: the two halves of
the jump table are adjacent, so their distance is the command count, and each
handler's operand count is its `INY` count minus one. Chicken Song yields 6
commands, Hollywood or Bust 7; `$80` sets the instrument in both.

One more piece was needed. The durations are all multiples of a common
factor (GCD 6 for Chicken Song, 3 for HoB), and Goattracker's fastest steady
row is 3 player calls — so emitting one row per frame cannot play at the
right rate. Dividing the durations by their GCD and handing the factor to
`CMD_SETTEMPO` (`Detection.frames_per_row`) is what took Chicken Song from
47% to 98% melody, and it is confined to this dialect: `frames_per_row` is 1
everywhere else, so no other file's bytes can move.

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
| `+6` | **not interpreted** — printed in the instrument name (it is the *pulse-width sweep*, see below) |
| `+7` | effect byte — read as Warhawk's "arp style" bit-field for every file, which is wrong for most of them (see below); *and* printed in the name |

`+6` is worth naming, because it is easy to mistake for a vibrato parameter and
it is not one. Warhawk loads it per instrument at `$11E1` (`LDA $163D,Y` against
an instrument table based at `$1637`, so record `+6`) into `$158B`, and the
routine at `$12BF` consumes it:

```
12BF  LDA $158B / BEQ skip     ; zero -> no sweep
12C7  AND #$0F                 ; low nibble  = rate (frames between steps)
12C9  DEC $1593,X / BPL skip   ; per-voice countdown
12D4  AND #$F0                 ; high nibble = step, kept in the high position
12DE  ... ADC $15C9,X          ; 16-bit add to the running value
12EE  CMP #$0E / INC $1596,X   ; flip direction at $0E, and at $08 coming down
1313  STA $D403,Y              ; <- PULSE WIDTH HIGH, not frequency
```

The write is `$D403`, so this is a **pulse-width sweep**: a triangle between
duty $8xx and $Exx. H2G already writes the pulse *table* from `+0`/`+1`, so
what is missing is the sweep, not a vibrato — and Goattracker's counterpart is
the pulse table's own sweep rows, not the speed table.

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

The right-hand column encoding is now confirmed against Goattracker's own
source and manual: `readme.txt:794-796` gives `$00-$5F` relative notes,
`$60-$7F` *negative* relative notes and `$80` "keep frequency unchanged", and
`gplay.c:717-728` implements exactly that (`if (note < 0x80) note +=
cptr->note; note &= 0x7f`). So `0x80 - N` is "N semitones down", which is the
right shape for an arpeggio. The `$FF`-left + `$00`-right = stop convention is
confirmed by instrument 1's fixed `09 FF 00 00 00` / `00 00 00 00 00` pair.

### `+7` is not a format — it is one player's bit-field

This is the important correction, and it applies to the block above.

The `arp_style` reading — bit `$01` a drum, bit `$04` an arpeggio whose
interval is the high nibble — is **Warhawk's**, and H2G applies it to every
file it converts. Reading the byte's own consumers out of five players shows
five different treatments. In each case the instrument-load routine stores
`+7` somewhere, and that address is what the player later tests:

| Player | holds `+7` in | what it does with it |
|---|---|---|
| Warhawk | `$15BD` | `AND #$08` / `#$01` / `#$02` / `#$04`, `LSR`×4 — the bit-field |
| Mega Apocalypse | `$4F60` | `LDA` / `BEQ` — the whole byte, zero or not |
| W.A.R. Preview | `$0CF8` | `LDA` / `BEQ`, then `CLC` / `ADC` |
| One Man and his Droid | `$1501` | `LDA` / `BEQ`, then `AND #$E0` |
| Chicken Song | `$15C1` | `AND #$02`, but the block `ORA #$80`s into `$D404` — a noise swap, not a pitch rise |

So the same bit means different things in different players. That was measured
rather than argued: an early version of `--effects` applied Warhawk's reading
corpus-wide and put **287 frames of pitch movement into W.A.R. Preview and 256
into Mega Apocalypse, whose originals have none at all** in the traced window.

`--effects` therefore decodes two bits only where the routine that reads them
is actually present, found by resolving the address the instrument-load routine
stores `+7` to and requiring the test block to name *that* address
(`detect._find_effect_routines`). 4 of 83 convertible corpus files have the
rise routine; 13 have the arpeggio one.

**Bit `$02` — a chromatic rise** (Warhawk `$13A2`): every fourth frame
(`LDA framecount / AND #$03 / BNE`) the player does `INC noteindex,X` and
rewrites `$D400`/`$D401` from the frequency table, so the note climbs a
semitone every four frames for as long as it is held. Goattracker cannot step a
note from the wavetable without one entry per semitone, which the fixed
five-entry-per-instrument layout has no room for — but it can *glide* at a
note-relative rate: a speed-table left side with bit `$80` set selects a
realtime-calculated speed, computed as the semitone interval at the current
note shifted right by the table's right byte (`readme.txt:171-174`,
`gplay.c:539-547`). Shift 2 is a quarter semitone per frame — the player's rate
exactly, as a continuous glide rather than four-frame steps. That approximation
is the only part of the mapping that is not literal, and it needs `--format
gts5`: a GTS2 file stores no speed table.

**Bit `$04` with a zero interval nibble is silent.** `$13DB` writes the nibble
into the operand of the `SBC` at `$13F4`, so a zero nibble subtracts zero and
both halves of the alternation play the same note. The original substitutes
`$74` — a `+12` relative note — for a zero nibble, inventing an octave-up
arpeggio. **315 of the corpus's 660 arpeggio instrument records have a zero
nibble**, including all six of Commando's, which is why turning this on moves
the byte-exact fixture.

### The census: which players actually implement which bit

The table above samples five players. This is all 95, and it separates two
questions that look like one:

- does the player **test** this bit against its own `+7` address at all
  (`LDA effect / AND #$xx`), and
- does the **whole block** match Warhawk's, i.e. does this player *mean* by
  that bit what Warhawk means?

77 of 95 files resolve a `+7` load at all (the other 18 include all 9
digi-engine files, whose 16-byte records the probe does not read).

| Warhawk block | files with the block | records setting the bit, corpus-wide | …of those, in a file that has the block | files that test the bit **without** the block |
|---|---:|---:|---:|---:|
| `$01` drum (`$1366`) | 44 | 447 | 299 | 25 |
| `$02` rise (`$13A2`) | 4 | 276 | 12 | 52 |
| `$04` arpeggio (`$13CD`) | 13 | 634 | 167 | 62 |
| `$08` pulse-lo (`$12A3`) | 21 | 294 | 59 | 34 |

Read the last two columns together. **467 of the 634 instrument records that
set the arpeggio bit are in a player with no arpeggio routine**, and the
wavetable builder arpeggiates all 634. For the drum bit it is 148 of 447.
Those are records where H2G invents an effect from a bit whose meaning it has
not established — the same defect the `--effects` gate was added to prevent,
still present in the *unconditional* part of the wavetable.

`Nineteen` is the clean example. It tests `$01`, `$02`, `$04`, `$08`, `$10`
and `$20` against its effect byte and matches **none** of the four blocks, yet
7 of its records get a fabricated noise tick and 11 a fabricated arpeggio. It
scores **melody 100%, wave 21%** — every note right, every timbre wrong,
and invisible to any attack-based metric.

30 further files resolve `+7` and neither test it nor read it whole, so for
those the byte may be inert entirely.

Two blocks are documented here for the first time:

**Bit `$01` — a drum** (Warhawk `$1366`). Two guard loads follow the bit test
(a per-voice counter at `$15B1,X` and a drum length at `$1576,X`), then the
block decrements that counter into `$D401` — a downward pitch sweep, one step
per frame — while writing the voice's own waveform with the gate bit cleared
(`$1390 LDA $157C,X / AND #$FE`), and on the late branch writes `#$80` to
`$D404` instead, swapping in noise. H2G's version is two wavetable entries:
one noise tick, then back. It gestures at the noise, in the wrong place, and
drops the sweep entirely — which is why the corpus under-produces noise (5710
frames against the original's 11641) *while* inventing it in 148 records
elsewhere. Both errors at once, which is exactly why the aggregate reads as
simple under-production.

### What Phase 2 did with the census, and what it cost

Under `--effects` the wavetable builder now writes bits `$01` and `$04` only
in a file whose player has the matching block, and writes the drum the way the
block plays it: attack, the voice's waveform with the gate released, one step
of a downward sweep at 256 units per frame (`goatwriter._drum_entries`). The
leading noise tick is gone from every path.

The measurements, corpus-wide over the 82 scored files, are worth recording in
full because two of the three plausible readings lost:

| shape | mean wave | our noise frames (orig 11641) |
|---|---:|---:|
| inherited: tick + arpeggio for every file | 60.5% | 5680 |
| gate both bits on the block, keep the tick | 60.2% | 5383 |
| gate, and end the drum on noise as `$139D` does | 58.1% | 10666 |
| **gate, gate-off waveform + sweep, no noise ending** | **60.6%** | 4548 |

The noise *ending* is the interesting loss. It is unambiguously in the player,
and writing it is unambiguously worse — because Goattracker latches the last
waveform of a gated-off voice until the next note, so a trailing noise entry
stands for the whole rest of the note, while the player stops writing `$D404`
the moment its counter runs out. A literal transcription of one instruction is
not a faithful transcription of what it does.

> **Correction, v0.5.90: it is not an ending.** Re-reading the branch for
> § 7.ii shows `BCC` is taken while the remaining-duration counter is still
> *large* — the beginning of the note. The noise is the drum's **attack** and
> the sweep runs after it. The measurement above stands as a measurement (that
> shape scored 58.1% against 60.6%), but it was testing noise at the wrong end,
> so it is not evidence about the player's actual shape. It also puts the
> *inherited* leading noise tick — which this section dismissed as "not in the
> player at all" — back in question. Neither has been re-measured; the drum's
> five wavetable entries are full, so writing an attack tick means dropping
> something else, and that trade has not been tried.

The second loss is subtler. Keeping the fabricated tick where no routine was
found is worth about +0.3 points — but the files that lose most from dropping
it (`Bangkok_Knights`, `Nineteen`, `Ricochet`) have originals that are 46%
noise *by frame*, so a tick anywhere lands on a noise frame about half the
time. Scoring at chance is what an invention looks like when the metric is
coarse enough to reward it. A looser probe was tried first and refuted: of the
25 files that test bit `$01` without matching Warhawk's block, only 2 write
noise to `$D404` anywhere near the test, and those 2 are not the files that
regress. There is no evidence the bit means "drum" in them.

The arpeggio half — 544 of 683 records — is invisible to both metrics by
construction: an arpeggio moves pitch, `melody` compares note attacks and
`wave` compares waveform class. It moved the report by 0.0 points. That is not
evidence it did nothing, and this is the fourth time in this project that a
correct fix has been invisible to the harness that was built to see it.

What remains of the census's four blocks: none of them, as of v0.5.80. Bit
`$08`'s pulse-width variant was the last one, blocked twice over — the pulse
table had two fixed entries per instrument, and no metric here could see a
duty cycle. Tracking siddump's `Pul` column was named as the prerequisite and
landed as the report's `pul` column in v0.5.78; `_pulse_layout` returns each
instrument's start position instead of a stride in the same version, which is
what let a program be longer than two entries. The engine itself is
`goatwriter._pulse_lo_program`, and corpus-wide it fires on **294 records
across 21 files**, with **no file** carrying both it and the sweep — the
mutual exclusivity the block's own bit test implies, confirmed rather than
assumed. The drum's sweep is still one entry deep rather than the counter's
length, since the counter is a runtime value and the wavetable has three free
slots.

**Bit `$08` — a pulse-width variant** (Warhawk `$12A3`). It selects between
two treatments of instrument byte `+6`: with the bit clear, the triangle sweep
into `$D403` (pulse HI) described in §7 above; with it set, `ADC`-accumulate
`+6` into the instrument's own `+0` byte and write that to `$D402` (pulse LO).
Note the store at `$12B3` writes the running total **back into the instrument
record**, so a static read of `+0` sees only its initial value — the same
class of hazard as the tables Devils Galop's init patches (§4).

**Lesson:** when the source format is *poorer* than the target format, you have
to synthesize plausible target-side structure. That synthesis is a creative
choice, not a translation — and it is where converted output stops being
"the original" and starts being "an interpretation of the original". The
census is the discipline that keeps the choice honest: *measure how often the
structure you are about to synthesize is actually there.*

### The census was half a census — `+7` has eight flags, and two formats

Phase 1 inventoried bits `$01`, `$02`, `$04` and `$08`, on the assumption that
the high nibble was Warhawk's arpeggio interval (`LDA effect / LSR x4`). It is
not, in most files. Re-running the census over all eight bits — and looking for
`BIT effect / BVC` and `LDA effect / BPL` as well as `AND #$xx`, without which
bits `$40` and `$80` are invisible — gives:

| bit | files testing it | files setting it | records set | in a testing file | in one that does not |
|---|---:|---:|---:|---:|---:|
| `$01` | 69 | 73 | 427 | 419 | 8 |
| `$02` | 56 | 57 | 252 | 237 | 15 |
| `$04` | 75 | 75 | 606 | 606 | 0 |
| `$08` | 55 | 60 | 264 | 230 | 34 |
| `$10` | 31 | 53 | 317 | 210 | 107 |
| `$20` | 30 | 50 | 317 | 189 | 128 |
| `$40` | 34 | 50 | 295 | 198 | 97 |
| `$80` | 12 | 41 | 209 | 117 | 92 |

(77 files, those whose `+7` address resolves.) All eight are real flags in some
player. Sorting the same files by *which* reading they use partitions them
exactly:

| reading | files |
|---|---:|
| high nibble as a number (Warhawk's arpeggio interval) | 13 |
| high nibble as four more flags | 41 |
| neither — `+7` unread or read whole | 23 |
| **both** | **0** |

Zero overlap is the finding. These are two formats, not one format read two
ways, and they are told apart by the player's own code rather than by the
dialect number. In the second one bit `$04` is not an arpeggio at all. IK+
`$E38B`, a shape 43 files share -- and a 44th, Mega Apocalypse, spells with
its per-voice cells in zero page (§ 7.yyyy):

```
E38B  29 04     AND #$04
E38F  BD FC E7  LDA counter,X     ; per-voice, set at note start
E392  F0 09     BEQ expired
E394  DE FC E7  DEC counter,X
E397  B9 EE E9  LDA attack,Y      ; still running -> the attack waveform
E39D  B9 77 E9  LDA $E977,Y       ; expired -> the instrument's own +2
E3A0  9D 8F E5  STA wavslot,X
```

`$E977` is `instr + 2`, the waveform the converter already emits — which is
what proves the block is a two-stage waveform and not something else. The
attack waveform and its duration live in a **second 8-byte-per-instrument
array** parallel to the records, indexed by the same `Y = i * stride`: attack
at its `+1`, duration at its `+3`. The duration is corroborated independently
from the note-start push chain, whose last `PHA` is the first `PLA` into the
very counter this block decrements — and corpus-wide that names `attack + 2`
in **44 files out of 44**.

Two details make this format hostile to a naive reader. Bit `$08` reuses the
same field as the *high byte of a pointer* to a per-instrument byte-code
program (IK+ `$E33A` builds `$40`/`$41` from it), so a record setting both
bits has no attack waveform to read. And a record's `$04` is meaningless if
the attack byte is not a legal waveform nibble — 24 of 295 are not, and every
one of them lies in the parallel array itself, which the instrument-count
sniffer (§4.1) walked straight into and reported as extra instruments until
v0.5.66. Locating the array is what made that boundary knowable: the reading
below is not written to the output, but it ended a miscount that had every
one of these files carrying roughly twice the instruments it has.

### Reading it is not the same as being able to write it

`detect._find_two_stage` lands this reading; `goatwriter` does not use it.
Encoding it was tried and measured on the corpus against a controlled
baseline -- the same tree, the same presets, the same trace window, differing
only in this change. Writing the attack as an *N*-entry prefix (capped at
three, since the fifth wavetable slot is the stop and the fourth carries the
sustained waveform) moves **18 files and costs 82 points of wave agreement**,
taking the corpus mean from 62% to 61%:

| file | wave | | file | wave |
|---|---:|---|---|---:|
| Skate or Die intro | −13 | | Thanatos | −6 |
| Kings of the Beach ingame | −9 | | ACE II | −5 |
| Trans-Atlantic Balloon | −8 | | W.A.R. Preview | −4 |
| Lightforce | −7 | | Delta, Food Feud, IK+, Saboteur II | −3 each |
| Sigma Seven | −7 | | Deep Strike, Pandora, Wiz | −2 each |
| Tarzan | −6 | | **Dragons Lair II** | **+2** |

Only one file gains. A second encoding -- making the attack the *sustained*
waveform wherever `frames` exceeds what the table can spell, which is what a
note shorter than `frames` actually plays -- was also tried and was worse
still; its numbers were taken before v0.5.64 changed which subtune the harness
traces, so they are not quoted here.

A Goattracker wavetable steps one entry per *play call*, so a two-to-three
frame transient is only worth writing if it lands on the same frames as the
original's, and for most of these files the note onsets are not aligned that
closely. The reading is certain; the encoding is not, so the reading ships and
the encoding does not.

**Lesson, and it is the second time this section has had to record one:** a
correct reading of the player can still be the wrong thing to write. Keep the
two decisions apart — resolve what the byte means from the 6502, then decide
separately, by measurement, whether the target format can carry it. Landing
the reading with nothing consuming it costs one dataclass field and saves the
next reader from re-deriving it.

#### v0.5.179: the measurement was right and the conclusion was too narrow

A listener reported Trans-Atlantic's **drums missing**. They are: the
conversion sounds **0 frames of noise against the original's 1089**. Its GT 2
is `$81` noise for four frames before its pulse — 226 notes of drum played as a
pulse — and its GT 4 has *no waveform of its own at all* (`+2` is `$00`), so the
attack is the only waveform it ever has and the instrument was silent for all 70
of its notes. Every one of those is this block, read and unused.

The obvious suspect for the −82 was §7.ddd: a 1–4 frame transient is exactly
what a 3–8 frame misalignment destroys, and until v0.5.175 every per-frame
column was charged that offset. So it was re-measured under the aligned
harness — **and came back the same**, −0.6pp mean and Tarzan −14. The original
finding stands, on a better instrument.

What was too narrow was the conclusion drawn from it. `wave` is an agreement
percentage, and restoring the transient moves it the wrong way *even when the
transient is right*: Trans-Atlantic gains its 250 missing noise onsets at
exactly the original's per-instrument counts (GT 2: 226, GT 5: 24) and `wave`
falls 71% → 65%. Meanwhile "we sound no noise whatever and the original sounds
1089 frames of it" is not a disagreement any percentage can express, because
there is nothing on our side to disagree *with* — the same one-sided shape
`noise`, `pul` and `filt` exist for.

So it ships as `--two-stage`, off by default, selected per song by
`presets.py --fidelity` on that one-sided criterion: **the original sounds noise
and we sound none** — bounded, because restoring a register has to mean landing
*closer* to the original than nothing did (`|ours - theirs| < theirs`). That
bound is not decoration: without it the criterion took Sigma Seven, whose
attack sounds 82 noise frames where the original sounds 41, and drums invented
at twice the rate are not an improvement on drums missing. Four files take it —
ACE II, Pandora, Thundercats, Trans-Atlantic — and `fidelity_better` still
refuses any candidate that loses notes, so the §7.eee failure mode cannot come
back through the new door. Deliberately *not* scored on `wave`, for the reason
measured above.

The corrected lesson: **an encoding that costs an agreement column can still be
right, if what it buys is something no agreement column can see.** The 2019-era
conclusion — reading yes, writing no — was correct about the cost and never
asked what the cost bought.

---

### 7.x Finding the table when the player does not store inline

Every signature in the instrument chain fingerprints the **store** into the
SID: `LDA record,X` followed by `STA $D40x,Y`. That is a fair fingerprint for
most of the family, and a blind spot for any player that reaches the SID
through a subroutine. `Phantoms_of_the_Asteroid` does exactly that —

```
E0F9  BD 36 E4  LDA $E436,X     ; this voice's instrument index
E0FC  8E 3C E4  STX $E43C
E0FF  0A 0A 0A  ASL ASL ASL     ; x8, the record size
E102  AA        TAX
E103  BD 69 E4  LDA $E469,X     ; record +2, the waveform
...
E112  BD 67 E4  LDA $E467,X     ; record +0
E115  20 4E F0  JSR $F04E       ; ... written by a trampoline, not STA $D402,Y
```

— so it matched nothing, converted with **zero** instruments, and every note
named an instrument the `.sng` did not contain. Goattracker plays that as
silence, and the file sat in the report as `silent` for the project's whole
history.

Fingerprinting the **load** instead is dialect-independent, because the
index-to-offset arithmetic is the same wherever the bytes end up going:

```
BD ?? ??  8E ?? ??  0A 0A 0A  AA  BD ?? ??
```

The trailing operand is the record's `+2` field, so the table base is that
address minus two. The shape is present in 70 corpus files and names the same
base the store-shaped chain already found in **68** of them; the two it does
not are the digi engine, whose 16-byte records have their own detection path.
It is consulted last, only once every other signature has failed, so it can
rescue a file that reads nothing and can never move one that reads correctly
— 94 of 95 corpus conversions are byte-identical, and the 95th is Phantoms,
which goes from `silent` to melody 53%.

### 7.y The instrument a voice starts on

The first operand of that same match names the **per-voice instrument index
array**, and it answers a separate question. The player writes the array only
when a pattern carries an instrument byte, so a voice whose first note is
reached before any pattern names one sounds whatever the array held.
Goattracker carries instruments forward the same way — `gplay.c:914` assigns
`cptr->instr` only on a non-zero column — but starts every channel on
instrument 1 (`gplay.c:223`), which H2G writes as an empty record. Those
voices come out silent.

41 of the corpus's 821 voice orderlists begin that way.
`Delta_Mix-E-Load_loader` is the unambiguous case: three orderlists of one
pattern each, patterns `$18` and `$17` with no instrument byte anywhere, and
`$C535` reading `03 09 00` — the three records whose ADSR (`3A98`, `BC5D`,
`0CF8`) siddump shows the original playing, with voice 1 as a built-in
control because its pattern names `$09` explicitly.

**But the array is mutable state, not a constant**, and that is the boundary
this reading has. Its file-image value is the starting instrument only for a
rip of a single tune. `Commodore_64_Music_Examples` carries fifteen subtunes;
its array reads `00 07 05`, naming records with ADSR `4764`/`2524`/`2740`
while the original plays `5C3A`/`1858`/`0868`. The snapshot caught the array
mid-tune, and nothing static can recover what each subtune starts from. So
the reading ships as `--initial-instrument` and is deliberately **not** in
`presets.json`'s `always` block — a rule that is right for a jingle and wrong
for a demo does not belong in a block that claims to be right for everything.

### 7.z The envelope: a misread register and an invented reset

Two defects sat in the envelope for the project's whole life, and neither was
findable from the report. Both were raised by the first listening pass, in
the form *"the notes sound correct, but the sounds are not correct"*.

**The sustain nibble.** The VB6 original masks bit `$10` out of any
sustain/release byte `>= $F0` (`h2g.frm:578-579`). Its comment states the
field as `SSSX RRRR` -- three bits of sustain, one spare, four of release.
SID register 6 is `SSSS RRRR`: four bits each. There is no spare bit, so the
mask does not discard a flag, it turns a sustain of F into E on every
instrument that asked for full sustain. That is the level the note holds for
its entire duration, so it is audible for longer than anything else in the
record. The port inherited the mask verbatim; `--sustain-exact` removes it and
reaches 64 of the 83 convertible files.

This is worth generalising: **an inherited comment is not evidence.** The mask
survived the port because the comment explained it, and the explanation was
confidently wrong about a register whose layout is in the datasheet.

**The hard restart.** Goattracker writes its `HR` parameter -- default
`$0F00` (`goattrk2.c:49`), baked into the packed player as `ADPARAM`/`SRPARAM`
at `greloc.c:1138` -- into `$D405`/`$D406` for one frame before every note,
unless the instrument sets `gatetimer` bit `$80` (`gplay.c:930-937`; the flag
is defined at `gsong.c:381`). This is standard C64 practice: it resets the
envelope generator so an attack lands reliably.

Hubbard's players do not do it. `$0F00` occurs in **no** corpus original, and
is the **most common ADSR value in every conversion** that does not set the
bit. So the converter was adding an envelope reset to every note in music
that never had one. `--no-hard-restart` sets bit `$80` on every instrument
read from the file; it deliberately does not set bit `$40`, which suppresses
the gate-off too and would stop notes releasing.

Note the asymmetry with the rest of this document: the other readings here
recover something the player *does*. This one removes something the *target
format* does. A converter inherits defaults from both ends, and the ones from
the output side are harder to notice because nothing in the input contradicts
them.

**Measured.** Per-frame ADSR agreement across the 83 convertible files, each
voice's last written value carried forward between writes:

| | agreement |
|---|---:|
| inherited | 54.2% |
| `--sustain-exact` | 60.6% |
| `--no-hard-restart` | 59.3% |
| both (shipped, in `always`) | **66.2%** |

The cost is one file: hard restart exists for a reason, and Confuzion drops
82% → 78% melody. Nothing else moves on melody, sequence, pitch or waveform
-- because when this shipped, **no column in `FIDELITY.md` compared ADSR at
all**. The table above comes from a separate comparison of siddump's `ADSR`
column written for this change, not from the report. Since v0.5.78 the report
has an `adsr` column that makes exactly this comparison per frame and per
voice, so the next change to the envelope will be visible where the last one
was not; the numbers above are left as they were measured rather than
restated from it.

### 7.aa The pulse width: a sweep written as a constant

The third defect the first listening pass raised, alongside the two envelope
ones in 7.z and the filter in 7.y. All four are the same shape: the notes were
right, the *sound* was not, and no column in `FIDELITY.md` could report any of
them at the time. All four are reportable now — v0.5.78 spent the registers
`parse_dump` had started reading on an `adsr` column, a `pul` column and a
`filt` column — which is why the sections below still quote the hand
measurements that were the only evidence when each change landed.

H2G wrote each instrument's pulse width once and stopped -- two pulse-table
entries, "set `$XYY`" then "stop". That is exactly right for the **328**
corpus instrument records whose sweep rate is zero, and wrong for the **414**
that sweep, across **43 of 95 files**.

The player's routine is self-modifying, which is what makes it readable
without ambiguity. It loads one byte from an array parallel to the instrument
records, splits it into nibbles, and **patches each nibble into the operand of
one of its own compares**:

```
LDA bounds,Y / AND #$0F / STA <operand of the descending CMP>
LDA bounds,Y / LSR x4   / STA <operand of the ascending CMP>
```

so both turning points are provably the two nibbles of that one byte. It then
adds or subtracts instrument byte `+6` -- the rate -- to a 12-bit per-voice
accumulator and flips direction when the high nibble reaches a bound, writing
`$D402`/`$D403` every frame. A triangle wave on the duty cycle.

The signature requires **both** halves: the sweep block gives the bounds array
but not which record byte holds the rate, and the note-start block that copies
the rate proves nothing about what it is for. What ties them is the `8D`
naming the same cell the sweep reads. 43 files match both; the rate is record
`+6` in all 43, and the bounds array's distance from the records varies from
+12 to +348 bytes, so its address is read from the instruction rather than
assumed.

Goattracker expresses this natively (`readme.txt:887-891`, `gplay.c:872-902`):
set, ascend, descend, jump. The encoding carries two stated approximations --
the turnaround lands a fraction of a step early, and the table steps per play
*call* where the player steps per *frame*, so `-S2` halves the speed and
doubles the ticks. A leg longer than 127 ticks becomes consecutive steps of the
same speed, which `gplay.c:902` executes identically.

| | pulse-width changes in 20 s, 37 files |
|---|---:|
| the original tunes | 60056 |
| inherited | 757 (**1%**) |
| `--pulse` | 35892 (**60%**) |

Mean melody and mean waveform agreement are **identical to the decimal** with
and without it. `wave` compares the waveform *class*; pulse is pulse whatever
its width. This was the seventh change in the project's history that is real,
verified against the 6502, and completely invisible to the report -- which was
the argument for building the `Pul` metric rather than a reason to doubt it.
That metric exists as of v0.5.78: the `pul` column counts duty-cycle movement
on each side, in the same ours/original form the table above uses.

### 7.bb Per-frame rates written into per-call tables

Every rate read out of a Hubbard player is *per frame*. The player is a raster
interrupt: the drum sweep decrements the frequency high byte once a frame
(Warhawk `$1387-$138D`), the chromatic rise steps a semitone every fourth frame
(`$13A2`), a pattern slide adds its 16-bit step once a frame (`$1320`), and an
instrument's attack waveform stands for one frame.

Every place Goattracker takes those numbers is *per play call*. Speed-table
deltas are applied inside the per-call `TICKNEFFECTS` (`gplay.c:748/758`) and
the wavetable advances one entry per call (`gplay.c:707`).

Those units are the same thing only at `gt2reloc -S1`. **33 of the 83 preset
corpus songs pack at `-S2`** — a CIA stub calling the player at 100 Hz, which
is the only way their tempo is expressible at all (§ *the fastest steady row is
3 calls*). In every one of them, until v0.5.82, each of those rates ran at
exactly twice the player's: slides bent twice as far per frame, the drum swept
twice as deep, the rise glided twice as fast, and the attack waveform lasted
half a frame instead of one.

The repo had stated the mismatch in its own words for twenty versions without
drawing the conclusion — `goatwriter.py`'s `DRUM_SPEED` comment described "256
units per frame" and then wrote it into a per-call table.

The fix is division at the point of encoding, by the `-S` factor the file will
be packed at, which `convert()` already derives for the tempo:

| rate | where | at `-S{m}` |
|---|---|---|
| pattern slide | speed-table entry, `build_speed_table` | 16-bit step ÷ m — **exact**, the table stores the whole step |
| pattern slide, GTS2 | the pattern data column | ÷ m rounded — the column holds an eighth of the step and the loader multiplies (`gsong.c:311-321`) |
| drum sweep | `_drum_speed` | 256 ÷ m, floored, never 0 |
| chromatic rise | `_rise_speed_index` | one more right-shift per doubling |
| attack transient | a wavetable delay entry `$01-$0F`, or the waveform again | held m calls instead of 1 — off by one until v0.5.130, § 7.mm |

**3023 of the corpus's 5566 portamento commands (54%) are in a file that packs
at `-S2`.** The differential is clean: exactly the 33 multiplier-2 songs change
bytes and not one of the 50 multiplier-1 songs does.

Three residuals, named rather than left to be re-found:

- ~~**The arpeggio alternation stays at the call rate.**~~ Closed in
  v0.5.130: the jump target buys the missing slot by looping through entry 0.
  See § 7.mm.
- **The drum shape has no slot for the transient delay** either — all five
  entries are the attack, the gate-off waveform, the sweep and two stops — so
  its attack still lasts one call. Spending the sweep to buy the frame would
  give back more than it bought.
- **The rise's shift is exact only for powers of two.** At `-S3` the rise
  glides ¾ of the player's rate where before it glided three times it. This
  was written when no corpus file asked for `-S3`; since § 7.kk's fractional
  rows, 15 files pack at 3, 4, 5 or 6 and the residual is live.

**One column moved anyway, and it is worth understanding why.** `slides`
counts frames on which siddump printed a bare frequency delta, and it moved on
8 of the 33 — 7 of them toward the original. The trace says exactly what
happened: Flash_Gordon's emitted step went from `(+ 03FC)` to `(+ 01FE)`, a
literal halving, and a slower slide spends more frames moving before it
arrives. That is the division showing up in the register writes, not the
harness measuring the call rate; siddump still traced both runs at 50 Hz.

The same trace turned up a **larger, older defect standing behind this one** —
`$03FC` is `0xFF * 4`, the clamp in `min(step // 4, 0xFF)`, and **2189 of the
corpus's 5566 portamento parameters (39%, in 15 files) sat on it**. That is
§ 7.cc.

**Nothing else in `FIDELITY.md` can move on any of this, and that is a fact
about the harness, not about the fix.** siddump calls the play routine `seconds × 50`
times whatever the PSID speed field says (`siddump.c:309/325`), so in the trace
every file behaves as multiplier 1 and a multiplier-dependent change is
invisible *by construction* — the same reason § *the shelved transient
encodings* could not have been biased by the multiplier either. The evidence
that this reaches anything is the differential hash above and
`tests/test_call_rate.py`; the evidence that it reaches the right thing is
`gplay.c` and the 6502. Confirming it audibly needs RetroDebugger, which
honours the CIA rate, or a listening pass.

### 7.cc The slide step: one fetch shape, two dialects, and an 8-bit column

A pitch slide is a 16-bit step split across two pattern bytes — the command
operand and a byte fetched after it. `detect.SLIDE_OPERAND_SHAPE` finds the
fetch (41 of 95 corpus files have it). **It does not say which byte is which
half, and two players disagree.**

Warhawk `$1320`, the routine this converter was built on:

```
1320  BD B7 15  LDA slidelo,X       ; the command operand
1325  29 7E     AND #$7E            ; ... IS the step's low half
132A  BD B7 15  LDA slidelo,X
132D  29 01     AND #$01            ; ... and its bit 0 is the direction
132F  F0 1C     BEQ add
1332  BD B4 15  LDA freqlo,X / SBC $1588 / STA $D400,Y
133E  BD B1 15  LDA freqhi,X
1341  FD BA 15  SBC slidehi,X       ; the fetched byte is the HIGH half
```

Flash Gordon `$12EB` — same fetch shape, halves the other way round, and the
direction taken from a threshold rather than a bit:

```
12EB  BD 40 15  LDA slidelo,X
12F0  C9 BF     CMP #$BF
12F2  90 1A     BCC up              ; < $BF adds, >= $BF subtracts
12F4  29 3F     AND #$3F            ; the operand is the step's HIGH half...
12F6  8D 07 13  STA $1307           ; ...self-modified into the SBC below
12FA  BD 3A 15  LDA freqlo,X
12FD  FD 3D 15  SBC slidehi,X       ; the fetched byte is the LOW half
1303  BD 37 15  LDA freqhi,X
1306  E9 08     SBC #$08            ; <- operand written at $12F6
```

Byte-for-byte the same routine, relocated, in Sanxion `$B2E1` and Delta
`$C0D6`. The `CMP` immediate is `$BF` in all 22 matches and the mask `$3F` in
all 22, so both are literals rather than parameters.

**The census partitions cleanly, the way `+7`'s two formats do:** 25 corpus
files have Warhawk's consumer, 22 have this one, and **none has both**. 22 of
the 41 files with the two-byte fetch were being decoded with the halves
swapped — a step about 256× too large.

#### The column that hid it

`patterns.py` packed the step as `min(step // 4, 0xFF)`, because the pattern
data column is one byte. A step read 256× too large therefore did not look
wrong, it looked *saturated*: **2189 of the corpus's 5566 portamento
parameters (39%, in 15 files) sat on that clamp**, and all 15 are in the
swapped dialect. The clamp was not the defect; it was the defect's hiding
place.

Correcting the dialect alone made it worse in the other direction — 250
columns whose true step was under 4 now packed to zero, which `gplay.c` reads
as *no parameter at all*. Both ends are the same mistake: an 8-bit column
carrying a 16-bit quantity.

**In a GTS5 file that column does not need to carry the value.** It ends up a
1-based speed-table index anyway (`gplay.c:740`), and the table stores the step
at full 16-bit width — so the decoder now writes the index directly and keeps
the steps beside the patterns (`patterns._step_index`). Nothing saturates and
nothing rounds to zero. The ceiling is 255 distinct steps per file; the worst
corpus file has **40**.

A GTS2 file keeps the packed byte, because its loader reads that column as the
value (`gsong.c:311-321`) and there is no stored table for an index to name.
That is a real format limit rather than an oversight, and it is one more reason
the presets use gts5.

#### What it measured, and the column that had to be built to see it

`slides` — frames on which the frequency moved — said the fix made things
**worse**: Flash_Gordon 635 → 266 against an original of 740. It was measuring
the wrong thing. siddump prints pitch movement in two forms, a bare delta
(`(+ 03FC)`) and a parenthesised note, choosing between them by whether the new
frequency lands near a note in its table. A change in step *size* moves frames
between the two forms, and `slides` counts only the first: Flash_Gordon's ties
rose 181 → 340 as its slides fell, and its *total* pitch movement rose 518 →
552 against the original's 569.

A count cannot judge a step size — the same lesson `cut` had to be built for
next to `filt`. **`bend` is the pitch counterpart**: our summed frame-to-frame
movement of `$D400/$D401`, excluding every frame the voice changes note on,
over the original's. On it the fix reads **1.67x → 1.51x** — still overshooting
the original's travel, but by less — and the reading does not depend on which
form siddump chose.

| | before | after |
|---|---:|---:|
| portamento parameters on the clamp | 2189 of 5566 (39%) | none — no clamp |
| Flash_Gordon `slides` (orig 740) | 635 | 266 |
| Flash_Gordon **`bend`** | 1.67x | **1.51x** |

**Those `bend` figures are not the ones v0.5.83 shipped**, which read 0.30x →
0.66x. The dimension's first cut excluded only *attack* frames, so a **tie** —
a note change the player did not re-gate — counted its whole pitch jump as
bending. It inflated the original side wherever a player uses legato:
Pygmies_Revenge, which ties 493 times in ten seconds, read 21.7 million units
of travel against about 12 thousand of real bending. v0.5.84 excludes ties
too. The direction of the v0.5.83 verdict survives the correction and its
magnitude does not, which is the second time in three versions that a number
about the converter turned out to be a number about the harness.

Only one corpus file moves either number, because the other 16 whose bytes
changed emit no pitch movement at all in the traced window — which is what
§ 7.dd is about.

### 7.dd Why a third of the corpus bends nothing: the vibrato was never written

`bend` was built to judge a step size and immediately answered a bigger
question. **33 of 95 corpus files move the pitch not at all where the original
moves it**, and the corpus median `bend` is **0.06x** — the converter produces
about a sixteenth of the pitch movement its sources do.

Sorting those 33 by *what the original is doing* in those frames settles it.
Take the summed movement and the **net** movement of each voice, excluding note
changes: a sweep travels (net ≈ total), a vibrato returns (net ≈ 0).

| net / total | reading | files |
|---|---|---:|
| < 0.25 | vibrato — it comes back | **20** |
| 0.25 – 0.6 | mixed | 11 |
| > 0.6 | a sweep that travels | 2 |

Warhawk is typical: 419 moved frames against 52 attacks in ten seconds, in
matched pairs — 104 × `(+ 0034)` against 97 × `(- 0034)`, 80 × `(- 0037)`
against 79 × `(+ 0037)`, and so on, with the depth growing with pitch.

**And it is not in the patterns at all.** Warhawk applies it between the
frequency-table lookup and the SID write, at `$1245`:

```
1245  B9 AC 14  LDA $14AC,Y / STA $158E   ; the note's frequency, lo
124B  B9 AD 14  LDA $14AD,Y / STA $158F   ; ...and hi
1251  BD C3 15  LDA $15C3,X               ; the voice's vibrato counter
1254  4A        LSR A / TAY / DEY
1257  30 16     BMI out
1259  38 AD 8E 15 ED 8C 15 ...            ; freq -= depth ($158C/$158D),
126C  4C 56 12  JMP $1256                 ; ...counter/2 times
1294  AC 6F 15  LDY $156F
1297  AD 8E 15  LDA $158E / STA $D400,Y   ; only now does the SID see it
```

The pitch the SID receives is `note − (counter / 2) × depth`, with the counter
oscillating. Nothing the ripper reads — pattern bytes, instrument records,
orderlists — carries it; it is player state.

**Goattracker can express exactly this, and the writer zeroes the two bytes
that would.** `gplay.c:352-354`, on every new note:

```c
cptr->vibdelay = iptr->vibdelay;
cptr->cmddata  = iptr->ptr[STBL];
```

so a channel with no pattern command falls through `CMD_DONOTHING` into
`CMD_VIBRATO` (`gplay.c:769-780`) once the delay expires, taking its half-period
and depth from the speed-table entry the *instrument* names. Those are record
bytes 5 and 6 — and `goatwriter._write_instruments` writes:

```python
out += bytes([ad, sr, wave_ptr, pulse_ptr, filt_ptr, 0x00, 0x00,
              gatetimer, 0x09])
```

`0x00, 0x00`: no speed-table pointer, no delay. **No file this project has ever
produced has vibrated**, and `CMD_VIBRATO` is never written into a pattern
either. Better still, the note-relative speed form (`cmpvalue >= 0x80`,
`gplay.c:786-792`) computes the depth from the semitone interval at the current
note — which is the shape Warhawk's trace shows, the depth growing with pitch.

The other two causes of a zero, both smaller and both structural:

- **10 files have no slide path in their decoder at all** — the 9 digi-grammar
  files and Hollywood_or_Bust's cmdtable grammar. `_build_raw_pattern_digi` and
  `_build_raw_pattern_cmdtable` emit no portamento command in any branch.
- **11 classic-grammar files emit zero portamento commands** because their
  players have no two-byte fetch for `--slides` to read.
- The remaining 12 *do* emit portamento — on 0.3% to 3.4% of their rows, and
  often late. Warhawk's 112 commands sit in 4 of 65 patterns, first named at
  orderlist position 86 of 91; sixty seconds of trace never reach them.

So the ranking is clear and the cheap fix is the big one: **the missing pitch
movement is mostly vibrato, and vibrato costs two bytes per instrument record
plus one speed-table entry.** That is § 7.ee.

### 7.ee Vibrato: one record byte, and Goattracker says the same thing

The parameter is a single instrument-record byte, and the player splits it in
two. Warhawk `$11EF`:

```
11E7  B9 3C 16  LDA record+5,Y
11EA  D0 03     BNE on              ; zero -> no vibrato at all
11EF  48        PHA
11F0  29 78     AND #$78            ; bits 3-6: the amplitude bound
11F2  4A 4A 4A  LSR A x3            ;           ... >> 3, so 0..15
11F5  9D C3 15  STA bound,X
11F8  68        PLA
11F9  29 07     AND #$07            ; bits 0-2: a right-shift
11FB  8D 8A 15  STA shift
```

and the depth, at `$1221`, is what makes this map onto Goattracker at all:

```
1221  BD 7F 15  LDA note,X
1224  0A A8     ASL A / TAY
1226  38        SEC
1227  B9 AC 14  LDA freqtbl+2,Y
122A  F9 AA 14  SBC freqtbl,Y       ; the semitone interval AT THIS NOTE
122D  8D 8C 15  STA depth           ; ... then >> shift
```

That is `gplay.c:786-792` written in 6502. A Goattracker speed-table entry with
bit `$80` on its left side selects a **note-relative** speed, computed as the
semitone interval at the current note shifted right by the entry's right byte.
The player and the tracker express vibrato depth the same way.

**The census is the cleanest in this document.** 56 of 95 files match the
split; the masks are `$78` and `$07` in **all 56**; the byte is at record `+5`
in every one whose addressing the reader recognises (49 of 56 — the other 7
reach it some other way and are skipped, an under-read); and **all 56 also
carry the note-relative depth**. Unlike `+7`, this is a shared format.

The mapping, derived rather than fitted:

* the player's counter steps once per frame between 0 and `bound`, so its
  half-period is `bound` frames; Goattracker's is `cmp + 2` **calls**
  (§ 7.kk). Match the period: `cmp = bound × multiplier − 2`.
* the player's apply loop only ever *subtracts*, so `(bound >> 1) × depth` is
  a peak-to-peak, not an amplitude; Goattracker's peak-to-peak is
  `(cmp + 2) × speed`. Match the excursion under the period above:
  `rshift = shift + 1 + log2(multiplier)`.
* Both numbers here are the **corrected** ones (v0.5.129). This section
  originally read Goattracker's half-period as `cmp / 2` and emitted
  `cmp = 2 × bound × multiplier`; see § 7.ll.
* So the entry is `($80 | cmp, rshift)`, the instrument's `ptr[STBL]` is its
  1-based index, and `vibdelay` is 1 — none of these players delays the onset.

Two stated approximations: the player applies its counter as a *position*, an
absolute offset from the note, where Goattracker integrates a step — the same
triangle reached differently; and Goattracker takes the interval *above* the
note where the player takes the one below, about 6% of a semitone.

**And the two bytes were there all along.** `gplay.c:352-354` loads
`cptr->vibdelay = iptr->vibdelay` and `cptr->cmddata = iptr->ptr[STBL]` on
every new note, and a channel with no pattern command falls through
`CMD_DONOTHING` into `CMD_VIBRATO`. Those are instrument-record bytes 5 and 6
in a GTS5 file (`gsong.c:224-225`) — and this writer had emitted `0x00, 0x00`
there since the port began.

| | before | after |
|---|---:|---:|
| corpus median `bend` | 0.06x | **0.33x** |
| files bending nothing where the original bends | 33 | **11** |
| files moved toward the original / away | — | **29 / 6** |
| any other dimension moved | — | none |

All six that moved away were **already overshooting** before vibrato existed —
Thrust 3.74x, Delta_Mix-E-Load 9.84x, Zoolook 9.38x, Bump_Set_Spike 11.45x.
Adding a correct vibrato to a file that already bends ten times too far makes
the number worse and the file no less right; that overshoot is the slide step,
a separate defect, and it is now the thing `bend` is pointing at.

**GTS5 only.** A GTS2 file stores no speed table: its loader packs the vibrato
into one instrument byte and calls `makespeedtable` itself (`gsong.c:285`), and
it reads bytes 5 and 6 *the other way round* (`vibdelay` first, `:284`). Same
numbers, different encoding — and the byte-exact fixture is a GTS2 file.

### 7.ff The digi engine's own slide, and what its bend number really counts

The digi grammar has two two-operand effects. § 5 recorded both as "parsed for
their length but not translated". One of them is a pitch slide.

Off the Cuff's handler stores the operands at `$1133` and its consumer adds
them every frame at `$134C`:

```
1133  C8 B1 FA  INY / LDA (patt),Y
1136  9D 7B 16  STA slidehi,X       ; the FIRST operand is the HIGH half
1139  C8 B1 FA  INY / LDA (patt),Y
113C  9D 78 16  STA slidelo,X       ; the second is the low half
1140  DE 7E 16  DEC gate,X          ; 0 -> $FF, "slide running"

134C  BD 7E 16  LDA gate,X / BEQ out
1351  18        CLC
1352  BD 75 16  LDA freqlo,X / ADC slidelo,X / STA freqlo,X
135B  BD 72 16  LDA freqhi,X / ADC slidehi,X / STA freqhi,X
```

One `CLC / ADC` pair and no direction test, so the step is **signed**: a high
byte of `$80` or above slides down. The gate is cleared at every note start
(`$10F4`), which is what Goattracker does with a channel's command
(`gplay.c:351`), so the two persist alike — and `$82` maps onto CMD_PORTAUP /
CMD_PORTADOWN directly, through the same full-width step collector the classic
decoder uses.

`$83` turns out to be a **vibrato** in the very same `$78`-bound / `$07`-shift
format as § 7.ee, overriding the instrument's own byte for the rest of the note
(`$1229`, falling back to `$1704,Y` at `$123F`). It stays untranslated:
`--vibrato` already emits the instrument-level parameter, and a row has one
command column.

**All nine digi files carry both shapes. The music barely uses `$82`** — 128
portamento columns across 5 of the 9, none at all in the other 4. So this is a
correctness fix with a small footprint, and no dimension in the report moved on
it. That is stated rather than glossed: the evidence is the 6502 and the 128
columns, not a number.

#### What the digi files' `bend` was actually measuring

Chasing why those files still scored near zero produced a better finding than
the slide did. **`bend` cannot tell a pitch bend from a voice being used as a
sample channel**, and the digi engine plays its samples by rewriting a SID
voice's frequency every frame:

| Off the Cuff, original, 10 s | voice 1 | voice 2 | voice 3 |
|---|---:|---:|---:|
| pitch travel | 3,032 | 8,855 | **5,426,086** |

99.8% of that file's `orig_bend` is the digi channel, so its ratio is not a
score of the conversion at all. An octave guard — reject a frame whose
frequency ratio exceeds 2 — was tried and **rejected**: it removed only a sixth
of the sample movement (5.43M to 901k) while costing real signal elsewhere
(Delta 56,531 to 40,429, two voices zeroed outright). A threshold that keeps
vibrato and drops sample playback is two orders of magnitude wide and would be
a number chosen to fit, so the limit is documented instead — in the report's
own *What this does not say*.

### 7.gg The command-table engine's slide, which nothing in the corpus uses

The third grammar has one too. Hollywood or Bust `$071B` and Chicken Song
`$1301` are byte for byte the same routine:

```
071B  BD 9A 09  LDA dir,X           ; operand 2, raw
071E  10 1C     BPL up              ; bit 7 clear -> add, set -> subtract
0720  38        SEC
0721  BD 97 09  LDA freqlo,X
0724  FD A5 09  SBC steplo,X        ; operand 1 is the step's LOW half
0727  9D 97 09  STA freqlo,X / STA $D400,Y
072D  BD 94 09  LDA freqhi,X
0730  FD 9D 09  SBC stephi,X        ; operand 2 AND #$3F is the HIGH half
0733  9D 94 09  STA freqhi,X / STA $D401,Y
```

with a handler (`$084D` / `$1430`) that stores the three operands in the same
order in both files: step low, direction-and-high raw, then a per-voice onset
delay in frames. Goattracker has no per-command delay, so that third operand is
read and dropped — the one approximation in the mapping.

It is the **high-first dialect** again (§ 7.cc): `AND #$3F` for the high half.
The direction is bit 7 rather than a `CMP` threshold because the two bytes are
separate operands rather than a command byte and a fetched one.

The command index is not assumed. The consumer names the cells, the handler
that fills them names the command, and `_cmdtable_slide` accepts it only if the
handler stores them in the order the consumer reads them. Both files answer
command 1.

**And neither file uses it.** Walking their patterns, Hollywood or Bust reaches
commands 0, 2, 4, 5 and 6 and Chicken Song 0, 2, 4 and 5 — never 1. The
converted output is byte-identical on all 83 preset songs, which the A/B mode
reports as *"this change reaches nothing"*, and that is the correct reading:
the grammar is now read completely and the corpus does not exercise this part
of it.

Worth having anyway, for a reason specific to this engine: an unread command
here desynchronises nothing (its operand count was always honoured), but a
*misread* one would, and the reading is now pinned by tests rather than left to
be re-derived by the next person who sees `$81` in a pattern.

#### What Hollywood or Bust's missing bend actually is

Not the slide. Its pitch movement is **vibrato driven by a table**, which is a
third form again — neither the classic `$78`/`$07` pair nor anything
Goattracker has:

```
05F3  BC B1 09  LDY lfo_index,X / INC lfo_index,X   ; one entry per frame
05F9  B9 DF 09  LDA $09DF,Y / CMP #$FF              ; $FF wraps to 0
060E  BD 7A 09  LDA note,X / ASL / TAY
0613  38 B9 A7 08 F9 A5 08   SEC / LDA freq+2,Y / SBC freq,Y   ; the interval
0622  4A 66 4D  LSR / ROR x4                        ; >> 4
0630  AC 86 09  LDY count / ... ADC ... DEY / BNE   ; x the table entry
```

so the frequency offset each frame is `(interval >> 4) × table[i]` — an
arbitrary LFO shape, where `--vibrato` reads a bound and a shift. Goattracker's
vibrato is a fixed triangle, so this can only ever be approximated: the table's
peak gives the excursion and its length the period. That approximation
**is** implemented -- see § 7.kk, which also corrects what § 7.ee
assumed Goattracker's half-period to be.

### 7.hh The overshoot: three quarters of it was the metric

Going after the files that bent *too far* — Bump_Set_Spike 11.8x,
Delta_Mix-E-Load 10.8x, Zoolook 9.7x, Confuzion 9.0x — found the fourth defect
in `bend` before it found anything in the converter.

`bend` was differencing siddump's frequency column between frames and excluding
the frames siddump marked as a note. That is not the same set as "frames that
are not a note change". **A Goattracker wavetable entry whose right side is a
relative note rewrites the frequency without touching the gate**, and siddump
prints that as a frequency with an empty note field — so every note onset in
our output contributed its whole interval as "bending". Zoolook scored 121,107
units where its *printed* bends total about 3,400.

The fix is to stop re-deriving the quantity. siddump prints `(+ xxxx)` /
`(- xxxx)` exactly when the frequency moved and it judged the voice to be on
the same note — which is the definition. `bend` now sums those magnitudes, so
it and `slides` are a count and a sum of the same lines, the way `filt` and
`cut` are.

| | before | after |
|---|---:|---:|
| Delta_Mix-E-Load_loader | 10.80x | **0.96x** |
| Zoolook | 9.65x | **0.26x** |
| Confuzion | 8.96x | **0.00x** |
| Thing_on_a_Spring | 3.36x | **0.35x** |
| Chain_Reaction | 2.19x | **0.26x** |
| Knucklebusters | 1.64x | **0.00x** |

That is four corrections to one dimension in six versions — excluding only
attacks, then ties as well, then bare frequency writes, and finally not
computing it here at all. The through-line: **every version that re-derived the
quantity from raw registers was wrong, and the one that takes the tool's own
answer is not.**

#### What survived, and the drum sweep's second measurement

Three files still overshoot for a reason in the converter, and it is the same
one: **the drum sweep fires where the player's does not.** `_drum_entries`
writes one 256-unit downward step for any instrument whose effect bit `$01` is
set in a player that has the routine — but the player's block also needs its
per-voice length and counter cells armed (`$1372 LDA $1576,X / BEQ out`), which
is runtime state no static read can see. Bump_Set_Spike's original plays **no**
256-unit step at all in the traced window; ours plays 64.

So the sweep was re-measured, this time against pitch rather than waveform:

| | with the sweep | without |
|---|---:|---:|
| Bump_Set_Spike | 11.79x | **0.34x** |
| Phantoms_of_the_Asteroid | 4.40x | 0.00x |
| Gerry_the_Germ | 2.29x | 0.00x |
| Game_Killer | **1.08x** | 0.00x |
| Crazy_Comets | **1.03x** | 0.00x |
| corpus median `bend` | **0.25x** | 0.15x |
| mean `wave` | 61.7% | 61.7% |

**Removing it is right for one file and wrong for eight.** Game_Killer and
Crazy_Comets sit at 1.08x and 1.03x *because* of it and drop to zero without
it. So the sweep stays. What gates it is § 7.ii.

#### `Thrust` at 43x is not an overshoot at all

The last one turned out to be neither the metric's arithmetic nor the
converter's magnitude. **It is the deliberate glide-versus-step approximation
in the chromatic rise, seen through a metric that counts only what siddump
labels a bend.**

Thrust's tune *is* the rise: all three voices sweep the same run of semitones,
offset from one another. Both sides play it. The difference is how each moves:

* **The player steps.** `$13A2`'s block does `INC noteindex,X` and re-reads the
  frequency table, so every frame lands on an exact semitone and siddump names
  it — **443 tie lines against 25 bend lines**.
* **We glide.** `_rise_speed_index` emits a note-relative portamento, a
  continuous quarter-semitone-per-call slide, because Goattracker cannot step a
  note from the wavetable without one entry per semitone and the fixed
  five-entry layout has no room. A third of our frames therefore land *between*
  notes, and siddump prints those as bends — **125 tie lines against 89**.

`bend` sums bend-labelled frames and excludes ties, because a tie is normally a
legato note change. In a stepped sweep the tie *is* the pitch movement. So the
original's sweep is almost invisible to the dimension and ours is fully
visible, and the ratio comes out 43x while the two sides travel comparable
distances over the same notes.

**No converter change follows.** The approximation is the only encoding
Goattracker offers, it was recorded as deliberate when the rise shipped, and
the emitted rate is right (a semitone per four calls against the player's per
four frames, at `-S1`). What follows is a limit on the dimension:
`bend` cannot compare a stepped sweep against a glided one, and a file whose
pitch movement is mostly stepped will read as an overshoot however faithful the
conversion is. That is now in the report's *What this does not say*.

Two smaller things fell out of the same trace and are worth not re-deriving:
`--fold-transpose` is refuted as a cause (Thrust converts to identical bytes
with it on and off), and this file's `pitch` of 100% rests on **4 attacks
against the original's 2** — a sample too small to mean anything, on a tune
that is nearly all sustained sweep.

### 7.ii The drum gate: read in full, and not expressible

The block is byte-identical in every file that has it — Warhawk `$1366`,
Bump_Set_Spike `$B34B`, Gerry_the_Germ `$E2FA` — so the reading below is the
family's, not one player's:

```
1366  AD BD 15  LDA effect        ; the effect byte cell
1369  29 01     AND #$01 / BEQ out
136D  BD B1 15  LDA freqhi,X / BEQ out      ; guard 1
1372  BD 76 15  LDA remaining,X / BEQ out   ; guard 2
1377  BD 79 15  LDA status,X / AND #$1F     ; W, the note's original duration
137C  38 E9 01  SEC / SBC #$01              ; W-1
137F  DD 76 15  CMP remaining,X             ; ... against R, counting down
1385  90 10     BCC noise
1387  BD B1 15  LDA freqhi,X / DEC freqhi,X / STA $D401,Y   ; the sweep
```

`R` starts at `W` and counts down, so `W-1 < R` holds **only on the note's
first frame**. That inverts the reading § 7 shipped with: the noise is the
*attack*, not the ending, and the 256-unit sweep runs on every frame after it —
**`W-1` steps per note**, where this converter emits exactly one. Corpus-wide
the emitted drum is therefore an *under*-render, which is why deleting it costs
eight files and helps one.

**The condition is not a property of the instrument.** `LDA effect` is
`AD` — absolute, not `,X`. The cell (`$15BD` in Warhawk, `$B504` in
Bump_Set_Spike) is written in exactly **one** place in the whole player, the
note-start path, as `STA abs`. So all three voices share it, and a sweep frame
— which by construction is a frame with no note start — reads whichever voice
most recently *started* a note. A Goattracker wavetable is per-instrument and
cannot carry cross-voice runtime state, so no encoding of it exists.

Three static proxies were tried against the split (Bump_Set_Spike 11.79x,
Phantoms 4.40x and Gerry_the_Germ 2.29x overshooting; Game_Killer, Crazy_Comets,
Rasputin, Last_V8, Thing_on_a_Spring benefiting) and **all three are refuted**:

| proxy | result |
|---|---|
| the note is one tick long, so only the noise frame runs | no drum-instrument note in any of the three lasts 1 tick — lengths are 2-9 |
| the share of note-starts made by drum instruments | 30% / 14% / 39% overshooting against 14% / 34% / 23% / 32% / 19% benefiting — overlapping |
| the `freqhi` guard rejects low notes | Bump_Set_Spike's originals sit at `$02B9` and above, well clear of the guard |

And the probe is not a false positive: Bump_Set_Spike's block is Warhawk's
byte for byte, its instruments do set bit `$01` (27 of 60 records), and its
notes are long enough.

#### Running it settles it — and the answer is the metric again

The three refutations above left one hypothesis standing, that the player never
triggers the drum. **v0.5.91 ran the player and it is false.** Bump_Set_Spike's
body was extracted to a PRG at `$B000`, driven by a nine-instruction harness
(`SEI / LDA #$35 / STA $01 / JSR $B000 / loop: JSR $B016 / JMP loop`) under
VICE's remote monitor, with breakpoints on the block entry and both branches:

| over 400 breakpoint stops | |
|---|---:|
| `$B34B` block entry | 261 |
| `$B36C` **the sweep** | **78** |
| `$B37C` the noise path | 61 |
| effect cell `$B504` with bit `$01` set, at entry | **226 of 261** |

and watching the frequency-high shadows at the end of each play call shows the
sweep working exactly as read — voice 2 walking `0D 0C 0B 0A 09 08 07`, one per
call, with `$D401` following it:

```
call  shadows $B4F8-FA        $D401 $D408 $D40F
   4  ['75', '0C', '03']      ['75', '0D', '03']
   5  ['75', '0B', '03']      ['75', '0C', '03']
   6  ['75', '0A', '03']      ['75', '0B', '03']
   7  ['75', '09', '03']      ['75', '0A', '03']
```

So the drum fires, reaches the SID, and sweeps. **What it does not do is
register as a bend.** A step of 256 units at those frequencies is more than a
semitone, so siddump names each one a *note* — the original's trace is full of
`0D09 (G-3 AB)`, `1F04 (A#4 BA)`, `0DD0 (G#3 AC)` on consecutive frames — and
`bend` excludes ties by construction.

**Bump_Set_Spike's 11.79x is therefore the same artefact as Thrust's 43x**
(§ 7.hh): a stepped sweep on the player's side that the dimension cannot see,
against a conversion whose single 256-unit step lands close enough to be called
a bend. The converter is not inventing a drum. It is *under*-rendering one —
one step where the player takes six or more — and the metric shows the
under-render as an overshoot.

That also re-reads the sweep's re-measurement: "right for one file and wrong
for eight" was scored on a dimension blind to the original's drum on **every**
one of those files. The sweep stays, and the reason is now the 6502 and the
emulator rather than a number.

The residual is real but smaller than § 7.ii first claimed: the gate is
cross-voice runtime state (`LDA effect` is `AD`, absolute, written once in the
note-start path), so a per-instrument wavetable cannot reproduce *when* the
player drums — only that it does.

### 7.jj Effect bit `$80` is three blocks, and the biggest one is not music

Every earlier note in this project described bit `$80` in one sentence: it
"drives a hard-coded voice-3 noise hit plus global filter/volume off a global
state byte, which no per-instrument wavetable can express." That sentence was
carried across five handoffs without an address behind it. Reading all twelve
blocks — every corpus file whose `+7` resolves and which tests the bit, found
by `LDA effect / BPL` against the resolved address — shows it is true of nine
files and false of three, and that the three are the interesting ones.

**Nine files: the game's sound effect.** IK+ `$E41A`, Bangkok Knights `$8488`,
Mega Apocalypse `$4E43`, Nineteen `$946E`, Pandora `$F81E`, Ricochet `$946D`,
Star Paws `$B3F9`, Thundercats `$F17E`, Trans-Atlantic Balloon `$0C2E`. One
shape, copied file to file:

```
E41A  AD 58 E7  LDA effect
E41D  10 2D     BPL $E44C        ; bit $80 clear -> ordinary instrument
E41F  AD 1E E8  LDA $E81E        ; a GLOBAL cell -- not per voice, not per
E422  C9 01     CMP #$01         ;   instrument, and never indexed
E424  F0 10     BEQ $E436
E426  A0 1F     LDY #$1F
E428  8C 18 D4  STY $D418        ; volume down
E42B  C9 06     CMP #$06
E42D  90 1D     BCC $E44C
E42F  A9 00     LDA #$00
E431  8D 1E E8  STA $E81E        ; ran past the end -> disarm
E436  A9 48     LDA #$48
E438  8D F2 E5  STA $E5F2        ; IK+ patches its own code here; the other
E43B  A9 81     LDA #$81         ;   eight write $D40F / $D412 directly
E43D  8D F5 E5  STA $E5F5        ; $81 = noise + gate, on voice 3
E440  A9 60     LDA #$60
E442  8D 16 D4  STA $D416
E445  A9 2F     LDA #$2F
E447  8D 18 D4  STA $D418        ; volume back up
```

The constants differ a little — Trans-Atlantic uses `$38`/`$50`, Pandora and
Star Paws count to 8, Ricochet to 9 — and Ricochet's arms are `LDA #$00` with
the writes stripped out of the rip altogether. The structure does not: a
global counter compared against 1 and then against a ceiling, driving fixed
writes to `$D40F` (cutoff high), `$D412` (voice-3 control), `$D416` and
`$D418` (master volume).

Nothing in the SID file ever writes that counter. It is set by the *game* —
an explosion, a hit, a jingle — and a rip contains only the player. So this is
not a case of the target format being too poor to carry the source: **the
block is dead code in every one of these files, and firing it would be wrong
even if Goattracker could.** It seizes voice 3 and the master volume, neither
of which belongs to any instrument. This is the one result in section 7 where
the right encoding is provably no encoding.

#### v0.5.181: every sentence of that paragraph is wrong

A listener reported Trans-Atlantic's drums missing. They are — the conversion
sounds **0 frames of noise against the original's 1089** — and this block is
where they went.

**"Nothing in the SID file ever writes that counter."** `INC $0FAD,X` does,
every frame, at the bottom of the same routine. `$0FAF` is `$0FAD + 2`: it is
not a global cell but the **third voice's own frame counter**, which is why it
is compared against 1 and reset at 6. Checked across the seven files carrying
the block, **six write it with `INC base,X` from inside the player**; only Mega
Apocalypse does not, and that is a rip whose arms are stripped.

**"It is set by the game."** The gate above it is `LDA effect / BPL`, and
`effect` is the cell `_effect_byte_address` locates — the *playing
instrument's* `+7`. Nothing outside the music can reach it.

**"The block is dead code."** It fires 226 times in 60 seconds of
Trans-Atlantic, once per note of GT 2, on the beat.

What it plays is a fixed-pitch noise hit:

```
41 05CE   the note, pulse
81 38CE   noise, frequency HIGH replaced by $38 -- the note's low byte kept
81 15EB   noise, a second fixed pitch
41 05CE   the note again
```

The pitch is the point. `#$38` is an immediate, identical under C-3, E-2, G-2
and A-2, and it is `$48` in five of the other six files. The SID's noise is an
LFSR clocked by the frequency register, so a conversion that sounds noise at
the note's own `$05CE` writes the register and produces **no sound at all** —
which is exactly what v0.5.179 shipped and v0.5.180 had to add an audibility
guard against.

`detect._find_sfx_drum` lands the reading as `sfx_pitch`, `sfx_voice` and
`sfx_period`, and **v0.5.182 emits it** as `--sfx-drum`. A wavetable names
notes rather than registers, so the pitch becomes the nearest absolute note --
`$3800` is index 68 (`$375C`), inside a quarter-tone, which for noise is a
difference nobody can hear. Five entries, looping as the player does:

```
41 00   the instrument's own waveform, at the played note
02 80   hold for the rest of the period
81 C4   noise at the drum's pitch
81 C4
FF nn   back to the top
```

**The note comes first, and the first attempt did not.** (The reason given here
for it is wrong and was corrected three sections on: the counter is *not*
free-running, it is zeroed at note start, and the hit belongs on the note's
second frame rather than at the end of the period. The measurement below is
real; only its explanation was. See § 7.pppp.) The player's counter
is per voice and free-running, so a hit falls wherever it falls relative to a
note start; a wavetable always begins at the note. Opening on the noise put the
drum's pitch on the note's own first frame, where the played note never sounded
at all -- Trans-Atlantic's melody fell from 94.7% to **50.4%**, and the measure
caught it before it shipped. Opening on the note keeps both: melody 94.7%,
`wave` 61.1% -> 62.4%, and the median noise pitch moves from an inaudible
`$0685` to `$3744` against the original's `$302B`.

Two details are measured rather than derived and are marked as open. The burst
is **two** frames in the trace where the `CMP #$01` implies one; and the second
frame's `$15EB` comes from somewhere this reader has not found, so both frames
are written at the pitch that *is* read. Off by default, selected per song --
Bangkok Knights, Pandora, Thundercats and Trans-Atlantic, the last alongside
`--two-stage`, which needed `fidelity_better` to judge audibility on the
*reference* as well as the candidate: scored on frame count alone, the
two-stage's silent noise counted as "we have drums now" and blocked the audible
one from ever being reached.

**The lesson is about the shape of the error, not the details.** The paragraph
above was not a guess — it cited addresses and quoted the disassembly. What it
never did was ask whether the cell it called global was written anywhere in the
file, which is one `grep`. A reading can be detailed, sourced, internally
consistent and still wrong at the first load instruction, and the thing that
caught it was somebody listening to the tune and saying the drums were missing.

**Two files: a byte-code wave program.** ACE II `$E357`, Auf Wiedersehen Monty
`$E743` — the same player, and the shape the "half a census" note above
predicted when it observed that bit `$08` doubles as the high byte of a
pointer in this family:

```
E357  8E 5E E5  STX $E55E
E35A  B9 24 E6  LDA $E624,Y      ; Y = i * stride, the same index as the record
E35D  85 FC     STA $FC          ; a 16-bit pointer, per instrument
E35F  B9 25 E6  LDA $E625,Y
E362  85 FD     STA $FD
E364  BD C7 EB  LDA $EBC7,X      ; per-VOICE program counter
E367  A8        TAY
E368  B1 FC     LDA ($FC),Y
E36A  10 1E     BPL $E38A        ; < $80 -> the three-byte form
E36C  C9 85     CMP #$85
E36E  D0 03     BNE $E373
E370  4C 5E E4  JMP $E45E        ; $85 -> hold; the counter is NOT advanced
E373  AE 4F E5  LDX $E54F
E376  9D 04 D4  STA $D404,X      ; waveform, straight to the chip
E379  C8        INY
E37A  B1 FC     LDA ($FC),Y
E37C  9D 01 D4  STA $D401,X      ; frequency high, absolute
...
E38A  9D 59 E5  STA $E559,X      ; < $80: waveform into the voice's own cell
E38D  C8        INY
E38E  38        SEC
E38F  BD 75 E5  LDA $E575,X      ; then a 16-bit SBC of the next two bytes
E392  F1 FC     SBC ($FC),Y      ;   off the voice's frequency
E394  9D 75 E5  STA $E575,X
E398  BD A2 EC  LDA $ECA2,X
E39B  F1 FC     SBC ($FC),Y
E39D  9D A2 EC  STA $ECA2,X
```

One entry per frame, two bytes or three. ACE II instrument 1's program reads
`81 40 | 41 80 03 | 40 00 02 | 40 55 05 ...` — noise+gate at frequency high
`$40`, then pulse+gate falling by `$0380`, then gate off and falling further.
**This one is a wavetable**, and Goattracker's carries the waveform column
exactly. The pitch column is where it stops being a translation: the player
subtracts a raw 16-bit frequency, Goattracker's right side names a *note*, and
the two are only the same thing at one pitch. Encodable, unencoded, and
unmeasured — the decision belongs to a controlled A/B on two files, not to a
reading.

**One file: a stepped frequency table.** Delta `$C1EC` decrements a per-voice
counter (`$C351,X`) and, on the frame it goes negative, reloads it from
`$C43E,Y` while adding `$C43F,Y` to the voice's frequency-high cell
(`$C34B,X`) — a table-walked sweep in the family of § 7.ee's vibrato, two
bytes per entry, duration and delta.

`detect._find_effect_bit80` lands all three as `Detection.effect_bit80`
("sfx" / "program" / "pitch") plus `effect_program`, the pointer array's
offset. `goatwriter` consumes none of it, for the reason § 7 has now recorded
three times: resolve what the byte means from the 6502, then decide
separately, by measurement, whether the target format should carry it. The
difference here is that for nine of the twelve files the measurement is not
needed — the block is not part of the tune.

### 7.ccc A third pulse engine, and a column that could not see it

Commando's lead sat on a single duty cycle where the original swept six
256-wide buckets. The instrument map named it; the annotated siddump of §7.bbb
found the mechanism in one read, because labelling each row with the
instrument sounding on it turns "what does GT 1 do" into a grep:

```
775 v1 1D46  A-4 B9  41 295F AC0 ONSET
776 v1 ....  ... ..  .. .... BA0
777 v1 ....  ... ..  .. .... C80
778 v1 ....  ... ..  40 0000 D60
779 v1 ....  ... ..  .. .... E40
780 v1 ....  ... ..  .. .... D60
```

A triangle, `$E0` a frame, turning at `$E40`. Not the sweep of §7.n (whose
bounds live in a per-record array, and which Commando does not have) and not
the accumulate engine (which moves only `$D402`, so the high nibble cannot
travel). A third engine, in the `else` of the accumulate branch:

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

**One rate byte, two fields.** `& $E0` is the step and `& $1F` the frames
between steps, so a rate of `$44` is 64 every five frames and a rate of `$1F`
is nothing, thirty-two times. Reading the byte as a plain rate — which is what
both other engines do with the same `+6` — would have made a slow sweep a
frantic one and a static record a swept one.

**24 corpus files, and the bounds read rather than assumed.** They are `$08`
and `$0E` in all 24. That is precisely why `_find_pulse_tri` takes them from
the two `CMP` operands: a constant that holds everywhere is indistinguishable
from one nobody checked. The instrument-table operand is checked against the
table detection already found, as `_find_pulse_lo` does. 19 of the 24 sit
behind an effect-bit-`$08` test with the accumulate engine on the other side;
**five have no test at all** and sweep every record, so the gate is honoured
only where it was found. 23 files change bytes; the 24th, Hunter_Patrol, has
bit `$08` set on every record with a nonzero step, so the gate correctly sends
all of them to the other engine.

**Two things Goattracker cannot say, both stated in the code.** The width
lives in the instrument record, so it is shared by every voice sounding that
instrument and **free-runs across notes** — nothing reseeds it. Goattracker
reloads a pulse pointer whenever its instrument is triggered
(`gplay.c:375-379`), so our sweep restarts every note. And a pulse speed is a
*signed byte* (`readme.txt:887-889`), so at `-S1` the width cannot move more
than 127 a call where the player moves 224. The band still comes out right
because the tick counts are recomputed from the speed actually emitted; only
the rate is slow, by 1.76x.

#### The column that could not see it

With the sweep shipped, the map's pulse table still read `$A00` against the
original's six buckets — **unchanged**. It was sampling one frame per onset,
and a sweep that restarts with the note is at the same place on every onset
however far it travels afterwards. The old column could not have shown this
fix, or any pulse fix, at all.

So the column was replaced rather than believed, per the rule this repo has
had to learn twice (§7.f, §7.dd): the band each note covers, on both sides.
The first version of *that* compared the **union of the bands across notes**
and scored GT 1 `ok` — flattering, and wrong for the same reason: a
free-running sweep visits every phase, so its union is the whole band however
little it moves during any one note. The verdict is now the **median travel
within one note**:

| GT | orig at onset | ours at onset | orig band | our band | travel/note | verdict |
|---|---|---|---|---|---|---|
| 1 | `$800`–`$D00` | `$A00` | `$820-$E40` | `$845-$DBA` | 1568/762 | 0.49x |
| 3 | `$100` | `$100` | `$100-$1FE` | `$152-$244` | 234/132 | 0.56x |
| 6 | `$800` | `$800` | `$800-$8FE` | `$8DA-$8E6` | 20/12 | 0.60x |

0.49x is the signed byte, and it is the ceiling at `-S1`. Rows 3 and 6 are the
*accumulate* engine — a pre-existing deficit the onset-only column had hidden
since it shipped, and one this fix did not touch. Note lengths are identical
on both sides (median gaps 12, 18, 12), so it is not an artefact of the window.

The pattern worth keeping: **the reading that made the sweep findable and the
reading that made it measurable were two different changes to the same tool**,
and the second only happened because the first produced a table that stayed
flat when the converter demonstrably changed.

#### And the same trap again, one report over

`FIDELITY.md` did move — its `pul` column went from `3/236` to `338/236` on
5_Title_Tunes, and similar elsewhere. Read as a count that is a large
regression. It is not: `pul` counts *frames on which the duty cycle moved*, and
a signed-byte speed emits one player step of 224 as 127 twice. Twice the
frames, the same sweep. This is precisely the pair `cut` was added beside
`filt` for in v0.5.78, and `pul` had gone without its companion ever since.

So `pspan` — the width of the band, ours over the original's. Its first
version then failed its own first check, in a way worth recording because it
looked exactly like a converter defect: Commando read **3.96x the original's
band** for a sweep measured at 0.49x an hour earlier. The cause was neither
converter nor player. Goattracker writes `$D402/$D403` on every frame of every
voice from its first call (`gplay.c:945`); the player writes them at its first
note. So our timeline opens on a run of `$000` and the original's opens on a
real width, and the span picked up a spurious `$000`-to-first-width jump on all
three voices of every file. Excluding zero — 0% duty is silence, not a timbre,
and the rule is symmetric — Commando reads 0.96x.

Two things that made it findable in minutes rather than being published: the
number was checked against a per-instrument measurement of the same thing
taken independently, and when they disagreed by 4x the *instrument* was
suspected before the converter. Corpus median is now 0.56x, six files are
frozen at 0.00x, and two overshoot.

A footnote that cost twenty minutes: `Commando.sid` in the repo root and
`Commando.sid` in the corpus are **different rips** (4222 and 4165 bytes). The
fixture is the one `instrmap.py` and the listening sessions use; `FIDELITY.md`
and `SURVEY.md` are the corpus. A number from one is not a number about the
other, and for a while two measurements that should have agreed did not
because they were of different files.

### 7.ddd The drum's noise duration was right, and the report was seven frames late

v0.5.174's drum fix took Commando's noise coverage from 49% to 92% of the
original's frames and cost 4.6pp of `wave`. That was written up here as
"the right amount of noise at partly the wrong times", with 962 frames of ours
landing where the original has none, and the next task was to fix the duration.

**There was nothing to fix.** Sweeping a frame offset over the noise agreement:

| shift | both | ours-only | orig-only |
|---:|---:|---:|---:|
| +0 | 463 | 962 | 1079 |
| **+7** | **1425** | **0** | **115** |

At +7 every one of our 1425 noise frames coincides with an original noise
frame. Our first attacks are at frame 8; the original's at frame 1. gt2reloc's
player spends a few frames initialising before its first note, and comparing
frame *k* to frame *k* charged that constant to the converter on every file.

Per-instrument noise durations, measured before the shift was known, said the
same thing and would have prevented the wrong write-up on their own:

| GT | own wave | original | ours |
|---|---|---|---|
| 2 | `$41` | 2 frames ×166, 4 ×23 | 2 ×189 |
| 4 | `$81` | 12 ×64, 6 ×5 | 11 ×64, 5 ×5 |
| 5, 6, 8, 13 | | 2 | 2 |

Exact but for two residuals summing to the 115 above, and **neither is a
duration**. GT 2's 4-frame notes are two 2-frame bursts — the player re-fires
the drum on a pattern row that does not retrigger the gate, so siddump sees one
note where the player sees two. GT 4's "one frame short" is the *next* note's
frame counted in this one: it holds `$09` with ADSR `$099F`, which is GT 3's
envelope, not GT 4's.

#### Estimated, not fitted

The correction has to be one number from a defined signal. The obvious
alternative — search the shift that maximises agreement — is a free parameter
that can only raise the score, and would make the column evidence of nothing.
So `startup_lag` is the difference between the two sides' first attack frames,
and it was **validated against** the search it replaces on 36 corpus files:

* it lands on the fitted optimum for **20 of 36**;
* mean `wave` is **77.0%** at the estimate against **77.1%** at the fit.

The search buys a tenth of a point and costs the measure its meaning.

It is also bounded. Chimera's raw lag is **438 frames** — 8.8 s, an opening one
side does not have. Absorbing that into an alignment would hide a real defect
and discard a third of the window, so a lag past `MAX_STARTUP_LAG` is clamped
and the raw value reported. The report names the file.

Corpus effect, and it is a **measurement** change with no converter change
behind it: mean `wave` 67.0 → 70.2%, mean `adsr` 71.9 → 76.4%, Commando's
`wave` +32pp, Phantoms +26pp, six files −1pp. Noise, `pul`, `pspan`, `filt` and
`cut` are one-sided counts or travels over each side's own window and are
shift-invariant, so they are computed before the shift and did not move.

**What this cost.** A converter fix was written up as a regression, and the
next task was set to repair something that already worked. The check that would
have caught it is cheap and general: **before attributing a per-frame
disagreement to the converter, sweep the offset.** A single number that
collapses the disagreement is not a defect in the thing being measured.

The one real finding left over is not a duration either — see §7.eee.

### 7.eee The silent frame on every note, and why removing it is wrong

Every record this tool writes carries `$09` in byte +8, the waveform Goattracker
puts on a note's first frame: testbit plus gate. The testbit holds the phase
accumulator and the noise LFSR at zero, so the frame is **silent**, and there is
one per note. The originals spend 4273 such frames across 12 of 83 files; we
spend **9179 across 79**. Most of ours are invented, and the invention is a
hardcoded constant rather than anything read out of a player.

So it looks like a clear defect, and it is not. Two replacements were measured.

**`$FF` — gate on, waveform untouched** (`gplay.c:355-363` reads a firstwave of
`$FE` or above as a gate value). On Commando: testbit frames 716 → 0, and `wave`
**91.5% → 99.5%**. It also deleted 79 notes — the collapsed attack sequence on
voice 1 went 139 → 125 against the original's 140, and on voice 3 216 → 153
against 217. **A per-frame agreement rewards losing notes**, because fewer
attacks mean fewer transitions to disagree about, and 99.5% was that and not
fidelity. Any register-agreement column can be gamed this way; this is the first
time in the project something actually did.

**The record's own waveform with the gate on** — what the player's first frame
really holds (`81 80 80 80 80` for Commando's noise record). This keeps the notes
(139, 105, 216 against 140, 105, 217 — voice 2 gains one) and removes all 716
invented frames. Corpus-wide, over the 82 files both settings convert:

| | off | on |
|---|---:|---:|
| mean `melody` | 79.6% | **63.9%** |
| mean `wave` | 69.8% | 73.9% |
| testbit frames | 9179 | 55 |

Melody falls **15.7 points** for 4.1 points of `wave`. Zoids loses 89, Thrust 87.
The frame is load-bearing: it is what makes a re-struck note retrigger, the same
role hard restart plays for the envelope. Three files gain 16–17
(`Last_V8` in both rips, `Trans-Atlantic_Balloon_Challenge`), so the effect is
not uniform — which is why this ships as `--no-test-restart`, off, and named in
`presets.EXCLUDED_FROM_ALWAYS` with the numbers, rather than as a comment
somebody re-derives.

#### Searching it per song (v0.5.177)

Three files wanting an option 79 do not is what per-song presets are for, except
that `presets.py` could not express it. Its scoring is structural — playable
subtunes, rows played, bytes — and `no_test_restart` changes **none** of them,
not even the byte count, so adding it to the searched set would have tied every
time and silently chosen the default. `presets.py --fidelity` searches it by
playing both settings through `gt2reloc` and siddump, and `fidelity._preset_opts`
plus `cli.py` now let a song entry override `always` — until v0.5.177 both read
`always` alone, so a searched setting would have been written and then ignored,
the exact shape in which `--slides` and `--filter` shipped dead.

It takes the option for exactly the three files the corpus A/B predicted. And
what it accepted is a **trade**, recorded rather than smoothed:

| Last_V8 | off | on | original |
|---|---:|---:|---:|
| attacks | 41 | **79** | 77 |
| melody | 46% | **62%** | |
| pitch | **91%** | 56% | |
| distinct pitches | 10 (10 shared) | 14 (9 shared, **5 invented**) | 11 |

`pitch` is a set overlap that ignores order and count, so a conversion playing a
strict subset of correct pitches scores near-maximally on it — it **rewards
playing less**, which is why it does not veto. Half the notes missing is the
worse fault. The five invented pitches are still real, and only a listen settles
that.

**Last_V8 was then auditioned, and the audition itself needed a second go.**
Opened in GoatTracker it played at half speed — the editor calls the player once
a frame and this tune advances a row every two — and at half speed the two
settings were hard to tell apart, so the listening verdict came back for the
*subset*. Re-tested at true speed as packed `-S2` `.sid` files, the 187-note
version is plainly the right one. The counts say why: voice 2 carries 188 notes
in the original, **71** with the option off and **187** with it on, and even the
missing bass notes the listener reported are worse without it (3 of the
original's 10 upper-register notes against 9).

The editor could have played it correctly all along — **SHIFT+F6** sets the
call-rate multiplier, and `play.ps1` reads the song's multiplier and prints how
many presses. Launching `goattrk2.exe` directly skipped that. The rule is in
CLAUDE.md now: a listening test at the wrong rate is not weak evidence, it is
evidence for the wrong conclusion.

The guard is `melody` (what is played, in order), `sequence` (uncollapsed, so a
lost re-strike shows) and our own attack count. `FIDELITY_MARGIN` keeps difflib
noise out. And because the fast structural search cannot see these options at
all, a plain regeneration **carries forward** whatever `--fidelity` recorded and
prints the count: without that, the next routine commit would have quietly
returned all three files to the default with nothing reporting it.

The general lesson is the one §7.ddd had just finished teaching from the other
side. There, a per-frame column was *too harsh* because of an offset nobody had
subtracted. Here it was *too kind* because a change quietly removed the events
it scores. **A register-agreement percentage is only interpretable next to the
note counts of both sides** — and the note counts are the thing a listener
notices first.

### 7.fff The byte-code wave program — 29 files, and a census that said one

A listener said Trans-Atlantic's snare was missing. It is GT 3, and the reason
is a **per-instrument byte-code interpreter** that nothing in this project reads.
Trans-Atlantic `$0B4E`, and the operands differ file to file while the shape does
not:

```
0B4E  B9 6B 11  LDA ptrs,Y      ; Y = i * stride -- 16-bit per instrument
0B51  85 F0     STA $F0
0B58  BD 4D 10  LDA pc,X        ; per-VOICE program counter
0B5C  B1 F0     LDA ($F0),Y     ; fetch an opcode
0B5E  10 1E     BPL threebyte   ; < $80
0B60  C9 85     CMP #$85
0B64  4C 60 0C  JMP done        ; $85 -- HOLD, the counter does not move
```

Three opcodes and nothing else:

| opcode | bytes | effect |
|---|---|---|
| `$85` | 1 | hold here for the rest of the note — the program's end |
| ≥ `$80` | 2 | waveform → `$D404`, frequency **high** → `$D401`, both written directly |
| < `$80` | 3 | waveform, then a 16-bit value **subtracted** from the voice's frequency accumulator |

The second form is why the snare exists at all: both bytes go straight to the
chip, so its pitch is the player's own and has nothing to do with the note.
GT 3's program is `81 30 | 10 00 02 | 40 C0 03 | 80 30 | 80 15 | 80 20` —
*noise at `$30xx`*, two slides down under a released triangle and pulse, then
three more noise pitches. Its first two bytes are literally the missing snare,
and they also answer the `$15EB` that §7.eee left open: `80 15` is right there.

The third form is a subtraction, so a large operand slides **up**: three of
GT 13's steps are `$FC00` taken away, which is `$0400` added. A decoder that
read the operand as unsigned "down" would invert them.

#### The census was wrong by a factor of 29

The first signature for this was written from Trans-Atlantic's exact operands —
44 bytes of them — and found **one** file. Written instead from the fetch-and-
hold shape (`LDA (ptr),Y / BPL / CMP #$85 / BNE`, eight bytes), it finds
**29 of 95**, including ACE II and Auf Wiedersehen Monty, which were already
classified as `effect_bit80 == "program"` and never connected to the other 27.
That makes this the most widespread instrument mechanism the project has found
unemitted, and the lesson is old: **fingerprint the shape, not one file's
register allocation.** The exact signature was not wrong, it was 29 times too
specific, and a conclusion — "one file, not worth the work" — was drawn from it
before the looser check took two minutes.

#### The gating bit, and an under-anchored scan that looked like a wrong match

A first attempt swept 40 bytes back from the *fetch* for any `AND #$xx / BEQ`,
returned `$01` for most files, and was dismissed — `$01` is the *drum* bit in
Warhawk's dialect, so it looked like the scan had found an unrelated test. It had
not. It was **under-anchored**, and `$01` really is the gate. The test sits
immediately above the pointer load, and that is the anchor it needs:

```
0B44  AD FB 0E  LDA effect      ; Trans-Atlantic: bit $08
0B47  29 08     AND #$08
0B49  F0 51     BEQ skip
0B4B  8E A2 0D  STX save
0B4E  B9 6B 11  LDA ptrs,Y      ; <- the anchor

E3D2  AD 7B E5  LDA effect      ; ACE II: bit $80, tested by sign
E3D5  10 51     BPL skip
```

| gate | how tested | files |
|---|---|---:|
| `$01` | `AND #$01 / BEQ` | 22 |
| `$08` | `AND #$08 / BEQ` | 3 |
| `$20` | `AND #$20 / BEQ` | 1 |
| `$80` | `BPL` — by sign | 2 |
| unread | shape not recognised | 1 |

**So in 22 of these players effect bit `$01` selects a wave program, where in
Warhawk's dialect the same bit means a drum.** That is the fourth independent
reading of `+7` this section has had to record, and the check that matters is
whether the two ever coincide: they do not, in any corpus file, so nothing
`--effects` reads is fabricating a drum over a program. In 18 of the 29 the cell
the branch tests is *independently* known to be the effect byte, which is what
makes it the instrument's own flag; the other 11 are files whose effect cell
detection cannot locate at all, so the gate is read but not corroborated.

The dismissal is the part worth keeping. A plausible-looking number from a
loose probe was written off as a false match because it collided with something
known, when the collision was the finding. **Tighten the anchor before
discarding the reading** — the loose scan and the tight one differ by one
instruction's worth of context and by 22 files.

#### Emitting it, and the snare that appears

`--wave-program` (v0.5.187). Each opcode becomes wavetable entries:

| opcode | entries |
|---|---|
| `≥ $80` | one: the waveform, with the nearest absolute note on the right |
| `< $80`, zero operand | one: a waveform change and no pitch movement |
| `< $80`, nonzero | two: the waveform, then a portamento whose speed-table entry *is* the operand |
| `$85` | none — the block stops, and Goattracker holds the last waveform as the player does |

Two details the encoding turns on. The operand is **subtracted**, so one above
`$8000` is a rise and takes `CMD_PORTAUP` with the two's complement — which also
keeps the speed-table high byte below `$80`, where it would otherwise read as
note-relative. And a waveform below `$10` cannot be written literally, because
`$01`–`$0F` are *delays*: `$E0`–`$EF` sets the waveform to `$00`–`$0F` instead
(`gplay.c:527`), and GT 11's program is three of those in a row.

Trans-Atlantic's GT 3, the snare, emits `81/C2 10/80 F2/01 40/80 F2/02 80/C2 …`
and **all 43 of its notes now sound noise in their opening frames**:

```
orig  11@15EB  81@30EB  10@13EB  40@102B  80@302B  80@152B
ours  81@313C  10@313C  10@2F3C  40@2F3C  40@2B7C  80@313C
```

Noise at `$31xx` against `$30xx`. Ours starts the program a frame earlier — the
player spends the note's first frame on the record's own `$11` — and the slides
land a frame late, because each costs two wavetable entries where the player
spends one. The waveform sequence and the pitches are otherwise the same.

**Multiplier 1 only.** The player advances one opcode per frame and a wavetable
advances one entry per *call*, so at `-S2` the program would run twice as fast;
slowing it needs a delay per opcode, roughly doubling a budget that already
reaches 131 entries on Kings of the Beach. 15 of the 29 files are `-S1`.

#### The search cannot select it, and the criterion is why

`presets.py --fidelity` chose it for **no file**, including the one whose snare
it restores. Neither branch of `fidelity_better` fires: `melody` falls (94.7% →
85.5%, the absolute pitches replacing the played notes), and the noise branch
compares the **median** noise pitch — which on Trans-Atlantic is dominated by
`--two-stage`'s ~900 inaudible frames and reads `$08B4` however audible the
snare's ~300 frames at `$31xx` are.

That is a real limitation of the criterion, not of the encoding, and it is left
stated rather than tuned: a median is the wrong statistic for "did a new sound
appear" when another mechanism contributes most of the frames. Bending the
threshold until this one file passed would be fitting, which §7.eee already
records the cost of. So the option ships off, selected nowhere, and the next
honest step is a listening test — the same route `FIDELITY_VETOED` exists for,
in the other direction.

### 7.ggg The drum's noise run is 1, 2 or the whole note — and we always write 2

SIDM2's `HUBBARD.md` places the drum's noise on the **first** frame, where
v0.5.172 concluded frames 1–2 from Commando's trace. Both are right, about
different players, and the constant `NOISE_TICK_FRAMES = 2` is right for neither
in general.

Hubbard's own commented disassembly (C=Hacking #5, Monty) is unambiguous about
the routine:

```
  lda savelnthcc,x / and #$1f / sbc #$01 / cmp lengthleft,x
  bcc firstime                      ; the drum's first vbl
  lda savefreqhi,x / dec savefreqhi,x / sta $d401,y     ; later: sweep down
  lda voicectrl,x / and #$fe / bne dumpctrl             ; ...and its own waveform
firstime:
  lda #$80                          ; NOISE -- first vbl only
```

and its comment states the other half: *"ctrlreg 0 is always noise; ctrlreg x is
noise for 1st vbl and x from then on."*

Commando's routine is that same shape byte for byte. What reaches the chip is
not the same:

```
Monty    GT 15   40 [41] 80  40  40         noise at offset 1
Commando GT  8   14 [15] 80  80  14         noise at offsets 1 and 2
```

Both put the record's waveform on the note's own first frame — the note-init
path writes `$D404` after the drum routine on that frame — so the routine's
"first vbl" is the note's *second*. The disagreement is only the run's length.

Measured over every drum-flagged note in the corpus, split by the record's
waveform:

| record waveform | noise run | notes |
|---|---:|---:|
| noise or none | 7 (the whole note) | **623** |
| noise or none | 4–6 | 72 |
| **pitched** | **1** | **1548** |
| **pitched** | **2** | **934** |
| pitched | 3 | 88 |
| pitched | 7 | 90 |

**The `ctrlreg 0` half is confirmed and already correct.** A record whose
waveform carries no waveform bits gets noise throughout, and `_drum_entries`
emits exactly that (`$81` → `81 81 81 80`). That half is predictable from the
record alone, which is why Hubbard could state it as a rule.

**The 1-versus-2 split is not.** Both routines are identical, so the difference
lies in the surrounding order — where the init path writes `$D404`, or when
`lengthleft` decrements — and nothing in the eight record bytes separates the
two families. We write 2 for every pitched record: right for 934 notes, one
frame too long for 1548.

#### The mechanism: the run is the speed gate less one

Found by elimination, not by fitting. Three structural comparisons across the
twelve run-1 files and the nine run-2 files came back identical: the drum block
itself, where `voicectrl` is written, and where `lengthleft` is decremented. So
the difference is not in the code, which leaves the data — and the drum's own
test is the clue:

```
lda savelnthcc,x / and #$1f / sbc #$01 / cmp lengthleft,x / bcc firstime
```

`lengthleft` decrements once per duration **unit**, not per frame. A unit lasts
`frames` frames (the speed gate `find_song_speeds` reads), so the test stays true
for that long — and the note's own first frame is spent by the init path writing
the record's waveform to `$D404` *after* the drum routine has run. What reaches
the chip is `frames - 1` frames of noise:

| speed gate | noise run | files |
|---:|---:|---:|
| 2 | 1 | 12 |
| 3 | 2 | 10 |

Exact on 22 of 25. The three exceptions are the noise-throughout class and one
file where no gate is found. Commando's gate is 3, which is why the hardcoded 2
was right for the file it was measured on and one frame too long for twelve
others — and why the fixture and the drum a listener validated are unaffected by
knowing this.

#### Wired in v0.5.196, after two commits said so and were wrong

**v0.5.192 and v0.5.193 both claimed edits that never applied.** Each used a
`str.replace` whose search text did not match, and `str.replace` returns the
string unchanged rather than raising. The tests passed and the fixture stayed
byte-exact — Commando's derived tick equals the old constant, so nothing this
project pins could have caught it. v0.5.193's message states
"`_noise_tick_frames` is now wired" and reports 19/74 → 43/74; the measurement
was real (the experiment monkey-patched `_drum_entries`) and the shipped code
never used it.

Re-applied with an `assert` on the search text, the figure is confirmed at
**43/74**. The rule that follows is narrow and absolute: **a scripted edit must
assert its match**, and a commit that claims a code change must show that change
in the diff, not in a passing test suite.

#### The reading, and what it took to trust it

`_noise_tick_frames` lands it. Wiring it into `_drum_entries` measured **flat**:
26 of 29 drum instruments match the original's run length either way. It
demonstrably fixes some — Last_V8 and Master of Magic's GT 8 both go 2 → 1,
confirmed frame by frame — and appeared to break an equal number.

The first explanation offered here was that shortening the tick frees a wavetable
entry and the pitch sweep moves into it (`41 81 40 F2 FF` where a 2-frame tick
gives `41 81 81 40 FF`), making it two changes under one flag. **That was wrong.**
Running both tick settings at budget 5 and again at budget 8 — enough room for the
sweep in either case — gave *identical* match counts. The sweep is exonerated.

What the derived tick actually does is move the noise a frame earlier relative to
siddump's attack:

| | scanned from `a+1` | from `a+0` |
|---|---|---|
| tick 2 | 46/55 | 19/55 |
| tick derived | 43/**50** | 41/55 |

Five instruments lose their `a+1` noise and gain it at `a+0`, so the two settings
are not measured on the same population and 46/55 against 43/50 is not a
comparison at all. **The metric cannot settle this**, for the fourth time today
from the same cause: a run's position relative to a gate-edge attack is unstable
when the run's length changes, and every boundary error in this session — GT 4's
"one frame short", the drum's own frames 1–2, the `$09` that belonged to the next
note — has been this.

#### The measure, and the answer it gave

`fidelity.noise_runs` finds **maximal stretches of `$D404 & $80`** and records how
long each is. No attack, no note boundary — a run's length does not depend on
where the run begins, which is exactly the property the previous two experiments
lacked. Two rules keep it honest: a run touching either edge of the window is
dropped, because its length is a fact about the window; and attribution is the
ADSR at the run's *midpoint*, so it lands inside the note however the run sits
within it.

Measured that way, on the same 74 drum instruments both times:

| tick length | instruments whose noise runs as long as the original's |
|---|---:|
| 2 (the constant) | **19 / 74 — 26%** |
| gate − 1 (derived) | **43 / 74 — 58%** |

So the derived length is right and both earlier "flat" results were the metric.
It is wired (v0.5.193), and `nrun` is now a column of `FIDELITY.md` so the next
change to the drum is measurable rather than arguable.

The column's own shape is worth reading before quoting it: 35 files report it, and
they split **25 at 0%, 5 partial, 5 at 100%** — so its per-file mean of 23% is not
the pooled 58% above and neither number is wrong. A file with one drum instrument
scores 0 or 100 and nothing between, which is why the pooled figure is the one to
compare settings with and the column is the one to spot a file with.

**The general lesson, and this session paid for it four times.** Every reading of
the drum before this asked what the waveform was at `a + k` for a gate-edge
attack. That is fine while `k` is fixed and useless the moment a change moves it —
and the changes worth making are exactly the ones that move it. GT 4's "one frame
short" was the next note's `$09`; the drum's frames 1–2 against the routine's
"first vbl" was the init path writing `$D404` after it; the tick comparison came
back flat twice, once blamed on a sweep that turned out to be innocent. **When a
change alters an event's duration, measure the duration, not the offset.**

**Two aggregate measures disagreed about this and the frames settled it.** A
file-level modal run said 14 → 16 files improved; a per-instrument one said
26 → 26. The file-level figure was collapsing several instruments into one mode.
That is the third time in this session an aggregate contradicted a direct frame
reading and the frames were right — §7.eee's `wave` 99.5%, §7.ddd's per-note
travel, and this. **When an aggregate and a trace disagree, print the frames.**

### 7.hhh `-R0` is the wrong half of a compensation already in place

A listener said some of Commando's slides were not right, and the columns agreed:
`slides` 293 of 527, `bend` 1.09x. `-Rxx` is gt2reloc's **realtime-effect**
skipping, default-on and the sibling of the `-Oxx` pulse skipping §7 had just
acted on — and portamento is a realtime effect. On Commando it looks decisive:

| Commando, 60 s | slides | bend |
|---|---:|---:|
| default | 293 / 527 | 1.09x |
| `-O0` | 245 / 527 | 0.44x |
| **`-O0 -R0`** | **511 / 527** | **0.89x** |

Corpus-wide it is the wrong move. Over the 75 files with any slide activity in a
60-second window:

| | slides | median ratio | median &#124;bend−1&#124; |
|---|---:|---:|---:|
| `-O0` | 147875 / 160711 | **1.04** | 0.59 |
| `-O0 -R0` | 180196 / 160711 | 1.23 | 0.56 |

Adding `-R0` puts the slide count **further** from the original on 47 files and
closer on 27; `bend` is a wash (39 against 35). `melody`, `wave` and `pspan` do
not move at all.

**The reason is that the compensation already exists.** `patterns._scaled_step`
has carried a `row_calls` correction since v0.5.147, added precisely because the
packed player drops a call per row. `-R0` stops it dropping the call. Doing both
over-corrects, and 92% → 112% is what that looks like. So the standing question
in CLAUDE.md — "`--R0` versus step-scaling for the slide deficit" — has an answer:
step-scaling, which is what ships, and whose median slide ratio is 1.04.

Commando is an outlier at 47%, not an instance of the corpus deficit. Its slides
want a per-file explanation.

#### A 10-second window barely measures slides at all

Both corpus A/Bs behind this were first run at `-t 10`, and both said `-O0` and
the default were **identical on every file** — zero movement. That was the window,
not a result: at 10 seconds Commando has `0/0` slides on both sides, and the
committed `FIDELITY.md` has **17 of 82 rows at `0/0`** with `bend` uncomputed on
19. The report's slide columns are close to vacuous for a fifth of the corpus, and
any conclusion drawn from them at that window inherits it.

Re-run at 60 seconds the same comparison had 75 files with slide activity and a
clear verdict. **Check what a window contains before comparing settings in it** —
this is the second time in one session that an aggregate said "no change" when the
measurement was empty rather than the change inert (§7.eee's `--baseline` note is
the first).

### 7.iii Every "slide" in Commando is a vibrato

A listener said some of Commando's slides were wrong. `--vibrato` off takes its
slide count from 245 to **zero**, and `--slides` and `--effects` change it by
nothing at all — all four combinations are bit-identical. So `slides` and `bend`
were never measuring portamento on this file; siddump classifies pitch movement
without a retrigger as a slide, and vibrato is exactly that.

Which means the `-R0` corpus A/B of §7.hhh was ranking vibrato rates while
appearing to rank slides. Goattracker's vibrato is a **realtime effect**, so
gt2reloc's default-on `-R` skipping drops it on the note-fetch tick — and the
`row_calls` step-scaling that compensates the pattern speed table does not touch
it, which is why toggling that compensation changes Commando by nothing.

`fidelity.pitch_motion` separates the two with no threshold to choose, because a
vibrato *reverses* and a portamento does not: it counts direction changes in the
frame-to-frame pitch delta, and reports `1 - net/gross` as the share of movement
that is back-and-forth. Frames within one of an attack are skipped, an onset being
a large jump in whatever direction the tune goes.

On that measure the `-R0` question answers the other way:

| | median reversal ratio | median &#124;ratio−1&#124; | closer / further |
|---|---:|---:|---|
| `-O0` | 0.46x | 0.62 | — |
| `-O0 -R0` | 0.54x | 0.52 | **62 / 13** |

**And the absolute figure is the finding.** Even with the skipping off we
oscillate at **half** the original's rate, corpus median 0.48x over 82 files. The
packer accounts for a small part of a factor of two; the rest is ours. v0.5.129
corrected the vibrato *period* from a `cmp / 2` reading to `cmp + 2` play calls
and left the amplitude alone because the two errors had cancelled — a remaining
2x in the rate is exactly the shape of a period still half right.

So `-R0` is not shipped. It is a real improvement on the rate and a real
regression on the frame count (92% → 112%), and settling that trade before
finding the missing factor of two would be optimising around the bigger defect.
`vib` is a column now, so the next attempt has a measure that names what it is
changing.

**The report moved to a 60-second window for this** (v0.5.195). At 10 s, 17 of 82
rows had `0/0` slides and 19 no `bend` at all; two corpus A/Bs in one session read
"identical on every file" from a window that contained nothing to compare. Figures
either side of the change are not comparable and the header records the window.

### 7.jjj The arpeggio was a call late

A listener said Commando's slides were wrong; §7.iii established that every
"slide" on that file is pitch *oscillation*, and that its dominant half-period is
one frame — an arpeggio, not a vibrato. So the question became whether our
arpeggio produces that alternation. It does, correctly, and late:

```
orig GT 2:  1D46 1D46 3A8C 1D46 3A8C 1D46 3A8C
ours GT 2:  1D46 1D46 1D46 1D46 1D46 3A8D 1D46
                             ^ starts here
```

Right rate (every frame), right interval (an octave — `1D46`→`3A8C` is exactly
×2, ours `3A8D` one LSB off from rounding), wrong phase. The cause is the shape:
the arpeggio note sat on entry **3** with the jump returning to entry 2, so the
first swing was the note's fourth call where the player's is its third. Moving it
to entry 2 with the jump returning to entry 1 gives `base, base, arp, base,
arp …` — the player's own sequence.

Measured across the files with an arpeggio routine, the onset was late on **15 of
24** before and **8 of 19** after, and the cluster moved exactly as designed:
`orig 2 → ours 3` (6 files) became `orig 2 → ours 2` (5 files, matched), and
`orig 1 → ours 3` became `orig 1 → ours 2`. The population shrank from 24 to 19,
which is the same comparability caveat §7.ggg records — the direction is
unambiguous but the two totals are not the same set.

**A ticked record cannot be fixed this way** and is not: the noise tick owns
frames 1–2, so its arpeggio cannot start before frame 3, while the player runs
both at once — writing noise to `$D404` *and* the arpeggio's frequency on the
same frame. A wavetable entry carries one waveform and one note, so expressing
both means putting arpeggio notes on the tick's own entries. Left alone.

#### It leaked into the VB6 path, exactly as `arp_fixed_up` did

The first version changed the shape unconditionally and broke **26**
byte-exactness tests — the same count, from the same cause, as the `arp_fixed_up`
leak earlier in this session. `effects` off means "reproduce the VB6 original",
and the fixture encodes its entry-3 shape.

Worse, the check that would have caught it immediately did not: `len(convert(...))
== 15193` passed, because moving a byte between two entries does not change the
file's length. **Compare the fixture's bytes, not its size** — `Commando.sng` is
on disk for that purpose and `got == ref` is one line.

### 7.kkk The vibrato onset: the best-scoring constant is the wrong one

With the arpeggio fixed, the listener still heard missing movement, and §7.iii's
diagnostic named the cause: on Commando's GT 1 the original's first pitch change
lands on frame 1 and ours on frame 13. That is `_vibrato_delay`, which emits
`vibdelay = 8` on this dialect to stand in for the player's per-note length gate
(§7.aaa: `CMP #$08` on the note's stored duration — a threshold decided before
the note sounds, which no Goattracker instrument can express, since `vibdelay` is
per instrument). Its own docstring named the cost and called it "much the smaller
error". That was an assertion; this section is the measurement.

Across the 25 corpus files the gate reaches, over 2487 notes belonging to
instruments whose *only* pitch movement is the vibrato — no drum bit, no arpeggio
bit, so nothing else can move the frequency — the original moves 435. Two axes:

```
gate   moves/still agrees   still notes we wobble   onset late (median)
   1                65.9%              826 of 2052                   +0
   8                85.5%                      207                  +10
  12                88.6%                      114                  +15
  14                88.6%                      113                  +17
```

They oppose each other, and that is the whole finding. `vibdelay 1` fixes the
onset *exactly* — median +0 — and wobbles 40% of the notes that should be still.
`8` catches 282 of the 435 and is a fifth of a second late on them. The spurious
wobble is the more audible error, so 8 ships: **not because it scores higher, but
because of which error it makes.**

The trap is the row below it. 12 scores best, and shipping it would have been
defensible on any single column — but the moves/still column cannot see the five
extra frames of lateness it costs, and it *plateaus* at 14 rather than peaking,
which is the signature of a measure saturating rather than optimising. Raising
the delay makes short notes stop moving; run it far enough and every note agrees
by being still. 8 is the value read out of the player's own comparison; 12 is a
value fitted to a proxy blind to the defect that started the investigation. This
is the rule about a count versus a travel measure (§7.xx) in its other form: **a
count can be maximised by destroying the events it counts**, and the `$FF`
firstwave scored `wave` 99.5% by deleting 79 notes for the same reason.

Two method notes from the run itself, both of the kind this document exists to
record:

- **The first pairing found zero notes.** Keying a note by its absolute frame
  cannot match across sides that differ by the startup lag — the same class of
  error as the four attack-anchored boundary mistakes in §7.ddd. Pairing by note
  index per voice fixed it.
- **The first sweep's "8" and the second's disagreed** (85.5% against 83.2%)
  because one called the real `_vibrato_delay` — which returns `gate ×
  multiplier` — and the other passed a literal 8, so multispeed files got 16 in
  one and 8 in the other. Reproducing the old number under the new sweep before
  believing any difference is what surfaced it, per the `--vice` rule in
  `CLAUDE.md`. The scaling is worth 2.3pp on its own.

Getting both halves is possible but not here: the gate is per note and
`vibdelay` is per instrument, so it needs a pattern-level vibrato command on
qualifying notes with `vibdelay 1`. `tests/test_vibrato.py` pins the constant at
8 with this reasoning attached, so the next pass at it does not re-derive 12.

### 7.lll The gate, expressed per note — and a constant read from one file

§7.kkk ended by naming the fix it could not make: the player's gate is per
*note* and `vibdelay` is per *instrument*, so getting both halves needs a
pattern-level command. Building it turned up two things, and the second is the
larger.

**The mechanism was already there, in a fallthrough.** `gplay.c`:

```c
case CMD_DONOTHING:
  if ((!cptr->cmddata) || (!cptr->vibdelay)) break;
  if (cptr->vibdelay > 1) { cptr->vibdelay--; break; }
case CMD_VIBRATO:          // <-- entered directly by a commanded row
```

The `vibdelay` countdown sits *inside* `case CMD_DONOTHING`. A row carrying
`$04` enters at the second label and never sees it, so a commanded vibrato runs
from the note's first call however large the instrument's delay is. And `$04 00`
gives `cmddata = 0`, which still enters the case but computes `cmpvalue = 0,
speed = 0` — a *damping* that applies per note, where zeroing the instrument's
pointer would suppress the un-commandable notes too. Long note gets the index,
short note gets zero, gate reproduced exactly.

Three properties of the existing row stream made this a pass rather than a
rewrite, and all three had to be checked rather than assumed:

- **Hold rows already repeat the note row's command** (`events += [GT_NO_NOTE,
  0x00, cmd1, cmd2]`). Without that an empty row would reset `cmddata` to the
  instrument pointer and stop the oscillation one row in.
- **`$BD` is "no new note", not a rest.** gplay.c:925 assigns `newnote` only for
  `<= LASTNOTE`, so a `$BD` row continues the note and is safe to count as part
  of its block. `$BE`/`$BF` are handled earlier and end a block.
- **The gate needs no unit conversion.** `wait = b1 & 0x1F` is the identical
  expression to the player's `AND #$1F` on the same byte, so a note occupies
  `wait + 1` rows and `wait >= gate` is a row count — the one rate-like
  quantity in the writer that must *not* be divided by the multiplier.

#### The constant was read from one file, and 5 of 25 disagree

The first run of the finished pass damped **695 of Commando's 705 notes and
vibrated 10**, which is the opposite of the intended effect. `TRIANGLE_VIBRATO_GATE
= 8` came from one player's `CMP #$08`; searching Commando for that shape finds
it *nowhere*. Its two `AND #$1F / CMP` tests compare against `$06` and `$03`.

Read at a fixed +56 bytes from the oscillator's own match — which holds in all
25 files — the thresholds are 8 in twenty of them and 6, 5, 4, 4, 2 in the rest.
The +56 anchor matters: every one of these players has a *second* gate on the
same duration cell 377 bytes further on, guarding an unrelated effect, and a
scan takes whichever comes first.

With Commando's own 6 the pass vibrates 50 notes, and the number is checkable
rather than fitted. Its stored durations are in units of three frames, so
`wait >= 6` means "24 frames or longer"; voice 1 has 27 notes of 24 frames and 4
of 30 — **exactly the 31 notes the original's trace is measured to move the
pitch on** (§7.kkk's diagnostic). That correspondence is what makes 6 a reading.

#### The same constant is right in one role and wrong in the other

Over the 2487 notes of § 7.kkk:

```
                                 agree   miss  invent   onset (median)
delay, gate 8 (v0.5.198)         85.5%    153     207              +10
delay, the file's own gate       78.9%    109     417              +10
command + damp, file's gate      92.1%    129      68               +0
```

The middle row is the one worth keeping. Feeding the correct per-file threshold
into the *delay* makes it markedly worse, because a delay is doing two jobs —
suppressing short notes and postponing long ones — and a lower threshold gives
up the first without buying anything. Behind the commands, where the damping
does the suppressing, the same per-file threshold is the *better* number for the
residue (92.1% against 90.3%, 129 misses against 173, almost all of it Ninja
with its gate of 2). So `_vibrato_delay` takes a `commanded` parameter rather
than a convenience default: **a number can be correct for the mechanism and
wrong for the approximation of it.**

The command pass beats the shipped behaviour on *both* axes at once, which
neither `vibdelay` value could do (§7.kkk), and reaches 100.0% on Commando,
Battle of Britain, Crazy Comets, Hunter Patrol, Ninja and One Man and his
Droid. The instrument keeps its pointer so an unreachable note — command column
already carrying a portamento, or instrument not yet named in the pattern —
falls back to the v0.5.198 approximation instead of going silent; zeroing it
scores higher on the agreement column alone and silences 60 qualifying notes.

Two process notes: the fixture could not have caught any of this, because it is
a GTS2 file and `_vibrato_layout` returns nothing for GTS2 — the whole mechanism
is unreachable from the project's only byte-exact anchor, which is why the
corpus measurement is the check. And no dimension of `FIDELITY.md` measures an
oscillation onset, so the report cannot adjudicate this change either; the
per-note measure in this section is what does.

### 7.mmm "Too many notes" was the right notes with the wrong endings

A listener pointed at pattern 12 of Commando: *"the slide is not correct, it
plays too many notes."* Three checks disposed of the stated diagnosis before
anything was changed:

- **The notes are right.** Voice 1 aligns with the original at difflib ratio
  1.00 over 60 s, 231 attacks against 230. Voice 3 likewise.
- **The pattern decodes exactly.** Every byte of Hubbard pattern 9 accounts for
  itself as `wait`/instrument/note; the repeated `01 3E / 01 3E` events are
  genuinely repeated notes in the player.
- **There is no slide in it.** The lead's effect byte is `00`, the pattern
  carries no slide operand, and its record `+6 = $E0` is the triangle pulse
  engine's rate — so § 7.iii's finding still holds: every "slide" in Commando is
  a vibrato.

What a frame-by-frame register dump showed instead:

```
        ORIGINAL              OURS
2485  * 2710 41 295F   →   * 2714 41 295F     note on
2488    2710 40 0000   →     2714 40 295F     gate off
2489    2710 40 0000   →     2714 40 295F     ...still ringing
2490    2710 40 0000   →     2714 09 295F     testbit finally cuts it
2491  * 2BD6 41 295F   →   * 2BDD 41 295F     next note
```

The gate-off frame matches. The *envelope* does not: the original writes
`AD = 0, SR = 0`, so the note stops dead and there are three frames of silence;
we keep the record's `$5F`, release `F`, so it rings until our hard-restart
testbit chops it. Five frames of sound where the original has three, no silence
between, and a click at the end — a staccato figure delivered legato. **The
notes were right and their tails were overlapping**, which is what "too many
notes" was describing.

#### The mechanism, and a correlation that was not it

The routine is at Commando `$518B`, reached from `$517F`:

```
LDA duration,X / AND #$20 / BNE skip    ; status bit 5 -- a tie flag
LDA counter,X  / BNE skip               ; only on the note's last row
LDA wave,X / AND #$FE / STA $D404,Y     ; gate off
LDA #$00 / STA $D405,Y / STA $D406,Y    ; envelope destroyed
```

**Status-byte bit 5 is a tie flag** — clear means "cut this note". Our decoder
already reads that bit (as `no_adsr`, mapping it to `CMD_TONEPORTA` when the
instrument is unchanged, which is a defensible tie), but nothing used its
*clear* case. 91% of 53308 notes across the 72 classic files are cut; Commando
is 708 to 21.

Getting there took a wrong turn worth recording. The first census asked, per
gate-off edge, whether the ADSR register *was* zero on the edge frame:
**20.7% corpus-wide**, and per instrument on Commando it split 100%/0% into a
clean-looking pattern that two different hypotheses fitted — "effect bit `$01`
clear" and "release nibble `= $F`" — at 59.8% and 79.0% corpus accuracy. Neither
is a mechanism, and shipping on either would have been fitting. Reading the
player settled it in one step; and once the measure took the release as a
**minimum over the whole gap** rather than the value on the edge frame, the
behaviour turned out to be present on **100% of Commando's instruments**, not
20.7% of its edges. The player simply does not write its zero on the edge frame.

#### The measure, and the key that erased its own subject

`FIDELITY.md` could not see any of this and still cannot see note length
(CLAUDE.md). `adsr` compares the envelope pair *while a note plays*, where both
sides agree — both write `295F` at the attack. `wave` and `nrun` read `$D404`,
and both sides gate off on the same frame. So the report needed a column for
what the envelope does after the gate closes: `release_tails` / the **`tail`**
column, built on `noise_runs`' shape — per-instrument, attributed at a run's
midpoint, runs and gaps touching the window edge dropped.

Its first version reported `n/a` for the very change it was written to measure.
The attribution key was the whole ADSR pair, and emitting a zero release moves
every one of our keys from `295F` to `2950`, so no instrument was shared with
the original and there was nothing to compare. **An attribution key must not
contain the quantity being attributed** — the release nibble is masked out of it
now. This is the same trap as reading a duration at a fixed offset from the
event whose duration changed (§ 7.ddd), in the other axis.

Result over the 30 measurable files: mean `tail` **27.6% → 99.2%**, better on
27, worse on none, `melody` unchanged at 78.2% — so nothing was lost, the change
is entirely in the note endings. Commando 0% → 100% on all seven instruments.
The sustain nibble is untouched: it governs the note while it plays, which is
not what the cut destroys.

#### And it pushes an existing column down 17 points

Corpus mean `adsr` falls **75% → 58%**. Attributed, rather than assumed: the
change is **−47.1 pp on the 29 files that have the cut routine and exactly
0.0 pp on the 50 that do not**, so the cause is not in doubt.

It is nonetheless not a regression in the sound. Those players write the record
verbatim at the attack, so the original's register holds `295F` where ours now
holds `2950`, and `adsr` compares the pair literally. But the release nibble is
consulted by the SID only when the gate falls, and by then the player has
overwritten it with zero — the `F` never acts. Attack, decay and sustain are
identical on both sides, so the envelope behaves the same on every frame.

Two things follow, and both are the point of this section. **A register-value
agreement is not an envelope-behaviour agreement**, and this is the first change
in the project where the two point in opposite directions — the standing rule
that a low score is a claim about the harness until it is a claim about the
converter, applied to a *fall* rather than a flat line. And the honest response
is not to redefine `adsr` so the change scores well: the report now states the
attribution beside the number, so nobody reads 58% as damage, and `tail` carries
the property that matters.

The alternative encodings were considered and do not exist. Keeping `SR = $5F`
and cutting the note in the wavetable would match the registers *and* the sound,
but the cut lands on the note's final row and a Goattracker wavetable is per
instrument, so it cannot say "at the end of whatever note this is" — the same
wall § 7.lll hit with the vibrato gate, and there is no per-note release
command to escape through.

### 7.nnn The same evidence, reduced two ways — and the drums paid for it

v0.5.200 (§ 7.mmm) shipped the envelope cut for **every** record of a file whose
player has the cut routine. A listener came back one build later: *"something bad
happened to the drums, perhaps the previous version sounded better."* It had.

The trace had said so all along. Per instrument, on Commando, what the envelope
does in the gap after a note:

```
rec  eff   first frames of the gap
  0   00   0000 0000 0000          <- cut on the gate-off frame
  2   08   0000 0000 0000          <- cut
  1   05   064B 064B 064B 064B     <- never cut: a real release
  7   05   0DFB 0DFB 0DFB 0DFB     <- never cut
 12   01   090A 090A 090A 090A     <- never cut
  3   05   0A09 0A09 0000 0000     <- holds 2 frames, then the NEXT note's zero
  4   03   0FC4 0FC4 0000 0000     <- likewise
```

Only two of seven are cut. **The cut is one write on the note's last row, and an
instrument whose effect routine runs every frame overwrites it**, so its release
survives and is heard. Zeroing it silences the drum's tail.

#### Why the measure said the opposite

`release_tails` took the release as the **minimum over the whole gap** to the
next note. The reasoning was that a minimum cannot depend on which frame the
player writes on — true, and beside the point: it also cannot tell *this* note's
cut from the *next* note's preparation. Records 3 and 4 above are zeroed by the
next note; records 1, 7 and 12 reach 0 somewhere later in a long gap. So the
column scored all seven instruments as cut, agreed with a writer that zeroed all
seven releases, and reported **27.6% → 99.2%, better on 27 files and worse on
none** for a change that was making files worse.

Read on the gate-off frame — one write, one frame, no ambiguity — the same three
builds measure:

```
                            mean tail   melody
off (v0.5.199)                  64.6%    78.2%
every record (v0.5.200)         62.1%    78.2%
gated per instrument            97.4%    78.2%
```

v0.5.200 was a **net regression** on the corpus, not the improvement it was
committed as: Commando 71% → 29%, Zoids 83% → 17%, Rasputin 80% → 20%.

The lesson generalises past this bug. § 7.mmm justified the gap reduction by
citing the *edge* reading as the error — "20.7% at the edge, 100% over the gap"
— and drew the conclusion that the wider window was the truer one. It was the
other way round: the edge reading was right, and the gap reading was admitting a
second event. **Widening a window is not automatically the safer reduction.**
When two reductions of the same signal disagree by 5x, that is not a
measurement detail to be settled by which number looks more plausible; one of
them is counting something else, and which one has to be established by looking
at the frames.

#### And the discriminator was there too

§ 7.mmm dismissed "effect bit `$01` clear" at **59.8%** corpus accuracy as a
correlation rather than a mechanism. That figure was computed over all 95 files
— but in the 62 with no cut routine nothing is cut whatever the effect byte
says, so they could contribute only false positives. Restricted to the 33 files
where the behaviour occurs, the same rule is **98.6%** accurate over 143
unambiguous instruments, with **no false negatives** and 2 false positives.
`& $07` scores 86.0%, `== 0` 78.3%.

So the rule that was rejected for being a mere correlation was in fact the
mechanism, mis-scored by evaluating it on a population where the phenomenon does
not exist. **A discriminator is only meaningful on the population the behaviour
occurs in** — and a necessary condition with zero false negatives deserves more
attention than its raw accuracy suggests, which was the one clue in § 7.mmm's
own table that pointed the right way and was not followed.

### 7.ooo Status bit 5, third time: it is a tie, and Goattracker can say it

A listener, on pattern `$12` of Commando: *"note E-5 on pos 16 should not be
played as a note but the glide from F#5 should stop at E-5 ... maybe the attack
on E-5 is too strong."* Both halves of that are one defect, and the trace names
it at frame 3896:

```
          ORIGINAL                  OURS
row 12    3138 41 * attack          313C 41 * attack
          30EA 309C 304E 3000 ...   313C 30D7 3072 3072 ...   the glide
row 15    2E7A 2E2C 2DDE 41         2F43 2EDE 40 -> 09        we close the gate
row 16    2BD6 41   no attack       2BDD 41  * ATTACK
```

**Status bit 5 again.** § 7.mmm found it gating the envelope cut and § 7.nnn
found which instruments that reaches; the bit's actual meaning is *don't close
the gate at this note's end*, and the consequence had not been drawn: the note
that **follows** a tied event arrives with the gate already open, so the player's
note-on writes a frequency and nothing else. No gate edge, no attack. Legato.

Two things had to be found before this could be fixed, and finding the pattern
was the harder one:

- **Goattracker numbers patterns in hex.** "PATT.12" in the editor is pattern
  **18**. Three separate dumps of `new_patterns[12]` disagreed with the
  screenshot before that landed, and the notes looked plausible enough each time
  to keep chasing the wrong data.
- **The editor's pattern is not the converter's intermediate.** GT pattern 18 is
  Hubbard pattern **15**, after de-duplication; and the orderlist's leading `D3`
  transposes, so the pitches on screen are not the pitches in the pattern bytes
  either. Matching by *note-row positions* rather than by index or by pitch is
  what identified it.

#### The mechanism exists in the target format, in one command

`CMD_TONEPORTA` with parameter **0** does all four things the tie needs:

```c
case CMD_TONEPORTA:                       // gplay.c:805
  if (!cptr->cmddata) {
    cptr->freq = targetfreq;               // an instant jump, not a slide
    cptr->lastnote = cptr->note;
    cptr->vibtime = 0;                     // the vibrato restarts on the landing
  }
...
if ((cptr->newcommand) != CMD_TONEPORTA) { // :930
  if (!(instr[...].gatetimer & 0x40)) cptr->gate = 0xfe;   // gate-off SKIPPED
```

plus `:355`, which skips the `firstwave` testbit on the same test. So one command
on the landing row reproduces the player exactly -- and the parameter has to be
**0**, because any speed makes it a slide instead of the jump the player performs.

It goes on the note *after* the tied event. The original **does** attack on the
slide row; putting the command there instead would delete an attack that is
really played. The existing decoder had read bit 5 for years (as `no_adsr`, the
VB6 comment calling it "Portamento (no new ADSR)") and emitted `CMD_TONEPORTA`
**on the tied row itself**, gated on the instrument being unchanged -- which for
Commando was inert, because the slide branch overwrote the command a few lines
later. The bit was read and its consequence was not.

#### Result

Commando's voice 1: attacks **511 -> 501** against the original's 502, and the
waveform through the landing becomes `41 41 41 41`, frame for frame what the
original does. Over the 64 classic files carrying tied events:

```
              median retrig   mean melody
off                   1.008         82.3%
--tie                 0.999         84.1%
```

19 files better on `melody`, 5 worse. **Delta_Mix-E-Load_loader goes 6% ->
100%** with its retrigger ratio 2.133 -> 1.067: nearly every note in it is
tied, and every one was being re-struck. Chimera 86% -> 98%, Confuzion 93% ->
99%, Action Biker's retrigger 1.333 -> 0.990, Auf Wiedersehen Monty 1.169 ->
1.013, W.A.R. 1.061 -> 1.000.

The worst regression is Kentilla, `melody` 95% -> 85%, whose *retrigger* ratio
improves over the same change (1.127 -> 1.035). `melody` is a difflib ratio over
a fixed window, so a conversion that stops emitting 30 spurious attacks shifts
what falls inside the window -- the standing "a score is not a clock" caveat,
here in its note-count form rather than its tempo form.

### 7.ppp The snare overshoot: run lengths named both causes at once

`--wave-program` (§ 7.fff) restored Trans-Atlantic's snare and a listener said
"the drum is better but not full fidelity". Measured, it sounded **670 noise
frames against the original's 387**. Totals could not say why; run lengths
could, and this is the third time `fidelity.noise_runs`' shape has been the one
that works:

```
instrument 0729 (43 notes)   original: 43 runs of 1, 43 runs of 8
                             ours:     43 of 1, 36 of 6, 3 of 30, 2 of 54, 1 of 78
```

Two separate defects in one column. The program decodes as `81 30` (noise, one
frame), two slides under released waveforms (two frames), eight `80` opcodes
(eight frames of noise), hold.

- **The 6 instead of 8**: a slide opcode was emitted as *two* wavetable entries,
  the waveform and then a portamento command. The player advances one opcode per
  frame and a wavetable spends a call on every entry, so two slides made the
  program 13 frames where the player's is 11 -- and the closing burst, being
  last, is what the note length then truncated. One entry per opcode now; the
  pitch movement is dropped. **A rate error and a length error look the same in a
  total and different in a distribution.**
- **The 30, 54 and 78**: the program ended holding noise. The emitter's own
  docstring asserted that Goattracker "keeps the last waveform, as the player
  does" -- and the player does not. Its note-end routine writes the *stored*
  waveform with the gate cleared, `LDA $54F8,X / AND #$FE / STA $D404,Y`: the
  very routine § 7.mmm read for the envelope cut, in the same file, three
  sections earlier. A program ending on noise therefore stops sounding noise
  when the note ends; holding it ran the burst into the gap. The record's own
  waveform is emitted before the stop now.

Both fixed, the snare's runs are **identical to the original's**: `{1: 43, 8: 43}`
on each side, 387 noise frames against 387, `nrun` 50% -> 67%, where without the
program voice 2 sounds none at all against 387.

#### A criterion that cannot see a per-instrument defect

`presets.fidelity_better` still scores the fixed program as *worse*, and not by a
margin -- structurally. Its `finds_noise` criterion requires the reference to
have **no audible noise**, which was written for "this conversion is missing its
drums outright" (§ 7.fff: 0 frames against 1089). Trans-Atlantic now has plenty
of noise from another instrument, so the test passes at file level while the
snare is absent at instrument level: **a per-file test for a per-instrument
defect, and a present hi-hat masks a missing snare.** `melody` meanwhile falls
95% -> 85%, because siddump reads noise onsets as notes and the compared sequence
gains 43 of them -- § 7.eee's blind spot again, in the direction that penalises
being right.

So the verdict is recorded in `presets.FIDELITY_CONFIRMED`, the mirror of
`FIDELITY_VETOED` and new here: a setting a listening test *confirmed* and the
search disagrees with. Both dictionaries now name the same file -- one vetoing
the wrong drum, one confirming the right one, which is a fair summary of how this
file has gone. The principled fix is to score `finds_noise` per instrument off
`noise_runs`; that re-decides every file's toggles and needs its own corpus run,
so it is deliberately not folded in here.

### 7.qqq Effect bits $20 and $40, and a drum that is three bits interleaved

A listener on the balloon song, after § 7.ppp made its snare register-exact:
*"I do hear sound where the drums are but not snare drums."* The snare was right;
a **second** drum was not, and chasing it turned up two effect bits this
converter had never read.

#### Why they were never found

Detection looks for `AND #$xx` against the effect byte. Bit 6 has an idiom of its
own -- `BIT cell / BVC` -- so **no scan for `AND #$40` could ever match**, which
is the same trick `STATUS_BIT6_SHAPE` already relies on one field over. Anchored
on the effect cell (the address the player tests with at least two masks whose
meaning is known, which is what identifies it as the effect byte's copy rather
than some other flag word):

```
$20 tested with AND #$20      35 of 95 files
$40 tested with BIT / BVC     41 of 95 files
```

216 instrument records set `$20` and 204 set `$40`, across 57 files.

#### $20 is a filter cutoff sweep

```
LDA effect / AND #$20 / BEQ out
LDA accum,X / CLC / ADC step,Y / STA accum,X
STA $D416                       ; cutoff high byte
LDA res,Y / STA $D417           ; resonance and routing
```

A per-voice accumulator advanced by a per-instrument step every frame. An
independent shape census -- an accumulate followed by `STA $D416` -- finds it in
31 files, against 35 anchored on the cell.

#### $40 is a fixed pitch out of the player's own note table

```
LDA counter,X / BEQ + / DEC counter,X / LDA $116B,Y / JMP fetch
+ LDA gate,Y / BNE out / LDA note,X
fetch  ASL / TAY / LDA table,Y / STA freqlo,X / LDA table+1,Y / STA freqhi,X
```

Three things had to be pinned, and two of them cost a wrong turn:

* **The two cells are the voice frequency** -- they feed `$D400`/`$D401`
  directly a few instructions later.
* **The table is the note table.** `sidfile.find_freq_table` locates it
  independently and returns the address this routine indexes, so the value is a
  *note* rather than an arbitrary number.
* **`Y` is the record offset, not the record number.** Read as a number the byte
  is 129 on record 1, mapping to `$1A03`, which is not a pitch the trace shows.
  Read as `index x stride` it is `$34` = 52, and `freqtable[52]` is `$15EB` --
  the frequency the original sounds on **226 of 226** frames. The clue that
  forced it: the `$08` interpreter reads `$116B,Y` and `$116C,Y` as one
  pointer's two halves, which only works if `Y` steps by more than one.

And the array is `det.wave_program` itself -- the same cell, a pointer low byte
under `$08` and a note index under `$40`. One byte, two meanings, chosen by the
bit, as with `$01` (drum or wave program) and `$80` (drum or program).

#### The drum is three bits interleaved by frame, which is why emitting one made it worse

Emitted onto the attack's first frame -- the only place a two-stage block can put
a note today -- the pitch is exactly right and `melody` **falls 85% to 39%**.
Measuring where the original actually puts it explains that in one table. Per
note, offsets from the attack frame:

```
offset 0   the PLAYED note's pitch    (freq-hi 3-13)   <- what melody reads
offset 1   noise at freq-hi 56        ($80, sfx_pitch = 56)
offset 2   noise at freq-hi 21        ($40, freqtable[52] = $15EB)
```

So `$04` supplies the attack waveform, `$80` the second frame's pitch and `$40`
the third's, and the attack frame keeps the pattern's note. **The bits interleave
by frame rather than stacking**, and any one of them alone lands its pitch on a
frame that belongs to another. That is also the retrospective verdict on § 7.fff's
listening veto: `--sfx-drum` was heard as "beeping" because it supplied offset 1
with nothing at offset 2 and no attack waveform in front -- a third of a drum.

The decode lands here and the emission does not: `det.effect_bit40` and
`goatwriter._fixed_attack_note` are read, tested and unwired, exactly as
`two_stage`'s arrays and the `$08` interpreter were before them. Emitting it
means emitting `$04`, `$80` and `$40` together as one per-frame block, which is a
larger change than any of the three.

### 7.rrr Composing the three bits: the profile that fits one file and not the next

§ 7.qqq decoded bit `$40` and stopped short of emitting it, because putting its
pitch on the attack's first frame took Trans-Atlantic's melody from 85% to 39%.
The per-frame profile says where it does belong. Raw frames, identical on all
three notes sampled and on all 226 by aggregate:

```
+0  wf 41  freq = the played note        (the record's own waveform)
+1  wf 81  freq = $38CE / $38B4 / $389C  NOISE
+2  wf 81  freq = $15EB                  NOISE
+3..+6  wf 41  the played note
+7  wf 81  freq = $38xx                  NOISE      (6 frames on: sfx_period)
```

Two details fall out of that and both were previously open. The `$38xx` frames
keep the **played note's low byte** (`05CE` → `38CE`), which is the signature of a
routine writing only `$D401` -- confirming bit `$80` as a high-byte-only write.
And `$15EB` is exactly `freqtable[52]`, the `$40` pitch.

Better still, `_sfx_drum_entries`' own docstring had recorded the target years
before the answer: *"the second frame's frequency is a fixed `$15EB` from
somewhere this reader has not found, so both frames are written at the pitch that
is read."* It is bit `$40`. Passing it as the burst's second note makes
Trans-Atlantic essentially exact:

```
                        melody   nrun   0A99 pitches            runs
original                    --     --   {21: 226, 56: 452}      {1: 226, 2: 226}
shipped (no sfx_drum)      85%    67%   3-13, smeared           {4: 226}
sfx_drum, both frames      85%   100%   {55: 678}  one pitch    {1: 226, 2: 226}
sfx_drum + the $40 pitch   85%   100%   {21: 226, 55: 452}      {1: 226, 2: 226}
```

#### And it is still not shipped, because Pandora says otherwise

```
Pandora, that instrument's noise pitches
  original   {3:13, 4:1, 5:7, 69:35, 72:364}     <- 35 frames at the $40 pitch
  before     {73: 620}
  after      {69: 281, 73: 339}                  <- 281 where 35 belong
```

**The `$40` pitch fires once per *note*; the drum block's entries loop once per
*period*.** Its counter runs out, so only the first burst after a note carries
it -- which is exactly what the Trans-Atlantic profile shows too (`+1,+2` a
two-frame burst, `+7` a one-frame tick). Trans-Atlantic happens to have one burst
per note, so per-tick and per-note coincide there and the numbers came out exact.
Pandora has many ticks per note and the same change over-applies eightfold.

That is the lesson worth more than the feature: **a profile measured on one file
can encode that file's own structure rather than the mechanism's.** The
Trans-Atlantic figures were not wrong, they were not general -- and the only
reason the difference surfaced is that Pandora ships with `--sfx-drum` on, so it
had to be checked before committing. Had the flag been off everywhere, the
regression would have shipped behind an exact-looking table.

Emitting it properly needs a **non-looping prologue** (played note, then the
two-frame burst whose second frame carries the `$40` pitch) ahead of a **looping
body** (the one-frame tick at the drum's pitch). `_sfx_drum_entries` returns a
single block that the caller closes with one jump, which cannot express two
regions. `second_note` is implemented and tested; nothing passes it.

A last note on visibility: `nrun` compares run *lengths* and `melody` reads the
attack frame, so **no dimension of the report can see a noise frame's pitch at
all**. Both the Trans-Atlantic gain and the Pandora regression are invisible to
`FIDELITY.md`; both were found by histogramming the pitch directly. That is a
column the report is missing.

### 7.sss The prologue and the loop, and a gate that was per file

§ 7.rrr established the shape and refused to ship it: bit `$40`'s pitch fires
once per *note* while `_sfx_drum_entries` returned one block the caller closed
with one jump, so the pitch landed on every *tick*. The fix is to let the jump
target the loop rather than the block, which the function now reports:

```
0  wave|1  00        the played note              offset 0
1  noise   drumnote  the drum's own high byte     offset 1
2  noise   $40 note  freqtable[index]             offset 2   <- prologue ends
3  wave|1  00                                     offset 3
4  delay 2 keep                                   offsets 4-6
5  noise   drumnote                               offset 7   <- loop starts here
6  wave|1  00                                     offset 8
7  delay 3 keep                                   offsets 9-12
   FF -> entry 5                                  offset 13, and every 6 after
```

Ticks at 1, 2, 7, 13, 19 -- the trace's profile, with the two-pitch burst once
and the single-pitch tick for as long as the note is held. The plain shape
(no `$40`) returns `loop = 0` and is byte-identical to before.

#### The gate was per file where the bit is per record

The first cut of this regressed Thundercats: `melody` 77% -> 72%, and 99 noise
frames at a pitch its original never sounds. `_fixed_attack_note` checked
`det.effect_bit40` -- which says the *player* reads the bit -- and never whether
*this record's* effect byte sets it. Thundercats' drum records are `$80` and
`$A0`; neither carries `$40`. **A detection flag about a player is not a fact
about a record**, and this converter has a whole family of per-record effect bits
where that distinction is the entire point.

With the gate on `data[rec + 7] & $40`:

```
                          ours                original            melody  nrun
Trans-Atlantic (forced)   {21: 226, 55: 452}  {21: 226, 56: 452}     85%  100%
Pandora                   {69:  35, 73: 375}  {69:  35, 72: 364}     96%  100%   (was 0%)
Thundercats               {73: 291} unchanged {72: 419}              77%  100%
```

Trans-Atlantic is exact; **Pandora's 35 frames at the `$40` pitch match the
original's 35 exactly** and its `nrun` goes 0% to 100%; Thundercats is untouched,
which is the correct answer for a record without the bit. The 55-against-56 and
73-against-72 gaps are `_sfx_note_byte`'s semitone quantisation, which for noise
is inaudible by the argument in its own docstring.

Note what carried this: none of it is visible in `FIDELITY.md` except Pandora's
`nrun`. The pitch histogram is still the only instrument that sees a drum's
colour, and it found both the win and the Thundercats regression.

### 7.ttt "Fix the vibrato rate" -- which was not the vibrato

The balloon song's `vib` column read **0.17x**: our pitch oscillating at a sixth
of the original's rate. The instruction was to fix the vibrato rate, and the
first measurement falsified the premise. Reversals by instrument:

```
instrument   original   ours     effect byte
0A09             1175     31     $10
0A99              904    112     $E4   (the drum, section 7.qqq)
0AF8              637     16     $14
0A88              317    257     $00, and the only record with a vibrato byte
```

The one instrument that *has* a vibrato is within 20% of the original. Nothing
was wrong with the rate: bound 4 emits `cmp 2`, a period of 8 calls against the
player's 4-frame half-period, which is exact. **The deficit was 1812 reversals of
a mechanism that had never been read at all.**

#### Bit $10 is a three-step arpeggio on a global phase

Read at $0BBB, and the shape is in **34 of 95 files** -- as widespread as the
two-stage attack:

```
LDA effect / AND #$10 / BEQ out
LDA index,Y / ASL / TAY            ; the record's own byte, doubled
LDA pairs,Y   / STA base+1         ; copy this instrument's two offsets
LDA pairs+1,Y / STA base+2
LDY phase                          ; a GLOBAL counter, DEC'd once per frame
CLC / LDA note,X / ADC base,Y      ; the played note plus this step
ASL / TAY / LDA freqtbl,Y ...
```

`seq[0]` is the byte at `base`, which nothing ever writes -- 0 in every file
checked. `seq[1..2]` are the instrument's pair. Trans-Atlantic's records 0 and 3
both hold `18 00`: **the note, two octaves up, the note**, on a three-frame
cycle. The phase counter closes the play routine as `DEC phase / BPL / LDA #$02 /
STA phase`, so its length is read rather than assumed.

And the index array is `det.wave_program` for the third time: a pointer low byte
under bit `$08`, a note index under `$40` (§ 7.qqq), a sequence index under
`$10`. One cell, three meanings, chosen by the bit.

#### It works, and the global phase is why it is off by default

Emitted as a three-entry wavetable loop, Trans-Atlantic's record 0 goes from 31
reversals to 1365 against the original's 1175, and the file's `vib` from 0.17x to
**0.61x** with `melody` unchanged. Across the 26 files that use it:

```
              median vib   mean melody
off                0.22x         81.5%
--pitch-seq        0.58x         76.3%
```

Seven files lose melody, After_8 by 40 points. **The phase is the reason and it
is not fixable here.** The player's counter is global, so which step a note opens
on depends on when the note happens; a Goattracker wavetable always starts at
entry 0. Leading with the modal step -- the likeliest value under a uniform
unknown phase, with the attack frame kept at the pattern's own note -- was tried
and moved the mean by -1 point, trading After_8 (92% -> 52%) for Chain Reaction.
There is no rotation that is right more than a third of the time.

So it ships read, emitted and **off**, and deliberately not in
`FIDELITY_TOGGLES`: `fidelity_better` selects on a melody *gain*, so it would
never pick this up even on the file where it plainly helps. Choosing it per song
needs a scorer that weighs oscillation -- the same gap § 7.rrr found for noise
pitch. Two mechanisms now wait on the same missing column.

### 7.uuu The scorer two mechanisms were waiting on

§ 7.rrr and § 7.ttt both ended the same way: a setting measured as closer to the
original that `presets.fidelity_better` could not select, because every criterion
it had was about *notes* or about a register we sounded **none** of. Neither the
drum's pitch nor the arpeggio's rate is either of those things.

Two terms, on the same one-sided footing as the existing pair:

- **Oscillation.** `reversal_ratio` is ours over theirs, so 1.0 is right. The
  distance to it is compared **in log space**, because 2.0x and 0.5x are the same
  size of wrong where `abs(r - 1)` calls one twice the other.
- **Noise pitch.** The median frequency each side spends its noise frames at,
  again as a ratio in log space. `_noise_pitch` was already computed for the
  audibility guard, so this needed no new measurement -- the numbers were in the
  tuple and unread.

Both keep `keeps_notes`, and that guard is what makes them safe: it is exactly
what rejects the arpeggio on the seven files where it costs melody while
accepting it on the one where it does not. Run over three files, the search now
answers

```
Trans-Atlantic   two_stage, sfx_drum, pitch_seq
After_8          defaults        (pitch_seq costs it 40 points of melody)
Chain Reaction   defaults        (100% -> 78%)
```

which is the per-song judgement both sections asked for.

#### And it retired a listening veto

The scorer selecting `sfx_drum` on Trans-Atlantic put the veto of § 7.fff back in
question, and the listener had already answered it: asked to A/B the shipping
build against one with the setting on, they reported **no audible difference at
all**. The verdict was "a beep and not a drum", recorded when the file had no
snare (§ 7.ppp fixed that) and the burst sounded one pitch for every frame
(§ 7.sss fixed that). A veto is retired when the ear stops objecting, not when a
number improves; here both happened, so `FIDELITY_VETOED` is now empty -- kept as
a comment, because the sequence of it is the useful part.

One practical note: five toggles is 31 combinations a song, each a convert, a
pack and two traces, so applying the new criteria corpus-wide is an hours-long
`--fidelity` run and has not been done. The three files measured today are
recorded in `FIDELITY_CONFIRMED` so the balloon song gets its result now rather
than waiting for it.

### 7.vvv Two bits on one record: the tests are sequential, not exclusive

§ 7.ttt emitted bit `$10`'s arpeggio and left one record of the balloon song
unreached. Trans-Atlantic's record 3 (`0AF8`) sets effect byte `$14` — both
`$10` **and** `$04`, the two-stage attack waveform of § 7.qqq — and
`_pitch_seq_entries` declined it, because its `+2` waveform is `$00` and every
entry that function emits puts `wave` on the *left* of the table, where
`$00`–`$0F` is a delay and not a waveform. The two-stage path then owned the
record and emitted no arpeggio at all: **0 pitch reversals in a 60 s trace,
against the original's 411.**

**The player does not choose between them.** The record's `+7` is copied to a
scratch cell once and then tested five times running — `$08` at `$0B44`, `$04`
at `$0B9C`, `$10` at `$0BB8`, `$20` at `$0BEB`, and `$40` as `BIT`/`BVC` at
`$0C05`:

```
0B9C  LDA $0EFB / AND #$04 / BEQ $0BB7   ; bit $04 -- the WAVEFORM
0BA3  LDA $0FAA,X / BEQ +                ;   attack counter still running?
0BA8  DEC $0FAA,X / LDA $116C,Y          ;   yes: the attack waveform
0BB1 +LDA $10DB,Y                        ;   no:  the record's own +2
0BB4  STA $0D5E,X                        ;   -> the voice's waveform cell
0BB7  CLC
0BB8  LDA $0EFB / AND #$10 / BEQ $0BEB   ; bit $10 -- the NOTE
0BBF  LDA $116B,Y / ASL / TAY            ;   this record's sequence
      LDA $10AE,Y / STA $10AC ...        ;   copy its two offsets
0BD0  LDY $107C                          ;   the GLOBAL phase
0BD4  LDA $0D61,X / ADC $10AB,Y          ;   played note + this step
0BDC  LDA $0C8C,Y / STA $0EE5,X          ;   -> the voice's frequency
      LDA $0C8D,Y / STA $0EB5,X
```

Nothing between `$0BB7` and `$0BB8` can skip the second test. `$04` writes the
waveform cell and falls through; `$10` writes the frequency pair. A record
setting both gets both, on the same frames — and the original's trace says
exactly that: five frames of `$11` from the onset with the frequency stepping
`+24, 0, 0, +24, 0` through them, and the arpeggio still running after the
waveform drops to `$00`.

So the emission is **one block carrying both**: `frames × multiplier` entries of
the attack waveform, then the sustain stage, then a jump back to the sustain
stage's *first* entry — the attack runs once per note, the arpeggio for as long
as the note is held. Every frame gets its own entry; a delay cannot carry a note
that changes on the frames it covers, because `gplay.c:697-723` applies the
right side only on the delay's last call. That is the cost of the mechanism, not
a choice.

```
11/00  11/00  11/18  11/00  11/00 | 10/18  10/00  10/00 | FF/06
`-------- attack, 5 frames -------' `--- sustain ------' `- loop to entry 6
```

`0AF8` goes from **0 reversals to 392** against the original's 411, on
*unchanged* note counts (70 either side, before and after) — so this is not the
"fewer events score better" artefact of the v0.5.176 candidate. `vib` moves
**0.72x → 0.87x** and every other column of the row is identical to the
decimal, `melody` and `wave` included: the change alters the note on those
frames and never the waveform, which is precisely what those two columns do and
do not read.

#### The rule that only a second file could find

Trans-Atlantic is the sole corpus file shipping both `--two-stage` and
`--pitch-seq`, so a corpus differential hash moves exactly one file and the
evidence for the shape is one song. § 7.rrr is the standing warning about that,
and forcing both options onto **Thundercats** — four records at `$34`, a
two-step sequence rather than three, a real sustaining `+2`, and multiplier 3
rather than 1 — earned it again.

Its reversals came out *exact*: 1308 against the original's 1308. Its `melody`
fell **77.3% → 65.7%**, on unchanged note counts.

The cause is where the arpeggio's frames land, the same axis as § 7.qqq.
`_pitch_seq_notes` rotates the cycle so the modal step follows the attack, and
Thundercats' sequence opens `+3`; entry 0 is applied on the note's *first* call,
which is where `melody` — and a listener — read the note's identity. All 148
notes were named three semitones sharp. On Trans-Atlantic the same rotation
happens to open on zero, which is why the primary file could not see it.

The composed block therefore **opens on a zero step wherever the cycle has
one**, and it nearly always does: `seq[0]` is the byte nothing writes. The
player's phase is global and unknowable here, so whichever step really falls on
the onset is a guess either way — but a step of zero is the one guess that
cannot *rename* the note. With it, Thundercats keeps 1308/1308 **and** its
`melody` and `sequence` are unchanged to four decimals, and Trans-Atlantic's
bytes do not move at all. A rotation is the freedom `_pitch_seq_notes` already
exercises; this narrows the choice rather than contradicting it, and it is
applied in the composed path only, so the eight files shipping the standalone
arpeggio are byte for byte as they were.

#### Two things left standing

- **The evidence for shipping is still one file.** Thundercats and
  Bangkok_Knights confirm the *shape*, the gating and the rate, but neither
  ships `--pitch-seq` and `--two-stage` together, so neither is a shipped
  measurement. What reaches users is Trans-Atlantic's row and nothing else.
- **`_pitch_seq_entries` does not scale its rate by `multiplier`.** The composed
  path does — § 7.bb's rule, and what `_two_stage_entries` already does to
  `frames` three lines away — so the two agree only at multiplier 1, which is
  where the composition is measured. Three shipped multispeed files
  (Flash_Gordon at 4, Shockway_Rider and Star_Paws at 2) would run the
  standalone arpeggio that many times too fast if the rule holds for it.
  Flagged and not changed here, and **the trace cannot settle it**: run against
  Thundercats at multiplier 3, scaled and unscaled emit different bytes and
  score the *identical* 1308 reversals, because siddump samples the registers
  once per frame whatever the call rate and an arpeggio cycling per call
  aliases to one cycling per frame. `--vice` is the instrument that would see
  it (§ 7.nn). Until then, "1308/1308 at multiplier 3" is evidence for the
  block's *shape* and for its note content, and for nothing about its rate.

### 7.www The note's first frame belongs to the record, not to the effect

`_drum_entries` learned in v0.5.172 that **the player writes the record's own
`+2` waveform on a note's first frame and reaches the effect block only from
the second** — Commando's trace reads `15 80 80 14 14` from each onset, and
opening the wavetable on the drum's noise ran it two frames early and dropped
that opening frame. The lesson was recorded in that one function and never
propagated. Both of the other emitters put their mechanism's first entry at
wavetable entry 0, so everything they emitted ran one frame early.

The measurement is the modal waveform class over frames 0..7 from each note
onset, per instrument, joined on ADSR the way `instrmap.py` joins — **with
identical note counts on both sides**, so none of this is the "fewer events,
fewer disagreements" artefact § 7 warns about elsewhere:

```
Trans-Atlantic GT 3 (+7 $08, the byte-code wave program), 43 onsets a side
  ORIGINAL  tri   noise tri   pulse noise noise noise noise
  OURS      noise tri   pulse noise noise noise noise noise    <- one frame early

Trans-Atlantic GT 5 (+7 $24, the two-stage attack), 24 onsets a side
  ORIGINAL  pulse noise pulse pulse pulse pulse pulse pulse
  OURS      noise pulse pulse pulse pulse pulse pulse pulse    <- one frame early

Thundercats GT 4/5/6/10 (+7 $34), 148 onsets each
  ORIGINAL  pulse noise pulse pulse pulse pulse pulse pulse
  OURS      noise pulse pulse pulse pulse pulse pulse pulse    <- the same
```

Each is the original shifted one frame left, and each original's frame 0 is
exactly `+2`'s class — `$11` tri for GT 3, `$41` pulse for GT 5. Prepending
that byte with the gate on, as `_drum_entries` does, makes all six frame-exact.

**The exception is what makes this a function and not a line.** A record whose
`+2` is `$00` has no waveform and no gate on its first frame, so siddump sees
no gate edge there and calls the *second* frame the onset. Trans-Atlantic's
GT 4 (`+2 $00`, a five-frame `$11` attack) already profiles as five frames of
`tri` from offset 0 and is **already aligned**; an entry for its silent frame
would move a block that is right, and a wavetable cannot write `$00` as a
waveform anyway ($00-$0F are delays). `_first_frame_entry` is that test, and it
leaves the one corpus record on the composed `$04`+`$10` path byte for byte.

**One frame is `multiplier` calls**, § 7.bb's rule again: the lead covers the
whole frame (an entry plus a delay), because at Thundercats' `-S3` a one-call
lead still leaves the attack inside frame 0. And in the composed path the loop
target moves with the lead, or the arpeggio's phase re-entry breaks.

Reach and cost, over the 8 corpus files that ship `--two-stage` or
`--wave-program` (the only files whose bytes move at all):

| | before | after |
|---|---:|---:|
| onset-frame agreement, mean of 8 | 66.3% | **71.7%** |
| Trans-Atlantic `melody` | 85% | **95%** |
| Trans-Atlantic `seq` | 86% | **94%** |
| `wave`, mean over the 7 that moved | — | **+2.1 pp** |

Tarzan's `wave` goes 64% → 77% and Thanatos' 94% → 100%; ACE_II and Saboteur_II
lose 2 and 3 points of it. Those two are the reading to be careful with:
`wave_compare` scores absolute frames against a single global startup lag,
while the onset-anchored measure of the same register reads ACE_II as *flat*
and Saboteur_II as **+0.2** — and the lag itself is unchanged on both. What
ACE_II exposes rather than causes is a separate defect: its GT 4 record claims
a two-frame attack where the original sounds one, so the correctly-placed lead
pushes the surplus noise frame from offset 0 (where it was wrong) to offset 2
(where it is still wrong).

**And one number moves away from the original, for a reason worth recording.**
Trans-Atlantic's noise frames go 1089 → 1053 against an original's 1089 — an
exact match, lost. All 36 are in GT 3, the wave-program snare, and they are the
*last* frame of each of 36 notes:

```
  ORIGINAL  tri noise tri pulse noise noise noise noise noise noise noise noise $00
  before    noise tri pulse noise noise noise noise noise noise noise $00 tri tri
  after     tri noise tri pulse noise noise noise noise noise noise noise $00 tri tri
```

Our note is one frame shorter than the original's here, so shifting the program
onto its right frames pushes its final noise entry past the note's end. Before,
nine noise frames sat one frame early; after, eight sit exactly where the
original's are. A frame **count** cannot tell those apart — `nrun`, which
compares run *lengths* per instrument, does not move — which is the same
count-versus-placement trap as § 7.qqq.

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

### 7.kk The LFO-table vibrato, and what Goattracker's half-period really is

§ 7.gg ends by naming Hollywood or Bust's missing movement — a vibrato driven
by an arbitrary table rather than by the `$78`/`$07` pair § 7.ee reads — and
leaving it unimplemented. This is that approximation, and finding it required
correcting a fact § 7.ee had assumed about the *target* rather than the source.

#### The player: two nibbles, four tables

The parameter byte sits at instrument record `+5`, the same offset the classic
form uses, and splits the other way (Hollywood or Bust `$05CE`, Chicken Song
`$11AF`, byte for byte the same routine):

```
05CE  B9 00 0A  LDA record+5,Y
05D1  D0 03     BNE on
05D3  4C 91 06  JMP past          ; zero -> no vibrato at all
05D6  48        PHA
05D7  29 0F     AND #$0F          ; low nibble: how many units per table step
05D9  8D 86 09  STA count
05DC  68        PLA
05DD  29 F0     AND #$F0          ; high nibble: WHICH table
05DF  4A 4A 4A 4A / AA
05E4  BD F3 09  LDA lfo_lo,X      ; two pointer tables, LO then HI...
05E7  8D FA 05  STA $05FA         ; ...patched straight into the fetch
05EA  BD F7 09  LDA lfo_hi,X
05ED  8D FB 05  STA $05FB
```

then the walk, one entry per frame, and the unit:

```
05F3  BC B1 09  LDY lfo_index,X / INC lfo_index,X
05F9  B9 DF 09  LDA table,Y / CMP #$FF          ; $FF wraps the index to 0
060E  BD 7A 09  LDA note,X / ASL / TAY
0613  38 B9 A7 08 F9 A5 08   SEC / LDA freq+2,Y / SBC freq,Y   ; the interval
0622  4A 66 4D  LSR / ROR x4                    ; >> 4
0630  AC 86 09  LDY count / ... ADC ... DEY / BNE
0652  68 F0 2F 30 17   PLA / BEQ / BMI          ; the entry's own sign bit
```

so frame `i` writes `table[i] * count * (interval >> 4)` as an **absolute
offset from the note's frequency** — a position, not an accumulation. The LFO
index is per voice, free-running, and reset only by the `$FF` wrap: a new note
does not restart it.

Both files carry four tables, at the same four shapes:

| index | table | length | peak |
|---:|---|---:|---:|
| 0 | `0 1 0 -1` | 4 | 1 |
| 1 | `0 1 2 1 0 -1` | 6 | 2 |
| 2 | `0 1 2 1 0 -1 -2 -1` | 8 | 2 |
| 3 | `0 1 2 3 2 1 0 -1 -2 -1` | 10 | 3 |

All four are triangles. That is the whole reason this is expressible at all:
Goattracker's vibrato is a fixed triangle, and an arbitrary LFO shape could
only have been approximated by its envelope. Nothing in the mapping assumes it
— `_read_lfo_table` measures length and peak and would happily encode the
envelope of a shape that was not a triangle — but the fidelity of the result
rests on it, and it is worth saying that the corpus, not the design, is what
makes it hold.

#### The target: simulate `gplay.c`, do not read its constants

Matching a period needs Goattracker's period, and § 7.ee took it from the code
in front of it: a counter compared against `ltable & $7f`, so a half-period of
`cmp / 2` calls. Running `gplay.c:795-801` instead —

```c
if ((vibtime < 0x80) && (vibtime > cmpvalue)) vibtime ^= 0xff;
vibtime += 0x02;
if (vibtime & 0x01) freq -= speed; else freq += speed;
```

— for every `cmpvalue` from 0 to 23 gives something else. `vibtime` walks the
even values up to `cmpvalue`, XORs into the odd half, walks that down, and
flips back, so:

```
peak-to-peak = (cmpvalue + 2) * speed
full period  = 2 * (cmpvalue + 2) calls
```

The **half-period is `cmp + 2` calls, not `cmp / 2`** — a factor of about four
at the small values both engines produce, and at `cmpvalue` 0 the `+ 2` is the
entire period. § 7.ee's `cmp = 2 × bound × multiplier` therefore emits an
oscillation at roughly half the player's rate for all 49 files that carry the
classic form *and* expose the byte to the reader. Its *excursion* is
unaffected, and § 7.ll works out exactly why the two errors cancelled there.
The correction is `cmp = bound × multiplier − 2`, made in v0.5.129;
`rshift` is unchanged. `tests/test_table_vibrato.py` pins the simulation so the
next derivation starts from the fact rather than the constant.

> **The transferable lesson:** a mapping has two sides, and the side you did
> not write is the one you are most likely to have read rather than measured.
> Four lines of C, run rather than read, moved the period by 4x.

#### The mapping

Period first, from the table's length in frames against Goattracker's calls:

```
cmp = length × multiplier / 2 − 2
```

then the excursion, equating the two amplitudes:

```
(cmp + 2) / 2 × (interval >> rshift)  ==  peak × count × (interval >> 4)
```

The interval cancels out of both sides entirely — which is the same reason the
classic form maps cleanly, and it is worth noticing that it holds here for a
*better* reason: this player takes `freq(note+1) − freq(note)`, the semitone
**above** the note, which is exactly what Goattracker's note-relative speed
computes. The classic players take the one below, about 6% of a semitone out.
Solving leaves

```
rshift = log2((cmp + 2) × 2**unit_shift / (2 × peak × count))
```

rounded to the nearest integer *in log space*, because the depth is a shift and
only powers of two are reachable, so the error to minimise is multiplicative.
`unit_shift` is counted off the `LSR A / ROR zp` pairs the player executes
rather than hard-coded at 4: it is the 16 in that expression, and a player
shifting by 3 would bend twice as far for the same byte.

Five of Hollywood or Bust's seven vibrato records ask for a ratio that is
already a power of two; two round, the worse of them by a third.

#### What it moved

| at `-t 10` | before | after |
|---|---:|---:|
| Hollywood_or_Bust `bend` | 0.00x | **0.41x** |
| Chicken_Song | 0.79x at `-t 40` | see below |
| any other corpus file's bytes | — | unchanged (95-file differential hash) |

At `-t 40`, where both files reach their vibrato instruments, Hollywood or Bust
reads 0.00x → **0.58x** and Chicken Song 0.79x → **2.07x**. The overshoot is
**not** explained by the rounding above: Chicken's four reachable records ask
for per-frame travel ratios of 1.33, 1.6, 1.14 and 0.5. Nor is `bend` a clean
signal there — the file already read 0.79x with no vibrato emitted at all, so
its number mixes the new movement with a pre-existing drum-sweep contribution,
which Hollywood or Bust (0 moving frames before this) does not. Left open, and
named here rather than smoothed: the emission is gated by one detection
function and can be withdrawn from that file alone if a listening pass says it
should be.

#### Detection, and the rule it follows

Three shapes must all match — the parameter split, the table walk with its
`$FF` wrap, and the `LSR/ROR` chain — and the self-modifying pair must patch
two consecutive bytes, which is what pins the routine as the one it looks like.
The record offset is read out of the `LDA record,Y` operand rather than assumed
to be `+5`, and the number of tables comes from `hi_pointers − lo_pointers`
rather than from the four the corpus happens to have.

It is consulted **only where `_find_vibrato` found nothing** — the same rule
`find_relocation`, `find_init_writes` and the instrument-index shape follow. It
can rescue a file that vibrates not at all; it can never disturb one that
already reads. Across all 95 corpus files exactly two match, which a test
asserts by sweeping the corpus rather than by naming the two.

---



### 7.ll The vibrato half-period, corrected — and a fix its own report cannot judge

§ 7.kk found that Goattracker's vibrato half-period is `cmp + 2` calls and left
the classic mapping alone, on the grounds that changing it moves every file
carrying the format and so deserves its own measured commit. This is it.

#### What changed, and what deliberately did not

The player's counter steps by one per frame between 0 and `bound`
(Warhawk `$11FE-$121E`: `DEC ctr,X / BNE out` walking down, `INC ctr,X /
LDA bound,X / CMP ctr,X / BCS out` walking up), so its half-period is `bound`
frames. Goattracker's is `cmp + 2` calls, i.e. `(cmp + 2) / multiplier` frames.
Hence

```
cmp = bound × multiplier − 2          (was: 2 × bound × multiplier)
```

**`rshift` is unchanged, and the reason is worth recording.** The old
derivation equated the player's `(bound >> 1) × depth` with a Goattracker
*amplitude* of `(cmp / 2) × speed`. But the player's apply loop only ever
subtracts —

```
1251  BD C3 15  LDA ctr,X / 4A LSR / A8 TAY / 88 DEY / 30 16 BMI out
1257  38 AD 8E 15 ED 8C 15 ...        ; freq -= depth, counter/2 times
```

— so the note is the *top* of the swing and `(bound >> 1) × depth` is a
peak-to-peak, not an amplitude. Matching peak-to-peak against Goattracker's
`(cmp + 2) × speed`, with `cmp + 2 = bound × multiplier` from the period,
cancels `bound` entirely and leaves `speed = depth / (2 × multiplier)` — which
is `rshift = shift + 1 + log2(multiplier)`, the shipped value. **A period twice
too long and an excursion convention off by two had cancelled in the shift
exactly.** Only `cmp` was ever wrong, and a fitted correction that "fixed" both
would have doubled every file's vibrato depth.

#### Reach

49 of 95 files change bytes — every file whose vibrato-byte addressing the
reader recognises (56 carry the format; 7 reach the byte by an idiom
`_find_vibrato` does not match). Verified by holding everything else fixed and
hashing each conversion under the old and new mapping; the A/B's independently
computed set is the same 49. The speed-table *indices* are identical on both
sides, so nothing else in the file shifted.

#### What the report said, and why it is not the evidence

`FIDELITY.md` moved on 30 files, in `slides` and `bend` only. Every other
dimension is flat, and that is expected rather than a null result:
`melody`/`seq`/`pitch`/`retrig` read *which* notes are struck, and
`wave`/`adsr`/`pul`/`filt`/`cut` read registers vibrato never touches. **No
dimension in the report measures an oscillation rate at all**, so none of them
can adjudicate a period fix. The direction confirms it: 15 files moved toward
the original and 15 away, corpus mean `melody` unchanged at 76.7%, median
`bend` 0.505 → 0.488.

The movement that *did* appear is second-order, and identifying it is what
makes the flat table readable. At `-S1` Goattracker adds or subtracts `speed`
on **every** call, so total pitch travel is `speed × calls` and is
structurally independent of the period — `bend` should not have moved on a
multiplier-1 file at all. Eleven did, by a clean ×1.5. The dump says why
(One_on_One, voice 3):

| frame | old | new |
|---|---|---|
| 100 | `2354 (+ 0084)` | `2354 (+ 0084)` |
| 101 | `23D8 (+ 0084)` | `23D8 (+ 0084)` |
| 102 | `245C (C#5 BD)` | `2354 (- 0084)` |

The old half-period was long enough that the pitch drifted **past a semitone**
before reversing, and siddump then re-read the movement as a *note change*
rather than a bend. `_bend_travel` takes siddump's own `(+ xxxx)` lines by
design (§ 7.hh), so those frames vanished from both `slides` and `bend`. The
correction turns the oscillation around sooner, siddump keeps calling it a
bend, and the counts rise — which is evidence the change *landed*, not evidence
it is *right*.

What makes it right is the derivation above plus the four lines of `gplay.c`
run rather than read. That is the whole of the case, and the report is silent
on it.

> **The transferable lesson**, and this repo has now paid for it twice: a flat
> or noisy table has two readings — "this change reaches nothing" and "nothing
> here can see this change". Distinguishing them is not optional and it is not
> a judgement call. `--baseline` hashes the converted bytes, which settled
> reach at 49 files; the dimension registry names the registers each column
> reads, which settled visibility. Neither number came from looking at the
> means.



### 7.mm The wavetable's own clock: an off-by-one and the arpeggio's missing slot

§ 7.bb divided every per-frame rate by the `-S` multiplier and left three
residuals. Two of them were the same mistake seen from different sides, and
both are closed here: the converter was encoding wavetable *time* against the
constant that names a delay entry rather than against the loop that consumes
one.

#### A delay entry is current for `value + 1` calls, not `value`

`gcommon.h:56-57` names the range (`WAVEDELAY $01 .. WAVELASTDELAY $0F`) and
says nothing about duration. `gplay.c:697-704` is where the duration lives:

```c
else {                                  // wave <= WAVELASTDELAY: a delay
  if (cptr->wavetime != wave) { cptr->wavetime++; goto TICKNEFFECTS; }
}
cptr->wavetime = 0;
cptr->ptr[WTBL]++;
```

The entry is left on the call where `wavetime == wave`, and `wavetime` was
incremented on each of the `wave` calls before it — so the entry is current
for `wave + 1` calls. Entry 0 is itself one call, so a frame of `m` calls asks
entry 1 for a delay of `m - 2`, not `m - 1`.

`_wave_delay` returned `m - 1` from v0.5.82 to v0.5.130, so **every multispeed
file's attack transient lasted `m + 1` calls** — 1.5 frames at `-S2`, where 22
of the corpus's 37 multispeed files sit, and 1.33 at `-S3`. The helper is now
`_wave_hold_byte`, and one extra call is written as the attack waveform again
rather than a delay of zero: `$00` is the editor's empty marker and 0 is not a
delay value. Where `tail == wave` that byte is already what entry 1 held, so
at `-S2` the correction is often the *removal* of a delay rather than a
different one.

There is a second consequence worth stating because it bit the fix: **a delay
entry's right side is read**, on its final call — `note` is loaded at the top
of `WAVEEXEC` and the fall-through reaches the note block. A hold entry placed
after a relative note therefore has to carry `$80` ("no note change") or it
drags the note back.

#### The arpeggio: five slots for six, until the jump target paid

The player alternates the note every frame (`$13CD`). Goattracker's wavetable
advances one entry per call, so the two-entry alternation § 7.ee emits swaps
twice a frame at `-S2` and three times at `-S3`. § 7.bb recorded this as
unfixable: attack + 2 × (note, hold) + jump is six entries and an instrument
has five.

The jump entry is the way out. `ptr[WTBL]++` happens first and the `$FF` test
is applied to the *new* entry, so **a jump costs no call** — and it can target
entry 0 as easily as entry 2. Looping through entry 0 makes the attack entry
double as the note half's first call:

```
entry 0   wave      right $00        the attack, and the base note
entry 1   hold      right $00        base note held to m calls
entry 2   tail      right $80-N      the arpeggio note
entry 3   hold      right $80        held to m calls, note unchanged
entry 4   $FF       right -> entry 0
```

`2m` calls a cycle, `m` per half, at every multiplier. It is sound only
because re-entering entry 0 rewrites the attack byte, which is a no-op exactly
when `tail == wave` — the two differ at most in the gate bit, and they are
equal in **all 45 corpus records that reach this branch**. Anything else stays
on the `-S1` shape rather than emitting a retrigger once per cycle.

#### Reach, and an instrument gap this made unmissable

The differential hash is exactly as it should be: **37 files change bytes, all
of them multiplier > 1; no multiplier-1 file changes and no multiplier > 1
file is missed.**

**Neither instrument in this repo can see the attack correction, and the two
fail for opposite reasons.** That is worth recording precisely, because a
reader looking only at the tables would conclude the change reaches nothing:

- **siddump samples the registers once per frame.** At `-S2` the removed call
  is the *interior* call of a frame; the value latched at the frame boundary
  is the same before and after. `wave` moved on **0 of 82** files.
- **`--equal-calls` resamples our side per call, but then drops the
  frame-aligned dimensions** — it compared `wave` on 45 files, and *none* of
  them has multiplier > 1. The 37 files the change touches are precisely the
  ones it cannot compare.

So the register dimensions are blind here by frame quantisation on one side
and by omission on the other. What would close it is one trace at a resolution
finer than a frame *on both sides* — `vicetrace.py`'s 312 samples per
rasterline-frame, still unwired.

What the report did show: 20 files move at frame sampling, almost all in
`slides`/`bend`; under `--equal-calls` **one** file moves. Corpus mean melody
76.70% → 76.68%, pitch 82.58% → 82.63%, `wave` and `adsr` identical to four
decimals. The single file the finer instrument can see —
Battle_of_Britain, melody 75% → 73%, pitch 50% → 43% — moved the *wrong* way,
and it is one file of 37 against a correction that both sides' source agrees
on. It is named here rather than averaged away.

> **The transferable lesson:** § 7.kk's was that the side you did not write is
> the one you read rather than measured. This is the same lesson one level
> down — the constant that *names* a mechanism and the loop that *runs* it are
> different sources, and only one of them is authoritative. Four lines of C
> moved the vibrato period by 4x; three lines moved every multispeed file's
> attack by a call.



### 7.nn A trace 312x finer, and the reduction that had to be measured first

Every register dimension in `FIDELITY.md` — `wave`, `adsr`, `pul`, `filt`,
`cut` — is computed from siddump, which samples the SID **once per frame**. A
value written and overwritten inside a frame is not in that trace at all, and
on a multiplier-`m` file the `m − 1` intermediate play calls leave no mark.
§ 7.mm's attack correction is the sharp case: it moves a waveform boundary by
one call, and `wave` moved on **0 of 82** files.

VICE's `dump` sound device writes the whole SID state on every rasterline —
**312 samples a PAL frame**. `vicetrace.py` has read it since v0.5.126. What
stopped it being wired in was not the parsing but a question nobody had
answered: the compare functions walk *frame-indexed* timelines, so the finer
trace has to be reduced, and the reduction is where the information is thrown
away.

#### The measurement that had to come first: the two sides are out of phase

Tracing Warhawk's original and our `-S2` conversion and asking, per rasterline,
where in the frame each side changes a register:

| side | busiest rasterlines |
|---|---|
| original | 9, 10, 18, 19, 8, 11 |
| ours (`-S2`, two calls) | 274, 279, 283, 126, 119, 284 |

The original's player runs near the top of the screen; our packed file runs
wherever `gt2reloc`'s CIA stub puts it. **So a rasterline-against-rasterline
comparison is impossible** — it would compare the original's post-write state
against our pre-write state for most of every frame and report the offset
rather than the music. A per-frame reduction is not a convenience here, it is
forced.

#### Four rules, and the property that decides between them

The offset above is inaudible: it is where in a frame the writes land, not
what is written. So the test is **stability under a shift of that offset**.
Shifting our side by 0–48 rasterlines and re-scoring, over eight files spanning
multipliers 1 to 6:

| rule | what it does | mean sd | worst range |
|---|---|---:|---:|
| `last` | the value at the frame boundary — **what siddump reports** | 0.18 | **2.64 pp** |
| `any` | agree if the two sides' value sets intersect | 0.09 | 1.67 pp |
| `majority` | the duration-weighted modal value | 0.02 | 0.09 pp |
| **`overlap`** | `sum_v min(share_a(v), share_b(v))` | **0.02** | **0.13 pp** |

Two results, and the first one was a surprise:

- **`last` — the rule the report has always used — is the least stable of the
  four.** It samples one instant, so a write that crosses the frame edge flips
  it outright. The expectation going in was the opposite: that `last` would be
  phase-free because both sides have written by the boundary. That is only
  true when nothing else moves afterwards, and on a multispeed file something
  usually does.
- **`any` is disqualified on level rather than on stability.** It reads
  Deep_Strike at **98.8%** where every other rule reads about 75%: with a
  carry-in slice from the previous frame in every histogram, two sides nearly
  always share *some* value.

`overlap` is stable *and* graded — a frame in which the two sides agree for
200 of 312 rasterlines scores 0.64, where `majority` scores 1.0 and `last`
scores 0. Delta shows the gap: `majority` 99.0% against `overlap` 89.2%, which
is a real minority disagreement that a hard vote discards. It is the default.

The counting dimensions cannot use a graded rule — a count needs one definite
value per frame — so they take the duration-weighted majority, which is the
stable one.

#### What is wired, and what it agrees with

`fidelity.py --vice` traces **both** sides with VICE and computes `wave`,
`adsr`, `pul`, `filt` and `cut` from the pair. Both sides, deliberately: the
original reads more gate edges under VICE than under siddump too, so tracing
only our side would trade one bias for another and make the two columns of
every count incomparable.

Validated against the siddump path on files that exercise each register:

| | siddump | `--vice` |
|---|---|---|
| Warhawk `wave` / `adsr` | 92.9% / 72.6% | 95% / 73% |
| Star_Paws `filt` | 493/498 | 491/496 |
| Star_Paws `cut` travel | 4026112/2079232 | 4016896/2074624 |
| Star_Paws `pul` | 42/1022 | 42/1018 |

Close enough to show the same music is being measured, different enough to
show the resolution is real. It is **not** the default: two emulator runs a
row at about 1.3x real time, against siddump's fraction of a second.

#### The corpus run, and the premise it half-refuted

95 rows, **0 failed traces**, re-run after the denominator fix below.
Corrected: `wave` 63.9% → **64.3%**, `adsr` 69.3% → **69.0%** — both essentially
flat, where the defective run had reported 64.7% and had folded a real
resolution effect together with an inflation bug into one number. Corpus-wide
mean absolute delta on `wave` is **1.09 pp** over 82 files: most files move by
less than a point, and the mean is still the least informative number here
because a handful carry the whole effect. Six files move by more than 4 pp,
`Human_Race` (+11.1) far out ahead of the rest — the one entry from the
original six-file sample that survives as a genuine anomaly rather than an
artefact of the denominator or the reduction rule.

Because `--vice` changes two things at once (a finer trace *and* a graded
rule), the per-file movement was decomposed by re-running the same files at
`--vice-reduce last`, which is the finer trace under siddump's own rule. **The
first version of that decomposition, published in v0.5.132, was wrong**, and
what it was wrong about is worth more than the table it produced.

#### A third effect was hiding inside the first: the denominator

`wave_compare` drops a frame where both sides select no waveform, so that a
voice silent in both cannot inflate the score. v0.5.131's `--vice` translated
that as "drop the frame when both whole histograms are silent" — which is not
the same rule. A frame in which one side flickered for a few rasterlines and
**both sides were silent at the boundary** then counted as a *full agreement*
rather than being dropped. That is exactly the inflation the original rule
exists to prevent.

Chasing it down began as a hunt for a fault in the harness — two instruments
disagreeing by ten points at `-S1`, where neither is undersampling, is a claim
about every register number this project has published. Traced on the same
file, siddump and VICE agree **100%** on the original and 99.8% on the packed
conversion, at a constant one-frame offset that cancels because `--vice`
compares VICE against VICE. The instruments were never in disagreement. The
gap was in `vice_register_compare`.

The fix is the graded form of the same rule: what leaves the denominator is
the **overlapping silent share**, `min(share_a(0), share_b(0))`, not the whole
frame. A frame both sides spend silent contributes weight 0; a frame one side
flickers through contributes 12/312 of a frame and agrees on none of it.

#### The decomposition, with all three separated

| file | siddump | resolution only | + rule | resolution | rule | denominator (defect) |
|---|---:|---:|---:|---:|---:|---:|
| Bangkok_Knights (`-S1`) | 2.3% | 2.3% | 2.3% | 0.0 | 0.0 | **+12.5** |
| Human_Race (`-S1`) | 70.1% | 81.1% | 81.2% | **+11.0** | +0.1 | 0.0 |
| IK_plus (`-S1`) | 40.0% | 40.1% | 40.2% | +0.1 | +0.1 | **+6.7** |
| Kings_of_the_Beach_intro (`-S5`) | 85.2% | 78.8% | 78.9% | −6.4 | +0.1 | 0.0 |
| Lightforce (`-S2`) | 72.3% | 84.9% | 78.5% | **+12.6** | −6.4 | 0.0 |
| Thing_on_a_Spring (`-S2`) | 81.1% | 92.2% | 86.7% | +11.1 | −5.6 | 0.0 |
| **mean abs** | | | | **6.9 pp** | **2.1 pp** | **3.2 pp** |

Resolution is still the largest term and the rule is still the smallest, so
the ordering v0.5.132 reported survives — but resolution was overstated at
10.1 pp because a defect worth 3.2 pp was being counted as part of it, and on
the two files where the defect dominated (Bangkok_Knights, IK_plus) the
resolution effect is **zero**. The two largest entries in the original table
were not measuring what the table said they were.

The premise this was built on still comes out only half right. `--vice` was
motivated by multispeed files, where siddump discards `m − 1` of every `m`
play calls, so the disagreement should have concentrated at high multipliers.
It does not: Human_Race and Bangkok_Knights are `-S1` files and the multiplier
trend is not monotone. But two of the three largest `-S1` movers turned out to
be the denominator defect rather than the trace, so the anomaly is smaller
than v0.5.132 claimed — Human_Race, at `-S1` and +11.0 pp of genuine
resolution, is what is left of it, and it is one file rather than a pattern.

> **The second transferable lesson, and the more expensive one:** v0.5.132
> published a decomposition that separated two effects and never asked whether
> there was a third. The check that found it was not subtle — run the new
> instrument under the old instrument's *rule* and see whether it reproduces
> the old number. It did not, on two files out of six. **When a new
> measurement disagrees with an old one, make the new one imitate the old one
> exactly before believing the difference is real.**

> **The transferable lesson:** the instrument's resolution and the
> instrument's *stability* are different properties, and this repo had been
> assuming the coarser one was at least the steadier. It is not. Before
> replacing a measurement, shift something that should not matter and check
> that the number does not move — the old rule failed that test and the
> replacement was chosen by it, not by argument.



### 7.oo The drum sweep: a structural dead end, not a bug — investigated and reverted

§ 7.ii read the drum's downward sweep as `W - 1` steps per note against the
one this converter emits, and called that a measured under-render. The
obvious next move is the jump-target trick § 7.mm gave the arpeggio: loop the
`WAVECMD_PORTADOWN` wavetable entry back onto itself, so it fires every call
instead of once, until the next note resets `ptr[WTBL]`. Implemented,
differential-hashed to exactly the 44 files that reach `_drum_entries`, and
directly verified on Bump_Set_Spike — VICE traces genuine repeated,
self-terminating falls (`117 → 116 → 115 → 114`, one high-byte step per
frame, matching the player's own rate). **It was reverted before commit.**

#### What the player has that `CMD_PORTADOWN` does not: a floor

Warhawk `$136D`'s `LDA freqhi,X / BEQ out` stops the sweep the instant the
shadow counter reaches 0 — the frequency freezes low rather than continuing
past it. `CMD_PORTADOWN` (`gplay.c:557-572`) is `cptr->freq -= speed` on an
unsigned 16-bit value with no clamp anywhere in the function. A loop that
outlives the distance to zero does not freeze — it wraps to a very high
frequency and keeps going, for as long as the loop keeps firing.

**This is not a theoretical risk.** Tracing all 44 affected files with
`--vice` (312 samples/frame, both sides already validated in § 7.nn) for a
falling run of two or more frames landing above `0xF000` with no gate
retrigger — the underflow signature, distinct from an ordinary new-note jump
— found **921 hits across 20 of the 44 files**, confirmed reproducible with
each file traced into its own isolated directory (the first pass shared one
workdir across the loop, which is exactly the contamination class this repo's
own tooling notes already warn about; a manual re-check of one hit did not
reproduce until the paths were isolated, which is what surfaced the risk and
was then confirmed real, not an artefact, once it was fixed).

**One of the twenty is `Commando.sid` — this project's byte-exact reference
fixture.** Read directly off the trace file, voice 0, gate held at `0x14`
throughout, no retrigger anywhere:

```
frame 567: freq   628 (0x0274)
frame 568: freq   372 (0x0174)
frame 569: freq   116 (0x0074)
frame 570: freq 65396 (0xFF74)   <- underflow
frame 571: freq 65140 (0xFE74)
frame 572: freq 64884 (0xFD74)
...continues falling, unbounded, for as long as the loop keeps firing
```

256 units removed every frame (the low byte `$74` never changes, confirming
the step), straight through zero and around the 16-bit space with nothing to
stop it. This note had been falling for 175 consecutive frames before it
wrapped — over three seconds — far longer than any note § 7.ii's three-file
sample called typical (lengths 2-9 ticks). Whatever this specific instrument
is (a sustained tone rather than a percussive hit, most likely, given the
duration), the drum bit is set on it and the player's own guard would have
frozen it near-silent; this encoding turns that into an audible screech for
the rest of the note.

#### Why no bound is provably safe

Goattracker's own frequency table (`gplay.c:9-21`) has its lowest legal note
at `0x0117` = **279**. The drum step at `-S1` is 256 (`DRUM_SPEED_PER_FRAME`,
scaled down at higher multipliers by `_drum_speed`, so this is the worst
case, not a special one). **279 − 256 = 23**: one step is the largest number
of unconditional repetitions that can never underflow, for *any* note the
instrument might be triggered on — which is exactly the one step this
converter already emits. A second static step would already risk it from the
table's lowest note; an unbounded loop risks it from anywhere, given enough
held time, as Commando's very ordinary starting frequency (~44800, nowhere
near the table floor) and unremarkable held duration (three seconds) just
demonstrated.

> **§ 7.tt corrects the paragraph above.** "Any note the instrument might be
> triggered on" is not the same question as "any note the format can
> express", and it is answerable from the finished patterns: measured across
> the corpus, *every* drum instrument's lowest played note clears two steps.
> The floor was never the binding constraint — the fixed five-entry
> wavetable layout was. A bounded second step ships as of v0.5.146.

Two structural facts close off the alternatives that would fix this properly:

- **`CMD_TONEPORTA`** does clamp — `gplay.c:574-585`'s glide-to-target stops
  exactly at `targetfreq` — but it is not one of the commands the
  wavetable's one-shot dispatch (`WAVEEXEC`'s `wave >= WAVECMD` switch,
  `gplay.c:522-572`) recognises. It is reachable only from a pattern's own
  effect column, set via `cptr->command = cptr->newcommand` at pattern-read
  time (`gplay.c:414`) — a different mechanism entirely, requiring the target
  note to be threaded through `patterns.py`'s row construction rather than
  `goatwriter.py`'s per-instrument wavetable, and knowledge (a floor note to
  glide toward) this function does not have.

  > **Wrong, and § 7.tt has the right reason.** `case CMD_TONEPORTA:` is at
  > `gplay.c:574` — *inside* the wavetable switch, four lines past the
  > `CMD_PORTADOWN` case this section cites. The switch was mis-bounded at
  > 572, the line where `CMD_PORTADOWN`'s own block happens to close; it
  > actually runs to ~692. The wavetable can execute `CMD_TONEPORTA`. What it
  > cannot do is aim it: the target is `freqtbl[cptr->note]`, and the
  > wavetable's note column sets `cptr->freq` and `cptr->lastnote` but
  > **never `cptr->note`** (`gplay.c:717-726`), which only pattern-read time
  > writes. So a wavetable `CMD_TONEPORTA` can only glide *toward* the note's
  > own pitch, never below it — and below it is exactly where the drum goes.
  > Same conclusion, different and checkable reason.
- **The wavetable format has no bounded-repeat primitive.** A jump is
  unconditional and permanent; there is no "loop N times then continue."
  Bounding the *iteration count* independent of the *entry count* is not
  expressible at all — only the entry count can be bounded, and the corpus's
  actual starting frequencies vary too widely (down toward the table's own
  floor, per Warhawk's guard existing at all) to pick a universal safe N
  above 1.

**Reverted rather than shipped with a caveat.** The reach was real (44
files), the trajectory shape was right (confirmed on Bump_Set_Spike), and it
still failed on the corpus's own reference fixture — which is exactly the
"never ship a fake success" case this repo's rules exist for. The under-render
§ 7.ii measured stands as documented, unresolved technical debt: closing it
needs either per-note information threaded into the wavetable build (which
`_wavetable_entries` does not have — one wavetable is shared by every
occurrence of the instrument, at every pitch, of every duration) or a pattern-
level `CMD_TONEPORTA` encoding, neither undertaken here.

> **Do not resurrect the jump-to-self loop for this without a floor.** The
> arpeggio's identical trick (§ 7.mm) is safe only because a relative-note
> wavetable entry *sets* `cptr->freq` from the frequency table every visit —
> it cannot drift. `CMD_PORTADOWN` has no such reset, which is the whole
> difference between the two cases and the reason one ships and the other
> does not.

### 7.pp Commando's rest section: a real defect on the flagship fixture, and a screen that overcounted it

None of the tooling in this project measures past the first ten seconds by
default. `--vice`, `--equal-calls`, `--diagnose` — every instrument built this
session inherits `fidelity.py`'s `-t 10`. The listening pass renders 30, and a
spectrogram of `Commando.h2g.wav` (§ *listen.py*, `python listen.py --files`)
showed why that gap matters: the original stays continuously busy for the
full 30 seconds, and the conversion turns into isolated sustained blocks with
an unmistakable silence gap around 16–20s. This is the project's own
byte-exact reference fixture, so it earned a full investigation rather than a
note.

#### The mechanism, confirmed at three independent levels

**Register-level, VICE-independent.** `run_siddump` on the packed `.sid`
shows all three voices going quiet in near-lockstep from **7.8–7.9s**,
recurring every **~5.2s** after — three voices pausing together is a
whole-song event, not three instruments each coincidentally sustaining a
note. Comparing frames 850–1100 against 1110–1360 (exactly one 260-frame
cycle apart) gives a **250/250 exact match** on voice 0's combined
frequency/waveform state — the strongest form of confirmation this project's
tooling can produce for a claim of "this is looping."

**Structural, from the converted track data itself.** Instrumenting
`h2g.convert.convert_tracks` for subtune 0 shows exactly why: voice 0's
orderlist is **64 entries**, voice 1's **63**, voice 2's **123**, each ending
in a `GT_ORDER_RESTART` marker. Reading the raw bytes at the track's own file
offset confirms it — the byte at voice 0's restart position is `0xFF`
(Hubbard's own "tune ended," version 0/1/3 dialect, `tracks.py:222-228`).
`--legal-restart` reads this correctly and does exactly what it is documented
to do: writes the restart-to-row-0 marker Goattracker's format requires,
because the format has no "stop." **The converter is not misreading
anything.** The orderlist really is 64–123 entries, and it really does end on
Hubbard's own marker.

**Ruled out: subtune mismatch.** This project's most common false-alarm class
(§ *fidelity.py --diagnose*, four prior corpus files) is the `.sid`'s own
init routine renumbering which subtune plays. `--diagnose` on Commando puts
this to rest — s0→o0 matches at **89%**, clean on the diagonal, s1→o1 at
100%, s2→o2 at 95%. Same piece, same subtune index, both sides. The
divergence is real, not a bookkeeping artifact.

**What the real player does at that boundary was not confirmed here — see
§7.qq, where it was.** The detector finds `track_selector: True` for
Commando's player — a genuine mechanism, but (contrary to the first
hypothesis here) not a *chaining* primitive: `detect.py:634-660` shows it
**rewrites `track_lo`/`track_hi`** to locate a subtune's own track table
through an extra indirection, the same pointers any player uses afterward.
It explains how the *right* table gets found (consistent with
`--diagnose`'s clean match), not what happens when that table runs out.

#### A wrong turn worth keeping in the record

Comparing h2g's early voice-0 output against the original's content at
7.2–14.88s found the *same riff* — `E-7, A-6, A-4×4, G-4, A-4×3, G-4, A-4,
E-7, A-6...` on both sides — and the first conclusion drawn from that was
**"not a bug, this is a legitimately repeating hook."** That conclusion was
wrong, caught only by extending the same comparison to the 15–22s window,
where the original introduces notes (E-5, F-5, B-4, G#3) absent from the
early riff entirely, while every voice keeps attacking continuously. The
riff match was real — the original does restate it early — but the
conclusion drawn from a partial window was premature. **A note-sequence
match over one section is evidence about that section, not about what comes
after it.**

#### The corpus-wide screen, and why its headline number does not survive verification

The structural check — every subtune-0 voice's orderlist length and whether
it ends in a restart — was run across all 95 corpus files. Reused directly
(not re-derived) because it had just been validated against Commando's own
confirmed 63/64/123:

| | |
|---|---:|
| files with *any* subtune-0 voice ending in a restart | 83 of 95 |
| files where *every* restarting voice is ≤150 entries (Commando's own ceiling was 123) | 55 of 95 |

55 of 95 sounds like a corpus-wide problem. **It is not one**, and the reason
is itself worth recording: orderlist entries measure the wrong thing.
Commando's patterns happen to be short, so 64 entries packs into ~5.2
seconds; nothing in the entry count says anything about how long each
referenced *pattern* runs, and that varies enormously across the corpus.

A candidate `track_selector` explanation was checked and did not hold:
27 of the 55 candidates have `track_selector: True` against a corpus-wide
base rate of 37/95 (39%) — 49% vs 39%, a weak enrichment, not a mechanism.
Most of the 55 have no track selector at all, so whatever produces the
*precondition* corpus-wide is not specifically tied to it.

#### Five files, stratified across the candidate range, verified by hand — zero repeats Commando

| file | restart pos | verdict |
|---|---:|---|
| Thanatos | 8 | Benign — stable pitch set on both sides |
| 5_Title_Tunes | 18 | **False positive** — h2g's own 30s trace never loops at all; its patterns run far longer than Commando's, so 18 entries covers well over 30 seconds |
| One_on_One_Jordan_vs_Bird | 47 | Benign — modest movement in one voice; the other two are stable bass/percussive parts, which is normal |
| BMX_Kidz | 60 | **False positive** — zero attacks in the first half is this file's own documented ~13s intro silence, not a loop artefact |
| Human_Race | 95 | **Correctly converted** — both sides cycle the same four-chord progression (G→F→D#→D→G); a fixed split point landed mid-cycle and flagged normal progression as new material. Voice 2 empty on both sides, confirming the detected 2-voice player |

Two of the five were caught by the *screening heuristic* being wrong, not the
conversion: BMX_Kidz's known intro silence and Human_Race's cycle length both
produce the same "new pitches after the split" signature Commando has,
for reasons that have nothing to do with a truncated track. **A screen
built to catch one confirmed case will re-find that case's own incidental
properties (a fixed time split, in both instances here) as if they were the
defect.** Distinguishing "the original has content the conversion can't
reach" from "my split point fell somewhere musically ordinary" needed the
full attack-sequence read every time; the heuristic only ever narrowed which
five got that read.

#### Where this leaves the corpus

Zero of five confirms nothing about the other fifty candidates — that is not
a large enough sample to clear them. It does mean the true rate is very
likely far below 55/95: the two mechanisms that would make a short orderlist
audible (a genuinely short pattern set, or an intro/cycle long enough to
outrun the trace window) both cut the *wrong* way for most of this corpus,
and the one file confirmed to have the problem was found by ear (or its
visual proxy), not by the structural screen. **This reads as Commando-
specific rather than a corpus-wide defect worth a structural fix campaign.**
Treat any other file's short orderlist as a candidate needing the same
by-hand check, not as evidence on its own.

> **The transferable lesson:** a cheap structural proxy (orderlist entries)
> and a cheap acoustic proxy (new pitches after a fixed split) each produced
> a large, alarming number, and each number was wrong for a knowable reason
> once checked against ground truth — the first because it does not know
> pattern length, the second because a fixed split point is blind to a
> piece's own natural cycle length. Neither failure was subtle once looked
> for. **Validate a screen against the one case you already understand before
> trusting it on the other ninety-four.**


### 7.qq The `$FF`/`$FE` boundary, read live: it loops, and h2g already had it right

§7.pp left one thing unconfirmed: what Commando's real player does when a
voice's track hits Hubbard's own end marker — loop, freeze, or chain to
another table. Running `Commando.sid` live (RetroDebugger, C64 core, PSID
loaded directly) and reading the 6502 at the point each voice's track byte is
fetched settles it. The read/dispatch, per voice (`X` = voice index), sits at
`$5086`-`$50AA`:

```
$5086  LDY $54EC,X        ; Y = this voice's own order-read position
$5089  LDA ($5D),Y        ; fetch the track byte at that position
$508B  CMP #$FF
$508D  BEQ $5099          ; -> LDA #$00 / STA $54EC,X (and two companions) / JMP $5086
$508F  CMP #$FE
$5091  BNE $50AA           ; (ordinary pattern number: fall through to $50AA)
$5093  JSR $5003          ; -> JMP $5F42 -> LDA #$C0 / STA $5519 / RTS
$5096  JMP $53A5
```

**`$FF` is a per-voice loop, nothing else.** `$5099` zeroes `$54EC,X` — this
voice's own read position — and jumps straight back to `$5086` to re-fetch
entry 0 of the *same* track. No other table is consulted, no pointer is
reloaded (`$5D`/`$5E`, this voice's track pointer, is untouched), no other
voice is involved. `--legal-restart`'s restart-to-0 marker is not a
Goattracker-side workaround for a gap in the source format — it is a literal
transcription of what the 6502 does.

**`$FE` is a different, non-looping event.** It does not touch `$54EC,X` at
all; it calls `$5F42`, which sets `$5519` to `$C0` (bit 7, tested by the
`BMI $5038` a few instructions earlier at `$5018` — a whole-tune "ended" flag,
not a per-voice one) and returns. `tracks.py:222-228`'s version 0/1/3 case
already encodes exactly this distinction — `$FF` → `[0xFF, 0x00]` (loop to
row 0), `$FE` → `[0xFF, 0xFD]` (the sentinel `legalise_restarts` treats as
"ended," not "loop") — decoded from the static byte patterns, before any of
this was run live. The dynamic read confirms the static one; there was
nothing to fix here.

**This also confirms the converted track data itself is faithful.**
`convert_tracks` on Commando's subtune 0 produces voice orderlists of 64, 63,
and 123 entries (matching §7.pp exactly), each independently ending in its
own `[0xFF, 0x00]` — i.e. each voice loops back to its *own* row 0 on its
*own* schedule, not a shared song-level restart. That independence is not an
artifact of the conversion; it is what `$54EC,X` being per-voice state (`X`
indexes voice 0/1/2 throughout the fetch/dispatch code above) makes true of
the original player as well.

**Checked next: does Goattracker's own engine force the three channels back
into lockstep, or let them drift the way the mechanism above implies it
should?** Reading `gplay.c`'s player loop settles this too.
`playroutine()`'s per-row loop (`gplay.c:304-342`) calls `sequencer(c, cptr)`
once per channel, `cptr` a distinct `CHN*` per channel with its own
`songptr`/`pattptr`/`pattnum`. `sequencer()` (`gplay.c:959-1007`) only
touches `cptr->songptr` — advancing to the next orderlist entry, or looping
it via the same `LOOPSONG` marker Goattracker's own export uses for
`--legal-restart` — when *that channel's own* `pattptr` has just hit
`ENDPATT` (`gplay.c:918-919`, set when the channel's current pattern runs
out). Nothing here reads or waits on another channel's state. **Goattracker
does not force the three orderlists into lockstep**; each channel's advance
is gated purely by that channel's own pattern length, exactly like the 6502
routine above gates each voice's advance purely by that voice's own
`$54EC,X`. The 64/63/123-entry independence confirmed structurally in §7.pp
is therefore preserved all the way through — from the source player, through
`convert_tracks`, through Goattracker's own playback — not collapsed at any
point in between.

### 7.rr Commando's silence gap, traced to source: `max_rows=128`, and the fix

**Traced next: the original at the same 16–20s window, against h2g's own
packed output.** Bucketing attacks per second over a 26s trace (both sides
packed/traced identically, `presets.json`'s own Commando options) settles
it immediately — the original stays in the 7–17 attacks/second range for
the entire 26s; h2g's own conversion matches that for the first ~8 seconds
(8–17/s) and then **collapses to 0–2/s for the remaining 18** — not a
different loop, not "the same riff forever," an actual near-total stop.
This is neither §7.qq's mechanism nor its pacing check — both checked out
faithful — so it is a third, independent defect, and it was found by
isolating it: §7.qq's own checks used `--legal-restart` alone; the
collapse only reproduces with `presets.json`'s full Commando options, so
an option, not the orderlist or the engine, was next.

#### The actual cause: `max_rows=128` has no headroom for an unterminated pattern

Bisecting `presets.json`'s option set against a healthy `max_rows=94`
baseline (every other flag on or off, one at a time, then in combination)
narrows the trigger to one setting: **`max_rows=128` alone**, together with
a trace window long enough to actually reach the affected pattern (`tempo`
`auto` gets there in 26s at Commando's real speed; the untuned default
tempo is slow enough that a 26s trace never reaches it, which is why an
earlier, narrower bisection pass missed it — an option can be *necessary to
observe* the defect without being its cause). A sweep of `max_rows` from 94
to 128 in single steps is unambiguous: 94, 100, 110, 120, 126, 127 all
produce the identical, fully healthy 100/105/108-attack trace; **128 alone**
produces the 36/32/36 collapse. Nothing about Commando's music changes
between 127 and 128 — the boundary is Goattracker's own.

`patterns._slice_pattern`'s docstring already named the mechanism, written
before this defect was ever observed: Goattracker's own loader
(`gsong.c`'s `clearpattern()`) pre-fills every pattern buffer with ENDPATT
from row 64 onward, and its length reader (`countpatternlengths()`)
**re-scans for that byte rather than trusting the file's stored length** —
so an unterminated slice's *true* length, at runtime, is wherever that
pre-fill starts. The docstring calls slicing at 94 safe "by luck: 94 > 64"
— there are 34 untouched, pre-cleared rows behind every 94-row slice for
the scan to land on. **`max_rows=128` is `MAX_PATTROWS` itself: a 128-row
slice fills the entire buffer, leaving zero pre-cleared rows behind it.**
The scan that would have safely stopped one row later at 94 instead runs
into whatever memory follows — which is why the trace stays musical for
~8 seconds (while patterns are comfortably under 128 rows) and only
collapses once playback reaches the one pattern in Commando's data long
enough to need a genuine 128-row slice (confirmed structurally: a 256-row
source pattern splits as `94+94+68` real rows at `max_rows=94`, safe on
both slices, but as `128+128+0` at `max_rows=128` — *two* zero-headroom
slices back to back, decoded via a temporary debug dump of `convert()`'s
own `tracks`/`patterns` and reverted, not inferred).

**This is not Commando-specific, and it is not about an exact multiple of
128 either** — any pattern anywhere in the corpus that reaches a full,
unterminated 128-row slice is exposed the same way, regardless of what
follows it, because the buffer overrun happens at that slice's own
boundary. `terminate_patterns=True` sidesteps it entirely (it bakes the
marker inside the declared length, which the buffer overrun then finds
immediately), but is off by default for the same byte-exactness reason
every other option here is.

**One honest gap in this account.** `tests/test_terminate_patterns.py`'s
own `_loaded_length` — a model of `gsong.c`'s `clearpattern()`, trusted by
this project since before this defect was found — pre-fills ENDPATT up to
row `MAX_PATTROWS` (128) *inclusive*, which predicts a 128-row unterminated
slice should be safe (the scan lands on row 128, still inside that model's
129-row buffer) — the opposite of what real `gt2reloc` + `siddump` measures.
The two are not necessarily describing the same code: `clearpattern()` is
the *interactive editor's* loader, and `gt2reloc` packs patterns through its
own RLE packer (`greloc.c`'s `packpattern()`) into a standalone player,
which is not shown here to share the editor's flat, pre-filled array at
all. **Which buffer the real defect lives in was not re-derived from
`greloc.c` this pass** — what stands in its place is a live measurement
against the actual shipped toolchain (`gt2reloc` + `siddump`, the same
pair `fidelity.py` traces every file with), which is the pair that has to
agree for a fix to matter here regardless of which C struct explains it:
the option sweep (94-127 healthy, 128 alone collapses) and the corpus scan
below are both taken from that toolchain directly, not from the model.

#### The corpus-wide check: every file that picked `max_rows=128` is exposed

`presets.json` picked `max_rows=128` for **52 of the 95 corpus files** —
the optimizer's own preference, not an edge case, presumably because a
shorter orderlist scores well on a metric that has never traced past ten
seconds. Converting each of those 52 with its own preset options (a
temporary debug dump of `convert()`'s `new_patterns`, added and reverted
the same way as the single-file check above) and counting patterns that
are exactly 128 rows with a non-`ENDPATT` final byte finds **all 52
exposed, zero exceptions** — from 2 affected patterns (BMX_Kidz, of 13
total) to 77 (`W_A_R`, of 156). This is not a rare corner this converter
occasionally hits; it is the **default outcome** of picking `max_rows=128`
on real Hubbard pattern lengths, which apparently reach or exceed 128 rows
routinely. Every one of these 52 files' current `presets.json` entry is
liable to the same silent, several-second-scale playback collapse
Commando's was — at an unknown point in each file, wherever its own first
full 128-row slice falls, which the ≤10s fidelity metric that chose the
option would never have seen either.

#### The fix: never emit a real, unterminated 128-row slice

`_slice_pattern` now shaves one row off its chunk length specifically when
`terminate` is false and the caller's `max_len` is exactly `GT_MAX_ROWS * 4`
— i.e. only reachable at `max_rows == 128`, since both CLI and
`convert_patterns` already clamp `max_rows` to `1..GT_MAX_ROWS`. Every slice
this produces is now ≤127 real rows unless explicitly terminated, matching
the one case the sweep above already showed was safe. No other `max_rows`
value's chunking changes: the shave is gated on hitting 128 specifically,
not on being close to it.

**Validated against the real toolchain, not the model this pass could not
reconcile.** Re-running the exact 52-file corpus scan finds **zero**
exposed patterns (was 52 of 52). Commando's own live trace — the same
`gt2reloc` + `siddump` pair used throughout this section — goes from
36/32/36 attacks over 26s to **100/105/108**, against the original's
101/106/109: the collapse is gone, not merely relocated. The full test
suite (665 tests) passes unchanged, including the byte-exact `Commando.sng`
fixture, which uses `max_rows=94` and is untouched by a change gated on
`max_rows==128`.

**A second file, and an honest miss.** `W_A_R.sid` had the corpus's worst
count (77 of 156 patterns) and its default subtune references 65 of them,
several within the first few orderlist entries — the strongest candidate
in the corpus for reproducing Commando's before/after gap a second time.
Traced 30s (subtune 0, its own `multiplier=4`) against the pre-fix
`patterns.py` (restored from git for the comparison, then put back) and
the fixed one: **the two traces are frame-for-frame identical** —
29/25/58 attacks either way, tracking the original's 28/20/58 closely with
no silent stretch on *either* side. So on this file's default subtune, the
structural defect (confirmed present, 65 hits) did not translate into an
audible difference within 30 real seconds. Read together with Commando,
this says the defect's audible cost is not uniform: whatever byte a
runaway read lands on next differs file to file and pattern to pattern,
and evidently was already harmless enough here, at least within the traced
window, that the fix's value on this file rests on the structural
guarantee (no read ever runs past a known-safe boundary again) rather than
on a second demonstrated collapse. The other 7 subtunes' 12 remaining
hits, and W_A_R's own subtune 0 past 30s, were not traced.

### 7.ss Closing the loop: with the silence gap fixed, does Commando still diverge?

§7.pp opened on a spectrogram showing the original "continuously busy for
the full 30 seconds" against h2g's conversion turning into "isolated
sustained blocks with an unmistakable silence gap." §7.rr found and fixed
the silence gap's cause. What it did not check is whether that was the
*whole* story — §7.pp's own "wrong turn" section had flagged that past
15–22s the original plays notes (`E-5`, `F-5`, `B-4`, `G#3`) absent from
h2g's early riff, which read at the time as a second, separate, unresolved
question about content, not just about the silence.

Re-tracing both sides 30s against the fixed build and diffing each
voice's full note sequence (not just counts, which already matched
exactly — 111/120/125 both sides) settles it: **voice 0 and voice 2 are a
perfect `difflib` match, ratio 1.000, across the entire 30 seconds** —
every one of §7.pp's "new" notes is there, in the same order, at
essentially the same frames. The melodic divergence that opened this
whole investigation is gone; it was never a second defect, it was this
one, seen from a different angle (the spectrogram and the note-window
comparison were both looking straight at the same underlying content that
the silence gap had truncated or displaced).

**Voice 1 is not a perfect match (ratio 0.600), and does not need to be.**
The mismatch is one recurring shape — the original plays four retriggered
`B-5`s where h2g plays four retriggered `G#7`s, at a fixed, regular
interval throughout the piece, both sides always four hits — and the
waveform events around each block show the original briefly reaching
Goattracker's noise waveform (`128`) where h2g's does not. This is voice
1's drum part, and this exact shape is §7.ii/§7.oo's already-documented,
already-investigated, deliberately-unfixed limitation (the drum sweep's
under-render, whose only known safe fix was reverted for lacking a floor)
— not a new defect this pass found. What changed the note value read
here rather than the timbre is a detail neither §7.ii nor §7.oo needed to
resolve, since both already treat this instrument class as a documented,
bounded gap rather than a bug to chase.

**Net result: the investigation that opened at §7.pp is closed.** The
silence gap is fixed and validated (§7.rr); the melodic content that
motivated the "wrong turn" write-up now matches the original exactly on
both unaffected voices; the one remaining voice-1 difference is not new
information, it is this file's existing, named, out-of-scope drum
limitation showing up in a finer-grained comparison than the one that
first found it.

### 7.tt The drum sweep, half-closed: two steps bounded by proof rather than by luck

§ 7.ii measured the drum as an under-render — the player sweeps for `W - 1`
frames where this converter emitted one step — and § 7.oo tried the obvious
loop, found it wrapped, and reverted it as a "structural dead end." Re-reading
the player found **both of § 7.oo's stated blockers were wrong**, and one real
one it never named.

#### What § 7.oo got right

The no-bounded-repeat claim is correct, and worth affirming because everything
else here depends on it. A wavetable entry is a command *or* a delay, never
both: `gplay.c:715-724` runs the delay branch as the `else` of
`wave > WAVELASTDELAY`, and after either branch `cptr->ptr[WTBL]++` advances
**unconditionally**. So a command entry fires exactly once and cannot be held,
delayed or repeated. N steps costs N entries — there is no "repeat this one N
times."

#### Blocker 1, wrong: `CMD_TONEPORTA` *is* reachable from a wavetable

§ 7.oo bounded the wavetable's command switch at `gplay.c:572` and concluded
`CMD_TONEPORTA` sits outside it. 572 is where the `CMD_PORTADOWN` *case* closes;
the switch runs on to ~692, and `case CMD_TONEPORTA:` is at **574**, four lines
later. The wavetable can execute it.

That does not rescue the drum, for a reason § 7.oo never reached: TONEPORTA's
target is `freqtbl[cptr->note]`, and **the wavetable cannot move `cptr->note`.**
Its note column writes `cptr->freq` and `cptr->lastnote` and leaves `cptr->note`
alone (`gplay.c:717-726`); only pattern-read time sets it (`gplay.c:350`). So a
wavetable TONEPORTA always glides *toward the note's own pitch* and clamps
there — it can fall *into* a note from above, but never below it, and below it
is where the drum sweep lives. Right conclusion, wrong reason, and the
difference matters: the wrong reason invites "just use TONEPORTA from the
wavetable," which now looks available and still is not the answer.

#### Blocker 2, wrong: the floor was never the binding constraint

§ 7.oo's arithmetic — Goattracker's lowest note is 279, the step is 256, so
`279 - 256 = 23` leaves room for exactly one step — is sound about *any note the
format can express*. But the clause that matters is its own: "any note the
instrument **might be triggered on**," and that is a property of the finished
patterns, which this converter is holding. Measured per instrument, over the
lowest note each is actually played at:

| | |
|---|---:|
| drum instruments played anywhere in the corpus | 192 |
| whose lowest played note clears **two** 256-unit steps | **192** |
| whose lowest played note clears eight (the whole `W - 1` range) | 180 |
| median steps clearable | **16** |

Not one drum instrument in the corpus is played anywhere near the table floor;
the lowest is note index 18 (789 units, Spellbound). The floor is a real
hazard — it is what wrapped Commando under an *unbounded* loop — but it never
bounded a *fixed, small* count.

#### The real blocker, which § 7.oo never named: the five-entry layout

`WAVE_ENTRIES_PER_INSTR = 5`, and each instrument's wavetable pointer is
arithmetic on its index (`wave_ptr = i * 5 + wtable_start`), so an instrument
cannot have six entries without moving every later instrument's pointer. The
drum shape spends its five on attack, gate-off waveform, one sweep step, and
**two** stops — and the second stop is unreachable, because the first already
ends the table. So the layout had exactly one spare slot all along, and depth
past two needs variable-length wavetables against a 255-entry shared budget —
which for a drum-heavy file (Rasputin has 10 drum instruments, `W_A_R` 156
patterns' worth) cannot fund `W - 1` steps each regardless. **The under-render
is bounded by table space, not by the floor.**

#### What ships: a second step, where it is provably safe

`_drum_steps_safe` writes the second `CMD_PORTADOWN` into the dead slot only
where `_note_freq(lowest played note) - 2 * step >= 32`, with the step taken
from `_drum_speed(multiplier)` rather than the 256 constant (§ 7.bb's rule: a
rate read out of the player is per *frame*, the table applies it per *call*).
An unknown bound is treated as unsafe, so a caller that supplies nothing gets
exactly the bytes that shipped before — which is why every pre-existing test
still passes unchanged.

The bound comes from `patterns.min_played_notes`, and two properties of the
data make it harder than "the lowest note in the pattern":

- **An orderlist transpose shifts every note in the patterns after it**
  (`gplay.c:977-981`, `:927`), so the bound is the lowest note under the
  *lowest* transpose any position plays that pattern at.
- **The instrument column is sticky.** 15162 of the corpus's 61611 note rows
  name no instrument and inherit the last one named, possibly from a previous
  pattern. Rows before the first naming row in a pattern are therefore
  unattributable, and their note has to lower the bound for **every**
  instrument. Filing them under whichever instrument the pattern happens to
  name first is how a drum's own low note ends up on the wrong record and the
  sweep gets deepened past what it can take. That case is what leaves
  Last_V8's eight instruments at one step.

Reach: **195 instruments across 42 files** take the second step, 24 stay at
one. `Commando.sng` is untouched — the sweep needs GTS5 for its speed-table
index and the fixture is GTS2, so `_drum_speed_index` returns 0 there and no
sweep is written at all.

#### Verified three ways, including the one that killed § 7.oo

- **Analytically**, over all 83 convertible files: parsing every emitted
  `.sng` back, every instrument carrying two steps clears the arithmetic, and
  the stop is correctly at entry 4 in all 195. Zero violations.
- **Empirically, the § 7.oo test**: pack and trace each of the 42 changed
  files, scanning for a fall landing above `0xF000` with no gate retrigger —
  the wraparound signature. Run on both arms, **0 files gained a wraparound.**
  (Flash_Gordon shows 18 in *both* arms: pre-existing, not from this change,
  and worth a look on its own.)
- **In the trace, as a trajectory.** At `-S1` Bump_Set_Spike's single-step
  frames go 111 → 222: the sweep runs two frames where it ran one. At `-S2`
  every 128-unit frame becomes a 256-unit frame (Warhawk 15, Delta 25,
  Last_V8_C128 124, with the 128-unit count going to zero) — both entries
  fire inside one frame.

That last row is the session's surprise, and it is a stronger result than
"deeper". At `-S2` the old *single* entry swept 128 units per frame, because
`_drum_speed` correctly divides the per-call step by the multiplier but one
entry only ever fires on one call. So the shipped sweep ran at **half the
player's per-frame rate** on every multispeed file. Two entries at `-S2` travel
256 units in one frame — exactly the player's own `LDA freqhi,X / DEC freqhi,X`
rate. The fix is a depth increase at `-S1` and a *rate correction* at `-S2`.

#### What is still open, stated as a ratio

The depth available is two **calls**; the player's is `W - 1` **frames**. So
this closes `2 / (multiplier × (W - 1))` of the gap: exact for a 3-tick note at
`-S1`, a quarter of an 9-tick note at `-S1`, and progressively less as the
multiplier rises — `-S4` files (Flash_Gordon, `W_A_R`) get half a frame of
player-equivalent sweep from their two entries. Closing the rest needs the
variable-length wavetable and a budget policy described above, not a floor
argument.

**No dimension of `FIDELITY.md` can adjudicate any of this**, for two
independent reasons: `wave` compares waveform *class* and the class does not
change while the frequency falls, and siddump samples once per frame, so at
`-S2` and above the two steps land inside one sample and cannot be separated
at all. The reach above is a byte-hash and a register trajectory, not a score.

### 7.uu Flash_Gordon's wraparounds: the original wraps too, and the slide loses one call a row

§ 7.tt's wraparound scan reported 18 frequency wraps on Flash_Gordon in *both*
arms — pre-existing, so not the drum deepening's doing. Chasing them found two
things, and the first one corrects how that scan should be read at all.

#### The original wraps through zero on purpose

Tracing the original alongside the conversion, **the original wraps nine times
in 30 seconds** — and does it with a regularity that rules out accident:

```
ORIGINAL voice 0, frames 68-83
  68  freq 0x5918 (22808)          wf 0x41
  69  freq 0x5088 (20616)   -2192  wf 0x41
  ...              (a constant -2192 every frame)
  78  freq 0x0378 (  888)   -2192  wf 0x41
  79  freq 0xfae8 (64232)  +63344  wf 0x41   <- wraps through zero
  80  freq 0xf258 (62040)   -2192  wf 0x40   <- and keeps falling
  82  freq 0x49b8 (18872)          wf 0x41   <- next note resets it
```

Every one of the nine is the identical `0x0378 → 0xfae8`, on a strict 81-frame
cycle, with the three voices offset 18 frames from each other. Hubbard's player
sweeps the frequency down at a constant rate with no floor, lets it wrap, and
keeps going until the next note. It is a deliberate effect.

> **So a wraparound is not per se a converter defect**, and § 7.oo's scan —
> reused unchanged in § 7.tt — must not be read as a defect count. It was
> still the right test there, because it was used *differentially* (0 files
> gained one); the absolute number was never the claim. § 7.oo's own use of
> it was also sound: what it found on Commando was a wrap the original does
> not make. The distinction is "does the original wrap here too", and only
> tracing both sides answers it.

#### What is ours: the slide is delivered at 8/9 of its own encoded rate

The conversion sweeps the same place, and its *encoding is exactly right*. Our
per-call step is 548 and the file packs at `-S4`: `548 × 4 = 2192`, the
original's per-frame step to the unit. But the delivered per-frame movement
alternates:

```
OURS voice 0, frames 15-26
  15  freq 0x47a1 (18337)          <- note C-6
  16  freq 0x47a1 (18337)      +0    <- a whole frame with no movement at all
  17  freq 0x4135 (16693)   -1644    <- 3 calls x 548
  18  freq 0x38a5 (14501)   -2192    <- 4 calls x 548
  19  freq 0x3239 (12857)   -1644
  ...
  25  freq 0x0321 (  801)   -2192
  26  freq 0xfcb5 (64693)  +63892    <- wraps, like the original
```

`-1644` is three calls and `-2192` is four, so the question is only *how many
of each frame's four calls slide*. Over the window above, 32 of 36 call-slots
move the frequency — **exactly 8/9**. Flash_Gordon's subtune 0 carries
`CMD_SETTEMPO 8`, and gplay.c:325 makes a row last `tempo + 1` = **9 calls**.
One call per row does not slide, and 1644/2192 alternating is that single
missing call beating against the 4-call frame.

That the arithmetic lands exactly on `(tempo) / (tempo + 1)` is the evidence;
*which* call is skipped is not established here. The reading it fits is
gplay.c:510-513, where a call carrying a new note does `goto NEXTCHN` and so
runs neither `WAVEEXEC` nor the tick-N effect block, plus gplay.c:733 gating
that block on `cptr->tick` being non-zero. **But the file traced here is
gt2reloc's packed standalone player, not `gplay.c`** — the same caveat § 7.rr
records against the `clearpattern()` model — so this is a consistent mechanism,
not one read out of the binary that ran.

The zero-movement frame right after the note onset (frame 16) is a further,
separate loss on top of the per-row one, and is what takes the whole sweep to
roughly **80%** of the original's rate rather than 89%.

#### Why ours wraps twice where the original wraps once

Nothing to do with the step. The original's wrap at frame 79 is cut off by its
next note three frames later; ours holds the note far longer, so the frequency
keeps descending and crosses zero a second time (frame 59, `0x001d → 0xf9b1`).
Both wraps are the same single unguarded sweep — a note-length difference, not
a slide-rate one.

#### What this opens, and what it does not

The `8/9` is a property of the tempo, not of Flash_Gordon: **every slide in
every file loses `1/(tempo + 1)` of its movement**, which across the corpus's
tempos is a 6-25% shortfall on every pitch bend this converter emits. That is
a much broader claim than one file, and it is *not* established here — one
file's window is where it was measured. `bend` (travel, § 7.hh) is the
dimension that could see it, and checking it corpus-wide against `--baseline`
is the next step, not a conclusion.

Compensating by scaling the encoded step by `(tempo + 1) / tempo` is the
obvious candidate and is deliberately not done here: it would overshoot on any
row where the slide *does* run its full count, and § 7.oo is the standing
lesson about shipping an unverified rate change to the sweep path.

### 7.vv The slide deficit is corpus-wide: every pitch bend loses a call a row

§ 7.uu measured Flash_Gordon's slide delivering 8/9 of its own encoded
movement, matched that to `tempo + 1 = 9` calls per row, and explicitly
refused to generalise from one file's window. Generalising it properly
confirms it — but only after the first instrument built to do so failed its
own validation.

#### The prediction, and why it is readable off the file

`CMD_SETTEMPO`'s data value **is** the row length in calls (gplay.c:494
decrements a value ≥ 3, :325 makes a row last `tempo + 1` calls), so for each
file the traced subtune's own tempo row gives `rc` directly, and the predicted
delivery ceiling is `(rc − 1) / rc`. Measuring the *observed* ratio means
finding steady slide runs in the trace and dividing the frequency actually
travelled by the call-slots available: `moved / (frames × multiplier)`.

#### The first detector was wrong, and the known case is what caught it

A permissive run-finder (any monotone span, per-call step recovered by GCD)
produced a table that looked like a result and was not one:

| | first detector | validated detector |
|---|---:|---:|
| Flash_Gordon observed (hand-measured: **0.889**) | 0.823 | **0.893** |
| files reading *above* the ceiling | many (Samantha_Fox 0.902 vs 0.667) | 1 of 19, at 5 runs |

Reading above `(rc − 1) / rc` is impossible if one call per row cannot slide,
so those rows alone falsified the instrument rather than the model. The cause
was the span-finder counting vibrato, note ties and the drum sweep as slides,
and GCD then recovering a step smaller than the real one — which inflates
`moved / step` without limit. Tightening it (≥ 6 samples, ≥ 3 moving, at most
`multiplier` distinct step sizes, none more than `multiplier` steps) brings
Flash_Gordon to 0.893 against the hand figure's 0.889. **The corpus was not
run until that agreed** — § 7.pp's lesson, applied before the fact for once
rather than after.

#### The result

Restricted to files with enough steady slide runs to measure (19 of 83; 13 with
20 runs or more):

| | all 19 | ≥ 20 runs (13) |
|---|---:|---:|
| at or below the `(rc − 1)/rc` ceiling | 18 | **13 of 13** |
| within 5 points of it | 10 | 8 |
| mean predicted loss (`1/rc`) | 24.2% | 23.2% |
| **mean observed loss** | 35.3% | **28.7%** |
| mean (observed − predicted) | −0.111 | −0.055 |

**Every high-confidence file loses slide movement, and none exceeds the
ceiling** — the model's one falsifiable prediction, holding 13 for 13. The
observed loss runs about 5 points worse than tempo alone accounts for, which
is the second effect § 7.uu already saw directly on Flash_Gordon: a whole frame
with no movement at the note onset, on top of the per-row skipped call.

The magnitude is much larger than § 7.uu's guess of "6-25%". For `rc = 3` —
the most common tempo in the corpus — the ceiling alone discards **a third** of
every bend, and 8 of the 19 files measured sit at `rc = 3`.

#### The fix, and the coupling that stops it being a one-liner

Scaling each encoded step by `rc / (rc − 1)` is the obvious compensation, and
the measurement above licenses it in a way § 7.uu could not: the ceiling is
never exceeded, so raising the step cannot overshoot a row that was already
delivering in full. It is still not a one-liner, for a reason this session
created:

> **The drum sweep shares the speed table.** `_drum_speed_index` appends
> `_drum_speed(multiplier)` to the same `speed_table` the pattern portamentos
> index, and § 7.tt's `_drum_steps_safe` proves its no-underflow bound against
> that exact value. Scaling the table indiscriminately would inflate the drum
> step and silently invalidate the bound that keeps the second sweep step from
> wrapping. A fix has to scale the *pattern portamento* entries only, and
> `_drum_steps_safe` has to read whatever value its own entry ends up holding.

Not attempted here: it is a rate change to the slide path, which is where
§ 7.oo's standing lesson applies, and it wants its own `--baseline` A/B with
`bend` (travel, § 7.hh) as the dimension — the one column that can see step
size rather than counting events.

### 7.ww Compensating the lost call — and a report that reads the fix backwards

§ 7.vv measured the deficit and named the fix: raise each encoded portamento
step by `rc / (rc - 1)`, where `rc` is the row length in play calls. That
ships here. It is the first change in this document whose benefit **no
dimension of `FIDELITY.md` can show**, and two of them actively read it as a
regression, so the evidence below is deliberately not a score.

#### Where the scaling goes, and why that dissolves the coupling hazard

§ 7.vv warned that the drum sweep shares the speed table, so scaling the table
would inflate the drum step and invalidate § 7.tt's no-underflow bound.
Scaling **inside `build_speed_table`** avoids it entirely rather than working
around it: that function only ever sees pattern portamento commands
(`GT_SPEEDTABLE_COMMANDS` is `(1, 2, 3)` — up, down, tone-porta), and the
drum's entry is appended afterwards by `_drum_speed_index`, which *looks its
value up* and appends only if absent. `_drum_steps_safe` then reasons from
`_drum_speed(multiplier)` directly and never reads the table at all. Re-running
§ 7.tt's verification confirms it: **195 instruments carrying two steps, 0
safety violations**, identical to before this change.

The same placement is what keeps `Commando.sng` byte-exact — the GTS2 column
path (`scale_portamento_data`) is untouched, so the fixture cannot move.

#### One row length per file, and it is the largest

`rc` is a single number per file rather than per pattern, because per-pattern
is ambiguous exactly where it would matter: of the 18 corpus files carrying
several tempos, **17 play at least one pattern at two different ones**
(Warhawk 44 such patterns, Spellbound 24, Knucklebusters 19). The caller passes
`max(tempo values)`, which yields the *smallest* correction — under-delivering
a fast subtune rather than overshooting a slow one. For the **65 of 83 files
whose subtunes all share one tempo it is exact.**

Reach: **40 of 83 files change bytes.**

#### Validated against the one case with ground truth

§ 7.uu established Flash_Gordon's sweep from both sides, so it is the case
where "did this help" has an answer. Measuring the mean per-frame fall over
sustained descending runs, against the original's:

| | units/frame | ratio to original |
|---|---:|---:|
| original | 1038.8 | — |
| compensation off | 902.3 | 0.869 |
| **compensation on** | **954.1** | **0.918** |

Toward parity by five points, and the residual is the design's own
under-correction rather than a surprise: Flash_Gordon's tempi are
`[8, 9, 10, 16]`, so it receives `16/15` where its traced subtune's `rc = 9`
wants `9/8`.

#### The report reads it backwards, for the reason this repo already documented

`--baseline` against the pre-fix run moves five files, and the two dimensions
that move most point the wrong way:

| file | slides | bend |
|---|---|---|
| Flash_Gordon | 772 → 763 | 0.88 → **0.81** |
| International_Karate | 124 → 120 | 0.66 → **0.61** |

Both are the confound CLAUDE.md already records against v0.5.83's slide fix: a
*larger* step is more likely to cross a semitone, so siddump prints the
movement as a **note change** rather than a bend — and `bend` excludes ties by
construction (§ 7.ii), while `slides` counts printed slide events. Making each
step bigger therefore *removes* movement from both numerators while the actual
register travel rises. The travel table above is measured off the raw frequency
timeline, which cannot be reclassified.

> **This is the third time a step-size change has been misread by a count or a
> travel figure derived from siddump's own classification.** The rule stands
> and needs restating: for a change to a step *size*, read the register
> timeline directly. `bend` is a travel measure, which is why § 7.hh preferred
> it to `slides` — but it is travel *as siddump chose to print it*, and that
> choice depends on the step size being measured.

#### What did not move, and what that turned up instead

34 of the 40 files whose bytes changed moved no printed number. Sampling 13 of
them on raw travel found the compensation changed the trace on only two, and
inspecting the emitted tables explains part of it and leaves part open:

- **Some files carry no pattern portamento at all.** Mozart's and After_8's
  entire speed tables are values ≥ `$8000` — Goattracker's note-relative form,
  i.e. vibrato entries appended by `goatwriter`. Nothing for this fix to scale,
  and correctly their bytes did not change either.
- **Rikky's table scaled exactly as intended (90 → 120, `4/3`) and its travel
  did not move at all.** Not explained here. Its slides may fall outside the
  20 s window, or adjacent to note onsets where the travel filter excludes
  them. Recorded as unexplained rather than attributed.

The sampling also appeared to turn up something larger than the deficit this
section fixes: on several files our conversion's within-note pitch travel
looked like a small fraction of the original's — Rikky 0.06, Powerplay_Hockey
0.03, Rock_Tells_the_Tale 0.02, After_8 0.01.

> **Retracted — see § 7.xx.** Those figures counted note changes as pitch
> travel: a median 98.3% of the measured "travel" was siddump ties, which
> excluding `attack_frames` does not remove. Corrected, After_8 is **2.506**,
> not 0.014 — the sign was wrong, not only the size. What survives is
> § 7.dd's known gap, and only on the files whose vibrato is undetected.

#### Shipped on the mechanism, not on a score

The measured mechanism (§ 7.vv, 13 of 13 files at or below the ceiling), an
arithmetic correction exact for 65 of 83 files, a targeted validation on the
one case with ground truth, and an unchanged drum bound. Not a fidelity
improvement anyone can currently print — and stated that way rather than
dressed up, because the two columns that did move say the opposite.

Left open: per-pattern `rc` for the 18 multi-tempo files (Flash_Gordon would go
from `16/15` to `9/8` on its traced subtune), which needs the table keyed by
scaled step rather than raw value and an overflow guard the current
no-overflow guarantee does not cover.

### 7.xx The pitch-travel gap: 98% of it was melody, and the rest is § 7.dd

§ 7.ww closed by naming a "more promising lead" than the lost-call deficit:
several conversions whose within-note pitch travel was a few percent of the
original's (Rikky 0.06, Powerplay_Hockey 0.03, Rock_Tells_the_Tale 0.02,
After_8 0.01). **That lead was a measurement artifact, and this section
retracts it.**

#### What the measure was actually counting

Summing `|Δfreq|` per frame while excluding note *onsets* is not the same as
measuring modulation, because a note change does not need an onset. siddump
prints an untriggered note change as a **tie**, and a tie moves the frequency
register by a musical interval — far more than any vibrato. Excluding
`attack_frames` alone leaves every one of them in the sum.

Re-measuring with `tie_frames` excluded as well: **a median 98.3% of the
original's measured "pitch travel" was note changes.** The four files quoted
above:

| file | ratio, ties counted | ratio, ties excluded |
|---|---:|---:|
| Rikky | 0.064 | 0.405 |
| Powerplay_Hockey | 0.031 | 0.079 |
| Rock_Tells_the_Tale | 0.018 | 0.079 |
| **After_8** | **0.014** | **2.506** |

After_8 does not have 1% of the original's within-note movement; it has two and
a half times as much. The sign of that finding was wrong, not just its
magnitude.

#### With the tie removed, the real split appears — and it is § 7.dd's

The corrected measure divides the corpus almost exactly along whether
`detect` found the player's vibrato at all:

| | files | median ratio | under 0.20 |
|---|---:|---:|---:|
| vibrato **detected** | 47 | **0.968** | 7 |
| vibrato **not** detected | 28 | **0.233** | 13 |

Where the vibrato is read, within-note pitch travel is at **parity** — 0.968,
which is as close as this project has come to saying a dimension is simply
right. Where it is not read, the median conversion carries **less than a
quarter** of the original's within-note movement.

So there is no new mystery here. This is § 7.dd's documented gap — "a third of
the corpus bends nothing, because the vibrato was never written" — now
*quantified*: on the 28 files whose vibrato addressing no signature matches,
roughly three quarters of the pitch movement is missing, and on the 47 where it
matches there is essentially nothing left to win. The fix is widening the
vibrato signatures per dialect, which is 6502 work per player, not a rate or an
encoding change.

**The overshoot column is not readable and is not a finding.** Ratios explode
on small denominators — Star_Paws shows 141x against an original travel of
1043 units over 20 seconds, which is a rounding artifact wearing a percentage.
Any use of these ratios needs an absolute floor first.

> **Third consecutive section in which a register-trace measure failed on
> note-versus-modulation classification**: § 7.vv's first slide detector
> counted ties and vibrato as slides; § 7.ww found `bend` and `slides`
> inverting a step-size change because siddump reprints a large step as a note;
> and this one counted ties as travel. The common failure is treating
> "excludes note onsets" as "excludes notes". It does not — an untriggered
> note change is still a note change, and it is the single largest term in any
> `|Δfreq|` sum.

### 7.yy Widening the vibrato: one file rescued, and a premise that did not survive

§ 7.xx ended by pointing at the 28 files whose vibrato `detect` does not find,
"where there's measurably ~77% of the pitch movement to recover". Investigating
that recovered **one** file, and established that the premise behind the other
thirty does not hold up. Both halves are the result.

#### Where the files actually stand

Partitioning the 83 convertible files by which stage of detection fails:

| | files |
|---|---:|
| vibrato found, offset resolved | 49 |
| the table-driven LFO form (§ 7.kk) | 2 |
| matches `VIBRATO_SHAPE`, offset **not** resolved | **1** (I, Ball) |
| matches the depth co-signature but not the split | 0 |
| matches no vibrato shape at all | 31 |

The docstring's long-standing "the other 7 reach the byte by some addressing
this does not recognise" is now one file, not seven — earlier work closed the
rest without the count being restated.

#### The one real rescue: a relocating player names its table somewhere else

I, Ball copies `$9000-$9FFF` to `$E000` at init, and its vibrato reads
`$E710` — the relocated address. `_find_vibrato` compared that against the
instrument table's *load-space* address `$970B`, got an offset of 20485,
failed the stride check, and returned None. Resolving the operand through
`sid.to_offset` instead — which already exists for exactly this, and consults
the relocation only when the plain formula lands outside the file — gives
`0x78E - 0x789 = 5`, the same `+5` as all 49 others.

For any address the plain formula resolves,
`to_offset(a) - instr_start` is algebraically the subtraction it replaced, so
**no other file can move**, and the census confirms it: 50 files now, every one
at `+5`. Five of I, Ball's eighteen records carry a non-zero vibrato byte, so
the change is not cosmetic.

**No instrument available here can show its effect, and that is worth stating
plainly.** I, Ball's original has **zero** within-note pitch travel over the
traced window once ties are excluded, and is melody-dominated with them
included — so both readings of § 7.xx's measure are blind to it. Shipped on
the address arithmetic, which is checkable, and on the `+5` agreeing with
every other file in the corpus.

#### The premise for the other thirty, and why it does not hold

§ 7.xx's "median 0.233" for the undetected group implied a uniform deficit.
Looked at per file, it is nothing of the sort:

- **Their originals barely move.** The largest within-note travel among the 31
  is W_A_R's 358,992 against 3.1M for Bump_Set_Spike and 5.5M for Proteus in
  the *detected* group — one to two orders of magnitude less. Three
  (5_Title_Tunes, Kings_of_the_Beach_ingame, Tarzan) have **exactly zero**.

  > **Overstated — the window was too short.** Re-measured over 60 s rather
  > than 20 s, the originals move considerably more (Devils_Galop 347,484,
  > One_Man_and_his_Droid 237,339, Monty_on_the_Run 200,465) and only *two*
  > sit at zero; Tarzan reaches 53,394. The gap between the groups is real but
  > much smaller than this claims. See § 7.zz's window note.
- **A third of them already overshoot.** Eleven of the 31 have a ratio above
  1 — Crazy_Comets 11.2, Commando 8.9, Thing_on_a_Spring 6.0,
  Confuzion 4.8, Battle_of_Britain 4.6. On those, *adding* vibrato moves away
  from the original, not toward it.
- **The static evidence is ambiguous, not confirming.** 30 of the 31 do
  contain the semitone-depth idiom (`0A A8 38 B9 ?? ?? F9 ?? ??` — double the
  note index, index the frequency table, subtract the neighbour). That looks
  like a vibrato depth calculation, but the slide code computes a semitone the
  same way, so its presence does not establish that a vibrato routine exists.
  It is a lead, not a finding.

And the measure cannot break the tie, for the reason § 7.xx already
established in a different guise: the original's *large* pitch steps get
printed as note changes and dropped from a ties-excluded sum, while ours, being
smaller, are printed as bends and kept. The same asymmetry that made ties look
like travel now makes a deep original effect look like no effect at all.

> **What a real widening needs**, and did not get here: reading the 6502 of a
> specific player in the `no_shape` group and establishing whether a vibrato
> routine exists at all, before any signature is written. RetroDebugger makes
> that tractable (§ 7.qq), one player at a time. What must *not* happen is
> generalising from "30 of 31 contain a semitone calculation" to "30 files are
> missing their vibrato" — that is the same shape of inference as § 7.pp's
> 55-of-95 screen and § 7.xx's retracted lead.

### 7.zz Reading one of them: the same vibrato, stored in zero page

Taking § 7.yy's own advice and reading a single `no_shape` player found the
routine immediately — and it is not a new one. W_A_R was the pick because it
has the most to gain: the largest within-note travel among the 31 (358,992)
against a conversion producing **zero**.

Its parameter split, at file `+0x0242`:

```
W_A_R       B9 53 E9  LDA $E953,Y     ; the vibrato byte, record+5
            D0 03     BNE on
            4C 8E E6  JMP past        ; zero -> no vibrato
            48        PHA
            29 78     AND #$78        ; the bound...
            4A 4A 4A  LSR A x3        ; ...>> 3
            95 D3     STA $D3,X       ; <-- zero page,X
            68        PLA
            29 07     AND #$07        ; the shift
            8D FE E8  STA $E8FE

canonical   48 29 78 4A 4A 4A 9D ?? ?? 68 29 07 8D ?? ??
```

The whole difference is `STA $D3,X` where the shape expects `STA abs,X` — one
addressing mode, one byte shorter, and the pattern misses. Everything the
mapping depends on is identical: the same `$78`/`$07` masks, the same PHA/PLA
split, the same `LDA record+5,Y` feeding it (`$E953 - $E94E = 5`).

Scanning the corpus for the store variants gives a small, closed set:

| bound store / shift store | files |
|---|---:|
| `STA abs,X` / `STA abs` (canonical) | 56 |
| `STA zp,X` / `STA abs` | 2 (Tarzan, W_A_R) |
| `STA zp,X` / `STA zp` | 3 (Mega_Apocalypse, Samantha_Fox, Spellbound) |
| `STA abs,X` / `STA zp` | 0 |

So this is **one routine in three addressing dialects**, and adding the two
zero-page forms takes detection from 50 files to **55**, every one of them
still answering `+5`. The shapes are tried canonical-first, so no file that
already read correctly can match anything new.

#### What it bought, measured per file rather than claimed

All five carry real vibrato data (6 to 22 non-zero bytes each) and all five
emit it. Measured over **60 seconds**:

| file | original | ours before | ours after | | |
|---|---:|---:|---:|---:|---|
| W_A_R | 421,340 | 19,137 | **207,045** | 0.045 → 0.491 | toward |
| Tarzan | 53,394 | 8,908 | **58,868** | 0.167 → 1.103 | toward |
| Mega_Apocalypse | 199,903 | 0 | 9,584 | 0.000 → 0.048 | toward |
| Samantha_Fox | 234,006 | 47,222 | 48,256 | 0.202 → 0.206 | toward |
| Spellbound | 122,256 | 518,980 | 550,725 | 4.245 → 4.505 | **away** |

**Four of five move toward the original.** W_A_R gains the most in absolute
terms; Tarzan lands at 1.103, essentially parity.

> **This table was first taken over 20 seconds and said something materially
> different** — one win, *two* files flat, and Tarzan recorded as "the original
> does not move" because its original shows zero within-note travel that early.
> All three readings were artifacts of the window. A 20 s trace is not long
> enough to reach the content of these files: Tarzan's original goes from 0 to
> 53,394 between 20 s and 60 s, and Mega_Apocalypse's conversion from 0 to
> 9,584. The flat entries were guessed at as "instruments not played in the
> window", which was the right guess, but measuring is not guessing. **Use 60 s
> for anything of this kind** — `fidelity.py`'s own `-t 10` default is tuned to
> a different question (note-attack agreement, which saturates early) and is
> far too short for one about a sustained effect.

**Spellbound still moves away** — further at 60 s (4.25x → 4.51x) than the 20 s
window suggested. It was already overshooting by four times before this change.

Spellbound is not a reason to withhold the dialect. The player demonstrably
contains the routine and reads the byte at `+5`; declining to detect it would
be deliberately mis-reading a player to flatter a metric that § 7.xx already
showed is unreliable in exactly this direction (the original's larger steps
get printed as note changes and dropped, ours kept). Whatever makes Spellbound
overshoot is a separate defect, and it was overshooting by 2x before this.

#### The 26 that remain, measured properly

With the same 60 s window, the group is no longer the flat "nothing to win"
picture § 7.yy drew: 15 of the 26 sit under the original, 9 over, and only 2
have an original that does not move at all. **Seven produce literally zero
within-note travel against an original that does:**

| file | original | ours |
|---|---:|---:|
| One_Man_and_his_Droid | 237,339 | **0** |
| Ninja | 52,468 | **0** |
| Rasputin | 37,108 | **0** |
| Commodore_64_Music_Examples | 28,516 | **0** |
| Phantoms_of_the_Asteroid | 23,857 | **0** |
| Human_Race | 7,248 | **0** |
| Master_of_Magic | 53,505 | 5,120 |

That is a target list with a property the § 7.yy analysis could not offer: a
conversion emitting *no* within-note movement cannot be overshooting, so the
"adding vibrato would make it worse" objection does not apply to any of them.
The nine that overshoot (Battle_of_Britain 11.1x, Confuzion 9.4x,
Gerry_the_Germ 6.5x, Thing_on_a_Spring 4.6x, Crazy_Comets 4.1x,
Commando 2.7x) remain a separate question, and a live one — something is
generating movement the originals do not have.

Next player to read is One_Man_and_his_Droid, on the same grounds W_A_R was
picked: the largest original travel in the group against a conversion
producing nothing. It has no `AND #$78` anywhere, so if it has a vibrato the
parameter split is a different one, not another store dialect.

### 7.aaa A second dialect, fully decoded: the global-triangle vibrato

One_Man_and_his_Droid was the next player read, on § 7.zz's grounds — the
largest original within-note travel among the remaining 26 (237,339 over 60 s)
against a conversion emitting **zero**. It has no `AND #$78` anywhere, so if it
had a vibrato it would not be another store dialect. It has one, and it is a
genuinely different encoding.

#### The routine, at `$11A0`

```
11A0  8C 0F 15  STY $150F
      B9 8F 15  LDA $158F,Y   ; record+7 -> $151A
      B9 8E 15  LDA $158E,Y   ; record+6 -> $1501
      B9 8D 15  LDA $158D,Y   ; record+5 -> $1500
      F0 6F     BEQ past      ; +5 zero -> no vibrato        (the enable test)
      AD 1C 15  LDA $151C     ; the global LFO counter
      29 07     AND #$07
      C9 04     CMP #$04
      90 02     BCC +2
      49 07     EOR #$07      ; -> 0,1,2,3,3,2,1,0           (the phase)
      8D 06 15  STA $1506
      BD F5 14  LDA $14F5,X
      0A A8     ASL A / TAY
      38        SEC
      B9 24 14  LDA freqtbl+2,Y
      F9 22 14  SBC freqtbl,Y                                (the semitone)
      8D 02 15  STA $1502
      B9 25 14  LDA freqtbl+3,Y
      F9 23 14  SBC freqtbl+1,Y
11C8  4A        LSR A         ; \
      6E 02 15  ROR $1502     ;  } shift the interval right
      CE 00 15  DEC $1500     ;  } (record+5 + 1) times       (the depth)
      10 F7     BPL $11C8     ; /
      8D 03 15  STA $1503
      B9 22 14  LDA freqtbl,Y     ; the note's own frequency
      8D 04 15  STA $1504
      B9 23 14  LDA freqtbl+1,Y
      8D 05 15  STA $1505
      BD EF 14  LDA $14EF,X
      29 1F     AND #$1F
      C9 08     CMP #$08
      90 1C     BCC out       ; only once the voice counter reaches 8  (the gate)
      AC 06 15  LDY $1506
11FE  88        DEY
      30 16     BMI out
      18        CLC
      AD 04 15  LDA $1504 / ADC $1502 / STA $1504
      AD 05 15  LDA $1505 / ADC $1503 / STA $1505   ; add the step, phase times
      4C FE 11  JMP $11FE
out:  AC E5 14  LDY $14E5,X
      AD 04 15  LDA $1504 / STA $D400,Y
      AD 05 15  LDA $1505 / STA $D401,Y
```

So the whole effect is

    frequency = note + phase x (semitone_at_this_note >> (record+5 + 1))

with `phase` the folded triangle `0,1,2,3,3,2,1,0`. Like the canonical form
(§ 7.ll) the apply loop **only ever adds** — the oscillation is one-sided.

#### What makes it a different dialect, not a variant

| | canonical (§ 7.ee) | this one |
|---|---|---|
| enable | `record+5` non-zero | `record+5` non-zero (same) |
| amplitude | `(byte & $78) >> 3`, per instrument | fixed `0..3`, from the global triangle |
| depth shift | `byte & $07` | the **whole** byte, as a shift count |
| period | per instrument, via the bound | **fixed**: 8 play calls |
| gate | none | per-voice counter `$14EF,X & $1F` must reach 8 |

The period is fixed because `$151C` is incremented at **`$1012`, the play
routine's own entry point** — unconditionally, once per call — and only three
bits of it are used. Eight calls per cycle, whatever the tune's tempo.

Reading `record+5` through the canonical mapping would be actively wrong here,
not merely lossy: the six instruments that carry a vibrato all hold **2**,
which the canonical split reads as bound `0` — no amplitude at all — and shift
`2`. That is exactly the "an under-read, never a wrong one" line the detector
holds, and it is why this needs its own signature rather than a widened one.

#### Not implemented, deliberately

The decode is complete enough to build on, and building on it is a larger
change than a shape: it needs a new `Detection` field, its own writer path, and
a mapping onto Goattracker's vibrato whose amplitude and period are *not* the
two the canonical mapping takes. § 7.ll is the standing warning — the canonical
mapping shipped for many versions with a doubled period and a halved amplitude
that cancelled, and the error was only visible once one of them was corrected
alone. A fixed 8-call period and a `0..3` triangle amplitude want their own
derivation against `gplay.c:795-801`, simulated rather than read off, and their
own before/after over a 60 s window.

#### It is not one file's dialect — it is twenty-five of them

The other zero-output files were read next, on the principle that knowing
whether a writer path serves one file or many should come before building it.
Searching for the routine as a single contiguous 41-byte shape — the triangle
fold through the shift loop, wildcarding only the operands —

```
29 07 C9 04 90 02 49 07 8D ?? ?? BD ?? ?? 0A A8 38
B9 ?? ?? F9 ?? ?? 8D ?? ?? B9 ?? ?? F9 ?? ?? 4A 6E ?? ?? CE ?? ?? 10 F7
```

matches **exactly 25 files, every one of them currently undetected, and no file
that detection already reads**. That is a clean partition, not an overlap: the
signature cannot disturb a single file that works today. It covers all seven of
§ 7.zz's zero-output targets and every remaining `no_shape` file except
Kings_of_the_Beach_ingame.

The enable fetch resolves to **`record+5` in all 25, unanimously**, and the
sequence feeding it is byte-for-byte identical across files down to the branch
displacement:

```
One_Man_and_his_Droid  B9 8D 15  8D 00 15  F0 6F  AD 1C 15  29 07 C9 04 90 02 49 07
Last_V8                B9 A6 85  8D 19 85  F0 6F  AD 35 85  29 07 C9 04 90 02 49 07
Human_Race             B9 E8 0D  8D C1 0D  F0 6F  AD E2 0D  29 07 C9 04 90 02 49 07
Ninja                  B9 74 CC  8D 39 CC  F0 6F  AD 58 CC  29 07 C9 04 90 02 49 07
```

Only the addresses differ. This is one routine assembled into twenty-five
tunes, which is why a single signature is the right shape for it rather than a
per-game fingerprint.

Most records hold a small shift count (1-4). Six files carry larger values
(Last_V8 81, Human_Race 119, Ninja 21 and 24, 5_Title_Tunes 16, Last_V8 15) and
**no player masks the byte** — so those really do shift the interval 16 or more
times, which drives the depth to zero. Those instruments simply have no
audible vibrato. That is consistent with the routine as read, not a
counter-example to it, but it does mean a mapping must handle "shift large
enough to vanish" rather than assuming 0-7.

**Reach if implemented: detection goes from 55 to 80 of 83 files.** That is the
single largest coverage change available in the converter, and it is the reason
to build the writer path rather than special-case One_Man_and_his_Droid.

Still not implemented here, for § 7.ll's reason: the mapping is the part this
project has got wrong before, and a fixed 8-call period with a `0..3` triangle
amplitude is not the pair `_classic_vibrato_entry` takes. What the decode now
gives an implementer is everything except that mapping — the signature, the
offset, the depth rule (`semitone >> (n+1)`, zero for large `n`), the period
(8 calls), and a 25-file corpus to A/B over 60 s.

### 7.bbb A listening session, and six metrics it overruled

Everything above this point was measured. This section is what happened when
the conversion was finally *played to a person* — Commando loaded into
GoatTracker, variants built to isolate one change each. It found two defects no
dimension of `FIDELITY.md` reports, corrected a diagnosis of mine, and settled
a question the metrics had answered backwards.

#### The click nobody could see: instrument 1

The report was "instrument 01 sounds off". GT instrument 1 is not converted
data at all — it is h2g's hardcoded Clear Voice placeholder, `AD $00 / SR $00`
with a wavetable of `$09` (gate + **testbit**). The readme is unambiguous about
what that makes: *"If all of them are zero just a very short click will be
heard"* (readme:741) and testbit *"silences sound and resets the oscillator"*
(readme:805).

**12 rows of Commando played it, and 1422 rows across 64 corpus files.** The
cause was `patterns.py:317`: an instrument change landing on a rest emitted a
fake `C-0` on instrument 1, on the assumption that Goattracker cannot latch an
instrument without a note. It can — `gplay.c:912-914` latches the column
whenever it is non-zero, *before and independently of* the note test, so a
`$BD` rest row carries the change and sounds nothing. Worse, `g_instrument`
already persists across rows, so the rest would have carried it anyway: the
block converted a silent latch into a click **and a retrigger of whatever was
sounding**. Fixed behind `--rest-instrument` (v0.5.159), gated because it moves
the byte-exact fixture — which is the anchor doing its job, since the VB6
original is what emitted the placeholder.

#### The drum sweep, and a diagnosis of mine that was wrong

The second report was "the tuning of instrument 3 is off". The frequency tables
were checked first and are correct — Commando's own table against Goattracker's
agrees to within one unit across the range, the 6-cent detune `find_freq_table`
already reports. So not a note-mapping fault, and consistent with the complaint
naming *one* instrument.

Instrument 3 is drum-flagged (`effect $05`) and so carries `_drum_entries`:
two `CMD_PORTADOWN` steps and then a stop. **512 units of fall, and then the
wavetable halts and the pitch simply sits there** for the rest of the note,
where the player keeps stepping until its own guard freezes it near zero. A
drum holding a definite wrong pitch is exactly what "out of tune" sounds like.

A variant with the sweep suppressed was **"much better"**, and I read that as
"the sweep does not belong on a tonal record" — reasoning from § 7.ii's finding
that the player's drum condition is a single cross-voice cell that no
per-instrument wavetable can encode. **That reading was wrong**, and the
correction came from the next listen: the instrument is a **tom** — a *pitched*
drum, tone and whoop together — and with the sweep restored it is *closer*, not
further. The record's own waveform confirms it (`$41` pulse, `$15` triangle on
its siblings; `_drum_entries` correctly uses the voice's waveform gate-released
rather than noise).

So the sweep belongs. What is wrong is only its depth, which is § 7.ii's
under-render exactly: the player falls 256 units a frame for `W-1` frames —
several octaves, down to inaudibility — against our two steps.

#### What this means for v0.5.146, and where the ceiling actually is

**v0.5.146 was directionally right and its metric said the opposite.** The
travel measure called the deepening "away from the original on 18 of 24 files";
the ear calls two steps closer than none. Deeper is better, and the shipped
change took the last slot available:

```
entry 0  attack waveform
entry 1  gate-off waveform
entry 2  CMD_PORTADOWN
entry 3  CMD_PORTADOWN     <- v0.5.146; the last free slot
entry 4  $FF stop          <- required: without it execution runs on
                              into the next instrument's wavetable
```

All five of `WAVE_ENTRIES_PER_INSTR` are in use, so **no further depth is
reachable in this layout at all** — confirming § 7.tt's identification of the
fixed five-entry allocation, not the underflow floor, as the real blocker.

A full whoop needs roughly eight steps, and both halves of that already exist:
the variable-length wavetable § 7.tt specified and deferred, and the
per-instrument safety bound `_drum_steps_safe` already computes (median 16
steps clearable, **180 of 194 instruments clear 8**). The one open design
question — whether the tom should fall to silence or land on a pitch — was put
to the listener and answered: **all the way to silence**, which is what the
player's own `freqhi == 0` guard produces.

> **Six measurements overruled in one session.** `slides` and `bend` inverted a
> step-size change (§ 7.ww); a travel metric counted ties as modulation
> (§ 7.xx); the same metric read the drum deepening and the triangle vibrato as
> regressions when both are improvements; a 20-second window reported three
> files as unaffected that a 60-second window shows moving (§ 7.zz); and the
> vibrato mapping my own harness rejected was called "very close" by ear. The
> pattern is not that the metrics are useless — several caught real defects
> nothing else would have. It is that **every one of them is blind to the
> difference between a wrong pitch and a right one at the wrong moment**, and
> that a listener resolves in seconds what a register trace argues about for
> versions. This project should have played its output to someone far earlier
> than it did.

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

The format delta looks tiny — different magic, plus a fourth (speed) table.
Instrument bytes 5 and 6 swap meaning between the two, but this converter emits
`0x00` for both, so nothing needs converting there.

**The speed table is not optional, and getting that wrong cost this converter
every pitch bend it emitted.** In a GTS2 file a portamento's data byte is a
packed value; in GTS3+ it is a **1-based index into the speed table**:

```c
speed = (ltable[STBL][cptr->cmddata-1] << 8) | rtable[STBL][cptr->cmddata-1];
                                                        // gplay.c:740
```

The GTS2 loader builds that table while reading — `makespeedtable(value,
MST_PORTAMENTO, 0) + 1` for every `$1`/`$2`/`$3` row (`gsong.c:311-321`) — so
the *same bytes* mean different things in the two formats. This writer emitted
an empty fourth table and left the raw values in the column, which is correct
GTS2 and silently inert GTS5: `cmddata-1` indexed a zero-length table, so every
slide resolved to speed 0.

Nothing detected it for a long time, because it is invisible from every
direction anyone was looking: the file parses, GoatTracker loads it, the
patterns show the commands in the editor, and the fidelity harness compares
*note attacks* — which a pitch bend does not produce. Measured over 10 s of 82
corpus files, the originals slide 22876 times and the conversions managed 7.
Writing the table (`patterns.build_speed_table`, the same quarter-of-the-16-bit-
step encoding GoatTracker uses) brings that to 1214 with no change to any
melody score, which is exactly the shape of a defect a metric cannot see.

> **Lesson:** when a format has two encodings of the same field, "we emit
> nothing there" is a decision, not a default. And a measurement that cannot
> distinguish "working" from "inert" will report both as fine.

> **Lesson worth more than the bug:** the target format had *two* loaders, and
> the one matching the era of the source tool was the broken one. Writing what
> the old tool wrote is not automatically the safe choice. Check whether your
> target still exercises that path.

Note the two-parallel-arrays layout used by both the wave and pulse tables
(`length, left[], right[]`) — that's Goattracker's native table shape, and it's
why `_write_wavetable` writes all left-column bytes for every instrument before
writing any right-column bytes.

### 7.ccc The drum sweep's other bound: the note's own length

§ 7.ii read the drum block and § 7.tt bounded its depth by the only thing the
converter then knew about a record — the lowest note it is played at, which
says how far a `CMD_PORTADOWN` chain may fall before it wraps. `_drum_max_steps`
said so in as many words: *"the safety bound and the musical target turn out to
be the same number."* They do not. They coincide only when the note is long
enough that the player's own guard never fires first, and on a short note it
fires long before the wrap.

The block has **two** exits, and § 7.tt only expressed one:

```
136D  LDA freqhi,X   / BEQ out      ; guard 1 -- the frequency reached zero
1372  LDA remaining,X / BEQ out     ; guard 2 -- the NOTE ended
```

Guard 1 is the pitch bound. Guard 2 is the note's duration, and nothing in the
converter looked at it. Commando's instrument 13 has room for thirteen steps by
pitch, was capped at eight by `DRUM_MAX_SWEEP_STEPS`, and gets **five** from the
player, because its note is four rows long.

#### The arithmetic, in the units the guards count in

`R` (`remaining,X`) decrements once per duration *unit*, not per frame — the
same fact § 7.ggg read out of the noise tick. With `W` the value it reloads to,
the block spends:

* `R == W`, one whole unit, on the `BCC` noise branch, which writes the
  frequency **without** decrementing it (so the sweep begins at the unit
  boundary, not at the note's first frame);
* `R` from `W-1` down to `1`, that is `W-1` units, sweeping once per frame;
* `R == 0`, the last unit, straight back out through guard 2, frozen wherever
  the sweep left it.

A converted row is one unit and an event lasts `wait + 1` of them, so a note of
`n` rows sweeps `(n - 2) * frames_per_row` frames. The first of those frames
writes the value it loaded (`LDA freqhi / DEC freqhi / STA`), so one fewer than
that many *decrements* reach the chip:

    steps = (n - 2) * frames_per_row - 1

Commando: `(4 - 2) * 3 - 1 = 5`. It is counted in play *calls* rather than
frames — `(n - 2) * row_calls - multiplier`, the same number at `-S1` — because
a row is not always a whole number of frames: W_A_R packs 9 calls at `-S4`, and
recovering `frames_per_row` by flooring 9/4 to 2 loses an eighth of its sweep.

#### Confirmed against the original, not argued

A 240 s `siddump` of Commando subtune 0, note onsets taken at gate rising edges
(`siddump.c:376-380` prints a bare note only there — taking them at waveform
changes splits every drum note in three and was the first thing to get wrong):

| note length | sweep | count |
|---|---|---|
| 12 frames = 4 rows | **5 steps**, `0DD0 0CD0 0BD0 0AD0 09D0 08D0` then frozen | 41 |
| 24 frames = 8 rows | 12 steps, `0DD0 → 01D0` | 7 |
| 36 frames = 12 rows | 12 steps, `0DD0 → 01D0` | 5 |

The 12-step rows are guard **1** — `0D` decremented until the byte would reach
zero — so both guards are visible in one trace, and the formula predicts the
crossover: 8 rows would give 17 steps by duration, and the pitch floor cuts it
to 12.

#### Which single number, and why the minimum is the wrong one

A wavetable holds one sweep for every note of an instrument, so whatever goes in
is wrong for every note of a different length. The first implementation took the
**minimum** duration, by analogy with `min_played_notes` — that one is a safety
bound and the minimum is the only safe reduction of it. This is not a safety
bound: the wrap is still handled by `_drum_max_steps`, which is applied as well.
It is an approximation of a distribution, and the reduction that minimises the
total error of one value against a distribution is its **median**.

The difference is not academic. Bump_Set_Spike's record 0 is played at 2, 4 and
6 rows in near-equal measure; its original sweeps 5 steps 221 times in 240 s;
the minimum would emit **0** and delete the sweep. Scored over the corpus as
play-weighted L1 error against each note's own true depth:

| reduction | total error (steps) | best-or-tied on |
|---|---:|---:|
| pitch bound alone (shipped) | 320070 | 34 of 122 records |
| minimum duration | 117806 | 97 |
| modal duration | 100102 | 120 |
| **median duration** | **99983** | **122** |

Weighted by how often the orderlists actually play each pattern, because the
median is a claim about what is heard — and `pack_repeats` encodes a run of `k`
as `$D0 + k - 1`, so a bare count of references understates a repeated pattern.

An occurrence whose hold rows run to the end of its pattern is **dropped**: what
that measures is the distance to a pattern boundary, not the note, and it is a
lower bound rather than a length. Counting them read Commando's instrument 13 as
two rows — there is a two-row pattern whose only row is such a note — and would
have taken its sweep away on the strength of a boundary.

#### End to end, on two files that use the block differently

Converted, packed with `gt2reloc`, traced. Voice 1 of Commando and voice 2 of
Bump_Set_Spike:

| | original | before | after |
|---|---|---|---|
| Commando, 12-frame note (×41) | 5 | 7 | **5** |
| Commando, 24/36-frame note (×12) | 12 | 8 | 5 |
| Bump_Set_Spike, 12-frame note (×246) | 5 | 7 | **5** |
| Bump_Set_Spike, 18-frame note (×4) | 11 | 8 | 5 |

The dominant case is now frame-for-frame identical to the original —
`0DD1 0DD1 0DD1 0DD1 0CD1 0BD1 0AD1 09D1 08D1 08D1 08D1 08D1` against the
original's `…0CD0 0BD0 0AD0 09D0 08D0 08D0 08D0 08D0`, the low byte differing by
the one unit Goattracker's frequency table rounds to. The long notes are the
trade the median makes, and they were already short at 8.

#### What the report can and cannot say

`FIDELITY.md` A/B over 95 files: **melody, seq, pitch, retrig, wave, noise,
adsr, nrun, tail, pul, pspan, filt and cut moved on zero files.** `slides` and
`bend` moved on 14 each — toward the original on 11 in log space, away on 2,
flat on 1 — and `vib` on one file, toward.

Read those two with § 7.ii in hand, because they are **not** a clean verdict on
this change. A 256-unit step at these frequencies is more than a semitone, so
siddump names the *original's* sweep frames as notes and `bend` excludes ties by
construction: the column counts our sweep and not theirs. Reducing our depth
therefore lowers our `bend` mechanically, which moves an over-1 file toward 1
and an under-1 file away from it — exactly the split observed (every file above
1.0 improved; the two below it, Bump_Set_Spike 0.43→0.36 and Deep_Strike
0.36→0.33, did not). Commando itself moves **no** column at all.

The evidence for this change is the frame comparison above, not the report. The
report's contribution is the negative one, and it is worth having: nothing else
moved anywhere.

> **The transferable lesson:** when one value has to stand for a distribution,
> the reduction is the **median** — the minimum is only right when the quantity
> is a safety bound, and this repo had one of each sitting in the same function.

---

### 7.zzz Two instruments for reading a conversion rather than scoring it

v0.5.215–216, written up late (v0.5.228). Every measurement in this project
reduces a conversion to a number. Two additions read it instead.

**`songview.py`** decodes a finished `.sng` to one self-contained HTML page:
orderlists with transposes resolved, wavetable entries with **cumulative call
timing**, instruments tagged with the effect bits recovered from the provenance
stamp `_write_instruments` already writes into the name (`NN:b5-b6-b7`, where
b7 is the player's own effect byte), and every pattern labelled with **all
three** of its identities — GoatTracker's hex number, the post-dedup index and
the Hubbard source. That last one retires a confusion that cost three debugging
attempts: a listener's "PATT.12" is pattern 18, the editor's pattern is
post-dedup, and the orderlist's leading transpose moves the pitches too.

It scores nothing, which is the point: unlike a new report column it cannot be
silently wrong in a way that changes a decision. Its parser is a deliberate
*second* reader of the format rather than a re-use of `build_sng`, and
`tests/test_songview.py` checks the two against each other and against the
byte-exact fixture — which is the only thing that makes the independence worth
having.

**`siddump -w<adr>[,…]`** (vendored `python/tools/siddump-rt`) dumps up to 16
arbitrary memory addresses once per displayed frame, from the same `mem` and at
the same point as the SID registers. It closes the one thing a register trace
cannot show: *which wavetable entry produced a register*. Printed verbatim every
frame and never elided to `..`, because a pointer that stops moving is exactly
the signal being looked for. Proved inert without the flag by rebuilding the
pre-patch source and diffing output on `Commando.sid -a0 -t5`: byte-identical.

Both were built in response to the question "would better live telemetry from
GoatTracker help?" The answer given, and the reason this pair exists instead:
the fidelity harness never runs GoatTracker. It packs with `gt2reloc` and traces
with `siddump`, so telemetry from the editor would measure a **different
execution path** than every number in this repo — the shape of the § 7.nn
mistake, where a finer instrument was believed before it had been shown to
reproduce the coarser one's answer.

§ 7.xxx is the first finding `songview.py` produced, and it produced it by
making one wavetable legible in one screen.

---

### 7.aaaa The `onset` dimension: seeing a mechanism a frame out of phase

v0.5.217, written up late (v0.5.228). Two emitters had, for as long as they had
existed, opened a note on the *effect* where the player writes the record's own
waveform first (§ 7.www). No column in the report could see it:

* **`wave`** averages per-frame waveform agreement over the whole window, so a
  wrong opening frame on a 43-note instrument is a rounding error against 3000
  frames. Trans-Atlantic's GT 3 read `noise tri pulse noise` against the
  original's `tri noise tri pulse` — and 63% either way.
* **`nrun`** compares the *lengths* of noise runs and is position-independent by
  design (§ 7.ddd), so a run that is right but starts a frame early scores 100%.

`fidelity.onset_shapes` records the waveform classes a note *opens* on, over
`ONSET_FRAMES = 4`, keyed by the ADSR pair latched one frame after the attack —
`instrmap.py`'s rule, because the attack frame can still hold a hard restart's
envelope. The key is `$D405/$D406` and the measured value is `$D404`, so the
attribution cannot contain the quantity attributed (the trap `release_tails`
fell into).

Three properties worth stating, because two of them were got wrong first:

1. **No startup-lag correction, and none is wanted.** Every other per-frame
   column compares frame *k* to frame *k* and must be shifted by the packed
   player's 3–8 frame latency (§ 7.ddd). This reads each side at its *own*
   attack frames, so the latency cancels by construction. The first wiring
   passed the lag in, which would have manufactured the phase error the column
   exists to detect.
2. **The direction is easy to write backwards, and was.** `ours == orig[1:]`
   means we never played the original's first frame — we are **early**.
3. **Reporting the direction is the point.** A wrong waveform and a right one a
   frame out have completely different fixes, and the report had never
   distinguished them. At introduction the corpus split was **32 early, 0
   late** — which is what a systematic emitter defect looks like and what noise
   does not.

---

### 7.bbbb The drum's first frame is a frame, not a call

v0.5.220, written up late (v0.5.228). After § 7.www fixed two emitters, 23
instruments still read early — and the split was **20 of 21 on multiplier-2
files against 3 of 45 single-speed ones**, which is not a distribution a
waveform error produces.

`_drum_entries` had opened on the record's own waveform correctly since
v0.5.172. Its docstring said so, and said the rest of it too:

> All five entries are in use either way, so unlike the plain shape this one has
> no slot for a delay: **its attack entry lasts one play call at every -S
> value**, and only the sweep *rate* is scaled by the multiplier.

That sentence reads as a description of a design and is a statement of the bug.
A wavetable steps once per **call**; one frame is `multiplier` calls. At `-S2`
the record's waveform therefore covered half of frame 0 and the noise tick
finished it — and siddump samples the registers at the end of a frame, so frame
0 read as the drum. It is the same defect § 7.www fixed, arriving by the other
route: not the effect placed on frame 0, but the waveform too short to keep it
off.

`_first_frame_lead(wave, multiplier, force=True)` is the extracted rule, shared
with `_two_stage_entries` — applying § 7.www's own lesson to itself. `force` is
there because `_drum_entries` has *always* emitted that entry, including for
records whose `+2` selects no waveform; gating it on `_first_frame_entry` would
delete it for those, which is a second and separately unmeasured change.

Corpus: onset matched **237 → 254**, early **23 → 14**, ten files up and none
down; Warhawk (the drum player of § 7.ii) 0% → 67%, Last_V8 and its C128
version → 100%. **melody, seq, adsr, nrun, tail and pitch moved on exactly zero
files** — the signature of a change that relocates a waveform *within* frame 0
and nothing else.

(The rule needed a fourth application, three sessions later: § 7.xxx.)

---

### 7.cccc An option no scorer could select

v0.5.221, written up late (v0.5.228). `presets.fidelity_better` decides which
of the invisible-to-structure options a song gets. Its docstring already
recorded that it is *deliberately* not scored on `wave`, because restoring a
1–4 frame transient moves `wave` the wrong way even when the transient is right
(§ 7.eee). The unintended consequence went unnoticed for as long as the option
existed: **`--two-stage` was unselectable**. Its attack strikes no new note,
sounds no new register and leaves `melody` untouched, so not one of the four
terms could see it. 45 corpus files sounded a transient at 109 instruments —
some 13,700 notes — and 42 of them had the option off.

The new term is `onset_frame_agreement`, and it is **graded per frame rather
than per instrument**. Both alternatives were checked before it was written:
whole-shape equality (`onset_agreement`, what the report prints) scores Sigma
Seven's `$0FFD` — no transient at all → a transient one frame too long — as
**zero**, and `onset_first_matched` cannot see it either because frame 0 already
agreed. Guarded by `keeps_notes` like every other term, and verified to decline
as well as accept.

> **The transferable lesson:** a scorer's blind spots are not symmetrical with
> the report's. A column deliberately excluded from scoring (here `wave`, for a
> good reason) removes every mechanism whose only visible effect is in that
> column — so an exclusion needs a replacement, not just a justification.

---

### 7.dddd Bit `$40` halves bit `$04`'s attack

v0.5.222, written up late (v0.5.228). This document carried, as an open
question, that "the relationship between that byte and the shared `$0FAA,X`
counter is not established". It is a halving. Measured across the corpus rather
than reasoned:

```
frames byte 2, effect $44  ->  1 frame   Sigma Seven $0FFD (124 onsets)
                                         Ricochet $0CE8 (77)
                                         Skate or Die $08D9 (300), $0AD8 (26)
frames byte 4, effect $44  ->  2 frames  Trans-Atlantic $0A99 (150)
                                         Sanxion $1909 (81), Pandora $0D99 (31)
                                         Auf Wiedersehen Monty $0AF9 (10)
                                         Knucklebusters $0AAD (4)
frames byte 2, effect $04  ->  2 frames  Sigma Seven $2B9D (61)
```

527 onsets on the first line and no counter-example there. **The second line is
what makes this a finding rather than a coincidence**: at `frames = 2` a halving
and a constant 1 are indistinguishable, and the constant was nearly shipped. The
`frames = 4` records measure 2, not 1.

The implied mechanism — an implication, not a reading of the 6502 — is that
`$40`'s handler decrements the same per-voice attack counter `$04`'s does, so
with both live it counts down twice per frame. One counter-example is recorded
rather than smoothed over: Lightforce's `$1FF9` is `$44` with a frames byte of 4
and measures **0** attack frames over 15 onsets. Unexplained; one record against
nine.

Effect, with `melody` unchanged everywhere: Sigma Seven onset 0.625 → **1.000**,
Sanxion 0.750 → 0.938, Trans-Atlantic 0.958 → 1.000, Skate or Die 0.500 →
0.625, Ricochet 0.650 → 0.700. **Ricochet and Skate or Die are the point** —
before the halving, forcing `--two-stage` on them moved their onsets not at all,
so § 7.cccc's criterion correctly declined them. The halving is what makes them
*selectable*.

---

### 7.eeee Two measurement bugs in the preset search

v0.5.223–225, written up late (v0.5.228). `presets.tune_by_fidelity` is a
**second implementation** of "convert, pack, trace both, compare", beside
`fidelity._measure`, and nothing pinned the two together. Both bugs were found
by refusing to commit a search result that tuned a file reading `melody 5%` and
asking why a 5% file was being tuned at all.

1. **No calibration.** `_measure` traces the original with
   `calibration(ft.detune)` where `sidfile.find_freq_table` reports its
   frequency table as sitting off the semitone grid; the search passed a hardcoded `0`, so siddump named every note of
   those files against the wrong table. Four corpus files are affected
   (Kings_of_the_Beach_intro, One_on_One_Jordan_vs_Bird, Powerplay_Hockey,
   Rock_Tells_the_Tale, all detune −0.696). One_on_One went 5% → **99%**.
2. **No subtune counterpart.** `_measure` searches a window of *our* subtunes
   and keeps the best match (`--search-subtunes`, default **3**); the search
   compared the original's N against our N. Action_Biker reads **6%** that way
   and **100%** the other — and on that 6% the search had "improved" it to 8%
   with `no_test_restart`. It now selects nothing there, which is correct.

The counterpart is resolved **once**, on the reference conversion, and reused
for every candidate: three traces per candidate would triple a search already
running 31 combinations a song, and none of the toggles changes an orderlist
length. That is an assumption and it is stated where it is made.

`tests/test_search_matches_report.py` pins the two harnesses together. Both
bug-catching tests were verified to **fail when their bug is reintroduced**,
which is the only way to know a regression test tests anything. The subtune test
asserts the *method* — that more than one of our subtunes is probed — rather
than the outcome, because which subtune fits legitimately moves; a guard test
checks the two named files still exhibit what they are there for, so a corpus
change cannot leave them passing vacuously.

**The corrected search** (v0.5.225) then gained 34 settings across 28 files and
lost 4. `--two-stage` reached 26 files where 3 had it, `--wave-program` 11 where
1 did. A/B at *fixed code*, so the comparison isolates the settings:

```
onset   62.1% -> 76.2%   +14.1pp   26 files up, 0 down
nrun    48.9% -> 51.7%    +2.8pp    2 up, 0 down
wave    74.0% -> 74.4%   +0.35pp   14 up, 12 down
melody, seq, adsr, tail, pitch      flat to within 0.02pp
```

> **The transferable lesson:** a second implementation of a measurement is a
> second place for the measurement to be wrong, and it will not announce itself
> — both of these read as *converter* defects on the file they touched. If a
> harness is duplicated for speed, pin the copy to the original with a test that
> fails when they diverge.

#### A third thing the search does, found by reading its own answer (v0.5.228)

Re-running the search after § 7.xxx and § 7.yyy changed exactly one entry —
Mega Apocalypse gaining `wave_program`, which is what § 7.yyy predicted. It also
gained `two_stage`, and that file's player sets no `effect_two_stage` at all:
the flag is **inert**, the conversion byte-identical without it.

Instrumenting the walk showed why, and it is not a bug in any one term:

```
combo  1  wave_program              wins: noise 0 -> 875 of 1444, onset .75 -> .93
combo  3  sfx_drum                  wins: oscillation .51 -> .55   (onset falls to .75)
combo  5  sfx_drum wave_program     wins: noise -> 1379, onset -> .93
combo  9  two_stage wave_program    wins: noise *pitch* 16824 -> 8412 (theirs 8912)
combo 13  two_stage sfx_drum wave_program   wins again on noise and oscillation
```

`fidelity_better` scores five one-sided questions and accepts a candidate that
improves **any** of them while keeping its notes. That is not a total order, so
the loop is a greedy *path* through the 31 combinations rather than a maximum,
and where it stops depends on the iteration order — combo 9 wins by moving the
noise pitch while giving back the oscillation combo 5 had gained.

The ordering is left alone: a single scalar over five incommensurable
dimensions would be a worse lie than a path through them. What is fixed is the
consequence — `prune_inert` re-converts once per selected flag and drops any
whose removal leaves the file identical. **A preset entry is a record of a
measured decision, and a flag that changes nothing was not one.** One entry in
the corpus was affected; the shipped conversion is unchanged, only its
description of itself.

---

### 7.xxx The drum block does not branch around the arpeggio

v0.5.226. International Karate was one of the two files the previous session
filed as **Class B** — instruments whose original changes waveform on the note's
second frame while the conversion holds the first, and which measured
*identically* under `--two-stage`, `--wave-program` and as shipped, so "some
other routine writes `$D404` on frame 1". Its `onset` was 40%, its `nrun` 0%,
and it played 437 noise frames against the original's 828.

`songview.py` — built for exactly this and, until now, never the thing that
answered a question — made the three failing instruments legible in one screen:

```
instr 1  '02:00-20-55'  adsr $0A0A     41 00   pulse, gate on
                                       40 00   pulse, gate off
                                       40 7B   pulse, gate off, note -5
                                       FF 02   jump to entry 2
```

An arpeggio, correctly derived, with no noise anywhere in it — against an
original measured as `pul noi noi pul` on every one of that instrument's 36
onsets. The record is `00 08 41 0A 0A 00 20 55`: `+7` is `$55`, which carries
**both** the drum bit `$01` and the arpeggio bit `$04`.

#### What the emitter believed, and what the player does

`_wavetable_entries` had this case gated since the effect bits were first read:

```python
if drum and effects and not arp:
    return _drum_entries(...)          # the tick, the gate-off, the sweep
if drum:
    left[1] = (wave & 0xFE) or WAVE_NOISE_GATEOFF
    # "The leading noise tick the original wrote is not in the player at
    #  all, and on the corpus it scores at chance."
```

The comment was written before v0.5.172 read the block, and the block says
otherwise. International Karate `$B15F` is Warhawk `$1366` byte for byte:

```
B15F  AD F7 B2   LDA effect
B162  29 01      AND #$01
B164  F0 35      BEQ $B19B          ; not a drum
B166  BD EB B2   LDA freqcnt,X / BEQ $B19B
B16B  BD C3 B2   LDA remaining,X / BEQ $B19B
B170  BD C6 B2   LDA duration,X / AND #$1F / SEC / SBC #$01
B178  DD C3 B2   CMP remaining,X
B17B  AC BC B2   LDY voice
B17E  90 10      BCC $B190          ; early in the note -> noise
B180  ...        DEC freqcnt,X / STA $D401,Y   ; else sweep the frequency
B189  BD C9 B2   LDA wave,X / AND #$FE / BNE $B198
B190  ...        LDA freqcnt,X / STA $D401,Y / LDA #$80
B198  99 04 D4   STA $D404,Y
B19B  EA         NOP
B19C  AD F7 B2   LDA effect         ; <- the ARPEGGIO's own bit test
B19F  29 04      AND #$04 / BEQ ...
```

Every exit of the drum block — the bit test, both guards, and the fall-through
after its own `STA $D404,Y` — lands on the `NOP` at `$B19B`, one byte before the
arpeggio's `LDA effect / AND #$04`. **There is no branch around it.** A record
setting both bits gets both blocks: the drum writes the waveform (noise while
the duration counter is still large), the arpeggio then overwrites the frequency
the drum swept. What five wavetable slots cannot hold is the drum's *sweep*
beside the arpeggio's pair — and the tick is not the sweep. It is two entries,
and variable-length wavetables (§ 7.oo) have room for them.

The fix is one line: such a record is routed through the `tick` path a
*sustaining* drum record already took. IK's three both-bits records go from
`pul pul pul pul` to `pul noi noi pul`, its `onset` from 40% to **100%**, and
its noise frames from 437 to 865 against the original's 828.

#### Two more defects the corpus surfaced on the way, both in the same shape

The change reached 62 of the 291 drum records the effect gate keeps, so the
corpus A/B did what one file could not.

**One: the length was a constant here and derived there.** With the tick emitted
at the hardcoded `NOISE_TICK_FRAMES = 2`, five files' `nrun` fell — Warhawk 67%
→ 29%, Proteus 33% → 20%, Spellbound, Formula_1_Simulator, Last_V8. They are
exactly the five whose speed gate derives a **one**-frame tick (§ 7.ggg), which
`_drum_entries` has read since v0.5.191 and this path never did.

**Two: the tick's own derivation read the wrong subtune.** Switching this path
to `_noise_tick_frames` fixed those five and broke Commando — `nrun` 67% → 0%,
`onset` 83% → 17%. The function took the **mode** of the gate over every
subtune, and the corpus rip of Commando carries nineteen: four songs at gates
3, 4, 3, 3 and fourteen one-frame sound effects. The effects outvote the music.
Its original measures a two-frame tick on all five of its pitched drum records
(371 runs of 2, and nothing else), and the mode says 1.

The subtune to read is the one the file itself starts on — `resolve_subtune`'s
rule, and for its reason: it is the subtune a player selects when the user
selects none, and therefore the one that is the tune. Settled by measurement
rather than by argument. Tracing each of the 35 corpus files whose player has
the drum routine and taking the modal noise-run length over the ADSR pairs of
its drum-flagged *pitched* records:

| derivation | exact | of the 28 files whose run is 1–3 frames |
|---|---:|---|
| mode over all subtunes | 24 | |
| **gate at `startSong`** | **27** | right everywhere the mode is, and on Commando, Delta and Phantoms_of_the_Asteroid besides |

The seven files neither fits measure 12–18 frames — the noise-throughout class
§ 7.ggg already documents. Sanxion is the one genuine miss: it measures 1 where
both derivations say 2.

**And this was invisible for as long as it existed**, because the test that
pins the reading uses the repo's `Commando.sid` fixture, which carries *three*
subtunes. The fixture's mode is 3; the corpus rip's is 1. The assertion passed
throughout while every fidelity number for Commando — and every drum record in
the file a listener validated by ear — was emitted at the wrong length.

**Three: frame 0 is `multiplier` calls here too.** With the length right,
Warhawk still read `noi pul pul pul` against `pul noi pul pul` on five
instruments while its two drum-only ones matched. Its `-S2`: the tick path's
lead was one *call*, so it covered half of frame 0 and the noise finished it,
and siddump samples at end of frame. This is v0.5.220's defect arriving for the
third time in the same file — `_drum_entries` was fixed then, `_two_stage_entries`
in v0.5.218, and the plain `tick` path was never looked at. It now calls the
shared `_first_frame_lead`.

#### The corpus, at fixed settings

| | | |
|---|---|---|
| `onset` | **+29.5 pp** on 15 files | 0 down. IK 40→100, Warhawk 67→100, Spellbound 50→100, Phantoms 57→100 |
| `nrun` | **+37.2 pp** on 16 files | Warhawk 67→100, Proteus 33→100, Delta 67→100, Zoolook 50→100 |
| `melody` | **+20.6 pp** on 8 files | 0 down. Formula_1_Simulator 39→88, Last_V8 (both) 62→100, Warhawk 74→82 |
| `seq` | +17.3 pp on 8 | |
| `pitch` | +12.6 pp on 5 | Spellbound 71→96 |
| `wave` | +0.9 pp on 18 | mixed by file, as a whole-window average over a 1–2 frame change must be |
| `adsr`, `tail`, `pul`, `filt`, `cut` | unmoved on every file | |

Two columns move the wrong way and are recorded rather than smoothed over.
`retrig` moves on 8 files, three of them from an undershoot to a *smaller*
overshoot (in log space, which is how a ratio is compared here) and Spellbound
from 1.13 to 1.50, a real regression on a file whose `melody` rose 16 points.
`vib` falls on 11 of the 15 files it moves — our reversal count against the
original's, on files where it was already under 1. Both columns read pitch
movement through siddump's note/bend split, which a change to the *waveform*
shifts frames across (§ 7.uu); neither is evidence about pitch on its own.

> **The transferable lesson**, and it is the third version of the same one:
> a rule about the player belongs in a function every emitter calls, not in a
> comment in one of them. `_first_frame_lead` was extracted in v0.5.220 for
> precisely this reason and the third emitter still did not call it. The
> corollary is new: **a fixture is not the corpus.** A test that pins a
> derivation against a file with three subtunes cannot see that the same tune,
> as the corpus ships it, has nineteen.

### 7.yyy The other Class B file: a gate read one byte out

v0.5.227. Mega Apocalypse was the second file the handoff filed as **Class B** —
a transient on the note's second frame that measured *identically* under
`--two-stage`, `--wave-program` and as shipped. Four of its seven instruments
open `X noi …` where we hold the first frame's waveform:

```
adsr     orig                ours
$07E7    tri noi pul pul     tri tri tri tri     +7 = $01
$09F9    tri noi tri pul     tri tri tri tri     +7 = $01
$0848    tri noi tri tri     tri tri tri tri     +7 = $44
$0998    pul noi pul pul     pul pul pul pul     +7 = $80
```

The two `$01` records are the byte-code wave program of § 7.fff, whose
interpreter detection *had already found* in this file (`wave_program` at
`$4D21`). What it had not found was the gate:

```
4D74  A5 EC      LDA $EC        ; the effect byte, zero page here
4D76  29 01      AND #$01
4D78  F0 46      BEQ past
4D7A  86 E4      STX $E4        ; <- two bytes, not three
4D7C  B9 A3 54   LDA $54A3,Y    ; the pointer array -- the walk's anchor
```

`find_wave_program` anchors on that `LDA array,Y / STA zp` pair — deliberately,
because the array and the pointer the fetch dereferences must be the same one —
and then stepped back a **fixed three bytes** for the `STX save` before looking
for the branch. Three is `STX abs`, which 28 of the 29 files carry. Mega
Apocalypse stores to zero page, so the walk looked for a branch opcode inside
the `AND`'s operand, found none, and reported the gate as unread. And reporting
it as unread is the emitter's refusal condition — `_wave_program_entries`
returns `None` when `wave_program_gate` is 0 — which is why forcing the option
on changed nothing at all, on any measure. The mechanism was implemented,
detected, enabled, and declining.

Trying both widths reads `$01` and leaves all 28 others byte-identical (checked
by running the old walk beside the new one over the corpus). The two `$01`
records then match the original **frame for frame**, `tri noi pul pul` and
`tri noi tri pul`, and the file's `onset` goes 42.9% → 71.4% with frame
agreement 0.75 → 0.93.

The other two records stay wrong and are named rather than folded in: `$0848`
is `$44`, a bit pair nothing reads here, and `$0998` is `$80` — whose handler
in this player writes `$D40F`/`$D412`, **voice 3 absolutely**, wherever the note
is playing, where `_sfx_drum_entries` puts the hit in the note's own voice. That
is a different shape from the seven-file drum § 7.rrr decoded and is not the
same bit doing the same thing.

**The change is inert until the preset search runs.** `--wave-program` is off
for this file, so every conversion in the corpus is byte-identical after the fix
(verified by hashing all 83). What it does is make the option *capable* of being
selected, the same "a new option is inert until it is in three places" trap in
its detection form.

> **The transferable lesson:** this is `_burst_cutoff_start` (v0.5.210) again —
> a signature anchored at a fixed byte distance reads one dialect and silently
> declines the next. When a walk steps a constant number of bytes over an
> instruction, ask which addressing mode that constant assumes.

### 7.ffff The packed player is not the editor: `--no-test-restart` owns frame 0

v0.5.229. IK+ was the handoff's **Class A** example — an attack transient the
original sounds and we hold flat, where forcing `--two-stage` raised `onset`
0.450 → 0.550 and cost 13 points of `melody`, so `keeps_notes` refused it. The
diagnosis "the emitter is wrong for this file in the way the `$40` halving was
wrong for Ricochet" was right about the shape and wrong about the mechanism.

Forcing `--wave-program` on it and reading the shapes:

```
adsr     original            ours
$0505    noi noi tri pul     noi noi noi tri     ours LATE
$08D8    tri noi tri pul     tri tri noi tri     ours LATE
$09F8    tri noi tri pul     tri tri noi tri     ours LATE
```

Three instruments a frame **late** — the mirror of § 7.www, whose corpus
signature was 32 early and 0 late. And `songview.py` said the wavetable itself
was exactly right: `11 / 81C2 / 1180 / 4180`, the record's `tri`, then the
program's noise, tri, pulse. The bytes say `tri noi tri pul` and the chip plays
`tri tri noi tri`.

The one thing IK+ has that almost nothing else does is **`--no-test-restart`**,
one of the four corpus files carrying it (with Hollywood_or_Bust,
One_on_One_Jordan_vs_Bird and Star_Paws). Turning it off, with everything
else identical, gives three exact matches. The two conversions differ in **one byte
per instrument**: `firstwave`, `$09` (gate + test bit) against the record's own
waveform.

#### Why that costs a frame, and why the editor cannot show it

In `gplay.c` it would not. A new note sets `cptr->wave = firstwave` and then
falls through to `WAVEEXEC` **on the same call**, so wavetable entry 0
overwrites `firstwave` and the value never reaches the chip.

The packed player is a different program. `player.s:903-911`, after the
new-note init:

```
              .IF (NOEFFECTS == 0)
                lda mt_chnnewparam,x            ;Execute tick 0 FX after
mt_tick0jump1:                                  ;newnote init
                jsr mt_tick0_0
              .ENDIF
                jmp mt_loadregs                 ; <- straight to the registers
...
mt_nonewnoteinit:                               ; only the NO-new-note path
                jsr mt_tick0_0                  ; "and wavetable afterwards"
mt_waveexec:
```

**The wavetable does not execute on a note's first call.** `firstwave` is what
reaches `$D404` on frame 0, and entry 0 lands on frame 1. With the default
`$09` that is invisible — the test bit selects no waveform, so frame 0 shows
nothing and entry 0 (the lead § 7.www added) is the note's first audible
frame, exactly where the player writes it. With `--no-test-restart` the
record's waveform is *already* on frame 0, and the lead repeats it: every
effect one frame late, for every instrument in the file.

The raw trace, voice 2, the same note either way:

```
--no-test-restart          default
frame 7  0000 C-0 80  11   frame 7  .... ... ..  09     <- note init
frame 8  1BA2 (G#4)   ..   frame 8  1BA2 G#4 B8  11     <- entry 0
frame 9  313C (F#5)   81   frame 9  313C (F#5)   81     <- entry 1
```

Note also what the option does to the *anchor*: with the gate on and the
frequency still `0000`, siddump prints a bare note `C-0` at frame 7 and every
attack-anchored measurement for those files reads from there.

`_first_frame_entry` takes the flag and returns False under it, so all four
emitters lose the lead together — the rule stays in one function, which is
§ 7.bbbb's lesson and the fourth time this file has had to learn it. IK+ with
`--wave-program`: `onset` 0% → **60%**, frame agreement 0.45 → 0.75, three
instruments exact, no "late" left.

**Corpus-wide it changes no byte**, because the four files carrying
`--no-test-restart` have none of the effect options on — the lead is only
emitted by the drum, two-stage, pitch-seq and wave-program blocks. Like
§ 7.yyy, what the fix does is make those options *selectable* on files where
they were being measured through a one-frame shift.

> **The transferable lesson:** this repo has two players. Every number here
> comes from `gt2reloc`'s packed one, and the editor's `gplay.c` is the more
> readable and the more often read. They agree about the format and not about
> the *schedule* — and a defect that lives in the difference is invisible to
> the source everyone consults.

### 7.gggg What `onset`'s 18% is made of, and a search that walked downhill

v0.5.230. Two findings that turned out to be the same story from opposite ends:
the column's remaining disagreements are almost entirely *mechanisms we do not
emit*, and one reason we do not emit them is that the search which chooses the
options can discard a setting it has already measured as better.

#### Calibrating the level

`onset` had never been calibrated. It demands an exact four-frame
waveform-class match, so an unknown share of the misses could have been
legitimate differences rather than defects — which is why every claim about it
so far has quoted its *movement* and not its level. Classifying every
disagreeing instrument in the corpus by kind settles it:

| kind | | | what it means |
|---|---:|---:|---|
| match | 348 | 80.9% | |
| **flat** | **59** | **13.7%** | the original changes class during the window and we hold frame 0's — a mechanism we do not emit at all |
| **phase** | **15** | 3.5% | the right sequence, one frame early or late |
| partial | 5 | 1.2% | some frames agree, nothing simpler fits |
| wrong | 2 | 0.5% | both change, and to different things |
| invented | 1 | 0.2% | we change where the original holds |

430 instruments over 42 files with at least one miss. Of the 82 misses,
**74 — 90% — are `flat` or `phase`**: a routine missing outright, or one
emitted out of phase. The remaining 8 are the only candidates for "a legitimate
difference the column is too strict about". The level is a defect count to
within a tenth, and quoting it as such is now defensible.

The census is a second implementation, so it can be checked against the first:
its 15 `phase` instruments are exactly the 15 the report counts as
`onset_ours_early` (and both say 0 late), computed by different code from the
same traces.

Grouping the `flat` misses by their record's effect byte gives the work list —
read as a lead rather than a fact, since the census keys instruments by ADSR
pair and several records can share one:

```
$01 x19   $04 x11   $80 x6   $0A x6   $08 x3   $20 x2   $02 x2   $14 x2
```

`$01` is a drum in one dialect and a byte-code wave program in another, `$04`
the two-stage attack, `$80` the SFX drum — all three *implemented*. Which means
a large part of the 59 is not missing code at all but options that are off.

#### The search that walked downhill

IK+ is the case, and it took an instrumented run to see. `--wave-program` on
that file was **accepted**: noise 140 → 1170 of the original's 1517, `onset`
0.45 → 0.75, `melody` unchanged at 0.990. Sixteen combinations later the walk
replaced it with `--no-test-restart` — noise back to 168, `onset` back to 0.45 —
which wins only because 168 frames of noise happen to sit at a pitch nearer the
original's than 1170 do.

§ 7.eeee's postscript had already found that `fidelity_better` is not a total
order and that the 31-combination loop is therefore a greedy *path*. It fixed
the cosmetic half: `prune_inert` drops a flag that changes nothing. This is the
substantive half — the path can run **downhill**, and the setting it gives up is
one it measured as better.

The criterion now also requires the candidate to be no *worse* than the
reference on `onset`, and never to lose the noise outright. It still imposes no
total order on the five terms: a candidate that trades one for another is simply
not accepted, which is the honest answer when the measurements disagree.

**Two vetoes and not five, and the first attempt is why.** Written to cover
every term it could compare — the oscillation ratio and the noise pitch as well
— it rejected the very candidate it was built to protect. IK+'s
`--wave-program` is better on noise, oscillation *and* onset, and was blocked by
its noise *pitch*: that pitch is estimated over the frames the setting itself
creates, 140 without it and 1170 with, and the pitch of 140 frames is not the
same quantity as the pitch of 1170. Across the corpus that version lost **seven
measured settings and gained one** — a net regression, caught because the search
result was diffed against the shipped presets before being adopted.

It is the veto form of a trap CLAUDE.md already states for register agreements:
*a change that resizes the events a term scores cannot be judged by that term
alone*. `onset` survives it because each side is read at its own attack frames
and scored per instrument, so it does not grow with the frames a setting adds;
and losing the noise outright is a fact rather than an estimate — named
explicitly, because `_closer` reads 0 frames as *not measurable* and declines to
compare it, so a candidate silencing a drum would otherwise pass while winning
on something else.

#### What it changed

One file, which is the right size for a fix to a selection rule that had been
wrong in one place:

```
IK_plus   no_test_restart -> wave_program
          noise  168 -> 1170 of the original's 1517
          nrun     0% -> 100%      onset  0% -> 60%
          pitch   79% -> 85%       melody unchanged
          wave    51% -> 49%   <- the documented cost of restoring a transient
```

Corpus means `onset` 82.0% → 82.8% and `nrun` 70.9% → 72.7%. Every other file's
settings and bytes are unchanged.

> **The transferable lesson:** "any one of these five improving is enough" is a
> sound acceptance rule and an unsound *replacement* rule. The moment an
> accepted candidate becomes the new reference, a rule with no total order needs
> a no-regression clause, or the search's answer depends on the order its
> options happen to be enumerated in — and nothing in the output says so.

### 7.hhhh Effect bit `$02` is the rise in one dialect and this in twenty-one

v0.5.231, and it came straight out of § 7.gggg's work list: `$0A` appeared six
times among the `flat` misses, on W_A_R, W_A_R_Preview and Flash_Gordon, all
reading `X X noi X` — a noise frame on the note's **third** frame, which no
emitter here produced.

`$0A` is `$02 | $08`, and W_A_R `$E759` says what both do:

```
E759  LDA effect / AND #$02 / BEQ $E776
E760  LDY voice
E763  LDA counter,X / AND #$01 / BEQ $E770   ; a per-voice FRAME counter
E76A  LDA $E950,Y                            ; the record's own +2
E76D  JMP $E773
E770  LDA $EA51,Y                            ; ...or the alternate
E773  STA wavecell,X

E776  LDA effect / AND #$04 / BEQ $E791      ; the two-stage attack (7.vvv)
E791  LDA effect / AND #$08 / BEQ $E7B9      ; the same alternation, on the NOTE
```

So the voice's waveform **alternates every frame** between the record's `+2`
and a second per-instrument table one byte past the two-stage attack waveform.
In 20 of the 21 files carrying the block that alternate is `$81` — noise with
the gate on — so what it sounds is a noise frame every other frame under the
note. Bit `$08` is the same alternation applied to the *note*; only the
waveform half is emitted here, and the note half is named rather than guessed.

**Bit `$02` is the rise in Warhawk's dialect**, which is why the emitter is
gated on `det.wave_alternate >= 0` — the routine having been found — and not on
the bit. No corpus file has both blocks.

#### The phase, which is the thing that makes it expressible

A per-voice counter that free-runs would leave a note no reproducible starting
phase, and § 7.ttt is the precedent: bit `$10`'s arpeggio is driven by a global
counter, cannot be put in a per-note wavetable, and no rotation of it is right
more than 1/steps of the time. This one is different, and the trace says so
rather than the code: W_A_R's instrument `$0900` reads `tri tri noi tri` on
**all 205** of its onsets — one shape, no distribution at all. The note's first
frame is spent by the init path (§ 7.www), and the alternation runs from the
second. So the wavetable is the frame-0 lead, then the pair, looping — with each
half held for `multiplier` calls, which W_A_R at `-S4` is the check on.

#### What it measures

Corpus A/B at fixed settings, 19 files' bytes changed:

```
onset   +26.9 pp on 12 files, 0 down     mean 82.8% -> 86.7%
wave     +4.9 pp on 12 files             W_A_R_Preview 85 -> 100, Flash_Gordon 86 -> 99
nrun    +50.0 pp on  4 files
melody, seq, pitch, retrig, adsr, vib, tail, pul, filt, cut  unmoved on every file
```

The noise-frame counts are the evidence that the mechanism is *right* rather
than merely helpful — ours against the original's, after:

```
Flash_Gordon  1142/1144    W_A_R      818/820     Tarzan   1254/1255
Nemesis       1059/1074    W_A_R_Prev 1330/1332   Delta    1049/1050
```

Three files remain short (Chain_Reaction 268/1383, Deep_Strike 988/1031,
Sanxion 1589/1669) — Chain_Reaction because several of its alternates are `$11`
and `$15` rather than `$81`, which this emits faithfully and which therefore
sounds no noise at all. Deep_Strike's `wave` falls 81% → 78% while its `onset`
goes 57% → 100% and its noise 393 → 988 of 1031: the documented trade of
§ 7.eee, and the only file where it lands that way.

> **The transferable lesson:** the census in § 7.gggg was not a report, it was a
> queue. Grouping the misses by the record byte that causes them turned "18% of
> instruments disagree" into "read the `$02` handler", and the handler took an
> afternoon where the census took a morning.

### 7.iiii Bit `$02`'s second dialect — decoded, measured, and not shipped

v0.5.232. § 7.hhhh emptied `$0A` out of the census's work list; two entries in
the same family were left, and they are the *same mechanism written twice*.

Hollywood or Bust `$0774` (and Chicken Song):

```
0774  LDA effect / AND #$02 / BEQ out
077B  LDA $09A2 / AND #$01 / BEQ $078C   ; a GLOBAL frame counter
0782  LDA wave,X / AND #$07 / ORA #$80   ; ...noise, keeping the control bits
0789  JMP store
078C  LDA wave,X                         ; ...or the voice's own waveform
078F  store: STA $D404,Y
```

Two differences from § 7.hhhh's: the counter is global rather than per voice,
and the alternate is **derived** (`$80 | (wave & $07)`) rather than read from a
table. Both files' phase is nonetheless stable — Hollywood or Bust's `$0800`
reads `tri noi tri noi` on all 375 onsets and `$0A00` on all 125 — and the
phase is *opposite* to the tabled dialect's, which the code explains rather
than contradicts: in both, the note's frame 1 takes the `BEQ`'s **fall-through**
branch, and the two players put different things there.

#### Why it is not emitted

Measured, both files, everything else fixed:

```
Chicken_Song       wave 77 -> 84%   noise 490 -> 919   nrun 0 -> 100%   onset 57 -> 86%   melody unmoved
Hollywood_or_Bust  wave 83 -> 100%  noise   0 -> 1496  nrun - -> 100%   onset 71 -> 100%  melody 58 -> 47%
```

One file each way. Eleven points of melody is not a price this repo pays for
register agreement -- it is exactly what `fidelity_better`'s `keeps_notes`
guard exists to refuse -- and there is no per-song switch for it short of a
sixth `--fidelity` toggle, which would double a search already running 31
combinations a song. So the block is **detected and logged and not written**,
the same standing `_find_sfx_drum` had for seven files before § 7.rrr, and the
Hollywood or Bust question is handed on with its numbers rather than buried.

#### What the detour found instead: the right-side byte

Chasing the melody loss produced something that outlives it. The wavetable's
right side does not mean the same thing in the two players:

| byte | `gplay.c` (the editor) | `player.s` (what gt2reloc packs) |
|---|---|---|
| `$00` | the base note, +0 semitones — **re-asserts the note** | `bne` fails: **no frequency write at all** |
| `$80` | `if (note != 0x80)` — **no change** | `adc chnnote / and #$7f` = `(128+n) & 127 == n` — a no-op transposition, and still a write |

So the value that leaves a bend alone is `$00` in the packed player and `$80`
in the editor, and every number in this repo comes from the packed one.
Emitting the alternation with `$80` — chosen by reading `gplay.c` — took
Hollywood or Bust's melody to **25%**, worse than either alternative, because
it re-asserted the base note on every frame and cancelled the file's own pitch
movement. That is the third place (§ 7.ffff, § 7.gggg) where the two players
differ and the editor is the more readable and the more misleading.

It also acquits the `$80` this repo already writes on delay entries, and here
the reading nearly went wrong a second time. `player.s:955-962` looks as though
the jump path leaves carry **set** -- the `clc` is assembled only for a song
with no wave commands -- which would make `$80` on the entry directly before a
jump `(128 + n + 1) & 127 == n + 1`, a semitone up. A corpus scan found 46 such
entries across 10 files, 44 of them emitted by § 7.hhhh's own block at `-S3`
and above. Tracing W_A_R both ways refutes it: **0 of 1500 frames differ in
frequency on any of its three voices**. `$80` and `$00` are equivalent on a
delay entry; they are not on a waveform entry, which is what cost Hollywood or
Bust its 22 points. The alternation now writes `$00` throughout for one
convention per block, and that change is byte-visible on 8 files and
measurably inert -- said here because a flat A/B is otherwise indistinguishable
from a change that reached nothing (§ 7.uuu).

> **The transferable lesson:** decoding a mechanism and shipping it are
> different decisions, and the second one is the corpus's to make. A block read
> correctly out of the 6502 can still cost more than it gains, and "we
> understand it now" is not a reason to emit it.

### 7.jjjj The census becomes a mode, and a shift that explained nothing

v0.5.234. § 7.gggg classified the `onset` column's disagreements with a scratch
script, and that classification is what turned a rate into a work list — `$01
x19, $04 x11, $80 x6, $0A x6` — the last group of which was decoded and
emitted (§ 7.hhhh) inside the same session. The script was then lost with the
scratch directory it lived in, and had to be written again to ask the same
question of a later tree. It is now `fidelity.py --census`.

#### Same comparison, not a second one

The census is computed inside `_measure`, from the two traces the column has
just scored and with the same modal reduction, so its `match` count *is*
`onset_matched` and its population *is* `onset_instruments`. A second pipeline
would have been the more independent check and the wrong trade here: it would
resolve its own subtune (`--search-subtunes` defaults to **3**) and could then
disagree with the report for a reason that has nothing to do with the
conversion. The independence that is worth keeping is between `classify_onset`
and the report's own `onset_ours_early`/`_late`, and that is held by a test
rather than by a duplicate implementation.

The effect byte each `flat` miss is grouped by comes from the instrument's own
**name** in the converted `.sng` — `NN:b5-b6-b7`, the converter's provenance
stamp — parsed by `songview.parse_sng`. No second detection pass, and the join
key is the ADSR pair for `onset_shapes`' reason: it is a verbatim per-instrument
copy of the record. Two instruments sharing one are marked `ambiguous` rather
than silently attributed to the first, because a work-list entry filed under
the wrong effect byte is worse than a missing one.

#### What promoting it to a tool found

Corpus at v0.5.233, pooled over instruments (not the per-file mean the report
prints):

| kind | | | what it means |
|---|---:|---:|---|
| match | 372 | 85.9% | |
| **flat** | **50** | **11.5%** | the original changes class during the window and we hold frame 0's |
| short | 4 | 0.9% | our note stops selecting a waveform inside the window |
| phase | 3 | 0.7% | the right sequence, one frame early or late |
| partial | 3 | 0.7% | |
| invented | 1 | 0.2% | |
| wrong | 0 | 0% | |

Three of what had been **six** `phase` entries were not phase errors at all:

    Devils_Galop   GT 2  $0208   original `noi noi noi noi`   ours `noi noi noi --`
    Monty_on_the_Run GT 2 $0208  original `noi noi noi noi`   ours `noi noi noi --`
    Pandora        GT 5  $4A59   original `tri tri tri tri`   ours `tri tri tri --`

The shift test is `ours[:-1] == orig[1:]`, and on a shape the original holds
**constant** that is true of anything agreeing in its first three frames. Our
note simply *ends* inside the four-frame window — a note-**length** difference,
which is a different defect in a different place and one no column here
measures — and it was being reported as a one-frame phase error, which points
at a fix (move the emitter) that would make it worse. `onset_shift` now
requires the shift to explain something the unshifted reading does not, both
readings share that one function, and the census calls the remainder `short`.

The three that survive are Rasputin's, and they are real: `pul pul noi pul`
against `pul noi pul pul` on three instruments, which no unshifted reading
fits.

> **The transferable lesson:** a degenerate case of a pattern-match is not
> evidence of the pattern. `A == B` proves nothing where `A == B` is true of
> everything in the neighbourhood — the discriminating question is whether the
> hypothesis explains something its absence does not. And a diagnostic that
> names the *wrong* cause is worse than one that names none: it sends the next
> session to move an emitter that is already where it belongs.


### 7.kkkk The largest group in the census was a rate, not a mechanism

v0.5.235. § 7.jjjj's work list opens with `$01 x19` — nineteen instruments
across nine files whose notes the original opens on a noise transient and we
hold flat. The shapes are almost one shape:

    Saboteur_II   GT 3  $08F8   original `tri noi tri pul`   ours `tri tri tri tri`
    Ricochet      GT 4  $07E7   original `tri noi pul pul`   ours `tri tri tri tri`
    Shockway      GT 3  $0889   original `tri noi pul pul`   ours `tri tri tri tri`
    Star_Paws     GT 8  $08C7   original `noi noi tri pul`   ours `noi noi noi noi`

None of the nine has `det.effect_drum`, so bit `$01` is not the drum here. In
eight it is the **wave-program gate**: `det.wave_program >= 0`,
`det.wave_program_gate == $01`, and the records carrying the bit are exactly
the instruments the census flags. So the mechanism was implemented, the option
existed, and `presets.py --fidelity` had measured it on every one of these
files across two corpus searches without ever selecting it.

#### Because it was measuring nothing

`--wave-program` forced on, corpus A/B: the converted bytes changed on **1 of
9** files. `_wave_program_entries` opened with

    if fmt != FORMAT_GTS5 or max(1, multiplier) != 1:
        return None

and seven of the nine pack at `-S2`, `-S3` or `-S5`. The option was selectable,
measured, and inert — a search cannot choose a setting that changes no bytes,
and `prune_inert` (§ 7.eeee) would have dropped it if it had. The refusal was
deliberate and documented: one opcode is one of the player's frames, a
wavetable steps once per *call*, so at `-S2` the program would run twice as
fast, and the docstring said "restricting it is an under-read; guessing the
rate is not".

The rate needed no guessing. It is the same division every other table in this
converter already does (§ 7.bb), and `_wave_hold_byte` is already the shared
encoding of it: a repeat of the waveform at `-S2`, where no delay value exists
for a single extra call, and a delay of `m - 2` above. Each opcode now gets one
after it, so the program lasts the same number of *frames* at every `-S`, and
the lead comes from `_first_frame_lead` — which this emitter, a fourth one,
had never called (§ 7.bbbb).

**The hold's right side is `$00` and that matters here specifically.** In the
packed player `$00` is *no frequency write at all* and `$80` is a no-op
transposition that still writes (§ 7.iiii). Elsewhere in this file the two are
interchangeable on a delay entry, traced; after a `>= $80` opcode they are not,
because `$80` would re-assert the pattern's own note over the absolute pitch
the opcode had just set.

#### What it lands

Bytes now change on 7 of the 9, and the noise-frame counts are the evidence
that the emission is *right* rather than merely present — ours against the
original's:

| file | noise before | noise after | original | onset | wave |
|---|---:|---:|---:|---|---|
| Shockway_Rider | 0 | **404** | 404 | 71% → 100% | 58% → 80% |
| Saboteur_II | 185 | **748** | 753 | 60% → 100% | 77% → 84% |
| Ricochet | 0 | **1402** | 1648 | 60% → 100% | 56% → 64% |
| Thundercats | 439 | **1652** | 1841 | 57% → 86% | 63% → 78% |
| Kings_of_the_Beach_intro | 1455 | **1975** | 2143 | 67% → 100% | 90% → 96% |
| Star_Paws | 944 | **1614** | 2372 | 56% → 78% | 73% → 69% |

`melody` is unmoved on all but Kings of the Beach, which gains six points.

#### Star Paws, and an A/B that measured the wrong thing

Forced on *over the song's existing preset*, Star Paws collapsed: voice 1 went
from melody 1.00 to **0.00** at an unchanged attack count — every attack in its
place and every one renamed, which is what an absolute pitch written over the
played note looks like. It was nearly written up as a defect in the emission.

It is an **interaction with `--no-test-restart`**, which that song's preset
carried. That option puts the record's waveform in the instrument's `firstwave`
and the emitters must then leave frame 0 alone (§ 7.ffff), so
`_first_frame_lead` returns nothing and the program's first opcode — noise at an
absolute pitch — becomes wavetable entry 0. At `-S2` entry 0 is still inside
frame 0, siddump samples at end of frame, and the attack is named by the
program's pitch instead of the played note's.

The search resolves it by varying all five toggles together, which is what it
is for: it drops `no_test_restart` and keeps `wave_program`, and Star Paws
ships at melody **97%** (96.5% → 96.6%, unmoved), `onset` 56% → 78%, noise 944
→ 1614 of 2372, `nrun` 0% → 67%. The `$01` instruments the census flagged for
it — `$08C7`, `$08E7`, `$09E8` — are no longer misses.

The lesson is about the A/B and not about the file: **forcing one option on top
of a preset measures the pair, not the option.** A per-song preset is already a
combination, and the combination is the thing under test.

#### What the search selected, and what it did to the census

`presets.py --fidelity` at 60 s (§ 7.mmmm) takes `wave_program` on **eight**
files — ACE II, Chain Reaction, Kings of the Beach intro, Ricochet, Saboteur II,
Shockway Rider, Star Paws and Thundercats — and changes nothing else in the
corpus. That is the attribution: this change can only reach a file that has a
wave program *and* packs above `-S1`, and all eight do, while every other song's
setting comes back identical to what shipped.

In `FIDELITY.md`: mean `wave` 75% → 76%, corpus noise frames 67176 → **73301** of
the original's 82742, `onset` to 100% on five of the eight.

    Shockway_Rider   noise    0 -> 404 of 404      onset  71% -> 100%   wave 58% -> 80%
    Ricochet         noise    0 -> 1402 of 1648    onset  60% -> 100%   wave 56% -> 64%
    Saboteur_II      noise  185 -> 748 of 753      onset  60% -> 100%   wave 77% -> 84%
    ACE_II           noise  288 -> 542 of 543      onset  71% -> 100%   wave 74% -> 83%
    Chain_Reaction   noise  268 -> 1367 of 1383    onset  71% -> 100%   wave 75% -> 90%
    Thundercats      noise  439 -> 1652 of 1841    onset  57% ->  86%   wave 63% -> 78%
    Kings_intro      noise 1455 -> 1975 of 2143    onset  67% -> 100%   melody 61% -> 67%
    Star_Paws        noise  944 -> 1614 of 2372    onset  56% ->  78%   wave 73% -> 69%

And in the census that started it, `$01` falls from **19** instruments to **4**:
Hollywood or Bust and Ninja, whose players have no wave program at all
(`det.wave_program == -1`, so bit `$01` there is something else again), and Wiz,
the one file of the nine at `-S1` — it was already emitting its program before
this change, and `gt2reloc` writes no `.sid` for the result. Corpus `match` goes
372 → **390** of 433 (85.9% → 90.1%) and `flat` 50 → 31.

`Wiz` is a second, older lead: it is the one file of the nine at `-S1`, so it
was already emitting the program before this change, and `gt2reloc` writes no
`.sid` for the result — exit code 0, no output file, the silent refusal path.
Its wavetable is 112 entries, well inside the 255 limit, so that is not the
cause. Pre-existing and unrelated to the multiplier.

> **The transferable lesson:** "the option is measured and never selected" has
> two readings — the search disagrees with you, or the search is comparing a
> file with itself. `--baseline`'s byte-hash separates them in one run
> (§ 7.uuu), and it is worth doing *before* theorising about the criterion. A
> restriction written down honestly in a docstring is still a restriction
> nobody re-examines: this one stood for 32 versions with the corpus's largest
> unrendered group behind it. And the second half, from Star Paws: an option
> forced on top of a preset is measured *with* that preset. When the result is
> a collapse rather than a shortfall, suspect the pair before the mechanism.


### 7.llll A search that failed, and a preset that looked like a decision

v0.5.235, found while re-running the preset search for § 7.kkkk. One line in
its output:

    W_A_R.sid: fidelity search failed (ValueError), keeping defaults

"Keeping defaults" is the structural result — and W_A_R's previous entry
carried `two_stage`, measured by an earlier search. The song did not decide
against it; the song was never scored. In the generated `presets.json` those
two are the same absence.

The exception is real and is a *different* defect:

    ValueError: wave table needs 256 entries, exceeding MAX_TABLELEN (255)

on 4 of W_A_R's 31 combinations, all of them `two_stage` + `pitch_seq`. The
cause is that above `-S1` a drum record occupies **six** wavetable entries — the
frame-0 lead is two entries (§ 7.bbbb) and the noise tick's delay is a third —
while `_wavetable_layout` reserves `WAVE_ENTRIES_PER_INSTR` = 5 for every later
record and floors each budget at the same 5. `_drum_entries` checks the budget
only for its *sweep*, so its base shape can overrun by one. It bites only where
a table is nearly full: W_A_R has 29 instruments at `-S4`, and record 25 was
handed a budget of 5 and emitted 6.

Two separable fixes, and only the cheap one is taken here:

* **`play()` treats a candidate that will not convert as one unplayable
  candidate**, returning None and naming it on stderr — exactly what it already
  did for a `.sng` `gt2reloc` refuses. W_A_R's other 27 combinations are scored
  now, and its answer is a measurement rather than a crash.
* **A song whose search does fail keeps what the previous run recorded.** The
  carry-forward that a routine regeneration already performs was gated on
  `--fidelity` being *off*; it now happens either way, and the message says
  which settings were kept.
* The overflow itself is left open and written down. Fixing it means either
  reserving six entries per record on a multispeed file or teaching every
  emitter the budget its base shape needs — both relay out every multispeed
  file's wavetable, which is a byte-visible change on dozens of files and wants
  its own corpus A/B rather than a ride on this one.

> **The transferable lesson:** in a generated file, "no setting" and "no
> measurement" look identical, so the generator has to be the thing that keeps
> them apart. Any batch tool whose per-item failure falls back to a default is
> quietly rewriting earlier results — read its stderr before adopting its
> output, and prefer a fallback that preserves the last known measurement over
> one that invents a fresh default.


### 7.mmmm The search was choosing settings in a window that could not see them

v0.5.235, and the reason the first regenerated `presets.json` of this session
could not be shipped. Re-running `presets.py --fidelity` at its default 10 s
*lost* `two_stage` on five files — Sanxion, Tarzan, Zoolook, W_A_R and Flash
Gordon — while the § 7.jjjj census, read over 60 s, showed exactly those files'
`$04` records going flat. Two instruments disagreeing about the same change is
the signal to distrust one of them.

The one to distrust was the search's window. Put `two_stage` back on all five
and A/B at 60 s:

| file | onset | wave | noise |
|---|---|---|---|
| Tarzan | 40% → **100%** | 80% → 88% | 724 → 1254 |
| Flash_Gordon | 50% → **100%** | 95% → 99% | . |
| Sanxion | 62% → **100%** | 65% → 59% | 1186 → 1589 |
| W_A_R | 75% → **100%** | . | . |
| Zoolook | 83% → **100%** | . | . |

`melody` unmoved on all five. And the reason the 10 s search cannot see it is
that the window does not contain the music:

    Sanxion at -t 10   onset instruments 1    original noise frames 0
    Sanxion at -t 60   onset instruments 8    original noise frames 1669

Two of `fidelity_better`'s five terms are *noise* terms and a third is `onset`;
at 10 s this file offers one comparable instrument and no noise at all, so the
criterion is not disagreeing, it is blind. Re-run at `-t 60` and the search
selects `two_stage` for all five.

**This is v0.5.195 repeating in the other tool.** That version moved
`FIDELITY.md` from 10 s to 60 s for the same reason — a fifth of the corpus
contributing nothing to `slides` and `bend` — and the finding was written up
about the report. The search kept its own default for forty versions, so every
preset in `presets.json` was chosen in a window the published report had
already been shown to be too short. The default is now 60 and
`tests/test_preset_passthrough.py` pins it against the report's window.

#### The check that the new window is the right one

A 60 s search is not self-evidently better just because a 60 s A/B agrees with
it. The evidence that it is: run over the whole corpus, it **reproduces every
shipped setting exactly** and adds only the eight `wave_program` entries § 7.kkkk
earns. The 10 s run had moved 22 files, 24 settings lost and 10 gained, and that
was read for a while as the converter having changed under a stale
`presets.json`. It had not. The churn was the window, and the file it produced
would have shipped 24 measured decisions away.

> **The transferable lesson:** when a measurement window is found to be too
> short, the finding is about the *window*, not about the tool that happened to
> reveal it. Grep for every other place the same window is chosen. And when two
> instruments disagree about one change — here a search saying "drop it" and a
> census saying "it went flat" — the cheap next step is to ask which of them
> can see the thing at all.


### 7.nnnn One guard, nine files, and every effect-byte routine

v0.5.236. § 7.jjjj's work list, after the wave program emptied `$01`, opened
with **`$04` x11 across five files** — Mr Meaner, Off the Cuff, Pygmies
Revenge, Rikky and Rock Tells the Tale. Bit `$04` is the two-stage attack, the
emitter has existed since v0.5.150-something, and `presets.py --fidelity` had
offered `--two-stage` to all five without ever selecting it. Same shape as
§ 7.kkkk, so the same first question: does the option change any bytes?

It does not, and this time not because of an encoding restriction. All five
report `det.effect_two_stage == False` — the routine was never found. Rikky's
player, disassembled at the one `AND #$04` in the file:

    13C2  LDA $1685        ; the effect byte
    13C5  AND #$04
    13C7  BEQ $13DD
    13C9  LDA $168F,X      ; per-voice countdown
    13CC  BEQ $13D7
    13CE  DEC $168F,X
    13D1  LDA $1704,Y      ; the attack waveform  -- record +9
    13D4  JMP $13DA
    13D7  LDA $16FD,Y      ; ...or the record's own +2
    13DA  STA $1652,X

That is `TWO_STAGE_SHAPE` **byte for byte**, and the note-start push chain that
loads the counter is `TWO_STAGE_PUSH` byte for byte:

    11B7  LDA $1706,X      ; record +11, the duration
    11BA  PHA
    ...
    11D8  PLA
    11D9  STA $168F,X

So both signatures match and detection still says no, because of a line in the
probe they share:

    if det.instr_start < 0 or det.instr_stride != 8:
        return None

`_effect_byte_address` computes record 0's `+7` and searches for the player's
own `LDA base,Y`. Neither step depends on how far apart the records are. The
guard excluded a **dialect** — the nine corpus files whose records are 16
bytes — and with it every routine that reads `+7`: the two-stage attack, bit
`$02`'s alternation, bit `$40`'s pitch, the lot. Nine files, six call sites,
one condition.

Removing it detects the block in all nine, with the two bytes inside the
record at `+9` and `+11` rather than in a table after the records. The existing
data model needed nothing: `duration == attack + 2` either way.

#### What it lands

`--two-stage` forced on, 60 s, ours against the original's noise frames:

| file | noise before | after | original | onset | melody |
|---|---:|---:|---:|---|---|
| After_8 | 0 | **218** | 210 | 75% → 100% | unmoved |
| Mr_Meaner | 0 | **307** | 309 | 86% → 100% | unmoved |
| Rikky | 0 | **270** | 264 | 33% → 100% | unmoved |
| One_on_One | 0 | **765** | 744 | 50% → 100% | unmoved |
| Off_the_Cuff | 1069 | **1331** | 1358 | 40% → 100% | unmoved |
| Rock_Tells_the_Tale | 0 | 286 | 182 | 0% → 100% | 54% → 53% |
| Pygmies_Revenge | 303 | 303 | 611 | 67% → 100% | unmoved |

Five files reach within 3% of the original's noise-frame count from a standing
start of zero, and `onset` reaches 100% on seven of the nine. `wave` slips a
point or two on four of them, which is the documented trade of § 7.eee: a
conversion that renders more transitions has more of them to disagree about.

It reaches one other routine, and to nothing: bit `$80`'s fixed-pitch drum is
now detected in six of the nine, with the same `$48` / voice 2 / period 6 its
stride-8 relatives report — and **not one of those six has a record that sets
bit `$80`**, so it is read and emitted nowhere. Forced on, `--sfx-drum` leaves
all nine byte-identical. That is the per-record rule working (§ 7.rrr): a
detection flag says the player reads the bit, and only a record's own effect
byte says it is set.

#### The counter-example the bound promised could not exist

`_bound_instruments` ends the instrument table where the two-stage array
begins, and its docstring validates the rule by measurement: over the 34
stride-8 files, "the bound never falls below the highest instrument any
pattern references". Eight of the nine new files fail its multiple-of-stride
test and are untouched. The ninth, Powerplay Hockey, passes it — and its
patterns name instrument **8** against a bound of **6**. Taking the bound costs
it melody 72% → 66%, seq 73% → 68%, wave 37% → 26%.

So the reduction is now restricted to `instr_stride == 8`, the population it
was measured on, and the whole corpus's default output is byte-identical
across this change (83 of 83 hashed).

#### Wiz, and a waveform byte that is a jump

The nine files' `$01` group also had a fourth member the wave program could not
help: Wiz, which is at `-S1` and so was emitting its program before v0.5.235 --
and whose result `gt2reloc` refuses, silently, with exit code 0 and no output
file. Replicating `gtable.c:1008`'s `exectable` in Python over the emitted
tables names it in one line:

    OVERFLOW: instrument 2 WTBL from ptr 6

Its block is `81/00 11/80 11/80 11/80 FF/DE`, and the `FF/DE` is not a jump
anybody wrote. Record 1's program is

    slide 11 / slide 11 / slide 11 / **set $FF, 250** / slide 15 / slide 11 / hold

and `_wave_program_entries` puts an opcode's waveform straight into the
wavetable's left column, where `$F0`-`$FF` are **commands**: `$FF` is the jump
and the note byte beside it becomes the target. `$DE` = 222 in a 112-row table,
so execution walks off the end and `greloc.c` reports `TYPE_OVERFLOW` to a
console that does not exist headless.

Three corpus files carry opcodes in the command range: Wiz (one), Kings of the
Beach intro (one) and Mega Apocalypse (six across three records) -- and the last
two **ship with `wave_program` selected**, so their tables contained a jump
where a waveform belongs and happened to land in range.

Fixed in v0.5.237. `_wave_byte` already had an encoding for a byte that cannot
be written literally -- `$E0`-`$EF`, which writes `$00`-`$0F` to `$D404`
(readme.txt 3.4.1, gplay.c:527) -- for waveforms *below* `$10`, where
`$01`-`$0F` are delays. The command range needed the same treatment and the
same reasoning: `$FF` is all four waveform bits **and** the test bit, the test
bit holds the oscillator in reset and four select bits AND to silence on a real
chip, so what the player sounds there is nothing. `$E0 | (wave & $0F)` keeps
gate, ring, sync and test exactly and drops a nibble that produces no output.

Kings of the Beach intro and Mega Apocalypse change bytes and **no column of
the report moves at all** -- stated because a flat A/B is otherwise
indistinguishable from a change that reached nothing (§ 7.uuu); the byte hash is
what says it reached them. Wiz *packs* for the first time, and with
`--wave-program` forced its `onset` goes 67% -> 100% and `nrun` 0% -> 100% for
12 points of melody, which is `keeps_notes`' business rather than this fix's.

The general form is now a test. `gtable.c:1008`'s `exectable` is twenty lines,
so `tests/test_table_validation.py` replicates it and walks every corpus
conversion's tables under its shipped options, asserting neither `TYPE_JUMP`
nor `TYPE_OVERFLOW`. It is the check that turns gt2reloc's silent refusal --
exit code 0, no output file, no message -- into a named instrument and row.

> **The transferable lesson:** a guard that reads like a sanity check can be a
> population filter. `instr_stride != 8` looked like "this probe needs the
> layout it was written for"; it meant "nine files get none of this file's
> nine routines". When a detection probe declines, check whether it declined
> the *file* or the *family* — and when a rule that was validated over a
> population starts reaching outside it, expect the counter-example rather
> than the extension.


### 7.oooo A guarantee the layout asserted and the emitters did not keep

v0.5.239, closing what § 7.llll recorded. `_wavetable_layout` hands each record
a budget of `GT_MAX_TABLELEN - used - reserved`, reserving
`WAVE_ENTRIES_PER_INSTR` = 5 for every *later* record and flooring each budget
at the same 5, and its docstring calls that "nobody starves". It is the
caller's arithmetic. Whether it holds depends on the emitters honouring the
number, and two of them did not:

    _drum_entries            emits 6 at a budget of 5    75 records
    the tick / fall-through  emits 7 or 8               122 records

across 40 of the 95 corpus files. Both are the same shape of omission:
`_drum_entries` checks the budget for its *sweep* -- the optional part -- and
not for its base, and the tick block checks nothing at all. Above `-S1` the
frame-0 lead is two entries (§ 7.bbbb) and the tick's own delay is a third, so
the five-entry assumption stopped being true the moment multispeed timing
arrived and nothing said so.

It bites only where a table is nearly full, which is why one file crashed and
not forty. Emitted lengths against the 255 ceiling: **Mega Apocalypse 255 --
exactly on it** -- Kings of the Beach intro 229, Thundercats 228,
Trans-Atlantic 225. W_A_R at `--two-stage --pitch-seq` overran by one and
`gt2reloc` refused the file with exit code 0 and no message, which cost it a
measured `two_stage` until § 7.llll fixed the search's half of that.

The fix is that both shapes now decline what does not fit, and the *order* of
what is given up is the design:

* The tick block keeps the five-entry shape instead of its own. The tick is
  lost; the table is not.
* `_drum_entries` gives up the **multiplier padding first** -- the lead reverts
  to the one call it was before v0.5.220 -- and only then the tick's hold. That
  is the smaller loss of the two: a frame-0 lead a call short moves a waveform
  *within* frame 0, where losing the tick removes a noise transient a listener
  hears.

Corpus output is byte-identical on all 83 files, and every one of the 31 search
combinations now converts for each of the four fullest files. Two tests hold
it: no record may exceed a budget of 5 anywhere in the corpus, and those four
files must convert under every combination. The first fails against the old
tick block.

**Three test helpers had to be corrected, and that is the finding restated.**
`test_noise_tick.py`, `test_effects.py` and `test_call_rate.py` all called
`_wavetable_entries` without a `budget`, taking the default of
`WAVE_ENTRIES_PER_INSTR` -- and every shape they pinned was one the emitter
could only produce by overrunning that number. The invariant was not held in
the code and it was not held in the tests' model of the code either; nine
assertions had been quietly describing an emitter that ignored its allocation.
They now say how much room they mean. The default stays conservative: a caller
that does not think about the table should get the shape that always fits, and
the layout always passes a real number.

> **The transferable lesson:** a guarantee written in the caller is a comment.
> `reserved = (n - i - 1) * WAVE_ENTRIES_PER_INSTR` reads like a proof and is
> an assumption about code somewhere else -- one that was true when it was
> written and stopped being true when multispeed timing made the minimum block
> six entries. If an invariant spans two functions, test it across both.


### 7.pppp Bit `$80` is right in detection and three frames late in emission

v0.5.244, from the census's `$80 x4`. Bangkok Knights `$8488`, and the same
block in Mega Apocalypse, Star Paws and Thundercats:

    8488  LDA effect / BPL out          ; bit 7 clear -> skip
    848D  LDA $8936                     ; = $8934,X with X=2: voice 3's counter
    8490  CMP #$01 / BEQ fire           ; == 1 -> hit
    8499  CMP #$06 / BCC out            ; == the period
    849D  LDA #$00 / STA $8936          ; at the period -> wrap
    84A4  fire: LDA #$48 / STA $D40F    ; voice 3 frequency high
    84A9        LDA #$81 / STA $D412    ; noise + gate

A fixed-pitch noise hit on voice 3, on the note's **second** frame and every
`period` frames after. The counter is zeroed at note start (`$80CE`) and
incremented once per frame at the foot of the voice loop (`$84D2`), so it is
**note-locked** -- which is what makes it expressible in a wavetable at all,
unlike bit `$10`'s free-running arpeggio (§ 7.ttt). Measured, that holds: 226
of Bangkok's 232 onsets share one shape, and all four files put noise at
offset 1 on 100% of onsets.

**Detection already reads it correctly** -- `sfx_pitch $48`, `sfx_voice 2`,
`sfx_period 6/6/8/6`. The census's `flat` verdict is not a missing mechanism.
What is wrong is the emission's phase and length:

    original  pul noi pul pul pul pul pul noi pul ...   hit at 1, then every 6
    ours      pul pul pul pul noi --  pul pul pul ...   hit at 4, two calls long

The block is `41/00 02/80 81/C9 81/C9 FF/01` -- it *closes* the loop with the
hit where the player *opens* with it, and holds noise for two calls where the
player writes it on one frame.

**Why nothing caught it before `onset`.** `nrun` compares run *lengths* and is
position-independent by design; `noise` is a one-sided count. Under both, a
drum three frames late and a call too long looks present and correct. This is
the census's third mechanism found by asking what a column *cannot* see.

Structural check, since the routine hard-codes voice 3 while we put the noise
in the instrument's own wavetable: in all four files this instrument plays only
on voice 3 (232/371/291/45 onsets, no exceptions), so the wavetable is the
right place for it.

#### The fix, and the belief it had to displace (v0.5.246)

`_sfx_drum_entries` held the opposite in its docstring, in a constant's
comment and in three tests: that the counter was **"per voice and
free-running"**, so a hit falls wherever it falls and a wavetable — which
always begins at the note — should therefore put the noise at the *end* of the
cycle. The plain shape did exactly that, firing at offsets 4-5 of a 6-frame
period where the player fires at 1.

The counter is not free-running. Both dialects zero it at note start —
Bangkok `LDA #$00 / STA $8934,X` at `$80CE`, Trans-Atlantic `STA $0FAD,X` at
`$08D2`, each inside the block clearing that voice's other per-note cells — and
`INC` it once a frame. Disassembled, the two players' gates are the same
routine byte for byte apart from a `STY $D418` where the other has NOPs.

**The measurement the old belief rested on is real, and was misread.** Opening
on the noise took Trans-Atlantic's melody 94.7% → 50.4% — but that experiment
put the noise on **frame 0**, where siddump names the note by whatever pitch is
sounding, so the drum's pitch replaced every attack. It is an argument against
frame 0, which the new shape still respects; it was never an argument for
putting the hit last. The identical collapse appears in § 7.kkkk when
`--no-test-restart` moves a wave program's first opcode into frame 0.

The plain shape is now one frame of the played note, one frame of noise, then
`period - 1` frames of the note, with the jump returning to the **hit** rather
than the top. The burst is one frame, which is what `CMP #$01 / BEQ` implies
and what all four `$48` files measure; `SFX_DRUM_FRAMES = 2` remains, and now
belongs only to the second-note dialect, whose phase was already right — which
is why Trans-Atlantic never exposed this.

    Bangkok_Knights  onset  80% -> 100%   wave 38 -> 40%   melody unmoved
    Thundercats      onset  86% -> 100%   wave 78 -> 83%   melody unmoved
    Mega_Apocalypse  nrun   67% -> 100%   wave 66 -> 77%   onset 71 -> 86%
    Nineteen         nrun   67% -> 100%
    Pandora          onset  86%, wave 67 -> 68%

**The `noise` count moves away from the original on four of the five, and that
is the fix working**: one frame per period where we emitted two. Read alone it
looks like damage. `nrun` compares run *lengths* per instrument and `onset`
reads the opening frames, and both improve — the mirror of § 7.uuu's rule that
a change removing the events a column scores will always appear to improve it.

And the prediction it came with held: **Star Paws now accepts `--sfx-drum`**,
which the search had declined at every previous run. Nothing else in the corpus
changed setting — 1 gained, 0 lost.

### 7.qqqq A track dialect where `$FD` ends a voice and `$FE` is not the end

v0.5.244. Rasputin's three voice pointers index **one shared stream** at
different offsets:

    v0 $C96D: 0A 0B 0B 0B 0B 0C 0C 0C 0C 0D FD | 2B 2B 08 2A 00 FD | FE 03 ...
    v1 $C978:                                    2B 2B 08 2A 00 FD | FE 03 ...
    v2 $C97E:                                                        FE 03 ...

`tracks.py`'s version-0 branch reads `if b1 <= 0xFD: track.append(b1)`, so
**`$FD` is stored as pattern number 253** and voice 0 reads straight on through
voices 1 and 2's data. And voice 2's list *opens* on `$FE`, which that branch
treats as "tune ended", so we emit an empty orderlist and the voice is silent
in every subtune. Both verified in the bytes and in the branch.

`$FE nn` recurs mid-stream (`FE 02 ... FE 03 ... FE 05`), so it is a two-byte
command rather than a terminator -- most likely a transpose, and that reading
is **not yet confirmed**; the operand's use in Rasputin's track reader will
settle it.

The population is not settled either. A scan of version-0 files whose lists
run into an `$FD` gives 5 by one walk and 18 by another, and neither bounds the
pointer table properly -- Rasputin, Tarzan (9 lists), Knucklebusters, Delta
Mix-E-Load loader and Hollywood or Bust are in both. Tarzan and Hollywood or
Bust are named elsewhere in these notes as under-performing.

**And Rasputin's FIDELITY row is a harness artefact, not a conversion
failure.** Its init at `$CFB5` remaps subtunes -- PSID 0 and 1 go to a different
entry point, n>=2 maps to n-2 -- so the traced diagonal is 20% where the real
correspondence (s1->o1) is 64%. At the right pairing we play *more* attacks
than the original (203 against 114), and the census's `phase` verdict for its
three instruments dissolves: our shape is the original's modal shape for two of
them, and the original's tick offset varies per note with the remaining-duration
counter, so no single wavetable offset can match it. It belongs on the
`--diagnose`-first list beside Dragon's Lair II and Flash Gordon.

### 7.rrrr The outer gate has a second spelling, and the old note was stale

v0.5.244. The speed-gate paragraph in CLAUDE.md said the under-read "has to be
found in the players" and named eight files. `--skip-gate` (v0.5.119) found it,
and every one of those eight now measures **0% out** -- Delta's row is 5/2 at
`-S2`, Deep Strike's 8/3 at `-S3`, Thanatos's 15/4 at `-S4`, all packed exactly
via the multiplier. Corpus today: of 63 timed files, 47 exact and 50 within 2%.
Re-measured at HEAD in a clean worktree before correcting the note, because a
stale rule misdirects harder than a missing one.

What is left is one unread idiom, at the PSID *play* address -- Warhawk
`$1012`:

    1012  DEC $15AE
    1015  BPL $101D      ; still counting -> run the player
    1017  LDA #$07 / STA $15AE
    101C  RTS            ; on the underflow call, do nothing at all

That is `_find_outer_gate`'s mechanism ending in **`RTS` instead of `JMP
past-the-gate`**, and `BPL +6` rather than `+8`. `OUTER_GATE` matches only the
`JMP` spelling, so `skip` comes back None and the uncorrected gate is used.
Eight corpus files open their play routine this way: Warhawk, Proteus,
International Karate, Bump Set Spike, Game Killer, Thrust, Mozart, Ninja --
none of which measures correctly today, so reading it cannot break a file that
is already right.

`SPEED_GATE`'s own comment names this idiom, but as *the prescaler variant* in
Mozart/Ninja/Mega Apocalypse, excluded because "no steady Goattracker tempo can
express it". Both halves have expired: it also sits **above** a normal gate in
four other files, where it multiplies rather than replaces; and
`_skip_gate_multiplier` is exactly the machinery that can express such a row
when the denominator is small.

The factor from the code is `(R+1)/R` on the immediate. Warhawk 8/7 -> row
2.286; Bump Set Spike 10/9 -> **3.33, its measured row exactly**. `--pace`'s
median says 9/8 for Warhawk while its own least-squares fit says 0.875 = 8/7,
and the original's gaps are whole frames, so a 2.286 row quantises to a lumpy
2/3 mix -- which is the reported IQR spread 0.875-0.889. Settle the +/-1 by
counting gate edges over a known row count, not by fitting.

Expected reach, and why it is smaller than it looks: Warhawk and Proteus
11% -> ~1.6% out, IK 8% -> ~1.5%, Bump Set Spike 10% -> 0%. Only Bump Set
Spike's corrected row is *encodable* -- 10/3 needs `-S3`, inside
`MAX_ROW_DENOMINATOR` = 6, while 16/7 and 33/10 are not. So the fix buys one
file a correct pack and four an honest diagnosis, and it changes packing, so it
is `[main]` work with a corpus A/B.

> **The transferable lesson:** a note that names *which files prove the
> problem* is a note that can be checked, and this one was -- three years of
> being right and one version of being wrong, because the fix landed and the
> paragraph did not move. Prefer evidence with filenames in it; it decays
> loudly instead of quietly.


### 7.ssss `hold` becomes a search term, and a veto that took three tries

v0.5.247. § 7.rrrr's `hold` column measures note length, and the option whose
main effect it measures — `--no-test-restart` — was selected on three files by
a search that could not see it. The obvious move is to make it a criterion. The
instructive part is everything that went wrong on the way.

#### First, what the option actually does corpus-wide

Forced on for all 81 songs that lacked it, against the v0.5.246 baseline:

| column | better | worse | same | mean |
|---|---:|---:|---:|---:|
| **hold** | 50 | 5 | 26 | **+49.3 pp** |
| **melody** | 0 | **68** | 15 | **−20.7 pp** |
| wave | 67 | 11 | 5 | +3.3 pp |
| onset | 3 | 18 | 60 | −10.9 pp |
| nrun | 18 | 4 | 45 | +10.0 pp |

Twenty-one points of melody across 68 files with **none improving** — the
mechanism of § 7.kkkk at corpus scale: `firstwave` puts a waveform on the
attack frame, and siddump names the note by whatever is sounding. So the option
stays per-song, `keeps_notes` already refuses all 68, and the only files a
`hold`-aware search can legitimately take are the ones where note length rises
and nothing else moves.

#### Then three attempts at saying "and nothing else moves"

**Attempt 1 — melody must not fall at all.** It blocked seven of the eight
files the term reaches. Their melody moves are *thousandths* — Delta 1.000 →
0.996, Tarzan 0.988 → 0.985, Sanxion 0.968 → 0.966 — against a `hold` gain of
0 → 100%. That is the noise floor of a difflib ratio, and a guard tuned to it
measures the wrong thing. Melody belongs to `keeps_notes`, which has a margin
for exactly this reason.

**The justification for attempt 1 was itself assembled from two different
comparisons.** After_8's numbers were read as "melody 92 → 91%, vib 0.93 →
0.29" — but the melody figure came from an A/B that *swapped* `pitch_seq` for
`no_test_restart`, and the oscillation figure from one that *stacked* them
(where melody actually collapses 0.917 → 0.578). A cost from one experiment
and a mechanism from another.

**Attempt 2 — the oscillation must not get worse**, via `_closer`. Its margin
is a fraction of the *remaining* gap, so on a ratio already far from 1 a wobble
clears it: Chicken Song's 0.32 → 0.29 is 8.7% of a gap of 1.14 in log space and
blocked a 100-point hold gain, where After_8's 0.93 → 0.29 is the same absolute
move against a gap of 0.07. Both "worse". Only one is a change of *rate*.

**Attempt 3, which holds — `_oscillation_lost`.** The candidate must not end up
more than **twice as far** from the original's rate as the reference was:

    After_8       0.93 -> 0.29    |log| 0.073 -> 1.238   17x     veto
    Chicken_Song  0.32 -> 0.29    |log| 1.139 -> 1.238   1.09x   allow
    Delta         0.51 -> 0.48                           1.03x   allow

That is a statement about what a listener would hear — a reversal ratio of 0.93
becoming 0.29 is a different rate; 0.32 becoming 0.29 is the same *absence* of
one, measured twice — rather than a threshold fitted to the corpus.

#### The result

**7 files gained, 0 lost**: Chicken Song, Delta, Rikky, Sanxion, Sigma Seven,
Tarzan, Wiz. After_8 keeps `pitch_seq two_stage` — the trade the veto exists to
refuse, a near-perfect arpeggio ratio given up for half a hold.

`hold` is an acceptance term and not part of `gave_back`, deliberately: a new
veto cost seven measured settings the last time one was widened (§ 7.gggg), and
the conservative half of an asymmetric rule is the half that cannot lose a
setting already measured as better.

> **The transferable lesson:** all three failures were the *expectation*, not
> the measurement — an exact bound where the quantity has a noise floor, a
> justification stitched from two experiments, and a test asserting the veto
> should stand down on a move that lands further away. This is the `bend`
> lesson (four corrections in six versions) in a new place: when reasoning
> about a ratio, do the log arithmetic before writing the rule down, and state
> the rule as a claim about what is audible rather than about what is smaller.


### 7.tttt The outer gate's `RTS` spelling, and two misread instruments

v0.5.248, finishing what § 7.rrrr identified. `OUTER_GATE` matched only the
form ending in `JMP past-the-gate`; at the PSID *play* address the same counter
ends in `RTS` -- "on the underflow call, do nothing at all" -- with `BPL +6`
rather than `+8` because it steps over one byte instead of three:

    1012  DEC $15AE / BPL $101D / LDA #$07 / STA $15AE / RTS      (Warhawk)

**Nine corpus files** open their play routine this way and **none carries the
`JMP` form as well**, so a second pattern needed no precedence rule. Reading it
changes the row length on three: Formula 1 Simulator, Thrust and Bump Set
Spike.

    Formula_1_Simulator   melody 88 -> 100%   wave 60 -> 91%
    Thrust                melody 75 ->  94%   wave 80 -> 96%
    Bump_Set_Spike        melody 96 ->  97%   (read with --equal-calls)

#### Both apparent contradictions were misread instruments

The measurement seemed to refuse the factor twice, and both times the fault was
in the reading.

**`--pace` prints a median and a least-squares fit, and they differ.** Warhawk's
median says the row is 2.25 frames where `(R+1)/R` predicts `2 x 8/7` = 2.286 --
but the same output's least-squares fit is 0.875, which *is* 8/7 exactly. The
original's gaps are whole frames, so a 2.286 row quantises to a lumpy 2/3 mix
whose median lands at 2.25. The fit is the estimator to read; § 7.rrrr said so
and it was read past.

**Bump Set Spike's "collapse" is the `-S5` sampling artefact.** Its corrected
row is 3.6 frames, which needs `-S5`, and its melody duly read 96% -> 68%. That
is the caveat this report already carries: siddump samples the registers once
per frame whatever the call rate, so four calls in five are discarded. Under
`--equal-calls` the same conversion reads **97%**. It is the corpus's first
`-S5` file, so this is the first time that caveat has decided a ship/refuse.

Its own image byte is 5, giving `6/5`; the `10/9 -> 3.33` § 7.rrrr attributed
to it is **Thrust's** (image byte 9), and Thrust is where that number lands
exactly.

#### What did not change

No file's `--fidelity` toggles moved -- 0 gained, 0 lost across the corpus. The
whole gain is the row length, which is what a speed-gate fix should be. Nothing
writes these immediates at init either (checked on all five candidates), so the
image byte really is the reload here, unlike the `JMP` dialect where 32 of 51
files rewrite it per subtune.

> **The transferable lesson:** an estimator that prints two numbers is telling
> you the quantity is not a point, and reaching for the friendlier one is how a
> correct prediction gets refuted by its own confirmation. Both of this
> section's reversals were instruments read wrongly -- a median where a fit was
> wanted, and a trace at a rate the trace cannot see -- and the repo already
> documented both hazards.


### 7.uuuu The `hold` column's tail is three things, and one of them is a blind spot

v0.5.249. § 7.ssss left the tail named and unexplained: "7 files at −2, one at
−20, and several *positive*". Measured per instrument across the corpus — modal
run length ours minus the original's, 415 instruments over 81 files:

     -1  231      +0   90      -2  25     -3  8     -4  6
     +5..+23  ~38        +58 +62 +163 +378 +575 +950  one each

#### One: the bulk is a *call*-rate artefact, and the column cannot always see it

Grouped by the rate each file packs at, without `--no-test-restart`:

    -S1   106 at -1, 8 at -2, 5 at -3, 2 at -4
    -S2    92 at -1, 16 at -2
    -S3    31 at -1, 16 at  0
    -S4    17 of 17 at 0
    -S5    11 of 13 at 0
    with the option:  44 of 45 at 0, at any rate

The next-note fetch is `gatetimer & $3f` **play calls** early (gplay.c:905), so
at `-S4` it costs a quarter of a frame and siddump — which samples once per
frame — cannot see it at all. **A zero at `-S4` or above means "not visible",
not "correct"**, and so does half of `-S3`. The `hold` Dimension now says this
in its own description, because a column that reads 100% for the wrong reason
is worse than one that reads 60%.

It also predicts something checkable before looking: the preset search can
never *see* a gain above `-S3`, so no file up there should carry
`--no-test-restart`. All nine that carry it are `-S1` but for Delta at `-S2`.
Pinned by `tests/test_sound_runs.py`.

#### Two: the far tail is not note length at all

Every instrument beyond +50 frames is a known defect wearing a length costume:

    Knucklebusters $00F8   orig 9 frames x 94 notes   ours 959 x 2
    Rasputin $0A0A/$0A0B   24 -> 47                   32/15 and 70/31 notes
    Auf_Wiedersehen $0ADF  581 -> 959                 1 note each side

Knucklebusters plays two notes where the original plays ninety-four — its voice
never retriggers, which is the version-0 orderlist misread of § 7.qqqq (and
Knucklebusters is on that section's list). Rasputin's subtunes are remapped by
its init, so the two sides are different music. The rest are single held notes
running to the window edge, where "length" is a fact about the window.

#### Three: what is actually left

The `-2` to `-7` group (46 instruments) and the `+5` to `+23` group (~38).
Neither is explained by the call-rate story, and neither has been attributed.
That is the honest remainder, and it is smaller than the raw histogram
suggested — which is the point of separating the three.

> **The transferable lesson:** a histogram of one quantity is not a population
> of one cause. Two thirds of this tail is an artefact of the trace's
> resolution, a handful is other defects being visible in a new place, and the
> genuine remainder is a fifth of what the shape first suggested. Group by
> suspected mechanism before counting, or the count will size the wrong job.


### 7.vvvv `$FD` ends a voice's list, in the three players that say so

v0.5.250, finishing § 7.qqqq. Rasputin's orderlist step, read with the
disassembler committed in v0.5.242:

    C094  LDY index,X / LDA (ptr),Y / CMP #$FF / BEQ stop
    C09D  CMP #$FE / BNE +
    C0A1    INC index,X / INY / LDA (ptr),Y        ; ...the operand
    C0A7    STA $C539 / STA $C53A
    C0AD    INC index,X / JMP $C094                ; and keep reading
    C0B3  + CMP #$FD / BNE + ; JSR $C003 ; JMP $C3C5   ; this voice is done

Two corrections in one reader. **`$FD` ends a voice's list**, where
`tracks.py` read anything `<= $FD` as a pattern number; and **`$FE nn` is a
two-byte command that *continues* the list**, where it read `$FE` as "tune
ended". The operand goes to a second gate --

    C012  DEC $C53A / BPL + / LDA $C539 / STA $C53A / JMP $C3C5

-- so it is a **tempo change mid-orderlist**, decoded here and not emitted:
Goattracker would need a tempo command in the pattern to express it.
(Emitted since v0.5.264, § 7.ddddd -- which also corrects what that gate is:
it is the *outer* counter of § 7.rrrr, so the operand scales the row rather
than being it.)

#### The near-miss, which is the useful part

Applied to all of versions 0/1/3, this rewrote **23 files and broke the
byte-exact `Commando.sng`**. `$FE` really is "tune ended" in the rest of the
family -- that is what `legalise_restarts` exists for -- and Rasputin is a
variant. Exactly the trap CLAUDE.md states as *a constant read from one player
is a constant about one player*, arrived at from the other direction: not a
constant this time but a **terminator**.

Gated on each player's own reader instead. Anchoring on the file was not
enough -- `CMP #$FD` appears somewhere in plenty of players -- so the probe is
the 48 bytes after the reader's `CMP #$FF`, which is where a dialect keeps its
other terminators. Three corpus files test `$FD` there: **Knucklebusters,
Rasputin and Tarzan**, and of those only Rasputin has the two-byte `$FE`.
Three files' bytes change and no other file moves by a byte.

    Rasputin        melody 39 -> 71%   seq 38 -> 71%   wave 32 -> 43%
    Knucklebusters  unchanged on its traced subtune
    Tarzan          unchanged at 99%

Rasputin's three voices index **one shared stream** at different offsets, so
voice 0 was reading straight through voices 1 and 2's data -- 106 bytes emitted
for a ten-entry list -- and voice 2, whose list *opens* with `$FE`, came out
empty and silent in every subtune. Two things to hold against the 32-point
gain: its `retrig` is now 1.81 (1332 attacks against 735) where it was 197, so
it has gone from far under to somewhat over; and its traced subtune is the
remapped one of § 7.qqqq, so the *level* is unreliable even though the
movement, measured identically both times, is not.

No preset moved, corpus-wide -- 0 gained, 0 lost.

#### How it was found

Not by looking for it. `hold` (§ 7.uuuu) reported Knucklebusters' `$00F8`
sounding 959 frames over **2 notes** against the original's 9 over **94**, in a
histogram of note lengths. A voice that never retriggers is not a note-length
defect, and following that back reached the orderlist.

> **The transferable lesson:** a terminator is a dialect, like a constant. And
> when a fix's blast radius is an order of magnitude larger than the evidence
> for it -- 23 files changed on a reading taken from one -- that is the
> measurement telling you the rule is scoped wrongly, before any of the numbers
> are even looked at.


### 7.wwww The census's remainder, partitioned

v0.5.251. After the `$01`, `$04` and `$80` groups closed, thirteen `flat`
instruments were left with no attribution. Grouped by *cause* rather than by
effect byte, they are four different situations and only one is a new
mechanism.

**Three are already decoded and deliberately unemitted.** Chicken Song `$0900`
and Hollywood or Bust `$0800` and `$0A00` all read `tri noi tri noi` against
our `tri tri tri tri`, and all three files report `wave_alternate_noise` — bit
`$02`'s *derived* dialect of § 7.iiii, which gains Chicken Song and costs
Hollywood or Bust eleven points of melody. Nothing new here; the census is
re-reporting a decision.

**Four are an option detected and not selected.** IK+ `$0A56` (`+7 $14`) has
`effect_two_stage` and no `--two-stage` in its preset — forcing it raises
`onset` and costs 13 points of melody, which `keeps_notes` refuses. Wiz's two
`$01` instruments are its wave-program gate, declined on the same grounds
(§ 7.nnnn). These are the search disagreeing with the census, which is the
search's prerogative.

**One is a detection gap in a file that has the routine elsewhere.** Mega
Apocalypse `$0848` carries `+7 $44` — bit `$04`, the two-stage attack — and
`effect_two_stage` is False for that file.

**Three are one new mechanism, in one player.** Ninja has no effect routine
detected at all, and its `$CAFD`:

    CAFD  LDA effect / AND #$02 / BEQ out
    CB04  LDA $CC5A,X          ; per-voice frame counter
    CB07  CMP $CC66,X          ; ...against a per-voice threshold
    CB0A  BCS +                ; past it -> the record's own waveform
    CB0C  LDA $CC63,X          ; ...before it -> an alternate
    CB12  + LDA $CC2B,X
    CB15  AND $CC5D,X / STA $D404,Y

Neither table is ever written — they are static player data, three bytes each,
one per voice:

    alt    $CC63   11 81 15      triangle, noise, triangle+pulse
    thresh $CC66   04 06 04      frames
    mask   $CC5D   FE FE FE      the gate cleared

So bit `$02` here is **a two-stage attack whose parameters are per *voice*, not
per instrument**: for the first `thresh[voice]` frames the voice sounds
`alt[voice]` with the gate off, then the record's own. It matches the trace
exactly — `$083A` plays on voice 0, `alt[0]` is `$11`, and the original reads
`pul tri tri tri` with the triangle lasting four frames.

**Emitting it needs something this converter does not have.** A wavetable is
per instrument and these parameters are per voice, so the entries can only be
written for an instrument that plays on exactly one voice — the argument
§ 7.pppp made for the bit-`$80` drum, where the routine hard-codes voice 3 and
the check was one query. Here it needs a general instrument-to-voice map built
from the patterns, and no such map exists. One file, three instruments, and a
new capability: recorded rather than built.

> **The transferable lesson:** "unattributed" is not a work item, it is an
> unsorted pile. Sorting thirteen of them by cause left exactly one that needed
> a disassembler, and told the difference between a mechanism nobody has read,
> a mechanism read and declined, and a search doing its job.


### 7.xxxx The `hold` tail is mostly the *slot*, and the rest is one cut note

v0.5.254, finishing § 7.uuuu. That section separated the column's tail into a
call-rate artefact, six far outliers that are other defects wearing a length
costume, and an unattributed remainder of 46 instruments at -2..-7 plus ~38 at
+5..+23. It could not attribute them because the histogram asked one question
where there are two: **is the note shorter, or is its slot?**

`sound_runs` measures the frames a note keeps a waveform selected *within its
own slot*. A note that fills the room it is given is not a note-length defect
at all -- what differs is when the next note arrives, which is a timing
question `--pace` and `retrig` measure and no wavetable edit can fix. So
`sound_note_runs` now reports `(held, slot, total)` per note, `sound_runs` is
its `held` reduction and unchanged, and `fidelity.py --hold-census PATH`
classifies every instrument the column compares:

    match  90  20.8%     fetch 211  48.8%     slot 117  27.1%
    thin    3   0.7%     sparse  1   0.2%     gap    1   0.2%
    short   3   0.7%     long    6   1.4%                      (432 total)

* `fetch` -- one frame short in an equal slot: Goattracker's next-note fetch,
  `gatetimer & $3f` play calls early. 211 of them, and `--no-test-restart`
  removes every one: 44 of the 46 instruments in files carrying it are `match`
  against 2 of 190 in the files that do not.
* `slot` -- the length difference *is* the slot's difference, within a frame.
* `thin` -- fewer than four notes a side. A mode over one note is that note.
* `gap` -- the sides sound for the same number of frames in total, but one of
  them drops the waveform for a frame in the middle and `held` stops at the
  first hole. A fact about the reduction, not about the music.

Where both a `slot` and a `fetch` reading fit, `slot` wins: a note one frame
short in a slot one frame short is over-determined, and above `-S3` the fetch
costs a fraction of a frame, so the slot is the reading that can be true at
every rate. That precedence moves 20 instruments out of `fetch`, all at `-S3`.

#### The old groups, re-read

    delta       match  fetch   slot   thin sparse    gap  short   long
    0              90      0      0      0      0      0      0      0
    -1              0    211     20      0      0      0      0      0
    -2..-7          0      0     50      0      0      0      2      0
    +5..+23         0      0     25      0      1      1      0      5

**§ 7.uuuu's 84 unattributed instruments are 75 `slot`, 5 `long`, 2 `short`,
1 `gap` and 1 `sparse`.** And `slot` is not a new mystery: it is the retrigger
disagreement seen in the length axis. For **94 of the 117**, the file's median
`our_slot / orig_slot` is the reciprocal of its own `retrigger_ratio` within
25% -- Ninja's five instruments are all at 0.75 against a `retrig` of 1.33,
Proteus's ten at 0.89 against 1.13, Warhawk's seven at 0.89, Spellbound's four
at 0.67. A single ratio shared by every instrument of a file is a tempo
signature, not seven independent note-length bugs.

#### What is actually left: nine instruments, and five are one mechanism

    file                       ADSR    eff   held    slot   notes
    Skate_or_Die_intro        $08E7    $01   7/23   20/24  149/123
    Arcade_Classics           $09F9    $01  10/23   24/24   73/74
    IK_plus                   $08D8    $08   6/17   18/18   93/93
    IK_plus                   $09F8    $08   6/17   18/18   62/64
    Trans-Atlantic_Balloon    $0AF8    $14   5/11   12/12   70/70

Equal slots, equal note counts, and we sound two to three times as long. The
traces say why -- the original kills the waveform partway through the note and
stays killed:

    IK+ $08D8       11 81 11 40 80 80 08 08 08 08 08 08     (slot 18)
    Arcade $09F9    11 81 41 41 81 80 80 80 80 80 00 00 ... (slot 24)
    Trans-Atl $0AF8 11 11 11 11 11 00 00 00 00 00 00 00     (slot 12)
    Skate $08E7     11 81 41 41 80 80 80 00 00 00 00 00 ... (slot 20)

`$00` or `$08` -- no waveform selected, gate and test bit alone -- written by
the player and held to the next note. We hold the last waveform instead. Three
different effect bytes across four files, so this is not an effect bit: it is a
terminating step the wavetable emitters do not write. **That is the queue item
this census exists to produce**, and it is worth noting what it is worth: nine
instruments of 432, where the raw histogram suggested eighty-four.

The remaining four are one apiece. Pandora `$0D99` sounds one frame a note
against our 63 in a slot eight times longer -- a retrigger question wearing a
length costume, like the rest of `slot` but too far out for the tolerance.
Shockway Rider `$0079`, Human_Race `$0E00` and I_Ball `$0999` all have slots
that differ by more than their held frames do.

> **The transferable lesson, and it is § 7.uuuu's sharpened:** grouping by
> suspected mechanism is not enough if the quantity itself confounds two
> mechanisms. `hold` measures a note's frames *and* its slot in one number, so
> no partition of that number could separate a length defect from a tempo
> difference. The fix was to measure the second quantity, not to bin the first
> more cleverly.

### 7.yyyy The two-stage block in zero page: Mega Apocalypse's `$44`

The census's remainder (§ 7.wwww) left one entry filed as a plain detection
gap: Mega Apocalypse's instrument at `+7 = $44` sets bit `$04`, the file has
every other effect routine, and `det.effect_two_stage` was `False`. It is the
same block, spelled shorter.

`TWO_STAGE_SHAPE` (§ 7.hh) is IK+ `$E38B`, and the corpus files that match it
share it byte for byte, per-voice counter and all, in **absolute,X** (43 files
before this change, 44 after — the "34" several older notes quote predates
v0.5.236's stride-16 lift and is stale wherever it still appears):

```
E38F  BD FC E7  LDA counter,X
E394  DE FC E7  DEC counter,X
E3A0  9D 8F E5  STA wavslot,X
```

Mega Apocalypse `$4DDA` keeps those three cells in **zero page**, so each
instruction is a byte shorter and the pattern misses from its fourth opcode
on:

```
4DDA  A5 EC     LDA $EC
4DDC  29 04     AND #$04
4DDE  F0 11     BEQ $4DF1
4DE0  B5 E0     LDA $E0,X        ; BD ?? ?? in the other 34
4DE2  F0 08     BEQ $4DEC
4DE4  D6 E0     DEC $E0,X        ; DE ?? ??
4DE6  B9 A4 54  LDA $54A4,Y      ; still running -> the attack waveform
4DE9  4C EF 4D  JMP $4DEF
4DEC  B9 FD 53  LDA $53FD,Y      ; expired -> the instrument's own +2
4DEF  95 C6     STA $C6,X        ; 9D ?? ??
```

Nothing else moves. Both table loads are still absolute, `$53FD` is still the
records' `+2` (the byte goatwriter already emits as the waveform), and the
note-start push chain still names `$54A6 = attack + 2` — so the file passes
the same *independent* second reading every other member of the family does,
which is what makes this a spelling rather than a looser pattern.
`TWO_STAGE_SHAPE_ZP` is that block; the attack operand sits at `+11` rather
than `+13`, hence `attack_at` in `_find_two_stage`.

**The blast radius is the check, and it is one file.** Run over the corpus
beside the old shape, the new one matches `Mega_Apocalypse.sid` and nothing
else, and matches no file the absolute shape already had — pinned in
`tests/test_two_stage.py` as a count, not merely as a match, because a second
spelling is a claim about which files it reaches. Byte-hashing all 95
conversions under the shipped presets moves exactly that one file.

**What it bought, and what it did not.** The reading alone changes the file's
bytes and moves no dimension of `FIDELITY.md`: `_bound_instruments` ends the
instrument table where the array begins and the count falls 43 → 21, dropping
21 phantom records whose ADSR was read out of duration bytes. No pattern
references them (the highest real reference is instrument 18; the one dangling
`$43` was dangling before), so the A/B is the honest "no dimension this report
measures can see this change" — smaller output, same music.

The *emission* is behind `--two-stage`, and with it on:

| | onset | wave | our noise frames | melody |
|---|---|---|---|---|
| without | 86% (6/7) | 76.6% | 1150 | 0.9987 |
| with | **100% (7/7)** | 79.4% | **1354** | 0.9987 |

against the original's **1444** noise frames — the deficit falls from 294 to
90 — and `noise_run_orig_only` from 1 to 0, the missing run appearing. Three
records carry `$44`, all three heavily played, and each opens on `$81` (noise)
for two frames over a `$11`/`$17`/`$15` body: a noise attack transient, which
is exactly what `onset` and the noise count are built to see.

> **The transferable lesson** is § 7.qqqq's, in a fourth place: *a walk or a
> pattern that assumes an addressing mode has assumed a dialect.* `find_wave_program`
> stepped 3 for a `STX abs` and lost the one file that stores to zero page;
> `_burst_cutoff_start` did the same; this pattern spelled three cells
> absolute and lost the one file that keeps them in zero page. The tell is
> identical every time — a file that has the surrounding machinery and reads
> as having none of it — and so is the check: run the old pattern beside the
> new one over the corpus and require the difference to be exactly the files
> you meant.
>
> A second one, cheaper: **a test can encode a defect as an invariant.**
> `test_a_flag_that_changes_nothing_is_not_recorded` asserted that Mega
> Apocalypse's `two_stage` is inert, with "its player sets no
> `effect_two_stage`" written into the docstring as the reason. The greedy
> preset walk had selected that flag and `prune_inert` had dropped it; the
> walk was right and the detection was missing. The test now pins the
> behaviour (`prune_inert` drops what the bytes cannot tell from a default)
> on `initial_instrument`, which is inert on that file, and asserts that
> `two_stage` survives.


### 7.zzzz The census's only `wrong` was two records sharing an ADSR pair

v0.5.253. `fidelity.py --census` reported one instrument in the whole corpus as
`wrong` — Nineteen's `$0B06`, effect `$A0`, original `noi -- -- --` against our
`pul noi pul pul`, on 267 of the original's attacks against 115 of ours. The
handoff filed it as "a second placement rule for the bit-`$80` drum: its hit
lands at offset 0, not 1", with the caveat that the modal shape was thin
evidence. It was thinner than that: **the shape is not one population.**

Split by shape rather than reduced to a mode, the original's voice 3 has

| shape | n | notes |
|---|---:|---|
| `noi -- -- --` | 151 | `C#6` ×151 |
| `pul noi pul pul` | 113 | `F-2` ×52, `A#2` ×18, `C-3` ×15, … |

Two things, not one. The 113 are bass notes and their shape is **exactly what
we emit**. The 151 are all one note — `C#6`, which is `$482D`, which is the
drum's own `$48` pitch high byte. They are not note onsets at all; they are the
drum ticking, named as notes by siddump because of its keyoff-keyon rule
(`siddump.c:434-437`): a bare note is printed when the waveform reaches `>= $10`
with the gate set and the *previous* frame's waveform was below `$10`. Between
hits this instrument holds `$01` — gate on, no waveform — so every `$81` tick
satisfies it.

The census keys by ADSR pair, and the instrument table says why that merged
them:

```
rec 0  80 02 41 0B 06 00 84 A0     <- +2 $41, pulse bass with the drum over it
rec 4  80 04 01 0B 06 00 84 A0     <- +2 $01, the drum ALONE
```

Same envelope, same effect byte, two instruments. `instrument_stamps` already
detects this on our side and records `ambiguous`; the census does not print it,
and the original's side is not checked at all. The mode picked the larger of the
two populations (151 > 113) on one side and the only one we emit on the other,
and reported the comparison as a wrong waveform.

**What was actually wrong is that record 4 emitted nothing.**
`_sfx_drum_entries` opened with

```python
    if not wave & 0xF0:
        return None
```

on the reasoning — recorded in the docstring, and correct as far as it went —
that `(wave & 0xFE) | 0x01` is `$01` for such a record, that `$01`-`$0F` are
*delays* in a wavetable rather than waveforms, and that emitting one had made
Bangkok Knights' GT 9 inherit noise from whatever played before at
`freqtbl[0]` = `$0117`. True; and the conclusion drawn from it — decline the
record — silenced a drum rather than mis-pitching one. Nineteen's record 4 is
58 pattern rows, and its GT 5 shipped as `01/00 01/00 01/00 FF/00`: three
one-call delays and a stop, no waveform, no drum, for the project's life.

The encoding that was missing is the one `_wave_byte` has provided since
v0.5.237: `$E0`-`$EF` writes `$00`-`$0F` to `$D404` as the control bits they
are (`gplay.c:527`). `$E1` is the `$01` the player holds. The table becomes

```
  28: E1 00     gate alone, the played note
  29: 81 C9     noise at C#6 -- $482D, the drum's own pitch      <- loop target
  30: E1 00
  31: 03 80     ...for the rest of the six-frame period
  32: FF 1D     jump to 29
```

which is the original's `$81 $01 $01 $01 $01 $01` frame for frame, and — because
`$01` is below `$10` — makes siddump name our ticks as notes exactly as it names
the original's.

Five corpus files carry a bit-`$80` record with no waveform of its own; the
change reaches exactly those five and no others (byte-hash over all 95). Three
have such a record in a played pattern:

| file | melody | seq | retrig | onset | noise |
|---|---|---|---|---|---|
| Nineteen | 77% → **96%** | 78% → 97% | 0.76 → **1.00** | 80% → **100%** | 1502 → 1657 / 1865 |
| Bangkok Knights | 96% → 96% | 88% → **97%** | 0.86 → **1.01** | 100% | 1447 → 1543 / 1640 |
| Pandora | 96% → **98%** | 96% → 99% | 0.97 → 1.03 | 86% | 812 → **839** / 877 |

No dimension moved down on any file. The note counts move *toward* the
original's rather than away (Nineteen 495 → 650 against 652), which is the check
CLAUDE.md asks for whenever an agreement column rises: a change that deletes
events the column scores raises it too.

The other two files — Mega Apocalypse's records 33 and 37 and Trans-Atlantic's
record 18 — carry `+2 $00` and **are named by no pattern row**, so their bytes
changed and nothing about them was measured. `$00` is the one case this section
does not settle: `(wave & 0xFE) | 0x01` gates the held frames on, and whether
the player leaves such a record's gate *off* between hits is a question no
corpus file can answer, because no corpus file plays one. Left as the
pre-existing rule rather than changed on a guess.

Three lessons, and the first two are the reason the fix took a session rather
than a paragraph:

> **A modal reduction over a key two records share is a comparison between two
> different instruments.** `onset`'s ADSR key is a verbatim copy of the record,
> which makes it a good key and not a unique one. The census flags this on our
> side already; it should read the original's the same way and say so in the
> table, rather than emitting a `wrong` that names neither record.

> **siddump's "notes" are not all note onsets.** A drum whose instrument holds
> no waveform between hits produces one printed note per hit, because the
> keyoff-keyon test is about the waveform register and not about the gate alone.
> Any population read off `attack_frames` can contain them.

> **A refusal is not a neutral default** — the second instance in six versions,
> after `_wave_program_entries` refusing every multispeed file (§ 7.kkkk). Both
> were written down honestly in the function's own docstring; both read as a
> caveat rather than as the missing feature they were. The docstring says what
> the code does, which is exactly why it cannot be the thing that notices.


### 7.aaaaa A mechanism whose parameters are per *voice*, and the map it needed

§ 7.wwww ended with one instrument in one player recorded rather than built:
Ninja's bit `$02`, an attack waveform held for a threshold number of frames
where **both parameters are per voice**. Every other effect table this
converter reads is indexed by `i * instr_stride`; these two are three bytes
each, indexed by the voice the player happens to be servicing:

    CAFD  LDA effect / AND #$02 / BEQ out
    CB04  LDA $CC5A,X          ; frames since this voice's note started
    CB07  CMP $CC66,X          ; ...against a per-voice threshold
    CB0A  BCS +                ; past it -> the record's own waveform
    CB0C  LDA $CC63,X          ; ...before it -> a per-voice alternate
    CB12  + LDA $CC2B,X
    CB15  ++ AND $CC5D,X / STA $D404,Y

    alt    $CC63   11 81 15      triangle, noise, triangle+ring
    thresh $CC66   04 06 04

Neither table is written anywhere in the file, so both are player data. The
`DD` at `$CB07` is what makes the block unambiguous -- an indexed *compare*,
not an immediate, which is the instruction that says the threshold is per
voice and not a constant. Corpus-wide the signature matches exactly one file.

**The map.** A Goattracker wavetable belongs to an instrument and there is no
per-voice one, so an instrument played on two voices has two right answers.
`tracks.instrument_voices` builds `{instrument: {voice: rows}}` from the
finished orderlists and patterns -- every voice whose orderlist reaches a
pattern, weighted by how often it reaches it, which is the same weighting
`_drum_max_steps` takes over durations (§ 7.ccc). It is sound because
Goattracker's instrument column carries forward *within* a voice
(`gplay.c:914`): an instrument sounding on a voice always has a set-site on
that voice's own patterns, so the map cannot under-report.

The first version then refused any instrument the map gave more than one
voice. Measured, that was the wrong rule: Ninja's GT 12 is played on voices 1
and 3 and refusing it left `onset` at 60% where taking its busier voice puts
it at 80%, with `melody`, `seq`, `noise`, `adsr` and the rest unmoved. The
reason the guess is cheap is visible in the table it indexes -- the two
alternates are `$11` and `$15`, triangle either way, so the wrong half of the
guess is wrong about the ring bit and right about the waveform.

**Two derivations turn the threshold into a number of our play calls, and
neither is the threshold.**

*The `- 1`.* The counter is zeroed at note start and incremented once per
call, and the note-start path **jumps straight past the effect block**
(`$C95C JMP $CB51`, the increment itself). So the first call that reaches the
comparison reads 1, not 0, and the attack lasts `threshold - 1` of the
player's calls. Three traces separate that from the obvious reading: the file
as it ships sounds the alternate for four displayed frames on voice 3
(`threshold` 4 -- which reads as "threshold frames" and is wrong), a copy
patched to `threshold = 1` sounds it for **none at all**, and a copy with the
alternate's table load redirected to the counter (`BD 63 CC` -> `BD 5A CC`)
prints the counter itself into `$D404`. The second is what refutes the first.

*The `(O + 1) / O`.* That probe printed `1 1 2 3 4 4 5` on consecutive frames,
which is not a counter incremented once a frame. It is the **outer gate**:
`$C806 DEC $CC59 / BPL / LDA #$03 / STA / RTS`, the `RTS` spelling § 7.tttt
added, doing nothing at all on one call in four. Our player has no such
counter, so `n` of the original's working calls occupy `n * (O + 1) / O` of
ours -- the correction `SongSpeeds.exact_row` makes to a row length, made to a
table entry (`_gate_calls`). It is **not** conditional on `--skip-gate`: that
option is about how long a *row* lasts, while a wavetable entry lasts a play
call and a play call is a frame whatever the tempo says.

Ninja is also the file that forced `outer_gate_skip` to exist beside
`SongSpeeds.skip_for`. The two gates are independent readings, and at the time
this player appeared to have only the outer one -- `find_song_speeds` returned
None for it, so the counter was unreachable through that path. It had the
inner gate all along, spelled with an immediate reload; § 7.eeeee reads it,
and the separation stands on its own terms rather than on this example.

**Measured**, `-t 60`, against its shipped preset:

| | onset | slides | bend | vib | wave | melody |
|---|---|---|---|---|---|---|
| without | 40% | 986/1338 | 0.71x | 0.58x | 59% | 85% |
| with | **80%** | **1026**/1338 | **0.75x** | **0.79x** | 58% | 85% |

`melody`, `seq`, `pitch`, `retrig`, `noise`, `adsr`, `nrun`, `hold`, `tail`,
`pul`, `filt` and `cut` are all unmoved to the printed precision. The three
ratio columns are what chose the gate correction over the bare `threshold`:
both give 4 for a threshold of 4, which is every threshold this corpus reaches
-- they part company only at Ninja's third voice, whose 6 is `_gate_calls(5) =
7` against 6, and no instrument is played there. So the arithmetic is what
makes the correction a reading and the ratios are what make it a measurement.

Blast radius, both directions: with the option off no corpus file's bytes
move; with it forced on every file, exactly `Ninja.sid` moves. That is why it
is in `presets.FIXED` rather than in `FIDELITY_TOGGLES` -- a sixth toggle
would double a four-hour search to settle a one-file question.

> **The transferable lesson:** a duration read out of a player is in that
> player's calls, and two things can stand between those and ours -- a call
> the player skips, and a call it makes without running the block. Both were
> present here, in opposite directions, and each on its own gives a wrong
> answer that looks reasonable. The probe that settled them was not a better
> argument, it was redirecting one `LDA` so the counter printed itself.


### 7.bbbbb The terminating step: what `$85` restores, and the one byte the packed player will not write

§ 7.xxxx's hold census left nine instruments, and named five of them as one
kind: an equal slot, an equal note count, and **we sound two to three times as
long** because the original kills the waveform partway through and stays
killed. Read rather than inferred, they are two different things, and the fix
for the larger one is a byte the encoding could not deliver.

**What the original actually plays.** Traced per note, both sides, at the
instrument's own ADSR:

    IK+ $08D8   orig  11 81 11 40 80 80 80 80 80 40 40 40 08 08 08 ...
                ours  11 81 11 40 80 80 80 80 80 10 10 10 10 10 10 ...
    Skate $08E7 orig  11 81 41 41 80 80 80 00 00 00 00 00 00 00 00 ...
                ours  11 81 41 41 80 80 80 80 10 10 10 10 10 10 10 ...

Both diverge at the frame the wave program ends, and they diverge differently.

**`$85` does not freeze the last waveform.** The interpreter writes two
different cells (IK+ `$E348`): a `>= $80` opcode stores to `$E5E7,X`, the cell
the per-frame writer copies to `$D404`, while a `< $80` opcode stores to
`$E58F,X`, the voice's *stored* waveform. The hold jumps to `$E44C`, which is
`LDA $E58F,X / AND gate,X / STA $E5E7,X` -- so the voice reverts to the last
`< $80` opcode's waveform. IK+'s program is `81 11 40 80 80 80 80 80`, and the
three frames of `$40` after it are opcode 2's, not the record's `+2`. v0.5.203
restored `+2` there, which is right only for a program that never ran a `< $80`
opcode at all.

That is the measurable half: restoring the stored cell moves `wave` on **16 of
21 files** for a mean **+1.2 pp** -- ACE II 83 -> 87%, Saboteur II 84 -> 88%,
Bangkok Knights 40 -> 43%, Thundercats 83 -> 85%, Shockway Rider 80 -> 82%,
Nineteen 43 -> 45%, Mega Apocalypse 79 -> 81% -- with `melody`, `seq`,
`retrig`, `pitch`, `adsr`, `onset`, `hold` and everything else unmoved on every
file.

**And where that stored cell selects no waveform, the original goes silent.**
Skate or Die intro and Arcade Classics both end on `slide $00`; Trans-Atlantic's
`$0AF8` carries `+2 $00` and reaches the same state through
`_two_stage_pitch_seq_entries`. All three sounded a released waveform for the
rest of the note where the original sounds nothing.

**The byte that says so is not `$E0`.** The editor reads `$E0`-`$EF` as "set
the waveform to `$00`-`$0F`" (gplay.c:527), and that is what this converter had
been told. `gt2reloc` rewrites the range on the way out
(`greloc.c:1270-1271`): it takes the low nibble, and then adds `$10` back
**only if the song uses a wavetable delay at all** (`nowavedelay`, computed at
`greloc.c:829` over the rows an instrument actually reaches). A song without one
therefore ships `$E0` as a literal `$00`, and the player it is built with reads
a zero byte as *no wave change* (`player.s:944`). The entry writes nothing and
the previous waveform keeps sounding.

That is not a reading of the source, it is what the two files do. Skate's packed
table carries the entry as `00` and its trace holds the `$80` before it;
Nineteen -- whose song does use delays -- carries `$E1` as `$11` and writes the
`$01` it means, which is why § 7.zzzz's drum works. One encoding, two outcomes,
decided by a property of the whole song.

So a waveform of `$00` is emitted as **`$18`**: triangle with the test bit,
which holds the oscillator in reset and outputs nothing. Both players write it,
no song-wide flag can quietly discard it, and it is the same argument
`FIRSTWAVE_TESTBIT` (`$09`) already rests on.

**No column in FIDELITY.md can confirm that half.** `hold` counts frames with a
*waveform nibble* selected, and `$18` has one; `wave` compares the waveform
class, and triangle-against-nothing is a disagreement whichever silent form we
write. The five instruments' `hold` figures are unchanged -- 0 files moved --
and they are supposed to be. What moved is `noise`, on the two files whose
spurious frames were noise: Arcade Classics 1085 -> **1011** against the
original's 1004, and Skate or Die intro 1231 -> 1122 against 1283. The second
looks like a regression and is the shape CLAUDE.md already warns about: `noise`
is a one-sided *count*, the frames removed are frames the original does not
have, and a count moving away from a total says nothing about where its frames
sit.

**Two of the five are not this mechanism at all.** IK+'s two instruments end
their notes *before* the program ends -- the trace goes to `$08`, and `$08` is
what `$E138` writes into the stored cell on a rest, six or twelve frames into an
eighteen-frame slot. That is a note-*length* difference, and no per-instrument
wavetable can express it: the same instrument is played with two different
lengths in the same tune. It stays open.

> **Closed by § 7.fffff, and the second clause is where it went wrong.** The
> length is not the instrument's: bit 6 of the status byte is a *rest*, this
> player silences on it, and the pattern data carried the cut all along. What
> could not express it was the wavetable, which is where this section was
> looking.

> **The transferable lesson:** an encoding is only as good as the *packer's*
> reading of it. Both halves of this were beliefs about a table byte -- one
> taken from the interpreter's own store instruction, one taken from the
> editor -- and the second was true in the editor and silently false in every
> packed `.sid`, conditional on a property of the song rather than of the
> instrument. Read `greloc.c` next to `player.s` before trusting a range, and
> settle it by looking at the packed bytes.

#### The settings this changed under, re-measured

v0.5.265 shipped the corpus artefacts with a caveat: the 45 `--fidelity`
settings in `presets.json` were **carried forward**, and 21 of them are
`--wave-program` songs whose emitter this section had just changed. A setting
chosen against an emitter that no longer exists is not a measurement, so the
four-hour search was re-run at v0.5.266 -- 83 songs, 31 combinations each, at
the 60 s window the report is published at.

It reproduces the shipped file **byte for byte apart from the generator
stamp**: 0 settings gained, 0 lost, the same 45 songs, the same structural
choices (`max_rows`, `pack`, `prune`, `dedup`, `multiplier`) on every one of
the 83, and no song's search failed. The distribution is `two_stage` 36,
`wave_program` 21, `pitch_seq` 10, `no_test_restart` 9, `sfx_drum` 7.

That is a result rather than a formality, and specifically it is *this*
result: all 21 `--wave-program` songs keep the option. The correction changed
what those files emit and did not change what the search wants for any of
them -- the terminating step is right where the option was already selected,
and it is not enough to make the option worth selecting anywhere it was not.

**A file cannot say which of the two it is.** `presets.json` records the same
bytes whether a setting was measured this hour or inherited from a converter
six versions old, so the distinction only ever lives in a commit message and
in a paragraph like this one. Check the diff, not the file: `0 gained, 0 lost`
is the only shape that says a carry-forward was safe, and v0.5.235's search
came back `1 gained, 7 lost` from the same-looking file.

### 7.ccccc The same player's bit `$01`, and 219 noise frames it never sounded

§ 7.aaaaa read Ninja's bit `$02` as a per-voice two-stage attack and built the
instrument-to-voice map to emit it. The map's second customer was 25 bytes
above that block, in the same player:

    CADD  LDA effect / AND #$01 / BEQ out
    CAE4  LDA counter,X / AND #$01 / BEQ own   ; the per-note frame counter
    CAEB  LDA alt,X                            ; odd  -> a per-voice alternate
    CAEE  JMP store
    CAF1  own: LDA wave,X                      ; even -> the voice's own
    CAF4  store: AND mask,X / LDY voice / STA $D404,Y

    alt  $CC60   81 81 81      noise, gate on

That is `wave_alternate` (§ 7.hhhh) with its table indexed by voice instead of
by instrument -- and, like the two-stage tables beside it, never written
anywhere in the file. Three of Ninja's records set the bit, and the conversion
emitted **no noise at all**: `FIDELITY.md` read `noise 0/219` for the file.

**The branch runs the opposite way round.** W_A_R's `AND #$01 / BEQ` jumps to
the alternate and falls through to the record's own; this one jumps to the
record's own and falls through to the alternate. The counter reads 1 on the
first call that reaches the block -- the note-start path skips it, § 7.aaaaa --
so the note's *second* call sounds the alternate here and the record's own
there. Same instruction, opposite output, which is why
`_wave_alternate_entries` has taken an `alt_first` parameter since the derived
dialect needed one. Read off the branch and then measured, on the voice that
sounds it:

    2562  41   <- note onset, written by the note-start path
    2563  81   <- the alternate, on the note's second call
    2564  ..   <- the outer gate skips this call; the register holds
    2565  41   2566  81   2567  41   2568  ..   2569  81

**The gate does not change the duty cycle**, which is worth stating because
§ 7.aaaaa's other derivation turned entirely on it: over any eight frames the
original spends four with noise selected, and a wavetable alternating every
call spends four too. A held frame repeats whichever half preceded it, and the
two halves alternate, so the hold lands on each equally often. The correction
that mattered for a *duration* is a no-op for a *ratio*.

Measured, `-t 60`, against the shipped preset:

| | noise | nrun | wave | melody |
|---|---|---|---|---|
| before | **0**/219 | `-` | 58% | 85% |
| after | 387/219 | **100%** | 57% | 85% |

`melody`, `seq`, `pitch`, `retrig`, `slides`, `bend`, `adsr`, `vib`, `hold`,
`onset`, `tail`, `pul`, `filt` and `cut` are all unmoved. `nrun` going from
"nothing to compare" to 100% is the load-bearing number: it compares noise
*run lengths* and is position-independent, so it says the shape is right
independently of how many of them there are.

**The overshoot is two known things and not a third.** 387 against 219 is
1.77x, and it decomposes: 30 of our frames are on a voice the original sounds
no noise on *in this window* -- the third bit-$01 record, which our conversion
reaches inside 60 s and the original does not -- and the remaining 357 against
219 is 1.63x on the voice both play, against a tune we play **1.33x too fast**
(`retrig` 1.33, § 7.xxxx's tempo signature, and Ninja's own `find_song_speeds`
returning None). Per unit of music that is 1.22x, and no dimension here
separates the last of it from the note lengths `hold` cannot see on this file.
The honest summary is that the mechanism is now present and its rate is bounded
by a tempo defect recorded elsewhere, not that the emission is 77% too eager.

> **Closed by § 7.eeeee.** That tempo defect was the unread immediate-reload
> speed gate, and reading it took the file to `retrig` 1.00. This mechanism's
> rate came with it: 387 noise frames against 219 became **205** against 219,
> i.e. 0.94x, with no change to the emitter. The paragraph above is left as
> written because the decomposition is what predicted this -- 1.22x per unit
> of music, and what remained after the tempo fix was 0.94x.

> **The transferable lesson:** two blocks in one player, 25 bytes apart,
> reading the same counter into the same register -- and the correction that
> was essential for one of them (the skipped call) cancels exactly for the
> other. A derivation is about a *quantity*, not about a player: ask whether
> the thing being measured is a duration or a ratio before carrying a
> correction across.


### 7.ddddd `$FE nn` emitted, and the gate it actually writes

§ 7.vvvv decoded Rasputin's two-byte orderlist command and left it unemitted:
"the operand goes to a second gate, so it is a tempo change mid-orderlist;
Goattracker would need a tempo command in the pattern to express it." Both
halves of that turn out to need work — the pattern command is straightforward,
and the *arithmetic* was wrong.

#### The operand is the outer counter, not the row

Rasputin has two counters, and the command writes the one § 7.vvvv did not
identify:

    C012  DEC $C53A / BPL work / LDA $C539 / STA $C53A / JMP exit   ; outer
    C062  DEC $C536 / BPL +    / LDA $C53B / STA $C536              ; the row
    C074  LDA $C536 / CMP $C53B / BNE skip        ; ...advance on the reload

The second is the speed gate `find_song_speeds` already reads, with the
per-subtune table at `$C537`; a row lasts `reload + 1` of the calls that reach
it. The first is the **outer gate of § 7.rrrr**, spelled with a *cell* reload
where `OUTER_GATE` expects an immediate — which is why `outer_gate_skip` is
None for this file and `SongSpeeds.skip` is empty. It runs the whole routine
on `R` calls in every `R + 1`, so a row lasts

    frames * (R + 1) / R

real frames, which is exactly `SongSpeeds.exact_row`'s factor with `R` moving
mid-song.

**The implausibility is what caught it.** Read as a row length, subtune 0's
eight commands are 3, 4, 6, 11, 61, 121, 7 and 3 frames a row — and the
patterns after the 121 are the same `01 01 01 03 03 01 05 02 31` the same list
plays at 3 twenty entries earlier. Ten seconds a row on material that had just
gone past at a quarter of a second is not a tempo, it is a misreading. Under
the ratio it is 3.0, 2.67, 2.4, 2.2, 2.03, 2.02, 2.33, 3.0 — a slow open, an
accelerando that flattens out, and a return to the opening tempo for the last
four bars.

#### Where a tempo change can be said

Goattracker's orderlist carries no command, so the only place is a pattern row,
which `apply_tempo` already uses for a subtune's opening tempo. Three things
that are not obvious:

* **Always into a copy.** All three of subtune 0's first changes land on its
  pattern `$01`, at three different tempos. Patching the shared pattern would
  apply the last one everywhere. Copies are keyed `(pattern, value)` so a tune
  alternating between two tempos costs two patterns, not one per step.
* **Before `pack_repeats`, and that is why the pass lives inside
  `reindex_tracks`.** A tempo change in the middle of a run of one repeated
  pattern is a boundary the packer would fold away. Substituting a copy — a
  different pattern number — splits the run as a side effect of saying the
  thing, so no packing rule had to learn about tempo.
* **A command at position 0 is the subtune's opening tempo**, and
  `derived_group_tempos`' value for that subtune is overridden with it. Both
  writes land on row 0 of the song otherwise, one on voice 0's pattern and one
  on voice 2's, and which won would come down to the order `gplay` services
  the channels in. Agreeing them is the reading, not a tie-break: the player's
  init loads the counter from its table and the voice's first step overwrites
  it before a row is played.

Rounded, because `frames * (R + 1) / R * multiplier` rarely lands on a whole
number of calls: 2.67 frames at `-S2` is 5.33 and is written as 5. The
alternative to a rounded change is the absent one, which is what this file had
— every row 4 calls where the truth ranges from 4.03 to 6.

#### Measured

`-t 60`, shipped preset, and `Rasputin.sid` is the only file whose bytes move
(a corpus SHA-1 either side; the other two `$FD` players carry no `$FE nn`):

| | melody | seq | pitch | retrig | wave | noise | adsr | bend | pul |
|---|---|---|---|---|---|---|---|---|---|
| without | 71% | 71% | 76% | 1.81 | 43% | 1693 | 25% | 1.19x | 5012 |
| with | **75%** | **75%** | **78%** | **1.66** | **46%** | **1775** | **27%** | **1.17x** | **4887** |

Every dimension that moved, moved toward the original; `vib`, `nrun`, `hold`,
`onset`, `tail`, `filt` and `cut` did not move. The original's noise is 2190
frames and its `pul` 3155, so both of those are approaches from the same side.

**`--pace` cannot adjudicate this one**, which is worth recording because the
repo's rule is to use it for anything about tempo. It fits *one* rate to a
file, and this file's rate changes eight times: it declines both sides for
disagreeing matched notes, and its IQR widens from 18% to 29% — which is what
a correct tempo *change* looks like to a constant-rate estimator, not a
regression. The subtune correspondence was checked instead
(`--diagnose`): `s0 -> o0` at 86% on the diagonal, "the correspondence is the
identity where it is legible", so the traced pair is the right music and the
movement is about the conversion.

What is left is a level, not a direction: `retrig` 1.66 is still well above 1,
and the rounding cannot explain more than a few percent of it. The remaining
suspect is the same one Ninja has — this file's melody has been capped since
long before this change.

> **The transferable lesson:** a value written into a *counter* is not a
> quantity until you know what the counter does. The same byte is a row length
> in one gate and a scale factor in the one 78 bytes above it, and the two
> readings differ by 60x on the same operand. The check that separated them
> was not in the disassembly — it was asking whether the music the operand
> implies could be the music the patterns around it contain.

### 7.eeeee One byte of branch offset, and a tune that was 25% fast

The handoff carried "the missing inner speed gate" as the largest defect that
could be named: Ninja's `find_song_speeds` returned None, so its tempo took the
fallback constant, and § 7.xxxx's hold census had already identified the
signature — one ratio shared by every instrument of a file is a tempo, not a
length. `--pace` says it exactly:

    our row ours/theirs 0.750  (IQR 0.750-0.750 over 858 gaps; fit 0.750)

Not approximately three quarters. Three quarters on **every gap**, with an
interquartile range of zero width. A wrong constant looks like this; irregular
pacing does not.

#### The gate was there, one byte off the pattern

    C83D  DEC $CC46 / BPL +5 / LDA #$02 / STA $CC46
    C84E  LDA $CC46 / CMP #$02 / BNE skip      ; work on the reload frame

Against `SPEED_GATE`, which is

    DEC ctr / BPL +6 / LDA reload / STA ctr

The only differences are the branch offset and the addressing mode of one
load, and the second causes the first: `LDA #imm` is two bytes where `LDA abs`
is three, so the branch that skips the reload is `+5` instead of `+6`. That is
the whole defect. `SPEED_GATE_IMM` is the same shape with `\xa9(.)` where the
other has `\xad(..)`.

The reload is 2, so a duration unit is three of the calls that reach the
sequencer. Ninja also has the outer counter of § 7.rrrr (`$C806`, reload 3,
the `RTS` spelling), which works on 3 calls in every 4 — so the row is
`3 * 4/3 = 4` real frames. Four exactly: one of the few files where the
corrected row is a whole number and `encodable_frames` can return it. We were
emitting the fallback constant of 3.

#### What one byte was worth

`-t 60`, shipped preset, and the corpus byte-hash moves **only this file**:

| | melody | seq | pitch | retrig | wave | adsr | noise | pspan |
|---|---|---|---|---|---|---|---|---|
| before | 85% | 86% | 79% | 1.33 | 57% | 45% | 387/219 | 1.46x |
| after | **100%** | **100%** | **100%** | **1.00** | **88%** | **62%** | **205**/219 | **1.00x** |

`--pace` goes to `1.000`, IQR `1.000-1.000`, "0% out". The file moves from the
report's *close (80-95%)* band to *plays the same music*.

**Two of those numbers are other people's work being unblocked, not this
fix.** § 7.ccccc's per-voice noise alternation was measured at 387 frames
against the original's 219 and its author decomposed the 1.77x into 30 frames
on an unreached voice plus 1.63x on a tune played 1.33x too fast — predicting
1.22x per unit of music. The emitter is untouched here and it now reads 205
against 219, i.e. **0.94x**. A decomposition that survives the removal of one
of its terms is worth more than the number it was defending.

And `pul` moved the wrong way, 972 to 426 against the original's 1050 — which
is the count-versus-rate trap from the other side. We were striking a third
more notes than the original, each restarting a pulse program, and the surplus
was flattering a column that counts duty-cycle *movements*. `pspan`, the ratio
form of the same question, went 1.46x to exactly 1.00. **Read a count next to
both sides' note counts** (CLAUDE.md); this is that rule with the sign
reversed, where removing invented events makes a count look worse.

#### Why it is a fallback and not a competitor

35 corpus files carry `SPEED_GATE_IMM`'s shape and **33 of them already read a
gate through the absolute spelling**. What that counter does in those 33 is not
established, and `find_song_speeds` has no way to choose between two candidates
it cannot tell apart — its own docstring says a wrong tempo is worse than the
old constant. So the immediate form is consulted only where the absolute one
matched nothing: the rule `find_relocation` and `INSTRUMENT_INDEX_SHAPE`
already follow, and it is what keeps this to two files.

The second is Mega Apocalypse, which lands on **3 frames a row — the value the
fallback constant was already guessing**. Its bytes do not move. That is worth
having anyway: the tempo is now read rather than assumed, and if the constant
is ever wrong for it, the reading will say so.

#### A test was pinning the defect

`test_ninja_s_outer_counter_is_readable_where_its_speed_gate_is_not` asserted
`find_song_speeds(sid, det) is None`, two days old, written by the same hand as
the fix. It was true, and it was documenting the bug as though it were a
property of the player. It is now `test_ninja_s_two_counters_agree`, which
pins what actually has to hold: `outer_gate_skip` and `SongSpeeds.skip_for`
return the same number, because `_gate_calls` and the row length both scale by
it and disagreeing would put the wavetable on a different timebase from the
rows.

> **The transferable lesson:** a signature that encodes an *addressing mode*
> encodes an instruction length, and an instruction length is in every branch
> offset around it. Two spellings of one idiom differ by a byte in two places
> at once, and matching neither looks exactly like the player not having the
> feature. The way this was found is worth more than the fix: `--pace`
> reported a ratio with zero spread, which is a claim no mechanism can make.
> A tight ratio is a constant; a loose one is a mechanism. Read the spread
> before reading the number.

### 7.fffff The rest that silences, and a change no column can score

§ 7.bbbbb left two of its five instruments open: IK+'s `$08D8` and `$09F8`
"end their notes before the program ends", filed as a note-length difference
no per-instrument wavetable could express, because the same instrument is
played at two lengths in one tune. Both halves of that are right and the
conclusion was wrong -- the length is not the instrument's, and the
information was already in our pattern data.

#### The rest is an event, and its position varies

Voice 2's first six notes, traced, with the slot to the next gate edge:

    onset  2  slot 24:  11 81 11 40 80 80 80 80 80 40 40 40 08 08 ...
    onset 26  slot 18:  11 81 11 40 80 80 08 08 ...
    onset 62  slot 12:  11 81 11 40 80 80 08 08 ...
    onset 74  slot 24:  11 81 11 40 80 80 08 08 ...

The program is one program -- the six-frame reading is its first half. What
varies is *when* the `08` arrives, and it does not track the slot: 24 frames
of slot with 12 frames of program at onset 2, and 24 with 6 at onset 74. So
the cut is its own event, and every note's program length plus the silence
that follows adds up exactly to the next onset. It is a **rest**, and the
pattern data has always carried it.

#### Bit 6 is a rest, and 21 players make it a silence

`status_bit6` has been read for a long time: a status byte of `$C0`-`$FE`
consumes only itself, because the player tests bit 6 first and alone. What was
never read is *what the branch does*. Three answers across the 61 corpus files
with the shape:

    5118  DEC .. / LDY voice / LDA instr,X / ...          Commando, 40 files
    914A  DEC .. / LDY voice / LDA #$00 / STA $D406,Y / STA $D405,Y
                                                          Ricochet, 4 files
    E138  LDY voice / LDA #$00 / STA / STA / LDA #$08 / JMP store
                                                          IK+, 17 files

The first writes no register and goes on to the effect path -- a genuine hold,
which is what this writer already emitted. The second zeroes the envelope
pair. The third writes the testbit into the voice's stored waveform. Both of
those stop the sound, and Goattracker's `KEYOFF` is the only row this format
has that ends a note without starting one.

`--rest-keyoff` emits it, gated on `detect._find_rest_silences`. 19 corpus
files' bytes move and they are exactly the flagged population -- the other two
flagged files have no bit-6 rest in any pattern their orderlists play, and no
unflagged file moves at all. Commando is a holder, so the byte-exact fixture
cannot move.

#### And then nothing happened

| | |
|---|---|
| files whose bytes moved | 19 |
| files whose report row moved | **1**, and 3 points of `pitch` worse |

That is not a flat table to be squinted at, it is a property of the encoding:
**a Goattracker KEYOFF clears the gate bit and changes nothing else.** `wave`
ignores the gate bit by construction ("with the gate/sync/ring/test bits
ignored"). `hold` counts frames on which a voice keeps a *waveform selected*,
which a gate-off does not change. `adsr` compares the envelope registers,
which we do not rewrite. Every column that could have seen this reads a
register the change does not touch, and `--baseline` says so in as many words:
*18 of the 19 files whose converted output changed moved no number at all.*

Measured on the one axis that can see it -- frames where the original has the
voice gated off and we still have it gated on:

| file, voice | original's gate-off frames | ours ringing, before | after |
|---|---|---|---|
| IK+ v1 | 372 | 330 | **141** |
| Arcade Classics v1 | 693 | 250 | **89** |
| IK+ v2 | 1266 | 267 | 243 |
| five files, all voices | 10762 | 4606 | **3931** |

So the change does what it says, on a quantity this project has never
measured -- which is an argument for measuring it rather than for shipping on
a hand-rolled probe.

#### The gate dimension, and what it then said

v0.5.270 adds `gate`: the overlap of the frames each side has the voice
*released*, `|both off| / |either off|`, the Jaccard shape `pitch` already
uses. Scored over the gate-off frames alone, because both sides hold the gate
on for most of a tune and counting those would put every file in the high
nineties and move for nothing. Two properties written into the column rather
than discovered later -- it reports its direction (`gate_ours_ringing` against
`gate_ours_silent`, a missing note end and a note ended early being different
defects), and it **rises when notes are removed**, so it belongs beside
`retrig` and the two attack counts like every other one-sided reading here.

One flaw was caught by its own tests before it ever ran: a voice neither side
writes reads `$00` on every frame, which is gate-off on both, and three silent
voices would have scored a perfect trace. `wave_compare` drops the equivalent
frames for the identical reason and the rule was simply not carried across.

Re-run, the option it was built to see moves **12 files and all 12 upward**:

| | | | |
|---|---|---|---|
| BMX Kidz 4% -> **85%** | Auf Wiedersehen Monty 18 -> 45% | Shockway Rider 52 -> 75% | Nineteen 45 -> 56% |
| IK+ 42 -> 48% | ACE II 62 -> 68% | Trans-Atlantic 30 -> 36% | Arcade Classics 42 -> 47% |
| Thundercats 66 -> 68% | Bangkok Knights 61 -> 63% | Star Paws 25 -> 26% | I Ball 39 -> 40% |

Nothing moves down. Every other column stays flat except the 3 points of
`pitch` on Auf Wiedersehen Monty that were there before. So `--rest-keyoff` is
in `presets.FIXED` after all, and the sequence is worth keeping as the
sequence: read the player, emit it, find no column can see it, **build the
column**, then let it decide.

And the corpus number the column arrived with is the largest thing it said:
**mean gate overlap 39%** over 83 files, 160722 frames sustaining a voice the
original had released against 38790 the other way. That is a standing error
axis rather than any one file's defect, and nothing measured it for the
project's whole life.

#### And then a seventh term, so the search can see it too

A column the report prints is not yet a column the *search* reads.
`fidelity_better` takes seven one-sided questions now, `gates_right` among
them, and the two properties that matter were written in rather than found:

* **Guarded by `keeps_notes`.** A conversion with fewer notes has more
  gate-off frames and scores higher for it -- the same shape as § 7.eee's
  candidate reaching `wave` 99.5% by deleting 79 notes. The raw attack count
  refuses that, and it is the guard every term here has always had.
* **Acceptance only, never a veto.** `gate` is scored over the frames *either*
  side has the voice released, so a setting that adds releases changes the
  denominator it is judged by -- exactly the reason the oscillation ratio and
  the noise pitch are kept out of `gave_back`, where a widened veto once cost
  seven measured settings.

> **The transferable lesson:** "no column moved" has two causes and they need
> different answers -- the change reached nothing, or every column is blind to
> the register it reached. This project built four dimensions the last time it
> hit the second (§ 7.78) and did it again here. The new part is that the
> blindness was *structural*: the gate bit is deliberately excluded from
> `wave`, for a good reason, and that decision silently made an entire class
> of change unscoreable for as long as nobody made a change in that class.
> **When a column documents what it ignores, read that list as a list of
> things you cannot yet ship on evidence** -- and treat it as a queue, because
> the gap between "correct by the player's own code" and "shippable" was one
> afternoon's dimension, not a listening session.

### 7.ggggg What the 39% is made of, and a probe that lied about it

§ 7.fffff's column arrived with a corpus number: **mean gate overlap 39%**,
160717 frames sustaining a voice the original had released against 38789 the
other way. That is a measurement, not a work item -- so, exactly as `onset`
became `--census` and `hold` became `--hold-census`, `gate` becomes
`--gate-census`. One record per release the *original* makes, classified by
what the conversion did on those frames.

Corpus, 46996 releases across 83 files:

| kind | runs | share | frames we ring |
|---|---:|---:|---:|
| matched | 23607 | 50.2% | 34149 |
| held | 11385 | 24.2% | 49046 |
| short | 11060 | 23.5% | 69684 |
| retrigger | 944 | 2.0% | 936 |

**Half of every release the originals make, we already make.** That reframes
39% considerably: the column is a frame-overlap and a release we make one
frame late costs it on both ends, so a 50% *event* match reads as a 39%
*frame* overlap. The queue is the 11385 `held` -- the original rests and we
play straight through -- led by Deep Strike (415 runs, 2136 frames), Thrust
(36 runs but 1914 frames, the longest a 320-frame rest), Samantha Fox (390 /
1766) and Knucklebusters (285 / 1756).

`short` is the larger frame count and the less interesting kind: we do let
go, at roughly the right moment, and re-attack too early. That is the
next-note fetch `hold`'s census already attributes (§ 7.xxxx's `fetch`, 211
of 432), seen from the other side.

#### The probe that lied

Before the census existed I read the same question off a hand-written probe,
and it said something entirely different: that the originals release for one
frame between most notes -- 170 of Zoolook's 210 runs -- and for 4-5 frames
at rests. The census says Zoolook has **no** one-frame releases at all.

The probe traced *both* sides at the song's `-S` multiplier. The multiplier
belongs to our side only: `_measure` traces the original at `-m1`, because it
is a 50 Hz VBI tune and the multiplier is a property of what `gt2reloc`
packed. Tracing Zoolook's original at `-m3` calls its play routine three
times a frame, which plays it three times too fast and manufactures exactly
the short gate edges the probe then reported. Two files' worth of that
analysis went into a section draft before the discrepancy with the tool's own
number forced the check.

The corrected `retrigger` figure carries its own version of the lesson. The
first two files I ran the census on both read zero, and "it measures zero on
this corpus" went into the docstring; over 83 files it is 944, 2.0%. Both
halves of the bucket's account -- why it is small (siddump samples once a
frame, so an edge inside a frame leaves none) and how small -- had to be
measured rather than reasoned.

#### What the queue paid, immediately

The `held` list is led by files whose player has the `BIT`/`BVS` shape and
whose branch does *not* silence -- Thrust, Deep Strike, Knucklebusters. Those
are the 40 that v0.5.269 deliberately excluded from `--rest-keyoff`, on the
reading that they "really do hold".

That reading was about the branch. Thrust's picture says what the voices do:
at frame 109 all three gate off together and stay off for 320 frames, both
sides re-attack on the same frame at 429, and in between we hold three notes
the original had let go. The rest is a rest whatever the branch writes; the
40 reach the released state by the ordinary end-of-note path a frame earlier
instead of in the branch itself.

Forced on for all 40 and measured on `gate`: **26 up, 0 down, 14 unchanged**,
with `melody` and `retrig` unmoved on every one. Battle of Britain 21 -> 90%,
Gremlins 25 -> 89%, Thrust 47 -> 87%, Confuzion 43 -> 77%, Monty on the Run
46 -> 72%, W_A_R 0.4 -> 41%, Flash Gordon 0 -> 32%. So the gate on
`_find_rest_silences` is dropped: the emission is gated on the *shape*, which
is what says the event is a rest.

Corpus after: mean gate overlap **39% -> 44%**, ringing frames 160717 ->
142073, mean pitch 93 -> 94%, and 28 rows move with **no file worse on
`melody`, `seq` or `wave`**.

**The first measurement of this said the opposite** -- 4 of 6 better and
Knucklebusters worse -- and it was the probe of the section above, with the
original traced at the multiplier. Properly traced, Knucklebusters is 6.3 ->
13.2%, up. One bad probe produced a false finding *and* a false refutation of
the fix for it.

#### The census disagreed with its own column

Re-run after that fix, the `held` list was led by runs of a shape nothing
else in it had: Pygmies Revenge 1024 frames, Master of Magic 768, Phantoms of
the Asteroid 768, Rock Tells the Tale 752 -- all starting at frame 0, all far
longer than the 3-frame rests around them. The obvious reading was a voice
the original enters late while we play from the start.

We play nothing there. Our `$D404` reads `$00` for every one of those frames:
no waveform, no gate, a voice the conversion never writes either. `gate`
scores that against the original's release as **agreement**, and the census
called it `held`, because the nonzero guard `gate_runs` needs on the
*original's* side -- a voice it never plays is not a release it makes -- had
been copied onto ours as well. 38 runs and 8889 frames, every one of them a
voice neither side had entered.

The rule the repo already states for `--census` is that its `match` count
*is* the column's numerator. This broke the same rule in the other
direction, and nothing failed: the census's own tests passed straight through
it, because none of them had a voice on our side that was never written. That
test exists now.

#### What the queue is, after both fixes

| kind | runs | share | frames we ring |
|---|---:|---:|---:|
| matched | 24165 | 51.4% | 35502 |
| short | 10742 | 22.9% | 50631 |
| held | 11145 | 23.7% | 36851 |
| retrigger | 944 | 2.0% | 865 |

**And `held` no longer has a tail.** Its longest run across the corpus is 29
frames (Deep Strike); Samantha Fox's longest is 4, Kings of the Beach's 4,
Dragons Lair's 3. 11145 runs over 36851 frames is an average of **3.3
frames**, which is not a rest we failed to read -- the bit-6 rests are read
now -- but a note that ends a few frames before the next one begins.

That is the note-*length* axis, which `hold` already owns and whose own
census attributes 211 of 432 instruments to Goattracker's next-note fetch
(§ 7.xxxx). The two columns are looking at one defect from opposite sides:
`hold` sees a note a frame short, `gate` sees the silence after it missing.
So the gate queue is not a separate mechanism to find, and saying so is worth
more than another list of files.

> **The transferable lesson:** the tool and the probe disagreed, and the
> probe was wrong in a way that *looked* like a finding -- a clean bimodal
> distribution with a mechanism-shaped story attached. What caught it was
> that the two numbers could not both be true, not that either looked
> suspicious. Build the census into the harness that already resolves the
> subtune, the multiplier and the startup lag correctly; a probe re-derives
> all three and only has to get one wrong.

### 7.hhhhh The next-note fetch, and the two calls that were a whole frame short

`hold`'s census attributes 211 of 432 instruments to it and `gate`'s the bulk
of 11145 held runs averaging 3.3 frames: Goattracker fetches the next note
`gatetimer & $3f` calls early and holds the gate off for them. Two columns'
residue, one mechanism.

The option that removes it, `--no-test-restart`, has been off since it was
measured: 21 points of melody across 68 files. Re-measured now that `gate`
and `hold` exist, forced corpus-wide, it is stranger than that:

| | melody | seq | pitch | onset | hold | gate | wave | nrun |
|---|---|---|---|---|---|---|---|---|
| files | 68 | 68 | 64 | 25 | 49 | 63 | 72 | 22 |
| mean | -26.3pp | -26.7pp | -15.6pp | -40pp | **+69.9pp** | +3.1pp | +3.0pp | +32.4pp |

Delta Mix-E-Load goes melody 100% -> **0%**. Not a rounding of a naming rule:
siddump prints a note when the waveform reaches `>= $10` with the gate set
*after a frame below `$10`* (siddump.c:434-437), and the testbit frame this
option removes is the only frame our conversions spend below `$10`. Take it
away and every attack becomes invisible to the instrument, which is why four
columns collapse while four others leap.

The originals need no such frame because they **gate off at the end of every
untied note** -- the fact the whole gate story rests on. Our conversion does
not, so the testbit frame is standing in for a release we never make. The
option is not the lever; the release is.

#### The release we do make is two calls long

Goattracker has one, and this writer has always set it to **2 calls**. At
`-S1` that is 2 frames. At `-S3` it is two thirds of one, and at `-S5` two
fifths -- against the players' own 3.3. It was a constant where every other
rate in this file is `frames * multiplier`, and the multispeed half of the
corpus has been getting a release too short to sample.

`HARD_RESTART_FRAMES` is 2 frames, converted like everything else, and
bounded twice:

* **gplay.c:334 stops the song outright** when the gatetimer exceeds the
  channel's tick. It is a correctness bound and the failure is total: swept
  past it, Commando reports 3 attacks against 716 and Sanxion 1 against 956.
* **Half the row**, which is a claim about music rather than the player.
  Bounded only by the player's limit, Saboteur II takes 6 calls of an 8-call
  row and melody falls 98% -> 62% with `retrig` 1.00 -> 0.81 -- alone among
  the files that moved. Half its row is 4, and the gains survive it.

Floored at the historical 2, so no single-speed file moves at all: Commando's
row is 3 calls and half of that is 1.

#### Measured

| | melody | seq | retrig | gate |
|---|---|---|---|---|
| Off the Cuff | 51 -> **95%** | 25 -> 96% | 0.64 -> 1.03 | 26 -> 55% |
| Kings of the Beach intro | 67 -> **100%** | 54 -> 100% | 0.67 -> 0.99 | 59 -> 71% |
| Mr Meaner | 72 -> 97% | 58 -> 97% | 0.68 -> 1.07 | 44 -> 63% |
| Bump Set Spike | 68 -> 97% | 67 -> 97% | 0.76 -> 0.94 | 45 -> 45% |
| Rock Tells the Tale | 53 -> 89% | 55 -> 90% | 0.80 -> 1.22 | 39 -> 48% |

`gate` moves on 15 files (+12.2pp mean), `hold` and `tail` on one each, and
**no file in the corpus is worse by half a point on melody, sequence, pitch,
wave, adsr, onset or hold**. The cost is `vib` on five files, mixed in
direction (Off the Cuff 0.80 -> 0.58, Mr Meaner 1.20 -> 1.02), and about
eight frames of `slides`.

Every one of the five files that gained melody was *under*-triggering --
`retrig` 0.64 to 0.80 -- and every one lands within 0.22 of 1.0. A release
long enough to sample is what lets a re-struck note be a re-struck note.

#### Which of the three numbers actually decides

`HARD_RESTART_FRAMES = 2` was chosen and not measured, so: swept, on the
converted bytes rather than on a derived row.

| | files whose bytes move | effect |
|---|---|---|
| 1 frame | 15 of 83 | mean `gate` 0.465 -> 0.453 |
| 3 frames | 3 (Chicken Song, Mr Meaner, Rock Tells the Tale) | no dimension moves |
| 4, 6 frames | the same 3 | the same |

So the constant is nearly inert, and the reason is that the two bounds decide
almost everywhere: the floor of 2 for the single-speed files, `row // 2` for
the multispeed ones. The row is the lever, and it was swept too:

| bound | mean melody | mean gate | against the shipped row/2 |
|---|---|---|---|
| `row // 3` | 0.901 | 0.448 | nothing better, nothing worse |
| **`row // 2`** | **0.901** | **0.465** | -- |
| `2 * row // 3` | 0.897 | 0.481 | Saboteur II melody 98 -> 67% |
| `row - 1` | 0.896 | 0.498 | Saboteur II melody 98 -> 62% |

`gate` rises monotonically with the bound and melody falls off a cliff at one
file. That is worth stating plainly: **`row // 2` is not a corpus optimum, it
is the last value before Saboteur II breaks.** A per-song choice could take
`2 * row // 3` everywhere else -- `gate` +1.6pp -- and `fidelity_better`'s
`keeps_notes` would refuse it on that one file. It is not offered as one
because a sixth `--fidelity` toggle doubles a four-hour search to buy 1.6pp
of a column no listener has yet confirmed.

**Two derived-row scripts got this wrong before the bytes settled it.** The
first parsed the tempo out of a log line and swept up the "in N pattern(s)"
count with it; the second took the row from the header's subtune count rather
than the emitted one. They reported 0 responding files and then 2, against
the true 3. Converting twice and hashing needs no row at all.

> **The transferable lesson:** the option that removes a defect is not
> always the fix for it. `--no-test-restart` deletes the frame that stands in
> for a missing release; what was wanted was the release. And the constant
> that produced it had the shape CLAUDE.md warns about twice over -- a rate
> in *calls* where the player's is in frames, written before the multiplier
> existed and never revisited when it did.

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
| A file that copies itself elsewhere at init named addresses the load address could not resolve, so every one of its tables read as out of range | `sidfile.find_relocation` reads the copy loop out of the init code; `to_offset` falls back to it only for an address that resolves nowhere, so no working file can be moved by a misread (`test_relocation.py`) |
| The transpose latch (§8) | Replaced by a single-byte operand lookahead; 17 corpus files were affected |
| `wait == 0` events dropped (§5) | Emitted as one-frame events; 2562 restored across 43 files |
| Version 2 grouped with 0/1/3, so its transpose commands were read as pattern numbers (§6) | Decoded as transposes; 6 corpus files played untransposed before, one of them with a wrong pattern spliced in |
| `reindex_tracks` split commands from pattern numbers at Goattracker's `$D0`, whatever the dialect | Split at `command_floor(version)`. Versions 0/1/3 have no command but `$FF`, so a pattern number of `$D0`–`$FD` was being emitted verbatim as a repeat or transpose — losing the reference *and* inventing a command. 146 bytes across 7 files |
| The out-of-range restart position standing in for Hubbard's `$FE` stop (§6) made `gt2reloc` refuse the file — with no message, because its error path writes to a console that does not exist headless. 28 of 78 files, and the failure looked like a successful run with a missing output | `--legal-restart` trades the stop for a loop; all 78 pack. The zero-length-voice variant is worse than a refusal and is still open: the subtune is exported as an entry that plays nothing, and the tail of the subtune list is truncated to match the count — silent data loss in 7 files, with no diagnostic from any layer |

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
