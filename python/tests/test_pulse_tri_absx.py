"""The per-voice triangle pulse engine with ABSOLUTE cells (PULSE_TRI_ABSX_SHAPE).

Bump_Set_Spike $B2A4 is Samantha Fox's per-voice triangle instruction for
instruction with every cell absolute (`ADC $B50D,X`, `LDA $B510,X`), so
neither PULSE_TRI_SHAPE (per-record `ADC instr,Y`) nor PULSE_TRI_ZP_SHAPE
matched and its bass -- record 2, rate $40, width $080 -- was written as the
static width. The player climbs $080, $0C0, $100, ... every call from each
note fetch ($B14A-$B174 reseeds the pair); ours sat on $080 (a user heard the
bass "low in volume and not as full").
"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from corpus import CORPUS, needs_corpus                      # noqa: E402
from h2g.detect import (PULSE_TRI_ABSX_SHAPE, PULSE_TRI_CMD_SHAPE,  # noqa: E402
                        PULSE_TRI_SHAPE, _find_pulse_tri_cmd,
                        PULSE_TRI_ZP_SHAPE, _find_pulse_tri_absx, detect)
from h2g.goatwriter.pulse import _pulse_tri_program          # noqa: E402
from h2g.search import search_file                           # noqa: E402
from h2g.sidfile import load_sid                             # noqa: E402

BUMP = "Bump_Set_Spike.sid"
ABSX_FILES = {BUMP, "Formula_1_Simulator.sid", "International_Karate.sid",
              "Kentilla.sid", "Las_Vegas_Video_Poker.sid", "Proteus.sid",
              "Thrust.sid", "Warhawk.sid"}


def _quiet(*_a, **_k):
    pass


@needs_corpus
def test_the_absolute_per_voice_spelling_is_found_on_exactly_its_files():
    found = set()
    for path in sorted(CORPUS.glob("*.sid")):
        sid = load_sid(str(path))
        det = detect(sid, _quiet)
        if search_file(sid.data, PULSE_TRI_ABSX_SHAPE) < 0:
            continue
        # A rescue: never where either other spelling matched.
        assert search_file(sid.data, PULSE_TRI_SHAPE) < 0, path.name
        assert search_file(sid.data, PULSE_TRI_ZP_SHAPE) < 0, path.name
        assert det.pulse_tri_per_voice, path.name
        assert (det.pulse_tri_lo, det.pulse_tri_hi) == (8, 0x0E), path.name
        assert (det.pulse_tri_step_mask,
                det.pulse_tri_delay_mask) == (0xF0, 0x0F), path.name
        assert det.pulse_tri_gated, path.name
        found.add(path.name)
    assert found == ABSX_FILES


@needs_corpus
def test_the_match_is_anchored_on_the_note_fetch_seed():
    """$B14A `LDA $B513,X / STA $D402,Y / PHA`: point the seed anywhere but
    instr_start and the match is refused."""
    sid = load_sid(str(CORPUS / BUMP))
    det = detect(sid, _quiet)
    assert _find_pulse_tri_absx(sid, det) is not None
    seed = sid.data.find(bytes([0xBD, 0x13, 0xB5, 0x99, 0x02, 0xD4]))
    assert seed >= 0 and sid.to_offset(0xB513) == det.instr_start
    data = bytearray(sid.data)
    data[seed + 1] = 0x17
    import dataclasses
    bad = dataclasses.replace(sid, data=bytes(data))
    assert _find_pulse_tri_absx(bad, det) is None


@needs_corpus
def test_bump_set_spike_bass_sweeps_from_its_width_at_the_players_rate():
    """Record 2 (ADSR $0F9E): set $080, then ascend. Rate $40 is a step of
    $40 every tick; at -S3 behind the 9-reload outer gate a tick is 10/3 of
    our calls, so 64 * 3 / 10 = 19.2 -> 19 a call (57 a frame against the
    original's 64 on 9 frames in 10, 57.6)."""
    sid = load_sid(str(CORPUS / BUMP))
    det = detect(sid, _quiet)
    prog = _pulse_tri_program(sid, det, 2, 3)
    assert prog is not None
    entries, _loop = prog
    assert entries[0] == (0x80, 0x80)          # set width $080
    assert entries[1][1] == 19                 # ascending speed per call


@needs_corpus
def test_the_command_table_spelling_halves_the_step_and_reads_voice_bounds():
    """Hollywood_or_Bust $06BD `AND #$F0 / LSR`: record 0 (the bass, ADSR
    $2C9F, rate $80) steps $40 a frame from $000, as siddump shows the
    original doing ($040, $080, $0C0 ... at frames 900-913). Its bounds are
    the per-voice cells $09AE/$09AB, $08 and $0F on every voice."""
    sid = load_sid(str(CORPUS / "Hollywood_or_Bust.sid"))
    det = detect(sid, _quiet)
    assert search_file(sid.data, PULSE_TRI_CMD_SHAPE) >= 0
    assert det.pulse_tri_per_voice and det.pulse_tri_step_shift == 1
    assert (det.pulse_tri_lo, det.pulse_tri_hi) == (8, 0x0F)
    entries, _loop = _pulse_tri_program(sid, det, 0, 1)
    assert entries[0] == (0x80, 0x00)
    assert entries[1][1] == 0x40


@needs_corpus
def test_the_command_table_spelling_declines_disagreeing_voice_bounds():
    """Chicken_Song carries the same routine, but its voice 3 cells hold
    $01/$04 against $08/$0F on the other two: one program per record cannot
    turn at both, so the reading declines rather than pick one."""
    sid = load_sid(str(CORPUS / "Chicken_Song.sid"))
    det = detect(sid, _quiet)
    assert search_file(sid.data, PULSE_TRI_CMD_SHAPE) >= 0
    assert _find_pulse_tri_cmd(sid, det) is None
    assert det.pulse_tri_hi < 0


def _convert_logged(name, **over):
    import json
    import fidelity
    from h2g.convert import convert
    doc = json.loads((Path(__file__).resolve().parents[2]
                      / "presets.json").read_text())
    lines = []
    out = convert(str(CORPUS / name), log=lines.append,
                  **dict(fidelity._preset_opts(doc, name), **over))
    # "Legato tie..: N tie row(s) kept CMD_TONEPORTA, the restart writing
    # what the voice already holds" -- the ties left unrespelled.
    kept = sum(int(line.split(":", 1)[1].split()[0]) for line in lines
               if "the restart writing what the voice already holds" in line)
    return out, kept


@needs_corpus
def test_tie_pulse_restart_is_what_respells_a_tie_into_a_sweeping_record():
    """International_Karate's ties land on records this engine now sweeps.
    Off (the default) they keep CMD_TONEPORTA; on, the ones whose landing
    replays only the pulse restart are respelled, so fewer are kept and the
    bytes move."""
    off, kept_off = _convert_logged("International_Karate.sid")
    on, kept_on = _convert_logged("International_Karate.sid",
                                  tie_pulse_restart=True)
    assert off != on
    assert kept_on < kept_off
