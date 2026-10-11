"""The pulse-phase layout comparisons weigh records by NOTES SOUNDED
(`build_pulse_phase_table(usage=pulse_usage(...))`), not by number.

Measured under forced `pulse_phase` at 2b64d25: Last_V8's per-phase layout
puts 12 records on pointer 0, and they sound 0 notes between them (silent
notes 0, degraded notes 197); the shared layout puts 15 there and they sound
68. Gremlins' per-phase layout: 7 silent records sounding 0 notes, 10 degraded
sounding 630. Counted as records, Last_V8's 12 were the bigger number.
"""
import json
import pathlib

import pytest

from h2g.goatwriter import pulse as P

REPO_ROOT = pathlib.Path(__file__).resolve().parents[2]
CORPUS = pathlib.Path("C:/Users/mit/claude/c64server/SIDM2/SID/Hubbard_Rob")


def _fake(monkeypatch, per_phase, shared):
    """`_lay_pulse_phase_table` returning `per_phase` / `shared`, each
    (rows, dropped, silent, dropped_notes, silent_notes)."""
    seen = []

    def lay(sid, det, iu, pulse, mult, phases, log, lead, share,
            reserve=False, usage=None):
        seen.append(usage)
        rows, d, s, dn, sn = shared if share else per_phase
        return ([(0x80, 0)] * rows, [1], {(2, 0x800, 1): 1}, d, s, 1, 1,
                dn, sn)
    monkeypatch.setattr(P, "_lay_pulse_phase_table", lay)
    return seen


def _build(usage):
    return len(P.build_pulse_phase_table(
        None, None, 2, True, 1, {2: set()}, None, 1, usage=usage)[0])


def test_cost_reads_notes_where_the_layout_carries_them_else_counts():
    assert P._cost((0, 0, 0, 3, 4, 1, 1, 30, 40)) == (30, 40)
    assert P._cost((0, 0, 0, 3, 4, 1, 1)) == (3, 4)


def test_fewer_records_but_more_notes_does_not_win(monkeypatch):
    # shared degrades 5 records sounding 10 notes; per-phase 3 sounding 100.
    seen = _fake(monkeypatch, per_phase=(100, 3, 0, 100, 0),
                 shared=(90, 5, 0, 10, 0))
    assert _build([1]) == 90
    assert seen[0] == [1], "usage must reach the layout"


def test_without_usage_the_record_counts_decide(monkeypatch):
    seen = _fake(monkeypatch, per_phase=(100, 3, 0, 3, 0),
                 shared=(90, 5, 0, 5, 0))
    assert _build(None) == 100
    assert seen[0] is None


def test_silent_records_that_sound_nothing_do_not_trigger_the_reserve(
        monkeypatch):
    calls = []

    def lay(sid, det, iu, pulse, mult, phases, log, lead, share,
            reserve=False, usage=None):
        calls.append(reserve)
        rows = 50 if reserve else 100
        # 2 records on pointer 0, sounding nothing, either way.
        return ([(0x80, 0)] * rows, [1], {(2, 0x800, 1): 1}, 2, 2, 1, 1,
                0, 0)
    monkeypatch.setattr(P, "_lay_pulse_phase_table", lay)
    out = P.build_pulse_phase_table(None, None, 2, True, 1, {2: set()}, None,
                                    1, usage=[0])
    assert len(out[0]) == 100, "an inaudible silence is not worth a re-lay"
    assert True in calls, "the reserve is still laid and compared"


def _forced(name):
    path = CORPUS / name
    if not path.exists():
        pytest.skip(f"{name} not in the corpus here")
    import fidelity
    from h2g import convert as C
    doc = json.load(open(REPO_ROOT / "presets.json"))
    kw = fidelity._preset_opts(doc, name)
    kw["pulse_phase"] = True
    cap = {}
    real = C.build_pulse_phase_table

    def spy(*a, **k):
        cap["a"], cap["k"] = a, k
        return real(*a, **k)
    C.build_pulse_phase_table = spy
    try:
        C.convert(str(path), log=lambda m: None, **kw)
    finally:
        C.build_pulse_phase_table = real
    return cap["a"], cap["k"]


@pytest.mark.parametrize("name,notes", [
    ("Last_V8.sid", (197, 0)),
    ("Gremlins.sid", (630, 0)),
])
def test_per_phase_layout_notes_on_the_corpus(name, notes):
    a, k = _forced(name)
    assert k.get("usage"), "convert.py must pass pulse_usage"
    sid, det, iu, pulse, mult, phases, _, lead = a[:8]
    t = P._lay_pulse_phase_table(sid, det, iu, pulse, mult, phases, None,
                                 lead, False, usage=k["usage"])
    assert (t[7], t[8]) == notes
    assert t[4] > 0 and t[8] == 0, "records on pointer 0 that nobody plays"
