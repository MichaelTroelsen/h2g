"""Effect bit $02's every-other-frame waveform.

The bit is the *rise* in Warhawk's dialect and this in another 21 corpus
files, which is why the emitter is gated on the routine being found rather
than on the bit alone -- the mistake `_fixed_attack_note` made against
Thundercats' drum, in the other direction.
"""
from pathlib import Path

import pytest

from h2g.detect import Detection, _find_wave_alternate
from h2g.goatwriter import _wave_alternate_entries, _wavetable_entries

CORPUS = Path(r"C:\Users\mit\claude\c64server\SIDM2\SID\Hubbard_Rob")


def test_the_shape_is_the_lead_then_the_pair_looping():
    # W_A_R instrument $0900: `+2` is $11 (triangle), the alternate $81
    # (noise). Its original reads `tri tri noi tri` on all 205 onsets -- the
    # note's first frame is the init path's, and the alternation runs from the
    # second, so the loop target is the first of the pair and not entry 0.
    left, right = _wave_alternate_entries(0x11, 0x81, 1, start=6, budget=8)
    assert left == [0x11, 0x11, 0x81, 0xFF]
    assert right == [0x00, 0x00, 0x00, 7], "loops to the pair, not the lead"
    # ...and every right side is $00, which in the PACKED player is "no
    # frequency write" (`player.s:976-977` tests `bne`). $80 is not the same
    # thing here as it is in the editor: it reaches `adc chnnote / and #$7f`,
    # which is a no-op transposition but still a write, re-asserting the base
    # note every frame. Emitted with $80, Hollywood or Bust's melody fell
    # 58% -> 25% against 47% with $00.


@pytest.mark.parametrize("multiplier,left", [
    (1, [0x11, 0x11, 0x81, 0xFF]),
    (2, [0x11, 0x11, 0x11, 0x11, 0x81, 0x81, 0xFF]),
    (3, [0x11, 0x01, 0x11, 0x01, 0x81, 0x01, 0xFF]),
])
def test_each_half_lasts_a_frame_at_every_multiplier(multiplier, left):
    """A frame is `multiplier` play calls, and a delay entry is current for
    `value + 1` of them. W_A_R packs at -S4 and its shape is frame-exact
    there, which is the check that this arithmetic is right."""
    got, _ = _wave_alternate_entries(0x11, 0x81, multiplier, start=6, budget=12)
    assert got == left


def test_it_declines_what_it_cannot_say():
    # An alternate inside the delay range is not a waveform at all; one equal
    # to the record's own +2 alternates with itself; and a record with no
    # waveform has nothing to alternate from.
    assert _wave_alternate_entries(0x11, 0x0F, 1, start=6) is None
    assert _wave_alternate_entries(0x11, 0x11, 1, start=6) is None
    assert _wave_alternate_entries(0x00, 0x81, 1, start=6) is None
    # ...and a block that will not fit is declined rather than truncated.
    assert _wave_alternate_entries(0x11, 0x81, 4, start=6, budget=5) is None


def test_the_bit_alone_is_not_enough():
    """`det.wave_alternate` says the player *has* the routine. Without it the
    record's bit $02 means the rise, or nothing."""
    class _Sid:
        def __init__(self):
            self.data = bytes(8) + bytes([0, 0, 0x11, 0x09, 0x00, 0, 0, 0x02])
            self.start_song = 1
    det = Detection(instr_start=8, instr_stride=8)      # wave_alternate = -1
    left, _ = _wavetable_entries(_Sid(), det, 0, True, "gts5", [], 1,
                                 start=6, budget=8)
    assert 0x81 not in left


def test_the_corpus_files_that_carry_it():
    if not CORPUS.is_dir():
        return
    from h2g.detect import detect
    from h2g.sidfile import load_sid
    files = records = 0
    for path in sorted(CORPUS.glob("*.sid")):
        try:
            sid = load_sid(str(path))
            det = detect(sid, log=lambda m: None)
        except Exception:                              # noqa: BLE001
            continue
        if det.wave_alternate < 0:
            continue
        files += 1
        records += sum(
            1 for i in range(det.instr_used)
            if det.instr_start + i * det.instr_stride + 7 < len(sid.data)
            and sid.data[det.instr_start + i * det.instr_stride + 7] & 0x02)
    assert files == 21, files
    assert records == 98, records


def test_the_block_is_anchored_on_this_instrument_tables_own_plus_two():
    """What stops it matching any `AND #$02` followed by two indexed loads.

    The first operand must be the records' `+2` field; the second is then the
    alternate table. Pinned on W_A_R, whose tables sit at $E94E and $EA50.
    """
    if not CORPUS.is_dir():
        return
    from h2g.detect import detect
    from h2g.sidfile import load_sid
    sid = load_sid(str(CORPUS / "W_A_R.sid"))
    det = detect(sid, log=lambda m: None)
    base = sid.load_addr - 0x7E
    assert det.instr_start + base == 0xE94E
    assert det.wave_alternate + base == 0xEA51
    # ...and it is one byte past the two-stage attack waveform, which is how
    # the aux record's fields line up: +0 attack, +1 alternate, +2 frames.
    assert det.wave_alternate == det.two_stage_wave + 1
    assert _find_wave_alternate(sid, det) == det.wave_alternate
