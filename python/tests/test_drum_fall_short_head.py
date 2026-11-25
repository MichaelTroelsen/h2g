"""`drum_fall`'s short head: a two-row drum note on a 3-call row.

Tarzan's voice-2 kick-less drum ($0407, 1500 hits in subtune 0's first 180 s) is
a note row and ONE rest row: the original gates off and falls $0080 on the
first frame of the second tick and again on each of the next two (frames
3, 4, 5 after the attack). The gate-off head (`gate on, gate off, two steps,
chain`) holds the first frame one step high -- its call is the gate-off's --
and the next note's first call, which runs no wavetable step, is the third
fall's frame: ours fell once, by $0100 on frame 4, a tie siddump prints and
never a bend. `bend` read 0.31x, 336000 of the original's 732442 units of
bend being this fall.

On a 3-call row the player itself gates off on frame 3 (the row after next is
fetched `gatetimer` = 2 calls early, player.s `mt_gatetimer`), so the head can
spend that call on the first step: gate kept, one step, one step, stop. Frames
3 and 4 are then the original's; frame 5 stays out of reach.

Measured at a3792d2 (subtune 0, -t 180, presets): bend .314 -> .576, slides
.308 -> .571, tie_agreement .711 -> .785, cents .905 -> .923, aud .9385 ->
.9389, no column lower; corpus byte-hash moves Tarzan alone.

Own file: reads no shared fixture.
"""
import json
import pathlib
import shutil
import sys

import pytest

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[1]))

import fidelity                                              # noqa: E402
from corpus import CORPUS, needs_corpus                      # noqa: E402
from h2g.convert import convert                              # noqa: E402
from h2g.goatwriter import drum_fall as DF                   # noqa: E402
from h2g.goatwriter.counter_fall import _visits              # noqa: E402
from h2g.goatwriter.constants import (CMD_SETWAVEPTR,        # noqa: E402
                                      GT_WAVE_JUMP, WAVECMD_PORTADOWN)
from songview import parse_sng                                # noqa: E402

REPO_ROOT = pathlib.Path(__file__).resolve().parents[2]
TARZAN = "Tarzan.sid"
DRUM_ADSR = 0x0407
SECONDS = 20

needs_tools = pytest.mark.skipif(
    not (pathlib.Path(fidelity.SIDDUMP).exists()
         and pathlib.Path(fidelity.GT2RELOC).exists()),
    reason="needs siddump (tools/siddump-rt) and gt2reloc")


def _opts() -> dict:
    doc = json.loads((REPO_ROOT / "presets.json").read_text(encoding="utf-8"))
    return fidelity._preset_opts(doc, TARZAN)


def _quiet(sid, **kw) -> bytes:
    return convert(str(sid), log=lambda m: None, **kw)


def test_a_pattern_is_short_only_where_every_subtune_runs_three_calls():
    # Subtune 0 plays patterns 0 and 1, subtune 1 plays 1 and 2: pattern 1 is
    # shared, and a head is a property of the pattern.
    patterns = [[0] * 8] * 3
    tracks = [[0, 1, 0xFF, 0], [], [],
              [1, 2, 0xFF, 0], [], []]
    assert DF.short_head_patterns(tracks, patterns, (3, 3)) == {0, 1, 2}
    assert DF.short_head_patterns(tracks, patterns, (3, 4)) == {0}
    assert DF.short_head_patterns(tracks, patterns, (4, 4)) == set()
    # a subtune the tempo list does not name qualifies nothing it plays
    assert DF.short_head_patterns(tracks, patterns, (3,)) == {0}


@needs_corpus
def test_tarzan_short_heads_sit_on_three_call_subtunes_only():
    sng = parse_sng(_quiet(CORPUS / TARZAN, **_opts()))
    wt = sng.tables["WTBL"]
    one = None
    for i, (l, r) in enumerate(sng.tables["STBL"], 1):
        if (l, r) == (0x00, 0x80):
            one = i
    assert one is not None

    def is_short(head: int) -> bool:
        return (wt[head] == (0x11, 0x80)
                and wt[head + 1] == (WAVECMD_PORTADOWN, one)
                and wt[head + 2] == (WAVECMD_PORTADOWN, one)
                and wt[head + 3] == (GT_WAVE_JUMP, 0x00))

    def row_calls(group: int) -> int:
        for track in sng.tracks[3 * group:3 * group + 3]:
            for b in track:
                if b < 0xD0:
                    pat = sng.patterns[b]
                    for r in range(0, len(pat), 4):
                        if pat[r + 2] == 0xF:
                            return pat[r + 3]
                    break
        return 0

    shorts = four = 0
    for g in range(len(sng.tracks) // 3):
        calls = row_calls(g)
        played = {p for track in sng.tracks[3 * g:3 * g + 3]
                  for _pos, p, _k, _t in _visits(track, sng.patterns)}
        for p in sorted(played):
            pat = sng.patterns[p]
            for r in range(0, len(pat), 4):
                if pat[r + 2] != CMD_SETWAVEPTR:
                    continue
                head = pat[r + 3] - 1
                if is_short(head):
                    shorts += 1
                    assert calls == DF.SHORT_HEAD_ROW_CALLS, (g, p, calls)
                elif calls != DF.SHORT_HEAD_ROW_CALLS:
                    four += 1
    assert shorts >= 4, shorts
    # the longer-row subtunes still carry gate-off heads
    assert four >= 4, four


@needs_corpus
@needs_tools
def test_tarzan_two_row_drum_falls_on_the_originals_frames_3_and_4(tmp_path):
    opts = _opts()
    sid = CORPUS / TARZAN
    local = tmp_path / "o.sid"
    shutil.copyfile(sid, local)
    cal, _ft = fidelity.table_calibration(sid, opts)
    orig = fidelity.run_siddump(local, SECONDS, 0, fidelity.SIDDUMP, cal)
    n = SECONDS * 50
    voice = 1
    ofr = fidelity.register_timeline(orig[voice].freq_events, n)
    oad = fidelity.register_timeline(orig[voice].adsr_events, n)
    hits = [a for a in orig[voice].attack_frames
            if a < n - 40 and oad[a] == DRUM_ADSR]
    assert len(hits) >= 100

    sng, _ = fidelity.legalise_restarts(_quiet(sid, **opts))
    where = tmp_path / "b"
    where.mkdir()
    packed = fidelity.pack_sid(sng, where, fidelity.GT2RELOC, 1)
    assert packed is not None
    ours = fidelity.run_siddump(packed, SECONDS + 1, 0, fidelity.SIDDUMP)
    lag, _ = fidelity.startup_lag(orig, ours)
    hfr = fidelity.register_timeline(ours[voice].freq_events, n + 60)
    hwf = fidelity.register_timeline(ours[voice].wf_events, n + 60)
    fell = gate = 0
    for a in hits:
        # frame 3 and 4 after the attack are the original's own pitch (frame
        # 3 was one step high before); the gate is off from frame 3.
        fell += all(abs(hfr[a + f + lag] - ofr[a + f]) <= 8 for f in (3, 4))
        gate += not hwf[a + 3 + lag] & 1
    assert fell >= 0.95 * len(hits), (fell, len(hits))
    assert gate >= 0.95 * len(hits), (gate, len(hits))
