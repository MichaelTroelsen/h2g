"""The drum's noise tick: whose gate, how long, and which frame it starts on.

v0.5.226. Three facts, each of which the corpus caught being wrong in the
`tick` path of `_wavetable_entries` while `_drum_entries` had it right -- the
"a lesson recorded in one emitter is not a lesson in the file" shape CLAUDE.md
names.
"""
from pathlib import Path

import pytest

from h2g.goatwriter import (SongSpeeds, _noise_tick_frames, _wavetable_entries,
                            NOISE_TICK_FRAMES)
from h2g.detect import Detection
import h2g.goatwriter as G

CORPUS = Path(r"C:\Users\mit\claude\c64server\SIDM2\SID\Hubbard_Rob")

DRUM, ARP = 0x01, 0x04


class _Sid:
    """Enough of a SidFile for the record reads `_wavetable_entries` makes."""

    def __init__(self, effect: int, wave: int = 0x41, start_song: int = 1):
        # one 8-byte record at offset 8: +2 waveform, +3/+4 ADSR, +7 effect
        self.data = bytes(8) + bytes([0x00, 0x00, wave, 0x0A, 0x0A,
                                      0x00, 0x00, effect])
        self.start_song = start_song
        self.subtunes = 1


def _det(**kw):
    """A Detection `_noise_tick_frames` will accept.

    It reads `det.can_convert` before passing the detection on, so a bare
    `None` here would raise inside the function's own `except` and every
    assertion below would be measuring the `NOISE_TICK_FRAMES` fallback
    instead of the rule under test -- which is exactly what the first draft
    of this file did.
    """
    return Detection(instr_start=8, instr_stride=8, effect_drum=True, **kw)


def _speeds(frames, monkeypatch):
    monkeypatch.setattr(
        G, "find_song_speeds",
        lambda sid, det: SongSpeeds(frames=tuple(frames), reload_addr=0,
                                    table_addr=None))


def _entries(effect, *, wave=0x41, multiplier=1, drum=True, arp=True):
    det = Detection(instr_start=8, instr_stride=8,
                    effect_arp=arp, effect_drum=drum)
    return _wavetable_entries(_Sid(effect, wave), det, 0, True, "gts5", [],
                              multiplier)


# --- which subtune's gate ----------------------------------------------------

def test_the_gate_is_read_at_the_subtune_the_file_starts_on(monkeypatch):
    # Commando's own gates: four songs at 3-4 frames and fourteen one-frame
    # sound effects. The mode is 1 and the tune's gate is 3, and the original
    # measures a two-frame tick on all five of its pitched drum records.
    _speeds((3, 4, 3, 3, 1, None) + (1,) * 13, monkeypatch)
    assert _noise_tick_frames(_Sid(DRUM, start_song=1), _det()) == 2
    # `startSong` is 1-based, and a file starting on its second subtune reads
    # that subtune's gate -- 3 here, which neither the mode (1) nor the
    # constant (2) can produce, so this assertion cannot pass vacuously.
    assert _noise_tick_frames(_Sid(DRUM, start_song=2), _det()) == 3


def test_an_unreadable_start_subtune_falls_back_to_the_mode(monkeypatch):
    # `frames[s]` is None where the table byte is not a sane speed. That is a
    # reason to fall back, not to give up: the rest of the table still says
    # what this player's gate is.
    _speeds((None, 4, 4, 4), monkeypatch)
    assert _noise_tick_frames(_Sid(DRUM, start_song=1), _det()) == 3


def test_no_readable_gate_at_all_keeps_the_constant(monkeypatch):
    _speeds((None, None), monkeypatch)
    assert _noise_tick_frames(_Sid(DRUM), _det()) == NOISE_TICK_FRAMES


def test_the_gate_is_never_read_below_one_frame(monkeypatch):
    # A gate of 1 would derive a zero-frame tick, which is not "no noise" but
    # an empty wavetable entry. The player writes noise on that frame.
    _speeds((1,), monkeypatch)
    assert _noise_tick_frames(_Sid(DRUM), _det()) == 1


# --- the tick reaches a record that also arpeggiates --------------------------

def test_a_record_setting_drum_and_arpeggio_still_gets_the_tick(monkeypatch):
    # The drum block does not branch around the arpeggio: every exit of
    # International Karate's $B15F lands on the NOP at $B19B, one byte before
    # the arpeggio's own bit test. Both run, so both belong in the wavetable.
    _speeds((3,), monkeypatch)
    left, right = _entries(DRUM | ARP | 0x30)
    assert left[1] == 0x81 and left[2] == 0x81, "two frames of noise"
    assert left[3] == 0x40, "then the record's waveform with the gate released"
    assert right[4] == 0x7D, "and the arpeggio keeps its -3 semitones"


def test_the_tick_length_follows_the_gate_and_not_the_constant(monkeypatch):
    # Gate 2 -> one frame of noise. Warhawk, Formula_1_Simulator, Spellbound,
    # Proteus and Last_V8 are this case, and all five regressed on `nrun` when
    # the tick first reached their both-bits records at the hardcoded 2.
    _speeds((2,), monkeypatch)
    left, _ = _entries(DRUM | ARP | 0x30)
    assert left[:3] == [0x41, 0x81, 0x40], "one noise entry, then the tail"


# --- and it starts on the note's second frame, at every -S --------------------

@pytest.mark.parametrize("multiplier,expect", [
    (1, [0x41, 0x81, 0x81, 0x40]),
    (2, [0x41, 0x41, 0x81, 0x02, 0x40]),
    (3, [0x41, 0x01, 0x81, 0x04, 0x40]),
])
def test_frame_zero_belongs_to_the_record_at_every_multiplier(
        multiplier, expect, monkeypatch):
    """One frame is `multiplier` play calls.

    At -S2 a one-call lead covers half of frame 0 and the tick finishes it, so
    siddump -- which samples at end of frame -- reads the noise where the
    player has the record's own waveform. Warhawk's five ticked instruments all
    measured `noi pul pul pul` against the original's `pul noi pul pul` until
    this shared `_first_frame_lead` with `_drum_entries`.
    """
    _speeds((3,), monkeypatch)
    left, _ = _entries(DRUM | ARP | 0x30, multiplier=multiplier)
    assert left[:len(expect)] == expect


# --- the corpus file the rule was derived from -------------------------------

def test_commando_derives_two_frames_from_its_own_header():
    if not CORPUS.is_dir():
        return
    from h2g.convert import _detect_tables
    from h2g.sidfile import load_sid
    # The corpus rip carries 19 subtunes where the repo fixture carries 3, so
    # this is the file the mode got wrong while the fixture's mode was right --
    # which is why `tests/test_effects.py`'s reading of the *fixture* passed
    # throughout and every fidelity number for Commando was taken at 1.
    sid, det = _detect_tables(load_sid(str(CORPUS / "Commando.sid")),
                              lambda *a, **k: None)
    assert sid.subtunes == 19
    assert _noise_tick_frames(sid, det) == 2
