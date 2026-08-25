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


def test_the_clamped_top_entry_is_in_the_length_and_not_in_the_run():
    # Entry 95 of the PAL table these players share is $FD2E -- 35 cents above
    # entry 94, not 100, because a semitone above $F820 is 67297 and $D400/
    # $D401 cannot hold it. `_table_run` is a validation and so stops there;
    # the entry is still a table entry, and three records name it.
    if not CORPUS.is_dir():
        return
    for name in ("Tarzan", "Delta_Mix-E-Load_loader", "Ricochet"):
        sid = load_sid(str(CORPUS / f"{name}.sid"))
        ft = find_freq_table(sid)
        assert ft is not None, name
        off = sid.to_offset(ft.addr) + 2 * 95
        assert sid.data[off] | (sid.data[off + 1] << 8) == 0xFD2E, name
        assert ft.run == 95, name
        assert ft.length == 96, name


# The six corpus files whose clamp is spelled `$FFFF` rather than `$FD2E`.
# They carry a second, independently rounded PAL table: 64 of its 96 entries
# differ from the commoner one by a single LSB, and its entry 94 is $F80F
# rather than $F820. That is why a rule keyed on either literal reads one
# family and misses the other -- see `sidfile._grid_edge_clamp`.
FFFF_TABLES = ("Go_Go_Dash", "Lakers_vs_Celtics", "Lion_Heart",
               "Pacific_Coast", "Radio_ACE", "Sun_Never_Shines")


@needs_corpus
def test_the_clamp_is_spelled_two_ways_and_the_census_says_which():
    # The durable fact, pinned so it decays loudly. Counted over *candidate*
    # tables (a file can offer more than one -- Powerplay Hockey offers two),
    # which is the population the docstring's numbers are about.
    from h2g.sidfile import _freq_table_sites, _grid_edge_clamp, _table_run
    spellings = {}
    candidates = 0
    for path in sorted(CORPUS.glob("*.sid")):
        sid = load_sid(str(path))
        seen = set()
        for addr in _freq_table_sites(sid.data):
            if addr in seen:
                continue
            seen.add(addr)
            off = sid.to_offset(addr)
            if not 0 <= off < len(sid.data) - 8:
                continue
            n = min(100, (len(sid.data) - off) // 2)
            vals = [sid.data[off + 2 * i] | (sid.data[off + 2 * i + 1] << 8)
                    for i in range(n)]
            start, run = max(((s, _table_run(vals, s)) for s in range(3)),
                             key=lambda t: t[1])
            if run < 36:
                continue
            candidates += 1
            if _grid_edge_clamp(vals, start + run):
                spellings.setdefault(vals[start + run], []).append(path.stem)
    assert candidates == 97, candidates
    counts = {hex(v): len(names) for v, names in sorted(spellings.items())}
    assert counts == {"0xfd2e": 82, "0xffff": 6}, counts
    assert sorted(spellings[0xFFFF]) == sorted(FFFF_TABLES), spellings[0xFFFF]
    assert sum(counts.values()) == 88


@needs_corpus
def test_the_ffff_spelling_reaches_length_the_same_way_fd2e_does():
    # The second spelling end to end, not merely as a `_grid_edge_clamp` unit
    # case: these six must come out of `find_freq_table` with the same
    # run/length split as Tarzan's, off a table whose entry 94 is $F80F.
    for name in FFFF_TABLES:
        sid = load_sid(str(CORPUS / f"{name}.sid"))
        ft = find_freq_table(sid)
        assert ft is not None, name
        off = sid.to_offset(ft.addr)
        assert sid.data[off + 2 * 94] | (sid.data[off + 2 * 94 + 1] << 8) \
            == 0xF80F, name
        assert sid.data[off + 2 * 95] | (sid.data[off + 2 * 95 + 1] << 8) \
            == 0xFFFF, name
        assert (ft.start, ft.run, ft.length) == (0, 95, 96), name


def test_the_clamp_is_arithmetic_rather_than_corruption():
    # Both families overflow, by 1762 and 1744 units respectively -- which is
    # what makes entry 95 a clamp and not a bad byte. Neither number is in the
    # test; the overflow is.
    assert 63520 * 2 ** (1 / 12) > 0xFFFF
    assert round(63520 * 2 ** (1 / 12)) == 67297
    assert round(63503 * 2 ** (1 / 12)) == 67279


def test_the_grid_edge_extension_is_the_overflow_and_nothing_else():
    from h2g.sidfile import _grid_edge_clamp
    # The real shape: a semitone above 63520 is 67297, so entry 95 is clamped.
    assert _grid_edge_clamp([63520, 0xFD2E], 1) is True
    assert _grid_edge_clamp([63520, 0xFFFF], 1) is True
    # ...and the $FFFF family's own predecessor, which is $F80F and not
    # $F820. The two families are both caught because the test is on the
    # overflow, not on either literal.
    assert _grid_edge_clamp([63503, 0xFFFF], 1) is True
    # ...and nothing below the top of a table qualifies, however off-grid the
    # bytes after it look. This is what keeps the widening to one entry in one
    # place instead of relaxing the semitone test.
    assert _grid_edge_clamp([1000, 1010], 1) is False
    assert _grid_edge_clamp([61000, 61500], 1) is False   # 61000 * 2^(1/12) fits
    # An entry that does not rise, or that is not there at all, is not a clamp.
    assert _grid_edge_clamp([63520, 63520], 1) is False
    assert _grid_edge_clamp([63520, 100], 1) is False
    assert _grid_edge_clamp([63520], 1) is False
    assert _grid_edge_clamp([63520, 0xFD2E], 0) is False


def test_the_grid_edge_entry_names_a_note_the_bound_used_to_refuse():
    # The point of the length, in the one place it is read: bit $08's alternate
    # note (Tarzan, Delta Mix-E-Load) and bit $40's fixed attack (Ricochet)
    # both index the player's table, and both refuse an index past its end.
    if not CORPUS.is_dir():
        return
    from h2g.goatwriter import (WAVE_NOTE_ABS, _fixed_attack_note,
                                _note_alternate_note)
    want = {"Tarzan": (_note_alternate_note, (0, 16)),
            "Delta_Mix-E-Load_loader": (_note_alternate_note, (5,)),
            "Ricochet": (_fixed_attack_note, (0, 20))}
    for name, (fn, records) in want.items():
        sid = load_sid(str(CORPUS / f"{name}.sid"))
        det = detect(sid, log=lambda m: None)
        for i in records:
            got = fn(sid, det, i)
            assert got is not None, (name, i)
            # $FD2E is 35 cents above Goattracker's note 94 and 65 below its
            # note 95, so the nearest-note rule names it 94 -- which is the
            # pitch the player actually sounds, register value for register
            # value.
            assert got == (WAVE_NOTE_ABS + 94) & 0xFF, (name, i, hex(got))


# The 11 files whose record 26 names note index 99 against a 96-entry table,
# with the two bytes the player's `LDA freqtbl,Y` actually loads for it.
# Neither the record nor the index differs between them; the *bytes* do, which
# is the whole finding -- see `sidfile._grid_edge_clamp`'s closing paragraph.
INDEX_99 = {
    "Bangkok_Knights": 0x1517,
    "Chain_Reaction": 0x0000,
    "Delta_Mix-E-Load_loader": 0x0000,
    "Dragons_Lair_Part_II": 0x0E12,
    "Knucklebusters": 0x0002,
    "Nineteen": 0x0002,
    "Sanxion": 0x0C08,
    "Thundercats": 0x1309,
    "W_A_R": 0x1300,
    "W_A_R_Preview": 0x1C03,
    "Zoolook": 0x1302,
}
# `80 08 41 7E 08 00 30 0A` -- the same eight bytes in all eleven files.
BOILERPLATE_26 = bytes.fromhex("8008417e0800300a")


@needs_corpus
def test_index_99_is_the_same_boilerplate_record_in_every_file():
    # The record that names it is not eleven records, it is one record copied
    # eleven times. That is the first half of "these cells are dead": a
    # sound-effect template carried from tune to tune, not a per-tune choice.
    from h2g.goatwriter import EFFECT_NOTE_ALT_MASK
    for name in INDEX_99:
        sid = load_sid(str(CORPUS / f"{name}.sid"))
        det = detect(sid, log=lambda m: None)
        base = det.instr_start + 26 * det.instr_stride
        assert sid.data[base:base + 8] == BOILERPLATE_26, name
        assert sid.data[base + 7] & EFFECT_NOTE_ALT_MASK, name
        assert sid.data[det.note_alternate + 26 * det.instr_stride] == 99, name


@needs_corpus
def test_every_other_bit_08_index_is_inside_the_table():
    # ...and the second half: 99 is the *only* out-of-range index bit $08
    # produces anywhere in the corpus. Every other record that sets the bit
    # names an entry in the validated run, so a widening is not owed to a
    # population -- it would be owed to one repeated template.
    from h2g.goatwriter import EFFECT_NOTE_ALT_MASK
    out_of_range = []
    for path in sorted(CORPUS.glob("*.sid")):
        sid = load_sid(str(path))
        det = detect(sid, log=lambda m: None)
        if det.note_alternate < 0 or det.instr_start < 0:
            continue
        ft = find_freq_table(sid)
        if ft is None:
            continue
        for i in range(max(det.instr_used, 0)):
            r7 = det.instr_start + i * det.instr_stride + 7
            off = det.note_alternate + i * det.instr_stride
            if max(r7, off) >= len(sid.data):
                continue
            if not sid.data[r7] & EFFECT_NOTE_ALT_MASK:
                continue
            if not 0 <= sid.data[off] < ft.length:
                out_of_range.append((path.stem, i, sid.data[off]))
    assert out_of_range == [(name, 26, 99) for name in sorted(INDEX_99)], \
        out_of_range


@needs_corpus
def test_index_99_reads_past_the_table_and_finds_no_note_there():
    # The routine really does read past the end -- `ASL / TAY / LDA freqtbl,Y`
    # is 8-bit with no mask, and 2*99 = 198 does not wrap. What it lands on is
    # whatever follows the table, which is a different value in every file and
    # a silent $0000 in two of them. Nothing about it is an extrapolation:
    # entry 95 is already the register ceiling, so there is no semitone above
    # it to extrapolate to.
    from h2g.goatwriter import _note_alternate_note
    for name, want in INDEX_99.items():
        sid = load_sid(str(CORPUS / f"{name}.sid"))
        ft = find_freq_table(sid)
        assert ft is not None and ft.length == 96, name
        at = sid.to_offset(ft.addr) + 2 * 99
        assert sid.data[at] | (sid.data[at + 1] << 8) == want, name
        # A semitone above entry 95 is unrepresentable, and these bytes are
        # not even monotonic with it -- all eleven read *below* $FD2E.
        assert want != 0xFD2E, name
        # ...so the emitter declines, which is what this test pins.
        det = detect(sid, log=lambda m: None)
        assert _note_alternate_note(sid, det, 26) is None, name


@needs_corpus
def test_the_boilerplate_record_is_played_in_at_most_one_place():
    # The decision half. Even if a note could be named for index 99, it would
    # reach one pattern row in one subtune of one file: W_A_R's pattern 142
    # row 0, the entry row of subtune 7 voice 0. Every other file names the
    # instrument in no emitted pattern at all, and W_A_R's PSID startSong is
    # 1, so the traced subtune is 0 and no FIDELITY.md dimension could see it.
    import json
    import h2g.convert as convert_mod
    from fidelity import _preset_opts
    presets = pathlib.Path(__file__).resolve().parents[2] / "presets.json"
    if not presets.is_file():
        return
    doc = json.loads(presets.read_text())
    captured = {}
    real = convert_mod.build_sng

    def spy(sid, det, tracks, patterns, *a, **kw):
        captured["patterns"] = patterns
        return real(sid, det, tracks, patterns, *a, **kw)

    rows = {}
    convert_mod.build_sng = spy
    try:
        for name in INDEX_99:
            opts = _preset_opts(doc, f"{name}.sid")
            captured.clear()
            convert_mod.convert(str(CORPUS / f"{name}.sid"),
                                log=lambda m: None, **opts)
            # Instrument numbers are 1-based and the inherited layout keeps a
            # placeholder at 1, so record 26 is instrument 28 unless
            # --compact-instruments dropped it.
            want = 27 if opts.get("compact_instruments") else 28
            rows[name] = sum(pat[k] == want
                             for pat in captured["patterns"]
                             for k in range(1, len(pat), 4))
    finally:
        convert_mod.build_sng = real
    assert rows == {name: (1 if name == "W_A_R" else 0) for name in INDEX_99}, \
        rows


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
