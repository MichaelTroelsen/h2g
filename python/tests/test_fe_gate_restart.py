"""Rasputin's `$FE nn` restarts the outer gate's count, not only its reload.

The handler at `$C09D` is `LDA (ptr),Y / STA $C539 / STA $C53A`: the operand
goes into the reload cell AND the counter the play entry `DEC`s
(`$C012 DEC $C53A / BPL work / LDA $C539 / STA $C53A / JMP exit`). So every
tempo change starts a fresh cycle -- R working calls, then the skip -- and
the skip the old cycle was working towards is never made. Each segment is
`W / R - (W - 1) // R` frames shorter (0 < that <= 1) than the average row
`2 * (R+1)/R` says, and through v0.5.516 the converter compensated towards
the average: the matched-attack offset crept 8 -> 11 frames across the 180 s
window against a startup lag of 7 (`drift` +0.27 per 1000, `drift_lag` 8.1).
Read as a restart it is 7 in every 500-frame window (drift 0.0). The
figures are in docs/H2G-CONVERSION-METHOD.md beside
`patterns._compensate_fractional_rows`.
"""
import dataclasses
import hashlib
import json
import pathlib
import sys

import pytest

from corpus import CORPUS, needs_corpus  # noqa: E402

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[1]))

from h2g import detect as D  # noqa: E402
from h2g.convert import _detect_tables, convert  # noqa: E402
from h2g.goatwriter import (CMD_SETTEMPO, orderlist_tempo_calls,  # noqa: E402
                            orderlist_tempo_clocks, restarted_gate_calls)
from h2g.patterns import GT_NO_NOTE, _compensate_fractional_rows  # noqa: E402
from h2g.sidfile import load_sid  # noqa: E402
from h2g.tracks import convert_tracks  # noqa: E402

ROOT = pathlib.Path(__file__).resolve().parents[2]
RASPUTIN = CORPUS / "Rasputin.sid"
END = [0xFF, 0, 0, 0]


def _bar(rows: int = 16, every: int = 4, first_cmd=(0, 0), note=0x75) -> list:
    """A drum-bar shaped pattern: a note every `every` rows, `$BD` holds."""
    out = []
    for r in range(rows):
        out += [note, 3, 0, 0] if r % every == 0 else [GT_NO_NOTE, 0, 0, 0]
    out[2:4] = list(first_cmd)
    return out + END


def _entry_calls(track, patterns, start_value):
    """Calls each entry lasts, Goattracker's way (gplay.c:325/494)."""
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
    return out


def _emulated_gate(frames: int, reload: int, rows: int) -> int:
    """Frames from the change to row `rows`, by stepping the player's bytes.

    Frame 0 is the fetch call that reads `$FE nn` (a working call: the gate
    let it through) and leaves the counter at the operand. Each later call
    is `DEC counter / BPL work`, and a counter that went negative is
    reloaded and the call skipped. A row is `frames` working calls.
    """
    counter = reload & 0xFF
    frame = work = 0
    while work < frames * rows:
        frame += 1
        counter = (counter - 1) & 0xFF
        if counter < 0x80:
            work += 1
        else:
            counter = reload & 0xFF
    return frame


# --- the clock, against the player's own instructions ----------------------

@pytest.mark.parametrize("reload", [1, 2, 3, 5, 6, 10, 60, 120, 0x7F])
@pytest.mark.parametrize("frames", [1, 2, 3])
def test_the_restarted_clock_is_the_gate_stepped_call_by_call(frames, reload):
    for mult in (1, 2, 3):
        for rows in range(0, 400):
            assert (restarted_gate_calls(frames, reload, mult, rows)
                    == mult * _emulated_gate(frames, reload, rows)), \
                (frames, reload, mult, rows)


def test_a_segment_is_up_to_one_frame_short_of_the_average():
    for reload in (2, 3, 5, 10, 60, 120):
        for rows in range(1, 3000):
            w = 2 * rows
            short = w * (reload + 1) / reload - restarted_gate_calls(
                2, reload, 1, rows)
            assert 0 < short <= 1 + 1e-9, (reload, rows, short)
    # R = 2 on an even segment drops exactly one frame, and it is the first
    # row's: rows of 2, 3, 3, 3 ... frames.
    assert [restarted_gate_calls(2, 2, 1, j) for j in range(5)] == [
        0, 2, 5, 8, 11]


# --- the original's own trace ----------------------------------------------

@needs_corpus
def test_the_original_s_attacks_sit_on_the_restarted_grid():
    """Rasputin subtune 0 opens on `$FE 02`, and `$FE 03` follows after 384
    rows. Every attack of every voice in the first 30 s sits on a row start
    of the RESTARTED clock -- 3j - 1 frames into the R = 2 segment, and the
    R = 3 segment starting at frame 1151 = 3 * 384 - 1 -- where the average
    row would put R = 2's rows on multiples of 3 and the change at 1152."""
    sys.path.insert(0, str(ROOT / "python"))
    import fidelity as F
    trace = F.run_siddump(RASPUTIN, 30, 0)
    start1 = restarted_gate_calls(2, 2, 1, 384)
    assert start1 == 1151
    grid0 = {restarted_gate_calls(2, 2, 1, j) for j in range(385)}
    grid1 = {start1 + restarted_gate_calls(2, 3, 1, j) for j in range(200)}
    for v in range(3):
        rel = [f - trace[v].attack_frames[0] for f in trace[v].attack_frames]
        seg0 = [f for f in rel if f < start1]
        seg1 = [f for f in rel if start1 <= f < 1500]
        assert len(seg0) > 50 and len(seg1) > 20, (v, len(seg0), len(seg1))
        assert all(f in grid0 for f in seg0), (v, [f for f in seg0
                                                   if f not in grid0])
        assert all(f in grid1 for f in seg1), (v, [f for f in seg1
                                                   if f not in grid1])
        # The average row's grid holds the opening attack and no other.
        assert [f for f in seg0 if f % 3 == 0] == [0], v
        assert seg1[0] == start1


# --- the reading -----------------------------------------------------------

@needs_corpus
def test_only_rasputin_restarts_its_gate():
    restart, command = [], []
    for p in sorted(CORPUS.glob("*.sid"), key=lambda q: q.name.lower()):
        sid = load_sid(str(p))
        if D._find_fe_gate_restart(sid):
            restart.append(p.name)
        if D.TRACK_FE_COMMAND.search(sid.data):
            command.append(p.name)
    assert restart == command == ["Rasputin.sid"]


class _Image:
    def __init__(self, data):
        self.data = data


@needs_corpus
def test_a_handler_that_stores_elsewhere_is_not_a_restart():
    data = bytearray(load_sid(str(RASPUTIN)).data)
    assert D._find_fe_gate_restart(_Image(bytes(data)))
    m = D.TRACK_FE_COMMAND.search(data)
    assert bytes(data[m.start(5):m.end(5)]) == b"\x3a\xc5"   # STA $C53A
    other = bytearray(data)
    other[m.start(5)] = 0x3B                    # STA $C53B: some other cell
    assert not D._find_fe_gate_restart(_Image(bytes(other)))
    g = D.FE_OUTER_GATE.search(data)
    assert bytes(data[g.start(1):g.end(1)]) == b"\x3a\xc5"   # DEC $C53A
    moved = bytearray(data)
    moved[g.start(1)] = moved[g.start(3)] = 0x3C   # the gate counts $C53C
    assert not D._find_fe_gate_restart(_Image(bytes(moved)))


@needs_corpus
def test_rasputin_s_clocks_are_its_operands():
    sid, det = _detect_tables(load_sid(str(RASPUTIN)), lambda *a, **k: None)
    assert det.track_fe_command and det.track_fe_restarts_gate
    raw: list = []
    convert_tracks(sid, det, lambda *a, **k: None, None, raw)
    clocks = orderlist_tempo_clocks(sid, det, raw, "auto", True)
    assert clocks[2] == {at: (2, r, 2) for at, r in raw[2].items()}
    assert sorted(raw[2].values()) == sorted([2, 3, 5, 10, 60, 120, 6, 2])
    # The average is unchanged: it is still what the change is rounded from.
    calls = orderlist_tempo_calls(sid, det, raw, "auto", True)
    assert calls[2] == {at: 2 * (r + 1) / r * 2 for at, r in raw[2].items()}
    # A player whose handler only reloads gets no clock, so it keeps the
    # average row it had.
    plain = dataclasses.replace(det, track_fe_restarts_gate=False)
    assert all(m == {} for m in orderlist_tempo_clocks(sid, plain, raw,
                                                       "auto", True))
    # An operand BPL reads as negative is not the count the clock models.
    hi = orderlist_tempo_clocks(sid, det, [{}, {}, {0: 0x80, 5: 0x7F}],
                                "auto", True)
    assert hi[2] == {5: (2, 0x7F, 2)}


# --- the pass --------------------------------------------------------------

def test_the_pass_spends_the_restart_s_lost_frame():
    """Six distinct 16-row bars at R = 2 (2 frames a row, -S2): 6 calls a row
    on average AND written, so the average leaves nothing to do -- but the
    restart drops 2 calls from the segment, and the pass must spend them."""
    def fresh():
        pats = [_bar(first_cmd=(CMD_SETTEMPO, 6))]
        pats += [_bar(note=0x76 + k) for k in range(5)]
        return pats, [0, 1, 2, 3, 4, 5]
    patterns, track = fresh()
    done, left = _compensate_fractional_rows(track, {0: 0}, {0: 6.0},
                                             patterns, {})
    assert (done, left) == (0, 0.0)
    assert track == [0, 1, 2, 3, 4, 5]
    patterns, track = fresh()
    done, left = _compensate_fractional_rows(track, {0: 0}, {0: 6.0},
                                             patterns, {},
                                             clocks={0: (2, 2, 2)})
    assert done == 1 and left == 0.0
    cum = 0
    for k, n in enumerate(_entry_calls(track, patterns, 6)):
        cum += n
        assert cum == restarted_gate_calls(2, 2, 2, 16 * (k + 1)), (k, cum)


def test_a_repeated_run_is_costed_once_for_all_its_plays():
    """R = 3: the first bar is 84 calls on the restarted clock (2 * (32 +
    31 // 3)), the three repeats 256 between them (340 - 84) -- 85.33 a
    play, so one shared copy at 85 and a call left over, never more."""
    patterns = [_bar(first_cmd=(CMD_SETTEMPO, 5)), _bar(note=0x76)]
    track = [0, 1, 1, 1]
    done, left = _compensate_fractional_rows(track, {0: 0}, {0: 16 / 3},
                                             patterns, {},
                                             clocks={0: (2, 3, 2)})
    assert len(set(track[1:])) == 1
    calls = _entry_calls(track, patterns, 5)
    assert calls == [84, 85, 85, 85], calls
    assert sum(calls) - restarted_gate_calls(2, 3, 2, 64) == -1
    assert left == pytest.approx(-1.0)


def test_an_entry_the_pass_leaves_still_moves_the_clock_on():
    """The first entry changes its own tempo past row 0, so the pass cannot
    read it and keeps the accumulator; the second must still be read 16 rows
    into the segment (96 calls, nothing to do), not at its start (94)."""
    busy = _bar(first_cmd=(CMD_SETTEMPO, 6))
    busy[4 * 5 + 2:4 * 5 + 4] = [CMD_SETTEMPO, 6]
    patterns = [busy, _bar(note=0x76)]
    track = [0, 1]
    done, left = _compensate_fractional_rows(track, {0: 0}, {0: 6.0},
                                             patterns, {},
                                             clocks={0: (2, 2, 2)})
    assert track == [0, 1] and done == 0 and left == 0.0


# --- the file --------------------------------------------------------------

def _rasputin_bytes() -> bytes:
    sys.path.insert(0, str(ROOT / "python"))
    import fidelity as F
    doc = json.loads((ROOT / "presets.json").read_text(encoding="utf-8"))
    opts = F._preset_opts(doc, "Rasputin.sid")
    return convert(str(RASPUTIN), log=lambda *a, **k: None, **opts)


@needs_corpus
def test_the_reading_is_what_moves_rasputin(monkeypatch):
    """With the reading forced off the file is converted towards the average
    row again; the two .sng differ, and only the restarted one stays on the
    player's clock (test_fractional_row_tempo reads it row by row)."""
    import songview
    from test_fractional_row_tempo import _voice2_clock_error
    sid, det = _detect_tables(load_sid(str(RASPUTIN)), lambda *a, **k: None)
    raw: list = []
    convert_tracks(sid, det, lambda *a, **k: None, None, raw)
    on = _rasputin_bytes()
    monkeypatch.setattr(D, "_find_fe_gate_restart", lambda sid: False)
    off = _rasputin_bytes()
    assert hashlib.sha1(on).digest() != hashlib.sha1(off).digest()
    _n, worst_on, last_on = _voice2_clock_error(songview.parse_sng(on), raw[2])
    _n, worst_off, last_off = _voice2_clock_error(songview.parse_sng(off),
                                                  raw[2])
    assert abs(last_on) <= 1.0, last_on
    # Off, the pass lands every segment on the average: 6.5 frames late on
    # the player's clock by the end of the first pass.
    assert last_off >= 10.0, last_off
    assert worst_off > worst_on
