"""`--rest-wave-silence`: the bit-6 rest's parked waveform.

The option is off by default and stays off — see the measurement in the
commit for v0.5.311. What these tests pin is the *emission*, because three
attempts at this mechanism have now failed for three different reasons and
two of them were the emitter rather than the idea:

* v0.5.284 wrote 673 command bytes where 61 were designed, because a bit-6
  event's `wait` hold rows reused `cmd1`/`cmd2`.
* the command displaced `CMD_SETTEMPO` on the row each subtune enters on,
  which costs the song its tempo entirely — the whole of the −43 pp.
"""
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from h2g import patterns as P  # noqa: E402

CORPUS = Path(r"C:\Users\mit\claude\c64server\SIDM2\SID\Hubbard_Rob")
PRESETS = Path(__file__).resolve().parents[2] / "presets.json"


def test_setwave_is_a_one_shot_command():
    """It assigns `cptr->wave` once (gplay.c:433). Repeating it on the hold
    rows of a rest is what made v0.5.284's A/B measure something other than
    the change described."""
    assert P.CMD_SETWAVE in P.ONE_SHOT_COMMANDS


def test_the_silent_waveform_is_08_not_18():
    """Both are silent to the ear. `$18` is class `$10` to every register
    column and stays above the `$10` siddump needs to name the next attack,
    which is why v0.5.282's `$18` moved no column on any file."""
    assert P.REST_SILENT_WAVE == 0x08


def test_the_tempo_outranks_the_rests_waveform():
    """`apply_tempo` may overwrite CMD_SETWAVE and nothing else. Widening it
    to any free row was measured and refused: 25 files, 2 better and 3 worse,
    because the derived tempo is wrong on some of them."""
    patterns = [[P.GT_KEYOFF, 0, P.CMD_SETWAVE, 0x08] + [0, 0, 0, 0] * 3]
    tracks = [[0, 0xFF, 0], [0, 0xFF, 0], [0, 0xFF, 0]]
    assert P.apply_tempo(patterns, tracks, 6) == 1
    assert patterns[0][2] == P.CMD_SETTEMPO
    assert patterns[0][3] == 6


def test_a_real_command_still_blocks_the_tempo():
    """A slide on the entry row keeps the old behaviour -- the tempo is not
    written, because restoring it on those files measured 2 up and 3 down."""
    patterns = [[60, 1, 3, 0x00] + [0, 0, 0, 0] * 3]
    tracks = [[0, 0xFF, 0], [0, 0xFF, 0], [0, 0xFF, 0]]
    assert P.apply_tempo(patterns, tracks, 6) == 0
    assert patterns[0][2] == 3


def test_a_free_row_is_written_as_before():
    patterns = [[60, 1, 0, 0] + [0, 0, 0, 0] * 3]
    tracks = [[0, 0xFF, 0], [0, 0xFF, 0], [0, 0xFF, 0]]
    assert P.apply_tempo(patterns, tracks, 4) == 1
    assert patterns[0][2:4] == [P.CMD_SETTEMPO, 4]


def _detect(name):
    from h2g.detect import detect
    from h2g.sidfile import load_sid
    return detect(load_sid(str(CORPUS / name)), log=lambda *a, **k: None)


def test_the_two_silencing_families_are_told_apart():
    """Only the testbit family parks a waveform; the envelope-zeroing family
    writes none, so the option must not reach it."""
    import pytest
    if not CORPUS.exists():
        pytest.skip("corpus not present")
    assert _detect("IK_plus.sid").rest_silence_kind == "testbit"
    assert _detect("Ricochet.sid").rest_silence_kind == "envelope"
    assert _detect("Commando.sid").rest_silence_kind == ""


def test_rest_silences_still_means_either_family():
    """The old flag is unchanged in meaning -- 21 files, both kinds."""
    import pytest
    if not CORPUS.exists():
        pytest.skip("corpus not present")
    for name in ("IK_plus.sid", "Ricochet.sid"):
        assert _detect(name).rest_silences is True
    assert _detect("Commando.sid").rest_silences is False


def test_the_option_reaches_only_the_testbit_family():
    """Forced on, the bytes move for the 17 testbit files and nobody else."""
    import hashlib
    import pytest
    if not CORPUS.exists() or not PRESETS.exists():
        pytest.skip("corpus or presets not present")
    sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
    from fidelity import _preset_opts
    from h2g.convert import convert
    doc = json.loads(PRESETS.read_text(encoding="utf-8"))
    moved, checked = 0, 0
    for name in ("IK_plus.sid", "Ricochet.sid", "Commando.sid"):
        opts = _preset_opts(doc, name)
        a = hashlib.sha1(convert(str(CORPUS / name), log=lambda *x, **k: None,
                                 **opts)).hexdigest()
        opts["rest_wave_silence"] = True
        b = hashlib.sha1(convert(str(CORPUS / name), log=lambda *x, **k: None,
                                 **opts)).hexdigest()
        checked += 1
        if a != b:
            moved += 1
            assert name == "IK_plus.sid", f"{name} should not move"
    assert checked == 3 and moved == 1
