"""Appending one song's subtunes to another (split out of goatwriter.py, text moved unchanged)."""
from __future__ import annotations

from dataclasses import (dataclass)
from typing import (List, Optional, Set)

from .constants import (GT_MAX_FILT, GT_MAX_INSTRUMENTS, GT_MAX_SONGS,
                        HEADER_LEN, _JUMP, _NAME_AT, _ORDERLIST_REPEAT,
                        _ORDERLIST_TRANSPOSE, _POINTER_COMMANDS, _RECORD_LEN,
                        _SONG_MAX_PATTERNS, _SPEED_COMMANDS, _TABLE_NAMES,
                        _WAVE_POINTER_COMMANDS, _WAVE_SPEED_COMMANDS)
from .instruments import (_padded_name_bytes)
from . import constants as _gw_constants
@dataclass
class _Song:
    magic: bytes
    header: bytes
    tracks: List[bytes]           # each: entries + $FF + restart
    instruments: List[bytearray]  # 25-byte records
    tables: List[List[tuple]]     # wave, pulse, filter[, speed] as (l, r)
    patterns: List[bytearray]     # rows * 4 bytes


def _parse_song(blob: bytes) -> _Song:
    """A `.sng` as build_sng writes it, in parts `_write_song` reassembles."""
    magic = bytes(blob[:4])
    if magic not in (b"GTS2", b"GTS5"):
        raise ValueError(f"not a Goattracker song: magic {magic!r}")
    pos = HEADER_LEN
    header = bytes(blob[:pos])
    tracks = []
    subtunes = blob[pos]
    pos += 1
    for _ in range(subtunes * 3):
        n = blob[pos] + 1
        tracks.append(bytes(blob[pos + 1:pos + 1 + n]))
        pos += 1 + n
    count = blob[pos]
    pos += 1
    instruments = [bytearray(blob[pos + k * _RECORD_LEN:pos + (k + 1) * _RECORD_LEN])
                   for k in range(count)]
    pos += count * _RECORD_LEN
    tables = []
    for _ in range(4 if magic == b"GTS5" else 3):
        n = blob[pos]
        left = blob[pos + 1:pos + 1 + n]
        right = blob[pos + 1 + n:pos + 1 + 2 * n]
        tables.append(list(zip(left, right)))
        pos += 1 + 2 * n
    patterns = []
    npat = blob[pos]
    pos += 1
    for _ in range(npat):
        rows = blob[pos]
        patterns.append(bytearray(blob[pos + 1:pos + 1 + rows * 4]))
        pos += 1 + rows * 4
    if pos != len(blob):
        raise ValueError(f".sng layout read ends at {pos}, file is {len(blob)}")
    return _Song(magic, header, tracks, instruments, tables, patterns)


def _write_song(song: _Song) -> bytes:
    out = bytearray(song.header)
    out.append(len(song.tracks) // 3)
    for t in song.tracks:
        out.append(len(t) - 1)
        out += t
    out.append(len(song.instruments))
    for r in song.instruments:
        out += r
    for table in song.tables:
        out.append(len(table))
        out += bytes(l for l, _ in table)
        out += bytes(r for _, r in table)
    out.append(len(song.patterns))
    for p in song.patterns:
        out.append(len(p) // 4)
        out += p
    return bytes(out)


def _table_entries(song: _Song, t: int, gts5: bool) -> Set[int]:
    """Every 1-based row of table `t` something in `song` points at."""
    found: Set[int] = set()
    for rec in song.instruments:
        v = rec[2 + t] if t < 3 else (rec[5] if gts5 else 0)
        if v:
            found.add(v)
    for p in song.patterns:
        for r in range(0, len(p), 4):
            cmd, data = p[r + 2] & 0x0F, p[r + 3]
            if data and (_POINTER_COMMANDS.get(cmd) == t
                         or (t == 3 and gts5 and cmd in _SPEED_COMMANDS)):
                found.add(data)
    for left, right in song.tables[0]:
        if right and (_WAVE_POINTER_COMMANDS.get(left) == t
                      or (t == 3 and gts5 and left in _WAVE_SPEED_COMMANDS)):
            found.add(right)
    return found


def _run_end(table: List[tuple], i: int) -> int:
    """The row of the `$FF` that ends the run through row `i` (or the last)."""
    while i < len(table) - 1 and table[i][0] != _JUMP:
        i += 1
    return i


def _regions(table: List[tuple], entries: Set[int], sequenced: bool):
    """[lo, hi] 0-based row spans reachable from `entries`, closed under jumps.

    A sequenced table runs from an entry to its `$FF` and on to wherever that
    jumps; the speed table is indexed, one row per reference.
    """
    n = len(table)
    spans = []
    for e in entries:
        if not 0 < e <= n:
            raise ValueError(f"a reference to row {e} of a {n}-row table")
        spans.append([e - 1, _run_end(table, e - 1) if sequenced else e - 1])
    while True:
        spans.sort()
        merged: List[list] = []
        for s in spans:
            if merged and s[0] <= merged[-1][1]:
                merged[-1][1] = max(merged[-1][1], s[1])
            else:
                merged.append(list(s))
        grown = False
        for s in merged if sequenced else ():
            for i in range(s[0], s[1] + 1):
                left, right = table[i]
                if left != _JUMP or not right:
                    continue
                if not 0 < right <= n:
                    raise ValueError(f"a jump to row {right} of a {n}-row table")
                lo, hi = min(s[0], right - 1), max(s[1], _run_end(table, right - 1))
                if (lo, hi) != (s[0], s[1]):
                    s[0], s[1], grown = lo, hi, True
        spans = merged
        if not grown:
            return spans


def _place_region(dest: List[tuple], rows: List[tuple]) -> int:
    """0-based row of `dest` where `rows` already stands, else where they are
    appended. A row of `rows` is (left, right, jump): a jump's right side is
    relative to the region's first row and compared as such."""
    def at(j: int) -> List[tuple]:
        return [(l, r + j + 1 if jump else r) for l, r, jump in rows]
    need = len(rows)
    for j in range(len(dest) - need + 1):
        if dest[j:j + need] == at(j):
            return j
    j = len(dest)
    dest.extend(at(j))
    return j


def _pattern_plays(track: bytes):
    """([(position, pattern, times)], restart) for one voice's orderlist.

    `$D0+n` plays the pattern after it n+1 times (patterns.GT_REPEAT);
    transposes are skipped, they do not change which instrument is latched.
    """
    end = track.index(_JUMP) if _JUMP in track else len(track)
    restart = track[end + 1] if end + 1 < len(track) else 0
    plays, times = [], 1
    for pos in range(end):
        x = track[pos]
        if _ORDERLIST_REPEAT <= x < _ORDERLIST_TRANSPOSE:
            times = x - _ORDERLIST_REPEAT + 1
        elif x < _ORDERLIST_REPEAT:
            plays.append((pos, x, times))
            times = 1
    return plays, restart


def _latched_after(pattern: bytearray, current: int) -> int:
    """The instrument a voice holds after playing `pattern` from `current`."""
    for r in range(0, len(pattern), 4):
        if pattern[r + 1]:
            current = pattern[r + 1]
    return current


def _pin_start_instruments(song: _Song) -> Optional[str]:
    """Make every voice's first row name the instrument it starts on.

    Goattracker starts every voice on instrument 1 (gplay.c:62) and latches a
    pattern's instrument column whenever it is non-zero (gplay.c:914). In the
    song a player converted to, instrument 1 is that player's first record;
    appended after another song it is the OTHER song's, and every row the voice
    plays before its own first instrument column runs under it -- its
    gatetimer decides when the next row is fetched (gplay.c:905), its vibrato
    moves the frequency. 5_Title_Tunes' player 3 opens voices 1 and 2 on eight
    rests, and under player 0's instrument 1 neither voice sounded a note: the
    subtune scored 42% against 100% for the same player converted alone.

    So the instrument the voice starts on is written into row 0 of its first
    pattern, which is what it already holds there. In place where every other
    play of that pattern (any voice, the restart loop included) enters it
    holding instrument 1 too, so the write changes nothing for them; else
    into a copy only the voices' first plays read. Returns why it cannot, or
    None.
    """
    entries: dict = {}
    firsts = []
    for v, track in enumerate(song.tracks):
        plays, restart = _pattern_plays(track)
        firsts.append(plays[0] if plays else None)
        looped = [p for p in plays if p[0] >= restart]
        current = 1
        for i, (pos, x, times) in enumerate(plays + looped + looped):
            if x >= len(song.patterns):
                return f"an orderlist names pattern {x} of {len(song.patterns)}"
            for t in range(times):
                entries.setdefault(x, []).append((v, i == 0 and t == 0, current))
                current = _latched_after(song.patterns[x], current)
    copies: dict = {}
    for v, first in enumerate(firsts):
        if first is None:
            continue
        pos, x, times = first
        if not song.patterns[x] or song.patterns[x][1]:
            continue                      # row 0 already names one
        others = [held for w, is_first, held in entries[x]
                  if not (w == v and is_first)]
        if all(held == 1 for held in others):
            song.patterns[x][1] = 1
            continue
        if times > 1 and _latched_after(song.patterns[x], 1) != 1:
            return (f"voice {v + 1} opens on a repeated pattern that enters "
                    "its repeats on another instrument")
        if x not in copies:
            copy = bytearray(song.patterns[x])
            copy[1] = 1
            song.patterns.append(copy)
            copies[x] = len(song.patterns) - 1
        track = bytearray(song.tracks[v])
        track[pos] = copies[x]
        song.tracks[v] = bytes(track)
    return None


def append_song(base: bytes, extra: bytes, tag: str = "",
                log=None) -> Optional[bytes]:
    """`base` with every subtune of `extra` appended after its own, or None.

    `base`'s bytes for its own subtunes are not touched -- its instruments,
    rows and patterns keep their numbers and contents -- so its subtunes play
    exactly as before. `extra`'s reachable table regions, instruments and
    patterns are placed after (or, where identical, onto) `base`'s and every
    reference renumbered; see the block comment above. `tag` prefixes the
    names of the instruments `extra` adds, so a reader can tell which player a
    record came from. None, with the reason logged, where a cap would be
    passed.
    """
    a, b = _parse_song(base), _parse_song(extra)
    if a.magic != b.magic:
        raise ValueError(f"cannot append a {b.magic!r} song to a {a.magic!r} one")
    gts5 = a.magic == b"GTS5"
    label = tag.rstrip("/") or "song"

    def refuse(why: str) -> None:
        if log:
            log(f"*** {label} NOT APPENDED: {why} ***")

    why = _pin_start_instruments(b)
    if why:
        refuse(why)
        return None
    caps = (_gw_constants.GT_MAX_TABLELEN, _gw_constants.GT_MAX_TABLELEN, GT_MAX_FILT, _gw_constants.GT_MAX_TABLELEN)
    # Old 1-based row -> new 1-based row, per table. Speed first, pulse and
    # filter next, the wavetable last: its command rows name the other three.
    maps: List[dict] = [{}, {}, {}, {}]
    for t in (3, 1, 2, 0):
        if t >= len(b.tables):
            continue
        table = b.tables[t]
        for lo, hi in _regions(table, _table_entries(b, t, gts5), t != 3):
            rows = []
            for i in range(lo, hi + 1):
                left, right = table[i]
                jump = t != 3 and left == _JUMP and right != 0
                if jump:
                    right = right - 1 - lo        # relative to the region
                elif t == 0 and right and left in _WAVE_POINTER_COMMANDS:
                    right = maps[_WAVE_POINTER_COMMANDS[left]][right]
                elif t == 0 and right and gts5 and left in _WAVE_SPEED_COMMANDS:
                    right = maps[3][right]
                rows.append((left, right, jump))
            j = _place_region(a.tables[t], rows)
            for i in range(lo, hi + 1):
                maps[t][i + 1] = j + (i - lo) + 1
        if len(a.tables[t]) > caps[t]:
            refuse(f"{_TABLE_NAMES[t]} table needs {len(a.tables[t])} rows "
                   f"> {caps[t]}")
            return None

    def moved(t: int, v: int) -> int:
        return maps[t][v] if v else 0

    known = {bytes(r[:_NAME_AT]): k + 1 for k, r in enumerate(a.instruments)}
    instr_map = {}
    for k, rec in enumerate(b.instruments):
        rec = bytearray(rec)
        for f in (2, 3, 4):
            rec[f] = moved(f - 2, rec[f])
        if gts5:
            rec[5] = moved(3, rec[5])
        key = bytes(rec[:_NAME_AT])
        if key not in known:
            if tag:
                name = bytes(rec[_NAME_AT:]).rstrip(b"\x00").decode("latin-1")
                rec[_NAME_AT:] = _padded_name_bytes(tag + name)
            a.instruments.append(rec)
            known[key] = len(a.instruments)
        instr_map[k + 1] = known[key]
    if len(a.instruments) > GT_MAX_INSTRUMENTS:
        refuse(f"{len(a.instruments)} instruments > {GT_MAX_INSTRUMENTS}")
        return None
    if len(a.patterns) + len(b.patterns) > _SONG_MAX_PATTERNS:
        refuse(f"{len(a.patterns)}+{len(b.patterns)} patterns "
               f"> {_SONG_MAX_PATTERNS}")
        return None
    if (len(a.tracks) + len(b.tracks)) // 3 > GT_MAX_SONGS:
        refuse(f"more than {GT_MAX_SONGS} subtunes")
        return None

    n_pat = len(a.patterns)
    for p in b.patterns:
        p = bytearray(p)
        for r in range(0, len(p), 4):
            ins = p[r + 1]
            if ins:
                if ins not in instr_map:
                    refuse(f"a pattern names instrument {ins} of "
                           f"{len(b.instruments)}")
                    return None
                p[r + 1] = instr_map[ins]
            cmd = p[r + 2] & 0x0F
            if cmd in _POINTER_COMMANDS:
                p[r + 3] = moved(_POINTER_COMMANDS[cmd], p[r + 3])
            elif gts5 and cmd in _SPEED_COMMANDS:
                p[r + 3] = moved(3, p[r + 3])
        a.patterns.append(p)
    for track in b.tracks:
        end = track.index(_JUMP) if _JUMP in track else len(track)
        a.tracks.append(bytes(x + n_pat if k < end and x < _ORDERLIST_REPEAT
                              else x for k, x in enumerate(track)))
    if log:
        log(f"Appended {label}: {len(b.tracks) // 3} subtune(s); the file now "
            f"carries {len(a.instruments)} instruments, "
            + ", ".join(f"{_TABLE_NAMES[t]} {len(tab)}"
                        for t, tab in enumerate(a.tables))
            + f" table rows, {len(a.patterns)} patterns")
    return _write_song(a)
