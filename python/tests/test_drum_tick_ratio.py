"""The bit-$01 drum sweep under an outer gate the TRACK reloads (Rasputin).

Rasputin's player (`$C325`-`$C348`, the Warhawk `$1366` block) subtracts one
from the frequency high byte once per TICK, from the second unit of a note.
Its outer gate is reloaded by the track (`$FE nn`), so a tick is not a frame and
`outer_gate_skip` has no `O` to read. Traced over 180 s (task
`listen-sub99-rasputin`, historical), the sweep a record plays is a CONSTANT
count of ties whatever the note's length or the tempo section: record `$0A0B`
11, `$0909` and `$0A09` 3. The wall-clock row count `_drum_duration_steps` used
(`(note_rows - 2) * row_calls - gate`) carries the skipped frames, and the
corpus-wide 8-step cap cut the long record, so ours played 8-9, 4-5 and 4-5:
tied-frame agreement 59%.

Sized on the record's own tick clock (`Detection.drum_tick_ratios`, from
`pulse.track_set_tick_ratios`) the counts are 11 / 3 / 3 exactly.
"""
import pathlib
import sys
from fractions import Fraction

import pytest

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[1]))

import fidelity                                              # noqa: E402
from corpus import CORPUS, needs_corpus                      # noqa: E402
from h2g.convert import convert                              # noqa: E402
from h2g.goatwriter import wavetable                         # noqa: E402
from h2g.goatwriter.constants import WAVECMD_PORTADOWN      # noqa: E402
from songview import parse_sng                                # noqa: E402

import json

RASPUTIN = CORPUS / "Rasputin.sid"
REPO_ROOT = pathlib.Path(__file__).resolve().parents[2]
C = Fraction(1117, 1000)          # record $0A0B's time-weighted clock, -S2


def test_duration_steps_are_ticks_not_wall_clock_rows():
    # row_calls 5 at -S2 is the rounded 2 ticks * 2 * c; 8 rows is `$0A0B`.
    assert wavetable._drum_duration_steps(8, 5, 2, None, C) == 22   # 11 ticks
    assert wavetable._drum_duration_steps(4, 5, 2, None, C) == 6    # 3 ticks
    assert wavetable._drum_duration_steps(2, 5, 2, None, C) == 0


def test_without_a_tick_ratio_the_wall_clock_count_is_unchanged():
    assert wavetable._drum_duration_steps(8, 5, 2, None) == 28
    assert wavetable._drum_duration_steps(4, 5, 2, None) == 8
    assert wavetable._drum_duration_steps(8, 3, 1, 3) == 17         # static O


def test_the_corpus_cap_is_lifted_only_where_a_tick_ratio_sizes_the_sweep():
    capped = wavetable._drum_max_steps(40, 2, None)
    assert capped == wavetable.DRUM_MAX_SWEEP_STEPS * 2
    assert wavetable._drum_max_steps(40, 2, None, capped=False) > capped


@needs_corpus
def test_rasputin_sweeps_the_record_s_own_tick_count():
    doc = json.loads((REPO_ROOT / "presets.json").read_text(encoding="utf-8"))
    opts = fidelity._preset_opts(doc, RASPUTIN.name)
    song = parse_sng(convert(str(RASPUTIN), log=lambda m: None, **opts))
    wave = song.tables["WTBL"]
    runs = {}
    for ins in song.instruments:
        n, i = 0, ins.wave_ptr - 1
        while i < len(wave) and wave[i][0] != 0xFF:      # to the stop
            n += wave[i][0] == WAVECMD_PORTADOWN
            i += 1
        if n:
            runs[ins.number] = n
    # entries = ticks x multiplier (2): 3 ticks, 3 ticks, 11 ticks
    assert runs[2] == 6 and runs[4] == 6 and runs[13] == 22, runs
