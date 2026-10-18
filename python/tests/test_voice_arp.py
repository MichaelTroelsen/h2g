"""Bit $04 read as Ninja reads it: an arpeggio with per-*voice* parameters.

Ninja `$CB1E` sounds `note + interval,X` on every working call whose per-note
counter AND `mask,X` is nonzero, with both tables indexed by the voice
(`FB FB 20` / `03 03 01`). Neither arpeggio shape `_find_effect_routines`
reads matches it, so until `detect._find_voice_arp` the records setting the
bit were converted as plain notes: voice 2's record 9 (`$380A`) held one pitch
where the player sounds the note a fourth below on three working calls in four.

The player's outer counter skips one call in four, and that skip lands on the
same frame of every note (`voice_arp_skip_phase`), so the arpeggio -- and bit
$01's per-voice waveform alternation on the same counter -- is laid out frame
by frame with the skipped frames held. These tests pin the reading, the phase,
the block, and the block against the original's own trace.
"""
import math
import pathlib
import subprocess
import sys

import pytest

from corpus import CORPUS, needs_corpus  # noqa: E402

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[1]))

import fidelity  # noqa: E402
from h2g.convert import _detect_tables, convert  # noqa: E402
from h2g.detect import VOICES  # noqa: E402
from h2g.goatwriter import voice_arp_entries, voice_arp_skip_phase  # noqa: E402
from h2g.search import search_file  # noqa: E402
from h2g.sidfile import load_sid  # noqa: E402

needs_siddump = pytest.mark.skipif(
    not pathlib.Path(fidelity.SIDDUMP).exists(),
    reason="siddump-rt not built")


def _det(name):
    sid = load_sid(str(CORPUS / f"{name}.sid"))
    return _detect_tables(sid, lambda *a, **k: None)


def _semis(right):
    """A .sng wavetable right byte as semitones from the played note."""
    if right == 0x00:
        return 0
    return right if right < 0x60 else right - 0x80


@needs_corpus
def test_ninja_reads_the_per_voice_tables():
    sid, det = _det("Ninja")
    assert not det.effect_arp
    iv = sid.data[det.voice_arp_interval:det.voice_arp_interval + VOICES]
    mk = sid.data[det.voice_arp_mask:det.voice_arp_mask + VOICES]
    assert bytes(iv) == bytes([0xFB, 0xFB, 0x20])     # $CC69
    assert bytes(mk) == bytes([0x03, 0x03, 0x01])     # $CC6C


@needs_corpus
def test_ninja_is_the_only_corpus_file_with_the_block():
    hits = []
    for path in sorted(CORPUS.glob("*.sid")):
        _sid, det = _detect_tables(load_sid(str(path)), lambda *a, **k: None)
        if det.voice_arp_interval >= 0:
            hits.append(path.name)
    assert hits == ["Ninja.sid"]


@needs_corpus
def test_skip_phase_is_stepped_from_the_counters():
    sid, det = _det("Ninja")
    # $CC59 holds 0 and reloads 3, $CC46 holds 1 and reloads 2: a row is
    # fetched on call 3 and the next skipped call is call 5.
    assert voice_arp_skip_phase(sid, det) == (3, 2)


def test_block_holds_the_skipped_frames():
    left, right = voice_arp_entries(0x11, 0xFB, 0x03, (3, 2), start=100,
                                    budget=64, written=True)
    # Frames 1-16, then the jump back to frame 1. The counter reads
    # 1 2 _ 3 4 5 _ 6 7 8 _ 9 10 11 _ 12 (`_` the skipped frame, held).
    assert [_semis(r) for r in right[:-1]] == [
        -5, -5, -5, -5, 0, 0, -5, -5, -5, -5, 0, -5, -5, -5, -5, 0]
    assert left == [0x11] * 16 + [0xFF] and right[-1] == 100
    # Bit $01 beside it (record 5 on voice 3): the waveform rides k & 1.
    left, right = voice_arp_entries(0x11, 0x20, 0x01, (3, 2), start=7,
                                    budget=64, written=True, alt=0x81)
    assert left[:-1] == [0x81, 0x81, 0x11, 0x81, 0x11, 0x11, 0x81, 0x11]
    assert [_semis(r) for r in right[:-1]] == [32, 32, 0, 32, 0, 0, 32, 0]


def test_block_refuses_what_it_cannot_say():
    assert voice_arp_entries(0x11, 0xFB, 0x03, (3, 2), start=None) is None
    assert voice_arp_entries(0x11, 0xFB, 0x03, (3, 2), start=1,
                             budget=5) is None          # 17 entries
    assert voice_arp_entries(0x11, 0x00, 0x00, (3, 2), start=1,
                             budget=64) is None         # nothing to say


def _frames(stdout):
    rows, st = [], [[0, 0, 0] for _ in range(3)]
    for line in stdout.splitlines():
        if not line.startswith("|") or "Frame" in line:
            continue
        c = line.split("|")
        try:
            int(c[1])
        except ValueError:
            continue
        for v in range(3):
            x = c[2 + v]
            if x[1:5] != "....":
                st[v][0] = int(x[1:5], 16)
            if x[15:17].strip(". "):
                st[v][1] = int(x[15:17], 16)
            if x[18:22] != "....":
                st[v][2] = int(x[18:22], 16)
        rows.append([tuple(s) for s in st])
    return rows


@needs_corpus
@needs_siddump
@pytest.mark.parametrize("voice,adsr,interval,mask,alt", [
    (1, 0x380A, 0xFB, 0x03, None),      # record 9, effect $54
    (2, 0x4900, 0x20, 0x01, 0x81),      # record 5, effect $05
    (0, 0x1D00, 0x00, 0x00, 0x81),      # record 12, effect $01
])
def test_block_is_what_the_original_sounds(voice, adsr, interval, mask, alt):
    proc = subprocess.run([fidelity.SIDDUMP, str(CORPUS / "Ninja.sid"),
                           "-a0", "-t90", "-v1"], capture_output=True,
                          text=True, timeout=180, stdin=subprocess.DEVNULL)
    rows = _frames(proc.stdout)
    sid, det = _det("Ninja")
    wave = 0x11 if voice != 0 else 0x41
    left, right = voice_arp_entries(wave, interval, mask,
                                    voice_arp_skip_phase(sid, det),
                                    start=0, budget=64, written=True, alt=alt)
    left, right = left[:-1], right[:-1]
    checked = 0
    for f in range(1, len(rows) - len(left) - 1):
        o = rows[f][voice]
        if not (o[1] & 1 and not rows[f - 1][voice][1] & 1 and o[2] == adsr):
            continue
        for r in range(1, len(left) + 1):
            x = rows[f + r][voice]
            if not x[1] & 1:
                break                   # the gate closed: the note is over
            want = _semis(right[r - 1])
            got = 12 * math.log2(x[0] / o[0])
            assert abs(got - want) < 0.1, (f, r, got, want)
            assert x[1] == left[r - 1], (f, r, hex(x[1]), hex(left[r - 1]))
            checked += 1
    assert checked > 40


@needs_corpus
def test_converted_ninja_carries_the_block():
    import json
    doc = json.loads((pathlib.Path(__file__).resolve().parents[2]
                      / "presets.json").read_text())
    opts = fidelity._preset_opts(doc, "Ninja.sid")
    pat = " ".join(f"{b:02X}" for b in
                   [0x7B, 0x7B, 0x7B, 0x7B, 0x00, 0x00, 0x7B, 0x7B,
                    0x7B, 0x7B, 0x00, 0x7B, 0x7B, 0x7B, 0x7B, 0x00])
    opts["voice_arp"] = True
    assert search_file(convert(str(CORPUS / "Ninja.sid"), **opts), pat) >= 0
    # Off (the default) the reading is not emitted at all.
    opts["voice_arp"] = False
    assert search_file(convert(str(CORPUS / "Ninja.sid"), **opts), pat) < 0


@needs_corpus
def test_bit01_alone_holds_the_skipped_frames_under_the_option():
    # Record 12 (`$1D00`, effect $01) on voice 1: `41 81 81 41 81 41 41 81`
    # from the note's frame 0, not a strict alternation.
    import json
    doc = json.loads((pathlib.Path(__file__).resolve().parents[2]
                      / "presets.json").read_text())
    opts = fidelity._preset_opts(doc, "Ninja.sid")
    opts["voice_arp"] = True
    sng = convert(str(CORPUS / "Ninja.sid"), **opts)
    assert search_file(sng, "81 81 41 81 41 41 81 41 FF") >= 0
    opts["voice_arp"] = False
    sng = convert(str(CORPUS / "Ninja.sid"), **opts)
    assert search_file(sng, "81 81 41 81 41 41 81 41 FF") < 0
