"""The packed-size budget `pulse_phase` runs against greloc.c's 256-byte limit.

`greloc.c`'s `packpattern()` (v2.77, greloc.c:1715) packs each pattern for the
player and returns -1 past 256 bytes (`if (destsize > 256) return -1;`, before
the endmark); `gt2reloc` then prints "PATTERN xx IS TOO COMPLEX (OVER 256
BYTES PACKED)!" to a console that does not exist headless, writes no file and
exits 0. That is what refused Rasputin at -S2 under `pulse_phase` while
convert.py's `multiplier == 1` gate kept the option off every multispeed file
(24b9f1d). The gate is lifted; `goatwriter.budget_pulse_phase_commands` is
what makes that safe, and it runs on the FINISHED rows in `build_sng` because
a budget on the plan drops nothing: Rasputin's four clones pack to 217 when
`apply_pulse_phase` writes them and to 264-270 once `_vibrato_command_pass`
has added its commands.

`test_table_validation.packed_pattern_size` is a SECOND reader of the same
arithmetic, written against greloc.c rather than against goatwriter's copy,
so the two can disagree; `test_the_two_readers_agree_on_the_corpus` is where
they would. It did, the first time: that reader counted the ENDPATT row that
`pattlen` (gsong.c:1330) stops before.
"""
import json
import pathlib
import sys

import pytest

from corpus import CORPUS, needs_corpus  # noqa: E402
from test_table_validation import (  # noqa: E402
    PACKED_PATTERN_LIMIT, _pattern_rows, packed_pattern_size)

PYTHON_ROOT = pathlib.Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PYTHON_ROOT))

import fidelity as F  # noqa: E402
import songview  # noqa: E402
from h2g import goatwriter as G  # noqa: E402
from h2g import patterns as P  # noqa: E402


def _flat(rows):
    return [b for row in rows for b in row] + list(P.GT_END_ROW)


def test_goatwriters_reader_agrees_with_the_test_replica_on_the_shapes():
    """The five shapes `test_table_validation` pins its replica on, read by
    goatwriter's copy: the busy pattern past the limit, the quiet one inside
    it, a repeated and a changed instrument, and a run of packed rests."""
    busy = [(0x60 + (r % 12), 0, 9, r) for r in range(127)]
    quiet = [(0x60 + (r % 12), 0, 0, 0) for r in range(127)]
    rests = [(0x60, 0, 0, 0)] + [(G.GT_REST, 0, 0, 0)] * 100
    assert G.packed_pattern_size(busy) == 381 > G.PACKED_PATTERN_LIMIT
    assert G.PACKED_PATTERN_LIMIT == PACKED_PATTERN_LIMIT == 256
    for rows in (busy, quiet, rests,
                 [(0x60, 3, 0, 0)] + [(0x61, 3, 0, 0)] * 10,
                 [(0x60, 3, 0, 0), (0x61, 4, 0, 0)]):
        assert G.packed_pattern_size(rows) == packed_pattern_size(rows)


def test_the_command_constant_is_the_same_in_both_modules():
    """patterns.py writes command 9 and goatwriter.py budgets command 9; the
    two copies of the constant must never drift (gcommon.h:13)."""
    assert G.CMD_SETPULSEPTR == P.CMD_SETPULSEPTR == 9


def test_pattern_rows_stops_at_endpatt():
    flat = [0x60, 1, 0, 0, 0xBD, 0, 0, 0, 0xFF, 0, 0, 0, 0x61, 0, 0, 0]
    assert G.pattern_rows(flat) == [(0x60, 1, 0, 0), (0xBD, 0, 0, 0)]
    assert _pattern_rows(flat) == G.pattern_rows(flat)


def _busy_pattern(rows: int = 127):
    """A pattern that is over the limit with phase commands on every note
    row and under it without: 127 notes, CMD_SETPULSEPTR with a fresh operand
    on each -- 381 packed."""
    return _flat([(0x60 + (r % 12), 0, G.CMD_SETPULSEPTR, 1 + r) for r in range(rows)])


def test_the_budget_drops_first_fit_and_lands_on_the_limit():
    busy = _busy_pattern()
    before = list(busy)
    logs = []
    out = G.budget_pulse_phase_commands([busy], G.CMD_SETPULSEPTR, logs.append)
    assert busy == before, "the input pattern was edited in place"
    assert len(out) == 1 and out[0] is not busy
    rows = G.pattern_rows(out[0])
    size = G.packed_pattern_size(rows)
    assert size <= PACKED_PATTERN_LIMIT
    assert packed_pattern_size(rows) == size
    kept = [k for k, r in enumerate(rows) if r[2] == G.CMD_SETPULSEPTR]
    # First-fit in row order: the kept commands are a prefix of the rows,
    # every note survives, and one more command would not fit.
    assert kept == list(range(len(kept))), kept
    assert all(r[0] == 0x60 + (k % 12) for k, r in enumerate(rows))
    trial = list(rows)
    trial[len(kept)] = (rows[len(kept)][0], 0, G.CMD_SETPULSEPTR, 1 + len(kept))
    assert packed_pattern_size(trial) > PACKED_PATTERN_LIMIT
    assert logs and "dropped from 1 pattern(s)" in logs[0], logs
    assert f"{127 - len(kept)} CMD_SETPULSEPTR dropped" in logs[0], logs


def test_a_pattern_inside_the_limit_is_returned_as_is():
    ok = _flat([(0x60 + (r % 12), 0, G.CMD_SETPULSEPTR, 1 + r) for r in range(60)])
    assert G.packed_pattern_size(G.pattern_rows(ok)) <= PACKED_PATTERN_LIMIT
    logs = []
    out = G.budget_pulse_phase_commands([ok], G.CMD_SETPULSEPTR, logs.append)
    assert out[0] is ok and not logs


def test_a_pattern_over_the_limit_without_the_command_is_not_this_passs():
    """Only the phase command is budgeted: a pattern some other writer took
    over 256 is returned untouched, and the corpus walk in
    `test_table_validation` is what says so. Otherwise a vibrato or a slide
    would vanish with no writer named."""
    over = _flat([(0x60 + (r % 12), 0, G.CMD_VIBRATO, 1 + r) for r in range(127)])
    assert G.packed_pattern_size(G.pattern_rows(over)) > PACKED_PATTERN_LIMIT
    logs = []
    out = G.budget_pulse_phase_commands([over], G.CMD_SETPULSEPTR, logs.append)
    assert out[0] is over and not logs


def test_other_commands_are_kept_and_charged():
    """A row already carrying another command keeps it, and it counts against
    the budget: with 60 vibrato rows in front, fewer phase commands fit than
    on the bare pattern."""
    mixed = [(0x60 + (r % 12), 0, G.CMD_VIBRATO, 1 + r) for r in range(60)]
    mixed += [(0x60 + (r % 12), 0, G.CMD_SETPULSEPTR, 1 + r) for r in range(60, 127)]
    out = G.budget_pulse_phase_commands([_flat(mixed)], G.CMD_SETPULSEPTR)
    rows = G.pattern_rows(out[0])
    assert rows[:60] == mixed[:60]
    assert G.packed_pattern_size(rows) <= PACKED_PATTERN_LIMIT
    kept = sum(1 for r in rows if r[2] == G.CMD_SETPULSEPTR)
    bare = G.budget_pulse_phase_commands([_busy_pattern()], G.CMD_SETPULSEPTR)
    bare_kept = sum(1 for r in G.pattern_rows(bare[0]) if r[2] == G.CMD_SETPULSEPTR)
    assert 0 < kept < bare_kept, (kept, bare_kept)


def _presets():
    return json.loads((pathlib.Path(__file__).resolve().parents[2]
                       / "presets.json").read_text(encoding="utf-8"))


@needs_corpus
def test_the_two_readers_agree_on_the_corpus():
    """goatwriter's copy of the arithmetic against test_table_validation's,
    on every pattern of every preset conversion -- rows and size both."""
    doc = _presets()
    compared = 0
    for path in sorted(CORPUS.glob("*.sid")):
        try:
            blob = F.convert(str(path), log=lambda m: None,
                             **F._preset_opts(doc, path.name))
        except Exception:                              # noqa: BLE001
            continue
        for flat in songview.parse_sng(blob).patterns:
            rows = _pattern_rows(flat)
            assert G.pattern_rows(flat) == rows
            assert G.packed_pattern_size(rows) == packed_pattern_size(rows)
            compared += 1
    assert compared > 1000, compared


@needs_corpus
def test_rasputin_packs_under_pulse_phase_at_S2_only_with_the_budget(monkeypatch):
    """The measured case. With the budget bypassed the -S2 conversion is
    what 24b9f1d recorded -- four patterns past 256, gt2reloc writes no
    file; with it, every pattern is inside the limit and the file packs."""
    path = CORPUS / "Rasputin.sid"
    exe = pathlib.Path(F.GT2RELOC)
    if not path.exists() or not exe.exists():
        pytest.skip("Rasputin.sid or gt2reloc.exe not available here")
    doc = _presets()
    opts = F._preset_opts(doc, "Rasputin.sid")
    opts["pulse_phase"] = True
    multiplier = doc["songs"]["Rasputin.sid"]["multiplier"]
    assert multiplier > 1, "the case is a multispeed file"

    def pack(blob):
        import tempfile
        with tempfile.TemporaryDirectory(prefix="h2g_budget_") as d:
            return F.pack_sid(blob, pathlib.Path(d), multiplier=multiplier)

    logs = []
    with_budget = F.convert(str(path), log=logs.append, **opts)
    assert any("CMD_SETPULSEPTR on" in m for m in logs), "the option did not reach the file"
    dropped = [m for m in logs if "dropped from" in m]
    assert dropped, logs
    sizes = [packed_pattern_size(_pattern_rows(p))
             for p in songview.parse_sng(with_budget).patterns]
    assert max(sizes) <= PACKED_PATTERN_LIMIT
    assert pack(with_budget) is not None, "gt2reloc refused the budgeted file"

    monkeypatch.setattr(G, "budget_pulse_phase_commands",
                        lambda patterns, command, log=None, limit=256: patterns)
    without = F.convert(str(path), log=lambda m: None, **opts)
    sizes = [packed_pattern_size(_pattern_rows(p))
             for p in songview.parse_sng(without).patterns]
    assert max(sizes) > PACKED_PATTERN_LIMIT, "the case no longer reproduces"
    assert pack(without) is None, "gt2reloc packed a pattern past 256"
