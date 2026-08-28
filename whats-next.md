<original_task>
Resume h2g work at HEAD `c376622` (v0.5.399).

**This file is no longer the open-task list.** `.claude/tasks/whattask.json`
is, and `/whattask` regenerates it by reconciling `todo.md`, this file and
`.claude/tasks/runs.jsonl` against the commit log. What survives here is the
context a plan record has no room for: how things are verified in this repo,
and the traps that have actually cost a session.

The previous version of this file was pinned at HEAD `5b2f3f3` and was read as
an open backlog for fifteen commits after three of its five priorities had
landed. That is the failure mode of a handoff doc: nothing closes it. If you
are reading a `<work_remaining>` section below and it is long, check it against
`git log` before believing a word of it.
</original_task>

<work_completed>
Nothing is in flight. The tree is clean at `c376622` and everything through
v0.5.399 is pushed.

The last stretch, newest first:

- **v0.5.399** — `graphify-out/`, `arkiv/*.sng`, `arkiv/Hubbard_Rob/` and the
  graphify settings backup are gitignored. Not cosmetic: `fidelity.py:3165`
  stamps every generated report with `git status --porcelain -- .`, which counts
  UNTRACKED files, so a stray path marked every report `-dirty`.
- **v0.5.398** — artefacts regenerated, and the regeneration was caught
  DELETING `real_firstwave_instruments` from both songs carrying it, one of them
  human-approved. Registered in `presets.EXCLUDED_FROM_ALWAYS`; guarded
  generally by `test_every_per_song_decision_in_the_artefact_survives_a_regeneration`.
- **v0.5.397** — `--regrid`. A Goattracker row is whole play calls; Monty's is
  384/127 = 3.0236 frames, so it shipped at 3 and ran 0.78% fast. Inaudible as a
  rate, audible as an integral: 15 frames by 38 s, where a listener heard voice 2
  enter early after a 12-second rest. 12 songs adopt it; drift improves on 14 of
  the 18 it reaches and five land on exactly 0.00.
- **v0.5.396** — the gatetimer bound is per instrument (minimum over the subtunes
  it plays in). Warhawk gate 84→88. It does NOT help Monty; all 16 of its
  instruments sound in the tempo-3 subtune.
- **v0.5.395** — Monty's drums were four octaves down behind a missing entry in
  `EFFECT_KNOWN_MASKS`. No report column could see it; a listener could.
</work_completed>

<work_remaining>
**Read `.claude/tasks/whattask.json`, not this section.** It is generated, it is
keyed to a commit, and `/whattask --dry-run` prints it without regenerating.

At `c376622` it held 15 tasks, 10 ready. The two waiting on a human:

- **`monty-firstwave-trade-needs-a-listen`** — Monty's
  `real_firstwave_instruments` [1..16] buys `hold` 0→88% and costs `pitch`
  (95→92). Three columns hang on which sounds closer.
- **`ace-ii-rest-envelope-awaits-a-listen`** — ACE_II measures adsr 93→96 with
  `rest_envelope_silence`, but its approval pins the no-flag bytes.

Nothing else here is a task list. If you want one, run `/whattask`.
</work_remaining>

<attempted_approaches>
Refutations worth not repeating. Each cost real time and each looked right.

- **Dropping `rshift`'s `+1` is not the vibrato-depth fix.** It reproduces
  v0.5.129's rejection to three decimals and destroys four more files
  (One_on_One 0.986→0.299). The fix was `vibdelay` (v0.5.369): delay the
  oscillator past frame 0 so the attack keeps its own pitch.
- **`--no-test-restart` is not the fix for the note-length deficit.** Forced
  corpus-wide it takes melody −26.3pp on 68 files, because the testbit frame is
  the only one below `$10` and siddump needs that to name an attack at all. What
  was wanted was `HARD_RESTART_FRAMES`.
- **`gt2reloc -R0` is not the fix for the slide deficit.** `_scaled_step`
  already compensates; disabling the skip double-corrects.
- **The `gplay.c` TONEPORTA story for the bit-6 rest regression is false.**
  It fits the shape perfectly and suppressing TONEPORTA after a rest changes
  ZERO bytes on all fifteen files. One run would have falsified it.
- **Per-pattern budgeting cannot pay a per-subtune debt** (found building
  `--regrid`): a pattern played five times delivers five times, and a
  `CMD_SETTEMPO` under `$80` sets all three channels, so scheduling from three
  voices fires each compensation three times. Both showed up as a deficit
  becoming a surplus of the same size.
</attempted_approaches>

<critical_context>
## Verification patterns that earned their keep
- **Corpus byte-hash against a clean `git archive HEAD` export** — the check of
  last resort. Copy `python/tools/siddump-rt/siddump.exe` into the export first:
  it is gitignored, and without it the harness silently measures only the
  single-speed files.
- **Assert your own success rate before comparing.** A probe where every
  conversion raised compares two identical sets of error strings and reports
  "nothing moved". This has shipped as evidence twice.
- **And assert the COLUMNS exist.** A probe asking rows for `pitch`/`seq`/`hold`
  when the real keys are `pitch_jaccard`/`sequence` gets `None` from `dict.get`
  and silently compares six of fourteen columns. Regenerating the artefact is a
  second, independent reader — prefer it BEFORE adopting a candidate.
- **A scripted edit must assert its match.** `str.replace` with a non-matching
  search returns the input unchanged and raises nothing. Two commits have
  described edits that never applied.
- **Check the fixture's BYTES, not its length.** `len(convert(...)) == 15193`
  passes for most edits that move a byte between two wavetable entries.

## Gotchas
- **`instr 00` means "keep the current instrument"**, not "no instrument".
- **`songview`'s `instruments[0]` has `number = 1`**; Goattracker numbers
  patterns in HEX and the editor's pattern is post-dedup.
- **`_preset_opts` passes `False` for absent keys**, not `None`.
- **`gplay.c:334` stops the song outright** if the gatetimer reaches the
  channel's tick — the failure is total, not graceful.
- **`_span` excludes zero; `wave_compare` ignores the gate bit** — which is why
  a KEYOFF-only change was unscoreable until `gate` was built.
- **Row 0's command column belongs to the subtune's clock.** A row-0 command
  silently costs that subtune its `CMD_SETTEMPO`; three changes have been caught
  by this. Declare in `TEMPO_OVERWRITABLE` as well as `ONE_SHOT_COMMANDS`.
- **The staged `.h2g.sng` is the audio's provenance** — `listen.py` packs it, so
  compare shas rather than mtimes.
- **NEVER `git stash`.** `refs/stash` is shared across worktrees; two concurrent
  stashes have already returned each other's diffs.

## Two genuinely different "instruments missing" cases
- **5 Title Tunes** — inheritance. 160/160/32 note rows carry `00` and inherit
  correctly. Not a defect. (Its firstwave set is human-approved.)
- **International Karate** — channels 1 and 3 set **no instrument on any row**,
  so the conversion plays whatever carried in. This is the real one, and it is
  `international-karate-voices-never-set-an-instrument` in the plan.
- **Pygmies Revenge** — 256/4/128 zero rows, all *before* that channel's first
  instrument. Same shape as 5TT, not a defect.

## Environment
- Corpus: `C:/Users/mit/claude/c64server/SIDM2/SID/Hubbard_Rob` (95 files, 83 convert)
- `sidplayfp`: `C:/Users/mit/Downloads/sidplayfp-2.15.2-32bit-mmx/sidplayfp.exe`
- GoatTracker sources: `C:/Users/mit/Downloads/GoatTracker_2.76/src` and
  `goattracker2/src` (has `player.s` — the PACKED player, which is the one that
  ships and which disagrees with `gplay.c` about the first call)
- `build/` and `graphify-out/` are gitignored. 12 CPUs. Full suite ≈ 5m40s.
- Locking: `serial.lock` + `serial.lock.d` mutex; `.tmp` + `mv -f`, never truncate.
</critical_context>

<current_state>
Clean at `c376622` (v0.5.399), pushed, `git status --porcelain` empty.
Suite 1595 passed / 2 skipped. All three human approvals (ACE_II, Action_Biker,
5_Title_Tunes) verify HOLDS by sha256.

Artefacts are current as of v0.5.397's conversions, stamped `h2g 0.5.397` in a
0.5.398 commit — the documented ordering, since `bump_version.py` runs after the
generators.

The open list is `.claude/tasks/whattask.json`. This file is context, not a queue.
</current_state>
