"""A two-stage attack longer than one delay entry spells out its whole length.

`_two_stage_entries` used to hold the attack waveform with ONE delay entry,
which is at most `WAVE_MAX_DELAY + 1` = 16 calls, so a stage past 16 calls
ended on call 17 whatever the record's counter said. Go_Go_Dash's record 13
(counter 15 frames, `$41` attack over a `$43` record waveform) at -S4 is 60
calls and sounded `$41` for 4 frames, then the record's `$43`, where the
original holds `$41` for the 15 counted frames
(`attack.TWO_STAGE_CHAIN`; C:/t/go-go-dash-sync-flashes-record-13/finding.md).
"""
import json
import pathlib
import sys

import pytest

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[1]))
from corpus import CORPUS, needs_corpus  # noqa: E402

from h2g.goatwriter import _two_stage_entries, attack  # noqa: E402
from h2g.goatwriter.attack import _stage_delay_chain, _wave_block_calls  # noqa: E402
from h2g.goatwriter.constants import WAVE_MAX_DELAY  # noqa: E402

ATTACK, OWN = 0x41, 0x43


def _stage_calls(left):
    """Calls the attack waveform stands: from its first entry to the entry
    that writes the record's own waveform after it."""
    a = left.index(ATTACK)
    b = left.index(OWN, a)
    return _wave_block_calls(left[a:b])


def test_the_chain_holds_exactly_the_calls_it_is_asked_for():
    for calls in range(2, 400):
        chain = _stage_delay_chain(calls)
        assert sum(d + 1 for d in chain) == calls, calls
        # no delay encodes one call, and none holds more than 16
        assert all(1 <= d <= WAVE_MAX_DELAY for d in chain), (calls, chain)


def test_a_sixty_call_stage_is_sixty_calls():
    left, right = _two_stage_entries(OWN, ATTACK, 15, 4, budget=40)
    assert _stage_calls(left) == 60
    assert left[-1] == 0xFF
    # every delay entry is a hold: the frequency byte is `keep`
    delays = [r for l, r in zip(left, right) if 0 < l <= WAVE_MAX_DELAY]
    assert delays and set(delays) == {0x80}


def test_a_stage_that_fits_one_delay_is_untouched():
    left, _ = _two_stage_entries(OWN, ATTACK, 4, 4, budget=40)
    assert _stage_calls(left) == 16
    assert _two_stage_entries(0x41, 0x81, 4)[0] == [0x41, 0x81, 0x02, 0x41, 0xFF]


def test_a_block_over_its_budget_keeps_the_single_delay():
    left, _ = _two_stage_entries(OWN, ATTACK, 15, 4, budget=5)
    assert _stage_calls(left) == 17


def test_the_switch_restores_the_single_delay(monkeypatch):
    monkeypatch.setattr(attack, "TWO_STAGE_CHAIN", False)
    left, _ = _two_stage_entries(OWN, ATTACK, 15, 4, budget=40)
    assert _stage_calls(left) == 17


@needs_corpus
def test_go_go_dash_record_13_holds_the_attack_for_its_fifteen_frames():
    import fidelity
    import songview
    from h2g.convert import convert

    root = pathlib.Path(__file__).resolve().parents[2]
    doc = json.load(open(root / "presets.json"))
    opts = fidelity._preset_opts(doc, "Go_Go_Dash.sid")
    # the song packs at -S4 (presets.json `multiplier`), which convert() derives
    mult = doc["songs"]["Go_Go_Dash.sid"]["multiplier"]
    song = songview.parse_sng(
        convert(str(CORPUS / "Go_Go_Dash.sid"), log=lambda m: None, **opts))
    # the only record whose program is a `$43` stage over a `$41` attack
    found = []
    for ins in song.instruments:
        if not ins.wave_ptr:
            continue
        prog = songview.wave_program(song, ins.wave_ptr)
        lefts = [row[1] for row in prog]
        if OWN in lefts and ATTACK in lefts:
            a = lefts.index(ATTACK)
            if OWN in lefts[a:]:
                found.append(_stage_calls(lefts))
    assert found == [15 * mult], (mult, found)


@needs_corpus
def test_a_table_that_would_starve_a_later_record_keeps_the_single_delay(
        monkeypatch):
    """W_A_R's wavetable is 250 of 255 entries; chained, its record 11 fell
    from the 14-entry arpeggio program to the plain shape (pitch 100% -> 96%).
    The layout guard (`wavetable.chain_is_safe`) lays the table out both ways
    and refuses the chain, so the file converts as before; with the guard
    forced open the bytes differ."""
    import fidelity
    from h2g.convert import convert
    from h2g.goatwriter import wavetable

    root = pathlib.Path(__file__).resolve().parents[2]
    doc = json.load(open(root / "presets.json"))
    opts = fidelity._preset_opts(doc, "W_A_R.sid")
    path = str(CORPUS / "W_A_R.sid")
    guarded = convert(path, log=lambda m: None, **opts)
    monkeypatch.setattr(attack, "TWO_STAGE_CHAIN", False)
    off = convert(path, log=lambda m: None, **opts)
    assert guarded == off
    monkeypatch.setattr(attack, "TWO_STAGE_CHAIN", True)
    monkeypatch.setattr(wavetable, "chain_is_safe", lambda a, k: True)
    forced = convert(path, log=lambda m: None, **opts)
    assert forced != off
