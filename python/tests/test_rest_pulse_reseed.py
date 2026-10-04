"""The zero-page triangle players reseed their pulse on a REST, and ours did not.

Samantha Fox voice 3 spanned 2756 against the original's 1984 and Spellbound
voice 0 3072 against 2208 (180 s, presets, 42f3f4a) under the correct
$F0/$0F masks. The cause was two readings, both pinned here:

* `detect._status_bit6_bvs` -- these players test status bit 6 first, as
  Commando does, but spell the stores zero page (Samantha Fox, and
  Mega_Apocalypse with the same shape) or compute a volume between
  the counter store and the BIT (Spellbound). STATUS_BIT6_SHAPE missed
  both, so their rests decoded as HOLDS: no KEYOFF, the gate held open
  across the rest, and nothing a reseed could hang on.
* `goatwriter.rest_reseed` -- the rest branch falls into the note's fetch
  tail, which reseeds the per-voice accumulator from the record; a
  Goattracker KEYOFF does not, so our sweep ran on through every release.
  `CMD_SETPULSEPTR` on the KEYOFF row is the reseed.
"""
import json
import shutil
import sys
import tempfile
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from corpus import CORPUS, needs_corpus                      # noqa: E402
from h2g import detect as D                                  # noqa: E402
from h2g.detect import Detection, detect                     # noqa: E402
from h2g.goatwriter import rest_reseed as RR                 # noqa: E402
from h2g.goatwriter.constants import (CMD_SETPULSEPTR,       # noqa: E402
                                      CMD_SETSR, CMD_TONEPORTA,
                                      GT_KEYOFF, GT_REST,
                                      _SONG_MAX_PATTERNS)
from h2g.search import search_file                           # noqa: E402
from h2g.sidfile import load_sid                             # noqa: E402

REPO_ROOT = Path(__file__).resolve().parents[2]
SAMANTHA = "Samantha_Fox_Strip_Poker.sid"
SPELLBOUND = "Spellbound.sid"
MEGA = "Mega_Apocalypse.sid"


def _quiet(*_a, **_k):
    pass


# --- the bit-6 test's other spellings ---------------------------------------

@needs_corpus
def test_the_fallback_spellings_reach_exactly_three_files_and_no_primary_one():
    """The rescue reads nothing the primary shape reads (the 61 files it
    matched are untouched) and adds exactly the three players read by hand."""
    primary, rescued = set(), set()
    for path in sorted(CORPUS.glob("*.sid")):
        data = load_sid(str(path)).data
        if search_file(data, D.STATUS_BIT6_SHAPE) >= 1:
            primary.add(path.name)
            assert D._status_bit6_bvs(data) == (
                search_file(data, D.STATUS_BIT6_SHAPE)
                + len(D.STATUS_BIT6_SHAPE.split())), path.name
        elif D._find_status_bit6(data):
            rescued.add(path.name)
    assert len(primary) == 61
    assert rescued == {SAMANTHA, SPELLBOUND, MEGA}


@needs_corpus
@pytest.mark.parametrize("name, target", [(SAMANTHA, 0x70F6),
                                          (SPELLBOUND, 0xE11C),
                                          (MEGA, 0x4B91)])
def test_the_bvs_found_is_the_rest_branch_read_by_hand(name, target):
    sid = load_sid(str(CORPUS / name))
    at = D._status_bit6_bvs(sid.data)
    rel = sid.data[at] - 256 if sid.data[at] > 127 else sid.data[at]
    assert at + 1 + rel == sid.to_offset(target)


def _zp_fetch(bit_operand: int = 0xB8) -> bytes:
    # LDA ($EE),Y / STA $A9,X / STA $B8 / AND #$1F / STA $A6,X / BIT zp / BVS
    return bytes([0x00, 0xB1, 0xEE, 0x95, 0xA9, 0x85, 0xB8, 0x29, 0x1F,
                  0x95, 0xA6, 0x24, bit_operand, 0x70, 0x3C, 0xEA])


def test_the_zero_page_spelling_must_test_the_cell_it_stored():
    assert D._status_bit6_bvs(_zp_fetch()) == 14
    assert D._status_bit6_bvs(_zp_fetch(0xB9)) == -1


def _late_fetch(between: bytes) -> bytes:
    # LDA ($CF),Y / STA $C7,X / STA $E4CD / AND #$1F / STA $E4CA,X, then
    # `between`, then BIT $E4CD / BVS
    return (bytes([0x00, 0xB1, 0xCF, 0x95, 0xC7, 0x8D, 0xCD, 0xE4, 0x29, 0x1F,
                   0x9D, 0xCA, 0xE4]) + between
            + bytes([0x2C, 0xCD, 0xE4, 0x70, 0x3A, 0xEA, 0xEA, 0xEA, 0xEA]))


def test_the_late_spelling_finds_its_bit_past_unrelated_code():
    volume = bytes([0xA9, 0x77, 0x38, 0xED, 0xC6, 0xE4])   # Spellbound $E0CE
    assert D._status_bit6_bvs(_late_fetch(volume)) == 13 + len(volume) + 4


def test_the_late_spelling_refuses_a_bit_after_the_operand_read():
    """`INY / LDA (zp),Y` before the BIT means the operand was consumed
    first -- whatever bit 6 does after that is not the skip."""
    assert D._status_bit6_bvs(_late_fetch(bytes([0xC8, 0xB1, 0xCF]))) == -1


def test_the_late_spelling_must_test_the_cell_it_stored():
    data = bytearray(_late_fetch(bytes([0xEA])))
    data[15] = 0xCE                                   # BIT $E4CE instead
    assert D._status_bit6_bvs(bytes(data)) == -1


@needs_corpus
@pytest.mark.parametrize("name, rest, join", [(SAMANTHA, 0x70F6, 0x70F8),
                                              (SPELLBOUND, 0xE11C, 0xE11E)])
def test_the_rest_branch_falls_into_the_notes_reseeding_tail(name, rest, join):
    """The premise `rest_reseed` stands on, read off the bytes: the rest
    target is a two-byte `DEC gate-mask` that lands on the address the note
    path JMPs to, and the tail from there writes $D402/$D403 and seeds the
    per-voice accumulator. A third file entering the dialect fails here
    before any conversion of it is trusted."""
    sid = load_sid(str(CORPUS / name))
    d = sid.data
    r, j = sid.to_offset(rest), sid.to_offset(join)
    assert d[r] in (0xC6, 0xCE) and r + 2 == j            # DEC zp, falls in
    assert d[r - 3] == 0x4C and d[r - 2] | d[r - 1] << 8 == join  # JMP join
    tail = d[j:j + 80]
    assert b"\x99\x02\xd4" in tail and b"\x99\x03\xd4" in tail
    det = detect(sid, _quiet)
    assert det.pulse_tri_per_voice and det.status_bit6


# --- the pass, on synthetic rows --------------------------------------------

def _det(per_voice: bool = True) -> Detection:
    det = Detection()
    det.pulse_tri_per_voice = per_voice
    det.pulse_tri_hi = 0x0E
    return det


def _pattern(*rows) -> list:
    out = []
    for r in rows:
        out += list(r)
    return out + [0xFF, 0, 0, 0]


NOTE = 0x80


def _run(patterns, tracks, sweeps=(2,), starts=None, det=None, ties=False,
         monkeypatch=None):
    starts = starts or {1: 0x11, 2: 0x22, 3: 0x33}
    pulse_starts = [starts.get(n, 0) for n in range(1, 5)]
    monkeypatch.setattr(RR, "_pulse_tri_program",
                        lambda sid, det, i, m: ([], 0) if i + 1 in sweeps
                        else None)
    logs = []
    out = RR.rest_pulse_reseeds(None, det or _det(), tracks, patterns,
                                pulse_starts, 4, 0, 1, logs.append, ties)
    return out, logs


def test_a_rest_on_a_sweeping_instrument_gets_its_programs_start(monkeypatch):
    pat = _pattern((NOTE, 2, 0, 0), (GT_REST, 0, 0, 0), (GT_KEYOFF, 0, 0, 0))
    (pats, tracks, n), _ = _run([pat], [[0, 0xFF, 0]], monkeypatch=monkeypatch)
    assert n == 1
    assert pats[0][8:12] == [GT_KEYOFF, 0, CMD_SETPULSEPTR, 0x22]


def test_a_static_instruments_rest_is_left_alone(monkeypatch):
    pat = _pattern((NOTE, 1, 0, 0), (GT_KEYOFF, 0, 0, 0))
    (pats, _, n), _ = _run([pat], [[0, 0xFF, 0]], monkeypatch=monkeypatch)
    assert n == 0 and pats[0] == pat


def test_a_rest_under_a_running_slide_is_left_alone(monkeypatch):
    """A one-shot command keeps a running portamento running
    (gplay.c:404-421), so the reseed would carry the slide into the rest."""
    pat = _pattern((NOTE, 2, 1, 4), (GT_REST, 0, 1, 4), (GT_KEYOFF, 0, 0, 0))
    (pats, _, n), logs = _run([pat], [[0, 0xFF, 0]], monkeypatch=monkeypatch)
    assert n == 0 and pats[0] == pat
    assert "1 running" in logs[0]


def test_a_rest_carrying_another_command_keeps_it(monkeypatch):
    pat = _pattern((NOTE, 2, 0, 0), (GT_KEYOFF, 0, CMD_SETSR, 0))
    (pats, _, n), logs = _run([pat], [[0, 0xFF, 0]], monkeypatch=monkeypatch)
    assert n == 0 and pats[0] == pat and "1 taken" in logs[0]


def test_a_tie_spelled_onto_a_rest_gives_way(monkeypatch):
    """`pending_tie` writes TONEPORTA 00 on a KEYOFF after a bit-5 note;
    neither player reads it there, so the reseed takes the column."""
    pat = _pattern((NOTE, 2, 0, 0), (GT_KEYOFF, 0, CMD_TONEPORTA, 0))
    (pats, _, n), _ = _run([pat], [[0, 0xFF, 0]], monkeypatch=monkeypatch)
    assert n == 1 and pats[0][4:8] == [GT_KEYOFF, 0, CMD_SETPULSEPTR, 0x22]


def test_the_instrument_is_carried_in_from_the_orderlist(monkeypatch):
    """Pattern 1 names nothing; the channel holds what pattern 0 left."""
    p0 = _pattern((NOTE, 2, 0, 0))
    p1 = _pattern((GT_KEYOFF, 0, 0, 0))
    (pats, tracks, n), _ = _run([p0, p1], [[0, 1, 0xFF, 0]],
                                monkeypatch=monkeypatch)
    assert n == 1 and pats[1][:4] == [GT_KEYOFF, 0, CMD_SETPULSEPTR, 0x22]
    assert tracks == [[0, 1, 0xFF, 0]]


def test_a_rest_pattern_entered_holding_two_instruments_is_cloned(monkeypatch):
    """Samantha Fox's case: one KEYOFF pattern behind several instruments.
    Each position gets the reseed of the instrument it holds; the copy is
    appended and only the positions that want it are repointed."""
    a, b = _pattern((NOTE, 2, 0, 0)), _pattern((NOTE, 3, 0, 0))
    rest = _pattern((GT_KEYOFF, 0, 0, 0))
    (pats, tracks, n), logs = _run(
        [a, b, rest], [[0, 2, 0xFF, 0], [1, 2, 0xFF, 0]], sweeps=(2, 3),
        monkeypatch=monkeypatch)
    assert n == 2 and len(pats) == 4 and "1 pattern copy" in logs[0]
    assert tracks[0][1] != tracks[1][1] and 3 in (tracks[0][1], tracks[1][1])
    assert pats[tracks[0][1]][:4] == [GT_KEYOFF, 0, CMD_SETPULSEPTR, 0x22]
    assert pats[tracks[1][1]][:4] == [GT_KEYOFF, 0, CMD_SETPULSEPTR, 0x33]


def test_a_position_whose_laps_disagree_writes_only_what_they_share(monkeypatch):
    """The loop re-enters position 1 holding instrument 3, the first pass
    holding 2: no single write is right, so none is made there."""
    a = _pattern((NOTE, 2, 0, 0))
    rest = _pattern((GT_KEYOFF, 0, 0, 0), (NOTE, 3, 0, 0))
    (pats, tracks, n), logs = _run([a, rest], [[0, 1, 1, 0xFF, 1]],
                                   sweeps=(2, 3), monkeypatch=monkeypatch)
    assert "disagree" in logs[0]
    assert pats[1] == rest and tracks[0][:3] == [0, 1, 2]
    assert pats[2][:4] == [GT_KEYOFF, 0, CMD_SETPULSEPTR, 0x33]


def test_a_full_pattern_table_drops_the_copy_not_the_song(monkeypatch):
    a, b = _pattern((NOTE, 2, 0, 0)), _pattern((NOTE, 3, 0, 0))
    rest = _pattern((GT_KEYOFF, 0, 0, 0))
    filler = [_pattern((GT_REST, 0, 0, 0))] * (_SONG_MAX_PATTERNS - 3)
    (pats, tracks, n), logs = _run(
        [a, b, rest] + filler, [[0, 2, 0xFF, 0], [1, 2, 0xFF, 0]],
        sweeps=(2, 3), monkeypatch=monkeypatch)
    assert len(pats) == _SONG_MAX_PATTERNS and n == 1
    assert "pattern table full" in logs[0]


def test_another_player_is_untouched(monkeypatch):
    pat = _pattern((NOTE, 2, 0, 0), (GT_KEYOFF, 0, 0, 0))
    (pats, tracks, n), _ = _run([pat], [[0, 0xFF, 0]], det=_det(False),
                                monkeypatch=monkeypatch)
    assert n == 0 and pats == [pat] and tracks == [[0, 0xFF, 0]]


def test_ties_are_off_by_default_and_placed_on_the_first_free_hold_row(monkeypatch):
    """The declined option (module docstring): it costs pitch. Pinned so it
    stays declined deliberately, and so its placement is what was measured."""
    pat = _pattern((NOTE, 2, 0, 0), (NOTE, 3, CMD_TONEPORTA, 0),
                   (GT_REST, 0, 5, 0x0F), (GT_REST, 0, 0, 0))
    (pats, _, n), _ = _run([pat], [[0, 0xFF, 0]], sweeps=(2, 3),
                           monkeypatch=monkeypatch)
    assert n == 0
    (pats, _, n), _ = _run([pat], [[0, 0xFF, 0]], sweeps=(2, 3), ties=True,
                           monkeypatch=monkeypatch)
    assert n == 1 and pats[0][12:16] == [GT_REST, 0, CMD_SETPULSEPTR, 0x33]


# --- end to end -------------------------------------------------------------

def _pulse_spans(name: str, seconds: int, voice: int):
    import fidelity as F
    from h2g import convert as C
    if not Path(F.SIDDUMP).exists() or not Path(F.GT2RELOC).exists():
        pytest.skip("siddump or gt2reloc not available here")
    doc = json.loads((REPO_ROOT / "presets.json").read_text(encoding="utf-8"))
    sid_path = CORPUS / name
    opts = F._preset_opts(doc, name)
    mult = doc["songs"][name]["multiplier"]
    wd = Path(tempfile.mkdtemp(prefix="rest_reseed_"))
    try:
        local = wd / "o.sid"
        shutil.copyfile(sid_path, local)
        cal, _ = F.table_calibration(sid_path, opts)
        sub, our_sub, _ = F.resolve_pair(sid_path, "auto")
        orig = F.run_siddump(local, seconds, sub, F.SIDDUMP, cal)
        # The harness's own window: where the original's subtune ends
        # inside it, both sides are compared over the music it plays.
        ended = F.original_ended(orig, seconds)
        if ended is not None and ended < seconds:
            seconds = ended
            orig = F.run_siddump(local, seconds, sub, F.SIDDUMP, cal)
        blob, _ = F.legalise_restarts(C.convert(str(sid_path), log=_quiet,
                                                **opts))
        packed = F.pack_sid(blob, wd, F.GT2RELOC, mult)
        assert packed is not None, "gt2reloc wrote no .sid"
        ours = F.run_siddump(packed, seconds, our_sub, F.SIDDUMP, calls=mult)
    finally:
        shutil.rmtree(wd, ignore_errors=True)
    n = seconds * 50
    return tuple(F._span(F.register_timeline(t[voice].pulse_events, n))
                 for t in (orig, ours))


@needs_corpus
@pytest.mark.parametrize("name, seconds, voice", [(SPELLBOUND, 30, 0),
                                                  (SAMANTHA, 100, 2)])
def test_our_band_no_longer_runs_past_the_originals(name, seconds, voice):
    """Spellbound voice 0's first rest is at frame 71 and Samantha Fox voice
    3's at frame 4561 (91 s); before this, both ran on to $DF1-$E00. Ours
    may fall short of the original (a reseed declined) but not exceed it by
    more than one step's overshoot."""
    orig, ours = _pulse_spans(name, seconds, voice)
    assert ours <= orig + 0x80, (name, voice, orig, ours)
