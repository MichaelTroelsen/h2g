"""A cross-check between two shapes is only one if both matched in the same code.

`_find_two_stage` locates the two-stage block, reads the attack table out of
it, and confirms that reading independently against a second shape -- the push
chain that stacks the record's two bytes -- by requiring `duration ==
attack + 2`. The check is sound and holds in every corpus file that has the
mechanism.

It cannot survive a file that contains the player twice. Powerplay Hockey does
(§ 7.iiiii): the block matches the engine its patterns belong to and names
`$4A09`, while the *first* push chain in the file belongs to the cue engine and
names `$3C03`. Taking `search_file`'s first match on both probes compared one
engine's attack table against the other engine's duration table, found them
unequal, and reported no mechanism at all -- costing the file its drum, 215
noise frames the original sounds and we sounded none of.

The condition is unchanged. What changed is that a file may offer it more than
one candidate. See § 7.jjjjj.
"""
import pathlib
import sys

from corpus import CORPUS, needs_corpus  # noqa: E402

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[1]))

from h2g.convert import _detect_tables  # noqa: E402
from h2g.detect import TWO_STAGE_PUSH, _search_all  # noqa: E402
from h2g.sidfile import load_sid  # noqa: E402

PP = "Powerplay_Hockey_USA_vs_USSR.sid"


def _durations(sid) -> list[int]:
    """The duration table each push chain in the file names."""
    return [sid.data[j + 15] | sid.data[j + 16] << 8
            for j in _search_all(sid.data, TWO_STAGE_PUSH)
            if j + 16 < len(sid.data)]


@needs_corpus
def test_powerplay_has_two_push_chains_and_the_first_is_the_wrong_engine():
    """The fact the fix rests on, stated so it fails if the file is re-read."""
    sid = load_sid(str(CORPUS / PP))
    durs = _durations(sid)
    assert len(durs) >= 2, durs
    assert durs[0] == 0x3C03, "the cue engine's -- first in the file"
    assert 0x4A0B in durs[1:], "the tune's engine, and attack $4A09 plus 2"


@needs_corpus
def test_the_block_is_found_and_agrees_with_the_matching_chain():
    sid, det = _detect_tables(load_sid(str(CORPUS / PP)),
                              lambda *a, **k: None)
    assert det.effect_two_stage
    # The two bytes are inside record 0, at +9 and +11: the stride-16 dialect.
    assert det.two_stage_frames == det.two_stage_wave + 2
    assert det.two_stage_wave - det.instr_start == 9
    assert det.instr_stride == 16


@needs_corpus
def test_the_cross_check_is_still_a_cross_check():
    """Widening the search must not have turned the condition into a formality.

    Every file that reports the mechanism has to have a push chain naming
    exactly `attack + 2` -- that is the whole content of the check, and if a
    file could pass it without one, the check would be unfalsifiable.
    """
    seen = 0
    for path in sorted(CORPUS.glob("*.sid")):
        try:
            sid, det = _detect_tables(load_sid(str(path)), lambda *a, **k: None)
        except Exception:
            continue
        if not det.effect_two_stage:
            continue
        seen += 1
        assert any(sid.to_offset(a) == det.two_stage_frames
                   for a in _durations(sid)), path.name
    assert seen >= 40, f"only {seen} files reported the mechanism -- re-measure"
