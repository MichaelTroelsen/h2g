"""The bit-$80 drum's tick on the VOICE the player writes it to.

Thundercats' sfx block (`$F17E-$F1AE`) stores to the voice-3 registers by
absolute address, whichever voice's record carries bit $80 (`detect`'s
`sfx_voice`; `SFX_DRUM_SHAPE` checks the two stores name one voice). A record
with the bit that voice 1 plays therefore ticks VOICE 3, and voice 1 keeps its
own waveform:

    frames 8193-8213 of Thundercats, voice 1 = record `$0E` (effect `$A0`,
    the 127-row note), voice 3 resting after a bit-6 rest

                       voice 1 (wave)       voice 3 (wave)
        original       41 41 41 41 41 41    08 08 08 08 08 81 08 ...  (every 6)
        ours before    41 81 41 41 41 41    40 40 40 40 40 40 40 ...

`_sfx_drum_entries` writes the hit into the record's own wavetable, which can
only reach the voice that plays the record. For a record the sfx voice plays
(Bangkok, Nineteen's record 1, IK+ ...) that is the right voice; for
Thundercats' `$0E`, played on voice 1 ALONE (16 rows, none on voice 3), it is
the wrong one on both ends: 134 frames of voice 1 read `81` where the original
holds `41`, and 112 frames of voice 3 read the parked `40` where the original
has the tick.

Two halves, both narrow, both keyed on the same reading:

* `stray_drum_record` -- the record carries no hit in its own wavetable
  (`wavetable._wavetable_entries`' `sfx_stray`), so the played voice keeps the
  waveform the player leaves on it;
* `sfx_tick_voice_plan` -- the sfx voice's REST rows (a bit-6 rest is the
  fetch that zeroes the drum's counter) that fall inside a stretch the stray
  record is live on its voice become a note on a click clone like
  `sfx_rest_click`'s (AD/SR `$00`, firstwave `$08`, the drum's lattice with the
  held frames parked, so each hit is a gate edge under `$0000`) whose hit is on
  the rest's OWN first frame -- see `tick_entries` for why that is one frame
  earlier than `sfx_rest_click`'s.

A record the sfx voice plays too (any row of it) keeps the old reading: a
wavetable is per instrument and cannot tick one voice for one play and
another voice for the next.

Where no rest of the sfx voice is inside the stretch (it plays notes under it)
nothing can be placed without silencing a note, and the plan changes nothing;
the record is still written without its hit in that case, because the hit it
would write sounds on the wrong voice either way.

Testbit-kind rests only (`det.rest_silence_kind == "testbit"` with the envelope
zeroed in the rest branch), the one kind read so far for this shape.
"""
from __future__ import annotations

from typing import Dict, List, Optional, Tuple

from .constants import (CMD_SETAD, CMD_SETSR, GT_FIRST_NOTE, GT_KEYOFF,
                        GT_LAST_NOTE, GT_MAX_TABLELEN, GT_REST, GT_WAVE_JUMP,
                        TEMPO_DUTY_MAX_CLONE)
from .rest_park import CMD_SETWAVE, REST_SILENT_WAVE
from .sfx_rest_click import (GT_ENDPATT, INSTR_BYTES, _carries_hit,
                             _effect_byte, entry_notes,
                             sfx_rest_click_entries)
from .primitives import _sfx_note_byte

# orderlist bytes (songview's constants, gcommon.h)
_ORDER_RESTART = 0xFF
_TRANSPOSE_LO = 0xE0
_REPEAT_LO = 0xD0
# The pitch a click row names where no note precedes it anywhere: the row's
# frames after the hit are parked under the test bit, so it only has to be
# a legal note.
FALLBACK_NOTE = GT_FIRST_NOTE + 36


def stray_drum_record(instr_voices: Optional[dict], instr: int,
                      sfx_voice: int) -> bool:
    """Whether GT instrument `instr` is played, and never on the sfx voice.

    `instr_voices` is `tracks.instrument_voices`: {instrument: {voice: rows}}.
    One row on the sfx voice is enough to keep the record's own hit, because
    the wavetable is per instrument."""
    per = (instr_voices or {}).get(instr)
    return bool(per) and sfx_voice not in per and sum(per.values()) > 0


def _rows(pat: List[int]) -> int:
    """Content rows of a pattern: those before its terminator."""
    n = len(pat) // 4
    for r in range(n):
        if pat[4 * r] == GT_ENDPATT:
            return r
    return n


def plays(track: List[int], patterns: List[List[int]]
          ) -> Tuple[List[tuple], int]:
    """([(entry index, play number, pattern, first row, rows)], total rows):
    one lap of an orderlist, repeats honoured, transposes skipped."""
    out: List[tuple] = []
    row, repeat = 0, 1
    for ei, b in enumerate(track):
        if b == _ORDER_RESTART:
            break
        if b >= _TRANSPOSE_LO:
            continue
        if b >= _REPEAT_LO:
            repeat = b - _REPEAT_LO + 1
            continue
        if b >= len(patterns):
            repeat = 1
            continue
        n = _rows(patterns[b])
        for k in range(repeat):
            out.append((ei, k, b, row, n))
            row += n
        repeat = 1
    return out, row


def live_spans(track: List[int], patterns: List[List[int]], stray: set
               ) -> List[Tuple[int, int]]:
    """[(first row, end row)) the voice spends on a stray record, from the
    note that names it to the next note that names another instrument.
    Rests keep the record live (the player's effect block reads the record
    the voice holds, a rest does not change it)."""
    spans: List[Tuple[int, int]] = []
    ps, total = plays(track, patterns)
    live: Optional[int] = None
    open_at: Optional[int] = None
    for _ei, _k, pn, first, n in ps:
        pat = patterns[pn]
        for r in range(n):
            note, ins = pat[4 * r], pat[4 * r + 1]
            if not GT_FIRST_NOTE <= note <= GT_LAST_NOTE:
                continue
            if ins:
                live = ins
            if live in stray:
                if open_at is None:
                    open_at = first + r
            elif open_at is not None:
                spans.append((open_at, first + r))
                open_at = None
    if open_at is not None:
        spans.append((open_at, total))
    return spans


def tick_rows(track: List[int], patterns: List[List[int]],
              spans: List[Tuple[int, int]]) -> Dict[int, set]:
    """{entry index: {row}} of the sfx voice's rest rows inside `spans`.

    An entry played more than once (a repeat) is kept only where every play
    has the same rows inside: the copy replaces the entry's pattern for all of
    its plays. Where the stretch opens ON a rest the player's first hit waits
    a whole period (the note-start frame does not run the effect block;
    Thundercats: stray note and voice-3 rest both at frame 8193, first tick
    8199), so that rest's first hit is one this lattice adds -- one tick in a
    stretch of 800 frames, left in because the orderlist's repeat cannot give
    one play its own pattern without changing the track's length."""
    ps, _total = plays(track, patterns)
    found: Dict[int, List[set]] = {}
    for ei, _k, pn, first, n in ps:
        pat = patterns[pn]
        rows = set()
        for r in range(n):
            if pat[4 * r] == GT_KEYOFF and not pat[4 * r + 1]:
                if any(a <= first + r < b for a, b in spans):
                    rows.add(r)
        found.setdefault(ei, []).append(rows)
    return {ei: got[0] for ei, got in found.items()
            if got[0] and all(g == got[0] for g in got)}


def click_pattern(pat: List[int], rows: set, clone: int,
                  carried: Optional[int]) -> List[int]:
    """A copy of `pat` with each of `rows` (rest rows) spelt as a note on the
    click clone; the rest's own `SETAD/SETSR $00` and parked-wave commands go
    (the clone's `$0000` is that state)."""
    copy = list(pat)
    last: Optional[int] = carried
    n = _rows(pat)
    r = 0
    while r < n:
        note = copy[4 * r]
        if GT_FIRST_NOTE <= note <= GT_LAST_NOTE:
            last = note
        if r in rows:
            copy[4 * r] = last if last is not None else FALLBACK_NOTE
            copy[4 * r + 1] = clone
            h = r + 1
            while h < n and copy[4 * h] == GT_REST and not copy[4 * h + 1]:
                h += 1
            for k in range(r, h):
                cmd, data = copy[4 * k + 2], copy[4 * k + 3]
                if ((cmd in (CMD_SETSR, CMD_SETAD) and data == 0)
                        or (cmd == CMD_SETWAVE and data == REST_SILENT_WAVE)):
                    copy[4 * k + 2] = copy[4 * k + 3] = 0
            last = copy[4 * r]
            r = h
        else:
            r += 1
    return copy


def tick_entries(pitch_hi: int, period: int, multiplier: int
                 ) -> Optional[tuple]:
    """(left, right, loop): the click program with the hit ON the note's own
    first frame and every `period` frames after.

    The tick a stray record fires lands on the frame the sfx voice's own rest
    is fetched: that voice's iteration of the play routine zeroes its counter
    and steps it to 1 before the stray voice's iteration reads it, so the hit
    is on frame 0 -- where `sfx_rest_click`'s (the sfx voice's own record,
    whose check precedes the step) is on frame 1. Thundercats frames
    8265-8304: hits at 8265/8271/8277/8284/8290, `sfx_rest_click`'s lattice
    one frame late on every one of them."""
    prog = sfx_rest_click_entries(pitch_hi, period, multiplier)
    if prog is None:
        return None
    left, right, loop = prog
    return left[loop:], right[loop:], 0


def sfx_tick_voice_plan(det, tracks: List[List[int]],
                        patterns: List[List[int]], out: bytearray,
                        instr_at: int, written: int,
                        wave_entries: List[Tuple[int, int]],
                        multiplier: int, log=None):
    """(tracks, patterns, wave_entries, written): the sfx voice's rests inside
    a stray record's stretch spelt as clicks. Unchanged where nothing places."""
    unplaced = (tracks, patterns, wave_entries, written)
    if not (det.effect_bit80 == "sfx" and det.sfx_pitch > 0
            and det.sfx_period > 0 and det.sfx_voice in (0, 1, 2)
            and det.rest_silence_kind == "testbit"
            and det.rest_silence_envelope):
        return unplaced
    from ..tracks import instrument_voices
    instr_voices = instrument_voices(tracks, patterns)
    note = _sfx_note_byte(det.sfx_pitch)
    stray = set()
    for g in range(1, written + 1):
        eff = _effect_byte(out, instr_at, g)
        if eff is None or not eff & 0x80:
            continue
        if not stray_drum_record(instr_voices, g, det.sfx_voice):
            continue
        # Only a record whose own block really has no hit: the wavetable's
        # `sfx_stray` and this agree, or the tick would sound twice.
        if _carries_hit(wave_entries,
                        out[instr_at + 1 + (g - 1) * INSTR_BYTES + 2], note):
            continue
        stray.add(g)
    if not stray:
        return unplaced
    prog = tick_entries(det.sfx_pitch, det.sfx_period, multiplier)
    if prog is None:
        return unplaced
    left, right, loop = prog
    from .note_passes import clone_number_ceiling
    clone = written + 1
    if clone > min(TEMPO_DUTY_MAX_CLONE,
                   clone_number_ceiling(patterns, written)):
        return unplaced
    if len(wave_entries) + 1 + len(left) > GT_MAX_TABLELEN:
        if log:
            log("Sfx tick voice..........: no room in the wavetable")
        return unplaced
    new_patterns = list(patterns)
    new_tracks = [list(t) for t in tracks]
    carried_by_pattern = entry_notes(tracks, patterns)
    sv = det.sfx_voice
    by_key: Dict[tuple, int] = {}
    placed = 0
    for st in range(len(tracks) // 3):
        base = 3 * st
        spans: List[Tuple[int, int]] = []
        for v in range(3):
            if v != sv:
                spans += live_spans(tracks[base + v], patterns, stray)
        if not spans:
            continue
        for ei, rows in tick_rows(tracks[base + sv], patterns, spans).items():
            pn = tracks[base + sv][ei]
            got = carried_by_pattern.get(pn, ())
            carried = next(iter(got)) if len(got) == 1 else None
            key = (pn, frozenset(rows), carried)
            if key not in by_key:
                if len(new_patterns) >= 208:
                    continue
                new_patterns.append(click_pattern(patterns[pn], rows, clone,
                                                  carried))
                by_key[key] = len(new_patterns) - 1
            new_tracks[base + sv][ei] = by_key[key]
            placed += len(rows)
    if not placed:
        return unplaced
    # The click clone: a record of the stray drum's own bytes with the click
    # program, as `sfx_rest_click_plan` cuts its clones (and no vibrato: the
    # stray record's own would move the parked voice's frequency).
    src = min(stray)
    start = len(wave_entries) + 1
    rec = bytearray(out[instr_at + 1 + (src - 1) * INSTR_BYTES:
                        instr_at + 1 + src * INSTR_BYTES])
    rec[0] = 0x00
    rec[1] = 0x00
    rec[2] = start & 0xFF
    rec[3] = 0x00
    rec[4] = 0x00
    rec[5] = 0x00
    rec[6] = 0x00
    rec[8] = REST_SILENT_WAVE
    out += rec
    out[instr_at] = written + 1
    if log:
        log(f"Sfx tick voice..........: {placed} rest(s) of voice "
            f"{sv + 1} sound the drum a record on another voice fires there")
    return (new_tracks, new_patterns,
            wave_entries + list(zip(left, right))
            + [(GT_WAVE_JUMP, start + loop)], written + 1)
