"""Nemesis' 15 and Thundercats' 11 phantom orderlists, and why suppressing
them is the whole gain.

Both files declare a large subtune count in the PSID header (15 and 16) and
carry a track table with room for exactly **one**: in each, the pattern LO
array begins at the byte after subtune 0's last track cell, so every
"pointer" subtune 1 upward reads is a pattern address being mistaken for an
orderlist address.  `tracks.track_table_extent` closes that, and
`tests/test_reject_phantoms.py` pins the extent itself.  What this file adds
is the two things that test cannot say:

**What the suppression is worth, end to end.**  `track_table_extent` is one
bound of three (`det.subtunes_available`, the player's sfx dispatch, the
layout) and the emitted count is the composition of all three plus the
trailing-run playability trim.  Asserting the extent is 1 does not assert the
`.sng` carries one subtune.  Switching the bound off here converts these two
files to **15** and **11** orderlist sets against **1** each -- and 11 rather
than 16 for Thundercats, because the trailing-run trim had already dropped
its last five without help.

**That the phantoms are not music.**  Ripping them would be the tempting
reading of "the file has fifteen subtunes and we emit one".  Traced with
siddump for 10 s at 50 Hz, every suppressed subtune of both files is a
**sound effect**: its last note attack lands on frame 0 (Nemesis subtune 2 is
the only one that carries on at all, and it is a 7-event pitch sweep -- B-7,
E-1, E-1, D-2, D-2, C#3, C#3 -- finished by frame 15).  Subtune 0 is still
attacking at frame 454 and 492 of the 500-frame window, with 12 and 104 note
events against the phantoms' 2 and 3.  So there is no music behind these
orderlists to recover: suppression is the gain, not a missing rip.

One correction to the wording this task was filed under.  The bound is
**not** `Detection.subtunes_available` -- that field is the digi engine's
own, read from the distance between its interleaved tables, and it is `0` on
both of these files.  The general-case bound is `tracks.track_table_extent`,
and `test_the_bound_is_the_layout_never_subtunes_available` pins the
difference so the two are not confused again.
"""
import pathlib
import sys

import pytest

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[1]))

from h2g.convert import convert
from h2g.detect import detect
from h2g.sidfile import load_sid
from h2g.tracks import track_table_extent
from h2g import tracks as tracks_mod

CORPUS = pathlib.Path(r"C:\Users\mit\claude\c64server\SIDM2\SID\Hubbard_Rob")
needs_corpus = pytest.mark.skipif(not CORPUS.is_dir(),
                                  reason="corpus not available")

# The .sng header: 'GTS!'/'GTS5' magic, then name / author / released.
SUBTUNE_BYTE = 4 + 32 * 3

# name -> (header subtunes, orderlist sets emitted with the layout bound
#          switched off, note events in the original's subtune 0 over 10 s)
FILES = {
    "Nemesis_the_Warlock": (15, 15, 12),
    "Thundercats": (16, 11, 104),
}


def _quiet(*_a, **_k):
    pass


@needs_corpus
@pytest.mark.parametrize("name", sorted(FILES))
def test_the_bound_is_the_layout_never_subtunes_available(name):
    """`subtunes_available` is the digi engine's field and is 0 here."""
    sid = load_sid(str(CORPUS / f"{name}.sid"))
    det = detect(sid, _quiet)
    assert sid.subtunes == FILES[name][0]
    assert det.subtunes_available == 0, \
        "subtunes_available is the interleaved-table bound; these are classic"
    assert det.music_subtunes is None, \
        "no CMP #imm / BCS / JMP sfx dispatch at init -- the layout is the bound"
    assert track_table_extent(sid, det) == 1
    # ...and it is 1 because the pattern LO array starts at the byte after
    # subtune 0's last track cell, not because of a threshold.
    last_cell = max(det.track_lo, det.track_hi) + (det.track_voices - 1)
    assert last_cell + 1 == det.pattern_lo


def _preset_opts(name: str) -> dict | None:
    """The options `presets.json` ships for this song, or None if unreadable.

    Taken from `fidelity._preset_opts` rather than rebuilt here: a probe that
    re-derives the calling convention gets one input wrong and measures
    something other than what ships (CLAUDE.md, "A probe that wraps convert()
    must assert its own success rate").  Note the key carries the ".sid"
    suffix -- keying on the bare stem silently reads no per-song entry at all.
    """
    import json
    doc_path = pathlib.Path(__file__).resolve().parents[2] / "presets.json"
    if not doc_path.is_file():
        return None
    fid = pytest.importorskip("fidelity")
    return fid._preset_opts(json.loads(doc_path.read_text()), f"{name}.sid")


@needs_corpus
@pytest.mark.parametrize("name", sorted(FILES))
def test_the_converted_sng_carries_exactly_one_subtune(name):
    """End to end, not just the extent: the .sng's own subtune byte.

    Checked twice -- at the bare defaults and at the options `presets.json`
    ships -- because the emitted count is the composition of three bounds and
    a playability trim, and only the shipped options say what a user gets.
    """
    blob = convert(str(CORPUS / f"{name}.sid"), log=_quiet)
    assert blob[SUBTUNE_BYTE] == 1
    opts = _preset_opts(name)
    if opts is not None:
        shipped = convert(str(CORPUS / f"{name}.sid"), log=_quiet, **opts)
        assert shipped[SUBTUNE_BYTE] == 1


@needs_corpus
@pytest.mark.parametrize("name", sorted(FILES))
def test_switching_the_bound_off_restores_the_phantoms(name, monkeypatch):
    """What the suppression is worth: 15 and 11 orderlist sets.

    Not a hypothetical -- this is the shape the converter had before
    `track_table_extent` landed, and the number is what makes "suppression is
    the gain" a measurement rather than an opinion.
    """
    monkeypatch.setattr(tracks_mod, "track_table_extent",
                        lambda sid, det: None)
    blob = convert(str(CORPUS / f"{name}.sid"), log=_quiet)
    assert blob[SUBTUNE_BYTE] == FILES[name][1]


@needs_corpus
@pytest.mark.parametrize("name", sorted(FILES))
def test_the_suppressed_subtunes_are_sound_effects_not_music(name):
    """Nothing is lost by suppressing them: they sound one hit and stop.

    Read at the *original* .sid and at `-m1`, because these are 50 Hz VBI
    tunes and the gt2reloc `-S` multiplier is a property of what this
    converter packed, not of the file (CLAUDE.md, "The multiplier belongs to
    our side only").
    """
    fid = pytest.importorskip("fidelity")
    sid_path = CORPUS / f"{name}.sid"
    sid = load_sid(str(sid_path))
    seconds = 10
    window = seconds * 50

    counts, last = [], []
    for a in range(sid.subtunes):
        trace = fid.run_siddump(sid_path, seconds, a, calls=1)
        frames = sorted(f for v in trace for f in v.attack_frames)
        counts.append(len(frames))
        last.append(frames[-1] if frames else -1)

    assert counts[0] == FILES[name][2]
    # Subtune 0 is still playing at the end of the window; no suppressed one
    # reaches even a third of a second.
    assert last[0] > window - 50, f"{name}: subtune 0 stops at frame {last[0]}"
    assert max(last[1:]) <= 15, \
        f"{name}: a suppressed subtune attacks at frame {max(last[1:])}"
    # And each sounds a couple of events where subtune 0 sounds dozens.
    assert max(counts[1:]) < counts[0]
    ordered = sorted(counts[1:])
    assert ordered[len(ordered) // 2] <= 3
