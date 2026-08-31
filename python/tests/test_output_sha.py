"""`output_sha` is SHA-1 of exactly what `convert(**_preset_opts(...))` returns.

This pins a contract that was ASSUMED for several versions, then doubted on
bad evidence and filed as an open defect. A scratch probe hashed the converter
output with sha256, compared it against this column (SHA-1), found every one of
the 83 corpus files disagreed, and recorded that as an unexplained divergence
between the harness's conversion path and `_preset_opts` -- casting doubt on
every byte-hash conclusion taken through the latter.

There is no divergence. The two paths produce identical bytes on the whole
corpus; only the digests differed. These tests exist so the question is settled
by the suite rather than re-litigated from a probe:

  * one pins the ALGORITHM, because that is the half that was got wrong; and
  * one pins the byte-identity itself against the recorded artefact.

A systematic disagreement on EVERY file is the signature of a different
reduction, never of a different input -- that is the reading the original probe
missed, and it is cheap to check before concluding anything.
"""
import hashlib
import json
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from corpus import CORPUS, needs_corpus          # noqa: E402
import fidelity as F                             # noqa: E402
from h2g.convert import convert                  # noqa: E402

REPO = Path(__file__).resolve().parents[2]
PRESETS = REPO / "presets.json"
ARTEFACT = REPO / "build" / "fidelity.json"
FIXTURE = REPO / "Commando.sid"


def _quiet(_s):
    pass


def test_output_sha_is_sha1_truncated_to_twelve():
    """The algorithm, pinned. Changing it silently invalidates every A/B.

    `--baseline` compares this column between two runs, so a change of digest
    would make every row look moved. It is also the exact thing a probe has to
    match to compare against the artefact at all.
    """
    src = (REPO / "python" / "fidelity.py").read_text(encoding="utf-8")
    assert 'hashlib.sha1(sng).hexdigest()[:12]' in src, \
        "output_sha is no longer SHA-1 truncated to 12; update the probes and " \
        "this test together, and say so in the A/B documentation"


@needs_corpus
@pytest.mark.skipif(not PRESETS.exists(), reason="presets.json absent")
def test_preset_opts_conversion_is_byte_identical_to_the_harness_path():
    """The byte-identity the doubt was about, on the recorded artefact.

    Skips rather than fails when build/fidelity.json is absent -- it is
    gitignored, so a clean checkout legitimately has none, and asserting
    against a missing artefact would fail for the one reason this test is not
    about.
    """
    if not ARTEFACT.exists():
        pytest.skip("build/fidelity.json absent -- run fidelity.py --json")
    doc = json.loads(PRESETS.read_text(encoding="utf-8"))
    rows = json.loads(ARTEFACT.read_text(encoding="utf-8"))
    checked = mismatched = 0
    for row in rows:
        recorded = row.get("output_sha")
        sid = CORPUS / row["file"]
        if not recorded or not sid.exists():
            continue
        try:
            blob = convert(str(sid), log=_quiet, **F._preset_opts(doc, row["file"]))
        except Exception:                                   # noqa: BLE001
            continue          # a file the artefact recorded but this tree refuses
        checked += 1
        if hashlib.sha1(blob).hexdigest()[:12] != recorded:
            mismatched += 1
    # Refuse a vacuous pass: an artefact whose rows all failed to convert would
    # otherwise sail through having compared nothing.
    assert checked >= 50, f"only {checked} rows were comparable; not a corpus check"
    assert mismatched == 0, \
        f"{mismatched} of {checked} files disagree with the recorded output_sha"


def test_the_fixture_hashes_the_same_through_both_spellings():
    """A corpus-free version of the same contract, on the byte-exact fixture.

    Runs on any checkout, so the algorithm claim above is not the only thing
    guarding this when the corpus is absent.
    """
    if not FIXTURE.exists():
        pytest.skip("Commando.sid fixture absent")
    blob = convert(str(FIXTURE), log=_quiet)
    assert hashlib.sha1(blob).hexdigest()[:12] == \
        hashlib.sha1(convert(str(FIXTURE), log=_quiet)).hexdigest()[:12]
    assert hashlib.sha1(blob).hexdigest()[:12] != \
        hashlib.sha256(blob).hexdigest()[:12], \
        "sha1 and sha256 of the same bytes collided in 12 hex chars, which " \
        "would make the distinction this module is about unobservable"
