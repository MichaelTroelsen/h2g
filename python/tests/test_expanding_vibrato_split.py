"""A pattern the swell is wanted on by some orderlist positions and not others.

Opened by expanding-vibrato-post-onset-swing: Mega_Apocalypse pattern $0F is
eighty hold rows of rests after notes that name no instrument. Voice 1 enters
it holding slot 4 (`$09B7`, a swell), voice 3 holding 1 or 2 (plain); a pass
writes a row only where every position reaching it wants the same entry (a
`4xy` or a wavetable loop shakes whatever instrument is sounding), so the two
never agreed and slot 4's long low notes swung 28 units against the original's
1634. `expanding_vibrato_split` copies the pattern per distinct set of rows its
positions want and repoints the positions.
"""
import json
import pathlib
import sys

import pytest

PYTHON_ROOT = pathlib.Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PYTHON_ROOT))
sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent))

from corpus import CORPUS, needs_corpus  # noqa: E402
from h2g.goatwriter.constants import (CMD_SETWAVEPTR, CMD_TONEPORTA,  # noqa: E402
                                      CMD_VIBRATO)
from h2g.goatwriter.note_passes import (  # noqa: E402
    _expanding_vibrato_loop_share, _expanding_vibrato_loops,
    _expanding_vibrato_pass, expanding_vibrato_split)
from test_expanding_vibrato_loops import (END, PROGRAM, _AgeSid, _det,  # noqa: E402
                                          _hold, _note)

ROWS = 14                       # hold rows in the shared pattern
ARGS = dict(vib_ptrs={0: (1, 2)}, speed_table=None, lead=0, multiplier=1,
            row_calls=3)


def _pat(rows):
    return [b for row in rows for b in row] + [END, 0, 0, 0]


def _world(entering, restart=False):
    """Patterns 0 (a note on slot 1, the swell), 1 (a note on slot 2, plain)
    and 2 (`ROWS` hold rows naming no instrument); one orderlist per entry of
    `entering`, each `[note pattern, 2, FF 0]`."""
    patterns = [_pat([_note(0xB3, 1)]), _pat([_note(0xB3, 2)]),
                _pat([_hold() for _ in range(ROWS)])]
    tracks = [[entering_pat, 2, 0xFF, 0] for entering_pat in entering]
    return tracks, patterns


def _split(tracks, patterns, **kw):
    sid, det = _AgeSid(), _det(7)
    args = dict(ARGS, speed_table=[(0x81, 3)])
    args.update(kw)
    return expanding_vibrato_split(sid, det, tracks, patterns, **args)


def _cmds(pat, n):
    return [(pat[i + 2], pat[i + 3]) for i in range(0, 4 * n, 4)]


def test_a_pattern_entered_on_a_swell_and_on_a_plain_instrument_is_copied():
    tracks, patterns = _world([0, 1])
    before = ([list(t) for t in tracks], [list(p) for p in patterns])
    t2, p2, copies = _split(tracks, patterns)
    assert (tracks, patterns) == before, "the arguments are not touched"
    assert copies == {3: 2} and len(p2) == 4 and p2[3] == p2[2]
    # The plain position keeps the source; the swelling one is repointed.
    assert t2[0][1] == 3 and t2[1][1] == 2


def test_the_copy_gets_the_commands_and_the_source_none():
    tracks, patterns = _world([0, 1])
    sid, det = _AgeSid(), _det(7)
    table = [(0x81, 3)]
    t2, p2, copies = _split(tracks, patterns)
    written = _expanding_vibrato_pass(sid, det, t2, p2, {0: (1, 2)}, table,
                                      0, 1, 3)
    assert written > 0
    assert any(c == CMD_VIBRATO for c, _ in _cmds(p2[3], ROWS))
    assert all(c == 0 for c, _ in _cmds(p2[2], ROWS))
    # Without the split the pass has nothing it can write: the positions
    # disagree on every row.
    p_whole = [list(p) for p in patterns]
    assert _expanding_vibrato_pass(sid, det, tracks, p_whole, {0: (1, 2)},
                                   table, 0, 1, 3) == 0
    assert all(c == 0 for c, _ in _cmds(p_whole[2], ROWS))


def test_the_loop_step_is_split_for_its_own_question():
    """`loops=True` asks `_expanding_vibrato_loops`' question, which marks a
    block a tie ends. Position A is followed by a tie, position B is not: the
    `4xy` pass sees one want set and splits nothing, but a tie does not
    re-point the wavetable, so the loops would run on under it -- the union
    carries `tie` on every row, and without a copy neither position's rows
    can be pointed. With the loops' split B's can."""
    sid, det = _AgeSid(), _det(7)
    table = [(0x81, 3)]
    patterns = [_pat([_note(0xB3, 1)]), _pat([_note(0xB3, 2)]),
                _pat([_hold() for _ in range(ROWS)]),
                _pat([_note(0xB5, 0, CMD_TONEPORTA, 0)])]
    tracks = [[0, 2, 3, 0xFF, 0], [0, 2, 0, 0xFF, 0]]
    t2, p2, copies = _split(tracks, patterns)
    assert copies == {}, "the 4xy pass's question has no tie in it"
    _expanding_vibrato_pass(sid, det, t2, p2, {0: (1, 2)}, table, 0, 1, 3)

    whole = [list(p) for p in p2]
    _e, n_whole = _expanding_vibrato_loops(
        sid, det, t2, whole, {0: (1, 2)}, table, 0, 1, 3, list(PROGRAM), [1])
    assert not any(c == CMD_SETWAVEPTR for c, _ in _cmds(whole[2], ROWS))

    t3, p3, copies = _split(t2, p2, loops=True, speed_table=table)
    assert copies == {4: 2}
    _entries, n = _expanding_vibrato_loops(
        sid, det, t3, p3, {0: (1, 2)}, table, 0, 1, 3, list(PROGRAM), [1])
    assert n > n_whole
    tied_at, free_at = t3[0][1], t3[1][1]       # A (tie follows), B
    assert tied_at != free_at
    assert not any(c == CMD_SETWAVEPTR for c, _ in _cmds(p3[tied_at], ROWS))
    assert any(c == CMD_SETWAVEPTR for c, _ in _cmds(p3[free_at], ROWS))


def test_positions_that_want_the_same_rows_share_one_copy():
    tracks, patterns = _world([0, 0, 1])
    t2, p2, copies = _split(tracks, patterns)
    assert copies == {3: 2} and len(p2) == 4
    assert t2[0][1] == t2[1][1] == 3 and t2[2][1] == 2


def test_with_no_plain_position_the_largest_group_keeps_the_source():
    """Two groups that both want something: the pattern is entered by the
    note itself on two orderlists and, on a third, five hold rows into the
    same note -- the swell's age is the player's, not the pattern's, so the
    third wants other levels on the same rows. The bigger group keeps the
    source; the odd one out gets the copy."""
    tracks, patterns = _world([0, 0, 0])
    patterns.append(_pat([_note(0xB3, 1)] + [_hold() for _ in range(5)]))
    tracks[2][0] = 3
    t2, p2, copies = _split(tracks, patterns)
    assert copies == {4: 2}, copies
    assert t2[0][1] == t2[1][1] == 2 and t2[2][1] == 4


def test_nothing_is_copied_where_every_position_agrees():
    tracks, patterns = _world([0, 0])
    t2, p2, copies = _split(tracks, patterns)
    assert copies == {} and t2 == tracks and len(p2) == len(patterns)
    # ... nor where no position wants anything.
    tracks, patterns = _world([1, 1])
    assert _split(tracks, patterns)[2] == {}


def test_a_full_pattern_table_leaves_the_pattern_whole():
    tracks, patterns = _world([0, 1])
    logs = []
    t2, p2, copies = _split(tracks, patterns, limit=len(patterns), log=logs.append)
    assert copies == {} and t2 == tracks and len(p2) == len(patterns)
    assert any("pattern table full" in m for m in logs), logs


def test_a_song_without_vibrato_records_is_left_alone():
    tracks, patterns = _world([0, 1])
    assert _split(tracks, patterns, vib_ptrs={}) == (tracks, patterns, {})


# ---------------------------------------------------------------------------
# Mega_Apocalypse, the one unheld file this moves most.

def _mega(log):
    import fidelity
    from h2g.convert import convert
    doc = json.loads((PYTHON_ROOT.parent / "presets.json").read_text())
    opts = fidelity._preset_opts(doc, "Mega_Apocalypse.sid")
    return fidelity, convert(str(CORPUS / "Mega_Apocalypse.sid"), log, **opts)


@needs_corpus
def test_mega_apocalypse_pattern_0f_is_copied_and_commanded():
    from songview import parse_sng
    logs = []
    _fid, sng = _mega(logs.append)
    lines = [m for m in logs if m.startswith("Swell pattern split.")]
    # Once for the `4xy` pass, once more for the loop step, whose tie marks
    # make two positions want different rows (pattern $2F, 47 -- measured at
    # v0.5.526 + this change).
    assert len(lines) == 2, lines
    assert "0F" in lines[0], lines
    song = parse_sng(sng)
    assert len(song.patterns) <= 208
    # Pattern 15 (nothing before it is renumbered) keeps the plain voice's
    # rows bare; its copy has the same notes and slot 4's hold rows pointed at
    # wavetable loops -- 28 of them, before the copy none.
    notes = lambda p: [p[i] for i in range(0, min(len(p), 4 * 64), 4)]
    cmds = lambda p: [p[i + 2] for i in range(0, min(len(p), 4 * 64), 4)]
    shape = notes(song.patterns[15])
    holders = [p for p in song.patterns[16:] if notes(p) == shape]
    assert holders, "no copy of pattern 15 in the finished song"
    assert not any(cmds(song.patterns[15]))
    assert max(cmds(p).count(CMD_SETWAVEPTR) for p in holders) >= 20


@needs_corpus
@pytest.mark.parametrize("name", ["Mega_Apocalypse", "BMX_Kidz",
                                  "Skate_or_Die_intro"])
def test_every_pattern_of_a_split_song_is_played(name):
    """A copy nobody plays is a copy the orderlist bytes were not repointed
    at. Mega_Apocalypse alone would not say so (the loop step's own split
    rewrites every orderlist again); BMX_Kidz and Skate_or_Die_intro split
    once and nothing rewrites after. Checked on the finished file: no
    pattern is named by no orderlist (none was, without the split)."""
    import fidelity
    from h2g.convert import convert
    from songview import parse_sng
    doc = json.loads((PYTHON_ROOT.parent / "presets.json").read_text())
    opts = fidelity._preset_opts(doc, name + ".sid")
    # Skate_or_Die_intro's size search took max_rows 94 -> 128 and dedup
    # true -> false at v0.5.528 (after this split shipped), and that build
    # does not split its swell; the subject here is the split's repointing,
    # so pin the build that splits (Mega and BMX_Kidz already ship it).
    opts["max_rows"], opts["dedup"] = 94, True
    logs = []
    song = parse_sng(convert(str(CORPUS / (name + ".sid")), logs.append, **opts))
    assert any(m.startswith("Swell pattern split.") for m in logs), logs[-5:]
    played, operand = set(), False
    for track in song.tracks:
        for b in track:
            if operand:                      # $FF's restart position
                operand = False
            elif b == 0xFF:
                operand = True
            elif b < 0xD0:                   # a pattern, not a transpose/repeat
                played.add(b)
    assert played >= set(range(len(song.patterns))),         sorted(set(range(len(song.patterns))) - played)


@needs_corpus
@pytest.mark.skipif(not pathlib.Path(
    __import__("fidelity").SIDDUMP).exists(), reason="no siddump")
def test_mega_apocalypse_09b7_long_low_notes_swing(tmp_path):
    """siddump of the packed conversion, 180 s: every `$09B7` note held 50
    frames or more swings at least 500 units peak to peak (the original's
    1634-1766; before the copy: 28 and 610)."""
    fid, sng = _mega(lambda m: None)
    sng, _ = fid.legalise_restarts(bytes(sng))
    packed = fid.pack_sid(sng, tmp_path, fid.GT2RELOC, 1)
    assert packed is not None
    trace = fid.run_siddump(packed, 180, 0, fid.SIDDUMP, calls=1)
    nf = 180 * 50
    swings = []
    for v in trace:
        fq = fid.register_timeline(v.freq_events, nf)
        ad = fid.register_timeline(v.adsr_events, nf)
        atk = sorted(v.attack_frames)
        for j, f0 in enumerate(atk):
            end = min(atk[j + 1] if j + 1 < len(atk) else nf, nf)
            if ad[f0] != 0x09B7 or end - f0 < 50 or end - f0 > 80:
                continue
            seg = [fq[f] for f in range(f0 + 2, end)]
            swings.append(max(seg) - min(seg))
    assert len(swings) >= 3, swings
    assert min(swings) >= 500, swings


# --- the loops that do not all fit -------------------------------------------

def _plan(*rows):
    """`(pattern, row, remainder, entry, notes)` per `(remainder, entry)`."""
    return [(0, 4 * i, rest, entry, (40,))
            for i, (rest, entry) in enumerate(rows)]


def test_loops_that_fit_are_left_alone():
    plan = _plan(((), (3, 8)), ((), (3, 11)), (((2, 0xE0),), (3, 8)))
    assert _expanding_vibrato_loop_share(plan, 7) == ({}, 0, 0.0)


def test_the_least_used_swing_goes_onto_the_nearest_loop_of_its_remainder():
    # (3, 8) on three rows, (3, 9) on one, (3, 40) on one: room for two
    # two-entry blocks, so (3, 9) -- one step from (3, 8) -- is the one to go.
    plan = _plan(((), (3, 8)), ((), (3, 8)), ((), (3, 8)), ((), (3, 9)),
                 ((), (3, 40)))
    alias, merged, off = _expanding_vibrato_loop_share(plan, 4)
    assert alias == {((), (3, 9)): ((), (3, 8))}
    assert merged == 1 and 0 < off < 0.2


def test_a_swing_never_moves_onto_a_loop_with_another_remainder():
    delay = ((2, 0xE0),)
    plan = _plan((delay, (3, 8)), ((), (3, 8)), ((), (3, 8)), ((), (3, 9)))
    # (3, 8) costs 3 (the remainder's block and the one F4/FF pair it
    # carries), (3, 9) 2: room 4 asks for one merge.
    alias, _m, _o = _expanding_vibrato_loop_share(plan, 4)
    assert alias == {((), (3, 9)): ((), (3, 8))}
    # nothing to merge with: the blocks stay and the caller finds them full
    alone = _plan((delay, (3, 8)), ((), (3, 9)))
    assert _expanding_vibrato_loop_share(alone, 3)[0] == {}


def test_a_chain_of_merges_is_followed_to_its_end():
    plan = _plan(((), (3, 8)), ((), (3, 8)), ((), (3, 9)), ((), (3, 10)))
    alias, merged, _o = _expanding_vibrato_loop_share(plan, 2)
    assert merged == 2 and set(alias.values()) == {((), (3, 8))}


def test_an_absolute_and_a_note_relative_entry_are_compared_on_the_note():
    # shift 3 on note 40 and the absolute speed equal to it are one swing
    from h2g.goatwriter.note_passes import _expanding_vibrato_loop_swing
    from h2g.goatwriter.primitives import _note_freq
    speed = (_note_freq(41) - _note_freq(40)) >> 3
    assert (_expanding_vibrato_loop_swing((0x83, 3), 40)
            == _expanding_vibrato_loop_swing((3, speed), 40))


@needs_corpus
def test_mega_apocalypse_no_swell_loop_is_dropped_for_a_full_table():
    """Pattern 15 split, 56 loops want 109 entries (a remainder's block
    jumps onto the speed's loop, 126 when each carried its own) of a table
    with 101 to give: 4 of them share a neighbour's, and every row keeps a
    loop."""
    lines = []
    _fid, sng = _mega(lines.append)
    swell = [m for m in lines if m.startswith("Expanding vibrato loops")]
    assert len(swell) == 1 and "table full" not in swell[0], swell
    assert "on the nearest loop that fits" in swell[0], swell
    import songview
    assert len(songview.parse_sng(sng).tables["WTBL"]) <= 255


@needs_corpus
def test_with_the_split_and_the_alternation_off_mega_converts_as_it_did(
        monkeypatch):
    """The alternation-off sha moved (3dd7d6f19319 -> f5958c98a448) because of
    the split alone: with the split off as well it is the old one, (the sharing
    only acts where the split's extra loops overflow the table)."""
    import hashlib
    import h2g.goatwriter.build as B
    import h2g.goatwriter.counter_fall as CF
    monkeypatch.setattr(CF, "ALTERNATION_MIN_DIPS", 10 ** 6)
    # Mega's tied landings are legato clones since ca85ac7's
    # tie-restart-mega-phantoms-note-start; this pin is the arm without them.
    monkeypatch.setattr(B._gw_note_passes, "legato_tie_family", lambda sid, det: False)
    monkeypatch.setattr(B._gw_note_passes, "expanding_vibrato_split",
                        lambda sid, det, tracks, patterns, *a, **k:
                        (tracks, patterns, {}))
    _fid, sng = _mega(lambda m: None)
    # Re-pinned by the -S1 slide frames (wave-program-slide-frames-0797-family):
    # Mega's $09F9/$07E7 slide frames are now semitone counts; with
    # note_pitches=None in convert() the old sha comes back.
    # Re-pinned (c909ffb6b436) by the drop of the pulse and filter rows only a
    # dropped record reaches (instrument_drop._drop_dead_blocks).
    assert hashlib.sha1(sng).hexdigest()[:12] == "c909ffb6b436"
