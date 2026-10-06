"""The expanding vibrato's swell on wavetable loops, which move on every call.

Opened by expanding-vibrato-gate: once the onset sat on the record's gate, the
swing after it was still short. Mega_Apocalypse `$00B9` (siddump, -t 180,
presets) read `236 0 0 -236 0 0` against the original's `246 123 0 -139 0 155
342`: a `4xy` row's oscillator is skipped on every row's tick 0 (player.s
`mt_wavedone`, REALTIMEOPTIMIZATION; gplay.c:731), so it moved on two calls in
three, and `_classic_vibrato_entry`'s tick-0 `cmp` stretched `$09B7`'s
8-frame period to 9. A wavetable command runs on tick 0 (`mt_execwavecmd`
jumps past the counter test), so `_expanding_vibrato_loops` points the hold
rows at `[F4 idx, FF -> F4]` loops with the player's own `cmp`.
"""
import json
import pathlib
import sys

import pytest

PYTHON_ROOT = pathlib.Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PYTHON_ROOT))

from corpus import CORPUS, needs_corpus  # noqa: E402
from h2g.detect import Detection, VibratoGate  # noqa: E402
from h2g.goatwriter.constants import (CMD_SETWAVEPTR,  # noqa: E402
                                      CMD_TONEPORTA, CMD_VIBRATO,
                                      GT_REST, SPEED_NOTE_RELATIVE)
from h2g.goatwriter.note_passes import (  # noqa: E402
    EXPANDING_VIBRATO_ABS_SPEEDS, _expanding_vibrato_loop_entry,
    _expanding_vibrato_loops, _expanding_vibrato_pass,
    _expanding_vibrato_remainder)
from h2g.goatwriter.primitives import _note_freq  # noqa: E402
from h2g.sidfile import FreqTable  # noqa: E402

END = 0xFF                      # patterns.GT_END_PATTERN
CMD_PORTAUP = 0x01              # gcommon.h CMD_PORTAUP
F4 = 0xF4                       # WAVECMD_BASE + CMD_VIBRATO
JUMP = 0xFF                     # GT_WAVE_JUMP


# ---------------------------------------------------------------------------
# gplay.c's vibrato, transcribed: CMD_VIBRATO at :777-800 (and the wavetable
# command's copy at :618-645), the tick-0 test at :731.

def _vib_step(state, cmp_value, speed):
    """One call of the oscillator; `state` is [vibtime, freq]."""
    vt = state[0]
    if vt < 0x80 and vt > cmp_value:
        vt ^= 0xFF
    vt = (vt + 2) & 0xFF
    state[0] = vt
    state[1] += -speed if vt & 1 else speed


def _trace(cmp_value, speed, calls, row_calls, skip_tick0):
    """Frequency offset after each of `calls` calls from a zeroed vibtime;
    with `skip_tick0`, every `row_calls`-th call runs no continuous effect
    (gplay.c:731 `if ((!optimizerealtime) || (cptr->tick))`)."""
    state, out = [0, 0], []
    for c in range(calls):
        if not (skip_tick0 and c % row_calls == 0):
            _vib_step(state, cmp_value, speed)
        out.append(state[1])
    return out


def _period(offsets):
    """Calls between successive arrivals at the same maximum."""
    top = max(offsets)
    at = [i for i, v in enumerate(offsets) if v == top]
    return at[1] - at[0]


# ---------------------------------------------------------------------------
# A synthetic file: Goattracker's own note table, one record with vibrato byte
# `param`, a counter gate per record.

class _AgeSid:
    TABLE = 0x1000

    def __init__(self, param=0x23):
        data = bytearray([0x00, 0x00, 0x41, 0x00, 0x00, param, 0x00, 0x00])
        data += bytes(self.TABLE - len(data))
        for n in range(96):
            f = min(_note_freq(n), 0xFFFF)
            data += bytes([f & 0xFF, f >> 8])
        self.data = bytes(data)

    def to_offset(self, addr):
        return addr


def _det(gate):
    det = Detection(instr_start=0, instr_stride=8, vibrato_offset=5,
                    freq_table=FreqTable(addr=_AgeSid.TABLE, start=0,
                                         length=96, shift=0, detune=0.0))
    det.vibrato_gate = VibratoGate("counter", None, 0x13, 0xBC,
                                   table=0x2000, per_record=(gate,))
    return det


PROGRAM = [(0x41, 0x00), (0x41, 0x00), (0x41, 0x00), (JUMP, 0x00)]


def _convert(rows, gate=7, param=0x23, wave=None, mult=1, row_calls=3):
    """The classic pass, then the loop step, on one pattern of `rows`;
    returns (pattern, speed table, wavetable)."""
    sid, det = _AgeSid(param), _det(gate)
    pat = [b for row in rows for b in row] + [END, 0, 0, 0]
    table = [(0x81, 3)]
    entries = list(wave if wave is not None else PROGRAM)
    _expanding_vibrato_pass(sid, det, [[0, 0xFF, 0]], [pat], {0: (1, 2)},
                            table, 0, mult, row_calls)
    entries, n = _expanding_vibrato_loops(
        sid, det, [[0, 0xFF, 0]], [pat], {0: (1, 2)}, table, 0, mult,
        row_calls, entries, [1])
    return pat, table, entries, n


def _note(note=0xB3, instr=1, cmd=0, data=0):
    return (note, instr, cmd, data)


def _hold(cmd=0, data=0):
    return (GT_REST, 0, cmd, data)


def _cmds(pat, n):
    return [(pat[i + 2], pat[i + 3]) for i in range(0, 4 * n, 4)]


def _block(entries, start):
    """The loop a CMD_SETWAVEPTR operand names: (prefix, speed index),
    asserting it ends `F4 idx / FF -> the F4`."""
    i = start - 1
    prefix = []
    while entries[i][0] != F4:
        prefix.append(entries[i])
        i += 1
    assert entries[i + 1] == (JUMP, i + 1), (start, entries[i:i + 2])
    return prefix, entries[i][1]


# ---------------------------------------------------------------------------

def test_a_wavetable_loop_moves_on_every_call_and_a_4xy_on_two_in_three():
    """The mechanism, on gplay.c's own loop: 3-call rows, `cmp 0`."""
    pattern = _trace(0, 100, 24, 3, skip_tick0=True)
    loop = _trace(0, 100, 24, 3, skip_tick0=False)
    moved = lambda off: sum(1 for a, b in zip([0] + off, off) if a != b)
    assert moved(loop) == 24
    assert moved(pattern) == 16
    # `cmp 0` is `+ - - +`: a period of 4 calls, 6 frames under the skip.
    assert _period(loop) == 4 and _period(pattern) == 6


@pytest.mark.parametrize("param,bound", [(0x23, 4), (0x1B, 3), (0x2B, 5),
                                         (0x33, 6)])
def test_the_loops_cmp_is_the_players_period_and_swing(param, bound):
    """Every F4 the step writes names an entry whose `cmp` gives gplay.c's
    loop a period of 2 * bound calls and a peak-to-peak of `bound` speeds --
    the player's counter walking 0..bound once a frame (`bound * step`,
    `_classic_vibrato_entry`) -- with nothing taken off for a tick 0 the
    loop does not skip."""
    pat, table, entries, n = _convert(
        [_note()] + [_hold() for _ in range(30)], param=param)
    assert n > 0
    idxs = {_block(entries, d)[1] for c, d in _cmds(pat, 31)
            if c == CMD_SETWAVEPTR}
    assert idxs
    for idx in idxs:
        left, right = table[idx - 1]
        cmp_value = left & 0x7F
        assert cmp_value == bound - 2, (param, table[idx - 1])
        off = _trace(cmp_value, 100, 8 * bound, 3, skip_tick0=False)
        assert _period(off) == 2 * bound
        assert max(off) - min(off) == bound * 100


def test_rows_before_the_gate_stay_and_the_gate_row_waits_on_a_delay():
    """Gate 7 at -S1 is call 8 (the test-bit attack is seen on call 1,
    `_counter_gate_call`). Rows 1 (calls 3-5) end before it and are left;
    row 2 (calls 6-8) contains it and points at `[delay 1/$80, F4, FF]`, so
    the loop's first step is on call 6 + (1 + 1) = 8; every row after it
    points at the plain loop."""
    pat, table, entries, n = _convert(
        [_note()] + [_hold() for _ in range(20)], gate=7)
    cmds = _cmds(pat, 21)
    assert cmds[0] == (0, 0)                      # the note row
    assert cmds[1] == (0, 0)                      # before the gate
    assert cmds[2][0] == CMD_SETWAVEPTR
    prefix, _ = _block(entries, cmds[2][1])
    assert prefix == [(1, 0x80)]                  # 1 + 1 calls, no re-pitch
    for c, d in cmds[3:]:
        assert c == CMD_SETWAVEPTR
        assert _block(entries, d)[0] == []
    # The original program is untouched and the loops are appended past it.
    assert entries[:4] == PROGRAM and min(d for c, d in cmds[2:]) > 4
    assert n == 19


def test_a_gate_on_a_row_boundary_needs_no_delay():
    """Gate 8 is call 9, row 3's first: no prefix there, row 2 is left."""
    pat, table, entries, n = _convert(
        [_note()] + [_hold() for _ in range(10)], gate=8)
    cmds = _cmds(pat, 11)
    assert cmds[2] == (0, 0) or cmds[2][0] == CMD_VIBRATO
    assert cmds[3][0] == CMD_SETWAVEPTR
    assert _block(entries, cmds[3][1])[0] == []


def test_the_rest_of_an_unfinished_program_runs_before_the_loop():
    """Gate 1 (call 2): row 1 starts on call 3, where a five-step program
    has read steps 1-2 (calls 1, 2) and would read step 3 on call 3 itself
    -- the call the row's pointer is taken on, before the wavetable runs. So
    steps 3-5 precede the loop: the re-pitch and the gate-off both stay."""
    prog = [(0x41, 0x00), (0x41, 0x80), (0x41, 0x00), (0x40, 0x00),
            (0x40, 0x00), (JUMP, 0x00)]
    pat, table, entries, n = _convert(
        [_note()] + [_hold() for _ in range(6)], gate=1, wave=prog)
    cmds = _cmds(pat, 7)
    assert cmds[1][0] == CMD_SETWAVEPTR
    assert _block(entries, cmds[1][1])[0] == [(0x41, 0x00), (0x40, 0x00),
                                              (0x40, 0x00)]
    assert _block(entries, cmds[2][1])[0] == []


def test_the_remainder_walk():
    prog = [(0x41, 0x00), (0x02, 0x80), (0x41, 0x00), (JUMP, 0x00)]
    # Step 1 on call 1, the delay on calls 2-4 (read on its last), step 3
    # on call 5.
    assert _expanding_vibrato_remainder(prog, 1, 1) == tuple(prog[:3])
    assert _expanding_vibrato_remainder(prog, 1, 2) == tuple(prog[1:3])
    assert _expanding_vibrato_remainder(prog, 1, 4) == tuple(prog[1:3])
    assert _expanding_vibrato_remainder(prog, 1, 5) == (prog[2],)
    assert _expanding_vibrato_remainder(prog, 1, 6) == ()
    assert _expanding_vibrato_remainder(prog, 0, 6) == ()       # no program
    loops = [(0x41, 0x00), (0x41, 0x00), (JUMP, 0x01)]
    assert _expanding_vibrato_remainder(loops, 1, 9) is None


def test_a_looping_program_keeps_the_pass_rows():
    loops = [(0x41, 0x00), (0x40, 0x00), (JUMP, 0x01)]
    pat, table, entries, n = _convert(
        [_note()] + [_hold() for _ in range(20)], gate=7, wave=loops)
    assert n == 0 and entries == loops
    assert all(c in (0, CMD_VIBRATO) for c, _ in _cmds(pat, 21))


def test_a_block_a_tie_ends_is_not_looped():
    """A tie is the one note that does not re-point the wavetable
    (gplay.c:352): a loop would run on under it, and its wavetable command
    keeps the voice off the portamento. The tie's own hold rows may loop:
    its `3 00` resolves on the tie row's first tick-N call, before them."""
    rows = ([_note()] + [_hold() for _ in range(10)]
            + [_note(0xB5, 0, CMD_TONEPORTA, 0)] + [_hold() for _ in range(3)]
            + [_note(0xB0)] + [_hold() for _ in range(10)])
    pat, table, entries, n = _convert(rows, gate=7)
    cmds = _cmds(pat, len(rows))
    assert all(c != CMD_SETWAVEPTR for c, _ in cmds[:11]), cmds[:11]
    assert cmds[11] == (CMD_TONEPORTA, 0)
    # The pass's own rows stay, so the classic swell is still there ...
    assert any(c == CMD_VIBRATO for c, _ in cmds[1:11])
    # ... and the note after is looped as usual.
    assert any(c == CMD_SETWAVEPTR for c, _ in cmds[16:])


def test_a_row_another_command_holds_is_left():
    rows = [_note()] + [_hold() for _ in range(5)] + [_hold(CMD_PORTAUP, 1)] \
        + [_hold() for _ in range(5)]
    pat, table, entries, n = _convert(rows, gate=7)
    cmds = _cmds(pat, len(rows))
    assert cmds[6] == (CMD_PORTAUP, 1)
    assert cmds[5][0] == cmds[7][0] == CMD_SETWAVEPTR


def test_the_entry_chooser_takes_an_absolute_speed_where_the_interval_is_short():
    """`cmp 2` (peak-to-peak 4 speeds). Low note: the interval is ~20 units,
    so a 1000-unit swing is past every note-relative entry and an absolute
    250 is nearest. High note: the interval is past 255, so the whole
    interval is the nearest. In between, an absolute speed wins on
    precision over the octave-apart shifts."""
    low = 30
    ivl = _note_freq(low + 1) - _note_freq(low)
    assert 4 * ivl < 1000
    assert _expanding_vibrato_loop_entry(1000, low, 2, 3) == (0x02, 255)
    high = 90
    ivl = _note_freq(high + 1) - _note_freq(high)
    assert ivl > 255
    assert _expanding_vibrato_loop_entry(4 * ivl, high, 2, 3) == \
        (SPEED_NOTE_RELATIVE | 0x02, 0)
    entry = _expanding_vibrato_loop_entry(4 * 100, 60, 2, 3)
    assert entry[0] == 0x02 and entry[1] in EXPANDING_VIBRATO_ABS_SPEEDS
    assert abs(entry[1] - 100) / 100 < 2 ** (1 / 8) - 1 + 1e-9
    # Nothing to aim at keeps the instrument's own note-relative level.
    assert _expanding_vibrato_loop_entry(0, 60, 2, 3) == \
        (SPEED_NOTE_RELATIVE | 0x02, 3)


# ---------------------------------------------------------------------------
# Mega_Apocalypse, the one unheld file with this routine.

def _mega():
    import fidelity
    from h2g.convert import convert
    doc = json.loads((PYTHON_ROOT.parent / "presets.json").read_text())
    opts = fidelity._preset_opts(doc, "Mega_Apocalypse.sid")
    logs = []
    sng = convert(str(CORPUS / "Mega_Apocalypse.sid"), logs.append, **opts)
    return fidelity, opts, sng, logs


@needs_corpus
def test_mega_apocalypse_hold_rows_point_at_loops_with_the_players_cmp():
    from songview import parse_sng
    _f, _o, sng, logs = _mega()
    assert any(m.startswith("Expanding vibrato loops.") for m in logs)
    song = parse_sng(sng)
    wt, st = song.tables["WTBL"], song.tables["STBL"]
    starts = {p[i + 3] for p in song.patterns for i in range(0, len(p), 4)
              if p[i + 2] == CMD_SETWAVEPTR}
    loops = [s for s in starts if any(e[0] == F4 for e in wt[s - 1:s + 2])]
    assert len(loops) >= 10, loops
    # Every loop's cmp is `bound - 2` (-S1) of a record carrying the
    # vibrato: the bound is the name's `+5` byte (`_write_instruments`'
    # `NN:b5-b6-b7`), `$78 >> 3`. Records 3 and 10 (`$09B7`, `$00B9`,
    # bounds 4 and 3) are among them.
    bounds = {(int(i.name.split(":")[1].split("-")[0], 16) & 0x78) >> 3
              for i in song.instruments if i.vib_ptr}
    assert {3, 4} <= bounds
    cmps = {st[_block(wt, s)[1] - 1][0] & 0x7F for s in loops}
    assert cmps <= {b - 2 for b in bounds} and {1, 2} <= cmps, (cmps, bounds)


@needs_corpus
@pytest.mark.skipif(not pathlib.Path(
    __import__("fidelity").SIDDUMP).exists(), reason="no siddump")
def test_mega_apocalypse_00b9_swings_on_every_frame_after_its_gate(tmp_path):
    """siddump of the packed conversion, 40 s: from the gate (frame 12 after
    the attack) every frame of a long `$00B9` note moves the pitch, as the
    original's does (`246 123 0 -139 0 155 342 171 0 ...` -- the `0`s are
    the counter crossing the note, still a move from the frame before);
    under `4xy` rows one frame in three held."""
    fidelity, opts, sng, _ = _mega()
    sng, _ = fidelity.legalise_restarts(bytes(sng))
    packed = fidelity.pack_sid(sng, tmp_path, fidelity.GT2RELOC, 1)
    assert packed is not None
    trace = fidelity.run_siddump(packed, 40, 0, fidelity.SIDDUMP, calls=1)
    nf = 40 * 50
    held = moved = notes = 0
    for v in trace:
        fq = fidelity.register_timeline(v.freq_events, nf)
        ad = fidelity.register_timeline(v.adsr_events, nf)
        atk = sorted(v.attack_frames)
        for j, f0 in enumerate(atk):
            end = atk[j + 1] if j + 1 < len(atk) else nf
            if ad[f0] != 0x00B9 or end - f0 < 30:
                continue
            notes += 1
            for f in range(f0 + 13, f0 + 28):
                if fq[f] != fq[f - 1]:
                    moved += 1
                else:
                    held += 1
    assert notes >= 3, notes
    assert held == 0, (held, moved)
