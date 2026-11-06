"""A `$68` note's vibrato sweeps a multiple of the table interval, and the
conversion carries that multiple.

The classic vibrato depth is `(freq(n + 1) - freq(n)) >> shift`, the table
read with the same unbounded index as the note. For `$68` that reads past the
table onto the per-voice waveform cells, so `freq(n + 1)` is `(voice 0's note
byte << 8) | voice 2's waveform` and the sweep is `$1530` (Devils_Galop's
opening, `$56` / `$41` / `$11`) where B-5's table interval is `$03E8` -- 5.4
times, a `$02A6` step a frame in a siddump of the original against `$007D`
(2026-11-03, `C:/t/devils-galop-68-sweep-depth/finding.md`).
"""
import json
import pathlib
import sys

from corpus import CORPUS, needs_corpus

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[1]))

from fidelity import _preset_opts  # noqa: E402
from h2g import stored_wave  # noqa: E402
from h2g.convert import _detect_tables, convert  # noqa: E402
from h2g.patterns import STORED_DEPTH_MARK  # noqa: E402
from h2g.sidfile import load_sid  # noqa: E402
from h2g.tracks import convert_tracks  # noqa: E402
from songview import parse_sng  # noqa: E402

PRESETS = pathlib.Path(__file__).resolve().parents[2] / "presets.json"
B_5 = 71
GT_FIRST_NOTE = 0x60
CMD_VIBRATO = 4


def _walk(name):
    sid = load_sid(str(CORPUS / name))
    sid, det = _detect_tables(sid, lambda m: None)
    tracks = convert_tracks(sid, det, lambda m: None)
    land = stored_wave._applicable(sid, det)
    means: dict = {}
    votes = stored_wave._walk(sid, det, tracks, land, True, True,
                              depth_out=means)
    return sid, det, votes, means


@needs_corpus
def test_devils_galop_sweep_mean_is_read_off_the_note_array():
    _sid, _det, votes, means = _walk("Devils_Galop.sid")
    first = [v for v in votes if v[2] == 0][0]
    assert first[6] == 0x4111 and first[7] == B_5
    # (voice 0's note $56 << 8 | voice 2's wave $41) - $4111, over the
    # note's 256 ticks (voice 0 walks $56 $57 $56 $5B $56 $57 $56 $4F).
    assert means[(first[0], first[1], first[2])] == 0x1530


@needs_corpus
def test_devils_galop_pattern_carries_the_wide_entry():
    doc = json.loads(PRESETS.read_text(encoding="utf-8"))
    blob = convert(str(CORPUS / "Devils_Galop.sid"), log=lambda m: None,
                   **_preset_opts(doc, "Devils_Galop.sid"))
    song = parse_sng(blob)
    stbl = song.tables["STBL"]
    # B-5 at 8 calls' half period, the instrument entry, and the wide one:
    # 5.4 times the interval is 2 octaves (shift 4 -> 2) and a 1.35 swing
    # factor on the half period (cmp 4 -> 6).
    assert (0x80 | 4, 4) in stbl and (0x80 | 6, 2) in stbl
    wide = stbl.index((0x80 | 6, 2)) + 1
    pat = song.patterns[song.tracks[1][0]]
    # the note is the sweep's CENTRE, one semitone above B-5 (below)
    assert pat[0] == GT_FIRST_NOTE + B_5 + stored_wave.SWEEP_CENTRE[
        "Devils Galop"]
    assert (pat[2], pat[3]) == (CMD_VIBRATO, wide)
    # the stale-note hold events carry it on, across the split pattern
    nxt = song.patterns[song.tracks[1][1]]
    assert (nxt[2], nxt[3]) == (CMD_VIBRATO, wide)
    # no mark survives into the file
    for p in song.patterns:
        for r in range(0, len(p), 4):
            assert not (p[r + 2] == CMD_VIBRATO
                        and p[r + 3] >= STORED_DEPTH_MARK)


@needs_corpus
def test_monty_gets_its_own_wide_entry():
    doc = json.loads(PRESETS.read_text(encoding="utf-8"))
    blob = convert(str(CORPUS / "Monty_on_the_Run.sid"), log=lambda m: None,
                   **_preset_opts(doc, "Monty_on_the_Run.sid"))
    stbl = parse_sng(blob).tables["STBL"]
    # mean $1500 against B-5's $03E8: 5.4 times as well
    assert (0x80 | 6, 2) in stbl


@needs_corpus
def test_untraced_files_keep_the_table_interval():
    """Gerry_the_Germ matches the same shapes and has not been traced: carried
    there its `bend` went 0.44 -> 0.23. It stays on the instrument's entry."""
    sid, det, votes, means = _walk("Gerry_the_Germ.sid")
    assert means and votes
    wide = {}
    for (_g, _v, _t, _p, e, o, _f, d) in votes:
        wide.setdefault(e, {})[o] = d
    assert stored_wave.sweep_depths(sid, det, votes, wide, means) == {}


@needs_corpus
def test_devils_galop_sweep_is_centred_not_based():
    """The original sweeps `$4111 + k * $02A6`, k = 0 1 2 3 3 2 1 0 -- never
    below B-5 -- and Goattracker's vibrato is symmetric about its note, so
    the note is raised by the sweep's centre (1.5 steps = 1.0 semitone of
    B-5's `$03E8` interval). Without it the file plays B-5 and swings both
    ways around it: melody 99.957% -> 100%, per-frame octave error over the
    first 511 frames 0.090 -> 0.069 (2026-11-04)."""
    assert stored_wave.SWEEP_CENTRE == {"Devils Galop": 1}
    step, interval = 0x02A6, 0x03E8
    assert round(1.5 * step / interval) == stored_wave.SWEEP_CENTRE[
        "Devils Galop"]
    doc = json.loads(PRESETS.read_text(encoding="utf-8"))
    blob = convert(str(CORPUS / "Devils_Galop.sid"), log=lambda m: None,
                   **_preset_opts(doc, "Devils_Galop.sid"))
    song = parse_sng(blob)
    assert song.patterns[song.tracks[1][0]][0] == GT_FIRST_NOTE + B_5 + 1


@needs_corpus
def test_other_traced_files_keep_the_walk_note():
    """Monty_on_the_Run is traced for depth but its sweep centre is not:
    +1..+3 semitones all cost it melody (1.0 -> 0.99955) for an `aud` move of
    +0.0002. It keeps the note the walk read."""
    assert "Monty on the Run" not in stored_wave.SWEEP_CENTRE
    assert "Gerry the Germ" not in stored_wave.SWEEP_CENTRE
