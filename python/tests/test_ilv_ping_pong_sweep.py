"""The interleaved filter sweep is a ping-pong, and the table turns it round.

The player moves a 16-bit cutoff accumulator by the record's `+2/+3` every
frame, pins it at the limit it crosses (`+4` going up, `+5` going down) and
turns it back (Lion_Heart `$15F9-$1661`). This used to emit ONE modulation row
of 127 calls in the start direction, which ran past the limit and wrapped the
8-bit cutoff: Lion_Heart's `$4E` stepping down 127 calls lands on `$CF`, and
its `cut` read 1.7355, Go_Go_Dash's 3.2460. It now emits the first leg to the
limit and a two-leg loop closed by a jump row (`goatwriter.filters._ilv_sweep`).

`_player` and `_table` below are independent transcriptions of the two loops
(the player's, and gplay.c:253-296 for the Goattracker filter table), so the
test compares behaviours, not the emitter's own arithmetic.
"""
import json
import pathlib

import pytest

from corpus import CORPUS, needs_corpus  # noqa: E402
from h2g.goatwriter import FILT_MODULATE, FILT_SET_CUTOFF, FILT_STOP
from h2g.goatwriter.filters import (_ilv_sweep, _ilv_sweep_resolve,
                                    ILV_SWEEP_MAX_STEP)

PYTHON_ROOT = pathlib.Path(__file__).resolve().parents[1]

# (program bytes read from the file's filter table, the shipped multiplier)
PROGRAMS = {
    "Lion_Heart": (bytes.fromhex("4E 03 03 A7 72 1D 03 30"), 3),
    "Go_Go_Dash": (bytes.fromhex("20 E9 0F FF 24 00 06 50"), 4),
    "Radio_ACE": (bytes.fromhex("AD 18 02 95 65 08 01 40"), 1),
    "Pacific_Coast": (bytes.fromhex("18 61 0B 71 3B 00 83 F0"), 1),
    "Sun_Never_Shines_2": (bytes.fromhex("5D DD 0D C8 7B 0F 83 F0"), 1),
    "Sun_Never_Shines_8": (bytes.fromhex("24 91 00 AE 4F 06 03 80"), 1),
}


def _player(prog: bytes, frames: int) -> list:
    """The cutoff HIGH byte per frame, the flush reading it before the sweep
    steps (`$15F9`): the start value first. `+6` bit 7 SET is up."""
    hi, lo = prog[0], prog[1]
    step = prog[2] << 8 | prog[3]
    upper, lower = prog[4], prog[5]
    up = bool(prog[6] & 0x80)
    out = []
    for _ in range(frames):
        out.append(hi)
        acc = hi << 8 | lo
        if up:
            acc += step
            if acc > 0xFFFF or acc >> 8 >= upper:
                hi, lo, up = upper, 0, False
            else:
                hi, lo = acc >> 8, acc & 255
        else:
            acc -= step
            if acc < 0 or acc >> 8 <= lower:
                hi, lo, up = lower, 0, True
            else:
                hi, lo = acc >> 8, acc & 255
    return out


def _rows(prog: bytes, mult: int, level: int = 0) -> list:
    """The table a program is emitted as: params, cutoff, then the sweep."""
    return [(0x80, 0x00), (FILT_SET_CUTOFF, prog[0])] + _ilv_sweep_resolve(
        _ilv_sweep(prog, mult, level), 3)


def _table(rows: list, calls: int) -> list:
    """The cutoff after each play call, gplay.c:253-296 (1-based pointer)."""
    ptr, time, cut = 1, 0, 0
    out = []
    for _ in range(calls):
        if ptr:
            if rows[ptr - 1][0] == FILT_STOP:
                ptr = rows[ptr - 1][1]
        if ptr and not time:
            left, right = rows[ptr - 1]
            if left >= 0x80:
                ptr += 1
                if rows[ptr - 1][0] == 0x00:
                    cut = rows[ptr - 1][1]
                    ptr += 1
            elif left:
                time = left
            else:
                cut = right
                ptr += 1
        if time:
            right = rows[ptr - 1][1]
            cut = (cut + (right - 256 if right >= 128 else right)) & 255
            time -= 1
            if not time:
                ptr += 1
        out.append(cut)
    return out


def _peaks(series: list) -> int:
    """Turn-arounds from rising to falling, plateaus counted once."""
    n = 0
    prev = 0
    for a, b in zip(series, series[1:]):
        d = (b > a) - (b < a)
        if d < 0 < prev:
            n += 1
        if d:
            prev = d
    return n


@pytest.mark.parametrize("name", sorted(PROGRAMS))
def test_the_table_stays_between_the_limits_and_never_wraps(name):
    """SABOTAGE TARGET: emit the old single `(FILT_MODULATE, per_call)` row.
    Lion_Heart then runs $4E down 127 calls and wraps to $CF, far above its
    $72 upper limit."""
    prog, mult = PROGRAMS[name]
    upper, lower = prog[4], prog[5]
    if not prog[2] << 8 | prog[3]:
        pytest.skip("static program")
    frames = 400
    got = _table(_rows(prog, mult), frames * mult)
    # +/- one per-frame step of slack for a leg that ends mid-frame.
    slack = ((prog[2] << 8 | prog[3]) >> 8) + 1
    assert max(got) <= max(upper, prog[0]) + slack, (name, max(got))
    assert min(got) >= max(min(lower, prog[0]) - slack, 0), (name, min(got))


@pytest.mark.parametrize("name", ["Lion_Heart", "Go_Go_Dash", "Radio_ACE",
                                  "Pacific_Coast", "Sun_Never_Shines_2"])
def test_the_table_turns_as_often_as_the_player(name):
    """SABOTAGE TARGET: close the sweep with `(FILT_STOP, 0x00)` instead of
    the jump row, or build each leg with `frames` rather than
    `frames * multiplier` calls. The first leaves one leg and no peak, the
    second turns `mult` times as fast."""
    prog, mult = PROGRAMS[name]
    frames = 600
    want = _peaks(_player(prog, frames))
    assert want >= 2, "the program must turn within the window to test this"
    calls = _table(_rows(prog, mult), frames * mult)
    got = _peaks([calls[f * mult + mult - 1] for f in range(frames)])
    assert abs(got - want) <= max(1, want // 10), (name, got, want)


@pytest.mark.parametrize("name", sorted(PROGRAMS))
def test_the_sweep_ends_in_a_jump_to_a_modulation_row_or_a_stop(name):
    """SABOTAGE TARGET: resolve the jump against the wrong base
    (`_ilv_sweep_resolve`): the target then points at a row that is not the
    loop's first."""
    prog, mult = PROGRAMS[name]
    rows = _rows(prog, mult)
    last = rows[-1]
    assert last[0] == FILT_STOP
    if last[1] == 0:
        assert not prog[2] << 8 | prog[3] or prog[4] <= prog[5]
        return
    target = rows[last[1] - 1]
    assert 3 <= last[1] < len(rows)
    assert 1 <= target[0] <= FILT_MODULATE, (name, target)
    # The loop is two legs: one rising, one falling.
    loop = rows[last[1] - 1:-1]
    signs = {(r[1] if r[1] < 128 else r[1] - 256) > 0 for r in loop if r[1]}
    assert signs == {True, False}, (name, loop)


def test_the_first_leg_runs_from_the_start_to_the_limit_it_heads_for():
    """Go_Go_Dash starts at $20 going down to 0 (`+6` bit 7 clear), Pacific
    starts at $18 going up to $3B: the first leg's travel is the distance to
    THAT limit, not the full range. SABOTAGE TARGET: start the loop at row 0
    of the sweep (`("jump", 0)`) and the first leg repeats."""
    for name, expect in (("Go_Go_Dash", -0x20), ("Pacific_Coast", 0x3B - 0x18),
                         ("Lion_Heart", -(0x4E - 0x1D))):
        prog, mult = PROGRAMS[name]
        sweep = _ilv_sweep(prog, mult)
        jump = sweep[-1][1]
        first = sweep[:jump]
        travel = sum(n * (r if r < 128 else r - 256) for n, r in first)
        assert travel == expect, (name, travel, expect)


def test_a_level_1_sweep_spends_fewer_rows_and_still_reaches_the_limits():
    """SABOTAGE TARGET: drop the `exact` branch so both levels are the same
    (the row count then matches) or let level 1 stop short of the limit."""
    prog, mult = PROGRAMS["Lion_Heart"]
    full = _ilv_sweep(prog, mult, 0)
    cheap = _ilv_sweep(prog, mult, 1)
    assert len(cheap) < len(full), (len(cheap), len(full))
    got = _table(_rows(prog, mult, 1), 400 * mult)
    assert max(got) >= prog[4] - 2 and min(got) <= prog[5] + 2, (min(got),
                                                                max(got))


def test_a_static_program_is_a_single_stop():
    prog = bytes.fromhex("E2 BD 00 00 FF 00 02 F0")      # Sun's program 12
    assert _ilv_sweep(prog, 1) == ((FILT_STOP, 0x00),)


def test_no_row_exceeds_the_tables_signed_step_or_time_range():
    for name, (prog, mult) in PROGRAMS.items():
        for level in (0, 1):
            for left, right in _ilv_sweep(prog, mult, level):
                if left in (FILT_STOP, "jump"):
                    continue
                signed = right if right < 128 else right - 256
                assert 0 <= left <= FILT_MODULATE or left == FILT_SET_CUTOFF
                assert abs(signed) <= ILV_SWEEP_MAX_STEP + 1, (name, left, right)


@needs_corpus
@pytest.mark.skipif(not pathlib.Path(
    __import__("fidelity").SIDDUMP).exists(), reason="no siddump")
@pytest.mark.parametrize("name,low,high", [("Lion_Heart", 0.8, 1.3),
                                           ("Go_Go_Dash", 0.6, 1.5)])
def test_cutoff_travel_is_near_the_originals(tmp_path, name, low, high):
    """siddump, -t 180 under presets, routed frames only. Before the ping-pong
    Lion_Heart read 1.7355 and Go_Go_Dash 3.2460 (18,042,624 and 12,786,688
    against 10,396,288 and 3,939,264); now 1.0777 and 0.7672.
    SABOTAGE TARGET: the single-row sweep puts both back out of range."""
    import fidelity as F
    from h2g.convert import convert
    doc = json.loads((PYTHON_ROOT.parent / "presets.json").read_text())
    sid = f"{name}.sid"
    opts = F._preset_opts(doc, sid)
    sub, our_sub, _ = F.resolve_pair(CORPUS / sid, "auto")
    nf = 180 * 50

    def travel(trace):
        f = trace.filter
        cut = F.register_timeline(f.cutoff_events, nf)
        return sum(abs(cut[i] - cut[i - 1]) for i in range(1, nf))

    local = tmp_path / sid
    local.write_bytes((CORPUS / sid).read_bytes())
    cal, _ = F.table_calibration(CORPUS / sid, opts)
    o_total = travel(F.run_siddump(local, 180, sub, F.SIDDUMP, cal))
    sng, _ = F.legalise_restarts(bytes(convert(str(CORPUS / sid),
                                               lambda m: None, **opts)))
    mult = F._preset_multiplier(doc, sid)
    packed = F.pack_sid(sng, tmp_path, F.GT2RELOC, mult)
    assert packed is not None
    u_total = travel(F.run_siddump(packed, 180, our_sub, F.SIDDUMP, 0,
                                   calls=mult))
    assert o_total > 0
    assert low < u_total / o_total < high, (u_total, o_total)


# ---- a record a pattern `$87` names keeps the one-row sweep -----------------

def _sid_det(name):
    from h2g.detect import detect
    from h2g.sidfile import load_sid
    sid = load_sid(str(CORPUS / f"{name}.sid"))
    return sid, detect(sid, lambda m: None)


def test_first_leg_is_the_pre_ping_pong_row_and_stops():
    from h2g.goatwriter.filters import _ilv_first_leg
    prog = bytes.fromhex("4E 03 03 A7 72 1D 03 30")        # Lion_Heart, down
    rows = _ilv_first_leg(prog, 3)
    assert rows[-1] == (FILT_STOP, 0x00)
    assert [r for r in rows if r[0] == FILT_MODULATE] == [(FILT_MODULATE, 0xFF)]   # -3/3
    assert _ilv_first_leg(bytes(8), 1) == ((FILT_STOP, 0x00),)


@needs_corpus
def test_the_records_pattern_command_87_names_are_exactly_the_census():
    """Census over the six ILV files (the only files with `ilv_filter`):
    $87 events, by record. SABOTAGE TARGET: return frozenset() and Sun's
    record 8 goes back to the ping-pong (test below)."""
    from h2g.goatwriter.filters import ilv_start_cutoff_records
    got = {n: set(ilv_start_cutoff_records(*_sid_det(n)))
           for n in ("Go_Go_Dash", "Lakers_vs_Celtics", "Lion_Heart",
                     "Pacific_Coast", "Radio_ACE", "Sun_Never_Shines")}
    assert got == {"Go_Go_Dash": {1}, "Lakers_vs_Celtics": set(),
                   "Lion_Heart": set(), "Pacific_Coast": set(),
                   "Radio_ACE": {8}, "Sun_Never_Shines": {8}}


@needs_corpus
def test_a_record_with_87_notes_is_not_turned_into_a_ping_pong():
    """Sun_Never_Shines' record 8 takes 119 `$87` start cutoffs, so the record's
    own start values are not the notes' (the bounded legs cost it `cut` 1.024
    -> 0.600 with record 8 alone gated, 0.585 ungated). Every program of the
    file stays one modulation row and a stop; Lion_Heart's and Go_Go_Dash's
    (whose one `$87` is on an unfiltered record) end in a jump.
    SABOTAGE TARGET: gating only the named record, or never gating."""
    from h2g.goatwriter.filters import _ilv_programs
    for name, mult in (("Sun_Never_Shines", 1), ("Radio_ACE", 1)):
        sid, det = _sid_det(name)
        progs = _ilv_programs(sid, det, det.instr_used, mult)
        assert progs, name
        for i, p in progs.items():
            assert p[3][-1] == (FILT_STOP, 0x00), (name, i)
            assert not any(r[0] == "jump" for r in p[3]), (name, i)
    for name, mult in (("Lion_Heart", 3), ("Go_Go_Dash", 4)):
        sid, det = _sid_det(name)
        progs = _ilv_programs(sid, det, det.instr_used, mult)
        assert progs and all(p[3][-1][0] == "jump" for p in progs.values()), name
