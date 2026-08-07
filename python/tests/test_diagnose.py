"""`fidelity.py --diagnose`: which question a low melody score is.

A melody percentage names no cause, and the corpus contains five distinct
defects that all present as one low number. Three of the four files the
handoff filed under "plays something else" turned out to be none of them:
the two sides were not the same piece of music, because the .sid's own init
routine renumbers the subtune before the player sees it.

`--search-subtunes` cannot find that. It varies *our* subtune index while
holding the original's at its startSong, so it finds a counterpart displaced
by a dropped subtune and nothing else -- when the original's index is what
moved, there is no window size that helps. These tests pin the two pieces
that do find it: the correspondence matrix, and the per-voice classifier that
is only meaningful once the correspondence is settled.
"""
import fidelity
from fidelity import Voice


def voice(*notes) -> Voice:
    """A Voice carrying just the attack sequence the classifier reads."""
    v = Voice()
    v.attacks = list(notes)
    v.attack_frames = list(range(len(notes)))
    return v


SEQ = ("C-4", "E-4", "G-4", "C-5", "B-4", "G-4", "E-4", "C-4")


def shifted(seq, k):
    """The same tune k semitones up, as siddump would name it."""
    out = []
    for n in seq:
        s = fidelity._semitone(n) + k
        out.append(("C-", "C#", "D-", "D#", "E-", "F-", "F#",
                    "G-", "G#", "A-", "A#", "B-")[s % 12] + str(s // 12))
    return out


# --------------------------------------------------------------------------
# The note name <-> semitone round trip the sweep rests on
# --------------------------------------------------------------------------
def test_semitone_reads_siddump_note_names():
    assert fidelity._semitone("C-4") == 48
    assert fidelity._semitone("C-5") - fidelity._semitone("C-4") == 12
    assert fidelity._semitone("C#4") - fidelity._semitone("C-4") == 1
    assert fidelity._semitone("B-3") + 1 == fidelity._semitone("C-4")


def test_shifted_helper_round_trips_through_the_names():
    assert shifted(SEQ, 0) == list(SEQ)
    assert shifted(SEQ, 12)[0] == "C-5"


# --------------------------------------------------------------------------
# The constant-shift sweep
# --------------------------------------------------------------------------
def test_an_untransposed_voice_peaks_at_zero():
    k, best, at_zero = fidelity.shift_sweep(voice(*SEQ), voice(*SEQ))
    assert (k, best, at_zero) == (0, 1.0, 1.0)


def test_the_shift_is_signed_as_ours_against_the_originals():
    """-7 means we play it a fifth low, not that adding 7 would fix it."""
    k, _, _ = fidelity.shift_sweep(voice(*SEQ), voice(*shifted(SEQ, -7)))
    assert k == -7


def test_a_transposed_voice_peaks_at_its_shift():
    for k_true in (-7, -1, 3, 12):
        k, best, at_zero = fidelity.shift_sweep(
            voice(*SEQ), voice(*shifted(SEQ, k_true)))
        assert k == k_true, k_true
        assert best == 1.0
        assert at_zero < 1.0


def test_the_sweep_does_not_need_the_alignment_to_survive():
    """The reason it replaced the position-aligned modal delta.

    A modal delta over two sequences of different length slips as soon as
    either side drops a note; the sweep compares whole sequences at each
    shift, so a transposition is still visible when half the notes are gone.
    """
    full = SEQ * 3
    dropped = [n for i, n in enumerate(shifted(full, 5)) if i % 4]
    k, best, at_zero = fidelity.shift_sweep(voice(*full), voice(*dropped))
    assert k == 5
    assert best > at_zero


def test_an_empty_side_sweeps_to_nothing():
    assert fidelity.shift_sweep(voice(), voice(*SEQ)) == (0, 0.0, 0.0)
    assert fidelity.shift_sweep(voice(*SEQ), voice()) == (0, 0.0, 0.0)


# --------------------------------------------------------------------------
# The per-voice classifier: the four defects, and agreement
# --------------------------------------------------------------------------
def test_two_silent_voices_are_not_a_defect():
    assert fidelity.classify_voice(voice(), voice()) == "silent in both"


def test_a_voice_we_never_play_is_absent():
    assert fidelity.classify_voice(voice(*SEQ), voice()).startswith("absent")


def test_a_voice_the_original_never_plays_is_invented():
    assert fidelity.classify_voice(voice(), voice(*SEQ)).startswith("invented")


def test_agreement_is_reported_as_agreement():
    """The classifier also runs at the *right* counterpart.

    Once the matrix has found that our o9 is the original's s0, the per-voice
    pass is re-run there -- and a voice that agrees must not come back
    described as one of the four ways of disagreeing.
    """
    assert fidelity.classify_voice(voice(*SEQ), voice(*SEQ)).startswith("matches")


def test_a_constant_transposition_is_named_with_its_size():
    got = fidelity.classify_voice(voice(*SEQ), voice(*shifted(SEQ, -5)))
    assert got.startswith("transposed -5 semitones")


def test_under_production_with_exact_pitches_is_its_own_finding():
    """Rasputin's voice 1: the right notes, a third of them.

    Distinct from "different music" because the fix is in the pattern decode
    rather than anywhere near the note table, and distinct from a
    transposition because the pitches are already right.
    """
    got = fidelity.classify_voice(voice(*(SEQ * 4)),
                                  voice("C-4", "E-4", "G-4"))
    assert got.startswith("under-produced")
    assert "3 attacks against 32" in got


def test_over_production_is_separated_from_under_production():
    got = fidelity.classify_voice(voice("C-4", "E-4", "G-4"),
                                  voice(*(SEQ * 4)))
    assert got.startswith("over-produced")


def test_unrelated_music_is_not_dressed_up_as_a_transposition():
    """The finding the sweep exists to *refuse*.

    Any two sequences peak somewhere. A peak only counts when it beats the
    unshifted ratio by a margin and is worth something in absolute terms --
    without both, every low-scoring file reads as "transposed by k" and the
    handoff records a cause that is not there.
    """
    other = voice("F#2", "A#5", "D-3", "G#6", "C#2", "B-6", "F-3", "A-2")
    got = fidelity.classify_voice(voice(*SEQ), other)
    assert got.startswith("different music")


# --------------------------------------------------------------------------
# The remap table
# --------------------------------------------------------------------------
def test_the_known_remaps_are_recorded_with_their_addresses():
    """These are read out of the files' init routines, not inferred.

    Dragons_Lair_Part_II's $AF00 wrapper maps PSID 0 to song 9, 1 to song 7
    and 9 to song 8 -- which is exactly the correspondence the matrix
    measures (94%, 98%, 97%). The note exists so the next reader gets the
    reason next to the evidence.
    """
    remaps = fidelity.SUBTUNE_REMAP
    assert "Dragons_Lair_Part_II.sid" in remaps
    assert "$AF00" in remaps["Dragons_Lair_Part_II.sid"]
    assert "Rasputin.sid" in remaps
    assert "$CFB5" in remaps["Rasputin.sid"]


def test_the_matrix_is_capped_and_says_so():
    """Quadratic in a claim that is not always honest.

    Rasputin's header claims 18 subtunes and fifteen of them play two notes
    in forty-five seconds. The cap keeps a bogus claim from turning into a
    thousand traces; CLAUDE.md's rule is that it may never do so silently, so
    `diagnose` prints what it left out.
    """
    assert fidelity.MATRIX_CAP >= 16
    src = fidelity.diagnose.__doc__ or ""
    assert "correspondence" in src
