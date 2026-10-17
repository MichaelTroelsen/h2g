"""`--rest-program-stop`: a bit-6 rest stops the byte-code wave program.

IK+ `$09F8` (record 2) is a twelve-opcode program and the original sounds six
frames of it. The trace: the event after the note is a REST (status byte
`$E549,X` = `$43`, where the note read `$81`), and the interpreter's prologue
is `LDA status / AND #$40 / BNE skip` (`$E329-$E32E`), so a rest never reaches
the program; the rest handler (`$E135`) has parked `$08` in the stored
waveform and nothing rewrites it. ours kept stepping the wavetable through
the rest. See `detect.wave_program_rest_bypass` and `goatwriter/rest_park.py`.

The pass tests use a synthetic song; the converter tests read the corpus and
skip without it.
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


def _pat(*rows):
    return [b for row in rows for b in row] + [0xFF, 0, 0, 0]


REST = (KEYOFF, 0, SETWAVE, 0x08)
HOLD = (NO_NOTE, 0, 0, 0)


def _song():
    """Instrument 1 has a wave PROGRAM, 2 an arpeggio table, 3 no table."""
    entries = [(0x41, 0x00), (0xFF, 0x01), (0x41, 0x00), (0xFF, 0x03)]
    starts = {1: 1, 2: 3, 3: 0}
    pats = [_pat((0x60, 1, 0, 0), REST, HOLD),      # program, then rest
            _pat((0x60, 2, 0, 0), REST, HOLD),      # arpeggio, then rest
            _pat((0x60, 3, 0, 0), REST, HOLD),      # no table, then rest
            _pat(REST, HOLD)]                       # entered from nowhere
    tracks = [[0, 1, 2, 0xFF, 0], [0xFF, 0], [0xFF, 0]]
    return pats, tracks, entries, starts


ONLY = frozenset({1})


# --- the pass ----------------------------------------------------------------

def test_a_rest_on_a_program_instrument_points_the_table_at_the_park():
    pats, tracks, entries, starts = _song()
    new, new_entries = RP.rest_park_plan(pats, tracks, entries, starts,
                                         only=ONLY)
    assert new_entries == entries + list(PARK)
    assert new[0][4 + 2:4 + 4] == [SETWAVEPTR, len(entries) + 1]


def test_a_lagged_program_instrument_parks_through_the_one_call_delay():
    """Test-bit firstwave: the program runs a call behind the row grid, the
    original's rest comes on attack + 12 and a tick-0 park is attack + 11
    (Bangkok_Knights `$0AA9`). The pointer names a delay row that falls
    through into the plain park: [delay, E8 80, FF 00]."""
    pats, tracks, entries, starts = _song()
    new, new_entries = RP.rest_park_plan(pats, tracks, entries, starts,
                                         only=ONLY, lagged=ONLY)
    assert new_entries == entries + [RP.REST_PARK_DELAY] + list(PARK)
    assert new[0][4 + 2:4 + 4] == [SETWAVEPTR, len(entries) + 1]
    # the delay row is a 1-call hold that writes nothing (gplay.c:697-704)
    assert RP.REST_PARK_DELAY[0] <= 0x0F and RP.REST_PARK_DELAY[0] == 0


def test_an_unlagged_program_instrument_keeps_the_plain_two_row_park():
    pats, tracks, entries, starts = _song()
    new, new_entries = RP.rest_park_plan(pats, tracks, entries, starts,
                                         only=ONLY, lagged=frozenset({2}))
    assert new_entries == entries + list(PARK)
    assert new[0][4 + 2:4 + 4] == [SETWAVEPTR, len(entries) + 1]


def test_both_kinds_share_one_park_program():
    """Instruments 1 (lagged) and 4 (not) both stop: one three-row program,
    the lagged rest at the delay row, the other one row in."""
    entries = [(0x41, 0x00), (0xFF, 0x01), (0x41, 0x00), (0xFF, 0x03)]
    starts = {1: 1, 4: 3}
    pats = [_pat((0x60, 1, 0, 0), REST, HOLD),
            _pat((0x60, 4, 0, 0), REST, HOLD)]
    tracks = [[0, 0xFF, 0], [1, 0xFF, 0], [0xFF, 0]]
    new, new_entries = RP.rest_park_plan(pats, tracks, entries, starts,
                                         only=frozenset({1, 4}),
                                         lagged=frozenset({1}))
    n = len(entries)
    assert new_entries == entries + [RP.REST_PARK_DELAY] + list(PARK)
    assert new[0][4 + 2:4 + 4] == [SETWAVEPTR, n + 1]
    assert new[1][4 + 2:4 + 4] == [SETWAVEPTR, n + 2]


def test_lagged_instruments_reads_the_testbit_firstwave():
    def rec(fw):
        return bytes(8) + bytes([fw]) + bytes(16)
    out = bytearray(1)
    for fw in (0x09, 0x10, 0x00, 0x48, 0xFF, 0xFE):
        out += rec(fw)
    # $09 and $48 (named test bit) lag; a gate-clear byte, no byte and the
    # two gate-command bytes do not
    assert RP.lagged_instruments(out, 0, 6) == frozenset({1, 4})


def test_the_delay_moves_the_park_one_call_in_the_player():
    """gplay.c's loop, transcribed in `Voice`: from SETWAVEPTR at tick 0 the
    plain park writes $08 on the SAME call, the delayed one on the next."""
    table = list(PARK)
    plain = Voice(table, 1)
    plain.waveexec()
    assert plain.wave == 0x08 and plain.ptr == 0
    late_table = [RP.REST_PARK_DELAY] + list(PARK)
    late = Voice(late_table, 1)
    late.waveexec()
    assert late.wave == 0x41 and late.ptr == 2
    late.waveexec()
    assert late.wave == 0x08 and late.ptr == 0


def test_a_rest_on_any_other_instrument_is_left_a_plain_keyoff():
    """The arpeggio instrument keeps stepping across a rest in the player, so
    parking its table is the loss `--rest-wave-silence` shows; the no-table
    one needs no stop. Neither keeps the CMD_SETWAVE $08 that placeholder."""
    pats, tracks, entries, starts = _song()
    new, _ = RP.rest_park_plan(pats, tracks, entries, starts, only=ONLY)
    assert new[1][4 + 2:4 + 4] == [0, 0]            # arpeggio
    assert new[2][4 + 2:4 + 4] == [0, 0]            # no table
    assert new[1][4:4 + 2] == [KEYOFF, 0]           # the key-off itself stays


def test_a_cleared_rest_gives_the_envelopes_ad_back_its_row():
    """Beside `--rest-envelope-silence` the pattern stage schedules
    `SETSR` / `SETWAVE` / `SETAD` on three rows. A rest this option does not
    stop must come out as the envelope option alone has it: SETSR, SETAD."""
    pats, tracks, entries, starts = _song()
    env = _pat((0x60, 2, 0, 0),
               (KEYOFF, 0, P.CMD_SETSR, 0),
               (NO_NOTE, 0, SETWAVE, 0x08),
               (NO_NOTE, 0, P.CMD_SETAD, 0),
               (NO_NOTE, 0, 0, 0))
    new, _ = RP.rest_park_plan([pats[0], env], [[0, 1, 0xFF, 0], [0xFF, 0],
                                                  [0xFF, 0]],
                               entries, starts, only=ONLY)
    rows = [tuple(new[1][i:i + 4]) for i in range(0, 20, 4)]
    assert rows[1] == (KEYOFF, 0, P.CMD_SETSR, 0)
    assert rows[2] == (NO_NOTE, 0, P.CMD_SETAD, 0)
    assert rows[3] == (NO_NOTE, 0, 0, 0)


def test_a_rest_whose_instrument_is_not_known_is_not_stopped():
    pats, tracks, entries, starts = _song()
    tracks = [[0, 0xFF, 0], [0xFF, 0], [0xFF, 0]]   # pattern 3 never entered
    new, _ = RP.rest_park_plan(pats, tracks, entries, starts, only=ONLY)
    assert new[3][2:4] == [0, 0]


def test_a_rest_entering_on_a_mix_is_not_stopped():
    """Pattern 3 follows pattern 0 on one orderlist and pattern 1 on the
    other: the live instrument is 1 or 2, and a park is wrong for 2."""
    pats, tracks, entries, starts = _song()
    tracks = [[0, 3, 0xFF, 0], [1, 3, 0xFF, 0], [0xFF, 0]]
    new, _ = RP.rest_park_plan(pats, tracks, entries, starts, only=ONLY)
    assert new[3][2:4] == [0, 0]


def test_no_program_instrument_appends_nothing_and_clears_the_rows():
    pats, tracks, entries, starts = _song()
    new, new_entries = RP.rest_park_plan(pats, tracks, entries, starts,
                                         only=frozenset())
    assert new_entries == entries
    assert all(p[r + 2] == 0 and p[r + 3] == 0
               for p in new for r in range(0, len(p) - 3, 4)
               if p[r] == KEYOFF)


def test_declines_without_room_in_the_wavetable_but_still_clears():
    pats, tracks, _entries, starts = _song()
    full = [(0x41, 0x00)] * (RP.GT_MAX_TABLELEN - 1) + [(0xFF, 0x01)]
    new, new_entries = RP.rest_park_plan(pats, tracks, full, starts, only=ONLY)
    assert new_entries == full
    assert new[0][4 + 2:4 + 4] == [0, 0]


def test_the_park_is_appended_only_when_a_rest_uses_it():
    pats, tracks, entries, starts = _song()
    only_arp = [pats[1], pats[2]]
    _, new_entries = RP.rest_park_plan(only_arp, [[0, 1, 0xFF, 0], [0xFF, 0],
                                                  [0xFF, 0]],
                                       entries, starts, only=ONLY)
    assert new_entries == entries


def test_the_input_patterns_are_not_mutated():
    pats, tracks, entries, starts = _song()
    before = [list(p) for p in pats]
    RP.rest_park_plan(pats, tracks, entries, starts, only=ONLY)
    assert pats == before


def test_without_only_the_pass_is_exactly_what_it_was():
    """`only` unset is `--rest-wave-silence`: the arpeggio rest keeps its
    SETWAVE and the program rest is pointed (test_rest_park pins the rest)."""
    pats, tracks, entries, starts = _song()
    new, _ = RP.rest_park_plan(pats, tracks, entries, starts)
    assert new[0][4 + 2] == SETWAVEPTR
    assert new[1][4 + 2:4 + 4] == [SETWAVEPTR, len(entries) + 1]
    assert new[2][4 + 2:4 + 4] == [SETWAVE, 0x08]


def test_program_instruments_reads_the_effect_byte_out_of_the_name():
    def rec(name):
        return bytes(9) + name.encode().ljust(16, b"\x00")
    out = bytearray(1)
    for name in ("02:00-C4-00", "04:00-00-08", "0F:23-00-0C", "07:00-00-A0"):
        out += rec(name)
    assert RP.program_instruments(out, 0, 4, 0x08) == frozenset({2, 3})
    assert RP.program_instruments(out, 0, 4, 0x08, arp_bit=True) == \
        frozenset({2})
    assert RP.program_instruments(out, 0, 4, 0x80) == frozenset({4})
    assert RP.program_instruments(out, 0, 4, 0) == frozenset()


# --- gplay.c, for the one claim the pass makes ---------------------------------

class Voice:
    """`cptr->wave`, `ptr[WTBL]` and the delay counter (gplay.c:433-445,
    :520-535, :709) -- the three things a stop turns on."""

    def __init__(self, table, ptr):
        self.table, self.ptr, self.wave, self.wavetime = table, ptr, 0x41, 0

    def command(self, cmd, data):
        if cmd == SETWAVEPTR:
            assert not data or self.table[data - 1][0] != 0xFF
            self.ptr, self.wavetime = data, 0

    def waveexec(self):
        if not self.ptr:
            return
        wave, _note = self.table[self.ptr - 1]
        if wave > 0x0F:
            if wave < 0xE0:
                self.wave = wave
            if 0xE0 <= wave <= 0xEF:
                self.wave = wave & 0xF
        elif self.wavetime != wave:
            self.wavetime += 1
            return
        self.wavetime = 0
        self.ptr += 1
        if self.table[self.ptr - 1][0] == 0xFF:
            self.ptr = self.table[self.ptr - 1][1]


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


def _rows(song):
    for pn, pat in enumerate(song.patterns):
        for r in range(0, len(pat) - 3, 4):
            if pat[r] == 0xFF:
                break
            yield pn, r // 4, pat[r:r + 4]


def test_ik_plus_carries_the_branch_and_the_nine_without_it_do_not():
    _need_corpus()
    from h2g.detect import detect, wave_program_rest_bypass
    from h2g.sidfile import load_sid
    got = {}
    for p in sorted(CORPUS.glob("*.sid")):
        try:
            sid = load_sid(str(p))
            det = detect(sid, lambda *a, **k: None)
        except Exception:                                  # noqa: BLE001
            continue
        if det.wave_program >= 0 and det.wave_program_gate:
            got[p.name] = wave_program_rest_bypass(sid, det)
    assert got["IK_plus.sid"] is True
    assert got["Mega_Apocalypse.sid"] is True           # the zero-page spelling
    assert got["ACE_II.sid"] is True                    # the sign-bit gate
    for name in ("After_8.sid", "Kings_of_the_Beach_intro.sid",
                 "Mr_Meaner.sid", "Off_the_Cuff.sid",
                 "One_on_One_Jordan_vs_Bird.sid",
                 "Powerplay_Hockey_USA_vs_USSR.sid", "Pygmies_Revenge.sid",
                 "Rikky.sid", "Rock_Tells_the_Tale.sid"):
        assert got[name] is False, name
    # The six `$1003` files joined the population at v0.5.566 (their `$86`
    # jump dialect); none carries the branch, so the 20 did not move.
    for name in ("Go_Go_Dash.sid", "Lakers_vs_Celtics.sid", "Lion_Heart.sid",
                 "Pacific_Coast.sid", "Radio_ACE.sid", "Sun_Never_Shines.sid"):
        assert got[name] is False, name
    assert sum(got.values()) == 20 and len(got) == 35   # historical: v0.5.566


def test_ik_plus_every_rest_is_stopped_or_a_plain_keyoff():
    """No CMD_SETWAVE $08 survives; the program instruments' rests carry the
    pointer; the park is two rows."""
    _need_corpus()
    import songview as S
    base = S.parse_sng(_convert("IK_plus.sid"))
    song = S.parse_sng(_convert("IK_plus.sid", rest_program_stop=True))
    w = song.tables["WTBL"]
    at = [i + 1 for i in range(len(w) - 1)
          if w[i] == PARK[0] and w[i + 1] == PARK[1]]
    # IK+ carries a test-bit firstwave ($09): the park is three rows, the
    # one-call delay in front of it, and each rest points at the delay.
    assert len(at) == 1 and len(w) == len(base.tables["WTBL"]) + 3
    assert w[at[0] - 2] == tuple(RP.REST_PARK_DELAY)
    pointers = [row for _, _, row in _rows(song)
                if row[2] == SETWAVEPTR and row[3] == at[0] - 1]
    assert pointers and all(r[0] == KEYOFF for r in pointers)
    assert not [row for _, _, row in _rows(song)
                if row[2] == SETWAVE and row[3] == 0x08]
    # ...and each pointer sits on a rest of the program instruments only.
    prog = {i.number for i in song.instruments
            if i.effect_byte and i.effect_byte & 0x08}
    assert prog and 3 in prog


def test_ik_plus_the_stop_ends_the_program_the_original_ends():
    """The real table, gplay.c's loop: three program frames, then the rest.
    Without the pointer the table keeps writing waveforms through the rest
    (the `$09F8` surplus); with it the voice reads `$08` and the pointer is 0."""
    _need_corpus()
    import songview as S
    song = S.parse_sng(_convert("IK_plus.sid", rest_program_stop=True))
    w = song.tables["WTBL"]
    park = [i for i in range(len(w) - 1)
            if w[i] == PARK[0] and w[i + 1] == PARK[1]][0]   # the delay row
    prog = [i for i in song.instruments
            if i.effect_byte and i.effect_byte & 0x08 and i.wave_ptr]
    assert prog
    running = changing = 0
    for ins in prog:
        free = Voice(w, ins.wave_ptr)
        stopped = Voice(w, ins.wave_ptr)
        for _ in range(3):
            free.waveexec()
            stopped.waveexec()
        if not free.ptr:
            continue                    # a program shorter than the note
        running += 1
        stopped.command(SETWAVEPTR, park)
        seen = set()
        before = stopped.wave
        for n in range(24):
            free.waveexec()
            stopped.waveexec()
            seen.add(free.wave)
            if n == 0:
                # the delay row holds one call: nothing is written yet
                assert stopped.wave == before and stopped.ptr == park + 1
            else:
                assert stopped.wave == 0x08 and stopped.ptr == 0
        changing += len(seen) > 1
    # $09F8 and $08D8 outlast three frames and keep rewriting the waveform
    assert running >= 2 and changing >= 2, (running, changing)


def test_inert_where_the_player_has_no_such_branch():
    _need_corpus()
    for name in ("Rikky.sid", "Pygmies_Revenge.sid"):
        assert (_convert(name, rest_program_stop=True)
                == _convert(name)), name


def test_the_gate_is_the_players_branch_not_the_option_alone(monkeypatch):
    """No corpus file lacks the branch AND would move (the nine without it are
    not testbit-family players with a program rest), so the gate is shown by
    taking the branch away from IK+: the option then writes nothing."""
    _need_corpus()
    import h2g.convert as C
    monkeypatch.setattr(C, "wave_program_rest_bypass", lambda sid, det: False)
    assert (_convert("IK_plus.sid", rest_program_stop=True)
            == _convert("IK_plus.sid"))


def test_inert_without_the_wave_program():
    _need_corpus()
    assert (_convert("IK_plus.sid", rest_program_stop=True,
                     wave_program=False)
            == _convert("IK_plus.sid", wave_program=False))


def test_the_broader_option_subsumes_it():
    _need_corpus()
    assert (_convert("IK_plus.sid", rest_program_stop=True,
                     rest_wave_silence=True)
            == _convert("IK_plus.sid", rest_wave_silence=True))


def test_the_option_off_is_the_shipped_conversion():
    _need_corpus()
    assert (_convert("IK_plus.sid", rest_program_stop=False)
            == _convert("IK_plus.sid"))


def test_thundercats_has_no_program_rest_so_nothing_moves(monkeypatch):
    """Thundercats ships `--rest-envelope-silence`, whose SETSR / SETAD rows
    the pattern stage rearranges to make room for a SETWAVE. None of its
    rests follows a program instrument, so every one is cleared AND the AD
    goes back to its shipped row: the conversion is the shipped bytes. (Before
    the AD was given back this moved Thundercats' `adsr` 0.974 -> 0.932.)

    Nothing moves because its wavetable is full (255 rows, "no room in the
    wavetable for the parked program"). With the blocks of its dead records
    gone (`goatwriter.dead_blocks`) there is room and 12 of its 15 rests do
    stop their program under the option, which the shipped presets leave off;
    the table this test is about is the full one."""
    _need_corpus()
    import h2g.goatwriter.dead_blocks as DB
    monkeypatch.setattr(DB, "plan_dead_blocks", lambda *a, **k: None)
    assert (_convert("Thundercats.sid", rest_program_stop=True)
            == _convert("Thundercats.sid"))
