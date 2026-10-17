"""`_append_players`' last rung frees instrument slots by dropping the appended
players' dead records before the merge.

The cap is checked on the merged file BEFORE `drop_unnamed_instruments` runs,
so every record no pattern names counts against Goattracker's 63 until the end.
5_Title_Tunes' four appended players reach 63 of 63 with 24 of them dead (39
survive the final drop), and none of the ladder's levels
(`pulse_phase`, `pulse`, mixed wave steps) frees a slot -- they spend wavetable
and pulse rows. A change that adds two instruments to that file therefore
loses player 4 (`global-triangle-vibrato-tick0`: 65 > 63).

The rung runs only where every other level left a player out, so a file that
appends everything keeps its bytes. Since the global triangle vibrato's
tick-0 correction (tick0-retake-on-append-ladder) 5_Title_Tunes is such a file
AT the shipped cap: its players' shared records no longer merge, the ladder
alone needs 66 > 63, and the rung brings it to 48. The "natural" reference is
therefore the same conversion at a cap raised to 70, where the ladder alone
fits and the rung is idle; before the correction it was the shipped cap with
a squeeze to 55 to make the rung observable.
"""
import json
import pathlib
import shutil
import sys
import tempfile
import warnings

import pytest

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[1]))

from corpus import CORPUS, needs_corpus  # noqa: E402

REPO_ROOT = pathlib.Path(__file__).resolve().parents[2]
FIVE = "5_Title_Tunes.sid"
SQUEEZED_CAP = 63           # the shipped cap; 66 without the rung
NATURAL_CAP = 70            # the rung is idle where the ladder alone fits
RUNG = ("unnamed instruments dropped from the appended players")


def _opts(name, **over):
    presets = REPO_ROOT / "presets.json"
    if not presets.is_file():
        pytest.skip("presets.json not available here")
    with warnings.catch_warnings():
        warnings.simplefilter("ignore")
        import fidelity
        doc = json.loads(presets.read_text())
        return dict(fidelity._preset_opts(doc, name), **over)


def _convert(cap=None, rung=True, **over):
    """(bytes, log) of 5_Title_Tunes under its presets, optionally with
    Goattracker's instrument cap lowered to `cap` and the rung switched off."""
    from h2g import convert as C
    from h2g.goatwriter import appending as A
    if not (CORPUS / FIVE).is_file():
        pytest.skip("corpus not available here")
    opts = _opts(FIVE, **over)
    lines = []
    real_cap, real_level = A.GT_MAX_INSTRUMENTS, C._append_level
    if cap is not None:
        A.GT_MAX_INSTRUMENTS = cap
    if not rung:
        C._append_level = lambda *a, drop_unnamed=False, **k: real_level(*a, **k)
    try:
        sng = C.convert(str(CORPUS / FIVE), log=lines.append, **opts)
    finally:
        A.GT_MAX_INSTRUMENTS, C._append_level = real_cap, real_level
    return sng, lines


@pytest.fixture(scope="module")
def natural():
    return _convert(cap=NATURAL_CAP)


@pytest.fixture(scope="module")
def squeezed():
    return _convert(cap=SQUEEZED_CAP)


@pytest.fixture(scope="module")
def squeezed_no_rung():
    return _convert(cap=SQUEEZED_CAP, rung=False)


def _players_line(lines):
    got = [l for l in lines if l.startswith("Players.................: ")
           and "further" in l]
    assert len(got) == 1, got
    return got[0]


@needs_corpus
def test_a_file_that_appends_everything_never_reaches_the_rung(natural):
    _sng, lines = natural
    assert _players_line(lines) == (
        "Players.................: 4 of 4 further player(s) appended as "
        "subtunes 1..4 (without pulse_phase)")
    assert any("Appended 4:" in l and "carries 66 instruments" in l
               for l in lines), [l for l in lines if l.startswith("Appended")]


@needs_corpus
def test_the_cap_binds_without_the_rung(squeezed_no_rung):
    _sng, lines = squeezed_no_rung
    assert "*** 4 NOT APPENDED: 66 instruments > 63 ***" in lines
    assert _players_line(lines).startswith(
        "Players.................: 3 of 4 further player(s) appended")


@needs_corpus
def test_the_rung_appends_the_player_the_cap_refused(squeezed):
    _sng, lines = squeezed
    assert _players_line(lines) == (
        "Players.................: 4 of 4 further player(s) appended as "
        f"subtunes 1..4 (without pulse_phase, {RUNG})")
    assert any("Appended 4:" in l and "carries 48 instruments" in l
               for l in lines), [l for l in lines if l.startswith("Appended")]


@needs_corpus
def test_the_rung_costs_the_finished_file_nothing(natural, squeezed):
    """What the final drop keeps is what the rung keeps: same instruments in
    the same order, the same notes, instrument columns and orderlists; only table rows that no
    surviving record reaches are gone."""
    from h2g.goatwriter import appending as A
    a, b = A._parse_song(natural[0]), A._parse_song(squeezed[0])
    assert len(a.instruments) == len(b.instruments) == 39
    assert b.tracks == a.tracks
    assert len(a.patterns) == len(b.patterns)
    pointers = set(A._POINTER_COMMANDS) | set(A._SPEED_COMMANDS)
    for pa, pb in zip(a.patterns, b.patterns):
        assert len(pa) == len(pb)
        for r in range(0, len(pa), 4):
            # note, instrument and command agree; a command's data too
            # unless it names a table row, which follows the rows.
            assert pa[r:r + 3] == pb[r:r + 3]
            if pa[r + 2] & 0x0F not in pointers:
                assert pa[r + 3] == pb[r + 3]
    # Records agree but for the four table pointers, which follow the rows.
    for ra, rb in zip(a.instruments, b.instruments):
        assert ra[:2] == rb[:2] and ra[6:] == rb[6:]
    for t in (0, 3):
        assert len(b.tables[t]) <= len(a.tables[t])
    assert len(b.tables[0]) < len(a.tables[0])      # wave rows left behind
    # The pulse and filter tables lose the rows only a dropped record reaches
    # in BOTH files (instrument_drop._drop_dead_blocks), and the rung's
    # pre-merge drop changes which blocks the merge shares, so their lengths
    # may differ either way (194 against 192 pulse rows here): what must agree
    # is the program every kept record enters.
    def program(song, t, ptr):
        rows, i = [], ptr - 1
        while ptr and 0 <= i < len(song.tables[t]):
            left, right = song.tables[t][i]
            if left == 0xFF:
                rows.append((left, right - ptr if right else None))
                break
            rows.append((left, right))
            i += 1
        return rows
    for ra, rb in zip(a.instruments, b.instruments):
        assert program(a, 1, ra[3]) == program(b, 1, rb[3])
        assert program(a, 2, ra[4]) == program(b, 2, rb[4])


@needs_corpus
def test_a_rung_that_frees_too_little_leaves_the_file_as_it_was():
    """At a cap of 20 not even player 1 fits dropped (24) or not (34): the
    rung appends exactly as many players as the ladder did, so its result is
    not adopted -- no label, and the very same bytes."""
    plain, plain_lines = _convert(cap=20, rung=False)
    tried, lines = _convert(cap=20)
    assert _players_line(plain_lines) == (
        "Players.................: none of 4 further player(s) appended")
    assert _players_line(lines) == _players_line(plain_lines)
    assert tried == plain


@needs_corpus
def test_the_rung_is_gated_on_the_final_drop():
    """Without `drop_unnamed_instruments` the dead records stay in the
    finished file, so dropping them from the appended players only would make
    the file inconsistent: the rung is not tried."""
    _sng, lines = _convert(cap=SQUEEZED_CAP, drop_unnamed_instruments=False)
    assert RUNG not in _players_line(lines)
    assert _players_line(lines).startswith(
        "Players.................: 3 of 4 further player(s) appended")


@needs_corpus
def test_the_rung_writes_the_same_registers_for_every_subtune():
    """Both files packed, each of the five subtunes through siddump for 20 s:
    register tables equal row for row."""
    import fidelity as F
    if not pathlib.Path(F.SIDDUMP).exists() or not pathlib.Path(F.GT2RELOC).exists():
        pytest.skip("siddump or gt2reloc not available here")
    natural_sng, _ = _convert(cap=NATURAL_CAP)
    squeezed_sng, _ = _convert(cap=SQUEEZED_CAP)
    assert natural_sng != squeezed_sng
    wd = pathlib.Path(tempfile.mkdtemp(prefix="instrument_cap_ladder_"))
    try:
        tables = []
        for tag, sng in (("natural", natural_sng), ("squeezed", squeezed_sng)):
            (wd / tag).mkdir()
            sid = F.pack_sid(sng, wd / tag)
            assert sid is not None, tag
            per_subtune = []
            for subtune in range(5):
                cap = []
                F.run_siddump(sid, 20, subtune, F.SIDDUMP, capture=cap)
                per_subtune.append([l for l in cap[1].splitlines()
                                    if l.startswith("|")])
            tables.append(per_subtune)
    finally:
        shutil.rmtree(wd, ignore_errors=True)
    for subtune in range(5):
        assert len(tables[0][subtune]) > 100, subtune
        assert tables[0][subtune] == tables[1][subtune], subtune
