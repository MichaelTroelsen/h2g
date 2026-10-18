"""International_Karate's doubled melody: voices 1 and 3 on one note and one
vibrato record, two counter updates apart (h2g.unison_vibrato).

User report 2026-10-18: "at 0:08 the two voices should be slightly off each
other, giving a roaming sound". Traced (siddump-rt -a0, PAL), frames 425-432:

    original  v1 14AF 148B 1467 148B 14AF 14D3 14F7 151B
              v3 14AF 14D3 14AF 148B 1467 148B 14AF 14D3
    ours      v1 = v3 on every frame (14B3 14C7 14EF 1513 14FB ...)

The counters `$B2DD,X` / directions `$B2FF,X` are written only by the update
at `$AFF7`; the image holds 02 01 04 / FF 00 FF and nothing before frame 425
runs a vibrato record on voices 1 or 3, so voice 3 sits two updates behind
voice 1 for the whole doubled passage (frames 425-1270).
"""
import pathlib
import sys

import pytest

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[1]))

import fidelity                                              # noqa: E402
import songview                                              # noqa: E402
from corpus import CORPUS, needs_corpus                      # noqa: E402
from h2g import unison_vibrato as uv                         # noqa: E402
from h2g.convert import convert                              # noqa: E402
from h2g.detect import detect                                # noqa: E402
from h2g.sidfile import load_sid                             # noqa: E402

REPO_ROOT = pathlib.Path(__file__).resolve().parents[2]
PRESETS = REPO_ROOT / "presets.json"
IK = "International_Karate.sid"

needs_tools = pytest.mark.skipif(
    not (pathlib.Path(fidelity.SIDDUMP).exists()
         and pathlib.Path(fidelity.GT2RELOC).exists()),
    reason="no siddump-rt or gt2reloc on this machine")


def _opts(name, on):
    import json
    doc = json.loads(PRESETS.read_text())
    return dict(fidelity._preset_opts(doc, name), unison_vibrato_phase=on)


def _sid(name):
    sid = load_sid(str(CORPUS / name))
    return sid, detect(sid, lambda m: None)


@needs_corpus
def test_the_counter_cells_and_their_image_bytes():
    sid, det = _sid(IK)
    assert uv.counter_cells(sid, det) == (0xB2DD, 0xB2FF)
    d = sid.data
    assert [d[sid.to_offset(0xB2DD + v)] for v in range(3)] == [2, 1, 4]
    assert [d[sid.to_offset(0xB2FF + v)] for v in range(3)] == [0xFF, 0, 0xFF]


def test_the_step_walks_the_traced_counters():
    """siddump-rt -w b2dd,b2df,...: from the image, the counter on the frames
    after the fetch at 425 (433 is the outer gate's skipped call)."""
    def walk(state, n):
        out = []
        for _ in range(n):
            state = uv.step(state[0], state[1], 5)
            out.append(state[0])
        return out
    assert walk((2, 0xFF), 9) == [1, 0, 1, 2, 3, 4, 5, 4, 3]
    assert walk((4, 0xFF), 9) == [3, 2, 1, 0, 1, 2, 3, 4, 5]
    assert uv.lag((2, 0xFF), (4, 0xFF), 5) == 2


def test_the_goattracker_period_is_twice_cmp_plus_two():
    # gplay.c:795-801 at the shipped IK entry ($B3: cmp $33).
    assert uv._gt_period(0x33) == 106


@needs_corpus
def test_voice_three_lags_on_every_doubled_note():
    sid, det = _sid(IK)
    blob = convert(str(CORPUS / IK), log=lambda m: None, **_opts(IK, False))
    got = uv.doubled_note_delays(blob, sid, det)
    assert len(got) == 7
    assert {k[0] for k in got} == {2}                # track 2: voice 3
    assert set(got.values()) == {(7, 2)}             # GT record 7, 2 updates


@needs_corpus
def test_the_lagging_voice_plays_a_later_vibdelay_clone():
    off = convert(str(CORPUS / IK), log=lambda m: None, **_opts(IK, False))
    lines = []
    on = convert(str(CORPUS / IK), log=lines.append, **_opts(IK, True))
    a, b = songview.parse_sng(off), songview.parse_sng(on)
    base = a.instruments[6]                          # GT 7, record 6's
    assert base.vib_ptr and base.vib_delay == 11
    clones = [i for i in b.instruments
              if i.name == base.name and i.number != base.number]
    assert len(clones) == 1
    c = clones[0]
    assert c.vib_delay == base.vib_delay + 21        # 2/10 of 106 calls
    assert (c.ad, c.sr, c.wave_ptr, c.pulse_ptr, c.vib_ptr, c.gatetimer,
            c.firstwave) == (base.ad, base.sr, base.wave_ptr, base.pulse_ptr,
                             base.vib_ptr, base.gatetimer, base.firstwave)
    assert b.tracks[0] == a.tracks[0]                # voice 1 untouched
    assert b.tracks[2] != a.tracks[2]
    assert len(b.patterns) == len(a.patterns) + 3
    assert any("Doubled-note vibrato" in m for m in lines)


def test_off_by_default():
    import inspect
    p = inspect.signature(convert).parameters["unison_vibrato_phase"]
    assert p.default is False


@needs_corpus
def test_thrust_is_declined_for_its_start_records():
    """Thrust starts its voices on records 23, 26, 21 (vibrato bytes $00,
    $30, $11), so the calls before the first fetch step voices 2 and 3 and
    not voice 1 (traced: frame 1 moves $0CCF/$0CD0 only). No pair is in
    lockstep from the image."""
    sid, det = _sid("Thrust.sid")
    assert uv.counter_cells(sid, det) == (0x0CCE, 0x0CEE)
    blob = convert(str(CORPUS / "Thrust.sid"), log=lambda m: None,
                   **_opts("Thrust.sid", False))
    assert uv.doubled_note_delays(blob, sid, det) == {}


@needs_corpus
def test_an_init_time_clear_declines():
    """Shockway_Rider's `$FB34 STA $ED00,X` clears the counters, so the image
    bytes are not the start state."""
    sid, det = _sid("Shockway_Rider.sid")
    at = sid.to_offset(0xFB34)
    assert bytes(sid.data[at:at + 3]) == bytes([0x9D, 0x00, 0xED])
    assert uv.counter_cells(sid, det) is None


@needs_corpus
def test_forced_on_only_international_karate_moves():
    """Corpus byte-hash, option forced on under presets: IK is the one mover
    (C:/t/ik-chorus/hash.py, 2026-10-18). Here: every file the update is
    read on, other than IK, has nothing to emit."""
    movers = []
    for path in sorted(CORPUS.glob("*.sid")):
        try:
            sid, det = _sid(path.name)
        except Exception:                            # noqa: BLE001
            continue
        if uv.counter_cells(sid, det) is None:
            continue
        try:
            blob = convert(str(path), log=lambda m: None,
                           **_opts(path.name, False))
        except Exception:                            # noqa: BLE001
            continue
        if uv.doubled_note_delays(blob, sid, det):
            movers.append(path.name)
    assert movers == [IK]


def _freqs(trace, n):
    return [fidelity.register_timeline(v.freq_events, n) for v in trace]


@needs_corpus
@needs_tools
def test_the_doubled_passage_is_a_chorus(tmp_path):
    """Packed at -S10 and traced: over frames 428-500 (startup lag 3) the
    original's voices 1 and 3 differ on most frames; ours were equal on
    every one and now differ on most, voice 3 trailing voice 1 by ~2 frames."""
    n = 30 * 50
    orig = _freqs(fidelity.run_siddump(CORPUS / IK, 30, 0), n)
    sides = {}
    for on in (False, True):
        sng, _ = fidelity.legalise_restarts(
            convert(str(CORPUS / IK), log=lambda m: None, **_opts(IK, on)))
        wd = tmp_path / str(on)
        wd.mkdir()
        packed = fidelity.pack_sid(sng, wd, fidelity.GT2RELOC, 10,
                                   original=CORPUS / IK)
        assert packed is not None
        sides[on] = _freqs(fidelity.run_siddump(packed, 30, 0, calls=10), n)
    span = range(428, 500)
    o = sum(orig[0][f] != orig[2][f] for f in span)
    off = sum(sides[False][0][f + 3] != sides[False][2][f + 3] for f in span)
    on = sum(sides[True][0][f + 3] != sides[True][2][f + 3] for f in span)
    assert o >= 55
    assert off == 0
    assert on >= 55
    # voice 3 is voice 1 two frames late, within a register step
    late = sum(abs(sides[True][2][f + 5] - sides[True][0][f + 3]) <= 0x30
               for f in range(440, 500))
    assert late >= 50
