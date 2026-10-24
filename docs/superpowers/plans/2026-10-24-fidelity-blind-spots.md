# Fidelity Blind Spots Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Status:** DRAFT for review (Fable pass requested by the user, 2026-10-24). No code written.

**Goal:** Find where the original SID and our packed conversion differ in ways
no existing `fidelity.py` column can see, build the smallest set of new
measurements that see them, prove each one can fail, and turn what they find
into queued, mechanism-level converter fixes.

**Architecture:** Nothing here replaces the 37-column report. The work is
(1) a read-only *residual* triage over `build/fidelity.json` that ranks songs
by sound deficit the register columns do not explain, (2) a handful of new
`Dimension`s, each aimed at one documented blind spot and each validated
against a known-bad case before it is trusted, and (3) feeding their misses
into `fidelity_queue.py` as census buckets so they become `/whattask` work.

**Tech Stack:** Python 3.10+ stdlib + numpy (already used by `sound.py`),
`siddump-rt`, `sidplayfp` 2.15.2 (`-u<n>` voice mute — verified in `--help`),
VICE `vsid` via `vicetrace.py`, `gt2reloc`. pytest dev-only.

**Spec:** this file's §Evidence, plus the report's own blindness account
(`docs/FIDELITY.md` § *What this run compared* / *What this does not say*)
and the earlier design note `docs/FIDELITY-TOOL-IMPROVEMENTS.md` (v0.5.72),
whose §5 `--all-subtunes` and §8 items are still unbuilt.

## Evidence (read-only, taken 2026-10-24 from `build/fidelity.json`, v0.5.595 `ad45412-dirty`, `-t 180 --sound`)

All figures are **historical** — they carry that run's version and must be
re-taken before any task below quotes them.

1. **The existing column set is broad; its holes are self-documented.**
   `FIDELITY.md` lists, as *registers/quantities no dimension reads*: the
   `$D418` volume nibble; tempo/row length (only `--pace`, not a column);
   anything outside one subtune / the window; note length above `-S3`; and
   per-column blindnesses: `adsr` masks the release nibble under
   `cut_release` (every preset file) and cannot see an envelope that is right
   but late; `wave` ignores sync/ring/test bits; `band` ignores resonance and
   routing; `pul` is a count, not a value comparison.
2. **Residual: sound deficit with clean registers.** `mean(wave, adsr, gate,
   melody) - aud`, top of the corpus:
   Kings_of_the_Beach_ingame 0.28 (aud 0.66, -S3), Confuzion 0.17
   (aud 0.80, -S1), Kings_of_the_Beach_intro 0.15 (aud 0.85, -S5),
   Mr_Meaner, Chicken_Song 0.08. The rest of the corpus forms a flat 0.05-0.07
   band.
3. **Level mismatches no column explains:** `loud_ratio` Mr_Meaner 1.71,
   Off_the_Cuff 1.47 (both -S5; ours louder), Chicken_Song 0.83.
   (BMX_Kidz 0.32 is a **held DIGI file** — `hold.ON_HOLD` — and is out of
   scope for every task below.)
4. **Corpus-wide offset, unconfirmed:** median `aud` is 0.923, while
   `docs/SOUND-CALIBRATION.md`'s closeness floor (two renders a listener
   called the same) is 0.970. That would mean almost no song reaches
   "sounds the same" — **but the floor is scored over the first 60 s
   (`CHECK_WINDOW_S`) and `aud` over 180 s**, so the two may not be
   comparable. Task 1 settles this before anything is built on it.
5. **A doc claim to re-check:** `fidelity.py:6192` says of the volume nibble
   "nothing the converter emits can move it". GoatTracker's `readme.txt:1296`
   documents a `DXY` master-volume command, and `readme.txt:689` says the
   volume defaults to `$F`. A Hubbard player that sets a lower volume would
   then be a fixable level defect, not an unmeasurable one.
6. **Plumbing that already exists:** `FilterState.volume_events` and
   `ctrl_events` are parsed but `volume` is compared by nothing;
   `listen.render_sidplayfp(..., mute=())` already supports voice muting;
   `fidelity_queue.voice_deficits` (tier 4) is written against an `aud_voices`
   row key that no `fidelity.py` code writes yet.

## Global Constraints

- Every new comparison goes through `register_timeline()` (sparse events mean *held*) and through `resolve_subtune`, never subtune 0.
- Every new number is a `Dimension(key, column, reads, kind, of, source)` in `fidelity.DIMENSIONS`, with its blindness written in `of` — a column without its blindness stated does not land.
- `tests/test_preset_passthrough.py`, the Commando byte-exact fixture and the full suite stay green; no converter output changes in Phases 1-2 (corpus byte-hash identical, reported as converted/refused/compared/moved).
- Held DIGI files (`hold.ON_HOLD`) are measured with everything else but no task targets one.
- No PR touches `SURVEY.md`, `presets.json`, `FIDELITY.md`, `QUEUE.md`; `master` regenerates once after merges (`[main]`).
- New `fidelity.py` flags that the current artefact must carry get added to `.claude/hooks/flag_guard.py` in the same task that adopts them for the refresh.
- `--jobs` sized to memory; 16 for a full refresh.
- Work from worktrees off pushed `master`; the user's uncommitted edits in `patterns.py`, `wavetable.py` and the tests are not touched by this plan.

## Review Focus

1. **A new column that reads 100% because it is blind** (e.g. `vol` on a corpus where both sides hold `$F`): every Dimension's test must include a known-bad case that scores low, and the report must print how many files had a population at all.
2. **Multispeed (-S4/-S5) rows:** siddump samples once per frame, so a per-frame column under-reads them. Each new column states whether it is valid above `-S3`, and its test includes one multiplier-5 file (Kings_of_the_Beach_intro).
3. **Startup lag:** a per-frame comparison without `startup_lag` alignment charges every frame for the onset. Each per-frame column uses the same lag as `wave`; test with a synthetic 1-frame shift that must NOT move the score.
4. **Per-voice audio on a voice the conversion moved:** our orderlist voice may not be the original's voice (attack-lateness swaps exist). `aud_voices` must pair voices by register agreement, not by index, or say it didn't.
5. **Render cost:** per-voice renders triple sidplayfp time; the cache key must include the mute set or a solo render will be served as a full mix.

---

## Phase 0 — Settle the baseline (read-only)

### Task 1: Is the 0.92 corpus `aud` a defect or a measurement artefact? `[subagent]` Opus 5.5 (falsification)

**Files:**
- Create: `python/tools/aud_ceiling_probe.py` (scratch-grade, kept for reproducibility)
- Output: `build/aud_ceiling.md` (gitignored)

**Interfaces:**
- Consumes: `sound.compare_sids(orig, ours, seconds, sub_orig, sub_ours, prior_s, cache, renderer, window_s)`, `sound_calibrate` check 2/3 machinery.
- Produces: one verdict among `comparable-defect | window-artefact | renderer-floor`, with numbers.

- [ ] **Step 1:** For 6 songs spanning `aud` 0.80-0.97 (pick from `build/fidelity.json`, none held), compute `aud` at `window_s=60` and `window_s=180`, and original-vs-second-render-of-original at both windows.
- [ ] **Step 2:** If original-vs-original at 180 s is itself near 0.92, the verdict is `renderer-floor` and the closeness floor must be re-measured at 180 s before any `aud` threshold is used. If not, and ours-vs-original is ≥0.03 below it at the same window, `comparable-defect`.
- [ ] **Step 3:** Assert the probe's own success: every song produced both renders (no silent `-` treated as 0).
- [ ] **Step 4:** Write the verdict and the table to `build/aud_ceiling.md`. No commit beyond the probe script.

Gate: Tasks 2+ that threshold on `aud` read this verdict first.

### Task 2: Residual triage report `[subagent]` Sonnet 5.5

**Files:**
- Create: `python/residual.py`
- Test: `python/tests/test_residual.py`

**Interfaces:**
- Produces: `residuals(rows: list[dict], floor: float) -> list[dict]` — one dict per song with keys `file, aud, loud, loud_ratio, reg_mean, residual, multiplier, held: bool, explained_by: list[str]`; CLI `python residual.py --from-json ../build/fidelity.json -o ../build/residual.md`.

- [ ] **Step 1: failing tests**
  - `test_residual_ranks_by_unexplained_gap`: two synthetic rows, aud 0.66/reg 0.94 and aud 0.90/reg 0.91 → first ranked first, `residual == pytest.approx(0.28)`.
  - `test_residual_marks_held`: a row for `BMX_Kidz.sid` → `held is True`, excluded from the ranked list, listed separately.
  - `test_residual_refuses_empty`: rows with no `aud` → raises `ValueError` (a "0 residuals" result must not look like a pass).
  - `test_loud_ratio_flag`: loud_ratio 1.71 → `"level"` in `explained_by` is False and the row is in the level list.
- [ ] **Step 2:** run, expect FAIL (module missing).
- [ ] **Step 3:** implement; `reg_mean` over `wave, adsr, gate, melody` present in the row; held set from `hold.ON_HOLD`.
- [ ] **Step 4:** run tests, PASS; run on the real JSON, check the top 3 match Evidence §2 (re-taken).
- [ ] **Step 5:** commit (bump version first).

---

## Phase 1 — Cheap columns from data already parsed

### Task 3: `vol` — master volume agreement `[subagent]` Sonnet 5.5

**Files:**
- Modify: `python/fidelity.py` (new `volume_compare(orig: FilterState, ours: FilterState, nframes: int, lag: int) -> dict`, a `Dimension("vol", "vol", ("$D418",), "fraction", ...)` entry, row keys `vol`, `orig_volume_values`, `our_volume_values`)
- Modify: the `$D418` line in the *Registers no dimension reads* text at `fidelity.py:6192` — rewrite from what Task 3's measurement shows, quoting what it retracts.
- Test: `python/tests/test_fidelity.py`

- [ ] **Step 1: failing tests**
  - `test_vol_identical_is_one`: both sides `volume_events=[(0,15)]` → `vol == 1.0`.
  - `test_vol_known_bad`: orig `[(0,10)]`, ours `[(0,15)]` over 500 frames → `vol == 0.0`, `orig_volume_values == {10}`.
  - `test_vol_lag_invariant`: same timeline shifted by `lag=1` → unchanged.
  - `test_vol_population_reported`: both sides constant `$F` → `vol == 1.0` AND row `vol_varies is False`, so the report can count files where the column could have failed.
- [ ] **Step 2-4:** fail → implement → pass.
- [ ] **Step 5:** corpus run without `--sound` (registers only, `--jobs 16`) into a scratch JSON; record how many files have `orig_volume_values != {15}`. If Mr_Meaner/Off_the_Cuff are among them, open a queue item `vol-level-<file>`; if none, say so in the commit message — the loud_ratio lead then points at filter/resonance (Task 4) instead.
- [ ] **Step 6:** commit.

### Task 4: `res` + `route` — resonance and per-voice filter routing `[subagent]` Sonnet 5.5

**Files:**
- Modify: `python/fidelity.py` (`filter_ctrl_compare(orig, ours, nframes, lag) -> dict` returning `res` (frames with equal `$D417>>4` over frames either side filters) and `route` (per-voice agreement of bits 0-2)); two `Dimension`s.
- Test: `python/tests/test_fidelity.py`

- [ ] **Step 1: failing tests** — `test_res_known_bad` (res $F vs $0 while filtering → 0.0), `test_route_voice_swap` (orig routes v1, ours v2 → `route` 0.0 though `filt` reads 1.00x), `test_res_ignores_unfiltered_frames` (different resonance while no voice routed → not charged).
- [ ] **Step 2-4:** fail → implement → pass.
- [ ] **Step 5:** commit.

### Task 5: `ctrl` — sync / ring / test bits `[subagent]` Sonnet 5.5

**Files:**
- Modify: `python/fidelity.py` (`ctrl_bits_compare(orig: list[Voice], ours: list[Voice], nframes, lag) -> dict` with one-sided ratios `sync`, `ring` like `noise`, and `test_frames` excluding the documented `$09` firstwave frame per note); `Dimension`s.
- Test: `python/tests/test_fidelity.py`

- [ ] **Step 1: failing tests** — `test_ring_lost` (orig `$15` frames, ours `$11` → ring ratio `0/N`), `test_firstwave_test_bit_not_charged` (ours `$09` on note opening only → `test_frames` equal), `test_wave_unaffected` (assert `wave` stays 1.0 on the ring-lost case — pins that this column sees what `wave` cannot).
- [ ] **Step 2-4:** fail → implement → pass.
- [ ] **Step 5:** commit.

---

## Phase 2 — Columns that need new data

### Task 6: `aud_voices` — per-voice rendered sound `[subagent]` Sonnet 5.5

Fills the shape `fidelity_queue.voice_deficits` already expects (read its docstring for the row shape before starting).

**Files:**
- Modify: `python/sound.py` (`compare_sids(..., mute: tuple = ())` passed through `render_cached`; `content_key(path, delay, mute)` includes the mute set)
- Modify: `python/fidelity.py` (behind a new `--sound-voices` flag: three solo renders per side, row key `aud_voices: list[float | None]`, voice pairing by best `wave` agreement with `aud_voice_pairing` recorded)
- Test: `python/tests/test_sound.py`, `python/tests/test_fidelity.py`, `python/tests/test_queue.py`

- [ ] **Step 1: failing tests**
  - `test_cache_key_differs_by_mute`: same sid, mute `()` vs `(2,3)` → different keys.
  - `test_solo_render_is_not_mix`: fake renderer records argv; solo voice 1 → argv contains `-u2 -u3`.
  - `test_voice_deficits_fires`: row with `aud_voices=[0.95, 0.60, 0.94]` → tier 4 entry naming voice 2.
- [ ] **Step 2-4:** fail → implement → pass.
- [ ] **Step 5:** run on the Task 2 top 5 (none held); record which voice carries each residual.
- [ ] **Step 6:** commit. Adoption into the routine refresh is a `[main]` decision after its cost is measured (3x renders), not part of this task.

### Task 7: `aud_timeline` — where in the song the sides part `[subagent]` Sonnet 5.5

**Files:**
- Modify: `python/sound.py` (`compare_features(...)` additionally returns `per_second: list[float]`)
- Modify: `python/fidelity.py` (row keys `aud_timeline` (rounded to 2 dp) and `aud_first_dip_s`: first second below the Task 1 floor for 3 consecutive seconds)
- Modify: `python/songview.py` or `abpage.py` — print the dip seconds next to the song's patterns/rows at that time (choose `songview.py` if it can map seconds to orderlist position; otherwise abpage only)
- Test: `python/tests/test_sound.py`

- [ ] **Step 1: failing tests** — `test_per_second_mean_matches_aud` (mean of `per_second` weighted by sounding frames == `aud` within 1e-6), `test_first_dip_located` (synthetic features identical except seconds 40-45 → `aud_first_dip_s == 40`).
- [ ] **Step 2-4:** fail → implement → pass.
- [ ] **Step 5:** commit.

### Task 8: `env` — simulated envelope level `[subagent]` Opus 5.5 (mechanism modelling)

The column the `cut_release` mask and "right but late" blindness call for: compare what the envelope *does*, not what the registers say.

**Files:**
- Create: `python/envsim.py` — `envelope_levels(gate: list[int], adsr: list[int], calls_per_frame: int = 1) -> list[int]` (0-255 per frame, SID rate-counter periods and exponential-decay steps from the documented 6581 table; ADSR delay bug explicitly NOT modelled and said so in the docstring)
- Modify: `python/fidelity.py` — `env` Dimension: per-voice mean absolute level difference / 255, lag-aligned, frames where both are 0 excluded
- Test: `python/tests/test_envsim.py`, `python/tests/test_fidelity.py`

- [ ] **Step 1: failing tests**
  - `test_attack_zero_reaches_peak_in_one_frame` (A=0 → 255 within frame 1).
  - `test_release_masked_case_seen`: orig SR `$A9`, ours `$A0` (what `cut_release` writes), gate off at frame 100 → `adsr` (existing) reads 1.0 on the masked comparison while `env` < 0.9. This test is the column's reason to exist.
  - `test_late_envelope_seen`: identical registers, ours gate rises 3 frames late → `env` < 1.0.
- [ ] **Step 2: validation against real hardware state:** with `vicetrace.py`, trace `$D41C` (voice 3 envelope output) on Commando for 10 s; `envelope_levels` for voice 3 must track it within ±8 on 95% of frames. If it does not, stop and report — do not tune constants to fit.
- [ ] **Step 3-5:** implement → pass → commit.

### Task 9: `--all-subtunes` sweep `[subagent]` Sonnet 5.5 (build) → `[main]` (run)

**Files:**
- Modify: `python/fidelity.py` — `--all-subtunes`: for each file, every subtune the conversion emits (pair via `matched_subtune` logic), writing `build/fidelity_subtunes.json` and a separate `docs/SUBTUNE-FIDELITY.md`; never touches the main report
- Test: `python/tests/test_fidelity.py`

- [ ] **Step 1: failing tests** — `test_all_subtunes_enumerates` (fake converter with 3 emitted subtunes → 3 rows with `subtune` 0,1,2), `test_all_subtunes_skips_dropped` (a subtune the census marks `sfx`/past-table → recorded as `dropped: <reason>`, not measured, not silently absent).
- [ ] **Step 2-4:** fail → implement → pass; commit.
- [ ] **Step 5 `[main]`:** run sharded (`--jobs 16`, `-t 60` to bound cost; say so in the header). List songs whose non-default subtunes score ≥10 points below their default.

---

## Phase 3 — Turn findings into work

### Task 10: Census buckets for the new columns `[subagent]` Sonnet 5.5

**Files:**
- Modify: `python/fidelity_queue.py` — `column_outliers` learns `vol`, `res`, `route`, `ctrl`, `env`, `aud_voices`, `aud_first_dip_s`; each entry carries `files`, a one-line cause, a `verify` and the tag scheme (`[subagent]`/`[main]`/`[user]`)
- Test: `python/tests/test_queue.py`

- [ ] Steps: failing test per new column (one outlier row → one entry with the right tag) → implement → pass → commit.

### Task 11: Investigate each top finding `[subagent]` per finding, Opus 5.5 for root cause

For each of the top findings from Tasks 2-9 (expected first: Kings_of_the_Beach_ingame, Confuzion, the loud_ratio pair):

- [ ] `--diagnose` + `songview.py` + `vicetrace.py --vice` around `aud_first_dip_s`, on the voice `aud_voices` names.
- [ ] Name the mechanism; **census it across the corpus** (memory: *cross-song mechanism check*) before proposing a fix.
- [ ] Output: a queue/todo entry with mechanism, files sharing it, proposed fix, and the A/B that would prove it. Stop there on refuted — no auto-fix.

### Task 12: Fixes `[subagent]` each, `[main]` to adopt

- [ ] One worktree per mechanism; corpus byte-hash + targeted `--baseline` A/B; fixture byte-exact.
- [ ] `[main]`: merge, version bump, regenerate SURVEY/presets (and FIDELITY/QUEUE with `--json`), full suite.
- [ ] `[user]`: listening verdict via `listen.py` / `abpage.py` on every song whose sound changed.

### Task 13: Documentation and refresh `[main]`

- [ ] `docs/MEASURING.md`: one section per new column (what it reads, what it is blind to, how it was validated).
- [ ] `CLAUDE.md` § Measurement discipline: one headline per durable rule; evidence to `docs/LESSONS.md`.
- [ ] `flag_guard.py`: add any flag adopted into the routine refresh.
- [ ] Regenerate FIDELITY/QUEUE once on `master` after merges.

---

## Order and parallelism

Task 1 → Task 2 (both read-only) gate everything. Tasks 3, 4, 5 touch the
same file (`fidelity.py`) but disjoint functions; run in parallel worktrees
with the optimistic-merge rule (rebase + re-verify on conflict). Tasks 6 and
7 both edit `sound.py` — serialise them. Task 8 is independent. Task 9 is
independent of 3-8. Tasks 10-13 follow.

## Questions for the reviewer

1. Is `mean(wave, adsr, gate, melody)` the right "register says it's fine" baseline for the residual, or should it weight by what each column can hear (e.g. leave `melody` out because it is near 100% everywhere and dilutes the mean)?
2. Is a 6581 envelope model worth its validation cost (Task 8), or does `aud_voices` + `aud_timeline` make it redundant for finding release defects?
3. Should `--all-subtunes` (Task 9) come before the new columns, given that it measures a whole class of output that currently has no coverage at all?
4. Anything in `docs/FIDELITY-TOOL-IMPROVEMENTS.md` § *What not to do* that this plan violates?
