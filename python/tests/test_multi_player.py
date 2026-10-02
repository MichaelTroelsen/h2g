"""A file carrying N players: the dispatch is read, and each player's tables.

Every signature chain takes the FIRST match in the file, so a compilation of
several separately assembled players -- 5_Title_Tunes has five, behind a
`CMP #n / BNE / JSR abs / RTS` ladder at init $0B10 and play $0B40 -- had only
its first player's tables read, and players 1-4 were never read at all.
`detect.find_players` reads the ladder (and Commodore_64_Music_Examples'
pointer-pair spelling) as "this file carries N players" and re-runs the four
table chains with `find` anchored to each player's own code range.

Four things are pinned here, and the third is the one that decays quietly:

  1. The two spellings parse, on synthetic bytes and on the two corpus files,
     to the addresses the players' own operands name.
  2. Anchoring works: player k's tables lie inside player k's range, and
     5_Title_Tunes' five instrument tables are five different addresses.
  3. The CENSUS: over the corpus exactly those two files carry a dispatch,
     and on every other file `Detection.players` is empty -- so nothing
     built on this reading can move another file's bytes.
  4. CONVERSION: `convert` appends players 1-4 of 5_Title_Tunes as subtunes
     1-4, each from a `detect.player_view` of its own window, merged into the
     one instrument list, pattern list and tables by `goatwriter.append_song`.
     Subtune 0's bytes are the unmerged conversion's, and each appended
     subtune plays what its player converted alone plays (`_canon`).

Commodore_64_Music_Examples is also a negative finding worth pinning: four of
its five players are not this ripper's engine at all (no `STA $D40x,Y` store
in any of their ranges), so only player 1 -- the one `detect()` already reads,
$1119 -- yields tables. That is a fact about the chains, not a defect in the
anchoring, and the test says which.
"""
import pathlib
import sys

import pytest

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
    # first match in the file is the first player's.
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


# --- Conversion: appending a song ----------------------------------------------

from h2g import goatwriter as G  # noqa: E402

GTS5_HEADER = b"GTS5" + bytes(G.HEADER_LEN - 4)


def _rec(ad, sr, wave, pulse, filt, speed, name=b"x"):
    return bytearray([ad, sr, wave, pulse, filt, speed, 0, 2, 0x09]
                     + list(name.ljust(16, b"\x00")))


def _song(tracks, instruments, tables, patterns):
    return G._write_song(G._Song(b"GTS5", GTS5_HEADER, tracks, instruments,
                                 tables, patterns))


def _row(note, ins=0, cmd=0, data=0):
    return bytes([note, ins, cmd, data])


END_ROW = _row(0xFF)


def _base_song():
    return _song([bytes([0, 0xFF, 0])] * 3,
                 [_rec(0x11, 0x22, 1, 1, 0, 0, b"base")],
                 [[(0x41, 0x00), (0xFF, 0x00)],          # wave
                  [(0x88, 0x00), (0xFF, 0x00)],          # pulse
                  [],                                    # filter
                  [(0x01, 0x02)]],                       # speed
                 [bytearray(_row(0x60, 1) + END_ROW)])


def test_append_song_renumbers_every_reference():
    base = _base_song()
    extra = _song(
        [bytes([0, 0xD1, 1, 0xE2, 0, 0xFF, 1])] * 3,
        [_rec(0x0A, 0x0B, 1, 1, 1, 1, b"one"),
         _rec(0x0C, 0x0D, 3, 3, 0, 2, b"two")],
        [[(0x21, 0x00), (0xFF, 0x01),                   # loops onto itself
          (0xF9, 0x03), (0xF4, 0x02), (0xFF, 0x00)],    # names pulse, speed
         [(0x84, 0x00), (0xFF, 0x00), (0x8C, 0xA0), (0xFF, 0x00)],
         [(0x90, 0xF1), (0xFF, 0x00)],
         [(0x07, 0x08), (0x09, 0x0A)]],
        [bytearray(_row(0x61, 2, 0x1, 0x01) + END_ROW),
         bytearray(_row(0x62, 1, 0x8, 0x03) + _row(0xBD, 0, 0x9, 0x03)
                   + _row(0xBD, 0, 0xA, 0x01) + _row(0xBD, 0, 0x3, 0x00)
                   + END_ROW)])
    out = G.append_song(base, extra, tag="1/")
    a, m = G._parse_song(base), G._parse_song(out)
    # The base is a prefix of every list, untouched.
    assert m.tracks[:3] == a.tracks
    assert m.instruments[:1] == a.instruments
    assert all(m.tables[t][:len(a.tables[t])] == a.tables[t] for t in range(4))
    assert m.patterns[:1] == a.patterns
    # Orderlist: patterns +1, the repeat/transpose/terminator/restart kept.
    assert m.tracks[3] == bytes([1, 0xD1, 2, 0xE2, 1, 0xFF, 1])
    # Tables: wave rows 3.., pulse 3.., filter 1.., speed 2..; the jumps and
    # the wavetable's command operands follow their targets.
    assert m.tables[0][2:] == [(0x21, 0x00), (0xFF, 0x03), (0xF9, 0x05),
                               (0xF4, 0x03), (0xFF, 0x00)]
    assert m.tables[1][2:] == [(0x84, 0x00), (0xFF, 0x00), (0x8C, 0xA0),
                               (0xFF, 0x00)]
    assert m.tables[2] == [(0x90, 0xF1), (0xFF, 0x00)]
    assert m.tables[3] == [(0x01, 0x02), (0x07, 0x08), (0x09, 0x0A)]
    one, two = m.instruments[1], m.instruments[2]
    assert list(one[:6]) == [0x0A, 0x0B, 3, 3, 1, 2]
    assert list(two[:6]) == [0x0C, 0x0D, 5, 5, 0, 3]
    assert bytes(two[9:]).rstrip(b"\x00") == b"1/two"
    # Patterns: instrument column +1; 1-4 speed, 8/9/A pointers moved; the
    # toneportamento's 0 (tie) stays 0.
    assert bytes(m.patterns[1]) == _row(0x61, 3, 0x1, 0x02) + END_ROW
    assert bytes(m.patterns[2]) == (_row(0x62, 2, 0x8, 0x05)
                                    + _row(0xBD, 0, 0x9, 0x05)
                                    + _row(0xBD, 0, 0xA, 0x01)
                                    + _row(0xBD, 0, 0x3, 0x00) + END_ROW)


def test_append_song_points_at_rows_and_records_already_there():
    """An identical song adds no table row and no instrument -- only its
    patterns, naming the base's records."""
    base = _base_song()
    out = G.append_song(base, base)
    m = G._parse_song(out)
    assert len(m.instruments) == 1
    assert [len(t) for t in m.tables] == [2, 2, 0, 1]
    assert len(m.patterns) == 2 and m.patterns[1] == m.patterns[0]
    assert m.tracks[3] == bytes([1, 0xFF, 0])


def test_append_song_copies_no_row_nothing_reaches():
    base = _base_song()
    extra = _song([bytes([0, 0xFF, 0])] * 3,
                  [_rec(0x0A, 0x0B, 3, 0, 0, 0)],
                  [[(0x11, 0x00), (0xFF, 0x00), (0x21, 0x00), (0xFF, 0x00)],
                   [], [], []],
                  [bytearray(_row(0x60, 1) + END_ROW)])
    m = G._parse_song(G.append_song(base, extra))
    assert m.tables[0] == [(0x41, 0x00), (0xFF, 0x00), (0x21, 0x00), (0xFF, 0x00)]
    assert m.instruments[1][2] == 3


def test_append_song_refuses_past_the_instrument_cap():
    base = _song([bytes([0, 0xFF, 0])] * 3,
                 [_rec(k, 0, 1, 0, 0, 0) for k in range(G.GT_MAX_INSTRUMENTS)],
                 [[(0x41, 0x00), (0xFF, 0x00)], [], [], []],
                 [bytearray(_row(0x60, 1) + END_ROW)])
    extra = _song([bytes([0, 0xFF, 0])] * 3, [_rec(0xEE, 0xEE, 1, 0, 0, 0)],
                  [[(0x41, 0x00), (0xFF, 0x00)], [], [], []],
                  [bytearray(_row(0x60, 1) + END_ROW)])
    lines = []
    assert G.append_song(base, extra, tag="9/", log=lines.append) is None
    assert any("64 instruments > 63" in l for l in lines), lines


def test_a_voice_that_opens_on_rests_is_pinned_to_its_own_first_record():
    """Row 0 of the first pattern names instrument 1 -- in place where every
    other play enters holding 1 anyway, in a copy where one does not."""
    rest, note2 = _row(0xBD), _row(0x60, 2)
    shared = bytearray(rest + _row(0x60, 1) + END_ROW)
    other = bytearray(rest + note2 + END_ROW)
    song = G._Song(b"GTS5", GTS5_HEADER,
                   [bytes([0, 0xFF, 0]),          # voice 1: shared, alone
                    bytes([1, 0, 0xFF, 0]),       # voice 2: other, then shared
                    bytes([0, 0xFF, 0])],
                   [_rec(1, 1, 0, 0, 0, 0), _rec(2, 2, 0, 0, 0, 0)],
                   [[], [], [], []], [shared, other])
    assert G._pin_start_instruments(song) is None
    # Pattern 0 is entered holding 2 on voice 2 (after `other`), so voices 1
    # and 3 get a copy; pattern 1 is only ever entered holding 1: in place.
    assert song.patterns[1][1] == 1
    assert song.patterns[0][1] == 0
    assert len(song.patterns) == 3 and song.patterns[2][1] == 1
    assert song.tracks[0][0] == 2 and song.tracks[2][0] == 2
    assert song.tracks[1] == bytes([1, 0, 0xFF, 0])


# --- Conversion: 5_Title_Tunes -------------------------------------------------

REPO_ROOT = pathlib.Path(__file__).resolve().parents[2]


def _run(table, ptr):
    """Rows from 1-based `ptr` to its `$FF`, the jump relative to `ptr`."""
    rows, i = [], ptr - 1
    while 0 <= i < len(table):
        left, right = table[i]
        if left == 0xFF:
            rows.append((left, right - ptr if right else None))
            break
        rows.append((left, right))
        i += 1
    return tuple(rows)


def _canon_wave(song, ptr):
    out = []
    for left, right in _run(song.tables[0], ptr):
        if left == 0xF9 and right:
            right = _run(song.tables[1], right)
        elif left == 0xFA and right:
            right = _run(song.tables[2], right)
        elif left in (0xF1, 0xF2, 0xF3, 0xF4) and right:
            right = song.tables[3][right - 1]
        out.append((left, right))
    return tuple(out)


def _canon_instr(song, n):
    r = song.instruments[n - 1]
    return (r[0], r[1],
            _canon_wave(song, r[2]) if r[2] else None,
            _run(song.tables[1], r[3]) if r[3] else None,
            _run(song.tables[2], r[4]) if r[4] else None,
            song.tables[3][r[5] - 1] if r[5] else None,
            r[6], r[7], r[8])


def _canon(song, k):
    """Subtune k as it plays: every row with the instrument the voice HOLDS
    (Goattracker starts it on 1), every table reference replaced by the rows
    it names. Numbering-free, so a merged subtune and the same player
    converted alone compare equal exactly when they play the same."""
    out = []
    for v in range(3):
        track = song.tracks[3 * k + v]
        plays, restart = G._pattern_plays(track)
        held, voice = 1, []
        for _pos, x, times in plays:
            for _ in range(times):
                rows = []
                p = song.patterns[x]
                for r in range(0, len(p), 4):
                    note, ins, cmd, data = p[r:r + 4]
                    held = ins or held
                    if cmd == 0x8 and data:
                        data = _canon_wave(song, data)
                    elif cmd in (0x9, 0xA) and data:
                        data = _run(song.tables[cmd - 0x8], data)
                    elif cmd in (0x1, 0x2, 0x3, 0x4, 0xE) and data:
                        data = song.tables[3][data - 1]
                    rows.append((note, _canon_instr(song, held), cmd, data))
                voice.append(tuple(rows))
        end = track.index(0xFF)
        out.append((tuple(voice), tuple(x for x in track[:end] if x >= 0xE0),
                    end, restart))
    return out


@pytest.fixture(scope="module")
def five():
    import json
    import warnings
    from h2g import convert as C
    presets = REPO_ROOT / "presets.json"
    if not (CORPUS.is_dir() and presets.is_file()):
        pytest.skip("corpus or presets.json not available here")
    with warnings.catch_warnings():
        warnings.simplefilter("ignore")
        import fidelity
        opts = fidelity._preset_opts(json.loads(presets.read_text()), FIVE)
    path = str(CORPUS / FIVE)
    lines = []
    merged = C.convert(path, log=lines.append, **opts)
    real = C._append_players
    C._append_players = lambda sng, *a, **k: sng
    try:
        alone = C.convert(path, log=_quiet, **opts)
    finally:
        C._append_players = real
    return opts, merged, alone, lines


@needs_corpus
def test_5_title_tunes_carries_one_subtune_per_player(five):
    _opts, merged, alone, lines = five
    assert alone[G.HEADER_LEN] == 1 and merged[G.HEADER_LEN] == 5
    assert any(l.startswith("Players.................: 4 of 4 further")
               for l in lines), [l for l in lines if "layer" in l]
    m = G._parse_song(merged)
    assert len(m.instruments) <= G.GT_MAX_INSTRUMENTS
    assert len(m.patterns) <= 0xD0
    assert all(len(t) <= cap for t, cap in zip(
        m.tables, (G.GT_MAX_TABLELEN, G.GT_MAX_TABLELEN, G.GT_MAX_FILT,
                   G.GT_MAX_TABLELEN)))


@needs_corpus
def test_5_title_tunes_subtune_0_is_the_unmerged_conversion_byte_for_byte(five):
    _opts, merged, alone, _lines = five
    a, m = G._parse_song(alone), G._parse_song(merged)
    assert m.tracks[:3] == a.tracks
    assert m.instruments[:len(a.instruments)] == a.instruments
    for t in range(4):
        assert m.tables[t][:len(a.tables[t])] == a.tables[t], t
    assert m.patterns[:len(a.patterns)] == a.patterns


@needs_corpus
def test_5_title_tunes_subtune_k_plays_what_player_k_converts_to_alone(five):
    """Each appended subtune against the same player's view converted on its
    own, at the level `_append_players` settled on (read off its log)."""
    from h2g import convert as C
    opts, merged, _alone, lines = five
    level = next(l for l in lines
                 if l.startswith("Players.................: 4 of 4"))
    view_opts = dict(opts, real_firstwave_instruments=(),
                     drop_unnamed_instruments=False)
    if "without pulse_phase" in level or "without pulse sweeps" in level:
        view_opts["pulse_phase"] = False
    if "without pulse sweeps" in level:
        view_opts["pulse"] = False
    sid = load_sid(str(CORPUS / FIVE))
    det = D.detect(sid, _quiet)
    m = G._parse_song(merged)
    for k in range(1, 5):
        view = D.player_view(sid, det.players, k, 1)
        alone = G._parse_song(C.convert(view, log=_quiet, **view_opts))
        assert len(alone.tracks) == 3
        assert _canon(m, k) == _canon(alone, 0), f"subtune {k}"


@needs_corpus
def test_a_player_view_is_its_window_and_its_own_header():
    sid = load_sid(str(CORPUS / FIVE))
    det = D.detect(sid, _quiet)
    assert D.read_init_call(sid, 0x1FA9) == (0, 0x189D)
    view = D.player_view(sid, det.players, 1, 1)
    lo, hi = sid.to_offset(0x189D), sid.to_offset(0x1FF6)
    assert view.data[lo:hi] == sid.data[lo:hi]
    assert not any(view.data[HLEN - 1:lo]) and not any(view.data[hi:])
    assert (view.init_addr, view.play_addr, view.subtunes, view.start_song) \
        == (0x1FA9, 0x18A3, 1, 1)
    assert view.speed == 0 and D.player_view(sid, det.players, 2, 1).speed == 1
    assert view.pack_multiplier == 1 and view.player == 1
    vdet = D.detect(view, _quiet)
    assert vdet.players == ()                      # no dispatch, no recursion
    assert vdet.instr_start == sid.to_offset(0x1D02)
    assert vdet.pattern_lo == sid.to_offset(0x1D8E)


@needs_corpus
def test_a_view_is_converted_at_the_compilations_pack_factor():
    """Player 1's rows want -S2 on their own; inside a -S1 file its tempo is
    worked out at -S1, clamped to the fastest steady row, like any
    non-starting subtune's."""
    from h2g.convert import _detect_tables
    sid = load_sid(str(CORPUS / FIVE))
    det = D.detect(sid, _quiet)
    view = D.player_view(sid, det.players, 1, 1)
    vs, vdet = _detect_tables(view, _quiet)
    speeds = G.find_song_speeds(vs, vdet)
    assert G.recommended_multiplier(speeds, 0, True) == 2
    assert G.file_multiplier(vs, speeds, True) == 1
    values, mult, _ = G.derived_group_tempos(vs, vdet, 1, True)
    assert (values, mult) == ([G.TEMPO_FASTEST_STEADY], 1)


@needs_corpus
def test_c64me_appends_nothing_because_its_subtune_0_is_not_player_0():
    from h2g import convert as C
    lines = []
    sng = C.convert(str(CORPUS / C64ME), log=lines.append)
    assert sng[G.HEADER_LEN] == 1
    assert any("subtune 0 was not read from the first; nothing appended" in l
               for l in lines)
