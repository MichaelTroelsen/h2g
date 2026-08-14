"""The instrument effect byte's *second* format, and why it is read but unused.

test_effects.py covers Warhawk's reading of +7: four flags in the low nibble
and an arpeggio interval in the high one, taken with `LSR x4`. That is not the
only format the byte has. 41 corpus files instead test $10/$20/$40/$80 as
single bits -- the last of them with `BIT effect / BVC` and `LDA effect / BPL`,
which a probe looking only for `AND #$xx` never sees -- and **no file does
both**. The two readings partition the corpus cleanly, which is what makes
them two formats rather than one format read two ways.

In that second family bit $04 is not an arpeggio at all. It holds an attack
waveform for a per-instrument number of frames and then drops to the record's
own +2 (IK+ $E38B). `detect._find_two_stage` reads it, `goatwriter` does not
use it: encoding it into the five-entry wavetable was measured on the corpus
and lost wave agreement under both encodings tried. See
H2G-CONVERSION-METHOD.md section 7 for the numbers. These tests pin the
reading, and pin the fact that it changes no output.
"""
import pathlib
from corpus import CORPUS as _CORPUS, needs_corpus  # noqa: E402
import sys

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[1]))

from h2g.convert import _detect_tables
from h2g.detect import (WAVEFORMS, _effect_byte_address, _find_two_stage,
                        detect)
from h2g.sidfile import HLEN, load_sid

CORPUS = _CORPUS
COMMANDO = pathlib.Path(__file__).resolve().parents[2] / "Commando.sid"

ARP = 0x04
POINTER = 0x08


def _det(name):
    sid = load_sid(str(CORPUS / f"{name}.sid"))
    return _detect_tables(sid, lambda *a, **k: None)


def test_ik_plus_has_the_two_stage_block():
    if not CORPUS.is_dir():
        return
    sid, det = _det("IK_plus")
    assert det.effect_two_stage
    assert det.two_stage_wave > 0
    # The duration always sits two bytes after the attack waveform -- the
    # probe requires the note-start push chain to say so independently.
    assert det.two_stage_frames == det.two_stage_wave + 2


def test_warhawk_does_not():
    if not CORPUS.is_dir():
        return
    # Warhawk is the other format: its bit $04 really is an arpeggio, and its
    # high nibble really is an interval. The two must never both fire.
    sid, det = _det("Warhawk")
    assert det.effect_arp is True
    assert det.effect_two_stage is False


def test_the_two_formats_never_coexist():
    if not CORPUS.is_dir():
        return
    for path in sorted(CORPUS.glob("*.sid")):
        sid = load_sid(str(path))
        sid, det = _detect_tables(sid, lambda *a, **k: None)
        assert not (det.effect_arp and det.effect_two_stage), path.name


def test_the_expired_branch_reads_the_record_s_own_waveform():
    """The proof the block is what it looks like.

    The two-stage block's second load is the instrument's +2 -- the very byte
    goatwriter already emits as the waveform. If that were not so, the block
    would be doing something else and the attack reading would be a guess.
    """
    if not CORPUS.is_dir():
        return
    from h2g.detect import TWO_STAGE_SHAPE, TWO_STAGE_SHAPE_ZP
    from h2g.search import search_file

    checked = 0
    for path in sorted(CORPUS.glob("*.sid")):
        sid = load_sid(str(path))
        sid, det = _detect_tables(sid, lambda *a, **k: None)
        if not det.effect_two_stage:
            continue
        addr, zp = _effect_byte_address(sid, det)
        load = (f"A5 {addr:02X}" if zp
                else f"AD {addr & 0xFF:02X} {addr >> 8:02X}")
        # The zero-page spelling is two bytes shorter by the time the second
        # `LDA table,Y` is reached, which is the whole difference between the
        # two offsets below.
        i = search_file(sid.data, TWO_STAGE_SHAPE.format(load=load))
        expired_at = 19
        if i <= -1:
            i = search_file(sid.data, TWO_STAGE_SHAPE_ZP.format(load=load))
            expired_at = 17
        assert i > -1, path.name
        p = i + len(load.split())
        expired = sid.data[p + expired_at] | sid.data[p + expired_at + 1] << 8
        instr_cpu = det.instr_start - (HLEN - 1) + sid.load_addr
        assert expired == instr_cpu + 2, path.name
        checked += 1
    assert checked >= 30, checked


def test_the_zero_page_spelling_is_one_file_and_reads_the_same_block():
    """v0.5.253. Mega Apocalypse keeps the block's three per-voice cells in
    zero page, so `BD ?? ??` / `DE ?? ??` / `9D ?? ??` are `B5 ??` / `D6 ??` /
    `95 ??` and `TWO_STAGE_SHAPE` misses it -- the file had the routine, the
    array and the push chain, and read as having none of them.

    Pinned as a *count* as well as a match: a second spelling is a claim about
    which files it reaches, and the check that catches a pattern loosened too
    far is running it over the corpus and requiring the difference to be
    exactly the file it was written for.
    """
    if not CORPUS.is_dir():
        return
    from h2g.detect import TWO_STAGE_SHAPE, TWO_STAGE_SHAPE_ZP
    from h2g.search import search_file

    matched = []
    for path in sorted(CORPUS.glob("*.sid")):
        sid = load_sid(str(path))
        sid, det = _detect_tables(sid, lambda *a, **k: None)
        found = _effect_byte_address(sid, det)
        if not found or det.instr_start < 0:
            continue
        addr, zp = found
        load = (f"A5 {addr:02X}" if zp
                else f"AD {addr & 0xFF:02X} {addr >> 8:02X}")
        if search_file(sid.data, TWO_STAGE_SHAPE_ZP.format(load=load)) > -1:
            matched.append(path.name)
            # ...and it is not a file the absolute shape already had.
            assert search_file(
                sid.data, TWO_STAGE_SHAPE.format(load=load)) <= -1, path.name
    assert matched == ["Mega_Apocalypse.sid"], matched

    sid = load_sid(str(CORPUS / "Mega_Apocalypse.sid"))
    sid, det = _detect_tables(sid, lambda *a, **k: None)
    assert det.effect_two_stage is True
    # The duration table is the push chain's, not the block's, exactly as in
    # the absolute dialect -- attack $54A4, duration $54A6.
    assert det.two_stage_frames == det.two_stage_wave + 2


def test_it_is_off_by_default_and_kept_out_of_always():
    """This test used to assert `"two_stage" not in goatwriter.py` -- the
    reading landed, the emission deliberately not, because encoding it cost 82
    points of wave agreement across 18 files.

    v0.5.179 emits it behind `--two-stage`, and the *default* is unchanged: the
    measurement was re-taken under v0.5.175's aligned harness (a 1-4 frame
    transient being exactly what a 3-8 frame misalignment destroys) and came
    back the same, -0.6pp mean and Tarzan -14. What changed is that the cost is
    now known to buy something no agreement column can express -- the files in
    this dialect have *no noise at all* without it -- so it is selectable per
    song instead of unreachable.
    """
    from h2g.convert import convert
    import presets
    plain = convert(str(COMMANDO), log=lambda m: None)
    assert len(plain) == 15193, "the default output must not move"
    assert "two_stage" in presets.EXCLUDED_FROM_ALWAYS
    assert "two_stage" in presets.FIDELITY_TOGGLES


def test_the_emission_is_the_attack_then_a_delay_then_the_records_own():
    """IK+ $E38B: the attack waveform for `frames` frames, then instrument +2.

    The delay holds for `value + 1` calls and the attack's own entry is one, so
    four frames is `attack`, delay 2, own -- the arithmetic `_wave_hold_byte`
    sets out, applied to a per-instrument count instead of the call rate.

    Ahead of all that sits the record's own `+2`, gate on: the player writes it
    on the note's first frame and reaches the attack block only from the second
    (v0.5.217, `_first_frame_entry`).
    """
    from h2g.goatwriter import _two_stage_entries
    left, right = _two_stage_entries(0x41, 0x81, 4)
    assert left == [0x41, 0x81, 0x02, 0x41, 0xFF]
    assert right == [0x00, 0x00, 0x80, 0x00, 0x00]
    # one frame needs no delay at all
    assert _two_stage_entries(0x41, 0x81, 1)[0] == [0x41, 0x81, 0x41, 0xFF]


def test_the_first_frame_is_the_records_own_waveform():
    """Measured, not argued. Trans-Atlantic's GT 5 (`+2 $41`, a one-frame `$81`
    attack) profiles over its 24 onsets as

        ORIGINAL  pulse noise pulse pulse ...
        OURS      noise pulse pulse pulse ...      (before v0.5.217)

    -- the original shifted one frame left, its frame 0 being exactly `+2`'s
    class. Thundercats' four records on ADSR $0987 say the same over 148 onsets
    each. One *frame* is `multiplier` calls, so a multispeed file's lead covers
    that many: at -S3 a one-call lead still leaves the attack inside frame 0,
    and Thundercats -- packed at -S3 -- is where that was measured.
    """
    from h2g.goatwriter import _two_stage_entries
    # -S3: the record's waveform, then a delay covering the frame's other two
    # calls, then the attack and its own delay.
    assert _two_stage_entries(0x41, 0x81, 1, 3, budget=12)[0] == [
        0x41, 0x01, 0x81, 0x01, 0x41, 0xFF]
    # A record with no waveform of its own has nothing to put there, and the
    # player's silent first frame is not an onset in the trace either.
    assert _two_stage_entries(0x00, 0x11, 5)[0][0] == 0x11
    # ...and the entries are dropped whole rather than the block truncated
    # where the table has no room: the shape degrades to what it always was.
    assert _two_stage_entries(0x41, 0x81, 4, budget=4)[0] == [
        0x81, 0x02, 0x41, 0xFF]


def test_a_record_with_no_waveform_of_its_own_releases_the_attack():
    """Trans-Atlantic's GT 4 has `+2` of $00 -- the player writes "no waveform
    selected" and the sound stops, which a Goattracker wavetable cannot say
    ($00-$0F are delays). The nearest it has is the attack waveform released,
    and without any of it that instrument was silent for all 70 of its notes.
    """
    from h2g.goatwriter import _two_stage_entries
    left, _ = _two_stage_entries(0x00, 0x11, 5)
    assert left == [0x11, 0x03, 0x10, 0xFF]


def test_nothing_is_written_where_the_record_names_no_attack():
    from h2g.goatwriter import _two_stage_entries
    assert _two_stage_entries(0x41, 0x00, 4) is None
    assert _two_stage_entries(0x41, 0x81, 0) is None


def test_a_file_without_the_push_chain_is_skipped():
    """The duration must be corroborated, not assumed.

    _find_two_stage resolves the duration twice -- once as attack+2, once from
    the note-start push chain -- and requires them to agree. A player matching
    the block but keeping its duration elsewhere returns nothing rather than a
    made-up offset.
    """
    if not CORPUS.is_dir():
        return
    sid = load_sid(str(CORPUS / "Commando.sid"))
    det = detect(sid, log=lambda m: None)
    found, wave, frames = _find_two_stage(sid, det)
    assert (found, wave, frames) == (False, -1, -1)


def test_every_detected_file_resolves_inside_the_data():
    if not CORPUS.is_dir():
        return
    n = 0
    for path in sorted(CORPUS.glob("*.sid")):
        sid = load_sid(str(path))
        sid, det = _detect_tables(sid, lambda *a, **k: None)
        if not det.effect_two_stage:
            continue
        n += 1
        span = max(det.instr_used, 0) * det.instr_stride
        assert 0 <= det.two_stage_wave
        assert det.two_stage_frames + span <= len(sid.data)
    # 44 files at the time of writing; assert the family, not the digit.
    assert n >= 30, n


def test_ik_plus_percussion_instrument_attacks_on_noise():
    """The concrete case this was opened for.

    IK+ record 8 is one of the two percussion instruments whose voice the
    fidelity harness scores as absent. Its waveform +2 is $01 -- gate on, no
    waveform bits, i.e. silence -- and its attack waveform is $81, noise. That
    is the burst siddump names and h2g never plays.
    """
    if not CORPUS.is_dir():
        return
    sid, det = _det("IK_plus")
    base = det.instr_start + 8 * det.instr_stride
    assert sid.data[base + 7] & ARP
    assert not sid.data[base + 7] & POINTER
    assert sid.data[base + 2] == 0x01
    attack = sid.data[det.two_stage_wave + 8 * det.instr_stride]
    assert attack == 0x81
    assert attack in WAVEFORMS


# --- v0.5.236: the same block in the 16-byte-record dialect -----------------
#
# `_effect_byte_address` probed `instr_stride == 8` and so switched off every
# effect-byte routine for the 9 corpus files whose records are 16 bytes. The
# address it computes is record 0's +7 and the search is for the player's own
# `LDA base,Y`; neither depends on the stride, so the guard excluded a dialect
# rather than an error -- and behind it sat the onset census's largest group,
# `$04` x11 across five of those nine.

STRIDE16 = ["After_8.sid", "Kings_of_the_Beach_intro.sid", "Mr_Meaner.sid",
            "Off_the_Cuff.sid", "One_on_One_Jordan_vs_Bird.sid",
            "Powerplay_Hockey_USA_vs_USSR.sid", "Pygmies_Revenge.sid",
            "Rikky.sid", "Rock_Tells_the_Tale.sid"]


@needs_corpus
def test_the_sixteen_byte_dialect_reads_its_effect_byte():
    for name in STRIDE16:
        sid = load_sid(str(CORPUS / name))
        _, det = _detect_tables(sid, lambda *a, **k: None)
        assert det.instr_stride == 16, name
        assert _effect_byte_address(sid, det) is not None, name


@needs_corpus
def test_the_block_is_the_same_shape_and_its_bytes_are_in_the_record():
    """Rikky $13C2 is `TWO_STAGE_SHAPE` byte for byte; what differs is where
    the two bytes live -- record `+9` and `+11` rather than a table after the
    records. `duration == attack + 2` holds either way, which is why the
    existing data model needed nothing."""
    for name in STRIDE16:
        sid = load_sid(str(CORPUS / name))
        _, det = _detect_tables(sid, lambda *a, **k: None)
        assert det.effect_two_stage, name
        assert det.two_stage_frames == det.two_stage_wave + 2, name
    sid = load_sid(str(CORPUS / "Rikky.sid"))
    _, det = _detect_tables(sid, lambda *a, **k: None)
    assert det.two_stage_wave - det.instr_start == 9
    assert det.two_stage_frames - det.instr_start == 11


@needs_corpus
def test_the_instrument_bound_is_not_taken_in_this_dialect():
    """`_bound_instruments` is a measurement over the 35 stride-8 files. The
    one stride-16 file whose two-stage offset happens to be a multiple of its
    stride is Powerplay Hockey, and taking the bound there cuts 12 records to
    6 -- below the instrument 8 its own patterns name -- for melody 72% -> 66%
    and wave 37% -> 26%."""
    sid = load_sid(str(CORPUS / "Powerplay_Hockey_USA_vs_USSR.sid"))
    _, det = _detect_tables(sid, lambda *a, **k: None)
    assert det.effect_two_stage
    assert det.instr_used == 12


@needs_corpus
def test_the_stride_eight_dialect_still_takes_its_bound():
    """The guard must not switch the reduction off where it was measured."""
    sid = load_sid(str(CORPUS / "IK_plus.sid"))
    _, det = _detect_tables(sid, lambda *a, **k: None)
    assert det.instr_stride == 8 and det.effect_two_stage
    assert det.instr_used == 15, "IK+ counts 30 records and has 15"
