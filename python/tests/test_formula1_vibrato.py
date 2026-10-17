"""Formula_1_Simulator's lead vibrato (task formula-1-lead-vibrato).

User report 2026-10-17: "the lead is a bit off and flat". Measured at
v0.5.583 (60 s, subtune 0, original at -m1, ours under presets packed and
traced at -S2/-m2; C:/t/f1-vibrato, census.py): the lead (voice 1, record
5, vibrato byte $2B = bound 5, shift 3) swung 0.63x the original's depth at
0.80x its period over 28 vibrato notes. The cause is read off the player:

    CB60  LDA $F7 / BNE $CB67 / JMP $C006      play: dispatch on the subtune
    CB40  STA $F7 / BNE $CB47 / JMP $C000      init stores A (the subtune)
    C006  DEC $C4EB / BPL $C011 / LDA #$04 / STA $C4EB / RTS   outer gate
    C1D6  LDA $C4FE,X / BPL ... INC/DEC $C4E0,X                counter update

so subtune 0 runs the update on four calls in five, and the entry needs the
gate's 5/4 stretch (`_classic_vibrato_entry` `gate_skip`). `entry_gate`
stopped at the dispatch; `entry_gate(dispatch=True)`, which `build_sng`
asks for the vibrato, follows it (`call_phase.subtune_zero_entry`). After
it: depth 1.05x, period 1.00x (same census); fidelity -t 180 depth 0.661 ->
0.870, bend 0.642 -> 0.734, travel 0.911 -> 0.929, reversal 1.021 -> 1.002.

The original's first excursion goes up or down by the note -- its counter
$C4E0,X is free-running -- while Goattracker's always goes up from the note
(gplay.c:795-799), so the direction is pinned on our side only.

Also here: the onset option (`vibrato_onset`, off by default -- a trade, see
docs/OPTIONS.md) and the LFO table's span (Hollywood_or_Bust).
"""
import inspect
import json
import pathlib
import sys

import pytest

PYTHON_ROOT = pathlib.Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PYTHON_ROOT))

import fidelity                                              # noqa: E402
import songview                                              # noqa: E402
from corpus import CORPUS, needs_corpus                      # noqa: E402
from h2g.convert import convert                              # noqa: E402
from h2g.detect import detect                                # noqa: E402
from h2g.goatwriter import call_phase                        # noqa: E402
from h2g.goatwriter.vibrato import (_classic_vibrato_entry,  # noqa: E402
                                    _repitch_after,
                                    _table_vibrato_entry)
from h2g.sidfile import load_sid                             # noqa: E402

F1 = CORPUS / "Formula_1_Simulator.sid"
HOLLYWOOD = CORPUS / "Hollywood_or_Bust.sid"
COMMANDO = PYTHON_ROOT.parent / "Commando.sid"
PRESETS = json.loads((PYTHON_ROOT.parent / "presets.json").read_text())
LEAD_ADSR = "$2C80"          # record 5's $2C8F, release nibble taken off


def _song(path, **over):
    opts = fidelity._preset_opts(PRESETS, path.name)
    sig = inspect.signature(convert).parameters
    kw = {k: v for k, v in opts.items() if k in sig}
    kw.update(over)
    return songview.parse_sng(convert(str(path), log=lambda m: None, **kw))


def _vibrato_records(song):
    return {i.number: i for i in song.instruments if i.vib_ptr}


def _gt_walk(cmp_value, speed, calls):
    """gplay.c:795-801: the offset after each call the vibrato runs on."""
    vibtime, freq, seen = 0, 0, []
    for _ in range(calls):
        if vibtime < 0x80 and vibtime > cmp_value:
            vibtime ^= 0xFF
        vibtime = (vibtime + 2) & 0xFF
        freq += -speed if vibtime & 1 else speed
        seen.append(freq)
    return seen


@needs_corpus
def test_the_dispatch_reaches_formula_1s_gate_and_no_other_files():
    sid = load_sid(str(F1))
    assert not call_phase.entry_gate(sid)
    assert call_phase.entry_gate(sid, dispatch=True)
    assert sid.to_address(call_phase.subtune_zero_entry(sid)) == 0xC006
    gained = [p.name for p in sorted(CORPUS.glob("*.sid"))
              if call_phase.entry_gate(load_sid(str(p)), dispatch=True)
              != call_phase.entry_gate(load_sid(str(p)))]
    assert gained == [F1.name]


def test_the_lead_entry_period_depth_and_direction():
    """bound 5 at -S2 stretched by 5/4: a half-period of 12.5 calls, the
    player's 6.25 frames. Unstretched it was 10 calls -- 20% fast. The swing
    `(cmp + 2) * (I >> rshift)` over the player's `bound * (I >> shift)`."""
    stretched = _classic_vibrato_entry(0x2B, 2, 0, gate_skip=4)
    plain = _classic_vibrato_entry(0x2B, 2, 0)
    assert stretched == (0x8A, 4) and plain == (0x88, 4)
    for entry, half_calls in ((stretched, 12), (plain, 10)):
        assert (entry[0] & 0x7F) + 2 == half_calls
    walk = _gt_walk(0x0A, 1 << 12 >> 4, 48)
    span = (max(walk) - min(walk)) / (1 << 12)
    assert span == pytest.approx(12 / 16)          # player: 5/8 = 10/16
    assert walk[0] > 0, "Goattracker's first excursion is up"


@needs_corpus
def test_formula_1_under_presets_takes_the_stretched_entry():
    """Under presets the shortest row also takes the tick-0 call off:
    `($88, 4)` where the unstretched entry was `($86, 4)`."""
    song = _song(F1)
    (lead,) = [i for i in _vibrato_records(song).values()
               if i.adsr == LEAD_ADSR]
    assert song.tables["STBL"][lead.vib_ptr - 1] == (0x88, 4)


@needs_corpus
def test_vibrato_onset_frees_the_plain_program_and_starts_on_frame_1():
    off = _vibrato_records(_song(F1, vibrato_onset=False))
    on_song = _song(F1, vibrato_onset=True)
    on = _vibrato_records(on_song)
    assert off.keys() == on.keys() and len(on) == 4
    for n, rec in on.items():
        assert off[n].vib_delay == 3 and rec.vib_delay == 2, n
        prog = on_song.tables["WTBL"][rec.wave_ptr - 1:rec.wave_ptr + 3]
        assert prog == [(0x41, 0x00), (0x41, 0x80), (0x41, 0x80),
                        (0xFF, 0x00)], n


def test_vibrato_onset_off_leaves_commando_alone():
    assert (convert(str(COMMANDO), log=lambda m: None, vibrato_onset=True)
            == convert(str(COMMANDO), log=lambda m: None))


def test_a_later_repitch_keeps_the_record_out_of_the_onset():
    """Deep_Strike's waveform-changing program writes the frequency again on
    its fifth step; an oscillator started before it only blips."""
    prog = [(0x41, 0x00), (0x01, 0x80), (0x11, 0x00), (0x01, 0x80),
            (0x41, 0x00), (0xFF, 0x00)]
    assert _repitch_after(prog, 1, 2, 0x40)
    plain = [(0x41, 0x00), (0x41, 0x80), (0x41, 0x80), (0xFF, 0x00)]
    assert not _repitch_after(plain, 1, 2, 0x40)


@needs_corpus
def test_deep_strike_keeps_its_delay_under_the_onset():
    """Deep_Strike (duration gate 3, -S3): every vibrato record runs such a
    program, so `vibrato_onset` leaves its delays at the floor's 4."""
    path = CORPUS / "Deep_Strike.sid"
    off = _vibrato_records(_song(path, vibrato_onset=False))
    on = _vibrato_records(_song(path, vibrato_onset=True))
    assert off and {n: r.vib_delay for n, r in on.items()} == {
        n: r.vib_delay for n, r in off.items()} == {n: 4 for n in off}


@needs_corpus
def test_the_lfo_table_span_is_read_off_the_table():
    """Table 1 is `00 01 02 01 00 81`: -1..+2, three units, not 2 * peak.
    Byte $13 (table 1, count 3) at -S1 with 3-call rows: cmp 0, the ratio
    `2 * 16 / (3 * 3)` = 3.56 -> rshift 2, where `2 * peak` read 2.67 -> 1
    and swung 1.78x the original's peak-to-peak."""
    song = _song(HOLLYWOOD)
    by_byte = {int(i.name.split(":")[1].split("-")[0], 16):
               song.tables["STBL"][i.vib_ptr - 1]
               for i in _vibrato_records(song).values()}
    assert by_byte[0x13] == (0x80, 2)
    tv = detect(load_sid(str(HOLLYWOOD)), lambda m: None).table_vibrato
    assert tv.spans == (2, 3, 4, 5)
    assert _table_vibrato_entry(0x13, tv, 1, 3, table_span=True) == (0x80, 2)
    assert _table_vibrato_entry(0x13, tv, 1, 3) == (0x80, 1)
    # Symmetric tables are unchanged.
    for byte in (0x24, 0x23, 0x22):
        assert (_table_vibrato_entry(byte, tv, 1, 3, table_span=True)
                == _table_vibrato_entry(byte, tv, 1, 3))
