"""`--gate-census`: what the 39% mean gate overlap is made of.

The column says the overlap; this says the shape of the disagreement, which
is the difference between a number and a queue -- the same relation
`--census` has to `onset` and `--hold-census` to `hold`.

Corpus at v0.5.272, 46996 releases the originals make across 83 files:
`matched` 50.2%, `held` 24.2%, `short` 23.5%, `retrigger` 2.0%. So half of
every release is already right, and the work is in the 11385 the conversion
sustains straight through.
"""
import pathlib
import sys

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[1]))

import fidelity  # noqa: E402
from fidelity import Voice, gate_census, gate_runs  # noqa: E402


def _v(pairs):
    return Voice(wf_events=list(pairs))


def _census(orig, ours, nframes=16, lag=0):
    return gate_census([_v(orig), _v([]), _v([])],
                       [_v(ours), _v([]), _v([])], nframes, lag=lag)


# --- the run finder --------------------------------------------------------

def test_a_release_is_a_nonzero_byte_with_the_gate_clear():
    tl = [0x41, 0x41, 0x40, 0x41, 0x40, 0x40, 0x40, 0x41]
    assert gate_runs(tl) == [(2, 1), (4, 3)]


def test_a_voice_never_written_is_not_a_release():
    """It reads $00 for the whole trace, which is not a note being let go."""
    assert gate_runs([0, 0, 0, 0]) == []


def test_a_release_running_to_the_end_is_still_a_release():
    assert gate_runs([0x41, 0x40, 0x40]) == [(1, 2)]


# --- the classification ----------------------------------------------------

def test_a_one_frame_release_is_a_retrigger_edge():
    recs = _census([(0, 0x41), (4, 0x40), (5, 0x41)], [(0, 0x41)])
    assert [r["kind"] for r in recs] == ["retrigger"]


def test_a_release_we_never_make_is_held():
    recs = _census([(0, 0x41), (4, 0x40), (10, 0x41)], [(0, 0x41)])
    assert recs[0]["kind"] == "held"
    assert recs[0]["frames"] == 6 and recs[0]["ours_off"] == 0


def test_a_release_we_mostly_make_is_matched():
    recs = _census([(0, 0x41), (4, 0x40), (10, 0x41)],
                   [(0, 0x41), (4, 0x40), (9, 0x41)])
    assert recs[0]["kind"] == "matched"
    assert recs[0]["ours_off"] == 5


def test_a_release_we_cut_short_is_short():
    recs = _census([(0, 0x41), (4, 0x40), (10, 0x41)],
                   [(0, 0x41), (4, 0x40), (5, 0x41)])
    assert recs[0]["kind"] == "short"
    assert recs[0]["ours_off"] == 1


def test_half_counts_as_matched_and_a_hair_under_does_not():
    """The boundary is stated so it cannot drift silently."""
    long = [(0, 0x41), (4, 0x40), (10, 0x41)]        # six frames released
    assert _census(long, [(0, 0x41), (4, 0x40), (7, 0x41)])[0]["kind"] \
        == "matched"                                  # three of six
    assert _census(long, [(0, 0x41), (4, 0x40), (6, 0x41)])[0]["kind"] \
        == "short"                                    # two of six


def test_it_is_aligned_like_the_column():
    # Six frames released at 4..9; ours the same shape four frames later, so
    # unaligned they overlap on two of six and aligned on all six.
    orig = [(0, 0x41), (4, 0x40), (10, 0x41)]
    ours = [(4, 0x41), (8, 0x40), (14, 0x41)]
    assert _census(orig, ours, nframes=20)[0]["kind"] == "short"
    assert _census(orig, ours, nframes=20, lag=4)[0]["kind"] == "matched"


def test_every_kind_is_declared():
    kinds = {r["kind"] for r in _census([(0, 0x41), (4, 0x40), (10, 0x41)],
                                        [(0, 0x41)])}
    assert kinds <= set(fidelity.GATE_KINDS)


def test_the_report_survives_a_run_that_measured_nothing():
    assert "Gate census" in fidelity.gate_census_report([])
    assert "Gate census" in fidelity.gate_census_report([{"file": "a.sid"}])
