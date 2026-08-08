"""Encoding the counter above the speed gate -- and why it is opt-in.

§7b established that most Hubbard players decrement their speed gate on only
some frames: a second counter jumps past it, or returns from the play call
outright, so a row lasts `(reload + 1) x (O + 1) / O` frames rather than
`reload + 1`. `--skip-gate` writes that corrected row.

It is off by default, and the reason is the interesting part. Correcting the
row changes the `-S` multiplier -- Tarzan goes from 2 to 1 -- and v0.5.82
divides every per-frame rate the converter emits (slide steps, the drum sweep,
wavetable delays) by that same multiplier. So the fix un-does its own
compensation: Tarzan's timing goes from 0.667 to a perfect 1.000 against the
original while its melody agreement falls 73% -> 59%, and that is not the
traced window, since it holds at 10, 20, 40 and 60 seconds.
"""
import pathlib
import sys

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[1]))

from corpus import CORPUS as _CORPUS, needs_corpus  # noqa: E402
CORPUS = _CORPUS

import presets                                            # noqa: E402
from h2g.goatwriter import (SongSpeeds, effective_frames,  # noqa: E402
                            recommended_multiplier)


def _speeds(frames, skip):
    return SongSpeeds(frames=frames, reload_addr=0x1000, table_addr=None,
                      skip=skip)


def test_a_whole_number_correction_is_encodable():
    # gate 2, one frame in three skipped -> 3.00 exactly.
    sp = _speeds((2,), (2,))
    assert sp.true_frames(0) == 3.0
    assert sp.encodable_frames(0) == 3


def test_a_fractional_correction_is_not():
    """2.67 has no tempo, and rounding it trades a known error for an unknown.

    Goattracker's tempo is a count of play calls, so a row of 8/3 frames
    cannot be written. Encoding it is §8's re-gridding problem.
    """
    sp = _speeds((2,), (3,))
    assert sp.true_frames(0) == 8 / 3
    assert sp.encodable_frames(0) is None


def test_a_negligible_skip_rounds_to_the_gate():
    """Ricochet's 127: 2.016 frames, which is 2 and must not become 3."""
    sp = _speeds((2,), (127,))
    assert sp.encodable_frames(0) == 2


def test_the_option_is_what_decides():
    sp = _speeds((2,), (2,))
    assert effective_frames(sp, 0, skip_gate=False) == 2
    assert effective_frames(sp, 0, skip_gate=True) == 3


def test_no_skip_means_the_option_changes_nothing():
    """Most of the corpus has no such counter and must be untouched."""
    sp = _speeds((3,), ())
    assert effective_frames(sp, 0, False) == effective_frames(sp, 0, True) == 3


def test_correcting_the_row_moves_the_multiplier():
    """The coupling that keeps this opt-in.

    A gate of 2 needs -S2 to be expressible at all; corrected to 3 it does
    not, and every per-frame rate the writer scales by the multiplier moves
    with it.
    """
    sp = _speeds((2,), (2,))
    assert recommended_multiplier(sp, 0, skip_gate=False) == 2
    assert recommended_multiplier(sp, 0, skip_gate=True) == 1


def test_it_is_deliberately_excluded_from_the_always_block():
    """A guard against someone enabling it by default without the coupling.

    tests/test_preset_passthrough.py requires every convert() option to be in
    presets' `always` block unless it is named here, so this is the record
    that the omission is a decision.
    """
    assert "skip_gate" in presets.EXCLUDED_FROM_ALWAYS


@needs_corpus
def test_tarzan_is_the_worked_example():
    from h2g.convert import _detect_tables
    from h2g.goatwriter import find_song_speeds
    from h2g.sidfile import load_sid
    sid = load_sid(str(CORPUS / "Tarzan.sid"))
    sid, det = _detect_tables(sid, lambda m: None)
    sp = find_song_speeds(sid, det if det.can_convert else None)
    assert sp.frames_for(0) == 2 and sp.skip_for(0) == 2
    assert sp.encodable_frames(0) == 3
    assert recommended_multiplier(sp, 0, True) == 1


@needs_corpus
def test_the_option_reaches_only_files_with_an_encodable_skip():
    """It must not disturb a file it has nothing to say about."""
    import hashlib
    from h2g.convert import convert
    for name in ("Commando.sid", "Ricochet.sid"):
        a = convert(str(CORPUS / name), log=lambda m: None, tempo="auto")
        b = convert(str(CORPUS / name), log=lambda m: None, tempo="auto",
                    skip_gate=True)
        assert hashlib.sha1(a).digest() == hashlib.sha1(b).digest(), name
