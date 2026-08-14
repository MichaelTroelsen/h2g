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
