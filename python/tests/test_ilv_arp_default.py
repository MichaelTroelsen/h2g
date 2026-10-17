"""The interleaved engine's DEFAULT arpeggio: record byte +10 (`--arpeggio-default`).

Read out of the note-start block of the six ilv players (Go_Go_Dash's bytes):

    12BB  BD 55 1B  LDA $1B55,X     ; record +10
    12BE  8D A0 13  STA $13A0       ; patches the LDA #imm at $139F
    139A  AD 61 1A  LDA $1A61       ; a $83 this event?
    139D  D0 05     BNE $13A4
    139F  A9 00     LDA #$00        ; operand = the record's +10
    13A1  9D 55 1A  STA $1A55,X     ; ...into the same cell $83 writes

so a record with +10 != 0 arpeggiates every note that carries no `$83`. The
verify instruments (runqueue cycle 6, `ilv-atkpitch-44-oscillation`) are all
such records: Go_Go_Dash `$0286` (rec 1, +10 = $C0), Lakers `$086A` (rec 8,
$13) and `$0875` (rec 6, $C0).

Synthetic where the shape is the point, corpus where the population is.
"""
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import songview                                              # noqa: E402
from corpus import CORPUS, needs_corpus                      # noqa: E402
from h2g import patterns as P                                # noqa: E402
from h2g.convert import convert                              # noqa: E402
from h2g.detect import detect                                # noqa: E402
from h2g.ilv_arp_default import ilv_default_arps             # noqa: E402
from h2g.sidfile import load_sid                             # noqa: E402

# Records the verify names, with their +10 byte, per file. Read off the
# instrument tables with `records.py`; the dict is a subset (a file may carry
# more records than the ones pinned).
PINNED = {
    "Go_Go_Dash.sid": {1: 0xC0, 3: 0xC0},
    "Lakers_vs_Celtics.sid": {6: 0xC0, 8: 0x13, 14: 0xCC},
    "Radio_ACE.sid": {4: 0xC0, 14: 0xC0},
    "Sun_Never_Shines.sid": {5: 0xC0},
    "Pacific_Coast.sid": {12: 0xC0},
    "Lion_Heart.sid": {13: 0xC0},
}


def _stream(*b):
    return bytes([0x00, 0x00]) + bytes(b)


def _rows(ev):
    return [ev[i:i + 4] for i in range(0, len(ev), 4)]


# ------------------------------------------------------------- the decoder

def test_a_note_with_no_83_takes_its_records_default():
    arps = P.IlvArps(commands=False, defaults={5: 0xC0})
    data = _stream(0x80, 0x05, 0xC0 | 3, 0x30, P.ILV_END)
    rows = _rows(P._build_raw_pattern_ilv(data, 2, arps=arps))
    assert list(arps) == [(5, 0xC0)]
    assert rows[0][2:] == [P.CMD_SETWAVEPTR, 1]
    assert [r[2:] for r in rows[1:4]] == [[0, 0]] * 3, "hold rows carry nothing"


def test_an_explicit_83_overrides_the_default_and_zero_cancels_it():
    both = P.IlvArps(commands=True, defaults={5: 0xC0})
    ev = P._build_raw_pattern_ilv(
        _stream(0x80, 0x05, 0x83, 0x50, 0x30, P.ILV_END), 2, arps=both)
    assert list(both) == [(5, 0x50)], "the note's own operand, not the default"
    zero = P.IlvArps(commands=True, defaults={5: 0xC0})
    ev = P._build_raw_pattern_ilv(
        _stream(0x80, 0x05, 0x83, 0x00, 0x30, P.ILV_END), 2, arps=zero)
    assert not zero and _rows(ev)[0][2:] == [0, 0], "$83 00 cancels the default"


def test_the_default_alone_ignores_83_commands():
    """`--arpeggio-default` without `--arpeggio` must not start emitting `$83`
    (it would change bytes the shipped presets for these files decline)."""
    arps = P.IlvArps(commands=False, defaults={})
    ev = P._build_raw_pattern_ilv(
        _stream(0x80, 0x05, 0x83, 0x50, 0x30, P.ILV_END), 2, arps=arps)
    assert not arps and _rows(ev)[0][2:] == [0, 0]


def test_a_record_without_a_default_and_a_rest_are_left_alone():
    arps = P.IlvArps(commands=False, defaults={5: 0xC0})
    data = _stream(0x80, 0x06, 0x30, 0x80, 0x05, P.ILV_REST, 0x30, P.ILV_END)
    rows = _rows(P._build_raw_pattern_ilv(data, 2, arps=arps))
    assert list(arps) == [(5, 0xC0)], "only the last note collects a pair"
    assert rows[0][2:] == [0, 0], "record 6 has no default"
    assert rows[1][2:] == [0, 0], "a rest is not arpeggiated"
    assert rows[2][2:] == [P.CMD_SETWAVEPTR, 1], "the note after the rest is"


def test_a_slide_keeps_the_command_column_and_the_default_declines():
    arps = P.IlvArps(commands=False, defaults={5: 0xC0})
    data = _stream(0x80, 0x05, 0x82, 0x01, 0x00, 0x30, P.ILV_END)
    ev = P._build_raw_pattern_ilv(data, 2, slides=True, steps=[], arps=arps)
    assert ev[2] in (1, 2), "the portamento, not the wavetable pointer"


# ------------------------------------------------------------ the detection

@needs_corpus
@pytest.mark.parametrize("name", sorted(PINNED))
def test_the_default_records_are_read_off_the_players_own_bytes(name):
    sid = load_sid(str(CORPUS / name))
    det = detect(sid, lambda *a: None)
    got = ilv_default_arps(sid, det)
    for rec, operand in PINNED[name].items():
        assert got.get(rec) == operand, (name, rec, got)


@needs_corpus
def test_a_non_ilv_player_reads_no_default():
    """The shape is matched on bytes AND gated on the dialect: a classic-engine
    file must return nothing, whatever its +10 bytes hold."""
    sid = load_sid(str(CORPUS / "Commando.sid"))
    det = detect(sid, lambda *a: None)
    assert ilv_default_arps(sid, det) == {}


# -------------------------------------------------------------- the wiring

KW = dict(fmt="gts5", slides=True, effects=True, compact_instruments=True)


@needs_corpus
def test_the_option_off_is_byte_identical():
    assert convert(str(CORPUS / "Go_Go_Dash.sid"), arpeggio_default=False, **KW) \
        == convert(str(CORPUS / "Go_Go_Dash.sid"), **KW)


@needs_corpus
def test_a_default_reaches_the_sng_as_a_block_and_a_pointer():
    """Go_Go_Dash's record 1 ($0286) is the `$44` octave trill: with the option
    on, its notes carry CMD_SETWAVEPTR to a block of two-step note offsets
    (0, +12) -- and with it off, none does."""
    off = songview.parse_sng(convert(str(CORPUS / "Go_Go_Dash.sid"), **KW))
    on = songview.parse_sng(
        convert(str(CORPUS / "Go_Go_Dash.sid"), arpeggio_default=True, **KW))

    def pointers(song):
        return [r for pat in song.patterns
                for r in (pat[k:k + 4] for k in range(0, len(pat), 4))
                if len(r) == 4 and r[2] == P.CMD_SETWAVEPTR]
    assert not pointers(off)
    rows = pointers(on)
    assert rows, "the default emitted no pointer"
    wave = on.tables["WTBL"]
    for t in {r[3] for r in rows}:
        assert 1 <= t <= len(wave) and wave[t - 1][0] != 0xFF
    # The $C0 trill block: the tail alternates 0 and +12 (relative note 0x0C).
    tails = {tuple(r for _, r in wave[t - 1:t + 8]) for t in {r[3] for r in rows}}
    assert any(0x0C in tail and 0x00 in tail for tail in tails)
