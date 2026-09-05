"""The interleaved engine's `$83` semitone arpeggio, emitted as CMD_SETWAVEPTR.

The mechanism is decoded in `patterns.ILV_ARP` and the encoding argued in
`goatwriter._arp_block`. What is pinned here is what can rot silently:

* the CYCLE the player's self-modifying dispatch produces, including the
  two-step case a `$x0` operand wraps to at `$1431`;
* the FRAME arithmetic, which is the packed player's rather than the editor's
  -- a wavetable call is one play call, and a note's first call runs no
  wavetable entry at all (player.s:908-911);
* the WIRING, which is the half every other test here would miss. The decoder
  emits an INDEX into `arps` and `build_sng` remaps it to a wavetable row;
  a value that is computed correctly, tested, and reaches no output is the
  failure this repo recorded in the drift-knee fields one version ago, so the
  end-to-end test below reads the finished `.sng` back with `songview` and
  checks the operand is a row and not an index.

Synthetic where the shape is the point, corpus where the population is.
"""
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import songview                                              # noqa: E402
from corpus import CORPUS, needs_corpus                      # noqa: E402
from h2g import goatwriter as G                              # noqa: E402
from h2g import patterns as P                                # noqa: E402
from h2g.convert import convert                              # noqa: E402

# Five of the six carry a `$83`; Pacific_Coast carries none, and it is in the
# list precisely so a change that gated on the DIALECT rather than on the
# MECHANISM would fail here.
ARPEGGIATED = {
    "Go_Go_Dash.sid": (41, 6),
    "Lakers_vs_Celtics.sid": (64, 9),
    "Lion_Heart.sid": (63, 5),
    "Radio_ACE.sid": (351, 12),
    "Sun_Never_Shines.sid": (143, 9),
}
UNARPEGGIATED = "Pacific_Coast.sid"


# ----------------------------------------------------------------- the cycle

def test_the_cycle_is_zero_then_the_high_nibble_then_the_low_one():
    assert G._arp_offsets(0x5B) == [0, 5, 11]


def test_a_low_nibble_of_zero_is_a_two_step_trill():
    """`$1431 LDA $1A55,X / AND #$0F / BNE` wraps at step 1 when it is zero.

    Emitting three steps with a zero third would trill at two thirds of the
    player's rate, which is the same class of error as a rate read per frame
    and applied per call.
    """
    assert G._arp_offsets(0x50) == [0, 5]
    assert G._arp_offsets(0x90) == [0, 9]


def test_an_empty_operand_is_declined_rather_than_emitted_flat():
    assert G._arp_offsets(0x00) is None


# ------------------------------------------------------- the frame arithmetic

SOURCE = [(0x41, 0), (0x02, 0), (0x41, 0), (0xFF, 0), (0x00, 0)]


def test_the_source_programs_waveforms_are_copied_verbatim():
    """The arpeggio moves the NOTE. Holding one waveform instead would drop
    Go_Go_Dash's `02` and Lion_Heart's `01` attack delays -- two of the five.
    """
    left, _ = G._arp_block(SOURCE, [0, 5], 1, 10)
    assert left[:3] == [0x41, 0x02, 0x41]


def test_entry_zero_is_step_zero_because_the_cycle_has_a_two_frame_head():
    """**This test used to assert `WAVE_NOTE_BASE + 5`, and the head is why it
    does not any more.**

    The packed player runs no wavetable entry on a note's first call, so entry
    0 lands on frame 1 -- which is why the old reading made it the cycle's
    SECOND step. Measured at v0.5.461 against the originals' own
    per-offset-from-attack profile, the players hold step 0 for frames 0 AND 1
    and raise on frame 2, so `ARP_HEAD_FRAMES` subtracts that head and clamps
    at 0. Radio_ACE voice 2 reads `+0 +0 +7 +0 +7 +0` where ours read
    `+0 -7 +0 -7 +0 +0`, one for one over 232 notes.

    Emitting the second step here put the offset ON the attack frame, and
    siddump names an attack from the frequency the gate rises on -- so the old
    arithmetic renamed every arpeggiated attack while leaving the COUNT alone.
    See `ARP_HEAD_FRAMES` for the three-arm A/B.
    """
    _, right = G._arp_block(SOURCE, [0, 5], 1, 10)
    assert right[0] == G.WAVE_NOTE_BASE + 0
    # and the head is a HEAD, not an off-by-one: with it removed the same
    # call would be step 1 again.
    assert G.ARP_HEAD_FRAMES == 2


def test_entry_zero_covers_frame_zero_above_multiplier_one():
    _, right = G._arp_block(SOURCE, [0, 5], 3, 10)
    assert right[0] == G.WAVE_NOTE_BASE + 0


def test_a_delay_entry_is_charged_to_the_frame_of_its_LAST_call():
    """A delay is current for `left + 1` calls and applies its right side on
    the last of them (gplay.c:697-704). Charging it to its first call would
    put the step a frame early on exactly the two files that have delays.
    """
    # A THREE-step cycle, deliberately: with the two-frame head a two-step one
    # puts both entries on step 0 and the test stops discriminating.
    _, right = G._arp_block([(0x41, 0), (0x02, 0), (0xFF, 0)], [0, 5, 7], 1, 10)
    # call 0 -> frame 1, less the head -> step 0
    assert right[0] == G.WAVE_NOTE_BASE + 0
    # the delay spans calls 1..3; its LAST is frame 4, less the head -> step 2.
    # Charged to its FIRST call it would be frame 2 -> step 0, so this asserts
    # the difference rather than the value.
    assert right[1] == G.WAVE_NOTE_BASE + 7


def test_the_step_is_a_rate_and_is_scaled_by_the_multiplier():
    """One frame is `multiplier` play calls, so a step holds that many entries.
    Without it a -S3 file arpeggiates three times too fast -- the rule
    CLAUDE.md states and `_filter_entries` broke for the life of the project.
    """
    for mult in (1, 2, 3, 4):
        left, _ = G._arp_block(SOURCE, [0, 5, 11], mult, 10)
        body = 3            # the source's own entries, before the terminator
        assert len(left) == body + 3 * mult + 1, mult


def test_the_jump_returns_to_the_TAIL_and_the_phase_across_it_is_exact():
    """Jumping to the block's start would re-run the attack program on every
    wrap; jumping to the tail keeps the waveform and the phase, because a whole
    cycle is a whole number of frames.
    """
    start = 10
    left, right = G._arp_block(SOURCE, [0, 5, 11], 2, start)
    assert left[-1] == G.WAVE_JUMP
    tail = start + 3                      # past the source's three entries
    assert right[-1] == tail
    # The tail is a WHOLE cycle, so the frame after its last entry is
    # congruent with its first: grouped by the multiplier its right column is
    # a rotation of the offsets, each step held `multiplier` entries.
    body = right[tail - start:-1]
    groups = [body[k:k + 2] for k in range(0, len(body), 2)]
    assert all(g[0] == g[1] for g in groups), groups
    steps = [g[0] - G.WAVE_NOTE_BASE for g in groups]
    # The source's three entries cover frames 0, 2 and 2 (its `02` delay spans
    # three calls), so it ends inside frame 2 -- step 11 -- and the tail must
    # open on frame 3, which is step 0. Continuing rather than restarting is
    # the property; the exact rotation is what proves it.
    assert steps == [0, 5, 11], steps


def test_a_program_with_no_waveform_at_all_is_declined():
    """`$00`-`$0F` on the left is a DELAY. A block whose sustained byte came
    out of that range would read as a delay for the whole note.
    """
    assert G._arp_block([(0x02, 0), (0xFF, 0)], [0, 5], 1, 10) is None
    assert G._arp_block([(0xFF, 0)], [0, 5], 1, 10) is None


# ------------------------------------------------------------- the decoder

def _stream(*b):
    return bytes([0x00, 0x00]) + bytes(b)


def test_the_command_lands_on_the_notes_own_row_and_not_its_hold_rows():
    """CMD_SETWAVEPTR is one-shot: it points the wavetable and the block loops
    for as long as the note is held. The `$82` slide immediately beside it in
    the decoder is continuous and MUST be repeated -- the two are opposite,
    which is why this is pinned rather than assumed.
    """
    arps: list = []
    data = _stream(0x80, 0x05, 0x83, 0x50, 0xC0 | 3, 0x30, P.ILV_END)
    ev = P._build_raw_pattern_ilv(data, 2, arps=arps)
    rows = [ev[i:i + 4] for i in range(0, len(ev), 4)]
    assert arps == [(5, 0x50)]
    assert rows[0][2:] == [P.CMD_SETWAVEPTR, 1], rows[0]
    assert [r[2:] for r in rows[1:4]] == [[0, 0]] * 3, "hold rows carry nothing"


def test_a_slide_keeps_the_command_column_and_the_arpeggio_declines():
    """Measured over all 7742 events of the six files, no event carries both --
    but where one did, the shipped and measured `$82` must win.
    """
    arps: list = []
    data = _stream(0x80, 0x05, 0x83, 0x50, 0x82, 0x01, 0x00, 0x30, P.ILV_END)
    ev = P._build_raw_pattern_ilv(data, 2, slides=True, steps=[], arps=arps)
    assert ev[2] in (1, 2), "the portamento, not the wavetable pointer"


def test_a_rest_consumes_the_arm_rather_than_carrying_it_to_the_next_note():
    """The player's flag is cleared at the next note start whatever that note
    is, so an arpeggio must not survive a rest and land on the note after it.
    """
    arps: list = []
    data = _stream(0x80, 0x05, 0x83, 0x50, P.ILV_REST, 0x30, P.ILV_END)
    ev = P._build_raw_pattern_ilv(data, 2, arps=arps)
    rows = [ev[i:i + 4] for i in range(0, len(ev), 4)]
    assert rows[1][2:] == [0, 0], "the note after the rest is not arpeggiated"


def test_nothing_is_emitted_when_the_option_is_off():
    """`arps=None` is the off state, and it must leave the stream exactly as it
    was -- this is what makes the corpus byte-hash 0 of 89 with the option off.
    """
    data = _stream(0x80, 0x05, 0x83, 0x50, 0x30, P.ILV_END)
    assert P._build_raw_pattern_ilv(data, 2, arps=None) == \
        P._build_raw_pattern_ilv(data, 2)


# ------------------------------------------------------------- the wiring

@needs_corpus
@pytest.mark.parametrize("name", sorted(ARPEGGIATED) + [UNARPEGGIATED])
def test_the_operand_reaches_the_sng_as_a_wavetable_row(name):
    """Read back with `songview`, a second reader of the format.

    The decoder emits an INDEX into `arps` and `build_sng` remaps it to a row.
    An unresolved index is a valid-looking byte that points the player at
    whatever sits at that row, so this asserts every emitted operand names a
    row inside the table AND that the row it names is the start of a block.
    """
    blob = convert(str(CORPUS / name), fmt="gts5", slides=True, effects=True,
                   compact_instruments=True, arpeggio=True)
    song = songview.parse_sng(blob)
    wave = song.tables["WTBL"]
    rows = [r for pat in song.patterns
            for r in (pat[k:k + 4] for k in range(0, len(pat), 4))
            if len(r) == 4 and r[2] == P.CMD_SETWAVEPTR]
    if name == UNARPEGGIATED:
        assert not rows, "no $83 in this file, so no command"
        return
    expected_rows, expected_blocks = ARPEGGIATED[name]
    assert len(rows) == expected_rows, f"{len(rows)} rows"
    targets = {r[3] for r in rows}
    assert len(targets) == expected_blocks, sorted(targets)
    for t in targets:
        assert 1 <= t <= len(wave), f"row {t} outside a {len(wave)}-entry table"
        # A block's first entry is a waveform or a delay -- never the jump that
        # ends the block before it, which is what an off-by-one would land on.
        assert wave[t - 1][0] != G.WAVE_JUMP, f"row {t} is a terminator"


@needs_corpus
def test_the_option_off_is_byte_identical():
    """The blocks are appended AFTER every instrument's, so no instrument's
    wavetable start moves. Corpus-wide this is 0 of 89 files; here it is the
    one file that would move if the layout had shifted.
    """
    kw = dict(fmt="gts5", slides=True, effects=True, compact_instruments=True)
    assert convert(str(CORPUS / "Radio_ACE.sid"), arpeggio=False, **kw) == \
        convert(str(CORPUS / "Radio_ACE.sid"), **kw)


@needs_corpus
def test_every_block_terminates_and_jumps_inside_itself():
    """The `exectable` question `tests/test_table_validation.py` asks of the
    instrument blocks, asked of these -- that file runs on the SHIPPED presets,
    where this option is off, so it cannot see them.
    """
    for name in sorted(ARPEGGIATED):
        blob = convert(str(CORPUS / name), fmt="gts5", slides=True,
                       effects=True, compact_instruments=True, arpeggio=True)
        song = songview.parse_sng(blob)
        wave = song.tables["WTBL"]
        targets = {r[3] for pat in song.patterns
                   for r in (pat[k:k + 4] for k in range(0, len(pat), 4))
                   if len(r) == 4 and r[2] == P.CMD_SETWAVEPTR}
        for t in sorted(targets):
            k, seen = t, 0
            while seen < len(wave):
                assert 1 <= k <= len(wave), f"{name}: ran off the table"
                left, right = wave[k - 1]
                if left == G.WAVE_JUMP:
                    assert t <= right < k, \
                        f"{name}: block at {t} jumps to {right}, outside itself"
                    break
                k += 1
                seen += 1
            else:
                pytest.fail(f"{name}: block at {t} never terminates")
