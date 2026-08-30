"""`presets.json` on disk must be exactly what its generator would write.

A generated artefact is only reviewable if a regeneration that changes nothing
semantically also changes nothing textually. For a long time this one was not:
the committed file was written with `indent=1` while `presets.py` dumps with
`indent=2`, so ANY regeneration rewrote all 1035 lines whatever had actually
changed -- which is worse than useless, because a real one-song change would
have been invisible inside it. It was found at v0.5.410 (while diffing a
two-song multiplier change against a 1035-line wall) and fixed by the
regeneration that commit already had to do; this test is what stops it coming
back, since nothing else compares the file's FORM to its generator's.

Two things this deliberately does not assert:

* the `generator` stamp, which legitimately moves every time the version does
  -- `bump_version.py` runs AFTER the artefact is regenerated, so a commit
  ships an artefact stamped one version behind, and CLAUDE.md records that as
  known and accepted;
* line endings. `presets.py` writes through `Path.write_text`, which on Windows
  translates to CRLF, while `json.dumps` yields LF -- a 1038-byte difference on
  a 1038-line file that is entirely `\\r`. git normalises it (`core.autocrlf`),
  so it never reaches a diff. Comparing raw bytes here would fail on Windows
  and pass on Linux, which is a worse test than none.
"""
import json
import pathlib
import sys

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[1]))

PRESETS = pathlib.Path(__file__).resolve().parents[2] / "presets.json"


def _normalised(path):
    return path.read_bytes().decode("utf-8").replace("\r\n", "\n")


def test_presets_json_is_what_its_generator_would_write():
    """The round-trip pins indent AND key order, which is the whole point.

    `json.loads` preserves the file's key order and `json.dumps` preserves the
    dict's, so re-dumping is a fixed point exactly when the file was written by
    this dump call with these settings.
    """
    on_disk = _normalised(PRESETS)
    redumped = json.dumps(json.loads(on_disk), indent=2) + "\n"
    assert on_disk == redumped, (
        "presets.json is not in its generator's form -- a regeneration would "
        "rewrite lines that did not change. Regenerate it with "
        "`python presets.py <corpus> -o ../presets.json` rather than editing "
        "it by hand."
    )


def test_the_indent_is_the_one_presets_py_uses():
    """Pinned against the generator's own literal, not against a constant here.

    A test carrying its own copy of the number would keep passing if
    `presets.py` changed its dump and the artefact did not -- which is the
    exact divergence this file exists to catch.
    """
    src = (pathlib.Path(__file__).resolve().parents[1] / "presets.py").read_text(
        encoding="utf-8")
    assert src.count("indent=2") >= 1, "presets.py no longer dumps at indent=2"
    assert "indent=1" not in src
    # And the file agrees: its second line is indented by exactly two spaces.
    second = _normalised(PRESETS).splitlines()[1]
    assert second.startswith('  "') and not second.startswith('   '), second
