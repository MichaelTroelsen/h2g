"""Per-note passes: instrument entry, ties and legato clones, vibrato command, attack hold, past-table drum, expanding vibrato (split out of goatwriter.py, text moved unchanged)."""
from __future__ import annotations

import math
from typing import (List, Optional, Set, Tuple)

from ..detect import (Detection, TRIANGLE_VIBRATO_GATE, VIBRATO_BOUND_MASK,
                      VIBRATO_BOUND_SHIFT, VIBRATO_SHIFT_MASK)
from ..search import (search_file)
from ..sidfile import (SidFile)
from .constants import (CMD_SETAD, CMD_SETSR, CMD_SETWAVEPTR, CMD_TONEPORTA,
                        CMD_VIBRATO, EFFECT_SFX_DRUM_MASK,
                        EXPANDING_VIBRATO_COUNTER_AT, EXPANDING_VIBRATO_SHAPES,
                        EXPANDING_VIBRATO_TABLE_AT, GT_FIRST_NOTE, GT_KEYOFF,
                        GT_LAST_NOTE, GT_MAX_INSTRUMENTS, GT_MAX_VIB_SHIFT,
                        GT_REST, GT_WAVE_FIRST_CMD, GT_WAVE_JUMP,
                        GT_WAVE_LAST_CMD, GT_WAVE_LAST_DELAY, GT_WAVE_NO_NOTE,
                        LEGATO_TIE_FLAG_STORE_SHAPE, LEGATO_TIE_GATE_SHAPE,
                        PACKED_PATTERN_LIMIT, SONG_START_ROW,
                        SPEED_NOTE_RELATIVE, TEMPO_DUTY_MAX_CLONE,
                        WAVE_GATE_BIT, WAVE_SILENT_BASE, WAVE_TEST_BIT)
from .primitives import (_fixed_pitch_yield_field, _note_freq, _speed_index,
                         _wave_byte)
from .pulse import (packed_pattern_size, pattern_rows)
from . import constants as _gw_constants
def _entry_instruments(tracks: List[List[int]],
                       patterns: List[List[int]]) -> dict:
    """Pattern number -> the set of instruments a channel HOLDS when it enters
    that pattern, walked in play order over every orderlist.

    `pulse_usage`'s walk (gplay.c:62/:223 -- a channel holds instrument 1
    before any row names one; `instr 00` keeps the current one, gplay.c:914;
    repeats honoured, transposes skipped) recording the channel's instrument
    at each pattern's first row instead of counting notes. A pattern reached
    from two places with two different instruments gets both, and the caller
    treats that as unknown.

    The restart is followed for one more lap (`_lapped_tracks`): the loop
    (gplay.c:966-968, songptr = the operand) leaves `instr` alone, so a
    pattern the restart re-enters is entered holding whatever the last lap
    ended on, not instrument 1. One lap is the fixpoint -- a lap naming no
    instrument ends holding what it began with, and one naming any ends on
    the same last name every time. Walked once, a pattern the loop re-enters
    holding a different instrument came out SETTLED on the first lap's
    value, and the caller wrote against an instrument the loop does not hold.
    """
    entry: dict = {}
    for track in _lapped_tracks(tracks):
        current, repeat, operand = 1, 1, False
        for b in track:
            if operand:
                operand = False
                continue
            if b == 0xFF:
                operand = True
                continue
            if 0xE0 <= b < 0xFF:
                continue
            if 0xD0 <= b < 0xE0:
                repeat = b - 0xD0 + 1
                continue
            if b >= len(patterns):
                continue
            pat = patterns[b]
            for _ in range(repeat):
                entry.setdefault(b, set()).add(current)
                for r in range(0, len(pat), 4):
                    if pat[r] == 0xFF:
                        break
                    if pat[r + 1]:
                        current = pat[r + 1]
            repeat = 1
    return entry


def _tied_instrument_envelopes(patterns: List[List[int]], envelopes: dict,
                               tracks: Optional[List[List[int]]] = None,
                               log=None, skip: Optional[set] = None,
                               only: Optional[set] = None) -> List[List[int]]:
    """Write the envelope a tied note's NEW instrument carries, which the tie
    itself never loads.

    The classic players re-initialise the instrument on EVERY fetched note
    event, tied or not: Samantha Fox `$70F8-$7127` writes the waveform (with
    the gate mask `$B7`, `$FF` for a note), the pulse, then `$D405` and
    `$D406` from the record the operand named. A status-bit-5 event before it
    only keeps the gate from closing at the note end (`$7154 AND #$20 / BNE`
    past the gate-off at `$715E`), so an event such as pattern `$04`'s

        21 3C        wait 1, bit 5, note $3C      -- gate held open
        87 06 3C     wait 7, instrument 6, note $3C

    is the SAME pitch, no attack, and a new envelope: the trace shows
    `$1A0F -> $0F9F` at frame 301 with `$D404` unchanged. Goattracker cannot
    say that in one row. `patterns._build_raw_pattern` spells the tie as
    `CMD_TONEPORTA 0` with the instrument in the column, and BOTH players
    skip the envelope load on that command -- gplay.c:354 `if (newcommand !=
    CMD_TONEPORTA)` wraps the `sidreg[5] = iptr->ad; sidreg[6] = iptr->sr`
    at :397-398, and player.s:833-835 `cmp #TONEPORTA / beq mt_nonewnoteinit`
    jumps past `mt_inssr`/`mt_insad` at :882-892. So the instrument column
    latches (gplay.c:912) and the chip keeps the OLD pair: Samantha Fox
    held `$1A00` for 380 gate-on frames the original spent on `$0F9F`, 14
    runs, all on voice 1 (runs.jsonl,
    `samantha-fox-has-380-gate-on-frames...`).

    The row's one command column is the tie, so the pair cannot share it.
    Where it goes was measured on Samantha Fox over the harness's 92 s
    window -- gate-on frames whose AD or sustain nibble disagrees with the
    original, 380 before any of this -- and on the 27 corpus files the
    change reaches, all at v0.5.486:

    * **The SR write goes on the row BEFORE the tie** -- the tied-from
      event's last hold row, where `instr` alone latches (gplay.c:912,
      player.s:1252 `mt_instr`) and `CMD_SETSR` writes -- the tie keeps its
      own row, and `CMD_SETAD` takes the tie's first hold row. The sustain
      nibble is the audible half (instrument 6 here sustains at 0 and
      instrument 7 at 9, and a level already decayed below the new sustain
      never comes back); a row early it lands on a note still decaying from
      its peak, above either sustain, so nothing is heard of the lead, and
      the tie row is untouched, which every other reader of a tie row
      relies on. 380 -> **109** frames, all of them the one-row lead and the
      one-row lag; `bend` 0.922 -> 0.917, `depth` 0.759 -> 0.799.

      Three other spellings were measured and refused. (a) SR on the tie's
      row with the note dropped and no tie at all: 380 -> 56 and the best
      `bend`, but the running vibrato is never re-anchored -- Goattracker's
      vibrato integrates its steps from wherever the frequency IS, so when
      the next `CMD_DONOTHING` row loads the new instrument's speed-table
      entry (gplay.c:406-408) the centre moves for the rest of the note:
      the tied C-5 sat 0x10A flat of the original's 22D0, Warhawk's D-4
      0xC0 flat. (b) SR on the row, AD next, the tie two rows down: 380 ->
      56, but the OLD instrument's vibrato runs on for two rows where the
      original already has the new one's, and `depth` fell 0.759 -> 0.622
      (Bump Set Spike 0.944 -> 0.635). (c) SR on the row, the tie next, AD
      after it: 380 -> 101, `depth` 0.673, and a command row after a
      `CMD_TONEPORTA` row prolongs it -- only `CMD_DONOTHING` resets the
      running command -- so the frequency stood still 7 frames instead of
      4 at every Bump Set Spike switch.
    * **No free row before the tie** (a row-0 tie from
      `_apply_boundary_ties`, or a tied-from event with no hold row): the
      pair goes on the hold rows after the tie, SR first, and the SR row
      carries the instrument number again -- a re-latch of what the tie
      row latched, gplay.c:912 storing the same value -- so that it reads
      as the instrument's own write and not as a hold row a one-shot
      command leaked into, the defect tests/test_hold_rows.py exists to
      catch. `_vibrato_command_pass` reads such a re-latch as part of the
      note's block for the same reason. Forced onto all five Samantha Fox
      rows this spelling measured 380 -> 101 and `bend` 0.922 -> 0.894,
      the tie's freeze lengthened by the two command rows.

    A row with no free hold row keeps the defect rather than losing what it
    has, and a hold row already carrying a command stops the fill.
    `_vibrato_command_pass` runs AFTER this and fills only free rows.

    Scoped to a row whose instrument column names a DIFFERENT instrument
    from the one the channel holds there. Inside a pattern that is the last
    instrument a row named; before any row has, it is what the orderlists
    say the channel carried INTO the pattern (`_entry_instruments`), and only
    when every orderlist entry agrees -- Samantha Fox's patterns `$12` and
    `$15` open on a bit-5 note and tie into instrument 7 on their second
    event, holding instrument 6 from pattern `$0D` before them, and those
    two are 52 of the 380 frames. A tie into the same instrument re-writes
    the pair the chip already holds, so nothing is owed; a tie whose held
    instrument cannot be settled (no `tracks`, or two entries disagreeing)
    is left alone, counted and logged, because a write the writer cannot
    justify is a command slot the clock and the slides compete for.

    `envelopes` maps a Goattracker instrument number to the `(ad, sr)` pair
    `_write_instruments` will emit for it -- from `record_envelope`, so the
    two cannot disagree.
    """
    entry = _entry_instruments(tracks, patterns) if tracks else {}
    out: List[List[int]] = []
    placed = short = unknown = 0
    for pn, pattern in enumerate(patterns):
        rows = list(pattern)
        n = len(rows) // 4
        held = entry.get(pn, set())
        live = next(iter(held)) if len(held) == 1 else 0

        def free(q: int) -> bool:
            return (0 <= q < n and rows[q * 4] == GT_REST
                    and rows[q * 4 + 1] == 0 and rows[q * 4 + 2] == 0)

        for r in range(n):
            k = r * 4
            note, instr, cmd, data = rows[k], rows[k + 1], rows[k + 2], rows[k + 3]
            prev = live
            if instr:
                live = instr
            if not GT_FIRST_NOTE <= note <= GT_LAST_NOTE:
                continue
            if cmd != CMD_TONEPORTA or data != 0 or not instr:
                continue
            # `skip`: rows `legato_tie_clones` will respell as a legato
            # clone, which loads its own envelope at the note (gplay.c:397);
            # `only`: the rows it declined, given this pass after all.
            if skip and (pn, r) in skip:
                continue
            if only is not None and (pn, r) not in only:
                continue
            if not prev:
                unknown += 1
                continue
            if instr == prev or instr not in envelopes:
                continue
            ad, sr = envelopes[instr]
            if free(r - 1):
                rows[k - 4:k] = [GT_REST, instr, CMD_SETSR, sr & 0xFF]
                writes: tuple = ((CMD_SETAD, 0, ad),)
            else:
                writes = ((CMD_SETSR, instr, sr), (CMD_SETAD, 0, ad))
            rr = r + 1
            for c, who, v in writes:
                if free(rr):
                    rows[rr * 4 + 1:rr * 4 + 4] = [who, c, v & 0xFF]
                    rr += 1
                else:
                    short += 1
                    break
            placed += 1
        out.append(rows)
    if log is not None and (placed or unknown):
        log(f"Tied instrument change..: {placed} row(s) given the new "
            f"instrument's envelope"
            + (f", {short} short of a free hold row" if short else "")
            + (f", {unknown} whose held instrument could not be settled"
               if unknown else ""))
    return out


def legato_tie_family(sid: SidFile, det: Detection) -> bool:
    """True where the player's instrument start is skipped by the note
    byte's bit 7 and by nothing else: `LDA flag / BMI / LDA pulse,X / STA
    $D402,Y`, with `flag` the cell the note store (`INY / LDA (patt),Y / STA
    flag / AND #$7F`) wrote. Both spellings of `detect`'s `note_flag` start
    with that store. A file whose decoder does not read the flag
    (Mega_Apocalypse stores it to zero page) is out: its ties' bit 7 is
    unknown, and the old spelling stands."""
    if det.pattern_dialect != "classic" or not det.note_flag:
        return False
    data = sid.data
    gate = search_file(data, LEGATO_TIE_GATE_SHAPE)
    store = search_file(data, LEGATO_TIE_FLAG_STORE_SHAPE)
    if gate < 0 or store < 0:
        return False
    return data[gate + 1:gate + 3] == data[store + 4:store + 6]


def note_bit7_rows(patterns: List[List[int]], known: dict,
                   decoded: int) -> dict:
    """Pattern index -> the rows whose note byte carried bit 7 (or None:
    unknown). `known` is `patterns.PatternList.note_bit7` for the first
    `decoded` patterns; every pattern appended since is a copy some pass made
    with its notes in place, attributed by note column where exactly one
    known pattern's notes match and every such match carries one set
    (`patterns.inherit_free_rows`' rule, with an unknown source counting as
    a set of its own so a copy that might be its is unattributed)."""
    def notes(p):
        return tuple(p[4 * r] for r in range(len(p) // 4))

    out: dict = {}
    by_notes: dict = {}
    for idx in range(min(decoded, len(patterns))):
        flags = known.get(idx)
        out[idx] = flags
        by_notes.setdefault(notes(patterns[idx]), set()).add(flags)
    for idx in range(decoded, len(patterns)):
        found = by_notes.get(notes(patterns[idx]), set())
        out[idx] = next(iter(found)) if len(found) == 1 else None
    return out


def legato_tie_rows(patterns: List[List[int]], bit7: dict) -> set:
    """(pattern, row) of every tie row whose landing note restarts the
    instrument: `CMD_TONEPORTA 00` on a note, in a pattern whose bit-7 rows
    are known, on a row not among them."""
    rows = set()
    for pn, pat in enumerate(patterns):
        flags = bit7.get(pn)
        if flags is None:
            continue
        for r in range(len(pat) // 4):
            k = r * 4
            if (GT_FIRST_NOTE <= pat[k] <= GT_LAST_NOTE
                    and pat[k + 2] == CMD_TONEPORTA and pat[k + 3] == 0
                    and r not in flags):
                rows.add((pn, r))
    return rows


def _lapped_tracks(tracks: List[List[int]]) -> List[List[int]]:
    """Each orderlist followed by a second lap from its restart position, so
    `_entry_instruments` (which calls this itself -- do not lap twice: the
    appended `$FF 00` would add a lap from position 0 the player never
    plays) sees the instrument a channel carries across the loop as well as
    the first time through. A restart out of range (the tune ends,
    gplay.c:969 `songptr >= songlen` stops the song) adds nothing."""
    out = []
    for t in tracks:
        end = t.index(0xFF) if 0xFF in t else None
        if end is None or end + 1 >= len(t) or t[end + 1] >= end:
            out.append(list(t))
            continue
        out.append(list(t[:end]) + list(t[t[end + 1]:end]) + [0xFF, 0x00])
    return out


def _pattern_successors(tracks: List[List[int]], count: int) -> dict:
    """Pattern number -> the set of patterns a channel plays NEXT after it,
    over every orderlist in play order (repeats honoured, transposes
    skipped -- `_entry_instruments`' walk), the restart followed one lap
    (`_lapped_tracks`). A pattern the song ends on (no restart, or one out
    of range: gplay.c:969 stops the song) has no successor from there."""
    nxt: dict = {}
    for track in _lapped_tracks(tracks):
        prev, repeat, operand = None, 1, False
        for b in track:
            if operand:
                operand = False
                continue
            if b == 0xFF:
                operand = True
                continue
            if 0xE0 <= b < 0xFF:
                continue
            if 0xD0 <= b < 0xE0:
                repeat = b - 0xD0 + 1
                continue
            if b >= count:
                continue
            for _ in range(repeat):
                if prev is not None:
                    nxt.setdefault(prev, set()).add(b)
                prev = b
            repeat = 1
    return nxt


def _successor_relatch(out: List[List[int]], pn: int, base: int,
                       entry: dict, successors: dict):
    """For a tie on pattern `pn`'s LAST row: (successors whose row 0 must
    name `base`, None), or (None, decline reason).

    The clone stays latched across the pattern boundary -- gplay.c:912
    replaces `cptr->instr` only where a row names one, player.s:1251
    `mt_instr` likewise -- and both players test the legato bit of the
    instrument latched at the fetch (gplay.c:930, after :912), so a
    successor whose first note comes before any row names an instrument
    would play that note legato. A successor that names nothing at all
    carries the clone on into the pattern after it. Writing `base` on such
    a successor's row 0 re-latches it (gplay.c:912 stores it; on a note row
    it is the instrument the note was going to play anyway). It is taken
    only where `_entry_instruments` settles the successor on exactly
    `base` -- every other way into it already holds `base`, so the write
    changes nothing they hear -- and only where the copy still packs
    (`PACKED_PATTERN_LIMIT`, greloc.c packpattern): the column costs a
    byte."""
    need = []
    for q in sorted(successors.get(pn, ())):
        pat = out[q]
        covered = False
        for r in range(len(pat) // 4):
            note, ins = pat[4 * r], pat[4 * r + 1]
            if note == 0xFF:
                break
            if ins:
                covered = True
                break
            if GT_FIRST_NOTE <= note <= GT_LAST_NOTE:
                break
        if covered:
            continue
        if entry.get(q) != {base}:
            return None, "successor entered holding another instrument"
        trial = list(pat)
        trial[1] = base
        if packed_pattern_size(pattern_rows(trial)) > PACKED_PATTERN_LIMIT:
            return None, "successor would pack past the limit"
        need.append(q)
    return need, None


def legato_tie_clones(patterns: List[List[int]], rows: set,
                      tracks: Optional[List[List[int]]],
                      cloneable: Set[int], first_number: int,
                      last_number: int = 0, log=None):
    """Respell each of `rows` (`legato_tie_rows`) as a plain note on a legato
    clone of the instrument it plays. Returns (patterns, clones, declined):
    `clones` is [(instrument, clone number)] in number order from
    `first_number`; `declined` the rows that kept `CMD_TONEPORTA 00`.

    The instrument column latches (gplay.c:912-913, player.s `mt_instr`), so
    a clone left latched would make the NEXT note legato too. The base is
    written back on the first later row that would otherwise inherit the
    clone: the next note row with an empty column, or -- where no note
    follows in the pattern -- the row after the tie, as a re-latch (the
    spelling `_tied_instrument_envelopes` uses). A tie on the pattern's LAST
    row has no row after it, so that pattern ends on the clone: the base is
    written on row 0 of each successor pattern (`_pattern_successors`)
    whose first note would otherwise inherit it, or that names nothing and
    would pass it on (`_successor_relatch`). The orderlists are already
    written when this runs, so a successor cannot be copied: one also
    entered holding another instrument declines the tie instead.

    A row declines, and keeps the old spelling, where the instrument it
    plays cannot be settled (an empty column before any row names one, the
    pattern entered with two instruments -- the orderlists are fixed here,
    so the pattern cannot be split per entry), where that instrument has no
    record to clone (`cloneable`), where a last-row tie's successors cannot
    take the re-latch (no `tracks`; a successor entered holding another
    instrument; one that would pack past `PACKED_PATTERN_LIMIT`), or where
    the numbers run out: `last_number` defaults to `GT_MAX_INSTRUMENTS`
    (gcommon.h MAX_INSTR - 1). The log names each decline's reason."""
    last_number = last_number or GT_MAX_INSTRUMENTS
    entry = _entry_instruments(tracks, patterns) if tracks else {}
    successors = _pattern_successors(tracks, len(patterns)) if tracks else {}
    out = [list(p) for p in patterns]
    clone_of: dict = {}
    declined: set = set()
    why: dict = {}

    def decline(pn: int, r: int, reason: str) -> None:
        declined.add((pn, r))
        why[reason] = why.get(reason, 0) + 1

    for pn, pat in enumerate(out):
        mine = sorted(r for p, r in rows if p == pn)
        if not mine:
            continue
        n = len(pat) // 4
        held = entry.get(pn, set())
        live = next(iter(held)) if len(held) == 1 else 0
        want = set(mine)
        for r in range(n):
            k = r * 4
            if pat[k + 1]:
                live = pat[k + 1]
            if r not in want:
                continue
            base = live
            room = r + 1 < n and pat[k + 4] != 0xFF
            if not base:
                decline(pn, r, "entered with two instruments"
                        if len(held) > 1 else "instrument unsettled")
                continue
            if base not in cloneable:
                decline(pn, r, "no record to clone")
                continue
            onward: List[int] = []
            if not room:
                if not tracks:
                    decline(pn, r, "last row, no orderlists")
                    continue
                need, reason = _successor_relatch(out, pn, base, entry,
                                                  successors)
                if need is None:
                    decline(pn, r, f"last row, {reason}")
                    continue
                onward = need
            if base not in clone_of:
                number = first_number + len(clone_of)
                if number > last_number:
                    decline(pn, r, "instrument numbers run out")
                    continue
                clone_of[base] = number
            pat[k + 1] = clone_of[base]
            pat[k + 2] = pat[k + 3] = 0
            if not room:
                for q in onward:
                    out[q][1] = base
                continue
            # Put the base back before anything inherits the clone: on the
            # next note, or on the next row where no note follows -- unless
            # a later row names an instrument first.
            relatch: Optional[int] = r + 1
            for q in range(r + 1, n):
                c = q * 4
                if pat[c] == 0xFF:
                    break
                if pat[c + 1]:
                    relatch = None
                    break
                if GT_FIRST_NOTE <= pat[c] <= GT_LAST_NOTE:
                    relatch = q
                    break
            if relatch is not None:
                pat[relatch * 4 + 1] = base
    clones = sorted(((b, c) for b, c in clone_of.items()), key=lambda bc: bc[1])
    if log is not None and (clones or declined):
        log(f"Legato tie..............: "
            f"{len(rows) - len(declined)} tie row(s) on "
            f"{len(clones)} legato clone(s)"
            + (f", {len(declined)} kept CMD_TONEPORTA ("
               + "; ".join(f"{c} {w}" for w, c in sorted(why.items())) + ")"
               if declined else ""))
    return out, clones, declined


def _vibrato_command_pass(det: Detection, patterns: List[List[int]],
                          vib_ptrs: dict, lead: int, log=None,
                          tracks: Optional[List[List[int]]] = None) -> dict:
    """Move the global-triangle dialect's vibrato from the instrument to the
    pattern rows, which is the only way to express its per-note length gate.

    The player gates vibrato on the note's own stored duration and nothing
    else (§ 7.aaa, and _vibrato_delay for the disassembly):

        BD EF 14  LDA $14EF,X / AND #$1F / CMP #$08 / BCC out

    A Goattracker *instrument* cannot say that, because `vibdelay` is per
    instrument, so v0.5.198 measured the two ways of approximating it with one
    number and shipped the less-bad one: `vibdelay 8` suppresses short notes
    correctly and starts long ones 10 frames late. This is the exact form
    instead, and it works because of where gplay.c puts the delay countdown:

        case CMD_DONOTHING:
        if ((!cptr->cmddata) || (!cptr->vibdelay)) break;
        if (cptr->vibdelay > 1) { cptr->vibdelay--; break; }
        case CMD_VIBRATO:                      // <-- fallthrough target
        ...oscillate...

    The countdown lives *inside* `case CMD_DONOTHING`. A row carrying
    `CMD_VIBRATO` enters at the second label and never sees it, so a commanded
    vibrato runs from the note's first call whatever `vibdelay` holds. Set the
    instrument's `ptr[STBL]` to 0 and an *uncommanded* note takes the
    `!cmddata` break and gets nothing at all. Between them: vibrato on exactly
    the notes the player vibrates, starting where the player starts it.

    Three properties of the row stream make this a pass rather than a rewrite:

    * **The gate needs no unit conversion.** `_build_raw_pattern` emits `wait`
      hold rows after each note and `wait = b1 & 0x1F` is the identical
      expression to the player's `AND #$1F`, so a note occupies `wait + 1`
      rows and `wait >= 8` is exactly `rows > TRIANGLE_VIBRATO_GATE`. Nothing
      here depends on frames per row, on the tempo, or on the multiplier --
      which is why this is the one rate-like quantity in the file that is *not*
      scaled (contrast build_speed_table, _drum_speed, _wave_hold_byte).
    * **Hold rows already carry the note row's command** (`events += [GT_NO_NOTE,
      0x00, cmd1, cmd2]`), and an empty row would otherwise reset `cmddata`
      back to the instrument's zeroed pointer and stop the oscillation
      mid-note, so the command has to be on every row of the note -- and
      writing it there matches what the decoder does with a portamento.
    * **`$BD` is "no new note", not a rest.** gplay.c:925 only assigns
      `newnote` for `<= LASTNOTE`, so a `$BD` row continues the note and is
      safe to treat as part of its block.

    **A short note is damped explicitly, and the instrument keeps its pointer.**
    `$04 00` gives `cmddata = 0`, which still enters `case CMD_VIBRATO` but with
    `cmpvalue` and `speed` both 0, so it adds nothing to the frequency -- a
    suppression that costs no extra state and, unlike zeroing `ptr[STBL]`,
    applies per note. Keeping the pointer then means a note this pass *cannot*
    reach falls back to the v0.5.198 approximation rather than losing its
    vibrato outright. Measured over the 25 files and 2487 notes of § 7.kkk,
    the three combinations separate cleanly:

        variant                    agree   miss  invent   onset (median)
        instrument vibdelay 8      85.5%    153     207              +10
        command, ptr[STBL] = 0     88.9%    212      63               +0
        command, pointer kept      85.6%    152     207               +0

    Zeroing the pointer removes 144 spurious vibratos -- notes lasting more
    than 8 *calls* whose player duration is under 8 *frames*, which a delay
    cannot distinguish and this gate can -- but costs 60 notes that qualify and
    could not be commanded. Damping short notes explicitly gets both, which is
    what this function does.

    **The threshold is the file's own `CMP`, not TRIANGLE_VIBRATO_GATE.** Those
    three rows were all measured against the assumed 8, and on Commando that
    damped 695 of 705 notes and vibrated 10 -- the constant was read from one
    player and 5 of the 25 compare against something else (Commando 6, then 5,
    4, 4, 2; detect._find_triangle_gate). With its own 6 the file vibrates 50
    notes and scores 100.0% where the instrument delay scored 97.8%, and the
    arithmetic is checkable rather than fitted: `wait >= 6` selects the 24- and
    30-frame notes, of which GT 1 has 27 + 4 = 31, exactly the 31 notes the
    original is measured to vibrate. Corpus-wide, with the right threshold:

        delay, gate 8 (v0.5.198)   85.5%   miss 153   invent 207   onset +10
        delay, per-file gate       78.9%   miss 109   invent 417   onset +10
        command + damp             92.1%   miss 129   invent  68   onset  +0

    -- better on *both* axes than either delay, which no single `vibdelay` could
    manage, and better on 6 files than the middle row is on any. The second row
    is the warning: the per-file gate is an improvement here and a regression as
    a plain delay. See `_vibrato_delay`.

    **The live instrument is carried across the orderlist.** Before any row
    of a pattern names an instrument, the channel holds what the orderlists
    carried INTO it (`_entry_instruments`, the walk `_tied_instrument_envelopes`
    already uses, and the state `fidelity.triangle_gate_records` and
    `patterns._entry_instruments` carry for the same reason: the instrument
    register is sticky in both players, gplay.c:914) -- taken only when every
    orderlist entry into the pattern agrees. A per-pattern reset was the
    whole of Commodore_64_Music_Examples' vibrato: its long notes sit in
    patterns that name no instrument, and the log read `0 note(s) vibrated,
    512 damped by length, 43 with the column in use, 31 on an unnamed
    instrument` while the original oscillates on all nine vibrato records.

    Skipped, and counted rather than silently dropped: a note whose command
    column is already spoken for (a portamento or a tempo change -- one column
    per row, and the slide is the more audible of the two), and a *qualifying*
    note whose live instrument is not known because no row has named one yet in
    this pattern and the orderlists do not settle it (no `tracks`, or two
    entries disagreeing). A short note needs no index to damp, so an unnamed
    instrument does not stop it.

    **A long note on a KNOWN instrument with no vibrato record is neither.**
    Its instrument is named; `_vibrato_layout` gave it no entry (most often
    a zero shift byte, the player's own `BEQ past` in
    `_triangle_vibrato_entry`), so there is no depth to command.
    It is counted on its own (`plain`), never as unnamed: lumping it in
    told Commodore_64_Music_Examples' reader three of its 16 "unnamed"
    notes were unresolved when they sit on instrument 04, whose shift byte
    is $00. Like the unnamed ones it is written nothing, so the split moves
    only the log.
    """
    gate = det.triangle_gate or TRIANGLE_VIBRATO_GATE
    by_slot = {rec + 1 + lead: idx for rec, (idx, _delay) in vib_ptrs.items()}
    placed = damped = busy = unknown = plain = 0
    entry = _entry_instruments(tracks, patterns) if tracks else {}
    for pn, pat in enumerate(patterns):
        held = entry.get(pn, set())
        live = next(iter(held)) if len(held) == 1 else 0
        i = 0
        while i + 3 < len(pat):
            note, instr = pat[i], pat[i + 1]
            if instr:
                live = instr
            if not GT_FIRST_NOTE <= note <= GT_LAST_NOTE:
                i += 4
                continue
            end = i + 4
            # `_tied_instrument_envelopes`' SR row after a tie names the
            # instrument already live -- a re-latch, gplay.c:912 storing the
            # same value -- and changes nothing for the player, so it is
            # part of the note's block. Only that row: a rest naming the
            # live instrument by other means is an event of its own.
            while (end + 3 < len(pat) and pat[end] == GT_REST
                   and (pat[end + 1] == 0
                        or (pat[end + 1] == live
                            and pat[end + 2] == CMD_SETSR))):
                end += 4
            index = 0
            if (end - i) // 4 > gate:
                index = by_slot.get(live, -1)
            if index < 0:
                if live:
                    plain += 1
                else:
                    unknown += 1
            else:
                # Only the free rows, so a portamento or a tempo change keeps
                # the column -- and a note whose *own* row is taken still gets
                # the vibrato on the rest of its block rather than none at all.
                # A tie emits CMD_TONEPORTA on the landing row (patterns.py),
                # and the original starts oscillating a frame or two into that
                # note, so filling from the next row is also what it does.
                for row in range(i, end, 4):
                    if pat[row + 2] == 0:
                        pat[row + 2] = CMD_VIBRATO
                        pat[row + 3] = index
                if pat[i + 2] != CMD_VIBRATO:
                    busy += 1
                elif index:
                    placed += 1
                else:
                    damped += 1
            i = end
    if log and (placed or damped):
        log(f"Vibrato command.........: {placed} note(s) vibrated, "
            f"{damped} damped by length"
            + (f", {busy} with the column in use" if busy else "")
            + (f", {unknown} on an unnamed instrument" if unknown else "")
            + (f", {plain} long on an instrument with no vibrato"
               if plain else ""))
    return vib_ptrs


def _attack_hold_records(sid: SidFile, det: Detection, instr_used: int,
                         lead: int, effects: bool, two_stage: bool) -> list:
    """Records whose fixed attack pitch the player holds on SOME notes only.

    The handler hands the frequency to the vibrato after the countdown
    (`_fixed_pitch_yield_field`) and the vibrato is a duration-gated one
    (`detect.VibratoGate` form "duration"): a note at least `gate` long
    vibrates from the note's own pitch, and a shorter one is never written
    again, so it keeps the attack pitch to its end. Sanxion's record 13
    (`$44`, +5 = `$10`): 87 short notes in 100 s hold C#6 from N+1 to the
    next attack in the original, and 17 long ones vibrate around the note
    from N+2. One wavetable cannot say both, so the record keeps its own
    program (the restore, right for the long notes) and these get a second
    one for `_attack_hold_pass` to point the short notes at.

    Only `$44` records without `$80`: the two-stage path is the one that
    emits the fixed pitch on such a record (`_wavetable_entries`), and
    `_wavetable_layout` drops any record whose held block comes out the same.
    """
    vg = det.vibrato_gate
    if (not effects or not two_stage or not det.effect_bit40
            or det.vibrato_offset is None or vg is None
            or vg.form != "duration" or vg.gate is None):
        return []
    if _fixed_pitch_yield_field(sid, det) != det.vibrato_offset:
        return []
    out = []
    for i in range(max(instr_used - lead, 0)):
        base = det.instr_start + i * det.instr_stride
        if base + 7 >= len(sid.data):
            break
        effect = sid.data[base + 7]
        if ((effect & 0x44) == 0x44 and not effect & EFFECT_SFX_DRUM_MASK
                and sid.data[base + det.vibrato_offset]):
            out.append(i)
    return out


def _successor_heads(tracks: List[List[int]],
                     patterns: List[List[int]]) -> dict:
    """Pattern number -> the first rows the orderlists play right after it.

    Walked like `_entry_instruments` (repeats honoured, transposes skipped).
    The last pattern before an orderlist's `$FF` gets `None`: the restart
    target is an operand this walk does not follow, so what plays next is
    not known here.
    """
    heads: dict = {}
    for track in tracks:
        seq, repeat = [], 1
        for b in track:
            if b == 0xFF:
                break
            if 0xE0 <= b < 0xFF:
                continue
            if 0xD0 <= b < 0xE0:
                repeat = b - 0xD0 + 1
                continue
            if b < len(patterns):
                seq += [b] * repeat
            repeat = 1
        for a, b in zip(seq, seq[1:]):
            heads.setdefault(a, set()).add(tuple(patterns[b][:4]))
        if seq:
            heads.setdefault(seq[-1], set()).add(None)
    return heads


def _predecessor_tails(tracks: List[List[int]],
                       patterns: List[List[int]]) -> dict:
    """Pattern number -> the LAST rows the orderlists play right before it;
    `_successor_heads` turned round.

    Walked the same way (repeats honoured, transposes skipped). An
    orderlist's first pattern gets `SONG_START_ROW`; the pattern the restart
    operand lands on also gets the last pattern before `$FF`, because the
    loop plays that one right before it. The operand is a byte position
    (player.s `mt_sequencer`: `LDA (seq),Y` again at the operand's index, so
    a transpose or repeat byte there still plays the pattern after it); one
    that lands on no pattern gives every pattern of that orderlist `None`,
    unknown, rather than guessing which one the loop re-enters.
    """
    def last_row(p: int):
        pat = patterns[p]
        r = 0
        while r + 3 < len(pat) and pat[r] != 0xFF:
            r += 4
        return tuple(pat[r - 4:r]) if r else None

    tails: dict = {}
    for track in tracks:
        seq, groups, repeat, group_start = [], [], 1, None
        restart = None
        for pos, b in enumerate(track):
            if b == 0xFF:
                restart = track[pos + 1] if pos + 1 < len(track) else None
                break
            if group_start is None:
                group_start = pos
            if 0xE0 <= b < 0xFF:
                continue
            if 0xD0 <= b < 0xE0:
                repeat = b - 0xD0 + 1
                continue
            if b < len(patterns):
                groups.append((group_start, pos, len(seq)))
                seq += [b] * repeat
            repeat, group_start = 1, None
        if not seq:
            continue
        tails.setdefault(seq[0], set()).add(SONG_START_ROW)
        for a, b in zip(seq, seq[1:]):
            tails.setdefault(b, set()).add(last_row(a))
        landing = [k for first, pat_pos, k in groups
                   if restart is not None and first <= restart <= pat_pos]
        if landing:
            tails.setdefault(seq[landing[0]], set()).add(last_row(seq[-1]))
        else:
            for p in seq:
                tails.setdefault(p, set()).add(None)
    return tails


def _held_to_attack(pat: List[int], end: int, gate: int,
                    heads: set) -> bool:
    """Whether a short note whose block ends at row offset `end` keeps the
    attack pitch until a new note's attack writes over it.

    The player writes nothing after the fixed pitch on such a record except
    its vibrato, and the vibrato's gate is read PER EVENT -- a rest included.
    So the hold lasts across every following event no longer than `gate`
    rows and ends at the first that is longer, where the vibrato starts on
    the old note's pitch: Sanxion's voice 3 at 4405, a 6-frame note then a
    long rest, holds C#6 for seven frames and then vibrates around the note
    (`$1A13`) through the release; a hold here kept C#6 under Goattracker's
    vibrato for the other 46 frames (C:/t/sanxion-c-sharp-6-hold,
    2026-10-01). True only where the walk reaches a new note that is not a
    tie's landing (`CMD_TONEPORTA`); a rest row the block stopped on because
    it carries something (a tied instrument change) is a continuation, and
    False. Across the pattern's end every successor's first row must say so
    (`_successor_heads`), and an unknown successor is False.
    """
    while True:
        if end + 3 >= len(pat) or pat[end] == 0xFF:
            return bool(heads) and all(
                h is not None and GT_FIRST_NOTE <= h[0] <= GT_LAST_NOTE
                and h[2] != CMD_TONEPORTA for h in heads)
        row = pat[end]
        if GT_FIRST_NOTE <= row <= GT_LAST_NOTE:
            return pat[end + 2] != CMD_TONEPORTA
        if row == GT_REST:
            return False
        nxt = end + 4
        while nxt + 3 < len(pat) and pat[nxt] == GT_REST and not pat[nxt + 1]:
            nxt += 4
        if (nxt - end) // 4 > gate:
            return False
        end = nxt


def _attack_hold_pass(patterns: List[List[int]], targets: dict, gate: int,
                      tracks: Optional[List[List[int]]] = None,
                      log=None, used: Optional[set] = None) -> List[List[int]]:
    """`CMD_SETWAVEPTR` to the held-attack program on each note of a
    `targets` instrument SHORTER than the vibrato's duration gate.

    `targets` maps a Goattracker instrument number to the wavetable row of
    its `_attack_hold_records` program. The test is the one
    `_vibrato_command_pass` makes for the same kind of gate -- a note
    occupies `wait + 1` rows and `wait` is the player's own `AND #$1F`
    duration -- turned round: rows `<= gate` is a note the player never
    vibrates, so the attack pitch is all it ever writes after the note.

    The note keeps the instrument's own program wherever this cannot place
    the command, which is what every note had before; counted, not dropped
    silently:

    * **busy**: the note row's command column is taken, or the row before
      it in the pattern carries any command. `CMD_SETWAVEPTR` does not
      reset the channel's running effect (gplay.c:436-438 sets only the
      wave pointer; player.s `mt_tick0_8` the same), so a portamento on the
      row before would carry into the note. Row 0's row before is the last
      row of every pattern the orderlists play ahead of it
      (`_predecessor_tails`), read once every other row is placed; one
      unknown predecessor makes it busy, and so does a one-row pattern,
      whose row 0 is a row before for its successors. Row 0 is also the row
      a subtune's `CMD_SETTEMPO` owns, but `apply_tempos` has written it by
      now (convert.py, before `build_sng`), so an occupied column is busy
      here and a free one costs no subtune its clock -- and
      `CMD_SETWAVEPTR` is in `patterns.TEMPO_OVERWRITABLE` in any case.
    * **unknown**: no row of this pattern has named the instrument yet and
      the orderlists enter the pattern holding more than one
      (`_entry_instruments`; Sanxion names the instrument once and carries
      it across patterns, so without the walk 59 of the 61 short notes went
      here).
    * **tied**: nothing says the next write is a new attack
      (`_held_to_attack`).
    * **over**: the command would pack the pattern past
      `PACKED_PATTERN_LIMIT` (greloc.c packpattern).

    Changed patterns are COPIES, as in `budget_pulse_phase_commands`.
    `used`, where given, collects the instrument numbers that got at least
    one command: `build_sng` runs this once before the wavetable is laid
    out, so a held program no note would point at is never written.
    """
    if not targets:
        return patterns
    entry = _entry_instruments(tracks, patterns) if tracks else {}
    heads = _successor_heads(tracks, patterns) if tracks else {}
    out: List[List[int]] = []
    row0: List[tuple] = []
    placed = busy = unknown = over = tied = 0
    for number, pat in enumerate(patterns):
        copy = None
        held = entry.get(number, ())
        live = next(iter(held)) if len(held) == 1 else 0
        ambiguous = len(held) > 1 and any(h in targets for h in held)
        i = 0
        while i + 3 < len(pat):
            note, instr = pat[i], pat[i + 1]
            if instr:
                live = instr
            if not GT_FIRST_NOTE <= note <= GT_LAST_NOTE:
                i += 4
                continue
            end = i + 4
            while (end + 3 < len(pat) and pat[end] == GT_REST
                   and (pat[end + 1] == 0
                        or (pat[end + 1] == live
                            and pat[end + 2] == CMD_SETSR))):
                end += 4
            if (end - i) // 4 > gate:
                i = end
                continue
            if live not in targets:
                unknown += 1 if not live and ambiguous else 0
                i = end
                continue
            if not _held_to_attack(pat, end, gate, heads.get(number, {None})):
                tied += 1
                i = end
                continue
            cur = copy if copy is not None else pat
            if cur[i + 2] or cur[i + 3] or (i and cur[i - 2]):
                busy += 1
                i = end
                continue
            if i == 0:
                row0.append((number, live))
                i = end
                continue
            trial = list(cur)
            trial[i + 2] = CMD_SETWAVEPTR
            trial[i + 3] = targets[live] & 0xFF
            if packed_pattern_size(pattern_rows(trial)) > PACKED_PATTERN_LIMIT:
                over += 1
            else:
                copy = trial
                placed += 1
                if used is not None:
                    used.add(live)
            i = end
        out.append(pat if copy is None else copy)
    # Row 0 last, against the finished rows: no placement below changes a
    # tail, because a one-row pattern (row 0 IS its tail) is refused.
    tails = _predecessor_tails(tracks, out) if row0 and tracks else {}
    for number, live in row0:
        cur = out[number]
        before = tails.get(number, {None})
        if (len(cur) < 9 or cur[4] == 0xFF
                or any(t is None or (t and t[2]) for t in before)):
            busy += 1
            continue
        trial = list(cur)
        trial[2] = CMD_SETWAVEPTR
        trial[3] = targets[live] & 0xFF
        if packed_pattern_size(pattern_rows(trial)) > PACKED_PATTERN_LIMIT:
            over += 1
            continue
        out[number] = trial
        placed += 1
        if used is not None:
            used.add(live)
    if log and (placed or busy or unknown or over or tied):
        log(f"Attack pitch held.......: {placed} short note(s) keep the $40 "
            f"pitch (vibrato gate {gate})"
            + (f", {busy} with the column in use" if busy else "")
            + (f", {tied} running on past their block" if tied else "")
            + (f", {unknown} short note(s) of an instrument not yet named "
               "in their pattern" if unknown else "")
            + (f", {over} over the pack limit" if over else ""))
    return out


# --- Past-table drum: a `$0000` note whose wave program still sounds ----------
#
# `patterns.past_table_rests` reads a note byte that indexes past the player's
# frequency table onto a constant `$0000` cell, and the decoder emits it as a
# KEYOFF -- the only KEYOFF it ever writes WITH an instrument column (the
# `rest_keyoff` rest, the pre-instrument silencing and the end-of-tune parks
# all write `00` there). But the original's event is an ordinary note-on at
# frequency `$0000`: the gate rises, the pulse reseeds and the instrument's
# wave program runs, and any frame of that program that sets an ABSOLUTE
# pitch is heard whatever the note was. Sanxion's record 0 is `41 / 81 at
# absolute B-5 / 41 / stop`: siddump's third voice shows `0000 C-0 41` then
# `41B8 (B-5 C7) 81` at each of the six drum patterns' row 20, 41 times in
# 100 s (frame 645 first), and the KEYOFF sounded none of them
# (C:/t/sanxion-noise-drum, 2026-10-02).
#
# Goattracker cannot play a frequency of `$0000` from a note, but it does not
# need to: every frame the note's pitch reaches is DC in the original, so a
# variant of the instrument whose pitched frames are test-bit silence and
# whose absolute frames are kept says the same thing with any note. The
# variant is a CLONE RECORD (envelope, pulse, filter, vibrato, gate timer and
# firstwave all the record's -- the note-on reseeds the pulse exactly as the
# original's does) with its own wavetable block.

def _past_table_drum_block(entries: List[tuple],
                           start: int) -> Optional[List[tuple]]:
    """The record's wave program at row `start` with every frame the NOTE
    pitches turned to test-bit silence; or None. It stops (`$FF 00`), so it
    reads the same wherever it is placed.

    Walked frame by frame like `gplay.c` WAVEEXEC (:515-725): a waveform
    byte latches (`$E0`-`$EF` its low nibble), a delay or `$00` keeps the
    latched one, the right side writes the note's frequency below `$80`, an
    absolute one above it, and `$80` keeps whichever was last written. A
    frame whose latched waveform selects an oscillator without the test bit
    is AUDIBLE; an audible frame on the note's own pitch becomes the test
    bit with the frame's gate bit kept (`$09` for `$41`, so the envelope runs
    exactly as the original's gate does), and an audible frame on an
    absolute pitch is kept. None -- the instrument keeps the KEYOFF -- where:

    * no audible absolute frame survives: the variant would be silence,
      which is what the KEYOFF already says;
    * a delay (or `$00`) entry would need its waveform changed, which only a
      waveform byte can do and which would drop the delay;
    * the program loops (`$FF` to a non-zero row) -- a second pass through
      the loop can enter with a different pitch, and this walks once;
    * nothing stops it within the table.
    """
    out: List[tuple] = []
    wave: Optional[int] = None
    absolute = False
    kept = False
    row = start
    while 1 <= row <= len(entries) and len(out) < _gw_constants.GT_MAX_TABLELEN:
        left, right = entries[row - 1]
        if left == GT_WAVE_JUMP:
            if right:
                return None
            out.append((left, right))
            return out if kept else None
        if GT_WAVE_FIRST_CMD <= left <= GT_WAVE_LAST_CMD:
            out.append((left, right))
            row += 1
            continue
        if left > GT_WAVE_LAST_DELAY:
            wave = left if left < WAVE_SILENT_BASE else left & 0x0F
        if right != GT_WAVE_NO_NOTE:
            absolute = right > GT_WAVE_NO_NOTE
        audible = (wave is not None and wave & 0xF0
                   and not wave & WAVE_TEST_BIT)
        if audible and not absolute:
            if left <= GT_WAVE_LAST_DELAY:
                return None
            wave = WAVE_TEST_BIT | (wave & WAVE_GATE_BIT)
            left = _wave_byte(wave)
        elif audible:
            kept = True
        out.append((left, right))
        row += 1
    return None


def _orderlist_min_transpose(tracks: List[List[int]]) -> dict:
    """Pattern number -> the lowest orderlist transpose any track plays it
    under (0 or below). `$E0`-`$FE` set the channel's transpose to
    `byte - $F0` (gcommon.h TRANSDOWN/TRANSUP, gplay.c:977-979) and it holds
    until the next one, so the walk carries it; the restart is not followed,
    and a transpose set before the restart point is carried into the rest
    of the track, which can only lower the minimum."""
    low: dict = {}
    for track in tracks:
        trans = 0
        for b in track:
            if b == 0xFF:
                break
            if 0xE0 <= b < 0xFF:
                trans = b - 0xF0
                continue
            if 0xD0 <= b < 0xE0:
                continue
            low[b] = min(low.get(b, 0), trans)
    return low


def past_table_drum_plan(sid: SidFile, det: Detection,
                         patterns: List[List[int]],
                         tracks: List[List[int]],
                         wave_entries: List[tuple], wave_starts: List[int],
                         lead: int, instr_used: int, first_number: int,
                         log=None) -> tuple:
    """(patterns, variants): each past-table rest row on an instrument whose
    wave program sounds an absolute-pitch frame, re-emitted as a note on a
    variant of that instrument (`_past_table_drum_block`).

    `variants` is a list of (record GT number, variant GT number, block),
    variant numbers counting up from `first_number`; the caller appends each
    block to the wavetable and each clone record after the others. A row
    is a KEYOFF carrying a written instrument's number, in a file where
    `patterns.past_table_rests` reads anything at all -- nothing else
    emits that shape, and a file with no past-table rest byte is returned
    untouched, so the reach is exactly the rule's.

    The note is C-0 lifted by the lowest orderlist transpose that plays the
    pattern (`_orderlist_min_transpose`), so it is a real note however the
    pattern is transposed; which note it is does not matter, because every
    frame it pitches is test-bit silence. C-0 is also what siddump names the
    original's `$0000`.

    The variant's number latches for the voice (gplay.c:912-913), so the
    record must be named again before the voice's next note: the first row
    after the drum that carries an instrument must come before -- or be --
    the next note, or that note gets the record's number written into its
    instrument column. A drum with no such row left in its pattern keeps
    the KEYOFF (`unlatched`), as does a row whose pattern would pack past
    `PACKED_PATTERN_LIMIT` (`over`). Changed patterns are COPIES.
    """
    from ..patterns import past_table_rests
    if not past_table_rests(sid, det):
        return patterns, []
    rows = [(n, k) for n, pat in enumerate(patterns)
            for k in range(0, len(pat) - 3, 4)
            if pat[k] == GT_KEYOFF and lead < pat[k + 1] <= instr_used]
    if not rows:
        return patterns, []
    variants: List[tuple] = []
    number: dict = {}
    room = _gw_constants.GT_MAX_TABLELEN - len(wave_entries)
    declined: List[int] = []
    for record in sorted({patterns[n][k + 1] for n, k in rows}):
        vnum = first_number + len(variants)
        block = (_past_table_drum_block(wave_entries, wave_starts[record - 1])
                 if record - 1 < len(wave_starts) else None)
        if (block is None or len(block) > room
                or vnum > TEMPO_DUTY_MAX_CLONE):
            declined.append(record)
            continue
        room -= len(block)
        number[record] = vnum
        variants.append((record, vnum, block))
    low = _orderlist_min_transpose(tracks)
    out = [list(p) for p in patterns]
    placed = unlatched = over = 0
    for n, k in rows:
        pat = out[n]
        record = pat[k + 1]
        if record not in number:
            continue
        trial = list(pat)
        trial[k] = GT_FIRST_NOTE - low.get(n, 0)
        trial[k + 1] = number[record]
        latch = None
        for j in range(k + 4, len(trial) - 3, 4):
            if trial[j] == 0xFF:
                break
            if trial[j + 1]:
                latch = j
                break
            if GT_FIRST_NOTE <= trial[j] <= GT_LAST_NOTE:
                trial[j + 1] = record
                latch = j
                break
        if latch is None or trial[k] > GT_LAST_NOTE:
            unlatched += 1
            continue
        if packed_pattern_size(pattern_rows(trial)) > PACKED_PATTERN_LIMIT:
            over += 1
            continue
        out[n] = trial
        placed += 1
    used = {r for r in number if any(
        out[n][k + 1] == number[r] for n, k in rows)}
    if len(used) != len(variants):
        # A variant no row kept is never written: renumber what is left.
        keep = [(r, v, b) for r, v, b in variants if r in used]
        remap = {v: first_number + i for i, (_, v, _) in enumerate(keep)}
        for n, k in rows:
            if out[n][k + 1] in remap:
                out[n][k + 1] = remap[out[n][k + 1]]
        variants = [(r, remap[v], b) for r, v, b in keep]
    out = [patterns[i] if out[i] == patterns[i] else out[i]
           for i in range(len(out))]
    if log and (placed or unlatched or over or declined):
        log(f"Past-table drum.........: {placed} $0000 note(s) sound their "
            f"absolute-pitch frame on {len(variants)} variant instrument(s)"
            + (f", {unlatched} with no row to name the record again"
               if unlatched else "")
            + (f", {over} over the pack limit" if over else "")
            + (f"; record(s) {', '.join(f'${r:02X}' for r in declined)} "
               "keep the KEYOFF (no absolute frame, or no room)"
               if declined else ""))
    return out, variants


def _expanding_vibrato_counter(sid: SidFile, det: Detection) -> Optional[int]:
    """Address of the frame counter the vibrato step grows with, or None.

    None for the static family and for anything that does not check out:
    the note table the loop reads must be the one `find_freq_table`
    validated (the same operand, so the intervals below are the player's
    own), and the counter must be one the player increments somewhere
    (`INC abs,X` / `INC zp,X`) -- a routine adding something it never
    counts up is not this mechanism, whatever its opcodes say.
    """
    if det.vibrato_offset is None or det.freq_table is None:
        return None
    data = sid.data
    for shape in EXPANDING_VIBRATO_SHAPES:
        at = search_file(data, shape)
        if at < 0:
            continue
        table = data[at + EXPANDING_VIBRATO_TABLE_AT] \
            | (data[at + EXPANDING_VIBRATO_TABLE_AT + 1] << 8)
        if table != det.freq_table.addr:
            continue
        zero_page = data[at + EXPANDING_VIBRATO_COUNTER_AT] == 0x75
        if zero_page:
            counter = data[at + EXPANDING_VIBRATO_COUNTER_AT + 1]
            inc = "F6 %02X" % counter
        else:
            counter = data[at + EXPANDING_VIBRATO_COUNTER_AT + 1] \
                | (data[at + EXPANDING_VIBRATO_COUNTER_AT + 2] << 8)
            inc = "FE %02X %02X" % (counter & 0xFF, counter >> 8)
        if search_file(data, inc) < 0:
            continue
        return counter
    return None


def _expanding_vibrato_step(hi: int, lo: int, age: int, shift: int) -> int:
    """The player's per-frame step `age` frames into a note, in SID units.

    `hi:lo` is `freq(note) - freq(note - 1)` from the player's own table.
    The carry into the ADC is the SBC's, set because the interval is
    positive, so the high byte becomes `hi + age + 1`; the `LSR A` before
    the shift loop halves it with bit 0 falling off the end rather than
    into the low byte; and the loop then shifts the 16-bit pair `shift`
    times. Eight-bit arithmetic throughout: a note held past 255 frames
    wraps, as the counter does.
    """
    a = ((hi + age + 1) & 0xFF) >> 1
    return ((a << 8) | (lo & 0xFF)) >> shift


def _player_interval(sid: SidFile, det: Detection,
                     gt_note: int) -> Optional[Tuple[int, int]]:
    """`(hi, lo)` of the player's semitone interval below Goattracker note
    index `gt_note`, read from its own table; None off the table's end.

    `FreqTable.shift` is what a player note is offset by to name the same
    pitch in Goattracker, so the player's entry is `gt_note - shift`, and the
    loop reads that entry and the one below it.
    """
    ft = det.freq_table
    if ft is None:
        return None
    n = gt_note - ft.shift
    if n < max(1, ft.start + 1) or n >= ft.length:
        return None
    off = sid.to_offset(ft.addr) + 2 * n
    if off - 2 < 0 or off + 1 >= len(sid.data):
        return None
    d = sid.data
    here = d[off] | (d[off + 1] << 8)
    below = d[off - 2] | (d[off - 1] << 8)
    if here <= below:
        return None
    ivl = here - below
    return ivl >> 8, ivl & 0xFF


def _expanding_vibrato_level(target: float, gt_note: int, cmp_value: int,
                             base: int) -> int:
    """The note-relative shift whose swing is nearest `target` in log space.

    Goattracker's peak-to-peak is `(cmp + 2)` steps of `interval >> shift`,
    the interval being the one ABOVE the note (player.s `mt_calculatedspeed`
    reads `freqtbl+1 - freqtbl`). Compared in log space because 2.0x and
    0.5x are the same size of wrong (CLAUDE.md); ties go to the shallower
    entry, which is the instrument's own level wherever that is a candidate.
    """
    ivl = _note_freq(gt_note + 1) - _note_freq(gt_note)
    if target <= 0 or ivl <= 0:
        return base
    best, err = base, None
    for s in range(GT_MAX_VIB_SHIFT, -1, -1):     # shallowest first
        step = ivl >> s
        if step <= 0:
            continue
        e = abs(math.log((cmp_value + 2) * step) - math.log(target))
        if err is None or e < err - 1e-9:
            best, err = s, e
    return best


def _expanding_vibrato_pass(sid: SidFile, det: Detection,
                            tracks: List[List[int]],
                            patterns: List[List[int]], vib_ptrs: dict,
                            speed_table: List[tuple], lead: int,
                            multiplier: int, row_calls: int,
                            instr_row_calls: Optional[dict] = None,
                            log=None) -> int:
    """Write the age-growing depth onto the rows after a note, as `4xy`.

    Walked along the orderlists, not pattern by pattern, because the age is
    the player's and not the pattern's: the counter is zeroed by a note
    fetch and by nothing else, so a swell runs on through the key-off, the
    rest rows after it, and the pattern boundary -- BMX_Kidz's longest
    $0878 note gates off at frame 9, silences its envelope at 12 and is
    still widening 417 frames later, two patterns on, and a hundred of the
    original's 305 measured cycles are in that one tail. Each row after the
    note row covers `row_calls / multiplier` frames of age; the original's
    swing over them is `bound * step(age)` averaged across the row, and the
    row wants the speed-table entry (the instrument's own `cmp`, the shift
    from `_expanding_vibrato_level`) whose swing is nearest. Rows still at
    the instrument's own level want nothing until the first row that is
    not -- after which every row of the block wants a command, because an
    empty command column resets the channel to the instrument's pointer
    (gplay.c's CMD_DONOTHING case) and the level would fall back to the
    shallowest step mid-swell.

    **Patterns are global and orderlists are per subtune** (CLAUDE.md), so
    a row is written only when every orderlist context that reaches it
    wants the same entry: a pattern that voice 1 plays on the swelling
    instrument and voice 2 on a plain one gets no command on the rows the
    two disagree about, since a `4xy` vibrates whatever instrument is
    sounding. Two passes for that reason -- collect what each context
    wants per (pattern, row), then write the unanimous rows into free
    columns. The note row itself is never commanded: the instrument's
    `vibdelay` keeps the oscillator off the attack frame (`_vibrato_delay`),
    which is what keeps the note's name intact for siddump and the melody
    column, and the first frames are at the instrument's level anyway.

    An orderlist transpose is applied to the note before the interval is
    read (the age term is pitch-independent, the interval is not); a repeat
    replays the pattern with the age running on, as the player's would. The
    row length is the instrument's shortest (`instr_row_calls`, else the
    file's), which under-counts the age in a slower subtune. Skipped and
    counted: rows the contexts disagree on, rows whose command column is
    taken (one column per row, and a portamento or a tempo change is the
    more audible loss), notes off the player's table, and a full speed
    table. Returns the number of rows written.

    **What the columns say, and what they cannot** (v0.5.487 tree, -t 180,
    presets, the five files): `depth` 0.195 -> 0.393 on BMX_Kidz, 0.06 ->
    0.43 Arcade_Classics, 0.07 -> 0.89 Mega_Apocalypse, 0.12 -> 0.49
    Ricochet, 0.15 -> 0.67 Skate_or_Die_intro, and `bend` toward 1.0 on all
    five (0.44 -> 1.05, 0.51 -> 1.17, 0.33 -> 0.79, 0.28 -> 0.83, 0.21 ->
    0.27). Two things bound `depth` short of 1.0 and neither is a knob
    here. Goattracker's deepest note-relative step is the whole interval,
    so a swing the original grows past three semitones saturates at
    `(cmp + 2)` intervals; and the column measures every cycle to the next
    attack, so on BMX_Kidz 248 of the original's 305 cycles are in tails
    whose envelope the rest has already zeroed (57 cycles sound), and the
    longest of those tails runs into a rest pattern every voice shares,
    where the orderlists disagree and nothing can be written. Over the 57
    audible cycles the ratio reads 0.62 before and 1.22 after -- the
    power-of-two rounding's own floor. **Arcade_Classics's `melody` reads
    99% -> 92% and it is the naming artefact the harness documents**, not
    a wrong note: both sides' attack frames still carry the PREVIOUS note's
    swinging pitch (the original's for four frames, ours for one), and a
    deeper swing there renames it. Naming every attack from five frames in
    instead, base and this read identically against the original -- 0.995,
    0.998, 0.994 per voice on that file -- and the attack counts are
    unchanged (1032 / 1030).
    """
    if not vib_ptrs or row_calls < 1:
        return 0
    mult = max(1, multiplier)
    data = sid.data
    by_slot: dict = {}
    for rec, (idx, _delay) in vib_ptrs.items():
        base = det.instr_start + rec * det.instr_stride + det.vibrato_offset
        if not 1 <= idx <= len(speed_table) or base >= len(data):
            continue
        byte = data[base]
        bound = (byte & VIBRATO_BOUND_MASK) >> VIBRATO_BOUND_SHIFT
        if not bound:
            continue
        left, right = speed_table[idx - 1]
        if not left & SPEED_NOTE_RELATIVE:
            continue
        by_slot[rec + 1 + lead] = (bound, byte & VIBRATO_SHIFT_MASK,
                                   left & ~SPEED_NOTE_RELATIVE, right)
    if not by_slot:
        return 0
    # (pattern, row) -> the set of entries the contexts reaching it want;
    # None is "nothing", and a row wanted as None by any context is left.
    wants: dict = {}
    off_table = 0
    for track in tracks:
        live, transpose, repeat, operand = 0, 0, 1, False
        block = None        # (bound, shift, cmp, base, hi, lo, frames, k, on)
        for b in track:
            if operand:                  # $FF's restart position
                operand = False
                continue
            if b == 0xFF:                # patterns.GT_ORDER_RESTART
                operand = True
                continue
            if 0xE0 <= b < 0xFF:         # patterns.GT_TRANSPOSE_DOWN/UP
                transpose = b - 0xF0
                continue
            if 0xD0 <= b < 0xE0:         # patterns.GT_REPEAT: the NEXT entry
                repeat = b - 0xD0 + 1
                continue
            if b >= len(patterns):
                continue
            pat = patterns[b]
            for _ in range(repeat):
                for r in range(0, len(pat) - 3, 4):
                    note, instr = pat[r], pat[r + 1]
                    if note == 0xFF:     # ENDPATT, patterns.GT_END_PATTERN
                        break
                    key = (b, r)
                    if GT_FIRST_NOTE <= note <= GT_LAST_NOTE:
                        if instr:
                            live = instr
                        block = None
                        wants.setdefault(key, set()).add(None)
                        if live not in by_slot:
                            continue
                        bound, shift, cmp_value, base = by_slot[live]
                        gt_note = note - GT_FIRST_NOTE + transpose
                        ivl = _player_interval(sid, det, gt_note)
                        if ivl is None:
                            off_table += 1
                            continue
                        frames = max(1, ((instr_row_calls or {}).get(live)
                                         or row_calls) // mult)
                        block = [bound, shift, cmp_value, base, ivl[0],
                                 ivl[1], frames, gt_note, 0, False]
                        continue
                    continues = (
                        (note == GT_REST and (instr == 0 or (
                            instr == live and pat[r + 2] == CMD_SETSR)))
                        or (note == GT_KEYOFF and instr in (0, live)))
                    if not continues or block is None:
                        if instr:
                            live = instr
                        block = None
                        wants.setdefault(key, set()).add(None)
                        continue
                    block[8] += 1
                    (bound, shift, cmp_value, base, hi, lo, frames, gt_note,
                     k, on) = block
                    ages = range(k * frames, (k + 1) * frames)
                    target = bound * sum(
                        _expanding_vibrato_step(hi, lo, a, shift)
                        for a in ages) / len(ages)
                    level = _expanding_vibrato_level(target, gt_note,
                                                     cmp_value, base)
                    if level == base and not on:
                        wants.setdefault(key, set()).add(None)
                        continue
                    block[9] = True
                    wants.setdefault(key, set()).add(
                        (SPEED_NOTE_RELATIVE | cmp_value, level))
            repeat = 1
    written = busy = disagree = full = 0
    touched: set = set()
    for (b, r), entries in sorted(wants.items()):
        if len(entries) != 1 or None in entries:
            if entries != {None}:
                disagree += 1
            continue
        pat = patterns[b]
        if pat[r + 2] != 0:
            busy += 1
            continue
        idx = _speed_index(speed_table, next(iter(entries)))
        if not idx:
            full += 1
            continue
        pat[r + 2] = CMD_VIBRATO
        pat[r + 3] = idx
        written += 1
        touched.add(b)
    if log and (written or busy or disagree or off_table or full):
        log(f"Expanding vibrato.......: {written} row(s) in {len(touched)} "
            f"pattern(s)"
            + (f", {busy} with the column in use" if busy else "")
            + (f", {disagree} the orderlists disagree on" if disagree else "")
            + (f", {off_table} note(s) off the table" if off_table else "")
            + (f", {full} with the speed table full" if full else ""))
    return written
