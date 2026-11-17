"""A track's first note has no predecessor and so casts no vote
(h2g.prev_class_firstwave).

`prev_class_firstwave` visits every note init in play order, the restart lap
included, and a pattern row several visits reach takes the clone the majority
of them want. The song's FIRST note is visited with nothing before it (the chip
is unknown), and it used to log a "keep the record" vote all the same -- which
tied the restart lap's real vote (the loop plays that row after the track's
last note) and kept the record, so every loop's note played the record's own
class on the frame before its attack.

Hollywood_or_Bust sub 2 voice 1 is one 8-row pattern looped: row 0 (`$0A`, a
triangle/noise alternation) follows a `$0C` note, and `$0C` ends on the
alternation's noise half, so the original's frame before every attack of `$0A`
reads `$84` (noise + ring) where ours read `$10`: 374 frames, the whole of that
file's remaining `wave` disagreement (.9861 at v0.5.668, 1.0000 with the vote
dropped). The player's own reason: `$0774` writes `AND #$07 / ORA #$80` of the
voice's waveform whenever the global frame counter `$09A2` is odd, `$09A2` is
bumped once per frame at `$0417`, and notes of 6 calls end on an odd counter, so
the note's last call is the noise one and the next note's init frame still shows it.
"""
import json
import pathlib
import sys

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[1]))

import songview                                              # noqa: E402
from corpus import CORPUS, needs_corpus                      # noqa: E402
from h2g.convert import convert                              # noqa: E402
from test_prev_class_firstwave import (                      # noqa: E402
    C4, instrument_column, parsed, run, song)


def test_the_loops_note_after_the_tail_takes_the_tails_class():
    # A is noise, B pulse, the song loops A, B, A, B ... The first A has
    # nothing before it; every later A follows B's pulse, and that is the
    # row's only evidence.
    sng = parsed(run(song([(C4, 1, 0, 0), (C4, 2, 0, 0)])))
    col = instrument_column(sng)
    assert col[0] == 4, "row 0 must take a clone (it used to tie and keep A)"
    assert sng.instruments[col[0] - 1].firstwave == 0x40
    assert sng.instruments[col[0] - 1].wave_ptr == sng.instruments[0].wave_ptr


def test_a_pattern_that_is_never_revisited_is_still_left_alone():
    # The only visit of a row that has no predecessor at all is no evidence
    # either way: nothing is retargeted from it.
    sng = parsed(run(song([(C4, 1, 0, 0)])))
    assert instrument_column(sng)[0] == 1


@needs_corpus
def test_hollywood_voice_one_plays_the_noise_class_clone_after_the_alternation():
    import fidelity
    repo = pathlib.Path(__file__).resolve().parents[2]
    doc = json.loads((repo / "presets.json").read_text(encoding="utf-8"))
    name = "Hollywood_or_Bust.sid"
    opts = fidelity._preset_opts(doc, name)
    assert opts["prev_class_firstwave"] and opts["wave_alternate"]
    sng = songview.parse_sng(convert(str(CORPUS / name), log=lambda m: None,
                                     **opts))
    order = sng.tracks[7]                    # subtune 2, voice 1
    pattern = sng.patterns[order[0]]
    ins = pattern[1]                         # row 0's instrument column
    assert ins and ins <= len(sng.instruments)
    record = sng.instruments[ins - 1]
    assert record.firstwave & 0xF0 == 0x80, (
        f"row 0 plays instrument {ins} with firstwave ${record.firstwave:02X}; "
        "the original shows noise ($84) on the frame before the attack")
