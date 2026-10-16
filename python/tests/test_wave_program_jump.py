"""The `$86 n` jump of the `$1003` dialect's wave program, and the loop it makes.

Go_Go_Dash, Lakers_vs_Celtics, Lion_Heart, Pacific_Coast, Radio_ACE and
Sun_Never_Shines carry the byte-code wave program of 29 other files with one
more opcode: `$86 n` jumps to the n-th opcode and fetches again in the same
frame (`16A1-16B7`). The fetch tests `$86` before the `$85` hold, so
`WAVE_PROGRAM_FETCH` never matched and these records read as plain -- their
instruments `$04D5` / `$04F9` (Pacific_Coast, 3285 and 2210 reversals in the
original) emitted none. The program ends `80 15 80 20 80 10 86 04`: a noise
pitch walking `$15 $20 $10` for as long as the note is held.

Pinned at v0.5.566 against the corpus. Mutations that fail these:
  A. drop WAVE_PROGRAM_FETCH_LOOP from `_wave_program_fetch_site` -> the
     detection tests (six files read nothing).
  B. let `decode_wave_program` read `$86` as a set whatever `jump` says ->
     the 29-file semantics test.
  C. write the stop (`FF 00`) instead of the jump -> the loop test.
  D. jump to `start + len(starts)` (the entry AFTER the target) -> the target
     test.
"""
from corpus import CORPUS, needs_corpus  # noqa: E402

from h2g.convert import _detect_tables
from h2g.detect import (decode_wave_program, find_wave_program,
                        wave_program_has_jump, wave_program_set_stores_wave)
from h2g.sidfile import load_sid

JUMP_FILES = {"Go_Go_Dash.sid", "Lakers_vs_Celtics.sid", "Lion_Heart.sid",
              "Pacific_Coast.sid", "Radio_ACE.sid", "Sun_Never_Shines.sid"}


def _tables(name):
    return _detect_tables(load_sid(str(CORPUS / name)), lambda *a, **k: None)


# --- the decoder, on synthetic programs ------------------------------------

def test_a_jump_ends_the_program_and_carries_its_operand():
    prog = bytes([0x81, 0x20, 0x80, 0x15, 0x80, 0x20, 0x86, 0x01, 0x85])
    assert decode_wave_program(prog, 0, jump=True) == [
        ("set", 0x81, 0x20), ("set", 0x80, 0x15), ("set", 0x80, 0x20),
        ("jump", 0, 0x01)]


def test_without_the_flag_0x86_is_an_ordinary_waveform():
    """The 29 files whose fetch has no `$86` test write it to `$D404`."""
    prog = bytes([0x86, 0x01, 0x85])
    assert decode_wave_program(prog, 0) == [("set", 0x86, 0x01), ("hold", 0, 0)]


def test_a_jump_with_no_operand_is_cut_rather_than_read_past_the_end():
    assert decode_wave_program(bytes([0x80, 0x15, 0x86]), 0, jump=True) == [
        ("set", 0x80, 0x15)]


# --- detection --------------------------------------------------------------

@needs_corpus
def test_the_jump_dialect_reads_in_exactly_the_six_files():
    got = set()
    for path in sorted(CORPUS.glob("*.sid")):
        try:
            sid = load_sid(str(path))
        except Exception:                                  # noqa: BLE001
            continue
        at, gate = find_wave_program(sid)
        if at >= 0 and wave_program_has_jump(sid):
            got.add(path.name)
            assert gate == 0x01, path.name
    assert got == JUMP_FILES


@needs_corpus
def test_the_jump_dialect_stores_its_waveform_in_the_stored_cell():
    """`16C4 STA $D404,X / PHA ... PLA / STA $1A43,X` -- the `set` path keeps
    the byte, as the slide path does (`16DD`)."""
    sid, det = _tables("Pacific_Coast.sid")
    assert wave_program_set_stores_wave(sid, det) is True


@needs_corpus
def test_the_pointer_array_is_the_record_plus_8_the_bit_40_handler_reads():
    for name in JUMP_FILES:
        sid, det = _tables(name)
        assert det.wave_program == det.fixed_pitch_index >= 0, name
        assert det.wave_program_gate == 0x01, name


@needs_corpus
def test_pacific_coast_record_2_loops_over_three_noise_pitches():
    sid, det = _tables("Pacific_Coast.sid")
    off = det.wave_program + 2 * det.instr_stride
    at = sid.to_offset(sid.data[off] | (sid.data[off + 1] << 8))
    prog = decode_wave_program(sid.data, at, jump=True)
    assert prog[-1] == ("jump", 0, 4)
    assert [p[2] for p in prog[3:-1]] == [0x30, 0x15, 0x20, 0x10]


# --- emission ---------------------------------------------------------------

@needs_corpus
def test_a_looping_program_ends_in_a_jump_to_its_target_opcode():
    from h2g.goatwriter import _wavetable_entries
    sid, det = _tables("Pacific_Coast.sid")
    start = 11
    left, right = _wavetable_entries(sid, det, 2, True, "gts5", [], 1,
                                     start=start, budget=40,
                                     wave_program=True)
    assert left[-1] == 0xFF
    target = right[-1] - start               # 0-based entry the jump lands on
    assert 0 < target < len(left) - 1
    # ...which is the `80 15` opcode, the first of the three the loop walks.
    assert left[target] == 0x80
    body = right[target:-1]
    assert len(body) == 3 and len(set(body)) == 3, body
    # Oscillation: up, down, up -- a reversal on every pass of the loop.
    a, b, c = (x & 0x7F for x in body)
    assert b > a and c < b and a > c


@needs_corpus
def test_the_loop_is_declined_where_it_cannot_be_written():
    from h2g.goatwriter import _wave_program_entries
    sid, det = _tables("Pacific_Coast.sid")
    # No table position to jump to.
    assert _wave_program_entries(sid, det, 2, [], "gts5", 1, 40) is None
    # A block the budget cuts before its jump would be a different loop.
    assert _wave_program_entries(sid, det, 2, [], "gts5", 1, 6,
                                 start=11) is None
    assert _wave_program_entries(sid, det, 2, [], "gts5", 1, 40,
                                 start=11) is not None


@needs_corpus
def test_a_program_that_never_jumps_still_stops_with_the_restore():
    """Pacific_Coast record 1 (`$0979`) ends `85`: unchanged shape."""
    from h2g.goatwriter import _wavetable_entries
    sid, det = _tables("Pacific_Coast.sid")
    left, right = _wavetable_entries(sid, det, 1, True, "gts5", [], 1,
                                     start=11, budget=40, wave_program=True)
    assert (left[-1], right[-1]) == (0xFF, 0x00)
