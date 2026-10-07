"""Fixed and nibble arpeggios, pitch-sequence clock and phases, tempo duty split (split out of goatwriter.py, text moved unchanged)."""
from __future__ import annotations

import math
import re
from bisect import (bisect_right)
from collections import (Counter)
from dataclasses import (dataclass)
from fractions import (Fraction)
from typing import (List, Optional, Tuple)

from ..detect import (Detection, NIBBLE_ARP_PERIOD_OPCODE_SHAPE,
                      NibbleArpPeriod, PITCH_SEQ_AT_PHASE, PITCH_SEQ_SHAPES)
from ..search import (search_file)
from ..sidfile import (SidFile)
from .constants import (BEQ, BNE, CMD_SETTEMPO, CMD_TONEPORTA,
                        EFFECT_PITCH_SEQ_MASK, FIXED_ARP_GATED_INC,
                        FIXED_ARP_PARITY_MASK, FIXED_ARP_RESET_WINDOW,
                        FIXED_ARP_SPLIT_FACTOR, FIXED_ARP_TIE_SHARE,
                        GT_FIRST_NOTE, GT_LAST_NOTE, NIBBLE_GATE_MAX_HALVES,
                        OUTER_GATE, OUTER_GATE_PAL, OUTER_GATE_RTS, SPEED_GATE,
                        SPEED_GATE_ZP,
                        TEMPO_DUTY_MAX_CLONE, WAVE_JUMP, WAVE_MAX_DELAY,
                        WAVE_NOTE_BASE)
from .primitives import (_fixed_arp_block, _gate_calls, _wave_hold_byte)
from .tempo import (outer_gate_skip)
from . import primitives as _gw_primitives
from . import tempo as _gw_tempo
def nibble_arp_up(sid: SidFile, det: Detection, nibble: int) -> Optional[bool]:
    """True where the nibble block ADDS this record's nibble, or None.

    Formula_1_Simulator's block ($C3B5, `NIBBLE_ARP_PERIOD_OPCODE_SHAPE`) is
    the corpus's one opcode-spelled period code: `CMP #$0C / BEQ +8 / LDY #1 /
    LDA #$E9 / SEC / JMP sta / LDY #4 / LDA #$69 / CLC / STA $C3D6`, the store
    landing on the opcode of the block's own `SBC #nibble`. A record whose
    nibble is the interval runs `ADC` -- the octave UP -- and every other one
    `SBC`. Measured on the original at 60 s: a `$0909` note on $45A0 plays
    $8B40 for four frames, where `_arp_relative`'s nibble rule emitted $22D0
    (C:/t/f1-ticked-reversal/notes_base.txt). None for every other spelling
    (each other nibble block always subtracts) and for the fixed dialect,
    leaving `_arp_relative`'s per-dialect sign in force; None also where the
    block read here disagrees with `det.arp_nibble_period`.
    """
    per = det.arp_nibble_period
    if per is None:
        return None
    p = search_file(sid.data, NIBBLE_ARP_PERIOD_OPCODE_SHAPE)
    if p < 0:
        return None
    d = sid.data
    if (d[p + 1], d[p + 13], d[p + 5]) != (per.interval, per.on_interval,
                                           per.otherwise):
        return None
    opcode = d[p + 15] if nibble == per.interval else d[p + 7]
    return {0x69: True, 0xE9: False}.get(opcode)


def fixed_arp_period(mask: int) -> int:
    """Counter steps per cycle of `counter & mask`: 2, 4 or 8 in the corpus.

    `(c & mask) == 0` repeats with the period of the mask's highest bit, so
    `$01` alternates every step, `$02` every two, `$04` every four -- and `$07`
    is zero on one step in eight.
    """
    return 1 << max(1, mask).bit_length()


def fixed_arp_up(mask: int, branch: int, counter: int) -> bool:
    """Whether the block adds its octave on a call whose counter reads this.

    `AND #mask / BEQ base` adds where the masked value is nonzero; `BNE` is the
    swapped spelling. **Measured, not argued** (v0.5.489, siddump of the
    originals, every octave-up and base frame after every octave onset in 60
    seconds against `fixed_arp_up(mask, branch, frame)`): Zoids 3524 frames
    agree and 0 disagree, One_Man_and_his_Droid 3195/4, Chimera 837/7,
    Master_of_Magic 3190/1, Phantoms_of_the_Asteroid 2561/1 -- all five with
    the counter reset on the new-song call, so `counter == frame`.
    """
    hit = (counter & mask) != 0
    return hit if branch == BEQ else not hit


def _fixed_arp_counter(sid: SidFile, det: Detection) -> Optional[int]:
    """Address of the frame counter the octave block reads, any mask."""
    blk = _fixed_arp_block(sid, det)
    if blk is None:
        return None
    at, lead = blk
    return sid.data[at + lead + 5] | sid.data[at + lead + 6] << 8


def fixed_arp_counter_gated(sid: SidFile, det: Detection) -> bool:
    """True where an outer gate skips the counter's `INC` one call in R+1."""
    ctr = _fixed_arp_counter(sid, det)
    if ctr is None:
        return False
    data = sid.data
    inc = search_file(data, f"EE {ctr & 0xFF:02X} {ctr >> 8:02X}")
    if inc < 1:
        return False
    return any(g.search(data[max(0, inc - 14):inc]) for g in FIXED_ARP_GATED_INC)


def fixed_arp_counter_base(sid: SidFile, det: Detection) -> Optional[int]:
    """What the octave block's counter reads on frame `k`, less `k`.

    The counter is `INC`'d at the play entry, before the block reads it. Two
    shapes, and the corpus has both:

    * **Reset.** Commando `$5012 INC $5525 / BIT $5519 / BMI / BVC / LDA #0 /
      STA $5525`: the new-song call -- the first, since the init sets the flag
      -- clears it after the increment, so frame 0 reads 0 and frame k reads
      k. Base 0.
    * **No reset.** Hunter_Patrol `$A006 INC $A426 / LDX #2 / DEC $A418 ...`
      goes straight into the sequencer and nothing in the file ever stores
      the counter, so frame k reads the file's own byte plus k plus one.

    The octave is up where the value is odd (`AND #$01 / BEQ` takes the base
    path on zero), so the parity of `base + frame` is the whole of the phase.
    **Measured** (v0.5.485, siddump of the originals, up-frames against the
    frame numbers): odd in Commando, Crazy_Comets, Gerry_the_Germ,
    5_Title_Tunes, Geoff_Capes_Strongman_Challenge and Gremlins -- the six
    with a reset -- and EVEN in Hunter_Patrol, whose byte is `$1E`: `$1E + 1`
    is odd, so its odd counter values fall on even frames. The one file that
    disagreed with the six is the one whose player differs, which is what
    makes this a derivation rather than a table.

    Any mask (since v0.5.489: the mask is the DUTY, `fixed_arp_period`, and
    the counter and its reset are the same bytes whatever it divides by).
    None where the block or the counter's `INC` is not found.

    **`k` is a call that passed the outer gate, where there is one.** A
    gated `INC` (`fixed_arp_counter_gated`: Game_Killer, Rasputin) sits
    behind an `RTS` that skips the whole play routine one call in R+1, so
    the counter is not the frame number -- it is the count of PASSING calls,
    which is the clock the sequencer's rows run on too, and the reset and
    no-reset shapes read exactly as above in that clock. Through v0.5.490
    this returned None for a gated counter and both files took residue 0.
    **Measured** (v0.5.490, siddump of the originals, 60 s, every
    octave-up and base frame after every octave onset against
    `fixed_arp_up(mask, branch, c)`): Game_Killer with `c` = passing calls
    since the reset -- the gate byte `$0C8C` is 4 in the file and reloads
    9, so frames 4, 14, 24, ... are skipped -- agrees 2933 and disagrees 0
    (7892/0 at 180 s), where `c` = frame reads 2149/784; Battle_of_Britain,
    the no-reset shape with byte `$DC` at `$841F`, agrees 405/0 at this
    function's 221 and 324/81 at 0. `tests/test_arp_octave.py::
    test_the_gated_counter_is_re_measured_against_the_original` re-takes
    all four whenever siddump is on the machine.
    """
    ctr = _fixed_arp_counter(sid, det)
    if ctr is None:
        return None
    return frame_counter_base(sid, ctr)


def frame_counter_base(sid: SidFile, ctr: int) -> Optional[int]:
    """What the play-entry counter at `ctr` reads on frame `k`, less `k`.

    `fixed_arp_counter_base`'s reading of the counter, for any block that
    names one -- the octave's, or the skydive's (`detect.Skydive.counter`,
    the same `$A426` in Hunter_Patrol). None where its `INC` is not found.
    """
    data = sid.data
    lo, hi = ctr & 0xFF, ctr >> 8
    inc = search_file(data, f"EE {lo:02X} {hi:02X}")
    if inc < 1:
        return None
    reset = data.find(bytes([0xA9, 0x00, 0x8D, lo, hi]), inc,
                      inc + FIXED_ARP_RESET_WINDOW)
    if reset >= 0:
        return 0
    off = sid.to_offset(ctr)
    if not 0 <= off < len(data):
        return None
    return data[off] + 1


def fixed_arp_first_fetch(sid: SidFile, det: Detection) -> Optional[int]:
    """The frame the player fetches its first row on: the gate counter's byte.

    The speed gate is `DEC ctr / BPL +6 / LDA reload / STA ctr`, then
    `LDA ctr / CMP reload / BNE nofetch` (Commando $5052): a voice takes a
    new event only on the call that reloads the counter, which is the call
    on which it underflows. Starting from the byte the file holds, `c`, that
    is call `c` -- and every row after it lands `reload + 1` calls later. The
    init does not write the counter (Commando $5F0C writes the reload from
    its per-subtune table and nothing else; the new-song path at $501C clears
    the per-voice cells and the frame counter, not this one), so the byte in
    the file IS the phase of the whole tune.

    **Measured, not argued** (v0.5.485, seven corpus files, first attack
    frame in a siddump of the original against this byte): Commando 0/0,
    Geoff_Capes 0/0, Crazy_Comets 1/1, Gerry_the_Germ 1/1, Hunter_Patrol
    1/1, Gremlins 2/2, 5_Title_Tunes 3/3 -- and the repo's own
    `Commando.sid`, a mid-run snapshot whose byte is 1, attacks on frame 1
    where the corpus copy of the same player attacks on frame 0.
    `tests/test_arp_octave.py` re-measures two of them whenever siddump is
    on the machine.

    None where no absolute-spelled gate is found; the gate nearest the
    instrument table is the detected player's own, `find_song_speeds`'s rule.
    """
    data = sid.data
    hits = []
    for m in SPEED_GATE.finditer(data):
        ctr, ctr2 = m.group(1), m.group(3)
        if ctr != ctr2:
            continue
        hits.append((abs(m.start() - det.instr_start), ctr[0] | ctr[1] << 8))
    if not hits:
        return None
    _, ctr = min(hits)
    off = sid.to_offset(ctr)
    if not 0 <= off < len(data):
        return None
    return data[off]


def fixed_arp_phases(sid: SidFile, det: Detection, tracks: List[List[int]],
                     patterns: List[List[int]]) -> dict:
    """{Goattracker instrument: the counter's residue on its attack frame}.

    The residue is `(base + a) mod fixed_arp_period(mask)` -- what the block's
    counter reads, modulo its cycle, on the frame the note attacks. For
    Commando's `$01` mask that is the attack frame's parity, and the first
    octave-up frame is `a + 1` where the residue is 0 and `a + 2` where it is
    1 (`_wavetable_entries`' tick shape reads it that way); for the other
    masks it is the position in a four- or eight-step cycle, and
    `fixed_arp_duty_entries` unrolls the cycle from it. Until v0.5.489 the
    value was the offset itself, 1 or 2, and only the parity mask voted.

    **The phase is per NOTE, and a wavetable is per instrument.** The block's
    counter reads `base + k` on frame `k` (`fixed_arp_counter_base`) and the
    octave is up where that is odd, whatever the note: Commando attacks on
    even frames and its first octave is offset 1, Crazy_Comets on odd frames
    and offset 2, Hunter_Patrol on both (60:36) with its offsets split the
    same way. The init call does not run the effect, so a note attacking on
    frame `a` gets its first octave on `a + 1` when `base + a` is even and
    on `a + 2` when it is odd.

    `a` is static: `fixed_arp_first_fetch` plus the note's row index times
    the subtune's row length in frames (`SongSpeeds.frames_for`) -- checked
    against the trace on Hunter_Patrol voice 2, 131 attacks of 131 on the
    frame the walk names. Walked here over the finished orderlists and
    patterns in play order, one lap, repeats expanded, the instrument column
    sticky (`instr 00` keeps the current one); each note votes for its
    instrument, and the instrument takes the majority -- exact wherever a
    row is an even number of frames or the instrument's notes all sit on
    rows of one parity, and a per-note split (two wavetables per record) is
    what would make Hunter_Patrol's minority right. A group whose numbering
    a split has shifted casts no vote.

    **A tied note casts no vote.** A row carrying `CMD_TONEPORTA 00` skips
    the new-note init that loads the waveptr (player.s:832-835 `cmp
    #TONEPORTA / beq mt_nonewnoteinit` ahead of `lda mt_inswaveptr-1,y`;
    gplay.c:354 `newcommand != CMD_TONEPORTA`), so the wavetable runs on
    from the note before and the tie's residue is never a block's attack --
    the rule `pitch_seq_phases` and `_note_phase_split` already kept.
    Through v0.5.513 ties voted here: Chimera's tie-row records GT 5 and
    GT 8 took residue 0 from their tie rows (198 and 60 of them) where
    every untied attack of GT 5 (6) and the plurality of GT 8's (16 of 52)
    is residue 2, and Game_Killer's GT 8 took 5 (101 votes) over 1 (97)
    where its untied notes tie 97:97 and the lower wins. Neither block reads
    the difference -- the tie-row shape is identical at residues 0-6 and
    Game_Killer's GT 8 at all eight -- so the corpus moved no byte under
    presets (C:/t/tie-votes-in-fixed-arp-phases). A slide (`CMD_TONEPORTA`
    with a speed) skips the same init in both players, but the converter
    emits none on a note the walk reads, so only the tie is tested.

    **The walk is in the player's own clock: calls that pass the outer
    gate.** Where the player has one (`SongSpeeds.skip`, Game_Killer's
    reload 9) a row is not a whole number of FRAMES, and through v0.5.490
    such a group cast no vote -- but the gate's `RTS` skips the counter's
    `INC` and the sequencer alike, so in passing calls a row is exactly
    `frames` calls and the counter steps exactly once a call: the residue
    is `(base + first + row * frames) % period` whatever the gate skips.
    Game_Killer's attacks, modelled that way over a 60 s trace, sit on
    residues 1, 3, 5 and 7 -- `first` 1 plus rows of 2 -- about evenly on
    every voice (`C:/t/gated-counter-phase/attack_residues.py`), so the
    majority vote picks one of four for each record where residue 0, the
    value both gated files took until then, occurs on no attack at all.

    Empty for any file whose block is not found or whose counters cannot be
    read.
    """
    base = fixed_arp_counter_base(sid, det)
    first = fixed_arp_first_fetch(sid, det)
    mask = _gw_primitives.fixed_arp_mask(sid, det)
    if base is None or first is None or mask is None:
        return {}
    period = fixed_arp_period(mask[0])
    speeds = _gw_tempo.find_song_speeds(sid, det)
    if speeds is None:
        return {}
    groups = len(tracks) // 3
    if groups > max(sid.subtunes, 1):
        return {}                        # a split subtune shifted the numbering
    votes: dict = {}
    for ti, track in enumerate(tracks):
        frames = speeds.frames_for(ti // 3)   # in passing calls; see above
        if frames is None:
            continue
        for row, current, pat, r in _walk_note_rows(track, patterns):
            if pat[r + 2] == CMD_TONEPORTA and pat[r + 3] == 0:
                continue                 # a tie restarts no wavetable
            residue = (base + first + row * frames) % period
            votes.setdefault(current, [0] * period)[residue] += 1
    # The majority residue; a tie goes to the lower one, which for the parity
    # mask is what `1 if even >= odd else 2` chose.
    return {instr: max(range(period), key=lambda p: (counts[p], -p))
            for instr, counts in votes.items()}


def _walk_note_rows(track: List[int], patterns: List[List[int]]):
    """(row, instrument, pattern, offset) for every note row, in play order.

    One lap of a finished orderlist: repeats expanded, transposes skipped,
    the `$FF` restart's operand skipped, the instrument column sticky
    (`instr 00` keeps the current one, gplay.c:914). `row` counts every row
    the voice plays, note or not, so it is the row grid's index; a note
    under instrument 0 (none yet) is not yielded. `pattern[offset]` is the
    row's note byte, for a caller that reads its command column.
    """
    row, current, repeat = 0, 0, 1
    operand = False
    for b in track:
        if operand:                  # $FF's restart position
            operand = False
            continue
        if b == 0xFF:                # patterns.GT_ORDER_RESTART
            operand = True
            continue
        if 0xE0 <= b < 0xFF:         # a transpose, no row of its own
            continue
        if 0xD0 <= b < 0xE0:         # patterns.GT_REPEAT: the NEXT entry
            repeat = b - 0xD0 + 1
            continue
        if b >= len(patterns):
            continue
        pat = patterns[b]
        for _ in range(repeat):
            for r in range(0, len(pat), 4):
                if pat[r] == 0xFF:   # ENDPATT, patterns.GT_END_PATTERN
                    break
                if pat[r + 1]:
                    current = pat[r + 1]
                if current and GT_FIRST_NOTE <= pat[r] <= GT_LAST_NOTE:
                    yield row, current, pat, r
                row += 1
        repeat = 1


@dataclass(frozen=True)
class PitchSeqClock:
    """Bit $10's DIVIDED phase counter and the row clock it is read against.

    Every cell's initial value is the file's own byte; reloads are the
    immediates. `outer`/`inner` are the row clock's two counters (the outer
    gate's cell and the speed gate's), whose reloads are per subtune and come
    from `find_song_speeds` (`skip`, `frames - 1`).
    """
    divider: int            # initial byte of the divider cell
    divider_reload: int
    phase: int              # initial byte of the phase cell
    phase_reload: int       # steps - 1
    outer: Optional[int]    # initial byte of the outer gate's cell; None:
    #                         the player has no outer gate (every call runs
    #                         the row clock -- `_pitch_seq_flat_clock`)
    inner: int              # initial byte of the speed gate's cell


# `_pitch_seq_flat_clock`'s pieces, Mega_Apocalypse's spelling ($4AEA,
# $4AF9, $4E78, $580F). The voice loop's exit sits directly in front of the
# phase's `DEC`, so the cell steps once per call after all three voices.
PITCH_SEQ_VOICE_EXIT = bytes([0xCA, 0x30, 0x03, 0x4C])     # DEX / BMI +3 / JMP
# `LDA zp / CMP abs / BNE` -- a voice takes a row only on the call that
# reloaded the zero-page speed counter (`fixed_arp_first_fetch`'s guard).
PITCH_SEQ_ZP_FETCH_GUARD = re.compile(rb"\xa5(.)\xcd(..)\xd0", re.DOTALL)
PITCH_SEQ_ZP_GUARD_WINDOW = 16
# `LDX #n / LDA #0 / STA zp,X / DEX / BPL -5`: the init's clear of the
# player's zero-page state, cells `zp .. zp + n`.
PITCH_SEQ_ZP_CLEAR = re.compile(rb"\xa2(.)\xa9\x00\x95(.)\xca\x10\xfb",
                                re.DOTALL)
PITCH_SEQ_INIT_WINDOW = 0x60     # bytes of the PSID init searched for its JSR
# Every opcode that can write an absolute cell -- STA/STX/STY abs[,X/Y],
# INC/DEC abs[,X], ASL/LSR/ROL/ROR abs[,X].
_ABS_WRITERS = (0x8D, 0x9D, 0x99, 0x8E, 0x8C, 0xEE, 0xFE, 0xCE, 0xDE,
                0x0E, 0x1E, 0x4E, 0x5E, 0x2E, 0x3E, 0x6E, 0x7E)


def _init_clears_zp(sid: SidFile, cell: int) -> bool:
    """Whether the PSID init's first-song path zeroes zero-page `cell`.

    Mega_Apocalypse's init ($5822) ends `PLA / BNE $5882 / JSR $4AA0` -- the
    first song (A = 0) takes the `JSR` -- and `$4AA0` is the player's own
    `JMP init` ($580F: `LDX #$44 / LDA #$00 / STA $B0,X / DEX / BPL`), so the
    whole of `$B0-$F4`, the speed counter `$DF` among it, reads 0 on the
    first play call. Required in that order -- a `JSR` in the init's first
    `PITCH_SEQ_INIT_WINDOW` bytes onto a `JMP` onto the clear loop, the cell
    inside the loop's range -- and False otherwise: a zero-page cell holds no
    file byte, so this is the only reading of its first value there is.
    """
    data = sid.data
    start = sid.to_offset(sid.init_addr)
    if not 0 <= start < len(data):
        return False
    for p in range(start, min(start + PITCH_SEQ_INIT_WINDOW, len(data) - 2)):
        if data[p] != 0x20:
            continue
        t = sid.to_offset(data[p + 1] | data[p + 2] << 8)
        if not 0 <= t < len(data) - 2 or data[t] != 0x4C:
            continue
        j = sid.to_offset(data[t + 1] | data[t + 2] << 8)
        if not 0 <= j < len(data):
            continue
        m = PITCH_SEQ_ZP_CLEAR.match(data, j)
        if m is not None and m.group(2)[0] <= cell <= (
                m.group(2)[0] + m.group(1)[0]):
            return True
    return False


def _pitch_seq_flat_clock(sid: SidFile,
                          det: Detection) -> Optional[PitchSeqClock]:
    """The UNDIVIDED bit-$10 clock, read from Mega_Apocalypse's shape.

    The phase cell steps once per call and the row clock has no outer gate:

        4AA6  ... BIT $E5 / BMI / BVC $4AE8        ; play entry
        4AB1  (new song) clear the voices ... JMP $4E7E
        4AE8  LDX #$02 / DEC $DF / BPL +5 / LDA $4F61 / STA $DF   ; speed
        4AF3  voice loop: LDA $DF / CMP $4F61 / BNE (no fetch) ...
        4DF2  ... the bit-$10 block: LDY $51BF ...
        4E78  DEX / BMI +3 / JMP $4AF3              ; voice loop exit
        4E7E  DEC $51BF / BPL / LDA #$02 / STA $51BF ; the phase

    so the new-song call steps the phase and nothing else, and each later
    call reloads `$DF` on its underflow, fetches a row on that call, reads
    the phase in the voice loop and steps it after. `$DF` is zero page, so
    its first value is the init's (`_init_clears_zp`); the phase cell's is
    its file byte, and nothing but the reload writes it. Every piece is
    required, as `_pitch_seq_clock`'s are, and None otherwise.

    Expressed as a `PitchSeqClock` with a divider that reloads to 0 (so the
    phase steps every call) and `outer=None`.
    """
    seq = det.pitch_seq
    if seq is None or seq.frames_per_step != 1 or seq.pairs < 0:
        return None
    data = sid.data
    at = -1
    for shape, _ in PITCH_SEQ_SHAPES:
        at = search_file(data, shape)
        if at >= 1:
            break
    if at < 1:
        return None
    lo, hi = data[at + PITCH_SEQ_AT_PHASE], data[at + PITCH_SEQ_AT_PHASE + 1]
    dec = bytes([0xCE, lo, hi, 0x10])
    reload_at = data.find(dec)
    while reload_at >= 0:
        j = reload_at
        if (j + 9 < len(data) and data[j + 5] == 0xA9
                and data[j + 7] == 0x8D and data[j + 8] == lo
                and data[j + 9] == hi):
            break
        reload_at = data.find(dec, reload_at + 1)
    if reload_at < 6:
        return None
    if data[reload_at - 6:reload_at - 2] != PITCH_SEQ_VOICE_EXIT:
        return None
    writes = sum(data.count(bytes([op, lo, hi])) for op in _ABS_WRITERS)
    if writes != 2:                      # the DEC and the reload's STA only
        return None
    phase_addr = sid.to_address(reload_at)
    if data.find(bytes([0x4C, phase_addr & 0xFF, phase_addr >> 8])) < 0:
        return None                      # no new-song JMP to the phase
    if OUTER_GATE.search(data) is not None:
        return None
    hits = [m for m in SPEED_GATE_ZP.finditer(data)
            if m.group(1) == m.group(3)]
    if not hits:
        return None
    g = min(hits, key=lambda m: abs(m.start() - det.instr_start))
    cell = g.group(1)[0]
    guard = PITCH_SEQ_ZP_FETCH_GUARD.search(
        data, g.end(), g.end() + PITCH_SEQ_ZP_GUARD_WINDOW)
    if guard is None or guard.group(1)[0] != cell or guard.group(2) != g.group(2):
        return None
    if not _init_clears_zp(sid, cell):
        return None
    off = sid.to_offset(lo | hi << 8)
    if not 0 <= off < len(data):
        return None
    return PitchSeqClock(divider=0, divider_reload=0, phase=data[off],
                         phase_reload=data[reload_at + 6], outer=None,
                         inner=0)


def _pitch_seq_clock(sid: SidFile, det: Detection) -> Optional[PitchSeqClock]:
    """The counters `pitch_seq_phases` simulates, read from Food_Feud's shape.

    Food_Feud is the one corpus player whose bit-$10 phase is DIVIDED
    (`detect._pitch_seq_divider`), and its play routine is, in full order:

        905E  DEC $953A / BPL +8 / LDA #$03 / STA $953A / JMP $9076  ; outer
        906B  DEC $9538 / BPL +6 / LDA $9539 / STA $9538             ; speed
        9076  ... LDA $953A / BEQ nofetch / LDA $9538 / CMP $9539 / BNE nofetch
              ... the voice loop: bit $10 reads `LDY $955D` ...
        93FB  DEC $955E / BPL / LDA #$03 / STA $955E                 ; divider
        9405  DEC $955D / BPL / LDA #$01 / STA $955D                 ; phase

    and the new-song call (`BIT $953D`, set by the init) runs NONE of the
    row clock: it clears the voices and `JMP $93FB`s straight to the
    divider. Nothing writes the four cells but the code above, so the
    file's bytes are the state at the init.

    Required in full -- the outer `JMP` gate with the speed gate directly
    behind it, the fetch guard naming the outer cell, the divider block
    ten bytes before the phase reload, and a `JMP` to that divider -- and
    None otherwise: no other corpus player has a divider, and a clock
    assumed rather than read would put a wrong phase on every note.

    The UNDIVIDED counter is `_pitch_seq_flat_clock`'s; `_pitch_seq_any_clock`
    is the one the phase walks ask.
    """
    seq = det.pitch_seq
    if seq is None or seq.frames_per_step <= 1 or seq.pairs < 0:
        return None
    data = sid.data
    at = -1
    for shape, _ in PITCH_SEQ_SHAPES:
        at = search_file(data, shape)
        if at >= 1:
            break
    if at < 1:
        return None
    lo, hi = data[at + PITCH_SEQ_AT_PHASE], data[at + PITCH_SEQ_AT_PHASE + 1]
    reload_at = data.find(bytes([0xCE, lo, hi, 0x10]))
    while reload_at >= 0:
        j = reload_at
        if (j + 9 < len(data) and data[j + 5] == 0xA9
                and data[j + 7] == 0x8D and data[j + 8] == lo
                and data[j + 9] == hi):
            break
        reload_at = data.find(bytes([0xCE, lo, hi, 0x10]), reload_at + 1)
    if reload_at < 10:
        return None
    d = reload_at - 10
    if not (data[d] == 0xCE and data[d + 3] == 0x10 and data[d + 5] == 0xA9
            and data[d + 7] == 0x8D and data[d + 8:d + 10] == data[d + 1:d + 3]):
        return None
    div_addr = sid.to_address(d)
    if data.find(bytes([0x4C, div_addr & 0xFF, div_addr >> 8])) < 0:
        return None                      # no new-song JMP to the divider
    m = OUTER_GATE.search(data)
    if m is None or m.group(1) != m.group(3):
        return None
    g = SPEED_GATE.match(data, m.end())
    if g is None or g.group(1) != g.group(3):
        return None
    target = sid.to_offset(m.group(4)[0] | m.group(4)[1] << 8)
    if target != g.end():
        return None
    outer = m.group(1)
    guard = bytes([0xAD, outer[0], outer[1], 0xF0])
    if data.find(guard, target, target + 16) < 0:
        return None
    cells = []
    for cell in (bytes(data[d + 1:d + 3]), bytes([lo, hi]), outer, g.group(1)):
        off = sid.to_offset(cell[0] | cell[1] << 8)
        if not 0 <= off < len(data):
            return None
        cells.append(data[off])
    return PitchSeqClock(divider=cells[0], divider_reload=data[d + 6],
                         phase=cells[1], phase_reload=data[reload_at + 6],
                         outer=cells[2], inner=cells[3])


def _pitch_seq_any_clock(sid: SidFile,
                         det: Detection) -> Optional[PitchSeqClock]:
    """The bit-$10 clock the phase walks simulate: the divided one
    (`_pitch_seq_clock`, Food_Feud) or the undivided one
    (`_pitch_seq_flat_clock`, Mega_Apocalypse), or None."""
    return _pitch_seq_clock(sid, det) or _pitch_seq_flat_clock(sid, det)


def _countdown(value: int, reload: int) -> tuple:
    """One `DEC cell / BPL / LDA #reload / STA cell`: (new value, reloaded)."""
    value = (value - 1) & 0xFF
    return (reload, True) if value & 0x80 else (value, False)


def _pitch_seq_advance(clock: PitchSeqClock, state: tuple) -> tuple:
    """(divider, phase) after one pass of the divider block."""
    div, ph = state
    div, under = _countdown(div, clock.divider_reload)
    if under:
        ph, _ = _countdown(ph, clock.phase_reload)
    return div, ph


def _pitch_seq_calls(clock: PitchSeqClock, frames: int, skip: int):
    """Yield (seen, fetched, after) for play calls 1, 2, 3, ... forever.

    `seen` is the (divider, phase) the call's voice loop reads -- the bit-$10
    block runs before the divider does -- `fetched` whether the row clock
    fetched a row on it, and `after` the state the call leaves, which is what
    `siddump -w` samples. Call 0, the new-song call, runs the divider and
    nothing else (`_pitch_seq_clock`), so it is applied before the first
    yield rather than yielded.
    """
    state = _pitch_seq_advance(clock, (clock.divider, clock.phase))
    outer, inner = clock.outer, clock.inner
    while True:
        seen = state
        if outer is None:                # no outer gate: every call counts
            inner, _ = _countdown(inner, frames - 1)
            fetch = inner == frames - 1
        else:
            outer, under = _countdown(outer, skip)
            if not under:
                inner, _ = _countdown(inner, frames - 1)
            fetch = outer != 0 and inner == frames - 1
        state = _pitch_seq_advance(clock, state)
        yield seen, fetch, state


def _pitch_seq_rate_read(clock: PitchSeqClock, frames, skip,
                         group: int) -> bool:
    """Whether subtune `group`'s row clock is one `clock` can walk: a row
    length, and an outer gate exactly where the clock read one. The flat
    clock (`outer=None`) is the first subtune's only -- its speed counter's
    first value was read on the init's first-song path (`_init_clears_zp`)."""
    if not frames:
        return False
    if clock.outer is None:
        return not skip and group == 0
    return bool(skip)


def pitch_seq_phases(sid: SidFile, det: Detection, tracks: List[List[int]],
                     patterns: List[List[int]]) -> dict:
    """{Goattracker instrument: bit $10's phase on frames 1.. after attack}.

    The phase cell is GLOBAL and never restarts at a note, and a wavetable
    restarts at every one. Where the counter is divided (Food_Feud, 4 frames
    a step on a 2-step cell, so an 8-frame cycle) a per-note wavetable that
    opens on the zero step first moves at attack + 5, while the original
    moves at attack + 1 or + 3. This carries the phase the way
    `fixed_arp_phases` carries the fixed octave's: the state on each attack
    frame is static -- the clock (`_pitch_seq_clock`) is simulated call by
    call, the row grid walked over the finished orderlists, each note votes
    for its instrument, and the instrument takes the majority. A tie goes to
    the lowest (divider, phase) state.

    The value is the phase cell's reading on frames `1 .. period` after the
    attack (the attack frame sounds the pattern's own note in the original,
    whatever the cell reads); `period` is the counter's whole cycle,
    `(divider_reload + 1) * (phase_reload + 1)` frames.

    **Measured** against `siddump -w955d,955e` of the original over 180 s:
    the simulated cells equal the dumped ones on every frame 1-8999, and the
    walked grid puts all 748 + 1042 + 734 attacks on the original's frames
    (`C:/t/pitch-seq-phase/model_probe.py`, `walk_probe.py`). A tied row
    (`CMD_TONEPORTA` 0) restarts no wavetable and casts no vote.

    The majority is thin -- Food_Feud's rows are 8/3 frames, so a record's
    notes split three ways by row mod 3 -- and `pitch_seq_phase_split_plan`
    gives each minority state a clone of its own; this stays the record's.

    Empty wherever no clock is read (`_pitch_seq_any_clock`), which is every
    file but Food_Feud and Mega_Apocalypse.
    """
    clock = _pitch_seq_any_clock(sid, det)
    if clock is None:
        return {}
    speeds = _gw_tempo.find_song_speeds(sid, det)
    if speeds is None:
        return {}
    groups = len(tracks) // 3
    if groups > max(sid.subtunes, 1):
        return {}                        # a split subtune shifted the numbering
    votes: dict = {}
    for g in range(groups):
        frames, skip = speeds.frames_for(g), speeds.skip_for(g)
        if not _pitch_seq_rate_read(clock, frames, skip, g):
            continue
        notes = []
        for ti in range(3 * g, 3 * g + 3):
            for row, instr, pat, r in _walk_note_rows(tracks[ti], patterns):
                if pat[r + 2] == CMD_TONEPORTA and pat[r + 3] == 0:
                    continue
                notes.append((row, instr))
        if not notes:
            continue
        need = max(row for row, _ in notes) + 1
        fetched = _pitch_seq_fetched(clock, frames, skip, need)
        for row, instr in notes:
            if row < len(fetched):
                tally = votes.setdefault(instr, {})
                tally[fetched[row]] = tally.get(fetched[row], 0) + 1
    out = {}
    for instr, tally in votes.items():
        best = max(sorted(tally), key=lambda s: tally[s])
        out[instr] = _pitch_seq_frames_after(clock, best)
    return out


def _pitch_seq_fetched(clock: PitchSeqClock, frames: int, skip: int,
                       need: int) -> List[tuple]:
    """The (divider, phase) state the voice loop reads on each of the first
    `need` row fetches -- row `k`'s attack state is element `k`."""
    fetched: List[tuple] = []
    calls = _pitch_seq_calls(clock, frames, skip)
    for _ in range(need * (frames + 1) * ((skip or 0) + 1) + 64):
        if len(fetched) >= need:
            break
        seen, fetch, _after = next(calls)
        if fetch:
            fetched.append(seen)
    return fetched


def _pitch_seq_frames_after(clock: PitchSeqClock, state: tuple) -> tuple:
    """The phase cell on frames `1 .. period` after an attack read in
    `state` -- the value `pitch_seq_phases` carries per instrument."""
    period = (clock.divider_reload + 1) * (clock.phase_reload + 1)
    frames_after = []
    for _ in range(period):
        state = _pitch_seq_advance(clock, state)
        frames_after.append(state[1])
    return tuple(frames_after)


def pitch_seq_note_phases(sid: SidFile, det: Detection,
                          tracks: List[List[int]],
                          patterns: List[List[int]]) -> Optional[dict]:
    """{(track, orderlist position, play): {row: phase tuple}} -- the walk
    `pitch_seq_phases` votes from, keyed by where each note sits so
    `pitch_seq_phase_split_plan` can rename it (`fixed_arp_note_residues`'
    shape). The value is `_pitch_seq_frames_after` of the note's own attack
    state, i.e. what `pitch_seq_phases` would give its instrument were this
    note the whole vote. None wherever `pitch_seq_phases` is empty for want
    of a clock or a row length.
    """
    clock = _pitch_seq_any_clock(sid, det)
    if clock is None:
        return None
    speeds = _gw_tempo.find_song_speeds(sid, det)
    if speeds is None:
        return None
    if len(tracks) // 3 > max(sid.subtunes, 1):
        return None
    out: dict = {}
    tuples: dict = {}
    for g in range(len(tracks) // 3):
        frames, skip = speeds.frames_for(g), speeds.skip_for(g)
        if not _pitch_seq_rate_read(clock, frames, skip, g):
            continue
        laid = []                            # (ti, pos, play, {k: row})
        need = 0
        for ti in range(3 * g, 3 * g + 3):
            row, seen = 0, Counter()
            for pos, p in _orderlist_occurrences(tracks[ti]):
                if p >= len(patterns):
                    continue
                pat = patterns[p]
                play = seen[pos]
                seen[pos] += 1
                rows = {}
                for r in range(0, len(pat), 4):
                    if pat[r] == 0xFF:
                        break
                    if GT_FIRST_NOTE <= pat[r] <= GT_LAST_NOTE:
                        rows[r // 4] = row
                        need = max(need, row + 1)
                    row += 1
                laid.append((ti, pos, play, rows))
        fetched = _pitch_seq_fetched(clock, frames, skip, need)
        for ti, pos, play, rows in laid:
            res = out.setdefault((ti, pos, play), {})
            for k, row in rows.items():
                if row < len(fetched):
                    state = fetched[row]
                    if state not in tuples:
                        tuples[state] = _pitch_seq_frames_after(clock, state)
                    res[k] = tuples[state]
    return out


def pitch_seq_phase_split_plan(sid: SidFile, det: Detection,
                               tracks: List[List[int]],
                               patterns: List[List[int]], lead: int,
                               instr_used: int, first_clone: int,
                               distinct=None,
                               log=None) -> Optional[ArpPhaseSplit]:
    """Clone each bit-$10 record whose notes attack in more than one state
    of the divided phase counter, one clone per minority state within
    `FIXED_ARP_SPLIT_FACTOR` of the majority, and rename each such note to
    its state's clone -- `fixed_arp_phase_split_plan` for bit $10.

    `pitch_seq_phases` gives each RECORD one phase, the majority of its
    notes'. On Food_Feud a row is 8/3 frames against the counter's 8-frame
    cycle, so a record's notes attack in three states, one per row mod 3,
    nearly evenly (GT 4 at v0.5.496: 102 / 100 / 95 notes) -- and the
    majority's wavetable sounds the other two thirds out of phase. Each
    clone is the record with the wavetable its state names (the clones'
    third slot is the phase tuple, which `_wavetable_layout` hands to
    `_wavetable_entries` as `pitch_phase`); a state whose block would be the
    record's (`distinct`) gets none. Callers gate on `pitch_seq`, GTS5 and
    `det.pitch_seq`, exactly as `pitch_seq_phases`' caller does; empty
    wherever no clock is read, which is every file but Food_Feud and
    Mega_Apocalypse.
    """
    if det.pitch_seq is None:
        return None
    phases = pitch_seq_phases(sid, det, tracks, patterns)
    if not phases:
        return None
    residues = pitch_seq_note_phases(sid, det, tracks, patterns)
    if residues is None:
        return None
    data = sid.data
    records = set()
    for i in range(max(instr_used - lead, 0)):
        at = det.instr_start + i * det.instr_stride + 7
        if at < len(data) and data[at] & EFFECT_PITCH_SEQ_MASK:
            records.add(i + lead + 1)
    if not records:
        return None
    # A repeated orderlist entry plays one pattern's bytes several times, and
    # `_note_phase_split` keeps its first play's spelling for all of them. On
    # Food_Feud the repeats are the phase's own problem: `D3 10` plays a
    # pattern four times, each a row count later, so each play wants its own
    # clones -- 72 of the bit-$10 records' 805 notes were left on another
    # play's phase. Such an entry is unrolled into one entry per play
    # (`_expand_repeats`) wherever its plays want different phases; the
    # copies then share a pattern wherever their spellings agree.
    unroll = _phase_divergent_repeats(tracks, patterns, residues, records)
    if unroll:
        wide = [(_expand_repeats(t, unroll.get(ti, set())) or t)
                if ti in unroll else t for ti, t in enumerate(tracks)]
        if wide != tracks:
            wide_res = pitch_seq_note_phases(sid, det, wide, patterns)
            if wide_res is not None:
                tracks, residues = wide, wide_res
    return _note_phase_split(tracks, patterns, residues, phases, records,
                             first_clone, distinct, "pitch phase split", log)


def _phase_divergent_repeats(tracks: List[List[int]],
                             patterns: List[List[int]], residues: dict,
                             records: set) -> dict:
    """{track: {orderlist positions}} of the repeated entries whose plays
    give one of `records`' untied notes different residues -- the walk
    `_note_phase_split` votes in, instrument column sticky."""
    out: dict = {}
    for ti, track in enumerate(tracks):
        cur = 0
        heard: dict = {}                     # pos -> set of per-play spellings
        seen = Counter()
        for pos, p in _orderlist_occurrences(track):
            if p >= len(patterns):
                continue
            play = seen[pos]
            seen[pos] += 1
            pat, res = patterns[p], residues.get((ti, pos, play), {})
            spelling = []
            for k in range(len(pat) // 4):
                if pat[k * 4] == 0xFF:
                    break
                if pat[k * 4 + 1]:
                    cur = pat[k * 4 + 1]
                tied = (pat[k * 4 + 2] == CMD_TONEPORTA
                        and pat[k * 4 + 3] == 0)
                if k in res and not tied and cur in records:
                    spelling.append((k, cur, res[k]))
            heard.setdefault(pos, set()).add(tuple(spelling))
        for pos, spellings in heard.items():
            if seen[pos] > 1 and len(spellings) > 1:
                out.setdefault(ti, set()).add(pos)
    return out


def _expand_repeats(track: List[int], positions: set) -> Optional[List[int]]:
    """`track` with each repeat whose pattern byte sits at one of
    `positions` written out as that many plain entries -- the same plays,
    one orderlist entry each. The `$FF` restart operand is moved with the
    bytes: a restart at the repeat byte lands on the first copy, one at the
    pattern byte (which plays it once) on the last. None if the result
    would pass Goattracker's 254-byte orderlist (gcommon.h MAX_SONGLEN) or
    the restart names a byte that no longer exists."""
    out: List[int] = []
    where: dict = {}
    restart_at = None
    i, operand = 0, False
    while i < len(track):
        b = track[i]
        if operand:
            restart_at = len(out)
            out.append(b)
            operand = False
            i += 1
            continue
        if b == 0xFF:
            operand = True
        elif (0xD0 <= b < 0xE0 and i + 1 in positions
                and i + 1 < len(track) and track[i + 1] < 0xD0):
            n = b - 0xD0 + 1
            where[i] = len(out)
            where[i + 1] = len(out) + n - 1
            out += [track[i + 1]] * n
            i += 2
            continue
        where[i] = len(out)
        out.append(b)
        i += 1
    if restart_at is not None:
        if out[restart_at] not in where:
            return None
        out[restart_at] = where[out[restart_at]]
    if len(out) > 254:
        return None
    return out


def fixed_arp_duty_entries(wave: int, tail: int, mask: int, branch: int,
                           phase: int, arp_note: int, multiplier: int,
                           start: int, budget: int, written: bool = False,
                           tick: Optional[tuple] = None,
                           tie_row: Optional[int] = None) -> Optional[tuple]:
    """The wavetable for a fixed-interval record whose mask is a duty cycle.

    `tie_row` (a row length in frames, `fixed_arp_tie_rows`) asks for the
    row-locked shape a record played under tie chains needs instead
    (`fixed_arp_tie_row_entries`); where that declines, the duty shape below
    is returned as before.

    The block adds its octave on every call whose masked counter
    `fixed_arp_up` says so, and the counter steps once a frame, so the octave
    is a square wave in FRAMES with the mask's period (`fixed_arp_period`):
    `$02` two base and two up, `$04` four and four, `$07` one base and seven
    up. The untimed shape alternates every call, which is `$01`'s duty and
    nobody else's -- `tests/test_arp_octave.py`'s module docstring carries
    the A/B in which `vib`, the oscillation rate, overshot the original by up
    to 5x on the widened files for exactly that reason.

    **Measured on the originals** (v0.5.489, per-onset profiles, `b` base and
    `u` octave up from the attack frame): Zoids `buubbbbuuuubbbbuu` on 78 of
    108 onsets and `bbbuuuubbbbu` on 14 -- four and four, two phases;
    One_Man_and_his_Droid `buuubbbb` on 187 of 188; Master_of_Magic
    `buuuuuubuuuuuuub` on 174 of 244; Phantoms_of_the_Asteroid `buuuuuuu` on
    319 of 340; Chimera `bubuuuuuuubuuuuuu` on 42 of 56. Frame 0 is base in
    every profile: the init call runs no effect.

    Frame `j` after the attack is up where `fixed_arp_up(mask, branch,
    phase + j)`, `phase` being the counter's residue on the attack frame
    (`fixed_arp_phases`, or 0 -- the reset value -- where no walk is
    possible). The frames are then run-length coded onto the wavetable:

    * frame 0 is the record's own waveform (unless `written`, when the
      instrument's firstwave already owns it and the entries start at frame
      1 -- `_first_frame_lead`'s rule);
    * `tick` frames (`(noise byte, frames)`, the drum block's opening noise
      for a both-bits record) follow, each a waveform entry;
    * the first frame after them writes `tail` once;
    * from there on nothing writes a waveform: a delay entry is current for
      `value + 1` play calls and applies its right side on the LAST of them
      (gplay.c's wavetable-delay `else`, `wavetime != wave` / `wavetime++`;
      player.s `mt_waveexec`, `cmp mt_chnwavetime,x / beq mt_nowavechange /
      inc mt_chnwavetime,x`), so a run of N calls in one state followed by a
      change is ONE entry, `(N - 1, new note)`, split at `WAVE_MAX_DELAY`;
    * the loop body is one whole period of frames, starting on the call after
      a transition so that its last entry fires the same transition a cycle
      later, and the jump lands on its first entry (a jump is read on the
      entry BEFORE it and costs no call, gplay.c's `ptr[WTBL]++` then
      `== 0xff` test).

    **One frame is `multiplier` play calls.** Every run above is in frames
    and is multiplied out here -- and a "frame" of the counter is one call
    that passed the outer gate, `(R + 1) / R` real frames where the player
    has one, which the caller folds into `multiplier` (`_gate_calls`:
    Game_Killer's 10 at -S9). The -S2 and -S3 shapes are pinned by
    `tests/test_arp_octave.py` at every residue rather than by any corpus
    byte. Returns None where the entries would not fit `budget`.
    """
    if tie_row is not None:
        shaped = fixed_arp_tie_row_entries(wave, tail, mask, branch, phase,
                                           arp_note, multiplier, start,
                                           budget, tie_row, written, tick)
        if shaped is not None:
            return shaped
    m = max(1, multiplier)
    period = fixed_arp_period(mask)
    tick_noise, tick_frames = tick if tick else (None, 0)
    first = 1 if written else 0
    tail_frame = tick_frames + 1

    def raw(j: int) -> bool:             # what the counter says on frame j
        return fixed_arp_up(mask, branch, phase + j)

    def up(j: int) -> bool:              # what sounds: frame 0 is the init
        return j > 0 and raw(j)

    # The body starts on a transition of the COUNTER's cycle, not of what
    # sounds -- frame 0 is base whatever the counter says, so `up(1) !=
    # up(0)` is not a transition the wrap a period later repeats.
    body = next((j for j in range(tail_frame, tail_frame + period)
                 if raw(j) != raw(j - 1)), None)
    if body is None:
        return None                      # a mask with no transition at all
    last_frame = body + period           # its first call fires the wrap
    notes = {False: WAVE_NOTE_BASE, True: arp_note}
    # call -> (waveform byte or None, note or None)
    events: dict = {}
    for j in range(first, last_frame + 1):
        wf = None
        if j == 0:
            wf = wave
        elif j <= tick_frames:
            wf = tick_noise
        elif j == tail_frame:
            wf = tail
        fires = j == first or up(j) != up(j - 1)
        if wf is not None or fires:
            events[j * m] = (wf, notes[up(j)] if fires else None)
    end = last_frame * m + 1
    left: List[int] = []
    right: List[int] = []
    starts: List[int] = []

    def fill(t: int, upto: int) -> None:  # calls t..upto, nothing fires
        while t <= upto:
            n = min(upto - t, WAVE_MAX_DELAY)
            starts.append(t)
            left.append(n)
            right.append(0x80)
            t += n + 1

    t = first * m
    pending = sorted(events)
    while t < end:
        nxt = next((c for c in pending if c >= t), None)
        if nxt is None:
            fill(t, end - 1)
            break
        wf, note = events[nxt]
        if wf is not None:
            if nxt > t:
                fill(t, nxt - 1)
            starts.append(nxt)
            left.append(wf)
            right.append(0x80 if note is None else note)
        else:
            while nxt - t > WAVE_MAX_DELAY:
                starts.append(t)
                left.append(WAVE_MAX_DELAY)
                right.append(0x80)
                t += WAVE_MAX_DELAY + 1
            starts.append(t)
            left.append(nxt - t)
            right.append(note)
        t = nxt + 1
    loop = starts.index(body * m + 1)
    left.append(WAVE_JUMP)
    right.append((start + loop) & 0xFF)
    if len(left) > budget:
        return None
    return left, right


def fixed_arp_tie_row_entries(wave: int, tail: int, mask: int, branch: int,
                              phase: int, arp_note: int, multiplier: int,
                              start: int, budget: int, row: int,
                              written: bool = False,
                              tick: Optional[tuple] = None) -> Optional[tuple]:
    """The row-locked wavetable for a duty record played under tie chains.

    `row` is the record's one row length in frames (`fixed_arp_tie_rows`).
    Frames are counted from the audible attack, as `fixed_arp_duty_entries`
    counts them; the wavetable's first entry runs on tick 1 (the init call
    runs none, player.s `jmp mt_loadregswaveonly`), so frame `j` is tick
    `(j + 1) % row` -- or `j % row` where `written`, the firstwave owning
    the attack frame.

    * Up to the first tick 0 the attack row follows the counter exactly as
      the duty shape does (`fixed_arp_up` from `phase`), and the record's
      waveform, `tick` noise and `tail` land on the same frames.
    * From there each frame writes the octave where its tick is 2 or more
      and nothing on ticks 0 and 1 (see the comment above).
    * The loop is one row from a tick 0: `(2, octave)`, then `(0, octave)`
      for each tick past 2, and the jump.

    -S1 only and a row of at least 3 frames (at 2 no tick is left to carry
    the octave); None otherwise, or where the entries would not fit
    `budget`, and the caller keeps the duty shape.
    """
    if multiplier != 1 or row < 3:
        return None
    tick_noise, tick_frames = tick if tick else (None, 0)
    first = 1 if written else 0
    tail_frame = tick_frames + 1

    def tk(j: int) -> int:
        return (j % row) if written else ((j + 1) % row)

    def up(j: int) -> bool:
        return j > 0 and fixed_arp_up(mask, branch, phase + j)

    def waveform(j: int) -> Optional[int]:
        if j == 0:
            return wave
        if j <= tick_frames:
            return tick_noise
        if j == tail_frame:
            return tail
        return None

    attack_row = next(j for j in range(1, row + 1) if tk(j) == 0)
    body = next(j for j in range(max(attack_row, tail_frame + 1),
                                 tail_frame + 1 + row) if tk(j) == 0)
    events: dict = {}
    cur = None
    for j in range(first, body):
        note = None
        if j < attack_row:
            if j == first or up(j) != cur:
                cur = up(j)
                note = arp_note if cur else WAVE_NOTE_BASE
        elif tk(j) >= 2:
            note = arp_note
        wf = waveform(j)
        if wf is not None or note is not None:
            events[j] = (wf, note)
    left: List[int] = []
    right: List[int] = []
    t = first
    for j in sorted(events):
        wf, note = events[j]
        if wf is not None:
            while t < j:                 # calls t..j-1 write nothing
                n = min(j - 1 - t, WAVE_MAX_DELAY)
                left.append(n)
                right.append(0x80)
                t += n + 1
            left.append(wf)
            right.append(0x80 if note is None else note)
        else:
            while j - t > WAVE_MAX_DELAY:
                left.append(WAVE_MAX_DELAY)
                right.append(0x80)
                t += WAVE_MAX_DELAY + 1
            left.append(j - t)
            right.append(note)
        t = j + 1
    while t < body:
        n = min(body - 1 - t, WAVE_MAX_DELAY)
        left.append(n)
        right.append(0x80)
        t += n + 1
    loop = len(left)
    left.append(2)
    right.append(arp_note)
    for _ in range(row - 3):
        left.append(0)
        right.append(arp_note)
    left.append(WAVE_JUMP)
    right.append((start + loop) & 0xFF)
    if len(left) > budget:
        return None
    return left, right


def fixed_arp_tie_rows(sid: SidFile, det: Detection, tracks: List[List[int]],
                       patterns: List[List[int]]) -> dict:
    """{Goattracker instrument: row frames} for duty records played tied.

    A record qualifies where more than `FIXED_ARP_TIE_SHARE` of the ROWS it
    sounds on -- a note's own row and the rows it is held through, up to the
    voice's next note -- are tie rows (`CMD_TONEPORTA $00` on a note), and
    every group that plays it
    has one and the same row length -- the shape is a loop of one row, so a
    record heard at two tempos has no row to lock to. Duty masks only (the
    parity mask `$01` keeps its shapes), and no group behind an outer gate
    (`SongSpeeds.skip`: a row there is not a whole number of frames). The
    walk is `fixed_arp_phases`'s; a split subtune that shifted the numbering
    gives an empty result, as it does there.

    **Rows, not notes**: a held row runs no tie, so there the duty shape is
    the right one (it carries the counter's base frame, the row shape does
    not). Chimera's GT 12 has 5 tie notes of 7 but 166 rows, 159 of them
    held; voting by notes sent it to the row shape and `vib` read 0.84
    where leaving it on the duty shape reads 0.85.
    """
    mask = _gw_primitives.fixed_arp_mask(sid, det)
    if mask is None or mask[0] == FIXED_ARP_PARITY_MASK:
        return {}
    speeds = _gw_tempo.find_song_speeds(sid, det)
    if speeds is None:
        return {}
    if len(tracks) // 3 > max(sid.subtunes, 1):
        return {}
    ties: dict = {}
    played: dict = {}
    rows: dict = {}
    for ti, track in enumerate(tracks):
        frames = speeds.frames_for(ti // 3)
        if speeds.skip_for(ti // 3):
            frames = None
        walk = [(row, current, pat[r + 2] == CMD_TONEPORTA and pat[r + 3] == 0)
                for row, current, pat, r in _walk_note_rows(track, patterns)]
        for k, (row, current, tie) in enumerate(walk):
            held = walk[k + 1][0] - row if k + 1 < len(walk) else 1
            played[current] = played.get(current, 0) + held
            rows.setdefault(current, set()).add(frames)
            if tie:
                ties[current] = ties.get(current, 0) + 1
    out = {}
    for instr, n in played.items():
        lengths = rows[instr]
        if (ties.get(instr, 0) > FIXED_ARP_TIE_SHARE * n and len(lengths) == 1
                and None not in lengths):
            out[instr] = next(iter(lengths))
    return out


@dataclass
class TempoDutySplit:
    """What `tempo_duty_split_plan` decided: tracks and patterns with the
    copies already made (identical bytes until `apply_tempo_duty_edits`),
    the clones as (record GT number, clone GT number, calls a step), and the
    instrument-column edits as {pattern: {row: (byte now, byte wanted)}}."""
    tracks: List[List[int]]
    patterns: List[List[int]]
    clones: List[Tuple[int, int, int]]
    edits: dict


def _orderlist_occurrences(track: List[int]):
    """(position of the pattern byte, pattern) for every pattern played, in
    play order, one lap, a repeat expanded -- the walk `fixed_arp_phases`
    makes, yielding the byte's position so a caller can repoint it."""
    repeat, operand = 1, False
    for pos, b in enumerate(track):
        if operand:
            operand = False
            continue
        if b == 0xFF:
            operand = True
            continue
        if 0xE0 <= b < 0xFF:
            continue
        if 0xD0 <= b < 0xE0:
            repeat = b - 0xD0 + 1
            continue
        for _ in range(repeat):
            yield pos, b
        repeat = 1


def tempo_duty_split_plan(sid: SidFile, det: Detection,
                          tracks: List[List[int]],
                          patterns: List[List[int]], effects: bool,
                          lead: int, instr_used: int, multiplier: int,
                          gate_skip: Optional[int] = None,
                          log=None) -> Optional[TempoDutySplit]:
    """Split each duty-arpeggio record whose notes play at more than one
    whole-number counter step, or None where nothing would change.

    Only for a duty mask behind a gated counter whose reload is a CELL
    (`fixed_arp_counter_gated` and no `SongSpeeds.skip`: Rasputin) -- the
    immediate reload (Game_Killer) is one step for the whole song and
    `_gate_calls` already says it. The tempo a note plays at is the last
    global `CMD_SETTEMPO` at or before its row on any of the subtune's three
    voices (Goattracker's rows advance in lockstep), in the finished
    patterns, so the clock is the one `orderlist_tempo_values` wrote.

    Conservative wherever the patterns cannot say it in one byte: a pattern
    occurrence whose notes of one record want two steps keeps the record; a
    repeated orderlist entry whose plays would need different bytes, a
    sticky instrument that would need naming on a `CMD_TONEPORTA` row, or a
    clone number past `TEMPO_DUTY_MAX_CLONE` or pattern count past 208 drops
    the whole split.
    """
    if not (effects and det.arp_fixed_up and det.effect_arp):
        return None
    mask = _gw_primitives.fixed_arp_mask(sid, det)
    if mask is None or mask[0] == FIXED_ARP_PARITY_MASK:
        return None
    if gate_skip or not fixed_arp_counter_gated(sid, det):
        return None
    speeds = _gw_tempo.find_song_speeds(sid, det)
    if speeds is None or any(speeds.skip):
        return None
    groups = len(tracks) // 3
    if groups > max(sid.subtunes, 1):
        return None
    base = _gate_calls(multiplier, gate_skip)
    data = sid.data
    duty = set()
    for i in range(max(instr_used - lead, 0)):
        at = det.instr_start + i * det.instr_stride + 7
        if at < len(data) and data[at] & 4:
            duty.add(i + lead + 1)
    if not duty:
        return None

    def step_for(tempo: Optional[int], frames: Optional[int]) -> int:
        if tempo is None or not frames or tempo % frames:
            return base
        return tempo // frames

    clone_of: dict = {}                  # (record, step) -> clone number
    # (track, position) -> the edit set every play of that entry wants
    wants: dict = {}
    for g in range(groups):
        frames = speeds.frames_for(g)
        starts = []                      # per voice: [(pos, pat, row0)]
        events = []
        for v in range(3):
            row, occ = 0, []
            for pos, p in _orderlist_occurrences(tracks[3 * g + v]):
                if p >= len(patterns):
                    continue
                pat = patterns[p]
                occ.append((pos, p, row))
                for r in range(0, len(pat), 4):
                    if pat[r] == 0xFF:
                        break
                    # Row 0 only: that is where a subtune's clock and an
                    # orderlist tempo change are written. A tempo past row 0
                    # is `patterns._compensate_fractional_rows` spending the
                    # part of a row the change rounded away -- the segment's
                    # step is still the change's, and reading the run's
                    # `b + 1` as a step would clone notes the player plays
                    # at the segment's rate.
                    if (r == 0 and pat[r + 2] == CMD_SETTEMPO
                            and pat[r + 3] < 0x80):
                        events.append((row, pat[r + 3]))
                    row += 1
            starts.append(occ)
        events.sort(key=lambda e: e[0])
        ev_rows = [e[0] for e in events]

        def tempo_at(row: int) -> Optional[int]:
            k = bisect_right(ev_rows, row) - 1
            return events[k][1] if k >= 0 else None

        for v in range(3):
            ti = 3 * g + v
            cur = new_cur = 0
            for pos, p, row0 in starts[v]:
                pat = patterns[p]
                rows = []
                for r in range(0, len(pat), 4):
                    if pat[r] == 0xFF:
                        break
                    rows.append(r // 4)
                # Which step each duty record's notes want in this play.
                c, per = cur, {}
                for k in rows:
                    if pat[k * 4 + 1]:
                        c = pat[k * 4 + 1]
                    if c in duty and GT_FIRST_NOTE <= pat[k * 4] <= GT_LAST_NOTE:
                        per.setdefault(c, set()).add(
                            step_for(tempo_at(row0 + k), frames))
                rename = {}
                for rec, steps in per.items():
                    if len(steps) == 1:
                        (s,) = steps
                        if s != base:
                            if (rec, s) not in clone_of:
                                clone_of[(rec, s)] = None
                            rename[rec] = (rec, s)
                edit = {}
                for k in rows:
                    b = pat[k * 4 + 1]
                    if b in rename:
                        edit[k] = (b, rename[b])
                # The sticky instrument this play inherits: name it on the
                # first note that relies on it where the new walk carries a
                # different one in from the previous play.
                want_in = rename.get(cur, cur)
                if new_cur != want_in:
                    for k in rows:
                        if pat[k * 4 + 1]:
                            break
                        if GT_FIRST_NOTE <= pat[k * 4] <= GT_LAST_NOTE:
                            if pat[k * 4 + 2] == CMD_TONEPORTA:
                                if log:
                                    log("tempo duty split: a sticky "
                                        "instrument lands on a tie; "
                                        "not splitting")
                                return None
                            edit[k] = (0, want_in)
                            break
                key = tuple(sorted(edit.items()))
                if wants.setdefault((ti, pos), key) != key:
                    if log:
                        log("tempo duty split: a repeated entry needs two "
                            "spellings; not splitting")
                    return None
                # Carry both walks to the end of the play.
                for k in rows:
                    b = pat[k * 4 + 1]
                    if b:
                        cur = b
                        e = edit.get(k)
                        new_cur = (e[1] if e else b)
                    elif k in edit:
                        new_cur = edit[k][1]
    if not clone_of:
        return None
    number = instr_used
    clones = []
    for rec, s in sorted(clone_of):
        number += 1
        clone_of[(rec, s)] = number
        clones.append((rec, number, s))
    if number > TEMPO_DUTY_MAX_CLONE:
        return None

    def resolve(key):
        return tuple((k, (old, w if isinstance(w, int) else clone_of[w]))
                     for k, (old, w) in key)

    # One spelling per pattern stays in place (the most common, the
    # unedited one on a tie); every other spelling gets a copy.
    by_pat: dict = {}
    for (ti, pos), key in wants.items():
        p = tracks[ti][pos]
        by_pat.setdefault(p, Counter())[resolve(key)] += 1
    new_tracks = [list(t) for t in tracks]
    new_patterns = [list(p) for p in patterns]
    edits: dict = {}
    copy_of: dict = {}
    for p, spellings in sorted(by_pat.items()):
        stay = max(spellings, key=lambda s: (spellings[s], not s))
        if stay:
            edits[p] = dict(stay)
        for s in spellings:
            if s == stay:
                continue
            copy_of[(p, s)] = len(new_patterns)
            if s:
                edits[len(new_patterns)] = dict(s)
            new_patterns.append(list(patterns[p]))
    if len(new_patterns) > 208:          # patterns.MAX_PATTERNS
        if log:
            log("tempo duty split: the copies would pass 208 patterns; "
                "not splitting")
        return None
    for (ti, pos), key in wants.items():
        n = copy_of.get((tracks[ti][pos], resolve(key)))
        if n is not None:
            new_tracks[ti][pos] = n
    if not edits:
        return None
    if log:
        log(f"tempo duty split: {len(clones)} clone(s) "
            f"{[(r, n, s) for r, n, s in clones]}, "
            f"{len(new_patterns) - len(patterns)} pattern copy(ies), "
            f"{sum(len(e) for e in edits.values())} instrument byte(s)")
    return TempoDutySplit(new_tracks, new_patterns, clones, edits)


def apply_tempo_duty_edits(patterns: List[List[int]],
                           split: Optional[TempoDutySplit],
                           log=None) -> List[List[int]]:
    """Write the split's instrument bytes, last -- after every pass that keys
    on an instrument number, so the clone is treated exactly as its record.
    An edit whose byte has moved since the plan is skipped and said."""
    if split is None:
        return patterns
    out = [list(p) for p in patterns]
    for p, rows in split.edits.items():
        for k, (old, new) in rows.items():
            at = k * 4 + 1
            if p < len(out) and at < len(out[p]) and out[p][at] == old:
                out[p][at] = new
            elif log:
                log(f"tempo duty split: pattern {p:02X} row {k} moved; "
                    "edit skipped")
    return out


@dataclass
class ArpPhaseSplit:
    """What `fixed_arp_phase_split_plan` decided, in `TempoDutySplit`'s shape
    (so `apply_tempo_duty_edits` writes its bytes): `clones` are (record GT
    number, clone GT number, residue)."""
    tracks: List[List[int]]
    patterns: List[List[int]]
    clones: List[Tuple[int, int, int]]
    edits: dict


def fixed_arp_note_residues(sid: SidFile, det: Detection,
                            tracks: List[List[int]],
                            patterns: List[List[int]]) -> Optional[tuple]:
    """(period, {(track, orderlist position, play): {row: residue}}).

    The walk `fixed_arp_phases` votes from -- `(base + first + row * frames)
    % period` in the player's passing-call clock -- keyed by where each note
    sits, so a caller can rename it. `play` counts the plays of a repeated
    orderlist entry. None wherever `fixed_arp_phases` is empty for want of a
    reading.
    """
    base = fixed_arp_counter_base(sid, det)
    first = fixed_arp_first_fetch(sid, det)
    mask = _gw_primitives.fixed_arp_mask(sid, det)
    if base is None or first is None or mask is None:
        return None
    period = fixed_arp_period(mask[0])
    speeds = _gw_tempo.find_song_speeds(sid, det)
    if speeds is None:
        return None
    if len(tracks) // 3 > max(sid.subtunes, 1):
        return None
    out: dict = {}
    for ti, track in enumerate(tracks):
        frames = speeds.frames_for(ti // 3)
        if frames is None:
            continue
        row, seen = 0, Counter()
        for pos, p in _orderlist_occurrences(track):
            if p >= len(patterns):
                continue
            pat = patterns[p]
            play = seen[pos]
            seen[pos] += 1
            res = out.setdefault((ti, pos, play), {})
            for r in range(0, len(pat), 4):
                if pat[r] == 0xFF:
                    break
                if GT_FIRST_NOTE <= pat[r] <= GT_LAST_NOTE:
                    res[r // 4] = (base + first + row * frames) % period
                row += 1
    return period, out


def arp_row_residues(sid: SidFile, det: Detection, tracks: List[List[int]],
                     patterns: List[List[int]]) -> Optional[dict]:
    """{(pattern, row): every residue that note row is played on} -- the
    counter `build_sng`'s `arp_phases` reads, in its own walk: the fixed
    arp's (`fixed_arp_phases`) where `det.arp_fixed_up`, else the nibble
    dialect's (`nibble_arp_phases`). One lap of each orderlist, repeats
    expanded; a pattern played at several places collects each one's
    residue. None where neither counter is read."""
    if det.arp_fixed_up:
        base = fixed_arp_counter_base(sid, det)
        mask = _gw_primitives.fixed_arp_mask(sid, det)
        period = fixed_arp_period(mask[0]) if mask is not None else None
    elif det.arp_nibble_period is not None:
        per = det.arp_nibble_period
        test = nibble_arp_counter_test(sid, per)
        base = test[0] if test is not None else None
        period = fixed_arp_period(max(per.on_interval, per.otherwise))
    else:
        return None
    first = fixed_arp_first_fetch(sid, det)
    speeds = _gw_tempo.find_song_speeds(sid, det)
    if base is None or first is None or period is None or speeds is None:
        return None
    if len(tracks) // 3 > max(sid.subtunes, 1):
        return None
    out: dict = {}
    for ti, track in enumerate(tracks):
        frames = speeds.frames_for(ti // 3)
        if frames is None:
            continue
        row = 0
        for _pos, p in _orderlist_occurrences(track):
            if p >= len(patterns):
                continue
            pat = patterns[p]
            for r in range(0, len(pat), 4):
                if pat[r] == 0xFF:
                    break
                if GT_FIRST_NOTE <= pat[r] <= GT_LAST_NOTE:
                    out.setdefault((p, r // 4), set()).add(
                        (base + first + row * frames) % period)
                row += 1
    return out


def _share(held: dict, lap: dict, rows: int) -> None:
    """Fold one voice's held rows into `held` as shares of its lap."""
    for key, n in lap.items():
        held[key] = held.get(key, 0) + n / max(rows, 1)
    lap.clear()


def fixed_arp_phase_split_plan(sid: SidFile, det: Detection,
                               tracks: List[List[int]],
                               patterns: List[List[int]], effects: bool,
                               lead: int, instr_used: int, first_clone: int,
                               distinct=None,
                               log=None) -> Optional[ArpPhaseSplit]:
    """Clone each fixed-arp record whose notes attack on more than one
    residue, one clone per minority residue within `FIXED_ARP_SPLIT_FACTOR`
    of the majority, and rename each such note to its residue's clone.

    Gated exactly as the record's own wavetable read is (`effects`,
    `arp_fixed_up`, `effect_arp`, the +7 byte's bit 2). `distinct(record,
    residue)` says whether the clone's wavetable would differ from the
    record's at all -- a shape that ignores the phase (the -S{m} per-call
    loop) gets no clone; None treats every residue as distinct. Tied notes
    (`CMD_TONEPORTA $00`) restart no wavetable and neither vote nor move.

    Renaming is per NOTE, not per pattern play: a row's instrument byte is
    written wherever the note's wanted number (its residue's clone, or the
    record) differs from the one the new walk carries in. A pattern played
    at two positions that want different bytes gets a copy; a repeated
    orderlist entry whose plays want different bytes keeps the first play's
    spelling (the others sound the record's or another clone's phase, never
    another record: a clone and its record share every byte but the
    wavetable start). Clones are numbered from `first_clone` up to
    `TEMPO_DUTY_MAX_CLONE`, most-voted first; past that, or past 208
    patterns, the plan declines.
    """
    if not (effects and det.arp_fixed_up and det.effect_arp):
        return None
    walked = fixed_arp_note_residues(sid, det, tracks, patterns)
    if walked is None:
        return None
    period, residues = walked
    phases = fixed_arp_phases(sid, det, tracks, patterns)
    data = sid.data
    arp_records = set()
    for i in range(max(instr_used - lead, 0)):
        at = det.instr_start + i * det.instr_stride + 7
        if at < len(data) and data[at] & 4:
            arp_records.add(i + lead + 1)
    if not arp_records:
        return None
    return _note_phase_split(tracks, patterns, residues, phases,
                             arp_records, first_clone, distinct,
                             "arp phase split", log)


def _note_phase_split(tracks: List[List[int]], patterns: List[List[int]],
                      residues: dict, phases: dict, records: set,
                      first_clone: int, distinct=None,
                      label: str = "phase split",
                      log=None,
                      factor: Optional[int] = FIXED_ARP_SPLIT_FACTOR
                      ) -> Optional[ArpPhaseSplit]:
    """The per-note split shared by `fixed_arp_phase_split_plan` and
    `pitch_seq_phase_split_plan`: `residues` is {(track, orderlist position,
    play): {row: residue}}, `phases` {GT number: the record's own residue}
    (the majority its wavetable already carries), `records` the GT numbers
    whose notes may vote. A residue is anything hashable and ordered -- the
    fixed arp's counter residue, or bit $10's phase tuple -- and the clones'
    third slot carries it to `_wavetable_layout` unchanged. The rules are
    `fixed_arp_phase_split_plan`'s, documented there; `factor` None clones
    every minority residue (`nibble_gate_phase_split_plan`)."""
    def plays():
        """(ti, pos, play, pattern) in play order, per track."""
        for ti, track in enumerate(tracks):
            seen = Counter()
            for pos, p in _orderlist_occurrences(track):
                if p >= len(patterns):
                    continue
                yield ti, pos, seen[pos], p
                seen[pos] += 1

    def tied(pat, k):
        return pat[k * 4 + 2] == CMD_TONEPORTA and pat[k * 4 + 3] == 0

    # Untied notes per (record, residue), the sticky instrument carried --
    # and the share of its voice's lap each one sounds, up to the voice's
    # next untied note (a tie restarts no wavetable, so its rows are the
    # note's before it). A share, not a row count: an orderlist loops, and a
    # short lap plays its notes as often as a long one plays its own.
    votes: dict = {}
    held: dict = {}
    lap: dict = {}
    cur_ti, cur, row, last = -1, 0, 0, None
    for ti, pos, play, p in plays():
        if ti != cur_ti:
            if lap:
                _share(held, lap, row)
            cur_ti, cur, row, last = ti, 0, 0, None
        pat, res = patterns[p], residues.get((ti, pos, play), {})
        for k in range(len(pat) // 4):
            if pat[k * 4] == 0xFF:
                break
            if pat[k * 4 + 1]:
                cur = pat[k * 4 + 1]
            if k in res and not tied(pat, k):
                last = None
                if cur in records:
                    votes.setdefault(cur, Counter())[res[k]] += 1
                    last = (cur, res[k])
            if last is not None:
                lap[last] = lap.get(last, 0) + 1
            row += 1
    _share(held, lap, row)
    wanted = []                              # (share heard, record, residue)
    for rec, n in votes.items():
        major = phases.get(rec)
        if major is None:
            continue
        top = max(n.values())
        for r, c in n.items():
            if r == major or (factor is not None and c * factor < top):
                continue
            if distinct is not None and not distinct(rec, r):
                continue
            wanted.append((held.get((rec, r), 0), rec, r))
    if not wanted:
        return None
    room = TEMPO_DUTY_MAX_CLONE - first_clone + 1
    wanted.sort(key=lambda w: (-w[0], w[1], w[2]))
    if room < len(wanted):
        if log:
            log(f"{label}: {len(wanted)} clone(s) wanted, room for "
                f"{max(room, 0)}; the least-heard residues stay on their "
                "record")
        wanted = wanted[:max(room, 0)]
    if not wanted:
        return None
    # Numbered, and so laid out, most-HEARD first -- by the share of its
    # voice's lap its notes sound, not their count: the wavetable's 255 entries run out before
    # the instrument numbers do (Game_Killer's -S9 duty blocks are 10-16
    # entries each), and a clone the table cannot hold is pointed at its
    # record's block. Game_Killer's record 6 has three notes, one a residue,
    # and they are voice 2's whole octave: ordered by note count its clones
    # lost the table and the voice read 0 reversals to the original's 75.
    clone_of = {}
    clones = []
    for k, (_c, rec, r) in enumerate(wanted):
        clone_of[(rec, r)] = first_clone + k
        clones.append((rec, first_clone + k, r))

    # Per play: the edit set the new walk wants, first play of an entry wins.
    spelled: dict = {}                       # (ti, pos) -> edit tuple
    cur_ti, cur, new_cur = -1, 0, 0
    for ti, pos, play, p in plays():
        if ti != cur_ti:
            cur_ti, cur, new_cur = ti, 0, 0
        pat, res = patterns[p], residues.get((ti, pos, play), {})
        rows = []
        for k in range(len(pat) // 4):
            if pat[k * 4] == 0xFF:
                break
            rows.append(k)
        edit = {}
        c, nc = cur, new_cur
        for k in rows:
            b = pat[k * 4 + 1]
            if b:
                c = nc = b
            note = GT_FIRST_NOTE <= pat[k * 4] <= GT_LAST_NOTE
            if not note or tied(pat, k) or c not in votes:
                continue
            w = clone_of.get((c, res.get(k)), c)
            if w != nc:
                edit[k] = (b, w)
                nc = w
        key = tuple(sorted(edit.items()))
        key = spelled.setdefault((ti, pos), key)
        # Carry both walks to the end of the play, under the spelling kept.
        kept = dict(key)
        for k in rows:
            b = pat[k * 4 + 1]
            if b:
                cur = new_cur = b
            if k in kept:
                new_cur = kept[k][1]
    by_pat: dict = {}
    for (ti, pos), key in spelled.items():
        by_pat.setdefault(tracks[ti][pos], Counter())[key] += 1
    new_tracks = [list(t) for t in tracks]
    new_patterns = [list(p) for p in patterns]
    edits: dict = {}
    copy_of: dict = {}
    for p, spellings in sorted(by_pat.items()):
        stay = max(spellings, key=lambda s: (spellings[s], not s, s))
        if stay:
            edits[p] = dict(stay)
        for s in sorted(spellings):
            if s == stay:
                continue
            copy_of[(p, s)] = len(new_patterns)
            if s:
                edits[len(new_patterns)] = dict(s)
            new_patterns.append(list(patterns[p]))
    if len(new_patterns) > 208:              # patterns.MAX_PATTERNS
        if log:
            log(f"{label}: the copies would pass 208 patterns; "
                "not splitting")
        return None
    for (ti, pos), key in spelled.items():
        n = copy_of.get((tracks[ti][pos], key))
        if n is not None:
            new_tracks[ti][pos] = n
    if not edits:
        return None
    if log:
        log(f"{label}: {len(clones)} clone(s) {clones}, "
            f"{len(new_patterns) - len(patterns)} pattern copy(ies), "
            f"{sum(len(e) for e in edits.values())} instrument byte(s)")
    return ArpPhaseSplit(new_tracks, new_patterns, clones, edits)


def unticked_arp_octave_entry(arp_phase: int, written: bool = False) -> int:
    """Which of the unticked -S1 shape's two loop entries carries the octave.

    The shape is `wave/00, tail/00, tail/00, FF -> entry 1`: the loop runs
    over entries 1 and 2, so entry 1 plays every odd frame after the attack
    and entry 2 every even one -- where `written` (`--no-test-restart`) the
    instrument's firstwave owns frame 0 and every entry lands one frame
    later, the tick shape's empty `_first_frame_lead`. The first octave-up
    frame is offset `1 + (residue & 1)` (`fixed_arp_phases`), so the octave
    goes on the entry whose frames share that parity. Residue 1 unwritten
    is entry 2, the offset the shape hard-coded until v0.5.490.
    """
    first_up = 1 + (arp_phase & 1)
    return 1 if (1 + int(written) - first_up) % 2 == 0 else 2


def ticked_arp_entries(frame0: List[int], frame0_r: List[int],
                       tl: List[int], tr: List[int], noise: int, tail: int,
                       arp_rel: int, multiplier: int, start: int,
                       budget: int,
                       arp_phase: Optional[int] = None,
                       half_calls: Optional[int] = None) -> Optional[tuple]:
    """The ticked arpeggio at -S{m}: each half of the alternation `m` calls.

    Until v0.5.489 a ticked arpeggio record above -S1 was forced onto the
    per-call two-entry loop (`_wavetable_entries`' -S1 shape), because the
    unticked -S{m} shape loops back to entry 0 and would replay the noise
    tick once per cycle. The player's counter steps once a FRAME, and a
    frame is `multiplier` calls, so that loop toggled the octave inside
    every frame: on the packed Last_V8 at -S2, vsid at 312 samples a frame
    read the note and its octave in the same frame on 75 of 399 frames,
    split 155-160 / 312 rasterlines -- a 100 Hz trill the original never
    plays and siddump, sampling once a frame, cannot see
    (C:/t/ticked-fixed-arp-at-s2-is-a-/vice_live_parity.txt). The nine
    mask != $01 files had already left this shape for
    `fixed_arp_duty_entries`; what remained were the parity-mask files at
    -S2 (Last_V8 x2, Monty_on_the_Run, Devils_Galop) and the nibble
    dialect's ticked records at -S3..-S10 (Thrust, Bump_Set_Spike,
    Spellbound, Formula_1_Simulator, Warhawk, Proteus, International_Karate)
    -- the same per-call loop, `m` toggles a frame.

    The shape: the frame-0 lead and the tick as the caller built them, then
    `tail:note, hold, tail:note, hold, $FF` -- a two-frame loop whose
    target is the entry AFTER the tick, so the tick plays once. `hold` is
    `_wave_hold_byte(multiplier, tail)`: the tail written again at -S2 (one
    more call), a delay of `m - 2` above it (`m - 1` calls,
    gplay.c:697-704), its right side `$80` so the last call of the up half
    does not drag the note back (the same rule the unticked -S{m} shape
    states). The two halves are `note` then the octave where no phase is
    known -- the order the per-call loop had.

    With `arp_phase` (the counter's residue on the attack frame,
    `fixed_arp_phases`; parity mask only, the caller gates it) the tick
    entries are expanded to one per call, exactly as the -S1 phased shape
    does, and every frame `j` after the attack is up where
    `(j - (1 + residue)) % 2 == 0` -- the tick frames on their noise
    entries' right side, the loop's two frames in whichever order that
    parity puts them. The walk is in frames and does not depend on the
    rate, so the residue the -S1 shape reads is the residue here. That
    expansion needs the tick to be a whole number of frames
    (`WAVE_MAX_DELAY` can clamp it) and the room for one entry a call;
    otherwise the unphased shape stands.

    `half_calls` (the nibble dialect, `nibble_arp_half_calls`) is how many
    calls each half lasts where that is not one frame: the record's own
    period in counter steps, times `m`, stretched by the outer gate. Each
    half is then `tail` and a hold of `half_calls - 1` calls (`_hold_run`,
    split at `WAVE_MAX_DELAY`); no phase is placed, the nibble counter's
    phase not being walked.

    Returns None where even the unphased shape does not fit `budget`; the
    caller then keeps the per-call loop, the tick being what is lost
    rather than the table.
    """
    m = max(1, multiplier)
    if half_calls is None:
        hold = _wave_hold_byte(m, tail)
        if hold is None:
            return None
        cycle_holds = [[hold], [hold]]
    else:
        # A `nibble_arp_half_cycle` loops over every one of its halves.
        cycle = _half_cycle(half_calls)
        if min(cycle) < 2:
            return None
        cycle_holds = [_hold_run(h - 1, tail) for h in cycle]
        arp_phase = None
    tick_calls = sum(1 if b > WAVE_MAX_DELAY else b + 1 for b in tl)
    first_up = False
    tl2, tr2 = list(tl), list(tr)
    if arp_phase is not None:
        ph = 1 + (arp_phase & 1)

        def up(frame: int) -> bool:
            return (frame - ph) % 2 == 0

        if (tick_calls % m == 0
                and len(frame0) + tick_calls + 5 <= budget):
            tl2 = [noise] * tick_calls
            tr2 = [arp_rel if up(1 + t // m) else 0x00
                   for t in range(tick_calls)]
            first_up = up(1 + tick_calls // m)
    if (len(frame0) + len(tl2) + 1
            + sum(1 + len(h) for h in cycle_holds) > budget):
        return None
    a, b = (arp_rel, 0x00) if first_up else (0x00, arp_rel)
    loop = start + len(frame0) + len(tl2)
    left, right = frame0 + tl2, frame0_r + tr2
    for j, holds in enumerate(cycle_holds):
        left = left + [tail] + holds
        right = right + [a if j % 2 == 0 else b] + [0x80] * len(holds)
    return left + [WAVE_JUMP], right + [loop & 0xFF]


def _hold_run(calls: int, wave: int) -> List[int]:
    """Left-side entries that spend exactly `calls` play calls, no change.

    `_wave_hold_byte`'s rule run past one entry: a delay `n` is current for
    `n + 1` calls (gplay.c:697-704), so each entry spends up to
    `WAVE_MAX_DELAY + 1`; a single call has no delay encoding and writes
    `wave` again (a no-op: it is the waveform already current). A run of
    `k <= 16` calls is the one byte `_wave_hold_byte(k + 1)` has always
    been.
    """
    out: List[int] = []
    while calls > 0:
        if calls == 1:
            out.append(wave)
            break
        n = min(calls, WAVE_MAX_DELAY + 1)
        out.append(n - 1)
        calls -= n
    return out


def nibble_arp_counter_gated(sid: SidFile, per: NibbleArpPeriod) -> bool:
    """True where the nibble block's counter `INC` sits behind an outer gate.

    The gate is `DEC ctr / BPL past / reload / RTS` (or `JMP`) ending at the
    counter's `INC` -- or five bytes before it, where the player writes
    $D418 between the two (Warhawk `$101D LDA #$0F / STA $D418`). Read
    procedurally because the corpus spells it several ways: absolute and
    zero-page `DEC`, `RTS` and `JMP` exits, Kentilla's `BPL +8` and
    Las_Vegas_Video_Poker's PAL/NTSC reload (`BPL +$0D`). Measured on the
    originals: a skipped call leaves the counter alone, so a half spanning
    it lasts a frame more (International_Karate's `$090A` alternates in 1s
    with a 2 about once in 11 frames, its gate reloading 10).
    """
    data, c = sid.data, per.counter
    inc_op = bytes([0xE6, c]) if c < 0x100 else bytes([0xEE, c & 0xFF, c >> 8])
    inc = data.find(inc_op)
    while inc >= 0:
        for b in range(max(3, inc - 24), inc - 1):
            if data[b] != 0x10 or data[b + 1] >= 0x80:
                continue
            if data[b - 3] != 0xCE and data[b - 2] != 0xC6:
                continue                      # not a DEC's BPL
            t = b + 2 + data[b + 1]
            if not (data[t - 1] == 0x60 or data[t - 3] == 0x4C):
                continue                      # the skipped path does not exit
            if t == inc:
                return True
            if t == inc - 5 and data[t] == 0xA9 and data[t + 2] == 0x8D:
                return True
        inc = data.find(inc_op, inc + 1)
    return False


def nibble_arp_half_calls(sid: SidFile, det: Detection, nibble: int,
                          multiplier: int,
                          gate_skip: Optional[int]) -> Optional[int]:
    """Calls each half of a nibble record's alternation lasts, or None.

    None where the block carries no period code (`det.arp_nibble_period`,
    read once by `detect.nibble_arp_period`: Mozart, the fixed dialect, a
    hand-built Detection) or where the answer is one frame of
    `multiplier` calls -- the half every shape has always emitted, so a
    record reading None keeps its bytes. Otherwise the record's own half in
    counter steps (two for an octave in Warhawk's spelling, four in
    Proteus' and Formula_1_Simulator's, one for any other interval) times
    `multiplier`, and where the counter's `INC` is behind the outer gate,
    `_gate_calls` of that: a counter step is a PASSING call, `(O + 1) / O`
    frames, exactly as the fixed dialect's duty steps.
    """
    per = det.arp_nibble_period
    if per is None:
        return None
    m = max(1, multiplier)
    calls = m * per.half(nibble)
    if gate_skip and nibble_arp_counter_gated(sid, per):
        calls = _gate_calls(calls, gate_skip)
    return None if calls == m else calls


def nibble_arp_half_cycle(sid: SidFile, det: Detection, nibble: int,
                          multiplier: int,
                          gate_skip: Optional[int]) -> Optional[tuple]:
    """The halves' call counts, in loop order, where a half is not whole.

    `nibble_arp_half_calls` ROUNDS `m * steps * (O + 1) / O`, and where that
    is not an integer the rounding is a rate error on every note. Formula_1_
    Simulator (-S2, `O` 4) is the worst case: a one-step half is 2.5 calls,
    rounded to 2, so every non-octave record alternated 25% fast -- the whole
    of its residual `reversal_ratio` (4193 -> 5079, 1.21x, split by ADSR in
    C:/t/f1-ticked-reversal/rba_base_Formula_1_Simulator.txt: $086A, $0900, $0908,
    $0A0A and $3960 each exactly 1.25x, the octave records $0909/$0F0A, whose
    10-call half is whole, exactly 1.00x). The original holds the counter
    over its skipped call, so its halves run `1 1 1 2` frames; a loop of
    halves summing to the exact length keeps the rate. The halves are spread
    as evenly as integers allow (`floor((i + 1) h) - floor(i h)`) over the
    shortest EVEN count whose total is whole -- even, so the alternation's
    parity survives the jump: (2, 3) for F1's 2.5, which a once-a-frame trace
    reads as the original's `1 1 1 2`. None where the half is whole (the
    caller keeps `nibble_arp_half_calls`) and wherever that function is None
    for want of a period code.
    """
    per = det.arp_nibble_period
    if per is None:
        return None
    exact = Fraction(max(1, multiplier) * per.half(nibble))
    if gate_skip and nibble_arp_counter_gated(sid, per):
        exact = exact * (gate_skip + 1) / gate_skip
    if exact.denominator == 1:
        return None
    n = exact.denominator * (1 if exact.denominator % 2 == 0 else 2)
    return tuple(math.floor((k + 1) * exact) - math.floor(k * exact)
                 for k in range(n))


def _half_cycle(half_calls) -> tuple:
    """A half length or a `nibble_arp_half_cycle` as the loop's halves."""
    if isinstance(half_calls, int):
        return (half_calls, half_calls)
    return tuple(half_calls)


def nibble_arp_counter_test(sid: SidFile,
                            per: NibbleArpPeriod) -> Optional[tuple]:
    """(base, branch) of the nibble block's counter, or None.

    `base` is what the counter reads on passing call 0, less nothing: the
    block's `INC` and the new-song reset are `fixed_arp_counter_base`'s two
    shapes (International_Karate `$AE95 INC $B2F9 / BIT / BMI / BVC / LDA #0
    / STA $B2F9`, base 0; Thrust and Las_Vegas_Video_Poker store nothing, so
    the file's own byte plus one), read here for an absolute or a zero-page
    counter -- a zero-page counter with no reset has no byte in the file and
    reads None. `branch` is the opcode after the block's `AND`: the block's
    is the counter load whose `AND` operand some `STY abs` writes (the
    self-modified mask), because the same counter is loaded by other effects
    too (`AND #$03` in Warhawk, Thrust, Spellbound; `AND #$01 / BEQ` in
    Proteus). International_Karate's `AND #$01 / BNE +9` skips the `SBC`,
    so the interval is taken where the masked value is ZERO --
    `fixed_arp_up(mask, BNE, c)`.
    """
    c, data = per.counter, sid.data
    if c < 0x100:
        load, inc = bytes([0xA5, c]), bytes([0xE6, c])
        reset = bytes([0xA9, 0x00, 0x85, c])
    else:
        load, inc = bytes([0xAD, c & 0xFF, c >> 8]), bytes([0xEE, c & 0xFF, c >> 8])
        reset = bytes([0xA9, 0x00, 0x8D, c & 0xFF, c >> 8])
    at = data.find(inc)
    if at < 0:
        return None
    if data.find(reset, at, at + FIXED_ARP_RESET_WINDOW) >= 0:
        base = 0
    elif c >= 0x100 and 0 <= sid.to_offset(c) < len(data):
        base = data[sid.to_offset(c)] + 1
    else:
        return None
    branches = set()
    i = data.find(load)
    while i >= 0:
        j = i + len(load)
        if j + 2 < len(data) and data[j] == 0x29 and data[j + 2] in (BEQ, BNE):
            a = sid.to_address(j + 1)
            if data.find(bytes([0x8C, a & 0xFF, a >> 8])) >= 0:
                branches.add(data[j + 2])
        i = data.find(load, i + 1)
    if len(branches) != 1:
        return None
    return base, branches.pop()


def nibble_arp_phases(sid: SidFile, det: Detection, tracks: List[List[int]],
                      patterns: List[List[int]]) -> dict:
    """{Goattracker instrument: the nibble counter's residue on its attack}.

    `fixed_arp_phases`' walk for the nibble dialect's counter: `(base + first
    + row * frames) mod P`, in the player's passing-call clock, the majority
    over each instrument's notes, P the longest cycle any record's mask makes
    (`fixed_arp_period` of the larger mask, so every record's own cycle
    divides it). Empty where the block carries no period code, its counter
    test is not read (`nibble_arp_counter_test`), or the rows cannot be
    walked.
    """
    per = det.arp_nibble_period
    if per is None:
        return {}
    test = nibble_arp_counter_test(sid, per)
    first = fixed_arp_first_fetch(sid, det)
    if test is None or first is None:
        return {}
    base = test[0]
    period = fixed_arp_period(max(per.on_interval, per.otherwise))
    speeds = _gw_tempo.find_song_speeds(sid, det)
    if speeds is None:
        return {}
    if len(tracks) // 3 > max(sid.subtunes, 1):
        return {}                        # a split subtune shifted the numbering
    votes: dict = {}
    for ti, track in enumerate(tracks):
        frames = speeds.frames_for(ti // 3)
        if frames is None:
            continue
        for row, current, _pat, _r in _walk_note_rows(track, patterns):
            residue = (base + first + row * frames) % period
            votes.setdefault(current, [0] * period)[residue] += 1
    return {instr: max(range(period), key=lambda p: (counts[p], -p))
            for instr, counts in votes.items()}


def nibble_gate_byte(sid: SidFile) -> Optional[int]:
    """The outer gate cell's byte at song start, or None where it is not read.

    The cell `_find_outer_gate` decrements (`DEC cell / BPL / reload /
    RTS|JMP`, or Las_Vegas_Video_Poker's PAL `LDY` spelling at the play
    address) starts the song holding the byte in the file, **provided nothing
    but the gate writes it**: the reload `STA`/`STY` must be the only store
    to it and the gate's `DEC` the only decrement. Measured, not argued
    (C:/t/nibble-gate-stall-phase/model_check.py, siddump of the originals,
    every frame after every two-valued arpeggio attack against the
    `nibble_gate_frames` model with this byte): Formula_1_Simulator (byte 0)
    736/0 at 120 s, Las_Vegas_Video_Poker (3) 3552/0 on its arpeggio notes,
    International_Karate (4) 563/0, Kentilla (3) 9075/0, Thrust (2) 541/0.
    A zero-page cell (Spellbound `$C2`, Samantha_Fox) has no byte in the
    image and reads None, as does any cell some other code stores to.
    """
    data = sid.data
    m = OUTER_GATE.search(data) or OUTER_GATE_RTS.search(data)
    if m is not None:
        cell = m.group(1)[0] | m.group(1)[1] << 8
        if cell != (m.group(3)[0] | m.group(3)[1] << 8):
            return None
    else:
        at = sid.to_offset(sid.play_addr) if sid.play_addr else None
        if at is None or not 0 <= at < len(data):
            return None
        mp = OUTER_GATE_PAL.match(data, at)
        if mp is None or mp.group(1) != mp.group(3):
            return None
        cell = mp.group(1)[0] | mp.group(1)[1] << 8
    off = sid.to_offset(cell)
    if not 0 <= off < len(data):
        return None
    lo, hi = cell & 0xFF, cell >> 8
    writes = sum(data.count(bytes([op, lo, hi]))
                 for op in (0x8D, 0x8C, 0x8E, 0x9D, 0x99))
    if writes != 1 or data.count(bytes([0xCE, lo, hi])) != 1:
        return None
    return data[off]


def nibble_gate_frames(residue: int, mask: int, branch: int, skip_at: int,
                       gate: int, frames: int) -> List[bool]:
    """Whether the interval sounds on each of frames 1..`frames` after an attack.

    The original's own clock, frame by frame: the counter read `residue` on
    the attack's passing call; each later frame is either a call that passes
    the outer gate (the counter steps, `fixed_arp_up` decides the half) or
    the call the gate skips, which runs nothing and so holds whatever the
    frame before it played -- the attack frame's base note where it is
    frame 1. The skipped call is the one before every passing call whose
    counter reads `skip_at` modulo `gate` (`skip_at` = the counter's base
    plus the gate cell's starting byte, `nibble_gate_byte`).
    """
    out: List[bool] = []
    c, prev, skipped = residue, False, False
    for _ in range(frames):
        if not skipped and (c + 1 - skip_at) % gate == 0:
            skipped = True
        else:
            skipped = False
            c += 1
            prev = fixed_arp_up(mask, branch, c)
        out.append(prev)
    return out


def nibble_gate_runs(residue: int, mask: int, branch: int, skip_at: int,
                     gate: int) -> Optional[tuple]:
    """(first_up, first frames, cycle of frame runs) of a gated one-mask record.

    **Where the gate's reload is a multiple of the record's period
    (`2 * mask` steps), the skipped frame always lands on the same counter
    residue**, so one and the same half is the long one on every note:
    Formula_1_Simulator (-S2, O 4) stretches the base note of its one-step
    records (`1 1 2 1` frames over each 5), Las_Vegas_Video_Poker (-S4, O 4)
    the interval, and its octave `2 3` with the 3 on the interval -- the
    original's figures in C:/t/lvvp-0aa0-and-spellbound-afff/o_runs.txt and
    `nibble_gate_byte`'s model check. An evenly spread `nibble_arp_half_cycle`
    or a whole `nibble_arp_half_calls` keeps the rate but puts the long half
    wherever its own index lands (LVVP's `0A0C` was inverted on all 427
    notes). The runs here are the original's frames, so every half boundary
    falls on a frame.

    The first run starts on frame 1 (the run `nibble_arp_first_half` names,
    lengthened where the gate skips inside it); the cycle is the runs after
    it, one gate period (`gate + 1` frames) long, alternating from the half
    after the first run. None where the reload is not a multiple of the
    period -- there the long half itself alternates -- or where the first
    run and the cycle do not reproduce the frames. That check is the
    contract, and it is what declines LVVP's octave from residue 0: frame 1
    is a skipped call holding the attack's base note where the counter's
    class is the interval, so no run boundary recurs a gate period later
    and the record keeps its old halves. It would decline a reload that is
    not a multiple of the period too (that pattern's period is longer than
    `gate + 1` frames); the modulus test below only says so first -- a
    mutation dropping it changes no result (C:/t/nibble-gate-stall-phase/
    sabotage_out.txt, M10).
    """
    period = 2 * mask
    if mask < 1 or gate < 1 or gate % period:
        return None
    span = gate + 1
    n = 4 * span + 4 * period + 2
    frames = nibble_gate_frames(residue, mask, branch, skip_at, gate, n)
    runs: List[list] = []
    for up in frames:
        if runs and runs[-1][0] == up:
            runs[-1][1] += 1
        else:
            runs.append([up, 1])
    first_up, first = runs[0]
    cycle: List[int] = []
    total = 0
    for _, length in runs[1:]:
        if total >= span:
            break
        cycle.append(length)
        total += length
    if total != span or len(cycle) % 2:
        return None
    rebuilt: List[bool] = [first_up] * first
    up = not first_up
    while len(rebuilt) < n:
        for length in cycle:
            rebuilt += [up] * length
            up = not up
    if rebuilt[:n - span] != frames[:n - span]:
        return None
    return first_up, first, tuple(cycle)


def nibble_gate_phases(sid: SidFile, det: Detection, tracks: List[List[int]],
                       patterns: List[List[int]],
                       gate: Optional[int]) -> dict:
    """{Goattracker instrument: the nibble counter's residue mod lcm(P, O)}.

    `nibble_arp_phases`' walk, kept modulo the gate's reload too, so the
    attack's place in the gate's cycle is known: `nibble_gate_runs` needs
    it to put the skipped frame. Each instrument takes the majority WITHIN
    the residue class `nibble_arp_phases` voted (same walk, same tie rule),
    so the two never disagree modulo P. Empty unless the counter's `INC` is
    behind the gate (`nibble_arp_counter_gated`), the gate cell's starting
    byte is read (`nibble_gate_byte`), and every walked subtune's reload is
    `gate`; a group whose reload differs casts no vote.
    """
    per = det.arp_nibble_period
    if per is None or not gate or not nibble_arp_counter_gated(sid, per):
        return {}
    if nibble_gate_byte(sid) is None:
        return {}
    test = nibble_arp_counter_test(sid, per)
    first = fixed_arp_first_fetch(sid, det)
    speeds = _gw_tempo.find_song_speeds(sid, det)
    if test is None or first is None or speeds is None:
        return {}
    if len(tracks) // 3 > max(sid.subtunes, 1):
        return {}
    period = fixed_arp_period(max(per.on_interval, per.otherwise))
    mod = period * gate // math.gcd(period, gate)
    votes: dict = {}
    for ti, track in enumerate(tracks):
        frames = speeds.frames_for(ti // 3)
        if frames is None or outer_gate_skip(sid, ti // 3) != gate:
            continue
        for row, current, _pat, _r in _walk_note_rows(track, patterns):
            residue = (test[0] + first + row * frames) % mod
            votes.setdefault(current, [0] * mod)[residue] += 1
    return {instr: _refined_majority(counts, period)
            for instr, counts in votes.items()}


def _refined_majority(counts: List[int], period: int) -> int:
    """The majority residue mod `len(counts)` inside the majority class mod `period`.

    The class is `nibble_arp_phases`' own vote (summed over the finer
    residues, the same tie rule: the lower wins), so the refined residue
    never contradicts the arp walk modulo the period -- a plain majority over
    the finer residues can: votes {0: 3, 1: 2, 3: 2} mod 4 take 0 outright,
    where the parity classes are even 3, odd 4.
    """
    mod = len(counts)
    cls = [sum(counts[r] for r in range(p, mod, period))
           for p in range(period)]
    best = max(range(period), key=lambda p: (cls[p], -p))
    return max(range(best, mod, period), key=lambda r: (counts[r], -r))


@dataclass(frozen=True, order=True)
class GatePhase:
    """A gated nibble record's attack residue, as a phase clone carries it.

    `residue` is the counter modulo lcm(P, O) (`nibble_gate_phases`' walk),
    `period` P: `_wavetable_layout` lays the clone out with `arp_phase`
    `residue % period` and `arp_gate_phase` `residue`. Its own type, not an
    int, because a bare int clone residue is the fixed arp's and lays out
    with no gate phase (`_phase_locked_ties` asks exactly that question),
    and not a tuple, which is bit $10's phase."""
    residue: int
    period: int


def nibble_gate_note_residues(sid: SidFile, det: Detection,
                              tracks: List[List[int]],
                              patterns: List[List[int]],
                              gate: Optional[int]) -> Optional[dict]:
    """{(track, orderlist position, play): {row: GatePhase}} -- the walk
    `nibble_gate_phases` votes from, keyed by where each note sits so
    `nibble_gate_phase_split_plan` can rename it (`fixed_arp_note_residues`'
    shape). Gated exactly as `nibble_gate_phases` is; a group whose reload is
    not `gate` gets no residues, so its notes neither vote nor move. None
    wherever that function is empty for want of a reading."""
    per = det.arp_nibble_period
    if per is None or not gate or not nibble_arp_counter_gated(sid, per):
        return None
    if nibble_gate_byte(sid) is None:
        return None
    test = nibble_arp_counter_test(sid, per)
    first = fixed_arp_first_fetch(sid, det)
    speeds = _gw_tempo.find_song_speeds(sid, det)
    if test is None or first is None or speeds is None:
        return None
    if len(tracks) // 3 > max(sid.subtunes, 1):
        return None
    period = fixed_arp_period(max(per.on_interval, per.otherwise))
    mod = period * gate // math.gcd(period, gate)
    out: dict = {}
    for ti, track in enumerate(tracks):
        frames = speeds.frames_for(ti // 3)
        if frames is None or outer_gate_skip(sid, ti // 3) != gate:
            continue
        row, seen = 0, Counter()
        for pos, p in _orderlist_occurrences(track):
            if p >= len(patterns):
                continue
            pat = patterns[p]
            play = seen[pos]
            seen[pos] += 1
            res = out.setdefault((ti, pos, play), {})
            for r in range(0, len(pat), 4):
                if pat[r] == 0xFF:
                    break
                if GT_FIRST_NOTE <= pat[r] <= GT_LAST_NOTE:
                    res[r // 4] = GatePhase(
                        (test[0] + first + row * frames) % mod, period)
                row += 1
    return out


def nibble_gate_phase_split_plan(sid: SidFile, det: Detection,
                                 tracks: List[List[int]],
                                 patterns: List[List[int]], effects: bool,
                                 lead: int, instr_used: int,
                                 first_clone: int, gate: Optional[int],
                                 distinct=None,
                                 log=None) -> Optional[ArpPhaseSplit]:
    """Clone each gated nibble-arpeggio record whose notes attack on more
    than one gate residue, one clone per minority residue, and rename each
    such note to its residue's clone -- `fixed_arp_phase_split_plan` for the
    nibble counter behind the outer gate.

    `nibble_gate_phases` gives each RECORD one residue modulo lcm(P, O), the
    majority of its notes', and `nibble_gate_runs` puts the gate's skipped
    frame from it -- so the record's every note stretches the half its
    majority stretches. Where a row is not a multiple of the gate's cycle
    the notes do not agree: Las_Vegas_Video_Poker (-S4, O 4, 3-frame rows)
    attacks on residues 1 and 3 by row mod 4, and the original's one-step
    first runs are `base1/arp1` on 82 of 321 notes in subtune 0's first
    120 s and its octave's `base3/arp3` on 5 of 12, where the majority
    spelling gave 1 and 0 (C:/t/lvvp-gate-phase-per-note-split/ab_runs.py).
    Every minority residue gets a clone (`FIXED_ARP_SPLIT_FACTOR` is not
    applied: a residue's notes are the original's own frames, not a guess
    outvoted), most-heard first, within `TEMPO_DUTY_MAX_CLONE` and the
    wavetable's room; a residue whose block is the record's (`distinct`)
    gets none. A repeated orderlist entry whose plays want different
    residues is unrolled first (`_expand_repeats`), as bit $10's split does.
    Gated as the record's gate phase is: `effects`, the nibble dialect,
    `effect_arp`, the +7 byte's bit 2 with a nonzero interval nibble.
    """
    if not (effects and not det.arp_fixed_up and det.effect_arp
            and det.arp_nibble_period is not None and gate):
        return None
    majority = nibble_gate_phases(sid, det, tracks, patterns, gate)
    if not majority:
        return None
    residues = nibble_gate_note_residues(sid, det, tracks, patterns, gate)
    if residues is None:
        return None
    per = det.arp_nibble_period
    period = fixed_arp_period(max(per.on_interval, per.otherwise))
    phases = {g: GatePhase(r, period) for g, r in majority.items()}
    data = sid.data
    records = set()
    for i in range(max(instr_used - lead, 0)):
        at = det.instr_start + i * det.instr_stride + 7
        if at < len(data) and data[at] & 4 and data[at] >> 4:
            records.add(i + lead + 1)
    if not records:
        return None
    unroll = _phase_divergent_repeats(tracks, patterns, residues, records)
    if unroll:
        wide = [(_expand_repeats(t, unroll.get(ti, set())) or t)
                if ti in unroll else t for ti, t in enumerate(tracks)]
        if wide != tracks:
            wide_res = nibble_gate_note_residues(sid, det, wide, patterns,
                                                 gate)
            if wide_res is not None:
                tracks, residues = wide, wide_res
    return _note_phase_split(tracks, patterns, residues, phases, records,
                             first_clone, distinct, "gate phase split", log,
                             factor=None)


def _nibble_gate_shape(sid: SidFile, det: Detection, nibble: int,
                       multiplier: int, gate_skip: Optional[int],
                       gate_phase: Optional[int]) -> Optional[tuple]:
    """(first_up, first_calls, cycle in calls) for `nibble_gate_runs`, or None.

    The record's frames at our rate, `multiplier` calls a frame. None
    wherever any reading it needs is missing, and over
    `NIBBLE_GATE_MAX_HALVES`, so the record keeps the shape it had.
    """
    per = det.arp_nibble_period
    if per is None or gate_phase is None or not gate_skip:
        return None
    test = nibble_arp_counter_test(sid, per)
    g0 = nibble_gate_byte(sid)
    if test is None or g0 is None or not nibble_arp_counter_gated(sid, per):
        return None
    runs = nibble_gate_runs(gate_phase, per.half(nibble), test[1],
                            test[0] + g0, gate_skip)
    if runs is None or len(runs[2]) > NIBBLE_GATE_MAX_HALVES:
        return None
    m = max(1, multiplier)
    first_up, first, cycle = runs
    return first_up, first * m, tuple(f * m for f in cycle)


def nibble_arp_first_half(residue: int, mask: int,
                          branch: int) -> tuple:
    """(interval?, counter steps left) of the half frame 1 after the attack plays.

    The block does not run on the attack frame (the init path writes the
    note), and on frame `k` after it the counter reads `residue + k`; the
    interval is taken where `fixed_arp_up(mask, branch, counter)`. Frame 1
    is therefore part-way through a half whenever the residue is not on a
    half boundary, and this is how many steps of that half remain.
    """
    c = residue + 1
    up = fixed_arp_up(mask, branch, c)
    left = 1
    while left < 2 * mask and fixed_arp_up(mask, branch, c + left) == up:
        left += 1
    return up, left


def ticked_nibble_arp_entries(frame0: List[int], frame0_r: List[int],
                              tick_calls: int, noise: int, tail: int,
                              arp_rel: int, half_calls: int,
                              first_up: bool, first_calls: int,
                              start: int, budget: int) -> Optional[tuple]:
    """The nibble dialect's ticked arpeggio with the alternation THROUGH the tick.

    **The original's alternation does not wait for the noise tick.** The drum
    block writes `$D404` and the arpeggio block the frequency, every frame,
    tick included, so on International_Karate (-S10) the original's first
    interval frame is offset 2 after the attack on 312 of 391 `$090A` notes
    and on 116 of 146 `$0A08` ones -- inside the two noise frames
    (`80 80` at +1 and +2). `ticked_arp_entries` held the base note over the
    tick and started its loop after it, so the same notes first toggled at
    offset 4 and 5 (C:/t/ik-first-toggle/base_ik.txt): two frames late, the
    tick's length, on every note.

    The shape, in play calls from the call after the frame-0 lead: a first
    run of `first_calls` on whichever half frame 1 plays (`first_up`, from
    `nibble_arp_first_half` and the record's phase), then halves of
    `half_calls` alternating; the waveform is `noise` for the tick's
    `tick_calls` and `tail` after. Every run is a waveform entry carrying its
    note and a hold (`_hold_run`) carrying `$80`. Unrolled until a half
    begins at or after the tick's end; from there it is
    `ticked_arp_entries`' two-half loop, entered on the half that falls
    there. None over `budget` -- the caller then keeps the unphased shape.
    """
    # `half_calls` may be a `nibble_arp_half_cycle`: the halves after the
    # first run take its lengths in turn, and the loop is all of them.
    cycle = _half_cycle(half_calls)
    if min(cycle) < 2 or first_calls < 1 or tick_calls < 1:
        return None
    note = {True: arp_rel, False: 0x00}
    left, right = list(frame0), list(frame0_r)
    t, up, run, k = 0, first_up, first_calls, 0
    while t < tick_calls:
        for lo, hi, wave in ((t, min(t + run, tick_calls), noise),
                             (tick_calls, t + run, tail)):
            if hi <= lo:
                continue
            holds = _hold_run(hi - lo - 1, wave)
            left += [wave] + holds
            right += [note[up] if lo == t else 0x80] + [0x80] * len(holds)
        t += run
        up, run, k = not up, cycle[k % len(cycle)], k + 1
    loop = start + len(left)
    k -= 1                                # `run` is cycle[k - 1]: not played
    for j in range(len(cycle)):
        holds = _hold_run(cycle[(k + j) % len(cycle)] - 1, tail)
        left += [tail] + holds
        right += [note[up]] + [0x80] * len(holds)
        up = not up
    left.append(WAVE_JUMP)
    right.append(loop & 0xFF)
    if len(left) > budget:
        return None
    return left, right


def nibble_arp_entries(wave: int, arp_rel: int, half_calls: int,
                       start: int, budget: int,
                       phase: Optional[tuple] = None) -> Optional[tuple]:
    """The unticked nibble shape with each half `half_calls` calls long.

    The unticked -S{m} shape (`_wavetable_entries`) generalised from one
    frame to the record's period: `wave` then a hold on the base note for
    the first half, `wave` with the relative note then a hold carrying `$80`
    for the second, and the jump to entry 0 -- the attack doubling as the
    note half's first call, which is only sound where `tail == wave` (the
    caller's gate, as it is for the shape this generalises). At `half_calls
    == multiplier <= 17` it is that shape byte for byte. None below two
    calls a half or over `budget`. A `nibble_arp_half_cycle` for
    `half_calls` loops over all of its halves, base note first.

    **That shape starts the alternation from the attack whatever the
    counter reads there**, and the original's does not: frame `k` after the
    attack reads `residue + k` (`nibble_arp_first_half`), so the first
    interval frame is wherever the walked residue (`nibble_arp_phases`)
    puts it -- exactly the defect `ticked_nibble_arp_entries` was written
    for, without the tick. `phase` is `(frame0, frame0_r, first_up,
    first_calls)`: the frame-0 lead (`_first_frame_lead`), then a first
    run of `first_calls` on whichever half frame 1 plays, then the halves
    of `half_calls` alternating, the loop over all of them and its target
    the entry after the first run, so the lead and that run play once.
    """
    cycle = _half_cycle(half_calls)
    if min(cycle) < 2:
        return None
    left, right = [], []
    if phase is not None:
        frame0, frame0_r, first_up, first_calls = phase
        if first_calls < 1:
            return None
        note = {True: arp_rel, False: 0x00}
        holds = _hold_run(first_calls - 1, wave)
        left = list(frame0) + [wave] + holds
        right = list(frame0_r) + [note[first_up]] + [0x80] * len(holds)
        loop = start + len(left)
        up = not first_up
        for h in cycle:
            holds = _hold_run(h - 1, wave)
            left += [wave] + holds
            right += [note[up]] + [0x80] * len(holds)
            up = not up
        left.append(WAVE_JUMP)
        right.append(loop & 0xFF)
        if len(left) > budget:
            return None
        return left, right
    for j, h in enumerate(cycle):
        holds = _hold_run(h - 1, wave)
        left += [wave] + holds
        right += ([0x00] * (1 + len(holds)) if j % 2 == 0
                  else [arp_rel] + [0x80] * len(holds))
    left.append(WAVE_JUMP)
    right.append(start & 0xFF)
    if len(left) > budget:
        return None
    return left, right


def gateoff_nibble_arp_entries(wave: int, tail: int, arp_rel: int,
                               half_calls, start: int,
                               budget: int) -> Optional[tuple]:
    """The unticked nibble shape where the tail is the gate-off waveform.

    `nibble_arp_entries` loops to entry 0, which is only sound where `tail
    == wave`; a drum+arp record whose noise tick did not fit its budget
    (`$41` attack, `$40` tail -- Bump_Set_Spike, Kentilla, Spellbound and
    Thrust, all in a full table at budget 5) fell instead to the -S1
    per-call loop, toggling the interval every play call above -S1 where
    the original holds it `nibble_arp_half_calls` calls.

    Here the attack stays at entry 0, `tail` on the base note at entry 1,
    then one delay run per half (`_hold_run`), each carrying the NEXT
    half's note on its last call -- a delay's right side is read on its
    final call (gplay.c:705-717, `tests/test_call_rate.wave_timeline`) --
    and the jump returns to entry 1. That costs no hold entry beside each
    note, so a two-half loop is five entries -- the budget every later
    record is reserved -- for a base half up to 17 calls and the other up
    to 16. The attack and entry 1 are
    the base half's first two calls, so its run is one call shorter, and
    the half after the loop's jump keeps its length because entry 1 is
    replayed (rewriting the waveform already current). A
    `nibble_arp_half_cycle` loops over all of its halves, base first.
    None below two calls a half or over `budget`: the caller keeps the
    per-call loop.
    """
    cycle = _half_cycle(half_calls)
    if min(cycle) < 2:
        return None
    left, right = [wave, tail], [0x00, 0x00]
    for k, h in enumerate(cycle):
        run = _hold_run(h - 1 if k == 0 else h, tail)
        left += run
        right += [0x80] * (len(run) - 1) + [arp_rel if k % 2 == 0 else 0x00]
    left.append(WAVE_JUMP)
    right.append((start + 1) & 0xFF)
    if len(left) > budget:
        return None
    return left, right


def gateoff_nibble_arp_budget_pair(half_calls) -> tuple:
    """The two halves nearest `half_calls`' rate that fit five entries.

    The fallback where `gateoff_nibble_arp_entries` declines the exact
    halves for want of room. Every corpus record reaching it is in a full
    table at the five-entry reservation (Kentilla 20 at -S10, a 22-call
    half; Thrust 18 and 25 at -S3, six-half cycles), and the per-call loop
    it replaces is the worst rate of all -- a half of one call. The pair
    sums to the cycle's mean doubled, rounded, base half the longer; a
    single delay entry spends at most 16 calls, and the base half's run is
    one call short (the attack and entry 1 are its first two), so the pair
    is capped at (17, 16). Measured at 3b1c66d + this tree, 180 s, under
    presets, runs of one frequency inside the notes attacking with
    record 18's ADSR (0A0A, which other records may share) in Thrust's
    subtune 0: original {1: 198, 2: 24}, per-call {1: 266, 3: 12}, this
    pair (4, 3) {1: 198, 2: 30, 3: 14} (C:/t/nibble-gateoff-tail/runs.py).
    Kentilla 20 and Thrust 25 (each a one-subtune file) give that reader
    no qualifying note in the first 180 s on either side; Kentilla 20's
    (17, 16) against 22 is MEASURED SHORT, not equal: its first note
    ($0F0D) attacks at frame 22337, so at -t 1800 (6e467ff + the staged
    merge, presets, `fidelity.run_siddump`), over the 26 notes the original
    holds two-valued for 8+ frames, each paired with the note our song
    attacks 3 frames later (all 514 paired attacks lag by exactly 3; ours
    cannot be found by ADSR state, which it writes only on an instrument
    change), runs of one frequency read once a frame are original
    {2: 548, 3: 120} (mean 2.180 frames = 21.8 calls at -S10; the player's
    22) against this pair {1: 295, 2: 565} (mean 1.657 frames = 16.6 calls;
    the pair's 16.5) -- a quarter short, 5.2 calls a half, so half a call
    is exceeded and no loop of five entries closes it: `gateoff_nibble_arp_entries`
    declines (18, 16) and (17, 17) at five, so the cycle tops out at this
    pair's 33 calls, and the player's (22, 22) takes seven (measured). The two spare entries
    would come out of Kentilla 4, which is itself clipped (95 entries
    wanted, 81 given: the table is full at 255), so closing the gap trades
    one starved record for another and is nibble-per-call-shape-above-s1's
    open decision, not made here. The per-call loop it replaces reads
    {26: 1, 53: 4} at one sample a frame: ten calls a frame is an even
    number of toggles, so a frame-rate reader aliases it to a constant and
    cannot see that defect (C:/t/kentilla-r20-gateoff-pair-measure/m4.py). Thrust
    25 (instrument 26, ADSR $0F0B) first plays at frame ~16430, so it was
    measured at -t 400 (v0.5.510, presets, voice 2, ADSR $0F0B frames
    16430-18993): runs of one frequency read once a frame, original
    {1: 48, 2: 810, 3: 208, 4: 2}, this pair {1: 58, 2: 954, 3: 198}
    (in calls {6: 570, 7: 576}); `fidelity.py --vice -t 400` osplit 0/0,
    and 2081/0 with this shape disabled (the per-call loop)
    (C:/t/thrust-instr26-percall-octave/r2, test_thrust_instr26_octave.py).
    """
    cyc = _half_cycle(half_calls)
    total = min(33, round(2 * Fraction(sum(cyc), len(cyc))))
    return (total - total // 2, total // 2)
