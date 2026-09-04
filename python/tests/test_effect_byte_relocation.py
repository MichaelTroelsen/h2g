"""`_effect_byte_address` must invert BOTH branches of `SidFile.to_offset`.

The probe computes record 0's `+7` address and searches for the player's own
`LDA base,Y`. It hand-inverted only `to_offset`'s plain branch, and carried a
comment excusing that: "a relocated file would need the relocated form instead,
but no such corpus file gets this far".

I_Ball is the counterexample. It moves $1000 bytes from $9000 to $E000 at init,
carries `effect_bit40` TRUE, reaches that line, and the naive inversion computes
$9712 -- an address in the file's own image that no instruction names. The
player reads the relocated copy and spells it `LDA $E712,Y`. So the probe
returned None on the one corpus file that needs the other branch, and every
routine gated on the effect byte was switched off for it.

What that cost is measurable and is the reason this test is worth its runtime:
with the address found, detection newly reports bit $80's SFX drum on I_Ball
(`effect_bit80` '' -> 'sfx', voice 2, pitch 72, period 6).
"""
from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import pytest  # noqa: E402
from corpus import CORPUS, needs_corpus  # noqa: E402
from h2g.sidfile import load_sid  # noqa: E402
from h2g import detect as D  # noqa: E402


def _quiet(*_a, **_k):
    pass


@needs_corpus
def test_the_relocated_file_resolves_its_effect_byte_address():
    sid = load_sid(str(CORPUS / "I_Ball.sid"))
    assert sid.relocation is not None, "I_Ball is the corpus's relocated file"
    det = D.detect(sid, log=_quiet)
    found = D._effect_byte_address(sid, det)
    assert found is not None, "the naive inversion alone returns None here"
    addr, zp = found
    assert 0 <= addr <= 0xFFFF


@needs_corpus
def test_the_address_is_taken_from_the_relocated_copy_not_the_image():
    """The naive address must genuinely find nothing -- else this proves nothing."""
    from h2g.search import search_file
    from h2g.sidfile import HLEN
    sid = load_sid(str(CORPUS / "I_Ball.sid"))
    det = D.detect(sid, log=_quiet)
    r = sid.relocation
    naive = det.instr_start - (HLEN - 1) + sid.load_addr + 7
    moved = naive - r.src + r.dst
    assert r.src <= naive < r.src + r.length, "the naive address is inside the moved window"
    assert search_file(sid.data, "B9 %02X %02X" % (naive & 0xFF, naive >> 8)) <= -1, \
        "if the NAIVE address matched, this file would not exercise the fix"
    assert search_file(sid.data, "B9 %02X %02X" % (moved & 0xFF, moved >> 8)) > -1


@needs_corpus
def test_the_relocation_branch_unlocks_the_sfx_drum_reading():
    # The consequence, pinned: without the address, these four fields are unset.
    det = D.detect(load_sid(str(CORPUS / "I_Ball.sid")), log=_quiet)
    assert det.effect_bit80 == "sfx"
    assert (det.sfx_voice, det.sfx_pitch, det.sfx_period) == (2, 72, 6)


@needs_corpus
@pytest.mark.parametrize("name", ["Commando.sid", "Delta.sid", "Warhawk.sid"])
def test_a_file_without_a_relocation_is_untouched_by_the_new_branch(name):
    """The relocation is consulted ONLY where the plain form found nothing.

    `find_relocation` and `find_init_writes` are ordered the same way, and the
    property that matters is that a file which already reads correctly cannot
    be disturbed -- so these files must resolve with `relocation` None and the
    branch never reached.
    """
    p = CORPUS / name
    if not p.exists():
        pytest.skip(f"{name} not in this corpus")
    sid = load_sid(str(p))
    assert sid.relocation is None
    D._effect_byte_address(sid, D.detect(sid, log=_quiet))  # must not raise
