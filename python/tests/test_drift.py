"""`drift`: accumulated phase error, which `pace` is structurally blind to.

`pace` compares one gap to one gap. That is exactly right for a row of the
wrong *length* -- such an error is in every gap and the median reports it --
and it cannot see a row that is a fraction of a frame wrong, because a
Goattracker row is a whole number of play calls: the error lands as zero on
most gaps and one whole frame on the occasional one, and the median of those
ratios is 1.000 exactly.

Integrating makes it visible. On this corpus the drift turns out to be the
outer gate's skipped call, and the relation is exact: `-1 / (skip + 1)`. See
H2G-CONVERSION-METHOD.md § 7.mmmmm.
"""
import pathlib
import sys

from corpus import CORPUS, needs_corpus  # noqa: E402

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[1]))

import fidelity as F  # noqa: E402
from h2g.convert import _detect_tables  # noqa: E402
from h2g.goatwriter import find_song_speeds  # noqa: E402
from h2g.sidfile import load_sid  # noqa: E402


def _voice(frames, names=None):
    v = F.Voice()
    v.attack_frames = list(frames)
    v.attacks = list(names) if names else [f"n{i}" for i in range(len(frames))]
    return v


def _trace(per_voice):
    return F.Trace([_voice(*a) if isinstance(a, tuple) else _voice(a)
                    for a in per_voice], F.FilterState())


def _pair(n=200, step=20, rate=0.0, lag=0):
    """Original every `step` frames; ours drifting by `rate` frames/frame."""
    o = [i * step for i in range(n)]
    u = [round(x + lag + rate * x) for x in o]
    names = [f"n{i}" for i in range(n)]
    return _trace([(o, names)] * 3), _trace([(u, names)] * 3)


def test_no_drift_reads_zero():
    got = F.drift(*_pair(rate=0.0))
    assert got["per_1000"] == 0.0
    assert got["mad"] == 0.0


def test_a_constant_lag_is_not_a_drift():
    """The slope is what is reported, so the startup lag falls out.

    Every per-frame column in the report has to estimate that lag and
    subtract it, and one of them was charged for it until v0.5.175. This
    measure never needs it.
    """
    for lag in (0, 5, 40, -12):
        got = F.drift(*_pair(rate=0.0, lag=lag))
        assert got["per_1000"] == 0.0, lag
        assert round(got["intercept"]) == lag, lag


def test_a_known_drift_is_recovered():
    for rate in (0.008, -0.008, 0.125, -0.25):
        got = F.drift(*_pair(rate=rate, n=300))
        assert abs(got["per_1000"] - rate * 1000) < 0.5, rate


def test_one_wild_voice_does_not_poison_the_others():
    """Powerplay's voice 1 matched a quarter of the original's notes at
    offsets of +845 and +1036 frames. Pooling all three voices put the
    intercept at +17.8 where the harness's own startup_lag says 5."""
    o, u = _pair(rate=-0.008, n=200)
    junk = [i * 20 for i in range(200)]
    wild = [x + (700 if i % 2 else -700) for i, x in enumerate(junk)]
    o[1].attack_frames, u[1].attack_frames = junk, wild
    got = F.drift(o, u)
    assert abs(got["per_1000"] + 8.0) < 0.6, got["per_1000"]


def test_a_voice_matched_too_thinly_is_dropped():
    o, u = _pair(rate=0.0, n=200)
    # Rename most of one voice's notes so difflib matches almost none.
    u[2].attacks = [f"x{i}" for i in range(len(u[2].attacks) - 4)] + \
        u[2].attacks[-4:]
    got = F.drift(o, u)
    assert got["voices"] == 2


def test_too_little_to_measure_says_so():
    got = F.drift(*_pair(n=5))
    assert got.get("per_1000") is None
    assert got["n"] < F.MIN_DRIFT_ONSETS * 3


@needs_corpus
def test_the_drift_is_the_outer_gates_skipped_call():
    """The finding, as a relation rather than as a table of numbers.

    `effective_frames` corrects a row for the skip when the corrected value
    can be packed (Delta 5/2 at -S2, Thrust 10/3 at -S3) and falls back to the
    raw gate when it cannot -- 3 x 113/112 wants 339 calls at -S112. What is
    pinned here is that dividing line, which is what the drift measures.
    """
    from fractions import Fraction
    corrected, declined = [], []
    for name in ("Delta.sid", "Tarzan.sid", "Thrust.sid", "IK_plus.sid",
                 "Ricochet.sid", "Sanxion.sid"):
        sid, det = _detect_tables(load_sid(str(CORPUS / name)),
                                  lambda *a, **k: None)
        sp = find_song_speeds(sid, det if det.can_convert else None)
        skip = sp.skip[0] if sp and sp.skip else None
        if not skip:
            continue
        true = sp.true_frames(0)
        eff = Fraction(sp.frames[0]) * (skip + 1) / skip
        (declined if abs(float(eff) - true) > 1e-9 or
         eff.denominator > 8 else corrected).append((name, skip))
    assert {n for n, _ in declined} == {"IK_plus.sid", "Ricochet.sid",
                                        "Sanxion.sid"}
    assert all(s > 100 for _, s in declined), declined
    assert all(s < 100 for _, s in corrected), corrected
