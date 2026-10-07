"""The reset idiom `LDA #imm / STA cell,X` on a voice's instrument cell.

`reset_idiom_census.py` lists every corpus file whose player writes a literal
into its per-voice instrument array, which is how Mega_Apocalypse's record 17
(eight zero bytes, loaded on two voices from frame 2) is a silent power-on
instrument rather than a missing one. Measured at v0.5.513 + the uncommitted
cycle-3 merge, 2026-10-07:

* 95 corpus files; 6 refuse and have no instrument table to census
  (Casio_Extended, Dont_Step_on_My_Wire, Era_of_Eidolon, Robs_Life,
  Task_Force, Up_up_and_Away);
* 51 of the 89 with a table carry the idiom, exactly one site each, at
  distance 0 (`LDA #imm` is the instruction before `STA cell,X`);
* 28 reset to an all-zero record, 23 to a non-zero one, and 4 of those 23
  (Auf_Wiedersehen_Monty, Kings_of_the_Beach_intro, Saboteur_II, Wiz) name an
  index at or past the counted records, so the byte run there is not an
  instrument at all;
* 51 of 51 execute in subtune 0's first frame (I_Ball, whose init waits on a
  flag its own interrupt clears, inside init) for X = 0, 1 and 2 with
  A = the literal -- a reset that runs, not dead code.

The other 38 converting files have exactly one `STA cell,X`, the pattern
reader's; their starting instrument is the array's file image
(`Detection.initial_instruments`). For the 51 that image is NOT the power-on
value: it differs from the literal, in at least one voice, in 34 of the 36
that have one (15 have none -- the array shape is absent -- and
One_on_One_Jordan_vs_Bird's reads 63 66 136, not an index array at all).
"""
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import reset_idiom_census as R                    # noqa: E402
from corpus import CORPUS, needs_corpus           # noqa: E402

NO_TABLE = {"Casio_Extended", "Dont_Step_on_My_Wire", "Era_of_Eidolon",
            "Robs_Life", "Task_Force", "Up_up_and_Away"}

# name: (index the reset writes, record all-zero, index past the counted records)
SITES = {
    "ACE_II": (10, False, False),
    "After_8": (15, False, False),
    "Arcade_Classics": (10, True, False),
    "Auf_Wiedersehen_Monty": (16, False, True),
    "Bangkok_Knights": (27, True, False),
    "BMX_Kidz": (10, True, False),
    "Chain_Reaction": (27, True, False),
    "Deep_Strike": (10, True, False),
    "Delta": (5, False, False),
    "Dragons_Lair_Part_II": (27, True, False),
    "Flash_Gordon": (17, True, False),
    "Food_Feud": (13, False, False),
    "Go_Go_Dash": (15, False, False),
    "I_Ball": (17, True, False),
    "IK_plus": (9, True, False),
    "International_Karate": (20, True, False),
    "Kings_of_the_Beach_ingame": (2, True, False),
    "Kings_of_the_Beach_intro": (15, False, True),
    "Knucklebusters": (27, True, False),
    "Lakers_vs_Celtics": (15, False, False),
    "Lightforce": (21, True, False),
    "Lion_Heart": (15, False, False),
    "Mega_Apocalypse": (17, True, False),
    "Mr_Meaner": (15, False, False),
    "Nemesis_the_Warlock": (15, True, False),
    "Nineteen": (27, True, False),
    "Off_the_Cuff": (15, False, False),
    "One_on_One_Jordan_vs_Bird": (15, False, False),
    "Pacific_Coast": (15, False, False),
    "Pandora": (10, True, False),
    "Powerplay_Hockey_USA_vs_USSR": (15, False, False),
    "Pygmies_Revenge": (15, False, False),
    "Radio_ACE": (15, False, False),
    "Ricochet": (15, False, False),
    "Rikky": (15, False, False),
    "Rock_Tells_the_Tale": (15, False, False),
    "Saboteur_II": (17, False, True),
    "Sanxion": (27, True, False),
    "Shockway_Rider": (12, True, False),
    "Sigma_Seven": (7, True, False),
    "Skate_or_Die_intro": (7, False, False),
    "Star_Paws": (19, True, False),
    "Sun_Never_Shines": (15, False, False),
    "Tarzan": (18, True, False),
    "Thanatos": (4, True, False),
    "Thundercats": (27, True, False),
    "Trans-Atlantic_Balloon_Challenge": (6, True, False),
    "W_A_R": (27, True, False),
    "W_A_R_Preview": (27, True, False),
    "Wiz": (27, False, True),
    "Zoolook": (27, True, False),
}


# --- the scanner, on bytes it can be wrong about -----------------------------

class _Flat:
    """A SidFile stand-in: address == offset."""

    def __init__(self, data: bytes):
        self.data = data

    def to_offset(self, addr):
        return addr

    def to_address(self, off):
        return off


TABLE, STRIDE, USED = 0x80, 8, 0x14
LOADER = bytes.fromhex("B5C9 0A0A0A A8 B98000".replace(" ", ""))  # LDA $C9,X ... LDA $0080,Y


def _image(code: bytes, table_bytes: bytes = bytes(8 * 4)) -> _Flat:
    """Code at $0000, the instrument table at $0080 (records 0..)."""
    img = bytearray(0x200)
    img[:len(LOADER)] = LOADER
    img[0x20:0x20 + len(code)] = code
    img[TABLE:TABLE + len(table_bytes)] = table_bytes
    return _Flat(bytes(img))


def _sites(code: bytes, table_bytes=bytes(8 * 4)):
    sid = _image(code, table_bytes)
    cells = R.find_cells(sid, TABLE, STRIDE, USED)
    return cells, R.find_sites(sid, cells, TABLE, STRIDE)


def test_the_cell_is_named_by_the_load_that_feeds_the_table_read():
    cells, _ = _sites(b"")
    assert cells == [("zp", 0xC9)]


def test_a_load_that_misses_the_table_names_no_cell():
    sid = _image(b"")
    assert R.find_cells(sid, TABLE + 0x100, STRIDE, USED) == []


def test_the_literal_directly_before_the_store_is_strict_and_reads_the_record():
    rec3 = bytes(range(1, 9))
    table = bytes(8 * 3) + rec3                 # records 0-2 zero, record 3 set
    cells, (sites, other) = _sites(bytes.fromhex("A903 95C9"), table)
    assert [(s.imm, s.distance, s.strict) for s in sites] == [(3, 0, True)]
    assert sites[0].record == rec3 and sites[0].all_zero is False
    assert other == 0


def test_an_all_zero_record_is_reported_as_one():
    _, (sites, _) = _sites(bytes.fromhex("A902 95C9"))
    assert sites[0].all_zero is True


def test_a_record_past_the_image_is_none_not_zero():
    sid = _image(bytes.fromhex("A9F0 95C9"))
    cells = R.find_cells(sid, TABLE, STRIDE, USED)
    (site,), _ = R.find_sites(sid, cells, TABLE, STRIDE)
    assert site.record is None and site.all_zero is None


def test_stores_that_leave_a_alone_do_not_end_the_walk():
    # LDA #5 / STA $50 / STA $51 / STA $C9,X: distance 2
    _, (sites, _) = _sites(bytes.fromhex("A905 8550 8551 95C9"))
    assert [(s.imm, s.distance) for s in sites] == [(5, 2)]


@pytest.mark.parametrize("between", [
    "AD0030",       # LDA abs
    "8A",           # TXA
    "6905",         # ADC #
    "0A",           # ASL A
    "D002",         # BNE (control may not reach the store)
    "4C0000",       # JMP
    "2000F0",       # JSR
])
def test_an_instruction_that_replaces_a_or_leaves_the_path_ends_the_walk(between):
    _, (sites, _) = _sites(bytes.fromhex("A905" + between + "95C9"))
    assert sites == []


def test_the_walk_gives_up_after_the_limit():
    # Literal counts, not R.WALK_LIMIT: a test written in terms of the
    # constant passes for any value of it. Six instructions are examined.
    assert R.WALK_LIMIT == 6
    _, (sites, _) = _sites(bytes.fromhex("A905" + "EA" * 6 + "95C9"))
    assert sites == []
    _, (sites, _) = _sites(bytes.fromhex("A905" + "EA" * 5 + "95C9"))
    assert [s.distance for s in sites] == [5]


def test_a_non_literal_store_is_counted_apart_from_the_idiom():
    # `LDA ($FB),Y / STA $C9,X` is the pattern reader writing a notated
    # instrument: not a power-on reset.
    _, (sites, other) = _sites(bytes.fromhex("B1FB 95C9".replace(" ", "")))
    assert sites == [] and other == 1


def test_a_literal_stored_to_another_cell_is_not_the_idiom():
    _, (sites, other) = _sites(bytes.fromhex("A905 95CA"))
    assert sites == [] and other == 0


# --- the corpus --------------------------------------------------------------

@pytest.fixture(scope="module")
def census():
    return {f.stem: R.census_file(f) for f in sorted(CORPUS.glob("*.sid"))}


@needs_corpus
def test_the_files_with_no_instrument_table_are_the_six_that_refuse(census):
    assert {n for n, c in census.items() if c.refused} == NO_TABLE


@needs_corpus
def test_the_corpus_census_is_exactly_the_pinned_list(census):
    got = {}
    for n, c in census.items():
        if c.sites:
            assert len(c.sites) == 1, (n, c.sites)
            s = c.sites[0]
            got[n] = (s.imm, s.all_zero, s.imm >= c.instr_used)
    assert got == SITES


@needs_corpus
def test_every_site_is_strict_and_in_the_cell_the_loader_reads(census):
    for n in SITES:
        c = census[n]
        (s,) = c.sites
        assert s.strict, n
        assert s.cell in c.cells, n


@needs_corpus
def test_the_other_converting_files_have_a_cell_and_no_literal_write(census):
    rest = {n: c for n, c in census.items()
            if not c.refused and n not in SITES}
    assert len(rest) == 38
    for n, c in rest.items():
        assert c.cells, n               # the loader was found: absence is real
        assert c.other_writes >= 1, n   # only the pattern reader writes it


@needs_corpus
def test_mega_apocalypse_is_the_zero_page_spelling_the_array_shape_misses(census):
    (s,) = census["Mega_Apocalypse"].sites
    assert s.cell == ("zp", 0xC9) and s.imm == 0x11 and s.all_zero is True
    assert s.store_at == 0x4AC8
    assert [n for n in SITES if census[n].sites[0].cell[0] == "zp"] == \
        ["Mega_Apocalypse"]


@needs_corpus
def test_the_zero_and_nonzero_split(census):
    zero = sorted(n for n, v in SITES.items() if v[1])
    assert len(zero) == 28 and len(SITES) - len(zero) == 23
    assert sorted(n for n, v in SITES.items() if v[2]) == [
        "Auf_Wiedersehen_Monty", "Kings_of_the_Beach_intro", "Saboteur_II",
        "Wiz"]


@needs_corpus
def test_every_site_runs_at_power_on_for_all_three_voices():
    pytest.importorskip("py65")
    for n in SITES:
        c = R.census_file(CORPUS / f"{n}.sid")
        (s,) = c.sites
        hits = R.trace_sites(CORPUS / f"{n}.sid", c.sites)[s.store_at]
        assert sorted({h.x for h in hits}) == [0, 1, 2], n
        assert {h.a for h in hits} == {s.imm}, n
        # The first frame, except I_Ball: its init waits on a flag its own
        # interrupt clears, and the reset runs in that interrupt, inside init.
        assert min(h.frame for h in hits) == (-1 if n == "I_Ball" else 0), n
