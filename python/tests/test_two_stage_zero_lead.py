"""A waveform-$00 two-stage + pitch-sequence record gets an entry for the note's silent frame 0.

Trans-Atlantic voice 1, record `AD$0A SR$F8` effect `$14`: the original's note frame is
`wf $00` with the pitch and ADSR written (gate clear), and the attack opens on the NEXT
frame -- `1D46 .. 00 0AF8` then `7518 A-6 D1 11` at frames 75, 76 of the 180 s trace.
Ours spent the init call on the firstwave and put the attack `11` on the wavetable's
first entry, so the gate rose on the row's frame, a frame before the original's, on
every such note (139 of 384 voice-1 attacks 1 frame early at the harness lag), and the
global-phase steps `phases` names for frames 1, 2, ... after the attack fell a frame
early with it (voice-1 pitch misses over 50 cents: 1653 -> 574 frames of 8733).

`attack.ZERO_WAVE_LEAD` switches the entry, so the test can show it is what moves the
bytes.
"""
import json
import pathlib
import sys

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[1]))

import fidelity                                              # noqa: E402
import songview                                              # noqa: E402
from corpus import CORPUS, needs_corpus                      # noqa: E402
from h2g.goatwriter import attack                            # noqa: E402
from h2g.goatwriter.attack import _two_stage_pitch_seq_entries  # noqa: E402
from h2g.goatwriter.constants import WAVE_NOTE_BASE          # noqa: E402

REPO_ROOT = pathlib.Path(__file__).resolve().parents[2]
NAME = "Trans-Atlantic_Balloon_Challenge.sid"
NOTES = [0, 24, 0]


def _block(wave, written=False, multiplier=1):
    return _two_stage_pitch_seq_entries(wave, 0x11, 5, list(NOTES), 10,
                                        multiplier, 40, written=written)


def test_a_record_with_no_waveform_opens_on_a_silent_note_entry():
    left, right = _block(0x00)
    assert (left[0], right[0]) == (0x00, WAVE_NOTE_BASE)
    assert left[1] == 0x11                   # the attack is the SECOND frame
    # The jump still targets the sustain stage, one entry further on.
    assert left[-1] == 0xFF and right[-1] == 10 + 1 + 5


def test_the_lead_is_one_frame_at_every_multiplier():
    for m in (1, 2, 3):
        left, _ = _block(0x00, multiplier=m)
        assert left[:m] == [0x00] * m and left[m] == 0x11, (m, left[:m + 1])


def test_a_record_with_a_waveform_or_written_firstwave_is_untouched():
    plain = _block(0x41)
    assert plain[0][0] == 0x41               # `_first_frame_entry`'s own lead
    left, _ = _block(0x00, written=True)     # --no-test-restart: firstwave has it
    assert left[0] == 0x11


def test_the_switch_removes_it(monkeypatch):
    monkeypatch.setattr(attack, "ZERO_WAVE_LEAD", False)
    left, _ = _block(0x00)
    assert left[0] == 0x11


@needs_corpus
def test_trans_atlantic_record_3_and_its_clones_open_on_the_lead(monkeypatch):
    from h2g.convert import convert
    doc = json.loads((REPO_ROOT / "presets.json").read_text(encoding="utf-8"))
    opts = fidelity._preset_opts(doc, NAME)

    def firsts():
        sng = convert(str(CORPUS / NAME), log=lambda m: None, **opts)
        song = songview.parse_sng(sng)
        wtbl = song.tables["WTBL"]
        return [wtbl[i.wave_ptr - 1] for i in song.instruments
                if i.name.endswith("-14") and i.wave_ptr]

    on = firsts()
    assert on and all(e == (0x00, WAVE_NOTE_BASE) for e in on), on
    monkeypatch.setattr(attack, "ZERO_WAVE_LEAD", False)
    off = firsts()
    assert off and all(e[0] == 0x11 for e in off), off
