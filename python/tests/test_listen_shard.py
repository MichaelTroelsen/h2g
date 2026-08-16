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


def test_merge_with_nothing_to_do_says_so(tmp_path):
    assert L.merge_notes(tmp_path) == 0
    assert not (tmp_path / "LISTENING.md").exists()


def test_split_notes_separates_head_tunes_and_tail():
    head, secs, tail = L.split_notes(
        HEAD + "## Delta — *named*\n\nbody\n\n" + TAIL)
    assert head.startswith("# Listening pass")
    assert list(secs) == ["Delta"]
    assert tail.startswith("## What to write down")
