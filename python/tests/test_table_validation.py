"""Every conversion's tables, walked the way `gt2reloc` walks them.

`gt2reloc` validates the tables before it packs, and when it refuses it says so
on a console that does not exist headless: exit code 0, no output file, no
message (CLAUDE.md). Wiz spent this whole project's life in that state and was
filed as "gt2reloc will not pack it" without a cause, because nothing here
could see *why*.

`gtable.c:1008`'s `exectable` is twenty lines, so this replicates it. Two error
kinds:

* `TYPE_JUMP` -- an instrument's table pointer points *at* an `$FF` row.
* `TYPE_OVERFLOW` -- following the rows runs past `MAX_TABLELEN`.

The whole corpus under its shipped options is the test. It found the class it
was written for on the first run: `_wave_program_entries` was copying a program
opcode's waveform straight into the wavetable's left column, where `$F0`-`$FF`
are commands and `$FF` is the jump, so Wiz's `set $FF, 250` became `FF/DE` -- a
jump to row 222 of a 112-row table.
"""
import json
import pathlib
import sys

from corpus import CORPUS, needs_corpus  # noqa: E402

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[1]))

import fidelity as F  # noqa: E402
import songview  # noqa: E402

MAX_TABLELEN = 255          # gcommon.h
POINTERS = {"WTBL": "wave_ptr", "PTBL": "pulse_ptr", "FTBL": "filt_ptr"}


def table_errors(blob: bytes) -> list:
    """`[(kind, table, instrument)]` for a `.sng`, `exectable`'s rules exactly.

    STBL is excluded for the reason gtable.c excludes it: its pointer is an
    index into a table the player reads directly rather than a row to execute,
    so neither the jump nor the overflow check applies.
    """
    song = songview.parse_sng(blob)
    out = []
    for name, attr in POINTERS.items():
        rows = song.tables.get(name) or []
        left = [l for l, _ in rows]
        right = [r for _, r in rows]

        def at(ptr, arr):
            return arr[ptr - 1] if 1 <= ptr <= len(arr) else 0

        for ins in song.instruments:
            ptr = getattr(ins, attr)
            if not ptr:
                continue
            if ptr <= MAX_TABLELEN and at(ptr, left) == 0xFF:
                out.append(("jump", name, ins.number))
                continue
            seen, p = set(), ptr
            while p:
                if p > MAX_TABLELEN:
                    out.append(("overflow", name, ins.number))
                    break
                if p in seen:
                    break
                seen.add(p)
                p = at(p, right) if at(p, left) == 0xFF else p + 1
    return out


@needs_corpus
def test_no_corpus_conversion_builds_a_table_gt2reloc_would_refuse():
    doc = json.loads((pathlib.Path(__file__).resolve().parents[2]
                      / "presets.json").read_text(encoding="utf-8"))
    bad = {}
    for path in sorted(CORPUS.glob("*.sid")):
        try:
            blob = F.convert(str(path), log=lambda m: None,
                             **F._preset_opts(doc, path.name))
        except Exception:                              # noqa: BLE001
            continue                                   # SURVEY.md's business
        errs = table_errors(blob)
        if errs:
            bad[path.name] = errs
    assert not bad, bad


@needs_corpus
def test_the_three_files_with_command_range_opcodes_are_clean():
    """Wiz, Kings of the Beach intro and Mega Apocalypse are the corpus's
    wave programs carrying an opcode in `$F0`-`$FF`. The first is the one that
    could not pack; the other two ship with `--wave-program` selected and their
    tables held a jump where a waveform belongs."""
    doc = json.loads((pathlib.Path(__file__).resolve().parents[2]
                      / "presets.json").read_text(encoding="utf-8"))
    for name in ("Wiz.sid", "Kings_of_the_Beach_intro.sid",
                 "Mega_Apocalypse.sid"):
        opts = F._preset_opts(doc, name)
        opts["wave_program"] = True
        blob = F.convert(str(CORPUS / name), log=lambda m: None, **opts)
        assert table_errors(blob) == [], name


def test_the_walk_reports_a_jump_and_an_overflow():
    """The checker itself, against hand-built tables: a validator that cannot
    fail is not a validator."""
    import songview as SV

    class _Ins:
        def __init__(self, n, ptr):
            self.number, self.wave_ptr = n, ptr
            self.pulse_ptr = self.filt_ptr = 0

    class _Song:
        def __init__(self, rows, ptr):
            self.tables = {"WTBL": rows}
            self.instruments = [_Ins(1, ptr)]

    real = SV.parse_sng
    try:
        # a pointer landing on a jump row
        SV.parse_sng = lambda b: _Song([(0xFF, 0x00), (0x11, 0x00)], 1)
        assert table_errors(b"") == [("jump", "WTBL", 1)]
        # a block that jumps past the end of a short table
        SV.parse_sng = lambda b: _Song([(0x11, 0x00), (0xFF, 0xDE)], 1)
        assert table_errors(b"") == [("overflow", "WTBL", 1)]
        # ...and one that stops properly
        SV.parse_sng = lambda b: _Song([(0x11, 0x00), (0xFF, 0x00)], 1)
        assert table_errors(b"") == []
    finally:
        SV.parse_sng = real
