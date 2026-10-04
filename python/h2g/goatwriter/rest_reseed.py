"""The zero-page triangle dialect's pulse reseed on a REST event.

Samantha Fox and Spellbound (`Detection.pulse_tri_per_voice`) reseed the
per-voice pulse accumulator on EVERY event the voice fetches, and a rest is
an event. The rest branch only decrements the gate mask and then falls into
the same fetch tail as a note:

    Samantha Fox  $70B6 BIT $B8 / BVS $70F6      (status bit 6: a rest)
                  $70F3 JMP $70F8                (the note path, after freq)
                  $70F6 DEC $B7                  (gate mask $FF -> $FE)
                  $70F8 LDY $73F6 ...            (the shared tail:)
                  $7110 LDA $7407,X / STA $D402,Y / PHA
                  $7117 LDA $7408,X / STA $D403,Y / PHA
                  $712C LDA #0 / STA $C6,X / STA $C3,X   (direction up, delay)
                  $7132 PLA / STA $E0,X / PLA / STA $DC,X (the accumulator)
    Spellbound    $E0DD BIT $E4CD / BVS $E11C, $E119 JMP $E11E,
                  $E11C DEC $C6, the tail at $E11E reseeding at $E13C-$E162

so across a rest the original's sweep starts again from the record's width,
direction up, with the voice's CURRENT record (`$B3,X` / `$C3,X`, which a
rest event does not change). A Goattracker KEYOFF clears the gate and
nothing else (gplay.c:920), so our pulse program kept climbing through the
release. That -- and NOT the rate mask, which left both spans where they
were -- is what widened the band (180 s, presets, at 42f3f4a): Spellbound
voice 0 reseeds on $200 at every rest and never passes $AA0 while ours ran
on to the $E00 bound, span 3072 against 2208; Samantha Fox voice 3 sweeps
on through one rest after a long note to $DF1 against the original's $AE0,
2756 against 1984. (The rests only became KEYOFF rows at all once
`detect._status_bit6_bvs` read these players' zero-page spelling of the
bit-6 test.)

MEASURED (fidelity.py -t 180 --sound --presets, A/B against 42f3f4a):
Spellbound voice 0 span 3072 -> 2230 (original 2208), pspan 1.16 -> 1.02,
gate 49% -> 58%; Samantha Fox voice 3 2756 -> 1763 (1984), gate 67% ->
94%; melody, retrig, slides and `pul` unmoved on both, `depth` 0.81 ->
0.80 and 1.05 -> 1.04 (part of this is the KEYOFF reading, which also
moved Mega_Apocalypse -- see `detect._status_bit6_bvs`). Samantha Fox
voice 1 falls 2280 -> 1566 against 2320 and its file pspan 1.11 -> 0.85:
that 2280 was the run-on through rests, and what is left is the tie
below, now visible.

`CMD_SETPULSEPTR` on the KEYOFF row is the reseed: it points the channel
at the instrument's own pulse program and zeroes the step timer
(gplay.c:447-450, player.s `mt_tick0_9`), whose first entry sets the
record's width and starts the ascent -- the player's state after
`$712C-$7136`.

Written only where it is SAFE, every other case counted and logged:

* **the channel's running command must be `CMD_DONOTHING`.** A one-shot
  command on a row leaves a running portamento, toneporta or vibrato
  command running (gplay.c:404-421: only `CMD_DONOTHING` resets
  `cptr->command`; player.s `mt_tick0_0`), so a reseed on the row after a
  slide would carry the slide into the rest where the original's fetch
  ends it (`$70A4 STA $D0,X`).
* **that instrument's record must sweep** under this engine
  (`_pulse_tri_program`): a static record's reseed rewrites the width the
  channel already holds, so it costs a command and changes nothing;
* **the command column must be free** -- or hold `CMD_TONEPORTA 00`, the
  tie `_build_raw_pattern`'s `pending_tie` spells onto a rest after a
  status-bit-5 note (its guard excludes GT_NO_NOTE, not KEYOFF). Both
  players read TONEPORTA as "no gate-off" only for a real note
  (gplay.c:925-928 `newnote <= LASTNOTE`, player.s `mt_normalnote`), so on
  a KEYOFF it ties nothing. Spellbound voice 0's rests in its opening
  patterns ($2B-$32) all carry one.
* **every pass through the position must agree.** The state is walked per
  ORDERLIST POSITION -- instrument and running command carried in play
  order, repeats unrolled, the restart lapped once (`_lapped_tracks`) --
  and a row is written only where every visit of that position wants the
  same write. A pattern its positions want differently is CLONED, one copy
  per distinct write set, and those positions repointed: Samantha Fox's
  rest patterns `$00`/`$51` are entered holding eleven different
  instruments across the file, and its voice 3 enters `$00` holding
  instrument 3. Past `_SONG_MAX_PATTERNS` the clone is dropped, counted.

It runs after every other pass that fills a command column, so it takes
only columns nobody wanted, and it returns new orderlists for the caller to
write back over the ones it already emitted (their lengths do not change).

**What this does not do by default: the tie.** The player reseeds on a
TIED note too (the same tail), and a tie row's column is its
`CMD_TONEPORTA`, which skips the instrument's pulse load (gplay.c:354/375),
so ours keeps the previous record's sweep -- Samantha Fox voice 1's ties
into instrument 7 (rate $50) go on at instrument 6's +$18 a frame. `ties`
writes the reseed on the tie's first free hold row instead, and it was
measured and DECLINED (180 s, presets, against the rest-only tree):
`_tied_instrument_envelopes` has already put SR before the tie and AD on
its first hold row, so the reseed lands two rows late (frame 313 against
the original's 301 on voice 1, 6 frames net of the conversion's own 6-frame
lag at the attack before it), and the one-shot there keeps the tie's
TONEPORTA 00 running a row longer, pinning the pitch. Samantha Fox voice 1 span 1566 -> 1888 (original 2320),
but `bend` 0.92 -> 0.89, `depth` 0.80 -> 0.78, `slides` 4064 -> 4027:
pulse bought with pitch, and still short. A placement that does not cost
the pitch is the open question.
"""
from __future__ import annotations

from typing import Dict, List, Tuple

from ..detect import Detection
from ..sidfile import SidFile
from .constants import (CMD_SETPULSEPTR, CMD_TONEPORTA, GT_FIRST_NOTE,
                        GT_KEYOFF, GT_LAST_NOTE, _SONG_MAX_PATTERNS)
from .note_passes import _lapped_tracks
from .pulse import _pulse_tri_program


def _rest_reseed_pattern(pattern: List[int], instr: int, running: int,
                         starts: dict, sweeps: set,
                         ties: bool = True) -> tuple:
    """One pass of one pattern from one entry state: (writes, skips, instr,
    running) -- `writes` the frozenset of (row, pulse start) this pass
    wants, `skips` the (row, reason) owed a reseed and not given one, the
    last two the state it leaves. `starts` is every instrument's pulse
    start, `sweeps` the instruments whose record this engine sweeps. `ties`
    also reseeds after a tie (module docstring)."""
    writes, skips = set(), set()
    # A tie's reseed, owed on its first free hold row: (start, tie row).
    owed = None
    for r in range(0, len(pattern) - 3, 4):
        note, named, cmd, data = pattern[r:r + 4]
        if note == 0xFF:
            break
        held = instr
        if named:
            instr = named
        is_tie = cmd == CMD_TONEPORTA and data == 0
        if GT_FIRST_NOTE <= note <= GT_LAST_NOTE:
            if owed is not None:
                skips.add((owed[1], "tie unplaced"))
            # Owed where the sweep restarts (a sweeping record) or the
            # record changes (the player writes the new record's width).
            owed = ((starts[instr], r // 4) if ties and is_tie
                    and instr in starts
                    and (instr in sweeps or instr != held) else None)
        elif note == GT_KEYOFF:
            if owed is not None:
                skips.add((owed[1], "tie unplaced"))
            owed = None
            if instr in sweeps and instr in starts:
                if cmd and not is_tie:
                    skips.add((r // 4, "taken"))
                elif running:
                    skips.add((r // 4, "running"))
                else:
                    writes.add((r // 4, starts[instr]))
                    continue    # SETPULSEPTR is one-shot: running stays 0
        elif owed is not None and not named and cmd == 0 and running in (
                0, CMD_TONEPORTA):
            # The tie's hold row: a one-shot here leaves the tie's
            # TONEPORTA 00 running one row longer, which pins the pitch to
            # the note it already sounds (gplay.c:810-814).
            writes.add((r // 4, owed[0]))
            owed = None
            continue
        if cmd <= 4:
            running = cmd
    if owed is not None:
        skips.add((owed[1], "tie unplaced"))
    return frozenset(writes), frozenset(skips), instr, running


def _rest_reseed_plan(tracks: List[List[int]], patterns: List[List[int]],
                      starts: dict, sweeps: set,
                      ties: bool = True) -> tuple:
    """(plan, skipped): `plan` maps (track index, orderlist position) to
    the writes every visit of that position agrees on; `skipped` counts,
    by reason, the (position, row) pairs owed a reseed that got none.
    Walked as `_entry_instruments` walks (instrument 1 and command 0 before
    any row, gplay.c:62/:190/:223; transposes skipped; a repeat is that
    many visits), with the restart lapped once."""
    plan: Dict[Tuple[int, int], frozenset] = {}
    missed: set = set()
    for ti, track in enumerate(tracks):
        end = track.index(0xFF) if 0xFF in track else len(track)
        restart = track[end + 1] if end + 1 < len(track) else None
        laps = [range(0, end)]
        if restart is not None and restart < end:
            laps.append(range(restart, end))
        instr, running = 1, 0
        for lap in laps:
            repeat = 1
            for pos in lap:
                b = track[pos]
                if 0xE0 <= b < 0xFF:
                    continue
                if 0xD0 <= b < 0xE0:
                    repeat = b - 0xD0 + 1
                    continue
                if b >= len(patterns):
                    repeat = 1
                    continue
                for _ in range(repeat):
                    want, skips, instr, running = _rest_reseed_pattern(
                        patterns[b], instr, running, starts, sweeps, ties)
                    key = (ti, pos)
                    missed |= {(key, row, why) for row, why in skips}
                    if key in plan and plan[key] != want:
                        missed |= {(key, row, "disagree")
                                   for row, _ in plan[key] ^ want}
                        want = plan[key] & want
                    plan[key] = want
                repeat = 1
    skipped: dict = {}
    for _key, _row, why in missed:
        skipped[why] = skipped.get(why, 0) + 1
    return plan, skipped


def rest_pulse_reseeds(sid: SidFile, det: Detection,
                       tracks: List[List[int]], patterns: List[List[int]],
                       pulse_starts: List[int], instr_used: int, lead: int,
                       multiplier: int, log=None, ties: bool = False) -> tuple:
    """(patterns, tracks, written): `CMD_SETPULSEPTR` on every KEYOFF row
    -- and, with `ties`, the first free hold row after a tie -- whose
    channel the zero-page triangle player would reseed, under the module
    docstring's conditions. Changed patterns and tracks are COPIES; clones
    are appended. A no-op unless `det.pulse_tri_per_voice`."""
    if not det.pulse_tri_per_voice or det.pulse_tri_hi < 0:
        return patterns, tracks, 0
    # GT instrument number -> its pulse program's first entry. Record i is
    # instrument i + lead + 1 and its pointer is `pulse_starts[i + lead]`
    # (`_write_instruments`); `sweeps` are the ones this engine sweeps.
    starts: dict = {}
    sweeps: set = set()
    for i in range(max(instr_used - lead, 0)):
        if i + lead >= len(pulse_starts) or not pulse_starts[i + lead]:
            continue
        starts[i + lead + 1] = pulse_starts[i + lead] & 0xFF
        if _pulse_tri_program(sid, det, i, multiplier) is not None:
            sweeps.add(i + lead + 1)
    if not sweeps:
        return patterns, tracks, 0
    plan, skipped = _rest_reseed_plan(tracks, patterns, starts, sweeps, ties)
    # pattern -> {writes: [(track, position), ...]}
    groups: Dict[int, Dict[frozenset, list]] = {}
    for (ti, pos), want in plan.items():
        groups.setdefault(tracks[ti][pos], {}).setdefault(want, []).append(
            (ti, pos))
    out = list(patterns)
    new_tracks = [list(t) for t in tracks]
    written = clones = full = 0

    def patched(b: int, want: frozenset) -> List[int]:
        rows = list(patterns[b])
        for row, start in want:
            rows[4 * row + 2], rows[4 * row + 3] = CMD_SETPULSEPTR, start
        return rows

    for b in sorted(groups):
        by_want = groups[b]
        wanted = [w for w in by_want if w]
        if not wanted:
            continue
        # The pattern keeps the positions that want nothing, or else the
        # largest group; every other group gets a copy of its own.
        if frozenset() in by_want:
            stays = frozenset()
        else:
            stays = max(wanted, key=lambda w: (len(by_want[w]), sorted(w)))
            out[b] = patched(b, stays)
            written += len(stays) * len(by_want[stays])
        for want in sorted((w for w in wanted if w != stays), key=sorted):
            if len(out) >= _SONG_MAX_PATTERNS:
                full += len(by_want[want])
                continue
            out.append(patched(b, want))
            clones += 1
            for ti, pos in by_want[want]:
                new_tracks[ti][pos] = len(out) - 1
            written += len(want) * len(by_want[want])
    if log and (written or skipped or full):
        log(f"Rest pulse reseed.......: CMD_SETPULSEPTR on {written} "
            f"row(s) over the orderlists, {clones} pattern copy(ies)"
            + "".join(f", {n} {why}" for why, n in sorted(skipped.items()))
            + (f", {full} position(s) left alone: pattern table full"
               if full else ""))
    return out, new_tracks, written
