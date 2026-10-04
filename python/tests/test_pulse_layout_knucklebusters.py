"""Knucklebusters' pulse table, the corpus file that fills it: every record
keeps its whole program, GT26 included, because a block whose loop body is
already in the table jumps into it.

History: before the loop-tail sharing, GT26 (record 25, 8 notes sounded, all
in subtune 2) was the one played record to lose its sweep -- its full block was
eight entries and seven were left, so it kept its set `$81 $40` at pointer 249
and nothing more. Its loop body is GT14's entry for entry, so a jump into
GT14's loop costs the 3-entry prefix plus one jump, four entries, not eight,
and `_lay_out_pulse` now writes that. The table is still 255 of 255.
"""
import json
import sys
from pathlib import Path

from corpus import CORPUS, needs_corpus

import pytest

PYTHON_ROOT = Path(__file__).resolve().parents[1]
REPO_ROOT = PYTHON_ROOT.parent
NAME = "Knucklebusters.sid"


def _convert_capturing(monkeypatch):
    """Convert under presets; return (sng, usage, programs, statics, lead)."""
    sys.path.insert(0, str(PYTHON_ROOT))
    import fidelity
    from h2g import goatwriter as gw
    from h2g.convert import convert
    presets = REPO_ROOT / "presets.json"
    if not presets.exists() or not (CORPUS / NAME).exists():
        pytest.skip(f"presets.json or {NAME} not available here")
    doc = json.loads(presets.read_text(encoding="utf-8"))
    opts = fidelity._preset_opts(doc, NAME)
    usages: list = []
    layouts: list = []
    real_usage, real_lay = gw.pulse_usage, gw._lay_out_pulse

    def usage(*a, **k):
        u = real_usage(*a, **k)
        usages.append(u)
        return u

    def lay(programs, statics, lead, share, **k):
        layouts.append((programs, statics, lead))
        return real_lay(programs, statics, lead, share, **k)

    monkeypatch.setattr(gw.pulse, "pulse_usage", usage)
    monkeypatch.setattr(gw.pulse, "_lay_out_pulse", lay)
    out = convert(str(CORPUS / NAME), **opts)
    assert usages and layouts, "the pulse layout never ran"
    programs, statics, lead = layouts[-1]
    return out, usages[-1], programs, statics, lead


@needs_corpus
def test_every_record_keeps_its_whole_program_and_gt26_jumps_into_gt14s_loop(
        monkeypatch):
    import songview
    out, usage, programs, statics, lead = _convert_capturing(monkeypatch)
    song = songview.parse_sng(out)
    ptbl = song.tables["PTBL"]
    assert len(ptbl) == 255, "the premise: Knucklebusters fills the table"
    by_number = {ins.number: ins for ins in song.instruments}
    assert 25 in [i for i, u in enumerate(usage) if u] and usage[25] == 8,         "the premise: GT26 is record 25 and sounds 8 notes"
    short = []
    for i, (program, loop) in enumerate(programs):
        n = lead + i + 1
        if i >= len(usage) or not usage[i]:
            continue                     # sounds nothing, so nothing to hear
        ptr = by_number[n].pulse_ptr
        assert ptr, f"GT{n} sounds {usage[i]} notes and has no width"
        got = list(ptbl[ptr - 1:ptr - 1 + len(program)])
        if loop is None:
            ok = got == list(program)
        else:
            # Follow the jump: the program is its prefix, then its loop body
            # wherever that lives (inline, or in an earlier block).
            prefix = list(program[:loop])
            ok = got[:loop] == prefix
            at = ptr + loop
            if got[loop:loop + 1] and got[loop][0] == 0xFF:
                at = got[loop][1]
            body = list(ptbl[at - 1:at - 1 + len(program) - loop])
            ok = ok and body == list(program[loop:])
        if not ok:
            short.append(n)
    assert short == [], f"records without their whole program: {short}"
    gt14, gt26 = by_number[lead + 14].pulse_ptr, by_number[lead + 26].pulse_ptr
    prefix = list(programs[25][0][:programs[25][1]])
    assert list(ptbl[gt26 - 1:gt26 - 1 + len(prefix)]) == prefix
    assert ptbl[gt26 - 1 + len(prefix)] == (0xFF, gt14 + programs[13][1]),         "GT26's block ends in a jump to the first entry of GT14's loop"
