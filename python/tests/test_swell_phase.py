"""The swell's free-running triangle (`goatwriter.swell_phase`) and the
zero-page spelling of effect bit $40 -- Mega_Apocalypse's lead and drum.

User report 2026-10-18, by ear: "the lead is a bit off and some of the fx
are not correct". Measured at e0b17bd (siddump -t60, presets, lag 7): the
lead `$00B9` had 558 of 1258 gated frames more than half a semitone off the
original, a mean of -0.39 st -- Goattracker's vibrato spans `-2..+1` steps
from where it starts and the player's `-1..+2` about the note, and the phase
was whatever the gate row left -- and the `$0848` drum sounded its noise
frame at the note's pitch where the player sounds `$22D0` (`$4E20 BIT $EC /
BVC`, read only as `BIT abs` until then).
"""
import json
import math
import pathlib
import sys

import pytest

PYTHON_ROOT = pathlib.Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PYTHON_ROOT))

from corpus import CORPUS, needs_corpus  # noqa: E402
from h2g.goatwriter import swell_phase as SW  # noqa: E402


def _phases(bound):
    """Every distinct state of the player's triangle over a period."""
    b0 = b6 = 0
    seen, out = set(), []
    for _ in range(6 * bound):
        b0, b6 = SW.triangle_step(b0, b6, bound)
        key = tuple(SW.player_offsets(bound, b0, b6, 2 * bound))
        if key not in seen:
            seen.add(key)
            out.append((b0, b6))
    return out


def test_the_triangle_is_lopsided_upward_on_an_odd_bound():
    # $4C97-$4CCF: freq(note) - (bound >> 1) * step + pos * step.
    offs = SW.player_offsets(3, 0, 0, 12)
    assert min(offs) == -1 and max(offs) == 2
    # Goattracker's own from vibtime 0, cmp = bound - 2: -2 .. +1.
    goat = SW.goat_offsets(1, 0, "", 12)
    assert min(goat) == -2 and max(goat) == 1


@pytest.mark.parametrize("bound", [3, 4])
def test_the_plan_matches_the_player_after_a_period_in_most_phases(bound):
    """With the phaser free to sit anywhere in two rows before the gate
    (Mega's `$00B9`: gate 12, rows of 3), every phase of the bound-3
    triangle is matched exactly from the second period on; bound 4 all but
    the one whose gate frame jumps two steps."""
    period = 2 * bound
    exact = 0
    for b0, b6 in _phases(bound):
        quiet, prefix = SW.plan_gate(bound, bound - 2, b0, b6, range(0, 6))
        n = 4 * period
        got = SW.goat_offsets(bound - 2, quiet, prefix, n)
        want = SW.player_offsets(bound, b0, b6, n)
        exact += got[2 * period:] == want[2 * period:]
    assert exact >= {3: 6, 4: 6}[bound], exact


def test_without_the_plan_the_loop_never_matches_an_odd_bound():
    # The control: the plain loop from the note, every phase, no frame of
    # the second period on agrees in the centre (it is a step low).
    for b0, b6 in _phases(3):
        got = SW.goat_offsets(1, 0, "", 24)
        want = SW.player_offsets(3, b0, b6, 24)
        assert got[12:] != want[12:]


def test_the_triangle_shape_is_megas_and_not_commandos():
    sid = (PYTHON_ROOT.parent / "Commando.sid").read_bytes()
    assert not SW.swell_triangle(sid)


@needs_corpus
def test_mega_reads_the_zero_page_triangle_and_bit_40():
    from h2g.detect import detect
    from h2g.goatwriter.attack import _fixed_attack_note
    from h2g.sidfile import load_sid
    sid = load_sid(str(CORPUS / "Mega_Apocalypse.sid"))
    assert SW.swell_triangle(sid.data)
    det = detect(sid, lambda m: None)
    assert det.effect_bit40
    # Record 1 ($0848, effect $44): `$54A3 + 8` is note 188 -- C-5 in
    # Goattracker's absolute spelling, `$22D0` in the player's table.
    assert _fixed_attack_note(sid, det, 1) == 188


def _traces(tmp_path, seconds=60):
    import fidelity
    from h2g.convert import convert
    doc = json.loads((PYTHON_ROOT.parent / "presets.json").read_text())
    opts = fidelity._preset_opts(doc, "Mega_Apocalypse.sid")
    src = CORPUS / "Mega_Apocalypse.sid"
    sng, _ = fidelity.legalise_restarts(bytes(convert(str(src), lambda m: None,
                                                      **opts)))
    packed = fidelity.pack_sid(sng, tmp_path, fidelity.GT2RELOC, 1)
    assert packed is not None
    cal, _ft = fidelity.table_calibration(src, opts)
    to = fidelity.run_siddump(src, seconds, 0, fidelity.SIDDUMP, cal, calls=1)
    tu = fidelity.run_siddump(packed, seconds, 0, fidelity.SIDDUMP, calls=1)
    nf = seconds * 50

    def tl(v):
        return (fidelity.register_timeline(v.freq_events, nf),
                fidelity.register_timeline(v.wf_events, nf),
                fidelity.register_timeline(v.adsr_events, nf))
    # The packed player's startup lag, uniform (investigate-mega-apocalypse-
    # s-constant-7-frame): voice 1's first attack on each side.
    lag = tu[0].attack_frames[0] - to[0].attack_frames[0]
    return [tl(v) for v in to], [tl(v) for v in tu], lag, nf, to


@needs_corpus
@pytest.mark.skipif(not pathlib.Path(
    __import__("fidelity").SIDDUMP).exists(), reason="no siddump")
def test_mega_lead_sits_on_the_originals_pitch(tmp_path):
    """60 s: `$00B9` gated frames more than half a semitone off the original,
    558 of 1258 before (mean -0.39 st), 101 after (mean -0.05 st)."""
    o, h, lag, nf, _ = _traces(tmp_path)
    (fo, wo, ao), (fh, _wh, _ah) = o[0], h[0]
    gated = [f for f in range(1, nf - lag) if wo[f] & 1 and ao[f] == 0x00B9
             and fo[f] and fh[f + lag]]
    st = [12 * math.log2(fh[f + lag] / fo[f]) for f in gated]
    off = sum(abs(x) > 0.5 for x in st)
    assert len(gated) > 1000, len(gated)
    assert off < 200, (off, len(gated))
    assert abs(sum(st) / len(st)) < 0.15, sum(st) / len(st)


@needs_corpus
@pytest.mark.skipif(not pathlib.Path(
    __import__("fidelity").SIDDUMP).exists(), reason="no siddump")
def test_mega_drum_sounds_its_noise_frame_at_the_players_pitch(tmp_path):
    """Voice 2 `$0848`: the frame after the attack is noise at `$22D0`
    whatever the note (`2710` or `4E20`), on every hit; before, at the
    note's own pitch on 204 of 205."""
    o, h, lag, nf, to = _traces(tmp_path)
    (fo, wo, ao), (fh, wh, _ah) = o[1], h[1]
    hits = [a for a in to[1].attack_frames
            if ao[a] == 0x0848 and a + lag + 2 < nf]
    assert len(hits) > 150, len(hits)
    assert all(fo[a + 1] == 0x22D0 and wo[a + 1] == 0x81 for a in hits)
    good = sum(fh[a + lag + 1] == 0x22D0 and wh[a + lag + 1] == 0x81
               for a in hits)
    assert good == len(hits), (good, len(hits))
