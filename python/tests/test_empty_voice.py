"""A voice orderlist holding nothing but an end marker costs its whole subtune.

`gsong.c:1338-1349` sets `songlen` to the index of the first byte `>= LOOPSONG`,
so a track starting with `$FF` has `songlen == 0`. `greloc.c:200-255` counts
`songs` as the subtunes whose three voices all have nonzero length, and
`greloc.c:653` then writes `for (c = 0; c < songs; c++)` over the *original*
indices, re-testing validity:

  * an invalid subtune keeps its slot and is written as a zero-length stub
    (`:701-706`) -- present in the packed .sid, playing nothing;
  * every subtune at or past the count is never written at all.

Nothing is renumbered and the list is not compacted; an earlier description of
this in the repo's docs said otherwise and was wrong.

Measured on the corpus with `--legal-restart` off, seven files carry at least
one such voice, and Rasputin is the worst: subtunes 0 and 1 invalid, `songs`
15 of 17, and subtunes 15 and 16 -- 309 and 621 sounding rows -- absent from
the packed .sid with no layer reporting it.
"""
import pathlib
from corpus import CORPUS as _CORPUS, needs_corpus  # noqa: E402
import sys

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[1]))


from h2g.patterns import DEFAULT_TRACK, GT_ORDER_RESTART
from h2g.tracks import ensure_playable_orderlists

CORPUS = _CORPUS


def _songlen(track):
    """What gsong.c:1344 would compute for this orderlist."""
    for i, b in enumerate(track):
        if b >= GT_ORDER_RESTART:
            return i
    return len(track)


def _subtune(*voices):
    return [list(v) for v in voices]


PLAIN = [0x01, GT_ORDER_RESTART, 0x00]      # one pattern, legal restart


def test_a_bare_end_marker_is_replaced():
    voices = _subtune([GT_ORDER_RESTART, 0x00], PLAIN, PLAIN)
    assert ensure_playable_orderlists(voices) == 1
    assert voices[0] == DEFAULT_TRACK
    assert all(_songlen(v) for v in voices)   # greloc.c:201 now accepts it


def test_a_subtune_with_no_empty_voice_is_untouched():
    voices = _subtune(PLAIN, [0x03, GT_ORDER_RESTART, 0x00], PLAIN)
    before = [list(v) for v in voices]
    assert ensure_playable_orderlists(voices) == 0
    assert voices == before


def test_a_track_starting_with_a_command_is_not_mistaken_for_a_marker():
    # $D0-$FE are repeats and transposes, not the marker: songlen counts them.
    for lead in (0xD2, 0xE8, 0xF4, 0xFE):
        voices = _subtune([lead, 0x03, GT_ORDER_RESTART, 0x00], PLAIN, PLAIN)
        assert ensure_playable_orderlists(voices) == 0
        assert voices[0][0] == lead


def test_every_empty_voice_of_a_subtune_is_repaired():
    voices = _subtune([GT_ORDER_RESTART, 0x00], PLAIN, [GT_ORDER_RESTART, 0x00])
    assert ensure_playable_orderlists(voices) == 1     # one subtune revived
    assert all(_songlen(v) for v in voices)


def test_a_revived_subtune_also_gets_its_siblings_restart_legalised():
    # greloc.c:244 runs only inside the all-voices-nonzero guard, so reviving a
    # subtune exposes stop markers that were never checked before. Repairing
    # only the empty voice turns Rasputin from "packs 15 of 17" into "packs
    # nothing".
    stopper = [0x02, 0x03, GT_ORDER_RESTART, 0xFD]
    voices = _subtune([GT_ORDER_RESTART, 0x00], stopper, PLAIN)
    assert ensure_playable_orderlists(voices) == 1
    assert voices[1] == [0x02, 0x03, GT_ORDER_RESTART, 0x00]


def test_an_untouched_subtune_keeps_its_stop_marker():
    # Only revived subtunes pay that price; everything else stays
    # --legal-restart's business.
    stopper = [0x02, 0x03, GT_ORDER_RESTART, 0xFD]
    voices = _subtune(stopper, PLAIN, PLAIN)
    assert ensure_playable_orderlists(voices) == 0
    assert voices[0][-1] == 0xFD


def test_it_reports_what_it_changed():
    lines = []
    ensure_playable_orderlists(
        _subtune([GT_ORDER_RESTART, 0x00], PLAIN, PLAIN), lines.append)
    assert lines and "1" in lines[0]


def test_nothing_is_logged_when_nothing_changes():
    lines = []
    ensure_playable_orderlists(_subtune(PLAIN, PLAIN, PLAIN), lines.append)
    assert lines == []


# --- end to end ------------------------------------------------------------

@needs_corpus
def test_rasputin_keeps_every_subtune_without_legal_restart():
    """The regression itself, at default options.

    Before this repair ran unconditionally, Rasputin's subtunes 0 and 1 were
    zero-length, so gt2reloc wrote 15 of 17 subtunes and the last two were
    lost. The repair is not conditional on --legal-restart because a
    zero-length voice is a problem whatever the restart position is.
    """
    sid = CORPUS / "Rasputin.sid"
    if not sid.exists():
        import pytest
        pytest.skip("corpus not available")

    from h2g.convert import convert

    from h2g import convert as convmod

    seen = {}
    orig = convmod.build_sng

    def spy(s, d, tracks, patterns, **kw):
        seen["tracks"] = [list(t) for t in tracks]
        return orig(s, d, tracks, patterns, **kw)

    convmod.build_sng = spy
    try:
        convert(str(sid), log=lambda m: None, legal_restart=False)
    finally:
        convmod.build_sng = orig

    tracks = seen["tracks"]
    assert len(tracks) % 3 == 0
    subtunes = len(tracks) // 3
    valid = sum(1 for s in range(subtunes)
                if all(_songlen(tracks[s * 3 + v]) for v in range(3)))
    assert valid == subtunes, "greloc.c would truncate at the first shortfall"
    assert subtunes == 17
