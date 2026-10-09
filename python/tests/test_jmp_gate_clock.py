"""The JMP-form outer gate's clock (Chain_Reaction `$0859`), and the startup
phase that puts our onsets on it (`goatwriter.call_phase.jmp_gate`,
`jmp_gate_ticks`).

Opened by skip-gate-song-call-phase: the entry-gate model (a gate that is the
play routine's first instruction and returns) moved Chain_Reaction's late third
of notes to early and took Kings_of_the_Beach_intro from 95/154 exact to 31/154
(60 s). The reason is that the JMP form is another clock, read off Chain_Reaction
`$0859-$0883`:

    DEC cell / BPL +8 / LDA #O / STA cell / JMP past   ; underflow: no ctr step
    DEC ctr / BPL +6 / LDA reload / STA ctr
    LDA cell / BEQ nofetch / LDA ctr / CMP reload / BNE nofetch

* the new-song call (flag `$40`, `BIT flag / BMI / BVC gate`) takes the reset
  path past the gate, so frame 0 steps neither counter;
* a fetch is due where the counter reads its reload, and **runs unless the cell
  reads 0 -- then the next call, the underflow one, whose counter is untouched,
  runs it**.

Measured at 60 s, one dump row per frame, through the packed file, before ->
after (every onset of every voice with an original to compare against):
Chain_Reaction 156/232, 176/265, 110/165 -> all; Kings_of_the_Beach_intro
95/154, 70/112, 188/312 -> all; and 13 more files, in
C:/t/jmp-form-outer-gate-clock/ab.
"""
import collections
import json
import pathlib
import sys

import pytest

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[1]))

import fidelity                                              # noqa: E402
from corpus import CORPUS, needs_corpus                      # noqa: E402
from h2g.convert import _detect_tables, convert              # noqa: E402
from h2g.goatwriter import call_phase, tempo                 # noqa: E402
from h2g.instrument_drop import onset_rows                   # noqa: E402
from h2g.sidfile import load_sid                             # noqa: E402

REPO_ROOT = pathlib.Path(__file__).resolve().parents[2]

needs_siddump = pytest.mark.skipif(
    not pathlib.Path(fidelity.SIDDUMP).exists(),
    reason="no siddump on this machine (tools/siddump-rt, see its README)")
needs_gt2reloc = pytest.mark.skipif(
    not pathlib.Path(fidelity.GT2RELOC).exists(),
    reason="no gt2reloc on this machine")

# Every corpus file the JMP-form reading reaches, and the startup row each
# gets (instrument 63's AD) when EVERY row is scored. The six entry-gate files
# are test_startup_call_phase's.
JMP_ALL_ROWS = {
    "ACE_II.sid": 17, "Chain_Reaction.sid": 17, "Deep_Strike.sid": 16,
    "Delta.sid": 11, "Food_Feud.sid": 17, "Kings_of_the_Beach_intro.sid": 28,
    "Mr_Meaner.sid": 28, "Off_the_Cuff.sid": 29, "Rock_Tells_the_Tale.sid": 35,
    "Saboteur_II.sid": 16, "Thanatos.sid": 22, "Thundercats.sid": 17,
    "W_A_R.sid": 22, "W_A_R_Preview.sid": 21, "Zoolook.sid": 17,
}


def _presets() -> dict:
    return json.loads((REPO_ROOT / "presets.json").read_text(encoding="utf-8"))


def _read(name: str):
    sid = load_sid(str(CORPUS / name))
    return _detect_tables(sid, lambda *_: None)


# --- the clock, by hand ------------------------------------------------------

def test_the_fetch_frames_are_the_players_dec_bpl_and_beq():
    # Chain_Reaction: cell 0 / reload 3, speed counter 0 / reload 1.
    #   f1 cell 0 -> underflow (3), counter untouched (0)        no fetch
    #   f2 cell 2, counter 0 -> reload 1                         FETCH
    #   f3 cell 1, counter 0
    #   f4 cell 0, counter reloads to 1: due, but the cell reads 0 -> held
    #   f5 cell underflows (3), counter still 1                  FETCH (late)
    assert call_phase.jmp_gate_ticks(0, 3, 0, 1, 6) == [2, 5, 7, 10, 13, 15]


def test_a_held_fetch_is_run_on_the_next_call_never_twice_or_lost():
    for reload, creload in [(3, 1), (3, 2), (5, 1), (4, 3), (9, 2)]:
        period = (reload + 1) * (creload + 1)
        got = call_phase.jmp_gate_ticks(2, reload, 1, creload, 10 * reload)
        # R fetches in every period of (R + 1)(C + 1) calls.
        in_ten = [f for f in got if f <= 10 * period + 1]
        assert abs(len(in_ten) - 10 * reload) <= 1, (reload, creload)
        assert len(set(got)) == len(got)
        assert all(b > a for a, b in zip(got, got[1:]))


def test_the_entry_model_started_on_frame_zero_is_not_this_clock():
    # The entry gate's frames, with the cell's byte as the first call's, are a
    # different sequence: that is why the first attempt moved the notes the
    # wrong way.
    entry = call_phase.gate_frames(0, 3, 12)
    ticks = call_phase.jmp_gate_ticks(0, 3, 0, 1, 12)
    assert entry != ticks and ticks[0] == 2 and entry[0] == 1


# --- which players it is for -------------------------------------------------

@needs_corpus
def test_the_reading_is_for_the_jmp_gate_behind_a_new_song_test():
    have = {}
    for path in sorted(CORPUS.glob("*.sid")):
        sid = load_sid(str(path))
        if tempo.outer_gate_skip(sid, 0):
            have[path.name] = call_phase.jmp_gate(sid)
    # The multispeed files the reading reaches: all the JMP movers, plus those
    # whose rows are not exact or whose rows it cannot read.
    for name in JMP_ALL_ROWS:
        assert have[name], name
    for name in ("Flash_Gordon.sid", "Lightforce.sid", "Shockway_Rider.sid",
                 "Star_Paws.sid", "Dragons_Lair_Part_II.sid",
                 "Knucklebusters.sid", "Kings_of_the_Beach_ingame.sid"):
        assert have[name], name
    # Not the entry family (a gate that IS the play entry has no such test),
    # not a player with no outer gate, and not Delta_Mix, whose init JSRs the
    # routine: its first PLAY call passes the gate.
    for name in ("Game_Killer.sid", "International_Karate.sid", "Kentilla.sid",
                 "Proteus.sid", "Thrust.sid", "Warhawk.sid",
                 "Las_Vegas_Video_Poker.sid", "Mozart.sid", "Ninja.sid",
                 "Bump_Set_Spike.sid", "Formula_1_Simulator.sid",
                 "Delta_Mix-E-Load_loader.sid", "Samantha_Fox_Strip_Poker.sid",
                 "Spellbound.sid"):
        assert not have[name], name
    assert not call_phase.jmp_gate(load_sid(str(CORPUS / "Commando.sid")))


@needs_corpus
def test_the_new_song_call_must_really_skip_the_gate():
    """Chain_Reaction's init stores `$40` to the flag the play routine's `BIT`
    reads (`LDA #$40 / STA $0D23` at `$14A3`). A song whose init sets nothing
    there has no reset call to bypass the gate, and the clock is not read."""
    import dataclasses
    sid = load_sid(str(CORPUS / "Chain_Reaction.sid"))
    assert call_phase.jmp_gate(sid)
    store = bytes([0xA9, 0x40, 0x8D, 0x23, 0x0D])
    at = sid.data.index(store)
    assert sid.data.count(store) == 1
    patched = sid.data[:at + 1] + b"\x00" + sid.data[at + 2:]
    assert not call_phase.jmp_gate(dataclasses.replace(sid, data=patched))


@needs_corpus
def test_the_corpus_movers_of_the_jmp_family_and_their_startup_rows():
    got = {}
    for path in sorted(CORPUS.glob("*.sid")):
        sid = load_sid(str(path))
        if not tempo.outer_gate_skip(sid, 0) or not call_phase.jmp_gate(sid):
            continue
        sid, det = _detect_tables(sid, lambda *_: None)
        speeds = tempo.find_song_speeds(sid, det)
        if speeds is None:
            continue
        m = tempo.file_multiplier(sid, speeds, True)
        tempos = [tempo.tempo_command_value(sid, s, speeds, m, True)
                  for s in range(max(sid.subtunes, 1))]
        phase = call_phase.startup_phase(sid, det, m, tempos)
        if phase is not None:
            assert phase.mismatched == 0 < phase.default_mismatched, (
                path.name, phase)
            got[path.name] = phase.tempo
    assert got == JMP_ALL_ROWS


# What convert() writes: scored over the rows that carry a note, so the three
# files whose default startup row is already exact on every note are left
# alone, and W_A_R takes the nearest of its two exact leads.
CONVERTED = {k: v for k, v in JMP_ALL_ROWS.items()
             if k not in ("Delta.sid", "Thanatos.sid", "W_A_R_Preview.sid")}
CONVERTED["W_A_R.sid"] = 23


@needs_corpus
def test_convert_writes_the_startup_row_scored_over_the_note_rows():
    import songview
    doc = _presets()
    for name in sorted(JMP_ALL_ROWS):
        song = songview.parse_sng(convert(
            str(CORPUS / name), log=lambda m: None,
            **fidelity._preset_opts(doc, name)))
        last = song.instruments[-1]
        got = last.ad if last.name == "Startup tempo" else None
        assert got == CONVERTED.get(name), name


@needs_corpus
def test_a_default_that_is_exact_on_every_note_row_is_kept():
    """Thanatos: 40 of its 80 rows are off the original's frames at the default
    startup row, and every one of its 19 note rows is on them."""
    sid, det = _read("Thanatos.sid")
    speeds = tempo.find_song_speeds(sid, det)
    m = tempo.file_multiplier(sid, speeds, True)
    tempos = [tempo.tempo_command_value(sid, s, speeds, m, True)
              for s in range(max(sid.subtunes, 1))]
    assert call_phase.startup_phase(sid, det, m, tempos) is not None
    doc = _presets()
    sng = convert(str(CORPUS / "Thanatos.sid"), log=lambda x: None,
                  **fidelity._preset_opts(doc, "Thanatos.sid"))
    rows = onset_rows(sng, 0, call_phase.startup_horizon(m, 4))
    assert rows is not None and len(rows) == 19
    assert call_phase.startup_phase(sid, det, m, tempos,
                                    lambda s, h: rows) is None


@needs_corpus
def test_onset_rows_walks_the_orderlists_of_the_converted_song():
    doc = _presets()
    sng = convert(str(CORPUS / "Chain_Reaction.sid"), log=lambda x: None,
                  **fidelity._preset_opts(doc, "Chain_Reaction.sid"))
    rows = onset_rows(sng, 0, 48)
    assert rows is not None and len(rows) == 12 and max(rows) < 48
    assert onset_rows(sng, 0, 6) <= rows and all(r < 6 for r in onset_rows(sng, 0, 6))
    assert onset_rows(sng, 5, 48) is None            # no such subtune


def test_onset_rows_follows_a_restart_and_stops_at_the_end_row():
    """One subtune, three voices each `pattern 0, RST 0`, pattern 0 = a note, a
    rest and the end row: the end row takes no time, so the loop is two rows
    long and the notes fall on 0, 2, 4, 6."""
    from h2g.goatwriter import HEADER_LEN
    blob = bytearray(b"GTS2" + bytes(HEADER_LEN - 4))
    blob.append(1)                                      # subtunes
    for _ in range(3):
        blob += bytes([3, 0x00, 0xFF, 0x00, 0x00])      # orderlist, length 4
    blob.append(0)                                      # no instruments
    blob += bytes(3)                                    # empty WTBL/PTBL/FTBL
    blob.append(1)                                      # one pattern
    blob.append(3)
    blob += bytes([0x60, 1, 0, 0, 0xBD, 0, 0, 0, 0xFF, 0, 0, 0])
    assert onset_rows(bytes(blob), 0, 7) == frozenset({0, 2, 4, 6})
    assert onset_rows(bytes(blob), 0, 3) == frozenset({0, 2})


@needs_corpus
def test_the_entry_model_picks_the_wrong_lead_for_chain_reaction():
    """Scored against `gate_frames` (the entry model) lead 16 is exact and 17
    is not; against the JMP clock it is the other way round. 16 is what the
    first attempt applied: it moved the late third of the notes to early
    (C:/t/skip-gate-song-call-phase/exp/sweep/Chain_Reaction.txt)."""
    sid, det = _read("Chain_Reaction.sid")
    speeds = tempo.find_song_speeds(sid, det)
    m = tempo.file_multiplier(sid, speeds, True)
    tempos = [tempo.tempo_command_value(sid, s, speeds, m, True)
              for s in range(max(sid.subtunes, 1))]
    leads = (18, 17, 16)
    entry = [call_phase.onset_mismatches(a, tempos[0], m, 0, 2, 0, 3, 48)
             for a in leads]
    jmp = [call_phase.onset_mismatches(a, tempos[0], m, 0, 2, 0, 3, 48, 1)
           for a in leads]
    assert [bool(x) for x in entry] == [True, True, False]
    assert [bool(x) for x in jmp] == [True, False, True]


# --- against the original, measured ------------------------------------------

def _fetch_frames(name, seconds):
    sid, det = _read(name)
    speeds = tempo.find_song_speeds(sid, det)
    s0 = tempo.pack_subtune(speeds, sid.start_song)
    from h2g.goatwriter import arpeggio
    n = seconds * 50 + 20
    return call_phase.jmp_gate_ticks(
        arpeggio.nibble_gate_byte(sid), tempo.outer_gate_skip(sid, s0),
        arpeggio.fixed_arp_first_fetch(sid, det), speeds.frames_for(s0) - 1,
        n)


@needs_corpus
@needs_siddump
@pytest.mark.parametrize("name", ["Chain_Reaction.sid",
                                  "Kings_of_the_Beach_intro.sid",
                                  "Saboteur_II.sid"])
def test_every_attack_of_the_original_is_on_a_fetch_the_clock_names(name):
    orig = fidelity.run_siddump(CORPUS / name, 20, 0, calls=1)
    fetches = {f for f in _fetch_frames(name, 20) if f < 20 * 50}
    attacks = [f for v in orig for f in v.attack_frames if f < 20 * 50]
    assert len(attacks) > 100
    assert [f for f in attacks if f not in fetches] == []
    # The held fetch: a frame on which the counter has just reloaded and the
    # cell reads 0 is due and fires nothing; the call after it does.
    held = _due_frames(name, 20) - fetches
    assert held and not (held & set(attacks))
    assert any(h + 1 in attacks for h in held)


def _due_frames(name, seconds):
    """The same player loop with the `BEQ` taken out: every frame a fetch is
    due, run or held."""
    sid, det = _read(name)
    speeds = tempo.find_song_speeds(sid, det)
    s0 = tempo.pack_subtune(speeds, sid.start_song)
    from h2g.goatwriter import arpeggio
    cell, ctr = arpeggio.nibble_gate_byte(sid), arpeggio.fixed_arp_first_fetch(sid, det)
    reload, creload = tempo.outer_gate_skip(sid, s0), speeds.frames_for(s0) - 1
    out = set()
    for frame in range(1, seconds * 50):
        cell -= 1
        if cell < 0:
            cell = reload
        else:
            ctr -= 1
            if ctr < 0:
                ctr = creload
        if ctr == creload:
            out.add(frame)
    return out


@needs_corpus
@needs_siddump
@needs_gt2reloc
@pytest.mark.parametrize("name", ["Chain_Reaction.sid",
                                  "Kings_of_the_Beach_intro.sid"])
def test_onsets_land_on_the_originals_frames_through_the_packed_file(
        tmp_path, name):
    doc = _presets()
    m = doc["songs"][name]["multiplier"]
    sng = convert(str(CORPUS / name), log=lambda x: None,
                  **fidelity._preset_opts(doc, name))
    packed = fidelity.pack_sid(sng, tmp_path, fidelity.GT2RELOC, m)
    assert packed is not None and packed.exists()
    orig = fidelity.run_siddump(CORPUS / name, 60, 0, calls=1)
    ours = fidelity.run_siddump(packed, 60, 0, calls=m)
    lag, _raw = fidelity.startup_lag(orig, ours)
    compared = 0
    for a, b in zip(orig, ours):
        n = min(len(a.attack_frames), len(b.attack_frames))
        assert [x - lag for x in b.attack_frames[:n]] == a.attack_frames[:n]
        compared += n
    assert compared > 300
