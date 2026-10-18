"""The swell's free-running triangle: its phase at each note's gate, and the
wavetable prefix that puts Goattracker's vibrato on it.

**The player's triangle is per voice and never reset by a note.**
Mega_Apocalypse `$4C4A`:

    4C4A  B5 B6     LDA $B6,X     ; direction (bit 7: falling)
    4C4C  10 08     BPL $4C56
    4C4E  D6 B0     DEC $B0,X     ; falling: pos - 1
    4C50  D0 12     BNE $4C64
    4C52  F6 B6     INC $B6,X     ; reached 0: rise
    4C54  10 0E     BPL $4C64
    4C56  F6 B0     INC $B0,X     ; rising: pos + 1
    4C58  B5 B3     LDA $B3,X     ; the record's bound, byte & $78 >> 3
    4C5A  D5 B0     CMP $B0,X
    4C5C  B0 06     BCS $4C64
    4C5E  95 B0     STA $B0,X     ; past it: back to the bound,
    4C60  D6 B6     DEC $B6,X     ;   fall,
    4C62  D6 B0     DEC $B0,X     ;   and one step down

and the frequency stored is `freq(note) - (bound >> 1) * step + pos *
step` (`$4C97`..`$4CCF`), so the swing spans `-(bound >> 1) .. bound -
(bound >> 1)` steps about the note: lopsided UPWARD on an odd bound. Only
the init's zero-page clear (`$5813`) ever writes `$B0`/`$B6`; the routine
runs on every frame whose record has a nonzero vibrato byte (`$4C35 BNE`)
EXCEPT a fetch frame, whose path leaves by `$4C09 JMP $4E63` past it. So
each note's phase at its gate is the voice's whole history, and a pattern
replayed at another point of the song swings in another phase.

**Goattracker's vibrato is the same triangle mirrored.** `cmp = bound - 2`
gives the same period and peak-to-peak (`_expanding_vibrato_loops`), but
from `vibtime = 0` it moves `+ - - - + +` (cmp 1): its span is `-2 .. +1`
about where it started. Through v0.5.588 every swell started there, so
on Mega_Apocalypse's lead (`$00B9`, bound 3) the conversion sat a step
FLAT of the original on average and swung in whatever phase the gate row
left it -- frames 1665-1682, original `184D 1961 185D 1739 1605 1739`,
ours `1678 1579 1678 17DA 193C 17DA`.

Two wavetable pieces fix both, and nothing else needs to change:

* a **phaser** on a row before the gate, `00 00` (the pattern's note:
  gplay.c:731 `cptr->vibtime = 0`, player.s `mt_wavenote` "Reset vibrato
  phase") `m` times, then `F4` on a zero-speed entry `(cmp, 0)`, which
  steps `vibtime` every call and moves nothing (player.s `mt_effect_4`
  clears the high byte; the right byte is the speed). The original holds
  the note before its gate, so this costs no audible frame, and the
  number of zero-speed calls before the gate chooses Goattracker's phase;
* a **prefix** on the gate row, before the row's own `F4` loop: nothing,
  one `F1`/`F2` step of the loop's speed (`U`/`D`, offsetting the centre
  one step, as the odd bound's lopsidedness needs), or one zero-speed `F4`
  (`S`, a frame the original holds at the note).

`plan_gate` tries every phaser placement the rows allow and every prefix
and keeps the one whose offsets match the player's -- exactly, after the
first period, wherever one exists.
"""
from __future__ import annotations

from typing import List, Optional, Tuple

from ..search import search_file

# `$4C4A` above, operands wild: direction cell, position cell, bound cell.
SWELL_TRIANGLE_SHAPE = ("B5 ?? 10 08 D6 ?? D0 12 F6 ?? 10 0E F6 ?? B5 ?? D5 "
                        "?? B0 06 95 ?? D6 ?? D6 ??")
# The prefixes `plan_gate` tries on the gate row, shortest first.
SWELL_PREFIXES = ("", "U", "D", "S", "SU", "SD")
# How many periods `plan_gate` scores, and from which one the tail starts.
SWELL_PLAN_PERIODS = 4
SWELL_PLAN_TAIL = 2


def swell_triangle(data: bytes) -> bool:
    """Whether the player's swell steps the zero-page triangle above, its
    three cells consistent (direction, position, bound)."""
    at = search_file(data, SWELL_TRIANGLE_SHAPE)
    if at < 0:
        return False
    d, pos = data[at + 1], data[at + 5]
    return (data[at + 9] == d and data[at + 13] == pos
            and data[at + 17] == pos and data[at + 21] == pos
            and data[at + 23] == d and data[at + 25] == pos)


def triangle_step(b0: int, b6: int, bound: int) -> Tuple[int, int]:
    """One frame of the player's triangle, `$4C4A`..`$4C62`."""
    if b6 & 0x80:
        b0 = (b0 - 1) & 0xFF
        if b0 == 0:
            b6 = (b6 + 1) & 0xFF
    else:
        b0 = (b0 + 1) & 0xFF
        if bound < b0:
            b0 = (bound - 1) & 0xFF
            b6 = (b6 - 1) & 0xFF
    return b0, b6


def player_offsets(bound: int, b0: int, b6: int, n: int) -> List[int]:
    """The player's offset, in steps about the note, on each of the `n`
    frames after the state `(b0, b6)`."""
    out = []
    for _ in range(n):
        b0, b6 = triangle_step(b0, b6, bound)
        out.append(b0 - (bound >> 1))
    return out


def _vib_call(vt: int, cmp_value: int) -> int:
    """gplay.c:795-797, player.s `mt_effect_4`: one call of `vibtime`."""
    if vt < 0x80 and vt > cmp_value:
        vt ^= 0xFF
    return (vt + 2) & 0xFF


def goat_offsets(cmp_value: int, quiet: int, prefix: str,
                 n: int) -> List[int]:
    """Goattracker's offset, in steps about the note, on each of the `n`
    calls from the gate: `vibtime` 0 and the note's pitch `quiet` calls
    before it (the phaser's last `00 00`, then zero-speed `F4`s), then
    `prefix`, then the loop's `F4` on every call."""
    vt = 0
    for _ in range(quiet):
        vt = _vib_call(vt, cmp_value)
    off, out = 0, []
    for i in range(n):
        step = prefix[i] if i < len(prefix) else "F"
        if step == "U":
            off += 1
        elif step == "D":
            off -= 1
        else:
            vt = _vib_call(vt, cmp_value)
            if step == "F":
                off += -1 if vt & 1 else 1
        out.append(off)
    return out


def plan_gate(bound: int, cmp_value: int, b0: int, b6: int,
              quiet_choices) -> Optional[Tuple[int, str]]:
    """`(quiet, prefix)` -- zero-speed calls between the phaser's last
    `00 00` and the gate, and the gate row's prefix -- whose offsets match
    the player's best, or None with no choices. Scored as (error after `SWELL_PLAN_TAIL` periods, total error),
    in steps; `quiet_choices` are the counts the rows allow."""
    period = 2 * max(1, bound)
    n = SWELL_PLAN_PERIODS * period
    want = player_offsets(bound, b0, b6, n)
    tail = SWELL_PLAN_TAIL * period

    def score(got):
        return (sum(abs(a - b) for a, b in zip(got[tail:], want[tail:])),
                sum(abs(a - b) for a, b in zip(got, want)))

    best = None
    for quiet in sorted(set(quiet_choices)):
        for prefix in SWELL_PREFIXES:
            s = score(goat_offsets(cmp_value, quiet, prefix, n))
            key = (s, len(prefix), quiet)
            if best is None or key < best[0]:
                best = (key, quiet, prefix)
    if best is None:
        return None
    return best[1], best[2]
