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
        if span > 0 and span % det.instr_stride == 0:
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

    A pattern names Goattracker instrument `record + 2`. In several files the
    bound is exactly the highest record any pattern reaches -- not one above,
    not ten above. Arithmetic that happened to look tidy does not land on the
    last instrument a tune plays, repeatedly, in files of different sizes.
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
        exact += det.instr_used == max(highest - 1, 0)
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
