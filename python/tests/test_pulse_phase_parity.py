"""A held staircase is entered on the delay counter's parity
(`goatwriter.parity_direction`, `build_pulse_phase_table`'s `_resolve_parity`).

Opened by `five-title-tunes-phase-stair-parity`: 5_Title_Tunes' players 3 and
6 hold each width two ticks and then step $80, on a delay counter that
free-runs across notes, so half the notes open with their first step one tick
after the fetch and half two. A slew at the mean rate was half a step off on
both (pphase 0.90: the buckets read one frame after the attack never matched);
a held staircase on one parity was right for half the notes and cost poff
(.929 -> .899). Keyed on the parity both are right.
"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from test_pulse_phase import _play_pulse_table  # noqa: E402

from h2g.goatwriter import (PARITY_B, PulsePhaseSim, PulseVoiceCell,  # noqa: E402
                            _phase_block, base_direction, held_stairs,
                            is_held_stair, is_hold, is_parity,
                            parity_direction, stair_costs_records)
from h2g.patterns import Counter0Phase  # noqa: E402
from h2g.goatwriter.pulse import _held_ramp_rows, _parity_pointer  # noqa: E402

LO, HI, STEP, SPEED = 0x800, 0xE00, 0x80, 0x40


def test_a_parity_direction_is_a_direction_and_never_a_hold():
    for d in (+1, -1):
        p = parity_direction(d)
        assert is_parity(p) and not is_parity(d)
        assert not is_hold(p) and (p > 0) == (d > 0)
        assert base_direction(p) == d == base_direction(d)
        assert abs(p) >= PARITY_B
    assert parity_direction(+1) != parity_direction(-1)


def test_only_a_step_of_two_speeds_and_a_wide_lattice_is_a_held_stair():
    assert is_held_stair(0x80, 0x40) and is_held_stair(0xE0, 0x70)
    assert not is_held_stair(0x80, 0x20)       # four calls a step
    assert not is_held_stair(0x40, 0x20)       # a fine lattice: too many rows
    assert not is_held_stair(0x80, 0) and not is_held_stair(None, 0x40)


def _stair_block():
    want = {(w, d) for w in range(0x880, 0xE00, STEP) for d in (+1, -1)}
    with held_stairs(True):
        return _phase_block(0, 1, want, 0x880, SPEED, LO, HI, False, STEP,
                            share=True)


def _original(w: int, d: int, counter: int, calls: int) -> list:
    """The widths the player shows from the attack frame on: the fetch tick
    writes `w`, every later tick counts the delay down (delay 2)."""
    sim = PulsePhaseSim(w, STEP, 2, LO >> 8, HI >> 8, PulseVoiceCell(d, counter))
    out = [w]
    for _ in range(calls - 1):
        sim.advance(1)
        out.append(sim.width)
    return out


def test_the_chain_is_the_originals_staircase_from_a_counter_one_note():
    rows, index = _stair_block()
    for w in range(0x900, 0xD80, STEP):
        for d in (+1, -1):
            assert (_play_pulse_table(rows, index[(1, w, d)], 8)
                    == _original(w, d, 1, 8)), (hex(w), d)


def test_a_counter_zero_note_enters_one_hold_row_early():
    """Its first call waits on the hold before the neighbour's set row, so
    from the second call it plays the original's counter-0 widths."""
    rows, index = _stair_block()
    for w in range(0x900, 0xD00, STEP):
        d = +1
        nxt = index[(1, w + STEP, d)]
        ptr = _parity_pointer(rows, nxt)
        assert ptr == nxt - 1 and rows[ptr - 1] == (1, 0), hex(w)
        ours = _play_pulse_table(rows, ptr, 8)
        assert ours[1:7] == _original(w, d, 0, 8)[1:7], (hex(w), ours)


def test_a_set_row_with_no_hold_before_it_keeps_its_entry():
    assert _parity_pointer([(0x89, 0x00), (0xFF, 1)], 1) == 1
    assert _parity_pointer([(0x89, 0x00), (1, 0), (0x89, 0x80)], 3) == 2
    assert _parity_pointer([(0x89, 0x00), (2, 0), (0x89, 0x80)], 3) == 3


def test_the_held_ramp_holds_one_call_between_set_rows():
    rows = [(0x89, 0x00)] + _held_ramp_rows(0x900, 5, +1, STEP, 2)  # direct
    assert [r for r in rows if r[0] == 1] == [(1, 0)] * 3
    assert _play_pulse_table(rows, 1, 6) == [0x900, 0x900, 0x980, 0x980,
                                             0xA00, 0xA00]


# --------------------------------------------------------------------------
# On the file
# --------------------------------------------------------------------------

def _five_title_tunes_parity():
    """(entries, index with the counter-0 keys, targets, convert's log) for
    5_Title_Tunes under its presets."""
    from test_pulse_phase_union import _corpus_and_presets
    corpus, doc = _corpus_and_presets()
    path = corpus / "5_Title_Tunes.sid"
    if not path.exists():
        import pytest
        pytest.skip("5_Title_Tunes not in the corpus here")
    import fidelity
    from h2g import convert as C
    kwargs = fidelity._preset_opts(doc, "5_Title_Tunes.sid")
    seen: list = []
    log: list = []
    real = C.parity_index

    def spy(entries, index, targets):
        out = real(entries, index, targets)
        seen.append((entries, out, targets))
        return out
    C.parity_index = spy
    try:
        C.convert(str(path), log=log.append, **kwargs)
    finally:
        C.parity_index = real
    assert seen, "no counter-0 note was planned"
    return seen[0] + (log,)


def test_5_title_tunes_plans_both_parities_for_its_wide_staircases():
    entries, index, targets, log = _five_title_tunes_parity()
    by_num: dict = {}
    for (num, w, d) in targets:
        by_num.setdefault(num, []).append((w, d))
    # Players 3 and 6 (step $80) plan counter-0 notes; player 5 (step $40,
    # a fine lattice) and everything else plan none.
    assert set(by_num) == {3, 6}
    for num, keys in by_num.items():
        early = 0
        for (w, d) in keys:
            ptr = index[(num, w, d)]
            wa, da = targets[(num, w, d)]
            if entries[ptr - 1] == (1, 0):
                early += 1
                # one hold row ahead of its neighbour's set row
                assert index[(num, wa, da)] == ptr + 1
        assert early >= len(keys) // 2, (num, early, len(keys))
    # The appended players keep their sweeps: the table this costs leaves
    # them room.
    assert not any("without pulse sweeps" in line for line in log)


def test_a_counter_zero_phase_is_the_plain_pair_with_a_flag():
    import copy
    ph = Counter0Phase(0x900, +1, True)
    assert ph == (0x900, +1) and hash(ph) == hash((0x900, +1))
    assert {ph, (0x900, +1)} == {(0x900, +1)}
    assert {(0x900, +1): 5}[ph] == 5
    assert copy.deepcopy(ph).counter0 is True
    assert Counter0Phase(0x900, -1).counter0 is False


def test_the_staircase_ships_only_where_it_keeps_every_record_the_slew_kept():
    def table(*nums):
        return ([], [], {(n, 0x900, +1): 1 for n in nums})
    assert stair_costs_records(table(1, 2), table(1, 2, 3))
    assert not stair_costs_records(table(1, 2, 3), table(1, 2, 3))
    assert not stair_costs_records(table(1, 2, 3), table(1, 2))
    # weighed by the notes each record sounds: three records of no notes do
    # not outweigh the one that sounds
    usage = [0, 0, 100, 0, 0]
    assert stair_costs_records(table(3, 4), table(2), usage)
    assert not stair_costs_records(table(2), table(3, 4), usage)


def test_human_race_full_staircase_costs_it_records_so_the_lean_one_ships():
    """Its FULL staircase table places 3 of the 7 phase-tracked records in 253
    rows where the slew places 5 in 227, so it is not what ships: the lean
    staircase (`STAIR_HEAD`, tests/test_pulse_phase_stair_lean.py) is."""
    from test_pulse_phase_union import _corpus_and_presets
    corpus, doc = _corpus_and_presets()
    path = corpus / "Human_Race.sid"
    if not path.exists():
        import pytest
        pytest.skip("Human_Race not in the corpus here")
    import fidelity
    from h2g import convert as C
    kwargs = fidelity._preset_opts(doc, "Human_Race.sid")
    tried: list = []
    real_stair = C._build_stair_table

    def spy_stair(*a, **kw):
        out = real_stair(*a, **kw)
        tried.append(out)
        return out
    C._build_stair_table = spy_stair
    try:
        C.convert(str(path), log=lambda m: None, **kwargs)
    finally:
        C._build_stair_table = real_stair
    assert len(tried) == 2 and tried[0] is not None, "the staircase was never laid"
    full, lean = tried
    full_nums = {k[0] for k in full[2]}
    lean_nums = {k[0] for k in lean[2]}
    assert len(full_nums) == 3 and len(full[0]) == 253
    assert len(lean_nums) == 5 and len(lean[0]) <= 255
