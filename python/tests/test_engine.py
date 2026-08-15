"""`--engine`: rip the other player in a file that carries more than one.

Powerplay Hockey's PSID header declares ten subtunes. One is the tune, and
the other nine are short game cues driven by a *second* player -- instruments
at `$3BA0`, orderlists at `$3C66`, patterns at `$3C9C`/`$3CBB` -- which the
converter had never reached, because the digi engine matches first and every
classic chain in `detect()` is guarded on that (§ 7.kkkkk).

The whole option is one line: decline `_detect_digi`, and the chains that were
already there find the other player unaided. No new signature was written for
this.

Two properties matter and are pinned below. `engine=0` is byte-identical for
every corpus file, because the digi probe runs exactly as it did. And
`engine=1` is not a *setting* -- it is a different song out of the same file,
so it is in `presets.EXCLUDED_FROM_ALWAYS` and nothing generated uses it.
"""
import contextlib
import io
import pathlib
import sys

import pytest

from corpus import CORPUS, needs_corpus  # noqa: E402

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[1]))

import presets  # noqa: E402
from h2g.convert import UnsupportedSidError, _detect_tables, convert  # noqa: E402
from h2g.sidfile import load_sid  # noqa: E402

PP = "Powerplay_Hockey_USA_vs_USSR.sid"


def _quiet(path, **kw):
    with contextlib.redirect_stdout(io.StringIO()):
        return convert(str(path), log=lambda *a: None, **kw)


def _cpu(sid, off):
    return sid.load_addr + off - sid.to_offset(sid.load_addr)


@needs_corpus
def test_engine_one_finds_the_cue_player_with_no_new_signature():
    sid, det = _detect_tables(load_sid(str(CORPUS / PP)),
                              lambda *a, **k: None, 1)
    assert _cpu(sid, det.instr_start) == 0x3BA0
    assert _cpu(sid, det.track_lo) == 0x3C66      # the Rasputin selector shape
    assert _cpu(sid, det.track_hi) == 0x3C69      # lo,lo,lo then hi,hi,hi
    assert _cpu(sid, det.pattern_lo) == 0x3C9C
    assert _cpu(sid, det.pattern_hi) == 0x3CBB
    assert det.track_voices == 3
    assert det.pattern_dialect == "classic"
    assert det.instr_stride == 8


@needs_corpus
def test_the_two_engines_are_different_players_not_two_copies():
    """§ 7.iiiii called them "the same code at two bases". They are not.

    The tune's engine is the digi variant -- 16-byte records, four voices, an
    interleaved orderlist table read straight from its own signature. The cue
    engine is the classic one -- 8-byte records, three voices, separate lo and
    hi tables. They are related players, and the difference is exactly what
    makes one line enough to select between them.
    """
    load = load_sid(str(CORPUS / PP))
    _, main = _detect_tables(load, lambda *a, **k: None, 0)
    _, cues = _detect_tables(load_sid(str(CORPUS / PP)),
                             lambda *a, **k: None, 1)
    assert (main.instr_stride, main.track_voices) == (16, 4)
    assert (cues.instr_stride, cues.track_voices) == (8, 3)
    assert main.pattern_dialect == "digi" and cues.pattern_dialect == "classic"


@needs_corpus
def test_the_cue_orderlists_name_only_patterns_that_exist():
    """The nine rows decode; a tenth would run into the pattern table.

    `$3C9C - $3C66` is 54, which is 9 x 6 exactly -- the subtune count falls
    out of the gap between the two tables rather than from the header, whose
    ten counts the tune as well.
    """
    sid, det = _detect_tables(load_sid(str(CORPUS / PP)),
                              lambda *a, **k: None, 1)
    assert det.pattern_lo - det.track_lo == 9 * 6
    npat = det.pattern_hi - det.pattern_lo
    d = sid.data
    for cue in range(9):
        for voice in range(3):
            k = det.track_lo + voice + cue * 6
            addr = d[k] | d[k + 3] << 8
            off = sid.to_offset(addr)
            assert 0 < off < len(d), (cue, voice, hex(addr))
            for step in range(64):          # to the first terminator
                b = d[off + step]
                if b in (0xFE, 0xFF):
                    break
                if not b & 0x80:
                    assert b < npat, (cue, voice, b, npat)
            else:
                pytest.fail(f"cue {cue} voice {voice}: no terminator")


@needs_corpus
def test_engine_one_converts_nine_subtunes():
    b = _quiet(CORPUS / PP, engine=1)
    assert len(b) > 1000
    # The tune's rip is a different song, not a longer or shorter one.
    assert b != _quiet(CORPUS / PP)


@needs_corpus
def test_engine_zero_is_byte_identical_across_the_corpus():
    """The digi probe runs exactly as before, so the default cannot move."""
    for path in sorted(CORPUS.glob("*.sid")):
        try:
            want = _quiet(path)
        except Exception as e:
            want = type(e).__name__
        try:
            got = _quiet(path, engine=0)
        except Exception as e:
            got = type(e).__name__
        assert want == got, path.name


@needs_corpus
def test_engine_one_refuses_the_files_that_have_only_a_digi_player():
    """Declining the digi engine must not invent a second one.

    Eight corpus files are digi-only. For them `engine=1` leaves the classic
    chains nothing to find, and refusing is the honest answer -- these are the
    files where a silent fallback would have produced a plausible wrong song.
    """
    digi_only = ["After_8.sid", "Kings_of_the_Beach_intro.sid", "Mr_Meaner.sid",
                 "Off_the_Cuff.sid", "One_on_One_Jordan_vs_Bird.sid",
                 "Pygmies_Revenge.sid", "Rikky.sid", "Rock_Tells_the_Tale.sid"]
    for name in digi_only:
        _quiet(CORPUS / name)                       # engine 0 converts
        with pytest.raises(UnsupportedSidError):
            _quiet(CORPUS / name, engine=1)


def test_engine_is_never_a_preset():
    """A preset records the best way to convert *the* tune. The cues are not
    a better conversion of it, so this option must stay off the always block
    and out of every generated artefact."""
    assert "engine" in presets.EXCLUDED_FROM_ALWAYS
    assert "engine" not in presets.FIXED
    assert "engine" not in presets.FIDELITY_TOGGLES
