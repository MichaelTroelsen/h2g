"""The interleaved (ILV) dialect's grammar constants, pinned against the
players they were read from.

`patterns.py` reads ILV_END, ILV_REST, ILV_TIE and ILV_COMMAND_OPERANDS out
of Radio_ACE's player at named addresses (its comment block above
`_build_raw_pattern_ilv` quotes the disassembly), and says the other five
carriers spell the same code -- four byte-identical, Lakers_vs_Celtics at
+$0C. Nothing re-read those bytes on a suite run: `test_interleaved_classic.py`
exercises the decoder THROUGH the constants and `test_ilv_grammar.py` covers
the `$FD nn` orderlist transpose. This file re-reads the player each run, so
a constant that drifts from the bytes fails here rather than in a decode.

The six files are not identified as Rob_Hubbard by SIDId (they match
`Jason_Page/RobTracker`) and the user has set them behind the 83 Hubbard
files; this pins what already ships, it adds no emission.
"""
import pathlib

import pytest

from h2g.patterns import (ILV_COMMAND_OPERANDS, ILV_END, ILV_REST, ILV_SLIDE,
                          ILV_ARP, ILV_TIE)
from h2g.sidfile import load_sid

CORPUS = pathlib.Path(r"C:/Users/mit/claude/c64server/SIDM2/SID/Hubbard_Rob")
# The five that spell the block at Radio_ACE's addresses, and Lakers at +$0C
# (patterns.py: "Lakers spells the same code at $1180 with its tables $28
# higher; the other four are byte-identical here").
AT_RADIO_ACE = ["Radio_ACE", "Go_Go_Dash", "Lion_Heart", "Pacific_Coast",
                "Sun_Never_Shines"]
SHIFTED = {"Lakers_vs_Celtics": 0x0C}
JMP_NEXT_EVENT = 0x116C      # every command handler ends `JMP $116C`


def _sid(name):
    p = CORPUS / f"{name}.sid"
    if not p.exists():
        pytest.skip(f"corpus file absent: {p}")
    return load_sid(str(p))


def _byte(sid, addr):
    return sid.data[sid.to_offset(addr)]


def _word(sid, addr):
    return bytes(sid.data[sid.to_offset(addr):sid.to_offset(addr) + 2])


def _dispatch(sid, start):
    """{command byte: handler address} from the `CMP #imm / BEQ rel` chain
    at `start`, walked until the chain breaks."""
    out, a = {}, start
    while _byte(sid, a) == 0xC9 and _byte(sid, a + 2) == 0xF0:
        rel = _byte(sid, a + 3)
        out[_byte(sid, a + 1)] = a + 4 + (rel - 256 if rel > 127 else rel)
        a += 4
    return out, a


def _iny_count(sid, handler, shift):
    """INY opcodes from the handler to its `JMP $116C` (+shift on Lakers).
    The first INY steps past the command byte itself, so a handler with n
    operands carries n + 1."""
    jmp = JMP_NEXT_EVENT + shift
    a, n = handler, 0
    for _ in range(80):
        if (_byte(sid, a) == 0x4C and _byte(sid, a + 1) == (jmp & 0xFF)
                and _byte(sid, a + 2) == jmp >> 8):
            return n
        if _byte(sid, a) == 0xC8:
            n += 1
        a += 1
    raise AssertionError(f"no JMP ${jmp:04X} within 80 bytes of ${handler:04X}")


@pytest.mark.parametrize("name", AT_RADIO_ACE + list(SHIFTED))
def test_the_markers_are_the_bytes_the_player_compares_against(name):
    sid = _sid(name)
    s = SHIFTED.get(name, 0)
    # $1228 CMP #$81 -- the lookahead that ends a pattern.
    assert _word(sid, 0x1228 + s) == bytes([0xC9, ILV_END])
    # $1238 and $1264 CMP #$60 -- the rest, tested twice on the note path.
    assert _word(sid, 0x1238 + s) == bytes([0xC9, ILV_REST])
    assert _word(sid, 0x1264 + s) == bytes([0xC9, ILV_REST])
    # $1174 AND #$40 (a $C0-$FF byte is a duration), $117C AND #$20 (the tie
    # flag, saved per voice), $1184 AND #$1F (the five-bit wait), and the
    # note path re-reading the flag at $12AC.
    assert _word(sid, 0x1174 + s) == bytes([0x29, 0x40])
    assert _word(sid, 0x117C + s) == bytes([0x29, ILV_TIE])
    assert _word(sid, 0x1184 + s) == bytes([0x29, 0x1F])
    assert _word(sid, 0x12AC + s) == bytes([0x29, ILV_TIE])


@pytest.mark.parametrize("name", AT_RADIO_ACE + list(SHIFTED))
def test_the_command_table_is_the_players_dispatch_chain(name):
    """The `$80-$BF` dispatch at $118E-$11AE compares on the exact value;
    ILV_COMMAND_OPERANDS must name exactly those values, and each handler's
    operand count is its INY count less the one that consumes the command
    byte. `$81` is not in the chain -- it is the end marker, met only by the
    lookahead -- and neither is anything the table does not name."""
    sid = _sid(name)
    s = SHIFTED.get(name, 0)
    handlers, end = _dispatch(sid, 0x118E + s)
    assert end == 0x11AE + s, f"chain ended at ${end:04X}"
    assert set(handlers) == set(ILV_COMMAND_OPERANDS)
    assert ILV_END not in handlers
    for cmd, handler in handlers.items():
        assert _iny_count(sid, handler, s) == ILV_COMMAND_OPERANDS[cmd] + 1, (
            f"${cmd:02X}: handler ${handler:04X}")
    assert ILV_COMMAND_OPERANDS[ILV_SLIDE] == 2 and ILV_COMMAND_OPERANDS[ILV_ARP] == 1


def test_the_constants_do_not_collide():
    assert ILV_REST == 0x60 and ILV_END == 0x81
    assert ILV_REST not in ILV_COMMAND_OPERANDS
    assert 0x80 <= min(ILV_COMMAND_OPERANDS) and max(ILV_COMMAND_OPERANDS) <= 0xBF
    assert ILV_TIE & 0x1F == 0, "the tie flag must sit outside the wait bits"
    assert ILV_TIE & 0x40 == 0, "and outside the duration marker bit"
