"""build_pulse_phase_table and _lay_pulse_phase_table rank layouts in ONE
order: records on pointer 0 (silent) first, then degraded (dropped), then
rows (`pulse._score`)."""
from h2g.goatwriter import pulse as P


def _layout(dropped, silent, tag, rows=2):
    return ([(0x80, 0)] * rows, [1], {"tag": tag}, dropped, silent, 3, 1)


def _build(monkeypatch, first, shared):
    def fake(sid, det, instr_used, pulse, multiplier, phases, log, lead, share,
             reserve=False, usage=None):
        return shared if share else first
    monkeypatch.setattr(P, "_lay_pulse_phase_table", fake)
    return P.build_pulse_phase_table(None, None, 4, True, 1, {}, None)[2]["tag"]


def test_score_is_silent_then_dropped():
    assert P._score(_layout(5, 1, "x")) == (1, 5)
    assert P._score((0, 0, 0, 3, 4, 1, 1, 30, 40)) == (40, 30)


def test_shared_with_fewer_silent_wins_though_it_drops_more(monkeypatch):
    # per-phase: 2 degraded, both on pointer 0; shared: 3 degraded, none silent
    assert _build(monkeypatch, _layout(2, 2, "first"),
                  _layout(3, 0, "shared")) == "shared"


def test_shared_with_more_silent_loses_though_it_drops_fewer(monkeypatch):
    assert _build(monkeypatch, _layout(3, 1, "first"),
                  _layout(2, 2, "shared")) == "first"

