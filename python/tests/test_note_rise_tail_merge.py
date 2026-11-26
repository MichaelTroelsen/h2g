"""Records that end in another record's rows give them to the note rise
(`note_rise.tail_merges`), and the fixed arp's phase vote counts every lap
(`arpeggio.FIXED_ARP_VOTE_UNROLLED`).

Game_Killer's voice 2 plays record 5 once an 80-frame lap, on one counter
residue in lap 1 and on another in lap 2. `_note_phase_split` voted on lap 1
by note count -- {1: 5, 3: 1, 7: 1} against its factor of 2 -- so no clone
of record 5 was built and its 112 notes a lap-2 residue-7 first octave step
one tick early (tiefr 79%, `tie_orig_only` 600). Voted over the unrolled laps,
by the share of the lap each residue is heard for, record 5 gets its two
clones (and record 6 one more): 3 clones, 22 wavetable entries.

The 255-entry table was full without them: the note rise ("carried on through
the rest after" a note, `_extension_pays`) needed 22 entries at 233, and with
the clones it was refused and fell back to 176 store rows, which took vib .99
-> .90, travel .96 -> .85 and bend .87 -> .83 with it
(`listen-sub99-game-killer`, runs.jsonl). Records 5, 6 and 7 are one program
at three heads -- after their first five rows each is the same eleven rows --
so two of them jump into the third's (a jump is free, player.s
`mt_nowavechange`) and their rows are free: 20 entries, which the programs
take. Game_Killer's 22 wavetable steps become 0 appended past the table; its
note rise keeps all 295 store rows and goes from 18 to 22 values.

Corpus byte-hash under presets, 95 files (89 converted, 6 refused): the vote
moves Game_Killer only; the tails (`TAIL_MERGE_MIN_FREED` 8) move
Game_Killer and Monty_on_the_Run (76 -> 81 of 127 store values), by programs
placed in rows they did not have free. At 3 they also moved Battle_of_Britain,
Chimera, Geoff_Capes_Strongman_Challenge, Gerry_the_Germ and Human_Race.
"""
import json
import pathlib
import sys

import pytest

from corpus import CORPUS, needs_corpus

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[1]))

import fidelity                                              # noqa: E402
import songview                                              # noqa: E402
from h2g.goatwriter import arpeggio as A                     # noqa: E402
from h2g.goatwriter import note_rise as R                    # noqa: E402

PYTHON_ROOT = pathlib.Path(__file__).resolve().parents[1]

# Three heads on one eleven-row tail (holds, then a loop of holds whose jump
# goes back into the run), as Game_Killer's records 5, 6 and 7 are.
TAIL = [(0x0F, 0x80)] * 3 + [(0x01, 0x00), (0x09, 0x0C)] + [(0x0F, 0x80)] * 4 \
    + [(0x05, 0x00)]
HEADS = [[(0x81, 0x00), (0x08, 0x80), (0x80, 0x80)],
         [(0x11, 0x00), (0x08, 0x80), (0x10, 0x80)],
         [(0x41, 0x00), (0x08, 0x80), (0x40, 0x80)]]


def _block(head, start):
    """`head`, the tail, and the loop's jump back to the tail's 5th row."""
    return list(head) + TAIL + [(0xFF, start + len(head) + 4)]


def _table():
    """Three blocks at 1, 15 and 29 (14 rows each), a block that stops at
    43, and a clone at 46 whose last row jumps into the first block's loop
    (row 1 + 3 + 4 = 8)."""
    wave, starts = [], []
    for head in HEADS:
        starts.append(len(wave) + 1)
        wave += _block(head, len(wave) + 1)
    starts.append(len(wave) + 1)
    wave += [(0x41, 0x00), (0x07, 0x00), (0xFF, 0x00)]
    starts.append(len(wave) + 1)
    wave += [(0x11, 0x00), (0x09, 0x00), (0xFF, 8)]
    return wave, starts


def _calls(wave, start, n=400):
    """The entry each of the first `n` play calls executes from `start`: a
    delay entry is current for `value + 1` calls, any other for one, a jump
    costs none and a stop ends the program (player.s `mt_waveexec`)."""
    out, row = [], start
    while len(out) < n and 1 <= row <= len(wave):
        left, right = wave[row - 1]
        if left == 0xFF:
            if not right:
                break
            row = right
            continue
        out += [(left, right)] * (left + 1 if left <= 0x0F else 1)
        row += 1
    return out[:n]


def test_the_tails_two_blocks_share_with_a_third_are_freed():
    wave, starts = _table()
    merges = R.tail_merges(wave, starts, [])
    assert len(merges) == 2
    # the tail is eleven rows (ten of holds and the loop's jump): the first
    # becomes the jump into the kept block's, the other ten are free
    assert sorted(m["start"] for m in merges) == [1, 29]
    assert {m["into"] for m in merges} == {15}
    for m in merges:
        first = m["start"] + 3
        assert m["freed"] == (first + 1, 10), m
        assert m["edits"][first] == (0xFF, 15 + 3), m


def test_a_merged_table_plays_every_program_call_for_call():
    wave, starts = _table()
    after = list(wave)
    for m in R.tail_merges(wave, starts, []):
        for row, entry in m["edits"].items():
            after[row - 1] = entry
        lo, n = m["freed"]
        for row in range(lo, lo + n):            # a program overwrites them
            after[row - 1] = (0x0E, 0xEE)
    for start in starts:
        before = _calls(wave, start)
        assert len(before) > 100 or start == starts[3]   # the one that stops
        assert _calls(after, start) == before, start


def test_a_jump_into_a_freed_tail_follows_it_to_the_kept_one():
    """The clone's `FF 08` lands on the first block's loop row; block 1's
    tail is freed, so it lands on the same row of block 15's (15 + 3 + 4)."""
    wave, starts = _table()
    edits = {}
    for m in R.tail_merges(wave, starts, []):
        edits.update(m["edits"])
    assert edits[48] == (0xFF, 22), edits


def test_a_pointer_into_a_tail_leaves_it_whole():
    wave, starts = _table()
    inside = 29 + 3 + 6                          # a row of the last tail
    got = R.tail_merges(wave, starts, [inside])
    assert all(m["start"] != 29 for m in got)
    for m in got:
        assert not (m["freed"][0] <= inside < m["freed"][0] + m["freed"][1])


def test_blocks_with_different_tails_are_left_alone():
    wave, starts = _table()
    wave[15 + 3 + 6 - 1] = (0x0E, 0x80)          # the middle tail differs
    wave[29 + 3 + 6 - 1] = (0x0D, 0x80)          # and so does the last
    assert R.tail_merges(wave, starts, []) == []


# --- the corpus ----------------------------------------------------------

def _converted(name, **extra):
    import h2g.convert as C
    doc = json.loads((PYTHON_ROOT.parent / "presets.json").read_text())
    lines = []
    opts = fidelity._preset_opts(doc, f"{name}.sid")
    opts.update(extra)
    sng = C.convert(str(CORPUS / f"{name}.sid"), log=lines.append, **opts)
    return sng, lines


def _rise(lines):
    (one,) = [m for m in lines if "Note rise (bit $02)" in m]
    return one


@needs_corpus
def test_game_killers_record_five_gets_its_clones_and_the_rise_keeps_its_rows():
    sng, lines = _converted("Game_Killer")
    split = [m for m in lines if m.startswith("arp phase split")]
    assert len(split) == 1 and "11 clone(s)" in split[0], split
    assert "(5, 13, 3), (5, 14, 7)" in split[0], split
    rise = _rise(lines)
    assert "295 store row(s)" in rise and "22 of 118" in rise, rise
    assert "0 wavetable step(s) at 255" in rise and "3 shared tail(s)" in rise
    assert "3 note(s) carried on through the rest after them" in rise, rise
    wt = songview.parse_sng(sng).tables["WTBL"]
    assert len(wt) <= 255


@needs_corpus
def test_without_the_vote_over_the_laps_record_five_has_no_clone(monkeypatch):
    monkeypatch.setattr(A, "FIXED_ARP_VOTE_UNROLLED", False)
    _sng, lines = _converted("Game_Killer")
    split = [m for m in lines if m.startswith("arp phase split")]
    assert "8 clone(s)" in split[0] and "(5, " not in split[0], split


@needs_corpus
def test_without_the_freed_tails_the_clones_cost_the_rise_its_continuation(
        monkeypatch):
    """The experiment of `listen-sub99-game-killer`: the clones alone."""
    monkeypatch.setattr(R, "NOTE_RISE_TAIL_MERGE", False)
    _sng, lines = _converted("Game_Killer")
    rise = _rise(lines)
    assert "carried on through the rest" not in rise, rise
    assert "295 store row(s)" not in rise, rise


MOVED = ["Game_Killer", "Monty_on_the_Run"]


@needs_corpus
@pytest.mark.parametrize("name", MOVED)
def test_every_record_plays_what_it_played_without_the_merge(name, monkeypatch):
    """Only programs are placed in the freed rows: each instrument's wavetable
    program, jumps followed, calls the same 600 entries with the merge as
    without it."""
    on, _ = _converted(name)
    monkeypatch.setattr(R, "NOTE_RISE_TAIL_MERGE", False)
    off, _ = _converted(name)
    a, b = songview.parse_sng(on), songview.parse_sng(off)
    assert len(a.instruments) == len(b.instruments)
    wa, wb = a.tables["WTBL"], b.tables["WTBL"]
    seen = 0
    for x, y in zip(a.instruments, b.instruments):
        assert (x.wave_ptr == 0) == (y.wave_ptr == 0), x.number
        if x.wave_ptr:
            assert _calls(wa, x.wave_ptr, 600) == _calls(wb, y.wave_ptr, 600), (
                name, x.number)
            seen += 1
    assert seen >= 5
    assert on != off
