"""The byte-code wave program: 29 of 95 files, and nothing emits it.

A listener reported Trans-Atlantic's snare missing. It is GT 3, and its program
begins `81 30` -- the interpreter writes an opcode >= $80 straight to $D404 and
the next byte to $D401, so that is literally "noise at $30xx", which is the 43
onsets the trace shows on voice 2.

Two of these files were already known (ACE II and Auf Wiedersehen Monty, as
`effect_bit80 == "program"`). The other 27 were not, which makes this the most
widespread instrument mechanism the project has found unemitted -- and the first
census of it was wrong by a factor of 29, because the signature was written from
one file's exact operands rather than from the shape.

The gating bit is deliberately not read; see the comment above WAVE_PROGRAM_FETCH.
"""
import pathlib

from corpus import CORPUS as _CORPUS, needs_corpus  # noqa: E402

from h2g.convert import _detect_tables
from h2g.detect import (WAVE_PROGRAM_HOLD, decode_wave_program,
                        find_wave_program)
from h2g.sidfile import load_sid

CORPUS = _CORPUS


def _prog(name, instr):
    sid, det = _detect_tables(load_sid(str(CORPUS / f"{name}.sid")),
                              lambda *a, **k: None)
    base = det.wave_program
    off = base + instr * det.instr_stride
    at = sid.to_offset(sid.data[off] | (sid.data[off + 1] << 8))
    return decode_wave_program(sid.data, at)


# --- the decoder, on synthetic programs ------------------------------------

def test_an_opcode_above_the_hold_is_a_waveform_and_an_absolute_pitch():
    """Both bytes go straight to the chip -- $D404 and $D401 -- so the pitch is
    the player's own and has nothing to do with the note being played."""
    assert decode_wave_program(bytes([0x81, 0x30, 0x85]), 0) == [
        ("set", 0x81, 0x30), ("hold", 0, 0)]


def test_an_opcode_below_the_hold_is_a_waveform_and_a_16_bit_step_down():
    got = decode_wave_program(bytes([0x10, 0x00, 0x02, 0x85]), 0)
    assert got == [("slide", 0x10, 0x0200), ("hold", 0, 0)]


def test_a_step_is_subtracted_so_a_large_one_slides_upward():
    """`SEC / LDA lo,X / SBC (ptr),Y` -- $FC00 taken away is $0400 added. The
    decoder reports the operand as written; reading it as unsigned "down" only
    would invert three of Trans-Atlantic's GT 13 steps."""
    got = decode_wave_program(bytes([0x50, 0x00, 0xFC, 0x85]), 0)
    assert got[0] == ("slide", 0x50, 0xFC00)
    assert (0x10000 - got[0][2]) == 0x0400


def test_the_hold_ends_the_program():
    assert WAVE_PROGRAM_HOLD == 0x85
    got = decode_wave_program(bytes([0x85, 0x81, 0x30]), 0)
    assert got == [("hold", 0, 0)]


def test_a_truncated_program_is_cut_rather_than_read_past_the_end():
    """Programs are not length-prefixed, so the only alternative to stopping is
    trusting a byte count nothing states."""
    assert decode_wave_program(bytes([0x81]), 0) == []
    assert decode_wave_program(bytes([0x10, 0x00]), 0) == []


def test_the_step_limit_is_honoured():
    assert len(decode_wave_program(bytes([0x81, 0x30] * 50), 0, limit=6)) == 6


# --- against the real players ----------------------------------------------

@needs_corpus
def test_the_interpreter_is_found_across_the_corpus():
    """29 files, and the first census said one. The signature that found one was
    written from Trans-Atlantic's exact operands; this one is written from the
    fetch-and-hold shape, which is what the players actually share.

    All 29 yield a pointer array. Only 27 also yield a plausible gating bit,
    which is why the gate is not part of the reading at all -- see the comment
    above WAVE_PROGRAM_FETCH."""
    sids = sorted(CORPUS.glob("*.sid"))
    if not sids:
        return
    found = 0
    for path in sids:
        try:
            sid = load_sid(str(path))
        except Exception:                              # noqa: BLE001
            continue
        if find_wave_program(sid) >= 0:
            found += 1
    assert found == 29, f"{found} -- the interpreter's reach changed"


@needs_corpus
def test_the_missing_snare_decodes_to_noise_at_a_fixed_pitch():
    if not CORPUS.is_dir():
        return
    steps = _prog("Trans-Atlantic_Balloon_Challenge", 2)
    assert steps[0] == ("set", 0x81, 0x30), steps[:3]
    # ...then two slides under a released waveform, then more noise pitches
    assert [s[0] for s in steps[:6]] == [
        "set", "slide", "slide", "set", "set", "set"], steps[:6]


@needs_corpus
def test_every_located_program_decodes_to_something():
    """A pointer array that resolves but decodes to nothing would mean the
    array was misidentified."""
    if not CORPUS.is_dir():
        return
    checked = 0
    for path in sorted(CORPUS.glob("*.sid")):
        try:
            sid, det = _detect_tables(load_sid(str(path)), lambda *a, **k: None)
        except Exception:                              # noqa: BLE001
            continue
        if det.wave_program < 0 or det.instr_used <= 0:
            continue
        nonempty = 0
        for i in range(det.instr_used):
            off = det.wave_program + i * det.instr_stride
            if off + 1 >= len(sid.data):
                break
            at = sid.to_offset(sid.data[off] | (sid.data[off + 1] << 8))
            if at >= 0 and decode_wave_program(sid.data, at, 4):
                nonempty += 1
        assert nonempty, path.name
        checked += 1
    assert checked >= 20, checked


def test_nothing_emits_it_yet():
    """The gating bit is unresolved -- which instruments run a program is not
    known -- so emitting would invent one for every record carrying whichever
    bit was guessed. Same discipline as the two-stage attack before v0.5.179."""
    import h2g.goatwriter as gw
    src = pathlib.Path(gw.__file__).read_text(encoding="utf-8")
    assert "wave_program" not in src
    assert "decode_wave_program" not in src
