"""The command-table engine's `$82 a b` chord arpeggio (h2g/cmd_chord.py).

Chicken Song's voice 2 cycles a three-note chord one note per frame on every
chorded note; until this pass the conversion held one pitch through all of
them (1169 of the voice's 2126 gated frames more than half a semitone off at
-t 60 under presets, at the harness's own startup lag). These pin the reader
(cells, commands, the intro waveform), the per-note walk (the rotation, the
enable carried across patterns, Hollywood or Bust's re-arm command), the
emission, and -- through the packed player -- the pitch itself.
"""
import json
import math
import pathlib
import sys

import pytest

from corpus import CORPUS, needs_corpus

PYTHON_ROOT = pathlib.Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PYTHON_ROOT))

import fidelity                                              # noqa: E402
from h2g import cmd_chord                                    # noqa: E402
from h2g.convert import convert                              # noqa: E402
from h2g.detect import detect                                # noqa: E402
from h2g.goatwriter.constants import WAVE_JUMP               # noqa: E402
from h2g.goatwriter.drums import _chord_block                # noqa: E402
from h2g.patterns import command_floor                       # noqa: E402
from h2g.sidfile import load_sid                             # noqa: E402
from h2g.tracks import convert_tracks                        # noqa: E402

PRESETS = PYTHON_ROOT.parent / "presets.json"
CMD_SETWAVEPTR = 8


def _walk(name):
    sid = load_sid(str(CORPUS / name))
    det = detect(sid, lambda m: None)
    ch = cmd_chord.find_cmd_chord(sid, det)
    tracks = convert_tracks(sid, det, lambda m: None)
    floor = command_floor(det.read_track_version, det.track_fd_transpose)
    return sid, det, ch, cmd_chord.chord_note_cycles(sid, det, ch, tracks, floor)


@needs_corpus
def test_the_reader_names_the_cells_and_commands():
    """Chicken Song $13D8/$144B/$1470 and Hollywood or Bust $07D8/$0868/
    $088D/$0874; the intro is Chicken Song's bit-$01 block ($133B), three
    frames of `$15ED,X` = $81 $11 $81."""
    sid, det, ch, _ = _walk("Chicken_Song.sid")
    assert (ch.cmd, ch.off, ch.resume) == (2, 4, -1)
    assert (ch.enable, ch.counter) == (0x15E3, 0x15E6)
    assert ch.cells == (0x15DA, 0x15DD, 0x15E0)
    assert ch.op_cells == (0x15DD, 0x15E0)
    assert (ch.intro_table, ch.intro_frames, ch.effect_offset) == (0x15ED, 3, 7)
    assert [cmd_chord._byte(sid, 0x15ED + v) for v in range(3)] == [0x81, 0x11, 0x81]
    sid, det, ch, _ = _walk("Hollywood_or_Bust.sid")
    assert (ch.cmd, ch.off, ch.resume) == (2, 4, 6)
    assert (ch.enable, ch.counter) == (0x09C3, 0x09C6)
    assert ch.intro_table == -1


@needs_corpus
def test_no_other_corpus_file_carries_the_chord():
    hits = []
    for p in sorted(CORPUS.glob("*.sid")):
        sid = load_sid(str(p))
        try:
            det = detect(sid, lambda m: None)
        except Exception:                                    # noqa: BLE001
            continue
        if cmd_chord.find_cmd_chord(sid, det) is not None:
            hits.append(p.name)
    assert hits == ["Chicken_Song.sid", "Hollywood_or_Bust.sid"]


@needs_corpus
def test_chicken_song_reads_one_rotation_on_voice_2():
    """Every duration is a multiple of 3 and one voice is chorded at a time,
    so every chorded note reads (op 2, op 1, 0) from its fetch frame -- the
    rotation the original's trace shows on all 51 chord runs of the first
    60 s (frame 420: $22D0 $2BD6 $3426, -7 -3 0)."""
    _sid, _det, _ch, cyc = _walk("Chicken_Song.sid")
    notes = [(p, k, v) for p, per in cyc.items() for k, v in per.items()]
    assert len(notes) == 57
    for _p, _k, (cycle, voice, record) in notes:
        assert voice == 1
        assert cycle[2] == 0 and cycle[0] < cycle[1] < 0, cycle
        assert record is not None
    # Pattern 5 ends with the enable set and $1D (29) and $0E (14), which
    # carry no chord command, follow it: the player plays them chorded.
    assert 29 in cyc and 14 in cyc


@needs_corpus
def test_hollywoods_re_arm_command_keeps_the_operands():
    """`$86` (command 6, $0874) is the setter's own tail: enable on, the
    operands kept. Pattern $11's fourth note follows `$84 ... $86` with no
    `$82`, and the original plays it chorded on the operands of the second
    (frames 36-47 of subtune 2: $1388 $106E $1A13, +3 0 +8)."""
    _sid, _det, _ch, cyc = _walk("Hollywood_or_Bust.sid")
    assert cyc[17][3][:2] == ((3, 0, 8), 2)


def test_the_chord_block_starts_on_call_0_and_loops_whole_cycles():
    """Call c is the original's frame c (see _chord_block): the intro on
    calls 0-2, the record's waveform after, and a three-call cycle jumping
    back to itself."""
    arp = cmd_chord.ChordArp((0, 4, 7), 0x11, 3)
    left, right = _chord_block([(0x41, 0), (0x41, 0), (0x41, 0),
                                (WAVE_JUMP, 0)], arp, 1, 10)
    assert left == [0x11, 0x11, 0x11, 0x41, 0x41, 0x41, WAVE_JUMP]
    assert right == [0, 4, 7, 0, 4, 7, 13]
    plain = cmd_chord.ChordArp((0, 0x7C - 0x80, 3))
    left, right = _chord_block([(0x41, 0), (WAVE_JUMP, 0)], plain, 1, 20)
    assert left == [0x41, 0x41, 0x41, WAVE_JUMP]
    assert right == [0, 0x7C, 3, 20]


@needs_corpus
def test_chicken_song_carries_the_chords_under_presets():
    import songview
    doc = json.loads(PRESETS.read_text(encoding="utf-8"))
    sng = convert(str(CORPUS / "Chicken_Song.sid"), log=lambda m: None,
                  **fidelity._preset_opts(doc, "Chicken_Song.sid"))
    song = songview.parse_sng(sng)
    rows = [(p[r + 2], p[r + 3]) for p in song.patterns
            for r in range(0, len(p) - 3, 4) if p[r + 2] == CMD_SETWAVEPTR]
    assert len(rows) == 57
    wt = song.tables["WTBL"]
    intro = 0
    for _c, row in rows:
        block = wt[row - 1:row + 3]
        # Records 5 and 10 carry effect bit $01 (the $11 intro); the others
        # (9's pulse, and the noise records patterns $1D/$0E play while the
        # enable pattern 5 left set is still on) do not, and their block is
        # the cycle alone on the record's own waveform.
        if block[0][0] == 0x11:
            intro += 1
            assert [w for w, _n in block[:3]] == [0x11, 0x11, 0x11]
            assert block[3][0] == 0x41
        else:
            assert len({w for w, _n in block[:3]}) == 1
            assert block[3] == (WAVE_JUMP, row)
    assert intro == 38


needs_tools = pytest.mark.skipif(
    not (pathlib.Path(fidelity.SIDDUMP).exists()
         and pathlib.Path(fidelity.GT2RELOC).exists()),
    reason="needs siddump and gt2reloc")


@needs_corpus
@needs_tools
def test_voice_2_plays_the_originals_pitch_through_the_packed_player(tmp_path):
    """-t 30 of Chicken Song under presets, at `startup_lag`: every gated
    frame of voice 2 within half a semitone of the original's (1169 of 2126
    were not over 60 s before the chords were emitted)."""
    name = "Chicken_Song.sid"
    doc = json.loads(PRESETS.read_text(encoding="utf-8"))
    sng = convert(str(CORPUS / name), log=lambda m: None,
                  **fidelity._preset_opts(doc, name))
    sng, _ = fidelity.legalise_restarts(sng)
    packed = fidelity.pack_sid(sng, tmp_path, fidelity.GT2RELOC,
                               fidelity._preset_multiplier(doc, name))
    assert packed is not None and packed.exists()
    seconds, n = 30, 30 * 50
    o = fidelity.run_siddump(CORPUS / name, seconds, 0)
    h = fidelity.run_siddump(packed, seconds, 0)
    lag, _raw = fidelity.startup_lag(o, h)
    fo = fidelity.register_timeline(o[1].freq_events, n + lag + 2)
    wo = fidelity.register_timeline(o[1].wf_events, n + lag + 2)
    fh = fidelity.register_timeline(h[1].freq_events, n + lag + 2)
    gated = off = 0
    for f in range(n - lag):
        if not wo[f] & 1 or not fo[f] or not fh[f + lag]:
            continue
        gated += 1
        if abs(12 * math.log2(fh[f + lag] / fo[f])) > 0.5:
            off += 1
    assert gated > 900
    assert off == 0, f"{off} of {gated} gated frames off pitch at lag {lag}"
