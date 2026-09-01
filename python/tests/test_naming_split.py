"""`naming_split` separates a renaming loss from a structural one.

This decomposition had been written from scratch twice as a throwaway probe and
both times decided a question, which by this repo's own rule means it was a tool
that had not been committed. These tests pin the two properties that make it
worth having, and one trap that makes a nearby implementation worthless.

They are deliberately synthetic: `compare()` is the harness's own melody, so
what needs pinning is the SPLIT, not the score, and a corpus trace would make
the test slow and couple it to preset drift.
"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import fidelity as F                                    # noqa: E402


def voices(*note_lists):
    """Three voices from note-name lists, with plausible attack frames."""
    out = []
    for notes in note_lists:
        out.append(F.Voice(attacks=list(notes),
                           attack_frames=[10 * i for i in range(len(notes))]))
    while len(out) < 3:
        out.append(F.Voice())
    return out


def test_a_pure_rename_is_attributed_entirely_to_naming():
    """Same notes struck, one called something else -> the loss is naming."""
    orig = voices(["C-4", "E-4", "G-4", "C-5"])
    arm_a = voices(["C-4", "E-4", "G-4", "C-5"])
    arm_b = voices(["C-4", "E-4", "G#4", "C-5"])
    r = F.naming_split(orig, arm_a, arm_b)
    assert r["renames"] == 1, r
    assert r["loss"] > 0, "arm B must actually score worse for a split to mean anything"
    assert r["naming_share"] is not None and r["naming_share"] > 0.99, r
    assert abs(r["melody_repaired"] - r["melody_a"]) < 1e-9, \
        "repairing the only difference must restore arm A's score exactly"


def test_a_dropped_note_is_not_attributed_to_naming():
    """A structural change must NOT be repaired by name substitution.

    This is the property the equal-length guard in `naming_split` exists for:
    difflib can report a deletion next to a replacement, and substituting
    across an unequal span would repair a structural change and credit it to
    the naming half -- which would make the whole measure a tautology.
    """
    orig = voices(["C-4", "E-4", "G-4", "C-5"])
    arm_a = voices(["C-4", "E-4", "G-4", "C-5"])
    arm_b = voices(["C-4", "E-4", "C-5"])
    r = F.naming_split(orig, arm_a, arm_b)
    assert r["loss"] > 0, r
    assert r["renames"] == 0, "a deletion is not a rename"
    assert r["recovered"] == 0, r
    assert r["naming_share"] == 0.0, r


def test_no_loss_reports_no_share_rather_than_zero():
    """A share of a non-loss is not meaningful and must not read as 'not naming'."""
    orig = voices(["C-4", "E-4", "G-4"])
    arm = voices(["C-4", "E-4", "G-4"])
    r = F.naming_split(orig, arm, arm)
    assert r["loss"] == 0
    assert r["naming_share"] is None, \
        "0.0 would read as 'none of the loss was naming'; there was no loss"


def test_the_report_states_that_the_count_is_method_dependent():
    """The count is alignment-dependent and the report must say so.

    The same file has been read as 3, 7 and 8 renames by three alignments --
    and an index-wise substitution recovers 100% of ANY loss by construction,
    because it simply overwrites arm B with arm A wherever they overlap. A
    reader who takes `renames` for a fact rather than a method artefact will
    draw the wrong conclusion, so this is pinned rather than left to prose.
    """
    text = F.naming_census_report([{
        "file": "X.sid", "melody_a": 0.99, "melody_b": 0.96,
        "melody_repaired": 0.99, "loss": 0.03, "recovered": 0.03,
        "renames": 7, "naming_share": 1.0,
    }])
    low = text.lower()
    assert "method-dependent" in low
    assert "3, 7 and 8" in text, "name the three counts, so the claim is checkable"
    assert "X.sid" in text


def test_a_failed_row_is_reported_rather_than_dropped():
    """A file that will not convert must appear, not vanish from the table."""
    text = F.naming_census_report([{"file": "Bad.sid", "error": "RuntimeError: x"}])
    assert "Bad.sid" in text and "RuntimeError" in text
