"""The packed song starts on the call phase that puts its onsets in the
original's frames (`goatwriter.call_phase`, instrument 63's AD).

Game_Killer (`-S9`, outer gate byte `$0C8C` = 4, reload 9) attacked one frame
early on 2 of every 3 notes on every voice: 135/367, 126/362, 150/450 exact at
60 s, 391/985, 385/1129, 450/1350 at 180 s, on the staged tree at 6e467ff. Our
row is the gate's exact average, 20 calls at `-S9`, an even grid; the
original's is uneven (frames 4, 14, 24, ... skipped), and an even grid of
10/9 frames sits in the original's frames at one phase in nine. gt2reloc's
startup row decided which: `6 * multiplier` calls (greloc.c:1143).

The phase is read, not fitted: the packed player's first call only resets
(player.s `mt_initsongnum`), its second is an empty tick 0, row 0's tick 0
follows the startup row, and a note's onset shows one call after its tick 0
(the test-bit firstwave is no key-on to siddump, siddump.c:434-437); the
original's rows start on passing call `first + frames * j`
(`fixed_arp_first_fetch`), and the gate's `DEC` / `BPL` on its byte says which
frame each passing call is. At 180 s through the packed file, every voice of
Game_Killer, International_Karate, Kentilla v0/v1, Proteus v1/v2, Thrust
v0/v1 and Warhawk v1/v2 went to every onset exact; the voices left are off by
whole note sequences, not by a frame (C:/t/skip-gate-song-call-phase/exp/ab).

**What it costs, measured, so nobody reads it as free**: Warhawk's in-note
pitch steps sit on the tick-0 grid (calls `8k - 1` after the onset call at
`-m1`), one call ahead of the onset's, and with `m = O` the phase serves one
grid only -- its `tie_agreement` .7578 -> .6085 and `wave` .9807 -> .9673 at
180 s, Proteus `wave` .9775 -> .965, Game_Killer `sound_run_agreement` .8182
-> .4545 (modal note length one frame short on 4 more instruments). The other
columns that moved went up: Game_Killer `gate` .7064 -> .7741 and
`tie_agreement` .2771 -> .4501, International_Karate `wave` .9379 -> .9753
and melody/sequence/pitch_jaccard to 1.0, Kentilla `tie_agreement` .2915 ->
.6402, Thrust `gate` .7693 -> .8342.

The JMP-form gate inside the play routine (Chain_Reaction `$0859`) is a
different clock -- it skips only the speed counter's `DEC` and the new-song
call bypasses it -- and the same model makes Kings_of_the_Beach_intro worse
(95/154 exact -> 31/154 at 60 s), so `entry_gate` declines it.
"""
import collections
import json
import pathlib
import sys

import pytest

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[1]))

import fidelity                                              # noqa: E402
import songview                                              # noqa: E402
from corpus import CORPUS, needs_corpus                      # noqa: E402
from h2g.convert import _detect_tables, convert              # noqa: E402
from h2g.goatwriter import arpeggio, call_phase, tempo       # noqa: E402
from h2g.instrument_drop import add_startup_tempo           # noqa: E402
from h2g.sidfile import HLEN, SidFile, load_sid              # noqa: E402

REPO_ROOT = pathlib.Path(__file__).resolve().parents[2]

needs_siddump = pytest.mark.skipif(
    not pathlib.Path(fidelity.SIDDUMP).exists(),
    reason="no siddump on this machine (tools/siddump-rt, see its README)")
needs_gt2reloc = pytest.mark.skipif(
    not pathlib.Path(fidelity.GT2RELOC).exists(),
    reason="no gt2reloc on this machine")

# The files the reading reaches, and the startup row each gets. Measured at
# 180 s (module docstring): every one of them loses every +-1 onset offset.
MOVERS = {"Game_Killer.sid": 49, "International_Karate.sid": 56,
          "Kentilla.sid": 57, "Proteus.sid": 40, "Thrust.sid": 16,
          "Warhawk.sid": 41}


def _presets() -> dict:
    return json.loads((REPO_ROOT / "presets.json").read_text(encoding="utf-8"))


def _read(name: str):
    sid = load_sid(str(CORPUS / name))
    return _detect_tables(sid, lambda *_: None)


def _tempos(sid, det, m):
    speeds = tempo.find_song_speeds(sid, det)
    return [tempo.tempo_command_value(sid, s, speeds, m, True)
            for s in range(max(sid.subtunes, 1))]


# --- the gate, as the player runs it ----------------------------------------

def test_the_gate_frames_are_the_players_dec_bpl():
    # Game_Killer's byte 4, reload 9: frames 0-3 pass, 4 is skipped, then
    # nine pass and the tenth is skipped.
    assert call_phase.gate_frames(4, 9, 14) == [0, 1, 2, 3, 5, 6, 7, 8, 9,
                                                10, 11, 12, 13, 15]
    # A byte of 0 skips the very first call.
    assert call_phase.gate_frames(0, 3, 4) == [1, 2, 3, 5]


def test_where_several_leads_are_exact_the_smallest_move_is_taken():
    # -S8 over a reload of 4: two calls a working frame's worth of phase are
    # exact (rows of 10 calls, 1 frame x 5/4). No corpus file in the family
    # has this shape; the choice must still be the lead nearest the default.
    scores = {a: call_phase.onset_mismatches(a, 10, 8, 0, 1, 2, 4, 160)
              for a in range(48, 40, -1)}
    assert sorted(a for a, s in scores.items() if s == 0) == [42, 43]
    got = call_phase.best_startup(10, 8, 0, 1, 2, 4)
    assert (got.tempo, got.default, got.mismatched) == (43, 48, 0)


def _gate_at_play(jump_lands_on: int) -> SidFile:
    """`DEC $1090 / BPL +8 / LDA #$05 / STA $1090 / JMP $1040` at the play
    address $1000, and `jump_lands_on` at $1040."""
    image = bytearray(0x100)
    image[0x00:0x0D] = bytes([0xCE, 0x90, 0x10, 0x10, 0x08, 0xA9, 0x05, 0x8D,
                              0x90, 0x10, 0x4C, 0x40, 0x10])
    image[0x40] = jump_lands_on
    return SidFile(path="synthetic", data=bytes(HLEN - 1) + bytes(image),
                   name="", author="", released="", load_addr=0x1000,
                   subtunes=1, play_addr=0x1000)


def test_a_jmp_gate_at_the_entry_must_land_on_a_return():
    # Kentilla's spelling: the underflow call jumps to an RTS, so it does
    # nothing else. Anywhere else, the rest of the frame runs (the speed
    # counter's DEC skipped, Chain_Reaction's shape), which is another clock.
    assert call_phase.entry_gate(_gate_at_play(0x60))
    assert not call_phase.entry_gate(_gate_at_play(0xEA))


# --- Game_Killer, by hand ----------------------------------------------------

@needs_corpus
def test_game_killers_startup_row_is_read_off_the_player():
    sid, det = _read("Game_Killer.sid")
    assert call_phase.entry_gate(sid)
    assert arpeggio.nibble_gate_byte(sid) == 4
    assert tempo.outer_gate_skip(sid, 0) == 9
    assert arpeggio.fixed_arp_first_fetch(sid, det) == 1
    assert tempo.find_song_speeds(sid, det).frames_for(0) == 2
    m = tempo.file_multiplier(sid, tempo.find_song_speeds(sid, det), True)
    assert m == 9 and _tempos(sid, det, m)[0] == 20
    got = call_phase.startup_phase(sid, det, m, _tempos(sid, det, m))
    assert got is not None
    assert (got.tempo, got.default, got.mismatched) == (49, 54, 0)
    assert got.default_mismatched > 0
    # The same arithmetic spelled out: our row j shows on call
    # 1 (reset) + 49 (startup row) + 1 (onset after tick 0) + 20 j; the
    # original's on passing call 1 + 2 j, frames 4, 14, 24, ... skipped.
    passing = [f for f in range(2000) if f < 4 or (f - 4) % 10]
    lags = {(1 + 49 + 1 + 20 * j) // 9 - passing[1 + 2 * j] for j in range(80)}
    assert lags == {4}
    # And gt2reloc's own startup row (54) puts 4 rows in 9 a frame early
    # (the notes, which sit on every third row, measured 2 in 3).
    lags = collections.Counter((1 + 54 + 1 + 20 * j) // 9 - passing[1 + 2 * j]
                               for j in range(81))
    assert lags == {5: 45, 4: 36}


# --- which players the reading is for ---------------------------------------

@needs_corpus
@pytest.mark.parametrize("name,want", [
    ("Game_Killer.sid", True), ("International_Karate.sid", True),
    ("Kentilla.sid", True),            # JMP spelling, landing on an RTS
    ("Proteus.sid", True), ("Thrust.sid", True), ("Warhawk.sid", True),
    ("Las_Vegas_Video_Poker.sid", True),   # the PAL spelling
    ("Chain_Reaction.sid", False),     # JMP form inside the routine
    ("Bump_Set_Spike.sid", False),     # an NTSC gate sits above the entry
    ("Formula_1_Simulator.sid", False),    # RTS gate, not at the entry
    ("Commando.sid", False),           # no outer gate
])
def test_the_reading_is_for_a_gate_at_the_play_entry_that_returns(name, want):
    sid, _ = _read(name)
    assert call_phase.entry_gate(sid) is want


@needs_corpus
def test_the_corpus_movers_and_their_startup_rows():
    """Every corpus file with an outer gate, under the converter's own
    multiplier and tempos: exactly the six get a startup row. Las_Vegas's
    default phase is already exact; the rest are not the entry family, run
    at -S1, or lack a read the model needs."""
    got = {}
    for path in sorted(CORPUS.glob("*.sid")):
        sid = load_sid(str(path))
        if not tempo.outer_gate_skip(sid, 0):
            continue
        try:
            sid, det = _detect_tables(sid, lambda *_: None)
        except Exception:
            continue
        speeds = tempo.find_song_speeds(sid, det)
        if speeds is None:
            continue
        m = tempo.file_multiplier(sid, speeds, True)
        phase = call_phase.startup_phase(sid, det, m, _tempos(sid, det, m))
        if phase is not None:
            assert phase.mismatched == 0, (path.name, phase)
            got[path.name] = phase.tempo
    assert got == MOVERS


# --- the record in the file --------------------------------------------------

@needs_corpus
def test_the_converted_song_carries_the_startup_record():
    name = "Game_Killer.sid"
    opts = fidelity._preset_opts(_presets(), name)
    assert opts.get("skip_gate")
    song = songview.parse_sng(convert(str(CORPUS / name), log=lambda m: None,
                                      **opts))
    assert len(song.instruments) == 63
    last = song.instruments[-1]
    assert (last.ad, last.wave_ptr, last.name) == (49, 0, "Startup tempo")
    named = {p[4 * r + 1] for p in song.patterns for r in range(len(p) // 4)}
    real = max(named)
    assert real < 63
    pad = song.instruments[real:62]
    assert pad and all((i.ad, i.sr, i.wave_ptr, i.pulse_ptr, i.gatetimer,
                        i.firstwave, i.name) == (0, 0, 0, 0, 0, 0, "")
                       for i in pad)
    # Without --skip-gate the rows are not the gate's grid; and where a
    # firstwave writes the waveform, an onset is tick 0 itself, not the call
    # after (`call_phase.ONSET_CALL`): no record in either.
    for other in (dict(opts, skip_gate=False), dict(opts, no_test_restart=True),
                  dict(opts, real_firstwave_instruments=(1,))):
        off = songview.parse_sng(convert(str(CORPUS / name),
                                         log=lambda m: None, **other))
        assert len(off.instruments) < 63, other


def _block(blob: bytes):
    pos = songview.HEADER_LEN
    n = blob[pos]
    pos += 1
    for _ in range(n * 3):
        pos += blob[pos] + 2
    return pos


@needs_corpus
def test_the_record_declines_where_it_would_change_what_plays():
    name = "Game_Killer.sid"
    opts = fidelity._preset_opts(_presets(), name)
    plain = bytearray(convert(str(CORPUS / name), log=lambda m: None,
                              **dict(opts, skip_gate=False)))
    added = add_startup_tempo(bytes(plain), 49)
    assert added[_block(added)] == 63
    # Already 63 instruments.
    assert add_startup_tempo(added, 49) == added
    # A startup row too short for a gatetimer: row 0 would never be fetched.
    at = _block(bytes(plain))
    gt = max(plain[at + 1 + k * 25 + 7] & 0x3F for k in range(plain[at]))
    assert gt >= 1
    assert add_startup_tempo(bytes(plain), gt) == bytes(plain)
    assert add_startup_tempo(bytes(plain), gt + 1) != bytes(plain)
    # A dangling instrument reference would land on a padding record.
    song = songview.parse_sng(bytes(plain))
    k = next(i for i, p in enumerate(song.patterns) if p and p[1])
    dangling = bytearray(plain)
    first_row = len(plain) - sum(1 + len(p) for p in song.patterns) + 1
    first_row += sum(1 + len(p) for p in song.patterns[:k])
    assert dangling[first_row + 1] == song.patterns[k][1]
    dangling[first_row + 1] = plain[at] + 1
    assert add_startup_tempo(bytes(dangling), 49) == bytes(dangling)


# --- both sides, measured ----------------------------------------------------

@needs_corpus
@needs_siddump
@needs_gt2reloc
def test_game_killer_onsets_land_on_the_originals_frames(tmp_path):
    name = "Game_Killer.sid"
    doc = _presets()
    m = doc["songs"][name]["multiplier"]
    sng = convert(str(CORPUS / name), log=lambda x: None,
                  **fidelity._preset_opts(doc, name))
    packed = fidelity.pack_sid(sng, tmp_path, fidelity.GT2RELOC, m)
    assert packed is not None and packed.exists()
    # Our side, one dump row per CALL: every attack is the call after a
    # tick 0 of the 20-call grid that starts 1 + 49 calls in.
    calls = fidelity.run_siddump(packed, 20 * m, 0, calls=1)
    for v in calls:
        assert v.attack_frames
        assert {(c - (1 + 49 + 1)) % 20 for c in v.attack_frames} == {0}
    # The original's, one row per frame: every attack on a passing call
    # 1 + 2 j of the gate model.
    orig = fidelity.run_siddump(CORPUS / name, 60, 0, calls=1)
    w = {f: k for k, f in enumerate(call_phase.gate_frames(4, 9, 3100))}
    for v in orig:
        assert {(w[f] - 1) % 2 for f in v.attack_frames} == {0}
    # And together, frame against frame: every onset on every voice.
    ours = fidelity.run_siddump(packed, 60, 0, calls=m)
    lag, raw = fidelity.startup_lag(orig, ours)
    assert lag == raw == 4
    for a, b in zip(orig, ours):
        assert len(a.attack_frames) == len(b.attack_frames) > 300
        assert [x - lag for x in b.attack_frames] == a.attack_frames
