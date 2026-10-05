"""A flagged note that re-attacks skips the two-stage attack and the pulse
reset: `goatwriter.note_passes.free_note_variants`.

In the legato-marker players (`note_flag`, `legato_tie_family`) a note byte
with bit 7 set jumps over the instrument start: Auf_Wiedersehen_Monty `$E569
LDA $EB2D / BMI $E5A3` skips the pulse write, the envelope write, the sweep
clear and the reload of the drum counter `$EB72` from `$EE0B,X`. The note
still re-gates (`$E5A3` stores the waveform), but the counter is left at 0
and no noise frame plays. Such a row (no `CMD_TONEPORTA`: a tie landing is
already legato) is respelled on a variant of its record whose wavetable
starts on the second stage and whose pulse pointer is 0.

Measured on Monty sub 0, 60 s, presets, gt2reloc + siddump-rt
(C:/t/monty-bit7-note-skips-drum-and-pulse/r2/ticks.py, check_bit7.py):
voice-3 noise frames 269 -> 239 (original 240); on the 30 flagged notes the
original never ticks and ours ticked on 30, now 0; the PW sweep carries on
through the flagged note (2F0 -> 320 -> 350, as the original's) where it
reset to 200. HISTORICAL figures (2026-10-05, base be0aeb1, dirty tree).
"""
import dataclasses
import json
import pathlib

import pytest

from h2g.convert import convert
from h2g.detect import detect
from h2g.goatwriter import constants as C
from h2g.goatwriter import note_passes as NP
from h2g.sidfile import load_sid
from songview import parse_sng

from corpus import CORPUS, needs_corpus

REPO_ROOT = pathlib.Path(__file__).resolve().parents[2]
NOTE = 0x60
REST = C.GT_REST
TIE = (C.CMD_TONEPORTA, 0x00)
MONTY = "Auf_Wiedersehen_Monty.sid"


def _preset_opts(name):
    import fidelity
    doc = json.loads((REPO_ROOT / "presets.json").read_text(encoding="utf-8"))
    return fidelity._preset_opts(doc, name)


def _convert(name, free=True):
    real = NP.free_note_skips_two_stage
    if not free:
        NP.free_note_skips_two_stage = lambda sid, det: False
    try:
        lines = []
        sng = convert(str(CORPUS / name), log=lines.append, **_preset_opts(name))
    finally:
        NP.free_note_skips_two_stage = real
    return sng, lines


# --- the rows ----------------------------------------------------------------

def test_free_rows_are_the_flagged_note_rows_that_restart():
    pat = [NOTE, 5, 0, 0,            # 0 flagged, plain note: free
           NOTE + 1, 0, *TIE,        # 1 flagged, a tie landing: legato already
           NOTE + 2, 0, 0, 0,        # 2 unflagged
           REST, 0, 0, 0,            # 3 flagged rest: no note
           NOTE + 3, 0, 0x04, 0x07]  # 4 flagged, carries a command: free
    rows = NP.free_note_rows([pat], {0: frozenset({0, 1, 3, 4})})
    assert rows == {(0, 0), (0, 4)}
    assert NP.free_note_rows([pat], {0: None}) == set()     # unknown bit 7
    assert NP.free_note_rows([pat], {}) == set()


def test_variant_keeps_the_rows_command_and_relatches_the_base():
    pat = [NOTE, 5, 0, 0,
           NOTE + 1, 0, 0x04, 0x07,  # free, with a command of its own
           NOTE + 2, 0, 0, 0,        # would inherit the variant
           NOTE + 3, 6, 0, 0,
           NOTE + 4, 0, 0, 0]        # free on an instrument with no stage
    out, variants, declined = NP.free_note_variants(
        [pat], {(0, 1), (0, 4)}, None, {5: 40}, 30)
    assert variants == [(5, 30)]
    assert out[0][4:8] == [NOTE + 1, 30, 0x04, 0x07]
    assert out[0][8:12] == [NOTE + 2, 5, 0, 0]
    assert declined == {(0, 4)} and out[0][16:20] == pat[16:20]


def test_the_decline_says_why():
    pat = [NOTE, 6, 0, 0, NOTE + 1, 0, 0, 0, REST, 0, 0, 0]
    lines = []
    NP.free_note_variants([pat], {(0, 1)}, None, {5: 40}, 30, log=lines.append)
    assert lines == ["Free note (bit 7).......: 0 flagged note row(s) on 0 "
                     "variant(s) with no attack stage and no pulse reset, 1 "
                     "kept the full start (1 no two-stage attack to skip)"]


# --- the player --------------------------------------------------------------

@needs_corpus
@pytest.mark.parametrize("name, skips", [
    (MONTY, True),          # $E56C BMI over $E57C LDA $EE0B,X
    ("ACE_II.sid", True),   # $E180 BMI over $E190 LDA $E627,X
    ("Commando.sid", False),
])
def test_the_skip_is_read_off_the_player(name, skips):
    sid = load_sid(str(CORPUS / name))
    det = detect(sid, lambda *a, **k: None)
    assert NP.free_note_skips_two_stage(sid, det) is skips


@needs_corpus
def test_a_skip_that_jumps_past_no_frame_count_read_is_not_one():
    sid = load_sid(str(CORPUS / MONTY))
    det = detect(sid, lambda *a, **k: None)
    data = bytearray(sid.data)
    at = sid.data.find(bytes([0xBD, 0x0B, 0xEE]))    # $E57C LDA $EE0B,X
    assert at > 0 and sid.to_address(at) == 0xE57C
    data[at + 1] = 0x0C                               # read some other array
    moved = dataclasses.replace(sid, data=bytes(data))
    assert NP.free_note_skips_two_stage(moved, det) is False


# --- Auf Wiedersehen Monty, end to end ---------------------------------------

@pytest.fixture(scope="module")
def monty():
    if not CORPUS.is_dir():
        pytest.skip("corpus absent")
    old, _ = _convert(MONTY, free=False)
    new, lines = _convert(MONTY)
    return parse_sng(old), parse_sng(new), lines


@needs_corpus
def test_monty_respells_its_flagged_notes_on_two_variants(monty):
    old, new, lines = monty
    assert any(l.startswith("Free note (bit 7).......: 21 flagged note row(s)"
                            " on 2 variant(s)") for l in lines)
    n_old = len(old.instruments)
    assert len(new.instruments) == n_old + 2
    assert new.instruments[:n_old] == old.instruments
    assert old.tracks == new.tracks and old.tables == new.tables
    wave = new.tables["WTBL"]
    for ins in new.instruments[n_old:]:
        base = next(b for b in old.instruments if b.name == ins.name)
        assert ins.pulse_ptr == 0 and base.pulse_ptr != 0
        assert (ins.ad, ins.sr, ins.filt_ptr, ins.vib_ptr, ins.vib_delay,
                ins.gatetimer, ins.firstwave) == (
            base.ad, base.sr, base.filt_ptr, base.vib_ptr, base.vib_delay,
            base.gatetimer, base.firstwave)
        # Inside the base's block, on its last entry before the stop: the
        # record's own waveform at the played note -- the attack is behind it.
        assert base.wave_ptr < ins.wave_ptr
        left, right = wave[ins.wave_ptr - 1]
        assert left < 0x80 and right == 0x00
        assert wave[ins.wave_ptr] == (C.GT_WAVE_JUMP, 0x00)
        skipped = wave[base.wave_ptr - 1:ins.wave_ptr - 1]
        assert skipped and all(l != C.GT_WAVE_JUMP for l, _ in skipped)
        assert any(l != left for l, _ in skipped)      # the attack waveform


@needs_corpus
def test_monty_moves_only_the_instrument_column(monty):
    old, new, _ = monty
    n_old = len(old.instruments)
    kinds = {"free": 0, "relatch": 0}
    for x, y in zip(old.patterns, new.patterns):
        for r in range(len(x) // 4):
            a, b = x[4 * r:4 * r + 4], y[4 * r:4 * r + 4]
            if a == b:
                continue
            assert a[0] == b[0] and a[2:] == b[2:], (a, b)
            kinds["free" if b[1] > n_old else "relatch"] += 1
    assert kinds["free"] == 21


@needs_corpus
def test_monty_no_unflagged_note_plays_latched_on_a_variant(monty):
    """A note with an empty column after a variant row would play the
    variant too (gplay.c:912-913 latch). Walked over every orderlist, one
    lap plus the loop."""
    old, new, _ = monty
    variants = set(range(len(old.instruments) + 1, len(new.instruments) + 1))
    leaks = 0
    for track in NP._lapped_tracks(new.tracks):
        cur, operand = 1, False
        for b in track:
            if operand:
                operand = False
                continue
            if b == 0xFF:
                operand = True
                continue
            if b >= 0xD0:
                continue
            pat = new.patterns[b]
            for r in range(len(pat) // 4):
                note, ins = pat[4 * r], pat[4 * r + 1]
                if note == 0xFF:
                    break
                if NOTE <= note <= 0xBC and not ins and cur in variants:
                    leaks += 1
                if ins:
                    cur = ins
            assert cur not in variants
    assert leaks == 0
