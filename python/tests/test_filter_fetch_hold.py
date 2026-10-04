"""Why the classic player's cutoff holds for one frame at every note change.

Measured on Saboteur_II under presets at `-t 180`: of 801 frames on which our
cutoff moves and the original's does not, 800 are the frame right before the
original's cutoff drops back to the new note's start value. The original
holds; ours takes one more modulation step.

**It is the note-FETCH frame, not the hard restart**, and the disassembly says
so (Saboteur_II, `python dis6502.py Saboteur_II.sid --at '$F000' -n 700`):

    F0DB  A9 20     LDA #$20        ; fetch path: cutoff accumulator reset ...
    F0DD  9D AB F5  STA $F5AB,X     ; ... to the start value, NOT written out
    ...
    F1B9  4C 5F F4  JMP $F45F       ; fetch path ends past every effect block
    ...
    F41C  AD 98 F5  LDA $F598       ; the filter block, the only $D416 write
    F42D  8D 16 D4  STA $D416
    F433  8D 17 D4  STA $D417
    F436  2C 98 F5  BIT $F598       ; (vibrato follows)
    F45F  AC 50 F5  LDY $F550       ; ctrl/freq write-out, reached by both paths

So on the fetch frame $D416 keeps the old note's last value, and the first
write of the new note (next frame) is already `start + step`. The hard-restart
gate-off ($F1BC: `LDA #$FE / STA $F566,X` when the duration counter is 0) is
on the NON-fetch path, which falls through to the filter block, so it does
write the cutoff.

**Why the emitter cannot say this with the filter table.** In the packed
player (`player.s`, `mt_filtstep`) the filter table executes and stores $D416
BEFORE `jsr mt_execchn`; the instrument's filter pointer is loaded during
channel execution at note init (`mt_insfiltptr`, `sta mt_filtstep+1`). So the
note-init call always runs ONE MORE step of the old program, and nothing in a
per-instrument table knows when the next note comes -- the hold belongs to
the note's DURATION, which the classic record (resctl, step) does not carry.
The only per-note handle that could stop the old sweep early is a tick-0
`CMD_SETFILTERPTR` on each filtered note's last row, pointing at a
per-instrument [modulate k, stop] tail; that is a pattern-pass change costing
a command-column slot per filtered note, and on Saboteur_II it is quantised
against rows of 8 calls at multiplier 3, so the init call's phase within a
frame rotates note to note. Not attempted here.

What this file pins is the player fact the decision rests on, across every
classic-filter file in the corpus, so a later emitter task starts from it.
"""
import pytest

from corpus import CORPUS, needs_corpus  # noqa: E402
from h2g.detect import FILTER_SHAPE, detect
from h2g.search import search_file
from h2g.sidfile import load_sid

# `CMP #$FF / BNE +8 / LDA #$00 / STA idx,X / INC pos,X / JMP post_effects`:
# the end of the note-fetch path (instrument byte list exhausted -> advance
# the track position), whose JMP is the fetch frame's only way out.
FETCH_TAIL = "C9 FF D0 08 A9 00 9D ?? ?? FE ?? ?? 4C ?? ??"
_TAIL_JMP = 12                    # offset of the 4C within FETCH_TAIL
_FILTER_LEN = 26                  # FILTER_SHAPE's byte length: up to STA $D417

# The files the task named, so the corpus walk cannot pass by finding none.
NAMED = ("Saboteur_II", "Auf_Wiedersehen_Monty", "Knucklebusters")


def fetch_frame_reading(sid, data: bytes):
    """(filter_addr, filter_end, tails, resets) for one classic-filter player.

    `tails` is every (jmp_addr, target) of a FETCH_TAIL lying before the filter
    block; `resets` every `STA cutoff,X` lying before it (the accumulator's
    reset at note start). None when the filter block is not found.
    """
    i = search_file(data, FILTER_SHAPE)
    if i <= -1:
        return None
    start = sid.to_address(i)
    end = start + _FILTER_LEN
    cut_lo, cut_hi = data[i + 15], data[i + 16]
    tails, j = [], 0
    while True:
        k = search_file(data[j:], FETCH_TAIL)
        if k <= -1:
            break
        k += j
        if k < i:
            target = data[k + _TAIL_JMP + 1] | data[k + _TAIL_JMP + 2] << 8
            tails.append((sid.to_address(k + _TAIL_JMP), target))
        j = k + 1
    resets = [sid.to_address(q) for q in range(1, i)
              if data[q] == 0x9D and data[q + 1] == cut_lo and data[q + 2] == cut_hi]
    return start, end, tails, resets


def skips_filter_on_fetch(reading) -> bool:
    """The fetch path leaves past the filter block, after resetting the cutoff."""
    if reading is None:
        return False
    start, end, tails, resets = reading
    if not tails or not resets:
        return False
    return (all(target >= end for _, target in tails)
            and all(r < jmp for r in resets for jmp, _ in tails[:1]))


def _classic_filter_files():
    out = {}
    for p in sorted(CORPUS.glob("*.sid")):
        sid = load_sid(str(p))
        try:
            det = detect(sid, lambda m: None)
        except Exception:                     # a file detect refuses is not ours
            continue
        if det.filter is not None:
            out[p.stem] = (sid, fetch_frame_reading(sid, sid.data))
    return out


@needs_corpus
def test_every_classic_filter_player_skips_the_filter_on_the_fetch_frame():
    files = _classic_filter_files()
    assert set(NAMED) <= set(files), sorted(set(NAMED) - set(files))
    failing = sorted(stem for stem, (_, r) in files.items()
                     if not skips_filter_on_fetch(r))
    assert failing == [], failing


@needs_corpus
def test_saboteur_ii_reads_as_the_docstring_quotes():
    sid = load_sid(str(CORPUS / "Saboteur_II.sid"))
    start, end, tails, resets = fetch_frame_reading(sid, sid.data)
    assert (start, end) == (0xF41C, 0xF436)
    assert tails == [(0xF1B9, 0xF45F)]
    assert resets == [0xF0DD]
    # the reset stores the note's start value, which detect reads as cutoff
    det = detect(sid, lambda m: None)
    assert det.filter.cutoff == 0x20


@needs_corpus
def test_the_reading_can_fail():
    """Probe lie #1: a check that cannot return False measures nothing.

    Retarget Saboteur_II's fetch-tail JMP to the filter block's first byte --
    a player that WOULD write the cutoff on the fetch frame -- and the reading
    must say so.
    """
    sid = load_sid(str(CORPUS / "Saboteur_II.sid"))
    data = bytearray(sid.data)
    start, _, tails, _ = fetch_frame_reading(sid, bytes(data))
    jmp_addr, _ = tails[0]
    k = search_file(bytes(data), FETCH_TAIL) + _TAIL_JMP
    assert sid.to_address(k) == jmp_addr
    data[k + 1], data[k + 2] = start & 0xFF, start >> 8
    assert not skips_filter_on_fetch(fetch_frame_reading(sid, bytes(data)))
