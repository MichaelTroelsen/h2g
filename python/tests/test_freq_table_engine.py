"""A file with two players has two frequency tables, and they need not agree.

`find_freq_table`'s tie-break used to be "the longest validated run wins",
which is a rule about table *length* standing in for a question about which
*player* is being read. Powerplay Hockey is where the two come apart: it
carries the tune's engine at $42xx-$4Axx with an NTSC table at $4895 (96
entries, 0.696 semitones flat) and the nine game cues' engine at $36xx-$3Cxx
with a PAL one at $3A36 (95 entries, on the grid). The longest run separates
those by **one entry out of 96** -- so which tuning the harness recalibrated
the original to was decided by a coin flip, and `--engine 1` got the wrong
side of it: the nine cues were named in another key and read a mean melody of
12.2% where they play at 70.6%.

Two things are pinned here.

  * `near` -- a byte offset into the file, the caller's own player -- resolves
    the choice by nearness, the rule `_nearest_table` already uses for the
    instrument table of this same file (§ 7.iiiii).
  * Without `near` nothing moves. The default path returns exactly what it
    returned before, on all 95 corpus files, so no conversion byte can move;
    the only addition is `ambiguous`, which *says* the answer was a coin flip
    rather than silently picking a side.

The shift guard and the detune guard are deliberately not symmetric. A wrong
shift transposes a whole tune and no shift merely leaves it as it was, so the
shift is suppressed on disagreement. There is no such null action for a
tuning -- naming a tune on the wrong tuning and naming it on none are wrong by
the same 0.65 semitones -- so the disagreement is reported instead.
"""
import json
import pathlib
import sys

from corpus import CORPUS, needs_corpus

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[1]))

from h2g.sidfile import (_freq_table_sites, _GRID_TOLERANCE,  # noqa: E402
                         find_freq_table, load_sid)

POWERPLAY = "Powerplay_Hockey_USA_vs_USSR.sid"

# The two engines' table bases, as C64 addresses, and one anchor inside each
# player -- `detect`'s pattern-pointer offset for engine 0 and engine 1.
CUE_TABLE, TUNE_TABLE = 0x3A36, 0x4895
CUE_PATTERNS, TUNE_PATTERNS = 0x071A, 0x15C8


def _pp():
    return load_sid(str(CORPUS / POWERPLAY))


@needs_corpus
def test_powerplay_offers_two_tables_a_single_entry_apart():
    # The premise of the whole fix: the old tie-break's margin here is one
    # entry, which is not a difference anything musical depends on.
    sid = _pp()
    found = {}
    for addr in dict.fromkeys(_freq_table_sites(sid.data)):
        ft = find_freq_table(sid, near=sid.to_offset(addr))
        if ft is not None:
            found[ft.addr] = ft
    assert set(found) >= {CUE_TABLE, TUNE_TABLE}
    assert found[TUNE_TABLE].run - found[CUE_TABLE].run == 1
    # ...and they disagree about the tuning by an NTSC clock ratio, which is
    # the difference that decides how the original's notes are named.
    assert abs(found[TUNE_TABLE].detune - found[CUE_TABLE].detune) > 0.5


@needs_corpus
def test_near_picks_the_table_of_the_player_it_points_at():
    sid = _pp()
    assert find_freq_table(sid, near=TUNE_PATTERNS).addr == TUNE_TABLE
    assert find_freq_table(sid, near=CUE_PATTERNS).addr == CUE_TABLE


@needs_corpus
def test_neither_powerplay_table_carries_a_shift():
    # Why the fix is byte-neutral rather than merely measured to be: the shift
    # is what reaches the converter (detect.note_base), and it is 0 on both
    # sides of the choice, so no reading of this file can move a pattern note.
    sid = _pp()
    for near in (TUNE_PATTERNS, CUE_PATTERNS, None):
        assert find_freq_table(sid, near=near).shift == 0


@needs_corpus
def test_the_ambiguity_is_reported_and_near_clears_it():
    sid = _pp()
    assert find_freq_table(sid).ambiguous is True
    assert find_freq_table(sid, near=TUNE_PATTERNS).ambiguous is False
    assert find_freq_table(sid, near=CUE_PATTERNS).ambiguous is False


@needs_corpus
def test_powerplay_is_the_corpus_only_ambiguous_tuning():
    # A flag that fires on a third of the corpus would be noise. It fires on
    # the one file that carries two players tuned differently.
    flagged = sorted(p.name for p in CORPUS.glob("*.sid")
                     if getattr(find_freq_table(load_sid(str(p))),
                                "ambiguous", False))
    assert flagged == [POWERPLAY]


@needs_corpus
def test_the_default_path_still_takes_the_longest_run():
    # `near=None` must reproduce the old walk exactly -- including its
    # first-wins tie-break -- or the byte-neutrality claim is unfounded.
    for path in sorted(CORPUS.glob("*.sid")):
        sid = load_sid(str(path))
        cands = []
        for addr in dict.fromkeys(_freq_table_sites(sid.data)):
            ft = find_freq_table(sid, near=sid.to_offset(addr))
            if ft is not None and ft.addr == addr:
                cands.append(ft)
        got = find_freq_table(sid)
        if not cands:
            assert got is None, path.name
            continue
        assert got.addr == max(cands, key=lambda c: c.run).addr, path.name


@needs_corpus
def test_fidelity_reads_the_table_of_the_engine_it_converts():
    import fidelity as F                                    # noqa: PLC0415

    root = pathlib.Path(__file__).resolve().parents[2]
    doc = json.loads((root / "presets.json").read_text())
    sid = CORPUS / POWERPLAY
    opts = F._preset_opts(doc, POWERPLAY)

    tune = F.engine_freq_table(sid, {**opts, "engine": 0})
    cue = F.engine_freq_table(sid, {**opts, "engine": 1})
    assert tune.addr == TUNE_TABLE and cue.addr == CUE_TABLE
    # And what the harness does with them: the tune's NTSC table is worth a
    # siddump -c, the cues' table is on the grid and is worth none. Getting
    # that backwards is the 12.2%-against-70.6% this test exists for.
    assert F.table_calibration(sid, {**opts, "engine": 0})[0] != 0
    assert F.table_calibration(sid, {**opts, "engine": 1})[0] == 0


@needs_corpus
def test_the_engine_the_presets_convert_moves_no_file():
    # The report is taken at the preset engine, and none of its rows may move:
    # the nearness rule reaches only a file asked for by --engine.
    import fidelity as F                                    # noqa: PLC0415

    root = pathlib.Path(__file__).resolve().parents[2]
    doc = json.loads((root / "presets.json").read_text())
    for path in sorted(CORPUS.glob("*.sid")):
        opts = F._preset_opts(doc, path.name)
        blind = find_freq_table(load_sid(str(path)))
        aimed = F.engine_freq_table(path, opts)
        assert (blind is None) == (aimed is None), path.name
        if blind is not None:
            assert (blind.addr, blind.shift) == (aimed.addr, aimed.shift), path.name
            assert abs(blind.detune - aimed.detune) < 1e-9, path.name


@needs_corpus
def test_the_disagreement_threshold_is_the_grid_tolerance():
    # The one constant the detune guard needs, and it is the one already
    # separating an index shift from a tuning -- below it two tables name the
    # same pitches, above it they do not.
    sid = _pp()
    a = find_freq_table(sid, near=TUNE_PATTERNS)
    b = find_freq_table(sid, near=CUE_PATTERNS)
    assert abs(a.detune - b.detune) > _GRID_TOLERANCE
