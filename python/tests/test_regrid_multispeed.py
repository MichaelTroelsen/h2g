"""`--regrid` on a multispeed song: the deficit is FRAMES, the tempo is CALLS.

Star_Paws (-S2) is the file that found it. Its play routine stalls the speed
counter one frame in 128:

    B053  DEC $B712      ; the outer counter
    B056  BPL $B060
    B058  LDA #$7F
    B05A  STA $B712
    B05D  JMP $B06B      ; past `DEC $B6D3`, the speed counter -- frozen

so subtune 0's two-frame row is really 2 * 128/127 = 256/127 frames. No tempo
can carry a denominator of 127, so it is encoded as 2 frames = tempo 4 at -S2,
and the conversion ran one frame in 128 fast: `drift` -7.81 per 1000, 71
frames ahead after 180 s. On the 8-frame drum grid of voices 2 and 3 that
read as "our attack 3 frames late" (orig 532, ours 535 at lag 6) -- but
paired by note INDEX ours was 5 frames early, the nearest-neighbour pairing
aliasing -5 to +3. Neither a startup_lag misestimate nor a per-note onset
delay: an integrating clock error, which is what `--regrid` exists to pay.

It could not, because `convert` compared `effective_frames` (2, frames) with
the tempo value (4, calls), and `2 != 4` declined every multispeed file.
"""
import pathlib
import sys
from fractions import Fraction

import pytest

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[1]))
sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent))

from corpus import CORPUS, needs_corpus                      # noqa: E402
from h2g.convert import convert, regrid_deficits             # noqa: E402
from h2g.goatwriter.tempo import (SongSpeeds, effective_frames,  # noqa: E402
                                  find_song_speeds)
from h2g.sidfile import load_sid                             # noqa: E402

STAR_PAWS = CORPUS / "Star_Paws.sid"


def _speeds(frames, skip):
    return SongSpeeds(tuple(frames), 0, None, skip=tuple(skip))


def test_a_declined_row_at_s2_owes_its_fraction_in_frames():
    """Star_Paws' subtune 0, synthetically: 2 frames, skip 127, -S2 tempo 4."""
    sp = _speeds([2], [127])
    assert sp.exact_row(0) == Fraction(256, 127)
    assert effective_frames(sp, 0, True) == 2      # 127 > MAX_ROW_DENOMINATOR
    got = regrid_deficits(sp, [4], True, 2)
    assert got == pytest.approx([2 / 127])


def test_the_s1_answer_is_the_one_every_adopter_was_measured_under():
    """At -S1 frames and calls are the same number, so the fix must leave the
    deficit exactly what the old `exact - values[k]` gave -- the 15 shipped
    `regrid: true` songs are all -S1 and their bytes must not move."""
    sp = _speeds([3], [127])
    exact = float(sp.exact_row(0))
    assert regrid_deficits(sp, [3], True, 1) == [max(0.0, exact - 3)]


def test_a_tempo_that_is_not_the_declined_row_owes_nothing():
    """`values` overwritten (an orderlist `$FE` opening, a split subtune) is not
    the row `effective_frames` declined, so there is nothing to make up."""
    sp = _speeds([2], [127])
    assert regrid_deficits(sp, [5], True, 2) == [0.0]
    # The old frames-against-calls comparison: matching the CALL value at -S2
    # by its FRAME value must not be mistaken for a match.
    assert regrid_deficits(sp, [2], True, 2) == [0.0]


def test_an_encodable_row_owes_nothing_at_any_multiplier():
    """9/4 frames packs exactly as tempo 9 at -S4; compensating it again would
    double-count."""
    sp = _speeds([2], [8])
    assert effective_frames(sp, 0, True) == Fraction(9, 4)
    assert regrid_deficits(sp, [9], True, 4) == [0.0]


def test_no_speeds_owes_nothing():
    assert regrid_deficits(None, [4, 4], True, 2) == [0.0, 0.0]


@needs_corpus
def test_star_paws_reads_a_stalled_clock_and_owes_two_127ths_of_a_frame():
    sid = load_sid(str(STAR_PAWS))
    stall = bytes.fromhex("CE12B71008A97F8D12B74C6BB0")
    assert stall in sid.data, "the one-in-128 stall at $B053 is not there"
    sp = find_song_speeds(sid)
    assert sp.frames_for(0) == 2 and sp.skip_for(0) == 127
    assert sp.exact_row(0) == Fraction(256, 127)
    assert regrid_deficits(sp, [4], True, 2)[0] == pytest.approx(2 / 127)


@needs_corpus
def test_regrid_reaches_star_paws_at_s2():
    """The end-to-end symptom: `--regrid` on a -S2 file now writes rows."""
    import json
    sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[1]))
    import fidelity
    doc = json.loads((pathlib.Path(__file__).resolve().parents[2]
                      / "presets.json").read_text(encoding="utf-8"))
    opts = fidelity._preset_opts(doc, "Star_Paws.sid")
    assert fidelity._preset_multiplier(doc, "Star_Paws.sid") == 2
    opts["regrid"] = False
    off = convert(str(STAR_PAWS), log=lambda m: None, **opts)
    lines = []
    opts["regrid"] = True
    on = convert(str(STAR_PAWS), log=lines.append, **opts)
    rg = [ln for ln in lines if ln.startswith("Re-grid")]
    assert rg, "regrid_tempos was never called: the deficit read 0"
    assert int(rg[0].split(":")[1].split()[0]) > 0, rg[0]
    assert on != off
