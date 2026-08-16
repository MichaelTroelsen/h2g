"""`listen.py --all`: stage every tune that converts.

The flag's whole content is *which* list it reads. Reading the corpus
directory would queue the twelve files no player is detected in and render a
silent conversion side for each — which reads as a fidelity catastrophe rather
than an absent player — so it reads `presets.json`'s song list, which is
exactly the tunes that convert.
"""
import json
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import listen as L  # noqa: E402


def _presets(tmp_path, songs):
    p = tmp_path / "presets.json"
    p.write_text(json.dumps({"always": {}, "songs": songs}), encoding="utf-8")
    return str(p)


def test_without_all_the_named_files_are_the_list(tmp_path):
    got = L.select_names(["B.sid", "A.sid"], False, _presets(tmp_path, {}))
    assert got == ["B.sid", "A.sid"]


def test_all_takes_every_song_the_presets_record(tmp_path):
    src = _presets(tmp_path, {"Delta.sid": {}, "ACE_II.sid": {}, "W_A_R.sid": {}})
    assert L.select_names([], True, src) == ["ACE_II.sid", "Delta.sid", "W_A_R.sid"]


def test_all_sorts_case_insensitively_like_the_search_does(tmp_path):
    src = _presets(tmp_path, {"Zoids.sid": {}, "acid.sid": {}})
    assert L.select_names([], True, src) == ["acid.sid", "Zoids.sid"]


def test_files_and_all_combine_rather_than_compete(tmp_path):
    """A tune outside the presets — a second rip, a file under test — joins a
    full pass by being named as well."""
    src = _presets(tmp_path, {"Delta.sid": {}})
    assert L.select_names(["Odd.sid"], True, src) == ["Delta.sid", "Odd.sid"]


def test_a_named_file_already_in_the_presets_is_not_staged_twice(tmp_path):
    src = _presets(tmp_path, {"Delta.sid": {}})
    assert L.select_names(["Delta.sid"], True, src) == ["Delta.sid"]


def test_all_without_presets_says_what_to_run(tmp_path):
    with pytest.raises(ValueError, match="presets.py"):
        L.select_names([], True, str(tmp_path / "missing.json"))


def test_all_with_an_empty_song_list_refuses(tmp_path):
    """An empty presets.json and a corpus that converts nothing are the same
    file; staging silently zero tunes would look like success."""
    with pytest.raises(ValueError, match="no songs"):
        L.select_names([], True, _presets(tmp_path, {}))


def test_the_real_presets_name_the_convertible_corpus():
    """The list --all reads is the one the rest of the harness uses, so it
    cannot drift from what actually converts."""
    root = Path(__file__).resolve().parents[2]
    presets = root / "presets.json"
    if not presets.exists():
        pytest.skip("presets.json not generated")
    got = L.select_names([], True, str(presets))
    assert len(got) > 50
    assert all(n.endswith(".sid") for n in got)
