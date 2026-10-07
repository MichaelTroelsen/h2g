"""A vibrating record's slides reach the chip at -S1, as a portamento chain.

Opened as nemesis-counter-gate-age-1-move: Nemesis_the_Warlock `$0B09`,
`$0C0A` and `$0C5A` move at frame 1 in the original although the vibrato's
counter gate reads 3, and moved at frame 4 here. The move is the wave
program, not the vibrato: `$E32E-$E341` subtracts each slide's operand from
the frequency cell `$E3F0` writes, one opcode a frame from age 1, and from
the gate on the vibrato re-stores its absolute pitch into that cell first
(`$E261 CMP #$03 / BCC`, `$E280/$E285`), so a later slide is a one-frame dip
below it. Traced: `0 -32 -368 vib-384 vib` (records 3/11) and `0 -3104
-3808 vib-496 vib-512 vib-768 vib` (record 12); IK_plus record 13 (gate 4)
`0 +896 +1536 +1152 vib-896 vib`. `_gated_slide_chain` emits the change
between those offsets as one wavetable command a call.
"""
import pathlib
import sys

import pytest

PYTHON_ROOT = pathlib.Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PYTHON_ROOT))

from corpus import CORPUS, needs_corpus  # noqa: E402

PORTAUP, PORTADOWN, JUMP = 0xF1, 0xF2, 0xFF


def _tables(name):
    from h2g.convert import _detect_tables
    from h2g.sidfile import load_sid
    return _detect_tables(load_sid(str(CORPUS / f"{name}.sid")),
                          lambda *a, **k: None)


def _entries(name, i, multiplier=1, budget=60, det_edit=None):
    from h2g.goatwriter.wave_program import _wave_program_entries
    sid, det = _tables(name)
    if det_edit:
        det_edit(det)
    speed: list = []
    got = _wave_program_entries(sid, det, i, speed, "gts5", multiplier,
                                budget)
    assert got is not None, (name, i)
    return list(got[0]), list(got[1]), speed


def _offsets(left, right, speed):
    """The frequency offset from the note after each entry, as gplay.c's
    CMD_PORTAUP/DOWN step it; a right side `$00` writes the note."""
    out, f = [], 0
    for l, r in zip(left, right):
        if l == JUMP:
            break
        if l in (PORTAUP, PORTADOWN):
            hi, lo = speed[r - 1]
            f += (hi << 8 | lo) * (1 if l == PORTAUP else -1)
        elif r == 0x00:
            f = 0
        out.append(f)
    return out


@needs_corpus
@pytest.mark.parametrize("i", [3, 11])
def test_nemesis_records_3_and_11_carry_their_slides(i):
    left, right, speed = _entries("Nemesis_the_Warlock", i)
    assert left == [0x41, PORTADOWN, PORTADOWN, PORTADOWN, 0x40, JUMP], \
        [hex(x) for x in left]
    # lead, ages 1-3, restore: the original's `0 -32 -368 vib-384 vib`
    assert _offsets(left, right, speed) == [0, -32, -368, -384, 0]


@needs_corpus
def test_nemesis_record_12_resets_to_the_vibrato_from_the_gate():
    left, right, speed = _entries("Nemesis_the_Warlock", 12)
    assert left == [0x11, PORTADOWN, PORTADOWN, PORTAUP, PORTADOWN,
                    PORTADOWN, 0x10, JUMP], [hex(x) for x in left]
    # Below the gate (ages 1-2) the slides accumulate; from age 3 each is
    # its own operand below the note -- not -4304, -4816, -5584.
    assert _offsets(left, right, speed) == [0, -3104, -3808, -496, -512,
                                            -768, 0]


@needs_corpus
def test_ik_record_13_gate_4_rises_then_dips():
    left, right, speed = _entries("IK_plus", 13)
    assert _offsets(left, right, speed) == [0, 896, 1536, 1152, -896, 0]
    assert left[-2:] == [0x10, JUMP]


@needs_corpus
def test_the_chain_declines_what_it_does_not_model():
    from h2g.goatwriter.wave_program import _gated_slide_chain
    from h2g.detect import decode_wave_program

    def chain(name, i, multiplier=1, det_edit=None):
        sid, det = _tables(name)
        if det_edit:
            det_edit(det)
        off = det.wave_program + i * det.instr_stride
        at = sid.to_offset(sid.data[off] | sid.data[off + 1] << 8)
        return _gated_slide_chain(sid, det, i, decode_wave_program(
            sid.data, at), [0x41], [0x00], [], multiplier, 60)

    assert chain("Nemesis_the_Warlock", 11) is not None
    # above -S1 the pairing path carries the travel already
    assert chain("Nemesis_the_Warlock", 11, multiplier=2) is None
    # a program with a `set` opcode (record 1) is not a chain
    assert chain("Nemesis_the_Warlock", 1) is None
    # a record the player does not vibrate (Mega record 2): the hold
    # keeps the accumulator, `_wave_program_hold_travels`' case
    assert chain("Mega_Apocalypse", 2) is None

    def late_gate(det):
        from h2g.detect import VibratoGate
        vg = det.vibrato_gate
        det.vibrato_gate = VibratoGate("counter", 9, 9, vg.cell)

    # a gate past the hold would leave the bare accumulator sounding
    assert chain("Nemesis_the_Warlock", 11, det_edit=late_gate) is None

    def no_gate(det):
        det.vibrato_gate = None

    assert chain("Nemesis_the_Warlock", 11, det_edit=no_gate) is None


@needs_corpus
def test_a_short_budget_falls_back_rather_than_overrunning():
    from h2g.goatwriter.wave_program import _wave_program_entries
    sid, det = _tables("Nemesis_the_Warlock")
    for budget in range(4, 20):
        got = _wave_program_entries(sid, det, 12, [], "gts5", 1, budget)
        if got is not None:
            assert len(got[0]) <= budget, (budget, len(got[0]))


@needs_corpus
@pytest.mark.skipif(not pathlib.Path(
    __import__("fidelity").SIDDUMP).exists(), reason="no siddump")
def test_nemesis_0b09_moves_on_frame_1(tmp_path):
    """siddump of the packed conversion under presets, 60 s: every `$0B09`
    note reads `-32 -368 -384` on frames 1-3, the original's frames."""
    import json
    import fidelity
    from h2g.convert import convert
    doc = json.loads((PYTHON_ROOT.parent / "presets.json").read_text())
    name = "Nemesis_the_Warlock.sid"
    sng = convert(str(CORPUS / name), lambda m: None,
                  **fidelity._preset_opts(doc, name))
    sng, _ = fidelity.legalise_restarts(bytes(sng))
    packed = fidelity.pack_sid(sng, tmp_path, fidelity.GT2RELOC, 1)
    assert packed is not None
    trace = fidelity.run_siddump(packed, 60, 0, fidelity.SIDDUMP, calls=1)
    nf = 60 * 50
    notes = 0
    for v in trace:
        fq = fidelity.register_timeline(v.freq_events, nf)
        ad = fidelity.register_timeline(v.adsr_events, nf)
        atk = sorted(v.attack_frames)
        for j, f0 in enumerate(atk):
            end = atk[j + 1] if j + 1 < len(atk) else nf
            if ad[min(f0 + 1, nf - 1)] != 0x0B09 or end - f0 < 5:
                continue
            notes += 1
            got = [fq[f0 + k] - fq[f0] for k in range(1, 5)]
            assert got == [-32, -368, -384, 0], (f0, got)
    assert notes >= 5, notes
