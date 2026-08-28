"""Encoding the counter above the speed gate.

§7b established that most Hubbard players decrement their speed gate on only
some frames: a second counter jumps past it, or returns from the play call
outright, so a row lasts `(reload + 1) x (O + 1) / O` frames rather than
`reload + 1`. `--skip-gate` writes that corrected row.

Correcting the row also changes the `-S` multiplier -- Tarzan goes from 2 to 1
-- so anything that packs the result has to pack it at the new one. v0.5.119
did not: the harness used the multiplier recorded in presets.json while the
tempo had been written for another, played the file at the wrong speed, read
Tarzan's melody as 73% -> 59% and concluded the option was harmful. With the
two matched it is 73% -> 96%, and Pygmies_Revenge 80% -> 93%.
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
    """A gate of 2 needs -S2 to be expressible at all; corrected to 3 it
    does not. Anything that packs the output must follow -- getting this
    wrong is what made the option look harmful for one version.
    """
    sp = _speeds((2,), (2,))
    assert recommended_multiplier(sp, 0, skip_gate=False) == 2
    assert recommended_multiplier(sp, 0, skip_gate=True) == 1


def test_it_is_on_by_default():
    """It was excluded for one version on a measurement that was my own bug.

    v0.5.119 read Tarzan's melody as 73% -> 59% and blamed a coupling between
    the corrected row and the -S multiplier. The harness was packing the file
    at the preset's multiplier while the tempo had been written for another,
    so it played at the wrong speed. With the two matched it is 73% -> 96%.
    """
    assert "skip_gate" not in presets.EXCLUDED_FROM_ALWAYS
    assert presets.FIXED.get("skip_gate") is True


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


def test_a_fractional_row_is_exact_at_the_right_multiplier():
    """A row of p/q frames is expressible: pack at -Sq with a tempo of p.

    A row lasts tempo/multiplier frames, so 8/3 is not a rounding problem --
    it is -S3 at tempo 8. This is what §8 called re-gridding, and it needs no
    change to how many rows a note gets.
    """
    from fractions import Fraction
    sp = _speeds((2,), (3,))                     # gate 2, one frame in four
    assert sp.exact_row(0) == Fraction(8, 3)
    assert sp.encodable_frames(0) is None        # not a whole number
    f = effective_frames(sp, 0, skip_gate=True)
    m = recommended_multiplier(sp, 0, skip_gate=True)
    assert f == Fraction(8, 3) and m == 3
    assert int(f * m) == 8                       # the tempo written
    assert Fraction(int(f * m), m) == sp.exact_row(0)   # exact, not rounded


def test_the_denominator_is_capped_by_playability():
    """The cap is where rounding stops being acceptable, not where q gets big.

    This asserted 6 and declined 33/10 on the reasoning that the rows beyond
    six "are within ~1.3% of a whole number anyway, so they round". That is
    true of most of them and false of exactly three shapes:

        16/7 -> 2   12.5% out      81/20  -> 4   1.2% out
        20/9 -> 2   10.0%          113/28 -> 4   0.9%
        33/10 -> 3   9.1%          339/112-> 3   0.9%

    A 7.5x gap with nothing in between, so v0.5.313 raised it to 10 and the
    six files it reaches all gained -- `drift` 0.00 on every one, `wave`
    +16.1pp mean. Ten calls a frame is ~three quarters of a PAL frame's
    19656 cycles: heavy, and the last value that is a call rate at all.

    The cap was also 4 for three versions on a measurement artefact: siddump
    samples once per frame whatever the call rate, so a -m5 trace of a
    multiplier-5 file drops four calls in five. At equal sampling nothing
    regresses -- Kings_of_the_Beach_intro, read as 96% -> 61%, is 96%.
    """
    from fractions import Fraction
    import h2g.goatwriter as gw
    assert gw.MAX_ROW_DENOMINATOR == 10
    sp = _speeds((3,), (5,))                     # 18/5 -- reachable at -S5
    assert sp.exact_row(0) == Fraction(18, 5)
    assert effective_frames(sp, 0, skip_gate=True) == Fraction(18, 5)
    assert recommended_multiplier(sp, 0, skip_gate=True) == 5
    # 33/10 is reachable now: rounding it to 3 is 9.1% out, which is a tempo
    # error a listener hears, against 500 calls a second which is merely busy.
    sp10 = _speeds((3,), (10,))
    assert sp10.exact_row(0) == Fraction(33, 10)
    assert effective_frames(sp10, 0, skip_gate=True) == Fraction(33, 10)
    assert recommended_multiplier(sp10, 0, skip_gate=True) == 10
    # ...and 339/112 is not, because it rounds to 3 within 0.9% and 112 calls
    # a frame is 5600 Hz.
    sp112 = _speeds((3,), (112,))
    assert sp112.exact_row(0) == Fraction(339, 112)
    assert effective_frames(sp112, 0, skip_gate=True) == 3


def test_an_integer_row_still_takes_no_multiplier():
    sp = _speeds((2,), (2,))
    assert recommended_multiplier(sp, 0, skip_gate=True) == 1


@needs_corpus
def test_the_zero_page_outer_gate_is_read():
    """DEC zp is two bytes where DEC abs is three, so the branch reads +5 and
    not +6, and the reload store is STA zp. Samantha Fox, at its play address
    $7006: DEC $EA / BPL / LDA #$04 / STA $EA / RTS."""
    from h2g.goatwriter import outer_gate_skip
    from h2g.sidfile import load_sid

    sid = load_sid(str(CORPUS / "Samantha_Fox_Strip_Poker.sid"))
    assert sid.play_addr == 0x7006
    assert outer_gate_skip(sid, 0) == 4


@needs_corpus
def test_the_pal_ntsc_outer_gate_takes_the_pal_reload():
    """Las Vegas's gate reads the KERNAL PAL/NTSC flag at $02A6 and chooses
    between two immediates, carrying the value in Y. This corpus is PAL, so
    the reload is the second one, 4 -- not the NTSC 2."""
    from h2g.goatwriter import outer_gate_skip
    from h2g.sidfile import load_sid

    sid = load_sid(str(CORPUS / "Las_Vegas_Video_Poker.sid"))
    assert sid.play_addr == 0x5006
    assert outer_gate_skip(sid, 0) == 4


@needs_corpus
def test_spellbounds_gate_reads_the_skip_its_drift_predicted():
    """Spellbound carried the same unread zero-page gate. Its committed row
    read `drift -90.9`, which is -1/11, i.e. skip 10 -- so the signature and
    the trace agree without either being fitted to the other."""
    from h2g.goatwriter import outer_gate_skip
    from h2g.sidfile import load_sid

    sid = load_sid(str(CORPUS / "Spellbound.sid"))
    assert sid.play_addr == 0xE012
    assert outer_gate_skip(sid, 0) == 10


@needs_corpus
def test_the_rescue_spellings_are_anchored_at_the_play_address():
    """THE ANCHOR, AND THE DEFECT IT EXISTS FOR.

    `DEC zp / BPL / LDA # / STA zp / RTS` is a common enough idiom that a
    file-wide search matched ordinary code in Spellbound and took its melody
    from 93% to 38%. An outer gate is the first thing the frame routine does,
    so it sits AT the header's playAddress. Moving the anchor off by a single
    byte must therefore find nothing.
    """
    import h2g.goatwriter as G
    from h2g.sidfile import load_sid

    sid = load_sid(str(CORPUS / "Samantha_Fox_Strip_Poker.sid"))
    at = sid.to_offset(sid.play_addr)
    assert G.OUTER_GATE_RTS_ZP.match(sid.data, at) is not None
    assert G.OUTER_GATE_RTS_ZP.match(sid.data, at + 1) is None, (
        "the anchor must be exact -- a file-wide search is what caused the "
        "Spellbound false positive")


@needs_corpus
def test_a_file_naming_no_play_routine_declines_rather_than_guessing():
    """playAddress 0 means the tune installs its own IRQ handler, so there is
    nothing to anchor on -- and a guess is worse than no reading."""
    import dataclasses

    from h2g.goatwriter import outer_gate_skip
    from h2g.sidfile import load_sid

    sid = load_sid(str(CORPUS / "Samantha_Fox_Strip_Poker.sid"))
    assert outer_gate_skip(dataclasses.replace(sid, play_addr=0), 0) is None

