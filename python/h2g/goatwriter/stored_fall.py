"""Bit $01's stored-waveform fall (detect._find_stored_wave_fall) beside bit $02.

Chicken Song `$133B` is not a drum: from call `first_call` of a note it writes
the voice's frequency HIGH byte one lower each call (`$0100`) down to 1, with
the waveform the record stored on `$D404` (`detect.STORED_WAVE_FALL_SHAPE`).
Record 3 (`00 08 41 0A 07 00 00 03`) sets it beside bit $02's noise
alternation, so a 12-call A#3 reads, from the original's siddump,

    call   0     1     2     3     4     5     6     7     8     9     10   11
    freq   0F82  .     .     .     0E82  0D82  0C82  0B82  0A82  0982  0882 0782
    wave   41    81    41    81    41    81    41    81    41    81    40   80

and shipped `wave_alternate` leaves the frequency at `0F82` from call 4 on.

**Why it is carried on the alternation's own rows.** A wavetable row is one
play call and a command row (`F2`) writes no waveform, so an exact portamento
(scratch variant V2: `F2 $0100` on calls 4-11) costs the alternation on every
fall call and measured `aud` .9404 -> .9402 and `wave` .965 -> .950, against
.9424 / .966 for this. A waveform row's right side can carry a note, so each
call keeps its waveform and takes the nearest of Goattracker's 96 notes to
the frequency the player writes there (16-47 cents off, against the 1-13
semitones of holding the pitch).

The offsets are RELATIVE to the played note (`$80 - n` for n semitones down,
readme p.794) and computed for the record's modal played pitch
(`played_note_weights`, which already carries the orderlist transposes), so
the program is the instrument's and not the note's: a play at another pitch
falls the same semitones. Declined, leaving the plain alternation:

* the multiplier is not 1 (a call is not a frame), or `pitches` / the typical
  note length is unknown (the probing passes carry neither);
* the record sets a bit besides $01 and $02, or has a vibrato byte -- a later
  block rewrites the frequency every call (`$1392` bit $04, `$1222` vibrato);
* the modal pitch is under 3/4 of the record's plays;
* the player's table does not name the pitch, or its high byte is 1 or less.
"""
from __future__ import annotations

import math
from typing import Dict, Optional

from ..detect import Detection
from ..sidfile import SidFile, find_freq_table
from .skydive import GT_FREQ_TABLE

# The decision rule: the modal pitch must carry at least this share of plays.
STORED_FALL_MODAL_SHARE = 0.75
# Readme p.794: `$60-$7F` is a negative relative note, so 32 semitones is the
# most a right side can lower the played note.
STORED_FALL_MAX_DOWN = 32


def stored_fall_offsets(sid: SidFile, det: Detection, i: int, effect: int,
                        pitches: Optional[dict], calls: Optional[int],
                        multiplier: int) -> Optional[Dict[int, int]]:
    """`{call: wavetable right side}` for record `i`'s fall, or None.

    `calls` is the record's typical note length in play calls. The fall
    writes on calls `first_call .. calls - 1`; the first write is the note's
    own high byte, so call `first_call + m` sounds the pitch `m` bytes down.
    """
    fall = det.stored_wave_fall
    if fall is None or multiplier != 1 or not pitches or not calls:
        return None
    if effect & ~0x03 or not effect & 0x01:
        return None
    base = det.instr_start + i * det.instr_stride
    vib = [det.vibrato_offset]
    if det.table_vibrato is not None:
        vib.append(det.table_vibrato.offset)
    if any(v is not None and sid.data[base + v] for v in vib):
        return None
    total = sum(pitches.values())
    note = max(pitches, key=lambda n: pitches[n])
    if pitches[note] < STORED_FALL_MODAL_SHARE * total:
        return None
    table = find_freq_table(sid)
    if table is None:
        return None
    index = note - table.shift
    at = sid.to_offset(table.addr) + 2 * index
    if not 0 <= index < table.length or at + 1 >= len(sid.data):
        return None
    freq = sid.data[at] | sid.data[at + 1] << 8
    if not 0 <= note < len(GT_FREQ_TABLE) - 1:
        return None
    steps = min((freq >> 8) - 1, calls - 1 - fall.first_call)
    out: Dict[int, int] = {}
    for m in range(1, steps + 1):
        target = freq - 0x100 * m
        near = min(range(len(GT_FREQ_TABLE) - 1),
                   key=lambda n: abs(math.log(GT_FREQ_TABLE[n] / target)))
        down = note - near
        if down > STORED_FALL_MAX_DOWN:
            break
        out[fall.first_call + m] = (0x80 - down) & 0x7F if down else 0x00
    return out or None
