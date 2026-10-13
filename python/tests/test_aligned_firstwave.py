"""`aligned_firstwave`: the note-init call's gate write on the pitch's frame.

Goattracker's init call writes only `$D404` (player.s mt_newnoteinit); the
frequency arrives one call later. `no_test_restart` spends that call on the
record's waveform with the gate ON, so under it every gate RISE lands one frame
before its pitch, and every FALL too, because the gatetimer counts from that
call. Chicken_Song, 30 s, presets, lag 8 (`fidelity.startup_lag`, which since
6e467ff names the pitch frame as the attack): rises and falls `{-1}` on all
three voices.

The option writes the record's waveform with the gate CLEAR on every instrument
(`gate_off_firstwave`), keeps the wavetable lead entry so gate and pitch land
together on call 1, and takes one call off the gatetimer so the gate is off for
the span it was. Measured on 0421071: Chicken_Song rises and falls `{0}` on
every voice; the firstwave alone (no gatetimer trim) fixes the rises and leaves
the falls at `{-1}`.

Own file, per the task's optimistic-merge rule: it reads no shared fixture.
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
from h2g.convert import convert                              # noqa: E402
from h2g.goatwriter import FORMAT_GTS5                       # noqa: E402
from h2g.goatwriter.constants import FIRSTWAVE_TESTBIT       # noqa: E402

REPO_ROOT = pathlib.Path(__file__).resolve().parents[2]
COMMANDO = REPO_ROOT / "Commando.sid"
SECONDS = 30

needs_siddump = pytest.mark.skipif(
    not pathlib.Path(fidelity.SIDDUMP).exists(),
    reason="no siddump on this machine (tools/siddump-rt, see its README)")
needs_gt2reloc = pytest.mark.skipif(
    not pathlib.Path(fidelity.GT2RELOC).exists(),
    reason="no gt2reloc on this machine")


def _records(sng: bytes) -> list[int]:
    """Byte offsets of every instrument record (25 bytes each)."""
    pos = songview.HEADER_LEN
    subtunes = sng[pos]
    pos += 1
    for _ in range(subtunes * 3):
        pos += sng[pos] + 2
    count = sng[pos]
    return [pos + 1 + k * 25 for k in range(count)]


def _quiet(sid, **kw) -> bytes:
    return convert(str(sid), log=lambda m: None, **kw)


def test_off_by_default_changes_no_byte():
    assert _quiet(COMMANDO, aligned_firstwave=False) == _quiet(COMMANDO)


def _compare_with_the_plain_build(sid, reference=None, **kw):
    """Aligned against the same build without it (`reference`: extra convert
    options for that build). The files are the same length and the ONLY bytes
    that differ are, per instrument record, the firstwave and the gatetimer: a
    record that took a gate-off byte (a waveform selected, gate bit clear)
    has a gatetimer one call less, never below 1, flag bits untouched; every
    other record -- the testbit fallback, whose init call is still gate ON,
    and the Clear Voice slot -- keeps both."""
    plain = _quiet(sid, **(reference or {}), **kw)
    got = _quiet(sid, aligned_firstwave=True, **kw)
    assert len(plain) == len(got)
    recs = _records(plain)
    assert recs == _records(got)
    inside = {rec + k for rec in recs for k in (7, 8)}
    assert {i for i, (a, b) in enumerate(zip(plain, got)) if a != b} <= inside
    trimmed, kept_fallback, deep = 0, 0, 0
    for n, rec in enumerate(recs):
        gt_plain, gt_got = plain[rec + 7], got[rec + 7]
        fw_got = got[rec + 8]
        if fw_got & 0xF0 and not fw_got & 1 and fw_got < 0xFE and n:
            assert gt_got & 0x3F == max(1, (gt_plain & 0x3F) - 1), (n, gt_plain)
            assert gt_got & 0xC0 == gt_plain & 0xC0, "flag bits are untouched"
            trimmed += gt_plain & 0x3F > 1
            deep += gt_plain & 0x3F > 2
        else:
            assert gt_got == gt_plain, (n, fw_got)
            kept_fallback += n > 0 and fw_got == FIRSTWAVE_TESTBIT
    assert trimmed, "no record was trimmed; proves nothing"
    return trimmed, kept_fallback, deep


def test_it_is_a_gate_off_firstwave_on_every_instrument_and_one_call_less():
    _compare_with_the_plain_build(COMMANDO)


@needs_corpus
def test_a_longer_gatetimer_loses_exactly_one_call_and_the_fallback_none():
    """5_Title_Tunes at `hard_restart_frames` 4 with `max_hard_restart` asks
    for a 3-call gatetimer, so the trim is not hiding behind the floor of 1,
    and it has records whose waveform nibble is empty (the testbit fallback)."""
    trimmed, kept_fallback, deep = _compare_with_the_plain_build(
        CORPUS / "5_Title_Tunes.sid", fmt=FORMAT_GTS5, tempo="auto",
        hard_restart_frames=4, max_hard_restart=True)
    assert deep > 0, "no record carried a gatetimer above 2"
    assert kept_fallback > 0, "no testbit-fallback record to keep"


def test_it_overrides_no_test_restart():
    assert (_quiet(COMMANDO, aligned_firstwave=True, no_test_restart=True)
            == _quiet(COMMANDO, aligned_firstwave=True))
    # ... and that is not vacuous: the flag alone is a different file.
    assert (_quiet(COMMANDO, no_test_restart=True)
            != _quiet(COMMANDO, aligned_firstwave=True))


def _edges(t: list[int], rise: bool) -> list[int]:
    return [i for i in range(1, len(t))
            if (t[i] & 1) != (t[i - 1] & 1) and bool(t[i] & 1) == rise]


def _census(a: list[int], b: list[int], w: int = 3) -> collections.Counter:
    """For each edge of the original, ours' nearest one, as ours - orig."""
    sb, out = set(b), collections.Counter()
    for e in a:
        out[next((d for d in sorted(range(-w, w + 1), key=abs)
                  if e + d in sb), None)] += 1
    return out


def _gate_census(orig, packed: pathlib.Path) -> list[dict]:
    ours = fidelity.run_siddump(packed, SECONDS, 0, calls=1)
    lag, _raw = fidelity.startup_lag(orig, ours)
    n = SECONDS * 50
    out = []
    for a, b in zip(orig, ours):
        ta, tb = fidelity._aligned(fidelity.register_timeline(a.wf_events, n),
                                   fidelity.register_timeline(b.wf_events, n),
                                   lag)
        out.append({"rise": _census(_edges(ta, True), _edges(tb, True)),
                    "fall": _census(_edges(ta, False), _edges(tb, False))})
    return out


@needs_corpus
@needs_siddump
@needs_gt2reloc
def test_chicken_song_gate_envelope_sits_on_the_pitch(tmp_path):
    name = "Chicken_Song.sid"
    doc = json.loads((REPO_ROOT / "presets.json").read_text(encoding="utf-8"))
    assert doc["songs"][name].get("multiplier", 1) == 1
    base = fidelity._preset_opts(doc, name)
    assert base["no_test_restart"], "the control arm needs the flag it fixes"
    orig = fidelity.run_siddump(CORPUS / name, SECONDS, 0)
    arms = {}
    for arm, extra in (("shipped", {}), ("aligned", {"aligned_firstwave": True})):
        sng, _ = fidelity.legalise_restarts(
            _quiet(CORPUS / name, **dict(base, **extra)))
        work = tmp_path / arm
        work.mkdir()
        packed = fidelity.pack_sid(bytes(sng), work)
        assert packed is not None and packed.exists(), arm
        arms[arm] = _gate_census(orig, packed)
    # The defect: every rise and every fall one frame ahead of the pitch.
    for vi, c in enumerate(arms["shipped"]):
        assert sum(c["rise"].values()) > 20, vi
        assert set(c["rise"]) == {-1} and set(c["fall"]) == {-1}, (vi, c)
    # The fix: all of them on the original's frame, every voice.
    for vi, c in enumerate(arms["aligned"]):
        assert sum(c["rise"].values()) > 20, vi
        assert set(c["rise"]) == {0} and set(c["fall"]) == {0}, (vi, c)


@needs_corpus
def test_a_funk_subtune_does_not_hand_the_trimmed_records_their_call_back():
    """`funk_gatetimers` raises a record whose gatetimer equals the funk row's
    to the value its longer rows get. A trimmed record lands on that value
    (2 -> 1), so the target has to be trimmed too or the pass undoes the
    trim. Gerry_the_Germ subtune 2 is the corpus' 2-call row, and none of its
    rows is longer than 3 calls: every gate-off record ends on gatetimer 1."""
    got = _quiet(CORPUS / "Gerry_the_Germ.sid", aligned_firstwave=True,
                 fmt=FORMAT_GTS5, tempo="auto")
    recs = _records(got)[1:]            # [0] is the Clear Voice slot
    off = [got[r + 7] & 0x3F for r in recs
           if got[r + 8] & 0xF0 and not got[r + 8] & 1 and got[r + 8] < 0xFE]
    assert len(off) > 10
    assert set(off) == {1}, collections.Counter(off)
