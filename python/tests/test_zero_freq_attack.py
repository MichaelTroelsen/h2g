"""An attack siddump prints at freq $0000 is named by the voice's next tie.

siddump names a note from the frequency register, so a gate edge at `$0000`
prints as `C-0` whatever the player meant. Sanxion's record 0 is the case:
`0000 C-0 41` on the note-on frame, then `41B8 (B-5 C7) 81` a frame later,
once the wave program writes an absolute pitch. The attack is a real strike
(it keeps its frame) whose pitch is the tie's; the tie is not a note change of
its own. Both sides of a comparison are read by `parse_dump`, so the rule
applies to the original and to ours alike.
"""
import fidelity

HEAD = """| Frame | Freq Note/Abs WF ADSR Pul | Freq Note/Abs WF ADSR Pul | Freq Note/Abs WF ADSR Pul | FCut RC Typ V |
+-------+---------------------------+---------------------------+---------------------------+---------------+
"""
QUIET = "....  ... ..  .. .... ..."
GLOB = ".... .. ... ."


def _dump(rows: list[tuple[int, str, str, str]]) -> str:
    out = HEAD
    for frame, a, b, c in rows:
        out += f"| {frame:5d} | {a} | {b} | {c} | {GLOB} |\n"
    return out


# The Sanxion shape on the third voice.
SANXION = _dump([
    (0, QUIET, QUIET, "0000  C-0 80  41 0FC4 200"),
    (1, QUIET, QUIET, "41B8 (B-5 C7) 81 .... ..."),
])


def test_the_zero_freq_attack_takes_the_next_ties_name():
    v = fidelity.parse_dump(SANXION)[2]
    assert v.attacks == ["B-5"]
    assert v.attack_frames == [0]            # the strike keeps its own frame


def test_the_naming_tie_is_not_counted_as_a_tie():
    v = fidelity.parse_dump(SANXION)[2]
    assert v.ties == 0
    assert v.tie_frames == []


def test_the_frequency_events_are_untouched():
    v = fidelity.parse_dump(SANXION)[2]
    assert v.freq_events == [(0, 0x0000), (1, 0x41B8)]


def test_an_attack_no_tie_ever_names_is_dropped():
    text = _dump([
        (0, QUIET, QUIET, "0000  C-0 80  41 0FC4 200"),
        (1, QUIET, QUIET, "1D12 (- 0034) .. .... ..."),   # a slide is no tie
    ])
    v = fidelity.parse_dump(text)[2]
    assert v.attacks == [] and v.attack_frames == []


def test_a_second_attack_before_any_tie_drops_the_first():
    text = _dump([
        (0, QUIET, QUIET, "0000  C-0 80  41 0FC4 200"),
        (1, QUIET, QUIET, "1D12  E-4 80  41 .... ..."),
        (2, QUIET, QUIET, "41B8 (B-5 C7) 81 .... ..."),
    ])
    v = fidelity.parse_dump(text)[2]
    assert v.attacks == ["E-4"] and v.attack_frames == [1]
    assert v.ties == 1                       # the tie after a real attack counts


def test_two_zero_freq_attacks_each_wait_for_their_own_tie():
    text = _dump([
        (0, QUIET, QUIET, "0000  C-0 80  41 0FC4 200"),
        (1, QUIET, QUIET, "41B8 (B-5 C7) 81 .... ..."),
        (9, QUIET, QUIET, "0000  C-0 80  41 .... ..."),
        (10, QUIET, QUIET, "3000 (G-4 C7) 81 .... ..."),
    ])
    v = fidelity.parse_dump(text)[2]
    assert v.attacks == ["B-5", "G-4"]
    assert v.attack_frames == [0, 9]
    assert v.ties == 0


def test_a_tie_with_no_pending_attack_still_counts():
    text = _dump([
        (0, QUIET, QUIET, "1D12  E-4 80  41 0FC4 200"),
        (1, QUIET, QUIET, "41B8 (B-5 C7) 81 .... ..."),
    ])
    v = fidelity.parse_dump(text)[2]
    assert v.attacks == ["E-4"] and v.ties == 1 and v.tie_frames == [1]


def test_a_dropped_attack_stays_countable_as_a_gate_edge():
    text = _dump([
        (0, QUIET, QUIET, "0000  C-0 80  41 0FC4 200"),
        (4, QUIET, QUIET, "1D12  E-4 80  41 .... ..."),
    ])
    v = fidelity.parse_dump(text)[2]
    assert v.attacks == ["E-4"]
    assert v.unnamed_attack_frames == [0]


def test_voices_are_resolved_independently():
    text = _dump([
        (0, "0000  C-0 80  41 0FC4 200", QUIET, QUIET),
        (1, QUIET, "3000 (G-4 C7) 81 .... ...", QUIET),   # voice 1's tie
        (2, "41B8 (B-5 C7) 81 .... ...", QUIET, QUIET),
    ])
    a, b, _ = fidelity.parse_dump(text)
    assert a.attacks == ["B-5"] and a.ties == 0
    assert b.attacks == [] and b.ties == 1
