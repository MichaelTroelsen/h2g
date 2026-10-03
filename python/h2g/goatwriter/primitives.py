"""Small leaf helpers shared by the wave, attack, arp and vibrato emitters (split out of goatwriter.py, text moved unchanged)."""
from __future__ import annotations

import math
from typing import (List, Optional)

from ..detect import (Detection, _effect_byte_address)
from ..search import (search_file)
from ..sidfile import (find_freq_table, GT_FREQ0, SidFile)
from .constants import (WAVE_MAX_DELAY, WAVE_NOTE_ABS, WAVE_SILENT_BASE,
                        WAVE_SILENT_TESTBIT, WAVECMD_BASE)
from . import constants as _gw_constants
def _note_freq(note: int) -> int:
    """Goattracker's `freqtbl` value for note index `note`, floored.

    gplay.c:9-21 tabulates `GT_FREQ0 * 2**(n/12)` rounded. Flooring the formula
    rather than transcribing the table keeps this *under* the real value, which
    is the safe direction for a bound that decides whether a sweep can wrap.
    """
    if note < 0:
        return 0
    return int(GT_FREQ0 * (2.0 ** (note / 12.0)))


def _wave_hold_byte(multiplier: int = 1, wave: int = 0) -> Optional[int]:
    """Entry-1 byte that makes the attack last one frame, or None at -S1.

    **A delay entry holds for `value + 1` play calls, not `value`.**
    gplay.c:697-704 advances only on the call where `wavetime == value`,
    having incremented it on each of the `value` calls before, so the entry
    is current for `value + 1` calls in total. Entry 0 is itself one call, so
    a frame of `m` calls needs `m - 1` more from entry 1, which is a delay of
    `m - 2`.

    Until v0.5.130 this returned `m - 1` and the attack ran for `m + 1` calls
    -- 1.5 frames at -S2, where 22 of the corpus's 37 multispeed files sit.
    The reading came from gcommon.h's `WAVEDELAY .. WAVELASTDELAY` range
    rather than from the loop that consumes it.

    One extra call has no delay encoding: 0 is not a delay value and `$00` in
    a wavetable is the editor's empty marker. At -S2 the attack waveform is
    written again instead -- the same one call, an unambiguous byte, and a
    no-op wherever `tail == wave` already put it there.
    """
    extra = max(1, multiplier) - 1
    if extra <= 0:
        return None
    if extra == 1:
        return wave
    return min(extra - 1, WAVE_MAX_DELAY)


def _freq_table_note(sid: SidFile, index: int) -> Optional[int]:
    """Wavetable right-side byte for note `index` of the player's own table.

    Two mechanisms hand a wavetable an *absolute* pitch out of the player's
    frequency table -- bit $40's fixed attack (`_fixed_attack_note`) and bit
    $08's alternate note (`_note_alternate_note`) -- and both do it the same
    way: `sidfile.find_freq_table` locates the table the player indexes, the
    16-bit frequency at `2 * index` is read out of it, and the nearest of
    Goattracker's 96 notes names it. One helper rather than two copies,
    because it is a rule about the player and not about either caller
    (CLAUDE.md).

    Returns None where the byte cannot be a note. The player's table has a
    definite length and an index past it is reading something else; a zero
    frequency is the same. Neither is guessed at.
    """
    table = find_freq_table(sid)
    if table is None:
        return None
    if not 0 <= index < table.length:
        return None
    at = sid.to_offset(table.addr) + 2 * index
    if at + 1 >= len(sid.data):
        return None
    freq = sid.data[at] | (sid.data[at + 1] << 8)
    if not freq:
        return None
    note = min(range(96), key=lambda n: abs(_note_freq(n) - freq))
    return (WAVE_NOTE_ABS + note) & 0xFF


def _first_frame_entry(wave: int, written: bool = False) -> bool:
    """Whether the note's first frame gets an entry of the record's own `+2`.

    **The player writes the record's `+2` waveform on the note's first frame
    and reaches the effect block only from the second** -- the same rule
    `_drum_entries` was corrected to in v0.5.172, which never propagated to the
    other two emitters. Measured on Trans-Atlantic, modal waveform class over
    frames 0..7 from each onset with identical note counts on both sides:

        GT 3 (`+7 $08`, the wave program, 43 onsets a side)
          ORIGINAL  tri   noise tri   pulse noise noise noise noise
          OURS      noise tri   pulse noise noise noise noise noise
        GT 5 (`+7 $24`, the two-stage attack, 24 onsets a side)
          ORIGINAL  pulse noise pulse pulse pulse pulse pulse pulse
          OURS      noise pulse pulse pulse pulse pulse pulse pulse

    Both are the original shifted one frame left, and both originals' frame 0
    is exactly `+2`'s class -- `$11` tri for GT 3, `$41` pulse for GT 5.

    **A `+2` of `$00` is the exception, and it is what makes this a function.**
    That record has no waveform and no gate on its first frame, so siddump sees
    no gate edge there and calls the *second* frame the onset: Trans-Atlantic's
    GT 4 (`+2 $00`, a five-frame `$11` attack) profiles as five frames of `tri`
    from offset 0 in the original, already aligned with what we emit. Adding an
    entry for its silent frame would move a block that is right. A wavetable
    cannot write `$00` as a waveform either ($00-$0F are delays), so there is
    nothing faithful to put there.

    **`written` is `--no-test-restart`, and it removes the entry entirely.**
    That option writes the record's own waveform into the instrument's
    `firstwave`, and the *packed* player -- unlike the editor's `gplay.c`,
    which executes the wavetable on the same call -- jumps straight to
    `mt_loadregs` after a new note's init (`player.s:908-911`), so the
    wavetable's first entry lands on the note's *second* call. `firstwave` has
    already put the record's waveform on frame 0; an entry here repeats it and
    pushes the whole effect one frame late. IK+ measured `tri tri noi tri`
    against the original's `tri noi tri pul` on three instruments, and the
    same shift on its two-stage records.
    """
    return not written and bool(wave & 0xF0)


def _first_frame_lead(wave: int, multiplier: int = 1,
                      force: bool = False, written: bool = False) -> tuple:
    """The entries that hold the record's `+2` waveform for the note's frame 0.

    `(left, right)`, empty where the record has no waveform to put there
    (`_first_frame_entry`) -- unless `force`, which keeps the entry whatever
    `+2` holds.

    **`written` beats `force`.** It is `--no-test-restart`, which puts the
    record's waveform in the instrument's `firstwave` -- and the packed player
    writes that on the note's first call without executing the wavetable at
    all (`player.s:908-911`), so frame 0 is already the record's waveform and
    an entry here is a duplicate that delays the effect by a frame. `force`
    says "this caller has always emitted the entry"; `written` says "the frame
    is already accounted for", and the second is about the file rather than
    about the caller's history.

    **`force` is for a caller that already emitted this entry unconditionally**,
    where dropping it would be a change of its own rather than the absence of
    an addition. `_drum_entries` is that caller: it has always opened on the
    record's waveform, including the records whose `+2` selects none, where the
    byte lands in the wavetable's `$00`-`$0F` delay range and holds the frame
    without writing it. Faithful for neither reading -- the player *writes*
    `$00` there and a delay does not -- but making the lead a whole frame and
    silently deleting it for those records are two changes, and only the first
    is measured here.

    **One frame is `multiplier` play calls, not one call.** A wavetable steps
    once per call, so at `-S2` a single entry covers only half of frame 0 and
    whatever follows finishes the frame -- and siddump samples the registers at
    the end of a frame, so frame 0 reads as the *effect* rather than as the
    waveform. That is the whole defect at one remove: the same emitters that
    put the effect on frame 0 outright were also, on every multispeed file,
    putting it there through an under-long lead.

    A delay entry is current for `value + 1` calls (gplay.c:697-704), so one
    extra entry covers any `-S` the corpus uses. Its right side is `$80` for
    the reason `_drum_entries` gives: a delay's right side *is* read, on its
    final call, and anything else would drag the note.

    Shared by `_drum_entries` and `_two_stage_entries` rather than written out
    in each -- this rule was prose in one function's docstring for 45 versions
    while two siblings in the same file contradicted it (CLAUDE.md).
    `_two_stage_pitch_seq_entries` spells its lead out instead, because that
    block needs a note on the right side of every call and a delay would
    supply one only on its last.
    """
    if written or not (force or _first_frame_entry(wave)):
        return [], []
    left, right = [wave], [0x00]
    rest = max(1, multiplier) - 1              # ...the entry above is one call
    if rest == 1:
        left.append(wave)
        right.append(0x00)
    elif rest > 1:
        left.append(min(rest - 1, WAVE_MAX_DELAY))
        right.append(0x80)
    return left, right


def _gate_calls(calls: int, gate_skip: Optional[int]) -> int:
    """The player's own working calls expressed in ours.

    A player with an outer counter above its gate does nothing at all on one
    call in `O + 1` (`_find_outer_gate`), and Goattracker's player has no such
    counter -- so a duration of `n` of the original's *working* calls occupies
    `n * (O + 1) / O` of ours. The same correction `SongSpeeds.exact_row`
    makes to a row length, made to a table entry. `gate_skip` is None where
    the player has no counter, and None without `--skip-gate`, where the rows
    were not corrected either.
    """
    if not gate_skip:
        return calls
    return int(round(calls * (gate_skip + 1) / gate_skip))


def _sfx_note_byte(pitch_hi: int) -> int:
    """Wavetable right-side byte for a frequency whose high byte is `pitch_hi`.

    The player writes `$D401` directly and keeps the note's low byte, which a
    wavetable cannot do -- its right side names a note, not a register. The
    nearest absolute note is what it can say: `$3800` lands on index 68
    (`$375C`) and `$4800` on 73 (`$49E5`), both inside a quarter-tone --
    **-19.9 and +45.0 cents**, so `$4800` only just. Those two are the only
    high bytes the corpus uses, and for both of them the nearest note by this
    *linear* difference is also the nearest in cents (68 against 67's +80.1,
    73 against 74's -55.0), so the usual "compare a ratio in log space"
    correction is a no-op here rather than an unmeasured risk. For
    noise that is not an approximation anyone can hear -- the pitch sets how
    fast the shift register clocks, and a quarter-tone changes the colour of a
    drum by nothing.
    """
    target = pitch_hi << 8
    idx = min(range(96), key=lambda n: abs(_note_freq(n) - target))
    return (WAVE_NOTE_ABS + idx) & 0xFF


def _wave_byte(wave: int) -> int:
    """Wavetable left byte that sets the player's waveform `wave`.

    **Two ranges cannot be written literally**, and both go through the
    `$E0`-`$EF` encoding (readme.txt 3.4.1, gplay.c:527), which writes
    `$00`-`$0F` to `$D404` -- control bits, no waveform selected:

    * below `$10`, because `$01`-`$0F` are *delays*. This is what lets a wave
      program carry `slide $01` at all.
    * `$F0` and above, because `WAVECMD` is `$F0` (gcommon.h:60) -- that range
      is Goattracker's commands and `$FF` is the **jump**. Writing such a byte
      literally does not select a waveform, it rewrites the table: Wiz's
      record 1 carries the opcode `set $FF, 250` and emitted `FF/DE`, a jump to
      row 222 of a 112-row table, which `gt2reloc` refuses with exit code 0 and
      no message (§ 7.nnnn). Three corpus files carry opcodes in that range and
      two of them ship with `--wave-program` selected.

    Dropping the four select bits is faithful rather than merely legal. `$FF`
    is all four waveforms *and* the test bit: the test bit holds the oscillator
    in reset and the four select bits AND to silence on a real chip, so what
    the player sounds there is nothing. `$E0 | (wave & $0F)` keeps gate, ring,
    sync and test exactly and drops a nibble that produces no output.

    **Except for `$E0` itself, which the packed player never writes.**
    `gplay.c:527` is the editor; `gt2reloc` re-encodes the range on the way out
    (`greloc.c:1270-1271`): `$E0`-`$EF` becomes its low nibble, and then `+$10`
    is added back **only if the song uses a wavetable delay at all**
    (`nowavedelay`, set from the used rows at `greloc.c:829`). A song without
    one therefore ships `$E0` as a literal `$00`, and the player it is built
    with reads a zero byte as *no wave change* (`player.s:944`, the
    `NOWAVEDELAY != 0` branch) -- so the entry writes nothing and the previous
    waveform keeps sounding. Every other value in the range survives, because
    `$01`-`$0F` are stored as themselves.
    Traced, not reasoned: Skate or Die intro's GT 7 ends its wave program on
    `slide $00`, its packed table carries that entry as `00`, and its trace
    holds the `$80` before it for the rest of the note where the original goes
    silent. Nineteen's `$E1`, in a song that does use delays, comes out as
    `$11` in the packed file and writes the `$01` it means (§ 7.zzzz).
    So a waveform of `$00` is emitted as `$18` instead -- triangle with the
    **test bit**, which the packed player does write and which sounds nothing,
    because the test bit holds the oscillator at zero. `$F0` takes the same
    route for the same reason.
    """
    if 0x10 <= wave < WAVECMD_BASE:
        return wave
    if not wave & 0x0F:
        return WAVE_SILENT_TESTBIT
    return WAVE_SILENT_BASE | (wave & 0x0F)


def _speed_index(speed_table: List[tuple], entry: tuple) -> int:
    """1-based speed-table index for `entry`, appending it, or 0 if full."""
    if entry not in speed_table:
        if len(speed_table) >= _gw_constants.GT_MAX_TABLELEN:
            return 0
        speed_table.append(entry)
    return speed_table.index(entry) + 1


def _rate_shift(multiplier: int = 1) -> int:
    """Extra right-shift that turns a per-frame rate into a per-call one.

    Only the note-relative speed entries take their rate as a shift, so this
    is exact for 1 and 2 and rounds for 3 (log2(3) = 1.58 -> 2, a division by
    four where three is wanted). See _rise_speed_index.
    """
    m = max(1, multiplier)
    return max(0, round(math.log2(m)))


def _counter_gate_call(det: Detection, multiplier: int, attack_call: int,
                       record: Optional[int] = None) -> Optional[int]:
    """The call a counter (dialect A) vibrato gate opens on: frame `gate` of
    the original, `gate x multiplier + attack_call` of ours -- see
    `_classic_gate_delay`, which this was split out of so that
    `_counter_gate_restore_call` asks the same question. None where no
    counter gate was read for `record`; a gate of 0 is a gate of 1."""
    vg = det.vibrato_gate
    if vg is None or vg.form != "counter":
        return None
    gate = vg.gate_for(record)
    if gate is None:
        return None
    return max(1, gate) * multiplier + attack_call


def _fixed_pitch_yield_field(sid: SidFile, det: Detection) -> Optional[int]:
    """Record offset bit $40's handler tests once its countdown has run out,
    or None where that branch is not the one read here.

    The handler (`detect._find_fixed_pitch_index`) continues past the `BEQ`:

        LDA counter,X / BEQ + / DEC counter,X / LDA idx,Y / JMP fetch
        + LDA field,Y / BNE out      ; <- THIS operand, Y = record offset
          LDA note,X                 ; ...else the played note goes back
        fetch ASL / TAY / LDA table,Y / STA freqlo,X / ...

    Sanxion `$B40B`: `LDA $B571,Y / BNE $B421`, `$B571` = the instrument
    table `$B56C` + 5, the byte the classic vibrato reads (`$B1D2 LDA
    $B571,Y`). So on a record carrying vibrato the handler writes NOTHING
    after the attack, and the fixed pitch stands until the vibrato writes.
    38 of the 43 corpus handlers spell this branch with a record operand,
    all of them +5; Go Go Dash's family tests a per-voice `LDA abs,X`
    instead, which is not this rule and returns None (C:/t/sanxion-c-sharp-6-
    hold/scan_handlers.txt, 2026-10-01).

    Anchored on the handler's own `LDA idx,Y` operand (`det.fixed_pitch_index`)
    rather than re-scanning the file, so it reads the copy detection settled
    on.
    """
    if det.fixed_pitch_index < 0 or det.instr_start < 0:
        return None
    data = sid.data
    idx = sid.to_address(det.fixed_pitch_index)
    tail = bytes((0xB9, idx & 0xFF, (idx >> 8) & 0xFF))
    at = data.find(tail)
    while at >= 0:
        j = at - 8          # LDA counter,X / BEQ / DEC counter,X / LDA idx,Y
        if (j >= 0 and data[j] == 0xBD and data[j + 3] == 0xF0
                and data[j + 5] == 0xDE
                and data[j + 1:j + 3] == data[j + 6:j + 8]):
            rel = data[j + 4]
            tgt = j + 5 + (rel - 0x100 if rel & 0x80 else rel)
            if (0 <= tgt and tgt + 4 < len(data) and data[tgt] == 0xB9
                    and data[tgt + 3] == 0xD0):
                field = (sid.to_offset(data[tgt + 1] | data[tgt + 2] << 8)
                         - det.instr_start)
                if 0 <= field < det.instr_stride:
                    return field
            return None
        at = data.find(tail, at + 1)
    return None


def _arp_relative(arp_fixed: int, arp_note: int,
                  up: Optional[bool] = None) -> int:
    """The wavetable right-side byte for the arpeggio's alternate note.

    Readme p.794: `$00-$5F` is a relative note up, `$60-$7F` a negative one,
    so `$80 - N` is N semitones down. The two dialects go opposite ways -- the
    nibble form's `SBC` lowers the note, the fixed form's `ADC` raises it -- so
    the sign is a property of the routine, not of the record. `up` overrides
    that where the routine chooses per record (`nibble_arp_up`).
    """
    if up is None:
        up = bool(arp_fixed)
    if up:
        return arp_note & 0x5F
    return (0x80 - arp_note) & 0xFF


def _fixed_arp_block(sid: SidFile, det: Detection) -> Optional[tuple]:
    """(offset, lead) of the fixed-interval octave block, or None.

    The same signature `detect._find_effect_routines` reads the `ADC` operand
    from, re-searched here because `Detection` records only the interval and
    the readers below need the two bytes it wildcards (the mask and the
    branch sense) and the counter's own operand.
    """
    if not det.arp_fixed_up:
        return None
    found = _effect_byte_address(sid, det)
    if not found:
        return None
    addr, zp = found
    load = f"A5 {addr:02X}" if zp else f"AD {addr & 0xFF:02X} {addr >> 8:02X}"
    lead = 2 if zp else 3
    for branch in ("F0", "D0"):
        at = search_file(
            sid.data,
            f"{load} 29 04 F0 ?? AD ?? ?? 29 ?? {branch} ?? BD ?? ?? 18 69 ??")
        if at >= 1 and at + lead + 16 < len(sid.data):
            return at, lead
    return None


def fixed_arp_mask(sid: SidFile, det: Detection) -> Optional[tuple]:
    """(mask, branch opcode) the block divides its frame counter by.

    Read out of the files rather than assumed, and four masks with both
    senses are in the corpus (`tests/test_arp_octave.py::FIXED_ARP`):
    `$01 BEQ` Commando and nine others, `$02 BEQ` Rasputin, `$04 BNE` Zoids
    and One_Man_and_his_Droid, `$07 BEQ` Chimera, Battle_of_Britain,
    Game_Killer, Master_of_Magic, Human_Race and Phantoms_of_the_Asteroid.
    None where the block is not found.
    """
    blk = _fixed_arp_block(sid, det)
    if blk is None:
        return None
    at, lead = blk
    return sid.data[at + lead + 8], sid.data[at + lead + 9]
