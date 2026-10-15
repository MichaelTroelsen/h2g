"""A relative wave step some notes play inside the table and some past it
(`past_table_wave.retarget_mixed_steps`).

5_Title_Tunes' instrument 5 is the octave arpeggio `10 +12 / 10 +0 / FF`.
On C#7 and D#7 the +12 step indexes 97 and 99, past Goattracker's 96 notes,
where the packed player reads gt2reloc's orderlist address bytes: `$F701`
at one wavetable size, `$8B01` at another, with no wave or note byte changed.
The original sounds `$000E`. The step cannot be pinned in place (other notes
play it inside the table), so the rows that overflow it point at a pinned
copy of the program.
"""
from __future__ import annotations

import subprocess
import sys
from pathlib import Path
from types import SimpleNamespace

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent))

from h2g import past_table_wave as W  # noqa: E402
from h2g.goatwriter.appending import _Song, _parse_song, _write_song  # noqa: E402
from h2g.goatwriter.constants import HEADER_LEN  # noqa: E402

# GTS5 record: ad sr wave pulse filter speed vibdelay gatetimer firstwave name
_ARP = [(0x10, 0x0C), (0x10, 0x00), (0xFF, 0x01)]    # octave arpeggio loop


def _det():
    return SimpleNamespace(freq_table=SimpleNamespace(length=96), note_base=0)


def _row(note=0, ins=0, cmd=0, data=0):
    return [note, ins, cmd, data]


def _note(n):
    return 0x60 + n


def _song(pattern_rows, *, vibrato=0, trans=0, extra_tracks=(), wave=None,
          instruments=1):
    recs = []
    for _ in range(instruments):
        rec = bytearray(25)
        rec[2], rec[5] = 1, vibrato
        recs.append(rec)
    pat = bytearray(b for row in pattern_rows for b in row)
    order = ([0xF0 + trans] if trans else []) + [0, 0xFF, 0]
    tracks = [bytes(order)] * 3 if not extra_tracks else list(extra_tracks)
    return _Song(b"GTS5", b"GTS5" + bytes(HEADER_LEN - 4), tracks, recs,
                 [list(wave if wave is not None else _ARP), [], [], []],
                 [pat])


# Tests that convert real files and so must read the real cells.
_CORPUS_TESTS = ("test_5_title_tunes", "test_no_note_row",
                 "test_shared_patterns")


@pytest.fixture(autouse=True)
def _cell(monkeypatch, request):
    """Every cell past the table reads as the table's first entry (the
    synthetic songs; the corpus tests read the real file's)."""
    if not any(part in request.node.name for part in _CORPUS_TESTS):
        monkeypatch.setattr(W, "_cell_entry", lambda sid, det, index: 0)


def _split(song):
    log = []
    changed = W.retarget_mixed_steps(song, None, _det(), log.append)
    return changed, log


def test_a_free_row_points_at_a_pinned_copy():
    song = _song([_row(_note(85), 1), _row(_note(60), 1)])
    before = [list(song.tables[0]), bytes(song.patterns[0])]
    changed, log = _split(song)
    assert changed and "1 pinned copy" in log[0] and "1 by pointer" in log[0]
    wave = song.tables[0]
    assert wave[:3] == before[0]                      # the original, untouched
    assert wave[3:] == [(0x10, 0x81), (0x10, 0x00), (0xFF, 4)]
    pat = song.patterns[0]
    assert list(pat[0:4]) == [_note(85), 1, 8, 4]     # the overflowing row
    assert bytes(pat[4:8]) == before[1][4:8]          # the in-table one


def test_nothing_changes_when_every_note_stays_inside_the_table():
    song = _song([_row(_note(60), 1), _row(_note(70), 1)])
    assert _split(song)[0] is False
    assert len(song.tables[0]) == 3


def test_a_row_of_a_vibrating_instrument_gets_a_clone_and_the_next_row_restores_it():
    song = _song([_row(_note(85), 1, 4, 0), _row(), _row(_note(60), 1)],
                 vibrato=2)
    changed, log = _split(song)
    assert changed and "1 by 1 instrument clone" in log[0]
    clone = song.instruments[1]
    assert clone[2] == 4 and clone[5] == 0            # pinned program, no vibrato
    assert bytes(song.instruments[0][:2]) == bytes(clone[:2])
    pat = song.patterns[0]
    assert list(pat[0:4]) == [_note(85), 2, 8, 4]
    assert pat[5] == 1          # the empty row after it names the original again
    assert list(pat[4:8]) == [0, 1, 0, 0]
    assert list(pat[8:12]) == [_note(60), 1, 0, 0]    # nothing else was touched
    assert song.instruments[0][2] == 1 and song.instruments[0][5] == 2


def test_a_clone_row_followed_by_a_named_row_adds_no_restore():
    song = _song([_row(_note(85), 1, 4, 0), _row(_note(60), 1)], vibrato=2)
    _split(song)
    assert song.patterns[0][5] == 1       # it already named the instrument


def test_vibrato_zero_on_an_instrument_that_never_vibrates_is_replaced():
    song = _song([_row(_note(85), 1, 4, 0), _row(_note(60), 1)], vibrato=0)
    _split(song)
    assert len(song.instruments) == 1
    assert list(song.patterns[0][0:4]) == [_note(85), 1, 8, 4]


def test_a_busy_command_column_is_left_alone():
    song = _song([_row(_note(85), 1, 1, 0x20), _row(_note(60), 1)])
    changed, log = _split(song)
    assert not changed and "1 with the command column in use" in log[0]
    assert len(song.tables[0]) == 3


def test_a_vibrating_row_that_ends_its_pattern_is_left_alone():
    song = _song([_row(_note(60), 1), _row(_note(85), 1, 4, 0)], vibrato=2)
    changed, log = _split(song)
    assert not changed and "1 ending their pattern" in log[0]
    assert len(song.instruments) == 1


_TWO_TRANSPOSES = [bytes([0, 0xFF, 0]), bytes([0xF0 - 14, 0, 0xFF, 0]),
                   bytes([0, 0xFF, 0])]


def test_a_row_played_under_two_transposes_gets_its_own_pattern():
    """Pattern 0 is played at +0 (85 + 12 = 97) and 14 semitones down (83):
    the two visits at +0 point at a copy that takes the pointer, the visit
    that reads inside the table keeps the original."""
    song = _song([_row(_note(85), 1), _row(_note(60), 1)],
                 extra_tracks=_TWO_TRANSPOSES)
    before = bytes(song.patterns[0])
    changed, log = _split(song)
    assert changed and "1 pattern cop" in log[0]
    assert len(song.patterns) == 2
    assert bytes(song.patterns[0]) == before            # the original, untouched
    assert list(song.patterns[1][0:4]) == [_note(85), 1, 8, 4]
    assert song.tracks[0] == bytes([1, 0xFF, 0])
    assert song.tracks[1] == _TWO_TRANSPOSES[1]         # reads inside the table
    assert song.tracks[2] == bytes([1, 0xFF, 0])
    assert len(song.tables[0]) == 6


def test_visits_that_overflow_alike_share_one_copy():
    song = _song([_row(_note(85), 1)],
                 extra_tracks=[bytes([0, 0xFF, 0]), bytes([0, 0xFF, 0]),
                               bytes([0xF0 - 14, 0, 0xFF, 0])])
    _split(song)
    assert len(song.patterns) == 2
    assert song.tracks[0] == song.tracks[1] == bytes([1, 0xFF, 0])


def test_a_copy_nothing_uses_is_taken_back_out():
    """The overflowing visit's row has its command column in use, so the
    copy would only be a duplicate: no pattern, no orderlist change."""
    song = _song([_row(_note(85), 1, 1, 0x20), _row(_note(60), 1)],
                 extra_tracks=_TWO_TRANSPOSES)
    tracks = list(song.tracks)
    changed, log = _split(song)
    assert not changed and "1 with the command column in use" in log[0]
    assert len(song.patterns) == 1 and song.tracks == tracks


def test_the_surviving_copy_is_renumbered_when_an_earlier_one_goes():
    """Patterns 0 (busy column) and 1 (free) both want a copy, numbered 2
    and 3; pattern 0's goes, so pattern 1's becomes pattern 2."""
    song = _song([_row(_note(85), 1, 1, 0x20), _row(_note(60), 1)],
                 extra_tracks=[bytes([0, 1, 0xFF, 0]),
                               bytes([0xF0 - 14, 0, 1, 0xFF, 0]),
                               bytes([0xF0 - 14, 0, 1, 0xFF, 0])])
    song.patterns.append(bytearray(
        b for row in [_row(_note(85), 1), _row(_note(60), 1)] for b in row))
    changed, _log = _split(song)
    assert changed and len(song.patterns) == 3
    assert song.tracks[0] == bytes([0, 2, 0xFF, 0])     # restart byte untouched
    assert list(song.patterns[2][0:4]) == [_note(85), 1, 8, 4]
    assert list(song.patterns[0][0:4]) == [_note(85), 1, 1, 0x20]


def test_no_copy_past_the_pattern_limit():
    song = _song([_row(_note(85), 1), _row(_note(60), 1)],
                 extra_tracks=_TWO_TRANSPOSES)
    song.patterns.extend(bytearray(8) for _ in range(W.MAX_PATTERNS - 1))
    changed, log = _split(song)
    assert not changed and "contexts that disagree" in log[0]
    assert len(song.patterns) == W.MAX_PATTERNS


def test_an_existing_pointer_row_is_retargeted():
    wave = _ARP + [(0x11, 0x00), (0xFF, 0x00)]
    song = _song([_row(_note(85), 1, 8, 4), _row(_note(60), 1)], wave=wave)
    song.instruments[0][2] = 4          # its own program is the plain one
    changed, _log = _split(song)
    assert not changed          # SETWAVEPTR 4 runs `11 +0 / FF`: nothing past
    song = _song([_row(_note(85), 1, 8, 1), _row(_note(60), 1)], wave=wave)
    changed, _log = _split(song)
    assert changed
    assert list(song.patterns[0][0:4]) == [_note(85), 1, 8, 6]


def test_a_jump_inside_the_copy_stays_inside_the_copy():
    wave = [(0x11, 0x00), (0x10, 0x0C), (0x10, 0x00), (0xFF, 0x02)]
    song = _song([_row(_note(85), 1), _row(_note(60), 1)], wave=wave)
    _split(song)
    assert song.tables[0][4:] == [(0x11, 0x00), (0x10, 0x81), (0x10, 0x00),
                                  (0xFF, 6)]


def test_two_notes_with_different_cells_get_two_copies(monkeypatch):
    monkeypatch.setattr(W, "_cell_entry",
                        lambda sid, det, index: {97: 0, 99: 5}[index])
    song = _song([_row(_note(85), 1), _row(_note(87), 1), _row(_note(85), 1)])
    changed, log = _split(song)
    assert changed and "2 pinned copy" in log[0]
    wave = song.tables[0]
    assert (0x10, 0x81) in wave[3:] and (0x10, 0x85) in wave[3:]
    pat = song.patterns[0]
    assert pat[3] == pat[11] != pat[7]


def test_a_full_wavetable_leaves_the_row_alone():
    wave = _ARP + [(0x11, 0)] * 250
    song = _song([_row(_note(85), 1), _row(_note(60), 1)], wave=wave)
    changed, log = _split(song)
    assert not changed and len(song.tables[0]) == 253
    assert "1 wavetable or instruments full" in log[0]
    assert list(song.patterns[0][0:4]) == [_note(85), 1, 0, 0]


def test_the_whole_pass_round_trips_through_the_writer():
    blob = _write_song(_song([_row(_note(85), 1, 4, 0), _row(), _row(_note(60), 1)],
                             vibrato=2))
    sid = SimpleNamespace(name="Synthetic")
    out = W.pin_past_table_wave_notes(blob, sid, _det())
    assert out != blob
    again = _parse_song(out)
    assert len(again.instruments) == 2 and len(again.tables[0]) == 6


def test_commando_is_still_held():
    blob = _write_song(_song([_row(_note(85), 1), _row(_note(60), 1)]))
    sid = SimpleNamespace(name="Commando")
    assert W.pin_past_table_wave_notes(blob, sid, _det()) == blob


# --- the corpus file that found it -----------------------------------------

_CORPUS: dict = {}


def _corpus_convert(name: str, forced: bool = False):
    """(final blob, [(before, after) of every call the pass made]): a
    compilation converts one view per player, and only player 1 of
    5_Title_Tunes plays the arpeggio."""
    key = (name, forced)
    if key in _CORPUS:
        return _CORPUS[key]
    import fidelity
    from h2g import convert as C
    from test_pulse_phase import _corpus_and_presets
    corpus, doc = _corpus_and_presets()
    path = corpus / name
    if not path.exists():
        pytest.skip(f"{name} not in the corpus here")
    kw = fidelity._preset_opts(doc, name)
    if forced:
        kw["pulse_phase"] = True
    seen = []
    real = C.pin_past_table_wave_notes

    def spy(blob, sid, det, log=None):
        after = real(blob, sid, det, log)
        # `_append_players` retries a compilation with the mixed split OFF
        # and may discard the attempt; those calls leave steps relative on
        # purpose and are not views of the finished file. Since the unnamed-
        # records rung (tick0-retake-on-append-ladder) 5_Title_Tunes is
        # attempted that way before the rung adopts a split-on result.
        if W.SPLIT_MIXED:
            seen.append((bytes(blob), bytes(after), sid, det))
        return after

    C.pin_past_table_wave_notes = spy
    try:
        out = C.convert(str(path), log=lambda m: None, **kw)
    finally:
        C.pin_past_table_wave_notes = real
    _CORPUS[key] = (out, seen)
    return _CORPUS[key]


def _voice_freqs(path: Path, sub: int, seconds: int, mult: int, voice: int):
    import fidelity
    cmd = [fidelity.SIDDUMP, str(path), f"-a{sub}", f"-t{seconds}"]
    if mult > 1:
        cmd.append(f"-m{mult}")
    out, cur = [], None
    for line in subprocess.run(cmd, capture_output=True, text=True).stdout.splitlines():
        if not (line.startswith("|") and line[2:7].strip().isdigit()):
            continue
        f = line.split("|")[2 + voice].split()
        if f and f[0] != "....":
            cur = f[0]
        out.append(cur)
    return out


def test_5_title_tunes_overflow_rows_point_at_pinned_copies():
    """Every conversion of the one view that plays the arpeggio (a compilation
    converts it more than once: held, then with carried skydive programs)."""
    _out, seen = _corpus_convert("5_Title_Tunes.sid")
    changed = {(a, b) for a, b, _s, _d in seen if a != b}
    assert changed, "the pass never split a step"
    for old_blob, new_blob in changed:
        old, new = _parse_song(old_blob), _parse_song(new_blob)
        assert new.tables[0][:len(old.tables[0])] == old.tables[0]   # not rewritten
        assert len(new.tables[0]) == len(old.tables[0]) + 10
        assert new.tables[1:] == old.tables[1:] and new.tracks == old.tracks
        assert len(new.instruments) == len(old.instruments) + 2
        for rec in new.instruments[len(old.instruments):]:
            assert rec[5] == 0 and rec[2] > len(old.tables[0])       # no vibrato
        moved = [(n, k) for n, (p, q) in enumerate(zip(old.patterns, new.patterns))
                 for k in range(0, len(p), 4) if p[k:k + 4] != q[k:k + 4]]
        assert len(moved) >= 6
        notes = {old.patterns[n][k] - 0x60 for n, k in moved
                 if old.patterns[n][k] >= 0x60}
        assert {85, 87} <= notes


def test_5_title_tunes_voice_zero_pitch_does_not_move_with_the_packed_layout(tmp_path):
    """The presets pack and the forced-pulse_phase pack lay different
    tables, so gt2reloc puts the orderlists -- and the bytes the overflowing
    cells read -- somewhere else. Voice 0 of subtune 1 played `$F701` on those
    frames at one size and `$8B01` at another; it must not care now."""
    import fidelity
    if not (Path(fidelity.SIDDUMP).exists() and Path(fidelity.GT2RELOC).exists()):
        pytest.skip("siddump or gt2reloc not available here")
    from test_pulse_phase import _corpus_and_presets
    _corpus, doc = _corpus_and_presets()
    name = "5_Title_Tunes.sid"
    mult = fidelity._preset_multiplier(doc, name)
    traces = []
    for forced in (False, True):
        out = _corpus_convert(name, forced)[0]
        wd = tmp_path / ("forced" if forced else "presets")
        wd.mkdir()
        packed = fidelity.pack_sid(out, wd, multiplier=mult)
        assert packed is not None, "gt2reloc refused"
        traces.append(_voice_freqs(packed, 1, 40, mult, 0))
    a, b = traces
    assert len(a) == len(b) > 0
    assert "F701" not in a and "8B01" not in a
    assert sum(x != y for x, y in zip(a, b)) == 0


def _unpinned(blob, sid, det):
    """(row, visit) pairs still sending a relative step past the table."""
    song = _parse_song(blob)
    cache: dict = {}
    return sum(1 for visits in W._reach(song).values()
               for st, n, _i in visits
               if W._split_key(song, sid, det, st, n, cache) is not None)


@pytest.mark.parametrize("name", [
    "5_Title_Tunes.sid", "Crazy_Comets.sid", "Formula_1_Simulator.sid",
    "Gerry_the_Germ.sid", "Nineteen.sid", "One_Man_and_his_Droid.sid",
    "Star_Paws.sid", "Thing_on_a_Spring.sid",
    "Trans-Atlantic_Balloon_Challenge.sid",
    "Saboteur_II.sid", "Rock_Tells_the_Tale.sid"])
def test_no_note_row_is_left_on_a_layout_dependent_cell(name):
    """Every view the file converts, after the pass: the eleven corpus files
    whose rows could be split have none left. The last two share a pattern
    between orderlist transposes, so the pattern is copied."""
    _out, seen = _corpus_convert(name)
    assert seen and all(_unpinned(a, sid, det) == 0
                        for _b, a, sid, det in seen)


@pytest.mark.parametrize("name,copies", [("Saboteur_II.sid", 3),
                                         ("Rock_Tells_the_Tale.sid", 2)])
def test_shared_patterns_under_two_transposes_are_copied(name, copies):
    """The same pattern row is inside the table under one orderlist
    transpose and past it under another; the visits that overflow play a
    copy, only the orderlist entries and the new patterns change."""
    _out, seen = _corpus_convert(name)
    changed = [(a, b) for a, b, _s, _d in seen if a != b]
    assert changed, "the pass never split a step"
    for old_blob, new_blob in changed:
        old, new = _parse_song(old_blob), _parse_song(new_blob)
        assert len(new.patterns) == len(old.patterns) + copies
        assert new.patterns[:len(old.patterns)] == old.patterns   # originals kept
        assert new.tables[0][:len(old.tables[0])] == old.tables[0]
        assert new.instruments == old.instruments
        assert len(new.patterns) <= W.MAX_PATTERNS
        assert new.tracks != old.tracks
        assert all(len(o) == len(n) for o, n in zip(old.tracks, new.tracks))
        for copy in new.patterns[len(old.patterns):]:
            assert any((copy[k + 2] & 0x0F) == 8 and copy[k + 3] > len(old.tables[0])
                       for k in range(0, len(copy), 4))     # each takes a pointer


def test_the_split_can_be_switched_off():
    """`_append_players` retries a compilation that lost a player to the
    room the split spent (5_Title_Tunes without compact_instruments: the
    clones take instrument slots the fifth player needs)."""
    song = _song([_row(_note(85), 1), _row(_note(60), 1)])
    with W.mixed_split(False):
        assert _split(song)[0] is False
    assert len(song.tables[0]) == 3
    assert W.SPLIT_MIXED is True
    assert _split(song)[0] is True


def test_5_title_tunes_keeps_every_subtune_without_compact_instruments():
    import fidelity
    from h2g.convert import convert
    from test_pulse_phase import _corpus_and_presets
    corpus, doc = _corpus_and_presets()
    path = corpus / "5_Title_Tunes.sid"
    if not path.exists():
        pytest.skip("5_Title_Tunes not in the corpus here")
    kw = dict(fidelity._preset_opts(doc, path.name), compact_instruments=False)
    lines: list = []
    blob = convert(str(path), log=lines.append, **kw)
    assert len(_parse_song(blob).tracks) // 3 == 5
    # The tick-0 vibrato correction splits the appended players' shared
    # records (66 > 63 without the rung); the unnamed-records rung brings the
    # file to 48, so the mixed split no longer has to be given up.
    assert not any("mixed wave steps left relative" in m for m in lines)
    assert any("unnamed instruments dropped from the appended players" in m
               for m in lines)
