"""The zero-page spelling of the gate-hold guard (Spellbound), and what it ties.

Task `spellbound-sweep-note-gate-and-legato`. Spellbound's player reads the
status byte from zero page:

    E18D  B5 C7     LDA $C7,X      ; status
    E18F  29 20     AND #$20 / BNE $E1A7
    E193  BD CA E4  LDA $E4CA,X / BNE $E1A7   ; the counter
    E198  B5 CA     LDA $CA,X / AND #$FE / STA $D404,Y      ; gate off

so `detect.GATE_HOLD_SHAPE` (`BD ?? ??`, absolute) never matched it and
`find_gate_hold` said False. Its sequencer is `E07E DEC $E4CA,X / BMI / JMP
$E182`, and the row clock's bypass `E072 BNE $E089 -> JMP $E1A7` lands PAST
the gate-off -- Human_Race's case, so a zero-`wait` event keeps its gate.

What that does to the music (siddump, subtune 0, voice 1, 180 s, measured
2026-10-07 on 6e467ff plus the cycle-6 merge, historical): 13 times the
original plays a 4-5 frame `$0FFF` drum hit (pattern $14 `81 0D 3B`, wait 1),
closes the gate for 2 frames, RE-GATES at +4/+5 on a chain of six wait-0
events (`00 42`, `00 47`, ... `00 5F`) whose gate it holds for 14-15 frames,
then lands LEGATO on the `$0F0A` record. Without the tie the chain was six
attacked one-row notes whose gatetimer (10 calls = the row) shut each gate on
its own first call: the sweep played gate-off, and the `$0F0A` note attacked.

The other direction of `find_gate_hold` is pinned by tests/test_gate_hold.py;
this file pins only the new spelling and Spellbound.
"""
import json
import pathlib

import pytest

from h2g.detect import (GATE_HOLD_SHAPE, GATE_HOLD_ZP_SHAPE,
                        find_gate_hold)
from h2g.search import search_file
from h2g.sidfile import SidFile, load_sid

from corpus import CORPUS, needs_corpus

PYTHON_ROOT = pathlib.Path(__file__).resolve().parents[1]
REPO_ROOT = PYTHON_ROOT.parent

LOAD = 0x1000
CLOCK = 0x40
DEC = 0x50
TEST = 0x80
COUNTER = 0x1234
CMD_TONEPORTA = 3


def _player(bypass_into_test: bool, *, split_target: bool = False,
            stray_primary: bool = False, stray_lsr: bool = False) -> SidFile:
    """A minimal player with the ZERO-PAGE status read, laid out as
    test_gate_hold._player lays out the absolute one. `split_target` sends
    the counter guard's BNE somewhere other than the bit-5 guard's;
    `stray_primary` / `stray_lsr` add a GATE_HOLD_SHAPE / LSR-spelling match
    elsewhere whose BNEs disagree, so that spelling matches but reaches no
    verdict -- and the zero-page one, a fallback, must then not be read."""
    from h2g.sidfile import HLEN
    base = HLEN - 1
    data = bytearray(base + 0x200)

    def put(off, *bs):
        data[base + off:base + off + len(bs)] = bytes(bs)

    def rel(frm, to):
        d = to - (frm + 2)
        assert -128 <= d <= 127, (frm, to)
        return d & 0xFF

    out = TEST + 11
    # LDA zp,X / AND #$20 / BNE out / LDA COUNTER,X / BNE out
    put(TEST, 0xB5, 0xC7, 0x29, 0x20, 0xD0, rel(TEST + 4, out),
        0xBD, COUNTER & 0xFF, COUNTER >> 8,
        0xD0, rel(TEST + 9, out + 2 if split_target else out))
    put(out, 0xB5, 0xCA, 0x29, 0xFE, 0x99, 0x04, 0xD4)
    if stray_primary:
        s = 0xC0
        put(s, 0xBD, 0x00, 0x13, 0x29, 0x20, 0xD0, rel(s + 5, 0xD0),
            0xBD, COUNTER & 0xFF, COUNTER >> 8, 0xD0, rel(s + 10, 0xD4))
    if stray_lsr:
        s = 0xC0
        put(s, 0xBD, 0x00, 0x13, 0x29, 0x20, 0xD0, rel(s + 5, 0xE0),
            0xBD, COUNTER & 0xFF, COUNTER >> 8, 0x4A,
            0xDD, COUNTER & 0xFF, COUNTER >> 8, 0xD0, rel(s + 14, 0xE4))
    put(DEC, 0xDE, COUNTER & 0xFF, COUNTER >> 8, 0x30, 0x08,
        0x4C, (LOAD + TEST) & 0xFF, (LOAD + TEST) >> 8)
    target = DEC + 5 if bypass_into_test else CLOCK + 8
    put(CLOCK, 0xAD, 0x20, 0x13, 0xCD, 0x21, 0x13,
        0xD0, rel(CLOCK + 6, target))
    if not bypass_into_test:
        put(CLOCK + 8, 0x4C, (LOAD + out) & 0xFF, (LOAD + out) >> 8)
    return SidFile(path="synthetic", data=bytes(data), name="", author="",
                   released="", load_addr=LOAD, subtunes=1)


def test_zp_spelling_is_a_gate_hold_player():
    p = _player(bypass_into_test=False)
    assert search_file(p.data, GATE_HOLD_SHAPE) == -1
    assert search_file(p.data, GATE_HOLD_ZP_SHAPE) > -1
    assert find_gate_hold(p) is True


def test_zp_spelling_keeps_the_bypass_check():
    """Saboteur_II's case in the new spelling: the clock's bypass lands on
    the JMP into the test, so a zero-`wait` note is gated off and no tie."""
    assert find_gate_hold(_player(bypass_into_test=True)) is False


def test_zp_spelling_needs_both_guards_to_skip_to_one_place():
    assert find_gate_hold(_player(bypass_into_test=False,
                                  split_target=True)) is False


def test_zp_spelling_is_not_read_where_the_primary_shape_matches():
    """A fallback: a primary match its own guards reject still decides."""
    assert find_gate_hold(_player(bypass_into_test=False,
                                  stray_primary=True)) is False


def test_zp_spelling_is_not_read_where_the_lsr_shape_matches():
    assert find_gate_hold(_player(bypass_into_test=False,
                                  stray_lsr=True)) is False


@needs_corpus
def test_spellbound_is_a_gate_hold_player():
    assert find_gate_hold(load_sid(str(CORPUS / "Spellbound.sid"))) is True


@needs_corpus
def test_bangkok_knights_still_reads_the_primary_spelling():
    """It carries the zero-page spelling too; the primary match decides."""
    sid = load_sid(str(CORPUS / "Bangkok_Knights.sid"))
    assert search_file(sid.data, GATE_HOLD_SHAPE) > -1
    assert search_file(sid.data, GATE_HOLD_ZP_SHAPE) > -1
    assert find_gate_hold(sid) is True


# --- what Spellbound's conversion says at the drum/sweep sites ---------------

DRUM = 0x9B                                  # pattern $14's `81 0D 3B`
SWEEP = [0xA2, 0xA7, 0xAE, 0xB3, 0xBA, 0xBC]  # `00 42` .. `00 5F` (5F clamps)


def _song(**extra):
    import fidelity
    from h2g.convert import convert
    from songview import parse_sng
    presets = REPO_ROOT / "presets.json"
    if not presets.exists():
        pytest.skip("presets.json not available here")
    doc = json.loads(presets.read_text(encoding="utf-8"))
    opts = fidelity._preset_opts(doc, "Spellbound.sid")
    opts.update(extra)
    return parse_sng(convert(str(CORPUS / "Spellbound.sid"),
                             log=lambda m: None, **opts))


def _sites(song):
    """(pattern, rows of the six sweep notes) wherever the drum is followed,
    after its hold row, by the whole sweep."""
    out = []
    for pi, p in enumerate(song.patterns):
        rows = [p[i:i + 4] for i in range(0, len(p), 4)]
        for r in range(len(rows) - 7):
            if rows[r][0] == DRUM and rows[r + 1][0] == 0xBD and all(
                    rows[r + 2 + k][0] == n for k, n in enumerate(SWEEP)):
                out.append((pi, rows[r], rows[r + 2:r + 8]))
    return out


@needs_corpus
def test_the_sweep_re_gates_once_and_then_ties():
    """Under presets: the first sweep note attacks (the drum was wait 1 and
    its gate closed), the five after it are ties -- `CMD_TONEPORTA 00`."""
    song = _song()
    sites = _sites(song)
    assert sites, "no drum + sweep run found in Spellbound's patterns"
    for pi, drum, sweep in sites:
        assert drum[2] != CMD_TONEPORTA, (pi, drum)
        assert sweep[0][2] != CMD_TONEPORTA, (pi, sweep[0])
        for row in sweep[1:]:
            assert (row[2], row[3]) == (CMD_TONEPORTA, 0), (pi, row)


@needs_corpus
def test_under_tie_restart_the_sweep_holds_its_gate_on_a_legato_clone():
    """Spellbound is a `classic_tie_restart_family` player ("voice"), so
    under `tie_restart` (FIXED's value) each tie is a plain note on a clone
    whose gatetimer has bit 6 -- no gate-off -- and the re-gated first note
    and the drum keep instruments that DO gate off before the next note."""
    song = _song(tie_restart=True)
    sites = _sites(song)
    assert sites
    for pi, drum, sweep in sites:
        gt = lambda row: song.instruments[row[1] - 1].gatetimer
        assert drum[1] and not gt(drum) & 0x40, (pi, drum)
        assert sweep[0][1] and not gt(sweep[0]) & 0x40, (pi, sweep[0])
        for row in sweep[1:]:
            live = row[1] or sweep[1][1]
            assert song.instruments[live - 1].gatetimer & 0x40, (pi, row)
            assert row[2] != CMD_TONEPORTA, (pi, row)
    # The landing: some legato clone carries the `$0F0A` record (`0E:...`).
    assert any(i.name.startswith("0E:") and i.gatetimer & 0x40
               for i in song.instruments)
