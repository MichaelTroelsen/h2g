"""A file carrying N players: the dispatch is read, and each player's tables.

Every signature chain takes the FIRST match in the file, so a compilation of
several separately assembled players -- 5_Title_Tunes has five, behind a
`CMP #n / BNE / JSR abs / RTS` ladder at init $0B10 and play $0B40 -- had only
its first player's tables read, and players 1-4 were never read at all.
`detect.find_players` reads the ladder (and Commodore_64_Music_Examples'
pointer-pair spelling) as "this file carries N players" and re-runs the four
table chains with `find` anchored to each player's own code range.

Three things are pinned here, and the third is the one that decays quietly:

  1. The two spellings parse, on synthetic bytes and on the two corpus files,
     to the addresses the players' own operands name.
  2. Anchoring works: player k's tables lie inside player k's range, and
     5_Title_Tunes' five instrument tables are five different addresses.
  3. The CENSUS: over the corpus exactly those two files carry a dispatch,
     and on every other file `Detection.players` is empty -- so this reading
     can move nothing the byte-hash sees. It is detection only; conversion
     from `players` is the next task.

Commodore_64_Music_Examples is also a negative finding worth pinning: four of
its five players are not this ripper's engine at all (no `STA $D40x,Y` store
in any of their ranges), so only player 1 -- the one `detect()` already reads,
$1119 -- yields tables. That is a fact about the chains, not a defect in the
anchoring, and the test says which.
"""
import pathlib
import sys

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[1]))

from corpus import CORPUS, needs_corpus  # noqa: E402

from h2g import detect as D  # noqa: E402
from h2g.search import search_file  # noqa: E402
from h2g.sidfile import HLEN, SidFile, load_sid  # noqa: E402

FIVE = "5_Title_Tunes.sid"
C64ME = "Commodore_64_Music_Examples.sid"

LOAD = 0x1000


def _sid(image: bytes, init: int, play: int) -> SidFile:
    """A SidFile whose image sits at LOAD, with the header bytes zeroed."""
    data = bytes(HLEN - 1) + image
    return SidFile(path="synthetic", data=data, name="", author="",
                   released="", load_addr=LOAD, subtunes=1,
                   init_addr=init, play_addr=play)


def _rung(n: int, target: int, nops: int = 0, back: bool = False) -> bytes:
    rr = (0x100 - 0x20) if back else 4 + nops
    return (bytes([0xC9, n, 0xD0, rr]) + bytes([0xEA] * nops)
            + bytes([0x20, target & 0xFF, target >> 8, 0x60]))


def _quiet(_m):
    pass


# --- The ladder spelling, on synthetic bytes ------------------------------

def test_ladder_parses_rungs_nop_padding_and_a_backward_last_bne():
    image = bytearray(0x100)
    ladder = (bytes([0x8D, 0x6F, 0x10])            # STA var, as 5_Title_Tunes
              + _rung(0, 0x1040) + _rung(1, 0x1060, nops=3)
              + _rung(2, 0x1080, back=True))
    image[0:len(ladder)] = ladder
    sid = _sid(bytes(image), LOAD, LOAD)
    assert D._read_ladder(sid, LOAD) == ((0, 0x1040), (1, 0x1060), (2, 0x1080))


def test_ladder_needs_two_rungs_and_a_forward_bne_that_lands_on_the_next():
    one = bytearray(0x100)
    one[0:8] = _rung(0, 0x1040)
    assert D._read_ladder(_sid(bytes(one), LOAD, LOAD), LOAD) is None
    # Two rungs, but the first BNE skips one byte too many: not a ladder.
    bad = bytearray(0x100)
    r = bytearray(_rung(0, 0x1040)); r[3] = 5
    bad[0:8] = r
    bad[8:16] = _rung(1, 0x1060)
    assert D._read_ladder(_sid(bytes(bad), LOAD, LOAD), LOAD) is None
    # A JSR whose target is outside the image ends the ladder short.
    out = bytearray(0x100)
    out[0:8] = _rung(0, 0x1040)
    out[8:16] = _rung(1, 0xF000)
    assert D._read_ladder(_sid(bytes(out), LOAD, LOAD), LOAD) is None


def test_dispatch_needs_both_ladders():
    image = bytearray(0x100)
    image[0:16] = _rung(0, 0x1040) + _rung(1, 0x1060)
    # play address points at zeros: the init ladder alone is not a dispatch
    assert D.find_player_dispatch(_sid(bytes(image), LOAD, LOAD + 0x80)) is None
    image[0x20:0x30] = _rung(0, 0x1041) + _rung(1, 0x1061)
    disp = D.find_player_dispatch(_sid(bytes(image), LOAD, LOAD + 0x20))
    assert disp is not None and disp.kind == "ladder"
    assert disp.plays == ((0, 0x1041), (1, 0x1061))


# --- The window ------------------------------------------------------------

def test_windowed_search_over_the_whole_file_is_search_file():
    data = bytes([0x00, 0xBD, 0x10, 0x20, 0x99, 0x02, 0xD4, 0xBD, 0x11, 0x20,
                  0x99, 0x03, 0xD4, 0x00])
    shape = "BD ?? ?? 99 02 D4"
    assert D._windowed_search(data, 0, len(data))(shape) == search_file(data, shape) == 1
    # Offset 0 is never tested, exactly as search_file never tests it.
    assert D._windowed_search(data[1:], 0, len(data) - 1)(shape) == -1


def test_windowed_search_finds_a_match_at_the_window_start_and_none_before_it():
    hit = bytes([0xBD, 0x10, 0x20, 0x99, 0x02, 0xD4])
    data = bytes(8) + hit + bytes(8) + hit + bytes(8)
    shape = "BD ?? ?? 99 02 D4"
    assert D._windowed_search(data, 0, len(data))(shape) == 8
    assert D._windowed_search(data, 22, len(data))(shape) == 22      # at lo itself
    assert D._windowed_search(data, 9, len(data))(shape) == 22       # not before lo
    assert D._windowed_search(data, 9, 27)(shape) == -1              # cut off by hi


# --- The two corpus files ------------------------------------------------------

@needs_corpus
def test_5_title_tunes_ladder_names_five_inits_and_five_plays():
    sid = load_sid(str(CORPUS / FIVE))
    disp = D.find_player_dispatch(sid)
    assert disp is not None and disp.kind == "ladder"
    assert disp.inits == ((0, 0x1850), (1, 0x1FA9), (2, 0x280C),
                          (3, 0x310C), (4, 0x38CF))
    assert disp.plays == ((0, 0x0C06), (1, 0x18A3), (2, 0x1FFC),
                          (3, 0x283C), (4, 0x315F))


@needs_corpus
def test_5_title_tunes_carries_five_players_each_with_its_own_tables():
    sid = load_sid(str(CORPUS / FIVE))
    det = D.detect(sid, _quiet)
    assert [p.play for p in det.players] == [0x0C06, 0x18A3, 0x1FFC, 0x283C, 0x315F]
    assert [p.inits for p in det.players] == [(0x1850,), (0x1FA9,), (0x280C,),
                                              (0x310C,), (0x38CF,)]
    assert [p.subtunes for p in det.players] == [(0,), (1,), (2,), (3,), (4,)]
    assert [p.instr_addr for p in det.players] == \
        [0x1065, 0x1D02, 0x245B, 0x2C9B, 0x35BE]
    assert [p.pattern_lo_addr for p in det.players] == \
        [0x10F1, 0x1D8E, 0x24E7, 0x2D27, 0x364A]
    for p in det.players:
        assert p.instr_used > 0 and p.pattern_used > 0
        assert p.track_lo_addr > 0 and p.track_hi_addr > 0
        # Anchored: every table lies in the range it was searched in, which
        # is what a chain taking the first match in the file cannot promise.
        lo, hi = sid.to_address(p.start), sid.to_address(p.end - 1)
        for a in (p.instr_addr, p.track_lo_addr, p.track_hi_addr,
                  p.pattern_lo_addr, p.pattern_hi_addr):
            assert lo <= a <= hi, f"player {p.index}: ${a:X} outside ${lo:X}-${hi:X}"
    # Player 0 IS the reading detect() has always taken from this file: the
    # first match in the file is the first player's. Detection only.
    p0 = det.players[0]
    assert sid.to_offset(p0.instr_addr) == det.instr_start
    assert p0.instr_used == det.instr_used
    assert sid.to_offset(p0.track_lo_addr) == det.track_lo
    assert sid.to_offset(p0.pattern_lo_addr) == det.pattern_lo
    assert p0.pattern_used == det.pattern_used


@needs_corpus
def test_c64me_table_dispatch_names_fifteen_inits_and_five_plays():
    sid = load_sid(str(CORPUS / C64ME))
    disp = D.find_player_dispatch(sid)
    assert disp is not None and disp.kind == "table"
    assert [a for _, a in disp.plays] == [0x0903, 0x1119, 0x1D8B, 0x2A23, 0x33DB]
    assert [n for n, _ in disp.inits] == list(range(15))
    assert [a for _, a in disp.inits][:4] == [0x10E5, 0x1337, 0x2915, 0x2B99]
    det = D.detect(sid, _quiet)
    assert [p.subtunes for p in det.players] == \
        [(0,), (1,), (2,), (3,), tuple(range(4, 15))]
    # Only player 1 is this ripper's engine; detect() already reads it, and
    # the anchored reading names the same tables. The other four ranges hold
    # no `STA $D40x,Y` at all (see tests/test_c64me_instrument_table.py).
    assert [p.instr_addr for p in det.players] == [-1, 0x1D1D, -1, -1, -1]
    assert [p.pattern_lo_addr for p in det.players] == [-1, 0x143C, -1, -1, -1]
    p1 = det.players[1]
    assert sid.to_offset(p1.instr_addr) == det.instr_start
    assert sid.to_offset(p1.track_lo_addr) == det.track_lo == sid.to_offset(0x1436)
    assert sid.to_offset(p1.pattern_lo_addr) == det.pattern_lo


# --- The census ----------------------------------------------------------------

@needs_corpus
def test_census_exactly_two_corpus_files_carry_a_dispatch():
    """Pinned as a SET, and per spelling, so a widened reader says which file."""
    ladder_init, ladder_play, table, players = set(), set(), set(), {}
    for path in sorted(CORPUS.glob("*.sid")):
        sid = load_sid(str(path))
        if D._read_ladder(sid, sid.init_addr):
            ladder_init.add(path.name)
        if D._read_ladder(sid, sid.play_addr):
            ladder_play.add(path.name)
        if D._read_table_dispatch(sid) is not None:
            table.add(path.name)
        got = D.find_players(sid, D.Detection())
        if got:
            players[path.name] = len(got)
    assert ladder_init == ladder_play == {FIVE}
    assert table == {C64ME}
    assert players == {FIVE: 5, C64ME: 5}
