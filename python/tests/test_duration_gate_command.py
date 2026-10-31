"""`_duration_gate_pass`: the classic vibrato's DURATION gate as a per-event
`CMD_VIBRATO 00`, task classic-duration-gate-per-note-command.

The gate (`detect.VibratoGate` form "duration", 25 corpus files) is a
threshold on the current event's stored length -- `LDA status,X / AND #$1F /
CMP #gate / BCC out` -- which a `vibdelay` cannot say (it postpones the long
notes instead of silencing the short ones). An event occupies `wait + 1`
rows, so it is gated off when `rows <= gate`; the pass writes the damp
(`04 00`, a vibrato of speed 0) on every free row of such an event and leaves
the long ones to the instrument's own pointer.
"""
import json
import pathlib
import sys

import pytest

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[1]))

from corpus import CORPUS, needs_corpus  # noqa: E402
from h2g.detect import Detection, VibratoGate  # noqa: E402
from h2g.goatwriter import _duration_gate_pass  # noqa: E402
from h2g.goatwriter import note_passes  # noqa: E402

NOTE, REST, KEYOFF = 0x70, 0xBD, 0xBE
VIB = {0: (7, 8)}                     # record 0 -> slot 2 at lead=1


def _pattern(*rows):
    out = []
    for r in rows:
        out += list(r)
    return out


def _note(instr=0, cmd=0, data=0):
    return (NOTE, instr, cmd, data)


def _hold(cmd=0, data=0):
    return (REST, 0x00, cmd, data)


def _keyoff():
    return (KEYOFF, 0x00, 0x00, 0x00)


def _col(pat, k):
    return [pat[i + k] for i in range(0, len(pat), 4)]


def _det(form="duration", gate=3, **vg):
    return Detection(vibrato_offset=5,
                     vibrato_gate=VibratoGate(form, gate, gate or 0, 0xB51C,
                                              **vg))


def test_an_event_at_the_gate_is_damped_and_one_row_longer_is_not():
    # gate 3: `duration < 3` is gated off, so wait 2 (3 rows) is damped and
    # wait 3 (4 rows) keeps the instrument's vibrato.
    short = _pattern(_note(instr=2), _hold(), _hold())
    long_ = _pattern(_note(instr=2), _hold(), _hold(), _hold())
    pats = [short, long_]
    assert _duration_gate_pass(_det(), pats, VIB, lead=1) == 1
    assert _col(pats[0], 2) == [4, 4, 4] and _col(pats[0], 3) == [0, 0, 0]
    assert _col(pats[1], 2) == [0, 0, 0, 0]


def test_the_threshold_is_the_files_own_operand():
    pats = [_pattern(_note(instr=2), _hold(), _hold(), _hold())]
    _duration_gate_pass(_det(gate=4), pats, VIB, lead=1)
    assert _col(pats[0], 2) == [4, 4, 4, 4]
    pats = [_pattern(_note(instr=2), _hold(), _hold(), _hold())]
    _duration_gate_pass(_det(gate=2), pats, VIB, lead=1)
    assert _col(pats[0], 2) == [0, 0, 0, 0]


def test_a_rest_is_its_own_event():
    # A long note, then a rest too short for the gate: the oscillation the
    # note started is frozen by the rest (the player stores nothing), and a
    # rest long enough keeps it going.
    note = [_note(instr=2)] + [_hold()] * 4
    short_rest = _pattern(*note, _keyoff(), _hold())
    long_rest = _pattern(*note, _keyoff(), _hold(), _hold(), _hold())
    pats = [short_rest, long_rest]
    _duration_gate_pass(_det(), pats, VIB, lead=1)
    assert _col(pats[0], 2) == [0] * 5 + [4, 4]
    assert _col(pats[1], 2) == [0] * 9


def test_a_column_in_use_keeps_its_row_and_the_rest_of_the_event_is_damped():
    from h2g.goatwriter import CMD_TONEPORTA
    pats = [_pattern(_note(instr=2, cmd=CMD_TONEPORTA), _hold(), _hold())]
    lines: list = []
    _duration_gate_pass(_det(), pats, VIB, lead=1, log=lines.append)
    assert _col(pats[0], 2) == [CMD_TONEPORTA, 4, 4]
    assert "1 event(s)" in lines[0]
    # an event with no free row at all is counted, not forced
    pats = [_pattern(_note(instr=2, cmd=CMD_TONEPORTA))]
    lines = []
    assert _duration_gate_pass(_det(), pats, VIB, lead=1, log=lines.append) == 0
    assert _col(pats[0], 2) == [CMD_TONEPORTA] and "1 with the column" in lines[0]


def test_only_an_instrument_with_a_vibrato_record_is_damped():
    plain = [_pattern(_note(instr=4), _hold())]
    _duration_gate_pass(_det(), plain, VIB, lead=1)
    assert _col(plain[0], 2) == [0, 0]
    unnamed = [_pattern(_note(), _hold())]
    lines: list = []
    _duration_gate_pass(_det(), unnamed, VIB, lead=1, log=lines.append)
    assert _col(unnamed[0], 2) == [0, 0] and "not resolved" in lines[0]


def test_the_instrument_carried_across_the_orderlist_is_the_live_one():
    pats = [_pattern(_note(instr=2), _hold(), _hold(), _hold(), _hold()),
            _pattern(_note(), _hold())]          # names none, entered on 2
    _duration_gate_pass(_det(), pats, VIB, lead=1, tracks=[[0, 1]])
    assert _col(pats[1], 2) == [4, 4]


def test_a_gate_that_is_not_a_duration_is_left_to_the_delay():
    pats = [_pattern(_note(instr=2), _hold())]
    assert _duration_gate_pass(_det(form="counter"), pats, VIB, lead=1) == 0
    assert _duration_gate_pass(Detection(vibrato_offset=5), pats, VIB,
                               lead=1) == 0
    assert _duration_gate_pass(_det(form="unread", gate=None), pats, VIB,
                               lead=1) == 0
    assert _col(pats[0], 2) == [0, 0]


def test_a_per_record_gate_is_read_by_record():
    # the player rewrites the operand per instrument (VIBRATO_GATE_STORE_SHAPE):
    # record 0 gates at 2, record 1 at 5, and a record past the table not at all.
    det = _det(gate=None, table=0x1000, per_record=(2, 5))
    vib = {0: (7, 8), 1: (8, 8), 2: (9, 8)}
    pats = [_pattern(_note(instr=2), _hold(), _hold()),        # record 0, 3 rows
            _pattern(_note(instr=3), _hold(), _hold()),        # record 1, 3 rows
            _pattern(_note(instr=4), _hold())]                 # record 2: unknown
    _duration_gate_pass(det, pats, vib, lead=1)
    assert _col(pats[0], 2) == [0, 0, 0]
    assert _col(pats[1], 2) == [4, 4, 4]
    assert _col(pats[2], 2) == [0, 0]


def test_a_pattern_that_would_not_pack_is_left_alone(monkeypatch):
    monkeypatch.setattr(note_passes, "PACKED_PATTERN_LIMIT", 0)
    pats = [_pattern(_note(instr=2), _hold())]
    lines: list = []
    assert _duration_gate_pass(_det(), pats, VIB, lead=1, log=lines.append) == 0
    assert _col(pats[0], 2) == [0, 0] and "over the packed" in lines[0]


def test_a_changed_pattern_is_a_copy_not_an_edit_in_place():
    original = _pattern(_note(instr=2), _hold())
    pats = [original]
    _duration_gate_pass(_det(), pats, VIB, lead=1)
    assert _col(original, 2) == [0, 0] and pats[0] is not original


# --- the corpus --------------------------------------------------------------

ROOT = pathlib.Path(__file__).resolve().parents[2]


def _convert(name):
    import fidelity
    from h2g.convert import convert
    doc = json.loads((ROOT / "presets.json").read_text())
    opts = fidelity._preset_opts(doc, name + ".sid")
    lines: list = []
    blob = convert(str(CORPUS / (name + ".sid")), lines.append, **opts)
    return blob, lines


@needs_corpus
@pytest.mark.parametrize("name,damped", [("Deep_Strike", 130),
                                         ("Sanxion", 68),
                                         ("Tarzan", 48)])
def test_the_corpus_gate_damps_the_short_events_and_logs_them(name, damped):
    blob, lines = _convert(name)
    line = next(l for l in lines if l.startswith("Duration gate"))
    assert f": {damped} event(s) shorter" in line


@needs_corpus
def test_a_file_whose_gate_is_not_a_duration_gets_no_pass():
    # Commando's triangle gate has its own pass; Food_Feud's is a counter.
    for name in ("Commando", "Food_Feud"):
        _blob, lines = _convert(name)
        assert not any(l.startswith("Duration gate") for l in lines), name


@needs_corpus
def test_every_damped_row_of_deep_strike_sits_on_a_short_event_of_a_vibrato_record():
    """Read the finished file: every `04 00` row is on an event of at most
    the gate's rows, and no event longer than the gate carries one."""
    from songview import parse_sng
    blob, _lines = _convert("Deep_Strike")
    song = parse_sng(blob)
    gate = 3
    vib_slots = {i.number for i in song.instruments if i.vib_ptr}
    damp = long_damp = 0
    for pat in song.patterns:
        live = 0
        i = 0
        while i + 3 < len(pat):
            if pat[i + 1]:
                live = pat[i + 1]
            if not (0x60 <= pat[i] <= 0xBC or pat[i] == KEYOFF):
                i += 4
                continue
            end = i + 4
            while end + 3 < len(pat) and pat[end] == REST and pat[end + 1] == 0:
                end += 4
            rows = (end - i) // 4
            damped = [pat[r + 2] == 4 and pat[r + 3] == 0
                      for r in range(i, end, 4)]
            if rows > gate:
                long_damp += sum(damped)
            elif any(damped):
                damp += 1
                # live 0: named by an earlier pattern (the pass walks the orderlists)
                assert live == 0 or live in vib_slots
            i = end
    assert damp > 100 and long_damp == 0
