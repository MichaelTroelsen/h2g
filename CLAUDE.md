# CLAUDE.md

Guidance for Claude Code working in this repository.

**This file is an index of rules. The evidence is in `docs/LESSONS.md`** — the
verbatim 2300-line predecessor of this file, archived at v0.5.475, holding every
measured figure, worked example, retraction and grading pass behind the rules
below. It is not auto-loaded. Wording was preserved across the split, so a grep
for a rule's phrasing here lands on its evidence there.

When you learn something durable, write the **rule** here and its **evidence**
in `docs/LESSONS.md`. A rule with no numbers in it does not decay; a number
written in the present tense does.

---

## What this is

H2G ("Hubbard 2 Goattracker") converts C64 `.SID` files containing Rob Hubbard's
music into Bitops Goattracker (`.sng`, v2.34+) format. Originally a VB6 tool by
Stilianos "Stello" Doussis (Aug 2005), released free/open source.

It is a **signature-based disassembly ripper**: it does not emulate the 6502. It
scans the raw SID bytes for known 6502 opcode fingerprints specific to each Rob
Hubbard player-engine variant, uses matches to locate the instrument table,
pattern table and track table, then re-encodes that data as Goattracker's binary
song format. It therefore only works on files whose player matches a hard-coded
signature.

User-facing docs: `README.md` (usage, options, versioning, testing) and
`H2G-CONVERSION-METHOD.md` (how the method works — used as reference material by
another project, so keep it current).

## Repository layout

- `python/h2g/` — **active development target**, a from-scratch Python CLI port.
- `VB6 Sourcecode/h2g.frm` — the original VB6 app (~1300 lines), the reference
  implementation the port was derived from and is verified against. `.frx` is
  VB6's binary resource companion; `.vbp`/`.vbw` are project files.
- `arkiv/` — archived VB6 build and sample `.sid` files.
- `Commando.sid` / `Commando.sng` — the byte-exact regression pair.
  `Commando.sng` came from `h2g.v1.2.exe`; the port must reproduce it byte for
  byte (`python/tests/test_commando.py`). It is the project's only fidelity anchor.
- `docs/LESSONS.md` — the evidence archive described above.

The VB6 side has no build script, tests or CI. Its architecture is summarised at
the end of this file.

## Python port

Plain-stdlib Python 3, no third-party runtime deps (`pytest` is dev-only).

- Run from `python/`: `python -m h2g <input.sid> [-o out.sng] [-q]`.
  From the repo root, `.\convert.ps1` wraps it; `.\play.ps1` also opens the result.
- Test: `python -m pytest tests/ -q` (from `python/`). Treat any output-changing
  edit as a regression unless it is an intentional feature — then update the
  fixtures, never delete the assertion.
- `python -m h2g --help` is the authoritative option list. Do not restate it here.

Module layout mirrors the VB6 pipeline 1:1:

| Module | Role |
|---|---|
| `sidfile.py` | PSID/RSID header parsing (`load_sid`); `find_relocation` (players that move themselves at init, e.g. I Ball); `find_init_writes` (table addresses written over the code at init, e.g. Devils Galop); `find_freq_table` (locates the player's note table and places it against Goattracker's) |
| `search.py` | wildcard opcode-pattern search (`search_file`, port of `SSearchfile`) |
| `detect.py` | player-engine signature chains → a `Detection` dataclass |
| `tracks.py` | `convert_tracks`; `apply_initial_instruments` |
| `patterns.py` | `convert_patterns`, `reindex_tracks`, pattern slicing, tempo application |
| `goatwriter.py` | `build_sng` — assembles the final `.sng` byte buffer |
| `convert.py` | orchestrates the above into `convert(sid_path) -> bytes` |
| `cli.py` / `__main__.py` | argparse entry point |

Where the port had to reason through non-obvious VB behaviour (off-by-one loops
reading one past written data and relying on implicit zero-fill), the equivalence
is explained at the point it matters — see `patterns._slice_pattern`. **If the
Python comments and `h2g.frm` ever appear to disagree, re-derive from the VB6.**

Two `sidfile.py` rescues (`find_relocation`, `find_init_writes`) and two
`detect.py` ones (`INSTRUMENT_INDEX_SHAPE`, `_find_table_vibrato`) are consulted
**only when the primary path found nothing**. That ordering is the rule: a rescue
may save a file that reads nothing and must never disturb one that reads correctly.

## Every commit

1. **Bump the version — on every commit, not just releases.**
   `python python/bump_version.py "short description"` before staging, then
   regenerate any doc embedding the version. See README § Versioning.
2. **Regenerate the routine artefacts**, in this order, from `python/`:
   ```sh
   python survey.py <sid_dir> -o ../docs/SURVEY.md --legal-restart --gt2reloc
   python presets.py <sid_dir> -o ../presets.json
   ```
   - `--gt2reloc` is what fills the pack-back column *at all*; omit it and the
     column is silently empty. `--legal-restart` is part of the same command
     because without it `greloc.c:244` refuses every tune ending on Hubbard's
     `$FE`, so the column would measure the option's absence.
   - Regenerate **after** the tree is coherent and the tests pass, never
     mid-edit: a run taken half-applied records a state that never existed.
   - `presets.json` is the easy one to forget because it is not human-facing —
     but it is what `--presets` applies, so a stale entry silently converts a
     song with the wrong options.
   - `presets.py --fidelity` traces four emulations a song; it is not part of the
     routine command. A plain run **carries forward** what `--fidelity` recorded
     and prints how many. `--no-carry`, or a missing output file, drops them.
     A **sharded** run requires `--carry-from` and refuses without it.
3. **Update the hand-written docs in the same commit.** `README.md`, this file
   and `H2G-CONVERSION-METHOD.md` are not generated. If a change alters
   behaviour they describe, the edit belongs in the same commit. Docs that drift
   are worse than absent ones.
4. `graphify update .` — see the graphify section.

**On demand, not every commit:** `FIDELITY.md`, then `QUEUE.md` in the same pass,
from `python/`:
```sh
python fidelity.py <sid_dir> -t 180 --presets ../presets.json --sound \
    --census ../build/onset_census.md --hold-census ../build/hold_census.md \
    --json ../build/fidelity.json -o ../docs/FIDELITY.md
python fidelity_queue.py --from-json ../build/fidelity.json -o ../docs/QUEUE.md --json ../build/queue.json
```
**`--json` is not optional**: without it `fidelity.py` writes only the report,
`build/fidelity.json` keeps its old stamp and `QUEUE.md` and
`tests/test_output_sha.py` read the stale one -- measured at v0.5.481, when the
first regeneration left Powerplay's old sha in the JSON under a fresh header.
`--sound` and the two census flags are what the current artefact carries;
`.claude/hooks/flag_guard.py` refuses a re-run that would drop them.
Regenerate after a commit that changes what the converter emits, and never from a
tree with unrelated edits in `h2g/`. `QUEUE.md` reads that same
`build/fidelity.json`, so it is only as fresh as the run before it and belongs
immediately after, never before. Each run gets its own scratch directory since
v0.5.66, so two can run at once; pass `--workdir` only to keep intermediates, and
never the same one twice concurrently.

`python listen.py <sid_dir> --from-json ../build/fidelity.json` stages WAV pairs
for a human listening check into gitignored `build/listen/`.

## Hard invariants

- **`--max-rows` defaults to 94. Do not change the default.** It is what the
  byte-exact fixture encodes.
- **Check the fixture's bytes, not its length.** `len(convert(...)) == 15193`
  passes for any edit that moves a byte between two wavetable entries. Compare
  `got == ref` against `Commando.sng`.
- **Opening output in GoatTracker requires `--format gts5`.** The legacy GTS2
  importer overruns its pattern array on the portamento commands this converter
  emits: a GTS2 file loads and then crashes on play. `gts2` stays the default
  because the fixture encodes it; `play.ps1` defaults to gts5.
- **Packing passes `gt2reloc -O0`.** Its pulse-optimization skipping is
  default-on and makes the packed player execute no pulse table on the note-fetch
  tick. All three packing sites pass it. Measurements taken before v0.5.189 are
  not comparable to later ones.
- **Packing back to a `.sid` needs `--legal-restart`.** Off by default (it
  changes the fixture's bytes); `presets.json`'s `always` block sets it.
  `gt2reloc`'s error path goes to a console that does not exist headless —
  **test for the output file, never the exit code.**
- **`patterns.MAX_PATTERNS` is 208** (GoatTracker's `MAX_PATT`). Every appender
  must respect it. A file one pattern over is not unpackable, so nothing
  announces it — it silently runs the default tick instead of its own
  `CMD_SETTEMPO`.
- **Row 0's command column belongs to the subtune's clock.** `apply_tempos`
  skips a pattern whose command column is occupied, so a row-0 command costs
  that subtune its `CMD_SETTEMPO`. A new row-0 command must declare itself in
  `patterns.TEMPO_OVERWRITABLE` **as well as** `ONE_SHOT_COMMANDS` — they are
  different questions and the second one looks like a catastrophe.
- **A rate read out of a player is per frame; every Goattracker table steps per
  play call.** They agree only at `-S1`, and most preset songs pack above it.
  Anything new carrying a rate must be divided by `multiplier` where it is
  encoded. **The list of emitters obeying this is a checklist to re-run against
  the tree, not a record to append to** — grep for what writes a rate byte, not
  for what already calls `multiplier`. Encode against the loop that consumes it:
  a wavetable delay entry is current for `value + 1` calls
  (`gplay.c:697-704`); `tests/test_call_rate.py` transcribes that loop.
- **The multiplier belongs to our side only.** Trace the original at `-m1` and
  the conversion at `-m{multiplier}`.
- **A new `convert()` option is inert until it is in three places**: the
  signature, `presets.py`'s `FIXED`, and `_preset_opts`. `_preset_opts` derives
  its keys from `inspect.signature(convert)` and `tests/test_preset_passthrough.py`
  fails if one escapes; `presets.EXCLUDED_FROM_ALWAYS` names deliberate
  omissions. Do not hand-edit that list back into existence.
- **A conversion must be the same length as the original, within ±5 s.** A
  listener's rule and an invariant no column enforces: where the original ends,
  ours must end. Hubbard's `$FE` means *tune ended*, which a Goattracker
  orderlist cannot say, so `--legal-restart` loops to position 0 and the tune
  plays forever. The repair is a restart target, not a new mechanism: park on a
  silent pattern. **Any tune whose window `fidelity.original_ended` shortens is
  a tune failing this rule** — read that list as a defect queue.

## Reading the players

- **This repo has two players and they do not agree.** Every timing number here
  comes from `gt2reloc`'s packed player (`player.s`); the editor's `gplay.c` is
  more readable and more often read. Read `player.s` before concluding anything
  about *when* a table entry lands.
- **Read `greloc.c` beside `player.s`, and settle it on the packed bytes.** The
  packer sits between what you emit and what runs, and it transforms: it inverts
  the wavetable's right-side high bit, and it rewrites the `$E0`-`$EF` waveform
  range conditionally on whether the song uses a wavetable delay at all.
- **A byte copied from a player into a Goattracker table is in Goattracker's
  encoding now** — `$F0`-`$FF` in the wavetable's left column are commands, so a
  copied `$FF` becomes a jump. `tests/test_table_validation.py` replicates
  `exectable` over every corpus conversion; when a pack fails silently, walk the
  tables.
- **A signature encodes an addressing mode, and therefore an instruction
  length** — which is in every branch offset around it. Two spellings of one
  idiom differ in *two* places at once, so a near-miss search never finds the
  other. Zero-page and immediate variants each need their own spelling, added as
  a **fallback** consulted only where the existing ones matched nothing.
- **Anchor a signature on the instruction that names the address you want**,
  never on the arithmetic in front of it — and when a load and a store in one
  idiom both name a table, ask which the *player* reads. The rescue outer-gate
  spellings anchor at the PSID play address; searched file-wide the same shape
  matches ordinary code.
- **A bit tested with `BIT`/`BVC` is invisible to an `AND #$xx` scan**, as is
  bit 7 via `BPL`/`BMI`. Scan all three forms when cataloguing a byte's bits.
- **A constant read from one player is a constant about one player.** Search the
  other files for the same shape and print the operand before generalising an
  immediate; prefer a constant that can be checked against the trace.
- **A walk that steps a fixed byte count over an instruction has assumed its
  addressing mode.** When a fix widens a walk, run the old one beside the new
  one over the corpus and require the difference to be exactly the files you meant.
- **A guard that reads like a sanity check can be a population filter.** When a
  probe declines, ask whether it declined the *file* or the *family*.
- **A detection flag about a player is not a fact about a record.** Every
  per-record effect bit needs both checks; the per-record one is the easy one to
  forget because the file-level flag is what detection hands you.
- **A value written into a counter is not a quantity until you know what the
  counter does.** Ask whether the music the operand implies could be the music
  the surrounding patterns contain.
- **A PSID header's subtune count is not a promise.** Three bounds, tighter
  wins: the player's own init dispatch (`detect.find_music_subtunes`), the digi
  engine's `subtunes_available`, and the layout extent (`tracks.track_table_extent`).
  Each dropped subtune is attributed to the bound that dropped it.
- **A standing disagreement between two independent readings is a lead, not a
  tie to break by preference.**
- **A grep returning 0 is evidence about the counter, not about the file** —
  before treating a count as a defect, subtract what the counter cannot see. A
  line-based search finds nothing for a quotation that wraps across a
  newline, and a naive `**` parity count calls Python's `**` exponentiation
  operator, sitting in a code fence, a stray bold marker. See `docs/LESSONS.md`
  for the measured instances. **A grep for a retracted sentence is the
  structural case, not a counting accident**: this repo requires a wrong
  mechanism to be retracted where a grep for its own words lands, so the
  retraction is *required* to quote the wording it retracts — a check for
  "is the bad wording gone" will always collide with the retraction that
  fixed it. Anchor such a check (a line number, or text outside
  blockquotes/strikethrough), never a bare count.
- **An identifier prefix is a naming convention, not a type.** A check keyed
  on a task id's prefix (`^ab-\d+`) silently includes everything else that
  happens to be named that way — a plan-hygiene meta-task filed under the same
  slug family but carrying no `Files` block at all. The check still returns a
  number, so the inclusion is invisible; only a field that actually
  distinguishes the family (here, `title.startswith('AB task')`) separates the
  subject from its container. Same family as the grep-returning-0 bullet
  above, the code-fence bold-marker parity count, and the `original_ended` /
  `original_ends` key mismatch — a check that cannot tell its subject from
  what merely shares its container. See `docs/LESSONS.md` for the measured
  instance.
- **Documenting a naming collision creates one.** A note explaining that one
  file's `X_*` family is unrelated to another file's same-prefixed `X_*`
  family has to *name* both families to make the point, so writing the note
  is what puts the other family's name into this file for the first time. A
  bare substring grep for the other family's name now matches the file the
  note was written to clear it from. Same family as the grep-returning-0
  bullet above and the identifier-prefix bullet: a check that counts
  occurrences cannot tell the disambiguating note from the collision it
  disambiguates — and the count itself is not even stable across counting
  methods, which is the same lesson again one level up. See
  `docs/LESSONS.md` for the measured instance.

## Measurement discipline

**`FIDELITY.md` is generated at `-t 180`** (since v0.5.459), and so is
`presets.py --fidelity`'s search. **Numbers either side of v0.5.459 are not
comparable**, as they are not across v0.5.195's 10 → 60 move; the header records
the window that produced them.

- **A score is not a clock.** Every column compares *what* is played, never
  *when*. Use `fidelity.py <file> --pace` before saying anything about speed,
  tempo or `-S` — and read its **spread** before its number: a tight ratio is a
  wrong constant, a loose one is a mechanism. **Read its MEDIAN, not its
  least-squares fit** — the fit is a divergence signal, never a row length —
  and use its integrated `drift` line for an error smaller than a frame, which
  the median is structurally blind to. This bullet said the opposite until
  v0.5.476 and the reversal is measured: on 5 of 8 files sampled the fit
  disagrees with the median while `drift` agrees with the median, and on Tarzan
  the fit reads 0.360 where both quartiles are 1.000 over 2728 gaps and the
  drift is zero across 8982 frames. `pace()` weights each gap by the square of
  the original's, so one long rest outweighs a hundred ordinary gaps. The tool
  already agrees: `ours/theirs`, `**their row is N frames**` and `N% out` are
  all derived from the median, and the fit is only ever printed beside it.
- **A low score is a claim about the harness until it is a claim about the
  converter.** Run `fidelity.py <file> --diagnose` before calling any row a
  conversion bug: subtune correspondence first, then a per-voice cause. Six
  separate defects have been in the measurement, including every per-frame
  column being charged for the packed player's startup lag.
- **A shift chosen to maximise agreement can only raise the score.** `startup_lag`
  is *estimated* from the two sides' first attack frames, never fitted.
- **Read any register agreement next to both sides' note counts.** A change that
  removes the events a column scores will always appear to improve it.
- **"No column moved" has four causes**: the change reaches nothing; no
  dimension can see it; the register is one every column ignores; or **the
  window did not contain the material**. The fourth has no fingerprint in the
  report and is the cheapest to exclude — widen the window and re-run.
  `fidelity.py --baseline old.json` separates the first two by hashing the
  converter's output per row; `subtune_content_shas()` names which subtune moved,
  because a change confined to an untraced subtune prints the same verdict as one
  nothing can see. `--baseline` refuses across different `-t` or subtunes and
  *names* rather than refuses an option difference.
- **Do not conclude a change did nothing from a flat table — make the tool say
  it.** Every dimension declares the registers it reads and the report ends with
  *What this run compared*, regenerated from the rows.
- **When a column documents what it ignores, read that as a list of things you
  cannot ship on evidence — then build the column**, rather than shipping on a
  hand-rolled probe.
- **Prefer a travel measure to a count whenever the change is to a step size**
  (`bend` over `slides`, `cut` beside `filt`, `depth` beside `vib`) — **and take
  the measurement from the tool rather than re-deriving it.**
- **Compare a ratio in log space.** 2.0x and 0.5x are the same size of wrong.
- **A `-` in the report is a finding, not a gap.**
- **A column can read 100% because the trace cannot see the defect.** State the
  blindness in the `Dimension` itself. Adding a column means adding a
  `Dimension` entry; `tests/test_fidelity.py` fails if the registry and the
  printed header disagree.
- **A census of what a column misses is a queue, not a report** —
  `fidelity.py --census PATH`. Classify a dimension's misses by cause before
  trying to move it. **And split a population before reducing it**: a modal shape
  over a key two records share compares two instruments.
- **`--vice` is the register dimensions at 312 samples a frame** — use it for
  any change that moves a register *within* a frame, since siddump samples once
  per frame. **Translate the old rule exactly before believing a difference**:
  run the new instrument under the old instrument's rule and confirm it
  reproduces the old number first.
- **A discriminator is only meaningful on the population the behaviour occurs
  in.** A necessary condition with no false negatives is worth more than its raw
  accuracy implies.
- **An attribution key must not contain the quantity being attributed.**
- **When a change alters an event's duration, do not measure it at a fixed
  offset from an attack.** `fidelity.noise_runs` is the shape that works: maximal
  runs, record lengths, drop runs touching the window edge, attribute at the
  midpoint. **When two reductions of one signal disagree by 5x, one is counting
  a different event** — settle it by looking at the frames.
- **A minimum is the reduction for a safety bound; a median is the reduction for
  an approximation** — and weight the distribution by how often the orderlist
  plays each pattern.
- **Verify a newly derived shape on a second file that uses the mechanism
  differently**, preferring one whose options are already enabled.
- **Before emitting a newly decoded effect, measure the original's
  per-offset-from-attack profile**, not just the aggregate.
- **A correlation over instruments is not a mechanism.** A clean per-instrument
  split is the moment to go read the routine, not to generalise.
- **An explanation that fits the shape of a regression is not thereby its
  cause** — turn the proposed cause off and see if the effect survives. **And
  count what you emitted**: a change writing ten times the designed number of
  bytes was not the change you A/B'd.
- **A trace that shows what is wrong does not tell you what writes it.** An
  approximation standing in for an unlocated mechanism is not a fix.
- **To read what a conversion *says*, use `songview.py`** — it decodes the whole
  `.sng` to one HTML page and scores nothing, so it cannot be silently wrong in
  a way that changes a decision. Its parser is a *second* reader of the format;
  `tests/test_songview.py` checks the two against each other.
- **Regenerating the artefact is a second, independent reader** — prefer it
  *before* adopting a candidate, not after.
- **The corpus byte-hash is the check of last resort**, and it answers the one
  question nothing else does: which files a change actually reaches.
  ```sh
  rm -rf <scratch> && mkdir -p <scratch>
  git archive HEAD | tar -x -C <scratch>
  cp python/tools/siddump-rt/siddump.exe <scratch>/python/tools/siddump-rt/
  ```
  then convert every corpus `.sid` on both sides through `fidelity._preset_opts`
  against the repo's `presets.json`, sha the bytes, and report *converted /
  refused / compared / moved*. **The `cp` is not optional** — `siddump.exe` is
  gitignored, and without it the harness silently measures only the single-speed
  files. Expect an exact number and name the files: "exactly 1 moved (W_A_R)" is
  evidence; "no regressions" is not.
- **Build `python/tools/siddump-rt` before taking any fidelity number.** It is
  vendored siddump 1.08 plus `-m<n>`; stock siddump calls the play routine
  `seconds × 50` times whatever the speed field says.

### Probes lie in five ways

Each was caught in-run and each cost more than one task. A probe that runs,
raises nothing, and returns a number about nothing is indistinguishable from a
correct null result.

1. **Assert your own success rate.** A probe passing an argument `convert()`
   does not accept recorded an error string for all 95 files and compared two
   identical sets of them. Refuse to write a result where most conversions failed.
2. **Assert every column you name exists.** `dict.get` returns `None` for a key
   that is absent, and the loop skips it in silence. The `--json` keys are
   `pitch_jaccard` and `sequence`; several report columns are not in it at all.
3. **Prefer a test to a probe.** A claim backed by a committed test survives; a
   scratch script that answers a question twice is a tool that was not committed.
4. **Reproduce the harness's calling convention.** A probe re-derives the
   subtune, the multiplier, the startup lag, the tempo mode and the frequency
   calibration, and need only get one wrong. The harness already resolved them.
   *What catches this is two numbers that cannot both be true*, not either
   looking wrong. The measured instance is the `_preset_opts` key above: a
   probe keyed on a full path recorded three files raising `ConversionAbort`
   under their presets, and all three convert. See `docs/LESSONS.md`.
5. **Know your readers.** `songview.parse_sng`'s `patterns` entries are flat
   lists of bytes, four per row, not row objects — iterating element-wise
   silently yields zero. And a probe that re-imports a module cannot compare
   that module's dataclasses with `==`: `dataclass.__eq__` tests
   `other.__class__ is self.__class__`, so it *manufactures* differences.

### Scripted edits lie in two ways

- **`str.replace` with a non-matching search string returns the input unchanged
  and raises nothing.** `assert old in s` before every replace, and check the
  change is in `git diff` — not merely that the tests still pass.
- **`cd X && <edit>` when the shell is already in X short-circuits**, because
  the Bash tool's working directory persists between calls. The exit is
  non-zero but reads like an ordinary command failure, and the check on the next
  line then passes against the unmodified file. Use absolute paths.
- **Keep the command short; put long text in a file.** A commit message or probe
  piped through a heredoc makes the command itself thousands of characters, past
  which the harness stops to ask a human. Write it with the Write tool and pass
  a path (`git commit -F <path>`, `python <path>`).

### Grading measured figures

**A measured figure written in the present tense decays into a false one.** A
figure is either **historical**, and carries the version it was measured at, or
**live**, and someone has re-checked it and says so. The ungraded middle is the
dangerous one because it reads as current and gets cited as current.

- **"Re-verified" is a timestamp, not a property.** A grading pass's own
  conclusions go stale on the same schedule as what they corrected.
- **State the SET, not the count.** A count decays whenever an unrelated reading
  moves a song's multiplier; the set of files is what the claim is about.
- **Say under which options.** "N converting" is not well-defined without it —
  the corpus converts a different number of files on defaults than on presets.
- **Prefer "check X against Y" to "X is still wrong"** when writing a to-do into
  prose. A bullet prescribing a fix decays exactly like a figure, and silently,
  because nothing re-reads the code it prescribes against.
- **The cheap grader is the pair of generated artefacts** — `presets.json` for
  populations, `build/fidelity.json` for per-file figures — not a corpus run.
  Check the artefact's own `-t` before comparing: two windows are two quantities.
- **`tests/test_claude_md_figures.py` re-derives the live figures here from
  `presets.json` and fails when this file disagrees.** That committed check is
  the argument for grading in a test rather than by hand.
- **A commit message is not a doc, and it is also not erasable.** When one
  carries a wrong mechanism, retract it somewhere a grep for its own words lands.
- **Write evidence with filenames in it**: it decays loudly instead of quietly.

### Preset search

- **`fidelity_better` is not a total order.** The `--fidelity` walk is a greedy
  path, not a maximum. Do not replace it with a single scalar score — five
  incommensurable dimensions collapsed into one number would be the worse lie.
  **"Any one improving" is a sound acceptance rule and an unsound replacement
  rule.**
- **Diff the search result against the shipped presets before adopting it.** One
  version lost seven measured settings and gained one.
- **A search that fails is not a search that says no.** Read stderr for
  `will not convert` and `search failed`; a missing entry and a measured "no" are
  indistinguishable in `presets.json`, which is a record of measurements.
- **`presets.prune_inert`** drops a selected flag whose removal leaves the bytes
  identical — a preset entry records a measured decision, and a flag changing
  nothing was not one.
- **A veto on a ratio must be sized, not merely signed**, and when a guard needs
  a bound, check the quantity's noise floor first.
- **Forcing one option on top of a preset measures the pair.** When a forced
  option produces a *collapse* rather than a shortfall, suspect the combination
  before the mechanism.
- **`fidelity_better` cannot select a change no column scores** — `--regrid`'s
  adoptions and `--initial-instrument`'s are hand-recorded measurements. Do not
  give it options it cannot see.
- **A guarantee written in the caller is a comment.** If an invariant spans two
  functions, test it across both (`tests/test_instrument_bound.py`).
- **A skip condition must be keyed on the thing that would make the assertion
  lie, never on a proxy that moves more often.** A guard keyed on the version
  goes dark on every commit, because the version changes on every commit — and
  the suite still reports green.
- **A regression test whose scenario the pipeline has drifted away from will
  pass forever without exercising the guard.** Pin it at the seam the guard
  owns, not at the file that once reached it.
- **A fixture is not the corpus.** When a reduction over per-subtune data is
  pinned by a fixture, check the corpus copy of the same tune has the same
  subtunes.

## Listening

- **Open a song with `.\play.ps1 -Presets presets.json`, never by launching
  `goattrk2.exe` yourself.** Most preset songs pack above `-S1`, so a bare launch
  plays them at 1/multiplier speed. The `.sng` cannot encode the rate, but the
  editor can be set to it with **SHIFT+F6**; `play.ps1` reads the multiplier and
  prints how many presses. Bypassing it once produced a half-speed audition, a
  listening verdict that reversed the measurement, and a re-test that reversed it
  back. A packed `.sid` played in `vsid` is the other correct way, and the only
  one for a `.sng` you cannot set the multiplier on.
- **`FIDELITY.md` is not the last word on fidelity.** It cannot see tempo or the
  volume nibble, and none of its register columns is a listening test.
- Stage material for a human with `listen.py` so the ask is a link, not a task.

## Emitting

- **A lesson recorded in one emitter is not a lesson in the file.** When a fix is
  really a *rule about the player*, give it a name every emitter has to call
  (`_first_frame_entry`, `_first_frame_lead`) and a column that fails when one
  stops (`onset`). **Extracting a helper is not the same as every caller using
  it** — grep for the constant the helper replaced, not just for the helper.
- **One frame is `multiplier` play calls.** A lead of one *call* is not a lead of
  one frame, and the difference is invisible at `-S1`.
- **Where an effect's frames land is part of the mechanism**, and a per-frame
  profile measured on one file can encode that file's structure rather than the
  mechanism's.
- **Two encodings can be equally correct per call and differ entirely in what a
  per-frame instrument can see.** Anchor only where you must and otherwise carry
  the player's own running state.
- **A mechanism driven by a global counter cannot be put in a per-note
  wavetable** — a wavetable restarts at every note.
- **Reading a bit is not drawing its consequence.** A flag already parsed with
  nothing observable depending on it is a lead, not a finished feature.
- **A rate byte may not be only a rate** — one engine packs the step and the
  frames-between-steps in the same byte another reads as a plain rate.
- **A register zeroed at a rest is not a register zeroed at a note end**, and the
  option fixing one destroys the other. Two mechanisms, two disjoint populations.
- **A restriction is not a neutral default.** When an option is offered and never
  chosen, hash the output before theorising about the criterion.
- **The option that removes a defect is not always the fix for it.**
- **When five derivations fail against one measurement, ship the measurement** —
  as a data table, keyed on something read out of the file, with a test that
  re-measures both endpoints every suite run. **An ablation tells you THAT a byte
  matters, never WHERE it runs and never WHAT it writes**: instrument
  reachability and the value in the *same* run as the ablation.
- **A byte-hash over preset options does not bound a change's reach over forced
  ones.**
- **A symptom can be diagnosed right and explained wrong, and the explanation is
  what propagates.** When a fix rests on "the other way measured worse", check
  the other way is the one you would fix next — there may be a third.
- **A wrong clock masks the defects underneath it.** To tell an unmasked defect
  from an introduced one, diff the structure, not the score.
- **A per-subtune value written into a global structure is read by every subtune
  that reaches it.** Goattracker's patterns are global and its orderlists are
  per subtune.
- **A guard tested on one variant does not cover the other.**
- **Read all three voices before concluding what a subtune does.**
- **A verify written from a symptom can name a fix worse than the defect.** Read
  a verify's prescription as a description of the symptom, and re-derive the fix.
- **When a fix's blast radius is an order of magnitude larger than the evidence
  for it, the rule is scoped wrongly** — visible before any score is read.
- **A shim that hides a defect from the score does not hide it from the file.**

### Four small readings that each cost a session

- **`instr 00` means "keep the current instrument", not "no instrument"**
  (`gplay.c:914`). The quantity you want is never "names no instrument" but
  "sounds a note before its own voice has named one", walked in play order.
- **`songview`'s `instruments[0]` has `number = 1`.** The list is 0-based; the
  numbering is not. Goattracker also numbers patterns in **hex**, and the
  editor's pattern is post-dedup and transposed by the orderlist — so identify a
  pattern by its note-row positions, and read the final `.sng`, not an intermediate.
- **`_preset_opts` passes `False` for an absent key, never `None`** — and a
  key absent because it is *spelled* wrong (a full path, or a bare stem where
  `presets.json` keys with the `.sid` extension) returns the always block
  alone, so the HARDEST files silently get the EASIEST options and the run
  still produces a number. It has warned since `e2fd3f8`; read the warning
  rather than the count.
- **`gplay.c:334` stops the song outright** when the gatetimer reaches the
  channel's tick — total, not graceful.

## Parallel work: branches, worktrees, PRs

Several agents have repeatedly worked this repo at once, and a shared working
tree does not survive it.

- **One branch per unit of work, one PR per branch.** Branch from a pushed
  `master`, never from a tree holding someone else's uncommitted edits.
- **Each concurrent agent gets its own git worktree** (`isolation: "worktree"`).
- **NEVER `git stash` in a fan-out.** A worktree is not a whole repo, and
  `refs/stash` is one of the refs it does not get its own copy of. Two agents
  stashing concurrently produced a `pop` returning a *sibling's* diff, an empty
  `stash list`, and 100+ dangling stash-shaped commits in the object store — so
  it has been happening unnoticed for sessions. The failure is silent and the
  diagnosis from inside one worktree is wrong in both directions. Snapshot with
  `git diff > x.patch` and `git apply -R`, or copy the file, or use a scratch
  branch. Same caution for anything else stored per-repo rather than per-worktree.
- **A worktree isolates the checkout, not the scratchpad**, and concurrent agents
  share the orchestrator's. Give every probe a name no sibling would choose — a
  per-agent subdirectory or a task-id prefix — never a bare `probe.py`,
  `scratch/` or `out.json`. And note `cp x /tmp/...` **succeeds** on this
  machine, so an `|| <fallback>` after it never runs.
- **A worktree has no build artefacts, and this harness needs one.** Copy or
  build `python/tools/siddump-rt/siddump.exe` first, and sanity-check a known
  multispeed file before trusting anything a fresh checkout measured.
- **No PR touches `SURVEY.md`, `presets.json` or `FIDELITY.md`.** They are
  generated; parallel branches conflict on every line, and a per-branch
  regeneration records a tree state that never existed. `master` regenerates
  once, after the merges.
- **Re-take every number after rebasing onto what landed.**
- **Verify the staged path list before committing** (`git diff --cached --name-only`).
- Worktree checkouts can be CRLF against LF blobs, producing bogus whole-file
  conflicts. Normalise before concluding the conflict is real — it usually is anyway.

### Tag every proposed task with how it can be run

Whenever you list next steps — a handoff, a "what next", a plan — tag each item:

- **`[subagent]`** — one agent, `isolation: "worktree"`. Qualifies when the
  change is confined to `python/h2g/` or one harness module, is verified by a
  corpus byte-hash plus a targeted A/B, and touches none of `SURVEY.md`,
  `presets.json`, `FIDELITY.md`. Brief it to copy `siddump.exe` into the worktree.
- **`[main]`** — this session only: anything regenerating an artefact, running
  `presets.py --fidelity`, or committing. Cost is measured, not extrapolated:
  the seven-toggle corpus search is ~25 minutes serial, ~9 minutes in six
  parallel `--shard I/N` runs (`--merge` recombines them; each song's walk is
  independent, and `fidelity.py` has had a private scratch dir per run since
  v0.5.66). **Extrapolating a per-song cost from a handful of files
  over-estimates it** — twice now a wrong cost figure has refused work.
- **`[user]`** — every listening verdict, and any decision about what a tune
  should sound like.

A **workflow** (multi-agent fan-out) is worth proposing only for *independent
investigations that return findings rather than patches*. It is the wrong tool
for anything ending in a whole-corpus measurement, because those serialise on
the same binaries and generated files. It is never started without the user asking.

`/whattask` lists `docs/QUEUE.md` beside `todo.md` — its tiers are already tagged
to this scheme, so read it before drafting a task list.

## graphify

This project has a knowledge graph at `graphify-out/`.

- For codebase questions, run `graphify query "<question>"` first; `graphify path
  "<A>" "<B>"` for relationships, `graphify explain "<concept>"` for focused
  concepts. These return a scoped subgraph, usually much smaller than
  `GRAPH_REPORT.md` or raw grep output.
- `graphify-out/wiki/index.md` for broad navigation; `GRAPH_REPORT.md` only for
  architecture review or when the three commands do not surface enough.
- **`graphify update .` is the orchestrator's job, not a delegated agent's.** A
  fan-out task's declared `touches` is what makes concurrent agents safe, and
  `graphify-out/` is essentially never in it — so an agent running it would be
  writing an undeclared path. One agent correctly refused; nothing else ran it
  either, and the graph rotted 15.5 hours across a fan-out. The refresh goes
  where the contention control already lives: whoever owns the cycle runs it
  once after the fan-out's writes have landed, exactly as the generated
  artefacts are regenerated once on `master` after merges.

## VB6 original — reference only

Requires VB6 (IDE or `VB6.EXE`) plus the `COMDLG32.OCX` common-dialog control.
Open `VB6 Sourcecode/h2g.vbp` and run (F5), or
`VB6.EXE /make "VB6 Sourcecode\h2g.vbp"`. No test suite: manual verification is
loading a known-Hubbard `.sid`, confirming the log detects a player, and loading
the `.sng` in Goattracker.

Everything lives in `h2g.frm` as one top-to-bottom pipeline from `loadfile()`:

1. **`loadfile()`** parses the PSID/RSID header from fixed offsets, loads the
   file into `SIDfile()`, and calls `SSearchfile()` with wildcard opcode patterns
   (`??` = any byte) to locate, in order: the instrument table, the track/subsong
   table, an optional track selector, the pattern table, and the player variant
   (`SIDRHreadTrackVersion`, 0–7). Each `If i <= -1 Then i = SSearchfile(...)`
   chain tries one known game's signature at a time, commented with its game.
2. **`GoatConvertTracks()`** rewrites Hubbard's track data (with its
   version-specific `$FE`/`$FF` markers) into `GoatTracks()`.
3. **`GoatConvertPattern()`** rewrites note/pattern data, including waveform and
   pulse table extraction and ADSR remapping.
4. **`GoatSave()`** serialises header, tracks, instruments and patterns to disk.

**Preserve the `If i <= -1 Then i = SSearchfile(...)` fallback chains.** Each
entry is a distinct game fingerprint; removing or reordering one silently breaks
detection for that game. Adding a new game means adding a new signature and
offset to one of these chains.
