"""residual.py: rank songs by the sound deficit the register columns do not explain."""
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import residual as R  # noqa: E402


def _row(file, aud, wave=1.0, adsr=1.0, gate=1.0, **kw):
    row = {"file": file, "aud": aud, "loud": aud, "loud_ratio": 1.0,
           "wave": wave, "adsr": adsr, "gate": gate, "melody": 1.0,
           "multiplier": 1, "window_seconds": 180, "window_coverage": 1.0}
    row.update(kw)
    return row


def test_ranks_by_residual():
    rows = [_row("Small.sid", 0.90, wave=0.91, adsr=0.91, gate=0.91),
            _row("Big.sid", 0.66, wave=0.94, adsr=0.94, gate=0.94)]
    ranked = R.residuals(rows)["ranked"]
    assert [r["file"] for r in ranked] == ["Big.sid", "Small.sid"]
    assert ranked[0]["residual"] == pytest.approx(0.28)
    assert ranked[1]["residual"] == pytest.approx(0.01)


def test_held_rows_are_separated():
    out = R.residuals([_row("Mr_Meaner.sid", 0.5), _row("Confuzion.sid", 0.8)])
    assert [r["file"] for r in out["ranked"]] == ["Confuzion.sid"]
    [h] = out["held"]
    assert h["file"] == "Mr_Meaner.sid"
    assert h["held"] is True
    assert h["hold_reason"].startswith("DIGI")


def test_refuses_rows_without_aud():
    with pytest.raises(ValueError):
        R.residuals([_row("A.sid", None), {"file": "B.sid", "status": "not converted"}])


def test_short_window_is_flagged():
    [r] = R.residuals([_row("Kings_of_the_Beach_ingame.sid", 0.66, window_seconds=8)])["ranked"]
    assert "short-window" in r["explained_by"]


def test_low_coverage_is_flagged():
    [r] = R.residuals([_row("A.sid", 0.9, window_coverage=0.1)])["ranked"]
    assert "coverage" in r["explained_by"]
    [r] = R.residuals([_row("A.sid", 0.9)])["ranked"]
    assert r["explained_by"] == []


def test_bounded_coverage_is_not_flagged():
    # `window_coverage_bounded` marks an original that never ends: its 0.1 is
    # fidelity.py's "<10%" ceiling, not a window that missed most of the tune.
    [r] = R.residuals([_row("A.sid", 0.9, window_coverage=0.1,
                            window_coverage_bounded=True)])["ranked"]
    assert "coverage" not in r["explained_by"]


def test_melody_is_not_in_reg_mean():
    [r] = R.residuals([_row("A.sid", 0.9, wave=0.8, adsr=0.8, gate=0.8, melody=0.2)])["ranked"]
    assert r["reg_mean"] == pytest.approx(0.8)


def test_reg_mean_skips_absent_columns():
    [r] = R.residuals([_row("A.sid", 0.9, wave=0.8, adsr=None, gate=0.6)])["ranked"]
    assert r["reg_mean"] == pytest.approx(0.7)


def test_unmeasured_rows_are_counted_not_ranked():
    out = R.residuals([_row("A.sid", 0.9), {"file": "B.sid", "status": "not converted"}])
    assert [r["file"] for r in out["ranked"]] == ["A.sid"]
    assert out["unmeasured"] == ["B.sid"]


def test_report_prints_the_median_residual():
    out = R.residuals([_row("A.sid", 0.9, wave=0.95, adsr=0.95, gate=0.95),
                       _row("B.sid", 0.95, wave=0.9, adsr=0.9, gate=0.9)])
    md = R.report(out, source="x.json")
    assert "median residual" in md
    assert "+0.000" in md
