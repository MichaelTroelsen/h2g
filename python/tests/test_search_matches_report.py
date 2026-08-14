"""The preset search must trace what the fidelity report traces.

`presets.tune_by_fidelity` is a second implementation of "convert, pack, trace
both, compare" beside `fidelity._measure`, and until v0.5.223 nothing pinned
the two together. It had drifted in two ways, each of which makes the search
score two *different pieces of music* and so corrupts every setting the
`--fidelity` search has ever chosen:

* it traced the original with a hardcoded calibration of 0, so the four corpus
  files whose frequency table sits off the semitone grid had every note
  misnamed -- One_on_One_Jordan_vs_Bird scored 5% and reads 99% correctly;
* it compared the original's subtune N against *our* subtune N, where the
  report searches a window of ours for the real counterpart -- Action_Biker
  scores 6% that way and 100% the other, and the search "improved" the 6% with
  a setting it then shipped.

Both were found by chasing a suspicious row. These tests are what makes the
next drift fail loudly instead.

`songview.py`'s parser is also a deliberate second implementation of something
this repo already writes, and it is *safe* -- because `test_songview.py`
asserts it agrees with the writer and with the byte-exact fixture. Same
pattern, opposite outcome, and the difference is a test.
"""
import os
import pathlib
import sys

import pytest

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent.parent))

import fidelity                                        # noqa: E402
import presets                                         # noqa: E402
from corpus import CORPUS, needs_corpus                # noqa: E402
from h2g.sidfile import find_freq_table, load_sid      # noqa: E402

siddump = os.environ.get("H2G_SIDDUMP", fidelity.SIDDUMP)
needs_tools = pytest.mark.skipif(
    not (pathlib.Path(siddump).exists()
         and pathlib.Path(fidelity.GT2RELOC).exists()),
    reason="siddump/gt2reloc not available")

# The two files the two bugs were found on. Named rather than discovered so a
# corpus that no longer contains them skips rather than passes vacuously.
DETUNED = "One_on_One_Jordan_vs_Bird.sid"     # needs a calibration
SHIFTED = "Action_Biker.sid"                  # our subtune numbering shifts


def _spy(monkeypatch):
    """Record every siddump invocation the code under test makes."""
    seen = []
    real = fidelity.run_siddump

    def probe(sid, seconds, subtune, exe=fidelity.SIDDUMP, calibrate=0,
              calls=1, video=fidelity._USE_DEFAULT, capture=None):
        seen.append({"file": pathlib.Path(sid).name, "sub": subtune,
                     "cal": calibrate, "calls": calls})
        return real(sid, seconds, subtune, exe, calibrate, calls, video,
                    capture)

    monkeypatch.setattr(fidelity, "run_siddump", probe)
    monkeypatch.setattr(presets.__dict__.setdefault("F", fidelity),
                        "run_siddump", probe, raising=False)
    return seen


def _search(name, monkeypatch, seconds=10):
    """Run the search over a *single* toggle, so the call is affordable.

    The setup under test -- which subtune, which calibration -- happens once
    per file and is what these tests are about; the 31-combination sweep is
    not, and would make this untestable.
    """
    monkeypatch.setattr(presets, "FIDELITY_TOGGLES", ("no_test_restart",))
    seen = _spy(monkeypatch)
    presets.tune_by_fidelity(
        CORPUS / name, {"max_rows": 128, "pack": True, "prune": True,
                        "dedup": True},
        1, siddump, fidelity.GT2RELOC, seconds, log=lambda m: None)
    return seen


@needs_corpus
def test_the_named_files_still_exhibit_what_they_are_here_for():
    """A guard on the fixtures themselves: if the corpus changes so that these
    files no longer have a detuned table or several subtunes, the tests below
    would pass while testing nothing."""
    if not (CORPUS / DETUNED).exists():
        pytest.skip(f"{DETUNED} not in corpus")
    ft = find_freq_table(load_sid(str(CORPUS / DETUNED)))
    assert ft is not None and abs(ft.detune) > 0.2, \
        f"{DETUNED} no longer needs a calibration"
    assert load_sid(str(CORPUS / SHIFTED)).subtunes > 1, \
        f"{SHIFTED} no longer has several subtunes"


@needs_corpus
@needs_tools
def test_the_search_calibrates_the_original_as_the_report_does(monkeypatch):
    """The bug: a hardcoded 0 renamed every note of a detuned original."""
    if not (CORPUS / DETUNED).exists():
        pytest.skip(f"{DETUNED} not in corpus")
    ft = find_freq_table(load_sid(str(CORPUS / DETUNED)))
    want = fidelity.calibration(ft.detune)
    seen = _search(DETUNED, monkeypatch)
    originals = [c for c in seen if c["file"] == "o.sid"]
    assert originals, "the original was never traced"
    assert all(c["cal"] == want for c in originals), \
        f"the search traced the original at {originals[0]['cal']}, not {want}"


@needs_corpus
@needs_tools
def test_the_search_looks_for_our_subtune_counterpart(monkeypatch):
    """The bug: the original's subtune N compared against our N.

    Asserted as "it probes a window", not as "it picks subtune k" -- the
    latter would pin an outcome that legitimately moves when the converter
    changes which subtunes fit, and this is a test about the *method*.
    """
    if not (CORPUS / SHIFTED).exists():
        pytest.skip(f"{SHIFTED} not in corpus")
    seen = _search(SHIFTED, monkeypatch)
    ours = {c["sub"] for c in seen if c["file"] != "o.sid"}
    assert len(ours) > 1, (
        "the search traced only our subtune "
        f"{ours} -- it is not looking for the counterpart")


@needs_corpus
@needs_tools
def test_a_file_needing_neither_is_traced_the_plain_way(monkeypatch):
    """The fixes must not perturb a single-subtune, on-grid file: Commando is
    the anchor everything else in this repo is checked against."""
    seen = _search("Commando.sid", monkeypatch)
    assert all(c["cal"] == 0 for c in seen), "Commando needs no calibration"


# --- v0.5.228: a preset states a measured decision, or nothing --------------

@needs_corpus
def test_a_flag_that_changes_nothing_is_not_recorded():
    """`prune_inert` drops a setting the conversion cannot tell from its default.

    `fidelity_better` is not a total order -- each term can improve while
    another degrades -- so the 31-combination walk is greedy and where it stops
    depends on iteration order. Mega Apocalypse stopped on
    `two_stage sfx_drum wave_program` where `two_stage` was inert, and the
    entry must not claim a flag nothing measured.

    **The inert flag here is no longer `two_stage`.** v0.5.253 read the block
    in this player's own spelling (its per-voice cells are in zero page, so
    `TWO_STAGE_SHAPE`'s `BD ?? ??` / `DE ?? ??` / `9D ?? ??` are `B5 ??` /
    `D6 ??` / `95 ??`), and with the reading in place the flag moves onset
    86% -> 100% and 204 noise frames -- the greedy walk that recorded it was
    right and the detection was missing. `initial_instrument` is inert on this
    file instead, so the example moved rather than the assertion: what is
    being pinned is `prune_inert` dropping a flag the bytes cannot tell from
    its default, whichever flag that currently is.
    """
    P = presets
    sid = CORPUS / "Mega_Apocalypse.sid"
    if not sid.is_file():
        return
    base = {"max_rows": 128, "pack": True, "prune": False, "dedup": True}
    kept = P.prune_inert(sid, base, {"initial_instrument": True,
                                     "sfx_drum": True,
                                     "wave_program": True})
    assert set(kept) == {"sfx_drum", "wave_program"}
    # The flag this test was written about, now that it is read: it changes
    # the bytes, so it survives.
    assert set(P.prune_inert(sid, base, {"two_stage": True})) == {"two_stage"}
    # ...and it drops nothing that does change the bytes, which is what stops
    # this from being a blanket "record less".
    assert set(P.prune_inert(sid, base, {"wave_program": True})) == {
        "wave_program"}
