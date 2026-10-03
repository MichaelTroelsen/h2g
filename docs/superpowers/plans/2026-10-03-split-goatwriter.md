# Plan: split `python/h2g/goatwriter.py` into a package of modules

Status: PLAN ONLY, not started. Written 2026-10-03 at HEAD `8b86184` (v0.5.502).
Every figure below was measured on that tree; re-take them before starting if
HEAD has moved (the scripts are named, so this is one command each).

## Why

`goatwriter.py` is 13,683 lines: 207 functions, 10 classes, 128 module-level
assignments. 90 of the 191 open tasks in `.claude/tasks/whattask.json` write it,
so `/runqueue` can never run two converter subtasks at once: every one of them
conflicts with every other on this one path. Removing `goatwriter.py` (and the
blanket `r:python/h2g` read) from the conflict arithmetic is what turns 43 of
the 191 tasks parallel; removing `python/tests` alone turns 0
(measured 2026-10-03 over the plan's `touches`).

## The one rule

**The split moves text. It changes no behaviour, no name, no signature, no
emitted byte, no log line.** Anything that is not a move or an import line is
out of scope and goes in a separate, later commit. If a step needs anything
else to pass its gates, the step is wrong: stop and re-plan, do not adapt the
code to the test.

## Measured facts the plan rests on

Scripts (read-only, scratch): `C:/t/split/defs.py` (definitions, line ranges,
who references whom), `C:/t/split/usage.py` (who imports goatwriter, how),
`C:/t/split/clusters.py` (proposed modules, cross-references, cycles).

- **66 files import goatwriter.** By name they import 191 different names, 72
  of them private (`_wavetable_entries`, `_note_freq`, ...). 74 names are read
  as `goatwriter.X` attributes. Every one of these must keep working unchanged.
- **Inside `h2g`, four modules import it at load time:** `cli.py`,
  `convert.py`, `instrument_drop.py`, `patterns.py`. `patterns.py` imports
  `CMD_SETTEMPO`, `CMD_SETWAVEPTR` and `PulseVoiceCell` from goatwriter, while
  goatwriter imports `patterns.past_table_rests` LAZILY inside
  `past_table_drum_plan`. That lazy import is what keeps the cycle from
  forming. It must stay lazy, and its relative depth changes (`.patterns`
  becomes `..patterns`).
- **Nine names are replaced by tests with `monkeypatch.setattr(goatwriter,
  ...)`:** `_lay_out_pulse`, `budget_pulse_phase_commands`, `find_song_speeds`,
  `fixed_arp_counter_base`, `fixed_arp_counter_gated`, `fixed_arp_first_fetch`,
  `fixed_arp_mask`, `legato_tie_family`, `pulse_usage`. **This is the most
  dangerous part of the split.** Today the patch works because caller and
  callee share one module namespace. After the split, patching the package
  attribute does NOT reach a caller in another module, and the test may still
  PASS with the patch silently dead. `find_song_speeds` is called from four of
  the proposed modules, `fixed_arp_mask` from three.
- **Two tests read `goatwriter.py` as text:** `tests/test_pulse_phase.py`
  (asserts the call ORDER inside `build_sng`, and that `class PulseBoundsSim`
  and `def pulse_bounds_sims` exist in the file). Moving the text breaks
  their file path, not their meaning.
- **No `global` statements, no `__file__`/`__module__` use** inside
  goatwriter, so moving a function cannot change which module-level state it
  writes. 12 module-level values are built from a list, dict, set or call;
  each is defined once and moves once.
- **Tooling keys on the directory, not the file.** `artefact_freshness.py`
  watches `python/h2g/` (excluding only `python/h2g/__init__.py`, the version
  file), and `.claude/hooks/artefact_guard.py` checks `python/h2g/` dirtiness.
  A package `python/h2g/goatwriter/` is covered by both unchanged.
- **The proposed layering is acyclic** once 15 small leaf helpers move into one
  low-level module (`primitives`). Without that, seven of the modules form one
  import cycle through those helpers.

## Target layout

`python/h2g/goatwriter.py` becomes the package `python/h2g/goatwriter/`.
Line counts are approximate (definition bodies; comments travel with the
definition they precede).

| module | ~lines | what moves there (original line range) |
|---|---:|---|
| `constants.py` | 150 | every UPPER_CASE module constant, wherever it sits today |
| `primitives.py` | 370 | `_wave_byte`, `_note_freq`, `_wave_hold_byte`, `_freq_table_note`, `_speed_index`, `_rate_shift`, `_first_frame_entry`, `_first_frame_lead`, `_sfx_note_byte`, `_gate_calls`, `_counter_gate_call`, `_fixed_pitch_yield_field`, `_arp_relative`, `_fixed_arp_block`, `fixed_arp_mask` |
| `hard_restart.py` | 175 | `_hard_restart_ticks` and its neighbours (203-383) |
| `instruments.py` | 350 | header, name and field bytes, `_write_instruments`, `record_envelope` (3454-3833) |
| `tempo.py` | 580 | tempo, song speeds, outer gate, multipliers, `find_song_speeds` (2615-3453) |
| `notes.py` | 340 | note and pitch-sequence entry helpers (384-834) |
| `attack.py` | 730 | fixed attack, two-stage, alternate-wave and fixed-hold entries (835-1699) |
| `drums.py` | 300 | arp block, sfx drum entries (1700-2109) |
| `wave_program.py` | 390 | wave program entries and travel (2110-2614) |
| `vibrato.py` | 680 | classic, triangle and table vibrato entries and layout (3834-4553) |
| `note_passes.py` | 1280 | instrument entry, ties and legato clones, vibrato command pass, attack hold, past-table drum, expanding vibrato (4554-6085) |
| `arpeggio.py` | 2170 | fixed arp, pitch-seq clock and phases, tempo duty split, nibble arp (6086-8576) |
| `wavetable.py` | 1560 | `_wavetable_entries`, drum entries, `_wavetable_layout` (8577-10175) |
| `pulse.py` | 1430 | pulse programs, triangle walk, phase sims, pulse layout and budget (10176-11778) |
| `filters.py` | 710 | filter steps, ILV routing, classic clearing (11779-12766). Named `filters`, not `filter`, so it never shadows the builtin |
| `build.py` | 510 | `build_sng` and its last-mile helpers (12767-13324) |
| `append_song.py` | 320 | appending one song's subtunes to another (13325-end) |
| `__init__.py` | — | the original module docstring, then explicit re-exports of EVERY name the old module had (see below) |

Import order, leaves first (each imports only from modules to its left):
`constants` → `hard_restart` → `instruments` → `append_song` → `primitives` →
`tempo` → `arpeggio` → `attack` → `pulse` → `filters` → `note_passes` →
`vibrato` → `drums` → `notes` → `wave_program` → `wavetable` → `build`.
This order comes from the reference graph; re-derive it with
`clusters.py` rather than trusting it if any definition moved since.

`arpeggio.py` (2,170 lines) and `wavetable.py` (`_wavetable_entries` alone is
854 lines) stay large. Splitting them further is a second, optional phase
with its own baseline. It is not part of this plan.

## How the facade keeps every caller working

`goatwriter/__init__.py` re-exports, by explicit name, every name the old
module's namespace held, private ones and imported ones included (`dir()` of
the old module minus dunders, captured in the baseline). A star import is not
enough: it skips `_private` names, and 72 private names are imported by
tests. So all 66 importers keep `from h2g.goatwriter import X` and
`goatwriter.X` unchanged, and every re-exported object `is` the object in its
defining module.

## The monkeypatch hazard and its fix

1. Inside the package, every caller of the nine patch-targeted names that
   lives in a DIFFERENT module from the definition calls it through the
   defining module's attribute (`from . import tempo` then
   `tempo.find_song_speeds(...)`), never through a `from .tempo import
   find_song_speeds` binding. Callers in the same module need no change. These
   are the only call sites whose text changes, apart from import lines; the
   execution script lists every one it rewrites.
2. The tests that patch them change their target from the facade to the
   defining module (`monkeypatch.setattr(goatwriter.tempo,
   "find_song_speeds", ...)`). Their assertions do not change.
3. A new guard test fails if any test calls `setattr`/`monkeypatch.setattr`
   on the `h2g.goatwriter` package itself for a function. A patch on the
   facade is now a no-op, so it must be impossible to write one by accident.
4. Each of those tests is checked to be LIVE after the split: with its patch
   line removed it must FAIL (a vacuous pass is the failure this hazard
   produces). That is the sabotage check for this step.

## Baseline, captured BEFORE anything moves (gate G0)

On a clean tree at the starting HEAD, written to a scratch dir outside the repo:

1. **Full suite**: `python -m pytest tests/ -q`, failures named (expect 0).
2. **Converted bytes**: sha256 of `convert()` for all 95 corpus files under
   (a) shipped presets (`fidelity._preset_opts`), (b) defaults, and
   (c) every `convert()` option forced on alone (one run per option over the
   corpus). (c) is what reaches the code paths no preset exercises. Refused
   files are recorded with their exception text.
3. **Log lines**: the full `log=` output of every conversion in 2(a) and
   2(b), because tests assert on log text.
4. **Packed .sid**: sha256 of `pack_sid` output for 2(a), and
   `Commando.sng` compared byte-for-byte (`tests/test_commando.py`).
5. **Fidelity rows**: `fidelity.py --jobs 16 --sound` over the corpus into
   scratch (warm cache, about 90 s); every field except `measure_seconds`,
   `label` and `version` is the reference.
6. **Public surface**: for every name in `dir(h2g.goatwriter)`, its type, its
   `inspect.signature` for callables, and a hash of its docstring.

## Steps

Work on a branch (`refactor/split-goatwriter`) from a pushed, clean `master`,
with NO drain or agent running against the tree. 90 open tasks touch this
file, and a concurrent edit would be a merge disaster. One commit per step,
so any step can be bisected or reverted alone.

1. **Write the extraction script** (scratch, not committed). It reads
   `goatwriter.py` with `ast`, assigns each top-level statement to a module by
   the table above, and copies each statement's EXACT source text, including
   the comment block and blank lines above it, into that module in the
   original order. For each module it then writes:
   - `from __future__ import annotations`;
   - only the stdlib and `..detect` / `..search` / `..sidfile` imports the
     module uses, computed from names;
   - explicit `from .x import a, b` lines for names from sibling modules,
     except the nine patch-targeted names, which go through module attributes
     (see above).

   It writes `__init__.py` with the original docstring and the explicit
   re-export list, and rewrites the one lazy import's relative depth. It
   refuses to write if any name is unassigned, assigned twice, or creates an
   import cycle.
2. **Dry run into a scratch copy of the package** and run gate G1 there
   (below) before touching the repo.
3. **Apply in the repo**: `git mv python/h2g/goatwriter.py
   python/h2g/goatwriter/build.py` first, so `git log --follow` keeps the
   history on the module that keeps `build_sng`. Then write the generated
   modules over it. Commit: "split goatwriter.py into a package (moves
   only)".
4. **Re-point the nine monkeypatches and the two source-reading tests**, and
   add the facade-patch guard test. Commit separately, so the code move and
   the test changes can be reviewed apart.
5. **Run G1 in full.** Only then bump the version (`bump_version.py`) and do
   the routine regeneration. SURVEY.md and presets.json must move ONLY their
   version stamp. Any byte count moving is a failed gate.

## Gate G1: what "nothing broke" means, checked after step 2 and again after step 5

Every item compared with G0. All must hold; one failure stops the work.

- [ ] Full suite: the same results as G0 (0 failed), plus the new guard test.
- [ ] Converted bytes identical for every file under presets, defaults and
      every forced option (2a-2c); the same files refused with the same
      exception text.
- [ ] Log lines identical, line for line (3).
- [ ] Packed .sid hashes identical; `Commando.sng` byte-identical (4).
- [ ] Fidelity rows identical in every field but timing and stamps (5).
- [ ] Public surface identical: same names, types, signatures and docstring
      hashes, and for each name `goatwriter.X is goatwriter.<module>.X` (6).
- [ ] `python -m h2g Commando.sid -o x.sng` and the `.\convert.ps1` /
      `.\play.ps1` wrappers produce identical bytes.
- [ ] `python -c "import h2g.patterns, h2g.convert, h2g.cli, fidelity,
      presets, listen, abpage"` imports cleanly (the `patterns` ↔ goatwriter
      cycle stays closed).
- [ ] Sabotage: removing each re-pointed test's patch line makes that test
      FAIL (proves the patch is live), the removed line printed from disk.
- [ ] The extraction script's own checks: every top-level name assigned
      exactly once, and the concatenated module bodies contain every
      non-import source line of the original (a line-multiset comparison, so
      no comment or blank line is lost).

## Rollback

Each step is one commit on a branch, and `master` is not touched until G1
passes, so rollback is `git checkout master` and deleting the branch.
Nothing in `build/`, `presets.json` or the docs is regenerated before G1
passes.

## After the split (separate commits, not part of the move)

- **CLAUDE.md**: the module table gains the package's modules, and the rule
  "a new `convert()` option ... `goatwriter.py`" names the module. Comments
  and docs that cite `goatwriter.py:NNNN` line numbers (24 such citations
  today) are stale either way. Citing by name is the repo's own rule;
  re-point them in a doc pass.
- **The plan**: re-run `/whattask`, so tasks declare the module they write
  (`rw:python/h2g/goatwriter/pulse.py`) and the specific modules they read,
  instead of `rw:python/h2g/goatwriter.py` plus `r:python/h2g`. This is the
  step that actually buys the parallelism.
- **`graphify update .`** and a tokensave re-index, so the code graph sees the
  new files.
- **`H2G-CONVERSION-METHOD.md`** names modules where it names the file.

## Cost and risk

- **Work:** the move itself is mechanical (a script). The cost is in the
  gates: the forced-option byte sweep (95 files × about 40 options) is the
  longest step, and the fidelity check is about 90 s.
- **Residual risk the gates cannot see:** code that looks a name up
  DYNAMICALLY (`getattr(goatwriter, name)`, `globals()[...]`) inside the old
  module. Checked at `8b86184`: no `global` statements, no `globals()`,
  `locals()`, `__dict__`, `importlib`, `eval` or `exec`. The five `getattr`
  calls all read attributes of data objects (`f.denominator`,
  `sid.pack_multiplier`, `sid.start_song`, `patterns.note_bit7`,
  `patterns.decoded`), not module names. Re-run that grep at the start; any
  new hit on a module object is a stop-and-re-plan.
- **What it buys:** converter tasks stop conflicting by default, and a
  13.7k-line file becomes 17 files of 150-2,200 lines.
