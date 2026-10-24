# Fidelity Blind Spots Implementation Plan — revised (Fable pass)

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Status:** REVISED DRAFT, 2026-10-24, Fable 5.1 review of `2026-10-24-fidelity-blind-spots.md`. No code written. Every figure below is **historical** and carries its source; re-take before a task quotes it.

**Goal:** unchanged — find where the original SID and our packed conversion differ in ways no existing `fidelity.py` column sees, build the smallest set of new measurements that see them, prove each can fail on this corpus, and turn what they find into mechanism-level converter fixes.

---

## Revision notes

Each entry: **draft said** / **what is true or better** / **evidence**. Items marked TODO could not be verified in this pass and must not be quoted as fact.

1. **Held files were used as leads and as a test file.** Draft: only BMX_Kidz is held; Kings_of_the_Beach_intro, Mr_Meaner and Off_the_Cuff are named as residual/level leads (Evidence §2-3, Task 3 Step 5, Task 11) and Kings_of_the_Beach_intro as the multiplier-5 test file (Review Focus 2). / All three are in `hold.FOURTH_VOICE`; CLAUDE.md § On hold: "Start no task whose subject is a held file". Non-held leads re-taken from `build/fidelity.json` (v0.5.595, `ad45412-dirty`): residual Kings_of_the_Beach_ingame 0.277, Confuzion 0.168, Chicken_Song 0.080, Zoolook 0.069, Delta_Mix-E-Load_loader 0.068; `loud_ratio` high Mega_Apocalypse 1.943, Pygmies_Revenge 1.800; low IK_plus 0.702, Battle_of_Britain 0.808, Chicken_Song 0.834. Non-held multiplier>=5 files: Spellbound (-S5), Proteus, Warhawk (-S7), Game_Killer (-S9), Delta_Mix-E-Load_loader, International_Karate, Kentilla (-S10). / `python/hold.py:25-41`; fidelity.json query (this pass).
2. **"The rest of the corpus forms a flat 0.05-0.07 band" is false.** / Over the 89 measured rows the residual `mean(wave,adsr,gate,melody) - aud` has median **-0.024**, quartiles [-0.077, -0.024, +0.026]; only ~10 rows exceed 0.06. Most songs score HIGHER on `aud` than on their register mean. / fidelity.json query (this pass).
3. **"37-column report"** / 34: `len(fidelity.DIMENSIONS) == 34`, and FIDELITY.md's *What this run compared* table has 34 rows. / `python -c "import fidelity;print(len(fidelity.DIMENSIONS))"`; `docs/FIDELITY.md:214-247`.
4. **Evidence §4's window question is already answered, and its inference is a category error.** Draft: the 0.970 closeness floor is scored over 60 s and `aud` over 180 s, "so the two may not be comparable"; "almost no song reaches sounds the same". / `docs/SOUND-CALIBRATION.md:7` already prints the whole-window (180 s) floors beside the 60 s ones: noise `0.0183`, closeness `0.9698`. So they are comparable. But the closeness floor is the LEAST agreement between two of OUR builds a listener called the same (an approval bound: at or above it a build sounds like what was approved); it says nothing about whether an original/conversion pair BELOW it sounds different. And the draft's `renderer-floor` hypothesis (original-vs-original near 0.92) is refuted by the same doc: a second render of the same original agrees with the cached one to within 0.0183 (check 2, 16 repeat renders), i.e. >= 0.98, and that was BEFORE `--delay=0` (v0.5.492) removed the random power-on state. The calibration itself is at v0.5.490 and reads **FAIL** ("nothing downstream may inherit an approval on these numbers"). / `docs/SOUND-CALIBRATION.md:3,7,11-12`; `python/sound_calibrate.py:135` (`CHECK_WINDOW_S = 60`); `python/listen.py:74` (`SIDPLAYFP_POWER_ON_DELAY = 0`). **Consequence:** Task 1 is replaced by a `[main]` re-run of the existing `sound_calibrate.py` at HEAD, not a new probe script, and `aud` thresholds in this plan are relative (movement against the 0.0183 noise floor), never absolute.
5. **Evidence §5's line numbers.** Draft: `readme.txt:1296` documents DXY. / `readme.txt:677` is the definition ("Command DXY: Set mastervolume to Y, if X is $0"); 1296 is the VOLUME CHANGE SUPPORT note that mentions it; 689 ("default is the maximum ($F)") is correct. The packed player has it: `gcommon.h:17 CMD_SETMASTERVOL 13`, `player.s:62 SETMASTERVOL = $0d`, `gplay.c:478,689`. The converter emits nothing to `$D418`'s low nibble today (grep of `python/h2g/` for volume/D418 hits only `detect.py` comments), so `fidelity.py:6192` is right about the current emitters and wrong about what GoatTracker can do. / files cited.
6. **NEW, decisive: the originals' volume nibble is NOT `$F` on 20 of 95 files**, so a `vol` column has a population and a predicted effect. Census run this pass (read-only, `siddump-rt`, 60 s at `resolve_subtune(...,"auto")`, HEAD 5346077-dirty, script `fable_blindspot_census.py` in the session scratchpad): constant `$8` for the whole window on **Mega_Apocalypse, Pygmies_Revenge** (non-held) and on Kings_of_the_Beach_intro, Mr_Meaner, Off_the_Cuff, One_on_One, Powerplay, Rock_Tells_the_Tale (held); `$0` for all 3000 frames on After_8 and Rikky (held; the digi engine drives `$D418` within the frame and siddump keeps end-of-frame state, so this is the sample engine, not a level); `$A` on BMX_Kidz, Ricochet, Skate_or_Die_intro (held); one- or two-frame `$0` at init on Chain_Reaction, Confuzion, Master_of_Magic, Thing_on_a_Spring, Zoolook, and 413 frames of `$0` on Up_up_and_Away (status *not converted*). Mega_Apocalypse's and Pygmies_Revenge's `loud_ratio` (1.94, 1.80) sit at the 15/8 = 1.875 a constant `$8` predicts. / scratchpad census JSON; fidelity.json. **Consequence:** `vol` moves to the front of the plan and arrives with its known-bad pair and a fix path (CMD_SETMASTERVOL).
7. **Resonance and routing populations, measured (same census):** 30 originals set a non-zero resonance nibble inside 60 s — 24 of them only `$F` while filtering, six with other values (Food_Feud [0,12,15], Go_Go_Dash [0,5], Lion_Heart [0,3], Radio_ACE [0,4], Sun_Never_Shines [0,8,15], Task_Force [0,10,15]; Task_Force is *not converted*). 28 originals change the route mask; only Sun_Never_Shines and Task_Force route more than one voice at a time. The converter carries a resonance field per filter record (`goatwriter/filters.py:57`), so `res` can fail on our side. / census; `filters.py:57`.
8. **Sync/ring/test populations, measured (same census, any voice, original side):** ring bit on 44 files, sync on 26, test on 14 (Bangkok_Knights 3920 test frames, Nineteen 1955, IK_plus 1713, Auf_Wiedersehen_Monty 1136). `wave` compares `x & 0xF0` (`fidelity.py:1680`), so bits 1-3 are invisible to it — confirmed in code; FIDELITY.md itself only says "ignores the gate bit" (`:271`). `H2G-CONVERSION-METHOD.md:328` says sync/ring are carried in the wavetable, so `sync`/`ring` may honestly read 100% — the test bit is where the two sides differ by construction (ours writes `$09` on every note's first frame). The column must report both directions (frames the original tests and we do not, and vice versa, minus the documented firstwave frame). / census; files cited.
9. **Evidence §6 verified, and understated.** `FilterState.volume_events`/`ctrl_events` (`fidelity.py:291-293`), `listen.render_sidplayfp(..., mute=())` (`listen.py:148-149`), `fidelity_queue.voice_deficits` reading an unwritten `aud_voices` (`fidelity_queue.py:31-36,145-170`) all check out. Not in the draft: `listen.py --voices` ALREADY renders six solo WAVs per song for `abpage.py`'s voice selector (`listen.py:821, 1070-1086`), so Task 6 needs only the scoring and the cache key; `fidelity_queue.TAG[4]` is `[main]`, not `[subagent]`; and **`fidelity_queue.py` has no hold awareness** — `docs/QUEUE.md` names Mr_Meaner 4 times, BMX_Kidz 14, Rikky 6, After_8 5 — so the queue already proposes work the hold forbids. / files cited; `grep -c` on QUEUE.md.
10. **`--vice` already parses resonance and the whole `$D418` byte** (`vicetrace.Sample.res`, `.modevol`, `vicetrace.py:84-85`; used at `fidelity.py:5365-5366`), so a per-call reading of `vol`/`res` is cheap there. **It does NOT parse `$D41C` (ENV3)**: the VICE `-sounddev dump` lines are FREQ/PULSE/CTRL/ADSR/FILTER only (`vicetrace.py:63-68`). Task 8 Step 2 as written cannot run. TODO: an envelope oracle (reSID's `envelope.cpp` driven directly, or a dedicated probe PSID rendered by sidplayfp) — unverified which is feasible.
11. **Task 8 duplicates what exists.** `fidelity.py` already transcribes reSID's envelope constants — `SID_RELEASE_MS`/`_release_frames` (`:1536-1543`), `SID_RATE_PERIOD`, `SID_DECAY_UNITS`, `SID_DELAY_BUG_CYCLES`, `_decay_to_zero_frames` (`:1554-1577`) — and `envelope_zero_frame` (`:2828`) models silence per frame. And the draft's "reason to exist" test (release masked by `cut_release`) is already a column: `tail` (`release_tail_agreement`, `:3556-3647`) reads the release nibble in force at each gate-off per instrument, unmasked; `adsr_exact` carries the unmasked frame figure. At v0.5.595 `tail` < 0.9 on Ninja 0.64, Phantoms_of_the_Asteroid 0.70, Gerry_the_Germ 0.88, Rasputin 0.88. What remains unseen is "right but late" and the level trajectory inside a note. / files cited; fidelity.json.
12. **Kings_of_the_Beach_ingame's residual is not "clean registers".** Its window is **8 s** (`original_ended` shortens it, `fidelity.py:2277`; `window_seconds: 8`, the shortest in the corpus with Geoff_Capes at 17 s), subtune 4, 84 notes; `gate` 0.78 with `gate_ours_ringing` = 84 = `our_attacks` (every one of our notes rings while the original is silent) and `wave_tail_frames` 117 of 1065. The mechanism is already described at `fidelity.py:1689-1702`: the original ends a note by writing waveform `$00` (instant silence), ours latches the waveform through its release. `rest_wave_silence` (`convert.py:261`) exists and is off in its preset. This is a Task 11 lead with a candidate mechanism, not a case for a new column — and an 8 s window is the "window did not contain the material" hazard (RULES.md:151-154). / fidelity.json; files cited.
13. **Task 10 is largely vacuous as written.** `column_outliers` iterates every `fraction` Dimension in `F.DIMENSIONS` (`fidelity_queue.py:202-237`), so `vol`, `res`, `route`, `ctrl`(fractions) get outlier entries with NO queue change — a test "one outlier row -> one entry" would pass before the task starts. What the queue lacks is hold-awareness (note 9), entries for the non-Dimension keys (`aud_voices`, `aud_first_dip_s`), and a cause text per column. Rewritten below.
14. **Task 3 Step 5 would be refused by the hook.** `.claude/hooks/flag_guard.py:128-134` blocks `fidelity.py` with `--json`/`-o` and no `--sound` whenever the artefact has `aud`. A scratch register-only run needs `H2G_ALLOW_MISSING_FLAG=1` set deliberately, and the plan says so. The original-side half of that step is already done (note 6).
15. **FIDELITY-TOOL-IMPROVEMENTS "§8 items still unbuilt" is partly stale.** Its gate-length item is built (`hold` since v0.5.196, `gate`); its RSID-render blocker is moot (`listen.py:56` renders with sidplayfp 2.15.2, not SID2WAV); `--pair` is still undocumented; the SIDM2 stages still exist and are run by nobody (`fidelity.py:6968-7030`: `sidm2_register` = frame-exact register accuracy with an Overall/Per-Frame/Filter figure; `sidm2_audio` = onset jitter). Neither duplicates a column proposed here, but TODO: whether SIDM2's "Filter Accuracy" reads `$D417`/`$D418` was not checked. The doc's last commit is v0.5.359 (54b4843), not v0.5.72; its sections carry their own stamps. §5's `--all-subtunes` is indeed unbuilt, but `--diagnose` already computes `subtune_matrix` (melody for every original x ours pair, `MATRIX_CAP = 24`, `fidelity.py:10834,10930`) and `SUBTUNE_COUNTERPART`/`SUBTUNE_REMAP` (`:7521,10919`) hold the known pairings — Task 9 builds on them. Population: 32 of 89 measured files carry >1 subtune in `subtune_shas`, 158 extra subtunes (Las_Vegas_Video_Poker 16, Samantha_Fox 14, Auf_Wiedersehen_Monty 13, Delta 13, Tarzan 11, Dragons_Lair_Part_II 10, Flash_Gordon 9, Warhawk 9).
16. **"What not to do" (FIDELITY-TOOL-IMPROVEMENTS:386-403): no violation found.** Every proposed comparison goes through `register_timeline`/`resolve_subtune`, no shared workdir, no `seconds x multiplier` tracing. Watch Task 9: a subtune row must never score against a stub (`:397-399`).
17. **Task 7's validation does not need synthetic data.** `sound_calibrate.KNOWN_BAD` (`sound_calibrate.py:345-347`) holds W_A_R 0.5.399 -> 0.5.400, a ~40 s event inside 20-60 s of the render (`sound.py:393-395`), and Action_Biker 0.5.371 -> 0.5.372 (a different piece of music from the first bar). `aud_first_dip_s` must land in 20-60 s on the first and at ~0 on the second. The "floor" for a dip is per song (below the song's own per-second median by more than the 0.0183 noise floor), not the closeness floor.
18. **`loud` already reads the volume nibble through the render.** Its Dimension text says so (`fidelity.py:6918-6924`), and `loud_ratio` is the level ratio. `vol` is therefore the REGISTER-side twin of `loud_ratio`: a `vol` finding predicts a `loud_ratio`, and the two must be reported together (Mega_Apocalypse/Pygmies_Revenge are the first pair). Evidence §1's "volume nibble read by nothing" should say "by no register column".
19. **Emitting DXY meets a hard invariant.** CLAUDE.md: "Row 0's command column belongs to the subtune's clock"; CMD_SETMASTERVOL (13) is in neither `patterns.ONE_SHOT_COMMANDS` (`patterns.py:86`) nor `TEMPO_OVERWRITABLE` (`:106`). A row-0 `D0Y` would cost the subtune its `CMD_SETTEMPO`. The fix design (row 1 on one voice, or the instrument-63 startup-row mechanism, or declaring it in both sets) is Task 12's first question, not something the measurement task decides. And on a digi file the `$0` IS the sample engine — a DXY `$0` there would silence the tune; the hold protects against it and the column's `of` must say siddump reads end-of-frame state.
20. **Global constraint "every new number is a `Dimension`" cannot hold for `aud_voices` (a list) or `aud_first_dip_s` (seconds).** Dimension kinds are `fraction | ratio | count` (`fidelity.py:6207`). Those two are row keys with their blindness stated in `docs/MEASURING.md` and in the report's notes; adding a `seconds` kind is a separate decision. `test_every_printed_column_has_a_dimension_declaring_its_registers` (`tests/test_fidelity.py:2004`) only governs printed columns.
21. **Residual baseline (Q1):** `melody` median is 0.9996 over the corpus; in a four-way mean it contributes a constant 0.25 and dilutes the spread. Drop it. Use `wave`, `adsr`, `gate`; keep `adsr_exact` beside, not in, the mean (it differs by `cut_release` design on every preset file: Confuzion 0.86 vs 0.24).
22. **Review Focus 2's test file** changes from Kings_of_the_Beach_intro (held) to Spellbound (-S5) or Delta_Mix-E-Load_loader (-S10).
23. Unverified in this pass, left as TODO where quoted: sidplayfp per-voice render cost ("3x"); whether `songview.py` can map seconds to orderlist position (grep found no seconds handling, `songview.py:607-623`; treat as *cannot* until shown); whether the `--vice` dump's `RES:` field is the whole `$D417` byte or the nibble.

---

## Evidence (read-only; `build/fidelity.json` v0.5.595 `ad45412-dirty`, `-t 180 --sound`; census 2026-10-24 at HEAD 5346077-dirty, 60 s, original side)

All figures are **historical** and must be re-taken before any task quotes them.

1. **The column set is broad (34 columns); its holes are self-documented.** `FIDELITY.md` § *What this run compared* lists, as quantities no column reads: the `$D418` volume nibble (no REGISTER column; `loud`/`loud_ratio` read it through the render); tempo/row length (`--pace` only); anything outside one subtune / the window; note length above `-S3`. Per-column: `adsr` masks the release nibble under `cut_release` (all 89 measured rows; `tail` and `adsr_exact` read it unmasked) and cannot see an envelope right but late; `wave` compares bits 4-7 only (sync/ring/test/gate invisible; code `fidelity.py:1680`); `band` ignores resonance and which voice is routed; `pul` is a count.
2. **Residual: sound deficit beside agreeing registers**, `mean(wave, adsr, gate) - aud`, non-held only, re-derived: Kings_of_the_Beach_ingame (aud 0.66, **8 s window**, gate 0.78 — see note 12), Confuzion (aud 0.80, -S1, 307 s window), Chicken_Song (aud 0.89, coverage 0.10 of a never-ending tune), Zoolook, Delta_Mix-E-Load_loader. Median residual is negative; the top of the distribution is the subject, not a "band".
3. **Level mismatches**, `loud_ratio`, non-held: Mega_Apocalypse 1.94 and Pygmies_Revenge 1.80 (both originals hold `$D418` volume `$8`: PREDICTED by the census, 15/8 = 1.875); IK_plus 0.70 (filter-heavy: 8997 filtered frames, `band` 0.835, volume `$F` both sides — a resonance/routing lead); Battle_of_Britain 0.81; Chicken_Song 0.83 (volume `$F`; unexplained). Held files with the same volume-nibble signature are listed in note 6 and are out of scope.
4. **Populations the new columns can fail on (census):** volume != `$F`: 20 originals (2 non-held constant, 5 non-held one-frame init blips); resonance != 0: 30 (6 with a value other than `$F`); routing changes: 28; ring 44, sync 26, test 14.
5. **GoatTracker can set master volume:** `DXY` (`readme.txt:677`), `CMD_SETMASTERVOL 13` (`gcommon.h:17`), default `$F` (`readme.txt:689`). The converter emits none. `fidelity.py:6189-6192` must be rewritten by the task that measures it, quoting what it retracts.
6. **Plumbing that exists:** `FilterState.volume_events`/`ctrl_events` parsed, uncompared; `vicetrace.Sample.res`/`.modevol` parsed; `listen.py --voices` renders solo WAVs; `render_sidplayfp(mute=...)`; `fidelity_queue.voice_deficits` awaits `aud_voices`; `subtune_matrix` + `SUBTUNE_COUNTERPART`; `sound_calibrate.KNOWN_BAD` pairs with known event times; `rest_wave_silence` option.

## Global Constraints

- Every new comparison goes through `register_timeline()` (sparse events mean *held*) and `resolve_subtune`/`resolve_pair`, never subtune 0, and is lag-aligned with `_aligned(..., startup_lag)` exactly as `wave` is.
- Every new printed column is a `Dimension(key, column, reads, kind, of, source)` in `fidelity.DIMENSIONS` with its blindness in `of`, including: "siddump keeps end-of-frame state, so a value written and overwritten inside a frame is invisible; above `-S3` read `--vice`". Non-column row keys (`aud_voices`, `aud_first_dip_s`) state their blindness in `docs/MEASURING.md` and the report notes.
- A new column lands with (a) a known-bad case from THIS corpus that scores low, (b) a report line saying on how many files the column could have failed (its population), (c) a test that the neighbouring blind column stays unmoved on the known-bad case.
- The full suite, `tests/test_preset_passthrough.py` and the Commando byte-exact fixture stay green; Phases 0-2 change no converter output (corpus byte-hash: converted/refused/compared/moved, named).
- Held files (`hold.ON_HOLD`) are measured with everything else; **no task, lead, test fixture or queue entry targets one**. A census row about a held file is reported under its own heading.
- No PR touches `SURVEY.md`, `presets.json`, `FIDELITY.md`, `QUEUE.md`; `master` regenerates once after merges (`[main]`).
- Flags the routine refresh adopts are added to `.claude/hooks/flag_guard.py` in the same task; a scratch register-only run sets `H2G_ALLOW_MISSING_FLAG=1` on purpose and says so.
- `--jobs` sized to memory (16 for a refresh). Worktrees off pushed `master`; the user's uncommitted edits (`patterns.py`, `wavetable.py`, tests) are not touched.

## Review Focus

1. **A column reading 100% because it is blind.** Every Dimension's tests include a corpus-derived known-bad case and the population count; the report prints "could have failed on N files".
2. **Multispeed rows:** siddump samples once per frame. Each new register column says in `of` whether it is valid above `-S3`; its test includes Spellbound (-S5) or Delta_Mix-E-Load_loader (-S10), never a held file.
3. **Startup lag:** per-frame columns use the row's `startup_lag`; a synthetic 1-frame shift must not move the score.
4. **Per-voice audio on a voice the conversion moved:** pair voices by `wave_voices` agreement, not by index, and record the pairing.
5. **Render cache:** the key must include the mute set; a test asserts a solo key differs from the mix key.
6. **Window size:** Kings_of_the_Beach_ingame (8 s) and Geoff_Capes (17 s) are the smallest windows in the corpus; a residual report prints `window_seconds` and flags < 60 s before anyone reads the number.

---

## Phase 0 — Triage (read-only)

### Task A: Residual triage report `[subagent]` Sonnet 5.5

**Files:** create `python/residual.py`, `python/tests/test_residual.py`.

**Interface:** `residuals(rows: list[dict]) -> list[dict]` — per song: `file, aud, loud, loud_ratio, reg_mean (wave, adsr, gate), residual, multiplier, window_seconds, held: bool, hold_reason, explained_by: list[str]`; CLI `python residual.py --from-json ../build/fidelity.json -o ../build/residual.md`. Held rows go in their own table at the bottom. `explained_by` is filled by later tasks (`"vol"`, `"res"`, ...); for now it is `["short-window"]` when `window_seconds < 60` and `["coverage"]` when `window_coverage < 0.2`.

- [ ] **Step 1: failing tests** — `test_ranks_by_residual` (two synthetic rows), `test_held_rows_are_separated` (`Mr_Meaner.sid` -> `held is True`, absent from the ranked list, present in the held list with `hold.ON_HOLD`'s reason), `test_refuses_rows_without_aud` (`ValueError`), `test_short_window_is_flagged` (a row with `window_seconds: 8` -> `"short-window"`), `test_melody_is_not_in_reg_mean`.
- [ ] **Step 2-3:** fail -> implement.
- [ ] **Step 4:** run on the real JSON; the top three non-held must match Evidence §2 re-taken; print the median residual in the header so nobody reads the top as a band again.
- [ ] **Step 5:** commit (bump version first).

---

## Phase 1 — Cheap register columns with a measured population

### Task B: `vol` — master volume `[subagent]` Sonnet 5.5

**Files:** modify `python/fidelity.py` (`volume_compare(orig: FilterState, ours: FilterState, nframes: int, lag: int) -> dict` with `vol` (frames both nibbles equal over frames either side sounds; `None` when `nframes == 0`), `vol_ratio` (linear `our_mode / orig_mode`, comparable to `loud_ratio`), `orig_volume_values`, `our_volume_values`, `vol_informative` (True when either side is ever != `$F` or the two differ); `Dimension("vol", "vol", ("$D418",), "fraction", of=...)`; the `--vice` path reads `Sample.modevol & 0xF`); rewrite `fidelity.py:6189-6192` quoting the retracted sentence; tests in `python/tests/test_fidelity.py`.

- [ ] **Step 1: failing tests** — `test_vol_identical_is_one`; `test_vol_constant_eight_against_f_is_zero` (orig `[(0,8)]`, ours `[(0,15)]`, 500 frames -> `vol == 0.0`, `vol_ratio == pytest.approx(15/8)`, `orig_volume_values == {8}`); `test_vol_lag_invariant`; `test_vol_init_blip_is_one_frame` (orig `[(0,0),(1,15)]` vs ours `[(0,15)]` -> charged one frame, not the window); `test_vol_population_flag` (`$F` both -> `vol == 1.0` and `vol_informative is False`); `test_loud_dimension_unmoved_by_vol` (the registry still has `loud` reading `rendered audio`); `test_vol_dimension_states_end_of_frame_blindness`.
- [ ] **Step 2-4:** fail -> implement -> pass.
- [ ] **Step 5:** scratch register-only corpus run (`H2G_ALLOW_MISSING_FLAG=1`, `--json` into a scratch path, `--jobs 16`), reporting: files with `vol_informative`, their `vol`, `vol_ratio` and the row's `loud_ratio`. Expected (census, note 6): Mega_Apocalypse and Pygmies_Revenge at `vol 0.0`, `vol_ratio ~1.875`, matching `loud_ratio` 1.94/1.80; held files listed separately. If the expectation fails, stop and report — do not tune.
- [ ] **Step 6:** commit. Open the Task K item `vol-mega-apocalypse-pygmies` with the DXY design question (note 19).

### Task C: `ctrl` — sync / ring / test bits `[subagent]` Sonnet 5.5

**Files:** modify `python/fidelity.py` (`ctrl_bits_compare(orig: list[Voice], ours: list[Voice], nframes: int, lag: int) -> dict`: `sync`, `ring` as count ratios ours/orig like `noise` (`None` when the original has none), `test_orig_only` / `test_ours_only` frame counts with the `$09` firstwave frame per note excluded from ours, and `ctrl` = share of frames either side sets any of bits 1-3 on which both agree bit for bit); Dimensions `sync`, `ring`, `ctrl`; tests.

- [ ] **Step 1: failing tests** — `test_ring_lost` (orig `$15`, ours `$11` -> `ring 0/N`, `ctrl 0.0`), `test_firstwave_test_bit_not_charged` (ours `$09` on note openings only -> `test_ours_only == 0`), `test_orig_test_bit_is_charged` (orig holds `$09` for 10 frames mid-note -> `test_orig_only == 10`), `test_wave_unaffected_by_ring_loss` (pins that `wave` reads 1.0 on the ring-lost case), `test_ring_declines_when_original_has_none`.
- [ ] **Step 2-4:** fail -> implement -> pass.
- [ ] **Step 5:** scratch corpus run (as Task B); report per-direction populations against the census (ring 44 / sync 26 / test 14 originals). A `ring` of 1.00 everywhere is a finding ("carried") and is written into `of`; any file losing ring/sync is a Task K lead.
- [ ] **Step 6:** commit.

### Task D: `res` + `route` — resonance and per-voice routing `[subagent]` Sonnet 5.5

**Files:** modify `python/fidelity.py` (`filter_ctrl_compare(orig: FilterState, ours: FilterState, nframes: int, lag: int) -> dict`: `res` = frames with equal `$D417 >> 4` over frames EITHER side has a voice routed AND a passband selected (the `filtered_frames` predicate, `fidelity.py:5014`); `route` = per-voice agreement of bits 0-2 over the same frames; `None` when neither side ever filters; `--vice` path from `Sample.res`); two Dimensions; tests.

- [ ] **Step 1: failing tests** — `test_res_known_bad` (`$F` vs `$0` while filtering -> 0.0), `test_route_voice_swap` (orig routes v1, ours v2 -> `route 0.0` while `passband_agree` 1.0 — pins what `band` cannot see), `test_res_ignores_unfiltered_frames`, `test_res_declines_when_neither_filters`.
- [ ] **Step 2-4:** fail -> implement -> pass.
- [ ] **Step 5:** scratch corpus run; expected population 29-30 `res` / 28 `route` (minus *not converted*). IK_plus (`loud_ratio` 0.70, 8997 filtered frames) is the first file to read. TODO: whether `--vice`'s `RES:` field is the whole byte.
- [ ] **Step 6:** commit.

---

## Phase 2 — Columns that need new data

### Task E: `aud_timeline` — where in the song the sides part `[subagent]` Sonnet 5.5

**Files:** modify `python/sound.py` (`compare_features(...)` additionally returns `per_second: list[float]`, sounding-frame weighted); `python/fidelity.py` (row keys `aud_timeline` (2 dp) and `aud_first_dip_s`: first second whose `per_second` is below the song's own median by more than the noise floor for 3 consecutive seconds; `None` when none); `abpage.py` prints the dip seconds (songview cannot map seconds to rows — note 23); tests in `tests/test_sound.py`, `tests/test_fidelity.py`.

- [ ] **Step 1: failing tests** — `test_per_second_weighted_mean_matches_aud` (within 1e-6), `test_first_dip_located` (identical features except seconds 40-45 -> 40), `test_no_dip_is_none`.
- [ ] **Step 2: validation on real known-bads (no synthetic):** `sound_calibrate.KNOWN_BAD` W_A_R 0.5.399 -> 0.5.400 must dip inside 20-60 s; Action_Biker 0.5.371 -> 0.5.372 at ~0 s. Use `sound_calibrate.convert_at` to rebuild both sides. If either fails, stop and report.
- [ ] **Step 3-4:** implement -> pass -> commit. Routine-refresh adoption needs no new flag (`--sound` already renders); say so.

### Task F: `aud_voices` — per-voice rendered sound `[subagent]` Sonnet 5.5

Fills the shape `fidelity_queue.voice_deficits` expects (`aud_voices: [v0, v1, v2]`, tag `[main]`).

**Files:** modify `python/sound.py` (`compare_sids(..., mute: tuple = ())`; `content_key(path, delay, mute=())` folds the mute set in; `render_cached` passes `mute` to the renderer, whose signature is already `(sid, out, seconds, subtune, mute=())`); `python/fidelity.py` (behind `--sound-voices`: three solo renders a side, voices paired by `wave_voices` agreement with `aud_voice_pairing` recorded); tests in `tests/test_sound.py`, `tests/test_fidelity.py`, `tests/test_queue.py`.

- [ ] **Step 1: failing tests** — `test_cache_key_differs_by_mute`, `test_solo_render_passes_mutes` (fake renderer records `mute == (2, 3)` for voice 1), `test_pairing_follows_wave_not_index`, `test_voice_deficits_fires` (`[0.95, 0.60, 0.94]` -> tier-4 entry naming voice 1, tag `[main]`).
- [ ] **Step 2-4:** fail -> implement -> pass.
- [ ] **Step 5:** run on Task A's top five non-held; record which voice carries each residual and the measured render cost (TODO: the "3x" is an assumption).
- [ ] **Step 6:** commit. Adoption into the refresh is a `[main]` decision after the cost is measured.

### Task G: `--all-subtunes` sweep `[subagent]` Sonnet 5.5 (build) -> `[main]` (run)

**Files:** modify `python/fidelity.py` (`--all-subtunes`: for each file every subtune of OURS, paired to the original through `subtune_matrix`/`SUBTUNE_COUNTERPART`, written to `build/fidelity_subtunes.json` and `docs/SUBTUNE-FIDELITY.md`; the main report untouched); tests.

- [ ] **Step 1: failing tests** — `test_all_subtunes_enumerates` (fake converter with 3 subtunes -> 3 rows), `test_all_subtunes_never_scores_a_stub` (a pair whose matrix melody is below the diagonal's is recorded `unpaired`, not scored — FIDELITY-TOOL-IMPROVEMENTS "what not to do" §3), `test_dropped_subtune_is_recorded` (TODO: no census marks a subtune `sfx`/past-table today; the row must say `dropped: <reason>` from whatever `convert` reports, and the test must build that reason, not assume a marker).
- [ ] **Step 2-4:** fail -> implement -> pass; commit.
- [ ] **Step 5 `[main]`:** sharded run, `-t 60` to bound cost (158 extra subtunes at v0.5.595), header says so. List subtunes >= 10 points below their file's default on `aud` or `melody`.

### Task H: Re-take the sound floors `[main]`

The calibration is at v0.5.490, pre `--delay=0`, and reads FAIL. Not a new probe: run `python sound_calibrate.py <sid_dir>` at HEAD (it carries its own flag guard), read checks 2-4 at 60 s and whole-window, and record the floors this plan's `aud` decisions use. If check 2's repeat-render floor is now well under 0.0183, say so with the version; if the doc still reads FAIL, the plan's `aud` thresholds stay relative. No threshold in this plan is absolute.

### Task I: `env` — envelope level trajectory `[subagent]` Opus 5.5 — CONDITIONAL

Runs only if a Task K investigation names "envelope shape" or "right but late" as the mechanism no column sees. Builds on `SID_RATE_PERIOD`, `SID_DECAY_UNITS`, `SID_DELAY_BUG_CYCLES`, `_decay_to_zero_frames` and `envelope_zero_frame` in `fidelity.py` — no new `envsim.py` constants. `tail` and `adsr_exact` already cover the `cut_release` mask; the draft's `test_release_masked_case_seen` is replaced by `test_tail_already_sees_it` as a guard against duplicating `tail`. Validation oracle is TODO (vicetrace has no ENV3; see note 10) and must be settled before implementation starts.

---

## Phase 3 — Turn findings into work

### Task J: Queue learns holds and the new keys `[subagent]` Sonnet 5.5

**Files:** modify `python/fidelity_queue.py` — every entry gains `held: bool` from `hold.held()`, and a held entry renders under *On hold: DIGI* with no tag (a `/whattask` task confined to held files is `requires-user`); new entries for `aud_first_dip_s` (tier 6, the second named) and per-column cause text for `vol`/`res`/`route`/`ctrl` (`column_outliers` already emits their outlier rows — no change there); tests in `tests/test_queue.py`.

- [ ] Steps: `test_held_entries_are_separated_and_untagged` (a Mr_Meaner outlier row -> held section), `test_dip_entry_names_the_second`, `test_vol_outlier_cause_names_loud_ratio` -> implement -> pass -> commit.

### Task K: Investigate each top finding `[subagent]` per finding, Opus 5.5 for root cause

Expected first, with the mechanism candidate each already carries:
- Mega_Apocalypse, Pygmies_Revenge — `vol` `$8` vs `$F` (Task B); the fix is CMD_SETMASTERVOL and its placement (note 19). Census across the corpus: all 20 volume files, held ones listed, none worked.
- Kings_of_the_Beach_ingame — every note rings where the original writes waveform `$00` (`gate_ours_ringing` 84/84); test `rest_wave_silence` in an A/B; 8 s window noted.
- Confuzion (307 s window, aud 0.80, `adsr` 0.86 / `adsr_exact` 0.24), Chicken_Song (`loud_ratio` 0.83, volume `$F`), IK_plus (`loud_ratio` 0.70, filter-heavy; read `res`/`route` first).

- [ ] `--diagnose` + `songview.py` + `--vice` around `aud_first_dip_s`, on the voice `aud_voices` names.
- [ ] Name the mechanism; census it across the corpus (memory: *cross-song mechanism check*) before proposing a fix.
- [ ] Output: a queue entry with mechanism, files sharing it, proposed fix, and the A/B that would prove it. Stop on refuted — no auto-fix.

### Task L: Fixes `[subagent]` each, `[main]` to adopt

- [ ] One worktree per mechanism; corpus byte-hash + targeted `--baseline` A/B; fixture byte-exact. A new `convert()` option is inert until it is in the signature, `presets.FIXED` and `_preset_opts` (CLAUDE.md hard invariant).
- [ ] `[main]`: merge, bump, regenerate SURVEY/presets (and FIDELITY/QUEUE with `--json`), full suite.
- [ ] `[user]`: listening verdict via `listen.py`/`abpage.py` on every song whose sound changed.

### Task M: Documentation and refresh `[main]`

- [ ] `docs/MEASURING.md`: one section per new column/key (reads, blindness, population, validation case).
- [ ] `CLAUDE.md` § Measurement discipline: headlines only; evidence to `docs/LESSONS.md` (including the census figures above, versioned).
- [ ] `flag_guard.py`: any adopted flag.
- [ ] Rewrite `fidelity.py:6189-6192` (done in Task B) and FIDELITY-TOOL-IMPROVEMENTS §8's stale items.
- [ ] Regenerate FIDELITY/QUEUE once on `master` after merges.

---

## Order and parallelism

A (read-only) first. **B, C, D** touch disjoint functions in `fidelity.py` and can run in parallel worktrees (optimistic merge: rebase + re-verify on conflict); B is the one with a predicted known-bad and a fix path, so if only one runs, it is B. **E and F** both edit `sound.py` — serialise (E first: it validates on existing KNOWN_BAD pairs and costs no new renders). **G** is independent. **H** is `[main]` and can run any time before a threshold is read. **I** is conditional on K. Then J, K, L, M.

## Answers to the draft's questions

1. **Residual baseline:** `mean(wave, adsr, gate)` — drop `melody` (median 0.9996, a constant that dilutes the spread by a quarter). Report `adsr_exact` beside it, not in it. Print the corpus median of the residual (negative at v0.5.595) in the header.
2. **Is the envelope model worth it?** Not yet. `tail` already sees the `cut_release` case the draft built it for, `adsr_exact` carries the unmasked figure, and the reSID constants it would need are already in `fidelity.py`. `aud_voices` + `aud_timeline` localise a deficit to a voice and a second; only if Task K then names envelope shape as the unseen mechanism does `env` earn its oracle problem (note 10).
3. **Should `--all-subtunes` come first?** No. It measures a large uncovered class (158 subtunes), but every finding there is reached through the same emitters as the default subtunes, it costs 158 extra rows of renders, and its pairing problem (`subtune_matrix`, stubs) is the hardest part of the harness. `vol` costs a day, has a predicted known-bad pair and a fix. Order: B, C, D, E, F, then G.
4. **"What not to do" violations:** none. Two near-misses the draft did not see: Task 3 Step 5 would be refused by `flag_guard.py` (note 14), and Task 9's enumerator must refuse to score a stub (note 16). A third, outside that doc: three of the draft's leads and its multiplier-5 test file were held files (note 1).
