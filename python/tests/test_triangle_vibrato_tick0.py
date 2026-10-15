"""The global-triangle vibrato entry against the packed player's tick-0 skip.

`REALTIMEOPTIMIZATION` (player.s `mt_wavedone`) runs no continuous effect on
the first call of a row, so a `row_calls`-call row steps Goattracker's
vibrato on `row_calls - 1` calls; the original's triangle steps every frame.
`_triangle_vibrato_entry` compensates by shortening `cmp` by
`(row_calls - 1) / row_calls` and re-taking the shift from the excursion law.

What is pinned:

  1. 0 and 1 do not compensate, and give the pre-correction entry exactly;
  2. on a transcription of player.s `mt_effect_4` run under the tick-0 skip,
     the oscillation's rate in FRAMES is the original's at every row length
     where the format can express it, and never further from it than the
     uncorrected entry was; the excursion stays within the shift's rounding
     (|log2| <= 0.5) and is exact where `cmp + 2` is a power of two times 3;
  3. `_vibrato_layout` hands each record its own shortest row
     (`instr_row_calls`, Goattracker number `i + lead + 1`), the file's only
     where the record is not attributed;
  4. on the corpus, 5_Title_Tunes' funk player (subtune 1, 2-call rows)
     gets `cmp` 0 and a shift one less than its byte + 1.
"""
import math
import pathlib
import sys

import pytest

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[1]))

from corpus import CORPUS, needs_corpus  # noqa: E402

from h2g.detect import (TRIANGLE_VIBRATO_PEAK,  # noqa: E402
                        TRIANGLE_VIBRATO_PERIOD, detect)
from h2g.goatwriter import _triangle_vibrato_entry  # noqa: E402
from h2g.goatwriter.constants import (FORMAT_GTS5,  # noqa: E402
                                      GT_MAX_VIB_SHIFT)
from h2g.goatwriter.vibrato import _triangle_rate_shift  # noqa: E402
from h2g.goatwriter.vibrato import _vibrato_layout  # noqa: E402
from h2g.sidfile import load_sid  # noqa: E402

GRID = [(m, rc) for m in (1, 2) for rc in range(2, 9)] + [(9, 20), (3, 6)]


def _uncorrected(byte, mult):
    """The entry as it was before the correction, transcribed."""
    cmp_value = min(0x7F, max(0, 4 * mult - 2))
    return (0x80 | cmp_value, min(byte + 1 + _triangle_rate_shift(mult),
                                  GT_MAX_VIB_SHIFT))


def _effect4(vibtime, cmp):
    """One call of player.s `mt_effect_4` (lines 367-402): the new vibtime
    and +1 (freqadd) or -1 (freqsub)."""
    a = vibtime
    if not a & 0x80 and a > cmp:      # bcc/beq not taken: reverse
        a ^= 0xFF
    a = (a + 2) & 0xFF                # clc / adc #$02
    return a, (-1 if a & 1 else 1)    # lsr: carry set -> freqsub


def _ours(entry, mult, row_calls, frames):
    """Our offset per frame, in units of `interval >> byte`'s fraction:
    the frequency after each frame's last call, under the tick-0 skip."""
    speedcmp, rshift = entry
    cmp = speedcmp & 0x7F
    step = 2.0 ** -rshift
    vib, off, out = 0, 0.0, []
    for n in range(frames * mult):
        if row_calls < 2 or n % row_calls:
            vib, d = _effect4(vib, cmp)
            off += d * step
        if n % mult == mult - 1:
            out.append(off)
    return out


def _player(byte, frames):
    """The original: offset = phase * (interval >> (byte + 1)), the folded
    triangle 0,1,2,3,3,2,1,0 stepped once per frame."""
    fold = [0, 1, 2, 3, 3, 2, 1, 0]
    assert len(fold) == TRIANGLE_VIBRATO_PERIOD
    return [fold[f % 8] * 2.0 ** -(byte + 1) for f in range(frames)]


def _reversals(seq):
    signs = [d > 0 for d in (b - a for a, b in zip(seq, seq[1:])) if d]
    return sum(1 for a, b in zip(signs, signs[1:]) if a != b)


def _rate(seq, ref):
    return _reversals(seq) / _reversals(ref)


def _depth(seq, ref):
    tail = seq[len(seq) // 2:]
    return (max(tail) - min(tail)) / (max(ref) - min(ref))


FRAMES = 2400


@pytest.mark.parametrize("mult", [1, 2, 3, 4, 9])
@pytest.mark.parametrize("rc", [0, 1])
def test_no_row_length_is_the_uncorrected_entry(mult, rc):
    for byte in range(1, 15):
        assert _triangle_vibrato_entry(byte, mult, rc) == _uncorrected(
            byte, mult), (byte, mult, rc)
        assert _triangle_vibrato_entry(byte, mult) == _uncorrected(byte, mult)


def test_the_transcription_reproduces_the_documented_period():
    """`period = 2 * cmp + 4` calls with every call an effect call -- the
    law _triangle_vibrato_entry's docstring derives from gplay.c."""
    for cmp in range(0, 12):
        seq = _ours((0x80 | cmp, 0), 1, 0, 1000)
        assert _reversals(seq) == pytest.approx(1000 / (cmp + 2), abs=2)


@pytest.mark.parametrize("mult,rc", GRID)
def test_the_rate_in_frames_is_the_originals_where_expressible(mult, rc):
    byte = 2
    ref = _player(byte, FRAMES)
    new = _rate(_ours(_triangle_vibrato_entry(byte, mult, rc), mult, rc,
                      FRAMES), ref)
    old = _rate(_ours(_uncorrected(byte, mult), mult, rc, FRAMES), ref)
    # The corrected half-period is round(4 m (rc-1)/rc) effect calls; it is
    # the original's 4 frames exactly when that rounding is exact.
    half = 4 * mult * (rc - 1) / rc
    if half == round(half):
        assert new == pytest.approx(1.0, abs=0.01), (mult, rc, new)
    assert abs(math.log2(new)) <= abs(math.log2(old)) + 1e-9, (mult, rc,
                                                                new, old)
    # Rounding a half-period of >= 2 calls is worth at most a quarter of it.
    assert abs(math.log2(new)) <= math.log2(4 / 3) + 1e-9, (mult, rc, new)


@pytest.mark.parametrize("mult,rc", GRID + [(4, 8), (4, 3), (2, 3)])
def test_the_excursion_stays_within_the_shifts_rounding(mult, rc):
    for byte in (1, 2, 3, 5):
        entry = _triangle_vibrato_entry(byte, mult, rc)
        got = _depth(_ours(entry, mult, rc, FRAMES), _player(byte, FRAMES))
        assert abs(math.log2(got)) <= 0.5 + 1e-9, (mult, rc, byte, got)
        if (((entry[0] & 0x7F) + 2) / TRIANGLE_VIBRATO_PEAK).is_integer() \
                and math.log2(((entry[0] & 0x7F) + 2)
                              / TRIANGLE_VIBRATO_PEAK).is_integer():
            assert got == pytest.approx(1.0), (mult, rc, byte, got)


def test_the_shift_is_one_rounding_of_the_excursion_law():
    """`byte + 1 + round(log2((cmp + 2) / PEAK))` with the emitted `cmp`.
    Paying the shortened half-period back on top of the uncorrected shift
    rounds twice: at -S2 3-call rows it gives 5/3 of the player's excursion
    where one rounding gives 5/6. Game_Killer (-S9, 20-call rows) takes
    cmp 34 -> 32 and the same shift as the uncorrected entry, now that
    `_triangle_rate_shift` rounds the whole ratio too."""
    for mult in (1, 2, 3, 4, 8, 9):
        for rc in range(2, 25):
            for byte in range(1, 9):
                got = _triangle_vibrato_entry(byte, mult, rc)
                cmp = got[0] & 0x7F
                assert got[1] == min(byte + 1 + round(math.log2(
                    (cmp + 2) / TRIANGLE_VIBRATO_PEAK)), GT_MAX_VIB_SHIFT), (
                        mult, rc, byte)
    assert _triangle_vibrato_entry(2, 2, 3) == (0x83, 4)
    assert _uncorrected(2, 9) == (0x80 | 34, 7)
    assert _triangle_vibrato_entry(2, 9, 20) == (0x80 | 32, 7)


def test_a_two_call_row_at_s1_keeps_the_period_and_the_formats_four_thirds():
    """5_Title_Tunes subtune 1's case: cmp 0, one shift less. Uncorrected,
    the rate is half the original's and the travel per frame two thirds;
    corrected, the rate is the original's and the travel four thirds -- the
    format's own 4/3 depth residual, now the only error left."""
    ref = _player(2, FRAMES)
    entry = _triangle_vibrato_entry(2, 1, 2)
    assert entry == (0x80, 2)
    old = _ours(_uncorrected(2, 1), 1, 2, FRAMES)
    new = _ours(entry, 1, 2, FRAMES)
    assert _rate(old, ref) == pytest.approx(0.5, abs=0.01)
    assert _rate(new, ref) == pytest.approx(1.0, abs=0.01)

    def travel(s):
        return sum(abs(b - a) for a, b in zip(s, s[1:]))
    assert travel(old) / travel(ref) == pytest.approx(2 / 3, abs=0.01)
    assert travel(new) / travel(ref) == pytest.approx(4 / 3, abs=0.01)


@needs_corpus
def test_the_layout_takes_each_records_own_row():
    sid = load_sid(str(CORPUS / "Gerry_the_Germ.sid"))
    det = detect(sid, log=lambda m: None)
    assert det.triangle_vibrato is not None
    n = 30
    data = sid.data
    live = [i for i in range(n - 1)
            if det.instr_start + i * det.instr_stride < len(data)
            and _triangle_vibrato_entry(
                data[det.instr_start + i * det.instr_stride
                     + det.triangle_vibrato], 1) is not None]
    assert len(live) >= 4
    lead = 1
    # Odd records at 2-call rows, even ones unattributed (file's 4).
    irc = {i + lead + 1: 2 for i in live[::2]}
    table: list = []
    got = _vibrato_layout(sid, det, n, True, FORMAT_GTS5, 1, table,
                          lead=lead, row_calls=4, instr_row_calls=irc)
    assert set(got) == set(live)
    for i in live:
        byte = data[det.instr_start + i * det.instr_stride
                    + det.triangle_vibrato]
        rc = irc.get(i + lead + 1, 4)
        assert table[got[i][0] - 1] == _triangle_vibrato_entry(byte, 1, rc), i
        assert (table[got[i][0] - 1][0] & 0x7F) == (0 if rc == 2 else 1), i


def _asked(monkeypatch, name):
    """Every (byte, multiplier, row_calls, entry) the triangle entry is
    asked for while `name` converts under presets."""
    import json
    import fidelity as F
    from h2g.convert import convert
    import h2g.goatwriter.vibrato as V
    root = pathlib.Path(__file__).resolve().parents[2]
    doc = json.loads((root / "presets.json").read_text())
    seen = []
    real = V._triangle_vibrato_entry

    def spy(byte, mult, rc=0):
        out = real(byte, mult, rc)
        seen.append((byte, mult, rc, out))
        return out
    monkeypatch.setattr(V, "_triangle_vibrato_entry", spy)
    convert(str(CORPUS / name), log=lambda m: None,
            **F._preset_opts(doc, name))
    return [s for s in seen if s[3] is not None]


@needs_corpus
def test_build_sng_hands_the_layout_each_records_row(monkeypatch):
    """Gerry_the_Germ's file-wide shortest row is 2 (subtune 2), but its
    records are played at 2, 3 and 4 calls; through `build_sng` each is
    asked at its own (`tracks.instrument_row_calls`), not all at 2."""
    assert {rc for _, _, rc, _ in _asked(monkeypatch,
                                         "Gerry_the_Germ.sid")} == {2, 3, 4}


@needs_corpus
def test_five_title_tunes_funk_player_gets_cmp_zero(monkeypatch):
    """Under presets, the subtune-1 player's triangle records are asked for
    at 2-call rows and come out `cmp` 0, shift = byte; the other players are
    asked at their own rows (s0 4, s2/s3 3), never at 2."""
    live = _asked(monkeypatch, "5_Title_Tunes.sid")
    assert {rc for _, _, rc, _ in live} == {2, 3, 4}
    funk = [s for s in live if s[2] == 2]
    assert funk
    for byte, mult, _, out in funk:
        assert mult == 1
        assert out == (0x80, byte), (byte, out)
