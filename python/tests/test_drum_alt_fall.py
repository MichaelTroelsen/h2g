"""`drum_alt_fall`: bit $01's high-byte fall inside bit $02's alternation program.

Lightforce records 2 and 16 (effect `$23`, `$F3C4`) are played only as six-row
notes (48 notes of 48 in 180 s, emulated), and from the second duration unit
the player subtracts `$0100` from the voice's frequency a frame for four units
while the waveform goes on alternating beside it: siddump reads
`4456 -> 4200 -> 3944 .. 872` over frames 3630-3643 of the original, 480 steps
of `$0100` over the window, which is all of voice 1's `travel` (122,880 of
174,916). `_drum_entries` carries a sweep and `drum_long` the long notes', but
both decline a record that alternates, so this fall never reached the chip and
the file read `travel` 0.24x.
"""
import json
import pathlib
import sys

import pytest

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[1]))

from corpus import CORPUS, needs_corpus               # noqa: E402
import fidelity as F                                  # noqa: E402
import songview                                       # noqa: E402
from h2g import detect, sidfile                       # noqa: E402
from h2g.convert import convert                       # noqa: E402
from h2g.goatwriter import attack                     # noqa: E402
from h2g.goatwriter.constants import (WAVECMD_PORTADOWN,  # noqa: E402
                                      WAVE_NOTE_KEEP)

REPO = pathlib.Path(__file__).resolve().parents[2]
PRESETS = REPO / "presets.json"
STEP = (1, 0)


def _lightforce(**extra):
    doc = json.loads(PRESETS.read_text(encoding="utf-8"))
    opts = F._preset_opts(doc, "Lightforce.sid")
    opts.pop("drum_alt_fall", None)
    opts.update(extra)
    return convert(str(CORPUS / "Lightforce.sid"), log=lambda _m: None, **opts)


def _fall_entries(blob):
    """(wavetable entries that step the pitch down by `$0100`)."""
    song = songview.parse_sng(blob)
    stbl = song.tables["STBL"]
    wtbl = song.tables["WTBL"]
    idx = [k + 1 for k, e in enumerate(stbl) if tuple(e) == STEP]
    assert len(idx) <= 1, stbl
    return [(i + 1, e) for i, e in enumerate(wtbl)
            if e[0] == WAVECMD_PORTADOWN and idx and e[1] == idx[0]]


@needs_corpus
def test_the_option_off_is_the_default_byte_for_byte():
    assert _lightforce() == _lightforce(drum_alt_fall=False)


@needs_corpus
def test_the_option_carries_a_fourteen_frame_fall_on_each_of_the_two_records():
    off, on = _lightforce(), _lightforce(drum_alt_fall=True)
    assert on != off
    assert not _fall_entries(off)
    # Two records x (6 - 2) rows x 7 calls / 2 calls a frame = 14 steps each.
    assert len(_fall_entries(on)) == 2 * 14


@needs_corpus
def test_the_fall_is_one_step_a_frame_on_the_frames_last_call():
    song = songview.parse_sng(_lightforce(drum_alt_fall=True))
    wtbl = song.tables["WTBL"]
    steps = [i for i, e in enumerate(wtbl) if e[0] == WAVECMD_PORTADOWN
             and tuple(song.tables["STBL"][e[1] - 1]) == STEP]
    # Every step sits on the second call of its frame: the waveform entry
    # before it keeps the pitch (`$80`), and the pair keeps alternating.
    for i in steps:
        assert wtbl[i - 1][1] == WAVE_NOTE_KEEP, (i, wtbl[i - 1])
        assert wtbl[i - 1][0] in (0x40, 0x80), (i, wtbl[i - 1])
    assert steps[1] - steps[0] == 2


def test_the_layout_alternates_beside_the_fall_and_holds_the_pitch_after_it():
    left, right = attack._wave_alternate_entries(
        0x41, 0x81, 2, start=10, budget=60, gate_frames=3, sweep=(lambda: 4, 5))
    assert left.count(WAVECMD_PORTADOWN) == 5
    steps = [k for k, b in enumerate(left) if b == WAVECMD_PORTADOWN]
    assert all(right[k] == 4 for k in steps)
    # The waveform entry in front of each step is the gate-off half of the
    # pair, in the alternation's phase, with the pitch left alone.
    assert [left[k - 1] for k in steps] == [0x40, 0x80, 0x40, 0x80, 0x40]
    assert all(right[k - 1] == WAVE_NOTE_KEEP for k in steps)
    # The loop after the fall keeps the pitch where the fall left it.
    assert left[-1] == 0xFF
    loop = right[-1] - 10
    assert all(r == WAVE_NOTE_KEEP for r in right[loop:-1])
    # Five fall frames end on a gate-off `$40`, so the loop opens on `$80`.
    assert left[loop:-1] == [0x80, 0x80, 0x40, 0x40]


def test_without_a_sweep_or_below_two_calls_a_frame_the_program_is_unchanged():
    plain = attack._wave_alternate_entries(
        0x41, 0x81, 2, start=10, budget=60, gate_frames=3)
    assert attack._wave_alternate_entries(
        0x41, 0x81, 2, start=10, budget=60, gate_frames=3, sweep=None) == plain
    # One call a frame cannot write the waveform and step the pitch.
    one = attack._wave_alternate_entries(
        0x41, 0x81, 1, start=10, budget=60, gate_frames=3)
    assert attack._wave_alternate_entries(
        0x41, 0x81, 1, start=10, budget=60, gate_frames=3,
        sweep=(lambda: 4, 5)) == one
    # A fall that does not fit declines to the plain alternation.
    assert attack._wave_alternate_entries(
        0x41, 0x81, 2, start=10, budget=12, gate_frames=3,
        sweep=(lambda: 4, 14)) == attack._wave_alternate_entries(
            0x41, 0x81, 2, start=10, budget=12, gate_frames=3)


@needs_corpus
def test_the_decrement_spelling_is_read_off_the_player():
    for name, expect in (("Lightforce.sid", True), ("Commando.sid", False)):
        path = CORPUS / name if name != "Commando.sid" else REPO / name
        sid = sidfile.load_sid(str(path))
        det = detect.detect(sid, lambda _m: None)
        assert det.effect_drum, name
        assert det.drum_shadow_dec is expect, name


def test_the_option_is_per_song_and_never_in_the_always_block():
    import presets
    assert "drum_alt_fall" in presets.EXCLUDED_FROM_ALWAYS
    doc = json.loads(PRESETS.read_text(encoding="utf-8"))
    assert "drum_alt_fall" not in doc["always"]


def test_a_layout_that_declines_claims_no_speed_table_entry():
    claimed = []

    def resolve():
        claimed.append(1)
        return 4

    plain = attack._wave_alternate_entries(
        0x41, 0x81, 2, start=10, budget=12, gate_frames=3)
    assert attack._wave_alternate_entries(
        0x41, 0x81, 2, start=10, budget=12, gate_frames=3,
        sweep=(resolve, 14)) == plain
    assert not claimed
    attack._wave_alternate_entries(
        0x41, 0x81, 2, start=10, budget=80, gate_frames=3, sweep=(resolve, 14))
    assert claimed == [1]


def test_the_fall_leaves_headroom_for_the_records_laid_after_it():
    swept = attack._wave_alternate_entries(
        0x41, 0x81, 2, start=10, budget=60, gate_frames=3,
        sweep=(lambda: 4, 5))
    fits = len(swept[0]) + attack.ALT_FALL_HEADROOM
    assert attack._wave_alternate_entries(
        0x41, 0x81, 2, start=10, budget=fits, gate_frames=3,
        sweep=(lambda: 4, 5)) == swept
    assert attack._wave_alternate_entries(
        0x41, 0x81, 2, start=10, budget=fits - 1, gate_frames=3,
        sweep=(lambda: 4, 5)) != swept
