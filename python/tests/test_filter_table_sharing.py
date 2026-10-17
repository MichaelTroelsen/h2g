"""Classic filter records that write the same rows share one block.

Star_Paws (multiplier 2) has 13 classic filter records. Each wrote its own
block of 6 rows (three params rows for the strike hold, the set-cutoff, the
sweep, the stop), so the table of 64 rows held 10 of them and the other three
never got a pointer; sized to the gaps the table needed 88 rows, so every size
was thrown away and each sweep ran one $7F row (127 calls, 64 frames) where
the player runs 95 (two 64/31-step legs across the 8-frame strikes of two
other voices). `cutoff_sweep` read 0.790 (ours/original travel).

Now (`filters._fit_sized_sweeps`): a record whose block equals an earlier
record's takes that block's pointer; a record whose every gap ends on a
filtered strike (`SweepLengths.free`) sweeps as well at any length from its
longest gap up, so the free records of one program share the group's longest
sweep (`_lift_free_sweeps`); where the table is still over, the sizes that
cost rows are given back, costliest first.

Measured at 7e8c58d, presets, -t 180: only Star_Paws moves under a corpus
byte-hash (89 compared); `cutoff_sweep` 0.7898 -> 0.9707 (travel 21,963,776 ->
26,994,688 against the original's 27,811,584), aud .8983 -> .8986.
"""
import json
import pathlib

import pytest

from corpus import CORPUS, needs_corpus
from h2g.detect import detect
from h2g.goatwriter import (GT_MAX_FILT, MAX_INSTRUMENTS, SweepLengths,
                            _filter_entries, _filter_entries_once,
                            _fit_sized_sweeps, _lift_free_sweeps)
from h2g.sidfile import load_sid

REPO = pathlib.Path(__file__).resolve().parents[2]
PYTHON = REPO / "python"


def _det(stem="Star_Paws"):
    sid = load_sid(str(CORPUS / f"{stem}.sid"))
    det = detect(sid, lambda m: None)
    return sid, det, min(det.instr_used + 1, MAX_INSTRUMENTS)


def _blocks(entries, ptrs):
    """{pointer: rows up to the block's FILT_STOP}"""
    out = {}
    for ptr in set(ptrs.values()):
        rows = []
        for row in entries[ptr - 1:]:
            rows.append(row)
            if row[0] == 0xFF:
                break
        out[ptr] = rows
    return out


@needs_corpus
def test_every_star_paws_record_gets_a_pointer_in_the_unsized_table():
    """SABOTAGE TARGET: `share=True` -> `False` in `_fit_sized_sweeps`' build
    and the 13 records need 78 of 64 rows: three have no pointer."""
    sid, det, n = _det()
    plain_once, once_ptrs, over = _filter_entries_once(sid, det, n, 1, 2,
                                                       None, None, None)
    assert over and len(once_ptrs) == 10        # the old table
    entries, ptrs = _filter_entries(sid, det, n, multiplier=2)
    assert len(ptrs) == 13 and len(entries) <= GT_MAX_FILT
    assert len(set(ptrs.values())) == 5         # five distinct programs


@needs_corpus
def test_records_with_equal_blocks_share_a_pointer_and_unequal_do_not():
    sid, det, n = _det()
    entries, ptrs = _filter_entries(sid, det, n, multiplier=2)
    seen = {}
    for rec, ptr in ptrs.items():
        key = tuple(_blocks(entries, ptrs)[ptr])
        assert seen.setdefault(key, ptr) == ptr


@needs_corpus
def test_free_records_of_one_program_share_the_longest_sweep():
    """SABOTAGE TARGET: `_lift_free_sweeps` returning `sizes` unchanged:
    the sized table then needs 88 rows and gives back the sizes it can."""
    sid, det, n = _det()
    sizes = SweepLengths({3: 192, 5: 256, 7: 112, 8: 256, 9: 80, 10: 8,
                          11: 128, 12: 96, 13: 8, 14: 952, 17: 128, 15: 96,
                          18: 88})
    sizes.free.update(sizes)
    lifted = _lift_free_sweeps(sid, det, n, 1, 2, None, None, dict(sizes),
                               sizes.free)
    assert lifted[3] == lifted[5] == 256                 # one program
    assert lifted[7] == lifted[12] == 112
    assert lifted[8] == lifted[9] == lifted[11] == 256
    assert lifted[10] == lifted[13] == lifted[14] == 952
    assert lifted[18] == 88                              # alone in its program
    entries, ptrs = _fit_sized_sweeps(sid, det, n, 1, 2, None, None, sizes)
    assert len(entries) <= GT_MAX_FILT
    # all sizes kept: the long record has its eight $7F rows
    assert sum(1 for left, _ in entries if left == 0x7F) >= 8


@needs_corpus
def test_sizes_that_do_not_fit_are_given_back_costliest_first_not_all_at_once():
    """No record is `free` here, so nothing is lifted and the 88 rows must be
    cut down. SABOTAGE TARGET: replace the `del sizes[...]` in
    `_fit_sized_sweeps` with `sizes = None` (every size thrown away, the old
    behaviour): no record keeps a second $7F row."""
    sid, det, n = _det()
    sizes = {3: 192, 5: 256, 7: 112, 8: 256, 9: 80, 10: 8, 11: 128, 12: 96,
             13: 8, 14: 952, 17: 128, 15: 96, 18: 88}
    entries, ptrs = _fit_sized_sweeps(sid, det, n, 1, 2, None, None, sizes)
    assert len(entries) <= GT_MAX_FILT and len(ptrs) == 13
    # 952 (eight rows) went first; a short size (record 10's 8 calls) stays
    assert not any(len(b) > 9 for b in _blocks(entries, ptrs).values())
    assert (6, 0xF8) in entries or any(
        left == 0x06 for left, _ in entries)         # 8 calls - 2 = 6 kept


@needs_corpus
def test_a_record_with_a_stop_gap_is_not_lifted():
    """SABOTAGE TARGET: lift every record, not only `free` ones."""
    sid, det, n = _det()
    sizes = {3: 192, 5: 256, 8: 256, 9: 80}
    lifted = _lift_free_sweeps(sid, det, n, 1, 2, None, None, dict(sizes),
                               {3, 5})            # 8 and 9 end on a stop
    assert lifted[3] == lifted[5] == 256
    assert lifted[8] == 256 and lifted[9] == 80


@needs_corpus
def test_a_plain_dict_of_sizes_is_never_lifted():
    """A caller with no `SweepLengths` (the unit tests, other tools) gets the
    sizes it gave, so only `classic_filter_stops` opts in."""
    sid, det, n = _det()
    entries, ptrs = _filter_entries(sid, det, n, multiplier=2,
                                    sweep_calls={3: 192, 5: 256})
    assert len(entries) <= GT_MAX_FILT and len(ptrs) == 13


@needs_corpus
def test_a_table_that_fits_is_built_as_before():
    """Share only on overflow: Sanxion's table is byte-identical to the one
    `share=False` builds."""
    sid, det, n = _det("Sanxion")
    sized = {1: 12}
    a, pa = _filter_entries(sid, det, n, multiplier=1, sweep_calls=sized)
    b, pb, over = _filter_entries_once(sid, det, n, 1, 1, None, None, sized)
    assert not over and (a, pa) == (b, pb)


try:
    import fidelity
except Exception:                                   # pragma: no cover
    fidelity = None
needs_siddump = pytest.mark.skipif(
    fidelity is None or not pathlib.Path(fidelity.SIDDUMP).exists(),
    reason="no siddump on this machine (tools/siddump-rt, see its README)")
needs_gt2reloc = pytest.mark.skipif(
    fidelity is None or not pathlib.Path(fidelity.GT2RELOC).exists(),
    reason="no gt2reloc on this machine")


@needs_corpus
@needs_siddump
@needs_gt2reloc
def test_star_paws_cutoff_travel_is_the_originals():
    """Measured: ours/original cutoff travel 0.790 -> 0.971 (-t 180, presets).
    SABOTAGE TARGET: any mutation of the sharing or the lift reads <= 0.82."""
    import shutil
    import types
    doc = json.loads((REPO / "presets.json").read_text("utf-8"))
    opts = fidelity._preset_opts(doc, "Star_Paws.sid")
    mult = fidelity._preset_multiplier(doc, "Star_Paws.sid")
    args = types.SimpleNamespace(
        seconds=60, subtune="auto", label=None, search_subtunes=3,
        siddump=fidelity.SIDDUMP, gt2reloc=fidelity.GT2RELOC, register=False,
        audio=False, length_probe=1, vice=False, sound=False)
    work, owned = fidelity.make_workdir()
    try:
        row = fidelity.measure(CORPUS / "Star_Paws.sid", work, opts, args, mult)
    finally:
        if owned:
            shutil.rmtree(work, ignore_errors=True)
    assert row["status"] == "measured", row.get("detail")
    assert 0.88 < row["cutoff_sweep"] < 1.08, row["cutoff_sweep"]
