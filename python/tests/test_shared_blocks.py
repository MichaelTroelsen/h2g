"""`shared_blocks`: identical instrument blocks stored once so `drum_long` fits.

Thrust's wavetable is 255 rows of 255, and ten of them are copies: the six-row
drum program `41 00 / 01 80 / 81 00 / 04 80 / 40 00 / FF 00` carried by
instruments 1, 2 and 8, and the five-row `41 00 / 01 00 / 41 00 / FF 00 /
FF 00` by seven vibrato records. `drum_long_plan` found no room for a sweep
chain and returned None, so the `$0908` kick (record 02, effect `$01`), whose
frequency high byte falls a step a frame in the original, played flat: 811 of
the original's 3454 ties no conversion tie matched at -t 180 (voice 1, key
`$0908`).

The pass is taken only after a plan found no room, so a file whose plan fits is
byte for byte what it was.
"""
import itertools
import json
import pathlib
import sys

import pytest

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[1]))

import fidelity                                              # noqa: E402
from corpus import CORPUS, needs_corpus                      # noqa: E402
from h2g.convert import convert                              # noqa: E402
from h2g.goatwriter import shared_blocks                     # noqa: E402
from h2g.goatwriter.constants import (CMD_SETWAVEPTR,       # noqa: E402
                                      GT_MAX_TABLELEN, GT_WAVE_JUMP,
                                      WAVECMD_PORTADOWN)
from songview import parse_sng                                # noqa: E402

THRUST = CORPUS / "Thrust.sid"
REPO_ROOT = pathlib.Path(__file__).resolve().parents[2]

DRUM = [(0x41, 0), (0x01, 0x80), (0x81, 0), (0x04, 0x80), (0x40, 0),
        (GT_WAVE_JUMP, 0)]


def _table():
    """rows 1-6 drum, 7-12 the same drum, 13-14 a one-off, 15-17 a block
    that jumps to its own first row (kept, and must be retargeted)."""
    return (list(DRUM) + list(DRUM) + [(0x15, 0), (GT_WAVE_JUMP, 0)]
            + [(0x41, 0), (0x01, 0), (GT_WAVE_JUMP, 15)])


def test_copy_is_removed_and_its_record_repointed():
    plan = shared_blocks.plan_shared_blocks(_table(), [1, 7, 13, 15], 0, [])
    assert plan is not None
    assert plan.rows == 6
    assert plan.shared == (1,)
    assert plan.starts == [1, 1, 7, 9]
    assert len(plan.entries) == 11


def test_jump_inside_a_kept_block_is_renumbered():
    plan = shared_blocks.plan_shared_blocks(_table(), [1, 7, 13, 15], 0, [])
    assert plan.entries[-1] == (GT_WAVE_JUMP, 9)
    assert plan.row_map[15] == 9


def test_a_block_something_points_into_is_kept():
    # A pattern's CMD_SETWAVEPTR operand landing in the copy keeps it.
    plan = shared_blocks.plan_shared_blocks(_table(), [1, 7, 13, 15], 0, [],
                                            operands=[9])
    assert plan is None


def test_no_copies_is_none():
    entries = [(0x41, 0), (GT_WAVE_JUMP, 0), (0x81, 0), (GT_WAVE_JUMP, 0)]
    assert shared_blocks.plan_shared_blocks(entries, [1, 3], 0, []) is None


def _opts(**kw):
    doc = json.loads((REPO_ROOT / "presets.json").read_text(encoding="utf-8"))
    opts = fidelity._preset_opts(doc, THRUST.name)
    return {**opts, **kw}


def _sweep_heads(blob):
    song = parse_sng(blob)
    wave = song.tables["WTBL"]
    heads = 0
    for pat in song.patterns:
        for r in range(0, len(pat) - 3, 4):
            if pat[r + 2] != CMD_SETWAVEPTR or not pat[r + 3]:
                continue
            at = pat[r + 3] - 1
            while wave[at][1] == 0x80 and wave[at][0] >= 0x10:
                at += 1
            if wave[at][0] == GT_WAVE_JUMP and wave[at][1]:
                tgt = wave[at][1] - 1
                if wave[tgt][0] == WAVECMD_PORTADOWN:
                    heads += 1
    return heads, len(wave)


@needs_corpus
def test_thrust_default_has_no_sweep():
    # Thrust ships drum_long since v0.5.686; held off, no sweep is laid.
    assert _opts().get("drum_long")
    blob = convert(str(THRUST), log=lambda m: None, **_opts(drum_long=False))
    heads, rows = _sweep_heads(blob)
    assert heads == 0
    assert rows == GT_MAX_TABLELEN


@needs_corpus
def test_thrust_drum_long_finds_room_by_sharing():
    log = []
    blob = convert(str(THRUST), log=log.append, **_opts(drum_long=True))
    heads, rows = _sweep_heads(blob)
    assert heads == 25
    assert rows <= GT_MAX_TABLELEN
    assert any("Shared wavetable blocks" in line for line in log)
    # the kick's chain: one PORTADOWN run of the room the copies left
    wave = parse_sng(blob).tables["WTBL"]
    run = max(len(list(g)) for k, g in itertools.groupby(
        e[0] == WAVECMD_PORTADOWN for e in wave) if k)
    assert run >= 24


def _programs(blob):
    """{(pattern, row): wavetable entries from the SETWAVEPTR operand to the
    first `$FF` jump, the jump's target left out}."""
    song = parse_sng(blob)
    wave = song.tables["WTBL"]
    out = {}
    for pi, pat in enumerate(song.patterns):
        for r in range(0, len(pat) - 3, 4):
            if pat[r + 2] != CMD_SETWAVEPTR or not pat[r + 3]:
                continue
            at = pat[r + 3] - 1
            prog = []
            while at < len(wave) and wave[at][0] != GT_WAVE_JUMP:
                prog.append(wave[at])
                at += 1
            out[(pi, r // 4)] = tuple(prog)
    return out


GREMLINS = CORPUS / "Gremlins.sid"


@needs_corpus
def test_gremlins_existing_pointers_still_reach_their_programs():
    """Gremlins carries 39 CMD_SETWAVEPTR rows of its own; sharing six records'
    blocks renumbers the rows under them, and each must still run the program
    it ran."""
    doc = json.loads((REPO_ROOT / "presets.json").read_text(encoding="utf-8"))
    opts = fidelity._preset_opts(doc, GREMLINS.name)
    log = []
    before = _programs(convert(str(GREMLINS), log=lambda m: None, **opts))
    after = _programs(convert(str(GREMLINS), log=log.append,
                              **{**opts, "drum_long": True}))
    assert len(before) == 39
    assert any("Shared wavetable blocks" in line for line in log)
    assert {k: v for k, v in before.items() if after.get(k) != v} == {}


def _instrument_programs(blob):
    """{instrument number: the wavetable entries its record runs, to the
    first `$FF` jump}."""
    song = parse_sng(blob)
    wave = song.tables["WTBL"]
    out = {}
    for ins in song.instruments:
        at = ins.wave_ptr
        prog = []
        while at and at <= len(wave) and wave[at - 1][0] != GT_WAVE_JUMP:
            prog.append(wave[at - 1])
            at += 1
        out[ins.number] = tuple(prog)
    return out


@needs_corpus
@pytest.mark.parametrize("path", [THRUST, GREMLINS], ids=lambda p: p.stem)
def test_every_instrument_still_runs_its_program(path):
    """The row holders beside the records (phase clones, attack holds, ...)
    are renumbered with the table: an instrument built on one of them
    runs the same program after the copies go."""
    doc = json.loads((REPO_ROOT / "presets.json").read_text(encoding="utf-8"))
    opts = fidelity._preset_opts(doc, path.name)
    before = _instrument_programs(convert(str(path), log=lambda m: None,
                                          **opts))
    log = []
    after = _instrument_programs(convert(str(path), log=log.append,
                                         **{**opts, "drum_long": True}))
    assert any("Shared wavetable blocks" in line for line in log)
    assert {k: v for k, v in before.items() if after.get(k) != v} == {}
