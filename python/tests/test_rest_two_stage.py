"""A REST replays the two-stage attack, gate off (`rest_two_stage`).

Chain_Reaction `$0C13 STA $D404,Y` is fed `$0D06,X AND $0D0F,X`. A bit-6 rest
runs the note's init tail (`$0961-$097D` reloads the record's stage-one frame
count into `$0D3A,X`), so the frame after a rest of a two-stage record sounds
the attack waveform for `count` frames with the gate off: `$40 $50 $40` where
the record's waveform is `$41` and its attack `$51`. A Goattracker KEYOFF clears
the gate and leaves the finished program at its stop, so ours stayed `$40`.
`CMD_SETWAVEPTR` on the KEYOFF row replays the program.
"""
import json
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from corpus import CORPUS, needs_corpus                      # noqa: E402
import fidelity as F                                         # noqa: E402
import songview                                              # noqa: E402
from h2g.convert import convert                              # noqa: E402
from h2g.goatwriter import rest_two_stage as RT              # noqa: E402
from h2g.goatwriter.constants import (CMD_SETTEMPO,           # noqa: E402
                                      CMD_SETWAVEPTR, GT_KEYOFF,
                                      WAVE_NOTE_KEEP)

REPO = Path(__file__).resolve().parents[2]
PRESETS = REPO / "presets.json"

# Chain_Reaction's instrument 6 as `_two_stage_entries` lays it out at -S3:
# wave, hold, attack wave, hold, wave, stop.
PROGRAM = [(0x41, 0), (0x01, 0x80), (0x51, 0), (0x01, 0x80), (0x41, 0),
           (0xFF, 0)]


def _run(entries, pointer, calls, held=0x00):
    """The waveform on each of `calls` play calls from a pointer, as
    gplay.c:697-745 steps it: a waveform entry is one call, a delay entry
    `value + 1` calls holding what is set, a jump costs none, a stop holds."""
    out, ptr, wait, cur = [], pointer, 0, held
    while len(out) < calls:
        if ptr == 0:
            out.append(cur)
            continue
        left, right = entries[ptr - 1]
        if left <= 0x0F:
            out.append(cur)
            if wait != left:
                wait += 1
                continue
            wait = 0
        else:
            cur = left
            out.append(cur)
        ptr += 1
        if entries[ptr - 1][0] == 0xFF:
            ptr = entries[ptr - 1][1]
    return out


def test_the_block_is_the_program_with_no_pitch_on_its_first_entry():
    block = RT.two_stage_block(PROGRAM, 1, delay=0)
    assert block == [(0x41, WAVE_NOTE_KEEP), (0x01, 0x80), (0x51, 0),
                     (0x01, 0x80), (0x41, 0), (0xFF, 0)]
    # a delay entry is current for `value + 1` calls (gplay.c:697-704)
    assert RT.two_stage_block(PROGRAM, 1, delay=2)[:2] == [
        (0x01, WAVE_NOTE_KEEP), (0x41, WAVE_NOTE_KEEP)]
    assert RT.REST_TWO_STAGE_DELAY == 1


@pytest.mark.parametrize("delay", [0, 1, 2])
def test_a_rest_sounds_waveform_attack_waveform_at_three_calls_a_frame(delay):
    entries = PROGRAM + RT.two_stage_block(PROGRAM, 1, delay=delay)
    calls = _run(entries, len(PROGRAM) + 1, 12, held=0x41)
    # the frame's last call is the one the register holds when it ends
    frames = [calls[k * 3 + 2] for k in range(4)]
    assert frames == [0x41, 0x51, 0x41, 0x41]


@pytest.mark.parametrize("program", [
    [(0x41, 0), (0xFF, 1)],                                  # no second stage
    [(0x41, 0), (0x01, 0x80), (0x41, 0), (0x01, 0x80), (0x41, 0), (0xFF, 0)],
    [(0x41, 0), (0x01, 0x80), (0x51, 0x30), (0x01, 0x80), (0x41, 0), (0xFF, 0)],
    [(0x41, 0), (0x01, 0x80), (0x51, 0), (0x01, 0x80), (0x41, 0), (0xFF, 3)],
    [(0x41, 0), (0x01, 0x80), (0x51, 0), (0xF2, 6), (0x41, 0), (0xFF, 0)],
])
def test_only_the_plain_shape_is_replayed(program):
    assert RT._plain_two_stage(program, 1) is None
    assert RT.two_stage_block(program, 1) == []


class _Det:
    effect_two_stage = True
    instr_start = 0
    instr_stride = 8


def _sid(effect):
    data = bytes([0, 0, 0x41, 0, 0, 0, 0, effect])
    return type("S", (), {"data": data})()


def test_only_a_record_with_the_two_stage_bit_is_named():
    assert RT.two_stage_records(_sid(0x04), _Det, PROGRAM, [1], 1, 0) == {1: 1}
    assert RT.two_stage_records(_sid(0x00), _Det, PROGRAM, [1], 1, 0) == {}
    off = type("D", (), dict(vars(_Det), effect_two_stage=False))
    assert RT.two_stage_records(_sid(0x04), off, PROGRAM, [1], 1, 0) == {}


def test_a_keyoff_row_with_a_free_column_gets_the_pointer_and_nothing_else(
        monkeypatch):
    monkeypatch.setattr(RT, "rest_reaches_stage_count", lambda sid, det: True)
    NOTE = 0x60
    pattern = [NOTE, 1, 0, 0,
               0xBD, 0, 0, 0,
               GT_KEYOFF, 0, 0, 0,                    # free: written
               NOTE, 1, 0, 0,
               GT_KEYOFF, 0, CMD_SETTEMPO, 5,         # taken: left alone
               0xFF, 0, 0, 0]
    pats, _tracks, written, entries = RT.rest_two_stages(
        _sid(0x04), _Det, [[0, 0xFF, 0]], [pattern], PROGRAM, [1], 1, 0,
        delay=0)
    assert written == 1
    assert pats[0][4 * 2 + 2:4 * 2 + 4] == [CMD_SETWAVEPTR,
                                            len(PROGRAM) + 1]
    assert pats[0][4 * 4 + 2:4 * 4 + 4] == [CMD_SETTEMPO, 5]
    assert entries[len(PROGRAM):] == RT.two_stage_block(PROGRAM, 1, delay=0)


def _sng(name):
    doc = json.loads(PRESETS.read_text(encoding="utf-8"))
    opts = F._preset_opts(doc, name)
    opts["pack"] = False
    return songview.parse_sng(convert(str(CORPUS / name), log=lambda s: None,
                                      **opts))


def _pointers(song):
    return [pat[r + 3] for pat in song.patterns
            for r in range(0, len(pat) - 3, 4)
            if pat[r] == GT_KEYOFF and pat[r + 2] == CMD_SETWAVEPTR]


@needs_corpus
@pytest.mark.parametrize("name", ["Chain_Reaction.sid", "Zoolook.sid"])
def test_the_rests_of_the_two_stage_record_replay_the_attack(name):
    """Every KEYOFF pointer names a block that plays `$41 $51 $41` a frame
    apart at the song's -S3, and the first entry carries no pitch (the delay
    entry before the waveform holds the previous one)."""
    song = _sng(name)
    wtbl = list(song.tables["WTBL"])
    # Other passes also point KEYOFF rows at blocks of their own; the ones
    # under test are those whose block is the plain two-stage program.
    ours = [p for p in set(_pointers(song))
            if wtbl[p - 1] == (RT.REST_TWO_STAGE_DELAY - 1, WAVE_NOTE_KEEP)
            and wtbl[p] == (0x41, WAVE_NOTE_KEEP)
            and wtbl[p + 2] == (0x51, 0)]
    assert ours, "no KEYOFF row points at a two-stage block"
    for p in ours:
        calls = _run(wtbl, p, 9, held=0x41)
        assert [calls[k * 3 + 2] for k in range(3)] == [0x41, 0x51, 0x41]


@needs_corpus
def test_the_rest_branch_reaches_the_stage_count_in_fifteen_players():
    """Straight-line code from the bit-6 test's target reaches the load of the
    two-stage frame count: the Chain_Reaction tail, spelled the same in these
    fifteen. The files whose rest goes elsewhere, or whose bit-6 test is not
    read, replay nothing (they moved the wrong way when it was forced)."""
    from h2g.detect import detect
    from h2g.sidfile import load_sid
    reached = []
    for path in sorted(CORPUS.glob("*.sid")):
        try:
            sid = load_sid(str(path))
            det = detect(sid, lambda *_: None)
        except Exception:                                    # noqa: BLE001
            continue
        if det.effect_two_stage and RT.rest_reaches_stage_count(sid, det):
            reached.append(path.stem)
    assert reached == [
        "Chain_Reaction", "Deep_Strike", "Delta", "Delta_Mix-E-Load_loader",
        "Dragons_Lair_Part_II", "Flash_Gordon", "Food_Feud", "Knucklebusters",
        "Lightforce", "Sigma_Seven", "Tarzan", "Thanatos", "W_A_R",
        "W_A_R_Preview", "Zoolook"]


@needs_corpus
def test_a_file_without_a_two_stage_record_is_untouched():
    assert _pointers(_sng("Rasputin.sid")) == []
