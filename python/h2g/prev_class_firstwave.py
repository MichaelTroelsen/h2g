"""The note-init frame shows the PREVIOUS note's last waveform, as the
original's does, from a finished `.sng`.

A gate-off firstwave (`goatwriter.gate_off_firstwave`) spends the note-init
call on the record's OWN waveform with the gate clear. The original writes no
waveform on that frame: its chip holds the previous note's last waveform,
gate clear, and the new waveform, the gate and the pitch arrive together on
the next frame (Phantoms_of_the_Asteroid voice 2, frames 369-376: O
`80 80 80 41*`, ours `80 80 40 41*`). Goattracker's firstwave byte is part of
the instrument record, so no single byte is right for a record that follows
different instruments, and the two other spellings are worse (`$FF` latches
the waveform but opens the gate on the stale pitch; `$FE` never opens it).

What the chip holds is a function of the previous INSTRUMENT, though: run the
predecessor's wavetable program for the calls its note lasted
(`_run_program`) and the waveform it leaves is the original's waveform on the
frame before the next attack, on every one of Phantoms' 2589, One_Man_and_his_
Droid's 2632 and Lakers_vs_Celtics' 1293 attacks (select nibble). A clone of
the record per predecessor waveform carries it.

This runs on the FINISHED bytes, after every pass that writes or renumbers an
instrument column and before the startup record (`call_phase`):

* every note-init row of every voice is visited in play order, orderlist
  repeats and the restart lap included, carrying the live instrument as the
  player does (instrument 00 keeps) and the chip's waveform through each
  note's program;
* a row whose record has a gate-off real firstwave and whose chip waveform has
  a different select nibble gets a clone of the record with that waveform
  (gate clear) as its firstwave;
* the variant chosen by the majority of the visits to a shared pattern row
  wins, and a row whose visits disagree on the instrument is left alone;
* a row that inherits its instrument from the row before it (instrument 00)
  and so would silently inherit a clone gets the instrument named explicitly.

A tone-portamento row is not a note init (`player.s:831`) and is neither
changed nor taken as a predecessor. Needs the subtune's row length in calls;
without it nothing is changed.
"""
from collections import Counter, defaultdict
from typing import Callable, Dict, List, Optional, Tuple

from .goatwriter import (GT_FIRST_NOTE, GT_LAST_NOTE, GT_TEMPO_INSTRUMENT,
                         HEADER_LEN)
from .patterns import (CMD_TONEPORTA, GT_END_PATTERN, GT_ORDER_RESTART,
                       GT_REPEAT, GT_TRANSPOSE_DOWN, MAX_PATTERNS)

_RECORD_LEN = 25
_WAVE_AT, _FIRSTWAVE_AT = 2, 8
_WAVE_MAX_DELAY = 0x0F
_WAVE_FIRST_CMD = 0xF0
_TESTBIT = 0x08
# The writer's own limit: GT_TEMPO_INSTRUMENT (63) is the startup record.
_MAX_RECORDS = GT_TEMPO_INSTRUMENT - 1
# Which record's ring, sync and test bits the init frame shows. The chip's
# (the predecessor's) match the original's pre-frame more often -- 2498 of
# 2626 attacks against the record's own 2395 on Zoolook, 2445 of 2448 against
# 2182 on Thundercats -- and lift `ctrl` 84 -> 86%, 98 -> 100%, 94 -> 100%
# (Chain_Reaction, Crazy_Comets, Formula_1_Simulator). But the printed `ring`
# and `sync` columns are frame COUNTS over the original's, and the record's
# own bits are what made them agree: with the chip's, Chain_Reaction 1.00 ->
# 0.96, Zoolook 0.99 -> 0.96, Thundercats 1.00 -> 0.97, unmasking ring frames
# the conversion misses elsewhere in the note. The record's own bits keep
# every one of those columns where it was (measured, -t 180). Flip to trade.
CONTROL_BITS_FROM_CHIP = False
# **A predecessor that leaves noise with the gate ON leaves the gate on.** An
# absolute (`>= $80`) wave-program opcode writes `$D404` raw and skips the
# per-frame `AND gate` (Lakers_vs_Celtics `$16E2`: `STA $D404,X / ... JMP $17ED`
# past `$17D8 LDA stored / AND mask`), so a drum whose last frames are `set $81`
# sits gate-on through the original's own gate-off window, and the next note
# (`41`, a pitch change) is not a gate edge. Goattracker's `wave & gate`
# (gplay.c:951) has no raw write: the window ANDs that `$81` to `$80` and the
# same note is a fresh edge (Lakers voice 2 f2691: one ours-only attack on
# instrument `$09CB`). The window is fetched `gatetimer` calls before a note by
# the NOTE'S instrument (gplay.c:920-927), so a legato clone of that
# instrument (gatetimer `$40`) for the note that follows such a tail leaves the
# gate up, and its firstwave is the chip's waveform with the gate set.
RAW_GATE_LEGATO = True
_RAW_GATE_ON = 0x81          # noise and gate: only an absolute opcode writes it
_LEGATO = 0x40
_GATETIMER_AT = 7


def _layout(blob: bytes):
    """(tracks, instr_at, wave table (left, right) rows, tables_at,
    patt_at, [(first row offset, rows)])."""
    if bytes(blob[:4]) not in (b"GTS2", b"GTS5"):
        raise ValueError("not a Goattracker song")
    pos = HEADER_LEN
    subtunes = blob[pos]
    pos += 1
    tracks = []
    for _ in range(subtunes * 3):
        n = blob[pos]
        tracks.append(list(blob[pos + 1:pos + n + 2]))
        pos += n + 2
    instr_at = pos
    tables_at = instr_at + 1 + blob[instr_at] * _RECORD_LEN
    pos = tables_at
    tables = []
    for _ in range(4 if bytes(blob[:4]) == b"GTS5" else 3):
        n = blob[pos]
        tables.append(list(zip(blob[pos + 1:pos + 1 + n],
                               blob[pos + 1 + n:pos + 1 + 2 * n])))
        pos += 1 + 2 * n
    patt_at = pos
    pos += 1
    patterns = []
    for _ in range(blob[patt_at]):
        rows = blob[pos]
        patterns.append((pos + 1, rows))
        pos += 1 + rows * 4
    if pos != len(blob):
        raise ValueError("layout read does not reach the end of the file")
    return tracks, instr_at, tables[0], tables_at, patt_at, patterns


def _run_program(wtbl: List[Tuple[int, int]], start: int,
                 wave: Optional[int], ncalls: int) -> Optional[int]:
    """The waveform byte the chip holds after `ncalls` play calls of the
    wavetable program from 1-based row `start`, given it held `wave` before
    (gplay.c:670-720: a delay row `d` holds `d + 1` calls, a waveform or a
    command row one, a jump is followed in the call that reaches it, and the
    init call itself runs no wavetable row)."""
    ptr, wait = start, 0
    for _ in range(max(ncalls, 0)):
        if not 1 <= ptr <= len(wtbl):
            break
        left, _right = wtbl[ptr - 1]
        if left <= _WAVE_MAX_DELAY:
            if left != wait:
                wait += 1
                continue
        elif left < _WAVE_FIRST_CMD:
            wave = left if left < 0xE0 else left & 0x0F
        wait = 0
        ptr += 1
        if 1 <= ptr <= len(wtbl) and wtbl[ptr - 1][0] == 0xFF:
            ptr = wtbl[ptr - 1][1]
    return wave


def _first_entry_is_wave(wtbl: List[Tuple[int, int]], start: int) -> bool:
    """The program from `start` opens on a waveform entry, so the firstwave
    byte is spent on the init call alone."""
    if not 1 <= start <= len(wtbl):
        return False
    left = wtbl[start - 1][0]
    return _WAVE_MAX_DELAY < left < _WAVE_FIRST_CMD


def _visits(track: List[int], patterns: List[Tuple[int, int]]):
    """(pattern, restart lap) in play order: the orderlist once, then the
    positions from its restart position once more."""
    seq: List[Tuple[int, int]] = []
    restart = 0
    repeat = 1
    body: List[Tuple[int, int]] = []     # (position, pattern)
    for pos, b in enumerate(track):
        if b == GT_ORDER_RESTART:
            restart = track[pos + 1] if pos + 1 < len(track) else 0
            break
        if GT_TRANSPOSE_DOWN <= b < GT_ORDER_RESTART:
            continue
        if GT_REPEAT <= b < GT_TRANSPOSE_DOWN:
            repeat = b - GT_REPEAT + 1
            continue
        if b >= MAX_PATTERNS or b >= len(patterns):
            repeat = 1
            continue
        body.append((pos, b, repeat))
        repeat = 1
    for pos, b, rep in body:
        seq += [(b, 0)] * rep
    for pos, b, rep in body:
        if pos >= restart:
            seq += [(b, 1)] * rep
    return seq


def prev_class_firstwave(blob: bytes,
                         subtune_row_calls: Optional[List[int]] = None,
                         multiplier: int = 1,
                         log: Optional[Callable[[str], None]] = None,
                         raw_gate_legato: bool = False) -> bytes:
    """`blob` with the clones and instrument columns described above.

    `subtune_row_calls` is the play calls a row lasts, per subtune
    (`convert`'s `group_tempos`): a note's length in calls is what decides
    how far the predecessor's wavetable program ran before the next note
    init. Without it nothing is changed. The program has run `D` calls at
    -S1 and `D - 1` above it, D being the note's length in calls
    (Hollywood_or_Bust voice 1 at -S1, a `$11 $81 $11 ...` alternation over
    6-call notes: the pre-frame holds noise, which `D - 1` calls would call
    triangle; at -S2/-S3, `D - 1` against `D - 2` over Zoolook, Thundercats
    and Chain_Reaction: wave .9881/.9865/.9892 against .9816/.9865/.9878).

    `raw_gate_legato` says the player's absolute opcode writes the chip raw
    (the `$86`-jump wave-program dialect, `RAW_GATE_LEGATO`); the pass takes
    it from the caller because the finished bytes cannot tell a raw `$81` from
    one the gate mask clears. Unscoped, the rule moved Chicken_Song (melody
    100% -> 87%, seq 100% -> 61%), Chain_Reaction (97%), Hollywood_or_Bust,
    Last_V8 and Zoolook, whose `$81` tails are ours and are masked.
    """
    if not subtune_row_calls:
        return bytes(blob)
    tracks, instr_at, wtbl, tables_at, patt_at, patterns = _layout(blob)
    count = blob[instr_at]
    recs = instr_at + 1

    def record(g: int) -> bytes:
        return blob[recs + (g - 1) * _RECORD_LEN:recs + g * _RECORD_LEN]

    # Records whose firstwave is a real, gate-clear waveform and whose
    # program opens on a waveform entry.
    eligible: Dict[int, int] = {}
    for g in range(1, count + 1):
        rec = record(g)
        fw = rec[_FIRSTWAVE_AT]
        if (fw & 0x01 == 0 and fw >= 0x10 and fw < 0xFE
                and _first_entry_is_wave(wtbl, rec[_WAVE_AT])):
            eligible[g] = fw

    def rows_of(b: int):
        start, nrows = patterns[b]
        for r in range(nrows):
            yield r, blob[start + 4 * r:start + 4 * r + 4]

    # Visit every note init of every voice in play order. The original's chip
    # keeps the last waveform written until the new note's program writes its
    # own: `chip` is that byte, advanced through each note's program for the
    # calls the note lasts (gate bit and all, as the register holds it).
    # (pattern, row) -> Counter of (instrument, wanted firstwave or None).
    want: Dict[Tuple[int, int], Counter] = defaultdict(Counter)
    insts: Dict[Tuple[int, int], set] = defaultdict(set)
    for ti, track in enumerate(tracks):
        calls = (subtune_row_calls[ti // 3]
                 if ti // 3 < len(subtune_row_calls) else 0)
        events = []                       # (key, live instrument, row index)
        live, row_no = 1, 0
        for b, _lap in _visits(track, patterns):
            for r, (note, ins, cmd, _data) in rows_of(b):
                if note == GT_END_PATTERN:
                    break
                if ins:
                    live = ins
                if (GT_FIRST_NOTE <= note <= GT_LAST_NOTE
                        and cmd != CMD_TONEPORTA):
                    events.append(((b, r), live, row_no))
                row_no += 1
        chip = None
        for i, (key, g, at) in enumerate(events):
            insts[key].add(g)
            nf = None
            if g in eligible and chip is not None:
                cand = ((chip & 0xF6) | (eligible[g] & _TESTBIT)
                        if CONTROL_BITS_FROM_CHIP
                        else (chip & 0xF0) | (eligible[g] & 0x0E))
                if ((cand & 0xF0) and cand < 0xFE
                        and (cand & 0xF0) != (eligible[g] & 0xF0)):
                    nf = cand
                if (RAW_GATE_LEGATO and raw_gate_legato
                        and chip & _RAW_GATE_ON == _RAW_GATE_ON):
                    nf = ("legato", (chip & 0xF0) | (eligible[g] & 0x0E) | 1)
            want[key][(g, nf)] += 1
            if i + 1 < len(events) and calls:
                ncalls = (events[i + 1][2] - at) * calls - (1 if multiplier > 1 else 0)
                chip = _run_program(wtbl, record(g)[_WAVE_AT], chip, ncalls)
            else:
                chip = None

    # The variant each row plays: its majority, original on a tie or where
    # the visits disagree on the instrument.
    choice: Dict[Tuple[int, int], Tuple[int, Optional[int]]] = {}
    for key, cnt in want.items():
        if len(insts[key]) != 1:
            continue
        g = next(iter(insts[key]))
        own = cnt.get((g, None), 0)
        (best, n), = cnt.most_common(1)
        if best[1] is not None and n > own:
            choice[key] = best

    if not choice:
        if log:
            log("Previous-class firstwave: no note follows a different "
                f"waveform ({len(want)} note row(s) read, {len(eligible)} "
                "record(s) with a gate-off firstwave)")
        return bytes(blob)

    # Clone numbers, most-used first, within the record limit.
    usage = Counter()
    for key, (g, nf) in choice.items():
        usage[(g, nf)] += want[key][(g, nf)]
    clones: Dict[Tuple[int, int], int] = {}
    for (g, nf), _n in usage.most_common():
        if count + len(clones) >= _MAX_RECORDS:
            break
        clones[(g, nf)] = count + len(clones) + 1
    choice = {k: v for k, v in choice.items() if v in clones}
    if not choice:
        return bytes(blob)

    # New instrument column, then keep inheritance intact: simulate every
    # voice with the new bytes and, wherever a note init would play an
    # instrument that is not a variant of the one it means (a row that
    # relied on the live instrument and now inherits a clone), name the
    # intended one on that row. A row the visits disagree on cannot be
    # named, and then the whole change is declined.
    def choice_num(key, base):
        v = choice.get(key)
        return clones[v] if v in clones else base

    out_ins: Dict[Tuple[int, int], int] = {
        key: clones[v] for key, v in choice.items()}

    def violations():
        bad = []
        for track in tracks:
            live_o, live_n, src = 1, 1, None
            for b, _lap in _visits(track, patterns):
                for r, (note, ins, cmd, _d) in rows_of(b):
                    if note == GT_END_PATTERN:
                        break
                    new_ins = out_ins.get((b, r), ins)
                    if ins:
                        live_o = ins
                    if new_ins:
                        live_n, src = new_ins, (b, r)
                    if (GT_FIRST_NOTE <= note <= GT_LAST_NOTE
                            and cmd != CMD_TONEPORTA
                            and live_n != choice_num((b, r), live_o)):
                        bad.append(((b, r), live_o, src))
        return bad

    for _ in range(64):
        bad = violations()
        if not bad:
            break
        key, base, src = bad[0]
        if len(insts[key]) == 1:
            out_ins[key] = choice_num(key, base)
        elif src in choice:
            # The row inherits a clone a predecessor made and cannot name
            # its own instrument (its visits differ): the predecessor keeps
            # its record.
            del choice[src]
            out_ins.pop(src, None)
        else:
            if log:
                log("Previous-class firstwave: declined, row "
                    f"{key} cannot be settled")
            return bytes(blob)
    else:
        if log:
            log("Previous-class firstwave: declined, inheritance did not "
                "settle")
        return bytes(blob)

    # Only the clones a row still plays, numbered from the first free one.
    used = sorted({out_ins[k] for k in choice if k in out_ins}
                  | {v for k, v in out_ins.items() if v > count})
    if not used:
        return bytes(blob)
    renum = {old: count + 1 + i for i, old in enumerate(used)}
    out_ins = {k: renum.get(v, v) for k, v in out_ins.items()}
    clones = {key: renum[num] for key, num in clones.items() if num in renum}

    result = bytearray(blob[:instr_at])
    result.append(count + len(clones))
    result += blob[recs:recs + count * _RECORD_LEN]
    for (g, nf), num in sorted(clones.items(), key=lambda kv: kv[1]):
        rec = bytearray(record(g))
        if isinstance(nf, tuple):
            rec[_FIRSTWAVE_AT] = nf[1]
            rec[_GATETIMER_AT] |= _LEGATO
        else:
            rec[_FIRSTWAVE_AT] = nf
        result += rec
    result += blob[tables_at:patt_at + 1]
    for (start, nrows), (bpat) in zip(patterns, range(len(patterns))):
        result.append(nrows)
        body = bytearray(blob[start:start + nrows * 4])
        for r in range(nrows):
            k = (bpat, r)
            if k in out_ins:
                body[4 * r + 1] = out_ins[k]
        result += body
    if log:
        log(f"Previous-class firstwave: {len(clones)} clone(s), "
            f"{len(choice)} row(s) retargeted"
            + (f", {sum(1 for v in choice.values() if isinstance(v[1], tuple))}"
               " of them legato (a raw gate-on tail before the note)"
               if RAW_GATE_LEGATO else ""))
    return bytes(result)
