"""A tie whose landing note restarts the instrument is a legato clone.

`goatwriter.legato_tie_clones`: in the legato-marker players (`note_flag`,
`goatwriter.legato_tie_family`) the instrument start is skipped by the note
byte's bit 7 and by nothing else -- status bit 5 only holds the gate open --
so a tie landing on a note with bit 7 clear keeps its gate AND restarts
pulse, envelope and effects (Auf Wiedersehen Monty `$E569-$E5A0`, read at
d52a1bf). `CMD_TONEPORTA 00` skips Goattracker's whole note init
(gplay.c:353-398), so such a tie is respelled as a plain note on a clone of
its instrument with gatetimer `$40` (no gate-off, gplay.c:930; player.s
`mt_nohr_legato`). Measured on Auf Wiedersehen Monty sub 0, 60 s, under
presets, packed and traced with siddump-rt (C:/t/tie-legato-clone/ticks.py):
voice-3 noise ticks 210 -> 269 (original 240), exact 45 -> 61, gate-on
edges 106/149/194 in both arms and the original; every added tick within
3 frames of an original one.

The figures above are HISTORICAL (2026-10-03, HEAD 3b1c66d, dirty tree).
"""
import json
import pathlib

import pytest

from h2g import goatwriter as G
from h2g.convert import convert
from h2g.detect import detect
from h2g.sidfile import load_sid
from songview import parse_sng

from corpus import CORPUS, needs_corpus

REPO_ROOT = pathlib.Path(__file__).resolve().parents[2]
NOTE = 0x60
REST = G.GT_REST
TIE = (G.CMD_TONEPORTA, 0x00)


def _preset_opts(name):
    import fidelity
    doc = json.loads((REPO_ROOT / "presets.json").read_text(encoding="utf-8"))
    return fidelity._preset_opts(doc, name)


def _convert(name, legato=True):
    # Both arms with the bit-7 free-note variants off
    # (`free_note_skips_two_stage`, tests/test_free_note_variant.py): they
    # are appended after the legato clones on the same family, and this file
    # measures the clones alone.
    real = G.legato_tie_family
    real_free = G.note_passes.free_note_skips_two_stage
    if not legato:
        G.note_passes.legato_tie_family = lambda sid, det: False
    G.note_passes.free_note_skips_two_stage = lambda sid, det: False
    try:
        lines = []
        sng = convert(str(CORPUS / name), log=lines.append, **_preset_opts(name))
    finally:
        G.note_passes.legato_tie_family = real
        G.note_passes.free_note_skips_two_stage = real_free
    return sng, lines


@pytest.fixture(scope="module")
def monty():
    if not CORPUS.is_dir():
        pytest.skip("corpus absent")
    old, _ = _convert("Auf_Wiedersehen_Monty.sid", legato=False)
    new, lines = _convert("Auf_Wiedersehen_Monty.sid")
    return parse_sng(old), parse_sng(new), lines


def _tie_rows(song):
    return [(p, r) for p, pat in enumerate(song.patterns)
            for r in range(len(pat) // 4)
            if NOTE <= pat[4 * r] <= 0xBC
            and (pat[4 * r + 2], pat[4 * r + 3]) == TIE]


# --- which players ----------------------------------------------------------

@needs_corpus
@pytest.mark.parametrize("name, want", [
    ("Auf_Wiedersehen_Monty.sid", True),   # read: $E569 LDA $EB2D / BMI
    ("Delta.sid", True),                   # $BF31, the same block
    ("Commando.sid", False),               # no bit-7 flag at all
    ("Mega_Apocalypse.sid", False),        # the block, but a zero-page store
])                                         # the decoder does not read
def test_the_family_is_the_bit7_gated_instrument_start(name, want):
    sid = load_sid(str(CORPUS / name))
    det = detect(sid, lambda *a, **k: None)
    assert G.legato_tie_family(sid, det) is want


def test_the_gate_must_test_the_flag_the_note_store_wrote():
    from types import SimpleNamespace
    det = SimpleNamespace(pattern_dialect="classic", note_flag=True)
    store = bytes.fromhex("C8B1048D2DEB297F")             # STA $EB2D
    gate = bytes.fromhex("AD2DEB3035BDB0EC9902D4")        # LDA $EB2D / BMI
    other = bytes.fromhex("AD2EEB3035BDB0EC9902D4")       # LDA $EB2E / BMI
    pad = bytes(16)
    assert G.legato_tie_family(SimpleNamespace(data=pad + store + pad + gate), det)
    assert not G.legato_tie_family(SimpleNamespace(data=pad + store + pad + other), det)
    assert not G.legato_tie_family(
        SimpleNamespace(data=pad + store + pad + gate),
        SimpleNamespace(pattern_dialect="classic", note_flag=False))


def test_a_bit7_landing_keeps_toneporta_and_an_unknown_pattern_keeps_it_all():
    tie = [NOTE, 0, *TIE]
    pats = [tie + [REST, 0, 0, 0] + tie + [REST, 0, 0, 0],
            tie + [REST, 0, 0, 0]]
    assert G.legato_tie_rows(pats, {0: frozenset({2}), 1: None}) == {(0, 0)}
    assert G.legato_tie_rows(pats, {0: frozenset(), 1: frozenset()}) == {
        (0, 0), (0, 2), (1, 0)}


def test_a_copy_inherits_its_sources_bit7_rows_by_note_column():
    a = [NOTE, 1, *TIE, NOTE + 1, 0, *TIE]
    b = [NOTE + 2, 1, 0, 0]
    copy_a = list(a)
    copy_a[3] = 0x05
    got = G.note_bit7_rows([a, b, copy_a, [NOTE + 9, 0, 0, 0]],
                           {0: frozenset({1}), 1: frozenset()}, 2)
    assert got == {0: frozenset({1}), 1: frozenset(), 2: frozenset({1}),
                   3: None}
    # A copy that might be an unknown source's is not attributed.
    got = G.note_bit7_rows([a, list(a), list(a)],
                           {0: frozenset({1}), 1: None}, 2)
    assert got[2] is None


# --- the respelling ---------------------------------------------------------

def test_the_tie_becomes_a_plain_note_on_a_legato_clone_and_the_base_returns():
    pat = [NOTE, 5, 0, 0,          # instrument 5 latched
           REST, 0, 0, 0,
           NOTE + 2, 0, *TIE,      # the tie -> clone of 5
           REST, 0, 0, 0,
           NOTE + 4, 0, 0, 0,      # inherits: 5 written back here
           NOTE + 5, 0, *TIE,      # a tie with no note after it
           REST, 0, 0, 0]          # -> 5 re-latched on the next row
    out, clones, declined = G.legato_tie_clones(
        [pat], {(0, 2), (0, 5)}, None, {5}, 20)
    assert clones == [(5, 20)] and declined == set()
    rows = [out[0][i:i + 4] for i in range(0, len(pat), 4)]
    assert rows[2] == [NOTE + 2, 20, 0, 0]
    assert rows[4] == [NOTE + 4, 5, 0, 0]
    assert rows[5] == [NOTE + 5, 20, 0, 0]
    assert rows[6] == [REST, 5, 0, 0]


def test_a_tie_on_the_last_row_or_an_unsettled_instrument_declines():
    last = [NOTE, 5, 0, 0, NOTE + 1, 0, *TIE]
    unsettled = [NOTE + 1, 0, *TIE, REST, 0, 0, 0]
    out, clones, declined = G.legato_tie_clones(
        [last, unsettled], {(0, 1), (1, 0)}, None, {5}, 20)
    assert clones == [] and declined == {(0, 1), (1, 0)}
    assert out == [last, unsettled]


def test_declines_to_the_old_spelling_when_the_instrument_numbers_run_out():
    pat = [NOTE, 5, 0, 0, NOTE + 1, 0, *TIE, REST, 0, 0, 0,
           NOTE, 6, 0, 0, NOTE + 1, 0, *TIE, REST, 0, 0, 0]
    rows = {(0, 1), (0, 4)}
    out, clones, declined = G.legato_tie_clones(
        [pat], rows, None, {5, 6}, G.GT_MAX_INSTRUMENTS)
    assert G.GT_MAX_INSTRUMENTS == 63          # gcommon.h MAX_INSTR - 1
    assert clones == [(5, 63)] and declined == {(0, 4)}
    assert out[0][16:20] == [NOTE + 1, 0, *TIE]
    out, clones, declined = G.legato_tie_clones(
        [pat], rows, None, {5, 6}, G.GT_MAX_INSTRUMENTS + 1)
    assert clones == [] and declined == rows and out == [pat]


def test_the_envelope_pass_leaves_a_respelled_tie_to_its_clone():
    pat = [NOTE, 5, 0, 0, REST, 0, 0, 0, NOTE + 1, 6, *TIE,
           REST, 0, 0, 0, REST, 0, 0, 0]
    env = {5: (0x11, 0x22), 6: (0x33, 0x44)}
    wrote = G._tied_instrument_envelopes([pat], env)[0]
    assert wrote != pat                         # the old spelling's writes
    assert G._tied_instrument_envelopes([pat], env, skip={(0, 2)})[0] == pat
    assert G._tied_instrument_envelopes([pat], env, only=set())[0] == pat
    assert G._tied_instrument_envelopes([pat], env, only={(0, 2)})[0] == wrote


@needs_corpus
def test_a_multispeed_song_keeps_the_old_spelling_because_greloc_slips():
    """gt2reloc bumps `numnohr` after mapping the instruments when -S > 1
    (greloc.c:811-815), so FIRSTLEGATOINSTR is one past the first legato
    record and player.s plays that one as a plain no-HR note. Measured on
    Star_Paws (-S2) before this decline: voice-1 siddump attacks 572 -> 967
    (original 571). Delta is in the family and packs at -S2."""
    old, _ = _convert("Delta.sid", legato=False)
    new, lines = _convert("Delta.sid")
    assert new == old
    assert any("kept CMD_TONEPORTA -- -S2 packs the first legato" in l
               for l in lines)


# --- Auf Wiedersehen Monty, end to end ----------------------------------------

@needs_corpus
def test_monty_respells_exactly_its_unflagged_ties(monty):
    old, new, lines = monty
    # 164 since tied slides (a slide event after a bit-5 note) spell their tie
    # on row 0 (tests/test_tied_slide.py): 150 before, +14, none of them
    # respelled -- the clone count below is unchanged.
    assert len(_tie_rows(old)) == 164
    assert len(_tie_rows(new)) == 164 - 33
    assert any("33 tie row(s) on 2 legato clone(s)" in l for l in lines)
    n_old = len(old.instruments)
    assert len(new.instruments) == n_old + 2
    on_clone = [(p, r) for p, pat in enumerate(new.patterns)
                for r in range(len(pat) // 4)
                if NOTE <= pat[4 * r] <= 0xBC and pat[4 * r + 1] > n_old]
    assert len(on_clone) == 33
    for p, r in on_clone:                       # a plain note: no command
        assert new.patterns[p][4 * r + 2:4 * r + 4] == [0, 0]


@needs_corpus
@pytest.mark.parametrize("name, replaced", [
    ("Auf_Wiedersehen_Monty.sid", 0),   # its preset writes real firstwaves
    ("Pandora.sid", 3),                 # every record on FIRSTWAVE_TESTBIT (2 before tied slides)
])
def test_clones_are_their_record_with_the_legato_bit_and_real_wave(name, replaced):
    old = parse_sng(_convert(name, legato=False)[0])
    new = parse_sng(_convert(name)[0])
    sid = load_sid(str(CORPUS / name))
    det = detect(sid, lambda *a, **k: None)
    n_old = len(old.instruments)
    bases = set()
    for p, pat in enumerate(new.patterns):
        for r in range(len(pat) // 4):
            c = pat[4 * r + 1]
            if c > n_old:
                bases.add((c, old.patterns[p][4 * r + 1]
                           or _latched(old, p, r)))
    assert bases
    lead = 1 if old.instruments[0].name == "Clear Voice" else 0
    real = 0
    for c, base in bases:
        clone, rec = new.instruments[c - 1], old.instruments[base - 1]
        assert clone.gatetimer == rec.gatetimer | G.GATETIMER_LEGATO
        assert not rec.gatetimer & G.GATETIMER_LEGATO
        assert (clone.ad, clone.sr, clone.wave_ptr, clone.pulse_ptr,
                clone.filt_ptr, clone.vib_ptr, clone.vib_delay) == (
            rec.ad, rec.sr, rec.wave_ptr, rec.pulse_ptr, rec.filt_ptr,
            rec.vib_ptr, rec.vib_delay)
        if rec.firstwave == G.FIRSTWAVE_TESTBIT:
            at = det.instr_start + (base - lead - 1) * det.instr_stride + 2
            assert clone.firstwave == sid.data[at] | 0x01
            assert clone.firstwave >= 0x10      # a waveform, no test bit
            real += 1
        else:
            assert clone.firstwave == rec.firstwave
    assert real == replaced


def _latched(song, p, r):
    pat = song.patterns[p]
    for q in range(r, -1, -1):
        if pat[4 * q + 1]:
            return pat[4 * q + 1]
    entries = G._entry_instruments(song.tracks, song.patterns).get(p, set())
    assert len(entries) == 1
    return next(iter(entries))


@needs_corpus
def test_monty_no_note_ever_plays_latched_on_a_clone(monty):
    """The leak the instrument latch would make: a note with an empty column
    after a clone row is legato too (gplay.c:912-913 latches, :930 tests the
    latched instrument). Walked over every orderlist, one lap plus the loop."""
    _, new, _ = monty
    clones ={i + 1 for i, ins in enumerate(new.instruments)
              if ins.gatetimer & G.GATETIMER_LEGATO}
    assert clones
    leaks = 0
    for track in G._lapped_tracks(new.tracks):
        cur, operand = 1, False
        for b in track:
            if operand:
                operand = False
                continue
            if b == 0xFF:
                operand = True
                continue
            if b >= 0xD0:
                continue
            pat = new.patterns[b]
            for r in range(len(pat) // 4):
                note, ins = pat[4 * r], pat[4 * r + 1]
                if note == 0xFF:
                    break
                if NOTE <= note <= 0xBC and not ins and cur in clones:
                    leaks += 1
                if ins:
                    cur = ins
            assert cur not in clones           # no pattern ends on a clone
    assert leaks == 0


@needs_corpus
def test_monty_moves_only_tie_relatch_and_envelope_rows(monty):
    """The byte-hash's other half: every row that differs from the old
    spelling is a respelled tie, a base written back, or an envelope command
    the clone made redundant -- and nothing outside the patterns and the
    appended clone records moves."""
    old, new, _ = monty
    assert old.tracks == new.tracks and old.tables == new.tables
    n_old = len(old.instruments)
    assert new.instruments[:n_old] == old.instruments
    kinds = {"tie": 0, "relatch": 0, "env": 0}
    for x, y in zip(old.patterns, new.patterns):
        for r in range(len(x) // 4):
            a, b = x[4 * r:4 * r + 4], y[4 * r:4 * r + 4]
            if a == b:
                continue
            if tuple(a[2:]) == TIE and b[2:] == [0, 0] and b[1] > n_old:
                kinds["tie"] += 1
            elif not a[1] and 0 < b[1] <= n_old and a[0] == b[0] \
                    and a[2:] == b[2:]:
                kinds["relatch"] += 1
            else:
                assert a[2] in (G.CMD_SETAD, G.CMD_SETSR) and b[2] == 0, (a, b)
                kinds["env"] += 1
    assert kinds == {"tie": 33, "relatch": 11, "env": 30}
