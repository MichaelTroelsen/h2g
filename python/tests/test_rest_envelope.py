"""The bit-6 rest's zeroed envelope pair: detection, and what it emits.

The routine is one idiom in 21 corpus files -- `LDA #$00` and two indexed
stores at consecutive DESCENDING addresses, SR before AD -- and it is the half
the `"testbit"`/`"envelope"` names in `_rest_silence_kind` do not describe.
See detect._find_rest_silence_envelope.
"""
import glob
import os

import pytest

from h2g.detect import (STATUS_BIT6_SHAPE, _find_rest_silence_envelope,
                        detect)
from h2g.patterns import (CMD_SETAD, CMD_SETSR, CMD_SETWAVE, GT_KEYOFF,
                          GT_NO_NOTE, ONE_SHOT_COMMANDS, TEMPO_OVERWRITABLE,
                          _build_raw_pattern)
from h2g.search import search_file
from h2g.sidfile import load_sid

CORPUS = r"C:/Users/mit/claude/c64server/SIDM2/SID/Hubbard_Rob"


# --- the probe --------------------------------------------------------------

# ACE_II $E157, the whole branch. `DEC` the gate mask, load the voice offset,
# zero SR then AD, then park $08 in the stored waveform.
ACE_II_BRANCH = bytes.fromhex("DE53E9AC4FE5A9009906D49905D4A9084CBDE1")
# Ricochet $914A: the same routine, jumping with the $00 still in A.
RICOCHET_BRANCH = bytes.fromhex("DE5F96AC2896A9009906D49905D44CBD91")
# IK+ $E135: the same again, written to the player's SHADOW SID -- $E5E3 is
# its $D400, so its pair is $E5E9/$E5E8.
IK_PLUS_BRANCH = bytes.fromhex("DEE0E5AC3FE5A90099E9E599E8E5A9084C9BE1")


def _with_branch(branch: bytes) -> bytes:
    """A file whose STATUS_BIT6_SHAPE match branches straight to `branch`.

    The shape ends on the BVS opcode, so the byte after it is the relative
    operand the probe follows; 0 lands on the next byte.
    """
    # Two leading pad bytes: search_file never tests offset 0 (it reproduces
    # VB's SSearchfile), so a shape at the very start of the buffer reads as
    # absent and every assertion below would pass for the wrong reason.
    shape = (b"\x00\x00"
             + bytes.fromhex("B1FA9D00108D0011291F9D0210" "2C0011" "70"))
    assert search_file(shape, STATUS_BIT6_SHAPE) >= 1, "the fixture must match"
    return shape + b"\x00" + branch


@pytest.mark.parametrize("branch,name", [
    (ACE_II_BRANCH, "ACE_II $E157"),
    (RICOCHET_BRANCH, "Ricochet $914A"),
    (IK_PLUS_BRANCH, "IK+ $E135 (shadow SID)"),
])
def test_the_three_spellings_of_one_routine_are_all_read(branch, name):
    assert _find_rest_silence_envelope(_with_branch(branch)), name


def test_the_two_stores_must_be_consecutive_and_descending():
    """SR before AD, one byte apart -- the order all 21 write them in.

    Two stores to unrelated cells after a `LDA #$00` are not this routine, and
    matching them would let any zeroing loop in a branch claim it.
    """
    apart = bytes.fromhex("A9009906D49900D4")
    assert not _find_rest_silence_envelope(_with_branch(apart))
    ascending = bytes.fromhex("A9009905D49906D4")
    assert not _find_rest_silence_envelope(_with_branch(ascending))
    other_page = bytes.fromhex("A9009906D49905D5")
    assert not _find_rest_silence_envelope(_with_branch(other_page))


def test_the_zeroing_is_required_not_just_the_stores():
    no_zero = bytes.fromhex("A90F9906D49905D4")
    assert not _find_rest_silence_envelope(_with_branch(no_zero))


def test_a_player_without_the_bit6_shape_reads_nothing():
    assert not _find_rest_silence_envelope(b"\x00" * 64 + ACE_II_BRANCH)


# --- the corpus -------------------------------------------------------------

_corpus = sorted(glob.glob(os.path.join(CORPUS, "*.sid")))


@pytest.mark.skipif(not _corpus, reason="corpus not present")
def test_it_is_exactly_the_files_that_silence_on_a_rest():
    """21 files, and the same 21 `rest_silences` names.

    The two probes read the same branch and were derived independently -- one
    off the parked waveform, one off the envelope stores -- so their agreeing
    on every file is the check that they describe one routine rather than two.
    Any disagreement means a player has been found that does one and not the
    other, which is a finding and not a test to relax.
    """
    silences, envelope = set(), set()
    for path in _corpus:
        try:
            det = detect(load_sid(path), lambda m: None)
        except Exception:                       # noqa: BLE001 -- not our subject
            continue
        name = os.path.basename(path)
        if det.rest_silences:
            silences.add(name)
        if det.rest_silence_envelope:
            envelope.add(name)
    assert len(envelope) == 21, sorted(envelope)
    assert envelope == silences, sorted(envelope ^ silences)


@pytest.mark.skipif(not _corpus, reason="corpus not present")
def test_it_is_disjoint_from_the_note_end_cut():
    """No file has both, which is what makes them two mechanisms.

    `--cut-release` zeroes the release nibble in the instrument, which is
    right only where the player cuts at EVERY note end. These 21 cut at the
    rest alone, so their ordinary note ends do sound the release and zeroing
    the nibble would destroy it.
    """
    for path in _corpus:
        try:
            det = detect(load_sid(path), lambda m: None)
        except Exception:                       # noqa: BLE001
            continue
        assert not (det.rest_silence_envelope and det.envelope_cut), path


# --- what it emits ----------------------------------------------------------

def _decode(status_bytes, **kw):
    data = bytes([0x00, 0x00]) + bytes(status_bytes) + bytes([0xFF])
    return _build_raw_pattern(data, 2, status_bit6=True, **kw)


def _rows(events):
    return [tuple(events[k:k + 4]) for k in range(0, len(events), 4)]


def test_the_rest_writes_the_sr_on_its_own_row_and_the_ad_on_the_next():
    """$42: bit 6 set, `wait` 2 -- the row itself plus two hold rows."""
    rows = _rows(_decode([0x42], rest_keyoff=True, rest_envelope=True))
    assert rows[0] == (GT_KEYOFF, 0, CMD_SETSR, 0x00)
    assert rows[1] == (GT_NO_NOTE, 0, CMD_SETAD, 0x00), "AD on hold row 1"
    assert rows[2] == (GT_NO_NOTE, 0, 0, 0), "and nothing after it"


def test_a_one_frame_rest_keeps_the_audible_half():
    """`wait` 0 has no hold row, so the AD is dropped rather than displacing
    the SR. Only the SR is audible: $D405 shapes a rising envelope and the
    gate is off for the whole rest."""
    rows = _rows(_decode([0x40], rest_keyoff=True, rest_envelope=True))
    assert rows[0] == (GT_KEYOFF, 0, CMD_SETSR, 0x00)
    assert rows[1][0] == 0xFF, "no hold row to carry the AD"


def test_it_is_off_by_default():
    rows = _rows(_decode([0x42], rest_keyoff=True))
    assert rows[0] == (GT_KEYOFF, 0, 0, 0)
    assert rows[1] == (GT_NO_NOTE, 0, 0, 0)


def test_it_declines_without_the_keyoff():
    """A sustain of 0 on a voice whose gate is still open silences a note that
    should still be sounding -- the opposite defect. The player clears the
    gate on the same call it zeroes the pair, so the two go together."""
    rows = _rows(_decode([0x42], rest_keyoff=False, rest_envelope=True))
    assert rows[0][2] == 0, rows[0]
    assert rows[1][2] == 0, rows[1]


def test_the_wave_silence_option_still_owns_the_column_where_both_are_asked():
    rows = _rows(_decode([0x42], rest_keyoff=True, rest_wave=True,
                         rest_envelope=True))
    assert rows[0][2] == CMD_SETWAVE
    # The command is cleared for the hold rows and the data byte is not,
    # which is how every ONE_SHOT_COMMANDS row has always been written --
    # command 0 ignores its operand (gplay.c:415-418). What matters here is
    # that no CMD_SETAD is smuggled onto the row behind the wave option.
    assert rows[1][:3] == (GT_NO_NOTE, 0, 0), rows[1]


def test_a_note_event_is_untouched():
    """Bit 6 clear: an ordinary note, and nothing here may reach it."""
    rows = _rows(_decode([0x82, 0x00, 0x10], rest_keyoff=True,
                         rest_envelope=True))
    assert rows[0][2] == 0, rows[0]
    assert all(r[2] == 0 for r in rows[1:3]), rows


# --- the interaction that broke it first ------------------------------------

def test_the_new_commands_act_once_and_yield_to_a_subtune_tempo():
    """Both halves of the trap this change fell into.

    `CMD_SETSR` must not repeat down the hold rows (§ 7.ppppp: 673 command
    bytes written where 61 were designed), and it must not block the
    `CMD_SETTEMPO` a subtune writes into row 0 of its entry pattern --
    `apply_tempo`/`apply_tempos` SKIP a pattern whose command column is taken,
    so a rest at row 0 silently costs the subtune its clock and it plays at
    Goattracker's default 6. Measured: without the `TEMPO_OVERWRITABLE` entry
    this change moved `drift` from 0.00 to 1250 on ACE_II and cost a mean 47pp
    of melody over 12 of 19 files.
    """
    assert CMD_SETSR in ONE_SHOT_COMMANDS
    assert CMD_SETSR in TEMPO_OVERWRITABLE
    assert CMD_SETWAVE in TEMPO_OVERWRITABLE and 0 in TEMPO_OVERWRITABLE


def test_the_tempo_write_takes_a_rest_row_back():
    from h2g.goatwriter import CMD_SETTEMPO
    from h2g.patterns import apply_tempo
    pattern = [GT_KEYOFF, 0, CMD_SETSR, 0x00, 0xFF, 0, 0, 0]
    patterns = [pattern]
    tracks = [[0, 0xFF, 0], [0, 0xFF, 0], [0, 0xFF, 0]]
    apply_tempo(patterns, tracks, 6)
    assert pattern[2] == CMD_SETTEMPO and pattern[3] == 6
