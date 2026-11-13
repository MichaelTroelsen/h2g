"""The note-init frame shows the PREVIOUS note's last waveform
(h2g.prev_class_firstwave).

Phantoms_of_the_Asteroid voice 2, frames 369-376: the original shows
`80 80 80 41*` and a gate-off firstwave shows `80 80 40 41*`, the record's own
waveform one frame early. On every attack of Phantoms (2589), One_Man_and_his_
Droid (2632) and Lakers_vs_Celtics (1293) the original's waveform on that frame
is the last waveform entry of the preceding note's wavetable program, which
makes the right firstwave byte a function of (record, predecessor record).

The synthetic song below is two records: A plays noise (`$81`), B pulse
(`$41`), both with the gate-off firstwave of their own class. B after A must
get a clone of B whose firstwave is noise with the gate clear (`$80`); A after
B, the song's first note, and B after B keep their records.
"""
import inspect
import pathlib
import sys

import pytest

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[1]))

import songview                                              # noqa: E402
from corpus import CORPUS, needs_corpus                      # noqa: E402
from h2g import prev_class_firstwave as pcf                  # noqa: E402
from h2g.convert import convert                              # noqa: E402
from h2g.goatwriter import HEADER_LEN                        # noqa: E402

C4 = 0x60 + 12 * 4
END = 0xFF
TONEPORTA = 0x03


def record(wave_ptr, firstwave):
    r = bytearray(25)
    r[2] = wave_ptr
    r[7] = 0x02
    r[8] = firstwave
    return bytes(r)


def song(rows, instruments=None, tracks=None, program_a=None):
    """A GTS5 song: instruments A (noise, 1) and B (pulse, 2), one pattern of
    `rows` ((note, instrument, command, data) tuples), voice 0 playing it and
    restarting at position 0, voices 1 and 2 empty."""
    out = bytearray(b"GTS5" + bytes(HEADER_LEN - 4))
    out.append(1)
    for track in tracks or ([0x00, 0xFF, 0x00], [0xFF, 0x00], [0xFF, 0x00]):
        out.append(len(track) - 1)
        out += bytes(track)
    program_a = program_a or [(0x81, 0x00), (0x80, 0x00), (0xFF, 0x00)]
    b_at = len(program_a) + 1
    recs = instruments or [record(1, 0x80), record(b_at, 0x40)]
    out.append(len(recs))
    for r in recs:
        out += r
    wtbl = program_a + [(0x41, 0x00), (0xFF, 0x00)]
    out.append(len(wtbl))
    out += bytes(left for left, _ in wtbl) + bytes(right for _, right in wtbl)
    for _ in range(3):                       # pulse, filter, speed tables
        out.append(0)
    out.append(1)
    out.append(len(rows) + 1)
    for row in rows:
        out += bytes(row)
    out += bytes([END, 0, 0, 0])
    return bytes(out)


def run(blob, calls=(4,), multiplier=1, raw=False):
    return pcf.prev_class_firstwave(blob, list(calls) if calls else None,
                                    multiplier, raw_gate_legato=raw)


def parsed(blob):
    return songview.parse_sng(blob)


def instrument_column(sng):
    return [sng.patterns[0][4 * r + 1] for r in range(len(sng.patterns[0]) // 4)]


def test_without_the_subtune_clock_nothing_changes():
    blob = song([(C4, 1, 0, 0), (C4, 2, 0, 0)])
    assert run(blob, calls=None) == blob


def test_the_waveform_is_the_one_the_predecessor_had_reached_when_the_next_note_began():
    # Record A writes noise on its first call, holds 16 calls, then pulse.
    # One 4-call row gives it 3 calls: still noise, so B takes a clone. Five
    # rows give it 19: pulse, B's own class, so there is nothing to change.
    program_a = [(0x81, 0), (0x0F, 0), (0x41, 0), (0xFF, 0)]
    short = song([(C4, 1, 0, 0), (C4, 2, 0, 0)], program_a=program_a)
    assert instrument_column(parsed(run(short)))[1] == 3
    held = song([(C4, 1, 0, 0)] + [(0xBD, 0, 0, 0)] * 4 + [(C4, 2, 0, 0)],
                program_a=program_a)
    assert run(held) == held


def test_the_option_is_off_by_default():
    assert inspect.signature(convert).parameters[
        "prev_class_firstwave"].default is False


def test_a_record_after_a_different_class_takes_that_class_as_its_firstwave():
    blob = song([(C4, 1, 0, 0), (C4, 2, 0, 0)])
    out = run(blob)
    sng = parsed(out)
    assert len(sng.instruments) == 3
    # B after A plays the clone, whose firstwave is A's last waveform, gate clear.
    assert instrument_column(sng)[:2] == [1, 3]
    assert sng.instruments[2].firstwave == 0x80
    # The records themselves are untouched.
    assert [i.firstwave for i in sng.instruments[:2]] == [0x80, 0x40]
    assert sng.instruments[2].wave_ptr == sng.instruments[1].wave_ptr


def test_a_record_after_its_own_class_keeps_its_record():
    blob = song([(C4, 2, 0, 0), (C4, 2, 0, 0)])
    assert run(blob) == blob


def test_a_tone_portamento_row_is_not_a_note_init():
    blob = song([(C4, 1, 0, 0), (C4, 2, TONEPORTA, 0x10)])
    assert run(blob) == blob


def test_a_row_that_inherits_its_instrument_names_it_when_the_live_one_moved():
    # Row 1 (B, after A) becomes the clone; row 2 relied on B being live and
    # must not inherit the clone, whose firstwave is wrong after B.
    blob = song([(C4, 1, 0, 0), (C4, 2, 0, 0), (C4, 0, 0, 0)])
    sng = parsed(run(blob))
    col = instrument_column(sng)
    assert col[1] == 3
    assert col[2] == 2


def test_a_firstwave_that_is_not_a_gate_off_waveform_is_left_alone():
    recs = [record(1, 0x80), record(3, 0x09)]       # B carries the testbit
    blob = song([(C4, 1, 0, 0), (C4, 2, 0, 0)], instruments=recs)
    assert run(blob) == blob


@needs_corpus
def test_phantoms_converts_with_clones_and_stays_within_the_record_limit():
    import json
    import fidelity
    repo = pathlib.Path(__file__).resolve().parents[2]
    doc = json.loads((repo / "presets.json").read_text(encoding="utf-8"))
    name = "Phantoms_of_the_Asteroid.sid"
    opts = fidelity._preset_opts(doc, name)
    assert opts["prev_class_firstwave"], "adopted for Phantoms at v0.5.662"
    off = convert(str(CORPUS / name), log=lambda m: None,
                  **dict(opts, prev_class_firstwave=False))
    on = convert(str(CORPUS / name), log=lambda m: None, **opts)
    assert off != on
    a, b = parsed(off), parsed(on)
    assert len(a.instruments) < len(b.instruments) <= 62
    named = {p[4 * r + 1] for p in b.patterns for r in range(len(p) // 4)}
    assert max(named) <= len(b.instruments)
    # The clones are copies of a record but for the firstwave byte.
    originals = {tuple(i.__dict__[k] for k in ("ad", "sr", "wave_ptr", "pulse_ptr"))
                 for i in a.instruments}
    for clone in b.instruments[len(a.instruments):]:
        assert (clone.ad, clone.sr, clone.wave_ptr, clone.pulse_ptr) in originals
        assert clone.firstwave & 0x01 == 0


# --- A predecessor that leaves noise with the gate ON (RAW_GATE_LEGATO) ------
#
# Lakers_vs_Celtics voice 2, original frames 2678-2690: the drum program ends
# `set $81` (an absolute opcode, written to $D404 raw and past the per-frame
# `AND gate`), so the chip is gate-on through the original's own gate-off
# window and the melodic note behind it (`41`) is a pitch change. Goattracker's
# `wave & gate` ANDs that `$81` to `$80` inside the window and the note is a
# fresh edge: one ours-only attack on instrument $09CB, hold 100% -> 93% once
# the ILV tie fixes removed the other extras. A LEGATO clone of the note's
# record (gatetimer $40) is not fetched with a window, and its firstwave is
# the chip's waveform with the gate set.

GATE_ON_TAIL = [(0x81, 0x00), (0xFF, 0x00)]


def test_a_gate_on_noise_tail_gives_the_next_note_a_legato_clone_with_the_gate_up():
    blob = song([(C4, 1, 0, 0), (C4, 2, 0, 0)], program_a=GATE_ON_TAIL)
    sng = parsed(run(blob, raw=True))
    assert instrument_column(sng)[:2] == [1, 3]
    clone = sng.instruments[2]
    assert clone.firstwave == 0x81
    assert clone.gatetimer & 0x40
    assert clone.wave_ptr == sng.instruments[1].wave_ptr
    # Neither original record is touched.
    assert not sng.instruments[1].gatetimer & 0x40
    assert [i.firstwave for i in sng.instruments[:2]] == [0x80, 0x40]


def test_a_gate_clear_noise_tail_keeps_the_plain_clone():
    blob = song([(C4, 1, 0, 0), (C4, 2, 0, 0)])
    sng = parsed(run(blob, raw=True))
    clone = sng.instruments[2]
    assert clone.firstwave == 0x80
    assert not clone.gatetimer & 0x40


def test_the_legato_clone_is_gone_when_the_switch_is_off(monkeypatch):
    monkeypatch.setattr(pcf, "RAW_GATE_LEGATO", False)
    blob = song([(C4, 1, 0, 0), (C4, 2, 0, 0)], program_a=GATE_ON_TAIL)
    clone = parsed(run(blob, raw=True)).instruments[2]
    assert clone.firstwave == 0x80
    assert not clone.gatetimer & 0x40


def test_a_player_without_the_raw_write_keeps_the_plain_clone():
    # The finished bytes cannot tell a raw `$81` from one the gate mask clears
    # (Chicken_Song, Chain_Reaction, Hollywood_or_Bust, Last_V8 and Zoolook all
    # end notes on a masked `$81` and read worse with a legato clone), so the
    # caller says which dialect it is.
    blob = song([(C4, 1, 0, 0), (C4, 2, 0, 0)], program_a=GATE_ON_TAIL)
    clone = parsed(run(blob, raw=False)).instruments[2]
    assert clone.firstwave == 0x80
    assert not clone.gatetimer & 0x40


@needs_corpus
def test_lakers_voice_two_drum_is_followed_by_legato_clones():
    import json
    import fidelity
    repo = pathlib.Path(__file__).resolve().parents[2]
    doc = json.loads((repo / "presets.json").read_text(encoding="utf-8"))
    name = "Lakers_vs_Celtics.sid"
    opts = fidelity._preset_opts(doc, name)
    assert opts["prev_class_firstwave"]
    on = parsed(convert(str(CORPUS / name), log=lambda m: None, **opts))
    pcf.RAW_GATE_LEGATO = False
    try:
        off = parsed(convert(str(CORPUS / name), log=lambda m: None, **opts))
    finally:
        pcf.RAW_GATE_LEGATO = True
    legato = [i for i in on.instruments if i.gatetimer & 0x40 and i.firstwave & 1]
    assert len(legato) >= 1
    assert not [i for i in off.instruments if i.gatetimer & 0x40 and i.firstwave & 1]
