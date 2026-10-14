"""A triangle sweep follows the clock it sounds at: one pulse program per
(record, clock class), chosen note by note.

`pulse.track_set_tick_ratios` gives each record ONE speed under an outer gate
the TRACK reloads (Rasputin's `$FE nn`): the record's mean clock. Rasputin's R
runs 2, 3, 5, 10, 60, 120, 6, 2 along subtune 0, and the original's sweep
covers 128 * R / (R + 1) width a frame (85.3, 96.0, 105.1, 114.6, 125.7,
127.5 for R = 2, 3, 5, 10, 60, 120, measured at 0d18fce), so one speed ran
43% fast at R = 2 and 4% slow at R = 120. A Goattracker pulse program is per
INSTRUMENT, and an instrument can be cloned and chosen per note: the way
`arpeggio.tempo_duty_split_plan` gives Rasputin's R = 2 notes a duty
arpeggio of their own.

Two stages, because the pulse table is laid out before the instrument bytes
are final and the clones are numbered after every other pass:

* `tri_clock_plan`, EARLY, on the patterns as `pulse_usage` sees them: for
  each swept record the notes whose clock the record's own program (the
  `track_set_tick_ratios` mean) misses by more than `CLOCK_BAND` are grouped
  into at most `MAX_CLOCK_CLASSES` classes of one speed each
  (`clock_classes`), and every note, in every subtune, is given the class
  nearest its clock. A note's clock is `ClockNote.around`, the section's
  rows-averaged clock, not its own few rows, which the fractional-row
  compensation commands (`patterns._compensate_fractional_rows`) make noisy.
* `tri_clock_split_plan`, LAST, on the finished patterns: each swept
  instrument's notes are renamed to the clone of their class, a pattern
  played under two classes copied, a sticky instrument named where the walk
  needs it -- `tempo_duty_split_plan`'s discipline, on instrument numbers
  rather than records, so a clone another pass made of a swept record is
  split as the record is.

A class whose notes cannot be spelled (no instrument number, no pulse-table
room, no pattern number) is dropped, least heard first, and its notes keep the
record's own program: the file is never worse than before.
"""
from __future__ import annotations

from collections import Counter
from dataclasses import dataclass, field
from fractions import Fraction
from typing import Dict, List, Optional, Set, Tuple

from ..detect import Detection
from ..sidfile import SidFile
from .arpeggio import (apply_tempo_duty_edits, TempoDutySplit,
                       _orderlist_occurrences)
from .constants import (CMD_TONEPORTA, GT_FIRST_NOTE, GT_LAST_NOTE,
                        GT_MAX_TABLELEN, TEMPO_DUTY_MAX_CLONE,
                        _SONG_MAX_PATTERNS)
from .note_passes import clone_number_ceiling
from .pulse import (_clock_notes, _pulse_lo_program, _pulse_tri_program)
from . import tempo as _gw_tempo

# A note whose clock the record's own speed misses by no more than this keeps
# the record (rate error = clock / own - 1). Rasputin's record 0 (own x1.057)
# keeps R = 10, 60 and 120 at +4%, -4.5% and -3.6%.
CLOCK_BAND = Fraction(7, 100)

# The most a class's own speed may miss a note it serves, before a further
# class is made.
CLOCK_TOLERANCE = Fraction(6, 100)

# Clone classes per record. Rasputin's record 0 needs three: R = 5 / 6, R = 3
# and R = 2 are 1.17 .. 1.5 calls a tick apart, and two classes leave the
# ends 9-10% off.
MAX_CLOCK_CLASSES = 3


@dataclass
class TriClockPlan:
    """What `tri_clock_plan` decided.

    `own` is the per-record ratio the record's own program is laid out with
    (`track_set_tick_ratios`); `classes[record]` the ratios of its clone
    classes, class 1 upward; `notes[(track, position, row)]` is
    (record, class, ticks), class 0 being the record's own program."""
    own: Dict[int, Fraction]
    classes: Dict[int, List[Fraction]] = field(default_factory=dict)
    notes: Dict[Tuple[int, int, int], Tuple[int, int, int]] = field(
        default_factory=dict)


def tri_swept(sid: SidFile, det: Detection, i: int, multiplier: int,
              ratio: Optional[Fraction]) -> bool:
    """Whether record `i` gets a triangle-engine sweep from `_pulse_program`
    (the same routing: the accumulate engine is asked first)."""
    if det.pulse_bounds >= 0 or det.pulse_tri_hi < 0:
        return False
    if (det.pulse_lo_base >= 0
            and _pulse_lo_program(sid, det, i, multiplier) is not None):
        return False
    return _pulse_tri_program(sid, det, i, multiplier,
                              tick_ratio=ratio) is not None


def clock_classes(items: List[Tuple[Fraction, int]], own: Fraction,
                  band: Fraction = CLOCK_BAND,
                  tolerance: Fraction = CLOCK_TOLERANCE,
                  limit: int = MAX_CLOCK_CLASSES) -> List[Fraction]:
    """The clone classes' ratios, ascending, for notes given as (clock in
    calls per tick over `multiplier`, weight).

    A note within `band` of `own` is the record's. The rest are cut into at
    most `limit` runs of neighbouring clocks, each served by its weighted
    mean (the way `track_set_tick_ratios` makes a record's), by dynamic
    programming over the distinct clocks: the fewest runs whose worst note
    is within `tolerance`, else `limit` runs of least worst error."""
    far: Dict[int, List[int]] = {}
    for r, w in items:
        if abs(r / own - 1) > band:
            slot = far.setdefault(round(r * 1000), [0, 0])
            slot[0] += w * round(r * 1000)
            slot[1] += w
    if not far:
        return []
    vals = [(Fraction(k, 1000), far[k][1], Fraction(far[k][0], 1000 * far[k][1]))
            for k in sorted(far)]
    n = len(vals)

    def cut(i: int, j: int):
        """(rep, worst error) of the run vals[i..j]."""
        w = sum(v[1] for v in vals[i:j + 1])
        rep = sum(v[1] * v[0] for v in vals[i:j + 1]) / w
        return rep, max(abs(vals[i][0] / rep - 1), abs(vals[j][0] / rep - 1))

    best: Dict[Tuple[int, int], Tuple[Fraction, int]] = {}
    for j in range(n):
        best[(1, j)] = (cut(0, j)[1], -1)
    for k in range(2, limit + 1):
        for j in range(n):
            cand = None
            for i in range(1, j + 1):
                prev = best.get((k - 1, i - 1))
                if prev is None:
                    continue
                err = max(prev[0], cut(i, j)[1])
                if cand is None or err < cand[0]:
                    cand = (err, i)
            if cand is not None:
                best[(k, j)] = cand
    chosen = limit
    for k in range(1, limit + 1):
        got = best.get((k, n - 1))
        if got is not None and got[0] <= tolerance:
            chosen = k
            break
    chosen = min(chosen, n)
    runs, j, k = [], n - 1, chosen
    while k >= 1 and j >= 0:
        i = best[(k, j)][1] if k > 1 else 0
        runs.append((i, j))
        j, k = i - 1, k - 1
    return sorted(Fraction(cut(i, j)[0]).limit_denominator(1000)
                  for i, j in runs)


def tri_clock_plan(sid: SidFile, det: Detection, tracks: List[List[int]],
                   patterns: List[List[int]], lead: int, multiplier: int,
                   own: Dict[int, Fraction], log=None
                   ) -> Optional[TriClockPlan]:
    """The classes of every swept record in `own` (`track_set_tick_ratios`),
    or None where no record has more than the one. The records' own ratios
    are `own`, untouched, so a record with one class is laid out as before."""
    if not own:
        return None
    swept = [i for i in sorted(own) if tri_swept(sid, det, i, multiplier,
                                                 own[i])]
    if not swept:
        return None
    walked = _clock_notes(sid, det, tracks, patterns, lead, multiplier)
    if walked is None:
        return None
    speeds, groups = walked
    pack = _gw_tempo.pack_subtune(speeds, sid.start_song)
    plan = TriClockPlan(own=dict(own))
    for rec in swept:
        # The pack subtune's notes make the classes where it sounds the
        # record, as `track_set_tick_ratios` makes the mean.
        pool = ([groups[pack]] if pack < len(groups)
                and any(n.record == rec for n in groups[pack]) else groups)
        items = [(n.around / multiplier, n.ticks)
                 for g in pool for n in g if n.record == rec]
        reps = clock_classes(items, own[rec])
        if not reps:
            continue
        choices = [own[rec]] + reps
        # A key is one note row of one orderlist entry: its plays (a repeat,
        # a second lap) share one class, chosen by their mean clock.
        agg: Dict[Tuple[int, int, int], List] = {}
        for g in groups:
            for n in g:
                if n.record == rec:
                    slot = agg.setdefault(n.key, [Fraction(0), 0])
                    slot[0] += n.around * n.ticks
                    slot[1] += n.ticks
        heard = Counter()
        mine = {}
        for key, (weighted, ticks) in agg.items():
            r = weighted / ticks / multiplier
            cls = min(range(len(choices)),
                      key=lambda c: (abs(r / choices[c] - 1), c))
            mine[key] = (rec, cls, ticks)
            heard[cls] += ticks
        used = sorted(c for c in heard if c)
        if not used:
            continue
        # Renumber to the classes anything is assigned to.
        renumber = {c: k + 1 for k, c in enumerate(used)}
        renumber[0] = 0
        plan.classes[rec] = [choices[c] for c in used]
        for key, (r_, cls, ticks) in mine.items():
            plan.notes[key] = (r_, renumber[cls], ticks)
        if log:
            log(f"Pulse sweep clock......: record {rec} x{float(own[rec]):.3f}"
                f" + {len(used)} clone class(es) "
                + ", ".join(f"x{float(choices[c]):.3f}" for c in used))
    return plan if plan.classes else None


def tri_clock_split_plan(tracks: List[List[int]], patterns: List[List[int]],
                         plan: TriClockPlan, sweep_of: Dict[int, int],
                         first_clone: int, last_clone: int,
                         unavailable: Set[Tuple[int, int]] = frozenset(),
                         log=None) -> Optional[TempoDutySplit]:
    """Rename the notes of every instrument in `sweep_of` ({GT number:
    record}) to the clone of their class. `clones` of the result are (GT
    number, clone GT number, class), numbered from `first_clone` to at most
    `last_clone`; `edits` are the instrument bytes `apply_tempo_duty_edits`
    writes. None where nothing would change.

    A class in `unavailable` ((record, class): no pulse-table room) keeps the
    record's program, as does one dropped for want of an instrument number or
    a pattern number, least heard first."""
    dropped: Set[Tuple[int, int]] = set(unavailable)
    heard = Counter()
    for rec, cls, ticks in plan.notes.values():
        if cls:
            heard[(rec, cls)] += ticks
    while True:
        got, over = _tri_split_once(tracks, patterns, plan, sweep_of,
                                    first_clone, last_clone, dropped, log)
        if not over:
            return got
        live = [k for k in heard if k not in dropped]
        if not live:
            return None
        gone = min(live, key=lambda k: (heard[k], k))
        dropped.add(gone)
        if log:
            log(f"tri clock split: giving up record {gone[0]} class "
                f"{gone[1]} ({over})")


def _tri_split_once(tracks, patterns, plan, sweep_of, first_clone,
                    last_clone, dropped, log):
    """(split, why it is over budget). `why` is falsy when the plan was made,
    or declined for a reason no smaller plan cures (then the split is None)."""
    groups = len(tracks) // 3
    clone_of: Dict[Tuple[int, int], Optional[int]] = {}
    wants: dict = {}
    for grp in range(groups):
        for v in range(3):
            ti = 3 * grp + v
            cur = new_cur = 0
            for pos, p in _orderlist_occurrences(tracks[ti]):
                if p >= len(patterns):
                    continue
                pat = patterns[p]
                rows = []
                for r in range(0, len(pat), 4):
                    if pat[r] == 0xFF:
                        break
                    rows.append(r // 4)
                # Which class each swept instrument's notes want in this play,
                # by the time they sound.
                c, per = cur, {}
                for k in rows:
                    if pat[k * 4 + 1]:
                        c = pat[k * 4 + 1]
                    if c in sweep_of and GT_FIRST_NOTE <= pat[k * 4] <= GT_LAST_NOTE:
                        note = plan.notes.get((ti, pos, k))
                        if note is not None and note[0] == sweep_of[c]:
                            cls = note[1]
                            if cls and (note[0], cls) in dropped:
                                cls = 0
                            per.setdefault(c, Counter())[cls] += max(
                                note[2], 1)
                rename = {}
                for g, votes in per.items():
                    cls = min(votes, key=lambda x: (-votes[x], x))
                    if cls:
                        clone_of.setdefault((g, cls), None)
                        rename[g] = (g, cls)
                edit = {}
                for k in rows:
                    b = pat[k * 4 + 1]
                    if b in rename:
                        edit[k] = (b, rename[b])
                # The sticky instrument this play inherits: name it on the
                # first note that relies on it where the new walk carries a
                # different one in from the previous play.
                want_in = rename.get(cur, cur)
                if new_cur != want_in:
                    for k in rows:
                        if pat[k * 4 + 1]:
                            break
                        if GT_FIRST_NOTE <= pat[k * 4] <= GT_LAST_NOTE:
                            if pat[k * 4 + 2] == CMD_TONEPORTA:
                                if log:
                                    log("tri clock split: a sticky "
                                        "instrument lands on a tie; "
                                        "not splitting")
                                return None, ""
                            edit[k] = (0, want_in)
                            break
                key = tuple(sorted(edit.items(),
                                   key=lambda kv: (kv[0], kv[1][0])))
                if wants.setdefault((ti, pos), key) != key:
                    if log:
                        log("tri clock split: a repeated entry needs two "
                            "spellings; not splitting")
                    return None, ""
                for k in rows:
                    b = pat[k * 4 + 1]
                    if b:
                        cur = b
                        e = edit.get(k)
                        new_cur = (e[1] if e else b)
                    elif k in edit:
                        new_cur = edit[k][1]
    if not clone_of:
        return None, ""
    number = first_clone - 1
    clones = []
    for g, cls in sorted(clone_of):
        number += 1
        clone_of[(g, cls)] = number
        clones.append((g, number, cls))
    if number > last_clone:
        return None, f"{number - first_clone + 1} clones, room for " \
                     f"{last_clone - first_clone + 1}"

    def resolve(key):
        return tuple((k, (old, w if isinstance(w, int) else clone_of[w]))
                     for k, (old, w) in key)

    by_pat: dict = {}
    for (ti, pos), key in wants.items():
        by_pat.setdefault(tracks[ti][pos], Counter())[resolve(key)] += 1
    new_tracks = [list(t) for t in tracks]
    new_patterns = [list(p) for p in patterns]
    edits: dict = {}
    copy_of: dict = {}
    for p, spellings in sorted(by_pat.items()):
        stay = max(spellings, key=lambda s: (spellings[s], not s))
        if stay:
            edits[p] = dict(stay)
        for s in spellings:
            if s == stay:
                continue
            copy_of[(p, s)] = len(new_patterns)
            if s:
                edits[len(new_patterns)] = dict(s)
            new_patterns.append(list(patterns[p]))
    if len(new_patterns) > _SONG_MAX_PATTERNS:
        return None, (f"{len(new_patterns) - len(patterns)} pattern copies "
                      f"pass {_SONG_MAX_PATTERNS} patterns")
    for (ti, pos), key in wants.items():
        n = copy_of.get((tracks[ti][pos], resolve(key)))
        if n is not None:
            new_tracks[ti][pos] = n
    if not edits:
        return None, ""
    if log:
        log(f"tri clock split: {len(clones)} clone(s) {clones}, "
            f"{len(new_patterns) - len(patterns)} pattern copy(ies), "
            f"{sum(len(e) for e in edits.values())} instrument byte(s)")
    return TempoDutySplit(new_tracks, new_patterns, clones, edits), ""


def extra_programs(sid: SidFile, det: Detection, plan: TriClockPlan,
                   multiplier: int, entries: int,
                   wanted: Optional[Set[Tuple[int, int]]] = None
                   ) -> Tuple[List[tuple], Dict[Tuple[int, int], int],
                              Set[Tuple[int, int]]]:
    """The pulse blocks of every clone class (or of `wanted`, as (record,
    class)), to append to a table that already holds `entries` rows: (the
    rows, {(record, class): 1-based start}, the classes that do not fit)."""
    rows: List[tuple] = []
    starts: Dict[Tuple[int, int], int] = {}
    lost: Set[Tuple[int, int]] = set()
    for rec in sorted(plan.classes):
        for cls, ratio in enumerate(plan.classes[rec], 1):
            if wanted is not None and (rec, cls) not in wanted:
                continue
            program = _pulse_tri_program(sid, det, rec, multiplier,
                                         tick_ratio=ratio)
            if program is None:
                lost.add((rec, cls))
                continue
            entries_, loop = program
            start = entries + len(rows) + 1
            block = (list(entries_) if loop is None
                     else list(entries_) + [(0xFF, start + loop)])
            if entries + len(rows) + len(block) > GT_MAX_TABLELEN:
                lost.add((rec, cls))
                continue
            starts[(rec, cls)] = start
            rows += block
    return rows, starts, lost


def tri_clock_clones(sid: SidFile, det: Detection, plan: TriClockPlan,
                     tracks: List[List[int]], patterns: List[List[int]],
                     out: bytearray, instr_at: int, written: int,
                     pulse_entries: List[tuple], pulse_starts: List[int],
                     lead: int, multiplier: int, log=None):
    """The finished instrument table's swept instruments split by clock class.

    `out` ends with the last instrument record (`written` of them, the table
    at `instr_at`): this appends the clones' records, extends `pulse_entries`
    with the classes' programs, and returns (tracks, patterns, written,
    [(instrument, clone)]) -- the inputs unchanged where no clone is made.
    An instrument is swept when its pulse pointer is the start of a record's
    own triangle program in `pulse_entries` (a record that fell back to its
    static pair is not)."""
    sweep_of: Dict[int, int] = {}
    for rec in plan.classes:
        program = _pulse_tri_program(sid, det, rec, multiplier,
                                     tick_ratio=plan.own[rec])
        at = pulse_starts[lead + rec] if lead + rec < len(pulse_starts) else 0
        if program is None or not at:
            continue
        entries, loop = program
        body = (list(entries) if loop is None
                else list(entries) + [(0xFF, at + loop)])
        if list(pulse_entries[at - 1:at - 1 + len(body)]) != body:
            continue
        for g in range(1, written + 1):
            if out[instr_at + 1 + (g - 1) * 25 + 3] == at:
                sweep_of[g] = rec
    if not sweep_of:
        return tracks, patterns, written, []
    _rows, _starts, lost = extra_programs(sid, det, plan, multiplier,
                                          len(pulse_entries))
    split = tri_clock_split_plan(
        tracks, patterns, plan, sweep_of, written + 1,
        min(TEMPO_DUTY_MAX_CLONE, clone_number_ceiling(patterns, written)),
        lost, log)
    if split is None:
        return tracks, patterns, written, []
    used = {(sweep_of[g], cls) for g, _n, cls in split.clones}
    rows, starts, lost = extra_programs(sid, det, plan, multiplier,
                                        len(pulse_entries), used)
    if lost:                         # cannot happen: `used` fitted above
        return tracks, patterns, written, []
    pulse_entries.extend(rows)
    for g, _number, cls in split.clones:
        rec = instr_at + 1 + (g - 1) * 25
        clone = bytearray(out[rec:rec + 25])
        clone[3] = starts[(sweep_of[g], cls)] & 0xFF
        out += clone
        written += 1
    out[instr_at] = written
    patterns = apply_tempo_duty_edits(split.patterns, split, log)
    return (split.tracks, patterns, written,
            [(g, number) for g, number, _cls in split.clones])
