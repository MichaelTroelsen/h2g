"""The part of a row an orderlist tempo change rounds away, spent in patterns.

Rasputin's `$FE nn` rows are `2 * (R+1)/R * 2` calls at `-S2`: 5.333 for
R = 3, 4.8 for R = 5, 4.4 for R = 10. `_apply_orderlist_tempos` can only
write whole calls, and the per-change errors integrated along the orderlist
into a matched-attack offset of -34 -> +62 -> -74 frames over 180 s.
`patterns._compensate_fractional_rows` carries an accumulator along the
track and lengthens or shortens a run of hold rows in each entry, in a copy.
"""
import json
import pathlib
import sys

from corpus import CORPUS, needs_corpus  # noqa: E402

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[1]))

from h2g.convert import _detect_tables, convert  # noqa: E402
from h2g.goatwriter import (CMD_SETTEMPO, orderlist_tempo_calls,  # noqa: E402
                            orderlist_tempo_values)
from h2g.patterns import (GT_NO_NOTE, _compensate_fractional_rows,  # noqa: E402
                          _fraction_row_ok, pack_repeats)
from h2g.sidfile import load_sid  # noqa: E402
from h2g.tracks import convert_tracks  # noqa: E402

ROOT = pathlib.Path(__file__).resolve().parents[2]
END = [0xFF, 0, 0, 0]


def _bar(rows: int = 16, every: int = 4, first_cmd=(0, 0)) -> list:
    """A drum-bar shaped pattern: a note every `every` rows, `$BD` holds."""
    out = []
    for r in range(rows):
        out += [0x75, 3, 0, 0] if r % every == 0 else [GT_NO_NOTE, 0, 0, 0]
    out[2:4] = list(first_cmd)
    return out + END


def _clock(track, patterns, start_value):
    """Calls each entry of `track` lasts, Goattracker's way: a row lasts the
    `CMD_SETTEMPO` value in effect at its tick 0 (gplay.c:325/494)."""
    v, out = start_value, []
    for e in track:
        pat = patterns[e]
        n = 0
        for r in range(0, len(pat), 4):
            if pat[r] == 0xFF:
                break
            if pat[r + 2] == CMD_SETTEMPO:
                v = pat[r + 3]
            n += v
        out.append(n)
    return out, v


# --- the pass on hand-built patterns ---------------------------------------

def test_the_accumulator_tracks_the_exact_clock_within_a_call():
    # Six distinct 16-row bars at R = 3 (5.333 calls), the change written as
    # 5 on the first: uncompensated they would run 6 x 5.33 = 32 calls fast.
    patterns = [_bar(first_cmd=(CMD_SETTEMPO, 5))] + [_bar() for _ in range(5)]
    for k in range(1, 6):                 # make them distinct patterns
        patterns[k][0] = 0x75 + k
    track = [0, 1, 2, 3, 4, 5]
    done, left = _compensate_fractional_rows(
        track, {0: 0}, {0: 16 / 3}, patterns, {})
    assert done == 6
    calls, end_value = _clock(track, patterns, 5)
    cum, ideal = 0, 0.0
    for n in calls:
        cum += n
        ideal += 16 * 16 / 3
        assert abs(cum - ideal) <= 0.5 + 1e-9, (cum, ideal)
    assert abs(left) <= 0.5 + 1e-9
    assert end_value == 5                 # every copy restores the change


def test_runs_sit_on_hold_rows_whose_neighbour_is_free():
    patterns = [_bar(first_cmd=(CMD_SETTEMPO, 5)), _bar()]
    track = [0, 1]
    _compensate_fractional_rows(track, {0: 0}, {0: 16 / 3}, patterns, {})
    for e in track:
        assert e >= 2                      # both entries now name a copy
        pat = patterns[e]
        rows = [r // 4 for r in range(4, len(pat) - 4, 4)
                if pat[r + 2] == CMD_SETTEMPO]
        assert len(rows) == 2, rows
        for k in rows:
            assert pat[4 * k] == GT_NO_NOTE and pat[4 * k + 1] == 0
            assert pat[4 * k - 2] == 0     # the previous row's column free
            assert k % 4 != 0              # never a note row of the bar
    # The originals are untouched: other positions play them at other tempos.
    assert patterns[1] == _bar()


def test_a_repeated_run_keeps_one_copy_so_it_still_packs():
    patterns = [_bar(first_cmd=(CMD_SETTEMPO, 5)), _bar()]
    track = [0, 1, 1, 1, 1]
    _compensate_fractional_rows(track, {0: 0}, {0: 16 / 3}, patterns, {})
    assert len(set(track[1:])) == 1
    assert len(pack_repeats(track)) == 3   # entry, repeat command, pattern


def test_an_entry_with_no_usable_rows_is_left_and_its_error_carried():
    # Every hold row's command column is taken: nothing may be written, and
    # the shortfall is carried to the next entry instead of dropped.
    busy = _bar(first_cmd=(CMD_SETTEMPO, 5))
    for r in range(1, 16):
        busy[4 * r + 2:4 * r + 4] = [4, 0]
    patterns = [busy, _bar()]
    track = [0, 1]
    _compensate_fractional_rows(track, {0: 0}, {0: 16 / 3}, patterns, {})
    assert track[0] == 0
    calls, _ = _clock(track, patterns, 5)
    assert calls[0] == 80
    # 2 x 85.33 = 170.67: the second entry takes both entries' remainders.
    assert sum(calls) == 171


def test_the_row_rule_reads_the_previous_column():
    pat = _bar()
    assert _fraction_row_ok(pat, 1, 16)
    assert not _fraction_row_ok(pat, 0, 16)        # row 0: the clock's
    assert not _fraction_row_ok(pat, 4, 16)        # a note row
    pat[4 * 2 + 2:4 * 2 + 4] = [4, 0]
    assert not _fraction_row_ok(pat, 2, 16)        # its own column taken
    assert not _fraction_row_ok(pat, 3, 16)        # its neighbour's taken


# --- the values, on the file that carries them -----------------------------

@needs_corpus
def test_the_written_value_is_the_exact_one_rounded():
    sid, det = _detect_tables(load_sid(str(CORPUS / "Rasputin.sid")),
                              lambda *a, **k: None)
    raw: list = []
    convert_tracks(sid, det, lambda *a, **k: None, None, raw)
    calls = orderlist_tempo_calls(sid, det, raw, "auto", True)
    values = orderlist_tempo_values(sid, det, raw, "auto", True)
    exact = {at: 2 * (r + 1) / r * 2 for at, r in raw[2].items()}
    assert calls[2] == exact
    assert values[2] == {at: round(c) for at, c in exact.items()}


def _rasputin_song():
    import songview
    sys.path.insert(0, str(ROOT / "python"))
    import fidelity as F
    doc = json.loads((ROOT / "presets.json").read_text(encoding="utf-8"))
    opts = F._preset_opts(doc, "Rasputin.sid")
    return songview.parse_sng(convert(str(CORPUS / "Rasputin.sid"),
                                      log=lambda *a, **k: None, **opts))


def _voice2_clock_error(song, raw2):
    exact = [2 * (r + 1) / r * 2 for _at, r in sorted(raw2.items())]
    k, v, c = -1, None, None
    ours = ideal = 0.0
    worst = 0.0
    rep = 1
    for e in song.tracks[2]:
        if e == 0xFF:
            break
        if 0xD0 <= e <= 0xDF:
            rep = e - 0xD0 + 1
            continue
        if e >= 0xE0:
            continue
        pat = song.patterns[e]
        plays, rep = rep, 1
        for _ in range(plays):
            for r in range(0, len(pat), 4):
                if pat[r] == 0xFF:
                    break
                if pat[r + 2] == CMD_SETTEMPO:
                    v = pat[r + 3]
                    if r == 0:
                        k += 1
                        c = exact[k]
                ours += v
                ideal += c
                worst = max(worst, abs(ours - ideal))
    return k + 1, worst, ours - ideal


@needs_corpus
def test_rasputin_s_clock_stays_on_the_player_s():
    """Voice 2's first pass, read back from the finished .sng (songview, a
    second reader), row by row against `2 * (R+1)/R * 2` calls for the `$FE`
    in effect. Uncompensated (v0.5.509) the gap ran -217.6 .. +145.1 calls
    over the pass (-109 .. +73 frames at -S2) and ended 145 calls out;
    compensated it read -6.3 .. +6.7 (about 3 frames) and ended +0.07. The
    widest excursion is the R = 6 entry whose last 32 rows carry a
    portamento on every row, so no run can sit there."""
    sid, det = _detect_tables(load_sid(str(CORPUS / "Rasputin.sid")),
                              lambda *a, **k: None)
    raw: list = []
    convert_tracks(sid, det, lambda *a, **k: None, None, raw)
    changes, worst, last = _voice2_clock_error(_rasputin_song(), raw[2])
    assert changes == len(raw[2]) == 8
    assert worst <= 8.0, worst
    assert abs(last) <= 1.0, last
