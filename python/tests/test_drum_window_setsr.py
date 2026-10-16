"""A window of period 9 before each drum rise: built, measured, NOT shipped
(task open-a-window-of-period-9-before, base ba696cb).

The form: the record's release restored by a wavetable CMD_SETSR at the gate-off
tick (the unshipped arm of test_drum_release_setsr.py), then a SECOND
`$F6 00` after the tail, behind a delay, timed `back` frames before the
record's typical note end (`note_rows * row_calls`), so the SID's rate counter
runs at period 9 (release 0) for the last frames before the next rise.
Built into the table only where it fits the record's budget (it always did:
the same 19 of 89 files move as with the restore alone, and a trimming variant
that gave up sweep steps moved the same bytes).

VICE `dump` device, 60 s, presets, drum voice swapped onto voice 3. Share of
drum attacks whose rise -> first ENV3 increase is <= 5 lines, head -> window
(back 2 frames), and tail sum8 mean:
"""
import json
import sys
import warnings
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
sys.path.insert(0, str(Path(__file__).resolve().parent))

from corpus import CORPUS, needs_corpus  # noqa: E402

# file: (head_on_time, restore_on_time, window_on_time,
#        head_tail_sum8, restore_tail_sum8, window_tail_sum8)
MEASURED = {
    "Rasputin": (0.023, 0.042, 0.659, 500622, 502725, 517826),
    "Formula_1_Simulator": (0.008, 0.012, 0.016, 446062, 446586, 443634),
    "Warhawk": (0.025, 0.005, 0.252, 460425, 460140, 457519),
    "Proteus": (0.007, 0.014, 0.209, 486924, 488600, 481240),
    "Bump_Set_Spike": (0.000, 0.011, 0.014, 534700, 535728, 521000),
}
# The release-0 arm reached 0.86-0.91 and the original has no wrap to speak of.
RELEASE_ZERO_ON_TIME_FLOOR = 0.85


@pytest.mark.parametrize("name", sorted(MEASURED))
def test_window_moves_the_wrap_on_two_files_and_not_the_rest(name):
    h, r, w, h_t, r_t, w_t = MEASURED[name]
    assert w < RELEASE_ZERO_ON_TIME_FLOOR      # never as clean as release 0
    assert w >= h                               # but the window does not hurt it
    if name in ("Rasputin", "Warhawk", "Proteus"):
        assert w > 0.2 and w > 5 * r            # the restore alone did not do this
    else:
        assert w < 0.02                         # no effect on the other two
    # the tail: -2.6 % at most (Bump_Set_Spike), Rasputin gains 3.4 %
    assert -0.03 < (w_t - h_t) / h_t < 0.04


# adsr_exact, -t 180, presets, --sound, head -> window, back in frames.
# EVERY offset tried costs the column on every one of the five files.
ADSR_EXACT = {
    "Rasputin": (0.6263, {0.5: 0.6166, 1: 0.6166, 2: 0.6096, 3: 0.6175, 4: 0.6138}),
    "Formula_1_Simulator": (0.6517, {0.5: 0.6226, 1: 0.6226, 2: 0.6217, 3: 0.6343, 4: 0.6343}),
    "Warhawk": (0.4389, {0.5: 0.4222, 1: 0.4216, 2: 0.4192, 3: 0.4106, 4: 0.3996}),
    "Proteus": (0.4792, {0.5: 0.4625, 1: 0.4619, 2: 0.4596, 3: 0.4510, 4: 0.4399}),
    "Bump_Set_Spike": (0.2959, {0.5: 0.2820, 1: 0.2820, 2: 0.2819, 3: 0.2819, 4: 0.2823}),
}


@pytest.mark.parametrize("name", sorted(ADSR_EXACT))
def test_window_costs_adsr_exact_at_every_offset_tried(name):
    head, arms = ADSR_EXACT[name]
    assert all(a < head for a in arms.values()), (name, head, arms)


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
def test_no_wavetable_entry_is_a_setsr_command(name):
    """The converter writes no CMD_SETSR ($F6) into a wavetable and no drum
    record has release 0: neither half of the unshipped form is adopted."""
    song = _song(name)
    assert not [1 for left, _ in song.tables["WTBL"] if left == 0xF6]
    drums = [i for i in song.instruments
             if i.effect_byte is not None and i.effect_byte & 0x01]
    assert drums and all(i.sr & 0x0F for i in drums), [i.adsr for i in drums]
