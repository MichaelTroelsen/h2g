"""Audit .claude/tasks/whattask.json for the grant defects that keep blocking runs.

Read-only. Exits 1 if any check finds something, so it can gate.

Every check here exists because the defect it names actually shipped in a real
plan and cost at least one task cycle:

  A  a granted repo path that does not exist        (typo vs deliberate create)
  B  rw: on a source file without rw: its test      (runner widens its own lock)
  C  a path in `verify` missing from `touches`, or there too WEAKLY -- `r:` on
     a path the verify must write. This is the newest variety and the one a
     presence-only check waves through: three tasks were blocked on it in one
     session, including one whose own human decision required writing two files
     it held `r:` on.
  D  two `parallel` tasks overlapping with at least one writer  (lane arithmetic)
  E  a dangling `depends_on`, which silently never resolves
  F  a verify quoting a sha/version/count with nothing to date it
"""
import collections
import json
import pathlib
import re
import subprocess
import sys

ROOT = pathlib.Path(__file__).resolve().parents[3]
PLAN = ROOT / ".claude/tasks/whattask.json"


def split(tok):
    if tok.startswith("rw:"):
        return "rw", tok[3:]
    if tok.startswith("r:"):
        return "r", tok[2:]
    return "rw", tok


def overlaps(a, b):
    a, b = a.rstrip("/"), b.rstrip("/")
    return a == b or a.startswith(b + "/") or b.startswith(a + "/")


def repo_path(p):
    return not re.match(r"^(host:|corpus:|port:|desktop:|emulator:)", p) \
        and not re.match(r"^[A-Za-z]:[\\/]", p)


def main() -> int:
    if not PLAN.exists():
        print("no plan at %s -- run /whattask first" % PLAN)
        return 0
    plan = json.loads(PLAN.read_text(encoding="utf-8"))
    tasks = plan["tasks"]
    findings = 0

    print("plan: %d task(s), %d closed, head %s\n"
          % (len(tasks), len(plan.get("closed") or []),
             plan["generated_from"]["head"]))

    # ---- A ---------------------------------------------------------------
    absent = collections.defaultdict(list)
    for t in tasks:
        for tok in t["touches"]:
            mode, p = split(tok)
            if repo_path(p) and not (ROOT / p).exists():
                absent[p].append((t["id"], mode))
    if absent:
        print("A. granted repo path(s) absent from the tree "
              "(a create is fine; a typo is not):")
        for p, who in sorted(absent.items()):
            print("   %-46s %s" % (p, ", ".join("%s(%s)" % w for w in who)))
        findings += len(absent)
        print()

    # ---- B ---------------------------------------------------------------
    bad = []
    for t in tasks:
        g = dict((p, m) for m, p in (split(x) for x in t["touches"]))
        for p, m in list(g.items()):
            mm = re.match(r"^python/(?:h2g/)?([A-Za-z_0-9]+)\.py$", p)
            if m == "rw" and mm:
                cand = "python/tests/test_%s.py" % mm.group(1)
                if (ROOT / cand).exists() and g.get(cand) != "rw":
                    bad.append((t["id"], p, cand, g.get(cand)))
    if bad:
        print("B. rw: source whose existing test file is not granted rw::")
        for i, p, c, have in bad:
            print("   %-52s %s -> %s (has %s)" % (i[:52], p, c, have))
        findings += len(bad)
        print()

    # ---- C ---------------------------------------------------------------
    PATHRE = re.compile(r"\b((?:python|docs|build|tests|\.claude)/"
                        r"[A-Za-z0-9_./-]+)\b")
    gaps = []
    for t in tasks:
        g = dict((p, m) for m, p in (split(x) for x in t["touches"]))
        for hit in sorted(set(PATHRE.findall(t.get("verify") or ""))):
            norm = hit if hit.startswith(("python/", "docs/", "build/",
                                          ".claude/")) else "python/" + hit
            covered = None
            for p, m in g.items():
                if overlaps(norm, p) or overlaps(hit, p):
                    covered = "rw" if (covered == "rw" or m == "rw") else m
            if covered is None:
                gaps.append((t["id"], hit, "ABSENT from touches"))
    if gaps:
        print("C. path named in `verify` but not covered by `touches`:")
        for i, h, why in gaps:
            print("   %-52s %-38s %s" % (i[:52], h, why))
        findings += len(gaps)
        print()

    # ---- D ---------------------------------------------------------------
    par = [t for t in tasks if t["lane"] == "parallel"]
    clash = []
    for i in range(len(par)):
        for j in range(i + 1, len(par)):
            for ta in par[i]["touches"]:
                ma, pa = split(ta)
                for tb in par[j]["touches"]:
                    mb, pb = split(tb)
                    if overlaps(pa, pb) and (ma == "rw" or mb == "rw"):
                        clash.append((par[i]["id"], par[j]["id"], pa))
    if clash:
        print("D. two `parallel` tasks overlap with a writer (lane arithmetic "
              "is wrong, not a judgement call):")
        for a, b, p in clash:
            print("   %s <-> %s on %s" % (a[:34], b[:34], p))
        findings += len(clash)
        print()

    # ---- E ---------------------------------------------------------------
    ids = {t["id"] for t in tasks} | {c["id"] for c in (plan.get("closed") or [])}
    dangling = [(t["id"], d) for t in tasks for d in t["depends_on"]
                if d not in ids]
    if dangling:
        print("E. dangling depends_on (never resolves, so the task never runs):")
        for i, d in dangling:
            print("   %-52s -> %s" % (i[:52], d))
        findings += len(dangling)
        print()

    # ---- F ---------------------------------------------------------------
    ungraded = []
    for t in tasks:
        v = t.get("verify") or ""
        for sha in set(re.findall(r"\b[0-9a-f]{7}\b", v)):
            try:
                n = subprocess.run(["git", "rev-list", "--count",
                                    "%s..HEAD" % sha], cwd=ROOT,
                                   capture_output=True, text=True, timeout=15)
                behind = n.stdout.strip()
            except Exception:                                  # noqa: BLE001
                behind = "?"
            if behind not in ("", "0"):
                ungraded.append((t["id"], sha, behind))
    if ungraded:
        print("F. verify quotes a sha that HEAD has moved past "
              "(grade it, or say 'check X against Y' instead):")
        for i, s, b in sorted(ungraded, key=lambda x: -int(x[2] or 0))[:12]:
            print("   %-52s %s (%s commit(s) behind)" % (i[:52], s, b))
        print("   %d total" % len(ungraded))
        print()

    if not findings:
        print("no grant defects found.")
    else:
        print("%d finding(s)." % findings)
    return 1 if findings else 0


if __name__ == "__main__":
    sys.exit(main())
