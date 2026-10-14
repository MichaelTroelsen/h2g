"""The zero-page entry gate (Spellbound `$C2`), read by
`call_phase.zp_entry_gate` since multispeed-call-phase-one-call-earlier.

    E012  DEC $C2 / BPL $E01B / LDA #$0A / STA $C2 / RTS         ; the play entry

is `entry_gate`'s clock -- every call passes the gate, which does nothing at
all on the underflow call -- with its counter in zero page. A zero-page cell
has no byte in the image, so `nibble_gate_byte` (which the arpeggio and vibrato
code take as read) reads None for it and `entry_gate` stays False; that is
deliberate and pinned here. `startup_phase` alone reads it, as a cell that
starts at 0 (siddump's RAM) because the gate's own `STA` and `DEC` are the only
accesses to it in the file.

What it buys (60 s, presets, C:/t/multispeed-call-phase-one-call-earlier/
out2): Spellbound's onset window {1..5} -> {-1..3} (all five phases of -S5,
Thrust's class), `onset_timing` .5994 -> 1.0000, tie_agreement .6738 -> .9747,
wave .9491 -> .9842, gate .5874 -> .6307, melody and sequence to 1.0000.
Samantha_Fox is the same gate but reads no first fetch of the speed counter,
so it gets no clock.
"""
import dataclasses
import json
import pathlib
import sys

import pytest

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[1]))

import fidelity                                              # noqa: E402
from corpus import CORPUS, needs_corpus                      # noqa: E402
from h2g.convert import _detect_tables, convert              # noqa: E402
from h2g.goatwriter import arpeggio, call_phase, tempo       # noqa: E402
from h2g.sidfile import load_sid                             # noqa: E402

REPO_ROOT = pathlib.Path(__file__).resolve().parents[2]

needs_siddump = pytest.mark.skipif(
    not pathlib.Path(fidelity.SIDDUMP).exists(),
    reason="no siddump on this machine (tools/siddump-rt, see its README)")
needs_gt2reloc = pytest.mark.skipif(
    not pathlib.Path(fidelity.GT2RELOC).exists(),
    reason="no gt2reloc on this machine")


def _presets() -> dict:
    return json.loads((REPO_ROOT / "presets.json").read_text(encoding="utf-8"))


def _read(name):
    sid = load_sid(str(CORPUS / name))
    sid, det = _detect_tables(sid, lambda *_: None)
    speeds = tempo.find_song_speeds(sid, det)
    m = tempo.file_multiplier(sid, speeds, True)
    tempos = [tempo.tempo_command_value(sid, s, speeds, m, True)
              for s in range(max(sid.subtunes, 1))]
    return sid, det, m, tempos


def _cell(sid) -> int:
    at = tempo.play_entry(sid)
    return call_phase.OUTER_GATE_RTS_ZP.match(sid.data, at).group(1)[0]


def _with_tail(name, tail: bytes):
    sid = load_sid(str(CORPUS / name))
    return dataclasses.replace(sid, data=sid.data + tail)


@needs_corpus
def test_the_reading_is_for_the_zero_page_gate_at_the_play_entry():
    reached = []
    for path in sorted(CORPUS.glob("*.sid")):
        sid = load_sid(str(path))
        if call_phase.zp_entry_gate(sid):
            reached.append(path.name)
    assert reached == ["Samantha_Fox_Strip_Poker.sid", "Spellbound.sid"]


@needs_corpus
@pytest.mark.parametrize("name", ["Spellbound.sid", "Samantha_Fox_Strip_Poker.sid"])
def test_it_is_not_entry_gate_and_the_cell_has_no_byte_for_the_other_readers(name):
    """Widening `entry_gate` or `nibble_gate_byte` to zero page would move the
    vibrato and arpeggio code of these files; this reading is `startup_phase`'s
    alone."""
    sid = load_sid(str(CORPUS / name))
    assert not call_phase.entry_gate(sid)
    assert not call_phase.jmp_gate(sid)
    assert arpeggio.nibble_gate_byte(sid) is None


@needs_corpus
@pytest.mark.parametrize("name", ["Game_Killer.sid", "Thrust.sid", "Chain_Reaction.sid",
                                  "Commando.sid", "Las_Vegas_Video_Poker.sid"])
def test_no_other_gate_form_is_read_as_this_one(name):
    assert not call_phase.zp_entry_gate(load_sid(str(CORPUS / name)))


@needs_corpus
@pytest.mark.parametrize("tail", [
    lambda cell: bytes([0x85, cell]),           # a second STA zp to the cell
    lambda cell: bytes([0x8D, cell, 0]),        # STA abs to the same address
    lambda cell: bytes([0xC6, cell]),           # a second DEC zp
    lambda cell: bytes([0x84, cell]),           # STY zp
], ids=["sta-zp", "sta-abs", "dec-zp", "sty-zp"])
def test_any_other_access_to_the_cell_declines(tail):
    name = "Spellbound.sid"
    sid = load_sid(str(CORPUS / name))
    assert call_phase.zp_entry_gate(sid)
    assert not call_phase.zp_entry_gate(_with_tail(name, tail(_cell(sid))))


@needs_corpus
def test_spellbound_takes_a_shorter_startup_row_and_samantha_fox_none():
    sid, det, m, tempos = _read("Spellbound.sid")
    assert (m, tempos[0]) == (5, 11)             # 11 * 10 == 2 * 11 * 5 : exact
    phase = call_phase.startup_phase(sid, det, m, tempos)
    assert phase is not None
    assert (phase.tempo, phase.default) == (28, 30)
    assert phase.mismatched == 0 and phase.default_mismatched == 88
    assert phase.rows == 220
    # Samantha_Fox: the gate is read, the speed counter's first fetch is not.
    sid, det, m, tempos = _read("Samantha_Fox_Strip_Poker.sid")
    assert arpeggio.fixed_arp_first_fetch(sid, det) is None
    assert call_phase.startup_phase(sid, det, m, tempos) is None


@needs_corpus
def test_the_record_and_the_gate_off_byte_reach_the_converted_song():
    import songview
    from h2g.goatwriter.constants import FIRSTWAVE_TESTBIT
    name = "Spellbound.sid"
    opts = fidelity._preset_opts(_presets(), name)
    blob = convert(str(CORPUS / name), log=lambda m: None, **opts)
    song = songview.parse_sng(blob)
    last = song.instruments[-1]
    assert last.name == "Startup tempo" and last.ad == 28
    # `GATE_OFF_FIRSTWAVE`: no instrument keeps the testbit as its firstwave.
    saved = call_phase.GATE_OFF_FIRSTWAVE
    call_phase.GATE_OFF_FIRSTWAVE = False
    try:
        plain = convert(str(CORPUS / name), log=lambda m: None, **opts)
    finally:
        call_phase.GATE_OFF_FIRSTWAVE = saved
    assert plain != blob and len(plain) == len(blob)
    assert FIRSTWAVE_TESTBIT != 0


@needs_corpus
@needs_siddump
@needs_gt2reloc
def test_every_onset_lands_on_one_of_the_originals_frames_through_the_packed_file(
        tmp_path, monkeypatch):
    """469 of 469 of our attacks at 60 s, .6034 without the startup row."""
    from h2g import convert as convert_module
    name = "Spellbound.sid"
    doc = _presets()
    m = doc["songs"][name]["multiplier"]
    shares = {}
    for phased in (False, True):
        if not phased:
            monkeypatch.setattr(convert_module, "startup_phase",
                                lambda *a, **k: None)
        sng = convert(str(CORPUS / name), log=lambda x: None,
                      **fidelity._preset_opts(doc, name))
        monkeypatch.undo()
        work = tmp_path / str(phased)
        work.mkdir()
        packed = fidelity.pack_sid(sng, work, fidelity.GT2RELOC, m)
        assert packed is not None and packed.exists()
        orig = fidelity.run_siddump(CORPUS / name, 60, 0, calls=1)
        ours = fidelity.run_siddump(packed, 60, 0, calls=m)
        lag, _raw = fidelity.startup_lag(orig, ours)
        total = hit = 0
        for a, b in zip(orig, ours):
            frames = set(a.attack_frames)
            for x in b.attack_frames:
                total += 1
                hit += (x - lag) in frames
        assert total > 400
        shares[phased] = hit / total
    assert shares[False] < 0.7 and shares[True] == 1.0, shares
