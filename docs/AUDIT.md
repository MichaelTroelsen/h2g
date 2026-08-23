# Project audit — code review, learnings, suggestions

Audited at `d1866c2` (v0.5.50), 252 tests passing, tree clean. Scope: the
Python port (`python/`), its tooling (`fidelity.py`, `survey.py`,
`presets.py`, `listen.py`, `bump_version.py`), the docs, and the working
process the git history records. Findings below are verified against the
code or by running it — anything not verified is marked as a suggestion.

---

## 1. Defects found by this audit

### 1.1 `--slides` on the CLI is a silent no-op — the exact defect class this project hunts

`cli.py:83` defines the flag; the `convert()` call at `cli.py:154-160` never
forwards it. Proven end-to-end: converting `Flash_Gordon.sid` via
`python -m h2g` with and without `--slides` produces byte-identical output,
while `convert(..., slides=True)` through the API changes the bytes.

`fidelity.py:670` calls `convert()` directly with `opts["slides"]`, so every
measurement in v0.5.50's commit is real — but a user following README's
`--slides` documentation gets nothing, silently. This is precisely the
"command that parses, loads and displays but does nothing" failure mode the
project just diagnosed in GoatTracker's GTS5 speed table (v0.5.50) and in
gt2reloc's error path. It survived because `cli.py` is the one layer with no
tests (§2.1).

**Fix:** add `slides=args.slides` to the call. Consider whether
`presets.json`'s `always` block should carry `slides` too (§1.4).

### 1.2 `--tempo 128..255` crashes with a traceback instead of an error

`cli.py:144` accepts `GT_MIN_TEMPO..255`; `convert.py:160` validates
`GT_MIN_TEMPO..0x7F` and raises `ValueError`, which is not in `cli.py:161`'s
except tuple `(SidFormatError, UnsupportedSidError, ConversionAbort)`. So
`--tempo 200` passes argument parsing and then tracebacks. Either bound the
CLI check at 127 (correct: `gplay.c:494` masks with `& 0x7f`, and ≥ `$80`
means "this channel only") or catch `ValueError` in `main()`.

### 1.3 `--tempo`'s help text describes the superseded mechanism

`cli.py:47-52` still says the tempo is written "into the last instrument"
and advises "speed multiplier 2". v0.5.42 replaced the instrument-63 route
with `CMD_SETTEMPO` — `goatwriter.py:104-110` documents why the old route
was wrong twice over, and the fastest steady row is now 3 calls (multiplier
3, not 2). The help text is the only user-facing place that still teaches
the old model. Same drift noted earlier in README § `--tempo` and
`SNG2SID-FIDELITY.md` §3 (flagged in v0.5.45's session, still open).

### 1.4 `CLAUDE.md`'s regeneration command silently produces an empty column

`CLAUDE.md:60` says:

    python survey.py <sid_dir> -o ../SURVEY.md --legal-restart

Without `--gt2reloc`, the survey's pack-back column silently empties — the
v0.5.44 fork warned exactly this, and the sessions since have all run with
`--gt2reloc` added by hand. The one command a fresh agent will copy-paste is
the one that quietly degrades the artefact. Add the flag to the documented
command.

Related latent inconsistency: `fidelity.py:394` reads
`always.get("slides")` from `presets.json`, but `presets.py` never emits a
`slides` key, so the setting can only diverge between the two tools once
someone adds it by hand to one of them.

### 1.5 Preset/flag interaction breaks on `--format=gts5` syntax

`cli.py:115` detects explicitly-given flags with
`given = set(argv...)` and membership tests like `"--format" not in given`.
Argparse accepts `--format=gts5` as one token, which defeats the check: the
preset would silently override an explicitly typed value. Low severity
(nothing currently ships that syntax), but the fix is one line — test with
`any(a == flag or a.startswith(flag + "=") for a in argv)`.

---

## 2. Structural risks

### 2.1 The untested layer is where the bugs were

Every defect in §1 lives in `cli.py` or a doc. No test imports `h2g.cli`;
there is no CI at all (no `.github/`). Meanwhile the heavily tested core
(`patterns.py`, `tracks.py`) has survived five concurrent forks without a
regression, guarded by 252 tests and the byte-exact fixture. The pattern is
unambiguous: coverage has tracked hardness exactly.

**Suggestion:** (a) a handful of `cli.main()` tests — flag forwarding can be
asserted with a stub `convert` in a few lines, and a forwarding test would
have caught §1.1 the day it was written; (b) a minimal GitHub Actions
workflow running `pytest` from `python/` — the unit tests need no corpus, no
gt2reloc and no siddump, so they run anywhere.

### 2.2 `convert()` accumulates boolean parameters

`convert()` now takes 8 option parameters and every new feature adds one,
threading through `cli.py`, `fidelity.py`, `survey.py`, `presets.py` and
`convert.ps1` — five call sites that must stay in sync (§1.1 is what happens
when one misses). **Suggestion:** a `ConvertOptions` dataclass with the
defaults encoding the fixture, passed whole. One place to add an option, one
place for presets to fill, and the fixture invariant becomes "default
`ConvertOptions()` reproduces Commando byte-exactly" — a single test.

### 2.3 Default output is fidelity-poor by design, and only the docs know

At defaults the output is GTS2 (whose importer overruns on our portamento
commands), 6× too slow (no tempo), unslid, unexportable to `.sid` (illegal
restart), and missing the two-byte bend operand. Every one of those defaults
is *correct* — the fixture anchors them — but the result is that the obvious
first command a newcomer runs produces the worst output the tool can make,
and the knowledge of which flags to stack lives in `presets.json`'s `always`
block, `convert.ps1`, and scattered README sections.

**Suggestion:** one umbrella flag (`--best`, or `--modern`) equivalent to
`--format gts5 --tempo auto --legal-restart --slides` + the per-song preset
if present. The fixture stays anchored; the newcomer gets one discoverable
switch instead of an archaeology exercise. README's first example should use
it.

### 2.4 One fixture, and it lives on the least-capable path

`Commando.sng` is the project's only byte-exact anchor, and it encodes the
GTS2/no-options path. All the newer machinery — GTS5 speed table, slides,
legal restart, `ensure_playable_orderlists` — is guarded only by unit tests
and the corpus surveys, which assert properties, not bytes.
**Suggestion:** freeze a second golden fixture (e.g. `Commando.best.sng`,
generated at the §2.3 umbrella settings, hash-asserted in a test). Cheap to
add, and it turns "did some fork change modern-path bytes?" from a
2-minute corpus diff into a failing test. It also gives re-anchoring a
procedure: the GTS2 fixture never moves, the best-path fixture is
deliberately regenerated when an output-changing feature lands.

### 2.5 Header parsing trusts two hardcoded assumptions silently

`sidfile.py` hardcodes `HLEN = 0x7F` and reads the load address from
`0x7C/0x7D`, deliberately preserving VB6 behaviour. Fine — but a PSID with
`dataOffset != 0x7C` or a nonzero header `loadAddress` misparses with no
warning: every table lookup lands shifted, and the failure mode is the
detection chain matching nothing (or worse, §"fake success"). The fields are
already read (`version`, at `0x04`) or trivially readable. **Suggestion:**
keep the behaviour, add a loud log line when `dataOffset != 0x7C` or header
`loadAddress != 0` — the corpus contains none today, so the warning is free
until the day it isn't.

### 2.6 The disassembler the method depends on is a scratch file

Every substantive finding since v0.5.25 came from disassembling players with
`dis6502.py` — which lives in `$TMP`, is rebuilt each session, and is
documented only in `whats-next.md` handoffs (along with the warning not to
name it `dis.py`). The project's single most-used investigation tool is the
only tool not in the repo. **Suggestion:** commit it as `tools/dis6502.py`.

### 2.7 Facts about GoatTracker internals are quadruplicated

The greloc empty-voice mechanism was described wrongly in three documents
simultaneously (corrected v0.5.47); the tempo mechanism is currently right
in `goatwriter.py` and stale in `cli.py` + README + `SNG2SID-FIDELITY.md`
(§1.3). Verified GoatTracker facts (limits, byte meanings, `gplay.c`
line-referenced semantics) are re-stated in at least four places.
**Suggestion:** one `docs/GOATTRACKER-FACTS.md` holding the verified-facts
table; everything else links. A fact stated once can only be wrong once.

### 2.8 Concurrent-fork versioning races are handled by convention only

`bump_version.py` rewrites `__init__.py` + `CHANGELOG.md`; two forks bumping
concurrently already collided once (recorded in the v0.5.43 handoff). The
convention — parent serialises, forks stage by pathspec — works but is
memory, not mechanism. **Suggestion:** smallest fix is for forks to never
bump (parent bumps at serialisation time); `CLAUDE.md` currently says "bump
on every commit", which forks read as "I must bump". One sentence there
("in a concurrent session, only the serialising agent bumps") makes the
convention explicit.

---

## 3. Learnings worth keeping (things this project does right)

Recorded because they are transferable, and because half of them were paid
for with a wrong conclusion first.

1. **Disassemble, don't trust.** Every dialect decision is justified by
   player code at a named address, in a comment at the point of use. The VB6
   original, the port's own comments, and three separate handoff claims have
   each been overturned by reading the 6502. The convention that a claim
   carries its evidence (`$1184: DEC $165D,X`) is what made the overturns
   cheap.
2. **A byte-exact fixture plus opt-in flags.** Every behaviour change is
   opt-in; the fixture pins the legacy path. This let five concurrent forks
   land converter changes with zero regressions. (§2.4: the modern path now
   deserves the same protection.)
3. **Measure playback, not storage — and control the baseline.** The
   presets scorer was wrong until it counted played rows; the v0.5.50 fork
   re-baselined mid-run when another fork's fix landed, rather than crediting
   itself with it. Corollary, now proven three times (digi rest, slides,
   vibrato): **a metric that cannot see a change is not evidence the change
   did nothing** — document the blindness next to the fix.
4. **Fail loudly rather than fabricate.** `check_detection_sound`,
   `_table_length_byte`'s refusal to wrap, the fake-success principle. The
   project's worst class of bug (structurally valid, musically empty) is
   guarded against by design, not review.
5. **Thresholds from data, not round numbers.** `MAX_DANGLING_SHARE = 2/3`
   is documented with the measurements on both sides of it. Nobody will
   "tidy" it to 0.5.
6. **External tools are guilty until proven silent.** gt2reloc reports
   nothing on failure; the rule "test for the output file, never the exit
   code" is written where it's needed. §1.1 shows the same skepticism must
   apply to this project's own CLI surface.
7. **Handoffs that record wrong turns.** `whats-next.md`'s
   attempted_approaches section — miscounts, refuted hypotheses, environment
   gotchas — has demonstrably prevented repeated work across sessions. Most
   projects only record successes; this one's failure log is its most reused
   document.

---

## 4. Suggested order of work

| # | Item | Cost | Blocked by |
|---|---|---|---|
| 1 | §1.1 forward `slides` (+ regression test) | minutes | in-flight forks touching `cli.py` |
| 2 | §1.4 `CLAUDE.md` `--gt2reloc`; §1.3 tempo help text | minutes | nothing |
| 3 | §1.2 tempo bound/catch | minutes | nothing |
| 4 | §2.1 CI + `cli.main()` tests | ~1 h | nothing |
| 5 | §2.6 commit `tools/dis6502.py` | minutes | nothing |
| 6 | §2.3 umbrella flag + §2.4 second fixture | ~2 h | design nod on the flag name |
| 7 | §2.2 options dataclass | ~2 h | quiet tree (touches every call site) |
| 8 | §2.7 facts doc consolidation | ~1 h | nothing |
