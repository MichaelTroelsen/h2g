"""`presets.py --shard` / `--merge`: splitting a corpus search across processes.

A sharded search is only worth having if the split cannot change the answer.
Two things make that true and both are tested here: the shards partition the
same sorted list (so their union is the corpus and no two overlap), and the
merge refuses any input set that would let a song be claimed twice or come
from a different version.

The end-to-end check is not here because it needs the corpus: three structural
shards merged reproduce the unsharded run's `songs` dict exactly (v0.5.303).
"""
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import presets as P  # noqa: E402


def _slice(names, index, count):
    """What main() does to `paths`, on names rather than Paths."""
    return sorted(names, key=str.lower)[index::count]


def test_the_shards_partition_the_corpus():
    names = ["%02d.sid" % i for i in range(83)]
    for count in (2, 3, 6, 7):
        seen = []
        for index in range(count):
            seen += _slice(names, index, count)
        assert sorted(seen) == sorted(names)
        assert len(seen) == len(set(seen))


def test_no_two_shards_share_a_song():
    names = ["%02d.sid" % i for i in range(83)]
    for count in (2, 3, 6):
        sets = [set(_slice(names, i, count)) for i in range(count)]
        for i in range(count):
            for j in range(i + 1, count):
                assert not sets[i] & sets[j]


def test_a_single_shard_is_the_whole_corpus():
    names = ["b.sid", "a.sid", "C.sid"]
    assert _slice(names, 0, 1) == sorted(names, key=str.lower)


def _doc(songs, always=None, criteria=None):
    return {"generator": "h2g test presets.py", "corpus": "x",
            "always": always if always is not None else {"fmt": "gts5"},
            "criteria": criteria if criteria is not None else ["a"],
            "songs": songs}


def _write(tmp_path, name, doc):
    p = tmp_path / name
    p.write_text(json.dumps(doc), encoding="utf-8")
    return str(p)


def test_merge_unions_disjoint_shards(tmp_path, capsys):
    a = _write(tmp_path, "a.json", _doc({"one.sid": {"max_rows": 94}}))
    b = _write(tmp_path, "b.json", _doc({"two.sid": {"max_rows": 128}}))
    out = tmp_path / "out.json"
    assert P.merge_shards([a, b], str(out)) == 0
    got = json.loads(out.read_text(encoding="utf-8"))
    assert set(got["songs"]) == {"one.sid", "two.sid"}
    assert got["songs"]["two.sid"]["max_rows"] == 128
    assert got["always"] == {"fmt": "gts5"}


def test_merge_sorts_case_insensitively_like_the_search_does(tmp_path):
    a = _write(tmp_path, "a.json", _doc({"Zoids.sid": {}, "acid.sid": {}}))
    out = tmp_path / "out.json"
    assert P.merge_shards([a], str(out)) == 0
    got = json.loads(out.read_text(encoding="utf-8"))
    assert list(got["songs"]) == ["acid.sid", "Zoids.sid"]


def test_merge_refuses_a_song_claimed_twice(tmp_path):
    """The only way a split goes wrong quietly: one shard's measurement
    silently replacing another's. Better to fail than to pick."""
    a = _write(tmp_path, "a.json", _doc({"one.sid": {"max_rows": 94}}))
    b = _write(tmp_path, "b.json", _doc({"one.sid": {"max_rows": 128}}))
    out = tmp_path / "out.json"
    assert P.merge_shards([a, b], str(out)) == 2
    assert not out.exists()


def test_merge_refuses_shards_that_disagree_on_always(tmp_path):
    """Two shards from different versions of the converter are two different
    measurements, and unioning them makes one file that was never true."""
    a = _write(tmp_path, "a.json", _doc({"one.sid": {}}, always={"fmt": "gts5"}))
    b = _write(tmp_path, "b.json", _doc({"two.sid": {}}, always={"fmt": "gts2"}))
    assert P.merge_shards([a, b], str(tmp_path / "out.json")) == 2


def test_merge_refuses_shards_that_disagree_on_criteria(tmp_path):
    a = _write(tmp_path, "a.json", _doc({"one.sid": {}}, criteria=["a"]))
    b = _write(tmp_path, "b.json", _doc({"two.sid": {}}, criteria=["a", "b"]))
    assert P.merge_shards([a, b], str(tmp_path / "out.json")) == 2


def test_merge_of_nothing_is_an_error_not_an_empty_file(tmp_path):
    """An empty presets.json is indistinguishable from a corpus that converts
    nothing, and would be adopted as one."""
    assert P.merge_shards([], str(tmp_path / "out.json")) == 2
