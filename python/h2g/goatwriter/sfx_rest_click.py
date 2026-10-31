"""The bit-$80 drum's hit on a REST: a one-frame click Goattracker's KEYOFF masks.

Thundercats' player (`$F17E-$F1AE`, the sfx block every `effect_bit80 ==
"sfx"` player carries) fires its hit by writing the voice-3 registers
absolutely and UNMASKED:

    F17E  LDA $F513 / BPL out        ; the voice's record +7, bit 7
    F183  LDA $F5AD / CMP #$01 / BEQ fire   ; voice 3's counter == 1
    F19A  fire: LDA #$48 / STA $D40F / LDA #$81 / STA $D412

and the counter is zeroed by EVERY pattern fetch, a rest included
(`$EDCC-$EDD1`, ahead of the rest's `BIT / BVS` at `$EDF1`). A bit-6 rest
(`$EE38`) then masks the gate, zeroes AD and SR and parks `$08` -- but the hit
does not go through the mask. So one frame into a rest of the drum record the
block writes `$81` over the parked `$08`: the gate RISES, under ADSR `$0000`,
and the next frame's `$08` drops it. siddump counts a gate edge, named C#6
(`$48xx`); the SID sounds a ~8 ms noise click.

    frame  original voice 3               ours (KEYOFF + SETSR/SETAD, lag 5)
    1068   ....  ... ..  08 0000          ....  ... ..  .. ....
    1069   482C  C#6 C9  81 ....          ....  ... ..  .. ....
    1070   052C  ... ..  08 ....          49C5 (C#6 C9) 80 0000

Ours runs the same drum loop across the rest, but a KEYOFF sets the channel's
gate mask to `$FE` (gplay.c:921-922, player.s `mt_loadregswaveonly`), so the
hit is written `$80`: no gate edge, no click, no note. On Thundercats that is
60 of the original's 916 voice-3 attacks in 180 s, every one between two
bass notes, which is why it costs `melody` (collapsed: each missing C#6 also
merges the two D#2s around it) far more than `seq`.

**The repair spells such a rest as a NOTE on a clone of the drum record** that
the rest itself would leave: AD and SR `$00`, firstwave `$08`, and a wave
program on the drum's own lattice (`_sfx_drum_entries`) with the held frames
at `$08` instead of the record's waveform -- so the hit lands on the rest's
second frame and every `period` after, gate rising each time, exactly where
the counter puts it. The note is the pattern's previous note, so the `$08`
frames restore the stored frequency the original's next frame writes. The
note after the rest names the drum record again (an explicit column; a
note-start reloads everything from it, gplay.c:347-399).

Applied only where it can be read and spelled:

* the player is the testbit-rest family that zeroes the envelope pair in the
  rest branch (`rest_silence_kind == "testbit"`, `rest_silence_envelope`),
  and the conversion already zeroes it there (a `CMD_SETSR $00` on the rest
  -- `--rest-envelope-silence`), so the clone's `$0000` is the rest's own
  state rather than a new write;
* the rest's live instrument is known, carries bit `$80`, carries the hit in
  its wavetable, and plays on the sfx voice ONLY (`tracks.instrument_voices`)
  -- the block writes voice 3 whatever voice runs it, so a bit-`$80` record
  on another voice clicks voice 3, not its own, and is left alone;
* the rest is followed, inside its pattern, by a plain note (not a
  toneportamento, which would keep the clone's program running).

**The envelope kind (`rest_silence_kind == "envelope"`, Mega_Apocalypse).** The
same hit, a different lattice. Mega's rest branch (`$4B91`) zeroes AD and SR,
parks the waveform `$00` (the `LDA #$00` is still in A at `$4BF7 STA $C6,X`) and
jumps to the register writes at `$4E63`, so the sfx block at `$4E43-$4E61` is
skipped on the fetch frame -- and the counter `$BE` is NOT zeroed there (only
the note path does, `$4BDB`); it just keeps stepping:

    4E47  LDA $BE / CMP #$01 / BEQ fire      ; fire: LDA #$48 / STA $D40F
    4E4D  CMP #$06 / BCC out                 ;       LDA #$81 / STA $D412
    4E51  LDA #$00 / STA $BE / BEQ out       ; wrap at 6 (skipped on the fetch)

so the first hit of a rest lands where the NOTE's lattice puts it, not one
frame in. With this player's 3-frame tick (`$4F61` = 2: `DEC $DF` / reload) a
note of an even number of rows is a whole number of periods, the wrap the
fetch frame skips is taken one frame later, and the hit is on the rest's THIRD
frame (delta 2 on 33 of 33 rests with a hit in 180 s: 93 gate rises from `$00`
under `$0000`, one per original miss; phase.py in
C:/t/mega-apocalypse-rest-click). A rest after an odd number of rows would
land on the fifth; none is in the file and none is spelt. So for this kind:

* its program opens with one more held frame (`ENVELOPE_LEAD`), and its held
  frames write `$00` (`ENVELOPE_HELD`, `$E0`) where the testbit kind's write
  `$08`: the original holds `$00` across the rest, and `$08`'s test bit is a
  `ctrl` disagreement on every held frame (130 frames on voice 3, ctrl 82.7% ->
  81.9%, finding.md). The clone's first frame (record +8) writes `$40`
  (`ENVELOPE_FIRSTWAVE`): at the 26 clicked rests the harness aligns it with
  the original's last frame of the note, `$40` on 26 of 26, where `$08` was a
  test bit against it and `$09` a gate the original does not have;
* the rest need not already carry a `CMD_SETSR $00` (no preset sets
  `--rest-envelope-silence` for Mega) because the clone's `$0000` IS the
  envelope the player writes at the rest;
* only a rest an EVEN number of rows after the pattern's last note qualifies
  (`ENVELOPE_ROW_FRAMES`, the tick this reading was taken at).

**Room.** The program is six rows and Mega_Apocalypse's wavetable holds 254 of
255. Six of those rows are `$FF 00` stops that NOTHING reaches -- the fifth row
of a five-row instrument block whose program already stopped at the fourth (rows
28, 64, 69, 78, 92, 97) -- so, where the program does not fit, the rows no record,
`CMD_SETWAVEPTR` or jump reaches are dropped (`dead_blocks.reached_rows`, the
same walk) and every row number is moved through the map: the records' starts,
the patterns' `CMD_SETWAVEPTR` operands and the table's own jumps. Only then,
and only if that is enough: a conversion that already has the room, or cannot
make it, is byte for byte what it was. The vibrato tables are untouched. Only
the envelope kind asks: the testbit kind's full table (Thundercats with its dead
blocks kept, `tests/test_rest_program_stop.py`) keeps its "no room" answer.

Inert without `--sfx-drum` (the caller's gate). A conversion where no rest
qualifies comes back unchanged, byte for byte.
"""
from __future__ import annotations

from typing import Dict, List, Optional, Tuple

from .constants import (CMD_SETAD, CMD_SETSR, CMD_TONEPORTA, GT_FIRST_NOTE,
                        GT_KEYOFF, GT_LAST_NOTE, GT_MAX_TABLELEN, GT_REST,
                        GT_WAVE_JUMP, TEMPO_DUTY_MAX_CLONE)
from .dead_blocks import (WAVE_SETPTR, reached_rows, remap_setwaveptr,
                          setwaveptr_operands)
from .drums import _sfx_drum_entries
from .primitives import _sfx_note_byte, _wave_byte
from .rest_park import CMD_SETWAVE, REST_SILENT_WAVE, WAVE_SILENT_BASE

# gcommon.h ENDPATT: a pattern's terminator, in the note column.
GT_ENDPATT = 0xFF
# One instrument record in the .sng (`_write_instruments`).
INSTR_BYTES = 25
# The envelope kind's rest parks `$00` (its `LDA #$00` is still in A), which
# `_wave_byte` cannot write -- it emits `$18`, and with that park the harness's
# `onset` column falls 100% -> 90% (the clone opens on a wave the original never
# plays). `$08` keeps it at 100% (measured, ab_novib_park08.txt).
ENVELOPE_PARK_WAVE = REST_SILENT_WAVE
# The held frames of the envelope kind's program: `$E0`, which writes `$00`
# (gplay.c:527; the packed player keeps it as `$10` in a song with a wavetable
# delay, which this program's own `03 80` row makes of any file that ships it).
# `$E8` writes `$08`, and its test bit is a `ctrl` disagreement on every held
# frame of a rest the original holds at `$00` (130 frames on Mega_Apocalypse
# voice 3, ctrl 82.7% -> 81.9%; finding.md).
ENVELOPE_HELD = WAVE_SILENT_BASE
# The waveform the clone's first frame writes (record +8): pulse, gate off,
# silent under the rest's ADSR $0000. Measured on Mega_Apocalypse, -t 180,
# against build/fidelity.json at 8a35b59 (ctrl, gate, wave): $08 ctrl -0.17 pp,
# $09 gate -0.04 pp, $10/$80 wave +0.38 pp, $40 ctrl 0, gate +0.17 pp, wave +0.49 pp.
ENVELOPE_FIRSTWAVE = 0x40
# Frames of the player's tick on the one envelope-kind file read so far
# (Mega_Apocalypse: `$4F61` = 2 -> a 3-call gate). A rest an even number of
# rows after the note is a whole number of 6-frame periods only at this tick.
ENVELOPE_ROW_FRAMES = 3
# Held frames before the first hit: the hit is on frame 1 + lead.
ENVELOPE_LEAD = 1


def sfx_rest_click_entries(pitch_hi: int, period: int, multiplier: int = 1,
                           parked: int = REST_SILENT_WAVE,
                           lead: int = 0,
                           held: Optional[int] = None) -> Optional[tuple]:
    """(left, right, loop): the drum's own lattice (`_sfx_drum_entries`) with
    every held frame at the parked waveform -- gate OFF -- instead of the
    record's waveform with the gate on. The hit (`$81`) is unchanged, so each
    one is a gate edge. `lead` more held frames open the program, so the first
    hit is on frame `1 + lead` (the envelope kind's counter is not zeroed)."""
    hit = _sfx_drum_entries(parked, pitch_hi, period, multiplier)
    if hit is None:
        return None
    left, right, loop = hit
    held_on = _wave_byte(parked | 0x01)
    held_off = _wave_byte(parked) if held is None else held
    left = [held_off if b == held_on else b for b in left]
    n = lead * max(1, multiplier)
    return [held_off] * n + left, [0x00] * n + list(right), loop + n


def _effect_byte(out, instr_at: int, g: int) -> Optional[int]:
    """The record's +7 from the instrument's name `NN:b5-b6-b7`."""
    at = instr_at + 1 + (g - 1) * INSTR_BYTES
    raw = bytes(out[at + 9:at + INSTR_BYTES]).split(b"\x00")[0]
    fields = raw.decode("latin-1", "replace").strip().partition(":")[2]
    parts = fields.split("-")
    if len(parts) != 3:
        return None
    try:
        return int(parts[2], 16)
    except ValueError:
        return None


def _carries_hit(wave_entries: List[Tuple[int, int]], start: int,
                 note: int) -> bool:
    """Whether the block at 1-based `start` writes the drum's hit before its
    jump -- i.e. the record was laid out as the sfx drum, not another shape."""
    if not 0 < start <= len(wave_entries):
        return False
    for left, right in wave_entries[start - 1:]:
        if left == GT_WAVE_JUMP:
            return False
        if left == 0x81 and right == note:
            return True
    return False


def click_rests(patterns: List[List[int]], entry: Dict[int, set],
                clone_of: Dict[int, int], envelope_kind: bool = False
                ) -> Tuple[List[List[int]], int, set]:
    """(patterns, rests rewritten, drum instruments used). Changed patterns
    are COPIES; see the module docstring for what qualifies. `envelope_kind`
    drops the `CMD_SETSR $00` requirement and takes only a rest an even number
    of rows after the pattern's last note."""
    out: List[List[int]] = []
    placed = 0
    used: set = set()
    for number, pat in enumerate(patterns):
        cands = set(entry.get(number, ()))
        rows = len(pat) // 4
        last_note = None
        last_row = -1
        copy: Optional[List[int]] = None
        r = 0
        while r < rows:
            note, ins = pat[4 * r], pat[4 * r + 1]
            if note == GT_ENDPATT:
                break
            if ins:
                cands = {ins}
            if GT_FIRST_NOTE <= note <= GT_LAST_NOTE:
                last_note = note
                last_row = r
            drum = next(iter(cands)) if len(cands) == 1 else None
            if (note != GT_KEYOFF or ins or drum not in clone_of
                    or last_note is None):
                r += 1
                continue
            h = r + 1
            while h < rows and pat[4 * h] == GT_REST and not pat[4 * h + 1]:
                h += 1
            nxt = pat[4 * h:4 * h + 4] if h < rows else []
            envelope = any(pat[4 * k + 2] == CMD_SETSR and pat[4 * k + 3] == 0
                           for k in (r, r + 1) if k < h)
            if envelope_kind:
                envelope = (last_row >= 0 and
                            (r - last_row) * ENVELOPE_ROW_FRAMES % 6 == 0)
            if (len(nxt) < 4 or not GT_FIRST_NOTE <= nxt[0] <= GT_LAST_NOTE
                    or nxt[2] == CMD_TONEPORTA or not envelope):
                r += 1
                continue
            if copy is None:
                copy = list(pat)
            copy[4 * r] = last_note
            copy[4 * r + 1] = clone_of[drum]
            for k in range(r, h):
                cmd, data = copy[4 * k + 2], copy[4 * k + 3]
                if ((cmd in (CMD_SETSR, CMD_SETAD) and data == 0)
                        or (cmd == CMD_SETWAVE and data == REST_SILENT_WAVE)):
                    copy[4 * k + 2] = copy[4 * k + 3] = 0
            if not nxt[1]:
                copy[4 * h + 1] = drum
            placed += 1
            used.add(drum)
            r = h
        out.append(pat if copy is None else copy)
    return out, placed, used


def _starts_of(out: bytearray, instr_at: int, written: int) -> List[int]:
    """The wavetable pointer of records 1..written."""
    return [out[instr_at + 1 + (g - 1) * INSTR_BYTES + 2]
            for g in range(1, written + 1)]


def drop_unreached_rows(wave_entries: List[Tuple[int, int]],
                        patterns: List[List[int]], starts: List[int]
                        ) -> Optional[Tuple[List[Tuple[int, int]],
                                            List[List[int]], Dict[int, int]]]:
    """(entries, patterns, row_map): the table without the rows nothing
    reaches, the patterns' `CMD_SETWAVEPTR` operands moved through `row_map`
    (copies; `patterns` is untouched), or None where every row is reached or a
    kept entry names a row the table does not have."""
    size = len(wave_entries)
    roots = {s for s in starts if s} | set(setwaveptr_operands(patterns))
    reached = reached_rows(wave_entries, roots)
    gone = {r for r in range(1, size + 1) if r not in reached}
    if not gone:
        return None
    row_map: Dict[int, int] = {}
    kept: List[Tuple[int, int]] = []
    for row in range(1, size + 1):
        if row not in gone:
            kept.append(wave_entries[row - 1])
            row_map[row] = len(kept)
    entries: List[Tuple[int, int]] = []
    for left, right in kept:
        if left in (GT_WAVE_JUMP, WAVE_SETPTR) and right:
            if right not in row_map:
                return None
            right = row_map[right]
        entries.append((left, right))
    moved = [list(p) for p in patterns]
    try:
        remap_setwaveptr(moved, row_map)
    except KeyError:
        return None
    return entries, moved, row_map


def sfx_rest_click_plan(det, tracks: List[List[int]],
                        patterns: List[List[int]], out: bytearray,
                        instr_at: int, written: int,
                        wave_entries: List[Tuple[int, int]],
                        multiplier: int, log=None):
    """(patterns, wave_entries, written): the qualifying rests spelt as click
    notes, the click program appended to the wavetable and one clone per drum
    instrument appended to `out` after record `written`. Unchanged where
    nothing qualifies."""
    if not (det.effect_bit80 == "sfx" and det.sfx_pitch > 0
            and det.sfx_period > 0 and det.sfx_voice in (0, 1, 2)
            and det.rest_silence_kind in ("testbit", "envelope")
            and det.rest_silence_envelope):
        return patterns, wave_entries, written
    envelope_kind = det.rest_silence_kind == "envelope"
    from ..tracks import instrument_voices
    from .note_passes import _entry_instruments, clone_number_ceiling
    note = _sfx_note_byte(det.sfx_pitch)
    voices = instrument_voices(tracks, patterns)
    drums = []
    for g in range(1, written + 1):
        eff = _effect_byte(out, instr_at, g)
        if eff is None or not eff & 0x80:
            continue
        if set(voices.get(g, {})) != {det.sfx_voice}:
            continue
        if not _carries_hit(wave_entries,
                            out[instr_at + 1 + (g - 1) * INSTR_BYTES + 2],
                            note):
            continue
        drums.append(g)
    if not drums:
        return patterns, wave_entries, written
    prog = (sfx_rest_click_entries(det.sfx_pitch, det.sfx_period, multiplier,
                                   ENVELOPE_PARK_WAVE, ENVELOPE_LEAD,
                                   ENVELOPE_HELD)
            if envelope_kind else
            sfx_rest_click_entries(det.sfx_pitch, det.sfx_period, multiplier))
    if prog is None:
        return patterns, wave_entries, written
    left, right, loop = prog
    row_map: Optional[Dict[int, int]] = None
    unplaced = (patterns, wave_entries, written)
    if len(wave_entries) + 1 + len(left) > GT_MAX_TABLELEN:
        freed = (drop_unreached_rows(wave_entries, patterns,
                                     _starts_of(out, instr_at, written))
                 if envelope_kind else None)
        if freed is None or (len(freed[0]) + 1 + len(left)
                             > GT_MAX_TABLELEN):
            if log:
                log("Sfx rest click..........: no room in the wavetable; "
                    "rests keep a plain key-off")
            return unplaced
        wave_entries, patterns, row_map = freed
    start = len(wave_entries) + 1
    ceiling = min(TEMPO_DUTY_MAX_CLONE, clone_number_ceiling(patterns, written))
    entry = _entry_instruments(tracks, patterns)
    clone_of = {g: written + 1 + k for k, g in enumerate(drums)
                if written + 1 + k <= ceiling}
    new, placed, used = click_rests(patterns, entry, clone_of, envelope_kind)
    if not placed:
        return unplaced
    if used != set(clone_of):
        # Number only the clones a rest names, contiguously.
        clone_of = {g: written + 1 + k
                    for k, g in enumerate(g for g in drums if g in used)}
        new, placed, used = click_rests(patterns, entry, clone_of,
                                        envelope_kind)
    written_before = written
    for g in sorted(clone_of, key=clone_of.get):
        rec = bytearray(out[instr_at + 1 + (g - 1) * INSTR_BYTES:
                            instr_at + 1 + g * INSTR_BYTES])
        rec[0] = 0x00                  # AD: the rest zeroes the pair
        rec[1] = 0x00                  # SR
        rec[2] = start & 0xFF          # the click program
        rec[3] = 0x00                  # pulse runs on, as across the rest
        rec[4] = 0x00                  # filter likewise
        # firstwave: the rest's parked $08
        rec[8] = ENVELOPE_FIRSTWAVE if envelope_kind else REST_SILENT_WAVE
        out += rec
        written += 1
    out[instr_at] = written
    if row_map is not None:
        # The rows moved: every record's pointer, as the clones are cut from
        # records whose pointer is moved here too and then set to `start`,
        # which is already a new row.
        for g in range(1, written_before + 1):
            at = instr_at + 1 + (g - 1) * INSTR_BYTES + 2
            if out[at]:
                out[at] = row_map[out[at]]
        if log:
            log(f"Sfx rest click..........: "
                f"{len(unplaced[1]) - len(wave_entries)} unreached wavetable "
                f"row(s) dropped to make room")
    if log:
        log(f"Sfx rest click..........: {placed} rest(s) of a drum record "
            f"sound the hit the player fires one frame in")
    return (new, wave_entries + list(zip(left, right))
            + [(GT_WAVE_JUMP, start + loop)], written)
