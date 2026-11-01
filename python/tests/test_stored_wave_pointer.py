"""A note byte past the table that lands on the voices' PATTERN READ POINTERS
sounds the pointers' values -- pinned on Thing_on_a_Spring's `$64`.

The Hubbard note fetch is `ASL / TAY / LDA freqtbl,Y` with no bound. In
Thing_on_a_Spring the table is 96 entries at `$C3A9`, so `$64` (Y = `$C8`)
reads `$C471`/`$C472`: the per-voice pattern read pointers `LDY $C470,X`
(`$C0AB`) steps with `INC $C470,X` (`$C0D4`, `$C0E4`, `$C154`). The frequency
the original writes is `ptr[2] << 8 | ptr[1]` AT THE FETCH: voice 1's pointer
is the index of the note byte it has just fetched, voice 2's the start of its
next event (0 at a pattern's end). One pattern plays six such notes and is
reached from several orderlist positions, so the notes climb F#1 ... E-6
while the clamp played a constant G#7 (58 melody misses, voice 1 .933).

The frequencies below were read off a 6502 emulation of the player's init and
play routine (py65, 9000 frames, `LDA $C3A9,Y` at `$C0F4` with Y = `$C8`:
60 fetches, frames 2929 ... 3403 and again from 7345) and agree with the names
a 180 s siddump of the original prints at those frames (2929 F#1, 2947 D#2,
2965 E-3, 2983 G-3, 3001 C-4, 3019 D-4, 3025 D#4).
"""
import pathlib
import sys

from corpus import CORPUS, needs_corpus

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[1]))

from h2g import stored_wave  # noqa: E402
from h2g.convert import _detect_tables  # noqa: E402
from h2g.sidfile import load_sid  # noqa: E402
from h2g.tracks import convert_tracks  # noqa: E402

F_SHARP_1, D_SHARP_2, E_3, G_3, C_4, D_4, D_SHARP_4 = 18, 27, 40, 43, 48, 50, 51


def _walk(name):
    sid = load_sid(str(CORPUS / name))
    sid, det = _detect_tables(sid, lambda m: None)
    tracks = convert_tracks(sid, det, lambda m: None)
    trace: list = []
    notes = stored_wave.stored_wave_notes(sid, det, tracks, slides=True,
                                          status_bit6=True, trace=trace)
    return sid, det, notes, trace


@needs_corpus
def test_thing_on_a_springs_64_lands_on_voice_1_and_2_pointers():
    sid, det, notes, trace = _walk("Thing_on_a_Spring.sid")
    assert stored_wave.pointer_landings(sid, det) == {
        0x64: (1, stored_wave.POINTER_CELL)}
    votes = [t for t in trace if t[1] == 1]
    assert [f for (*_h, f, _d) in votes[:7]] == [
        0x0302, 0x0508, 0x0B0E, 0x0D14, 0x111A, 0x1320, 0x1502]
    assert [d for (*_h, d) in votes[:7]] == [
        F_SHARP_1, D_SHARP_2, E_3, G_3, C_4, D_4, D_SHARP_4]
    # One pattern, six notes, none of them the clamp's entry 92.
    assert len(notes) == 1 and len(next(iter(notes.values()))) == 6
    assert all(d < 92 for (*_h, d) in votes)


@needs_corpus
def test_commando_stays_held_so_the_fixture_keeps_its_bytes():
    # `_applicable` returns before reading either kind of landing.
    sid = load_sid(str(pathlib.Path(__file__).resolve().parents[2]
                       / "Commando.sid"))
    sid, det = _detect_tables(sid, lambda m: None)
    assert stored_wave._applicable(sid, det) == {}
