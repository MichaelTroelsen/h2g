"""Bit $02's rise under the arpeggio, emitted as a pattern-side stair
(`goatwriter.rise_stair`).

A record setting the rise AND the nibble arpeggio climbs a semitone every
four counter steps while the arpeggio alternates around the climbing note:
Spellbound $11 (effect $56) reads `+0 +0 -5 +0 -4 +1 -4 +1 -3 +2 ...` and is
+60 by the end of its 281 frames. The wavetable cannot carry it (the EMITTER
LIMIT note beside the rise branch in `goatwriter/wavetable.py`), so the
climb is a note per semitone on `CMD_TONEPORTA` naming a ZERO speed: the
note moves (`mt_chnnote`), the instrument's arpeggio program runs on and its
next note entry plays the climbed note, and nothing else is touched -- speed
`$00` would be the tie, which pulls the frequency to the note on every hold
call of the program.

Measured at 82d60ac + this change (historical; C:/t/rise-arp-pattern-stair,
`probes/ab_climb.py`, original at -m1, ours under presets at the preset -S):
the climb level agrees frame for frame on Spellbound sub 0 1274/1406 (22
before), Warhawk sub 7 8724/8967 (411), Thrust 776/1227 (82) and
Bump_Set_Spike sub 0 882/1167 (200).
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
from h2g.convert import _detect_tables, convert              # noqa: E402
from h2g.goatwriter import rise_stair as RS                  # noqa: E402
from h2g.goatwriter.constants import (CMD_TONEPORTA,         # noqa: E402
                                      GT_FIRST_NOTE, GT_LAST_NOTE, GT_REST,
                                      _SONG_MAX_PATTERNS)
from h2g.sidfile import load_sid                             # noqa: E402
from songview import parse_sng                               # noqa: E402

PRESETS = PYTHON_ROOT.parent / "presets.json"

needs_siddump = pytest.mark.skipif(
    not pathlib.Path(fidelity.SIDDUMP).exists(),
    reason="no siddump on this machine (tools/siddump-rt, see its README)")
needs_gt2reloc = pytest.mark.skipif(
    not pathlib.Path(fidelity.GT2RELOC).exists(),
    reason="no gt2reloc on this machine")

# The files whose bytes the stair moves under presets (corpus byte-hash at
# 82d60ac + this change: 89 compared, 4 moved, exactly these).
MOVERS = ("Bump_Set_Spike", "Spellbound", "Thrust", "Warhawk")


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
    """The 0-based record an instrument plays, from the name `_write_
    instruments` gives it (`NN:b5-b6-b7`, NN the record + 2); clones copy
    the name. None for anything else."""
    try:
        return int(ins.name.split(":")[0], 16) - 2
    except ValueError:
        return None


def _zero_speed_rows(song):
    """The step rows: (pattern, row) of every CMD_TONEPORTA whose speed-table
    row is $0000."""
    stbl = song.tables.get("STBL", [])
    out = set()
    for p, pat in enumerate(song.patterns):
        for r in range(len(pat) // 4):
            cmd, data = pat[4 * r + 2], pat[4 * r + 3]
            if (cmd == CMD_TONEPORTA and data
                    and data <= len(stbl) and stbl[data - 1] == (0, 0)):
                out.add((p, r))
    return out


# --- the model ---------------------------------------------------------------

def test_a_step_lands_on_every_fourth_counter_value_after_the_fetch():
    # counter 0 on the fetch frame: steps on working frames 4, 8, 12, 16.
    assert RS.stair_steps(0, 20, frozenset()) == [(4, 1), (8, 2), (12, 3),
                                                  (16, 4)]
    # counter 1: the multiples of four fall on 3, 7, 11 ...
    assert [w for w, _ in RS.stair_steps(1, 12, frozenset())] == [3, 7, 11]
    # The fetch frame itself never steps (w starts at 1).
    assert RS.stair_steps(0, 4, frozenset()) == []


def test_a_later_events_fetch_frame_loses_its_step():
    """Spellbound $E086 `JMP $E367`: a frame on which the voice fetches an
    event runs no effect, so a step due there is lost and the climb is one
    lower from then on -- its 128-row note re-fetches a gate-off every 32
    rows (64 working frames) on a step frame, and climbs 60, not 63."""
    steps = RS.stair_steps(0, 256, frozenset({64, 128, 192}))
    assert len(steps) == 60
    assert [k for w, k in steps if w in (60, 68)] == [15, 16]
    assert not any(w in (64, 128, 192) for w, _ in steps)


def test_a_step_goes_on_the_nearer_row_and_the_earlier_on_a_tie():
    # A step at a row's start: that row, then the next.
    assert RS.step_rows(4, 2) == [2, 3]
    # Two working frames a row, one in: early and late are equally far.
    assert RS.step_rows(3, 2) == [1, 2]
    # Three a row: one in is nearer this row, two in nearer the next.
    assert RS.step_rows(4, 3) == [1, 2]
    assert RS.step_rows(5, 3) == [2, 1]


def test_the_zero_speed_row_is_appended_once_and_reused():
    table = [(0x95, 0x05)]
    assert RS.zero_speed_index(table) == 2
    assert table == [(0x95, 0x05), (0, 0)]
    assert RS.zero_speed_index(table) == 2
    assert len(table) == 2
    assert RS.zero_speed_index([(0, 0), (1, 2)]) == 1
    assert RS.zero_speed_index([(1, 1)] * 255) is None


# --- reading the player ------------------------------------------------------

@needs_corpus
@pytest.mark.parametrize("name,at,counter,zp,base", [
    ("Spellbound", 0xE2FF, 0xC1, True, 0),        # INC $C1 / LDA #0 STA $C1
    ("Warhawk", 0x13A2, 0x15BF, False, 0),
    ("Kentilla", 0xAE77, 0xAFEF, False, 0),
    ("Bump_Set_Spike", 0xB387, 0xB506, False, 0),
    # INC $0CEA with no reset after it: the file's byte plus one.
    ("Thrust", 0x0B72, 0x0CEA, False, None),
])
def test_the_rise_block_and_its_counter(name, at, counter, zp, base):
    sid, det = _det(name)
    block = RS.rise_block(sid, det)
    assert block is not None
    assert sid.to_address(block.at) == at
    assert (block.counter, block.zp) == (counter, zp)
    want = base if base is not None else sid.data[sid.to_offset(counter)] + 1
    assert RS.rise_counter_base(sid, block) == want


@needs_corpus
@pytest.mark.parametrize("name,records", [
    ("Spellbound", [0x11]),
    # $04 (effect $07) has a zero nibble: no arpeggio program to move.
    ("Kentilla", [0x11]),
    ("Warhawk", [0x17]),
    ("Thrust", [0x0A, 0x0D, 0x17, 0x1B]),
    ("Bump_Set_Spike", [0x03]),
])
def test_the_records_that_climb_under_the_arpeggio(name, records):
    sid, det = _det(name)
    assert RS.rise_arp_records(sid, det, det.instr_used) == records


# --- what is emitted ---------------------------------------------------------

@needs_corpus
def test_spellbounds_long_note_carries_sixty_step_rows():
    """Subtune 0, voice 1, the first note on record $11 (E-1, 128 rows of two
    working frames, the counter reading 0 on its fetch): a step on every
    even row from 2, none on the gate-off rows 32, 64 and 96 -- 60 rows, the
    note climbing one semitone on each."""
    sng, lines, _ = _song("Spellbound")
    assert any(l.startswith("Rise stair (bit $02)") and "up to +60" in l
               for l in lines)
    song = parse_sng(sng)
    stbl = song.tables["STBL"]
    rows = list(RS._played_rows(song.tracks[1], len(song.patterns),
                                song.patterns))
    cur = 0
    start = None
    for a, (_v, _pos, p, r, _t) in enumerate(rows):
        n, ins = song.patterns[p][4 * r], song.patterns[p][4 * r + 1]
        if ins:
            cur = ins
        if GT_FIRST_NOTE <= n <= GT_LAST_NOTE and \
                _record_of(song.instruments[cur - 1]) == 0x11:
            start = a
            break
    assert start is not None
    base = song.patterns[rows[start][2]][4 * rows[start][3]]
    steps = []
    for j in range(1, 128):
        _v, _pos, p, r, _t = rows[start + j]
        n, ins, cmd, data = song.patterns[p][4 * r:4 * r + 4]
        if cmd == CMD_TONEPORTA and data and stbl[data - 1] == (0, 0):
            steps.append((j, n - base))
    want = [j for j in range(2, 128, 2) if j not in (32, 64, 96)]
    assert [j for j, _ in steps] == want
    assert [k for _, k in steps] == list(range(1, 61))


@needs_corpus
@pytest.mark.parametrize("name", MOVERS)
def test_every_step_row_is_inside_a_rising_note(name):
    """Every play of every step row is a row after a note on a rise+arp
    record and before the next note -- a pattern also played elsewhere was
    copied for the note's positions rather than written for all (Spellbound
    $3D is played after $3F too, outside any rising note)."""
    sid, det = _det(name)
    rising = set(RS.rise_arp_records(sid, det, det.instr_used))
    sng, _, _ = _song(name)
    song = parse_sng(sng)
    steps = _zero_speed_rows(song)
    assert steps
    seen = set()
    for track in song.tracks:
        cur = 0
        in_note = False
        for _v, _pos, p, r, _t in RS._played_rows(track, len(song.patterns),
                                                   song.patterns):
            n, ins = song.patterns[p][4 * r], song.patterns[p][4 * r + 1]
            if ins:
                cur = ins
            if (p, r) in steps:
                assert in_note, (name, hex(p), r)
                assert _record_of(song.instruments[cur - 1]) in rising
                seen.add((p, r))
            elif GT_FIRST_NOTE <= n <= GT_LAST_NOTE:
                in_note = _record_of(song.instruments[cur - 1]) in rising
    assert seen == steps


@needs_corpus
@pytest.mark.parametrize("name", MOVERS)
def test_the_movers_stay_inside_max_patterns(name):
    sng, _, _ = _song(name)
    assert len(parse_sng(sng).patterns) <= _SONG_MAX_PATTERNS


@needs_corpus
@pytest.mark.parametrize("name", ["Kentilla", "Commando"])
def test_no_stair_where_no_arpeggio_program_rises(name):
    """Kentilla's only rise+arp record that plays, $04, has a zero nibble;
    $11 is never played. Commando has no rise block at all."""
    sng, lines, _ = _song(name)
    assert not _zero_speed_rows(parse_sng(sng))
    assert not any(l.startswith("Rise stair") for l in lines)


# --- against the original ----------------------------------------------------

def _levels(fq, wf, a, b, k):
    """The climb level per frame of a note (the base tracked through the
    pair (b, b-k)) and the frames it steps on, from the note's onset; a
    test-bit onset frame (our `$09` firstwave) is silent and read as +0."""
    ref = a + 1 if wf[a] & 0x08 else a
    cur, lv, steps = 0, [], []
    for f in range(a, b):
        s = 0 if f < ref else round(12 * math.log2(fq[f] / fq[ref]))
        if s in (cur + 1, cur + 1 - k) and s not in (cur, cur - k):
            cur += 1
            steps.append(f - a)
        lv.append(cur)
    return lv, steps


@needs_corpus
@needs_siddump
def test_spellbounds_original_steps_every_four_working_frames():
    """The model, re-measured on the original: record $11's first note
    (voice 1, frames 1-281) climbs 60 semitones; consecutive steps are 4 or
    5 frames apart (four working frames, the outer gate skipping one frame
    in eleven) except three gaps of 8-9 -- the steps lost on the gate-off
    fetches."""
    orig = fidelity.run_siddump(CORPUS / "Spellbound.sid", 7, 0)
    fq = fidelity.register_timeline(orig[1].freq_events, 350)
    wf = fidelity.register_timeline(orig[1].wf_events, 350)
    lv, steps = _levels(fq, wf, 1, 282, 5)
    assert max(lv) == 60 and len(steps) == 60
    gaps = [b - a for a, b in zip(steps, steps[1:])]
    assert sorted(set(gaps)) == [4, 5, 8, 9]
    assert sum(g >= 8 for g in gaps) == 3


@needs_corpus
@needs_siddump
@needs_gt2reloc
def test_spellbounds_packed_note_climbs_with_the_original(tmp_path):
    """Through gt2reloc and siddump at the preset -S5, 7 s: our first $11
    note climbs 60 in 60 steps, each within one frame of the original's
    step of the same height (the outer gate's skipped frame falls a frame
    apart in the two players); without the stair it climbed none."""
    orig = fidelity.run_siddump(CORPUS / "Spellbound.sid", 7, 0)
    fq_o = fidelity.register_timeline(orig[1].freq_events, 350)
    wf_o = fidelity.register_timeline(orig[1].wf_events, 350)
    _, steps_o = _levels(fq_o, wf_o, 1, 282, 5)
    sng, _, doc = _song("Spellbound")
    m = fidelity._preset_multiplier(doc, "Spellbound.sid")
    packed = fidelity.pack_sid(sng, tmp_path, multiplier=m)
    assert packed is not None and packed.exists()
    ours = fidelity.run_siddump(packed, 8, 0, calls=m)
    fq = fidelity.register_timeline(ours[1].freq_events, 400)
    wf = fidelity.register_timeline(ours[1].wf_events, 400)
    on = [f for f in range(1, 400) if wf[f] & 1 and not wf[f - 1] & 1]
    lv, steps = _levels(fq, wf, on[0], on[1], 5)
    assert max(lv) == 60 and len(steps) == 60
    assert all(abs(a - b) <= 1 for a, b in zip(steps, steps_o)), \
        list(zip(steps, steps_o))
