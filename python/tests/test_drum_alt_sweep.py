"""`drum_alt_sweep`: `drum_alt_fall` for a record whose budget declined it.

W_A_R_Preview's record `00 08 41 0A 09 00 00 03` (ADSR `$0A09`, effect `$03`)
sets the drum (bit $01) and the waveform alternation (bit $02). The player runs
both blocks: the voice alternates `40 / 80` and the frequency high byte falls
`$106E -> $0F6E -> $0E6E -> $0D6E -> $0C6E`, one `$0100` a frame for four
frames, on every one of the 96 hits in 180 s. `drum_alt_fall` emits that fall
(`attack._wave_alternate_entries(sweep=)`) but leaves `ALT_FALL_HEADROOM`
entries free in the record's budget, which this record's (36-42 entries)
cannot spare, so it declined. `drum_alt_sweep` is the same mechanism with no
headroom, taken only where the whole plain wavetable has room.

Per song, off by default: W_A_R_Preview ships it; W_A_R's wavetable has one
row free, so `convert` declines it there.
"""
import json
import pathlib
import sys

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[1]))

import fidelity                                              # noqa: E402
from corpus import CORPUS, needs_corpus                      # noqa: E402
from h2g.convert import convert                              # noqa: E402
from h2g.goatwriter import attack, wavetable                 # noqa: E402
from h2g.goatwriter.constants import WAVECMD_PORTADOWN       # noqa: E402
from songview import parse_sng                                # noqa: E402

PREVIEW = CORPUS / "W_A_R_Preview.sid"
WAR = CORPUS / "W_A_R.sid"
REPO_ROOT = pathlib.Path(__file__).resolve().parents[2]


def _doc() -> dict:
    return json.loads((REPO_ROOT / "presets.json").read_text(encoding="utf-8"))


def _convert(path, **kw):
    opts = fidelity._preset_opts(_doc(), path.name)
    return convert(str(path), log=lambda m: None, **{**opts, **kw})


def _swept_frames(blob):
    """Wavetable rows of every swept frame: a waveform entry that writes no
    pitch (`$80`), then a PORTADOWN of the `$0100` step, then the held calls."""
    song = parse_sng(blob)
    wave = song.tables["WTBL"]
    speed = song.tables["STBL"]
    found = []
    for at in range(1, len(wave) - 1):
        left, right = wave[at]
        if left != WAVECMD_PORTADOWN or not 0 < right <= len(speed):
            continue
        if speed[right - 1] != (0x01, 0x00):
            continue
        before = wave[at - 1]
        if before[1] == 0x80 and before[0] & 0xF0 in (0x40, 0x80):
            found.append(at)
    return found


@needs_corpus
def test_off_emits_no_swept_frame():
    assert _swept_frames(_convert(
        PREVIEW, drum_alt_fall=False, drum_alt_sweep=False)) == []


@needs_corpus
def test_on_adds_the_four_frame_fall():
    # Four frames of `$0100` is the original's fall on all 96 hits.
    assert len(_swept_frames(_convert(PREVIEW, drum_alt_sweep=True))) == 4


@needs_corpus
def test_the_fall_without_headroom_is_what_declined_it():
    # `drum_alt_fall` alone leaves the headroom and declines this record: one
    # mechanism, the headroom is the whole difference.
    fall = _convert(PREVIEW, drum_alt_fall=True, drum_alt_sweep=False)
    assert _swept_frames(fall) == []
    assert attack.ALT_FALL_HEADROOM > 0


@needs_corpus
def test_short_circuited_sweep_emits_nothing(monkeypatch):
    off = _convert(PREVIEW, drum_alt_sweep=False)
    monkeypatch.setattr(wavetable, "_alt_drum_sweep", lambda *a, **k: None)
    assert _convert(PREVIEW, drum_alt_sweep=True) == off


@needs_corpus
def test_a_full_wavetable_declines_the_sweep():
    # W_A_R leaves one of 255 rows: the fall took them and five note rows lost
    # their pinned copy (pitch 100% -> 96%), so the option is refused there and
    # the bytes are the plain conversion's.
    assert (_convert(WAR, drum_alt_sweep=True)
            == _convert(WAR, drum_alt_sweep=False))


def test_only_w_a_r_preview_ships_the_option():
    doc = _doc()
    on = sorted(name for name in doc["songs"]
                if fidelity._preset_opts(doc, name).get("drum_alt_sweep"))
    assert on == ["W_A_R_Preview.sid"]
