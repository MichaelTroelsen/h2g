"""gt2reloc's multispeed slip lands on a decoy, not on a legato clone.

At -S2 and above greloc.c maps the instruments -- legato records last, in
number order (:362-370) -- and only THEN bumps `numnohr` "for multispeed
stability" (:811-815):

    if (multiplier > 1)
    {
      fixedparams = 0;
      numlegato++;
      numnohr++;
    }

so `insertdefine("FIRSTLEGATOINSTR", numnormal + numnohr + 1)` (:1134) is one
past the first legato record, and player.s `mt_nohr_legato: cmp
#FIRSTLEGATOINSTR / bcc mt_skiphr` gates that record off at the fetch like a
no-HR note. Before this spelling the legato clones were withheld at -S>1
(Star_Paws voice 1, historical: siddump attacks 572 -> 967, original 571).

`goatwriter.legato_slip_decoy` hands the packer a record to slip on: a legato
copy of the instrument a voice already holds, numbered below every clone and
named on a rest row whose next instrument byte precedes the next note, so no
note is ever fetched holding it. These tests read the thresholds out of the
PACKED player bytes (the `C9 nn B0 oo` compare whose branch target is `C9 nn
90 .. B0 ..`, player.s mt_normalnote -> mt_nohr_legato), as
tests/test_hard_restart.py reads `GATETIMERPARAM`.
"""
import json
import pathlib

import pytest

from h2g import goatwriter as G
from h2g.convert import convert
from songview import parse_sng

from corpus import CORPUS, needs_corpus

REPO_ROOT = pathlib.Path(__file__).resolve().parents[2]
NOTE, REST = G.GT_FIRST_NOTE, G.GT_REST
END = 0xFF


# --- the row ----------------------------------------------------------------

def _song(*patterns):
    """One subtune, all three voices on pattern 0 then the rest in order."""
    order = list(range(len(patterns))) + [END, 0]
    return [list(p) for p in patterns], [list(order) for _ in range(3)]


def test_a_rest_before_a_named_note_takes_the_decoy():
    pat = [NOTE, 5, 0, 0, REST, 0, 0, 0, NOTE + 1, 6, 0, 0, END, 0, 0, 0]
    pats, tracks = _song(pat)
    assert G.legato_slip_decoy(pats, tracks, 6, 7) == (0, 1, 5)


def test_a_rest_before_a_bare_note_does_not():
    """The bare note would inherit the decoy and slip -- the defect itself."""
    pat = [NOTE, 5, 0, 0, REST, 0, 0, 0, NOTE + 1, 0, 0, 0,
           REST, 0, 0, 0, END, 0, 0, 0]
    pats, tracks = _song(pat)
    assert G.legato_slip_decoy(pats, tracks, 6, 7) is None


def test_a_rest_on_the_last_row_does_not():
    """The successor's first note could inherit it."""
    pat = [NOTE, 5, 0, 0, REST, 0, 0, 0, END, 0, 0, 0]
    pats, tracks = _song(pat)
    assert G.legato_slip_decoy(pats, tracks, 6, 7) is None


def test_a_keyoff_or_note_row_is_not_a_rest():
    pat = [NOTE, 5, 0, 0, G.GT_KEYOFF, 0, 0, 0, NOTE + 1, 6, 0, 0, END, 0, 0, 0]
    pats, tracks = _song(pat)
    assert G.legato_slip_decoy(pats, tracks, 6, 7) is None


def test_the_held_instrument_must_be_settled_and_written():
    # Entered on two instruments: pattern 1 follows 0 (holding 5) and 2
    # (holding 6) on different voices, and names nothing before its rest.
    p0 = [NOTE, 5, 0, 0, END, 0, 0, 0]
    p2 = [NOTE, 6, 0, 0, END, 0, 0, 0]
    p1 = [REST, 0, 0, 0, NOTE, 5, 0, 0, END, 0, 0, 0]
    pats = [p0, p1, p2]
    tracks = [[0, 1, END, 0], [2, 1, END, 0], [0, END, 0]]
    assert G.legato_slip_decoy(pats, tracks, 6, 7) is None
    # Settled, but on a number past the records written: nothing to copy.
    pat = [NOTE, 9, 0, 0, REST, 0, 0, 0, NOTE, 5, 0, 0, END, 0, 0, 0]
    pats, tracks = _song(pat)
    assert G.legato_slip_decoy(pats, tracks, 6, 7) is None


def test_only_a_pattern_greloc_packs_can_carry_it():
    """greloc.c:200-218: pattused only in a subtune whose three orderlists
    are all non-empty; an instrument named elsewhere is not instrused."""
    good = [NOTE, 5, 0, 0, REST, 0, 0, 0, NOTE + 1, 6, 0, 0, END, 0, 0, 0]
    plain = [NOTE, 5, 0, 0, END, 0, 0, 0]
    pats = [plain, good]
    tracks = [[0, END, 0], [0, END, 0], [0, END, 0],      # subtune 0
              [1, END, 0], [1, END, 0], [END, 0]]         # subtune 1: voice 3 empty
    assert G.note_passes._packed_patterns(tracks, 2) == {0}
    assert G.legato_slip_decoy(pats, tracks, 6, 7) is None
    tracks[5] = [1, END, 0]
    assert G.note_passes._packed_patterns(tracks, 2) == {0, 1}
    assert G.legato_slip_decoy(pats, tracks, 6, 7) == (1, 1, 5)


# --- the packed .sid ---------------------------------------------------------

def _thresholds(body: bytes):
    hits = []
    for i in range(len(body) - 4):
        if body[i] == 0xC9 and body[i + 2] == 0xB0:
            off = body[i + 3] - 256 if body[i + 3] >= 128 else body[i + 3]
            t = i + 4 + off
            if (0 <= t < len(body) - 6 and body[t] == 0xC9
                    and body[t + 2] == 0x90 and body[t + 4] == 0xB0):
                hits.append((body[i + 1], body[t + 1]))
    return hits


def _greloc_numbers(song):
    """greloc.c:341-370 over the instruments greloc.c:274-291 counts."""
    pattused = set()
    tr = song.tracks
    for g in range(0, len(tr) - 2, 3):
        grp = [t[:t.index(END)] if END in t else list(t) for t in tr[g:g + 3]]
        if all(grp):
            for t in grp:
                pattused.update(b for b in t if b < 0xD0)
    used = {1}
    for p in pattused:
        pat = song.patterns[p]
        for r in range(len(pat) // 4):
            if pat[4 * r] == END:
                break
            if pat[4 * r + 1]:
                used.add(pat[4 * r + 1])
    gt = {i + 1: ins.gatetimer for i, ins in enumerate(song.instruments)}
    order = ([c for c in sorted(used) if not gt[c] & 0xC0]
             + [c for c in sorted(used) if gt[c] & 0xC0 == 0x80]
             + [c for c in sorted(used) if gt[c] & 0x40])
    return {c: k + 1 for k, c in enumerate(order)}, pattused


def _note_instruments(song, pattused):
    """Every instrument a note row is fetched holding, latch included,
    walked over every orderlist (a lap plus the loop)."""
    held = set()
    for track in G._lapped_tracks(song.tracks):
        cur, operand = 1, False
        for b in track:
            if operand:
                operand = False
                continue
            if b == END:
                operand = True
                continue
            if b >= 0xD0:
                continue
            pat = song.patterns[b]
            for r in range(len(pat) // 4):
                note, ins = pat[4 * r], pat[4 * r + 1]
                if note == END:
                    break
                if ins:
                    cur = ins
                if NOTE <= note <= G.GT_LAST_NOTE:
                    held.add(cur)
    return held


def _packed(name, tmp_path):
    import fidelity as F
    if not pathlib.Path(F.GT2RELOC).exists():
        pytest.skip("gt2reloc not available")
    doc = json.loads((REPO_ROOT / "presets.json").read_text(encoding="utf-8"))
    lines = []
    sng = convert(str(CORPUS / name), log=lines.append,
                  **F._preset_opts(doc, name))
    mult = F._preset_multiplier(doc, name)
    sid = F.pack_sid(sng, tmp_path, multiplier=mult)
    assert sid is not None and sid.exists()
    return parse_sng(sng), sid.read_bytes()[0x7E:], mult, lines


@needs_corpus
@pytest.mark.parametrize("name", ["Star_Paws.sid", "Delta.sid"])
def test_the_packed_player_slips_only_the_decoy(name, tmp_path):
    song, body, mult, lines = _packed(name, tmp_path)
    assert mult > 1
    th = _thresholds(body)
    assert len(th) == 1, th
    first_nohr, first_legato = th[0]
    numbers, pattused = _greloc_numbers(song)
    normal = sum(1 for c in numbers
                 if not song.instruments[c - 1].gatetimer & 0xC0)
    nohr = sum(1 for c in numbers
               if song.instruments[c - 1].gatetimer & 0xC0 == 0x80)
    # The slip itself, read from the packed bytes: one past the legato class.
    assert first_nohr == normal + 1
    assert first_legato == normal + nohr + 2
    legato = sorted(c for c in numbers
                    if song.instruments[c - 1].gatetimer & 0x40)
    assert len(legato) >= 2
    slipped = [c for c in legato if numbers[c] < first_legato]
    decoy = legato[0]
    assert slipped == [decoy]
    # The slipped record is never fetched by a note; every clone a note
    # plays is packed in the legato class.
    on_notes = _note_instruments(song, pattused)
    assert decoy not in on_notes, "a note plays the slipped legato record"
    played = [c for c in legato if c in on_notes]
    assert played == legato[1:]
    assert all(numbers[c] >= first_legato for c in played)
    assert any("decoy legato record" in l for l in lines)


@needs_corpus
def test_the_decoy_is_a_legato_copy_of_the_instrument_it_is_latched_over():
    """Neutral on the rows it holds: gatetimer (gplay.c:345, player.s
    mt_nonewpatt) and vibrato (gplay.c:408) are the held record's."""
    import fidelity as F
    doc = json.loads((REPO_ROOT / "presets.json").read_text(encoding="utf-8"))
    name = "Star_Paws.sid"
    song = parse_sng(convert(str(CORPUS / name), log=lambda m: None,
                             **F._preset_opts(doc, name)))
    legato = [i + 1 for i, ins in enumerate(song.instruments)
              if ins.gatetimer & 0x40]
    decoy = legato[0]
    rows = [(p, r) for p, pat in enumerate(song.patterns)
            for r in range(len(pat) // 4) if pat[4 * r + 1] == decoy]
    assert len(rows) == 1
    p, r = rows[0]
    pat = song.patterns[p]
    assert pat[4 * r] == REST
    held = next(pat[4 * q + 1] for q in range(r - 1, -1, -1) if pat[4 * q + 1])
    a, b = song.instruments[decoy - 1], song.instruments[held - 1]
    assert a.gatetimer == b.gatetimer | G.GATETIMER_LEGATO
    assert (a.ad, a.sr, a.wave_ptr, a.pulse_ptr, a.filt_ptr, a.vib_ptr,
            a.vib_delay, a.firstwave) == (b.ad, b.sr, b.wave_ptr, b.pulse_ptr,
                                          b.filt_ptr, b.vib_ptr, b.vib_delay,
                                          b.firstwave)
