"""Release nibble 0 at note init + the record's own release restored by a
wavetable CMD_SETSR on the call before the drum's gate-off tick: built,
measured, NOT shipped (task drum-release-setsr-at-gate-off, base 5813a45).

The form: a drum record (bit $01, drum player, -S>1) is written with SR & $F0;
its wavetable's frame-0 padding entry (the repeat of the record's waveform, or
the last call of the delay that holds it) becomes `$F6 sr` (CMD_SETSR, gplay.c
:650 writes `sidreg[0x6+7*c]` in that very call), so the gate-off noise tick
still lands on the call it did and the release is back before the gate drops.
No slot is added at -S2 (the repeat is replaced), one at -S3 and above (the
delay is split). 19 of 29 drum files moved under presets, 10 did not (no room,
or the record is not the drum shape).

Result, VICE `dump` device, 60 s, presets, drum voice swapped onto voice 3
(rise -> first ENV3 increase; same attack set per arm):

* The tail survives: ENV3 summed over 8 frames from the rise equals the head's
  within 1%, where release nibble 0 alone lost 44% (Rasputin 500981 -> 504367,
  against rel0's 278660).
* **The wrap does not go.** Share of drum attacks starting within 5 lines of
  the rise stays at 0.5-4.9% (head 0-3.0%), delay median 466-512 lines
  (head 497-512). The reading that fits (reSID's rate counter, not itself
  traced): the mechanism is not the SR write at note init but what
  the release period was BEFORE it: the SID's rate counter keeps running in
  the release state at the record's long period (R=11: 3126 cycles), so at the
  next rise it is above the attack's 9-cycle period with probability
  ~(1 - 9/period) and must run on through $7FFF. The release-0 arm removed the
  wrap because the PREVIOUS note's whole release ran at period 9, which is
  exactly the tail it lost. Restoring the release at the gate-off tick gives
  back the long period for the rest of the previous note, so the wrap is
  back. A write one line before the rise (note init) cannot undo a counter
  that has been cycling at a long period; only a window of >= ~33 ms (1.67
  frames) at period 9 before the rise can, and that is the original's
  `ADSR $0000` write before every rise, which also cuts the previous tail.
* Fidelity, -t 180, presets, --sound, 29 files: `adsr_exact` mean -0.27 pp
  (falls on 9, rises on 0; Thrust -1.6 pp, Kentilla -0.7, Bump_Set_Spike
  -1.4); `release_tail_agreement` moves on none; `loud` mean -0.025 pp
  (down 17, up 11); `aud` -0.002 pp. Thrust also moves `gate` -0.3 pp,
  `sequence` +0.6 pp and `wave` +0.4 pp (the extra wavetable entry shifts the
  layout there).

So the pair of arms is: R=0 whole note removes the wrap and the tail
(adsr_exact -24 pp); R restored at the gate-off tick keeps the tail and the
wrap (adsr_exact -0.3 pp). The measured numbers are a keyed table (the shape
is not shipped, so there is no code to mutate); the code-facing pins below
break if either arm is adopted by accident.
"""
import json
import sys
import warnings
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
sys.path.insert(0, str(Path(__file__).resolve().parent))

from corpus import CORPUS, needs_corpus  # noqa: E402

# file: (head_on_time, setsr_on_time, head_tail_sum8, setsr_tail_sum8,
#        head_delay_median, setsr_delay_median)
# on_time = share of drum attacks whose rise -> first ENV3 increase is
# <= 5 lines (p/wrapfrac.py); tail sum8 = mean ENV3 summed over the 8 frames
# from the rise (p/drum2.py).
MEASURED = {
    "Rasputin": (0.030, 0.049, 500981, 504367, 511, 510),
    "Formula_1_Simulator": (0.020, 0.008, 445903, 446552, 512, 512),
    "Warhawk": (0.025, 0.005, 460425, 460140, 512, 468),
    "Proteus": (0.007, 0.014, 486924, 488600, 511, 466),
    "Bump_Set_Spike": (0.000, 0.011, 534700, 535728, 497, 497),
}
# The release-0 arm (tests/test_drum_release_adparam.py): 0.864 etc.
RELEASE_ZERO_ON_TIME_FLOOR = 0.85


@pytest.mark.parametrize("name", sorted(MEASURED))
def test_setsr_restore_keeps_the_tail_but_not_the_wrap_gone(name):
    h_on, s_on, h_tail, s_tail, h_med, s_med = MEASURED[name]
    assert abs(s_tail - h_tail) / h_tail < 0.01        # the tail is kept ...
    assert s_on < 0.06 < RELEASE_ZERO_ON_TIME_FLOOR    # ... the wrap is not gone
    assert s_med > 400                  # the original's median is 1 line


# adsr_exact, -t 180, presets, --sound: head -> setsr arm, the files it fell on
ADSR_EXACT = {
    "Bump_Set_Spike": (0.2959, 0.2823),
    "Deep_Strike": (0.9945, 0.9925),
    "Game_Killer": (0.2609, 0.2522),
    "Kentilla": (0.2666, 0.2595),
    "Proteus": (0.4792, 0.4699),
    "Rasputin": (0.6263, 0.6221),
    "Spellbound": (0.629, 0.6226),
    "Thrust": (0.42, 0.4038),
    "Warhawk": (0.4389, 0.4296),
}


@pytest.mark.parametrize("name", sorted(ADSR_EXACT))
def test_setsr_restore_costs_under_two_points_of_adsr_exact(name):
    head, arm = ADSR_EXACT[name]
    assert 0 < head - arm < 0.02          # rel0 paid 24 points on average


# ---------------------------------------------------------------------------
# code-facing pins
# ---------------------------------------------------------------------------
def _song(name: str):
    import fidelity as F
    import songview as V
    from h2g.convert import convert
    root = Path(__file__).resolve().parents[2]
    doc = json.loads((root / "presets.json").read_text(encoding="utf-8"))
    with warnings.catch_warnings():
        warnings.simplefilter("ignore")
        opts = F._preset_opts(doc, name + ".sid")
    return V.parse_sng(convert(str(next(CORPUS.rglob(name + ".sid"))),
                               log=lambda *a, **k: None, **opts))


@needs_corpus
@pytest.mark.parametrize("name", ["Rasputin", "Warhawk"])
def test_no_drum_record_is_written_with_release_zero_or_a_setsr_entry(name):
    """Neither half of the unshipped form is in the converter: no wavetable
    entry is the CMD_SETSR command ($F6), and no drum record has release 0."""
    song = _song(name)
    wave = song.tables["WTBL"]
    assert not [1 for left, _ in wave if left == 0xF6]
    drums = [i for i in song.instruments
             if i.effect_byte is not None and i.effect_byte & 0x01]
    assert drums and all(i.sr & 0x0F for i in drums), [i.adsr for i in drums]
