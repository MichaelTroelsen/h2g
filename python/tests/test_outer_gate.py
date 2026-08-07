"""The counter above the speed gate, and the frames it eats.

`find_song_speeds` reads the gate's reload byte and reports `reload + 1` frames
per duration unit. Timed against the original (`--pace`, `--ticks`), that is
too small on a large minority of the corpus by a tune-specific factor between
1.1 and 1.5 -- never 2, which is what made it hard to attribute.

The factor is a second counter three instructions above the gate:

    DEC outer / BPL +8 / LDA #O / STA outer / JMP past-the-gate
    DEC gate  / BPL +6 / LDA reload / STA gate

On the frame the outer counter underflows, the gate's own DEC is jumped over.
So the gate advances on O of every O+1 frames and a row lasts
`(reload + 1) * (O + 1) / O` frames. Against the 15 files in whats-next.md 7b
whose row length was timed independently, that is within 5% on all 15.

The trap this file exists to hold shut: **O is an immediate operand, and the
byte in the file image is a decoy.** Where the init writes it from a
per-subtune table, the image byte is whatever the last init left there.
Tarzan's image byte reads 11 and its subtune 0 actually runs 2 -- and the
difference is 2.18 frames against the measured 3.00. v0.5.102 read the image
byte, found it constant per file, and concluded the value was a per-player
constant. It is per subtune in 32 of the 51 files that have the counter.
"""
import pathlib
import sys

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[1]))

from corpus import CORPUS as _CORPUS, needs_corpus  # noqa: E402
CORPUS = _CORPUS

from h2g.goatwriter import SongSpeeds, find_song_speeds  # noqa: E402
from h2g.sidfile import load_sid                          # noqa: E402
from presets import _detect_tables                        # noqa: E402


def _speeds(name):
    sid = load_sid(str(CORPUS / name))
    sid, det = _detect_tables(sid, lambda m: None)
    return find_song_speeds(sid, det if det.can_convert else None)


def test_no_outer_counter_leaves_the_gate_alone():
    """Most of the corpus has no such counter, and must be unaffected."""
    sp = SongSpeeds(frames=(3,), reload_addr=0x1000, table_addr=None)
    assert sp.skip_for(0) is None
    assert sp.true_frames(0) == 3.0


def test_the_skip_stretches_the_row():
    sp = SongSpeeds(frames=(2,), reload_addr=0x1000, table_addr=None, skip=(2,))
    # Gate advances on 2 frames in 3; a 2-frame row therefore takes 3.
    assert sp.true_frames(0) == 3.0


def test_a_skip_can_make_the_row_non_integer():
    """Which is the whole reason this is reported and not encoded.

    A gate of 2 skipping one frame in four gives rows of 3, 3 and 2 frames.
    Goattracker has no tempo for 2.67, so `frames_for` -- what the writer
    uses -- deliberately still returns the unadjusted 2.
    """
    sp = SongSpeeds(frames=(2,), reload_addr=0x1000, table_addr=None, skip=(3,))
    assert sp.true_frames(0) == 8 / 3
    assert sp.frames_for(0) == 2


def test_a_huge_skip_is_almost_no_skip():
    """Ricochet's 127: one frame in 128, and it measures 2.00 against a gate
    of 2. It is the corpus's control, and it is correct for a reason."""
    sp = SongSpeeds(frames=(2,), reload_addr=0x1000, table_addr=None, skip=(127,))
    assert abs(sp.true_frames(0) - 2.0) < 0.02


def test_skip_for_out_of_range_subtune_is_none():
    sp = SongSpeeds(frames=(2, 2), reload_addr=0x1000, table_addr=None, skip=(2,))
    assert sp.skip_for(1) is None
    assert sp.true_frames(1) == 2.0      # falls back to the gate, not to None


@needs_corpus
def test_tarzan_reads_its_table_and_not_the_image_byte():
    """The regression that would silently restore v0.5.102's wrong reading.

    $59EA[0] is 2; the image byte at the immediate is 11. Reading the image
    would give 2.18 frames where the player measures 3.00.
    """
    sp = _speeds("Tarzan.sid")
    assert sp.frames_for(0) == 2
    assert sp.skip_for(0) == 2
    assert sp.true_frames(0) == 3.0
    assert sp.skip_table_addr == 0x59EA


@needs_corpus
def test_ricochet_has_no_table_and_takes_the_image_byte():
    sp = _speeds("Ricochet.sid")
    assert sp.skip_table_addr is None
    assert sp.skip_for(0) == 127


@needs_corpus
def test_the_corrected_row_matches_what_was_timed():
    """Every file in whats-next.md 7b with both a timing and this counter.

    These are measurements taken two ways that owe each other nothing --
    `--pace` times our conversion against the original over difflib-matched
    notes, `--ticks` reads the period out of the original's cycle profile --
    and the formula has to land on both.
    """
    timed = {"Tarzan.sid": (0, 3.00), "Deep_Strike.sid": (0, 2.67),
             "Delta.sid": (11, 2.50), "ACE_II.sid": (0, 2.65),
             "Food_Feud.sid": (0, 2.68), "Saboteur_II.sid": (0, 2.65),
             "Thundercats.sid": (0, 2.65), "Zoolook.sid": (0, 2.71),
             "Lightforce.sid": (0, 3.50), "Thanatos.sid": (0, 3.75),
             "Pygmies_Revenge.sid": (0, 4.00), "Ricochet.sid": (0, 2.00)}
    for name, (sub, want) in timed.items():
        got = _speeds(name).true_frames(sub)
        assert got is not None, name
        assert abs(got - want) / want <= 0.05, f"{name}: {got:.2f} vs {want}"


@needs_corpus
def test_the_gate_alone_would_have_missed_all_of_them():
    """The control for the test above: the uncorrected number is not close.

    Without this, the previous test could pass on a formula that happened to
    agree with a reading that was already right.
    """
    for name, sub, want in (("Tarzan.sid", 0, 3.00), ("Deep_Strike.sid", 0, 2.67),
                            ("Lightforce.sid", 0, 3.50)):
        sp = _speeds(name)
        assert abs(sp.frames_for(sub) - want) / want > 0.05, name
