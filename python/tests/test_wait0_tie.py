"""A tie survives a pattern boundary, because the player's gate does.

`_build_raw_pattern`'s `pending_tie` is a local and starts False at every
pattern; the player's state does not restart. Its note-end gate-off sits on
the *hold* path of the previous event and a `$FF` terminator is an orderlist
fetch, not an event -- so nothing between two patterns closes the gate, and a
pattern whose predecessor's last event carried status bit 5 (or, where
`gate_hold` reads it, a zero `wait`) is entered exactly as a tied note is
entered inside a pattern. Until this, the converter re-struck it.

Three halves are pinned here:

  * `_build_raw_pattern` reports that state through its `exits_tied`
    out-parameter, and reports it for the same two causes and under the same
    gates the intra-pattern tie uses (`tests/test_gate_hold.py` pins those);
  * `_apply_boundary_ties` writes the tie into row 0 of a **copy** of the
    successor, never in place -- 96 of the 180 corpus entries that are ever
    entered tied are also entered untied somewhere, so a shared pattern would
    silence attacks the player really makes;
  * `reindex_tracks` carries that state from the orderlist step that produces
    it to the one that consumes it, across a transpose byte, and does nothing
    at all when handed a plain list instead of a `TrackIndex`.

The file is named for the wait==0 tie because that is the cause this defect
was found behind: on Human_Race the boundary tie is *entirely* downstream of
it -- with `gate_hold` forced off the boundary pass changes not one byte of
that file. It is not downstream of it corpus-wide: 22 of the 30 files the
pass moves still move with the wait==0 clause disabled, on status bit 5
alone.

**A bit-6 rest exits untied whatever its bit 5 says**, which the wait==0 half
had excluded from the start and the bit-5 half had not. That asymmetry is what
put Battle of Britain, Devils Galop, Crazy Comets and Monty on the Run at
`retrig` 0.988/0.995/0.995/0.996 instead of 1.000 -- a handful of real attacks
tied away at a boundary whose predecessor ends on `$7F`. Warhawk was a fifth,
0.989 -> 0.996.
"""
import pathlib

import pytest

from corpus import CORPUS, needs_corpus
from h2g.convert import _detect_tables, convert
from h2g.patterns import (CMD_SETTEMPO, CMD_TONEPORTA, GT_KEYOFF, GT_NO_NOTE,
                          MAX_PATTERNS, TrackIndex, _apply_boundary_ties,
                          _apply_wrap_tie, _build_raw_pattern, apply_tempos,
                          decode_entry, reindex_tracks)
from h2g.sidfile import load_sid

REPO_ROOT = pathlib.Path(__file__).resolve().parents[2]

END = 0xFF          # ENDPATT status byte terminating a Hubbard pattern
NOTE = 0x64         # an arbitrary Goattracker note in range
ROW = 4


def _status(wait, *, get_next=False, no_note=False, no_adsr=False):
    b = wait & 0x1F
    if get_next:
        b |= 0x80
    if no_note:
        b |= 0x40
    if no_adsr:
        b |= 0x20
    return b


def _exit_state(pattern_bytes, **kw):
    ex: list = []
    data = bytes(64) + bytes(pattern_bytes)
    events = _build_raw_pattern(data, 64, exits_tied=ex, **kw)
    assert events is not None
    assert len(ex) == 1, f"expected exactly one report, got {ex}"
    return ex[0]


# One ordinary note, then the event whose status byte decides the exit state.
def _ending_on(status_byte, *, operand=True):
    p = [_status(1, get_next=True), 0x05, 0x20, status_byte]
    if operand:
        p += [0x05, 0x24]
    return p + [END]


# --- what _build_raw_pattern reports --------------------------------------

def test_bit5_last_event_exits_tied():
    p = _ending_on(_status(1, get_next=True, no_adsr=True))
    assert _exit_state(p, tie=True) is True


def test_plain_last_event_does_not_exit_tied():
    assert _exit_state(_ending_on(_status(1, get_next=True)), tie=True) is False


def test_zero_wait_last_event_exits_tied_only_with_gate_hold():
    p = _ending_on(_status(0, get_next=True))
    assert _exit_state(p, tie=True, gate_hold=True) is True
    assert _exit_state(p, tie=True, gate_hold=False) is False


def test_zero_wait_rest_does_not_exit_tied():
    """The rest branch closes the gate itself -- see test_gate_hold.py."""
    p = _ending_on(_status(0, no_note=True), operand=False)
    assert _exit_state(p, tie=True, gate_hold=True) is False


@pytest.mark.parametrize("wait", [0, 1, 31])
def test_a_rest_carrying_bit5_does_not_exit_tied(wait):
    """The rest branch's gate-off does not consult bit 5.

    `$7F` -- rest, bit 5, wait 31 -- is the byte four corpus players end a
    pattern on, and reading its bit 5 as "the gate stays open" tied the next
    pattern's opening note into a gate the rest had already shut. The player
    reloads a mask with `#$FF` on every fetch frame, the rest branch `DEC`s it
    to `$FE` and ANDs it into $D404 unconditionally (Battle of Britain
    $8065/$80C0/$80D9, Devils Galop $1399/$13FA/$1418), so the next note
    really does attack.
    """
    p = _ending_on(_status(wait, no_note=True, no_adsr=True), operand=False)
    assert _exit_state(p, tie=True, gate_hold=True) is False
    assert _exit_state(p, tie=True, gate_hold=False) is False


def test_a_rest_clears_a_tie_the_note_before_it_opened():
    """Not merely "a rest asserts nothing" -- the `AND` is unconditional, so a
    rest after a bit-5 note leaves the gate shut too."""
    p = [_status(1, get_next=True, no_adsr=True), 0x05, 0x20,
         _status(4, no_note=True, no_adsr=True), END]
    assert _exit_state(p, tie=True, gate_hold=True) is False


def test_tie_off_never_exits_tied():
    """`tie` is the option the whole mechanism hangs off, fixture included."""
    for sb in (_status(1, get_next=True, no_adsr=True), _status(0, get_next=True)):
        assert _exit_state(_ending_on(sb), tie=False, gate_hold=True) is False


def test_nothing_is_reported_when_the_decode_fails():
    ex: list = []
    assert _build_raw_pattern(bytes(16), 900, exits_tied=ex, tie=True) is None
    assert ex == []


def test_the_out_parameter_changes_no_byte():
    p = _ending_on(_status(1, get_next=True, no_adsr=True))
    data = bytes(64) + bytes(p)
    with_it = _build_raw_pattern(data, 64, tie=True, exits_tied=[])
    without = _build_raw_pattern(data, 64, tie=True)
    assert with_it == without


# --- what _apply_boundary_ties writes -------------------------------------

def _pattern(note=NOTE, cmd=0, data=0):
    return [note, 0x01, cmd, data, 0xFF, 0, 0, 0]


def test_the_tie_lands_on_a_copy_and_not_on_the_pattern():
    patterns = [_pattern()]
    track = [0]
    n = _apply_boundary_ties(track, {0: 0}, {0}, patterns, {})
    assert n == 1
    assert len(patterns) == 2, "no copy was made"
    assert track == [1], "the step was not pointed at the copy"
    assert patterns[0][2:4] == [0, 0], "the shared pattern was patched"
    assert patterns[1][:4] == [NOTE, 0x01, CMD_TONEPORTA, 0]


def test_a_contested_pattern_keeps_its_untied_entries():
    """The apply_tempos rule: the state belongs to the position, not the
    pattern. Steps 0 and 2 play pattern 0; only step 0 is entered tied."""
    patterns = [_pattern()]
    track = [0, 0, 0]
    _apply_boundary_ties(track, {0: 0, 1: 1, 2: 2}, {0}, patterns, {})
    assert track == [1, 0, 0]


def test_one_copy_serves_every_tied_step():
    patterns = [_pattern()]
    track = [0, 0]
    n = _apply_boundary_ties(track, {0: 0, 1: 1}, {0, 1}, patterns, {})
    assert n == 2
    assert len(patterns) == 2 and track == [1, 1]


def test_a_row_zero_with_no_note_is_left_alone():
    """`pending_tie` is consumed by a note, and recomputed by anything else."""
    patterns = [_pattern(note=GT_NO_NOTE)]
    track = [0]
    assert _apply_boundary_ties(track, {0: 0}, {0}, patterns, {}) == 0
    assert track == [0] and len(patterns) == 1


def test_a_taken_command_column_is_left_alone():
    """The intra-pattern tie tests `cmd1 == 0` too; this is the same rule."""
    patterns = [_pattern(cmd=15, data=6)]        # CMD_SETTEMPO
    track = [0]
    assert _apply_boundary_ties(track, {0: 0}, {0}, patterns, {}) == 0
    assert track == [0] and len(patterns) == 1


def test_a_row_that_already_ties_costs_no_copy():
    patterns = [_pattern(cmd=CMD_TONEPORTA, data=0)]
    track = [0]
    assert _apply_boundary_ties(track, {0: 0}, {0}, patterns, {}) == 1
    assert track == [0] and len(patterns) == 1


def test_the_pattern_limit_is_respected():
    patterns = [_pattern() for _ in range(MAX_PATTERNS)]
    track = [0]
    assert _apply_boundary_ties(track, {0: 0}, {0}, patterns, {}) == 0
    assert len(patterns) == MAX_PATTERNS


# --- what reindex_tracks carries ------------------------------------------

def _index(exits):
    """One slice per entry, entry i -> Goattracker pattern i."""
    return TrackIndex([[i] for i in range(len(exits))], exits)


def test_reindex_ties_the_step_after_a_tied_pattern():
    patterns = [_pattern(), _pattern()]
    tracks = [[0, 1, 0xFF, 0]]
    out = reindex_tracks(tracks, _index([True, False]), patterns=patterns)
    # Step 1 follows entry 0, which exits tied, so it plays a tied copy.
    assert out[0][:2] == [0, 2]
    assert patterns[2][2:4] == [CMD_TONEPORTA, 0]


def test_reindex_does_not_tie_after_an_untied_pattern():
    patterns = [_pattern(), _pattern()]
    tracks = [[0, 1, 0xFF, 0]]
    out = reindex_tracks(tracks, _index([False, False]), patterns=patterns)
    assert out[0][:2] == [0, 1] and len(patterns) == 2


def test_a_transpose_byte_does_not_break_the_carry():
    """An orderlist transpose is consumed by the reader and plays nothing, so
    the gate the previous pattern left open is still open."""
    patterns = [_pattern(), _pattern()]
    tracks = [[0, 0xD5, 1, 0xFF, 0]]
    out = reindex_tracks(tracks, _index([True, False]), patterns=patterns,
                         floor=0xD0)
    assert out[0][:3] == [0, 0xD5, 2]


def test_a_restart_operand_is_not_read_as_a_pattern():
    patterns = [_pattern(), _pattern()]
    tracks = [[0, 0xFF, 0x00, 1]]
    out = reindex_tracks(tracks, _index([True, False]), patterns=patterns)
    # $00 after $FF is the restart position, not a reference, so entry 1 is
    # still preceded by entry 0 and ties.
    assert out[0] == [0, 0xFF, 0x00, 2]


def test_a_plain_list_gets_no_boundary_ties():
    """Backwards compatible: only a TrackIndex carries the state."""
    patterns = [_pattern(), _pattern()]
    tracks = [[0, 1]]
    out = reindex_tracks(tracks, [[0], [1]], patterns=patterns)
    assert out[0] == [0, 1] and len(patterns) == 2


def test_no_patterns_means_no_pass():
    """reindex_tracks is called without `patterns` in several tests and by
    tracks.py; the pass must simply not run rather than raise."""
    out = reindex_tracks([[0, 1]], _index([True, False]))
    assert out[0] == [0, 1]


# --- the wrap: the boundary the orderlist closes on -----------------------
#
# `_apply_boundary_ties` reaches every boundary inside a list and none of the
# one the `$FF` makes. The player's restart is an orderlist fetch like any
# other -- version 4 zeroes the three indices and jumps to the top without
# touching `$D404` -- so a list whose LAST entry exits tied re-enters the
# pattern at its restart position with the gate open.
#
# Two things bound it, and both were measured rather than reasoned:
#
#   * a `$FD` restart position is Hubbard's *tune ended*, not a loop, so the
#     wrap the tie describes never happens (2 of the 5 corpus lists that end
#     on a tied pattern are that);
#   * voice 0's entry reference belongs to the tempo. `apply_tempos` runs
#     AFTER `reindex_tracks` and skips a pattern whose command column is
#     taken, so taking it dropped Star_Paws' tempo writes from 3 patterns to
#     1 and its subtune 1 read `melody 75% -> 37%`, `retrig 0.96 -> 0.30`,
#     with all three voices losing three quarters of their attacks.

def test_the_wrap_ties_the_restart_position():
    patterns = [_pattern(), _pattern()]
    track = [1, 0xFF, 0x00]
    assert _apply_wrap_tie(track, patterns, {}, True, False) == 1
    assert track == [2, 0xFF, 0x00], "the restart step was not repointed"
    assert patterns[2][:4] == [NOTE, 0x01, CMD_TONEPORTA, 0]
    assert patterns[1][2:4] == [0, 0], "the shared pattern was patched"


def test_an_untied_last_entry_wraps_into_nothing():
    patterns = [_pattern(), _pattern()]
    track = [1, 0xFF, 0x00]
    assert _apply_wrap_tie(track, patterns, {}, False, False) == 0
    assert track == [1, 0xFF, 0x00] and len(patterns) == 2


def test_a_stop_marker_is_not_a_loop():
    """`$FF $FD` is Hubbard's *tune ended*: an out-of-range restart position,
    written so the editor stops. `legalise_restarts` rewrites it to 0 later so
    gt2reloc will pack the file, but that loop is one the player never plays --
    tying into it would suppress an attack the original does make."""
    patterns = [_pattern(), _pattern()]
    track = [1, 0xFF, 0xFD]
    assert _apply_wrap_tie(track, patterns, {}, True, False) == 0
    assert track == [1, 0xFF, 0xFD] and len(patterns) == 2


def test_a_transpose_at_the_restart_position_is_stepped_over():
    """The reader consumes it and plays nothing, so the gate is still open
    when the pattern behind it arrives -- the same rule `reindex_tracks` uses
    to let `prev_ref` survive one."""
    patterns = [_pattern(), _pattern()]
    track = [0xD5, 1, 0xFF, 0x00]
    assert _apply_wrap_tie(track, patterns, {}, True, False) == 1
    assert track == [0xD5, 2, 0xFF, 0x00]


def test_voice_zeros_entry_reference_belongs_to_the_tempo():
    patterns = [_pattern()]
    track = [0, 0xFF, 0x00]
    assert _apply_wrap_tie(track, patterns, {}, True, True) == 0
    assert track == [0, 0xFF, 0x00] and len(patterns) == 1


def test_the_tempo_veto_only_covers_the_step_the_tempo_takes():
    """The veto is about one row, not about the voice: a restart position
    naming some later step leaves the entry reference free."""
    patterns = [_pattern(), _pattern()]
    track = [0, 1, 0xFF, 0x01]
    assert _apply_wrap_tie(track, patterns, {}, True, True) == 1
    assert track == [0, 2, 0xFF, 0x01]


def test_reindex_wraps_the_last_entrys_state_into_the_restart():
    patterns = [_pattern()]
    tracks = [[0, 0xFF, 0]] * 3
    out = reindex_tracks(tracks, _index([True]), patterns=patterns)
    # Voice 0 yields to the tempo; voices 1 and 2 share one tied copy.
    assert [t[0] for t in out] == [0, 1, 1]
    assert patterns[1][2:4] == [CMD_TONEPORTA, 0]


def test_the_wrap_leaves_voice_zeros_row_for_apply_tempos():
    """The regression Star_Paws measured, in one assertion: the tempo pass
    runs after reindexing and cannot write into a column this took."""
    patterns = [_pattern()]
    tracks = [[0, 0xFF, 0] for _ in range(3)]
    out = reindex_tracks(tracks, _index([True]), patterns=patterns)
    assert apply_tempos(patterns, out, [6]) == 1
    assert patterns[out[0][0]][2:4] == [CMD_SETTEMPO, 6]


@needs_corpus
def test_star_paws_keeps_all_three_of_its_opening_tempos():
    """Star_Paws is the only corpus file the wrap reaches, and both of its
    tied exits are on voice 0 -- so the whole of what this pass does there is
    to decline. With the veto missing it wrote a tie into the entry pattern of
    subtunes 1 and 2, and the log line below read `in 1 pattern(s)`.

    `tie=True` is not decoration: it defaults **off**, and without it this
    test converts a song with no tie state at all and passes whatever the
    wrap does -- which is how it was first written."""
    lines: list = []
    convert(str(CORPUS / "Star_Paws.sid"), log=lines.append, tempo="auto",
            tie=True)
    tempo = [ln for ln in lines if ln.startswith("Tempo")]
    assert len(tempo) == 1, tempo
    assert "in 3 pattern(s)" in tempo[0], tempo[0]


# --- the corpus files this was found on -----------------------------------

@needs_corpus
@pytest.mark.parametrize("name,tied,untied", [
    ("Human_Race.sid", (0x2, 0x3, 0x5, 0x6, 0x8, 0x9, 0xB, 0xC, 0x11),
     (0x0, 0x1, 0x4, 0x7, 0xA, 0xD)),
    # Warhawk $23 (`64 FF`), $2F and $30 (`... 7F 7F 7F FF`) end on a **rest**
    # carrying bit 5, and are untied for that reason -- see
    # test_a_rest_carrying_bit5_does_not_exit_tied. They were in the tied list
    # until the rest's own gate-off was read; $25-$28 stay tied through the
    # zero-`wait` path, which is what keeps this pair of lists a real test of
    # both causes rather than of one.
    ("Warhawk.sid", (0x25, 0x26, 0x27, 0x28),
     (0x0, 0x1, 0x2, 0x22, 0x23, 0x24, 0x2F, 0x30)),
])
def test_corpus_entries_report_the_expected_exit_state(name, tied, untied):
    sid = load_sid(str(CORPUS / name))
    sid, det = _detect_tables(sid, lambda m: None, 0)
    assert det.can_convert and det.gate_hold

    def state(i):
        ex: list = []
        assert decode_entry(sid, det, i, slides=True, status_bit6=True,
                            rest_instrument=True, instr_base=1, tie=True,
                            rest_keyoff=True, exits_tied=ex) is not None
        assert len(ex) == 1
        return ex[0]

    assert [i for i in tied if not state(i)] == []
    assert [i for i in untied if state(i)] == []


# --- the three declines, and the one that is not on voice 0 ---------------
#
# The pass had been recorded as reaching nothing because "every corpus
# instance is on voice 0", and that is not why. Censused by wrapping
# `_apply_wrap_tie` at its own call site over the whole corpus, five voice
# orderlists exit tied and three have an in-range restart, and they decline
# for THREE unrelated reasons -- one of them on voice 1, where the veto never
# runs at all. See the function's docstring for the table and the numbers.

def test_a_keyoff_at_the_restart_position_is_not_a_note_to_tie_into():
    """Chimera's decline, as a unit.

    `GT_KEYOFF` is $BE and `GT_LASTNOTE` is $BC, so a KEYOFF row 0 fails
    `_tie_step`'s note-range test. That is the right answer rather than an
    off-by-two: a KEYOFF is the player's own data saying *release here*, so
    there is no attack being suppressed and nothing to tie into. Tying it
    would write a portamento into a row that closes the gate.
    """
    patterns = [_pattern(), _pattern(note=GT_KEYOFF)]
    track = [1, 0xFF, 0x00]
    assert _apply_wrap_tie(track, patterns, {}, True, False) == 0
    assert track == [1, 0xFF, 0x00], "the step was repointed anyway"
    assert len(patterns) == 2, "a copy was made for a row that cannot tie"


def test_the_same_step_with_a_real_note_does_tie():
    """The pair for the test above: it is the KEYOFF that declines, not the
    fixture. Same track, same call, one byte different on row 0."""
    patterns = [_pattern(), _pattern()]
    track = [1, 0xFF, 0x00]
    assert _apply_wrap_tie(track, patterns, {}, True, False) == 1
    assert track[0] == 2


@needs_corpus
def test_the_corpus_wrap_census_has_not_moved():
    """Every exit-tied orderlist in the corpus, and why each one declines.

    Four files carry all five, so this pins the census without converting the
    whole corpus. It asserts the DECLINE KIND per file, not just a total: a
    change that turned the KEYOFF decline into a tie, or that lifted the
    tempo veto, would leave the total at zero ties on some other route and
    pass a bare count.
    """
    import h2g.patterns as P

    real = P._apply_wrap_tie
    seen: list = []
    state = {"file": None, "ti": -1}

    def spy(new_track, patterns, copies, exits_tied, tempo_voice, log=None):
        state["ti"] += 1
        ti = state["ti"]
        songlen = next((i for i, b in enumerate(new_track)
                        if b == P.GT_ORDER_RESTART), None)
        pos = (new_track[songlen + 1]
               if songlen is not None and songlen + 1 < len(new_track) else None)
        n = real(new_track, patterns, copies, exits_tied, tempo_voice, log)
        if exits_tied:
            in_range = (pos is not None and songlen is not None
                        and pos < songlen)
            seen.append((state["file"], ti // 3, ti % 3, in_range, n))
        return n

    expect = {
        # file,               subtune, voice, restart in range, ties written
        "Chimera.sid":        [(0, 1, True, 0)],    # row 0 is a KEYOFF
        "Flash_Gordon.sid":   [(6, 0, False, 0)],   # $FD: a stop, not a loop
        "Star_Paws.sid":      [(1, 0, True, 0),     # the tempo owns the column
                               (2, 0, True, 0)],
        "Warhawk.sid":        [(4, 2, False, 0)],   # $FD: a stop, not a loop
    }
    P._apply_wrap_tie = spy
    try:
        for name in sorted(expect):
            state["file"], state["ti"] = name, -1
            convert(str(CORPUS / name), log=lambda m: None, tempo="auto",
                    tie=True)
    finally:
        P._apply_wrap_tie = real

    got: dict = {}
    for name, sub, voice, in_range, n in seen:
        got.setdefault(name, []).append((sub, voice, in_range, n))
    assert got == expect, f"the wrap census moved:\n got {got}\n want {expect}"
    assert sum(n for *_, n in seen) == 0, "a wrap tie was written"
    # The finding this test exists for: the one instance NOT on voice 0.
    assert got["Chimera.sid"][0][1] == 1, "Chimera's tied exit left voice 1"
