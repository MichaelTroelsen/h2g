"""What a command does on the rows an event holds for.

An event with wait W occupies W+1 rows, and a Goattracker command byte is
executed on the row it appears on. So a *continuous* effect must be repeated
on every one of them -- that is how a portamento keeps stepping, gplay.c:740
re-reading the speed each tick -- and a *one-shot* effect must appear once, or
one intent becomes W+1 of them.

The hold loop's default is **repeat**, which is right for the two commands
this converter emits continuously and wrong for anything added later that acts
once. v0.5.284's `CMD_SETWAVE` experiment inherited that default: 61 rows were
designed, 673 command bytes were written, and the corpus A/B it fed measured
something other than the change it described (§§ 7.ooooo, 7.ppppp). These
tests pin the property that would have caught it, in a form that does not
depend on `CMD_SETWAVE` ever being emitted.
"""
import pathlib
import sys

from corpus import CORPUS, needs_corpus  # noqa: E402

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[1]))

from h2g.convert import _detect_tables, convert  # noqa: E402
from h2g.patterns import (GT_NO_NOTE, ONE_SHOT_COMMANDS,  # noqa: E402
                          convert_patterns)
from h2g.sidfile import load_sid  # noqa: E402
import songview as SV  # noqa: E402

# gcommon.h: 1 PORTAUP, 2 PORTADOWN, 3 TONEPORTA. The first two step a value
# every tick and must persist; the third assigns in one call (gplay.c:811).
CONTINUOUS = {1, 2}


def test_the_one_shot_commands_are_disjoint_from_the_continuous_ones():
    """The property, not the membership. This asserted
    `== frozenset({3})` until v0.5.311 added CMD_SETWAVE and the literal
    failed -- a set written down in a test drifts from the module that
    declares it, which is the same shape as the combination counts in
    test_preset_passthrough.

    What must hold is that a command is applied once or stepped every tick
    and never both: `gplay.c:740` re-reads a portamento's speed each tick, so
    repeating it is how it works, while CMD_TONEPORTA with parameter 0
    assigns `freq = targetfreq` in one call (gplay.c:811) and CMD_SETWAVE
    assigns `cptr->wave` in one (gplay.c:433).
    """
    assert 3 in ONE_SHOT_COMMANDS, "CMD_TONEPORTA is applied once"
    assert not (ONE_SHOT_COMMANDS & CONTINUOUS), (
        "a command cannot be both stepped every tick and applied once")


@needs_corpus
def test_no_one_shot_command_survives_into_a_hold_row():
    """The property itself, over every pattern the corpus produces.

    A hold row is `GT_NO_NOTE` with no instrument; if it carries a command
    from `ONE_SHOT_COMMANDS`, the event applied that command more than once.
    """
    offenders = []
    holds = 0
    for path in sorted(CORPUS.glob("*.sid")):
        try:
            sid, det = _detect_tables(load_sid(str(path)),
                                      lambda *a, **k: None)
            # (patterns, lengths) -- unpacked, because iterating the tuple
            # yields two lists whose elements are lists, `note` never equals
            # GT_NO_NOTE, and the sweep passes having compared nothing. That
            # is what the first draft of this file did.
            pats, _lens = convert_patterns(sid, det, lambda *a, **k: None)
        except Exception:                                      # noqa: BLE001
            continue
        for n, pat in enumerate(pats or []):
            for k in range(0, len(pat) - 3, 4):
                note, instr, c1, _ = pat[k:k + 4]
                if note == GT_NO_NOTE and not instr:
                    holds += 1
                    if c1 in ONE_SHOT_COMMANDS:
                        offenders.append((path.name, n, k // 4, c1))
    # A "nothing found" that examined nothing is not a pass. The first draft
    # of this file iterated `convert_patterns`' (patterns, lengths) tuple and
    # compared lists to GT_NO_NOTE, matching zero rows and reporting clean.
    assert holds > 10000, f"only {holds} hold rows examined -- sweep is vacuous"
    assert offenders == [], offenders[:8]


@needs_corpus
def test_a_continuous_command_does_survive():
    """The other half: without it, "no command on a hold row" would pass by
    emitting none at all, and every slide in the corpus would stop after one
    row."""
    seen = files = 0
    for path in sorted(CORPUS.glob("*.sid")):
        try:
            sid, det = _detect_tables(load_sid(str(path)),
                                      lambda *a, **k: None)
            # `slides` is opt-in and is what emits CMD_PORTAUP/DOWN at all;
            # without it no continuous command exists to look for.
            pats, _lens = convert_patterns(sid, det, lambda *a, **k: None,
                                           slides=True)
        except Exception:                                      # noqa: BLE001
            continue
        files += 1
        for pat in pats or []:
            for k in range(0, len(pat) - 3, 4):
                note, instr, c1, _ = pat[k:k + 4]
                if note == GT_NO_NOTE and not instr and c1 in CONTINUOUS:
                    seen += 1
    assert files > 20, f"only {files} files decoded -- the sweep is too thin"
    assert seen > 0, ("no continuous command reaches a hold row -- every slide "
                      "would stop after its first row")


@needs_corpus
def test_the_property_holds_in_the_written_sng():
    """Read back through songview's parser rather than the writer's own
    intermediate, so pattern slicing, dedup and packing are covered too."""
    for name in ("Commando.sid", "IK_plus.sid",
                 "Auf_Wiedersehen_Monty.sid"):
        song = SV.parse_sng(convert(str(CORPUS / name),
                                    log=lambda *a: None))
        for n, pat in enumerate(song.patterns):
            for k in range(0, len(pat) - 3, 4):
                note, instr, c1, _ = pat[k:k + 4]
                assert not (note == GT_NO_NOTE and not instr
                            and c1 in ONE_SHOT_COMMANDS), (name, n, k // 4)
