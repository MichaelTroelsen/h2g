"""Two pulse engines that were not read at all, so every record using them
held its seed width (task frozen-pulse-phantoms-ninja-pygmies-nineteen):

* the accumulate engine FOLDED by `ORA #$40` (`detect.PULSE_LO_ORA_SHAPES`,
  Ninja $CA0F, Phantoms_of_the_Asteroid $E1F6 through a JSR), emitted by
  `_pulse_lo_fold_program`;
* a per-voice pulse PROGRAM of (frames - 1, delta) pairs
  (`detect.PULSE_PROG_SHAPE`, Star_Paws $B27D), emitted by
  `_pulse_prog_program`;
* and the bounds engine in Powerplay_Hockey's second copy of the player
  (`_find_pulse_sweep`'s fallback, `PULSE_SETUP_16`).

The emitted tables are checked against the players' own arithmetic by
running both: `_gt_pulse` is gplay.c:865-902's pulse-table step, one call at
a time, and `_player_*` transcribe the two 6502 blocks quoted in detect.py.
"""
import dataclasses

import pytest

from corpus import CORPUS, needs_corpus
from h2g.detect import (PULSE_LO_ORA_SHAPES, PULSE_LO_SHAPES, _find_pulse_lo,
                        _find_pulse_prog, detect)
from h2g.goatwriter import _pulse_program
from h2g.goatwriter.pulse import _spread_rows
from h2g.sidfile import load_sid

FOLD_FILES = {"Chimera", "Crazy_Comets", "Game_Killer", "Human_Race",
              "Last_V8", "Last_V8_C128_version", "Ninja",
              "Phantoms_of_the_Asteroid"}
PROG_FILES = {"Arcade_Classics", "BMX_Kidz", "Bangkok_Knights", "Ricochet",
              "Skate_or_Die_intro", "Star_Paws", "Thundercats"}


def _load(stem):
    sid = load_sid(str(CORPUS / f"{stem}.sid"))
    return sid, detect(sid, lambda *_a, **_k: None)


def _gt_pulse(entries, loop, calls):
    """Pulse width after each of `calls` play calls, gplay.c's pulse step
    (set rows `$8x`, modulation rows `tt ss`, `$FF` jumps; `loop` is where the
    block's own trailing jump returns, None for a block ending `$FF 00`)."""
    table = list(entries) + ([(0xFF, loop + 1)] if loop is not None else [])
    ptr, time, pulse, out = 1, 0, 0, []
    for _ in range(calls):
        if ptr and table[ptr - 1][0] == 0xFF:
            ptr = table[ptr - 1][1]
        if ptr:
            if not time:
                left, right = table[ptr - 1]
                if left >= 0x80:
                    pulse = ((left & 0x0F) << 8) | right
                    ptr += 1
                else:
                    time = left
            if time:
                speed = table[ptr - 1][1]
                pulse = (pulse + speed - (0x100 if speed >= 0x80 else 0)) & 0xFFF
                time -= 1
                if not time:
                    ptr += 1
        out.append(pulse)
    return out


def _player_fold(width, rate, fold, ticks):
    """Widths at the end of each tick: the fetch writes the record's width,
    then `lo = (lo + rate) | fold` a tick, the high nibble untouched."""
    hi, lo, out = width & 0xF00, width & 0xFF, [width]
    for _ in range(ticks - 1):
        lo = ((lo + rate) & 0xFF) | fold
        out.append(hi | lo)
    return out


def _player_prog(seed, prog, frames):
    """Star_Paws $B27D, a frame at a time from the fetch frame (width = seed,
    count 0, pos 0); the first pair is read the frame after."""
    width, count, pos, delta, out = seed, 0, 0, 0, [seed]
    for _ in range(frames - 1):
        count -= 1
        add = True
        if count < 0:
            while True:
                op = prog[pos]
                if op == 0xFE:
                    count, add = 0xFE - 0x100, False
                    break
                if op == 0xFF:
                    pos = 0
                    continue
                if op & 0x80:
                    width = seed
                count = op & 0x7F
                delta = prog[pos + 1] - (0x100 if prog[pos + 1] & 0x80 else 0)
                pos += 2
                break
        if add:
            width += delta
        out.append(width & 0xFFF)
    return out


@needs_corpus
def test_the_fold_spelling_is_read_on_exactly_these_files():
    found = {}
    for path in sorted(CORPUS.glob("*.sid")):
        sid, det = _load(path.stem)
        if det.pulse_lo_fold:
            found[path.stem] = det.pulse_lo_fold
    assert found == {s: 0x40 for s in FOLD_FILES}
    # The fold is a fallback: no plain-spelling file is read through it.
    assert len(PULSE_LO_ORA_SHAPES) == 2
    assert all("09" not in s.split() for s in PULSE_LO_SHAPES)


@needs_corpus
def test_the_program_engine_is_read_on_exactly_these_files():
    found = {}
    for path in sorted(CORPUS.glob("*.sid")):
        sid, det = _load(path.stem)
        if det.pulse_prog_table >= 0:
            found[path.stem] = det.pulse_prog_count
            # ... and only where no other engine was.
            assert det.pulse_bounds < 0 and det.pulse_lo_base < 0
            assert det.pulse_tri_hi < 0
    assert found == {**{s: 2 for s in PROG_FILES},
                     "Ricochet": 22, "Arcade_Classics": 37,
                     # zero-page spelling (PULSE_PROG_ZP_SHAPE)
                     "Mega_Apocalypse": 14}


def _mutated(sid, old: bytes, new: bytes):
    assert sid.data.count(old) == 1, old.hex()
    return dataclasses.replace(sid, data=sid.data.replace(old, new))


@needs_corpus
def test_the_jsr_spelling_needs_a_subroutine_storing_d402():
    sid, det = _load("Phantoms_of_the_Asteroid")
    assert _find_pulse_lo(sid, det) == det.instr_start
    # $F04E `INC $E6 / STA $D402,Y` -> `STA $D403,Y`.
    broken = _mutated(sid, bytes.fromhex("E6E69902D4C6E6"),
                      bytes.fromhex("E6E69903D4C6E6"))
    assert _find_pulse_lo(broken, det) == -1


@needs_corpus
def test_the_program_number_must_come_from_record_6():
    sid, det = _load("Star_Paws")
    assert _find_pulse_prog(sid, det)[0] >= 0
    # `LDA $B979,Y / STA $B6A1` -> `STA $B6A2`.
    broken = _mutated(sid, bytes.fromhex("B979B98DA1B6"),
                      bytes.fromhex("B979B98DA2B6"))
    assert _find_pulse_prog(broken, det) == (-1, 0)


def _record(sid, det, i):
    rec = det.instr_start + i * det.instr_stride
    return sid.data[rec:rec + 8]


@needs_corpus
def test_phantoms_record_2_plays_the_players_cycle_exactly():
    # rate 4, seed $100, ORA #$40, -S2: the player's 140..17C, 1C0..1FC
    # cycle, every frame end, for three laps -- the loop closes on it.
    sid, det = _load("Phantoms_of_the_Asteroid")
    r = _record(sid, det, 2)
    assert r[7] & 0x08 and r[6] == 0x04 and (r[1], r[0]) == (0x01, 0x00)
    entries, loop = _pulse_program(sid, det, 2, True, 2)
    ours = _gt_pulse(entries, loop, 2 * 100)[1::2]
    theirs = _player_fold(0x100, 4, 0x40, 100)
    # Our frame f ends on call 2f + 1; the leg reaches the player's tick
    # value on that call, so frame ends agree to the unit.
    assert ours == theirs
    assert len(entries) <= 12


@needs_corpus
@pytest.mark.parametrize("stem, i, mult", [("Ninja", 10, 1),
                                           ("Phantoms_of_the_Asteroid", 8, 2),
                                           ("Phantoms_of_the_Asteroid", 18, 2)])
def test_a_folded_record_never_leaves_its_band(stem, i, mult):
    # Whatever the rate, the width keeps the record's high nibble and a low
    # byte that the fold allows on every frame end -- the plain spelling's
    # leg would carry into the next nibble. Rate $79 folds every tick and
    # must still alternate halves frame by frame at -S2, not alias to one.
    sid, det = _load(stem)
    r = _record(sid, det, i)
    entries, loop = _pulse_program(sid, det, i, True, mult)
    ours = _gt_pulse(entries, loop, mult * 200)[mult - 1::mult]
    assert {w >> 8 for w in ours} == {r[1] & 0x0F}
    assert all(w & 0x40 for w in ours[1:])
    if r[6] >= 0x40:
        halves = [w & 0x80 for w in ours[1:40]]
        assert all(a != b for a, b in zip(halves, halves[1:])), halves


@needs_corpus
@pytest.mark.parametrize("stem, i, mult", [("Star_Paws", 0, 2),
                                           ("Star_Paws", 3, 2),
                                           ("Thundercats", 3, 3),
                                           ("Thundercats", 0, 3),
                                           ("Bangkok_Knights", 0, 1)])
def test_a_program_plays_the_players_widths(stem, i, mult):
    sid, det = _load(stem)
    r = _record(sid, det, i)
    tab, n = det.pulse_prog_table, det.pulse_prog_count
    at = sid.to_offset(sid.data[tab + r[6] - 1] | sid.data[tab + n + r[6] - 1] << 8)
    prog = sid.data[at:at + 32]
    seed = ((r[1] & 0x0F) << 8) | r[0]
    entries, loop = _pulse_program(sid, det, i, True, mult)
    frames = 150
    ours = _gt_pulse(entries, loop, mult * frames)[mult - 1::mult]
    theirs = _player_prog(seed, prog, frames)
    # Within a pair the leg is two integer speeds, the lower first, so a
    # frame end trails by at most a quarter of the pair's travel; at every
    # pair's end it is exact.
    worst = max(abs(((a - b + 0x800) & 0xFFF) - 0x800)
                for a, b in zip(ours, theirs))
    assert worst <= 0x40, (worst, ours[:24], theirs[:24])
    ends, f, pos = [], 0, 0
    while prog[pos] < 0xFE and f < frames:
        f += (prog[pos] & 0x7F) + 1
        ends.append(f)
        pos += 2
    assert all(ours[e] == theirs[e] for e in ends if e < frames)


def test_a_spread_leg_lands_exactly():
    for total, calls in ((16 * 21, 63), (-16 * 13, 38), (0x41 * 13, 26), (5, 1)):
        rows = _spread_rows(total, calls)
        assert sum(t for t, _ in rows) == calls
        assert sum(t * (s - (0x100 if s >= 0x80 else 0)) for t, s in rows) == total


@needs_corpus
def test_powerplays_sweep_is_read_from_the_copy_its_records_belong_to():
    # Two copies of the player: $37xx (8-byte records at $3BA0, the first
    # PULSE_SWEEP/PULSE_SETUP matches) and $45xx (16-byte records at $4A00,
    # the detected table). The second copy's block reads its bounds at
    # record +13 and its rate cell from record +6.
    sid, det = _load("Powerplay_Hockey_USA_vs_USSR")
    assert sid.to_address(det.instr_start) == 0x4A00 and det.instr_stride == 16
    assert det.pulse_bounds == det.instr_start + 13
    assert det.pulse_rate_field == 6
    # Record 1: seed $200, rate $10, bounds byte $FD (turns at $D00 and
    # $F00 -- a band that wraps through $FFF). It held $200 before.
    rec = det.instr_start + 1 * det.instr_stride
    assert (sid.data[rec + 1], sid.data[rec + 6], sid.data[rec + 13]) == (2, 0x10, 0xFD)
    entries, loop = _pulse_program(sid, det, 1, True, 1)
    assert entries[0] == (0x82, 0x00) and loop is not None
    assert {s for t, s in entries[1:] if t < 0x80} == {0x10, 0xF0}


def _forced_phase_table(name):
    """(rows, swept records) of the pulse-phase table convert() lays for
    `name` under its presets with `pulse_phase` forced."""
    import json
    from pathlib import Path

    import fidelity
    from h2g import convert as C
    presets = Path(__file__).resolve().parents[2] / "presets.json"
    doc = json.loads(presets.read_text(encoding="utf-8"))
    kw = fidelity._preset_opts(doc, name)
    kw["pulse_phase"] = True
    cap = {}
    real = C.build_pulse_phase_table

    def spy(*a, **k):
        cap["t"] = real(*a, **k)
        return cap["t"]
    C.build_pulse_phase_table = spy
    try:
        C.convert(str(CORPUS / name), log=lambda m: None, **kw)
    finally:
        C.build_pulse_phase_table = real
    entries, _starts, index = cap["t"]
    return len(entries), sorted({k[0] for k in index})


@needs_corpus
@pytest.mark.parametrize("name, read, unread", [
    ("Human_Race.sid", (227, [1, 2, 4, 18, 23]), (242, [1, 2, 4, 18, 21, 23])),
    ("Last_V8.sid", (251, [2, 7, 8, 9]), (245, [2, 7, 8, 9])),
    ("Ninja.sid", (224, [5, 7, 13]), (249, [5, 7, 9])),
    ("Phantoms_of_the_Asteroid.sid", (120, [1, 7, 16, 17]),
     (58, [1, 7, 16, 17]))])
def test_what_the_fold_programs_cost_a_forced_pulse_phase_table(
        name, read, unread, monkeypatch):
    # Not a shipped layout: none of these files sets `pulse_phase` in its
    # presets. Forced, the folded records' programs share the 255-row table
    # with the phase blocks: Human_Race's record 21 loses its phase sweep,
    # Ninja keeps 13 where it kept 9. The tests pinning the earlier layouts
    # lay the folds static (`corpus.folds_unread`); this is what they cost.
    assert _forced_phase_table(name) == read
    from h2g.goatwriter import pulse as P
    monkeypatch.setattr(P, "_pulse_lo_fold_program", lambda *a, **k: None)
    assert _forced_phase_table(name) == unread
