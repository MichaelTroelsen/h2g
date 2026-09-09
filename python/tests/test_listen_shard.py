"""`listen.py --shard` / `--merge-notes`: splitting a listening pass.

Sharding a pass is only safe because each tune's render is independent. The
part that is *not* independent is the notes: every run writes the whole
`LISTENING.md`, so shards sharing an output directory leave only the last
one's — and `abpage.py` reads that file for each tune's "what to listen for",
so the loss is silent and reads as tunes that were never staged. That happened
to 22 tunes at v0.5.307 before this existed.
"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import listen as L  # noqa: E402

HEAD = "# Listening pass\n\nStaged by listen.py.\n\n"
TAIL = "## What to write down\n\nOne line each.\n"


def _part(tmp_path, i, tunes):
    body = "".join("## %s — *named*\n\n- **note** for %s\n\n" % (t, t) for t in tunes)
    p = tmp_path / ("LISTENING.part%d.md" % i)
    p.write_text(HEAD + body + TAIL, encoding="utf-8")
    return p


def test_the_shards_partition_the_list():
    names = ["%02d.sid" % i for i in range(83)]
    for count in (2, 3, 6, 7):
        seen = []
        for index in range(count):
            seen += names[index::count]
        assert sorted(seen) == sorted(names)
        assert len(seen) == len(set(seen))


def test_merge_joins_every_part(tmp_path):
    _part(tmp_path, 0, ["Delta", "W_A_R"])
    _part(tmp_path, 1, ["ACE_II"])
    assert L.merge_notes(tmp_path) == 3
    got = (tmp_path / "LISTENING.md").read_text(encoding="utf-8")
    for t in ("Delta", "W_A_R", "ACE_II"):
        assert "## %s" % t in got
    assert got.startswith("# Listening pass")
    assert got.count("## What to write down") == 1


def test_merge_sorts_case_insensitively(tmp_path):
    _part(tmp_path, 0, ["Zoids", "acid"])
    L.merge_notes(tmp_path)
    got = (tmp_path / "LISTENING.md").read_text(encoding="utf-8")
    assert got.index("## acid") < got.index("## Zoids")


def test_merge_deletes_the_parts(tmp_path):
    _part(tmp_path, 0, ["Delta"])
    L.merge_notes(tmp_path)
    assert not list(tmp_path.glob("LISTENING.part*.md"))


def test_merge_keeps_notes_already_in_the_directory(tmp_path):
    """Staging a few more tunes into an existing pass must not discard the
    notes already there -- the v0.5.307 incident in the other direction."""
    (tmp_path / "LISTENING.md").write_text(
        HEAD + "## Commando — *named*\n\n- **old** note\n\n" + TAIL, encoding="utf-8")
    _part(tmp_path, 0, ["Delta"])
    assert L.merge_notes(tmp_path) == 2
    got = (tmp_path / "LISTENING.md").read_text(encoding="utf-8")
    assert "## Commando" in got and "## Delta" in got


def test_a_part_wins_over_a_stale_section_for_the_same_tune(tmp_path):
    """Re-staging a tune replaces its notes rather than keeping both."""
    (tmp_path / "LISTENING.md").write_text(
        HEAD + "## Delta — *named*\n\n- **stale** note\n\n" + TAIL, encoding="utf-8")
    _part(tmp_path, 0, ["Delta"])
    L.merge_notes(tmp_path)
    got = (tmp_path / "LISTENING.md").read_text(encoding="utf-8")
    assert "stale" not in got
    assert got.count("## Delta") == 1


def test_the_header_comes_from_a_part_not_from_the_file_already_there(tmp_path):
    """The preamble names the version, the window, the subtune and the
    renderer, so carrying it over from the previous pass publishes a header
    describing a run that no longer exists. A 0.5.316 / 120 s / sidplayfp pass
    shipped with `0.5.306, 30 s of subtune 0, SID2WAV` over it exactly that
    way -- the drift v0.5.311 fixed for the single-process path, reintroduced
    by the sharded one."""
    stale = ("# Listening pass\n\nStaged by listen.py (h2g 0.5.306), 30 s of "
             "subtune 0, rendered by SID2WAV.\n\n")
    (tmp_path / "LISTENING.md").write_text(
        stale + "## Commando — *named*\n\n- **old** note\n\n" + TAIL,
        encoding="utf-8")
    fresh = ("# Listening pass\n\nStaged by listen.py (h2g 0.5.316), 120 s of "
             "each file's own subtune, by sidplayfp.\n\n")
    (tmp_path / "LISTENING.part0.md").write_text(
        fresh + "## Delta — *named*\n\n- **new** note\n\n" + TAIL,
        encoding="utf-8")

    L.merge_notes(tmp_path)
    got = (tmp_path / "LISTENING.md").read_text(encoding="utf-8")

    assert "0.5.316" in got and "sidplayfp" in got and "120 s" in got
    assert "0.5.306" not in got and "SID2WAV" not in got
    # ...and the carried-over section survives, which is the other half of
    # the merge and the reason the old file is in the loop at all.
    assert "## Commando" in got and "## Delta" in got


def test_merge_with_nothing_to_do_says_so(tmp_path):
    assert L.merge_notes(tmp_path) == 0
    assert not (tmp_path / "LISTENING.md").exists()


def test_split_notes_separates_head_tunes_and_tail():
    head, secs, tail = L.split_notes(
        HEAD + "## Delta — *named*\n\nbody\n\n" + TAIL)
    assert head.startswith("# Listening pass")
    assert list(secs) == ["Delta"]
    assert tail.startswith("## What to write down")


# --- the non-sharded path merges too ----------------------------------------
#
# `merge_notes` above covers the SHARDED path. A plain run writes the whole
# document in one go, and that overwrite used to silently drop every
# tune it did not stage -- which `abpage.py` then renders as "no note", making
# a discarded section indistinguishable from a tune nobody ever staged.

NEWHEAD = "# Listening pass\n\nh2g 0.5.477, 180 s of subtune 0.\n\n"


def _doc(head, tunes, note="new"):
    return head + "".join(
        "## %s — *named*\n\n- **%s** note for %s\n\n" % (t, note, t)
        for t in tunes) + TAIL


def test_a_plain_run_keeps_the_notes_it_did_not_restage(tmp_path):
    """THE DEFECT THIS EXISTS FOR. At 665939c the file held 55 sections against
    89 staged pairs; the 34 missing were the ones absent from the last partial
    run, not tunes that had never been staged."""
    p = tmp_path / "LISTENING.md"
    p.write_text(_doc(HEAD, ["Commando", "Delta"], note="old"), encoding="utf-8")
    got, carried = L.merge_into_existing(p, _doc(NEWHEAD, ["Delta"]))
    assert "## Commando" in got, "an unstaged tune's note must survive"
    assert carried == ["Commando"]


def test_a_restaged_tune_replaces_its_old_note(tmp_path):
    p = tmp_path / "LISTENING.md"
    p.write_text(_doc(HEAD, ["Delta"], note="old"), encoding="utf-8")
    got, carried = L.merge_into_existing(p, _doc(NEWHEAD, ["Delta"]))
    assert "**new** note" in got and "**old** note" not in got
    assert carried == [], "a restaged tune is not carried over"
    assert got.count("## Delta") == 1


def test_the_header_is_this_runs_and_never_the_old_files(tmp_path):
    """Same rule as merge_notes: the preamble states the version, window,
    subtune and renderer, so a header carried over describes a run that no
    longer exists."""
    p = tmp_path / "LISTENING.md"
    p.write_text(_doc(HEAD, ["Commando"], note="old"), encoding="utf-8")
    got, _ = L.merge_into_existing(p, _doc(NEWHEAD, ["Delta"]))
    assert "0.5.477" in got and "180 s" in got
    assert "Staged by listen.py." not in got


def test_carried_sections_are_named_in_the_preamble(tmp_path):
    """A merged file asserts one provenance over mixed material unless it says
    which sections the header does NOT cover. Named as the SET, not counted."""
    p = tmp_path / "LISTENING.md"
    p.write_text(_doc(HEAD, ["Commando", "Zoids"], note="old"), encoding="utf-8")
    got, carried = L.merge_into_existing(p, _doc(NEWHEAD, ["Delta"]))
    head = L.split_notes(got)[0]
    assert "`Commando`" in head and "`Zoids`" in head
    assert "`Delta`" not in head, "a tune this run staged is not carried"
    assert carried == ["Commando", "Zoids"]


def test_no_carried_note_when_this_run_staged_everything(tmp_path):
    p = tmp_path / "LISTENING.md"
    p.write_text(_doc(HEAD, ["Delta"], note="old"), encoding="utf-8")
    got, carried = L.merge_into_existing(p, _doc(NEWHEAD, ["Delta"]))
    assert carried == []
    assert "EARLIER run" not in got


def test_a_first_run_writes_its_document_unchanged(tmp_path):
    """No file yet: the merge must be the identity, not an empty document."""
    text = _doc(NEWHEAD, ["Delta"])
    got, carried = L.merge_into_existing(tmp_path / "LISTENING.md", text)
    assert got == text and carried == []


def test_the_merge_keeps_one_tail_and_stays_sorted(tmp_path):
    p = tmp_path / "LISTENING.md"
    p.write_text(_doc(HEAD, ["Zoids", "acid"], note="old"), encoding="utf-8")
    got, _ = L.merge_into_existing(p, _doc(NEWHEAD, ["Delta"]))
    assert got.count("## What to write down") == 1
    assert got.index("## acid") < got.index("## Delta") < got.index("## Zoids")
