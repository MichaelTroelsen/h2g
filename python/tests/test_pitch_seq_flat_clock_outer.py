"""Bit $10's UNDIVIDED clock on the classic outer-gated players.

Task pitch-seq-flat-clock-other-files. 24 corpus files detect the bit-$10
block with an undivided phase counter and the classic play routine (Bangkok_
Knights `$8059`):

    DEC outer / BPL / LDA #skip / STA outer / JMP voice-loop      ; outer gate
    DEC inner / BPL / LDA speed / STA inner                       ; speed gate
    voice loop ... LDA outer / BEQ nofetch / LDA inner / CMP speed / BNE ...
    DEX / BMI +3 / JMP loop       ; the loop's exit
    DEC phase / BPL / LDA #n / STA phase                          ; every call

The voice loop runs on every call (the outer gate only withholds the fetch),
so the phase steps once per call; the new-song call (`JMP` out of the play
entry) runs the phase and nothing else, and a note's attack frame is plain.
`_pitch_seq_outer_flat_clock` reads it, and `pitch_seq_phases` carries it as
it does Food_Feud's divided clock and Mega_Apocalypse's zero-page one
(tests/test_pitch_seq_flat_clock.py).
"""
import dataclasses
import pathlib
import subprocess
import sys

import pytest

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[1]))

from corpus import CORPUS, needs_corpus                        # noqa: E402

import fidelity                                                # noqa: E402
from h2g import goatwriter as G                                # noqa: E402
from h2g.convert import _detect_tables                         # noqa: E402
from h2g.sidfile import load_sid                               # noqa: E402

needs_siddump = pytest.mark.skipif(
    not pathlib.Path(fidelity.SIDDUMP).exists(),
    reason="no siddump on this machine (tools/siddump-rt, see its README)")

# stem -> (phase file byte, phase reload, outer file byte, inner file byte),
# every one of them the file's own bytes; `divider=0, divider_reload=0`.
READ = {
    "After_8": (0, 2, 0, 0),
    "Bangkok_Knights": (0, 2, 94, 1),
    "BMX_Kidz": (1, 2, 107, 2),
    "Chain_Reaction": (0, 2, 0, 0),
    "Flash_Gordon": (1, 2, 4, 0),
    "I_Ball": (0, 2, 0, 0),
    "IK_plus": (0, 2, 0, 0),
    "Lightforce": (0, 2, 6, 0),
    "Mr_Meaner": (0, 2, 0, 0),
    "Nineteen": (1, 2, 62, 1),
    "Off_the_Cuff": (0, 2, 0, 0),
    "Pandora": (1, 2, 29, 1),
    "Pygmies_Revenge": (0, 2, 0, 0),
    "Rikky": (0, 2, 0, 0),
    "Rock_Tells_the_Tale": (0, 2, 0, 0),
    "Saboteur_II": (0, 2, 0, 1),
    "Sanxion": (1, 2, 71, 2),
    "Shockway_Rider": (2, 2, 1, 1),
    "Star_Paws": (0, 2, 6, 0),
    "Thundercats": (1, 1, 3, 0),
    "Trans-Atlantic_Balloon_Challenge": (2, 2, 109, 2),
    "W_A_R": (2, 2, 2, 1),
    "W_A_R_Preview": (2, 2, 3, 1),
    "Zoolook": (2, 2, 3, 0),
}
# Detect the block with an undivided counter and are NOT read, and why.
DECLINED = {
    "Delta_Mix-E-Load_loader": "init JSRs the player entry: frame 0 is a plain call",
    "Dragons_Lair_Part_II": "init stores the outer cell",
    "Kings_of_the_Beach_ingame": "init stores the outer cell",
    "Knucklebusters": "a song event stores the outer and speed cells",
    "Go_Go_Dash": "the phase cell is never written: a constant",
    "Lakers_vs_Celtics": "the phase cell is never written: a constant",
    "Lion_Heart": "the phase cell is never written: a constant",
    "Pacific_Coast": "the phase cell is never written: a constant",
    "Radio_ACE": "the phase cell is never written: a constant",
    "Sun_Never_Shines": "the phase cell is never written: a constant",
}


def _tables(stem):
    return _detect_tables(load_sid(str(CORPUS / f"{stem}.sid")),
                          lambda *a, **k: None)


def _patched(sid, at, new):
    data = bytearray(sid.data)
    data[at:at + len(new)] = bytes(new)
    return dataclasses.replace(sid, data=bytes(data))


@needs_corpus
def test_the_outer_flat_clock_is_read_on_exactly_these_files():
    got = {}
    for path in sorted(CORPUS.glob("*.sid")):
        sid, det = _detect_tables(load_sid(str(path)), lambda *a, **k: None)
        if det is None:
            continue
        clock = G._pitch_seq_outer_flat_clock(sid, det)
        if clock is not None:
            assert (clock.divider, clock.divider_reload) == (0, 0)
            got[path.stem] = (clock.phase, clock.phase_reload, clock.outer,
                              clock.inner)
    assert got == READ, (set(got) ^ set(READ), got)


@needs_corpus
def test_every_other_undivided_file_is_declined_and_the_dispatcher_agrees():
    for stem in DECLINED:
        sid, det = _tables(stem)
        assert det.pitch_seq is not None, stem
        assert G._pitch_seq_flat_clock(sid, det) is None, (stem, DECLINED[stem])
        assert G._pitch_seq_any_clock(sid, det) is None, stem
    # the dispatcher keeps the zero-page reader and the divided one apart
    sid, det = _tables("Bangkok_Knights")
    assert G._pitch_seq_clock(sid, det) is None          # not divided
    assert G._pitch_seq_zp_flat_clock(sid, det) is None   # not Mega's shape
    assert G._pitch_seq_flat_clock(sid, det) == G._pitch_seq_outer_flat_clock(
        sid, det)
    sid, det = _tables("Mega_Apocalypse")
    assert G._pitch_seq_outer_flat_clock(sid, det) is None
    assert G._pitch_seq_flat_clock(sid, det) == G._pitch_seq_zp_flat_clock(
        sid, det)
    sid, det = _tables("Food_Feud")
    assert G._pitch_seq_flat_clock(sid, det) is None
    assert G._pitch_seq_clock(sid, det) is not None


@needs_corpus
def test_a_third_writer_of_the_outer_or_speed_cell_declines_the_clock():
    """Dragons_Lair's init stores the outer cell, so its first value is not
    the file's byte. One `STA abs` planted in dead bytes at the file's end,
    for each cell."""
    sid, det = _tables("Bangkok_Knights")
    assert G._pitch_seq_outer_flat_clock(sid, det) is not None
    for cell in (0x85DD, 0x85CA, 0x89C8):      # outer, speed counter, phase
        bad = _patched(sid, len(sid.data) - 3,
                       [0x8D, cell & 0xFF, cell >> 8])
        assert G._pitch_seq_outer_flat_clock(bad, det) is None, hex(cell)


@needs_corpus
def test_a_phase_step_not_behind_the_voice_loop_declines_the_clock():
    """Bangkok's `DEX / BMI +3 / JMP loop` sits directly before the `DEC`
    ($84D5); the `DEX` overwritten with a `NOP` and the clock is declined."""
    sid, det = _tables("Bangkok_Knights")
    at = sid.to_offset(0x84D5)
    assert bytes(sid.data[at:at + 4]) == G.arpeggio.PITCH_SEQ_VOICE_EXIT
    assert G._pitch_seq_outer_flat_clock(_patched(sid, at, [0xEA]), det) is None


@needs_corpus
def test_the_phase_step_reached_by_a_jmp_from_the_voice_exit_is_read():
    """W_A_R puts the `DEC` in a tail routine behind `DEX / BMI +3 / JMP
    loop / JMP tail` ($E808)."""
    sid, det = _tables("W_A_R")
    at = sid.to_offset(0xE808)
    assert bytes(sid.data[at:at + 4]) == G.arpeggio.PITCH_SEQ_VOICE_EXIT
    assert bytes(sid.data[at + 6:at + 7]) == b"\x4c"
    assert G._pitch_seq_outer_flat_clock(sid, det) is not None
    assert G._pitch_seq_outer_flat_clock(_patched(sid, at, [0xEA]), det) is None


@needs_corpus
def test_a_fetch_guard_that_does_not_name_the_outer_cell_declines():
    """`LDA outer / BEQ nofetch` ($807D... Bangkok $8078): the outer cell's
    operand changed to the speed cell and the guard no longer names it."""
    sid, det = _tables("Bangkok_Knights")
    at = sid.to_offset(0x8078)
    assert bytes(sid.data[at:at + 4]) == bytes([0xAD, 0xDD, 0x85, 0xF0])
    assert G._pitch_seq_outer_flat_clock(_patched(sid, at + 1, [0xDC]),
                                         det) is None


@needs_corpus
def test_an_init_that_calls_the_player_entry_declines_the_clock():
    """Delta_Mix-E-Load_loader's init JSRs `$C012`, five bytes of volume
    set-up ahead of the entry's `BIT $C55E`, so the new-song call has run
    before frame 0: measured, frame 0 reads phase 1 where the clock reads 2.
    The same JSR planted into Bangkok_Knights' init body (`LDY #0 / TAX` at
    $903C replaced by `JSR $800F`) declines it too."""
    sid, det = _tables("Delta_Mix-E-Load_loader")
    assert G._init_runs_player_entry(
        sid, G._pitch_seq_phase_block(sid)[1]) is True
    sid, det = _tables("Bangkok_Knights")
    at = sid.to_offset(0x903C)
    assert bytes(sid.data[at:at + 3]) == bytes([0xA0, 0x00, 0xAA])
    assert G._init_runs_player_entry(
        sid, G._pitch_seq_phase_block(sid)[1]) is False
    bad = _patched(sid, at, [0x20, 0x0F, 0x80])
    assert G._init_runs_player_entry(
        bad, G._pitch_seq_phase_block(bad)[1]) is True
    assert G._pitch_seq_outer_flat_clock(bad, det) is None


@needs_corpus
def test_the_init_scan_stops_at_the_jmp_so_a_wrappers_irq_handler_is_not_it():
    """After_8's init is `JMP $26EF`; behind its `JMP $100C` sits the IRQ
    handler whose `JSR $1012` ($2726) IS the play call, not the init's. And
    IK_plus's init `JSR $E009` is the init vector of a `JMP` table, which
    the entry's own bytes (`JMP` / `JMP`) are not a straight run to."""
    for stem in ("After_8", "IK_plus", "Bangkok_Knights"):
        sid, det = _tables(stem)
        phase_at = G._pitch_seq_phase_block(sid)[1]
        assert G._init_runs_player_entry(sid, phase_at) is False, stem
        assert G._pitch_seq_outer_flat_clock(sid, det) is not None, stem


def _dump_cells(path, subtune, cells, seconds):
    out = subprocess.run(
        [str(fidelity.SIDDUMP), str(path), f"-a{subtune}", f"-t{seconds}",
         f"-v{fidelity.PAL_FLAG}", "-w" + ",".join(f"{c:04x}" for c in cells)],
        capture_output=True, text=True, timeout=300,
        stdin=subprocess.DEVNULL).stdout
    rows = {}
    for line in out.splitlines():
        c = line.split("|")
        if len(c) >= 8:
            try:
                rows[int(c[1])] = tuple(int(x, 16) for x in c[6].split())
            except ValueError:
                continue
    return rows


def _cells(sid):
    m = G.OUTER_GATE.search(sid.data)
    g = G.SPEED_GATE.match(sid.data, m.end())
    (lo, hi), _ = G._pitch_seq_phase_block(sid)
    word = lambda b: b[0] | b[1] << 8                          # noqa: E731
    return word(m.group(1)), word(g.group(1)), word(g.group(2)), lo | hi << 8


# One file per spelling: the plain one, a non-zero phase and outer, a
# wrapper init, a `JMP`-to-tail phase step, and a gate that ends its tune.
MEASURED = ("Bangkok_Knights", "Nineteen", "After_8", "W_A_R", "Thundercats",
            "Flash_Gordon", "Zoolook", "Trans-Atlantic_Balloon_Challenge")


@needs_corpus
@needs_siddump
@pytest.mark.parametrize("stem", MEASURED)
def test_the_simulated_outer_flat_clock_is_re_measured_against_the_original(
        stem):
    """`siddump -w<outer>,<inner>,<speed>,<phase>` samples the cells after
    every call. On every subtune whose gate runs (a stopped one never moves
    the outer cell, and a tune that ends freezes it -- compared up to its
    last move) and whose row length is read: the simulated phase equals the
    phase cell on every frame, and the simulated fetches are exactly the
    frames where `outer != 0 and inner == speed`. Frame 0 is the new-song
    call: the phase stepped once, nothing else."""
    sid, det = _tables(stem)
    clock = G._pitch_seq_outer_flat_clock(sid, det)
    speeds = G.find_song_speeds(sid, det)
    cells = _cells(sid)
    checked = 0
    for sub in range(max(sid.subtunes, 1)):
        frames, skip = speeds.frames_for(sub), speeds.skip_for(sub)
        if not G._pitch_seq_rate_read(clock, frames, skip, sub):
            continue
        rows = _dump_cells(CORPUS / f"{stem}.sid", sub, cells, 30)
        moves = [f for f in range(1, len(rows)) if rows[f][0] != rows[f - 1][0]]
        if not moves:
            continue                                    # a stopped subtune
        assert rows[0][3] == G._pitch_seq_advance(
            clock, (clock.divider, clock.phase))[1], (stem, sub)
        calls = G._pitch_seq_calls(clock, frames, skip)
        for frame in range(1, moves[-1] + 1):
            _seen, fetched, after = next(calls)
            outer, inner, speed, phase = rows[frame]
            assert after[1] == phase, (stem, sub, frame)
            assert fetched == (outer != 0 and inner == speed), (stem, sub, frame)
        checked += 1
    assert checked >= 1, stem


# --- the lead: the attack frame is plain wherever the note's call 0 falls ---

def _note_after_each_call(left, right, calls):
    """The note a wavetable leaves sounding after note call 1, 2, ...
    `left`/`right` as `_pitch_seq_phased_entries` returns them (last pair:
    `$FF` and its 1-based target). An entry whose left side is 1..15 is a
    delay: current for `left + 1` calls, its right side applied on the last
    (gplay.c's wavetable-delay `else`); any other left side applies at once.
    A jump is read on the entry before it and costs no call."""
    out, pos, wait, note = [], 0, 0, None
    for _ in range(calls):
        entry = left[pos]
        if 1 <= entry <= 15:
            if wait < entry:
                wait += 1
                out.append(note)
                continue
            wait = 0
        note = right[pos]
        pos += 1
        if left[pos] == 0xFF:
            pos = right[pos] - 1
        out.append(note)
    return out


def _sampled_frames(left, right, m, c, count):
    """What a frame-end sampler reads for a note whose call 0 -- the `$09`
    firstwave, below `$10` -- is call `c` of its frame (0-based), for `count`
    frames from the one holding call 1, which is the frame the attack is
    named from. Wavetable call `j` is note call `j + 1`."""
    first = (c + 1) // m
    last_call = (first + count) * m - c
    per_call = _note_after_each_call(left, right, last_call + 1)
    out = []
    for frame in range(first, first + count):
        call = (frame + 1) * m - 1 - c            # the frame's last call
        out.append(per_call[call - 1])
    return out


@pytest.mark.parametrize("m", [1, 2, 3, 4, 5])
def test_the_phased_block_is_plain_on_the_attack_frame_wherever_call_0_falls(m):
    """For every call position `c` of the note's call 0 in its frame, the
    attack frame samples the note's own note and frame `f` the group `f - 1`
    of the period. With `m - 1` plain calls the note starting on its frame's
    last call (`c == m - 1`) sampled the first phase on its attack frame
    (task pitch-seq-flat-clock-other-files: Chain_Reaction, melody 1.0000
    -> 0.8477 before this). At -S2 and up the block is `1 + period` entries
    of `(m - 1, note)` delays, not `m + period * m`."""
    notes, phases = [0x00, 0x7C, 0x79], (2, 1, 0)
    left, right = G._pitch_seq_phased_entries(notes, phases, 0x41, m,
                                              start=1, budget=200)
    plain = G.WAVE_NOTE_BASE
    assert left[-1] == 0xFF and right[0] == plain
    if m == 1:
        assert len(left) == 1 + 3 + 1 and left[:-1] == [0x41] * 4
    else:
        assert left == [0x41] + [m - 1] * 3 + [0xFF]
        assert right[1:4] == [0x79, 0x7C, 0x00]
    assert right[-1] == 2                      # looped onto the first step
    for c in range(m):
        seen = _sampled_frames(left, right, m, c, 1 + 2 * len(phases))
        assert seen[0] == plain, (m, c)
        for frame in range(1, len(seen)):
            assert seen[frame] == notes[phases[(frame - 1) % 3]], (m, c, frame)
    if m >= 2:                                  # the lead it replaced fails
        old_left = [0x41] * (m - 1 + 3 * m) + [0xFF]
        old_right = ([plain] * (m - 1)
                     + [notes[p] for p in phases for _ in range(m)]
                     + [m])
        assert _sampled_frames(old_left, old_right, m, m - 1, 1)[0] != plain


def test_a_multiplier_past_the_delay_range_keeps_the_long_form():
    notes, phases = [0x00, 0x7C, 0x79], (2, 1, 0)
    left, right = G._pitch_seq_phased_entries(notes, phases, 0x41, 17,
                                              start=1, budget=200)
    assert left == [0x41] * (17 + 3 * 17) + [0xFF]
