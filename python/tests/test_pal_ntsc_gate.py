"""A gate table indexed by the PAL/NTSC flag, not by the subtune.

Both gate readers assume the `LDA table,X` feeding a reload cell has the
subtune number in X, because in 82 of the 83 convertible files it does. Skate
or Die intro's init puts the KERNAL's territory flag there instead:

    $3FE0  LDX $02A6        ; 0 = NTSC
    $3FE3  LDA $3FDA,X      ; 7F 04  -- the outer gate's skip
    $3FE6  STA $45DD
    $3FE9  STA $4B14
    $3FEC  LDA $3FDC,X
    $3FEF  STA $4801
    $3FF2  LDA $3FDE,X      ; 02 01  -- the inner gate's reload
    $3FF5  STA $4B13

Reading entry 0 gave NTSC's 127 and 2, so the row came out 384/127 = 3.024
frames; MAX_ROW_DENOMINATOR refuses a denominator of 127 and it fell back to a
flat 3. `--pace` measured that as a ratio of exactly 1.200 with an IQR of
1.200-1.200 over 826 gaps -- the signature CLAUDE.md names for a wrong
constant rather than a mechanism. PAL's entries are 4 and 1, so the row is
2 x 5/4 = 5/2 = 2.50 frames, which packs exactly as tempo 5 at `-S2`.

This file could not have been reached by the v0.5.402 rescue spellings: it
installs its own IRQ, so its PSID header names no play routine, and those are
anchored at the play address and correctly decline.

CLAUDE.md carried "one gate picks its reload from the PAL/NTSC flag" as a
STANDING HYPOTHESIS for this exact file, found real in Las Vegas first. It was
right.
"""
import pathlib
import sys

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[1]))

from corpus import CORPUS, needs_corpus                        # noqa: E402

from h2g.convert import _detect_tables                         # noqa: E402
from h2g.goatwriter import (PAL_NTSC_ENTRY, _pal_ntsc_indexed,  # noqa: E402
                            effective_frames, find_song_speeds,
                            recommended_multiplier)
from h2g.sidfile import load_sid                               # noqa: E402

LDX_PAL = b"\xae\xa6\x02"          # LDX $02A6
LDA_ABS_X = b"\xbd\xde\x3f"        # LDA $3FDE,X


def test_a_load_right_after_the_flag_is_territory_indexed():
    data = b"\x00" * 8 + LDX_PAL + LDA_ABS_X
    assert _pal_ntsc_indexed(data, len(data) - 3)


def test_a_load_with_no_flag_nearby_is_subtune_indexed():
    data = b"\x00" * 8 + b"\xa2\x00" + LDA_ABS_X       # LDX #$00
    assert not _pal_ntsc_indexed(data, len(data) - 3)


def test_an_intervening_ldx_breaks_the_chain():
    """X reloaded between the flag and the load means X is no longer it."""
    data = b"\x00" * 4 + LDX_PAL + b"\xa2\x03" + LDA_ABS_X    # LDX #$03
    assert not _pal_ntsc_indexed(data, len(data) - 3)


def test_the_flag_must_be_inside_the_window():
    data = LDX_PAL + b"\xea" * 40 + LDA_ABS_X
    assert not _pal_ntsc_indexed(data, len(data) - 3)


def test_the_pal_entry_is_the_second_one():
    """0 is NTSC; this corpus is PAL and is compared against a 50 Hz trace."""
    assert PAL_NTSC_ENTRY == 1


@needs_corpus
def test_skate_or_die_intros_row_is_five_halves():
    sid = load_sid(str(CORPUS / "Skate_or_Die_intro.sid"))
    # The precondition that makes this file unreachable any other way.
    assert not sid.play_addr, "header names a play routine; premise changed"
    s2, det = _detect_tables(sid, lambda m: None)
    sp = find_song_speeds(s2, det)
    assert sp.frames == (2,), sp.frames          # NTSC would give (3,)
    assert sp.skip == (4,), sp.skip              # NTSC would give (127,)
    from fractions import Fraction
    assert sp.exact_row(0) == Fraction(5, 2)     # NTSC gave 384/127
    assert effective_frames(sp, 0, True) == Fraction(5, 2)
    assert recommended_multiplier(sp, 0, True) == 2


@needs_corpus
def test_no_other_corpus_file_is_territory_indexed():
    """The reach is one file, and a widening of the window would show here."""
    import re
    hit = []
    for p in sorted(CORPUS.glob("*.sid")):
        try:
            sid = load_sid(str(p))
            s2, det = _detect_tables(sid, lambda m: None)
            sp = find_song_speeds(s2, det)
        except Exception:                                      # noqa: BLE001
            continue
        if sp is None:
            continue
        for addr in (sp.table_addr, sp.skip_table_addr):
            if not addr:
                continue
            want = bytes([0xBD, addr & 0xFF, addr >> 8])
            if any(_pal_ntsc_indexed(s2.data, m.start())
                   for m in re.finditer(re.escape(want), s2.data)):
                hit.append(p.name)
                break
    assert hit == ["Skate_or_Die_intro.sid"], hit
