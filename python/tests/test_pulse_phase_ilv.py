"""`pulse_phase` on the interleaved (ILV) engine: Go_Go_Dash's pphase.

Go_Go_Dash's original opens notes on 22 duty buckets and ours on 13
(`pphase` 0.59x at `-t 180`): its pulse accumulator is not reseeded on a note
that carries command `$88` (`$11DE STA $1A64`, tested at `$12C9 LDA $1A64 /
BNE $12E8`) or that the previous duration byte tied (`$12C1 LDA $1AC3 / BEQ /
JMP $13B5`), so those notes open wherever the free-running sweep has got to.
The bounds-engine phase walk (`PulseBoundsSim`) models exactly that, but
`convert` only handed it the files whose reseed test is `LDA note / BMI`, and
the ILV decoder fed it no free rows, so the option was inert on all six ILV
files.

Two changes, pinned here:

* `_build_raw_pattern_ilv(free_rows=...)` reports the rows of `$88` notes and,
  under `tie`, of notes the previous duration byte tied; and `convert` hands
  the bounds sims to the ILV dialect.
* The phase table's greedy layout lays records in instrument order, so
  Go_Go_Dash's instrument 5 (85 notes, 27 phases) took the rows instrument 6
  (737 notes, 25 phases, 107 rows) then needed and the busiest record fell to
  a static width: pulse changes 18583 -> 13158 against the original's 18077.
  `_shed_for_played` re-lays with the less-played record's phases left out
  where that lowers the note-weighted cost.

Both are inert under shipped presets: no preset enables `pulse_phase` on an
ILV file, and the corpus byte-hash of the 89 converting files under presets is
unchanged (task listen-sub99-go-go-dash).
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent))
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import corpus                                                   # noqa: E402
from h2g.patterns import _build_raw_pattern_ilv                  # noqa: E402

REPO_ROOT = Path(__file__).resolve().parent.parent.parent


def _ilv_free_rows(pattern: list[int], tie: bool) -> tuple[list[int], list[int]]:
    data = bytes([0, 0] + pattern)
    fr: list[int] = []
    with_rows = _build_raw_pattern_ilv(data, 2, tie=tie, free_rows=fr)
    without = _build_raw_pattern_ilv(data, 2, tie=tie)
    assert with_rows == without, "free_rows must be a pure out-parameter"
    return fr, with_rows


# $80 02 selects record 2; $C1 is a two-row duration (`& $1F` = 1 hold row);
# $E1 the same duration with the tie bit ($20); $88 is the no-reseed command;
# $81 ends the pattern. Rows: 0 note, 1 hold, 2 note, 3 hold, 4 note, 5 hold,
# 6 note, 7 hold.
_PATTERN = [0x80, 0x02,
            0xC1, 0x30,          # row 0: plain note
            0x88, 0xC1, 0x32,    # row 2: `$88` before it -> free
            0xE1, 0x34,          # row 4: plain note, its duration carries the tie
            0xC1, 0x36,          # row 6: tied by the previous duration byte
            0x81]


def test_ilv_free_rows_reports_88_and_the_duration_tie():
    fr, _ = _ilv_free_rows(_PATTERN, tie=True)
    assert fr == [2, 6]


def test_ilv_duration_tie_is_free_only_under_the_tie_option():
    fr, _ = _ilv_free_rows(_PATTERN, tie=False)
    assert fr == [2]


def test_ilv_88_belongs_to_one_note_only():
    # The player zeroes `$1A64` at every event fetch ($115E): the note after
    # the next one reseeds again.
    pattern = [0x80, 0x02, 0x88, 0xC1, 0x32, 0xC1, 0x34, 0x81]
    fr, _ = _ilv_free_rows(pattern, tie=True)
    assert fr == [0]


def _forced_logs(name: str) -> tuple:
    presets = REPO_ROOT / "presets.json"
    path = corpus.CORPUS / name
    if not presets.exists() or not path.exists():
        pytest.skip("corpus or presets.json not available here")
    import fidelity
    from h2g.convert import convert
    doc = json.loads(presets.read_text(encoding="utf-8"))
    kwargs = fidelity._preset_opts(doc, name)
    kwargs["pulse_phase"] = True
    logs: list[str] = []
    out = convert(str(path), log=logs.append, **kwargs)
    return logs, out


@corpus.needs_corpus
def test_go_go_dash_pulse_phase_reaches_the_ilv_engine_and_keeps_instrument_6():
    """Forced on, Go_Go_Dash plans phases (it did not at 1c9d17c: the
    option was byte-inert) and instrument 6 -- the voice-1 workhorse, 737
    notes -- keeps its 25 phases rather than falling to a static width."""
    logs, forced = _forced_logs("Go_Go_Dash.sid")
    text = "\n".join(logs)
    assert "CMD_SETPULSEPTR on" in text, "the walk planned nothing"
    assert "FALLING BACK TO A STATIC WIDTH" not in text, text
    assert "phases of instrument 5 shed" in text
    from h2g.convert import convert
    import fidelity
    doc = json.loads((REPO_ROOT / "presets.json").read_text(encoding="utf-8"))
    kwargs = fidelity._preset_opts(doc, "Go_Go_Dash.sid")
    # pulse_phase ships on Go_Go_Dash since v0.5.683: shipped == forced, and
    # the conversion with the option held off differs.
    assert kwargs["pulse_phase"] is True
    shipped = convert(str(corpus.CORPUS / "Go_Go_Dash.sid"), log=lambda m: None,
                      **kwargs)
    assert shipped == forced
    plain = convert(str(corpus.CORPUS / "Go_Go_Dash.sid"), log=lambda m: None,
                    **{**kwargs, "pulse_phase": False})
    assert forced != plain


@corpus.needs_corpus
def test_go_go_dash_without_the_shed_rescue_drops_instrument_6(monkeypatch):
    """The rescue's own pin: short-circuit it and the greedy layout puts
    instrument 5 first and cuts instrument 6 to a static width."""
    import h2g.goatwriter.pulse as P
    monkeypatch.setattr(P, "_shed_for_played", lambda *a, **k: set())
    logs, _ = _forced_logs("Go_Go_Dash.sid")
    text = "\n".join(logs)
    assert "PULSE PHASE NEEDS" in text and "INSTRUMENT 6" in text, text
    assert "phases of instrument 5 shed" not in text


@corpus.needs_corpus
def test_ilv_reach_is_gated_on_the_dialect(monkeypatch):
    """With the ILV arm of the bounds-sim gate removed the option is inert on
    Go_Go_Dash again (identical bytes to the unforced conversion)."""
    import fidelity
    import h2g.convert as C
    presets = REPO_ROOT / "presets.json"
    if not presets.exists():
        pytest.skip("presets.json not available here")
    doc = json.loads(presets.read_text(encoding="utf-8"))
    kwargs = fidelity._preset_opts(doc, "Go_Go_Dash.sid")
    path = str(corpus.CORPUS / "Go_Go_Dash.sid")
    # held off explicitly: Go_Go_Dash ships pulse_phase since v0.5.683
    plain = C.convert(path, log=lambda m: None, **{**kwargs, "pulse_phase": False})
    monkeypatch.setattr(C, "pulse_bounds_sims", lambda *a, **k: {})
    kwargs["pulse_phase"] = True
    gated = C.convert(path, log=lambda m: None, **kwargs)
    assert gated == plain


def _pacific_coast_record_0d_rows(pulse_phase: bool, monkeypatch=None) -> list:
    """The pulse-table rows of Pacific_Coast's record $0D (rate 149 a call,
    over `SPELLED_SPEED_MIN`), under presets with `pulse_phase` as given."""
    import fidelity
    import songview
    from h2g.convert import convert
    doc = json.loads((REPO_ROOT / "presets.json").read_text(encoding="utf-8"))
    kwargs = fidelity._preset_opts(doc, "Pacific_Coast.sid")
    kwargs["pulse_phase"] = pulse_phase
    sng = convert(str(corpus.CORPUS / "Pacific_Coast.sid"),
                  log=lambda m: None, **kwargs)
    song = songview.parse_sng(sng)
    inst = [i for i in song.instruments if i.name.startswith("0D:")]
    assert len(inst) == 1
    table = next(v for k, v in song.tables.items() if k.lower().startswith("p"))
    start = inst[0].pulse_ptr - 1
    return table[start:start + 6]


@corpus.needs_corpus
def test_phase_table_keeps_the_spelled_sweep_of_a_fast_unplanned_record(monkeypatch):
    """Pacific_Coast's record $0D sweeps 149 a call, which one modulation row
    cannot carry (127 at most). `_pulse_layout` spells it as set rows; the
    phase table laid its non-phase-tracked records without that trial and
    clamped it to 127 (poff .974 -> .956 under forced `pulse_phase`). It keeps
    the set rows now."""
    rows = _pacific_coast_record_0d_rows(True)
    assert all(left & 0x80 for left, _ in rows), rows
    import h2g.goatwriter.pulse as P
    real = P._pulse_program

    def clamp(*a, **k):
        k["spell"] = False
        return real(*a, **k)
    monkeypatch.setattr(P, "_pulse_program", clamp)
    clamped = _pacific_coast_record_0d_rows(True)
    assert not all(left & 0x80 for left, _ in clamped), clamped
