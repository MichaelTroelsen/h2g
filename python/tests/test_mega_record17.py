"""Mega_Apocalypse record 17 is the player's silent power-on instrument.

A runtime trace (py65, init $5822 then the IRQ vector, 20000 frames) loads
record 17 on voices 0 and 2 from frame 2 -- 1330 and 190 frames -- yet the
presets conversion emits GT instruments only for records 0-16. That is correct:

* the player's reset code at $4AC6 is `LDA #$11 / STA $C9,X`, so 17 ($11) is
  every voice's instrument index until a pattern row sets one -- it is never
  set by a pattern (the only other writer of $C9,X, $4B70, only ever wrote
  0-16 in the same trace);
* record 17 is eight zero bytes: AD/SR 0, waveform 0, no vibrato, no effect.
  It sounds nothing, and the SID shows voice 0 and 2 ungated until their
  first pattern-set instrument (frames 1345 and 193);
* the writer emits it as GT 18, no pattern names it, and
  `instrument_drop.drop_unnamed_instruments` removes it (with 18-20, which are
  also unnamed): "Dropped 4 instrument(s) no pattern names: $12, $13, $14, $15".

The converse risk would be a note reaching a voice before its first instrument
column: GT starts every channel on instrument 1 (record 0, audible under
--compact-instruments), where the original plays the silent record 17. No
voice of the emitted song does that.
"""
import json
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from corpus import CORPUS, needs_corpus          # noqa: E402
import fidelity as F                             # noqa: E402
import songview                                  # noqa: E402
from h2g import detect as D, sidfile             # noqa: E402
from h2g.convert import convert                  # noqa: E402
from h2g.instrument_drop import named_instruments  # noqa: E402

REPO = Path(__file__).resolve().parents[2]
PRESETS = REPO / "presets.json"
NAME = "Mega_Apocalypse.sid"
SID = CORPUS / NAME

pytestmark = [needs_corpus,
              pytest.mark.skipif(not PRESETS.exists(),
                                 reason="presets.json absent")]


def _opts():
    doc = json.loads(PRESETS.read_text(encoding="utf-8"))
    return F._preset_opts(doc, NAME)


def _convert(**override):
    logs = []
    opts = _opts()
    opts.update(override)
    blob = convert(str(SID), log=logs.append, **opts)
    return blob, logs


def test_record_17_is_eight_zero_bytes():
    sid = sidfile.load_sid(str(SID))
    det = D.detect(sid, lambda s: None)
    assert det.instr_stride == 8 and det.instr_used == 21
    rec = sid.data[det.instr_start + 17 * 8:det.instr_start + 18 * 8]
    assert bytes(rec) == bytes(8), rec.hex()


def test_the_reset_code_makes_17_every_voices_instrument_index():
    sid = sidfile.load_sid(str(SID))
    # LDA #$11 / STA $C9,X / DEX / BPL back -- the loop at $4AC6.
    assert bytes.fromhex("A911 95C9 CA 10E6".replace(" ", "")) in sid.data


def test_no_pattern_names_record_17_so_it_is_dropped():
    blob, _ = _convert(drop_unnamed_instruments=False)
    named = named_instruments(blob)
    # GT instrument n is record n-1 under compact_instruments: record 17 is
    # GT 18, and no pattern column holds anything above 17.
    assert max(named) == 17, sorted(named)
    assert 18 not in named
    blob, logs = _convert()
    assert any("Dropped 4 instrument(s) no pattern names: $12, $13, $14, $15"
               in line for line in logs), logs
    assert len(songview.parse_sng(blob).instruments) == 17


def test_every_voice_names_an_instrument_before_its_first_note():
    blob, _ = _convert()
    song = songview.parse_sng(blob)
    assert song.subtunes == 1
    for voice in range(3):
        seen = False
        first_note = None
        for entry in song.tracks[voice]:
            if entry >= 0xD0 or entry >= len(song.patterns):
                continue
            pat = song.patterns[entry]
            for r in range(len(pat) // 4):
                note, ins = pat[r * 4], pat[r * 4 + 1]
                seen = seen or bool(ins)
                if 0 < note < 0xBC:
                    first_note = (entry, r, seen)
                    break
            if first_note:
                break
        assert first_note is not None, f"voice {voice} has no note"
        assert first_note[2], \
            f"voice {voice}: first note (pattern {first_note[0]:#x} row " \
            f"{first_note[1]}) precedes any instrument column, so GT would " \
            "play instrument 1 where the original plays the silent record 17"
