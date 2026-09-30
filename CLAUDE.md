# CLAUDE.md

Guidance for Claude Code working in this repository.

**This file is an index of rules. The evidence is in `docs/LESSONS.md`** — the
verbatim 2300-line predecessor of this file, archived at v0.5.475, holding every
measured figure, worked example, retraction and grading pass behind the rules
below. It is not auto-loaded. Wording was preserved across the split, so a grep
for a rule's phrasing here lands on its evidence there.

Since v0.5.492 the reading/measurement/emitting rules appear here as one-line
headlines; their **full text is in `docs/RULES.md`**, also not auto-loaded.
Option-by-option behaviour is in `docs/OPTIONS.md` and the measuring tools in
`docs/MEASURING.md` (both moved out of `README.md`).

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

**Take the refresh from a clean converter, and keep its A/B.** When another
agent is editing the harness in the same checkout, run it from a detached
worktree of HEAD with `build/` junctioned in (the stamp then reads the bare
sha); and launch a run that outlives the shell tool's ceiling detached, with
`--ab-output PATH`, because a detached launch can drop the stdout the
`--baseline` table goes to. Measured at v0.5.491 (`docs/LESSONS.md`).

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

## Rules by area — one line each, full text in `docs/RULES.md`

Each line below is the rule's headline; **read the section in
[`docs/RULES.md`](docs/RULES.md) before acting on one**, and its evidence in
`docs/LESSONS.md`. A code comment citing "CLAUDE.md's ..." quotes wording that
now lives there.

## Reading the players

- `player.s`, `greloc.c`, `gplay.c` are **not in this repo**: they are at
  `C:/Users/mit/Downloads/GoatTracker_2.77/src/` (plus `readme.txt`). Do not
  search the filesystem for them.
- Two players that disagree: timing comes from `player.s` (packed), not `gplay.c`.
  Read `greloc.c` beside it and settle on the packed bytes.
- A byte copied into a Goattracker table is in Goattracker's encoding (`$F0`-`$FF`
  are commands); `tests/test_table_validation.py` walks the tables.
- A signature encodes an addressing mode and so an instruction length; a new
  spelling is a **fallback** consulted only where the others matched nothing.
- Anchor a signature on the instruction naming the address you want; ask which
  of load/store the *player* reads.
- `BIT`/`BVC` and `BPL`/`BMI` bits are invisible to an `AND #$xx` scan.
- A constant from one player is about one player; a fixed-byte walk has assumed
  an addressing mode; a sanity-check guard may be a population filter.
- A detection flag about a player is not a fact about a record; a counter's
  operand is not a quantity until you know what the counter does.
- A PSID subtune count is not a promise: three bounds, tighter wins, each drop
  attributed.
- A standing disagreement between two independent readings is a lead.
- **A grep returning 0 is evidence about the counter, not about the file.** A
  grep for a retracted sentence is the structural case: the retraction must
  quote what it retracts, so anchor the check, never a bare count.
- An identifier prefix is a naming convention, not a type; documenting a naming
  collision creates one; a presence guard must assert against the slice, not
  the file.

## Measurement discipline

`FIDELITY.md` is generated at `-t 180` (since v0.5.459), and `-t` is a floor
since v0.5.489; numbers across either change are not comparable.

- A score is not a clock: use `fidelity.py --pace`, read its spread, then its
  **median** (never the least-squares fit), and `drift` for sub-frame error.
- A low score is a claim about the harness until `--diagnose` says otherwise.
- `startup_lag` is estimated, never fitted; read register agreement beside both
  sides' note counts.
- "No column moved" has four causes, the cheapest being the window; use
  `--baseline` and `subtune_content_shas()`, and make the tool say it.
- A column that documents what it ignores is a list of things you cannot ship
  on evidence — build the column. Prefer travel measures; compare ratios in log
  space.
- A `-` is a finding; a column that can decline for two reasons records which,
  per side. A column can read 100% because the trace is blind — say so in its
  `Dimension`.
- A census of misses is a queue; split a population before reducing it.
- `--vice` for anything within a frame; translate the old rule exactly first.
- Duration changes: measure runs (`fidelity.noise_runs`), not fixed offsets.
  Minimum for a safety bound, median for an approximation.
- Verify a new shape on a second file; profile per offset-from-attack before
  emitting; a correlation over instruments is not a mechanism; an explanation
  that fits a regression is not its cause until turned off; count what you emit.
- `songview.py` to read what a conversion says; regenerating an artefact is a
  second reader.
- **The corpus byte-hash is the check of last resort** — report
  converted/refused/compared/moved and name the files. `siddump.exe` must be
  copied into the scratch tree. Build `python/tools/siddump-rt` first.

### Probes lie in five ways

Assert your own success rate; assert every column you name exists; prefer a
test to a probe; reproduce the harness's calling convention (`_preset_opts`
keys); know your readers (`parse_sng` patterns are flat byte lists; re-imported
dataclasses never compare `==`).

### Scripted edits lie in two ways

`assert old in s` before every `str.replace` and check `git diff`; use absolute
paths, not `cd X && ...`; keep commands short — put long text in a file and pass
the path.

### Grading measured figures

A figure is **historical** (carries its version) or **live** (re-checked, and
says so). "Re-verified" is a timestamp; state the set, not the count; say under
which options; prefer "check X against Y" to "X is still wrong". Grade against
`presets.json` and `build/fidelity.json` (check their `-t`);
`tests/test_claude_md_figures.py` re-derives the live figures. A presence check
must **normalise both sides before matching** (`_says`). A commit message
carrying a wrong mechanism is retracted where a grep for its words lands.

### Preset search

`fidelity_better` is not a total order and must not become a scalar; diff a
search result against the shipped presets before adopting it; a failed search
is not a "no" (read stderr); `prune_inert` drops flags that change no bytes;
size a ratio veto against its noise floor; a forced option measures the pair; do
not give the search options no column scores; test invariants across both
functions; key a skip on what would make the assertion lie, never the version;
pin a regression test at the seam; a fixture is not the corpus.

## Listening

Open a song with **`.\play.ps1 -Presets presets.json`**, never a bare
`goattrk2.exe` (multiplier; SHIFT+F6). `FIDELITY.md` is not the last word;
stage with `listen.py`. Renders need a fixed power-on delay (`--delay=0` since
v0.5.492). Prune `build/audio` with `sound.py --prune ... --quarantine DIR
--apply` (see `docs/MEASURING.md` § Listening).

## Emitting

- A rule about the player gets a named helper every emitter calls
  (`_first_frame_entry`, `_first_frame_lead`) and a column that fails; grep for
  the constant the helper replaced.
- One frame is `multiplier` play calls; where an effect's frames land is part of
  the mechanism; anchor only where you must.
- A global counter cannot live in a per-note wavetable, but its phase per note
  is static (`goatwriter.fixed_arp_phases`); read base and first-fetch frame off
  the player.
- Reading a bit is not drawing its consequence; a rate byte may not be only a
  rate; a rest is not a note end; a restriction is not a neutral default; the
  option removing a defect is not always its fix.
- When derivations keep failing, ship the measurement as a keyed data table with
  a test; an ablation says THAT, not WHERE or WHAT.
- A per-subtune value in a global structure is read by every subtune; a wrong
  clock masks defects; a guard on one variant does not cover another; read all
  three voices; re-derive a verify's prescribed fix; a blast radius far beyond
  the evidence means a mis-scoped rule; a shim hiding a defect from the score
  does not hide it from the file.
- Small readings: `instr 00` means "keep current" (`gplay.c:914`);
  `songview` `instruments[0]` is number 1 and patterns are numbered in hex;
  `_preset_opts` passes `False` for an absent (or misspelt) key; `gplay.c:334`
  stops the song outright.

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

`VB6 Sourcecode/h2g.frm` is the reference implementation; build steps and its
pipeline are in [`docs/RULES.md`](docs/RULES.md) § VB6 original. **Preserve the
`If i <= -1 Then i = SSearchfile(...)` fallback chains** — each is one game's
fingerprint.
