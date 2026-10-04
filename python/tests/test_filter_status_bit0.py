"""Does a status-bit-$01 record reach the classic filter block? Per file.

`tests/test_filter_fetch_hold.py` left a lead: in Saboteur_II a record whose
status byte has bit $01 set takes a path that leaves past the filter block,
so the original never writes $D416 for it -- and seven files carry records
with both $20 (filter on) and $01 set, for which we emit filter blocks:
Delta_Mix-E-Load_loader [20], Dragons_Lair_Part_II [20], Food_Feud [4, 8],
Knucklebusters [1, 6, 7, 19, 20], Lightforce [1, 2, 15, 16], Sanxion [1, 2]
and the held Powerplay_Hockey_USA_vs_USSR [14, 17] (re-measured at 42f3f4a,
records in `range(instr_used - 1)`, the range `filters._filter_entries` reads).

**Bit $01 is two different routines in the classic-filter players, and only
one of them bypasses.** Read from each file's disassembly
(`python dis6502.py <sid> --find 'AD ?? ?? 29 01 F0'`):

* The TABLE-PROGRAM dialect (Saboteur_II $F331): bit $01 walks a per-record
  waveform/frequency program through `LDA ($F8),Y`, and every way out of it
  is `JMP $F45F` (the ctrl/freq write-out) or `JMP $F477` (the voice loop's
  INC/DEX) -- both past the filter block at $F41C. Nine files: Bangkok_Knights,
  Nemesis_the_Warlock, Nineteen, Pandora, Powerplay_Hockey_USA_vs_USSR,
  Saboteur_II, Star_Paws, Thundercats, Wiz.
* The WARHAWK DRUM dialect (Knucklebusters $074E, and byte-for-byte the same
  38-byte block in the other six):

      074E  AD 91 09  LDA $0991       ; status
      0751  29 01     AND #$01
      0753  F0 26     BEQ $077B
      0755  BD 85 09  LDA $0985,X     ; drum counter   -> BEQ $077B
      075A  BD 49 09  LDA $0949,X     ; note duration  -> BEQ $077B
      ...                             ; DEC counter / gate mask #$FE, BNE $077B
      0776  A9 80     LDA #$80        ; ... or noise
      0778  9D 4F 09  STA $094F,X
      077B  AD 91 09  LDA $0991       ; falls into the bit-$02 test

  Every exit lands on the next bit test, and from there every path reaches
  the filter block ($080E). Seven files: Deep_Strike, Delta_Mix-E-Load_loader,
  Dragons_Lair_Part_II, Food_Feud, Knucklebusters, Lightforce, Sanxion.

The five remaining classic-filter files (ACE_II, Auf_Wiedersehen_Monty,
I_Ball, IK_plus, Trans-Atlantic_Balloon_Challenge) test no bit $01 on the
status byte at all.

So **all six named non-held files write the filter for their $21 records**,
and the filter blocks we emit for them are right; no converter change. The
one file whose $21 records ride a bypassing path is Powerplay, which is on
hold (`hold.ON_HOLD`), so nothing is opened for it here.

The reading is a control-flow walk, not a pattern: from the bit-set successor
of `LDA status / AND #$01 / Bxx`, follow every branch both ways and every
JMP, step over JSR, and stop at the filter block's first byte. An exit
(DEX, RTS, an indirect JMP or an undecodable byte) reached without passing it
is a bypass. `test_a_retargeted_jump_changes_the_reading` proves it can fail.
"""
import sys
from pathlib import Path

from corpus import CORPUS, needs_corpus  # noqa: E402

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import dis6502 as D  # noqa: E402
import hold  # noqa: E402
from h2g.detect import FILTER_ENABLE_BIT, FILTER_SHAPE, detect  # noqa: E402
from h2g.search import search_file  # noqa: E402
from h2g.sidfile import load_sid  # noqa: E402
from test_filter_fetch_hold import fetch_frame_reading  # noqa: E402

DRUM_BIT = 0x01

# The files the opening record named (Powerplay is held, read but not named).
NAMED = ("Delta_Mix-E-Load_loader", "Dragons_Lair_Part_II", "Food_Feud",
         "Knucklebusters", "Lightforce", "Sanxion")

BYPASSES = {"Bangkok_Knights", "Nemesis_the_Warlock", "Nineteen", "Pandora",
            "Powerplay_Hockey_USA_vs_USSR", "Saboteur_II", "Star_Paws",
            "Thundercats", "Wiz"}
REACHES = {"Deep_Strike", "Delta_Mix-E-Load_loader", "Dragons_Lair_Part_II",
           "Food_Feud", "Knucklebusters", "Lightforce", "Sanxion"}
NO_BIT01 = {"ACE_II", "Auf_Wiedersehen_Monty", "I_Ball", "IK_plus",
            "Trans-Atlantic_Balloon_Challenge"}


def _decode_at(sid, data: bytes, addr: int):
    off = sid.to_offset(addr)
    if not 0 <= off < len(data):
        return None
    return D.decode(data, off, addr)


def walk_to_filter(sid, data: bytes, start: int, filt: int, limit: int = 4000):
    """(reaches_filter, exits): every path from `start`, stopping at `filt`.

    `exits` is the sorted tuple of (kind, address) ends some path reaches
    WITHOUT passing `filt`: the voice loop's DEX, an RTS/RTI/BRK, an indirect
    JMP, or an undecodable byte. Empty means every path writes the filter.
    """
    seen, stack, exits, reached = set(), [start], set(), False
    while stack and len(seen) < limit:
        a = stack.pop()
        if a in seen:
            continue
        seen.add(a)
        if a == filt:
            reached = True
            continue
        ins = _decode_at(sid, data, a)
        if ins is None or ins.mnemonic == "???":
            exits.add(("bad", a))
            continue
        m, nxt = ins.mnemonic, (a + ins.size) & 0xFFFF
        if m in ("RTS", "RTI", "BRK", "DEX"):
            exits.add((m, a))
        elif m == "JMP":
            if ins.mode == "ind":
                exits.add(("JMPind", a))
            else:
                stack.append(ins.operand)
        elif ins.mode == "rel":
            stack += [ins.target(), nxt]
        else:
            stack.append(nxt)            # JSR is stepped over: it returns
    return reached, tuple(sorted(exits))


def bit01_reading(sid, data: bytes):
    """dict(filt, status, site, set_succ, reaches, exits), or None.

    `site` is the `LDA status` of the first `LDA status / AND #$01 / BEQ|BNE`
    in the player, `status` being the variable the classic filter block tests
    (FILTER_SHAPE's operand). None when there is no filter block or no such
    test.
    """
    i = search_file(data, FILTER_SHAPE)
    if i <= -1:
        return None
    filt = sid.to_address(i)
    status = data[i + 1] | data[i + 2] << 8
    for o in D.find_all(data, f"AD {status & 0xFF:02X} {status >> 8:02X} 29"):
        a = sid.to_address(o)
        test = D.decode(data, o + 3, a + 3)
        br = D.decode(data, o + 5, a + 5)
        if not (test.operand & DRUM_BIT and br.mnemonic in ("BEQ", "BNE")):
            continue
        set_succ = br.address + 2 if br.mnemonic == "BEQ" else br.target()
        reaches, exits = walk_to_filter(sid, data, set_succ, filt)
        return dict(filt=filt, status=status, site=a, set_succ=set_succ,
                    reaches=reaches, exits=exits)
    return None


def bypasses(reading) -> bool:
    return reading is not None and bool(reading["exits"])


def _classic_filter_files():
    out = {}
    for p in sorted(CORPUS.glob("*.sid")):
        sid = load_sid(str(p))
        try:
            det = detect(sid, lambda m: None)
        except Exception:                     # a file detect refuses is not ours
            continue
        if det.filter is not None:
            out[p.stem] = (sid, det)
    return out


def _filter_drum_records(sid, det):
    """Records the filter emitter can give a block to that also carry bit $01."""
    f = det.filter
    out = []
    for i in range(max(det.instr_used - 1, 0)):   # filters._filter_entries' range
        s = f.status + i * det.instr_stride
        if s < len(sid.data) and sid.data[s] & (FILTER_ENABLE_BIT | DRUM_BIT) \
                == FILTER_ENABLE_BIT | DRUM_BIT:
            out.append(i)
    return out


@needs_corpus
def test_named_files_write_the_filter_on_the_bit01_path():
    for stem in NAMED:
        sid = load_sid(str(CORPUS / f"{stem}.sid"))
        r = bit01_reading(sid, sid.data)
        assert r is not None, stem
        assert r["reaches"] and r["exits"] == (), (stem, r)


@needs_corpus
def test_knucklebusters_reads_as_the_docstring_quotes():
    sid = load_sid(str(CORPUS / "Knucklebusters.sid"))
    r = bit01_reading(sid, sid.data)
    assert (r["filt"], r["status"], r["site"], r["set_succ"]) == \
        (0x080E, 0x0991, 0x074E, 0x0755)
    assert r["reaches"] and r["exits"] == ()


@needs_corpus
def test_saboteur_ii_bit01_leaves_past_the_filter():
    sid = load_sid(str(CORPUS / "Saboteur_II.sid"))
    r = bit01_reading(sid, sid.data)
    assert (r["filt"], r["status"], r["site"], r["set_succ"]) == \
        (0xF41C, 0xF598, 0xF331, 0xF338)
    assert not r["reaches"]
    assert r["exits"] == (("DEX", 0xF47A),)


@needs_corpus
def test_corpus_census_of_the_two_bit01_dialects():
    files = _classic_filter_files()
    got = {"bypass": set(), "reach": set(), "none": set()}
    for stem, (sid, _) in files.items():
        r = bit01_reading(sid, sid.data)
        got["none" if r is None else "bypass" if bypasses(r) else "reach"].add(stem)
    assert got == {"bypass": BYPASSES, "reach": REACHES, "none": NO_BIT01}


@needs_corpus
def test_no_emitted_filter_record_rides_a_bypassing_path_outside_the_hold():
    """The consequence the converter rests on: if a non-held file's $21
    records ever take a path past the filter block, the blocks we emit for
    them play where the original writes nothing, and this must fail."""
    files = _classic_filter_files()
    riding = {}
    for stem, (sid, det) in files.items():
        recs = _filter_drum_records(sid, det)
        if recs and bypasses(bit01_reading(sid, sid.data)):
            riding[stem] = recs
    assert riding == {"Powerplay_Hockey_USA_vs_USSR": [14, 17]}
    assert all(hold.held(stem) for stem in riding)
    # and the named files do carry such records, so the guard is not vacuous
    named = {stem: _filter_drum_records(*files[stem]) for stem in NAMED}
    assert named == {"Delta_Mix-E-Load_loader": [20],
                     "Dragons_Lair_Part_II": [20], "Food_Feud": [4, 8],
                     "Knucklebusters": [1, 6, 7, 19, 20],
                     "Lightforce": [1, 2, 15, 16], "Sanxion": [1, 2]}


@needs_corpus
def test_a_retargeted_jump_changes_the_reading():
    """Probe lie #1: a reading that cannot change measures nothing.

    (a) Saboteur_II's three exits from the bit-$01 program, retargeted to the
        filter block's first byte, make it a player that writes the filter.
    (b) Knucklebusters' drum, with its first guard replaced by a JMP to the
        post-effects address its own fetch path leaves through, becomes one
        that bypasses it.
    """
    sid = load_sid(str(CORPUS / "Saboteur_II.sid"))
    data = bytearray(sid.data)
    for jmp in (0xF351, 0xF368, 0xF386):
        o = sid.to_offset(jmp)
        assert data[o] == 0x4C
        data[o + 1], data[o + 2] = 0x1C, 0xF4
    r = bit01_reading(sid, bytes(data))
    assert r["reaches"] and r["exits"] == ()

    # (c) retarget only the two exits on the `BPL $F36B` fall-through side: the
    #     taken side still leaves by `JMP $F45F` at $F386, so it still bypasses
    #     -- a walk that followed only fall-throughs would read "reaches".
    data = bytearray(sid.data)
    for jmp in (0xF351, 0xF368):
        o = sid.to_offset(jmp)
        data[o + 1], data[o + 2] = 0x1C, 0xF4
    r = bit01_reading(sid, bytes(data))
    assert r["reaches"] and r["exits"] == (("DEX", 0xF47A),)

    sid = load_sid(str(CORPUS / "Knucklebusters.sid"))
    data = bytearray(sid.data)
    _, _, tails, _ = fetch_frame_reading(sid, sid.data)
    post = tails[0][1]
    o = sid.to_offset(0x0755)
    data[o:o + 3] = bytes((0x4C, post & 0xFF, post >> 8))
    r = bit01_reading(sid, bytes(data))
    assert not r["reaches"] and r["exits"]
