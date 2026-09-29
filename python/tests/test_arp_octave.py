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
runs (232 of 293 octave onsets in a 240 s trace). The record keeps the
mask's own two-and-two, and a note on a row whose CMD_SETTEMPO makes the
step longer names a copy built at the row's tempo over its passing calls
(the tempo split, tested at the end of this file). The tests below pin the
readers, the shape against a
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
    # A GATED counter counts the calls that PASS the gate -- the gate's RTS
    # skips the sequencer too -- and its reset reads like any other: base 0
    # in both. Through v0.5.490 these two read None and took residue 0.
    for name in ("Game_Killer", "Rasputin"):
        sid, det = _det(CORPUS / f"{name}.sid")
        assert fixed_arp_counter_gated(sid, det), name
        assert fixed_arp_counter_base(sid, det) == 0, name
    for name in ("Zoids", "Chimera", "Commando", "Hunter_Patrol"):
        sid, det = _det(CORPUS / f"{name}.sid")
        assert not fixed_arp_counter_gated(sid, det), name
    # The no-reset shape under a duty mask: Battle_of_Britain's `$841F` byte
    # is $DC and nothing stores it, so frame k reads $DD + k.
    sid, det = _det(CORPUS / "Battle_of_Britain.sid")
    assert not fixed_arp_counter_gated(sid, det)
    assert fixed_arp_counter_base(sid, det) == 0xDD
    assert fixed_arp_first_fetch(sid, det) == 0


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


# ---------------------------------------------------------------------------
# A gated counter counts the calls that pass the gate (v0.5.491).
#
# Game_Killer's `$0826 DEC $0C8C / BPL / LDA #9 / STA $0C8C / RTS` skips the
# whole player one call in ten, the octave block's `INC $0C8B` and the
# sequencer alike, so the counter is the number of PASSING calls since the
# new-song reset and a row is `frames` passing calls: the residue walk is
# the ungated one in the player's own clock. Through v0.5.490
# `fixed_arp_counter_base` returned None for a gated counter, no phase was
# walked and Game_Killer and Rasputin took residue 0 -- a value that occurs
# on none of Game_Killer's attacks (they sit on 1, 3, 5 and 7). What the gate
# does change is the FRAME length of a counter step, (R + 1) / R, which is
# `_gate_calls` applied to the duty's call count: 10 of our calls at -S9.
# ---------------------------------------------------------------------------
from h2g.goatwriter import (_wavetable_entries, OUTER_GATE_RTS,  # noqa: E402
                            find_song_speeds)


def _gated_counter(sid, seconds):
    """`(c[f], gate_skip)`: what a gated, reset counter reads on each frame
    of a trace of `seconds`, the gate walked from the file's own byte."""
    m = OUTER_GATE_RTS.search(sid.data)
    assert m is not None
    ctr = m.group(1)[0] | m.group(1)[1] << 8
    reload = m.group(2)[0]
    g = sid.data[sid.to_offset(ctr)]
    n = seconds * 50 + 2
    c, cnt, started = [0] * n, 0, False
    for f in range(n):
        g -= 1
        if g < 0:                        # DEC underflows: reload, RTS
            g = reload
            c[f] = cnt
            continue
        if started:
            cnt += 1
        started = True                   # the new-song call reads 0
        c[f] = cnt
    return c, reload


def _octave_frames(trace, n):
    """(frame, is_up) for every octave-up or base frame after every octave
    onset -- the frames `fixed_arp_up` is asked about."""
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
                if is_up or x == lo:
                    yield f + k, is_up


@needs_corpus
@needs_siddump
def test_the_gated_counter_is_re_measured_against_the_original():
    """Game_Killer: every octave frame of every onset in 60 s against
    `fixed_arp_up(mask, branch, c)` with `c` the passing-call count --
    the gate byte `$0C8C` is 4 in the file and reloads 9, so frames 4, 14,
    24, ... are skipped -- and against the frame number, which the walk
    used to be refused for. The first must agree; the second must NOT,
    or the walk is not load-bearing. Battle_of_Britain beside it: the
    no-reset shape, base 221 off its `$841F` byte, ungated."""
    path = CORPUS / "Game_Killer.sid"
    sid, det = _det(path)
    assert fixed_arp_counter_gated(sid, det)
    assert fixed_arp_counter_base(sid, det) == 0
    mask, branch = fixed_arp_mask(sid, det)
    seconds = 60
    n = seconds * 50 + 2
    c, reload = _gated_counter(sid, seconds)
    assert reload == find_song_speeds(sid, det).skip_for(0) == 9
    trace = fidelity.run_siddump(path, seconds, 0, fidelity.SIDDUMP)
    frames = list(_octave_frames(trace, n))
    assert len(frames) >= 300, len(frames)
    walked = sum(fixed_arp_up(mask, branch, c[f]) != up for f, up in frames)
    as_frame = sum(fixed_arp_up(mask, branch, f) != up for f, up in frames)
    assert walked / len(frames) < 0.02, (walked, len(frames))
    assert as_frame / len(frames) > 0.2, (as_frame, len(frames))
    # The no-reset shape under the same mask, at the base read off the byte.
    path = CORPUS / "Battle_of_Britain.sid"
    sid, det = _det(path)
    base = fixed_arp_counter_base(sid, det)
    assert base == 0xDD
    trace = fidelity.run_siddump(path, seconds, 0, fidelity.SIDDUMP)
    frames = list(_octave_frames(trace, n))
    assert len(frames) >= 300, len(frames)
    at_base = sum(fixed_arp_up(mask, branch, base + f) != up for f, up in frames)
    at_zero = sum(fixed_arp_up(mask, branch, f) != up for f, up in frames)
    assert at_base / len(frames) < 0.02, (at_base, len(frames))
    assert at_zero / len(frames) > 0.1, (at_zero, len(frames))   # 81 of 405


@needs_corpus
def test_a_gated_counter_is_walked_in_passing_calls():
    """Game_Killer's records vote from residues 1, 3, 5, 7 (first fetch 1,
    rows of 2 passing calls), never 0; Rasputin's walk lands every record on
    0, which is why the corpus byte-hash that shipped this named Game_Killer
    alone; Battle_of_Britain's attacks all sit on rows a multiple of 4 and
    read 221 + 8k, residue 5, as before."""
    if not (PYTHON_ROOT.parent / "presets.json").exists():
        pytest.skip("presets.json not present")
    sid, det = _det(CORPUS / "Game_Killer.sid")
    _, tracks, patterns = _converted("Game_Killer")
    phases = fixed_arp_phases(sid, det, tracks, patterns)
    assert phases and set(phases.values()) <= {1, 3, 5, 7}, phases
    assert 0 not in phases.values()
    sid, det = _det(CORPUS / "Rasputin.sid")
    _, tracks, patterns = _converted("Rasputin")
    phases = fixed_arp_phases(sid, det, tracks, patterns)
    assert phases and set(phases.values()) == {0}, phases
    sid, det = _det(CORPUS / "Battle_of_Britain.sid")
    _, tracks, patterns = _converted("Battle_of_Britain")
    phases = fixed_arp_phases(sid, det, tracks, patterns)
    assert phases and set(phases.values()) == {5}, phases


@needs_corpus
def test_the_gated_duty_steps_once_a_passing_call():
    """A duty record at -S9 under a reload-9 gate takes the -S10 shape --
    the octave's first call is 10, `_gate_calls(9, 9)` -- and a record
    without the arpeggio bit is not touched by the gate at all."""
    sid, det = _det(CORPUS / "Game_Killer.sid")
    mask = fixed_arp_mask(sid, det)
    base = det.instr_start + 2 * det.instr_stride
    assert sid.data[base + 7] & 0x04 and not sid.data[base + 7] & 0x01

    def entries(i, multiplier, gate_skip):
        return _wavetable_entries(sid, det, i, True, "gts5", [], multiplier,
                                  budget=255, start=6, arp_phase=1,
                                  arp_mask=mask, gate_skip=gate_skip)
    gated = entries(2, 9, 9)
    assert gated == entries(2, 10, None)
    assert gated != entries(2, 9, None)
    left, right = gated
    tl = wave_timeline(left, right, first=6, calls=40)
    first_up = next(k for k, (_, _, note) in enumerate(tl) if note == 0x0C)
    assert first_up == 10, first_up
    assert entries(0, 9, 9) == entries(0, 9, None)


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


# ---------------------------------------------------------------------------
# A duty record's residue is the one that agrees on the most FRAMES.
#
# One wavetable per instrument has to stand for a residue that is per note,
# and for a duty mask the mode is the wrong reduction: over an L-frame note
# two residues sound the same wherever both their base frames fall past the
# note's end. Chimera subtune 1's instrument 15 plays six-frame notes on
# residues 0, 2, 4 and 6; the mode took 4 and put a base frame on offset 4
# of every note, which the next note's first-frame lead then held a frame
# more -- `bUUUbb` on 895 onsets in a 180 s trace, where the original
# sounds `bUUUUU` on 361, `bUbUUU` on 269 and `bUUUbU` on 267.
# `_duty_residue` takes 0: `bUUUUU` on 896, the up-fraction at offsets 4
# and 5 from 0.43 to 0.99 (original 0.80 and 0.96), and subtune 1 voice 1's
# frequency agreeing with the original's on 7987 frames of 8880 where it
# agreed on 6841 (C:/t/chimera-gk-duty/profile_180.txt and agree.py,
# measured at 924e4bd plus the working tree's uncommitted h2g/). A track's
# last note is not counted: its span is the orderlist loop's, and a
# placeholder span there once decided three Game_Killer records on one note
# each -- a byte moved, the 180 s dump identical on both sides.
#
# Two populations keep the mode. The parity mask: a residue there is all or
# nothing. And any record a toneporta row names: under `3 00` the packed
# player rewrites the pattern's note on every call on which the wavetable
# fires nothing (player.s `mt_wavedone` -> `mt_effect_3_found`), so a duty
# held by a delay entry is base from its second call -- Chimera subtune 0's
# `$0060` tie runs, where the original's octave sounds on every frame but
# the row's and the counter's own base frame. That is the reversal deficit
# (5944 -> 2853, subtune 0, the fidelity row's) and no residue reaches it:
# letting the frame count choose for those records moved voice 1's
# agreement 4406 -> 4143 frames, and firing a note on every
# call instead of holding it 4406 -> 3651. What does reach it is re-spelling
# the tie itself: see the last section of this file.
# ---------------------------------------------------------------------------
from h2g.goatwriter import _duty_residue, _majority_residues  # noqa: E402

# Chimera instrument 15, one lap of subtune 1: {(residue, frames): notes}.
CHIMERA_15 = {(0, 6): 120, (2, 6): 120, (4, 6): 180, (6, 6): 180}


def test_a_duty_residue_is_counted_in_frames_not_notes():
    """The mode of Chimera's instrument 15 is 4 (180 notes, the lower of a
    tie with 6); counted in frames it is 0, which sounds the original's own
    `bUUUUU` on residues 0 and 2 and misses one frame on each of 4 and 6."""
    counts = [0] * 8
    for (r, _), n in CHIMERA_15.items():
        counts[r] += n
    assert _majority_residues({15: counts}, 8) == {15: 4}
    assert _duty_residue(CHIMERA_15, 0x07, BEQ, 4) == 0


def test_a_frame_count_tie_keeps_the_mode():
    """Six-frame notes all on residue 2: residues 0, 1 and 2 sound the same
    `bUUUUU`, and the record keeps the residue it had -- which is what keeps
    every duty file but these two byte for byte."""
    assert _duty_residue({(2, 6): 10}, 0x07, BEQ, 2) == 2
    assert _duty_residue({(2, 6): 10}, 0x07, BEQ, 1) == 1
    assert _duty_residue({(5, 12): 3}, 0x07, BEQ, 5) == 5


@needs_corpus
def test_the_chimera_vote_counts_frames_except_under_a_tie():
    """`fixed_arp_phases` on the file: instrument 15 takes the frame
    count's 0; instruments 5 and 9, which toneporta rows name, keep the
    mode (0 and 7) where the frame count would say 4 and 0."""
    if not (PYTHON_ROOT.parent / "presets.json").exists():
        pytest.skip("presets.json not present")
    sid, det = _det(CORPUS / "Chimera.sid")
    _, tracks, patterns = _converted("Chimera")
    phases = fixed_arp_phases(sid, det, tracks, patterns)
    assert (phases.get(15), phases.get(5), phases.get(9)) == (0, 0, 7), phases


@needs_corpus
def test_the_chimera_duty_reaches_the_sng():
    """Read back by songview and played through the loop transcription:
    instrument 15's first base frame after the attack is offset 8, so a
    six-frame note sounds `buuuuu`."""
    if not (PYTHON_ROOT.parent / "presets.json").exists():
        pytest.skip("presets.json not present")
    import songview
    sng, _, _ = _converted("Chimera")
    ins = next(i for i in songview.parse_sng(sng).instruments
               if i.number == 15)
    wt = _wavetable_of(sng, 15)
    left = [l for l, _ in wt]
    right = [r for _, r in wt]
    assert _profile(left, right, 0x0C, 12,
                    start=ins.wave_ptr) == "buuuuuuubuuu"


# ---------------------------------------------------------------------------
# The tie itself, re-spelled (`goatwriter._legato_duty_ties`).
#
# No residue reaches the tie runs above because the `3 00` is what drops the
# octave, so the tie goes: each tied row on a duty record names a LEGATO
# variant of it -- gatetimer bit $40 (no gate-off, no hard restart at the
# fetch), firstwave $00 (no waveform, gate untouched), no pulse or filter
# pointer -- whose wave pointer restarts a duty block unrolled from the
# row's own counter residue, entered through a prefix writing the record's
# waveform with the gate on. The row after it latches the source again.
# Chimera subtune 0 at 180 s against the working tree it was cut from:
# reversals 2853 -> 4433 of the original's 5944 (the `$0060` tie runs 1143
# -> 2030 of 2763), voice 1's frequency agreeing on 6419 frames of 8880
# where it agreed on 4406, `gate` 0.655 -> 0.752, melody, attacks and
# `wave` unmoved (C:/t/chimera-gk-duty/lg/). -S1 only: gt2reloc's multispeed
# build misclassifies the first legato record (see the goatwriter comment).
# ---------------------------------------------------------------------------
from h2g.goatwriter import _duty_tie_sites                    # noqa: E402


def _pitch_from(wt, ptr, calls):
    """(waveform, note) per call from 1-based row `ptr` of a whole
    wavetable: `test_call_rate.wave_timeline`'s loop with a start pointer,
    which a block entered through a jump needs (its rows lie before it)."""
    wavetime, cur_wave, cur_note, out = 0, None, None, []
    for _ in range(calls):
        left, right = wt[ptr - 1]
        if left > 0x0F:
            if left < 0xE0:
                cur_wave = left
        elif wavetime != left:
            wavetime += 1
            out.append((cur_wave, cur_note))
            continue
        wavetime = 0
        ptr += 1
        if wt[ptr - 1][0] == 0xFF:
            ptr = wt[ptr - 1][1]
        if right != 0x80:
            cur_note = right
        out.append((cur_wave, cur_note))
    return out


def _legato(song):
    return {i.number: i for i in song.instruments if i.gatetimer & 0x40}


@needs_corpus
def test_a_chimera_tie_restarts_on_a_legato_variant():
    """Every legato record is its source's envelope with the legato fields,
    and no row naming one carries a command -- the `3 00` is gone."""
    if not (PYTHON_ROOT.parent / "presets.json").exists():
        pytest.skip("presets.json not present")
    import songview
    sng, _, _ = _converted("Chimera")
    song = songview.parse_sng(sng)
    legato = _legato(song)
    assert legato
    for ins in legato.values():
        assert (ins.firstwave, ins.pulse_ptr, ins.filt_ptr) == (0, 0, 0)
        assert any((src.ad, src.sr, src.gatetimer | 0x40)
                   == (ins.ad, ins.sr, ins.gatetimer)
                   for src in song.instruments if src.number not in legato)
    named = [p[k:k + 4] for p in song.patterns for k in range(0, len(p), 4)
             if p[k + 1] in legato]
    assert len(named) > 500, len(named)          # 526 at the measurement
    assert all(row[2] == 0 and row[3] == 0 for row in named)


@needs_corpus
def test_every_legato_row_plays_its_own_residue():
    """Each re-spelled row's program, played from its variant's pointer:
    frame 0 writes the record's waveform with the gate and sounds the base,
    and every frame after it is the octave the counter names on the row's
    own residue -- the profile an attacked note on that residue sounds."""
    if not (PYTHON_ROOT.parent / "presets.json").exists():
        pytest.skip("presets.json not present")
    import songview
    sid, det = _det(CORPUS / "Chimera.sid")
    sng, tracks, patterns = _converted("Chimera")
    song = songview.parse_sng(sng)
    legato = _legato(song)
    wt = song.tables["WTBL"]
    checked = 0
    for (b, r), plays in _duty_tie_sites(sid, det, tracks, patterns).items():
        variant = song.patterns[b][r + 1]
        if variant not in legato:
            continue
        residues = [res for _, res in plays]
        residue = max(range(8), key=lambda c: (residues.count(c), -c))
        got = _pitch_from(wt, legato[variant].wave_ptr, 16)
        assert got[0][0] & 0x01 and got[0][0] & 0xF0, (b, r, got[0])
        prof = "".join("u" if note == 0x0C else "b" for _, note in got)
        assert prof == _expected(0x07, BEQ, residue, 16, 1), (b, r, residue)
        checked += 1
    assert checked > 500, checked


@needs_corpus
def test_no_attacked_note_plays_a_legato_variant():
    """The instrument column is sticky, so a variant left latched would turn
    the next attacked note legato. Walked over every orderlist in play
    order: a note whose own column is empty never finds one latched, and no
    pattern ends on one."""
    if not (PYTHON_ROOT.parent / "presets.json").exists():
        pytest.skip("presets.json not present")
    import songview
    sng, _, _ = _converted("Chimera")
    song = songview.parse_sng(sng)
    legato = _legato(song)
    assert legato
    for track in song.tracks:
        current, operand = 0, False
        for b in track:
            if operand:
                operand = False
                continue
            if b == 0xFF:
                operand = True
                continue
            if b >= 0xD0 or b >= len(song.patterns):
                continue
            pat = song.patterns[b]
            for k in range(0, len(pat), 4):
                if pat[k] == 0xFF:
                    break
                if pat[k + 1]:
                    current = pat[k + 1]
                elif 0x60 <= pat[k] <= 0xBC:
                    assert current not in legato, (b, k // 4, current)
            assert current not in legato, (b, "pattern ends latched")


@needs_corpus
def test_the_legato_ties_stay_ties_above_s1():
    """One_Man_and_his_Droid packs at -S2 and has a duty tie row: it keeps
    its `3 00`, and the song carries no legato record."""
    if not (PYTHON_ROOT.parent / "presets.json").exists():
        pytest.skip("presets.json not present")
    import songview
    sng, _, _ = _converted("One_Man_and_his_Droid")
    song = songview.parse_sng(sng)
    assert not _legato(song)
    assert any(p[k + 2] == 0x03 and p[k + 3] == 0 and 0x60 <= p[k] <= 0xBC
               for p in song.patterns for k in range(0, len(p), 4))


# ---------------------------------------------------------------------------
# The per-note split (METHOD 7.bbbbbb).
#
# One wavetable per instrument has to stand for a residue that is per note.
# Where a record's notes land on several residues about equally (each within
# `ARP_SPLIT_RATIO` of its commonest) the record gets a copy per residue --
# everything but the wave pointer -- and every non-tie note names the copy
# its own attack selects, per pattern PLAY (a pattern played at two offsets
# is two renditions). Measured at 26111a5 (v0.5.494) plus the working
# tree's uncommitted h2g/ (C:/t/per-note-split-unticked): Hunter_Patrol's
# offset-1 up-fraction 0.32 -> 0.40 against the original's 0.40 (180 s, 561
# octave onsets, prof2_HP_180.txt), every one of its 697 arp notes on the
# octave entry its residue names where 463 were; Game_Killer's
# reversal_ratio at -t 60 0.234 -> 0.527, melody 1.00 both sides
# (fid2_GK_*.json); Chimera subtune 1 voice 3 bUbUUUUUUUbb -> the
# original's bUUUUUbUUUUU on 187 of 187 onsets (prof2_Chimera_voice.txt).
# The corpus byte-hash moves exactly the six files the split fires on
# (hash2.txt).
# ---------------------------------------------------------------------------
from h2g.goatwriter import (_arp_lap_walk, _share_loop_tail,  # noqa: E402
                            _split_arp_orderlists, _fixed_arp_clock,
                            ARP_SPLIT_RATIO, GT_FIRST_NOTE, GT_LAST_NOTE,
                            CMD_TONEPORTA)

SPLIT_FILES = {"Chimera", "Game_Killer", "Human_Race", "Hunter_Patrol", "Rasputin",
               "One_Man_and_his_Droid", "Zoids"}


class _Speeds:
    def __init__(self, frames):
        self.frames = frames

    def frames_for(self, subtune):
        return self.frames


def _pattern(*rows):
    out = []
    for note, instr in rows:
        out += [note, instr, 0, 0]
    return out + [0xFF, 0, 0, 0]


def test_a_loop_off_the_cycle_is_walked_until_it_returns():
    """Game_Killer's voice 3 is one 18-row pattern looping at two calls a
    row: 36 counter steps, 4 off a multiple of 8, so the loop is walked
    twice. A 16-row loop is a whole cycle and is walked once; a prefix
    before the restart position is played once."""
    eighteen = [0x60, 1, 0, 0] * 18 + [0xFF, 0, 0, 0]
    walk = _arp_lap_walk([0, 0xFF, 0], [eighteen], 2, 8)
    assert [(p, lap) for p, lap, _, _ in walk] == [(0, 0), (0, 1)]
    sixteen = [0x60, 1, 0, 0] * 16 + [0xFF, 0, 0, 0]
    assert len(_arp_lap_walk([0, 0xFF, 0], [sixteen], 2, 8)) == 1
    three = [0x60, 1, 0, 0] * 3 + [0xFF, 0, 0, 0]
    walk = _arp_lap_walk([0, 1, 0xFF, 1], [three, three], 1, 2)
    assert [(p, lap) for p, lap, _, _ in walk] == [(0, 0), (1, 0), (1, 1)]


def test_the_split_renames_each_play_for_its_own_residue():
    """Parity mask, one frame a row, base and first fetch 0. Pattern 0 is
    one row: a note on instrument 1. Played at rows 0 and 1 it sounds on
    residues 0 and 1, so the second play needs the copy (instrument 5) and
    becomes a new pattern; the `D1` repeat is unrolled around the
    transpose, and the restart operand follows its entry."""
    clock = (0, 0, (0x01, BEQ), 2, _Speeds(1))
    pat = _pattern((0x60, 1))
    track = [0xE0, 0xD1, 0, 0xFF, 1]
    out = _split_arp_orderlists([track], [pat], clock, {1: {1: 5}})
    assert out is not None
    new_tracks, new_patterns, renamed = out
    assert renamed == 1
    assert new_patterns[0] == pat
    assert new_patterns[1][:4] == [0x60, 5, 0, 0]
    assert new_tracks[0] == [0xE0, 0, 1, 0xFF, 1]
    # a residue with no copy is left alone
    assert _split_arp_orderlists([track], [pat], clock, {1: {}}) is None
    # a tie keeps its column: the wavetable it would restart does not
    tie = [0x60, 1, CMD_TONEPORTA, 0, 0xFF, 0, 0, 0]
    assert _split_arp_orderlists([[0xD1, 0, 0xFF, 0]], [tie], clock,
                                 {1: {1: 5}}) is None


def test_the_restart_follows_its_entry():
    """A restart pointing past an unrolled repeat lands on the same
    pattern entry in the rewritten orderlist: `D2 00` (rows 0, 1, 2 on
    residues 0, 1, 0) is three entries where it was two, so the restart
    that named position 2 names position 3."""
    clock = (0, 0, (0x01, BEQ), 2, _Speeds(1))
    pat = _pattern((0x60, 1))
    two = _pattern((0x60, 2), (0x60, 2))
    out = _split_arp_orderlists([[0xD2, 0, 1, 0xFF, 2]], [pat, two], clock,
                                {1: {1: 5}})
    assert out[0][0] == [0, 2, 0, 1, 0xFF, 3]


def test_the_split_follows_the_latch_not_the_column():
    """A note with no instrument inherits the voice's latch, so a copy
    named on one row carries to the next: that row is renamed back only
    where its own residue needs the record."""
    clock = (0, 0, (0x01, BEQ), 2, _Speeds(1))
    pat = _pattern((0x60, 1), (0x60, 0), (0x60, 0), (0x60, 0))
    out = _split_arp_orderlists([[0, 0xFF, 0]], [pat], clock, {1: {1: 5}})
    _, patterns, renamed = out
    assert [patterns[0][k] for k in (1, 5, 9, 13)] == [1, 5, 1, 5]
    assert renamed == 3


def test_a_copy_jumps_into_an_identical_loop():
    """Game_Killer's duty residues differ before the cycle settles and
    share the loop after it: the copy keeps its own lead and jumps into the
    loop already in the table (a jump costs no call, gplay.c:707-711)."""
    loop = [(0x09, 0x0C), (0x0F, 0x80), (0x05, 0x00)]
    table = [(0x41, 0x00), (0x0F, 0x80)] + loop + [(0xFF, 3)]
    start = 10                             # the copy's loop starts at 12
    left = [0x41, 0x0D] + [l for l, _ in loop] + [0xFF]
    right = [0x00, 0x00] + [r for _, r in loop] + [12]
    got = _share_loop_tail((left, right), start, table)
    assert got == ([0x41, 0x0D, 0xFF], [0x00, 0x00, 3])
    # no identical loop in the table: unchanged
    assert _share_loop_tail((left, right), start, table[:2]) == (left, right)
    # a loop that is the whole block is never shared
    whole = ([l for l, _ in loop] + [0xFF], [r for _, r in loop] + [start])
    assert _share_loop_tail(whole, start, table) == whole


def _split_notes(name):
    """(song, [(record name, residue, instrument)]) for every non-tie note
    of the finished .sng's own orderlists and patterns (songview, a second
    reader), loops unrolled."""
    import songview
    sng, _, _ = _converted(name)
    s = songview.parse_sng(sng)
    sid, det = _det(CORPUS / f"{name}.sid")
    base, first, _, period, speeds = _fixed_arp_clock(sid, det, s.tracks)
    named = {i.number: i.name for i in s.instruments}
    notes = []
    for ti, track in enumerate(s.tracks):
        frames = speeds.frames_for(ti // 3)
        row, latched = 0, 0
        for _, _, b, plays in _arp_lap_walk(track, s.patterns, frames,
                                            period):
            pat = s.patterns[b]
            for _ in range(plays):
                for r in range(0, len(pat) - len(pat) % 4, 4):
                    if pat[r] == 0xFF:
                        break
                    if pat[r + 1]:
                        latched = pat[r + 1]
                    if (latched and GT_FIRST_NOTE <= pat[r] <= GT_LAST_NOTE
                            and pat[r + 2] != CMD_TONEPORTA):
                        res = (base + first + row * frames) % period
                        notes.append((named[latched], res, latched))
                    row += 1
    return s, notes


@needs_corpus
def test_hunter_patrol_notes_sit_on_their_residues_octave():
    """Every non-tie note on a fixed-arp record plays the entry its own
    residue names (`unticked_arp_octave_entry`): 697 of 697, where the
    per-instrument vote had 463."""
    if not (PYTHON_ROOT.parent / "presets.json").exists():
        pytest.skip("presets.json not present")
    s, notes = _split_notes("Hunter_Patrol")
    wt = s.tables["WTBL"]
    ptr = {i.number: i.wave_ptr for i in s.instruments}

    def octave(n):
        for j in range(3):
            left, right = wt[ptr[n] - 1 + j]
            if left == 0xFF:
                return None
            if right == OCTAVE:
                return j
        return None
    agree = miss = 0
    for _, res, instr in notes:
        if octave(instr) is None:
            continue
        if octave(instr) == unticked_arp_octave_entry(res):
            agree += 1
        else:
            miss += 1
    assert (agree, miss) == (697, 0)


@needs_corpus
def test_game_killer_names_one_copy_per_residue():
    """The melodic records 3 and 7 and voice 3's record 6 play one
    instrument per residue, a different one on each of 1, 3, 5 and 7, and
    voice 3's one-pattern loop is unrolled to two laps in the orderlist."""
    if not (PYTHON_ROOT.parent / "presets.json").exists():
        pytest.skip("presets.json not present")
    s, notes = _split_notes("Game_Killer")
    by_record = {}
    for name, res, instr in notes:
        by_record.setdefault(name, {}).setdefault(res, set()).add(instr)
    for name, m in by_record.items():
        for res, instrs in m.items():
            assert len(instrs) == 1, (name, res, instrs)
    split = {n: m for n, m in by_record.items()
             if len(set().union(*m.values())) > 1}
    assert len(split) == 3, by_record
    for m in split.values():
        assert sorted(m) == [1, 3, 5, 7], m
        assert len(set().union(*m.values())) == 4, m
    body = [b for b in s.tracks[2][:-2] if b < 0xD0]
    assert len(body) == 2 and body[0] != body[1], s.tracks[2]


@needs_corpus
def test_the_split_fires_on_exactly_the_split_files():
    """The census the corpus byte-hash was checked against: of the fixed
    arp files, exactly these seven log a split under their presets --
    Rasputin by the tempo split alone."""
    if not (PYTHON_ROOT.parent / "presets.json").exists():
        pytest.skip("presets.json not present")
    import json
    import h2g.convert as C
    doc = json.loads((PYTHON_ROOT.parent / "presets.json").read_text())
    fired = set()
    for p in sorted(CORPUS.glob("*.sid")):
        if p.name not in doc["songs"] or not _det(p)[1].arp_fixed_up:
            continue
        lines = []
        C.convert(str(p), log=lines.append,
                  **fidelity._preset_opts(doc, p.name))
        if any("Per-note arp split" in m for m in lines):
            fired.add(p.stem)
    assert fired == SPLIT_FILES
    assert ARP_SPLIT_RATIO == 2


@needs_corpus
def test_chimera_copies_are_their_source_but_the_wave_pointer():
    """Chimera also carries legato variants (numbered after the rest
    variants), so the copies are numbered after both: each copy the log
    names is its source's record with only the wave pointer changed. And
    record 4 -- residue 6 in subtune 0, residue 2 in subtune 1, where
    voice 3 sounded bUbUUUUUUUbb against the original's bUUUUUbUUUUU on
    187 onsets before the split -- names one instrument per residue."""
    if not (PYTHON_ROOT.parent / "presets.json").exists():
        pytest.skip("presets.json not present")
    import dataclasses
    import json
    import re
    import songview
    import h2g.convert as C
    doc = json.loads((PYTHON_ROOT.parent / "presets.json").read_text())
    lines = []
    sng = C.convert(str(CORPUS / "Chimera.sid"), log=lines.append,
                    **fidelity._preset_opts(doc, "Chimera.sid"))
    s = songview.parse_sng(sng)
    split = [m for m in lines if "Per-note arp split" in m]
    assert len(split) == 1, lines
    pairs = [(int(c, 16), int(src, 16)) for c, src in
             re.findall(r"\$([0-9A-F]+) \(of \$([0-9A-F]+)\)", split[0])]
    assert pairs and (0x28, 0x4) in pairs, split
    by = {i.number: i for i in s.instruments}
    for copy, src in pairs:
        a = dataclasses.replace(by[copy], number=0, wave_ptr=0)
        b = dataclasses.replace(by[src], number=0, wave_ptr=0)
        assert a == b, (copy, src)
        assert by[copy].wave_ptr != by[src].wave_ptr, (copy, src)
    _, notes = _split_notes("Chimera")
    four = {}
    for name, res, instr in notes:
        if name == by[4].name:
            four.setdefault(res, set()).add(instr)
    assert set(four) == {2, 6}, four
    assert all(len(v) == 1 for v in four.values()), four
    assert four[2] != four[6], four


# --- The tempo split: a gated duty follows the row's tempo -----------------
#
# Rasputin's counter steps once a PASSING call of a gate whose reload is the
# track's `$FE nn` tempo, so its `$02` duty half is one row at every tempo:
# three frames and three at the opening's reload 2, where the record's one
# wavetable sounded two and two. Measured before the split (per-onset
# profile, 30 s of subtune 0, C:/t/rasputin-tempo-duty/profile_base.txt):
# the original `bbbuuubbbuuubbbuu` on 12 of 17 octave onsets and 3:3 on the
# rest, ours `bbuubbuubbuubbuub` on 15 of 17 and 2:2 on the rest; after it
# (profile_edit.txt) ours `bbbuuubbbuuubbbuu` on 13 of 17 and 3:3 on 15, the
# other two the `$FE 03` rows' 2.5-frame half. `--vice -t 30`: vib 3.61x ->
# 3.09x, tie 1.18x -> 1.07x, every sequence column unchanged.

from fractions import Fraction                               # noqa: E402

from h2g.goatwriter import (_duty_tempo_calls,               # noqa: E402
                            _track_tempo_events, CMD_SETTEMPO)


def _halves(left, right, first, calls, skip=12):
    """Run lengths, in calls, of the octave state past the first `skip`
    calls -- the partial runs at either end dropped."""
    notes = [n for _, _, n in wave_timeline(left, right, first=first,
                                            calls=calls)][skip:]
    runs, n = [], 1
    for a, b in zip(notes, notes[1:]):
        if a == b:
            n += 1
        else:
            runs.append(n)
            n = 1
    return runs[1:]


@pytest.mark.parametrize("phase", range(4))
def test_a_whole_fractional_step_is_the_integer_shape(phase):
    """`Fraction(3)` calls a step is the -S3 shape byte for byte."""
    a = fixed_arp_duty_entries(0x41, 0x41, 0x02, BEQ, phase, 0x0C, 3,
                               start=6, budget=255)
    b = fixed_arp_duty_entries(0x41, 0x41, 0x02, BEQ, phase, 0x0C,
                               Fraction(3), start=6, budget=255)
    assert a is not None and a == b


@pytest.mark.parametrize("phase", range(4))
@pytest.mark.parametrize("tempo", [4, 5, 6])
def test_the_duty_half_is_the_row_at_every_tempo(phase, tempo):
    """Rasputin's rows are 2 passing calls, so a step is `tempo / 2` of our
    calls and the `$02` half -- two steps -- is exactly `tempo` calls,
    including the `$FE 03`/`$FE 05` rows' 5, which is 2.5 a step."""
    left, right = fixed_arp_duty_entries(0x41, 0x41, 0x02, BEQ, phase, 0x0C,
                                         Fraction(tempo, 2), start=6,
                                         budget=255)
    assert left[-1] == 0xFF
    runs = _halves(left, right, 6, 120)
    assert runs and set(runs) == {tempo}, runs


def test_a_step_whose_period_is_not_whole_calls_is_declined():
    """A loop of one period must end on a call: 4 steps of 7/3 is 28/3."""
    assert fixed_arp_duty_entries(0x41, 0x41, 0x02, BEQ, 0, 0x0C,
                                  Fraction(7, 3), start=6, budget=255) is None


def _pat(*rows):
    out = []
    for note, cmd, arg in rows:
        out += [note, 0, cmd, arg]
    return out + [0xFF, 0, 0, 0]


def test_the_tempo_timeline_follows_the_orderlist_loop():
    """Rows are counted through repeats (`$D0+n`) and round the loop from
    the restart position, as far as the horizon asks."""
    pats = [_pat((0x60, 0, 0), (0x60, 0, 0)),
            _pat((0x60, CMD_SETTEMPO, 6), (0x60, 0, 0)),
            _pat((0x60, CMD_SETTEMPO, 0x84))]
    track = [0x01, 0xD1, 0x00, 0x02, 0xFF, 0x01]
    got = _track_tempo_events(track, pats, 14)
    # 0: pattern 1 (2 rows), 2-5: pattern 0 twice, 6: pattern 2, then the
    # loop restarts at position 1 (the repeat) -> 7-10, 11: pattern 2 ...
    assert got == [(0, 6), (6, 0x84), (11, 0x84)], got
    assert _track_tempo_events([0x00, 0xFF, 0x00], [[0xFF, 0, 0, 0]],
                               10) == []           # a loop of no rows ends


@needs_corpus
def test_only_a_gated_counter_follows_the_tempo():
    """Rasputin's gated counter reads a step per tempo; Zoids' ungated one
    names none whatever its patterns say."""
    if not (PYTHON_ROOT.parent / "presets.json").exists():
        pytest.skip("presets.json not present")
    from h2g.goatwriter import _fixed_arp_clock
    sid, det = _det(CORPUS / "Rasputin.sid")
    _, tracks, patterns = _converted("Rasputin")
    clock = _fixed_arp_clock(sid, det, tracks)
    calls = _duty_tempo_calls(sid, det, tracks, patterns, clock, Fraction(2))
    assert calls is not None
    assert calls(0, 0) == Fraction(3)          # `$FE 02`: 6 calls a row
    assert calls(1, 0) == Fraction(3)          # a voice with no tempo of its own
    sid, det = _det(CORPUS / "Zoids.sid")
    _, tracks, patterns = _converted("Zoids")
    clock = _fixed_arp_clock(sid, det, tracks)
    assert not fixed_arp_counter_gated(sid, det)
    assert _duty_tempo_calls(sid, det, tracks, patterns, clock, 2) is None


def _instrument_halves(song, number, calls=160):
    """`_halves` of instrument `number`'s program, read out of the whole
    wavetable (a copy's loop may jump into an earlier copy's)."""
    wt = [tuple(e) for e in song.tables["WTBL"]]
    ptr = next(i for i in song.instruments if i.number == number).wave_ptr
    n = len(wt)
    rot = wt[ptr - 1:] + wt[:ptr - 1]          # entry `ptr` first

    def moved(i):
        return i if i >= ptr else i + n
    left = [l for l, _ in rot]
    right = [moved(r) if l == 0xFF else r for l, r in rot]
    return _halves(left, right, ptr, calls)


@needs_corpus
def test_rasputin_s_opening_duty_is_three_and_three():
    """Every note of the opening's first pattern names a copy whose octave
    half is 6 calls -- three frames at -S2 -- while its source record keeps
    the 4-call half the `$FE 78` rows play."""
    if not (PYTHON_ROOT.parent / "presets.json").exists():
        pytest.skip("presets.json not present")
    import json
    import re
    import songview
    import h2g.convert as C
    doc = json.loads((PYTHON_ROOT.parent / "presets.json").read_text())
    lines = []
    sng = C.convert(str(CORPUS / "Rasputin.sid"), log=lines.append,
                    **fidelity._preset_opts(doc, "Rasputin.sid"))
    s = songview.parse_sng(sng)
    split = [m for m in lines if "Per-note arp split" in m]
    assert len(split) == 1, lines
    pairs = {int(c, 16): int(src, 16) for c, src in
             re.findall(r"\$([0-9A-F]+) \(of \$([0-9A-F]+)\)", split[0])}
    first = s.patterns[s.tracks[0][0]]
    named = {first[r + 1] for r in range(0, len(first) - 3, 4)
             if first[r] != 0xFF and first[r + 1]}
    duty = {i for i in named if i in pairs}
    assert duty, (named, pairs)
    for copy in duty:
        assert set(_instrument_halves(s, copy)) == {6}, copy
        assert set(_instrument_halves(s, pairs[copy])) == {4}, pairs[copy]


# ---------------------------------------------------------------------------
# The nibble dialect's period is PER RECORD (goatwriter's block above
# `NIBBLE_ARP_SELFMOD`). The bit-$04 block that subtracts the record's high
# nibble writes a mask into its own `AND` operand from the nibble -- `$02`
# (or `$04`) for the octave nibble `$0C`, `$01` for every other -- and then
# divides the same `INC`'d play-entry counter the fixed dialect does, behind
# the same outer gate. Measured on the originals (60 s, every subtune,
# interior halves in frames, C:/t/nibble-arp-period/prof_base.txt): Warhawk
# 2.29 on its octave records and 1.14 on the rest (2 x 8/7, 8/7),
# International_Karate 2.19 and 1.09 (2 x 11/10, 11/10), Formula_1_Simulator
# 4.04 on its octave -- an octave UP, its block swaps the SBC for an ADC --
# and 1.22 on the rest. Until then every nibble record alternated one step a
# half at `m` calls a step: 1.00 on every record of all three.
# ---------------------------------------------------------------------------
from h2g.goatwriter import (nibble_arp_block, nibble_arp_record,  # noqa: E402
                            outer_gate_skip)

# name -> (masks (octave, other), ADC (octave, other), zero-page counter)
NIBBLE_ARP = {
    "Warhawk": ((0x02, 0x01), (False, False), False),
    "International_Karate": ((0x02, 0x01), (False, False), False),
    "Thrust": ((0x02, 0x01), (False, False), False),
    "Bump_Set_Spike": ((0x02, 0x01), (False, False), False),
    "Kentilla": ((0x02, 0x01), (False, False), False),
    "Las_Vegas_Video_Poker": ((0x02, 0x01), (False, False), False),
    "Spellbound": ((0x02, 0x01), (False, False), True),
    "Samantha_Fox_Strip_Poker": ((0x02, 0x01), (False, False), True),
    "Proteus": ((0x04, 0x01), (False, False), False),
    "Hollywood_or_Bust": ((0x04, 0x01), (False, False), False),
    "Chicken_Song": ((0x04, 0x01), (False, False), False),
    "Formula_1_Simulator": ((0x04, 0x01), (True, False), False),
    "Mozart": ((0x01, 0x01), (False, False), False),
}


@needs_corpus
def test_the_nibble_block_reads_a_mask_per_record():
    """Every corpus file of the dialect, and no fixed-dialect file."""
    for name, (masks, up, zp) in NIBBLE_ARP.items():
        sid, det = _det(CORPUS / f"{name}.sid")
        blk = nibble_arp_block(sid, det)
        assert blk is not None, name
        assert (blk.masks, blk.up, blk.zp, blk.branch) == (masks, up, zp,
                                                           BNE), name
        octave = nibble_arp_record(blk, 0x0C)
        other = nibble_arp_record(blk, 0x05)
        assert octave[0] == masks[0] and other[0] == masks[1], name
        assert octave[2] == (0x0C if up[0] else 0x74), name
        assert other[2] == 0x7B, name                  # five semitones down
        assert nibble_arp_record(blk, 0) is None       # zero subtracts zero
    for name in FIXED_ARP:
        path = COMMANDO if name == "Commando" else CORPUS / f"{name}.sid"
        sid, det = _det(path)
        assert nibble_arp_block(sid, det) is None, name


def test_a_duty_loop_may_span_laps_where_one_period_is_not_whole_calls():
    """Thrust's step is 10/3 calls at -S3: one period of `$01` is 20/3
    calls and is declined, three are 20 and loop."""
    step = Fraction(10, 3)
    assert fixed_arp_duty_entries(0x41, 0x41, 0x01, BNE, 0, 0x74, step,
                                  start=6, budget=255) is None
    got = fixed_arp_duty_entries(0x41, 0x41, 0x01, BNE, 0, 0x74, step,
                                 start=6, budget=255, max_laps=3)
    assert got is not None
    left, right = got
    calls = 200
    notes = [n for _, _, n in wave_timeline(left, right, first=6,
                                            calls=calls)]
    for t in range(calls):
        j = max(k for k in range(t + 2) if int(k * step) <= t)
        want = 0x74 if j and fixed_arp_up(0x01, BNE, j) else 0x00
        assert (notes[t] or 0x00) == want, t


def _nibble_step(doc, name, sid):
    m = doc["songs"][name + ".sid"].get("multiplier", 1)
    r = outer_gate_skip(sid)
    return Fraction(m * (r + 1), r) if r else Fraction(m)


@needs_corpus
@pytest.mark.parametrize("name", ["Warhawk", "International_Karate",
                                  "Formula_1_Simulator", "Thrust", "Proteus"])
def test_the_nibble_records_reach_the_sng_at_their_own_period(name):
    """Each arpeggio record's program, read back by songview: its alternate
    note is its block's (Formula_1_Simulator's octave UP), and its interior
    halves average its mask's steps at the exact `m (R + 1) / R` calls a
    step, each within one call of it."""
    if not (PYTHON_ROOT.parent / "presets.json").exists():
        pytest.skip("presets.json not present")
    import json
    import songview
    doc = json.loads((PYTHON_ROOT.parent / "presets.json").read_text())
    sid, det = _det(CORPUS / f"{name}.sid")
    step = _nibble_step(doc, name, sid)
    opts = fidelity._preset_opts(doc, f"{name}.sid")
    lead = 0 if opts.get("compact_instruments") else 1
    sng, _, _ = _converted(name)
    s = songview.parse_sng(sng)
    checked = {}
    for ins in s.instruments:
        i = ins.number - lead - 1
        base = det.instr_start + i * det.instr_stride
        if i < 0 or base + 8 > len(sid.data) or not sid.data[base + 7] & 4:
            continue
        nibble = sid.data[base + 7] >> 4
        if not nibble:
            continue
        # From the table above, not the reader under test.
        masks, up, _ = NIBBLE_ARP[name]
        k = 0 if nibble == 0x0C else 1
        mask = masks[k]
        rel = (nibble if up[k] else 0x80 - nibble) & 0xFF
        assert rel in {r for _, r in _wavetable_of(sng, ins.number)}, \
            ins.number
        half = step * fixed_arp_period(mask) / 2
        runs = _instrument_halves(s, ins.number, calls=int(half * 24))
        assert runs, ins.number
        assert abs(Fraction(sum(runs), len(runs)) - half) <= Fraction(1, 2), \
            (ins.number, runs, half)
        assert all(abs(r - half) < 1 for r in runs), (ins.number, runs, half)
        checked[mask] = checked.get(mask, 0) + 1
    assert len(checked) == 2, checked             # both periods reached


def _nibble_halves(trace, n):
    """{semitones: interior half lengths in frames} over every onset."""
    import math
    out = {}
    for v in trace:
        t = _timeline(v, n)
        at = v.attack_frames
        for k, f in enumerate(at):
            end = at[k + 1] if k + 1 < len(at) else n
            seg = t[f:min(end, f + 25)]
            if len(seg) < 4 or not seg[0]:
                continue
            others = [x for x in seg[1:] if x and x != seg[0]]
            if not others:
                continue
            lo = max(set(others), key=others.count)
            st = 12 * math.log2(seg[0] / lo)
            if abs(st - round(st)) > 0.2 or not 0 < abs(round(st)) <= 15:
                continue
            shape = ["H" if x == seg[0] else "a" if x == lo else "."
                     for x in seg]
            if "." in shape[:6]:
                continue
            runs, j = [], 0
            while j < len(shape):
                e = j
                while e < len(shape) and shape[e] == shape[j]:
                    e += 1
                runs.append((shape[j], e - j))
                j = e
            out.setdefault(round(st), []).extend(
                r for c, r in runs[1:-1] if c != ".")
    return out


@needs_corpus
@needs_siddump
@pytest.mark.parametrize("name,octave", [("Warhawk", 12),
                                         ("International_Karate", 12),
                                         ("Formula_1_Simulator", None)])
def test_the_nibble_period_is_re_measured_against_the_original(name, octave):
    """The originals' interior halves, subtune 0, 60 s: the octave records
    at the octave mask's steps and every other interval at the `$01`
    mask's, a step `(R + 1) / R` frames -- within 0.1 frame of the mean.

    Formula_1_Simulator's octave records are checked on the conversion
    only (`..._reach_the_sng_...`): its notes are ten frames long and its
    `$04` mask's first half after the attack is cut short by the attack
    frame itself, so no whole octave half is ever interior (4.04 frames,
    `HaaaaHHHHH` on 200 of 205 onsets, which the conversion reproduces
    exactly -- C:/t/nibble-arp-period/prof_edit3.txt)."""
    sid, det = _det(CORPUS / f"{name}.sid")
    blk = nibble_arp_block(sid, det)
    r = outer_gate_skip(sid)
    step = (r + 1) / r
    seconds = 60
    trace = fidelity.run_siddump(CORPUS / f"{name}.sid", seconds, 0,
                                 fidelity.SIDDUMP)
    halves = _nibble_halves(trace, seconds * 50 + 2)
    assert octave is None or octave in halves, sorted(halves)
    for semis, runs in halves.items():
        if len(runs) < 20 or (octave is None and abs(semis) == 12):
            continue
        mask = blk.masks[0] if semis == octave else blk.masks[1]
        want = step * fixed_arp_period(mask) / 2
        assert abs(sum(runs) / len(runs) - want) < 0.1, (semis, want,
                                                          runs[:20])


# ---------------------------------------------------------------------------
# Formula_1_Simulator's reversal_ratio doubled at v0.5.489 (0.74 -> 2.10 in
# build/fidelity.json, subtune 0, -t 180) when `ticked_arp_entries` took over
# the ticked records above -S1. The cause, from the per-offset octave profile
# of subtune 0 (C:/t/f1-ticked-reversal/prof_F1_sub0.txt): the ticked shape
# held each half for `m` calls -- ONE frame at -S2 -- and put the attack note
# on the octave, `UUUbUbUbUb` on 625 of 719 onsets, where the original holds
# its `$04` mask's two steps of 2.5 frames and starts on the base note,
# `bUUUUbbbbb` on 516 of 611. It was never the ticked shape's own period:
# the nibble dialect's period was not read at all. Since the per-record mask
# (`nibble_arp_record`, the self-modified AND) every nibble record takes
# `fixed_arp_duty_entries` BEFORE the ticked shape is consulted, and the
# conversion reads `bUUUUbbbbb` at every offset 0-9 and reversal_ratio 1.02
# (4279 / 4193) with Last_V8 (5214 / 6144) and Monty_on_the_Run
# (5669 / 6084) unmoved. The two tests below pin both halves of that.
# ---------------------------------------------------------------------------
NIBBLE_TICK_FILES = ("Formula_1_Simulator", "Warhawk", "International_Karate",
                     "Thrust", "Proteus", "Spellbound", "Bump_Set_Spike")


@needs_corpus
def test_no_nibble_record_reaches_the_ticked_shape(monkeypatch):
    """Every record whose nibble the dialect reads is routed away from
    `ticked_arp_entries`, whose `m`-call half is the period no nibble record
    plays; and Formula_1_Simulator's records all take the per-record duty
    shape. Before the nibble route existed these seven files sent 55
    records through the ticked shape, six of them Formula_1_Simulator's
    (C:/t/f1-ticked-reversal/census_prenibble.txt); none since
    (census_cur.txt)."""
    import json
    import h2g.goatwriter as G
    from h2g.convert import convert
    doc = json.loads((PYTHON_ROOT.parent / "presets.json").read_text())
    state, seen = {}, {}
    real_we, real_rec = G._wavetable_entries, G.nibble_arp_record
    real_tick, real_duty = G.ticked_arp_entries, G.fixed_arp_duty_entries

    def we(*a, **k):
        state.clear()
        try:
            return real_we(*a, **k)
        finally:
            if state.get("nib") is not None:
                key = ("ticked" if "ticked" in state else
                       "duty" if state.get("duty") else "other")
                seen[cur][key] = seen[cur].get(key, 0) + 1
            state.clear()

    def rec(*a, **k):
        state["nib"] = real_rec(*a, **k)
        return state["nib"]

    def tick(*a, **k):
        state["ticked"] = True
        return real_tick(*a, **k)

    def duty(*a, **k):
        r = real_duty(*a, **k)
        if state.get("nib") is not None:
            state["duty"] = state.get("duty") or r is not None
        return r

    monkeypatch.setattr(G, "_wavetable_entries", we)
    monkeypatch.setattr(G, "nibble_arp_record", rec)
    monkeypatch.setattr(G, "ticked_arp_entries", tick)
    monkeypatch.setattr(G, "fixed_arp_duty_entries", duty)
    for cur in NIBBLE_TICK_FILES:
        seen[cur] = {}
        convert(str(CORPUS / f"{cur}.sid"), log=lambda m: None,
                **fidelity._preset_opts(doc, f"{cur}.sid"))
    assert all(v for v in seen.values()), seen      # the spy saw records
    assert not any(v.get("ticked") for v in seen.values()), seen
    f1 = seen["Formula_1_Simulator"]
    assert f1.get("duty") and set(f1) == {"duty"}, f1


def _octave_up_fraction(trace, n, offsets=13):
    """(octave onsets, fraction of them an octave up at each offset from the
    attack) -- the per-offset profile of
    C:/t/ticked-fixed-arp-at-s2-is-a-/profile_ab.py."""
    rows = []
    for v in trace:
        t = _timeline(v, n)
        at = v.attack_frames
        for k, f in enumerate(at):
            end = at[k + 1] if k + 1 < len(at) else n
            seg = t[f:min(end, f + offsets)]
            if not seg or not seg[0]:
                continue
            lo = min(x for x in seg if x)
            if not any(x and abs(x / lo - 2) < 0.02 for x in seg):
                continue
            rows.append([bool(x and abs(x / lo - 2) < 0.02) for x in seg])
    frac = []
    for k in range(offsets):
        have = [r[k] for r in rows if len(r) > k]
        frac.append(sum(have) / len(have) if have else None)
    return len(rows), frac


@needs_corpus
@needs_siddump
def test_formula_1_s_octave_hold_is_re_measured_through_the_packer(tmp_path):
    """Formula_1_Simulator's conversion, packed at its multiplier and traced
    at it, against the original: subtune 0, 60 s. The octave onsets match in
    number, the up-fraction matches at every offset 0-9 (the original's
    `bUUUUbbbbb`; offset 10 onwards is the few notes longer than ten frames),
    and the pitch reversal rate -- the `vib` column that read 2.10x -- is
    within 20% in log space. Measured 205 / 205 onsets and 1.08x (730 / 673)
    here; the pre-nibble converter read 267 onsets, `UUUbUbUbUb` and 3.20x
    over the same 60 s (C:/t/f1-ticked-reversal/probe_cur.txt, probe_pre.txt)."""
    import json
    import math
    from h2g.convert import convert
    if not pathlib.Path(fidelity.GT2RELOC).exists():
        pytest.skip("no gt2reloc on this machine")
    doc = json.loads((PYTHON_ROOT.parent / "presets.json").read_text())
    path = CORPUS / "Formula_1_Simulator.sid"
    opts = fidelity._preset_opts(doc, path.name)
    mult = doc["songs"][path.name]["multiplier"]
    cal, _ = fidelity.table_calibration(path, opts)
    sng, _ = fidelity.legalise_restarts(
        convert(str(path), log=lambda m: None, **opts))
    packed = fidelity.pack_sid(sng, tmp_path, fidelity.GT2RELOC, mult)
    assert packed is not None
    seconds = 60
    n = seconds * 50 + 2
    a = fidelity.run_siddump(path, seconds, 0, fidelity.SIDDUMP, cal)
    b = fidelity.run_siddump(packed, seconds, 0, fidelity.SIDDUMP, calls=mult)
    na, fa = _octave_up_fraction(a, n)
    nb, fb = _octave_up_fraction(b, n)
    assert na >= 150 and abs(nb - na) <= 0.05 * na, (na, nb)
    assert fa[:10] == [0, 1, 1, 1, 1, 0, 0, 0, 0, 0], fa      # the original
    assert all(abs(x - y) <= 0.05 for x, y in zip(fa[:10], fb[:10])), (fa, fb)
    ratio = fidelity.pitch_motion_compare(a, b, n)["reversal_ratio"]
    assert ratio and abs(math.log(ratio)) < math.log(1.2), ratio
