"""The free-running cutoff holds for one call at every event its voice fetches.

Sigma_Seven's `$830B` sweep (`LDA $84A1,X / ADC step / STA $84A1,X / STA
$D416`) sits BEHIND the note-fetch path: a voice that fetches an event ends
`JMP $8347` (`$8197`) past the filter block, so on that frame it adds no step.
The voices run X = 2, 1, 0, so voice 0's write is the one the chip keeps, and
voice 0's fetch frames are holds in the cutoff: 128 of the first 3563 frames
after power-on in the original. `tests/test_filter_fetch_hold.py` names the
same fact for the classic engine, where the next note's reset to its start
value hides a missed hold; here nothing resets the accumulator, so a missed
hold is a step the conversion keeps for ever.

Goattracker holds on a NEW NOTE for free: the instrument loads the filter
pointer, and the next call runs the table's params row, which adds no step
(player.s `mt_setfilt`). A TIE skips the instrument load (gplay.c:354) and a
KEYOFF has none, so neither held, and the cutoff took a step the original did
not at every one -- the conversion held on 80 of those 128, missing 48, a
net drift of +2 each, +80 by frame 3460, which is what held back the
start-value patch (`free_running_start`: first-300-frame error 4.67 -> 3.33
but whole-tune 18.2 -> 25.4).

`free_running_fetch_holds` writes a `CMD_SETFILTERPTR` to the instrument's own
params row on the event's row, or the nearest free row before it.

Measured on Sigma_Seven under presets at `-t 180` (mean circular |cutoff
difference|, frames 10-3500, ours shifted by the 5-frame startup lag; the
same formula as the start-value patch's record):

                              first 300 frames    whole tune
    base (862f703)                 4.67              18.23
    start value only               3.33              25.43
    holds only (back 3)            8.19               8.17
    both, back 2                   0.19               2.31
    both, back 3 (shipped)         0.19               0.17

Holds alone leave the start 8 low; the start alone leaves the drift; the
pair cancels both. `back` 2 leaves the two plays of pattern $03 without a
hold (its tie at row 77 follows two funk-tempo rows), two missed holds, +4.
`cutoff_sweep` 1.023 -> 0.999; `our_cutoff_travel` 3256832 -> 3181056 against
the original's 3183104; melody, wave, adsr and every other column unchanged.
"""
import dataclasses
import json
import pathlib
import sys

import pytest

from corpus import CORPUS, needs_corpus

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[1]))

import fidelity                                              # noqa: E402
from h2g.convert import convert                              # noqa: E402
from h2g.goatwriter import (CMD_SETFILTERPTR, FETCH_HOLD_BACK,   # noqa: E402
                            FILT_SET_PARAMS, _fetch_hold_pattern,
                            _free_running_block,
                            free_running_fetch_hold_voice,
                            free_running_fetch_holds)
from h2g.search import search_file                           # noqa: E402
from h2g.sidfile import load_sid                             # noqa: E402
from songview import parse_sng                               # noqa: E402
from test_filter_absent_four import gt_filter_calls          # noqa: E402

REPO = pathlib.Path(__file__).resolve().parents[2]
REST, KEYOFF = 0xBD, 0xBE
NOTE = 0x90
needs_siddump = pytest.mark.skipif(
    not pathlib.Path(fidelity.SIDDUMP).exists(),
    reason="no siddump on this machine (tools/siddump-rt, see its README)")
needs_gt2reloc = pytest.mark.skipif(
    not pathlib.Path(fidelity.GT2RELOC).exists(),
    reason="no gt2reloc on this machine")


def _pat(*rows):
    """Flat pattern bytes from (note, instr, cmd, data) rows, `$FF` row last."""
    flat = []
    for r in rows:
        flat += list(r)
    return flat + [0xFF, 0, 0, 0]


def _rest(cmd=0, data=0, ins=0):
    return (REST, ins, cmd, data)


def _tie(ins=0, note=NOTE):
    return (note, ins, 3, 0)


def _plan(pattern, instr=1, running=0, ptr_of=None, back=FETCH_HOLD_BACK):
    return _fetch_hold_pattern(pattern, instr, running,
                               {1: 1, 4: 4} if ptr_of is None else ptr_of,
                               back)


# --- which rows are events, and where the hold goes ---------------------------

def test_a_new_note_is_not_an_event():
    """Its instrument load is the hold (gplay.c:388, the params row after)."""
    writes, skips, _i, _r = _plan(_pat((NOTE, 1, 0, 0), _rest(), (NOTE, 4, 0, 0)))
    assert (writes, skips) == (frozenset(), frozenset())


def test_a_keyoff_with_a_free_column_holds_on_its_own_row():
    writes, _s, _i, _r = _plan(_pat((NOTE, 1, 0, 0), _rest(), _rest(),
                                    (KEYOFF, 0, 0, 0)))
    assert writes == {(3, 1)}


def test_the_hold_names_the_params_row_of_the_instrument_the_event_plays():
    """SABOTAGE TARGET: use a fixed pointer and instrument 4's events hold on
    instrument 1's program."""
    writes, _s, _i, _r = _plan(_pat((NOTE, 4, 0, 0), _rest(), (KEYOFF, 0, 0, 0)))
    assert writes == {(2, 4)}
    # a tie that names its instrument holds on THAT instrument's program
    writes, _s, _i, _r = _plan(_pat((NOTE, 1, 0, 0), _rest(), _tie(ins=4)))
    assert writes == {(1, 4)}


def test_a_tie_holds_on_the_nearest_free_row_before_it():
    """SABOTAGE TARGET: write on the tie's own row and its TONEPORTA is
    replaced."""
    pat = _pat((NOTE, 1, 0, 0), _rest(), _rest(), _tie(ins=1))
    writes, skips, _i, _r = _plan(pat)
    assert writes == {(2, 1)} and not skips


def test_a_tie_steps_over_taken_columns_up_to_back_rows():
    """The tie into a new instrument has its SR on the row before it and the
    AD after (`_tied_instrument_envelopes`); the hold goes before both."""
    pat = _pat((NOTE, 1, 0, 0), _rest(), _rest(), _rest(0x06, 0x9D, ins=1),
               _tie(ins=1))
    assert _plan(pat)[0] == {(2, 1)}
    # one row further than `back` and it is declined, counted
    far = _pat((NOTE, 1, 0, 0), _rest(), _rest(), _rest(0x0F, 3), _rest(0x0F, 4),
               _rest(0x06, 0x9D), _tie(ins=1))
    writes, skips, _i, _r = _plan(far)
    assert writes == frozenset() and skips == {(6, "no free row")}
    # and a deeper `back` finds the free row
    assert _plan(far, back=4)[0] == {(2, 1)}


def test_a_hold_never_crosses_the_previous_event():
    """A row belongs to the event it follows: stepping back over a note would
    put this event's hold on that one's."""
    pat = _pat((NOTE, 1, 0, 0), _rest(0x06, 0x9D), _tie(ins=1))
    writes, skips, _i, _r = _plan(pat)
    assert writes == frozenset() and skips == {(2, "no free row")}


def test_row_zero_is_allowed_when_its_column_is_free():
    writes, _s, _i, _r = _plan(_pat((KEYOFF, 0, 0, 0), _rest()))
    assert writes == {(0, 1)}
    writes, skips, _i, _r = _plan(_pat((KEYOFF, 0, 0x0F, 3), _rest()))
    assert writes == frozenset() and skips == {(0, "no free row")}


def test_a_running_command_blocks_the_row():
    """A one-shot leaves the channel's running command running
    (gplay.c:404-421), so a row entered under a portamento is not free."""
    pat = _pat((NOTE, 1, 1, 0x10), _rest(0x06, 0x9D), (KEYOFF, 0, 0, 0))
    writes, skips, _i, _r = _plan(pat)
    assert writes == frozenset() and skips == {(2, "no free row")}
    # entered running, the same: the state carried in from the last pattern
    writes, skips, _i, running = _plan(_pat((KEYOFF, 0, 0, 0)), running=3)
    assert writes == frozenset() and skips == {(0, "no free row")}
    assert running == 0


def test_a_new_note_resets_the_running_command():
    """`cptr->command = 0` on every new note (gplay.c:346): a one-shot on the
    note row leaves nothing running."""
    pat = _pat((NOTE, 1, 0x0F, 4), _rest(), (KEYOFF, 0, 0, 0))
    assert _plan(pat, running=3)[0] == {(2, 1)}


def test_an_instrument_with_no_filter_program_is_not_held():
    pat = _pat((NOTE, 2, 0, 0), _rest(), (KEYOFF, 0, 0, 0))
    assert _plan(pat, ptr_of={1: 1, 2: 0})[0] == frozenset()


def test_the_instrument_is_carried_across_rests_and_patterns():
    pat = _pat(_rest(), (KEYOFF, 0, 0, 0))
    assert _plan(pat, instr=4)[0] == {(1, 4)}
    assert _plan(_pat(_rest(ins=4), (KEYOFF, 0, 0, 0)), instr=1)[0] == {(1, 4)}
    assert _plan(pat, instr=4)[2] == 4


# --- the pass ----------------------------------------------------------------

def _tracks():
    return [[0, 0xFF, 0], [1, 0xFF, 0], [2, 0xFF, 0]]


def test_only_the_driving_voice_is_edited_and_a_shared_pattern_is_cloned():
    """SABOTAGE TARGET: skip the clone and voice 1's visit of the shared
    pattern holds too -- on frames the original's voice 0 does not fetch."""
    shared = _pat((NOTE, 1, 0, 0), _rest(), (KEYOFF, 0, 0, 0))
    patterns = [shared, list(shared), _pat(_rest(), (KEYOFF, 0, 0, 0))]
    tracks = [[0, 0xFF, 0], [0, 0xFF, 0], [2, 0xFF, 0]]
    out_p, out_t, written = free_running_fetch_holds(tracks, patterns,
                                                     {1: 1, 4: 4}, 0)
    assert written == 1 and len(out_p) == 4
    assert out_t[0][0] == 3 and out_t[1][0] == 0 and out_t[2][0] == 2
    assert out_p[0] == shared                      # the original is untouched
    assert out_p[3][4 * 2 + 2:4 * 2 + 4] == [CMD_SETFILTERPTR, 1]
    assert out_p[2] == patterns[2]                 # voice 2's own pattern too
    assert tracks == [[0, 0xFF, 0], [0, 0xFF, 0], [2, 0xFF, 0]]   # inputs kept


def test_a_pattern_only_the_driving_voice_plays_is_edited_in_place():
    patterns = [_pat((NOTE, 1, 0, 0), _rest(), (KEYOFF, 0, 0, 0)),
                _pat(_rest()), _pat(_rest())]
    out_p, out_t, written = free_running_fetch_holds(_tracks(), patterns,
                                                     {1: 1}, 0)
    assert written == 1 and len(out_p) == 3 and out_t == _tracks()
    assert out_p[0][4 * 2 + 2:4 * 2 + 4] == [CMD_SETFILTERPTR, 1]


def test_visits_that_disagree_keep_only_what_they_share():
    """The restart laps the orderlist: a pattern entered holding instrument 1
    the first time and instrument 4 the second wants a different pointer for
    its KEYOFF each time, so neither is written, and it is counted."""
    patterns = [_pat(_rest(), (KEYOFF, 0, 0, 0)), _pat((NOTE, 4, 0, 0), _rest())]
    tracks = [[0, 1, 0xFF, 0], [1, 0xFF, 0], [1, 0xFF, 0]]
    lines = []
    out_p, out_t, written = free_running_fetch_holds(tracks, patterns,
                                                     {1: 1, 4: 4}, 0,
                                                     log=lines.append)
    assert written == 0 and out_p == patterns and out_t == tracks
    assert lines and "disagree" in lines[0], lines


def test_a_full_pattern_table_leaves_the_position_alone_and_counts_it():
    shared = _pat((NOTE, 1, 0, 0), _rest(), (KEYOFF, 0, 0, 0))
    patterns = [shared] + [_pat(_rest())] * 0xCF
    tracks = [[0, 0xFF, 0], [0, 0xFF, 0], [1, 0xFF, 0]]
    lines = []
    out_p, out_t, written = free_running_fetch_holds(tracks, patterns,
                                                     {1: 1}, 0, log=lines.append)
    assert len(out_p) == 0xD0 and out_t == tracks and written == 0
    assert "DROPPED" in lines[0], lines


# --- the player fact the pass rests on ----------------------------------------

def test_a_pointer_set_to_the_params_row_costs_exactly_one_step():
    """player.s `mt_setfilt`: the params row adds no step, so a
    CMD_SETFILTERPTR to it mid-sweep is a one-call hold, then `+2` as before.
    SABOTAGE TARGET: point the command at the modulation row (2) and the hold
    vanishes."""
    block = _free_running_block(0x10, 0xF4, 2, 1)
    assert block[0][0] == FILT_SET_PARAMS | 0x10
    free = gt_filter_calls(block, 1, 40, cutoff=0x08)
    resumed = gt_filter_calls(block, 1, 20, cutoff=0x08)
    held = gt_filter_calls(block, 1, 20, cutoff=resumed[-1])
    assert held[0] == resumed[-1]                       # the held call
    assert held[1:3] == [(resumed[-1] + 2) & 0xFF, (resumed[-1] + 4) & 0xFF]
    # one step behind the uninterrupted sweep, for ever after
    assert (free[39] - held[19]) & 0xFF == 2
    not_held = gt_filter_calls(block, 2, 20, cutoff=resumed[-1])
    assert not_held[0] == (resumed[-1] + 2) & 0xFF


# --- detection: which files the pass reaches -----------------------------------

@needs_corpus
def test_the_fetch_skip_is_read_in_sigma_seven_alone():
    """After_8, Rikky and Mr_Meaner are free-running too (and DIGI held); none
    carries the fetch tail, so none is reached."""
    got = {}
    for stem in ("Sigma_Seven", "After_8", "Rikky", "Mr_Meaner"):
        got[stem] = free_running_fetch_hold_voice(
            load_sid(str(CORPUS / f"{stem}.sid")))
    assert got == {"Sigma_Seven": 0, "After_8": None, "Rikky": None,
                   "Mr_Meaner": None}


@needs_corpus
def test_the_reading_can_fail():
    """Probe lie #1: send the fetch tail's JMP into the filter block -- a
    player that WOULD step on the fetch frame -- and nothing is read."""
    sid = load_sid(str(CORPUS / "Sigma_Seven.sid"))
    data = bytearray(sid.data)
    tail = "C9 FF D0 08 A9 00 9D ?? ?? FE ?? ?? 4C ?? ??"
    k = search_file(bytes(data), tail) + 12
    block = search_file(bytes(data), "AD ?? ?? 29 20 F0 ?? BD ?? ?? "
                        "18 79 ?? ?? 9D ?? ?? 8D 16 D4 B9 ?? ?? 8D 17 D4")
    at = sid.to_address(block)
    assert data[k + 1] | data[k + 2] << 8 == 0x8347
    data[k + 1], data[k + 2] = at & 0xFF, at >> 8
    assert free_running_fetch_hold_voice(
        dataclasses.replace(sid, data=bytes(data))) is None


# --- the conversion -----------------------------------------------------------

def _converted(stem="Sigma_Seven", **extra):
    doc = json.loads((REPO / "presets.json").read_text("utf-8"))
    opts = dict(fidelity._preset_opts(doc, f"{stem}.sid"), **extra)
    lines = []
    blob = convert(str(CORPUS / f"{stem}.sid"), log=lines.append, **opts)
    return blob, parse_sng(blob), lines


def _orderlist_patterns(track):
    out, i = [], 0
    while i < len(track) and track[i] != 0xFF:
        if track[i] < 0xD0:
            out.append(track[i])
        i += 1
    return out


@needs_corpus
def test_sigma_seven_holds_on_voice_zero_events_only():
    """SABOTAGE TARGET: gate `free_running_fetch_holds` off in build.py and no
    row carries the command; drop the voice filter and voices 1 and 2 do."""
    _blob, song, lines = _converted()
    on = {p for p, pat in enumerate(song.patterns)
          for r in range(len(pat) // 4)
          if pat[4 * r + 2] == CMD_SETFILTERPTR}
    assert on, "no CMD_SETFILTERPTR row at all"
    voice = [set(_orderlist_patterns(t)) for t in song.tracks[:3]]
    assert on & voice[0] and not on & (voice[1] | voice[2])
    logged = [m for m in lines if m.startswith("Filter fetch hold")]
    assert len(logged) == 1 and "no free row" not in logged[0], logged


@needs_corpus
def test_every_hold_names_a_params_row_and_sits_on_a_free_event_neighbourhood():
    _blob, song, _lines = _converted()
    params = {k + 1 for k, (left, _r) in enumerate(song.tables["FTBL"])
              if FILT_SET_PARAMS <= left < 0xFF}
    held = [(p, r, pat[4 * r + 3]) for p, pat in enumerate(song.patterns)
            for r in range(len(pat) // 4) if pat[4 * r + 2] == CMD_SETFILTERPTR]
    assert held and all(ptr in params for _p, _r, ptr in held), held
    for p, r, _ptr in held:
        note = song.patterns[p][4 * r]
        assert note in (REST, KEYOFF), (p, r, note)     # never over a note


@needs_corpus
@pytest.mark.parametrize("stem", ["After_8", "Rikky", "Mr_Meaner", "Saboteur_II"])
def test_no_other_filter_file_gets_a_hold(stem):
    _blob, song, lines = _converted(stem)
    assert not any(m.startswith("Filter fetch hold") for m in lines)


@needs_corpus
@needs_siddump
@needs_gt2reloc
def test_sigma_seven_cutoff_follows_the_original_over_the_whole_tune(tmp_path):
    """The check the start-value patch failed (whole tune 18.2 -> 25.4): mean
    circular |ours - original| over frames 10-3490 at the 5-frame startup
    lag, measured 0.17 (base 18.06). SABOTAGE TARGET: gate the pass off and
    this reads 5.5 with the start value alone, 25 without the holds."""
    blob, _song, _lines = _converted()
    sng, _patched = fidelity.legalise_restarts(blob)
    packed = fidelity.pack_sid(sng, tmp_path, fidelity.GT2RELOC, 1)
    assert packed is not None
    orig = fidelity.run_siddump(CORPUS / "Sigma_Seven.sid", 180, 1)
    ours = fidelity.run_siddump(packed, 180, 1)
    n, lag = 3500, 5
    co = [x >> 8 for x in fidelity.register_timeline(orig.filter.cutoff_events, n + 30)]
    cu = [x >> 8 for x in fidelity.register_timeline(ours.filter.cutoff_events, n + 30)]
    diff = [abs((cu[i + lag] - co[i] + 128) % 256 - 128) for i in range(10, n - 10)]
    assert sum(diff[:300]) / 300 < 1.0
    assert sum(diff) / len(diff) < 1.0, sum(diff) / len(diff)
    # the holds themselves: the original's 128 after power-on, ours within a few
    def holds(t, hi):
        fr = {a for a, _ in t.filter.cutoff_events}
        first = min(fr)
        return [f for f in range(first, hi) if f not in fr]
    h_o = [f for f in holds(orig, 3563) if f > 3]
    h_u = [f for f in holds(ours, 3568) if f > 12]
    assert abs(len(h_o) - len(h_u)) <= 3, (len(h_o), len(h_u))
