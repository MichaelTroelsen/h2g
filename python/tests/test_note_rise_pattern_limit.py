"""Bit $02's note rise on a pattern that cannot take every pointer row.

Human_Race's patterns $50 and $53 hold 112 store rows each; with every row's
`CMD_SETWAVEPTR` they pack to 262 bytes against greloc's 256
(`PACKED_PATTERN_LIMIT`), and the planner used to decline BOTH patterns whole
("every pattern past the packed limit, not emitted"). Rows are now taken
first-fit in row order and the rest left on the vibrato.
"""
from corpus import CORPUS, needs_corpus
from test_note_rise import _converted



@needs_corpus
def test_human_race_takes_the_rows_that_fit_instead_of_none():
    sng, lines, _opts = _converted("Human_Race")
    rise = [m for m in lines if m.startswith("Note rise")]
    assert len(rise) == 1, rise
    assert "not emitted" not in rise[0], rise
    assert "store row(s) on instrument(s)" in rise[0], rise
    # The packed limit is no longer binding: the planner also tries the
    # duplicate-block rows when a first fit cut rows, and thinning the
    # pointers there takes all 224.
    assert "224 store row(s)" in rise[0], rise
    assert "past the packed limit" not in rise[0], rise
