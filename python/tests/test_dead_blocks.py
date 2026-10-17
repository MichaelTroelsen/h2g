"""The wavetable blocks of the records no pattern names are dropped
(`goatwriter.dead_blocks`), so the programs that size themselves against the
table's room see the room.

`drop_unnamed_instruments` removes the dead records from the finished file and
leaves their blocks behind. Under `prune` that is a lot of table: Last_V8's
song as written plays 18 of its 33 records and the wavetable kept all 33
blocks, 217 rows of 255. The skydive, note-rise and counter-fall passes, and
the past-table pointer copies, ask how many rows are left; the dead blocks
answered wrongly. They are dropped between the layout and those passes, behind
the same option that drops the records.

Measured at v0.5.578 under presets over the 89 files that convert (a
historical figure): the wavetable's unreachable rows went from 2821 to 641, 71
files move, 18 do not (no dead record), and of the 71 the wavetable programs of
every named record and every `CMD_SETWAVEPTR` operand are the same program
(relocated) in 65 -- the other 6 (5_Title_Tunes, Battle_of_Britain, Gremlins,
Hunter_Patrol, Mega_Apocalypse, W_A_R_Preview) are the files whose freed rows
a pass then used.
"""
import json
import pathlib
import sys

import pytest

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[1]))

from corpus import CORPUS, needs_corpus                      # noqa: E402
import fidelity as F                                         # noqa: E402
import songview                                              # noqa: E402
from h2g.convert import convert                              # noqa: E402
from h2g.goatwriter import dead_blocks as D                  # noqa: E402
from h2g.goatwriter import build as B                        # noqa: E402
from h2g.goatwriter.constants import (CMD_SETWAVEPTR,        # noqa: E402
                                      GT_MAX_TABLELEN)

PRESETS = pathlib.Path(__file__).resolve().parents[2] / "presets.json"
STOP = (0xFF, 0x00)


def _block(tag, n=3):
    """A stop-terminated program of n+1 rows, recognisable by its waveform."""
    return [(tag, 0x00)] * n + [STOP]


def _table(*blocks):
    entries, starts = [], []
    for b in blocks:
        starts.append(len(entries) + 1)
        entries += b
    return entries, starts


def _program(entries, ptr):
    """The rows from `ptr` to its stop, jump targets as offsets from `ptr`
    (so a relocated copy compares equal)."""
    out, row = [], ptr
    while True:
        left, right = entries[row - 1]
        if left == 0xFF:
            out.append((left, right and right - ptr))
            return out
        out.append((left, right))
        row += 1


def test_an_unreachable_dead_block_is_dropped_and_the_rest_relocated():
    entries, starts = _table(_block(0x11), _block(0x22), _block(0x33))
    plan = D.plan_dead_blocks(entries, starts, 0, dead=[1], block_starts=[])
    assert plan is not None
    assert plan.dropped == (1,) and plan.rows == 4
    assert len(plan.entries) == len(entries) - 4
    # record 2's block moved up by the four rows; both survivors read the same
    assert plan.row_map[starts[2]] == starts[2] - 4
    assert _program(plan.entries, plan.row_map[starts[0]]) == _program(
        entries, starts[0])
    assert _program(plan.entries, plan.row_map[starts[2]]) == _program(
        entries, starts[2])


def test_a_jump_inside_a_kept_block_is_retargeted():
    kept = [(0x11, 0x00), (0x22, 0x00), (0xFF, 0x00)]
    looper = [(0x41, 0x00), (0x42, 0x00), (0xFF, 0x00)]
    entries, starts = _table(_block(0x77), kept, looper)
    # the looper's last row jumps to its own second row
    entries[-1] = (0xFF, starts[2] + 1)
    plan = D.plan_dead_blocks(entries, starts, 0, dead=[0], block_starts=[])
    new = plan.row_map[starts[2]]
    assert plan.entries[new - 1 + 2] == (0xFF, new + 1)


def test_a_block_another_program_jumps_into_is_kept():
    entries, starts = _table(_block(0x11), _block(0x22), _block(0x33))
    # record 0 ends by jumping into record 1's second row
    entries[3] = (0xFF, starts[1] + 1)
    assert D.plan_dead_blocks(entries, starts, 0, dead=[1],
                              block_starts=[]) is None


def test_a_row_something_points_into_keeps_its_block():
    entries, starts = _table(_block(0x11), _block(0x22), _block(0x33))
    assert D.plan_dead_blocks(entries, starts, 0, dead=[1],
                              block_starts=[], operands=[starts[1] + 2]) is None


def test_a_dead_record_sharing_a_kept_start_loses_nothing():
    entries, starts = _table(_block(0x11), _block(0x22))
    starts.append(starts[0])            # record 2 reads record 0's block
    assert D.plan_dead_blocks(entries, starts, 0, dead=[2],
                              block_starts=[]) is None
    # ... and the other way round
    starts[0], starts[2] = starts[2], starts[0]
    assert D.plan_dead_blocks(entries, starts, 0, dead=[0],
                              block_starts=[]) is None


def test_the_protected_rows_and_the_lead_blocks_are_never_dropped():
    entries, starts = _table(_block(0x09), _block(0x22), _block(0x33))
    # lead = 1: starts[0] is the placeholder, not a record
    assert D.plan_dead_blocks(entries, starts, 1, dead=[],
                              block_starts=[]) is None
    plan = D.plan_dead_blocks(entries, starts, 1, dead=[0], block_starts=[])
    assert plan.dropped == (0,) and plan.row_map[1] == 1
    # protect covers the second block: nothing to drop
    assert D.plan_dead_blocks(entries, starts, 1, dead=[0], block_starts=[],
                              protect=8) is None


def test_a_setwaveptr_command_in_the_table_is_followed_and_retargeted():
    entries, starts = _table(_block(0x11),
                             [(0xF8, 0), (0x22, 0), STOP],
                             _block(0x33))
    # the middle block's first row repoints at the last block's third row
    entries[starts[1] - 1] = (D.WAVE_SETPTR, starts[2] + 2)
    plan = D.plan_dead_blocks(entries, starts, 0, dead=[0], block_starts=[])
    assert plan is not None and plan.dropped == (0,)
    new = plan.row_map
    assert plan.entries[new[starts[1]] - 1] == (D.WAVE_SETPTR,
                                                new[starts[2] + 2])
    # a dead block the command lands in is reached, so it is kept
    assert D.plan_dead_blocks(entries, starts, 0, dead=[2],
                              block_starts=[]) is None


def test_a_kept_jump_off_the_table_declines_the_rewrite():
    entries, starts = _table(_block(0x11), _block(0x22))
    entries[-1] = (0xFF, len(entries) + 5)
    assert D.plan_dead_blocks(entries, starts, 0, dead=[0],
                              block_starts=[]) is None


def test_nothing_dead_is_nothing_done():
    entries, starts = _table(_block(0x11), _block(0x22))
    assert D.plan_dead_blocks(entries, starts, 0, dead=[],
                              block_starts=[]) is None


def test_a_jump_into_one_dead_block_spares_that_block_and_only_that_one():
    """The reach is what keeps a jumped-into block while the unreferenced one
    beside it goes; the rewrite's own refusal would otherwise decline both."""
    entries, starts = _table(_block(0x11), _block(0x22), _block(0x33))
    entries[3] = (0xFF, starts[1] + 1)          # record 0 jumps into record 1
    plan = D.plan_dead_blocks(entries, starts, 0, dead=[1, 2],
                              block_starts=[])
    assert plan is not None and plan.dropped == (2,)
    assert plan.row_map[starts[1] + 1] == starts[1] + 1


def test_the_protected_rows_are_roots_their_jumps_keep_what_they_reach():
    library = [(0x11, 0x00), (0x22, 0x00), (0xFF, 0x00)]
    entries, starts = _table(_block(0x44), _block(0x55), _block(0x66))
    entries = library + entries
    starts = [s + 3 for s in starts]
    entries[2] = (0xFF, starts[1] + 1)          # the library jumps into dead 1
    plan = D.plan_dead_blocks(entries, starts, 0, dead=[1, 2],
                              block_starts=[], protect=3)
    assert plan is not None and plan.dropped == (2,)


def test_a_block_that_starts_right_behind_a_dead_one_bounds_it():
    """A clone's block (a start in `block_starts`) is not a part of the dead
    record's block before it, so the dead block goes and the clone's stays."""
    entries, starts = _table(_block(0x11), _block(0x22))
    clone = len(entries) + 1
    entries += _block(0x99)
    plan = D.plan_dead_blocks(entries, starts, 0, dead=[1],
                              block_starts=[clone])
    assert plan is not None and plan.dropped == (1,) and plan.rows == 4
    assert plan.entries[plan.row_map[clone] - 1] == (0x99, 0x00)
    assert len(plan.entries) == len(entries) - 4


def test_instrument_one_is_never_dead_and_dead_means_named_by_no_row():
    pats = [[0x60, 3, 0, 0, 0xFF, 0, 0, 0]]
    # compact layout (lead 0): GT 1 is record 0, GT 3 is record 2
    assert D.dead_records(pats, 5, 0) == [1, 3, 4]
    # inherited layout (lead 1): GT 1 is the placeholder, GT 2 is record 0
    assert D.dead_records(pats, 5, 1) == [0, 2, 3]
    assert D.dead_records([None], 2, 0) == [1]


def test_setwaveptr_operands_are_read_and_remapped_in_place():
    # rows: note, instrument, command, data
    pats = [[0x60, 1, CMD_SETWAVEPTR, 9, 0x60, 2, CMD_SETWAVEPTR, 0,
             0x60, 3, 1, 9, 0xFF, 0, 0, 0], None]
    assert D.setwaveptr_operands(pats) == [9]
    assert D.named_records(pats) == {1, 2, 3}
    D.remap_setwaveptr(pats, {9: 5})
    assert pats[0][3] == 5 and pats[0][7] == 0 and pats[0][11] == 9


# -- the corpus ------------------------------------------------------------

def _convert(name, **over):
    doc = json.loads(PRESETS.read_text(encoding="utf-8"))
    lines = []
    opts = F._preset_opts(doc, f"{name}.sid")
    opts.update(over)
    sng = convert(str(CORPUS / f"{name}.sid"), log=lines.append, **opts)
    return sng, lines


def _canon(wave, ptr):
    """A program from `ptr`, relocation-normalised: rows numbered in the order
    they are reached, jump targets by that number."""
    if not ptr:
        return ()
    num, order, i = {ptr: 0}, [ptr], 0
    while i < len(order):
        left, right = wave[order[i] - 1]
        i += 1
        succ = []
        if left != 0xFF:
            succ.append(order[i - 1] + 1)
        if left in (0xFF, 0xF8) and right:
            succ.append(right)
        for t in succ:
            if t not in num:
                num[t] = len(order)
                order.append(t)
    out = []
    for r in order:
        left, right = wave[r - 1]
        out.append((left, ("->", num[right])
                    if left in (0xFF, 0xF8) and right else right))
    return tuple(out)


def _plays(song):
    """{instrument number: its program} for the records a pattern names,
    plus the programs of the `CMD_SETWAVEPTR` rows."""
    wave = song.tables["WTBL"]
    named = {1}
    ptrs = []
    for pat in song.patterns:
        for r in range(0, len(pat), 4):
            if pat[r + 1]:
                named.add(pat[r + 1])
            if pat[r + 2] == CMD_SETWAVEPTR and pat[r + 3]:
                ptrs.append(pat[r + 3])
    progs = {i.number: _canon(wave, i.wave_ptr) for i in song.instruments
             if i.number in named}
    return progs, [_canon(wave, p) for p in ptrs], named


@needs_corpus
@pytest.mark.parametrize("name", ["Delta_Mix-E-Load_loader", "Zoolook",
                                  "Kings_of_the_Beach_intro",
                                  "Arcade_Classics",
                                  "Dragons_Lair_Part_II",
                                  # operands already in the patterns when the
                                  # blocks go (the attack-hold pass's)
                                  "Lion_Heart", "Sanxion"])
def test_dropping_the_blocks_changes_no_program_that_plays(name, monkeypatch):
    """Files where the freed rows are used by no pass: every named record and
    every pointer command plays the same program, and the table is shorter."""
    new, lines = _convert(name)
    assert any(m.startswith("Dead wavetable blocks") for m in lines)
    monkeypatch.setattr(D, "plan_dead_blocks", lambda *a, **k: None)
    old, _ = _convert(name)
    a, b = songview.parse_sng(old), songview.parse_sng(new)
    assert len(b.tables["WTBL"]) < len(a.tables["WTBL"])
    pa, qa, na = _plays(a)
    pb, qb, nb = _plays(b)
    assert na == nb and pa == pb and qa == qb
    assert a.tracks == b.tracks and a.tables["STBL"] == b.tables["STBL"]


@needs_corpus
def test_last_v8_frees_the_rows_of_its_fifteen_dead_records():
    """The 217-row table of the 33-record file loses the blocks of the 15
    records the pruned song never names (78 rows); the skydive window that
    needed 124 rows plain is laid out compact in the room that is left."""
    sng, lines = _convert("Last_V8")
    (msg,) = [m for m in lines if m.startswith("Dead wavetable blocks")]
    assert "15 record(s)" in msg and "78 of 217 rows freed" in msg
    song = songview.parse_sng(sng)
    assert len(song.tables["WTBL"]) <= GT_MAX_TABLELEN
    _progs, _ptrs, named = _plays(song)
    assert all(i.wave_ptr for i in song.instruments if i.number in named)


@needs_corpus
@pytest.mark.parametrize("name,steps", [("Last_V8", 102),
                                        ("Last_V8_C128_version", 98)])
def test_the_last_v8s_skydive_fits_compact_without_sharing_any_tail(name,
                                                                    steps):
    """With the dead blocks gone the compact program fits on its own: the
    sharing of identical tail programs (`skydive.compact_wave_tail`, 60 rows)
    is no longer reached for."""
    _sng, lines = _convert(name)
    (msg,) = [m for m in lines if m.startswith("Skydive (bit $02)")]
    assert f"{steps} wavetable step(s)" in msg and "compact" in msg, msg
    assert "sharing" not in msg and "not emitted" not in msg, msg


@needs_corpus
@pytest.mark.parametrize("name,dead,freed,then", [
    # the freed rows are spent by the passes that were short of them
    ("Hunter_Patrol", "17 record(s)", "85 of 182 rows freed",
     ("Skydive (bit $02)", "5 program(s)")),
    ("Gremlins", "11 record(s)", "55 of 174 rows freed",
     ("Skydive (bit $02)", "7 program(s)")),
    ("W_A_R_Preview", "20 record(s)", "136 of 255 rows freed",
     ("Past-table wave split", "play one of 1 pinned copy(ies)")),
    ("Mega_Apocalypse", "4 record(s)", "20 of 117 rows freed",
     ("Expanding vibrato loops", "(2 swing(s) merged")),
])
def test_the_rows_it_frees_are_spent_by_the_passes_that_were_short(
        name, dead, freed, then):
    _sng, lines = _convert(name)
    (msg,) = [m for m in lines if m.startswith("Dead wavetable blocks")]
    assert dead in msg and freed in msg, msg
    (spent,) = [m for m in lines if m.startswith(then[0])]
    assert then[1] in spent, spent


@needs_corpus
def test_no_named_record_is_left_without_a_block():
    """The option's invariant on the files that drop the most: whatever the
    patterns name has a program, and every pointer lands inside the table."""
    for name in ("Delta_Mix-E-Load_loader", "Kings_of_the_Beach_intro",
                 "Thundercats", "Hunter_Patrol", "W_A_R_Preview"):
        sng, _ = _convert(name)
        song = songview.parse_sng(sng)
        wave = song.tables["WTBL"]
        _progs, ptrs, named = _plays(song)
        for ins in song.instruments:
            if ins.number in named:
                assert 1 <= ins.wave_ptr <= len(wave), (name, ins.number)
        for left, right in wave:
            if left == 0xFF and right:
                assert 1 <= right <= len(wave), name


@needs_corpus
def test_a_pass_that_names_a_dropped_record_rebuilds_without_the_drop(
        monkeypatch):
    """The safety net: if a later pass names a record whose block went, the
    build is redone with the blocks in place and says so. The last pass before
    the check is made to name every record in a pattern of its own."""
    name = "Delta_Mix-E-Load_loader"
    real = B._gw_rest_park.rest_park_plan

    def naming_everything(patterns, *a, **k):
        out, entries = real(patterns, *a, **k)
        rows = []
        for k_ in range(1, 41):
            rows += [0x60, k_, 0, 0]
        return list(out) + [rows], entries

    monkeypatch.setattr(B._gw_rest_park, "rest_park_plan", naming_everything)
    sng, lines = _convert(name)
    assert any("built again without it" in m for m in lines)
    monkeypatch.setattr(D, "plan_dead_blocks", lambda *a, **k: None)
    plain, plain_lines = _convert(name)
    assert not any(m.startswith("Dead wavetable blocks") for m in plain_lines)
    assert sng == plain


@needs_corpus
def test_the_option_off_leaves_the_table_alone():
    """Without `drop_unnamed_instruments` nothing is dropped: the unnamed
    records are still in the file and still point at their blocks."""
    sng, lines = _convert("Delta_Mix-E-Load_loader",
                          drop_unnamed_instruments=False)
    assert not any(m.startswith("Dead wavetable blocks") for m in lines)
    song = songview.parse_sng(sng)
    assert all(i.wave_ptr for i in song.instruments)


@needs_corpus
def test_a_cut_note_block_moves_with_the_rows_dropped_before_it(monkeypatch):
    """The cut-note programs (`cut_starts`) are laid out behind the records'
    own blocks and named by a CMD_SETWAVEPTR the pass wrote before the blocks
    go: they relocate like every other start. No corpus file has both a cut
    block and a dead record, so the first record of Auf_Wiedersehen_Monty is
    declared dead (and the revival check silenced) and every pointer command
    must still land on the program it landed on."""
    name = "Auf_Wiedersehen_Monty"
    plain, _ = _convert(name)
    ref = songview.parse_sng(plain)
    _progs, ref_ptrs, _named = _plays(ref)
    assert ref_ptrs, "the cut-note pass wrote no pointer command here"
    monkeypatch.setattr(D, "dead_records", lambda *a, **k: [0])
    monkeypatch.setattr(D, "named_records", lambda *a, **k: frozenset())
    sng, lines = _convert(name)
    (msg,) = [m for m in lines if m.startswith("Dead wavetable blocks")]
    assert "1 record(s)" in msg
    song = songview.parse_sng(sng)
    assert len(song.tables["WTBL"]) < len(ref.tables["WTBL"])
    _progs, ptrs, _named = _plays(song)
    assert ptrs == ref_ptrs
    # The later passes read the cut blocks' starts as the rows they must not
    # reuse (`wave_pointers` of the skydive and note-rise plans); no corpus
    # file runs those beside a cut block, so the wiring is asserted at the
    # two calls: the start is one of the kept block starts handed to the
    # plan, and the list holding it is one of those remapped.
    seen = {}
    real_plan, real_remap = D.plan_dead_blocks, D.remap_rows
    real_cut = B._cut_note_pass

    def cut_spy(patterns, targets, *a, **k):
        if targets and len(a) > 1 and "cut" not in seen:
            seen["cut"] = {v[0] for v in targets.values()}
        return real_cut(patterns, targets, *a, **k)

    def plan_spy(entries, wave_starts, lead, dead, block_starts, *a, **k):
        seen["held"] = set(block_starts)
        return real_plan(entries, wave_starts, lead, dead, block_starts,
                         *a, **k)

    def remap_spy(rows, row_map):
        seen.setdefault("remapped", []).append(set(rows))
        return real_remap(rows, row_map)

    monkeypatch.setattr(B, "_cut_note_pass", cut_spy)
    monkeypatch.setattr(D, "plan_dead_blocks", plan_spy)
    monkeypatch.setattr(D, "remap_rows", remap_spy)
    _convert(name)
    assert seen["cut"] and seen["cut"] <= seen["held"], seen
    assert any(seen["cut"] <= rows for rows in seen["remapped"]), seen
