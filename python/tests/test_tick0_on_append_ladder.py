"""The global-triangle vibrato's tick-0 correction costs 5_Title_Tunes three
instrument slots, and `_append_players`' unnamed-records rung gives them back.

The correction (`vibrato._triangle_vibrato_entry(row_calls=...)`) makes the
entry a function of the record's row, so the shared records of 5_Title_Tunes'
2-call and 3-call players no longer merge: with `compact_instruments` off the
merged file needs 65 > 63 instruments and player 4 / subtune 4 is not appended
(`global-triangle-vibrato-tick0`, held at 6e467ff because of exactly that).
The rung `instrument-cap-append-ladder` added drops each appended view's
unnamed records before the merge, which brings the same file to 50.

Both halves are pinned: with the rung switched off the squeeze reappears, and
with it on every player is kept. A change that drops either the correction's
cost or the rung's gain makes one of them fail.
"""
import json
import pathlib
import re
import sys
import warnings

import pytest

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[1]))

from corpus import CORPUS  # noqa: E402

REPO_ROOT = pathlib.Path(__file__).resolve().parents[2]
FIVE = "5_Title_Tunes.sid"
RUNG = "unnamed instruments dropped from the appended players"
GT_CAP = 63


def _convert(rung=True, **over):
    """(bytes, log) of 5_Title_Tunes under its presets plus `over`."""
    from h2g import convert as C
    presets = REPO_ROOT / "presets.json"
    if not presets.is_file():
        pytest.skip("presets.json not available here")
    if not (CORPUS / FIVE).is_file():
        pytest.skip("corpus not available here")
    with warnings.catch_warnings():
        warnings.simplefilter("ignore")
        import fidelity
        opts = dict(fidelity._preset_opts(json.loads(presets.read_text()),
                                          FIVE), **over)
    lines = []
    real_level = C._append_level
    if not rung:
        C._append_level = lambda *a, drop_unnamed=False, **k: real_level(*a, **k)
    try:
        sng = C.convert(str(CORPUS / FIVE), log=lines.append, **opts)
    finally:
        C._append_level = real_level
    return sng, lines


def _players_line(lines):
    return next(l for l in lines if l.startswith("Players......")
                and "further player(s)" in l)


def _last_appended_instruments(lines):
    """Instruments the merged file carried after the last player joined."""
    hits = [int(m.group(1)) for l in lines
            for m in [re.match(r"Appended \d+: .*now carries (\d+) instruments",
                               l)] if m]
    assert hits, "no 'Appended N:' line"
    return hits[-1]


@pytest.fixture(scope="module")
def compact_off():
    return _convert(compact_instruments=False)


@pytest.fixture(scope="module")
def compact_off_no_rung():
    return _convert(rung=False, compact_instruments=False)


@pytest.fixture(scope="module")
def presets_run():
    return _convert()


def test_every_player_is_kept_with_compact_off(compact_off):
    _, lines = compact_off
    assert "NOT APPENDED" not in "\n".join(lines)
    assert "4 of 4 further player(s) appended" in _players_line(lines)


def test_the_rung_is_what_keeps_them_with_compact_off(compact_off):
    _, lines = compact_off
    assert RUNG in _players_line(lines)


def test_without_the_rung_player_4_overflows_the_cap(compact_off_no_rung):
    """The cost of the tick-0 correction, measured at f28b063: 68 > 63 with
    `compact_instruments` off (66 under the presets), player 4 left out."""
    _, lines = compact_off_no_rung
    text = "\n".join(lines)
    assert re.search(r"\*\*\* 4 NOT APPENDED: \d+ instruments > 63", text)
    assert "3 of 4 further player(s) appended" in _players_line(lines)


def test_the_merged_file_stays_under_the_cap(compact_off, presets_run):
    for _, lines in (compact_off, presets_run):
        assert _last_appended_instruments(lines) <= GT_CAP


def test_presets_keep_every_player_and_use_the_rung(presets_run):
    _, lines = presets_run
    line = _players_line(lines)
    assert "4 of 4 further player(s) appended" in line
    assert RUNG in line
    assert "NOT APPENDED" not in "\n".join(lines)


# The exact counts, measured at 2b50aee (pin-the-5-title-tunes-instrument-count).
# The tests above only bound them by 63; the rung's margin is what protects
# player 4, so a change pushing the rung's output toward 63 fails here before
# player 4 is dropped.
PRESETS_INSTRUMENTS = 48
COMPACT_OFF_INSTRUMENTS = 50
COMPACT_OFF_INSTRUMENTS_NO_RUNG = 68


def test_presets_instrument_count_is_pinned(presets_run):
    _, lines = presets_run
    assert _last_appended_instruments(lines) == PRESETS_INSTRUMENTS


def test_compact_off_instrument_count_is_pinned(compact_off):
    _, lines = compact_off
    assert _last_appended_instruments(lines) == COMPACT_OFF_INSTRUMENTS


def test_the_rung_leaves_a_margin_below_the_cap(compact_off, presets_run):
    for _, lines in (compact_off, presets_run):
        assert GT_CAP - _last_appended_instruments(lines) >= 10


def test_the_unrung_overflow_count_is_pinned(compact_off_no_rung):
    """Without the rung: 68 with compact off, so the gap the rung closes
    (68 -> 50) is a number, not a story."""
    _, lines = compact_off_no_rung
    assert (f"*** 4 NOT APPENDED: {COMPACT_OFF_INSTRUMENTS_NO_RUNG} "
            f"instruments > {GT_CAP} ***") in lines
