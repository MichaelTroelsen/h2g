"""The disassembler, against encodings and against a block already decoded.

Two kinds of check. The unit ones pin every addressing mode's length and text,
because an operand read at the wrong width desynchronises everything after it
and a disassembly that is subtly wrong is worse than none -- this project reads
players to decide what a bit *means*.

The corpus one pins Rikky's `$13C2` block, which
H2G-CONVERSION-METHOD.md section 7.nnnn quotes instruction for instruction as
the evidence that bit `$04` in the 16-byte-record dialect is
`detect.TWO_STAGE_SHAPE`. If the tool and the write-up ever disagree, one of
them is wrong and this says so.
"""
import pathlib
import sys

from corpus import CORPUS, needs_corpus  # noqa: E402

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[1]))

import dis6502 as D  # noqa: E402
from h2g.search import search_file  # noqa: E402
from h2g.sidfile import HLEN, load_sid  # noqa: E402


def _one(raw, address=0x1000):
    return D.decode(bytes(raw), 0, address)


# --- addressing modes -------------------------------------------------------

def test_every_mode_has_the_length_the_cpu_reads():
    cases = [
        ([0xEA], 1, "NOP"),                        # imp
        ([0x0A], 1, "ASL A"),                      # acc
        ([0xA9, 0x40], 2, "LDA #$40"),             # imm
        ([0xA5, 0x54], 2, "LDA $54"),              # zp
        ([0xB5, 0x54], 2, "LDA $54,X"),            # zpx
        ([0xB6, 0x54], 2, "LDX $54,Y"),            # zpy
        ([0xA1, 0x54], 2, "LDA ($54,X)"),          # izx
        ([0xB1, 0x54], 2, "LDA ($54),Y"),          # izy
        ([0xAD, 0x04, 0xD4], 3, "LDA $D404"),      # abs
        ([0xBD, 0x04, 0xD4], 3, "LDA $D404,X"),    # abx
        ([0xB9, 0x04, 0xD4], 3, "LDA $D404,Y"),    # aby
        ([0x6C, 0x00, 0x10], 3, "JMP ($1000)"),    # ind
    ]
    for raw, size, text in cases:
        ins = _one(raw)
        assert ins.size == size, text
        assert ins.text() == text


def test_a_branch_names_its_destination_not_its_offset():
    """`F0 14` at $13C7 is the `BEQ $13DD` of section 7.nnnn: 2 for the
    instruction and $14 forward."""
    assert _one([0xF0, 0x14], 0x13C7).text() == "BEQ $13DD"


def test_a_backward_branch_is_signed():
    assert _one([0xD0, 0xFB], 0x1000).text() == "BNE $0FFD"


def test_an_unknown_opcode_is_one_byte_and_says_so():
    """Hubbard's players carry tables between routines, so a listing walks into
    data constantly. Guessing an operand width there desynchronises the rest;
    stepping one byte lets it resynchronise."""
    ins = _one([0xFF, 0xDE, 0xAD])
    assert ins.mnemonic == "???" and ins.size == 1


def test_a_truncated_instruction_at_the_end_of_the_file_is_not_a_guess():
    ins = D.decode(bytes([0xAD, 0x04]), 0, 0x1000)
    assert ins.mnemonic == "???"


# --- the SID annotation -----------------------------------------------------

def test_a_store_into_the_chip_is_named():
    """`$D404` is the register `wave`, `onset` and `nrun` all read."""
    lines = D.format_lines([_one([0x99, 0x04, 0xD4])])
    assert "ctrl (waveform/gate)" in lines[0]


def test_an_indexed_store_names_the_register_and_not_a_voice():
    """`,Y` holds the voice offset (0, 7, 14), so `$D404,Y` is every voice's
    control register -- naming voice 1 there would be a claim the code does not
    make."""
    line = D.format_lines([_one([0x99, 0x04, 0xD4])])[0]
    assert "v1" not in line
    assert "v2" in D.format_lines([_one([0x8D, 0x0B, 0xD4])])[0]


def test_an_address_outside_the_chip_gets_no_note():
    assert D.format_lines([_one([0xAD, 0x85, 0x16])])[0].count(";") == 0


# --- the offset/address mapping --------------------------------------------

def test_the_address_mapping_is_to_offsets_inverse():
    class _Sid:
        load_addr = 0x1000
        relocation = None
        data = b""

        def to_offset(self, addr):
            return addr - self.load_addr + HLEN - 1

    sid = _Sid()
    for addr in (0x1000, 0x13C2, 0x16FB):
        assert D.to_address(sid, sid.to_offset(addr)) == addr


# --- the pattern search -----------------------------------------------------

def test_find_all_agrees_with_the_signature_search_it_mirrors():
    """A pattern `detect.py` matches has to match here at the same offset, or
    the tool is answering a different question than the one being debugged --
    including `search_file`'s quirk of never testing offset 0."""
    data = bytes([0x29, 0x04] + [0x00] * 8 + [0x29, 0x04])
    assert D.find_all(data, "29 04")[0] == search_file(data, "29 04")
    assert D.find_all(data, "29 04") == [10]        # ...not [0, 10]


def test_find_all_honours_wildcards_and_the_limit():
    data = bytes([0x00, 0xAD, 0x11, 0x16, 0x29, 0x04,
                  0xAD, 0x22, 0x16, 0x29, 0x04])
    assert D.find_all(data, "AD ?? ?? 29 04") == [1, 6]
    assert D.find_all(data, "AD ?? ?? 29 04", limit=1) == [1]


# --- against a block the method doc already quotes --------------------------

@needs_corpus
def test_rikkys_two_stage_block_reads_as_the_method_doc_records_it():
    sid = load_sid(str(CORPUS / "Rikky.sid"))
    offset = sid.to_offset(0x13C2)
    lines = [ins.text() for ins
             in D.disassemble(sid.data, offset, 0x13C2, 10)]
    assert lines == [
        "LDA $1685",            # the effect byte
        "AND #$04",
        "BEQ $13DD",
        "LDA $168F,X",          # per-voice countdown
        "BEQ $13D7",
        "DEC $168F,X",
        "LDA $1704,Y",          # the attack waveform, record +9
        "JMP $13DA",
        "LDA $16FD,Y",          # ...or the record's own +2
        "STA $1652,X",
    ]


@needs_corpus
def test_the_block_is_found_by_the_pattern_that_names_it():
    """`--find` is the step that was a separate byte search and a hand-computed
    address before this file existed."""
    sid = load_sid(str(CORPUS / "Rikky.sid"))
    hits = D.find_all(sid.data, "AD ?? ?? 29 04 F0 ?? BD ?? ?? F0")
    assert hits and D.to_address(sid, hits[0]) == 0x13C2
