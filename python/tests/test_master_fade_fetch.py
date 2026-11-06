"""master_fade, the row-fetch spelling (Confuzion `$0956`).

`LDA #$A0 / SEC / SBC $0BC2 / CMP #$0F / BCC +2 / LDA #$0F / STA $D418` sits
inside the row fetch, behind `BIT status / BVS` and `BPL`, so it runs only for
a row whose status byte has bit 7 and no bit 6. A position's level reaches the
chip only if some voice fetches such a row while the position is current.

The expected writes are the trace of the original (siddump -v1 with
-w0bc1,0bc2,0bc3, 20000 frames, C:/t/sanxion-position-driven-master-fade/
confuzion_orig.dump): `$D418`'s volume steps to E at call 13994 (voice 1's
position $92) and down one level per 96 calls to 1 at call 15242 (position
$9F); positions $A0..$A3 hold one instrument-less pattern on every voice, so
nothing is written for them, the volume stays 1, and the tune's own end
routine zeroes it at call 15650. The walk's tick t is call 3t+2.
"""
import json
from pathlib import Path

import pytest

import fidelity as F
from corpus import CORPUS, needs_corpus
from h2g import convert as C
from h2g import patterns as P
from h2g.convert import convert
from h2g.detect import detect, find_master_fade, master_fade_is_fetch
from h2g.master_fade import written_positions
from h2g.patterns import command_floor
from h2g.sidfile import load_sid
from songview import parse_sng

REPO = Path(__file__).resolve().parents[2]
CONFUZION = CORPUS / "Confuzion.sid"
ZOIDS = CORPUS / "Zoids.sid"


def _opts(name, fade):
    doc = json.loads((REPO / "presets.json").read_text("utf-8"))
    return dict(F._preset_opts(doc, name), master_fade=fade)


def _levels(song):
    return sorted(pat[4 * r + 3] for pat in song.patterns
                  for r in range(len(pat) // 4)
                  if pat[4 * r + 2] == P.CMD_SETMASTERVOL)


@needs_corpus
def test_the_second_spelling_is_read_and_named():
    sid = load_sid(str(CONFUZION))
    assert find_master_fade(sid) == (0xA0, 1)
    assert master_fade_is_fetch(sid)
    assert not master_fade_is_fetch(load_sid(str(CORPUS / "Sanxion.sid")))


@needs_corpus
def test_the_walk_writes_what_the_original_wrote(monkeypatch):
    """SABOTAGE TARGET: `written_positions` returning every position (the
    formula taken as if it were written) puts `$A0` in the result."""
    cap = {}
    real = C.reindex_tracks

    def spy(tracks, *a, **k):
        cap["tracks"] = [list(t) for t in tracks]
        return real(tracks, *a, **k)

    monkeypatch.setattr(C, "reindex_tracks", spy)
    opts = _opts("Confuzion.sid", False)
    convert(str(CONFUZION), log=lambda m: None, **opts)
    sid = load_sid(str(CONFUZION))
    det = detect(sid, lambda m: None)
    got = written_positions(sid, det, cap["tracks"], 0, 1,
                            command_floor(det.read_track_version,
                                          det.track_fd_transpose),
                            slides=opts["slides"],
                            status_bit6=opts["status_bit6"])
    assert max(got) == 0x9F and 0xA0 not in got
    assert sorted(got) == list(range(0x9F + 1))
    assert 3 * got[0x92] + 2 == 13994             # V=E, the first fade write
    assert 3 * got[0x9F] + 2 == 15242             # V=1, the last
    assert all(got[0x92 + k] - got[0x92] == 32 * k for k in range(14))


@needs_corpus
def test_the_option_writes_levels_e_to_1_and_never_0():
    """SABOTAGE TARGET: the walk gate in `convert` (`written`): without it
    `D00` is written at position $A0, which the original never does."""
    on = parse_sng(convert(str(CONFUZION), log=lambda m: None,
                           **_opts("Confuzion.sid", True)))
    off = parse_sng(convert(str(CONFUZION), log=lambda m: None,
                            **_opts("Confuzion.sid", False)))
    # The fade's own levels are E..1; the one `D00` is the tune-end write, in
    # the LAST pattern (test_master_fade_tune_end.py), never in a fade copy.
    last = on.patterns[-1]
    assert [last[4 * r + 3] for r in range(len(last) // 4)
            if last[4 * r + 2] == P.CMD_SETMASTERVOL] == [0]
    assert sorted(l for pat in on.patterns[:-1] for r in range(len(pat) // 4)
                  for l in [pat[4 * r + 3]]
                  if pat[4 * r + 2] == P.CMD_SETMASTERVOL) == list(range(1, 15))
    assert _levels(off) == []
    assert len(on.patterns) <= P.MAX_PATTERNS


@needs_corpus
def test_a_version_0_file_with_the_second_spelling_is_left_alone():
    """Zoids has the shape under a version-0 orderlist, whose positions are
    not the flat index (repeat commands): reading it is not done."""
    a = convert(str(ZOIDS), log=lambda m: None, **_opts("Zoids.sid", True))
    b = convert(str(ZOIDS), log=lambda m: None, **_opts("Zoids.sid", False))
    assert a == b
