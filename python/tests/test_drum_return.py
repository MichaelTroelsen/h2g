"""Whether a bit-$01 drum ends back on the note's pitch, and why it is per record.

The bit-$01 drum block does not restore anything -- Last V8 $8309 and Commando
$52FA are the same twenty-five instructions modulo relocation, and both only
ever `LDA freqhi,X / DEC freqhi,X / STA $D401,Y`. What brings the voice back is
the vibrato routine's last act, which rewrites the note's own frequency out of
the player's note table on every call and is skipped entirely when the record's
byte at that offset is zero.

So the question "does this drum return to base" is a question about a *record*,
and the file that proves it is Last V8: record 0 (gate byte $02) returns on all
141 of its notes while records 9 and 10 (gate byte $00), in the same file and
the same player, park on all 12 of theirs. A per-file flag cannot express that,
and Commando is why it matters -- its audible drum, record 12, has a zero gate
byte and must not be given a return.

Corpus measurement behind these numbers (siddump, -t60, each file's own start
subtune, records carrying bit $01 alone and whose envelope pair no other record
claims): 328 returning notes, every one under a true gate, and 1635 notes under
a false gate with zero returns.
"""
import pathlib

import pytest

from corpus import CORPUS, needs_corpus

from h2g.convert import _detect_tables
from h2g.detect import (NOTE_REASSERT_TAIL, NOTE_REASSERT_TAIL_LEN,
                        drum_returns_to_base)
from h2g.search import search_file
from h2g.sidfile import load_sid

COMMANDO = pathlib.Path(__file__).resolve().parents[2] / "Commando.sid"


def _det(path):
    return _detect_tables(load_sid(str(path)), lambda *a, **k: None)


# (file, record, expected) -- every one measured, see the module docstring.
MEASURED = [
    # returns: 141, 141 and 46 notes, no parked note between them
    ("Last_V8.sid", 0, True),
    ("Last_V8_C128_version.sid", 0, True),
    ("Rasputin.sid", 9, True),
    # the same players' other bit-$01 records, which park
    ("Last_V8.sid", 9, False),
    ("Last_V8.sid", 10, False),
    ("Rasputin.sid", 1, False),
    ("Rasputin.sid", 3, False),
    ("Rasputin.sid", 12, False),
    # the drum a listener validated: 10 parked and 4 flat, never a return
    ("Commando.sid", 12, False),
    # and the rest of the parking population, one record per file
    ("Action_Biker.sid", 3, False),
    ("Battle_of_Britain.sid", 12, False),
    ("Chimera.sid", 6, False),
    ("Crazy_Comets.sid", 6, False),
    ("Formula_1_Simulator.sid", 1, False),
    ("Game_Killer.sid", 10, False),
    ("Hunter_Patrol.sid", 6, False),
    ("Monty_on_the_Run.sid", 1, False),
    ("Proteus.sid", 12, False),
    ("Thing_on_a_Spring.sid", 8, False),
    ("Thrust.sid", 0, False),
    ("Warhawk.sid", 12, False),
    ("Zoids.sid", 12, False),
]


@needs_corpus
@pytest.mark.parametrize("name,rec,expected", MEASURED)
def test_gate_matches_the_measured_return(name, rec, expected):
    path = CORPUS / name
    if not path.exists():
        pytest.skip(f"{name} not in this corpus")
    sid, det = _det(path)
    assert drum_returns_to_base(sid, det, rec) is expected


@needs_corpus
def test_last_v8_splits_within_one_file():
    """The argument against a per-file flag, as an assertion.

    Same file, same player, same block: record 0 returns and records 9 and 10
    do not. Anything file-level is wrong here whichever way it points.
    """
    sid, det = _det(CORPUS / "Last_V8.sid")
    returning = [i for i in range(det.instr_used)
                 if drum_returns_to_base(sid, det, i)]
    assert 0 in returning
    assert 9 not in returning and 10 not in returning


@needs_corpus
def test_commando_and_last_v8_share_the_drum_block():
    """The premise the field exists to replace.

    A player-level flag would have to separate these two files, and it cannot:
    their drum blocks are byte-identical but for the address operands. So the
    difference is in the records, not the code.
    """
    a = load_sid(str(CORPUS / "Last_V8.sid"))
    b = load_sid(str(CORPUS / "Commando.sid"))
    shape = "AD ?? ?? 29 01 F0 ?? BD ?? ?? F0 ?? BD ?? ?? F0"
    ia, ib = search_file(a.data, shape), search_file(b.data, shape)
    assert ia >= 1 and ib >= 1
    block_a = a.data[ia:ia + 0x3C]
    block_b = b.data[ib:ib + 0x3C]
    assert block_a != block_b            # different addresses
    differing = [i for i in range(len(block_a)) if block_a[i] != block_b[i]]
    # Every difference is an address operand: an opcode byte is never one of
    # them, and each run of differences is the 2 bytes after a 3-byte opcode.
    assert differing == [1, 2, 8, 9, 13, 14, 18, 19, 26, 27, 29, 30,
                         34, 35, 37, 38, 43, 44, 50, 51]
    # ...and the block's own last instruction, `STA $D404,Y`, is identical in
    # both -- indices 57-59, which are not in the list above.
    assert block_a[57:60] == block_b[57:60] == b"\x99\x04\xD4"


@needs_corpus
def test_the_gate_never_fires_without_the_drum_bit():
    """Both halves are required -- the file's routine and the record's byte.

    The trap `det.effect_bit40` fell into: a detection flag about a player read
    as a fact about a record. Every corpus record the gate is true for carries
    bit $01 in its own effect byte.
    """
    checked = 0
    for path in sorted(CORPUS.glob("*.sid")):
        try:
            sid, det = _det(path)
        except Exception:                                      # noqa: BLE001
            continue
        if det.note_reassert_offset is None:
            continue
        for i in range(det.instr_used):
            if not drum_returns_to_base(sid, det, i):
                continue
            base = det.instr_start + i * det.instr_stride
            assert sid.data[base + 7] & 0x01
            assert sid.data[base + det.note_reassert_offset] != 0
            checked += 1
    assert checked >= 20, checked


@needs_corpus
def test_the_reassert_is_found_at_record_plus_five_or_not_at_all():
    """33 corpus files carry the gated store, and every one names +5.

    An under-read is the safe direction -- None means "the drum parks", which
    is what every unmatched file measures -- so the assertion is that a match
    is always +5, never that a particular file matches.
    """
    seen = 0
    for path in sorted(CORPUS.glob("*.sid")):
        try:
            sid, det = _det(path)
        except Exception:                                      # noqa: BLE001
            continue
        if det.note_reassert_offset is None:
            continue
        assert det.note_reassert_offset == 5, path.name
        seen += 1
    assert seen >= 30, seen


@needs_corpus
def test_the_gate_branch_clears_the_store_in_every_matching_file():
    """The check that makes the signature a claim rather than a coincidence.

    The store is what the tail anchors on; the gate only counts if its branch
    lands at or past the end of it. In all 33 matching files the target is the
    byte right after the last `STA $D401,Y` -- so a match is never marginal,
    and a shape that merely looked similar would be visible as a target that
    lands inside.
    """
    from h2g import detect as D
    for path in sorted(CORPUS.glob("*.sid")):
        try:
            sid, det = _det(path)
        except Exception:                                      # noqa: BLE001
            continue
        if det.note_reassert_offset is None:
            continue
        at = search_file(sid.data, NOTE_REASSERT_TAIL)
        end = at + NOTE_REASSERT_TAIL_LEN
        data = sid.data
        target = None
        for k in range(at - 1, max(0, at - D.NOTE_REASSERT_BACK), -1):
            if (data[k] == 0xB9 and data[k + 3] == 0x8D
                    and data[k + 6] == 0xF0):
                target = k + 8 + ((data[k + 7] ^ 0x80) - 0x80)
            elif (data[k] == 0xB9 and data[k + 3] == 0xD0
                  and data[k + 4] == 0x03 and data[k + 5] == 0x4C):
                target = sid.to_offset(data[k + 6] | data[k + 7] << 8)
            else:
                continue
            if target >= end:
                break
            target = None
        assert target == end, (path.name, target, end)


def test_the_fixture_still_converts_byte_for_byte():
    """Nothing consumes the field yet, so `Commando.sng` must not move.

    Bytes, not length: `len(convert(...)) == 15193` passes for any edit that
    moves a byte between two wavetable entries.
    """
    from h2g.convert import convert
    ref = (pathlib.Path(__file__).resolve().parents[2] / "Commando.sng")
    got = convert(str(COMMANDO))
    assert got == ref.read_bytes()
