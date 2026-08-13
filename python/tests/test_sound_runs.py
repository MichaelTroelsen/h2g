"""How long a note keeps a waveform selected -- the column for note length.

CLAUDE.md has recorded for most of this project's life that no dimension
measures note length, and the `onset` census's `short` kind named five
instruments where our note stops selecting a waveform inside the four-frame
opening window while the original still does. This is that observation turned
into a measurement.

The mechanism it sees, Commando voice 0 on twelve-frame notes:

    ORIGINAL  15 80 80 14 14 14 14 14 14 14 14 14 | next attack
    OURS      15 81 81 15 15 15 15 15 15 14 14 09 | next attack

Goattracker fetches the next note `gatetimer & $3f` ticks early
(gplay.c:905) and writes the instrument's `firstwave` -- `$09`, test bit and
gate, no waveform -- so the note before it loses its final frame.
"""
import pathlib
import sys
from collections import Counter

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[1]))

import fidelity as F  # noqa: E402


def _voices(*event_lists):
    vs = [F.Voice(wf_events=list(wf), adsr_events=list(ad),
                  attack_frames=list(at))
          for wf, ad, at in event_lists]
    return vs + [F.Voice()] * (3 - len(event_lists))


def test_a_note_sounds_until_its_waveform_is_deselected():
    """Four frames of triangle, then `$09` -- three sounding frames, and the
    fourth is the one Goattracker spends on the next note's reset."""
    v = _voices(([(0, 0x11), (3, 0x09)], [(0, 0x0A09)], [0, 8]))
    assert F.sound_runs(v, 16) == {0x0A09: Counter({3: 1})}


def test_a_latched_waveform_sounds_to_the_end_of_the_slot():
    """A gated-off voice keeps its waveform, which is what the original does:
    `80` held to the next attack counts every frame of the slot."""
    v = _voices(([(0, 0x81), (1, 0x80)], [(0, 0x0A09)], [0, 8]))
    assert F.sound_runs(v, 16) == {0x0A09: Counter({8: 1})}


def test_the_slot_is_capped_at_the_next_attack():
    """Without the cap the original's run would cross every note to the end of
    the window and be dropped as window-cut, which is the "nothing to compare"
    trap `release_tails` fell into."""
    v = _voices(([(0, 0x11)], [(0, 0x0A09)], [0, 4, 8]))
    assert F.sound_runs(v, 16) == {0x0A09: Counter({4: 2})}


def test_a_note_whose_slot_reaches_the_window_is_dropped():
    """Its length would be a fact about the window, not about the note."""
    v = _voices(([(0, 0x11)], [(0, 0x0A09)], [0, 4]))
    assert F.sound_runs(v, 16) == {0x0A09: Counter({4: 1})}


def test_the_key_is_the_adsr_after_the_attack():
    v = _voices(([(0, 0x11)], [(0, 0x0000), (1, 0x0A09)], [0, 4]))
    assert list(F.sound_runs(v, 16)) == [0x0A09]


# ---- the agreement --------------------------------------------------------

def test_matching_lengths_agree_and_the_delta_is_zero():
    o = _voices(([(0, 0x11)], [(0, 0x0A09)], [0, 4]))
    u = _voices(([(0, 0x11)], [(0, 0x0A09)], [0, 4]))
    got = F.sound_run_agreement(o, u, 16)
    assert got["sound_run_agreement"] == 1.0
    assert got["sound_run_delta"] == 0


def test_a_note_one_frame_short_reads_as_a_delta_of_minus_one():
    """The corpus-wide signature as shipped: nothing matches, and the number
    worth reading is the delta rather than the zero."""
    o = _voices(([(0, 0x11)], [(0, 0x0A09)], [0, 4]))
    u = _voices(([(0, 0x11), (3, 0x09)], [(0, 0x0A09)], [0, 4]))
    got = F.sound_run_agreement(o, u, 16)
    assert got["sound_run_matched"] == 0
    assert got["sound_run_delta"] == -1


def test_an_instrument_only_one_side_plays_is_absent_rather_than_wrong():
    """`melody` already reports a dropped instrument; counting it here too
    would let one defect move two columns."""
    o = _voices(([(0, 0x11)], [(0, 0x0A09)], [0, 4]),
                ([(0, 0x41)], [(0, 0x0F00)], [0, 4]))
    u = _voices(([(0, 0x11)], [(0, 0x0A09)], [0, 4]))
    assert F.sound_run_agreement(o, u, 16)["sound_run_instruments"] == 1


def test_the_dimension_is_registered_and_printed():
    """`tests/test_fidelity.py` fails if the registry and the header disagree;
    this is the same check from the other end."""
    keys = [d.key for d in F.DIMENSIONS]
    assert "sound_run_agreement" in keys
    assert [d for d in F.DIMENSIONS if d.key == "sound_run_agreement"][0].column == "hold"
