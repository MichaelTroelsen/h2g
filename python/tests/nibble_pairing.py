"""Time-aligned reading of a nibble record's runs, original against ours.

`test_arp_octave._nibble_runs` finds a note by the ADSR state it attacks
with, which is how the ORIGINAL writes it (every note's instrument start).
Our song writes ADSR only on an instrument CHANGE, so the same reader finds
a fraction of our notes (Kentilla's `$0F0D` record: 8 notes at -t 600, where
the original plays 26 qualifying ones by -t 1800). The two sides are
therefore paired by TIME: each original note whose ADSR matches is paired
with the first attack our voice makes within `window` frames of it
(Kentilla: all 514 attacks lag by exactly 3), and the runs of one sounding
frequency are read inside each side's own note.

Importing this module imports `test_arp_octave` for `_timeline` and `_runs`.
"""
from collections import Counter

from test_arp_octave import _runs, _timeline

WINDOW = 8
MIN_FRAMES = 8


def two_valued(seg, min_frames=MIN_FRAMES):
    """`seg` from the first frame it shows only its two values, or None when
    it never settles to exactly two, or is shorter than `min_frames`."""
    while len(set(seg)) > 2:
        seg = seg[1:]
    return seg if len(set(seg)) == 2 and len(seg) >= min_frames else None


def interior_runs(seg):
    """Run lengths of `seg`, the first and last (cut by the attack and the
    next note) dropped."""
    return [r[1] for r in _runs(seg)][1:-1]


def adsr_attacks(voice, n, adsr):
    """(attack frame, end frame) of every note of `voice` attacking with
    ADSR state `adsr`; a note ends at the next attack, or at `n`."""
    ad = dict(voice.adsr_events)
    cur, state = None, []
    for f in range(n):
        if f in ad:
            cur = ad[f]
        state.append(cur)
    at = list(voice.attack_frames)
    return [(f, at[i + 1] if i + 1 < len(at) else n)
            for i, f in enumerate(at) if f < n and state[f] == adsr]


def pair_notes(orig, ours, n, adsr, window=WINDOW):
    """([(f, f_end, g, g_end)], lags, unpaired): each original note attacking
    with `adsr`, paired with the first attack of `ours` in [f, f + window]
    that is also before the original's next attack (so one attack never
    serves two notes). `lags` counts g - f; `unpaired` counts the original
    notes that found no attack."""
    theirs = [g for g in ours.attack_frames if g < n]
    pairs, lags, unpaired = [], Counter(), 0
    for f, f_end in adsr_attacks(orig, n, adsr):
        g = next((x for x in theirs
                  if f <= x <= min(f + window, f_end - 1)), None)
        if g is None:
            unpaired += 1
            continue
        nxt = next((x for x in theirs if x > g), n)
        pairs.append((f, f_end, g, nxt))
        lags[g - f] += 1
    return pairs, lags, unpaired


def paired_nibble_runs(orig_trace, ours_trace, n, adsr, window=WINDOW):
    """(orig runs, our runs, stats): Counters of interior run lengths in
    frames, over the notes where BOTH sides settle to a two-valued segment of
    8+ frames. `stats` counts 'orig notes' (original notes attacking with
    `adsr`), 'paired', 'unpaired', 'orig qualifying' (two-valued, 8+
    frames) and 'both qualifying' -- the found count -- plus 'lags'."""
    orig_out, ours_out = Counter(), Counter()
    stats, lags = Counter(), Counter()
    for vo, vn in zip(orig_trace, ours_trace):
        to, tn = _timeline(vo, n), _timeline(vn, n)
        stats['orig notes'] += len(adsr_attacks(vo, n, adsr))
        pairs, lag, unpaired = pair_notes(vo, vn, n, adsr, window)
        lags.update(lag)
        stats['unpaired'] += unpaired
        for f, f_end, g, g_end in pairs:
            stats['paired'] += 1
            so = two_valued(to[f:f_end])
            if so is None:
                continue
            stats['orig qualifying'] += 1
            sn = two_valued(tn[g:g_end])
            if sn is None:
                continue
            stats['both qualifying'] += 1
            orig_out.update(interior_runs(so))
            ours_out.update(interior_runs(sn))
    stats['lags'] = dict(lags)
    return orig_out, ours_out, stats
