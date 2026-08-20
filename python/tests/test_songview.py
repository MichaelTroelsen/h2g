"""`songview.parse_sng` against what `goatwriter.build_sng` actually writes.

The parser is deliberately a second reader rather than a re-use of the
writer's internals -- a parser sharing code with the thing it reads cannot
disagree with it, and disagreeing is the whole value. That only works if
something checks the two against each other, which is this.
"""

import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

import songview                                  # noqa: E402
from h2g.convert import convert                  # noqa: E402
from h2g.goatwriter import GT_FIRST_NOTE         # noqa: E402

REPO = ROOT.parent
COMMANDO = REPO / "Commando.sid"


@pytest.fixture(scope="module")
def commando():
    return songview.parse_sng(convert(str(COMMANDO), log=lambda m: None))


def test_header_round_trips(commando):
    assert commando.fmt == "GTS2"
    assert commando.name
    assert commando.subtunes >= 1
    assert len(commando.tracks) == commando.subtunes * 3


def test_pattern_count_matches_the_reference_file(commando):
    """The byte-exact fixture is the anchor, so the parser must agree with it."""
    ref = songview.parse_sng((REPO / "Commando.sng").read_bytes())
    assert len(commando.patterns) == len(ref.patterns)
    assert commando.patterns == ref.patterns
    assert len(commando.instruments) == len(ref.instruments)


def test_every_pattern_row_is_four_bytes(commando):
    for pat in commando.patterns:
        assert len(pat) % 4 == 0


def test_gts2_has_three_tables_and_gts5_has_four():
    gts2 = songview.parse_sng(convert(str(COMMANDO), log=lambda m: None,
                                      fmt="gts2"))
    gts5 = songview.parse_sng(convert(str(COMMANDO), log=lambda m: None,
                                      fmt="gts5"))
    assert set(gts2.tables) == {"WTBL", "PTBL", "FTBL"}
    assert set(gts5.tables) == {"WTBL", "PTBL", "FTBL", "STBL"}


def test_instrument_name_carries_the_effect_byte(commando):
    """`_write_instruments` stamps `NN:b5-b6-b7`, and b7 is the effect byte.

    That stamp is the only provenance the .sng carries, and the viewer decodes
    its bits -- so a change to the name format silently blinds the viewer.
    """
    named = [i for i in commando.instruments if i.effect_byte is not None]
    assert named, "no instrument carried a decodable provenance stamp"
    for ins in named:
        assert 0 <= ins.effect_byte <= 0xFF


def test_clear_voice_placeholder_declines_rather_than_guesses(commando):
    """Instrument 1 is the hardcoded placeholder; it has no source record."""
    assert commando.instruments[0].name.startswith("Clear")
    assert commando.instruments[0].effect_byte is None
    assert commando.instruments[0].effects == []


def test_delay_entries_are_current_for_value_plus_one_calls():
    """gplay.c:697-704 -- the off-by-one that cost v0.5.82 through v0.5.130."""
    assert songview.decode_wave_entry(0x02, 0x80)[2] == 3
    assert songview.decode_wave_entry(0x01, 0x00)[2] == 2
    # Everything that is not a delay occupies exactly one call.
    assert songview.decode_wave_entry(0x41, 0x00)[2] == 1
    assert songview.decode_wave_entry(0xF2, 0x03)[2] == 1
    # A jump consumes none.
    assert songview.decode_wave_entry(0xFF, 0x05)[2] == 0


def test_wave_entry_kinds():
    assert songview.decode_wave_entry(0x41, 0x00)[0] == "wave"
    assert songview.decode_wave_entry(0x05, 0x80)[0] == "delay"
    assert songview.decode_wave_entry(0xF1, 0x02)[0] == "command"
    assert songview.decode_wave_entry(0xFF, 0x01)[0] == "jump"
    assert "the pattern's note" in songview.decode_wave_entry(0x41, 0x00)[1]
    assert "noise" in songview.decode_wave_entry(0x81, 0x00)[1]


def test_wave_program_walk_terminates_on_a_self_referential_jump():
    """A malformed table must not hang the viewer."""
    song = songview.Song(fmt="GTS5", name="", author="", released="",
                         subtunes=0, tracks=[], instruments=[],
                         tables={"WTBL": [(0xFF, 0x01)]}, patterns=[])
    prog = songview.wave_program(song, 1)
    assert len(prog) == 1
    assert prog[0][3] == "jump"


def test_note_names_anchor_at_gt_first_note():
    assert songview.note_name(GT_FIRST_NOTE) == "C-0"
    assert songview.note_name(GT_FIRST_NOTE + 12) == "C-1"
    assert songview.note_name(GT_FIRST_NOTE + 1) == "C#0"
    assert songview.note_name(0xBD) == "..."
    assert songview.note_name(0xFF) == "END"


def test_render_produces_self_contained_html(commando):
    page = songview.render(commando, "Commando")
    assert "<title>" in page and "<style>" in page
    # A strict CSP forbids external hosts; nothing here may reach one.
    for scheme in ("http://", "https://", "//cdn"):
        assert scheme not in page
    assert "Orderlists" in page and "Instruments" in page


def test_render_has_no_comparison_section(commando):
    """The original-vs-ours overlay moved to `instrmap.py` (v0.5.331): two
    tools joined the original's trace against ours on the ADSR pair, and
    `songview.py`'s own docstring already said it "judges nothing and scores
    nothing" -- a promise `--compare` broke. `instrmap.py` is now the one
    place that comparison is made, with `songview.py` back to a pure
    renderer of bytes already on disk."""
    assert "Original against ours" not in songview.render(commando, "Commando")
    assert not hasattr(songview, "compare_sides")
    assert not hasattr(songview, "InstrumentDelta")
    assert not hasattr(songview, "pair_by_adsr")
