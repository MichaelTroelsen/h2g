<original_task>
Continuation of work on `C:\Users\mit\claude\c64server\hubbard` — **H2G**, a
converter from Rob Hubbard `.sid` files to Goattracker `.sng`. This session
began from a handoff at **v0.5.43** with 75/95 converting, 177 tests, and one
open claim: that our held rows re-trigger notes ~7× too often.

The user's requests, in order:

1. "read what next" — read the handoff, report where things stood.
2. `/subtask` forks, in one batch: "do the gplay.c read for item 1", "do 2"
   (the illegal restart position), "do 3. There are more tools like siddump in
   the SIDM2 that can be used" (the fidelity harness), "do 4" (the coverage
   tail — the fork correctly read this as item 4 of the *reply's* ranked list,
   not of the handoff).
3. `/subtask` "investigate the digi note path then" — after the gplay.c read
   refuted the `0xBD` hypothesis.
4. "commit and push to git."
5. "update whats-next.md" (this file).

The main thread's own work was the serialisation pass: five concurrent forks
left an entangled tree, and it had to be untangled into coherent commits with
artefacts regenerated against each settled state.
</original_task>

<work_completed>

## Headline result

| | session start (v0.5.43) | now (v0.5.46) |
|---|---:|---:|
| corpus at defaults | 75/95 | **77/95** |
| coverage of files *in reach* | 75/83 = 90% | **77/83 = 93%** |
| best per-song options | 78/95 | **80/95** |
| packs back to `.sid` with gt2reloc | 50/78 | **77/77** |
| tests | 177 | **218** (+2 skipped) |
| **does it play the right music?** | unknown | **measured** |

`Commando.sid` → `Commando.sng` remains **byte-exact (15193 B)**.

## Commits (all pushed to `MichaelTroelsen/SIDDetector2`, private)

```
97971b6 v0.5.44  convert the Delta loader and I, Ball
d1ae827 v0.5.45  legalise the restart position, and measure fidelity
18b59f9 v0.5.46  the digi engine's rest is a key-off, not a hold
```

## The big one: fidelity is now measured, not assumed

`python/fidelity.py` — convert → legalise restart → pack with `gt2reloc` →
`siddump` both → compare **note attacks**. Whole 95-file corpus in ~5 s.

```sh
python fidelity.py <sid_dir> -t 10 --presets ../presets.json -o ../FIDELITY.md
python fidelity.py --pair a.sid b.sid --audio --register
```

Stage 1 (note sequence) is the default; stages 2 and 3 from
`SIDM2-FIDELITY-TESTER.md` are wired behind `--audio`
(`pyscript/audio_tightness_tool.py`) and `--register`
(`scripts/validate_sid_accuracy.py`), both verified to run and parse. The audio
stage reads the tool's **jitter** block, not its raw-delta block — the raw one
just re-reports our known tempo offset. Controls: a file against itself scores
100%, two unrelated tunes 0%.

**`FIDELITY.md`, 80 of 95 measured** — mean melody 66%, median retrigger 0.98:

| melody similarity | files |
|---|---:|
| plays the same music (95–100%) | 15 |
| close (80–95%) | 24 |
| recognisable (50–80%) | 20 |
| **plays something else (<50%)** | **21** |

This is the single most useful thing the session produced: 77 files convert and
load, but only ~39 plausibly play the right music. That is a far sharper
statement of the gap than "only one file has ever been listened to."

## Player-engine reverse engineering

Method unchanged and non-negotiable: **disassemble the player and read the
semantics out of the 6502.** Scratch disassembler: `$TMP/dis6502.py`
(`python dis6502.py <sid> <hex addr> <count>`). **Never name it `dis.py`** — it
shadows the stdlib module `inspect` imports.

### `$FE` means "tune ended" (v0.5.45)
Verified in three dialects before a line was written: every one calls the
player's jump-table entry +3, which is `LDA #$C0 / STA flag / RTS`, and the
`BIT flag / BMI` at the top of the play routine then stops fetching notes —
Warhawk `$109F`→`$1003`→`$1F30`, Last V8 `$809B`→`$8013`→`$8C71`, Saboteur II
`$F0A2`→`$F00C`→`$F589`. The VB6 comment (`h2g.frm:1206`, `'make repeat
illegal, so goattracker stops`) was exactly right about intent.

### The digi engine's note path (v0.5.46)
Per-voice tick `$10A2`: `DEC $1648,X / BMI` → new event, else sustain
(`JMP $11FB`); the counter reloads from a sticky register at `$11F2`, so a note
lasts `wait+1` frames. Our `note row + wait hold rows` matches that exactly, at
one row per frame. Three things were unmodelled; one is fixed:

- **fixed — `$60` is a key-off, not a hold.** `$1184` does `DEC $165D,X`,
  taking the gate mask just set to `$FF` at `$10FF` down to `$FE` — what the
  end-of-note release path writes. `$165D,X` is ANDed into the `$D404` write at
  `$148D`, clearing GATE. Every rest used to sustain the previous note.
- **open — bit 5 of the duration byte is a tie flag** (`$11FE`–`$1206`); it
  also skips the pulse/ADSR reload at `$11A9`, so a tied note is true legato.
  See work_remaining §1.
- **open, negligible — duration is sticky across patterns**; the decoder resets
  it. Only 4 patterns in the whole 9-file set start without a prefix.

### The Delta loader and I, Ball (v0.5.44)
- `Delta_Mix-E-Load_loader` — **one byte**. Mega Apocalypse's pattern-table
  fingerprint exactly, except it clears per-voice state with `STA abs,X` (`9D`)
  where that one uses `STA zp,X` (`95`). Added as its own chain entry with the
  tail byte literal, not wildcarded. Read at `$C0CA`; the tables tile the region
  with no slack — orderlist ptrs `$C762`, selector `$C768`, pattern lo/hi
  `$C76E`/`$C796`, orderlist data `$C7BE` — each ending where the next begins.
  That also settles the subtune count: the header claims 16, but subsong 1's
  selector entry *is* the pattern table, so there is one.
- `I_Ball` needed **no signature**. It loads at `$9000`, and its init copies
  `$9000-$9FFF` up to `$E000` where the tune lives — so every address its player
  names is past the end of a file that stops at `$C2CF`. Detection was finding
  all four tables and rejecting all four as out of range.
  `sidfile.find_relocation` reads the page-copy loop out of the init code. The
  rule that keeps it safe: **`to_offset` consults a relocation only for an
  address that resolves nowhere**, so a misread loop can fail to rescue a file
  but can never move one that already works.

## Features added

- **`--legal-restart`** (v0.5.45) — rewrites the out-of-range restart position
  that stands in for `$FE`. Took gt2reloc packing from **50/78 to 78/78**. Runs
  **last**, on completed orderlists, because slicing, packing, merging and
  splitting all move the length — position 0 is the only value choosable without
  knowing the finished orderlist. Cost is honest and logged: a one-shot tune
  loops instead of ending. Off by default (the fixture carries three such
  tracks); `presets.json`'s `always` block sets it.
- **`GT_KEYOFF`** (v0.5.46) — the digi rest fix above.
- **`sidfile.find_relocation`** (v0.5.44) — files that copy themselves.

## A second gt2reloc defect found, unfixed

`greloc.c:201` only validates and packs subtunes whose **three voices all have
nonzero length**, and `:653` writes survivors consecutively. So a voice whose
orderlist is just a marker (`[$FF,$00]`, songlen 0) **drops its whole subtune
and renumbers every later one** in the packed `.sid`. That is the real
explanation for the `Rasputin` outlier `SNG2SID-FIDELITY.md` had recorded as
"presumably optimised away": both affected subtunes, subtune 0 included, were
discarded, so it "relocated" while throwing the music away. **Directly relevant
to every fidelity number** — a `siddump` comparison against a renumbered export
silently measures the wrong tune.

## Documentation

- `FIDELITY.md` — new, generated.
- `H2G-CONVERSION-METHOD.md` — the `$FE`/restart section, "When the file moves
  itself" (relocation), the digi rest, the tail-opcode note.
- `SIDM2-FIDELITY-TESTER.md` — §4b correction (see attempted_approaches §1).
- `SNG2SID-FIDELITY.md` — the empty-voice subtune-drop.
- `CLAUDE.md` — `--legal-restart` in the survey command and why; `FIDELITY.md`
  regenerated on demand rather than per commit.
</work_completed>

<work_remaining>

## 1. The digi tie flag — the largest *known* fidelity defect

93% of corpus digi notes have the tie flag **clear**, meaning they should gate
off at the end of their duration. They don't, so every non-tied note plays
legato. Correct semantics, no mechanical encoding:

- A per-note `$BE` row **collapses the attack count** — One_on_One 102 → 4,
  siddump showing `WF 40`/`42` with the gate bit stuck clear while the
  wavetable keeps changing frequency. `cptr->gate` is persistent channel state
  (`gplay.c:922`, written as `cptr->wave & cptr->gate` at `:951`), and once
  ~half the rows are key-offs the notes stop reading as attacks at all.
- GT's native form is the instrument's **`gatetimer`** (`gplay.c:345`,
  `:930-935` — bit 6 = no gate-off, bit 7 = no ADSR reset, which is *precisely*
  the digi tie flag). But it is per-instrument where the digi duration is
  per-note.

Needs a design decision — e.g. synthesising per-duration instrument variants —
not a patch.

## 2. Why 21 files play something else

The `<50%` bucket: `Delta` (2%), `Chicken_Song` (3%), `Dragons_Lair_Part_II`,
`Flash_Gordon`, `IK_plus`, `Saboteur_II`, `Rasputin`, `Kings_of_the_Beach_intro`,
`One_on_One_Jordan_vs_Bird`, `Rock_Tells_the_Tale` (retrig 6.62 — the real
holder of the "7× re-triggers" figure), `BMX_Kidz` (silent), and others.

**Ruled out:** subtune misalignment. The worst three match none of our subtunes
0–5, and `--search-subtunes 4` moves the corpus mean only 66% → 69%.

**Worth trying first:** check them against the empty-voice subtune-drop above —
if `greloc.c` discarded subtune 0, the comparison was never valid to begin with.
That is cheap and would partition the bucket into "converted wrong" and "measured
wrong" before anyone starts disassembling.

A known one: the Delta loader's restart handler **patches voice 0's orderlist
byte** from `$C45A,X` (`$18` → `$1D`) on each loop, so the player plays `$18`
once then loops `$1D`; we emit the on-disk `18 FF` and loop `$18` forever.

## 3. The vibrato/slide gap — corpus-wide

The corrected measurement (attempted_approaches §1) showed the original bends
pitch *within* a note where we jump far enough to land on other note numbers,
including octaves the original never plays. On Off the Cuff: original 0 note
changes without retrigger and 349 slides; ours 530 and 0. This is the shape of
defect behind much of the 66% mean, and it is not the digi engine's alone.

## 4. Tempo: three calls per row is still the floor

`CMD_SETTEMPO` 3 → tempo 2 → 3 calls/row. Exact 1-row-per-frame needs **speed
multiplier 3**, a player setting not storable in the `.sng`. Open whether
gt2reloc can set it (`-S` was observed moving the wrong way, unexplained). This
item was **never worked** — the fork that read "do 4" correctly took the
coverage tail instead.

## 5. Remaining coverage — 6 files

`Chicken_Song` and `Knucklebusters` still drop a subtune at defaults;
Knucklebusters has two long voices so no cut aligns (the P4 case).

## 6. Listening pass — still never done

`FIDELITY.md` replaces guessing with measurement, but **`Commando` remains the
only file ever heard by a human**. The measurement can be wrong in ways only a
listener catches. `build/` is stale — regenerate before listening. Variant 4
(ACE 2) has no working sample in the corpus.

## 7. Smaller items

- README § `--tempo` and `SNG2SID-FIDELITY.md` § 3 still describe the
  instrument-63 tempo hack that **v0.5.42 replaced** with `CMD_SETTEMPO`.
- Suspected pattern-table undercount behind `Delta`'s dangling refs.
- Scratch `packverify.py` is invalid for `Kentilla`/`Knucklebusters` (it
  compares pattern tables between packed/unpacked runs, and merging changes
  those). Its row-stream half is the meaningful part and never runs.
- P2 (Gremlins split) artifacts remain unrebased and are almost certainly moot.
</work_remaining>

<attempted_approaches>

## Wrong conclusions reached and corrected — do not repeat

1. **"We re-trigger roughly seven times too often"** — the previous handoff's
   headline open item, and it was an artefact of the measurement.
   `grep -oE "[A-G]#?-[0-9]"` counts three different siddump events alike; a
   bare note is printed **only after a gate rising edge** (`siddump.c:376-380`,
   `:409`). Separated, on Off the Cuff over 8 s:

   | | attacks | note changes w/o retrigger | slides |
   |---|---:|---:|---:|
   | original | 82 | 0 | 349 |
   | ours | 64 | **530** | 0 |

   We strike **0.78** notes per original note; corpus median **0.98**. The 7×
   figure belongs to `Rock_Tells_the_Tale` alone. **Count the right event.**

2. **"`0xBD` hold rows are re-triggering notes"** — refuted from the source.
   `gplay.c:908-941` is the only consumer of a pattern's note column during song
   playback; it tests `KEYOFF` (`$BE`), `KEYON` (`$BF`) and `<= LASTNOTE`
   (`$BC`), and `$BD` matches none, falling through to `NEXTCHN`. The C64
   runtime player agrees (`player.s:1280-1284` → `mt_rest`, which only advances
   the pointer, and `player.s` even packs runs of them). `$BD` is what the
   editor writes into cleared rows (`gpattern.c:741,762,784,847,1173`). The
   constant is **misnamed**: in the note column `REST` means *no note /
   continue*. Actual silencing is `KEYOFF`.

3. **A fork's measurement of the digi rest fix did not reproduce.** It reported
   Kings_of_the_Beach retrig 1.17 → 0.94; on the settled tree `FIDELITY.md` does
   not move **one percent** on any of the nine digi files. The fix is real — Off
   the Cuff gains 66 `$BE` rows, 0 before — but **the metric is blind to it by
   construction**: it compares attacks, and closing a gate adds none. The fix was
   taken on the disassembly, and the limitation is written into
   `H2G-CONVERSION-METHOD.md` beside it so the flat report is not later read as
   evidence the fix did nothing. **Re-measure a fork's numbers on the settled
   tree before quoting them.**

4. **"gt2reloc is unreliable"** — over-general, twice over. First it was the
   illegal restart position (fixed). Then it was the empty-voice subtune drop
   (found, unfixed). Both times the tool was behaving exactly as its source says.

## Environment gotchas

- **`@'...'@` here-strings are PowerShell only.** Using one in the Bash tool
  made bash parse `convert -> pack -> siddump both -> compare` as *redirections*
  and silently create empty files named `pack`, `siddump`, `compare` in the repo
  root. For multi-line commit messages: write the message to a scratchpad file
  and `git commit -F`.
- **`--legal-restart` is required on the survey command.** Without it the
  `gt2reloc` column measures the option's absence, not the converter.
- **gt2reloc never reports failure** — errors go to `fopen("CON")` and SDL
  routines that do nothing headless. Exit 0, no output, no file. **Test for the
  output file, never the exit code.**
- **Concurrent `/subtask` forks share one git index.** Five ran this session.
  Two correctly declined to commit; two staged reconstructed HEAD+own-hunks
  blobs rather than `git add`-ing shared files, which worked well. **Never
  `git add -A`.** Shared prose files (`README.md`, `CLAUDE.md`) end up carrying
  several forks' edits interleaved and cannot be split by pathspec — plan to
  land those together.
- **Regenerating artefacts mid-edit records a state that never existed.** The
  serialisation pass handled this by `git stash push -- <paths>` to isolate one
  fork's change, regenerating, committing, then popping.
- Naming a scratch file `dis.py` breaks Python (`inspect` imports stdlib `dis`).
- `pytest` must run from `python/`, not the repo root.
- PowerShell scripts need the PowerShell tool, not Bash.
</attempted_approaches>

<critical_context>

## Invariants

- **`Commando.sid` → `Commando.sng` must stay byte-exact (15193 B).** Every
  output-changing feature is opt-in: `--max-rows` 94, `--format` gts2, and
  `--terminate-patterns` / `--tempo` / `--dedup-patterns` / `--prune-patterns` /
  `--pack-repeats` / `--legal-restart` all default off.
- **Bump the version on every commit**: `python python/bump_version.py "desc"`.
- **Regenerate on every commit that changes conversion**, from `python/`, after
  tests pass and never mid-edit:
  ```sh
  python survey.py <sid_dir> -o ../SURVEY.md --legal-restart --gt2reloc
  python presets.py <sid_dir> -o ../presets.json
  python fidelity.py <sid_dir> -t 10 --presets ../presets.json -o ../FIDELITY.md
  ```
- **Never ship a "fake success"** — a structurally valid, musically empty
  `.sng`. This drove v0.5.26 and has since made two forks correctly refuse to
  commit.
- Every orderlist-structure change needs the **gplay.c-faithful playback
  equivalence check** (`test_pack_repeats.py` has the harness).
- **A metric that cannot see a change is not evidence the change did nothing.**
  Say which defects the measurement is blind to, in the doc, next to the fix.

## Verified Goattracker facts (read from source)

```
MAX_PATT 208   MAX_PATTROWS 128   MAX_SONGLEN 254   MAX_INSTR 64
FIRSTNOTE $60  LASTNOTE $BC  REST $BD  KEYOFF $BE  KEYON $BF  ENDPATT $FF
REPEAT $D0     TRANSDOWN $E0   TRANSUP $F0   LOOPSONG $FF
```
- `$BD` in the note column is a **no-op**, not silence. `$BE` silences.
- Orderlist step = `[transpose][repeat][pattern]` (`gplay.c:977-992`). A repeat
  after a repeat makes the second byte the pattern number.
- Transpose `$E0..$FE` → −16..+14. `$FF` is LOOPSONG, so **+15 is not
  representable** (`gorder.c:70` rewrites a typed `$FF` to `$FE`).
- `$D0+n` plays the next pattern **n+1** times. `$D0` alone is discarded by
  `greloc.c:680`, which also requires a pattern to follow (`:683`).
- `greloc.c:244` rejects a restart position `>= songlen`.
- `greloc.c:201` skips any subtune with a zero-length voice; `:653` writes
  survivors consecutively, **renumbering** the rest.
- **Tempo 0 and 1 are funktempo** (`gplay.c:325`), not a rate. A row lasts
  `tempo+1` calls, so the fastest steady row is tempo 2 = **3 calls**.
- Effective instrument ceiling is **51**, not 64. Clamped at 50.
- `siddump` prints a bare note **only on a gate rising edge**
  (`siddump.c:376-380`, `:409`) — the basis of the attack metric.

## Key paths

| | |
|---|---|
| Corpus (95 files) | `C:\Users\mit\claude\c64server\SIDM2\SID\Hubbard_Rob` |
| SIDId database | `C:\Users\mit\claude\c64server\SIDM2\tools\sidid.cfg` |
| GoatTracker 2.77 (prebuilt + source) | `C:\Users\mit\Downloads\GoatTracker_2.77` |
| `gt2reloc.exe` / `siddump.exe` | `…\GoatTracker_2.77\win32\`, `SIDM2\tools\` |
| Short scratch path for gt2reloc | `C:\t\` |
| SIDM2 accuracy tools | `SIDM2\pyscript\audio_tightness_tool.py`, `SIDM2\scripts\validate_sid_accuracy.py` |

Run SIDM2 tools with **cwd = SIDM2 root** (`tools/siddump.exe` is relative).

## Non-obvious behaviours

- `command_floor(version)` exists because `reindex_tracks` receives tracks in
  **Hubbard** numbering, where the command boundary moves by dialect: `$FF` for
  0/1/3/4/5, `$F0` for 2/6/7/8.
- `presets.json`'s `always` block (gts5, tempo auto, gt2reloc, legal_restart) is
  what makes a preset reproduce the exact bytes it records.
- The digi engine's subtune count comes from the **table extent**, not the PSID
  header — Powerplay Hockey claims 10 and reading them yields 4119 refs to 45
  patterns.
- Opening output in GoatTracker requires `--format gts5`; the GTS2 importer
  overruns its pattern array on the portamento commands we emit.
</critical_context>

<current_state>

## Status: all work committed and pushed; tree clean

- **HEAD `18b59f9` (v0.5.46)**, 3 commits this session, all pushed to
  `https://github.com/MichaelTroelsen/SIDDetector2.git` (private).
- **218 tests pass, 2 skipped** (run from `python/`). `Commando.sng` byte-exact.
- `SURVEY.md`, `presets.json` and `FIDELITY.md` are current as of v0.5.46.
- Working tree clean except this untracked file.

## Deliverables

| Artifact | Status |
|---|---|
| `fidelity.py` + `FIDELITY.md` | complete; stages 2/3 wired behind flags |
| `--legal-restart` | complete; 77/77 pack back to `.sid` |
| digi rest → key-off | complete |
| Delta loader + I, Ball detection | complete |
| digi tie flag | **open — needs a design decision** |
| empty-voice subtune drop in gt2reloc | **found, unfixed** |
| speed multiplier 3 | **never investigated** |
| listening pass | **never done** |

## Open questions

1. How to encode the digi tie flag — per-duration instrument variants, or
   accept the legato?
2. How many of the 21 `<50%` files are *measured* wrong rather than *converted*
   wrong, because gt2reloc dropped subtune 0?
3. Can speed multiplier 3 be set from the command line at all?
4. What does any of it actually sound like?

## The gap, restated

The old handoff said the project's largest epistemic gap was that only one file
had ever been listened to. That is still true, but it is now bounded: 15 files
measure as playing the same music, 21 as playing something else. The gap has
moved from "we have no idea" to "we know which files are wrong and mostly not
why."
</current_state>
