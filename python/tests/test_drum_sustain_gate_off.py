"""drum_sustain_gate_off: the drum shape for a SUSTAINING record; keep_hard_restart.

The player's drum block closes the gate and falls the pitch whatever the
record's sustain: Crazy_Comets record 1 (`00 08 81 1A 69 00 00 01`, S=6)
reads `81` then `80`, freq-hi $13 -> $0E, from each onset. Until v0.5.615 the
sustain rule (v0.5.164's verdict on Commando) held it `81` gated and flat
even under drum_gate_off. Per song, not folded into drum_gate_off, which
would also move five songs nobody heard with it (Last_V8_C128_version among
them, approved by ear). Heard 2026-10-25: Spellbound and Warhawk right with
the drum shape; Crazy_Comets right only with keep_hard_restart as well,
because its drum then releases on R=9 into the next note and the SID's ADSR
delay swallowed beats (gate-rest-encoding run record).
"""
import io
import json
import contextlib
from pathlib import Path

import pytest

from corpus import CORPUS, needs_corpus
from h2g.convert import convert
from h2g.goatwriter.constants import WAVECMD_PORTADOWN

REPO = Path(__file__).resolve().parents[2]
CRAZY = "Crazy_Comets"


def _song(stem, **over):
    import fidelity as F
    from songview import parse_sng
    doc = json.loads((REPO / "presets.json").read_text("utf-8"))
    opts = dict(F._preset_opts(doc, f"{stem}.sid"), **over)
    with contextlib.redirect_stdout(io.StringIO()):
        return parse_sng(convert(str(CORPUS / f"{stem}.sid"),
                                 log=lambda m: None, **opts))


def _wave(song, ad, sr):
    """The wavetable rows of the instrument with this ADSR, up to its stop."""
    ins = [i for i in song.instruments if (i.ad, i.sr) == (ad, sr)]
    assert ins, f"no instrument {ad:02X}{sr:02X}: the test is blind"
    rows, p = [], ins[0].wave_ptr - 1
    while song.tables["WTBL"][p][0] != 0xFF:
        rows.append(tuple(song.tables["WTBL"][p]))
        p += 1
    return rows


@needs_corpus
def test_a_sustaining_drum_gets_the_gate_off_and_the_fall_under_the_option():
    """SABOTAGE TARGET: dropping `det.drum_sustain_gate_off or` from the
    sustain exemption holds record 1 at `81` and this fails."""
    rows = _wave(_song(CRAZY), 0x1A, 0x69)
    assert rows[0][0] == 0x81, rows
    assert any(left == 0x80 for left, _ in rows[1:]), rows   # gate released
    assert any(left == WAVECMD_PORTADOWN for left, _ in rows), rows  # the fall


@needs_corpus
def test_the_sustaining_drum_keeps_the_old_rule_without_the_option():
    """Option off: the v0.5.164 sustain rule still holds the gate."""
    rows = _wave(_song(CRAZY, drum_sustain_gate_off=False), 0x1A, 0x69)
    assert all(left & 0x01 for left, _ in rows), rows
    assert not any(left == WAVECMD_PORTADOWN for left, _ in rows), rows


@needs_corpus
def test_the_fall_is_not_withheld_for_sustain_under_the_option():
    """SABOTAGE TARGET: passing the record's sustain to `_drum_entries` again
    drops the PORTADOWN steps; the gate-off alone would still pass the test
    above, so this one names the sweep separately."""
    rows = _wave(_song(CRAZY), 0x1A, 0x69)
    assert sum(left == WAVECMD_PORTADOWN for left, _ in rows) >= 1


@needs_corpus
def test_keep_hard_restart_clears_bit_80_on_every_instrument():
    """SABOTAGE TARGET: dropping `and not keep_hard_restart` in convert()
    leaves bit $80 set, and this fails."""
    on = _song(CRAZY)                                    # presets: keep on
    off = _song(CRAZY, keep_hard_restart=False)
    assert on.instruments and all(not (i.gatetimer & 0x80) for i in on.instruments)
    assert all(i.gatetimer & 0x80 for i in off.instruments)
    # the option changes the hard-restart flag and nothing else
    assert [(i.ad, i.sr, i.wave_ptr, i.gatetimer & 0x7F) for i in on.instruments] \
        == [(i.ad, i.sr, i.wave_ptr, i.gatetimer & 0x7F) for i in off.instruments]
    assert on.patterns == off.patterns and on.tables == off.tables


@needs_corpus
@pytest.mark.parametrize("stem", ["Spellbound", "Warhawk"])
def test_the_heard_songs_take_the_drum_shape_without_keep_hard_restart(stem):
    """Spellbound and Warhawk were heard right with the drum shape alone."""
    import fidelity as F
    doc = json.loads((REPO / "presets.json").read_text("utf-8"))
    opts = F._preset_opts(doc, f"{stem}.sid")
    assert opts.get("drum_sustain_gate_off") and not opts.get("keep_hard_restart")


@needs_corpus
def test_the_option_reaches_only_the_heard_songs():
    """Approved and unheard drum_gate_off songs do not take it."""
    import fidelity as F
    doc = json.loads((REPO / "presets.json").read_text("utf-8"))
    took = {k for k in doc["songs"]
            if F._preset_opts(doc, k).get("drum_sustain_gate_off")}
    assert took == {"Crazy_Comets.sid", "Spellbound.sid", "Warhawk.sid",
                    "Proteus.sid"}  # Proteus heard 2026-10-31


@needs_corpus
def test_the_shipped_last_v8_c128_still_emits_its_skydive_with_the_option():
    """The skydive overflow seen with the option is test_skydive_compact's
    fixture (dead_blocks off), not the shipped path: forced on, the shipped
    conversion keeps its 98 compact steps."""
    import fidelity as F
    doc = json.loads((REPO / "presets.json").read_text("utf-8"))
    stem = "Last_V8_C128_version"
    lines = []
    with contextlib.redirect_stdout(io.StringIO()):
        convert(str(CORPUS / f"{stem}.sid"), log=lines.append,
                **dict(F._preset_opts(doc, f"{stem}.sid"),
                       drum_sustain_gate_off=True))
    sky = [m for m in lines if m.startswith("Skydive")]
    assert sky and "not emitted" not in sky[0] and "98 wavetable step(s)" in sky[0], sky
