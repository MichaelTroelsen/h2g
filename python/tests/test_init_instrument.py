"""The instrument the original's init starts every voice on, read off the
player, and the entry walk that now starts there.

Goattracker starts a channel on instrument 1 (gplay.c:223). Hubbard's init
writes an instrument index into all three voice slots, and a voice sounds it
until a pattern names another: Knucklebusters starts on `$1B`
(`LDA #$1B / STA $0955,X` at `$043B`), Delta on `$05` (`LDA #$05 / STA
$C2FE,X` at `$BE13`) -- while the file image of the array, which
`Detection.initial_instruments` reads, holds a snapshot of whatever the
ripper last played (`$1B $13 $0B`, `$10 $12 $0F`).

`_entry_instruments` -- the walk every respell, split and decoy pass settles a
row's instrument with -- started every voice on 1. It now starts the first lap
on `Detection.init_instrument` where the player writes one
(`note_passes.init_entry_start`, `entry_instruments_start`).

MEASURED, at base dbb9364 (v0.5.522 + the cycle-6 merges), under presets
(C:/t/entry-instruments-init-index): the corpus byte-hash moves NO file (95
files, 6 refused in both arms, 89 compared, 0 moved), the free-note decline
counts are unchanged in all four files that carry them (Knucklebusters 1,
Delta 11, Flash_Gordon 4, Shockway_Rider 1), and forcing
`initial_instrument` on for the 19 files that start on a read init moves
exactly one (Dragons_Lair_Part_II, two voice orderlists). Every one of those
players names an instrument on the first row of its first pattern, so no
row the passes touch precedes the first named instrument on the first lap.

Delta's "held $02" the trace finds (original pattern $02 entered holding idx
2 at frame 9602) is NOT this: the converter's orderlist for subtune 0 voice
0 ends at 254 entries (`tracks.py`: `if count >= 254: b1 = 0xFF`), before
the original's pattern $05 -- the one that names idx 2 -- so the walk is
right about the file it walks.
"""
import json
import os
import pathlib
import subprocess

import pytest

from corpus import CORPUS, needs_corpus
from h2g.convert import convert
from h2g.detect import (Detection, INSTRUMENT_INDEX_SHAPE,
                        INSTRUMENT_INDEX_SHAPE_ASL4, _find_init_instrument,
                        _search_all, detect)
from h2g.goatwriter import note_passes as NP
from h2g.sidfile import load_sid
from h2g.tracks import _initial_for, convert_tracks

REPO_ROOT = pathlib.Path(__file__).resolve().parents[2]
END = 0xFF

# name -> the index the player's init stores, read off the bytes
# (`LDA #imm / STA array,X / DEX / BPL`); every other corpus player stores
# none, and `detect` leaves `init_instrument` None.
INIT = {
    "ACE_II.sid": 10, "Arcade_Classics.sid": 10,
    "Auf_Wiedersehen_Monty.sid": 16, "BMX_Kidz.sid": 10,
    "Bangkok_Knights.sid": 27, "Chain_Reaction.sid": 27,
    "Deep_Strike.sid": 10, "Delta.sid": 5, "Dragons_Lair_Part_II.sid": 27,
    "Flash_Gordon.sid": 17, "IK_plus.sid": 9, "I_Ball.sid": 17,
    "International_Karate.sid": 20, "Kings_of_the_Beach_ingame.sid": 2,
    "Knucklebusters.sid": 27, "Lightforce.sid": 21,
    "Nemesis_the_Warlock.sid": 15, "Nineteen.sid": 27,
    "One_on_One_Jordan_vs_Bird.sid": 15, "Pandora.sid": 10,
    "Powerplay_Hockey_USA_vs_USSR.sid": 15, "Ricochet.sid": 15,
    "Saboteur_II.sid": 17, "Sanxion.sid": 27, "Shockway_Rider.sid": 12,
    "Sigma_Seven.sid": 7, "Skate_or_Die_intro.sid": 7, "Star_Paws.sid": 19,
    "Tarzan.sid": 18, "Thanatos.sid": 4, "Thundercats.sid": 27,
    "Trans-Atlantic_Balloon_Challenge.sid": 6, "W_A_R.sid": 27,
    "W_A_R_Preview.sid": 27, "Wiz.sid": 27, "Zoolook.sid": 27,
}
# Subtune 0 whose init never reaches the loop: its frame-0 slots are the
# file image. EMPTY since `_reconcile_instrument_index`: the two names that used
# to be here (One_on_One, Powerplay) were an artefact of reading ANOTHER
# player's array -- 4 and 11 against `3F 42 88` / `00 01 01` -- and the tune
# player's own array holds `0F 0F 0F` at frame 0 of subtune 0 in both
# (tests/test_instrument_index_reconcile.py).
IMAGE_AT_SUBTUNE_0: set = set()


# --- the signature ---------------------------------------------------------

ARRAY = 0x0955


def _init_loop(value=0x1B, array=ARRAY, tail=(0xCA, 0x10, 0xE1)):
    lo, hi = array & 0xFF, array >> 8
    return bytes((0x99, 0x06, 0xD4, 0xA9, value, 0x9D, lo, hi) + tail)


def test_the_store_is_read_off_the_loop():
    assert _find_init_instrument(b"\xEA" * 9 + _init_loop(0x1B), ARRAY) == 0x1B
    assert _find_init_instrument(_init_loop(0x05), ARRAY) == 0x05


def test_a_store_outside_a_voice_loop_is_not_the_init():
    """`CA 10` -- DEX / BPL -- is what says the store covers every voice: the
    same `STA array,X` closes the pattern reader (`INC off,X` ... `STA
    array,X / JMP`), which writes the instrument a pattern names."""
    assert _find_init_instrument(_init_loop(tail=(0x4C, 0x36, 0x05)),
                                 ARRAY) is None
    assert _find_init_instrument(_init_loop(tail=(0xCA, 0xD0, 0xE1)),
                                 ARRAY) is None


def test_only_an_immediate_is_an_init_value():
    """`TXA / STA array,X` (the voice number) or a load from a table is not a
    constant the walk can start on."""
    blob = bytes((0x8A, 0x9D, 0x55, 0x09, 0xCA, 0x10, 0xE1))
    assert _find_init_instrument(blob, ARRAY) is None


def test_disagreeing_stores_read_nothing():
    assert _find_init_instrument(_init_loop(0x1B) + _init_loop(0x05),
                                 ARRAY) is None
    assert _find_init_instrument(_init_loop(0x1B) + _init_loop(0x1B),
                                 ARRAY) == 0x1B


def test_a_store_to_another_array_is_not_this_ones():
    assert _find_init_instrument(_init_loop(array=0x0956), ARRAY) is None


# --- every corpus player ---------------------------------------------------

def _sid(name):
    sid = load_sid(str(CORPUS / name))
    return sid, detect(sid, log=lambda m: None)


@needs_corpus
def test_the_init_index_is_read_for_exactly_these_players():
    got = {}
    for path in sorted(CORPUS.glob("*.sid")):
        try:
            _sid_, det = _sid(path.name)
        except Exception:
            continue                      # a refused file has no detection
        if det.init_instrument is not None:
            got[path.name] = det.init_instrument
    assert got == INIT, {k: (got.get(k), INIT.get(k))
                         for k in set(got) | set(INIT)
                         if got.get(k) != INIT.get(k)}


@needs_corpus
def test_the_file_image_is_not_the_init_value():
    """Why it is read off the code: Knucklebusters' image is `$1B $13 $0B`
    and Delta's `$10 $12 $0F`."""
    _s, kb = _sid("Knucklebusters.sid")
    _s, delta = _sid("Delta.sid")
    assert kb.initial_instruments == (0x1B, 0x13, 0x0B)
    assert kb.init_instrument == 0x1B
    assert delta.initial_instruments == (0x10, 0x12, 0x0F)
    assert delta.init_instrument == 0x05


def _tune_array(sid, det):
    """The per-voice array of the player whose instrument table `detect`
    found: the first match, in either spelling, whose second `LDA` names that
    table. (The shape's FIRST match is not always the tune player's.)"""
    data = sid.data
    table = sid.to_address(det.instr_start)
    for shape, op in ((INSTRUMENT_INDEX_SHAPE, 11),
                      (INSTRUMENT_INDEX_SHAPE_ASL4, 12)):
        for i in _search_all(data, shape):
            if (data[i + op] | data[i + op + 1] << 8) - 2 == table:
                return data[i + 1] | data[i + 2] << 8
    raise AssertionError("no index load names the instrument table")


def _slots_at_frame_zero(name, subtune=0):
    from fidelity import SIDDUMP
    if not pathlib.Path(SIDDUMP).exists():
        pytest.skip("siddump-rt is not built")
    sid = load_sid(str(CORPUS / name))
    data = sid.data
    array = _tune_array(sid, detect(sid, log=lambda m: None))
    out = subprocess.run(
        [SIDDUMP, str(CORPUS / name), f"-a{subtune}", "-t1", "-v1",
         f"-w{array:04x},{array + 1:04x},{array + 2:04x}"],
        capture_output=True, text=True).stdout
    for line in out.splitlines():
        parts = [p.strip() for p in line.split("|")]
        if len(parts) >= 7 and parts[1].isdigit() and int(parts[1]) == 0:
            return tuple(int(x, 16) for x in parts[6].split())
    raise AssertionError(f"no frame 0 in siddump output for {name}")


@needs_corpus
@pytest.mark.parametrize("name", sorted(INIT))
def test_siddump_finds_the_init_index_in_every_slot_at_frame_0(name):
    """The trace is the check: frame 0 of subtune 0 holds the index in all
    three slots, except in the two players whose init branches round the
    loop for that subtune -- there the slots are the file image."""
    _s, det = _sid(name)
    slots = _slots_at_frame_zero(name)
    if name in IMAGE_AT_SUBTUNE_0:
        assert slots == det.initial_instruments, (name, slots)
        assert slots != (INIT[name],) * 3
    else:
        assert slots == (INIT[name],) * 3, (name, slots)


# --- the walk's start ------------------------------------------------------

def _song():
    """Pattern 0 plays two notes before anything names an instrument; pattern 1
    names 7 on its first row; pattern 2 names none."""
    pats = [[0x20, 0, 0, 0, 0x22, 0, 0, 0, END, 0, 0, 0],
            [0x24, 7, 0, 0, END, 0, 0, 0],
            [0x26, 0, 0, 0, END, 0, 0, 0]]
    # A restart past the end is no restart: one lap, so a start is all the
    # first lap there is.
    tracks = [[0, 1, 2, END, 9], [2, END, 9], [END, 9]]
    return tracks, pats


def test_the_walk_starts_on_goattrackers_instrument_1_by_default():
    tracks, pats = _song()
    entry = NP._entry_instruments(tracks, pats)
    assert entry[0] == {1}
    assert entry[2] == {1, 7}          # voice 0 after pattern 1; voice 1 first


def test_the_walk_starts_on_the_init_instrument_where_given():
    tracks, pats = _song()
    entry = NP._entry_instruments(tracks, pats, start=(28, 28, 28))
    assert entry[0] == {28}
    assert entry[2] == {28, 7}         # the first lap of voice 1 holds 28


def test_each_voice_has_its_own_start():
    tracks, pats = _song()
    tracks = [[2, END, 9], [2, END, 9], [2, END, 9]]
    entry = NP._entry_instruments(tracks, pats, start=(4, 5, 6))
    assert entry[2] == {4, 5, 6}


def test_a_later_subtunes_voice_takes_the_same_voices_start():
    tracks, pats = _song()
    two = [[2, END, 9], [END, 9], [END, 9], [2, END, 9], [END, 9], [END, 9]]
    assert NP._entry_instruments(two, pats, start=(4, 5, 6))[2] == {4}
    two[3] = [END, 9]
    two[4] = [2, END, 9]
    assert NP._entry_instruments(two, pats, start=(4, 5, 6))[2] == {4, 5}


def test_the_second_lap_carries_what_the_first_ended_on():
    """The restart keeps the instrument (gplay.c:966-968): a start applies to
    the first lap only."""
    pats = [[0x20, 0, 0, 0, END, 0, 0, 0],
            [0x24, 7, 0, 0, END, 0, 0, 0]]
    tracks = [[0, 1, END, 0], [END, 0], [END, 0]]
    assert NP._entry_instruments(tracks, pats, start=(28, 28, 28))[0] == {28, 7}
    assert NP._entry_instruments(tracks, pats)[0] == {1, 7}


def test_the_context_sets_every_reader_and_restores():
    tracks, pats = _song()
    before = NP._entry_instruments(tracks, pats)
    with NP.entry_instruments_start((28, 28, 28)):
        assert NP._entry_instruments(tracks, pats)[0] == {28}
        # `_position_entries` is the same walk per position.
        assert NP._position_entries(tracks, pats)[(0, 0)] == {28}
        # An explicit argument wins.
        assert NP._entry_instruments(tracks, pats, start=(3, 3, 3))[0] == {3}
    assert NP._entry_instruments(tracks, pats) == before
    assert NP._position_entries(tracks, pats)[(0, 0)] == {1}


def test_the_context_restores_when_the_block_raises():
    tracks, pats = _song()
    with pytest.raises(RuntimeError):
        with NP.entry_instruments_start((28, 28, 28)):
            raise RuntimeError
    assert NP._entry_instruments(tracks, pats)[0] == {1}


# --- which start, in which numbering -----------------------------------------

def _det(**kw):
    det = Detection()
    det.instr_used = kw.pop("instr_used", 29)
    for k, v in kw.items():
        setattr(det, k, v)
    return det


def test_the_start_is_in_the_numbering_the_patterns_use():
    det = _det(init_instrument=27)
    assert NP.init_entry_start(det, 1) == (28, 28, 28)     # compact
    assert NP.init_entry_start(det, 2) == (29, 29, 29)     # inherited layout


def test_no_start_where_nothing_was_read():
    assert NP.init_entry_start(_det(), 1) is None


def test_no_start_where_the_player_parks_silence_until_an_instrument():
    """A note before the first instrument sounds nothing there
    (`silence_pre_instrument_notes` keys it off), so there is no row an
    instrument could be wrong for."""
    assert NP.init_entry_start(
        _det(init_instrument=5, pre_instrument_silence=True), 1) is None


def test_no_start_where_the_index_names_no_record():
    assert NP.init_entry_start(_det(init_instrument=29), 1) is None
    assert NP.init_entry_start(_det(init_instrument=28), 1) == (29, 29, 29)
    # Wiz's init writes $1B against a 20-record table.
    assert NP.init_entry_start(_det(init_instrument=27, instr_used=20),
                               1) is None


def test_no_start_past_the_instrument_number_cap():
    det = _det(init_instrument=60, instr_used=80)
    assert NP.init_entry_start(det, 1) is None


def test_the_option_path_gives_every_voice_the_init_index():
    """`apply_initial_instruments` read the image, so voices 1 and 2 of
    Knucklebusters would have started on `$13` and `$0B`."""
    det = _det(init_instrument=27, initial_instruments=(27, 19, 11))
    assert [_initial_for(det, v, 1) for v in range(3)] == [28, 28, 28]
    det = _det(initial_instruments=(27, 19, 11))
    assert [_initial_for(det, v, 1) for v in range(3)] == [28, 20, 12]


# --- the corpus, end to end ----------------------------------------------------

def _convert_with_start(name, monkeypatch, start):
    import fidelity as F
    doc = json.loads((REPO_ROOT / "presets.json").read_text(encoding="utf-8"))
    seen = {}
    real = NP._entry_instruments

    def spy(tracks, patterns, start=None):
        seen.setdefault("start", NP._ENTRY_START.get())
        return real(tracks, patterns, start)
    monkeypatch.setattr(NP, "_entry_instruments", spy)
    if start is False:
        monkeypatch.setattr(NP, "init_entry_start", lambda det, base: None)
    return convert(str(CORPUS / name), log=lambda m: None,
                   **F._preset_opts(doc, name)), seen


@needs_corpus
def test_knucklebusters_builds_on_the_players_start(monkeypatch):
    sng, seen = _convert_with_start("Knucklebusters.sid", monkeypatch, True)
    assert seen["start"] == (28, 28, 28)           # $1B + the compact base


@needs_corpus
def test_delta_keeps_instrument_1_because_it_parks_silence(monkeypatch):
    sng, seen = _convert_with_start("Delta.sid", monkeypatch, True)
    assert seen["start"] is None


@needs_corpus
@pytest.mark.parametrize("name", ["Knucklebusters.sid", "Flash_Gordon.sid"])
def test_the_start_moves_no_byte_where_every_first_pattern_names_one(
        name, monkeypatch):
    """Measured over the whole corpus under presets: 0 of 89 files move. Pinned
    on the two files the free-note respell was traced on. A file that starts
    to move is a file whose first lap has a respelled row before its first
    named instrument -- measure it against a trace before taking it."""
    with_start, seen = _convert_with_start(name, monkeypatch, True)
    assert seen["start"] is not None
    without, _ = _convert_with_start(name, monkeypatch, False)
    assert with_start == without


@needs_corpus
def test_delta_orderlist_ends_before_the_pattern_naming_instrument_3():
    """The original's pattern $05 names idx 2 (GT 3) at frame 9602; the
    converted voice-0 orderlist is cut at the 254-entry read limit before
    reaching it, so the walk's {1, 2} for GT pattern 3 is the file's."""
    sid, det = _sid("Delta.sid")
    tracks = convert_tracks(sid, det, lambda m: None)
    assert len(tracks[0]) == 254
    assert 5 not in tracks[0]
