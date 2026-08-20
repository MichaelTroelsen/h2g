"""The orderlist dialects, and the one whose terminators we had backwards.

`tracks.py`'s version-0 branch read `$FE` as "tune ended" and everything below
it as a pattern number. That is right for most of the family -- it is what
`legalise_restarts` exists for -- and wrong for the three players whose reader
also tests `#$FD`. For those, `$FD` ends a voice's list, and reading it as
pattern 253 let a voice run straight on into the next voice's data.
"""
import pathlib
import sys

from corpus import CORPUS, needs_corpus  # noqa: E402

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[1]))

from h2g.tracks import _build_track  # noqa: E402


@needs_corpus
def test_only_the_players_that_test_fd_are_given_the_rule():
    """Three corpus readers compare `#$FD` within reach of their `$FF` test --
    Knucklebusters, Rasputin and Tarzan. The others never mention it, and
    applying Rasputin's reading to all of version 0 rewrote 23 files and broke
    the byte-exact fixture. Anchored on the reader rather than on the file:
    `CMP #$FD` occurs somewhere in plenty of players."""
    from h2g.convert import _detect_tables
    from h2g.sidfile import load_sid

    found = {}
    for path in sorted(CORPUS.glob("*.sid")):
        try:
            sid, det = _detect_tables(load_sid(str(path)), lambda *a, **k: None)
        except Exception:                              # noqa: BLE001
            continue
        # Only the versions whose branch consults the flag; it is computed
        # for every player and inert elsewhere, which the corpus hash
        # confirms -- exactly three files' bytes move.
        if det.track_fd_ends and det.read_track_version in (0, 1, 3):
            found[path.stem] = det.track_fe_command
    assert set(found) == {"Knucklebusters", "Rasputin", "Tarzan"}, sorted(found)
    # ...and only Rasputin reads `$FE nn` as a two-byte tempo command.
    assert [n for n, fe in found.items() if fe] == ["Rasputin"]


def test_fd_is_a_pattern_number_unless_the_player_tests_it():
    """The flag is the whole difference: the same bytes read two ways."""
    data = bytes([0x05, 0x06, 0xFD, 0x07, 0xFF])
    assert _build_track(data, 0, 0) == [5, 6, 0xFD, 7, 0xFF, 0x00]
    assert _build_track(data, 0, 0, fd_ends=True) == [5, 6, 0xFF, 0xFD]


def test_the_fe_command_consumes_its_operand_and_carries_on():
    """`$FE nn` sets a second gate's reload -- a tempo change mid-orderlist --
    and the list continues. Read as a terminator it emptied Rasputin's voice 2,
    whose list *opens* with one, in every subtune."""
    data = bytes([0xFE, 0x03, 0x01, 0x02, 0xFD])
    assert _build_track(data, 0, 0, fd_ends=True,
                        fe_command=True) == [1, 2, 0xFF, 0xFD]
    # ...and without the flag the same bytes are a tune that ended at once
    assert _build_track(data, 0, 0) == [0xFF, 0xFD]


def test_the_fe_operand_is_never_read_as_a_pattern():
    """The operand of a tempo command is not a pattern number, and an operand
    that happens to be a legal one is exactly how this hides."""
    data = bytes([0x01, 0xFE, 0x09, 0x02, 0xFD])
    assert _build_track(data, 0, 0, fd_ends=True,
                        fe_command=True) == [1, 2, 0xFF, 0xFD]


# The player's init dispatch, per file: header subtunes, the CMP immediate,
# and how many orderlists convert_tracks emitted before the cap existed. Five
# of the eight lose slots; the other three were already right, which is what
# makes the cap a *reading* rather than a tuning -- it agrees with the
# resolving-pointer trim wherever that trim happened to land correctly.
DISPATCH_TRACKS = {
    "Crazy_Comets.sid": (17, 2, 17),
    "Geoff_Capes_Strongman_Challenge.sid": (24, 8, 21),
    "Gerry_the_Germ.sid": (23, 7, 7),
    "Hollywood_or_Bust.sid": (10, 3, 3),
    "Knucklebusters.sid": (11, 3, 3),
    "Spellbound.sid": (13, 3, 13),
    "Thing_on_a_Spring.sid": (17, 1, 13),
    "Warhawk.sid": (18, 9, 18),
}


@needs_corpus
def test_the_dispatch_caps_the_orderlists_a_file_emits():
    """Every file the dispatch is read on emits exactly its music count.

    The `before` column is what the trailing-run trim alone produced, and it
    is right on three files and too generous on five. Recorded so that a
    later change to either rule shows which of the two moved.
    """
    from h2g.convert import _detect_tables
    from h2g.detect import find_music_subtunes
    from h2g.sidfile import load_sid
    from h2g.tracks import convert_tracks

    for name, (declared, music, before) in DISPATCH_TRACKS.items():
        sid, det = _detect_tables(load_sid(str(CORPUS / name)),
                                  lambda *a, **k: None)
        assert sid.subtunes == declared, name
        assert det.music_subtunes == music, name
        tracks = convert_tracks(sid, det, lambda *a, **k: None)
        assert len(tracks) == music * 3, name
        # ...and the same conversion with the dispatch unread is `before`,
        # which is the claim that the cap is what moved these files.
        det.music_subtunes = None
        was = convert_tracks(sid, det, lambda *a, **k: None)
        assert len(was) == before * 3, name
        # The cap only ever removes a trailing run: every orderlist it keeps
        # is the one it kept before, byte for byte. That is what says the
        # music of these files did not change, only how much of the file
        # after it was emitted.
        assert was[:music * 3] == tracks, name
        assert find_music_subtunes(sid) == music, name
