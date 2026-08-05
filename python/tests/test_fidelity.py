"""The fidelity harness: what counts as a note event, and how two traces compare.

`fidelity.py` is the only thing in this repo that measures whether a
conversion *sounds* like its source rather than whether it parses. Everything
it reports rests on one distinction -- which of siddump's note cells is a
struck note -- so that is what these tests pin down, against rows captured
verbatim from `siddump.exe`.

siddump prints a bare note (`E-7 D8`) only after a gate rising edge:
siddump.c:376-380 sets `prevchn[c].note = -1` on keyoff->keyon, and :409
prints the bare form only when that flag is set. A parenthesised note
(`(F#1 92)`) is the same voice moving to a different pitch without
re-triggering, and `(+ 0034)` is a frequency slide inside one note. Counting
all three as "notes" -- which a `grep -oE "[A-G]#?-[0-9]"` over the dump does
-- conflates a re-struck note with a vibrato cycle, and that conflation is
what made an early measurement read as a 7x re-trigger defect.
"""
import os
import pathlib
import shutil
import subprocess

import pytest

import fidelity

REPO_ROOT = pathlib.Path(__file__).resolve().parents[2]

# Verbatim siddump output: header, a first frame (all three voices attack), a
# parenthesised note change, two slides, and unchanged cells.
DUMP = """Load address: $5000 Init address: $5FB2 Play address: $5012
Calling initroutine with subtune 0
Calling playroutine for 100 frames, starting from frame 0
Middle C frequency is $1168

| Frame | Freq Note/Abs WF ADSR Pul | Freq Note/Abs WF ADSR Pul | Freq Note/Abs WF ADSR Pul | FCut RC Typ V |
+-------+---------------------------+---------------------------+---------------------------+---------------+
|     0 | AF58  E-7 D8  15 0DFB 180 | 0000  C-0 80  43 0FC4 200 | 03A9  A-1 95  41 099F 180 | 0000 00 Off F |
|     1 | 0303 (F#1 92) 80 .... ... | ....  ... ..  .. .... ... | ....  ... ..  .. .... 196 | .... .. ... . |
|     3 | ....  ... ..  .. .... CE0 | 1D12 (- 0034) .. .... 140 | 05CE (F-2 9D) 41 .... 1C0 | .... .. ... . |
|     5 | ....  ... ..  .. .... D40 | 1D12 (+ 0034) .. .... 1C0 | ....  ... ..  .. .... 240 | .... .. ... . |
|     6 | 4E20  D-6 CA  41 .... C80 | 1D46 (+ 0034) .. .... 200 | ....  ... ..  .. .... 280 | .... .. ... . |
"""


def test_only_bare_notes_count_as_attacks():
    v0, v1, v2 = fidelity.parse_dump(DUMP)
    assert v0.attacks == ["E-7", "D-6"]      # frames 0 and 6
    assert v1.attacks == ["C-0"]             # frame 0 only
    assert v2.attacks == ["A-1"]


def test_a_parenthesised_note_is_a_tie_not_an_attack():
    v0, _, v2 = fidelity.parse_dump(DUMP)
    assert v0.ties == 1                      # (F#1 92)
    assert v2.ties == 1                      # (F-2 9D)
    assert "F#1" not in v0.attacks


def test_a_frequency_delta_is_a_slide():
    _, v1, _ = fidelity.parse_dump(DUMP)
    assert v1.slides == 3                    # (- 0034), (+ 0034), (+ 0034)
    assert v1.ties == 0


def test_attack_frames_are_recorded():
    v0 = fidelity.parse_dump(DUMP)[0]
    assert v0.attack_frames == [0, 6]


def test_header_and_rule_rows_are_not_frames():
    # The header row also starts with '|' and has the right field count.
    assert sum(len(v.attacks) + v.ties + v.slides
               for v in fidelity.parse_dump(DUMP)) == 4 + 2 + 3


def test_collapsed_merges_consecutive_repeats_only():
    v = fidelity.Voice(attacks=["B-4", "B-4", "B-4", "E-4", "B-4"])
    assert v.collapsed == ["B-4", "E-4", "B-4"]


def _voices(*seqs):
    return [fidelity.Voice(attacks=list(s)) for s in seqs]


def test_identical_traces_score_one():
    a = _voices(["C-4", "E-4"], ["G-3"], [])
    got = fidelity.compare(a, _voices(["C-4", "E-4"], ["G-3"], []))
    assert got["melody"] == 1.0 and got["sequence"] == 1.0
    assert got["retrigger_ratio"] == 1.0


def test_disjoint_traces_score_zero():
    got = fidelity.compare(_voices(["C-4"], [], []), _voices(["G-7"], [], []))
    assert got["melody"] == 0.0
    assert got["pitch_jaccard"] == 0.0


def test_a_retriggered_hold_costs_sequence_but_not_melody():
    """The defect the harness exists to tell apart from a wrong note.

    Striking one held note eight times plays the same music badly; playing
    eight different notes plays different music. Both would look identical to
    a raw event count, so melody (collapsed) and sequence (not) must diverge.
    """
    orig = _voices(["B-4"], [], [])
    ours = _voices(["B-4"] * 8, [], [])
    got = fidelity.compare(orig, ours)
    assert got["melody"] == 1.0
    assert got["sequence"] < 0.5
    assert got["retrigger_ratio"] == 8.0


def test_a_voice_silent_in_both_does_not_dilute_the_score():
    two_voices = fidelity.compare(_voices(["C-4"], ["G-3"]),
                                  _voices(["C-4"], ["A-3"]))
    plus_silent = fidelity.compare(_voices(["C-4"], ["G-3"], []),
                                   _voices(["C-4"], ["A-3"], []))
    assert two_voices["melody"] == plus_silent["melody"]
    # ... and a voice the original plays counts even when ours is silent.
    dropped = fidelity.compare(_voices(["C-4"], ["G-3", "A-3"], []),
                               _voices(["C-4"], [], []))
    assert dropped["melody"] < 1.0


def test_a_loud_voice_outweighs_a_sparse_one():
    """Weighting is by the original's attack count, so the voice carrying the
    tune decides the score rather than one playing two notes."""
    orig = _voices(["C-4"] * 20, ["G-3"], [])
    melody_wrong = fidelity.compare(orig, _voices(["A-7"] * 20, ["G-3"], []))
    sparse_wrong = fidelity.compare(orig, _voices(["C-4"] * 20, ["A-7"], []))
    assert melody_wrong["melody"] < sparse_wrong["melody"]


def test_legalise_restarts_only_touches_out_of_range_positions():
    """greloc.c:244 refuses to pack a song whose restart position is >= the
    track's length, which is exactly what tracks.py emits for a `$FE` byte."""
    blob = bytearray(4 + 32 * 3)
    blob.append(1)                       # one subtune
    for restart in (0xFD, 0x01):         # illegal, then legal
        blob += bytes([3, 0x00, 0x01, 0xFF, restart])
    blob += bytes([2, 0x00, 0xFF, 0x00])  # already legal
    fixed_blob, count = fidelity.legalise_restarts(bytes(blob))
    assert count == 1
    assert fixed_blob[105] == 0x00       # the $FD became 0
    assert fixed_blob[110] == 0x01       # the legal one is untouched


def test_the_commando_fixture_needs_patching_to_pack():
    """The byte-exact reference output carries the illegal restart, so the
    harness patches before packing rather than reporting the file unpackable.
    If this ever fails, the converter itself has been fixed -- see
    SNG2SID-FIDELITY.md and update this test rather than deleting it."""
    _, count = fidelity.legalise_restarts((REPO_ROOT / "Commando.sng").read_bytes())
    assert count == 3


# --- what gt2reloc exports -------------------------------------------------

def _sng(*subtunes):
    """A .sng header carrying `subtunes`, each a triple of orderlist lengths.

    build_sng stores `len(track) - 1` for a track that ends `[..., $FF,
    restart]`, so a voice greloc sees as length n is stored as n+1.
    """
    blob = bytearray(4 + 32 * 3)
    blob.append(len(subtunes))
    for voices in subtunes:
        for n in voices:
            blob.append(n + 1)
            blob += bytes(n) + bytes([0xFF, 0x00])
    return bytes(blob)


def test_song_lengths_reads_greloc_lengths_not_stored_bytes():
    # A voice whose orderlist is only the [$FF, restart] marker is length 0 to
    # greloc (gsong.c:1338-1349), though the .sng stores 1 for it.
    assert fidelity.song_lengths(_sng((4, 0, 2))) == [(4, 0, 2)]


def test_a_subtune_with_an_empty_voice_is_exported_as_a_stub_in_place():
    """greloc.c:653 loops over the original indices, so nothing is renumbered:
    the invalid subtune keeps its slot and is written with songsize 0."""
    exp = fidelity.greloc_export([(1, 1, 0), (2, 2, 2), (3, 3, 3)])
    assert exp["exported"] == 2          # only two subtunes are valid
    assert exp["stub"] == [0]            # index 0 survives as an empty entry
    assert exp["lost"] == [2]            # index 2 >= songs, never written


def test_a_valid_subtune_past_the_exported_count_is_lost_entirely():
    # Two invalid subtunes at the front cost the last two valid ones, which is
    # what happens to Rasputin's subtunes 15 and 16.
    exp = fidelity.greloc_export([(0, 1, 1), (1, 0, 1)] + [(2, 2, 2)] * 4)
    assert exp["exported"] == 4
    assert exp["stub"] == [0, 1]
    assert exp["lost"] == [4, 5]


def test_a_file_with_no_empty_voice_exports_every_subtune():
    exp = fidelity.greloc_export([(1, 1, 1)] * 5)
    assert exp["exported"] == 5
    assert exp["stub"] == [] and exp["lost"] == []


# --- live tools ------------------------------------------------------------
# These need siddump and are the controls for the measurement itself: a file
# against itself must score 1.0, two different tunes near 0.
siddump = os.environ.get("H2G_SIDDUMP", fidelity.SIDDUMP)
needs_siddump = pytest.mark.skipif(not pathlib.Path(siddump).exists(),
                                   reason="siddump not available")


@needs_siddump
def test_a_file_compared_with_itself_is_a_perfect_match(tmp_path):
    sid = REPO_ROOT / "Commando.sid"
    trace = fidelity.run_siddump(sid, 4, 0, siddump)
    assert sum(len(v.attacks) for v in trace) > 0
    got = fidelity.compare(trace, trace)
    assert got["melody"] == 1.0 and got["retrigger_ratio"] == 1.0
