"""Per-pitch-class clones of a byte-code wave-program record.

**The player's `>= $80` opcode writes the frequency HIGH byte only**, so the
pitch it sounds is `hi:lo(note)` (`wave_program._wave_set_note_byte`), and a
slide opcode's target is `note - sum(slides)`. Both depend on the note the
record is played at, and a Goattracker record has ONE wavetable, which names
ONE absolute note (or one semitone count) for all of them. Go_Go_Dash's drum
record `31 04 41 0f dd 00 69 01` sounds `0751`, `0459`, `0836`... for its
last frame on seventeen notes: nine of them straddle the semitone the traced
tuning rounds to, so the single note the wavetable carries is right for 136
of its 224 hits and a semitone off for the other 88 (measured v0.5.670,
`heard.py`: 3.4 points of the song's 2552 notes). The values are not off the
grid, they are a per-note function of the pitch the record is played at.

The cure is the one the phase splits already make: clone the record per
class of notes, and rename each note to its class's clone
(`arpeggio._note_phase_split`). A class here is the notes whose block --
`_wave_program_entries` over that note alone -- is the same bytes, so the
residue is a `NotePitch`, the heaviest note of its class, and the record's
own residue (the block its pooled distribution already writes) is `MAJOR`.
A class below `MIN_SHARE` of the record's plays stays on the record: a stray
costs less as a note one semitone off than as an instrument and a block.

Only a record whose block `_wave_program_entries` writes from the played
pitches can differ by note, so every other record's probes return the
record's own block and no clone is made.
"""
from __future__ import annotations

from collections import Counter
from dataclasses import dataclass
from typing import Callable, Dict, List, Optional, Set

from .arpeggio import _note_phase_split, _orderlist_occurrences
from .constants import CMD_TONEPORTA, GT_FIRST_NOTE, GT_LAST_NOTE

# Switched off by `tests/test_note_pitch_split.py`, which proves the plan is
# what moves the bytes.
ENABLED = True

# A class heard less than this share of its record's plays, or fewer than
# `MIN_PLAYS` times, keeps the record's block: of the seven corpus files the
# first cut moved, the four whose clones stood on 2 to 8 plays (Lakers,
# Star_Paws, Sun_Never_Shines, Wiz) moved nothing the heard census counts and
# read `aud` -0.0008 / -0.0002 (Lakers, Star_Paws).
MIN_SHARE = 0.03
MIN_PLAYS = 10

# GT_TRANSPOSE_UP (`patterns`): an orderlist byte `$E0`-`$FE` is a transpose.
_TRANSPOSE_ZERO = 0xF0


@dataclass(frozen=True, order=True)
class NotePitch:
    """A note class's residue: the played note index (the transpose added,
    relative to `GT_FIRST_NOTE`) of its heaviest member."""
    note: int


# The residue of the record's own block.
MAJOR = NotePitch(-1000)


def _transposes(track: List[int]) -> Dict[int, int]:
    """{orderlist position of a pattern byte: the transpose it plays under}."""
    out: Dict[int, int] = {}
    trans, operand = 0, False
    for pos, b in enumerate(track):
        if operand:
            operand = False
        elif b == 0xFF:
            operand = True
        elif 0xE0 <= b < 0xFF:
            trans = b - _TRANSPOSE_ZERO
        elif 0xD0 <= b < 0xE0:
            continue
        else:
            out[pos] = trans
    return out


def _same_shape(own, block) -> bool:
    """Whether `block` is `own` with other right-hand bytes only: the same
    entries, the same left column. A clone that changes what the record DOES
    (a slide frame that falls back to a portamento, a frame the budget
    drops) moves the pulse, filter and travel columns with it (Mega_Apocalypse
    reads 1326 slides against 709 when its notes are laid out one by one);
    what the cloning is for is the note a frame names."""
    if own is None or block is None:
        return False
    try:
        return len(own) == 2 and len(block) == 2 and own[0] == block[0]
    except TypeError:
        return False


def note_classes(note_pitches: Dict[int, Dict[int, int]], lead: int,
                 instr_used: int,
                 blocks: Callable[[list], dict]
                 ) -> Dict[int, Dict[int, NotePitch]]:
    """{record GT number: {note index: its class's residue}} for every record
    some of whose notes lay out a block other than the record's own.

    `blocks(keys)` answers {(record, residue): the block as a hashable, None
    where there is none}, a residue of None being the record's own
    (`_arp_phase_distinct`'s `.blocks`). Notes on the record's block, those
    of its heaviest class, and any class under `MIN_SHARE` of the record's
    plays are `MAJOR`.
    """
    records = [g for g, plays in sorted(note_pitches.items())
               if lead < g <= instr_used and len(plays) >= 2]
    if not records:
        return {}
    keys = [(g, None) for g in records]
    keys += [(g, NotePitch(n)) for g in records
             for n in sorted(note_pitches[g])]
    got = blocks(keys)
    out: Dict[int, Dict[int, NotePitch]] = {}
    for g in records:
        own = got.get((g, None))
        if own is None:
            continue
        plays = note_pitches[g]
        groups: Dict[object, List[int]] = {}
        for n in sorted(plays):
            b = got.get((g, NotePitch(n)))
            if b is None:
                continue
            groups.setdefault(b, []).append(n)
        if len(groups) < 2:
            continue
        total = sum(plays.values())
        # The heaviest class keeps the record's own block, which was laid out
        # for the pooled distribution and so for it first: a clone only ever
        # replaces the block of a note the record's block serves less well.
        heaviest = max(groups, key=lambda b: (
            sum(plays[n] for n in groups[b]), b == own,
            -min(groups[b])))
        mapping: Dict[int, NotePitch] = {}
        for b, members in groups.items():
            if b == heaviest or b == own or not _same_shape(own, b):
                continue
            if sum(plays[n] for n in members) < max(MIN_PLAYS, MIN_SHARE * total):
                continue
            rep = NotePitch(max(members, key=lambda n: (plays[n], -n)))
            for n in members:
                mapping[n] = rep
        if mapping:
            out[g] = mapping
    return out


def note_residues(tracks: List[List[int]], patterns: List[List[int]],
                  classes: Dict[int, Dict[int, NotePitch]]) -> dict:
    """{(track, orderlist position, play): {row: residue}} for every untied
    note played on a record in `classes`, the walk `_note_phase_split` votes
    and renames over (the instrument column sticky, a tie restarting no
    wavetable and so taking none)."""
    out: dict = {}
    for ti, track in enumerate(tracks):
        trans = _transposes(track)
        seen: Counter = Counter()
        cur = 0
        for pos, p in _orderlist_occurrences(track):
            if p >= len(patterns):
                continue
            play = seen[pos]
            seen[pos] += 1
            pat = patterns[p]
            res: dict = {}
            for k in range(len(pat) // 4):
                if pat[k * 4] == 0xFF:
                    break
                if pat[k * 4 + 1]:
                    cur = pat[k * 4 + 1]
                if not (GT_FIRST_NOTE <= pat[k * 4] <= GT_LAST_NOTE):
                    continue
                if pat[k * 4 + 2] == CMD_TONEPORTA and pat[k * 4 + 3] == 0:
                    continue
                mapping = classes.get(cur)
                if mapping is None:
                    continue
                n = pat[k * 4] - GT_FIRST_NOTE + trans.get(pos, 0)
                res[k] = mapping.get(n, MAJOR)
            if res:
                out[(ti, pos, play)] = res
    return out


def note_pitch_split_plan(tracks: List[List[int]],
                          patterns: List[List[int]],
                          note_pitches: Optional[Dict[int, Dict[int, int]]],
                          lead: int, instr_used: int, first_clone: int,
                          blocks: Callable[[list], dict], log=None):
    """The split, or None where no record's notes differ in their blocks.

    `_note_phase_split` over `note_residues`: one clone per minority class of
    a record, numbered most-heard first and renamed on the notes that play
    them; the factor is None because a class is already filtered by share
    here.
    """
    if not ENABLED or not note_pitches:
        return None
    classes = note_classes(note_pitches, lead, instr_used, blocks)
    if not classes:
        return None
    residues = note_residues(tracks, patterns, classes)
    if not residues:
        return None
    phases = {g: MAJOR for g in classes}
    records: Set[int] = set(classes)
    return _note_phase_split(tracks, patterns, residues, phases, records,
                             first_clone, None, "note pitch split", log,
                             factor=None)
