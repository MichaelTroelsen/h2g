<original_task>
Continuation of work on **H2G**, a converter from Rob Hubbard `.sid` files to
GoatTracker `.sng`. The session opened with `read what next` against the
previous handoff (then at v0.5.135, in `C:\Users\mit\claude\h2g`) and was
driven as a sequence of single-item directives, each answered before the
next was given:

1. `read what next` → summarised the previous session's open items;
   flagged that `mcp__retrodebugger__*` tools had just become available
   and recommended using them to close work_remaining §1 (what the real
   6502 player does at Commando's `$FF` track-end marker), which the prior
   session had explicitly left open for lack of a disassembler
2. `continue` → loaded `Commando.sid` directly into RetroDebugger's C64
   core and read the live 6502 dispatch at the track-end boundary
3. `yes, do the goatwriter pacing check next` → read `gplay.c`'s player
   loop to check whether Goattracker forces its three channels back into
   lockstep
4. `yes, run that trace next` → traced the *original* against *h2g's own
   packed Commando output* over 26s, real time, both sides — found a
   defect neither of the first two checks explained
5. (root-cause investigation, no directive needed — same thread) →
   bisected the defect to one option (`max_rows=128`), found the
   mechanism, then scanned the whole corpus and found all 52 files that
   picked that option in `presets.json` are exposed
6. (asked via `AskUserQuestion`) `first check how many other corpus files
   are exposed` → the scan above
7. (asked again) `yes, implement and validate the fix` → fixed
   `patterns._slice_pattern`, added a regression test, regenerated all
   three generated artefacts, committed, pushed
8. `push it` (implicit in the same turn — the fix commit was pushed
   immediately after validation, then a further explicit `push it` after
   the W_A_R spot-check)
9. `do the W_A_R trace next` → spot-checked the fix on the corpus's
   worst-exposed file; the before/after comparison did not reproduce a
   second collapse, and that miss was recorded rather than smoothed over
10. `push it`
11. `write the whats-next.md handoff` → this document

Standing rules from `CLAUDE.md` that shaped every commit: bump the version
on every commit; regenerate `SURVEY.md`/`presets.json`/`FIDELITY.md` on a
settled tree, once, only when converter behaviour changed; never ship a
fake success; keep `Commando.sng` byte-exact; stage only project paths by
pathspec; verify a claim against a real source before stating it, and say
so explicitly when it can't be fully verified.
</original_task>

<work_completed>

## Headline

| | start (v0.5.135) | now (v0.5.142) |
|---|---:|---:|
| tests | 665 pass / 3 skip | **666 pass / 3 skip** (the skip is the same version-gate as last session — see *Current state*) |
| Commando's `$FF`/`$FE` mechanism | unconfirmed (no disassembler) | **confirmed live**, 6502 dispatch read directly |
| Goattracker channel pacing | unchecked | **confirmed independent**, from `gplay.c` |
| Commando's silence gap | described, cause unknown | **root-caused and fixed** |
| corpus files exposed to that defect | unknown it existed | **52 of 95 found exposed, then fixed to 0** |

`Commando.sid` → `Commando.sng` **byte-exact** throughout. Seven commits,
`b3c6feb`→`5e9f5ce` (v0.5.136 was the tip at session start, already
committed and pushed; this session's own commits start at v0.5.137). All
pushed to `origin/master`.

## v0.5.137 — Commando's `$FF`/`$FE` boundary, read live: it loops, and h2g already had it right

The prior session's central open question — does the real 6502 player
loop, freeze, or chain to another table when a voice's track hits
Hubbard's own end marker — needed a disassembler, which this session had
and the last one didn't (`mcp__retrodebugger__*` connected for the first
time). Loaded `Commando.sid` directly into RetroDebugger's C64 core
(`retro_load` accepts a PSID directly; no manual init/play wiring needed)
and read the per-voice track-byte dispatch at `$5086`-`$50AA`:

```
LDA ($5D),Y        ; fetch this voice's own track byte
CMP #$FF
BEQ $5099          ; -> LDA #$00 / STA $54EC,X (this voice's own read
                   ;    position) / JMP $5086 -- loop to row 0
CMP #$FE
BNE $50AA
JSR $5003 -> $5F42 ; -> LDA #$C0 / STA $5519 (a whole-tune "ended" flag,
                   ;    tested by BMI $5038) / RTS -- no loop
```

**`$FF` is a per-voice loop, nothing else** — no other table, no other
voice, no pointer reload. **`$FE` is a genuinely different, non-looping
event.** `tracks.py:222-228`'s existing version 0/1/3 encoding already
distinguished exactly this (`$FF`→loop-to-0, `$FE`→the sentinel
`legalise_restarts` treats as "ended") from the static byte patterns,
before this was ever run live — the dynamic read confirmed the static one,
there was nothing to fix. Also confirmed: the converted track lengths
(64/63/123 per voice, independently restarting) are faithful to what
`$54EC,X` being per-voice state makes true of the source.

## v0.5.138 — Goattracker paces channels independently, no forced lockstep

Next question: does Goattracker's own engine re-sync the three channels,
which would make the per-voice independence above moot in practice?
`gplay.c:304-342`'s `playroutine()` calls `sequencer(c, cptr)` once per
channel, each with its own `CHN*`; `sequencer()` (`gplay.c:959-1007`) only
advances *that* channel's `songptr` when *that* channel's `pattptr` has
just hit `ENDPATT`. No shared row/song-position variable. **Confirmed: no
lockstep.** This ruled out one candidate explanation for "the original
keeps introducing content the conversion doesn't" (per-channel drift is a
real, available mechanism) — but a per-channel-independent loop predicts
an *exact repeat* each lap, not the *silence* §7.pp had actually measured,
so it narrowed the mystery rather than closing it.

## v0.5.139 — root cause: `max_rows=128` has no headroom for an unterminated pattern

Traced the *original* against *h2g's own packed Commando output*
(`presets.json`'s options, both sides through the same `gt2reloc` +
`siddump` pair `fidelity.py` uses) over 26 real seconds, bucketed by
attacks/second. The original stays busy (7-17/s) the whole time; h2g's
own conversion matches that for ~8 seconds, then **collapses to 0-2/s for
the rest** — an actual near-total stop, not a different loop.

Bisected `presets.json`'s option set against a healthy `max_rows=94`
baseline: **`max_rows=128` alone** reproduces it (a single-step sweep from
94 to 128 is unambiguous — 94 through 127 identical and healthy, 128 alone
collapses). `patterns._slice_pattern`'s own docstring had already named
the mechanism, written before this defect was ever observed: Goattracker's
loader pre-fills a pattern buffer with an end marker from row 64 onward
and *rescans* for that byte at runtime rather than trusting the file's
declared length. Slicing at 94 is safe "by luck" (94 > 64, leaving
untouched pre-filled rows behind it); **128 is Goattracker's own
MAX_PATTROWS**, so a 128-row slice fills the whole declared buffer and
(empirically, under the real toolchain) leaves nothing safe for the rescan
to land on nearby. Confirmed structurally via a temporary debug dump of
`convert()`'s own `tracks`/`patterns` (added and reverted, not left in the
tree): Commando's 256-row source pattern splits as `94+94+68` (safe) at
`max_rows=94` but `128+128+0` (two zero-headroom slices back to back) at
128.

## v0.5.140 — confirmed the defect exposes all 52 corpus files that picked it

`presets.json` picked `max_rows=128` for **52 of the 95 corpus files** —
the optimizer's own preference (shorter orderlists), not a corner case.
Converting each with its own preset options and counting patterns that are
exactly 128 rows with a non-`ENDPATT` final byte: **all 52 exposed, zero
exceptions** — 2 to 77 affected patterns per file. Every one of those 52
`presets.json` entries was liable to the same class of collapse Commando's
was, at an unknown point in each file, invisible to a fidelity metric that
has never traced past ten seconds.

## v0.5.141 — the fix, validated against the real toolchain

`_slice_pattern` now shaves one row off any unterminated chunk specifically
when `max_len == GT_MAX_ROWS * 4` (i.e. only reachable at `max_rows==128`,
since both the CLI and `convert_patterns` already clamp `max_rows` to
`1..GT_MAX_ROWS`). No other `max_rows` value's chunking changes. Re-running
the 52-file scan finds **zero** exposed patterns. Commando's own live trace
goes from 36/32/36 attacks over 26s to **100/105/108**, against the
original's 101/106/109 — the collapse is gone, not relocated. Added a
direct unit test on `_slice_pattern` (`test_max_rows_128_never_leaves_a_
full_unterminated_slice`); full suite passed (667/2 at the time, before the
next commit's version bump re-armed the unrelated skip — see *Current
state*). `Commando.sng` (`max_rows=94`) is untouched. Regenerated
`SURVEY.md`, `presets.json` and `FIDELITY.md` — `FIDELITY.md`'s own numbers
barely moved, expectedly, since 10 seconds isn't enough trace to reach most
files' first affected pattern; recorded that explicitly rather than reading
the flat report as "the fix reached nothing."

**One honest gap, recorded rather than papered over:** `tests/
test_terminate_patterns.py`'s own `_loaded_length` — a model of the
*interactive editor's* `clearpattern()`, trusted by this project since
before this defect was found — predicts row 128 should already be safely
pre-filled with ENDPATT, the opposite of what `gt2reloc`'s packed player
measurably does. `gt2reloc` packs patterns through its own RLE packer
(`greloc.c`'s `packpattern()`) into a standalone player, which is not shown
in this session's work to share the interactive editor's flat, pre-filled
array at all — that packer's own player-side memory layout was not
re-derived. The fix is validated against the actual shipped toolchain
(`gt2reloc` + `siddump`), which is the pair that has to agree for it to
matter regardless of which C struct explains the gap — but *why* the
model and reality disagree is still open.

## v0.5.142 — spot-checked the fix on W_A_R, an honest miss

`W_A_R.sid` has the corpus's worst exposure (77 of 156 patterns) and its
default subtune references 65 of them, several within the first few
orderlist entries — the strongest candidate for a second dramatic
before/after. Traced 30s against both the pre-fix `patterns.py`
(temporarily restored from git for the comparison, then put back — see
*Attempted approaches* for the exact technique and its one hazard) and the
fixed one: **the two traces are frame-for-frame identical** — 29/25/58
attacks either way, tracking the original's 28/20/58 closely with no
silent stretch on *either* side. Recorded as a genuine miss, not
disconfirming: the runaway read's audible cost is evidently not uniform
across files, and this fix's value on W_A_R rests on the structural
guarantee (no read ever runs past a known-unsafe boundary again) rather
than a second demonstrated collapse. The other 7 subtunes' 12 remaining
hits, and this subtune past 30s, were not traced.

</work_completed>

<work_remaining>

## 1. Why does the loader model disagree with `gt2reloc`'s real behaviour?

v0.5.141's honest gap. `test_terminate_patterns.py`'s `_loaded_length`
models `gsong.c`'s `clearpattern()` (the *interactive editor's* pattern
loader) and predicts a 128-row unterminated slice is safe; live
measurement through `gt2reloc` + `siddump` says otherwise. `gt2reloc`
packs through `greloc.c`'s `packpattern()` (an RLE packer, `greloc.c:715,
749`) into a standalone player whose own runtime memory layout was not
read this session. Reading that packer and the standalone player it
builds — not the interactive editor's `gplay.c`/`gsong.c`, which is what
every citation so far in this defect's writeup actually comes from — is
the direct way to close this. Low priority: the fix doesn't depend on it,
but the method doc currently states the mechanism with a caveat instead
of confidence.

## 2. Broader audible validation of the max_rows=128 fix

Only 2 of the 52 previously-exposed files got a live before/after trace
(Commando: dramatic collapse, fixed; W_A_R: structural exposure confirmed,
no audible before/after difference in the traced window). The structural
guarantee (no unterminated 128-row slice, ever) is proven corpus-wide; the
*audible* stakes on the other 50 files are unknown — could be anywhere
from "as dramatic as Commando" to "as invisible as W_A_R's traced window."
Not urgent (the fix is unconditionally safe either way), but worth knowing
before citing this as having "fixed 52 files' worth of real defects" versus
"fixed 52 files' worth of latent risk."

## 3. Carried forward from last session, untouched this one

- **Commando's `.frm` player is confirmed to loop, not chain — but the
  original composition's own audible "keeps introducing content" behaviour
  is still not tied to a specific mechanism.** Both v0.5.137 (mechanism)
  and v0.5.138 (pacing) came back "faithful, no bug here," and v0.5.139-141
  found and fixed a real but *different* defect (the silence gap) instead.
  Whether Commando's audible divergence, once the silence gap is fixed, is
  now fully explained or whether something is still left over needs a
  fresh listening/spectrogram pass against the *current* (fixed) build —
  not attempted this session.
- **The drum sweep under-render** (§7.ii) — the obvious fix (loop
  `CMD_PORTADOWN` back onto itself) is closed off (§7.oo): it has no floor
  and Commando's own ordinary content underflows it after 175 frames. A
  real fix needs either per-note info threaded into the wavetable build, or
  a pattern-level `CMD_TONEPORTA` encoding (bigger, touches `patterns.py`).
- **Gerry_the_Germ's apparent missing rise effect** — flagged from last
  session's spectrogram pass (four clear rising sweeps in the original's
  opening, none in h2g's), not verified against this file's actual
  detected bits, not fixed either way.
- **Bump_Set_Spike/Gerry_the_Germ's compressed dynamics** — σ dB collapse
  confirmed numerically and visually, root cause not investigated.
  Candidates: ADSR release/sustain difference, gate-hold difference, or a
  legato/note-length effect the register dimensions can't see.
- **The listening-pass tooling** (spectrogram script) from two sessions
  ago was scratch and is gone; a real audio-capable second opinion (the
  OpenAI-pilot plan) is still just a plan, gated on explicit consent.
- **The ~50 unverified restart-screen candidates** from §7.pp — 0 of 5
  verified as real defects, not proof the rest are clean.
- **`_rate_shift` exact only for powers of two**, **`OUTER_GATE`'s
  narrower dialects**, **ACE II/Auf Wiedersehen Monty's two unencoded
  per-instrument wave programs**, **Spellbound's `--pace` residual** — all
  named in the prior handoff, none touched.

</work_remaining>

<attempted_approaches>

## What worked this session — reusable techniques

1. **Live 6502 disassembly via RetroDebugger, on a `.sid` loaded directly.**
   `retro_load` accepts a PSID file with no manual init/play wiring; the
   emulator starts running it immediately. `retro_search_pattern` (mnemonic
   patterns like `"CMP #$FF"`, `executedOnly` toggle) found the exact
   dispatch point in two calls rather than a manual disassembly crawl. This
   was unavailable last session and directly unblocked work_remaining §1.
2. **A temporary debug-dump hook in `convert.py`, added and reverted every
   time.** `os.environ.get("H2G_DEBUG_DUMP")` gated a one-line pickle dump
   of `tracks`/`new_patterns` right after the point of interest, run via a
   throwaway script, then `git checkout -- convert.py` immediately after.
   Used three separate times this session (single-file structural compare,
   corpus-wide scan, post-fix corpus re-scan) with zero leakage into the
   tree — confirmed clean each time before moving on. Faster and more
   reliable than reimplementing convert()'s internal pipeline by hand.
3. **Restoring a file's pre-fix content from `git show <rev>~1:path` for a
   live before/after, then restoring the fix from a session-local backup
   copy.** Used for the W_A_R comparison. **The hazard**: this edits a
   tracked file on disk without `git add`/commit, so `git status` shows a
   real (if temporary) modification the whole time the comparison runs —
   check status immediately after restoring, and keep the "restore the fix
   back" step as its own explicit command, not folded into a longer chain
   that could be interrupted mid-way (the same class of risk this repo's
   own `CLAUDE.md` already flags for `git stash` + a killed background job).
4. **Bisecting an option set against a known-healthy baseline, one flag at
   a time then in combination, before trusting a correlation.** The first
   pass (individual `presets.json` flags against a `max_rows=94` baseline)
   found nothing; only leave-one-out *from the full broken combination*
   isolated `max_rows`. Both were needed — the first ruled out simple
   single-flag causes, the second found the real one.
5. **A single-step parameter sweep (94, 100, 110, 120, 126, 127, 128) as
   the actual proof**, not the leave-one-out result. Leave-one-out said
   "removing max_rows fixes it"; the sweep is what showed the boundary is
   *exactly* 128, ruling out "any high max_rows" or "specifically 128 as an
   exact multiple of something in this file" as alternate explanations.

## A wrong turn worth keeping in the record

**Asserting a specific C-level memory mechanism ("the buffer has zero
headroom, contiguous pattern arrays, the overrun lands in the next
pattern's slot") as settled fact, before checking it against the project's
own existing model.** `test_terminate_patterns.py`'s `_loaded_length`
(already in the repo, trusted, and now known to have been written before
this defect existed) predicts the opposite of what was about to be
written up as confirmed. Caught by re-reading that test file before
finalizing the doc — not by anticipating the conflict. The fix and its
empirical validation stand regardless (they don't depend on the
mechanism's exact micro-detail), but the writeup was corrected to say "the
real toolchain measures X; here is a documented, trusted model that
disagrees; the discrepancy is open" instead of asserting the confident
wrong story. **Lesson**: when a plausible mechanism explains a measured
result, check whether anything already in the repo has modeled the
adjacent case before treating the plausible explanation as the verified
one — the same "validate against a case you already understand" discipline
this repo has already learned twice before (the periodicity detector, the
`--vice` denominator), applied here to a written explanation rather than
a new tool.

## Tooling notes

- `fidelity.py`'s internal helpers (`F._preset_opts`, `F._preset_multiplier`,
  `F.convert`, `F.legalise_restarts`, `F.pack_sid`, `F.run_siddump`,
  `F.resolve_subtune`) are directly importable and reusable for one-off
  traces without going through the CLI — `resolve_subtune(sid, "auto")`,
  not `resolve_subtune(sid, None)` (the latter throws; `"auto"` is the
  sentinel the function actually checks for).
- `Trace` is a `list` subclass, not an object with a `.voices` attribute —
  index it directly (`trace[0]`, `trace[1]`, `trace[2]`) or iterate it.

</attempted_approaches>

<critical_context>

## Where things are

| | |
|---|---|
| **Repo (work here)** | `C:\Users\mit\claude\h2g` → github.com/MichaelTroelsen/h2g |
| Corpus (95 files) | `C:\Users\mit\claude\c64server\SIDM2\SID\Hubbard_Rob`, or `H2G_CORPUS` |
| `gt2reloc.exe` | `C:\Users\mit\Downloads\GoatTracker_2.77\win32\`, or `H2G_GT2RELOC` |
| GoatTracker source | `C:\Users\mit\Downloads\GoatTracker_2.77\src\` (`gplay.c`, `greloc.c`, `gsong.c` referenced but not read this session) |
| VICE 3.9 (`vsid`) | `C:\Users\mit\Downloads\GTK3VICE-3.9-win64\GTK3VICE-3.9-win64\bin\`, or `H2G_VSID` |
| **RetroDebugger MCP** | `mcp__retrodebugger__*` — connected this session for the first time; loads a `.sid` directly via `retro_load`, no manual PSID wiring. Stopped cleanly at session end (`retro_stop_platform`, platform `c64`). |
| `siddump-rt` | `python/tools/siddump-rt/` — already built (`siddump.exe` present); needed for any multiplier > 1 trace |
| Short scratch | `C:\t\` (gt2reloc's 60-byte filename buffer) |
| gcc | `C:\Users\mit\Downloads\w64devkit\bin\` |
| Session scratchpad (does **not** persist) | `C:\Users\mit\AppData\Local\Temp\claude\...\scratchpad` — this session's trace scripts (`trace_commando.py`, `trace_war.py`) live only here |

## Invariants

- **`Commando.sng` byte-exact.** `--max-rows` 94 and `--format` gts2 stay
  the defaults, and this session's fix is gated on `max_rows==128`
  specifically, so it cannot touch the fixture.
- **Bump the version every commit**; regenerate all three artefacts on a
  **settled** tree, once, in the order survey → presets → fidelity —
  **only when converter behaviour actually changed**. v0.5.137, .138,
  .139, .140 and .142 are investigation/doc-only and correctly did not
  regenerate; v0.5.141 (the actual fix) did.
- A new `convert()` option is inert until it is in **four** places: the
  signature, `presets.FIXED`, the hand-written `always` dict, and (if it
  moves the rate) `pack_multiplier`. Not touched this session — the fix
  changed `_slice_pattern`'s internal chunking, not any option's surface.
- **Validate any new automated check, or any newly-written mechanism
  explanation, against a case you already understand (or a model the
  repo already trusts) before treating it as settled** — this session's
  own version of a lesson the repo has now learned three times (the
  periodicity detector, the `--vice` denominator, and now the
  `clearpattern()`/`gt2reloc` mismatch above).

## Verified facts (new this session)

- `gplay.c:5086`-`50AA` (Commando's own relocated address space, read via
  RetroDebugger): `$FF` in a voice's track resets *that voice's own*
  `$54EC,X` to 0 and loops; `$FE` sets a whole-tune flag at `$5519` and
  does not loop. (Note: these are addresses inside `Commando.sid`'s own
  memory image, not `gplay.c`'s line numbers — the player code here is
  Rob Hubbard's original, not Goattracker's.)
- `gplay.c:304-342`, `959-1007`: `playroutine()`/`sequencer()` advance each
  channel's `songptr` independently; no shared position variable.
- `gplay.c:918-919`, and the two other `pattlen[]` references at lines 231
  and 1001 (the *only* three in the file): Goattracker's row-tick hot path
  never consults a pattern's declared length, only the ENDPATT byte.
- `patterns.py`'s `GT_MAX_ROWS` (128) is the only value `max_rows` can take
  that is unsafe when unterminated, confirmed by a single-step sweep
  94-128; every other value in that range chunks identically to before
  this session.
- All 52 `presets.json` entries with `max_rows: 128` had at least one
  affected pattern before the fix (2 to 77 each); zero after.

## Commands

```sh
cd python
python -m pytest tests/ -q                                    # 666 pass, 3 skip (see Current state)
python fidelity.py <corpus> -t 10 --presets ../presets.json -o ../FIDELITY.md
python survey.py <corpus> -o ../SURVEY.md --legal-restart --gt2reloc
python presets.py <corpus> -o ../presets.json
python bump_version.py "description"                          # before staging any commit
```

For a one-off live trace (pattern used three times this session):
```python
import sys; sys.path.insert(0, r"C:\Users\mit\claude\h2g\python")
import fidelity as F, json, shutil
from pathlib import Path
doc = json.load(open(r"C:\Users\mit\claude\h2g\presets.json"))
opts = F._preset_opts(doc, "<Name>.sid"); mult = F._preset_multiplier(doc, "<Name>.sid")
sng = F.convert(str(sid_path), log=lambda m: None, **opts)
sng, _ = F.legalise_restarts(sng)
packed = F.pack_sid(sng, workdir, F.GT2RELOC, mult)
shutil.copyfile(sid_path, workdir / "o.sid")
a = F.run_siddump(workdir / "o.sid", seconds, F.resolve_subtune(sid_path, "auto"), F.SIDDUMP, 0)
b = F.run_siddump(packed, seconds, F.resolve_subtune(sid_path, "auto"), F.SIDDUMP, calls=mult)
```

</critical_context>

<current_state>

## Everything is committed and pushed; tree clean

- **`h2g` `master` = `5e9f5ce`, v0.5.142**, public, pushed. Working tree
  clean.
- **666 tests pass, 3 skipped.** `Commando.sng` byte-exact. The skip count
  matches last session's handoff exactly (`test_preset_passthrough`'s
  version-gate) — it briefly cleared to 2 right after v0.5.141 regenerated
  `presets.json`, then re-armed itself at v0.5.142's version bump, exactly
  as documented: it clears whenever artefacts are regenerated for a real
  reason and re-arms on every version bump in between. Not a regression.
- `SURVEY.md`/`presets.json`/`FIDELITY.md` are current as of **v0.5.141**
  (the fix commit) — not v0.5.142 (doc-only).
- No scratch/investigation files leaked into the repo tree. Three separate
  temporary debug-dump hooks in `convert.py`, and one temporary
  git-restore of `patterns.py`, were each added/used/reverted within a
  handful of commands and confirmed clean via `git status`/`git diff
  --stat` before moving on every time.

## Two things a fresh session must know first

1. **RetroDebugger (`mcp__retrodebugger__*`) is connected and works well
   for this project.** `retro_load` takes a `.sid` directly; no PSID
   header parsing or manual init/play wiring needed. If a future
   work_remaining item needs "what does the real 6502 player actually do
   here," reach for this before assuming it's unanswerable — that
   assumption held for at least one prior session and was wrong.
2. **A structural defect confirmed present is not the same as an audible
   defect confirmed present** (v0.5.142's W_A_R result). The `max_rows=128`
   fix is unconditionally correct and provably closes a real hole, but
   only 2 of the 52 previously-exposed files have an actual before/after
   audio-adjacent trace, and they disagree on how audible the bug was.
   Don't cite "fixed 52 files" as "52 files now sound different" without
   checking — cite it as "52 files no longer carry a proven-unsafe read."

## Open questions carried forward

- Why does `test_terminate_patterns.py`'s `clearpattern()` model disagree
  with `gt2reloc`'s real behaviour at exactly `max_rows==128`? (work
  remaining §1 — needs `greloc.c`'s `packpattern()` and whatever standalone
  player it builds, not `gplay.c`/`gsong.c`)
- Is the `max_rows=128` fix audible on the other 50 previously-exposed
  files, or structural-but-silent like W_A_R? (§2)
- With the silence gap now fixed, does Commando's conversion still
  audibly diverge from the original past ~8s, or was the silence gap the
  whole story? (§3, needs a fresh listening/spectrogram pass against the
  current build — the last spectrogram tooling was scratch and is gone)
- All the smaller carried-forward items from two sessions ago, still
  untouched: drum sweep, Gerry_the_Germ's rise effect and dynamics
  compression, `_rate_shift`, `OUTER_GATE` dialects, the two unencoded wave
  programs, Spellbound's `--pace` residual.

</current_state>
