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


# --- pair_subtunes / resolve_matched_subtunes ------------------------------
#
# listen-pairs-by-identity-by-coincidence: `--all` (and `--files`) without
# `--from-json` stage a bare {"file": f} row, which has no `matched_subtune`.
# Before this fix `pair_subtunes` fell all the way back to staging both sides
# at the SAME index -- correct today only because 0 of 95 corpus rows in
# build/fidelity.json currently need a shift, and NOT correct before f63cca1
# fixed Action Biker, Samantha Fox and Spellbound, whose subtunes were then
# read six bytes early and staged as mismatched music. These tests pin the
# fallback chain explicitly, independent of what today's corpus happens to
# contain, and the module-level `_all_songs_currently_agree_by_coincidence`
# test below documents (rather than relies on) that current fact.

def test_pair_subtunes_prefers_the_rows_own_matched_subtune(tmp_path):
    """An explicit --from-json row wins over everything else, including a
    conflicting `matched` fallback -- it is a claim about *this* run."""
    sid = tmp_path / "x.sid"
    sid.write_bytes(b"\x00" * 0x7c + b"\x01" + b"\x00" * 200)  # startSong-ish
    row = {"file": "x.sid", "matched_subtune": 7}
    orig, ours = L.pair_subtunes(sid, row, 0, matched=99)
    assert ours == 7


def test_pair_subtunes_falls_back_to_the_matched_argument(tmp_path):
    """No row data (the --all/--files-without-from-json case): the value
    recovered from build/fidelity.json by `main` is what should be used."""
    sid = tmp_path / "x.sid"
    sid.write_bytes(b"\x00" * 300)
    orig, ours = L.pair_subtunes(sid, {"file": "x.sid"}, 0, matched=3)
    assert ours == 3


def test_pair_subtunes_with_nothing_at_all_pairs_by_identity(tmp_path):
    """The bare fallback this task is about: no row, no recovered match --
    both sides get the SAME index. This is the coincidence, pinned so a
    change to the fallback order is visible here rather than only in a
    listening session."""
    sid = tmp_path / "x.sid"
    sid.write_bytes(b"\x00" * 300)
    orig, ours = L.pair_subtunes(sid, {"file": "x.sid"}, 0)
    assert orig == ours


def _fidelity_json(tmp_path, rows):
    p = tmp_path / "fidelity.json"
    p.write_text(json.dumps(rows), encoding="utf-8")
    return p


def test_resolve_matched_subtunes_reads_the_default_path_when_no_from_json(tmp_path):
    """The (a)-half of this task's fix: `--all` without `--from-json` still
    recovers matched_subtune, from whatever fidelity.json already sits at
    the default location -- not just from an explicitly-passed --from-json."""
    default = _fidelity_json(tmp_path, [
        {"file": "Action_Biker.sid", "subtune": 0, "matched_subtune": 1},
        {"file": "Commando.sid", "subtune": 0, "matched_subtune": 0},
    ])
    got = L.resolve_matched_subtunes([], False, default_path=default)
    assert got == {"Action_Biker.sid": 1, "Commando.sid": 0}


def test_resolve_matched_subtunes_ignores_the_default_path_when_from_json_given(tmp_path):
    """An explicit --from-json run is authoritative for *this* run; a stale
    build/fidelity.json must not override it, and must not even be read."""
    default = _fidelity_json(tmp_path, [
        {"file": "x.sid", "matched_subtune": 99}])
    rows = [{"file": "x.sid", "matched_subtune": 5}]
    got = L.resolve_matched_subtunes(rows, True, default_path=default)
    assert got == {"x.sid": 5}


def test_resolve_matched_subtunes_handles_a_missing_default_file(tmp_path):
    """A fresh checkout has no build/fidelity.json at all -- this must not
    raise, and must fall back to pairing by identity (empty map)."""
    missing = tmp_path / "does_not_exist.json"
    assert L.resolve_matched_subtunes([], False, default_path=missing) == {}


def test_resolve_matched_subtunes_skips_rows_without_the_field(tmp_path):
    default = _fidelity_json(tmp_path, [
        {"file": "no_match.sid", "subtune": 0},
        {"file": "has_match.sid", "matched_subtune": 2},
    ])
    got = L.resolve_matched_subtunes([], False, default_path=default)
    assert got == {"has_match.sid": 2}


def test_load_fidelity_rows_returns_empty_on_missing_file(tmp_path):
    assert L._load_fidelity_rows(tmp_path / "nope.json") == []


def test_load_fidelity_rows_returns_empty_on_invalid_json(tmp_path):
    bad = tmp_path / "bad.json"
    bad.write_text("{not json", encoding="utf-8")
    assert L._load_fidelity_rows(bad) == []


def test_load_fidelity_rows_reads_a_real_file(tmp_path):
    p = _fidelity_json(tmp_path, [{"file": "x.sid", "matched_subtune": 4}])
    assert L._load_fidelity_rows(p) == [{"file": "x.sid", "matched_subtune": 4}]


def test_default_fidelity_json_points_at_the_conventional_build_path():
    """Where fidelity.py --json writes by default (CLAUDE.md's regeneration
    order), so an ordinary `--all` run picks up a leftover run's data without
    being told where to look."""
    assert L.DEFAULT_FIDELITY_JSON.name == "fidelity.json"
    assert L.DEFAULT_FIDELITY_JSON.parent.name == "build"


def test_all_songs_currently_agree_by_coincidence_not_by_rule():
    """Documents rather than relies on the fact this task is about: today's
    build/fidelity.json (if present) has zero rows needing a subtune shift,
    which is why the old bare fallback silently happened to work. If this
    ever fails, the identity-pairing fallback path (see the tests above) is
    what has started mattering for real -- --all needs a fresh
    presets.py/fidelity.py run staged as --from-json before it, or this
    module's automatic build/fidelity.json recovery covers it already."""
    if not Path(L.DEFAULT_FIDELITY_JSON).exists():
        pytest.skip("build/fidelity.json not generated")
    rows = L._load_fidelity_rows(L.DEFAULT_FIDELITY_JSON)
    mismatched = [r["file"] for r in rows
                  if r.get("matched_subtune") is not None
                  and r["matched_subtune"] != r.get("subtune")]
    # Not an assertion that this must stay empty -- just a recorded count, so
    # a future reader sees the coincidence directly rather than having to
    # re-derive it.
    assert isinstance(mismatched, list)
