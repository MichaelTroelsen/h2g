"""The packed song's call phase under an outer gate (instrument 63's AD).

**What is wrong without it.** A player with an outer gate of reload O does
nothing at all on one call in O + 1 (`tempo.outer_gate_skip`), so its rows sit
on an uneven frame grid: Game_Killer (O = 9, `-S9`) ticks on frames 0-3, 5-13,
15-23, ... and skips 4, 14, 24. `--skip-gate` makes our row the gate's exact
average -- 20 calls at `-S9`, 2 x 10/9 frames -- which is an EVEN grid, and an
even grid of 10/9 frames lands every tick in the original's frame only at one
phase out of nine. Which phase the packed song starts on was an accident of
gt2reloc's startup, and on Game_Killer it was a wrong one: 2 of every 3 notes
attacked a frame early on every voice (135/367, 126/362, 150/450 exact at 60 s).

**The phase is a sub-frame shift of the whole song, so only a frame-grouped
reader sees it.** siddump runs the `-S` calls of a frame back to back and
samples the chip after the last one (tools/siddump-rt/README.md), and the
harness compares frames; a real CIA spaces the calls evenly and no listener can
hear a constant shift of under one frame. What the phase changes is whether
each of our ticks falls in the frame the original's does -- the alignment every
per-frame column of the report reads through.

**The one lever: instrument 63's attack/decay.** The packed player's first
call after init only resets the song (player.s `mt_initsongnum`), its second is
an empty tick 0 (the counter starts at 1, `mt_initchn`), and the counter then
reloads from `mt_chntempo` = DEFAULTTEMPO, so row 0's tick 0 is call
`1 + DEFAULTTEMPO + 1`. greloc.c:1140-1143 sets DEFAULTTEMPO to
`instr[63].ad - 1` where instrument 63 has `ad >= 2` and no wavetable pointer,
else `6 * multiplier - 1` -- Goattracker's documented "song startup default
tempo" (readme.txt:1083-1086). Row 0's own CMD_SETTEMPO then sets every later
row, so the record lengthens or shortens the startup row and nothing else. It
is not the superseded `--tempo` route (constants.py): that one put the ROW tempo
there, and its packed tunes were silent (docs/SNG2SID-FIDELITY.md, which blamed
the padding; greloc.c:1140 reads `instr[63]` as loaded, before any remap, and
a 2- or 3-call startup row never reaching a gatetimer of 2 is what player.s
`mt_gatetimer` would predict -- a reading, not re-traced here). Here the
startup row stays within a frame of its default `6 * multiplier`, and
`instrument_drop.add_startup_tempo` declines where any record's gatetimer
would not be reached. The editor ignores the record for this song (gplay.c:198 starts
its tick at `6 * multiplier - 1` and row 0's command replaces the tempo before
the first reload); only the packed file reads it.

**A note's onset is the call AFTER its tick 0.** The new-note init writes the
firstwave and returns (player.s `jmp mt_loadregswaveonly`/`mt_loadregs`,
`primitives._first_frame_entry`), and this writer's firstwave is the test bit
`$09`, below `$10`, which siddump does not take for a key-on
(siddump.c:434-437); the wavetable's first entry writes the waveform on the
next call. Measured at -m1 (one dump row a call) on Game_Killer, Chain_Reaction
and Kings_of_the_Beach_intro: every attack at `lead + 1` modulo the row.

**The original's grid, read from the player.** Its rows start on passing calls
`first + frames * j` (`arpeggio.fixed_arp_first_fetch`: the speed counter's
byte; `SongSpeeds.frames_for`), and passing call `w` falls on the frame the
gate cell (`arpeggio.nibble_gate_byte`, reload O) says -- simulated here call by
call, `DEC` / `BPL` on a byte, exactly as the player runs it. Our row `j`
shows on frame `(1 + lead + 1 + row_calls * j) // multiplier`. The phase wanted
is the lead whose frames differ from the original's by one constant on every
row, which needs no trace: it is the model above, evaluated.

**Only where the gate is the play routine's first instruction and its
underflow call returns** (`entry_gate`). There every call, the new-song one
included, passes through the gate, so the cell's byte in the file is the phase
of the first call. The `JMP` spelling inside the routine
(Chain_Reaction $0859) is a different mechanism: it jumps over the speed
counter's DEC and lets the rest of the frame run, and the new-song call never
reaches it; measured with this model's lead it moves the third of
Chain_Reaction's notes that were a frame late to a frame early, and takes
Kings_of_the_Beach_intro from 95/154 exact to 31/154. That family is the
`jmp_gate` clock below, read off the player and modelled by `jmp_gate_ticks`.

**The JMP form's clock** (Chain_Reaction `$0859`; ACE_II, Flash_Gordon, Delta,
Lightforce ... `jmp_gate`). The play routine opens `BIT flag / BMI / BVC
gate`, and the new-song call (flag `$40`) takes the reset path past the gate,
so frame 0 never touches either counter. Every later call runs

    DEC cell / BPL +8 / LDA #O / STA cell / JMP past   ; underflow: cell = O
    DEC ctr / BPL +6 / LDA reload / STA ctr            ; every other call
    LDA cell / BEQ nofetch / LDA ctr / CMP reload / BNE nofetch

so the speed counter steps on O of every O + 1 calls, a row is fetched where it
has just reloaded -- and **the fetch is suppressed on the call that leaves the
cell at 0, to be run on the next call**, the underflow one, whose counter
`DEC` is jumped over and still reads `reload`. A tick therefore never doubles
and never vanishes; it is one call late when it lands on the zero call. Read
against siddump of the originals at 20 s, one row a call, every attack of
Chain_Reaction (173), ACE_II (201), Deep_Strike, Delta, Flash_Gordon,
Food_Feud, Go_Go_Dash, Kings_of_the_Beach_intro (180), Lightforce, Lion_Heart,
Mr_Meaner, Off_the_Cuff, Rock_Tells_the_Tale, Saboteur_II, Shockway_Rider,
Star_Paws, Thanatos, Thundercats, W_A_R, W_A_R_Preview and Zoolook sits on a
frame `jmp_gate_ticks` names; counting frame 0 as a gate pass, as the entry
model does, puts none of them there (0/173, 0/201, 0/180).

`jmp_gate` reads the shape (and that the init sets the flag and does not spend
the new-song call itself: Delta_Mix carries the test but its init `JSR`s the
routine, and its first play call passes the gate); `startup_phase` then
scores the leads against `jmp_gate_ticks` instead of `gate_frames`. Measured
through the packed file at 60 s (C:/t/jmp-form-outer-gate-clock/ab): onsets
exact before -> after, Chain_Reaction 156/232, 176/265, 110/165 -> all;
Kings_of_the_Beach_intro 95/154, 70/112, 188/312 -> all (the entry model's lead
took it to 31/154); ACE_II, Deep_Strike, Food_Feud, Saboteur_II, Zoolook and
Thundercats v0/v1 likewise. The JMP family is scored over the rows that carry a
note (`startup_phase`), which leaves Delta, Thanatos and W_A_R_Preview on the
default row: they were already exact where they sound.
"""
from __future__ import annotations

import re
from collections import Counter
from dataclasses import dataclass
from typing import AbstractSet, Callable, List, Optional, Sequence, Tuple

from ..detect import Detection, PlayerView
from ..sidfile import SidFile
from . import arpeggio as _gw_arpeggio
from . import tempo as _gw_tempo
from .constants import (GT_DEFAULT_TEMPO_CALLS, GT_MIN_TEMPO, OUTER_GATE,
                        OUTER_GATE_PAL, OUTER_GATE_RTS, SPEED_GATE)

# `play_entry` (and PLAY_ENTRY_JMPS, how many `JMP`s it follows) live in
# tempo.py: `outer_gate_match` needs them to pick the gate the play routine
# enters, and this module imports tempo. Re-exported here under the old names.
play_entry = _gw_tempo.play_entry
PLAY_ENTRY_JMPS = _gw_tempo.PLAY_ENTRY_JMPS

# Calls before row 0's startup row begins: the first call after init only
# resets the song (player.s `mt_initsongnum`, the `bpl` not taken once).
STARTUP_RESET_CALLS = 1

# The call, counted from a note's tick 0, on which siddump sees its onset: the
# init call writes only the test-bit firstwave (`$09`, no key-on below `$10`,
# siddump.c:434-437) and the wavetable's first entry the waveform, one call on.
ONSET_CALL = 1


@dataclass(frozen=True)
class StartupPhase:
    """The startup row that puts our onsets on the original's frames.

    `tempo` is instrument 63's AD: the startup row's length in calls, which
    gt2reloc turns into DEFAULTTEMPO `tempo - 1` (greloc.c:1140-1141).
    `default` is the row's length without the record (`6 * multiplier`,
    greloc.c:1143). The two mismatch counts are rows, out of `rows`, whose
    frame offset from the original's differs from the modal one.
    """
    tempo: int
    default: int
    mismatched: int
    default_mismatched: int
    rows: int


def entry_gate(sid: SidFile) -> bool:
    """Whether the outer gate is the play routine's first instruction and its
    underflow call does nothing else.

    Three spellings qualify, each at `play_entry`: `OUTER_GATE_RTS` (Warhawk,
    Game_Killer), `OUTER_GATE_PAL` (Las_Vegas_Video_Poker), and the `JMP`
    spelling `OUTER_GATE` where the jump lands on an `RTS` (Kentilla `$AB10
    JMP $AEEE`, `$AEEE RTS`). **And it must be the gate the rest of the writer
    reads**: `_find_outer_gate` and `nibble_gate_byte` take
    `tempo.outer_gate_match` -- the first match of `OUTER_GATE`, then
    `OUTER_GATE_RTS`, except that an `RTS` gate the play routine enters wins
    (Bump_Set_Spike carries an NTSC gate at `$B00B` above the one its play
    address enters at `$B016`; the reload read used to be the NTSC one's) -- then the PAL spelling at the entry.
    """
    at = play_entry(sid)
    if at is None:
        return False
    data = sid.data
    first = _gw_tempo.outer_gate_match(sid)
    if first is not None:
        if first.start() != at or first.group(1) != first.group(3):
            return False
        if first.re is OUTER_GATE_RTS:
            return True
        target = sid.to_offset(first.group(4)[0] | first.group(4)[1] << 8)
        return 0 <= target < len(data) and data[target] == 0x60   # RTS
    pal = OUTER_GATE_PAL.match(data, at)
    return pal is not None and pal.group(1) == pal.group(3)


# What the JMP form does after it jumps past the speed counter's DEC:
# `LDA cell / BEQ nofetch / LDA ctr / CMP reload / BNE nofetch`. The fetch is
# suppressed where the cell reads 0 (Chain_Reaction $0871-$0883).
_JMP_GATE_FETCH = re.compile(
    rb"\xad(..)\xf0.\xad(..)\xcd(..)\xd0", re.DOTALL)
# How far past the jump's landing the fetch test is looked for: Chain_Reaction
# puts `LDA $0CF6,X / STA $0CF9 / TAY` (7 bytes) between them.
_JMP_GATE_FETCH_WINDOW = 16
# How far before the gate the new-song test `BIT flag / BMI / BVC` is looked
# for; the BVC lands on the `LDX` right above the gate.
_JMP_GATE_ENTRY_WINDOW = 128
# How far into the init routine a `JSR` of the play routine is looked for
# (at most; it stops at the first `RTS` or `JMP` byte).
INIT_WINDOW = 96
_LDX_LENGTHS = {0xAE: 3, 0xA6: 2, 0xA2: 2}      # LDX abs / zp / #imm


def jmp_gate(sid: SidFile) -> bool:
    """Whether the outer gate is the JMP form INSIDE the play routine, past a
    new-song test, with the fetch suppressed on the call that leaves the cell
    at 0 (Chain_Reaction `$0859`) -- the clock `jmp_gate_ticks` runs.

    All of: the first `OUTER_GATE` match (the one `nibble_gate_byte` and
    `_find_outer_gate` read) names one cell twice; the speed counter's own
    `DEC / BPL +6 / LDA reload / STA` follows it directly and the `JMP` lands
    just past that block; the landing is followed by `LDA cell / BEQ / LDA ctr
    / CMP reload / BNE` on the same three cells; and the gate sits behind a
    `BIT flag / BMI / BVC` whose `BVC` lands on the `LDX` above it, and the
    song's init stores `$40` to that flag (`LDA #$40 / STA flag`) -- V set, the
    test the new-song call fails, so frame 0 passes neither counter -- and the
    init does not itself `JSR` the routine, which would spend that call before
    the first play call. Delta_Mix's does (`CCEE JSR $C012`): its first play
    call passes the gate (siddump of the original: every attack on the other
    grid). Not `entry_gate`'s: a gate that IS the play entry has no such
    test.
    """
    data = sid.data
    gate = OUTER_GATE.search(data)
    if gate is None or gate.group(1) != gate.group(3):
        return False
    block = SPEED_GATE.match(data, gate.end())
    if block is None or block.group(1) != block.group(3):
        return False
    landing = sid.to_offset(gate.group(4)[0] | gate.group(4)[1] << 8)
    if landing != block.end():
        return False
    fetch = _JMP_GATE_FETCH.search(
        data, landing, landing + _JMP_GATE_FETCH_WINDOW + 10)
    if (fetch is None or fetch.start() > landing + _JMP_GATE_FETCH_WINDOW
            or fetch.group(1) != gate.group(1)
            or fetch.group(2) != block.group(1)
            or fetch.group(3) != block.group(2)):
        return False
    found = _new_song_test(data, gate.start())
    if found is None:
        return False
    flag, bit_at = found
    if (b"\xa9\x40\x8d" + flag) not in data:
        return False
    # The routine starts at its `LDA #vol / STA $D418` prefix when it has one.
    start = bit_at - 5 if data[bit_at - 3:bit_at] == b"\x8d\x18\xd4" else bit_at
    jsr = b"\x20" + bytes([sid.to_address(start) & 0xFF,
                           sid.to_address(start) >> 8])
    init = sid.to_offset(sid.init_addr)
    if not 0 <= init < len(data):
        return False
    # The init's straight-line start: to its first `RTS` / `JMP` byte (Kings
    # of the Beach's init ends in a `JMP`, and the raster handler that calls
    # the routine sits right behind it).
    end = next((k for k in range(init, min(init + INIT_WINDOW, len(data)))
                if data[k] in (0x60, 0x4C)), init + INIT_WINDOW)
    return jsr not in data[init:end]


def _new_song_test(data: bytes, gate_at: int) -> Optional[Tuple[bytes, int]]:
    """The flag address bytes and the file offset of the `BIT flag / BMI / BVC`
    whose `BVC` branches (on V clear) to the `LDX` that ends exactly at
    `gate_at`, or None."""
    for ldx_len in (3, 2):
        landing = gate_at - ldx_len
        if landing < 5 or _LDX_LENGTHS.get(data[landing]) != ldx_len:
            continue
        for at in range(max(5, landing - _JMP_GATE_ENTRY_WINDOW), landing):
            rel = data[at + 1] - 256 if data[at + 1] > 127 else data[at + 1]
            if (data[at] == 0x50 and at + 2 + rel == landing
                    and data[at - 5] == 0x2C and data[at - 2] == 0x30):
                return bytes(data[at - 4:at - 2]), at - 5
    return None


def jmp_gate_ticks(cell: int, reload: int, counter: int, counter_reload: int,
                   count: int) -> List[int]:
    """The frame of each of the first `count` fetches under the JMP form.

    Frame 0 is the new-song call, which passes neither counter. Each later
    call steps the cell (`DEC` / `BPL`, reload on underflow) and, unless it
    underflowed, the speed counter (reload on underflow); a fetch is due when
    the counter reads its reload, and runs unless the cell reads 0 -- then it
    is due again, unchanged, on the next call. Chain_Reaction, reload 3, speed
    counter reload 1, both bytes 0: fetches on frames 2, 5, 7, 10, 13, 15.
    """
    out: List[int] = []
    cell &= 0xFF
    counter &= 0xFF
    frame = 0
    while len(out) < count:
        frame += 1
        cell = (cell - 1) & 0xFF
        if cell & 0x80:
            cell = reload & 0xFF
        else:
            counter = (counter - 1) & 0xFF
            if counter & 0x80:
                counter = counter_reload & 0xFF
        if cell != 0 and counter == counter_reload & 0xFF:
            out.append(frame)
    return out


def gate_frames(gate_byte: int, reload: int, count: int) -> List[int]:
    """The frame each of the first `count` passing calls falls on.

    The gate as the player runs it: `DEC cell` on every call, and where the
    byte goes negative (`BPL` not taken) `cell = reload` and the call returns.
    Game_Killer's byte 4, reload 9: frames 0-3 pass, 4 is skipped, 5-13 pass.
    """
    out: List[int] = []
    cell, frame = gate_byte & 0xFF, 0
    while len(out) < count:
        cell = (cell - 1) & 0xFF
        if cell & 0x80:
            cell = reload & 0xFF
        else:
            out.append(frame)
        frame += 1
    return out


def onset_mismatches(lead: int, row_calls: int, multiplier: int, first: int,
                     frames: int, gate_byte: int, reload: int,
                     rows: int, counter_reload: Optional[int] = None,
                     only: Optional[AbstractSet[int]] = None) -> int:
    """Rows of `rows` whose frame offset from the original's is not the modal one.
    With `only`, just those rows are scored (and the mode taken over them).

    Ours: row `j`'s onset is call `STARTUP_RESET_CALLS + lead + ONSET_CALL +
    row_calls * j`, on frame `call // multiplier`. The original's: passing call
    `first + frames * j` on the frame `gate_frames` gives it -- or, with
    `counter_reload` (the JMP form, `jmp_gate`), the `j`th fetch
    `jmp_gate_ticks` names, `first` being the speed counter's byte. Zero means
    every row lands in the original's frame, one constant lag apart.
    """
    if counter_reload is None:
        real = gate_frames(gate_byte, reload, first + frames * rows + 1)
        real = [real[first + frames * j] for j in range(rows)]
    else:
        real = jmp_gate_ticks(gate_byte, reload, first, counter_reload, rows)
    scored = range(rows) if only is None else sorted(j for j in only if j < rows)
    diffs = Counter(
        (STARTUP_RESET_CALLS + lead + ONSET_CALL + row_calls * j) // multiplier
        - real[j] for j in scored)
    return len(scored) - max(diffs.values(), default=0)


def default_startup_calls(multiplier: int) -> int:
    """The startup row without instrument 63: `6 * multiplier` calls.

    greloc.c:1143 (`DEFAULTTEMPO multiplier*6-1`), and the counter reloads to
    DEFAULTTEMPO, so the row is one call longer than the value.
    """
    return GT_DEFAULT_TEMPO_CALLS * max(1, multiplier)


def startup_phase(sid: SidFile, det: Detection, multiplier: int,
                  tempos: Sequence[int],
                  onset_rows: Optional[Callable[[int, int], Optional[AbstractSet[int]]]]
                  = None) -> Optional[StartupPhase]:
    """The startup row that puts the start subtune's onsets on the original's
    frames, or None where the default already does or nothing here is read.

    `tempos` is the CMD_SETTEMPO calls per subtune group (`convert`'s
    `group_tempos`). Declined unless: the file is packed above `-S1` (at one
    call a frame there is no phase); the gate is `entry_gate`'s or `jmp_gate`'s
    (the latter scored against `jmp_gate_ticks`); the gate byte,
    the first fetch and the start subtune's speed are all read; and the start
    subtune's row is EXACTLY the corrected one, `row_calls * O == frames * (O +
    1) * multiplier` -- a row the tempo rounded drifts against the grid and has
    no phase to be on. The candidate leads are the default and the
    `multiplier - 1` below it, which covers every phase and moves the song by
    under one frame; the fewest mismatched rows wins, the default on a tie.

    **A JMP-form gate is scored over the rows that carry a note.** A row with
    nothing to attack has nothing to put on a frame, and a phase chosen to
    please them can cost a song that was already exact where it sounds:
    Thanatos, W_A_R_Preview and Delta attack every note in the original's
    frame at the default startup row, yet 40 of 80, 36 of 144 and 20 of 40
    rows are off it, and Thanatos' gate column went 1 -> .7495 under the
    phase chosen over all of them. `onset_rows(subtune, horizon)` names the
    rows (`instrument_drop.onset_rows` on the finished bytes); None, or an
    empty answer, scores every row. The entry family keeps scoring every
    row -- its six startup rows were measured that way.
    """
    if multiplier < 2 or isinstance(sid, PlayerView) or len(det.players) > 1:
        return None
    speeds = _gw_tempo.find_song_speeds(sid, det)
    if speeds is None:
        return None
    s0 = _gw_tempo.pack_subtune(speeds, sid.start_song)
    reload = _gw_tempo.outer_gate_skip(sid, s0)
    jmp = jmp_gate(sid)
    if not reload or not (jmp or entry_gate(sid)):
        return None
    gate_byte = _gw_arpeggio.nibble_gate_byte(sid)
    first = _gw_arpeggio.fixed_arp_first_fetch(sid, det)
    frames = speeds.frames_for(s0)
    if gate_byte is None or first is None or frames is None:
        return None
    if not 0 <= s0 < len(tempos):
        return None
    row_calls = tempos[s0]
    if row_calls * reload != frames * (reload + 1) * multiplier:
        return None
    only = None
    if jmp and onset_rows is not None:
        only = onset_rows(s0, startup_horizon(multiplier, reload)) or None
    return best_startup(row_calls, multiplier, first, frames, gate_byte, reload,
                        jmp=jmp, only=only)


def startup_horizon(multiplier: int, reload: int) -> int:
    """Rows `best_startup` scores: `4 * multiplier * (reload + 1)`, which covers
    both grids' common period."""
    return 4 * multiplier * (reload + 1)


def best_startup(row_calls: int, multiplier: int, first: int, frames: int,
                 gate_byte: int, reload: int, jmp: bool = False,
                 only: Optional[AbstractSet[int]] = None
                 ) -> Optional[StartupPhase]:
    """`startup_phase`'s choice, from the values it read.

    Every lead from the default down `multiplier - 1` calls is scored over
    `4 * multiplier * (reload + 1)` rows, which covers both grids' common
    period. The fewest mismatched rows wins and, among equals, the lead
    nearest the default -- where `multiplier` is a multiple of the reload
    above 1, several leads are exact and the smallest move is taken. None
    where the default is already as good as any.
    """
    rows = startup_horizon(multiplier, reload)
    default = default_startup_calls(multiplier)
    leads = [a for a in range(default, default - multiplier, -1)
             if a - 1 >= GT_MIN_TEMPO]
    counter_reload = frames - 1 if jmp else None
    score = {a: onset_mismatches(a, row_calls, multiplier, first, frames,
                                 gate_byte, reload, rows, counter_reload, only)
             for a in leads}
    best = min(leads, key=lambda a: (score[a], default - a))
    if score[best] >= score[default]:
        return None
    return StartupPhase(best, default, score[best], score[default], rows)


def nibble_gate_step_lead(sid: SidFile, det: Detection, multiplier: int,
                          gate_skip: Optional[int], written: bool) -> int:
    """Calls the attack's own counter step outlasts a one-frame lead, or 0.

    **Under the outer gate a counter step is `h = m * (O + 1) / O` of our
    calls, and the attack's step is the first of them.** The rows are on that
    lattice (`--skip-gate`: a row is `frames * h` calls), our onset is the
    call after tick 0 (`ONSET_CALL`) and stands for the attack's passing call,
    and `startup_phase` puts the lattice on the original's frames -- so the
    counter's next step, and the first frame the nibble block plays, begins
    `h` calls after the onset. The phased nibble shapes
    (`arpeggio.ticked_nibble_arp_entries`, `nibble_arp_entries(phase=)`) put
    it after a frame-0 lead of `m`: every half boundary, and the noise tick's
    start, `h - m` calls early. Sampled once a frame that early boundary
    lands in the frame before the original's once every `O` steps, which is
    exactly the stretched half: International_Karate and Kentilla (O 10,
    -S10, `h` 11) put the one-step record's long sampled half on the other
    note on every note, Warhawk and Proteus (O 7, -S7, `h` 8) likewise
    (C:/t/ik-kentilla-gate-long-half/abnote.py, per note against the
    original). Where `_nibble_gate_shape` lays the original's own frames the
    boundaries are on frames and this does not arise.

    0 where the nibble counter is not behind the gate, `h` is not whole (the
    halves are then a spread `nibble_arp_half_cycle`), the frame-0 lead is not
    an entry (`written`, `--no-test-restart`, whose firstwave plays frame 0),
    or the gate is not `entry_gate`'s -- the precondition of `startup_phase`,
    without which nothing anchors our lattice to the original's frames.
    """
    per = det.arp_nibble_period
    m = max(1, multiplier)
    if (written or not gate_skip or per is None
            or not _gw_arpeggio.nibble_arp_counter_gated(sid, per)):
        return 0
    step, rest = divmod(m * (gate_skip + 1), gate_skip)
    if rest or step <= m or not entry_gate(sid):
        return 0
    return step - m
