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

FATES = {"emitted", "placeholder", "trimmed", "beyond_table", "sfx"}

# The immediate of each file's `CMP #imm / BCS / JMP` init dispatch: how many
# of its header's subtunes reach the music player at all. Read from the
# player, not fitted to anything -- see detect.find_music_subtunes.
DISPATCH = {
    "Crazy_Comets.sid": (17, 2),
    "Geoff_Capes_Strongman_Challenge.sid": (24, 8),
    "Gerry_the_Germ.sid": (23, 7),
    "Hollywood_or_Bust.sid": (10, 3),
    "Knucklebusters.sid": (11, 3),
    "Spellbound.sid": (13, 3),
    "Thing_on_a_Spring.sid": (17, 1),
    "Warhawk.sid": (18, 9),
}


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


@needs_corpus
def test_the_dispatch_is_read_on_exactly_the_files_that_have_it():
    """The music/sfx split, from the player's own `CMP #imm / BCS / JMP`.

    Anchored at the init entry rather than searched for, because that shape is
    ordinary player code anywhere else in the file. Eight corpus files carry
    it and no other does -- a free search over the whole image would not have
    that property.
    """
    from h2g.detect import find_music_subtunes
    found = {}
    for path in sorted(CORPUS.glob("*.sid")):
        try:
            sid = load_sid(str(path))
        except Exception:                              # noqa: BLE001
            continue
        n = find_music_subtunes(sid)
        if n is not None:
            found[path.name] = (sid.subtunes, n)
    assert found == DISPATCH, sorted(found)


@needs_corpus
def test_knucklebusters_reads_three_subtunes_not_eleven():
    """The file this task is named for: 11 in the header, 3 in the player.

    `1EC3 CMP #$03 / 1EC5 BCS $1ECA / 1EC7 JMP $040D` -- and the eight above
    the split are looked up in `$1EF0`, a table of exactly eight bytes, and
    played by a second engine at $1A00 that never touches the orderlists.
    """
    sid, det, rows, tracks = _census("Knucklebusters.sid")
    assert sid.subtunes == 11
    assert det.music_subtunes == 3
    assert len(tracks) == 3 * 3
    assert [r["subtune"] for r in rows
            if r["fate"] == "sfx"] == list(range(3, 11))


@needs_corpus
def test_the_split_is_where_the_pointer_table_stops_being_a_table():
    """Independent of the CMP: a real row sits beside its neighbours.

    Warhawk's rows 0-8 climb $1847..$1A14 and row 9 is $6C16 $1840 $3C56 --
    the row SUBTUNES.md already singled out as "one pointer resolves, and it
    is still not a subtune". The player's constant names that boundary
    without looking at a single pointer, which is what makes it evidence
    rather than another heuristic.
    """
    sid, det, rows, _ = _census("Warhawk.sid")
    music = [r for r in rows if r["fate"] != "sfx"]
    assert len(music) == det.music_subtunes == 9
    flat = [p for r in music for p in r["pointers"]]
    assert flat == sorted(flat), flat
    assert all(0x1847 <= p <= 0x1A14 for p in flat), flat
    assert [r["subtune"] for r in rows if r["fate"] == "sfx"] == \
        list(range(9, 18))
    # Row 9 read straight out of the table, since a census row for a subtune
    # the cap removed carries no pointers of its own.
    d = sid.data
    row9 = [d[det.track_hi + v + 9 * 6] << 8 | d[det.track_lo + v + 9 * 6]
            for v in range(3)]
    assert row9 == [0x6C16, 0x1840, 0x3C56], [hex(p) for p in row9]


@needs_corpus
def test_the_cap_never_drops_the_subtune_the_header_starts_on():
    """`startSong` is what a player selects when the user selects none, so a
    cap that excluded it would be converting a tune the file does not play.
    Three of the eight start past 1 (Gerry the Germ 7, Hollywood or Bust 3,
    Knucklebusters 2) and all three sit inside their own music range."""
    for name, (_, music) in DISPATCH.items():
        sid = load_sid(str(CORPUS / name))
        assert max(0, sid.start_song - 1) < music, name


@needs_corpus
def test_a_file_without_the_dispatch_is_left_alone():
    """The probe declines rather than guessing: every other player reaches its
    music init unconditionally, and there is then nothing it can say about the
    header's count."""
    for name in ("Commando.sid", "Gremlins.sid", "BMX_Kidz.sid"):
        _, det, rows, _ = _census(name)
        assert det.music_subtunes is None, name
        assert not [r for r in rows if r["fate"] == "sfx"], name
