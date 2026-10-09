"""Knucklebusters' `$FD a b` is a three-byte TEMPO command, not a terminator.

The orderlist reader at `$04B0` is

    CMP #$FD / BNE pattern
    INY / LDA (ptr),Y / STA $0980 / STA $0967     ; a: the speed gate
    INY / LDA (ptr),Y / STA $0468 / STA $0981     ; b: the outer gate
    INY / TYA / STA index,X / LDA (ptr),Y         ; then the pattern number

so it continues the list and changes the row length of EVERY voice to
`(a + 1) * (b + 1) / b` frames. Read as Rasputin's "this voice is done", subtune
0's voice 2 stopped at its first `$FD` (frame 18042 of the original's 30000) and
the other two voices never ran the faster tempo that follows: 2134 attacks
against the original's 3417 at -t 600, melody 77%.
"""
import json
import pathlib
import sys

import pytest

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[1]))

from corpus import CORPUS, needs_corpus                    # noqa: E402

import h2g.convert                                         # noqa: E402,F401
from h2g.detect import detect                              # noqa: E402
from h2g.goatwriter import (file_multiplier,               # noqa: E402
                            find_song_speeds,
                            orderlist_tempo_calls)
from h2g.sidfile import load_sid                           # noqa: E402
from h2g.tracks import _build_track, convert_tracks        # noqa: E402

ORDERLIST = bytes([0x05, 0xFD, 0x01, 0x02, 0x07, 0x08, 0xFF])


def test_fd_tempo_consumes_both_operands_and_continues():
    tempos = {}
    track = _build_track(ORDERLIST, 0, 0, fd_tempo=True, tempos=tempos)
    # Neither operand is a pattern number, and the list runs on to the $FF.
    assert track == [0x05, 0x07, 0x08, 0xFF, 0x00]
    # Keyed by the position of the entry the command takes effect at.
    assert tempos == {1: (1, 2)}


def test_fd_tempo_is_not_a_terminator_even_when_the_flag_for_one_is_set():
    """`fd_tempo` wins over `fd_ends` for the same byte: Knucklebusters' reader
    tests `#$FD` within reach of its `$FF` test, which is all
    `_find_track_terminators` can see."""
    track = _build_track(ORDERLIST, 0, 0, fd_ends=True, fd_tempo=True)
    assert track == [0x05, 0x07, 0x08, 0xFF, 0x00]
    assert _build_track(ORDERLIST, 0, 0, fd_ends=True) == [0x05, 0xFF, 0xFD]


def test_fd_tempo_with_the_operands_past_the_end_truncates():
    track = _build_track(bytes([0x05, 0xFD, 0x01]), 0, 0, fd_tempo=True)
    assert track == [0x05, 0xFF, 0x00]


@pytest.fixture(scope="module")
def knucklebusters():
    sid = load_sid(str(CORPUS / "Knucklebusters.sid"))
    return sid, detect(sid, lambda m: None, 0)


@needs_corpus
def test_only_knucklebusters_reads_fd_as_a_tempo(knucklebusters):
    """Rasputin and Tarzan keep the terminator reading (tests/test_tracks.py)."""
    _sid, det = knucklebusters
    # The CPU address of `a`'s first store: the speed gate's reload cell.
    assert det.track_fd_tempo == 0x0980
    assert not det.track_fd_ends
    for name in ("Rasputin", "Tarzan", "Commando"):
        other = detect(load_sid(str(CORPUS / f"{name}.sid")), lambda m: None, 0)
        assert other.track_fd_tempo == -1, name
    for name in ("Rasputin", "Tarzan"):
        other = detect(load_sid(str(CORPUS / f"{name}.sid")), lambda m: None, 0)
        assert other.track_fd_ends, name


@needs_corpus
def test_subtune_0_voice_2_runs_past_its_first_fd(knucklebusters):
    """The orderlist the original plays is 199 entries; read as a terminator it
    was 30, and the `$FD` pairs that follow were never seen."""
    sid, det = knucklebusters
    tempos = []
    tracks = convert_tracks(sid, det, lambda m: None, None, tempos)
    assert len(tracks[2]) > 100
    # Subtune 0 voice 2 carries eight, subtune 1 voice 2 three (back to back).
    assert tempos[2] == {50: (1, 2), 101: (1, 3), 116: (1, 3), 143: (1, 4),
                         159: (1, 8), 184: (1, 4), 188: (1, 2), 192: (2, 1)}
    assert tempos[5] == {41: (1, 4), 42: (1, 2), 43: (1, 1)}


@needs_corpus
def test_the_pair_becomes_a_row_length_in_both_gates(knucklebusters):
    """`(a + 1) * (b + 1) / b` frames, times the file's multiplier. The last
    command of subtune 0 voice 2, `$FD 02 01`, is the subtune's own opening
    clock (A = 2, B = 1: 6 frames) restored for the loop, so it must come out
    at exactly the opening row."""
    sid, det = knucklebusters
    tempos = []
    convert_tracks(sid, det, lambda m: None, None, tempos)
    speeds = find_song_speeds(sid, det)
    mult = file_multiplier(sid, speeds, True)
    calls = orderlist_tempo_calls(sid, det, tempos, "auto", True)[2]
    assert calls[192] == 6 * mult == speeds.exact_row(0) * mult
    assert calls[50] == 3 * mult           # $FD 01 02: 2 * 3 / 2
    assert calls[101] == pytest.approx(8 / 3 * mult)     # $FD 01 03
    assert calls[143] == pytest.approx(2.5 * mult)       # $FD 01 04
    assert calls[159] == pytest.approx(2.25 * mult)      # $FD 01 08
    # Without skip_gate the opening row is the bare speed gate's A + 1, so the
    # command drops the outer factor too: every row is a + 1 frames.
    bare = orderlist_tempo_calls(sid, det, tempos, "auto", False)[2]
    bare_mult = file_multiplier(sid, speeds, False)
    assert bare[50] == 2 * bare_mult and bare[192] == 3 * bare_mult


@needs_corpus
def test_a_command_storing_to_another_cell_declines(knucklebusters):
    """The pair is read only where `a` lands in the speed gate's reload cell."""
    from dataclasses import replace
    sid, det = knucklebusters
    other = replace(det, track_fd_tempo=0x0990)
    assert orderlist_tempo_calls(sid, other, [{}, {}, {50: (1, 2)}], "auto",
                                 True) == [{}, {}, {}]


@needs_corpus
def test_a_zero_outer_reload_is_not_a_row():
    """B = 0 never reaches the row fetch at `$0484`; there is no row length."""
    sid = load_sid(str(CORPUS / "Knucklebusters.sid"))
    det = detect(sid, lambda m: None, 0)
    assert orderlist_tempo_calls(sid, det, [{}, {}, {7: (1, 0)}], "auto",
                                 True)[2] == {}


@needs_corpus
def test_the_converted_subtune_keeps_its_length():
    """End to end: the written song's subtune 0 voice 2 is not truncated."""
    from fidelity import _preset_opts
    from h2g.convert import convert
    from songview import parse_sng
    root = pathlib.Path(__file__).resolve().parents[2]
    doc = json.loads((root / "presets.json").read_text(encoding="utf-8"))
    sng = convert(str(CORPUS / "Knucklebusters.sid"), log=lambda m: None,
                  **_preset_opts(doc, "Knucklebusters.sid"))
    song = parse_sng(sng)
    assert len(song.tracks[2]) > 100       # was 30 when `$FD` ended the voice
