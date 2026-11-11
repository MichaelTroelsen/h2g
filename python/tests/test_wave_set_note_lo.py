"""A `>= $80` wave-program opcode writes `$D401` alone, so its pitch is
`arg:lo` with `lo` inherited from the previous frame (Lion_Heart `$16C4-$16DA`).

Lion_Heart's noise drum plays C-4 and the player's operand is `$5F` on frames
1, 4 and 5. Traced (`C:/t/corpus-melody-column-sub99-mechanisms/work/lh`): frame
1 `5F67` (the note's own low byte `$67`), frames 4-5 `5FBB` (`$BB` of
`$1167 - $05AC`, the two slides' sum). `5F67` is nearer F-6, `5FBB` nearer F#6;
`_sfx_note_byte` quantised `5F00` and wrote F-6 for all three, so the melody
column read 123 tokens a semitone low (91.5%). `_wave_set_note_byte` takes the
low byte from the running slide total and the instrument's played notes.
"""
import pathlib
import sys

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[1]))

import fidelity                                              # noqa: E402
import songview                                              # noqa: E402
from corpus import CORPUS, needs_corpus                      # noqa: E402
from h2g.convert import convert                              # noqa: E402
from h2g.goatwriter import wave_program                      # noqa: E402
from h2g.goatwriter.constants import WAVE_NOTE_ABS           # noqa: E402

REPO_ROOT = pathlib.Path(__file__).resolve().parents[2]
F_6, F_SHARP_6 = 77, 78                      # note indices; GT 5CF1 / 6278
C_4 = 48                                     # GT 1168


def test_the_low_byte_follows_the_slides_not_zero():
    set_byte = wave_program._wave_set_note_byte
    # Frame 1: no slide yet, lo = the note's own $68 -> 5F68, nearer F-6.
    assert set_byte(0x5F, {C_4: 10}, 0) == WAVE_NOTE_ABS + F_6
    # Frames 4-5: after the two slides ($15A + $452), lo = $BC -> 5FBC, nearer F#6.
    assert set_byte(0x5F, {C_4: 10}, 0x5AC) == WAVE_NOTE_ABS + F_SHARP_6


def test_without_a_distribution_it_is_the_old_quantisation():
    for running in (0, 0x5AC):
        assert (wave_program._wave_set_note_byte(0x5F, None, running)
                == wave_program._sfx_note_byte(0x5F) == WAVE_NOTE_ABS + F_6)


def test_the_weights_decide_between_notes():
    # C-4 (lo $BC after the slides) outweighs G-3 (lo $5E, F-6): F#6 wins; the
    # other way round F-6 does.
    assert (wave_program._wave_set_note_byte(0x5F, {C_4: 10, 43: 2}, 0x5AC)
            == WAVE_NOTE_ABS + F_SHARP_6)
    assert (wave_program._wave_set_note_byte(0x5F, {C_4: 2, 43: 10}, 0x5AC)
            == WAVE_NOTE_ABS + F_6)


@needs_corpus
def test_lion_heart_drum_is_f6_then_f_sharp_6_on_the_slid_frames():
    import json
    doc = json.loads((REPO_ROOT / "presets.json").read_text(encoding="utf-8"))
    sng = convert(str(CORPUS / "Lion_Heart.sid"), log=lambda x: None,
                  **fidelity._preset_opts(doc, "Lion_Heart.sid"))
    song = songview.parse_sng(sng)
    # Record 04 (`11 81 41 41 80 81`) is the instrument whose program opens
    # tri, then noise on call 4 and 13/16.
    prog = songview.wave_program(song, song.instruments[1].wave_ptr)
    noise = [(first, right) for _, left, right, kind, _, first, _ in prog
             if left in (0x80, 0x81) and right >= WAVE_NOTE_ABS
             and right - WAVE_NOTE_ABS in (F_6, F_SHARP_6)]
    assert [(f, r - WAVE_NOTE_ABS) for f, r in noise] == [
        (4, F_6), (13, F_SHARP_6), (16, F_SHARP_6)]
