"""EXTRA_PAGES get their own fidelity rows: `<page>.sid`, traced at the page's
subtune pair, converted from the source with the source's presets."""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import extra_pages as E  # noqa: E402
import fidelity as F  # noqa: E402


def test_extra_jobs_name_only_pages_whose_source_is_in_the_sweep(monkeypatch):
    monkeypatch.setattr(F, "EXTRA_PAGES", {
        "Tune_2": {"source": "Tune.sid", "subtune": 1},
        "Gone_3": {"source": "Gone.sid", "subtune": 2}})
    sids = [Path("c/Other.sid"), Path("c/Tune.sid")]
    assert F._extra_jobs(sids) == [(Path("c/Tune.sid"), "Tune_2")]


def test_the_extra_row_is_named_by_page_and_traced_at_its_pair(monkeypatch):
    monkeypatch.setattr(F, "EXTRA_PAGES", {
        "Tune_2": {"source": "Tune.sid", "subtune": 1},
        "Tune_5": {"source": "Tune.sid", "subtune": 4, "ours": 3}})
    calls = []

    def fake(sid, workdir, opts, args, multiplier=1, pair=None):
        calls.append((sid.name, opts, multiplier, pair))
        return {"file": sid.name, "status": "measured"}

    monkeypatch.setattr(F, "measure", fake)
    row = F._timed_measure(Path("c/Tune.sid"), Path("w"), {"x": 1}, None, 2, "Tune_2")
    assert (row["file"], row["source"]) == ("Tune_2.sid", "Tune.sid")
    F._timed_measure(Path("c/Tune.sid"), Path("w"), {}, None, 1, "Tune_5")
    plain = F._timed_measure(Path("c/Tune.sid"), Path("w"), {}, None, 1)
    assert calls == [("Tune.sid", {"x": 1}, 2, (1, 1)),
                     ("Tune.sid", {}, 1, (4, 3)),
                     ("Tune.sid", {}, 1, None)]
    assert plain["file"] == "Tune.sid" and "source" not in plain


def test_every_registered_page_has_a_pair():
    for page in E.EXTRA_PAGES:
        a, b = F._extra_pair(page)
        assert isinstance(a, int) and isinstance(b, int)
