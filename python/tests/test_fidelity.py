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


def test_waveform_writes_are_recorded_per_voice():
    # The WF column is the 2 chars after the 9-char note field in all four
    # note formats; '..' means "not written this frame" and is not an event.
    v0, v1, v2 = fidelity.parse_dump(DUMP)
    assert v0.wf_events == [(0, 0x15), (1, 0x80), (6, 0x41)]
    assert v1.wf_events == [(0, 0x43)]
    assert v2.wf_events == [(0, 0x41), (3, 0x41)]


def test_wave_timeline_carries_the_register_forward():
    # siddump prints a row only on change; between writes the chip keeps
    # playing the latched value, and skipped frames (2, 4, 5) inherit it.
    v0 = fidelity.parse_dump(DUMP)[0]
    assert fidelity.wave_timeline(v0, 8) == \
        [0x15, 0x80, 0x80, 0x80, 0x80, 0x80, 0x41, 0x41]


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


# --- waveform-class agreement ----------------------------------------------

def _wf_voice(*events):
    return fidelity.Voice(wf_events=list(events))


def _wf_voices(*event_lists):
    vs = [_wf_voice(*e) for e in event_lists]
    return vs + [fidelity.Voice()] * (3 - len(vs))


def test_a_trace_against_itself_has_full_wave_agreement():
    a = _wf_voices([(0, 0x41), (5, 0x81)], [(0, 0x21)])
    got = fidelity.wave_compare(a, _wf_voices([(0, 0x41), (5, 0x81)], [(0, 0x21)]),
                                nframes=10)
    assert got["wave"] == 1.0


def test_the_gate_bit_is_not_a_timbre():
    # $41 (gated pulse) and $40 (released pulse) are the same class: note
    # length is the attack metrics' job, not this one's.
    got = fidelity.wave_compare(_wf_voices([(0, 0x41)]),
                                _wf_voices([(0, 0x40)]), nframes=4)
    assert got["wave"] == 1.0


def test_a_combined_waveform_is_its_own_class():
    # $51 (tri+pulse) matches neither pure triangle nor pure pulse.
    tri_pulse = _wf_voices([(0, 0x51)])
    assert fidelity.wave_compare(tri_pulse, _wf_voices([(0, 0x41)]),
                                 nframes=2)["wave"] == 0.0
    assert fidelity.wave_compare(tri_pulse, _wf_voices([(0, 0x11)]),
                                 nframes=2)["wave"] == 0.0
    assert fidelity.wave_compare(tri_pulse, _wf_voices([(0, 0x51)]),
                                 nframes=2)["wave"] == 1.0


def test_an_invented_noise_tick_costs_agreement_and_is_counted():
    """The Phase-0 signal: our fabricated wavetable opens a note on a frame
    of noise where the original plays pulse throughout."""
    orig = _wf_voices([(0, 0x41)])
    ours = _wf_voices([(0, 0x81), (1, 0x41)])   # noise tick, then pulse
    got = fidelity.wave_compare(orig, ours, nframes=4)
    assert got["wave"] == 0.75                  # 1 of 4 frames disagrees
    assert got["orig_noise_frames"] == 0
    assert got["our_noise_frames"] == 1


def test_frames_silent_on_both_sides_do_not_inflate_agreement():
    # Both sides drop to class 0 at frame 2, so only frames 0-1 are counted:
    # a long shared silence must not drown out a real timbre disagreement.
    orig = _wf_voices([(0, 0x41), (2, 0x00)])
    ours = _wf_voices([(0, 0x21), (2, 0x00)])
    got = fidelity.wave_compare(orig, ours, nframes=6)
    assert got["wave_frames"] == 2
    assert got["wave"] == 0.0
    # ... but one side selecting a waveform against silence is a disagreement.
    half = fidelity.wave_compare(_wf_voices([(0, 0x41)]),
                                 _wf_voices([(0, 0x41), (2, 0x00)]), nframes=4)
    assert half["wave"] == 0.5


def test_noise_frames_are_counted_over_all_frames_per_side():
    # Carry-forward: noise latched at frame 1 persists to nframes.
    got = fidelity.wave_compare(_wf_voices([(0, 0x41), (1, 0x81)]),
                                _wf_voices([(0, 0x41)]), nframes=5)
    assert got["orig_noise_frames"] == 4
    assert got["our_noise_frames"] == 0


def test_wave_is_none_when_no_frames_are_counted():
    got = fidelity.wave_compare(_wf_voices(), _wf_voices(), nframes=5)
    assert got["wave"] is None


def test_wave_nframes_defaults_to_the_last_write_seen():
    got = fidelity.wave_compare(_wf_voices([(0, 0x41)]),
                                _wf_voices([(0, 0x41), (9, 0x21)]))
    assert got["wave_frames"] == 10
    assert got["wave"] == 0.9


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
    # ... and the same control for the wave metric: siddump plays
    # seconds*50 frames, and a real trace has waveform writes to compare.
    wave = fidelity.wave_compare(trace, trace, nframes=4 * 50)
    assert wave["wave_frames"] > 0
    assert wave["wave"] == 1.0
    assert wave["orig_noise_frames"] == wave["our_noise_frames"]


# --- what a row's status means ---------------------------------------------
# Three ways a row can carry no melody score, and only two of them are the
# converter's fault. Conflating the third with "silent" is what put BMX_Kidz
# -- which matches its original at 95% once the window is long enough to
# reach its first note -- in the bucket labelled "plays something else".


class _Args:
    seconds = 10
    subtune = "auto"
    label = None
    search_subtunes = 3
    register = False
    audio = False


def _row(name, status, melody=None, orig=0, ours=0):
    r = {"file": name, "status": status, "subtune": 0,
         "orig_attacks": orig, "our_attacks": ours, "retrigger_ratio": None,
         "orig_slides": 0, "our_slides": 0, "multiplier": 1}
    if melody is not None:
        r.update(melody=melody, sequence=melody, pitch_jaccard=melody,
                 retrigger_ratio=1.0, wave=melody, wave_frames=100,
                 orig_noise_frames=0, our_noise_frames=0)
    return r


def test_a_window_in_which_neither_side_played_is_not_scored():
    # compare() runs before the status is decided, so the row does carry a
    # melody -- 0%, from two empty sequences. The point is that it is not
    # averaged in, not that the number is missing.
    rows = [_row("Good.sid", "measured", 1.0, 50, 50),
            _row("Empty.sid", "window empty", 0.0, 0, 0)]
    text = fidelity.report(rows, _Args())
    # It stays visible in the table...
    assert "| Empty.sid |" in text and "window empty" in text
    # ...but a window with nothing in it must not drag the headline down.
    assert "- measured: **1** of 2" in text
    assert "mean melody similarity: **100%**" in text


def test_a_conversion_that_plays_nothing_is_still_a_defect():
    # The original played; we did not. That is ours, and it is scored 0%.
    rows = [_row("Good.sid", "measured", 1.0, 50, 50),
            _row("Mute.sid", "silent", 0.0, 50, 0)]
    text = fidelity.report(rows, _Args())
    assert "- measured: **2** of 2" in text
    assert "mean melody similarity: **50%**" in text


# --- the scratch directory -------------------------------------------------
#
# Every file the harness writes has a fixed name -- a.sng, b.sid, o.sid -- so
# two runs sharing a directory overwrite each other between the write and the
# read, and each measures whichever file won the race. Nothing fails; the
# numbers are plausible and about the wrong tune. It has contaminated a real
# A/B in this repo, and this project runs concurrent agents as a matter of
# course, so the default has to be private.


def test_two_runs_never_share_a_scratch_directory():
    a, owned_a = fidelity.make_workdir()
    b, owned_b = fidelity.make_workdir()
    try:
        assert a != b
        assert a.is_dir() and b.is_dir()
        assert owned_a and owned_b
        # The collision is between identically named files, so distinct
        # directories are the whole guarantee.
        (a / "a.sng").write_bytes(b"first")
        (b / "a.sng").write_bytes(b"second")
        assert (a / "a.sng").read_bytes() == b"first"
    finally:
        shutil.rmtree(a, ignore_errors=True)
        shutil.rmtree(b, ignore_errors=True)


def test_a_named_directory_is_used_as_given_and_not_owned(tmp_path):
    """--workdir is the debugging route: it keeps the intermediates, so the
    caller owns them and this script must not delete them."""
    target = tmp_path / "keep" / "me"
    d, owned = fidelity.make_workdir(str(target))
    assert d == target and d.is_dir()
    assert owned is False


def test_the_default_is_unset_so_nothing_inherits_one_path():
    """listen.py takes its default from this constant too. If it named a
    directory, both scripts would default to the same one again."""
    assert fidelity.WORKDIR is None or os.environ.get("H2G_FIDELITY_WORK")
