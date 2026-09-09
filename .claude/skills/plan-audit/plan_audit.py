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
  G  a verify whose done-condition needs a person, on a task that is NOT
     mode requires-user -- it can never programmatically succeed, so the
     runner loops on it forever. This one CLASSIFIES rather than counts: a
     plain vocabulary match for user/person/listen returns findings for
     reasons that have nothing to do with a done-condition, so each source
     is stripped structurally before a leftover match is trusted -- see
     check_g's docstring.
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


# ---- G ---------------------------------------------------------------
# A verify whose done-condition needs a person, but whose task is not mode
# requires-user, is a defect no amount of retrying fixes -- the runner loops
# on it forever. A naive vocabulary match on words like user/person/listen
# is NOT that check: run over this plan it finds words that showed up for
# reasons having nothing to do with a done-condition needing a person --
#   (a) the ILV scope sentence pasted into many tasks verbatim
#       ("The user has set these to LOW PRIORITY ...") is a statement about
#       PRIORITY, not a done-condition.
#   (b) the PATH build/listen, where "listen" is a directory name, not a
#       verb.
#   (c) the MODE TOKEN "requires-user" itself, spelled out inside prose
#       that discusses the mode -- a hyphenated identifier is not the word
#       "user" split off from it.
#   (d) a task that IS this very check (or another plan-audit task) and so
#       necessarily quotes the vocabulary it exists to classify, in order
#       to say what to exempt. Detected structurally, off `touches`
#       granting plan_audit.py -- never by trying to parse "is this a
#       quotation" out of the prose itself, which is the retraction-
#       collision this repo has hit before (CLAUDE.md, "A grep for a
#       retracted sentence is the structural case").
# Each source is stripped BEFORE a leftover user/person/listen match is
# trusted; only what survives all four is reported. Over the plan at
# 665939c (105 open tasks) this returns 0 findings; dropping exemption (a)
# resurfaces the 12 ILV tasks, dropping (b) resurfaces the 3 build/listen
# tasks -- see .claude/skills/plan-audit/test_plan_audit.py.
G_ILV_SENTENCE = "The user has set these to LOW PRIORITY"
G_PATH_RE = re.compile(r"\bbuild/listen\b")
G_MODE_TOKEN_RE = re.compile(r"requires-user")
G_CAND_RE = re.compile(r"\b(user|person|listen)\b", re.I)
G_SELFREF_RE = re.compile(r"plan[-_]audit|plan_audit\.py")


def g_is_selfref(t):
    """A task whose own touches grant plan_audit.py (or another plan-audit
    path) is necessarily discussing this check's vocabulary as subject
    matter, not asserting its own done-condition needs a person."""
    return any(G_SELFREF_RE.search(tok) for tok in t.get("touches", ()))


def g_strip_exempt(v):
    """Remove every span attributable to a known non-signal source, so a
    leftover user/person/listen match means something."""
    v = v.replace(G_ILV_SENTENCE, "")
    v = G_PATH_RE.sub("", v)
    v = G_MODE_TOKEN_RE.sub("", v)
    return v


def check_g(tasks):
    """Return [(task_id, matched_word), ...] for every non-requires-user
    task whose verify still needs a person after exemptions (a)-(d)."""
    out = []
    for t in tasks:
        if t.get("mode") == "requires-user":
            continue
        if g_is_selfref(t):
            continue
        v = t.get("verify") or ""
        hit = G_CAND_RE.search(g_strip_exempt(v))
        if hit:
            out.append((t["id"], hit.group(0)))
    return out


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
    # A "GRADED at <head>: <sha> is <N> commit(s) behind <head> ..." clause
    # is the remedy this check itself prescribes -- a stale sha that has been
    # dated and marked historical is not a finding, only a bare quoted one
    # is. GRADED_RE finds each such clause's body (up to the sentence's own
    # " -- " / " || " terminator, or end of string); SHA_GRADE_RE pulls every
    # sha inside that body that is explicitly said to be behind -- a clause
    # naming several ("a is N behind; b is M behind; c is K behind") grades
    # all of them, not just the first.
    GRADED_RE = re.compile(
        r"GRADED at [0-9a-f]{7}:(?P<body>.*?)(?:\s--\s|\s\|\|\s|$)", re.S)
    SHA_GRADE_RE = re.compile(
        r"\b([0-9a-f]{7})\b\s+is\s+\d+\s+commit\(s\)\s+behind")

    def graded_shas(v):
        out = set()
        for gm in GRADED_RE.finditer(v):
            out.update(SHA_GRADE_RE.findall(gm.group("body")))
        return out

    ungraded = []
    graded = []
    for t in tasks:
        v = t.get("verify") or ""
        gset = graded_shas(v)
        for sha in set(re.findall(r"\b[0-9a-f]{7}\b", v)):
            try:
                n = subprocess.run(["git", "rev-list", "--count",
                                    "%s..HEAD" % sha], cwd=ROOT,
                                   capture_output=True, text=True, timeout=15)
                behind = n.stdout.strip()
            except Exception:                                  # noqa: BLE001
                behind = "?"
            if behind not in ("", "0"):
                (graded if sha in gset else ungraded).append(
                    (t["id"], sha, behind))
    if ungraded:
        print("F. verify quotes a sha that HEAD has moved past, ungraded "
              "(grade it, or say 'check X against Y' instead):")
        for i, s, b in sorted(ungraded, key=lambda x: -int(x[2] or 0))[:12]:
            print("   %-52s %s (%s commit(s) behind)" % (i[:52], s, b))
        print("   %d total (%d already GRADED and not counted here)"
              % (len(ungraded), len(graded)))
        print()
    elif graded:
        print("F. every stale sha quoted in `verify` is GRADED "
              "(%d sha(s) across the plan) -- no bare stale quotes found."
              % len(graded))
        print()

    # ---- G ---------------------------------------------------------------
    needs_person = check_g(tasks)
    if needs_person:
        print("G. verify's done-condition needs a person, but mode is not "
              "requires-user (flip the mode, or reword the done-condition "
              "so a script can satisfy it):")
        for i, word in needs_person:
            print("   %-52s survives on %r" % (i[:52], word))
        findings += len(needs_person)
        print()

    if not findings:
        print("no grant defects found.")
    else:
        print("%d finding(s)." % findings)
    return 1 if findings else 0


if __name__ == "__main__":
    sys.exit(main())
