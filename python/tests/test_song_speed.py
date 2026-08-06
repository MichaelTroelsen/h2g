"""The player's song-speed gate, and the per-file tempo derived from it.

The classic players do not advance their sequencer every frame: a master
counter (`DEC / BPL / LDA reload / STA counter`) gates the per-voice duration
DEC, so one duration unit -- one converted pattern row -- lasts reload+1
frames. The reload value is per subtune where init loads it from a table
(Commando $5F0F: `TAX / LDA $5514,X / STA $5517`, speeds 2,3,2,2), and a
static data byte where init never writes it (Zoids $146F).

Everything here was read out of the 6502 first and validated per voice
against siddump of the originals (Commando, Thing on a Spring, Crazy Comets,
IK+, Zoids, After 8, Pandora, Nemesis, Off the Cuff): the original's attack
gaps are exactly reload+1 times the decoded pattern rows.
"""
import pathlib
import subprocess
import sys

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[1]))

from h2g.detect import Detection
from h2g.goatwriter import (CMD_SETTEMPO, TEMPO_FASTEST_STEADY, SongSpeeds,
                            derived_group_tempos, find_song_speeds,
                            recommended_multiplier, tempo_command_value)
from h2g.sidfile import HLEN, SidFile, load_sid

REPO_ROOT = pathlib.Path(__file__).resolve().parents[2]
PYTHON_ROOT = pathlib.Path(__file__).resolve().parents[1]
COMMANDO = REPO_ROOT / "Commando.sid"
CRAZY_COMETS = REPO_ROOT / "arkiv" / "Crazy_Comets.sid"
BUMP_SET_SPIKE = REPO_ROOT / "arkiv" / "Bump_Set_Spike.sid"


def _synthetic(reload_value: int, subtunes: int = 2,
               second_gate_value=None) -> SidFile:
    """A minimal image with one speed gate and a static reload byte.

    Layout at load address $1000: the gate code names counter $1040 and
    reload $1044, whose byte is `reload_value`.
    """
    image = bytearray(0x100)
    gate = bytes([0xCE, 0x40, 0x10, 0x10, 0x06,        # DEC $1040 / BPL +6
                  0xAD, 0x44, 0x10,                    # LDA $1044
                  0x8D, 0x40, 0x10])                   # STA $1040
    image[0x00:0x0B] = gate
    image[0x44] = reload_value
    if second_gate_value is not None:
        second = bytes([0xCE, 0x80, 0x10, 0x10, 0x06,
                        0xAD, 0x84, 0x10,
                        0x8D, 0x80, 0x10])
        image[0x60:0x6B] = second
        image[0x84] = second_gate_value
    data = bytes(HLEN - 1) + bytes(image)
    return SidFile(path="synthetic", data=data, name="", author="",
                   released="", load_addr=0x1000, subtunes=subtunes)


# --- reading the gate out of real players -----------------------------------

def test_commando_speeds_come_from_the_per_subtune_table():
    speeds = find_song_speeds(load_sid(str(COMMANDO)))
    assert speeds is not None
    assert speeds.table_addr == 0x5514
    # Init: $5F0F LDA $5514,X / STA $5517 -- the table holds 2,3,2, so the
    # main tune ticks every 3 frames and subtune 1 every 4. (The repo copy
    # declares 3 subtunes; the HVSC copy declares 19 and its table over-read
    # yields None entries past the real four.)
    assert speeds.frames == (3, 4, 3)


def test_crazy_comets_speed_is_a_static_reload_byte():
    speeds = find_song_speeds(load_sid(str(CRAZY_COMETS)))
    assert speeds is not None
    assert speeds.table_addr is None
    assert set(speeds.frames) == {3}


def test_bump_set_spike_second_subtune_is_faster():
    speeds = find_song_speeds(load_sid(str(BUMP_SET_SPIKE)))
    assert speeds is not None
    assert speeds.frames == (3, 2)


def test_a_static_gate_covers_every_subtune():
    speeds = find_song_speeds(_synthetic(reload_value=1, subtunes=3))
    assert speeds is not None
    assert speeds.frames == (2, 2, 2)
    assert "static" in speeds.source


def test_an_insane_reload_byte_is_not_a_speed():
    # Table over-reads land in code; a byte like $70 would otherwise become
    # an absurd tempo.
    assert find_song_speeds(_synthetic(reload_value=0x70)) is None


def test_disagreeing_gates_without_a_detection_yield_nothing():
    # One on One carries several gate-shaped byte runs with different values;
    # guessing between them risks a wrong tempo, worse than the constant.
    sid = _synthetic(reload_value=1, second_gate_value=4)
    assert find_song_speeds(sid) is None


def test_a_detection_picks_the_nearest_gate():
    sid = _synthetic(reload_value=1, second_gate_value=4)
    near_second = Detection(instr_start=HLEN - 1 + 0x65)
    speeds = find_song_speeds(sid, near_second)
    assert speeds is not None and speeds.frames[0] == 5


# --- multiplier and command value -------------------------------------------

def test_multiplier_is_1_wherever_three_calls_fit():
    # frames >= 3 is expressible at 1x; 2 and 1 need the call rate raised
    # (Goattracker's fastest steady row is three calls).
    def sp(f):
        return SongSpeeds((f,), 0, None)
    assert recommended_multiplier(None) == 1
    assert recommended_multiplier(sp(3)) == 1
    assert recommended_multiplier(sp(6)) == 1
    assert recommended_multiplier(sp(2)) == 2
    assert recommended_multiplier(sp(1)) == 3


def test_command_value_is_frames_times_multiplier():
    sid = _synthetic(reload_value=1)          # f = 2
    speeds = find_song_speeds(sid)
    assert tempo_command_value(sid, 0, speeds, multiplier=2) == 4
    # At 1x the same tune cannot go below the floor: gplay.c:325 reads tempo
    # 0/1 as funktempo, and gplay.c:334 stops the song outright if an
    # instrument's gatetimer (always 2 here) exceeds the channel's tick.
    assert tempo_command_value(sid, 0, speeds, multiplier=1) == \
        TEMPO_FASTEST_STEADY


def test_unknown_speed_falls_back_to_the_old_constant():
    sid = _synthetic(reload_value=0x70)       # no usable gate
    assert tempo_command_value(sid) == TEMPO_FASTEST_STEADY
    assert tempo_command_value(sid, 0, None, multiplier=2) == \
        TEMPO_FASTEST_STEADY * 2


def test_derived_group_tempos_are_per_subtune():
    values, mult, note = derived_group_tempos(
        load_sid(str(COMMANDO)), Detection(), 3)
    assert values == [3, 4, 3]
    assert mult == 1
    assert "$5514" in note


# --- end to end -------------------------------------------------------------

def _run(sid, out_path, *extra):
    return subprocess.run(
        [sys.executable, "-m", "h2g", str(sid), "-o", str(out_path), "-q",
         *extra],
        cwd=str(PYTHON_ROOT), capture_output=True, text=True)


def test_auto_writes_each_subtunes_own_tempo(tmp_path):
    out = tmp_path / "c.sng"
    assert _run(COMMANDO, out, "--tempo", "auto").returncode == 0
    blob = out.read_bytes()
    # Subtune 0 ticks every 3 frames, subtune 1 every 4.
    assert bytes([CMD_SETTEMPO, 3]) in blob
    assert bytes([CMD_SETTEMPO, 4]) in blob


def test_defaults_stay_byte_exact(tmp_path):
    out = tmp_path / "d.sng"
    assert _run(COMMANDO, out).returncode == 0
    assert out.read_bytes() == (REPO_ROOT / "Commando.sng").read_bytes()
