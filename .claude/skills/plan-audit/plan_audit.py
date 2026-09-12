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
  F  a verify quoting a sha/version/count with nothing to date it. A sha
     TOKEN is judged by ITS OWN occurrence, never by whether the same
     digits are graded somewhere else in the same verify -- see
     sha_occurrences's docstring for the container/subject collapse this
     replaced.
  G  a verify whose done-condition needs a person, on a task that is NOT
     mode requires-user -- it can never programmatically succeed, so the
     runner loops on it forever. This one CLASSIFIES rather than counts: a
     plain vocabulary match for user/person/listen returns findings for
     reasons that have nothing to do with a done-condition, so each source
     is stripped structurally before a leftover match is trusted -- see
     check_g's docstring.
  H  a verify PROMISING to create an artefact that is already sitting in
     the repo -- a spent creation promise the done-condition can never
     freshly satisfy. CLASSIFIES rather than counts: a bare verb+path
     proximity match fires on administrative "GRANTS CORRECTED/WIDENED at
     <sha>:" bookkeeping clauses that are talking ABOUT a path, not
     promising to create it -- see check_h's docstring.
  I  a prerequisite stated ONLY in prose ("this must wait on task X") with
     no matching `depends_on` edge, invisible to a runner that selects by
     the edge. CLASSIFIES rather than counts: prerequisite-shaped words
     (before/must/requires/...) are common in this plan's prose for
     reasons having nothing to do with naming another task, so a match is
     trusted only when it additionally NAMES AN EXISTING PLAN ID -- see
     check_i's docstring.
  J  a task that DECLARES ITSELF a recurring obligation -- its own verify
     instructs a runner never to treat it as permanently satisfied -- but
     that has nonetheless been moved to `closed`, or whose last runs.jsonl
     record reads outcome "done". The plan schema has no recurrence field
     (see plan_audit.py's own module docstring history), so the one
     recurring task in the repo can only declare itself in prose, and nothing
     stops a runner from closing it on a green run anyway -- which is
     exactly what happened to its own predecessor. CLASSIFIES rather than
     counts: a generic recurrence-vocabulary scan (recurring/whenever/
     periodic/...) also matches prose that merely DISCUSSES recurrence as a
     topic (a sibling plan-audit task explaining the defect class), so a
     match is trusted only on the narrower, operational phrases a
     self-declaring verify actually uses to instruct a runner not to close
     it -- see check_j's docstring.

Head-freshness note: the worked figures quoted in each check's own comment
block above (665939c for check_e's exemption drops, 5a2fa2d for check_h and
check_i's clause/finding counts, 24b9f1d for check_j's recurrence-vocabulary
and closed-entries scans) are HISTORICAL readings taken at those heads --
they are not re-derived on every import, and nothing here re-checks them
against the live plan. The plan itself has moved on (144 open / 344 closed
at eae8d8d, vs the 101-105 open / 286 closed the comments were measured
against), so those specific counts are already stale -- only the
CLASSIFICATION each comment argues for (which exemption, which narrowing)
is still the live behaviour. This file's checks were last re-run against
the live plan and runs.jsonl -- not merely the comments re-read -- at
eae8d8d (v0.5.484): check_i returns 1 finding and check_j returns 0,
matching test_check_i_real_plan_has_one_known_ambiguous_finding and
test_check_j_real_plan_has_zero_findings. Re-verifying a check's own
figures means re-running it against the live plan/closed/runs.jsonl at a
current head and updating this paragraph's head and counts, not editing
the per-check historical worked examples above, which stay pinned to the
head that produced them.
"""
import collections
import json
import pathlib
import re
import subprocess
import sys

ROOT = pathlib.Path(__file__).resolve().parents[3]
PLAN = ROOT / ".claude/tasks/whattask.json"
RUNS = ROOT / ".claude/tasks/runs.jsonl"


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


# ---- F ---------------------------------------------------------------
# A "GRADED at <head>: <sha> is <N> commit(s) behind <head> ..." clause is
# the remedy this check itself prescribes -- a stale sha that has been
# dated and marked historical is not a finding, only a bare quoted one is.
# GRADED_RE finds each such clause's body (up to the sentence's own
# " -- " / " || " terminator, or end of string); SHA_GRADE_RE pulls every
# sha inside that body that is explicitly said to be behind -- a clause
# naming several ("a is N behind; b is M behind; c is K behind") grades
# all of them, not just the first.
#
# A sha string collapsed into a SET of "graded shas" for the whole verify
# is NOT this check -- it is the exact container/subject bug this file's
# other checks were swept for: if the same 7-hex-digit string is quoted
# TWICE in one verify -- once inside a GRADED clause (dated, fine) and
# once again bare, elsewhere in the same text (the actual staleness this
# check exists to catch) -- a `sha in {graded shas}` test can only see the
# digits, not which quote it is testing, so the bare copy hides behind the
# graded one and the finding is silently lost. sha_occurrences judges each
# TOKEN by its own character offset against graded_positions (also offsets,
# not strings), so a task with both a graded and a bare occurrence of the
# same sha reports it as ungraded -- there is at least one occurrence
# nothing has dated. See test_plan_audit.py's
# test_check_f_bare_occurrence_beside_a_graded_one_is_still_reported for
# the worked case, and check_f's own docstring for the two-arg contract
# that makes this classification testable without a live git process.
GRADED_RE = re.compile(
    r"GRADED\s+at\s+[0-9a-f]{7}:(?P<body>.*?)(?:\s--\s|\s\|\|\s|$)", re.S)
SHA_GRADE_RE = re.compile(
    r"\b([0-9a-f]{7})\b\s+is\s+\d+\s+commit\(s\)\s+behind")
SHA_TOKEN_RE = re.compile(r"\b[0-9a-f]{7}\b")


def graded_positions(v):
    """Return the set of absolute character offsets, in `v`, of every sha
    token that sits inside a GRADED clause's own '<sha> is N commit(s)
    behind' body. A position, not a string: two occurrences of the same
    digits at two different offsets are two different facts about `v`."""
    out = set()
    for gm in GRADED_RE.finditer(v):
        body = gm.group("body")
        base = gm.start("body")
        for sm in SHA_GRADE_RE.finditer(body):
            out.add(base + sm.start(1))
    return out


def sha_occurrences(v):
    """Return [(sha, is_graded), ...] for every sha-shaped token in `v`,
    each classified by ITS OWN occurrence position -- never by whether
    that sha's digits are graded somewhere else in `v`. This is the slice
    check_f reads: a sha graded once and bare-quoted again later in the
    same verify yields two entries for the same sha, one True and one
    False, and check_f treats the pair as ungraded because not every
    occurrence is dated."""
    gpos = graded_positions(v)
    return [(m.group(0), m.start() in gpos) for m in SHA_TOKEN_RE.finditer(v)]


def _git_rev_list_behind(sha, root=ROOT, timeout=15):
    try:
        n = subprocess.run(["git", "rev-list", "--count", "%s..HEAD" % sha],
                            cwd=root, capture_output=True, text=True,
                            timeout=timeout)
        return n.stdout.strip()
    except Exception:                                          # noqa: BLE001
        return "?"


def check_f(tasks, behind_of=_git_rev_list_behind):
    """Return (ungraded, graded), each a list of (task_id, sha, behind).
    A (task, sha) pair lands in `ungraded` when behind_of(sha) says HEAD
    has moved past it AND at least one of its occurrences in that task's
    verify is not inside a GRADED clause -- sliced per-occurrence via
    sha_occurrences, never via a bare set of sha strings (see this
    section's docstring for the collapse that fix replaced). `behind_of`
    is injectable so the position/slice logic is testable without a git
    subprocess."""
    ungraded, graded = [], []
    for t in tasks:
        v = t.get("verify") or ""
        occ = sha_occurrences(v)
        if not occ:
            continue
        by_sha = collections.OrderedDict()
        for sha, is_graded in occ:
            by_sha.setdefault(sha, []).append(is_graded)
        for sha, flags in by_sha.items():
            behind = behind_of(sha)
            if behind not in ("", "0"):
                bucket = graded if all(flags) else ungraded
                bucket.append((t["id"], sha, behind))
    return ungraded, graded


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
# trusted; only what survives all seven is reported. Over the plan at
# 665939c (105 open tasks) this returned 0 findings; dropping exemption (a)
# resurfaces the 12 ILV tasks, dropping (b) resurfaces the 3 build/listen
# tasks -- see .claude/skills/plan-audit/test_plan_audit.py.
#
# Two more sources showed up sweeping this check at 50a6178, both container/
# subject collapses of the same shape as (b) and (a):
#   (e) `python/listen.py` (the harness module) and its attribute accesses
#       (`listen.render_sidplayfp`) are a FILENAME/module reference -- the
#       substring "listen" inside a dotted identifier is not the verb.
#       8 of the 8 findings on the live plan at 50a6178 were this shape
#       (`preset-key-misses-should-be-countable-not-only-warnable`,
#       `artefact-guard-blocks-a-mention-and-misses-approvals-py`,
#       `listen-py-traces-our-side-without-the-multiplier`,
#       `restage-listening-md-after-the-multiplier-fix`,
#       `test-that-a-preset-multiplier-file-is-traced-at-its-rate`,
#       `aud-voices-needs-the-artefact-grant-and-a-mute-aware-render-cache`)
#       -- dropping this exemption resurfaces all 6.
#   (f) "the user has set/placed ... priority" generalises (a) beyond the
#       one pasted ILV sentence -- `unblock-the-six-interleaved-classic-
#       files-their-material-now-exists` says "the user has placed them
#       behind the 83 RH files ... LOW priority", a paraphrase, not the
#       literal sentence (a) matched. "the user named <path>" describing a
#       CLI's own behaviour ("a path the user named that does not exist
#       should be an error") is the same non-signal one step further:
#       descriptive prose about what the TOOL does with a user-supplied
#       value, not a done-condition needing a person -- see
#       `a-missing-presets-file-runs-fidelity-on-defaults-instead-of-refusing`.
#   (g) "NOTE FOR THE USER: ..." is a sequencing ASIDE addressed to a
#       person, appended after the done-condition, not the done-condition
#       itself -- `restage-listening-md-after-the-multiplier-fix`'s verify
#       is satisfied by re-running listen.py and regenerating LISTENING.md;
#       the trailing note ("the 13 pending sign-off tasks read these
#       notes, so this should land before any further listening is asked
#       for") only tells a human what to prioritise NEXT.
# All narrowed to the operational shape (a preposition immediately after
# "the user", or the literal "NOTE FOR THE USER:" clause marker), never a
# bare "user" stopword list -- see test_plan_audit.py.
G_PRIORITY_RE = re.compile(
    r"the user has (?:set|placed)\b[^.]*?\bpriority\b", re.I)
G_NAMED_DESC_RE = re.compile(
    r"the user named\b[^.]*?\b(?:error|exist)\w*\b", re.I)
G_NOTE_RE = re.compile(
    r"NOTE FOR THE USER:.*?(?:\s\|\|\s|\Z)", re.I | re.S)
G_PATH_RE = re.compile(r"\bbuild/listen\b")
G_FILENAME_RE = re.compile(r"\blisten\.(?:py\b|[a-z_][a-z0-9_]*)", re.I)
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
    v = G_PRIORITY_RE.sub("", v)
    v = G_NAMED_DESC_RE.sub("", v)
    v = G_NOTE_RE.sub("", v)
    v = G_PATH_RE.sub("", v)
    v = G_FILENAME_RE.sub("", v)
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


# ---- H ---------------------------------------------------------------
# A verify PROMISING to create an artefact that already exists is a spent
# creation promise: the done-condition reads as "this task creates X", but
# X is already sitting in the tree, so the condition is either trivially
# true before the task ever runs or the wording is stale. A bare
# verb+nearby-path match is NOT that check -- run unfiltered over the live
# plan at 5a2fa2d (101 open tasks) it fires 3 times and every one is noise:
#   ab-7 and ab-9 share "...the previous grant named python/fidelity.py,
#   which this task only READS" -- an explicit NEGATION of writing, sitting
#   inside a "GRANTS CORRECTED at <sha>:" bookkeeping clause, not a promise.
#   ab-7 also has "the design document writes `H2G-CONVERSION-METHOD.md`"
#   a few dozen characters further into that SAME clause -- prose ABOUT a
#   path (and about the path's own missing docs/ prefix), not the task's
#   own deliverable.
# All three sit inside one clause shape this plan already uses for
# bookkeeping ("GRANTS CORRECTED/WIDENED at <sha>: ..."), so that clause is
# stripped -- structurally, like check_g's exemptions -- before a leftover
# verb+existing-path match is trusted. Doing so drops all 3 to 0.
#
# Sweeping this check at 50a6178 surfaced two more container/subject
# collapses of the same shape, both narration ABOUT a write rather than a
# promise of THIS task's own:
#   - a "BLOCKED at <sha>: ..." or "PARTIAL at <sha>: ..." clause narrates
#     a PAST run of the verify, explicitly saying what did or didn't
#     happen ("NOT RUN, AND DELIBERATELY SO ... NOTHING WAS WRITTEN"; "...
#     writing the exact patch to scratch; stopped at the undeclared
#     python/fidelity.py ... partial") -- see
#     `promote-pulse-phase-into-fidelity-toggles-once-the-multiplier-gate-
#     is-settled` and
#     `noise-run-agreement-is-blind-to-the-gate-bit-and-that-is-most-of-its-
#     disagreement`. Folded into H_GRANTS_RE's clause-stripping alongside
#     GRANTS CORRECTED/WIDENED, since all four are this plan's "<TAG> at
#     <sha>: <narration>" bookkeeping shape.
#   - "a fan-out writing <path>" narrates a DIFFERENT, concurrently-run
#     task's write (a lockctl/lane-contention war story), not this task's
#     own -- see `the-approvals-regeneration-task-does-not-grant-python-
#     h2g-though-it-converts-the-corpus` and its sibling
#     `the-approvals-task-touches-omit-python-h2g-though-the-run-converts-
#     the-whole-corpus`. Stripped as its own narrow phrase, since it is
#     inline prose, not wrapped in a "<TAG> at <sha>:" clause.
# Dropping either exemption resurfaces exactly the 4 findings named above.
H_VERB_RE = re.compile(
    r"\b(?:creates?|creating|writes?|writing|generates?|generating)\b",
    re.I)
H_PATH_RE = re.compile(r"\b((?:python|docs|build|tests|\.claude)/"
                       r"[A-Za-z0-9_./-]+)\b")
H_INLINE_PATH_RE = re.compile(r"`([A-Za-z0-9_./-]+\.[A-Za-z0-9]+)`")
H_WINDOW = 200
H_GRANTS_RE = re.compile(
    r"\b(?:GRANTS (?:CORRECTED|WIDENED)|BLOCKED|PARTIAL) at [0-9a-f]{7}\b"
    r".*?(?:\s\|\|\s|\Z)",
    re.S)
H_FANOUT_RE = re.compile(
    r"\bfan-out writing\s+[A-Za-z0-9_./-]+", re.I)


def h_strip_exempt(v):
    """Remove GRANTS-CORRECTED/WIDENED/BLOCKED/PARTIAL bookkeeping clauses
    -- narration about this task's OWN history, never its done-condition
    -- and "a fan-out writing <path>" phrases narrating a DIFFERENT task's
    write."""
    v = H_GRANTS_RE.sub(" ", v)
    v = H_FANOUT_RE.sub(" ", v)
    return v


def h_find_path(tail):
    m = H_PATH_RE.search(tail)
    if m:
        return m.group(1)
    m = H_INLINE_PATH_RE.search(tail)
    if m:
        return m.group(1)
    return None


def h_path_exists(cand):
    """True for a SOURCE path that already exists. `build/` is excluded on
    purpose: it is gitignored, regenerable output, so a verify that writes
    build/approvals.json describes a regeneration, not a promise to create a
    file that is already there -- and because that directory exists only in
    a checkout that has run the tools, one plan read 0 findings in a fresh
    worktree and 2 in the main checkout (measured at 50a6178). A check whose
    answer depends on which clone runs it is not a check."""
    if cand.startswith("build/"):
        return False
    norm = cand if cand.startswith(("python/", "docs/", "build/",
                                    ".claude/")) else "python/" + cand
    return (ROOT / norm).exists() or (ROOT / cand).exists()


def check_h(tasks):
    """Return [(task_id, verb, path), ...] for every verify whose text
    promises to create/write/generate an artefact that already exists in
    the repo, once GRANTS-clause bookkeeping and plan-audit self-reference
    are stripped."""
    out = []
    for t in tasks:
        if g_is_selfref(t):
            continue
        v = h_strip_exempt(t.get("verify") or "")
        for vm in H_VERB_RE.finditer(v):
            tail = v[vm.end():vm.end() + H_WINDOW]
            cand = h_find_path(tail)
            if cand and h_path_exists(cand):
                out.append((t["id"], vm.group(0), cand))
    return out


# ---- I ---------------------------------------------------------------
# A prerequisite stated ONLY in prose -- "this must wait on task X" with no
# matching `depends_on` edge -- is invisible to a runner that selects tasks
# by the edge: exactly what happened to ab-9's GATE clause naming
# `regrid-could-be-searchable-from-repeated-attack-run-length-without-a-
# trace` before that edge was added. A bare cue-word scan for prerequisite
# language (before/ahead of/must/requires/GATE/depends on/blocked by/
# prerequisite/needs) is NOT that check -- these are common words in this
# plan's prose for reasons having nothing to do with naming another task:
# over the live plan at 5a2fa2d (101 open tasks) 68 `||`-delimited clauses
# contain one, and the overwhelming majority are the ILV/interleaved-
# classic tasks' pasted "...do not start this ahead of an RH task..."
# sentence, which names no task id at all -- prose that can never become an
# edge because there is no edge target to add. Key the classification on
# whether the matched clause additionally NAMES AN EXISTING PLAN ID (open
# or closed) that is not already in the task's own `depends_on` -- that is
# what separates the one real historical case (ab-9, before its edge was
# added) from the noise, and it is structural, like check_g's exemptions,
# never a tightened phrase list.
#
# Sweeping this check at 50a6178 found the cue-word scan itself has a
# container/subject collapse: a " || "-delimited CLAUSE is not the unit the
# cue word and the id belong to -- one clause is often several sentences,
# and this plan's own opening boilerplate puts a cue word and an id in the
# SAME clause but a DIFFERENT sentence from each other:
#   "OPENED by `X` at <sha>; every figure in this text is HISTORICAL at
#   that head and must be re-measured, not re-quoted."
# pastes an id X next to "must" 64 times across the live plan -- every one
# of them a PROVENANCE reference (which task's finding opened this one),
# never a prerequisite. I_OPENED_RE strips this exact recurring sentence
# before the cue/id search runs, since the id inside it can never be a
# dependency of the task it is quoted in (it is that task's own origin).
# A second, rarer shape survives even that: `unblock-the-six-interleaved-
# classic-files-their-material-now-exists`'s clause reads "...must be
# re-measured, not re-quoted. `the-six-interleaved-classic-files-have-
# never-been-listened-to` is recorded blocked at 4b5d7f0 on '0 of the six
# appear...'" -- two separate SENTENCES (the boilerplate, then a status
# report on a different task) sharing one `||` clause. I_SENTENCE_RE slices
# each clause at sentence boundaries so the cue and the id must occur in
# the SAME sentence, not merely the same clause, before either can pair up
# -- the count-then-slice fix, applied at the sentence level because the
# clause level is too coarse a container. `nrun-blind-to-tick-length-noise`
# has the same provenance shape spelled WITHOUT backticks, lower-case, and
# parenthetical -- "(opened by our-noise-run-is-the-note, same Dimension
# entry)" -- so I_OPENED_PAREN_RE strips that shape too.
#
# A THIRD collapse showed up on `noise-run-agreement-is-blind-to-the-gate-
# bit-and-that-is-most-of-its-disagreement`: the cue word GATE matched
# inside the quoted id `re-run-the-hold-delta-split-after-the-GATE-aware-
# noise-runs` itself -- the id's own slug happens to spell the cue word.
# A cue match inside an id token's own span is a fact about the id's NAME,
# never a prerequisite in the surrounding prose, so id token spans are
# computed FIRST and a cue match fully contained in one is not trusted --
# see _cue_outside_ids.
# Dropping the OPENED-boilerplate strip, the parenthetical strip, or the
# id-span exclusion resurfaces 64, 1 and 1 finding(s) respectively; see
# test_plan_audit.py.
I_CUE_RE = re.compile(
    r"\b(?:before|ahead\s+of|must|requires|GATE|depends\s+on|blocked\s+by|"
    r"prerequisite|needs)\b", re.I)
I_ID_TOKEN_RE = re.compile(r"\b[a-z][a-z0-9]*(?:-[a-z0-9]+)+\b")
I_OPENED_RE = re.compile(
    r"OPENED by `[a-z][a-z0-9-]*` at [0-9a-f]{7};\s*every figure in this "
    r"text is HISTORICAL at that head and must be re-measured, not "
    r"re-quoted\.",
    re.I)
I_OPENED_PAREN_RE = re.compile(
    r"\(opened by [a-z][a-z0-9-]*[^)]*\)", re.I)
I_SENTENCE_RE = re.compile(r"(?<=[.!?])\s+")


def i_strip_exempt(v):
    """Remove the plan's recurring "OPENED by `X` at <sha>; ... must be
    re-measured, not re-quoted." boilerplate, and its parenthetical
    "(opened by X, ...)" sibling -- both PROVENANCE, naming which task's
    finding opened or folded into this one, never a prerequisite on it."""
    v = I_OPENED_RE.sub(" ", v)
    v = I_OPENED_PAREN_RE.sub(" ", v)
    return v


def _cue_outside_ids(clause):
    """True if `clause` has an I_CUE_RE match that does NOT sit entirely
    inside an I_ID_TOKEN_RE span -- so a cue word that is only a substring
    of a quoted id's own slug (e.g. "...-the-gate-aware-...") never counts
    as prerequisite language in the surrounding prose."""
    id_spans = [m.span() for m in I_ID_TOKEN_RE.finditer(clause)]
    for cm in I_CUE_RE.finditer(clause):
        cs, ce = cm.span()
        if not any(s <= cs and ce <= e for s, e in id_spans):
            return True
    return False


def check_i(tasks, closed=()):
    """Return [(task_id, named_id), ...] for every SENTENCE that reads as
    a prerequisite, names a real plan id (open or in `closed`), and has no
    corresponding `depends_on` edge on that task. Sliced at the sentence,
    not the `||` clause, so a cue word in one sentence cannot pair with an
    id quoted in a neighbouring sentence of the same clause -- see
    I_SENTENCE_RE's docstring above."""
    all_ids = {t["id"] for t in tasks} | {c["id"] for c in closed}
    out = []
    seen = set()
    for t in tasks:
        dep = set(t.get("depends_on") or ())
        v = i_strip_exempt(t.get("verify") or "")
        sentences = [s for clause in v.split(" || ")
                     for s in I_SENTENCE_RE.split(clause)]
        for clause in sentences:
            if not _cue_outside_ids(clause):
                continue
            for tok in I_ID_TOKEN_RE.findall(clause):
                if tok == t["id"] or tok not in all_ids or tok in dep:
                    continue
                key = (t["id"], tok)
                if key not in seen:
                    seen.add(key)
                    out.append(key)
    return out


# ---- J ---------------------------------------------------------------
# A task that DECLARES ITSELF a recurring obligation -- one whose verify
# tells a runner it can never be permanently satisfied -- must not appear
# in `closed`, and must not carry a `done` last record in runs.jsonl. Both
# are the exact failure this repo already lived through once:
# regenerate-fidelity-artefacts-at-v0-5-459 was closed, then its successor
# regenerate-the-fidelity-artefacts-whenever-the-converter-emission-changes
# was written specifically to say "THIS TASK CANNOT BE SATISFIED ONCE" and
# "a runner that finds it done ... should leave it open, not close it" --
# in prose, because the plan schema (see split()/PLAN above) has no
# recurrence field to hold that fact structurally.
#
# A generic recurrence-vocabulary scan is NOT this check. Run unfiltered
# over the plan at 24b9f1d (101 open tasks) a bare
# r"\b(recurring|recur|repeat|periodic|whenever|ongoing)\b" scan already
# returns only 2 hits, but one of them --
# a-done-run-record-describes-one-commit-and-a-later-commit-can-expire-it
# -- is a SIBLING plan-audit task whose own verify reads "A recurring
# obligation is not readable as permanently done" while DISCUSSING the
# defect class (and naming the other task's history) rather than declaring
# recurrence for ITSELF: it carries no instruction to a runner about its
# own closure. J_DECLARE_RE narrows to the operational phrases a verify
# actually uses to tell a runner not to close it -- "cannot be satisfied
# once", "leave it open", "deliberately version-less" -- which fire only on
# the one real case and 0 times on that sibling, checked in
# test_plan_audit.py.
#
# Closed entries in this plan carry only id/title/closed_by/reason -- no
# `verify` (see PLAN's own schema) -- so a declaration cannot be read back
# off a closed record directly; J_DECLARE_RE is instead run over each
# closed entry's title+reason too, on the chance a future close narrates
# the same self-declaring phrase there. Over the live `closed` list at
# 24b9f1d (286 entries) this finds 0 -- including
# regenerate-fidelity-artefacts-is-a-recurring-obligation-modelled-as-a-
# one-shot-task, whose title and reason both say "recurring" but neither
# carries the operational phrase, because that task's own job was closing
# out the one-shot MISTAKE, not declaring recurrence for itself.
J_DECLARE_RE = re.compile(
    r"cannot\s+be\s+satisfied\s+once|leave\s+it\s+open|"
    r"deliberately\s+version-?less",
    re.I)


J_QUOTED_RE = re.compile(r"`[^`]*`|'[^']*'")


def j_strip_quoted(text):
    """A declaration phrase inside backticks or single quotes is MENTIONED,
    not declared -- the task at eae8d8d that fixed J_DECLARE_RE's own
    whitespace handling quoted its phrases ('cannot be satisfied once',
    'leave it open') in its verify, closed as done, and check J read the
    quotation as a recurring obligation that had been closed. Same
    container/subject collapse as checks G/H/I: the phrase belongs to the
    sentence quoting it, not to this task's done-condition."""
    return J_QUOTED_RE.sub(" ", text)


def check_j_declared(tasks):
    """Return the ids of open tasks whose own verify self-declares as a
    recurring obligation (an operational instruction not to close it)."""
    return [t["id"] for t in tasks
            if J_DECLARE_RE.search(j_strip_quoted(t.get("verify") or ""))]


def load_runs_last(path=RUNS):
    """Return {task_id: last record} from runs.jsonl, last line wins."""
    last = {}
    if not path.exists():
        return last
    for line in path.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line:
            continue
        try:
            rec = json.loads(line)
        except ValueError:
            continue
        tid = rec.get("id") or rec.get("task_id")
        if tid:
            last[tid] = rec
    return last


def check_j(tasks, closed, runs_last):
    """Return [(task_id, reason), ...] for every task that declares itself
    a recurring obligation and either (a) appears in `closed`, or (b) has
    a last runs.jsonl record reading outcome "done"."""
    declared = set(check_j_declared(tasks))
    for c in closed:
        text = (c.get("title") or "") + " " + (c.get("reason") or "")
        if J_DECLARE_RE.search(j_strip_quoted(text)):
            declared.add(c["id"])

    closed_ids = {c["id"] for c in closed}
    out = []
    for tid in sorted(declared):
        if tid in closed_ids:
            out.append((tid, "in `closed`"))
        rec = runs_last.get(tid)
        if rec and rec.get("outcome") == "done":
            out.append((tid, "runs.jsonl last record is outcome \"done\""))
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
    ungraded, graded = check_f(tasks)
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

    # ---- H ---------------------------------------------------------------
    spent_creation = check_h(tasks)
    if spent_creation:
        print("H. verify promises to create an artefact that already "
              "exists (reword the done-condition, or drop the promise):")
        for i, verb, path in spent_creation:
            print("   %-52s %-10s %s" % (i[:52], verb, path))
        findings += len(spent_creation)
        print()

    # ---- I ---------------------------------------------------------------
    prose_prereq = check_i(tasks, plan.get("closed") or [])
    if prose_prereq:
        print("I. verify states a prerequisite naming a real task id with "
              "no depends_on edge (add the edge, so a selector can see it):")
        for i, tok in prose_prereq:
            print("   %-52s -> %s" % (i[:52], tok))
        findings += len(prose_prereq)
        print()

    # ---- J ---------------------------------------------------------------
    runs_last = load_runs_last()
    declared_recurring = check_j(tasks, plan.get("closed") or [], runs_last)
    if declared_recurring:
        print("J. task declares itself a recurring obligation but is closed, "
              "or reads a `done` last run (a recurring obligation must never "
              "be readable as permanently satisfied):")
        for i, why in declared_recurring:
            print("   %-52s %s" % (i[:52], why))
        findings += len(declared_recurring)
        print()

    if not findings:
        print("no grant defects found.")
    else:
        print("%d finding(s)." % findings)
    return 1 if findings else 0


if __name__ == "__main__":
    sys.exit(main())
