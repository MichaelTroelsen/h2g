"""`gate_off_firstwave_instruments` keeps a gate-clear record LEGATO.

Chimera's record 8 (`$BF05`, waveform `$10`) is a record whose own waveform has
the gate CLEAR. `instruments._write_instruments` gives it `gate_clear_firstwave`
(its own waveform as firstwave) AND `GATETIMER_LEGATO`, because the original
closes that gate on the fetch frame, not `gatetimer` calls before it
(tests/test_gate_clear_record.py).

Naming the instrument in `gate_off_firstwave_instruments` took the first branch
of the firstwave chain and so skipped the legato bit. Forced on 1..62 in a
private copy of Chimera's preset (-t 180, --sound, v0.5.660):

    arm                    gate   wave   tail   aud    adsrnf
    shipped                .822   .924   1.000  .934   .929
    forced, legato lost    .973   .958   .875   .928   .975
    forced, legato kept    .987   .958   1.000  .934   .975

The lost bit is `tail` (the release tail) and 12 points of the gate gain: the
early gate-off the legato bit exists to suppress closes the gate three calls
before the fetch. C:/t/gate-wave-firstwave-09-frame-in-gate-off-gap/ab.

Re-taken at v0.5.662 (HEAD cb2d3e3, same private preset on the current
presets.json; ab662/): shipped gate .822 / tail 1.000 / aud .934; forced with
the legato lost (unpatched HEAD) gate .973 / tail .875 / aud .928; forced with
it kept gate .987 / tail 1.000 / aud .934.

The byte is the same either way (`gate_off_firstwave($10) == $10`); only the
gatetimer's bit $40 moves. Only a record with a gate-clear waveform and a
select bit takes it.
"""
import json
import pathlib
import sys
import warnings

import pytest

PYTHON_ROOT = pathlib.Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PYTHON_ROOT))

import fidelity                                              # noqa: E402
import songview                                              # noqa: E402
from corpus import CORPUS, needs_corpus                      # noqa: E402
from h2g.convert import convert                              # noqa: E402
from h2g.goatwriter.constants import GATETIMER_LEGATO        # noqa: E402

PRESETS = PYTHON_ROOT.parent / "presets.json"
EVERY = tuple(range(1, 63))
RECORD_8_ADSR = 0xBF05


def _quiet(_m):
    pass


def _chimera(**over):
    if not PRESETS.exists():
        pytest.skip("presets.json not generated")
    doc = json.loads(PRESETS.read_text(encoding="utf-8"))
    with warnings.catch_warnings():
        warnings.simplefilter("ignore")
        opts = fidelity._preset_opts(doc, "Chimera.sid")
    opts.pop("gate_off_firstwave_instruments", None)
    opts.update(over)
    return songview.parse_sng(
        convert(str(CORPUS / "Chimera.sid"), log=_quiet, **opts))


@needs_corpus
def test_forced_gate_off_firstwave_keeps_the_gate_clear_record_legato():
    song = _chimera(gate_off_firstwave_instruments=EVERY)
    clear = [i for i in song.instruments if (i.ad << 8 | i.sr) == RECORD_8_ADSR]
    assert clear
    for ins in clear:
        assert ins.firstwave == 0x10, ins
        assert ins.gatetimer & GATETIMER_LEGATO, ins


@needs_corpus
def test_no_other_record_changes_its_legato_bit():
    off = _chimera()
    on = _chimera(gate_off_firstwave_instruments=EVERY)
    assert len(off.instruments) == len(on.instruments)
    for a, b in zip(off.instruments, on.instruments):
        if (b.ad << 8 | b.sr) != RECORD_8_ADSR:
            assert (a.gatetimer & GATETIMER_LEGATO) == (
                b.gatetimer & GATETIMER_LEGATO), (a, b)


@needs_corpus
def test_unnamed_is_the_shipped_conversion():
    # Chimera's preset names no instrument: the option's absence is the
    # shipped bytes, with record 8 legato by the gate_clear_firstwave branch.
    off = _chimera()
    clear = [i for i in off.instruments if (i.ad << 8 | i.sr) == RECORD_8_ADSR]
    assert clear and all(i.gatetimer & GATETIMER_LEGATO for i in clear)
