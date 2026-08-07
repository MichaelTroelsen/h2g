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


def test_register_timeline_carries_the_register_forward():
    # siddump prints a row only on change; between writes the chip keeps
    # playing the latched value, and skipped frames (2, 4, 5) inherit it.
    v0 = fidelity.parse_dump(DUMP)[0]
    assert fidelity.register_timeline(v0.wf_events, 8) == \
        [0x15, 0x80, 0x80, 0x80, 0x80, 0x80, 0x41, 0x41]


# --- the rest of the row: ADSR, pulse width, and the global filter cell -----
#
# siddump prints five register groups per frame and the harness used to read
# two fields out of three of them. These pin the other seven, and above all
# the one property they share: a field printed as dots is the chip *holding*
# its last value, so every one of them has to carry forward.

def test_adsr_writes_are_recorded_per_voice():
    v0, v1, v2 = fidelity.parse_dump(DUMP)
    assert v0.adsr_events == [(0, 0x0DFB)]
    assert v1.adsr_events == [(0, 0x0FC4)]
    assert v2.adsr_events == [(0, 0x099F)]


def test_pulse_writes_are_recorded_per_voice():
    v0, v1, v2 = fidelity.parse_dump(DUMP)
    assert v0.pulse_events == [(0, 0x180), (3, 0xCE0), (5, 0xD40), (6, 0xC80)]
    assert v1.pulse_events == [(0, 0x200), (3, 0x140), (5, 0x1C0), (6, 0x200)]
    assert v2.pulse_events == \
        [(0, 0x180), (1, 0x196), (3, 0x1C0), (5, 0x240), (6, 0x280)]


def test_the_global_cell_is_read():
    # ' 0000 00 Off F ' on frame 0, dots on every later frame in DUMP.
    f = fidelity.parse_dump(DUMP).filter
    assert f.cutoff_events == [(0, 0x0000)]
    assert f.ctrl_events == [(0, 0x00)]
    assert f.passband_events == [(0, 0)]      # 'Off'
    assert f.volume_events == [(0, 0xF)]


# A filter sweep: cutoff moving frame by frame, the $D417 byte and the
# passband changing once each, and the master volume ducking. Written in
# siddump's exact column widths (siddump.c:451-467) -- note 'Hi ' is padded
# to three characters in siddump's own table, so the cell reads 'Hi  '.
FILTER_DUMP = """| Frame | Freq Note/Abs WF ADSR Pul | Freq Note/Abs WF ADSR Pul | Freq Note/Abs WF ADSR Pul | FCut RC Typ V |
+-------+---------------------------+---------------------------+---------------------------+---------------+
|     0 | AF58  E-7 D8  15 0DFB 180 | ....  ... ..  .. .... ... | ....  ... ..  .. .... ... | 0800 F1 Low F |
|     1 | ....  ... ..  .. 0A08 ... | ....  ... ..  .. .... ... | ....  ... ..  .. .... ... | 0A00 .. ... . |
|     2 | ....  ... ..  .. .... ... | ....  ... ..  .. .... ... | ....  ... ..  .. .... ... | 0C00 .. Hi  . |
|     4 | ....  ... ..  .. .... ... | ....  ... ..  .. .... ... | ....  ... ..  .. .... ... | .... 04 ... 8 |
"""


def test_every_global_field_is_read_independently():
    f = fidelity.parse_dump(FILTER_DUMP).filter
    assert f.cutoff_events == [(0, 0x0800), (1, 0x0A00), (2, 0x0C00)]
    assert f.ctrl_events == [(0, 0xF1), (4, 0x04)]
    assert f.passband_events == [(0, 1), (2, 4)]   # 'Low', then 'Hi '
    assert f.volume_events == [(0, 0xF), (4, 0x8)]


def test_the_passband_name_round_trips_to_its_register_bits():
    # The index is ($D418 >> 4) & 7, so the name is the register value.
    assert fidelity.FILTER_PASSBAND[4] == "Hi"
    assert fidelity.FILTER_PASSBAND[0] == "Off"
    assert len(fidelity.FILTER_PASSBAND) == 8


def test_a_held_register_is_not_a_zero():
    # The whole point of the parse contract. Frames 3 and 5+ print no cutoff
    # at all; the filter is still open at $0C00, not closed.
    f = fidelity.parse_dump(FILTER_DUMP).filter
    assert fidelity.register_timeline(f.cutoff_events, 6) == \
        [0x0800, 0x0A00, 0x0C00, 0x0C00, 0x0C00, 0x0C00]
    assert fidelity.register_timeline(f.volume_events, 6) == \
        [0xF, 0xF, 0xF, 0xF, 0x8, 0x8]
    assert fidelity.register_timeline(f.passband_events, 6) == \
        [1, 1, 4, 4, 4, 4]


def test_adsr_and_pulse_carry_forward_the_same_way():
    v0 = fidelity.parse_dump(FILTER_DUMP)[0]
    assert fidelity.register_timeline(v0.adsr_events, 5) == \
        [0x0DFB, 0x0A08, 0x0A08, 0x0A08, 0x0A08]
    assert fidelity.register_timeline(v0.pulse_events, 5) == \
        [0x180] * 5


def test_a_silent_voice_contributes_no_events():
    v1 = fidelity.parse_dump(FILTER_DUMP)[1]
    assert v1.wf_events == v1.adsr_events == v1.pulse_events == []


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


# --- what the run says it compared -----------------------------------------
#
# The repo's standing rule -- a metric that cannot see a change is not
# evidence the change did nothing -- has been applied correctly at least seven
# times and every one of them depended on an author remembering it. These
# tests are what makes it structural: a run states which dimensions it
# computed, and therefore which registers no dimension of it reads.


def test_every_printed_column_has_a_dimension_declaring_its_registers():
    """The registry is only useful if it is complete. A column that exists in
    the table and not in DIMENSIONS is invisible to --baseline, which is the
    exact failure the registry is here to prevent."""
    header = next(line for line in fidelity.report([_row("A.sid", "measured", 1.0)],
                                                   _Args()).splitlines()
                  if line.startswith("| File |"))
    cells = {c.strip() for c in header.split("|")}
    for d in fidelity.DIMENSIONS:
        assert d.column in cells, f"{d.column} is declared but not printed"
    # ... and nothing is printed that no dimension claims, bar the four
    # non-measurements: the file, the two raw attack counts, and the status.
    assert cells - {d.column for d in fidelity.DIMENSIONS} == {
        "", "File", "orig", "ours", "status"}


def test_a_row_records_only_the_dimensions_it_actually_compared():
    full = _row("A.sid", "measured", 0.5)
    assert fidelity.dimensions_present(full) == [d.key for d in fidelity.DIMENSIONS]
    # A file whose voices never select a waveform has no wave score, and a row
    # claiming one it did not compute is the misreading in miniature.
    no_wave = dict(full, wave=None)
    assert "wave" not in fidelity.dimensions_present(no_wave)
    assert "melody" in fidelity.dimensions_present(no_wave)
    # A file that would not convert compared nothing at all: its row carries
    # none of the metric keys, as _measure's first exit leaves it.
    assert fidelity.dimensions_present(
        {"file": "B.sid", "status": "not converted"}) == []


def test_the_registers_no_dimension_reads_are_named():
    """Every dimension is computed from the frequency registers or from $D404.
    Those are the two the report can see; the rest is where v0.5.71's
    envelope, v0.5.72's filter and v0.5.73's pulse width all landed."""
    unread = dict(fidelity.registers_unread({d.key for d in fidelity.DIMENSIONS}))
    assert set(unread) == {"$D402/$D403", "$D405/$D406",
                           "$D415/$D416", "$D417", "$D418"}
    # Losing a dimension widens the blind spot rather than leaving it fixed:
    # a run that scored no notes cannot claim to have compared pitch. ($D404
    # stays read either way -- the attack metrics need its gate bit as an
    # edge, which is why note *length* is in NOT_MEASURED rather than here.)
    assert "$D400/$D401" in dict(fidelity.registers_unread({"wave", "noise"}))
    assert len(fidelity.registers_unread(set())) == len(fidelity.SID_REGISTERS)


def test_the_report_states_its_own_reach():
    text = fidelity.report([_row("A.sid", "measured", 1.0, 50, 50)], _Args())
    assert "## What this run compared" in text
    assert "$D405/$D406" in text and "$D415/$D416" in text
    assert "note length" in text


# --- A/B against a previous run --------------------------------------------


def _ab(name, sha="aaa", **kw):
    r = {"file": name, "status": "measured", "seconds": 10, "subtune": 0,
         "options": {"filters": True}, "multiplier": 1, "output_sha": sha,
         "melody": 0.80, "sequence": 0.80, "pitch_jaccard": 0.80,
         "retrigger_ratio": 1.0, "our_slides": 5, "wave": 0.60,
         "our_noise_frames": 0}
    r.update(kw)
    r["dimensions"] = fidelity.dimensions_present(r)
    return r


def test_an_invisible_change_is_printed_as_a_result():
    """The whole point. The converter's output changed and no dimension
    moved, which is a finding -- not the flat table that has been read as a
    null result more often than anything else in this project."""
    text, code = fidelity.compare_runs([_ab("A.sid", "old")], [_ab("A.sid", "new")])
    assert code == 0
    assert "No dimension this report measures can see this change" in text
    # ... and it says where the change can have gone instead.
    assert "$D405/$D406" in text and "$D402/$D403" in text


def test_an_inert_change_is_told_apart_from_an_invisible_one():
    """Two readings of one flat table, and this repo has shipped the second
    believing the first twice. Identical bytes mean the change reached
    nothing; changed bytes mean it reached the output and was not measured."""
    text, code = fidelity.compare_runs([_ab("A.sid", "same")], [_ab("A.sid", "same")])
    assert code == 0
    assert "This change reaches nothing" in text
    assert "No dimension this report measures can see" not in text


def test_a_baseline_without_hashes_refuses_to_guess_which_it_was():
    old = _ab("A.sid")
    del old["output_sha"]
    text, code = fidelity.compare_runs([old], [_ab("A.sid", "new")])
    assert "cannot say whether" in text
    assert "reaches nothing" not in text


def test_movement_below_the_printed_precision_is_not_silence():
    """A report that prints 50% either way looks like a no-op to a reader
    diffing two tables. The raw values moved, and the mode says so."""
    text, code = fidelity.compare_runs(
        [_ab("A.sid", "old", melody=0.5000)],
        [_ab("A.sid", "new", melody=0.5004)])
    assert code == 0
    assert "below the precision the report prints" in text
    assert "50% -> 50% !" in text          # marked as invisible in the table


def test_a_baseline_traced_at_other_settings_is_refused():
    """A 10 s run against a 20 s one is two statements about different music.
    Nothing about the delta between them is meaningful."""
    text, code = fidelity.compare_runs([_ab("A.sid", seconds=10)],
                                       [_ab("A.sid", "new", seconds=20)])
    assert code == 2
    assert "## Refused" in text and "seconds 10 -> 20" in text
    # A different subtune is the same class of mismatch.
    _, code2 = fidelity.compare_runs([_ab("A.sid", subtune=0)],
                                     [_ab("A.sid", "new", subtune=3)])
    assert code2 == 2


def test_a_baseline_missing_a_field_is_old_rather_than_incomparable():
    """Refusing every saved run the first time a field is added would make
    the mode useless exactly when a baseline is most valuable."""
    old = _ab("A.sid", "old")
    del old["seconds"]
    _, code = fidelity.compare_runs([old], [_ab("A.sid", "new")])
    assert code == 0


def test_an_option_difference_is_named_as_the_change_under_test():
    """FIDELITY-TOOL-IMPROVEMENTS.md §4 asks for a hard failure on any
    settings difference. Conversion options are the deliberate exception: an
    option A/B is what the mode is mostly for, and naming the difference
    answers the hazard that refusing it would have answered."""
    base = _ab("A.sid", "old")
    base["options"] = dict(base["options"], filters=False)
    text, code = fidelity.compare_runs([base], [_ab("A.sid", "new")])
    assert code == 0
    assert "`filters` False -> True on 1 file(s)" in text


def test_identical_bytes_that_measure_differently_are_the_harness_moving():
    text, _ = fidelity.compare_runs([_ab("A.sid", "same", melody=0.80)],
                                    [_ab("A.sid", "same", melody=0.60)])
    assert "convert to identical bytes and still moved" in text


def test_a_partly_blind_change_says_how_many_files_it_could_not_see():
    """The case that actually occurs. Reporting only the file that moved
    reproduces the misreading at a smaller scale: two files could not be
    seen at all."""
    base = [_ab("A.sid", "old"), _ab("B.sid", "old"), _ab("C.sid", "old")]
    new = [_ab("A.sid", "new", melody=0.90), _ab("B.sid", "new"),
           _ab("C.sid", "new")]
    text, code = fidelity.compare_runs(base, new)
    assert code == 0
    assert "2 of the 3 file(s) whose converted output changed moved no number" in text


def test_a_file_that_stops_converting_is_movement():
    """A change that costs three files their conversion must not read as
    quiet just because a row with no numbers has no numbers to move."""
    gone = {"file": "A.sid", "status": "not converted", "seconds": 10,
            "subtune": 0, "options": {}, "multiplier": 1, "dimensions": []}
    text, code = fidelity.compare_runs([_ab("A.sid", "old")], [gone])
    assert code == 0
    assert "## Status changes" in text
    assert "reaches nothing" not in text


def test_files_present_in_only_one_run_are_reported():
    text, _ = fidelity.compare_runs([_ab("A.sid", "old"), _ab("Gone.sid", "old")],
                                    [_ab("A.sid", "old"), _ab("New.sid", "old")])
    assert "only in the current run (1): New.sid" in text
    assert "only in the baseline (1): Gone.sid" in text


# --- provenance ------------------------------------------------------------


def test_the_label_names_the_commit_the_measurement_was_taken_from():
    """--label was free text and optional, so a run could not say which tree
    it came from. Several commits share one version during a branch's life,
    and a dirty tree shares its version with the commit it is not."""
    got = fidelity.git_label()
    head = subprocess.run(["git", "-C", str(REPO_ROOT), "rev-parse", "--short",
                           "HEAD"], capture_output=True, text=True)
    if head.returncode != 0:
        pytest.skip("not a git checkout")
    assert got.split("-dirty")[0] == head.stdout.strip()
    assert got in (head.stdout.strip(), head.stdout.strip() + "-dirty")


def test_a_run_is_labelled_or_unlabelled_but_never_mislabelled(monkeypatch):
    """git not answering is not a reason to fail a measurement, and it is
    also not a reason to invent a provenance for one."""
    def boom(*a, **kw):
        raise OSError("no git here")
    monkeypatch.setattr(fidelity.subprocess, "run", boom)
    assert fidelity.git_label() is None
