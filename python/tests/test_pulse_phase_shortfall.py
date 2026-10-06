"""What Gremlins 10's sweep is short of in the shared pulse-phase layout, and
why the records `drop_unnamed_instruments` removes do not supply it.

The comment above `_lay_pulse_phase_pass` states the measurement; each test
here pins one clause of it, under each file's presets with `pulse_phase`
forced, measured at 8586101 (v0.5.511):

* the 11 records the drop removes from Gremlins cost the shared pass no
  rows, because `reuse` already points each at an earlier named record's
  copy -- laying nothing for them leaves every union subset's row count as
  it was;
* both union groups need 258 rows, 3 past GT_MAX_TABLELEN, so record 22
  (the file's most played) would reach pointer 0, and the shipped table
  keeps 10 on a static width;
* every record still holding rows sounds notes, and only laying record 9's
  or 15's sweep as its static width closes the 3 rows -- a trade;
* on Last_V8 (and its C128 version) the same skip would have been a loss
  against the layout without the statics reserve: the pointer-0 records it
  "rescues" (22-33) sound nothing, and the layout it prefers silences 16
  and 17. Re-measured once the reserve was merged: the shipped table has
  no pointer-0 record left (223 / 224 rows, 2, 7 and 8 swept, 9 degraded),
  the skip as built would still silence 16 and 17 and so is no longer
  adopted, and under the reserve it would keep the same records swept and
  save only 12 rows.

The Gremlins clauses are unchanged by the reserve: its chosen layout puts
no record on pointer 0, so `build_pulse_phase_table` never lays it again.

They are NOT unchanged by the triangle's wrap ramps (`_leg_ramps`): record
10's 12 phases outside the band now ramp through the 12-bit wrap, its block
grows from 92 to 113 rows, it degrades in every layout, and both unions fit
with 22 kept (168 rows; `test_pulse_phase_union.py` pins that). So every
test here lays the table as it was measured, with the triangle's entry
ramps clamped (`_the_clamp`); Last_V8 has no phase outside the band, so the
clamp changes nothing there.
"""
from __future__ import annotations

import itertools
import re
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent))
from test_pulse_phase import _corpus_and_presets  # noqa: E402

_CACHE: dict = {}


@pytest.fixture(autouse=True)
def _the_clamp(monkeypatch):
    """The table these clauses were measured on: the triangle's entry ramps
    clamped at the bound, as `_phase_block` laid them before `_leg_ramps`
    (its step-less reading). `_CACHE` only ever holds captures taken under
    it."""
    from h2g.goatwriter import pulse as P
    real = P._leg_ramps
    monkeypatch.setattr(P, "_leg_ramps", lambda w, d, lo_v, hi_v, wrap, step:
                        real(w, d, lo_v, hi_v, wrap, None))


def _capture(name: str) -> dict:
    """convert.py's `build_pulse_phase_table` arguments and result, the
    patterns and tracks it hands `apply_pulse_phase` (the phase-time
    instrument columns), and the finished file's drop log."""
    if name in _CACHE:
        return _CACHE[name]
    corpus, doc = _corpus_and_presets()
    path = corpus / name
    if not path.exists():
        pytest.skip(f"{name} not in the corpus here")
    import fidelity
    from h2g import convert as C
    kwargs = fidelity._preset_opts(doc, name)
    kwargs["pulse_phase"] = True
    cap: dict = {}
    real_build, real_apply = C.build_pulse_phase_table, C.apply_pulse_phase

    def build(*a, **kw):
        cap.setdefault("args", a)
        cap.setdefault("table", real_build(*a, **kw))
        return cap["table"]

    def apply(patterns, tracks, *a, **kw):
        cap.setdefault("patterns", [list(p) for p in patterns])
        cap.setdefault("tracks", [list(t) for t in tracks])
        return real_apply(patterns, tracks, *a, **kw)
    logs: list = []
    C.build_pulse_phase_table, C.apply_pulse_phase = build, apply
    try:
        C.convert(str(path), log=logs.append, **kwargs)
    finally:
        C.build_pulse_phase_table, C.apply_pulse_phase = real_build, real_apply
    assert "args" in cap and "patterns" in cap, f"{name} shipped no phase table"
    dropped: set = set()
    for line in logs:
        m = re.match(r"Dropped \d+ instrument\(s\) no pattern names: (.*)", line)
        if m:
            dropped |= {int(x.strip()[1:], 16) for x in m.group(1).split(",")}
    sid, det, iu, pulse, mult, phases, _, lead = cap["args"]
    named = {p[r + 1] for p in cap["patterns"] for r in range(0, len(p) - 1, 4)}
    cap["unnamed"] = {n for n in range(lead + 1, iu + 1)
                      if n != 1 and n not in named}
    cap["dropped"] = dropped
    from h2g.goatwriter.pulse import pulse_usage
    use = pulse_usage(cap["tracks"], cap["patterns"], lead)
    cap["use"] = {n: (use[n - lead - 1] if n - lead - 1 < len(use) else 0)
                  for n in range(lead + 1, iu + 1)}
    _CACHE[name] = cap
    return cap


def _pass(cap: dict, unions: dict, empty: frozenset = frozenset(),
          static: frozenset = frozenset(), limit: int | None = None) -> tuple:
    """One shared `_lay_pulse_phase_pass` over `unions`, with the records in
    `empty` laying no block at all and those in `static` laying their static
    pair instead of their sweep; `limit` replaces GT_MAX_TABLELEN."""
    import h2g.goatwriter as G
    from h2g.goatwriter import pulse as P
    sid, det, iu, pulse, mult, phases, _, lead = cap["args"]
    real_prog, real_limit = P._pulse_program, G.GT_MAX_TABLELEN

    def prog(s, d, i, pl, m):
        num = i + 1 + lead
        if num in empty:
            return [], None
        return real_prog(s, d, i, False if num in static else pl, m)
    P._pulse_program = prog
    if limit is not None:
        G.constants.GT_MAX_TABLELEN = limit
    try:
        return P._lay_pulse_phase_pass(sid, det, iu, pulse, mult, phases,
                                       None, lead, True, unions)
    finally:
        P._pulse_program = real_prog
        G.constants.GT_MAX_TABLELEN = real_limit


def _groups(cap: dict) -> dict:
    from h2g.goatwriter import pulse as P
    sid, det, iu, pulse, mult, phases, _, lead = cap["args"]
    return P._union_groups(sid, det, iu, mult, phases, lead)


def _pointer0(t: tuple, skip=()) -> list:
    return [n for n, s in enumerate(t[1], 1) if s == 0 and n not in skip]


def test_the_records_the_drop_removes_cost_the_shared_pass_no_rows():
    cap = _capture("Gremlins.sid")
    assert cap["unnamed"] == {0x0E} | set(range(0x17, 0x21)), sorted(cap["unnamed"])
    # Read off the phase-time patterns, they are exactly what the drop
    # removes from the finished file.
    assert cap["unnamed"] <= cap["dropped"], sorted(cap["unnamed"] - cap["dropped"])
    groups = _groups(cap)
    assert sorted(sorted(m) for m in groups.values()) == [[3, 7], [6, 20]]
    keys = list(groups)
    empty = frozenset(cap["unnamed"])
    rows = {}
    for r in range(len(keys) + 1):
        for sub in itertools.combinations(keys, r):
            unions = {k: groups[k] for k in sub}
            laid, freed = _pass(cap, unions), _pass(cap, unions, empty=empty)
            label = tuple(sorted(tuple(sorted(groups[k])) for k in sub))
            rows[label] = (len(laid[0]), len(freed[0]))
            # Each one's start is a copy some NAMED record already laid.
            named_starts = {s for n, s in enumerate(laid[1], 1)
                            if n not in cap["unnamed"]}
            assert all(laid[1][n - 1] in named_starts for n in cap["unnamed"]), label
            assert (laid[3], laid[4], _pointer0(laid)) == \
                (freed[3], freed[4], _pointer0(freed, empty)), label
    assert rows == {(): (254, 254), ((3, 7),): (255, 255),
                    ((6, 20),): (252, 252), ((3, 7), (6, 20)): (255, 255)}, rows


def test_both_unions_are_three_rows_short_and_the_shipped_table_keeps_22():
    cap = _capture("Gremlins.sid")
    groups = _groups(cap)
    unlimited = _pass(cap, groups, limit=10 ** 6)
    assert (len(unlimited[0]), unlimited[3], unlimited[4]) == (258, 0, 0)
    at_limit = _pass(cap, groups)
    assert (len(at_limit[0]), at_limit[3], at_limit[4]) == (255, 1, 1)
    assert _pointer0(at_limit) == [22]
    assert cap["use"][22] == max(cap["use"].values()) == 1344
    entries, starts, index = cap["table"]
    assert len(entries) == 252
    assert sorted({k[0] for k in index}) == [3, 6, 7, 20]
    assert starts[22 - 1] != 0 and cap["use"][10] == 280


def test_the_three_rows_exist_only_as_a_sweep_traded_away():
    cap = _capture("Gremlins.sid")
    from h2g.goatwriter import pulse as P
    sid, det, iu, pulse, mult, phases, _, lead = cap["args"]
    # Every record that is not dropped sounds notes.
    assert all(u > 0 for n, u in cap["use"].items() if n not in cap["unnamed"])
    groups = _groups(cap)
    closes = {}
    for num in range(lead + 1, iu + 1):
        i = num - 1 - lead
        if phases.get(num) or (P._pulse_program(sid, det, i, pulse, mult)
                               == P._pulse_program(sid, det, i, False, mult)):
            continue                       # phase-tracked, or no sweep to lose
        t = _pass(cap, groups, static=frozenset({num}))
        if (t[3], t[4]) == (0, 0):
            closes[num] = len(t[0])
        else:
            assert 22 in _pointer0(t), num
    assert closes == {9: 255, 15: 253}, closes
    assert (cap["use"][9], cap["use"][15]) == (179, 156)


def _lay_last_v8(cap: dict, share: bool, reserve: bool,
                 empty: frozenset = frozenset()) -> tuple:
    """One `_lay_pulse_phase_table` layout, the records in `empty` laying no
    block at all (the skip counterfactual)."""
    from h2g.goatwriter import pulse as P
    sid, det, iu, pulse, mult, phases, _, lead = cap["args"]
    real = P._pulse_program

    def prog(s, d, i, pl, m):
        return ([], None) if i + 1 + lead in empty else real(s, d, i, pl, m)
    P._pulse_program = prog
    try:
        return P._lay_pulse_phase_table(sid, det, iu, pulse, mult, phases,
                                        None, lead, share, reserve=reserve)
    finally:
        P._pulse_program = real


@pytest.mark.parametrize("name, rows", [("Last_V8.sid", (254, 223, 211)),
                                        ("Last_V8_C128_version.sid",
                                         (255, 224, 212))])
def test_on_last_v8_the_reserve_leaves_the_skip_nothing_to_rescue(name, rows):
    # Re-pointed at 8586101 + the cycle merging the statics reserve
    # (`build_pulse_phase_table`'s "statics reserved" rescue). This test
    # used to assert the shipped table's pointer-0 records were 22-33; the
    # reserve removed them, so it now pins (a) that the layout WITHOUT the
    # reserve still has exactly those 12, all unheard, (b) that the shipped
    # table has none and keeps 2, 7 and 8 swept, and (c) that laying nothing
    # for the unnamed records would now buy only rows.
    cap = _capture(name)
    entries, starts, index = cap["table"]
    unreserved, reserved, skipped = rows
    tracked = sorted(n for n, w in cap["args"][5].items() if w)
    assert tracked == [2, 7, 8, 9], tracked
    # (a) The pre-reserve choice: the per-phase layout, its 12 pointer-0
    # records sounding nothing, every one of them removed by the drop.
    before = _lay_last_v8(cap, False, False)
    assert (len(before[0]), before[3], before[4]) == (unreserved, 14, 12)
    assert _pointer0(before) == list(range(22, 34)), _pointer0(before)
    assert all(cap["use"][n] == 0 for n in _pointer0(before))
    assert set(_pointer0(before)) <= cap["unnamed"] <= cap["dropped"]
    # (b) What ships: no record on pointer 0, 9 (69 notes) the one degraded.
    assert [n for n, s in enumerate(starts, 1) if s == 0] == []
    assert len(entries) == reserved
    assert sorted({k[0] for k in index}) == [2, 7, 8]
    assert cap["use"][9] == 69
    # (c) The skip as it was built -- the shared layout without the reserve,
    # laying nothing for the unnamed records -- still puts two records that
    # DO sound on pointer 0, so its (silent, degraded) (2, 2) no longer
    # beats the shipped (0, 1) and it would not be adopted. Under the
    # reserve the skip keeps the same records swept and saves only rows.
    empty = frozenset(cap["unnamed"])
    freed = _lay_last_v8(cap, True, False, empty)
    assert (freed[6], freed[5]) == (4, 4)
    assert _pointer0(freed, empty) == [16, 17], _pointer0(freed, empty)
    assert (cap["use"][16], cap["use"][17]) == (4, 64)
    assert (freed[4], freed[3]) == (2, 2) > (0, 1)
    shipped = _lay_last_v8(cap, True, True)
    assert (len(shipped[0]), shipped[3], shipped[4]) == (reserved, 1, 0)
    assert shipped[0] == entries and shipped[1] == starts
    with_skip = _lay_last_v8(cap, True, True, empty)
    assert (len(with_skip[0]), with_skip[3], with_skip[4]) == (skipped, 1, 0)
    assert _pointer0(with_skip, empty) == []
    assert {k[0] for k in with_skip[2]} == {k[0] for k in index}
