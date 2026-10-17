"""A rest rings out at the instrument's release and is cut on its last tick.

`--cut-release` zeroes the release nibble in every instrument of a player that
ends a NOTE by writing `$0000` to the envelope pair (`detect.ENVELOPE_CUT_SHAPES`),
because that note stops dead on the tick the gate drops. A REST is not that
note end. Las Vegas Video Poker, the routine at `$5006`:

    5089 ...fetch...      BIT $54D3 / BVS $511F      ; status bit 6: a rest
    511F DEC $54D2                                   ; gate mask $FF -> $FE
    5122 ...                                         ; the SHARED tail: wave &
                                                     ;   mask -> $D404, then
    514B LDA $5509,X / STA $D405,Y                   ;   the instrument's AD
    5152 LDA $550A,X / STA $D406,Y                   ;   and SR, re-written
    ...
    518B LDA $54C6,X / AND #$20 / BNE $51AA          ; status bit 5: no cut
    5195 LDA $54C3,X / BNE $51AA                     ; the tick counter
    519A LDA $54C9,X / AND #$FE / STA $D404,Y        ; counter == 0: gate off
    51A2 LDA #0 / STA $D405,Y / STA $D406,Y          ;   and the pair zeroed

so a rest drops its gate on its FIRST tick with the instrument's own release
loaded, and the cut that follows every untied event lands on its LAST. Voice 1
of the default subtune, event `$43` (wait 3, instrument 8, `SR $0C`), siddump
-v1:

    301  .... 40 ....      gate off, SR still $0C
    ...                    the release plays for 11 frames
    312  .... .. 0000      counter reached 0 (the "late" ADSR zero)
    316  C-4  41 0A0C      the next note

The late zero keys on the **tick counter**, not on a delay: `wait` ticks after
the rest began, and not at all when the status byte carries bit 5 (`$20`) or
when `wait` is 0 (the counter is set to 0 by the fetch and DEC'd to $FF by the
next one, so `counter == 0` is never read after a decrement).

Ours had release 0 from the first row, so every frame between was silent where
the original sounds -- Las Vegas voice 1's `tie_ours_only_silent` ties.

THE SPELLING (`patterns._build_raw_pattern` writes the marker, this pass
finishes it):

    the row BEFORE the KEYOFF   CMD_SETSR <the held instrument's UNCUT SR>
    last hold row of the rest   CMD_SETSR $00           (the cut: counter == 0)

**The ring is written a row early, and that is not a choice.** Goattracker
reads a row `gatetimer` calls ahead of its time (gplay.c:854, :905; the
instrument's `hard_restart_frames`) and a KEYOFF takes effect THEN, while the
row's command waits for the row's own tick 0. An SR written on the KEYOFF row
lands after the gate has already dropped on the release 0 the instrument
carries, and a released envelope does not climb back: Las Vegas traces gate
off at 302 and `0A0C` at 306, four frames of silence at the head of the ring,
which is the whole ring. Written on the row before it changes only the
release nibble of a gate that is still open.

The row before is a free hold row of the same pattern, or -- when the rest
opens a pattern, which is most of Las Vegas's default subtune -- the LAST row
of every predecessor pattern, taken only when each predecessor leads nowhere
else (a shared one would ring a rest that is not ringing) and wants the same
SR. Any other case drops the marker, the rest as it was: a late ring is a
command slot spent for nothing.

The cut is `SETSR $00` and not a zeroed release alone: it is the same pair the
player writes, and the register the `adsr` column reads.

A pattern that differs only in these markers is still one pattern under
`dedup` (`patterns._ring_key`, `_merge_ring_markers`: a marker survives a merge
only where every source carries it), so a file in which nothing rings keeps the
pattern table it had. A pattern this pass pushes past the packed-size limit is
put back as it was.

Written only where it is SAFE, every other case dropped:

* the held instrument is known (`note_passes._entry_instruments`: every
  orderlist entry into the pattern agrees, or a row in the pattern names it, or
  the entries differ but share one envelope pair);
* its release is actually zeroed (`record_envelope` with and without
  `cut_release` differ) -- an instrument whose effect byte has bit 0 keeps its
  release in the record because the effect routine re-writes the envelope
  every frame (`constants.EFFECT_PER_FRAME`), and cutting it here would be the
  defect `cut_release` already avoids;
* the KEYOFF row's command column is free or holds the `CMD_TONEPORTA 00` of a
  rest after a tied note, which the KEYOFF path never reads.
"""
from __future__ import annotations

from .constants import (CMD_SETSR, CMD_TONEPORTA, GT_FIRST_NOTE, GT_KEYOFF,
                        GT_LAST_NOTE, GT_REST, PACKED_PATTERN_LIMIT,
                        _SONG_MAX_PATTERNS)
from .note_passes import _entry_instruments, _pattern_successors
from .pulse import packed_pattern_size, pattern_rows


def _ring_free(rows: list, q: int) -> bool:
    k = q * 4
    return (rows[k] == GT_REST and rows[k + 1] == 0
            and rows[k + 2] == 0 and rows[k + 3] == 0)


def _ring_marker(rows: list, q: int) -> bool:
    k = q * 4
    return (rows[k] == GT_REST and rows[k + 1] == 0
            and rows[k + 2] == CMD_SETSR and rows[k + 3] == 0)


def _ring_last_row(rows: list) -> int:
    """Index of the last real row (before the 0xFF terminator), or -1."""
    n = len(rows) // 4
    for r in range(n):
        if rows[r * 4] == 0xFF:
            return r - 1
    return n - 1


def _ring_occurrences(tracks: list, count: int) -> dict:
    """(track, position) -> (pattern, repeat, next pattern) for every pattern
    an orderlist plays, `next` being what plays after it (the restart's
    pattern at the end; None where the song stops). `repeat` is the `$Dn`
    prefix's count, 1 for none."""
    out: dict = {}
    for ti, track in enumerate(tracks):
        seq = []
        repeat, pos, restart = 1, 0, None
        while pos < len(track):
            b = track[pos]
            if b == 0xFF:
                restart = track[pos + 1] if pos + 1 < len(track) else None
                break
            if 0xE0 <= b < 0xFF:
                pos += 1
                continue
            if 0xD0 <= b < 0xE0:
                repeat = b - 0xD0 + 1
                pos += 1
                continue
            if b < count:
                seq.append((pos, b, repeat))
            repeat = 1
            pos += 1
        wrap = None
        if restart is not None and restart < pos:
            wrap = next((p for ps, p, _r in seq if ps >= restart), None)
        for i, (ps, p, r) in enumerate(seq):
            nxt = seq[i + 1][1] if i + 1 < len(seq) else wrap
            out[(ti, ps)] = (p, r, nxt)
    return out


def rest_ring_pass(patterns, ring_envelopes: dict, cut_envelopes: dict,
                   tracks=None, log=None, chains: bool = True):
    """Finish the rest-end markers `_build_raw_pattern` wrote; returns
    `(patterns, tracks)` -- a pattern played where one rest follows and a tie
    elsewhere is copied, and only the positions that want the ring repointed.

    `ring_envelopes` / `cut_envelopes` map a Goattracker instrument number to
    the `(ad, sr)` pair emitted without / with `cut_release`. Every marker the
    decoder wrote is either turned into the ring and the cut or taken out
    again, so a pattern that gets neither is the pattern it always was.

    `chains` admits the two rests a tied note's release reaches past the
    first one: a rest entered ringing (a KEYOFF straight after an uncut rest,
    whose cut is marked by `patterns` `ring_chain`) and a tied chain that
    runs off the pattern uncut. False reads both the way this pass did
    before them -- the caller turns it off where the note rise's per-row
    programs (`goatwriter.note_rise`, run later) want the same command
    column through the rest (Chimera, Game_Killer, Battle_of_Britain,
    Human_Race).
    """
    entry = _entry_instruments(tracks, patterns) if tracks else {}
    successors = _pattern_successors(tracks, len(patterns)) if tracks else {}
    out = [list(p) for p in patterns]
    unknown = inert = 0
    # (pattern, KEYOFF row, cut-marker row, SR) for every rest that should ring.
    wanted = []
    # (pattern, KEYOFF row, SR): a rest chain entered from a tied note in this
    # very pattern that runs off its end with no cut marker -- the bit-5
    # rests that never cut, or a chain whose cut the 94-row slicing put in the
    # next pattern. It rings with no cut of its own (see the end of the loop).
    wanted_open = []

    def held_pair(named, live, held, shared):
        if named or len(held) == 1:
            return ring_envelopes.get(live), cut_envelopes.get(live), bool(live)
        if shared is not None:
            return shared[0], shared[1], True
        return None, None, False
    for pn, rows in enumerate(out):
        n = len(rows) // 4
        held = entry.get(pn, set())
        live = next(iter(held)) if len(held) == 1 else 0
        # Several instruments entered, one envelope pair: settled all the same.
        pairs = {(ring_envelopes.get(i), cut_envelopes.get(i)) for i in held}
        shared = next(iter(pairs)) if len(pairs) == 1 else None
        named = False
        open_at = None
        tied_open = False
        for r in range(n):
            k = r * 4
            if rows[k] == 0xFF:
                break
            if rows[k + 1]:
                live = rows[k + 1]
                named = True
            if rows[k] == GT_KEYOFF:
                if (open_at is not None and rows[k + 1] == 0
                        and rows[k + 2] == 0 and rows[k + 3] == 0):
                    # A rest straight after a rest that did not cut: the
                    # release that began at the FIRST KEYOFF is still
                    # sounding (`patterns` `ring_chain`), so the chain rings
                    # from there and this KEYOFF, on a gate already shut,
                    # changes nothing.
                    if not chains:
                        open_at = None      # its marker becomes an orphan
                    continue
                # Free, or the `CMD_TONEPORTA 00` a rest after a tied note is
                # given (`pending_tie`): the packed player's KEYOFF path
                # never reads it (player.s `mt_gate` precedes the
                # TONEPORTA test in `mt_normalnote`).
                open_at = r if (rows[k + 1] == 0 and (
                    (rows[k + 2], rows[k + 3]) in ((0, 0), (CMD_TONEPORTA, 0)))
                    ) else None
                tied_open = (open_at is not None
                             and rows[k + 2] == CMD_TONEPORTA)
                continue
            if open_at is not None and _ring_free(rows, r):
                continue
            if open_at is not None and _ring_marker(rows, r):
                ring, cutd, known = held_pair(named, live, held, shared)
                if not known:
                    unknown += 1
                elif ring is None or cutd is None or ring[1] == cutd[1]:
                    inert += 1
                else:
                    wanted.append((pn, open_at, r, ring[1] & 0xFF))
                    open_at = None
                    continue
                rows[k + 2:k + 4] = [0, 0]
            elif _ring_marker(rows, r) and r != _ring_last_row(rows):
                rows[k + 2:k + 4] = [0, 0]          # an orphan: no KEYOFF
            open_at = None
        if chains and open_at is not None and tied_open and open_at > 0:
            # The chain is still open where the pattern ends. Its first
            # KEYOFF carries the `CMD_TONEPORTA 00` of a tied note, so the
            # gate it shuts was open and the player's rest re-wrote the
            # record's SR over it (Kentilla `37 77 77 57`, `$AC23`): the
            # release sounds. Rung with no cut, so a cut the slicing moved
            # into the next pattern is dropped and the ring runs into the
            # next attack -- a tick late at most, against a rest that was
            # silent from its first frame.
            ring, cutd, known = held_pair(named, live, held, shared)
            if not known:
                unknown += 1
            elif ring is None or cutd is None or ring[1] == cutd[1]:
                inert += 1
            else:
                wanted_open.append((pn, open_at, ring[1] & 0xFF))

    opening = {pn: sr for pn, a, _m, sr in wanted if a == 0}

    def successor_ok(x: int, sr: int) -> bool:
        """May a ring written on the LAST row of a pattern be left there for
        a successor `x`? Yes where `x` is a rest that wants this very SR, a
        rest of its own (a KEYOFF rings at the held release whether or not it
        is cut), or opens on a plain note, whose attack reloads the
        instrument's SR over it (gplay.c:397). No where it opens on a tie --
        a TONEPORTA loads nothing -- or on the middle of an event."""
        if x in opening:
            return opening[x] == sr
        if x >= len(out) or not out[x] or out[x][0] == 0xFF:
            return False
        note, cmd = out[x][0], out[x][2]
        if note == GT_KEYOFF:
            return True
        return GT_FIRST_NOTE <= note <= GT_LAST_NOTE and cmd != CMD_TONEPORTA

    mine: set = set()             # (pattern, row) this pass leaves behind
    # The rests that open inside their pattern put the ring on the row before.
    for pn, a, m, sr in wanted:
        if a > 0 and _ring_free(out[pn], a - 1):
            out[pn][(a - 1) * 4 + 2:(a - 1) * 4 + 4] = [CMD_SETSR, sr]
            mine.update({(pn, a - 1), (pn, m)})
    rung_open = 0
    for pn, a, sr in wanted_open:
        if _ring_free(out[pn], a - 1):
            out[pn][(a - 1) * 4 + 2:(a - 1) * 4 + 4] = [CMD_SETSR, sr]
            mine.add((pn, a - 1))
            rung_open += 1

    # The rests that open a pattern put it on the last row of whatever plays
    # before them -- per orderlist POSITION, because a pattern that leads to a
    # rest in one place and a tie in another can carry the ring in only one of
    # them; the others get a copy (filters.free_running_fetch_holds' rule).
    new_tracks = [list(t) for t in tracks] if tracks else []
    occurrences = _ring_occurrences(new_tracks, len(out)) if tracks else {}
    asks: dict = {}                       # pattern -> {position: (SR, opener)}
    for (ti, pos), (q, repeat, nxt) in occurrences.items():
        sr = opening.get(nxt)
        if sr is None:
            continue
        last = _ring_last_row(out[q])
        succs = {nxt} | ({q} if repeat > 1 else set())
        if (last >= 0 and _ring_marker(out[q], last)
                and all(successor_ok(x, sr) for x in succs)):
            asks.setdefault(q, {})[(ti, pos)] = (sr, nxt)
    clone_of: dict = {}
    openers_rung: set = set()
    for q, asked in asks.items():
        everywhere = [o for o, (qq, _r, _n) in occurrences.items() if qq == q]
        sigs = {o: (asked[o][0] if o in asked else None) for o in everywhere}
        distinct = list(dict.fromkeys(sigs.values()))
        number = {None: q}
        for sig in distinct:
            if sig is None:
                continue
            edited = list(out[q])
            last = _ring_last_row(edited)
            edited[last * 4 + 3] = sig
            if packed_pattern_size(pattern_rows(edited)) > PACKED_PATTERN_LIMIT:
                number[sig] = None
            elif None not in distinct and sig == distinct[0]:
                out[q] = edited                     # every position agrees
                number[sig] = q
                mine.add((q, last))
            elif len(out) >= _SONG_MAX_PATTERNS:
                number[sig] = None
            else:
                number[sig] = len(out)
                clone_of[len(out)] = q
                mine.add((len(out), last))
                out.append(edited)
        for o in everywhere:
            n = number[sigs[o]]
            if sigs[o] is not None and n is not None:
                new_tracks[o[0]][o[1]] = n
                openers_rung.add(asked[o][1])
    clones = len(clone_of)

    # A rest that got no ring has no use for its cut: only the markers of
    # rests that were given one stay, and a copy keeps what its source kept.
    declined = 0
    for pn, a, m, sr in wanted:
        if (pn, m) in mine or (a == 0 and pn in openers_rung):
            mine.add((pn, m))
        else:
            declined += 1
    for c, q in clone_of.items():
        mine.update({(c, r) for (p, r) in mine if p == q})
    for pn, rows in enumerate(out):
        for r in range(len(rows) // 4):
            if rows[r * 4] != 0xFF and _ring_marker(rows, r) and (pn, r) not in mine:
                rows[r * 4 + 2:r * 4 + 4] = [0, 0]  # an exit no rest took up

    # A command column costs packed bytes (greloc.c packpattern): a pattern
    # this pass pushed past the limit goes back to what it was.
    rolled = 0
    for pn, rows in enumerate(out):
        if packed_pattern_size(pattern_rows(rows)) <= PACKED_PATTERN_LIMIT:
            continue
        bare = list(rows)
        for p, r in mine:
            if p == pn:
                bare[r * 4 + 2:r * 4 + 4] = [0, 0]
        if packed_pattern_size(pattern_rows(bare)) <= PACKED_PATTERN_LIMIT:
            out[pn] = bare
            rolled += 1
    if log is not None and (wanted or wanted_open or unknown or inert):
        log(f"Rest ring-out...........: {len(wanted) - declined} rest(s) "
            f"ring at the held instrument's release, cut on their last tick"
            + (f", {rung_open} tied rest chain(s) ring uncut to the next "
               "note" if rung_open else "")
            + (f", {clones} pattern copy(ies)" if clones else "")
            + (f", {declined} with no free row before them" if declined
               else "")
            + (f", {unknown} whose held instrument could not be settled"
               if unknown else "")
            + (f", {inert} on an instrument whose release is not cut"
               if inert else "")
            + (f", {rolled} pattern(s) put back over the packed-size limit"
               if rolled else ""))
    return out, (new_tracks if tracks else tracks)
