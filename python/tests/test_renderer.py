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
    fn, why = L.pick_renderer(_psid(tmp_path), _args(tmp_path))
    assert why == ""
    fn(_psid(tmp_path), tmp_path / "o.wav", 1, 0)
    assert calls == ["fp", "fp"]          # the probe, then the real call


def test_it_falls_back_to_sid2wav_for_a_psid(tmp_path, monkeypatch):
    """A machine without sidplayfp still stages a pass."""
    Path(tmp_path / "sid2wav.exe").write_text("x")
    used = []
    monkeypatch.setattr(L, "render", lambda s, o, sec, sub, exe=None: used.append("s2w") or True)
    fn, why = L.pick_renderer(_psid(tmp_path), _args(tmp_path))
    fn(_psid(tmp_path), tmp_path / "o.wav", 1, 0)
    assert used == ["s2w"]


def test_an_rsid_without_sidplayfp_goes_to_vice(tmp_path, monkeypatch):
    """sid2wav is a 1997 build and refuses every RSID; VICE reads them."""
    used = []
    monkeypatch.setattr(L, "render_vsid", lambda s, o, sec, sub: used.append("vsid") or True)
    rsid = _psid(tmp_path, "r.sid", b"RSID")
    fn, why = L.pick_renderer(rsid, _args(tmp_path))
    fn(rsid, tmp_path / "o.wav", 1, 0)
    assert used == ["vsid"]
    assert "VICE" in why


def test_a_refusing_sidplayfp_does_not_split_the_pair(tmp_path, monkeypatch):
    """The regression this function exists to prevent. If sidplayfp cannot read
    the original -- the C64 ROMs are the usual reason -- the *pair* moves to
    another engine, never just one side of it."""
    Path(tmp_path / "sidplayfp.exe").write_text("x")
    Path(tmp_path / "sid2wav.exe").write_text("x")
    monkeypatch.setattr(L, "render_sidplayfp", lambda s, o, sec, sub, exe=None: False)
    used = []
    monkeypatch.setattr(L, "render", lambda s, o, sec, sub, exe=None: used.append("s2w") or True)
    fn, why = L.pick_renderer(_psid(tmp_path), _args(tmp_path))
    assert "ROMs" in why
    for side in ("original", "ours"):
        fn(_psid(tmp_path), tmp_path / f"{side}.wav", 1, 0)
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


def test_the_probe_is_one_second_not_the_whole_render(tmp_path, monkeypatch):
    """Choosing a renderer must not cost a full pass per tune."""
    Path(tmp_path / "sidplayfp.exe").write_text("x")
    seen = []
    monkeypatch.setattr(L, "render_sidplayfp",
                        lambda s, o, sec, sub, exe=None: seen.append(sec) or True)
    L.pick_renderer(_psid(tmp_path), _args(tmp_path))
    assert seen == [1]
