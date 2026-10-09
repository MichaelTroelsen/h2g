"""The classic vibrato's RATE in a player whose outer gate stops the whole play
routine, and in one whose counter holds the bound (mozart-classic-vibrato-
file-wide-rate; figures historical, measured at v0.5.517, -t 180, presets).

Mozart's update steps `ctr` once per call that passes `DEC $0C33 / BPL` (two
calls in three), and on top of that sits on the bound for two updates, so its
oscillation's half-period is `(bound + 1/2) * 3/2` frames, not `bound`. The
entry used to say `bound`: voice 0's bound-3 records read 3 frames a half-
period against the original's 5 (128 cycles to 401 in a 180 s window); with
the skip and the dwell modelled they read 5 against 5 (127). Ablated one cause
at a time on those records (half-period frames, ours; original 5.0):

    neither 3.0   skip alone 5.0 (swing 2.5u)   dwell alone 4.0   both 5.0

The depth loop of the same player shifts `shift + 1` times (count tested
last), so its depth is half what the entry assumed; `depth_extra` carries
that into the shift. Only `vibrato_dwell` and `vibrato_shift_extra` read it,
and in the corpus only Mozart does.

Scope: `entry_gate` players (International_Karate, Kentilla,
Las_Vegas_Video_Poker, Mozart, Proteus, Thrust, Warhawk) take the stretch; no
other file's bytes move (corpus byte-hash, 89 compared, 6 refused in both
arms, exactly those seven move).
"""
import pathlib
import sys

import pytest

from corpus import CORPUS, needs_corpus

PYTHON_ROOT = pathlib.Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PYTHON_ROOT))
import h2g.goatwriter.vibrato as vibrato_mod                  # noqa: E402
from h2g.convert import convert                               # noqa: E402
from h2g.detect import (VIBRATO_BOUND_SHIFT, _find_vibrato_dwell,  # noqa: E402
                        _find_vibrato_shift_extra, detect)
from h2g.goatwriter import (_classic_vibrato_entry,           # noqa: E402
                            _vibrato_layout)
from h2g.goatwriter.constants import VIBRATO_CMP_BIAS         # noqa: E402
from h2g.goatwriter.call_phase import entry_gate              # noqa: E402
from h2g.sidfile import load_sid                              # noqa: E402

# The files whose update sits on the bound for two updates (period 2*bound+1)
# -- test_classic_vibrato_census.DWELL -- and the ones the converter resolves.
DWELL_FAMILY_C = ("Go_Go_Dash", "Lakers_vs_Celtics", "Lion_Heart",
                  "Pacific_Coast", "Radio_ACE", "Sun_Never_Shines")
ENTRY_GATE_CLASSIC = {"International_Karate": 10, "Kentilla": 10,
                      "Las_Vegas_Video_Poker": 4, "Mozart": 2, "Proteus": 7,
                      "Thrust": 9, "Warhawk": 7}


def _byte(bound, shift=0):
    return (bound << VIBRATO_BOUND_SHIFT) | shift


# --- the entry --------------------------------------------------------------

@pytest.mark.parametrize("bound", [1, 2, 3, 4, 5, 7, 15])
@pytest.mark.parametrize("multiplier", [1, 2, 3, 7])
def test_defaults_are_the_entry_it_always_was(bound, multiplier):
    """No gate, no dwell, no extra: `cmp = bound * multiplier - 2`, `rshift =
    shift + round(log2(multiplier))`, byte for byte -- the 88 files that do not
    carry the skip keep their bytes."""
    import math
    cmp_value, rshift = _classic_vibrato_entry(_byte(bound, 2), multiplier, 0)
    assert cmp_value == 0x80 | min(0x7F, max(0, bound * multiplier - 2))
    assert rshift == 2 + max(0, round(math.log2(multiplier)))


@pytest.mark.parametrize("bound", [2, 3, 4, 5, 8])
@pytest.mark.parametrize("gate", [2, 4, 7, 10])
def test_an_entry_gate_player_lasts_o_plus_one_over_o_frames_an_update(bound, gate):
    """The half-period is `bound * (O + 1) / O` frames: `cmp + 2` calls at
    multiplier 1 and no tick-0 compensation."""
    cmp_value, _ = _classic_vibrato_entry(_byte(bound), 1, 0, gate_skip=gate)
    assert (cmp_value & 0x7F) + VIBRATO_CMP_BIAS == round(bound * (gate + 1) / gate)


@pytest.mark.parametrize("bound", [2, 3, 4, 5, 8])
def test_a_dwelling_counter_has_a_half_period_of_bound_and_a_half(bound):
    cmp_value, _ = _classic_vibrato_entry(_byte(bound), 2, 0, dwell=True)
    assert (cmp_value & 0x7F) + VIBRATO_CMP_BIAS == round((bound + 0.5) * 2)


def test_mozart_voice_zero_bound_three_is_five_frames_a_half_period():
    """Mozart at -S2, rows of 3 calls (`row_calls` 3): the entry the layout
    builds for its bound-3 records. The original's measured half-period is 5.0
    frames; cmp 5 is 7 calls over 2/3 of them running = 5.25 frames."""
    cmp_value, rshift = _classic_vibrato_entry(
        _byte(3, 2), 2, 3, gate_skip=2, dwell=True, depth_extra=1)
    assert cmp_value == 0x80 | 5
    assert (cmp_value & 0x7F) + VIBRATO_CMP_BIAS == 7
    # 7 calls at 2 per frame, one in three of them (tick 0) not running it
    assert 7 / 2 * 3 / 2 == 5.25
    assert rshift == 2 + 1 + 1


def _player_half_period_frames(bound, outer_reload):
    """Run Mozart's update (`09B2-09D6`) under its gate (`0829-0833`) and
    return the mean frames between the counter's turning points."""
    ctr, direction, gate = 0, 0x00, outer_reload
    frames_at_turn, frame = [], 0
    prev = ctr
    last_dir = None
    for _ in range(4000):
        frame += 1
        gate -= 1
        if gate < 0:
            gate = outer_reload
            continue                                  # RTS: no update this call
        if direction & 0x80 == 0:                     # `LDA dir,X / BPL`: up
            ctr += 1
            if bound < ctr:                           # CMP ctr,X / BCS fails
                ctr = bound
                direction = 0xFF
        else:                                         # down
            ctr -= 1
            if ctr == 0:
                direction = 0
        d = (ctr > prev) - (ctr < prev)
        if d and last_dir is not None and d != last_dir:
            frames_at_turn.append(frame)
        if d:
            last_dir = d
        prev = ctr
    gaps = [b - a for a, b in zip(frames_at_turn, frames_at_turn[1:])]
    return sum(gaps) / len(gaps)


@pytest.mark.parametrize("bound", [2, 3, 4, 5])
def test_the_entry_matches_a_transcription_of_the_players_counter(bound):
    """The player's own update and gate, run: the mean half-period in frames
    is `(bound + 1/2) * 3/2`, and the entry at multiplier 1 (no tick-0
    compensation) is that to the nearest call. Pins the model to the
    mechanism, not to a number the model was fitted on."""
    frames = _player_half_period_frames(bound, outer_reload=2)
    assert frames == pytest.approx((bound + 0.5) * 3 / 2, abs=0.05)
    cmp_value, _ = _classic_vibrato_entry(_byte(bound), 1, 0, gate_skip=2,
                                          dwell=True)
    assert abs((cmp_value & 0x7F) + VIBRATO_CMP_BIAS - frames) <= 0.5


def test_a_deeper_shift_loop_halves_the_depth_it_asks_of_the_entry():
    """`depth_extra` raises `rshift` so the emitted swing, `(cmp + 2) * (I >>
    rshift)`, tracks the player's `bound * (I >> (shift + 1))` and not
    `bound * (I >> shift)`. Checked as the swing ratio over every bound."""
    interval = 1 << 16
    for bound in range(1, 9):
        for shift in range(0, 4):
            cmp_value, rshift = _classic_vibrato_entry(
                _byte(bound, shift), 2, 3, gate_skip=2, dwell=True,
                depth_extra=1)
            ours = ((cmp_value & 0x7F) + VIBRATO_CMP_BIAS) * (interval >> rshift)
            theirs = bound * (interval >> (shift + 1))
            assert 0.7 <= ours / theirs <= 1.45, (bound, shift)


# --- detection --------------------------------------------------------------

@needs_corpus
def test_only_mozart_reads_as_dwelling_and_as_shifting_one_more():
    got, extra = [], []
    for path in sorted(CORPUS.glob("*.sid")):
        try:
            det = detect(load_sid(str(path)), lambda *a: None)
        except Exception:                                  # noqa: BLE001
            continue
        if det.vibrato_offset is None:
            assert not det.vibrato_dwell and not det.vibrato_shift_extra
            continue
        if det.vibrato_dwell:
            got.append(path.stem)
        if det.vibrato_shift_extra:
            extra.append(path.stem)
    assert got == ["Mozart"]
    assert extra == ["Mozart"]


@needs_corpus
def test_the_dwell_reads_the_six_dollar_1003_files_too_and_not_the_others():
    """The converter does not resolve these six (no `vibrato_offset`), so the
    reader is exercised at their update directly. The stepping-back family
    (`STA ctr / DEC dir / DEC ctr`) must read False."""
    for name in DWELL_FAMILY_C:
        sid = load_sid(str(CORPUS / f"{name}.sid"))
        assert _find_vibrato_dwell(sid, sid.to_offset(0x1490)), name
    for name, at in (("Warhawk", 0x11EF), ("Tarzan", 0x56E0),
                     ("Mega_Apocalypse", 0x4C40), ("Las_Vegas_Video_Poker",
                                                   0x51C0)):
        sid = load_sid(str(CORPUS / f"{name}.sid"))
        assert not _find_vibrato_dwell(sid, sid.to_offset(at)), name
        assert _find_vibrato_shift_extra(sid, sid.to_offset(at)) == 0, name


@needs_corpus
def test_the_entry_gate_players_with_a_classic_vibrato_are_these_seven():
    got = {}
    for path in sorted(CORPUS.glob("*.sid")):
        try:
            sid = load_sid(str(path))
            det = detect(sid, lambda *a: None)
        except Exception:                                  # noqa: BLE001
            continue
        if det.vibrato_offset is not None and entry_gate(sid):
            from h2g.goatwriter.tempo import outer_gate_skip
            got[path.stem] = outer_gate_skip(sid)
    assert got == ENTRY_GATE_CLASSIC


# --- the wiring: what `build_sng` hands the entry ----------------------------

def _entry_calls(name):
    """The (gate_skip, dwell, depth_extra) every classic entry of `name` was
    built with, recorded off a real conversion."""
    seen = []
    real = vibrato_mod._classic_vibrato_entry

    def spy(byte, multiplier, row_calls=0, gate_skip=None, dwell=False,
            depth_extra=0):
        seen.append((gate_skip, dwell, depth_extra))
        return real(byte, multiplier, row_calls, gate_skip=gate_skip,
                    dwell=dwell, depth_extra=depth_extra)

    vibrato_mod._classic_vibrato_entry = spy
    try:
        convert(str(CORPUS / f"{name}.sid"), log=lambda *a: None,
                fmt="gts5", vibrato=True, effects=True)
    finally:
        vibrato_mod._classic_vibrato_entry = real
    return set(seen)


@needs_corpus
@pytest.mark.parametrize("name, want", [
    ("Mozart", {(2, True, 1)}),
    ("Warhawk", {(7, False, 0)}),
    ("Tarzan", {(None, False, 0)}),
    ("Powerplay_Hockey_USA_vs_USSR", {(None, False, 0)}),
])
def test_build_hands_the_entry_the_gate_only_for_an_entry_gate_player(name, want):
    assert _entry_calls(name) == want


def test_the_layout_default_is_no_gate():
    """`_vibrato_layout` without `gate_skip` builds the entries it always did."""
    from h2g.detect import Detection

    class Sid:
        data = bytes([0, 0, 0x41, 0, 0, _byte(3, 2), 0, 0] * 2)

    det = Detection(instr_start=0, instr_stride=8, vibrato_offset=5)
    plain, with_gate = [], []
    _vibrato_layout(Sid, det, 3, True, "gts5", 2, plain)
    _vibrato_layout(Sid, det, 3, True, "gts5", 2, with_gate, gate_skip=2)
    assert plain == [_classic_vibrato_entry(_byte(3, 2), 2, 0)]
    assert with_gate == [_classic_vibrato_entry(_byte(3, 2), 2, 0, gate_skip=2)]
    assert plain != with_gate
