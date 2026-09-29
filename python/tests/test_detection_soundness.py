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


# --- the triangle sweep's per-VOICE cells (task triangle-direction-per-voice-
# from-the-image). `_find_pulse_tri_cells` reads the direction and counter
# arrays off the sweep's own `DEC cnt,X` / `STA cnt,X` / `LDA dir,X` /
# `INC dir,X` and requires each pair to agree. Pinned per file, with the
# image's opening bytes, because the walk seeds every voice from them: a
# signature edit that moves a cell moves every triangle plan. The three
# addresses read off the disassembly independently (C:/t/triangle-sim-model/
# MECHANISM.txt) are the second reader.
_TRI_CELLS = {   # name: (dir address, its 3 bytes, counter address, its 3 bytes)
    "5_Title_Tunes.sid": (0x1052, "000001", 0x104F, "000001"),
    "Action_Biker.sid": (0xC3E4, "000000", 0xC3E1, "000000"),
    "Battle_of_Britain.sid": (0x840E, "010000", 0x840B, "000001"),
    "Chimera.sid": (0xC64F, "000000", 0xC64C, "000000"),
    "Commando.sid": (0x5510, "000000", 0x550D, "000000"),
    "Confuzion.sid": (0x0BE5, "000000", 0x0BE2, "000000"),
    "Crazy_Comets.sid": (0x54F7, "000001", 0x54F4, "000000"),
    "Devils_Galop.sid": (0x177C, "000000", 0x1779, "000000"),
    "Game_Killer.sid": (0x0C78, "010000", 0x0C75, "000000"),
    "Geoff_Capes_Strongman_Challenge.sid": (0x1510, "000001", 0x150D, "001000"),
    "Gerry_the_Germ.sid": (0xE510, "010000", 0xE50D, "000000"),
    "Gremlins.sid": (0x16E8, "010001", 0x16E5, "010101"),
    "Human_Race.sid": (0x0DCB, "000000", 0x0DC8, "000000"),
    "Hunter_Patrol.sid": (0xA415, "000000", 0xA412, "000000"),
    "Last_V8.sid": (0x8523, "010000", 0x8520, "001201"),
    "Last_V8_C128_version.sid": (0x8523, "010100", 0x8520, "001900"),
    "Master_of_Magic.sid": (0xC417, "010001", 0xC414, "010000"),
    "Monty_on_the_Run.sid": (0x84E8, "010000", 0x84E5, "00011d"),
    "Ninja.sid": (0xCC43, "000000", 0xCC40, "000000"),
    "One_Man_and_his_Droid.sid": (0x150A, "000000", 0x1507, "000000"),
    "Phantoms_of_the_Asteroid.sid": (0xE448, "000000", 0xE445, "000000"),
    "Rasputin.sid": (0xC530, "000000", 0xC52D, "000000"),
    "Thing_on_a_Spring.sid": (0xC491, "000001", 0xC48E, "010100"),
    "Zoids.sid": (0x146B, "000000", 0x1468, "000000"),
}
assert len(_TRI_CELLS) == 24


@corpus.needs_corpus
def test_the_triangle_voice_cells_census():
    from corpus import CORPUS
    from h2g.detect import detect
    from h2g.sidfile import load_sid
    assert (_TRI_CELLS["One_Man_and_his_Droid.sid"][::2],
            _TRI_CELLS["Rasputin.sid"][::2],
            _TRI_CELLS["Game_Killer.sid"][::2]) == (
        (0x150A, 0x1507), (0xC530, 0xC52D), (0x0C78, 0x0C75))
    found = {}
    for p in sorted(CORPUS.glob("*.sid")):
        try:
            sid = load_sid(str(p))
            det = detect(sid, lambda *a, **k: None)
        except Exception:
            continue
        # The zero-page dialect (Samantha Fox, Spellbound) reseeds both
        # cells at every note fetch, so neither is read there.
        if det.pulse_tri_hi < 0 or det.pulse_tri_reseeds:
            assert (det.pulse_tri_dir, det.pulse_tri_cnt) == (-1, -1), p.name
            continue
        d = sid.data
        addr = lambda off: sid.to_address(off)
        found[p.name] = (addr(det.pulse_tri_dir),
                         bytes(d[det.pulse_tri_dir:det.pulse_tri_dir + 3]).hex(),
                         addr(det.pulse_tri_cnt),
                         bytes(d[det.pulse_tri_cnt:det.pulse_tri_cnt + 3]).hex())
    assert found == _TRI_CELLS, {k: (found.get(k), _TRI_CELLS.get(k))
                                 for k in set(found) | set(_TRI_CELLS)
                                 if found.get(k) != _TRI_CELLS.get(k)}


def test_the_triangle_cells_need_both_operand_pairs_to_agree():
    """A STA or INC naming a different cell from its DEC or LDA reads
    nothing: the shape matched, the operands say it is not this sweep."""
    from h2g.detect import (PULSE_TRI_SHAPE, _TRI_CNT_DEC, _TRI_CNT_STA,
                            _TRI_DIR_INC, _TRI_DIR_LDA, _find_pulse_tri_cells)
    from h2g.sidfile import HLEN, SidFile
    shape = bytes(0 if t == "??" else int(t, 16) for t in PULSE_TRI_SHAPE.split())
    body = bytearray(shape) + bytes(16)
    for k, a in ((_TRI_CNT_DEC, 0x1100), (_TRI_CNT_STA, 0x1100),
                 (_TRI_DIR_LDA, 0x1103), (_TRI_DIR_INC, 0x1103)):
        body[k], body[k + 1] = a & 0xFF, a >> 8
    load = 0x1000

    def cells(b: bytes):
        # loaded at $1000 behind $100 of padding: the shape sits at $1100,
        # so its own first bytes are the cells it names
        data = bytes(HLEN - 1) + bytes(0x100) + b
        sid = SidFile.__new__(SidFile)
        sid.data, sid.load_addr, sid.relocation = data, load, None
        return _find_pulse_tri_cells(sid)
    d, c = cells(bytes(body))
    assert (d, c) == (HLEN - 1 + 0x103, HLEN - 1 + 0x100), (d, c)
    for k in (_TRI_CNT_STA, _TRI_DIR_INC):
        bad = bytearray(body)
        bad[k] ^= 0x01
        assert cells(bytes(bad)) == (-1, -1), k


# --- the triangle sweep's per-voice CURRENT-RECORD cell (task triangle-
# preroll-on-the-image-record). `_find_pulse_tri_record_cell` chains the
# triangle entry's `LDY idx` to the voice loop's `LDA cur,X / ASL x3 / TAY /
# STY idx`; the image's three bytes are the record each voice sweeps on the
# ticks before its first fetch. Pinned per file with those bytes, because the
# walk's preroll lands on them. The three addresses read off the disassembly
# independently (C:/t/triangle-sim-model/dis_*_full.txt: One_Man $1199 LDA
# $14F8,X, Rasputin $C1C7 LDA $C51E,X, Game_Killer $099D LDA $0C66,X) are
# the second reader; the py65 write watch is
# C:/t/triangle-preroll-image/probe_reccells.txt.
_TRI_RECORD_CELL = {   # name: (current-record array address, its 3 bytes)
    "5_Title_Tunes.sid": (0x1040, "000102"),
    "Action_Biker.sid": (0xC3D2, "070802"),
    "Battle_of_Britain.sid": (0x83FC, "090a02"),
    "Chimera.sid": (0xC63D, "040e02"),
    "Commando.sid": (0x54FE, "000902"),
    "Confuzion.sid": (0x0BD3, "000302"),
    "Crazy_Comets.sid": (0x54E5, "011310"),
    "Devils_Galop.sid": (0x176A, "000002"),
    "Game_Killer.sid": (0x0C66, "060905"),
    "Geoff_Capes_Strongman_Challenge.sid": (0x14FE, "100f03"),
    "Gerry_the_Germ.sid": (0xE4FE, "110402"),
    "Gremlins.sid": (0x16D6, "151503"),
    "Human_Race.sid": (0x0DB9, "000002"),
    "Hunter_Patrol.sid": (0xA403, "04040a"),
    "Last_V8.sid": (0x8511, "060103"),
    "Last_V8_C128_version.sid": (0x8511, "040408"),
    "Master_of_Magic.sid": (0xC405, "070e03"),
    "Monty_on_the_Run.sid": (0x84D6, "100210"),
    "Ninja.sid": (0xCC31, "00090b"),
    "One_Man_and_his_Droid.sid": (0x14F8, "000002"),
    "Phantoms_of_the_Asteroid.sid": (0xE436, "000002"),
    "Rasputin.sid": (0xC51E, "000602"),
    "Thing_on_a_Spring.sid": (0xC47F, "0e0506"),
    "Zoids.sid": (0x1459, "0c0302"),
}
assert len(_TRI_RECORD_CELL) == 24 and set(_TRI_RECORD_CELL) == set(_TRI_CELLS)


@corpus.needs_corpus
def test_the_triangle_record_cell_census():
    from corpus import CORPUS
    from h2g.detect import detect
    from h2g.sidfile import load_sid
    assert (_TRI_RECORD_CELL["One_Man_and_his_Droid.sid"][0],
            _TRI_RECORD_CELL["Rasputin.sid"][0],
            _TRI_RECORD_CELL["Game_Killer.sid"][0]) == (0x14F8, 0xC51E, 0x0C66)
    found = {}
    for p in sorted(CORPUS.glob("*.sid")):
        try:
            sid = load_sid(str(p))
            det = detect(sid, lambda *a, **k: None)
        except Exception:
            continue
        if det.pulse_tri_hi < 0 or det.pulse_tri_reseeds:
            assert det.pulse_tri_rec == -1, p.name
            continue
        d = sid.data
        found[p.name] = (sid.to_address(det.pulse_tri_rec),
                         bytes(d[det.pulse_tri_rec:det.pulse_tri_rec + 3]).hex())
    assert found == _TRI_RECORD_CELL, {
        k: (found.get(k), _TRI_RECORD_CELL.get(k))
        for k in set(found) | set(_TRI_RECORD_CELL)
        if found.get(k) != _TRI_RECORD_CELL.get(k)}


def test_the_triangle_record_cell_is_the_select_the_entry_names():
    """The cell is read only through the entry's own `LDY idx`: a select
    storing to another scalar, a select with two shifts, a stride other than
    8, a second select naming a different array, or no `LDY abs` at the
    entry, each reads nothing."""
    from h2g.detect import (PULSE_TRI_SHAPE, _TRI_ENTRY, Detection,
                            _find_pulse_tri_record_cell)
    from h2g.sidfile import HLEN, SidFile
    shape = bytes(0 if t == "??" else int(t, 16) for t in PULSE_TRI_SHAPE.split())
    # the select at $10E0: LDA $1000,X / ASL x3 / TAY / STY $10F0; the
    # entry at $1100: LDA $10F1 / BEQ / LDY $10F0, then the shape
    select = bytes.fromhex("BD0010" "0A0A0A" "A8" "8CF010")
    entry = bytes.fromhex("ADF110" "F000" "ACF010")
    assert len(entry) == _TRI_ENTRY

    def cell(sel: bytes, ent: bytes = entry, stride: int = 8):
        body = bytearray(0x100)
        body[0xE0:0xE0 + len(sel)] = sel
        data = bytes(HLEN - 1) + bytes(body) + ent + shape + bytes(16)
        sid = SidFile.__new__(SidFile)
        sid.data, sid.load_addr, sid.relocation = data, 0x1000, None
        det = Detection()
        det.instr_stride = stride
        return _find_pulse_tri_record_cell(sid, det)
    # `cur` = $1000, the load address: file offset HLEN - 1
    assert cell(select) == HLEN - 1, cell(select)
    assert cell(select, stride=4) == -1
    assert cell(bytes.fromhex("BD0010" "0A0A0A" "A8" "8CF110")) == -1
    assert cell(bytes.fromhex("BD0010" "0A0A" "A8" "8CF010")) == -1
    assert cell(select + bytes.fromhex("BD0310" "0A0A0A" "A8" "8CF010")) == -1
    assert cell(select + select) == HLEN - 1
    assert cell(select, ent=bytes.fromhex("ADF110" "F000" "EAEAEA")) == -1


# --- the note-end cut with a counter test inside it --------------------------
#
# Commodore 64 Music Examples zeroes AD/SR at every gate-off, but spells it
# `AND #$FE / STA $D404,Y / LDA cnt,X / BNE / LDA #0 / STA $D405,Y /
# STA $D406,Y` ($1229-$123B): the LDA/BNE between the gate-clear and the zero
# puts it out of reach of ENVELOPE_CUT_SHAPES, so `cut_release` (on in the
# always block) was inert for it. Reading it as a cut moved its tail column
# 0.2308 -> 1.0 at the traced pair (orig 1 / ours 0) and the Hubbard_Rob
# byte-hash moved exactly that file (v0.5.497, C:/t/envelope-cut-c64me).

_GUARDED_CUT = bytes.fromhex("29FE9904D4BD1214D008A9009905D49906D4")


class _Data:
    def __init__(self, data):
        self.data = data


def test_the_counter_guarded_cut_is_read_as_a_cut():
    from h2g.detect import (ENVELOPE_CUT_GUARDED_SHAPES, ENVELOPE_CUT_SHAPES,
                            find_envelope_cut)
    from h2g.search import search_file
    blob = b"\x00" + _GUARDED_CUT
    assert all(search_file(blob, s) < 1 for s in ENVELOPE_CUT_SHAPES), (
        "the primary shapes must not already see it -- or this is not a "
        "fallback")
    assert any(search_file(blob, s) >= 1 for s in ENVELOPE_CUT_GUARDED_SHAPES)
    assert find_envelope_cut(_Data(blob))


def test_the_counter_guarded_cut_still_needs_the_gate_clear():
    """Without `AND #$FE / STA $D404,Y` in front the zero is an init
    routine clearing the chip, which the primary shape also refuses."""
    from h2g.detect import find_envelope_cut
    body = bytearray(_GUARDED_CUT)
    body[1] = 0xFF                               # AND #$FF: gate not cleared
    assert not find_envelope_cut(_Data(b"\x00" + bytes(body)))
    body = bytearray(_GUARDED_CUT)
    body[8] = 0xF0                               # BEQ: a different test
    assert not find_envelope_cut(_Data(b"\x00" + bytes(body)))


@corpus.needs_corpus
def test_the_counter_guarded_cut_is_one_file_and_a_fallback():
    from corpus import CORPUS
    from h2g.detect import (ENVELOPE_CUT_GUARDED_SHAPES, ENVELOPE_CUT_SHAPES,
                            detect)
    from h2g.search import search_file
    from h2g.sidfile import load_sid
    hits, both = set(), set()
    for p in sorted(CORPUS.glob("*.sid")):
        data = load_sid(str(p)).data
        if any(search_file(data, s) >= 1 for s in ENVELOPE_CUT_GUARDED_SHAPES):
            hits.add(p.name)
            if any(search_file(data, s) >= 1 for s in ENVELOPE_CUT_SHAPES):
                both.add(p.name)
    assert hits == {"Commodore_64_Music_Examples.sid"}, sorted(hits)
    assert not both, sorted(both)
    det = detect(load_sid(str(CORPUS / "Commodore_64_Music_Examples.sid")),
                 lambda *a, **k: None)
    assert det.envelope_cut


# --- the gate hold's LSR/CMP spelling ------------------------------------
#
# Commodore 64 Music Examples tests its note-end counter with `LDA cnt,X /
# LSR A / CMP cnt,X / BNE` ($1220), which GATE_HOLD_SHAPE cannot see, so its
# zero-wait notes re-attacked. Reading the fallback moved voice 2's ties at
# the traced pair (orig 1 / ours 0) 0 -> 72 of 72 and melody 96 -> 100%
# (C:/t/gate-hold-lsr-cmp, v0.5.497 working tree).

@corpus.needs_corpus
def test_the_lsr_cmp_gate_hold_is_one_file_and_a_fallback():
    from corpus import CORPUS
    from h2g.detect import GATE_HOLD_LSR_SHAPE, GATE_HOLD_SHAPE, detect
    from h2g.search import search_file
    from h2g.sidfile import load_sid
    hits, both = set(), set()
    for p in sorted(CORPUS.glob("*.sid")):
        data = load_sid(str(p)).data
        if search_file(data, GATE_HOLD_LSR_SHAPE) >= 1:
            hits.add(p.name)
            if search_file(data, GATE_HOLD_SHAPE) >= 1:
                both.add(p.name)
    assert hits == {"Commodore_64_Music_Examples.sid"}, sorted(hits)
    assert not both, sorted(both)
    det = detect(load_sid(str(CORPUS / "Commodore_64_Music_Examples.sid")),
                 lambda *a, **k: None)
    assert det.gate_hold


@corpus.needs_corpus
def test_the_lsr_cmp_gate_hold_is_read_only_in_the_converted_player():
    """Five players in one image: the fallback reads the range of the one
    the signature chains matched, and nothing without a span to anchor it."""
    from corpus import CORPUS
    from h2g.detect import find_gate_hold
    from h2g.sidfile import load_sid
    sid = load_sid(str(CORPUS / "Commodore_64_Music_Examples.sid"))
    assert find_gate_hold(sid, [(sid.to_offset(0x11DE), 12)]) is True
    assert find_gate_hold(sid) is False                  # no span, no read
    assert find_gate_hold(sid, [(sid.to_offset(0x0903), 1)]) is False
    assert find_gate_hold(sid, [(sid.to_offset(0x1D8B), 1)]) is False
