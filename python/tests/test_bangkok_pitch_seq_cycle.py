"""Bangkok_Knights' in-note pitch cycle is effect bit $10, not an octave arpeggio.

The original's voice 0 plays `295e 3426 295e 52bc 3426 ...` inside one note: the
note, the note +4 semitones, the note +12 (`$89EC` = `00 04 0C`). That is the
player's bit-$10 pitch sequence (`$8415`: `AND #$10`, the per-record index at
`$8B3A + 8*record`, the pair table `$89FF`, the global phase `$89C8` counting
2, 1, 0), which `detect._find_pitch_seq` reads and the `pitch_seq` option
emits. It is NOT `--arpeggio`, which is inert on this file because bit $04 is a
two-stage waveform here, not a nibble arpeggio (todo.md, 2026-11-13, named the
wrong option).

What is pinned: the three tables are read from the file's own bytes, the six
records that set bit $10 carry the pairs the player holds, and the emitter turns
each into a relative-note cycle. A reader that returns None for this file (the
failure that leaves `pitch_seq` inert and the cycle flat) fails the first
test.
"""
import pytest

from corpus import CORPUS, needs_corpus
from h2g.convert import _detect_tables
from h2g.goatwriter.notes import (_pitch_seq_entries, _pitch_seq_note_byte,
                                  _pitch_seq_notes)
from h2g.sidfile import load_sid

# record -> (index byte, pair) as the player reads them at $8B3A + 8*record and
# $89FF + 2*index (disassembly of $8415, read 2026-11-14 at v0.5.668).
RECORDS = {2: (0, (4, 12)), 3: (0, (4, 12)), 7: (1, (251, 248)),
           10: (3, (5, 8)), 14: (4, (5, 0)), 15: (5, (0, 250))}


def _bangkok():
    return _detect_tables(load_sid(str(CORPUS / "Bangkok_Knights.sid")),
                          lambda *a: None)


@needs_corpus
def test_bangkok_pitch_sequence_is_read_from_the_player_bytes():
    sid, det = _bangkok()
    seq = det.pitch_seq
    assert seq is not None, "bit $10's block at $8415 must be recognised"
    assert (seq.steps, seq.frames_per_step) == (3, 1)
    assert [sid.to_address(x) for x in (seq.index, seq.pairs, seq.base)] \
        == [0x8B3A, 0x89FF, 0x89EC]
    assert list(sid.data[seq.base:seq.base + 3]) == [0, 4, 12]
    for rec, (idx, pair) in RECORDS.items():
        assert sid.data[seq.index + 8 * rec] == idx
        assert (sid.data[seq.pairs + 2 * idx],
                sid.data[seq.pairs + 2 * idx + 1]) == pair
        assert sid.data[det.instr_start + 8 * rec + 7] & 0x10, rec


@needs_corpus
def test_bangkok_records_emit_the_cycle_as_relative_notes():
    sid, det = _bangkok()
    for rec, (_idx, (a, b)) in RECORDS.items():
        # steps >= $80 are signed (record 7's -5/-8), written as relative notes
        want = sorted([0, _pitch_seq_note_byte(a), _pitch_seq_note_byte(b)])
        assert sorted(_pitch_seq_notes(sid, det, rec)) == want, rec
        entries = _pitch_seq_entries(sid, det, rec, 0x41)
        assert entries is not None, rec
        left, right = entries
        # three entries holding the record's waveform, opening on the note
        assert left == [0x41] * 3 and right[0] == 0, rec
        assert sorted(right) == want, rec
    # a record without bit $10 emits nothing (record 0 is a fixed-pitch drum)
    assert _pitch_seq_entries(sid, det, 0, 0x41) is None
