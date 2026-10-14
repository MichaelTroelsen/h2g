"""A song the startup record phases takes the gate-off firstwave on every
instrument (`call_phase.GATE_OFF_FIRSTWAVE`, `convert`).

`startup_phase` puts our onsets, the call after each note's init, in the
original's frames. The init is then the PREVIOUS frame's last call whenever
the onset is a frame's first call -- one note in `m`, whatever the phase
(`call_phase.onset_mismatches`' lattice: 40 of 360 rows at -S9 for every lead)
-- and the trace samples that call. The testbit `$09` it wrote selects no
waveform, so the note before read one frame SHORT, and its gate bit opened the
gate a frame before the original's.

The property is the existing option's, named on all instruments, taken by the
songs that get the record and by no other (the 20 files that get the record, `PHASED` below samples them;
`tests/test_gate_off_firstwave_call_phase.py` is why it is wrong without the
phase).
"""
import json
import pathlib
import sys

import pytest

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[1]))

import fidelity                                              # noqa: E402
from corpus import CORPUS, needs_corpus                      # noqa: E402
from h2g import convert as convert_module                    # noqa: E402
from h2g import instrument_drop                              # noqa: E402
from h2g.convert import convert                              # noqa: E402
from h2g.goatwriter import call_phase                        # noqa: E402
from h2g.goatwriter.constants import FIRSTWAVE_TESTBIT       # noqa: E402

REPO_ROOT = pathlib.Path(__file__).resolve().parents[2]
EVERY = tuple(range(1, 64))
# Entry-gate family (test_startup_call_phase.MOVERS) and a JMP-form sample.
PHASED = ("Game_Killer.sid", "International_Karate.sid", "Kentilla.sid",
          "Proteus.sid", "Thrust.sid", "Warhawk.sid",
          "Chain_Reaction.sid", "Food_Feud.sid",
          # The JMP form with a prescaler block above its gate, and the
          # zero-page entry gate (multispeed-call-phase-one-call-earlier).
          "Go_Go_Dash.sid", "Spellbound.sid")

needs_siddump = pytest.mark.skipif(
    not pathlib.Path(fidelity.SIDDUMP).exists(),
    reason="no siddump on this machine (tools/siddump-rt, see its README)")
needs_gt2reloc = pytest.mark.skipif(
    not pathlib.Path(fidelity.GT2RELOC).exists(),
    reason="no gt2reloc on this machine")


def _doc() -> dict:
    return json.loads((REPO_ROOT / "presets.json").read_text(encoding="utf-8"))


def _build(name: str, flag: bool, **over) -> bytes:
    opts = fidelity._preset_opts(_doc(), name)
    opts.update(over)
    saved = call_phase.GATE_OFF_FIRSTWAVE
    call_phase.GATE_OFF_FIRSTWAVE = flag
    try:
        return convert(str(CORPUS / name), log=lambda m: None, **opts)
    finally:
        call_phase.GATE_OFF_FIRSTWAVE = saved


@needs_corpus
@pytest.mark.parametrize("name", PHASED)
def test_the_phase_is_the_option_on_every_instrument(name):
    """Not a new byte: the existing option, named on all of them."""
    on = _build(name, True)
    off = _build(name, False)
    by_hand = _build(name, False, gate_off_firstwave_instruments=EVERY)
    assert on == by_hand
    assert on != off and len(on) == len(off)


def _firstwaves(blob: bytes) -> list:
    """Every written instrument record's firstwave byte (offset 8 of 25)."""
    instr_at, _tables, _patt, _patterns = instrument_drop._layout(blob)
    recs = instr_at + 1
    return [blob[recs + k * instrument_drop._RECORD_LEN + 8]
            for k in range(blob[instr_at])]


@needs_corpus
def test_the_default_is_the_phase_taking_the_byte():
    """`convert` as shipped, no seam touched: the module default is on."""
    assert call_phase.GATE_OFF_FIRSTWAVE is True
    name = "Game_Killer.sid"
    opts = fidelity._preset_opts(_doc(), name)
    plain = convert(str(CORPUS / name), log=lambda m: None, **opts)
    assert plain == _build(name, True) != _build(name, False)


@needs_corpus
@pytest.mark.parametrize("name", ["Lion_Heart.sid", "Commando.sid"])
def test_a_song_without_the_startup_record_keeps_the_testbit(name):
    """Lion_Heart's default row is already exact on every row that carries a
    note (no startup row; the loss class of
    test_gate_off_firstwave_call_phase), Commando is -S1. Neither gets a
    record, so neither takes the byte: the testbit is still the firstwave of
    its records (read off the bytes, because the two builds below are equal
    by construction once the byte is applied to both)."""
    path = CORPUS / name
    if not path.exists():
        pytest.skip(f"{name} not in the corpus")
    on = _build(name, True)
    assert on == _build(name, False)
    assert FIRSTWAVE_TESTBIT in _firstwaves(on), name


@needs_corpus
def test_a_declined_startup_record_builds_the_song_as_it_was(monkeypatch):
    """The byte is right only WITH the phase. Where `add_startup_tempo`
    declines the record the default phase stays, and the song must be the one
    built without the byte -- not the one built with it."""
    name = "Game_Killer.sid"
    monkeypatch.setattr(convert_module, "add_startup_tempo",
                        lambda blob, tempo, log=None: bytes(blob))
    declined = _build(name, True)
    assert declined == _build(name, False)
    monkeypatch.undo()
    assert declined != _build(name, True)


def _short_notes(name: str, flag: bool, tmp_path: pathlib.Path):
    doc = _doc()
    mult = fidelity._preset_multiplier(doc, name)
    sng, _ = fidelity.legalise_restarts(_build(name, flag))
    packed = fidelity.pack_sid(sng, tmp_path, multiplier=mult)
    assert packed is not None and packed.exists()
    seconds = 60
    ours = fidelity.run_siddump(packed, seconds, 0, calls=mult)
    runs = fidelity.sound_note_runs(ours, seconds * 50)
    notes = [t for per in runs.values() for t in per]
    return sum(1 for held, slot, _ in notes if held < slot), len(notes)


@needs_corpus
@needs_siddump
@needs_gt2reloc
@pytest.mark.parametrize("name", ["Game_Killer.sid", "Thrust.sid"])
def test_no_note_reads_a_frame_short_under_the_phase(name, tmp_path):
    """The mechanism, measured in the trace: a note's waveform stays selected
    to the next attack. Without the byte a tenth or more of the notes lose
    their last frame to the testbit; with it, none."""
    (tmp_path / "on").mkdir()
    (tmp_path / "off").mkdir()
    short_on, n_on = _short_notes(name, True, tmp_path / "on")
    short_off, n_off = _short_notes(name, False, tmp_path / "off")
    assert n_on == n_off > 100, (n_on, n_off)
    assert short_on == 0, (name, short_on, n_on)
    assert short_off > n_off // 10, (name, short_off, n_off)
