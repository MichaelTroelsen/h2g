"""A relative wavetable step past Goattracker's 96 notes (`past_table_wave`).

Measured at 6e467ff plus the cycle-6 merge (the base of task
gt2reloc-freq-table-trim-noise-drum), every file under its presets:

* the three drum records whose EVERY note overflows: Master_of_Magic sub 1
  voice 1 record 16, G-7 (91) at transpose +0, octave step +12 -> index 103;
  Phantoms_of_the_Asteroid sub 1 voices 1-2 record 5, C-7 (84) and D#7 (87)
  at +0 -> 96 and 99; Human_Race sub 3 voice 1 record 11, E-7 (88) at +0
  -> 100. gt2reloc keeps notes 0..95 in all three (its cap), so the packed
  player read the orderlist address bytes after `mt_freqtblhi`, and the
  pitch moved with the pulse table's size: frequency frames differing
  between the presets pack and the forced-pulse_phase pack over 180 s were
  0/450/0 (MoM, voices 0/1/2), 0/2618/336 (Phantoms) and 174/2803/0
  (Human_Race; voice 0's 174 are an in-table octave phase, not this) --
  and 0/0/0, 0/0/0, 174/0/0 once pinned.
* the pins are the original's own cells: index 96 is `$0700` in all three
  (`00 07`, the head of the per-voice offset table -> G#2, entry 32), Human_Race's 100
  is `$0000` at load (C#0, the lowest absolute note), Master_of_Magic's 103
  is `$0F4F` at load (A#3, entry 46).
"""
from __future__ import annotations

import subprocess
from collections import Counter
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent))
from test_pulse_phase import _corpus_and_presets  # noqa: E402

# (file, the note the drum plays (+ transpose), the absolute note it pins to)
DRUMS = [
    ("Master_of_Magic.sid", 91, 46),
    ("Phantoms_of_the_Asteroid.sid", 84, 32),
    ("Human_Race.sid", 88, 1),
]
_CACHE: dict = {}


def _convert(name: str, forced: bool = False):
    """(the pass's output, the blob it was handed, sid, det, the finished
    conversion). The pass's output, not the conversion: the finished-bytes
    passes after it (`drop_unnamed_instruments`, the startup tempo) rewrite
    the blob too."""
    key = (name, forced)
    if key in _CACHE:
        return _CACHE[key]
    import fidelity
    from h2g import convert as C
    corpus, doc = _corpus_and_presets()
    path = corpus / name
    if not path.exists():
        pytest.skip(f"{name} not in the corpus here")
    kw = fidelity._preset_opts(doc, name)
    if forced:
        kw["pulse_phase"] = True
    seen = []
    real = C.pin_past_table_wave_notes

    def spy(blob, sid, det, log=None):
        after = real(blob, sid, det, log)
        seen.append((bytes(after), bytes(blob), sid, det))
        return after

    C.pin_past_table_wave_notes = spy
    try:
        out = C.convert(str(path), log=lambda m: None, **kw)
    finally:
        C.pin_past_table_wave_notes = real
    after, before, sid, det = seen[0]
    _CACHE[key] = (after, before, sid, det, out)
    return _CACHE[key]


def _song(blob):
    from h2g.goatwriter.appending import _parse_song
    return _parse_song(blob)


def _overflowing_steps(blob):
    """Relative wave steps every note reaching them sends past note 95."""
    from h2g import past_table_wave as W
    song = _song(blob)
    wave = song.tables[0]
    out = []
    for step, notes in W._contexts(song).items():
        left, right = wave[step - 1]
        if left < 0xF0 and right < 0x80 and all(
                (n + right) & 0x7F >= W.GT_NOTES for n in notes):
            out.append(step)
    return sorted(out)


@pytest.mark.parametrize("name,note,target", DRUMS)
def test_the_drum_read_past_the_table_before_the_pass(name, note, target):
    _out, before, _sid, _det, _final = _convert(name)
    assert _overflowing_steps(before), "the pass had nothing to pin"


@pytest.mark.parametrize("name,note,target", DRUMS)
def test_no_step_reads_past_the_table_on_every_note(name, note, target):
    out, _before, _sid, _det, _final = _convert(name)
    assert _overflowing_steps(out) == []


@pytest.mark.parametrize("name,note,target", DRUMS)
def test_the_drum_note_pins_to_the_original_cell(name, note, target):
    from h2g import past_table_wave as W
    out, before, _sid, _det, _final = _convert(name)
    old, new = _song(before), _song(out)
    pinned = {}
    for step, notes in W._contexts(new).items():
        if note in notes and old.tables[0][step - 1] != new.tables[0][step - 1]:
            l0, r0 = old.tables[0][step - 1]
            l1, r1 = new.tables[0][step - 1]
            assert l0 == l1 and r0 == 0x0C, (step, old.tables[0][step - 1])
            pinned[step] = r1
    assert pinned and set(pinned.values()) == {0x80 | target}, pinned


@pytest.mark.parametrize("name,note,target", DRUMS)
def test_only_wavetable_right_bytes_move(name, note, target):
    out, before, _sid, _det, _final = _convert(name)
    old, new = _song(before), _song(out)
    assert len(out) == len(before)
    assert old.tracks == new.tracks and old.instruments == new.instruments
    assert old.patterns == new.patterns and old.tables[1:] == new.tables[1:]
    assert [l for l, _ in old.tables[0]] == [l for l, _ in new.tables[0]]
    moved = [i for i, (a, b) in enumerate(zip(old.tables[0], new.tables[0])) if a != b]
    assert len(moved) == 2, moved


@pytest.mark.parametrize("index,name,entry", [
    (96, "Phantoms_of_the_Asteroid.sid", 32),   # $0700, the offset table
    (100, "Human_Race.sid", 0),                 # $0000 at load
    (103, "Master_of_Magic.sid", 46),           # $0F4F at load
])
def test_cell_entry_reads_the_original_table(index, name, entry):
    from h2g import past_table_wave as W
    _out, _before, sid, det, _final = _convert(name)
    assert det.freq_table.length == 96 and det.note_base == 0
    assert W._cell_entry(sid, det, index) == entry


@pytest.mark.parametrize("name", ["Crazy_Comets.sid", "One_Man_and_his_Droid.sid",
                                  "Saboteur_II.sid"])
def test_a_step_some_note_reaches_inside_the_table_is_left_alone(name):
    """These reach indexes 96-104 too, but on records that also play notes
    the relative step serves inside the table: one byte cannot be both."""
    out, before, _sid, _det, _final = _convert(name)
    assert out == before


def test_a_mixed_step_keeps_its_relative_byte_even_where_most_notes_overflow():
    """Master_of_Magic's drum with ONE of its G-7 rows moved to D-4 (50):
    the +12 steps now serve a note inside the table, so they stay relative
    although the most-played note (91) still overflows."""
    from h2g import past_table_wave as W
    from h2g.goatwriter.appending import _write_song
    _out, before, sid, det, _final = _convert("Master_of_Magic.sid")
    rows = [(n, k) for n, pat in enumerate(_song(before).patterns)
            for k in range(0, len(pat), 4) if pat[k] == 0x60 + 91]
    for n, k in rows:      # the first G-7 row the drum's +12 steps play
        song = _song(before)
        song.patterns[n][k] = 0x60 + 50
        blob = _write_song(song)
        ctx = W._contexts(_song(blob))
        mixed = [s for s, notes in ctx.items() if {50, 91} <= set(notes)
                 and _song(blob).tables[0][s - 1][1] == 0x0C]
        if mixed:
            break
    else:
        pytest.fail("no G-7 row reaches the drum's +12 steps")
    assert Counter(ctx[mixed[0]]).most_common(1)[0][0] == 91
    out = _song(W.pin_past_table_wave_notes(blob, sid, det))
    assert [out.tables[0][s - 1][1] for s in mixed] == [0x0C] * len(mixed)


def test_commando_is_held():
    """The byte-exact fixture: under its own options step 27 would pin."""
    from h2g import past_table_wave as W
    from h2g import convert as C
    root = Path(__file__).resolve().parents[2]
    seen = []
    real = C.pin_past_table_wave_notes
    C.pin_past_table_wave_notes = lambda b, s, d, log=None: (
        seen.append((bytes(b), s, d)) or real(b, s, d, log))
    try:
        C.convert(str(root / "Commando.sid"), log=lambda m: None)
    finally:
        C.pin_past_table_wave_notes = real
    blob, sid, det = seen[0]
    assert sid.name in W.HELD
    assert _overflowing_steps(blob) == [27]
    assert W.pin_past_table_wave_notes(blob, sid, det) == blob


def _freq_columns(path: Path, sub: int, seconds: int, mult: int):
    import fidelity
    cmd = [fidelity.SIDDUMP, str(path), f"-a{sub - 1}", f"-t{seconds}"]
    if mult > 1:
        cmd.append(f"-m{mult}")
    rows, cur = [], [None, None, None]
    for line in subprocess.run(cmd, capture_output=True, text=True).stdout.splitlines():
        if not (line.startswith("|") and line[2:7].strip().isdigit()):
            continue
        for v in range(3):
            f = line.split("|")[2 + v].split()
            if f and f[0] != "....":
                cur[v] = f[0]
        rows.append(tuple(cur))
    return rows


@pytest.mark.parametrize("name,sub,voice", [
    ("Phantoms_of_the_Asteroid.sid", 1, 1),
    ("Human_Race.sid", 3, 1),
    ("Master_of_Magic.sid", 1, 1),
])
def test_the_drum_pitch_does_not_move_with_the_packed_layout(tmp_path, name, sub, voice):
    """The presets pack and the forced-pulse_phase pack lay different pulse
    tables, so gt2reloc puts the orderlists -- and the bytes after
    `mt_freqtblhi` -- somewhere else. The drum voice's frequency must not
    care."""
    import fidelity
    if not (Path(fidelity.SIDDUMP).exists() and Path(fidelity.GT2RELOC).exists()):
        pytest.skip("siddump or gt2reloc not available here")
    _corpus, doc = _corpus_and_presets()
    mult = fidelity._preset_multiplier(doc, name)
    traces = []
    for forced in (False, True):
        out = _convert(name, forced)[4]
        wd = tmp_path / ("forced" if forced else "presets")
        wd.mkdir()
        packed = fidelity.pack_sid(out, wd, multiplier=mult)
        assert packed is not None, "gt2reloc refused"
        traces.append(_freq_columns(packed, sub, 60, mult))
    a, b = traces
    assert len(a) == len(b) > 0
    assert sum(x[voice] != y[voice] for x, y in zip(a, b)) == 0
