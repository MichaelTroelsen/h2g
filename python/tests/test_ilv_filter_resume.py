"""The interleaved player's `$84` notes do not restart a filter program, and
`ilv_filter_resume` says so (h2g.goatwriter.ilv_filter_resume).

Lion_Heart's record 4 sweeps its filter between `$1D00` and `$7200` and the
player restarts that sweep (to `$4E00`) on every filtered note except the 36 a
`$84` precedes (`$1321 LDA $1A86 / BNE $1389`). Goattracker restarts a filter
table on every note naming an instrument with a filter pointer, so before the
option those 36 notes jumped the cutoff back. Measured at 1c9d17c + the change,
`-t 180`, shipped presets plus the option on Lion_Heart alone: `cfrm`
.7985 -> .8480, `cut` 1.068 -> 1.021, every other printed column but `aud`
(.92852 -> .92846) and `loud` (.96956 -> .96943) identical.

SABOTAGE TARGET: with `ilv_filter_resume.RESUME_ENABLED` set False, the
conversion with the option on is byte-identical to the one with it off, and
`test_the_option_moves_exactly_the_files_that_carry_played_dollar_84_notes`
and `test_a_flagged_note_names_a_clone_with_no_filter_pointer` fail.
"""
import json
import pathlib

import pytest

from corpus import CORPUS, needs_corpus  # noqa: E402
from h2g import patterns as P  # noqa: E402
from h2g.convert import convert  # noqa: E402
from h2g.goatwriter import ilv_filter_resume as R  # noqa: E402

REPO = pathlib.Path(__file__).resolve().parents[2]


def _rows(*b, **kw):
    """(rows, skip_rows) of a pattern `0x80 05, *b`."""
    sk: list = []
    ev = P._build_raw_pattern_ilv(bytes([0, 0, 0x80, 0x05, *b, P.ILV_END]), 2,
                                  skip_rows=sk, **kw)
    return [ev[i:i + 4] for i in range(0, len(ev), 4)], sk


# --- the decoder ----------------------------------------------------------

def test_the_note_after_a_dollar_84_is_flagged_and_no_other():
    rows, sk = _rows(0xC0 | 1, 0x30, 0x84, 0xC0 | 1, 0x31, 0xC0 | 1, 0x32)
    notes = [i for i, r in enumerate(rows)
             if r[0] not in (P.GT_NO_NOTE, P.GT_END_PATTERN)]
    assert len(notes) == 3 and sk == [notes[1]]


def test_the_flag_is_cleared_by_a_rest_as_the_players_fetch_does():
    """`$1152 STA $1A86` runs at every event fetch, a rest's included."""
    rows, sk = _rows(0x84, 0xC0 | 1, P.ILV_REST, 0xC0 | 1, 0x30)
    assert sk == []


def test_no_dollar_84_no_rows_and_the_stream_is_unchanged():
    base, _ = _rows(0xC0 | 1, 0x30, 0x31)
    flagged, sk = _rows(0x84, 0xC0 | 1, 0x30, 0x31)
    assert sk == [0] and flagged == base


def test_the_decoder_asks_nothing_of_a_caller_that_passes_no_list():
    ev = P._build_raw_pattern_ilv(bytes([0, 0, 0x80, 0x05, 0x84, 0xC1, 0x30,
                                         P.ILV_END]), 2)
    assert ev is not None


# --- the plan --------------------------------------------------------------

def _instruments(filter_ptrs):
    """A finished instrument table of `len(filter_ptrs)` records, 25 bytes
    each, record g's wave pointer g + 10 and filter pointer `filter_ptrs[g-1]`."""
    out = bytearray([len(filter_ptrs)])
    for g, f in enumerate(filter_ptrs, 1):
        rec = bytearray(25)
        rec[0], rec[1], rec[2], rec[3], rec[4] = 9, 7, g + 10, g + 20, f
        rec[5] = 3
        out += rec
    return out


def _pattern(*rows):
    out = []
    for note, ins, cmd, dat in rows:
        out += [note, ins, cmd, dat]
    return out + [0xFF, 0, 0, 0]


NOTE = 0x70


def test_a_flagged_note_names_a_clone_with_no_filter_pointer():
    out = _instruments([6, 0])                  # instrument 1 filters, 2 not
    pats = [_pattern((NOTE, 1, 0, 0), (NOTE, 1, 0, 0), (NOTE, 2, 0, 0),
                     (NOTE, 1, P.CMD_TONEPORTA, 0), (0xBD, 0, 0, 0))]
    got, written, clones = R.resume_plan(pats, {0: frozenset({1, 2, 3})}, 1,
                                         (), out, 0, 2)
    assert clones == [(1, 3)] and written == 3 and out[0] == 3
    rows = [got[0][4 * r:4 * r + 4] for r in range(4)]
    assert [r[1] for r in rows] == [1, 3, 2, 1]
    # the clone is the record's bytes with the filter pointer cleared
    src, clone = out[1:26], out[1 + 2 * 25:1 + 3 * 25]
    assert clone[4] == 0 and src[4] == 6
    assert clone[:4] + clone[5:] == src[:4] + src[5:]


def test_nothing_is_renamed_without_flags_or_where_the_source_is_unknown():
    out = _instruments([6])
    pat = _pattern((NOTE, 1, 0, 0), (NOTE, 1, 0, 0))
    for known in (None, {}, {0: frozenset()}, {0: None}):
        pats = [list(pat)]
        got, written, clones = R.resume_plan(pats, known, 1, (), out, 0, 1)
        assert clones == [] and written == 1 and got[0] == pat
    assert len(out) == 26


def test_a_copy_is_attributed_by_note_column():
    """A pass's copy (a pattern past `skip_decoded`) takes its source's rows."""
    out = _instruments([6])
    src = _pattern((NOTE, 1, 0, 0), (NOTE + 1, 1, 0, 0))
    copy = _pattern((NOTE, 1, 0, 0), (NOTE + 1, 1, 0, 0))
    pats = [list(src), list(copy)]
    got, _w, clones = R.resume_plan(pats, {0: frozenset({1})}, 1, (), out, 0, 1)
    assert clones == [(1, 2)]
    assert got[0][5] == 2 and got[1][5] == 2 and got[1][1] == 1


def test_the_switch_short_circuits_the_plan(monkeypatch):
    out = _instruments([6])
    pats = [_pattern((NOTE, 1, 0, 0), (NOTE + 1, 1, 0, 0))]
    monkeypatch.setattr(R, "RESUME_ENABLED", False)
    _p, written, clones = R.resume_plan(pats, {0: frozenset({1})}, 1, (),
                                        out, 0, 1)
    assert clones == [] and written == 1 and pats[0][5] == 1


# --- the corpus ------------------------------------------------------------

def _song(stem, **extra):
    import fidelity as F
    from songview import parse_sng
    doc = json.loads((REPO / "presets.json").read_text("utf-8"))
    opts = dict(F._preset_opts(doc, f"{stem}.sid"), **extra)
    lines: list = []
    blob = convert(str(CORPUS / f"{stem}.sid"), log=lines.append, **opts)
    return blob, parse_sng(blob), lines


@needs_corpus
def test_the_option_is_inert_off():
    """Off, the option emits nothing. Lion_Heart (adopted v0.5.677) and
    Radio_ACE (v0.5.678) are the two song entries that set it, so their
    shipped files are the option-on ones and differ from off."""
    for name in ("Radio_ACE", "Lion_Heart"):
        shipped, _, _ = _song(name)
        on, _, _ = _song(name, ilv_filter_resume=True)
        off, _, lines = _song(name, ilv_filter_resume=False)
        assert shipped == on, name
        assert shipped != off, name
        assert not [m for m in lines if m.startswith("ILV filter resume")], name


@needs_corpus
def test_a_flagged_note_on_lion_hearts_sweep_record_names_the_clone():
    off, song_off, _ = _song("Lion_Heart", ilv_filter_resume=False)
    on, song, lines = _song("Lion_Heart", ilv_filter_resume=True)
    assert on != off
    logged = [m for m in lines if m.startswith("ILV filter resume")]
    assert len(logged) == 1, logged
    ins = {i.number: i for i in song.instruments}
    base = {i.number: i for i in song_off.instruments}
    extra = sorted(set(ins) - set(base))
    assert len(extra) == 1, extra
    clone = ins[extra[0]]
    assert clone.filt_ptr == 0
    # the record it clones: same envelope, wave, pulse and vibrato, and a
    # filter pointer that was not 0
    twin = [b for b in base.values()
            if (b.ad, b.sr, b.wave_ptr, b.pulse_ptr, b.vib_ptr, b.gatetimer,
                b.firstwave) == (clone.ad, clone.sr, clone.wave_ptr,
                                 clone.pulse_ptr, clone.vib_ptr,
                                 clone.gatetimer, clone.firstwave)
            and b.filt_ptr]
    assert twin, "the clone's source record has a filter pointer"
    named = sum(1 for p in song.patterns
                for r in range(len(p) // 4) if p[4 * r + 1] == clone.number)
    # the 36 `$84` notes of record 4 (and the copies a pass makes of them)
    assert 36 <= named <= 60, named


@needs_corpus
def test_the_option_moves_exactly_the_files_that_carry_played_dollar_84_notes():
    """The census over the six interleaved filter files: only Lion_Heart and
    Radio_ACE play a `$84` before a filtered record's note (Sun_Never_Shines'
    79 are in patterns no orderlist reaches)."""
    moved = []
    for stem in ("Go_Go_Dash", "Lakers_vs_Celtics", "Lion_Heart",
                 "Pacific_Coast", "Radio_ACE", "Sun_Never_Shines"):
        off, _, _ = _song(stem, ilv_filter_resume=False)
        on, _, _ = _song(stem, ilv_filter_resume=True)
        if on != off:
            moved.append(stem)
    assert moved == ["Lion_Heart", "Radio_ACE"], moved
