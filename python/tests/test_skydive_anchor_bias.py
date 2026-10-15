"""A compact skydive program falls from the ORIGINAL's note, not Goattracker's
(`goatwriter.skydive.anchor_bias`).

Last_V8_C128_version's windows on note 76 read one high byte up all the way
down (ours $570D against the original's $56AC): a relative-note-0 step puts
the voice on Goattracker's $57BA, the file's own table has $57AC, and the
vibrato tick that follows the fall (+$53 there) carries $56BA over to $570D
where $56AC reaches only $56FF. The fall's speed rows now carry the
difference, so the voice lands on the original's own frequency.
"""
import pathlib
import sys

from corpus import CORPUS, needs_corpus

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[1]))

import fidelity                                              # noqa: E402
from h2g.goatwriter import skydive as S                      # noqa: E402

import test_skydive_multispeed as M                          # noqa: E402


def test_the_speed_adds_the_bias_to_the_frames_movement():
    assert S.skydive_speed(3) == (3, 0)
    assert S.skydive_speed(3, bias=0x0E) == (3, 0x0E)
    # Divided with the movement at -S2: $300 + $0E is not a whole number of
    # units per call, $300 + $0E + 0 is.
    assert S.skydive_speed(3, 2, bias=0x0E) == (1, 0x87)
    assert S.skydive_speed(3, 2, bias=0x0F) is None


def test_the_bias_is_how_far_goattrackers_note_sits_above_the_originals():
    vib = S.SkydiveVibrato(counter=0, base=0x57AC, step=167, anchor=0x57BA)
    assert S.anchor_bias(vib) == 0x0E
    assert S.anchor_bias(None) == 0
    # An original table that is not known leaves anchor and base equal.
    assert S.anchor_bias(S.SkydiveVibrato(0, 0x57BA, 167, 0x57BA)) == 0
    assert S.anchor_bias(S.SkydiveVibrato(0, 0x57BA, 167)) == 0
    # Not a small interval: not a tuning difference.
    assert S.anchor_bias(S.SkydiveVibrato(0, 0x4000, 167, 0x4200)) == 0


def test_program_order_accepts_a_key_carrying_a_bias():
    plain = ((2, 30, True), None)
    assert S._program_order(plain + (0,)) < S._program_order(plain + (14,))


@needs_corpus
def test_last_v8_c128_falls_by_the_largest_bias_of_its_notes():
    """Notes 74, 76 and 78 are $08, $0E and $08 above the file's table; one
    program serves all three windows and takes $0E."""
    import songview
    sng, lines = M._converted("Last_V8_C128_version")
    assert "1 program(s)" in M._sky(lines)[0]
    speeds = songview.parse_sng(sng).tables["STBL"]
    assert (0x0C, 0x0E) in [tuple(e) for e in speeds] or any(
        e[0] == 0x0C and e[1] == 0x0E for e in speeds), speeds


@needs_corpus
@M.needs_siddump
@M.needs_gt2reloc
def test_last_v8_c128_windows_read_the_originals_high_byte(tmp_path):
    """Packed at -S2 and traced at -m2, 90 s: every store of the windows
    from frame 3500 (note 74, 76 and 78) names the original's high byte."""
    seconds = 90
    n = seconds * 50
    orig = fidelity.run_siddump(CORPUS / "Last_V8_C128_version.sid",
                                seconds, 0)
    stores = {f: hi for f, hi in M._store_frames(orig, n)[0].items()
              if f >= 3500}
    assert len(stores) >= 100, len(stores)
    sng, _ = M._converted("Last_V8_C128_version")
    packed = fidelity.pack_sid(sng, tmp_path, multiplier=2)
    assert packed is not None and packed.exists()
    ours = fidelity.run_siddump(packed, seconds + 1, 0, calls=2)
    lag = fidelity.startup_lag(orig, ours)[0]
    fq = fidelity.register_timeline(ours[0].freq_events, n + lag)
    assert sum(fq[f + lag] >> 8 == hi
               for f, hi in stores.items()) == len(stores)
