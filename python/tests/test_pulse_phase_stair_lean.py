"""The lean staircase (`goatwriter.STAIR_HEAD`): where the full staircase costs
a file records, an entry piece off the shared chain lays only its first step
as the player's staircase and the rest of its ramp as a slew.

Opened by `human-race-pphase-94-1-00-poff`: Human_Race's staircase table
placed 3 of its 7 phase-tracked records in 253 rows where the slew placed 5 in
227, so `stair_costs_records` kept the slew (pphase .94, poff .799). 122 of the
$80-step union's 170 rows were three off-band pieces (phases at $000, $080 and
$800 going down), each a 16-31 step ramp at two rows a step. Laid lean the
table is 255 rows and places all five parity records: pphase 1.00, poff .837.
"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from test_pulse_phase import _play_pulse_table  # noqa: E402

from h2g.goatwriter import (STAIR_HEAD, _phase_block, held_stairs,  # noqa: E402
                            stair_costs_records)

LO, HI, STEP, SPEED = 0x800, 0xE00, 0x80, 0x40
OFF_BAND = (0x100, -1)


def _block(on: bool, head=None):
    want = {(w, d) for w in range(0x880, 0xE00, STEP) for d in (+1, -1)}
    want.add(OFF_BAND)
    with held_stairs(on, head=head):
        return _phase_block(0, 1, want, 0x880, SPEED, LO, HI, False, STEP,
                            share=True)


def test_the_lean_head_is_the_first_step_of_the_staircase():
    assert STAIR_HEAD == 2


def test_a_lean_off_band_piece_is_far_shorter_than_the_full_staircase():
    full, _ = _block(True)
    lean, _ = _block(True, STAIR_HEAD)
    slew, _ = _block(False)
    assert len(lean) < len(full) - 20
    assert len(lean) <= len(slew) + 8


def test_a_lean_piece_opens_on_the_players_first_step():
    """Its first calls are the full staircase's: the width held a call, then
    the step; only the ramp after them is a slew."""
    full, f_idx = _block(True)
    lean, l_idx = _block(True, STAIR_HEAD)
    got = _play_pulse_table(lean, l_idx[(1,) + OFF_BAND], 6)
    want = _play_pulse_table(full, f_idx[(1,) + OFF_BAND], 6)
    assert got[:STAIR_HEAD + 1] == want[:STAIR_HEAD + 1]
    assert got[1] == got[0] and got[2] == (got[0] - STEP) & 0xFFF
    # ... and then the slew at the mean rate: half a step a call.
    assert got[3] == (got[2] - SPEED) & 0xFFF


def test_the_chained_legs_stay_the_full_staircase():
    """An in-band entry is on the shared chain, where every lattice width is
    an entry: the lean layout plays it exactly as the full one does."""
    full, f_idx = _block(True)
    lean, l_idx = _block(True, STAIR_HEAD)
    for w in range(0x900, 0xD80, STEP):
        for d in (+1, -1):
            assert (_play_pulse_table(lean, l_idx[(1, w, d)], 14)
                    == _play_pulse_table(full, f_idx[(1, w, d)], 14)), (
                        hex(w), d)


def _convert_spy(name: str):
    from test_pulse_phase_union import _corpus_and_presets
    corpus, doc = _corpus_and_presets()
    path = corpus / f"{name}.sid"
    if not path.exists():
        import pytest
        pytest.skip(f"{name} not in the corpus here")
    import fidelity
    from h2g import convert as C
    kwargs = fidelity._preset_opts(doc, f"{name}.sid")
    heads: list = []
    shipped: list = []
    real_held, real_index = C.held_stairs, C.parity_index

    def spy_held(on, head=None):
        heads.append(head)
        return real_held(on, head=head)

    def spy_index(entries, index, targets):
        shipped.append((entries, index))
        return real_index(entries, index, targets)
    C.held_stairs, C.parity_index = spy_held, spy_index
    try:
        C.convert(str(path), log=lambda m: None, **kwargs)
    finally:
        C.held_stairs, C.parity_index = real_held, real_index
    return heads, shipped


def test_human_race_ships_the_lean_staircase_with_all_five_records():
    heads, shipped = _convert_spy("Human_Race")
    assert heads[0] is None and STAIR_HEAD in heads, heads
    assert shipped, "the lean staircase did not ship"
    entries, index = shipped[0]
    assert len(entries) <= 255
    assert {k[0] for k in index} >= {1, 2, 4, 18, 23}


def test_a_file_whose_full_staircase_fits_never_lays_the_lean_one():
    heads, shipped = _convert_spy("5_Title_Tunes")
    assert heads and set(heads) == {None}, heads    # built twice, never lean
    assert shipped


def test_the_lean_staircase_is_only_a_rescue(monkeypatch):
    """With the lean layout short-circuited to the full one, Human_Race falls
    back to the slew exactly as before."""
    import h2g.convert as C
    monkeypatch.setattr(C, "STAIR_HEAD", None)
    heads, shipped = _convert_spy("Human_Race")
    assert not shipped
    assert heads and set(heads) == {None}, heads


def test_the_lean_table_is_judged_by_the_same_record_count():
    def table(*nums):
        return ([], [], {(n, 0x900, +1): 1 for n in nums})
    assert stair_costs_records(table(1, 2, 4), table(1, 2, 4, 18, 23))
    assert not stair_costs_records(table(1, 2, 4, 18, 23),
                                   table(1, 2, 4, 18, 23))
