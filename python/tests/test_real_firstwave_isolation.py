"""`real_firstwave_instruments` touches the instruments it names and no other.

The option exists to take `no_test_restart`'s firstwave byte per instrument
instead of file-wide (see `goatwriter._write_instruments`). On Confuzion the
file-wide flag costs voice 0's melody (1.00 -> 0.68) for a noise change that
lives on voice 1 alone; naming only the noise instruments keeps voices 0 and 2
at their un-flagged scores (HISTORICAL: v0.5.497 working tree, `-t 180`
with the window floor at 307 s, presets from the 496 refresh;
C:/t/check-whether-real-firstwave/fid_*.json). That is only true while the option is isolated in
BOTH places it is read -- the record's byte +8 and the wavetable's
`instrument_written` -- so both are pinned here, on the file that motivated it.

**The number is the OUTPUT file's GT number, and it moves with
`compact_instruments`.** Confuzion's two noise records ($0300 and $0900, names
`03:` and `05:`) are GT 3 and 5 on defaults and GT 2 and 4 under its preset,
which drops the empty "Clear Voice" slot. A preset entry naming (2, 4) is
correct only beside `compact_instruments`; the last test pins that the
numbering tracks the record, not the slot.
"""
from corpus import CORPUS, needs_corpus

from h2g.convert import convert
from h2g.goatwriter import FIRSTWAVE_TESTBIT

import songview

CONFUZION = CORPUS / "Confuzion.sid"


def _song(**opts):
    return songview.parse_sng(convert(str(CONFUZION), log=lambda m: None,
                                      **opts))


def _program(song, ins):
    """The instrument's wave program with its jump made start-relative, so a
    table that moved under it still compares equal."""
    out = []
    for idx, left, right, kind, *_ in songview.wave_program(song, ins.wave_ptr):
        out.append((left, (right - ins.wave_ptr) if kind == "jump" else right))
    return out


def _noise_numbers(song):
    """GT numbers whose own wave program opens on a NOISE select."""
    got = set()
    for ins in song.instruments:
        prog = songview.wave_program(song, ins.wave_ptr)
        if prog and prog[0][3] != "jump" and prog[0][1] & 0x80 \
                and prog[0][1] < 0xF0:
            got.add(ins.number)
    return got


@needs_corpus
def test_naming_the_noise_instruments_changes_only_their_firstwave():
    base = _song()
    named = _noise_numbers(base)
    assert named, "Confuzion lost its noise instruments -- re-derive the test"
    flagged = _song(real_firstwave_instruments=tuple(sorted(named)))
    assert len(flagged.instruments) == len(base.instruments)
    for a, b in zip(base.instruments, flagged.instruments):
        assert a.firstwave == FIRSTWAVE_TESTBIT, a.number
        if b.number in named:
            # the record's own waveform, gate forced on: noise + gate
            assert b.firstwave == 0x81, (b.number, hex(b.firstwave))
        else:
            assert b.firstwave == FIRSTWAVE_TESTBIT, (b.number, hex(b.firstwave))
            assert (b.ad, b.sr, b.gatetimer, b.name) == \
                (a.ad, a.sr, a.gatetimer, a.name), b.number
            assert _program(flagged, b) == _program(base, a), b.number


@needs_corpus
def test_an_empty_tuple_is_byte_inert():
    sid = str(CONFUZION)
    assert convert(sid, log=lambda m: None, real_firstwave_instruments=()) \
        == convert(sid, log=lambda m: None)


@needs_corpus
def test_the_number_follows_the_record_across_compact_instruments():
    """GT 3/5 on defaults and GT 2/4 compacted are the same two records."""
    loose = _song(real_firstwave_instruments=(3, 5))
    tight = _song(compact_instruments=True,
                  real_firstwave_instruments=(2, 4))
    flipped = {ins.name.split(":")[0] for ins in loose.instruments
               if ins.firstwave != FIRSTWAVE_TESTBIT and ":" in ins.name}
    assert flipped == {"03", "05"}
    assert flipped == {ins.name.split(":")[0] for ins in tight.instruments
                       if ins.firstwave != FIRSTWAVE_TESTBIT}
    assert {ins.adsr for ins in tight.instruments
            if ins.firstwave != FIRSTWAVE_TESTBIT} == {"$0300", "$0909"}
    # $0909 is the record's own SR; the preset's `sustain_exact` writes it
    # as $0900, which is the key the fidelity report prints for our side.
