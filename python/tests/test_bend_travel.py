"""`travel`: the pitch travel read off the frequency register, beside `bend`.

`bend` sums siddump's `(+ xxxx)` lines, and siddump prints a pitch move in that
form only while the new frequency stays near the note it already named; a swing
crossing a note boundary comes out as a tie, which `bend` drops by
construction. Mega_Apocalypse `$00B9` (the expanding-vibrato loops): bend read
1.13x per ADSR and 1.57x for the file, the register's own travel 1.02x
(545,426 against 535,024; 1.14x for the file). `fidelity.within_note_travel`
sums the register instead; `compare()` carries `orig_travel`, `our_travel` and
`travel_ratio` into every measured row. There is no report column yet.
"""
import json
import pathlib
import sys

import pytest

PYTHON_ROOT = pathlib.Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PYTHON_ROOT))

import fidelity  # noqa: E402

REPO_ROOT = PYTHON_ROOT.parent

_DOTS = "|  ....  ... ..  .. .... ... "


def _dump(*voice0_cells: tuple[int, str]) -> str:
    """A siddump table with voice 0 as given and voices 1 and 2 untouched."""
    rows = []
    for frame, cell in voice0_cells:
        rows.append(f"|{frame:6d} | {cell} {_DOTS}{_DOTS}| .... .. ... . |")
    return "\n".join(rows)


# frame 0: attack at 1000; 5, 6: two printed bends of 16; 7: a TIE to 1070 (a
# swing crossing a note boundary: 80 units, which `bend` cannot see); 8: a bare
# write jumping to 2000 (a note, not a bend); 9: a bare write 8 on from it;
# 12: a second attack at 3000; 15: a printed bend of 6; 20, 21: silence and
# the first write after it.
VIBRATO = _dump(
    (0, "1000  C-4 41  41 0000 800"),
    (5, "1010 (+ 0010) .. .... ..."),
    (6, "1020 (+ 0010) .. .... ..."),
    (7, "1070 (D-4 41) .. .... ..."),
    (8, "2000  ... ..  .. .... ..."),
    (9, "2008  ... ..  .. .... ..."),
    (12, "3000  G-5 41  41 .... ..."),
    (15, "3006 (+ 0006) .. .... ..."),
    (20, "0000  ... ..  .. .... ..."),
    (21, "0100  ... ..  .. .... ..."),
)


def _voices(text: str):
    return list(fidelity.parse_dump(text))


def test_travel_counts_the_tied_swing_that_bend_cannot_see():
    v = _voices(VIBRATO)[0]
    assert fidelity._bend_travel(v) == 16 + 16 + 6
    assert v.ties == 1
    assert fidelity.within_note_travel(v) == 16 + 16 + 80 + 8 + 6


def test_travel_skips_onsets_note_jumps_and_silence():
    # Left out of the 126: the step onto each attack (frames 0, 12), the bare
    # write to 2000 (3984 units, past 1/8 of the pitch), the step to 3000
    # across the second attack, the drop to 0 and the climb out of it (a step
    # from or to zero is the whole pitch, so the same threshold takes it).
    only = _dump((0, "1000  C-4 41  41 0000 800"),
                 (8, "2000  ... ..  .. .... ..."),
                 (12, "3000  G-5 41  41 .... ..."),
                 (20, "0000  ... ..  .. .... ..."),
                 (21, "0100  ... ..  .. .... ..."))
    assert fidelity.within_note_travel(_voices(only)[0]) == 0


def test_frames_beside_a_gate_rise_are_not_travel():
    # Moves at a+1 and a+2 (the retrigger's own settling) are skipped as
    # `pitch_motion` skips them; a+3 is the first that counts.
    t = _dump((0, "1000  C-4 41  41 0000 800"),
              (1, "1010 (+ 0010) .. .... ..."),
              (2, "1020 (+ 0010) .. .... ..."),
              (3, "1030 (+ 0010) .. .... ..."))
    assert fidelity.within_note_travel(_voices(t)[0]) == 16


def test_travel_is_the_register_not_the_label():
    # The same 80-unit move: printed as a bend it is in both columns, printed
    # as a tie it is in travel only.
    def one(cell):
        return _voices(_dump((0, "1000  C-4 41  41 0000 800"),
                             (5, cell)))[0]
    bent, tied = one("1050 (+ 0050) .. .... ..."), one("1050 (D-4 41) .. .... ...")
    assert fidelity.within_note_travel(bent) == fidelity.within_note_travel(tied) == 80
    assert fidelity._bend_travel(bent) == 80 and fidelity._bend_travel(tied) == 0


def test_a_step_size_change_moves_travel_by_the_same_ratio():
    def voice(step):
        v = fidelity.Voice()
        v.attack_frames = [0]
        v.freq_events = [(0, 0x1000)] + [(10 + k, 0x1000 + (step if k % 2 else 0))
                                          for k in range(8)]
        return v
    out = fidelity.compare([voice(10), fidelity.Voice(), fidelity.Voice()],
                           [voice(40), fidelity.Voice(), fidelity.Voice()])
    assert out["orig_travel"] == 7 * 10 and out["our_travel"] == 7 * 40
    assert out["travel_ratio"] == pytest.approx(4.0)


def test_compare_carries_travel_keys_and_none_without_original_travel():
    still = [fidelity.Voice(), fidelity.Voice(), fidelity.Voice()]
    out = fidelity.compare(still, still)
    assert (out["orig_travel"], out["our_travel"]) == (0, 0)
    assert out["travel_ratio"] is None
    both = _voices(VIBRATO)
    out = fidelity.compare(both, both)
    assert out["orig_travel"] == out["our_travel"] == 126
    assert out["travel_ratio"] == 1.0


def test_equal_calls_rows_drop_travel_with_bend():
    # The equal-calls mode compares frame against frame on a side whose frames
    # cover `multiplier` times the real time; every key the pop names there must
    # include the travel keys, or that mode would report them as agreement.
    src = (PYTHON_ROOT / "fidelity.py").read_text(encoding="utf8")
    i = src.index('for k in ("bend_ratio", "slides_ratio"')
    popped = src[i:src.index(":", src.index("):", i))]
    for k in ("orig_travel", "our_travel", "travel_ratio"):
        assert f'"{k}"' in popped, k


@pytest.mark.skipif(not pathlib.Path(fidelity.SIDDUMP).exists(),
                    reason="no siddump")
def test_a_measured_row_carries_travel(tmp_path):
    """The key reaches the JSON rows, from a real siddump trace of Commando
    (the byte-exact fixture) against its own conversion."""
    out = tmp_path / "f.json"
    rc = fidelity.main([str(REPO_ROOT / "Commando.sid"), "-t", "20",
                        "--workdir", str(tmp_path / "w"),
                        "--json", str(out), "-o", str(tmp_path / "f.md")])
    assert rc in (0, None)
    doc = json.loads(out.read_text(encoding="utf8"))
    rows = doc["rows"] if isinstance(doc, dict) else doc
    row = next(r for r in rows if r.get("status") == "measured")
    for k in ("orig_travel", "our_travel", "travel_ratio"):
        assert k in row, k
    # Our side depends on whether presets.json sits beside the tree (Commando
    # converts with vibrato only under it), so only the original is asserted
    # non-zero.
    assert row["orig_travel"] > 0
    assert row["travel_ratio"] == pytest.approx(
        row["our_travel"] / row["orig_travel"])
    # Commando's vibrato stays inside its notes, so the register's travel is at
    # least what siddump printed as bends (less the skipped onset frames).
    assert row["orig_travel"] >= 0.5 * row["orig_bend"]
