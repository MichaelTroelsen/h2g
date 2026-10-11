"""Effect bit $02 as the rise's MIRROR: a fall of the note index.

Las_Vegas_Video_Poker $537B is Warhawk's rise block with `DEC note,X` three
times where Warhawk has `INC note,X` once, so the voice's note index drops
THREE semitones every fourth counter step (`detect._find_effect_fall`). The
file is the only one in the corpus with it. Its records $11 (effect $02, no
arpeggio), $12 ($46), $13 ($26) and $15 ($36) set the bit; they play in
subtunes 8, 9, 10, 14 and 15 and not in subtune 0, which is the one
`FIDELITY.md` measures.

It is emitted by the rise's pattern-side stair (`goatwriter/rise_stair.py`),
sign and step size read off the player. A record with an arpeggio program
takes the rise's zero-speed toneportamento; $11, which has none, takes a TIE
(`CMD_TONEPORTA 00`), because a plain program has no note entry for the new
note to be heard through.

Measured at 2b64d25 + this change (historical; C:/t/las-vegas-bit02-fall,
original at -m1, ours under presets packed and traced at -m4, 20 s, the first
140 frames of each note on a record that sets the bit):

* subtune 8, the fall alone: per-frame semitone level agrees on 301 of 411
  frames, 118/140, 120/136, 117/135 within a frame (12/411 before);
* subtune 9 297/417 (9/417 before), subtune 10 300/420 (30/420);
* corpus byte-hash under presets: 89 compared, 1 moved, Las_Vegas_Video_Poker;
  Commando unchanged; the 180 s traces of subtunes 0-7, 11, 12, 13 are
  identical to the base's and 8, 9, 10, 14, 15 differ.
"""
import json
import pathlib
import sys

import pytest

from corpus import CORPUS, needs_corpus

PYTHON_ROOT = pathlib.Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PYTHON_ROOT))

import fidelity                                              # noqa: E402
from h2g import detect as detect_mod                         # noqa: E402
from h2g.convert import _detect_tables, convert              # noqa: E402
from h2g.detect import EffectFall                            # noqa: E402
from h2g.goatwriter import rise_stair as RS                  # noqa: E402
from h2g.goatwriter.constants import (CMD_TONEPORTA,         # noqa: E402
                                      GT_FIRST_NOTE, GT_LAST_NOTE,
                                      _SONG_MAX_PATTERNS)
from h2g.sidfile import load_sid                             # noqa: E402
from songview import parse_sng                               # noqa: E402

PRESETS = PYTHON_ROOT.parent / "presets.json"
LVVP = "Las_Vegas_Video_Poker"

needs_siddump = pytest.mark.skipif(
    not pathlib.Path(fidelity.SIDDUMP).exists(),
    reason="no siddump on this machine (tools/siddump-rt, see its README)")
needs_gt2reloc = pytest.mark.skipif(
    not pathlib.Path(fidelity.GT2RELOC).exists(),
    reason="no gt2reloc on this machine")


def _det(name):
    sid = load_sid(str(CORPUS / f"{name}.sid"))
    _, det = _detect_tables(sid, lambda *a, **k: None)
    return sid, det


def _song(name, **extra):
    if not PRESETS.is_file():
        pytest.skip("presets.json not generated")
    doc = json.loads(PRESETS.read_text(encoding="utf-8"))
    opts = fidelity._preset_opts(doc, f"{name}.sid")
    opts.update(extra)
    lines = []
    sng = convert(str(CORPUS / f"{name}.sid"), log=lines.append, **opts)
    return sng, lines, doc


def _record_of(ins):
    try:
        return int(ins.name.split(":")[0], 16) - 2
    except ValueError:
        return None


def _played(song):
    """Per track, the cell (note, instrument, command, data) of every row the
    track plays, in order, and the instrument number in force at each."""
    out = []
    for track in song.tracks:
        cells, cur_of = [], []
        cur = 0
        for _v, _pos, p, r, _t in RS._played_rows(track, len(song.patterns),
                                                   song.patterns):
            cell = tuple(song.patterns[p][4 * r:4 * r + 4])
            if cell[1]:
                cur = cell[1]
            cells.append(cell)
            cur_of.append(cur)
        out.append((cells, cur_of))
    return out


def _stair_rows(monkeypatch):
    """(song, [(track, index, new cell, old cell, instrument)]): the played
    rows the stair pass changed, found by converting twice -- once with the
    pass switched off -- since a tie respell also writes `CMD_TONEPORTA 00`
    on cells of its own."""
    sng, lines, _ = _song(LVVP)
    song = parse_sng(sng)
    with monkeypatch.context() as m:
        m.setattr(RS, "rise_stair_plan", lambda *a, **k: None)
        base_sng, _, _ = _song(LVVP)
    base = parse_sng(base_sng)
    new, old = _played(song), _played(base)
    assert len(new) == len(old)
    diffs = []
    for ti, ((nc, ni), (oc, _oi)) in enumerate(zip(new, old)):
        assert len(nc) == len(oc), ti
        for k, (a, b) in enumerate(zip(nc, oc)):
            if a != b:
                diffs.append((ti, k, a, b, ni[k]))
    return song, lines, diffs


# --- the model ----------------------------------------------------------------

def test_the_step_mask_comes_from_the_player_not_the_constant():
    # A mask of 1 steps on every second counter value, a mask of 7 on every
    # eighth; the default is the rise's 3.
    assert RS.stair_steps(0, 9, frozenset(), 1) == [(2, 1), (4, 2), (6, 3),
                                                    (8, 4)]
    assert RS.stair_steps(0, 9, frozenset(), 7) == [(8, 1)]
    assert RS.stair_steps(0, 9, frozenset()) == [(4, 1), (8, 2)]


# --- reading the player ---------------------------------------------------------

class _FakeSid:
    def __init__(self, data):
        self.data = data


def _block(opcode):
    # LDA $54F7 / AND #2 / BEQ / LDA $54F9 / AND #3 / BNE / <op> $54CC,X x2
    return bytes([0xAD, 0xF7, 0x54, 0x29, 0x02, 0xF0, 0x2A,
                  0xAD, 0xF9, 0x54, 0x29, 0x03, 0xD0, 0x23]
                 + [opcode, 0xCC, 0x54] * 2 + [0xBD, 0xCC, 0x54])


@pytest.mark.parametrize("opcode,steps", [(0xDE, 2), (0xFE, None)])
def test_only_dec_reads_as_the_fall_and_the_count_is_the_dec_count(
        monkeypatch, opcode, steps):
    """The rise (`INC`, Warhawk) and the fall (`DEC`) share their head; the
    opcode is the whole discriminator, and the semitones a step are the number
    of `DEC`s, not a constant."""
    monkeypatch.setattr(detect_mod, "_effect_byte_address",
                        lambda sid, det: (0x54F7, False))
    got = detect_mod._find_effect_fall(_FakeSid(bytes(4) + _block(opcode)),
                                       None)
    if steps is None:
        assert got is None
    else:
        assert (got.steps, got.mask, got.counter, got.zp) ==             (steps, 3, 0x54F9, False)


@needs_corpus
def test_the_fall_block_is_read_off_the_player():
    sid, det = _det(LVVP)
    assert det.effect_rise is False
    assert det.effect_fall == EffectFall(at=det.effect_fall.at, steps=3,
                                         mask=3, counter=0x54F9, zp=False)
    assert sid.to_address(det.effect_fall.at) == 0x537B
    block = RS.rise_block(sid, det)
    assert block is not None
    assert (block.step, block.mask, block.counter, block.zp) == \
        (-3, 3, 0x54F9, False)
    assert block.arp is True           # the arpeggio divides the same counter
    assert sid.to_address(block.at) == 0x537B


@needs_corpus
def test_only_las_vegas_video_poker_has_the_fall():
    falling = []
    for path in sorted(CORPUS.glob("*.sid")):
        sid = load_sid(str(path))
        try:
            _, det = _detect_tables(sid, lambda *a, **k: None)
        except Exception:                                    # noqa: BLE001
            continue                    # a file the converter refuses
        if det.effect_fall is not None:
            falling.append(path.stem)
            assert det.effect_rise is False
    assert falling == [LVVP]


@needs_corpus
def test_the_rise_files_have_no_fall():
    for name in ("Warhawk", "Spellbound", "Kentilla", "Thrust",
                 "Bump_Set_Spike"):
        _, det = _det(name)
        assert det.effect_rise is True and det.effect_fall is None


@needs_corpus
def test_the_records_that_fall_and_how_each_is_moved():
    sid, det = _det(LVVP)
    block = RS.rise_block(sid, det)
    assert RS.stair_kinds(sid, det, det.instr_used, block) == {
        0x11: ("tie", 0),       # effect $02: no arpeggio program
        0x12: ("arp", 4),       # $46
        0x13: ("arp", 2),       # $26
        0x15: ("arp", 3),       # $36
    }


# --- what is emitted --------------------------------------------------------------

@needs_corpus
def test_the_fall_is_emitted_under_presets_and_logged():
    sng, lines, _ = _song(LVVP)
    log = [l for l in lines if l.startswith("Fall stair (bit $02)")]
    assert len(log) == 1
    assert "CMD_TONEPORTA 00 (tie)" in log[0] and "(speed $0000)" in log[0]
    assert "up to -" in log[0]
    assert not any(l.startswith("Rise stair") for l in lines)
    assert len(parse_sng(sng).patterns) <= _SONG_MAX_PATTERNS


@needs_corpus
def test_every_step_row_is_a_free_cell_inside_a_falling_note(monkeypatch):
    sid, det = _det(LVVP)
    block = RS.rise_block(sid, det)
    kinds = RS.stair_kinds(sid, det, det.instr_used, block)
    falling = set(kinds)
    song, _, diffs = _stair_rows(monkeypatch)
    stbl = song.tables["STBL"]
    assert len(diffs) > 100
    ties = zero = 0
    for ti, k, new, old, ins in diffs:
        assert ti // 3 != 0, "a stair row in subtune 0"
        assert old == (0xBD, 0, 0, 0), old          # it took an empty row
        note, i2, cmd, data = new
        assert GT_FIRST_NOTE <= note <= GT_LAST_NOTE and not i2
        assert cmd == CMD_TONEPORTA
        record = _record_of(song.instruments[ins - 1])
        assert record in falling
        # The arpeggio plays `low` semitones under the stepped note, and a
        # note under the lowest wraps to the top of the range.
        assert note - kinds[record][1] >= GT_FIRST_NOTE
        if data == 0:
            ties += 1
        else:
            assert stbl[data - 1] == (0, 0)
            zero += 1
    assert ties and zero
    assert len(song.patterns) <= _SONG_MAX_PATTERNS


@needs_corpus
def test_steps_descend_by_threes_from_the_note(monkeypatch):
    """Walk each track: after a note on a falling record, every step row is
    lower than the note by a multiple of three, and each lower than the
    one before (the note index fell `DEC` x3 each time)."""
    song, _, diffs = _stair_rows(monkeypatch)
    steps = {(ti, k): new[0] for ti, k, new, _o, _i in diffs}
    cells = _played(song)
    checked = 0
    for ti, (cs, _cur) in enumerate(cells):
        base = prev = None
        for k, cell in enumerate(cs):
            if (ti, k) in steps:
                assert base is not None
                note = steps[(ti, k)]
                assert (base - note) % 3 == 0 and note < prev, (ti, k)
                prev = note
                checked += 1
            elif GT_FIRST_NOTE <= cell[0] <= GT_LAST_NOTE:
                base = prev = cell[0]
    assert checked == len(steps)


# --- against the original -----------------------------------------------------------

def _semis(fq, a, k):
    import math
    base = fq[a]
    return ["?" if not (base and fq[f]) else
            round(12 * math.log2(fq[f] / base)) for f in range(a, a + k)]


@needs_corpus
@needs_siddump
@needs_gt2reloc
def test_subtune_eights_fall_follows_the_original(tmp_path):
    """Record $11 alone (no arpeggio): the original drops 3 semitones every
    5 frames (four counter steps, the outer gate running four calls of
    five). Ours, packed at the preset -S4 and traced at -m4, follows that
    level within a frame on at least 80% of the first 140 frames of the note
    (118/140 measured; without the stair it stayed within 4 frames of +0)."""
    orig = fidelity.run_siddump(CORPUS / f"{LVVP}.sid", 8, 8)
    fq_o = fidelity.register_timeline(orig[0].freq_events, 400)
    lv_o = _semis(fq_o, 1, 140)
    assert lv_o[10] == -6 and lv_o[100] == -45       # -3 per 5 frames
    sng, _, doc = _song(LVVP)
    m = fidelity._preset_multiplier(doc, f"{LVVP}.sid")
    packed = fidelity.pack_sid(sng, tmp_path, multiplier=m)
    assert packed is not None and packed.exists()
    ours = fidelity.run_siddump(packed, 8, 8, calls=m)
    fq = fidelity.register_timeline(ours[0].freq_events, 400)
    wf = fidelity.register_timeline(ours[0].wf_events, 400)
    on = next(f for f in range(1, 400) if wf[f] & 1 and not wf[f - 1] & 1)
    lv = _semis(fq, on, 140)
    near = sum(1 for i, x in enumerate(lv_o)
               if x != "?" and any(0 <= i + d < 140 and lv[i + d] == x
                                   for d in (-1, 0, 1)))
    assert near >= 0.8 * 140, near
    assert min(x for x in lv if x != "?") <= -40
