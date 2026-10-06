"""The phase table's static reserve (`build_pulse_phase_table`, `reserve`).

Under forced `pulse_phase`, Last_V8 and its C128 version used to ship a
pulse table with 14 records degraded and 12 of them on pointer 0 -- no
width at all: the phase blocks for instruments 2/7/8/9 were laid before
the static blocks of the records after them, which then ran out of table.
The rescue lays the table again holding back every later record's static
width before a record may spend rows on a sweep or a phase block, and ships
it only where the layout without the reserve left a record on pointer 0.
Measured at 8586101 + this change: shared ramps, 223 rows (224 on the C128
version), instruments 2, 7 and 8 keep their phases and 9 alone degrades --
its shared block asks 47 rows where 32 are left, which is the budget that
forbids it. Under presets nothing moves (no shipped preset leaves a record
on pointer 0).

The reserve must be EXACT, not merely safe: it holds back only rows the
later records will really take. Swept over every table limit from the
statics-only length to 255, both layouts, the reserved table equals the
plain one wherever the plain one degrades nothing, and leaves no record on
pointer 0 at any limit. Each refinement of `held_back` -- reuse of a static
already laid, of one pending, of the one being laid, and the skip of union
members -- is what one of those files needs; without it the reserve
degrades records that fit (Phantoms at a 59-row limit: 5)."""
from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from test_pulse_phase import (_OVERFLOWING, _forced_pulse_phase_logs,  # noqa: E402
                              _forced_table_args, _play_pulse_table)

_CALLS = 3200
_LAST_V8 = {"Last_V8.sid": 223, "Last_V8_C128_version.sid": 224}


def _unlimited(args: tuple):
    import h2g.goatwriter as G
    sid, det, iu, pulse, mult, phases, _, lead = args
    limit = G.GT_MAX_TABLELEN
    G.constants.GT_MAX_TABLELEN = 10 ** 6
    try:
        return G._lay_pulse_phase_table(sid, det, iu, pulse, mult, phases,
                                        None, lead, False)
    finally:
        G.constants.GT_MAX_TABLELEN = limit


def test_last_v8_sets_every_records_width_under_forced_pulse_phase():
    """0 records on pointer 0 where 12 were; the one degraded record is
    instrument 9, and the figures that keep it out are printed: its shared
    block against the rows left after the 223 laid."""
    import h2g.goatwriter as G
    from h2g.goatwriter import _phase_block, _phase_sweep_params
    for name, rows in _LAST_V8.items():
        args, table = _forced_table_args(name)
        sid, det, iu, pulse, mult, phases, _, lead = args
        assert table is not None, name
        entries, starts, index = table
        assert len(entries) == rows, (name, len(entries))
        assert 0 not in starts[lead:], (name, starts)
        assert {k[0] for k in index} == {2, 7, 8}, (name, sorted(index))
        params = _phase_sweep_params(sid, det, 9 - 1 - lead, mult)
        want = set(phases[9]) | {(params[0], +1)}
        need = len(_phase_block(0, 9, want, *params, share=True)[0])
        assert need == 47 and need > G.GT_MAX_TABLELEN - rows, (name, need, rows)
        lines = _forced_pulse_phase_logs(name)
        assert not any("SET NO WIDTH AT ALL" in l for l in lines), lines
        assert ("*** PULSE TABLE FULL UNDER --pulse-phase -- 1 INSTRUMENT(S) "
                "LOSE THEIR PHASE ENTRIES ***") in lines, lines
        assert any(l.startswith("Pulse phase.............: statics reserved -- "
                                f"shared ramps, {rows} table row(s) place 3 of 4")
                   for l in lines), lines


def test_reserved_layout_plays_what_the_unlimited_table_plays():
    """Every CMD_SETPULSEPTR target and every record pointer plays, call for
    call over 3200 calls, what the same one plays from the per-phase layout
    with no table limit -- except instrument 9, which plays its own record
    width and holds it (the static fallback)."""
    for name in _LAST_V8:
        args, (entries, starts, index) = _forced_table_args(name)
        lead = args[7]
        ref = _unlimited(args)
        assert ref[3] == 0, name
        for key, at in index.items():
            assert (_play_pulse_table(entries, at, _CALLS)
                    == _play_pulse_table(ref[0], ref[2][key], _CALLS)), (name, key)
        for k, (a, b) in enumerate(zip(starts[lead:], ref[1][lead:])):
            num = k + 1 + lead
            got = _play_pulse_table(entries, a, _CALLS)
            want = _play_pulse_table(ref[0], b, _CALLS)
            if num == 9:
                assert got == [want[0]] * _CALLS, (name, num, got[:4], want[:4])
            else:
                assert got == want, (name, num)


def test_reserve_is_not_consulted_where_no_record_lost_its_width():
    """A rescue: the files whose table overflows but leaves every record a
    width (Gremlins and Human_Race degrade one record each to a static width;
    the rest fit shared) ship exactly what they shipped, with no `statics
    reserved` line."""
    for name in list(_OVERFLOWING) + ["Gerry_the_Germ.sid"]:
        lines = _forced_pulse_phase_logs(name)
        assert not any("statics reserved" in l for l in lines), (name, lines)
        assert not any("SET NO WIDTH AT ALL" in l for l in lines), (name, lines)


# Files whose forced tables need every refinement of `held_back`: with any
# one removed, the reserved layout degrades a record the plain layout fits
# at some limit (measured at 8586101 + this change, every corpus file that
# reaches the table swept the same way: the same four, and no other).
_TIGHT = ["Phantoms_of_the_Asteroid.sid", "Game_Killer.sid",
          "Master_of_Magic.sid", "Battle_of_Britain.sid"]


def _sweep_limits(name: str):
    """(share, limit, plain, reserved) for every table limit from the
    statics-only length to GT_MAX_TABLELEN, both layouts."""
    import h2g.goatwriter as G
    from h2g.goatwriter import pulse as P
    args, _ = _forced_table_args(name)
    sid, det, iu, pulse, mult, phases, _, lead = args
    limit = G.GT_MAX_TABLELEN
    try:
        for share in (False, True):
            G.constants.GT_MAX_TABLELEN = limit
            floor = len(P._lay_pulse_phase_pass(sid, det, iu, False, mult, {},
                                                None, lead, share, {})[0])
            for cap in range(floor, limit + 1):
                G.constants.GT_MAX_TABLELEN = cap
                plain = P._lay_pulse_phase_table(sid, det, iu, pulse, mult,
                                                 phases, None, lead, share)
                held = P._lay_pulse_phase_table(sid, det, iu, pulse, mult,
                                                phases, None, lead, share,
                                                reserve=True)
                yield share, cap, plain, held
    finally:
        G.constants.GT_MAX_TABLELEN = limit


def test_the_reserve_holds_back_only_rows_later_records_take():
    """Wherever the plain layout degrades nothing, the reserved layout is
    that layout, entry for entry, at every limit: the reserve never costs a
    record that fits its movement."""
    for name in _TIGHT:
        checked, miss = 0, []
        for share, cap, plain, held in _sweep_limits(name):
            if plain[3]:
                continue
            checked += 1
            if held[:3] != plain[:3]:
                miss.append((share, cap, held[3], held[4]))
        assert checked > 50, (name, checked)
        assert not miss, (name, miss[:4])


def test_the_reserve_leaves_no_record_without_a_width_at_any_limit():
    """The rescue's promise: while the statics alone fit, no record reaches
    pointer 0 -- at every limit down to the statics-only length."""
    for name in _TIGHT + list(_LAST_V8):
        silent = [(share, cap, held[4])
                  for share, cap, _, held in _sweep_limits(name) if held[4]]
        assert not silent, (name, silent[:4])
