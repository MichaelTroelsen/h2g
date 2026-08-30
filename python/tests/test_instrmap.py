"""The instrument columns appended to siddump's own table.

`annotate_dump` is the join the rest of `instrmap.py` reports as a summary,
applied per frame instead of per song: it labels each voice of the trace --
including the *original's* trace -- with the GT instrument sounding on it.

What is worth pinning is that it stays faithful to the tables it sits under.
The instrument is decided on the frame after the attack and held for the note,
so a hard restart's ADSR on the attack frame cannot relabel it, and a row of
the dump cannot contradict the mapping above it.
"""
import instrmap as M
import fidelity as F

# Real Commando rows: a silent frame, an attack on all three voices, then a
# frame that writes only the gate-off waveform. The third row is what proves
# the carry-forward -- its ADSR field is dots, so a per-frame join would read
# it as ADSR 0 and lose the instrument mid-note.
DUMP = """\
| Frame | Freq Note/Abs WF ADSR Pul | Freq Note/Abs WF ADSR Pul | Freq Note/Abs WF ADSR Pul | FCut RC Typ V |
+-------+---------------------------+---------------------------+---------------------------+---------------+
|     0 | 0116  ... ..  00 0000 0B8 | 0116  ... ..  00 0000 000 | 0000  ... ..  00 0000 068 | 0000 00 Off F |
|     1 | AF58  E-7 D8  15 0DFB 180 | 2141  B-4 BB  43 0FC4 200 | 03A9  A-1 95  41 099F 168 | .... .. ... . |
|     2 | ....  ... ..  80 .... ... | ....  ... ..  80 .... ... | ....  ... ..  80 .... ... | .... .. ... . |
"""

NF = 3
# instrument 8 carries $0DFB and 5 carries $0FC4; $099F is deliberately left
# out, so voice 3 exercises the unmatched-ADSR path
INS = {0x0DFB: [8], 0x0FC4: [5]}


def _rows(text):
    return [l for l in text.splitlines() if l.startswith("|")]


def test_columns_are_appended_and_aligned():
    body, _ = M.annotate_dump(DUMP, F.parse_dump(DUMP), INS, NF)
    lines = body.splitlines()
    assert "Ins1 Ins2 Ins3" in lines[0]
    # the rule row has to grow with the header or the table stops being one
    assert len(set(len(l) for l in lines)) == 1


def test_onset_marked_and_held_for_the_note():
    body, _ = M.annotate_dump(DUMP, F.parse_dump(DUMP), INS, NF)
    r = _rows(body)
    assert r[1].endswith("   .    .    . |")      # frame 0, nothing sounding
    assert r[2].endswith("  *8   *5   *a |")      # frame 1, all three attack
    # frame 2 writes no ADSR at all; the note is still the same instrument
    assert r[3].endswith("   8    5    a |")


def test_unmatched_adsr_is_lettered_and_named():
    _, legend = M.annotate_dump(DUMP, F.parse_dump(DUMP), INS, NF)
    assert legend == ["`$099F` = `a`"]


def test_ambiguous_adsr_names_every_instrument_sharing_it():
    body, _ = M.annotate_dump(DUMP, F.parse_dump(DUMP),
                              {**INS, 0x0DFB: [3, 8]}, NF)
    assert "*3/8" in _rows(body)[2]


# --- the aligned dump ---------------------------------------------------------
#
# A literal side-by-side diff of two siddumps is 100% noise: measured on
# ACE II, 2 of 3001 lines match and difflib scores 0.001, on a conversion whose
# melody/seq/pitch are all 100%. Three things cause that, and `aligned_dump`
# corrects each: `....` means "unchanged" so the text is write-events rather
# than state, the packed player starts a few frames late, and the traces drift.

ALIGN_DUMP = """\
| Frame | Freq Note/Abs WF ADSR Pul | Freq Note/Abs WF ADSR Pul | Freq Note/Abs WF ADSR Pul | FCut RC Typ V |
+-------+---------------------------+---------------------------+---------------------------+---------------+
|     0 | 0EA3  A-3 AD  11 08F8 800 | 0000  ... ..  00 0000 000 | 0000  ... ..  00 0000 000 | 3000 F4 Low F |
|     1 | ....  ... ..  .. .... ... | ....  ... ..  .. .... ... | ....  ... ..  .. .... ... | .... .. ... . |
|     2 | 0923 (C#3 A5) 40 .... 200 | ....  ... ..  .. .... ... | ....  ... ..  .. .... ... | 2700 .. ... . |
"""


def test_dots_are_resolved_to_the_value_being_held():
    """`....` is siddump saying "unchanged", not "nothing".

    Comparing the text as written makes two traces holding identical values
    look different on nearly every line, which is the whole reason a raw diff
    of two dumps is useless.
    """
    st = M._dump_state(ALIGN_DUMP, 10)
    assert len(st) == 3
    v1 = [f[0][0] for f in st]
    assert v1[0][1] == "A-3" and v1[0][2] == "11"
    # frame 1 printed dots: every field must still read frame 0's values
    assert v1[1] == v1[0], "a held value was lost"
    # frame 2 changes note, waveform and pulse but NOT adsr -- adsr carries
    assert v1[2][1] == "C#3" and v1[2][2] == "40" and v1[2][4] == "200"
    assert v1[2][3] == "08F8", "adsr should still be the held value"


def test_the_tie_parentheses_are_stripped():
    """siddump wraps a note it did not re-gate in parens; `(C#3` is a note."""
    st = M._dump_state(ALIGN_DUMP, 10)
    assert st[2][0][0][1] == "C#3"


def test_the_filter_columns_carry_forward_too():
    st = M._dump_state(ALIGN_DUMP, 10)
    assert st[0][1] == ("3000", "F4", "Low")
    assert st[1][1] == ("3000", "F4", "Low"), "filter state was lost"
    assert st[2][1][0] == "2700" and st[2][1][1] == "F4"


def test_the_aligned_view_shifts_our_side_by_the_lag():
    """The original's frame f is our frame f+lag, or the comparison is noise."""
    late = ALIGN_DUMP.replace("|     0 |", "|     9 |")   # shape only; see below
    # Build a two-frame-late copy by prepending two silent frames.
    head, rows = ALIGN_DUMP.split("\n", 2)[:2], ALIGN_DUMP.splitlines()[2:]
    silent = "|     x | 0000  ... ..  00 0000 000 | 0000  ... ..  00 0000 000 | 0000  ... ..  00 0000 000 | 0000 00 Off F |"
    shifted = "\n".join(head + [silent, silent] + rows)
    out = M.aligned_dump(ALIGN_DUMP, shifted, 2, 10)
    assert out, "no aligned output"
    text = "\n".join(out)
    assert "startup lag of 2 frame(s)" in text
    # With the shift applied the two sides agree, so nothing is marked bold.
    body = text.split("Voice 1")[1] if "Voice 1" in text else text
    assert "note 100%" in text or "**" not in body.split("Voice 2")[0]


def test_the_aligned_view_says_it_capped_rather_than_truncating_silently():
    out = M.aligned_dump(ALIGN_DUMP, ALIGN_DUMP, 0, 10, cap=2)
    text = "\n".join(out)
    assert "Capped at 2 frame(s)" in text


def test_the_aligned_percentages_are_flagged_as_not_the_report_columns():
    """A per-frame agreement is not `melody`, and 56% next to 100% invites
    exactly that confusion."""
    text = "\n".join(M.aligned_dump(ALIGN_DUMP, ALIGN_DUMP, 0, 10))
    assert "not `FIDELITY.md`'s columns" in text

def test_the_map_joins_through_paired_keys_not_through_equality():
    """One instrument must not print as two because --cut-release moved its key.

    The ADSR pair identifies an instrument only while both sides carry the same
    one, and `--cut-release` zeroes the release nibble in OURS. Joined on `==`,
    Action_Biker's single 125-note pulse instrument printed as `$0730` "we play
    it, the original does not" ABOVE `$0739` "sounded by the original, with no
    instrument of ours" -- same waveform, same note count, two rows.

    fidelity solved this at v0.5.292 and instrmap never used the solution. The
    behaviour is pinned at the fidelity level (the join really does pair a
    release-only difference, and really does NOT pair a difference elsewhere)
    and the wiring is pinned at the instrmap level, because a correct matcher
    that nothing calls is what this was.
    """
    import pathlib
    import fidelity as F

    # release-only difference: joined
    assert dict(F.paired_keys({0x0739: 1}, {0x0730: 1})) == {0x0739: 0x0730}
    # difference OUTSIDE the release nibble: not joined
    assert dict(F.paired_keys({0x0839: 1}, {0x0730: 1})) == {}
    # an exact match is preferred and leaves the masked one alone
    got = dict(F.paired_keys({0x0730: 1, 0x0739: 1}, {0x0730: 1}))
    assert got == {0x0730: 0x0730}, got

    src = pathlib.Path(M.__file__).read_text(encoding="utf-8")
    assert "F.paired_keys(o_by, u_by)" in src, (
        "the mapping table no longer joins through the shared matcher")
    assert "_ours_to_theirs" in src, (
        "the mapping table no longer resolves our ADSR to the original's")
    assert "ins[_their] = ins[_our]" in src, (
        "the ORIGINAL's siddump is no longer labelled through the same join, "
        "so the dump and the table above it can disagree")
