"""Which records take a legato clone in Star_Paws: never a vibrato record.

`star-paws-legato-vibrato-travel` asked whether a legato clone's vibrato
restart matches the original's at the tie landing, after the entry split
(`entry_instrument_split`) moved Star_Paws' `vib` reversals 1.088 -> 1.096 and
`travel` 0.987 -> 0.969. In the original every fetched note, tied or not,
zeroes the vibrato counter (`STA $B8AD,X`, the first thing the fetch does) and
leaves the oscillator running; a clone restarts the record's wavetable and
speed-table step, so the two could disagree.

They cannot here: all 192 tie rows land on records whose effect byte carries
bit $10 (the 3-step pitch sequence on a global phase cell, effects `$30` and
`$38`), and none of the records with a vibrato pointer (GT 4, 5, 6 and 11) is
cloned. With every tie left as `CMD_TONEPORTA 00` the per-instrument vibrato
reversal counts of those records are identical to the clone arm's (ADSR
`$0A98` 937 against 937, `$0AAA` 280 against 280; the original's 877 and 264;
2026-10-09, 81a766c, -t 180 under presets, historical). What the entry split
moved is the pitch sequence: see `docs/H2G-CONVERSION-METHOD.md` § "A legato
clone of a bit-$10 record".

This pins the premise. If a vibrato record ever takes a clone, the question
the task asked is open again and this fails to say so.
"""
import json
import pathlib

from h2g.convert import convert
from songview import parse_sng

from corpus import CORPUS, needs_corpus

REPO_ROOT = pathlib.Path(__file__).resolve().parents[2]
GATETIMER_LEGATO = 0x40
EFFECT_PITCH_SEQ = 0x10


def _star_paws():
    import fidelity as F
    doc = json.loads((REPO_ROOT / "presets.json").read_text(encoding="utf-8"))
    return parse_sng(convert(str(CORPUS / "Star_Paws.sid"),
                             **F._preset_opts(doc, "Star_Paws.sid")))


@needs_corpus
def test_star_paws_has_vibrato_records_and_legato_clones():
    song = _star_paws()
    assert any(i.vib_ptr for i in song.instruments), "premise is vacuous"
    assert any(i.gatetimer & GATETIMER_LEGATO for i in song.instruments)


@needs_corpus
def test_no_star_paws_legato_clone_carries_a_vibrato():
    song = _star_paws()
    clones = [i for i in song.instruments if i.gatetimer & GATETIMER_LEGATO]
    assert clones
    for i in clones:
        assert i.vib_ptr == 0 and i.vib_delay == 0, (i.number, i.name)


@needs_corpus
def test_every_star_paws_legato_clone_but_the_decoy_is_a_bit_10_record():
    song = _star_paws()
    clones = [i for i in song.instruments if i.gatetimer & GATETIMER_LEGATO]
    plain = [i for i in clones
             if not (i.effect_byte or 0) & EFFECT_PITCH_SEQ]
    # The -S2 slip's decoy (`legato_slip_decoy`) is a copy of a record no
    # note plays on it; every other clone is the record a tie landed on.
    assert len(plain) == 1, [(i.number, i.name) for i in plain]
    assert len(clones) > 1
