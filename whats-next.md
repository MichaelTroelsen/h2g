<original_task>
Continuation of long-running work on **H2G**, a signature-based ripper that
converts Rob Hubbard `.sid` files into GoatTracker `.sng`, at
`C:\Users\mit\claude\h2g`. This document covers **two** runs:

* **v0.5.253 → v0.5.297**, 52 commits, *reconstructed* — see the provenance
  note below.
* **v0.5.298 → v0.5.304**, 8 commits, written by the session that did them.
  It opened by being asked to "read what next", found the handoff 52 commits
  stale, rewrote it, and then followed one thread out of it to the end.
* **v0.5.305 → v0.5.309**, 5 commits, same session, same day. It began as
  "restage the listening pairs" — the item three consecutive handoffs had
  called the immediate next action — and turned into building the listening
  apparatus that item had always assumed existed.
* **v0.5.310 → v0.5.313**, 4 commits, same session. Took the queue's one
  genuinely stuck item (the bit-6 rest), found its cause, and followed the
  finding two levels down into the tempo and then into the row grid. A
  concurrent session pushed its own v0.5.311 in the middle of it.
* **v0.5.314 → v0.5.317**, 5 commits (one carries no version), a later
  session. It ran the queue rather than a thread: re-searched the six
  re-gridded files' settings, regenerated the artefacts behind them, then
  executed the listen item's *staging* half — and found a defect in the
  staging tool by reading the artefact it had just produced.

> **Provenance, for the first run only.** That part is reconstructed from the
> 52 commit messages, the generated artefacts and the tree, by a session that
> did none of the work. The previous handoffs were written by the session that
> did it and could record what left no trace — a directive, an approach
> abandoned before it reached a file, a listening verdict given in chat.
> Everything is checkable; what is missing is whatever was never committed.
> Treat its `<attempted_approaches>` entries as "refutations that reached a
> commit message", not as the full list. The v0.5.298–304 entries carry no
> such caveat.

None of the three had an up-front task. The first was driven by short
directives and three rounds of forked subagents; the second and third by short
directives alone, no forks, everything in one session. The working mode is the project's established
one:

> measure the conversion against the original, find where they differ, read the
> 6502 to learn why, fix it, re-measure across the corpus, and ship or refuse to
> ship on the measurement.

Scope: `python/h2g/` (detect.py, goatwriter.py, tracks.py, patterns.py), the
measurement harness (`fidelity.py`, `presets.py`, `survey.py`, `songview.py`),
two new generated reports (`SUBTUNES.md`, `VIBRATO.md`), and in the third run
the listening apparatus (`listen.py`, new `abpage.py`). The VB6 original was
not touched, and **the third and fifth runs changed no converter code at
all** — every commit in them is harness, tooling or docs.
</original_task>

<work_completed>

## Summary

**74 commits, v0.5.253 → v0.5.317. The last two are committed but NOT
pushed** (`git status -sb`: ahead 2) — `ee76308` and `96298cc`. `Commando.sng`
byte-exact throughout. Working tree clean but for the deliberately untracked
`6581.pdf` and a stray `monlog_out.txt`.

Corpus movement, from `FIDELITY.md`'s own summary blocks:

| | v0.5.252 | v0.5.297 | v0.5.304 | v0.5.315 (current) |
|---|---|---|---|---|
| mean melody | 88% | 91% | 91% | **91%** |
| mean sequence | 87% | 90% | 90% | **91%** |
| mean wave | 78% | 79% | 79% | **81%** |
| mean ADSR | 63% | 65% | 65% | **66%** |
| noise frames ours/orig | 75904 | 76332 | 76332 | **76034** / 82742 |
| *plays the same music* (95–100%) | 46 files | 54 | 54 | **56 files** |
| mean gate overlap | (no such column) | 47% | 50% | **52%** |
| frames we sustain, they released | — | 134630 | 129106 | **122589** |
| drift | (no such column) | 46 of 79 exact | 46 of 79 | **52 of 79** |

The current column is the artefacts as they stand, stamped 0.5.315. Its gains
over v0.5.304 are v0.5.313's re-grid and v0.5.315's re-search of the six files
it moved — six files out of 83, which is why the means move by a point and
`drift` by six files.

The second run moved one column: `gate`, by 3pp, on 12 files, by making the
hard restart's row bound a per-song choice. Everything else it did was to the
*harness* and the *record* — which is what the run was mostly about.

Four report columns and four census modes did not exist at the start of the
run. Two of them — `gate` and `drift` — were built specifically because a
correct-by-the-player change could not be shipped on evidence without them.

## The through-line

**Build the column, then ship the change.** Twice in this run a fix was read
correctly out of the player, changed bytes on a dozen-plus files, and moved
nothing in the report — because no dimension read the register it touched.
`--rest-keyoff` (v0.5.269) was flat on 18 of 19 files until `gate` existed
(v0.5.270), at which point it read 12 files, all 12 upward, and moved into
`presets.FIXED`. `drift` (v0.5.281/288) did the same for timing, and its first
honest run found a file running at exactly half speed that `--pace` had been
reporting for versions without anyone reading it as a defect.

The counterweight, learned expensively in the same run: **a new instrument is
wrong until it agrees with an old one.** The vibrato census shipped four
separate defects in five commits (7.ttttt, 7.vvvvv, 7.xxxxx, 7.yyyyy, 7.zzzzz),
each inflating a bucket and producing a plausible queue item; two were reported
as findings and withdrawn. The catch was available the whole time — its
instrument counts disagreed with `onset`'s on the same files.

## By thread — the first run (v0.5.253–297)

### The fork rounds and their merges — v0.5.254–266

Two rounds of four forks each, merged with renumbering (every branch bumps to
the same version in parallel; every branch appends the same method-doc section
letter).

* **v0.5.254 the hold census** (`--hold-census`). `hold`'s unattributed tail was
  asking one question where there are two: is the *note* shorter, or its *slot*?
  433 instruments — fetch 211, slot 117, match 92, residue nine. For 94 of the
  117 `slot` rows the file's median `our_slot/orig_slot` is `1/retrigger_ratio`
  within 25%: one ratio shared by every instrument of a file is a tempo
  signature, not seven length bugs.
* **v0.5.255 Mega Apocalypse's `$44`** — `TWO_STAGE_SHAPE` with its per-voice
  cells in zero page, so the absolute pattern misses from its fourth opcode.
  `TWO_STAGE_SHAPE_ZP` matches that file and nothing else.
* **v0.5.256 Nineteen's `$0B06`** — the onset census's only `wrong`, and not a
  placement rule: records 0 and 4 share an ADSR pair and differ in `+2`
  (`$41` pulse bass, `$01` drum alone). `_sfx_drum_entries` *declined* a record
  with no waveform of its own, silencing the drum for the project's life.
  Nineteen melody 77 → 96%, Bangkok Knights seq 88 → 97%, Pandora 96 → 98%.
* **v0.5.257 Ninja's per-voice two-stage** — and `tracks.instrument_voices`, the
  **instrument→voice map** the previous handoff listed as a prerequisite.
  Read from the finished orderlists, weighted by how often each pattern plays.
  Two corrections turn the player's threshold into play calls and neither is
  the threshold: `- 1` (the note's first call jumps past the effect block) and
  `× (O+1)/O` (the outer gate). Both settled by tracing *patched copies* of the
  file, not by re-reading the 6502.
* **v0.5.262 the wave program's terminating step** — `$85` does not freeze the
  last waveform; the program's end reverts to the last `< $80` opcode. And
  **`$E0` is not a silent waveform in a packed `.sid`**: `greloc.c:1270-1271`
  rewrites the range and a song with no wavetable delay ships it as a literal
  `$00`, which `player.s:944` reads as *no wave change*. Silence is `$18`.
  `wave` up on 16 files.
* **v0.5.263 Ninja's bit `$01`** — per-voice alternation, branch running the
  opposite way from W_A_R's (`alt_first=True`). noise 0/219 → 387/219,
  `nrun` 100%.
* **v0.5.264 Rasputin's `$FE nn`** — emitted as `CMD_SETTEMPO`, always into a
  *copy* of the pattern (all three of subtune 0's first changes land on pattern
  `$01` at three different tempos). melody 71 → 75%, retrig 1.81 → 1.66.
* **v0.5.266** re-ran the full `--fidelity` search against the changed
  wave-program emitter: **0 gained, 0 lost, byte-identical apart from the
  stamp.** Recorded because `presets.json` cannot distinguish a setting
  measured this hour from one inherited six versions ago.

Also merged: a second machine regenerated all three artefacts from a fresh
clone (gt2reloc from SourceForge, siddump-rt built with `zig cc`) and got a
**one-line diff on each — the version stamp**.

### The speed gate's immediate spelling — v0.5.267–268

`--pace` named it before any code was read: Ninja's row 0.750 of the
original's, **IQR 0.750–0.750 over 858 gaps**. Zero spread on a musical
quantity is a wrong constant, not a mechanism. The gate was one byte off the
pattern — `LDA #imm` is two bytes where `LDA abs` is three, so the branch
skipping the reload is `+5` rather than `+6`. `SPEED_GATE_IMM` is a
**fallback**, consulted only where the absolute form found nothing (Ninja and
Mega Apocalypse; 33 of the 35 files carrying the shape already read a gate).

melody 85 → 100%, seq 86 → 100%, pitch 79 → 100%, retrig 1.33 → 1.00,
wave 57 → 88%. It also unblocked two earlier readings: v0.5.263's 1.77×
noise overshoot became 0.94× untouched, and `pul` moved the *wrong* way
because we had been striking a third too many notes.

### The gate axis — v0.5.269–274

* **v0.5.269 `--rest-keyoff`.** Status bit 6 is a rest; three things happen at
  the `BIT`/`BVS` branch across the 61 files with the shape and only the first
  was ever read (hold, envelope-zeroed, testbit-into-waveform). Off by default
  **because it could not be measured at all** — a GT KEYOFF clears the gate and
  nothing else, and every column ignores that bit by construction.
* **v0.5.270 the `gate` dimension.** `|both off| / |either off|` over the
  gate-off frames alone. Two properties written in rather than discovered:
  it reports its direction, and it **rises when notes are removed**. Then
  `--rest-keyoff` reads 12 files, all 12 up (BMX Kidz 4 → 85%), and moves into
  `FIXED`. Corpus states an error axis it never had: **mean gate 39%**.
* **v0.5.271 `gate` as a search term** — acceptance only, never a veto, guarded
  by `keeps_notes`. Its one independent selection is a wash and lands on the
  corpus's least measurable file, which is recorded as such rather than
  hand-picked out.
* **v0.5.272 `--gate-census`** — 46996 releases: matched 50.2%, held 24.2%,
  short 23.5%, retrigger 2.0%. **A probe of mine said something else entirely
  and was wrong**: it traced *both* sides at the song's `-S` multiplier, which
  plays a 50 Hz original three times too fast and manufactures one-frame gate
  edges. Two files' worth had reached a section draft.
* **v0.5.273** dropped the gate on `_find_rest_silences`: a bit-6 event is a
  rest in all 61 files, 21 cut the sound in the branch and 40 reach the same
  released state a frame earlier. Forced across the 40: **26 up, 0 down**
  (Battle of Britain 21 → 90%, Thrust 47 → 87%). Mean gate 39 → 44%.
  **The first measurement of this said the opposite** — it came from the bad
  probe above, so one defective probe produced a false finding *and* a false
  refutation of the fix for it.
* **v0.5.274** the census disagreed with its own column: the nonzero guard
  `gate_runs` needs on the *original's* side had been copied onto ours, so 38
  runs over 8889 frames of a voice **neither side plays** read as `held`.
  Result: **`held` has no tail left** — longest run 29 frames, mean 3.3 — so it
  is the same defect `hold`'s `fetch` owns, seen from the other side, not a
  separate mechanism to go and find.

### The hard restart — v0.5.275–276

`--no-test-restart` is **not** the fix for the note-length deficit: forced
corpus-wide it is `hold` +69.9pp and **`melody` −26.3pp on 68 files**, because
the testbit frame it deletes is the only frame our conversions spend below
`$10` and siddump needs one to name an attack. The testbit frame stands in for
a release we never make, so the release is the lever — and ours was
`HARD_RESTART_FRAMES = 2` **calls**, a rate in calls where every other rate in
the file is `frames × multiplier`.

Five files gained 25–45 points of melody with retrig landing within 0.22 of
1.0, and **no file in the corpus is worse by half a point** on melody, seq,
pitch, wave, adsr, onset or hold. Mean melody **88 → 90%**, *plays the same
music* 48 → 52.

v0.5.276 then swept the three numbers bounding it and found the constant nearly
inert: the floor of 2 decides for single-speed files and `row // 2` for
multispeed ones. **`row // 2` is not a corpus optimum — it is the last value
before Saboteur II breaks.**

### Powerplay Hockey: two players in one file — v0.5.277–280

The corpus's least measurable file (melody 72%, adsr **0%**, four columns
printing `-`) turned out to carry the player **twice**. The orderlist and
pattern chains matched engine two; the instrument chain takes the first
matching store-shape in the file, which is engine one's. Right notes, wrong
instruments. Rule: where the winning signature matches more than once, take the
table nearest the pattern pointers — which `find_song_speeds` already used for
gates. **1 of 83 files moves**: melody 72 → 99.3%, adsr 0 → 99.9%, retrig
1.76 → 1.01.

v0.5.278 then fixed the confirmation probe: `_find_two_stage` requires
`duration == attack + 2` and both probes took `search_file`'s **first** match,
so it compared one engine's attack table against the other's duration table.
Every match, not the first.

v0.5.279 `--engine N` rips the second player: nine game cues, mean melody 75%
against the original's subtunes 1–9. **No new signature was written** — the
classic chains find all of it already and were being skipped by the digi guard,
so the option is one line. `--engine 0` cannot move a byte.

v0.5.280 `survey.py --subtune-census`: 553 declared, 312 emitted, 227 lost
across 39 files — and **the converter was already right**. 167 have no
resolving voice pointer at all; the 59 that resolve one or two of three point
at *another subtune's* orderlist or into the track table. The reference counts
agree with the wrong answer (a garbage pointer reads small bytes, and a small
number is a valid pattern index), so 30 files leave the queue rather than
joining it.

### Drift — v0.5.281, 288, 289

`--pace` is blind to a row wrong by a *fraction* of a frame, structurally: a GT
row is whole play calls, so the error is zero on most gaps and one whole frame
on the occasional one. Powerplay reads median 1.000 while its notes arrive 24
frames early. The fix is a different statistic of the same two traces —
Theil-Sen fit of `ours[k] - orig[k]` against `orig[k]`, per voice.

**37 files drift by zero, 29 drift, and on 17 the figure is exactly
`-1/(skip+1)`** — the outer gate's skipped call, which `effective_frames`
corrects only when the corrected row can be packed. A number on a known
limitation, not a new defect; the fix is re-gridding.

v0.5.288 promoted it to a report column, bounded by scatter as a share of the
window (1%): the first regeneration's headline `+1151.4` was one voice at a MAD
of 82 frames, two sides *wandering* rather than parting at a rate. `drift()`
had returned `mad` since its first version and nothing consulted it — writing
the caveat is not enforcing it.

Its first honest run found **Mozart at +1000.0 with a scatter of 0.0** — a
conversion running at exactly half speed. v0.5.289: the signature was never
missing (`OUTER_GATE_RTS` has matched since v0.5.248); `find_song_speeds`
returns None as soon as no *inner* gate is found. **A player with only the
outer counter advances its pattern once per working call, so the row is one
tick.** melody 62 → 100%, drift +1000 → 0. 1 of 95 files.

### IK+'s bit-6 rest: three refutations, still open — v0.5.282–286

A listening session reported IK+ as not sounding right — behind a `melody` of
99% that hides it, `hold` 0%, `gate` 48%, `seq` 77%.

1. **v0.5.282** appended a silence to the wave program. `$18` is not `$08`
   (silent to the ear, not to the instruments). With `$08`: IK+ gains 3 points
   of `wave`, **Nemesis the Warlock loses 45**. Reverted. The mechanism was
   never located — only its effect on one file's trace.
2. **v0.5.283** located it: pattern status **bit 6**, via the `BIT`/`BVS` idiom
   the method doc already warns is invisible to an `AND #$xx` scan. Four rounds
   of xrefs missed it; a literal search for `LDA #$08` found it in one step.
3. **v0.5.284** emitted `CMD_SETWAVE $08` on the rest — verified in the editor,
   the packed player *and* the relocator. **melody −43.0pp over 8 files.**
   Reverted.
4. **v0.5.285** turned the proposed cause off and it survived: suppressing
   `CMD_TONEPORTA` after a bit-6 rest changes **zero bytes** on all fifteen
   files. The `gplay.c` reading was correct and predicted the right shape and
   was still not what happened. **And the experiment was invalid anyway** — 673
   command bytes were written where 61 were designed, because a bit-6 event's
   `wait` hold rows reuse `cmd1`/`cmd2`.
5. **v0.5.286** fixed that mechanism structurally (`ONE_SHOT_COMMANDS`), 0 of 95
   files moving, so the next attempt starts from a valid emitter.

**Still open.** Two measured facts remain unassembled: Auf Wiedersehen Monty's
voice 2 holds `$41` — gate ON — continuously where the original drops to `$40`
at each note end (194 attacks → 14), which is the *opposite* of what writing
`$08` should do; and no one has re-run the A/B since the emission was corrected.

### The vibrato census — v0.5.290–297

A listening session on Knucklebusters ("the vibration is not fidelity, slides
are not fidelity") pointed at `vib`, median **0.66** over 80 files.

The headline held across all seven commits and is the useful finding:
**the shortfall is absence, not rate.** 114 of 136 instruments emit no
oscillation whatever; 22 merely run slow. v0.5.129's rate correction was
working on the smaller half.

Everything else in the census was wrong at least once:

* **v0.5.291** — `instrument_stamps` joined on the raw ADSR pair while
  `--cut-release` rewrites the release nibble, so `unknown` was 67 instruments
  that were simply unjoined. Masking took it to 5. **And three report columns
  had the same hole.**
* **v0.5.292** — but blanket masking is a bad trade (it merges 9.5% of the
  corpus's instruments). `paired_keys` matches **exactly first**, falling back
  to the masked key only for leftovers where one candidate remains in both
  directions. All six ADSR-keyed sites call it now. Instruments compared:
  `onset` 443 → 528, `hold` 440 → 525. Nine files' printed numbers move and all
  nine convert to identical bytes — a measurement fix looks like that.
* **v0.5.293** — the effect-bit table was written into the census; `$04` is an
  arpeggio in some players and a two-stage attack in others. Now built from
  `Detection` per file.
* **v0.5.295** — bit `$02` alternates a **waveform** and cannot move a pitch.
  The classifier iterated bits numerically, so `$2B` was named for `$02` every
  time. The `alt` bucket — "the second largest mechanism, 20 instruments
  emitting nothing" — was work that did not exist.
* **v0.5.296** — three more map errors, all from writing it beside the census
  rather than reading `detect.py`. `effect_arp` is **`$04`**, not `$10`. The map
  now quotes detect.py's field comments in place.
* **v0.5.297** — the census was **unioning** raw keys where every neighbour
  pairs. Totals fell from 188 instruments / 60053 reversals to **136 / 42618**.

One converter fix came out of it: **v0.5.294**, both the command pass and
`_vibrato_delay` were gating at once, so a note the command *enabled* was
postponed 8 calls against a half-period of 4. Over the 25 files of the dialect,
`vib` moved on 20 and toward 1.0 on 19, with no other column touched.
The docstring had said the design needs `vibdelay 1` since v0.5.199; the
measurement it cited compared two *ways of delaying* and never asked what not
delaying scores.

### Housekeeping

* **v0.5.286** `ONE_SHOT_COMMANDS` (above).
* `0447bb7` **shared permission allowlist** in `.claude/settings.json`, built
  from what 50 transcripts actually run. The fork fix is one rule covering
  `AppData/Local/Temp/claude/**` instead of one per worktree name. Deliberately
  absent: `git add`/`commit`/`push`, `rm`, `cp`, `mkdir`. Its stated limit:
  `python -c` and `python - <<PY` are 1231 of 3666 recorded Bash calls and no
  rule can cover them without granting arbitrary execution — the lever is
  promoting recurring probes into `python/`.
* Two commits (`b5a7f4e`, `0447bb7`) deliberately **did not bump the version**,
  because `test_preset_passthrough`'s guard is armed only while presets.json's
  stamp equals `__version__`.


## The second run (v0.5.298–304), commit by commit

It started as bookkeeping and turned into a feature, which is the whole shape
worth carrying: **an unmeasured cost figure had been refusing work for 26
versions.**

### v0.5.298 — the handoff, rewritten
The previous one described v0.5.251 and was read 46 versions later — the
second consecutive handoff consumed stale, which its own opening paragraph
records about *its* predecessor. Reconstructed from commit messages with every
figure re-taken from the tree, because a message states what was true when it
was written.

### v0.5.299 — one stamp across all five artefacts
`SURVEY.md`, `presets.json`, `FIDELITY.md` and `SUBTUNES.md` had drifted three
versions behind `__version__`, because v0.5.295–297 were census corrections
that each regenerated only the report they touched. Every one came back with a
**one-line diff, the version stamp**; `VIBRATO.md` carries no stamp and came
back byte-identical. The substantive effect: `test_preset_passthrough`'s guard
re-armed after four versions of silently skipping — so the check that no
`convert()` option escapes into `presets.py` had not been running.

### v0.5.300 — the carried settings, re-measured
The 47 `--fidelity` settings had been carried since v0.5.271, across three
changes to what the converter emits. Re-run: **1 gained, 0 lost**, structural
choices identical on all 83. Kings of the Beach intro takes `two_stage`; its
independent A/B is `slides` and `vib` toward the original, `wave` and `bend`
away, twelve columns flat. Adopted rather than hand-picked, per v0.5.271.

### v0.5.301 — the search is 8 minutes, not four hours
Timed twice: **8m11s** and ~8m, 83 songs, zero failures. The documented figure
had never been timed and was wrong by ~30×; CLAUDE.md carried *two* different
values for the same command 400 lines apart. The second run also seeded itself
with the adopted output and returned **0 gained, 0 lost**, so the search is
deterministic and idempotent and v0.5.300's gain was a convergence.

Ten sites corrected — and **three of them were using the cost as a reason**,
so they were rewritten rather than renumbered. `--voice-two-stage`'s refusal
kept its sound reason (a one-file signature belongs in `FIXED`) and lost the
clock; the per-song `HARD_RESTART` row bound had no second reason and was
reopened.

### v0.5.302 — `--wide-hard-restart`
The reopened item. `_hard_restart_ticks` gains a bound of `2 * row // 3`.
Forced off it changes no corpus byte; forced on it reaches 19 files; the search
takes it for **9 and refuses it on Saboteur II** — the file v0.5.276's sweep
said breaks. That refusal was the premise the option was built on and
`keeps_notes` did it unprompted. Mean gate 47 → 48%, W_A_R Preview 63 → 99%,
nothing falling anywhere.

### v0.5.303 — `presets.py --shard I/N` and `--merge`
A seventh toggle makes the search 127 combinations a song — about a minute a
song, 80 minutes serially, which is what the serial run was measurably tracking
toward when it was killed. Nothing about it is sequential. Six shards:
**80 minutes → 11m20s.** The equivalence is checked, not asserted: three
structural shards merged reproduce the unsharded run's `songs` dict exactly.
`--merge` refuses rather than resolves — a song claimed twice, shards
disagreeing on `always`/`criteria`, or nothing to merge (an empty
`presets.json` reads exactly like a corpus that converts nothing).

### v0.5.304 — `--max-hard-restart`, and the bound is a three-way choice
`row - 1`, the last value before `gplay.c:334` stops the song. Offered because
the gentler option's guard had been *seen* to catch the case rather than merely
expected to. It outranks `wide` where both are given, verified on the corpus
(forcing both is byte-identical to forcing `max`) and not only in a unit test.

**The corpus splits three ways**: 11 files take `row - 1`, **ACE II keeps
`2 * row // 3` having tried the wider value and rejected it**, 71 keep
`row // 2` — Saboteur II among them, refused at both. No file carries both
flags. Delta 42 → 84%, Flash Gordon 59 → 85%. Mean gate 48 → 50%.

That one file keeps the middle value is the finding: a sweep of a single
constant, which is what v0.5.276 did, can only ask which value is least bad for
everyone, and could never have shown it.


## The third run (v0.5.305–309): the listening apparatus

Three consecutive handoffs named "re-stage and listen" as the immediate next
action, and each time it stayed undone. This run found out why: the staging
existed but nothing made a *comparison* practical, and the renderer underneath
it had two defects nobody had looked for. **No converter code changed in this
run.** What changed is that a listening pass is now a thing a person can
actually sit down and do.

### v0.5.305 — the handoff covers both runs
v0.5.298 rewrote the handoff and then the session kept going for seven more
commits, so the document described its own starting point.

### v0.5.306 — `abpage.py`, gapless A/B pages
Playing two WAVs in a media player is not an A/B: the switch costs a click and
a seek, and by the time the second file starts you are comparing a sound to a
*memory* of one. That is the wrong instrument for a corpus where `melody`,
`seq`, `pitch`, `retrig`, `onset`, `hold`, `tail` and `adsr` can all read 100%
on a tune that still sounds wrong.

`abpage.py` builds one page per staged tune that **plays both renders at once
and swaps which one is audible** — gapless, position-matched, with a loop
toggle and a **blind mode** that hides the labels, randomises after each guess
and keeps a tally. A tune you cannot pick above chance is a stronger result
than any column in the report.

Two output modes and the distinction matters: local pages reference the WAVs
beside them (~13 KB, any length); `--embed` inlines the audio at 4/3 its size
(~14 MB a minute a side), which is the mode with a ceiling. Pages **quote**
`FIDELITY.md` and `LISTENING.md` rather than restating them, so a page cannot
prime a listener for a defect the report does not name. A `-` column is
dropped rather than printed — in that report it means *no shared instrument
key*, not zero. 11 tests, including an `html.parser` balance walk over real
generated markup.

### v0.5.307 — `listen.py --all`
Staging the corpus needed the song list spelled out on the command line. The
flag reads **`presets.json`, not the corpus directory**: the directory holds 95
files and 12 have no player this converter detects, so queueing those renders a
silent conversion side for each — which reads as a fidelity catastrophe rather
than an absent player. `--files` and `--all` combine. `select_names()` is
extracted so it is testable without rendering the corpus; 8 tests.

### v0.5.308 — the renderer is `sidplayfp`
**The user identified this, and it was the substantive find of the run.**
`SID2WAV.EXE` is version 1.8 from 1997 and is a build of libsidplayfp's own
lineage; the current frontend of that lineage is `sidplayfp`. Being
twenty-eight years newer fixes three things, two of which this harness had
already *measured* without recognising them as defects:

* **It refuses every RSID** — 18 of 95 corpus files, so the corpus was being
  rendered by two different emulations (sid2wav and VICE).
* **It fades the last seconds out.** Visible as a decaying tail in an energy
  profile of its Commando render, printed while chasing an unrelated question
  and read past. Every comparison's ending was corrupted and nothing said so.
  `-fo0` turns it off.
* **It exposes no chip model.** Hubbard is 6581-era; `-mo`/`-mn` and ReSIDfp's
  `--fcurve`/`--frange` are audible and were unavailable.

And VICE, the fallback, **does not render the length it is asked for**:
`-limitcycles` overshot a 20 s request by 1.76 s, and the staged
Kings_of_the_Beach_intro pair was 115.6 s against 120.0. After the switch all
83 pairs are 120.00 s on both sides, checked.

The structural change is `pick_renderer`: the engine is chosen **once per
pair, never per side**, by probing the *original* (the harder of the two, since
`gt2reloc` always writes a PSID and the original may not be). The old code
chose per side and fell back inside each call, so sid2wav on one side and vsid
on the other was reachable — the one outcome this staging cannot tolerate,
since two emulations differ in level and filter enough to colour a verdict.

**RSID needs the C64 ROMs and the failure looks like silence**: without a
KERNAL, libsidplayfp runs to an illegal instruction having already written a
44-byte header. `sidplayfp.ini` now points at VICE's `kernal-901227-03.bin`,
`basic-901226-01.bin`, `chargen-901225-01.bin`.

### v0.5.309 — `listen.py --shard` / `--merge-notes`
The corpus at 120 s is ~95 minutes serially and ~8 across six shards. Each
tune's render is independent; **the notes are not**. Every run writes the whole
`LISTENING.md`, so shards sharing an output directory leave only the last
one's — and `abpage.py` reads that file for each tune's "what to listen for",
so the loss is silent and reads as tunes that were never staged. Sharded runs
write `LISTENING.part<I>.md`; `--merge-notes` joins them and folds in whatever
was already there.

**A real bug, found by running the thing rather than testing the parts.** Two
shards concurrently produced one part file and half the tunes: v0.5.308's
`pick_renderer` wrote its probe to a fixed `_probe.wav` in the *output*
directory, which sharded passes share, so they raced and one shard silently
staged nothing. This is the defect `make_workdir` was added for in v0.5.66,
reached by a different route eight months later, in code written the same day
as the tests meant to cover it. **Every unit test passed throughout.** What
caught it was running three shards for real and counting the output.

### The listening set as it now stands
83 pairs, 120 s, every one rendered by one engine, `build/listen/`, 1.7 GB,
gitignored. 83 A/B pages plus `index.html`. Final corpus-scale run: **8m13s**
for all 83 including merge and page generation, with 0 leftover parts and 0
stray probes.


## The fourth run (v0.5.310–313): one stuck item, three levels down

The queue's item 2 had been stuck through three attempts. Taking it produced
a chain, each step of which was a different defect from the one above it.

### v0.5.312 — the bit-6 rest's regression was the tempo write
`--rest-wave-silence` emits `CMD_SETWAVE $08` on a rest, reproducing what 17
players park in the stored waveform. v0.5.284 measured **melody −43 pp over 8
files** for this and three explanations had been refuted (the wavetable, the
`$18` value, `CMD_TONEPORTA`).

The cause is **`apply_tempo`**. It writes `CMD_SETTEMPO` into the row each
subtune enters on, and **the command column is one byte per row** — a rest
holding row 0 takes the slot, the write is skipped entirely, and the song runs
at Goattracker's default. The correlation is exact: the eight files that
collapse all lose a tempo write; three of the four inert ones keep theirs.

**`drift` is why it was findable now**: added v0.5.288, four versions *after*
the failed attempt, reading 0.00 → **1400.00** on Shockway Rider. A lost clock,
not a timbre, and no column that existed then could have said so.

With the tempo preserved: melody, seq, retrig, adsr, gate, drift, hold, onset,
tail and nrun move on **zero files**; `wave` +0.3 pp mean over 12, and **IK+ —
the file the mechanism was decoded from — loses 5**. Safe, not an improvement,
ships off.

A fourth defect fell out and was **refused**: widening the tempo scan to any
free row reaches **25 files that ship with no tempo write at all**, and
restoring one is 2 better and 3 worse. `retrig` says why — every gain moves
toward 1.0, every loss away.

### v0.5.313 — the row was not expressible, and was being rounded
Chasing "why is the derived tempo wrong on those files" found that it is not.
A gate-corrected row is `(reload+1)(O+1)/O` frames, a rational, and `-Sq`
expresses denominator q exactly. `MAX_ROW_DENOMINATOR` capped q at 6.

**The cap belongs where rounding stops working**, and the corpus says exactly
where that is:

    16/7  = 2.286 -> 2  12.5% out  |  81/20   = 4.050 -> 4  1.2% out
    20/9  = 2.222 -> 2  10.0%      |  113/28  = 4.036 -> 4  0.9%
    33/10 = 3.300 -> 3   9.1%      |  339/112 = 3.027 -> 3  0.9%

A 7.5x gap with nothing between. The old comment said the rows past six "are
within ~1.3% of a whole number anyway, so they round" — true of the right
column, false of every shape on the left, which is the whole of what a cap of
10 reaches. Raised to 10; six files re-grid and **every one gains**: `drift`
0.00 on all six, `wave` +16.1 pp mean, `gate` ≈ +30 pp, `retrig` toward 1.00.

  Warhawk -S2→-S7, Proteus -S2→-S7, Game Killer -S2→-S9, and Delta
  Mix-E-Load / International Karate / Kentilla -S1→-S10.

**Warhawk's melody reads 82 → 64% and that is the sampling artefact.** At -S7
siddump discards six calls in seven; `--equal-calls` reads **90%, retrig
1.00**. Second time that caveat has decided a ship-or-refuse — and 11 files
are now above `-S4` where 5 were.

### The version collision
A concurrent session pushed **its own v0.5.311** (LISTENING.md naming the
renderer, built on this session's v0.5.309) while v0.5.312 was being measured.
Both claimed the number; mine rebased to 312. No content conflict — theirs is
`listen.py`, mine `patterns.py` — only `CHANGELOG.md` and the version. The
suite was **re-run after the rebase** rather than carried over, and came back
1202 rather than the 1193 measured before it.

## The fifth run (v0.5.314–317): the queue, and a tool caught by its own output

No thread of its own. It took what the previous run had left owed, and the one
finding it produced came from reading an artefact rather than from looking for
a defect.

### v0.5.315 — the re-gridded files' settings were carried, not measured
v0.5.313 moved six files from `-S1`/`-S2` to `-S7`..`-S10`. Their `--fidelity`
settings had been searched at v0.5.304 against the *old* multipliers, and the
hard restart's bound is `row - 1` **calls** — so what that option is worth
changes by a factor of five or ten when the rate does. By this project's own
standard a carried setting is not a measurement.

Re-searched, 127 combinations a song, 3 shards, **42 s**. Five gained, none
lost, structural choices identical:

    Delta_Mix-E-Load  two_stage -> two_stage max_hard_restart
    Game_Killer / Kentilla / Proteus / Warhawk  (none) -> max_hard_restart
    International_Karate                        unchanged

    Warhawk           melody 64 -> 90%  seq 65 -> 90%  retrig 0.86 -> 1.00
    Delta_Mix-E-Load  gate 30 -> 53%   Game_Killer gate 64 -> 72%
    Proteus           gate 63 -> 69%   Kentilla    gate 43 -> 45%

Warhawk's row is the one to read: v0.5.313 shipped it at melody 64% with a
note that this is the `-S7` sampling artefact. It now measures 90% on a normal
trace, which is what the caveat predicted — the artefact was real and so was
the setting underneath it.

All four stamped artefacts regenerated here (0.5.313 → 0.5.315); `gate` frames
123671 → **122589**.

### v0.5.316 — VIBRATO.md against the re-gridded rates
Regenerated on demand. It had been two versions behind the multipliers it
describes, which is exactly the way a per-song option goes stale unnoticed.

### `ee76308` — an inert permission rule, no version
File permission checks match `Edit(path)` rules, which cover every
file-editing tool, so a `Write(...)` rule in `.claude/settings.json` had never
matched anything. Dropped. No converter behaviour, so no bump and no
regeneration — the first commit in this document to skip both deliberately.

### The listening set, re-staged (no version — `build/` is gitignored)
The staged pairs dated from before v0.5.313, so six files' WAVs were of a
converter that no longer existed. Re-staged whole: six `listen.py` shards,
83 tunes, 120 s a side, `sidplayfp` 2.15.2, then `--merge-notes` and
`abpage.py`. 14+14+14+14+14+13 tunes, exit 0 each, no refusal in any shard
log; 83 `.h2g.wav` and 83 `.original.wav`, every pair 120.0x s on both sides
(worst within-pair difference 0.03 s, sub-frame); 84 pages; 1.7 GB.

### v0.5.317 — merge_notes published the wrong run's header
Reading the document that staging had just produced, its first sentence was:

    Staged by `python/listen.py` (h2g 0.5.306), 30 s of subtune 0,
    rendered by `SID2WAV` at 44.1 kHz/16-bit.

Every fact in it was false about the run it described (0.5.316, 120 s, each
file's own `startSong`, `sidplayfp`) — and it is the sentence the apparatus
rests on, because a listener trusts "every difference within a pair is a
difference in the music" only if both sides really came from one engine at one
setting.

`merge_notes` folds the parts with `for src in [outdir/"LISTENING.md"] + parts`
and took the header as `head = head or h` — **first non-empty wins, and the
file already there is first**. So the preamble was always the *previous*
pass's. This is the drift v0.5.311 fixed for the single-process path
(`document_header` derives the line from what the run did) reintroduced by the
sharded path, which routes around that function entirely; `_policy_header` was
written so the claim stays true "whichever part wins the merge", and the merge
was not picking a part. `document_header`'s own docstring asserted "merge_notes
keeps the first part's header" — that was the intent, never the behaviour, and
the two readings differ only when an old `LISTENING.md` exists, which is every
re-stage.

    head = h or head          # was: head = head or h

Last non-empty wins, always a part, matching `tail = t or tail` one line below.
Sections still merge in the old order, so a re-staged tune's notes keep
replacing the stale ones — only the two whole-document fields take the last
writer.

The existing merge tests could not see it: every part and the pre-existing file
shared one `HEAD` constant, so the two candidate headers were the same string.
The new test uses two different ones and was **confirmed to fail on the old
line** (reverting it alone: 1 failed, 8 passed). 1203 passed, 3 skipped.

**The general shape.** The tool that stages evidence is itself evidence, and
nothing in this repo scores it. Both defects in the listening apparatus so far
(v0.5.311's constant, v0.5.317's merge order) were found by *reading its output
as prose*, not by a check — and both had a passing test suite over them at the
time.

## The sixth run (v0.5.319–325): a per-song plan, three songs worked, and the listening rig grown into an instrument

Driven by the task runner (`.claude/tasks/whattask.json` + `runs.jsonl`): 7
runs closed in this window, 14 task ids closed in total, 38 open. **No commit
in this run changed a converted byte.** `python/h2g/` was touched once
(`patterns.py`, comment-only, v0.5.320); everything else is docs, `listen.py`
and `abpage.py`.

### v0.5.319 — `PER-SONG-PLAN.md`, the loop and the metric audit
Three user questions answered in one document (`PER-SONG-PLAN.md`, 10 KB):

* **The loop**, nine steps, every one a tool that already exists — score →
  `--diagnose` (a low row is a claim about the harness until it is a claim
  about the converter) → `--pace` (a wrong clock poisons every per-frame
  column) → the four censuses (`--census`, `--hold-census`, `--vib-census`,
  `--gate-census`) → `songview.py` → listen → read the player → byte-hash +
  `--baseline` A/B at `-t 60` → ship or refuse with numbers. One song per
  session; the corpus A/B at the end is the guard rail.
* **A shortlist of five songs in order**, Knucklebusters first (since struck —
  see v0.5.323).
* **The metric audit.** Register *coverage* is closed — `FIDELITY.md`'s
  generated tail says every SID register is read by some dimension. The gaps
  are *inside* registers already read, and one was written down nowhere:
  **sync and ring modulation (`$D404` bits 1–2) are scored by nothing.**
  `wave` compares `x & 0xF0` and its own comment excludes the low nibble;
  `gate` reads bit 0 alone. A conversion could drop every ring-mod effect in
  the corpus and no number in the report would move. Same blindness class as
  the gate axis before v0.5.270. Also unscored: resonance (`$D417` high
  nibble), master volume (`$D418` low nibble), and sweep *direction* (`pul`
  and `cut` count movement without judging it).
* **On GT track effects and tables**: the harness scores register outcomes
  rather than GT commands *on purpose* — a command is a means, and scoring it
  would mark a correct-sounding alternative encoding as wrong. GT-side
  structure is already covered by `tests/test_table_validation.py` and
  `songview.py`.

### v0.5.320 — the tempo refusal re-measured, and the `plain` bucket split
Two findings from the task runner; comment and documentation only.

**The widened `apply_tempo` A/B, re-run at `-t 60` on top of v0.5.313's
re-grid and v0.5.315's re-search.** It reaches exactly **25 of 83** files;
**19 move no printed number**; of the 6 that do, **2 gain and 4 lose**:

    Knucklebusters    melody 50 -> 81%   retrig 0.39 -> 0.69   gain
    Geoff Capes       melody 49 -> 60%   retrig 3.21 -> 2.40   gain
    Warhawk           melody 90 -> 47%   retrig 1.00 -> 0.34   loss
    Delta Mix-E-Load  seq   100 -> 57%   retrig 1.00 -> 0.40   loss
    Human Race        melody 65 -> 56%   retrig 2.28 -> 5.57   loss
    Rasputin          melody 75 -> 73%   retrig 1.66 -> 1.72   loss

`retrig` is exact as a tell: every gain moves toward 1.0, every loss away.
**The re-measurement strengthened the refusal.** The previous handoff had
recorded that Warhawk's old 82→56% was measured against a file that no longer
exists and implied the evidence was void; it is not — Warhawk now *starts* at
90%, so the loss is 43 pp where it was 26. Reports: `build/AB_TEMPO_WIDE.md`,
`build/AB_TEMPO_SCOPED.md`.

**One explanation proposed, tested and killed before it reached the record**:
that the widened write drops subtune *k*'s value on a row another subtune
plays. It fits perfectly (the two worst losers have the widest per-subtune
spread — Warhawk 8..40 calls a row at `-S7`, Delta 20..127 at `-S10`, against
[3, 6] for Knucklebusters). A variant restricting the write to patterns no
other subtune references is **byte-identical on all six files**, so those
patterns are already exclusive and sharing is not the cause. The surviving
lead, explicitly untested: the widened write is a tempo *change* mid-pattern,
re-applied every playthrough, with damage tracking distance from
Goattracker's default of 6.

**The `plain` vibrato bucket is four problems, not one.** Read each absent
instrument's source record back out of the shipped `.sng` — the converter
stamps `NN:b5-b6-b7` into the instrument name and `vibrato_offset` is 5 on
every file here, so **b5 *is* the classic vibrato byte** — and the 35 absent
rows (31 convertible) split:

    17  b5 = $00, no vibrato in the record at all. The original oscillates
        anyway, so the mechanism is UNDECODED and is not the classic pair --
        Flash Gordon 936 reversals, Chain Reaction and Zoolook 525 each,
        Hollywood or Bust 441
     6  nonzero AND a speed-table entry already emitted (vib_ptr 1, 3, 4, 19,
        24, 26) and the census still scores 0 -- a question about the COLUMN
     3  nonzero, no entry: the only true refusals, ALL THREE Powerplay Hockey
     5  no instrument at that ADSR in our output at all (Battle of Britain,
        Game Killer, One Man and his Droid x3)

Also established: 17 of the 25 files **do** have a vibrato table detected
(9797 of the reversals); 8 do not (2993). So the largest group is a *decode*
job, not an emit job, and the one-agent-one-emitter fan-out the previous
handoff proposed would have changed the smallest part of it.

### v0.5.321 — `abpage.py` draws both sides on one canvas; the pages declare UTF-8
`PER-SONG-PLAN.md` § 3b. Every A/B page carries a "Both sides, drawn" card:
peak envelopes for both renders on one canvas (original in the Source A rust,
ours in the Source B teal, 1400 columns), a `|difference|` strip on the same
time axis, a playhead, and click-to-seek moving both players together.

    Knucklebusters   canvas visible, 37.0% of pixels painted, mean |d| 8.1%
    Human_Race       main 31.2%, difference strip 9.3%, mean |d| 6.6%
    click-to-seek    25% -> 29.96s, 50% -> 60.00s, 90% -> 107.97s of 120s

**It is deliberately not a score, and the page says so**: amplitude shows
dropped/extra notes, note lengths, missing drums, silence and tempo drift; it
cannot show pitch, timbre or filter, because two different notes of the same
loudness draw the same shape. `mean |delta|` is labelled as how far apart the
two *pictures* are.

**A second defect, pre-existing and found by this one.** The pages carried no
`<meta charset>`, so Chrome decoded them as `windows-1252`
(`document.characterSet == "windows-1252"`). That affected **every page ever
generated** — any non-ASCII byte in a tune name or a staged note rendered as
mojibake — and went unnoticed because the templates emit `&mdash;` and friends
as entities. The Δ in the new legend was the first raw non-ASCII character on
a page and showed up as `mean |Î”|`. Both templates now declare UTF-8.

**How the seek was verified, and what that does not claim.** Media elements do
not load in the automation tab: `visibilityState` is `"hidden"`, Chrome
throttles media there, and `readyState` stayed 0 after an explicit `load()`
and twenty seconds of waiting — not the network (the same WAV fetches in
19 ms) and not the page (a 0.5 s silent data-URI WAV appended by hand also
never left `readyState` 0). The three seek positions were therefore measured
with `duration` stubbed and `currentTime` intercepted. Whether Chrome seeks a
*loaded* element was not tested.

### v0.5.322 — the pages correct the startup lag, and `abpage.py` serves itself
Two faults reported from listening: the renders are not in sync, and the
envelope overlay shows an error instead of a drawing.

**The sync.** They were never in sync, and by a knowable amount. gt2reloc's
packed player reaches its first note 3–8 frames after the original —
`startup_lag`, corrected in every per-frame column since v0.5.175 — and
**nothing corrected for it on the listening side**, so each A/B ran with one
side 120–155 ms late: audible as a flam on the switch, in a rig whose whole
purpose is that switching does not lose your place. Measured from the audio,
per tune, on load:

    Knucklebusters 154 ms (7.7 frames)   Commando 150 ms (7.5)
    Human Race     127 ms (6.3)          Warhawk  116 ms (5.8)
    Auf Wiedersehen Monty 146 ms (7.3)

— the 3–8 frame band `FIDELITY.md` documents, arrived at independently. B runs
ahead of A at all four places the players are tied together, and the drawn B
shifts with it so the picture cannot contradict the ears. A slider (±500 ms,
1 ms steps) overrides by hand, with `auto` and `0` buttons.

**Correlation was tried first and is the wrong instrument.** Cross-correlating
onset envelopes over 60 s comes out flat: on Knucklebusters the top six lags
were 41, −10, −28, 59, 52 and −17 columns, all within 3% of each other,
because the two sides drift apart and often play different numbers of notes
(156 against 404 there). **A start offset is a property of the START**, and
the first onset is where it lives; the difference of first onsets is stable on
every file tried. The first prominence guard was also wrong in a way worth
recording: it refused a peak that did not beat the **runner-up** by 5%, and on
any smooth correlation the runner-up is the adjacent lag — so it refused
everything. Prominence is measured against the best score *outside a window*,
or not at all.

**The drawing.** The overlay reads both WAVs with `fetch()`, which no browser
allows over `file://`. So the tool is now the web server: `python abpage.py
--serve` builds the pages and hosts `build/listen` on `127.0.0.1:8730`.
Playback and the sync slider work over `file://` either way; only the drawing
and the automatic offset need http.

### v0.5.323 — Knucklebusters refused for scoping: the tempo write is not its lever
`PER-SONG-PLAN.md` had named it the first song to work and called the widened
tempo write "a *known* +31 pp lever". Worked, and the premise does not survive
the file's own bytes. Read out of the shipped `.sng` with
`songview.parse_sng`:

    subtune 0: entry pattern 29  CMD_SETTEMPO row 0 -> 6
    subtune 1: entry pattern  0  CMD_SETTEMPO row 0 -> 3
    subtune 2: entry pattern 29  CMD_SETTEMPO row 0 -> 6

**Every subtune already has its tempo write** (two patterns hold three writes
because 0 and 2 enter on the same pattern — that is what the converter's "in 2
pattern(s)" counted). So there is nothing for a widened scan to add, and the
corpus A/B's 50→81 pp gain has **no identified mechanism** — the same position
Human_Race reached.

**The rate is wrong and cannot account for it.** `--diagnose` traces subtune 1
(the header's startSong 2), whose row is 7/3 = 2.33 frames against the 3 we
write: 28.6% slow, predicting ~0.78 of the original's attacks where `retrig`
measures **0.39**. `--pace` refuses the file outright ("IQR spans 56% of the
median"), which by this repo's own rule is a mechanism rather than a constant.

**What actually limits the file is structural**, each larger than the tempo:
our `.sng` carries **3 subtunes against the header's 11**; the subtunes want
**mutually incompatible multipliers** (1, 3, 8, 8, 8, 4 for 0–5) while the file
packs `-S1`, so five of six play at a rate no single `-S` can express; and on
the traced pair voice 0 is "under-produced: 16 attacks against 48", voice 1
matches at ratio 0.69, and **voice 2 is different music** (pitches 14% the
same). It re-enters the loop as a subtune/structure question.

**A hypothesis refuted mid-task and recorded rather than dropped**: that the
traced subtune had *no* tempo write and ran at Goattracker's default 6 against
the 7/3 it wants, because 2.33/6 = 0.39 matches `retrig` 0.39 exactly. A clean
arithmetic fit, and wrong — the subtune has a write, value 3.

### v0.5.324/325 — per-voice A/B, a facts card, a register panel, a tracker view
(One commit, `3894a63`; **`0.5.324` exists in `CHANGELOG.md` with no commit of
its own** — the second version collision this document records.)

**Per-voice A/B.** `listen.py --voices` stages each voice alone on both sides
through `sidplayfp -u`, and the page gained a selector that swaps **both**
sources to the same voice. Knucklebusters: six extra WAVs at 120.02–120.03 s;
Voice 2 swaps to `.v2.original.wav` / `.v2.h2g.wav`; All restores the pair; the
sync offset survives the swap (154 ms throughout) — the startup lag belongs to
the two players, not to which voice is audible.

A renderer that cannot mute **refuses** a per-voice render rather than
returning the full mix: three identical "solo" files would poison a listening
pass in a way nothing downstream could catch. The mute is real — the three
solos are mutually uncorrelated (0.008, 0.024, −0.013 on the original; 0.006,
0.011, 0.003 on ours), none byte-identical, each about a third of the energy
(RMS 1989/1709/2249 against 3604 full).

**What the sum check does NOT show, stated rather than dressed up**: v1+v2+v3
correlates only 0.12 with the full mix at zero lag and peaks at 0.50 (original)
/ 0.55 (ours) at about **+7 ms**, because separate `sidplayfp` runs do not
start on the same sample and **the SID filter is shared** — a soloed voice
passes a filter the other two no longer feed. The ~7 ms inter-run offset is
worth carrying: switching voices in the page can jump by that much, and it is
**not** the startup lag the sync slider corrects. Also true by construction
rather than measurement: `-u` is a sidplayfp *output* flag and the register
trace comes from siddump, which never sees it, so muting cannot reach the play
routine.

**A facts card**, from artefacts the page already quotes — `SURVEY.md` for the
player identification and structure, `presets.json` for the packing rate and
per-song options. Knucklebusters reads "SUBTUNES 3 (hdr 11)", the loss
v0.5.323 found, now on the tune's own page.

**A register panel**, modelled on the SID capability matrices analysis tools
show, with the difference that matters: every row carries **both** sides.
Waveform classes, test bit, hard sync, ring modulation and two "repeatedly
changes" counts, per voice, lit live at the playhead. It earned its keep on the
first tune — Commando:

    voice 1  orig: ring w1 w4 w8       ours: ring test w1 w4 w8   ours-only: test
    voice 2  orig: ring sync w1 w4 w8  ours: ring sync test w1 w4 w8  ours-only: test
    voice 3  orig: w4 w8               ours: test w4 w8           ours-only: test

We set the test bit on all three voices where the original never does — the
`$09` hard-restart frame. **Hard sync and ring modulation are read by no column
in `FIDELITY.md`**, so for those rows this panel is the only place in the repo
the two sides are compared at all. Data is siddump's own change list;
`listen.py` writes `<name>.trace.json`, and `--traces-only` rewrites just those
in two siddump runs a tune instead of eight renders.

**A tracker view** — GoatTracker's own pattern display of the subtune the WAVs
are of: three channels, note/instrument/command, following our render's clock,
current row scrolled to centre. Built from the staged `.sng` with
`songview.parse_sng`, embedded rather than fetched so it works over `file://`.
Verified: at 20 s it lands on row 333, which is frame 1000 over 3 frames a row.
Two notes on it — a `CMD_SETTEMPO` below `$80` sets **all three** channels
(`gplay.c:494`) and `apply_tempo` writes it into voice 0's entry pattern only,
so a per-voice walk that tracked its own tempo left voices 2 and 3 on the
fallback and drifted them to half speed (the song tempo is now found once,
globally); and the row timing is *derived* from the tempo written into the
file, so where the row rate is wrong **the view drifts against the audio** —
left visible on purpose, because that is the defect this repo hunts and a view
that silently re-synced would hide it.

**A defect introduced and fixed in the same run**: `abpage` discovers tunes by
globbing `*.original.wav`, so the per-voice files registered as three extra
songs and got pages of their own. Discovery now skips a `.v[123]` suffix.
Three stale pages had to be deleted by hand — **`abpage` does not prune**,
which is latent for any renamed tune.

Also `build/listen/Listen.ps1`, a double-clickable launcher that starts
`--serve` and opens the index, written **by** `abpage.py` on every build
because `build/` is gitignored and a hand-placed file would vanish on a clean
checkout.

### The three songs worked, and what they all turned out to be

Three per-song runs and one gate probe landed on the **same** defect, which is
the largest finding of this run:

**Geoff Capes (`retrig` 3.21) — the entire deficit is note LENGTH.**
`--diagnose`: correspondence is the identity where legible (s6→o6, s7→o7 both
100%); at s0 all three voices are "over-produced" by the same factor — 113
against 35, 113 against 35, 275 against 86 (3.23/3.23/3.20) — with **pitches
100% the same on every voice**. `--pace`: our row 3.00 frames, ours/theirs
1.000, IQR 1.000–1.000 over 153 gaps, drift +0.00, "0% out". Plus pitch 100%,
onset 100%, tail 100% — and **hold 0%**. We play the right notes at the right
moments with the right timbres and re-strike each one ~3.2× instead of holding
it. The durations *are* present and read: the status byte's low-5-bit wait
field averages 9.37 over 798 status bytes, with many values 15–31, against the
original's ~11.6 rows per note on voice 2. Not a missing duration field.

**It does not contradict the tempo-write lead.** That lead models damage to a
*correct* baseline; Geoff Capes' baseline is already broken in the direction
the write happens to help, so lengthening its rows cuts the attack count toward
the original's. The "gain" is a partial masking of the note-length defect.

**Corpus-wide: 46 of 95 files read `hold` 0%**, and the retrig ladder tracks it
— Kings_of_the_Beach_ingame 7.82, Geoff_Capes 3.21, Human_Race 2.28 at the
top, while many `hold`-0% files sit at retrig ~1.0 and melody 97–100%. So
`hold` 0% is not fatal by itself, but **every badly over-triggering file has
it**. (`hold` is declared blind above `-S3`; these files are `-S1`, so it is
meaningful here.)

**Human_Race — the drift/wave gain is a population artefact, and the "skip
table" reading of it was wrong.** With the widened write: 490 attacks against
88 (retrig 2.28→5.57), drift −250.0→−7.81, wave 63→89% — while melody 65→56%,
seq 57→56%, onset 100→67%. `drift` is a Theil–Sen fit over **matched onsets**
and `wave` carries a lag estimated from **first attacks**, so both are computed
over a population those 289 extra attacks rewrite. The tell: `--pace`'s
estimate of **the original's** row moves 5.33→4.00 frames, which is impossible
as a fact about the original.

Then a follow-up run (`human-race-skip-table-undetected`, at `3894a63`)
**refuted the mechanism the first run proposed**: the file has *no outer gate*
at all. Its play routine opens `INC $0DE2` — a free-running counter, where both
`OUTER_GATE` and `OUTER_GATE_RTS` require `DEC` — and `$0DE2` is read in three
places, all effect masks (`$0B10` `AND #$07 / CMP #$04 / BCC / EOR #$07`, a
triangle LFO; `$0C97` `AND #$01`; `$0CB3` `AND #$07 / BEQ`). `_find_outer_gate`
returns `()` **correctly**. The only gate is the inner one at `$09C0`
(`DEC $0DCE / BPL +6 / LDA $0DCF / STA $0DCE`), read correctly; the per-subtune
table at `$0DD0` is `[3,3,2,3,1,0]`, so subtune 0's row is reload+1 = **4
frames**, and our `.sng` writes `CMD_SETTEMPO 4` at `-S1`. **Both sides run 4
frames per row. There is no row-length error on this file.** What `--pace` was
measuring is matched note *gaps*: 201 attacks against 88 with `hold` 0%, so our
gaps collapse toward one row while the original's average 1.33 — 4.00 against
5.33, ratio 0.750.

**Auf Wiedersehen Monty — the queued "voice 2 holds `$41`, 194 attacks against
14" fact does not exist in any build.** Control-register census of both sides
at `-m1`, 3000 frames, values carried forward (siddump prints `..` for an
unchanged field). Voice 2 original: gate-on 2413, gate-off 587, edges 194,
histogram `$41`:2173 `$40`:585 `$81`:240. Ours: gate-on 2600, gate-off 400,
edges **197**, histogram `$41`:2190 `$40`:393 `$81`:213 **`$09`:197**. Forcing
`--rest-wave-silence` gives a byte-identical census. What *is* wrong on voice
2: (1) 197 frames in `$09` (test bit + gate) the original never uses — exactly
our gate-edge count, one test-restart frame per note, same on voice 0 (107/107)
and voice 1 (152/152); (2) released frames 400 against 585, each release about
a third shorter. `--diagnose` puts the traced pair at melody 100%, all three
voices ratio 1.00, pitches 100%. **Third file in a row landing on the
note-length defect.**

**"Plays something else" — both rows compare two different pieces of music,
and `--diagnose` says so outright.** `Dragons_Lair_Part_II` (header 10
subtunes, startSong 1 traced as 0, our `.sng` 10, `-S2`): matches ≥50% are
s0→o9 60%, s1→o7 70%, s5→o2 62%; the printed pair s0/o0 is **15%**. At the
diagonal all three voices read "different music" (pitches 36/25/17%); at the
real counterpart o9, voices 0 and 1 match (0.77/0.78, pitches 64/58%) and voice
2 still reads different music at 26%. **CLAUDE.md's "94/98/97%" for this file
is stale** — the best counterpart is 60%, so correcting the correspondence
moves the row to ~60% and leaves a real defect underneath.
`Commodore_64_Music_Examples` (header 15, our `.sng` 15, `-S1`): the only match
≥50% in the whole matrix is **s1→o0 at 93%** — a clean off-by-one, the
conversion is good and the numbering is shifted; its 16% row is entirely a
harness artefact. What is *not* explained: **the original's s0 has no
counterpart anywhere in our 15**. Full outputs in gitignored
`build/diag_<name>.txt`.

</work_completed>

<work_remaining>

Ordered by value. Tags per CLAUDE.md: `[subagent]` = one agent in its own
worktree (brief it to copy `python/tools/siddump-rt/siddump.exe` in, touch none
of the generated files, return a `git diff`); `[main]` = this session only;
`[user]` = needs a human.

### 1. Listen — `[user]`, and it is **ready and current**
This item has been the immediate next action in four consecutive handoffs and
was blocked each time by the apparatus, not the will. It is not blocked now,
and as of the fifth run it is not stale either.

**Open `build/listen/index.html`.** 83 tunes, 120 s each, every pair rendered
by one engine at exactly 120.0x s, each with an A/B page that swaps sources
gaplessly and a blind mode that keeps score. Nothing needs regenerating: the
set was re-staged at **v0.5.316**, after the six files v0.5.313 re-gridded and
the settings v0.5.315 re-searched, so every pair is of the converter as it
stands. `LISTENING.md`'s preamble now states that run rather than a previous
one (v0.5.317).

The four questions worth taking first, because each has a decision waiting on
it:

* **`gate` has never been validated by ear.** It was built at v0.5.270 because
  no other column could see the register it reads, and it has since driven
  three shipped decisions — `--rest-keyoff` into `always`, and both
  hard-restart bounds. `W_A_R_Preview` scores 99% on it and `W_A_R` 80%; if
  the column is real those should sound correspondingly right.
* **`Saboteur_II`** is the file `keeps_notes` refused at both wider bounds. If
  it sounds fine as shipped, the guard was right twice on its own.
* **`Auf_Wiedersehen_Monty`** carries the open bit-6 fact (item 2): voice 2
  holds `$41` where the original drops to `$40`, 194 attacks against 14.
* **Anything in *plays something else*** — Commodore_64_Music_Examples,
  Dragons_Lair_Part_II, Geoff_Capes_Strongman_Challenge,
  Kings_of_the_Beach_ingame.

Two verdicts in the previous run each opened a productive thread (IK+ →
§§ 7.nnnnn–ppppp, Knucklebusters → the vibrato census), which is the argument
for the format. For interactive editing use `.\play.ps1 <file> -Presets
presets.json`, **never `goattrk2.exe` directly**.

To re-stage after a converter change:

    cd python
    python listen.py <sid_dir> --all -t 120 --presets ../presets.json --shard 0/6
    ... one process per shard, 0..5 ...
    python listen.py --merge-notes
    python abpage.py

### 2. ~~The bit-6 rest's waveform~~ — **closed at v0.5.312**
The −43 pp was `apply_tempo` losing its write to an occupied command column,
not anything about waveforms. `--rest-wave-silence` exists, is measured, and
ships **off**: with the tempo preserved it moves no structural column on any
file, `wave` +0.3 pp mean over 12, and IK+ — the file it was decoded from —
loses 5. What is left is not a bug but a judgement, and a listener could
settle it: `build/listen/IK_plus.html` and `Auf_Wiedersehen_Monty.html` are
staged, and AWM is the file that gains most (+8 pp `wave`).

~~One fact from the thread is still unassembled: Auf Wiedersehen Monty's
voice 2 holds `$41` continuously where the original drops to `$40` at each note
end, 194 attacks against 14.~~ **Refuted at v0.5.323's run — the split does not
exist in any build.** A control-register census of both sides shows we drop to
`$40` on 393 frames and our gate edges are 197 against the original's 194 (not
14); forcing `--rest-wave-silence` gives a byte-identical census. 194 is
recognisable as the original's voice-2 gate-edge count, but nothing in either
build produces 14. What voice 2 *does* show: 197 frames of `$09` the original
never uses (one test-restart frame per note), and released frames 400 against
585 — the note-length defect, not a held gate. The item is **retired** in favour
of `awm-release-length`.

### 2b. ~~The 25 files with no tempo write~~ — **re-measured and refused again at v0.5.318**
The A/B below was re-run on top of v0.5.313/315 as this item asked. It reaches
exactly **25** files; **19 move no printed number**, and of the 6 that do,
**2 gain and 4 lose** — Knucklebusters melody 50→81% and Geoff Capes 49→60%
against Warhawk 90→**47%**, Delta Mix-E-Load seq 100→57%, Human Race 65→56%
and Rasputin 75→73%. `retrig` remains exact: every gain moves toward 1.0,
every loss away.

**The re-measurement strengthened the refusal rather than reopening it.** The
note below said Warhawk's loss was measured against a file that no longer
exists — true, and the current Warhawk loses *more*: 43pp from a 90% start
where the old figure was 26pp from 82%.

**One explanation was proposed, tested and killed** before it reached the
record: that the widened write lands on a row another subtune plays. A variant
restricting it to patterns no other subtune references is **byte-identical on
all six files**, so those patterns are already exclusive. The surviving lead —
untested — is that the widened write is a tempo *change* mid-pattern rather
than an opening tempo, re-applied every playthrough, with damage tracking the
distance from Goattracker's default of 6: Warhawk derives 8..40 calls a row and
Delta Mix-E-Load 20..127 against [3, 6] for Knucklebusters. Reports:
`build/AB_TEMPO_WIDE.md`, `build/AB_TEMPO_SCOPED.md`.

**Human Race is the one file worth a scoped rule**: the write takes its drift
from **−250.00 to −7.81** and its `wave` from 63 to 89% while costing 9pp of
melody and tripling retrig. The clock and the note stream disagree there, and
no other file in the set does that.

The original item, for the record:

### 2b-orig. The 25 files with no tempo write — `[main]`
Found at v0.5.312 and deliberately **not** fixed. `apply_tempo` writes into the
row each subtune enters on and skips the subtune entirely if that row carries a
command; 25 corpus files have no tempo write for that reason. Restoring one is
**2 better and 3 worse** — Knucklebusters melody 50 → 81% and Geoff Capes
49 → 60% against Warhawk 82 → 56%, Delta Mix-E-Load's sequence 97 → 57% and
Human Race 65 → 56%.

`retrig` is the tell: every gain moves toward 1.0 and every loss away from it,
so on the losers the *value* that would be written is wrong and the missing
write was accidentally protecting them. v0.5.313 fixed one cause of a wrong
value (an unexpressible row) for six files — **re-run this A/B on top of it**
before concluding anything, since three of the five files named above are in
neither set and may now behave differently. Warhawk *is* in both sets and has
moved twice since the A/B was taken: re-gridded at v0.5.313 and given
`max_hard_restart` at v0.5.315, melody 64 → 90%. Its 82 → 56% is the loss the
refusal rested on, and it was measured against a Warhawk that no longer
exists.

### 3. The vibrato shortfall, by bucket — `[subagent]` per bucket
`VIBRATO.md`, 136 instruments / 42618 reversals missing, **114 emitting nothing
at all**. The buckets are now trustworthy for the first time in the run:

| cause | absent | slow | reversals | note |
|---|---:|---:|---:|---|
| plain | 34 | 14 | 17912 | the record's own vibrato byte |
| drum | 26 | 3 | 9847 | bit `$01`'s sweep |
| pitchseq | 13 | 1 | 5782 | |
| arp | 18 | 0 | 4786 | **global phase — a per-note wavetable cannot hold it** (§ 7.ttt) |
| program | 13 | 2 | 2923 | |
| atkpitch | 5 | 1 | 569 | |

`arp` is the one to *not* take: § 7.ttt measured that emitting it costs 5 points
of mean melody, and `fidelity_better` cannot select it. One agent per bucket is
the natural fan-out.

**`plain` is not one queue, and it is not mostly an emitter problem.** It was
taken as "34 instruments whose own vibrato byte we ignore" and it is nothing
of the kind. Reading each absent instrument's source record back out of the
`.sng` we ship — the converter stamps `NN:b5-b6-b7` into the instrument name,
and `vibrato_offset` is 5 on every file here, so **b5 is the classic vibrato
byte** — splits the 35 absent rows (31 convertible; W_A_R and Dragons Lair are
two of the three files that do not convert at all):

| what the record says | inst | what it means |
|---|---:|---|
| **b5 = `$00`** | **17** | the record carries no vibrato. The original oscillates anyway, so the mechanism is undecoded and is *not* the classic pair — Flash Gordon 936 reversals, Chain Reaction and Zoolook 525 each, Hollywood or Bust 441 |
| b5 nonzero, entry **emitted** | 6 | we already write a speed-table entry (`vib_ptr` 1, 3, 4, 19, 24, 26) and the census still scores the instrument 0. Either the depth rounds away or the attribution is wrong — a question about the *column*, not the emitter |
| b5 nonzero, **no** entry | 3 | the only true refusals, and **all three are Powerplay Hockey** — the two-player file of § 7.iiiii |
| no instrument at that ADSR | 5 | Battle of Britain, Game Killer, One Man and his Droid ×3 — we never emit an instrument with that envelope |

So the bucket's 17912 reversals are at least four different problems, and the
biggest of them is a **decode** job rather than an emit job. Nothing here is
the one-agent-one-emitter change the fan-out assumed. Do not brief an agent to
"emit the record's vibrato byte" for `plain`: on 17 of 31 there is no byte to
emit.

Two cheap follow-ups fall out. The 6 "entry emitted, still zero" rows are worth
one look at whether `_classic_vibrato_entry`'s `rshift` can round the step to
nothing before any emitter work is done, and Powerplay's 3 belong with the
two-player thread rather than with vibrato.

### 4. ~~Re-grid the rows for drift~~ — **closed at v0.5.313**, residual below
Raising `MAX_ROW_DENOMINATOR` to 10 re-gridded six files and every one gained;
their settings were re-searched at v0.5.315. The corpus now reads **52 of 79
exact**, the other 27 at a median 8.9 frames per 1000, worst Rasputin −355.8.

What is left is the **17 files whose drift is exactly `-1/(skip+1)`** — the
outer gate's skipped call, which `effective_frames` declines to correct when
the corrected row cannot be packed (IK+'s 3 × 113/112 wants `-S112`). The 7.5x
gap in the rounding table says a cap above 10 buys nothing, so the honest
outcome here may be a committed statement that these 17 are a format limit
rather than a fix. **Changes packing either way, so `[main]`.**

**But the 17 is a hardcoded literal.** `fidelity.py:3733` emits
`f'On 17 files this is exactly \`-1/(skip+1)\`'` as plain text inside a
generated summary — nothing computes it, so it prints 17 whatever the corpus
does. A real count over the current corpus is **3** (Human_Race,
Las_Vegas_Video_Poker, Samantha_Fox_Strip_Poker), and **all three have no outer
gate at all**, so even those three are coincidence rather than the skipped call.
`drift-residual-17` is named after that literal; **re-scope the item before
working it**, and fix the literal either way (task
`fidelity-hardcoded-drift-count`, not yet in `whattask.json`).

### 5. The gate axis's remaining 122589 frames — `[main]`
Mean gate overlap **52%**; 122589 frames still sustain a voice the original
released (129106 at v0.5.313; the six re-gridded files account for the
difference, not a change to this axis). v0.5.274 established that `held` has no long tail and is the same
mechanism `hold`'s `fetch` owns, so this is not a new mechanism to find.

**The hard-restart bound is now exhausted as a lever.** v0.5.302 and v0.5.304
made it a three-way per-song choice (`row // 2`, `2 * row // 3`, `row - 1`);
12 files moved, mean gate 47% → 50%, and `row - 1` is the player's own ceiling
— there is no fourth value. What is left needs the next-note fetch itself,
which has one measured non-answer (`--no-test-restart`, −26.3pp melody) and
nothing else tried.

Two things a next attempt should know. `keeps_notes` has now refused a
candidate on Saboteur II **twice**, unprompted, so the guard is trustworthy for
a bolder experiment than would otherwise be defensible. And a seventh toggle
costs 11 minutes sharded, so the objection that killed this item for 26
versions no longer applies to anything.

### 6. Powerplay's cue-length stall — `[subagent]`
§ 7.kkkkk. Each cue's length byte at `$3B37,X` feeds a counter that skips a
speed-gate tick on underflow **and**, on the call it reads zero, declines to
advance the orderlist. The first half lands correctly as the outer-gate skip;
the second is a further stall per cycle no Goattracker tempo expresses. Cue
lengths are approximate and a cue that ends in the original loops here.

### 7. Chimera's clamped startup lag — `[subagent]`
`FIDELITY.md` reports one file measuring a lag too large to be a startup
latency (Chimera, 438 frames) and clamping rather than correcting. Unexamined.

### 8. The method doc has run out of section letters — `[main]`
`H2G-CONVERSION-METHOD.md` is at **§ 7.zzzzz**. The five-letter run is
exhausted; the next section needs a scheme, and choosing one is cheaper before
four parallel forks each invent a different one — which is exactly what
happened twice this run with `7.bbbbb`.

**Seven sections are now owed**, all blocked on the same missing name:
`--wide-hard-restart` (v0.5.302), `--max-hard-restart` and the three-way row
bound (v0.5.304), `MAX_ROW_DENOMINATOR`'s cap and the six re-gridded files
(v0.5.313), the re-search at the new rates (v0.5.315), `merge_notes`' header
order (v0.5.317), the widened-tempo refusal and the `plain` bucket's four-way
split (v0.5.320), and the listening rig's startup-lag correction (v0.5.322).
The backlog grows by one per run while the question stays unanswered, and each
is a finding that currently exists only in a commit message. Ids
`method-doc-section-scheme` (`[user]` — it is a naming decision) and
`method-doc-owed-sections` (`[main]`).

### 9. Older, still open
* `songview.py`'s **live render check**, owed since v0.5.243. Chrome extension
  reported not connected; serve `build/` over `127.0.0.1` (Chrome MCP cannot
  open `file://`). `[user]` or `[main]`.
* `instrmap.py` still overlaps `songview.py --compare`.
* No noise-pitch column.
* Bit `$10`'s global arpeggio, decoded and unemitted (§ 7.ttt) — same reason as
  bucket `arp` above.
* Three corpus files fail to convert; 12 are out of scope by construction.

### 10. ~~The note-length defect~~ — **worked at v0.5.328: it was three
### different things, and the two worst were the harness**
The item was framed as one defect behind `hold` 0% on 46 of 95 files, with
Geoff Capes as its cleanest statement and the `retrig` ladder
(Kings_of_the_Beach_ingame 7.82, Geoff_Capes 3.21, Human_Race 2.28) as its
corpus signature. Worked one file at a time, per `PER-SONG-PLAN.md`, and the
cluster split three ways:

**1. `hold` 0% is mostly the one-frame next-note fetch, not a length loss.**
`--hold-census` on Geoff Capes classifies **4 of 4** comparable instruments as
`fetch` — `delta == -1`, one frame, Goattracker's `gatetimer & $3f` early
fetch, the artefact `--no-test-restart` removes outright. Nothing on that file
is `short`, `long` or `slot`. So a `hold` 0% row does not by itself mean the
notes are the wrong length, and the corpus figure cannot be read as 46 files
of note-length loss.

**2. Geoff Capes and Kings of the Beach ingame were being charged for a loop
the original never plays** — a *measurement* defect, now fixed. The original's
subtune ends inside the window (last attack at frame 768 and 322 of 3000) and
plays nothing after it; Hubbard's `$FE` means *tune ended*, a Goattracker
orderlist cannot say that, so `--legal-restart` restarts at position 0 and we
play the tune three or seven more times. Measured over the music the original
actually has:

    Geoff Capes (17s)      retrig 3.21 -> 1.02   melody 49% -> 100%   seq 47 -> 99%
    Kings of the Beach (8s) retrig 7.82 -> 1.04  melody 23% -> 98%    seq 23 -> 98%

`fidelity.original_ended` (v0.5.328) is the rule, `tests/test_original_ended.py`
pins it, and the report names the rows it shortened. Corpus: **exactly those
two rows move**, *plays the same music* 56 → **58**, *plays something else*
4 → **2**, mean melody 91% → 93%. Both files leave the queue.

**3. What is left is genuine, and it is two files, not forty-six.**
Human_Race really does over-trigger (voice 0: 40 attacks against 120, and its
original plays to frame 2816, so no truncation applies) and Auf Wiedersehen
Monty really does release short (400 frames against 585) while its note
*counts* match within 3. Those are the note-length question, and they are what
`hold-zero-note-length-loss` should be re-scoped to.

**Refuted on the way, cheaply, and recorded so it is not re-tried:** that the
vibrato command displaces the tie. 91.5% of Geoff Capes' note rows carry
`CMD_VIBRATO` and the tie block requires `cmd1 == 0`, which fits perfectly —
and converting with `vibrato_command=False` leaves TONEPORTA at **10 rows
either way**, so the column is not what drops it. The file simply has ten tied
events.

### 11. Two report rows compare different music — `[main]`
`--diagnose` names the correspondence for both and neither is the identity:
`Dragons_Lair_Part_II` s0→o9 60% (the printed pair is 15%) and
`Commodore_64_Music_Examples` s1→o0 **93%** (printed pair 14%). The second is a
clean off-by-one — the conversion is good and only the numbering is shifted —
so its 16% row is entirely a harness artefact. The first is only *partly*
harness: 60% is its best counterpart and voice 2 still reads "different music"
there, so correcting it exposes a real defect. **`CLAUDE.md`'s 94/98/97% figure
for `Dragons_Lair_Part_II` is stale and should not be quoted again.** Ids
`subtune-correspondence-rows`, and `c64-music-examples-missing-s0` for the
original's s0 having no counterpart in our 15.

### 12. A `ctrl` column for sync and ring modulation — `[main]`
`$D404` bits 1–2 are scored by **nothing** (`wave` masks `& 0xF0`, `gate` reads
bit 0). Proposed at v0.5.319 ahead of the queued noise-pitch column because it
is cheap and closes the last unscored bits of a register everything else reads.
v0.5.325's register panel now *shows* both sides' sync/ring per voice on the
listening pages — which is a pair of eyes, not a column, and Commando already
demonstrates the panel finding something no report row can (we set the test bit
on all three voices where the original never does). Ids `ctrl-sync-ring-column`,
`noise-pitch-column`, `sweep-direction-metric`, `resonance-volume-columns`.

### 13. Knucklebusters as a structure question — `[subagent]`
Re-entering the loop after v0.5.323's refusal, and **not** as a tempo question:
3 subtunes shipped against the header's 11 (`knucklebusters-subtunes-11-to-3`),
and subtunes wanting mutually incompatible multipliers — 1, 3, 8, 8, 8, 4 for
0–5 while the file packs `-S1` — which is a general problem, not this file's
(`per-subtune-multiplier-conflict`, `[main]`, it changes packing).

### 14. Listening-rig follow-ups — `[subagent]`, cheap
* `abpage` never prunes pages for tunes no longer staged; three stale ones had
  to be deleted by hand this run (`abpage-prune-stale-pages`).
* A regression test that both page templates declare a charset — the
  `windows-1252` defect affected every page ever generated
  (`abpage-charset-regression-test`).
* Spectrogram overlay (the half amplitude cannot show) and a piano-roll from
  `fidelity --json` (`abpage-spectrogram`, `abpage-piano-roll`).

</work_remaining>

<attempted_approaches>

## Refuted, reverted, or corrected — the first run

1. **The trailing silence on a wave program's end** (v0.5.282) — mean `wave`
   −3.0pp, Nemesis the Warlock −45. Reverted. The mechanism had never been
   located, only its effect on one file's trace; what would have shipped was an
   approximation standing in for it.
2. **`CMD_SETWAVE $08` on a bit-6 rest** (v0.5.284) — melody −43.0pp over 8
   files. Reverted. Verified three ways (editor, packed player, relocator) and
   none of the three touched the question that decided it, which was what the
   *next* note does.
3. **The TONEPORTA explanation for that regression** (v0.5.285) — turning the
   proposed cause off changed **zero bytes**. Correct about `gplay.c`, right
   about the shape, and still not the cause. Its CLAUDE.md rule was *replaced*
   rather than amended.
4. **A gate probe tracing both sides at the `-S` multiplier** (v0.5.272) —
   manufactured one-frame gate edges on the original, with a mechanism-shaped
   story attached, and then **falsely refuted the fix** for the real defect
   (v0.5.273: Knucklebusters "worse", properly traced 6.3 → 13.2% better).
5. **Two derived-row scripts for the hard-restart sweep** (v0.5.276) — one
   parsed the row out of a log line, one took the header's subtune count where
   the converter uses the emitted one. Answered 0 files and 2 against the true
   3. Converting at each value and hashing needs no row at all.
6. **A byte-hash probe passing `quiet=True`**, which `convert()` does not accept
   (v0.5.282) — every run recorded `ERR TypeError` for all 95 files and every
   comparison was between two identical sets of error strings. The "0 of 95
   files move" evidence in **v0.5.278 and v0.5.280 measured nothing when it was
   published.** Both claims were later re-verified as true, which is exactly why
   it survived: a vacuous check and a correct conclusion look identical.
7. **Four separate vibrato-census defects in five commits** — a raw-key join, an
   effect-bit map wrong three ways, and a union where every neighbour pairs.
   Two produced findings that were reported and withdrawn.
8. **A `test_hold_rows.py` sweep that passed vacuously** (v0.5.286) — iterating
   `convert_patterns`' return yields two lists, `note` never equals
   `GT_NO_NOTE`, and it reported clean having compared nothing. Exposed by the
   *positive* test failing.
9. **Mozart read as (note, duration) pairs** (v0.5.289) — `48 03 48 07` looks
   exactly like one; disassembling the player's reader showed the existing
   decoder had been right all along.
10. **Blanket release-masking of instrument keys** (v0.5.292) — merges 126 of
    1323 instruments that genuinely differ only in release. `paired_keys`
    instead.

## Refuted or blocked — the second run

1. **"About four hours" for a corpus `--fidelity` search** — never timed, and
   wrong by ~30×. It had refused a feature for 26 versions. Two of the ten
   sites carrying it were *arguments* rather than reports.
2. **My own estimate that seven toggles would take ~30 minutes** — from
   doubling the six-toggle run. The real serial rate is about a minute a song,
   80 minutes; the run was killed at 15 songs in 15 minutes and re-done
   sharded. Doubling a measured time is not measuring the next one.
3. **The TONEPORTA-style trap avoided rather than repeated** — `--max-hard-
   restart` outranking `--wide-hard-restart` was checked on the corpus (forcing
   both is byte-identical to forcing `max`) instead of resting on the unit
   test, because the first run has an entry for a reading that was correct
   about `gplay.c` and still not what happened.
4. **Rewriting history to re-file two `presets.py` lines** — the seventh
   toggle's entries landed in v0.5.303, whose message is about `--shard`. A
   `git reset --soft` was blocked by auto mode's classifier and **not worked
   around**; the misfiling is recorded in v0.5.304's message instead. Costs a
   bisect for those two lines and nothing else.

## Refuted, broken or blocked — the third run

1. **Investigating SIDM2 as the SID2WAV replacement.** It only wraps VICE; the
   actual lineage is libsidplayfp. Corrected by the user. The time was not
   wasted — the vsid comparison found the length overshoot — but the premise
   was wrong for two exchanges.
2. **A renderer comparison whose numbers were junk.** Cross-correlating
   sid2wav against vsid gave ~0.000 with 400 ms lags, and envelope correlation
   0.05–0.20 with lags pinned at the search bound. Cause: the two renders were
   20.00 s and 21.76 s, so every correlation compared misaligned material of
   different lengths. **The level and spectrum figures from that run are
   sound; the correlation and beat-period figures are not evidence of
   anything.** Reported as such rather than quietly dropped.
3. **`_probe.wav` in the shared output directory** (v0.5.308 → fixed in
   v0.5.309). Two shards raced on one fixed filename and one silently staged
   nothing. All unit tests passed. Found by running three shards and counting.
4. **Destroying 22 tunes' notes.** A smoke test — `listen.py --all` with no
   `sid_dir` — staged 0 tunes and *wrote `LISTENING.md` anyway*, overwriting a
   full one. Recovered by re-staging. **The guard is still unwritten**: a run
   that stages nothing should not overwrite the record of a run that staged
   something. Named in v0.5.307's message as owed.
5. **The heredoc backslash trap, twice in one session**, on a rule CLAUDE.md
   already documents and that I had quoted in a commit message an hour
   earlier. `python - <<PY` mangles `\n` in a patch string. Use Write/Edit.
6. **Rewriting history to re-file two `presets.py` lines** — `git reset
   --soft` was blocked by auto mode's classifier and **not worked around**.
   Recorded in v0.5.304's message instead. The user chose to leave it.
7. **Two minutes of audio in one published artifact** — 28 MB against a 16 MB
   ceiling. The answer was not compression (no ffmpeg/sox, and Python 3.14
   dropped `audioop`) but local pages that reference the WAVs instead of
   inlining them, which removed the ceiling entirely.

## Refuted, broken or blocked — the fourth run

1. **A wavetable-clobbering explanation for the −43 pp.** `WAVEEXEC`
   (gplay.c:515) writes `cptr->wave` from the table *after* commands run
   (line 433), so a pattern `CMD_SETWAVE` should be overwritten within the
   frame. Checked against real conversions: our tables end `$FF 00`, which
   zeroes `ptr[WTBL]` and stops WAVEEXEC — IK+ 26 of 26, AWM 24 of 24. The
   mechanism is real but does not fire here. Reported as a negative result
   rather than shipped as a finding.
2. **Widening `apply_tempo` to any free row.** 25 files, 2 better and 3
   worse. Refused; see item 2b.
3. **A probe with `apply_tempo`'s first two arguments reversed** — reported
   "83 of 83 files changed", which is what a broken probe looks like. Caught
   by the implausibility, not by a test.
4. **A `--pace` median read as the truth.** Warhawk's headline says 2.25
   frames; the least-squares fit says 0.875, i.e. 2.286 = 2 × 8/7 exactly.
   The median quantises. The repo's own rule and I nearly took the median.
5. **A denominator census keyed on `resolve_subtune(src, None)`** — that
   helper takes `"auto"`, and `None` raised for all 83 files, which the first
   run reported as `ERR 83`.

## Refuted, broken or blocked — the sixth run

1. **Knucklebusters' "known +31 pp tempo lever".** Written into
   `PER-SONG-PLAN.md` as the first song to work; the file's own bytes show
   **every subtune already carries a `CMD_SETTEMPO`**, so there is nothing for
   a widened scan to add and the A/B's gain has no identified mechanism.
2. **My prediction that its traced subtune had no tempo write**, because
   2.33/6 = 0.39 matches `retrig` 0.39 exactly. A clean arithmetic fit, refuted
   by one query against the `.sng` (the subtune has a write, value 3).
3. **Human_Race's "undetected outer-gate skip table".** The first run read
   `drift −250/1000 = −1/4 = −1/(skip+1)` with skip 3 and `4 × 4/3 = 5.33`
   matching `--pace`'s estimate of the original's row — two arithmetic
   coincidences. The file **has no outer gate**: it opens `INC $0DE2` where both
   `OUTER_GATE` patterns require `DEC`, and `_find_outer_gate` returns `()`
   correctly. Both sides run 4 frames per row, provably, from the player's
   reload table and our own tempo byte.
4. **That run's demonstration of the "fix" was mis-run** and is not evidence
   either way: forcing `effective_frames` to return 16/3 left the multiplier
   alone (it comes from `derived_group_tempos` in `convert.py`), so the file
   still packed `-S1` and the fractional row rounded to 5.
5. **The "194 attacks against 14" gate fact on AWM** — the split does not exist
   in either build. The check was vacuous as written and the task was retired
   rather than retried.
6. **Cross-correlation as the A/B sync estimator** — flat over 60 s (top six
   lags within 3% of each other on Knucklebusters, 156 notes against 404). A
   start offset is a property of the START; first-onset difference is stable.
   And the first prominence guard compared the peak against the **runner-up**,
   which on any smooth correlation is the adjacent lag — it refused everything.
7. **`v1+v2+v3 ≈ full mix` as proof the mute worked** — only 0.12 at zero lag,
   peaking 0.50/0.55 at ~7 ms, because separate `sidplayfp` runs do not start on
   the same sample and the SID filter is shared. Reported as not proving what it
   was reached for; the mutual-uncorrelation check is what establishes the
   solos are different voices.
8. **`entry['options']` in `presets.json`** — a song's flags live at **top
   level**, so setting `entry['options']` is silently ignored and the first
   forced-`rest_wave_silence` run was the default build wearing a different
   filename. `--diagnose` prints the options line; that is the cheap
   confirmation a forced flag applied.
9. **Three probes that guessed the record layout** during the vibrato split
   (`detect()` arity, `Detection.vibrato` which is `vibrato_offset`, ADSR at
   `record+2/+3` which found 0 of 23). Each printed its failure only because the
   scripts assert their own success rate. The route that worked was the tool's
   own reader (`songview.parse_sng` + the `NN:b5-b6-b7` name stamp).
10. **A rows-per-note probe over `_build_raw_pattern`** — returned exactly 1.00
    for `hold`-0% and `hold`-100% files alike, so the test was wrong rather than
    the files alike. Nothing was concluded from it.
11. **Shell quoting**: `"$D\$f.sid"` inside double quotes escapes the dollar and
    produced `Hubbard_Rob$f.sid`; two runs died on `FileNotFoundError`. Forward
    slashes fixed it.

## Not pursued

* Emitting bit `$10`/`$04`'s global arpeggio (costs 5 points of mean melody;
  `fidelity_better` cannot select it).
* ~~A per-song `HARD_RESTART` row bound~~ — **done at v0.5.302 and v0.5.304**
  (`--wide-hard-restart`, `--max-hard-restart`). The bound is a three-way
  per-song choice now: 11 files take `row - 1`, ACE II takes `2 * row // 3`
  having tried and rejected the wider one, and 71 keep `row // 2` — Saboteur
  II among them, refused by `keeps_notes` both times. Mean gate 47% → **50%**,
  5524 fewer frames sustaining a voice the original released, and no column
  falls on any file. Delta 42% → 84%, Flash Gordon 59% → 85%.
* Widening `--rest-keyoff` detection to players whose bit-6 branch does not
  silence — measured at v0.5.272 on 6 sampled files, 4 better and 1 worse; not
  enough to widen a detection gate. (v0.5.273 then widened it on better
  evidence, so this entry is superseded — noted because the *first* measurement
  came from the bad probe.)

</attempted_approaches>

<critical_context>

## Environment

* Repo `C:\Users\mit\claude\h2g`, branch `master`, at **v0.5.326** (this handoff), in sync with
  `origin/master`.
* Corpus (95 files): `C:\Users\mit\claude\c64server\SIDM2\SID\Hubbard_Rob`
* GoatTracker 2.77 source: `C:\Users\mit\Downloads\GoatTracker_2.77\src`.
  `exectable` is `gtable.c:1008`; the next-note fetch is `gplay.c:905`;
  `greloc.c:1270-1271` is the `$E0`-`$EF` rewrite.
  SourceForge's documented path for `GoatTracker_2.77.zip` 404s — the file is
  under `GoatTracker 2/2.77/` and the mirror link is in the interstitial.
  sha256 `96c2bd6a6ab3aca2f5bb18b1c764ac6ea69ac245cae14002a72cd87c554561ef`.
* `python/tools/siddump-rt` builds with
  `zig cc -O2 -o siddump.exe siddump.c cpu.c` if gcc is absent; the invariant
  holds for that build (`-m1` byte-identical to stock siddump on Commando.sid,
  507 lines).
* `build/` is gitignored; `6581.pdf` untracked deliberately.
* **Timings, measured rather than assumed** (v0.5.301/303/304). A corpus
  `--fidelity` search costs about a minute a song and scales with the toggle
  count: **8 min** at five toggles, **15** at six, **80** at seven — or
  **11 min** at seven with `--shard 0..5/6` across six processes. `fidelity.py`
  over the corpus ≈ 3 min; a full regeneration of all five artefacts ≈ 7 min;
  the test suite ≈ 4 min (8 under load). The "about four hours" that stood for
  26 versions was never timed and refused a feature.
* `python -m pytest` must be run from `python/` — from the repo root it silently
  finds no tests.
* `.claude/settings.json` now carries a **shared** permission allowlist; the
  per-machine `.claude/settings.local.json` is gitignored.
* **Rendering.** `sidplayfp` (libsidplayfp's frontend) at
  `C:\Users\mit\Downloads\sidplayfp-2.15.2-32bit-mmx\sidplayfp.exe` is the
  renderer. **RSIDs need the C64 ROMs**, wired in
  `%APPDATA%\sidplayfp\sidplayfp.ini` to VICE's `C64/` directory
  (`kernal-901227-03.bin`, `basic-901226-01.bin`, `chargen-901225-01.bin`;
  a `.ini.bak` holds the original). Without them libsidplayfp dies on an
  illegal instruction having written a 44-byte header — which looks exactly
  like a tune that renders silence. `SID2WAV` (1997) and VICE's `vsid` remain
  as fallbacks; **do not** reach for them deliberately: sid2wav fades the tail
  and refuses RSIDs, vsid does not render the requested length.
* **Listening timings.** 83 tunes at 120 s: ~95 min serial, **~8 min** across
  six shards including merge and page generation. 1.7 GB in `build/listen/`.
* **11 files now pack above `-S4`** (was 5), so the sampling caveat covers
  more of the corpus than it did: siddump samples once per frame whatever the
  call rate, and a `-S7` file has six calls in seven discarded. **Read
  `--equal-calls` for the sequence dimensions of any such row** — Warhawk is
  64% on a normal trace and 90% at equal sampling. `FIDELITY.md` prints the
  warning; it has now decided a ship-or-refuse twice.
* **`MAX_ROW_DENOMINATOR` is 10** and the cap is a property of the corpus, not
  a tuned threshold: the rows it declines round within 0.8–1.2% and the ones it
  reaches are 9.1–12.5% out, with nothing in between. Do not raise it to chase
  q = 20 or 112 — those are 1–6.4 kHz call rates and they round correctly.
* **Auto mode's classifier blocks `git reset --soft` and some compound
  commands containing `cp`.** Not a repo rule — a harness one — but it decides
  what a session can do unattended: history rewriting needs a human, and
  compound shell lines get denied where the same steps run fine separately.
  Split commands rather than fighting the denial.

## Rules added to CLAUDE.md during the second run

15. **A cost written down but never timed is a planning input** — and this one
    refused a feature for 26 versions. Time a cost before it decides anything.
16. **`--shard I/N` / `--merge`**, and the correction of the line that said
    there is "no reason to run them in parallel" — true of two whole searches
    contending, wrong about shards.

## Rules added to CLAUDE.md during the first run

1. Which side the multiplier belongs to (ours, never the original's).
2. Keep the *command* short; put the long text in a file — past a length the
   harness cannot security-scan a command and stops to ask a human.
3. A `-` in the report is a finding, not a gap.
4. "No column moved" has a third cause: the register is one every column
   deliberately ignores — **build the column**.
5. Read `--pace`'s spread before its number: a tight ratio is a constant, a
   loose one is a mechanism.
6. To ask whether a constant matters, hash the output — do not re-derive the
   quantity it is bounded by.
7. A probe that wraps `convert()` must assert its own success rate.
8. An explanation that fits the shape of a regression is not thereby its cause —
   turn the proposed cause off and see if the effect survives.
9. A trace that shows what is wrong does not tell you what writes it; `$18` is
   not `$08`.
10. `multiplier` is not the only thing between the player's calls and ours (the
    outer-gate skip, and the note-start path's counter).
11. A value written into a counter is not a quantity until you know what the
    counter does.
12. A key must not contain a field the *conversion* alters, measured or not.
13. The option that removes a defect is not always the fix for it.
14. An encoding is only as good as the *packer's* reading of it.

## Gotchas worth carrying

* **`--cut-release` rewrites the release nibble**, so a raw ADSR-pair join
  between our side and the original finds far less than it should. Every
  ADSR-keyed site goes through `paired_keys` now — a new one must too.
* **`--pace` prints a median and a least-squares fit.** Read the fit. And it
  cannot see a row wrong by a fraction of a frame at all; that is `drift`.
* **A file packed above `-S4` cannot be judged on a normal trace.** Use
  `--equal-calls`.
* **`fidelity.py --diagnose` before calling any row a conversion bug.**
* **A probe must reproduce the harness's calling convention** — three failed
  this run by omitting `--tempo auto`, the frequency-table calibration, and
  `convert()`'s real signature respectively.
* **`_voice_addr` returns a file offset, not an address**, as do
  `det.track_lo`/`track_hi`.
* Where a signature can match twice, ask *which* match — Powerplay cost two
  commits to that (the instrument chain, then the push chain).
* `search_file`'s first match is not always the right one, and a file can carry
  a whole second player.
* **A tight `--pace` ratio is not always a constant.** CLAUDE.md's rule ("a
  tight ratio is a constant, a loose one is a mechanism") holds only where both
  sides' note populations are comparable. Human_Race's 0.750 has IQR
  0.750–0.750 over 78 gaps and is still not a row error: where one side
  systematically re-strikes, the ratio is tight for a reason that has nothing to
  do with the row.
* **`drift` and `wave` are computed over a matched population.** `drift` is a
  Theil–Sen fit over matched onsets, `wave`'s lag comes from first attacks — so
  a change that adds 289 attacks rewrites both without touching the clock. The
  tell is `--pace` reporting a different row for **the original**, which is
  impossible as a fact about the original.
* **A song entry in `presets.json` holds its flags at top level**, not under an
  `options` key. `entry['options'] = {...}` is silently ignored.
* **`fidelity.py:3733`'s "On 17 files" is a hardcoded literal**, not a computed
  count. Do not quote it; the real count is 3.
* **`-u` is a `sidplayfp` output flag**, invisible to `siddump` — muting cannot
  reach the play routine, so there is nothing to compare on the register side.
* **Separate `sidplayfp` runs do not start on the same sample** (~7 ms), and the
  SID filter is shared across voices. Distinct from the original-vs-ours startup
  lag the pages correct.
* **Media elements do not load in the Chrome automation tab** —
  `visibilityState` is `"hidden"` and `readyState` stays 0. Verify page logic
  with `duration` stubbed and `currentTime` intercepted, and say so.

## Assumptions needing validation

* `onset`'s 4-frame window and exact-match rule are choices, not measurements.
* `drift`'s 1% scatter bound is a claim about audibility; the corpus agrees
  (4.6× gap between worst true positive and best false one) but it was not
  fitted.
* `paired_keys`' fallback requires one remaining candidate in both directions;
  no one has checked what it does on a file with many near-duplicate records.
* The `slot`/`fetch` split in the hold census assumes the file's median
  `our_slot/orig_slot` really is `1/retrigger_ratio`; it holds for 94 of 117.
* Whether the bit-6 rest population (17 files) is the right scope at all —
  three attempts have failed inside it.

</critical_context>

<current_state>

## Repository

* **HEAD is this handoff commit (v0.5.326) on top of `3894a63` v0.5.325**, master
  in sync with `origin/master`. The last
  commit to change what the converter *emits* is still **v0.5.313** (six files
  re-grid onto a higher multiplier); before it, v0.5.304. Everything from
  v0.5.314 to v0.5.325 is harness, tooling or docs — `python/h2g/` was touched
  once in the sixth run (`patterns.py`, comment-only, v0.5.320).
* **`0.5.324` is in `CHANGELOG.md` with no commit of its own** (`3894a63` is
  0.5.325 and covers both entries) — the second version collision this document
  records.
* **A concurrent session is also pushing to `master`.** It pushed its own
  v0.5.311 during this run and both commits claimed the number. Fetch before
  assuming HEAD is yours, and re-take any measurement after rebasing.
* Working tree clean but for three untracked paths: `6581.pdf` (deliberate),
  `monlog_out.txt` (VICE monitor output, should be removed or gitignored — task
  `untracked-monlog`), and `.claude/tasks/` (the task runner's `whattask.json`
  and `runs.jsonl`; **38 open tasks, 14 closed**, and the run records carry
  evidence that exists nowhere else).
* `Commando.sng` byte-exact.
* Last suite at HEAD (re-run for this handoff, ~4m13s from `python/`): **1203
  passed, 3 skipped**. It was 1135/3 at v0.5.297;
  the 17 new tests are the two hard-restart bounds (7), the shard/merge
  partition and its three refusals (9), and one derived-count fix.
* ~~**The third skip is `test_preset_passthrough` disarming itself again.**~~
  **Re-armed at v0.5.327** by regenerating `SURVEY.md` and `presets.json`. It
  had been skipping since v0.5.315 — **ten versions** — because the guard only
  runs while `presets.json`'s stamp matches the converter, so the check that no
  `convert()` option escapes into `presets.py` had not run in that window. (It
  was disarmed for four versions once before, v0.5.295–299, and the previous
  handoff recorded re-arming it: this is the second occurrence of the same
  failure mode, and it will recur after every stretch of non-converter commits.)
  **Suite at v0.5.327: 1204 passed, 2 skipped** — one more test running than
  before, and the only remaining skips are `test_legal_restart.py:185`, which
  needs `H2G_GT2RELOC` set.

## Generated artefacts

| file | stamp | current? |
|---|---|---|
| `SURVEY.md` | **0.5.327** | yes — regenerated v0.5.327 |
| `presets.json` | **0.5.327** | yes — regenerated v0.5.327 |
| `FIDELITY.md` | 0.5.315 | yes (on demand; no converter change since) |
| `SUBTUNES.md` | 0.5.315 | yes (on demand) |
| `VIBRATO.md` | *none* | yes — regenerated v0.5.316 (on demand) |

All four stamped artefacts regenerated at v0.5.315 against the re-search, and
`VIBRATO.md` at v0.5.316. **The converter is 0.5.325, so the stamps read ten
versions behind** — and the *numbers* are still correct, because nothing between
v0.5.316 and v0.5.325 changed converter behaviour: docs, `listen.py`,
`abpage.py`, and one comment-only edit to `patterns.py`. Verified for this
handoff: `git diff v0.5.315..HEAD -- python/h2g/` is `__init__.py`'s version
line plus comment and blank lines in `patterns.py`.

**The stamp gap had a cost even though the numbers were right**:
`test_preset_passthrough`'s guard skipped while it stood, so the option-escape
check was off. **Closed at v0.5.327** (task `artefact-stamp-realign`) by
regenerating both, per `CLAUDE.md`'s order and with `--legal-restart
--gt2reloc`. The regeneration is itself the evidence the numbers were current:
**one line changed in each file, the version stamp** — 80/95 converted in the
survey, 83/95 convertible in the presets, 22 `always` keys, and **52
`--fidelity` settings carried forward** (the run prints the count, so the fast
path cannot silently revert a measured per-song decision).

`FIDELITY.md` and `SUBTUNES.md` still read 0.5.315 and are still correct — they
are on-demand artefacts and nothing between v0.5.316 and v0.5.327 changed what
the converter emits. Neither gates a test, so neither costs anything the way the
`presets.json` stamp did.

**Order the bump before the regeneration, not after.** The first attempt at
v0.5.327 regenerated both files and *then* ran `bump_version.py`, which stamped
the artefacts 0.5.326 against a 0.5.327 converter and disarmed the guard again
in the same commit that was meant to re-arm it. `CLAUDE.md` says to bump
"before staging" and to "regenerate any doc embedding the version"; the two
instructions only compose in one order. Caught by re-reading the stamp, not by
a test — the guard's failure mode *is* silence.

The `--fidelity` settings are **current as of v0.5.315**: the six files
v0.5.313 re-gridded were re-searched there — 127 combinations a song, 3 shards,
42 s — and five of the six gained a `max_hard_restart`.

All five regenerated at v0.5.304 against a converter change, so `FIDELITY.md`
moves five rows as well as its stamp and the rest move stamps only.
`VIBRATO.md` carries no stamp at all and regenerates byte-identical whenever
nothing it measures moved; that is worth knowing before reading its mtime as
evidence of anything.

`presets.json`'s `--fidelity` settings were **re-measured at v0.5.300** and are
current. They had been carried forward since v0.5.271 across three changes to
what the converter emits — the hard restart (v0.5.275), the outer-gate-only row
(v0.5.289) and the vibrato delay (v0.5.294) — and the re-run came back
**1 gained, 0 lost** (Kings of the Beach intro takes `two_stage`), with
structural choices identical on all 83 songs.

**And it costs 8 minutes, not the four hours documented since v0.5.235.** Timed
twice (8m11s and ~8m, 83 songs, zero failures), and the second run against the
adopted output returned 0 gained / 0 lost, so the search is deterministic and
idempotent. That figure had never been timed, and it was load-bearing: it is
the stated reason two features were refused. Both are reopened above.

## Corpus at v0.5.315 (the artefacts as they stand)

* 95 files; **83 measured**, 80 of 83 in reach converted, 3 failed, 12 out of
  scope (not a Hubbard player).
* mean melody **91%**, sequence **91%**, pitch **94%**, wave **81%**,
  ADSR **66%**, gate **52%**.
* noise frames ours/original **76034 / 82742**.
* gate: **122589** frames sustaining a voice the original released, **37146**
  the other way round.
* *plays the same music* (95–100%) **58 files** (56 before v0.5.328); close
  15; recognisable 8; plays something else **2** — Commodore_64_Music_Examples
  and Dragons_Lair_Part_II, both of them the subtune correspondence rather
  than the conversion (item 11). Mean melody **93%**.
* drift: **52** of 79 exact; 27 part company at a median 8.9 frames per 1000.
* `presets.json`: 83 songs, 22 `always` keys, **48** carrying a `--fidelity`
  setting — full search v0.5.304, plus the six re-gridded files re-searched at
  v0.5.315. No song's settings predate its current multiplier.
* Multipliers: **11 files above `-S4`** (three at `-S10`, one `-S9`, two
  `-S7`, one `-S6`, four `-S5`). Read `--equal-calls` for those rows.
* Hard restart bound: **16** files at `row - 1`, 1 at `2 * row // 3`, 66 at
  `row // 2` (11/1/71 at v0.5.313; the five that moved are v0.5.315's
  re-search of the re-gridded files).
* Vibrato census: 136 instruments, 42618 reversals missing, **114 emitting no
  oscillation at all**.

## New surface added during the sixth run

* `listen.py` — `--voices` (per-voice solo staging through `sidplayfp -u`),
  `--traces-only` (rewrite `<name>.trace.json` in two siddump runs a tune
  instead of eight renders), `mute` threaded into the renderer
* `abpage.py` — the "Both sides, drawn" envelope canvas with a `|difference|`
  strip and click-to-seek; the measured **startup-lag sync offset** with a
  ±500 ms slider, `auto` and `0`; `--serve` (builds and hosts `build/listen` on
  `127.0.0.1:8730`); a voice selector; a facts card (from `SURVEY.md` and
  `presets.json`); a **register panel** (waveform classes, test bit, hard sync,
  ring modulation, per voice, both sides, live at the playhead); a **tracker
  view** built from the staged `.sng` via `songview.parse_sng`; `<meta charset>`
  on both templates; discovery skipping the `.v[123]` suffix; and
  `build/listen/Listen.ps1`, written by the builder on every build
* `tests/test_renderer.py` — the `sidplayfp` stub takes `mute` and asserts it
  reaches the renderer (the signature change is intentional, so the test was
  extended rather than relaxed)
* `PER-SONG-PLAN.md` — the nine-step per-song loop, the song shortlist (entry 1
  struck at v0.5.323), the metric audit, and the listening-tool roadmap
* `.claude/tasks/` — `whattask.json` (38 open, 14 closed) and `runs.jsonl`
  (12 run records). **The run records carry evidence that exists nowhere else**
  — the per-voice mute correlations, the AWM control-register census, the
  Human_Race gate disassembly — and the directory is *untracked*
* No converter surface at all: `python/h2g/` took one comment-only edit

## New surface added during the fifth run

* `listen.merge_notes` — the header is taken from a part, not from the
  `LISTENING.md` already in the directory (`head = h or head`); docstrings in
  `merge_notes` and `document_header` corrected to describe the behaviour
  rather than the intent
* `tests/test_listen_shard.py` —
  `test_the_header_comes_from_a_part_not_from_the_file_already_there`, the
  first merge test whose two candidate headers differ (9 in the file, 1203 in
  the suite)
* No converter surface at all: `python/h2g/` was not touched in this run

## New surface added during the fourth run

* `detect.rest_silence_kind` — splits the two rest-silencing families
  ("testbit" 17, "envelope" 4); `_find_rest_silences` is `bool(kind)`
* `patterns.CMD_SETWAVE`, `REST_SILENT_WAVE`, `ONE_SHOT_COMMANDS` extended;
  `apply_tempo` may overwrite CMD_SETWAVE and nothing else
* `convert(rest_wave_silence=)` / `--rest-wave-silence`, in
  `presets.EXCLUDED_FROM_ALWAYS`
* `MAX_ROW_DENOMINATOR` 6 → 10
* `tests/test_rest_wave.py` (8); `test_hold_rows` and `test_skip_gate`
  rewritten from literals to properties

## New surface added during the third run

* `python/abpage.py` — A/B listening pages (`--embed` for a self-contained
  one), plus `tests/test_abpage.py` (11)
* `listen.py` — `render_sidplayfp`, `pick_renderer`, `select_names`,
  `split_notes`, `merge_notes`; flags `--all`, `--shard I/N`,
  `--merge-notes`, `--sidplayfp`; plus `tests/test_renderer.py` (7),
  `tests/test_listen_all.py` (8), `tests/test_listen_shard.py` (8)
* `build/listen/` — 83 pairs at 120 s, 83 pages, `index.html`,
  `LISTENING.md` (all gitignored, 1.7 GB)
* `%APPDATA%\sidplayfp\sidplayfp.ini` — C64 ROM paths (machine config, not
  in the repo; a fresh machine must do this itself)

## New surface added during the second run

* `goatwriter.py` — `_hard_restart_ticks(..., wide, full)`, the three-way row
  bound; `--wide-hard-restart` / `--max-hard-restart` threaded through
  `_write_instruments`, `build_sng`, `convert()` and `cli.py`
* `presets.py` — `--shard I/N`, `--merge`, `merge_shards()`; `FIDELITY_TOGGLES`
  at seven
* New tests: `tests/test_preset_shard.py` (9), seven in `test_hard_restart.py`,
  and `test_preset_passthrough`'s combination counts derived from
  `len(FIDELITY_TOGGLES)` rather than written down

## New surface added during the first run

* `fidelity.py` — the `gate` and `drift` dimensions; `--gate-census`,
  `--hold-census`, `--vib-census`; `paired_keys`, `pitch_effect_bits`,
  `sound_note_runs`, `gate_runs`, `drift()`
* `survey.py` — `--subtune-census`, generating `SUBTUNES.md`
* `presets.py` — `gates_right` search term, `--rest-keyoff` and
  `voice_two_stage` in `FIXED`
* `detect.py` — `SPEED_GATE_IMM`, `TWO_STAGE_SHAPE_ZP`, `_find_voice_two_stage`,
  `pitch_effect_bits` support, the every-match push chain, the nearest-table
  rule for a doubled player
* `tracks.py` — `instrument_voices` (the instrument→voice map), `$FE nn` tempo
* `goatwriter.py` — `ONE_SHOT_COMMANDS`, `HARD_RESTART_FRAMES` in frames,
  the wave program's terminating step, `_wave_alternate_entries(alt_first=)`
* `cli.py` — `--rest-keyoff`, `--engine N`
* New reports: `SUBTUNES.md`, `VIBRATO.md` (both on demand, like `FIDELITY.md`)

## Method-doc sections added

§ 7.xxxx through **§ 7.zzzzz** — the hold tail, the zero-page two-stage,
Nineteen's drum, Ninja's per-voice attack and alternation, the terminating step,
Rasputin's tempo command, the immediate speed gate, the gate dimension and its
census, the hard restart, Powerplay's two players, `--engine`, the subtune
census, drift, the bit-6 rest's three refutations, the outer-gate-only row, and
the vibrato census's four self-corrections.

**The letter run is exhausted.** § 7.zzzzz is the last available name under the
current scheme, and **five sections are owed behind it** — see
`<work_remaining>` item 8 for which. Nothing has been added to the method doc
since; the findings live in commit messages only.

## Open questions for the user

1. **The listening set is staged and current** — 83 pairs, re-rendered at
   v0.5.316 so that the six re-gridded files and the settings re-searched at
   v0.5.315 are what you hear. The question is no longer whether to stage it
   but what it says. See `<work_remaining>` item 1 for the four tunes that each
   have a decision waiting on them.
2. The bit-6 rest is **closed** (v0.5.312): the regression was the tempo
   write. `--rest-wave-silence` is measured and ships off, and whether it
   *should* is now a listening question — `IK_plus.html` loses 5 pp of `wave`
   and `Auf_Wiedersehen_Monty.html` gains 8, both staged.
3. What scheme should method-doc sections use past § 7.zzzzz? Still unresolved
   and now **seven sections overdue** — v0.5.302, 304, 313, 315, 317, 320 and
   322 each shipped without one because there was no name to give it.
4. The v0.5.303/304 misfiling (two `presets.py` lines in the wrong commit) is
   recorded in prose rather than rebased, because the fix was blocked. Fine to
   leave, or worth a force-push?
5. **`--rest-wave-silence`: ship on or off?** Still a listening question, and
   now a better-equipped one — `IK_plus.html` loses 5 pp of `wave` and
   `Auf_Wiedersehen_Monty.html` gains 8, and both pages now sync the two sides,
   solo a voice and show the register panel.
6. `6581.pdf` and `monlog_out.txt` sit untracked in the repo root. Commit,
   gitignore, or delete?

## Immediate next action

**Listen. Open `build/listen/Listen.ps1` (double-click), or run
`python abpage.py --serve` from `python/` and open the printed URL.**

This has been the immediate next action in five consecutive handoffs, and the
rig it names is no longer the same object. Since the last one it has gained:
the **startup-lag correction** (the two sides were 120–155 ms out of sync in
every previous listening pass — the flam a listener would have been hearing on
every switch), a **voice selector** that solos the same voice on both sides, an
**envelope canvas** with a difference strip and click-to-seek, a **register
panel** comparing waveform classes, test bit, hard sync and ring modulation per
voice, and a **tracker view** of the subtune being played. Two of those show
things no column in `FIDELITY.md` can: hard sync and ring modulation are scored
nowhere, and Commando's panel already reports that we set the test bit on all
three voices where the original never does.

Four decisions wait on ears, all staged: `--rest-wave-silence` on IK+ (−5 pp
`wave`) against Auf Wiedersehen Monty (+8), and the three files whose reports
disagree with their music. `[user]`, about an hour.

**If code is wanted before ears — the highest-value item is item 10, the
note-length defect.** It is new to this handoff and it is where the sixth run's
three independent song investigations converged: 46 of 95 files read `hold` 0%,
and every badly over-triggering file in the corpus is one of them. Geoff Capes
states it as cleanly as it can be stated — pitch 100%, onset 100%, tail 100%,
`--pace` 0% out — and still re-strikes every note 3.2×. The duration is present
in the source and is read; **where it is lost is not localised**, and the one
probe that tried returned the same answer for `hold`-0% and `hold`-100% files
alike. `[subagent]`, own worktree, `siddump.exe` copied in.

**Cheap and unblocking, in this session:**

1. ~~**Regenerate the artefacts.**~~ **Done at v0.5.327.** The numbers did not
   move (one stamp line per file) and `test_preset_passthrough` is armed again:
   1204 passed, 2 skipped.
2. **Choose the method-doc section scheme past § 7.zzzzz.** A five-minute
   naming decision now blocking **seven** owed sections, each of which exists
   only in a commit message. `[user]`.
3. **Fix `fidelity.py:3733`'s hardcoded "On 17 files"** — it prints 17 whatever
   the corpus does; the real count is 3, and `drift-residual-17` is named after
   the literal. `[subagent]`.

**And one thing to correct in `CLAUDE.md` before it is quoted again:** the
"Dragons_Lair_Part_II is 7% on the diagonal and 94/98/97% at its real
counterparts" figure is stale — measured this run, its best counterpart is 60%
and voice 2 still reads "different music" there.

What this run adds to the document's running tally: **five** more measurement
instruments or premises that reported mechanisms which did not exist (the
Knucklebusters tempo lever, my own arithmetic fit against it, Human_Race's skip
table, AWM's `$41` split, the sum-of-voices check), and **two** more defects in
the listening apparatus found by looking at its output rather than by any check
(the missing charset on every page ever generated, the uncorrected startup lag
in every A/B ever staged). A listener is still the only instrument here that
has never been wrong.

</current_state>
