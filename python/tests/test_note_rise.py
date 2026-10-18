"""Bit $02's skydive without its window (`detect._find_note_rise`), emitted as
per-row CMD_SETWAVEPTR programs (`goatwriter.note_rise`).

Game_Killer $0B33: on every tick whose counter `$0C8B` is odd, for every note
of at least $11 ticks, the player stores the note's frequency high byte into
$D401 and INCs it -- from the note's first effect tick to its last. Its
record 1 (GT 2, ADSR $0A9A, effect $0A) rewrites the whole frequency on the
ticks between (its vibrato), so the original alternates the vibrato with a
rising high byte: the `$0A9A` row of docs/VIBRATO.md, 1652 reversals against
our 479 at -t 180 (re-measured on 6e467ff + the c6 merge, under presets),
1173 of the file's 1186 missing. Battle_of_Britain $82CC is the same block
with DEC.
"""
import dataclasses
import json
import pathlib
import re
import sys

import pytest

from corpus import CORPUS, needs_corpus

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[1]))

import fidelity                                              # noqa: E402
from h2g.detect import NoteRise, detect                      # noqa: E402
from h2g.goatwriter import note_rise as R                    # noqa: E402
from h2g.goatwriter import skydive as S                      # noqa: E402
from h2g.goatwriter.constants import (CMD_SETWAVEPTR,        # noqa: E402
                                      GT_FIRST_NOTE, GT_LAST_NOTE, GT_REST)
from h2g.sidfile import load_sid                             # noqa: E402

PYTHON_ROOT = pathlib.Path(__file__).resolve().parents[1]

needs_siddump = pytest.mark.skipif(
    not pathlib.Path(fidelity.SIDDUMP).exists(),
    reason="no siddump on this machine (tools/siddump-rt, see its README)")
needs_gt2reloc = pytest.mark.skipif(
    not pathlib.Path(fidelity.GT2RELOC).exists(),
    reason="no gt2reloc on this machine")

# (counter, MIN, step) read from each file's own block.
BLOCKS = {
    "Battle_of_Britain": (0x841F, 0x0C, -1),
    "Chimera": (0xC661, 0x11, 1),
    "Crazy_Comets": (0x5509, 0x11, -1),
    "Game_Killer": (0x0C8B, 0x11, 1),
    "Human_Race": (0x0DE2, 0x11, 1),
    # NOTE_RISE_DOUBLE_SHAPE: two INCs a store. Commando has the block and
    # no record with bit $02, so nothing is emitted for it.
    "Commando": (0x5525, 0x03, 2),
    "Geoff_Capes_Strongman_Challenge": (0x152A, 0x03, 2),
    "Gerry_the_Germ": (0xE52A, 0x03, 2),
}


def _det(name):
    sid = load_sid(str(CORPUS / f"{name}.sid"))
    return sid, detect(sid, lambda *a, **k: None)


def _converted(name, **extra):
    import h2g.convert as C
    doc = json.loads((PYTHON_ROOT.parent / "presets.json").read_text())
    lines = []
    opts = fidelity._preset_opts(doc, f"{name}.sid")
    opts.update(extra)
    sng = C.convert(str(CORPUS / f"{name}.sid"), log=lines.append, **opts)
    return sng, lines, opts


@needs_corpus
def test_the_block_is_read_in_exactly_the_eight_files_that_carry_it():
    found = {}
    for path in sorted(CORPUS.glob("*.sid")):
        sid = load_sid(str(path))
        try:
            det = detect(sid, lambda *a, **k: None)
        except Exception:
            continue                      # a file detect refuses has no block
        if det.note_rise is not None:
            assert det.skydive is None and not det.effect_rise, path.name
            nr = det.note_rise
            found[path.stem] = (nr.counter, nr.min_length, nr.step)
    assert found == BLOCKS


@needs_corpus
def test_game_killers_operands():
    _sid, det = _det("Game_Killer")
    assert det.note_rise == NoteRise(counter=0x0C8B, min_length=0x11, step=1)


def test_the_store_lag_is_one_tick_only_where_a_frame_holds_the_lead():
    """-S1 and -S2 with the test-bit lead: the attack frame ends a tick
    after the row's first; anywhere else inside it."""
    assert R.store_lag(1, 1, True) == 1          # skydive_plan's -S1 lag
    assert R.store_lag(1, 1, False) == 0
    assert R.store_lag(2, 2, True) == 1          # Battle_of_Britain, measured
    assert R.store_lag(2, 2, False) == 0
    assert R.store_lag(9, 10, True) == 0         # Game_Killer, measured
    assert R.store_lag(3, 3, True) == 0
    assert R.store_lag(4, 4, True) == 0


def test_store_values_spread_from_one_to_the_top():
    assert R.store_values(16, 16) == list(range(1, 17))
    assert R.store_values(16, 40) == list(range(1, 17))
    assert R.store_values(16, 10) == [1, 3, 4, 6, 8, 9, 11, 13, 14, 16]
    assert R.store_values(16, 1) == [16]
    assert R.store_values(0, 5) == [] and R.store_values(5, 0) == []
    assert R.nearest_value(2, [1, 3]) == 1       # the lower on a tie
    assert R.nearest_value(15, [1, 3, 14, 16]) == 14


def _run(entries, start):
    """The program at `start` (1-based) call by call, as gplay.c WAVEEXEC
    reads it: {call: what the call does} for the calls that do anything --
    'note' for a relative-note-0 step, the (command, speed) for a command.
    A delay's other calls run the row's effect and are left out."""
    out, at, call = {}, start, 0
    while True:
        left, right = entries[at - 1]
        if left == 0xFF:
            if right == 0:
                return out
            at = right
            continue
        if left <= 0x0F:
            call += left
            if right == 0x00:
                out[call] = "note"
        else:
            out[call] = (left, right)
        call += 1
        at += 1


@pytest.mark.parametrize("ticks", [1, 2, 10])
def test_a_first_tick_store_jumps_and_comes_back_to_the_note(ticks):
    entries, starts = R.note_rise_entries({0: [3, 7]}, ticks, 1, 1,
                                          lambda k: 0x40 + k)
    for v in (3, 7):
        got = _run(entries, starts[(0, v)])
        want = {0: (0xF1, 0x40 + v), ticks: "note"}
        if ticks >= 2:
            want[2 * ticks - 1] = "note"     # the next row's step from it
        assert got == want, (ticks, v, got)


@pytest.mark.parametrize("ticks", [2, 10])
def test_a_second_tick_store_sits_on_the_note_and_falls(ticks):
    entries, starts = R.note_rise_entries({1: [5]}, ticks, -1, 1,
                                          lambda k: 0x40 + k)
    got = _run(entries, starts[(1, 5)])
    assert got == {ticks - 1: "note", ticks: (0xF2, 0x45),
                   2 * ticks - 1: "note"}, got


def test_every_value_shares_one_tail_per_half():
    entries, _ = R.note_rise_entries({0: [1, 2, 3], 1: [1, 2, 3]}, 10, 1, 1,
                                     lambda k: k)
    cost0, tail0 = R.program_cost(0, 10)
    cost1, tail1 = R.program_cost(1, 10)
    assert len(entries) == tail0 + tail1 + 3 * (cost0 + cost1) == 20


def _store_rows(song, number):
    """(lap row offset from its note, pointer) for every CMD_SETWAVEPTR row
    inside a note of GT instrument `number`."""
    hits = []
    for track in song.tracks:
        rows = list(S._lap_rows(track, song.patterns))
        current, note_at = 0, None
        for a, (p, r, _t) in enumerate(rows):
            n, i, cmd, dat = song.patterns[p][4 * r:4 * r + 4]
            if i:
                current = i
            if GT_FIRST_NOTE <= n <= GT_LAST_NOTE:
                note_at = (a, current)
            elif cmd == CMD_SETWAVEPTR and note_at and note_at[1] == number:
                hits.append((a - note_at[0], dat))
    return hits


@needs_corpus
@pytest.mark.parametrize("tie_restart", [False, True])
def test_game_killer_points_rows_2_to_17_of_each_note_at_a_rising_store(
        tie_restart):
    """Every note of GT 2 is 18 rows; store k is on the original's tick
    2 + 2k, the first tick of row k + 1, so rows 2..17 carry k = 1..16 --
    through sixteen programs, one a value (the wavetable's last 23 entries
    held ten; the five identical `41 00 / 07 00 / 41 00 / FF 00 / FF 00`
    instrument blocks now share one copy and the other four give their rows
    to the programs), every one a single `F1` of `$100 * v` into the shared
    tail. A pattern whose packed size the sixteen distinct operands would
    push past the limit takes the value below the one asked for on some of
    its rows (98 of 672 rows at the time of writing). The same with
    `tie_restart`, which presets.FIXED turns on."""
    import songview
    sng, lines, _ = _converted("Game_Killer", tie_restart=tie_restart)
    song = songview.parse_sng(sng)
    every = _store_rows(song, 2)
    # The rows past the note's 18 are the rest after it, which the rise runs
    # on through (`note_rise.continuation`); their own test is
    # test_note_rise_isolate.py.
    hits = [(j, s) for j, s in every if j < 18]
    assert {j for j, _ in hits} == set(range(2, 18)), hits
    assert any(j >= 18 for j, _ in every), every
    wt, stbl = song.tables["WTBL"], song.tables["STBL"]
    assert len(wt) <= 255
    exact = 0
    for j, start in hits:
        prog = _run(wt, start)
        (cmd,) = [s for s in prog.values() if s != "note"]
        v = stbl[cmd[1] - 1][0]
        assert cmd[0] == 0xF1 and stbl[cmd[1] - 1][1] == 0x00, (j, prog)
        assert v in (j - 1, j - 2), (j, v)
        exact += v == j - 1
        assert prog == {0: cmd, 10: "note", 19: "note"}, (j, prog)
    assert exact > 5 * len(hits) // 6, (exact, len(hits))
    assert len({start for _j, start in hits}) == 16
    rise = [m for m in lines if "Note rise (bit $02)" in m]
    assert len(rise) == 1 and "295 store row(s)" in rise[0], rise
    # the notes' own sixteen values stay exact; the continued stores above
    # them take the 2 more the table has room for
    assert re.search(r"18 of 118 store value\(s\)", rise[0]), rise


def _hi_frames(trace, nframes, key, keep):
    """{voice: {frame: high byte}} for the frames `keep(hi, note_hi)` selects
    inside the notes whose attack sets AD and the S nibble to `key` (the
    `$0A9A` record is $0A9), `note_hi` being the attack frame's."""
    out = {}
    for vi, v in enumerate(trace):
        fq = fidelity.register_timeline(v.freq_events, nframes)
        ad = fidelity.register_timeline(v.adsr_events, nframes)
        atk = sorted(v.attack_frames)
        got = {}
        for j, a in enumerate(atk):
            if a + 1 >= nframes or ad[a + 1] >> 4 != key:
                continue
            nxt = atk[j + 1] if j + 1 < len(atk) else nframes
            for f in range(a + 1, min(nxt, nframes)):
                if keep(fq[f] >> 8, fq[a] >> 8):
                    got[f] = fq[f] >> 8
        out[vi] = got
    return out


@needs_corpus
@needs_siddump
def test_game_killers_original_reads_the_note_byte_plus_k_on_alternate_ticks():
    """The model, re-measured on the original rather than assumed: voice 0's
    note at frame 641, with the outer gate's skipped frames (4, 14, 24, ...:
    `$0C8C` holds 4 and reloads 9) taken out, reads the note's high byte $34
    plus k on tick 2 + 2k for k = 0..16, and the vibrato's own high byte
    ($34-$36, steps of $C7 from $3426) on every tick between."""
    orig = fidelity.run_siddump(CORPUS / "Game_Killer.sid", 15, 0)
    fq = fidelity.register_timeline(orig[0].freq_events, 750)
    ticks = [fq[f] for f in range(641, 690) if (f - 4) % 10]
    assert ticks[0] == 0x3426
    for k in range(17):
        assert ticks[2 + 2 * k] >> 8 == 0x34 + k, (k, hex(ticks[2 + 2 * k]))
    for t in range(1, 35, 2):
        assert ticks[t] in (0x3426, 0x34ED, 0x35B4, 0x367B), (t, hex(ticks[t]))


def _agreement(name, multiplier, seconds, key, keep, tmp_path, sub):
    orig = fidelity.run_siddump(CORPUS / f"{name}.sid", seconds, 0)
    n = seconds * 50
    stores = _hi_frames(orig, n, key, keep)
    sng, _, _ = _converted(name)
    work = tmp_path / sub
    work.mkdir()
    packed = fidelity.pack_sid(sng, work, multiplier=multiplier)
    assert packed is not None and packed.exists(), sub
    ours = fidelity.run_siddump(packed, seconds + 2, 0, calls=multiplier)
    lag = fidelity.startup_lag(orig, ours)[0]
    out = {}
    for vi, got in stores.items():
        if not got:
            continue
        fu = fidelity.register_timeline(ours[vi].freq_events, n + lag + 1)
        out[vi] = (len(got), sum(fu[f + lag] >> 8 == hi
                                 for f, hi in got.items()))
    return out


@needs_corpus
@needs_siddump
@needs_gt2reloc
def test_game_killers_packed_stores_land_on_the_originals_frames(
        tmp_path, monkeypatch):
    """Through gt2reloc and siddump, 60 s at -S9: of the frames the original
    sits 3 or more above its note's high byte (the stores from k = 3; the
    vibrato reaches 2), ours reads the same high byte at the startup lag on
    over 40% (63 of 123 measured, the rest the nearest-value rounding and
    the outer gate's doubled frame landing a frame apart) -- and on none
    without the plan."""
    def keep(hi, onset):
        return 3 <= hi - onset <= 0x20
    emitted = _agreement("Game_Killer", 9, 60, 0x0A9, keep, tmp_path, "emitted")
    assert set(emitted) == {0}, emitted
    total, same = emitted[0]
    assert total >= 100 and same >= 0.4 * total, emitted
    monkeypatch.setattr(R, "note_rise_plan", lambda *a, **k: None)
    without = _agreement("Game_Killer", 9, 60, 0x0A9, keep, tmp_path, "without")
    assert without[0][1] <= total // 20, (emitted, without)


@needs_corpus
@needs_siddump
@needs_gt2reloc
def test_battle_of_britains_falling_stores_are_on_the_rows_second_tick(
        tmp_path, monkeypatch):
    """-S2 with the test-bit lead puts the original's tick one of ours late
    (`store_lag`), so the fall's stores go on each row's second tick. Of the
    frames the original sits below its note's high byte, ours reads the same
    byte at the startup lag on over 90% on both voices (112 of 114 and 82
    of 82 measured); without the plan none (the vibrato is above the note),
    and with the store on the first tick -- lag 0 -- none either: one frame
    early, every one."""
    def keep(hi, onset):
        return 1 <= onset - hi <= 0x20
    emitted = _agreement("Battle_of_Britain", 2, 120, 0x0FF, keep, tmp_path, "emit")
    for vi in (0, 1):
        total, same = emitted[vi]
        assert total >= 50 and same >= 0.9 * total, emitted
    monkeypatch.setattr(R, "store_lag", lambda *a, **k: 0)
    early = _agreement("Battle_of_Britain", 2, 120, 0x0FF, keep, tmp_path, "early")
    assert all(early[vi][1] <= emitted[vi][0] // 50 for vi in (0, 1)), early
    monkeypatch.setattr(R, "note_rise_plan", lambda *a, **k: None)
    without = _agreement("Battle_of_Britain", 2, 120, 0x0FF, keep, tmp_path, "none")
    assert all(without[vi][1] <= emitted[vi][0] // 50 for vi in (0, 1)), \
        without


@needs_corpus
def test_the_doubled_block_reads_a_step_of_two():
    """Gerry_the_Germ $E34D: `INC savehi,X` twice before the store
    (NOTE_RISE_DOUBLE_SHAPE), so the step is 2, not the 1 the single-INC
    reading would give."""
    _sid, det = _det("Gerry_the_Germ")
    assert det.note_rise == NoteRise(counter=0xE52A, min_length=3, step=2)


@needs_corpus
@needs_siddump
def test_gerrys_original_steps_the_byte_by_two_on_alternate_frames():
    """Voice 1's $A0F0 note at frame 3841 reads the note's own $1D46 on
    every even frame (the record's note re-assert) and $1D + 2k over its low
    byte on the odd ones from 3843 (k = 0, 1, ...)."""
    orig = fidelity.run_siddump(CORPUS / "Gerry_the_Germ.sid", 80, 0)
    fq = fidelity.register_timeline(orig[1].freq_events, 3860)
    assert fq[3841] == 0x1D46
    for k in range(8):
        assert fq[3843 + 2 * k] == 0x1D46 + 0x200 * k, (k, hex(fq[3843 + 2 * k]))
        assert fq[3844 + 2 * k] == 0x1D46, k


def _gerry_lead(tmp_path, sub):
    """(the original's voice-1 frames 3848-3857, ours at the startup lag,
    the store agreement of `_agreement` on the $A0F record over 100 s)."""
    def keep(hi, onset):
        return 2 <= hi - onset <= 0x40
    orig = fidelity.run_siddump(CORPUS / "Gerry_the_Germ.sid", 100, 0)
    sng, _, _ = _converted("Gerry_the_Germ")
    work = tmp_path / sub
    work.mkdir()
    packed = fidelity.pack_sid(sng, work, multiplier=1)
    assert packed is not None and packed.exists(), sub
    ours = fidelity.run_siddump(packed, 102, 0, calls=1)
    lag = fidelity.startup_lag(orig, ours)[0]
    fo = fidelity.register_timeline(orig[1].freq_events, 3860)
    fu = fidelity.register_timeline(ours[1].freq_events, 3860 + lag)
    stores = _hi_frames(orig, 5000, 0xA0F, keep)
    fa = {vi: fidelity.register_timeline(ours[vi].freq_events, 5000 + lag + 1)
          for vi in stores}
    total = sum(len(g) for g in stores.values())
    same = sum(fa[vi][f + lag] >> 8 == hi
               for vi, g in stores.items() for f, hi in g.items())
    return ([fo[f] for f in range(3848, 3858)],
            [fu[f + lag] for f in range(3848, 3858)], total, same)


@needs_corpus
@needs_siddump
@needs_gt2reloc
def test_gerrys_lead_alternates_like_the_original(tmp_path, monkeypatch):
    """Through gt2reloc and siddump under presets (-S1): voice 1's frames
    3848-3857, `1D46 2346 1D46 2546 1D46 2746 1D46 2946 1D46 2B46` in the
    original, are the same ten values in ours (they were $1D46 on every frame
    before the doubled block was read), and of the frames any $A0F note sits
    2 or more above its note's high byte over 100 s ours reads the same
    byte on most. Read as one INC a store the rise climbs half as fast and
    the window misses; with the file-wide shortest row (`row_calls`, 2
    calls) in place of subtune 0's own 3, the lead is declined and held."""
    orig, ours, total, same = _gerry_lead(tmp_path, "emitted")
    assert ours == orig, ([f"{x:04X}" for x in orig], [f"{x:04X}" for x in ours])
    assert total >= 200 and same >= 0.6 * total, (total, same)

    real = R._rise_plan_once

    def one_a_store(sid, det, *a, **k):
        nr = det.note_rise
        return real(sid, dataclasses.replace(
            det, note_rise=NoteRise(nr.counter, nr.min_length, 1)), *a, **k)
    monkeypatch.setattr(R, "_rise_plan_once", one_a_store)
    _o, single, _t, single_same = _gerry_lead(tmp_path, "single")
    assert single != orig and single_same <= same // 4, (single_same, same)

    def file_wide_row(*a, subtune_row_calls=(), **k):
        return real(*a, **k)
    monkeypatch.setattr(R, "_rise_plan_once", file_wide_row)
    _o, held, _t, held_same = _gerry_lead(tmp_path, "file_wide")
    assert held == [0x1D46] * 10 and held_same <= same // 4, (held, held_same)
