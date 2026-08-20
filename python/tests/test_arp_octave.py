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
