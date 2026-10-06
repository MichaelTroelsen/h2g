"""A counter-gated record's plain program gives its re-pitching steps back.

Every plain instrument's wavetable program is `[wave/00, tail/00, tail/00,
FF/00]`, and each `/00` step writes the note's frequency and skips the
continuous effects (player.s `bne mt_wavefreq` past `mt_wavedone`; gplay.c
`goto PULSEEXEC`), so the instrument vibrato cannot start before call 4,
frame 3 after the attack, whatever `vibdelay` says. Mega_Apocalypse records
12 and 15 (stored gate 0, read as 1) move at age 1-2 in the original and
moved at 3 on every note here. `_free_gate_calls` respells the later steps
`/80` where the gate's call is one the program withholds -- for a record
the swell pass commands, only inside the note's own row.
"""
import json
import pathlib
import sys

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[1]))

from corpus import CORPUS, needs_corpus  # noqa: E402
from h2g.detect import Detection, VibratoGate  # noqa: E402
from h2g.goatwriter.vibrato import (_effect_call_list,  # noqa: E402
                                    _free_gate_calls, _gate_start_call,
                                    _step_calls)

PYTHON_ROOT = pathlib.Path(__file__).resolve().parents[1]

PLAIN = [(0x41, 0x00), (0x41, 0x00), (0x41, 0x00), (0xFF, 0x00),
         (0xFF, 0x00)]


def _det(gate, form="counter"):
    return Detection(vibrato_gate=VibratoGate(form, gate, gate or 0, 0xBC))


def _free(entries, gate, form="counter", vib=None, row_calls=0,
          swelling=()):
    vib_ptrs = {0: (1, 1)} if vib is None else vib
    return _free_gate_calls(_det(gate, form), vib_ptrs, entries, [(0, 1)],
                            1, row_calls, lead=1, swelling=swelling)


def test_a_withheld_gate_frees_every_step_after_the_first():
    out, freed = _free(PLAIN, 1)                 # target call 2
    assert freed == [0]
    # The first step still sets the note's pitch; the stop is untouched.
    assert out == [(0x41, 0x00), (0x41, 0x80), (0x41, 0x80), (0xFF, 0x00),
                   (0xFF, 0x00)]
    assert _effect_call_list(PLAIN, 1, 8) == [4, 5, 6, 7]
    assert _effect_call_list(out, 1, 8) == [2, 3, 4, 5, 6, 7]
    assert _gate_start_call(_effect_call_list(out, 1, 0x100), 2) == 2
    # The input list is not edited in place.
    assert PLAIN[1] == (0x41, 0x00)


def test_a_gate_already_past_the_program_keeps_its_bytes():
    # Mega_Apocalypse records 3 and 10: gates 6 and 12, targets 7 and 13,
    # both effect calls of the plain program already.
    for gate in (3, 6, 12):
        assert _free(PLAIN, gate) == (PLAIN, []), gate


def test_a_tick0_withheld_target_is_freed_only_if_it_gets_nearer():
    # Gate 2 -> target 3. With 3-call rows call 3 is a tick 0 either way,
    # but freeing makes call 2 an effect call: one early beats one late
    # only strictly, and 4 - 3 == 3 - 2 is a tie, which goes late.
    assert _free(PLAIN, 2, row_calls=3) == (PLAIN, [])
    out, freed = _free(PLAIN, 2)
    assert freed == [0] and _effect_call_list(out, 1, 6)[:2] == [2, 3]


def test_only_the_plain_shape_is_touched():
    # A program that changes waveform is a two-stage or byte-code program
    # (ACE_II record 9 `41/00 01/80 43/00 07/80 41/00`), not a re-pitch.
    two = [(0x41, 0x00), (0x81, 0x00), (0x41, 0x00), (0xFF, 0x00)]
    assert _free(two, 1) == (two, [])
    # A loop is not a stop.
    loop = [(0x41, 0x00), (0x41, 0x00), (0x41, 0x00), (0xFF, 0x01)]
    assert _free(loop, 1) == (loop, [])
    # A step carrying a note of its own.
    note = [(0x41, 0x00), (0x41, 0x0C), (0x41, 0x00), (0xFF, 0x00)]
    assert _free(note, 1) == (note, [])
    # A gate-bit change alone is still one waveform: the gate-timer programs.
    gated = [(0x11, 0x00)] * 5 + [(0x10, 0x00), (0xFF, 0x00)]
    out, freed = _free(gated, 1)
    assert freed == [0] and out[0] == (0x11, 0x00)
    assert all(r == 0x80 for _, r in out[1:6])


def test_a_swelling_record_keeps_the_hold_rows_reset():
    """A `4xy` does not reset the oscillator's phase, so the step on the
    first hold row's call stays a re-pitch for a record the swell pass
    commands: only the steps inside the note's own row are freed."""
    out, freed = _free(PLAIN, 1, row_calls=3, swelling={0})
    assert freed == [0]
    assert out[:3] == [(0x41, 0x00), (0x41, 0x80), (0x41, 0x00)]
    # Entry 2 is read on call 3, the hold row's first call; the stop
    # after it is followed on that same call, as gplay.c:709-712 does.
    assert _step_calls(PLAIN, 1, 8) == {0: 1, 1: 2, 2: 3}
    # Rows of 4 calls put entry 2 inside the note's row, and as the
    # program's last step it is still the latest reset there is: kept.
    out, _ = _free(PLAIN, 1, row_calls=4, swelling={0})
    assert [r for _, r in out[:3]] == [0x00, 0x80, 0x00]
    # A longer program frees what lies between its first and last steps
    # inside the note's row, and keeps what is on or past the hold row.
    long = [(0x41, 0x00)] * 6 + [(0xFF, 0x00)]
    out, _ = _free(long, 1, row_calls=4, swelling={0})
    assert [r for _, r in out[:6]] == [0x00, 0x80, 0x80, 0x00, 0x00, 0x00]
    # A record the pass does not command is freed all the way.
    out, _ = _free(PLAIN, 1, row_calls=3, swelling={7})
    assert [r for _, r in out[:3]] == [0x00, 0x80, 0x80]
    # A delay step is read on its LAST call.
    held = [(0x41, 0x00), (0x01, 0x00), (0x41, 0x00), (0xFF, 0x00)]
    assert _step_calls(held, 1, 8) == {0: 1, 1: 3, 2: 4}


def test_no_counter_gate_or_no_vibrato_frees_nothing():
    for form in ("duration", "unread"):
        assert _free(PLAIN, 1, form=form) == (PLAIN, []), form
    assert _free(PLAIN, 1, vib={}) == (PLAIN, [])
    assert _free(PLAIN, 1, vib={0: (0, 1)}) == (PLAIN, [])
    assert _free_gate_calls(Detection(), {0: (1, 1)}, PLAIN, [(0, 1)], 1,
                            0) == (PLAIN, [])


def _mega_tables():
    """(det, entries, starts, lead, refined vib_ptrs) as build_sng hands them
    to `_classic_gate_refine` for Mega_Apocalypse under its preset."""
    import fidelity
    import h2g.goatwriter.build as B
    from h2g.convert import convert
    doc = json.loads((PYTHON_ROOT.parent / "presets.json").read_text())
    opts = fidelity._preset_opts(doc, "Mega_Apocalypse.sid")
    got = {}
    real = B._classic_gate_refine

    def spy(det, vib_ptrs, entries, starts, multiplier, row_calls,
            instr_row_calls=None, lead=1, *a, **k):
        out = real(det, vib_ptrs, entries, starts, multiplier, row_calls,
                   instr_row_calls, lead, *a, **k)
        got.update(det=det, entries=list(entries), starts=list(starts),
                   lead=lead, mult=multiplier, row_calls=row_calls,
                   irc=dict(instr_row_calls or {}), vib=dict(out))
        return out

    B._classic_gate_refine = spy
    try:
        convert(str(CORPUS / "Mega_Apocalypse.sid"), lambda m: None, **opts)
    finally:
        B._classic_gate_refine = real
    assert got, "build_sng never refined Mega_Apocalypse's gates"
    return got


def _block(got, rec):
    p = got["starts"][rec + got["lead"]]
    out = []
    while got["entries"][p - 1][0] != 0xFF:
        out.append(got["entries"][p - 1])
        p += 1
    return out


@needs_corpus
def test_mega_apocalypse_records_12_and_15_start_on_call_2():
    got = _mega_tables()
    det, lead = got["det"], got["lead"]
    assert got["mult"] == 1
    for rec in (12, 15):
        assert det.vibrato_gate.gate_for(rec) == 0, rec
        blk = _block(got, rec)
        assert len(blk) == 3, (rec, blk)
        # Freed on call 2; call 3 opens the first hold row the swell pass
        # commands, and its re-pitch is the oscillator's reset.
        assert got["row_calls"] == 3
        assert [r for _, r in blk] == [0x00, 0x80, 0x00], (rec, blk)
        idx, delay = got["vib"][rec]
        assert idx and delay == 1, (rec, got["vib"][rec])
        own = got["irc"].get(rec + lead + 1, got["row_calls"])
        calls = _effect_call_list(got["entries"], got["starts"][rec + lead],
                                  0x100, own)
        # vibdelay 1 runs the oscillator on the first effect call: call 2,
        # the frame after the attack siddump names (the init call writes
        # the test-bit firstwave), where the original moves at age 1.
        assert calls[delay - 1] == 2, (rec, calls[:6])
    for rec in (3, 10):
        assert det.vibrato_gate.gate_for(rec) in (6, 12)
        assert [r for _, r in _block(got, rec)] == [0x00, 0x00, 0x00], rec
