"""Put a note's pitch in the register before its init call (`pitch_lead_tie`).

Goattracker's new-note init writes `$D404` and nothing else: `player.s`
mt_newnoteinit (line 813) loads firstwave, SR and AD and ends in
`jmp mt_loadregswaveonly` (line 909), which stores only `mt_chnwave AND
mt_chngate` to `SIDBASE+$04` (line 1358). The frequency registers are written
by mt_loadregs (line 1352) from `mt_chnfreqlo/hi`, and those are set by the
wavetable's note column (mt_wavefreq / mt_wavenote, lines 1055-1075) on a LATER
call. So the init call sounds whatever frequency the voice held before. With
the default testbit firstwave (`$09`) that frame is silent; with a gated real
waveform (`real_firstwave_instruments`, `no_test_restart`) it is a full-level
frame of the PREVIOUS note's pitch -- Monty voice 2's drum at 0:38 (the
original's frame 1937, `$057B` E-2) opens on `$09C5` D-3, the hit before it
(7138892, presets, lag 6; task pitch-lead-residue). Every
other route to the frequency on that call is closed too: the tick-0 commands
the init runs (`mt_tick0jump1`, line 905) write no frequency (lines 156-345),
and BUFFEREDWRITES' mt_loadregs would only copy the same stale
`mt_chnfreq`. What the player CAN do is have `mt_chnfreq` already hold the
note when the init call arrives.

The pass does that with a tie: the bare rest row before such a note becomes
the note itself with CMD_TONEPORTA $00. At the fetch a toneporta note skips
the gate-off (line 1299), and at its tick 0 the init stores `mt_chnnote` and
skips the rest (line 833); its continuous effect, speed `$00` = "tie note"
(line 410), jumps to `mt_effect_3_found` (line 503) and sets the frequency to
the note on the next call. The row after then starts the note as written, its
init call now writing a gated waveform at the note's own pitch. The tie is the
same note byte as the row it leads, so a pattern played under any orderlist
transpose leads with the transposed pitch.

**The cost is what the previous note does on the tie row.** The tie moves the
voice's frequency for the rest of that row: inaudible where the previous note
has already gated off and released (most of Monty's drums), heard where it is
still gated (Chicken_Song, Hollywood_or_Bust, Radio_ACE in the census of task
drum-attack-first-frame). And it does nothing where the previous instrument's
wavetable still writes a frequency on those calls (a wavetable note column
returns through mt_wavefreq, line 977, past the effect). Hence an option,
off by default, adopted per song on measurement.

Only notes on a record whose firstwave is a gated waveform are led (the
testbit record's init frame is silent, so a lead would buy nothing there),
only from a rest row with no command (`tie_row`; an instrument byte on it is
kept) that is not row 0 (row 0's command column is the subtune's clock,
`patterns.TEMPO_OVERWRITABLE`), only where the instrument is known from an
earlier row of the same pattern, and never where the lead would push the
pattern past gt2reloc's 256 packed bytes (`goatwriter.packed_pattern_size`,
greloc.c:1935).

A pattern's row-0 note is led from the LAST row of the pattern played before
it, and that row is shared by every place the earlier pattern is played. Where
all those places want the same tie byte it is written in place
(`_lead_row0`); where they want different ones the pattern is copied, one copy
per tie byte, and each orderlist entry pointed at its copy (`_clone_row0`,
which also splits a repeat whose plays into itself want another byte than its
exit). The orderlists play the same patterns in the same order under the same
transposes; only which copy is named changes.
"""
from __future__ import annotations

from typing import Callable, Optional, Tuple

from .goatwriter import (HEADER_LEN, PACKED_PATTERN_LIMIT,
                         packed_pattern_size, pattern_rows)
from .instrument_drop import _RECORD_LEN, _layout
from .patterns import (GT_END_PATTERN, GT_ORDER_RESTART, GT_REPEAT,
                       GT_TRANSPOSE_DOWN, GT_TRANSPOSE_UP, MAX_PATTERNS,
                       MAX_TRACK_LEN)

GT_REST = 0xBD
GT_FIRST_NOTE = 0x60
CMD_TONEPORTA = 0x03
# Instrument record byte 8 (songview Instrument.firstwave); $FE/$FF are the
# "skip waveform" spellings (player.s:842-843).
_FIRSTWAVE_AT = 8


def tie_row(cells) -> bool:
    """A row the tie may take: a rest with no command. An instrument byte
    on it is kept: it latches `mt_chninstr` at the fetch whether the note
    column holds a rest or the tie (player.s mt_nonewpatt, line 806), and
    the tie's init skips the rest of note init (line 833) as before. Monty
    voice 2's pattern 2 ends on `BD 17 00 00`, before the 0:38 drum."""
    return cells[0] == GT_REST and cells[2] == 0 and cells[3] == 0


def gated_firstwave_records(blob: bytes, instr_at: int) -> set:
    """GT instrument numbers whose init call writes a gated real waveform."""
    out = set()
    for i in range(blob[instr_at]):
        fw = blob[instr_at + 1 + i * _RECORD_LEN + _FIRSTWAVE_AT]
        if 0x10 <= fw < 0xFE and fw & 0x01:
            out.add(i + 1)
    return out


def _successions(blob, npatt: int) -> Optional[list]:
    """Every (pattern, transpose, next pattern, its transpose) the orderlists
    play, over each voice of each subtune: repeats expanded, transposes held
    (player.s mt_notrans: a transpose byte sets `mt_chntrans` until the next
    one), and the `RST` jump followed once, so the pattern at the restart
    target is seen with the transpose the loop arrives with. None where an
    orderlist does not read."""
    pos = HEADER_LEN
    subtunes = blob[pos]
    pos += 1
    out = []
    for _ in range(subtunes * 3):
        n = blob[pos]
        order = blob[pos + 1:pos + n + 2]
        pos += n + 2
        seq, at, trans, repeat, jumped, steps = [], 0, 0, 1, False, 0
        while at < len(order) and steps < 4096:
            steps += 1
            b = order[at]
            if b == GT_ORDER_RESTART:
                if jumped or at + 1 >= len(order) or order[at + 1] >= len(order):
                    break
                jumped, at = True, order[at + 1]
            elif b >= GT_TRANSPOSE_DOWN:
                trans = b - GT_TRANSPOSE_UP
                at += 1
            elif b >= GT_REPEAT:
                repeat = b - GT_REPEAT + 1
                at += 1
            else:
                if b >= npatt:
                    return None
                seq.extend([(b, trans)] * repeat)
                repeat = 1
                at += 1
        out.extend((q, tq, p, tp) for (q, tq), (p, tp) in zip(seq, seq[1:]))
    return out


def _last_row(blob, start: int, rows: int) -> int:
    """Index of a pattern's last played row: the one before its ENDPATT."""
    for r in range(rows):
        if blob[start + r * 4] == GT_END_PATTERN:
            return r - 1
    return rows - 1


def _lead_row0(out: bytearray, patterns, gated: set) -> Tuple[int, int]:
    """Lead a pattern's row-0 note from the LAST row of each pattern played
    before it. That row belongs to every place the earlier pattern is played,
    so it is written only where EVERY succession out of that pattern asks for
    the same tie byte (the note as written in the earlier pattern, so that its
    own transpose lands it on the later pattern's transposed note), and never
    where any succession out of it reaches a row 0 this pass cannot lead."""
    succ = _successions(out, len(patterns))
    if not succ:
        return 0, 0
    def last_instrument(q):
        start, rows = patterns[q]
        named = [out[start + r * 4 + 1]
                 for r in range(_last_row(out, start, rows) + 1)]
        named = [i for i in named if i]
        return named[-1] if named else None

    want: dict = {}
    for q, tq, p, tp in succ:
        start, _rows = patterns[p]
        # A row-0 note with no instrument byte plays the one the voice
        # arrives with: the last named in the pattern before it.
        note, ins = out[start], out[start + 1] or last_instrument(q)
        if GT_FIRST_NOTE <= note < GT_REST and ins in gated \
                and out[start + 2] != CMD_TONEPORTA:
            v = note + tp - tq
            want.setdefault(q, set()).add(v if GT_FIRST_NOTE <= v < GT_REST
                                          else None)
        else:
            want.setdefault(q, set()).add(None)
    led = skipped = 0
    for q, values in sorted(want.items()):
        if len(values) != 1 or None in values:
            continue
        (v,) = values
        start, rows = patterns[q]
        last = _last_row(out, start, rows)
        o = start + last * 4
        if last < 1 or not tie_row(out[o:o + 4]):
            continue
        cells = [list(out[start + r * 4:start + r * 4 + 4]) for r in range(rows)]
        cells[last] = [v, out[o + 1], CMD_TONEPORTA, 0]
        if packed_pattern_size(pattern_rows(sum(cells, []))) \
                > PACKED_PATTERN_LIMIT:
            skipped += 1
            continue
        out[o:o + 4] = bytes(cells[last])
        led += 1
    return led, skipped


def _plays(track: bytes) -> list:
    """[(byte position, pattern, transpose, times)] in the order one voice's
    orderlist plays them: the list once, then from the `RST` target to the
    end again with the transpose the loop arrives with -- the reading
    `_successions` takes, kept per orderlist byte so that a pattern number
    can be rewritten where it stands."""
    end = track.index(GT_ORDER_RESTART) if GT_ORDER_RESTART in track \
        else len(track)
    restart = track[end + 1] if end + 1 < len(track) else 0
    out, trans = [], 0
    for first in (0, restart if restart < end else end):
        times = 1
        for at in range(first, end):
            b = track[at]
            if b >= GT_TRANSPOSE_DOWN:
                trans = b - GT_TRANSPOSE_UP
            elif b >= GT_REPEAT:
                times = b - GT_REPEAT + 1
            else:
                out.append((at, b, trans, times))
                times = 1
    return out


def _clone_row0(out: bytearray, gated: set, max_patterns: int
                ) -> Tuple[bytes, int, dict]:
    """Lead a row-0 note `_lead_row0` declined because the pattern before it
    is followed, somewhere in the orderlists, by row-0 notes wanting
    DIFFERENT tie bytes. Each orderlist entry of such a pattern is pointed at
    a copy whose last row ties to the byte ITS successor wants: one copy per
    distinct tie byte, the original serving the entries that want none (or
    the most common byte, where every entry wants one). The pattern number is
    rewritten in place, so no orderlist changes length and no `RST` target
    moves. Declined, and counted by reason, where an entry wants two bytes
    at once (a repeat into a different successor, or a loop that arrives
    with another transpose), where the copy would pass gt2reloc's 256 packed
    bytes, or where no pattern number is left under `max_patterns`
    (`patterns.MAX_PATTERNS`)."""
    from .goatwriter.appending import _parse_song, _write_song
    song = _parse_song(bytes(out))
    pats = song.patterns
    declined: dict = {}
    splits = 0

    def decline(why, n=1):
        declined[why] = declined.get(why, 0) + n

    def row0_tie(q, tq, p, tp):
        """The tie byte q's last row needs for p's row-0 note, or None."""
        cells = pats[p]
        note, ins = cells[0], cells[1]
        if not ins:
            # The instrument the voice arrives with (`_lead_row0`).
            end = (_last_row(pats[q], 0, len(pats[q]) // 4) + 1) * 4
            named = [i for i in pats[q][1:end:4] if i]
            ins = named[-1] if named else None
        if GT_FIRST_NOTE <= note < GT_REST and ins in gated \
                and cells[2] != CMD_TONEPORTA:
            v = note + tp - tq
            return v if GT_FIRST_NOTE <= v < GT_REST else None
        return None

    def wants(track) -> dict:
        """position -> (pattern, tie bytes its repeats into itself ask for,
        tie bytes the entry after it asks for)."""
        seq, out = [], {}
        for at, p, trans, times in _plays(track):
            seq.extend([(at, p, trans)] * times)
        for (at, q, tq), (at2, p, tp) in zip(seq, seq[1:]):
            rec = out.setdefault(at, (q, set(), set()))
            rec[1 if at2 == at else 2].add(row0_tie(q, tq, p, tp))
        return out

    def leadable(q) -> bool:
        last = _last_row(pats[q], 0, len(pats[q]) // 4)
        return last >= 1 and tie_row(pats[q][last * 4:last * 4 + 4])

    # A repeat whose plays into itself want another tie byte than its exit
    # (Monty voice 2: `$D7 02`, pattern 2 eight times, its row-0 drum after
    # each) is split so the LAST play is an entry of its own: `$D0+n p`
    # becomes `$D0+n-1 p p` (`p p` where it played twice), the `RST` target
    # moved past the inserted byte. Declined where the orderlist would reach
    # `MAX_TRACK_LEN`.
    for ti in range(len(song.tracks)):
        for _guard in range(256):
            track = song.tracks[ti]
            end = track.index(GT_ORDER_RESTART)
            split = None
            for at, (q, own_set, exit_set) in sorted(wants(track).items()):
                both = own_set | exit_set
                if own_set and exit_set and len(both) > 1 \
                        and both - {None} and leadable(q) \
                        and at >= 1 and GT_REPEAT <= track[at - 1] \
                        < GT_TRANSPOSE_DOWN and at < end:
                    split = at
                    break
            if split is None:
                break
            at = split
            times = track[at - 1] - GT_REPEAT + 1
            if times == 2:
                new = track[:at - 1] + bytes((track[at], track[at])) \
                    + track[at + 1:]
            else:
                new = bytearray(track[:at - 1] + bytes(
                    (track[at - 1] - 1, track[at], track[at])) + track[at + 1:])
                if len(new) >= MAX_TRACK_LEN:
                    decline("repeat split past the orderlist limit")
                    break
                if new[-1] >= at:     # the restart target, past the insert
                    new[-1] += 1
                new = bytes(new)
            song.tracks[ti] = new
            splits += 1

    # Per orderlist entry: every tie byte its successors ask for.
    entries: dict = {}            # (track, position) -> (pattern, set)
    for ti, track in enumerate(song.tracks):
        for at, (q, own_set, exit_set) in wants(track).items():
            entries[(ti, at)] = (q, own_set | exit_set)
    by_pattern: dict = {}
    for key, (q, wants) in sorted(entries.items()):
        by_pattern.setdefault(q, []).append((key, wants))
    led = 0
    for q in sorted(by_pattern):
        rows = len(pats[q]) // 4
        last = _last_row(pats[q], 0, rows)
        if last < 1 or not tie_row(pats[q][last * 4:last * 4 + 4]):
            continue
        groups: dict = {}
        stay = 0                  # entries the bare original must serve
        for key, wants in by_pattern[q]:
            if len(wants) == 1 and None not in wants:
                (v,) = wants
                groups.setdefault(v, []).append(key)
            else:
                stay += 1
                if len(wants - {None}):
                    decline("entry wants two tie bytes")
        if not groups or (len(groups) == 1 and not stay):
            continue              # nothing to lead, or `_lead_row0`'s case
        order = sorted(groups, key=lambda v: (-len(groups[v]), v))
        # Every copy packs to the same size (only a note byte differs).
        probe = bytearray(pats[q])
        keep = pats[q][last * 4 + 1]
        probe[last * 4:last * 4 + 4] = bytes((order[0], keep, CMD_TONEPORTA, 0))
        if packed_pattern_size(pattern_rows(list(probe))) \
                > PACKED_PATTERN_LIMIT:
            decline("copy over 256 packed bytes",
                    sum(len(g) for g in groups.values()))
            continue
        # The original may take a byte only where every entry is served:
        # an entry left on it would tie to a byte its successor never plays.
        free = max_patterns - len(pats)
        own = None
        if not stay and len(order) - 1 <= free:
            own, order = order[0], order[1:]
        for v in order:
            copy = bytearray(pats[q])
            copy[last * 4:last * 4 + 4] = bytes((v, keep, CMD_TONEPORTA, 0))
            num =next((k for k, pk in enumerate(pats) if pk == copy), None)
            if num is None:
                if len(pats) >= max_patterns:
                    decline("no pattern number left", len(groups[v]))
                    continue
                pats.append(copy)
                num = len(pats) - 1
            for ti, at in groups[v]:
                t = bytearray(song.tracks[ti])
                t[at] = num
                song.tracks[ti] = bytes(t)
            led += 1
        if own is not None:
            pats[q][last * 4:last * 4 + 4] = bytes(
                (own, keep, CMD_TONEPORTA, 0))
            led += 1
    return (_write_song(song) if led else bytes(out)), led, declined, splits


def lead_ties(blob: bytes, log: Optional[Callable[[str], None]] = None,
              max_patterns: int = MAX_PATTERNS) -> Tuple[bytes, int]:
    """(new bytes, rows led). Byte-identical where nothing qualifies."""
    instr_at, _tables, _patt, patterns = _layout(blob)
    gated = gated_firstwave_records(blob, instr_at)
    if not gated:
        return blob, 0
    out = bytearray(blob)
    led = skipped = 0
    for start, rows in patterns:
        cells = [list(out[start + r * 4:start + r * 4 + 4]) for r in range(rows)]
        cur = None
        for r in range(rows):
            note, ins, cmd, _dat = cells[r]
            if ins:
                cur = ins
            if not (GT_FIRST_NOTE <= note < GT_REST) or cmd == CMD_TONEPORTA:
                continue
            if r < 2 or cur not in gated:
                continue
            if not tie_row(cells[r - 1]):
                continue
            trial = [list(c) for c in cells]
            trial[r - 1] = [note, cells[r - 1][1], CMD_TONEPORTA, 0]
            if packed_pattern_size(pattern_rows(sum(trial, []))) \
                    > PACKED_PATTERN_LIMIT:
                skipped += 1
                continue
            cells[r - 1] = trial[r - 1]
            led += 1
        for r in range(rows):
            out[start + r * 4:start + r * 4 + 4] = bytes(cells[r])
    across, skipped_across = _lead_row0(out, patterns, gated)
    led += across
    skipped += skipped_across
    before = len(patterns)
    blob2, cloned, declined, splits = _clone_row0(out, gated, max_patterns)
    led += cloned
    if log and led:
        log(f"Pitch lead ties.........: {led} row(s) tie to the note they "
            f"lead" + (f"; {skipped} left, pattern over "
                       f"{PACKED_PATTERN_LIMIT} packed bytes" if skipped else ""))
    if log and cloned:
        added = _layout(blob2)[2]
        log(f"Pitch lead copies.......: {cloned} pattern end(s) tie per "
            f"successor; {blob2[added] - before} pattern(s) added, "
            f"{blob2[added]} of {max_patterns}"
            + (f"; {splits} orderlist repeat(s) split" if splits else ""))
    if log and declined:
        log("Pitch lead copies left..: " + ", ".join(
            f"{n} entr{'y' if n == 1 else 'ies'}: {why}"
            for why, n in sorted(declined.items())))
    return blob2, led
