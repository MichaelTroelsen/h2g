"""A 2-call row, through CMD_FUNKTEMPO on a `02 02` speed entry.

CMD_SETTEMPO's fastest steady row is 3 calls, so a subtune whose player
ticks every 2 frames clamped to 3 whenever the file is packed at -S1 -- the
start-subtune rule (`goatwriter.pack_subtune`) picks one rate per file.
5_Title_Tunes' players 1 and 4 played 1.5x slow (melody 80.6 / 81.7 at
-t 180, v0.5.509). Goattracker's own recipe (readme.txt:1078-1081) gives the
2-call row through the other door: CMD_FUNKTEMPO pointing at `02 02`, every
instrument on gatetimer 1, gt2reloc `-O0` (always passed here).

What is pinned:

  1. the placeholder: `tempo_command_value(funk=True)` passes EXACTLY two calls
     as `FUNK_ROW_CALLS`, and `write_funktempo` turns it into CMD_FUNKTEMPO on
     one shared `02 02` entry (or the steady floor when the table is full);
  2. the rate rules that call 2 a row now (`_scaled_step`);
  3. the SAFETY bound: a 2-call row's counter never reaches gatetimer 2
     (player.s:1090-1098), so a voice under such an instrument never fetches
     its next row. `instrument_row_calls` must charge instrument 1 to a
     subtune whose voice opens without naming one (player.s:618-621), and the
     instrument writer must look the bound up under the Goattracker number --
     it read the slot before (`i + lead`) until this task;
  4. on the corpus, every funk subtune's instruments obey 3, and which files
     and subtunes carry a funk row;
  5. on a trace, those subtunes play at the original's pace with every voice
     sounding.
"""
import json
import pathlib
import shutil
import sys

import pytest

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[1]))

from corpus import CORPUS, needs_corpus  # noqa: E402

from h2g.goatwriter import tempo as T  # noqa: E402
from h2g.goatwriter.appending import _parse_song  # noqa: E402
from h2g.goatwriter.constants import (CMD_FUNKTEMPO, CMD_SETTEMPO,  # noqa: E402
                                      FUNK_ROW_CALLS, FUNK_SPEED_ENTRY,
                                      GT_MAX_TABLELEN, TEMPO_FASTEST_STEADY)
from h2g.patterns import GT_ORDER_RESTART, _scaled_step  # noqa: E402
from h2g.tracks import instrument_row_calls  # noqa: E402

ROOT = pathlib.Path(__file__).resolve().parents[2]

# file -> the subtunes whose patterns carry CMD_FUNKTEMPO under presets.json
FUNK_SUBTUNES = {
    "5_Title_Tunes.sid": {1, 4},
    "Auf_Wiedersehen_Monty.sid": {12},
    "Gerry_the_Germ.sid": {2},
    "Human_Race.sid": {4},
}


def _speeds(*frames):
    return T.SongSpeeds(tuple(frames), 0, None)


def test_only_an_exact_two_call_row_becomes_the_placeholder():
    value = lambda f, m, funk: T.tempo_command_value(  # noqa: E731
        None, 0, _speeds(f), m, False, funk)
    assert value(2, 1, True) == FUNK_ROW_CALLS
    assert value(1, 2, True) == FUNK_ROW_CALLS          # 2 calls at -S2
    assert value(2, 1, False) == TEMPO_FASTEST_STEADY   # GTS2: no speed table
    assert value(1, 1, True) == TEMPO_FASTEST_STEADY    # 1 call: no door
    assert value(3, 1, True) == 3 and value(4, 1, True) == 4


def _row(cmd, data, instr=0):
    return [0xBD, instr, cmd, data]


def test_write_funktempo_points_every_placeholder_at_one_shared_entry():
    a = _row(CMD_SETTEMPO, FUNK_ROW_CALLS) + _row(0, 0)
    b = _row(CMD_SETTEMPO, FUNK_ROW_CALLS)
    c = _row(CMD_SETTEMPO, 3)
    table = [(0, 0x40)]
    assert T.write_funktempo([a, b, c], table) == 2
    assert table == [(0, 0x40), FUNK_SPEED_ENTRY]
    assert a[2:4] == [CMD_FUNKTEMPO, 2] and b[2:4] == [CMD_FUNKTEMPO, 2]
    assert c[2:4] == [CMD_SETTEMPO, 3]
    # An entry already there is reused, not duplicated.
    d = _row(CMD_SETTEMPO, FUNK_ROW_CALLS)
    assert T.write_funktempo([d], table) == 1 and len(table) == 2
    assert d[2:4] == [CMD_FUNKTEMPO, 2]


def test_write_funktempo_keeps_the_steady_floor_when_the_table_is_full():
    a = _row(CMD_SETTEMPO, FUNK_ROW_CALLS)
    table = [(0, k) for k in range(GT_MAX_TABLELEN)]
    assert T.write_funktempo([a], table) == 0
    assert a[2:4] == [CMD_SETTEMPO, TEMPO_FASTEST_STEADY]
    assert len(table) == GT_MAX_TABLELEN


def test_a_two_call_row_compensates_the_call_its_slide_loses():
    # One call of two runs effects (player.s:982-987), so the step doubles.
    assert _scaled_step(0x100, 1, 2) == (0x02, 0x00)
    assert _scaled_step(0x100, 1, 3) == (0x01, 0x80)
    for rc in (0, 1):
        assert _scaled_step(0x100, 1, rc) == (0x01, 0x00)


def _track(*pats):
    return list(pats) + [GT_ORDER_RESTART, 0]


def test_instrument_1_is_charged_to_a_subtune_whose_voice_opens_unnamed():
    p0 = [0x30, 2, 0, 0]                       # names instrument 2
    p1 = [0xBD, 0, 0, 0, 0x30, 3, 0, 0]        # rests on the default first
    p2 = [0x30, 4, 0, 0]
    tracks = [_track(0), _track(0), _track(0),            # subtune 0, 4 calls
              _track(1), _track(2), _track(0)]            # subtune 1, 2 calls
    got = instrument_row_calls(tracks, [p0, p1, p2], [4, 2])
    assert got == {1: 2, 2: 2, 3: 2, 4: 2}
    # Without the unnamed opening, instrument 1 is nobody's.
    tracks[3] = _track(2)
    assert 1 not in instrument_row_calls(tracks, [p0, p1, p2], [4, 2])


def _subtune_parts(song, s):
    pats = {b for t in song.tracks[3 * s:3 * s + 3]
            for b in t[:t.index(0xFF)] if b < 0xD0}
    named = {song.patterns[p][r + 1] for p in pats
             for r in range(0, len(song.patterns[p]), 4)} - {0}
    implicit = any(not song.patterns[t[0]][1]
                   for t in song.tracks[3 * s:3 * s + 3] if t[0] < 0xD0)
    funk = {song.patterns[p][r + 3] for p in pats
            for r in range(0, len(song.patterns[p]), 4)
            if song.patterns[p][r + 2] == CMD_FUNKTEMPO}
    return named | ({1} if implicit else set()), funk


def _convert_all(**extra):
    import fidelity as F
    from h2g.convert import convert
    doc = json.loads((ROOT / "presets.json").read_text())
    return {name: convert(str(CORPUS / name), log=lambda m: None,
                          **dict(F._preset_opts(doc, name), **extra))
            for name in FUNK_SUBTUNES}


@pytest.fixture(scope="module")
def conversions():
    return _convert_all()


@needs_corpus
@pytest.mark.parametrize("extra", [{}, {"compact_instruments": False}],
                         ids=["presets", "clear-voice-lead"])
def test_every_instrument_a_funk_subtune_runs_under_has_gatetimer_1(extra):
    """Under presets every one of these files has `lead` 0; without
    `compact_instruments` instrument 1 is the Clear Voice slot, which a voice
    opening on rests runs under, so it is checked through the same rule."""
    for name, blob in _convert_all(**extra).items():
        song = _parse_song(blob)
        carries = set()
        for s in range(len(song.tracks) // 3):
            instruments, funk = _subtune_parts(song, s)
            if not funk:
                continue
            carries.add(s)
            for idx in funk:
                assert song.tables[3][idx - 1] == FUNK_SPEED_ENTRY, (name, s)
            slow = {i: song.instruments[i - 1][7] for i in instruments
                    if song.instruments[i - 1][7] & 0x3F > 1}
            assert not slow, f"{name} subtune {s}: gatetimers {slow}"
        assert carries == FUNK_SUBTUNES[name], name


@needs_corpus
def test_funk_subtunes_play_at_the_original_pace_with_every_voice(conversions,
                                                                  tmp_path):
    import fidelity as F
    if not (pathlib.Path(F.SIDDUMP).exists()
            and pathlib.Path(F.GT2RELOC).exists()):
        pytest.skip("siddump or gt2reloc not available")
    doc = json.loads((ROOT / "presets.json").read_text())
    for name, subs in FUNK_SUBTUNES.items():
        src = CORPUS / name
        mult = F._skip_gate_multiplier(src) or 1
        assert mult == 1, name                 # every funk file packs at -S1
        wd = tmp_path / name
        wd.mkdir()
        packed = F.pack_sid(F.legalise_restarts(conversions[name])[0], wd,
                            F.GT2RELOC, mult)
        local = wd / "o.sid"
        shutil.copyfile(src, local)
        cal, _ = F.table_calibration(src, F._preset_opts(doc, name))
        for s in sorted(subs):
            a = F.run_siddump(local, 30, s, F.SIDDUMP, cal)
            b = F.run_siddump(packed, 30, s, F.SIDDUMP, calls=mult)
            got = F.compare(a, b)
            assert got["melody"] >= 0.98, (name, s, got["melody"])
            for v, (x, y) in enumerate(zip(a, b)):
                if x.attack_frames:
                    assert y.attack_frames, f"{name} subtune {s} voice {v}"


def test_the_vibrato_rules_count_a_two_call_row_too():
    from h2g.goatwriter.vibrato import _classic_vibrato_entry, _effect_call_list
    # Half-period counted on one call of two (player.s:982-987).
    byte = 0x78 | 0x02                 # bound $78 >> 3 = 15, shift 2
    two, three, none = (_classic_vibrato_entry(byte, 1, rc) for rc in (2, 3, 0))
    assert two[0] < three[0] < none[0]
    assert _effect_call_list(None, 0, 7, 2) == [1, 3, 5]
    assert _effect_call_list(None, 0, 7, 0) == [1, 2, 3, 4, 5, 6]


@needs_corpus
def test_a_forced_tempo_2_stays_cmd_settempo():
    """`--tempo 2` is CMD_SETTEMPO 2 -- three calls (gplay.c:494) -- and only
    the derived path's placeholder may become CMD_FUNKTEMPO."""
    from h2g.convert import convert
    blob = convert(str(CORPUS / "Gerry_the_Germ.sid"), log=lambda m: None,
                   fmt="gts5", tempo=2, slides=True)
    song = _parse_song(blob)
    cmds = {p[r + 2] for p in song.patterns for r in range(0, len(p), 4)}
    assert CMD_FUNKTEMPO not in cmds and CMD_SETTEMPO in cmds
