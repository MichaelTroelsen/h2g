"""How many frames a bit-$01+$02 drum note holds the gate: its first unit.

Delta's drum record `AD $0F SR $09` (effect $0B) reads `11 11 81 10 80 10 80`
from every one of its onsets in the original: the gate stays on for the note's
first duration unit, which on that player (speed gate 2, outer gate skipping
one call in four) is 3 frames on the long unit of its 3-and-2 cycle, and every
drum note of the song sits on that unit. The conversion wrote `11 11 80`: the
song-wide unit (`wavetable._real_unit_frames`) is the MEAN, 2.5, and rounds an
exact half down. `goatwriter.drum_unit` reads the unit each record's notes
start on instead (225 gate-column frames on Delta, 150 on Delta_13).

The three layers are pinned apart: the unit arithmetic, the mode over a
walked orderlist, and the converted wavetable; the last two also against the
original's own trace.
"""
import json
import pathlib
import sys
import warnings
from collections import Counter

import pytest

PYTHON_ROOT = pathlib.Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PYTHON_ROOT))

import fidelity                                              # noqa: E402
from corpus import CORPUS, needs_corpus                      # noqa: E402
from h2g.convert import convert                              # noqa: E402
from h2g.goatwriter import drum_unit, tempo, wavetable       # noqa: E402
from h2g.goatwriter.tempo import SongSpeeds                  # noqa: E402
import songview                                              # noqa: E402

needs_siddump = pytest.mark.skipif(
    not pathlib.Path(fidelity.SIDDUMP).exists(),
    reason="no siddump on this machine (tools/siddump-rt, see its README)")

ROOT = PYTHON_ROOT.parent
GT_C4 = 0x60 + 48


def _units(cells, gate, skip, n=8):
    f = drum_unit.fetch_frames(cells[0], cells[1], gate, skip, n + 1)
    return [f[k + 1] - f[k] for k in range(n)]


def test_the_row_clock_is_simulated_from_the_files_own_counters():
    # Delta: gate 2, outer reload 4, counters (4, 1) -> 3 and 2 alternately.
    assert _units((4, 1), 2, 4) == [3, 2, 3, 2, 3, 2, 3, 2]
    # W_A_R_Preview and Flash_Gordon share gate 2 / skip 8 and differ only in
    # where the counters start: the long unit sits on row 0 in the first and
    # on row 1 in the second, which no constant for the cycle can say.
    assert _units((3, 1), 2, 8) == [3, 2, 2, 2, 3, 2, 2, 2]
    assert _units((4, 0), 2, 8) == [2, 3, 2, 2, 2, 3, 2, 2]
    # Deep_Strike and Food_Feud (skip 3): two long units in three.
    assert _units((0, 1), 2, 3) == [2, 3, 3, 2, 3, 3, 2, 3]
    assert _units((1, 1), 2, 3) == [3, 2, 3, 3, 2, 3, 3, 2]


class _Sid:
    subtunes = 1
    start_song = 1


class _Det:
    can_convert = False


def _song(note_rows, speeds, monkeypatch, current=2, cells=(4, 1)):
    """tracks/patterns with instrument 1 sounding at each of `note_rows`."""
    rows = max(note_rows) + 2
    pat = []
    for r in range(rows):
        if r in note_rows:
            pat += [GT_C4, 1, 0, 0]
        else:
            pat += [0xBD, 0, 0, 0]
    pat += [0xFF, 0, 0, 0]
    monkeypatch.setattr(tempo, "find_song_speeds", lambda *a, **k: speeds)
    monkeypatch.setattr(drum_unit, "clock_cells", lambda sid: cells)
    monkeypatch.setattr(wavetable, "_noise_tick_frames",
                        lambda *a, **k: current - 1)
    tracks = [[0, 0xFF, 0], [], []]
    return tracks, [pat]


def _speeds(gate, skip):
    return SongSpeeds(frames=(gate,), reload_addr=0, table_addr=None,
                      skip=(skip,))


def test_the_mode_of_the_notes_unit_is_taken_per_instrument(monkeypatch):
    # Delta's shape: every drum note on an even row -> the long unit, 3.
    tracks, pats = _song({0, 4, 8, 12, 20}, _speeds(2, 4), monkeypatch)
    assert drum_unit.drum_first_units(_Sid, _Det, tracks, pats) == {1: 3}
    # An odd row is the short one; most of the notes decide.
    tracks, pats = _song({1, 3, 5, 6}, _speeds(2, 4), monkeypatch)
    assert drum_unit.drum_first_units(_Sid, _Det, tracks, pats) == {1: 2}


def test_a_tie_keeps_the_song_wide_value(monkeypatch):
    # Delta's clock, notes on rows 0 and 1 -> one unit of 3, one of 2.
    tracks, pats = _song({0, 1}, _speeds(2, 4), monkeypatch, current=2)
    assert drum_unit.drum_first_units(_Sid, _Det, tracks, pats) == {1: 2}
    tracks, pats = _song({0, 1}, _speeds(2, 4), monkeypatch, current=3)
    assert drum_unit.drum_first_units(_Sid, _Det, tracks, pats) == {1: 3}


def test_no_outer_gate_or_a_shifted_numbering_says_nothing(monkeypatch):
    tracks, pats = _song({0, 4}, _speeds(2, None), monkeypatch)
    assert drum_unit.drum_first_units(_Sid, _Det, tracks, pats) == {}
    tracks, pats = _song({0, 4}, _speeds(2, 4), monkeypatch)
    assert drum_unit.drum_first_units(_Sid, _Det, tracks + [[]] * 3,
                                      pats) == {}
    # ... or counters whose first values are not the file's.
    tracks, pats = _song({0, 4}, _speeds(2, 4), monkeypatch, cells=None)
    assert drum_unit.drum_first_units(_Sid, _Det, tracks, pats) == {}


def _delta_song():
    doc = json.loads((ROOT / "presets.json").read_text(encoding="utf-8"))
    with warnings.catch_warnings():
        warnings.simplefilter("ignore")
        opts = fidelity._preset_opts(doc, "Delta.sid")
    return songview.parse_sng(convert(str(CORPUS / "Delta.sid"),
                                      log=lambda *a, **k: None, **opts))


@needs_corpus
def test_delta_drum_record_gates_three_frames_then_the_gate_off_pair():
    song = _delta_song()
    drum = [i for i in song.instruments if i.adsr == "$0F09"]
    assert len(drum) == 1 and drum[0].effect_byte == 0x0B
    wave = song.tables["WTBL"]
    start = drum[0].wave_ptr - 1
    # -S2: a frame is two calls. Frame 0 (the lead) and frame 1 are the
    # record's own waveform, frame 2 the alternate WITH the gate, then the
    # pair with the gate cleared: 11 11 81 10 80 -- the original's.
    left = [wave[start + k][0] for k in range(10)]
    assert left == [0x11, 0x11, 0x11, 0x11, 0x81, 0x81, 0x10, 0x10, 0x80,
                    0x80], [f"{b:02X}" for b in left]


def _gated_run_lengths(dump_text, ad_sr):
    """Counter of the gated frames each gate rise of ADSR `ad_sr` holds, on
    any voice, from siddump text (waveform column carried between changes)."""
    frames = []
    cur = [[None, None] for _ in range(3)]
    for line in dump_text.splitlines():
        parts = line.split("|")
        if len(parts) < 6 or not parts[1].strip().isdigit():
            continue
        for v, col in enumerate(parts[2:5]):
            t = col.replace("(", "").replace(")", "").split()
            if len(t) != 6:
                continue
            if t[3] != "..":
                cur[v][0] = t[3]
            if t[4] != "....":
                cur[v][1] = t[4]
        frames.append([tuple(c) for c in cur])
    out = Counter()
    for v in range(3):
        prev = 0
        for f, row in enumerate(frames):
            w = int(row[v][0], 16) if row[v][0] else 0
            if (w & 1) and not prev and row[v][1] == ad_sr:
                n = 0
                while f + n < len(frames) and frames[f + n][v][0]                         and int(frames[f + n][v][0], 16) & 1:
                    n += 1
                out[n] += 1
            prev = w & 1
    return out


# name, 0-based subtune the harness measures, the drum record, and the
# frames the ORIGINAL holds its gate on every one of its onsets (180 s).
ORIGINAL = [("Delta", 11, "0F09", 3),
            ("W_A_R_Preview", 0, "0A09", 3),
            ("Flash_Gordon", 0, "0F07", 2)]


@needs_corpus
@needs_siddump
@pytest.mark.parametrize("name,subtune,adsr,frames", ORIGINAL)
def test_the_original_holds_the_gate_the_same_frames_on_every_onset(
        name, subtune, adsr, frames):
    cap = []
    fidelity.run_siddump(CORPUS / f"{name}.sid", 180, subtune, capture=cap)
    seen = _gated_run_lengths(cap[1], adsr)
    assert sum(seen.values()) >= 20, seen
    assert set(seen) == {frames}, seen


@needs_corpus
@pytest.mark.parametrize("name,subtune,adsr,frames", ORIGINAL)
def test_the_converter_reads_the_same_unit_off_the_orderlists(
        name, subtune, adsr, frames):
    from h2g.detect import detect
    from h2g.sidfile import load_sid
    doc = json.loads((ROOT / "presets.json").read_text(encoding="utf-8"))
    with warnings.catch_warnings():
        warnings.simplefilter("ignore")
        opts = fidelity._preset_opts(doc, name + ".sid")
    song = songview.parse_sng(convert(str(CORPUS / f"{name}.sid"),
                                      log=lambda *a, **k: None, **opts))
    sid = load_sid(str(CORPUS / f"{name}.sid"))
    det = detect(sid, lambda *a, **k: None)
    det.drum_gate_off = True
    units = drum_unit.drum_first_units(sid, det, song.tracks, song.patterns)
    record = [i.number for i in song.instruments if i.adsr == "$" + adsr]
    assert record and all(units[n] == frames for n in record), (units, record)
