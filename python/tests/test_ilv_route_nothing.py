"""`ilv_filter_routing` writes an empty union as `B $00`, which stops the program.

The interleaved player's cutoff never moves while no voice is routed (traced
on all five filtering ILV originals); the old `B $X0` left the Goattracker
filter table running, so a program's FILT_MODULATE kept sweeping a cutoff
nobody hears -- Radio_ACE's `cut` 1.379 -> 1.431. See ILV_ROUTE_NOTHING in
goatwriter/constants.py.
"""
import json
import pathlib

import pytest

from corpus import CORPUS, needs_corpus  # noqa: E402
from h2g.goatwriter import (CMD_SETFILTERCTRL, ILV_ROUTE_NOTHING,
                            _ilv_routing_walk, _ilv_voice_rows)

PYTHON_ROOT = pathlib.Path(__file__).resolve().parents[1]
_REST = (0xBD, 0, 0, 0)
_ROUTED, _PLAIN = 1, 2          # instr_base 1: record 0 routed, record 1 not


def _pattern(rows, length=8):
    out = []
    for r in range(length):
        out += list(dict(rows).get(r, _REST))
    return out + [0xFF, 0, 0, 0]


def _walk(patterns, tracks, horizon, programs):
    timeline = [_ilv_voice_rows(t, patterns, horizon) for t in tracks]
    return _ilv_routing_walk([(horizon, timeline)], patterns, 1, {0},
                             programs, "shared", {}, {})


def test_route_nothing_is_b_00():
    assert ILV_ROUTE_NOTHING == 0x00


def test_an_empty_union_drops_the_resonance_and_stops_the_program():
    """SABOTAGE TARGET: restore `(res or ILV_EMPTY_UNION)` as the empty-union
    value and row 3 reads $40 -- the table keeps running."""
    patterns = [_pattern({1: (0x90, _ROUTED, 0, 0), 3: (0x90, _PLAIN, 0, 0)}),
                _pattern({}), _pattern({})]
    tracks = [[0, 0xFF, 0], [1, 0xFF, 0], [2, 0xFF, 0]]
    plan, stats = _walk(patterns, tracks, 8, {0: (0x10, 0x40, 0x80, 0x02)})
    assert plan == {(0, 0): {1: (CMD_SETFILTERCTRL, 0x41),
                             3: (CMD_SETFILTERCTRL, 0x00)}}, plan
    assert stats["late_rows"] == 0 and stats["stopped_live"] == 0


def test_a_replayed_b_00_under_a_routed_voice_is_counted():
    """SABOTAGE TARGET: drop the `stopped_live` count. Voice 0 plays pattern
    0 twice (REPEAT $D1); its first play writes `B $00` at row 3, and on the
    second play voice 2 is routed at that row, so the replayed stop lands on
    a live program -- which no later `B` can restart, so it is counted."""
    patterns = [_pattern({1: (0x90, _ROUTED, 0, 0), 3: (0x90, _PLAIN, 0, 0)}),
                _pattern({}, 16),
                _pattern({10: (0x90, _ROUTED, 0, 0)}, 16)]
    tracks = [[0xD1, 0, 0xFF, 0], [1, 0xFF, 0], [2, 0xFF, 0]]
    plan, stats = _walk(patterns, tracks, 16, {0: (0x10, 0x40, 0x80, 0x02)})
    assert plan[(0, 1)] == {1: (CMD_SETFILTERCTRL, 0x41),
                            3: (CMD_SETFILTERCTRL, 0x00)}, plan
    assert stats["stopped_live"] == 1, stats


@needs_corpus
@pytest.mark.skipif(not pathlib.Path(
    __import__("fidelity").SIDDUMP).exists(), reason="no siddump")
def test_radio_ace_cutoff_holds_still_while_nothing_is_routed(tmp_path):
    """siddump, -t 180 under presets: the ORIGINAL moves its cutoff on no
    frame without a routed voice and a passband; neither may ours. Under
    `B $X0` ours travelled 564,224 there and `cut` read 1.4305; `B $00`
    takes it to 0 and 1.1560 (6e467ff plus the cycle-c5 merge)."""
    import fidelity as F
    from h2g.convert import convert
    doc = json.loads((PYTHON_ROOT.parent / "presets.json").read_text())
    name = "Radio_ACE.sid"
    opts = F._preset_opts(doc, name)
    assert opts.get("ilv_filter_routing"), "presets no longer route ILV"
    sub, our_sub, _ = F.resolve_pair(CORPUS / name, "auto")
    nf = 180 * 50

    def travel(trace):
        f = trace.filter
        cut = F.register_timeline(f.cutoff_events, nf)
        ctrl = F.register_timeline(f.ctrl_events, nf)
        band = F.register_timeline(f.passband_events, nf)
        total = sum(abs(cut[i] - cut[i - 1]) for i in range(1, nf))
        unrouted = sum(abs(cut[i] - cut[i - 1]) for i in range(1, nf)
                       if not (ctrl[i] & F.FILTER_ROUTE and band[i]))
        return total, unrouted

    local = tmp_path / name
    local.write_bytes((CORPUS / name).read_bytes())
    cal, _ = F.table_calibration(CORPUS / name, opts)
    o_total, o_unrouted = travel(F.run_siddump(local, 180, sub, F.SIDDUMP, cal))
    sng, _ = F.legalise_restarts(bytes(convert(str(CORPUS / name),
                                               lambda m: None, **opts)))
    mult = F._preset_multiplier(doc, name)
    packed = F.pack_sid(sng, tmp_path, F.GT2RELOC, mult)
    assert packed is not None
    u_total, u_unrouted = travel(F.run_siddump(packed, 180, our_sub, F.SIDDUMP,
                                               0, calls=mult))
    assert o_total > 0 and o_unrouted == 0, (o_total, o_unrouted)
    assert u_unrouted == 0, u_unrouted
    assert u_total / o_total < 1.3, (u_total, o_total)
