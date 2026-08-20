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
from test_fidelity import _Args, _row  # noqa: E402


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


# --- the report column -----------------------------------------------------

def test_drift_is_a_declared_dimension():
    """`fidelity.py`'s rule: a printed column has a Dimension declaring the
    registers it is derived from, and `test_fidelity` fails if the registry
    and the header disagree. Pinned here too, because the interesting claim
    is *which* registers -- drift is computed from note onsets, so it reads
    the pitch pair and $D404 like `melody`, and differs from it only in using
    the frame positions `melody` throws away."""
    d = next(x for x in F.DIMENSIONS if x.key == "drift_per_1000")
    assert d.column == "drift"
    assert d.kind == "ratio"
    assert set(d.reads) == {"$D400/$D401", "$D404"}


def test_a_file_can_score_perfect_melody_and_still_drift():
    """Why the column had to exist. `melody` is a difflib ratio over a note
    sequence and discards when the notes arrive; a conversion can reproduce
    every note in order and still walk away from the original."""
    o, u = _pair(rate=-0.008, n=200)
    got = F.drift(o, u)
    assert got["per_1000"] < -7
    assert F.compare(o, u)["melody"] == 1.0


def test_zero_and_missing_print_differently():
    """`0.0` is a measurement -- 37 corpus files hold the original's timing
    exactly -- and `-` is the absence of one. A formatter that collapsed them
    would report the corpus as untimed."""
    assert F._fmt_drift({"drift_per_1000": 0.0}) == "+0.0"
    assert F._fmt_drift({"drift_per_1000": -12.34}) == "-12.3"
    assert F._fmt_drift({"drift_per_1000": 7.81}) == "+7.8"
    assert F._fmt_drift({}) == "-"


def test_a_wandering_offset_is_not_reported_as_a_rate():
    """The gate that keeps a fit out of the table when it explains nothing.

    Knucklebusters printed the corpus-worst `+1151` from one voice whose
    offsets scattered 82 frames about the line, and Rock Tells the Tale
    printed `0.0` at MAD 93. `mad` had been computed since the first version
    and simply not consulted.
    """
    o, u = _pair(rate=0.0, n=200)
    # Offsets alternating +-400 frames: no line describes them.
    u[0].attack_frames = [x + (400 if i % 2 else -400)
                          for i, x in enumerate(o[0].attack_frames)]
    u[1].attack_frames = list(u[0].attack_frames)
    u[2].attack_frames = list(u[0].attack_frames)
    got = F.drift(o, u)
    assert got["per_1000"] is None
    assert "wander" in got["unfitted"]
    # The diagnostics survive, so --pace can still say what it saw.
    assert got["mad"] > 100 and got["span"] > 0


def test_a_real_drift_survives_the_gate():
    """The other half: a bound that rejected the true positives would be
    worse than none. Spellbound's -298 sits at 0.67% scatter and must pass."""
    o, u = _pair(rate=-0.29, n=300)
    got = F.drift(o, u)
    assert got["per_1000"] is not None
    assert abs(got["per_1000"] + 290) < 10


# --- the "On N files this is exactly -1/(skip+1)" sentence -----------------
#
# v0.5.288 shipped that count as a literal 17, measured once by hand and
# never revisited. v0.5.330's tempo fix took Human_Race's drift to 0.00 --
# one file fewer in `moving` -- and nothing recomputed the sentence next to
# it. `_drift_gate_skip_declined` and the summary in `report()` replace the
# literal with a count taken from the rows themselves.


@needs_corpus
def test_gate_skip_declined_matches_the_pinned_relation():
    """`_drift_gate_skip_declined` reproduces the relation
    `test_the_drift_is_the_outer_gates_skipped_call` pins directly: it must
    read False for the three corrected files and True for the three whose
    correction `effective_frames` declines (skip > 100 in each case)."""
    corrected = ("Delta.sid", "Tarzan.sid", "Thrust.sid")
    declined = ("IK_plus.sid", "Ricochet.sid", "Sanxion.sid")
    for name in corrected:
        assert F._drift_gate_skip_declined(CORPUS / name, 0) is False, name
    for name in declined:
        assert F._drift_gate_skip_declined(CORPUS / name, 0) is True, name


def test_gate_skip_declined_is_false_with_no_gate_or_bad_file():
    # Commando has no outer-gate skip counter at all.
    assert F._drift_gate_skip_declined(
        pathlib.Path(__file__).resolve().parents[2] / "Commando.sid", 0
    ) is False
    assert F._drift_gate_skip_declined(pathlib.Path("no-such-file.sid"), 0) is False


def _moving_row(name, drift_per_1000, gate_skip):
    r = _row(name, "measured", melody=1.0, orig=10, ours=10)
    r["drift_per_1000"] = drift_per_1000
    r["drift_total"] = drift_per_1000 * 3
    r["drift_gate_skip"] = gate_skip
    return r


def test_the_report_counts_gate_skip_declines_from_the_rows():
    """The count in the sentence must track how many rows carry
    `drift_gate_skip = True`, not a number written into the format string.

    Three declining and two moving-for-another-reason: a reversion to the
    old literal `17` would fail this (and every other count chosen here that
    is not coincidentally 17)."""
    rows = [
        _moving_row("Sanxion.sid", -9.2, True),
        _moving_row("IK_plus.sid", -8.8, True),
        _moving_row("Ricochet.sid", -7.8, True),
        _moving_row("Knucklebusters.sid", 285.7, False),
        _moving_row("Rasputin.sid", -4.3, False),
        _row("Exact.sid", "measured", melody=1.0, orig=10, ours=10),  # 0.0
    ]
    text = F.report(rows, _Args())
    assert "On **3** file(s) this is exactly `-1/(skip+1)`" in text
    assert "On 17 files" not in text
    assert "On **17**" not in text


def test_the_report_omits_the_sentence_when_no_row_declines():
    rows = [_moving_row("Rasputin.sid", -4.3, False),
            _row("Exact.sid", "measured", melody=1.0, orig=10, ours=10)]
    text = F.report(rows, _Args())
    assert "part company" in text
    assert "-1/(skip+1)" not in text


def test_the_report_count_changes_when_the_rows_do():
    """A second, differently-sized population must print a different count
    -- pinning that the sentence is derived, not memoised or hardcoded."""
    few = [_moving_row("Sanxion.sid", -9.2, True),
           _row("Exact.sid", "measured", melody=1.0, orig=10, ours=10)]
    many = few + [_moving_row(f"Extra{i}.sid", -9.2, True) for i in range(5)]
    text_few = F.report(few, _Args())
    text_many = F.report(many, _Args())
    assert "On **1** file(s) this is exactly `-1/(skip+1)`" in text_few
    assert "On **6** file(s) this is exactly `-1/(skip+1)`" in text_many
