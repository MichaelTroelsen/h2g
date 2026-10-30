"""render_check: CONSOLE-line parsing, selector test, and a live probe page."""
from __future__ import annotations

import sys
import tempfile
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
import render_check as R  # noqa: E402

SAMPLE = (
    '[309820:264780:1030/190138.640:INFO:CONSOLE:1] "probe one", source: file:///p.html (1)\n'
    '[309820:264780:1030/190138.640:INFO:CONSOLE:1] "Uncaught ReferenceError: x is not defined", source: file:///p.html (1)\n'
    '[309820:264780:1030/190138.700:ERROR:gpu_process.cc:1] unrelated noise\n'
)


def test_parse_counts_console_lines_only():
    got = R.parse_console(SAMPLE)
    assert len(got) == 2, got
    assert got[0].startswith('"probe one"')
    assert "ReferenceError" in got[1]


def test_parse_clean_stderr_is_empty():
    assert R.parse_console("[1:2:3:ERROR:other.cc:1] nothing\n") == []


def test_parse_newer_chrome_format():
    assert len(R.parse_console('[1:2:3:INFO:CONSOLE(7)] "m", source: u (7)\n')) == 1


def test_selectors():
    dom = '<html><table class="a worst"><tr></tr></table><div id="k"></div>'
    assert R.has_selector(dom, "table.worst")
    assert not R.has_selector(dom, "div.worst")
    assert R.has_selector(dom, "#k")
    assert not R.has_selector(dom, "table.wors")


@pytest.mark.skipif(R.find_chrome() is None, reason="Chrome not installed")
def test_probe_page_reports_exactly_two():
    with tempfile.TemporaryDirectory() as d:
        p = Path(d) / "probe.html"
        p.write_text('<!doctype html><table class="worst"></table><script>'
                     'console.error("one");undefinedFn();</script>', "utf-8")
        r = R.check_page(p.as_uri(), ["table.worst", "table.nope"],
                         R.find_chrome(), budget_ms=3000)
    assert len(r.console) == 2, r.console
    assert r.selectors == {"table.worst": True, "table.nope": False}
