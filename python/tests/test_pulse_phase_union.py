"""The shared pulse-phase layout's UNION BLOCKS (`_lay_pulse_phase_table`,
`_union_groups`, `_union_kind`).

Records whose sweeps agree on (speed, lo, hi, wrap) can share one
`_phase_block` laid over the union of their phase sets, each record's start
and index pointing into it. Three properties hold that up, one test each:

* every entry point the union ships plays, call for call, what the same
  phase plays from the unlimited per-phase layout -- including on
  5_Title_Tunes' first table, where records 3 and 6 share a sweep but not a
  `_union_kind`, and a union across kinds plays 22 of 56 entries off;
* a union is never taken where it silences a record -- on Gremlins both
  unions together put record 22 (1344 note rows) on pointer 0;
* the unions are taken where they help: fewer rows, fewer records degraded.

Figures measured under forced `pulse_phase` at be0aeb1 + this change.
"""
from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from test_pulse_phase import (_corpus_and_presets,  # noqa: E402
                              _play_pulse_table)

_CALLS = 3200


def _table_calls(name: str) -> list:
    """Every `build_pulse_phase_table` call convert.py makes on `name` under
    its presets with `pulse_phase` forced, as its positional arguments --
    a compilation makes one per player."""
    corpus, doc = _corpus_and_presets()
    path = corpus / name
    if not path.exists():
        import pytest
        pytest.skip(f"{name} not in the corpus here")
    import fidelity
    from h2g import convert as C
    kwargs = fidelity._preset_opts(doc, name)
    kwargs["pulse_phase"] = True
    calls: list = []
    real = C.build_pulse_phase_table

    def spy(*a, **kw):
        calls.append(a)
        return real(*a, **kw)
    C.build_pulse_phase_table = spy
    try:
        C.convert(str(path), log=lambda m: None, **kwargs)
    finally:
        C.build_pulse_phase_table = real
    assert calls, f"{name} never reached the phase table"
    return calls


def _layouts(args: tuple) -> tuple:
    """(shared layout, unlimited per-phase reference) for one call."""
    import h2g.goatwriter as G
    from h2g.goatwriter import pulse as P
    sid, det, iu, pulse, mult, phases, _, lead = args
    shared = P._lay_pulse_phase_table(sid, det, iu, pulse, mult, phases,
                                      None, lead, True)
    limit = G.GT_MAX_TABLELEN
    G.constants.GT_MAX_TABLELEN = 10 ** 6
    try:
        ref = P._lay_pulse_phase_table(sid, det, iu, pulse, mult, phases,
                                       None, lead, False)
    finally:
        G.constants.GT_MAX_TABLELEN = limit
    assert ref[3] == 0, "the unlimited reference degraded"
    return shared, ref


def test_union_blocks_play_the_widths_each_record_played_alone():
    """Every file whose first table has a sweep group: each index entry of
    the shared layout, and each phase-tracked record's own pointer, plays
    over 3200 calls exactly the widths the same phase plays from the
    per-phase layout with no table limit. 5_Title_Tunes is the case that
    needs `_union_kind` (3 "plain" and 6 "chained" on one sweep)."""
    from h2g.goatwriter import pulse as P
    files = ["5_Title_Tunes.sid", "Battle_of_Britain.sid", "Commando.sid",
             "Flash_Gordon.sid", "Game_Killer.sid", "Gremlins.sid",
             "Human_Race.sid", "Master_of_Magic.sid",
             "Phantoms_of_the_Asteroid.sid", "Sanxion.sid", "Sigma_Seven.sid"]
    for name in files:
        args = _table_calls(name)[0]
        sid, det, iu, pulse, mult, phases, _, lead = args
        if name != "5_Title_Tunes.sid":   # its pair is the next test's
            assert P._union_groups(sid, det, iu, mult, phases, lead), name
        shared, ref = _layouts(args)
        entries, starts, index = shared[0], shared[1], shared[2]
        for key, at in index.items():
            assert (_play_pulse_table(entries, at, _CALLS)
                    == _play_pulse_table(ref[0], ref[2][key], _CALLS)), (name, key)
        for num in {k[0] for k in index}:
            assert (_play_pulse_table(entries, starts[num - 1], _CALLS)
                    == _play_pulse_table(ref[0], ref[1][num - 1], _CALLS)), (name, num)


def test_5_title_tunes_records_3_and_6_share_a_sweep_not_a_kind():
    """The pair the kind exists for: same (speed, lo, hi, wrap), different
    `_union_kind`, so `_union_groups` offers no union of them."""
    from h2g.goatwriter import pulse as P
    sid, det, iu, pulse, mult, phases, _, lead = _table_calls("5_Title_Tunes.sid")[0]
    params = {n: P._phase_sweep_params(sid, det, n - 1 - lead, mult) for n in (3, 6)}
    assert params[3][1:] == params[6][1:]
    kinds = {n: P._union_kind(set(phases[n]) | {(params[n][0], +1)}, *params[n][1:])
             for n in (3, 6)}
    assert kinds == {3: "plain", 6: "chained"}, kinds
    assert P._union_groups(sid, det, iu, mult, phases, lead) == {}


def test_no_union_silences_a_record():
    """Gremlins: unioning (3, 7) and (6, 20) together keeps 10 and 20 swept
    but puts record 22 -- 1344 note rows -- on pointer 0; (6, 20) alone keeps
    20 swept and degrades only 10, to its static width. The layout takes the
    one that silences nothing."""
    from h2g.goatwriter import pulse as P
    sid, det, iu, pulse, mult, phases, _, lead = _table_calls("Gremlins.sid")[0]
    groups = P._union_groups(sid, det, iu, mult, phases, lead)
    assert sorted(sorted(m) for m in groups.values()) == [[3, 7], [6, 20]]
    both = P._lay_pulse_phase_pass(sid, det, iu, pulse, mult, phases, None,
                                   lead, True, groups)
    assert [i + 1 for i, v in enumerate(both[1]) if v == 0] == [22]
    shared = P._lay_pulse_phase_table(sid, det, iu, pulse, mult, phases,
                                      None, lead, True)
    assert 0 not in shared[1], shared[1]
    assert (shared[4], shared[3]) == (0, 1)
    assert {k[0] for k in shared[2]} == {3, 6, 7, 20}


def test_unions_buy_rows_and_records():
    """Where a union helps it is taken: the shared layout's rows and the
    records it keeps swept, against the per-record shared layout (no union),
    which is what shipped before."""
    from h2g.goatwriter import pulse as P
    want = {  # name: ((rows, kept) with unions, (rows, kept) without)
        "Master_of_Magic.sid": ((103, {11, 14}), (172, {11, 14})),
        "Phantoms_of_the_Asteroid.sid": ((59, {1, 7, 16, 17}), (200, {1, 7, 16, 17})),
        "Battle_of_Britain.sid": ((147, {7, 8, 9, 10, 11, 15, 16}),
                                  (225, {7, 8, 9, 10, 11, 15, 16})),
        "Gremlins.sid": ((252, {3, 6, 7, 20}), (254, {3, 6, 7})),
        "Human_Race.sid": ((252, {1, 4, 18, 21, 23}), (249, {1, 4, 18, 21})),
    }
    for name, (with_u, without) in want.items():
        sid, det, iu, pulse, mult, phases, _, lead = _table_calls(name)[0]
        got = P._lay_pulse_phase_table(sid, det, iu, pulse, mult, phases,
                                       None, lead, True)
        alone = P._lay_pulse_phase_pass(sid, det, iu, pulse, mult, phases,
                                        None, lead, True, {})
        assert (len(got[0]), {k[0] for k in got[2]}) == with_u, name
        assert (len(alone[0]), {k[0] for k in alone[2]}) == without, name
        assert got[4] == 0 and alone[4] == 0, name
