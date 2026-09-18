"""The fixed-interval arpeggio, and the two bytes of it that vary.

`detect._find_effect_routines` reads two dialects of effect bit `$04`. The
nibble form takes its interval from the record (`LSR x4` into an `SBC`
operand); the fixed form takes none at all -- a hardcoded `CLC / ADC #$0C`, an
octave up, chosen on a *global* frame counter:

    LDA effect  / AND #$04 / BEQ out
    LDA counter / AND #$mm / Bxx even
    LDA note,X  / CLC / ADC #$0C / JMP tofreq
  even:
    LDA note,X                          ; <- the JMP lands here + 3
    ASL / TAY / LDA freqtable,Y ...

Until this file existed the probe pinned `mm` to `$01` and `Bxx` to `BEQ`,
which is Commando's spelling and only Commando's. Nine corpus files carry the
block, with four different masks and both branch senses:

    $01 BEQ  Commando
    $02 BEQ  Rasputin
    $04 BNE  Zoids, One_Man_and_his_Droid
    $07 BEQ  Chimera, Battle_of_Britain, Game_Killer, Master_of_Magic,
             Human_Race, Phantoms_of_the_Asteroid

so eight of the nine read as having no arpeggio at all. Widening the two bytes
was a *detection* fix and deliberately not a rate fix: the mask is the
alternation period and, until v0.5.489, `goatwriter._wavetable_entries` did
not read it -- it emitted the one-call swing `AND #$01` gives. The A/B that
shipped the widening says so plainly. Every sequence and register dimension
(melody, seq, pitch, retrig, wave, noise, adsr, gate, nrun, hold, onset,
tail, drift) was **exactly unchanged** on all nine files; `bend` moved toward
1 on five of them (Phantoms 5.83 -> 1.14, Zoids 4.79 -> 0.91) and `vib` --
the oscillation rate -- moved on seven, four toward the original and three
past it (Game_Killer 0.19 -> 2.55, Master_of_Magic 0.59 -> 2.92). Mean
log-distance from 1.00 fell 1.29 -> 0.89. The overshoot was the mask the
emitter could not express.

**Since v0.5.489 the mask IS read**, and it is a duty cycle in frames
(`goatwriter.fixed_arp_period`, `fixed_arp_up`): `$02` two base and two up,
`$04` four and four, `$07` one base and seven up. `fixed_arp_duty_entries`
run-length codes one period onto wavetable delay entries from the record's
phase (`fixed_arp_phases`, now the counter's residue on the attack frame
rather than a 1-or-2 offset) and multiplies the runs out by the call rate.
Two counters are GATED -- Game_Killer's `INC` sits behind an outer
`DEC / BPL / LDA #$09 / STA / RTS` and Rasputin's behind `DEC / BPL / LDA
$C539 / STA / JMP`, where `$C539` is the track's own `$FE nn` tempo -- so the
counter is not the frame number, no phase can be walked, and those two take
the reset residue 0. Rasputin's duty follows that tempo: three and three at
the opening's reload 2, two and two at the 5..120 the rest of the tune
runs (232 of 293 octave onsets in a 240 s trace); it gets the mask's own
two-and-two. The tests below pin the readers, the shape against a
transcription of the player's wavetable loop at -S1 and -S2, and the duty
against a siddump of four originals.

What makes the block unambiguous is that both paths converge: the `JMP` after
the `ADC` lands exactly on the `ASL` of the fallthrough's own frequency
lookup, three bytes past its `LDA note,X`. Both halves therefore index one
table with one note, differing only by the twelve. The tests below check that
convergence, and check the interval against the player's *own* table rather
than against the immediate: `freq[n + 12] / freq[n]` is 2.00 to within the
rounding of a 16-bit table on all nine files.
"""
import pathlib
import sys

from corpus import CORPUS as _CORPUS, needs_corpus

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[1]))

from h2g.detect import _effect_byte_address, detect          # noqa: E402
from h2g.search import search_file                           # noqa: E402
from h2g.sidfile import load_sid                             # noqa: E402

CORPUS = _CORPUS
COMMANDO = pathlib.Path(__file__).resolve().parents[2] / "Commando.sid"

OCTAVE = 0x0C

# name -> (counter mask, branch opcode). Read out of the files, not assumed:
# four masks and two branch senses across nine players.
FIXED_ARP = {
    "Chimera": (0x07, 0xF0),
    "Zoids": (0x04, 0xD0),
    "Battle_of_Britain": (0x07, 0xF0),
    "Game_Killer": (0x07, 0xF0),
    "Master_of_Magic": (0x07, 0xF0),
    "Rasputin": (0x02, 0xF0),
    "Human_Race": (0x07, 0xF0),
    "One_Man_and_his_Droid": (0x04, 0xD0),
    "Phantoms_of_the_Asteroid": (0x07, 0xF0),
    "Commando": (0x01, 0xF0),
}


def _det(path):
    sid = load_sid(str(path))
    return sid, detect(sid, lambda *a, **k: None)


def _block(sid, det):
    """(offset, lead) of the fixed-interval arpeggio block, or (-1, 0)."""
    found = _effect_byte_address(sid, det)
    if not found:
        return -1, 0
    addr, zp = found
    load = f"A5 {addr:02X}" if zp else f"AD {addr & 0xFF:02X} {addr >> 8:02X}"
    lead = 2 if zp else 3
    for branch in ("F0", "D0"):
        at = search_file(
            sid.data,
            f"{load} 29 04 F0 ?? AD ?? ?? 29 ?? {branch} ?? BD ?? ?? 18 69 ??")
        if at >= 1:
            return at, lead
    return -1, lead


@needs_corpus
def test_every_fixed_arp_file_reports_an_octave():
    for name, (mask, branch) in FIXED_ARP.items():
        path = COMMANDO if name == "Commando" else CORPUS / f"{name}.sid"
        sid, det = _det(path)
        assert det.effect_arp is True, name
        assert det.arp_fixed_up == OCTAVE, name
        at, lead = _block(sid, det)
        assert at >= 1, name
        assert sid.data[at + lead + 8] == mask, name
        assert sid.data[at + lead + 9] == branch, name


@needs_corpus
def test_both_paths_reach_the_same_frequency_lookup():
    """The `JMP` lands on the fallthrough's `ASL`, three bytes past its `LDA`.

    Without this the block is only "an `ADC #$0C` somewhere near a bit test".
    With it, the two halves provably index one table with one note register,
    differing by exactly the twelve.
    """
    for name in FIXED_ARP:
        path = COMMANDO if name == "Commando" else CORPUS / f"{name}.sid"
        sid, det = _det(path)
        at, lead = _block(sid, det)
        assert at >= 1, name
        d = sid.data
        target = d[at + lead + 18] | d[at + lead + 19] << 8
        fall = at + lead + 20                   # the fallthrough `LDA note,X`
        assert d[fall] == 0xBD, name
        assert sid.to_offset(target) == fall + 3, name
        assert d[fall + 3] == 0x0A, name        # ASL
        assert d[fall + 4] == 0xA8, name        # TAY


@needs_corpus
def test_the_interval_is_an_octave_in_the_player_s_own_table():
    """`freq[n + 12] / freq[n]` == 2.00, read off the table the block uses.

    The immediate says twelve semitones; only the table says that is an
    octave. Both bytes of each entry are read from the two `LDA table,Y`
    operands the fallthrough carries, so nothing here is assumed about where
    the table sits.
    """
    for name in FIXED_ARP:
        path = COMMANDO if name == "Commando" else CORPUS / f"{name}.sid"
        sid, det = _det(path)
        at, lead = _block(sid, det)
        d = sid.data
        lookup = sid.to_offset(d[at + lead + 18] | d[at + lead + 19] << 8)
        assert lookup >= 0 and d[lookup + 2] == 0xB9, name   # ASL TAY LDA,Y
        table = sid.to_offset(d[lookup + 3] | d[lookup + 4] << 8)
        assert table >= 0, name
        ratios = []
        for note in range(24):
            lo = table + 2 * note
            hi = table + 2 * (note + 12)
            if hi + 1 >= len(d):
                break
            a = d[lo] | d[lo + 1] << 8
            b = d[hi] | d[hi + 1] << 8
            if a:
                ratios.append(b / a)
        assert len(ratios) >= 12, name
        assert min(ratios) > 1.99, (name, min(ratios))
        assert max(ratios) < 2.01, (name, max(ratios))


@needs_corpus
def test_no_other_corpus_file_claims_a_fixed_interval():
    """The widened bytes must reach this dialect and no other file.

    A mask wildcard is the loosest byte in the signature, so the guard against
    it is a census rather than an argument: exactly nineteen corpus files
    report an octave, and the two whose `ADC` operand is `$18` instead
    (Devils_Galop, Thing_on_a_Spring -- two octaves) are left out of the set
    on purpose, so a widening that started reading *their* interval as an
    octave would fail here rather than pass quietly. Ten of the nineteen the
    old `AND #$01 / BEQ` spelling already found; the nine of `FIXED_ARP`
    besides Commando are what the widening added, and the corpus byte-hash
    named exactly those nine.
    """
    seen = {}
    for path in sorted(CORPUS.glob("*.sid")):
        try:
            _, det = _det(path)
        except Exception:                                    # noqa: BLE001
            continue
        if det.arp_fixed_up:
            seen[path.stem] = det.arp_fixed_up
    octaves = {n for n, v in seen.items() if v == OCTAVE}
    expected = {n for n in FIXED_ARP if n != "Commando"} | {
        "5_Title_Tunes", "Crazy_Comets", "Geoff_Capes_Strongman_Challenge",
        "Gerry_the_Germ", "Gremlins", "Hunter_Patrol", "Last_V8",
        "Last_V8_C128_version", "Monty_on_the_Run", "Commando"}
    assert octaves == expected, sorted(octaves ^ expected)


# ---------------------------------------------------------------------------
# The phase of the alternation, v0.5.485.
#
# The tick shape held the base note through both noise entries and put the
# first octave on entry 4 -- `0 0 0 0 1 0 1` per offset from the attack where
# Commando's original reads `0 1 0 1 0 1 0`: a swing wrong on EVERY frame of
# every ticked note. `goatwriter.fixed_arp_phases` derives the phase from the
# file (counter base + first fetch + row index x row length) and the tick
# entries carry the octave from the original's frame. The measured
# endpoints are pinned below and RE-MEASURED against a trace of the original
# wherever siddump is on the machine, because a data point about a player is
# a data point until the trace says so again.
# ---------------------------------------------------------------------------
import pytest                                                # noqa: E402

from h2g.goatwriter import (fixed_arp_counter_base,          # noqa: E402
                            fixed_arp_counter_gated,
                            fixed_arp_duty_entries, fixed_arp_first_fetch,
                            fixed_arp_mask, fixed_arp_period, fixed_arp_phases,
                            fixed_arp_up, BEQ, BNE)

PYTHON_ROOT = pathlib.Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PYTHON_ROOT))
import fidelity                                              # noqa: E402

needs_siddump = pytest.mark.skipif(
    not pathlib.Path(fidelity.SIDDUMP).exists(),
    reason="no siddump on this machine (tools/siddump-rt, see its README)")

# The `AND #$01 / BEQ` files at -S1 under presets, and what the two readers
# return: (counter base, first fetch frame). Base 0 is the reset shape
# (`INC ctr / BIT / BMI / BVC / LDA #0 / STA ctr`); Hunter_Patrol's player
# never stores its counter, so its base is the file's byte $1E plus the INC.
# The first fetch is the speed gate counter's own byte.
PHASE_READINGS = {
    "Commando": (0, 0),
    "Crazy_Comets": (0, 1),
    "Gerry_the_Germ": (0, 1),
    "5_Title_Tunes": (0, 3),
    "Geoff_Capes_Strongman_Challenge": (0, 0),
    "Gremlins": (0, 2),
    "Hunter_Patrol": (0x1F, 1),
}


@needs_corpus
def test_counter_base_and_first_fetch_are_read_from_the_file():
    for name, (base, first) in PHASE_READINGS.items():
        sid, det = _det(CORPUS / f"{name}.sid")
        assert fixed_arp_counter_base(sid, det) == base, name
        assert fixed_arp_first_fetch(sid, det) == first, name
    # The repo fixture is the same player as the corpus Commando saved
    # mid-run: its gate counter byte is 1, so it attacks one frame later.
    sid, det = _det(COMMANDO)
    assert fixed_arp_counter_base(sid, det) == 0
    assert fixed_arp_first_fetch(sid, det) == 1
    # Another mask is the same counter and the same reset: Zoids divides by
    # $04 and its base reads 0 like Commando's (until v0.5.489 it read None,
    # the parity mask being the only one the emitter could use).
    sid, det = _det(CORPUS / "Zoids.sid")
    assert det.arp_fixed_up == OCTAVE
    assert fixed_arp_counter_base(sid, det) == 0
    assert fixed_arp_first_fetch(sid, det) == 1
    # A GATED counter has no base: its `INC` is skipped one call in R+1.
    for name in ("Game_Killer", "Rasputin"):
        sid, det = _det(CORPUS / f"{name}.sid")
        assert fixed_arp_counter_gated(sid, det), name
        assert fixed_arp_counter_base(sid, det) is None, name
    for name in ("Zoids", "Chimera", "Commando", "Hunter_Patrol"):
        sid, det = _det(CORPUS / f"{name}.sid")
        assert not fixed_arp_counter_gated(sid, det), name


def _timeline(voice, n):
    t, cur = [None] * n, None
    ev = dict(voice.freq_events)
    for f in range(n):
        if f in ev:
            cur = ev[f]
        t[f] = cur
    return t


@needs_corpus
@needs_siddump
@pytest.mark.parametrize("name", ["Commando", "Hunter_Patrol"])
def test_the_phase_is_re_measured_against_the_original(name):
    """Two endpoints per file, from a siddump of the ORIGINAL.

    * the first attack lands on the frame `fixed_arp_first_fetch` names;
    * every octave-up frame `f` of every onset has `base + f` odd, and every
      base frame after the attack has it even -- the counter's parity, read
      off the frequency rather than off the code.

    Commando is the reset shape and Hunter_Patrol the no-reset one; they
    disagree about which frames are odd, which is what the base is for.
    """
    path = CORPUS / f"{name}.sid"
    sid, det = _det(path)
    base = fixed_arp_counter_base(sid, det)
    first = fixed_arp_first_fetch(sid, det)
    seconds = 15
    trace = fidelity.run_siddump(path, seconds, 0, fidelity.SIDDUMP)
    n = seconds * 50 + 2
    attacks = [min(v.attack_frames) for v in trace if v.attack_frames]
    assert attacks and min(attacks) == first, (name, attacks, first)
    ups = downs = odd_ups = even_downs = 0
    for v in trace:
        t = _timeline(v, n)
        at = v.attack_frames
        for i, f in enumerate(at):
            end = at[i + 1] if i + 1 < len(at) else n
            seg = t[f:min(end, f + 13)]
            if not seg or not seg[0]:
                continue
            lo = min(x for x in seg if x)
            if not any(x and abs(x / lo - 2) < 0.02 for x in seg):
                continue                     # not an octave onset
            for k, x in enumerate(seg):
                if k == 0 or not x:
                    continue                 # the init frame runs no effect
                if abs(x / lo - 2) < 0.02:
                    ups += 1
                    odd_ups += (base + f + k) & 1
                elif x == lo:
                    downs += 1
                    even_downs += 1 - ((base + f + k) & 1)
    assert ups >= 100 and downs >= 100, (name, ups, downs)
    # Not 100%: a note may end mid-segment on a frame the effect no longer
    # writes. 97% of several hundred frames is the parity; a wrong base
    # reads about 3%.
    assert odd_ups / ups > 0.97, (name, odd_ups, ups)
    assert even_downs / downs > 0.97, (name, even_downs, downs)


def _converted(name):
    """(sng bytes, tracks, patterns) of a corpus file under its preset."""
    import json
    import h2g.convert as C
    doc = json.loads((PYTHON_ROOT.parent / "presets.json").read_text())
    opts = fidelity._preset_opts(doc, f"{name}.sid")
    got = {}
    real = C.build_sng

    def spy(sid, det, tracks, patterns, **kw):
        got["tracks"] = [list(t) for t in tracks]
        got["patterns"] = [list(p) for p in patterns]
        return real(sid, det, tracks, patterns, **kw)
    C.build_sng = spy
    try:
        sng = C.convert(str(CORPUS / f"{name}.sid"), log=lambda m: None, **opts)
    finally:
        C.build_sng = real
    return sng, got["tracks"], got["patterns"]


def _wavetable_of(sng, number):
    import songview
    s = songview.parse_sng(sng)
    wt = s.tables["WTBL"]
    ins = next(i for i in s.instruments if i.number == number)
    out, k = [], ins.wave_ptr - 1
    while k < len(wt):
        out.append(tuple(wt[k]))
        if wt[k][0] == 0xFF:
            break
        k += 1
    return out


@needs_corpus
def test_ticked_records_carry_the_octave_on_the_tick():
    """The shape, read back from the .sng by songview (a second reader).

    Commando attacks on even frames (base 0, first fetch 0, row 3 frames,
    its octave notes on even rows), so its first octave is offset 1: the
    FIRST tick entry carries $0C and the tails continue the alternation.
    Crazy_Comets attacks on odd frames (first fetch 1): offset 2, the SECOND
    tick entry. Before v0.5.485 both read `41 00 / 81 00 / 81 00 / 41 00 /
    41 0C / FF`, the octave after the tick.
    """
    if not (PYTHON_ROOT.parent / "presets.json").exists():
        pytest.skip("presets.json not present")
    sng, _, _ = _converted("Commando")
    assert _wavetable_of(sng, 2) == [(0x41, 0x00), (0x81, 0x0C), (0x81, 0x00),
                                     (0x41, 0x0C), (0x41, 0x00), (0xFF, 0x09)]
    sng, _, _ = _converted("Crazy_Comets")
    assert _wavetable_of(sng, 1) == [(0x11, 0x00), (0x81, 0x00), (0x81, 0x0C),
                                     (0x10, 0x00), (0x10, 0x0C), (0xFF, 0x04)]


@needs_corpus
def test_the_vote_splits_hunter_patrol_by_instrument():
    """Row 3 frames, first fetch 1, base $1F. Instrument 12's notes all sit
    on rows 0, 18, 36, ... -- odd frames, and with the odd base the counter
    is EVEN there (residue 0), so the octave is the frame after: offset 1.
    Instrument 11's notes sit on both parities, 11 odd-frame to 6 even-frame
    in one lap of voice 2, so it takes residue 0 too; instrument 4, the
    noise record the voice's other 150 notes play, sits on even frames
    throughout and takes residue 1, offset 2. The walk names the frame of
    all 131 of voice 2's attacks exactly (v0.5.485, siddump of the
    original), so the split is the music's, and instrument 11's minority is
    the residue a per-note phase would recover.

    The values are the counter's residue since v0.5.489 (`0` and `1` where
    they were the offsets `1` and `2`); `_wavetable_entries`' tick shape
    turns a residue back into `1 + (residue & 1)`.
    """
    if not (PYTHON_ROOT.parent / "presets.json").exists():
        pytest.skip("presets.json not present")
    sid, det = _det(CORPUS / "Hunter_Patrol.sid")
    _, tracks, patterns = _converted("Hunter_Patrol")
    phases = fixed_arp_phases(sid, det, tracks, patterns)
    assert (phases.get(12), phases.get(11), phases.get(4)) == (0, 0, 1), phases
    sid, det = _det(CORPUS / "Commando.sid")
    _, tracks, patterns = _converted("Commando")
    phases = fixed_arp_phases(sid, det, tracks, patterns)
    assert phases and set(phases.values()) == {0}, phases


# ---------------------------------------------------------------------------
# The mask's duty cycle, v0.5.489.
#
# `fixed_arp_duty_entries` is checked three ways: the readers against the
# files, the shape against a transcription of the player's wavetable loop
# (`test_call_rate.wave_timeline`, gplay.c's WAVEEXEC) at -S1, -S2 and -S3,
# and the duty against a siddump of the originals wherever siddump is on the
# machine. Nothing here asserts a count of entries: the shape is whatever
# the loop plays.
# ---------------------------------------------------------------------------
from test_call_rate import wave_timeline                     # noqa: E402

# name -> counter residue on the attack frame for the profile the original
# sounds most (measure_duty at v0.5.489, per-onset `b`/`u` from the attack):
#   Zoids `buubbbbuuuubbbbuu` 78 of 108   One_Man `buuubbbb` 187 of 188
#   Master_of_Magic `buuuuuubuuuuuuub` 174 of 244
#   Phantoms `buuuuuuu` 319 of 340
DUTY_PROFILES = {
    "Zoids": (1, "buubbbbuuuubbbbuu"),
    "One_Man_and_his_Droid": (0, "buuubbbb"),
    "Master_of_Magic": (1, "buuuuuubuuuuuuub"),
    "Phantoms_of_the_Asteroid": (0, "buuuuuuu"),
}


def test_the_period_is_the_masks_highest_bit_doubled():
    assert fixed_arp_period(0x01) == 2
    assert fixed_arp_period(0x02) == 4
    assert fixed_arp_period(0x04) == 8
    assert fixed_arp_period(0x07) == 8


def test_the_branch_sense_swaps_the_paths():
    # `BEQ base`: up where the masked counter is nonzero.
    assert [fixed_arp_up(0x07, BEQ, c) for c in range(8)] == [False] + [True] * 7
    assert [fixed_arp_up(0x02, BEQ, c) for c in range(4)] == [False, False, True, True]
    # `BNE base`: Zoids' spelling, up where it is zero.
    assert [fixed_arp_up(0x04, BNE, c) for c in range(8)] == [True] * 4 + [False] * 4
    assert [fixed_arp_up(0x01, BEQ, c) for c in range(4)] == [False, True, False, True]


@needs_corpus
def test_the_mask_is_read_from_every_file():
    for name, (mask, branch) in FIXED_ARP.items():
        path = COMMANDO if name == "Commando" else CORPUS / f"{name}.sid"
        sid, det = _det(path)
        assert fixed_arp_mask(sid, det) == (mask, branch), name


def _profile(left, right, up_note, calls, start=6):
    """`b`/`u` per play call from the loop transcription, entry 0 on call 0."""
    out = []
    for _, _, note in wave_timeline(left, right, first=start, calls=calls):
        out.append("u" if note == up_note else "b")
    return "".join(out)


def _expected(mask, branch, phase, frames, m):
    """The original's profile, frame 0 base, each frame `m` calls."""
    prof = "b" * m
    for j in range(1, frames):
        prof += ("u" if fixed_arp_up(mask, branch, phase + j) else "b") * m
    return prof


@pytest.mark.parametrize("m", [1, 2, 3])
@pytest.mark.parametrize("mask,branch", [(0x02, BEQ), (0x04, BNE), (0x07, BEQ)])
@pytest.mark.parametrize("phase", range(8))
def test_the_shape_plays_the_masks_duty_at_every_rate(mask, branch, phase, m):
    """One period of frames, run-length coded, at -S1, -S2 and -S3.

    Every call of 40 frames is checked against `fixed_arp_up` on the
    counter the frame would read, from every residue the counter can hold
    on the attack frame. The loop transcription is what consumes delay
    entries, so `value + 1` calls and the note on the last of them are
    both exercised rather than assumed.
    """
    if phase >= fixed_arp_period(mask):
        pytest.skip("residue past the period")
    got = fixed_arp_duty_entries(0x41, 0x41, mask, branch, phase, 0x0C, m,
                                 start=6, budget=255)
    assert got is not None
    left, right = got
    assert left[0] == 0x41 and right[0] == 0x00      # frame 0: the record
    assert left[-1] == 0xFF and 6 <= right[-1] < 6 + len(left) - 1
    frames = 40
    assert (_profile(left, right, 0x0C, frames * m)
            == _expected(mask, branch, phase, frames, m))


def test_the_written_shape_starts_on_frame_one():
    """`written`: the firstwave owns frame 0, entry 0 is frame 1's call."""
    left, right = fixed_arp_duty_entries(0x41, 0x41, 0x04, BNE, 0, 0x0C, 2,
                                         start=6, budget=255, written=True)
    # Frame 1 is up for residue 0 under `$04 BNE`, so the very first entry
    # -- the tail -- carries the octave.
    assert (left[0], right[0]) == (0x41, 0x0C)
    prof = _profile(left, right, 0x0C, 39 * 2)
    assert "b" * 2 + prof == _expected(0x04, BNE, 0, 40, 2)


def test_the_tick_frames_carry_noise_and_the_octave():
    """A both-bits record: the drum's opening noise, and the octave on it."""
    left, right = fixed_arp_duty_entries(0x41, 0x40, 0x07, BEQ, 0, 0x0C, 1,
                                         start=6, budget=255,
                                         tick=(0x81, 2))
    assert left[:4] == [0x41, 0x81, 0x81, 0x40]      # record, noise x2, tail
    assert right[1] == 0x0C                          # frame 1 is up
    tl = wave_timeline(left, right, first=6, calls=20)
    waves = [w for _, w, _ in tl]
    assert waves[:4] == [0x41, 0x81, 0x81, 0x40] and set(waves[4:]) == {0x40}
    assert _profile(left, right, 0x0C, 20) == _expected(0x07, BEQ, 0, 20, 1)


def test_a_run_longer_than_a_delay_is_split():
    """`$07` at -S3: seven up frames are 21 calls, past WAVE_MAX_DELAY."""
    left, right = fixed_arp_duty_entries(0x41, 0x41, 0x07, BEQ, 0, 0x0C, 3,
                                         start=6, budget=255)
    assert max(v for v in left if v < 0x10) == 0x0F
    assert _profile(left, right, 0x0C, 30 * 3) == _expected(0x07, BEQ, 0, 30, 3)


def test_the_shape_declines_a_budget_it_cannot_fit():
    assert fixed_arp_duty_entries(0x41, 0x41, 0x04, BNE, 1, 0x0C, 1,
                                  start=6, budget=3) is None


@needs_corpus
def test_the_duty_reaches_the_sng_and_the_parity_files_keep_theirs():
    """Read back by songview: Zoids' loop is four and four, Commando's the
    tick shape pinned above -- byte for byte what it was before the duty
    existed, because `$01` never reaches `fixed_arp_duty_entries`."""
    if not (PYTHON_ROOT.parent / "presets.json").exists():
        pytest.skip("presets.json not present")
    sng, _, _ = _converted("Zoids")
    wt = _wavetable_of(sng, 6)
    # record, tail + octave, then the four-and-four loop: the profile the
    # original sounds on 78 of its 108 octave onsets.
    left = [l for l, _ in wt]
    right = [r for _, r in wt]
    assert left[0] == 0x41 and left[-1] == 0xFF
    assert _profile(left, right, 0x0C, 17, start=34) == "buubbbbuuuubbbbuu"
    sng, _, _ = _converted("Commando")
    assert _wavetable_of(sng, 2) == [(0x41, 0x00), (0x81, 0x0C), (0x81, 0x00),
                                     (0x41, 0x0C), (0x41, 0x00), (0xFF, 0x09)]


@needs_corpus
@needs_siddump
@pytest.mark.parametrize("name", sorted(DUTY_PROFILES))
def test_the_duty_is_re_measured_against_the_original(name):
    """Every octave frame of every onset against `fixed_arp_up(mask, branch,
    frame)`: the counter is the frame number in these four (reset shape,
    ungated `INC`), so the duty AND its phase are read off the trace."""
    path = CORPUS / f"{name}.sid"
    sid, det = _det(path)
    mask, branch = fixed_arp_mask(sid, det)
    assert fixed_arp_counter_base(sid, det) == 0
    seconds = 30
    trace = fidelity.run_siddump(path, seconds, 0, fidelity.SIDDUMP)
    n = seconds * 50 + 2
    agree = disagree = 0
    for v in trace:
        t = _timeline(v, n)
        at = v.attack_frames
        for i, f in enumerate(at):
            end = at[i + 1] if i + 1 < len(at) else n
            seg = t[f:min(end, f + 17)]
            if not seg or not seg[0]:
                continue
            lo = min(x for x in seg if x)
            if not any(x and abs(x / lo - 2) < 0.02 for x in seg):
                continue
            for k, x in enumerate(seg):
                if k == 0 or not x:
                    continue
                is_up = abs(x / lo - 2) < 0.02
                if not is_up and x != lo:
                    continue
                if is_up == fixed_arp_up(mask, branch, f + k):
                    agree += 1
                else:
                    disagree += 1
    assert agree >= 300, (name, agree, disagree)
    assert disagree / (agree + disagree) < 0.02, (name, agree, disagree)


# --- The ticked shape above -S1 (v0.5.489, `ticked_arp_entries`) ---------
#
# Until v0.5.489 a ticked arpeggio record above -S1 was forced onto the
# per-call two-entry loop, so the octave toggled `m` times a frame: on the
# packed Last_V8 at -S2, vsid at 312 samples a frame read the note and its
# octave in the SAME frame on 75 of 399 frames, split 155-160 / 312
# rasterlines -- a 100 Hz trill siddump cannot see, since it samples once a
# frame and read a constant octave-up (`bbUUUUUb` on 421 of 503 onsets
# where the original plays `bUbUbUbU` on 314 of 370). With the shape below
# the same trace reads `bUbUbUbU` on 364 of 443 onsets and vsid reads 0
# frames carrying both notes (C:/t/ticked-fixed-arp-at-s2-is-a-/
# prof_Last_V8.txt, vice_ab.txt).

from h2g.goatwriter import ticked_arp_entries                 # noqa: E402


def _ticked(m, tick_frames=1, wave=0x41, tail=0x41, phase=None, budget=255,
            written=False):
    """A ticked record's lead and tick as `_wavetable_entries` builds them
    at -S{m}: the record's waveform for one frame, then `tick_frames`
    frames of noise -- a second noise entry at -S2, a delay above it."""
    from h2g.goatwriter import _first_frame_lead
    noise = 0x80 | (wave & 0x01)
    frame0, frame0_r = _first_frame_lead(wave, m, force=True, written=written)
    extra = tick_frames * m - 1
    tl, tr = [noise], [0x00]
    if extra == 1:
        tl.append(noise)
        tr.append(0x00)
    elif extra > 1:
        tl.append(min(extra - 1, 0x0F))
        tr.append(0x80)
    return ticked_arp_entries(frame0, frame0_r, tl, tr, noise, tail, 0x0C,
                              m, 6, budget, arp_phase=phase)


def _frames(left, right, m, frames, start=6):
    """One `b`/`u`/`n` per FRAME: the note each frame's last call carries
    (siddump's reading), `n` where the waveform is the noise tick."""
    out = ""
    calls = wave_timeline(left, right, first=start, calls=frames * m)
    for j in range(frames):
        _, wave, note = calls[j * m + m - 1]
        out += "n" if wave in (0x80, 0x81) else "u" if note == 0x0C else "b"
    return out


@pytest.mark.parametrize("m", [2, 3, 4, 7])
def test_the_ticked_shape_holds_each_half_for_m_calls(m):
    """Every call of 20 frames from the loop transcription: the record's
    waveform for frame 0, the noise tick for frame 1, then the note and
    the octave alternating a whole frame each -- `m` calls a half, never
    the per-call toggle -- and the loop target past the tick."""
    left, right = _ticked(m)
    assert left[-1] == 0xFF
    assert right[-1] == 6 + len(left) - 5          # the entry after the tick
    assert right[-1] > 6 + 1                       # never entry 0, never the lead
    calls = wave_timeline(left, right, first=6, calls=20 * m)
    notes = [note for _, _, note in calls]
    waves = [wave for _, wave, _ in calls]
    assert waves[:m] == [0x41] * m                     # frame 0: the record
    assert waves[m:2 * m] == [0x81] * m                # frame 1: the tick
    assert all(w == 0x41 for w in waves[2 * m:])       # the tick plays once
    # from frame 2 on, runs of exactly m calls, alternating
    body = notes[2 * m:]
    runs = []
    for x in body:
        if runs and runs[-1][0] == x:
            runs[-1][1] += 1
        else:
            runs.append([x, 1])
    assert [r[1] for r in runs[:-1]] == [m] * (len(runs) - 1), runs
    assert [r[0] for r in runs[:4]] == [0x00, 0x0C, 0x00, 0x0C]
    assert _frames(left, right, m, 8) == "bnbububu"


@pytest.mark.parametrize("m", [2, 3])
@pytest.mark.parametrize("residue", [0, 1])
def test_the_ticked_shape_carries_the_phase(m, residue):
    """The parity residue read by `fixed_arp_phases`: 0 puts the first
    octave on frame 1 -- the tick frame, carried on the noise entries'
    right side -- and 1 on frame 2, at every rate. Per frame, the shape
    is the original's `bUbU...` from the attack (Last_V8 and Monty read
    `0 1 0 1 0 1` at v0.5.482, the first octave at offset 1)."""
    left, right = _ticked(m, phase=residue)
    first_up = 1 + residue
    want = "".join("u" if (j - first_up) % 2 == 0 else "b" for j in range(1, 12))
    got = _frames(left, right, m, 12)
    assert got[0] == "b"
    # frame 1 is the tick: its note is what the noise entries carry
    tick_note = right[len(left) - 5 - m * 1:len(left) - 5]
    assert set(tick_note) == ({0x0C} if residue == 0 else {0x00})
    assert got[2:] == want[1:], (got, want)


def test_the_ticked_shape_leaves_the_tick_alone_where_it_cannot_expand():
    """A tick clamped by WAVE_MAX_DELAY is not a whole number of frames, so
    the phase cannot be placed per frame: the tick keeps its delay entry
    and the loop starts on the note, as it does with no phase at all."""
    left, right = _ticked(9, tick_frames=2, phase=0)     # 17 calls -> $0F
    assert 0x0F in left
    assert right[-5] == 0x00 and right[-3] == 0x0C


def test_the_ticked_shape_declines_a_budget_it_cannot_fit():
    assert _ticked(2, budget=8) is None
    assert _ticked(2, budget=9) is not None
    assert ticked_arp_entries([0x41], [0], [0x81], [0], 0x81, 0x41, 0x0C, 1,
                              6, 255) is None            # -S1 keeps its shape


@needs_corpus
def test_the_ticked_multispeed_records_reach_the_sng():
    """Read back by songview: Last_V8's ticked octave record at -S2 holds
    each half two calls and its loop returns to the entry after the tick,
    while Monty's unticked record keeps the -S{m} shape it had."""
    if not (PYTHON_ROOT.parent / "presets.json").exists():
        pytest.skip("presets.json not present")
    sng, _, _ = _converted("Last_V8")
    assert _wavetable_of(sng, 2) == [
        (0x41, 0x00), (0x41, 0x00), (0x81, 0x0C), (0x81, 0x0C),
        (0x40, 0x00), (0x40, 0x80), (0x40, 0x0C), (0x40, 0x80), (0xFF, 0x11)]
    sng, _, _ = _converted("Monty_on_the_Run")
    assert _wavetable_of(sng, 5) == [(0x41, 0x00), (0x41, 0x00), (0x41, 0x0C),
                                     (0x41, 0x80), (0xFF, 0x1A)]


# ---------------------------------------------------------------------------
# The UNTICKED -S1 parity shape, and the residue it read from v0.5.490:
# `wave/00, tail/00, tail/00, FF -> entry 1` loops over entries 1 and 2, so
# entry 1 plays every odd frame after the attack and entry 2 every even one.
# Until v0.5.490 the octave was hard-coded on entry 2 -- offset 2 -- for
# every record, while the tick shape beside it and `ticked_arp_entries`
# already read `fixed_arp_phases`. The corpus byte-hash that shipped this
# moved exactly the residue-0 files: Geoff_Capes_Strongman_Challenge,
# Gremlins and Hunter_Patrol (its instrument 9; 14 and 15 are residue 1 and
# kept their bytes). Per-offset up-fraction at offset 1, original / before /
# after, 180 s: Gremlins 0.90 / 0.95 / 1.00, Hunter_Patrol 0.40 / 0.15 / 0.32;
# Geoff_Capes at 60 s 0.90 / 0.74 / 1.00. `vib` cannot see a parity swap
# (it counts reversals, and a shifted alternation has the same number), so
# the profile is the measurement.

from h2g.goatwriter import unticked_arp_octave_entry           # noqa: E402


@pytest.mark.parametrize("residue, entry", [(0, 1), (1, 2)])
def test_the_unticked_shape_puts_the_octave_on_the_residues_entry(residue, entry):
    """Residue 0 is a first octave on offset 1 -- entry 1 of the loop;
    residue 1 is offset 2 -- entry 2, the offset every record had before."""
    assert unticked_arp_octave_entry(residue) == entry
    # A higher residue is read by parity, as the tick shape reads it.
    assert unticked_arp_octave_entry(residue + 2) == entry


@pytest.mark.parametrize("residue", [0, 1])
def test_the_written_unticked_shape_lands_a_frame_later(residue):
    """`--no-test-restart`: the firstwave owns frame 0 and every entry
    plays a frame later, so the octave swaps entries -- the empty
    `_first_frame_lead` the tick shape reads as `k + 1`."""
    assert (unticked_arp_octave_entry(residue, written=True)
            != unticked_arp_octave_entry(residue, written=False))
    assert unticked_arp_octave_entry(residue, written=True) in (1, 2)


@needs_corpus
def test_the_unticked_records_carry_the_residue_in_the_sng():
    """Read back by songview (a second reader). Geoff_Capes attacks on even
    frames (base 0, first fetch 0; residue 0): the octave is on entry 1.
    Crazy_Comets attacks on odd frames (first fetch 1; residue 1): entry 2,
    byte for byte the shape it had before v0.5.490. Hunter_Patrol has both
    residues in one file, split by instrument (`fixed_arp_phases`' vote)."""
    if not (PYTHON_ROOT.parent / "presets.json").exists():
        pytest.skip("presets.json not present")
    sng, _, _ = _converted("Geoff_Capes_Strongman_Challenge")
    assert _wavetable_of(sng, 8) == [(0x41, 0x00), (0x41, 0x0C), (0x41, 0x00),
                                     (0xFF, 0x29)]
    sng, _, _ = _converted("Crazy_Comets")
    assert _wavetable_of(sng, 10) == [(0x41, 0x00), (0x41, 0x00), (0x41, 0x0C),
                                      (0xFF, 0x3A)]
    sng, _, _ = _converted("Hunter_Patrol")
    assert _wavetable_of(sng, 9) == [(0x41, 0x00), (0x41, 0x0C), (0x41, 0x00),
                                     (0xFF, 0x2E)]
    assert _wavetable_of(sng, 14) == [(0x41, 0x00), (0x41, 0x00), (0x41, 0x0C),
                                      (0xFF, 0x53)]
