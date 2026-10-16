"""The entry split also serves pulse-only free-note records.

`build_sng` used to hand `entry_instrument_split` only the free-note rows
that could play a record WITH an attack, so a pattern entered holding two
pulse-only records declined "entered with two instruments" (Delta: 11 rows,
patterns $02/$03 entered holding records 0, 1 and 11). With the split
settling each copy on one instrument, the pulse-only variant's "channel
holds its own instrument" test passes. Measured at e16bddb under presets
(C:/t/free-note-split-pulse-only): Delta 39 -> 67 free rows on 4 -> 7
variants, 0 declines (was 11), 3 pattern copies; the only corpus file whose
bytes move. Knucklebusters' two rows were already settled by its existing
7-copy split (no entry decline left; 1 "follows another instrument").
"""
import json
import pathlib

from h2g.convert import convert

from corpus import CORPUS, needs_corpus

REPO_ROOT = pathlib.Path(__file__).resolve().parents[2]


def _lines(name):
    import fidelity as F
    doc = json.loads((REPO_ROOT / "presets.json").read_text(encoding="utf-8"))
    lines = []
    convert(str(CORPUS / name), log=lines.append, **F._preset_opts(doc, name))
    return lines


@needs_corpus
def test_delta_splits_for_its_pulse_only_records():
    lines = _lines("Delta.sid")
    free = [ln for ln in lines if ln.startswith("Free note (bit 7)")]
    assert len(free) == 1, lines
    assert "entered with two instruments" not in free[0], free[0]
    # Figures re-taken at the orderlist-254-entry-read-cap fix (base c4eedc4):
    # Delta's subtune-0 voices 0 and 1 are now read whole, so the pass sees
    # rows the capped file never held. The old 67 rows / 7 variants / 0 kept
    # the full start / 3 copies were the capped file's. The 3 "kept the full
    # start" are declines at pattern rows reached only past the old cut
    # (1 unsettled, 2 follow another instrument), not an entry decline.
    # Re-taken at delta-new-rows-kept-full-start (base 881bbe1): $B4/$B5
    # row 11 followed a legato CLONE of its own record (28 of 2), which the
    # walk read as another instrument; one is now taken (137 rows), the other
    # declines at its last row for what its successor holds.
    assert "137 flagged note row(s) on 8 variant(s)" in free[0], free[0]
    assert ("2 kept the full start (1 follows an unsettled instrument; "
            "1 last row, successor entered holding another instrument)"
            ) in free[0], free[0]
    split = [ln for ln in lines if ln.startswith("Entry instrument split")]
    assert split and "5 pattern cop(ies) of 02, 03" in split[0], split


@needs_corpus
def test_knucklebusters_has_no_entry_decline_left():
    free = [ln for ln in _lines("Knucklebusters.sid")
            if ln.startswith("Free note (bit 7)")]
    assert len(free) == 1 and "entered with two instruments" not in free[0]
