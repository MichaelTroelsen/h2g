"""The unticked nibble arpeggio starts its alternation from the walked
counter residue (`nibble_arp_entries(phase=...)`), as the ticked shape does.

Ported from the runqueue task nibble-unticked-counter-phase (v0.5.496), where
each of seven mutations of the shape or its caller failed a test here."""
import pytest
from test_call_rate import wave_timeline
from corpus import CORPUS
from h2g.sidfile import load_sid
from h2g.detect import detect
from h2g.goatwriter import (_first_frame_lead, _wavetable_entries,
                            nibble_arp_entries)


def _runs(notes):
    out = []
    for n in notes:
        if out and out[-1][0] == n:
            out[-1][1] += 1
        else:
            out.append([n, 1])
    return out


def _det(name):
    sid = load_sid(str(CORPUS / f"{name}.sid"))
    return sid, detect(sid, lambda *a: None)


@pytest.mark.parametrize("m, half, up, first_calls, written", [
    (10, 11, False, 11, False), (10, 22, True, 22, False),
    (4, 5, True, 5, False), (3, (3, 3, 4, 3, 3, 4), False, 3, False),
    (2, (2, 3), True, 2, False), (10, 11, False, 11, True),
    (5, 40, False, 20, False),
])
def test_phased_unticked_shape_per_call(m, half, up, first_calls, written):
    """Lead = frame 0 on the base note; first run on `up`'s note for
    `first_calls`; then the halves alternate; the loop target is after the
    first run, so the lead and the run play once."""
    wave, alt = 0x41, 0x7B
    frame0, frame0_r = _first_frame_lead(wave, m, force=True, written=written)
    lead = 0 if written else m
    assert sum(1 if b > 0x0F else b + 1 for b in frame0) == lead
    left, right = nibble_arp_entries(wave, alt, half, 6, 255,
                                     phase=(frame0, frame0_r, up, first_calls))
    cyc = (half, half) if isinstance(half, int) else half
    want = [cyc[k % len(cyc)] for k in range(4 * len(cyc))]
    calls = wave_timeline(left, right, first=6,
                          calls=lead + first_calls + sum(want) + 1)
    assert set(w for _, w, _ in calls) == {wave}
    notes = [x for _, _, x in calls]
    assert notes[:lead] == [0x00] * lead
    runs = _runs(notes[lead:])
    assert runs[0] == [alt if up else 0x00, first_calls], runs
    assert len(runs) == len(want) + 2, runs     # first run, halves, 1 call
    assert [r[1] for r in runs[1:-1]] == want, runs
    assert all(a[0] != b[0] for a, b in zip(runs, runs[1:])), runs
    target = right[-1] - 6
    assert left[-1] == 0xFF
    assert target == len(frame0) + 1 + len(_h(first_calls)), (target, left)
    assert nibble_arp_entries(wave, alt, half, 6, len(left) - 1,
                              phase=(frame0, frame0_r, up, first_calls)) is None


def _h(c):
    from h2g.goatwriter import _hold_run
    return _hold_run(c - 1, 0x41)


def _frame_notes(left, right, m, frames):
    calls = wave_timeline(left, right, first=6, calls=m * frames)
    return [calls[k * m + m - 1][2] for k in range(frames)]


@pytest.mark.parametrize("name, rec, m, skip, phase, want", [
    # IK `$0908` (record 7, nibble 5): residue 2 -> frames 0-1 note, 2 interval
    ("International_Karate", 7, 10, 10, 2, [0, 0, 1, 0, 1, 0]),
    ("International_Karate", 7, 10, 10, 1, [0, 1, 0, 1, 0, 1]),
    # Kentilla record 0 (octave, two steps a half): residue 2, then 3
    ("Kentilla", 0, 10, 10, 2, [0, 0, 1, 1, 0, 0]),
    ("Kentilla", 0, 10, 10, 3, [0, 1, 1, 0, 0, 1]),
    ("Kentilla", 0, 10, 10, 1, [0, 0, 0, 1, 1, 0]),
])
def test_unticked_records_toggle_on_the_residues_frame(name, rec, m, skip,
                                                       phase, want):
    sid, det = _det(name)
    left, right = _wavetable_entries(sid, det, rec, True, "gts5", [], m,
                                     budget=255, start=6, gate_skip=skip,
                                     arp_phase=phase)
    nib = sid.data[det.instr_start + rec * det.instr_stride + 7] >> 4
    alt = (0x80 - nib) & 0xFF
    notes = _frame_notes(left, right, m, len(want))
    assert [int(x == alt) for x in notes] == want, (notes, left, right)


def test_unphased_where_the_phase_already_matches():
    """Kentilla record 0 at -S10 ungated: half 20 calls, residue 2 puts frame
    1 on the note with one step left -- exactly the unphased shape's first
    half -- so its bytes are kept; residue 0 is not, and moves them."""
    sid, det = _det("Kentilla")
    kw = dict(budget=255, start=6)
    none = _wavetable_entries(sid, det, 0, True, "gts5", [], 10, **kw)
    assert _wavetable_entries(sid, det, 0, True, "gts5", [], 10,
                              arp_phase=2, **kw) == none
    assert _wavetable_entries(sid, det, 0, True, "gts5", [], 10,
                              arp_phase=0, **kw) != none


def test_written_record_has_no_lead():
    """`no_test_restart`: firstwave owns frame 0, so no lead entries; the
    first run (residue 1: the interval) is entry 0."""
    sid, det = _det("International_Karate")
    left, right = _wavetable_entries(sid, det, 7, True, "gts5", [], 10,
                                     budget=255, start=6, gate_skip=10,
                                     arp_phase=1, no_test_restart=True)
    notes = [x for _, _, x in wave_timeline(left, right, first=6, calls=40)]
    nib = sid.data[det.instr_start + 7 * det.instr_stride + 7] >> 4
    alt = (0x80 - nib) & 0xFF
    assert _runs(notes)[0] == [alt, 11], _runs(notes)
    assert _runs(notes)[1] == [0x00, 11]
