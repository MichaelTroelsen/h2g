"""The digi decoder's `$82` slide lasts the whole event, not one row.

Named `test_digi.py` rather than added to the existing `test_digi_engine.py`
because the task that produced these tests declared this path and not that one.
**They belong together**: `test_digi_engine.py` already covers
`_build_raw_pattern_digi` and `DIGI_SLIDE`, and whoever holds that path should
fold these in and delete this file.
"""
from h2g.patterns import (GT_NO_NOTE, _build_raw_pattern_digi, DIGI_DURATION,
                          DIGI_END, DIGI_SLIDE)


def _rows(events):
    return [events[i:i + 4] for i in range(0, len(events), 4)]


def _pattern(wait: int, step_hi: int, step_lo: int) -> bytes:
    """One `$82` slide, then a note held for `wait` extra rows, then the end.

    The duration prefix is sticky and read before the note (see the module's
    `$1104` listing), so it precedes the command exactly as the player's
    stream does.
    """
    # Two leading pad bytes because the builder refuses `addr <= 1`, so every
    # call below starts at offset 2.
    return bytes([0x00, 0x00,
                  DIGI_DURATION | wait, DIGI_SLIDE, step_hi, step_lo,
                  0x30, DIGI_END])


def test_the_slide_is_repeated_on_every_hold_row_of_its_event():
    """The player adds the step on EVERY frame while its gate is set, and that
    gate is cleared only at the next note start ($10F4-$10F6) -- so the slide
    runs for the whole event. A Goattracker command byte executes on the row it
    appears on and nowhere else (the module header on `ONE_SHOT_COMMANDS`), and
    `CMD_PORTAUP`/`CMD_PORTADOWN` are continuous, so one row of command is one
    row of slide. Attached to the note row alone the slide stopped after one
    row -- the defect this pins.

    The ILV decoder was given the identical repeat at v0.5.454; this is the
    same reading applied to the engine that shares its `_digi_command`.
    """
    steps: list[int] = []
    events = _build_raw_pattern_digi(_pattern(3, 0x01, 0x00), 2,
                                     slides=True, steps=steps)
    rows = _rows(events)
    # note row, three hold rows, then the end marker
    assert rows[0][0] != GT_NO_NOTE, "the note itself"
    assert [r[0] for r in rows[1:4]] == [GT_NO_NOTE] * 3, "its three hold rows"
    cmd, data = rows[0][2], rows[0][3]
    assert cmd == 1, "a positive step is CMD_PORTAUP"
    for i, r in enumerate(rows[1:4], start=1):
        assert (r[2], r[3]) == (cmd, data), (
            f"hold row {i} carries the same command as the note row")


def test_a_slide_with_no_hold_rows_is_unchanged():
    """wait 0 is one row, so the repeat loop runs zero times. This is what
    keeps every file whose slides all fall on single-row events byte-identical.
    """
    steps: list[int] = []
    rows = _rows(_build_raw_pattern_digi(_pattern(0, 0x01, 0x00), 2,
                                         slides=True, steps=steps))
    assert rows[0][2] == 1
    assert len(rows) == 2, "the note and the end marker, nothing between"


def test_the_step_is_signed_and_a_high_byte_above_80_slides_down():
    """One `CLC / ADC` pair in the player and no direction test, so `$FF00` is
    -256 rather than 65280 -- and it must reach the hold rows as PORTADOWN,
    not merely as a different operand on row 0.
    """
    steps: list[int] = []
    rows = _rows(_build_raw_pattern_digi(_pattern(2, 0xFF, 0x00), 2,
                                         slides=True, steps=steps))
    assert rows[0][2] == 2, "a negative step is CMD_PORTADOWN"
    assert [(r[2], r[3]) for r in rows[1:3]] == [(rows[0][2], rows[0][3])] * 2


def test_no_command_is_written_where_the_option_is_off():
    """`slides=False` is the default and must leave the stream exactly as it
    was before any of this existed -- the repeat loop is guarded on there being
    a command at all, so an event with hold rows still gets bare hold rows.
    """
    rows = _rows(_build_raw_pattern_digi(_pattern(3, 0x01, 0x00), 2,
                                         slides=False, steps=None))
    assert all((r[2], r[3]) == (0x00, 0x00) for r in rows), \
        "no command column is written anywhere"
    assert [r[0] for r in rows[1:4]] == [GT_NO_NOTE] * 3
