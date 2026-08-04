"""Startup tempo (--tempo N | auto).

This converter emits one pattern row per Hubbard player tick, so a row must
last one tick. Goattracker makes a row last `tempo+1` play-routine calls
(gplay.c:322-326) and defaults to 6, which is why an untempo'd conversion runs
6x slow.

The only in-file lever is the last instrument's Attack/Decay (gplay.c:221):

    if ((instr[MAX_INSTR-1].ad >= 2) && (!(instr[MAX_INSTR-1].ptr[WTBL])))
        cptr->tempo = instr[MAX_INSTR-1].ad - 1;

It does not scale with the speed multiplier, unlike the default
(`6*multiplier-1`, gplay.c:212) -- so it sets calls-per-row absolutely.
"""
import pathlib
import struct
import subprocess
import sys

import pytest

from h2g.goatwriter import (GT_MIN_TEMPO, GT_TEMPO_INSTRUMENT,
                            TEMPO_ONE_TICK_PER_ROW, tempo_for)
from h2g.sidfile import load_sid

REPO_ROOT = pathlib.Path(__file__).resolve().parents[2]
PYTHON_ROOT = pathlib.Path(__file__).resolve().parents[1]
SID_PATH = REPO_ROOT / "Commando.sid"
REFERENCE_SNG_PATH = REPO_ROOT / "Commando.sng"


def _run(out_path, *extra):
    return subprocess.run(
        [sys.executable, "-m", "h2g", str(SID_PATH), "-o", str(out_path), "-q", *extra],
        cwd=str(PYTHON_ROOT), capture_output=True, text=True,
    )


def _instruments(blob, ntables):
    pos = 4 + 32 * 3
    subtunes = blob[pos]; pos += 1
    for _ in range(subtunes):
        for _c in range(3):
            n = blob[pos]; pos += 1; pos += n + 1
    count = blob[pos]; pos += 1
    instr = []
    for _ in range(count):
        instr.append(blob[pos:pos + 9]); pos += 9 + 16
    for _ in range(ntables):
        t = blob[pos]; pos += 1; pos += 2 * t
    npatt = blob[pos]; pos += 1
    for _ in range(npatt):
        rows = blob[pos]; pos += 1; pos += rows * 4
    assert pos == len(blob), f"trailing data: parsed {pos} of {len(blob)}"
    return instr


# --- PSID speed field ------------------------------------------------------

def test_speed_field_is_parsed():
    sid = load_sid(str(SID_PATH))
    raw = SID_PATH.read_bytes()
    assert sid.speed == struct.unpack(">I", raw[0x12:0x16])[0]
    # Commando is plain 50Hz VBI on every subtune.
    assert sid.speed == 0
    assert not sid.is_cia_timed(0)


def test_cia_bit_is_per_subtune():
    sid = load_sid(str(SID_PATH))
    sid.speed = 0b1010
    assert not sid.is_cia_timed(0)
    assert sid.is_cia_timed(1)
    assert not sid.is_cia_timed(2)
    assert sid.is_cia_timed(3)
    # Subtunes past 31 reuse bit 31, per the PSID spec.
    sid.speed = 1 << 31
    assert sid.is_cia_timed(31)
    assert sid.is_cia_timed(40)


def test_tempo_for_is_one_tick_per_row():
    sid = load_sid(str(SID_PATH))
    assert tempo_for(sid) == TEMPO_ONE_TICK_PER_ROW == GT_MIN_TEMPO


# --- output ----------------------------------------------------------------

def test_no_tempo_by_default_and_fixture_unchanged(tmp_path):
    out = tmp_path / "d.sng"
    assert _run(out).returncode == 0
    assert out.read_bytes() == REFERENCE_SNG_PATH.read_bytes()


def test_auto_writes_tempo_into_instrument_63(tmp_path):
    out = tmp_path / "t.sng"
    assert _run(out, "--tempo", "auto").returncode == 0
    instr = _instruments(out.read_bytes(), 3)
    assert len(instr) == GT_TEMPO_INSTRUMENT
    last = instr[GT_TEMPO_INSTRUMENT - 1]
    assert last[0] == TEMPO_ONE_TICK_PER_ROW, "AD byte carries the tempo"
    # Goattracker ignores the override unless the wavetable pointer is 0.
    assert last[2] == 0


def test_explicit_tempo_value(tmp_path):
    out = tmp_path / "t6.sng"
    assert _run(out, "--tempo", "6").returncode == 0
    instr = _instruments(out.read_bytes(), 3)
    assert instr[GT_TEMPO_INSTRUMENT - 1][0] == 6


def test_padding_instruments_are_inert(tmp_path):
    """Padding must not claim table space or Goattracker plays garbage."""
    out = tmp_path / "p.sng"
    assert _run(out, "--tempo", "auto").returncode == 0
    instr = _instruments(out.read_bytes(), 3)
    real = 14  # Commando: 13 ripped instruments plus the Clear Voice slot
    for i in range(real, GT_TEMPO_INSTRUMENT - 1):
        assert instr[i] == bytes(9), f"padding instrument {i+1} is not blank"
    for b in instr[real:]:
        assert b[2] == 0 and b[3] == 0 and b[4] == 0, "padding must own no tables"


def test_tempo_preserves_musical_content(tmp_path):
    """Only the instrument section may change; tracks and patterns must not."""
    a, b = tmp_path / "a.sng", tmp_path / "b.sng"
    assert _run(a).returncode == 0
    assert _run(b, "--tempo", "auto").returncode == 0
    ba, bb = a.read_bytes(), b.read_bytes()
    # 49 padding instruments at 25 bytes each.
    assert len(bb) - len(ba) == (GT_TEMPO_INSTRUMENT - 14) * 25
    # Orderlists are ahead of the instrument section, so that prefix is identical.
    head = 4 + 32 * 3
    assert ba[:head] == bb[:head]
    # Patterns are the tail and must survive byte-for-byte.
    assert ba[-4000:] == bb[-4000:]


def test_tempo_composes_with_gts5(tmp_path):
    out = tmp_path / "g.sng"
    assert _run(out, "--tempo", "auto", "--format", "gts5").returncode == 0
    blob = out.read_bytes()
    assert blob[:4] == b"GTS5"
    instr = _instruments(blob, 4)
    assert instr[GT_TEMPO_INSTRUMENT - 1][0] == TEMPO_ONE_TICK_PER_ROW


@pytest.mark.parametrize("bad", ["0", "1", "256", "-1", "fast"])
def test_rejected_tempo_values(tmp_path, bad):
    """0 and 1 select funktempo in Goattracker, so they must not be accepted."""
    out = tmp_path / "x.sng"
    assert _run(out, "--tempo", bad).returncode != 0
    assert not out.exists()
