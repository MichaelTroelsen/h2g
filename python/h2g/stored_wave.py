"""The pitch a note byte sounds when it indexes past the frequency table onto
the per-voice STORED-WAVEFORM cells.

The classic note fetch is `ASL / TAY / LDA freqtbl,Y` with no bound, so a
byte at or above the table's length reads whatever follows it. In ten corpus
players the byte `$68` (Y = `$D0`) lands sixteen bytes past the 96-entry
table, exactly on the per-voice stored-waveform array the event path writes
with `STA cell,X` from the current instrument's waveform byte -- Commando
`$515A STA $54F8,X`, Crazy_Comets `$514C STA $54DF,X`, Devils_Galop `$143C
STA $1764,X`, Phantoms `$E130 STA $E430,X`, Proteus `$0990 STA $0D73,X`, and
the same instruction in Gerry_the_Germ, Warhawk, Gremlins, Geoff_Capes and
Monty_on_the_Run. So the frequency the original writes is

    lo = what voice 0's cell holds,  hi = what voice 1's cell holds

AT THE MOMENT OF THE FETCH -- a runtime fact, not a constant. Measured at
24b9f1d (siddump on the playing voice): B-5 (`$4141`/`$4341`) where voice 1
holds a `$41` pulse, C-4 on Crazy_Comets, D#4 on Phantoms. Re-checked
2026-10-02 against this walk: every frequency it predicts, in all ten
files, appears on the predicted voice in a 900 s siddump of the original --
Monty and Devils_Galop's `$8141` (B-6, voice 1 on noise) included; the
"silence" a 180 s trace showed for Devils_Galop was the window, its one
`$68` fetch comes later. `past_table_notes`
cannot see this (it reads the file image, which is saved runtime state, and
it declines any cell an instruction writes); `stored_wave_notes` walks the
three orderlists in time and reads each voice's waveform off the instrument
it holds at that tick.

What the walk relies on is read from the player, not assumed:

* the landing cell is the operand of `LDA tmp / STA cell,X` whose `tmp` was
  loaded by `LDA wave,X / STA tmp` with `wave` inside the instrument record
  (`STORE_SHAPE`, `WAVE_LOAD_SHAPE`) -- that gives the record offset of the
  waveform byte the cell receives;
* the voice loop runs X = 2, 1, 0 (`VOICE_LOOP_SHAPES`), so on a tick where
  several voices fetch, voice 0 already sees voice 1's new waveform and
  voice 2 sees neither;
* the store sits on the path every fetched event takes (note, rest and
  slide alike), and it runs AFTER the lookup, so a voice reading its own
  cell reads its PREVIOUS event's waveform.

**COMMANDO IS HELD** (`HELD`), by human decision (2026-10-01, plan task
`any-commando-pitch-fix-requires-recutting-the-byte-exact-fixture`): its
`$68` rows stay the clamp's G#7 until the note-104 listen reopens the
question, because `Commando.sng` is the byte-exact fixture.
"""
from collections import Counter
from math import log2
from typing import Dict, List, Optional, Tuple

from .detect import Detection
from .search import search_file
from .sidfile import SidFile

# Held by name, by human decision -- see the module docstring. The PSID name
# field, so the repo-root fixture and the corpus rip (two different files,
# same tune) are both held.
HELD = frozenset({"Commando"})

# `LDA tmp / STA cell,X` -- the store of the stored waveform. `tmp` and
# `cell` are read out of the match.
STORE_SHAPE = "AD ?? ?? 9D ?? ??"
# `LDA wave,X / STA tmp`, searched backwards from the store for this many
# bytes (the corpus distance is $2F-$3C: the SID register writes sit between).
WAVE_LOAD_WINDOW = 0x60
# The voice loop: `LDX #$02 / DEC divider / BPL` at the top, `DEX / BMI out /
# JMP top` at the bottom -- X counts 2, 1, 0.
VOICE_LOOP_SHAPES = ("A2 02 CE ?? ?? 10", "CA 30 03 4C ?? ??")

# The walk runs every subtune for this many times its longest voice's first
# pass, so every loop phase of the voices against each other is sampled at
# least once in the common case; capped so a pathological orderlist cannot
# stall a conversion.
HORIZON_PASSES = 2
MAX_TICKS = 200_000


def stored_wave_landings(sid: SidFile, det: Detection) -> Dict[int, Tuple[int, int]]:
    """Past-table entries whose two bytes are stored-waveform cells.

    Returns {entry: (k, wave_offset)}: the fetch at `entry` reads voice k's
    cell as the frequency LO byte and voice k+1's as the HI byte, and each
    cell holds byte `wave_offset` of the voice's current instrument record.
    Empty where the shapes are not found.
    """
    ft = det.freq_table
    if ft is None or det.instr_start < 0 or det.instr_stride <= 0:
        return {}
    data = sid.data
    if any(search_file(data, sh) < 0 for sh in VOICE_LOOP_SHAPES):
        return {}
    instr_addr = sid.to_address(det.instr_start)
    cells: Dict[int, int] = {}     # cell base -> wave offset
    for i in range(len(data) - 5):
        if data[i] != 0xAD or data[i + 3] != 0x9D:
            continue
        tmp = data[i + 1] | (data[i + 2] << 8)
        cell = data[i + 4] | (data[i + 5] << 8)
        for j in range(i - 6, max(-1, i - WAVE_LOAD_WINDOW), -1):
            if (data[j] == 0xBD and data[j + 3] == 0x8D
                    and (data[j + 4] | (data[j + 5] << 8)) == tmp):
                off = (data[j + 1] | (data[j + 2] << 8)) - instr_addr
                if 0 <= off < det.instr_stride:
                    cells[cell] = off
                break
    out: Dict[int, Tuple[int, int]] = {}
    for n in range(ft.length, 0x80):
        addr = ft.addr + 2 * n
        for k in (0, 1):
            if addr - k in cells:
                out[n] = (k, cells[addr - k])
    return out


def _nearest_entry(table: List[int], freq: int) -> int:
    return min(range(len(table)),
               key=lambda i: abs(log2(max(table[i], 1) / max(freq, 1))))


def _applicable(sid: SidFile, det: Detection, log=None
                ) -> Dict[int, Tuple[int, int]]:
    """The landings the walk reads, or {} where it does not run."""
    if det.pattern_dialect != "classic" or det.track_voices != 3:
        return {}
    if sid.name in HELD:
        if log and stored_wave_landings(sid, det):
            log("Stored-wave pitch.......: HELD for this tune (human decision, "
                "the byte-exact fixture); past-table bytes stay clamped")
        return {}
    return stored_wave_landings(sid, det)


def _walk(sid: SidFile, det: Detection, tracks: List[List[int]],
          landings: Dict[int, Tuple[int, int]], slides: bool,
          status_bit6: bool) -> List[tuple]:
    """Every vote the walk casts, in walk order, as `(group, voice, tick,
    position, entry, ordinal, freq, derived)` -- `position` being the index
    in `tracks[3 * group + voice]` of the orderlist byte that named `entry`.
    See `stored_wave_notes` for what is walked and how."""
    ft = det.freq_table
    data = sid.data
    base = sid.to_offset(ft.addr)
    table = [data[base + 2 * i] | (data[base + 2 * i + 1] << 8)
             for i in range(ft.length)]

    from .patterns import command_floor, decode_entry
    floor = command_floor(det.read_track_version, det.track_fd_transpose)

    cache: Dict[int, List[tuple]] = {}

    def events(entry: int) -> List[tuple]:
        if entry not in cache:
            ev: List[tuple] = []
            if decode_entry(sid, det, entry, slides=slides,
                            status_bit6=status_bit6, event_log=ev) is None:
                ev = []
            cache[entry] = ev
        return cache[entry]

    def record_byte(rec: Optional[int], off: int) -> Optional[int]:
        if rec is None:
            return None
        at = det.instr_start + rec * det.instr_stride + off
        return data[at] if 0 <= at < len(data) else None

    votes: List[tuple] = []
    for g in range(len(tracks) // 3):
        bodies: List[List[int]] = []
        # Per body element, the index of its byte in the orderlist: what a
        # per-position copy rewrites.
        places: List[List[int]] = []
        starts: List[Optional[int]] = []
        for v in range(3):
            track = tracks[3 * g + v]
            body: List[int] = []
            at: List[int] = []
            restart = None
            i = 0
            while i < len(track):
                b = track[i]
                if b == 0xFF:
                    restart = track[i + 1] if i + 1 < len(track) else 0
                    break
                if b < floor:
                    body.append(b)
                    at.append(i)
                elif b != 0xF0:
                    # A non-zero orderlist transpose moves the byte the
                    # player shifts; the walk does not model it.
                    body = []
                    break
                i += 1
            start = None
            if restart is not None:
                start = sum(1 for j in range(min(restart, len(track)))
                            if track[j] < floor)
                if start >= len(body):
                    start = None        # `$FE`: the tune ends here
            bodies.append(body)
            places.append(at)
            starts.append(start)
        if any(not b for b in bodies):
            continue
        pass_len = [sum(w + 1 for p in b for (w, _, _) in events(p))
                    for b in bodies]
        if min(pass_len) <= 0:
            continue
        horizon = min(MAX_TICKS, HORIZON_PASSES * max(pass_len))

        # Per voice: (position in body, event index in pattern)
        pos = [0, 0, 0]
        evi = [0, 0, 0]
        nxt = [0, 0, 0]
        # The instrument record each voice's cell was last written from,
        # None until the voice has fetched under a named instrument. The
        # player writes the cell AFTER the lookup, so it is updated below
        # the vote: a voice reading its own cell reads its previous event.
        held: List[Optional[int]] = [None, None, None]
        ended = False
        t = 0
        while t < horizon and not ended:
            for v in (2, 1, 0):
                if nxt[v] != t:
                    continue
                # Skip empty patterns: the player steps the orderlist past
                # them within the same fetch.
                guard = 0
                while evi[v] >= len(events(bodies[v][pos[v]])):
                    evi[v] = 0
                    pos[v] += 1
                    if pos[v] >= len(bodies[v]):
                        if starts[v] is None:
                            ended = True
                            break
                        pos[v] = starts[v]
                    guard += 1
                    if guard > len(bodies[v]) + 1:
                        ended = True
                        break
                if ended:
                    break
                entry = bodies[v][pos[v]]
                wait, rec, note = events(entry)[evi[v]]
                if note in landings:
                    k, off = landings[note]
                    lo = record_byte(held[k], off)
                    hi = record_byte(held[k + 1], off)
                    if lo is not None and hi is not None:
                        freq = (hi << 8) | lo
                        votes.append((g, v, t, places[v][pos[v]], entry,
                                      evi[v], freq,
                                      _nearest_entry(table, freq)))
                if rec is not None:
                    held[v] = rec
                evi[v] += 1
                nxt[v] = t + wait + 1
            t = min(nxt)
    return votes


def _majority(picks: List[int]) -> int:
    """The most frequent value, the first seen breaking a tie."""
    c = Counter(picks)
    top = max(c.values())
    return next(n for n in picks if c[n] == top)


def stored_wave_notes(sid: SidFile, det: Detection, tracks: List[List[int]],
                      log=None, slides: bool = False,
                      status_bit6: bool = False,
                      trace: Optional[List[tuple]] = None
                      ) -> Dict[int, Dict[int, int]]:
    """{pattern entry: {event ordinal: table entry}} for every event whose
    note byte lands on the stored-waveform cells, as the original sounds it.

    `tracks` are `convert_tracks`'s orderlists, still in Hubbard numbering.
    `slides`/`status_bit6` are the options `convert_patterns` decodes under,
    so the events walked are the events emitted.

    Each subtune's three voices are walked tick by tick (one tick = one
    event-duration unit, `wait + 1` per event, shared by all three voices),
    in the player's order X = 2, 1, 0 within a tick. At each fetch the
    landing byte's frequency is `cell[k+1] << 8 | cell[k]` from the cells as
    they stand; then the voice's own cell takes its current instrument's
    waveform byte. A cell is unknown until its voice has fetched under a
    named instrument, and an event reading an unknown cell casts no vote.

    A pattern is global, so a pattern played at two moments with different
    neighbours has ONE note to give here: the most frequent pitch across the
    plays the walk saw (first seen breaks a tie), and the disagreement is
    logged. An event the walk never reached is absent, and the decoder
    clamps it exactly as before. `stored_wave_copies` is what convert()
    calls: it gives each disagreeing orderlist position its own copy.

    `trace`, when given a list, receives one `(group, voice, tick, entry,
    ordinal, freq, derived)` tuple per vote, in walk order -- the frequency
    the original writes at that fetch, which is what a siddump of the
    original can be checked against, and which the returned map (one note
    per event) cannot show. It changes nothing returned.
    """
    landings = _applicable(sid, det, log)
    if not landings:
        return {}
    votes = _walk(sid, det, tracks, landings, slides, status_bit6)
    if trace is not None:
        trace.extend((g, v, t, e, o, f, d)
                     for (g, v, t, _p, e, o, f, d) in votes)
    plays: Dict[Tuple[int, int], List[int]] = {}
    for (_g, _v, _t, _p, e, o, _f, d) in votes:
        plays.setdefault((e, o), []).append(d)
    out: Dict[int, Dict[int, int]] = {}
    split = 0
    for (entry, ordinal), picks in plays.items():
        if len(set(picks)) > 1:
            split += 1
        out.setdefault(entry, {})[ordinal] = _majority(picks)
    if log and out:
        n = sum(len(m) for m in out.values())
        log(f"Stored-wave pitch.......: {n} past-table note(s) in "
            f"{len(out)} pattern(s) read off the voices' waveforms"
            + (f"; {split} played under two waveform states, majority kept"
               if split else ""))
    return out


def stored_wave_copies(sid: SidFile, det: Detection, tracks: List[List[int]],
                       first: int, limit: int, log=None,
                       slides: bool = False, status_bit6: bool = False,
                       trace: Optional[List[tuple]] = None
                       ) -> Tuple[Dict[int, Dict[int, int]],
                                  List[Tuple[int, Dict[int, int]]]]:
    """`stored_wave_notes`, with one pattern copy per waveform state.

    A pattern is global, but the pitch a stored-wave note sounds is what the
    OTHER voices hold at the fetch, so two orderlist positions naming the
    same pattern can sound it differently (Crazy_Comets' pattern $18: C-4
    where voice 1 holds a triangle, B-5 where it holds a pulse). One note
    per pattern is then a compromise. Here each orderlist POSITION gets the
    note map its own plays vote for -- per event, the majority of that
    position's plays, an event it never voted on taking the pattern-wide
    majority -- and positions are grouped by that map:

    * the map with the most plays (first seen breaking a tie) keeps the
      pattern's own number, and is returned in the first map in the shape
      `stored_wave_notes` returns (with one landing event per pattern, the
      corpus case, it is the same majority note; with several, it is the
      map one group of positions actually plays rather than a per-event
      mix no position plays);
    * every other map becomes a COPY, numbered `first`, `first + 1`, ...
      (after `fold_transposes`' variants, which is what `first` says), and
      the positions that vote for it are rewritten IN PLACE in `tracks` to
      name the copy. A position the walk never reached keeps the pattern.

    A copy is not made at or past `limit` (the dialect's command floor: an
    orderlist byte there is a command, not a pattern); its positions then
    keep the majority, as before. `convert_patterns` decodes copy j from its
    source entry with its own map, after the variants, and is where the
    pattern-count limit is enforced.

    What a copy cannot repair is a position whose OWN plays disagree -- a
    loop that brings the same orderlist byte round under a different
    neighbour. That is still one byte with one note; the count of such
    events is logged.

    Returns `(wave_notes, copies)`: `wave_notes` as `stored_wave_notes`
    (for the patterns' own numbers), `copies` the `(source entry, map)`
    list in copy-number order. `trace` as `stored_wave_notes`.
    """
    landings = _applicable(sid, det, log)
    if not landings:
        return {}, []
    votes = _walk(sid, det, tracks, landings, slides, status_bit6)
    if trace is not None:
        trace.extend((g, v, t, e, o, f, d)
                     for (g, v, t, _p, e, o, f, d) in votes)
    # Pattern-wide, as stored_wave_notes: the fallback for an event a
    # position did not vote on.
    wide_plays: Dict[Tuple[int, int], List[int]] = {}
    # Per position (track, index in it): its entry, and its plays per event.
    where: Dict[Tuple[int, int], int] = {}
    pos_plays: Dict[Tuple[int, int], Dict[int, List[int]]] = {}
    for (g, v, _t, p, e, o, _f, d) in votes:
        wide_plays.setdefault((e, o), []).append(d)
        key = (3 * g + v, p)
        where[key] = e
        pos_plays.setdefault(key, {}).setdefault(o, []).append(d)
    wide: Dict[int, Dict[int, int]] = {}
    for (e, o), picks in wide_plays.items():
        wide.setdefault(e, {})[o] = _majority(picks)

    # Per entry: each distinct position map, in first-seen order, with its
    # play count and the positions voting for it.
    maps: Dict[int, List[list]] = {}
    still_split = 0
    for key, per in pos_plays.items():        # insertion = walk order
        e = where[key]
        m = dict(wide[e])
        for o, picks in per.items():
            m[o] = _majority(picks)
            if len(set(picks)) > 1:
                still_split += 1
        frozen = tuple(sorted(m.items()))
        weight = sum(len(picks) for picks in per.values())
        for slot in maps.setdefault(e, []):
            if slot[0] == frozen:
                slot[1] += weight
                slot[2].append(key)
                break
        else:
            maps[e].append([frozen, weight, [key]])

    out: Dict[int, Dict[int, int]] = {}
    copies: List[Tuple[int, Dict[int, int]]] = []
    moved = refused = 0
    for e in sorted(maps):
        slots = maps[e]
        top = max(s[1] for s in slots)
        keep = next(s for s in slots if s[1] == top)
        out[e] = dict(keep[0])
        for s in slots:
            if s is keep:
                continue
            if first + len(copies) >= limit:
                refused += len(s[2])
                continue
            number = first + len(copies)
            copies.append((e, dict(s[0])))
            for (tn, p) in s[2]:
                tracks[tn][p] = number
                moved += 1
    if log and out:
        n = sum(len(m) for m in out.values())
        log(f"Stored-wave pitch.......: {n} past-table note(s) in "
            f"{len(out)} pattern(s) read off the voices' waveforms"
            + (f"; {len(copies)} waveform-state cop(ies) for {moved} "
               f"orderlist position(s)" if copies else "")
            + (f"; {refused} position(s) kept the majority, no pattern "
               f"number left below the command floor" if refused else "")
            + (f"; {still_split} event(s) whose own plays disagree, "
               f"majority kept" if still_split else ""))
    return out, copies
