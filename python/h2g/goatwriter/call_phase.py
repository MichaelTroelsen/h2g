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
Kings_of_the_Beach_intro from 95/154 exact to 31/154. That family is left
alone until its own clock is read.
"""
from __future__ import annotations

from collections import Counter
from dataclasses import dataclass
from typing import List, Optional, Sequence

from ..detect import Detection, PlayerView
from ..sidfile import SidFile
from . import arpeggio as _gw_arpeggio
from . import tempo as _gw_tempo
from .constants import (GT_DEFAULT_TEMPO_CALLS, GT_MIN_TEMPO, OUTER_GATE,
                        OUTER_GATE_PAL, OUTER_GATE_RTS)

# How many `JMP`s to follow from the PSID play address to the routine's first
# instruction (Kentilla's play address is the gate itself; a jump table in
# front of it is followed, never searched past).
PLAY_ENTRY_JMPS = 4

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


def play_entry(sid: SidFile) -> Optional[int]:
    """Image offset of the first instruction the play routine runs, or None.

    Follows a chain of `JMP`s from the PSID play address. None where the
    header names no play routine (the tune installs its own IRQ), or the chain
    leaves the image.
    """
    if not sid.play_addr:
        return None
    at = sid.to_offset(sid.play_addr)
    for _ in range(PLAY_ENTRY_JMPS + 1):
        if not 0 <= at < len(sid.data) - 2:
            return None
        if sid.data[at] != 0x4C:            # JMP abs
            return at
        at = sid.to_offset(sid.data[at + 1] | sid.data[at + 2] << 8)
    return None


def entry_gate(sid: SidFile) -> bool:
    """Whether the outer gate is the play routine's first instruction and its
    underflow call does nothing else.

    Three spellings qualify, each at `play_entry`: `OUTER_GATE_RTS` (Warhawk,
    Game_Killer), `OUTER_GATE_PAL` (Las_Vegas_Video_Poker), and the `JMP`
    spelling `OUTER_GATE` where the jump lands on an `RTS` (Kentilla `$AB10
    JMP $AEEE`, `$AEEE RTS`). **And it must be the gate the rest of the writer
    reads**: `_find_outer_gate` and `nibble_gate_byte` take the first match of
    `OUTER_GATE`, then `OUTER_GATE_RTS`, then the PAL spelling at the entry --
    Bump_Set_Spike carries an NTSC gate at `$B00B` above the one its play
    address enters at `$B016`, and the reload read is the NTSC one's.
    """
    at = play_entry(sid)
    if at is None:
        return False
    data = sid.data
    first = OUTER_GATE.search(data) or OUTER_GATE_RTS.search(data)
    if first is not None:
        if first.start() != at or first.group(1) != first.group(3):
            return False
        if first.re is OUTER_GATE_RTS:
            return True
        target = sid.to_offset(first.group(4)[0] | first.group(4)[1] << 8)
        return 0 <= target < len(data) and data[target] == 0x60   # RTS
    pal = OUTER_GATE_PAL.match(data, at)
    return pal is not None and pal.group(1) == pal.group(3)


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
                     rows: int) -> int:
    """Rows of `rows` whose frame offset from the original's is not the modal one.

    Ours: row `j`'s onset is call `STARTUP_RESET_CALLS + lead + ONSET_CALL +
    row_calls * j`, on frame `call // multiplier`. The original's: passing call
    `first + frames * j` on the frame `gate_frames` gives it. Zero means every
    row lands in the original's frame, one constant lag apart.
    """
    real = gate_frames(gate_byte, reload, first + frames * rows + 1)
    diffs = Counter(
        (STARTUP_RESET_CALLS + lead + ONSET_CALL + row_calls * j) // multiplier
        - real[first + frames * j] for j in range(rows))
    return rows - max(diffs.values())


def default_startup_calls(multiplier: int) -> int:
    """The startup row without instrument 63: `6 * multiplier` calls.

    greloc.c:1143 (`DEFAULTTEMPO multiplier*6-1`), and the counter reloads to
    DEFAULTTEMPO, so the row is one call longer than the value.
    """
    return GT_DEFAULT_TEMPO_CALLS * max(1, multiplier)


def startup_phase(sid: SidFile, det: Detection, multiplier: int,
                  tempos: Sequence[int]) -> Optional[StartupPhase]:
    """The startup row that puts the start subtune's onsets on the original's
    frames, or None where the default already does or nothing here is read.

    `tempos` is the CMD_SETTEMPO calls per subtune group (`convert`'s
    `group_tempos`). Declined unless: the file is packed above `-S1` (at one
    call a frame there is no phase); the gate is `entry_gate`'s; the gate byte,
    the first fetch and the start subtune's speed are all read; and the start
    subtune's row is EXACTLY the corrected one, `row_calls * O == frames * (O +
    1) * multiplier` -- a row the tempo rounded drifts against the grid and has
    no phase to be on. The candidate leads are the default and the
    `multiplier - 1` below it, which covers every phase and moves the song by
    under one frame; the fewest mismatched rows wins, the default on a tie.
    """
    if multiplier < 2 or isinstance(sid, PlayerView) or len(det.players) > 1:
        return None
    speeds = _gw_tempo.find_song_speeds(sid, det)
    if speeds is None:
        return None
    s0 = _gw_tempo.pack_subtune(speeds, sid.start_song)
    reload = _gw_tempo.outer_gate_skip(sid, s0)
    if not reload or not entry_gate(sid):
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
    return best_startup(row_calls, multiplier, first, frames, gate_byte, reload)


def best_startup(row_calls: int, multiplier: int, first: int, frames: int,
                 gate_byte: int, reload: int) -> Optional[StartupPhase]:
    """`startup_phase`'s choice, from the values it read.

    Every lead from the default down `multiplier - 1` calls is scored over
    `4 * multiplier * (reload + 1)` rows, which covers both grids' common
    period. The fewest mismatched rows wins and, among equals, the lead
    nearest the default -- where `multiplier` is a multiple of the reload
    above 1, several leads are exact and the smallest move is taken. None
    where the default is already as good as any.
    """
    rows = 4 * multiplier * (reload + 1)
    default = default_startup_calls(multiplier)
    leads = [a for a in range(default, default - multiplier, -1)
             if a - 1 >= GT_MIN_TEMPO]
    score = {a: onset_mismatches(a, row_calls, multiplier, first, frames,
                                 gate_byte, reload, rows) for a in leads}
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
    without which nothing anchors our lattice to the original's frames
    (Bump_Set_Spike, whose play address enters below an NTSC gate).
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
