"""The subtune census: what became of every subtune a header declares.

`SURVEY.md` says which files convert. It has never said what happened to the
subtunes inside them, and the gap is large: 553 declared across the corpus
against 312 emitted. The census is `survey.py --subtune-census PATH`, and it
reads the record `convert_tracks` fills in as it decides -- not a second pass
re-deriving `_voice_addr`, `command_floor` and `pattern_references` from a
`Detection`, which is the shape this repo has been bitten by before.

Its result is a negative one, which is why the tests below pin the *reasoning*
rather than a number to be improved: the loss is almost entirely subtunes past
the end of a track table that has no length field, and the converter is right
to drop them. See H2G-CONVERSION-METHOD.md § 7.lllll.
"""
import pathlib
import sys

from corpus import CORPUS, needs_corpus  # noqa: E402

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[1]))

from h2g.convert import _detect_tables  # noqa: E402
from h2g.sidfile import load_sid  # noqa: E402
from h2g.tracks import convert_tracks  # noqa: E402

FATES = {"emitted", "placeholder", "trimmed", "beyond_table"}


def _census(name):
    sid, det = _detect_tables(load_sid(str(CORPUS / name)),
                              lambda *a, **k: None)
    rows = []
    tracks = convert_tracks(sid, det, lambda *a, **k: None, census=rows)
    return sid, det, rows, tracks


@needs_corpus
def test_the_census_accounts_for_every_declared_subtune():
    for name in ("Commando.sid", "Warhawk.sid", "BMX_Kidz.sid",
                 "Knucklebusters.sid", "Powerplay_Hockey_USA_vs_USSR.sid"):
        sid, _, rows, _ = _census(name)
        assert len(rows) == sid.subtunes, name
        assert [r["subtune"] for r in rows] == list(range(sid.subtunes)), name
        assert {r["fate"] for r in rows} <= FATES, name


@needs_corpus
def test_emitted_count_matches_the_tracks_actually_returned():
    """The census must agree with the conversion it is a census of."""
    for name in ("Commando.sid", "Warhawk.sid", "Gremlins.sid",
                 "BMX_Kidz.sid"):
        _, _, rows, tracks = _census(name)
        kept = max((r["subtune"] for r in rows
                    if r["fate"] in ("emitted", "placeholder")), default=-1) + 1
        assert kept * 3 == len(tracks), name


@needs_corpus
def test_refs_are_read_before_the_placeholder_reset():
    """The defect the first run of this census had.

    `convert_tracks` replaces a dropped subtune's orderlists with
    DEFAULT_TRACK before the census block is reached, so reading `built` there
    reports that placeholder's three bytes as the subtune's own references.
    Commando's subtune 14 came out as "3 voices, 3 refs, 0 dangling" -- a row
    that cannot exist, because such a subtune would have been emitted. Its
    real reading is 3 refs and 3 dangling.
    """
    _, _, rows, _ = _census("Commando.sid")
    r = next(x for x in rows if x["subtune"] == 14)
    assert r["fate"] != "emitted"
    assert r["voices_ok"] == 3
    assert r["dangling"] == r["refs"] == 3, (
        "a subtune with resolving voices and no dangling reference would "
        "have been emitted -- this is the placeholder being measured")


@needs_corpus
def test_a_resolving_pointer_is_not_evidence_of_music():
    """The finding, pinned on the two files that show it most plainly.

    BMX_Kidz subtune 1 "resolves" one voice, on `$B4FF` -- which is subtune
    0's own voice 0. Warhawk subtune 9 resolves one voice on `$1840`, seven
    bytes below the first real orderlist. Both read a clean set of pattern
    references (56 and 86, none dangling) because a garbage pointer into
    pattern data reads bytes that happen to be small, and a small number is a
    valid pattern index.
    """
    _, _, rows, _ = _census("BMX_Kidz.sid")
    first = next(r for r in rows if r["subtune"] == 0)
    lost = next(r for r in rows if r["subtune"] == 1)
    assert first["fate"] == "emitted"
    assert lost["fate"] != "emitted"
    assert lost["voices_ok"] == 1
    assert lost["dangling"] == 0, "clean references, and still not a subtune"
    # The whole point: its one resolving pointer is a pointer we already have.
    assert lost["pointers"][2] == first["pointers"][0]


@needs_corpus
def test_the_census_changes_no_conversion():
    """An out-parameter, like `transposes` and `tempos` beside it."""
    for name in ("Commando.sid", "Warhawk.sid", "Gremlins.sid"):
        sid, det = _detect_tables(load_sid(str(CORPUS / name)),
                                  lambda *a, **k: None)
        without = convert_tracks(sid, det, lambda *a, **k: None)
        with_it = convert_tracks(sid, det, lambda *a, **k: None, census=[])
        assert without == with_it, name


@needs_corpus
def test_beyond_table_is_reported_for_the_file_that_has_it():
    """Powerplay's header declares ten and its digi track table holds one.

    The other nine are a second player's, reachable with `--engine 1`
    (§ 7.kkkkk) -- and this is the row that says so, rather than nine
    subtunes silently absent.
    """
    sid, _, rows, _ = _census("Powerplay_Hockey_USA_vs_USSR.sid")
    assert sid.subtunes == 10
    beyond = [r for r in rows if r["fate"] == "beyond_table"]
    assert len(beyond) == 9
    assert all(r["subtune"] >= 1 for r in beyond)
