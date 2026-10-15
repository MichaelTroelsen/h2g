"""The reset-idiom literal, not the file image, is the instrument a voice starts
on -- and it is already in place before the voice's first read of the index.

`reset_idiom_census.py` found 36 corpus files that carry both a reset site
(`LDA #imm / STA cell,X`) and a file image of the per-voice instrument array
(`Detection.initial_instruments`); in 34 of them the image differs from the
literal in at least one voice. `apply_initial_instruments` therefore must not
start a voice on the image. It does not, since v0.5.524: `Detection.
init_instrument` (`detect._find_init_instrument`, read off the same
`LDA #imm / STA array,X / DEX / BPL` loop) wins in `tracks._initial_for`.

This file closes the two things that were still only asserted:

* the two independent readings agree -- `init_instrument` equals the census
  literal in all 36, so "the player's init writes it" and "the census found a
  literal store" name the same index;
* the ORDER. A literal stored in play frame 0 would still be wrong if a note of
  that voice read the index cell before the store ran. Traced with py65 over
  init and four play frames, measured 2026-10-13 at 8618f82: in all 36 files
  the store runs (play frame 0 in 35, inside init for I_Ball) before the first
  read of the cell for each of the three voices. Literal-first is therefore
  safe for subtune 0 everywhere; it is NOT a statement about later subtunes
  (26 of 166 start on the image: `note_passes._track_start`).
"""
import struct
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import reset_idiom_census as R                    # noqa: E402
from corpus import CORPUS, needs_corpus           # noqa: E402
from h2g import detect as D, sidfile              # noqa: E402
from h2g.detect import Detection                  # noqa: E402
import h2g.convert                             # noqa: E402,F401  (import order: patterns/goatwriter cycle)
from h2g.tracks import _initial_for               # noqa: E402

FRAMES = 4


def first_events(path, sites, cells, frames=FRAMES):
    """([(phase, kind, x)], status): every execution of a literal store and
    every read (`LDA cell` / `LDA cell,X`, absolute or zero page) of the
    instrument-index cell, in order. phase is -1 inside init, else the 0-based
    play call. Same machine model as `reset_idiom_census.trace_sites`."""
    py65 = pytest.importorskip("py65.devices.mpu6502")
    sid = sidfile.load_sid(str(path))
    m = py65.MPU()
    mem = m.memory
    for i, b in enumerate(sid.data[sidfile.HLEN - 1:]):
        if 0 <= sid.load_addr + i < 0x10000:
            mem[sid.load_addr + i] = b
    stores = {s.store_at for s in sites}
    cellset = {a for _kind, a in cells}
    events = []
    phase = [-1]

    def hook():
        pc = m.pc
        if pc in stores:
            events.append((phase[0], "STORE", m.x))
            return
        op = mem[pc]
        if op in (0xBD, 0xAD):
            if (mem[pc + 1] | mem[pc + 2] << 8) in cellset:
                events.append((phase[0], "READ", m.x))
        elif op in (0xB5, 0xA5):
            if mem[pc + 1] in cellset:
                events.append((phase[0], "READ", m.x))

    def vector():
        return (mem[0xFFFE] | mem[0xFFFF] << 8) or (mem[0x314] | mem[0x315] << 8)

    def push_return():
        m.stPush(((R.SENTINEL - 1) >> 8) & 0xFF)
        m.stPush((R.SENTINEL - 1) & 0xFF)

    def irq(frame):
        vec = vector()
        if not vec:
            return
        sp, pc, p = m.sp, m.pc, m.p
        m.stPush(R.SENTINEL >> 8)
        m.stPush(R.SENTINEL & 0xFF)
        m.stPush(p & ~0x10)
        m.p |= 0x04
        m.pc = vec
        exits = R.KERNAL_EXIT if not (mem[0xFFFE] | mem[0xFFFF] << 8) else ()
        phase[0] = frame
        k = 0
        while m.pc != R.SENTINEL and m.pc not in exits and k < R.FRAME_STEPS:
            hook()
            m.step()
            k += 1
        m.sp, m.pc, m.p = sp, pc, p

    m.sp = 0xFF
    push_return()
    m.pc, m.a, m.x, m.y = sid.init_addr, 0, 0, 0
    n = 0
    while m.pc != R.SENTINEL and n < R.INIT_STEPS:
        phase[0] = -1
        hook()
        before = m.pc
        m.step()
        n += 1
        if sid.play_addr:
            continue
        if n % R.IRQ_PERIOD == 0 and not m.p & 0x04:
            irq(-1)
        elif m.pc == before:
            break
    if m.pc != R.SENTINEL and sid.play_addr:
        return events, "init never returned"
    for f in range(frames):
        if sid.play_addr:
            phase[0] = f
            m.sp = 0xFF
            push_return()
            m.pc = sid.play_addr
            k = 0
            while m.pc != R.SENTINEL and k < R.FRAME_STEPS:
                hook()
                m.step()
                k += 1
        else:
            if not vector():
                break
            irq(f)
    return events, "ok"


def verdicts(events):
    """Per voice: 'store-first' when the voice's first literal store precedes
    its first read of the cell, 'READ-FIRST' when a read comes before the
    store, 'no-store' / 'no-read' where either never happens."""
    out = []
    for v in range(3):
        s = next((i for i, e in enumerate(events)
                  if e[1] == "STORE" and e[2] == v), None)
        r = next((i for i, e in enumerate(events)
                  if e[1] == "READ" and e[2] == v), None)
        if s is None:
            out.append("no-store")
        elif r is None:
            out.append("store-first")       # nothing read it in the window
        else:
            out.append("READ-FIRST" if r < s else "store-first")
    return out


# --- the probe itself, on hand-assembled players ---------------------------

CELL = 0x1100


def _psid(tmp_path, init_code, play_code, name):
    """PSID with `init_code` at $1000 and `play_code` at $1040."""
    img = bytearray(0x100)
    img[:len(init_code)] = init_code
    img[0x40:0x40 + len(play_code)] = play_code
    hdr = bytearray(0x7E)
    hdr[0:4] = b"PSID"
    hdr[4:6] = (2).to_bytes(2, "big")
    hdr[6:8] = (0x7C).to_bytes(2, "big")
    hdr[0x0A:0x0C] = (0x1000).to_bytes(2, "big")
    hdr[0x0C:0x0E] = (0x1040).to_bytes(2, "big")
    hdr[0x0E:0x10] = (1).to_bytes(2, "big")
    hdr[0x10:0x12] = (1).to_bytes(2, "big")
    hdr[0x7C:0x7E] = struct.pack("<H", 0x1000)
    path = tmp_path / name
    path.write_bytes(bytes(hdr) + bytes(img))
    return path


def _loop(body):
    """LDX #2 / L: <body> / DEX / BPL L / RTS."""
    return bytes([0xA2, 0x02]) + body + bytes([0xCA, 0x10, 0x100 - (len(body) + 3), 0x60])


# LDA #$07 / STA $1100,X                      -- the strict reset
STORE = bytes([0xA9, 0x07, 0x9D, CELL & 0xFF, CELL >> 8])
# LDA $1100,X                                  -- the player's read of the index
READ = bytes([0xBD, CELL & 0xFF, CELL >> 8])


def _run(tmp_path, init_code, play_code, store_at):
    path = _psid(tmp_path, init_code, play_code, "p.sid")
    site = R.Site(("abs", CELL), store_at - 2, store_at, 7, 0, 0, None)
    return first_events(path, [site], [("abs", CELL)])


def test_a_store_before_the_read_is_store_first(tmp_path):
    # play: LDX #2 / L: LDA #7 / STA cell,X / LDA cell,X / DEX / BPL L / RTS
    play = _loop(STORE + READ)
    ev, st = _run(tmp_path, bytes([0x60]), play, 0x1040 + 2 + 2)
    assert st == "ok"
    assert verdicts(ev) == ["store-first"] * 3
    assert min(e[0] for e in ev if e[1] == "STORE") == 0   # every frame stores


def test_a_read_before_the_store_is_read_first(tmp_path):
    # play: LDX #2 / L: LDA cell,X / LDA #7 / STA cell,X / DEX / BPL L / RTS
    play = _loop(READ + STORE)
    ev, st = _run(tmp_path, bytes([0x60]), play, 0x1040 + 2 + 3 + 2)
    assert st == "ok"
    assert verdicts(ev) == ["READ-FIRST"] * 3


def test_a_store_in_init_runs_in_phase_minus_one(tmp_path):
    init = _loop(STORE)
    play = _loop(READ)
    ev, st = _run(tmp_path, init, play, 0x1000 + 2 + 2)
    assert st == "ok"
    assert {e[0] for e in ev if e[1] == "STORE"} == {-1}
    assert verdicts(ev) == ["store-first"] * 3


# --- the corpus --------------------------------------------------------------

@pytest.fixture(scope="module")
def image_files():
    """{name: (path, census, detection)} for every census site file whose
    detection carries a 3-byte instrument-array image."""
    out = {}
    for p in sorted(CORPUS.glob("*.sid")):
        c = R.census_file(p)
        if c.refused or not c.sites:
            continue
        det = D.detect(sidfile.load_sid(str(p)), lambda s: None)
        if len(det.initial_instruments) == 3:
            out[p.stem] = (p, c, det)
    return out


@needs_corpus
def test_forty_three_site_files_carry_an_image_and_forty_one_differ(image_files):
    """36 and 34 at 6f346b6. The seven stride-16 players that spell the record
    multiply `ASL x4` (After_8, Kings_of_the_Beach_intro, Mr_Meaner,
    Off_the_Cuff, Pygmies_Revenge, Rikky, Rock_Tells_the_Tale) gained an image
    from `_reconcile_instrument_index`'s rescue, and all seven differ from the
    `$0F` literal (`$13 $09 $16`; Kings `$05 $05 $01`)."""
    assert len(image_files) == 43
    differ = sorted(
        n for n, (_p, c, det) in image_files.items()
        if any(b != c.sites[0].imm for b in det.initial_instruments))
    assert len(differ) == 41
    assert sorted(set(image_files) - set(differ)) == ["ACE_II", "BMX_Kidz"]


@needs_corpus
def test_init_instrument_is_the_census_literal_in_every_one(image_files):
    """Two independent readings of one fact: the census's literal store and
    detect's `LDA #imm / STA array,X / DEX / BPL`."""
    bad = {n: (det.init_instrument, c.sites[0].imm)
           for n, (_p, c, det) in image_files.items()
           if det.init_instrument != c.sites[0].imm}
    assert bad == {}


@needs_corpus
@pytest.mark.parametrize("base", [1, 2])
def test_the_option_starts_every_voice_on_the_literal_not_the_image(
        image_files, base):
    for n, (_p, c, det) in image_files.items():
        want = c.sites[0].imm + base
        assert [_initial_for(det, v, base) for v in range(3)] == [want] * 3, n


@needs_corpus
def test_the_literal_store_precedes_the_first_read_for_every_voice(image_files):
    """Literal-first is safe where no note can read the index before the reset
    has written it. Subtune 0, init plus four play frames."""
    pytest.importorskip("py65")
    phases = {}
    for n, (p, c, _det) in image_files.items():
        ev, st = first_events(p, c.sites, c.cells)
        assert st == "ok", (n, st)
        assert verdicts(ev) == ["store-first"] * 3, (n, verdicts(ev))
        phases[n] = {e[0] for e in ev if e[1] == "STORE"}
    assert phases.pop("I_Ball") == {-1}
    assert all(v == {0} for v in phases.values()), phases
