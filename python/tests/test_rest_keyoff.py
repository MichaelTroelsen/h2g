"""The bit-6 rest, and the 21 players that silence on it.

`status_bit6` has been read since v0.5.x: a status byte of `$C0`-`$FE`
consumes only itself, because the player tests bit 6 first and alone
(`BIT status / BVS`). What was never read is *what the branch does*. Our
decoder emits a hold row, which sustains the note that was playing.

Three different things happen at that branch target across the 61 corpus
files with the shape:

    5118  DEC .. / LDY voice / LDA instr,X / ...      Commando, 40 files
    914A  DEC .. / LDY voice / LDA #$00 / STA $D406,Y / STA $D405,Y
                                                       Ricochet, 4 files
    E138  LDY voice / LDA #$00 / STA / STA / LDA #$08 / JMP store
                                                       IK+, 17 files

The first holds -- it goes on to the effect path and writes no register. The
second zeroes the envelope pair; the third writes the testbit into the stored
waveform. Both of those stop the sound, and `KEYOFF` is the only row
Goattracker has that ends a note without starting one.

**No column of FIDELITY.md can see this.** A KEYOFF clears the gate and
nothing else, and `wave` ignores the gate bit by construction while `hold`
counts frames with a waveform *selected* -- which a gate-off does not change.
Measured on the one axis that can see it, frames where the original has the
voice gated off and we do not: IK+ voice 1 330 -> 141, Arcade Classics voice 1
250 -> 89. That is why the option is off by default and in
`presets.EXCLUDED_FROM_ALWAYS`: it is a reading, not a scored improvement.
"""
import pathlib
import sys

from corpus import CORPUS, needs_corpus  # noqa: E402

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[1]))

from h2g.convert import _detect_tables, convert  # noqa: E402
from h2g.detect import (STATUS_BIT6_SHAPE, _find_rest_silences,  # noqa: E402
                        _find_status_bit6)
from h2g.patterns import GT_KEYOFF, GT_NO_NOTE, _build_raw_pattern  # noqa: E402
from h2g.search import search_file  # noqa: E402
from h2g.sidfile import load_sid  # noqa: E402

COMMANDO = pathlib.Path(__file__).resolve().parents[2] / "Commando.sid"


def _bytes_for(target: bytes) -> bytes:
    """A minimal player image: the shape, then `target` at the BVS's landing."""
    shape = bytes([0xB1, 0x42, 0x9D, 0x49, 0xE5, 0x8D, 0xF8, 0xE5,
                   0x29, 0x1F, 0x9D, 0x46, 0xE5, 0x2C, 0xF8, 0xE5, 0x70])
    # search_file never tests offset 0, so the image needs a leading byte.
    return b"\x00" + shape + bytes([0x02, 0xEA, 0xEA]) + target


def test_a_branch_that_writes_no_register_is_a_hold():
    """Commando's: straight on to the effect path."""
    target = bytes([0xCE, 0x01, 0x55, 0xAC, 0xEB, 0x54, 0xBD, 0xFE, 0x54])
    assert not _find_rest_silences(_bytes_for(target))


def test_the_testbit_load_is_a_silence():
    target = bytes([0xAC, 0x3F, 0xE5, 0xA9, 0x00, 0x99, 0xE9, 0xE5,
                    0x99, 0xE8, 0xE5, 0xA9, 0x08, 0x4C, 0x9B, 0xE1])
    assert _find_rest_silences(_bytes_for(target))


def test_zeroing_the_envelope_pair_is_a_silence():
    target = bytes([0xAC, 0x28, 0x96, 0xA9, 0x00,
                    0x99, 0x06, 0xD4, 0x99, 0x05, 0xD4])
    assert _find_rest_silences(_bytes_for(target))


def test_a_zero_that_goes_somewhere_else_is_not():
    """`LDA #$00` alone says nothing; it must reach $D405/$D406."""
    target = bytes([0xAC, 0x28, 0x96, 0xA9, 0x00, 0x9D, 0x06, 0x96])
    assert not _find_rest_silences(_bytes_for(target))


def test_a_file_without_the_shape_is_never_flagged():
    assert not _find_rest_silences(b"\x00" * 64)


# --- the corpus split ------------------------------------------------------

@needs_corpus
def test_the_corpus_splits_into_holders_and_silencers():
    holds, silences = [], []
    for path in sorted(CORPUS.glob("*.sid")):
        data = load_sid(str(path)).data
        if not _find_status_bit6(data):
            continue
        (silences if _find_rest_silences(data) else holds).append(path.name)
    # 61 files carry the shape; the split is 40/21 and Commando is a holder.
    assert len(holds) + len(silences) == 61
    assert len(silences) == 21
    assert "Commando.sid" in holds
    assert "IK_plus.sid" in silences and "Ricochet.sid" in silences


@needs_corpus
def test_the_fixture_is_a_holder_so_its_bytes_cannot_move():
    """Commando is the byte-exact anchor and must be blind to this option."""
    plain = convert(str(COMMANDO), log=lambda *a, **k: None)
    assert plain == convert(str(COMMANDO), log=lambda *a, **k: None,
                            rest_keyoff=True)


# --- what it emits ---------------------------------------------------------

def _rows(events):
    return [tuple(events[i:i + 4]) for i in range(0, len(events), 4)]


def test_a_bit_6_event_becomes_a_keyoff_row():
    # status $C2 -> bit 6 set, wait 2; then a note event; then $FF.
    data = bytes([0x00, 0x00, 0xC2, 0x02, 0x10, 0xFF, 0x00, 0x00])
    off = _build_raw_pattern(data, 2, status_bit6=True)
    on = _build_raw_pattern(data, 2, status_bit6=True, rest_keyoff=True)
    assert _rows(off)[0][0] == GT_NO_NOTE
    assert _rows(on)[0][0] == GT_KEYOFF
    # The instrument column goes with it: the event read no operand, so any
    # number there is the previous event's and would re-latch it.
    assert _rows(on)[0][1] == 0
    # Its wait rows stay holds -- the note ends once, not on every frame.
    assert [r[0] for r in _rows(on)[1:3]] == [GT_NO_NOTE, GT_NO_NOTE]


def test_the_option_does_nothing_without_the_bit_6_shape():
    data = bytes([0x00, 0x00, 0xC2, 0x02, 0x10, 0xFF, 0x00, 0x00])
    assert (_build_raw_pattern(data, 2, status_bit6=False)
            == _build_raw_pattern(data, 2, status_bit6=False,
                                  rest_keyoff=True))


def test_an_event_that_carries_a_note_is_untouched():
    data = bytes([0x00, 0x00, 0x02, 0x10, 0xFF, 0x00, 0x00])
    on = _build_raw_pattern(data, 2, status_bit6=True, rest_keyoff=True)
    assert _rows(on)[0][0] not in (GT_KEYOFF,)


@needs_corpus
def test_it_reaches_only_the_files_whose_rest_silences():
    """A reading gated on the player must not move a player it does not fit."""
    moved, flagged = [], []
    for name in ("IK_plus", "Ricochet", "Commando", "Warhawk", "Delta"):
        path = CORPUS / f"{name}.sid"
        if not path.exists():
            continue
        data = load_sid(str(path)).data
        if _find_rest_silences(data):
            flagged.append(name)
        try:
            a = convert(str(path), log=lambda *x, **k: None, effects=True,
                        status_bit6=True)
            b = convert(str(path), log=lambda *x, **k: None, effects=True,
                        status_bit6=True, rest_keyoff=True)
        except Exception:
            continue
        if a != b:
            moved.append(name)
    assert set(moved) <= set(flagged)
    assert "IK_plus" in moved
