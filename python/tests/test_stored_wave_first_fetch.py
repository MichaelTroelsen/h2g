"""A `$68` fetch whose cells are still unknown when it runs sounds the cells
as they stand once that tick's stores have run.

Devils_Galop opens with voice 1 (X = 1) fetching a `$68` note (entry `$12`,
ordinal 0) on tick 0. The walk reads voice 0's and voice 1's waveform cells,
but at tick 0 neither voice has fetched yet, so the vote used to be skipped
and the pattern kept only its tick-5248 vote, `$8141` (B-6). The original
does not sound that on the first pass: the player re-reads the note table on
every call, so after tick 0's stores (voice 0 `$11`, voice 1 `$41`) it sounds
`$4111` (B-5, base of the 8-frame sweep a siddump of the original shows from
frame 1; 2026-11-03, `C:/t/devils-galop-aud-dip-0/finding.md`).
"""
import pathlib
import sys

from corpus import CORPUS, needs_corpus

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[1]))

from h2g import stored_wave  # noqa: E402
from h2g.convert import _detect_tables  # noqa: E402
from h2g.sidfile import load_sid  # noqa: E402
from h2g.tracks import convert_tracks  # noqa: E402

B_5, B_6 = 71, 83


@needs_corpus
def test_devils_galop_first_pass_sounds_b5_not_the_later_pass_b6():
    sid = load_sid(str(CORPUS / "Devils_Galop.sid"))
    sid, det = _detect_tables(sid, lambda m: None)
    tracks = convert_tracks(sid, det, lambda m: None)
    trace: list = []
    stored_wave.stored_wave_notes(sid, det, tracks, slides=True,
                                  status_bit6=True, trace=trace)
    # (group, voice, tick, entry, ordinal, freq, derived)
    mine = [t for t in trace if t[3] == 0x12 and t[4] == 0]
    first = [t for t in mine if t[2] == 0]
    assert first, "tick 0 must cast a vote once the cells are known"
    assert first[0][5] == 0x4111 and first[0][6] == B_5
    later = [t for t in mine if t[2] > 0]
    assert later and later[0][5] == 0x8141 and later[0][6] == B_6
