"""Where the instrument table ends.

`detect()` counts instruments by walking the records in `instr_stride` steps
and stopping at the first +2 byte that is not a waveform. Nothing in that walk
knows where the records stop. In the 35 stride-8 corpus files that carry the
two-stage attack array (see test_two_stage.py; 44 files carry the block, but
in nine the two bytes live inside a 16-byte record and there is no trailing
array at all) a second table of the same 8-byte rows
begins immediately after the records, and its own +2 -- the low byte of a
frame count -- is a legal waveform often enough to carry the walk straight
through it. The result was roughly twice the truth: IK+ 30 records where 15
are real, Wiz 40/20, Delta 44/22, Sanxion 59/29.

That is not a cosmetic miscount. The phantom rows were emitted as instruments
whose ADSR is a duration byte, and a table of 58 exceeds what Goattracker's
255-entry wavetable can address -- so ten corpus files were reported as losing
real instruments to a limit they never reached, and H2G-CONVERSION-METHOD.md
argued from the recurring rows that the count had to be right.

`_bound_instruments` ends the count at the array `_find_two_stage` located.
These tests pin the boundary against what the *music* asks for, which is the
only check independent of the arithmetic that produced it.
"""
import pathlib
from corpus import CORPUS as _CORPUS, needs_corpus  # noqa: E402
import sys

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[1]))

import songview
from h2g.convert import _detect_tables, convert
from h2g.detect import WAVEFORMS, detect
from h2g.sidfile import load_sid
from presets import FIXED, _parse

CORPUS = _CORPUS
REPO_ROOT = pathlib.Path(__file__).resolve().parents[2]


def _det(name):
    sid = load_sid(str(CORPUS / f"{name}.sid"))
    return _detect_tables(sid, lambda *a, **k: None)


def _unbounded(sid, det):
    """The count the walk alone produces -- what detect() used to return."""
    data, j, n = sid.data, det.instr_start + 2, 0
    while 0 <= j < len(data) and data[j] in WAVEFORMS:
        j += det.instr_stride
        if j >= len(data):
            break
        n += 1
    return n


def test_ik_plus_stops_at_fifteen_not_thirty():
    if not CORPUS.is_dir():
        return
    sid, det = _det("IK_plus")
    assert _unbounded(sid, det) == 30
    assert det.instr_used == 15
    # The records end exactly where the attack array begins, and the array's
    # attack byte is its +1.
    assert det.two_stage_wave - 1 == det.instr_start + 15 * det.instr_stride


def test_the_bound_is_a_whole_number_of_records_or_is_not_applied():
    """The adjacency is required, not assumed.

    Three corpus files (ACE II, Trans-Atlantic Balloon Challenge, W.A.R.) put
    something between the two tables, so the gap is not a multiple of the
    stride. Those keep the count the walk gave them rather than being cut to
    a boundary that is not one.
    """
    if not CORPUS.is_dir():
        return
    checked = 0
    for path in sorted(CORPUS.glob("*.sid")):
        sid = load_sid(str(path))
        sid, det = _detect_tables(sid, lambda *a, **k: None)
        if not det.effect_two_stage:
            continue
        checked += 1
        span = (det.two_stage_wave - 1) - det.instr_start
        # **Stride 8 only** (v0.5.236). The rule this pins was measured over the
        # stride-8 files (34 then, 35 since v0.5.255's zero-page spelling); the two-stage block is now detected in the 16-byte
        # dialect too, where the attack and duration live *inside* the record at
        # +9 and +11 and there is no trailing array to end the table at. Eight
        # of those nine fail the multiple-of-stride test anyway; the ninth,
        # Powerplay Hockey, passes it and is the counter-example -- its patterns
        # name instrument 8 against a bound of 6, and taking it costs melody
        # 72% -> 66%.
        if det.instr_stride == 8 and span > 0 and span % det.instr_stride == 0:
            bound = span // det.instr_stride
            assert det.instr_used == min(bound, _unbounded(sid, det)), path.name
        else:
            assert det.instr_used == _unbounded(sid, det), path.name
    assert checked >= 30, checked


def _rows(pat):
    """(note, instrument) per row, stopping at the end-of-pattern marker."""
    for r in range(0, len(pat), 4):
        if pat[r] == songview.GT_END_PATTERN:
            return
        yield pat[r], pat[r + 1]


def _played(blob):
    """(highest instrument the ORDERLISTS reach, written, reached set, patterns).

    Read back from the emitted `.sng` with songview's parser rather than from
    the converter's internals -- the reason `tests/test_songview.py` exists: a
    reader that shares code with the writer cannot disagree with it.
    """
    song = songview.parse_sng(blob)
    reached = set()
    for sub in range(song.subtunes):
        for voice in range(3):
            for kind, what, _ in songview.decode_orderlist(
                    song.tracks[sub * 3 + voice]):
                if kind == "pattern":
                    reached.add(int(what[1:], 16))
    hi = 0
    for i in reached:
        if i < len(song.patterns):
            hi = max([hi] + [ins for _, ins in _rows(song.patterns[i])])
    return hi, len(song.instruments), reached, len(song.patterns)


def _both(path, opts):
    """(reported, played) -- the two readings, from ONE conversion.

    `reported` is goatwriter's own DANGLING warning, over the patterns as
    built: ALL of them, reachable or not. That is right for the converter,
    which must not emit a reference it cannot satisfy, and wrong for the
    question `test_the_bound_adds_no_dangling_reference` asks, which is about
    the music. `played` is the same question restricted to the patterns some
    orderlist actually reaches, and is None when nothing the tune plays names
    an instrument beyond the ones written.

    Both come from the same bytes deliberately: two conversions would leave a
    difference between the readings unattributable.
    """
    msgs = []
    try:
        blob = convert(str(path), log=msgs.append, **opts)
    except Exception:
        return None, None
    m = next((x for x in msgs if "DANGLING" in x), None)
    reported = int(m.split("$")[1].split()[0], 16) if m else None
    hi, written, _, _ = _played(blob)
    return reported, (hi if hi > written else None)


def _dangling(path, opts):
    """goatwriter's warning alone -- what the converter reports, all patterns."""
    return _both(path, opts)[0]


def _dangling_played(path, opts):
    """The same question asked only of the patterns the orderlists reach."""
    return _both(path, opts)[1]


def test_the_bound_adds_no_dangling_reference(monkeypatch):
    """The falsification, run as a difference rather than an absolute.

    Some corpus files reference instruments they do not contain whatever the
    count is -- unreachable patterns full of bytes that were never note data.
    So the question is not whether any reference dangles; it is whether the
    bound makes one dangle that did not. Over every file carrying the array,
    under the options presets.json always applies, a file that was clean stays
    clean, and where something already dangled the *highest* reference is
    unchanged -- the bound moves how many are unmet, never which byte is at
    the top, because it does not touch the patterns at all.

    **THE REDUCTION IS OVER PLAYED PATTERNS SINCE v0.5.461, AND RICOCHET IS
    WHY.** It used to read goatwriter's DANGLING warning, which scans every
    pattern emitted -- and Ricochet emits 150 of which its one subtune plays
    40. v0.5.459's derived instrument mask made the UNBOUNDED conversion of
    that file clean (32 written covers the highest byte any pattern carries,
    $20), so the difference construction started charging the bound for a
    reference in pattern 7 -- 94 rows whose notes read G#7, D-2 and D#0
    against the $01-$07 every played pattern names. Bytes that were never note
    data, which is the case the paragraph above already knew about and which
    the old reduction could only survive while the unbounded count happened
    not to cover them. Same correction as CLAUDE.md's "walk the orderlist in
    play order" rule, written for the identical mistake one axis over
    (`instr 00` is inheritance, so "names no instrument" is never the quantity
    you want).

    The bound is right on that file, and the PLAYER says so rather than the
    arithmetic: the block at file $0ADE that the walk keeps counting is read
    at `LDA $9A1C,Y / STA $44 / LDA $9A1D,Y / STA $45 / LDA ($44),Y` -- a
    pointer per instrument, dereferenced -- and at `LDA $9A1F,X` beside the
    records' own `LDA $999C,X` and `LDA $999F,X`. It is a parallel
    per-instrument table, not more records: 16 rows for 16 records, which is
    why the unbounded walk lands on exactly twice the truth here as it does on
    IK+ 30/15, Wiz 40/20 and Delta 44/22.

    Both readings are still taken, because the old one is what stops this
    quietly becoming a weaker test: over the 50 corpus files carrying the
    array, the warning moves between the two arms on RICOCHET ALONE, and the
    played reading is clean on every file in both arms (Arcade Classics and
    BMX Kidz warn at $32 in both arms and neither plays it).
    """
    if not CORPUS.is_dir():
        return
    import h2g.detect as d
    opts = dict(FIXED, legal_restart=True)
    checked, clean, moved = 0, 0, []
    for path in sorted(CORPUS.glob("*.sid")):
        sid = load_sid(str(path))
        sid, det = _detect_tables(sid, lambda *a, **k: None)
        if not det.effect_two_stage:
            continue
        checked += 1
        b_reported, bounded = _both(path, opts)
        monkeypatch.setattr(d, "_bound_instruments", lambda *a, **k: None)
        u_reported, unbounded = _both(path, opts)
        monkeypatch.undo()
        if unbounded is None:
            assert bounded is None, (path.name, bounded)
        else:
            assert bounded == unbounded, (path.name, bounded, unbounded)
        clean += bounded is None and unbounded is None
        if b_reported != u_reported:
            moved.append((path.name, b_reported, u_reported))
    assert checked >= 30, checked
    # Measured at v0.5.461 over the 50 files carrying the array: nothing any
    # tune PLAYS dangles at either count, and the whole-file warning moves on
    # one file only.
    assert clean == checked, (clean, checked)
    assert [m[0] for m in moved] == ["Ricochet.sid"], moved


def test_ricochets_warning_is_a_pattern_no_orderlist_reaches():
    """The single file above, pinned so the reduction cannot be simplified back.

    A reader who deletes the played/reported distinction gets a green suite
    until this file is converted again, so the difference is asserted rather
    than merely described: the warning says $20, the music says $07 against 16
    instruments written, and every pattern naming $20 is one nothing plays.
    """
    if not CORPUS.is_dir():
        return
    opts = dict(FIXED, legal_restart=True)
    path = CORPUS / "Ricochet.sid"
    blob = convert(str(path), log=lambda m: None, **opts)
    song = songview.parse_sng(blob)
    hi, written, reached, total = _played(blob)
    assert (hi, written) == (7, 16), (hi, written)
    assert 0 < len(reached) < total, (len(reached), total)   # 40 of 150
    assert _dangling(path, opts) == 0x20
    assert _dangling_played(path, opts) is None
    naming = {i for i, pat in enumerate(song.patterns)
              if any(ins == 0x20 for _, ins in _rows(pat))}
    assert naming and not (naming & reached), sorted(naming & reached)


def test_the_bound_lands_on_the_last_instrument_played_in_several_files():
    """Why the boundary is a reading and not a plausible-looking guess.

    A pattern names Goattracker instrument `record + base`, where base is 2 in
    the inherited layout (instrument 1 being the empty Clear Voice) and 1 under
    --compact-instruments. In several files the bound is exactly the highest
    record any pattern reaches -- not one above, not ten above. Arithmetic that
    happened to look tidy does not land on the last instrument a tune plays,
    repeatedly, in files of different sizes.

    The offset is derived from the options actually used rather than written in,
    so this keeps testing the *bound* rather than the numbering convention.
    """
    if not CORPUS.is_dir():
        return
    exact, checked = 0, 0
    for path in sorted(CORPUS.glob("*.sid")):
        sid = load_sid(str(path))
        sid, det = _detect_tables(sid, lambda *a, **k: None)
        if not det.effect_two_stage:
            continue
        try:
            blob = convert(str(path), log=lambda m: None,
                           **dict(FIXED, legal_restart=True))
        except Exception:
            continue
        checked += 1
        _, patterns = _parse(blob, ntables=4)
        highest = max((p[k] for p in patterns for k in range(1, len(p), 4)),
                      default=0)
        base = 1 if FIXED.get("compact_instruments") else 2
        exact += det.instr_used == max(highest - (base - 1), 0)
    assert checked >= 25, checked
    assert exact >= 3, exact


def test_nineteen_at_bare_defaults_is_a_slide_operand_not_an_instrument():
    """The one file the bound newly warns about, and why it is not a cut.

    At the survey defaults Nineteen's patterns appear to name instrument $31,
    which the bound no longer writes. Turning on `--slides` -- which reads the
    second operand byte of a pitch-bend command instead of decoding it as an
    event -- clears the reference entirely. The byte was never an instrument;
    it is the far end of a bend, and the warning is a symptom of a different
    default. presets.json's `always` block sets `slides`.

    **SUPERSEDED AT v0.5.459 AND KEPT FOR THE READING, NOT THE SYMPTOM.** The
    `$31` never reached a real instrument in the PLAYER either: it masks a
    pattern's instrument byte by SHIFTING (`ASL A` x3 for a stride-8 record),
    which keeps five bits, so `$31` indexes record 17 and not 49. Once
    `patterns._instrument_mask` derives that from the stride, the bare-default
    reference is in range and the warning is gone -- so this no longer asserts
    that a warning appears. What is still true and still worth pinning is the
    second line: the byte is a bend operand, and `--slides` makes it vanish as
    an event rather than merely land somewhere legal.
    """
    if not CORPUS.is_dir():
        return
    nineteen = CORPUS / "Nineteen.sid"
    # The symptom this test was written for is gone, by the mask fix:
    assert _dangling(nineteen, {}) is None
    assert _dangling(nineteen, {"slides": True}) is None


def test_a_file_without_the_array_keeps_its_count():
    """Nothing may move a file the evidence does not cover.

    Commando has no two-stage block, so its count comes from the walk alone --
    which is what the byte-exact fixture encodes.
    """
    sid = load_sid(str(REPO_ROOT / "Commando.sid"))
    det = detect(sid, log=lambda m: None)
    assert not det.effect_two_stage
    assert det.instr_used == _unbounded(sid, det)


def test_no_corpus_file_is_reported_over_the_wavetable_ceiling():
    """The claim the miscount was producing.

    Ten files were detected over Goattracker's wavetable limit and the nine of
    them that convert were listed in SURVEY.md as losing the excess, 80 records
    in total. All ten carry the two-stage array; none is over the ceiling once
    the count stops at the records.
    """
    if not CORPUS.is_dir():
        return
    over = []
    for path in sorted(CORPUS.glob("*.sid")):
        sid = load_sid(str(path))
        try:
            sid, det = _detect_tables(sid, lambda *a, **k: None)
        except Exception:
            continue
        if det.instr_used + 1 > 50:
            over.append(path.name)
    assert over == [], over


def _instrument_count(blob: bytes) -> int:
    """The stored instrument count byte, read the way gsong.c walks the file."""
    q = 4 + 96
    subs = blob[q]; q += 1
    for _ in range(subs * 3):
        n = blob[q]; q += 1; q += n + 1
    return blob[q]


def test_compact_instruments_frees_the_placeholder_slot():
    """Goattracker reserves no slot; the VB6 original's Clear Voice did.

    Its format stores instruments from 1 and a pattern column of 0 already
    means "no change" (readme:613, 1386), so the empty slot at 1 is inherited
    convention rather than a requirement. Dropping it frees an instrument slot
    and five wavetable entries and lines the numbering up with the player's own
    records -- which is how it was noticed: a listener named an instrument by
    number and it was one slot away from the one h2g had written.
    """
    from h2g.convert import convert as _convert
    fixture = str(REPO_ROOT / "Commando.sid")
    # Both with rest_instrument, so the only difference under test is the
    # numbering: compacting implies it (there is no empty slot left to aim a
    # placeholder note at), and comparing against the placeholder layout would
    # be comparing two changes at once.
    plain = _convert(fixture, log=lambda m: None, fmt="gts5",
                     rest_instrument=True)
    compact = _convert(fixture, log=lambda m: None, fmt="gts5",
                       rest_instrument=True, compact_instruments=True)
    assert _instrument_count(compact) == _instrument_count(plain) - 1

    _, pats_p = _parse(plain, ntables=4)
    _, pats_c = _parse(compact, ntables=4)
    shifted = 0
    for a, b in zip(pats_p, pats_c):
        for k in range(1, min(len(a), len(b)), 4):
            if a[k]:
                assert b[k] == a[k] - 1, "instrument numbers shift by exactly one"
                shifted += 1
    assert shifted, "the fixture should name instruments at all"


def test_compact_is_off_by_default_and_the_fixture_is_untouched():
    """Verified corpus-wide when this shipped: 83 of 83 byte-identical.

    The fixture stands for that here, and is the reason the layout change is an
    option rather than a correction -- Commando.sng is what proves the port
    reproduces the VB6 original, and the original is what reserved the slot.
    """
    from h2g.convert import convert as _convert
    assert _convert(str(REPO_ROOT / "Commando.sid"), log=lambda m: None) ==         (REPO_ROOT / "Commando.sng").read_bytes()


# --- v0.5.239: the reservation is a property the emitters have to hold up ---

@needs_corpus
def test_no_record_overruns_a_budget_of_five():
    """`_wavetable_layout` reserves `WAVE_ENTRIES_PER_INSTR` for every later
    record and floors each budget at the same five. That is only a guarantee if
    the emitters honour it, and two of them did not: the tick shape checked
    nothing and `_drum_entries` checked only its sweep, so 197 records across 40
    corpus files emitted 6, 7 or 8 when handed 5. It bites where a table is
    nearly full -- W_A_R at `--two-stage --pitch-seq` overran 255 by one and
    `gt2reloc` refused the file with no message."""
    import json
    import fidelity as F
    from h2g.goatwriter import _wavetable_entries

    doc = json.loads((pathlib.Path(__file__).resolve().parents[2]
                      / "presets.json").read_text(encoding="utf-8"))
    over = []
    for path in sorted(CORPUS.glob("*.sid")):
        try:
            sid, det = _detect_tables(load_sid(str(path)), lambda *a, **k: None)
        except Exception:                              # noqa: BLE001
            continue
        opts = F._preset_opts(doc, path.name)
        mult = F._preset_multiplier(doc, path.name)
        for i in range(max(det.instr_used - 1, 0)):
            try:
                left, _ = _wavetable_entries(
                    sid, det, i, True, "gts5", [], mult, None, 1, 1, 5,
                    two_stage=opts.get("two_stage", False),
                    sfx_drum=opts.get("sfx_drum", False),
                    wave_program=opts.get("wave_program", False),
                    pitch_seq=opts.get("pitch_seq", False),
                    no_test_restart=opts.get("no_test_restart", False))
            except Exception:                          # noqa: BLE001
                continue
            if len(left) > 5:
                over.append((path.name, i, len(left)))
    assert not over, over[:10]


@needs_corpus
def test_every_search_combination_of_the_fullest_files_converts():
    """The four corpus files whose wavetables come closest to the 255-row
    ceiling, over all 31 combinations the preset search tries. W_A_R had four
    that raised, and a raising candidate cost it a measured setting until
    v0.5.235 made the search skip rather than abandon."""
    import itertools
    import presets as P
    from h2g.convert import convert

    for name in ("W_A_R.sid", "Mega_Apocalypse.sid", "Thundercats.sid",
                 "Kings_of_the_Beach_intro.sid"):
        path = CORPUS / name
        found = P.best_options(path)
        base = {k: found[k] for k in ("max_rows", *P.TOGGLES)}
        for r in range(len(P.FIDELITY_TOGGLES) + 1):
            for combo in itertools.combinations(P.FIDELITY_TOGGLES, r):
                convert(str(path), log=lambda m: None, **base, **P.FIXED,
                        **{k: True for k in combo})
