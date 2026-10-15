"""Human_Race's instrument 20 cannot keep its pulse-phase entries: the table
is too small for its block beside any set of the others that is worth more.

Task `human-race-pulse-phase-record-20-block`, measured under forced
`pulse_phase` and Human_Race's own presets at 9c15f95 (v0.5.543). It opened
on "s4 voice 1 record 20 and s0 voice 1 record 2 have no phase entry"; at
this tree record 2 HAS one (the lockstep walk, the wrap ramps and the lattice
legs moved it) and the records without are 20 and 23. The shipped table is
245 of GT_MAX_TABLELEN (255) rows and places {1, 2, 4, 18, 21}.

What each test pins, in the order the argument goes:

* record 20 has no same-sweep partner, so no union block can share its
  loop -- the only union `_union_groups` finds in the file is {1, 2};
* its shared block is 166 rows for 82 phases, two a phase: every entry point
  must be its own set-width row (a pointer at a ramp row would continue from
  whatever width the voice last wrote) and two set rows on one leg are at
  least four speed steps apart, so a ramp row sits between them. 166 is the
  floor of that encoding, not a first draft;
* the whole plan asks 470 rows of 255, and the file's untracked records and
  static widths take 16 of them whatever is kept;
* of the 128 subsets of the seven tracked records, 66 fit and 8 hold record
  20; none of those 8 holds all of {1, 2, 4, 18, 21} (the nearest is 253
  rows with {1, 4, 20}). The best of them loses 734 note rows to a static
  width, where the shipped set loses 477 -- keeping 20 is a net loss by
  the notes sounded (`pulse_usage`), and keeping 20 AND 2 is worse still
  (at best {1, 2, 20}, 1415). The row model is checked against the real
  passes at both ends it reaches (245 shipped, 470 unlimited).

NOT claimed: that the shipped set is the best one. {1, 2, 4, 18, 23} fits in
220 rows and loses 437 notes against the shipped 477, because the pass lays
records in index order and 21 takes the rows 23 needed
(`test_a_better_set_exists_but_does_not_hold_record_20`). That is a different
lever (choose by notes sounded) and moves the listening, so it is pinned as
a fact here, not adopted.
"""
from __future__ import annotations

import itertools
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent))
from test_pulse_phase import _corpus_and_presets  # noqa: E402

_NAME = "Human_Race.sid"
_CACHE: dict = {}


def _forced():
    """(args, kwargs, table) of the one `build_pulse_phase_table` call
    convert.py makes on Human_Race under its presets with `pulse_phase`
    forced."""
    if "call" in _CACHE:
        return _CACHE["call"]
    corpus, doc = _corpus_and_presets()
    path = corpus / _NAME
    if not path.exists():
        pytest.skip(f"{_NAME} not in the corpus here")
    import fidelity
    from h2g import convert as C
    kwargs = fidelity._preset_opts(doc, _NAME)
    kwargs["pulse_phase"] = True
    cap: dict = {}
    real = C.build_pulse_phase_table

    def spy(*a, **kw):
        cap["args"], cap["kw"] = a, kw
        cap["table"] = real(*a, **kw)
        return cap["table"]
    C.build_pulse_phase_table = spy
    try:
        C.convert(str(path), log=lambda m: None, **kwargs)
    finally:
        C.build_pulse_phase_table = real
    assert "args" in cap, "Human_Race never reached the phase table"
    _CACHE["call"] = (cap["args"], cap["kw"], cap["table"])
    return _CACHE["call"]


class _Model:
    """Row cost of keeping a SUBSET of the tracked records swept, the rest on
    their static width, as `_lay_pulse_phase_pass` (share=True) lays them:
    the shared block of each kept record, one block over {1, 2} when both
    are kept, and the standalone-program reuse for every static."""

    def __init__(self):
        from h2g.goatwriter import pulse as P
        (self.sid, self.det, self.iu, self.pulse, self.mult, self.phases, _,
         self.lead), kw, _ = _forced()
        self.P = P
        usage = kw["usage"]
        self.nrec = self.iu - self.lead
        self.tracked: dict = {}
        for j in range(self.nrec):
            num = j + 1 + self.lead
            want = self.phases.get(num)
            params = (P._phase_sweep_params(self.sid, self.det, j, self.mult)
                      if want else None)
            if params:
                weight = usage[j] if j < len(usage) else 0
                self.tracked[num] = (j, set(want) | {(params[0], +1)},
                                     params, weight)

    def base_rows(self, keep) -> int:
        P = self.P
        seen: set = set()
        rows = 2
        for j in range(self.nrec):
            num = j + 1 + self.lead
            if num in self.tracked:
                if num in keep:
                    continue
                prog, loop = P._pulse_program(self.sid, self.det, j, False,
                                              self.mult)
            else:
                prog, loop = P._pulse_program(self.sid, self.det, j,
                                              self.pulse, self.mult)
            standalone = (loop is None
                          and all(l != 0xFF or r == 0 for l, r in prog))
            if standalone:
                if tuple(prog) in seen:
                    continue
                seen.add(tuple(prog))
            rows += len(prog) + (loop is not None)
        return rows

    def block_rows(self, keep) -> int:
        P = self.P
        total, done = 0, set()
        for num in sorted(keep):
            if num in done:
                continue
            _, ws, params, _ = self.tracked[num]
            if num in (1, 2) and 1 in keep and 2 in keep:
                union = self.tracked[1][1] | self.tracked[2][1]
                total += len(P._phase_block(0, 0, union, *self.tracked[1][2],
                                            share=True)[0])
                done |= {1, 2}
            else:
                total += len(P._phase_block(0, num, ws, *params,
                                            share=True)[0])
                done.add(num)
        return total

    def rows(self, keep) -> int:
        return self.base_rows(keep) + self.block_rows(keep)

    def lost(self, keep) -> int:
        return sum(w for n, (_, _, _, w) in self.tracked.items()
                   if n not in keep)

    def fitting(self):
        from h2g.goatwriter import constants as K
        nums = sorted(self.tracked)
        for r in range(len(nums) + 1):
            for S in itertools.combinations(nums, r):
                rows = self.rows(set(S))
                if rows <= K.GT_MAX_TABLELEN:
                    yield rows, set(S)


def _model() -> _Model:
    if "model" not in _CACHE:
        _CACHE["model"] = _Model()
    return _CACHE["model"]


_SHIPPED = {1, 2, 4, 18, 21}


def test_the_shipped_table_places_five_and_degrades_20_and_23():
    """The starting point: 245 rows, {1, 2, 4, 18, 21} swept, 20 and 23 on a
    static width, record 2 -- the title's second record -- among the swept."""
    from h2g.goatwriter import constants as K
    _, _, (entries, starts, index) = _forced()
    assert len(entries) == 245 <= K.GT_MAX_TABLELEN
    swept = {num for (num, _, _) in index}
    assert swept == _SHIPPED
    assert {20, 23}.isdisjoint(swept)
    assert any(num == 2 for (num, _, _) in index)


def test_record_20_sweeps_alone_so_no_union_can_share_its_loop():
    P = _model().P
    m = _model()
    key = {n: m.tracked[n][2][1:6] for n in m.tracked}
    assert set(m.tracked) == {1, 2, 4, 18, 20, 21, 23}
    assert key[20] == (16, 2048, 3584, False, 32)
    assert all(key[n] != key[20] for n in key if n != 20)
    groups = P._union_groups(m.sid, m.det, m.iu, m.mult, m.phases, m.lead)
    assert [sorted(v) for v in groups.values()] == [[1, 2]]


def test_record_20_block_is_two_rows_a_phase():
    """166 rows for 82 phases, shared. Every phase is a set-width row, and
    on one leg two of them are >= 4 speed steps apart, so a ramp row sits
    between each pair: the block cannot be shorter without dropping a
    phase."""
    m = _model()
    _, ws, params, _ = m.tracked[20]
    block, index = m.P._phase_block(0, 20, ws, *params, share=True)
    assert len(ws) == 82
    assert len(block) == 166
    setrows = [i for i, (l, r) in enumerate(block) if 0x80 <= l <= 0x8F]
    assert len(setrows) == 82
    assert sorted(index.values()) == [i + 1 for i in setrows]
    # no two set rows adjacent: a ramp (or the jump closing a leg) between
    assert all(b - a >= 2 for a, b in zip(setrows, setrows[1:]))
    # and the per-phase layout asked 250
    pp = m.P._phase_block(0, 20, ws, *params)[0]
    assert len(pp) == 250


def test_the_whole_plan_asks_470_rows_of_255():
    """Every tracked record swept: the model and the real unlimited pass
    agree on 470, 215 past the table."""
    from h2g.goatwriter import constants as K
    from h2g.goatwriter import pulse as P
    m = _model()
    assert m.base_rows(set()) == 16
    assert m.rows(set(m.tracked)) == 470
    saved = K.GT_MAX_TABLELEN
    K.GT_MAX_TABLELEN = 100000
    try:
        got = P._lay_pulse_phase_table(m.sid, m.det, m.iu, m.pulse, m.mult,
                                       m.phases, None, m.lead, True)
    finally:
        K.GT_MAX_TABLELEN = saved
    assert (len(got[0]), got[3], got[4]) == (470, 0, 0)
    assert 470 - saved == 215
    # the model's row count of the shipped layout is the real one
    assert m.rows(_SHIPPED) == 245


def test_no_set_holding_20_keeps_what_the_shipped_table_keeps():
    """Of the 128 subsets of the tracked records, the 66 that fit; the ones
    holding 20 lose more notes to a static width than the shipped set."""
    m = _model()
    fits = list(m.fitting())
    assert len(fits) == 66
    shipped_lost = m.lost(_SHIPPED)
    assert shipped_lost == 477
    with20 = [(rows, S) for rows, S in fits if 20 in S]
    assert len(with20) == 8
    # none of them holds the five the shipped table holds
    assert all(not _SHIPPED <= S for _, S in with20)
    # and every one of them costs more notes than the shipped set
    assert min(m.lost(S) for _, S in with20) == 734
    assert all(m.lost(S) > shipped_lost for _, S in with20)
    best = min(with20, key=lambda t: m.lost(t[1]))
    assert (best[0], best[1]) == (253, {1, 4, 20})
    # record 2 AND record 20 together: at best {1, 2, 20} (237 rows)
    both = [(rows, S) for rows, S in with20 if 2 in S]
    assert min(m.lost(S) for _, S in both) == 1415
    assert sorted((rows, sorted(S)) for rows, S in both) == [
        (237, [1, 2, 20]), (237, [2, 20])]


def test_a_better_set_exists_but_does_not_hold_record_20():
    """Not adopted: {1, 2, 4, 18, 23} is 220 rows and loses 437 notes where
    the index-order pass ships {1, 2, 4, 18, 21} at 477, because 21 (173
    notes) takes the 86 rows 23 (213) needed. Record 20 (264 notes) is in
    neither."""
    m = _model()
    fits = list(m.fitting())
    best = min(fits, key=lambda t: (m.lost(t[1]), t[0]))
    assert best == (220, {1, 2, 4, 18, 23})
    assert m.lost(best[1]) == 437
    assert 20 not in best[1]
    assert {n: m.tracked[n][3] for n in m.tracked} == {
        1: 48, 2: 132, 4: 813, 18: 216, 20: 264, 21: 173, 23: 213}
