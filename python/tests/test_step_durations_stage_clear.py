"""`step_durations` starts a counter the set-up stage clears at 0, not at the image.

Auf_Wiedersehen_Monty's file image holds `$19` at its outer gate counter
(`$EA46`, top `$7F`), and the player's set-up stage clears it (`LDA #$00` ...
`STA $EA46`, `$E419`): a siddump of the original with `-wea46` reads `00` on
frame 0 and `7F` on frame 1. Read from the image, the first underflow came 25
calls late and every lengthened row of the schedule landed 14-29 frames after
the original's, a constant phase, so `regrid_phase` (which places the extra
frame on those rows) was unusable on this file. Read as 0, the lengthened
rows' start frames (123, 253, 380, 507, 637 from the first row) fall inside
the 13-frame gaps the original's attack grid shows at 122, 255, 376, 509, 630.
"""
import pathlib
import sys

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[1]))
sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent))

from corpus import CORPUS, needs_corpus                      # noqa: E402
from h2g.goatwriter import step_durations                    # noqa: E402
from h2g.goatwriter import tempo                             # noqa: E402
from h2g.sidfile import load_sid                             # noqa: E402


class _Sid:
    def __init__(self, data):
        self.data = data


def test_stage_clears_reads_lda_zero_then_sta_run_and_not_a_reload():
    ctr = b"\x46\xea"
    # LDA #0 / LDY $E8D8,X / STA $D404,Y / STA $E8DC,X / STA ctr   (Monty $E419)
    cleared = bytes([0xA9, 0x00, 0xBC, 0xD8, 0xE8, 0x99, 0x04, 0xD4,
                     0x9D, 0xDC, 0xE8, 0x8D]) + ctr
    assert tempo._stage_clears(_Sid(cleared), ctr)
    # LDA #$7F / STA ctr: the reload, not a clear
    reload_ = bytes([0xA9, 0x7F, 0x8D]) + ctr
    assert not tempo._stage_clears(_Sid(reload_), ctr)
    # a store of some other cell
    assert not tempo._stage_clears(_Sid(cleared), b"\x47\xea")


@needs_corpus
def test_monty_first_lengthened_rows_start_where_the_original_has_them():
    dur = step_durations(load_sid(str(CORPUS / "Auf_Wiedersehen_Monty.sid")), 700)
    start, fours = 0, []
    for i, d in enumerate(dur):
        if d == 4:
            fours.append((i, start))
        start += d
    # the original's attack grid (siddump, 180 s) has its 13-frame gaps at
    # 122, 255, 376, 509, 630: the first row starts on frame 2
    assert [f + 2 for _, f in fours[:5]] == [125, 255, 382, 509, 639]
    assert [r for r, _ in fours[:5]] == [41, 84, 126, 168, 211]


@needs_corpus
def test_the_corpus_files_that_read_the_gate_but_clear_nothing_are_unchanged():
    # IK_plus's image counters are 0 and its stage clears neither: the
    # schedule that regrid_phase was verified against is the same one.
    dur = step_durations(load_sid(str(CORPUS / "IK_plus.sid")), 7616)
    fours = [i for i, d in enumerate(dur) if d == 4]
    assert len(fours) == 204 and fours[:3] == [36, 74, 111]
