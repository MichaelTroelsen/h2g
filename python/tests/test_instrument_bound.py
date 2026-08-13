"""Where the instrument table ends.

`detect()` counts instruments by walking the records in `instr_stride` steps
and stopping at the first +2 byte that is not a waveform. Nothing in that walk
knows where the records stop. In the 34 corpus files that carry the two-stage
attack array (see test_two_stage.py) a second table of the same 8-byte rows
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
        # 34 stride-8 files; the two-stage block is now detected in the 16-byte
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


def _dangling(path, opts):
    """(highest instrument referenced, or None if nothing dangles).

    Read out of goatwriter's own warning rather than re-derived here: it is
    the check the converter already performs, over the patterns as built.
    """
    msgs = []
    try:
        convert(str(path), log=msgs.append, **opts)
    except Exception:
        return None
    m = next((x for x in msgs if "DANGLING" in x), None)
    return int(m.split("$")[1].split()[0], 16) if m else None


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
    """
    if not CORPUS.is_dir():
        return
    import h2g.detect as d
    opts = dict(FIXED, legal_restart=True)
    checked = 0
    for path in sorted(CORPUS.glob("*.sid")):
        sid = load_sid(str(path))
        sid, det = _detect_tables(sid, lambda *a, **k: None)
        if not det.effect_two_stage:
            continue
        checked += 1
        bounded = _dangling(path, opts)
        monkeypatch.setattr(d, "_bound_instruments", lambda *a, **k: None)
        unbounded = _dangling(path, opts)
        monkeypatch.undo()
        if unbounded is None:
            assert bounded is None, (path.name, bounded)
        else:
            assert bounded == unbounded, (path.name, bounded, unbounded)
    assert checked >= 30, checked


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
    """
    if not CORPUS.is_dir():
        return
    nineteen = CORPUS / "Nineteen.sid"
    assert _dangling(nineteen, {}) is not None
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
