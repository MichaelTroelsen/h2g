"""Pins check_column's two vacuous-input refusals and its two distinct PASS
verdicts, on synthetic approvals.json/index.html data -- never the live
corpus, so the suite does not depend on build/ existing.

The state this module exists to catch (4 spans render, 0 of them
`inherited`, and the checker printed a plain PASS anyway) is
`test_zero_inherited_is_flagged_not_plain_pass` below.
"""
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import check_column as CC  # noqa: E402


def _index(rows):
    """rows: list of (stem, class_letter) -> minimal index.html body."""
    spans = "".join(
        '<a href="%s.html">%s</a> <span class="%s">%s</span>\n'
        % (stem, stem, cls, CC.CLASS[cls])
        for stem, cls in rows
    )
    return "<html><body>%s</body></html>" % spans


def _approvals(tunes):
    return {"tunes": tunes}


def _rec(status):
    return {"status": status}


# ---- vacuous-input refusal (the ORIGINAL checker's own guard) ------------
def test_empty_index_refuses():
    doc = _approvals({"Foo": _rec("exact")})
    with pytest.raises(AssertionError, match="REFUSING"):
        CC.check("<html><body>no spans here</body></html>", doc)


# ---- the premise this task measured: 4 spans, 0 inherited, plain PASS ----
def test_zero_inherited_is_flagged_not_plain_pass():
    """Reproduces the reported shape: every rendered span agrees with its
    tune's status, and NONE of the tunes is `inherited` -- the exact
    corpus state measured live (2 exact + 2 uncalibrated, 0 inherited) at
    build/approvals.json as of this task."""
    tunes = {
        "A": _rec("exact"),
        "B": _rec("exact"),
        "C": _rec("uncalibrated"),
        "D": _rec("uncalibrated"),
    }
    rows = [("A", "y"), ("B", "y"), ("C", "s"), ("D", "s")]
    result = CC.check(_index(rows), _approvals(tunes))

    assert result["bad"] == []
    assert result["missing"] == set()
    assert result["inherited_statuses"] == 0
    assert result["inherited_spans"] == 0

    msg = CC.verdict(result)
    assert msg.startswith("PASS")
    assert "NEVER OBSERVED" in msg
    assert "0/4 tunes have status=inherited" in msg


def test_inherited_observed_is_a_plain_pass():
    tunes = {
        "A": _rec("exact"),
        "B": _rec("inherited"),
    }
    rows = [("A", "y"), ("B", "i")]
    result = CC.check(_index(rows), _approvals(tunes))

    assert result["bad"] == []
    assert result["inherited_statuses"] == 1
    assert result["inherited_spans"] == 1

    msg = CC.verdict(result)
    assert msg.startswith("PASS")
    assert "NEVER OBSERVED" not in msg
    assert "1 tunes with status=inherited observed" in msg


def test_disagreement_is_detected_and_raises():
    tunes = {"A": _rec("inherited")}
    rows = [("A", "y")]  # rendered "approved", but status says inherited
    result = CC.check(_index(rows), _approvals(tunes))

    assert result["bad"] == [("A", "inherited", "inherited", "approved")]
    with pytest.raises(AssertionError):
        CC.verdict(result)


def test_missing_tune_is_detected_and_raises():
    tunes = {"A": _rec("exact"), "B": _rec("exact")}
    rows = [("A", "y")]  # B never rendered
    result = CC.check(_index(rows), _approvals(tunes))

    assert result["missing"] == {"B"}
    with pytest.raises(AssertionError):
        CC.verdict(result)


def test_main_reads_files_and_prints_never_observed(tmp_path, capsys):
    tunes = {"A": _rec("exact"), "B": _rec("uncalibrated")}
    rows = [("A", "y"), ("B", "s")]
    idx = tmp_path / "index.html"
    idx.write_text(_index(rows), encoding="utf-8")
    appr = tmp_path / "approvals.json"
    import json
    appr.write_text(json.dumps(_approvals(tunes)), encoding="utf-8")

    rc = CC.main(["--index", str(idx), "--approvals", str(appr)])
    assert rc == 0
    out = capsys.readouterr().out
    assert "NEVER OBSERVED" in out
    assert "DISAGREEMENTS: 0" in out
