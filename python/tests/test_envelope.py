"""The instrument envelope: the sustain nibble, and Goattracker's hard restart.

Both are opt-in because both change the bytes of the Commando fixture, and both
are in `presets.json`'s `always` block because neither is a per-song taste --
they are what SID register 6 holds and what the player does with it.
"""
from pathlib import Path

import pytest

from h2g.convert import convert

REPO = Path(__file__).resolve().parents[2]
COMMANDO = REPO / "Commando.sid"

# .sng layout up to the instruments: 4 magic + 3 * 32 name, then the subtune
# count, then one length byte + that many bytes per track, then the instrument
# count, then 9 bytes + a 16-byte name per instrument.
_HDR = 4 + 32 * 3


def _instruments(sng: bytes):
    """(ad, sr, gatetimer) for each instrument record in a .sng."""
    pos = _HDR
    subtunes = sng[pos]
    pos += 1
    for _ in range(subtunes * 3):
        n = sng[pos] + 1
        pos += 1 + n
    count = sng[pos]
    pos += 1
    out = []
    for _ in range(count):
        rec = sng[pos:pos + 9]
        out.append((rec[0], rec[1], rec[7]))
        pos += 9 + 16
    return out


def _sng(**opts):
    return convert(str(COMMANDO), log=lambda m: None, **opts)


def test_fixture_is_byte_exact_at_defaults():
    assert _sng() == (REPO / "Commando.sng").read_bytes()


def test_sustain_clamp_is_the_default_and_lowers_a_full_sustain():
    """The inherited VB6 mask clears $10 from any sr >= $F0, so sustain F
    reaches Goattracker as E. SID register 6 is SSSS RRRR -- four bits each
    (6581 datasheet) -- so there is no spare bit to clear."""
    default = _instruments(_sng())
    exact = _instruments(_sng(sustain_exact=True))
    assert len(default) == len(exact)

    clamped = [(d[1], e[1]) for d, e in zip(default, exact) if d[1] != e[1]]
    assert clamped, "Commando has no full-sustain instrument to exercise this"
    for got, want in clamped:
        assert want >= 0xF0, "only sr >= $F0 is touched"
        assert got == want & 0xEF
        assert (want >> 4) == 0xF and (got >> 4) == 0xE
        assert (got & 0x0F) == (want & 0x0F), "the release nibble must survive"


def test_sustain_exact_leaves_every_other_field_alone():
    default = _instruments(_sng())
    exact = _instruments(_sng(sustain_exact=True))
    for d, e in zip(default, exact):
        assert d[0] == e[0], "attack/decay untouched"
        assert d[2] == e[2], "gatetimer untouched"


def test_hard_restart_is_on_by_default():
    """gatetimer bit $80 is Goattracker's 'no hard restart' flag
    (gsong.c:381). Clear, so gplay.c:930-937 writes adparam ($0F00) into
    $D405/$D406 for a frame before every note."""
    for _ad, _sr, gatetimer in _instruments(_sng()):
        assert not gatetimer & 0x80


def test_no_hard_restart_sets_the_flag_on_every_read_instrument():
    """Every record read out of the .sid, which is all of them but the first.
    Instrument 1 is Goattracker's own empty "Clear Voice" slot, written rather
    than read, and it keeps the convention Goattracker writes for it."""
    records = _instruments(_sng(no_hard_restart=True))
    assert len(records) > 1
    for _ad, _sr, gatetimer in records[1:]:
        assert gatetimer & 0x80


def test_no_hard_restart_does_not_set_the_legato_bit():
    """Bit $40 is a different thing: it suppresses the gate-off as well, so a
    note would never release. Only $80 is wanted."""
    for _ad, _sr, gatetimer in _instruments(_sng(no_hard_restart=True))[1:]:
        assert not gatetimer & 0x40


def test_the_two_options_are_independent():
    base = _sng()
    a = _sng(sustain_exact=True)
    b = _sng(no_hard_restart=True)
    both = _sng(sustain_exact=True, no_hard_restart=True)
    assert len({base, a, b, both}) == 4

    ia, ib, iboth = _instruments(a), _instruments(b), _instruments(both)
    for ra, rb, rboth in zip(ia, ib, iboth):
        assert rboth[1] == ra[1], "sustain comes from --sustain-exact"
        assert rboth[2] == rb[2], "gatetimer comes from --no-hard-restart"


@pytest.mark.parametrize("opts", [
    {},
    {"sustain_exact": True},
    {"no_hard_restart": True},
    {"sustain_exact": True, "no_hard_restart": True},
])
def test_instrument_1_stays_the_empty_clear_voice_slot(opts):
    """Instrument 1 is written, not read from the file, so neither option may
    touch it -- Goattracker starts every channel on it (gplay.c:223)."""
    assert _instruments(_sng(**opts))[0] == (0x00, 0x00, 0x02)
