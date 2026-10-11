"""The shared pulse-phase layout on a record that is neither "chained" nor
"plain": 5_Title_Tunes' SECOND pulse table, record 2.

Record 2 sweeps $800-$E00 at speed 6 on a step-32 lattice, so its band is
not a whole number of steps and only 8 of its 18 phases sit on the lattice
(`_chained_phases`); the others arrive off their bound. `_union_kind` is
None for it. At 8586101 `_phase_block(share=True)` chained those 8 phases
anyway, and the shared layout played 10 of the table's 37 index entries --
all of them record 2's -- off the per-phase widths: an off-bound piece ran
into a chained leg's set row and was snapped onto the lattice there. Under
`prefer_short` (a compilation) that layout would ship; the first table's
pair (record 3 "plain" / 6 "chained", test_pulse_phase_union.py) is the
other half of the same rule.

Since v0.5.512 `_phase_block` chains a record only when its kind is
"chained", so a None record lays its per-phase loop and pieces, row for row.
The tests pin that: the table played entry by entry, the block itself, and
the selection `prefer_short` makes.

Figures measured under forced `pulse_phase` at 0d18fce (v0.5.524).
"""
from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from test_pulse_phase import _play_pulse_table  # noqa: E402
from test_pulse_phase_union import _CALLS, _layouts, _table_calls  # noqa: E402

_NAME = "5_Title_Tunes.sid"


def _second_tables() -> list:
    """Every call that lays the 37-entry table (records 1 and 2)."""
    out = [a for a in _table_calls(_NAME) if set(a[5]) == {1, 2}]
    assert out, "5_Title_Tunes lays no two-record phase table"
    return out


def _record2(args: tuple) -> tuple:
    """(params tail, want_set) of the table's record 2."""
    from h2g.goatwriter import pulse as P
    sid, det, iu, pulse, mult, phases, _, lead = args
    num = 2
    params = P._phase_sweep_params(sid, det, num - 1 - lead, mult)
    return params, set(phases[num]) | {(params[0], +1)}


def test_record_2_is_neither_chained_nor_plain():
    from h2g.goatwriter import pulse as P
    for args in _second_tables():
        params, want = _record2(args)
        assert params[1:] == (6, 2048, 3584, False, 32), params
        assert len(want) == 18
        assert len(P._chained_phases(want, *params[1:])) == 8
        assert P._union_kind(want, *params[1:]) is None


def test_shared_layout_plays_every_entry_of_the_second_table_per_phase():
    """All 37 index entries (records 1 and 2) and both records' own start
    pointers play, over 3200 calls, the widths the unlimited per-phase layout
    plays. At 8586101: 10 of the 37 off, all record 2's."""
    for args in _second_tables():
        shared, ref = _layouts(args)
        entries, starts, index = shared[0], shared[1], shared[2]
        assert len(index) == 37 and set(index) == set(ref[2])
        assert {k[0] for k in index} == {1, 2}
        off = [key for key, at in index.items()
               if _play_pulse_table(entries, at, _CALLS)
               != _play_pulse_table(ref[0], ref[2][key], _CALLS)]
        assert off == [], off
        for num in (1, 2):
            assert (_play_pulse_table(entries, starts[num - 1], _CALLS)
                    == _play_pulse_table(ref[0], ref[1][num - 1], _CALLS)), num


def test_prefer_short_ships_the_shared_layout_and_it_plays_per_phase():
    """The selection the task feared: a compilation's `prefer_short` takes
    the shared layout (154 rows against 177), and what ships plays the
    per-phase widths."""
    from h2g.goatwriter import pulse as P
    for args in _second_tables():
        ref = _layouts(args)[1]
        shipped = P.build_pulse_phase_table(*args, prefer_short=True)
        assert shipped is not None
        entries, starts, index = shipped
        assert (len(entries), len(ref[0])) == (154, 177)
        for key, at in index.items():
            assert (_play_pulse_table(entries, at, _CALLS)
                    == _play_pulse_table(ref[0], ref[2][key], _CALLS)), key


def test_a_none_kind_record_is_laid_as_its_own_per_phase_block():
    """The mechanism, one level down: for record 2 `_phase_block(share=True)`
    is `share=False` row for row (no chained leg is laid), while a "chained"
    record's two layouts differ -- so the gate, not luck, keeps the entries
    on their widths."""
    from h2g.goatwriter import pulse as P
    for args in _second_tables():
        params, want = _record2(args)
        speed, lo_v, hi_v, wrap, step = params[1:]
        mk = lambda share: P._phase_block(  # noqa: E731
            10, 2, want, params[0], speed, lo_v, hi_v, wrap, step, share)
        assert mk(True) == mk(False)
        sid, det, iu, pulse, mult, phases, _, lead = args
        p1 = P._phase_sweep_params(sid, det, 1 - 1 - lead, mult)
        w1 = set(phases[1]) | {(p1[0], +1)}
        assert P._union_kind(w1, *p1[1:]) == "chained"
        b = lambda share: P._phase_block(  # noqa: E731
            10, 1, w1, p1[0], *p1[1:], share)
        assert b(True)[0] != b(False)[0]
