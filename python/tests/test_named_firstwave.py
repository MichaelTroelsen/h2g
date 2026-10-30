"""`named_firstwave`: let the note-init call's frame carry a pitch step siddump
can NAME.

siddump prints a note, a tie or an attack only on a frame whose waveform is
`>= $10` (siddump.c:434-437). The testbit `$09` every instrument writes on its
init call selects none, so at -S2 and above -- where the previous call of the
same frame has already stepped the arpeggio -- the step sits in the register
unnamed (`751A ... ..`) and the original's tie on that frame is charged to us
as `tie_orig_only_firstwave`. The option spends the init call on the record's
select bits with the test bit and the gate CLEAR (`$x8`).

At -S1 the init call writes no pitch (player.s `mt_loadregswaveonly`), so
nothing is carried: Mega_Apocalypse's 479 firstwave ties are RECLASSIFIED (the
frame is no longer sub-$10, so `_is_firstwave_frame` stops matching) and
`tie_same_frame` does not move. Pinned below so nobody reads that 479 -> 0 as
a gain.

Own file, per the task's optimistic-merge rule.
"""
import json
import pathlib
import sys

import pytest

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[1]))

import fidelity                                              # noqa: E402
import songview                                              # noqa: E402
from corpus import CORPUS, needs_corpus                      # noqa: E402
from h2g.convert import convert, GT_TEMPO_INSTRUMENT         # noqa: E402
from h2g.goatwriter.constants import FIRSTWAVE_TESTBIT       # noqa: E402
from h2g.goatwriter.instruments import (                     # noqa: E402
    gate_off_firstwave, named_testbit_firstwave)

REPO_ROOT = pathlib.Path(__file__).resolve().parents[2]
COMMANDO = REPO_ROOT / "Commando.sid"

needs_siddump = pytest.mark.skipif(
    not pathlib.Path(fidelity.SIDDUMP).exists(),
    reason="no siddump on this machine (tools/siddump-rt, see its README)")
needs_gt2reloc = pytest.mark.skipif(
    not pathlib.Path(fidelity.GT2RELOC).exists(),
    reason="no gt2reloc on this machine")


def _quiet(sid, **kw) -> bytes:
    return convert(str(sid), log=lambda m: None, **kw)


def _records(sng: bytes) -> list[int]:
    pos = songview.HEADER_LEN
    subtunes = sng[pos]
    pos += 1
    for _ in range(subtunes * 3):
        pos += sng[pos] + 2
    count = sng[pos]
    return [pos + 1 + k * 25 for k in range(count)]


@pytest.mark.parametrize("wave, want", [
    (0x41, 0x48), (0x81, 0x88), (0x11, 0x18), (0x21, 0x28), (0xF1, 0xF8),
    (0x40, 0x48),                        # the gate bit of the record is dropped
    (0x43, 0x4A), (0x15, 0x1C),          # sync/ring bits are kept, as gate-off keeps them
    (0xF7, FIRSTWAVE_TESTBIT), (0xFF, FIRSTWAVE_TESTBIT),   # would be $FE
    (0x00, FIRSTWAVE_TESTBIT), (0x08, FIRSTWAVE_TESTBIT),
    (0x09, FIRSTWAVE_TESTBIT)])          # no select bit: the testbit stays
def test_the_byte(wave, want):
    assert named_testbit_firstwave(wave) == want


def test_the_byte_is_nameable_silent_and_gate_clear():
    """>= $10 (siddump names it), test bit set (oscillator held, as `$09`),
    gate clear (it names a tie, never a ghost attack), and never `$FE`/`$FF`,
    which Goattracker reads as a gate command (gplay.c:355)."""
    named = 0
    for wave in range(0x100):
        fw = named_testbit_firstwave(wave)
        if wave & 0xF0 and fw != FIRSTWAVE_TESTBIT:
            named += 1
            assert fw >= 0x10 and fw & 0x08 and not fw & 0x01 and fw < 0xFE
            assert fw & 0xF0 == wave & 0xF0
            # the existing gate-off byte plus the test bit, nothing else
            assert fw == gate_off_firstwave(wave) | 0x08
        else:
            assert fw == FIRSTWAVE_TESTBIT
    assert named > 200, "the byte must name nearly every real waveform"


def test_off_by_default_changes_no_byte():
    assert _quiet(COMMANDO, named_firstwave=False) == _quiet(COMMANDO)


def test_it_is_a_gate_off_firstwave_on_every_instrument_plus_the_test_bit():
    """Against the same build with `gate_off_firstwave_instruments` over every
    instrument: same length, and the only bytes that differ are record
    firstwave bytes -- the select bits identical, the test bit added, the
    gatetimer (byte 7) untouched, which is what separates it from
    `aligned_firstwave`."""
    ref = _quiet(COMMANDO, gate_off_firstwave_instruments=tuple(
        range(1, GT_TEMPO_INSTRUMENT)))
    got = _quiet(COMMANDO, named_firstwave=True)
    assert len(ref) == len(got)
    recs = _records(ref)
    assert recs == _records(got)
    inside = {rec + 8 for rec in recs}
    assert {i for i, (a, b) in enumerate(zip(ref, got)) if a != b} <= inside
    changed = 0
    for rec in recs[1:]:                 # [0] is the Clear Voice slot
        a, b = ref[rec + 8], got[rec + 8]
        assert ref[rec + 7] == got[rec + 7]
        if a != b:
            changed += 1
            assert b == a | 0x08 and b & 0xF0 == a & 0xF0
    assert changed, "no record changed; proves nothing"
    # and it is not the default build
    assert got != _quiet(COMMANDO)


def test_aligned_firstwave_overrides_it():
    assert (_quiet(COMMANDO, aligned_firstwave=True, named_firstwave=True)
            == _quiet(COMMANDO, aligned_firstwave=True))


def test_a_real_firstwave_instrument_still_wins():
    """`real_firstwave_instruments` names one record; under the option that
    record keeps the real-waveform byte (gate ON), every other takes `$x8`."""
    plain = _quiet(COMMANDO)
    real = _quiet(COMMANDO, real_firstwave_instruments=(2,))
    named = _quiet(COMMANDO, named_firstwave=True)
    both = _quiet(COMMANDO, named_firstwave=True,
                  real_firstwave_instruments=(2,))
    recs = _records(both)
    rec2 = recs[2 - 1]
    assert real[rec2 + 8] != plain[rec2 + 8], "the control must move record 2"
    assert both[rec2 + 8] == real[rec2 + 8]
    assert both[rec2 + 8] & 0x01, "real-waveform firstwave keeps the gate ON"
    assert named[rec2 + 8] != both[rec2 + 8]
    for rec in recs[1:]:
        if rec != rec2:
            assert both[rec + 8] == named[rec + 8]


def _row(tmp_path, name: str, secs: int, **forced) -> dict:
    doc = json.loads((REPO_ROOT / "presets.json").read_text(encoding="utf-8"))
    doc["songs"][name].update(forced)
    pres = tmp_path / f"presets_{'_'.join(sorted(forced)) or 'base'}.json"
    pres.write_text(json.dumps(doc), encoding="utf-8")
    out = tmp_path / f"{name}_{'_'.join(sorted(forced)) or 'base'}.json"
    rc = fidelity.main([
        str(CORPUS / name), "-t", str(secs), "--presets", str(pres),
        "--label", "test", "--workdir",
        str(tmp_path / f"w_{name}_{'_'.join(sorted(forced)) or 'base'}"),
        "--json", str(out), "-o", str(out.with_suffix(".md"))])
    assert rc in (0, None)
    return json.loads(out.read_text(encoding="utf-8"))[0]


@needs_corpus
@needs_siddump
@needs_gt2reloc
def test_at_s2_the_firstwave_ties_are_named_and_agree(tmp_path):
    """Last_V8 (-S2): the init call's frame already carries the step, only
    unnamed. -t 60, measured at 4c9dab5 + this change (historical).
    Last_V8 itself shipped gate_off_firstwave_instruments on 2026-10-30
    (firstwave sweep), which removes these ties (tie_orig_only_firstwave
    0), so the case is read on the C128 version: the same music, -S2, and
    left without it."""
    name = "Last_V8_C128_version.sid"
    base = _row(tmp_path, name, 60)
    got = _row(tmp_path, name, 60, named_firstwave=True)
    assert base["multiplier"] == 2
    assert base["tie_orig_only_firstwave"] > 100
    assert got["tie_orig_only_firstwave"] == 0
    assert got["tie_same_frame"] > base["tie_same_frame"] + 100
    assert got["tie_agreement"] > base["tie_agreement"]
    # the naming costs no note: melody and sequence do not move
    assert got["melody"] >= base["melody"] - 1e-3
    assert got["sequence"] >= base["sequence"] - 1e-3


@needs_corpus
@needs_siddump
@needs_gt2reloc
def test_at_s1_nothing_is_carried_only_reclassified(tmp_path):
    """Mega_Apocalypse (-S1): the init call writes no pitch, so no tie can
    appear on it. `tie_orig_only_firstwave` falls to 0 only because the frame
    is no longer sub-$10; the same frames are still `tie_orig_only` and
    `tie_same_frame` is unchanged."""
    name = "Mega_Apocalypse.sid"
    # Both arms with `gate_off_firstwave_instruments` off: since v0.5.588
    # Mega's preset names 1..62, whose gate-off byte is a waveform (not
    # sub-$10) and so already reclassifies the frames this measures.
    off = dict(gate_off_firstwave_instruments=[])
    base = _row(tmp_path, name, 60, **off)
    got = _row(tmp_path, name, 60, named_firstwave=True, **off)
    assert base["multiplier"] == 1
    assert base["tie_orig_only_firstwave"] > 100
    assert got["tie_orig_only_firstwave"] == 0
    assert got["tie_same_frame"] == base["tie_same_frame"]
    assert got["tie_orig_only"] == base["tie_orig_only"]
    assert got["tie_agreement"] == base["tie_agreement"]
