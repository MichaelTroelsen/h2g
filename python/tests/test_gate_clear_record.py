"""A record whose waveform has the gate CLEAR closes the gate on its own fetch.

Chimera's voice 1 regates every 18 frames in the original (subtune 0, frames
5618-5888, 6194-6464, 8210-8354, 8498-8624: `$10`/`$BF05` on the sixth row of
each group, `$11`/`$BF00` three frames later) where the conversion spelt its
wait-0 arpeggio chains as 40-row ties. The tie decoder was right that the
player never closes the gate at those notes' ENDS (`gate_hold`); it missed
that the classic fetch writes the record's waveform on every event
(`$C315 LDA $C664,X / AND $C640 / STA $D404,Y`), and record 8's is `$10`.

Three readings make the regate audible, each pinned here:

* `patterns.record_gate_clear` + `_build_raw_pattern(gate_clear_records=)`:
  such an event is not a tie target, and the note after it attacks;
* `wavetable._wavetable_entries`: a record whose typical note is one row
  never runs the drum (its `LDA duration,X / BEQ` guard), so the attack holds
  its waveform instead of sounding noise and closing the gate on frame 4;
* `instruments._write_instruments(gate_clear_firstwave=)`: the record's own
  waveform as firstwave (no `$09` gate edge) and the legato bit (no early
  gate-off; the fetch is where the original shuts it).
"""
import pathlib
import sys

import pytest

from corpus import CORPUS, needs_corpus

PYTHON_ROOT = pathlib.Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PYTHON_ROOT))

import fidelity                                              # noqa: E402
from h2g.detect import detect                                # noqa: E402
from h2g.goatwriter.constants import GATETIMER_LEGATO        # noqa: E402
from h2g.patterns import (CMD_TONEPORTA, _build_raw_pattern,  # noqa: E402
                          record_gate_clear)
from h2g.sidfile import load_sid                             # noqa: E402

needs_siddump = pytest.mark.skipif(
    not pathlib.Path(fidelity.SIDDUMP).exists(),
    reason="no siddump on this machine (tools/siddump-rt, see its README)")
needs_gt2reloc = pytest.mark.skipif(
    not pathlib.Path(fidelity.GT2RELOC).exists(),
    reason="no gt2reloc on this machine")

# Four wait-0 events (status $80, instrument operand, note) and the
# terminator: record 0, record 0, record 1, record 0.
CHAIN = bytes([0, 0,
               0x80, 0x00, 0x30,
               0x80, 0x00, 0x32,
               0x80, 0x01, 0x34,
               0x80, 0x00, 0x30,
               0xFF])

# The regate ranges of the run record, original frames, subtune 0, voice 1.
RANGES = ((5618, 5888), (6194, 6464), (8210, 8354), (8498, 8624))


def _rows(events):
    return [events[k:k + 4] for k in range(0, len(events) - 4, 4)]


def test_a_gate_clear_record_is_not_a_tie_target_and_ends_the_chain():
    plain = _rows(_build_raw_pattern(CHAIN, 2, tie=True, gate_hold=True))
    assert [r[2] for r in plain] == [0, CMD_TONEPORTA, CMD_TONEPORTA,
                                     CMD_TONEPORTA]
    split = _rows(_build_raw_pattern(CHAIN, 2, tie=True, gate_hold=True,
                                     gate_clear_records=frozenset({1})))
    # Row 2 (record 1) restarts its instrument; row 3 attacks.
    assert [r[2] for r in split] == [0, CMD_TONEPORTA, 0, 0]
    # Notes and instruments are untouched -- only the tie moved.
    assert [r[:2] for r in split] == [r[:2] for r in plain]


def test_a_record_the_pattern_has_not_named_keeps_the_tie():
    # Record 1 closes the gate, but an event only knows its record once the
    # pattern names one: the carried-in instrument is not read here.
    chain = bytes([0, 0, 0x00, 0x30, 0x00, 0x32, 0xFF])
    rows = _rows(_build_raw_pattern(chain, 2, tie=True, gate_hold=True,
                                    gate_clear_records=frozenset({0, 1})))
    assert [r[2] for r in rows] == [0, CMD_TONEPORTA]


def test_the_rule_needs_tie_to_do_anything():
    a = _build_raw_pattern(CHAIN, 2)
    b = _build_raw_pattern(CHAIN, 2, gate_clear_records=frozenset({1}))
    assert a == b


@needs_corpus
def test_record_gate_clear_reads_chimeras_record_8_and_skips_legato_players():
    sid = load_sid(str(CORPUS / "Chimera.sid"))
    det = detect(sid, lambda *a, **k: None)
    got = record_gate_clear(sid, det)
    assert 8 in got and 7 not in got
    assert sid.data[det.instr_start + 8 * det.instr_stride + 2] == 0x10
    # A legato-marker player has no unconditional fetch write to rest on.
    sid = load_sid(str(CORPUS / "Auf_Wiedersehen_Monty.sid"))
    det = detect(sid, lambda *a, **k: None)
    assert det.note_flag
    assert record_gate_clear(sid, det) == frozenset()


def _converted(name):
    import json
    import h2g.convert as C
    doc = json.loads((PYTHON_ROOT.parent / "presets.json").read_text())
    opts = fidelity._preset_opts(doc, f"{name}.sid")
    return C.convert(str(CORPUS / f"{name}.sid"), log=lambda m: None, **opts)


def _wavetable_of(song, ins):
    wt = song.tables["WTBL"]
    out, k = [], ins.wave_ptr - 1
    while k < len(wt):
        out.append(tuple(wt[k]))
        if wt[k][0] == 0xFF:
            break
        k += 1
    return out


@needs_corpus
def test_chimeras_conversion_carries_all_three_readings():
    import songview
    song = songview.parse_sng(_converted("Chimera"))
    by_adsr = {}
    for ins in song.instruments:
        by_adsr.setdefault((ins.ad << 8) | ins.sr, []).append(ins)
    # Record 7 ($BF00, effect $05 = drum + arpeggio): one-row notes, so no
    # noise tick and no gate-off in its wavetable.
    for ins in by_adsr[0xBF00]:
        lefts = [l for l, _r in _wavetable_of(song, ins)[:-1]]
        assert not any(l & 0x80 for l in lefts if l >= 0x10), lefts
        assert all(l & 0x01 for l in lefts if 0x10 <= l < 0xE0), lefts
    # Record 8 ($BF05, waveform $10): its own waveform as firstwave, legato.
    clear = by_adsr[0xBF05]
    assert clear
    for ins in clear:
        assert ins.firstwave == 0x10, ins
        assert ins.gatetimer & GATETIMER_LEGATO, ins
    # Every row naming record 8 restarts its instrument -- none is a tie.
    numbers = {ins.number for ins in clear}
    named = 0
    for pat in song.patterns:
        for k in range(0, len(pat), 4):
            if pat[k + 1] in numbers and pat[k] < 0xBD:
                named += 1
                assert pat[k + 2] != CMD_TONEPORTA, (k // 4, pat[k:k + 4])
    assert named


@needs_corpus
def test_commandos_fixture_options_take_none_of_it():
    # The byte-exact fixture is converted with effects off, where firstwave
    # stays $09 and no gatetimer gains $40 (tests/test_commando.py holds the
    # bytes themselves).
    import songview
    import h2g.convert as C
    song = songview.parse_sng(C.convert(
        str(pathlib.Path(__file__).resolve().parents[2] / "Commando.sid"),
        log=lambda m: None))
    assert all(i.firstwave == 0x09 for i in song.instruments[1:])
    assert not any(i.gatetimer & GATETIMER_LEGATO for i in song.instruments)


def _gate_on_edges(voice, n):
    wf = fidelity.register_timeline(voice.wf_events, n)
    return [f for f in range(1, n) if (wf[f] & 1) and not (wf[f - 1] & 1)]


def _gate_off_edges(voice, n):
    wf = fidelity.register_timeline(voice.wf_events, n)
    return [f for f in range(1, n) if not (wf[f] & 1) and (wf[f - 1] & 1)]


@needs_corpus
@needs_siddump
@needs_gt2reloc
def test_voice_1_regates_every_18_frames_as_the_original_does(tmp_path):
    """Re-measured, both sides through siddump: in each range the original's
    voice 1 makes N gate-on edges 18 frames apart, and so must the packed
    conversion, offset by one constant startup lag -- and its gate-OFF
    edges (the original's fall on the fetch of the `$10` row, 15 frames
    after each attack) must sit at that same lag: the duty, not just the
    cadence."""
    seconds, n = 180, 180 * 50
    orig = fidelity.run_siddump(CORPUS / "Chimera.sid", seconds, 0, calls=1)
    packed = fidelity.pack_sid(_converted("Chimera"), tmp_path)
    assert packed is not None and packed.exists()
    ours = fidelity.run_siddump(packed, seconds, 0, calls=1)
    lags = set()
    for edges in (_gate_on_edges, _gate_off_edges):
        o_all, u_all = edges(orig[1], n), edges(ours[1], n)
        for a, b in RANGES:
            # The window's own edges (each regate's gate-off precedes its
            # gate-on by 3 frames, so the off window starts that much early).
            lo = a - 3 if edges is _gate_off_edges else a
            o = [f for f in o_all if lo <= f <= b]
            assert len(o) >= 8, (edges.__name__, o)
            assert all(y - x == 18 for x, y in zip(o, o[1:])), o
            # Ours in the same window, allowing a startup lag of 0..8.
            u = [f for f in u_all if lo <= f <= b + 8]
            assert len(u) == len(o), (edges.__name__, a, b, o, u)
            assert all(y - x == 18 for x, y in zip(u, u[1:])), u
            lags |= {y - x for x, y in zip(o, u)}
    assert len(lags) == 1 and 0 <= lags.pop() <= 8, lags
