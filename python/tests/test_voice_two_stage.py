"""Bit $02 read a third way: a two-stage attack with per-*voice* parameters.

Two other readings of that bit are already pinned elsewhere -- the rise
(test_effects.py) and the every-other-frame alternation (test_effects.py's
`wave_alternate` cases). This is the third, and the first mechanism in this
project whose parameters are indexed by the voice being serviced rather than
by the instrument: Ninja `$CAFD` compares a per-note frame counter against a
three-byte threshold table and sounds a three-byte alternate table until it
passes.

What that costs is a map from instrument to voice, because a Goattracker
wavetable is per instrument and there is no such thing as a per-voice one.
`tracks.instrument_voices` builds it from the finished orderlists and
patterns; these tests pin the map, the reading, and the two derivations that
turn the player's threshold into a number of our play calls -- the `- 1` for
the call the note-start path never lets reach the effect block, and the
`(O + 1) / O` for the calls the player's outer counter skips and ours does
not.
"""
import pathlib
import sys

from corpus import CORPUS, needs_corpus  # noqa: E402

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[1]))

from h2g.convert import _detect_tables, convert  # noqa: E402
from h2g.detect import VOICES, _find_voice_two_stage, detect  # noqa: E402
from h2g.goatwriter import (_gate_calls, _record_voice,  # noqa: E402
                            _voice_two_stage_entries, outer_gate_skip)
from h2g.sidfile import load_sid  # noqa: E402
from h2g.tracks import instrument_voices  # noqa: E402


def _det(name):
    sid = load_sid(str(CORPUS / f"{name}.sid"))
    return _detect_tables(sid, lambda *a, **k: None)


# --- the reading -----------------------------------------------------------

@needs_corpus
def test_ninja_carries_the_per_voice_block():
    sid, det = _det("Ninja")
    assert det.voice_two_stage_alt > 0
    assert det.voice_two_stage_frames > 0
    alt = sid.data[det.voice_two_stage_alt:det.voice_two_stage_alt + VOICES]
    fr = sid.data[det.voice_two_stage_frames:
                  det.voice_two_stage_frames + VOICES]
    # $CC63 / $CC66, static player data: nothing in the file writes either.
    assert bytes(alt) == bytes([0x11, 0x81, 0x15])
    assert bytes(fr) == bytes([0x04, 0x06, 0x04])


@needs_corpus
def test_the_tables_are_never_written():
    """What makes them player data rather than state, and so readable at all."""
    sid, det = _det("Ninja")
    for off in (det.voice_two_stage_alt, det.voice_two_stage_frames):
        addr = off - (sid.to_offset(sid.load_addr)) + sid.load_addr
        for store in (0x9D, 0x8D):      # STA abs,X / STA abs
            assert bytes([store, addr & 0xFF, addr >> 8]) not in sid.data


@needs_corpus
def test_exactly_one_corpus_file_has_it():
    """A signature this specific either names a dialect or names a bug."""
    found = []
    for path in sorted(CORPUS.glob("*.sid")):
        sid = load_sid(str(path))
        sid, det = _detect_tables(sid, lambda *a, **k: None)
        if det.voice_two_stage_alt >= 0:
            found.append(path.name)
    assert found == ["Ninja.sid"]


@needs_corpus
def test_it_never_coexists_with_the_other_two_readings_of_bit_02():
    for path in sorted(CORPUS.glob("*.sid")):
        sid = load_sid(str(path))
        sid, det = _detect_tables(sid, lambda *a, **k: None)
        if det.voice_two_stage_alt < 0:
            continue
        assert det.wave_alternate < 0, path.name
        assert not det.wave_alternate_noise, path.name
        assert not det.effect_rise, path.name


def test_the_probe_declines_a_file_with_no_effect_byte():
    sid = load_sid(str(pathlib.Path(__file__).resolve().parents[2]
                       / "Commando.sid"))
    det = detect(sid, lambda *a, **k: None)
    assert _find_voice_two_stage(sid, det) == (-1, -1)


# --- the instrument-to-voice map -------------------------------------------

def test_the_map_reads_pattern_columns_through_the_orderlist():
    # One subtune, three voices. Voice 0 plays pattern 0, voice 1 pattern 1,
    # voice 2 pattern 0 again -- so instrument 5 is on two voices and 7 on one.
    tracks = [[0, 0xFF, 0], [1, 0xFF, 0], [0, 0xFF, 0]]
    patterns = [[0x60, 5, 0, 0], [0x60, 7, 0, 0]]
    got = instrument_voices(tracks, patterns)
    assert set(got[5]) == {0, 2}
    assert set(got[7]) == {1}


def test_the_restart_operand_is_not_a_pattern_number():
    """`$FF 02` restarts at step 2; reading the 2 as a pattern invents a voice."""
    tracks = [[0, 0xFF, 2], [1, 0xFF, 0], [3, 0xFF, 0]]
    patterns = [[0x60, 5, 0, 0], [0x60, 6, 0, 0],
                [0x60, 9, 0, 0], [0x60, 8, 0, 0]]
    got = instrument_voices(tracks, patterns)
    assert 9 not in got                     # pattern 2 is played by nobody
    assert set(got[5]) == {0}


def test_the_map_weights_by_how_often_the_orderlist_plays_a_pattern():
    tracks = [[0, 0, 0, 1, 0xFF, 0], [0xFF, 0], [0xFF, 0]]
    patterns = [[0x60, 4, 0, 0], [0x60, 4, 0, 0]]
    # Voice 0 plays pattern 0 three times and pattern 1 once: four rows, not two.
    assert instrument_voices(tracks, patterns)[4] == {0: 4}


def test_a_shared_instrument_takes_its_busier_voice():
    assert _record_voice({3: {0: 9, 2: 4}}, 3) == 0
    assert _record_voice({3: {0: 1, 2: 40}}, 3) == 2


def test_an_instrument_nothing_plays_has_no_voice():
    assert _record_voice({3: {0: 9}}, 4) is None
    assert _record_voice(None, 4) is None
    assert _record_voice({}, 4) is None


# --- the two derivations ---------------------------------------------------

def test_a_player_with_no_outer_counter_leaves_a_call_a_call():
    assert _gate_calls(3, None) == 3
    assert _gate_calls(3, 0) == 3


def test_the_outer_counter_stretches_the_players_calls_into_ours():
    # Reload 3 -> the player works on 3 calls in 4, so 3 of its calls are 4
    # of ours. This is the value Ninja actually uses.
    assert _gate_calls(3, 3) == 4
    assert _gate_calls(5, 3) == 7
    assert _gate_calls(1, 1) == 2


@needs_corpus
def test_ninja_s_outer_counter_is_readable_where_its_speed_gate_is_not():
    """The reason `outer_gate_skip` exists beside `SongSpeeds.skip_for`."""
    from h2g.goatwriter import find_song_speeds
    sid, det = _det("Ninja")
    assert find_song_speeds(sid, det) is None
    assert outer_gate_skip(sid) == 3


def test_the_attack_is_threshold_minus_one_of_the_players_calls():
    # threshold 4, no outer counter: 3 calls of the alternate after the
    # frame-0 lead. Entry 0 is one call and a delay of `n` covers `n + 1`.
    left, right = _voice_two_stage_entries(0x41, 0x11, 4, 1, written=True)
    assert left[0] == 0x11              # the alternate, on the note's 2nd call
    assert (left[1], right[1]) == (0x01, 0x80)   # ...held for two more
    # Then the record's own. `_two_stage_entries` clears the gate bit and puts
    # the record's back, so a gated record stays gated.
    assert left[2] == 0x41
    assert left[3] == 0xFF


def test_a_threshold_of_one_says_nothing_and_is_declined():
    """The counter reads 1 on the first call that reaches the block."""
    assert _voice_two_stage_entries(0x41, 0x11, 1, 1, written=True) is None


def test_the_gate_correction_lengthens_the_attack():
    short = _voice_two_stage_entries(0x41, 0x11, 4, 1, written=True)
    long = _voice_two_stage_entries(0x41, 0x11, 4, 1, written=True,
                                    gate_skip=3)
    # 3 of the player's calls -> 4 of ours, so the delay covers one more.
    assert short[0][1] == 0x01
    assert long[0][1] == 0x02


# --- what it emits ---------------------------------------------------------

@needs_corpus
def test_ninja_gains_the_attack_and_nothing_else_does():
    src = str(CORPUS / "Ninja.sid")
    off = convert(src, log=lambda *a, **k: None, effects=True,
                  compact_instruments=True)
    on = convert(src, log=lambda *a, **k: None, effects=True,
                 compact_instruments=True, voice_two_stage=True)
    assert off != on
    plain = str(pathlib.Path(__file__).resolve().parents[2] / "Commando.sid")
    assert (convert(plain, log=lambda *a, **k: None, effects=True)
            == convert(plain, log=lambda *a, **k: None, effects=True,
                       voice_two_stage=True))


@needs_corpus
def test_the_option_needs_effects_like_every_other_reading_of_plus_7():
    src = str(CORPUS / "Ninja.sid")
    assert (convert(src, log=lambda *a, **k: None)
            == convert(src, log=lambda *a, **k: None, voice_two_stage=True))
