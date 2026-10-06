"""Bit $10's UNDIVIDED clock: Mega_Apocalypse's `$0A06` arpeggio in phase.

Task mega-0a06-frame-2-pitch-move. Records 06, 07, 09 and 0A of
Mega_Apocalypse (ADSR `$0A06`, effect `$30`) carry bit $10's chord
arpeggio: the player adds `$524D[phase]` -- 0, then the record's own pair
-- to the note, and the phase is a GLOBAL cell (`$51BF`) stepped DOWN once
per call after the voice loop (`$4E7E DEC $51BF / BPL / LDA #$02 / STA`).
Rows are 3 calls and the first row is fetched on call 1, so every note
attacks with the cell reading 1 and the original plays `0, 0, hi, lo, 0,
hi` from each attack -- all 110 notes of 180 s. The modal rotation (the
only path a clock-less file gets) played `0, lo, hi`: the wrong direction
and a frame early, 826 reversals against the original's 716.

`_pitch_seq_flat_clock` reads the clock; `pitch_seq_phases` then carries
the phase exactly as it does Food_Feud's divided one, and
`_pitch_seq_phased_entries` leads with one entry of the attack's own note
at -S1, where entry 0 is the frame the attack is named from.
"""
import dataclasses
import pathlib
import subprocess
import sys

import pytest

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[1]))

from corpus import CORPUS, needs_corpus                        # noqa: E402

import fidelity                                                # noqa: E402
from h2g import goatwriter as G                                # noqa: E402
from h2g.convert import _detect_tables, convert                # noqa: E402
from h2g.sidfile import load_sid                               # noqa: E402

needs_siddump = pytest.mark.skipif(
    not pathlib.Path(fidelity.SIDDUMP).exists(),
    reason="no siddump on this machine (tools/siddump-rt, see its README)")
needs_gt2reloc = pytest.mark.skipif(
    not pathlib.Path(fidelity.GT2RELOC).exists(),
    reason="no gt2reloc on this machine")

MEGA = CORPUS / "Mega_Apocalypse.sid"
FLAT = G.PitchSeqClock(divider=0, divider_reload=0, phase=2, phase_reload=2,
                       outer=None, inner=0)
# Record -> (lo, hi): the pair `$5392 + 2 * $54A3[record]` copies into
# `$524E/$524F`, i.e. what the player adds while the cell reads 1 and 2.
PAIRS = {0x06: (5, 8), 0x07: (3, 8), 0x09: (5, 9), 0x0A: (4, 9)}


def _mega():
    sid, det = _detect_tables(load_sid(str(MEGA)), lambda *a, **k: None)
    return sid, det


@needs_corpus
def test_the_flat_clock_is_read_on_mega_apocalypse_and_nowhere_else():
    """Every piece from the bytes; None on every other corpus file,
    including the 34 others that detect the block with an undivided
    counter (36 detect it; Food_Feud's is divided)."""
    got = {}
    for path in sorted(CORPUS.glob("*.sid")):
        sid, det = _detect_tables(load_sid(str(path)), lambda *a, **k: None)
        if det is None:
            continue
        clock = G._pitch_seq_flat_clock(sid, det)
        if clock is not None:
            got[path.stem] = clock
    assert got == {"Mega_Apocalypse": FLAT}, got


@needs_corpus
def test_the_dispatch_keeps_the_divided_reader_and_adds_the_flat_one():
    sid, det = _mega()
    assert G._pitch_seq_clock(sid, det) is None      # Food_Feud's reader only
    assert G._pitch_seq_any_clock(sid, det) == FLAT
    ff, ffd = _detect_tables(load_sid(str(CORPUS / "Food_Feud.sid")),
                             lambda *a, **k: None)
    assert G._pitch_seq_any_clock(ff, ffd) == G._pitch_seq_clock(ff, ffd)


@needs_corpus
def test_the_speed_counter_is_zero_page_and_the_init_clears_it():
    """`$580F LDX #$44 / LDA #0 / STA $B0,X / DEX / BPL` clears `$B0-$F4`;
    `$DF` is inside, `$AF` and `$F5` are not."""
    sid, _ = _mega()
    assert G._init_clears_zp(sid, 0xDF)
    assert G._init_clears_zp(sid, 0xB0) and G._init_clears_zp(sid, 0xF4)
    assert not G._init_clears_zp(sid, 0xAF)
    assert not G._init_clears_zp(sid, 0xF5)


@needs_corpus
def test_a_second_writer_of_the_phase_cell_declines_the_clock():
    """Nothing but the reload may store the cell, or its value is not the
    simulated one. One `STA $51BF` planted in dead bytes at the file's end."""
    sid, det = _mega()
    data = bytearray(sid.data)
    data[-3:] = bytes([0x8D, 0xBF, 0x51])
    assert G._pitch_seq_flat_clock(
        dataclasses.replace(sid, data=bytes(data)), det) is None


@needs_corpus
def test_a_phase_step_not_behind_the_voice_loop_declines_the_clock():
    """The `DEC` must sit right behind the voice loop's exit (`$4E78 DEX /
    BMI +3 / JMP $4AF3`), or it is not known to run once a call. The exit's
    `DEX` overwritten with a `NOP`."""
    sid, det = _mega()
    data = bytearray(sid.data)
    at = sid.to_offset(0x4E78)
    assert bytes(data[at:at + 4]) == G.arpeggio.PITCH_SEQ_VOICE_EXIT
    data[at] = 0xEA
    assert G._pitch_seq_flat_clock(
        dataclasses.replace(sid, data=bytes(data)), det) is None


def test_the_flat_clock_walks_only_its_own_subtune_and_no_outer_gate():
    divided = dataclasses.replace(FLAT, outer=1)
    assert G._pitch_seq_rate_read(FLAT, 3, None, 0)
    assert G._pitch_seq_rate_read(FLAT, 3, (), 0)
    assert not G._pitch_seq_rate_read(FLAT, 3, None, 1)
    assert not G._pitch_seq_rate_read(FLAT, 3, (3,), 0)
    assert not G._pitch_seq_rate_read(FLAT, None, None, 0)
    assert G._pitch_seq_rate_read(divided, 3, (3,), 1)
    assert not G._pitch_seq_rate_read(divided, 3, None, 0)


def test_the_flat_walk_fetches_on_the_reload_call_and_steps_every_call():
    """Call 0 (new song) steps the phase only; call 1 reloads the speed
    counter and fetches, reading the phase the new-song call left."""
    calls = G._pitch_seq_calls(FLAT, 3, None)
    got = [next(calls) for _ in range(7)]
    assert [f for _, f, _ in got] == [True, False, False] * 2 + [True]
    assert [s[1] for s, _, _ in got] == [1, 0, 2, 1, 0, 2, 1]
    assert [a[1] for _, _, a in got] == [0, 2, 1, 0, 2, 1, 0]
    assert G._pitch_seq_frames_after(FLAT, (0, 1)) == (0, 2, 1)


@needs_corpus
@needs_siddump
def test_the_simulated_flat_clock_is_re_measured_against_the_original():
    """`siddump -w51bf,00df` samples the phase cell and the speed counter
    after every call. The simulated phase must equal `$51BF` on every frame,
    the simulated fetches must be exactly the frames `$DF` reads its reload
    (2), and every attack the original plays must sit on one of them."""
    sid, det = _mega()
    clock = G._pitch_seq_any_clock(sid, det)
    speeds = G.find_song_speeds(sid, det)
    out = subprocess.run([str(fidelity.SIDDUMP), str(MEGA), "-a0", "-t60",
                          f"-v{fidelity.PAL_FLAG}", "-w51bf,00df"],
                         capture_output=True, text=True, timeout=180,
                         stdin=subprocess.DEVNULL).stdout
    cells = {}
    for line in out.splitlines():
        c = line.split("|")
        if len(c) >= 8:
            try:
                f = int(c[1])
            except ValueError:
                continue
            phase, ctr = c[6].split()
            cells[f] = (int(phase, 16), int(ctr, 16))
    assert len(cells) == 3000
    assert cells[0] == (1, 0)            # the new-song call: phase only
    calls = G._pitch_seq_calls(clock, speeds.frames_for(0), speeds.skip_for(0))
    fetches = set()
    for frame in range(1, 3000):
        _seen, fetched, after = next(calls)
        assert after == (0, cells[frame][0]), frame
        assert fetched == (cells[frame][1] == speeds.frames_for(0) - 1), frame
        if fetched:
            fetches.add(frame)
    attacks = set()
    for v in fidelity.parse_dump(out):
        attacks |= set(v.attack_frames)
    assert len(attacks) > 300
    assert attacks <= fetches, sorted(attacks - fetches)[:10]


def _mega_opts(pitch_seq: bool) -> dict:
    import json
    doc = json.loads((pathlib.Path(__file__).resolve().parents[2]
                      / "presets.json").read_text())
    opts = fidelity._preset_opts(doc, MEGA.name)
    opts["pitch_seq"] = pitch_seq
    return opts


@needs_corpus
def test_the_0a06_records_carry_the_players_phase():
    """With `pitch_seq` on, each `$0A06` record's wavetable is the attack's
    own note twice, then `hi, lo` -- the cell reads 0, 2, 1 on frames 1..3
    -- looped onto its second entry."""
    from songview import parse_sng
    sid, det = _mega()
    opts = _mega_opts(True)
    sng = convert(str(MEGA), lambda m: None, **opts)
    s = parse_sng(sng)
    W = s.tables["WTBL"]
    got = {}
    for ins in s.instruments:
        rec = int(ins.name.split(":")[0], 16)
        if rec not in PAIRS:
            continue
        p = ins.wave_ptr
        prog = [W[p - 1 + k] for k in range(5)]
        got[rec] = prog
        lo, hi = PAIRS[rec]
        assert prog == [(0x41, 0), (0x41, 0), (0x41, hi), (0x41, lo),
                        (0xFF, p + 1)], (rec, prog)
    assert sorted(got) == sorted(PAIRS)


def _frames_after(voices, nf, adsr, k):
    out = []
    for v in voices:
        fq = fidelity.register_timeline(v.freq_events, nf)
        ad = fidelity.register_timeline(v.adsr_events, nf)
        atk = sorted(v.attack_frames)
        for j, f0 in enumerate(atk):
            end = atk[j + 1] if j + 1 < len(atk) else nf
            if ad[f0] == adsr and end - f0 >= k and f0 + k <= nf:
                out.append(tuple(fq[f] - fq[f0] for f in range(f0, f0 + k)))
    return out


@needs_corpus
@needs_siddump
@needs_gt2reloc
def test_mega_apocalypse_0a06_notes_open_like_the_originals(tmp_path):
    """Frames 0..4 of every `$0A06` note: the original holds the note two
    frames, then `hi, lo, 0`. Ours must do the same on every note, compared
    as a set of shapes because ours runs `startup_lag` frames late."""
    secs, k = 120, 5
    opts = _mega_opts(True)
    m = opts.get("multiplier", 1) or 1
    sng = convert(str(MEGA), lambda x: None, **opts)
    sng, _ = fidelity.legalise_restarts(bytes(sng))
    packed = fidelity.pack_sid(sng, tmp_path, fidelity.GT2RELOC, m)
    assert packed is not None
    cal, _ft = fidelity.table_calibration(MEGA, opts)
    a = fidelity.run_siddump(MEGA, secs, 0, fidelity.SIDDUMP, cal)
    b = fidelity.run_siddump(packed, secs, 0, fidelity.SIDDUMP, calls=m)
    nf = secs * 50
    orig = _frames_after(a, nf, 0x0A06, k)
    ours = _frames_after(b, nf, 0x0A06, k)
    assert len(orig) >= 30 and len(ours) >= 30, (len(orig), len(ours))
    shape = lambda d: tuple((x > 0) - (x < 0) for x in d)   # noqa: E731
    assert {shape(d) for d in orig} == {(0, 0, 1, 1, 0)}
    assert {shape(d) for d in ours} == {(0, 0, 1, 1, 0)}
    # and the pitches themselves: hi above lo on every note, as the original
    assert all(d[2] > d[3] > 0 for d in ours)
