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

| | session start (v0.5.43) | now (v0.5.48) |
|---|---:|---:|
| corpus at defaults | 75/95 | **79/95** |
| coverage of files *in reach* | 75/83 = 90% | **79/83 = 95%** |
| best per-song options | 78/95 | **82/95** |
| packs back to `.sid` with gt2reloc | 50/78 | **all converted files** |
| tests | 177 | **230** (+2 skipped) |
| **does it play the right music?** | unknown | **measured** |

`Commando.sid` → `Commando.sng` remains **byte-exact (15193 B)**.

## Commits (all pushed to `MichaelTroelsen/SIDDetector2`, private)

```
97971b6 v0.5.44  convert the Delta loader and I, Ball
d1ae827 v0.5.45  legalise the restart position, and measure fidelity
18b59f9 v0.5.46  the digi engine's rest is a key-off, not a hold
3f11136          handoff: bring whats-next.md up to v0.5.46
4bdbcfb v0.5.47  separate measured-wrong from converted-wrong, stage a listen
7b5b797 v0.5.48  convert ACE 2 and Chain Reaction
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

**`FIDELITY.md`, 81 of 95 measured** — mean melody 67%, median retrigger 0.98:

| melody similarity | files |
|---|---:|
| plays the same music (95–100%) | 15 |
| close (80–95%) | 26 |
| recognisable (50–80%) | 20 |
| **plays something else (<50%)** | **20** |

This is the single most useful thing the session produced: 79 files convert and
load, but only ~41 plausibly play the right music. That is a far sharper
statement of the gap than "only one file has ever been listened to."

`fidelity.py` also excludes files it cannot honestly compare: `greloc.c` writes
an invalid subtune as a zero-length stub, so if subtune 0 is the invalid one the
`-a0` trace is of silence. One corpus file (`Rasputin`) is in that state; it is
tabulated and kept out of the averages.

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
- **version 4 append + version 9 dialect** (v0.5.48) — ACE 2 and Chain
  Reaction; see above.
- **`python/listen.py`** (v0.5.47) — stages a listening pass: one tune per
  fidelity band, the **median** of the band rather than the extreme, rendered
  to WAV both ways with the same emulator at the same settings, each with a
  note saying what the numbers predict so a listen can contradict them.

## A second gt2reloc defect — mechanism corrected, still open

The first description of this (in three docs) was **wrong**: it is not a
compaction and **nothing is renumbered**. `greloc.c:200-255` counts `songs` =
subtunes whose three voices all have nonzero length; the writing loop at `:653`
then runs `c < songs` over the **original** indices and re-tests validity. So:

- an invalid subtune **keeps its slot**, written with `songsize 0`
  (`:701-706`) — present in the packed `.sid`, plays nothing;
- every subtune at or past the count is **never written**, valid or not.

Verified on Rasputin: 17 subtunes in, PSID reports 15 out; ours 0 and 1 come
back as silent stubs in place, and ours 15 and 16 — carrying 309 and 621
sounding rows — do not come back at all.

`fidelity.py` now detects the stub case and excludes those rows. **The tail
truncation is still open**: silent data loss in the packed `.sid` that no layer
reports. Cheap converter-side fix — give an empty voice a real one-pattern
orderlist so every subtune stays valid.

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

## 2. Why 20 files play something else

The `<50%` bucket: `Delta` (2%), `Chicken_Song` (3%), `Dragons_Lair_Part_II`,
`Flash_Gordon`, `IK_plus`, `Saboteur_II`, `Rasputin`, `Kings_of_the_Beach_intro`,
`One_on_One_Jordan_vs_Bird`, `Rock_Tells_the_Tale` (retrig 6.62 — the real
holder of the "7× re-triggers" figure), `BMX_Kidz` (silent), and others.

**Ruled out — subtune misalignment.** The worst three match none of our
subtunes 0–5, and `--search-subtunes 4` moves the corpus mean only 66% → 69%.

**Ruled out — measurement error (done, v0.5.47).** Exactly **one** of the 21
(`Rasputin`) was measured wrong; `fidelity.py` now detects it and excludes it.
**The other 20 are converted wrong.** So this section is now a real, unexplained
converter defect list, not a mixed bag.

**Ruled out — the slide gap (§3).** See below: no correlation with melody score.

A known one: the Delta loader's restart handler **patches voice 0's orderlist
byte** from `$C45A,X` (`$18` → `$1D`) on each loop, so the player plays `$18`
once then loops `$1D`; we emit the on-disk `18 FF` and loop `$18` forever.

Nothing else has been ruled in. This is the project's biggest open question and
it now needs per-file disassembly, starting with the extremes (`Delta` 2%,
`Chicken_Song` 3%).

## 3. The vibrato/slide gap — corpus-wide, audible, invisible to the metric

Corpus-wide, 80 files: the originals slide **22,674** times, our conversions
**7**. 57 of 80 files have slides in the original and none in ours. Off the Cuff
is 440 slides / 0 ties in the original against 0 / 664 in ours. We step pitch
where Hubbard bends it, essentially everywhere.

**It does not explain the melody scores** — an earlier version of this file
claimed it did, and that was wrong:

| | files | mean melody |
|---|---:|---:|
| ≥100 slides in the original | 47 | 67% |
| 0 slides in the original | 21 | 66% |

The `<50%` bucket averages 280 original slides, the `≥95%` bucket 269. `Wiz`
measures 99% melody and 100% pitch overlap against an original that slides 2033
times. Slides create no attacks, so the metric cannot see them — the same
blindness the digi rest fix hit.

**The mapping is mechanical, though.** Hubbard's vibrato is instrument record
**+6** (Warhawk `$12BF`: low nibble rate, high nibble depth, `CMP #$0E / INC`
flips direction — a triangle; depth is note-relative, `±$0058` at F#5 and
`±$005D` at G-5), loaded per instrument at `$11E4`. H2G does not interpret that
byte at all — it renders it into the instrument *name*. GoatTracker has the
same construct per instrument: `gplay.c:352-353` makes `iptr->ptr[STBL]` the
vibrato parameter with no per-row command, and `:777-802` is the same triangle,
with `cmpvalue >= 0x80` making the depth note-relative. So: rate nibble → left
byte with bit 7 set, depth nibble → right byte as a shift, `vibdelay` non-zero,
one speedtable entry per distinct vibrato byte.

Of 71 classic-stride corpus files, exactly one has slides while +5/+6 are both
zero.

**Sequencing note:** doing this buys audible fidelity on 57 files and *provably
zero* movement in `FIDELITY.md`. It needs a slides column in the harness before
anyone can see it landed, and a listening check to validate it. Do §6 first.

Related, unproven: our 24,647 ties against 7 slides look like the fabricated
wavetable's arpeggio standing in for pitch movement, which would make the arp
byte +7 and the vibrato byte +6 two halves of one misreading.

## 4. Tempo: three calls per row is still the floor

`CMD_SETTEMPO` 3 → tempo 2 → 3 calls/row. Exact 1-row-per-frame needs **speed
multiplier 3**, a player setting not storable in the `.sng`. Open whether
gt2reloc can set it (`-S` was observed moving the wrong way, unexplained). This
item was **never worked** — the fork that read "do 4" correctly took the
coverage tail instead.

## 5. Remaining coverage — 4 files, one of them genuine

Three of the four (`Delta`, `Dragons_Lair_Part_II`, `W_A_R`) fail only at
survey defaults with `TOO MANY NEW PATTERN CREATED` and convert fine under
their presets. **`Devils_Galop` is the only file with no working options.**

Its pattern fetch at `$138B` names `$1797,Y` / `$1798,Y` — one byte apart, so
interleaved — and `$1790-$1798` is **all zeros on disk**. An init loop at
`$18E7` copies 120 bytes into place at runtime (`LDA $183B,X / STA $1799,X`),
the code's base 2 bytes below the destination — the same shape as the digi
engine's `+8` runtime table and I, Ball's self-relocation. Neither existing
mechanism catches it: `find_relocation` only consults a relocation for an
address that resolves *nowhere*, and this one resolves — to zeros. Needs a
table-copy reader plus a **"a table of zeros is not a table"** guard.

`Chicken_Song` and `Knucklebusters` still drop a subtune at defaults;
Knucklebusters has two long voices so no cut aligns (the P4 case).

## 6. Listening pass — staged, never performed

`python/listen.py` renders the set; `build/listen/` (gitignored) currently
holds **Flash_Gordon** (8%), **Star_Paws** (72%), **5_Title_Tunes** (87%) and
**Wiz** (99%), verified as real audio at comparable levels (RMS 4079–8945,
none silent). **Nobody has listened yet** — `Commando` remains the only file
ever heard by a human, and the measurement can be wrong in ways only a listener
catches. This now gates §3.

Variant 4 (ACE 2) finally has a working sample as of v0.5.48.

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

- **HEAD `7b5b797` (v0.5.48)**, 6 commits this session, all pushed to
  `https://github.com/MichaelTroelsen/SIDDetector2.git` (private).
- **230 tests pass, 2 skipped** (run from `python/`). `Commando.sng` byte-exact.
- `SURVEY.md`, `presets.json` and `FIDELITY.md` are current as of v0.5.48.
- Working tree clean.

## Deliverables

| Artifact | Status |
|---|---|
| `fidelity.py` + `FIDELITY.md` | complete; stages 2/3 wired behind flags |
| `--legal-restart` | complete; every converted file packs back to `.sid` |
| digi rest → key-off | complete |
| Delta loader + I, Ball + ACE 2 + Chain Reaction | complete |
| measured-wrong / converted-wrong partition | complete: 1 of 21 was measured wrong |
| `listen.py` + staged WAVs | complete — **but nobody has listened** |
| digi tie flag | **open — needs a design decision** |
| vibrato / slide gap | **open — mapping known, unimplemented** |
| gt2reloc tail truncation | **open — cheap converter-side fix known** |
| `Devils_Galop` | **open — needs a table-copy reader** |
| speed multiplier 3 | **never investigated** |

## Open questions

1. **Why do 20 files play the wrong notes?** Ruled out: subtune misalignment,
   measurement error, and the slide gap. Nothing is ruled in. This is the
   project's biggest open question.
2. How to encode the digi tie flag — per-duration instrument variants, or
   accept the legato?
3. Can speed multiplier 3 be set from the command line at all?
4. What does any of it actually sound like?

## The gap, restated

Two sessions ago the gap was "only one file has ever been listened to." One
session ago it became "15 files measure right, 21 measure wrong." It is now
sharper still: of those, exactly one was *measured* wrong, and the two obvious
suspects — subtune misalignment and the missing pitch slides — have both been
ruled out with data. What remains is 20 files that genuinely play the wrong
notes for reasons nobody has identified, and a corpus that has still never been
heard. The staged WAVs in `build/listen/` are the cheapest way to change that.
</current_state>
