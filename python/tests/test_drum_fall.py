"""`drum_fall`: bit $01's 16-bit drum fall in Tarzan's player.

Tarzan `$57EA` (detect.DRUM_FALL16_SHAPE): from the first frame of a drum
note's second tick the frequency falls `$0080` a frame and the gate is masked
off, until the note ends or the high byte reaches zero. Before the option the
converter read no drum in this player (Warhawk's two-guard shape does not
match it) and held the pitch flat with the gate on to the note's last tick.
Measured at 03eb34f, subtune 0, 120 s, presets: voice 3's $0908 kick, 53 hits,
original `1168 1168 1168 10E8 1068 ... 09E8` with the gate off from frame 3,
ours `1168` on every frame with the gate on to frame 15; voice 2's $0407, 999
hits, the same three-frame fall held flat.

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
from h2g.detect import detect                                # noqa: E402
from h2g.goatwriter.constants import (CMD_SETWAVEPTR,        # noqa: E402
                                      GT_WAVE_JUMP, WAVECMD_PORTADOWN)
from h2g.goatwriter.drum_fall import (drum_fall_records,     # noqa: E402
                                      fall_steps)
from h2g.sidfile import load_sid                              # noqa: E402
from songview import parse_sng                                # noqa: E402

REPO_ROOT = pathlib.Path(__file__).resolve().parents[2]
COMMANDO = REPO_ROOT / "Commando.sid"
TARZAN = "Tarzan.sid"
KICK_ADSR = 0x0908
SECONDS = 20

needs_tools = pytest.mark.skipif(
    not (pathlib.Path(fidelity.SIDDUMP).exists()
         and pathlib.Path(fidelity.GT2RELOC).exists()),
    reason="needs siddump (tools/siddump-rt) and gt2reloc")


def _quiet(sid, **kw) -> bytes:
    return convert(str(sid), log=lambda m: None, **kw)


def _opts() -> dict:
    doc = json.loads((REPO_ROOT / "presets.json").read_text(encoding="utf-8"))
    return fidelity._preset_opts(doc, TARZAN)


def _det(name):
    sid = load_sid(str(CORPUS / name))
    return sid, detect(sid, lambda m: None)


def test_off_by_default_changes_no_byte():
    assert _quiet(COMMANDO, drum_fall=True) == _quiet(COMMANDO)


def test_fall_steps_stop_where_the_high_byte_reaches_zero():
    # `LDA freqhi / BEQ out` before each subtract: $1168 falls 33 times,
    # the last landing on $00E8.
    assert fall_steps(0x1168, 0x80) == 33
    assert 0x1168 - 33 * 0x80 == 0x00E8
    assert fall_steps(0x00FF, 0x80) == 0


@needs_corpus
def test_tarzan_block_is_read_and_only_there():
    sid, det = _det(TARZAN)
    assert det.drum_fall_step == 0x80
    assert not det.effect_drum
    # The records whose fall reaches the chip: bit $01 with nothing after
    # it rewriting the shadows (records 7, 9, 10 carry $40, 0 and 14 $02).
    assert drum_fall_records(sid, det, det.instr_used) == {1, 3, 6, 11}
    # Flash_Gordon's same arithmetic wears Warhawk's two guards and is read
    # there; Commando is the Warhawk shape itself.
    for other in ("Flash_Gordon.sid", "Commando.sid"):
        _sid, d = _det(other)
        assert d.drum_fall_step == 0, other


@needs_corpus
def test_kick_row_after_the_note_points_at_a_gate_off_head_and_chain():
    sng = parse_sng(_quiet(CORPUS / TARZAN, **dict(_opts(), drum_fall=True)))
    wt, st = sng.tables["WTBL"], sng.tables["STBL"]
    kick = next(i.number for i in sng.instruments
                if (i.ad << 8 | i.sr) == KICK_ADSR)
    pointed = 0
    for pat in sng.patterns:
        rows = [pat[r:r + 4] for r in range(0, len(pat) - 3, 4)]
        for r, (_n, ins, _c, _d) in enumerate(rows[:-1]):
            if ins != kick:
                continue
            nxt = rows[r + 1]
            assert nxt[2] == CMD_SETWAVEPTR, (r, nxt)
            head = nxt[3] - 1
            # The gate goes off with the frequency kept ...
            assert wt[head] == (0x10, 0x80)
            # ... then two steps (the head's frame and its own) ...
            assert wt[head + 1][0] == WAVECMD_PORTADOWN
            assert st[wt[head + 1][1] - 1] == (0x01, 0x00)
            # ... then a jump into single $0080 steps ending in a stop.
            assert wt[head + 2][0] == GT_WAVE_JUMP
            at = wt[head + 2][1] - 1
            steps = 0
            while wt[at][0] == WAVECMD_PORTADOWN:
                assert st[wt[at][1] - 1] == (0x00, 0x80)
                steps += 1
                at += 1
            assert wt[at] == (GT_WAVE_JUMP, 0x00)
            # 2 + steps decrements never reach below $0100 from C-4.
            assert 2 + steps <= fall_steps(0x1168, 0x80)
            pointed += 1
    assert pointed >= 4


@needs_corpus
@needs_tools
def test_tarzan_kick_falls_and_gates_off_like_the_original(tmp_path):
    opts = _opts()
    sid = CORPUS / TARZAN
    local = tmp_path / "o.sid"
    shutil.copyfile(sid, local)
    cal, _ft = fidelity.table_calibration(sid, opts)
    orig = fidelity.run_siddump(local, SECONDS, 0, fidelity.SIDDUMP, cal)
    n = SECONDS * 50
    ofr = fidelity.register_timeline(orig[2].freq_events, n)
    oad = fidelity.register_timeline(orig[2].adsr_events, n)
    hits = [a for a in orig[2].attack_frames if oad[a] == KICK_ADSR]
    assert len(hits) >= 5

    def ours(on: bool, where: pathlib.Path):
        where.mkdir()
        sng, _ = fidelity.legalise_restarts(
            _quiet(sid, **dict(opts, drum_fall=on)))
        packed = fidelity.pack_sid(sng, where, fidelity.GT2RELOC, 1)
        assert packed is not None
        return fidelity.run_siddump(packed, SECONDS + 1, 0, fidelity.SIDDUMP)

    def agree(trace) -> tuple[int, int]:
        lag, _ = fidelity.startup_lag(orig, trace)
        w = lag - 1        # our waveform's frame; the pitch is a frame late
        hfr = fidelity.register_timeline(trace[2].freq_events, n + 60)
        hwf = fidelity.register_timeline(trace[2].wf_events, n + 60)
        fell = gate = 0
        for a in hits:
            # The original falls on frames 3..14 of every hit; the head's
            # frame (3) is one step high, frames 4..14 exact.
            fell += all(abs(hfr[a + f + w] - ofr[a + f]) <= 8
                        for f in range(4, 15))
            gate += not hwf[a + 3 + w] & 1
        return fell, gate

    plain = agree(ours(False, tmp_path / "a"))
    fall = agree(ours(True, tmp_path / "b"))
    assert plain == (0, 0), plain
    assert fall == (len(hits), len(hits)), (fall, len(hits))
