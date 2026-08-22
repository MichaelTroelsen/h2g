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
import struct
import sys
import wave
from pathlib import Path

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
