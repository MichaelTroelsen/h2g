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
from h2g.patterns import MAX_PATTERNS  # noqa: E402

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


# greloc.c's packpattern() (v2.77) packs each pattern for the player and
# returns -1 past this many bytes; gt2reloc then prints "PATTERN xx IS TOO
# COMPLEX (OVER 256 BYTES PACKED)!" to the console that does not exist headless
# and writes no file. This is what refused Rasputin under `pulse_phase` at -S2
# (v0.5.480): CMD_SETPULSEPTR on 785 note rows made four 127-row patterns pack
# to 264-270 bytes. Confirmed by intervention -- stripping the command from
# ONLY those four patterns packs (max 217), stripping it from every OTHER
# pattern and keeping the four is still refused. Since the `multiplier == 1`
# gate was lifted, `goatwriter.budget_pulse_phase_commands` is what keeps
# that file inside the limit -- `test_pattern_budget.py` -- and the corpus
# walk below runs with `pulse_phase` forced on as well as under the presets,
# because the writer that crosses the line is only reached by the first.
PACKED_PATTERN_LIMIT = 256
_FX, _FXONLY, _FIRSTNOTE, _REST = 0x40, 0x50, 0x60, 0xBD


def packed_pattern_size(rows) -> int:
    """Bytes greloc.c's `packpattern` emits for `rows` of (note, instr, cmd,
    data) -- its size arithmetic exactly, before the endmark.

    Three rules decide it: a repeated instrument byte costs nothing, a
    command/data pair costs two bytes only where it CHANGES from the previous
    row (one where the command is 0), and a run of bare rests after the first
    row collapses to one byte per 64. Table remaps are size-neutral. The one
    thing not replicated is `CMD_SETMASTERVOL` above `$0F` being erased when
    no author info is packed, which can only make a pattern smaller.
    """
    temp1, instr = [], 0
    for c, (n, i, cmd, dat) in enumerate(rows):
        if c and i and i == instr:
            temp1.append((n, 0, cmd, dat))
        else:
            temp1.append((n, i, cmd, dat))
            if i:
                instr = i
    b, command, databyte = [], -1, -1
    for n, i, cmd, dat in temp1:
        if i:
            b.append(i)
        if n == _REST:
            if cmd != command or dat != databyte:
                command, databyte = cmd, dat
                b.append(_FXONLY + cmd)
                if cmd:
                    b.append(dat)
            else:
                b.append(_REST)
        else:
            if cmd != command or dat != databyte:
                command, databyte = cmd, dat
                b.append(_FX + cmd)
                if cmd:
                    b.append(dat)
            b.append(n)
    size, c = 0, 0
    while c < len(b):
        packok = c != 0
        if b[c] < _FX:
            size += 1
            c += 1
            packok = False
        if c < len(b) and _FXONLY <= b[c] < _FIRSTNOTE:
            fxnum = b[c] - _FXONLY
            size += 2 if fxnum else 1
            c += 2 if fxnum else 1
            continue
        if c < len(b) and b[c] < _FXONLY:
            fxnum = b[c] - _FX
            size += 2 if fxnum else 1
            c += 2 if fxnum else 1
            packok = False
        if c >= len(b):
            break
        if b[c] != _REST:
            packok = False
        if not packok:
            size += 1
            c += 1
        else:
            d = c
            while d < len(b) and b[d] == _REST and d - c < 64:
                d += 1
            d -= c
            size += 1
            c += d if d > 1 else 1
    return size


_ENDPATT = 0xFF


def _pattern_rows(flat):
    """`songview.parse_sng` keeps a pattern as a flat byte list, four a row,
    ENDPATT row included. `packpattern` is handed `pattlen` rows -- the count
    BEFORE the ENDPATT (gsong.c:1330) -- so the walk stops there. Counting the
    end row charged every pattern one byte it never packs, which is how this
    reader disagreed with goatwriter's the first time the two were compared
    (`test_pattern_budget.test_the_two_readers_agree_on_the_corpus`)."""
    rows = list(zip(flat[0::4], flat[1::4], flat[2::4], flat[3::4]))
    for k, row in enumerate(rows):
        if row[0] == _ENDPATT:
            return rows[:k]
    return rows


def test_the_packed_size_charges_a_command_change_two_bytes():
    """127 notes with a command whose data changes every row: 127 + 2 x 127 =
    381, past the limit. The same notes with no command: 127 + 1 (the first
    row's `FX+0`) = 128, well inside it -- which is why Rasputin packs at
    -S2 without `pulse_phase` and not with it."""
    busy = [(0x60 + (r % 12), 0, 9, r) for r in range(127)]
    assert packed_pattern_size(busy) == 381 > PACKED_PATTERN_LIMIT
    quiet = [(0x60 + (r % 12), 0, 0, 0) for r in range(127)]
    assert packed_pattern_size(quiet) == 128
    # A repeated instrument costs nothing; a changed one costs a byte.
    assert packed_pattern_size([(0x60, 3, 0, 0)] + [(0x61, 3, 0, 0)] * 10) == 13
    assert packed_pattern_size([(0x60, 3, 0, 0), (0x61, 4, 0, 0)]) == 5
    # Bare rests after the first row collapse to one byte each 64.
    rests = [(0x60, 0, 0, 0)] + [(_REST, 0, 0, 0)] * 100
    assert packed_pattern_size(rests) == 2 + 2


@needs_corpus
def test_no_corpus_conversion_packs_a_pattern_past_256_bytes():
    """The guard the Rasputin refusal was missing. Every shipped conversion's
    patterns pack inside greloc.c's limit; a writer that puts a command on
    most rows of a long pattern (CMD_SETPULSEPTR under `pulse_phase` did) is
    what pushes one over, and nothing before this could see it. Walked under
    the presets AND with `pulse_phase` forced on: the presets reach that
    writer on few files, and the forced arm is where the budget earns its
    keep (Rasputin at -S2 is in it)."""
    doc = json.loads((pathlib.Path(__file__).resolve().parents[2]
                      / "presets.json").read_text(encoding="utf-8"))
    bad, worst, walked = {}, 0, 0
    for path in sorted(CORPUS.glob("*.sid")):
        for forced in (False, True):
            opts = F._preset_opts(doc, path.name)
            if forced:
                opts["pulse_phase"] = True
            try:
                blob = F.convert(str(path), log=lambda m: None, **opts)
            except Exception:                              # noqa: BLE001
                continue                                   # SURVEY.md's business
            walked += 1
            song = songview.parse_sng(blob)
            sizes = [packed_pattern_size(_pattern_rows(p)) for p in song.patterns]
            worst = max(worst, max(sizes, default=0))
            over = [(i, n) for i, n in enumerate(sizes) if n > PACKED_PATTERN_LIMIT]
            if over:
                bad[(path.name, forced)] = over
    assert not bad, bad
    assert walked > 100, f"only {walked} conversions walked -- the walk is vacuous"
    assert worst > 0, "no pattern measured -- the walk is vacuous"


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


@needs_corpus
def test_no_corpus_conversion_emits_more_patterns_than_goattracker_holds():
    """W_A_R converted to 209 patterns against GoatTracker's MAX_PATT of 208
    (gcommon.h:30, mirrored as patterns.MAX_PATTERNS): gt2reloc packed it and
    returned SUCCESS, survey.py counted it converted, the byte-exact fixture
    was unaffected and the suite was green -- while the packed player ran
    subtune 0 at its default tick. `tracks.legalise_restarts` now declines the
    silent park when the table is full, but nothing asserted the invariant
    itself. This does."""
    doc = json.loads((pathlib.Path(__file__).resolve().parents[2]
                      / "presets.json").read_text(encoding="utf-8"))
    bad = {}
    for path in sorted(CORPUS.glob("*.sid")):
        try:
            blob = F.convert(str(path), log=lambda m: None,
                             **F._preset_opts(doc, path.name))
        except Exception:                              # noqa: BLE001
            continue                                   # SURVEY.md's business
        song = songview.parse_sng(blob)
        if len(song.patterns) > MAX_PATTERNS:
            bad[path.name] = len(song.patterns)
    assert not bad, bad


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
