"""Two ways to lower the release period before a drum's gate rise above -S1,
both measured and neither shipped (task drum-release-and-adparam).

The SID's ADSR delay: a gate rise waits up to $8000 cycles (520 lines) when
the rate counter is above the attack period, and nothing has lowered the
period before a drum (see `wavetable._drum_tick_noise`). The original writes
ADSR $0000 before every rise.

1. **Release nibble 0 on the drum records** (`sr &= $F0` where the record's
   +7 has bit $01 in a drum player, at -S>1). It does remove the wrap -- VICE,
   60 s, drum voice swapped onto voice 3, rise -> first ENV3 increase -- but
   the drum's own release is what the listener hears after its gate-off tick,
   and R=0 cuts it: ENV3 summed over 8 frames from the rise falls by 44% on
   Rasputin, and `adsr_exact` / `release_tail_agreement` fall on 28 of the 29
   files it reaches, rising on none (mean -24 pp / -31 pp; `loud` falls on 23
   and rises on 6, mean -1 pp; `aud` falls on 27, mean -1.5 pp; `nrun` gains
   on two files).
2. **`gt2reloc -A0000`** (`adparam`, default $0F00). Under `presets.json`
   it changes NO packed byte on any of the 89 files that convert: every file
   carries `no_hard_restart`, so no USED instrument is a hard-restart
   instrument (greloc.c counts `numnormal` over used instruments only, and
   `player.s` assembles the `ADPARAM` store only for `NUMHRINSTR > 0`). It
   matters only where a hard restart is on, and there it lifts `adsr` (14
   files forced to `no_hard_restart=False`: mean +8.5 pp, `release_tail`,
   `loud`, `aud` unmoved) -- but `adparam` is not stored in the `.sng`, so
   GoatTracker would play $0F00 while the harness measured $0000.

The measured numbers are a keyed table (no code to mutate there); the two
code-facing pins at the bottom break if either variant is adopted by accident.
"""
import json
import subprocess
import sys
import warnings
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
sys.path.insert(0, str(Path(__file__).resolve().parent))

from corpus import CORPUS, needs_corpus  # noqa: E402

# VICE, 60 s, under presets, e = ENV3 per raster line, the voice-3 swap of
# p/dumpx.py. Per file: (multiplier, share of drum attacks whose rise -> first
# ENV3 increase is <= 5 lines, head then rel0; ENV3 summed over the 8 frames
# from the rise, mean, head then rel0). The original on Rasputin: delay 1 line
# on 156 of 156, tail sum 531166.
RELEASE_ZERO = {
    # file: (head_tail_sum, rel0_tail_sum)
    "Rasputin": (501665, 278660),
    "Formula_1_Simulator": (445903, 269841),
    "Warhawk": (460423, 252826),
    "Proteus": (486706, 316804),
    "Bump_Set_Spike": (534700, 331400),
}
RASPUTIN_ORIGINAL_TAIL_SUM = 531166
# rel0 share of attacks starting within 5 lines (head: 0.019 on Rasputin).
RELEASE_ZERO_ON_TIME = {"Rasputin": 0.864, "Formula_1_Simulator": 0.880,
                        "Warhawk": 0.911, "Proteus": 0.902,
                        "Bump_Set_Spike": 0.888}


@pytest.mark.parametrize("name", sorted(RELEASE_ZERO))
def test_release_zero_removes_the_wrap_but_costs_the_tail(name):
    head, rel0 = RELEASE_ZERO[name]
    assert RELEASE_ZERO_ON_TIME[name] > 0.85       # the wrap IS gone ...
    assert rel0 < 0.7 * head                       # ... and so is the tail


def test_head_keeps_the_originals_tail_where_rel0_does_not():
    head, rel0 = RELEASE_ZERO["Rasputin"]
    assert abs(head - RASPUTIN_ORIGINAL_TAIL_SUM) / RASPUTIN_ORIGINAL_TAIL_SUM < 0.06
    assert abs(rel0 - RASPUTIN_ORIGINAL_TAIL_SUM) / RASPUTIN_ORIGINAL_TAIL_SUM > 0.4


# ---------------------------------------------------------------------------
# code-facing pins
# ---------------------------------------------------------------------------
def _convert(name: str, **override):
    import fidelity as F
    from h2g.convert import convert
    root = Path(__file__).resolve().parents[2]
    doc = json.loads((root / "presets.json").read_text(encoding="utf-8"))
    with warnings.catch_warnings():
        warnings.simplefilter("ignore")
        opts = F._preset_opts(doc, name + ".sid")
        mult = F._preset_multiplier(doc, name + ".sid")
    opts.update(override)
    return convert(str(next(CORPUS.rglob(name + ".sid"))),
                   log=lambda *a, **k: None, **opts), mult


@needs_corpus
def test_rasputins_drum_records_keep_their_release_nibble():
    """Four drum records, ADSR $0A0B/$0909/$0706/$0F0F in the player; the
    conversion must carry each release nibble (B, 9, 6, F), not zero."""
    import songview as V
    sng, _ = _convert("Rasputin")
    song = V.parse_sng(sng)
    drums = [i for i in song.instruments
             if i.effect_byte is not None and i.effect_byte & 0x01]
    releases = {i.sr & 0x0F for i in drums}
    assert drums and 0 not in releases, [i.adsr for i in drums]
    assert {0x0B, 0x09, 0x06, 0x0F} <= releases, releases


def _pack(sng: bytes, mult: int, tmp: Path, tag: str, extra: list) -> bytes:
    import fidelity as F
    wd = tmp / tag
    wd.mkdir()
    (wd / "a.sng").write_bytes(sng)
    args = [F.GT2RELOC, "a.sng", "b.sid"]
    if mult > 1:
        args.append(f"-S{mult}")
    subprocess.run(args + ["-O0"] + extra, cwd=str(wd), timeout=120,
                   capture_output=True, stdin=subprocess.DEVNULL)
    out = wd / "b.sid"
    assert out.exists(), "gt2reloc refused"
    return out.read_bytes()


def _have_gt2reloc() -> bool:
    import fidelity as F
    return Path(F.GT2RELOC).exists()


@needs_corpus
@pytest.mark.skipif(not _have_gt2reloc(), reason="gt2reloc not built")
@pytest.mark.parametrize("name", ["Rasputin", "Warhawk", "Action_Biker"])
def test_adparam_zero_changes_no_packed_byte_under_presets(name, tmp_path):
    sng, mult = _convert(name)
    plain = _pack(sng, mult, tmp_path, "plain", [])
    zero = _pack(sng, mult, tmp_path, "a0000", ["-A0000"])
    assert plain == zero


@needs_corpus
@pytest.mark.skipif(not _have_gt2reloc(), reason="gt2reloc not built")
def test_adparam_zero_does_change_a_hard_restart_file(tmp_path):
    """The control: the pin above is not vacuous, -A0000 reaches the packed
    player as soon as a used instrument carries the hard restart."""
    sng, mult = _convert("Rasputin", no_hard_restart=False)
    plain = _pack(sng, mult, tmp_path, "plain", [])
    zero = _pack(sng, mult, tmp_path, "a0000", ["-A0000"])
    assert plain != zero
