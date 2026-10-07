"""Pin a wavetable note that indexes past Goattracker's frequency table.

A wavetable step's right side `$00`-`$7F` is a note RELATIVE to the voice's
note: both players compute `(note + right) & $7F` and look that up in the
frequency table (`player.s:1055-1058` `adc mt_chnnote,x / and #$7f`,
`gplay.c:717-721`). Goattracker's table has 96 entries, so a sum of 96-127
reads past its end -- and the two players disagree about what is there:

* the editor's table is 128 entries long with zeros above 95
  (`gplay.c:9-35`), so it plays frequency `$0000`;
* the packed player reads whatever `gt2reloc` put after `mt_freqtblhi`
  (`greloc.c:1182-1194`): the low byte comes out of the high table and the
  high byte out of `mt_songtbllo`, the orderlists' address bytes. Those
  move with the size of everything laid out before the orderlists, so a
  change to the PULSE table moved a drum's pitch. Measured on the forced
  pulse_phase packs that found this (Master_of_Magic sub 1, Phantoms sub 1,
  Human_Race sub 3): the frequency changed between two layouts with no
  change to any wave or note byte.

`gt2reloc` cannot keep these inside its table either: its range is capped
at 95 (`greloc.c:315`, `:887`), which these files already reach.

**What the original does there.** The relative step is the player's own
`CLC / ADC #$0C` (the octave) on the note index before `ASL / TAY / LDA
freqtbl,Y` (Master_of_Magic `$C308` -> `$C311`, Phantoms `$E339` -> `$E342`,
Human_Race `$0CBD` -> `$0CC6`, each `LDA` naming the table `find_freq_table`
places), so the original reads past ITS table too, at the same index,
and sounds the two bytes that follow it -- the reading `patterns.
past_table_notes` already makes for a note BYTE past the table. Here it is
made for a wavetable step: the step is rewritten as the ABSOLUTE note
nearest the cell's load-time value, in the original's own table.

At index 96 all three read `00 07`, the head of the per-voice offset table
that follows the note table: `$0700`, which siddump shows the original
playing on every one of Phantoms' 262 C-7 octave frames in 180 s. Where the player writes the cell (its per-voice
work bytes, from index 97 on) the original sounds running state that a
wavetable cannot follow -- Human_Race's index 100 high byte is voice 0's
note-length countdown (`$09E4 DEC $0DAD,X`), $0B00 down to $0000 per note --
and the load-time value is a fixed stand-in for it, chosen because it is
static and is the same reading as the unwritten case. A `$0000` cell has no
absolute note (`$80` means "no change"), so it pins C#0, the lowest one.

**Reach: a step every note that reaches it overflows.** A step that some
note reaches inside the table must keep its relative byte, so it is left
alone (a variant record would be needed to split it -- not done here). The
notes are read off the finished orderlists: every note row under the
voice's latched instrument (1 until a column names one, `gplay.c:62`),
transposed, plus every CMD_SETWAVEPTR row with the voice's note. Where the
notes reaching a step read different cells, the most-played note's cell
wins, and the log says how many notes it overrode.

**COMMANDO IS HELD** (`HELD`), as `stored_wave.HELD` holds it and for the
same reason: `Commando.sng` is the byte-exact fixture. Under the fixture's
options its step 27 (`+12`, notes reaching only indexes 97-104) would pin to
entry 59 -- a per-voice stored-waveform cell `stored_wave` reads, which is
running state. Under presets.json no Commando step qualifies.

Last, on the finished bytes, beside the other finished-bytes passes
(`instrument_drop`), and before `_append_players`: the cells are read in
THIS player's table, so the appended players' steps must not be seen.
"""
from __future__ import annotations

from collections import Counter, defaultdict
from math import log2
from typing import Callable, Dict, List, Optional, Tuple

from .goatwriter.appending import _parse_song, _write_song

# Goattracker's frequency table length (gcommon.h:37 MAX_NOTES).
GT_NOTES = 96
_FIRST_NOTE, _LAST_NOTE = 0x60, 0xBC      # gcommon.h:48-49
_CMD_SETWAVEPTR = 0x8                      # gcommon.h CMD_SETWAVEPTR
_WAVE_CMD = 0xF0                           # left $F0-$FE: command; $FF: jump
_JUMP = 0xFF
_KEEP = 0x80                               # right $80: no frequency change

# Held by PSID name -- see the module docstring.
HELD = frozenset({"Commando"})


def _program(wave: List[Tuple[int, int]], start: int) -> List[int]:
    """1-based steps the wave program entered at `start` runs through."""
    steps, seen, i = [], set(), start
    while 0 < i <= len(wave) and i not in seen:
        seen.add(i)
        left, right = wave[i - 1]
        if left == _JUMP:
            i = right
            continue
        steps.append(i)
        i += 1
    return steps


def _contexts(song) -> Dict[int, Counter]:
    """{1-based wave step: Counter(note index the voice holds when it runs)}."""
    wave = song.tables[0]
    count = len(song.instruments)
    out: Dict[int, Counter] = defaultdict(Counter)
    progs: Dict[int, List[int]] = {}

    def run(start: int, note: int) -> None:
        if start not in progs:
            progs[start] = _program(wave, start)
        for s in progs[start]:
            out[s][note] += 1

    for track in song.tracks:
        trans, instr, note = 0, 1, None
        for b in track[:-1]:
            if b == 0xFF:
                break
            if 0xE0 <= b < 0xFF:
                trans = b - 0xF0
                continue
            if 0xD0 <= b < 0xE0 or b >= len(song.patterns):
                continue
            pat = song.patterns[b]
            for k in range(0, len(pat) - 3, 4):
                nt, ins, cmd, data = pat[k:k + 4]
                if ins:
                    instr = ins
                if _FIRST_NOTE <= nt <= _LAST_NOTE:
                    note = nt - _FIRST_NOTE + trans
                    if 0 < instr <= count and song.instruments[instr - 1][2]:
                        run(song.instruments[instr - 1][2], note)
                if (cmd & 0x0F) == _CMD_SETWAVEPTR and data and note is not None:
                    run(data, note)
    return out


def _cell_entry(sid, det, index: int) -> Optional[int]:
    """The original's table entry nearest the load-time value of the cell
    its note fetch reads at `index` past the table; None off the file."""
    ft = det.freq_table
    data = sid.data
    base = sid.to_offset(ft.addr)
    cell = base + 2 * index
    if base < 0 or cell + 1 >= len(data) or base + 2 * ft.length > len(data):
        return None
    table = [data[base + 2 * i] | (data[base + 2 * i + 1] << 8)
             for i in range(ft.length)]
    value = data[cell] | (data[cell + 1] << 8)
    if value == 0:
        return 0
    return min(range(ft.length),
               key=lambda i: abs(log2(max(table[i], 1) / value)))


def pin_past_table_wave_notes(blob: bytes, sid, det,
                              log: Optional[Callable[[str], None]] = None
                              ) -> bytes:
    """`blob` with every relative wave step that only ever reads past
    Goattracker's table rewritten as the absolute note the original reads
    there (see the module docstring)."""
    if det.freq_table is None or sid.name in HELD:
        return bytes(blob)
    song = _parse_song(blob)
    wave = song.tables[0]
    shift = det.note_base
    pinned: List[str] = []
    overridden = 0
    for step, notes in sorted(_contexts(song).items()):
        left, right = wave[step - 1]
        if left >= _WAVE_CMD or right >= _KEEP:
            continue
        if any((n + right) & 0x7F < GT_NOTES for n in notes):
            continue
        major = min(notes, key=lambda n: (-notes[n], n))
        index = (major - shift + right) & 0x7F
        if index < det.freq_table.length:
            continue        # the original names a pitch Goattracker cannot
        entry = _cell_entry(sid, det, index)
        if entry is None:
            continue
        target = max(1, entry + shift)
        if target >= GT_NOTES:
            continue
        overridden += sum(c for n, c in notes.items()
                          if (n - shift + right) & 0x7F != index
                          and _cell_entry(sid, det, (n - shift + right) & 0x7F)
                          != entry)
        wave[step - 1] = (left, 0x80 | target)
        pinned.append(f"{step}:+{right}->{target}")
    if not pinned:
        return bytes(blob)
    if log:
        log(f"Past-table wave note....: {len(pinned)} relative step(s) read "
            f"past Goattracker's table on every note; pinned to the original's "
            f"cell ({', '.join(pinned)})"
            + (f"; {overridden} note(s) whose own cell reads another pitch"
               if overridden else ""))
    return _write_song(song)
