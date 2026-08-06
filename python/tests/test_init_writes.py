"""A player whose table addresses arrive from its init routine, not the code.

Devils Galop's table-read instructions carry placeholder operands pointing at
nine bytes of zeroes; the init routine at $18B3 writes the real addresses over
those operands before the first play call, and finishes by block-copying the
authored instrument records over a stale set. Read literally, the file names a
pattern table with `$1798 - $1797 - 1` = no entries, which is why it converted
to nothing.

The rule that keeps this safe is the same shape as the relocation's: init
writes are applied *only* to a file whose tables, read as they stand, name no
patterns at all. Applying them can therefore rescue a file that reads nothing,
and can never disturb one that reads correctly -- 45 of the 95 corpus files
have a findable set of init writes and exactly one has them applied.
"""
import struct

from h2g.convert import _detect_tables, _tables_readable
from h2g.detect import Detection
from h2g.sidfile import HLEN, SidFile, find_init_writes, load_sid

LOAD_ADDR = 0x1000
INIT_ADDR = 0x1000


def _sid(code: bytes, init_addr=INIT_ADDR, load_addr=LOAD_ADDR, pad=0):
    """A SidFile whose data section starts at `load_addr` with `code`."""
    data = bytes(HLEN - 1) + code + bytes(pad)
    return SidFile(path="", data=data, name="", author="", released="",
                   load_addr=load_addr, subtunes=1, init_addr=init_addr)


def _writes(code: bytes, init_addr=INIT_ADDR, pad=0):
    sid = _sid(code, init_addr, pad=pad)
    return find_init_writes(sid.data, sid.init_addr, sid.load_addr)


# --- reading the init routine ----------------------------------------------

def test_an_immediate_store_is_read_as_a_write():
    # LDA #$2A / STA $1010
    w = _writes(b"\xA9\x2A\x8D\x10\x10\x60", pad=64)
    assert w == {_sid(b"", pad=64).to_offset(0x1010): 0x2A}


def test_one_immediate_can_feed_several_stores():
    """$18BA/$18BD/$18C0/$18C3 all take the same LDA #$0A in the real file."""
    code = b"\xA9\x0A\x8D\x10\x10\x8D\x11\x10\x8D\x12\x10\x60"
    off = _sid(b"", pad=64).to_offset
    assert _writes(code, pad=64) == {off(0x1010): 0x0A, off(0x1011): 0x0A,
                                     off(0x1012): 0x0A}


def test_a_store_with_no_immediate_before_it_is_ignored():
    """Otherwise a store of whatever A happens to hold is invented."""
    assert _writes(b"\x8D\x10\x10\x60", pad=64) == {}


def test_reloading_a_from_memory_forgets_the_immediate():
    # LDA #$2A / LDA $1020 / STA $1010 -- A is no longer the immediate
    assert _writes(b"\xA9\x2A\xAD\x20\x10\x8D\x10\x10\x60", pad=64) == {}


def test_a_store_outside_the_file_is_ignored():
    assert _writes(b"\xA9\x2A\x8D\x00\xE0\x60", pad=64) == {}


def test_the_leading_jmp_chain_is_followed():
    """`init: JMP realinit` is near-universal, so the walk must step through it."""
    # $1000 JMP $1003 ; $1003 LDA #$2A / STA $1010
    code = b"\x4C\x03\x10" + b"\xA9\x2A\x8D\x10\x10\x60"
    assert _writes(code, pad=64) == {_sid(b"", pad=64).to_offset(0x1010): 0x2A}


def test_a_jmp_after_the_routine_has_started_ends_the_walk():
    """Devils Galop's init ends `JMP $12EB` into the player.

    Following that would read the play routine's per-frame `LDA #imm / STA abs`
    state writes as if they were init patches.
    """
    # LDA #$2A / STA $1010 / JMP $100B ; $100B LDA #$FF / STA $1011
    code = (b"\xA9\x2A\x8D\x10\x10\x4C\x0B\x10"
            + b"\xA9\xFF\x8D\x11\x10\x60")
    assert _writes(code, pad=64) == {_sid(b"", pad=64).to_offset(0x1010): 0x2A}


def test_rts_ends_the_walk():
    code = b"\xA9\x2A\x8D\x10\x10\x60\xA9\xFF\x8D\x11\x10"
    assert _writes(code, pad=64) == {_sid(b"", pad=64).to_offset(0x1010): 0x2A}


def test_an_undocumented_opcode_ends_the_walk_rather_than_desynchronising_it():
    code = b"\x02\xA9\x2A\x8D\x10\x10\x60"
    assert _writes(code, pad=64) == {}


# --- the block copy --------------------------------------------------------

def _block_copy(src=0x1040, dst=0x1020, length=4):
    return bytes([0xA2, 0x00,                       # LDX #$00
                  0xBD, src & 0xFF, src >> 8,       # LDA src,X
                  0x9D, dst & 0xFF, dst >> 8,       # STA dst,X
                  0xE8,                             # INX
                  0xE0, length,                     # CPX #length
                  0xD0, 0xF5,                       # BNE
                  0x60])                            # RTS


def test_a_block_copy_moves_its_source_over_its_destination():
    code = _block_copy()
    sid = _sid(code, pad=0x60)
    payload = bytearray(sid.data)
    for k in range(4):
        payload[sid.to_offset(0x1040) + k] = 0xE0 + k
    w = find_init_writes(bytes(payload), sid.init_addr, sid.load_addr)
    assert w == {sid.to_offset(0x1020) + k: 0xE0 + k for k in range(4)}


def test_a_copy_whose_source_runs_past_the_file_is_ignored():
    """An over-long length would otherwise read whatever follows the data."""
    assert _writes(_block_copy(src=0x1040, length=0xFF), pad=0x20) == {}


def test_a_copy_that_does_not_start_at_index_zero_is_ignored():
    code = bytearray(_block_copy())
    code[1] = 0x08                                  # LDX #$08
    assert _writes(bytes(code), pad=0x60) == {}


# --- the guard -------------------------------------------------------------

def test_tables_are_unreadable_when_the_bases_are_found_but_name_no_patterns():
    """`can_convert` alone is not enough -- Devils Galop passed it and read nothing."""
    assert not _tables_readable(Detection(track_lo=1, track_hi=2, pattern_lo=3,
                                          pattern_hi=4, pattern_used=0))
    assert _tables_readable(Detection(track_lo=1, track_hi=2, pattern_lo=3,
                                      pattern_hi=4, pattern_used=1))


def test_a_file_with_nothing_to_apply_stages_nothing():
    assert _sid(b"\x60", pad=64).with_init_writes() is None


def test_writes_that_change_no_byte_stage_nothing():
    """A store of the value already there is not a patch."""
    sid = _sid(b"\xA9\x00\x8D\x10\x10\x60", pad=64)
    assert sid.with_init_writes() is None


def test_a_file_that_already_reads_its_tables_is_never_patched():
    """The whole safety argument: the fallback is unreachable for a working file."""
    seen = []

    def fake_detect(sid, log):
        seen.append(sid)
        return Detection(track_lo=1, track_hi=2, pattern_lo=3, pattern_hi=4,
                         pattern_used=9)

    import h2g.convert as convert_mod
    real, convert_mod.detect = convert_mod.detect, fake_detect
    try:
        sid = _sid(b"\xA9\x2A\x8D\x10\x10\x60", pad=64)
        out, det = _detect_tables(sid, lambda _m: None)
    finally:
        convert_mod.detect = real

    assert out is sid                     # the original image, byte for byte
    assert det.pattern_used == 9
    assert len(seen) == 1                 # no second, patched attempt


# --- the file this was built for -------------------------------------------

CORPUS = r"C:/Users/mit/claude/c64server/SIDM2/SID/Hubbard_Rob/Devils_Galop.sid"


def _devils_galop():
    try:
        return load_sid(CORPUS)
    except OSError:
        return None


def test_devils_galop_names_its_real_tables_once_init_is_applied():
    sid = _devils_galop()
    if sid is None:
        return                            # corpus not present on this machine
    staged = sid.with_init_writes()
    assert staged is not None
    _, det = _detect_tables(sid, lambda _m: None)
    # $0A1E/$0A21 orderlists (3 apart, one per voice), $0A24/$0A50 patterns.
    assert det.track_lo == staged.to_offset(0x0A1E)
    assert det.track_hi == staged.to_offset(0x0A21)
    assert det.pattern_lo == staged.to_offset(0x0A24)
    assert det.pattern_hi == staged.to_offset(0x0A50)
    assert det.pattern_used == 0x2B       # 44 entries, was 0 before


def test_devils_galop_takes_its_instruments_from_the_copy_not_the_stale_set():
    sid = _devils_galop()
    if sid is None:
        return
    staged = sid.with_init_writes()
    src, dst = staged.to_offset(0x183B), staged.to_offset(0x1799)
    assert staged.data[dst:dst + 0x78] == sid.data[src:src + 0x78]
    assert sid.data[dst:dst + 8] != sid.data[src:src + 8]   # they really differ
