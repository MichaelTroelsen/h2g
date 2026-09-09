# Backlog

Every id an `opened` array in `.claude/tasks/runs.jsonl` has ever named that is **not** a task in
`.claude/tasks/whattask.json`, **not** in its `closed` list, and has **no run record**. It is the
residue the plan deliberately does not carry: a plan that held all of it would stop being a plan.

**This file is DERIVED. Do not hand-edit it.** Promote an entry by adding it to the plan; retire
one by running the work and letting its run record exist. Either way the next regeneration drops
it from here on its own.

Generated at `665939c` on 2026-09-08. **429 entries**, of which **95 carry a rationale** the run record
supplied inline.

## How it is derived

The generator is reproduced here rather than kept in a separate script, so the file and the rule
that makes it cannot drift apart:

```python
SLUG = re.compile(r'^[a-z0-9]+(-[a-z0-9]+){2,}$')
# For every record in runs.jsonl, for every entry of its `opened` array:
#   split at the FIRST colon; the head is the id and the tail, if any, is the rationale.
#   An entry whose head is not a well-formed slug is skipped and counted separately.
# Keep the ids absent from the plan, absent from `closed`, and with no record of their own.
```

**Splitting at the first colon is the load-bearing part.** A pass at `91e8e25` classified 178 of
these as "prose sentences that are not ids at all" and a task was opened to DELETE them at source.
Re-measured at `665939c`: of the 136 non-bare entries, **123 carry a well-formed slug before the
colon** and only 13 are genuinely a sentence. Those 123 are an id *with its rationale attached* --
the most useful form in the whole log, not the least. The delete-at-source prescription is
retracted in the plan.

**TWO COUNTS APPEAR IN THE HISTORY AND THEY ARE DIFFERENT QUANTITIES, not growth.** A pass at
`91e8e25` counted 302 and one at `665939c` counted 325, and BOTH counted bare slugs only -- an
`opened` entry of the form `id: rationale` was excluded from those figures as prose. This file
counts 429 because it splits at the first colon and recovers those ids too, which is the whole
point of the rule above. Compare 302 with 325; do NOT compare either with 429.
Growth over a fixed rule is real but far smaller than that jump suggests: 737 distinct `opened`
refs at `665939c` against 657 at `91e8e25`.

## Entries

### opened by `a-blocked-run-record-describes-a-plan-and-must-not-survive-a-whattask-regeneration`

- **`a-classifier-keyed-on-a-word-cannot-tell-a-report-of-a-grant-from-a-complaint-about-one`** — counting blocked/partial records by the bare word 'grant' reads 36 where the condition-keyed rule reads 3, an over-match of 33 at 665939c -- the same shape as the id-prefix and retraction-collision rules already in CLAUDE.md, and it belongs beside them if a second instance turns up.
- **`the-either-show-or-record-verify-template-grants-no-path-for-the-recording-half`** — seven open main-mode tasks say 'either X is shown, or it is recorded beside the code it concerns' while holding no writable repo path, so only the first arm is reachable; measured at 665939c over 106 open tasks, 8 of which grant no writable repo path once requires-user and the read-only censuses are excluded.

### opened by `a-done-run-record-describes-one-commit-and-a-later-commit-can-expire-it`

- **`the-artefact-staleness-test-should-be-a-committed-script-not-a-remembered-git-incantation`** — whether build/fidelity.json is stale is answerable in one line -- git diff --name-only <label>..HEAD -- python/h2g/ discounting __init__.py, plus git status on the same path -- and it currently answers NOT STALE at 665939c over six intervening commits; it belongs in the repo where the next reader meets it rather than being re-derived, and needs a writable python/ or .claude/skills/ path.

### opened by `a-fourth-pitch-seq-file-was-expected-and-only-three-are-invisible-at-60-seconds`

- **`pitch-seq-is-a-second-always-block-option-that-cannot-reach-the-ilv-decoder`**
- **`whattask-wrote-a-verify-number-that-appears-in-no-run-record`**

### opened by `a-note-before-its-voices-first-instrument-must-not-sound-on-bangkok-but-must-on-delta`

- **`bangkok-pre-instrument-silence-is-the-test-bit-not-a-zero-waveform`**
- **`init-clears-stored-waveform-is-known-for-44-files-but-not-statically-decidable`**
- **`survey-md-is-stale-by-24-versions`**
- **`whattask-touches-reconciliation-ignores-the-doc-with-code-change-rule`**

### opened by `a-pulse-register-term-in-fidelity-better-is-what-would-make-pulse-phase-searchable`

- **`promote-pulse-phase-into-fidelity-toggles-now-that-the-criterion-recovers-four-of-four`**
- **`shipped-presets-carries-four-pitch-seq-yeses-and-five-max-hard-restart-noes-the-search-no-longer-agrees-with`**

### opened by `a-wavetable-tick-is-pinned-to-one-pitch-where-the-player-tracks-the-note`

- **`whattask-dropped-the-partial-bangkok-under-strikes-task-from-the-plan`**

### opened by `ab-1-sound-features-and-compare-wavs`

- **`aud-averages-over-all-64-mel-bands-so-shared-floor-bands-dilute-the-timbre-score`**
- **`every-ab-task-verify-names-a-corpus-byte-hash-that-reads-paths-none-of-them-declares`**
- **`no-ab-task-declares-the-plan-document-so-it-can-never-be-amended-from-inside-its-own-plan`**
- **`the-ab-plan-document-is-out-of-date-with-its-own-align-implementation`**

### opened by `ab-2-sound-cached-renders-and-compare-sids`

- **`sound-py-imports-listen-which-imports-fidelity-so-ab-3-closes-an-import-cycle`**
- **`worktree-isolation-is-impossible-for-the-ab-chain-while-sound-py-is-untracked`**

### opened by `ab-4-sound-calibrate-thresholds`

- **`ab-3-must-name-the-known-bad-blind-spot-in-the-aud-dimension-per-plan-step-6`**
- **`aud-cannot-see-any-of-the-three-documented-fixes-at-sixty-seconds-so-the-ab-chain-needs-a-decision`**
- **`claude-md-attributes-las-vegas-and-samantha-fox-multiplier-flip-to-v0-5-402-but-it-is-401`**

### opened by `ab-5-approvals-inheritance`

- **`ab-5-step-5-adds-a-recover-flag-the-step-3-code-block-does-not-contain`**
- **`ab-5-step-6-writes-build-approvals-json-which-the-tasks-touches-does-not-grant`**

### opened by `ace2-bend-half-attribution`

- **`ace2-instrument4-attack-pitch-spike-missing-on-66-percent-of-notes`** — instrument 4 ($0506, 289 notes) opens each note with a 2-frame attack pitch spike; the original emits it on 288/289, we emit it on 97/288 and emit ZERO on 191. 976,152 units of missing pitch travel, 6.7x the whole bend denominator, and NO column scores it -- bend excludes it (siddump names a >semitone move as a note change) and melody/onset read the attack frame. Bigger than the vibrato depth deficit on this file. [subagent] read-only diagnosis first.

### opened by `ace2-hold-43-percent`

- **`ace2-has-no-note-length-defect-close-the-family`** — ace2-voice0-rings-26-percent-longer (opened by the slides task) proposed folding voice 0's 26% longer sounding into this task. It is the same population: hold's census says 0 short and 0 long, so the extra sounding frames are release/ringing under `gate` 88% and gate_ours_ringing 385, not note length. Any further work belongs to `gate`, not `hold`. [subagent] read-only.
- **`hold-column-counts-slot-and-fetch-as-failures`** — `hold` scores an instrument as not matching when its disagreement is `slot` (a timing question the column does not measure and no wavetable edit can fix) or `fetch` (a known fixed call-rate deficit). On ACE_II that is 4 of 7 instruments, so the column reads 43% on a file with ZERO short/long instruments. Consider reporting hold over the short/long population only, or printing the census split beside the percentage, so a reader cannot mistake it for a note-length defect. [main], touches python/fidelity.py.

### opened by `ace2-slides-emitted-1.6x-too-many`

- **`ace2-voice0-rings-26-percent-longer`** — voice 0 keeps a waveform selected on 2597 frames against the original's 2060 (1.2607x) with gate 88% and gate_ours_ringing 385. That is note LENGTH, not pitch, and it is the same family as the open ace2-hold-43-percent task -- worth folding into it rather than chasing separately. [main]
- **`slides-and-bend-both-misread-a-shallow-vibrato`** — siddump prints a frequency move as a slide line only when the nearest-note NAME is unchanged, so a swing near a semitone is printed as ties and a shallow one as slides. On ACE_II this makes `slides` INVENT a 1.61x surplus out of a depth DEFICIT, and makes `bend` overstate the same deficit (0.478x against a true voice-0 interior travel of 0.59x and 0.83x file-wide) by discarding the original's 460 tie-line movements. Both Dimension docstrings should carry this beside the existing drum-sweep caveat; CLAUDE.md's 'prefer a travel measure to a count' paragraph should name it as the case where BOTH forms mislead. [main], doc + docstring change.

### opened by `ace2-wave-gate-residual-census`

- **`build-instrmap-is-stale-against-head`** — build/instrmap/*.md predate 428ca07 and therefore predate --rest-envelope-silence being enabled for five songs. Every read-only diagnosis in this plan reads those dumps. Rebuild with `python abpage.py --instrmap <sid_dir>` before the next cycle, or each agent pays to regenerate its own. [main], rebuilds build/instrmap and build/listen.

### opened by `action-biker-drum-run-is-one-frame-short-at-its-start`

- **`a-task-whose-title-came-from-an-uncorrected-frame-pairing-should-be-re-derived-before-it-is-run`**
- **`action-biker-trades-a-pitch-exact-11-frame-drum-for-a-12-frame-one-255-units-out`**
- **`the-drums-frame-0-needs-its-own-pitch-and-firstwave-carries-only-a-waveform`**

### opened by `action-biker-hold-zero-is-fetch-not-length`

- **`action-biker-adsr-69-and-gate-72`** — with hold refuted and the sequence exact, Action Biker's remaining measurable deficit outside nrun is adsr 69% / gate 72% / wave 97%. Neither has been attributed to a cause. Census them the way onset was censused before touching an emitter. [subagent], read-only.

### opened by `action-biker-listening-verdict`

- **`5-title-tunes-pulse-sweep-subdivided-twice-too-finely`** — pul 4459/2240 = 1.99x with pspan 0.47x, and 1.99 x 0.47 = 0.94 -- total travel about right, sweep subdivided twice as finely. NOT the per-frame-vs-per-call multiplier family (presets records multiplier 1, where that correction is the identity). Look at the pulse program's own step encoding, in particular the triangle engine's `& $E0` step against `& $1F` frames-between-steps. In todo.md. [subagent] for the census, [main] for any emitter change.
- **`conversion-must-match-original-length-within-5-seconds`** — the listener's rule, now in CLAUDE.md as an invariant and in todo.md as two pieces of work. No column enforces it -- drift, retrig and --pace all measure the rate of a ROW and are every one of them satisfied by a conversion that plays the right music at the right speed FOREVER. (1) a `len` dimension reporting seconds of music ours plays against the original's, flagged outside +-5 s [subagent]; (2) an opt-in restart into a SILENT pattern instead of position 0, so the tune ends in every way a listener can hear [main].
- **`original-ended-is-a-defect-queue-not-a-methodology-note`** — fidelity.original_ended already detects that the original stops inside the window, and uses it to SHORTEN the comparison so our surplus is not charged -- protecting the score while the shipped .sng still plays forever. That is the same shape as the --search-subtunes line corrected in v0.5.375, one level over: a shim that hides a defect from the score does not hide it from the file. Every file whose window it shortens FAILS the +-5 s rule and should be listed as such. [main], touches python/fidelity.py.

### opened by `action-biker-noise-runs-are-one-frame-short-and-the-leading-gate-bit-is-refuted-as-the-lever`

- **`action-biker-drum-run-is-one-frame-short-at-its-start-and-wants-a-fix-that-keeps-frame-zero`**

### opened by `action-biker-nrun-zero-run-lengths`

- **`fidelity-has-no-nrun-census`** — `--census` is the ONSET census only. The nrun column has no by-cause census, so answering 'why is nrun 0%' required a hand-written wrapper around noise_run_agreement. CLAUDE.md's rule is that a scratch script answering a question twice is a tool that was not committed -- this is the second time run-length disagreement has been investigated by probe. Promote it. [subagent], touches python/fidelity.py and python/tests/test_fidelity.py.
- **`noise-and-nrun-are-not-independent-columns`** — for a file whose runs have zero variance, noise (frame count) and nrun (modal run length) are algebraically the same number -- Action_Biker's 682/744 IS 11/12. Two columns that cannot disagree are one column presented as corroboration. Worth a caveat in both Dimension docstrings. [main], doc.
- **`nrun-modal-equality-is-a-boolean-on-single-instrument-files`** — noise_run_agreement is a modal-equality test over shared ADSR keys, so on a file with ONE such instrument it can only read 0% or 100%. Action_Biker reads 0% off a single instrument that is off by one frame -- indistinguishable in the report from a file where everything is wrong. Print the instrument count beside the percentage, the same fix `hold` needs. [main], touches python/fidelity.py.

### opened by `action-bikers-fidelity-is-not-99-percent`

- **`action-biker-gate-off-lands-1-to-2-frames-late-on-every-matched-release`**

### opened by `adsr-counts-inaudible-gate-off-attack-decay`

- **`adsr-gated-off-split-could-be-a-column`** — `adsr_gated_off` and `adsr_gated_off_audible` ride in the row and in `--json` but are not printed, so a reader of docs/FIDELITY.md sees the corpus figure in the methodology note and cannot see their own file's split. Geoff Capes and Battle of Britain are at opposite extremes and the table cannot say so. Adding a column means a Dimension entry, the header, the hand-built row AND the not-converted dash count -- the three places that have drifted twice this session. Worth it only if a reader actually wants it per file. [main], touches python/fidelity.py, python/tests/test_fidelity.py, docs/FIDELITY.md.

### opened by `align-maximises-envelope-correlation-and-can-still-pick-a-worse-residual-integer-hop`

- **`aud-and-loud-move-corpus-wide-under-the-new-align-and-the-size-is-predicted-not-observed`**

### opened by `arp-mask-period`

- **`arp-fix-reaches-untraced-subtunes-on-4-files`** — Zoids, Battle_of_Britain, Human_Race and Rasputin all changed bytes under this fix while their fidelity-traced subtune's reversal count stayed exactly identical -- the changed records are not sounded by the subtune fidelity.py traces, so a real fix reads as a no-op on 4 of 9 files. Decide whether the report should trace more than one subtune per multi-subtune file, or at minimum say when a change reached only an untraced one. [main]
- **`arp-swing-listening-verdict-needed`** — the 1:7 swing means an instrument now spends 7 of every 8 frames an octave above the pattern's note where it used to alternate every frame -- large, audible, and no FIDELITY.md column judges whether it SOUNDS right on the six $07-BEQ files. Stage Master_of_Magic and Phantoms_of_the_Asteroid with listen.py for a human verdict. [user]
- **`arp-swing-read-twice-move-to-detection`** — the counter mask/branch is read once in detect._find_effect_routines (kept only as the ADC operand) and again in goatwriter._read_fixed_arp_swing over the identical search string -- move it into the Detection dataclass beside arp_fixed_up so it's walked once; excluded here because detect.py was outside this task's declared touches. [main]
- **`arp-tick-plus-drum-bit-conflict`** — a record setting both effect bits $01 and $04 keeps the OLD 1:1 loop because the tick block owns entries the new 1:7 loop needs -- on Master_of_Magic alone this leaves 3 instruments (GT 8, 5, 17) reported as arp/absent, 113 reversals missing. Find whether the variable-length wavetable can afford both, or state the surrender order the way _drum_entries does. [subagent]
- **`master-of-magic-slides-bend-unattributed`** — Master_of_Magic's slides/bend movement under the arp fix is real and not fully attributed. Live lead: instrument GT 7 carries both the arp bit and a vibrato pointer -- the old 1:1 loop rewrote its note every frame, the new 1:7 loop leaves it to a delay entry for 13 of 16 calls, so Goattracker's own vibrato accumulates instead of resetting. Turn the proposed cause off (pad that record's arp run with note-writing entries instead of delays) and see if bend returns toward 0.75x. [subagent]
- **`rasputin-mask-vs-measured-ratio-mismatch`** — Rasputin's block reads mask $02 (predicted 2:2) but the original measures mostly 3:3 run lengths -- its counter does not advance once per frame the way the other four files' do (its INC sits beside an extra store the others lack). Read what actually writes that counter before trusting the 2:2 reading. [subagent]
- **`vib-census-blind-to-over-oscillation`** — fidelity.py --vib-census only lists instruments oscillating at UNDER half the original's rate, so a file oscillating too much (Zoids, vib 3.65x) gets an empty census table and no attribution at all -- the exact column that adjudicates every arp/vibrato change is one-sided. [subagent]

### opened by `artefact-stamp-realign`

- **`fidelity-stamp-is-dirty-by-construction`**

### opened by `awm-release-length`

- **`gate-column-blind-to-testbit-silence`**
- **`player-releases-a-whole-row-inexpressible`**

### opened by `awm-voice2-gate-bit`

- **`awm-short-rest-detection-gap`** — Auf Wiedersehen Monty's gate deficit is 219 `held` runs of at most 4 frames -- the original rests and we sustain. rest_keyoff is already on and rest_envelope_silence provably does not touch the gate, so these are rests DETECTION does not see rather than rests the emitter mishandles. Next step is to find what the player does on those frames that our bit-6 rest test misses. [main], opus, touches python/h2g/detect.py.

### opened by `bangkok-c-sharp-6-tick-stops-at-frame-1131-and-the-pitch-is-now-refuted-as-the-cause`

- **`bangkok-writes-adsr-0000-with-waveform-08-on-109-frames-and-neither-rest-option-reaches-it`**

### opened by `bangkok-under-strikes-by-18-attacks-once-the-spurious-twenty-are-gone`

- **`bangkok-and-monty-both-pin-a-tick-to-one-pitch-where-the-player-tracks-the-note`**
- **`bangkok-c-sharp-6-wavetable-tick-stops-at-frame-1131-while-both-instruments-loop-onto-it`**
- **`bangkok-second-half-never-clears-the-gate-so-siddump-cannot-name-our-tick`**

### opened by `bangkok-writes-adsr-0000-with-waveform-08-on-109-frames`

- **`bangkoks-drum-silence-needs-the-drum-on-pattern-rows-not-in-the-wavetable`**
- **`goattrackers-hard-restart-is-a-gate-off-and-cannot-express-a-zeroed-envelope`**

### opened by `boundary-tie-four-files-retrig-below-one`

- **`docs-boundary-tie-rest-rule-claude-md-and-method`**
- **`status-bit6-shape-misses-devils-galop-volume-block`**

### opened by `boundary-tie-loop-around-restart-position`

- **`star-paws-subtune-1-voice-2-under-attacks-by-58`** — Star_Paws subtune 1 reads melody 0.7481 / seq 0.8636 against 0.9869 / 0.9854 on subtune 2, and the cause is not the wrap tie -- voice 2 sounds 234 attacks in 60 s against the original's 292, a deficit of 58, while voices 1 and 3 over-attack by 12 and 20. A wrap tie can only ever ADD one attack per loop, so this is a separate mechanism and it is the largest single defect on the file. Note the harness resolves this file at -S2, and `fidelity.py Star_Paws.sid --diagnose` should be run BEFORE calling it a converter bug: three of the four files once filed under 'plays something else' were the harness. [main], opus.

### opened by `build-fidelity-json-is-stale-again-for-the-four-instrument-count-files`

- **`row-fields-have-no-passthrough-test-the-way-convert-options-do`**

### opened by `c64-music-examples-phantom-subtunes-not-trimmed`

- **`delete-or-document-the-superseded-worktree-branches`** — three branches are now confirmed fully superseded (4663ffa, 55f5f12, f2c86f2) and one -- worktree-wf_beea4e15-8ff-1 -- carries a Spellbound=4 assertion that contradicts the repo's settled 3. They will be re-examined by every future pass that notices an unmerged branch. Delete them or record the supersession somewhere a `git branch -a` reader will see. [main], git housekeeping.
- **`empty-voice-test-pins-rasputins-old-subtune-count`**
- **`refidelity-search-the-17-bounded-files`**
- **`regenerate-subtunes-md-after-the-track-table-bound`**
- **`spellbound-4-vs-3-would-have-regressed-silently`** — the branch's test asserted Spellbound = 4 (the layout extent) where f63caa1 established 3 (the init dispatch). Had it been rebased mechanically, the test would have been 'fixed' to match the branch rather than the repo. Worth a line in CLAUDE.md's subtune-bound paragraph naming Spellbound as the file where a stale branch and the settled answer differ. [subagent], doc only.
- **`subtune-census-test-needs-a-synthetic-placeholder`**

### opened by `c64me-instrument-table-mismatch`

- **`c64me-phantom-subtunes-are-pattern-pointers`**
- **`survey-reports-15-subtunes-where-1-is-real`**

### opened by `census-set-only-pulse-programs-across-corpus`

- **`pulse-table-exhaustion-eleven-instruments-set-no-width`**

### opened by `chicken-song-alone-qualifies-for-the-derived-wave-alternate-and-there-is-no-option`

- **`a-zero-register-baseline-at-60-seconds-is-the-likeliest-to-be-non-zero-at-180`**
- **`goatwriter-wave-alternate-comment-carries-60-second-figures-that-invert-its-conclusion`**

### opened by `chicken-song-command-arpeggio`

- **`cmdtable-chord-arpeggio-emission`**
- **`regenerate-vibrato-and-fidelity-after-chicken-drum-fix`**

### opened by `chimera-and-confuzion-instrument-counts-are-two-different-off-by-ones`

- **`a-verify-written-from-a-symptom-named-a-fix-that-crashed-action-biker`**

### opened by `chimera-confuzion-and-mega-apocalypse-dangle-instruments-for-a-reason-that-is-not-the-stride`

- **`chimera-waveforms-set-missing-gate-clear-triangle-byte-0x10-undercounts-instrument-table`**
- **`confuzion-count-instruments-eof-peek-drops-last-valid-record-when-table-abuts-end-of-ripped-file`**
- **`mega-apocalypse-instrument-66-may-be-an-unmasked-effect-bit-rather-than-a-genuine-index`**

### opened by `chimera-startup-lag`

- **`startup-lag-reduction-robustness`**

### opened by `chimera-voice0-gate-suppression-unlocated`

- **`duration-zero-is-a-tie`**
- **`duration-zero-tie-corpus-ab`**
- **`gate-edge-census-column`**

### opened by `classic-vibrato-row-calls-wants-the-mean-row-not-the-shortest`

- **`vibrato-cmp-quantisation-limits-the-tick0-correction`**

### opened by `claude-md-carries-four-more-figures-and-three-probe-lessons-from-this-drain`

- **`a-plans-verify-string-is-itself-an-ungraded-figure-and-should-name-where-to-re-derive`**
- **`window-coverage-is-floored-at-1800s-so-any-statistic-over-it-reports-the-floor`**

### opened by `claude-md-carries-three-more-figures-the-v0-5-455-pass-did-not-reach`

- **`claude-md-refers-to-h2g-conversion-method-md-at-the-root-where-it-lives-in-docs`**
- **`conversion-method-7-iiii-carries-60-second-chicken-song-figures-under-a-180-second-regime`**
- **`h2g-conversion-method-7-iiii-still-needs-rw-on-docs-h2g-conversion-method-md`**
- **`the-plan-is-exhausted-and-whattask-must-regenerate-with-four-touches-corrections`**

### opened by `claude-md-states-measured-numbers-in-the-present-tense`

- **`cd-then-heredoc-depends-on-should-be-contention-not-dependency`**
- **`grade-the-claude-md-figures-that-need-a-corpus-sweep`**

### opened by `claude-mds-graded-figures-should-be-a-committed-check-not-a-periodic-chore`

- **`a-claim-about-the-source-is-a-second-uncheckable-category-beside-the-one-off-percentages`**
- **`a-doc-versus-artefact-test-needs-rw-on-the-doc-because-it-will-find-a-disagreement-on-day-one`**
- **`claude-md-says-the-drift-split-is-68-18-and-every-artefact-since-v0-5-455-says-69-17`**
- **`claude-mds-wave-program-split-is-9-at-head-and-10-in-the-tree-and-owes-a-regrade-on-commit`**

### opened by `cmd-setwaveptr-is-goattracker-command-8-and-patterns-py-does-not-define-it`

- **`cmd-setfilterptr-is-command-10-and-is-what-the-ilv-87-sweep-needs`**
- **`the-index-to-row-patch-shape-now-exists-twice-with-two-orderings-and-no-name`**

### opened by `commando-voice-1-plays-g-sharp-7-where-the-original-plays-b-5`

- **`commando-note-104-is-not-a-note-and-the-faithful-emission-is-a-fixed-high-pitch-not-a-clamp`**
- **`commando-note-byte-104-to-index-71-mapping-is-still-unknown`**
- **`commando-voice-1-octave-is-player-state-not-the-note-byte`**

### opened by `confuzion-runs-295s-past-its-original-the-only-measured-length-failure`

- **`whattask-regeneration-carries-stale-verify-text-forward-instead-of-re-deriving-it`**

### opened by `convert-through-preset-opts-and-the-harness-produce-different-bytes`

- **`v0-5-425-action-biker-sha-retraction-is-itself-withdrawn`**

### opened by `converter-emits-sound-effects-as-subtunes`

- **`sfx-dispatch-bcc-spelling`**

### opened by `crazy-comets-last-missing-attack`

- **`crazy-comets-voice0-g-sharp-7-pitch-defect`**
- **`fidelity-window-loses-startup-lag-frames-of-the-original`**

### opened by `drift-fits-one-rate-to-tunes-whose-offset-has-a-knee-and-cannot-say-so`

- **`the-knee-fields-want-a-report-column-once-an-artefact-writing-task-can-add-one`**
- **`two-of-the-eight-knee-files-are-interleaved-and-lakers-also-has-the-attack-surplus`**

### opened by `drum-return-to-base-detection`

- **`drum-return-to-base-emission`**
- **`vib-census-ambiguous-adsr-filter`**

### opened by `effect-byte-address-inverts-only-the-naive-branch-of-to-offset-so-i-ball-is-wrong`

- **`a-probe-that-reimports-a-module-cannot-compare-its-dataclasses-with-equals`**
- **`a-verify-that-is-a-preset-driven-byte-hash-depends-on-whatever-decides-the-presets`**

### opened by `emit-bit08-note-alternate`

- **`first-frame-lead-written-multispeed`**

### opened by `emitter-and-read-only-tasks-in-this-plan-had-touches-too-narrow-to-record-their-own-findings`

- **`a-task-whose-deliverable-edits-whattask-json-cannot-run-under-runtask-and-needs-re-homing`**
- **`diagnosis-tasks-with-a-fix-branch-should-be-granted-the-whole-h2g-subsystem-not-more-artefacts`**

### opened by `envelope-cut-writes-0000-at-note-end-and-cut-release-only-zeroes-a-nibble`

- **`v0-5-426-five-title-tunes-adsr-attribution-is-wrong-and-the-gate-coincidence-was-real`**

### opened by `fidelity-better-has-no-term-that-can-see-a-rest-parked-waveform`

- **`the-eight-toggle-search-re-decides-ik-plus-and-one-on-one-at-180-seconds`**

### opened by `fidelity-hardcoded-drift-count`

- **`agent-returned-stub-record-unverified`**

### opened by `fidelity-hardcodes-s2-in-multispeed-summary`

- **`recover-and-reapply-lost-goatwriter-vibrato-realtimeoptimization-patch`**

### opened by `fidelity-json-reports-no-noise-pitch-so-part-of-fidelity-better-cannot-be-tested`

- **`five-files-emit-a-noise-pitch-of-exactly-12604-which-looks-like-a-constant`**
- **`presets-noise-pitch-should-delegate-to-fidelity-rather-than-duplicate-it`**
- **`trans-atlantic-and-nineteen-drums-are-pitched-a-fifth-high`**

### opened by `five-non-converting-files-share-one-stored-wave-key-and-detect-finds-no-hubbard-player`

- **`a-four-voice-track-table-needs-a-fourth-voice-decision-before-any-of-it-is-emitted`**
- **`interleaved-classic-instrument-stride-is-16-in-the-player-and-8-in-detection`**
- **`nine-converting-files-share-the-init-copy-idiom-so-it-must-be-a-last-resort-chain`**
- **`the-interleaved-classic-six-need-a-third-pattern-grammar-bit7-set-is-a-command`**
- **`the-pattern-table-can-be-interleaved-and-no-dialect-supports-stride-2`**
- **`whattask-touches-must-cover-the-file-the-work-has-to-be-made-in-not-only-paths-the-verify-names`**

### opened by `five-title-tunes-pulse-census`

- **`pul-and-pspan-should-be-read-as-a-pair-in-the-report`** — `pul` doubling is the expected half-step substitution and `_span` documents it, but the report prints the two columns side by side with no hint that a 2x count next to a normal band is CORRECT while a 2x count next to a halved band is not. A reader without the docstring cannot tell. Worth a line in FIDELITY.md's column notes. [main], doc.
- **`pulse-sweep-cannot-free-run-across-notes`** — the substantive defect, and it is NOT the field split the plan assumed. Goattracker reloads the pulse pointer at every note while the player's accumulator free-runs, so on a file with short uniform notes our band is a fraction of the player's (5_Title_Tunes: 449/771/899 against 1536/1536/1408). Any fix has to make the sweep's phase survive a note, which a per-instrument pulse program structurally cannot -- so this may be a limitation to document rather than a defect to fix, and that judgement should be made before code is written. Same family as the wavetable-cannot-hold-a-global-counter case CLAUDE.md records for effect bit $10. [main], opus.
- **`pulse-triangle-docstring-claims-the-band-carries-over`** — _pulse_triangle (goatwriter.py:4358) states 'The band and the rate carry over; the phase cannot.' Measured on 5_Title_Tunes the band does NOT carry over when notes are short against the sweep period. Correct the sentence whether or not the emitter changes -- it is the sentence that would stop the next reader looking. [subagent], docstring only.

### opened by `five-title-tunes-wave-90-note-end-frame`

- **`five-title-tunes-gate-note-length`** — our gate spans 6 frames per 8-frame period where the original's spans 4 (one frame late closing, then Goattracker's 2-frame hard restart). That is the other half of this file's gate 0.4996 and is invisible to wave by construction. [subagent] if confined to the emitter plus a corpus byte-hash.
- **`five-title-tunes-real-firstwave-preset`** — adopt real_firstwave_instruments for 5_Title_Tunes.sid -- measured here as {1,2,3,5,6,8} giving wave 0.8958 -> 0.9857 for melody 0.9982 -> 0.9950, with instrument 6 free and instrument 7 the one that must be excluded. [main] -- it writes presets.json.
- **`five-title-tunes-real-firstwave-preset-costs-pitch`** — the wave half is reachable via a per-song real_firstwave_instruments entry, but the {1,2,3,5,6,8} combination the census recommends costs pitch_jaccard 1.0000 -> 0.9836 and sequence 0.9984 -> 0.9957 alongside wave 0.8958 -> 0.9857 and melody 0.9982 -> 0.9950. The per-instrument sweep that produced the recommendation did not measure pitch. Re-run it over ALL the columns before adopting any subset, and note real_firstwave_instruments is not in FIDELITY_TOGGLES so the search cannot find this on its own. [main], touches python/presets.py and presets.json.
- **`instr7-firstwave-sequence-collapse`** — with the real-waveform firstwave on GT instrument 7, voice 0's attack and note counts become exact (375/375, 286/286) while its difflib sequence falls 0.9987 -> 0.6933. Not the documented attack-visibility collapse; cause unknown.

### opened by `fix-7kkkkk-cue-stall-claim`

- **`prune-worktrees-conflicts-with-the-runner-itself`**

### opened by `food-feud-and-mega-apocalypse-now-detect-pitch-seq-and-nobody-has-measured-enabling-it`

- **`mega-apocalypse-pitch-seq-is-a-near-exact-vib-fix-costing-twelve-points-of-pitch-and-needs-an-ear`**

### opened by `four-pitch-seq-files-move-bytes-and-no-column-sees-them-at-either-window`

- **`claude-md-no-column-moved-bullet-needs-a-fourth-cause-the-window-lacks-the-material`**

### opened by `freq-table-length-off-by-one-at-the-grid-edge`

- **`freq-table-bit-40-indices-above-127-wrap-in-goatwriter`**
- **`freq-table-run-vs-length-test-assertions`**

### opened by `freq-table-per-engine-nearness`

- **`fidelity-engine-flag`**
- **`powerplay-cue-length-stall`**

### opened by `gate-and-hold-report-opposite-signed-note-length-errors-on-action-biker`

- **`a-dimension-edit-forces-a-regeneration-that-runtask-cannot-stamp-cleanly`**
- **`gate-dimension-description-does-not-say-it-is-not-a-note-length-measure`**

### opened by `go-go-dash-drops-58-percent-of-its-attacks-and-its-duration-unit-is-3-75-frames`

- **`go-go-dash-onset-is-20-percent-with-zero-early-and-zero-late-so-it-is-shape-not-phase`**
- **`go-go-dash-pace-least-squares-fit-reads-0-833-where-its-median-reads-1-000`**
- **`the-interleaved-classic-dialect-emits-no-filter-at-all-on-go-go-dash`**

### opened by `go-go-dash-emits-zero-noise-frames-against-the-originals-1972`

- **`six-preset-adoptions-now-sit-ahead-of-build-fidelity-json-and-the-refresh-is-owed`**
- **`the-interleaved-engine-keeps-its-two-stage-duration-somewhere-the-push-chain-is-not`**
- **`the-interleaved-two-stage-reaches-29-percent-of-go-go-dashs-noise-and-the-ungated-870-is-a-second-mechanism`**
- **`two-stage-was-hand-adopted-on-six-files-and-the-next-fidelity-search-should-arbitrate-it`**

### opened by `hard-restart-frames-is-not-searchable`

- **`a-verify-can-be-internally-inconsistent-not-merely-stale`**
- **`hard-restart-sub-search-is-wasted-on-36-inert-files`**

### opened by `hard-restart-frames-per-song-option`

- **`regenerate-fidelity-after-the-hard-restart-option`** — 5_Title_Tunes' bytes moved (gate 0.4996 -> 0.7494), so docs/FIDELITY.md and build/fidelity.json are stale against HEAD. docs/SURVEY.md and SUBTUNES.md too if that file's row counts changed. [main], the once-after regeneration.

### opened by `hard-restart-frames-vs-the-original-gap`

- **`hard-restart-want-needs-a-per-song-lever`** — `want` is HARD_RESTART_FRAMES * multiplier and nothing else, so a single-speed file whose player releases for 4 frames cannot ask for more than 2. Measured on 5_Title_Tunes: reaching the row's ceiling of 3 takes gate 0.4996 -> 0.7494 with melody, seq, pitch and wave all unchanged. Add an opt-in convert() option that sets the hard-restart frame count per song, in all three places, then let the search find it. [main], touches python/h2g/goatwriter.py, python/h2g/cli.py, python/h2g/convert.py, python/presets.py and presets.json.

### opened by `hold-zero-note-length-loss`

- **`wait0-tie-scoped-to-envelope-cut`**

### opened by `i-ball-is-the-only-file-with-bit40-true-and-no-per-record-effect-byte-and-it-is-relocated`

- **`effect-byte-address-inverts-only-the-naive-branch-of-to-offset-and-i-ball-needs-the-relocated-one`**

### opened by `i-ball-should-adopt-sfx-drum-and-the-search-must-decide-it-not-a-hand-edit`

- **`four-pitch-seq-adoptions-were-dropped-by-the-search-and-may-have-been-human-decisions`**
- **`shard-help-claims-a-5x-speedup-and-six-parallel-shards-measure-2-8x`**

### opened by `ik-plus-voice-2-strikes-222-attacks-against-the-originals-481`

- **`a-detection-fix-behind-an-opt-in-option-lands-inert-and-needs-a-paired-search-task`**
- **`diagnosis-tasks-get-touches-scoped-to-the-symptom-not-to-where-the-mechanism-could-live`**
- **`ik-plus-instruments-8-and-9-emit-wavetable-01-a-gate-with-no-waveform-bit`**
- **`ik-plus-should-adopt-sfx-drum-and-the-search-must-decide-it`**
- **`ricochet-has-effect-bit80-sfx-and-neither-drum-spelling-matches-it`**
- **`sfx-drum-signature-cannot-see-a-player-that-writes-its-sid-registers-through-a-ram-shadow`**

### opened by `ilv-83-arpeggio-needs-instrument-clones-or-cmd-setwaveptr-and-the-two-routes-should-be-costed`

- **`depth-is-a-fourth-column-absent-from-fidelity-json`**

### opened by `initial-for-ignores-compact-instruments-and-is-off-by-one-on-every-song`

- **`apply-initial-instruments-docstring-says-initial-for-rejects-zero-and-it-does-not`**
- **`initial-for-task-touches-omits-convert-py-so-the-fix-cannot-reach-anything`**

### opened by `initial-instrument-voice-2-collapse-is-not-the-selected-instrument`

- **`a-byte-hash-over-preset-options-does-not-bound-reach-over-forced-options`**

### opened by `international-karate-voices-never-set-an-instrument`

- **`claude-md-international-karate-instrument-claim-is-false`**

### opened by `kings-of-the-beach-ingame-loses-the-most-aud-and-sat-at-the-old-search-bound`

- **`kings-of-the-beach-ingame-aud-is-0-657-and-the-window-explains-only-its-movement`**
- **`sound-pys-narrow-window-census-comment-reads-7-of-89-and-is-now-5`**

### opened by `length-rule-needs-a-longer-window-than-the-report-uses`

- **`las-vegas-and-samantha-fox-end-20-seconds-early`** — the length probe's first find. Las_Vegas_Video_Poker reads len -20.9s and Samantha_Fox_Strip_Poker -18.0s -- our conversion STOPS about 20 seconds before the original does, the opposite direction from the loop-forever defect silent_park fixed. Candidates: a track ending on $FE early, a subtune whose orderlist is truncated, or silent_park parking a track that had more to play. Both files are outside the 12 refused, so they convert. [main], touches python/h2g/tracks.py, python/h2g/patterns.py, python/tests/test_legal_restart.py.

### opened by `listen-pairs-by-identity-by-coincidence`

- **`listen-pair-fallback-design-rationale-unrecorded`** — the agent was asked to argue between (a) loading build/fidelity.json for matched_subtune and (b) merely stating the identity assumption in LISTENING.md, and to say why. It implemented (a) plus part of (b) but recorded no rationale, so the coupling of staging to a hazard artefact another lane rebuilds was never justified in writing. Read the diff and record the reason, or reconsider it. [main], doc or revert.

### opened by `lock-records-with-a-null-pid-cannot-be-reaped-by-the-pid-rule`

- **`orphaned-tail-processes-survive-their-sessions`**

### opened by `measure-does-not-copy-the-new-drift-knee-fields-into-the-row-so-they-reach-no-artefact`

- **`other-hand-listed-key-sets-in-measure-may-have-fallen-behind-the-same-way`**

### opened by `measure-geoff-capes-strongman-challenge`

- **`cut-release-costs-adsr-on-release-heavy-tunes`** — `cut_release` sits in presets.json's `always` block and costs Geoff Capes 0.8147 -> 0.1211 adsr in a measured ablation (1752 of 2220 disagreeing frames are orig R=$F against our R=$0); census which corpus files are dominated by long-release records in their window before anyone decides whether the option's population is the right one.
- **`fetch-minus-one-shows-up-in-three-columns`** — the next-note `fetch` -1 is the single cause of Geoff Capes' hold 0% (4/4 instruments, delta -1, slot_delta 0), nrun 50% ($0A09's modal noise run 12 -> 11 while $050A matches exactly) and noise 284/308; worth measuring as one mechanism with three readings rather than as three rows of the defect queue.
- **`vibrato-rate-and-depth-are-one-mechanism-not-two`** — Geoff Capes reads vib 0.7425x with depth 1.3524x and the vib census names zero absent and zero slow instruments, so our vibrato is slower and correspondingly wider (product 1.0042); verify the coupling on a second file whose vibrato options are already enabled before either column is tuned, since Goattracker integrates its vibrato speed and a change to the rate moves both.

### opened by `measure-kings-of-the-beach-ingame`

- **`hold-column-single-instrument-slot-mode-artefact`**
- **`wave-column-charges-latched-waveform-after-tune-end`**

### opened by `measure-knucklebusters`

- **`knucklebusters-atkpitch-instrument-12-slow`**
- **`knucklebusters-bend-depth-step-size-unattributed`**
- **`knucklebusters-cutoff-overtravel`**
- **`knucklebusters-gate-short-releases-voice2`**
- **`knucklebusters-length-shortfall-four-seconds`**
- **`knucklebusters-pitchseq-instrument-26-absent`**
- **`knucklebusters-release-tail-one-instrument`**
- **`knucklebusters-voice1-four-surplus-attacks`**

### opened by `measure-las-vegas-video-poker`

- **`lvvp-adsr-note-end-envelope-kill`**
- **`lvvp-adsr-release-nibble-emitted-zero`**
- **`lvvp-pulse-set-only-program-25-of-25`**
- **`lvvp-vib-excess-pitch-write-rate`**
- **`lvvp-voice2-slides-bend-shortfall`**

### opened by `measure-samantha-fox-strip-poker`

- **`emit-note-end-envelope-kill-samantha-fox`**
- **`pulse-table-emits-no-modulation-entry`**
- **`unemitted-envelope-record-0f9f-samantha-fox`**

### opened by `measure-sanxion`

- **`filter-sweep-unbounded-step-count`**
- **`nrun-modal-length-blindness`**
- **`sanxion-drum-burst-fragmentation`**
- **`sanxion-missing-slide-frames`**
- **`sanxion-voice0-pulse-phase-collapse`**
- **`sanxion-voice1-adsr-deficit`**
- **`sanxion-voice2-note-naming`**
- **`sanxion-voice2-pulse-span-overshoot`**

### opened by `measure-sigma-seven`

- **`atkpitch-effect-40-sweep-not-emitted`**
- **`gate-release-two-frames-against-players-three`**
- **`pspan-file-level-hides-per-voice-cancellation`**
- **`pulse-phase-absent-from-sigma-seven-preset`**
- **`sigma-seven-filter-routine-unread-by-detect`**
- **`startup-lag-is-the-files-rarest-attack-offset`**

### opened by `mega-apocalypse-instrument-66-may-be-an-unmasked-effect-bit-rather-than-a-record`

- **`songview-patterns-are-flat-byte-lists-and-three-probes-have-now-mis-read-them`**

### opened by `melody-can-punish-a-pitch-that-moved-closer-to-the-original`

- **`a-dimension-description-edit-makes-fidelity-md-stale-mechanically`**

### opened by `monty-drums-play-four-octaves-too-low`

- **`claude-md-wave-program-population-is-9-multispeed-and-12-single-speed-not-8-and-13`**
- **`emitter-tasks-in-this-plan-cannot-ship-because-their-touches-omit-the-fidelity-artefacts`**
- **`monty-drum-cluster-steps-come-from-an-unidentified-emitter-not-the-wave-program`**
- **`monty-voice-1-drum-variation-is-a-linear-frequency-offset-not-a-note-transposition`**
- **`monty-voice-1-noise-attribution-to-an-instrument-is-not-done`**
- **`monty-voice-1-noise-is-a-fifth-high-and-joins-the-12604-group`**
- **`wave-program-travel-entry-is-refused-at-s1-which-is-what-blocks-monty`**
- **`whattask-verify-named-voice-1-where-the-defect-is-voice-2`**

### opened by `multi-engine-sid-one-player-assumption`

- **`engine-index-multi-emit`**
- **`multi-engine-scope-decision`**

### opened by `naming-share-decomposition-should-be-a-fidelity-census-flag`

- **`naming-share-is-method-dependent-not-just-the-rename-count`**

### opened by `nemesis-warlock-wave-program-bend-regression`

- **`bend-dimension-docstring-same-mechanism-caveat`** — bend Dimension docstring should state the ratio is only a ranking when both sides' pitch movement is the same mechanism -- Nemesis is a second instance of the drum-sweep caveat already in CLAUDE.md, in the opposite direction. [main]
- **`fidelity-window-census-flag`** — promote scratchpad/corpus_inprogram.py (splits bend into in-mechanism-window vs outside) into fidelity.py, e.g. --window-census. [subagent]
- **`nemesis-slide-travel-primary-testfile`** — wave-program-slide-travel-as-portadown should use Nemesis_the_Warlock as its primary test file -- 6 gated wave-program records (1,3,6,8,11,12), 3 all-slide, corpus-largest operands ($0C20,$0480,$0395). [subagent]
- **`shockway-rider-inprogram-bend-direction-check`** — Shockway_Rider moves slightly AWAY on the in-program bend split (17->12 frames vs original 21; 336->208 units vs 2031) -- confirm whether this reaches its FIDELITY.md slides row or is absorbed, to verify the only-Nemesis-moved claim is exact. [subagent]
- **`wave-note-base-mutes-continuous-effect-doc`** — undocumented general mechanism -- a WAVE_NOTE_BASE wavetable entry also mutes the pattern's continuous effect (vibrato/portamento/toneporta) for its frame. Belongs beside the WAVE_NOTE_BASE/WAVE_NOTE_KEEP constants in goatwriter.py and in CLAUDE.md. [subagent]

### opened by `nineteen-tie-spelling-melody-loss`

- **`boundary-tie-corpus-wide-residual-check`** — _apply_boundary_ties moves 30 corpus files per test_wait0_tie.py's own docstring; only Nineteen's effect has been read note-by-note. A per-file A/B at -t 60 (pass wrapped on/off, compare melody/seq/retrig/onset) would say whether any other file carries the same untied-row-0 residual shape. Confined to a fidelity A/B, no artefact writes. [subagent]
- **`effect-bit08-moves-bytes-no-dimension-sees`** — this run's probe shows effect bit $08 (c0ee1a5) moving Nineteen's converted bytes while moving zero digits of melody/seq/retrig/pitch -- the 'no dimension this report measures can see this change' signature. Run fidelity.py --baseline over the 21 files/80 records carrying bit $08 to establish whether the emitter is measurable anywhere at all. [subagent]
- **`hard-restart-budget-lost-its-motivating-file`** — hard-restart-budget-three-call-row's motivating file (Nineteen) now measures exactly correct with the boundary tie in place (voice 0: 69/69 attacks); removing the budget two independent ways overshoots to 70 and costs melody. Needs a new motivating file from the 38-file census in tests/test_row_budget.py before any corpus A/B is spent on it. [main]
- **`hard-restart-budget-three-call-row`**
- **`melody-collapsed-ratio-mis-orders-a-shorter-truer-sequence`**
- **`melody-collapsed-ratio-needs-re-derivation-or-closure`** — the open item melody-collapsed-ratio-mis-orders-a-shorter-truer-sequence rests entirely on Nineteen evidence this run refutes -- with _apply_boundary_ties present the shorter truer voice-0 sequence is also the higher-scoring one (26 vs 36 collapsed notes, melody 0.980 vs 0.525). Close the item or re-derive it from a file where the paradox actually survives. [main]

### opened by `no-hard-restart-moves-bytes-and-no-column-can-see-it`

- **`wide-hard-restart-is-inert-under-max-hard-restart-and-the-walk-could-skip-it`**

### opened by `note-end-envelope-zero-for-adsr`

- **`five-title-tunes-adsr-is-half-the-gate-task`** — 1873 of the 3743 adsr-disagreeing frames are exactly the frames counted by gate_ours_ringing. Any movement on hard-restart-frames-vs-the-original-gap will move `adsr` by the same frames, so the two columns must not be read as independent evidence when that task is A/B'd -- and its verify should expect adsr to move with gate. [main], no code change, a note on the sibling task's verify.

### opened by `note-freq-extrapolates-past-the-16-bit-ceiling`

- **`freq-table-index-wraps-at-8-bit-asl-for-the-four-bit-40-records`**

### opened by `one-on-one-two-voice-drift-fit-differs-tenfold-between-sixty-and-one-eighty-seconds`

- **`one-on-one-regrid-sawtooth-drift-confirm-against-pattern-boundaries`**

### opened by `orderlist-silent-park-for-fe`

- **`regenerate-presets-json-for-silent-park`** — `silent_park` is in convert(), cli.py and presets.FIXED, and reaches zero songs because presets.json's `always` block predates it -- tests/test_preset_passthrough.py SKIPS with exactly that message rather than failing, which is correct but means the suite stays green on a dead feature. Regenerating presets.json turns it on for the 29 files that carry $FE and fixes the length rule on all of them (Action Biker 856 attacks -> 291 over 180s). MIND THE CARRY-FORWARD: a plain run is keyed on FIDELITY_TOGGLES, a boolean walk, and will drop 5_Title_Tunes' measured `hard_restart_frames: 4` -- verify that entry survives before adopting the output. Then regenerate docs/FIDELITY.md and build/fidelity.json, where `len` should move on Kings of the Beach and Geoff Capes. [main], touches presets.json, docs/FIDELITY.md, build/fidelity.json.
- **`silent-park-costs-a-pattern-slot-on-files-near-the-limit`** — parking appends one pattern and one orderlist position per song. The orderlist side is guarded (a track at MAX_TRACK_LEN falls back to restart 0, tested), but the PATTERN side is not: nothing checks MAX_PATTERNS before appending SILENT_PATTERN. No corpus file hits it today -- all 29 movers convert and the byte-hash is clean -- but `_pulse_layout` and `_tie_step` both carry explicit table-full branches for the same reason, and this one does not. [subagent], touches python/h2g/tracks.py and python/tests/test_tracks.py.

### opened by `pace-rule-in-claude-md-contradicts-fidelity-paces-own-docstring`

- **`bold-parity-gate-asserts-absolute-parity-with-no-baseline-so-it-cannot-see-a-pre-existing-odd-count`**
- **`fidelity-paces-docstring-cites-an-ace-ii-example-that-no-longer-reproduces`**

### opened by `pending-tie-across-pattern-boundaries`

- **`presets-and-fidelity-regen-after-boundary-tie`**

### opened by `phantom-subtunes-nemesis-thundercats`

- **`claudemd-track-table-extent-reach-overstated`** — CLAUDE.md's three-bounds bullet credits track_table_extent with '22 files, 204 subtunes', but switching it off changes converted bytes on only 12 files -- on the other ~10, the trailing-run playability trim in tracks.convert_tracks already dropped the same surplus subtunes, so the extent is redundant there. Measure the per-file split and reword the bullet plus SUBTUNES.md's by-cause framing in survey.py. [subagent]
- **`default-path-byte-identity-unpinned`** — the converter is byte-identical between v0.5.341 (b327970) and v0.5.357 on all 80 corpus files that convert at bare defaults, while 64 of 83 move under presets.json -- fifty commits are entirely option-gated. Currently unpinned; a test like test_engine_zero_is_byte_identical_across_the_corpus (hash the default path against a committed manifest) would catch a future accidental default-path regression instead of relying on a hand-rolled probe. [subagent]
- **`phantom-subtunes-dod-wording-wrong`** — the queue entry states the byte-hash names only Nemesis_the_Warlock and Thundercats; the real reach of tracks.track_table_extent is 12 files (Commando, Commodore_64_Music_Examples, Delta_Mix-E-Load_loader, Gremlins, Last_V8, Last_V8_C128_version, Mega_Apocalypse, Monty_on_the_Run, Nemesis_the_Warlock, One_Man_and_his_Droid, Rasputin, Thundercats), matching b327970's own commit message. Correct the wording so a future agent doesn't re-run this exact refutation. [main]
- **`phantom-subtunes-verify-names-the-wrong-bound`**
- **`three-files-only-convert-under-presets`** — Delta, Dragons_Lair_Part_II and W_A_R raise at bare defaults but convert under presets.json's options, explaining the 80/15 vs 83/12 split. Undocumented which option rescues each; pin the per-file reason so a probe's success-rate assertion has a known-good baseline. [subagent]

### opened by `pitchseq-detect-shape-gap`

- **`kings-of-the-beach-pitchseq-static-table`** — Kings_of_the_Beach_intro's bit-$10 sequence is a STATIC GLOBAL table ($126B = note,+12,+24) with no per-instrument index array and no pair copy -- goatwriter._pitch_seq_notes computes pair=pairs+2*data[index+i*stride] and has no way to express 'no index, read base+1/base+2 directly'. Needs either a PitchSeq.static flag the writer honours, or _pitch_seq_notes accepting pairs=None. 475 of VIBRATO.md's cited 2943 reversals. [subagent] touches detect.py + goatwriter.py + tests, verified by corpus byte-hash naming only this file.
- **`vibratomd-pitchseq-census-misattribution`** — fidelity.py's _effect_meanings sets out[0x10]='pitchseq' with NO detection gate (every other cause in that function is gated), and VIB_CAUSE_ORDER ranks $10 first -- so International_Karate (x2 records) and Formula_1_Simulator, whose players contain no AND #$10 at all and read the byte's high nibble as bit $04's arpeggio depth, are filed under pitchseq instead of arp. 2331 of the task's cited 2943 reversals (79%) is this misattribution, not a detection gap. Fix: gate out[0x10] on det.pitch_seq is not None. [subagent] for the code change in fidelity.py, [main] to regenerate VIBRATO.md afterward.

### opened by `plan-audit-check-f-cannot-tell-a-graded-sha-from-an-ungraded-one`

- **`plan-audit-check-f-reports-but-cannot-gate-because-it-never-reaches-the-findings-count`**

### opened by `plays-something-else-diagnose`

- **`subtune-correspondence-rows`**

### opened by `powerplay-cue-length`

- **`original-ended-five-second-floor`**
- **`outer-gate-nearest-table`**

### opened by `powerplay-cue-melody-residual`

- **`fidelity-cue-subtune-offbyone`** — our .sng subtune o_k is the original's PSID subtune k+1 ($4200 dispatches CMP #$00 -> tune, SBC #$01 -> cue A-1), so `fidelity.py -a N` on this file at engine=1 compares cue N-1 against cue N. With the tuning corrected the matrix is a clean off-diagonal band s(k+1)->o(k) at 63-83% against identity readings of 0-41%. SUBTUNE_REMAP has no entry; --diagnose sees only s1->o0 at its 50% threshold. [subagent], touches python/fidelity.py, python/tests/.
- **`fix-7kkkkk-measurement-provenance`** — § 7.kkkkk's per-cue melody table (mean 75%) was taken at -t 12 AND without the frequency-table calibration -- the § 7.mmmmm trap, which for the cue engine is accidentally the right answer. Traces on $3A36 and traces with no calibration are identical on all nine cues. The table needs both facts recorded, or it will keep reading as a contradiction of the harness's 1%/18%. [main], touches H2G-CONVERSION-METHOD.md.

### opened by `powerplay-naming-share-must-be-re-measured-on-the-frame-axis-before-the-user-decides`

- **`a-verify-may-not-require-an-edit-to-whattask-json-because-runtask-is-forbidden-to-make-one`**

### opened by `powerplay-vibrato-rate-still-two-thirds`

- **`never-git-stash-in-a-multiworktree-fanout`**
- **`recover-worktree-4-fidelity-stash-acbba6ef`**
- **`vibrato-tick0-skip-lfo-and-triangle-engines`**

### opened by `powerplay-vibrato-refusals`

- **`powerplay-vibrato-md-regen-at-merge`**

### opened by `promote-pulse-phase-into-fidelity-toggles-once-the-multiplier-gate-is-settled`

- **`promote-pulse-phase-has-no-depends-on-for-the-gate-its-own-title-names`**
- **`the-multispeed-pulse-phase-player-has-never-been-measured-and-gates-49-songs`**
- **`the-seven-declined-vbi-pulse-phase-carriers-have-an-unread-second-cause`**

### opened by `pulse-free-run-via-zero-pulse-pointer`

- **`human-race-voice0-is-the-other-free-run-candidate`** — the census named 5_Title_Tunes voice 2 and Human_Race voice 0 as the only two voices a free-running pulse would help. Both are now documented as knowingly approximated. If either ever gets a listening complaint about a static-sounding duty cycle, this is the cause and the repair is known -- worth recording against those two files rather than rediscovering it. [subagent], doc only.
- **`plan-declares-python-h2g-as-a-whole-directory`** — nine tasks carry `r:python/h2g`, so any task writing goatwriter.py or sidfile.py serialises against all of them -- 0 of 27 delegable x main pairs could coexist this cycle and the fan-out lane sat idle. Narrow the reads to the files actually consulted (detect.py, goatwriter.py, patterns.py, tracks.py) at the next /whattask. This is the 'out/ is not one resource' rule and it is costing whole cycles. [main], touches .claude/tasks/whattask.json.

### opened by `pulse-phase-is-inert-on-the-rest-of-its-engine-and-nobody-knows-which-gate-declines-it`

- **`a-read-only-task-cannot-record-its-own-finding-and-four-have-now-hit-that`**

### opened by `pulse-phase-via-setpulseptr-per-note`

- **`pulse-phase-verify-has-no-decline-branch`** — the verify string for pulse-phase-via-setpulseptr-per-note asserts the repair is cheap ('computable at emit time ... no new player state') and lists only a DONE-WHEN, so a measurement showing the cost is unacceptable cannot satisfy it. The missing cost is that a pulse pointer belongs to the orderlist POSITION while Goattracker's patterns are global, so a pattern entered at k phases needs k copies. Rewrite the clause to admit a costed decline. General form: a verify that names only a success condition cannot record a refutation, and this repo's most valuable outcomes are refutations. [main], plan edit.

### opened by `pulse-triangle-docstring-says-the-band-carries-over-and-it-does-not`

- **`a-verify-that-runs-a-byte-hash-must-declare-a-scratch-path-in-touches`**

### opened by `pygmies-revenge-gate-falls-against-the-flags-own-direction`

- **`pygmies-revenge-startup-lag-wrong-by-16-frames`** — Pygmies_Revenge's startup_lag reads 21 where the packed player's real init delay is 5 (corroborated by both non-lagging voices' gate rises and adsr hitting exactly 100.0% at lag 5), costing its FIDELITY.md row 16pp wave / 26pp adsr / 16pp gate. Cause: the estimator takes min-over-voices independently per side, and our voice 1's first note is one 16-frame row late, outvoting the other two voices. Two separable questions: is voice 1 genuinely a row late (a converter defect, python/h2g), or should one voice's difference be allowed to set the whole file's alignment (a harness question, python/fidelity.py). [main], needs a decision on which question to chase first.
- **`startup-lag-perturbed-by-no-test-restart`** — --no-test-restart deletes the sub-$10 frame siddump needs to name an attack, so our first named attack moves one frame earlier while the gate edge does not, and startup_lag drops by exactly 1 on every file checked (3 of 3). Every per-frame column (gate, wave, adsr, hold, onset) then gets A/B'd at two different alignments -- Delta's 32.5->84.2% gate 'gain' is 100% this artefact. Candidate fixes: estimate lag from the first GATE RISE instead of siddump's named attack (flag-invariant, verified), or hold the baseline's lag when A/Bing an option. [main] touches python/fidelity.py only; verify by re-running the three files' sweeps and requiring both variants compared at one lag.

### opened by `raising-the-fidelity-window-to-180-needs-a-task-that-declares-both-artefacts`

- **`claude-mds-60-second-figures-need-grading-now-that-the-window-is-180`**
- **`commit-the-drains-pending-converter-work-and-regenerate-both-artefacts-before-any-window-change`**
- **`test-preset-passthrough-pins-the-search-window-at-60-and-must-follow-to-180`**
- **`the-sound-render-cache-is-keyed-on-the-window-so-a-window-change-costs-13x`**

### opened by `rebuild-build-instrmap`

- **`instrmap-rebuild-should-say-what-it-cached`** — the expensive --instrmap half completed and the cheap page half did not, but nothing in the output distinguished the two phases, so the natural recovery would have been to re-run --instrmap and pay for 83 tunes x 2 emulations again. A line naming which phase finished would make the cheap recovery obvious. [subagent], touches python/abpage.py.
- **`instrmap-staleness-test-is-a-count-and-should-be-a-sha`** — the task asserted 168 files is stale because the corpus has 83 tunes, but 168 = 2 x 84 and the dumps are plausibly two files per tune plus an index pair. A count is the wrong staleness test either way -- the right one is each dump's .sng sha against a fresh convert(), which is what listen.py's provenance check already does for audio. Settle the file-per-tune question before any rebuild. [subagent], touches build/instrmap and r:python/songview.py.
- **`orchestrator-must-read-agent-record-content-not-just-its-id`** — a returned record with evidence/verify_output/notes all equal to 'test' passed id equality and claimed outcome done. The runqueue's documented defence is id equality plus re-verifying numbers that matter; neither catches a record with NO numbers. Add an explicit check that evidence and verify_output are substantive before accepting any outcome. [plan/command edit].
- **`rebuild-build-instrmap-verify-asserts-a-false-premise`** — the plan's verify reads 'the count matches the 83 convertible corpus files rather than 168', which is unsatisfiable because 168 IS correct (83 x 2 + an index pair). A verify that encodes a wrong premise cannot be met by correct work, and the first attempt's stub is the shape of what that invites. Same class as whats-next-md-verify-names-an-undeclared-path from cycle 1: TWO of this plan's fifteen verify strings could not be satisfied as written. [plan edit].

### opened by `rebuild-build-instrmap-which-predates-the-conversion-changes-it-documents`

- **`instrmap-rebuild-is-scoped-to-staged-tunes-so-the-six-new-files-need-a-restage-first`**
- **`whattask-touches-must-cover-a-sibling-file-that-differs-only-by-extension`**

### opened by `redispatch-three-read-only-with-ids-stated`

- **`agent-schema-opened-field-returns-file-paths`** — all three cycle-2 agents (and the cycle-1 four) filled `opened` with the file paths they read rather than with new task ids. The schema says items:string and is satisfied either way, so nothing catches it. The dispatch prompt should state what `opened` is for, exactly as it now states the id. [main], a prompt fix in the runner.

### opened by `regenerate-artefacts-after-the-monty-firstwave`

- **`per-instrument-gatetimer`** — `_write_instruments` computes ONE gatetimer from the file's shortest row, so a file whose subtunes run tempos [3,4,5] caps every instrument at 2 ticks even where an instrument sounds only in tempo-4/5 subtunes that could afford 3. Monty's gate is 48% with a derived ceiling of 2/3 of the original's release; the emitter already receives note_rows (median played durations) and instr_voices, so a per-instrument bound is computable. The risk is an instrument shared across subtunes of different tempos -- the bound must be the MINIMUM over the rows that instrument actually plays, and the 5TT force-test (gatetimer >= row kills the song, 938 attacks -> 3) is the failure mode to test against. [main], touches python/h2g/goatwriter.py, python/h2g/convert.py, python/tests/test_hard_restart.py.

### opened by `regenerate-fidelity-artefacts-at-v0-5-459`

- **`the-180-second-report-is-58-minutes-cold-and-11m38s-warm-and-only-the-cold-figure-is-written-down`**
- **`the-fidelity-provenance-stamp-says-dirty-for-a-plan-file-that-cannot-change-a-number`**

### opened by `regenerate-the-fidelity-artefacts-on-the-clean-tree-at-v0-5-455`

- **`claude-md-says-the-fidelity-run-is-15m46s-and-a-warm-cache-run-is-5m08s-neither-labelled`**
- **`cov-says-three-files-are-fully-contained-at-60-seconds-where-claude-md-records-two`**
- **`kings-of-the-beach-ingame-loses-the-most-aud-and-is-the-file-that-sat-at-the-old-search-bound`**
- **`whattask-tasks-declare-the-scratch-root-so-all-57-serialise-on-scratch-alone`**

### opened by `regrid-and-no-test-restart-need-a-guard-or-a-documented-incompatibility`

- **`claude-md-cites-readme-sections-by-name-and-regrid-turned-out-not-to-exist`**

### opened by `regrid-could-be-searchable-from-repeated-attack-run-length-without-a-trace`

- **`ab-9-gate-asks-this-task-for-evidence-its-own-verify-never-required`**
- **`go-go-dash-is-not-in-the-regrid-population-though-whats-next-files-it-there`**
- **`regrid-searchability-needs-a-one-sided-pitch-phase-trace-not-a-pattern-predictor`**

### opened by `regrid-makes-one-on-one-offsets-wander-so-drift-cannot-be-fitted`

- **`min-drift-coverage-is-a-count-gate-where-a-spread-gate-is-needed-one-on-one-v2-clears-it-at-046`**

### opened by `regrid-moves-bmx-kidz-bytes-without-moving-its-drift-at-all`

- **`regrid-over-supplies-bmx-kidz-by-about-five-times-and-only-a-short-window-hides-it`**

### opened by `regrid-over-supplies-a-subtune-whose-exclusive-patterns-replay`

- **`regrid-on-bmx-kidz-may-be-adoptable-now-that-the-over-supply-is-fixed`**
- **`six-regrid-adoptions-now-drift-more-and-want-re-deciding-at-t-180`**

### opened by `replacing-the-envelope-search-with-the-attack-lag-moves-aud-on-87-files`

- **`aud-and-loud-are-stale-on-87-rows-after-the-alignment-change`**
- **`known-bad-may-be-defeated-by-the-alignment-refinement-re-run-it-against-v0-5-459`**
- **`the-align-refine-branch-shipped-untested-from-v0-5-455`**

### opened by `rest-envelope-four-both-half-losers`

- **`rest-envelope-losers-are-drift-not-a-rest-defect`** — on Bangkok_Knights, I_Ball, Ricochet and Skate_or_Die the --rest-envelope-silence `away` frames are pure displacement -- re-anchoring our envelope-zero runs onto the nearest original zero-run takes away from 605/257/254 to 3/0/0. The option is being charged for a pre-existing timing error. Decide whether that means (a) enable it corpus-wide and accept the adsr cost as drift's, or (b) gate it on a drift threshold. Needs a decision, then a corpus A/B. [main]

### opened by `rest-envelope-silence-is-unreachable-through-presets`

- **`ace-ii-rest-envelope-awaits-a-listen`** — ACE_II measures adsr 93->96 with nothing worse under rest_envelope_silence, but its human approval pins the no-flag bytes (sha 7bc6dfad). Adopting the flag invalidates the approval; the listener should decide whether +3 adsr is worth re-listening. [requires-user].

### opened by `rest-wave-silence-is-adopted-on-zero-songs-and-the-shared-schedule-makes-it-worth-re-searching`

- **`claude-md-still-records-rest-wave-silence-as-costing-43pp-of-melody-which-is-now-0-4pp`**
- **`fidelity-better-has-no-term-that-can-see-a-rest-parked-waveform-so-rest-wave-silence-is-unselectable`**
- **`rest-wave-silence-costs-slides-and-bend-together-on-exactly-five-wave-program-files`**

### opened by `restage-build-listen-audio`

- **`restage-cost-estimate-in-plans-was-30x-wrong`** — whattask.json called this 'hours of wall clock and ~28 GB' where it is ~20 min sharded and 6.9 GB. An untimed cost written into a plan is a planning input, and this one would have deferred the task indefinitely. Same shape as CLAUDE.md's note that presets.py --fidelity was quoted at 'about four hours' for forty versions and is 8 minutes. Time a cost before it decides anything. [main], doc only.

### opened by `retake-wave-alternate-noise-trade`

- **`chicken-song-baseline-wave-moved-unexplained`** — Chicken_Song's baseline wave score (no dialect emitted) moved from 77% (v0.5.232, fb787fd) to 84.1% (current tree) for a reason unrelated to bit $02's dialect -- not chased down. Find what changed between fb787fd and 73354bd that affects this file's wave agreement; check whether it's a real fix or a harness artifact (same caution as the startup_lag findings from cycle 2 of this session). [subagent]
- **`retake-wave-alternate-post-emission-numbers`** — build a scratch monkeypatch (or temporary emitter, following the existing pattern of wiring det.wave_alternate_noise the way det.wave_alternate is already wired) to actually emit bit $02's derived noise dialect, and re-measure Chicken_Song and Hollywood_or_Bust's post-emission wave/noise/nrun/onset numbers against the current tree -- the old 84/919/100/86 and 100/1496/100 figures predate an unrelated baseline shift and cannot be trusted. [subagent] needs rw:python/h2g/goatwriter.py.

### opened by `reversal-ratio-may-be-nonlinear-in-oscillation-rate`

- **`vib-figures-are-step-quantised-reread-past-decisions`**

### opened by `rikky-immunity-to-regrid-is-unexplained`

- **`one-on-one-121-renames-away-from-a-lengthened-row-may-be-the-mid-glide-population`**
- **`powerplay-naming-share-is-67-percent-not-the-94-the-adoption-task-quotes`**
- **`regrid-breaks-the-double-strike-pairing-on-one-on-one-voice-2`**
- **`regrid-docstring-says-six-files-and-never-voice-0-both-wrong`**
- **`seventy-six-one-on-one-renames-have-neither-a-lengthened-gap-nor-a-moving-pitch`**
- **`the-selection-rule-steers-every-iteration-into-the-task-with-most-inbound-edges`**
- **`the-two-channel-regrid-split-rests-on-difflib-rename-counts-that-undercount-37x`**

### opened by `robs-life-no-signature`

- **`25-unreachable-tunes-count-needs-reducing-by-3`** — the '25 unreachable tunes' task in whattask.json counts Robs_Life's 3 subtunes among tunes that must eventually emit a .sng; since Robs_Life is SidTracker64 (permanently out of reach for a signature-based Hubbard ripper), that target should read 22 tunes (C64ME 14, One_on_One 3, 5_Title_Tunes 4, Sanxion 1). [main] whattask.json edit.
- **`dis6502-needs-a-compare-mode`** — the operand-masked opcode comparison that settled this had to be hand-written inline -- the third such ad-hoc probe in this repo's history. A `dis6502.py --compare other.sid --at $X -n N` mode would turn 'is this the same player relocated?' into one command. [subagent], extends tests/test_dis6502.py.
- **`find-music-subtunes-docstring-overclaims`** — its docstring says 'every other player in the corpus reaches its music init unconditionally', which Robs_Life falsifies (a 3-way self-modifying selector). No Hubbard file uses that idiom so nothing needs implementing, but the docstring should say 'every Hubbard player'. [subagent], one-line fix.
- **`sidtracker64-scope-decision`** — 5 corpus files (Casio_Extended, Dont_Step_on_My_Wire, Era_of_Eidolon, Robs_Life, Task_Force) are SidTracker64 and permanently unreachable by a signature-based Hubbard ripper. Whether they're ever in scope needs either a second ripper or an emulate-and-capture approach -- a project-scope decision only the user can make. [user]
- **`survey-py-should-cite-opcode-evidence`** — survey.py's out-of-scope prose names only the SIDId signature as the exclusion reason, which is why Robs_Life has been re-opened as a detection gap twice. Adding the opcode-identity evidence (929 instructions, 0 differences vs Casio_Extended.sid) would make SURVEY.md self-defending. Regenerating SURVEY.md is [main] work by the repo's own rule.

### opened by `runhuman-flips-mode-but-leaves-the-requires-user-verify-boilerplate-in-place`

- **`plan-audit-needs-a-check-g-for-a-done-condition-only-a-human-can-discharge`** — .claude/skills/plan-audit/plan_audit.py has checks A-F and none for a non-requires-user task whose verify asks for a person; it must CLASSIFY by cause, since a vocabulary grep reports 16 findings against 0 real ones on the plan at 665939c (12 ILV scope notes, 3 build/listen paths, 1 self-quotation). Needs rw:.claude/skills/plan-audit/plan_audit.py and r:.claude/tasks/whattask.json.

### opened by `search-subtunes-default-now-the-shim-is-empty`

- **`shifted-subtune-cause-is-not-yet-mechanically-separable`** — the rewritten line says the two causes cannot be told apart, which is honest but is a description of a gap. They ARE separable in principle -- a gt2reloc drop means our surviving subtune count is less than what we emitted, where a wrong-order defect leaves the count intact. The row already carries `subtune_shas` (our emitted count) but not the packed count, so the discriminator needs one more field. Adding it would turn a warning into a verdict. [subagent], touches python/fidelity.py and python/tests/test_fidelity.py.

### opened by `shipped-presets-carries-four-pitch-seq-yeses-and-five-max-hard-restart-noes-to-re-check`

- **`preset-disagreements-recorded-at-60-seconds-should-be-re-checked-before-being-queued-as-criterion-bugs`**

### opened by `sidfile-has-no-to-address-so-every-caller-hand-inverts-to-offset`

- **`find-outer-gate-inverts-to-offset-naively-and-returns-none-for-i-ball`**
- **`test-vibrato-two-players-carries-the-eleventh-hand-inversion-and-is-not-granted`**
- **`two-inversion-sites-in-goatwriter-are-invisible-to-a-grep-for-hlen`**

### opened by `sigma-seven-and-wiz-lose-half-their-hold-agreement-under-the-regrid-fix`

- **`hold-counts-slot-and-sparse-as-misses-while-its-own-census-calls-them-non-defects`**
- **`tasks-keyed-on-hold-retrig-or-tail-cannot-read-them-from-build-fidelity-json`**

### opened by `six-regrid-adoptions-drift-more-at-180-seconds-and-want-re-deciding`

- **`bmx-kidz-regrid-over-supply-is-halved-to-23-59-and-still-refused`**
- **`claude-md-still-lists-one-on-one-as-a-regrid-refusal-and-says-13-adoptions`**
- **`every-task-granted-r-siddump-exe-needs-r-fidelity-py-and-r-h2g-to-use-it`**
- **`one-on-one-regrid-refusal-rests-on-a-melody-collapse-that-no-longer-happens`**

### opened by `skate-or-die-row-is-5-halves-not-3`

- **`claude-md-pal-ntsc-gate-is-no-longer-a-hypothesis`**

### opened by `song-knucklebusters`

- **`per-subtune-multiplier-conflict`**

### opened by `songspeeds-skip-reads-past-its-table`

- **`songspeeds-frames-table-bleed-into-skip-table-uncaught`**

### opened by `sound-calibration-known-bad-check-fails-on-two-of-three-pairs`

- **`known-bad-pairs-two-of-three-have-a-good-build-that-stops-at-30-seconds`**
- **`the-calibration-now-validates-on-one-pair-and-wants-two-more-that-build-comparably`**

### opened by `staleness-guard-on-staged-output`

- **`instrmap-pages-will-need-regenerating-after-any-restage`** — the banner is baked into the HTML at page-build time, so pages built before a restage will claim 'behind' after the audio has been brought current. Whichever of the two rebuild tasks runs first, abpage must run again after the other. [main].
- **`seventy-seven-of-eighty-three-staged-tunes-play-an-older-conversion`** — the guard's first corpus reading is that 93% of the staged listening set is behind the shipping converter, six files aside. That is the measurement restage-build-listen-audio exists to fix, and it is now visible on every page rather than having to be inferred from mtimes. [main], already tasked.
- **`verify-clause-conflated-approval-sha-with-staged-audio-sha`** — whattask.json's verify for this task asserts the banner must not appear on ACE_II 'whose sha is unchanged'. Two shas exist and only one is unchanged -- the approval's (7bc6dfad, equal to today's conversion) against the staged audio's (b70c156b, an older conversion). Any future task text about staleness should name WHICH sha. [main], doc/plan wording only.

### opened by `sun-never-shines-and-lion-heart-voice-0-undershoot-by-fifty-and-forty-four-attacks`

- **`lion-hearts-voice-0-shifts-eighty-notes-from-the-five-gap-to-the-eleven-gap`**
- **`sun-never-shines-voice-0-needs-a-five-frame-row-and-its-voice-1-needs-fewer-notes`**
- **`sun-never-shines-voice-1-invents-210-attacks-against-an-original-that-holds`**

### opened by `survey-md-reports-86-converted-without-saying-on-which-options`

- **`survey-py-build-report-is-the-only-artefact-writer-with-no-test-until-now-check-the-others`**
- **`whattask-emitted-a-task-with-mode-subtask-and-needs-main-true-which-cannot-both-hold`**

### opened by `survey-py-build-report-is-the-only-artefact-writer-with-a-test-check-the-others`

- **`a-test-file-named-for-a-function-is-not-a-test-of-it-subtune-census-is-the-case`**
- **`build-subtune-census-computes-five-published-figures-and-has-no-test`**
- **`claude-md-says-the-subtunes-headline-is-unfixed-and-the-code-edit-was-made`**
- **`claude-mds-grading-rule-should-cover-claims-about-the-code-not-only-figures`**

### opened by `test-classic-vibrato-row-calls-compensation`

- **`extend-row-calls-compensation-to-lfo-triangle-engines`** — goatwriter.py's own docstring notes the packed player's tick-0 skip applies to every vibrato it runs, but only the classic ($78/$07) engine's cmp gets the row_calls compensation -- the LFO-table and global-triangle engines in _table_vibrato_entry are still uncorrected. Needs main-session work (changes converter output, needs corpus-wide fidelity re-measurement, touches SURVEY.md/presets.json/FIDELITY.md). [main]
- **`row-calls-should-be-mean-not-shortest-row`** — row_calls is taken from the file's shortest row (short_row_calls), exact on 44 of 55 classic-vibrato files but over-correcting the 11 that vary row length (worst: Warhawk, 8 vs 40 calls). Reaching the mean row over the calls vibrato actually runs for needs a new convert() argument and a corpus-wide re-measurement. [main]

### opened by `the-classic-dialect-instrument-mask-should-be-derived-from-the-stride-not-fixed-at-7f`

- **`an-out-of-range-instrument-number-was-doing-duty-as-a-mis-decode-alarm`**

### opened by `the-digi-decoders-slide-is-attached-to-one-row-and-not-to-its-hold-rows`

- **`build-fidelity-json-is-stale-for-five-digi-files-and-the-artefacts-are-owed-a-regeneration`**
- **`fold-test-digi-into-test-digi-engine-and-delete-the-duplicate-file`**

### opened by `the-envelope-and-attack-lag-estimators-disagree-by-more-than-a-frame-on-53-of-89-files`

- **`replacing-the-envelope-search-with-the-attack-lag-moves-aud-on-87-files-and-needs-its-own-ab`**
- **`sound-calibration-known-bad-check-fails-on-two-of-three-pairs-and-is-unrelated-to-lag`**

### opened by `the-fidelity-report-should-print-how-much-of-each-tune-its-window-contained`

- **`regenerate-fidelity-md-so-the-new-cov-column-actually-appears`**

### opened by `the-hold-column-and-the-sound-render-family-share-the-sound-run-prefix-and-are-unrelated`

- **`documenting-a-naming-collision-creates-one-and-a-counting-check-cannot-tell-them-apart`**

### opened by `the-ilv-arpeggio-steps-land-at-offsets-the-originals-do-not`

- **`the-three-files-that-abort-under-preset-opts-were-my-probe-passing-the-stem-not-a-repo-defect`**

### opened by `the-ilv-decoder-has-no-tie-parameter-and-drops-99-percent-of-the-originals-ties`

- **`fidelity-ties-and-the-tie-convert-option-share-a-word-and-mean-different-things`**
- **`ilv-duration-bit-5-is-isolated-by-the-player-into-a-cell-nothing-reads`**
- **`the-ilv-attack-surplus-is-unattributed-again-and-the-tie-metric-measures-pitch-movement`**

### opened by `the-ilv-filter-over-produces-on-pacific-coast-and-routes-all-three-voices`

- **`lion-hearts-original-holds-the-filter-through-unfiltered-notes-and-the-15b1-path-must-say-why`**
- **`the-ilv-filter-holds-the-circuit-in-for-two-to-five-times-the-originals-frames`**
- **`the-ilv-routing-clear-fits-three-of-the-six-files-and-wants-a-per-file-adoption`**

### opened by `the-interleaved-classic-dialect-emits-no-filter-at-all-on-any-of-its-six-files`

- **`filter-step-per-call-takes-an-8-bit-step-and-the-interleaved-engine-sweeps-16-bit`**
- **`io-open-wb-fails-with-oserror-22-on-this-machine-and-tmp-plus-os-replace-does-not`**
- **`pacific-coast-emits-1366-filter-frames-where-its-original-emits-none`**
- **`the-interleaved-filter-is-a-stride-8-table-indexed-by-instrument-byte-12-and-wants-one-reader-plus-one-emitter`**
- **`the-interleaved-filter-routes-all-three-voices-and-over-produces-on-single-instrument-files`**
- **`the-verify-allowed-emit-or-refuse-and-the-answer-was-neither-unimplemented-is-a-third-outcome`**

### opened by `the-interleaved-engines-vibrato-family-is-the-rest-of-its-missing-pitch-travel`

- **`arpeggio-is-undocumented-in-readme-because-the-task-could-not-write-it`**
- **`build-fidelity-json-is-one-row-stale-and-the-refresh-is-owed-for-the-whole-session`**
- **`ilv-83-is-a-semitone-arpeggio-and-would-need-the-wavetable-not-a-pattern-command`**
- **`ilv-87-filter-sweep-can-now-reuse-the-arpeggios-block-layout-and-index-remap`**
- **`ilv-87-is-a-filter-cutoff-sweep-and-needs-a-pattern-level-filter-route-in-goatwriter`**
- **`lakers-instrument-7-is-the-only-ilv-arpeggio-safe-to-bake-into-an-instrument`**
- **`the-ilv-arpeggio-wants-a-listen-before-any-per-song-adoption`**
- **`the-ilv-arpeggios-steps-land-at-offsets-the-originals-do-not-and-cost-27pp-of-melody`**
- **`the-interleaved-engines-missing-bend-travel-is-unlocated-and-is-not-83-86-or-87`**
- **`the-vibrato-tasks-touches-grant-fidelity-pys-outputs-but-not-fidelity-py`**

### opened by `the-pulse-phase-multiplier-gate-declines-eleven-files-and-has-never-been-measured-above-s1`

- **`game-killer-gains-pphase-0-64-to-0-91-and-is-blocked-only-by-rasputins-pack-failure`**
- **`promoting-pulse-phase-to-fidelity-toggles-must-not-happen-while-the-multiplier-gate-is-lifted`**
- **`rasputins-pulse-phase-plan-makes-59-pattern-copies-and-gt2reloc-refuses-the-result`**

### opened by `the-re-verified-live-list-in-claude-md-contains-at-least-three-stale-figures`

- **`claude-mds-graded-figures-are-mechanically-re-derivable-and-should-be-a-committed-check`**
- **`survey-md-reports-86-converted-without-saying-on-default-options-while-presets-convert-89`**

### opened by `the-seven-toggle-search-cost-is-forty-minutes-not-eighty-and-two-docs-say-otherwise`

- **`the-180-second-window-costs-75-minutes-of-search-not-24-and-that-cuts-against-raising-it`**

### opened by `the-shift-noise-floor-is-driven-by-devils-galop-and-whole-hop-alignment-and-may-halve-cheaply`

- **`docs-fidelity-md-carries-aud-and-loud-at-the-old-hop-and-wants-regenerating`**

### opened by `the-six-interleaved-classic-files-have-had-no-fidelity-search-only-structural-options`

- **`pacific-coast-no-test-restart-adoption-trades-melody-for-rendered-audio-and-wants-a-listen`**

### opened by `the-six-interleaved-presets-must-be-re-searched-after-the-instr-used-stride-fix`

- **`four-of-the-six-interleaved-classic-files-emit-zero-filter-frames-not-just-go-go-dash`**

### opened by `the-two-incomparable-known-bad-pairs-need-retiring-or-replacing-and-that-is-a-coverage-decision`

- **`the-all-seen-filter-needs-an-any-comparable-guard-or-an-all-excluded-suite-passes-vacuously`**

### opened by `todo-md-monty-drum-figures-are-stale-and-name-the-wrong-voice`

- **`monty-voice-1-noise-sounds-5-pitches-where-the-original-sounds-16`**
- **`verify-strings-carry-arithmetic-nobody-checks`**

### opened by `two-stage-fixed-attack-pitch-is-dropped-after-one-call-and-its-test-pins-the-bug`

- **`nineteen-and-trans-atlantic-report-a-noise-pitch-1-5x-from-their-originals`**
- **`one-on-one-vib-goes-1-029-to-1-350-under-the-held-attack-pitch-and-the-cause-is-unknown`**

### opened by `unmerged-vibrato-worktree-commits`

- **`stale-worktree-branches-hold-nothing-unique`** — worktree-wf_09778b63-af8-2 and worktree-wf_09778b63-af8-4 carry only commits already on master (55f5f12==c6119ab, 4663ffa==386e746). Ten merge-* and worktree-* branches exist in total; a prune pass would need the same containment test run per branch before deleting any. [main], git operations are the user's.

### opened by `vibrato-atkpitch`

- **`detect-note-index-array-for-bit40`**
- **`dimension-for-attack-window-pitch`**
- **`vib-census-attribute-cause-by-reversal-location`**

### opened by `vibrato-depth-dimension`

- **`regenerate-fidelity-md-for-the-depth-column`** — docs/FIDELITY.md predates the `depth` column, so the shipped report has no depth data for any file and the column's own self-documentation is absent from it. Regenerate on master per the once-after-merges rule. [main], rebuilds docs/FIDELITY.md and build/fidelity.json.

### opened by `vibrato-depth-via-vibdelay`

- **`regenerate-fidelity-and-presets-after-the-vibdelay-change`** — 55 of 83 files move, so docs/FIDELITY.md, docs/SURVEY.md and presets.json are all stale against this change once it is committed, and the preset search may now select differently for the classic-vibrato files. [main], the once-after-merges regeneration.
- **`vibrato-onset-delay-needs-an-ear-or-a-column`** — the depth fix delays the oscillator by `multiplier` calls and NO column measures when an oscillation starts, so its only cost is invisible to the corpus A/B that justified it. Either stage the 55 moved files for a listening pass, or build an onset-of-oscillation measure the way `depth` was built for the amplitude. _vibrato_delay's docstring already records a listener complaining the vibrato starts late. [user] for the ear, [subagent] for the column.

### opened by `vibrato-drum`

- **`vib-census-shape-classifier`**
- **`wave-alternate-pitch-half`**

### opened by `vibrato-pitchseq`

- **`pitchseq-preset-reselect`**
- **`pitchseq-zero-step-encoding`**

### opened by `vibrato-plain-effect00-arpeggio-decode`

- **`chord-emission-global-phase`**
- **`classic-vibrato-emitted-no-oscillation`**
- **`find-vibrato-nearest-copy`**
- **`vib-census-chicken-song-cause`**

### opened by `vibrato-plain-zero-byte-decode`

- **`vib-census-flag-ambiguous-adsr`**

### opened by `vibrato-program`

- **`fix-claudemd-wavetable-right-byte-paragraph`**
- **`invert-wave-program-hold-test`**

### opened by `wave-alternate-emitter-predates-the-record-that-called-it-missing`

- **`wave-alternate-noise-post-emission-figures-need-a-goatwriter-probe-and-chicken-songs-wave-baseline-moved`**

### opened by `wave-alternate-noise-post-emission-figures-need-a-goatwriter-probe`

- **`chicken-song-alone-qualifies-for-the-derived-wave-alternate-and-there-is-no-option-to-select-it`**
- **`fidelity-json-reports-no-noise-pitch-so-fidelity-better-audible-cannot-be-tested-offline`**
- **`h2g-conversion-method-7-iiii-carries-the-same-stale-wave-alternate-figures-the-code-just-lost`**

### opened by `wave-program-all-slide-portamento`

- **`wave-program-hold-accumulator-docs`**
- **`wave-program-nemesis-bend-regression`**

### opened by `wave-program-single-speed-absent-pitch`

- **`presets-research-21-wave-program-files`**
- **`wave-program-slide-travel-as-portadown`**

### opened by `whats-next-md-is-spent`

- **`whats-next-md-verify-names-an-undeclared-path`** — the task's verify offers 'deleted with its surviving context folded into todo.md' as an accepted outcome, but touches is rw:whats-next.md alone. A runner taking that branch must either write an undeclared path or drop the clause. General form: a verify with two branches must declare the paths BOTH branches need. [plan edit].

### opened by `whattask-should-check-a-touches-path-exists-before-granting-it`

- **`the-drum-tick-task-grants-test-drum-py-where-test-drum-return-py-is-the-real-file`**

### opened by `which-other-always-block-options-cannot-reach-the-ilv-decoder`

- **`pitch-seq-emits-nothing-on-lion-heart-and-the-cause-is-not-the-pattern-decoder`**
- **`rest-instrument-is-in-the-always-block-and-moves-no-byte-on-any-song`**

