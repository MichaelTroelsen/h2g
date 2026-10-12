"""Flash_Gordon subtune 2: the bounds-engine pulse program sweeps the player's band.

Opened by free-note-pulse-only-variant at 6e467ff, which measured ours at
504-512 units of duty-cycle span against the original's 272 (pspan 1.85-1.88)
and called the instrument "already nearly twice too wide". The cause was the
per-record-bounds engine aiming each leg at the bound itself (`high << 8` going
up) where the player turns on the first width of its step lattice whose high
nibble EQUALS the bound. bounds-engine-lattice-turns (v0.5.528, merge 6f346b6)
put the legs on the lattice (`_lattice_legs`); this task found the defect
already gone at e16bddb and bisected the fix to that merge:

    commit   sha      -a 2 pulse span (orig / ours), -t 180 (30 s tune), presets
    v0.5.514 86ac533  272 / 512
    v0.5.521 ae5b063  272 / 512
    v0.5.527 a6ccf89  272 / 512
    v0.5.528 6f346b6  272 / 272
    v0.5.532 e16bddb  272 / 272   (pspan 1.00; pul 1475 orig / 1494 ours)

Voice 0 carries the whole sweep; voices 1 and 2 write one width and have none.
This test pins the span at the traced window so the regression the earlier
measurement saw cannot come back without a named failure.
"""
import pathlib
import sys

import pytest

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[1]))

import fidelity                                              # noqa: E402
from corpus import CORPUS, needs_corpus                      # noqa: E402
from h2g.convert import convert                              # noqa: E402

REPO_ROOT = pathlib.Path(__file__).resolve().parents[2]
NAME = "Flash_Gordon.sid"
SUBTUNE = 2
SECONDS = 30

needs_siddump = pytest.mark.skipif(
    not pathlib.Path(fidelity.SIDDUMP).exists(),
    reason="no siddump on this machine (tools/siddump-rt, see its README)")
needs_gt2reloc = pytest.mark.skipif(
    not pathlib.Path(fidelity.GT2RELOC).exists(),
    reason="no gt2reloc on this machine")


@needs_corpus
@needs_siddump
@needs_gt2reloc
def test_subtune_two_pulse_band_matches_the_original(tmp_path):
    import json
    presets = json.loads((REPO_ROOT / "presets.json").read_text(encoding="utf-8"))
    m = presets["songs"][NAME]["multiplier"]
    sng = convert(str(CORPUS / NAME), log=lambda x: None,
                  **fidelity._preset_opts(presets, NAME))
    packed = fidelity.pack_sid(sng, tmp_path, fidelity.GT2RELOC, m)
    assert packed is not None and packed.exists()
    orig = fidelity.run_siddump(CORPUS / NAME, SECONDS, SUBTUNE, calls=1)
    ours = fidelity.run_siddump(packed, SECONDS, SUBTUNE, calls=m)
    res = fidelity.pulse_compare(orig, ours, SECONDS * 50)
    v0 = res["pulse_voices"][0]
    # the instrument is on voice 0; the sweep is real (not a frozen width)
    assert v0["orig_pulse_span"] > 200 and v0["orig_pulse_changes"] > 1000
    # 512 against 272 before 6f346b6; 272 against 272 after.
    assert 0.95 <= v0["pulse_span"] <= 1.05, v0
    assert 0.95 <= res["pulse_span"] <= 1.05, res["pulse_span"]
    # the count must not have been traded away to get the band right
    assert 0.9 <= v0["our_pulse_changes"] / v0["orig_pulse_changes"] <= 1.1, v0
