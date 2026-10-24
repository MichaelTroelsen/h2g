"""Star_Paws voice 1, frames 2815-2818: no pitch wraps past Goattracker's table.

Subtune 0's voice-1 run climbs a rising arpeggio whose top event is the
Hubbard note byte `$5D` (entry 93) under an orderlist transpose of +3, so the
original's note fetch reads entry 96 -- the `$0000` cell after its 96-entry
table -- on those four frames. Before v0.5.536 the row was the clamped note
(`$BC`, entry 92) with the +3 added by the orderlist, i.e. entry 95 plus a
relative wave step: the conversion read `$FFFF` there and the vibrato
excursion after it (`$01BF`, `$FE3F`, `$FC7F`; `$FFFF`/`$027F`/`$FD7F`/`$FAFF`
in the first A/B), a 16-bit wrap in place of the original's `$0000`/`$00B4`.
The cycle-20 top-note pin (`past_table_wave`, "A note above the note column")
points the row at a wave program pinned to the lowest absolute note, C#0
(`$0127`, the documented stand-in for a `$0000` cell, which has no absolute
note), and the same frames read `$0127 $0129 $0125 $0123`.

Two pins. The static one: every `$BC` row of the climb that carries a
`CMD_SETWAVEPTR` starts a program whose first step is an absolute note, and
the two entries the climb needs ($DD = 93 and $81 = the C#0 stand-in) are both
there. The traced one: packed by gt2reloc and run through siddump-rt, voice 1
of subtune 0 reads one note's four frames inside a few hundred units of each
other -- not `$FFFF` followed by a vibrato that wraps through `$0000`.
"""
from __future__ import annotations

import sys
from pathlib import Path

import pytest

PYTHON_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PYTHON_ROOT))

from h2g.goatwriter.appending import _parse_song  # noqa: E402

CORPUS = Path("C:/Users/mit/claude/c64server/SIDM2/SID/Hubbard_Rob")
pytestmark = pytest.mark.skipif(not (CORPUS / "Star_Paws.sid").exists(),
                                reason="the Hubbard corpus is not on this machine")

_CMD_SETWAVEPTR = 0x8
_TOP = 0xBC           # GT_LASTNOTE: the note column's last note, entry 92


# Star_Paws adopted regrid at v0.5.595; these tests pin the pre-adoption arm.
PRE_ADOPTION = dict(regrid=False, regrid_full_debt=False, regrid_per_play=False)


def _star_paws():
    import json
    import fidelity as F
    from h2g.convert import convert
    doc = json.load(open(PYTHON_ROOT.parent / "presets.json"))
    blob = convert(str(CORPUS / "Star_Paws.sid"), log=lambda *a, **k: None,
                   **{**F._preset_opts(doc, "Star_Paws.sid"), **PRE_ADOPTION})
    return _parse_song(blob)


@pytest.fixture(scope="module")
def song():
    return _star_paws()


def test_the_climb_does_not_wrap_in_the_packed_trace(tmp_path):
    import json
    import fidelity as F
    doc = json.load(open(PYTHON_ROOT.parent / "presets.json"))
    if not (Path(F.SIDDUMP).exists() and Path(F.GT2RELOC).exists()):
        pytest.skip("siddump or gt2reloc not available here")
    from h2g.convert import convert
    mult = F._preset_multiplier(doc, "Star_Paws.sid")
    sng = convert(str(CORPUS / "Star_Paws.sid"), log=lambda *a, **k: None,
                  **{**F._preset_opts(doc, "Star_Paws.sid"), **PRE_ADOPTION})
    sid = F.pack_sid(sng, tmp_path, F.GT2RELOC, mult)
    assert sid, "gt2reloc refused the conversion"
    frames = 3000                                 # 60 s; the climb is at 2811
    trace = F.run_siddump(Path(sid), 60, 0, F.SIDDUMP, 0, calls=mult)
    freq = F.register_timeline(trace[0].freq_events, frames)
    assert 0xFFFF not in freq
    top = freq[2815:2819]                         # the original's $0000 frames
    assert max(top) - min(top) < 0x400, [hex(f) for f in top]
    assert freq[2811] == 0xF820                   # entry 94 just before it


def test_the_climb_tops_out_on_an_absolute_pinned_step(song):
    # Subtune 0's voice-1 climb: the $BC row carrying a CMD_SETWAVEPTR. Each
    # such row starts a program whose first step is an ABSOLUTE note (right
    # $81-$DF) -- entry 93 itself ($DD) or, under the +3 transpose that sends
    # the original to its $0000 cell, the lowest absolute note ($81).
    wave = song.tables[0]
    firsts = set()
    for pat in song.patterns:
        for k in range(0, len(pat) - 3, 4):
            nt, _ins, cmd, data = pat[k:k + 4]
            if nt == _TOP and cmd & 0x0F == _CMD_SETWAVEPTR:
                left, right = wave[data - 1]
                assert left < 0xF0 and 0x81 <= right <= 0xDF, (data, left, right)
                firsts.add(right)
    assert 0x81 in firsts and 0xDD in firsts
