"""Does the rendered approval column agree with build/approvals.json per tune?

Read-only. Cross-checks the two artefacts against each other rather than
against what anyone remembers rendering, and REFUSES a vacuous answer in two
distinct ways:

  1. the index carries no verdict spans at all -- a "0 disagreements" result
     would look exactly like a pass over real data.
  2. every rendered span agrees, but zero of them are `inherited` -- the
     inherited-status branch of EXPECT was never exercised, which is exactly
     the state this checker exists to catch (see the task that opened this
     one: calibration for `inherited` has never been observed on this
     corpus). This is not refused -- both `exact`/`stale`-only agreement and
     agreement-with-inheritance are legitimate passes -- but the two are
     printed as DIFFERENT verdicts so a reader (or a CI gate) cannot mistake
     "never exercised the interesting branch" for "exercised and agreed".

Moved here from a scratch prototype at
C:/t/check-column-passes-with-zer/check_column_patched.py (itself built on
the original at C:/t/abpage-render-check/check_column.py) per the task
check-column-passes-with-zero-inherited-spans-which-is-the-state-it-exists-to-detect.
"""
from __future__ import annotations

import argparse
import json
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent

CLASS = {"y": "approved", "i": "inherited", "s": "stale"}
# status -> the column value it must produce. `uncalibrated` cannot inherit,
# so it falls through to the sha rule, i.e. stale when the sha moved.
EXPECT = {"exact": "approved", "inherited": "inherited", "stale": "stale",
          "uncalibrated": "stale"}


def parse_index(html: str) -> dict[str, str]:
    """tune stem -> rendered column value, read from the verdict spans."""
    found: dict[str, str] = {}
    for m in re.finditer(r'<span class="([yis])">([a-z]+)</span>', html):
        before = html[:m.start()]
        names = re.findall(r'href="([A-Za-z0-9_\-.]+)\.html"', before)
        assert names, "a verdict span with no tune link before it"
        found[names[-1]] = CLASS[m.group(1)]
    return found


def check(html: str, approvals_doc: dict) -> dict:
    """Cross-check the rendered index against approvals.json. Read-only,
    raises nothing itself except the vacuous-input refusal; disagreements are
    collected into the result for `verdict` to raise on."""
    tunes = approvals_doc.get("tunes", approvals_doc)
    found = parse_index(html)
    assert found, "REFUSING: the index carries NO verdict spans -- vacuous"

    rows, bad = [], []
    for stem, rec in tunes.items():
        st = rec.get("status")
        assert st in EXPECT, "unmapped status %r for %s" % (st, stem)
        want = EXPECT[st]
        got = found.get(stem)
        rows.append((stem, st, want, got))
        if got != want:
            bad.append((stem, st, want, got))

    missing = set(tunes) - set(found)
    extra = set(found) - set(tunes)
    # The inherited count is read from approvals.json -- the source of
    # truth -- not from the rendered spans: a span can only read "inherited"
    # because some tune's status already was, so counting the status answers
    # whether EXPECT["inherited"] was ever exercised, not just whether the
    # rendering happens to agree.
    inherited_statuses = sum(1 for rec in tunes.values() if rec.get("status") == "inherited")
    inherited_spans = sum(1 for v in found.values() if v == "inherited")

    return {"found": found, "tunes": tunes, "rows": rows, "bad": bad,
             "missing": missing, "extra": extra,
             "inherited_statuses": inherited_statuses,
             "inherited_spans": inherited_spans}


def report(result: dict) -> str:
    lines = ["verdict spans in the index: %d" % len(result["found"]),
             "tunes in approvals.json:    %d" % len(result["tunes"])]
    for stem, st, want, got in result["rows"]:
        flag = "OK " if got == want else "BAD"
        lines.append("  %s %-16s status=%-13s expect=%-9s column=%s"
                      % (flag, stem, st, want, got))
    lines.append("")
    lines.append("in approvals.json but not rendered: %s" % (sorted(result["missing"]) or "none"))
    lines.append("rendered but not in approvals.json: %s" % (sorted(result["extra"]) or "none"))
    lines.append("")
    lines.append("inherited spans rendered: %d" % result["inherited_spans"])
    lines.append("tunes with status=inherited in approvals.json: %d" % result["inherited_statuses"])
    lines.append("DISAGREEMENTS: %d" % len(result["bad"]))
    return "\n".join(lines)


def verdict(result: dict) -> str:
    """The final PASS line -- distinguishing 'agrees, inheritance observed'
    from 'agrees, inheritance never happened'. Raises AssertionError on any
    disagreement or missing tune, exactly as the original did."""
    assert not result["bad"] and not result["missing"], result["bad"] or result["missing"]
    if result["inherited_statuses"] == 0:
        return ("PASS -- agrees for every tune, but INHERITANCE WAS NEVER OBSERVED "
                 "(0/%d tunes have status=inherited): this run exercises the "
                 "approved/stale branches only, not the inherited branch"
                 % len(result["tunes"]))
    return ("PASS -- the column agrees with the assessment for every tune "
             "(%d tunes with status=inherited observed)" % result["inherited_statuses"])


def main(argv=None) -> int:
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--index", default=str(ROOT / "build" / "listen" / "index.html"))
    p.add_argument("--approvals", default=str(ROOT / "build" / "approvals.json"))
    args = p.parse_args(argv)

    html = Path(args.index).read_text(encoding="utf-8")
    doc = json.loads(Path(args.approvals).read_text(encoding="utf-8"))
    result = check(html, doc)
    print(report(result))
    print()
    print(verdict(result))
    return 0


if __name__ == "__main__":
    sys.exit(main())
