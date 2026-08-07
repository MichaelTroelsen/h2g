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

What remains of the census's four blocks: bit `$08`'s pulse-width variant is
still unwritten, because the pulse table has two entries per instrument and no
metric here can see a duty cycle — tracking siddump's `Pul` column comes
first. The drum's sweep is one entry deep rather than the counter's length,
since the counter is a runtime value and the wavetable has three free slots.

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
-- because **no column in `FIDELITY.md` compares ADSR at all**. The table
above comes from a separate comparison of siddump's `ADSR` column written for
this change, not from the report.

### 7.aa The pulse width: a sweep written as a constant

The third defect the first listening pass raised, alongside the two envelope
ones in 7.z and the filter in 7.y. All four are the same shape: the notes were
right, the *sound* was not, and no column in `FIDELITY.md` could report any of
them.

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
its width. This is the seventh change in the project's history that is real,
verified against the 6502, and completely invisible to the report -- which is
the argument for building the `Pul` metric rather than a reason to doubt it.

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
