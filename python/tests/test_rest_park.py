"""`--rest-wave-silence` under a running wavetable: the parked twin
(`goatwriter/rest_park.py`) and the tempo row-0 move that keeps a pattern-
opening rest's park (`patterns._move_rest_wave_off_row0`).

The mechanism is gplay.c's, so the first tests transcribe the two pieces of
it that decide the outcome (`CMD_SETWAVE`/`CMD_SETWAVEPTR` at gplay.c:433-445
and WAVEEXEC at gplay.c:520-535, :709-712) and show the failure the pass
exists for before showing it gone. The rest read the converter's own output.
"""
import json
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

# goatwriter first: importing h2g.patterns first trips a pre-existing circular
# import (patterns -> goatwriter -> counter_fall -> patterns).
from h2g.goatwriter import rest_park as RP  # noqa: E402
from h2g import patterns as P  # noqa: E402

CORPUS = Path(r"C:\Users\mit\claude\c64server\SIDM2\SID\Hubbard_Rob")
PRESETS = Path(__file__).resolve().parents[2] / "presets.json"

KEYOFF, NO_NOTE = P.GT_KEYOFF, P.GT_NO_NOTE
SETWAVE, SETWAVEPTR = P.CMD_SETWAVE, P.CMD_SETWAVEPTR
PARK = RP.REST_PARK_PROGRAM


# --- gplay.c, transcribed ----------------------------------------------------

class Voice:
    """The three fields the rest turns on: `cptr->wave`, `ptr[WTBL]`, and the
    delay counter. `table` is 1-based like the player's."""

    def __init__(self, table, ptr=0, wave=0x41):
        self.table, self.ptr, self.wave, self.wavetime = table, ptr, wave, 0

    def command(self, cmd, data):                         # gplay.c:433-445
        if cmd == SETWAVE:
            self.wave = data
        elif cmd == SETWAVEPTR:
            assert not data or self.table[data - 1][0] != 0xFF, \
                "gplay.c:442 stops the song on a jump target"
            self.ptr, self.wavetime = data, 0

    def waveexec(self):                                   # gplay.c:520-535, 709
        if not self.ptr:
            return
        wave, _note = self.table[self.ptr - 1]
        if wave > 0x0F:
            if wave < 0xE0:
                self.wave = wave                          # :525
            if 0xE0 <= wave <= 0xEF:
                self.wave = wave & 0xF                    # :527
        elif self.wavetime != wave:
            self.wavetime += 1
            return
        self.wavetime = 0
        self.ptr += 1
        if self.table[self.ptr - 1][0] == 0xFF:           # :709
            self.ptr = self.table[self.ptr - 1][1]


def _loop_table():
    """`41 00 / 41 0C / FF 1` -- a looping arpeggio -- then the park program."""
    arp = [(0x41, 0x00), (0x41, 0x0C), (0xFF, 0x01)]
    return arp + list(PARK), 1, len(arp) + 1


def test_a_running_table_overwrites_setwave_and_the_pointer_does_not():
    table, arp, park = _loop_table()
    v = Voice(table, ptr=arp)
    v.waveexec()
    v.command(SETWAVE, 0x08)
    v.waveexec()
    assert v.wave == 0x41, "the failure this pass exists for"
    w = Voice(table, ptr=arp)
    w.waveexec()
    w.command(SETWAVEPTR, park)
    for _ in range(20):
        w.waveexec()
        assert w.wave == 0x08
    assert w.ptr == 0, "the program stops: nothing is left to rewrite $08"


def test_the_park_program_is_a_plain_step_then_a_stop():
    assert PARK == ((0xE8, 0x80), (0xFF, 0x00))
    assert PARK[0][0] & 0xF == P.REST_SILENT_WAVE
    assert 0xE0 <= PARK[0][0] <= 0xEF, "gplay.c:527's 'silent' range"


# --- the pass ----------------------------------------------------------------

def _pat(*rows):
    return [b for row in rows for b in row] + [0xFF, 0, 0, 0]


REST = (KEYOFF, 0, SETWAVE, 0x08)
HOLD = (NO_NOTE, 0, 0, 0x08)


def _song():
    """Two instruments, 1 with a program (wavetable row 1), 2 without."""
    entries = [(0x41, 0x00), (0xFF, 0x01)]
    starts = {1: 1, 2: 0}
    pats = [_pat((0x60, 1, 0, 0), REST, HOLD),          # instrument 1 then rest
            _pat((0x60, 2, 0, 0), REST, HOLD),          # instrument 2 then rest
            _pat(REST, HOLD)]                           # holds whatever it entered
    tracks = [[0, 1, 2, 0xFF, 0], [0xFF, 0], [0xFF, 0]]
    return pats, tracks, entries, starts


def test_inert_without_a_setwave_row():
    pats, tracks, entries, starts = _song()
    for pat in pats:
        for r in range(0, len(pat) - 3, 4):
            if pat[r + 2] == SETWAVE:
                pat[r + 2] = pat[r + 3] = 0
    new_pats, new_entries = RP.rest_park_plan(pats, tracks, entries, starts)
    assert new_pats is pats and new_entries is entries


def test_rewrites_a_rest_on_an_instrument_with_a_program_and_appends_two_rows():
    pats, tracks, entries, starts = _song()
    new_pats, new_entries = RP.rest_park_plan(pats, tracks, entries, starts)
    assert new_entries == entries + list(PARK)
    park = len(entries) + 1
    assert new_pats[0][4 + 2:4 + 4] == [SETWAVEPTR, park]


def test_leaves_a_rest_on_an_instrument_with_no_program():
    pats, tracks, entries, starts = _song()
    new_pats, _ = RP.rest_park_plan(pats, tracks, entries, starts)
    assert new_pats[1][4 + 2:4 + 4] == [SETWAVE, 0x08]


def test_a_rest_whose_instrument_is_not_named_is_parked_by_pointer():
    """Pattern 2 is entered holding instrument 2 (no program) after pattern 1
    on this orderlist, so its rest stays a SETWAVE; entered from nowhere, it
    is unknown and takes the pointer (which is correct for both)."""
    pats, tracks, entries, starts = _song()
    new_pats, _ = RP.rest_park_plan(pats, tracks, entries, starts)
    assert new_pats[2][2:4] == [SETWAVE, 0x08]          # held instrument 2
    tracks2 = [[0, 0xFF, 0], [0xFF, 0], [0xFF, 0]]      # pattern 2 unreached
    new2, _ = RP.rest_park_plan(pats, tracks2, entries, starts)
    assert new2[2][2:4] == [SETWAVEPTR, len(entries) + 1]


def test_the_input_patterns_are_not_mutated():
    pats, tracks, entries, starts = _song()
    before = [list(p) for p in pats]
    RP.rest_park_plan(pats, tracks, entries, starts)
    assert pats == before


def test_declines_without_room_in_the_wavetable():
    pats, tracks, _entries, starts = _song()
    full = [(0x41, 0x00)] * (RP.GT_MAX_TABLELEN - 1) + [(0xFF, 0x01)]
    new_pats, new_entries = RP.rest_park_plan(pats, tracks, full, starts)
    assert new_pats is pats and new_entries is full


def test_the_pointer_fits_the_pattern_it_replaces_byte_for_byte():
    """Same row, same two bytes: the pass cannot move a pattern's packed size."""
    pats, tracks, entries, starts = _song()
    new_pats, _ = RP.rest_park_plan(pats, tracks, entries, starts)
    assert [len(p) for p in new_pats] == [len(p) for p in pats]


# --- the tempo keeps row 0; the park moves to hold row 1 -----------------------

def test_the_park_moves_to_hold_row_one_when_the_tempo_takes_row_zero():
    p = list(REST) + list(HOLD) + [NO_NOTE, 0, 0, 0x08]
    P._move_rest_wave_off_row0(p)
    assert p[2:4] == [SETWAVE, 0x08]          # row 0 untouched: the caller writes the tempo
    assert p[6:8] == [SETWAVE, 0x08]


def test_the_move_is_inert_without_a_hold_row_or_off_the_spelling():
    one_row = list(REST) + [0xFF, 0, 0, 0]
    before = list(one_row)
    P._move_rest_wave_off_row0(one_row)       # no hold row to take it
    assert one_row == before
    busy = list(REST) + [NO_NOTE, 0, 3, 0] + [NO_NOTE, 0, 0, 0]
    before = list(busy)
    P._move_rest_wave_off_row0(busy)          # row 1 has a command
    assert busy == before
    note = [0x60, 1, SETWAVE, 0x08] + list(HOLD)
    before = list(note)
    P._move_rest_wave_off_row0(note)          # row 0 is a note
    assert note == before
    envelope = [KEYOFF, 0, P.CMD_SETSR, 0] + list(HOLD)
    before = list(envelope)
    P._move_rest_wave_off_row0(envelope)      # the SETSR spelling is the other move's
    assert envelope == before


def test_apply_tempo_keeps_the_park_on_a_pattern_that_opens_on_a_rest():
    patterns = [list(REST) + list(HOLD) + [NO_NOTE, 0, 0, 0x08]]
    tracks = [[0, 0xFF, 0], [0, 0xFF, 0], [0, 0xFF, 0]]
    assert P.apply_tempo(patterns, tracks, 3) == 1
    assert patterns[0][2:4] == [P.CMD_SETTEMPO, 3]
    assert patterns[0][6:8] == [SETWAVE, 0x08]


def test_apply_tempos_keeps_the_park_too():
    patterns = [list(REST) + list(HOLD) + [NO_NOTE, 0, 0, 0x08]]
    tracks = [[0, 0xFF, 0], [0, 0xFF, 0], [0, 0xFF, 0]]
    assert P.apply_tempos(patterns, tracks, [3]) == 1
    assert patterns[0][2:4] == [P.CMD_SETTEMPO, 3]
    assert patterns[0][6:8] == [SETWAVE, 0x08]


# --- the converter's own output ------------------------------------------------

def _convert(name, **extra):
    from fidelity import _preset_opts
    from h2g.convert import convert
    doc = json.loads(PRESETS.read_text(encoding="utf-8"))
    opts = _preset_opts(doc, name)
    opts.update(extra)
    return convert(str(CORPUS / name), log=lambda *a, **k: None, **opts)


def _need_corpus():
    if not CORPUS.exists() or not PRESETS.exists():
        pytest.skip("corpus or presets not present")


def _park_rows(blob):
    import songview as S
    song = S.parse_sng(blob)
    w = song.tables["WTBL"]
    at = [i + 1 for i in range(len(w) - 1)
          if w[i] == PARK[0] and w[i + 1] == PARK[1]]
    return song, at


def test_nineteen_every_rest_is_parked_by_pointer_under_the_option():
    """Nineteen: 42 KEYOFF rows, one of them the pattern-0 rest whose row 0 is
    the tempo's -- its park is on hold row 1 -- and the other 41 carry the
    pointer. None is left as a bare SETWAVE, which a running table would
    overwrite."""
    _need_corpus()
    song, at = _park_rows(_convert("Nineteen.sid", rest_wave_silence=True))
    assert len(at) == 1
    park = at[0]
    kinds = {"pointer": 0, "tempo+hold": 0, "other": []}
    for pn, pat in enumerate(song.patterns):
        for r in range(0, len(pat) - 3, 4):
            if pat[r] == 0xFF:
                break
            if pat[r] != KEYOFF:
                continue
            if pat[r + 2:r + 4] == [SETWAVEPTR, park]:
                kinds["pointer"] += 1
            elif (pat[r + 2] == P.CMD_SETTEMPO
                  and pat[r + 6:r + 8] == [SETWAVEPTR, park]):
                kinds["tempo+hold"] += 1
            else:
                kinds["other"].append((pn, r // 4))
    assert kinds["other"] == []
    assert kinds["pointer"] == 41 and kinds["tempo+hold"] == 1


def test_the_option_off_appends_nothing_and_writes_no_pointer():
    _need_corpus()
    song, at = _park_rows(_convert("Nineteen.sid"))
    assert at == []
    assert all(not (pat[r + 2] == SETWAVEPTR and pat[r] == KEYOFF)
               for pat in song.patterns for r in range(0, len(pat) - 3, 4)
               if pat[r] != 0xFF)


def test_the_cost_is_two_wavetable_rows_and_four_bytes(monkeypatch):
    """Shockway_Rider, option on, with and without the pass: the pass adds the
    park program's two rows (4 bytes) and rewrites 37 rest rows in place."""
    _need_corpus()
    with monkeypatch.context() as m:
        m.setattr(RP, "rest_park_plan", lambda pats, tracks, entries, starts,
                  log=None: (pats, entries))
        without = _convert("Shockway_Rider.sid", rest_wave_silence=True)
    with_pass = _convert("Shockway_Rider.sid", rest_wave_silence=True)
    s_without, at_without = _park_rows(without)
    s_with, at_with = _park_rows(with_pass)
    assert at_without == [] and len(at_with) == 1
    assert (len(s_with.tables["WTBL"])
            == len(s_without.tables["WTBL"]) + 2)
    assert len(with_pass) == len(without) + 4
    pointed = sum(1 for pat in s_with.patterns
                  for r in range(0, len(pat) - 3, 4)
                  if pat[r] != 0xFF and pat[r + 2] == SETWAVEPTR
                  and pat[r + 3] == at_with[0])
    assert pointed == 37


def test_a_file_outside_the_testbit_family_is_untouched_by_the_option():
    _need_corpus()
    assert (_convert("Commando.sid", rest_wave_silence=True)
            == _convert("Commando.sid"))
