# Rules in full

The full text of the rules `CLAUDE.md` indexes in one line each. Moved out of
`CLAUDE.md` at v0.5.492 to cut what loads every session; the wording is
unchanged, so a grep for a rule's phrasing in `CLAUDE.md` or in a code comment
citing "CLAUDE.md's ..." lands here, and its measured evidence is in
[`LESSONS.md`](LESSONS.md).

## Reading the players

- **`player.s`, `greloc.c` and `gplay.c` are NOT in this repo.** Only the
  vendored `python/tools/siddump-rt` tree is; the two bullets below tell you
  to read files a fresh checkout does not have. They are GoatTracker 2.77's
  own sources: on this machine at
  `C:/Users/mit/Downloads/GoatTracker_2.77/src/` (`player.s`, `greloc.c`,
  `gplay.c` -- and `readme.txt` for the table semantics); elsewhere, unpack
  the GoatTracker 2.77 source archive and read them there. Do not search the
  filesystem for them -- two agents burned past 120 s doing exactly that
  before this bullet existed (`docs/LESSONS.md`, "The player sources are not
  in the repo").
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

- **A presence guard must assert against the slice, not the file.** A check
  that a figure or a sentence is *present* — `phrase in text` — passes for as
  long as any copy of the phrase survives anywhere in the file, so a figure
  with a second copy (a STALE entry and its re-take, a listening bullet and
  the per-frame-rate bullet it repeats, a docstring's cause names quoted in
  a retraction) is unguarded in exactly the place the guard was written for:
  delete the guarded line and the guard stays green on the other copy. Slice
  first — the list item the anchor sentence starts, the section under a
  heading, the docstring paragraph — and assert inside the slice; the
  `_says` normalisation above is still needed, but on the slice. Same family
  as the three bullets above: a check whose subject and container share a
  substring cannot tell them apart by counting. See `docs/LESSONS.md` for the
  measured instance and which guards still assert against the whole file.

## Measurement discipline

**`FIDELITY.md` is generated at `-t 180`** (since v0.5.459), and so is
`presets.py --fidelity`'s search. **Numbers either side of v0.5.459 are not
comparable**, as they are not across v0.5.195's 10 → 60 move; the header records
the window that produced them. **Since v0.5.489 `-t` is a floor, not the
window**: where the length probe places the original's ending past `-t`, the
register columns are traced over that length (`window_seconds` in the row,
named in the header and a notes bullet; `--no-window-floor` pins the old
behaviour), so a prefix row scores the whole tune and `--baseline` refuses
across two files whose windows differ. A file whose original ends inside `-t`,
or never ends, is unchanged. Evidence in `docs/LESSONS.md`.

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
- **A `-` in the report is a finding, not a gap** — and a column that can
  decline for more than one reason must record, per side, *which*. A guard
  that is right for the quantity (drop a run the window cut, because its
  length is a fact about the window) can drop the only material a file has,
  and then "the window could not measure it" and "there is nothing to
  measure" print the same `-`; a one-sided count elsewhere in the row does
  not say which. Record what the guard dropped (count and frames, each
  side) beside the verdict: `noise_run_agreement`'s `*_edge_runs` /
  `*_edge_frames` keys are the shape, and the report names the files the
  first cause declined. The measured instance was Confuzion under the
  gate-blind `noise_runs` (v0.5.480: one 8998-frame original run the whole
  window long, dropped whole, `nrun` `-`); the gate-AND at v0.5.483 fixed
  *that file* (2 of 2 paired, `nrun` 1.0 at v0.5.486), not the mechanism.
  Read the row's `-` beside those keys before reading it as "no noise".
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
- **A check that asserts a quoted sentence is present in prose or source must
  normalise both sides before matching** — strip line-leading comment and
  blockquote markers, collapse every whitespace run — because prose wraps and
  a bare `phrase in text` reads 0 the moment anyone re-flows the paragraph.
  This is the grep-returning-0 rule's wrapped-quotation case met by a guard
  that enforced it: a retraction guard failed against a correct retraction
  wrapped across a `#`, and the figure guard failed against a corrected
  figure wrapped across a line, on one afternoon. `_says` in
  `tests/test_claude_md_figures.py` is the shape; a new presence check
  anywhere else should call something like it, never `in` on raw text.
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
- **A render is reproducible only with a fixed power-on delay.** sidplayfp
  draws one at random unless `--delay=<0..8191>` is passed;
  `listen.render_sidplayfp` passes 0 since v0.5.492. The render cache is keyed
  on the `.sid` bytes, so a cached WAV does not say which delay made it --
  a calibration floor taken against pre-flag renders is the old floor.
- **`build/audio` accumulates a superseded `ours` render per converter
  change.** `python sound.py --prune <sid_dir> --quarantine DIR --apply`
  quarantines them (never deletes); the live set is `build/fidelity.json`'s
  rows plus the calibration's rebuilt historical builds plus recoverable
  approvals, and it refuses while a calibration build cannot be rebuilt.
  Since v0.5.490; `docs/MEASURING.md` § Listening has the rule in full.

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
  wavetable** — a wavetable restarts at every note. **But the counter's phase
  at each note is static**: it is the counter's value at the first fetch plus
  the note's row index times the row length in frames, so what the wavetable
  cannot carry per note it can carry per instrument by majority
  (`goatwriter.fixed_arp_phases`), exact wherever a row is an even number of
  frames. Read the counter's base and the first-fetch frame off the player,
  never off a trace of one file: the repo's Commando fixture is the corpus
  Commando saved mid-run, same player and a different first attack frame.
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
