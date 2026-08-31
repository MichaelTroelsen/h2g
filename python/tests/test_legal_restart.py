"""The restart position Goattracker's exporter refuses (--legal-restart).

Hubbard's `$FE` track byte means "this tune has ended" -- every dialect calls
the player's jump-table entry +3, `LDA #$C0 / STA flag / RTS`, and the play
routine's `BIT flag / BMI` at the top then stops fetching notes (Warhawk
$109F, Last V8 $809B, Saboteur II $F0A2). Goattracker's orderlist has no stop,
so the VB6 original wrote `$FF $FD`: a restart position out of range, which
makes gplay.c:969 call stopsong().

That is right in the editor and fatal everywhere else. greloc.c:244 refuses to
export a song whose restart position is `>= songlen`, and gt2reloc reports the
refusal to a console that does not exist headless -- exit 0, no output, no
file. 28 of the corpus's 78 convertible files were unpackable for this reason
alone, which blocked the whole .sng -> .sid fidelity route for them.

The tests below cover the grammar walk (the restart *operand* is an ordinary
small number and must not be read as anything else), the two shapes that need
fixing, and the invariant that matters: every emitted track satisfies
greloc's own test. Commando is the subject because it carries three such
tracks and is the byte-exact fixture, so the same file proves both that the
option is off by default and that it works when asked for.
"""
import os
import pathlib
import shutil
import subprocess
import sys

import pytest

from h2g.patterns import DEFAULT_TRACK, GT_ORDER_RESTART
from h2g.tracks import ensure_playable_orderlists, legalise_restarts

REPO_ROOT = pathlib.Path(__file__).resolve().parents[2]
PYTHON_ROOT = pathlib.Path(__file__).resolve().parents[1]
SID_PATH = REPO_ROOT / "Commando.sid"
REFERENCE_SNG = REPO_ROOT / "Commando.sng"

STOP_OPERAND = 0xFD     # what _build_track emits for Hubbard's $FE
REPEAT = 0xD0


def _run(sid, out_path, *extra):
    return subprocess.run(
        [sys.executable, "-m", "h2g", str(sid), "-o", str(out_path), "-q", *extra],
        cwd=str(PYTHON_ROOT), capture_output=True, text=True,
    )


def _tracks(blob):
    pos = 4 + 32 * 3
    subtunes = blob[pos]; pos += 1
    out = []
    for _ in range(subtunes * 3):
        length = blob[pos]; pos += 1
        out.append(list(blob[pos:pos + length + 1])); pos += length + 1
    return out


def _greloc_ok(track):
    """greloc.c:244 -- `songorder[songlen+1] >= songlen` is rejected.

    songlen is the index of the first byte >= LOOPSONG (gsong.c:1344), which
    in a finished orderlist can only be the marker itself: pattern numbers are
    below $D0, repeats $D0-$DF and transposes are clamped to $FE.
    """
    songlen = next((i for i, b in enumerate(track) if b == GT_ORDER_RESTART), None)
    if songlen is None or songlen + 1 >= len(track):
        return False
    return track[songlen + 1] < songlen


# --- legalise_restarts: the grammar ---------------------------------------

def test_a_legal_restart_is_left_alone():
    track = [0x00, 0x01, GT_ORDER_RESTART, 0x00]
    assert legalise_restarts([track]) == 0
    assert track == [0x00, 0x01, GT_ORDER_RESTART, 0x00]


def test_the_stop_marker_becomes_a_restart_at_zero():
    track = [0x00, 0x01, 0x02, GT_ORDER_RESTART, STOP_OPERAND]
    assert legalise_restarts([track]) == 1
    assert track == [0x00, 0x01, 0x02, GT_ORDER_RESTART, 0x00]
    assert _greloc_ok(track)


def test_a_track_that_is_only_a_stop_marker_is_left_to_the_other_pass():
    # songlen == 0: there is no position to restart at, so no operand can be
    # legal -- but that failure excludes the subtune from the export instead of
    # failing it, and repairing it must not depend on this opt-in flag.
    # ensure_playable_orderlists owns it, and convert() runs that first.
    # See test_empty_voice.py.
    track = [GT_ORDER_RESTART, 0x00]
    assert legalise_restarts([track]) == 0
    assert track == [GT_ORDER_RESTART, 0x00]
    # ensure_playable_orderlists works a subtune at a time -- three voices, in
    # the order convert_tracks emits them.
    voices = [track, [0x01, GT_ORDER_RESTART, 0x00], [0x01, GT_ORDER_RESTART, 0x00]]
    assert ensure_playable_orderlists(voices) == 1
    assert track == DEFAULT_TRACK
    assert _greloc_ok(track)


def test_a_transpose_before_the_marker_is_not_mistaken_for_it():
    # $FE is the largest transpose the format can hold (+14); the marker is
    # $FF. Scanning for "the first high byte" would cut the walk short here.
    track = [0xFE, 0x03, 0xD2, 0x04, GT_ORDER_RESTART, STOP_OPERAND]
    assert legalise_restarts([track]) == 1
    assert track[:5] == [0xFE, 0x03, 0xD2, 0x04, GT_ORDER_RESTART]
    assert track[5] == 0x00


def test_reports_how_many_tracks_changed():
    logged = []
    n = legalise_restarts(
        [[0x00, GT_ORDER_RESTART, STOP_OPERAND],
         [0x00, GT_ORDER_RESTART, 0x00],
         [0x01, 0x02, GT_ORDER_RESTART, 0x09]],
        logged.append)
    assert n == 2
    assert logged and "2 track(s)" in logged[0]


# --- end to end ------------------------------------------------------------

def test_default_is_off_and_byte_exact(tmp_path):
    out = tmp_path / "d.sng"
    assert _run(SID_PATH, out).returncode == 0
    assert out.read_bytes() == REFERENCE_SNG.read_bytes()


def test_the_fixture_is_unexportable_without_the_option():
    # The premise of the whole option. If this ever stops holding, the option
    # has become dead code rather than the tests having become wrong.
    bad = [t for t in _tracks(REFERENCE_SNG.read_bytes()) if not _greloc_ok(t)]
    assert len(bad) == 3


def test_only_the_restart_operands_change(tmp_path):
    out = tmp_path / "f.sng"
    assert _run(SID_PATH, out, "--legal-restart").returncode == 0
    ref, fixed = REFERENCE_SNG.read_bytes(), out.read_bytes()
    assert len(ref) == len(fixed), "the option must not resize anything"
    diff = [i for i in range(len(ref)) if ref[i] != fixed[i]]
    assert len(diff) == 3
    assert all(ref[i] == STOP_OPERAND and fixed[i] == 0x00 for i in diff)


def test_every_track_satisfies_greloc(tmp_path):
    out = tmp_path / "g.sng"
    assert _run(SID_PATH, out, "--legal-restart").returncode == 0
    assert all(_greloc_ok(t) for t in _tracks(out.read_bytes()))


def test_the_music_before_the_loop_is_untouched(tmp_path):
    # Only where the song restarts changes; which patterns it plays on the way
    # there must not.
    out = tmp_path / "h.sng"
    assert _run(SID_PATH, out, "--legal-restart").returncode == 0

    def prefix(track):
        return track[:track.index(GT_ORDER_RESTART)]

    ref = [prefix(t) for t in _tracks(REFERENCE_SNG.read_bytes())]
    assert [prefix(t) for t in _tracks(out.read_bytes())] == ref


def test_composes_with_the_orderlist_options(tmp_path):
    # pack, merge and split all change an orderlist's length, and whether a
    # restart position is in range is a question about the finished list --
    # so the fix has to run after them, not in _build_track.
    out = tmp_path / "i.sng"
    r = _run(SID_PATH, out, "--legal-restart", "--pack-repeats",
             "--prune-patterns", "--max-rows", "128", "--format", "gts5")
    assert r.returncode == 0, r.stderr
    assert all(_greloc_ok(t) for t in _tracks(out.read_bytes()))


# --- against the real exporter --------------------------------------------

GT2RELOC = os.environ.get("H2G_GT2RELOC") or shutil.which("gt2reloc")


@pytest.mark.skipif(not GT2RELOC, reason="set H2G_GT2RELOC to gt2reloc.exe")
@pytest.mark.parametrize("opts,expect_sid", [((), False), (("--legal-restart",), True)])
def test_gt2reloc_packs_only_the_fixed_file(tmp_path, opts, expect_sid):
    """The end the option exists for: a .sid that gt2reloc actually writes.

    Never the exit code -- gt2reloc opens its STDOUT/STDERR as fopen("CON")
    (gt2reloc.c:130), so a refusal is exit 0 with no output. The written file
    is the only signal. Bare filenames with cwd set, because argv[1] is
    strcpy'd into a 60-byte buffer.
    """
    sng, sid = tmp_path / "t.sng", tmp_path / "t.sid"
    assert _run(SID_PATH, sng, "--format", "gts5", *opts).returncode == 0
    subprocess.run([GT2RELOC, sng.name, sid.name], cwd=str(tmp_path),
                   capture_output=True, timeout=120)
    assert sid.exists() == expect_sid


def test_force_park_parks_a_track_whose_restart_is_already_legal():
    """The one thing `--silent-park` cannot do.

    `legalise_restarts` acts on an OUT-OF-RANGE restart, which convert_tracks
    writes only for Hubbard's `$FE`. A tune that ends and never says so keeps a
    legal restart 0 and plays forever -- Confuzion's track region is six bytes
    with no `$FE` in it at all.
    """
    from h2g.tracks import legalise_restarts, SILENT_PATTERN
    from h2g.patterns import GT_ORDER_RESTART

    def track():                       # three positions, restart 0: legal
        return [1, 2, 3, GT_ORDER_RESTART, 0]

    # Without the flag a legal restart is left exactly alone.
    pats = [[0] * 8]
    t = [track()]
    assert legalise_restarts(t, None, pats, force_park=False) == 0
    assert t[0] == [1, 2, 3, GT_ORDER_RESTART, 0]
    assert len(pats) == 1

    # With it, a silent pattern is appended and the restart points AT it, so
    # the orderlist loops something that makes no sound.
    pats = [[0] * 8]
    t = [track()]
    assert legalise_restarts(t, None, pats, force_park=True) == 1
    assert len(pats) == 2, "the silent pattern must be appended"
    assert pats[1] == list(SILENT_PATTERN)
    songlen = t[0].index(GT_ORDER_RESTART)
    assert t[0][songlen - 1] == 1, "the silent pattern is the last position"
    assert t[0][songlen + 1] == songlen - 1, "restart points at the silent entry"
    assert t[0][:3] == [1, 2, 3], "the tune's own positions are untouched"


def test_force_park_needs_the_pattern_table_like_silent_park_does():
    """No pattern table means no silent pattern to park on, so it declines
    rather than inventing one -- the same refusal `silent_park` makes."""
    from h2g.tracks import legalise_restarts
    from h2g.patterns import GT_ORDER_RESTART
    t = [[1, 2, 3, GT_ORDER_RESTART, 0]]
    assert legalise_restarts(t, None, None, force_park=True) == 0
    assert t[0] == [1, 2, 3, GT_ORDER_RESTART, 0]


def _pat(rows):
    """A pattern of `rows` sounding rows, then ENDPATT."""
    from h2g.patterns import GT_END_PATTERN
    return [0, 0, 0, 0] * rows + [GT_END_PATTERN, 0, 0, 0]


def test_voice_rows_counts_rows_not_orderlist_entries():
    """An entry COUNT is not a duration -- repeats multiply and transposes
    occupy no step. Reading Confuzion's 36/163/39 entries as one voice being
    four times another was exactly that mistake; its voices span an identical
    5216 rows."""
    from h2g.tracks import voice_rows
    from h2g.patterns import GT_ORDER_RESTART, GT_REPEAT, GT_TRANSPOSE_DOWN
    pats = [_pat(4), _pat(10)]
    assert voice_rows([0, 1, GT_ORDER_RESTART, 0], pats) == 14
    # one entry, repeated three times, is three patterns' worth of rows
    assert voice_rows([GT_REPEAT + 2, 0, GT_ORDER_RESTART, 0], pats) == 12
    # a transpose is not a step
    assert voice_rows([GT_TRANSPOSE_DOWN, 0, GT_ORDER_RESTART, 0], pats) == 4


def test_force_park_declines_a_subtune_whose_voices_do_not_end_together():
    """The safety condition, which went unchecked from v0.5.431 to v0.5.433.

    Parking puts each voice on a silent pattern at the end of its OWN
    orderlist, which ends the tune only if they finish together. Where one is
    shorter it is currently looping and playing on under the others; parking
    it silences it early. Measured over the corpus, **76 of 237 subtunes in 28
    files** have voices that do not end together, so this is the common case
    rather than a corner.
    """
    from h2g.tracks import legalise_restarts, voices_end_together
    from h2g.patterns import GT_ORDER_RESTART
    pats = [_pat(4), _pat(8)]

    even = [[0, 0, GT_ORDER_RESTART, 0] for _ in range(3)]      # 8 rows each
    odd = [[0, 0, GT_ORDER_RESTART, 0], [0, 0, GT_ORDER_RESTART, 0],
           [0, GT_ORDER_RESTART, 0]]                            # 8, 8, 4
    assert voices_end_together(even, pats)
    assert not voices_end_together(odd, pats)

    t = [list(x) for x in even] + [list(x) for x in odd]
    n = legalise_restarts(t, None, [list(p) for p in pats], force_park=True)
    assert n == 3, f"only the even subtune's three voices may park, got {n}"
    for v in t[:3]:
        assert v.index(GT_ORDER_RESTART) == 3, "the even subtune parked"
    for v in t[3:]:
        assert v[v.index(GT_ORDER_RESTART) + 1] == 0, \
            "the uneven subtune must be left looping from the top"


def test_the_end_together_test_is_taken_before_anything_is_parked():
    """Parking APPENDS a position, so a group tested track by track reads
    [8, 8, 8] for its first voice and [12, 8, 8] for its second -- the guard
    would decline the very voices it had just made unequal.

    That is not hypothetical: computed inside the loop it parked Confuzion's
    voice 0 alone and moved the shipped bytes (246c879a020a -> 7654033d8806).
    """
    from h2g.tracks import legalise_restarts
    from h2g.patterns import GT_ORDER_RESTART
    pats = [_pat(8)]
    t = [[0, GT_ORDER_RESTART, 0] for _ in range(3)]
    n = legalise_restarts(t, None, [list(p) for p in pats], force_park=True)
    assert n == 3, f"all three voices must park, not just the first -- got {n}"
