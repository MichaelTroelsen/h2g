"""A compilation's subtune-0 pulse table is laid out short, so the players
appended after it keep their sweeps.

5_Title_Tunes is five players (`convert._append_players`). Its subtune 0
converts under `pulse_phase`, and the per-phase layout took 214 of the
pulse table's 255 rows; players 1-4 then fitted only with their sweeps
dropped (`without pulse sweeps`). `build_pulse_phase_table`'s shared-ramp
layout plays the same register writes in 167 rows, and with it players 1-4
append at `without pulse_phase` -- every record's sweep intact, pulse 248 of
255 (measured at 81da71d). `prefer_short` asks for that layout, and
`convert` passes it on exactly the gate `_append_players` appends on: not a
PlayerView, two or more players.
"""
import json
import pathlib
import shutil
import sys
import tempfile
import warnings

import pytest

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[1]))

from corpus import CORPUS, needs_corpus  # noqa: E402

from h2g.goatwriter import pulse as PULSE  # noqa: E402

REPO_ROOT = pathlib.Path(__file__).resolve().parents[2]
FIVE = "5_Title_Tunes.sid"


def _fake_layouts(monkeypatch, per_phase, shared):
    """`_lay_pulse_phase_table` returning `per_phase` for share=False and
    `shared` for share=True, each as (rows, dropped, silent)."""
    def lay(sid, det, iu, pulse, mult, phases, log, lead, share):
        rows, dropped, silent = shared if share else per_phase
        entries = [(0x80, 0x00)] * rows
        return (entries, [1], {(2, 0x800, 1): 1}, dropped, silent, 1, 1)
    monkeypatch.setattr(PULSE, "_lay_pulse_phase_table", lay)


def _build(prefer_short):
    out = PULSE.build_pulse_phase_table(None, None, 2, True, 1, {2: set()},
                                        None, 1, prefer_short=prefer_short)
    return len(out[0])


def test_prefer_short_ships_the_shorter_shared_layout(monkeypatch):
    _fake_layouts(monkeypatch, per_phase=(214, 0, 0), shared=(167, 0, 0))
    assert _build(True) == 167


def test_without_prefer_short_a_fitting_table_keeps_the_per_phase_layout(
        monkeypatch):
    _fake_layouts(monkeypatch, per_phase=(214, 0, 0), shared=(167, 0, 0))
    assert _build(False) == 214


def test_prefer_short_never_takes_a_longer_or_equal_layout(monkeypatch):
    _fake_layouts(monkeypatch, per_phase=(150, 0, 0), shared=(150, 0, 0))
    assert _build(True) == 150
    _fake_layouts(monkeypatch, per_phase=(150, 0, 0), shared=(160, 0, 0))
    assert _build(True) == 150


def test_prefer_short_never_takes_a_layout_that_degrades_a_record(monkeypatch):
    # Shorter, but it dropped a record the per-phase layout placed.
    _fake_layouts(monkeypatch, per_phase=(214, 0, 0), shared=(100, 1, 0))
    assert _build(True) == 214


def _opts(name):
    presets = REPO_ROOT / "presets.json"
    if not presets.is_file():
        pytest.skip("presets.json not available here")
    with warnings.catch_warnings():
        warnings.simplefilter("ignore")
        import fidelity
        doc = json.loads(presets.read_text())
        return fidelity._preset_opts(doc, name), doc


@pytest.fixture(scope="module")
def five_calls():
    """5_Title_Tunes converted under its presets: the log, the result, and
    every `build_pulse_phase_table` call's (sid type, prefer_short, rows)."""
    from h2g import convert as C
    if not (CORPUS / FIVE).is_file():
        pytest.skip("corpus not available here")
    opts, _doc = _opts(FIVE)
    calls = []
    real = C.build_pulse_phase_table

    def spy(sid, *a, **kw):
        out = real(sid, *a, **kw)
        calls.append((type(sid).__name__, kw.get("prefer_short", False),
                      len(out[0]) if out else None))
        return out
    C.build_pulse_phase_table = spy
    lines = []
    try:
        sng = C.convert(str(CORPUS / FIVE), log=lines.append, **opts)
    finally:
        C.build_pulse_phase_table = real
    return opts, sng, lines, calls


@needs_corpus
def test_5_title_tunes_subtune_0_asks_for_the_short_layout_and_gets_it(
        five_calls):
    _opts, _sng, lines, calls = five_calls
    assert calls, "no pulse phase table was built"
    kind, prefer, rows = calls[0]
    assert (kind, prefer) == ("SidFile", True), calls
    assert rows == 167, calls
    assert any(l.startswith("Pulse phase.............: shared ramps -- 167 "
                            "table row(s) where one ramp per phase took 214")
               for l in lines), [l for l in lines if "Pulse phase" in l]


@needs_corpus
def test_5_title_tunes_appended_players_never_ask_for_it(five_calls):
    _opts, _sng, _lines, calls = five_calls
    assert all(not prefer for kind, prefer, _rows in calls
               if kind == "PlayerView"), calls


@needs_corpus
def test_5_title_tunes_appends_every_player_with_its_sweeps(five_calls):
    from h2g.goatwriter import appending as A
    _opts, sng, lines, _calls = five_calls
    level = [l for l in lines if l.startswith("Players.................: ")
             and "further" in l]
    assert level == ["Players.................: 4 of 4 further player(s) "
                     "appended as subtunes 1..4 (without pulse_phase)"], level
    assert len(A._parse_song(sng).tables[1]) <= 255


@needs_corpus
def test_a_single_player_file_does_not_ask_for_the_short_layout():
    """Every other `pulse_phase` file keeps the per-phase layout's bytes."""
    from h2g import convert as C
    opts_five, doc = _opts(FIVE)
    names = sorted(n for n, e in doc["songs"].items()
                   if e.get("pulse_phase") and n != FIVE
                   and (CORPUS / n).is_file())
    if not names:
        pytest.skip("no other pulse_phase preset in the corpus here")
    name = names[0]
    opts, _ = _opts(name)
    seen = []
    real = C.build_pulse_phase_table

    def spy(sid, *a, **kw):
        seen.append(kw.get("prefer_short", False))
        return real(sid, *a, **kw)
    C.build_pulse_phase_table = spy
    try:
        C.convert(str(CORPUS / name), log=lambda m: None, **opts)
    finally:
        C.build_pulse_phase_table = real
    assert seen and not any(seen), (name, seen)


@needs_corpus
def test_the_short_layout_writes_the_same_registers_for_subtune_0():
    """Subtune 0 packed with each layout, siddump's register table compared
    row for row over 180 s. Measured identical (9001 rows) at 81da71d."""
    import fidelity as F
    from h2g import convert as C
    if not pathlib.Path(F.SIDDUMP).exists() or not pathlib.Path(F.GT2RELOC).exists():
        pytest.skip("siddump or gt2reloc not available here")
    opts, _doc = _opts(FIVE)
    real_append, real_build = C._append_players, C.build_pulse_phase_table

    def per_phase(*a, **kw):
        kw["prefer_short"] = False
        return real_build(*a, **kw)
    C._append_players = lambda sng, *a, **k: sng
    try:
        short = C.convert(str(CORPUS / FIVE), log=lambda m: None, **opts)
        C.build_pulse_phase_table = per_phase
        long_ = C.convert(str(CORPUS / FIVE), log=lambda m: None, **opts)
    finally:
        C._append_players, C.build_pulse_phase_table = real_append, real_build
    assert short != long_
    wd = pathlib.Path(tempfile.mkdtemp(prefix="appended_pulse_budget_"))
    try:
        tables = []
        for tag, sng in (("short", short), ("long", long_)):
            (wd / tag).mkdir()
            sid = F.pack_sid(sng, wd / tag)
            assert sid is not None, tag
            cap = []
            F.run_siddump(sid, 180, 0, F.SIDDUMP, capture=cap)
            tables.append([l for l in cap[1].splitlines() if l.startswith("|")])
    finally:
        shutil.rmtree(wd, ignore_errors=True)
    assert len(tables[0]) == 9001
    assert tables[0] == tables[1]
