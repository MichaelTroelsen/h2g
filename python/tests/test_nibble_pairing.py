"""`nibble_pairing`: runs inside a nibble note, original paired with ours by TIME.

`test_arp_octave._nibble_runs` identifies a note by the ADSR state at its
attack frame. That holds for the original, which writes ADSR on every note,
and fails for ours wherever the ADSR write does not sit on the attack frame
(our song writes it on an instrument change, not a note). The pairing here
takes the original's note as the anchor and ours as the first attack within a
few frames after it. Kentilla's `$0F0D` record (fef37ef, presets, -S10):

                      original notes   paired   both two-valued   lag
    -t  600                      145      145                41   {3: 145}
    -t 1800                      648      648               160   {3: 648}

both sides read {2: 3272, 3: 824} frames at -t 1800: 22.01 calls a half.
Thrust's `$0A0A` (-S3, -t 240) is the case that pairing cannot hide: 45
original notes, 15 paired, 30 reported UNPAIRED -- our voice 2 has 529
attacks to the original's 559, so the notes it never attacked are not read.
"""
import json
import pathlib
import sys
from types import SimpleNamespace

import pytest

from corpus import CORPUS, needs_corpus

PYTHON_ROOT = pathlib.Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PYTHON_ROOT))
import fidelity                                              # noqa: E402
from nibble_pairing import (adsr_attacks, interior_runs,    # noqa: E402
                            pair_notes, paired_nibble_runs, two_valued)
from test_arp_octave import (_nibble_runs, _converted,      # noqa: E402
                             needs_gt2reloc, needs_siddump)

ADSR = 0x0F0D
OTHER = 0x0A08


def _voice(notes, adsr_at, halves=(2, 3), a=0x1000, b=0x2000):
    """A voice playing `notes` = [(attack frame, length)], each alternating
    `a` and `b` in runs cycling through `halves`. `adsr_at` maps frame ->
    ADSR register."""
    freq, attacks = [], []
    for start, length in notes:
        attacks.append(start)
        f, i, cur = start, 0, a
        while f < start + length:
            freq.append((f, cur))
            f += halves[i % len(halves)]
            i += 1
            cur = b if cur == a else a
    return SimpleNamespace(freq_events=freq, attack_frames=attacks,
                           adsr_events=sorted(adsr_at.items()))


def _pair(lag=3, adsr_lag=1, notes=((100, 60), (300, 60), (500, 60)),
          ours_adsr=True, ours_halves=(2, 3)):
    orig = _voice(list(notes), {s: ADSR for s, _ in notes})
    ours_notes = [(s + lag, l) for s, l in notes]
    ours_ad = {s + lag + adsr_lag: ADSR for s, _ in notes} if ours_adsr else {}
    ours = _voice(ours_notes, ours_ad, halves=ours_halves)
    return orig, ours


def test_the_adsr_keyed_reader_misses_notes_whose_adsr_trails_the_attack():
    """Ours writes ADSR one frame after the attack: the ADSR-keyed reader
    loses the first note (its state is still unset at the attack), then
    finds the rest only through the state it carries forward; the paired
    reader reads all three by their time."""
    orig, ours = _pair(adsr_lag=1)
    n = 700
    assert len(adsr_attacks(orig, n, ADSR)) == 3
    assert len(adsr_attacks(ours, n, ADSR)) == 2
    assert sum(_nibble_runs([ours], n, ADSR).values()) < sum(
        _nibble_runs([orig], n, ADSR).values())
    o, w, st = paired_nibble_runs([orig], [ours], n, ADSR)
    assert st['orig notes'] == st['paired'] == st['both qualifying'] == 3
    assert st['unpaired'] == 0 and st['lags'] == {3: 3}
    assert o == w and sum(w.values()) > 0


def test_ours_is_read_whatever_its_adsr_state_is():
    orig, ours = _pair(ours_adsr=False)
    o, w, st = paired_nibble_runs([orig], [ours], 700, ADSR)
    assert st['both qualifying'] == 3 and o == w


def test_a_different_run_pattern_in_ours_shows_in_ours_only():
    orig, ours = _pair(ours_halves=(1, 2))
    o, w, st = paired_nibble_runs([orig], [ours], 700, ADSR)
    assert set(o) == {2, 3} and set(w) == {1, 2}
    assert st['both qualifying'] == 3


def test_a_note_ours_never_attacked_is_unpaired_not_borrowed():
    """The middle note has no attack in ours: the pairing may not take the
    NEXT note's attack (inside the window of nothing, past the original's
    next attack) for it."""
    orig, ours = _pair()
    ours.attack_frames.remove(303)
    pairs, lags, unpaired = pair_notes(orig, ours, 700, ADSR)
    assert unpaired == 1 and len(pairs) == 2
    assert [p[0] for p in pairs] == [100, 500]
    assert lags == {3: 2}


def test_an_attack_is_paired_once_and_only_inside_the_window():
    orig, ours = _pair(lag=3)
    pairs, lags, unpaired = pair_notes(orig, ours, 700, ADSR, window=2)
    assert pairs == [] and unpaired == 3        # lag 3 is outside window 2
    pairs, lags, unpaired = pair_notes(orig, ours, 700, ADSR, window=3)
    assert len(pairs) == 3 and unpaired == 0
    # two original notes cannot share one attack of ours
    orig = _voice([(100, 4), (104, 60)], {100: ADSR, 104: ADSR})
    ours = _voice([(105, 60)], {})
    pairs, _, unpaired = pair_notes(orig, ours, 300, ADSR)
    assert [(p[0], p[2]) for p in pairs] == [(104, 105)] and unpaired == 1


def test_the_note_ends_at_the_next_attack_of_its_own_side():
    orig, ours = _pair()
    pairs, _, _ = pair_notes(orig, ours, 700, ADSR)
    assert pairs == [(100, 300, 103, 303), (300, 500, 303, 503),
                     (500, 700, 503, 700)]


def test_only_the_asked_adsr_is_paired():
    orig = _voice([(100, 60), (300, 60)], {100: ADSR, 300: OTHER})
    assert adsr_attacks(orig, 500, ADSR) == [(100, 300)]
    assert adsr_attacks(orig, 500, OTHER) == [(300, 500)]
    assert adsr_attacks(orig, 250, OTHER) == []


def test_two_valued_settles_then_demands_eight_frames():
    assert two_valued([1, 2, 3, 1, 2, 1, 2, 1, 2, 1, 2]) == [1, 2] * 4
    assert two_valued([1, 2, 3] + [4, 5] * 4) == [4, 5] * 4
    assert two_valued([4, 5] * 3) is None        # short
    assert two_valued([1] * 12) is None          # one value
    assert interior_runs([1, 1, 2, 2, 2, 1, 1, 2]) == [3, 2]


@needs_corpus
@needs_siddump
@needs_gt2reloc
def test_kentilla_record_20_is_read_in_ours_by_time(tmp_path):
    """Kentilla at its preset -S10, 600 s (the first `$0F0D` attack is at
    447 s): every one of the original's 145 `$0F0D` notes has an attack of
    ours exactly 3 frames later, 41 settle to two values on both sides, and
    the record's half is the player's 22 calls on both. Floors are the
    counts at fef37ef."""
    if not (PYTHON_ROOT.parent / "presets.json").exists():
        pytest.skip("presets.json not present")
    seconds, n = 600, 600 * 50
    doc = json.loads((PYTHON_ROOT.parent / "presets.json").read_text())
    m = fidelity._preset_multiplier(doc, "Kentilla.sid")
    sng, _t, _p = _converted("Kentilla")
    packed = fidelity.pack_sid(sng, tmp_path, multiplier=m)
    assert packed is not None and packed.exists()
    orig = fidelity.run_siddump(CORPUS / "Kentilla.sid", seconds, 0, calls=1)
    ours = fidelity.run_siddump(packed, seconds, 0, calls=m)
    o, w, st = paired_nibble_runs(orig, ours, n, ADSR)
    assert st['orig notes'] >= 145 and st['unpaired'] == 0, st
    assert st['both qualifying'] >= 41, st
    assert st['lags'] == {3: st['paired']}, st
    for runs in (o, w):
        mean = sum(k * v for k, v in runs.items()) / sum(runs.values())
        assert mean * m == pytest.approx(22.0, abs=0.5), runs
