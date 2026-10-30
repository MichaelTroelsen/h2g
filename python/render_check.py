"""Headless-Chrome render check for the A/B pages.

    python render_check.py URL_OR_FILE [...] [--select table.worst ...]
    python render_check.py --listen Commando.html [--select table.worst]

Per page: the CONSOLE lines Chrome writes to stderr and whether each named
selector is present in the dumped DOM. Chrome's stderr carries no usable
severity (console.error and an uncaught ReferenceError both print as
INFO:CONSOLE), so every CONSOLE line counts: a clean page logs nothing.
`--listen NAME` serves build/listen with its own `abpage.py --serve PORT
--no-build` on a free port and stops it afterwards. Exit 1 on any console
line or missing selector, 2 when Chrome is absent.
"""
from __future__ import annotations

import argparse
import re
import shutil
import socket
import subprocess
import sys
import tempfile
import time
from dataclasses import dataclass, field
from pathlib import Path

HERE = Path(__file__).resolve().parent
CHROME_CANDIDATES = (
    r"C:/Program Files/Google/Chrome/Application/chrome.exe",
    r"C:/Program Files (x86)/Google/Chrome/Application/chrome.exe",
)
# [pid:tid:MMDD/HHMMSS.mmm:INFO:CONSOLE:12] "message", source: URL (12)
CONSOLE_RE = re.compile(r':CONSOLE[:(]\d*\)?\]\s*(.*)')


def find_chrome() -> str | None:
    for c in CHROME_CANDIDATES:
        if Path(c).exists():
            return c
    return shutil.which("chrome") or shutil.which("google-chrome")


def parse_console(stderr: str) -> list[str]:
    """Message text of every CONSOLE line in Chrome's stderr."""
    out = []
    for line in stderr.splitlines():
        m = CONSOLE_RE.search(line)
        if m:
            out.append(m.group(1).strip())
    return out


def has_selector(dom: str, selector: str) -> bool:
    """tag.class / tag#id / .class / #id / tag against the dumped DOM."""
    m = re.fullmatch(r'([a-zA-Z][\w-]*)?(?:([.#])([\w-]+))?', selector)
    if not m:
        raise ValueError("unsupported selector %r" % selector)
    tag, kind, name = m.groups()
    for t in re.finditer(r'<([a-zA-Z][\w-]*)([^>]*)>', dom):
        if tag and t.group(1).lower() != tag.lower():
            continue
        if not kind:
            return True
        attrs = t.group(2)
        if kind == '.':
            for c in re.finditer(r'\bclass\s*=\s*"([^"]*)"', attrs):
                if name in c.group(1).split():
                    return True
        else:
            if re.search(r'\bid\s*=\s*"%s"' % re.escape(name), attrs):
                return True
    return False


@dataclass
class PageResult:
    url: str
    console: list[str] = field(default_factory=list)
    selectors: dict[str, bool] = field(default_factory=dict)
    returncode: int = 0


def check_page(url: str, selectors: list[str], chrome: str,
               budget_ms: int = 8000, timeout: float = 120.0) -> PageResult:
    ud = tempfile.mkdtemp(prefix="render-check-ud-")
    try:
        p = subprocess.run(
            [chrome, "--headless=new", "--disable-gpu", "--user-data-dir=" + ud,
             "--enable-logging=stderr", "--v=0",
             "--virtual-time-budget=%d" % budget_ms, "--dump-dom", url],
            capture_output=True, timeout=timeout)
    finally:
        shutil.rmtree(ud, ignore_errors=True)
    dom = p.stdout.decode("utf-8", "replace")
    err = p.stderr.decode("utf-8", "replace")
    return PageResult(url, parse_console(err),
                      {s: has_selector(dom, s) for s in selectors},
                      p.returncode)


def free_port() -> int:
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


class ListenServer:
    """`abpage.py --serve PORT --no-build` on a free port, for a with-block."""

    def __enter__(self) -> "ListenServer":
        self.port = free_port()
        self.proc = subprocess.Popen(
            [sys.executable, str(HERE / "abpage.py"), "--no-build",
             "--serve", str(self.port)],
            cwd=str(HERE), stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        deadline = time.time() + 60
        while time.time() < deadline:
            if self.proc.poll() is not None:
                raise RuntimeError("abpage.py --serve exited early")
            try:
                socket.create_connection(("127.0.0.1", self.port), 0.5).close()
                return self
            except OSError:
                time.sleep(0.2)
        self.proc.kill()
        raise RuntimeError("abpage.py --serve never bound port %d" % self.port)

    def __exit__(self, *exc) -> None:
        self.proc.terminate()
        try:
            self.proc.wait(10)
        except subprocess.TimeoutExpired:
            self.proc.kill()

    def url(self, name: str) -> str:
        return "http://127.0.0.1:%d/%s" % (self.port, name)


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("urls", nargs="*", help="URLs or local file paths")
    ap.add_argument("--listen", nargs="+", default=[], metavar="NAME",
                    help="pages under build/listen, served by our own server")
    ap.add_argument("--select", action="append", default=[], metavar="SEL",
                    help="selector that must be present (tag.class, #id ...)")
    ap.add_argument("--budget", type=int, default=8000, help="virtual ms")
    a = ap.parse_args(argv)
    chrome = find_chrome()
    if not chrome:
        print("chrome not found")
        return 2
    results: list[PageResult] = []

    def run(urls: list[str]) -> None:
        for u in urls:
            results.append(check_page(u, a.select, chrome, a.budget))

    run([u if "://" in u else Path(u).resolve().as_uri() for u in a.urls])
    if a.listen:
        with ListenServer() as srv:
            run([srv.url(n) for n in a.listen])
    bad = False
    for r in results:
        print("%s: %d console error(s)" % (r.url, len(r.console)))
        for c in r.console:
            print("  CONSOLE %s" % c)
        for s, ok in r.selectors.items():
            print("  %s: %s" % (s, "present" if ok else "MISSING"))
        bad |= bool(r.console) or not all(r.selectors.values())
    return 1 if bad else 0


if __name__ == "__main__":
    raise SystemExit(main())
