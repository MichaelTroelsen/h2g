"""The `$1003` family's per-record vibrato delay, and the held program that
takes Lion_Heart's `$2B` records (lion-heart-vibrato-depth-short-travel;
figures historical, v0.5.670 base, -t 180).

Ahead of the split the six files carry a second per-voice countdown:

    1486  LDA $1A5E,X / BEQ + / DEC $1A5E,X / JMP $154A   ; skip update AND store
    1491  LDA #imm / PHA                                    ; the split

whose cell is written at every note fetch from a patched immediate fed from
record +14 (`LDA $1B59,X / STA $1304`). The oscillator is silent for `delay +
1` frames from the note where the record says so, longer than the `$1ACE,X <
4` age gate. Lion_Heart's records read 0, 5 and 13 (measured: voice 0's
`$0AF9` first moves at frame 6 and voice 1's `$0FB9` at frame 14, ours at 4).

`vibrato_hold.RECORD_HOLD` takes Lion_Heart's `$0AC4` and `$0AF9` records
(vibrato byte `$2B`) as frame-held programs, the one encoding that does not
divide the step by the call rate: at `-S3` the speed-table entry rounds
`log2(3)` to a step of `interval >> (shift + 2)` and the swing falls to 0.70 of
the player's, and the tick-0 skip costs another 1/8.
"""
import json
import pathlib
import sys

import pytest

from corpus import CORPUS, needs_corpus

PYTHON_ROOT = pathlib.Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PYTHON_ROOT))
import fidelity                                               # noqa: E402
import songview                                               # noqa: E402
from h2g import vibrato_hold as vh                            # noqa: E402
from h2g.convert import convert                               # noqa: E402
from h2g.detect import (_find_vibrato_delay_offset,           # noqa: E402
                        _find_vibrato_site, detect)
from h2g.sidfile import load_sid                              # noqa: E402

PRESETS = PYTHON_ROOT.parent / "presets.json"
SIX = ("Go_Go_Dash", "Lakers_vs_Celtics", "Lion_Heart", "Pacific_Coast",
       "Radio_ACE", "Sun_Never_Shines")


def _det(name):
    return detect(load_sid(str(CORPUS / f"{name}.sid")), lambda *a, **k: None)


@needs_corpus
def test_lion_heart_reads_the_delay_byte_at_record_plus_14():
    sid = load_sid(str(CORPUS / "Lion_Heart.sid"))
    det = detect(sid, lambda *a, **k: None)
    assert det.vibrato_delay_offset == 14
    delays = [sid.data[det.instr_start + r * det.instr_stride + 14]
              for r in (4, 5, 7)]
    assert delays == [0, 13, 5]


@needs_corpus
def test_exactly_the_six_read_a_record_delay():
    got = set()
    for path in sorted(CORPUS.glob("*.sid")):
        sid = load_sid(str(path))
        try:
            det = detect(sid, lambda *a, **k: None)
        except Exception:                                  # noqa: BLE001
            continue
        if det.vibrato_offset is None:
            assert det.vibrato_delay_offset is None, path.stem
            continue
        site = _find_vibrato_site(sid, det)
        found = (site is not None and _find_vibrato_delay_offset(
            sid, det, site[1]) is not None)
        assert found == (det.vibrato_delay_offset is not None), path.stem
        if found:
            got.add(path.stem)
    assert got == set(SIX), got ^ set(SIX)


def _records(sng):
    return songview.parse_sng(sng).instruments


def _convert(name, **extra):
    doc = json.loads(PRESETS.read_text())
    lines = []
    sng = convert(str(CORPUS / f"{name}.sid"), log=lines.append,
                  **dict(fidelity._preset_opts(doc, name + ".sid"), **extra))
    return sng, lines


@needs_corpus
def test_lion_heart_takes_its_three_2b_records_without_the_option():
    sng, lines = _convert("Lion_Heart")
    assert any("Frame-held vibrato" in m and "3 record(s)" in m
               for m in lines)
    held = {i.name for i in _records(sng) if not i.vib_ptr
            and i.name.split(":")[1].startswith("2B")}
    assert held == {"06:2B-10-20", "09:2B-44-04", "10:2B-10-20"}


def _first_step_call(wtbl, start):
    """Calls ahead of the first `F4 nn` vibrato step of the program at the
    1-based row `start` (a delay row `d` holds `d + 1` calls)."""
    calls = 0
    for left, _right in wtbl[start - 1:]:
        if left == 0xF4:
            return calls
        calls += left + 1 if left <= 0x0F else 1
    return None


@needs_corpus
def test_the_held_records_wait_out_their_own_delay():
    """Record 7's delay byte is 5, so its first step is `5 + 1` frames (18
    calls at -S3) from the note; records 4 and 14 (delay 0) keep the frame
    lattice the age gate gives, 3 frames."""
    sng, _ = _convert("Lion_Heart")
    song = songview.parse_sng(sng)
    first = {i.name: _first_step_call(song.tables["WTBL"], i.wave_ptr)
             for i in song.instruments if i.name.split(":")[1].startswith("2B")}
    assert first == {"06:2B-10-20": 9, "09:2B-44-04": 18, "10:2B-10-20": 9}


@needs_corpus
def test_taking_the_dwell_gate_back_leaves_every_record_per_call(monkeypatch):
    monkeypatch.setattr(vh, "HOLD_DWELL", False)
    sng, lines = _convert("Lion_Heart")
    assert not any("Frame-held vibrato" in m for m in lines)
    assert all(i.vib_ptr for i in _records(sng)
               if i.name.split(":")[1].startswith("2B"))


@needs_corpus
def test_a_song_not_named_is_untouched_by_the_keyed_records():
    on, _ = _convert("Go_Go_Dash")
    assert vh.keyed_records(load_sid(str(CORPUS / "Go_Go_Dash.sid"))) is None
    off, _ = _convert("Go_Go_Dash", vibrato_hold=False)
    assert on == off


def _gt_walk(cmp_value, steps):
    """Position (in speed units) after each `CMD_VIBRATO` step, simulating
    gplay.c:777-801 with `vibtime` from 0: even adds, odd subtracts."""
    vibtime, pos, out = 0, 0, []
    for _ in range(steps):
        if vibtime < 0x80 and vibtime > cmp_value:
            vibtime ^= 0xFF
        vibtime = (vibtime + 2) & 0xFF
        pos += -1 if vibtime & 1 else 1
        out.append(pos)
    return out


@pytest.mark.parametrize("bound", [2, 3, 4, 5, 6, 7])
def test_the_dwell_frame_sits_on_the_top_of_the_walk(bound):
    prefix, cycle = vh.dwell_pattern(bound)
    frames = 6 * (2 * bound + 1)
    flags = list(prefix)
    while len(flags) < frames:
        flags += list(cycle)
    flags = flags[:frames]
    walk = _gt_walk(bound - 2, sum(flags))
    pos, series = 0, []
    steps = iter(walk)
    for moved in flags:
        pos = next(steps) if moved else pos
        series.append(pos)
    top = max(series)
    held = [i for i in range(1, frames) if series[i] == series[i - 1]]
    assert held, bound
    assert all(series[i] == top for i in held), (bound, series)
    # one held frame per `2 * bound + 1`: the player's period
    assert held[1] - held[0] == 2 * bound + 1, (bound, held)
