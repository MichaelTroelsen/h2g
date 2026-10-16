"""presets.best_options keeps the shipped shape unless another plays more.

A regeneration at v0.5.563 moved Human_Race's max_rows 128 -> 94 and
Game_Killer's dedup true -> false on size alone, and the smaller Human_Race
was smaller because the slicing left no room for its rest-row copies.
"""
import pathlib
import sys

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[1]))
import presets as P  # noqa: E402


def _search(monkeypatch, scores, keep):
    """`scores` maps (max_rows, dedup) to (subtunes, rows, size)."""
    def fake_convert(path, log=None, **opts):
        key = (opts["max_rows"], opts["dedup"])
        if key not in scores or not (opts["pack"] and opts["prune"]):
            raise ValueError("miss")
        return bytes(scores[key][2])

    by_size = {v[2]: v for v in scores.values()}
    assert len(by_size) == len(scores), "sizes must tell the shapes apart"
    monkeypatch.setattr(P, "convert", fake_convert)
    monkeypatch.setattr(P, "_score",
                        lambda blob: (by_size[len(blob)][0],
                                      by_size[len(blob)][1], -len(blob)))
    monkeypatch.setattr(P, "MAX_ROWS", (94, 128))
    return P.best_options(pathlib.Path("x.sid"), keep)


def _shape(rows, dedup):
    return {"max_rows": rows, "pack": True, "prune": True, "dedup": dedup}


def test_the_shipped_shape_stays_when_another_is_only_smaller(monkeypatch):
    scores = {(94, True): (5, 21036, 25292), (128, True): (5, 21036, 25405)}
    got = _search(monkeypatch, scores, _shape(128, True))
    assert got["max_rows"] == 128 and got["bytes"] == 25405


def test_without_a_shipped_shape_the_smaller_wins(monkeypatch):
    scores = {(94, True): (5, 21036, 25292), (128, True): (5, 21036, 25405)}
    assert _search(monkeypatch, scores, None)["max_rows"] == 94


def test_a_shape_that_plays_more_rows_replaces_the_shipped_one(monkeypatch):
    scores = {(94, True): (5, 21040, 25500), (128, True): (5, 21036, 25405)}
    assert _search(monkeypatch, scores, _shape(128, True))["max_rows"] == 94


def test_a_shipped_shape_that_no_longer_converts_is_not_kept(monkeypatch):
    scores = {(94, True): (5, 21036, 25292)}
    assert _search(monkeypatch, scores, _shape(128, True))["max_rows"] == 94


def test_a_toggle_only_smaller_keeps_the_shipped_one(monkeypatch):
    scores = {(128, False): (1, 8132, 12790), (128, True): (1, 8132, 12791)}
    assert _search(monkeypatch, scores, _shape(128, True))["dedup"] is True
