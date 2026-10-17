"""How often a .sid's play routine is called on a PAL machine, and making a
packed conversion call ours as often as the original calls its own.

**A PSID's speed bits are part of the tune.** Bit `n` of the header's `speed`
field set means subtune `n + 1` is called from CIA 1 timer A, not from the
vertical blank; a player then leaves the timer at the KERNAL's default latch
`$4025` unless the tune's init writes one. On PAL that is 985248 / 16422 =
59.996 Hz against the VBI's 985248 / 19656 = 50.125 Hz: a 1.1969x tempo.

`gt2reloc` knows none of this. At `-S1` it writes speed `$00000000` -- every
subtune on the VBI (greloc.c:1653-1659) -- and at `-S2` and up it prepends a
ten-byte stub `LDX #lo / STX $DC04 / LDX #hi / STX $DC05` (greloc.c:140) with
latch `$4CC7 / multiplier`, i.e. the VBI rate times the multiplier
(greloc.c:1606-1625), and sets every speed bit. Its player (player.s) never
touches $DC04/$DC05 itself. So a CIA-timed original came back 1.1969x slow --
Confuzion and Human_Race, reported by ear 2026-10-17 -- while every siddump
column agreed, because siddump calls BOTH sides once per row whatever either
header says (siddump.c:309/325): the trace is in ticks, and the error is in
the clock that issues them. `retime_packed` repairs the packed bytes;
`packed_call_period` reads them back for fidelity's `rate` column.

Measured under sidplayfp (C:/t/cia-tempo/probe.py, a PSID whose play routine
toggles $D418 each call): VBI 50.114 Hz, CIA with no timer write 59.983 Hz,
CIA after an explicit `$4025` write 59.983 Hz -- the same rate, so the default
latch is `$4025` -- and after `$2663` 100.229 Hz. All four read 0.02% low
against the cycle arithmetic, the same factor, so the ratios are exact.
"""
from __future__ import annotations

from pathlib import Path

PAL_CLOCK = 985248
PAL_FRAME = 19656            # 63 cycles x 312 lines: one VBI call
CIA_DEFAULT_LATCH = 0x4025   # KERNAL timer A, the PSID "60 Hz" (measured above)
CIA_DEFAULT = CIA_DEFAULT_LATCH + 1   # a latch L fires every L + 1 cycles

# gt2reloc's multispeed stub, greloc.c:140; bytes 1 and 6 are the latch.
STUB = bytes([0xA2, 0x00, 0x8E, 0x04, 0xDC, 0xA2, 0x00, 0x8E, 0x05, 0xDC])
STUB_LEN = len(STUB)

# Inits that write timer A themselves, so the default latch does not apply.
# Each is read off the file's own code, and `tests/test_call_rate_header.py`
# pins the bytes it was read from.
#   Commodore_64_Music_Examples: init $087C pushes A (the 0-based subtune) at
#   $089B, pulls it at $08AC, and `CMP #$04 / BCC` at $08B2 skips
#   `LDA #$26 / LDX #$63 / STX $DC04 / STA $DC05` ($08BC-$08C3) for
#   subtunes 0-3: songs 5-15 run at 985248 / 9828 = 100.25 Hz.
INIT_LATCH = {
    "Commodore_64_Music_Examples.sid": lambda sub: 0x2663 if sub >= 4 else None,
}

_TIMER_STORES = [bytes([op, reg, 0xDC]) for op in (0x8D, 0x8E, 0x8C, 0x9D, 0x99)
                 for reg in (0x04, 0x05)]


def _speed_bit(speed: int, sub: int) -> int:
    # PSID v2: subtunes past 32 share bit 31.
    return speed >> min(sub, 31) & 1


def original_call_period(sid: Path, sub: int) -> int | None:
    """CPU cycles between two play calls of the original's subtune `sub`
    (0-based) on PAL, or None where the header cannot say.

    None for an RSID (its init installs its own interrupt, so the rate is in
    its code, not its header), for an NTSC-only PSID, and for a CIA subtune
    whose code stores to the timer but has no `INIT_LATCH` entry -- an unread
    rate is reported as unread rather than guessed.
    """
    b = Path(sid).read_bytes()
    if b[:4] != b"PSID":
        return None
    flags = int.from_bytes(b[0x76:0x78], "big") if b[5] >= 2 else 0
    if (flags >> 2) & 3 == 2:
        return None
    speed = int.from_bytes(b[0x12:0x16], "big")
    if not _speed_bit(speed, sub):
        return PAL_FRAME
    rule = INIT_LATCH.get(Path(sid).name)
    if rule is not None:
        latch = rule(sub)
        return CIA_DEFAULT if latch is None else latch + 1
    code = b[int.from_bytes(b[6:8], "big"):]
    if any(s in code for s in _TIMER_STORES):
        return None
    return CIA_DEFAULT


def _has_stub(b: bytes) -> bool:
    off = int.from_bytes(b[6:8], "big")
    load = b[off] | b[off + 1] << 8
    init = int.from_bytes(b[0x0A:0x0C], "big")
    d = b[off + 2:off + 2 + STUB_LEN]
    return (init == load and len(d) == STUB_LEN
            and all(d[i] == STUB[i] for i in (0, 2, 3, 4, 5, 7, 8, 9)))


def packed_call_period(b: bytes, sub: int) -> int:
    """Cycles between two play calls of a gt2reloc-packed .sid's subtune."""
    speed = int.from_bytes(b[0x12:0x16], "big")
    if not _speed_bit(speed, sub):
        return PAL_FRAME
    if _has_stub(b):
        off = int.from_bytes(b[6:8], "big") + 2
        return (b[off + 1] | b[off + 6] << 8) + 1
    return CIA_DEFAULT


def retime_packed(b: bytes, periods: list[int | None], multiplier: int) -> bytes:
    """`b` with its call rate set so OUR subtune i ticks once per
    `periods[i]` cycles, `multiplier` calls to a tick.

    Unchanged where every period is the VBI's or unknown -- which is every
    file whose original is on the VBI, so they keep gt2reloc's bytes exactly.
    Otherwise, cheapest first:

    * at `-S1`, where every wanted period is the VBI's or the default CIA's:
      set the subtunes' speed bits and nothing else, so the packed file asks
      the player for the default timer exactly as the original does;
    * where all subtunes want one period: gt2reloc's own stub carries it --
      re-latched in place at `-S2`+, prepended at `-S1` the way greloc.c:
      1606-1611/1683-1697 prepends it (load and init move 10 bytes down, all
      speed bits set), with latch `(period - 1) // multiplier`, greloc's
      `$4CC7 / multiplier` convention;
    * mixed periods under one stub cannot be expressed: left as packed, and
      `packed_call_period` shows the mismatch.
    """
    songs = int.from_bytes(b[0x0E:0x10], "big")
    want = [periods[i] if i < len(periods) else None for i in range(songs)]
    want = [PAL_FRAME if p is None else p for p in want]
    if all(p == PAL_FRAME for p in want) or multiplier < 1:
        return b
    out = bytearray(b)
    stub = _has_stub(b)
    if (not stub and multiplier == 1 and songs <= 32
            and set(want) <= {PAL_FRAME, CIA_DEFAULT}):
        bits = sum(1 << i for i, p in enumerate(want) if p == CIA_DEFAULT)
        out[0x12:0x16] = bits.to_bytes(4, "big")
        return bytes(out)
    if len(set(want)) != 1:
        return b
    latch = (want[0] - 1) // multiplier
    off = int.from_bytes(b[6:8], "big")
    if stub:
        out[off + 3] = latch & 0xFF
        out[off + 8] = latch >> 8
        return bytes(out)
    load = (b[off] | b[off + 1] << 8) - STUB_LEN
    code = bytearray(STUB)
    code[1], code[6] = latch & 0xFF, latch >> 8
    out[0x0A:0x0C] = load.to_bytes(2, "big")
    out[0x12:0x16] = b"\xff\xff\xff\xff"
    return bytes(out[:off]) + bytes([load & 0xFF, load >> 8]) + bytes(code) + b[off + 2:]
