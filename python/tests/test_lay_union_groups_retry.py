"""`_lay_pulse_phase_table` retries a union group that did not pay alone once
another has been adopted (task `lay-pulse-phase-table-adopts-union-groups`).

Human_Race under forced `pulse_phase`: groups {1,2} and {18,23}. Measured on
the notes sounded (`usage`): none 237 rows / 437 lost, {1,2} alone 233 / 477,
{18,23} alone 197 / 437, both 242 / 264. The one-pass loop tried {1,2} first
against the empty set, refused it, and never looked at it again: 197 rows,
5 records kept, 437 notes lost. Now 242 rows, 6 kept, 264 lost.
Scripts in C:/t/lay-pulse-phase-table-adopts-union-groups.
"""
from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))


def test_group_that_pays_only_with_another_is_adopted_after_it(monkeypatch):
    from h2g.goatwriter import pulse as P
    groups = {"A": {1: {1}, 2: {2}}, "B": {3: {3}, 4: {4}}}
    # (silent, dropped, rows) by the set of groups laid: A pays only with B.
    cost = {frozenset(): (0, 10, 50), frozenset("A"): (0, 12, 49),
            frozenset("B"): (0, 10, 40), frozenset("AB"): (0, 5, 45)}

    def fake_pass(sid, det, iu, pulse, mult, phases, log, lead, share,
                  unions, *a):
        silent, dropped, rows = cost[frozenset(unions)]
        return ([None] * rows, [], {}, dropped, silent, 1, 1)

    monkeypatch.setattr(P, "_union_groups", lambda *a: dict(groups))
    monkeypatch.setattr(P, "_lay_pulse_phase_pass", fake_pass)
    t = P._lay_pulse_phase_table(None, None, 5, True, 1, {}, None, 0, True)
    assert len(t[0]) == 45 and t[3] == 5


def test_human_race_keeps_six_records_with_both_unions():
    from test_pulse_phase_union import _table_calls
    from h2g.goatwriter import pulse as P
    sid, det, iu, pulse, mult, phases, _, lead = _table_calls("Human_Race.sid")[0]
    t = P._lay_pulse_phase_table(sid, det, iu, pulse, mult, phases, None,
                                 lead, True)
    assert len(t[0]) <= 255
    assert t[6] >= 6
