"""The player's own note frequency table, and the two ways it can disagree
with Goattracker's.

Every Hubbard player carries a table of SID frequency register values, one per
semitone, and looks a pattern's note byte up in it. Goattracker has the same
thing (gplay.c:9/23), and this converter has always assumed the two line up --
note byte n becomes Goattracker note $60+n.

Two files' worth of the corpus say otherwise, and they need opposite answers:

  * **Skate or Die (intro)** has a $0000 at entry 0, so its first *sounding*
    entry is 1 and its note byte n is Goattracker's note n-1. Emitting $60+n
    played the whole tune one semitone sharp -- 5% melody similarity against
    the original, with every note in the right place. That is a converter
    defect and is corrected.

  * **Kings of the Beach (intro), One on One, Powerplay Hockey and Rock Tells
    the Tale** carry tables computed for the NTSC C64's faster clock: every
    register value is 0.647 semitones (985248/1022727) below the PAL
    equivalent. The note *numbers* are right and no Goattracker file can say
    "and tune the chip down 65 cents", so nothing is corrected. It shows up
    only in a harness that reads note names out of register values, where it
    is worth exactly one siddump -c flag -- see fidelity.calibration.

Telling the two apart is the whole job, and they are not close: a shifted
table sits within 7 cents of the semitone grid and an NTSC one 65 cents off
it.
"""
import pathlib
from corpus import CORPUS as _CORPUS, needs_corpus  # noqa: E402
import sys

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[1]))


from h2g.detect import detect
from h2g.sidfile import GT_FREQ0, find_freq_table, load_sid

CORPUS = _CORPUS
COMMANDO = pathlib.Path(__file__).resolve().parents[2] / "Commando.sid"

# 12 * log2(985248 / 1022727): a table written for NTSC, read at PAL.
NTSC_SEMITONES = -0.6469


def _table(name):
    return find_freq_table(load_sid(str(CORPUS / f"{name}.sid")))


def test_commando_table_is_found_and_lines_up():
    # The fixture file, so this one runs wherever the repo does. Commando's
    # table is the shape 88 of the 95 corpus files share: entry 0 sounds, and
    # it is Goattracker's note 0 to within the rounding of a 16-bit register.
    ft = find_freq_table(load_sid(str(COMMANDO)))
    assert ft is not None
    assert ft.start == 0
    assert ft.shift == 0
    assert abs(ft.detune) < 0.1
    assert ft.length >= 90


def test_commando_note_base_is_zero():
    sid = load_sid(str(COMMANDO))
    assert detect(sid, log=lambda m: None).note_base == 0


def test_skate_or_die_table_starts_one_entry_late():
    if not CORPUS.is_dir():
        return
    ft = _table("Skate_or_Die_intro")
    assert ft is not None
    # Entry 0 is the dummy; entry 1 holds what everyone else holds at entry 0.
    data = load_sid(str(CORPUS / "Skate_or_Die_intro.sid"))
    off = data.to_offset(ft.addr)
    assert data.data[off] | (data.data[off + 1] << 8) == 0
    assert ft.start == 1
    assert ft.shift == -1
    # The table itself is a perfectly ordinary PAL one -- only its index moved.
    assert abs(ft.detune) < 0.1


def test_skate_or_die_note_base_reaches_detection():
    if not CORPUS.is_dir():
        return
    sid = load_sid(str(CORPUS / "Skate_or_Die_intro.sid"))
    assert detect(sid, log=lambda m: None).note_base == -1


def test_ntsc_tables_are_reported_as_tuning_not_as_a_shift():
    if not CORPUS.is_dir():
        return
    for name in ("Kings_of_the_Beach_intro", "One_on_One_Jordan_vs_Bird",
                 "Powerplay_Hockey_USA_vs_USSR", "Rock_Tells_the_Tale"):
        ft = _table(name)
        assert ft is not None, name
        # round(-0.70) is -1; the fractional residue is what stops it being
        # read as an index shift, and it must match the clock ratio.
        assert ft.shift == 0, name
        assert abs(ft.detune - NTSC_SEMITONES) < 0.1, (name, ft.detune)


def test_a_dummy_entry_zero_is_not_on_its_own_a_shift():
    if not CORPUS.is_dir():
        return
    # I, Ball also has $0000 at entry 0 -- but its entry 1 is Goattracker's
    # note *1*, so the index scales already agree and nothing must move. This
    # is the case a "table starts with $0000, subtract one" rule would break.
    ft = _table("I_Ball")
    assert ft is not None
    assert ft.start == 1
    assert ft.shift == 0
    assert abs(ft.detune) < 0.1


def test_the_shift_is_the_only_one_in_the_corpus():
    if not CORPUS.is_dir():
        return
    shifted = sorted(p.stem for p in CORPUS.glob("*.sid")
                     if (find_freq_table(load_sid(str(p))) or
                         type("", (), {"shift": 0})()).shift)
    assert shifted == ["Skate_or_Die_intro"]


def test_a_file_with_no_recognised_lookup_keeps_the_old_mapping():
    if not CORPUS.is_dir():
        return
    # Six players index their table through an idiom find_freq_table does not
    # know. They must come back None -- and note_base 0, i.e. exactly what the
    # converter did before any of this existed -- rather than a wrong guess.
    for name in ("Casio_Extended", "Robs_Life", "Task_Force"):
        sid = load_sid(str(CORPUS / f"{name}.sid"))
        assert find_freq_table(sid) is None, name
        assert detect(sid, log=lambda m: None).note_base == 0, name


def test_gt_freq0_matches_goattrackers_table():
    # gplay.c freqtbllo[0] = 0x17, freqtblhi[0] = 0x01. If this ever drifts,
    # every base measurement above silently moves with it.
    assert GT_FREQ0 == 0x0117


def test_calibration_maps_a_flat_table_onto_siddumps_naming():
    from fidelity import SIDDUMP_MIDDLE_C, calibration
    assert calibration(0.0) == SIDDUMP_MIDDLE_C
    # An NTSC table's middle C, the value siddump must be told to call C-4 for
    # the original to be named in the same key as our PAL conversion.
    assert calibration(NTSC_SEMITONES) == 0x10C5
    # A whole semitone down halves nothing and moves 1/12 of an octave.
    assert calibration(-12.0) == SIDDUMP_MIDDLE_C // 2
