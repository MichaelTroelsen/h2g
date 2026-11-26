"""`drum_long` at -S1: Geoff_Capes_Strongman_Challenge's bit-$01 drum falls.

Geoff's drum records (`drum, arpeggio, pulse-lo`) are played at four rows and
eight, three calls a row at -S1. The original's block sweeps the frequency high
byte down one a frame from the unit after the first: a four-row note falls
`106E -> 0B6E` on frames +4..+8 (`(4 - 2) * 3 - 1` = 5 steps, Commando's own
figure), an eight-row one on to the high byte's floor (`0F6E ... 016E`, 15
steps). `_drum_entries` lays at most two `CMD_PORTADOWN` entries on the
five-entry layout, so everything after the second step went missing (`tie`
orig-only 70 of 326 original ties, `travel` and `cents` on voice 0).

`drum_long` was planned from -S2 only, and declined any record whose MEDIAN
note is three rows or more. At -S1 it declines on the record's own sweep
(`own_sweep`) against what the note leaves room for, and the head opens on the
noise tick's second frame (`lead_noise`), because the row after the drum note
starts `row_calls - 1` frames after the attack's visible frame.

A per-song `convert()` option (off by default; nothing ships it at -S1).
"""
import json
import pathlib
import sys

import pytest

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[1]))

import fidelity                                              # noqa: E402
from corpus import CORPUS, needs_corpus                      # noqa: E402
from h2g.convert import convert                              # noqa: E402
from h2g.goatwriter import drum_long                         # noqa: E402
from h2g.goatwriter.constants import (CMD_SETWAVEPTR, FORMAT_GTS5,  # noqa: E402
                                      GT_WAVE_JUMP, WAVECMD_PORTADOWN)
from songview import parse_sng                                # noqa: E402

GEOFF = CORPUS / "Geoff_Capes_Strongman_Challenge.sid"
REPO_ROOT = pathlib.Path(__file__).resolve().parents[2]


def _doc() -> dict:
    return json.loads((REPO_ROOT / "presets.json").read_text(encoding="utf-8"))


def _convert(**kw):
    opts = fidelity._preset_opts(_doc(), GEOFF.name)
    return convert(str(GEOFF), log=lambda m: None, **{**opts, **kw})


def _heads(blob):
    """(pattern, row, head lefts, chain length) of every SETWAVEPTR whose head
    is hold entries into a jump onto a PORTADOWN chain ending in a jump."""
    song = parse_sng(blob)
    wave = song.tables["WTBL"]
    found = []
    for pi, pat in enumerate(song.patterns):
        for r in range(0, len(pat) - 3, 4):
            if pat[r + 2] != CMD_SETWAVEPTR:
                continue
            i = pat[r + 3] - 1
            head = []
            while wave[i][0] != GT_WAVE_JUMP and len(head) < 6:
                head.append(wave[i][0])
                i += 1
            if wave[i][0] != GT_WAVE_JUMP:
                continue
            target = wave[i][1]
            n = 0
            while wave[target - 1 + n][0] == WAVECMD_PORTADOWN:
                n += 1
            if n and wave[target - 1 + n][0] == GT_WAVE_JUMP:
                found.append((pi, r // 4, head, n))
    return found


def test_own_sweep_counts_the_records_portadown_entries():
    entries = [(0x41, 0x00), (0x80, 0x00), (WAVECMD_PORTADOWN, 3),
               (WAVECMD_PORTADOWN, 3), (0xFF, 0x00),
               (WAVECMD_PORTADOWN, 3)]          # past the stop: not counted
    assert drum_long.own_sweep(entries, 1) == 2
    assert drum_long.own_sweep(entries, 3) == 2
    assert drum_long.own_sweep(entries, 0) == 0
    assert drum_long.own_sweep([], 1) == 0


def test_the_plan_needs_the_table_at_s1():
    """Without the wavetable the -S1 plan cannot know the own sweep."""
    class Det:                                    # noqa: D401
        effect_drum = True
    assert drum_long.drum_long_plan(None, Det(), [], [], 0, 0, FORMAT_GTS5, 1,
                                    None, [], 0, 3, {1: 4}) is None


@needs_corpus
def test_off_emits_no_head():
    assert _heads(_convert(drum_long=False)) == []


@needs_corpus
def test_s1_drum_notes_get_the_players_full_sweep(monkeypatch):
    # Counted with the -S1 drum sweep cut at DRUM_MAX_SWEEP_STEPS, as when
    # this was written; uncapped (shipped since v0.5.683) see the next test.
    from h2g.goatwriter import wavetable
    monkeypatch.setattr(wavetable, "DRUM_SWEEP_UNCAP_S1", False)
    heads = _heads(_convert(drum_long=True))
    chains = sorted(n for _p, _r, _h, n in heads)
    # Four-row notes: (4 - 2) * 3 - 1 = 5 steps. The eight-row note's 17 is cut
    # to the 16 the high byte allows, and a pitch that falls less to 12.
    assert len(heads) == 12
    assert chains.count(5) == 10
    assert 16 in chains and 12 in chains


@needs_corpus
def test_uncapped_the_twelve_step_fall_is_the_records_own():
    """With the -S1 drum sweep uncapped (`wavetable.DRUM_SWEEP_UNCAP_S1`),
    pattern 23 row 1's twelve-step fall is carried by instrument 9's own
    wavetable (12 PORTADOWN entries, 8 when capped), so drum_long declines
    its head on `own_sweep` and no SETWAVEPTR is written there."""
    from h2g.goatwriter import wavetable
    assert wavetable.DRUM_SWEEP_UNCAP_S1
    blob = _convert(drum_long=True)
    heads = _heads(blob)
    assert len(heads) == 11
    assert sorted(n for *_x, n in heads).count(5) == 10 and 16 in [n for *_x, n in heads]
    song = parse_sng(blob)
    pat = song.patterns[23]
    assert pat[1] == 9 and pat[6] != CMD_SETWAVEPTR
    wave = song.tables["WTBL"]
    k = song.instruments[8].wave_ptr - 1
    own = 0
    while wave[k][0] != GT_WAVE_JUMP:
        own += wave[k][0] == WAVECMD_PORTADOWN
        k += 1
    assert own == 12


@needs_corpus
def test_s1_head_opens_on_the_noise_tick_then_the_gate_off_wave():
    heads = _heads(_convert(drum_long=True))
    assert heads
    for _p, _r, head, _n in heads:
        # noise ($80) on the tick's second frame, then the record's gate-off
        # waveform for the frame the sweep's first (no-change) step takes.
        assert head == [0x80, 0x40]
