"""The free-note respell runs beside bit $10's phase split where the split is never displaced.

Task food-feud-pitch-seq-wave-hold. Forcing `pitch_seq` + `pulse_phase` on
Food_Feud lifts tie_agreement .705 -> .929 and cents .900 -> .982, but cost
`wave` .9930 -> .9909: 12 frames on voice 0 and 2 on voice 2 where the
original holds `$41` and ours wrote `$11` (frames 340-341, a flagged note
after instrument 8's A-5 attack). Cause: the free-note respell (a bit-7 note
skips the two-stage attack and the pulse reseed, `free_note_skips_two_stage`)
stands down beside ANY phase split, silently, and the bit-$10 plan only asks
`displaces` -- the check that declines the plan where the respell has work --
on the outer-gated flat clocks. Food_Feud's divider clock is not one, so the
split ran and the respell's 14 rows (22 with `pulse_phase`) played the attack
stage the original skips. The respell now runs beside a split the planner
never asked about, exactly as `phase_split_over_passes` makes it on the files
that option names (`test_phase_split_over_passes.py`).
"""
import json
import pathlib

from h2g.convert import convert

from corpus import CORPUS, needs_corpus

REPO_ROOT = pathlib.Path(__file__).resolve().parents[2]
SPLIT = "pitch phase split: "


def _food_feud(forced: bool, **extra):
    import fidelity as F
    doc = json.loads((REPO_ROOT / "presets.json").read_text(encoding="utf-8"))
    if forced:
        doc["songs"]["Food_Feud.sid"].update(pitch_seq=True, pulse_phase=True)
    opts = F._preset_opts(doc, "Food_Feud.sid")
    opts.update(extra)
    lines = []
    blob = convert(str(CORPUS / "Food_Feud.sid"), log=lines.append, **opts)
    return blob, lines


def _clones(lines):
    return [ln for ln in lines if ln.startswith(SPLIT) and "clone(s) [" in ln]


def _free_note(lines):
    return [ln for ln in lines if ln.startswith("Free note (bit 7)")]


@needs_corpus
def test_the_free_note_respell_runs_beside_food_feuds_pitch_split():
    """Forced `pitch_seq`: the split is made (4 clones of records 3 and 4) AND
    the respell takes its flagged rows. Without the respell the log has no
    `Free note` line at all and notes 339/342 of voice 0 play the attack."""
    _blob, lines = _food_feud(True)
    assert _clones(lines), lines
    assert not any(ln.startswith(SPLIT + "not splitting") for ln in lines)
    free = _free_note(lines)
    assert free, lines
    rows = int(free[0].split(": ", 1)[1].split(" ", 1)[0])
    assert rows >= 14, free


@needs_corpus
def test_it_is_what_the_explicit_option_gives_there_byte_for_byte():
    """`phase_split_over_passes` is the existing way to ask for the respell
    beside the split; on a clock the planner never displaces it is now the
    default, so the two conversions are the same bytes."""
    default, _ = _food_feud(True)
    explicit, _ = _food_feud(True, phase_split_over_passes=True)
    assert default == explicit


@needs_corpus
def test_the_shipped_conversion_has_no_split_and_keeps_its_free_note_rows():
    """Without `pitch_seq` (Food_Feud's preset before v0.5.680): no split, the
    respell's own 14 rows -- the baseline the forced conversion is held to.
    Since v0.5.680 the shipped preset IS the forced pair, so the shipped bytes
    equal the forced ones and differ from this baseline."""
    blob, lines = _food_feud(False, pitch_seq=False, pulse_phase=False)
    shipped, _ = _food_feud(False)
    forced, _ = _food_feud(True)
    assert shipped == forced
    assert shipped != blob
    assert not _clones(lines), lines
    free = _free_note(lines)
    assert free and free[0].split(": ", 1)[1].startswith("14 flagged"), free
    # the unmoved bytes themselves are pinned by tests/test_output_sha.py
    assert blob == _food_feud(False, pitch_seq=False, pulse_phase=False,
                              phase_split_over_passes=True)[0]
