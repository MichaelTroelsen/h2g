# A/B fidelity automation — design

Date: 2026-09-01. HEAD at time of writing: `be759f0` (v0.5.446).

## Goal

Fewer listening sessions. Today a human verdict is one bit per tune
(`approved.json`, 4 of 83 tunes), pinned to a `.sng` sha256, so any byte
change invalidates it and every measured gain on that tune is withheld in
`presets.FIDELITY_VETOED` until someone listens again. ACE_II has carried
+15 `gate` and +3 `adsr` that way since v0.5.394/407. Eleven of the 34 open
tasks in `.claude/tasks/whattask.json` are `requires-user`, and the three most
valuable of them are listens.

The reason listens exist is that every column of `FIDELITY.md` reads SID
registers via siddump and nothing reads the rendered sound — timbre, filter
movement, envelope shape and the volume nibble are invisible to the report.
This design adds an audio-domain measure, lets a human approval survive a
change the measure can vouch for, makes the preset search respect approvals
by measurement rather than by a hand-written veto list, and turns the
report's misses into a ranked queue that `/whattask` reads as a source.

Out of scope: making listening sessions themselves more structured; a scalar
score across columns; any change to `python/h2g/` (the converter stays
stdlib-only and byte-identical throughout).

## 0. Naming, amended when the plan was written

`fidelity.py --audio` **already exists**: it shells out to SIDM2's
`audio_tightness_tool.py` (onset-timing jitter, never run in the report).
So this design's names are: flag `--sound` (and `--sound-voices` for the
per-voice diagnostic), module `python/sound.py`, calibrator
`python/sound_calibrate.py` writing `docs/SOUND-CALIBRATION.md` and
`build/sound_calibration.json`, approvals `python/approvals.py`, queue
`python/fidelity_queue.py`. The report columns stay `aud` and `loud`. The
calibrator and queue are separate scripts rather than `fidelity.py` flags
because that file is 7000 lines. In §3 the vetoes and the inheritance check
are applied to each song's **final winner** against its default, not to every
candidate — one render per song rather than thirty-one. In §5 check 4, the
Last_V8 half-speed audition is dropped: it is a siddump calls-per-frame trap,
not a render, so there is no wrong-rate WAV to score. Wherever the sections
below say `audio.py`, `--audio`, `--audio-calibrate` or `--queue`, read the
names above.

## 1. The audio metric — `python/audio.py`

**Dependencies.** numpy, harness only. `python/h2g/` remains stdlib-only.
Rendering via `sidplayfp` through `listen.pick_renderer`, same settings both
sides (`-fo0`, one chip model), so a difference in the WAVs is a difference in
the music. RSIDs need the ROMs README already documents.

**Two report columns**, both `Dimension` entries in `python/fidelity.py`:

- `aud` — spectral agreement in [0, 1]. Log-mel spectrogram per side
  (64 bands, 20 Hz–8 kHz, 2048-point FFT, 512-sample hop, ≈86 frames/s);
  per-frame normalised L1 distance between the two, averaged over the window,
  reported as agreement the way `wave` is.
- `loud` — loudness. Per-frame RMS in dB: envelope agreement plus an overall
  level ratio. The first instrument in the repo that reads the volume nibble.

Per-voice variants (`fidelity.py --audio-voices`) reuse the per-voice renders
`listen.py --voices` stages and are diagnostic output, not report columns.

**Alignment.** The packed player starts 3–8 frames late. The audio side does
not trust `startup_lag` (a siddump-attack quantity on a different clock): it
cross-correlates the two RMS envelopes within ±0.5 s using `startup_lag` as
the prior, and reports the lag found beside the column. The search window is
bounded and the objective is envelope correlation, never the spectral score
itself — estimated from the signal, not fitted to maximise agreement.

**Silence.** Frames both sides spend silent leave numerator and denominator
alike (`_graded_agreement`'s rule). A frame silent on one side only counts
fully against.

**Registry.** The two Dimensions declare `reads = AUDIO`, a sentinel rather
than a register list, so *What this run compared* names "rendered audio"
honestly. If numpy or the renderer is missing the columns print `-` and the
report header says why; an absent dimension recommends nothing.

**Cost and caching.** Renders live under `build/audio/`, keyed by content:
`<stem>.orig.<sid-sha12>.wav` and `<stem>.<sng-sha12>.wav`. A corpus pass
renders only cache misses. `fidelity.py --audio` is on-demand (like `--vice`)
until §5's calibration passes; it is not a default.

**Blind spots, written into the Dimension descriptions.** The metric does not
know which side is wrong. It cannot see a right note at the wrong time beyond
the alignment window (`drift` and `len` do). A change that removes events can
raise it — the same trap as `wave` (H2G-CONVERSION-METHOD § 7.eee) — so it is
read beside both sides' attack counts, always.

## 2. Approval semantics — the approved render is a second reference

`approved.json` is unchanged: hand-written, sha-pinned, no tool writes it.

The approved `.sng` is rendered once (cached as
`build/audio/<stem>.<approved-sha12>.wav`) and becomes a second reference
beside the original. A new build **inherits** the approval when, on the same
window and alignment, all three hold:

1. **No farther from the original.** `aud` and `loud` of the new build against
   the original are at least those of the approved render against the
   original, within the noise floor §5 measures (check 2).
2. **Close to what was approved.** `aud`/`loud` of the new build against the
   *approved render* are at least the agreement §5 check 3 measures between
   two builds a listener called inaudible. The threshold is that measured
   number itself — the most distant pair a human has called the same — and
   every further inaudible-verdict pair recorded in `approved.json` notes
   tightens it. It must sound like the thing the person said yes to, not
   merely score as well.
3. **Nothing structural regressed** that the listener could have heard: attack
   count no farther from the original's, `melody`/`seq` within
   `FIDELITY_MARGIN`, `len` inside ±5 s. These reuse `fidelity_better`'s
   guards; no new bounds.

**Output.** `build/approvals.json`, one record per approved tune:

    {"<stem>": {"approved_sha": ..., "current_sha": ...,
                "status": "exact" | "inherited" | "stale",
                "since": "<version>", "builds_inherited": N,
                "evidence": {"aud_vs_orig": [approved, current],
                             "loud_vs_orig": [...], "aud_vs_approved": ...,
                             "loud_vs_approved": ..., "attacks": [...],
                             "melody": [...], "len": ...},
                "listener_should_check": "<the criterion nearest its threshold>"}}

`abpage.py`'s index and per-tune pages show three states: **approved
(exact)**, **approved (inherited — since sha …, N builds)**, **stale — needs
a listen**, with `listener_should_check` as the ask on a stale page.

**Rules.**
- Inheritance never creates an approval. A tune with no human verdict stays
  unapproved whatever it scores; the metric bounds how much a change moved,
  it is not evidence the result is right.
- Criterion 2 is always against the human-approved render, never the last
  inherited build, so small steps cannot walk away from the verdict.
- "Stale" now means only: a build that failed a criterion. That is the listen
  worth asking for.

## 3. Acceptance and vetoes — the search respects approvals by measurement

**`FIDELITY_VETOED` splits.** Structural vetoes (Dragons_Lair's wrong-subtune
pairing) stay hard-coded with their comments. Approval vetoes are removed:
`presets.py --fidelity` asks §2's question of every candidate on an approved
tune. A candidate that inherits is admissible; one that does not is refused
**with the criterion printed** to stderr, e.g.
`ACE_II: hard_restart_frames refused -- aud vs approved 0.71 below floor 0.83`.
ACE_II's `hard_restart_frames` entry is deleted on the commit that lands
this; its gain then ships or is refused on evidence.

**`fidelity_better` gains exactly two vetoes, no acceptors.** "Any one
improving" is a sound acceptance rule and an unsound replacement rule, and the
last five-veto version of this function rejected the candidate it existed to
protect (CLAUDE.md). Each bound is measured:

1. `aud` must not fall below the reference by more than §5's noise floor.
2. `len` must stay inside ±5 s.

**`drift` as an acceptance term — gated.** A candidate whose `drift` is closer
to 0 (log space, via `_closer`) with `melody`/`seq`/attacks unmoved is a win.
This is what makes `--regrid` searchable. It is gated on the existing task
`regrid-could-be-searchable-from-repeated-attack-run-length-without-a-trace`
closing with `FIDELITY.md`'s `drift` column and `--pace`'s integrated drift
shown to agree on the 13 hand adoptions — they have never been checked
against each other. Whether `regrid` then joins `FIDELITY_TOGGLES` (31 → 63
combinations) is the cost decision in
`regrid-is-not-in-fidelity-toggles-so-the-search-never-walks-it`, which stays
the user's.

**Refusals become a record.** Every refusal — inheritance, the two vetoes,
`will not convert`, `search failed` — is written to
`build/search_refusals.json` (`{song, option/combination, criterion, value,
bound}`), because a missing preset entry and a measured "no" are
indistinguishable in `presets.json`. §4 reads it.

**Unchanged:** `FIDELITY_MARGIN`, the greedy walk, `prune_inert`,
`--shard`/`--merge`.

## 4. The derived queue — `fidelity.py --queue`

**Output.** `build/queue.json` and `docs/QUEUE.md`, stamped with version, sha
and window like `FIDELITY.md`. `/whattask` lists `docs/QUEUE.md` as a source
beside `todo.md`. Nothing here writes `.claude/tasks/whattask.json`.

**An entry is a cause, not a file.** Fields: stable `id` (slug of source +
cause + file or file-group), `files`, `evidence` (the numbers), `tag`
(`[subagent]` / `[main]` / `[user]`), `verify` (a done-condition naming the
measurement that settles it), `first_seen`, `last_seen`, `already_tracked`,
`already_refuted`.

**Six sources; the tier is the rank.**

1. **Stale approvals** (§2). `[user]`, the ask is `listener_should_check`.
   Nothing else can close these.
2. **Length rule failures** — `len` outside ±5 s or `length_bounded` true.
   `[main]`.
3. **Search refusals** (§3) — a measured gain refused by a named criterion,
   with the margin: a refusal within a hair of its bound is a lead, one by a
   mile is a record. `[main]`.
4. **Audio per-voice deficits** — a voice whose `aud` sits well below the
   file's other voices, named with the instruments it plays
   (`instrument_stamps`) and their effect bits. `[main]`.
5. **Census buckets** — `--census` (onset), `--hold-census`,
   `--naming-census`, grouped by cause byte/kind across the corpus, ranked by
   files reached. Two linked entries: `[subagent]` to confirm one cause,
   `[main]` for the emitter change.
6. **Column outliers** — a file more than a measured spread below the corpus
   median on one column, with its dominant instrument. Lowest tier: the repo
   has six harness defects on record that looked like this.

Within a tier: files reached first (a shared cause is one fix), then gap
size. Never a weighted scalar across tiers.

**Dedupe by annotation.** The tool reads `.claude/tasks/whattask.json` and
`.claude/tasks/runs.jsonl` (read-only). An entry is marked
`already_tracked: <task id>` when a plan task's `source` or `verify` names the
same file and column, and `already_refuted: <run id>` when a `done` run's
evidence names the same cause on the same file. Entries are never dropped for
that; `QUEUE.md` shows the annotation.

**Persistence.** `first_seen`/`last_seen` per id; entries absent since the
last run are listed once under *closed since last run* with the sha.

**Not in scope:** cost, model or lane — `/whattask` derives those.

## 5. Validation, tests, rollout

**Calibration before any decision.** `fidelity.py --audio-calibrate` writes
`docs/AUDIO-CALIBRATION.md` — a regenerated artefact — from five checks:

1. **Identity.** Same WAV both sides → `aud` 1.00, `loud` ratio 1.00.
2. **Inaudible shift.** One side delayed by 0–48 rasterlines and by up to one
   frame; the score must move under 1 pp. That movement **is the noise floor**
   for §2 criterion 1 and §3 veto 1 — measured, never typed.
3. **A verdict that says "inaudible".** ACE_II's approval note records the
   vibrato-depth change (v0.5.368 → v0.5.369) as not audible to the listener.
   Both renders from `git archive`, scored against each other: a lower bound
   on §2 criterion 2's threshold, from a human's own word.
4. **Known-bad builds from history.** Las Vegas converting to silence and
   Samantha Fox at 3× speed (both pre-v0.5.402), Human Race on the wrong clock
   (pre-v0.5.330), the v0.5.177 half-speed Last_V8 audition. Each must score
   clearly below its fixed build; any that does not becomes a named blind
   spot in the Dimension description before the column ships.
5. **The four approved tunes** should sit in the corpus's upper half on `aud`.
   If one does not, the doc says which of (metric, approval) to check; it
   does not pick.

**Tests.**
- `python/tests/test_audio.py` — synthetic signals: identity, both-silent
  handling, injected lag recovered, scaled copy gives the exact level ratio,
  missing numpy → `-` plus a header line.
- `python/tests/test_fidelity.py` — the registry/header check covers the two
  Dimensions; `AUDIO` appears in *What this run compared*.
- `python/tests/test_approvals.py` — exact / inherited / stale on fixture
  records; inheritance never creates; criterion 2 always against the human
  sha.
- `python/tests/test_presets.py` — the two vetoes; `search_refusals.json`
  written; no approval-kind entry remains in `FIDELITY_VETOED`.
- `python/tests/test_queue.py` — tiering, cause grouping, stable ids,
  `already_tracked`/`already_refuted`, `first_seen`/`last_seen`.
- **Corpus byte-hash reads MOVED 0 on every tooling commit.** Bytes move only
  in the presets-regeneration commit, reported per file.

**Rollout, one commit each, each measured before the next is built on it.**
1. `audio.py`, `--audio` off by default, calibration artefact. Decides nothing.
2. Report columns; first corpus pass; `FIDELITY.md` gains `aud`/`loud`.
3. `build/approvals.json`; `abpage` three states. Read-only over approvals.
4. `presets.py`: computed approval check, two vetoes, refusals file. Search
   result diffed against shipped presets before adoption (the v0.5.413 rule).
   ACE_II's two withheld gains resolve here.
5. `--queue`, `docs/QUEUE.md`; `/whattask` adds it as a source.
6. `drift` acceptance term — after the drift-vs-`--pace` agreement task.

**Docs in the same commits:** README §Fidelity/§Listening/§presets; CLAUDE.md
bullets for approval inheritance, the two vetoes and the queue's dedupe;
H2G-CONVERSION-METHOD.md §7 entries for the metric and its calibration.

## Files touched (for the plan's `touches`)

New: `python/audio.py`, `python/tests/test_audio.py`,
`python/tests/test_approvals.py`, `python/tests/test_queue.py`,
`docs/AUDIO-CALIBRATION.md`, `docs/QUEUE.md`, `build/audio/`,
`build/approvals.json`, `build/search_refusals.json`, `build/queue.json`.

Modified: `python/fidelity.py`, `python/presets.py`, `python/abpage.py`,
`python/listen.py` (renderer reuse only), `python/tests/test_fidelity.py`,
`python/tests/test_presets.py`, `python/tests/test_abpage.py`, `README.md`,
`CLAUDE.md`, `H2G-CONVERSION-METHOD.md`, and — in the regeneration commit
only — `presets.json`, `docs/FIDELITY.md`, `build/fidelity.json`.

Untouched: everything under `python/h2g/`, `Commando.sng`, `approved.json`.
