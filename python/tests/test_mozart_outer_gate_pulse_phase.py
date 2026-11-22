"""`pulse_phase` on Mozart (`listen-sub99-mozart`, measured at d66e7a3).

Mozart's pulse engine is the triangle (PULSE_TRI_MASKS_SHAPE) behind a play
routine with an OUTER gate and no inner speed gate (`$0829 DEC $0C33 / BPL`).
Forced `pulse_phase` declined it for two reasons, both pinned here:

* `triangle_start` read the speed counter off the inner gate, found none and
  returned None -- "the triangle player's start state or row clock cannot be
  read; not walked" -- though with no inner gate every working call advances
  the voice counters, `$083E` clears them, and the first call fetches. The
  start now carries `counter=None` and `prefetch` is 0.
* Once walked, the phase blocks of the records laid first (130, 129, 62 ...
  rows) left the 255-row table too little for the later ones, and the nine
  that did not fit fell back to a width that never moves, so `poff` fell
  .856 -> .590. `build_pulse_phase_table` now also lays the table holding back
  each later record's ORDINARY sweep and ships it where it places more
  phase-tracked records and strands fewer on a static width: 7 of 14 placed,
  every other record on its own sweep (`pphase` .367 -> .833, `pspan` .882 ->
  .932, `poff` .856 -> .879 under forced `pulse_phase`).

Under presets nothing moves: Mozart's entry does not set `pulse_phase`.
"""
from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from test_pulse_phase import (_forced_pulse_phase_logs,  # noqa: E402
                              _forced_table_args, _play_pulse_table)

CORPUS = Path(r"C:/Users/mit/claude/c64server/SIDM2/SID/Hubbard_Rob")


def _mozart():
    import pytest
    path = CORPUS / "Mozart.sid"
    if not path.exists():
        pytest.skip("Mozart.sid not in the corpus here")
    from h2g.detect import detect
    from h2g.sidfile import load_sid
    sid = load_sid(str(path))
    return sid, detect(sid, lambda *a, **k: None)


def test_the_outer_gate_only_player_has_a_start_and_sweeps_nothing_before_it():
    from h2g.goatwriter import triangle_start
    sid, det = _mozart()
    st = triangle_start(sid, det, lead=0)
    assert st is not None
    assert st.cells == ((1, 0), (1, 0), (1, 0))
    assert st.instruments == (1, 2, 3)
    assert st.counter is None
    assert st.prefetch(1) == 0


def test_a_player_with_an_inner_gate_still_counts_its_prefetch():
    from h2g.goatwriter import TriangleStart
    # 5_Title_Tunes: counter 3 against a reload of 3 -> three ticks sweep
    assert TriangleStart(((1, 0),) * 3, (1, 2, 3), 3).prefetch(4) == 3


def test_forced_pulse_phase_walks_mozart_and_ships_the_sweeps_layout():
    lines = _forced_pulse_phase_logs("Mozart.sid")
    assert not any("not walked" in l for l in lines), lines
    assert not any("SET NO WIDTH AT ALL" in l for l in lines), lines
    assert any(l.startswith("Pulse phase.............: sweeps reserved -- "
                            "shared ramps, 253 table row(s) place 7 of 14 "
                            "phase-tracked record(s) and degrade 7 record(s), "
                            "0 to pointer 0")
               for l in lines), lines


def test_every_record_the_table_cannot_phase_keeps_a_moving_sweep():
    import h2g.goatwriter as G
    args, table = _forced_table_args("Mozart.sid")
    sid, det, iu, pulse, mult, phases, _, lead = args
    assert table is not None
    entries, starts, index = table
    phased = {k[0] for k in index}
    assert len(phased) == 7, sorted(phased)
    checked = 0
    for i in range(max(iu - lead, 0)):
        num = i + 1 + lead
        program, _loop = G._pulse_program(sid, det, i, True, mult)
        if num in phased or len(program) <= 2:
            continue                      # laid in phases, or never sweeps
        assert starts[num - 1] != 0, num
        widths = _play_pulse_table(entries, starts[num - 1], 400)
        assert len(set(widths)) > 1, (num, "width never moves")
        checked += 1
    assert checked == 7, checked
