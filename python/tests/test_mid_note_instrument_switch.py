"""A tied note that changes instrument must carry the new instrument's envelope.

Samantha Fox, subtune 9, voice 1: pattern `$04` at `$770F` ends

    $771E  21 3C     wait 1, status bit 5, note $3C   -- gate held open
    $7720  87 06 3C  wait 7, instrument 6, note $3C   -- same note, new instrument

and the player re-initialises the instrument on EVERY fetched note event
(`$70F8-$7127`: waveform under the gate mask, pulse, `$D405`, `$D406`), while
bit 5 only keeps the note-end gate-off from running (`$7154 AND #$20 / BNE`).
So the trace shows `$1A0F -> $0F9F` at frame 301 with `$D404` unchanged: no
attack, a new envelope. `patterns._build_raw_pattern` spells that as
`CMD_TONEPORTA 0` with the instrument in the column, and Goattracker never
loads AD/SR on that command (gplay.c:354, player.s:833-835), so the chip
held instrument 6's pair for the 380 gate-on frames the original spent on
instrument 7's -- 14 runs of 26-34 frames, all on voice 1 (runs.jsonl,
`samantha-fox-has-380-gate-on-frames...`, measured at 24b9f1d).

`goatwriter._tied_instrument_envelopes` writes the pair around the tie; this
file pins the decoded event, the spelling, and the corpus file it was read
from. Dropping the emission fails the second and third parts.
"""
import json
import pathlib
import sys

import pytest

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[1]))

from corpus import CORPUS, needs_corpus  # noqa: E402
from h2g import goatwriter  # noqa: E402
from h2g.convert import convert  # noqa: E402
from h2g.detect import detect  # noqa: E402
from h2g.goatwriter import (_entry_instruments,  # noqa: E402
                            _tied_instrument_envelopes, record_envelope)
from h2g.patterns import (CMD_SETAD, CMD_SETSR, CMD_TONEPORTA,  # noqa: E402
                          GT_END_PATTERN, GT_NO_NOTE, _build_raw_pattern)
from h2g.sidfile import load_sid  # noqa: E402
import songview  # noqa: E402

REPO = pathlib.Path(__file__).resolve().parents[2]
PRESETS = REPO / "presets.json"
SAMANTHA_FOX = CORPUS / "Samantha_Fox_Strip_Poker.sid"
# The two events above, at their file offset (load $7000, two-byte prefix).
TIE_OFFSET = 0x7E + 0x771E - 0x7000
TIE_BYTES = bytes.fromhex("21 3C 87 06 3C")

INSTR_BASE = 2  # _build_raw_pattern's default: player record N -> instrument N+2


def _quiet(*_a, **_k):
    return None


def _decode(pattern: list[int], **kw) -> list[list[int]]:
    data = bytes([0, 0]) + bytes(pattern)
    events = _build_raw_pattern(data, 2, tie=True, status_bit6=True, **kw)
    assert events is not None
    rows = [events[k:k + 4] for k in range(0, len(events), 4)]
    assert rows[-1][0] == GT_END_PATTERN
    return rows[:-1]


# --- the decoded event ------------------------------------------------------

def test_a_bit5_note_followed_by_an_instrument_change_on_the_same_note_is_a_tied_row():
    rows = _decode([0x81, 0x05, 0x3C,       # instrument 5, note $3C, wait 1
                    0x21, 0x3C,             # bit 5: gate held open at the end
                    0x87, 0x06, 0x3C,       # instrument 6, same note, wait 7
                    0xFF])
    note = 0x60 + 0x3C
    assert rows[0] == [note, 5 + INSTR_BASE, 0, 0]
    # The decoder repeats the current instrument on every note row.
    assert rows[2] == [note, 5 + INSTR_BASE, 0, 0]
    # The tie: same note, the NEW instrument in the column, TONEPORTA 0, and
    # every hold row after it free -- which is what the writer fills.
    assert rows[4] == [note, 6 + INSTR_BASE, CMD_TONEPORTA, 0]
    assert rows[5:12] == [[GT_NO_NOTE, 0, 0, 0]] * 7
    assert len(rows) == 12


# --- the spelling -----------------------------------------------------------

ENVELOPES = {5 + INSTR_BASE: (0x1A, 0x00), 6 + INSTR_BASE: (0x0F, 0x90)}


def test_the_same_pitch_tie_gets_sr_the_row_before_and_ad_the_row_after():
    rows = _decode([0x81, 0x05, 0x3C, 0x21, 0x3C, 0x87, 0x06, 0x3C, 0xFF])
    flat = [v for row in rows for v in row] + [GT_END_PATTERN, 0, 0, 0]
    out = _tied_instrument_envelopes([flat], ENVELOPES)[0]
    got = [out[k:k + 4] for k in range(0, len(out), 4)]
    note = 0x60 + 0x3C
    assert got[3] == [GT_NO_NOTE, 6 + INSTR_BASE, CMD_SETSR, 0x90]
    assert got[4] == [note, 6 + INSTR_BASE, CMD_TONEPORTA, 0]
    assert got[5] == [GT_NO_NOTE, 0, CMD_SETAD, 0x0F]
    # Nothing else moved.
    assert got[:3] == rows[:3] and got[6:] == rows[6:] + [[GT_END_PATTERN, 0, 0, 0]]


def test_a_different_pitch_tie_is_spelled_the_same_way():
    # The tie row is never touched, so the pitch does not matter.
    rows = _decode([0x81, 0x05, 0x3C, 0x21, 0x3C, 0x87, 0x06, 0x3E, 0xFF])
    flat = [v for row in rows for v in row] + [GT_END_PATTERN, 0, 0, 0]
    out = _tied_instrument_envelopes([flat], ENVELOPES)[0]
    got = [out[k:k + 4] for k in range(0, len(out), 4)]
    assert got[3] == [GT_NO_NOTE, 6 + INSTR_BASE, CMD_SETSR, 0x90]
    assert got[4] == [0x60 + 0x3E, 6 + INSTR_BASE, CMD_TONEPORTA, 0]
    assert got[5] == [GT_NO_NOTE, 0, CMD_SETAD, 0x0F]


def test_a_tie_with_no_row_before_it_takes_the_hold_rows_after_it():
    # The tied-from event has wait 0: no hold row to put the SR on.
    rows = _decode([0x81, 0x05, 0x3C, 0x20, 0x3C, 0x87, 0x06, 0x3C, 0xFF])
    flat = [v for row in rows for v in row] + [GT_END_PATTERN, 0, 0, 0]
    out = _tied_instrument_envelopes([flat], ENVELOPES)[0]
    got = [out[k:k + 4] for k in range(0, len(out), 4)]
    note = 0x60 + 0x3C
    assert got[2] == [note, 5 + INSTR_BASE, 0, 0]
    assert got[3] == [note, 6 + INSTR_BASE, CMD_TONEPORTA, 0]
    # The SR row re-latches the instrument: not a hold row.
    assert got[4] == [GT_NO_NOTE, 6 + INSTR_BASE, CMD_SETSR, 0x90]
    assert got[5] == [GT_NO_NOTE, 0, CMD_SETAD, 0x0F]


def test_a_tie_into_the_same_instrument_owes_nothing():
    rows = _decode([0x81, 0x05, 0x3C, 0x21, 0x3C, 0x87, 0x05, 0x3C, 0xFF])
    flat = [v for row in rows for v in row] + [GT_END_PATTERN, 0, 0, 0]
    assert _tied_instrument_envelopes([flat], ENVELOPES)[0] == flat


def test_a_row_zero_tie_is_settled_by_the_orderlist():
    # Pattern 1 opens on a tie into instrument 8 (row 0 -- what
    # _apply_boundary_ties produces); pattern 0 leaves the channel on
    # instrument 7.
    note = 0x60 + 0x3C
    p0 = [note, 7, 0, 0, GT_NO_NOTE, 0, 0, 0, GT_END_PATTERN, 0, 0, 0]
    p1 = [note, 8, CMD_TONEPORTA, 0, GT_NO_NOTE, 0, 0, 0,
          GT_NO_NOTE, 0, 0, 0, GT_END_PATTERN, 0, 0, 0]
    tracks = [[0, 1, 0xFF, 0]]
    assert _entry_instruments(tracks, [p0, p1]) == {0: {1}, 1: {7}}
    out = _tied_instrument_envelopes([p0, p1], ENVELOPES, tracks)
    # No row before the tie: the hold rows after it, SR re-latching first.
    assert out[1][0:4] == [note, 8, CMD_TONEPORTA, 0]
    assert out[1][4:8] == [GT_NO_NOTE, 8, CMD_SETSR, 0x90]
    assert out[1][8:12] == [GT_NO_NOTE, 0, CMD_SETAD, 0x0F]
    # Without the orderlist the held instrument is unknown and nothing is written.
    assert _tied_instrument_envelopes([p0, p1], ENVELOPES) == [p0, p1]
    # Two entries disagreeing on the instrument: unknown again.
    p2 = [note, 8, 0, 0, GT_END_PATTERN, 0, 0, 0]
    assert _tied_instrument_envelopes([p0, p1, p2], ENVELOPES,
                                      [[0, 1, 2, 1, 0xFF, 0]])[1] == p1


# --- the corpus file it was read from ----------------------------------------

@needs_corpus
@pytest.mark.skipif(not PRESETS.exists(), reason="presets.json absent")
def test_samantha_fox_voice_one_carries_instrument_sevens_envelope_on_the_tied_c5():
    sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[1]))
    import fidelity as F  # noqa: E402  (the harness's option resolution)

    sid = load_sid(str(SAMANTHA_FOX))
    assert sid.data[TIE_OFFSET:TIE_OFFSET + len(TIE_BYTES)] == TIE_BYTES
    det = detect(sid, _quiet)
    doc = json.loads(PRESETS.read_text(encoding="utf-8"))
    opts = F._preset_opts(doc, SAMANTHA_FOX.name)
    log: list = []
    song = songview.parse_sng(convert(str(SAMANTHA_FOX), log=log.append, **opts))

    # The writer's envelope for each instrument is the record's own.
    lead = 0 if opts["compact_instruments"] else 1
    for ins in song.instruments[lead:]:
        ad, sr = record_envelope(sid.data, det, ins.number - lead - 1,
                                 opts["sustain_exact"], opts["cut_release"])
        assert (ins.ad, ins.sr) == (ad, sr), ins
    seven = song.instruments[7 - 1]
    assert seven.number == 7 and (seven.ad, seven.sr) == (0x0F, 0x90)

    c5 = 0x60 + 0x3C
    spelled: list = []
    for pat in song.patterns:
        rows = [pat[k:k + 4] for k in range(0, len(pat), 4)]
        for i in range(len(rows) - 2):
            if (rows[i] == [GT_NO_NOTE, 7, CMD_SETSR, 0x90]
                    and rows[i + 1][1:] == [7, CMD_TONEPORTA, 0]
                    and 0x60 <= rows[i + 1][0] <= 0xBC
                    and rows[i + 2] == [GT_NO_NOTE, 0, CMD_SETAD, 0x0F]):
                spelled.append(rows[i + 1][0])
    # Pattern $04's C-5 (played three times through one deduplicated
    # pattern), $07's and $0A's ties on other notes, and $12/$15, which open
    # on a bit-5 note and tie on their second event: five rows, every one
    # with a free row before the tie.
    assert len(spelled) == 5 and c5 in spelled, spelled
    assert any(l.startswith("Tied instrument change..: 5 row(s)") for l in log), log
