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
# name -> (header count, the dispatch's music count, what the LAYOUT bound
# alone gives). The third column is `track_table_extent` with the dispatch
# switched off, not the header: since the two bounds landed on master together
# the old "unbounded" figure is unreachable, and the interesting comparison is
# between the two bounds rather than between one bound and none.
DISPATCH_TRACKS = {
    "Crazy_Comets.sid": (17, 2, 2),
    "Geoff_Capes_Strongman_Challenge.sid": (24, 8, 8),
    "Gerry_the_Germ.sid": (23, 7, 7),
    "Hollywood_or_Bust.sid": (10, 3, 3),
    "Knucklebusters.sid": (11, 3, 3),
    # Spellbound's layout bound read 4 until the selector signature stopped
    # encoding an addressing mode: its track table is the six bytes at $E6B6,
    # and the $E6B0 the chain used to name is the scratch buffer the player
    # copies each subtune's six pointers INTO. Reading the table one entry
    # early gave the layout one more row to fit, and disagreed with the
    # dispatch. Now both say 3.
    "Spellbound.sid": (13, 3, 3),
    "Thing_on_a_Spring.sid": (17, 1, 1),
    "Warhawk.sid": (18, 9, 9),
}


@needs_corpus
def test_the_dispatch_caps_the_orderlists_a_file_emits():
    """Every file the dispatch is read on emits exactly its music count.

    Two bounds now cap this count and they were derived independently -- this
    one by reading the player's `CMP #imm / BCS / JMP` init dispatch, the
    other (`tracks.track_table_extent`) by reading where the track table runs
    into the pattern table. They AGREE on all eight files that have both,
    which is mutual corroboration rather than redundancy: two different
    methods, one answer.

    Spellbound used to be the one disagreement -- layout 4 against dispatch 3
    -- and the disagreement turned out to be a third defect rather than a
    difference of kind: the selector signature read the six-byte scratch
    buffer at $E6B0 as the table instead of the table at $E6B6, so the layout
    was measuring a table that started one entry early and had room for one
    row more. Correcting the base made the two agree without either rule
    being touched. A standing disagreement between two independent readings
    is a lead, not a tie to be broken by preference.

    So the third column is the LAYOUT bound alone, not the header. Where it
    equals the music count the dispatch changes no bytes and earns its place
    by attribution instead: the census fate is `sfx` rather than
    `beyond_table`, which is what SUBTUNES.md reports. Nothing is load-bearing
    on the dispatch alone today, and this test is what says which of the two
    moved if either rule changes.
    """
    from h2g.convert import _detect_tables
    from h2g.detect import find_music_subtunes
    from h2g.sidfile import load_sid
    from h2g.tracks import convert_tracks

    import dataclasses
    agreed = 0
    for name, (declared, music, extent_only) in DISPATCH_TRACKS.items():
        sid, det = _detect_tables(load_sid(str(CORPUS / name)),
                                  lambda *a, **k: None)
        assert sid.subtunes == declared, name
        assert det.music_subtunes == music, name
        tracks = convert_tracks(sid, det, lambda *a, **k: None)
        assert len(tracks) == music * 3, name
        # ...and the same conversion with the dispatch unread falls back to
        # the layout bound alone. Switch it off on a COPY: `det` is reused
        # below and mutating it here once made this test measure itself.
        without = dataclasses.replace(det, music_subtunes=None)
        was = convert_tracks(sid, without, lambda *a, **k: None)
        assert len(was) == extent_only * 3, name
        assert extent_only >= music, name    # the dispatch is never looser
        agreed += extent_only == music
        # The cap only ever removes a trailing run: every orderlist it keeps
        # is the one it kept before, byte for byte. That is what says the
        # music of these files did not change, only how much of the file
        # after it was emitted.
        assert was[:music * 3] == tracks, name
        assert find_music_subtunes(sid) == music, name
    # Two independent methods, one answer, on all eight. If this number falls,
    # the two bounds have started disagreeing and one of them has drifted --
    # that is the signal, not the individual file counts.
    assert agreed == 8, agreed


# --- parking a finished tune on silence -----------------------------------
#
# Hubbard's `$FE` means TUNE ENDED. A Goattracker orderlist has no "stop", so
# `legalise_restarts` rewrites the out-of-range restart position to 0 and the
# tune loops from the top instead of ending -- which is what makes the file
# packable and also why every such tune plays forever. `len` reads Action
# Biker at >+120.5s past its original's ending over a 180s trace, with 856
# attacks against the original's 291.
#
# Given the pattern table, the same pass parks the track on a SILENT pattern
# appended to its own orderlist. An orderlist still cannot say "stop", but it
# can loop something that makes no sound.

def _ended_track(entries):
    """An orderlist ending the way convert_tracks writes a `$FE`."""
    return list(entries) + [0xFF, 0xFD]


def test_without_the_pattern_table_the_restart_is_still_zeroed():
    """The behaviour every caller had before, unchanged when `patterns` is
    not passed -- this is what keeps the option opt-in."""
    from h2g.tracks import legalise_restarts
    track = _ended_track([0, 1, 2])
    assert legalise_restarts([track]) == 1
    assert track == [0, 1, 2, 0xFF, 0x00]


def test_given_the_pattern_table_the_track_parks_on_silence():
    from h2g.tracks import SILENT_PATTERN, legalise_restarts
    patterns = [[0] * 8, [0] * 8]
    track = _ended_track([0, 1, 0])
    assert legalise_restarts([track], None, patterns) == 1
    # the silent pattern was appended to the table ...
    assert patterns[-1] == SILENT_PATTERN
    silent = len(patterns) - 1
    # ... its number sits at the end of the orderlist, and the restart names it
    assert track == [0, 1, 0, silent, 0xFF, 3]
    assert track[track.index(0xFF) + 1] == 3, "restart does not name the park"


def test_one_silent_pattern_serves_every_parked_track():
    """It carries no per-track state, so a copy each would spend pattern slots
    for nothing. Auf Wiedersehen Monty parks 36 tracks."""
    from h2g.tracks import legalise_restarts
    patterns = [[0] * 8]
    tracks = [_ended_track([0]), _ended_track([0, 0]), _ended_track([0, 0, 0])]
    assert legalise_restarts(tracks, None, patterns) == 3
    assert len(patterns) == 2, "more than one silent pattern was created"
    for t in tracks:
        assert t[t.index(0xFF) + 1] == t.index(0xFF) - 1


def test_a_track_at_the_length_limit_falls_back_to_restart_zero():
    """Parking costs one orderlist position. A track with no room for it must
    still be legalised -- an unpackable file is worse than a looping one."""
    from h2g.patterns import MAX_TRACK_LEN
    from h2g.tracks import legalise_restarts
    patterns = [[0] * 8]
    track = [0] * (MAX_TRACK_LEN - 2) + [0xFF, 0xFD]
    assert len(track) >= MAX_TRACK_LEN
    assert legalise_restarts([track], None, patterns) == 1
    assert track[-1] == 0, "it should have fallen back to restart 0"
    assert len(patterns) == 1, "a silent pattern was spent on a track with no room"


def test_a_track_that_already_loops_is_left_alone_either_way():
    """Parking is for tracks that ENDED. A legal restart is a real loop the
    composer wrote, and touching it would silence music the player plays."""
    from h2g.tracks import legalise_restarts
    patterns = [[0] * 8]
    track = [0, 1, 2, 0xFF, 0x01]
    assert legalise_restarts([track], None, patterns) == 0
    assert track == [0, 1, 2, 0xFF, 0x01]
    assert len(patterns) == 1


def test_the_silent_park_declines_when_the_pattern_table_is_full():
    """W_A_R converts to exactly 208 patterns -- Goattracker's MAX_PATT -- and
    appending a silent pattern took it to 209.

    gt2reloc packs 209 without a word, so nothing reported it: the file was
    produced, the suite was green, and the packed player then ran subtune 0 at
    its default tick instead of the CMD_SETTEMPO on row 0 of the pattern its
    orderlist enters on. melody read 18.6% against 100% with the park declined.
    """
    from h2g.patterns import MAX_PATTERNS
    from h2g.tracks import (GT_END_PATTERN, GT_ORDER_RESTART,
                            legalise_restarts)

    # one track ending on the $FE marker, and a pattern table already full
    patterns = [[0x60, 0, 0, 0, GT_END_PATTERN, 0, 0, 0]
                for _ in range(MAX_PATTERNS)]
    tracks = [[0, GT_ORDER_RESTART, 0xFF], [], []]
    fixed = legalise_restarts(tracks, None, patterns)

    assert fixed == 1, "the illegal restart still has to be repaired"
    assert len(patterns) == MAX_PATTERNS, (
        f"emitted {len(patterns)} patterns, one past Goattracker's "
        f"{MAX_PATTERNS} limit")
    assert tracks[0][-1] == 0, "with no slot to park in, it restarts at 0"


def test_the_silent_park_still_happens_with_one_slot_left():
    """The guard is `< MAX_PATTERNS`, not a blanket refusal: a file with room
    for the silent pattern must still get it."""
    from h2g.patterns import MAX_PATTERNS
    from h2g.tracks import (GT_END_PATTERN, GT_ORDER_RESTART,
                            legalise_restarts)

    patterns = [[0x60, 0, 0, 0, GT_END_PATTERN, 0, 0, 0]
                for _ in range(MAX_PATTERNS - 1)]
    tracks = [[0, GT_ORDER_RESTART, 0xFF], [], []]
    legalise_restarts(tracks, None, patterns)
    assert len(patterns) == MAX_PATTERNS, "the one free slot should be used"


def test_one_silent_pattern_serves_every_parked_track_at_the_boundary():
    """The pattern is allocated once, so a second parked track must not be
    refused merely because the table is full AFTER the first allocation."""
    from h2g.patterns import MAX_PATTERNS
    from h2g.tracks import (GT_END_PATTERN, GT_ORDER_RESTART,
                            legalise_restarts)

    patterns = [[0x60, 0, 0, 0, GT_END_PATTERN, 0, 0, 0]
                for _ in range(MAX_PATTERNS - 1)]
    tracks = [[0, GT_ORDER_RESTART, 0xFF], [1, GT_ORDER_RESTART, 0xFF], []]
    legalise_restarts(tracks, None, patterns)
    assert len(patterns) == MAX_PATTERNS, "still exactly one silent pattern"
    parked = [t for t in tracks[:2] if t and t[-1] != 0]
    assert len(parked) == 2, "both tracks park on the one silent pattern"


def test_a_parked_track_loops_on_silence_rather_than_restarting_at_zero():
    """The property the +-5 s length rule actually rests on.

    The two tests above pin the MAX_PATTERNS boundary -- whether a pattern is
    appended at all. Neither asks the question the rule cares about: that the
    thing parked ON makes no sound, and that the restart operand points AT it
    rather than at position 0. Both were true before this test and neither was
    checked, so a change that parked on the wrong position, or on a pattern
    carrying a note, would have kept both existing tests green while every
    tune played forever again.

    Measured at v0.5.461, `-t 180`, this one flag: Action_Biker ends at 59.68 s
    against its original's 59.54 with the park, and NEVER STOPS without it
    (`length_delta >= +120.46`, `length_bounded`), with an identical 291
    attacks in both arms.
    """
    from h2g.tracks import (GT_END_PATTERN, GT_KEYOFF, GT_ORDER_RESTART,
                            SILENT_PATTERN, legalise_restarts)

    patterns = [[0x60, 1, 0, 0, GT_END_PATTERN, 0, 0, 0]]
    # position 0 plays pattern 0, then LOOPSONG with an out-of-range operand
    tracks = [[0, GT_ORDER_RESTART, 0xFF], [], []]
    assert legalise_restarts(tracks, None, patterns) == 1

    track = tracks[0]
    songlen = track.index(GT_ORDER_RESTART)
    assert songlen == 2, ("the silent pattern is an appended POSITION, so the "
                          f"orderlist grows from 1 to 2 entries, got {track}")
    parked_at = songlen - 1                      # the entry the park inserted
    assert track[parked_at] == len(patterns) - 1, (
        "the parked position must name the pattern that was just appended")
    assert track[songlen + 1] == parked_at, (
        f"the restart must point at the parked entry, not at {track[songlen + 1]}")
    assert track[songlen + 1] != 0, (
        "restart 0 is the workaround this branch exists to replace")

    # And the pattern parked on has to be silent -- a KEYOFF and nothing else.
    parked = patterns[-1]
    assert parked == list(SILENT_PATTERN), parked
    assert parked[0] == GT_KEYOFF and parked[1] == 0, (
        "a parked pattern that names a note or an instrument sounds")
    assert parked[4] == GT_END_PATTERN, "and it has to end after that one row"
