<original_task>
Continuation of long-running work on **H2G**, a signature-based ripper that
converts Rob Hubbard `.sid` files into GoatTracker `.sng`, at
`C:\Users\mit\claude\h2g`. The session opened by reading the previous handoff
(then at v0.5.208) and ran to **v0.5.225**.

There was no single up-front task. The session was driven as a sequence of short
directives — "read what next", "do the next task", "go on" — each answered before
the next was given. The working mode is the project's established one:

> measure the conversion against the original, find where they differ, read the
> 6502 to learn why, fix it, re-measure across the corpus, and ship or refuse to
> ship on the measurement.

The directives, in order, were roughly: read the handoff and pick the next task;
run the full `--fidelity` corpus search; do items #2/#3/#4 of the previous
handoff (filter sweep, Commando's drum sweep, the `0AF8` precedence question);
push and commit; then a design question — *"would better telemetry from
GoatTracker help, or should we build an HTML viewer? and can we improve the
fidelity tracker too?"* — which produced `songview.py`, `siddump -w` and the
`onset` dimension; then repeated "go on" driving the drum-sweep multiplier fix,
the attack-transient investigation, the `$40` halving, two harness bugs, and the
corrected corpus search.

Scope note: everything is inside the Python port (`python/h2g/`) plus its
measurement harness (`python/fidelity.py`, `python/presets.py`,
`python/instrmap.py`, new `python/songview.py`) and the vendored siddump
(`python/tools/siddump-rt/`). The VB6 original was not touched.
</original_task>

<work_completed>

## Summary

**17 commits, v0.5.209 → v0.5.225, all pushed.** HEAD is `31294e2`, master in
sync with `origin/master`. `877 passed, 2 skipped`. `Commando.sng` remains
byte-exact throughout (the project's only fidelity anchor). Working tree clean
apart from untracked `6581.pdf` (deliberate, all session).

---

## Part 1 — the previous handoff's work items

### v0.5.209 — `59f36b8` — apply the full `--fidelity` corpus search

Ran `presets.py --fidelity -t 60` over the corpus (item #1 of the old handoff).
80/95 convertible, 19 files took a non-default setting.

**Caught a bad selection before committing.** `Dragons_Lair_Part_II` picked up
`pitch_seq` at 14% melody. `fidelity.py --diagnose` showed why: the file's own
init routine remaps subtunes, so the original's subtune 0 is *our* subtune 9
(89% match there against 9% on the diagonal) — the search compared two different
pieces of music. Added it to `presets.FIDELITY_VETOED`, broadening that
dict's documented purpose from "a listening test rejected this" to "…or the
measurement that chose it is known to be invalid". Renamed the log line from
"vetoed by a listening test" to "vetoed (see FIDELITY_VETOED)".

Also trimmed `FIDELITY_CONFIRMED` for Trans-Atlantic from three entries to one:
the search now selects `sfx_drum` and `pitch_seq` independently, so only
`wave_program` still needs the hand-recorded override. Updated the pinning test
in `tests/test_wave_program.py`.

### v0.5.210 — `3720d33` — filter cutoff detection (old handoff item #2)

Delegated to an Opus agent in a worktree. **The item was stale**: effect bit
`$20`'s filter sweep was already decoded and shipped at v0.5.72; the handoff had
re-discovered a mechanism that had existed for 132 commits.

The real gap was detection coverage. `FILTER_CUTOFF_SHAPES` only matched an
`LDA #imm` immediately followed by one `STA`, missing players that clear several
per-voice arrays with one `LDA #imm` feeding a *run* of consecutive `STA arr,X`.
New `detect._burst_cutoff_start()` walks backward from a `STA cutoff_var,X`
through an unbroken run of same-opcode stores to the feeding `LDA #imm`,
explicitly skipping the sweep routine's own `CLC/ADC/STA`. Corpus filter
coverage **15 → 21 files**; verified on two independent files (Lightforce `filt`
0/2998→2993/2998, Sanxion 0/1809→2416/1809).

### v0.5.211 — `a8ebd94` — `_noise_tick_frames` crash

Found while investigating the drum sweep. `SongSpeeds.frames` is
`Tuple[Optional[int], ...]` — a subtune whose reload exceeds
`MAX_SANE_SPEED_RELOAD` reports `None` — but the guard only caught an *empty*
tuple. `Counter(frames).most_common(1)[0][0]` could return `None` into
`max(1, modal - 1)` and raise `TypeError`, silently marking the whole file
unconvertible. Filtering `None` out before taking the mode recovered
**Geoff_Capes_Strongman_Challenge, Gerry_the_Germ, Spellbound**; presets
convertible count 80 → 83.

### v0.5.212 — `346a160` — the drum sweep's second bound (old handoff item #3)

Delegated to an Opus agent (worktree). The Warhawk-family drum block has **two**
exits and only one was expressed:

```
136D  LDA freqhi,X    / BEQ out     ; the frequency reached zero  <- _drum_max_steps
1372  LDA remaining,X / BEQ out     ; the NOTE ended              <- nothing read this
```

`_drum_max_steps`' docstring claimed "the safety bound and the musical target
turn out to be the same number". They coincide only when the note is long enough
for the frequency to reach zero first. Commando's instrument 13 has room for 13
steps by pitch and its original takes 5, because its note is four rows long.

New `patterns.median_played_durations` measures each instrument's typical note
length in rows. **The median, not the minimum** — a wavetable holds one sweep for
all of an instrument's notes, and the reduction minimising total error against a
distribution is its median. The minimum deletes Bump_Set_Spike's sweep outright
(its record 0 plays at 2, 4 and 6 rows in near-equal measure). Scored as
play-weighted L1 error: pitch bound alone 320070, minimum 117806, mode 100102,
**median 99983** (best-or-tied on all 122 measurable records against the
minimum's 97).

`goatwriter._drum_duration_steps` converts rows to steps against the row's call
rate; `_drum_entries` applies whichever bound is smaller. Verified end to end on
Commando *and* Bump_Set_Spike (the "second file that uses it differently" rule).
The agent also disproved the prior session's blocker: `apply_tempo` was a red
herring, `CMD_SETTEMPO` only lands in row 0's command columns.

### v0.5.213 — `eb133f1` — compose effect bits `$04` and `$10` (old handoff item #4)

Delegated to an Opus agent (worktree). Trans-Atlantic's player copies the
record's `+7` to scratch `$0EFB` once then tests it five times in a row — `$08`
at `$0B44`, `$04` at `$0B9C`, `$10` at `$0BB8`, `$20` at `$0BEB`, `$40` (as
`BIT`/`BVC`) at `$0C05`. `$04`'s handler falls through a bare `CLC` into
`$10`'s, so nothing can skip the second test. Record `0AF8` (`$14`) gets both.

New `_two_stage_pitch_seq_entries` builds one block carrying the attack waveform
and the arpeggio's note on every frame. Gated **per record** on both bits.
Trans-Atlantic `0AF8`: reversals **0 → 392** against the original's 411, `vib`
0.72x → 0.87x, every other column identical.

**The second-file check caught a defect no review would have.** Forcing it on
Thundercats gave *exact* reversals (1308 vs 1308) while `melody` fell
**77.3% → 65.7%** — the shared rotation opened its sequence on `+3`, and
wavetable entry 0 lands on the note's first call, renaming all 148 notes three
semitones sharp. The block now opens on a zero step where the cycle has one;
Thundercats then holds 1308/1308 with melody unchanged and Trans-Atlantic's bytes
do not move.

### v0.5.214 — `6a01aff` — FIDELITY.md regeneration for v0.5.210–213

---

## Part 2 — the design question and the instruments it produced

The user asked whether better live telemetry from GoatTracker would help, or an
HTML viewer, since "GT is very compact while HTML does not have this
limitation"; and separately said the fidelity tracker could be improved too.

**The answer given**, and the reasoning that shaped the rest of the session: the
data mostly already existed — `instrmap.py` had *already* computed the
Trans-Atlantic answer and printed it in a table. The gap was **comprehension and
attribution**, not measurement. Live GT telemetry was ranked *last* because the
fidelity harness never runs GoatTracker (it packs with `gt2reloc` and traces with
`siddump`), so telemetry from the editor would measure a **different execution
path** than every number in the repo — the shape of the v0.5.131/132 mistake.

### v0.5.215 — `786966c` — `python/songview.py`

An HTML view of what a `.sng` *says*, as opposed to what it measured. Parses the
whole file and renders one self-contained page (no external assets). Rendering
verified in a real browser via Chrome MCP (19 instrument cards, 48 patterns, no
horizontal overflow; `file://` is blocked, so served over `python -m http.server`
on 127.0.0.1).

Three things the editor cannot do:
- **every pattern carries all three identities** — GT's hex number, the
  post-dedup index, the Hubbard source (retires the confusion that cost three
  debugging attempts);
- **wavetable entries carry cumulative call timing** — a delay entry is current
  for `value + 1` calls (gplay.c:697-704), the off-by-one that stood from
  v0.5.82 to v0.5.130;
- **instruments decode their effect bits** from the provenance stamp
  `_write_instruments` already writes into the name (`NN:b5-b6-b7`, where b7 is
  the player's effect byte — a gift discovered while reading the writer).

Uses `fidelity._preset_opts` rather than re-implementing option filtering.
`tests/test_songview.py` (11 tests) checks the parser against `build_sng`'s
output and the byte-exact fixture — the parser is a deliberate *second* reader,
and the test is what makes that safe.

### v0.5.216 — `a0ae0b2` — `siddump -w`

Added to the vendored `python/tools/siddump-rt/siddump.c`:
`-w<adr>[,<adr>...]`, up to 16 addresses, dumped once per displayed frame from
the same `mem` and at the same point as the SID registers. Closes the one thing
register traces cannot show: *which wavetable entry produced a register*.

Printed verbatim every frame, never elided to `..` — a pointer that stops moving
is the signal being looked for. **Proved inert without the flag** by rebuilding
the pre-patch source and diffing output on `Commando.sid -a0 -t5`: byte-identical.
Documented in that directory's README.

### v0.5.217 — `f98d6bf` — the `onset` dimension

`fidelity.onset_shapes` / `onset_agreement`: the waveform classes a note *opens*
on, over `ONSET_FRAMES = 4`, keyed by the ADSR one frame after the attack
(instrmap's rule — the attack frame can hold a hard restart's envelope). Key is
`$D405/$D406`, measured value is `$D404`, so the attribution cannot contain the
quantity attributed.

**Two errors caught during implementation, both now pinned by tests:**
1. I first passed the startup lag in. Wrong — each side is read at its *own*
   attack frames, so the latency cancels by construction; passing it would
   manufacture the phase error the column detects.
2. I wrote `early`/`late` backwards. `ours == orig[1:]` means we never played the
   original's first frame, i.e. **early**.

Corpus at introduction: 415 instruments, 55% matched, **32 early / 0 late** —
a one-sided split that is what a systematic emitter defect looks like.

### v0.5.218 — `938fe7a` — the note's first frame belongs to the record

Delegated to an Opus agent (worktree), briefed with the full evidence.
`_wave_program_entries` and `_two_stage_entries` opened on the *effect* where the
player writes the record's own `+2` waveform on the note's first frame and
reaches the effect only from the second. `_drum_entries` had been corrected to
this in v0.5.172 and the lesson never propagated.

Two refinements the agent found that the brief did not anticipate:
- **a record whose `+2` is `$00` must get no entry** — no waveform and no gate on
  frame 0, so siddump sees no gate edge and calls the *second* frame the onset;
  and `$00`-`$0F` are wavetable delays, so there is nothing faithful to put;
- **one frame is `multiplier` calls** — Thundercats at `-S3` only becomes
  frame-exact with the lead scaled.

Cross-validated by the `onset` column, which the agent never saw: **32 early →
23**, matched 228 → 237, six files up and none down. Trans-Atlantic onset
71% → 100%, melody 85% → **95%**.

### v0.5.219 — `42f42fb` — commit the prior session's handoff document

Finished a half-done commit left by a `/subtask` fork (it had bumped the version
and written the CHANGELOG entry but not committed).

### v0.5.220 — `3f281cc` — the drum's first frame is a frame, not a call

The 23 instruments still reading early were **20 of 21 multiplier-2 files against
3 of 45 single-speed ones**. `_drum_entries` had opened on the record's waveform
correctly since v0.5.172 but its entry lasted **one call at every `-S`** — its own
docstring said so, reading as a description rather than as the defect. At `-S2`
the waveform covered half of frame 0 and the noise tick finished the frame; siddump
samples at end of frame, so frame 0 read as the drum.

Extracted `_first_frame_lead(wave, multiplier, force=False)`, shared with
`_two_stage_entries` — applying v0.5.218's own lesson to itself. `force=True` for
`_drum_entries`, which has *always* emitted that entry, so gating it on
`_first_frame_entry` would be a second, unmeasured change (deleting it for
records whose `+2` selects no waveform).

Result: matched **237 → 254**, early **23 → 14**, ten files up and none down.
Warhawk (the canonical drum player of § 7.ii) 0% → 67%; Last_V8 and its C128
version → 100%. **melody, sequence, adsr, nrun, tail and pitch all moved on
exactly zero files** — the signature of a change that relocates a waveform within
frame 0 and nothing else.

---

## Part 3 — the attack-transient investigation

Starting from the user's concern that they *"cannot explain what is wrong with
Trans-Atlantic from a fidelity perspective"*.

**The chain that answered it:** `songview.py` made the wavetable legible and
showed instrument 3's bytes were *right* → reframed the defect from "wrong
waveform" to "wrong frame" → a trace comparison confirmed it and found it in a
second emitter → the `onset` column made it measurable → the fix landed and the
column independently confirmed it.

### The corpus census (scratch, not committed)

`scratchpad/transient_census.py` measures, from the traces and never from the
effect byte, instruments where the original changes waveform class on frame 1
while we hold frame 0's. At v0.5.220: **45 files, 109 instruments, ~13,720
notes**.

**A methodological error made and corrected here:** I first split those by the
transient's *timbre* (noise ⇒ drum tick, pitched ⇒ two-stage). Sigma Seven killed
that — zero records set bit `$01` yet both instruments sound a noise transient. A
noise transient is just as likely a two-stage attack whose attack waveform is
noise. The timbre split was withdrawn.

### v0.5.221 — `3fa22f8` — the `onset` criterion in `fidelity_better`

`fidelity_better`'s docstring already recorded that it is *deliberately* not
scored on `wave`, because restoring a 1–4 frame transient moves `wave` the wrong
way even when right. The unintended consequence: `--two-stage` was
**unselectable** — the attack strikes no new note, sounds no new register and
leaves melody untouched, so none of the four existing terms could see it.

Added a **graded** `onset_frame_agreement` (new in `fidelity.onset_agreement`)
rather than the report's per-instrument `onset_agreement`. Checked both
alternatives before writing the term: whole-shape equality scores Sigma Seven's
`$0FFD` (no transient → transient one frame too long) as **zero**, and
`onset_first_matched` cannot see it either because frame 0 already agreed.
Verified it declines as well as accepts. `tests/test_onset_criterion.py`, 6 tests.

### v0.5.222 — `b320b54` — bit `$40` halves bit `$04`'s attack

Resolved an open question `H2G-CONVERSION-METHOD.md` had carried as *"the
relationship between that byte and the shared `$0FAA,X` counter is not
established"*.

```
frames 2, effect $44  -> 1 frame   Sigma Seven $0FFD (124), Ricochet $0CE8 (77),
                                   Skate or Die $08D9 (300), $0AD8 (26)
frames 4, effect $44  -> 2 frames  Trans-Atlantic $0A99 (150), Sanxion $1909 (81),
                                   Pandora $0D99 (31), Auf W. Monty $0AF9 (10),
                                   Knucklebusters $0AAD (4)
frames 2, effect $04  -> 2 frames  Sigma Seven $2B9D (61)
```

527 onsets on the first line with no counter-example. **The `frames = 4` line is
what rules out "a record with `$40` always sounds one frame"** — at `frames = 2`
a halving and a constant 1 are indistinguishable, and I nearly shipped the
constant. `goatwriter._two_stage_frames(frames, effect)` returns
`max(1, frames // 2)` when `EFFECT_FIXED_PITCH_MASK` is set. Implied mechanism
(an implication, not a reading of the 6502): `$40`'s handler decrements the same
per-voice attack counter, so with both live it counts down twice per frame.

One counter-example recorded rather than smoothed over: **Lightforce `$1FF9`** is
`$44` with `frames 4` and measures 0 attack frames over 15 onsets. Unexplained.

Effect (melody unchanged everywhere): Sigma Seven onset 0.625 → **1.000**,
Sanxion 0.750 → 0.938, Skate or Die 0.500 → 0.625, Ricochet 0.650 → 0.700,
Trans-Atlantic 0.958 → 1.000. **Ricochet and Skate or Die are the point** —
before the halving, forcing `--two-stage` on them moved their onsets not at all,
so v0.5.221's criterion correctly declined them. The halving makes them
*selectable*.

### v0.5.223 — `909ab85` — two measurement bugs in the preset search

Found by refusing to commit a search result containing "One_on_One… (melody 5%)"
and asking why a 5% file was being tuned at all.

`presets.tune_by_fidelity` is a second implementation of "convert, pack, trace
both, compare" beside `fidelity._measure`, and nothing pinned them together:

1. **No calibration.** `_measure` traces the original with
   `calibration(ft.detune)` where the frequency table sits off the semitone grid;
   the search passed a hardcoded `0`, so siddump named every note of those files
   against the wrong table. Four corpus files (Kings_of_the_Beach_intro,
   One_on_One_Jordan_vs_Bird, Powerplay_Hockey, Rock_Tells_the_Tale, all
   detune −0.696, cal `4280`). One_on_One went 5% → **99%**.
2. **No subtune counterpart.** `_measure` searches a window of *our* subtunes and
   keeps the best match (`--search-subtunes`, **default 3**); the search compared
   the original's N against our N. Action_Biker reads **6%** that way and
   **100%** the other, and on that 6% the search "improved" it to 8% with
   `no_test_restart`. It now selects nothing, which is correct.

The counterpart is resolved **once**, on the reference conversion, and reused for
every candidate — three traces per candidate would triple a search already
running 31 combinations a song, and the toggles vary no orderlist length. That
assumption is stated where it is made.

### v0.5.224 — `6e54cc0` — `tests/test_search_matches_report.py`

Four tests pinning the search to the report. **Both bug-catching tests were
verified to fail when their bug is reintroduced** (`presets.py` saved to
`/tmp/presets_good.py`, sabotaged with assert-matched edits, tested, restored;
`git diff` confirmed empty afterwards). The subtune test asserts the *method*
(more than one of our subtunes is probed), not the outcome, because which
subtunes fit legitimately moves. A guard test checks the two named files still
exhibit what they are there for, so a corpus change cannot leave them passing
vacuously. They run one toggle rather than the 31-combination sweep (~1 s).

### v0.5.225 — `31294e2` — the corrected corpus search

**34 settings gained across 28 files, 4 lost.** `--two-stage` reaches 26 files
where 3 had it; `--wave-program` 11 where 1 did. A/B against the previous presets
**at fixed code**, so the comparison isolates the settings:

```
onset   62.1% -> 76.2%   +14.1pp   26 files up, 0 down
nrun    48.9% -> 51.7%    +2.8pp    2 up, 0 down
wave    74.0% -> 74.4%   +0.35pp   14 up, 12 down
melody, sequence, adsr, tail, pitch    flat to within 0.02pp
```

Both bogus selections from the broken run are gone.

### Post-fix census

45 → **27 files**, 109 → **59 instruments**, 13,720 → **7,047 notes**. Of the 27:
10 have a two-stage routine, 20 have a wave program, **7 have neither**
(Bump_Set_Spike, Chicken_Song, Crazy_Comets, Gerry_the_Germ, Hollywood_or_Bust,
International_Karate, Ninja).

Forcing each option on split the remainder into two classes:

```
IK_plus  as shipped     onset 0.450  melody 99%
         +wave_program  onset 0.350  melody 76%    <- worse both ways
         +two_stage     onset 0.550  melody 86%    <- onset up, melody -13pp
Mega_Apocalypse / International_Karate: identical under all three settings
```

- **Class A** — the option exists and costs more than it gains (emitter quality
  problem, the same shape the `$40` halving fixed for Ricochet).
- **Class B** — no current option touches them (unimplemented mechanism).
</work_completed>

<work_remaining>

Ordered by value.

### 1. Class B transients — the mechanism nothing implements

**Mega_Apocalypse and International_Karate measure identically under
`--two-stage`, `--wave-program` and as shipped**, so some other routine writes
`$D404` on the note's second frame. International_Karate is in the
neither-routine set, so it is the cleanest case.

Method: `python fidelity.py <file> --diagnose` first, then the per-instrument
detail script (`scratchpad/onsetdetail.py`, see below) to get the exact shapes,
then read the player. **`siddump -w` (v0.5.216) exists for exactly this and has
still never answered a question** — the packed player's wavetable pointer per
voice would say which entry produced a frame. The retrodebugger MCP
(`mcp__retrodebugger__*`) is also available for a memory breakpoint on `$D404`.

**Do not infer the mechanism from the transient's timbre.** That error was made
and refuted twice this session.

### 2. Class A transients — emitter quality on IK+ and the other 19

`--two-stage` on IK+ raises onset 0.450 → 0.550 and costs 13 points of melody,
so `keeps_notes` refuses it. Something in the emission is wrong for that file in
a way the `$40` halving was wrong for Ricochet. Finding it would flip those files
from "declined" to "selected" without any change to the criterion.

### 3. Lightforce `$1FF9`

`$44` with `frames 4`, measures **0** attack frames over 15 onsets where the
halving predicts 2. One record against nine. Recorded in `_two_stage_frames`'
docstring; unexplained.

### 4. Calibrate the 155 "other disagreement" onsets

Mean `onset` is 76.2% and the absolute level is **not calibrated** — the column
demands an exact 4-frame class match, and an unknown share of the disagreements
are legitimate differences rather than defects. Until this is understood, quote
the *movement* of `onset`, not its level. (Note the 4-frame window itself,
`ONSET_FRAMES`, is a choice: short on purpose so it does not start charging for
note length.)

### 5. Documentation debt

`H2G-CONVERSION-METHOD.md` has sections through **§ 7.www** (v0.5.218) and
**§ 7.ccc** (v0.5.212). **v0.5.220, .221, .222, .223, .224 and .225 added no
method-doc section.** CLAUDE.md requires the write-up to move with behaviour
changes — it is used as reference material by another project. Sections owed:
the multiplier half of the first-frame rule, the `onset` dimension, the `$40`
halving, and the two harness bugs. `CLAUDE.md` and `README.md` *were* updated
throughout.

### 6. `songview.py`'s comparison overlay

The designed selling point that was never built: `instrmap`'s per-instrument
original-vs-ours tables, linked and sorted with flagged deltas on top. The `.sng`
side is done. This would turn the scratch scripts used repeatedly this session
into a first-class view.

### 7. Older, still open

- The speed gate is under-read by a tune-specific 1.1–1.5× across the corpus
  (`goatwriter.find_song_speeds`). Per-file targets in `build/pace.txt`. Use
  `fidelity.py <file> --pace` before saying anything about tempo.
- `FIDELITY.md` still has no noise-pitch column.
- Trans-Atlantic's noise frames are 1053 against the original's 1089 — all 36 are
  GT 3's snare final frame, because our note is one frame shorter than the
  original's. **No column measures note length.**

### 8. Listening verdicts pending

Nothing has been auditioned since the v0.5.209 corpus run. 28 files changed
settings at v0.5.225 and none has been heard. Use `.\play.ps1 <file> -Presets
presets.json` — **never launch `goattrk2.exe` directly**.
</work_remaining>

<attempted_approaches>

## Refuted, reverted, or refused

1. **"The remaining early onsets are the § 7.ii drum tick"** — refuted by Sigma
   Seven: zero records set bit `$01` yet both instruments sound a noise
   transient. I had inferred mechanism from timbre.
2. **"The transients are two-stage, detected but simply not enabled"** — looked
   compelling and was *initially measured as refuted* (forcing the option fixed
   1 instrument of 16). **That reading was itself wrong**: I read only the
   matched count and missed that Sigma Seven's `$2B9D` became frame-exact while
   `$0FFD` went from no transient to one a frame too long. Corrected next turn.
3. **"A record with `$40` always sounds one attack frame"** — nearly shipped.
   Indistinguishable from a halving at `frames = 2`; the `frames = 4` records
   (which measure 2, not 1) separate them.
4. **"The search and the report disagree because of subtune correspondence"** —
   dismissed early on a misread (`if args.search_subtunes > 1` assumed to default
   to 1; it defaults to **3**). Correct after all.
5. **"The two harnesses actually agree"** — "confirmed" using a hand-built `args`
   object that was itself misconfigured and coincidentally reproduced the search's
   wrong number. Instrumenting the *real* CLI path via monkeypatched
   `run_siddump` is what settled it.
6. **`_first_frame_entry` gating for `_drum_entries`** — would have *removed* the
   entry for records whose `+2` selects no waveform (a different change from "do
   not add one"). Caught before running; hence `force=True`.
7. **Passing the startup lag into `onset_agreement`** — would manufacture the
   phase error the column detects. Caught before committing.
8. **`early`/`late` written backwards** in `onset_agreement`. Caught by comparing
   against an independent scratch analysis; both directions now have tests.
9. **Committing the first corrected-criterion search** (39 files) — refused. It
   was taken on the broken harness. `presets.json` was reverted with
   `git checkout`.
10. **Letting the first v0.5.221 search finish** — killed at ~2/3 when the `$40`
    halving was found, because the `$44` files it had not yet reached were exactly
    the ones the finding would change. `presets.py` writes only at the end, so
    nothing was left half-written.
11. **A `python - <<'PY'` heredoc edit** whose `\\n` became a literal newline and
    broke a string literal across two lines. The `assert old in s` guard fired
    correctly but only proves the *match*, not that the result parses. Now also
    `ast.parse` the file after scripted edits.

## Delegation pattern that worked

Four Opus agents in isolated git worktrees (`isolation: "worktree"`), each
briefed with the full evidence and told to verify on a second file, not to
commit, and not to touch generated artefacts. Patches were exported with
`git diff`, applied with `git apply --3way`, tested, then committed by the main
session. Every one found something the brief did not anticipate. One (v0.5.212's
predecessor, a `/subtask` fork) correctly **reverted its own work** rather than
ship an unverified fix.

Caveat learned: a `/subtask` fork cannot spawn its own subagents, so
`/subtask do 2 / do 3 / do 4` ran only item 2.
</attempted_approaches>

<critical_context>

## Environment

- Repo `C:\Users\mit\claude\h2g`, branch `master`, HEAD `31294e2`, pushed.
- Corpus (95 files): `C:\Users\mit\claude\c64server\SIDM2\SID\Hubbard_Rob`
- GoatTracker 2.77 source: `C:\Users\mit\Downloads\GoatTracker_2.77\src`
  (`gplay.c`, `gsong.c`, `gcommon.h`). `gt2reloc.exe` and `goattrk2.exe` are in
  that tree's `win32/`; `fidelity.py` hardcodes the path (`H2G_GT2RELOC`
  overrides).
- `build/` is gitignored; `6581.pdf` untracked deliberately.
- Python 3.14, stdlib only at runtime.
- Scratch scripts used repeatedly and worth recreating:
  `scratchpad/onsetdetail.py` (per-instrument onset shapes, both sides, one
  file), `scratchpad/transient_census.py` (corpus census of unrendered
  transients), `scratchpad/phase.py` (parses instrmap's folded dumps).

## Rules added to CLAUDE.md this session

1. **A lesson recorded in one emitter is not a lesson in the file.**
   `_drum_entries` fixed the first-frame rule in v0.5.172; two siblings in the
   same file carried the defect for 45 versions. When a fix is really a *rule
   about the player*, give it a name every emitter calls and a column that fails
   when one stops — `_first_frame_entry`/`_first_frame_lead` and `onset`.
2. **The rule had a second half nobody stated**: one frame is `multiplier` play
   *calls*. `_drum_entries`' docstring described its one-call lead as a fact
   rather than as the bug.
3. **`onset` is the column that sees a mechanism emitted one frame out of
   phase**, and it takes no startup-lag correction.

## Non-obvious behaviours discovered

- **`--search-subtunes` defaults to 3**, so `fidelity.py` routinely compares the
  original's subtune N against our N±1 and keeps the best. Any second harness
  must do the same.
- **`run_siddump`'s fifth positional argument is the calibration**, not a flag.
  Four corpus files need it.
- The instrument **name** field in a `.sng` is the converter's provenance stamp,
  `NN:b5-b6-b7`, and b7 is the player's effect byte — decodable without
  re-running detection.
- `SongSpeeds.frames` can contain `None`.
- Chrome MCP cannot open `file://` URLs; serve over `127.0.0.1`.
- A `.sng`'s wavetable right side: `$00`-`$5F` relative up, `$60`-`$7F` relative
  down, `$80`-`$DF` absolute note.

## Assumptions needing validation

- The `$40` halving's implied mechanism (a shared per-voice counter decremented
  by both handlers) is **inferred from two measured points**, not read out of the
  6502. Lightforce contradicts it once.
- `tune_by_fidelity` resolves the subtune counterpart **once** and reuses it for
  all 31 candidates, assuming no toggle changes orderlist length.
- `onset`'s 4-frame window and its exact-match rule are choices, not measurements.
</critical_context>

<current_state>

## Repository

- **HEAD `31294e2` (v0.5.225), pushed; `master` in sync with `origin/master`.**
- Working tree clean except untracked `6581.pdf`.
- `python -m pytest tests/ -q` → **877 passed, 2 skipped** (the two skips are
  environment-gated on `H2G_GT2RELOC`).
- `Commando.sng` byte-exact.
- `SURVEY.md`, `presets.json`, `FIDELITY.md` all regenerated at v0.5.225 and
  committed.

## Corpus state

- 83 of 95 files convertible (up from 80 — the v0.5.211 crash fix).
- **38 files carry a non-default `--fidelity` setting** (up from 19):
  `--two-stage` on 26, `--wave-program` on 11, plus `sfx_drum`, `pitch_seq`,
  `no_test_restart` per song.
- Corpus means at v0.5.225: melody **85%**, wave **74%**, onset **76.2%**.

## Per-song overrides in `presets.py`

- `FIDELITY_VETOED` — `{"Dragons_Lair_Part_II.sid": {"pitch_seq"}}`, because its
  init routine renumbers subtunes and the measurement that chose it compared two
  different pieces of music.
- `FIDELITY_CONFIRMED` — `{"Trans-Atlantic_Balloon_Challenge.sid":
  {"wave_program"}}`.

## New surface added this session

- `python/songview.py` + `tests/test_songview.py` (11)
- `python/tools/siddump-rt/siddump.c` — `-w` (documented in its README)
- `fidelity.py` — `_wave_class`, `ONSET_FRAMES`, `onset_shapes`,
  `onset_agreement` (incl. `onset_frame_agreement`), the `onset` Dimension and
  table column
- `presets.py` — the `opens_right` term, calibration, the subtune-counterpart
  probe
- `goatwriter.py` — `_first_frame_entry`, `_first_frame_lead`,
  `_two_stage_frames`, `EFFECT_FIXED_PITCH_MASK`, `_two_stage_pitch_seq_entries`,
  `_drum_duration_steps`
- `patterns.py` — `median_played_durations`, `_pattern_plays`,
  `_entry_instruments`
- `detect.py` — `_burst_cutoff_start`
- New tests: `test_songview.py`, `test_onset.py` (10),
  `test_onset_criterion.py` (6), `test_two_stage_frames.py` (5),
  `test_search_matches_report.py` (4), `test_two_stage_pitch_seq.py` (7)

## Open questions for the user

1. **Nothing has been auditioned since v0.5.209.** 28 files changed settings at
   v0.5.225. The `onset` gain is large and every other column is flat, but that
   is a register argument, not a listening one.
2. Whether Trans-Atlantic now sounds right — it has changed substantially
   (v0.5.213, .218, .222).
3. Whether the documentation debt (§ 5 of Work Remaining) should be paid before
   more code lands.

## Immediate next action

The transient thread is characterised and paused at a natural boundary, with the
two classes separated and evidenced. The highest-value next step is **Class B**:
take International_Karate or Mega_Apocalypse and find what writes `$D404` on the
note's second frame — using `siddump -w` or the retrodebugger, **not** by
inferring the mechanism from the transient's waveform.
</current_state>
