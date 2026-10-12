"""`regrid_park`: the whole calls of `regrid`'s debt are paid through a voice that
loops one pattern forever, and voice 0's schedule is left only the remainder.

`CMD_SETTEMPO` under `$80` lengthens a row for all three channels, so a pair in
ANY voice's pattern pays voice 0's debt. Star_Paws' voice 1 plays pattern 0
(65 rows) in a one-pattern loop; two pairs in a clone of it deliver 2 of the
2.047 calls a loop owes, evenly, where voice 0's patterns 57-64 (no free
command pair) dived the ledger to -23.8 calls. See `patterns._regrid_park`.
"""
import copy
import json
import pathlib
import sys

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[1]))
sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent))

from corpus import CORPUS, needs_corpus                      # noqa: E402
from h2g.goatwriter import CMD_SETTEMPO                      # noqa: E402
from h2g.patterns import (GT_END_PATTERN, MAX_PATTERNS,      # noqa: E402
                          _loop_pattern, _regrid_park, regrid_tempos)

ROOT = pathlib.Path(__file__).resolve().parents[2]


def _pattern(rows):
    out = []
    for _ in range(rows):
        out += [0x30, 1, 0, 0]
    return out + [GT_END_PATTERN, 0, 0, 0]


def _ups(pat, base):
    return sum(1 for r in range(len(pat) // 4)
               if pat[r * 4 + 2] == CMD_SETTEMPO and pat[r * 4 + 3] == base + 1)


def _case():
    """Subtune 0: voice 0 plays pattern 0 (94 rows, the end row counted) six
    times, voice 1 loops pattern 1 (65 rows), voice 2 is silent. Subtune 1's
    voice 1 plays pattern 1 too."""
    pats = [_pattern(93), _pattern(64), _pattern(93)]
    tracks = [[0, 0, 0, 0, 0, 0, 0xFF, 0], [0xF0, 1, 0xFF, 0], [0xFF, 0],
              [2, 0xFF, 0], [0xF0, 1, 0xFF, 0], [0xFF, 0]]
    return pats, tracks


def test_a_one_pattern_loop_is_recognised():
    assert _loop_pattern([0xF0, 7, 0xFF, 0]) == 7
    assert _loop_pattern([7, 0xFF, 0]) == 7
    assert _loop_pattern([0xD3, 7, 0xFF, 0]) == 7        # p played four times
    assert _loop_pattern([0xF0, 7, 0xFF, 1]) == 7        # restart AT p


def test_anything_else_is_not_a_loop():
    assert _loop_pattern([0xF0, 7, 8, 0xFF, 0]) is None   # two patterns
    assert _loop_pattern([0xF0, 7, 0xFF, 2]) is None      # restart past p
    assert _loop_pattern([0xD3, 7, 0xFF, 1]) is None      # inside the repeat
    assert _loop_pattern([0xF0, 7]) is None               # never loops
    assert _loop_pattern([0xFF, 0]) is None               # no pattern
    assert _loop_pattern([]) is None


def test_whole_calls_go_to_a_clone_and_the_remainder_is_left():
    pats, tracks = _case()
    orig1 = list(pats[1])
    d = 0.0315 / 2                                         # frames a row at -S2
    rest, n = _regrid_park(pats, tracks, 0, 4, d, 2)
    assert n == 2                                          # 65 * 0.0315 = 2.05
    assert len(pats) == 4 and pats[1] == orig1             # cloned, not edited
    assert tracks[1] == [0xF0, 3, 0xFF, 0]
    assert tracks[4] == [0xF0, 1, 0xFF, 0]                 # other subtune's
    assert _ups(pats[3], 4) == 2
    assert abs((d - rest) * 2 * 65 - 2) < 1e-9
    assert 0 < rest < d


def test_it_never_delivers_more_than_the_debt():
    for rate in (0.0315, 0.05, 0.1, 0.12):
        pats, tracks = _case()
        rest, n = _regrid_park(pats, tracks, 0, 4, rate / 2, 2)
        assert n / 65 <= rate + 1e-9, (rate, n)
        assert rest * 2 >= -1e-9


def test_a_loop_in_voice_2_is_found_too():
    pats = [_pattern(93), _pattern(64)]
    tracks = [[0, 0xFF, 0], [0xFF, 0], [0xF0, 1, 0xFF, 0]]
    rest, n = _regrid_park(pats, tracks, 0, 4, 0.0315 / 2, 2)
    assert n == 2 and tracks[2][1] == 2 and tracks[1] == [0xFF, 0]


def test_the_loop_that_takes_more_pairs_wins():
    """Voice 1 loops 16 rows (0.5 call: none), voice 2 loops 64 (2 calls)."""
    pats = [_pattern(93), _pattern(15), _pattern(64)]
    tracks = [[0, 0xFF, 0], [1, 0xFF, 0], [2, 0xFF, 0]]
    rest, n = _regrid_park(pats, tracks, 0, 4, 0.0315 / 2, 2)
    assert n == 2 and tracks[1] == [1, 0xFF, 0] and tracks[2][0] == 3
    pats = [_pattern(93), _pattern(64), _pattern(127)]
    tracks = [[0, 0xFF, 0], [1, 0xFF, 0], [2, 0xFF, 0]]
    rest, n = _regrid_park(pats, tracks, 0, 4, 0.0315 / 2, 2)
    assert n == 4 and tracks[2][0] == 3 and tracks[1] == [1, 0xFF, 0]


def test_a_loop_too_short_for_one_whole_call_is_left_alone():
    pats = [_pattern(93), _pattern(16)]
    tracks = [[0, 0xFF, 0], [0xF0, 1, 0xFF, 0], [0xFF, 0]]
    before = copy.deepcopy((pats, tracks))
    assert _regrid_park(pats, tracks, 0, 4, 0.0315 / 2, 2) == (0.0315 / 2, 0)
    assert (pats, tracks) == before


def test_no_looping_voice_changes_nothing():
    pats = [_pattern(93), _pattern(64)]
    tracks = [[0, 1, 0xFF, 0], [0, 1, 0xFF, 0], [0xFF, 0]]
    before = copy.deepcopy((pats, tracks))
    assert _regrid_park(pats, tracks, 0, 4, 0.05, 1) == (0.05, 0)
    assert (pats, tracks) == before


def test_a_full_pattern_table_is_not_grown():
    pats, tracks = _case()
    pats += [_pattern(3)] * (MAX_PATTERNS - len(pats))
    before = copy.deepcopy((pats, tracks))
    assert _regrid_park(pats, tracks, 0, 4, 0.05, 1) == (0.05, 0)
    assert (pats, tracks) == before


def test_regrid_tempos_off_is_the_bytes_it_always_wrote():
    pats, tracks = _case()
    a, b = copy.deepcopy(pats), copy.deepcopy(pats)
    ta, tb = copy.deepcopy(tracks), copy.deepcopy(tracks)
    regrid_tempos(a, ta, [4, 4], [0.0315 / 2, 0.0], 2)
    regrid_tempos(b, tb, [4, 4], [0.0315 / 2, 0.0], 2, park=False)
    assert (a, ta) == (b, tb)
    assert len(a) == 3


def test_regrid_tempos_counts_the_parked_rows_and_leaves_voice_0_the_rest():
    pats, tracks = _case()
    off, toff = copy.deepcopy(pats), copy.deepcopy(tracks)
    n_off = regrid_tempos(off, toff, [4, 4], [0.0315 / 2, 0.0], 2)
    n_on = regrid_tempos(pats, tracks, [4, 4], [0.0315 / 2, 0.0], 2, park=True)
    assert len(pats) == 4 and tracks[1][1] == 3
    assert _ups(pats[3], 4) == 2
    # six plays of 94 rows owe voice 0 about 0.4 calls once voice 1 pays 2.05
    # of every 2.05 per loop, against 17.8 on its own
    assert _ups(pats[0], 4) < _ups(off[0], 4)
    assert n_on == _ups(pats[0], 4) + _ups(pats[3], 4)
    assert n_off == _ups(off[0], 4) >= 1


def test_it_is_inert_without_regrid():
    from h2g.convert import convert
    assert (convert(str(ROOT / "Commando.sid"), log=lambda m: None,
                    regrid_park=True)
            == (ROOT / "Commando.sng").read_bytes())


def test_the_command_line_and_a_preset_entry_both_reach_convert(tmp_path,
                                                                monkeypatch):
    import h2g.cli as cli
    seen = {}

    def fake(path, log=None, **kw):
        seen.clear()
        seen.update(kw)
        return b"x"

    monkeypatch.setattr(cli, "convert", fake)
    out = tmp_path / "o.sng"
    sid = str(ROOT / "Commando.sid")
    cli.main([sid, "-o", str(out), "-q", "--regrid", "--regrid-park"])
    assert seen["regrid_park"] is True
    cli.main([sid, "-o", str(out), "-q"])
    assert seen["regrid_park"] is False
    presets = tmp_path / "p.json"
    presets.write_text(json.dumps({"always": {}, "songs": {
        "Commando.sid": {"regrid": True, "regrid_park": True}}}))
    cli.main([sid, "-o", str(out), "-q", "--presets", str(presets)])
    assert seen["regrid_park"] is True


def test_preset_opts_hands_the_toggle_through_and_no_song_adopts_it():
    import fidelity
    doc = {"always": {}, "songs": {"X.sid": {"regrid": True,
                                             "regrid_park": True}}}
    assert fidelity._preset_opts(doc, "X.sid")["regrid_park"] is True
    assert fidelity._preset_opts({"always": {}, "songs": {"X.sid": {}}},
                                 "X.sid")["regrid_park"] is False
    shipped = json.loads((ROOT / "presets.json").read_text(encoding="utf-8"))
    assert not shipped["always"].get("regrid_park")
    assert not any(e.get("regrid_park") for e in shipped["songs"].values())


# --- Star_Paws: the file that found it -------------------------------------

def _star_paws(monkeypatch, **force):
    import fidelity
    import h2g.convert as C
    doc = json.loads((ROOT / "presets.json").read_text(encoding="utf-8"))
    opts = fidelity._preset_opts(doc, "Star_Paws.sid")
    opts.update(regrid=True, regrid_per_play=True)
    opts.update(force)
    seen = {}
    real = regrid_tempos        # not C's: an earlier call's spy is in its place

    def spy(patterns, tracks, bases, deficits, multiplier=1, log=None, **kw):
        seen["before"] = copy.deepcopy(patterns)
        r = real(patterns, tracks, bases, deficits, multiplier, log, **kw)
        seen.update(out=copy.deepcopy(patterns), tracks=copy.deepcopy(tracks),
                    base=bases[0], owed=deficits[0] * multiplier)
        return r

    monkeypatch.setattr(C, "regrid_tempos", spy)
    C.convert(str(CORPUS / "Star_Paws.sid"), log=lambda m: None, **opts)
    return seen


def _ledger(seen):
    """Calls delivered minus owed at every voice-0 play boundary, voice 0's
    rows plus whatever voice 1's loop has fired by then."""
    from h2g.patterns import _regrid_order
    out_p, tr, base = seen["out"], seen["tracks"], seen["base"]
    loop_p = _loop_pattern(tr[1])
    loop_rows = len(out_p[loop_p]) // 4
    loop_ups = _ups(out_p[loop_p], base)
    led, rows, out = 0.0, 0, []
    for p in _regrid_order(tr[0], len(out_p)):
        n = len(out_p[p]) // 4
        rows += n
        led += _ups(out_p[p], base) - seen["owed"] * n
        out.append(led + loop_ups * (rows // loop_rows))
    return out


@needs_corpus
def test_star_paws_voice_1_pays_the_trough_and_the_other_subtune_keeps_its_clock(
        monkeypatch):
    """Measured at 5c5e0c0, `regrid` + `regrid_per_play` forced: voice 0's
    ledger dives to -23.8 calls; with the park it never leaves a few calls of
    zero, the index-paired attack offset going -12/+1 -> -1/+1 frames."""
    plain = _star_paws(monkeypatch)
    parked = _star_paws(monkeypatch, regrid_park=True)
    assert min(_ledger(plain)) < -20                          # voice 0 alone
    assert len(parked["out"]) == len(plain["out"]) + 1
    new = len(parked["out"]) - 1
    assert parked["tracks"][1][1] == new
    assert _ups(parked["out"][new], parked["base"]) == 2
    # pattern 0 is subtune 2's voice 1, with its own clock: untouched
    assert parked["out"][0] == parked["before"][0]
    assert parked["tracks"][7] == plain["tracks"][7] == [0xFC, 0, 0xFF, 0]
    led = _ledger(parked)
    assert min(led) > -4 and max(led) < 4, (min(led), max(led))


@needs_corpus
def test_star_paws_voice_0_owes_the_remainder_only(monkeypatch):
    from h2g.patterns import _regrid_order
    plain = _star_paws(monkeypatch)
    parked = _star_paws(monkeypatch, regrid_park=True)

    def delivered(seen):
        return sum(_ups(seen["out"][p], seen["base"])
                   for p in _regrid_order(seen["tracks"][0], len(seen["out"])))

    assert delivered(plain) > 140            # 147.28 calls a pass owed
    assert delivered(parked) < 10            # 3.4 left after voice 1's 2 pairs
