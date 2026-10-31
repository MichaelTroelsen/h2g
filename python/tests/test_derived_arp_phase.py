"""The derived dialect's counter half on the attack frame (Hollywood, Chicken).

The command-table player's bit-$02 alternation (`$0774`: `AND #$01 / BEQ
own`, noise on odd counts) and its nibble arpeggio (`$0792`: `AND #mask /
BNE note`, the note lowered on clear) read ONE global counter, `$09A2`, and
both run on the note's own frame: the note-start path falls into the
per-frame effects. So Hollywood_or_Bust sub 2 record 9 (`$D6`, nibble 13,
mask $01) sounds `0C4E/11 1A13/81 0C4E/11 1A13/81` from every onset -- the
lowered note FIRST -- where every Goattracker shape here assumed Commando's
reading (the block starts on frame 1) and played `1A15 1A15 0C4F` and
`11 11 81`. `derived_arp_parities` walks the counter's parity per
instrument; the two shapes take it where the wavetable owns the attack frame
(`aligned_firstwave`, which Hollywood's preset sets alongside
`wave_alternate`).

Measured at -t 180 under presets, sub 2 (run record
hollywood-or-bust-melody-77-root-cause): with aligned_firstwave and
wave_alternate, record 9's onsets read `>,=,>` from the attack on 375 of
375 against the original's 375 of 375; melody .774 -> .944, onset .778 ->
1.0, wave .833 -> .945.
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

import pytest

PYTHON_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PYTHON_ROOT))

from h2g.detect import detect  # noqa: E402
from h2g.goatwriter import arpeggio as A  # noqa: E402
from h2g.goatwriter.appending import _parse_song  # noqa: E402
from h2g.goatwriter.wavetable import _wavetable_entries  # noqa: E402
from h2g.sidfile import load_sid  # noqa: E402

CORPUS = Path("C:/Users/mit/claude/c64server/SIDM2/SID/Hubbard_Rob")
HOLLYWOOD = CORPUS / "Hollywood_or_Bust.sid"
CHICKEN = CORPUS / "Chicken_Song.sid"
needs_corpus = pytest.mark.skipif(not HOLLYWOOD.exists(),
                                  reason="the Hubbard corpus is not on this machine")
REC9 = 9                       # `$D6`: wave $11, nibble 13, mask $01
LOWERED = 0x80 - 13            # `$73`, the note minus 13 (F#3 under G-4)


def _load(path):
    sid = load_sid(str(path))
    return sid, detect(sid, log=lambda m: None)


def _opts(name, **over):
    import fidelity as F
    doc = json.load(open(PYTHON_ROOT.parent / "presets.json"))
    return {**F._preset_opts(doc, name), "skip_gate": True, **over}


def _record_block(blob, rec, lead=0):
    """Record `rec`'s wavetable program, from its pointer to the jump."""
    song = _parse_song(blob)
    wave = song.tables[0]
    ptr = song.instruments[rec + lead][2]
    out = []
    for k in range(ptr - 1, len(wave)):
        out.append(wave[k])
        if wave[k][0] == 0xFF:
            return out, ptr
    return out, ptr


# --- the shape, given a parity ---------------------------------------------

@needs_corpus
@pytest.mark.parametrize("parity, want", [(0, [LOWERED, 0x00]),
                                          (1, [0x00, LOWERED])])
def test_the_attack_frame_takes_the_counters_half(parity, want):
    sid, det = _load(HOLLYWOOD)
    det.derived_arp_parity = {REC9 + 1: parity}
    got = _wavetable_entries(sid, det, REC9, True, "gts5", [], 1, lead=0,
                             start=6, budget=12)
    assert got == ([0x11, 0x11, 0xFF], want + [6])


@needs_corpus
def test_a_written_firstwave_keeps_its_bytes():
    """Under `--no-test-restart` the init call is the attack's gate a frame
    before its pitch; the shape there is the one it always was."""
    sid, det = _load(HOLLYWOOD)
    before = _wavetable_entries(sid, det, REC9, True, "gts5", [], 1, lead=0,
                                start=6, budget=12, no_test_restart=True)
    det.derived_arp_parity = {REC9 + 1: 0}
    after = _wavetable_entries(sid, det, REC9, True, "gts5", [], 1, lead=0,
                               start=6, budget=12, no_test_restart=True)
    assert after == before


@needs_corpus
def test_no_parity_no_change():
    sid, det = _load(HOLLYWOOD)
    assert det.derived_arp_parity == {}
    got = _wavetable_entries(sid, det, REC9, True, "gts5", [], 1, lead=0,
                             start=6, budget=12)
    assert got[1][:3] == [0x00, 0x00, LOWERED]      # Commando's reading


@needs_corpus
def test_the_derived_pair_puts_the_noise_on_frame_1():
    """`tri noi tri noi`: the lead is the own half (the lowered note on the
    record's waveform), then the noise half carrying the note."""
    sid, det = _load(HOLLYWOOD)
    det.derived_arp_parity = {REC9 + 1: 0}
    got = _wavetable_entries(sid, det, REC9, True, "gts5", [], 1, lead=0,
                             start=6, budget=12, wave_alternate=True)
    assert got == ([0x11, 0x81, 0x11, 0xFF], [LOWERED, 0x00, LOWERED, 7])


# --- the walk ----------------------------------------------------------------

@needs_corpus
def test_the_walk_is_the_derived_dialect_only():
    for path, want in ((HOLLYWOOD, True), (CHICKEN, True),
                       (CORPUS / "W_A_R.sid", False),
                       (CORPUS / "Commando.sid", False)):
        sid, det = _load(path)
        assert det.wave_alternate_arp is want, path.name
        if not want:
            assert A.derived_arp_parities(sid, det, [[0]], [[]]) == {}


@needs_corpus
def test_hollywood_converts_record_9_lowered_first():
    from h2g.convert import convert
    blob = convert(str(HOLLYWOOD), log=lambda m: None,
                   **_opts(HOLLYWOOD.name, aligned_firstwave=True,
                           wave_alternate=False))
    block, ptr = _record_block(blob, REC9)
    assert block == [(0x11, LOWERED), (0x11, 0x00), (0xFF, ptr)]
    blob = convert(str(HOLLYWOOD), log=lambda m: None,
                   **_opts(HOLLYWOOD.name, aligned_firstwave=True,
                           wave_alternate=True))
    block, ptr = _record_block(blob, REC9)
    assert block == [(0x11, LOWERED), (0x81, 0x00), (0x11, LOWERED),
                     (0xFF, ptr + 1)]


@needs_corpus
def test_hollywoods_preset_takes_both():
    o = _opts(HOLLYWOOD.name)
    assert o["aligned_firstwave"] and o["wave_alternate"]
