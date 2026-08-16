"""The vibrato census: which instrument's oscillation is missing, and why.

`vib` is a whole-file ratio and a whole-file ratio cannot say *which*
instrument is missing its movement -- which decides what to fix. The balloon
song read 0.17x and was taken for a vibrato-rate defect; the one instrument
carrying a vibrato byte was within 20% of the original and the missing 1812
reversals were an arpeggio on a global counter (§ 7.ttt).

Two findings this exists to keep visible. Knucklebusters' 0.16x is **86% effect
bit `$02`**, not vibrato at all. And corpus-wide, 171 of the 188 instruments
under half rate emit *zero* oscillation rather than a slow one -- absence and
slowness have different fixes and are counted apart.
"""
import pathlib
import sys

from corpus import CORPUS, needs_corpus  # noqa: E402

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[1]))

import fidelity as F  # noqa: E402


def _voice(frames, freqs, adsr):
    """One voice: a note at each frame, with a pitch series after it."""
    v = F.Voice()
    v.attack_frames = list(frames)
    v.attacks = [f"n{i}" for i in range(len(frames))]
    v.freq_events = list(freqs)
    v.adsr_events = [(0, adsr)]
    return v


def _osc(start, n, step=0x40):
    """A pitch that reverses every frame -- one reversal per frame."""
    return [(start + i, 0x1000 + (step if i % 2 else 0)) for i in range(n)]


def test_reversals_are_attributed_to_the_sounding_instrument():
    a = F.Trace([_voice([0], _osc(0, 40), 0x0A0B),
                 F.Voice(), F.Voice()], F.FilterState())
    got = F.reversals_by_instrument(a, 60)
    assert set(got) == {0x0A0B}
    assert got[0x0A0B] > 10


def test_the_split_adds_up_to_the_column():
    """Not a second measurement: the per-instrument counts must total what
    `pitch_motion` reports, or the census is describing something else."""
    a = F.Trace([_voice([0], _osc(0, 40), 0x0A0B),
                 _voice([0], _osc(0, 30), 0x0C0D), F.Voice()],
                F.FilterState())
    assert sum(F.reversals_by_instrument(a, 60).values()) == \
        F.pitch_motion(a, 60)["reversals"]


def test_an_absent_oscillation_is_not_a_slow_one():
    orig = F.Trace([_voice([0], _osc(0, 40), 0x0A0B),
                    F.Voice(), F.Voice()], F.FilterState())
    ours = F.Trace([_voice([0], [(0, 0x1000)], 0x0A0B),
                    F.Voice(), F.Voice()], F.FilterState())
    rows = F.vib_census(orig, ours, 60)
    rec = next(r for r in rows if r["adsr"] == 0x0A0B)
    assert rec["orig"] > 10 and rec["ours"] == 0
    assert rec["ratio"] == 0.0


def test_the_cause_comes_from_the_effect_byte():
    orig = F.Trace([_voice([0], _osc(0, 40), 0x0A0B),
                    F.Voice(), F.Voice()], F.FilterState())
    ours = F.Trace([_voice([0], [(0, 0x1000)], 0x0A0B),
                    F.Voice(), F.Voice()], F.FilterState())
    for eff, want in ((0x10, "arp"), (0x02, "alt"), (0x44, "plain"),
                      (0x00, "plain")):
        rows = F.vib_census(orig, ours, 60,
                            {0x0A0B: {"gt": 3, "effect": eff}})
        assert rows[0]["cause"] == want, hex(eff)


@needs_corpus
def test_knucklebusters_loud_instruments_carry_the_alt_bit():
    """The detection half of the finding that justified building this.

    Its `vib` is 0.16x, and 1614 of the ~1884 reversals missing belong to two
    instruments whose effect byte is `$2B` -- bit `$02` set -- not to the
    record's own vibrato. Tuning the vibrato rate would have chased 14% of
    the problem. Checked here from the records rather than from a trace, so
    the test costs nothing; the measured split is in VIBRATO.md.
    """
    from h2g.convert import _detect_tables
    from h2g.sidfile import load_sid
    sid, det = _detect_tables(load_sid(str(CORPUS / "Knucklebusters.sid")),
                              lambda *a, **k: None)
    pairs = {}
    for i in range(det.instr_used):
        o = det.instr_start + i * det.instr_stride
        pairs[(sid.data[o + 3] << 8) | sid.data[o + 4]] = sid.data[o + 7]
    for adsr in (0x0F09, 0x0F0A):
        assert pairs.get(adsr) == 0x2B, hex(adsr)
        assert pairs[adsr] & 0x02, "the alternating-waveform bit"


def test_a_cause_is_only_claimed_when_the_effect_byte_is_known():
    """67 of the 148 `plain` rows have no recoverable effect byte, because
    `instrument_stamps` keys on the ADSR pair and two instruments can share
    one (§ 7.zzzz). Where the stamp is missing the row must not assert a
    mechanism it cannot see."""
    orig = F.Trace([_voice([0], _osc(0, 40), 0x0A0B),
                    F.Voice(), F.Voice()], F.FilterState())
    ours = F.Trace([_voice([0], [(0, 0x1000)], 0x0A0B),
                    F.Voice(), F.Voice()], F.FilterState())
    rec = F.vib_census(orig, ours, 60)[0]          # no stamps at all
    assert rec.get("effect") is None
    assert rec["cause"] == "unknown", (
        "`plain` asserts no oscillating bit is set -- a claim about a record "
        "we could not read")
