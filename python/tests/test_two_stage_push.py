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
from h2g.detect import (TWO_STAGE_PUSH, TWO_STAGE_PUSH_ANCHORED,
                        _search_all)  # noqa: E402
from h2g.search import search_file  # noqa: E402
from h2g.sidfile import HLEN, load_sid  # noqa: E402

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

    Every file that reports the mechanism has to establish `duration ==
    attack + 2` against the code, not against itself -- and if a file could
    pass without doing so, the check would be unfalsifiable.

    **v0.5.459 gives that fact a SECOND route and this guard now pins both.**
    The interleaved dialect's push chain is interrupted -- its third load sits
    34 bytes after the first two, behind a conditional self-modify and an X
    save/restore -- so `TWO_STAGE_PUSH`, one contiguous run, matches nowhere in
    those files while the duration really is pushed from attack+2.
    `TWO_STAGE_PUSH_ANCHORED` asks the narrower question directly, formatted
    with the expected address, so it confirms and cannot invent.

    The guard is therefore a disjunction AND a partition: every file takes one
    route or the other, and the set taking the anchored one is named. A
    regression that made the anchored form the general answer would move a file
    out of `by_chain` and fail here, which is the formality this test exists to
    prevent.
    """
    seen = 0
    by_chain, by_anchor = [], []
    for path in sorted(CORPUS.glob("*.sid")):
        try:
            sid, det = _detect_tables(load_sid(str(path)), lambda *a, **k: None)
        except Exception:
            continue
        if not det.effect_two_stage:
            continue
        seen += 1
        if any(sid.to_offset(a) == det.two_stage_frames
               for a in _durations(sid)):
            by_chain.append(path.name)
            continue
        instr_cpu = det.instr_start - (HLEN - 1) + sid.load_addr
        want = det.two_stage_frames - det.instr_start + instr_cpu
        assert search_file(sid.data, TWO_STAGE_PUSH_ANCHORED.format(
            lo=want & 0xFF, hi=want >> 8)) > -1, path.name
        # AND it has to DISCRIMINATE, or it is the formality this test is
        # named for. A four-byte pattern is short, so the guard is that the
        # NEIGHBOURING addresses do not match: measured over these six, only
        # the exact operand does, at every one of -2, -1, +1, +2 and +3. If
        # the anchor is ever loosened to something that matches a bare PHA,
        # this is the assertion that fails.
        for delta in (-2, -1, 1, 2, 3):
            near = want + delta
            assert search_file(sid.data, TWO_STAGE_PUSH_ANCHORED.format(
                lo=near & 0xFF, hi=near >> 8)) <= -1, (path.name, delta)
        by_anchor.append(path.name)

    assert by_anchor == ["Go_Go_Dash.sid", "Lakers_vs_Celtics.sid",
                         "Lion_Heart.sid", "Pacific_Coast.sid",
                         "Radio_ACE.sid", "Sun_Never_Shines.sid"], by_anchor
    # The contiguous chain is still how the great majority answer.
    assert len(by_chain) >= 40, by_chain
    assert seen >= 40, f"only {seen} files reported the mechanism -- re-measure"
