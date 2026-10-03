"""Rejecting detections that matched something other than the tune's player.

Signature matching gives no guarantee the operands it reads are really table
addresses. When they are not, every downstream guard behaves correctly on
garbage and the result is a structurally valid, musically empty .sng -- a
failure that reads as a success. Two corpus files did exactly that:

  One on One: Jordan vs Bird  the three "orderlist" pointers land in
                              nibble-packed sample data; 89% of the references
                              they yield name patterns that do not exist
  ACE 2                       the first orderlist byte is already a restart
                              command, so no subtune plays anything

Individually bad references are normal -- phantom subtunes alone account for
up to 46% of a real file's references (Mega Apocalypse) -- so only the
proportion across the whole file separates the two cases.
"""
import pathlib
import sys

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[1]))

import pytest

import corpus
from h2g.convert import (MAX_DANGLING_SHARE, UnsupportedSidError,
                         check_detection_sound)

PATTERN_USED = 9   # patterns $00-$09 exist


def _check(tracks):
    check_detection_sound(tracks, PATTERN_USED, log=lambda m: None)


def test_clean_orderlist_passes():
    _check([[0x00, 0x01, 0x09, 0xFF, 0x00]])


def test_no_subtune_at_all_is_rejected():
    # convert_tracks returns [] rather than fabricating a placeholder subtune;
    # the placeholder referenced pattern 0 and so looked sound to every check.
    with pytest.raises(UnsupportedSidError, match="NO PLAYABLE SUBTUNE"):
        _check([])


def test_mostly_dangling_orderlist_is_rejected():
    # 3 of 4 references (75%) name patterns that do not exist.
    with pytest.raises(UnsupportedSidError, match="UNSOUND"):
        _check([[0x63, 0x7A, 0x05, 0x51, 0xFF, 0x00]])


def test_a_minority_of_dangling_references_is_tolerated():
    # Half the references dangle -- worse than any real corpus file, and still
    # not enough to condemn the detection. Losing those rows is the known,
    # reported behaviour; refusing the file outright would be worse.
    _check([[0x63, 0x01, 0x7A, 0x02, 0xFF, 0x00]])


def test_threshold_is_exclusive():
    # Exactly at the limit passes; the check fires only above it.
    assert MAX_DANGLING_SHARE == 2 / 3
    _check([[0x63, 0x7A, 0x05, 0xFF, 0x00]])                   # 2 of 3 dangle
    with pytest.raises(UnsupportedSidError):
        _check([[0x63, 0x7A, 0x51, 0x05]])                     # 3 of 4 dangle


def test_restart_position_is_not_counted_as_a_reference():
    # The byte after $FF is a restart position, not a pattern reference. Here
    # it is $63 -- out of range, so counting it would put this file at 25%
    # dangling instead of 0%. The grammar itself is covered by test_prune.
    _check([[0x01, 0x02, 0x03, 0xFF, 0x63]])


def test_commands_are_not_counted_as_references():
    # $D0-$FE are repeat/transpose commands, all >= the pattern ceiling. If
    # they were counted, every transposed tune would look unsound.
    _check([[0xF7, 0x01, 0xF2, 0x02, 0xD3, 0x03, 0xFF, 0x00]])


# --- pulse_reseed_gate: the bounds engine's reseed-gate spelling, per file ---
#
# Read C:/t/pulse-phase-sim-for-the-boun/WIRING.md before touching this
# section: a walk over `pulse_bounds` records that reseeds $D402/$D403 at
# note start is validated (100% of steps, 100% of attack onsets on a 180 s
# siddump trace -- see the two `test_..._reseed_gate_is_validated_on_` tests
# below) ONLY where `pulse_reseed_gate` is "lda_bmi" or "other"; IK_plus
# matches neither spelling and a walk must not assume the rule for it. This
# is the population census that pins per file which spelling detect() finds,
# so a signature edit that silently moves a file between the three groups
# fails a named test instead of degrading a walk nobody re-checks.
#
# Every name here is in presets.json and exists under corpus.CORPUS at
# recording time (see test_every_named_file_is_a_real_bounds_engine_file).
_PULSE_RESEED_LDA_BMI = {
    "ACE_II.sid", "Auf_Wiedersehen_Monty.sid", "Chain_Reaction.sid",
    "Deep_Strike.sid", "Delta.sid", "Delta_Mix-E-Load_loader.sid",
    "Dragons_Lair_Part_II.sid", "Flash_Gordon.sid", "Food_Feud.sid",
    "I_Ball.sid", "Kings_of_the_Beach_ingame.sid", "Knucklebusters.sid",
    "Lightforce.sid", "Nemesis_the_Warlock.sid", "Nineteen.sid",
    "One_on_One_Jordan_vs_Bird.sid", "Pandora.sid", "Saboteur_II.sid",
    "Sanxion.sid", "Shockway_Rider.sid", "Sigma_Seven.sid", "Tarzan.sid",
    "Thanatos.sid", "Trans-Atlantic_Balloon_Challenge.sid", "W_A_R.sid",
    "W_A_R_Preview.sid", "Wiz.sid", "Zoolook.sid",
}
_PULSE_RESEED_OTHER = {
    "After_8.sid", "Go_Go_Dash.sid", "Kings_of_the_Beach_intro.sid",
    "Lakers_vs_Celtics.sid", "Lion_Heart.sid", "Mr_Meaner.sid",
    "Off_the_Cuff.sid", "Pacific_Coast.sid", "Pygmies_Revenge.sid",
    "Radio_ACE.sid", "Rikky.sid", "Rock_Tells_the_Tale.sid",
    "Sun_Never_Shines.sid",
}
_PULSE_RESEED_UNMATCHED = {"IK_plus.sid"}

assert len(_PULSE_RESEED_LDA_BMI) == 28
assert len(_PULSE_RESEED_OTHER) == 13
assert len(_PULSE_RESEED_UNMATCHED) == 1
assert not (_PULSE_RESEED_LDA_BMI & _PULSE_RESEED_OTHER
            & _PULSE_RESEED_UNMATCHED)

_ALL_BOUNDS_ENGINE_FILES = (_PULSE_RESEED_LDA_BMI | _PULSE_RESEED_OTHER
                            | _PULSE_RESEED_UNMATCHED)


def _detect_all_bounds_engine_files():
    """name -> Detection, for every corpus file whose player has the bounds
    engine (`det.pulse_bounds >= 0`) and is named in presets.json."""
    import json

    from corpus import CORPUS
    from h2g.detect import detect
    from h2g.sidfile import load_sid

    presets_path = pathlib.Path(__file__).resolve().parents[2] / "presets.json"
    names = json.loads(presets_path.read_text(encoding="utf-8"))["songs"]
    out = {}
    for name in names:
        p = CORPUS / name
        if not p.exists():
            continue
        try:
            sid = load_sid(str(p))
            det = detect(sid, lambda *a, **k: None)
        except Exception:
            continue
        if det.pulse_bounds >= 0:
            out[name] = det
    return out


@corpus.needs_corpus
def test_pulse_reseed_gate_census_matches_pinned_population():
    dets = _detect_all_bounds_engine_files()
    assert set(dets) == _ALL_BOUNDS_ENGINE_FILES, (
        "the set of bounds-engine files presets.json names has changed -- "
        "re-derive the three groups below, do not just widen this set")
    for name, det in dets.items():
        if name in _PULSE_RESEED_LDA_BMI:
            want = "lda_bmi"
        elif name in _PULSE_RESEED_OTHER:
            want = "other"
        else:
            want = ""
        assert det.pulse_reseed_gate == want, (
            f"{name}: pulse_reseed_gate={det.pulse_reseed_gate!r}, "
            f"expected {want!r}")


@corpus.needs_corpus
def test_pulse_reseed_gate_lda_bmi_is_validated_on_saboteur_ii():
    # The lda_bmi rule (bit-7-clear note reseeds $D402/$D403 from the
    # record's own seed, bit-7 note free-runs) is validated against a
    # siddump trace: 100% of steps and 100% of attack onsets predicted,
    # including the 56 attacks that do NOT reseed -- WIRING.md's own
    # measurement, re-run at this HEAD by
    # C:/t/detect-the-reseed-gate-spell/pps_validate.py (a copy of
    # C:/t/pulse-phase-sim-for-the-boun/pps_validate.py retargeted to this
    # worktree).
    from corpus import CORPUS
    from h2g.detect import detect
    from h2g.sidfile import load_sid
    det = detect(load_sid(str(CORPUS / "Saboteur_II.sid")), lambda *a, **k: None)
    assert det.pulse_reseed_gate == "lda_bmi"


@corpus.needs_corpus
def test_pulse_reseed_gate_other_is_validated_on_after_8():
    # The 13-file "other" spelling is not a different reseed RULE, only a
    # different GATE for reaching the same unconditional store -- validated
    # the same way on After_8 (0.5.485+task: 26036/26036 steps, 713/713
    # attack onsets over a 180 s trace, via pps_validate.py above).
    from corpus import CORPUS
    from h2g.detect import detect
    from h2g.sidfile import load_sid
    det = detect(load_sid(str(CORPUS / "After_8.sid")), lambda *a, **k: None)
    assert det.pulse_reseed_gate == "other"


@corpus.needs_corpus
def test_pulse_reseed_gate_is_empty_for_ik_plus():
    # IK_plus writes $D402/$D403 some other way this walk's two spellings do
    # not match -- the point of the field: a consumer must not assume the
    # reseed rule holds here just because pulse_bounds >= 0.
    from corpus import CORPUS
    from h2g.detect import detect
    from h2g.sidfile import load_sid
    det = detect(load_sid(str(CORPUS / "IK_plus.sid")), lambda *a, **k: None)
    assert det.pulse_bounds >= 0
    assert det.pulse_reseed_gate == ""


# --- sabotage: each mutation below must make a named test above fail ---
#
# Mutation A: swap PULSE_RESEED_ABS's condition (BMI -> BPL, i.e. invert the
#   sense of the test) -- breaks test_pulse_reseed_gate_census_matches_
#   pinned_population (every "lda_bmi" file stops matching, since the corpus
#   files use BMI not BPL there) AND test_pulse_reseed_gate_lda_bmi_is_
#   validated_on_saboteur_ii.
# Mutation B: delete the PULSE_RESEED_UNCOND fallback (or make it require a
#   preceding BMI, collapsing it into PULSE_RESEED_ABS) -- breaks
#   test_pulse_reseed_gate_census_matches_pinned_population (the 13 "other"
#   files read "" instead) AND test_pulse_reseed_gate_other_is_validated_on_
#   after_8.
# Mutation C: return "lda_bmi" unconditionally whenever pulse_bounds >= 0
#   (skip the search entirely) -- breaks test_pulse_reseed_gate_census_
#   matches_pinned_population (the 13 "other" files and IK_plus all read
#   "lda_bmi") AND test_pulse_reseed_gate_is_empty_for_ik_plus.


# --- fixed_pitch_index: the bit-$40 handler's own note-index array, per file --
#
# Every corpus file whose player tests effect bit $40 (`det.effect_bit40`,
# 43 files under their presets.json engine) carries the handler shape
# `BIT effect / BVC / LDA counter,X / BEQ / DEC counter,X / LDA idx,Y`, and
# `detect._find_fixed_pitch_index` reads the `idx` operand out of it. This
# census pins, per file, how that operand relates to `det.wave_program` --
# the array `_fixed_attack_note` read until v0.5.486 -- so a signature edit
# that silently moves a file between the three groups fails a named test:
#
#   AGREE     both arrays exist and name the same offset (26 files; the
#             reading the old code was derived on, unchanged by the new one).
#             Powerplay Hockey joined this group when `find_wave_program`
#             was scoped to the selected engine (`_wave_program_fetch_site`):
#             file-wide it returned the OTHER player's array ($3C00, the
#             $3BA0 copy's) while the handler read the selected $4A00
#             table's own +8; both now name $4A08.
#   DISAGREE  both exist and differ (After 8: handler +12, wave_program +8)
#             -- the handler's byte is what the original sounds
#   REACH     no wave_program at all, and the handler operand is the only
#             reading (16 files); every one of them has records with $40 set
#
# Recorded at v0.5.486 against the corpus; every name is in presets.json.
_FIXED_PITCH_AGREE = {
    "ACE_II.sid", "Arcade_Classics.sid", "Auf_Wiedersehen_Monty.sid",
    "Bangkok_Knights.sid", "BMX_Kidz.sid", "I_Ball.sid", "IK_plus.sid",
    "Kings_of_the_Beach_intro.sid", "Mr_Meaner.sid", "Nemesis_the_Warlock.sid",
    "Nineteen.sid", "Off_the_Cuff.sid", "One_on_One_Jordan_vs_Bird.sid",
    "Pandora.sid", "Powerplay_Hockey_USA_vs_USSR.sid", "Pygmies_Revenge.sid",
    "Ricochet.sid", "Rikky.sid",
    "Rock_Tells_the_Tale.sid", "Saboteur_II.sid", "Shockway_Rider.sid",
    "Skate_or_Die_intro.sid", "Star_Paws.sid", "Thundercats.sid",
    "Trans-Atlantic_Balloon_Challenge.sid", "Wiz.sid",
}
_FIXED_PITCH_DISAGREE = {"After_8.sid"}
_FIXED_PITCH_REACH = {
    "Deep_Strike.sid", "Delta.sid", "Delta_Mix-E-Load_loader.sid",
    "Dragons_Lair_Part_II.sid", "Food_Feud.sid", "Go_Go_Dash.sid",
    "Knucklebusters.sid", "Lakers_vs_Celtics.sid", "Lightforce.sid",
    "Lion_Heart.sid", "Pacific_Coast.sid", "Radio_ACE.sid", "Sanxion.sid",
    "Sigma_Seven.sid", "Sun_Never_Shines.sid", "Tarzan.sid",
}

assert len(_FIXED_PITCH_AGREE) == 26
assert len(_FIXED_PITCH_DISAGREE) == 1
assert len(_FIXED_PITCH_REACH) == 16
assert not (_FIXED_PITCH_AGREE & _FIXED_PITCH_DISAGREE)
assert not (_FIXED_PITCH_AGREE & _FIXED_PITCH_REACH)
assert not (_FIXED_PITCH_DISAGREE & _FIXED_PITCH_REACH)

_ALL_BIT40_FILES = (_FIXED_PITCH_AGREE | _FIXED_PITCH_DISAGREE
                    | _FIXED_PITCH_REACH)


def _detect_all_bit40_files():
    """name -> (sid, Detection) for every presets.json file whose player
    tests effect bit $40, detected under the engine its preset selects."""
    import json

    from corpus import CORPUS
    from h2g.detect import detect
    from h2g.sidfile import load_sid

    presets_path = pathlib.Path(__file__).resolve().parents[2] / "presets.json"
    songs = json.loads(presets_path.read_text(encoding="utf-8"))["songs"]
    out = {}
    for name, entry in songs.items():
        p = CORPUS / name
        if not p.exists():
            continue
        try:
            sid = load_sid(str(p))
            det = detect(sid, lambda *a, **k: None,
                         engine=int(entry.get("engine") or 0))
        except Exception:
            continue
        if det.effect_bit40:
            out[name] = (sid, det)
    return out


@corpus.needs_corpus
def test_fixed_pitch_index_census_matches_pinned_population():
    dets = _detect_all_bit40_files()
    assert set(dets) == _ALL_BIT40_FILES, (
        "the set of bit-$40 files presets.json names has changed -- "
        "re-derive the three groups below, do not just widen this set")
    for name, (sid, det) in dets.items():
        assert det.fixed_pitch_index >= 0, (
            f"{name}: the handler operand was not read")
        if name in _FIXED_PITCH_AGREE:
            assert det.wave_program >= 0, name
            assert det.fixed_pitch_index == det.wave_program, (
                f"{name}: handler +0x{det.fixed_pitch_index:04X} != "
                f"wave_program +0x{det.wave_program:04X}")
        elif name in _FIXED_PITCH_DISAGREE:
            assert det.wave_program >= 0, name
            assert det.fixed_pitch_index != det.wave_program, name
        else:
            assert det.wave_program < 0, name
            recs = [i for i in range(det.instr_used)
                    if sid.data[det.instr_start + i * det.instr_stride + 7]
                    & 0x40]
            assert recs, f"{name}: no record sets $40, so nothing is reached"


# Mutation E: drop the engine scope in `_wave_program_fetch_site` (return
#   sites[0] unconditionally) -- breaks
#   test_fixed_pitch_index_census_matches_pinned_population on Powerplay
#   Hockey (wave_program reads the $3BA0 copy's $3C00 again, so it leaves
#   AGREE) AND tests/test_fixed_pitch_index.py's two Powerplay wave-program
#   pins. The other 28 files carrying the fetch are unmoved by the scope:
#   27 have one site and One_on_One's first of four is the anchored one.
# Mutation D: read the `DEC counter,X` operand (data[j + 6]) instead of the
#   `LDA idx,Y` one (data[j + 9]) in _find_fixed_pitch_index -- breaks
#   test_fixed_pitch_index_census_matches_pinned_population (every AGREE
#   file's offset stops equalling wave_program) AND tests/
#   test_fixed_pitch_index.py's Food Feud pin ($95EB -> 63 -> D#5).


# --- The classic vibrato's gate: a pinned population -----------------------
#
# detect._find_vibrato_gate reads the compare in front of the classic loop's
# store. A reading is only sound where the split itself resolved, a counter
# is only a counter where the player increments it, and an UNREAD operand is
# never a number. The census (2026-09-30) is pinned so a widened or narrowed
# shape names the files it moved rather than passing quietly.
_GATE_COUNTER = {
    "ACE_II.sid", "After_8.sid", "Arcade_Classics.sid",
    "Auf_Wiedersehen_Monty.sid", "BMX_Kidz.sid", "Bangkok_Knights.sid",
    "Food_Feud.sid", "IK_plus.sid", "I_Ball.sid",
    "Kings_of_the_Beach_intro.sid", "Mega_Apocalypse.sid", "Mr_Meaner.sid",
    "Nemesis_the_Warlock.sid", "Nineteen.sid", "Off_the_Cuff.sid",
    "One_on_One_Jordan_vs_Bird.sid", "Pandora.sid",
    "Powerplay_Hockey_USA_vs_USSR.sid", "Pygmies_Revenge.sid", "Ricochet.sid",
    "Rikky.sid", "Rock_Tells_the_Tale.sid", "Saboteur_II.sid",
    "Shockway_Rider.sid", "Skate_or_Die_intro.sid", "Star_Paws.sid",
    "Thundercats.sid", "Trans-Atlantic_Balloon_Challenge.sid", "Wiz.sid",
}
_GATE_DURATION = {
    "Bump_Set_Spike.sid", "Chain_Reaction.sid", "Deep_Strike.sid",
    "Delta.sid", "Delta_Mix-E-Load_loader.sid", "Dragons_Lair_Part_II.sid",
    "Flash_Gordon.sid", "Formula_1_Simulator.sid",
    "International_Karate.sid", "Kentilla.sid", "Knucklebusters.sid",
    "Las_Vegas_Video_Poker.sid", "Lightforce.sid", "Mozart.sid",
    "Proteus.sid", "Samantha_Fox_Strip_Poker.sid", "Sanxion.sid",
    "Spellbound.sid", "Tarzan.sid", "Thanatos.sid", "Thrust.sid",
    "W_A_R.sid", "W_A_R_Preview.sid", "Warhawk.sid", "Zoolook.sid",
}
# Since the per-instrument store was read (detect.VIBRATO_GATE_STORE_SHAPE),
# no corpus operand is UNREAD: all three were operands the player rewrites
# per instrument, as are Arcade_Classics', BMX_Kidz', Mega_Apocalypse's and
# Star_Paws' -- whose static bytes had read as a gate. Pinned by name, with
# the table each is stored from.
_GATE_UNREAD: dict = {}
_GATE_STORED = {
    "Arcade_Classics.sid": 0x3868, "BMX_Kidz.sid": 0xB456,
    "Mega_Apocalypse.sid": 0x54A8, "Ricochet.sid": 0x9A21,
    "Skate_or_Die_intro.sid": 0x4BE0, "Star_Paws.sid": 0xBA18,
    "Thundercats.sid": 0xF787,
}
_GATE_ABSENT = {"Sigma_Seven.sid"}


@corpus.needs_corpus
def test_classic_vibrato_gate_census_matches_pinned_population():
    from corpus import CORPUS
    from h2g.detect import detect
    from h2g.search import search_file
    from h2g.sidfile import load_sid

    got: dict = {"counter": set(), "duration": set(), "unread": set(),
                 "absent": set(), "stored": {}}
    for p in sorted(CORPUS.glob("*.sid")):
        sid = load_sid(str(p))
        try:
            det = detect(sid, lambda *a, **k: None)
        except Exception:
            continue
        vg = det.vibrato_gate
        if det.vibrato_offset is None:
            assert vg is None, f"{p.name}: a gate without the classic split"
            continue
        if vg is None:
            got["absent"].add(p.name)
            continue
        got[vg.form].add(p.name)
        if vg.table is not None:
            got["stored"][p.name] = vg.table
            assert vg.gate is None, f"{p.name}: a stored gate read as one value"
            assert vg.per_record, p.name
        elif vg.form == "unread":
            assert vg.gate is None, f"{p.name}: UNREAD operand read as {vg.gate}"
            assert vg.operand == _GATE_UNREAD.get(p.name), p.name
        else:
            assert vg.gate == vg.operand and vg.gate not in (0, 0xF0, 0xFE), p.name
        if vg.form == "counter":
            inc = ("F6 %02X" % vg.cell if vg.cell < 0x100 else
                   "FE %02X %02X" % (vg.cell & 0xFF, vg.cell >> 8))
            assert search_file(sid.data, inc) >= 1, f"{p.name}: never counts"
    assert got["counter"] == _GATE_COUNTER, got["counter"] ^ _GATE_COUNTER
    assert got["duration"] == _GATE_DURATION, got["duration"] ^ _GATE_DURATION
    assert got["unread"] == set(_GATE_UNREAD), got["unread"]
    assert got["absent"] == _GATE_ABSENT, got["absent"]
    assert got["stored"] == _GATE_STORED, got["stored"]


# --- the triangle sweep's start state, per file -------------------------------
#
# `goatwriter.triangle_start` reads what the triangle walk seeds itself with
# off the player: the per-voice direction and delay counter cells (operands
# of PULSE_TRI_SHAPE at detect._TRI_DIR / _TRI_COUNTER), the instrument
# each voice sweeps before a row names one (the cell `LDA instr,X / ASL /
# ASL / ASL / TAY / STY idx` fills the sweep's own `LDY idx` from), and the
# speed gate's counter, which `prefetch` turns into the ticks swept before
# the first fetch. A start that cannot be read declines the walk, so a
# signature or operand edit that silently loses or moves one of these
# fails here by name rather than as a quietly different plan. Read with
# lead 0 (`compact_instruments`, what presets.json's `always` sets);
# (direction, counter) per voice, +1 up / -1 down.
_TRIANGLE_START = {
    "5_Title_Tunes.sid": (((1, 0), (1, 0), (-1, 1)), (1, 2, 3), 3),
    "Action_Biker.sid": (((1, 0), (1, 0), (1, 0)), (8, 9, 3), 1),
    "Battle_of_Britain.sid": (((-1, 0), (1, 0), (1, 1)), (10, 11, 3), 0),
    "Chimera.sid": (((1, 0), (1, 0), (1, 0)), (5, 15, 3), 2),
    "Commando.sid": (((1, 0), (1, 0), (1, 0)), (1, 10, 3), 0),
    "Confuzion.sid": (((1, 0), (1, 0), (1, 0)), (1, 4, 3), 2),
    "Crazy_Comets.sid": (((1, 0), (1, 0), (-1, 0)), (2, 20, 17), 1),
    "Devils_Galop.sid": (((1, 0), (1, 0), (1, 0)), (1, 1, 3), 0),
    "Game_Killer.sid": (((-1, 0), (1, 0), (1, 0)), (7, 10, 6), 1),
    "Geoff_Capes_Strongman_Challenge.sid": (((1, 0), (1, 16), (-1, 0)), (17, 16, 4), 0),
    "Gerry_the_Germ.sid": (((-1, 0), (1, 0), (1, 0)), (18, 5, 3), 1),
    "Gremlins.sid": (((-1, 1), (1, 1), (-1, 1)), (22, 22, 4), 2),
    "Human_Race.sid": (((1, 0), (1, 0), (1, 0)), (1, 1, 3), 0),
    "Hunter_Patrol.sid": (((1, 0), (1, 0), (1, 0)), (5, 5, 11), 1),
    "Last_V8.sid": (((-1, 0), (1, 18), (1, 1)), (7, 2, 4), 0),
    "Last_V8_C128_version.sid": (((-1, 0), (-1, 25), (1, 0)), (5, 5, 9), 1),
    "Master_of_Magic.sid": (((-1, 1), (1, 0), (-1, 0)), (8, 15, 4), 1),
    "Monty_on_the_Run.sid": (((-1, 0), (1, 1), (1, 29)), (17, 3, 17), 0),
    "Ninja.sid": (((1, 0), (1, 0), (1, 0)), (1, 10, 12), 1),
    "One_Man_and_his_Droid.sid": (((1, 0), (1, 0), (1, 0)), (1, 1, 3), 0),
    "Phantoms_of_the_Asteroid.sid": (((1, 0), (1, 0), (1, 0)), (1, 1, 3), 0),
    "Rasputin.sid": (((1, 0), (1, 0), (1, 0)), (1, 7, 3), 0),
    "Thing_on_a_Spring.sid": (((1, 1), (1, 1), (-1, 0)), (15, 6, 7), 1),
    "Zoids.sid": (((1, 0), (1, 0), (1, 0)), (13, 4, 3), 1),
}


@corpus.needs_corpus
def test_triangle_start_census_matches_pinned_population():
    """Every presets.json file with the absolute-dialect triangle (24, the
    population test_pulse_phase.py counts) yields a start state, and it is
    the one pinned above."""
    import json

    from corpus import CORPUS
    from h2g.detect import detect
    from h2g.goatwriter import triangle_start
    from h2g.sidfile import load_sid

    presets_path = pathlib.Path(__file__).resolve().parents[2] / "presets.json"
    names = json.loads(presets_path.read_text(encoding="utf-8"))["songs"]
    got = {}
    for name in names:
        p = CORPUS / name
        if not p.exists():
            continue
        try:
            sid = load_sid(str(p))
            det = detect(sid, lambda *a, **k: None)
        except Exception:
            continue
        if det.pulse_tri_hi < 0 or det.pulse_tri_per_voice:
            continue
        st = triangle_start(sid, det, lead=0)
        got[name] = None if st is None else (st.cells, st.instruments,
                                             st.counter)
    assert got == _TRIANGLE_START
