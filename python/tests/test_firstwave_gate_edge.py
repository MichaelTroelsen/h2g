"""Our gate opens one frame early on every note because of the firstwave's
gate bit. Row timing and the gatetimer are already on the original's frames.

Confuzion's voice 2 noise note, lag-aligned, is `21 x $81, 3 x $80` in the
original and `$09, 21 x $81, 2 x $80` in ours under presets. A wrong note-row
time or a wrong gatetimer was the suspect. Through the packed player, on every
voice, under presets, at 180 s:

- every gate FALL lands on the original's frame (v1 485/485, v2 343/343,
  v0 183/191, plus 8 at -3 that are a separate question);
- every WAVEFORM ONSET (the first gated frame at or above $10) lands on the
  original's frame (192/192, 486/486, 344/344);
- every gate RISE is exactly one frame early (192/192, 486/486, 344/344).

So the only frame that differs is the note-init call. `player.s`
mt_newnoteinit writes only `$D404` there, set to the firstwave, and
`FIRSTWAVE_TESTBIT` = `$09` carries the gate (bit 0). The original keeps its
gate off for that frame (the third `$80`). Clearing bit 0 in the `.sng`, and
changing nothing else, puts all 1022 rises on the original's frame and takes
`gate` .7656 -> .9946. melody, sequence, wave, nrun and adsr are unchanged.
The record-waveform-with-gate-cleared spelling (`gate-off-firstwave-option`)
also brings voice 2 to 1 differing `$D404` frame of 8994, and wave
.9609 -> .9980.

Measured in C:/t/confuzion-gate-opens-one-frame-early/edges.py on 81da71d
(v0.5.509). The probe monkeypatched build._write_instruments in-process.
output_sha fccdf21a4b68 matches build/fidelity.json.

This test is the same experiment, shortened to 30 s, with the `.sng` patched
directly. It predicts the rise offset from the firstwave byte the `.sng`
actually carries, so it keeps holding once a gate-off firstwave ships. What it
refuses is an early rise from anything else, and any drift of the gate fall
or the waveform onset off the original's frame.
"""
import collections
import json
import pathlib
import sys

import pytest

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[1]))

import fidelity                                              # noqa: E402
import songview                                              # noqa: E402
from corpus import CORPUS, needs_corpus                      # noqa: E402

REPO_ROOT = pathlib.Path(__file__).resolve().parents[2]
SECONDS = 30

needs_siddump = pytest.mark.skipif(
    not pathlib.Path(fidelity.SIDDUMP).exists(),
    reason="no siddump on this machine (tools/siddump-rt, see its README)")
needs_gt2reloc = pytest.mark.skipif(
    not pathlib.Path(fidelity.GT2RELOC).exists(),
    reason="no gt2reloc on this machine")


def _firstwave_offsets(sng: bytes) -> list[int]:
    """Byte offsets of every instrument record's firstwave (+8 of 25)."""
    pos = songview.HEADER_LEN
    subtunes = sng[pos]
    pos += 1
    for _ in range(subtunes * 3):
        pos += sng[pos] + 2
    count = sng[pos]
    return [pos + 1 + k * 25 + 8 for k in range(count)]


def _edges(t: list[int], rise: bool) -> list[int]:
    return [i for i in range(1, len(t))
            if (t[i] & 1) != (t[i - 1] & 1) and bool(t[i] & 1) == rise]


def _onsets(t: list[int]) -> list[int]:
    """First gated frame selecting a waveform after an ungated or sub-$10
    frame: where the note's own waveform starts."""
    return [i for i in range(1, len(t))
            if t[i] >= 0x10 and t[i] & 1
            and (not t[i - 1] & 1 or t[i - 1] < 0x10)]


def _census(a: list[int], b: list[int], w: int = 3) -> collections.Counter:
    """For each edge of the original, ours' nearest one, as ours - orig."""
    sb, out = set(b), collections.Counter()
    for e in a:
        out[next((d for d in sorted(range(-w, w + 1), key=abs)
                  if e + d in sb), None)] += 1
    return out


def _edge_census(orig, packed: pathlib.Path) -> list[dict]:
    ours = fidelity.run_siddump(packed, SECONDS, 0, calls=1)
    lag, raw = fidelity.startup_lag(orig, ours)
    assert lag == raw, (lag, raw)
    n = SECONDS * 50
    out = []
    for a, b in zip(orig, ours):
        ta, tb = fidelity._aligned(fidelity.register_timeline(a.wf_events, n),
                                   fidelity.register_timeline(b.wf_events, n),
                                   lag)
        out.append({
            "rise": _census(_edges(ta, True), _edges(tb, True)),
            "fall": _census(_edges(ta, False), _edges(tb, False)),
            "onset": _census(_onsets(ta), _onsets(tb)),
        })
    return out


@needs_corpus
@needs_siddump
@needs_gt2reloc
def test_confuzion_gate_rise_is_early_by_the_firstwave_gate_bit_alone(
        tmp_path):
    from h2g.convert import convert
    name = "Confuzion.sid"
    doc = json.loads((REPO_ROOT / "presets.json").read_text(encoding="utf-8"))
    assert doc["songs"][name].get("multiplier", 1) == 1
    opts = fidelity._preset_opts(doc, name)
    sng, _ = fidelity.legalise_restarts(
        convert(str(CORPUS / name), log=lambda m: None, **opts))
    offs = _firstwave_offsets(sng)
    parsed = [i.firstwave for i in songview.parse_sng(sng).instruments]
    assert [sng[o] for o in offs] == parsed, "record walk is off"
    # A firstwave of 0 writes no waveform at all (gplay.c:355 `if
    # (iptr->firstwave)`): the tie_restart legato clones carry it, and they
    # have no gate bit to contribute, so they are neither counted nor flipped.
    offs = [o for o in offs if sng[o]]
    shipped = {sng[o] for o in offs}
    # One gate bit for the whole file, so one predicted rise offset per arm.
    assert len({fw & 1 for fw in shipped}) == 1, shipped

    flipped = bytearray(sng)
    for o in offs:
        flipped[o] ^= 0x01
    assert sum(x != y for x, y in zip(sng, flipped)) == len(offs) > 0

    orig = fidelity.run_siddump(CORPUS / name, SECONDS, 0)
    arms = {}
    for arm, blob in (("shipped", sng), ("flipped", bytes(flipped))):
        work = tmp_path / arm
        work.mkdir()
        packed = fidelity.pack_sid(bytes(blob), work)
        assert packed is not None and packed.exists(), arm
        gate_bit = next(iter({blob[o] & 1 for o in offs}))
        arms[arm] = (gate_bit, _edge_census(orig, packed))

    for arm, (gate_bit, voices) in arms.items():
        want_rise = -1 if gate_bit else 0
        for vi, c in enumerate(voices):
            where = (arm, vi, {k: dict(v) for k, v in c.items()})
            assert sum(c["rise"].values()) > 20, where
            # The onset and the rise are each 100% on one offset.
            assert set(c["onset"]) == {0}, where
            assert set(c["rise"]) == {want_rise}, where
            # The fall: voices 1 and 2 entirely on the original's frame. Voice
            # 0 also has a few falls 3 frames early, which are not this
            # mechanism, so it only has to be modal.
            if vi:
                assert set(c["fall"]) == {0}, where
            else:
                assert c["fall"].most_common(1)[0][0] == 0, where
    # Clearing the bit is the whole difference: the falls and onsets did not
    # move between the arms.
    for vs, vf in zip(arms["shipped"][1], arms["flipped"][1]):
        assert vs["fall"] == vf["fall"] and vs["onset"] == vf["onset"]
