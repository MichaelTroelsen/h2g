"""A 900 s layout-perturbation check for the pattern clone
(`past_table_wave._split_patterns`).

Saboteur_II and Rock_Tells_the_Tale play a pattern under two orderlist
transposes, and one row overflows the wavetable under one of them. Without the
clone that row reads a cell past the table, where the packed player holds
gt2reloc's orderlist address bytes, so the pitch depends on how the packed
tables are laid out. The first such note is at frame ~9820 (~196 s), past
FIDELITY's 180 s window, so a 180 s layout comparison reads 0 differing
frames on the unsplit conversion too and cannot tell the two apart. This one
traces 900 s (45000 frames).

Layout is perturbed by packing the same conversion at the presets and with
`pulse_phase` + `compact_instruments=False` forced (different table sizes, so
gt2reloc lays the orderlists elsewhere). The clone is disabled by replacing
`_split_patterns` with a function that makes no copy.
"""
from __future__ import annotations

import subprocess
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent))

from h2g import past_table_wave as W  # noqa: E402

SECONDS = 900
LATE = 9000          # frames: FIDELITY's 180 s window ends here, the first overflow is ~9820
FILES = ("Saboteur_II.sid", "Rock_Tells_the_Tale.sid")
_CACHE: dict = {}


def _traces(path: Path, mult: int):
    """{voice: [frequency word per frame]} of subtune 1, every voice from one run."""
    import fidelity
    cmd = [fidelity.SIDDUMP, str(path), "-a1", f"-t{SECONDS}"]
    if mult > 1:
        cmd.append(f"-m{mult}")
    out = {0: [], 1: [], 2: []}
    cur = {0: None, 1: None, 2: None}
    for line in subprocess.run(cmd, capture_output=True, text=True).stdout.splitlines():
        if not (line.startswith("|") and line[2:7].strip().isdigit()):
            continue
        cols = line.split("|")
        for v in range(3):
            f = cols[2 + v].split()
            if f and f[0] != "....":
                cur[v] = f[0]
            out[v].append(cur[v])
    return out


def _layout_diffs(name: str, clone: bool, tmp_path: Path):
    """{voice: frames at which the presets pack and the perturbed pack
    disagree}, with the clone on or off."""
    key = (name, clone)
    if key in _CACHE:
        return _CACHE[key]
    import fidelity
    from h2g import convert as C
    from test_pulse_phase import _corpus_and_presets
    if not (Path(fidelity.SIDDUMP).exists() and Path(fidelity.GT2RELOC).exists()):
        pytest.skip("siddump or gt2reloc not available here")
    corpus, doc = _corpus_and_presets()
    if not (corpus / name).exists():
        pytest.skip(f"{name} not in the corpus here")
    mult = fidelity._preset_multiplier(doc, name)
    real = W._split_patterns
    if not clone:
        W._split_patterns = lambda song, sid, det, cache, top=None: {}
    try:
        traces = {}
        for tag, extra in (("presets", {}),
                           ("perturbed", {"pulse_phase": True,
                                          "compact_instruments": False})):
            kw = dict(fidelity._preset_opts(doc, name), **extra)
            blob = C.convert(str(corpus / name), log=lambda m: None, **kw)
            wd = tmp_path / f"{name}_{'clone' if clone else 'noclone'}_{tag}"
            wd.mkdir(parents=True)
            packed = fidelity.pack_sid(blob, wd, multiplier=mult)
            assert packed is not None, "gt2reloc refused"
            traces[tag] = _traces(packed, mult)
    finally:
        W._split_patterns = real
    res = {}
    for v in range(3):
        a, b = traces["presets"][v], traces["perturbed"][v]
        assert len(a) == len(b) >= SECONDS * 50 - 1, (len(a), len(b))
        res[v] = [i for i, (x, y) in enumerate(zip(a, b)) if x != y]
    _CACHE[key] = res
    return res


@pytest.fixture(scope="module")
def _tmp(tmp_path_factory):
    return tmp_path_factory.mktemp("long_window")


@pytest.mark.parametrize("name", FILES)
def test_without_the_clone_the_pitch_follows_the_layout_after_the_short_window(name, _tmp):
    """The control, and the proof the window has power: with no clone the
    layouts disagree, and only after the 180 s window."""
    diffs = _layout_diffs(name, False, _tmp)
    assert diffs[0], "no layout dependence without the clone: the check has no power"
    assert min(diffs[0]) >= LATE
    assert not [i for v in diffs for i in diffs[v] if i < LATE]


@pytest.mark.parametrize("name", FILES)
def test_with_the_clone_the_pitch_does_not_follow_the_layout_for_900_s(name, _tmp):
    diffs = _layout_diffs(name, True, _tmp)
    assert {v: len(d) for v, d in diffs.items()} == {0: 0, 1: 0, 2: 0}
