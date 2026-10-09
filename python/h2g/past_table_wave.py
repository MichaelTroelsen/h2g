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

**A step some note reaches inside the table** cannot be pinned in place --
one byte would serve both -- and used to be left alone, which left its
overflowing notes on the layout-dependent cell. Measured on 5_Title_Tunes
(the octave arpeggio `10 +12 / 10 +0 / FF` of its instrument 5, played on
C#7 and D#7 as well as on notes inside the table): the same conversion
sounded `$F701` on those notes at one wavetable size and `$8B01` at another
-- the high byte is the low byte of an orderlist address -- and a carried
skydive program that added wavetable rows moved the voice's
within-note travel from 0.856 of the original's to 1.637 with no window
involved. The original sounds `$000E` there. `retarget_mixed_steps` splits
the step by NOTE instead: the note row that sends a mixed step past the
table gets a `CMD_SETWAVEPTR` to a copy of the instrument's wave program
(every run the program reaches, jumps remapped) with that one step pinned
to the original's cell, exactly as above. A note row's own `CMD_SETWAVEPTR`
replaces the instrument's wave pointer on the note's first call and leaves
the instrument alone otherwise (`note_passes._attack_hold_pass`), so no
instrument is cloned and no later row needs restoring. A row is left
on the relative step, counted in the log, when its command column is taken,
when the contexts that play it disagree (a shared pattern under two
transposes), when the copy does not fit the wavetable, or when the pattern
would pack past `PACKED_PATTERN_LIMIT`.

Last, on the finished bytes, beside the other finished-bytes passes
(`instrument_drop`), and before `_append_players`: the cells are read in
THIS player's table, so the appended players' steps must not be seen.
"""
from __future__ import annotations

from collections import Counter, defaultdict
from contextlib import contextmanager
from math import log2
from typing import Callable, Dict, List, Optional, Tuple

from .goatwriter.appending import _parse_song, _write_song
from .goatwriter.constants import (CMD_VIBRATO as _CMD_VIBRATO, GT_MAX_TABLELEN,
                                  GT_TEMPO_INSTRUMENT, PACKED_PATTERN_LIMIT)
from .goatwriter.pulse import packed_pattern_size, pattern_rows

# Goattracker's frequency table length (gcommon.h:37 MAX_NOTES).
GT_NOTES = 96
_FIRST_NOTE, _LAST_NOTE = 0x60, 0xBC      # gcommon.h:48-49
_CMD_SETWAVEPTR = 0x8                      # gcommon.h CMD_SETWAVEPTR
_WAVE_CMD = 0xF0                           # left $F0-$FE: command; $FF: jump
_JUMP = 0xFF
_KEEP = 0x80                               # right $80: no frequency change
_VIBRATO_AT = 5                             # an instrument record's speed-table pointer
# Instrument 63 is the startup row `instrument_drop.add_startup_tempo` adds.
_MAX_SONG_INSTRUMENTS = GT_TEMPO_INSTRUMENT - 1

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


def _pin_target(sid, det, note: int, right: int) -> Optional[int]:
    """The absolute note the original sounds where `note` plus the relative
    step `right` reads past Goattracker's table, or None (the step reads
    inside it, or the original's cell names no pitch Goattracker has)."""
    if (note + right) & 0x7F < GT_NOTES:
        return None
    shift = det.note_base
    index = (note - shift + right) & 0x7F
    if index < det.freq_table.length:
        return None
    entry = _cell_entry(sid, det, index)
    if entry is None:
        return None
    target = max(1, entry + shift)
    return target if target < GT_NOTES else None


def _reach(song) -> Dict[Tuple[int, int], List[Tuple[int, int, int]]]:
    """{(pattern, byte offset of the row): [(wave row the row starts, note
    it is played at, instrument latched at the row), ...]}, one entry per
    orderlist visit.

    The walk of `_contexts`, but a note row that carries its own
    `CMD_SETWAVEPTR` starts only that program: the pointer replaces the
    instrument's before its first step runs."""
    count = len(song.instruments)
    out: Dict[Tuple[int, int], List[Tuple[int, int, int]]] = defaultdict(list)
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
                start = None
                if _FIRST_NOTE <= nt <= _LAST_NOTE:
                    note = nt - _FIRST_NOTE + trans
                    if 0 < instr <= count and song.instruments[instr - 1][2]:
                        start = song.instruments[instr - 1][2]
                if (cmd & 0x0F) == _CMD_SETWAVEPTR and data and note is not None:
                    start = data
                if start is not None and note is not None:
                    out[(b, k)].append((start, note, instr))
    return out


def _closure(wave: List[Tuple[int, int]],
             start: int) -> Optional[List[Tuple[int, int]]]:
    """The 1-based row spans (first, last) the program entered at `start`
    can run, closed under jumps and ending at a `$FF` row each; None where
    one runs off the table or jumps off it."""
    spans: List[Tuple[int, int]] = []
    queue, seen = [start], set()
    while queue:
        first = queue.pop()
        if first in seen:
            continue
        seen.add(first)
        if not 0 < first <= len(wave):
            return None
        last = first
        while wave[last - 1][0] != _JUMP:
            last += 1
            if last > len(wave):
                return None
        spans.append((first, last))
        target = wave[last - 1][1]
        if target:
            queue.append(target)
    merged: List[List[int]] = []
    for first, last in sorted(spans):
        if merged and first <= merged[-1][1]:
            merged[-1][1] = max(merged[-1][1], last)
        else:
            merged.append([first, last])
    return [(a, b) for a, b in merged]


def _split_key(song, sid, det, start: int, note: int, cache: dict):
    """(start, ((row, pinned note), ...)) for a program played at `note`
    whose relative steps read past the table, or None."""
    wave = song.tables[0]
    if start not in cache:
        cache[start] = _closure(wave, start)
    spans = cache[start]
    if spans is None:
        return None
    pins = []
    for a, b in spans:
        for row in range(a, b + 1):
            left, right = wave[row - 1]
            if left >= _WAVE_CMD or right >= _KEEP:
                continue
            target = _pin_target(sid, det, note, right)
            if target is not None:
                pins.append((row, target))
    return (start, tuple(pins)) if pins else None


def _variant_rows(wave: List[Tuple[int, int]], spans, pins: Dict[int, int],
                  base: int) -> List[Tuple[int, int]]:
    """The `spans` rows copied to rows `base + 1` on, jumps remapped, the
    `pins` rows turned absolute."""
    where, pos = {}, base + 1
    for a, b in spans:
        where[a] = pos
        pos += b - a + 1

    def moved(row: int) -> int:
        for a, b in spans:
            if a <= row <= b:
                return where[a] + row - a
        raise ValueError(f"jump to row {row} leaves the copied program")

    rows = []
    for a, b in spans:
        for row in range(a, b + 1):
            left, right = wave[row - 1]
            if left == _JUMP and right:
                right = moved(right)
            elif row in pins:
                right = 0x80 | pins[row]
            rows.append((left, right))
    return rows


def _offset_in(spans, start: int) -> int:
    """Rows from the first copied row to the copy of `start`."""
    off = 0
    for a, b in spans:
        if a <= start <= b:
            return off + start - a
        off += b - a + 1
    raise ValueError(start)


# Off while `convert._append_players` retries a compilation that lost a player
# to the room the split spends (wavetable rows, instrument slots).
SPLIT_MIXED = True


@contextmanager
def mixed_split(on: bool):
    global SPLIT_MIXED
    before, SPLIT_MIXED = SPLIT_MIXED, on
    try:
        yield
    finally:
        SPLIT_MIXED = before


def retarget_mixed_steps(song, sid, det,
                         log: Optional[Callable[[str], None]] = None) -> bool:
    """Split the steps `pin_past_table_wave_notes` cannot pin in place (see
    the module docstring) by pointing each note row that overflows one at a
    pinned copy of its wave program. Edits `song`; True where it changed.

    Two ways to point, by what the row's command column holds:

    * free (or already a `CMD_SETWAVEPTR`, or a `CMD_VIBRATO 0` on an
      instrument with no vibrato, which says nothing): the row takes the
      pointer, and nothing else about the voice changes;
    * `CMD_VIBRATO 0` on an instrument that does vibrate -- the vibrato
      pass's "this note never vibrates" -- the pointer cannot share the
      column, so the row names a CLONE of the instrument with the vibrato
      off and the pinned program, and the row after it names the instrument
      again where it names none (the clone stays latched until a column says
      otherwise, `gplay.c:62`/`:358`). A row that ends its pattern is left.
    """
    if det.freq_table is None or not SPLIT_MIXED:
        return False
    wave = song.tables[0]
    cache: dict = {}
    plans: Dict[Tuple[int, int], tuple] = {}
    conflict = busy = edge = 0
    for (b, k), visits in _reach(song).items():
        keys = {_split_key(song, sid, det, st, n, cache) for st, n, _i in visits}
        if keys == {None}:
            continue
        instrs = {i for _s, _n, i in visits}
        if len(keys) > 1 or len(instrs) > 1:
            conflict += 1
            continue
        key, instr = next(iter(keys)), next(iter(instrs))
        pat = song.patterns[b]
        cmd, data = pat[k + 2] & 0x0F, pat[k + 3]
        if cmd == 0 and data == 0 or cmd == _CMD_SETWAVEPTR:
            plans[(b, k)] = ("ptr", key, instr)
        elif (cmd == _CMD_VIBRATO and data == 0
              and 0 < instr <= len(song.instruments)):
            if not song.instruments[instr - 1][_VIBRATO_AT]:
                plans[(b, k)] = ("ptr", key, instr)
            elif k + 4 >= len(pat):
                edge += 1
            else:
                plans[(b, k)] = ("clone", key, instr)
        else:
            busy += 1
    if not plans:
        if log and (conflict or busy or edge):
            log(f"Past-table wave split...: {conflict + busy + edge} note "
                f"row(s) left on a relative step past the table ({conflict} "
                f"played under contexts that disagree, {busy} with the "
                f"command column in use, {edge} ending their pattern)")
        return False
    wave_room = GT_MAX_TABLELEN - len(wave)
    instr_room = _MAX_SONG_INSTRUMENTS - len(song.instruments)
    noroom = over = 0
    while True:
        usage = Counter(p[1] for p in plans.values())
        starts: Dict[tuple, int] = {}
        bodies: Dict[tuple, list] = {}
        used = 0
        for key in sorted(usage, key=lambda c: (-usage[c], c)):
            body = _variant_rows(wave, cache[key[0]], dict(key[1]),
                                 len(wave) + used)
            if used + len(body) > wave_room:
                continue
            starts[key] = len(wave) + used + 1 + _offset_in(cache[key[0]], key[0])
            bodies[key] = body
            used += len(body)
        cloned = Counter((p[2], p[1]) for p in plans.values() if p[0] == "clone")
        clones: Dict[tuple, int] = {}
        for ck in sorted(cloned, key=lambda c: (-cloned[c], c)):
            if ck[1] in starts and len(clones) < instr_room:
                clones[ck] = len(song.instruments) + 1 + len(clones)
        dropped = [rc for rc, (mode, key, instr) in plans.items()
                   if key not in starts
                   or (mode == "clone" and (instr, key) not in clones)]
        for rc in dropped:
            del plans[rc]
            noroom += 1
        edited: Dict[int, list] = {}
        for (b, k), (mode, key, instr) in plans.items():
            pat = edited.setdefault(b, list(song.patterns[b]))
            pat[k + 2], pat[k + 3] = _CMD_SETWAVEPTR, starts[key]
            if mode == "clone":
                pat[k + 1] = clones[(instr, key)]
        for (b, k), (mode, key, instr) in plans.items():
            # The row after a clone names the instrument again, unless it
            # names one of its own (a clone row does, above).
            if mode == "clone" and song.patterns[b][k + 5] == 0 \
                    and plans.get((b, k + 4), ("",))[0] != "clone":
                edited[b][k + 5] = instr
        too_big = [b for b, pat in edited.items()
                   if packed_pattern_size(pattern_rows(pat)) > PACKED_PATTERN_LIMIT]
        for rc in [rc for rc in plans if rc[0] in too_big]:
            del plans[rc]
            over += 1
        if not dropped and not too_big:
            break
    if not plans:
        if log:
            log(f"Past-table wave split...: {noroom + over} note row(s) left "
                f"on a relative step past the table ({noroom} wavetable or "
                f"instruments full, {over} pattern would pack too large)")
        return False
    for key in starts:
        wave.extend(bodies[key])
    for (instr, key), number in sorted(clones.items(), key=lambda c: c[1]):
        rec = bytearray(song.instruments[instr - 1])
        rec[2], rec[_VIBRATO_AT] = starts[key], 0
        song.instruments.append(rec)
    for b, pat in edited.items():
        song.patterns[b][:] = pat
    if log:
        steps = sorted({r for key in starts for r, _t in key[1]})
        pointed = sum(1 for p in plans.values() if p[0] == "ptr")
        log(f"Past-table wave split...: {len(plans)} note row(s) play one of "
            f"{len(starts)} pinned copy(ies) of their wave program "
            f"({used} row(s); {pointed} by pointer, {len(plans) - pointed} "
            f"by {len(clones)} instrument clone(s)); steps "
            f"{', '.join(map(str, steps))} read past the table on those "
            "notes and inside it on others"
            + (f"; {conflict} row(s) left (contexts disagree)" if conflict else "")
            + (f"; {busy} left (command column in use)" if busy else "")
            + (f"; {edge} left (ends its pattern)" if edge else "")
            + (f"; {noroom} left (wavetable or instruments full)" if noroom else "")
            + (f"; {over} left (pattern would pack too large)" if over else ""))
    return True


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
    if pinned and log:
        log(f"Past-table wave note....: {len(pinned)} relative step(s) read "
            f"past Goattracker's table on every note; pinned to the original's "
            f"cell ({', '.join(pinned)})"
            + (f"; {overridden} note(s) whose own cell reads another pitch"
               if overridden else ""))
    split = retarget_mixed_steps(song, sid, det, log)
    if not pinned and not split:
        return bytes(blob)
    return _write_song(song)
