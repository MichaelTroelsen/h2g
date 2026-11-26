"""Delta's filter, which `find_filter` refused for want of one `ADC`.

Delta $C1A1 is `FILTER_SHAPE` with `ADC base,X` between the accumulator's
store and the $D416 write (`detect.FILTER_SHAPE_ADDEND`). Its subtune 13 (page
`Delta_13`) filters 8997 of 9000 original frames at `-t 180` and ours filtered
none: `band` / `res` / `route` 0, `cut` 0.00x, `cfrm` 0. Read, they measured
(Delta_13, v0.5.674 base -> this change) band 0 -> 100%, res and route 0 ->
100%, cut 0 -> 0.43x, cfrm 0 -> 0.14, aud .9466 -> .9469.

The second term is NOT modelled (a per-voice accumulator on its own clock,
wrapping every 720 frames); `FILTER_ADDEND_CENTRE` stands in for it. Left at
$00 the filter sat far below the original's for most of the tune and aud fell
.9466 -> .9093, which is why the centre is part of the reading and not an
afterthought.
"""
import pytest

from corpus import CORPUS, needs_corpus
from h2g.detect import (FILTER_ADDEND_CENTRE, FILTER_SHAPE, FILTER_SHAPE_ADDEND,
                        FILTER_SHAPE_CLAMP, detect)
from h2g.goatwriter import (FILT_SET_CUTOFF, FILT_SET_PARAMS, FILT_STOP,
                            _filter_entries, _filter_step_per_call)
from h2g.search import search_file
from h2g.sidfile import load_sid


def _det(stem):
    sid = load_sid(str(CORPUS / f"{stem}.sid"))
    return sid, detect(sid, lambda m: None)


# Delta $C1A1..$C1BB, bytes as the player has them.
BODY = ("AD 3B C3 29 20 F0 16 BD 4E C3 18 79 45 C4 9D 4E C3 {mid}"
        "8D 16 D4 B9 44 C4 8D 17 D4")


def test_the_addend_spelling_is_its_own_shape():
    """SABOTAGE TARGET: drop the `7D ?? ??` from FILTER_SHAPE_ADDEND and the
    plain shape would have to match it; widen FILTER_SHAPE past the store and
    the plain shape starts claiming Delta. Each spelling reads only its own."""
    blob = bytes.fromhex("EA " * 4 + BODY.format(mid="7D 4B C3 "))
    plain = bytes.fromhex("EA " * 4 + BODY.format(mid=""))
    assert search_file(blob, FILTER_SHAPE_ADDEND) == 4
    assert search_file(blob, FILTER_SHAPE) <= -1
    assert search_file(blob, FILTER_SHAPE_CLAMP) <= -1
    assert search_file(plain, FILTER_SHAPE) == 4
    assert search_file(plain, FILTER_SHAPE_ADDEND) <= -1


@needs_corpus
def test_the_addend_reading_reaches_exactly_delta():
    """SABOTAGE TARGET: delete the FILTER_SHAPE_ADDEND branch from
    `find_filter` and the set comes back empty. It is consulted only where
    the primary and clamp spellings found nothing, so no other file moves."""
    reached = set()
    for p in sorted(CORPUS.glob("*.sid")):
        try:
            sid, det = _det(p.stem)
        except Exception:                                   # noqa: BLE001
            continue
        if det.filter is not None and det.filter.addend:
            reached.add(p.stem)
        if search_file(sid.data, FILTER_SHAPE_ADDEND) > -1:
            assert search_file(sid.data, FILTER_SHAPE) <= -1, p.stem
    assert reached == {"Delta"}, reached


@needs_corpus
def test_delta_reads_as_a_centred_classic_sweep():
    _sid, det = _det("Delta")
    f = det.filter
    assert f is not None and det.ilv_filter is None
    assert f.addr == 0xC444           # resctl sits after the 7D, not at +21
    assert f.addend == 0xC34B         # the `ADC base,X` operand
    assert (f.passband, f.clamp, f.free_running) == (0x10, False, False)
    assert f.cutoff == FILTER_ADDEND_CENTRE   # the player's own start is $00


@needs_corpus
def test_delta_emits_a_filter_program_from_the_centre():
    """The emission, so the reading is not only a detection: the one record
    that enables the filter gets a block that starts the sweep from the
    centre, `multiplier` calls after the strike (`_classic_sweep_block`)."""
    sid, det = _det("Delta")
    entries, ptrs = _filter_entries(sid, det, det.instr_used, multiplier=2)
    assert entries and ptrs
    sets = {right for left, right in entries if left == FILT_SET_CUTOFF}
    assert sets, entries
    # every swept block opens at centre + one frame's step (`multiplier`
    # calls of the per-call step), whatever that record's step is
    f = det.filter
    want = set()
    for i in range(det.instr_used - 1):
        if sid.data[f.status + i * det.instr_stride] & 0x20:
            step = sid.data[f.offset + i * det.instr_stride + 1]
            want.add((FILTER_ADDEND_CENTRE
                      + _filter_step_per_call(step, 2) * 2) & 0xFF)
    assert sets <= want, (sets, want)
    assert (FILTER_ADDEND_CENTRE + 2) & 0xFF in sets   # the +2 a frame record
    assert any(left == FILT_SET_PARAMS | 0x10 for left, _ in entries)
    assert any(left == FILT_STOP for left, _ in entries)


@needs_corpus
def test_no_other_delta_row_reads_a_different_filter():
    """Delta_Mix-E-Load_loader shares the name and not the routine."""
    _sid, det = _det("Delta_Mix-E-Load_loader")
    assert det.filter is None or not det.filter.addend

