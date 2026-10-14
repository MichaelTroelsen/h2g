"""The six split files whose layout dependence the first A/B could not show.

`past-table-variant-record-split` packed each conversion twice (presets, and
forced `pulse_phase`) and compared the frequency traces. Six of the eleven
split files read 0 in the no-split control, so for them only the static census
(`test_past_table_variant_record_split`) said the split mattered. Two reasons,
both found by `past-table-split-layout-perturbation`:

* forced `pulse_phase` does not move the layout of 5_Title_Tunes, Formula_1,
  Gerry, Star_Paws or Rock_Tells (same .sng size, same packed size): it
  was no perturbation at all for them;
* the A/B traced `-a1`..`-a{n}`, but siddump's `-a` is the 0-based subtune
  the packed player's init receives. Subtune 0 was never traced, and `-a{n}`
  is past the song table. Star_Paws' only overflow is orderlist 0 (subtune 0);
  every single-subtune file was traced as a nonexistent subtune.

The cell a past-the-table index reads is `(songtbllo[k] << 8) | freqtblhi[k]`
(`past_table_wave` docstring), the low byte of an orderlist ADDRESS, so any
change in the size of what gt2reloc lays out before the orderlists moves it.
A gt2reloc player option that adds code (`-E1` volume support, 7 bytes; `-D1`
sound-effect support, 168) moves every orderlist by that much and changes
nothing the music reads. Nineteen's only cell is k=4 on a 3-orderlist song,
`songtblhi[1]`: the HIGH byte of an address, which moves only when the shift
crosses a page, so it needs `-D1`.

For each file: the same .sng packed plain and with the option; with the split
disabled (`past_table_wave.mixed_split(False)`, the control) the overflowing
voice's frequency differs on frames the option does not otherwise touch; with
the split (the shipped conversion) no voice differs. `first` is the first
differing control frame, so the window is no longer than it must be.
"""
from __future__ import annotations

import subprocess
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent))

from h2g import past_table_wave as W            # noqa: E402
from test_past_table_split import _corpus_convert, _voice_freqs   # noqa: E402
from test_pulse_phase import _corpus_and_presets                  # noqa: E402

# (file, 0-based subtune, voice, gt2reloc option, seconds, first control
#  frame measured at 300 s)
_CASES = [
    ("Gerry_the_Germ.sid", 3, 1, "-E1", 5, 10),
    ("Formula_1_Simulator.sid", 0, 1, "-E1", 15, 498),
    ("5_Title_Tunes.sid", 1, 0, "-E1", 30, 1050),
    ("Star_Paws.sid", 0, 0, "-E1", 70, 2816),
    ("Nineteen.sid", 0, 0, "-D1", 95, 4242),
    ("Rock_Tells_the_Tale.sid", 0, 0, "-E1", 270, 12967),
]


def _tools():
    import fidelity
    if not (Path(fidelity.SIDDUMP).exists() and Path(fidelity.GT2RELOC).exists()):
        pytest.skip("siddump or gt2reloc not available here")
    return fidelity


def _pack(fidelity, sng: bytes, wd: Path, mult: int, option: str | None):
    """`fidelity.pack_sid` plus one gt2reloc option (they follow both filenames)."""
    wd.mkdir(parents=True, exist_ok=True)
    (wd / "a.sng").write_bytes(sng)
    dst = wd / "b.sid"
    dst.unlink(missing_ok=True)
    args = [fidelity.GT2RELOC, "a.sng", "b.sid"]
    if mult > 1:
        args.append(f"-S{mult}")
    args.append("-O0")
    if option:
        args.append(option)
    subprocess.run(args, cwd=str(wd), timeout=120, capture_output=True,
                   stdin=subprocess.DEVNULL)
    assert dst.exists(), f"gt2reloc refused ({option})"
    return dst


def _differs(fidelity, sng, tmp_path, mult, option, sub, secs, voices=(0, 1, 2)):
    """Per voice, frames whose frequency differs between the plain pack and
    the one with `option`; and the two packed sizes (the layout did move)."""
    a = _pack(fidelity, sng, tmp_path / "plain", mult, None)
    b = _pack(fidelity, sng, tmp_path / "opt", mult, option)
    assert a.stat().st_size != b.stat().st_size, "the option did not move the layout"
    out = {}
    for v in voices:
        fa = _voice_freqs(a, sub, secs, mult, v)
        fb = _voice_freqs(b, sub, secs, mult, v)
        assert len(fa) == len(fb) > 0
        out[v] = sum(x != y for x, y in zip(fa, fb))
    return out


def _control(name: str) -> bytes:
    """The shipped conversion with only the mixed-step split switched off."""
    import fidelity
    from h2g import convert as C
    corpus, doc = _corpus_and_presets()
    kw = fidelity._preset_opts(doc, name)
    with W.mixed_split(False):
        return C.convert(str(corpus / name), log=lambda m: None, **kw)


@pytest.mark.parametrize("name,sub,voice,option,secs,first", _CASES,
                         ids=[c[0] for c in _CASES])
def test_the_control_hears_the_layout_and_the_split_does_not(
        name, sub, voice, option, secs, first, tmp_path):
    fidelity = _tools()
    _corpus, doc = _corpus_and_presets()
    mult = fidelity._preset_multiplier(doc, name)
    assert first < secs * 50, "the window must reach the first differing frame"

    control = _differs(fidelity, _control(name), tmp_path / "control", mult,
                       option, sub, secs, voices=(voice,))
    assert control[voice] > 0, "the control no longer hears the layout"

    split = _differs(fidelity, _corpus_convert(name)[0], tmp_path / "split",
                     mult, option, sub, secs)
    assert split == {0: 0, 1: 0, 2: 0}, split
