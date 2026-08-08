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

The recurrence is real. It is not evidence for the count. In the 34 files that
carry the two-stage attack array (§7), a second table of the same 8-byte rows
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
`$E38B`, a shape 34 files share:

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
in **34 files out of 34**.

Two details make this format hostile to a naive reader. Bit `$08` reuses the
same field as the *high byte of a pointer* to a per-instrument byte-code
program (IK+ `$E33A` builds `$40`/`$41` from it), so a record setting both
bits has no attack waveform to read. And a record's `$04` is meaningless if
the attack byte is not a legal waveform nibble — 24 of 295 are not, and every
one of them lies in the parallel array itself, which the instrument-count
sniffer (§4.1) walked straight into and reported as extra instruments until
v0.5.66. Locating the array is what made that boundary knowable: the reading
below is not written to the output, but it ended a miscount that had every
one of these 34 files carrying roughly twice the instruments it has.

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

95 rows, **0 failed traces**. The corpus means barely move — but the figures
v0.5.132 published for them (`wave` 63.9% → 64.7%) came from the run with the
denominator defect below and are superseded; the corrected corpus figures are
in the table at the end of this section. Either way the mean is the least
informative number here, because it averages per-file disagreements of up to
±12.6 points that cancel.

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
