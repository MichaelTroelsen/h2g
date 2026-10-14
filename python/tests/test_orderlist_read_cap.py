"""The orderlist reader no longer cuts a track at 254 entries.

The VB6 original forced `$FF` at the 254th entry read (an array bound), the
port kept that, and Delta's reader cut at 252 beside it. The limit belongs
downstream: `patterns.reindex_tracks` fits an over-long orderlist into
Goattracker's `MAX_TRACK_LEN` by REPEAT packing, merging, splitting or
dropping, and a read that truncates first takes those decisions away.

MEASURED at base c4eedc4 (v0.5.538), under presets
(C:/t/orderlist-254-entry-read-cap):

* Census over the corpus, every `_build_track` call with the cap removed
  against as-is: the cap changes exactly two tracks, both Delta subtune 0
  (voice 0: 254 -> 927 bytes, voice 1: 254 -> 872 bytes, each ending on the
  original's own `$FF 00`). In both it was Delta's `252` that fired; the
  generic `count >= 254` fires on nothing in the corpus.
* Corpus byte-hash, base vs this change: 95 files, 6 refused in both arms,
  89 compared, 1 moved -- Delta. Commando.sng is byte-identical.
* Delta subtune 0, rows in the final .sng per voice (loop length): 3420 /
  6156 / 13822 capped, 14557 / 14502 / 13822 read in full. `fidelity.py -a 0
  -t 290` (past the original's 13632-frame loop): melody 91.0% -> 99.7%,
  retrig 1.06 -> 1.00, attacks 4353 -> 4104 against the original's 4104.
"""
import pathlib
import sys

import pytest

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[1]))

from corpus import CORPUS, needs_corpus                      # noqa: E402
import h2g.convert                                           # noqa: E402,F401  (first: h2g's import cycle)
from h2g.patterns import MAX_TRACK_LEN                      # noqa: E402
from h2g import tracks as tracks_mod                         # noqa: E402
from h2g.detect import detect                               # noqa: E402
from h2g.sidfile import load_sid                             # noqa: E402
from h2g.tracks import (ORDERLIST_READ_CAP, _build_track,    # noqa: E402
                        convert_tracks)

END = [0xFF, 0x00]


def test_a_version_0_orderlist_longer_than_254_entries_is_read_whole():
    raw = bytes(range(0x00, 0x7F)) * 3 + bytes([0xFF])      # 381 entries
    got = _build_track(raw, 0, 0)
    assert got == list(raw[:-1]) + END


def test_a_delta_orderlist_longer_than_252_entries_is_expanded_whole():
    # P0 once, then $06 x100, $07 x100, $08 x100: 301 entries (a count must
    # be < $80 or it reads as a marker).
    raw = bytes([0x05, 100, 0x06, 100, 0x07, 100, 0x08, 0xFF])
    assert _build_track(raw, 0, 10) == \
        [0x05] + [0x06] * 100 + [0x07] * 100 + [0x08] * 100 + END


def test_the_runaway_guard_still_bounds_a_stored_zero_chain():
    # 100 pairs of (pattern, 0): each pair after the first is 256 plays, so
    # the expansion would be 25600 entries. The guard ends it with a clean
    # `$FF 00` at ORDERLIST_READ_CAP and never past it.
    raw = bytes([0x05] + [0x00, 0x06] * 100 + [0xFF])
    got = _build_track(raw, 0, 10)
    assert got[-2:] == END
    assert len(got) <= ORDERLIST_READ_CAP
    assert len(got) > 254


def test_the_cap_is_not_goattrackers_limit():
    # The read cap is a guard against runaway expansion. Goattracker's own
    # limit is MAX_TRACK_LEN, enforced by patterns.reindex_tracks.
    assert ORDERLIST_READ_CAP > MAX_TRACK_LEN
    assert tracks_mod.ORDERLIST_READ_CAP == ORDERLIST_READ_CAP


@needs_corpus
def test_only_delta_subtune_0_reaches_the_old_cap_in_the_corpus():
    """The census: every corpus track of 254+ bytes, by (file, subtune,
    voice). A new entry here is a track the old cap would have cut -- decide
    it against a trace of the original's orderlist position before adding."""
    got = set()
    for path in sorted(CORPUS.glob("*.sid")):
        try:
            sid = load_sid(str(path))
            det = detect(sid, log=lambda m: None)
            tracks = convert_tracks(sid, det, lambda m: None)
        except Exception:
            continue                        # a refused file has no tracks
        for i, t in enumerate(tracks):
            if len(t) >= 254:
                got.add((path.name, i // 3, i % 3))
    assert got == {("Delta.sid", 0, 0), ("Delta.sid", 0, 1)}, got


@needs_corpus
def test_delta_subtune_0_voices_fit_goattracker_after_packing():
    """Read whole, the 927 / 872-entry voices must come out of
    reindex_tracks packed, not split or dropped, and subtune 0's three voices
    must loop over about the same number of rows (capped: 3420 / 6156 /
    13822)."""
    import json

    import fidelity as F
    import songview
    from h2g.convert import convert

    root = pathlib.Path(__file__).resolve().parents[2]
    doc = json.loads((root / "presets.json").read_text(encoding="utf-8"))
    lines = []
    sng = convert(str(CORPUS / "Delta.sid"), log=lines.append,
                  **F._preset_opts(doc, "Delta.sid"))
    assert not [l for l in lines if "DROPPED" in l or "split into" in l], lines
    song = songview.parse_sng(sng)
    rows = []
    for v in range(3):
        track, repeat, total = song.tracks[v], 1, 0
        for b in track:
            if b == 0xFF:
                break
            if 0xD0 <= b < 0xE0:
                repeat = b - 0xD0 + 1
            elif b < 0xD0:
                total += repeat * (len(song.patterns[b]) // 4)
                repeat = 1
        rows.append(total)
    assert min(rows) > 13000 and max(rows) < 15000, rows
