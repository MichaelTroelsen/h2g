"""An over-long orderlist costs its subtune, not the whole file.

Goattracker's orderlist limit is 254 bytes. A track over it used to raise
ConversionAbort, which discarded everything else the tune contained --- and
across the corpus exactly one subtune is over-long in each affected file, so
that abort threw away 25 good subtunes of Gremlins, 18 of Monty on the Run and
2 of Knucklebusters.

The subtune is replaced wholesale rather than truncated. Cutting one voice
short while its neighbours play on makes that voice loop early and drift
against them for the rest of the subtune: a subtune that sounds wrong, which
is worse than one plainly absent.
"""
import pathlib
import sys

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[1]))



from h2g.convert import convert
from h2g.patterns import DEFAULT_TRACK, MAX_TRACK_LEN, reindex_tracks

REPO_ROOT = pathlib.Path(__file__).resolve().parents[2]

# Hubbard pattern n -> Goattracker pattern n, so a track's length is its own.
INDEX = [[i] for i in range(0x100)]
SHORT = [0x01, 0xFF, 0x00]
LONG = [0x02] * 300 + [0xFF, 0x00]


def _subtunes(tracks):
    return [tracks[k:k + 3] for k in range(0, len(tracks), 3)]


def test_a_short_subtune_is_untouched():
    out = reindex_tracks([SHORT] * 3, INDEX)
    assert out == [SHORT] * 3


def test_an_over_long_voice_drops_its_whole_subtune():
    # A subtune missing one voice does not play the tune either, so all three
    # go together.
    out = reindex_tracks([LONG, SHORT, SHORT], INDEX)
    assert out == [DEFAULT_TRACK] * 3


def test_other_subtunes_survive():
    # This is the whole point: one bad subtune used to cost every good one.
    tracks = [SHORT] * 3 + [LONG, SHORT, SHORT] + [SHORT] * 3
    out = _subtunes(reindex_tracks(tracks, INDEX))
    assert out[0] == [SHORT] * 3
    assert out[1] == [DEFAULT_TRACK] * 3
    assert out[2] == [SHORT] * 3


def test_the_dropped_subtune_is_reported():
    dropped = []
    logged = []
    reindex_tracks([SHORT] * 3 + [LONG, SHORT, SHORT], INDEX,
                   log=logged.append, dropped=dropped)
    assert dropped == [1]
    assert any("DROPPED" in m for m in logged)


def test_a_track_at_the_limit_is_kept():
    # The limit is 254 usable bytes; MAX_TRACK_LEN is the first length that is
    # too long, because Goattracker stores len-1 in a single byte.
    at_limit = [0x02] * (MAX_TRACK_LEN - 1)
    assert len(at_limit) == 254
    assert reindex_tracks([at_limit, SHORT, SHORT], INDEX)[0] == at_limit
    over = [0x02] * MAX_TRACK_LEN
    assert reindex_tracks([over, SHORT, SHORT], INDEX)[0] == DEFAULT_TRACK


def test_packing_runs_before_the_length_check():
    # A run of one repeated pattern collapses to two bytes, so a track that is
    # over the limit raw can still fit -- the check must not pre-empt that.
    runs = [0x02] * 300 + [0xFF, 0x00]
    assert reindex_tracks([runs, SHORT, SHORT], INDEX, pack=True)[0] != DEFAULT_TRACK
    assert reindex_tracks([runs, SHORT, SHORT], INDEX, pack=False)[0] == DEFAULT_TRACK


def test_nothing_left_is_the_condition_convert_refuses_on():
    # convert() refuses when every track is a placeholder. Dropping the only
    # subtune produces exactly that, and a .sng of placeholders is
    # structurally valid but musically empty -- the fake success v0.5.26
    # removed. Three corpus files reach this at defaults (Chicken Song,
    # International Karate, Kentilla); all three convert with --pack-repeats.
    out = reindex_tracks([LONG, LONG, LONG], INDEX)
    assert all(t == DEFAULT_TRACK for t in out)


def test_commando_is_unaffected():
    # No Commando track is anywhere near the limit, so the fixture must not
    # move.
    out = convert(str(REPO_ROOT / "Commando.sid"), log=lambda m: None)
    assert out == (REPO_ROOT / "Commando.sng").read_bytes()
