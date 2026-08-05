"""Song tempo, written as CMD_SETTEMPO in the pattern data.

This converter emits one pattern row per Hubbard player tick, so a row has to
last one tick. Goattracker has no per-row duration -- the song tempo sets it --
and `gplay.c:494` applies a CMD_SETTEMPO value under $80 to all three channels
at once, so one row per subtune is enough and the setting persists.

Two things about the value, both read out of gplay.c rather than assumed:

  * `gplay.c:498` decrements the low 7 bits when they are >= 3, so a command
    value of 2 and of 3 both mean tempo 2.
  * `gplay.c:325` treats tempo 0 and 1 as **funktempo** -- alternating tick
    lengths out of funktable[] -- not as a rate. So the fastest steady row the
    format can express is tempo 2, which is three play-routine calls.

This replaces putting the tempo in instrument 63's attack/decay
(`gplay.c:221`). That route was wrong twice over: `ad = 2` gives tempo 1,
which is funktempo rather than the steady 2 calls/row it was documented as,
and reaching instrument 63 meant declaring 63 instruments -- ~1.2 KB of inert
padding that gt2reloc strips when packing to .sid, leaving the packed tune
silent. Pattern data survives relocation.
"""
import pathlib
import subprocess
import sys

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[1]))

from h2g.goatwriter import (CMD_SETTEMPO, GT_MIN_TEMPO, TEMPO_FASTEST_STEADY,
                            tempo_command_value)
from h2g.patterns import apply_tempo
from h2g.sidfile import load_sid

REPO_ROOT = pathlib.Path(__file__).resolve().parents[2]
PYTHON_ROOT = pathlib.Path(__file__).resolve().parents[1]
SID = REPO_ROOT / "Commando.sid"
REFERENCE = REPO_ROOT / "Commando.sng"

ROW = [0x60, 0x01, 0x00, 0x00]      # note, instrument, command, value


def _run(out_path, *extra):
    return subprocess.run(
        [sys.executable, "-m", "h2g", str(SID), "-o", str(out_path), "-q", *extra],
        cwd=str(PYTHON_ROOT), capture_output=True, text=True)


# --- the value -------------------------------------------------------------

def test_the_fastest_steady_tempo_is_three_calls_per_row():
    # value 3 -> decremented to 2 -> a row lasts tempo+1 = 3 calls.
    assert TEMPO_FASTEST_STEADY == 3
    assert GT_MIN_TEMPO == 2


def test_auto_picks_the_fastest_steady_tempo():
    assert tempo_command_value(load_sid(str(SID))) == TEMPO_FASTEST_STEADY


def test_funktempo_values_are_rejected(tmp_path):
    for bad in ("0", "1"):
        r = _run(tmp_path / "x.sng", "--tempo", bad)
        assert r.returncode != 0, bad
        assert "funktempo" in r.stderr.lower()


# --- where it is written ---------------------------------------------------

def test_it_lands_in_the_first_pattern_the_subtune_plays():
    patterns = [list(ROW) * 2, list(ROW) * 2]
    tracks = [[0x01, 0xFF, 0x00], [0xFF, 0x00], [0xFF, 0x00]]
    assert apply_tempo(patterns, tracks, 3) == 1
    assert patterns[1][2:4] == [CMD_SETTEMPO, 3]      # the one voice 0 plays
    assert patterns[0][2:4] == [0x00, 0x00]           # untouched


def test_every_subtune_gets_one():
    # Goattracker plays one subtune at a time and each starts its own
    # orderlist, so a tempo in subtune 0 alone would not reach subtune 1.
    patterns = [list(ROW), list(ROW)]
    tracks = ([[0x00, 0xFF, 0x00]] * 3) + ([[0x01, 0xFF, 0x00]] * 3)
    assert apply_tempo(patterns, tracks, 3) == 2
    assert patterns[0][2:4] == [CMD_SETTEMPO, 3]
    assert patterns[1][2:4] == [CMD_SETTEMPO, 3]


def test_an_existing_command_is_never_overwritten():
    # Portamento in the command column must survive; losing it would silently
    # change the music in order to fix the timing.
    patterns = [[0x60, 0x01, 0x03, 0x40]]
    tracks = [[0x00, 0xFF, 0x00], [0xFF, 0x00], [0xFF, 0x00]]
    assert apply_tempo(patterns, tracks, 3) == 0
    assert patterns[0][2:4] == [0x03, 0x40]


def test_a_subtune_playing_no_pattern_is_skipped():
    patterns = [list(ROW)]
    tracks = [[0xFF, 0x00], [0xFF, 0x00], [0xFF, 0x00]]
    assert apply_tempo(patterns, tracks, 3) == 0


def test_a_dangling_pattern_number_is_skipped():
    patterns = [list(ROW)]
    tracks = [[0x7F, 0xFF, 0x00], [0xFF, 0x00], [0xFF, 0x00]]
    assert apply_tempo(patterns, tracks, 3) == 0


# --- end to end ------------------------------------------------------------

def test_default_is_off_and_byte_exact(tmp_path):
    out = tmp_path / "d.sng"
    assert _run(out).returncode == 0
    assert out.read_bytes() == REFERENCE.read_bytes()


def test_a_tempo_changes_only_the_pattern_data(tmp_path):
    # The old mechanism padded the instrument list out to 63 entries, ~1.2 KB.
    # Writing a command instead costs nothing, so the size must not move.
    plain, tempo = tmp_path / "a.sng", tmp_path / "b.sng"
    assert _run(plain).returncode == 0
    assert _run(tempo, "--tempo", "auto").returncode == 0
    a, b = plain.read_bytes(), tempo.read_bytes()
    assert len(a) == len(b)
    assert a != b


def test_the_command_is_present_in_the_output(tmp_path):
    out = tmp_path / "t.sng"
    assert _run(out, "--tempo", "auto").returncode == 0
    assert bytes([CMD_SETTEMPO, TEMPO_FASTEST_STEADY]) in out.read_bytes()
