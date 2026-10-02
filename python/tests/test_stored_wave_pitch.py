"""A note byte past the table that lands on the stored-waveform cells sounds
what voices 0 and 1 hold at that moment -- pinned on two files whose voices
hold different things.

Ten corpus players reach a `$68` (Y = `$D0`), which lands sixteen bytes past
the 96-entry frequency table on the per-voice stored-waveform array the event
path writes with `STA cell,X`. The frequency the original writes is therefore
`cell[1] << 8 | cell[0]`: voice 1's waveform byte high, voice 0's low, as
they stand at that fetch. `stored_wave.stored_wave_notes` walks the
orderlists in time to read them; Commando is held out by human decision
(`stored_wave.HELD`) so the byte-exact fixture keeps the clamp's G#7.

The frequencies pinned below were each found on the same voice in a 900 s
siddump of the original (2026-10-02, `C:/t/commando-68-nine-files/
probe_trace.py`): Crazy_Comets voice 0 writes $1141 (7 frames), $1115 (129),
$4311 (3) and $4315 (90); Phantoms writes $1543 on voice 0 (25 frames) and
voice 1 (23). The clamp emitted G#7 for every one of them.
"""
import pathlib
import sys

from corpus import CORPUS, needs_corpus

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[1]))

from h2g import patterns, stored_wave  # noqa: E402
from h2g.convert import _detect_tables  # noqa: E402
from h2g.sidfile import load_sid  # noqa: E402
from h2g.tracks import convert_tracks  # noqa: E402

COMMANDO = pathlib.Path(__file__).resolve().parents[2] / "Commando.sid"

# Table entries (C-0 = 0).
C_4, D_SHARP_4, B_5, G_SHARP_7 = 48, 51, 71, 92


def _walk(path):
    """The walk exactly as convert() runs it under the shipped presets for
    these files (`slides` and `status_bit6` on), with its vote trace."""
    sid = load_sid(str(path))
    sid, det = _detect_tables(sid, lambda m: None)
    tracks = convert_tracks(sid, det, lambda m: None)
    trace: list = []
    notes = stored_wave.stored_wave_notes(sid, det, tracks, slides=True,
                                          status_bit6=True, trace=trace)
    return sid, det, notes, trace


def _votes(trace, entry, ordinal):
    return [t for t in trace if t[3] == entry and t[4] == ordinal]


@needs_corpus
def test_crazy_comets_sounds_c4_where_voice_1_holds_a_triangle():
    sid, det, notes, trace = _walk(CORPUS / "Crazy_Comets.sid")
    assert stored_wave.stored_wave_landings(sid, det) == {0x68: (0, 2)}
    # One event in the whole tune, pattern $18's first, on voice 0.
    assert notes == {0x18: {0: C_4}}
    votes = _votes(trace, 0x18, 0)
    assert {v for (_, v, *_r) in votes} == {0}
    # Played under FOUR waveform states: voice 1 on triangle ($11) gives
    # C-4, on pulse ($43) gives B-5; voice 0's own previous byte only moves
    # the low half. A constant cannot produce this set.
    assert {f for (*_h, f, _d) in votes} == {0x1141, 0x1115, 0x4311, 0x4315}
    assert {d for (*_h, f, d) in votes if f >> 8 == 0x11} == {C_4}
    assert {d for (*_h, f, d) in votes if f >> 8 == 0x43} == {B_5}
    # The tie (six plays each) goes to the first state the tune reaches.
    assert votes[0][5] >> 8 == 0x11


@needs_corpus
def test_phantoms_sounds_d_sharp_4_on_two_voices_at_once():
    sid, det, notes, trace = _walk(CORPUS / "Phantoms_of_the_Asteroid.sid")
    assert stored_wave.stored_wave_landings(sid, det) == {0x68: (0, 2)}
    assert notes == {0x30: {0: D_SHARP_4}}
    votes = _votes(trace, 0x30, 0)
    # Voices 0 and 1 fetch the same pattern on the same tick, voice 1 first
    # (the player's X runs 2, 1, 0), and both write $1543.
    assert [(v, t, f) for (_, v, t, _e, _o, f, _d) in votes] == [
        (1, 256, 0x1543), (0, 256, 0x1543)]


@needs_corpus
def test_the_derived_note_reaches_the_decoded_row():
    sid, det, notes, _ = _walk(CORPUS / "Phantoms_of_the_Asteroid.sid")
    plain = patterns.decode_entry(sid, det, 0x30, slides=True,
                                  status_bit6=True)
    read = patterns.decode_entry(sid, det, 0x30, slides=True,
                                 status_bit6=True, wave_notes=notes[0x30])
    assert plain[0] == patterns.GT_FIRSTNOTE + G_SHARP_7 + det.note_base
    assert read[0] == patterns.GT_FIRSTNOTE + D_SHARP_4 + det.note_base
    # Nothing but that one note column moves.
    assert [i for i in range(len(plain)) if plain[i] != read[i]] == [0]


def test_commando_is_held_and_keeps_the_clamp():
    # The fixture file, so this runs wherever the repo does. Its `$68` lands
    # on the same kind of cell -- the walk would read B-5 -- but the human
    # decision holds it until the note-104 listen.
    sid, det, notes, trace = _walk(COMMANDO)
    assert stored_wave.stored_wave_landings(sid, det) == {0x68: (0, 2)}
    assert sid.name in stored_wave.HELD
    assert notes == {} and trace == []
    ev = patterns.decode_entry(sid, det, 0x8, slides=True, status_bit6=True)
    assert ev[0] == patterns.GT_FIRSTNOTE + G_SHARP_7
