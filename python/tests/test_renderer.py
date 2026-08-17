"""`listen.py`'s renderer choice.

One property matters above the rest: **both sides of a pair go through the same
engine**. Two SID emulations differ in level and filter enough to colour a
listening verdict, and the whole staging exists to support such verdicts — so a
pair split across two renderers is worse than a pair that fails to render.
`pick_renderer` returns one callable for exactly that reason; before it, a
fallback inside the per-side call could split them.
"""
import sys
import types
from collections import Counter
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import listen as L  # noqa: E402


def _args(tmp_path, **over):
    a = types.SimpleNamespace(
        sidplayfp=str(tmp_path / "sidplayfp.exe"),
        sid2wav=str(tmp_path / "sid2wav.exe"),
        outdir=str(tmp_path), subtune=0)
    for k, v in over.items():
        setattr(a, k, v)
    return a


def _psid(tmp_path, name="a.sid", magic=b"PSID"):
    p = tmp_path / name
    p.write_bytes(magic + b"\x00" * 200)
    return p


def test_sidplayfp_is_preferred_when_it_works(tmp_path, monkeypatch):
    Path(tmp_path / "sidplayfp.exe").write_text("x")
    calls = []
    monkeypatch.setattr(L, "render_sidplayfp",
                        lambda s, o, sec, sub, exe=None: calls.append("fp") or True)
    c = L.pick_renderer(_psid(tmp_path), _args(tmp_path))
    assert c.why == ""
    assert c.engine == "sidplayfp"
    c.render(_psid(tmp_path), tmp_path / "o.wav", 1, 0)
    assert calls == ["fp", "fp"]          # the probe, then the real call


def test_it_falls_back_to_sid2wav_for_a_psid(tmp_path, monkeypatch):
    """A machine without sidplayfp still stages a pass."""
    Path(tmp_path / "sid2wav.exe").write_text("x")
    used = []
    monkeypatch.setattr(L, "render", lambda s, o, sec, sub, exe=None: used.append("s2w") or True)
    c = L.pick_renderer(_psid(tmp_path), _args(tmp_path))
    assert c.engine == "sid2wav"
    c.render(_psid(tmp_path), tmp_path / "o.wav", 1, 0)
    assert used == ["s2w"]


def test_an_rsid_without_sidplayfp_goes_to_vice(tmp_path, monkeypatch):
    """sid2wav is a 1997 build and refuses every RSID; VICE reads them."""
    used = []
    monkeypatch.setattr(L, "render_vsid", lambda s, o, sec, sub: used.append("vsid") or True)
    rsid = _psid(tmp_path, "r.sid", b"RSID")
    c = L.pick_renderer(rsid, _args(tmp_path))
    assert c.engine == "vsid"
    c.render(rsid, tmp_path / "o.wav", 1, 0)
    assert used == ["vsid"]
    assert "VICE" in c.why


def test_a_refusing_sidplayfp_does_not_split_the_pair(tmp_path, monkeypatch):
    """The regression this function exists to prevent. If sidplayfp cannot read
    the original -- the C64 ROMs are the usual reason -- the *pair* moves to
    another engine, never just one side of it."""
    Path(tmp_path / "sidplayfp.exe").write_text("x")
    Path(tmp_path / "sid2wav.exe").write_text("x")
    monkeypatch.setattr(L, "render_sidplayfp", lambda s, o, sec, sub, exe=None: False)
    used = []
    monkeypatch.setattr(L, "render", lambda s, o, sec, sub, exe=None: used.append("s2w") or True)
    c = L.pick_renderer(_psid(tmp_path), _args(tmp_path))
    assert "ROMs" in c.why
    assert c.engine == "sid2wav"
    for side in ("original", "ours"):
        c.render(_psid(tmp_path), tmp_path / f"{side}.wav", 1, 0)
    assert used == ["s2w", "s2w"]


def test_the_probe_file_is_cleaned_up(tmp_path, monkeypatch):
    """The probe renders one second to decide; leaving it behind would put a
    stray _probe.wav in the listening directory, where abpage.py globs."""
    Path(tmp_path / "sidplayfp.exe").write_text("x")

    def fake(s, o, sec, sub, exe=None):
        Path(o).write_bytes(b"RIFF" + b"\x00" * 200)
        return True

    monkeypatch.setattr(L, "render_sidplayfp", fake)
    L.pick_renderer(_psid(tmp_path), _args(tmp_path))
    assert not (tmp_path / "_probe.wav").exists()


def test_the_probe_goes_in_the_private_dir_not_the_shared_one(tmp_path, monkeypatch):
    """The probe is a fixed filename. Written into the *output* directory --
    which sharded passes share -- two shards race on it and one silently
    stages nothing, which is what happened before this argument existed. It
    belongs in the per-run workdir, the same isolation make_workdir provides.
    """
    Path(tmp_path / "sidplayfp.exe").write_text("x")
    private = tmp_path / "private"
    private.mkdir()
    shared = tmp_path / "shared"
    shared.mkdir()
    where = []

    def fake(s, o, sec, sub, exe=None):
        where.append(Path(o).parent)
        Path(o).write_bytes(b"RIFF" + b"\x00" * 200)
        return True

    monkeypatch.setattr(L, "render_sidplayfp", fake)
    L.pick_renderer(_psid(tmp_path), _args(tmp_path, outdir=str(shared)), private)
    assert where == [private]
    assert not list(shared.glob("*.wav"))


def test_the_probe_is_one_second_not_the_whole_render(tmp_path, monkeypatch):
    """Choosing a renderer must not cost a full pass per tune."""
    Path(tmp_path / "sidplayfp.exe").write_text("x")
    seen = []
    monkeypatch.setattr(L, "render_sidplayfp",
                        lambda s, o, sec, sub, exe=None: seen.append(sec) or True)
    L.pick_renderer(_psid(tmp_path), _args(tmp_path))
    assert seen == [1]


# --- what the staged document says the run did -------------------------------
#
# `LISTENING.md`'s header is the only place a reader learns which emulator and
# which subtune produced the pass, and it asserted `SID2WAV` from a constant
# for four versions after v0.5.308 had moved the staging to `sidplayfp`. These
# pin it to the run instead. Joined with a space rather than a newline: every
# claim under test sits inside one element, and the join is not the subject.


def _hdr_args(**over):
    a = types.SimpleNamespace(seconds=30, subtune="auto")
    for k, v in over.items():
        setattr(a, k, v)
    return a


def test_the_header_names_the_engine_that_ran():
    head = " ".join(L.document_header(
        _hdr_args(), Counter({"sidplayfp": 83}), [("a", 0, 0)]))
    assert "`sidplayfp`" in head
    assert "SID2WAV" not in head


def test_a_mixed_pass_names_every_engine_and_says_pairs_only():
    """The fallback is per pair, so one pass can legitimately use two engines.
    Saying so is the point: two tunes rendered by different emulators are not
    comparable with each other, only within their own pair."""
    head = " ".join(L.document_header(
        _hdr_args(), Counter({"sidplayfp": 79, "vsid": 4}), [("a", 0, 0)]))
    assert "`sidplayfp` (79)" in head and "`vsid` (4)" in head
    assert "per *pair*" in head


def test_the_header_reports_how_many_subtunes_are_not_zero():
    rows = [("a", 0, 0), ("b", 4, 4), ("c", 9, 10)]
    head = " ".join(L.document_header(
        _hdr_args(), Counter({"sidplayfp": 3}), rows))
    assert "2 of 3 are not 0" in head


def test_a_forced_subtune_is_reported_as_forced():
    head = " ".join(L.document_header(
        _hdr_args(subtune=3), Counter({"sidplayfp": 1}), [("a", 3, 3)]))
    assert "subtune 3" in head and "startSong" not in head


# --- which subtune each side is rendered at ----------------------------------


def test_the_original_is_rendered_at_its_own_startsong(tmp_path, monkeypatch):
    """Seven corpus files name something other than 0, and one of those
    subtune 0s is a one-note stub. A pass staged at 0 for those asks a listener
    about music no measurement in the repo ever compared."""
    monkeypatch.setattr(L, "resolve_subtune", lambda sid, req: 9)
    assert L.pair_subtunes(_psid(tmp_path), {}, "auto") == (9, 9)


def test_our_side_follows_the_counterpart_a_fidelity_row_found(tmp_path, monkeypatch):
    """Our numbering shifts when gt2reloc drops a subtune, so the same tune can
    be index 9 in the original and 10 in ours."""
    monkeypatch.setattr(L, "resolve_subtune", lambda sid, req: 9)
    assert L.pair_subtunes(_psid(tmp_path), {"matched_subtune": 10},
                           "auto") == (9, 10)


def test_a_forced_number_overrides_both_sides(tmp_path):
    assert L.pair_subtunes(_psid(tmp_path), {}, 2) == (2, 2)


def test_the_probe_resolves_auto_rather_than_passing_it_on(tmp_path, monkeypatch):
    """`-o{subtune + 1}` cannot take the string "auto". The probe renders one
    second to choose an engine, so it has to resolve the same way the real
    render will."""
    Path(tmp_path / "sidplayfp.exe").write_text("x")
    monkeypatch.setattr(L, "resolve_subtune", lambda sid, req: 4)
    seen = []
    monkeypatch.setattr(L, "render_sidplayfp",
                        lambda s, o, sec, sub, exe=None: seen.append(sub) or True)
    L.pick_renderer(_psid(tmp_path), _args(tmp_path, subtune="auto"))
    assert seen == [4]


def test_a_shard_states_the_policy_and_counts_nothing():
    """`merge_notes` keeps the first part's header, so a count taken over one
    shard's tunes would be published as a count over the whole pass."""
    head = " ".join(L.document_header(
        _hdr_args(), Counter({"sidplayfp": 7}), [("a", 0, 0), ("b", 4, 4)],
        shard=(0, 4)))
    assert "of 2" not in head and "(7)" not in head
    assert "startSong" in head and "one engine" in head
