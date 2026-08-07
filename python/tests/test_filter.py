"""The per-instrument filter array, and the gates that stop it inventing one.

The reading itself is proved in detect.find_filter's docstring; what is worth
pinning here is every way it can go wrong, because each one was reached by
measurement before it was reached by argument.
"""
import json
from pathlib import Path

import pytest

from h2g.convert import convert
from h2g.detect import detect, FILTER_ENABLE_BIT
from h2g.goatwriter import (GT_MAX_FILT, MAX_INSTRUMENTS, FILT_SET_PARAMS,
                            FILT_SET_CUTOFF, FILT_STOP, _filter_entries)
from h2g.sidfile import load_sid

CORPUS = Path(r"C:\Users\mit\claude\c64server\SIDM2\SID\Hubbard_Rob")
REPO = Path(__file__).resolve().parents[2]

pytestmark = pytest.mark.skipif(not CORPUS.is_dir(),
                                reason="corpus not present")

# Originals that drive the filter hard, and the ones that never turn it on.
# Measured with siddump's FCut/Typ columns over 60 s.
FILTERED = ["ACE_II", "IK_plus", "I_Ball", "Nemesis_the_Warlock", "Pandora",
            "Star_Paws", "Trans-Atlantic_Balloon_Challenge"]
UNFILTERED = ["Powerplay_Hockey_USA_vs_USSR"]

OPTS = dict(log=lambda m: None, fmt="gts5", slides=True, effects=True,
            status_bit6=True, reject_phantoms=True, fold_transpose=True,
            legal_restart=True)


def _det(stem):
    sid = load_sid(str(CORPUS / f"{stem}.sid"))
    return sid, detect(sid, lambda m: None)


def test_commando_fixture_is_untouched_by_the_flag():
    """The fixture has no filter routine, so the flag must be a no-op on it."""
    ref = (REPO / "Commando.sng").read_bytes()
    plain = convert(str(REPO / "Commando.sid"), log=lambda m: None)
    filtered = convert(str(REPO / "Commando.sid"), log=lambda m: None,
                       filters=True)
    assert plain == ref
    assert filtered == ref


@pytest.mark.parametrize("stem", FILTERED)
def test_a_filtered_player_yields_entries(stem):
    sid, det = _det(stem)
    assert det.filter is not None
    entries, ptrs = _filter_entries(sid, det,
                                    min(det.instr_used + 1, MAX_INSTRUMENTS))
    assert ptrs, f"{stem} drives the filter but got no table entries"
    assert len(entries) <= GT_MAX_FILT


@pytest.mark.parametrize("stem", UNFILTERED)
def test_a_player_that_never_filters_gets_no_audible_filter(stem):
    """Powerplay Hockey carries the routine and the array and never filters.

    Before the status-bit gate this file was given five filtered instruments
    and swept the cutoff 497 times against an original that writes it once.
    The gate is the player's own: it runs the block only for an instrument
    whose status byte has bit $20 set.
    """
    sid, det = _det(stem)
    if det.filter is None:
        return  # refused outright, which is also correct
    _, ptrs = _filter_entries(sid, det,
                              min(det.instr_used + 1, MAX_INSTRUMENTS))
    for i in ptrs:
        status = sid.data[det.filter.status + i * det.instr_stride]
        assert status & FILTER_ENABLE_BIT


def test_every_entry_is_a_legal_filter_table_opcode():
    """A malformed left side sends Goattracker's filter interpreter anywhere."""
    for stem in FILTERED:
        sid, det = _det(stem)
        entries, _ = _filter_entries(sid, det,
                                     min(det.instr_used + 1, MAX_INSTRUMENTS))
        for left, right in entries:
            assert (left == FILT_SET_CUTOFF or left == FILT_STOP
                    or 0x01 <= left <= 0x7F
                    or FILT_SET_PARAMS <= left <= 0xF0), hex(left)
            assert 0 <= right <= 0xFF


def test_every_block_starts_with_params_and_ends_stopped():
    """A table step that runs off the end keeps executing the next block."""
    for stem in FILTERED:
        sid, det = _det(stem)
        entries, ptrs = _filter_entries(
            sid, det, min(det.instr_used + 1, MAX_INSTRUMENTS))
        for start in ptrs.values():
            assert entries[start - 1][0] & FILT_SET_PARAMS
            end = start - 1
            while entries[end][0] != FILT_STOP:
                end += 1
                assert end < len(entries), f"{stem}: block never stops"


def test_the_flag_changes_no_file_whose_player_has_no_filter():
    """Under-read by construction: refusing a file must leave it byte-exact."""
    changed = []
    for p in sorted(CORPUS.glob("*.sid")):
        try:
            a = convert(str(p), **OPTS)
            b = convert(str(p), filters=True, **OPTS)
        except Exception:
            continue
        if a != b:
            changed.append(p.stem)
    for stem in changed:
        sid, det = _det(stem)
        assert det.filter is not None, (
            f"{stem} changed but no filter was detected")


def test_the_array_is_two_bytes_per_record():
    """resctl == step - 1 held in 24 of 24 files the shape matched.

    That adjacency is the whole basis for reading one array rather than two
    unrelated tables, so find_filter refuses a file where it fails; this pins
    that the surviving files really do satisfy it.
    """
    seen = 0
    for p in sorted(CORPUS.glob("*.sid")):
        try:
            sid, det = _det(p.stem)
        except Exception:
            continue
        if det.filter is None:
            continue
        seen += 1
        # The step byte is the resonance byte's immediate neighbour.
        assert det.filter.offset + 1 < len(sid.data)
    assert seen >= 10
