"""The waveform a Hubbard voice latches before its first note.

Measured on the twelve files of the todo.md entry "Wave: the original latches
a waveform on a voice before its first note and we stay `$00`" (Pygmies_Revenge,
Chimera, Phantoms_of_the_Asteroid, Master_of_Magic, Kentilla, Crazy_Comets,
Last_V8 and its C128 build, Hunter_Patrol, Samantha_Fox_Strip_Poker,
Formula_1_Simulator, Gremlins).

**The mechanism is the player's per-frame control write, not a command.** The
classic play routine loads the voice's held instrument, ANDs its control byte
with the gate mask and stores the result in `$D404` on EVERY frame, rests
included (Pygmies_Revenge `$1487-$1490`: `LDA $1654,X / AND $165D,X /
STA $D404,Y`, with `$1654,X` reloaded from the instrument record's control
byte at `$13D9` and the mask `$165D,X` set to `$FE` by a rest). A voice whose
first events are rests therefore shows the waveform of the instrument it HOLDS
-- gate clear -- from the first or second frame, long before its first note.
Before a pattern names an instrument the voice holds the one the player's init
wrote into every slot (`Detection.init_instrument`: `$0F` in Pygmies, whose
record 15 has control `$41`, so `$40` is latched from frame 2) or, where the
init writes none, the file image of the index array
(`Detection.initial_instruments`).

Goattracker starts a voice on waveform `$00` and only a note, `CMD_SETWAVE` or
a wavetable step changes it. Compared class by class (`wave & $F0`) the wave
column charges every frame before the first attack: 1535 of Pygmies' 1887
disagreeing frames. None of it is audible -- the original's gate is clear in
all of them -- so this is a fidelity-of-state emission, and the only thing it
costs is a free command cell and (where the entry pattern is played again
later) one pattern copy.

The prediction `control(instrument the voice starts on) & $FE` against the
frames before each voice's first gate, siddump at -t60, subtune 0: Pygmies
`$40 $40 $40` (init `$0F`), Chimera v1/v2 `$40`, Crazy_Comets v0 `$80` v2
`$40`, Formula_1 v1 `$40`, Gremlins v1 `$40`, Hunter_Patrol v0/v1 `$10`,
Last_V8 v0 `$40` v2 `$80`, Last_V8_C128 v0/v2 `$40`, Master_of_Magic v0 `$10`
v2 `$40`, Phantoms v0/v2 `$40`, Kentilla v1 `$14` (then a `$80` alternation
this does not reproduce): every voice that latches, in the class it latches.
A voice whose first event is already a note (Chimera v0, Crazy_Comets v1, ...)
has no such frames and is left alone, which is `apply_pre_note_waves`'s
first-note test.

**What it costs, measured** (A/B on the twelve, `-t 180 --presets --sound`):
the wave column rises on eleven (Pygmies .930 -> .987, Master_of_Magic .967 ->
.995, Kentilla .971 -> .994, Chimera .924 -> .956, ...), `ctrl`/`ring` rise on
Kentilla, and no attack, gate or envelope column moves. `tiefr` FALLS 0.4-4.5
pp on six files (Phantoms .645 -> .599): once a waveform is selected, siddump
prints the packed player's idle-voice instrument vibrato (`player.s`
`mt_effect_0` runs a vibrato at delay 0, where `gplay.c:759` breaks) as ties,
which `wave = $00` hid. Those ties are silent (the gate is clear) and
`tie_ratio_audible` does not move.

Off by default (`convert(pre_note_wave=...)`): it moves the bytes of every
file it reaches (23 of 89 when forced on the whole corpus).
"""
from __future__ import annotations

from typing import List, Optional, Tuple

from .detect import Detection
from .sidfile import SidFile

# gcommon.h CMD_SETWAVE; `patterns.CMD_SETWAVE`. Spelled here as well because
# `patterns` imports the writer side and this module is read by it.
CMD_SETWAVE = 7

# Goattracker's note column (gcommon.h FIRSTNOTE/LASTNOTE).
_FIRSTNOTE = 0x60
_LASTNOTE = 0xBC

# The orderlist grammar (gplay.c:966-988): $00-$CF pattern, $D0-$DF repeat,
# $E0-$FE transpose, $FF restart + position.
_COMMAND_FLOOR = 0xD0
_REPEAT_END = 0xE0
_RESTART = 0xFF
# Goattracker's longest orderlist, entries and the `FF nn` pair included
# (gcommon.h MAX_SONGLEN 254), less one for the length byte's own bias.
_MAX_ORDERLIST = 253


def start_waves(sid: SidFile, det: Detection) -> Tuple[Optional[int], ...]:
    """Per voice, the control byte (gate clear) the ORIGINAL's player writes
    while the voice still holds the instrument it started on, or None where
    that is not known or selects no waveform.

    Subtune 0 only is the caller's business: the index array of a later
    subtune is whatever the last tune left (`note_passes._track_start`).
    """
    if det.pre_instrument_silence or det.instr_stride <= 0 or det.instr_start < 0:
        return (None, None, None)
    if det.init_instrument is not None:
        index = (det.init_instrument,) * 3
    elif len(det.initial_instruments) == 3:
        index = tuple(det.initial_instruments)
    else:
        return (None, None, None)
    out: List[Optional[int]] = []
    for i in index:
        at = det.instr_start + i * det.instr_stride + 2
        if i >= det.instr_used or at >= len(sid.data):
            out.append(None)
            continue
        wave = sid.data[at] & 0xFE
        out.append(wave if wave & 0xF0 else None)
    return tuple(out)


def _entry(track: List[int]) -> Optional[int]:
    """Index in `track` of the first byte naming a pattern."""
    operand = False
    for k, b in enumerate(track):
        if operand:
            operand = False
        elif b == _RESTART:
            operand = True
        elif b < _COMMAND_FLOOR:
            return k
    return None


def _first_note_row(pattern: List[int]) -> Optional[int]:
    for r in range(0, len(pattern) - 3, 4):
        if pattern[r] == 0xFF:           # ENDPATT
            return None
        if _FIRSTNOTE <= pattern[r] <= _LASTNOTE:
            return r // 4
    return None


def _first_note_instrument(patterns: List[List[int]], track: List[int],
                           at: int) -> Optional[int]:
    """The instrument named on the first note of `track`'s first lap, or None
    where that note names none (it would inherit the held instrument) or no
    pattern of the track has a note."""
    operand = False
    for b in track[at:]:
        if operand:
            operand = False
        elif b == _RESTART:
            operand = True
        elif b < _COMMAND_FLOOR and b < len(patterns):
            r = _first_note_row(patterns[b])
            if r is not None:
                return patterns[b][4 * r + 1] or None
    return None


def quiet_idle_vibrato(pattern: List[int], first_note_instrument: Optional[int],
                       vibrato: dict) -> bool:
    """Stop the packed player vibrating a voice that has not played yet.

    A latched waveform makes siddump print the voice's frequency moves, and
    the packed player moves it: `mt_effect_0` runs the HELD instrument's
    vibrato at delay 0 (a voice starts on instrument 1, and a command-free row
    reloads `mt_chnparam` from `mt_insvibparam`), where `gplay.c:759` breaks
    on `!vibdelay`. Phantoms_of_the_Asteroid's instrument 1 vibrates around
    frequency 0 from the second call, which `tiefr` then counts as ties the
    original does not have. The cure is the instrument, not a command: row 0
    names an instrument with no vibrato (`vibrato[n] == 0`). An instrument
    change on a rest sets `mt_chninstr` and nothing else (`player.s:1252`,
    `gplay.c:914`), and the voice's first note names its own instrument, so
    nothing after the idle stretch inherits the quiet one.

    Left alone: a first note that names no instrument (it would inherit the
    quiet one), a row 0 that already names an instrument, an instrument 1
    without vibrato, a song with no vibrato-free instrument. Returns whether
    it wrote.
    """
    if first_note_instrument is None or pattern[1] != 0:
        return False
    if not vibrato.get(1):
        return False
    quiet = next((n for n in sorted(vibrato) if n != 1 and not vibrato[n]),
                 None)
    if quiet is None:
        return False
    pattern[1] = quiet
    return True


def apply_pre_note_waves(patterns: List[List[int]], tracks: List[List[int]],
                         waves: Tuple[Optional[int], ...], max_patterns: int,
                         log=None, vibrato: Optional[dict] = None
                         ) -> Tuple[List[List[int]], List[List[int]], int]:
    """`CMD_SETWAVE wave` on the first free row of each voice's entry pattern
    that precedes its first note, for the FIRST LAP of subtune 0
    (`tracks[0:3]`).

    **First lap only, because the original's loop does not re-latch.** On the
    second lap the original's voice holds whatever instrument it ended the
    first on, not the one its init wrote, so a latch that ran again at the
    loop would overwrite a waveform the original is still holding (Last_V8
    voice 0: a `$16` ring-and-sync note spans the restart; a latch in the
    entry pattern turned 286 frames of it into `$40`, ctrl 100% -> 76%). A
    restart to position 0 -- every one of the twelve -- is therefore handled
    by moving the plain entry pattern to the END of the orderlist:

        prefix E X1 .. Xn  FF 0   ->   prefix L X1 .. Xn prefix E  FF |prefix|+1

    `L` is a copy of `E` that carries the latch, played once; the loop then
    runs X1 .. Xn prefix E, which is the original's lap exactly. A restart
    past the entry (a tune that ended and parks) never re-enters it, so the
    latch goes into the entry pattern itself, copied first where another
    position plays the same pattern. A restart INTO the prefix is left alone.

    Skips a voice whose first row is a note (nothing precedes it), whose entry
    pattern has no free command cell before its first note, or whose entry is
    repeated with a note in it. A copy past `max_patterns`, or an orderlist
    that would pass Goattracker's length, is dropped, not made wrong. Returns
    (patterns, tracks, written) -- both lists are fresh copies.
    """
    patterns = [list(p) for p in patterns]
    tracks = [list(t) for t in tracks]
    written = 0
    plays: dict = {}
    for track in tracks:
        operand = False
        for b in track:
            if operand:
                operand = False
            elif b == _RESTART:
                operand = True
            elif b < _COMMAND_FLOOR:
                plays[b] = plays.get(b, 0) + 1
    for v in range(min(3, len(tracks))):
        wave = waves[v] if v < len(waves) else None
        if wave is None:
            continue
        track = tracks[v]
        at = _entry(track)
        if (at is None or len(track) < 3 or track[-2] != _RESTART
                or track[at] >= len(patterns)):
            continue
        p = track[at]
        restart = track[-1]
        note = _first_note_row(patterns[p])
        repeated = at > 0 and _COMMAND_FLOOR <= track[at - 1] < _REPEAT_END
        if note == 0:
            continue
        if repeated and note is not None:
            if log:
                log(f"Pre-note wave...........: voice {v} entry pattern "
                    f"{p:02X} repeats with a note in it; left alone")
            continue
        limit = note if note is not None else len(patterns[p]) // 4
        row = next((r for r in range(limit)
                    if patterns[p][4 * r + 2] == 0
                    and patterns[p][4 * r + 3] == 0), None)
        if row is None:
            if log:
                log(f"Pre-note wave...........: voice {v} has no free "
                    f"command cell before its first note; ${wave:02X} not "
                    f"written")
            continue
        if restart != 0 and restart <= at:
            if log:
                log(f"Pre-note wave...........: voice {v} restarts into its "
                    f"entry prefix; ${wave:02X} not written")
            continue
        first_lap = restart == 0
        shared = plays.get(p, 0) > 1
        if first_lap or shared:
            if len(patterns) >= max_patterns:
                if log:
                    log(f"Pre-note wave...........: voice {v} needs a "
                        f"pattern copy and the {max_patterns}-pattern "
                        f"ceiling is reached; ${wave:02X} not written")
                continue
        if first_lap and len(track) + at + 1 > _MAX_ORDERLIST:
            if log:
                log(f"Pre-note wave...........: voice {v} orderlist is too "
                    f"long to carry the first-lap copy; ${wave:02X} not "
                    f"written")
            continue
        if first_lap or shared:
            patterns.append(list(patterns[p]))
            copy = len(patterns) - 1
        else:
            copy = p
        patterns[copy][4 * row + 2] = CMD_SETWAVE
        patterns[copy][4 * row + 3] = wave
        if vibrato and quiet_idle_vibrato(
                patterns[copy], _first_note_instrument(patterns, track, at),
                vibrato) and log:
            log(f"Pre-note wave...........: voice {v} idles on a "
                f"vibrato-free instrument until its first note")
        if first_lap:
            prefix = track[:at]
            tracks[v] = (prefix + [copy] + track[at + 1:-2] + prefix + [p]
                         + [_RESTART, len(prefix) + 1])
            where = "first lap"
        else:
            if shared:
                plays[p] -= 1
                plays[copy] = 1
                track[at] = copy
            where = "entry"
        written += 1
        if log:
            log(f"Pre-note wave...........: voice {v} latches ${wave:02X} "
                f"on row {row} of pattern {copy:02X} ({where})")
    return patterns, tracks, written
