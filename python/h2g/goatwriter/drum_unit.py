"""How many frames a drum note holds the gate: its first duration unit.

The drum block (`detect` bit $01) closes the gate with a mask written the
first time `(duration & $1F) - 1 >= remaining` holds, and `remaining` steps
once per duration UNIT, so the gate stays on for the note's first unit
(Delta `$C127-$C139`: `LDA #$FE / STA $C301,X`, the byte `$C20A AND`s the
waveform with). A unit is the span between two row fetches of the player's
clock, and that clock is two counters (`tempo.outer_gate_match` and the speed
gate behind it): the outer one withholds a call in `skip + 1`, the inner one
fetches a row every `gate` working calls. A unit is therefore `gate` frames,
or one more where it holds a skipped call -- **which a NOTE gets is its row's
place on that clock, and the clock is static**: both counters start at the
file's own bytes, so the frame of every row fetch is a plain simulation
(`arpeggio._pitch_seq_calls` is the same loop for the bit-$10 phase).

Measured on the originals (py65 traces of the start subtune, 6000 frames, the
leading gated frames of each onset of every record carrying both bits $01 and
$02, so reaching `_wave_alternate_entries`), against the simulation walked
over the converted orderlists (`fetch_frames`, `drum_first_units`):

    Delta           gate 2 skip 4  0F09  3 on 100%         predicted 3 on 100%
    W_A_R_Preview   gate 2 skip 8  0A09  3 on 100%         predicted 3 on 100%
    Flash_Gordon    gate 2 skip 8  0F07  2 on 100%         predicted 2 on 100%
    Knucklebusters  gate 2 skip 6  0F09  2 on 66%, 3 34%   predicted 67% / 33%
    Deep_Strike     gate 2 skip 3  0F07  2 on 33%, 3 67%   predicted 33% / 67%
    Food_Feud       gate 2 skip 3  0A0A  2 on 33%, 3 67%   predicted 33% / 67%

The song-wide value (`wavetable._real_unit_frames`) is the MEAN unit rounded,
and an exact half rounds down: right where a record's notes spread over the
clock's cycle (Knucklebusters, Deep_Strike, Food_Feud: the mode is the mean's
rounding), wrong where they do not. Every drum note of Delta and
W_A_R_Preview sits on the cycle's long unit (a beat is a whole number of
cycles), and every one of Flash_Gordon's on a short one -- the same gate and
skip as W_A_R_Preview, a different starting phase (outer cell 4, not 3),
which is why no constant for the cycle's start can stand in for the
simulation. A wavetable is per instrument, so the note's own unit cannot be
said; the record's mode over the notes the song plays can (`drum_first_units`).
"""
from __future__ import annotations

from collections import Counter
from typing import Dict, List, Optional, Tuple

from ..detect import Detection
from ..sidfile import SidFile
from . import tempo as _gw_tempo
from .arpeggio import _abs_writers, _countdown, _walk_note_rows
from .constants import CMD_TONEPORTA, SPEED_GATE


def fetch_frames(outer: int, inner: int, gate: int, skip: int,
                 need: int) -> List[int]:
    """The play call (1, 2, ...) each of the first `need` row fetches lands on.

    `outer` and `inner` are the two counters' values before call 1 (the
    file's bytes), `skip` and `gate` their reloads: the outer counts down
    every call and a call that underflows it does no work; the inner counts
    down on the working calls and fetches when it holds `gate - 1` while the
    outer is not zero (`arpeggio._pitch_seq_calls`, the fetch guard
    `LDA outer / BEQ`, `LDA inner / CMP speed / BNE`).
    """
    out: List[int] = []
    call = 0
    while len(out) < need and call < need * (gate + 1) * (skip + 1) + 64:
        call += 1
        outer, under = _countdown(outer, skip)
        if not under:
            inner, _ = _countdown(inner, gate - 1)
        if outer != 0 and inner == gate - 1:
            out.append(call)
    return out


def clock_cells(sid: SidFile) -> Optional[Tuple[int, int]]:
    """(outer, inner) counter bytes before the first play call, or None.

    Read the way `arpeggio._pitch_seq_outer_flat_clock` reads them: the
    speed gate directly behind the outer gate, and no instruction of the
    file writing either cell but the gate's own `DEC` and reload `STA`. A
    file whose init stores a counter (Knucklebusters, Dragons_Lair_Part_II)
    has a first value this does not read, and is declined.
    """
    m = _gw_tempo.outer_gate_match(sid)
    if m is None:
        return None
    data = sid.data
    g = SPEED_GATE.match(data, m.end())
    if g is None:
        return None
    if _abs_writers(data, m.group(1)) != 2 or _abs_writers(data,
                                                           g.group(1)) != 2:
        return None
    cells = []
    for addr in (m.group(1), g.group(1)):
        at = sid.to_offset(addr[0] | addr[1] << 8)
        if not 0 <= at < len(data):
            return None
        cells.append(data[at])
    return cells[0], cells[1]


def drum_first_units(sid: SidFile, det: Detection, tracks: List[List[int]],
                     patterns: List[List[int]]) -> Dict[int, int]:
    """`{Goattracker instrument: frames its notes' first unit lasts}`.

    An instrument whose mode ties with what `wavetable` would write without
    this (the song-wide `1 + _noise_tick_frames`) keeps that. Walked over the
    finished orderlists of the START subtune, one lap, repeats expanded and
    the instrument column sticky, as `arpeggio.fixed_arp_phases` is; one
    converted row is one duration unit, so a note's row index is its fetch
    index on the clock. A tie row (`CMD_TONEPORTA`) restarts no wavetable and
    casts no vote.

    Empty -- so the song is byte-identical to before -- where the player has
    no outer gate, where its counters' first values are not the file's
    (`clock_cells`), where the speeds cannot be read, or where a dropped
    subtune has shifted the orderlist numbering away from the PSID's.
    """
    try:
        speeds = _gw_tempo.find_song_speeds(sid, det if det.can_convert
                                            else None)
    except Exception:                                   # noqa: BLE001
        return {}
    if speeds is None or len(tracks) != 3 * max(sid.subtunes, 1):
        return {}
    idx = max(0, getattr(sid, "start_song", 1) - 1)
    gate = speeds.frames_for(idx)
    skip = speeds.skip_for(idx)
    cells = clock_cells(sid)
    if not gate or not skip or cells is None or 3 * idx + 3 > len(tracks):
        return {}
    notes = []
    for track in tracks[3 * idx:3 * idx + 3]:
        for row, instr, pat, r in _walk_note_rows(track, patterns):
            if pat[r + 2] != CMD_TONEPORTA:
                notes.append((row, instr))
    if not notes:
        return {}
    fetched = fetch_frames(cells[0], cells[1], gate, skip,
                           max(row for row, _ in notes) + 2)
    from .wavetable import _noise_tick_frames
    current = 1 + _noise_tick_frames(sid, det)
    votes: Dict[int, Counter] = {}
    for row, instr in notes:
        if row + 1 < len(fetched):
            votes.setdefault(instr, Counter())[
                fetched[row + 1] - fetched[row]] += 1
    out: Dict[int, int] = {}
    for instr, counts in votes.items():
        best = max(counts.values())
        modes = sorted(n for n, c in counts.items() if c == best)
        out[instr] = current if current in modes else modes[0]
    return out
