# What SIDM2 already knows about the Hubbard player

The sibling project `C:\Users\mit\claude\c64server\SIDM2` reverse-engineered the
same player family this converter rips, for a different target (SF2 / a native
6502 driver rather than Goattracker). It works on the **same 95-file corpus**,
`SID/Hubbard_Rob/`, and it got further on several mechanisms than H2G has.

This file is a transfer list. It is **not** verified against our own reading —
everything below is SIDM2's claim, and this project's standing rule is that a
claim is checked against the 6502 before it is shipped. What makes it worth
reading anyway is that four items here bear directly on defects H2G has open
right now, and one of them contradicts something we shipped.

Source of record: `SIDM2/docs/players/HUBBARD.md`, `HUBBARD_V2_PLAN.md`,
`sidm2/hubbard_parser.py` (605 lines), `bin/build_hubbard_native_song.py`.

---

## 0. The asset we never had: a commented disassembly

`SIDM2/docs/analysis/hubbard/chacking5_monty_disassembly.txt` — 177 KB,
Anthony McSweeney's **fully-commented disassembly of *Monty on the Run***
from *C=Hacking* #5. SIDM2 treats it as ground truth for the whole V1 engine.

H2G has reverse-engineered every mechanism it implements by hand out of raw
bytes. This file is a labelled map of the same engine. Before the next player
excavation, read it.

---

## 1. The pulse engine — the fix for our 21 unimplemented files

**This is the highest-value item in the file.** H2G v0.5.73 implemented one
pulse-sweep mechanism (43 files). A census showed 21 further files where
detection reports `pulse-lo` (effect-byte bit `$08`) and **nothing writes it** —
Commando, One Man and his Droid, Warhawk, Thrust, Kentilla, Zoids, Formula 1
Simulator among them. Measured on One Man and his Droid: the original moves the
duty cycle **961 times per voice in 20 s and we move it twice.**

SIDM2 documents both variants explicitly, as one per-instrument engine:

- **classic bounce** (Monty): step `= pv & $E0` applied every `(pv & $1F)+1`
  frames; rails at PW hi-nibble `$0E` going down and `$08` going up.
- **fast-PWM** (Commando, selected by `fx` bit 3 — *our* `pulse-lo`):
  `PWlo += pulsespeed` **every frame**, PW hi held fixed.
- `pv == 0` → static width.

Three structural details we do not model at all:

1. **PW state is per-instrument, not per-voice** — it lives in the instrument
   record's own bytes 0/1 and is *shared across voices playing that instrument*.
2. **It free-runs.** The counter is **never reset at note fetch** in V1, and the
   load image ships a **nonzero initial value** (Monty: `[0,1,29]`). A conversion
   that starts every note's sweep from phase 0 is wrong even with the right rate.
3. **V2 is the opposite** — its note fetch rewrites the PW from the instrument
   record on every note. SIDM2 records that leaving the V1 free-run flag on for a
   V2 tune froze Delta's first ramp forever: **pulse 11% → 100% by dropping one
   flag.**

A warning that matches our own gating: SIDM2 selects fast-PWM only when `AND #$08`
appears in the *pulsework body*, because **Monty carries `fx` bit 3 with a
different meaning** and must not select it. Testing the instrument bit alone
would be a false positive. (Auf Wiedersehen Monty is absent from our `pulse-lo`
list, so our code-gated detection appears already to agree.)

---

## 2. Instrument byte **+5 is vibrato depth** — and we have never read it

SIDM2's instrument record, confirmed in `hubbard_parser.py` (`"vibdepth": b[5],
"pulsespeed": ..., "fx": b[7]`):

```
[0]=PW lo  [1]=PW hi  [2]=ctrl  [3]=AD  [4]=SR  [5]=vibdepth  [6]=pulsespeed  [7]=fx
```

**Bytes +6 and +7 match our reading exactly** — v0.5.50 established +6 as a
pulse-width sweep rate (refuting a proposed vibrato mapping) and v0.5.51/59/65
established +7 as the effect byte. That agreement is what makes byte +5
credible: it is the one field of the record H2G has never touched.

The vibrato algorithm, per SIDM2:

- per frame, `counter & 7` indexes an oscillating **`0 1 2 3 3 2 1 0`** shape
- depth = the semitone step `>> (vibdepth + 1)`
- applied **only when the note's `len >= 8`**

Bearing: the report currently measures **1229 slide-frames against the
original's 24828**, and 49 files where the original moves pitch and we emit
none. `whats-next.md` records that the *source* of that pitch movement "has
never been located in the 6502". This says it is byte +5, with a known
waveform and a known gating condition.

Goattracker expresses vibrato natively (CMD_VIBRATO), so unlike the pulse
engine this needs no table gymnastics.

---

## 3. Hard restart — this contradicts what we shipped in v0.5.71

v0.5.71 added `--no-hard-restart` (now in the `always` block) on the finding
that **`$0F00` appears in no corpus original**, concluding "Hubbard's players
never hard restart" and suppressing Goattracker's.

SIDM2 says the ROM *does* have one, and describes it as two distinct things:

- a release-side **"kill ADSR"** (`$7D` rows in their driver), and
- a per-retrigger **ADSR re-arm on the fetch frame** — explicitly **not** one
  frame early: *"the ROM never takes the 6581 precaution"*, and pre-arming a
  frame early cost them ~5% of register-stream match.

Independent support from our side: on One Man and his Droid the original
alternates `077F` / **`0000`** seventy-nine times per voice — writing `0000` to
`$D405/$D406` *is* a hard restart, with adparam `0000` rather than GT's default
`$0F00`. We write ADSR twice in 20 s.

So the v0.5.71 evidence was about the *value* `$0F00`, not the *mechanism*. The
likely correct fix is **setting Goattracker's `adparam` to `0000`** rather than
suppressing the restart. That flag is in `always` and affects every file.

**Do not act on this without re-deriving it.** But it should be treated as an
open defect, not a settled question.

---

## 4. Fractional tempo — the "swallow counter"

SIDM2's V2 engine carries a **second countdown** beside the speed gate
(`DEC abs / BPL / LDA #v / STA same / JMP`). On expiry the speed-decrement is
**skipped for one frame**, stretching that tick. Effective tempo becomes
`fpt + 1/period`. Observed periods: **Sanxion 109, Delta 5, Thundercats 4,
Star_Paws / Wiz / Auf_Wiedersehen_Monty 128.**

`whats-next.md` §7 lists four files with "no expressible rate" — Mozart, Ninja,
Mega Apocalypse (running the player *v* of every *v+1* calls) and Chain
Reaction (needing 5.5 calls per row). A fractional tempo of exactly the form
`fpt + 1/period` is the mechanism that produces "*v* of every *v+1*". Our
description of the symptom and their description of the cause are the same
thing.

It does not make the rate expressible in a steady Goattracker tempo — but it
turns "unknown, keeps the constant" into a known quantity that can be
approximated deliberately, and it may explain Chain Reaction's 0.66x.

Their measurement path, if the signature scan is not enough: `measure_tick_schedule`
derives the schedule empirically by replaying the original, and validated
Game_Killer 100% even though it has **no swallow signature at all**.

---

## 5. Initial instruments — replay init instead of reading the image

v0.5.67 shipped `--initial-instrument` and left it **out** of the `always`
block, because the per-voice instrument array is mutable player state: for a
multi-subtune rip like `Commodore_64_Music_Examples` the image was captured
mid-tune, and enabling it took melody 15%→19% while dropping wave 29%→**0%**.

SIDM2 hit the same wall and solved it differently: `initial_instruments()`
**replays the init routine in a 6502 emulator** and reads the array afterwards,
per subtune. Same finding as ours — *"Last_V8's silent-pulse voices were reading
instrument 0's PW instead of the ROM's per-voice defaults"* — with a dynamic
answer instead of a static one.

That would let the flag move into `always` and fix the class rather than the
easy half of it. Cost: H2G is a static ripper with no emulator, so this is a
real architectural addition, not a patch.

---

## 6. Note-byte semantics, and a tie we may be re-triggering

SIDM2's V1 note byte 0: `len` in bits 0–4, **bit5 = no-release**, **bit6 =
append/tie**, bit7 = "a second byte follows".

- **bit6 append** consumes *only* the length byte — a tie holding the previous
  pitch and instrument, with no re-gate.
- **bit5 no-release** skips the length-end ADSR kill, so the next note's fetch
  writes ctrl over an already-open gate → **no gate edge, no re-attack**: a tie
  *with* a pitch update.
- V2 adds **pitch bit7 = no-fetch**: pitch changes with no instrument fetch, no
  PW/ADSR write and no gate edge.

Their hardest-won lesson here is worth quoting: *"No-release (bit5) chains are
TIES, not retriggers. Emitting them as hard-restart rows chopped the sustained
bass for 2 frames every 1.28 s — invisible to register-state %, caught by the
ear and the VICE dump."*

H2G's v0.5.52 found a "bit-7 note flag" needing `AND #$7F` before the frequency
lookup in 14 files, which matches the *masking* half of V2's no-fetch bit. What
we do not obviously implement is the *semantic* half — suppressing the gate edge.
Our median retrigger ratio is 0.96, but per-file ratios run well above 1 in
places, and a tie emitted as a retrigger is exactly that error.

---

## 7. The filter — SIDM2 says Hubbard never uses it

Flatly, from their gotchas: **"'filter 100%' was VACUOUS — Hubbard never uses
the filter."** zig64 over 1000 frames of Monty and of Delta sub11 found **zero**
cutoff/resonance writes, `$D417` routing never written, `$D418` written once for
volume.

H2G v0.5.72 shipped a filter reader that reaches 15 files, 10 of which gain an
audible filter, and the v0.5.78 `filt` column reports 3662/7085 frames with 8
files playing unfiltered where the original filters.

**These are not necessarily in conflict** — SIDM2 tested Monty and Delta, and
neither is in our filtered list (I_Ball, IK+, Pandora, Trans-Atlantic, Nemesis,
ACE II, Nineteen, Star_Paws, Thundercats, Deep_Strike). The honest reading is
that the filter is *rare* rather than absent, which fits both.

The transferable part is the **trap**, and it is one our new columns must not
fall into: their metric compared `0 == 0` a thousand times and scored 100%, so
**any driver ignoring the filter entirely scored perfect**. `score_pct` could not
see it, because the denominator was 1000 rather than 0 — catching it needs a
**distinct-value check**. Our `filt` column requires routing *and* a selected
passband and reports `0/0` for Powerplay Hockey, which looks like the right
shape; it is worth confirming a file that filters nowhere cannot score 100%.

---

## 8. Code signatures we could borrow

SIDM2 locates every table by relocation-safe signature, as we do. Their map:

| Signature | Meaning |
|---|---|
| `BD .. 99 .. E8 C8 C0 06 D0` | V1 songs table (6 bytes/song) |
| `BD .. 85 .. BD .. 85` (no copy loop) | V2 split lo/hi songs tables |
| `CE .. 10 .. A9 v 8D same 4C` | swallow counter (fractional tempo) |
| `AND #$60 / CMP #$60 / BNE` | V2 note format (rest / 4-byte porta / no-fetch) |
| `BD .. 8E .. 0A 0A 0A AA` | per-voice instrument-number array |

The last one is **the same idiom H2G v0.5.67 adopted** to read the instrument
table through the index load (`BD ?? ?? 8E ?? ?? 0A 0A 0A AA BD ?? ??`) — two
projects arriving at the same relocation-safe anchor independently.

Also worth noting: their **V2 portamento is a 4-byte note spec**, and reading it
as 3 desynchronises the entire stream (their "instrument 127 garbage"). H2G's
`--slides` reads a second operand byte in 41 files; if any of those are the V2
class, the count may be off by one byte per event.

---

## 9. Two process lessons that apply to our new columns

- **The vacuous-100 trap and its sequel.** An empty comparison window returned a
  fabricated `100.0`. Fixing the one call site did not fix the class: *eleven*
  sibling scorers each had their own `100.0 * ok / tot if tot else 100.0`, two of
  them inside builders where the fake score fed a real A/B decision. Their fix is
  canonical: `score_pct()` returns **None** on an empty comparison and prints
  `n/a`, because None cannot be silently compared. v0.5.78 added four columns
  with denominators; this is the failure mode to check them against.
- **A validator that returns a meaningless number for a whole class is worse
  than one that refuses.** `bin/hubbard_validate.py` is V1-only and scores Delta
  at 23–25% by ignoring its swallow period — *"not a refutation of Delta, a
  validator returning a meaningless number"*. We have hit this exact shape three
  times (NTSC naming, subtune 0, the 10 s window).

---

## 10. Vocabulary map

| SIDM2 | H2G |
|---|---|
| V1 / V2 (Delta class) | dialect registry 0–10; their Delta class ≈ our version 10 (v0.5.52) |
| swallow counter | (no equivalent) — `whats-next.md` §7 "no expressible rate" |
| `fx` byte | instrument effect byte `+7` |
| `pulsespeed` (+6) | pulse-width sweep rate (v0.5.50/73) |
| `vibdepth` (+5) | **nothing** — unread |
| append (bit6) / no-release (bit5) | partially, via the `$FE`/tie handling |
| per-voice init instruments | `--initial-instrument` (v0.5.67, opt-in) |
| HP_ENGINE / HPReplay | (no equivalent) — we emit a static pulse |
| `mon_part_fidelity.py` | `fidelity.py` |

---

## Ranked, if you only do a few

1. **The fast-PWM algorithm** (§1) — a written-down solution to our largest
   measured defect, covering 21 files including the byte-exact fixture.
2. **Instrument byte +5 = vibrato depth** (§2) — a named source for pitch
   movement we produce 5% of, in a field we have never read.
3. **Re-open the hard-restart question** (§3) — we shipped a flag in `always` on
   reasoning this contradicts, and our own One Man and his Droid trace supports
   SIDM2 rather than us.
4. **Read the Monty disassembly** (§0) before the next excavation.

Everything above is SIDM2's claim. None of it is evidence until it is read out
of the 6502 here.
