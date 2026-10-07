"""A tie in the classic players with no legato marker restarts the instrument.

`convert(tie_restart=True)`, `goatwriter.classic_tie_restart_family`: the
classic players without `note_flag` have no way to skip their instrument
start. Commando, read at 6e467ff: the fetch reloads the gate mask (`$50BD
LDA #$FF / STA $5501`), reads the status byte, and runs `$5133-$5151` --
waveform AND mask to $D404, pulse, AD, SR -- on every event that is not a
rest; status bit 5 is tested only at the note's END (`$517F AND #$20`). So a
tie's landing re-runs the whole start where `CMD_TONEPORTA 00` skips it
(gplay.c:353-398). The tie is respelled as a plain note on a legato clone
(`legato_tie_clones`) where that restart is HEARD (`_restart_heard`), and
kept where a restarted block would leave the arpeggio counter's phase
(`_phase_locked_ties`).

Measured at 6e467ff + this change, under presets, `fidelity.measure` -t 180
(C:/t/motr-family-tie-reruns-note-start/ab.py, ab4/): 23 files move;
Kentilla voice-3 attacks 355 -> 379 (original 379), melody .952 -> .982;
Thrust voice-3 attacks 346 -> 386 (original 411), melody .978 -> 1.000;
pulse_span Samantha_Fox .850 -> .958, Warhawk .450 -> .690. Respelling the
silent restarts too (Commando's 41 ties, Ninja's 10) moved Ninja's
pulse_span .980 -> .946 and nothing audible on Commando. HISTORICAL figures.
"""
import json
import pathlib
from types import SimpleNamespace

import pytest

from h2g import goatwriter as G
from h2g.convert import convert
from h2g.goatwriter import arpeggio as GA
from h2g.goatwriter import build as GB
from h2g.goatwriter import note_passes as GN
from songview import parse_sng

from corpus import CORPUS, needs_corpus

REPO_ROOT = pathlib.Path(__file__).resolve().parents[2]
REST = G.GT_REST
TIE = [G.CMD_TONEPORTA, 0x00]
END = [0xFF, 0, 0, 0]


def _preset_opts(name):
    import fidelity
    doc = json.loads((REPO_ROOT / "presets.json").read_text(encoding="utf-8"))
    return fidelity._preset_opts(doc, name)


def _convert(name, **extra):
    lines = []
    opts = _preset_opts(name)
    opts.update(extra)
    sng = convert(str(CORPUS / name), log=lines.append, **opts)
    return sng, lines


# --- the family: read off the fetch, not assumed of `classic` ---------------

PAD = bytes(8)
RELOAD = bytes.fromhex("A9 FF 8D 01 55")          # LDA #$FF / STA $5501
FETCH = bytes.fromhex("B1 5F 9D F5 54 29 1F")     # LDA ($5F),Y / STA / AND #$1F
BLOCK = bytes.fromhex("BD 93 55 2D 01 55 99 04 D4 BD 91 55 99 02 D4")
CLASSIC = SimpleNamespace(pattern_dialect="classic", note_flag=False)


def _player(*parts):
    return SimpleNamespace(data=PAD + b"".join(parts) + PAD)


def test_the_family_is_a_start_block_gated_by_the_fetchs_own_mask():
    after = bytes.fromhex("BD 92 55")             # LDA pulse hi,X: "record"
    assert G.classic_tie_restart_family(
        _player(RELOAD, FETCH, BLOCK, after), CLASSIC) == "record"
    # PHA after the pulse write: the start reseeds per-voice sweep cells.
    assert G.classic_tie_restart_family(
        _player(RELOAD, FETCH, BLOCK, b"\x48"), CLASSIC) == "voice"
    # The zero-page spelling (Samantha_Fox `25 B7`).
    zp = bytes.fromhex("BD 09 74 25 B7 99 04 D4 BD 07 74 99 02 D4 48")
    assert G.classic_tie_restart_family(
        _player(bytes.fromhex("A9 FF 85 B7"), b"\xB1\xEE", zp),
        CLASSIC) == "voice"


def test_the_family_declines_what_it_cannot_read():
    after = bytes.fromhex("BD 92 55")
    # The AND names another cell than the one the fetch reloads with $FF.
    other = bytes.fromhex("A9 FF 8D 02 55")
    assert G.classic_tie_restart_family(
        _player(other, FETCH, BLOCK, after), CLASSIC) is None
    # The reload is not followed by the status fetch.
    assert G.classic_tie_restart_family(
        _player(RELOAD, b"\xEA\xEA", BLOCK, after), CLASSIC) is None
    # A bit-5 test between the fetch and the block: the tie may skip it.
    assert G.classic_tie_restart_family(
        _player(RELOAD, FETCH, b"\x29\x20\xD0\x10", BLOCK, after),
        CLASSIC) is None
    # A legato-marker player is `legato_tie_family`'s, and only classic.
    for det in (SimpleNamespace(pattern_dialect="classic", note_flag=True),
                SimpleNamespace(pattern_dialect="ilv", note_flag=False)):
        assert G.classic_tie_restart_family(
            _player(RELOAD, FETCH, BLOCK, after), det) is None


@needs_corpus
@pytest.mark.parametrize("name, want", [
    ("Commando.sid", "record"),
    ("Monty_on_the_Run.sid", "record"),
    ("Chimera.sid", "record"),
    ("International_Karate.sid", "voice"),
    ("Samantha_Fox_Strip_Poker.sid", "voice"),
    ("Thrust.sid", "voice"),
    ("Auf_Wiedersehen_Monty.sid", None),     # note_flag: legato_tie_family
    ("Mega_Apocalypse.sid", None),            # no such block
    ("Phantoms_of_the_Asteroid.sid", None),   # no such block
])
def test_the_family_on_the_corpus(name, want):
    from h2g.detect import detect
    from h2g.sidfile import load_sid
    sid = load_sid(str(CORPUS / name))
    assert G.classic_tie_restart_family(
        sid, detect(sid, lambda *a, **k: None)) == want


# --- which restarts are heard ------------------------------------------------

def test_a_steady_block_writes_one_waveform_at_the_patterns_note():
    steady = [(0x41, 0x00), (0x41, 0x00), (0x41, 0x00), (0xFF, 0x00)]
    assert GB._block_is_steady(steady, 1, 0x41)
    assert GB._block_is_steady(steady, 1, 0x00)        # no firstwave
    assert GB._block_is_steady([(0x41, 0x00), (0x08, 0x80), (0x41, 0x00),
                                (0xFF, 0x00)], 1, 0x41)
    # Commando's drum shape, a noise frame, a gate-off, another note, a
    # wavetable command, a firstwave the block does not keep.
    assert not GB._block_is_steady([(0x41, 0x00), (0x01, 0x80), (0x81, 0x00),
                                    (0x40, 0x00), (0xFF, 0x00)], 1, 0x41)
    assert not GB._block_is_steady([(0x41, 0x00), (0x41, 0x0C),
                                    (0xFF, 0x02)], 1, 0x41)
    assert not GB._block_is_steady([(0x41, 0x00), (0xF4, 0x01),
                                    (0xFF, 0x00)], 1, 0x41)
    assert not GB._block_is_steady(steady, 1, 0x81)


def test_a_pulse_program_sweeps_where_a_modulation_entry_moves():
    assert GB._pulse_sweeps([(0x88, 0x00), (0x0C, 0x7F), (0xFF, 0x02)], 1)
    assert not GB._pulse_sweeps([(0x82, 0x00), (0xFF, 0x00)], 1)
    assert not GB._pulse_sweeps([(0x88, 0x00), (0x0C, 0x7F)], 0)


def _records(*specs):
    """Instrument bytes at instr_at 0: (wave ptr, pulse ptr) per number."""
    out = bytearray(1 + 25 * len(specs))
    for g, (w, p) in enumerate(specs, 1):
        out[1 + (g - 1) * 25 + 2] = w
        out[1 + (g - 1) * 25 + 3] = p
    return out


STEADY = [(0x41, 0x00), (0x41, 0x00), (0xFF, 0x00)]     # wave rows 1-3
DRUM = [(0x41, 0x00), (0x81, 0x00), (0x40, 0x00), (0xFF, 0x00)]  # rows 4-7
SWEEP = [(0x88, 0x00), (0x0C, 0x7F), (0xFF, 0x02)]      # pulse rows 1-3
STATIC = [(0x82, 0x00), (0xFF, 0x00)]                   # pulse rows 4-5
PAT = [0x60, 1, 0, 0,  0x62, 0, *TIE,  0x64, 2, *TIE,  0x65, 3, *TIE,
       *END]
TRACKS = [[0, 0xFF, 0x00]] * 3


def _heard(out, kind="record"):
    return GB._restart_heard({(0, 1), (0, 2), (0, 3)}, TRACKS, [list(PAT)],
                             {1: 0, 2: 1, 3: 1}, out, 0, STEADY + DRUM,
                             SWEEP + STATIC, lambda g: 0, kind)


def test_a_tie_into_the_held_record_on_a_steady_block_is_silent():
    """Row 1 ties into the instrument the channel holds (1), on a steady
    block: the original's start writes what the voice already holds, and
    the old spelling stays. Row 2 changes record (1 -> 2): heard. Row 3
    changes number but not record (2 -> 3, both record 1): silent."""
    assert _heard(_records((1, 1), (1, 4), (1, 4))) == {(0, 2)}
    # A block the restart replays (the drum) is heard on the held record.
    assert _heard(_records((4, 1), (1, 4), (4, 4))) == {(0, 1), (0, 2), (0, 3)}


def test_a_sweep_is_heard_only_where_the_start_reseeds_it():
    """Instrument 1 sweeps. "record": the fetch writes the live value, so
    the tie moves no pulse. "voice": the start reseeds the sweep."""
    out = _records((1, 1), (1, 4), (1, 4))
    assert _heard(out, "record") == {(0, 2)}
    assert _heard(out, "voice") == {(0, 1), (0, 2)}


# --- the arpeggio counter's phase -------------------------------------------

def _locked(monkeypatch, residues, **kw):
    monkeypatch.setattr(GA, "arp_row_residues", lambda *a: residues)
    sid = SimpleNamespace(data=bytes(64))
    det = SimpleNamespace(instr_start=8, instr_stride=8)
    args = dict(arp_phases={1: 0}, arp_tie_rows={}, pitch_phases={},
                arp_gate_phases={}, phase_clones=[],
                distinct=lambda g, x: x != 0)
    args.update(kw)
    pat = [0x60, 1, 0, 0,  0x62, 0, *TIE,  0x64, 0, *TIE,  *END]
    return GB._phase_locked_ties(sid, det, {(0, 1), (0, 2)}, TRACKS, [pat],
                                 {1: 0}, 0, args["arp_phases"],
                                 args["arp_tie_rows"], args["pitch_phases"],
                                 args["arp_gate_phases"],
                                 args["phase_clones"], args["distinct"])


def test_a_tie_off_its_records_residue_keeps_the_old_spelling(monkeypatch):
    """Row 1 lands on residue 1, its record's block carries residue 0 and
    `distinct` says the two differ: a restart would put the octave out of
    the original's global counter. Row 2 lands on 0: free to restart."""
    assert _locked(monkeypatch, {(0, 1): {1}, (0, 2): {0}}) == {(0, 1)}
    # A row played on both residues is kept.
    assert _locked(monkeypatch, {(0, 1): {0, 1}, (0, 2): {0}}) == {(0, 1)}
    # A block no residue changes is free to restart anywhere.
    assert _locked(monkeypatch, {(0, 1): {1}, (0, 2): {0}},
                   distinct=lambda g, x: False) == set()


def test_shapes_no_residue_walk_models_keep_the_old_spelling(monkeypatch):
    res = {(0, 1): {0}, (0, 2): {0}}
    # The row-locked tie-chain shape is built for a tie that does NOT
    # restart (`fixed_arp_tie_rows`, Chimera).
    assert _locked(monkeypatch, res, arp_tie_rows={1: 3}) == {(0, 1), (0, 2)}
    # The nibble gate's phase is in the block: `distinct` at its own
    # residue says so.
    assert _locked(monkeypatch, res, arp_gate_phases={1: 2},
                   distinct=lambda g, x: True) == {(0, 1), (0, 2)}
    assert _locked(monkeypatch, res, arp_gate_phases={1: 2},
                   distinct=lambda g, x: False) == set()


# --- the clone ---------------------------------------------------------------

def test_a_same_record_clone_is_split_from_a_record_changing_one():
    """`kind(base, held)` splits a base's clones. A tie chain's second tie
    is read against the instrument the first one's row held (the walk reads
    each row before its respell), so the chain shares one clone."""
    pat = [0x60, 1, 0, 0,  0x62, 0, *TIE,  0x63, 0, *TIE,  0x64, 2, *TIE,
           0x65, 1, *TIE,  *END]
    kinds = {}
    out, clones, declined = G.legato_tie_clones(
        [pat], {(0, 1), (0, 2), (0, 3), (0, 4)}, TRACKS, {1, 2}, 5,
        kind=lambda base, held: held == base, kinds=kinds)
    assert not declined
    assert clones == [(1, 5), (2, 6), (1, 7)]
    assert kinds == {5: True, 6: False, 7: False}
    assert [out[0][4 * r + 1] for r in range(5)] == [1, 5, 5, 6, 7]


def test_a_kept_tie_back_into_a_clones_instrument_writes_no_envelope():
    """Bump_Set_Spike pattern $1F under `tie_restart`: row 12 becomes clone
    25 of instrument 14 with no note after it to re-latch, and the kept tie
    on row 36 names 14 again. The late envelope pass (`only=declined`) read
    the clone as another instrument and wrote 14's SR/AD around row 36 --
    the pair the chip already held. `alias` reads the clone as 14."""
    pat = [0x60, 14, 0, 0,  0x62, 25, 0, 0,  REST, 0, 0, 0,
           0x63, 14, *TIE,  REST, 0, 0, 0,  *END]
    env = {14: (0x0F, 0xF0), 25: (0x0F, 0xF0)}
    kept = {(0, 3)}
    same = G.note_passes._tied_instrument_envelopes(
        [list(pat)], env, TRACKS, only=kept, alias={25: 14})
    assert same == [pat]
    wrote = G.note_passes._tied_instrument_envelopes(
        [list(pat)], env, TRACKS, only=kept)
    assert wrote[0][8:12] == [REST, 14, G.CMD_SETSR, 0xF0]


@needs_corpus
def test_commandos_ties_restart_silently_so_its_bytes_do_not_move():
    """The task's own example: Commando's 41 playable ties all land on
    record 8 ($41 throughout, its sweep living in the record) in the
    instrument the channel holds -- the restart writes what is there."""
    old, _ = _convert("Commando.sid", tie_restart=False)
    new, lines = _convert("Commando.sid", tie_restart=True)
    assert new == old
    assert any("41 tie row(s) kept CMD_TONEPORTA, the restart writing what"
               in line for line in lines), lines
    # The fixture's own pair (tests/test_commando.py): default options.
    ref = (REPO_ROOT / "Commando.sng").read_bytes()
    assert convert(str(REPO_ROOT / "Commando.sid"), log=lambda m: None,
                   tie_restart=True) == ref


@needs_corpus
def test_thrust_restarts_its_drum_and_its_record_changes():
    """Thrust ("voice"): 22 heard ties on 3 clones -- record 9's drum
    (`41, 81, 40`) re-attacks with its noise frame, as the original's does,
    and records $17/$18 take their own pulse and envelope."""
    sng, lines = _convert("Thrust.sid", tie_restart=True)
    assert any("22 tie row(s) on 3 legato clone(s)" in line
               for line in lines), lines
    song = parse_sng(sng)
    base = {i.name: i for i in song.instruments[:28]}
    clones = [i for i in song.instruments[28:] if i.name in base
              and i.wave_ptr == base[i.name].wave_ptr]
    assert {i.name for i in clones} >= {"09:00-40-05", "17:11-13-00",
                                        "18:10-10-00"}
    for clone in clones:
        b = base[clone.name]
        if clone.gatetimer == b.gatetimer | G.GATETIMER_LEGATO and clone.firstwave == 0:
            assert clone.pulse_ptr == b.pulse_ptr and clone.pulse_ptr
            assert (clone.ad, clone.sr) == (b.ad, b.sr)


@needs_corpus
@pytest.mark.parametrize("name, record, held", [
    ("Monty_on_the_Run.sid", "0A:02-5F-04", True),   # tie into the held record
    ("Confuzion.sid", "04:00-00-00", False),         # tie changing record
])
def test_a_record_dialect_clone_holds_the_pulse_only_on_its_own_record(
        name, record, held):
    sng, _ = _convert(name, tie_restart=True)
    old = parse_sng(_convert(name, tie_restart=False)[0])
    song = parse_sng(sng)
    base = next(i for i in old.instruments if i.name == record)
    clone = song.instruments[-1]
    assert clone.name == record
    assert clone.gatetimer == base.gatetimer | G.GATETIMER_LEGATO
    assert clone.firstwave == 0 and base.firstwave == G.FIRSTWAVE_TESTBIT
    assert clone.pulse_ptr == (0 if held else base.pulse_ptr)
    assert base.pulse_ptr


@needs_corpus
def test_the_phase_locked_ties_keep_the_old_spelling():
    _, lines = _convert("Rasputin.sid", tie_restart=True)
    assert any("8 tie row(s) kept CMD_TONEPORTA, the clone's restart out of "
               "phase (8 arpeggio phase)" in line for line in lines), lines
    assert any("8 tie row(s) on 1 legato clone(s)" in line for line in lines)
    _, lines = _convert("Chimera.sid", tie_restart=True)
    # 541 before record 8's rows (waveform `$10`) and the attacks after them
    # stopped reading as ties (tests/test_gate_clear_record.py).
    assert any("(477 row-locked arpeggio)" in line for line in lines), lines
    # The nibble dialect's counter (`nibble_arp_phases`' walk), and its
    # gate's phase: International-Karate-style player, -S4.
    _, lines = _convert("Las_Vegas_Video_Poker.sid", tie_restart=True)
    assert any("(6 arpeggio phase; 16 gated arpeggio phase)" in line
               for line in lines), lines


# --- the option -------------------------------------------------------------

MOVERS = {
    # Action_Biker left at v0.5.514: presets.py raised its max_rows 94 -> 128,
    # and its two-entry pattern no longer needs the entry split.
    "5_Title_Tunes.sid", "Bump_Set_Spike.sid", "Chimera.sid", "Confuzion.sid",
    "Crazy_Comets.sid", "Devils_Galop.sid",
    "Geoff_Capes_Strongman_Challenge.sid", "Gerry_the_Germ.sid",
    "Gremlins.sid", "Human_Race.sid", "Hunter_Patrol.sid",
    "International_Karate.sid", "Kentilla.sid", "Las_Vegas_Video_Poker.sid",
    "Master_of_Magic.sid", "Monty_on_the_Run.sid", "One_Man_and_his_Droid.sid",
    "Proteus.sid", "Rasputin.sid", "Samantha_Fox_Strip_Poker.sid",
    "Spellbound.sid", "Thing_on_a_Spring.sid", "Thrust.sid", "Warhawk.sid", "Zoids.sid",
}


@needs_corpus
def test_the_option_moves_exactly_the_familys_heard_files():
    """Under the shipped presets, forcing the option on moves these 26 and
    nothing else -- every one of them in the family (at 6e467ff + this
    change; a sibling merge re-takes the set). Action_Biker and
    Thing_on_a_Spring joined with `entry_instrument_split`: each declined
    its ties "entered with two instruments" until the pattern was copied
    per entry instrument (Thing_on_a_Spring's 4 now take a clone;
    Action_Biker's 1 is then a quiet restart, so only the copy moves).
    Spellbound joined with `detect.GATE_HOLD_ZP_SHAPE`: until its player
    read as a gate-hold one it emitted no tie for the option to act on
    (tests/test_gate_hold_zp.py)."""
    from h2g.detect import detect
    from h2g.sidfile import load_sid
    songs = json.loads((REPO_ROOT / "presets.json").read_text(
        encoding="utf-8"))["songs"]               # the 89 that convert
    moved = set()
    for path in sorted(CORPUS.glob("*.sid")):
        if path.name not in songs:
            continue
        old, _ = _convert(path.name, tie_restart=False)
        new, _ = _convert(path.name, tie_restart=True)
        if new != old:
            moved.add(path.name)
            sid = load_sid(str(path))
            assert G.classic_tie_restart_family(
                sid, detect(sid, lambda *a, **k: None)), path.name
    assert moved == MOVERS, (sorted(moved - MOVERS), sorted(MOVERS - moved))


def test_the_option_is_held_out_of_always_and_in_the_cli(capsys):
    import presets
    from h2g import cli
    # Held out of `always` at v0.5.514 (see presets.EXCLUDED_FROM_ALWAYS):
    # per song or not at all until its pinned tests are re-reviewed.
    assert "tie_restart" not in presets.FIXED
    assert "tie_restart" in presets.EXCLUDED_FROM_ALWAYS
    doc = json.loads((REPO_ROOT / "presets.json").read_text(encoding="utf-8"))
    assert "tie_restart" not in doc["always"]
    with pytest.raises(SystemExit):
        cli.main(["--help"])
    assert "--tie-restart" in capsys.readouterr().out


@needs_corpus
def test_the_cli_flag_reaches_convert(tmp_path, monkeypatch):
    from h2g import cli
    seen = {}
    real = cli.convert

    def spy(path, **kw):
        seen.update(kw)
        return real(path, **kw)

    monkeypatch.setattr(cli, "convert", spy)
    out = tmp_path / "t.sng"
    assert cli.main([str(CORPUS / "Thrust.sid"), "-o", str(out), "-q",
                     "--tie", "--tie-restart"]) == 0
    assert seen["tie_restart"] is True and out.is_file()
