"""Where the Hubbard corpus lives, which is not in this repository.

The 95 test tunes are HVSC-derived files belonging to another collection, so
they are pointed at rather than vendored. Until v0.5.103 each test file spelled
the path out as an absolute Windows path into a sibling checkout, which meant
two things: the suite could only ever be green on one machine, and five of the
fourteen files that use it had no existence check at all, so a clone without
the corpus **failed** rather than skipped.

Set `H2G_CORPUS` to point somewhere else. The default is the path this project
was developed against, so nothing changes for an existing checkout.

Use both names together:

    from corpus import CORPUS, needs_corpus

    @needs_corpus
    def test_something_about_every_tune():
        for path in sorted(CORPUS.glob("*.sid")):
            ...

`needs_corpus` is the guard. A bare `if not CORPUS.is_dir(): return` passes a
test that never ran, which is the failure mode this module exists to remove --
skipping says so out loud and pytest counts it.
"""
import os
import pathlib

import pytest

DEFAULT = r"C:/Users/mit/claude/c64server/SIDM2/SID/Hubbard_Rob"

CORPUS = pathlib.Path(os.environ.get("H2G_CORPUS", DEFAULT))

needs_corpus = pytest.mark.skipif(
    not CORPUS.is_dir(),
    reason=f"Hubbard corpus not found at {CORPUS} -- set H2G_CORPUS")
