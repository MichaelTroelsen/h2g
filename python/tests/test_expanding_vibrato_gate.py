"""The expanding vibrato's swell starts on the record's own gate.

The classic swell routine computes its age-grown step every frame and then
skips the frequency store while the note's age is below a gate the player
loads per instrument (Mega_Apocalypse `LDA $54A8,Y / STA $4CB1` into
`CMP #$13` at $4CB0). `_expanding_vibrato_pass` writes `4xy` on hold rows,
and a commanded vibrato runs from its row's first call whatever `vibdelay`
says -- so before it read the gate, Mega_Apocalypse records 3 and 10 (gates
6 and 12, 3-frame rows) swung from frame 3 against the original's 6 and 12.
"""
import json
import pathlib
import sys

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[1]))

from corpus import CORPUS, needs_corpus  # noqa: E402
from h2g.detect import Detection, VibratoGate  # noqa: E402
from h2g.goatwriter.constants import (CMD_VIBRATO, GT_FIRST_NOTE,  # noqa: E402
                                      GT_LAST_NOTE, GT_REST)
from h2g.goatwriter.note_passes import (_expanding_vibrato_gate,  # noqa: E402
                                        _expanding_vibrato_pass)
from h2g.goatwriter.primitives import _note_freq  # noqa: E402
from h2g.sidfile import FreqTable  # noqa: E402

PYTHON_ROOT = pathlib.Path(__file__).resolve().parents[1]

END = 0xFF                      # patterns.GT_END_PATTERN


def test_only_a_counter_gate_is_read_and_per_record():
    stored = VibratoGate("counter", None, 0x13, 0xBC, table=0x54A8,
                         per_record=(240, 253, 253, 6, 240, 240, 253, 240,
                                     240, 19, 12, 253, 0))
    det = Detection(vibrato_gate=stored)
    assert [_expanding_vibrato_gate(det, r) for r in (3, 9, 10, 12)] \
        == [6, 19, 12, 0]
    # A record past the table is unknown, and unknown imposes nothing.
    assert _expanding_vibrato_gate(det, 99) == 0
    # One static counter gate holds for every record.
    assert _expanding_vibrato_gate(
        Detection(vibrato_gate=VibratoGate("counter", 9, 9, 0x9557)), 4) == 9
    # A duration is a threshold on the note's length, not a delay; an
    # UNREAD operand is not a number; no compare is no gate.
    assert _expanding_vibrato_gate(
        Detection(vibrato_gate=VibratoGate("duration", 8, 8, 0x14EF)), 0) == 0
    assert _expanding_vibrato_gate(
        Detection(vibrato_gate=VibratoGate("unread", None, 0xF0, 0x4B40)),
        0) == 0
    assert _expanding_vibrato_gate(Detection(), 0) == 0


class _AgeSid:
    """Goattracker's own note table at TABLE, one 8-byte record at 0 whose
    vibrato byte is `param` (bound 4, shift 3 by default)."""

    TABLE = 0x1000

    def __init__(self, param=0x23):
        data = bytearray([0x00, 0x00, 0x41, 0x00, 0x00, param, 0x00, 0x00])
        data += bytes(self.TABLE - len(data))
        for n in range(96):
            f = min(_note_freq(n), 0xFFFF)
            data += bytes([f & 0xFF, f >> 8])
        self.data = bytes(data)

    def to_offset(self, addr):
        return addr


def _rows(gate):
    """The command column of a B-6 held 40 rows, 3 frames a row."""
    sid = _AgeSid()
    det = Detection(instr_start=0, instr_stride=8, vibrato_offset=5,
                    freq_table=FreqTable(addr=_AgeSid.TABLE, start=0,
                                         length=96, shift=0, detune=0.0))
    if gate is not None:
        det.vibrato_gate = VibratoGate("counter", None, 0x13, 0xBC,
                                       table=0x2000, per_record=(gate,))
    pat = [0xB3, 1, 0, 0] + [GT_REST, 0, 0, 0] * 40 + [END, 0, 0, 0]
    _expanding_vibrato_pass(sid, det, [[0, 0xFF, 0]], [pat], {0: (1, 2)},
                            [(0x81, 3)], 0, 1, 3)
    return [(pat[i + 2], pat[i + 3]) for i in range(0, 41 * 4, 4)]


def test_no_row_starting_below_the_gate_is_commanded():
    free = _rows(None)
    first = next(k for k, c in enumerate(free) if c[0] == CMD_VIBRATO)
    # Non-vacuous: ungated, the swell is commanded from row `first`, and a
    # gate past that row's first age must take rows away.
    assert first * 3 < 15
    gated = _rows(15)
    assert all(c == (0, 0) for c in gated[:5]), gated[:5]     # ages 0..14
    # From the gate on, the rows are the ungated pass's own: the age term
    # does not depend on where the commands started.
    assert gated[5:] == free[5:]
    assert gated[5][0] == CMD_VIBRATO


def test_a_row_the_gate_falls_inside_is_left_to_vibdelay():
    """Gate 7 sits inside the row of ages 6..8. Commanding that row would
    start the swing at 6; leaving it lets the instrument's own `vibdelay`
    (`_classic_gate_refine`, already on the gate's frame) start it."""
    gated = _rows(16)
    assert gated[5] == (0, 0)                     # ages 15..17, gate 16
    assert gated[6][0] == CMD_VIBRATO
    # Gate 0 (read as 1 elsewhere) and gate 1 never reach past the note row.
    assert _rows(0) == _rows(None) == _rows(1)


def _mega_pass_rows():
    """Every (slot, row index k, frames a row, command) the pass left on the
    hold rows of Mega_Apocalypse under its preset, walked as the pass walks
    the orderlists."""
    import fidelity
    import h2g.goatwriter.build as B
    from h2g.convert import convert
    doc = json.loads((PYTHON_ROOT.parent / "presets.json").read_text())
    opts = fidelity._preset_opts(doc, "Mega_Apocalypse.sid")
    got = {}
    real = B._expanding_vibrato_pass

    def spy(sid, det, tracks, patterns, vib_ptrs, table, lead, multiplier,
            row_calls, instr_row_calls=None, log=None):
        n = real(sid, det, tracks, patterns, vib_ptrs, table, lead,
                 multiplier, row_calls, instr_row_calls=instr_row_calls,
                 log=log)
        got.update(det=det, tracks=[list(t) for t in tracks],
                   patterns=[list(p) for p in patterns], lead=lead,
                   mult=max(1, multiplier), row_calls=row_calls,
                   irc=dict(instr_row_calls or {}), written=n)
        return n

    B._expanding_vibrato_pass = spy
    try:
        convert(str(CORPUS / "Mega_Apocalypse.sid"), lambda m: None, **opts)
    finally:
        B._expanding_vibrato_pass = real
    assert got, "the expanding pass never ran on Mega_Apocalypse"
    out = []
    for track in got["tracks"]:
        live, k, repeat, operand = 0, None, 1, False
        for b in track:
            if operand:
                operand = False
                continue
            if b == 0xFF:
                operand = True
                continue
            if 0xE0 <= b < 0xFF:
                continue
            if 0xD0 <= b < 0xE0:
                repeat = b - 0xD0 + 1
                continue
            pat = got["patterns"][b]
            for _ in range(repeat):
                for r in range(0, len(pat) - 3, 4):
                    note, instr, cmd = pat[r], pat[r + 1], pat[r + 2]
                    if note == END:
                        break
                    if GT_FIRST_NOTE <= note <= GT_LAST_NOTE:
                        live = instr or live
                        k = 0
                        continue
                    if k is None or instr not in (0, live):
                        k = None
                        live = instr or live
                        continue
                    k += 1
                    frames = max(1, (got["irc"].get(live) or got["row_calls"])
                                 // got["mult"])
                    out.append((live, k, frames, cmd))
            repeat = 1
    return got, out


@needs_corpus
def test_mega_apocalypse_records_3_and_10_swell_from_their_gates():
    got, rows = _mega_pass_rows()
    det, lead = got["det"], got["lead"]
    assert got["written"] > 0
    for rec, gate in ((3, 6), (10, 12)):
        assert det.vibrato_gate.gate_for(rec) == gate, rec
        slot = rec + 1 + lead
        mine = [(k, f, c) for s, k, f, c in rows if s == slot]
        commanded = [(k, f) for k, f, c in mine if c == CMD_VIBRATO]
        assert commanded, (rec, "no commanded hold row: the check is vacuous")
        # No swell before the gate ...
        assert all(k * f >= gate for k, f in commanded), (rec, commanded[:8])
        # ... and it starts on the gate's own row: 3-frame rows put gate 6
        # on row 2 and gate 12 on row 4, the frames the original's
        # siddump moves on (6..8 and 12..13).
        assert min(k * f for k, f in commanded) == gate, rec
