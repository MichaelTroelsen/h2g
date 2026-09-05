"""`abpage.py`: the A/B listening pages built from what listen.py staged.

The page itself cannot be tested here — whether two `<audio>` elements really
stay in sync is a browser question. What is testable is everything that decides
*what the page says*: the two parsers that read `FIDELITY.md` and
`LISTENING.md`, and the guarantee that a page quotes them rather than restating
them. A page disagreeing with the report it cites would be the failure mode
worth catching, since a listener would then be told the wrong thing to listen
for.
"""
import base64
import html.parser
import math
import os
import struct
import sys
import time
import wave
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import abpage as A  # noqa: E402

VOID = {"area", "base", "br", "col", "embed", "hr", "img", "input",
        "link", "meta", "param", "source", "track", "wbr"}


class Balance(html.parser.HTMLParser):
    """Every non-void element opened is closed, in order."""

    def __init__(self):
        super().__init__(convert_charrefs=True)
        self.stack, self.bad = [], []

    def handle_starttag(self, tag, attrs):
        if tag not in VOID:
            self.stack.append(tag)

    def handle_endtag(self, tag):
        if tag in VOID:
            return
        if not self.stack:
            self.bad.append("closed %s with nothing open" % tag)
        elif self.stack[-1] != tag:
            self.bad.append("closed %s inside %s" % (tag, self.stack[-1]))
        else:
            self.stack.pop()


def _balanced(markup):
    p = Balance()
    p.feed(markup)
    p.close()
    return p.bad + (["unclosed: %s" % ",".join(p.stack)] if p.stack else [])


ROW = {"melody": "100%", "seq": "97%", "retrig": "1.00", "wave": "98%",
       "gate": "80%", "hold": "-", "onset": "100%", "bend": "0.46x",
       "vib": "0.69x", "drift": "+0.0"}


def test_the_page_is_well_formed():
    got = A.page("W_A_R", ROW, ["**Legato.** 419 changes"], "v0.5.305",
                 embed=False, index_link=True)
    assert _balanced(got) == []


def test_the_index_is_well_formed():
    got = A.index(["A_Tune", "B_Tune"], {"A_Tune": ROW}, "v0.5.305")
    assert _balanced(got) == []


def test_a_local_page_references_the_wavs_beside_it():
    """The reason a local page can carry two minutes where an embedded one
    cannot: it never inlines the audio."""
    got = A.page("Delta", ROW, [], "v1", embed=False, index_link=True)
    assert 'src="Delta.original.wav"' in got
    assert 'src="Delta.h2g.wav"' in got
    assert "base64" not in got


def test_a_dash_column_is_dropped_rather_than_printed():
    """`-` in FIDELITY.md means no shared instrument key, not zero. Printing it
    as a value would read as a score of nothing."""
    got = A.page("X", ROW, [], "v1", embed=False, index_link=False)
    assert "<span>hold</span>" not in got
    assert "<span>melody</span>" in got


def test_a_tune_with_no_row_says_so_rather_than_showing_an_empty_rail():
    got = A.page("Unmeasured", {}, [], "v1", embed=False, index_link=False)
    assert "not in FIDELITY.md" in got


def test_a_tune_with_no_notes_says_the_useful_thing():
    got = A.page("X", ROW, [], "v1", embed=False, index_link=False)
    assert "no check in the repo can see" in got


def test_markdown_becomes_markup_and_escapes_first():
    assert A.md("**a** and `b`") == "<strong>a</strong> and <code>b</code>"
    assert A.md("<script>") == "&lt;script&gt;"
    assert "&mdash;" in A.md("a -- b")


def test_fidelity_rows_reads_the_report(tmp_path, monkeypatch):
    doc = ("# Fidelity report\n\n"
           "| File | melody | gate |\n|---|---|---|\n"
           "| Delta.sid | 99% | 84% |\n"
           "| W_A_R.sid | 100% | 80% |\n")
    (tmp_path / "FIDELITY.md").write_text(doc, encoding="utf-8")
    monkeypatch.setattr(A, "ROOT", tmp_path)
    rows = A.fidelity_rows()
    assert rows["Delta"]["gate"] == "84%"
    assert rows["W_A_R"]["melody"] == "100%"
    assert "File" not in rows


def test_fidelity_rows_keeps_the_first_row_for_a_repeated_file(tmp_path, monkeypatch):
    """The report prints per-file rows in more than one table -- the filter
    section repeats each file with different columns. The main table comes
    first and is the one meant, so the reader must not let a later table
    overwrite it."""
    doc = ("| File | melody | gate |\n|---|---|---|\n"
           "| Delta.sid | 99% | 84% |\n\n"
           "## Filter\n\n"
           "| File | melody | gate |\n|---|---|---|\n"
           "| Delta.sid | 0/0 | 0/0 |\n")
    (tmp_path / "FIDELITY.md").write_text(doc, encoding="utf-8")
    monkeypatch.setattr(A, "ROOT", tmp_path)
    assert A.fidelity_rows()["Delta"]["melody"] == "99%"


def test_listening_notes_reads_the_staged_prose(tmp_path, monkeypatch):
    doc = ("# Listening pass\n\n"
           "## W_A_R — *named*\n\n"
           "Packed at `-S4`: this player wants 4 calls per frame.\n\n"
           "- **No legato.** 419 note changes\n"
           "- **Bends.** half as far\n\n"
           "## Delta — *named*\n\n"
           "- **Something.** else\n\n"
           "## What to write down\n\nFor each tune, one line.\n")
    listen = tmp_path / "build" / "listen"
    listen.mkdir(parents=True)
    (listen / "LISTENING.md").write_text(doc, encoding="utf-8")
    monkeypatch.setattr(A, "LISTEN", listen)
    notes = A.listening_notes()
    assert len(notes["W_A_R"]) == 3          # the Packed-at line plus two bullets
    assert notes["W_A_R"][0].startswith("Packed at")
    assert notes["Delta"] == ["**Something.** else"]
    assert "What to write down" not in notes


def test_both_templates_declare_a_charset():
    """Neither template has a <head>, so the charset meta tag is the only
    thing standing between the page and the browser guessing the encoding --
    a guess that would corrupt every &mdash;/&middot; entity already baked
    into these pages."""
    page_got = A.page("W_A_R", ROW, [], "v1", embed=False, index_link=False)
    index_got = A.index(["W_A_R"], {"W_A_R": ROW}, "v1")
    assert '<meta charset="utf-8">' in page_got
    assert '<meta charset="utf-8">' in index_got


def test_the_page_quotes_the_notes_it_was_given():
    """A page states what to listen for; if it invented that, the listener
    would be primed for the wrong defect."""
    got = A.page("W_A_R", ROW, ["**No legato.** 419 note changes"], "v1",
                 embed=False, index_link=False)
    assert "<strong>No legato.</strong> 419 note changes" in got


# ---- prune_stale_pages --------------------------------------------------
#
# `listen.py` never deletes its own staged output, and until prune_stale_pages
# existed neither did abpage.py: removing a staged pair (its `.original.wav` /
# `.h2g.wav`) left that tune's `<name>.html` on disk forever, reachable by URL
# even though no index.html links it any more. Three `.v[123].html` files from
# an earlier bug (before the current voice-suffix filter existed) had to be
# found and deleted by hand -- prune_stale_pages is the fix that makes that a
# rebuild rather than a manual cleanup.

def test_prune_stale_pages_removes_pages_for_untracked_names(tmp_path, monkeypatch):
    monkeypatch.setattr(A, "LISTEN", tmp_path)
    for f in ("Kept.html", "Stale.html", "Stale.embed.html",
              "Stale.v1.html", "index.html"):
        (tmp_path / f).write_text("x", encoding="utf-8")

    removed = A.prune_stale_pages(["Kept"])

    assert {p.name for p in removed} == {
        "Stale.html", "Stale.embed.html", "Stale.v1.html"}
    assert (tmp_path / "Kept.html").exists()
    assert (tmp_path / "index.html").exists()          # never pruned here
    assert not (tmp_path / "Stale.html").exists()
    assert not (tmp_path / "Stale.embed.html").exists()
    assert not (tmp_path / "Stale.v1.html").exists()


def test_prune_stale_pages_never_touches_the_staged_pair(tmp_path, monkeypatch):
    """The hazard this function must not create: build/listen holds staged
    A/B pairs a human is actively using, and only the generated `.html` is
    fair game -- the `.wav`/`.trace.json` a rebuild would need to regenerate
    the page must survive even when the page itself is pruned."""
    monkeypatch.setattr(A, "LISTEN", tmp_path)
    for f in ("Removed.html", "Removed.original.wav", "Removed.h2g.wav",
              "Removed.trace.json", "Removed.h2g.sng"):
        (tmp_path / f).write_text("x", encoding="utf-8")

    removed = A.prune_stale_pages([])                   # no tune staged now

    assert [p.name for p in removed] == ["Removed.html"]
    assert (tmp_path / "Removed.original.wav").exists()
    assert (tmp_path / "Removed.h2g.wav").exists()
    assert (tmp_path / "Removed.trace.json").exists()
    assert (tmp_path / "Removed.h2g.sng").exists()


def test_prune_stale_pages_keeps_everything_when_nothing_is_stale(tmp_path, monkeypatch):
    monkeypatch.setattr(A, "LISTEN", tmp_path)
    (tmp_path / "Kept.html").write_text("x", encoding="utf-8")
    (tmp_path / "index.html").write_text("x", encoding="utf-8")

    assert A.prune_stale_pages(["Kept"]) == []
    assert (tmp_path / "Kept.html").exists()


def test_prune_stale_pages_on_a_missing_directory_is_a_no_op(tmp_path, monkeypatch):
    monkeypatch.setattr(A, "LISTEN", tmp_path / "does-not-exist")
    assert A.prune_stale_pages(["Anything"]) == []


# ---- notes-per-voice strip -----------------------------------------------
#
# build/fidelity.json (a `fidelity.py --json` run) is a LIST of per-file
# dicts, not a dict keyed by name -- getting that wrong is the exact mistake
# CLAUDE.md records a sibling probe making. It carries no per-note pitch/time
# sequence, only each voice's orig_attacks/our_attacks *count* plus the set
# of distinct pitches either side used, so the strip these tests check is a
# density strip keyed on counts, not a real piano roll.

FJ_ROW = {
    "file": "W_A_R.sid",
    "orig_attacks": 8, "our_attacks": 9,
    "voices": [
        {"orig_attacks": 5, "our_attacks": 4,
         "orig_pitches": ["C-4", "D-4"], "our_pitches": ["C-4"]},
        {"orig_attacks": 3, "our_attacks": 3,
         "orig_pitches": [], "our_pitches": []},
        {"orig_attacks": 0, "our_attacks": 2,
         "orig_pitches": [], "our_pitches": ["E-5"]},
    ],
}


def test_fidelity_json_rows_reads_the_list_shape(tmp_path, monkeypatch):
    build = tmp_path / "build"
    build.mkdir()
    (build / "fidelity.json").write_text(
        '[{"file": "W_A_R.sid", "voices": []}, {"file": "Delta.sid", "voices": []}]',
        encoding="utf-8")
    monkeypatch.setattr(A, "ROOT", tmp_path)
    rows = A.fidelity_json_rows()
    assert set(rows) == {"W_A_R", "Delta"}


def test_fidelity_json_rows_on_a_dict_shape_is_empty_not_a_crash(tmp_path, monkeypatch):
    """The documented hazard: a probe that assumes a dict-keyed file and
    silently iterates zero rows. Guard the wrong top-level shape explicitly
    rather than let `for row in doc` iterate a dict's keys as strings."""
    build = tmp_path / "build"
    build.mkdir()
    (build / "fidelity.json").write_text('{"W_A_R.sid": {"voices": []}}',
                                         encoding="utf-8")
    monkeypatch.setattr(A, "ROOT", tmp_path)
    assert A.fidelity_json_rows() == {}


def test_fidelity_json_rows_missing_file_is_empty(tmp_path, monkeypatch):
    monkeypatch.setattr(A, "ROOT", tmp_path)
    assert A.fidelity_json_rows() == {}


def test_notes_strip_counts_match_the_fidelity_json_per_voice_attacks():
    """The verify clause, verbatim: the strip's counts must equal the
    per-voice attack counts fidelity's own --json output reports."""
    got = A.notes_strip_card("W_A_R", FJ_ROW)
    assert got.count('class="nt o"') == sum(
        vv["orig_attacks"] for vv in FJ_ROW["voices"])
    assert got.count('class="nt u"') == sum(
        vv["our_attacks"] for vv in FJ_ROW["voices"])
    # And the printed per-voice number, not just the tick count, matches.
    assert '<span class="scount">5</span>' in got
    assert '<span class="scount">4</span>' in got
    assert '<span class="scount">3</span>' in got
    assert '<span class="scount">0</span>' in got
    assert '<span class="scount">2</span>' in got


def test_notes_strip_totals_equal_the_row_aggregate():
    """Summed across voices, the strip's counts equal the same orig/ours
    total FIDELITY.md's row for this file reports -- fidelity.json's own
    top-level orig_attacks/our_attacks are that total, verified corpus-wide
    (95/95 rows) to equal the sum of their own `voices` entries."""
    got = A.notes_strip_card("W_A_R", FJ_ROW)
    assert got.count('class="nt o"') == FJ_ROW["orig_attacks"]
    assert got.count('class="nt u"') == FJ_ROW["our_attacks"]


def test_notes_strip_shows_the_pitch_sets_per_voice():
    got = A.notes_strip_card("W_A_R", FJ_ROW)
    assert "C-4, D-4" in got
    assert "E-5" in got


def test_notes_strip_is_capped_but_the_printed_count_is_not():
    """A pathological voice must not blow the page out with thousands of
    <i> elements, but the number shown beside it stays exact regardless."""
    fj = {"voices": [{"orig_attacks": A.STRIP_MAX_TICKS + 50,
                       "our_attacks": 1, "orig_pitches": [], "our_pitches": []}]}
    got = A.notes_strip_card("Dense", fj)
    assert got.count('class="nt o"') == A.STRIP_MAX_TICKS
    assert ('<span class="scount">%d</span>' % (A.STRIP_MAX_TICKS + 50)) in got


def test_notes_strip_is_absent_with_no_voices():
    """No fidelity.json row (or a row with no `voices` key) draws nothing --
    the same "say so, don't fabricate" rule the rest of the page follows for
    a tune with no FIDELITY.md row at all."""
    assert A.notes_strip_card("X", None) == ""
    assert A.notes_strip_card("X", {}) == ""
    assert A.notes_strip_card("X", {"voices": []}) == ""


def test_notes_strip_card_is_well_formed():
    got = A.notes_strip_card("W_A_R", FJ_ROW)
    assert _balanced('<div class="wrap">%s</div>' % got) == []


def test_the_page_embeds_the_notes_strip_when_fidjson_is_given():
    got = A.page("W_A_R", ROW, [], "v1", embed=False, index_link=False,
                 fidjson=FJ_ROW)
    assert "Notes per voice" in got
    assert got.count('class="nt o"') == FJ_ROW["orig_attacks"]
    assert _balanced(got) == []


def test_the_page_omits_the_notes_strip_when_no_fidjson_is_given():
    """Every existing call to page() (this test file's own ROW-based tests
    included) passes no `fidjson` -- the new card must default to invisible
    rather than change what those pages say."""
    got = A.page("W_A_R", ROW, [], "v1", embed=False, index_link=False)
    assert "Notes per voice" not in got


# ---- spectrogram: both sides' FFT, precomputed at build time ------------
#
# The verify clause is "readable at 120s, drawing in under a second" -- the
# under-a-second part cannot be tested here (it is a browser question, same
# disclaimer as the module docstring), so what these tests pin is that the
# heavy pass runs in Python at build time and hands the page two fixed-size
# byte grids, and that it degrades to "no card" rather than crashing on the
# same malformed/missing input the rest of this file already exercises.

def _write_test_wav(path, seconds=0.3, freq=440.0, framerate=8000):
    """A short real mono 16-bit WAV -- enough samples for one SPEC_WINDOW
    frame, at a framerate cheap enough to keep the test fast."""
    n = int(seconds * framerate)
    frames = bytearray()
    for i in range(n):
        v = int(16000 * math.sin(2 * math.pi * freq * i / framerate))
        frames += struct.pack("<h", v)
    with wave.open(str(path), "wb") as w:
        w.setnchannels(1)
        w.setsampwidth(2)
        w.setframerate(framerate)
        w.writeframes(bytes(frames))


def test_spectrogram_payload_is_none_when_files_are_missing(tmp_path, monkeypatch):
    monkeypatch.setattr(A, "LISTEN", tmp_path)
    assert A.spectrogram_payload("Nope") is None


def test_spectrogram_payload_is_none_for_unreadable_wav_bytes(tmp_path, monkeypatch):
    """The documented hazard: a test fixture's placeholder WAV bytes (see
    test_main_prunes_a_page_whose_pair_was_removed below) must not crash a
    build."""
    monkeypatch.setattr(A, "LISTEN", tmp_path)
    (tmp_path / "X.original.wav").write_bytes(b"RIFF....WAVEfmt ")
    (tmp_path / "X.h2g.wav").write_bytes(b"RIFF....WAVEfmt ")
    assert A.spectrogram_payload("X") is None


def test_spectrogram_payload_returns_fixed_size_grids_for_a_real_pair(tmp_path, monkeypatch):
    monkeypatch.setattr(A, "LISTEN", tmp_path)
    _write_test_wav(tmp_path / "X.original.wav", freq=440.0)
    _write_test_wav(tmp_path / "X.h2g.wav", freq=880.0)
    spec = A.spectrogram_payload("X")
    assert spec is not None
    assert spec["cols"] == A.SPEC_COLS
    assert spec["bins"] == A.SPEC_BINS
    got_a = base64.b64decode(spec["a"])
    got_b = base64.b64decode(spec["b"])
    assert len(got_a) == A.SPEC_COLS * A.SPEC_BINS
    assert len(got_b) == A.SPEC_COLS * A.SPEC_BINS
    assert all(0 <= v <= 255 for v in got_a)


def test_spectrogram_card_is_empty_with_no_spectrogram():
    assert A.spectrogram_card(None) == ""
    assert A.spectrogram_card({}) == ""


def test_spectrogram_card_names_the_range_it_drew():
    spec = {"cols": 480, "bins": 64, "fmin": 40.0, "fmax": 12000.0, "a": "", "b": ""}
    got = A.spectrogram_card(spec)
    assert '<canvas id="spectro">' in got
    assert "480 time slices" in got
    assert _balanced('<div class="wrap">%s</div>' % got) == []


def test_the_page_embeds_null_spectrogram_when_none_is_staged(tmp_path, monkeypatch):
    """Every existing call to page() in this file stages no WAVs -- the new
    embed must default to null rather than change what those pages say.

    LISTEN is monkeypatched to an EMPTY directory rather than left alone: the
    real build/listen is a hazard path that may hold 83 staged pairs, and
    "W_A_R" is one of them. Without this the test asserts the opposite of the
    truth on any tree where a human has staged listening material -- it passed
    in the worktree that wrote it (no build/) and failed on master (83 pairs).
    A test whose result depends on the developer's staging is not a test.
    """
    monkeypatch.setattr(A, "LISTEN", tmp_path)
    got = A.page("W_A_R", ROW, [], "v1", embed=False, index_link=False)
    assert "window.__abSpectrogram = null;" in got
    assert "<canvas id=\"spectro\">" not in got


def test_the_page_embeds_the_spectrogram_when_a_pair_is_staged(tmp_path, monkeypatch):
    monkeypatch.setattr(A, "LISTEN", tmp_path)
    _write_test_wav(tmp_path / "X.original.wav", freq=440.0)
    _write_test_wav(tmp_path / "X.h2g.wav", freq=880.0)
    got = A.page("X", ROW, [], "v1", embed=False, index_link=False)
    assert '<canvas id="spectro">' in got
    assert "window.__abSpectrogram = {" in got
    assert _balanced(got) == []


def test_main_prunes_a_page_whose_pair_was_removed(tmp_path, monkeypatch):
    """End to end: build once with two tunes staged, remove one pair, build
    again -- the DoD clause verbatim. No page and no index entry should
    survive for the removed tune, and the still-staged tune's page and WAVs
    must be untouched."""
    monkeypatch.setattr(A, "LISTEN", tmp_path)
    monkeypatch.setattr(A, "ROOT", tmp_path.parent)
    for stem in ("Kept", "Gone"):
        (tmp_path / ("%s.original.wav" % stem)).write_bytes(b"RIFF....WAVEfmt ")
        (tmp_path / ("%s.h2g.wav" % stem)).write_bytes(b"RIFF....WAVEfmt ")
    monkeypatch.setattr(sys, "argv", ["abpage.py"])
    assert A.main() == 0
    assert (tmp_path / "Gone.html").exists()

    # The pair is removed, as a human deleting a staged tune would do -- the
    # page is what a rebuild must retire, never the WAVs themselves.
    (tmp_path / "Gone.original.wav").unlink()
    (tmp_path / "Gone.h2g.wav").unlink()
    assert A.main() == 0

    assert not (tmp_path / "Gone.html").exists()
    assert (tmp_path / "Kept.html").exists()
    index_html = (tmp_path / "index.html").read_text(encoding="utf-8")
    assert "Gone" not in index_html
    assert "Kept" in index_html


# --- the staged audio's provenance -------------------------------------------
#
# A page shows numbers, envelopes, a spectrogram and a human verdict about the
# conversion -- and plays a WAV that was rendered at some earlier moment. When
# the converter has moved since that render, every one of those describes
# something the tool no longer emits, and nothing on the page used to say so.
#
# The guard keys on the sha256 of the `.sng` `listen.py` staged beside the WAV,
# because that file IS what the audio was made from. It must never key on
# `__version__` or a commit id: the version moves on every commit, including
# the ones that touch only abpage.py and cannot alter a byte of audio, so a
# version-keyed guard would mark every page behind on a schedule nobody chose.
# That mistake was made once on the approval badge in this repo and undone.

BANNER = '<div class="staleaudio">'   # the CSS names the class too; match the element

SNG_OLD = b"GTS5" + b"\x01" * 200
SNG_NEW = b"GTS5" + b"\x02" * 200


def _sha(b):
    import hashlib
    return hashlib.sha256(b).hexdigest()


def _stage(dirpath, stem, sng=SNG_OLD):
    (dirpath / ("%s.original.wav" % stem)).write_bytes(b"RIFF....WAVEfmt ")
    (dirpath / ("%s.h2g.wav" % stem)).write_bytes(b"RIFF....WAVEfmt ")
    if sng is not None:
        (dirpath / ("%s.h2g.sng" % stem)).write_bytes(sng)


def test_audio_provenance_is_current_when_the_staged_sng_is_todays(tmp_path, monkeypatch):
    monkeypatch.setattr(A, "LISTEN", tmp_path)
    _stage(tmp_path, "Tune", SNG_OLD)
    assert A.audio_provenance("Tune", {"Tune": _sha(SNG_OLD)})[0] == "current"


def test_audio_provenance_is_behind_when_the_converter_has_moved(tmp_path, monkeypatch):
    monkeypatch.setattr(A, "LISTEN", tmp_path)
    _stage(tmp_path, "Tune", SNG_OLD)
    state, was, now = A.audio_provenance("Tune", {"Tune": _sha(SNG_NEW)})
    assert state == "behind"
    assert (was, now) == (_sha(SNG_OLD), _sha(SNG_NEW))


def test_audio_provenance_with_no_staged_sng_is_unknown_not_behind(tmp_path, monkeypatch):
    """Absence of evidence, printed as silence. A pair staged by a tool that
    kept no `.sng` cannot be judged, and guessing `behind` would put a warning
    on a page nobody can act on."""
    monkeypatch.setattr(A, "LISTEN", tmp_path)
    _stage(tmp_path, "Tune", sng=None)
    assert A.audio_provenance("Tune", {"Tune": _sha(SNG_NEW)})[0] == "unknown"


def test_audio_provenance_with_no_conversion_sha_is_unknown(tmp_path, monkeypatch):
    """`conversion_shas()` skips a tune that is not in presets.json, whose
    `.sid` is not on disk, or that raises. None of those is staleness."""
    monkeypatch.setattr(A, "LISTEN", tmp_path)
    _stage(tmp_path, "Tune", SNG_OLD)
    assert A.audio_provenance("Tune", {})[0] == "unknown"
    assert A.audio_provenance("Tune", None)[0] == "unknown"


def test_the_banner_appears_only_when_the_audio_is_behind(tmp_path, monkeypatch):
    monkeypatch.setattr(A, "LISTEN", tmp_path)
    _stage(tmp_path, "Tune", SNG_OLD)
    assert A.audio_banner("Tune", {"Tune": _sha(SNG_OLD)}) == ""
    assert A.audio_banner("Tune", {}) == ""
    stale = A.audio_banner("Tune", {"Tune": _sha(SNG_NEW)})
    assert "older conversion" in stale
    assert _sha(SNG_OLD)[:12] in stale and _sha(SNG_NEW)[:12] in stale
    assert _balanced(stale) == []


def test_the_page_carries_the_banner_when_its_audio_is_behind(tmp_path, monkeypatch):
    """The DoD clause: a page whose staged `.h2g.wav` came from a `.sng` that
    no longer matches today's conversion says so on its face.

    STRENGTHENED, not relaxed: by default such a page now WITHHOLDS the render
    as well as labelling it, so the default banner is the withheld one. The
    original wording is still what a reader sees under `--allow-stale-audio`,
    where the audio really is served and "older conversion" is the accurate
    thing to say -- so both are asserted rather than one being swapped for the
    other.
    """
    monkeypatch.setattr(A, "LISTEN", tmp_path)
    _stage(tmp_path, "Tune", SNG_OLD)
    got = A.page("Tune", ROW, [], "v0.5.373", embed=False, index_link=True,
                 now_shas={"Tune": _sha(SNG_NEW)})
    assert BANNER in got
    assert "WITHHELD from this page" in got
    assert _balanced(got) == []

    served = A.page("Tune", ROW, [], "v0.5.373", embed=False, index_link=True,
                    now_shas={"Tune": _sha(SNG_NEW)}, allow_stale=True)
    assert BANNER in served
    assert "older conversion" in served
    assert _balanced(served) == []


def test_the_page_is_silent_when_its_audio_is_the_current_conversion(tmp_path, monkeypatch):
    """The matching case. A page that is up to date carries no badge saying so
    -- a banner on every page is a banner nobody reads."""
    monkeypatch.setattr(A, "LISTEN", tmp_path)
    _stage(tmp_path, "Tune", SNG_OLD)
    got = A.page("Tune", ROW, [], "v0.5.373", embed=False, index_link=True,
                 now_shas={"Tune": _sha(SNG_OLD)})
    assert BANNER not in got
    assert _balanced(got) == []


def test_the_banner_does_not_key_on_the_version(tmp_path, monkeypatch):
    """The judgement this guard exists to get right. Same staged `.sng`, same
    conversion, four different version strings -- and no page may claim its
    audio is behind, because the version moving is not the thing that would
    make the claim true. v0.5.370, v0.5.371 and v0.5.373 each touched only
    abpage.py, which cannot alter a byte of audio."""
    monkeypatch.setattr(A, "LISTEN", tmp_path)
    _stage(tmp_path, "Tune", SNG_OLD)
    shas = {"Tune": _sha(SNG_OLD)}
    for version in ("v0.5.369", "v0.5.370", "v0.5.371", "v0.9.999"):
        got = A.page("Tune", ROW, [], version, embed=False, index_link=True,
                     now_shas=shas)
        assert BANNER not in got, version


def test_a_valid_approval_does_not_silence_the_banner(tmp_path, monkeypatch):
    """The live ACE_II case, reduced. The approval records the sha
    `conversion_shas()` gave when the verdict was written, so it can match
    today's conversion exactly while the WAV on the page came from a `.sng`
    staged earlier. Both statements belong on the page: the verdict still
    holds, and it is not what you are hearing."""
    monkeypatch.setattr(A, "LISTEN", tmp_path)
    _stage(tmp_path, "Tune", SNG_OLD)
    appr = {"Tune": {"approved": True, "sng_sha256": _sha(SNG_NEW),
                     "version": "0.5.369", "at": "2026-08-23"}}
    got = A.page("Tune", ROW, [], "v0.5.373", embed=False, index_link=True,
                 approval=appr, now_shas={"Tune": _sha(SNG_NEW)})
    assert "Human approved" in got
    assert BANNER in got
    assert _balanced(got) == []


def test_the_index_names_which_tunes_play_an_older_conversion(tmp_path, monkeypatch):
    monkeypatch.setattr(A, "LISTEN", tmp_path)
    _stage(tmp_path, "Old", SNG_OLD)
    _stage(tmp_path, "New", SNG_NEW)
    _stage(tmp_path, "Unknown", sng=None)
    got = A.index(["Old", "New", "Unknown"], {}, "v0.5.373", {},
                  {"Old": _sha(SNG_NEW), "New": _sha(SNG_NEW),
                   "Unknown": _sha(SNG_NEW)})
    rows = {n: got.split('%s.html">' % n)[1].split("</tr>")[0]
            for n in ("Old", "New", "Unknown")}
    assert "behind" in rows["Old"]
    assert "current" in rows["New"] and "behind" not in rows["New"]
    assert "behind" not in rows["Unknown"]
    assert _balanced(got) == []


# --- build atomicity: an interrupted build must not go undetected ----------
#
# abpage-page-build-is-not-atomic. A killed build used to leave some pages
# rewritten by the new run and some (and index.html, written last) still
# from the old one -- a page could say "current" while index.html, reading
# from a different build entirely, still called it "behind". Nothing on disk
# recorded which run a page belonged to, so nothing could tell the two apart
# after the fact; it was found once, by hand.
#
# The fix stamps every page and index.html with one id per call to the build
# loop in `main()` (`_new_build_id`/`_stamp`), so `check_build_consistency`
# can say, after the fact, which on-disk pages were not part of the same
# build as the index that links them.

def test_atomic_write_replaces_the_file_and_leaves_no_temp_behind(tmp_path):
    target = tmp_path / "page.html"
    target.write_text("old", encoding="utf-8")
    A._atomic_write(target, "new content")
    assert target.read_text(encoding="utf-8") == "new content"
    assert list(tmp_path.glob("*.tmp-*")) == []


def test_stamp_and_build_id_of_round_trip(tmp_path):
    p = tmp_path / "x.html"
    p.write_text(A._stamp("deadbeef1234", "<html><body>hi</body></html>"),
                 encoding="utf-8")
    assert A._build_id_of(p) == "deadbeef1234"


def test_build_id_of_a_file_with_no_stamp_is_unknown(tmp_path):
    p = tmp_path / "x.html"
    p.write_text("<html><body>no stamp here</body></html>", encoding="utf-8")
    assert A._build_id_of(p) is None


def test_build_id_of_a_missing_file_is_unknown(tmp_path):
    assert A._build_id_of(tmp_path / "nope.html") is None


def test_check_build_consistency_is_empty_with_no_index(tmp_path, monkeypatch):
    monkeypatch.setattr(A, "LISTEN", tmp_path)
    assert A.check_build_consistency(["Tune"]) == []


def test_check_build_consistency_is_empty_when_every_page_agrees(tmp_path, monkeypatch):
    monkeypatch.setattr(A, "LISTEN", tmp_path)
    (tmp_path / "index.html").write_text(A._stamp("abc123", "<html></html>"),
                                          encoding="utf-8")
    (tmp_path / "Tune.html").write_text(A._stamp("abc123", "<html></html>"),
                                        encoding="utf-8")
    assert A.check_build_consistency(["Tune"]) == []


def test_check_build_consistency_names_the_page_that_disagrees(tmp_path, monkeypatch):
    """The exact reported shape: index.html from one build, a page left over
    from an earlier one."""
    monkeypatch.setattr(A, "LISTEN", tmp_path)
    (tmp_path / "index.html").write_text(A._stamp("aaa111", "<html></html>"),
                                          encoding="utf-8")
    (tmp_path / "Fresh.html").write_text(A._stamp("aaa111", "<html></html>"),
                                         encoding="utf-8")
    (tmp_path / "Stale.html").write_text(A._stamp("aaa000", "<html></html>"),
                                         encoding="utf-8")
    assert A.check_build_consistency(["Fresh", "Stale"]) == ["Stale"]


def test_check_build_consistency_treats_an_untagged_page_as_unknown_not_stale(
        tmp_path, monkeypatch):
    """A page from before this stamp existed must not be flagged -- absence
    of evidence is not evidence of disagreement, the same fallback shape
    `audio_provenance`'s "unknown" state uses."""
    monkeypatch.setattr(A, "LISTEN", tmp_path)
    (tmp_path / "index.html").write_text(A._stamp("aaa111", "<html></html>"),
                                          encoding="utf-8")
    (tmp_path / "Legacy.html").write_text("<html>no stamp</html>",
                                          encoding="utf-8")
    assert A.check_build_consistency(["Legacy"]) == []


def _stage_pair(dirpath, stem):
    (dirpath / ("%s.original.wav" % stem)).write_bytes(b"RIFF....WAVEfmt ")
    (dirpath / ("%s.h2g.wav" % stem)).write_bytes(b"RIFF....WAVEfmt ")


def test_an_interrupted_build_is_caught_and_reported_on_the_next_run(
        tmp_path, monkeypatch, capsys):
    """OBSERVED shape, reproduced: kill `main()` after it has rewritten one
    page but before it reaches the rest (and index.html, written last).
    `check_build_consistency` must name exactly the page that changed, and
    the NEXT `main()` invocation must print that finding rather than stay
    silent about it -- the two halves of `abpage-page-build-is-not-atomic`.
    """
    monkeypatch.setattr(A, "LISTEN", tmp_path)
    monkeypatch.setattr(A, "ROOT", tmp_path.parent)
    for stem in ("Alpha", "Beta"):
        _stage_pair(tmp_path, stem)
    monkeypatch.setattr(sys, "argv", ["abpage.py"])

    assert A.main() == 0
    capsys.readouterr()

    good_id = A._build_id_of(tmp_path / "index.html")
    assert good_id
    assert A._build_id_of(tmp_path / "Alpha.html") == good_id
    assert A._build_id_of(tmp_path / "Beta.html") == good_id

    # Simulate the kill: let exactly one page's write through, then blow up
    # before the next one -- the write loop is the only place a kill CAN
    # land mid-build now, since every page is fully rendered in memory
    # first.
    real_write = A._atomic_write
    written = []

    def _flaky(path, text):
        if written:
            raise KeyboardInterrupt("simulated kill")
        written.append(path)
        real_write(path, text)

    monkeypatch.setattr(A, "_atomic_write", _flaky)
    with pytest.raises(KeyboardInterrupt):
        A.main()
    capsys.readouterr()

    assert len(written) == 1
    updated = written[0].stem
    stale = "Beta" if updated == "Alpha" else "Alpha"

    # The page that got through carries a NEW id; the other one, and
    # index.html (never reached), still carry the old one.
    assert A._build_id_of(tmp_path / ("%s.html" % updated)) != good_id
    assert A._build_id_of(tmp_path / ("%s.html" % stale)) == good_id
    assert A._build_id_of(tmp_path / "index.html") == good_id

    # This is the exact bug: the tool reported nothing on its own.
    assert A.check_build_consistency(["Alpha", "Beta"]) == [updated]

    # A plain rerun must SAY so, not silently paper over it.
    monkeypatch.setattr(A, "_atomic_write", real_write)
    assert A.main() == 0
    out, _ = capsys.readouterr()
    assert "left over from a build that did not finish" in out
    assert updated in out

    # ...and, having rebuilt, the inconsistency is gone.
    assert A.check_build_consistency(["Alpha", "Beta"]) == []


# --- run_instrmap: say what got cached, and reuse it -----------------------
#
# instrmap-rebuild-should-say-what-it-cached, folded in here. The expensive
# half of `--instrmap` (two emulations a song) had already written
# build/instrmap.json by the time a kill hit the observed run; retrying the
# same command blindly re-traced everything, paying for it again. A retry
# with nothing else changed must reuse what is already on disk instead.

class _FakeResult:
    def __init__(self, returncode=0, stdout="", stderr=""):
        self.returncode = returncode
        self.stdout = stdout
        self.stderr = stderr


def _touch(path, when):
    path.write_bytes(path.read_bytes() if path.exists() else b"")
    os.utime(path, (when, when))


def test_run_instrmap_skips_the_trace_when_the_cache_already_covers_everything(
        tmp_path, monkeypatch):
    monkeypatch.setattr(A, "ROOT", tmp_path)
    monkeypatch.setattr(A, "LISTEN", tmp_path / "build" / "listen")
    A.LISTEN.mkdir(parents=True)
    sid_dir = tmp_path / "sids"
    sid_dir.mkdir()
    for stem in ("Alpha", "Beta"):
        (sid_dir / ("%s.sid" % stem)).write_bytes(b"PSID")
    build = tmp_path / "build"
    jpath = build / "instrmap.json"
    jpath.write_text('{"seconds": 60, "songs": [{"file": "Alpha.sid"}, '
                     '{"file": "Beta.sid"}]}', encoding="utf-8")
    (build / "instrmap").mkdir(parents=True, exist_ok=True)
    (build / "instrmap" / "Alpha.html").write_text("<html>report</html>",
                                                     encoding="utf-8")

    now = time.time()
    _touch(sid_dir / "Alpha.sid", now - 100)
    _touch(sid_dir / "Beta.sid", now - 100)
    os.utime(jpath, (now, now))          # the cache is NEWER than every .sid

    def _boom(*a, **k):
        raise AssertionError("subprocess.run must not be called on a fresh cache")
    monkeypatch.setattr("subprocess.run", _boom)

    rc = A.run_instrmap(str(sid_dir), ["Alpha", "Beta"])
    assert rc == 0
    # The HTML report copy still runs on the skip path -- a page must not
    # lose its instrument-map card just because the trace was skipped.
    assert (A.LISTEN / "Alpha.instrmap.html").exists()


def test_run_instrmap_retraces_when_a_sid_postdates_the_cache(tmp_path, monkeypatch):
    monkeypatch.setattr(A, "ROOT", tmp_path)
    monkeypatch.setattr(A, "LISTEN", tmp_path / "build" / "listen")
    A.LISTEN.mkdir(parents=True)
    sid_dir = tmp_path / "sids"
    sid_dir.mkdir()
    (sid_dir / "Alpha.sid").write_bytes(b"PSID")
    build = tmp_path / "build"
    jpath = build / "instrmap.json"
    jpath.write_text('{"seconds": 60, "songs": [{"file": "Alpha.sid"}]}',
                     encoding="utf-8")
    now = time.time()
    os.utime(jpath, (now - 100, now - 100))   # the cache is OLDER than the .sid
    _touch(sid_dir / "Alpha.sid", now)

    calls = []

    def _fake_run(cmd, capture_output, text):
        calls.append(cmd)
        jpath.write_text('{"seconds": 60, "songs": [{"file": "Alpha.sid"}]}',
                         encoding="utf-8")
        return _FakeResult(returncode=0)

    monkeypatch.setattr("subprocess.run", _fake_run)
    rc = A.run_instrmap(str(sid_dir), ["Alpha"])
    assert rc == 0
    assert len(calls) == 1


def test_run_instrmap_force_bypasses_a_fresh_cache(tmp_path, monkeypatch):
    monkeypatch.setattr(A, "ROOT", tmp_path)
    monkeypatch.setattr(A, "LISTEN", tmp_path / "build" / "listen")
    A.LISTEN.mkdir(parents=True)
    sid_dir = tmp_path / "sids"
    sid_dir.mkdir()
    (sid_dir / "Alpha.sid").write_bytes(b"PSID")
    build = tmp_path / "build"
    jpath = build / "instrmap.json"
    jpath.write_text('{"seconds": 60, "songs": [{"file": "Alpha.sid"}]}',
                     encoding="utf-8")
    now = time.time()
    _touch(sid_dir / "Alpha.sid", now - 100)
    os.utime(jpath, (now, now))          # fresh by mtime alone

    calls = []

    def _fake_run(cmd, capture_output, text):
        calls.append(cmd)
        jpath.write_text('{"seconds": 60, "songs": [{"file": "Alpha.sid"}]}',
                         encoding="utf-8")
        return _FakeResult(returncode=0)

    monkeypatch.setattr("subprocess.run", _fake_run)
    rc = A.run_instrmap(str(sid_dir), ["Alpha"], force=True)
    assert rc == 0
    assert len(calls) == 1


# --- the pattern view shows the instrument that SOUNDS -----------------------
#
# Goattracker reads 00 in a pattern's instrument column as "keep the current
# instrument", not "no instrument". Showing the literal byte made a reader of
# 5 Title Tunes conclude the instruments were missing -- 43% of that file's
# note rows on channels 1 and 2 inherit rather than set. `row_schedule` now
# carries the last non-zero forward as `eff` (index 7) and flags the row as
# inherited (index 8), so the view can show what sounds while still saying the
# row is not where it was set.

def _sched_rows(tmp_path, monkeypatch):
    import pathlib as _pl
    sng = _pl.Path(A.__file__).resolve().parent.parent / "build" / "listen" / "5_Title_Tunes.h2g.sng"
    if not sng.exists():
        pytest.skip("build/listen/5_Title_Tunes.h2g.sng not staged")
    return A.row_schedule(sng, 0, 1, 3000)


def test_a_note_row_never_reports_instrument_zero(tmp_path, monkeypatch):
    sched = _sched_rows(tmp_path, monkeypatch)
    for v, rows in enumerate(sched["voices"]):
        notes = [r for r in rows if r[1] not in ("...", "===")]
        assert notes, v
        assert all(r[7] for r in notes), (
            "voice %d has a note row whose effective instrument is 0" % v)


def test_an_inherited_row_is_flagged_and_keeps_its_literal_byte(tmp_path, monkeypatch):
    sched = _sched_rows(tmp_path, monkeypatch)
    inherited = [r for rows in sched["voices"] for r in rows
                 if r[1] not in ("...", "===") and r[8]]
    assert inherited, "expected some inherited note rows on this file"
    for r in inherited:
        assert r[2] == 0          # the literal pattern byte is still 00
        assert r[7] != 0          # and the effective instrument is real


def test_a_row_that_sets_an_instrument_is_not_flagged(tmp_path, monkeypatch):
    sched = _sched_rows(tmp_path, monkeypatch)
    setters = [r for rows in sched["voices"] for r in rows
               if r[1] not in ("...", "===") and r[2]]
    assert setters
    for r in setters:
        assert r[8] == 0
        assert r[7] == r[2]

def test_a_stale_h2g_render_is_withheld_not_merely_labelled(monkeypatch):
    """A warning that can be clicked past is not a guard.

    `audio_provenance` has flagged "behind" for many versions and the page went
    on serving the audio anyway, which is how a listening task came to be
    pointing at a build the converter no longer produces. The H2G `<audio>`
    element must carry no `src` for such a tune, so it cannot be played at all.

    Three cases, because the interesting part is what is NOT withheld: the
    original render (a converter change cannot make it stale), and a tune whose
    own render is current (43 of the 83 staged tunes were, so an all-or-nothing
    refusal would have taken those down too).
    """
    import abpage as A

    def fake(name, shas=None):
        return ("behind" if name == "Stale_Tune" else "current", "a" * 64, "b" * 64)

    monkeypatch.setattr(A, "audio_provenance", fake)
    stale = A.page("Stale_Tune", {}, [], "v", embed=False, index_link=True,
                   now_shas={})
    fresh = A.page("Fresh_Tune", {}, [], "v", embed=False, index_link=True,
                   now_shas={})
    allowed = A.page("Stale_Tune", {}, [], "v", embed=False, index_link=True,
                     now_shas={}, allow_stale=True)

    assert 'id="bu" preload="auto" src=' not in stale, (
        "a stale H2G render is still playable")
    assert "WITHHELD from this page" in stale, (
        "the page does not say the render was withheld")
    assert 'id="au" preload="auto" src=' in stale, (
        "the ORIGINAL render must keep playing -- a converter change cannot "
        "make it stale, and the page stays useful for what the tune should "
        "sound like")

    assert 'id="bu" preload="auto" src=' in fresh, (
        "a current render must not be withheld")
    assert "WITHHELD from this page" not in fresh

    assert 'id="bu" preload="auto" src=' in allowed, (
        "--allow-stale-audio no longer restores the older render")
    assert "WITHHELD from this page" not in allowed

def test_sidid_is_abbreviated_by_rule_not_by_a_lookup_of_todays_values():
    """A ninth value must degrade to its own text, never to a blank.

    The corpus carries eight SIDId strings today. Abbreviating by table alone
    would render a file bringing a ninth as nothing at all, which in a column
    of player names reads as "not identified" -- the opposite of the truth.
    """
    assert A.abbrev_sidid("Rob_Hubbard") == "RH"
    assert A.abbrev_sidid("Rob_Hubbard, (Rob_Hubbard_Digi)") == "RH+digi"
    assert A.abbrev_sidid("Rob_Hubbard, Voicemaster_Covox") == "RH+Covox"
    assert A.abbrev_sidid("Companion, Rob_Hubbard") == "Companion+RH"
    # unknown: kept verbatim rather than dropped
    assert A.abbrev_sidid("Brand_New_Player_9000") == "Brand_New_Player_9000"
    assert A.abbrev_sidid("Rob_Hubbard, Nine_Thousand") == "RH+Nine_Thousand"
    # SIDId's own "nothing matched" marker, and a missing row, both read as a
    # dash rather than as the word "none" among player names.
    assert A.abbrev_sidid("(none)") == "&mdash;"
    assert A.abbrev_sidid("") == "&mdash;"


def test_the_index_carries_an_abbreviated_sidid_with_the_full_text_on_hover():
    """Abbreviating is only acceptable because nothing is lost by it."""
    rows = {"Tune": {"melody": "100%"}}
    survey = {"Tune": {"SIDId": "Rob_Hubbard, (Rob_Hubbard_Digi)"}}
    got = A.index(["Tune"], rows, "v", survey=survey)
    assert "<th>SIDId</th>" in got
    assert '>RH+digi<' in got
    assert 'title="Rob_Hubbard, (Rob_Hubbard_Digi)"' in got, (
        "the long form must remain one hover away")
    # a tune with no survey row must not claim an identification
    bare = A.index(["Tune"], rows, "v", survey={})
    assert "not surveyed" in bare
    assert _balanced(got) == []


APPR = {"Tune": {"approved": True, "sng_sha256": "aaa", "version": "0.5.400", "at": "2026-08-20"}}


def test_badge_is_inherited_when_the_build_inherits():
    rec = {"Tune": {"status": "inherited", "approved_sha": "aaa", "current_sha": "bbb",
                    "since": "0.5.447", "builds_inherited": 2, "failed": [],
                    "listener_should_check": "aud_vs_approved", "evidence": {}}}
    html = A.approval_badge("Tune", APPR, "0.5.448", {"Tune": "bbb"}, inherited=rec)
    assert 'class="approval inherited"' in html
    assert "since 0.5.447" in html and "2 build" in html


def test_badge_is_stale_and_names_what_to_listen_for():
    rec = {"Tune": {"status": "stale", "approved_sha": "aaa", "current_sha": "bbb",
                    "since": "0.5.447", "builds_inherited": 0,
                    "failed": ["aud_vs_approved"], "listener_should_check": "aud_vs_approved",
                    "evidence": {}}}
    html = A.approval_badge("Tune", APPR, "0.5.448", {"Tune": "bbb"}, inherited=rec)
    assert 'class="approval stale"' in html
    assert "aud_vs_approved" in html


def test_badge_falls_back_to_the_sha_rule_without_an_assessment():
    """No build/approvals.json, or a tune it does not cover: the old two
    states, unchanged."""
    html = A.approval_badge("Tune", APPR, "0.5.448", {"Tune": "bbb"}, inherited={})
    assert 'class="approval stale"' in html
    html = A.approval_badge("Tune", APPR, "0.5.448", {"Tune": "aaa"}, inherited={})
    assert 'class="approval yes"' in html


def test_index_shows_three_states():
    rec = {"Tune": {"status": "inherited", "approved_sha": "aaa", "current_sha": "bbb",
                    "since": "0.5.447", "builds_inherited": 1, "failed": [],
                    "listener_should_check": None, "evidence": {}}}
    html = A.index(["Tune"], {}, "0.5.448", APPR, {"Tune": "bbb"}, inherited=rec)
    assert 'class="i">inherited' in html
