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
is a *detection* fix and deliberately not a rate fix: the mask is the
alternation period and `goatwriter._wavetable_entries` does not read it -- it
emits the one-call swing `AND #$01` gives. The A/B that shipped this says so
plainly. Every sequence and register dimension (melody, seq, pitch, retrig,
wave, noise, adsr, gate, nrun, hold, onset, tail, drift) is **exactly
unchanged** on all nine files; `bend` moves toward 1 on five of them
(Phantoms 5.83 -> 1.14, Zoids 4.79 -> 0.91) and `vib` -- the oscillation
rate -- moves on seven, four toward the original and three past it
(Game_Killer 0.19 -> 2.55, Master_of_Magic 0.59 -> 2.92). Mean log-distance
from 1.00 falls 1.29 -> 0.89. The overshoot is the mask this emitter cannot
express, and it is the next piece of work, not a defect in the reading.

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
                            fixed_arp_first_fetch, fixed_arp_phases)

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
    # Another mask is not this phase: Zoids divides by $04.
    sid, det = _det(CORPUS / "Zoids.sid")
    assert det.arp_fixed_up == OCTAVE
    assert fixed_arp_counter_base(sid, det) is None


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
    is EVEN there, so the octave is the frame after: offset 1. Instrument
    11's notes sit on both parities, 11 odd-frame to 6 even-frame in one lap
    of voice 2, so it takes offset 1 too; instrument 4, the noise record
    the voice's other 150 notes play, sits on even frames throughout and
    takes offset 2. The walk names the frame of all 131 of voice 2's attacks
    exactly (v0.5.485, siddump of the original), so the split is the
    music's, and instrument 11's minority is the residue a per-note phase
    would recover.
    """
    if not (PYTHON_ROOT.parent / "presets.json").exists():
        pytest.skip("presets.json not present")
    sid, det = _det(CORPUS / "Hunter_Patrol.sid")
    _, tracks, patterns = _converted("Hunter_Patrol")
    phases = fixed_arp_phases(sid, det, tracks, patterns)
    assert (phases.get(12), phases.get(11), phases.get(4)) == (1, 1, 2), phases
    sid, det = _det(CORPUS / "Commando.sid")
    _, tracks, patterns = _converted("Commando")
    phases = fixed_arp_phases(sid, det, tracks, patterns)
    assert phases and set(phases.values()) == {1}, phases
