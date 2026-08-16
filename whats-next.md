<original_task>
Continuation of long-running work on **H2G**, a signature-based ripper that
converts Rob Hubbard `.sid` files into GoatTracker `.sng`, at
`C:\Users\mit\claude\h2g`. The run covered here opened at **v0.5.253** — by
being asked to "read what next", where the handoff described v0.5.251 — and
ran to **v0.5.297**, 52 commits.

> **Provenance.** This handoff is *reconstructed*, from the 52 commit messages,
> the generated artefacts and the tree, by a session that did none of the work.
> The previous ones were written by the session that did it and could record
> what left no trace — a directive, an approach abandoned before it reached a
> file, a listening verdict given in chat. Everything below is checkable; what
> is missing is whatever was never committed. Treat `<attempted_approaches>`
> as "refutations that reached a commit message", not as the full list.

There was no up-front task. The work was driven by short directives and by
three rounds of forked subagents. The working mode is the project's established
one:

> measure the conversion against the original, find where they differ, read the
> 6502 to learn why, fix it, re-measure across the corpus, and ship or refuse to
> ship on the measurement.

Scope: `python/h2g/` (detect.py, goatwriter.py, tracks.py, patterns.py) and the
measurement harness (`fidelity.py`, `presets.py`, `survey.py`, `songview.py`),
plus two new generated reports (`SUBTUNES.md`, `VIBRATO.md`). The VB6 original
was not touched.
</original_task>

<work_completed>

## Summary

**52 commits, v0.5.253 → v0.5.297, all pushed.** `Commando.sng` byte-exact
throughout. Working tree clean but for the deliberately untracked `6581.pdf`.

Corpus movement over the run, from `FIDELITY.md`'s own summary blocks:

| | v0.5.252 | v0.5.294 (current) |
|---|---|---|
| mean melody | 88% | **91%** |
| mean sequence | 87% | **90%** |
| mean wave | 78% | **79%** |
| mean ADSR | 63% | **65%** |
| noise frames ours/orig | 75904 / 82742 | **76332 / 82742** |
| *plays the same music* (95–100%) | 46 files | **54 files** |
| mean gate overlap | (no such column) | **47%** |
| drift | (no such column) | **46 of 79 exact** |

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

## By thread

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

</work_completed>

<work_remaining>

Ordered by value. Tags per CLAUDE.md: `[subagent]` = one agent in its own
worktree (brief it to copy `python/tools/siddump-rt/siddump.exe` in, touch none
of the generated files, return a `git diff`); `[main]` = this session only;
`[user]` = needs a human.

### 1. Re-stage and listen — `[user]`
The staged pairs in gitignored `build/listen/` are from **v0.5.238, 13 Aug** —
44 versions and every gain above them. Two listening verdicts *did* arrive
during the run (IK+ at v0.5.282, Knucklebusters at v0.5.290) and each opened a
thread that produced real work, which is the argument for doing it again now
that mean melody is 91% and `gate` exists. Re-stage with
`python listen.py <sid_dir> -t 30 --presets ../presets.json`; for interactive
listening `.\play.ps1 <file> -Presets presets.json`, **never `goattrk2.exe`
directly**. Worth including: Auf Wiedersehen Monty (item 2), a `-S5` file, and
one of the four in *plays something else*.

### 2. The bit-6 rest's waveform — `[main]`
§§ 7.nnnnn / 7.ooooo / 7.ppppp. Three attempts, three refutations, and the
cause of the −43pp regression is **still unknown** — v0.5.285 falsified the
TONEPORTA explanation by turning it off. Two facts sit unassembled: Auf
Wiedersehen Monty's voice 2 holds `$41` continuously where the original drops to
`$40` (194 attacks → 14), and the A/B that produced the regression measured 673
command bytes where 61 were designed. **v0.5.286 fixed that emitter**, so the
first move is re-running the same A/B and seeing whether the regression is even
still there. `[main]` rather than `[subagent]` because it has burned three
plausible readings already.

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
of mean melody, and `fidelity_better` cannot select it. `plain` absent is the
largest genuine queue. One agent per bucket is the natural fan-out.

### 4. Re-grid the rows for drift — `[main]`
33 files drift, median 9.2 frames per 1000, worst Rasputin −355.8. On 17 the
cause is exact — `-1/(skip+1)`, the outer-gate correction `effective_frames`
declines when the corrected row cannot be packed (IK+'s 3 × 113/112 wants
`-S112`). The fix is re-gridding, not a tempo. **Changes packing, so `[main]`.**

### 5. The gate axis's remaining 134630 frames — `[subagent]`
Mean gate overlap 47%; 134630 frames sustain a voice the original released.
v0.5.274 established that `held` has no long tail and is the same mechanism
`hold`'s `fetch` owns. So this is not a new mechanism to find — it is whether
the next-note fetch can be compensated at all, and that question has one
measured non-answer (`--no-test-restart`, −26.3pp melody) and one measured
partial (`HARD_RESTART_FRAMES`). The unexplored lever is the `row // 2` bound:
`2 * row // 3` is +1.6pp of gate everywhere except Saboteur II, which breaks.
A per-song toggle settled it: `--wide-hard-restart` (v0.5.302) raises the
bound to `2 * row // 3` per song. v0.5.276 had declined one on the cost of
doubling "a four-hour search", a cost never timed and actually 8 minutes.
9 files take it, Saboteur II is refused by `keeps_notes`, and the corpus gains
1pp of mean gate with nothing falling. **What remains of this item is the rest
of the 131618 frames**, which `hold`'s `fetch` owns.

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

### 9. Older, still open
* `songview.py`'s **live render check**, owed since v0.5.243. Chrome extension
  reported not connected; serve `build/` over `127.0.0.1` (Chrome MCP cannot
  open `file://`). `[user]` or `[main]`.
* `instrmap.py` still overlaps `songview.py --compare`.
* No noise-pitch column.
* Bit `$10`'s global arpeggio, decoded and unemitted (§ 7.ttt) — same reason as
  bucket `arp` above.
* Three corpus files fail to convert; 12 are out of scope by construction.

</work_remaining>

<attempted_approaches>

## Refuted, reverted, or corrected during this run

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

## Not pursued

* Emitting bit `$10`/`$04`'s global arpeggio (costs 5 points of mean melody;
  `fidelity_better` cannot select it).
* ~~A per-song `HARD_RESTART` row bound~~ — **done at v0.5.302**
  (`--wide-hard-restart`). Searched, taken by 9 of the 19 files it reaches,
  refused on Saboteur II by `keeps_notes` as predicted; mean gate 47% → 48%
  with no column falling anywhere.
* Widening `--rest-keyoff` detection to players whose bit-6 branch does not
  silence — measured at v0.5.272 on 6 sampled files, 4 better and 1 worse; not
  enough to widen a detection gate. (v0.5.273 then widened it on better
  evidence, so this entry is superseded — noted because the *first* measurement
  came from the bad probe.)

</attempted_approaches>

<critical_context>

## Environment

* Repo `C:\Users\mit\claude\h2g`, branch `master`, at **v0.5.299**, in sync with
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
* **Timings**: `presets.py --fidelity` over the corpus ≈ **4 hours** (60 s
  window); `fidelity.py` over the corpus ≈ 5 minutes; the test suite ≈ 3
  minutes.
* `python -m pytest` must be run from `python/` — from the repo root it silently
  finds no tests.
* `.claude/settings.json` now carries a **shared** permission allowlist; the
  per-machine `.claude/settings.local.json` is gitignored.

## Rules added to CLAUDE.md during this run

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

* **HEAD is v0.5.299; master in sync with `origin/master`.** The last commit to
  change an executable line is **v0.5.294**; v0.5.295–297 are census
  corrections, v0.5.298 is this handoff and v0.5.299 the regeneration.
* Working tree clean but for untracked `6581.pdf`.
* `Commando.sng` byte-exact.
* Last suite at HEAD: **1136 passed, 2 skipped**. The count rose by one
  because v0.5.299's regeneration re-armed `test_preset_passthrough`'s stamp
  guard, which had been skipping since v0.5.295 — so the check that no
  `convert()` option escapes into `presets.py` was not running for four
  versions.

## Generated artefacts

| file | stamp | current? |
|---|---|---|
| `SURVEY.md` | 0.5.299 | yes |
| `presets.json` | 0.5.299 | yes |
| `FIDELITY.md` | 0.5.299 | yes |
| `SUBTUNES.md` | 0.5.299 | yes (on demand) |
| `VIBRATO.md` | *none* | yes (on demand) |

All five regenerated at v0.5.299, and **every one came back with a one-line
diff — the version stamp** — which is what a regeneration after a run of
census-only commits should look like. `VIBRATO.md` carries no stamp at all, so
it regenerated byte-identical; that is worth knowing before reading its mtime
as evidence of anything.

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

## Corpus at v0.5.294

* 95 files; **83 measured**, 80 of 83 in reach converted, 3 failed, 12 out of
  scope (not a Hubbard player).
* mean melody **91%**, sequence **90%**, pitch **94%**, wave **79%**,
  ADSR **65%**, gate **47%**.
* noise frames ours/original **76332 / 82742**.
* *plays the same music* (95–100%) **54 files**; close 18; recognisable 7;
  plays something else 4 (Commodore_64_Music_Examples, Dragons_Lair_Part_II,
  Geoff_Capes_Strongman_Challenge, Kings_of_the_Beach_ingame).
* drift: 46 of 79 exact; 33 part company at a median 9.2 frames per 1000.
* `presets.json`: 83 songs, 22 `always` keys, 47 carrying a `--fidelity`
  setting.
* Vibrato census: 136 instruments, 42618 reversals missing, **114 emitting no
  oscillation at all**.

## New surface added during the run

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
current scheme.

## Open questions for the user

1. **Listening material is 44 versions stale** (13 Aug, v0.5.238) — re-stage?
2. Is the bit-6 rest worth a fourth attempt now that its emitter is fixed, or
   should it be parked?
3. What scheme should method-doc sections use past § 7.zzzzz?

## Immediate next action

**Re-stage and listen.** Mean melody has moved 88 → 91% and *plays the same
music* 46 → 54 files since anything was auditioned, and the two verdicts that
did arrive mid-run each opened a productive thread. Everything else on the queue
is a ship-or-refuse decision, and this run contains four instances of a
measurement instrument confidently reporting a mechanism that did not exist.
</current_state>
