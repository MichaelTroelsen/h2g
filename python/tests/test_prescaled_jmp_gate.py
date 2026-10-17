"""The JMP-form outer gate with a prescaler block above it (Go_Go_Dash,
Lion_Heart), read by `call_phase.jmp_gate` since multispeed-call-phase-one-
call-earlier.

Chain_Reaction's spelling puts `LDA cell / BEQ / LDA ctr / CMP reload / BNE`
right after the gate's landing and the new-song `BVC` on the `LDX` just above
the gate. Go_Go_Dash's player is the same clock with two differences:

    107E  LDX $1AA9                      ; the BVC of 1029 lands here
    1081  LDA #0 / STA $1019             ; clear the prescaler's flag cell
    1086  LDA $3E36 / BEQ $109A          ; a data byte, 0: skip the prescaler
    108B  DEC $1018 / BPL $109A / LDA #4 / STA $1018 / STA $1019 / BNE $10B2
    109A  DEC $1AA8 / BPL .. / LDA #O / STA $1AA8 / JMP $10B2     ; the gate
    10A7  DEC $1AA6 ...                                            ; speed counter
    10B2  per-voice work ...
    10E9  LDA $1AA8 / BEQ $1101 / LDA $1AA6 / CMP $1AA7 / BNE $1101  ; the fetch

so the fetch test sits 79 bytes on, past the per-voice duration counters, and a
prescaler block that `$3E36` = 0 switches off lies between the `LDX` and the
gate. Lion_Heart is the same engine. Neither was read before: `jmp_gate` was
False for both, `startup_phase` returned None, and the song ran on gt2reloc's
own startup row.

What the reading buys (60 s, presets, 4 arms in
C:/t/multispeed-call-phase-one-call-earlier/out2): Go_Go_Dash's onset window
{1, 3} -> {0, 2}, `onset_timing` .5552 -> 1.0000, wave .7229 -> .8369. Lion_Heart
is read but takes no record: every row that carries a note is already on the
original's frames at the default row (`best_startup` keeps the default).
"""
import dataclasses
import pathlib
import sys

import pytest

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[1]))

import fidelity                                              # noqa: E402
from corpus import CORPUS, needs_corpus                      # noqa: E402
from h2g.convert import _detect_tables, convert              # noqa: E402
from h2g.goatwriter import call_phase, tempo                 # noqa: E402
from h2g.sidfile import load_sid                             # noqa: E402

REPO_ROOT = pathlib.Path(__file__).resolve().parents[2]
PRESCALED = ("Go_Go_Dash.sid", "Lion_Heart.sid")

needs_siddump = pytest.mark.skipif(
    not pathlib.Path(fidelity.SIDDUMP).exists(),
    reason="no siddump on this machine (tools/siddump-rt, see its README)")
needs_gt2reloc = pytest.mark.skipif(
    not pathlib.Path(fidelity.GT2RELOC).exists(),
    reason="no gt2reloc on this machine")


def _presets() -> dict:
    import json
    return json.loads((REPO_ROOT / "presets.json").read_text(encoding="utf-8"))


def _patched(name: str, edit):
    sid = load_sid(str(CORPUS / name))
    data = bytearray(sid.data)
    edit(sid, data)
    return dataclasses.replace(sid, data=bytes(data))


def _block(sid):
    gate = call_phase.OUTER_GATE.search(sid.data)
    blk = call_phase._JMP_GATE_PRESCALER.match(sid.data, gate.start() - 25)
    assert blk is not None
    return gate, blk


@needs_corpus
@pytest.mark.parametrize("name", PRESCALED)
def test_both_are_the_jmp_gate_with_a_prescaler_block(name):
    sid = load_sid(str(CORPUS / name))
    assert call_phase.jmp_gate(sid)
    assert not call_phase.entry_gate(sid)
    gate, blk = _block(sid)
    # The block is the whole of what lies between the LDX and the gate.
    assert len(blk.group(0)) == 25
    assert sid.data[gate.start() - 25 - 3] == 0xAE           # LDX abs
    assert not call_phase._new_song_test(sid.data, gate.start())


@needs_corpus
@pytest.mark.parametrize("name", PRESCALED)
def test_a_prescaler_the_file_can_switch_on_is_not_this_clock(name):
    """The block is skipped, and the gate's clock is Chain_Reaction's, only
    while its flag byte reads 0."""
    def on(sid, data):
        _gate, blk = _block(sid)
        data[sid.to_offset(blk.group(2)[0] | blk.group(2)[1] << 8)] = 1
    assert not call_phase.jmp_gate(_patched(name, on))


@needs_corpus
@pytest.mark.parametrize("name", PRESCALED)
def test_a_store_to_the_prescaler_flag_anywhere_in_the_file_declines(name):
    def store(sid, data):
        _gate, blk = _block(sid)
        data += b"\x8d" + blk.group(2)          # STA flag, past the image's code
    assert not call_phase.jmp_gate(_patched(name, store))


@needs_corpus
@pytest.mark.parametrize("name", PRESCALED)
def test_the_prescaler_must_leave_onto_the_gates_own_landing(name):
    """Its `BNE` is the only way out of the block other than the gate: if it
    lands anywhere but the `JMP`'s target the counters are not skipped as the
    clock says."""
    def moved(sid, data):
        gate, _blk = _block(sid)
        data[gate.start() - 1] += 1             # the BNE's displacement
    assert not call_phase.jmp_gate(_patched(name, moved))


@needs_corpus
@pytest.mark.parametrize("name", PRESCALED)
def test_the_far_fetch_test_must_name_the_gates_own_cells(name):
    """The `LDA cell / BEQ / LDA ctr / CMP reload / BNE` further on is the
    fetch only if it reads the gate's cell, its counter and the counter's
    reload."""
    def other_cell(sid, data):
        gate, _blk = _block(sid)
        fetch = next(call_phase._JMP_GATE_FETCH.finditer(
            sid.data, gate.start(), gate.start() + 200))
        data[fetch.start() + 1] ^= 0x01         # LDA cell: another cell
    assert not call_phase.jmp_gate(_patched(name, other_cell))


def _tempos(name):
    sid = load_sid(str(CORPUS / name))
    sid, det = _detect_tables(sid, lambda *_: None)
    speeds = tempo.find_song_speeds(sid, det)
    m = tempo.file_multiplier(sid, speeds, True)
    tempos = [tempo.tempo_command_value(sid, s, speeds, m, True)
              for s in range(max(sid.subtunes, 1))]
    return sid, det, m, tempos


@needs_corpus
def test_go_go_dash_rows_are_exact_and_it_takes_a_shorter_startup_row():
    sid, det, m, tempos = _tempos("Go_Go_Dash.sid")
    assert (m, tempos[0]) == (4, 15)             # 15 * 4 == 3 * 5 * 4 : exact
    phase = call_phase.startup_phase(sid, det, m, tempos)
    assert phase is not None
    assert (phase.tempo, phase.default) == (23, 24)
    assert phase.mismatched == 0 and phase.default_mismatched == 20
    assert phase.rows == 80


@needs_corpus
def test_lion_heart_is_read_and_keeps_the_default_row():
    sid, det, m, tempos = _tempos("Lion_Heart.sid")
    assert call_phase.jmp_gate(sid)
    # Scored over every row a lead below the default is as good (17 and 14);
    # over the 16 rows that carry a note the default is exact already.
    assert call_phase.startup_phase(sid, det, m, tempos) is not None
    from h2g.instrument_drop import onset_rows
    sng = convert(str(CORPUS / "Lion_Heart.sid"), log=lambda x: None,
                  **fidelity._preset_opts(_presets(), "Lion_Heart.sid"))
    rows = onset_rows(sng, 0, call_phase.startup_horizon(m, 3))
    assert rows is not None and len(rows) == 16
    assert call_phase.startup_phase(sid, det, m, tempos,
                                    lambda s, h: rows) is None


def _share_on_an_original_attack_frame(name, tmp_path, monkeypatch, phased):
    """Of our attacks, the share that fall (after the harness's lag) on a
    frame the original attacks on, over 60 s and all three voices."""
    from h2g import convert as convert_module
    if not phased:
        monkeypatch.setattr(convert_module, "startup_phase",
                            lambda *a, **k: None)
    doc = _presets()
    m = doc["songs"][name]["multiplier"]
    sng = convert(str(CORPUS / name), log=lambda x: None,
                  **fidelity._preset_opts(doc, name))
    monkeypatch.undo()
    work = tmp_path / ("on" if phased else "off")
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
    assert total > 500
    return hit / total


@needs_corpus
@needs_siddump
@needs_gt2reloc
def test_go_go_dash_onsets_land_on_the_originals_frames_through_the_packed_file(
        tmp_path, monkeypatch):
    """.525 without the startup row, .936 with it (902 of 964 at 60 s; what
    remains are attacks the sequence does not share with the original, not a
    phase). Historical, before the ILV tie was emitted (test_ilv_tie.py),
    which removes the surplus: .558 without, .994 with at v0.5.579+."""
    off = _share_on_an_original_attack_frame(
        "Go_Go_Dash.sid", tmp_path, monkeypatch, False)
    on = _share_on_an_original_attack_frame(
        "Go_Go_Dash.sid", tmp_path, monkeypatch, True)
    assert off < 0.6 and on > 0.92, (off, on)
