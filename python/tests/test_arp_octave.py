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
    # The jump is absolute: `$12` is this record's start (14) + 4, the entry
    # after the tick. It was `$11` while instrument 1's drum lacked the
    # one-frame hold before its sweep (test_drum_sweep_gate_skip), which
    # moved every later record down one entry.
    assert _wavetable_of(sng, 2) == [
        (0x41, 0x00), (0x41, 0x00), (0x81, 0x0C), (0x81, 0x0C),
        (0x40, 0x00), (0x40, 0x80), (0x40, 0x0C), (0x40, 0x80), (0xFF, 0x12)]
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


# --- Rasputin's duty follows its tempo (v0.5.494+, `tempo_duty_split_plan`) --
#
# Rasputin's outer gate reloads from the cell its track's `$FE nn` writes,
# so the `$02` mask's counter step is (R + 1) / R frames with R moving:
# measured at -t 30 (C:/t/rasputin-tempo-duty/measure_duty.py) the original's
# opening sounds `bbbuuubbbuuu` on 14 of 16 voice-0 octave onsets and the
# unsplit conversion `bbuubbuubbuu` on all 16. The split gives the notes
# played at tempo 6 (= R 2, 3 frames a row at -S2) a clone stepping 3 calls,
# and leaves every other note on its record.

from h2g.goatwriter import (CMD_SETTEMPO, CMD_TONEPORTA,      # noqa: E402
                            SongSpeeds, apply_tempo_duty_edits,
                            tempo_duty_split_plan)


@needs_corpus
def test_a_clone_steps_its_own_calls_a_counter_step():
    """`arp_step_calls` replaces `_gate_calls(multiplier, gate_skip)` in the
    duty call and nothing else: Rasputin's GT 7 at -S2 with 3 calls a step
    sounds three frames base and three up (first octave call 6)."""
    sid, det = _det(CORPUS / "Rasputin.sid")
    mask = fixed_arp_mask(sid, det)

    def entries(step):
        return _wavetable_entries(sid, det, 6, True, "gts5", [], 2,
                                  budget=255, start=6, arp_phase=0,
                                  arp_mask=mask, arp_step_calls=step)
    assert entries(None) == entries(2)
    left, right = entries(3)
    tl = wave_timeline(left, right, first=6, calls=40)
    ups = [k for k, (_, _, note) in enumerate(tl) if note == 0x0C]
    assert ups[:7] == [6, 7, 8, 9, 10, 11, 18], ups[:8]


@needs_corpus
def test_rasputin_splits_its_opening_by_tempo():
    """Read back by songview (a second reader): every note of a duty record
    played under tempo 6 sounds that record's clone and every other note
    sounds the record -- 30 notes of GT 7 and 1 of GT 14 -- and each clone
    is its record's bytes but for the wavetable start, whose shape steps 3
    calls where the record's steps 2."""
    import songview
    from h2g.goatwriter import _orderlist_occurrences
    from bisect import bisect_right
    sng, _, _ = _converted("Rasputin")
    s = songview.parse_sng(sng)
    assert len(s.instruments) == 16
    clones = {7: 15, 14: 16}
    moved = {7: 0, 14: 0}
    for g in range(s.subtunes):
        ev, per = [], []
        for v in range(3):
            row, cur, notes = 0, 0, []
            for _pos, p in _orderlist_occurrences(s.tracks[3 * g + v]):
                pat = s.patterns[p]
                for r in range(0, len(pat), 4):
                    if pat[r] == 0xFF:
                        break
                    # Row 0 only, the planner's own reading: a tempo past
                    # row 0 is the fractional-row compensation
                    # (`patterns._compensate_fractional_rows`), not a step.
                    if (r == 0 and pat[r + 2] == CMD_SETTEMPO
                            and pat[r + 3] < 0x80):
                        ev.append((row, pat[r + 3]))
                    if pat[r + 1]:
                        cur = pat[r + 1]
                    if 0x60 <= pat[r] <= 0xBC:
                        notes.append((row, cur))
                    row += 1
            per.append(notes)
        ev.sort(key=lambda e: e[0])
        rows = [e[0] for e in ev]
        for notes in per:
            for row, ins in notes:
                k = bisect_right(rows, row) - 1
                tempo = ev[k][1] if k >= 0 else None
                if ins in clones.values():
                    rec = next(r for r, c in clones.items() if c == ins)
                    assert tempo == 6, (g, row, ins, tempo)
                    moved[rec] += 1
                elif ins in clones:
                    assert tempo != 6, (g, row, ins, tempo)
    assert moved == {7: 30, 14: 1}, moved
    for rec, clone in clones.items():
        a, b = s.instruments[rec - 1], s.instruments[clone - 1]
        assert (a.ad, a.sr, a.pulse_ptr, a.filt_ptr, a.vib_ptr, a.vib_delay,
                a.gatetimer, a.firstwave, a.name) == (
                b.ad, b.sr, b.pulse_ptr, b.filt_ptr, b.vib_ptr, b.vib_delay,
                b.gatetimer, b.firstwave, b.name)
        assert a.wave_ptr != b.wave_ptr
    # GT 7's own shape and its clone's, by the delay byte of the duty loop.
    assert _wavetable_of(sng, 7)[4:7] == [(0x80, 0x0C), (0x03, 0x00),
                                          (0x03, 0x0C)]
    assert _wavetable_of(sng, 15)[4:7] == [(0x80, 0x0C), (0x05, 0x00),
                                           (0x05, 0x0C)]


@needs_corpus
@pytest.mark.parametrize("name", ["Game_Killer", "Zoids", "Commando",
                                  "Master_of_Magic"])
def test_no_constant_step_file_is_split(name):
    """Game_Killer's gate has an immediate reload (one step all song), the
    others no gate at all: the plan declines every one of them."""
    import json
    from h2g.goatwriter import _instruments_used
    doc = json.loads((PYTHON_ROOT.parent / "presets.json").read_text())
    entry = doc["songs"].get(f"{name}.sid", {})
    _, tracks, patterns = _converted(name)
    sid, det = _det(CORPUS / f"{name}.sid")
    for lead in (0, 1):
        assert tempo_duty_split_plan(
            sid, det, tracks, patterns, True, lead,
            _instruments_used(det, None, lead),
            entry.get("multiplier", 1)) is None


def _fake_split(monkeypatch, tie=False):
    """A one-subtune song on a fake duty file: voice 0 plays pattern 0 at
    tempo 6 (record 1 named on row 0, row 1 sticky) and then pattern 1 at
    tempo 4 (set by voice 1's pattern 3), whose row 0 inherits the
    instrument and names none."""
    import h2g.goatwriter as G
    from types import SimpleNamespace
    monkeypatch.setattr(G.primitives, "fixed_arp_mask", lambda sid, det: (0x02, 0xF0))
    monkeypatch.setattr(G.arpeggio, "fixed_arp_counter_gated", lambda sid, det: True)
    monkeypatch.setattr(G.tempo, "find_song_speeds",
                        lambda sid, det: SongSpeeds((2,), 0, None))
    det = SimpleNamespace(arp_fixed_up=0x0C, effect_arp=True,
                          instr_start=0, instr_stride=8)
    sid = SimpleNamespace(data=bytes([0, 0, 0x41, 0, 0, 0, 0, 0x04]),
                          subtunes=1)
    end = [0xFF, 0, 0, 0]
    patterns = [
        [0x70, 1, CMD_SETTEMPO, 6, 0x72, 0, 0, 0] + end,
        [0x70, 0, CMD_TONEPORTA if tie else 0, 0, 0x72, 0, 0, 0] + end,
        [0xBD, 0, 0, 0, 0xBD, 0, 0, 0] + end,
        [0xBD, 0, CMD_SETTEMPO, 4, 0xBD, 0, 0, 0] + end,
    ]
    # The tempo 4 comes from voice 1 on row 2: rows advance in lockstep.
    tracks = [[0, 1, 0xFF, 0], [2, 3, 0xFF, 0], [2, 2, 0xFF, 0]]
    return tempo_duty_split_plan(sid, det, tracks, patterns, True, 0, 1, 2)


def test_a_sticky_instrument_is_named_where_the_split_changes_it(monkeypatch):
    """Pattern 1 relied on pattern 0's `instr 01`; once pattern 0 names the
    clone, pattern 1's first note must name the record or it plays the
    clone at tempo 4. No copies: each pattern has one spelling."""
    split = _fake_split(monkeypatch)
    assert split is not None
    assert split.clones == [(1, 2, 3)]
    assert split.edits == {0: {0: (1, 2)}, 1: {0: (0, 1)}}
    assert len(split.patterns) == 4
    out = apply_tempo_duty_edits(split.patterns, split)
    assert out[0][1] == 2 and out[1][1] == 1


def test_a_sticky_instrument_on_a_tie_drops_the_split(monkeypatch):
    """A `CMD_TONEPORTA` row cannot take the instrument (both players skip
    the instrument's init on it), so the plan declines rather than move it."""
    assert _fake_split(monkeypatch, tie=True) is None



# ---------------------------------------------------------------------------
# Tie chains: the octave locked to the ROW (`fixed_arp_tie_row_entries`).
#
# Chimera's GT 5, 8 and 9 play almost nothing but tie rows, and a tie row's
# `CMD_TONEPORTA $00` re-writes the note's base on every call whose
# wavetable entry writes no note, tick 0 excepted (player.s `mt_effect_3`
# -> `mt_effect_3_found` from `mt_wavedone`; no continuous effect on tick 0
# under REALTIMEOPTIMIZATION). `_tied_calls` transcribes exactly that beside
# the wavetable loop, and the shapes are checked against the original's
# tie row: its fetch frame sounds the new note's base, the frames after it
# the counter's octave (`C:/t/chimera-gk-duty`, v0.5.494).
# ---------------------------------------------------------------------------
from h2g.goatwriter import (fixed_arp_tie_row_entries,       # noqa: E402
                            fixed_arp_tie_rows)


def _tied_calls(left, right, row, frames, written=False, start=6):
    """Per frame (m = 1): 'b'/'u' of the note sounding, for a chain whose
    attack note is followed by a tie row every `row` frames, each tie to a
    new note. Frame 0 is the audible attack; the wavetable's first entry
    runs on tick 1 of the attack row (the init call runs none), so frame
    `j` is tick `(j + 1) % row`, or `j % row` where `written` (the
    firstwave owns frame 0 and the entries start on frame 1).

    'B'/'U' is the NEXT row's base/octave: a note written on a tie row's
    tick 0 is relative to the next row's note, which `mt_newnoteinit` has
    already stored in `mt_chnnote` (player.s) -- on the original's last
    frame of a row, unless `written` puts tick 0 on its fetch frame.
    `test_a_tick_0_note_sounds_the_next_rows_note` measures it."""
    lt = {start + k: left[k] for k in range(len(left))}
    rt = {start + k: right[k] for k in range(len(right))}
    ptr, wavetime = start, 0
    sounding = "b"                       # frame 0: the attack's own note
    out = []
    first = 1 if written else 0
    for j in range(frames):
        tick = (j % row) if written else ((j + 1) % row)
        tied = j >= row - (0 if written else 1)   # a tie row is playing
        wrote = None
        if j >= first:
            wave, note = lt[ptr], rt[ptr]
            if wave <= 0x0F and wavetime != wave:
                wavetime += 1            # an unfinished delay: no note
            else:
                wavetime = 0
                ptr += 1
                if lt.get(ptr) == 0xFF:
                    ptr = rt[ptr]
                if note != 0x80:
                    wrote = "u" if note == 0x0C else "b"
        if wrote is not None:
            sounding = (wrote.upper() if tied and tick == 0 and not written
                        else wrote)
        elif tied and tick != 0:
            sounding = "b"               # the tie writes the new base
        out.append(sounding)
    return "".join(out)


def _original_tied(mask, branch, phase, row, frames):
    """The original's chain: frame 0 and every fetch frame (a multiple of
    `row`) base, every other frame the counter's octave."""
    return "".join("b" if j % row == 0 or not fixed_arp_up(mask, branch,
                                                              phase + j)
                   else "u" for j in range(frames))


@pytest.mark.parametrize("row", [3, 4, 6])
@pytest.mark.parametrize("phase", range(8))
@pytest.mark.parametrize("tick", [None, (0x81, 2)])
def test_a_tied_row_sounds_its_base_then_the_octave(row, phase, tick):
    """Every frame of 60 against the original's tie chain: the only frames
    allowed to differ are the counter's own base frames (one in eight,
    not carried) and the attack row's tick 0, where the previous frame
    holds. The duty shape under the same ties is wrong on most octave
    frames -- the reason the row shape exists."""
    got = fixed_arp_tie_row_entries(0x41, 0x41, 0x07, BEQ, phase, 0x0C, 1,
                                    6, 255, row, tick=tick)
    assert got is not None
    left, right = got
    assert left[0] == 0x41 and right[0] == 0x00
    assert left[-1] == 0xFF
    frames = 60
    ours = _tied_calls(left, right, row, frames)
    want = _original_tied(0x07, BEQ, phase, row, frames)
    bad = [j for j in range(frames) if ours[j] != want[j]]
    allowed = {j for j in range(frames)
               if not fixed_arp_up(0x07, BEQ, phase + j) or j == row - 1}
    assert set(bad) <= allowed, (ours, want, bad)
    # Every fetch frame is the new base.
    for j in range(row, frames):
        if j % row == 0:
            assert ours[j] == "b", (j, ours)
    duty = fixed_arp_duty_entries(0x41, 0x41, 0x07, BEQ, phase, 0x0C, 1,
                                  start=6, budget=255, tick=tick)
    old = _tied_calls(*duty, row, frames)
    old_bad = sum(1 for j in range(frames) if old[j] != want[j])
    # At most the counter's base frames (one in eight) and one more; the
    # duty shape misses at least three times as many.
    assert len(bad) <= frames // 8 + 1, bad
    assert old_bad >= 3 * len(bad) and old_bad >= 20, (old, want)


def test_the_tie_row_shape_on_a_written_record_starts_on_frame_one():
    left, right = fixed_arp_tie_row_entries(0x41, 0x41, 0x07, BEQ, 0, 0x0C,
                                            1, 6, 255, 3, written=True)
    ours = _tied_calls(left, right, 3, 48, written=True)
    # Written: GT's tick 0 is the original's fetch frame, so the new base
    # lands a frame late (tick 1); tick 2 carries the octave.
    for j in range(3, 48):
        if j % 3 == 2 and fixed_arp_up(0x07, BEQ, j):
            assert ours[j] == "u", (j, ours)
    assert ours[0] == "b"


def test_the_tie_row_shape_declines_what_it_cannot_lock():
    assert fixed_arp_tie_row_entries(0x41, 0x41, 0x07, BEQ, 0, 0x0C, 2,
                                     6, 255, 3) is None    # above -S1
    assert fixed_arp_tie_row_entries(0x41, 0x41, 0x07, BEQ, 0, 0x0C, 1,
                                     6, 255, 2) is None    # no tick 2
    assert fixed_arp_tie_row_entries(0x41, 0x41, 0x07, BEQ, 0, 0x0C, 1,
                                     6, 3, 3) is None      # no room
    # ...and the duty shape answers in its place.
    assert (fixed_arp_duty_entries(0x41, 0x41, 0x07, BEQ, 0, 0x0C, 2, 6, 255,
                                   tie_row=3)
            == fixed_arp_duty_entries(0x41, 0x41, 0x07, BEQ, 0, 0x0C, 2, 6,
                                      255))


@needs_corpus
def test_only_chimeras_tied_records_take_the_row_shape():
    """Read back by songview: Chimera's three tied records carry the row
    loop -- `(2, octave)` and the jump -- and its GT 12 (5 tie notes of 7,
    but 159 of its 166 rows held) keeps the duty. The corpus byte-hash at
    v0.5.494 moved Chimera and nothing else."""
    if not (PYTHON_ROOT.parent / "presets.json").exists():
        pytest.skip("presets.json not present")
    sng, tracks, patterns = _converted("Chimera")
    sid, det = _det(CORPUS / "Chimera.sid")
    assert fixed_arp_tie_rows(sid, det, tracks, patterns) == {5: 3, 8: 3,
                                                              9: 3}
    for number in (5, 8, 9):
        wt = _wavetable_of(sng, number)
        assert wt[-2] == (0x02, 0x0C) and wt[-1][0] == 0xFF, (number, wt)
    assert _wavetable_of(sng, 5) == [(0x41, 0x00), (0x81, 0x0C), (0x81, 0x80),
                                     (0x41, 0x80), (0x00, 0x0C), (0x02, 0x0C),
                                     (0xFF, 0x1D)]
    assert _wavetable_of(sng, 12)[-2] != (0x02, 0x0C)
    for name in ("Zoids", "One_Man_and_his_Droid", "Master_of_Magic",
                 "Phantoms_of_the_Asteroid", "Battle_of_Britain",
                 "Game_Killer", "Rasputin"):
        sng, tracks, patterns = _converted(name)
        sid, det = _det(CORPUS / f"{name}.sid")
        assert fixed_arp_tie_rows(sid, det, tracks, patterns) == {}, name


@needs_corpus
@needs_siddump
def test_chimeras_tie_rows_are_re_measured_against_the_original():
    """The original's tied records (ADSR $0060, $BF00) over 60 s: every
    re-pitch that is not an octave flip lands a multiple of 3 frames from
    the chain's attack, and the frame after each sounds that note's
    octave -- the `b u` the row shape writes."""
    n = 60 * 50
    trace = fidelity.run_siddump(CORPUS / "Chimera.sid", 60, 0, calls=1)
    repitch = octave_after = 0
    for v in trace:
        fq = fidelity.register_timeline(v.freq_events, n + 4)
        ad = fidelity.register_timeline(v.adsr_events, n + 4)
        at = sorted(v.attack_frames)
        for i, a in enumerate(at):
            if ad[a] not in (0x0060, 0xBF00):
                continue
            end = at[i + 1] if i + 1 < len(at) else n
            lo = fq[a]
            for f in range(a + 1, min(end, n) - 1):
                x, prev = fq[f], fq[f - 1]
                if x == prev or not x or not lo:
                    continue
                if (abs(x / prev - 2) < 0.02 or abs(prev / x - 2) < 0.02
                        or abs(x / lo - 2) < 0.02 or x == lo):
                    continue             # an octave flip, not a re-pitch
                repitch += 1
                assert (f - a) % 3 == 0, (a, f)
                lo = x
                if abs(fq[f + 1] / x - 2) < 0.02:
                    octave_after += 1
    assert repitch > 300, repitch
    assert octave_after / repitch > 0.8, (octave_after, repitch)


# The counter's own base frame under a tie chain (task tie-chain-counter-base,
# v0.5.496): the original sounds it, the row shape does not, and carrying it
# was measured and REJECTED at the chain's residue as well as the record's
# -- see the RETRACTED paragraph above `FIXED_ARP_TIE_SHARE`. The reason is
# the packed player's tick 0, pinned by the two tests below.
@pytest.mark.parametrize("row", [3, 4, 6])
@pytest.mark.parametrize("phase", range(8))
@pytest.mark.parametrize("tick", [None, (0x81, 2)])
def test_the_tie_row_shape_writes_no_note_on_a_tie_rows_tick_0(row, phase,
                                                               tick):
    """A note written on a tie row's tick 0 sounds the NEXT row's note
    (`_tied_calls`' 'B'/'U'), so the shape writes none there: the base frame
    a counter-carrying loop would put on tick 0 and the octave's return
    after a tick-2 base frame both land on the wrong note. The carrying arm
    measured on Chimera at -t 180: 177 tick-0 frames the next note's octave,
    `vib` 0.847 -> 0.829."""
    left, right = fixed_arp_tie_row_entries(0x41, 0x41, 0x07, BEQ, phase,
                                            0x0C, 1, 6, 255, row, tick=tick)
    ours = _tied_calls(left, right, row, 96)
    assert ours == ours.lower(), ours


def _wave_left_offset(sng):
    """Offset of the WTBL's left column in a .sng (`build_sng`'s order)."""
    import songview
    pos = songview.HEADER_LEN
    subtunes = sng[pos]
    pos += 1
    for _ in range(subtunes * 3):
        pos += sng[pos] + 2
    pos += 1 + sng[pos] * 25
    return pos + 1


needs_gt2reloc = pytest.mark.skipif(
    not pathlib.Path(fidelity.GT2RELOC).exists(),
    reason="no gt2reloc on this machine")


@needs_corpus
@needs_siddump
@needs_gt2reloc
def test_a_tick_0_note_sounds_the_next_rows_note(tmp_path):
    """Through the PACKED player: Chimera's $0060 record (GT 5) with its loop
    entry `(2, octave)` respelt `(0, octave)` -- the octave written on every
    call, tick 0 included -- re-pitches each tie one frame EARLIER than the
    shipped shape does, onto the next note's octave: on tick 0
    `mt_newnoteinit` has already stored the next row's note, and the
    wavetable's relative note is read against it (player.s, the
    `cmp #TONEPORTA / beq mt_nonewnoteinit` that runs the wavetable after
    tick 0's note init). The shipped shape re-pitches on tick 1, where the
    tie writes the new base."""
    import songview
    sng, _t, _p = _converted("Chimera")
    wt = _wavetable_of(sng, 5)
    assert wt[-2] == (0x02, 0x0C) and wt[-1][0] == 0xFF, wt
    ins = next(i for i in songview.parse_sng(sng).instruments
               if i.number == 5)
    at = _wave_left_offset(sng) + ins.wave_ptr - 1 + len(wt) - 2
    assert sng[at] == 0x02
    patched = bytearray(sng)
    patched[at] = 0x00
    assert songview.parse_sng(bytes(patched)).tables["WTBL"][
        ins.wave_ptr - 1 + len(wt) - 2] == (0x00, 0x0C)
    seconds, n = 30, 30 * 50

    def repitches(blob, sub):
        work = tmp_path / sub
        work.mkdir()
        packed = fidelity.pack_sid(bytes(blob), work)
        assert packed is not None and packed.exists(), sub
        out = set()
        for vi, v in enumerate(fidelity.run_siddump(packed, seconds, 0,
                                                    calls=1)):
            fq = fidelity.register_timeline(v.freq_events, n + 4)
            ad = fidelity.register_timeline(v.adsr_events, n + 4)
            for f in range(1, n):
                x, prev = fq[f], fq[f - 1]
                if ad[f] != 0x0060 or not x or not prev or x == prev:
                    continue
                if abs(x / prev - 2) < 0.02 or abs(prev / x - 2) < 0.02:
                    continue             # an octave flip, not a re-pitch
                out.add((vi, f))
        return out

    shipped = repitches(sng, "shipped")
    every_call = repitches(patched, "every_call")
    assert len(shipped) > 100, len(shipped)
    early = {(v, f + 1) for v, f in every_call} & shipped
    # The respelt record re-pitches a frame before the shipped one: 461 of
    # its 465 re-pitches, covering 461 of the shipped shape's 499 (v0.5.496;
    # the rest are chain attacks and octave-adjacent notes).
    assert len(early) / len(every_call) > 0.95, (len(early), len(every_call))
    assert len(early) / len(shipped) > 0.85, (len(early), len(shipped))



# ---------------------------------------------------------------------------
# The per-note phase (`fixed_arp_phase_split_plan`): METHOD 7.bbbbbb's
# "two wavetables per record chosen by attack parity", built. A record whose
# notes attack on a minority residue within a factor of two of the majority
# gets a clone per such residue, and each note is renamed to its residue's.
# Measured at build (C:/t/per-note-split-unticked): Hunter_Patrol's offset-1
# octave up-fraction 0.32 -> 0.40 against the original's 0.40 (180 s);
# Game_Killer's `vib` (reversal_ratio) 0.23 -> 0.53 at -t 60, melody 100%
# both; the corpus byte-hash under presets moved exactly Chimera,
# Game_Killer, Human_Race, Hunter_Patrol, One_Man_and_his_Droid and Zoids.
# ---------------------------------------------------------------------------
import ast                                                     # noqa: E402

from h2g.goatwriter import (_orderlist_occurrences,           # noqa: E402
                            _shared_loop_block,
                            fixed_arp_note_residues,
                            fixed_arp_phase_split_plan)

SPLIT_FILES = {"Chimera", "Game_Killer", "Human_Race", "Hunter_Patrol",
               "One_Man_and_his_Droid", "Zoids"}


def _split_of(name):
    """(sng, the clones `build_sng` logged as (record, clone, residue))."""
    import json
    import h2g.convert as C
    doc = json.loads((PYTHON_ROOT.parent / "presets.json").read_text())
    # drop_unnamed_instruments (always-on since v0.5.495) renumbers the
    # records the split logs; the residues are checked in the player's own
    # numbering.
    opts = dict(fidelity._preset_opts(doc, f"{name}.sid"),
                drop_unnamed_instruments=False)
    logs = []
    sng = C.convert(str(CORPUS / f"{name}.sid"), log=logs.append, **opts)
    clones = []
    for line in logs:
        if line.startswith("arp phase split:") and "clone(s) [" in line:
            clones = ast.literal_eval(line[line.index("["):line.index("]") + 1])
    return sng, clones


def _sounding(name):
    """(song, clones, {(record, note residue, residue the instrument plays):
    untied notes}) over the finished song."""
    import songview
    from collections import Counter
    sng, clones = _split_of(name)
    s = songview.parse_sng(sng)
    sid, det = _det(CORPUS / f"{name}.sid")
    _, tracks, patterns = _converted(name)
    phases = fixed_arp_phases(sid, det, tracks, patterns)
    _, res = fixed_arp_note_residues(sid, det, s.tracks, s.patterns)
    clone = {c: (r, q) for r, c, q in clones}
    split = {r for r, _, _ in clones}
    tally = Counter()
    for ti, track in enumerate(s.tracks):
        cur, seen = 0, Counter()
        for pos, p in _orderlist_occurrences(track):
            pat = s.patterns[p]
            rr = res.get((ti, pos, seen[pos]), {})
            seen[pos] += 1
            for k in range(len(pat) // 4):
                if pat[4 * k] == 0xFF:
                    break
                if pat[4 * k + 1]:
                    cur = pat[4 * k + 1]
                if k not in rr or (pat[4 * k + 2] == CMD_TONEPORTA
                                   and pat[4 * k + 3] == 0):
                    continue
                rec, plays = clone.get(cur, (cur, phases.get(cur)))
                if rec in split:
                    tally[(rec, rr[k], plays)] += 1
    return s, clones, tally


@needs_corpus
@pytest.mark.parametrize("name", ["Hunter_Patrol", "Game_Killer"])
def test_every_split_note_sounds_its_own_residue(name):
    """Read back by songview (a second reader): every untied note of a split
    record, on the residue its clone was made for or the record's own,
    sounds an instrument carrying that residue -- and the clones are their
    records' bytes but for the wavetable start."""
    if not (PYTHON_ROOT.parent / "presets.json").exists():
        pytest.skip("presets.json not present")
    s, clones, tally = _sounding(name)
    assert clones, name
    made = {(r, q) for r, _, q in clones}
    wrong = {k: n for k, n in tally.items()
             if ((k[0], k[1]) in made or k[2] == k[1]) and k[1] != k[2]}
    assert not wrong, (name, wrong)
    moved = sum(n for (r, nr, q), n in tally.items() if (r, nr) in made)
    assert moved > 0, tally
    for rec, c, _ in clones:
        a, b = s.instruments[rec - 1], s.instruments[c - 1]
        assert (a.ad, a.sr, a.pulse_ptr, a.filt_ptr, a.vib_ptr, a.vib_delay,
                a.gatetimer, a.firstwave, a.name) == (
                b.ad, b.sr, b.pulse_ptr, b.filt_ptr, b.vib_ptr, b.vib_delay,
                b.gatetimer, b.firstwave, b.name)


@needs_corpus
def test_hunter_patrol_splits_by_parity():
    """Rows of 3 frames alternate parity, so instrument 11's 60:36 vote
    (METHOD 7.bbbbbb) splits; the parity mask has two residues, so each
    clone carries the record's other one."""
    if not (PYTHON_ROOT.parent / "presets.json").exists():
        pytest.skip("presets.json not present")
    _, clones = _split_of("Hunter_Patrol")
    sid, det = _det(CORPUS / "Hunter_Patrol.sid")
    _, tracks, patterns = _converted("Hunter_Patrol")
    phases = fixed_arp_phases(sid, det, tracks, patterns)
    assert {r for r, _, _ in clones} >= {11}, clones
    for rec, _, q in clones:
        assert q == 1 - phases[rec], (rec, q, phases[rec])


@needs_corpus
def test_every_game_killer_clone_has_a_block_of_its_own():
    """Eight clones at -S9 fit the 255-entry table only because each shares
    its record's loop (`_shared_loop_block`): every clone's wavetable start
    differs from its record's, and its block jumps into the record's."""
    if not (PYTHON_ROOT.parent / "presets.json").exists():
        pytest.skip("presets.json not present")
    import songview
    sng, clones = _split_of("Game_Killer")
    s = songview.parse_sng(sng)
    assert len(clones) == 8, clones
    for rec, c, _ in clones:
        a, b = s.instruments[rec - 1], s.instruments[c - 1]
        assert b.wave_ptr != a.wave_ptr, (rec, c)
        block = _wavetable_of(sng, c)
        assert block[-1][0] == 0xFF
        own = _wavetable_of(sng, rec)
        assert a.wave_ptr <= block[-1][1] < a.wave_ptr + len(own), (rec, c)


@needs_corpus
def test_only_files_with_a_split_vote_are_split():
    """Every fixed-arp file in the corpus: the plan builds where a record's
    minority residue is within a factor of two of its majority, and only
    there (Rasputin's tempo split owns its instrument columns)."""
    if not (PYTHON_ROOT.parent / "presets.json").exists():
        pytest.skip("presets.json not present")
    names = set(FIXED_ARP) | {
        "5_Title_Tunes", "Crazy_Comets", "Devils_Galop",
        "Geoff_Capes_Strongman_Challenge", "Gerry_the_Germ", "Gremlins",
        "Hunter_Patrol", "Last_V8", "Monty_on_the_Run", "Thing_on_a_Spring"}
    got = {n for n in names if _split_of(n)[1]}
    assert got == SPLIT_FILES, got


def test_a_clone_loop_jumps_into_its_records():
    """The unticked parity shape: the record (start 6) loops octave/base,
    the clone (start 20) base/octave -- the same two entries rotated, so the
    clone is its frame-0 entry and a jump to the record's second loop
    entry. A loop that is not a rotation is left whole."""
    record = [(0x41, 0x00), (0x41, 0x0C), (0x41, 0x00), (0xFF, 7)]
    entries = [(0, 0)] * 5 + record
    clone = ([0x41, 0x41, 0x41, 0xFF], [0x00, 0x00, 0x0C, 21])
    assert _shared_loop_block(clone, 20, entries, 6) == (
        [0x41, 0xFF], [0x00, 8])
    other = ([0x41, 0x41, 0x21, 0xFF], [0x00, 0x00, 0x0C, 21])
    assert _shared_loop_block(other, 20, entries, 6) == other
    # A shared block plays what the whole one plays, call for call: laid out
    # with the clone at 6 and its record at 20, from the clone's start.
    rec2 = [(0x41, 0x00), (0x41, 0x0C), (0x41, 0x00), (0xFF, 21)]
    clone2 = ([0x41, 0x41, 0x41, 0xFF], [0x00, 0x00, 0x0C, 7])
    shared = _shared_loop_block(clone2, 6, [(0, 0)] * 19 + rec2, 20)
    assert shared == ([0x41, 0xFF], [0x00, 22])

    def sounds(block):
        left = block[0] + [0] * (14 - len(block[0])) + [b for b, _ in rec2]
        right = block[1] + [0] * (14 - len(block[1])) + [b for _, b in rec2]
        return [(w, n) for _, w, n in wave_timeline(left, right, first=6,
                                                    calls=12)]
    assert sounds(shared) == sounds(clone2)


def _fake_phase(monkeypatch, track):
    """A one-subtune parity-mask file whose rows are 3 frames (so row k
    attacks on residue k & 1), one fixed-arp record (GT 1, lead 0), voice 0
    playing `track` over pattern 0 (three notes, instrument named on row 0
    only) and voices 1-2 a rest."""
    import h2g.goatwriter as G
    from types import SimpleNamespace
    monkeypatch.setattr(G.primitives, "fixed_arp_mask", lambda sid, det: (0x01, 0xF0))
    monkeypatch.setattr(G.arpeggio, "fixed_arp_counter_base", lambda sid, det: 0)
    monkeypatch.setattr(G.arpeggio, "fixed_arp_first_fetch", lambda sid, det: 0)
    monkeypatch.setattr(G.tempo, "find_song_speeds",
                        lambda sid, det: SongSpeeds((3,), 0, None))
    det = SimpleNamespace(arp_fixed_up=0x0C, effect_arp=True,
                          instr_start=0, instr_stride=8)
    sid = SimpleNamespace(data=bytes([0, 0, 0x41, 0, 0, 0, 0, 0x04]),
                          subtunes=1)
    end = [0xFF, 0, 0, 0]
    patterns = [[0x70, 1, 0, 0, 0x72, 0, 0, 0, 0x74, 0, 0, 0] + end,
                [0xBD, 0, 0, 0] + end]
    tracks = [track, [1, 0xFF, 0], [1, 0xFF, 0]]
    return tracks, patterns, (sid, det)


def test_each_note_names_its_residues_instrument(monkeypatch):
    """Two plays of pattern 0 at rows 0 and 3: the first attacks on residues
    0, 1, 0 and the second on 1, 0, 1 -- a 3:3 tie, the record keeps 0 and
    residue 1 gets clone 2. The second play wants other bytes, so it is a
    copy (pattern 2), and the first play's last note names the record back
    after the clone."""
    tracks, patterns, (sid, det) = _fake_phase(monkeypatch, [0, 0, 0xFF, 0])
    split = fixed_arp_phase_split_plan(sid, det, tracks, patterns, True, 0,
                                       1, 2)
    assert split is not None
    assert split.clones == [(1, 2, 1)]
    assert split.edits == {0: {1: (0, 2), 2: (0, 1)},
                           2: {0: (1, 2), 1: (0, 1), 2: (0, 2)}}
    assert split.tracks[0] == [0, 2, 0xFF, 0]
    out = apply_tempo_duty_edits(split.patterns, split)
    assert [out[0][1], out[0][5], out[0][9]] == [1, 2, 1]
    assert [out[2][1], out[2][5], out[2][9]] == [2, 1, 2]


def test_a_repeated_entry_keeps_its_first_spelling(monkeypatch):
    """`$D1 00`: one orderlist entry played twice, whose plays want two
    spellings. A repeat cannot be repointed, so the first play's stands --
    and no copy is made."""
    tracks, patterns, (sid, det) = _fake_phase(monkeypatch, [0xD1, 0, 0xFF, 0])
    split = fixed_arp_phase_split_plan(sid, det, tracks, patterns, True, 0,
                                       1, 2)
    assert split is not None
    assert split.edits == {0: {1: (0, 2), 2: (0, 1)}}
    assert len(split.patterns) == len(patterns)


def test_a_residue_whose_shape_ignores_it_gets_no_clone(monkeypatch):
    """`distinct` says the clone's block would be the record's (the -S{m}
    per-call loop ignores the phase): nothing is split."""
    tracks, patterns, (sid, det) = _fake_phase(monkeypatch, [0, 0, 0xFF, 0])
    assert fixed_arp_phase_split_plan(sid, det, tracks, patterns, True, 0,
                                      1, 2, distinct=lambda r, q: False) is None
    # And with `effects` off -- the VB6 reproduction -- nothing at all.
    assert fixed_arp_phase_split_plan(sid, det, tracks, patterns, False, 0,
                                      1, 2) is None


# ---------------------------------------------------------------------------
# The NIBBLE dialect's half-period, per record (nibble-arp-alternation-period).
#
# The nibble block self-modifies the mask it divides its counter by, chosen
# from the record's own nibble: `LDY #$02 / CMP #$0C / BEQ / LDY #$01 / STY
# and-operand` (Warhawk $13DE) -- an octave record alternates two counter
# steps a half, every other record one (`#$04` for the octave in Proteus,
# Chicken_Song, Hollywood_or_Bust and Formula_1_Simulator, whose spelling
# also swaps the SBC for an ADC). The counter's `INC` sits behind the outer
# gate, so a step is a passing call and a half spanning the skipped call is
# a frame longer. Measured on the originals at 60 s (C:/t/nibble-arp-period/
# orig_*.txt, runs of one sounding frequency inside a note): Warhawk
# `$090E` {2: 159, 3: 65} and `$0F08` {1: 397, 2: 65}; International_Karate
# `$0A08` {2: 103, 3: 25}, `$0F0B` {2: 128, 3: 32}, `$090A` {1: 1638,
# 2: 168}. Every shape held a half for exactly one frame until then:
# Warhawk `$090E` converted read {1: 519}, IK `$0A08` {1: 269}.
# ---------------------------------------------------------------------------
from h2g.detect import nibble_arp_period                     # noqa: E402
from h2g.goatwriter import (_hold_run, _wave_hold_byte,      # noqa: E402
                            nibble_arp_counter_gated, nibble_arp_entries,
                            nibble_arp_half_calls)

# name -> (interval, mask for it, mask otherwise, counter address), read off
# the files (dis6502 at the `STA` into the SBC operand).
NIBBLE_PERIODS = {
    "Warhawk": (0x0C, 2, 1, 0x15BF),
    "International_Karate": (0x0C, 2, 1, 0xB2F9),
    "Thrust": (0x0C, 2, 1, 0x0CEA),
    "Bump_Set_Spike": (0x0C, 2, 1, 0xB506),
    "Spellbound": (0x0C, 2, 1, 0xC1),                 # zero page
    "Kentilla": (0x0C, 2, 1, 0xAFEF),
    "Las_Vegas_Video_Poker": (0x0C, 2, 1, 0x54F9),
    "Samantha_Fox_Strip_Poker": (0x0C, 2, 1, 0xE8),   # zero page
    "Proteus": (0x0C, 4, 1, 0x0DA3),
    "Chicken_Song": (0x0C, 4, 1, 0x15C3),
    "Hollywood_or_Bust": (0x0C, 4, 1, 0x09A2),
    "Formula_1_Simulator": (0x0C, 4, 1, 0xC4F9),     # the ADC spelling
}
# The two with no outer gate in front of the counter's INC.
NIBBLE_UNGATED = {"Chicken_Song", "Hollywood_or_Bust"}


@needs_corpus
def test_the_nibble_period_is_read_from_every_file():
    for name, want in NIBBLE_PERIODS.items():
        sid, det = _det(CORPUS / f"{name}.sid")
        per = nibble_arp_period(sid, det)
        assert per is not None, name
        assert det.arp_nibble_period == per, name     # read once, at detect
        got = (per.interval, per.on_interval, per.otherwise, per.counter)
        assert got == want, (name, got)
        assert per.half(0x0C) == want[1] and per.half(0x05) == 1
        assert nibble_arp_counter_gated(sid, per) == (
            name not in NIBBLE_UNGATED), name
    # Mozart's nibble block masks with a constant `#$01`, and the fixed
    # dialect has no nibble block at all.
    for name in ("Mozart", "Commando", "Zoids"):
        sid, det = _det(CORPUS / f"{name}.sid")
        assert nibble_arp_period(sid, det) is None, name
        assert det.arp_nibble_period is None, name


@needs_corpus
def test_the_nibble_half_is_per_record_and_per_passing_call():
    """`m` calls a counter step, stretched by `(O + 1) / O` where the INC
    is gated: Warhawk -S7 gate 7 -> 8 calls a step, IK -S10 gate 10 -> 11.
    None where the answer is the old one-frame half."""
    cases = [("Warhawk", 7, 7, 0x0C, 16), ("Warhawk", 7, 7, 0x09, 8),
             ("International_Karate", 10, 10, 0x0C, 22),
             ("International_Karate", 10, 10, 0x05, 11),
             ("International_Karate", 10, None, 0x05, None),
             ("International_Karate", 10, None, 0x0C, 20),
             ("Formula_1_Simulator", 2, 4, 0x0C, 10),
             ("Hollywood_or_Bust", 1, None, 0x0C, 4),
             ("Mozart", 2, 2, 0x0C, None)]
    for name, m, skip, nib, want in cases:
        sid, det = _det(CORPUS / f"{name}.sid")
        got = nibble_arp_half_calls(sid, det, nib, m, skip)
        assert got == want, (name, m, skip, nib, got)


@pytest.mark.parametrize("calls", range(1, 70))
def test_a_hold_run_spends_exactly_its_calls(calls):
    run = _hold_run(calls, 0x41)
    spent = sum(1 if b == 0x41 else b + 1 for b in run)
    assert spent == calls, run
    assert all(b == 0x41 or 1 <= b <= 0x0F for b in run), run
    if calls <= 16:                       # one entry, the byte it always was
        assert run == [_wave_hold_byte(calls + 1, 0x41)]


def _runs(notes):
    runs = []
    for x in notes:
        if runs and runs[-1][0] == x:
            runs[-1][1] += 1
        else:
            runs.append([x, 1])
    return runs


@pytest.mark.parametrize("m, half", [(2, 4), (3, 7), (7, 8), (7, 16),
                                     (10, 11), (10, 22), (1, 2), (1, 4)])
def test_the_ticked_nibble_shape_holds_each_half_for_its_period(m, half):
    """The tick plays once, then base and alternate `half` calls each --
    across delay entries split at `WAVE_MAX_DELAY` where `half` exceeds
    17 -- and the loop target is the entry after the tick."""
    from h2g.goatwriter import _first_frame_lead
    wave, alt = 0x41, 0x74
    noise = 0x81
    frame0, frame0_r = _first_frame_lead(wave, m, force=True)
    extra = m - 1
    tl, tr = [noise], [0x00]
    if extra == 1:
        tl.append(noise)
        tr.append(0x00)
    elif extra > 1:
        tl.append(min(extra - 1, 0x0F))
        tr.append(0x80)
    left, right = ticked_arp_entries(frame0, frame0_r, tl, tr, noise, wave,
                                     alt, m, 6, 255, half_calls=half)
    assert left[-1] == 0xFF and right[-1] == 6 + len(frame0) + len(tl)
    calls = wave_timeline(left, right, first=6, calls=2 * m + 8 * half)
    waves = [w for _, w, _ in calls]
    assert waves[:m] == [wave] * m and waves[m:2 * m] == [noise] * m
    body = [note for _, _, note in calls[2 * m:]]
    runs = _runs(body)
    assert [r[1] for r in runs[:-1]] == [half] * (len(runs) - 1), runs
    assert [r[0] for r in runs[:4]] == [0x00, alt, 0x00, alt]


def test_the_ticked_shape_is_unchanged_where_the_half_is_a_frame():
    """A half of `m` calls is the unphased shape every fixed-dialect record
    keeps (`half_calls=None`), byte for byte."""
    from h2g.goatwriter import _first_frame_lead
    for m in (2, 3, 7, 16):
        frame0, frame0_r = _first_frame_lead(0x41, m, force=True)
        args = (frame0, frame0_r, [0x81, m - 2 if m > 2 else 0x81],
                [0x00, 0x80 if m > 2 else 0x00], 0x81, 0x41, 0x74, m, 6, 255)
        assert (ticked_arp_entries(*args, half_calls=m)
                == ticked_arp_entries(*args)), m


@pytest.mark.parametrize("half", [2, 3, 7, 8, 11, 16, 17, 18, 22, 40])
def test_the_unticked_nibble_shape_holds_each_half_for_its_period(half):
    """Base `half` calls from the attack, the alternate `half`, and round
    again through entry 0 -- where `half` is one frame it is the old -S{m}
    shape byte for byte."""
    left, right = nibble_arp_entries(0x41, 0x7B, half, 6, 255)
    assert left[-1] == 0xFF and right[-1] == 6
    notes = [n for _, _, n in wave_timeline(left, right, first=6,
                                            calls=8 * half)]
    runs = _runs(notes)
    assert [r[1] for r in runs] == [half] * 8, runs
    assert [r[0] for r in runs[:2]] == [0x00, 0x7B]
    if half <= 17:
        hold = _wave_hold_byte(half, 0x41)
        assert (left, right) == ([0x41, hold, 0x41, hold, 0xFF],
                                 [0x00, 0x00, 0x7B, 0x80, 6])
    assert nibble_arp_entries(0x41, 0x7B, half, 6, 4) is None
    assert nibble_arp_entries(0x41, 0x7B, 1, 6, 255) is None


@needs_corpus
def test_the_nibble_period_reaches_each_record():
    """International_Karate at its preset -S10 behind a reload-10 gate:
    the octave records `$0F0B` (3) and `$0A08` (4) alternate 22 calls a
    half, `$090A` (1, nibble 5) 11 -- per record in one file -- and
    Warhawk's `$090E` (10) 16 at -S7, its `$0F08` (7, nibble 9) 8."""
    cases = [("International_Karate", 10, 10, {3: 22, 4: 22, 1: 11}),
             ("Warhawk", 7, 7, {10: 16, 11: 16, 7: 8})]
    for name, m, skip, want in cases:
        sid, det = _det(CORPUS / f"{name}.sid")
        for rec, half in want.items():
            left, right = _wavetable_entries(sid, det, rec, True, "gts5", [],
                                             m, budget=255, start=6,
                                             gate_skip=skip)
            nib = sid.data[det.instr_start + rec * det.instr_stride + 7] >> 4
            alt = (0x80 - nib) & 0xFF
            notes = [n for _, _, n in wave_timeline(left, right, first=6,
                                                    calls=12 * half)]
            k = notes.index(alt)
            runs = _runs(notes[k:])
            assert [r[1] for r in runs[:-1]] == [half] * (len(runs) - 1), (
                name, rec, runs)


def _nibble_runs(trace, n, adsr):
    """Runs of one sounding frequency inside every note attacking with
    `adsr`, from the first frame the note shows only its two values; the
    first and last run of each note are cut by the attack and dropped."""
    from collections import Counter
    out = Counter()
    for v in trace:
        t = _timeline(v, n)
        ad = dict(v.adsr_events)
        cur, adsr_at = None, {}
        for f in range(n):
            if f in ad:
                cur = ad[f]
            adsr_at[f] = cur
        at = v.attack_frames
        for i, f in enumerate(at):
            if adsr_at.get(f) != adsr:
                continue
            seg = t[f:at[i + 1] if i + 1 < len(at) else n]
            while len(set(seg)) > 2:
                seg = seg[1:]
            if len(set(seg)) != 2 or len(seg) < 8:
                continue
            runs = [r[1] for r in _runs(seg)]
            out.update(runs[1:-1])
    return out


@needs_corpus
@needs_siddump
@pytest.mark.parametrize("name, records", [
    ("International_Karate", (1, 3, 4)),
    ("Warhawk", (7, 10, 11)),
])
def test_the_nibble_period_is_re_measured_against_the_original(name, records):
    """The reader against the original: the commonest run of each record
    is its half in frames, and every run is that half or one frame more
    -- the skipped call. IK `$090A` {1, 2}, `$0A08`/`$0F0B` {2, 3}."""
    sid, det = _det(CORPUS / f"{name}.sid")
    per = nibble_arp_period(sid, det)
    trace = fidelity.run_siddump(CORPUS / f"{name}.sid", 60, 0)
    for rec in records:
        base = det.instr_start + rec * det.instr_stride
        adsr = sid.data[base + 3] << 8 | sid.data[base + 4]
        half = per.half(sid.data[base + 7] >> 4)
        runs = _nibble_runs(trace, 60 * 50, adsr)
        assert sum(runs.values()) >= 50, (name, rec, runs)
        assert runs.most_common(1)[0][0] == half, (name, rec, runs)
        near = runs[half] + runs[half + 1]
        assert near >= 0.97 * sum(runs.values()), (name, rec, runs)
        assert runs[half + 1] > 0, (name, rec, runs)      # the stall


# ---------------------------------------------------------------------------
# The nibble dialect's ticked arpeggio runs THROUGH the noise tick
# (ik-ticked-tick-first-toggle-two-frames-late).
#
# The drum block writes $D404 and the arpeggio block the frequency, every
# frame, tick included -- so the original's alternation does not wait for the
# tick to end. International_Karate at its preset -S10, 180 s, first frame
# after the attack whose frequency is not the note's (C:/t/ik-first-toggle/
# per_note.py; orig / before / after):
#
#   $090A  {2: 312, 3: 79}  /  {4: 320, ...}  /  {2: 313, 3: 16, ...}
#   $0A08  {2: 116, 3: 30}  /  {5: 120, ...}  /  {2: 117, 3: 4, ...}
#   $0F0B  {2: 58, 3: 15}   /  {5: 59, ...}   /  {2: 59, ...}
#
# `ticked_arp_entries` held the note over the tick's two frames and began its
# loop after them: two frames late on every note, the tick's length. The
# phase is the nibble counter's residue on the attack (`nibble_arp_phases`,
# `fixed_arp_phases`' walk on the nibble block's counter); IK's notes vote 2,
# which puts frame 1 on the note and frame 2 on the interval for both the
# one-step and the two-step records. Warhawk (-S7) moved from 4/5 to the
# original's 3 on `$080C`/`$090E`/`$0F4F` and from 3 to 1 on `$0F08`/`$0FDA`.
# The corpus byte-hash under presets moved exactly the seven nibble files
# with a ticked record: Bump_Set_Spike, Formula_1_Simulator,
# International_Karate, Proteus, Spellbound, Thrust, Warhawk.
# ---------------------------------------------------------------------------
from h2g.goatwriter import (BNE, nibble_arp_counter_test,     # noqa: E402
                            nibble_arp_first_half, nibble_arp_phases,
                            ticked_nibble_arp_entries)

# name -> (base, branch) of the nibble counter: the reset reads 0, Thrust and
# Las_Vegas_Video_Poker store nothing (the file's byte plus one), and
# Samantha_Fox_Strip_Poker's zero-page counter has no byte in the file.
NIBBLE_COUNTER_TESTS = {
    "Warhawk": (0, BNE), "International_Karate": (0, BNE),
    "Thrust": (192, BNE), "Bump_Set_Spike": (0, BNE),
    "Spellbound": (0, BNE), "Kentilla": (0, BNE),
    "Las_Vegas_Video_Poker": (146, BNE), "Samantha_Fox_Strip_Poker": None,
    "Proteus": (0, BNE), "Chicken_Song": (0, BNE),
    "Hollywood_or_Bust": (0, BNE), "Formula_1_Simulator": (0, BNE),
}


@needs_corpus
def test_the_nibble_counter_test_is_read_from_every_file():
    """The block's own `AND` is the one a `STY` writes: the counter is also
    loaded by `AND #$03` (Warhawk, Thrust, Spellbound) and `AND #$01 / BEQ`
    (Proteus), which must not vote on the branch."""
    for name, want in NIBBLE_COUNTER_TESTS.items():
        sid, det = _det(CORPUS / f"{name}.sid")
        got = nibble_arp_counter_test(sid, det.arp_nibble_period)
        assert got == want, (name, got)


@pytest.mark.parametrize("residue, mask, want", [
    (2, 1, (False, 1)), (1, 1, (True, 1)), (0, 1, (False, 1)),
    (2, 2, (False, 1)), (0, 2, (True, 1)), (3, 2, (True, 2)),
    (1, 2, (False, 2)), (7, 4, (True, 4)), (5, 4, (False, 2)),
])
def test_frame_one_plays_the_residues_half(residue, mask, want):
    """`AND #mask / BNE` takes the interval where the masked counter is
    zero, and frame `k` reads `residue + k`: IK's residue 2 puts frame 1 on
    the note with one step left, at either mask."""
    assert nibble_arp_first_half(residue, mask, BNE) == want


def _frame_notes(left, right, m, frames, first=6):
    calls = wave_timeline(left, right, first=first, calls=m * frames)
    return ([calls[k * m + m - 1][1] for k in range(frames)],
            [calls[k * m + m - 1][2] for k in range(frames)], calls)


@pytest.mark.parametrize("m, tick, half, up, first_calls", [
    (10, 17, 11, False, 11), (10, 17, 22, False, 11), (10, 17, 22, True, 22),
    (7, 13, 8, False, 8), (7, 6, 16, True, 8), (3, 5, 7, False, 3),
    (2, 3, 2, True, 1), (5, 9, 40, False, 20),
])
def test_the_alternation_runs_through_the_tick(m, tick, half, up, first_calls):
    """Per call: the record's note for the lead, noise for `tick` calls, the
    first run `first_calls` on `up`'s note, then halves of `half` alternating
    -- across the tick's end and the loop's jump alike."""
    from h2g.goatwriter import _first_frame_lead
    wave, noise, alt = 0x41, 0x81, 0x74
    frame0, frame0_r = _first_frame_lead(wave, m, force=True)
    left, right = ticked_nibble_arp_entries(
        frame0, frame0_r, tick, noise, wave, alt, half, up, first_calls,
        6, 255)
    assert left[-1] == 0xFF
    n = m + tick + first_calls + 8 * half
    calls = wave_timeline(left, right, first=6, calls=n)
    waves = [w for _, w, _ in calls]
    notes = [x for _, _, x in calls]
    assert waves[:m] == [wave] * m and notes[:m] == [0x00] * m
    assert waves[m:m + tick] == [noise] * tick
    assert set(waves[m + tick:]) == {wave}
    runs = _runs(notes[m:])
    assert runs[0] == [alt if up else 0x00, first_calls], runs
    assert [r[1] for r in runs[1:-1]] == [half] * (len(runs) - 2), runs
    assert all(a[0] != b[0] for a, b in zip(runs, runs[1:])), runs
    # The loop is the two halves after the unrolled run: its target is an
    # entry at or after the tick's end, so the tick plays once.
    target = right[-1] - 6
    assert left[target] == wave and target >= len(frame0)
    assert ticked_nibble_arp_entries(frame0, frame0_r, tick, noise, wave,
                                     alt, half, up, first_calls, 6,
                                     len(left) - 1) is None


@needs_corpus
def test_the_karate_records_toggle_on_frame_two():
    """IK -S10 behind its reload-10 gate, residue 2: `$090A` (record 1,
    one step a half) and `$0A08`/`$0F0B` (4 and 3, two steps) all sound the
    note on frames 0-1 and the interval on frame 2 -- the original's modal
    first toggle -- with the tick's noise on frames 1-2 as before."""
    sid, det = _det(CORPUS / "International_Karate.sid")
    m = 10
    for rec, want in ((1, [0, 0, 1, 0, 1, 0]), (3, [0, 0, 1, 1, 0, 0]),
                      (4, [0, 0, 1, 1, 0, 0])):
        left, right = _wavetable_entries(sid, det, rec, True, "gts5", [], m,
                                         budget=255, start=6, gate_skip=10,
                                         arp_phase=2)
        waves, notes, _ = _frame_notes(left, right, m, 6)
        nib = sid.data[det.instr_start + rec * det.instr_stride + 7] >> 4
        alt = (0x80 - nib) & 0xFF
        assert [int(x == alt) for x in notes] == want, (rec, notes)
        assert waves[1] == 0x81 and waves[3] != 0x81, waves         # the tick


@needs_corpus
def test_the_karate_conversion_carries_the_walked_phase():
    """Through `build_sng`: the walk over IK's finished orderlists votes
    residue 2 on the ticked records' instruments, and the .sng (read back
    by songview) toggles them on frame 2."""
    if not (PYTHON_ROOT.parent / "presets.json").exists():
        pytest.skip("presets.json not present")
    sng, tracks, patterns = _converted("International_Karate")
    sid, det = _det(CORPUS / "International_Karate.sid")
    phases = nibble_arp_phases(sid, det, tracks, patterns)
    for number, want in ((2, [0, 0, 1, 0, 1]), (4, [0, 0, 1, 1, 0]),
                         (5, [0, 0, 1, 1, 0])):
        assert phases[number] == 2, (number, phases)
        wt = _wavetable_of(sng, number)
        left, right = [w for w, _ in wt], [r for _, r in wt]
        _, notes, _ = _frame_notes(left, right, 10, 5,
                                   first=_wavetable_start(sng, number))
        alt = next(r for r in right[:-1] if 0x60 <= r < 0x80)
        assert [int(x == alt) for x in notes] == want, (number, wt)


def _wavetable_start(sng, number):
    import songview
    s = songview.parse_sng(sng)
    return next(i for i in s.instruments if i.number == number).wave_ptr


@needs_corpus
@needs_siddump
def test_the_karate_first_toggle_is_re_measured_against_the_original():
    """The phase against the original: the modal first frame whose
    frequency leaves the note is `1 + steps` for residue 2 (frame 2) on
    every ticked record, `$090A`, `$0A08` and `$0F0B` alike."""
    from collections import Counter
    sid, det = _det(CORPUS / "International_Karate.sid")
    per = det.arp_nibble_period
    n = 120 * 50
    trace = fidelity.run_siddump(CORPUS / "International_Karate.sid", 120, 0)
    for rec in (1, 3, 4):
        base = det.instr_start + rec * det.instr_stride
        adsr = sid.data[base + 3] << 8 | sid.data[base + 4]
        up, steps = nibble_arp_first_half(
            2, per.half(sid.data[base + 7] >> 4), BNE)
        want = 1 if up else 1 + steps
        firsts = Counter()
        for v in trace:
            t = _timeline(v, n)
            ad = sorted(v.adsr_events)
            for f in v.attack_frames:
                cur = [a for g, a in ad if g <= f]
                if not cur or cur[-1] != adsr or f + 8 > n:
                    continue
                seg = t[f:f + 8]
                k = next((k for k, x in enumerate(seg) if x != seg[0]), None)
                firsts[k] += 1
        assert sum(firsts.values()) >= 20, (rec, firsts)
        assert firsts.most_common(1)[0][0] == want == 2, (rec, firsts)


# ---------------------------------------------------------------------------
# Formula_1_Simulator's residual `reversal_ratio`, and its octave's sign
# (formula-1-simulator-reversal-doubles-under-the-ticked-hold).
#
# The doubling the task was opened on (2.10x at v0.5.493) was the one-frame
# hold on the octave records, whose half is four counter steps: the original's
# `$0909` alternates in runs of 4, the conversion read {1: 940}
# (C:/t/nibble-arp-period/base_f1.txt). `nibble_arp_half_calls` (10 calls,
# -S2 behind gate 4) took that to 1.21x -- and the whole residual is the
# ONE-step records: split by ADSR (C:/t/f1-ticked-reversal/
# rba_base_Formula_1_Simulator.txt) `$086A` 560 -> 705, `$0900` 240 -> 300,
# `$0908` 672 -> 840, `$0A0A` 276 -> 345, `$3960` 1438 -> 1803, each 1.25x,
# while `$0909`/`$0F0A` read 50/50 and 16/16. Their half is 2 x 5/4 = 2.5
# calls, which `_gate_calls` rounds to 2 -- the old one-frame half, 25% fast.
# `nibble_arp_half_cycle` loops (2, 3); after it the same records read 564,
# 240, 672, 276, 1441 and the file 4279 / 4193 = 1.02x. The corpus byte-hash
# under presets moved exactly the three files whose gated half is not whole:
# Formula_1_Simulator (2.5), Thrust (10/3 and 20/3) and Spellbound (5.5);
# reversal_ratio 1.211 -> 1.021, 1.172 -> 1.078 and 0.982 -> 1.051 --
# Spellbound's aggregate moved AWAY from 1 although every one-step record of
# it moved toward the original ($0709 523 -> 591 of 593, $180A 1965 -> 2190
# of 2150, $AFFF 1151 -> 1257 of 1226): its `$0F0A` already alternated 336
# times against 228 (more alternating notes, its runs' shape now matching),
# and the rounding had been cancelling it. Last_V8 and Monty_on_the_Run do
# not move (fixed dialect).
#
# The sign: the corpus's one opcode-spelled block (`nibble_arp_up`) ADDS the
# octave. A `$0909` note on $45A0 plays $8B40 in the original and played
# $22D0 here; it now plays $8B42.
# ---------------------------------------------------------------------------
from h2g.goatwriter import (_arp_relative, nibble_arp_half_cycle,  # noqa: E402
                            nibble_arp_up)

# Formula_1_Simulator's arpeggio records by number (C:/t/f1-ticked-reversal).
F1_OCTAVE = (3, 4)                       # `$0F0A`, `$0909`: nibble $C
F1_ONE_STEP = (0, 6, 7, 8, 11)           # `$0A0A` `$0900` `$086A` `$3960` `$0908`


@needs_corpus
def test_only_formula_1s_octave_records_add_the_interval():
    sid, det = _det(CORPUS / "Formula_1_Simulator.sid")
    assert nibble_arp_up(sid, det, 0x0C) is True
    for nib in (2, 3, 4, 5, 7):
        assert nibble_arp_up(sid, det, nib) is False, nib
    for name in list(NIBBLE_PERIODS) + ["Mozart", "Commando", "Zoids"]:
        if name == "Formula_1_Simulator":
            continue
        sid2, det2 = _det(CORPUS / f"{name}.sid")
        assert nibble_arp_up(sid2, det2, 0x0C) is None, name
    assert _arp_relative(0, 0x0C, True) == 0x0C
    assert _arp_relative(0, 0x0C, False) == _arp_relative(0, 0x0C) == 0x74
    assert _arp_relative(0x0C, 0x0C) == 0x0C
    for rec, want, never in ((4, 0x0C, 0x74), (3, 0x0C, 0x74),
                             (6, 0x7E, 0x02)):
        left, right = _wavetable_entries(sid, det, rec, True, "gts5", [], 2,
                                         budget=255, start=6, gate_skip=4,
                                         arp_phase=0)
        assert want in right[:-1] and never not in right[:-1], (rec, right)


@needs_corpus
@needs_siddump
def test_formula_1s_octave_is_re_measured_against_the_original():
    """On the original every `$0909`/`$0F0A` note that alternates sounds its
    own note on the attack frame and twice that frequency as the other
    value: the octave is above it."""
    from collections import Counter
    sid, det = _det(CORPUS / "Formula_1_Simulator.sid")
    n = 60 * 50
    trace = fidelity.run_siddump(CORPUS / "Formula_1_Simulator.sid", 60, 0)
    for rec in F1_OCTAVE:
        base = det.instr_start + rec * det.instr_stride
        adsr = sid.data[base + 3] << 8 | sid.data[base + 4]
        up = down = 0
        for v in trace:
            t = _timeline(v, n)
            ad = sorted(v.adsr_events)
            for f in v.attack_frames:
                cur = [a for g, a in ad if g <= f]
                if not cur or cur[-1] != adsr or f + 10 > n:
                    continue
                common = Counter(t[f + 1:f + 12]).most_common(2)
                if len(common) != 2 or not t[f]:
                    continue
                lo, hi = sorted(x for x, _ in common)
                if abs(hi - 2 * lo) <= 0x10:
                    up += t[f] == lo
                    down += t[f] == hi
        assert up >= 20 and down == 0, (rec, up, down)


@needs_corpus
def test_a_fractional_half_is_spread_over_an_even_loop():
    """`m * steps * (O + 1) / O` calls a half: whole -> None (the rounded
    `nibble_arp_half_calls` is exact), otherwise the shortest even loop of
    halves summing to it, as even as integers allow."""
    from fractions import Fraction
    cases = [("Formula_1_Simulator", 2, 4, 0x05, (2, 3)),
             ("Formula_1_Simulator", 2, 4, 0x0C, None),
             ("Formula_1_Simulator", 2, None, 0x05, None),
             ("Thrust", 3, 9, 0x05, (3, 3, 4, 3, 3, 4)),
             ("Thrust", 3, 9, 0x0C, (6, 7, 7, 6, 7, 7)),
             ("Spellbound", 5, 10, 0x05, (5, 6)),
             ("Spellbound", 5, 10, 0x0C, None),
             ("International_Karate", 10, 10, 0x05, None),
             ("Warhawk", 7, 7, 0x0C, None),
             ("Hollywood_or_Bust", 1, None, 0x05, None),
             ("Mozart", 2, 2, 0x05, None)]
    for name, m, skip, nib, want in cases:
        sid, det = _det(CORPUS / f"{name}.sid")
        got = nibble_arp_half_cycle(sid, det, nib, m, skip)
        assert got == want, (name, m, skip, nib, got)
        if got is None:
            continue
        per = det.arp_nibble_period
        exact = Fraction(m * per.half(nib)) * (skip + 1) / skip
        assert len(got) % 2 == 0 and sum(got) == exact * len(got), got
        assert max(got) - min(got) == 1, got


@pytest.mark.parametrize("cycle", [(2, 3), (3, 3, 4, 3, 3, 4), (5, 6),
                                   (6, 7, 7, 6, 7, 7)])
def test_every_shape_plays_a_cycle_at_its_exact_rate(cycle):
    """All three nibble shapes take a cycle for `half_calls`: the halves
    after the first run follow it in order, the notes alternate, and the
    jump keeps both going round."""
    from h2g.goatwriter import _first_frame_lead
    wave, noise, alt = 0x41, 0x81, 0x74
    reps = 4 * len(cycle)
    want = [cycle[k % len(cycle)] for k in range(reps)]
    # Unticked: base note from the attack, through entry 0 again.
    left, right = nibble_arp_entries(wave, alt, cycle, 6, 255)
    assert right[-1] == 6
    notes = [x for _, _, x in wave_timeline(left, right, first=6,
                                            calls=sum(want) + 1)]
    runs = _runs(notes)
    assert [r[1] for r in runs[:-1]] == want, runs
    assert [r[0] for r in runs[:2]] == [0x00, alt]
    # Ticked, phase walked: first run, then the cycle from its start.
    m, tick = 2, 3
    frame0, frame0_r = _first_frame_lead(wave, m, force=True)
    left, right = ticked_nibble_arp_entries(
        frame0, frame0_r, tick, noise, wave, alt, cycle, True, 1, 6, 255)
    notes = [x for _, _, x in wave_timeline(
        left, right, first=6, calls=m + 1 + sum(want) + 1)][m:]
    runs = _runs(notes)
    assert runs[0] == [alt, 1], runs
    assert [r[1] for r in runs[1:-1]] == want, runs
    assert all(a[0] != b[0] for a, b in zip(runs, runs[1:])), runs
    # Ticked, phase unknown.
    tl, tr = [noise, noise], [0x00, 0x00]
    left, right = ticked_arp_entries(frame0, frame0_r, tl, tr, noise, wave,
                                     alt, m, 6, 255, half_calls=cycle)
    calls = wave_timeline(left, right, first=6, calls=2 * m + sum(want) + 1)
    runs = _runs([x for _, _, x in calls[2 * m:]])
    assert [r[1] for r in runs[:-1]] == want, runs
    assert [r[0] for r in runs[:2]] == [0x00, alt]


@needs_corpus
@needs_siddump
def test_formula_1s_one_step_half_is_re_measured_against_the_original():
    """The original's one-step records hold a half one frame, and two over
    the outer gate's skipped call: 180 s of interior runs average 1.20-1.24
    frames -- neither the rounded 2 calls (1.0 frame at -S2) nor 3 (1.5).
    Every such record's wavetable now averages 2.5 calls, 1.25 frames."""
    sid, det = _det(CORPUS / "Formula_1_Simulator.sid")
    n = 180 * 50
    trace = fidelity.run_siddump(CORPUS / "Formula_1_Simulator.sid", 180, 0)
    for rec in F1_ONE_STEP:
        base = det.instr_start + rec * det.instr_stride
        adsr = sid.data[base + 3] << 8 | sid.data[base + 4]
        runs = _nibble_runs(trace, n, adsr)
        count = sum(runs.values())
        mean = sum(k * v for k, v in runs.items()) / count
        assert count >= 200 and 1.15 < mean < 1.30, (rec, runs)
        for phase in (0, None):
            left, right = _wavetable_entries(sid, det, rec, True, "gts5", [],
                                             2, budget=255, start=6,
                                             gate_skip=4, arp_phase=phase)
            notes = [x for _, _, x in wave_timeline(left, right, first=6,
                                                    calls=400)]
            body = [r[1] for r in _runs(notes)][2:-1]
            assert set(body) == {2, 3}, (rec, phase, body)
            assert sum(body) / len(body) == pytest.approx(2.5, abs=0.05), (
                rec, phase, body)


# ---------------------------------------------------------------------------
# The GATE-OFF tail (nibble-per-call-shape-above-s1). A drum+arp record whose
# noise tick did not fit its budget keeps `tail` `$40` against its `$41`
# attack, so `nibble_arp_entries` -- which loops through entry 0 -- declines
# it, and until `gateoff_nibble_arp_entries` it fell to the -S1 per-call
# loop: the interval toggled on every play call above -S1. Census under
# presets at 3b1c66d + the dirty tree (C:/t/nibble-gateoff-tail/
# census_before.json): Bump_Set_Spike 22-24 and Spellbound 22-24 at -S5,
# Kentilla 20 at -S10, Thrust 18 and 25 at -S3 -- each at the five-entry
# (Thrust 18: six) budget of a full table. The old census's Warhawk, IK and
# Samantha_Fox per-call records were read past the instrument table and are
# never converted (C:/t/nibble-per-call-shape-above-s1/where_out.txt).
# ---------------------------------------------------------------------------
from h2g.goatwriter import (gateoff_nibble_arp_budget_pair,  # noqa: E402
                            gateoff_nibble_arp_entries,
                            nibble_arp_half_cycle)


@pytest.mark.parametrize("half", [2, 3, 6, 11, 16, 17, 22, 40, (5, 6),
                                  (2, 3), (6, 7, 7, 6, 7, 7),
                                  (3, 3, 4, 3, 3, 4)])
def test_the_gateoff_nibble_shape_holds_each_half_for_its_period(half):
    """The attack once at entry 0 and `$40` on every call after it -- the
    gate never re-asserted; every half, the first included (the attack is
    its first call), is the cycle's, base first; the jump returns to entry
    1, not 0."""
    cyc = (half, half) if isinstance(half, int) else half
    left, right = gateoff_nibble_arp_entries(0x41, 0x40, 0x74, half, 6, 255)
    assert (left[:2], right[:2]) == ([0x41, 0x40], [0x00, 0x00])
    assert left[-1] == 0xFF and right[-1] == 7
    assert 0x41 not in left[1:]
    calls = wave_timeline(left, right, first=6, calls=6 * sum(cyc))
    assert [w for _, w, _ in calls] == [0x41] + [0x40] * (len(calls) - 1)
    runs = _runs([n for _, _, n in calls])
    assert len(runs) > 2 * len(cyc), runs
    assert [r[1] for r in runs[:-1]] == (list(cyc) * 8)[:len(runs) - 1], runs
    assert [r[0] for r in runs[:2]] == [0x00, 0x74]


@pytest.mark.parametrize("half", [2, 3, 6, 16, (5, 6), (17, 16), (3, 4)])
def test_a_two_half_gateoff_loop_is_five_entries(half):
    """Each delay carries the next half's note on its final call, so no
    hold entry sits beside a note: halves up to (17, 16) cost the five
    entries every later record is reserved (16 a side is one delay; the
    base half's first two calls are the attack and entry 1). Declined at
    a budget of four, and at a half of one call."""
    left, _ = gateoff_nibble_arp_entries(0x41, 0x40, 0x7B, half, 6, 5)
    assert len(left) == 5
    assert gateoff_nibble_arp_entries(0x41, 0x40, 0x7B, half, 6, 4) is None
    assert gateoff_nibble_arp_entries(0x41, 0x40, 0x7B, 1, 6, 255) is None
    assert gateoff_nibble_arp_entries(0x41, 0x40, 0x7B, (1, 2), 6, 255) is None


def test_a_starved_gateoff_record_keeps_the_nearest_rate_that_fits():
    """Where the exact halves need more than the budget, the two halves
    summing to the cycle's mean doubled (rounded, base the longer), capped
    at one delay entry each -- never the per-call loop."""
    cases = {22: (17, 16), 40: (17, 16), 6: (6, 6), (5, 6): (6, 5),
             (6, 7, 7, 6, 7, 7): (7, 6), (3, 3, 4, 3, 3, 4): (4, 3)}
    for half, want in cases.items():
        pair = gateoff_nibble_arp_budget_pair(half)
        assert pair == want, (half, pair)
        left, _ = gateoff_nibble_arp_entries(0x41, 0x40, 0x74, pair, 6, 5)
        assert len(left) == 5, (half, left)


# name -> (multiplier, gate skip, {record: (start, budget, left, right)}),
# each record's block as `convert` lays it out under presets.
GATEOFF_RECORDS = {
    "Kentilla": (10, 10, {
        20: (221, 5, [0x41, 0x40, 0x0F, 0x0F, 0xFF],
             [0x00, 0x00, 0x74, 0x00, 0xDE])}),
    "Spellbound": (5, 10, {
        22: (241, 5, [0x41, 0x40, 0x03, 0x05, 0xFF],
             [0x00, 0x00, 0x7D, 0x00, 0xF2]),
        23: (246, 5, [0x41, 0x40, 0x03, 0x05, 0xFF],
             [0x00, 0x00, 0x7C, 0x00, 0xF7]),
        24: (251, 5, [0x41, 0x40, 0x03, 0x05, 0xFF],
             [0x00, 0x00, 0x7B, 0x00, 0xFC])}),
    "Thrust": (3, 9, {
        18: (205, 6, [0x41, 0x40, 0x02, 0x02, 0xFF],
             [0x00, 0x00, 0x7B, 0x00, 0xCE]),
        25: (241, 5, [0x41, 0x40, 0x05, 0x05, 0xFF],
             [0x00, 0x00, 0x74, 0x00, 0xF2])}),
    "Bump_Set_Spike": (5, 5, {
        22: (241, 5, [0x41, 0x40, 0x04, 0x05, 0xFF],
             [0x00, 0x00, 0x7D, 0x00, 0xF2]),
        23: (246, 5, [0x41, 0x40, 0x04, 0x05, 0xFF],
             [0x00, 0x00, 0x7C, 0x00, 0xF7]),
        24: (251, 5, [0x41, 0x40, 0x04, 0x05, 0xFF],
             [0x00, 0x00, 0x7B, 0x00, 0xFC])}),
}


@needs_corpus
@pytest.mark.parametrize("name", sorted(GATEOFF_RECORDS))
def test_the_gateoff_records_take_the_gateoff_shape(name):
    """Every corpus record of the population: Spellbound's (5, 6) and
    Bump_Set_Spike's 6 are its own halves exactly; Kentilla's 22 and
    Thrust's six-half cycles need more than their budget and take
    `gateoff_nibble_arp_budget_pair`. None toggles per call."""
    m, skip, records = GATEOFF_RECORDS[name]
    sid, det = _det(CORPUS / f"{name}.sid")
    for rec, (start, budget, want_l, want_r) in records.items():
        got = _wavetable_entries(sid, det, rec, True, "gts5", [], m,
                                 start=start, budget=budget, gate_skip=skip)
        assert got == (want_l, want_r), (name, rec, got)
        nib = sid.data[det.instr_start + rec * det.instr_stride + 7] >> 4
        own = (nibble_arp_half_cycle(sid, det, nib, m, skip)
               or nibble_arp_half_calls(sid, det, nib, m, skip))
        cyc = (own, own) if isinstance(own, int) else tuple(own)
        exact = gateoff_nibble_arp_entries(want_l[0], want_l[1], want_r[2],
                                           own, start, budget)
        want = cyc if exact is not None else gateoff_nibble_arp_budget_pair(
            own)
        runs = _runs([n for _, _, n in wave_timeline(
            want_l, want_r, first=start, calls=10 * sum(want))])
        assert [r[1] for r in runs[:-1]] == (
            list(want) * 10)[:len(runs) - 1], (name, rec, runs)
        assert min(r[1] for r in runs) >= 2, (name, rec, runs)


# ---------------------------------------------------------------------------
# The gated duty's 10-call step is RIGHT; what doubles a base frame is where
# our song's calls fall against the original's skipped frame (v0.5.496,
# C:/t/gated-duty-step-rounding).
#
# Opened as "Game_Killer's -S9 duty steps every 10 calls (1.11 frames), so
# one base frame sounds as two; this caps reversal_ratio at about 0.53 even
# with every note on its own residue". REFUTED on both counts, measured on
# the tree as found under presets:
#
# * The cap is not the duty. At -t 180 the original sounds 2091 reversals
#   and ours 905; split by the attack frame's AD + S nibble, `$0A9` (the
#   `$0A9A` record, GT 2, effect $0A: 7 long notes on voice 0 and 2 on
#   voice 1) is 1652 against 479 -- 1173 of the 1186 missing. Every other
#   group is within 12 (`296` 87/75, `19B` 63/62, the rest equal). At -t 60
#   the voice-0 note at frame 641 alone is 262 against 78.
# * The doubled base frame is not the step length. A step of 10 calls is
#   the original's average exactly -- one passing call is 10/9 frames -- and
#   a 10-call grid sampled every 9 calls repeats one step in ten frames, as
#   the original's gate does. What decides WHICH frame repeats is the call
#   phase: ours attacks one frame early on 2 of every 3 notes on every
#   voice (t180, matched by index after the harness's lag 5: v1 -1 x744 /
#   0 x385, v2 -1 x900 / 0 x450). Advancing the packed song 3, 4 or 5 calls
#   in its init (a scratch 6502 stub) makes every onset exact (t60: 367/367,
#   362/362, 450/450), voice 0's octave-frame agreement 888/1153 -> 1029/1068
#   at 5 calls, and reversal_ratio 0.527 -> 0.547 -- the ceiling of anything
#   aimed at the duty; reproducing the `$0A9A` note's 262 would put it at
#   0.98 (arithmetic, (214 + 184) / 406, not measured).
#
# The model below is that finding, minus the trace: the original's frames
# from its own gate walk, ours from `fixed_arp_duty_entries` through the
# wavetable loop transcription, a frame sampled after its ninth call.
# ---------------------------------------------------------------------------
from h2g.goatwriter import _gate_calls, file_multiplier         # noqa: E402

_PHASE_NOTES = 72        # 8 counter residues x 9 skip phases: every pairing
_PHASE_FRAMES = 12       # frames compared from each attack


def _gate_walk(sid, nframes):
    """`(skip, c, reload)`: per frame, whether the outer gate's RTS skips it
    and what the octave block's counter reads (held on a skipped frame) --
    the player's `DEC ctr / BPL / LDA #reload / STA ctr / RTS`, from the
    file's own byte; the new-song call reads 0."""
    m = OUTER_GATE_RTS.search(sid.data)
    assert m is not None
    ctr = m.group(1)[0] | m.group(1)[1] << 8
    reload = m.group(2)[0]
    g = sid.data[sid.to_offset(ctr)]
    skip, c, cnt, started = [], [], 0, False
    for _ in range(nframes):
        g -= 1
        if g < 0:
            g = reload
            skip.append(True)
            c.append(cnt)
            continue
        if started:
            cnt += 1
        started = True
        skip.append(False)
        c.append(cnt)
    return skip, c, reload


def _gated_duty_model(sigma, step=None):
    """`(onsets misplaced, frames differing on the notes that are not)`,
    over a note attacking on each of the first `_PHASE_NOTES` passing calls.

    The original: attack frame base (the init call runs no effect), then each
    passing frame `fixed_arp_up` on the counter, each skipped frame holding.
    Ours: the note's first call is `grid * w + sigma`, `grid` our calls a
    passing call -- the song's row clock, (R + 1) * m / R, independent of the
    code under test -- and a frame shows the state after its last call.
    `step` overrides the duty's own call count (the code's is `_gate_calls`).
    """
    sid, det = _det(CORPUS / "Game_Killer.sid")
    mask, branch = fixed_arp_mask(sid, det)
    base = fixed_arp_counter_base(sid, det)
    speeds = find_song_speeds(sid, det)
    m = file_multiplier(sid, speeds, True)
    skip, c, reload = _gate_walk(sid, 2 * _PHASE_NOTES + 4 * _PHASE_FRAMES)
    assert ((reload + 1) * m) % reload == 0
    grid = (reload + 1) * m // reload
    duty = _gate_calls(m, reload) if step is None else step
    passing = [f for f, s in enumerate(skip) if not s]
    misplaced = differ = 0
    for w in range(_PHASE_NOTES):
        f0 = passing[w]
        want = ["b"]
        for f in range(f0 + 1, f0 + _PHASE_FRAMES):
            want.append(want[-1] if skip[f] else
                        "u" if fixed_arp_up(mask, branch, base + c[f]) else "b")
        left, right = fixed_arp_duty_entries(
            0x41, 0x41, mask, branch, (base + c[f0]) % fixed_arp_period(mask),
            0x0C, duty, start=6, budget=255)
        s = grid * w + sigma
        tl = wave_timeline(left, right, first=6,
                           calls=m * (_PHASE_FRAMES + 2) + grid)
        if s // m != f0:
            misplaced += 1
            continue
        got = ["u" if tl[m * f + m - 1 - s][2] == 0x0C else "b"
               for f in range(f0, f0 + _PHASE_FRAMES)]
        differ += sum(a != b for a, b in zip(want, got))
    return misplaced, differ


@needs_corpus
def test_the_gated_duty_is_frame_exact_at_the_originals_call_phase():
    """Exactly one call phase of our row grid puts every attack on the
    original's frame, and at it the duty `_gate_calls` steps is frame-exact
    for every residue against every skip phase; a step one call shorter or
    longer is not. So 10 calls is not what doubles a base frame."""
    sid, det = _det(CORPUS / "Game_Killer.sid")
    m = file_multiplier(sid, find_song_speeds(sid, det), True)
    _, _, reload = _gate_walk(sid, 1)
    assert (m, reload, _gate_calls(m, reload)) == (9, 9, 10)
    grid = 10
    aligned = [s for s in range(grid) if _gated_duty_model(s)[0] == 0]
    assert len(aligned) == 1, aligned
    assert _gated_duty_model(aligned[0]) == (0, 0)
    for step in (grid - 1, grid + 1):
        assert _gated_duty_model(aligned[0], step)[1] > 0, step


@needs_corpus
def test_off_the_originals_call_phase_a_base_frame_doubles():
    """Every other phase misplaces attacks AND differs on notes whose attack
    it does place: the `bb` the opened task saw is the phase, carried by the
    same 10-call duty that is exact above."""
    aligned = [s for s in range(10) if _gated_duty_model(s)[0] == 0]
    for sigma in range(10):
        if sigma in aligned:
            continue
        misplaced, differ = _gated_duty_model(sigma)
        assert misplaced > 0 and differ > 0, (sigma, misplaced, differ)
