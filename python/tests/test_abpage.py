"""`abpage.py`: the A/B listening pages built from what listen.py staged.

The page itself cannot be tested here — whether two `<audio>` elements really
stay in sync is a browser question. What is testable is everything that decides
*what the page says*: the two parsers that read `FIDELITY.md` and
`LISTENING.md`, and the guarantee that a page quotes them rather than restating
them. A page disagreeing with the report it cites would be the failure mode
worth catching, since a listener would then be told the wrong thing to listen
for.
"""
import html.parser
import sys
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
