"""The wave program's `$85` restore keeps the gate, as the player does.

Opened as wave-program-restore-releases-gate-early (by
nemesis-counter-gate-age-1-move). `_wave_program_entries` wrote the restore
as `persist & ~WAVE_GATE_BIT`, so the voice's gate fell at the program's hold.
The player's `$85` does not release it: Nemesis jumps to `$E3F0`
(`LDA $E4FA,X / AND $E503,X / STA $D404,Y`) and `$E503` is `$FF` until the
note's own gate-off (`$E1C1`), so `0B09`/`0C0A` read `/41` and `0C5A` `/11` for
every frame of the note. Ours went `/40` from frame 4 and `/10` from frame 6,
entering the release early. The same `LDA stored / AND mask / STA $D404,Y`
shape is the waveform writer of 27 of the 29 corpus wave-program players
(IK_plus and Mega_Apocalypse spell it differently). Goattracker's own
key-off clears the gate on `cptr->gate`, so a restore that keeps the bit
still releases when the pattern ends the note.

**Which opcodes write the stored cell is the player's.** Nine files' `>= $80`
opcode also stores to it (`PHA ... PLA / STA stored,X`), so their hold sounds
the LAST opcode's waveform -- Pygmies' `set $80` tail, ungated -- and clearing
the gate happened to match them. Keeping the gate without that second half
re-gated Pygmies' tail as `$41` (retrigger ratio 1.0465 -> 1.1403, 137 extra
gate rises on voice 1, measured before the family was read).
"""
import pathlib
import sys

import pytest

PYTHON_ROOT = pathlib.Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PYTHON_ROOT))

from corpus import CORPUS, needs_corpus  # noqa: E402

JUMP = 0xFF
PORTAS = (0xF1, 0xF2)

# The files whose `>= $80` opcode also writes the stored waveform, read off
# the player's `C9 85 D0 03 4C` block by hand (Pygmies `$1387`: `9D 04 D4 /
# 48 ... 68 / 9D 54 16`) -- the independent half of the detector's test.
SET_STORES = {"After_8", "Kings_of_the_Beach_intro", "Mr_Meaner",
              "Off_the_Cuff", "One_on_One_Jordan_vs_Bird",
              "Powerplay_Hockey_USA_vs_USSR", "Pygmies_Revenge", "Rikky",
              "Rock_Tells_the_Tale"}
WAVE_PROGRAM_FILES = [
    "ACE_II", "After_8", "Arcade_Classics", "Auf_Wiedersehen_Monty",
    "Bangkok_Knights", "BMX_Kidz", "Chain_Reaction", "I_Ball", "IK_plus",
    "Kings_of_the_Beach_intro", "Mega_Apocalypse", "Mr_Meaner",
    "Nemesis_the_Warlock", "Nineteen", "Off_the_Cuff",
    "One_on_One_Jordan_vs_Bird", "Pandora", "Powerplay_Hockey_USA_vs_USSR",
    "Pygmies_Revenge", "Ricochet", "Rikky", "Rock_Tells_the_Tale",
    "Saboteur_II", "Shockway_Rider", "Skate_or_Die_intro", "Star_Paws",
    "Thundercats", "Trans-Atlantic_Balloon_Challenge", "Wiz",
]
MULTIPLIER = {"ACE_II": 3, "Chain_Reaction": 3, "Kings_of_the_Beach_intro": 5,
              "Mr_Meaner": 5, "Off_the_Cuff": 5, "Ricochet": 2,
              "Rock_Tells_the_Tale": 6, "Saboteur_II": 3,
              "Shockway_Rider": 2, "Skate_or_Die_intro": 2, "Star_Paws": 2,
              "Thundercats": 3}


def _tables(name):
    from h2g.convert import _detect_tables
    from h2g.sidfile import load_sid
    return _detect_tables(load_sid(str(CORPUS / f"{name}.sid")),
                          lambda *a, **k: None)


def _entries(name, i, multiplier=1, hold_travel=False, budget=120):
    from h2g.goatwriter.wave_program import _wave_program_entries
    sid, det = _tables(name)
    return _wave_program_entries(sid, det, i, [], "gts5", multiplier, budget,
                                 False, hold_travel)


def _restore(left):
    """The restore entry: the one before the stop, past a closing travel."""
    assert left[-1] == JUMP
    k = len(left) - 2
    if left[k] in PORTAS:
        k -= 1
    return left[k]


@needs_corpus
@pytest.mark.parametrize("i,want", [(3, 0x41), (11, 0x41), (12, 0x11)])
def test_nemesis_chain_restore_keeps_the_gate(i, want):
    # the gated slide chain's restore, `/00` on the note
    left, right = _entries("Nemesis_the_Warlock", i)
    assert (left[-2], right[-2], left[-1]) == (want, 0x00, JUMP), \
        [hex(x) for x in left]


@needs_corpus
def test_general_path_restore_keeps_the_gate_ik_plus_record_2():
    # IK_plus `$08D8`: the stored cell is the last `< $80` opcode's `$41`
    # (the `$40` the restore wrote ended its gate), not the record's `$11`.
    left, right = _entries("IK_plus", 2)
    assert left[-2:] == [0x41, JUMP], [hex(x) for x in left]


@needs_corpus
def test_a_player_whose_set_does_not_store_keeps_the_last_slides_wave():
    # Ricochet record 2 packs at -S2: `set $80` x16 after a `$41` slide, and
    # the hold goes back to the slide's `$41` with its gate.
    left, right = _entries("Ricochet", 2, multiplier=2)
    assert left[-3:] == [0x41, 0xF2, JUMP], [hex(x) for x in left]


@needs_corpus
@pytest.mark.parametrize("name,i,m", [("Pygmies_Revenge", 0, 1),
                                      ("Pygmies_Revenge", 2, 1),
                                      ("Kings_of_the_Beach_intro", 2, 5),
                                      ("Off_the_Cuff", 0, 5)])
def test_a_player_whose_set_stores_restores_the_last_sets_wave(name, i, m):
    # Pygmies `$0782`: the program ends `set $80` and the original reads
    # `$80` from the last frame to the next note -- not a re-gated `$41`.
    left, right = _entries(name, i, multiplier=m)
    assert _restore(left) == 0x80, [hex(x) for x in left]


@needs_corpus
def test_the_detector_reads_the_nine_stored_cell_players():
    from h2g.detect import wave_program_set_stores_wave
    got = set()
    for name in WAVE_PROGRAM_FILES:
        sid, det = _tables(name)
        if wave_program_set_stores_wave(sid, det):
            got.add(name)
    assert got == SET_STORES, sorted(got ^ SET_STORES)


@needs_corpus
def test_a_stored_waveform_without_a_gate_stays_without_one():
    # Skate_or_Die's `slide $00` ending stores no waveform: that restore is
    # silence, and keeping the gate must not conjure one.
    from h2g.detect import decode_wave_program
    from h2g.goatwriter.primitives import _wave_byte
    sid, det = _tables("Skate_or_Die_intro")
    found = 0
    for i in range(32):
        got = _entries("Skate_or_Die_intro", i, multiplier=2)
        if got is None:
            continue
        rec = det.instr_start + i * det.instr_stride
        off = det.wave_program + i * det.instr_stride
        at = sid.to_offset(sid.data[off] | sid.data[off + 1] << 8)
        stored = sid.data[rec + 2]
        for kind, wave, _ in decode_wave_program(sid.data, at):
            if kind == "slide":
                stored = wave
        if not stored & 1:
            assert _restore(got[0]) == _wave_byte(stored), i
            assert not _restore(got[0]) & 1, i
            found += 1
    assert found, "no gate-less stored waveform in the file any more"


@needs_corpus
@pytest.mark.parametrize("name", WAVE_PROGRAM_FILES)
def test_every_restore_in_the_corpus_is_the_stored_cell_verbatim(name):
    """The player writes `stored & mask` and the mask is `$FF` until the note
    ends: the restore is the stored waveform with whatever gate it has."""
    from h2g.detect import decode_wave_program
    from h2g.goatwriter.primitives import _wave_byte
    sid, det = _tables(name)
    mult = MULTIPLIER.get(name, 1)
    checked = 0
    for i in range(32):
        got = _entries(name, i, multiplier=mult)
        if got is None:
            continue
        rec = det.instr_start + i * det.instr_stride
        off = det.wave_program + i * det.instr_stride
        at = sid.to_offset(sid.data[off] | sid.data[off + 1] << 8)
        prog = decode_wave_program(sid.data, at)
        n_ops = sum(1 for k, _, _ in prog if k != "hold")
        if n_ops > 60 or len(got[0]) >= 118:    # budget-truncated: not this rule
            continue
        stored = sid.data[rec + 2]
        for kind, wave, _ in prog:
            if kind == "slide" or (kind == "set" and name in SET_STORES):
                stored = wave
        assert _restore(got[0]) == _wave_byte(stored), \
            (name, i, hex(_restore(got[0])), hex(stored))
        checked += 1
    # Powerplay's tune-engine records run past the 64-opcode read with no
    # hold in view (its preset leaves `wave_program` off): nothing to check.
    assert checked or name == "Powerplay_Hockey_USA_vs_USSR", name
