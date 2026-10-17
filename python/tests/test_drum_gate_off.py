"""`drum_gate_off`: the drum block's gate-off where the converter held the gate.

Commando's drum block (`$52FA`, effect bit $01) writes `$5331 LDA #$80 / STA
$D404,Y` while the note's first duration unit lasts and `$5324 LDA $54F8,X /
AND #$FE` after it: the gate is open on the note's first frame ONLY, whatever
the record's sustain. Its record 1 (ADSR $064B, effect $05: drum + the
fixed-octave arpeggio) is the arpeggio a listener heard as too quiet: the
original reads `41 80 80 40 40` from each onset and rings on R=$B, where the
conversion held the gate and decayed to S=$4 (`41 81 81 41 41`). The sustaining
record rule (`wavetable._wavetable_entries`, v0.5.164) cleared `drum` for it;
under the option a record with a live arpeggio keeps it, and a drum record's
noise tick is written gate-off at -S1 (`_drum_tick_noise`).

Deep Strike's player masks the gate instead (`$C302 LDA #$FE / STA $C4AF,X`,
`$C3B5 LDA $C4A6,X / AND $C4AF,X / STA $D404,Y`), under effect bit $02's
alternation: record 7 (ADSR $0F07, effect $0B) reads `11 11 81 10 80 10 80`
in the original, and the alternation shape held the gate on both halves.

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
from h2g.goatwriter import wavetable                         # noqa: E402

REPO_ROOT = pathlib.Path(__file__).resolve().parents[2]
COMMANDO = REPO_ROOT / "Commando.sid"
DEEP_STRIKE = "Deep_Strike.sid"
ARP_ADSR = 0x064B
SECONDS = 30

needs_tools = pytest.mark.skipif(
    not (pathlib.Path(fidelity.SIDDUMP).exists()
         and pathlib.Path(fidelity.GT2RELOC).exists()),
    reason="needs siddump (tools/siddump-rt) and gt2reloc")


def _quiet(sid, **kw) -> bytes:
    return convert(str(sid), log=lambda m: None, **kw)


def _opts(name: str) -> dict:
    doc = json.loads((REPO_ROOT / "presets.json").read_text(encoding="utf-8"))
    return fidelity._preset_opts(doc, name)


def _records(sid, monkeypatch, **kw) -> dict:
    """Record index -> the (left, right) `_wavetable_entries` returned for it
    (the last call wins; a record built twice is built alike)."""
    seen = {}
    real = wavetable._wavetable_entries

    def spy(s, det, i, *a, **k):
        r = real(s, det, i, *a, **k)
        seen[i] = (list(r[0]), list(r[1]))
        return r
    monkeypatch.setattr(wavetable, "_wavetable_entries", spy)
    _quiet(sid, **kw)
    monkeypatch.setattr(wavetable, "_wavetable_entries", real)
    return seen


def test_off_by_default_changes_no_byte():
    ref = (REPO_ROOT / "Commando.sng").read_bytes()
    assert _quiet(COMMANDO) == ref
    assert _quiet(COMMANDO, drum_gate_off=False) == ref
    opts = _opts("Commando.sid")
    assert _quiet(COMMANDO, **dict(opts, drum_gate_off=False)) \
        == _quiet(COMMANDO, **opts)


def test_commando_arp_record_gates_one_frame(monkeypatch):
    opts = _opts("Commando.sid")
    held = _records(COMMANDO, monkeypatch, **opts)[1][0]
    cut = _records(COMMANDO, monkeypatch,
                   **dict(opts, drum_gate_off=True))[1][0]
    # Without the option: the noise tick and the arpeggio's tails gated.
    assert held[:5] == [0x41, 0x81, 0x81, 0x41, 0x41]
    # With it: the record's waveform on frame 0, then the gate is shut.
    assert cut[:5] == [0x41, 0x80, 0x80, 0x40, 0x40]
    assert not any(w & 1 for w in cut[1:] if 0x10 <= w < 0xF0)


@needs_corpus
def test_deep_strike_alternation_takes_the_gate_mask(monkeypatch):
    sid = CORPUS / DEEP_STRIKE
    opts = _opts(DEEP_STRIKE)
    held = _records(sid, monkeypatch, **opts)[7]
    left, _right = _records(sid, monkeypatch,
                            **dict(opts, drum_gate_off=True))[7]
    assert 0x10 not in held[0] and 0x80 not in held[0]
    # The loop the alternation keeps after the tick is the gate-off pair.
    loop = left.index(0x80)
    assert left[-1] == 0xFF
    assert [w for w in left[loop:-1] if w >= 0x10] == [0x80, 0x10]
    # ... and before it, the frame-0 lead and one gated frame of the pair.
    assert [w for w in left[:loop] if w >= 0x10] == [0x11, 0x11]


def _runs(text: str, voice: int, adsr: int) -> list:
    """Sounding gated frames after each attack of `adsr` on `voice`: frames
    with the gate on and the test bit off (a gated test-bit frame is
    Goattracker's silent hard restart)."""
    st = [[0, 0] for _ in range(3)]   # wf, adsr per voice, carried forward
    rows = []
    for line in text.splitlines():
        if not line.startswith("|") or "Frame" in line:
            continue
        c = line.split("|")
        try:
            int(c[1])
        except ValueError:
            continue
        for v in range(3):
            x = c[2 + v]
            wf, ad = x[15:17], x[18:22]
            if wf.strip(". "):
                st[v][0] = int(wf, 16)
            if ad != "....":
                st[v][1] = int(ad, 16)
        rows.append((st[voice][0], st[voice][1]))
    out = []
    for f in range(1, len(rows)):
        wf, ad = rows[f]
        if wf & 1 and not rows[f - 1][0] & 1 and ad == adsr:
            k = f
            while k < len(rows) and rows[k][0] & 1 and rows[k][0] & 8:
                k += 1
            n = 0
            while k + n < len(rows) and rows[k + n][0] & 1:
                n += 1
            out.append(n)
    return out


def _trace(sid: pathlib.Path, sub: int, calls: int = 1, cal: int = 0) -> str:
    cap = []
    fidelity.run_siddump(sid, SECONDS, sub, fidelity.SIDDUMP, cal,
                         calls=calls, capture=cap)
    return cap[1]


def _packed(sng: bytes, tmp: pathlib.Path) -> pathlib.Path:
    sng, _ = fidelity.legalise_restarts(sng)
    tmp.mkdir()
    packed = fidelity.pack_sid(sng, tmp, fidelity.GT2RELOC, 1)
    assert packed is not None, "gt2reloc wrote no .sid"
    return packed


@needs_tools
def test_commando_arp_trace_gates_one_frame_like_the_original(tmp_path):
    opts = _opts("Commando.sid")
    sub, our_sub, _ = fidelity.resolve_pair(COMMANDO, "auto")
    local = tmp_path / "o.sid"
    shutil.copyfile(COMMANDO, local)
    cal, _ft = fidelity.table_calibration(COMMANDO, opts)
    orig = _runs(_trace(local, sub, cal=cal), 1, ARP_ADSR)
    held = _runs(_trace(_packed(_quiet(COMMANDO, **opts), tmp_path / "a"),
                        our_sub), 1, ARP_ADSR)
    cut = _runs(_trace(_packed(_quiet(COMMANDO, **dict(
        opts, drum_gate_off=True)), tmp_path / "b"), our_sub), 1, ARP_ADSR)
    assert len(orig) >= 20 and set(orig) == {1}
    assert len(cut) == len(held) >= 20
    assert min(held) > 1
    assert set(cut) == {1}
