"""The command-table engine's `$85 nn` transpose, lifted into the orderlist.

Chicken Song and Hollywood or Bust set a per-voice transpose from INSIDE a
pattern: command `$85 nn` stores its operand in a cell the note fetch adds to
every note (`AND #$7F / CLC / ADC cell,X` -- Hollywood $04F0, Chicken Song
$10E7; handlers $0896 / $1479). `_build_raw_pattern_cmdtable` consumed the
operand for length and dropped it, so Hollywood's subtune 2 voice 0 played
207 notes an octave high and Chicken Song's voice 0 played 504 notes 9 or 12
semitones low.

The cell has Goattracker's own `trans` semantics -- assigned, per voice,
persisting across patterns and across the restart -- so the conversion emits
it as an orderlist transpose byte ($E0-$FE) before every reference whose
pattern assigns one (`tracks._build_track`, version 11). No pattern is
copied. Version 0's command floor is $FF, under which `reindex_tracks` drops
a transpose byte as a dangling reference, so a file whose `cmd_transpose` is
found reads as track version 11 with the floor at `GT_TRANSPOSE_DOWN`
(`patterns.command_floor`).

Measured at v0.5.486 on the two files at -t 180 under presets.json: melody
59 -> 61% (Chicken Song) and 52 -> 61% (Hollywood), and `--diagnose` reads
both voice 0s as "different music" before and "matches" after (pitches 67 ->
83% and 77 -> 80% the same). The corpus byte-hash moves exactly these two.
"""
import json
import pathlib
import sys

import pytest

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[1]))

from corpus import CORPUS, needs_corpus  # noqa: E402
from h2g.convert import _detect_tables, convert  # noqa: E402
from h2g.detect import detect  # noqa: E402
from h2g.patterns import (GT_FIRSTNOTE, GT_LASTNOTE, GT_ORDER_RESTART,  # noqa: E402
                          GT_REPEAT, GT_TRANSPOSE_DOWN, GT_TRANSPOSE_UP,
                          cmdtable_transposes, command_floor)
from h2g.sidfile import load_sid  # noqa: E402
from h2g.tracks import convert_tracks  # noqa: E402

PRESETS = pathlib.Path(__file__).resolve().parents[2] / "presets.json"
CHICKEN = CORPUS / "Chicken_Song.sid"
HOLLYWOOD = CORPUS / "Hollywood_or_Bust.sid"

# Read off the two players (see the module docstring): the command index and
# what each pattern that uses it assigns, as (entry, exit) signed semitones.
CHICKEN_TX = {12: (0, 0), 18: (0, 0), 19: (9, 9), 20: (12, 12), 31: (0, 0)}
HOLLYWOOD_TX = {16: (0, 0), 33: (0, 0), 34: (-12, -12)}


def _quiet(*_a, **_k):
    pass


def _preset_opts(name: str) -> dict:
    sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[1]))
    import fidelity as F
    doc = json.loads(PRESETS.read_text(encoding="utf-8"))
    return F._preset_opts(doc, name)


@needs_corpus
def test_exactly_the_two_cmdtable_files_carry_the_transpose_command():
    """Census over the corpus: the fetch-plus-handler pair is found in the two
    files and nowhere else, it is command $85 in both, and finding it is what
    moves a file to track version 11 -- no other file's version changes."""
    found = {}
    versions = {}
    for path in sorted(CORPUS.glob("*.sid")):
        try:
            _sid, det = _detect_tables(load_sid(str(path)), _quiet)
        except Exception:                              # noqa: BLE001
            continue
        versions[path.stem] = det.read_track_version
        if det.cmd_transpose >= 0:
            found[path.stem] = det.cmd_transpose
    assert found == {"Chicken_Song": 5, "Hollywood_or_Bust": 5}, found
    assert {n for n, v in versions.items() if v == 11} == set(found)


def test_version_11_puts_the_floor_at_goattrackers_transpose_range():
    """Hollywood's -12 is $E4, below the version-2 family's $F0 floor; version
    0's own floor is $FF, under which reindex_tracks drops every transpose."""
    assert command_floor(11) == GT_TRANSPOSE_DOWN
    assert command_floor(0) == GT_ORDER_RESTART


@needs_corpus
def test_the_patterns_that_assign_a_transpose_and_what_they_assign():
    """Per pattern, signed: Hollywood's operand is $F4, and the player adds it
    8-bit, so it is -12 and not +244."""
    for path, want in ((CHICKEN, CHICKEN_TX), (HOLLYWOOD, HOLLYWOOD_TX)):
        sid = load_sid(str(path))
        det = detect(sid, log=_quiet)
        assert det.read_track_version == 11
        lines: list = []
        assert cmdtable_transposes(sid, det, lines.append) == want, path.stem
        # No use of the command sits after a note, so nothing is logged as
        # inexpressible -- Chicken Song's pattern 31 has it after a REST.
        assert not any("AFTER THEIR FIRST NOTE" in s for s in lines), lines


@needs_corpus
def test_the_raw_orderlists_carry_a_transpose_before_every_assigning_pattern():
    """Hollywood subtune 2 voice 0 (track 6) enters patterns 34 under -12 and
    16/33 under 0; Chicken Song voice 0 enters 19 under +9 and 20 under +12.
    Every reference to an assigning pattern gets its byte, whether or not the
    value changed -- the loop can arrive carrying anything."""
    sid = load_sid(str(HOLLYWOOD))
    det = detect(sid, log=_quiet)
    tracks = convert_tracks(sid, det, _quiet)
    t = tracks[6]
    pairs = [(t[i - 1], t[i]) for i in range(1, len(t))
             if GT_TRANSPOSE_DOWN <= t[i - 1] < GT_ORDER_RESTART]
    assert set(pairs) == {(GT_TRANSPOSE_UP - 12, 34), (GT_TRANSPOSE_UP, 16),
                          (GT_TRANSPOSE_UP, 33)}, pairs
    assert len(pairs) == t.count(34) + t.count(16) + t.count(33) == 8
    # The other subtunes' voices never reach an assigning pattern: no byte.
    for k, tr in enumerate(tracks):
        if k != 6:
            assert not any(GT_TRANSPOSE_DOWN <= b < GT_ORDER_RESTART
                           for b in tr[:-2]), (k, tr)

    sid = load_sid(str(CHICKEN))
    det = detect(sid, log=_quiet)
    t = convert_tracks(sid, det, _quiet)[0]
    pairs = [(t[i - 1], t[i]) for i in range(1, len(t))
             if GT_TRANSPOSE_DOWN <= t[i - 1] < GT_ORDER_RESTART]
    assert set(pairs) == {(GT_TRANSPOSE_UP + 9, 19), (GT_TRANSPOSE_UP + 12, 20),
                          (GT_TRANSPOSE_UP, 18), (GT_TRANSPOSE_UP, 12),
                          (GT_TRANSPOSE_UP, 31)}, pairs


def _notes_under_transpose(blob: bytes, voice: int):
    """{trans: notes} for one .sng track, walked as gplay.c walks an orderlist
    step -- [transpose][repeat][pattern] -- with `trans` persisting until the
    next transpose byte. Repeats play a pattern `n + 1` times."""
    import songview
    song = songview.parse_sng(blob)
    track = song.tracks[voice]
    out: dict = {}
    trans = 0
    times = 1
    for b in track:
        if b == GT_ORDER_RESTART:
            break
        if b >= GT_TRANSPOSE_DOWN:
            trans = b - GT_TRANSPOSE_UP
            continue
        if b >= GT_REPEAT:
            times = b - GT_REPEAT + 1
            continue
        pat = song.patterns[b]
        notes = sum(1 for k in range(0, len(pat), 4)
                    if GT_FIRSTNOTE <= pat[k] <= GT_LASTNOTE)
        out[trans] = out.get(trans, 0) + notes * times
        times = 1
    return out


@needs_corpus
def test_the_finished_sng_plays_the_measured_notes_under_the_transpose():
    """On the .sng the presets produce -- so through prune, dedup, pack,
    slicing at 128 rows and reindexing, which is where a version-0 floor
    would have dropped the bytes -- Hollywood subtune 2 voice 0 plays 207
    notes at -12 and Chicken Song voice 0 plays 162 at +9 and 342 at +12,
    the counts the play-order walk of the originals gave."""
    blob = convert(str(HOLLYWOOD), log=_quiet, **_preset_opts("Hollywood_or_Bust.sid"))
    got = _notes_under_transpose(blob, 6)
    assert got.get(-12) == 207, got
    assert set(got) == {0, -12}, got

    blob = convert(str(CHICKEN), log=_quiet, **_preset_opts("Chicken_Song.sid"))
    got = _notes_under_transpose(blob, 0)
    assert got.get(9) == 162 and got.get(12) == 342, got
    assert set(got) == {0, 9, 12}, got


@needs_corpus
def test_nothing_but_the_two_orderlists_moves():
    """The A/B the change was adopted on, pinned at the file level: with the
    command not found, the same conversion differs only in the transposed
    voices' orderlists -- every pattern byte, instrument and table is the
    same. Detected through `cmd_transpose` alone, so the version stays 0 and
    the floor $FF, which is the old behaviour byte for byte."""
    import h2g.detect as D
    import songview

    for path, name, voices in ((HOLLYWOOD, "Hollywood_or_Bust.sid", {6}),
                               (CHICKEN, "Chicken_Song.sid", {0})):
        opts = _preset_opts(name)
        with_tx = songview.parse_sng(convert(str(path), log=_quiet, **opts))
        real = D._cmdtable_transpose
        try:
            D._cmdtable_transpose = lambda *a, **k: -1
            without = songview.parse_sng(convert(str(path), log=_quiet, **opts))
        finally:
            D._cmdtable_transpose = real
        assert with_tx.patterns == without.patterns
        assert with_tx.instruments == without.instruments
        assert with_tx.tables == without.tables
        moved = {v for v, (a, b) in enumerate(zip(with_tx.tracks, without.tracks))
                 if a != b}
        assert moved == voices, (name, moved)
        assert len(with_tx.tracks) == len(without.tracks)
