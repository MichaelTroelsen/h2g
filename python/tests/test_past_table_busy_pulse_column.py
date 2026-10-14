"""A note row that overflows a relative wave step but whose command column
holds CMD_SETPULSEPTR (forced pulse_phase on Thing_on_a_Spring) used to stay on
the relative step: `retarget_mixed_steps` could neither take the column for
CMD_SETWAVEPTR nor swap it. It now names a clone of the instrument carrying
the pinned wave pointer ("clonekeep": the vibrato and the row's pulse pointer
are untouched)."""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

from test_past_table_split import _corpus_convert                # noqa: E402
from test_past_table_variant_record_split import _overflowing_visits  # noqa: E402


def test_forced_pulse_phase_thing_on_a_spring_leaves_no_relative_step():
    _out, seen = _corpus_convert("Thing_on_a_Spring.sid", forced=True)
    assert seen and any(a != b for b, a, _s, _d in seen)
    assert any(_overflowing_visits(b) > 0 for b, _a, _s, _d in seen)
    assert all(_overflowing_visits(a) == 0 for _b, a, _s, _d in seen)


def test_clonekeep_keeps_the_vibrato():
    from h2g import past_table_wave as W
    from h2g.goatwriter.appending import _parse_song
    _out, seen = _corpus_convert("Thing_on_a_Spring.sid", forced=True)
    for before, after, _s, _d in seen:
        a, b = _parse_song(before), _parse_song(after)
        for rec in b.instruments[len(a.instruments):]:
            keep = [i for i in range(len(rec)) if i not in (2, W._VIBRATO_AT)]
            src = [r for r in a.instruments
                   if all(r[i] == rec[i] for i in keep)]
            assert src, "a clone differs from every instrument beyond wave/vibrato"
            assert src[0][W._VIBRATO_AT] and rec[W._VIBRATO_AT] == src[0][W._VIBRATO_AT]
