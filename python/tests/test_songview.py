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


# --- the comparison overlay (v0.5.242) -------------------------------------

def _delta(number, adsr, orig, ours, kind, paired="adsr", effect=0x01,
           declares=0x41, orig_notes=10, our_notes=10):
    return songview.InstrumentDelta(
        number=number, adsr=adsr, effect=effect, declares=declares,
        orig_shape=orig, our_shape=ours, orig_notes=orig_notes,
        our_notes=our_notes, kind=kind, paired=paired)


def test_an_exact_adsr_is_paired_with_itself():
    assert songview.pair_by_adsr({0x064B}, {0x064B}) == [(0x064B, 0x064B, "adsr")]


def test_a_release_that_cut_release_zeroed_still_pairs():
    """The key contains the release nibble and `--cut-release` changes it, so
    Commando's `$295F` and our `$2950` are one instrument. Keyed exactly it is
    two rows, one flagged 'ours only' and one 'original only' -- two false
    flags for an instrument that agrees, which is what this page showed the
    first time it ran."""
    assert songview.pair_by_adsr({0x295F}, {0x2950}) == [(0x295F, 0x2950, "ad+s")]


def test_an_ambiguous_release_match_is_refused_rather_than_guessed():
    """Two candidates sharing AD+sustain: which of them the trace heard is a
    guess, and a wrong pairing is a wrong row. Left unpaired instead."""
    got = songview.pair_by_adsr({0x295F, 0x2951}, {0x2950})
    assert all(how == "adsr" for _, _, how in got)
    assert (0x295F, 0x2950, "ad+s") not in got
    assert set(got) == {(None, 0x2950, "adsr"), (0x2951, None, "adsr"),
                        (0x295F, None, "adsr")}


def test_an_instrument_only_one_side_sounds_keeps_its_row():
    assert songview.pair_by_adsr({0x1111}, {0x2222}) == [
        (0x1111, None, "adsr"), (None, 0x2222, "adsr")]


def test_the_overlay_sorts_disagreements_first_and_links_to_the_card():
    tri, noi = 0x10, 0x80
    deltas = [
        _delta(2, 0x064B, (tri,) * 4, (tri,) * 4, "match"),
        _delta(11, 0x0800, (tri, noi, tri, noi), (tri,) * 4, "flat"),
        _delta(3, 0x0A00, (tri,) * 4, (tri,) * 4, "match"),
    ]
    deltas.sort(key=lambda d: (not d.flagged, d.number))
    html = songview._comparison_section(deltas)
    assert html.index("cmp11") < html.index("cmp2"), "flagged rows come first"
    assert "href='#ins11'" in html, "each row links to its instrument card"
    assert "1 of 3 disagree" in html


def test_a_row_paired_on_the_release_says_so():
    """A pairing rule is a claim, so the page has to make it."""
    html = songview._comparison_section(
        [_delta(1, 0x2950, (0x40,) * 4, (0x40,) * 4, "match", paired="ad+s")])
    assert "*" in html and "--cut-release" in html


def test_the_page_without_a_comparison_is_unchanged(commando):
    """`--compare` is opt-in: it needs siddump and gt2reloc, and the page's
    whole point is that reading bytes off disk cannot be wrong."""
    assert "Original against ours" not in songview.render(commando, "Commando")
    assert "Original against ours" in songview.render(
        commando, "Commando", None,
        [_delta(1, 0x2950, (0x40,) * 4, (0x40,) * 4, "match")])
