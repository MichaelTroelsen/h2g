"""The byte-code wave program's `$85` hold sits on the accumulator at -S1 too.

Opened as mega-ins03-arp-last-step-hold: Mega_Apocalypse `$09F9` record 2
(GT ins03, `set $81 $30 / slide $10 $0200 / slide $40 $03C0 / set $80 x8 /
hold`) reads `$14AF - $05C0` (-1472) for the rest of every note past its
program in the original, and ours returned to the note. The interpreter's
`$85` jumps to the per-frame writer (`$4D90 JMP $4E63`), which writes the
accumulator `$C0,X`/`$C3,X` the slides count down (`$4DAB-$4DB6`). The
travel was emitted only above -S1 (`_wave_program_travels`), because there a
portamento BESIDE an opcode costs no frame; after the restore it costs none
of the program's either (`_wave_program_hold_travels`).

Two declines, each measured: a record the player vibrates keeps the note
(its vibrato re-centres there -- Nemesis `$0B09`, `$0C5A`), and a song with
any real or gate-off firstwave gets no -S1 travel at all, because the next
note's init call opens at the tail's pitch (melody 0.99 -> 0.69 on
Auf_Wiedersehen_Monty, identical named one frame in).
"""
import json
import pathlib
import sys

import pytest

PYTHON_ROOT = pathlib.Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PYTHON_ROOT))

from corpus import CORPUS, needs_corpus  # noqa: E402

PORTADOWN, PORTAUP, JUMP = 0xF2, 0xF1, 0xFF
NOTE_BASE = 0x00                       # right side: write the note


def _tables(name):
    from h2g.convert import _detect_tables
    from h2g.sidfile import load_sid
    return _detect_tables(load_sid(str(CORPUS / f"{name}.sid")),
                          lambda *a, **k: None)


def _entries(name, i, multiplier=1, budget=60, hold_travel=True):
    from h2g.goatwriter.wave_program import _wave_program_entries
    sid, det = _tables(name)
    speed: list = []
    got = _wave_program_entries(sid, det, i, speed, "gts5", multiplier,
                                budget, hold_travel=hold_travel)
    assert got is not None, (name, i)
    return list(got[0]), list(got[1]), speed


@needs_corpus
def test_mega_record_2_ends_on_the_accumulator_at_s1():
    left, right, speed = _entries("Mega_Apocalypse", 2)
    # restore (the stored `$40`, released, on the note), then the travel of
    # the slides' sum, then the stop
    assert left[-3:] == [0x40, PORTADOWN, JUMP], [hex(x) for x in left]
    assert right[-3] == NOTE_BASE
    assert speed[right[-2] - 1] == (0x05, 0xC0), speed
    old_l, old_r, old_s = _entries("Mega_Apocalypse", 2, hold_travel=False)
    assert old_l[-2:] == [0x40, JUMP] and not old_s
    # ...and nothing before the restore moved: the opcodes keep their frames
    assert left[:-2] == old_l[:-1] and right[:-2] == old_r[:-1]


@needs_corpus
def test_a_record_the_player_vibrates_keeps_the_note():
    from h2g.goatwriter.wave_program import _wave_program_record_vibrates
    sid, det = _tables("Nemesis_the_Warlock")
    assert _wave_program_record_vibrates(sid, det, 11)
    msid, mdet = _tables("Mega_Apocalypse")
    assert not _wave_program_record_vibrates(msid, mdet, 2)
    on = _entries("Nemesis_the_Warlock", 11, hold_travel=True)
    off = _entries("Nemesis_the_Warlock", 11, hold_travel=False)
    assert on == off
    # No closing travel: the restore before the stop is on the note. The
    # portamentos before it are the program's own slides, one a frame
    # (`_gated_slide_chain`, tests/test_gated_slide_chain.py).
    assert on[0][-1] == JUMP and on[0][-2] not in (PORTADOWN, PORTAUP)
    assert on[1][-2] == NOTE_BASE


@needs_corpus
@pytest.mark.parametrize("multiplier", [2, 3])
def test_above_s1_nothing_changes(multiplier):
    for name, i in (("Trans-Atlantic_Balloon_Challenge", 2),
                    ("Nemesis_the_Warlock", 11), ("Mega_Apocalypse", 2)):
        assert (_entries(name, i, multiplier, hold_travel=True)
                == _entries(name, i, multiplier, hold_travel=False)), name


@needs_corpus
def test_the_budget_reserves_the_closing_travel():
    from h2g.goatwriter.wave_program import _wave_program_entries
    for name, i in (("Mega_Apocalypse", 2), ("Mega_Apocalypse", 6),
                    ("Nemesis_the_Warlock", 1), ("IK_plus", 3)):
        sid, det = _tables(name)
        for budget in range(4, 30):
            got = _wave_program_entries(sid, det, i, [], "gts5", 1, budget,
                                        hold_travel=True)
            if got is not None:
                assert len(got[0]) <= budget, (name, i, budget, len(got[0]))


def _mega(**extra):
    import fidelity
    from h2g.convert import convert
    doc = json.loads((PYTHON_ROOT.parent / "presets.json").read_text())
    opts = {**fidelity._preset_opts(doc, "Mega_Apocalypse.sid"), **extra}
    return fidelity, opts, convert(str(CORPUS / "Mega_Apocalypse.sid"),
                                   lambda m: None, **opts)


def _ins03_block(sng):
    """Record 2's program -- `81/C2 10/00 40/00`, its set and two slides,
    whatever lead the firstwave gives it -- up to its stop."""
    from songview import parse_sng
    song = parse_sng(sng)
    wt = song.tables["WTBL"]
    for p in range(len(wt) - 2):
        if wt[p:p + 3] == [(0x81, 0xC2), (0x10, 0x00), (0x40, 0x00)]:
            k = p
            while wt[k][0] != JUMP:
                k += 1
            return wt[p:k + 1], song.tables["STBL"]
    raise AssertionError("no ins03 block")


@needs_corpus
def test_the_conversion_carries_it_only_under_the_test_bit():
    block, st = _ins03_block(_mega()[2])
    assert block[-2][0] == PORTADOWN and st[block[-2][1] - 1] == (0x05, 0xC0)
    for extra in ({"no_test_restart": True},
                  {"real_firstwave_instruments": (3,)},
                  {"gate_off_firstwave_instruments": (3,)}):
        block, _st = _ins03_block(_mega(**extra)[2])
        assert block[-2][0] not in (PORTADOWN, PORTAUP), extra
        assert block[-1] == (JUMP, 0x00)


@needs_corpus
@pytest.mark.skipif(not pathlib.Path(
    __import__("fidelity").SIDDUMP).exists(), reason="no siddump")
def test_mega_tails_hold_the_accumulator(tmp_path):
    """siddump of the packed conversion, 40 s. `$07E7` (record 6, slides
    `$0600 + $0640`) holds `note - $0C40` (-3136) from frame 10 to the next
    note, as the original does from frame 9; frame 9 is the restore's one
    call on the note, which is where the travel's frame goes. Before, the
    whole tail sat on the note."""
    fidelity, _opts, sng = _mega()
    sng, _ = fidelity.legalise_restarts(bytes(sng))
    packed = fidelity.pack_sid(sng, tmp_path, fidelity.GT2RELOC, 1)
    assert packed is not None
    trace = fidelity.run_siddump(packed, 40, 0, fidelity.SIDDUMP, calls=1)
    nf = 40 * 50
    notes = held = 0
    for v in trace:
        fq = fidelity.register_timeline(v.freq_events, nf)
        ad = fidelity.register_timeline(v.adsr_events, nf)
        atk = sorted(v.attack_frames)
        for j, f0 in enumerate(atk):
            end = atk[j + 1] if j + 1 < len(atk) else nf
            if ad[f0] != 0x07E7 or end - f0 < 12:
                continue
            notes += 1
            assert fq[f0 + 9] == fq[f0], (f0, fq[f0:end])
            tail = [fq[f] - fq[f0] for f in range(f0 + 10, end - 1)]
            assert tail and set(tail) == {-0x0C40}, (f0, tail)
            held += len(tail)
    assert notes >= 20, notes
