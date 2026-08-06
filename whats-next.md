<original_task>
Continuation of work on `C:\Users\mit\claude\c64server\hubbard` — **H2G**, a
converter from Rob Hubbard `.sid` files to Goattracker `.sng`. The current
session began from a handoff at **v0.5.43** (75/95 converting, 177 tests, one
open claim about re-triggering that turned out to be a miscount) and ran to
**v0.5.60** through three waves of concurrent `/subtask` forks.

The user's requests, in order: read the handoff; a first wave of forks
(gplay.c read, illegal restart, fidelity harness, coverage tail, digi note
path); commit and push; update this file; a second wave (vibrato mapping →
became the slides/speed-table work, Delta/Chicken_Song investigation, tail
truncation, speed multiplier, +7 effect byte, a project audit); "retrodebugger
MCP is also available"; a serialisation pass; then a third wave (per-file
tempo, phantom pattern entries, wavetable Phase 0, Devils_Galop, the digi
tie-flag census), a second serialisation pass, and a fourth wave (the -S
wiring, the wavetable census, and a re-read of the low-fidelity bucket).

The serialisation discipline that emerged over both waves: forks work in
scratchpad copies or stage reconstructed HEAD+own-hunks blobs; the main
thread lands their work in dependency order, one version bump per commit,
artefacts regenerated only on a settled tree, everything staged by pathspec.
</original_task>

<work_completed>

## Headline result

| | session start (v0.5.43) | now (v0.5.60) |
|---|---:|---:|
| corpus at defaults | 75/95 | **80/95** (80/83 in reach = 96%) |
| best per-song options | 78/95 | **83/95** |
| mean melody similarity | unknown | **68%** (71% excluding the 33 files the harness mis-scores — see work_remaining §1) |
| mean waveform agreement | not measured | **61%** |
| plays the same music (95–100%) | unknown | **19 files** |
| plays something else (<50%) | unknown | 18 files, of which **4 genuinely wrong** (work_remaining §4) |
| packs back to `.sid` | 50/78 | all converted files |
| tests | 177 | **326** (+2 skipped) |

`Commando.sid` → `Commando.sng` remains **byte-exact (15193 B)**.

## Commits this session (all pushed to `MichaelTroelsen/SIDDetector2`)

```
97971b6 v0.5.44  convert the Delta loader and I, Ball
d1ae827 v0.5.45  legalise the restart position, and measure fidelity
18b59f9 v0.5.46  the digi engine's rest is a key-off, not a hold
3f11136          handoff update
4bdbcfb v0.5.47  separate measured-wrong from converted-wrong, stage a listen
7b5b797 v0.5.48  convert ACE 2 and Chain Reaction
adfa5d6          handoff update
6875483 v0.5.49  repair empty voice orderlists unconditionally
d1866c2 v0.5.50  map Hubbard's pitch bends onto Goattracker's speed table
dbe9848 v0.5.51  decode the instrument effect byte where the player has it
d4b130b v0.5.52  Delta's interleaved repeats, bit-7 note flag, third grammar
b67169e v0.5.53  land the audit — AUDIT.md and its four unblocked fixes
3f54de4 v0.5.54  regenerate artefacts; rewrite the handoff
5f01175 v0.5.55  read a player whose table addresses its init writes over the code
40ee116 v0.5.56  measure waveform agreement, not just which notes are struck
83b4f78 v0.5.57  reject phantom patterns, honour the status byte, derive tempo per file
11c32af v0.5.58  regenerate on the settled tree; report what the harness cannot see
892d541 v0.5.59  census the instrument effect byte's real consumers
2345c30 v0.5.60  pack at the speed multiplier the player needs
```

## Third-wave findings (v0.5.55-58)

- **Devils Galop's table addresses are not in its code.** It reads pointers
  from `$1795-$1798`, nine bytes of zeroes nothing stores to; init at
  `$18B3` writes the real addresses over those operands a byte at a time.
  `sidfile.find_init_writes` walks from the PSID `initAddress`, follows the
  `init: JMP realinit` indirection, and stops at the first `JMP` taken after
  the routine starts. Gated to files whose tables as they stand name no
  patterns: **45 of 95 have findable init writes; exactly 1 has them
  applied**, and 189 of 190 corpus outputs are byte-identical.
- **The tempo "scatter" was mixed-voice medians.** The players gate their
  sequencer with a master countdown (Commando `$5054`), so one row lasts
  reload+1 frames; the shape matches 85/95 files. Truth: f=3 for 34 files
  (the old constant was accidentally right), f=4/5 for 10, **f=2 for 30**,
  6 underivable. Validated in RetroDebugger, not just siddump.
- **A phantom pattern entry corrupts the whole file through gt2reloc.**
  Last V8's `$1C` is unreferenced by any clean subtune, yet shipping the
  bit-6 fix took it 71% -> 3%: its garbage portamento became speed-table
  entries and `greloc.c:2184` re-encodes that table file-wide. The
  detection signature's own match offsets (`Detection.code_spans`) are now
  the proof that a decode span is player code.
- **survey.py was reporting a file convert() could convert.** It called a
  bare `detect()` while `convert()` has had its own detection path since
  v0.5.55. Caught by regenerating and seeing 79 where 80 was measured.

## The fidelity harness (v0.5.45/47) — the session's spine

`python/fidelity.py`: convert → legalise restart → pack with gt2reloc →
siddump both → compare **note attacks**; `--audio`/`--register` wire SIDM2's
deeper tools; a **slides** column since v0.5.50; rows whose packed subtune 0
is a zero-length stub are excluded from averages (exactly one: Rasputin,
now 56% after the empty-voice repair). `python/listen.py` stages a
listening pass (`build/listen/`, one median file per band — WAVs verified
real audio, **still unheard**).

## Player findings, each read out of the 6502 and landed

- **`$FE` = "tune ended"** in every classic dialect → `--legal-restart`
  (v0.5.45); all converted files now pack.
- **Digi rest is a key-off** (`$1184 DEC $165D,X`), not a hold (v0.5.46).
- **ACE 2 (v4)**: the VB6's `Case 4` appended nothing — every version-4
  orderlist came out empty; inherited bug, one line (v0.5.48). **Chain
  Reaction (v9)**: version 0's shape with `$FE` as its only marker (v0.5.48).
- **Empty-voice orderlists** repaired unconditionally (v0.5.49): greloc.c
  writes an invalid subtune as an in-place zero-length stub and truncates the
  subtune list at its `songs` count — reviving a voice also requires
  legalising that subtune's restart or the whole export aborts. With
  `--legal-restart` on, zero bytes changed corpus-wide.
- **The speed table was never written** (v0.5.50): a portamento's data byte
  is a packed value in GTS2 but a 1-based speed-table index in GTS3+
  (`gplay.c:740`), so every portamento this tool ever emitted was inert in
  the gts5 files the presets select. Corpus slides 7 → 1214 frames. Plus the
  **two-byte bend operand** (41 files have the second fetch) as `--slides`.
  Flash_Gordon 8% → 52% at the time. **Instrument byte +6 is a pulse-width
  sweep, not vibrato** — the handoff's proposed vibrato mapping was refuted
  before it was built ($12BF ends at `STA $D403,Y`).
- **+7 effect byte** (v0.5.51): bit $02 is a semitone rise every 4 frames
  (252 instrument records across 59 files), bit $04's zero-nibble arpeggio is
  silent in the player where the original substituted octave-up (half the
  corpus's arpeggio records). `--effects`, gated on detection finding the
  routine that reads the bits. Also fixed the `--slides` CLI forwarding.
- **Delta (v10)** (v0.5.52): orderlist carries repeat counts woven between
  pattern numbers ($BF85 DEC/BNE; only corpus file with the DEC form).
  Confirmation: all 13 subtunes' three voices come out exactly equal in
  frames. Delta 2% → **90%**. **Bit-7 note flag** (14 files): `AND #$7F`
  before the frequency lookup; clamping the raw byte collapsed every flagged
  note onto $BC. **Chicken_Song / Hollywood_or_Bust**: a third pattern
  grammar ("cmdtable") — command jump table with derived operand counts, a
  duration table (`6 12 24 36 72 48 96 18`), durations divided by their GCD
  with the factor handed to CMD_SETTEMPO. Chicken_Song 3% → **87%**.

## The audit (v0.5.53)

`AUDIT.md`: five verified defects (all now fixed — the `--slides` no-op via
dbe9848, the rest in b67169e), eight structural risks, learnings, ranked fix
order. `presets.json`'s `always` block now carries `slides` and `effects`.

## RetroDebugger (MCP) — validated, now the timing harness

`-S2` Commando measured in the emulator: play-call interval **9828 cycles =
$2663+1 = 100.25 Hz — exactly 2×**. The CIA-stub mechanism (greloc.c:1595)
is real and works. **siddump is structurally blind to it** (calls the play
routine seconds×50 times, ignoring the PSID speed field), which is why `-S`
looked like it moved the wrong way. Operational notes: stop/start does NOT
reset the machine; the built-in assembler rejects standard syntax —
hand-assemble via memory writes.
</work_completed>

<work_remaining>

## 1. The +14 transpose clamp — the largest known fidelity defect, and it is ours

Hubbard's orderlists carry transposes of **24, 36 and 48** (two to four
octaves). Goattracker's orderlist transpose tops out at `$FE` because `$FF`
is LOOPSONG, so `_transpose_byte` clamps at **+14** and every note under
such a step plays 10-34 semitones flat. The repo has documented the ceiling
since v0.5.25 and treated clamping as the safe choice; nobody checked what
Hubbard actually stores.

Confirmed by position-aligned modal semitone deltas, with controls: every
high scorer returns `+0` at 100% (Commando, Zoids, Crazy_Comets, Wiz, Rikky,
Off_the_Cuff, After_8), so a constant offset is a real file-specific error.
The arithmetic matches: One_on_One `24 -> 14` predicts -10, measured -9;
Kings_of_the_Beach_intro and Rock_Tells_the_Tale `36 -> 14` predict -22,
measured -21.

Affected: Kings_of_the_Beach_intro, One_on_One, Rock_Tells_the_Tale,
Powerplay_Hockey, Skate_or_Die_intro -- all at 100% modal share.

**The fix in principle:** these are octave multiples, so split `T` into
`T mod 12` in the orderlist and fold `12k` into the pattern's note values
(GT notes span `$60`-`$BC`, ~7.75 octaves of headroom). The cost is
per-(pattern, octave-shift) variants against the 208-pattern limit -- a
design call, not a one-liner. Rock's 17 and 19 are clamped too but are not
octave multiples, so they need the same split with a non-zero remainder.

## 2. Wavetable Phase 2 — re-scope from the Phase 1 census, not the old plan

Phase 1 (v0.5.59) inventoried every `+7` consumer from the players' code and
documented two blocks for the first time: the `$01` **drum** is a per-frame
downward pitch sweep into `$D401` that writes `#$80` to `$D404` only on the
exhausted branch (h2g emits two wavetable entries -- the noise gesture, no
sweep), and `$08` selects between a triangle sweep into `$D403` and an
`ADC`-accumulate of `+6` into the instrument's own `+0` written to `$D402`,
storing the running total **back into the record** so `+0` cannot be read
statically in those 21 files.

| bit | block in files | records set | in a file with the block | tests it **without** the block |
|---|---:|---:|---:|---:|
| `$01` drum | 44 | 447 | 299 | 25 |
| `$02` rise | 4 | 276 | 12 | 52 |
| `$04` arpeggio | 13 | 634 | 167 | 62 |
| `$08` pulse-lo | 21 | 294 | 59 | 34 |

**467 of the 634 arpeggio records are in players with no arpeggio routine,
and the builder arpeggiates all 634**; the drum figure is 148 of 447. That
is the defect `--effects` was gated to prevent in v0.5.51, still present in
the unconditional part of the wavetable.

So Phase 2 is not "stop fabricating where nothing is detected": the arpeggio
is the larger invention, the drum needs **suppressing and deepening** at
once, and `+6` needs a dynamic read in 21 files. `Detection.effect_drum` and
`effect_pulse_lo` exist and are logged; nothing consumes them yet.

This also resolves the Phase 0 tension: the corpus under-produces noise
(5710 vs 11641) *while* inventing it in 148 records -- our two-entry drum is
thinner than the real sweep where the routine exists and pure invention
where it does not. Both errors at once, which is why the aggregate looked
like simple under-production.

## 3. The listening pass — never performed, and now eleven versions overdue

`build/listen/` predates v0.5.49. Regenerate with `listen.py` and play four
files. Everything the attack metric is blind to -- slides, effects, gate
lengths, tempo feel, waveform -- has only ever been checked by disassembly.
It is the one check that can catch an error shared by the reading *and* the
metric, which this project has hit repeatedly.

## 4. Only 4 files genuinely play the wrong music

The `<50%` bucket was 18 files and is mostly mislabelled. Partitioned by
per-voice modal delta:

| class | n |
|---|---:|
| constant transposition (item 1) | 5 |
| a whole voice missing | 3 |
| converts to silence (`Phantoms_of_the_Asteroid`, `rows: 0`) | 1 |
| rate artefact only (`Flash_Gordon`, `+0@100%`) | 1 |
| original near-silent in the window (denominator <= 4) | 4 |
| **genuinely scrambled** | **4** |

The four: `Action_Biker`, `Commodore_64_Music_Examples`,
`Dragons_Lair_Part_II`, `Hollywood_or_Bust` (partial -- v1 is `+0@100%`).

## 5. Three unexplained residuals

- **Exactly +1 semitone**, 100% consistent, on Powerplay (all three voices),
  Skate_or_Die (both), and the low-transpose voice of Kings, One_on_One and
  Rock. Not dialect-linked: Skate_or_Die is classic, the others digi, and
  the digi controls all return `+0`.
- **IK_plus and I_Ball each lose exactly 83 attacks on voice 2**, both
  version 7. The same number in two files is unlikely to be coincidence --
  one look at the version-7 third-voice path.
- **A rate error that is not the multiplier.** Chain_Reaction's attack rate
  is 0.66x the original's, not 0.5x, and stays 0.66x when the trace window
  doubles. Found while testing (and rejecting) a longer-window workaround.

## 6. Measuring the `-S2` group needs a cycle-accurate trace

v0.5.60 wires `-S` into all three packing paths, so those files now *play*
correctly -- verified in the emitted bytes (latch `$2663` = 100.25 Hz). It
does **not** move their scores and nothing at the packing step can: siddump
calls the play routine `seconds x 50` times regardless of the PSID speed
field, so `-S` changes the packed bytes and not the trace. A/B on
Chain_Reaction is identical to the digit either way. Tracing our side for
`seconds x multiplier` is not a substitute (helps 2 files, hurts 1 -- see
the 0.66x finding above). RetroDebugger is the tool; the driver pattern is
in critical_context.

## 7. Three prescaler players have no expressible rate

Mozart, Ninja and Mega Apocalypse run the player v of every v+1 calls
(effective 1.5x, 4x-with-jitter, unknown). No steady Goattracker tempo
expresses them; they keep the constant. Needs a design idea.

## 8. Smaller items

- Per-subtune tempo applies only while group numbering matches the PSID
  header; a split subtune falls back to subtune 0's timebase.
- `find_init_writes` steps over `JSR`s, so a helper's writes are missed. An
  under-read: it can fail to rescue a file, never invent a rescue.
- `SURVEY.md`'s `Ver` column shows the *orderlist* family for digi files
  (they detect as version 2 or 7 with `dialect=digi`), so the digi engine is
  invisible there. Cosmetic, but it has cost a fork a detour.
- Pulse-width tracking (siddump's `Pul` column) is the next fidelity
  dimension after wave; noted in `fidelity.py`, not built.
- 3 files still fail at survey defaults (`Delta`, `Dragons_Lair_Part_II`,
  `W_A_R`, all `TOO MANY NEW PATTERN CREATED`) but convert under presets.
</work_remaining>

<attempted_approaches>

## Premises refuted this session — do not resurrect

1. **"~7× too many re-triggers"** — a grep counting three siddump event
   types alike. Real ratio 0.78/0.98 median; the 7× belongs to
   Rock_Tells_the_Tale alone.
2. **"`0xBD` hold rows re-trigger"** — $BD is a no-op in the note column
   (`gplay.c:908-941`); the editor writes it into blank rows itself.
3. **"`gatetimer` holds a note length"** — it is a compare value against a
   per-row countdown, capped at `tempo` (`gplay.c:334`). Every encoding
   built on it (per-duration variants, modal, hybrid) is void.
4. **"The fabricated wavetable invents noise"** — zero corpus files invent
   noise; we produce *half* the original's. The error is misplaced class.
5. **"Devils Galop needs a table-copy reader"** — its init writes over the
   *operands in its own code*; the block copy moves instrument records.
6. **"GT's gate mask is sticky, so per-note `$BE` collapses attacks"** —
   `firstwave = 0x09` re-opens the gate on every note (`gplay.c:356-363`).
   The collapse has a different, still-unconfirmed cause.
7. **"The tempo scatter is per-file variance"** — it was per-voice medians
   over a mixed-voice measurement. The real distribution is four values.
8. **"Wiring `-S` will unblock the 33 mis-scored files"** — it will not, and
   nothing at the packing step can. siddump calls the play routine
   `seconds x 50` times regardless of the PSID speed field, so `-S` changes
   the packed bytes and not the trace. A/B identical to the digit.
9. **"The 18 sub-50% files are playing something else"** — 5 are a constant
   transposition we introduced, 3 are missing a voice, 4 have a near-silent
   original in the window, 1 is silent, 1 is a rate artefact. Four are
   genuinely scrambled.
8. **"The slide gap explains the low melody scores"** — no correlation
   (47 slide-heavy files: 67%; 21 slide-free files: 66%). It is an
   *ornamentation* defect, real and now fixed, but invisible to attacks.
4. **"Instrument +6 is vibrato"** — it is a pulse-width sweep
   ($12BF → `STA $D403,Y`). The proposed mapping would have encoded a
   duty-cycle sweep as pitch modulation.
5. **"3 calls per row is the floor" as a corpus-wide constant** — the row
   rate is a per-file scatter; 19 files are already exact and a global
   `-S3` would wreck them.
6. **"gt2reloc renumbers subtunes"** — nothing is renumbered; invalid
   subtunes become in-place zero-length stubs and the count truncates the
   tail. (And the repair MUST legalise the revived subtune's restart or
   greloc.c:244 aborts the whole export — measured, Rasputin went from
   "packs 15 of 17" to "packs nothing" with the naive fix.)
7. **"Delta has a pattern-table undercount"** — the table was right; the
   orderlist was carrying interleaved repeat counts.

## Process lessons

- **A metric that cannot see a change is not evidence the change did
  nothing** — hit three separate times (digi rest, slides, effects). Say in
  the doc, next to the fix, which metric is blind to it.
- **Re-measure a fork's numbers on the settled tree before quoting them**
  (the digi-rest retrig "improvement" did not reproduce; a controlled
  baseline attributed the Rasputin gain to the right commit).
- **When two readings of a table are both plausible, the one under which
  the three voices agree in length is the player's** (Delta v10 proof).
- **Phantom table entries make correct fixes net-negative** — check what an
  unreferenced entry decodes to before changing how bytes decode.
- Fork hygiene that worked: scratchpad trees + unified diffs against a
  pristine copy; reconstructed HEAD+own-hunks blobs for shared files;
  refusing to commit into an entangled tree; `git merge-file` for the
  3-way landing (mind CRLF — plain `patch` fails on line endings).
- **Bash here-strings with `->` arrows create stray files** (`pack`,
  `siddump`, `compare` appeared in the repo root once). Multi-line commit
  messages go in a scratchpad file, `git commit -F`.

## Environment gotchas (cumulative)

- `dis6502.py` (never `dis.py`) in `$TMP` — usage:
  `python dis6502.py <sid> <hex addr> <count>`.
- pytest from `python/`; PowerShell scripts need the PowerShell tool.
- gt2reloc: test for the output file, never the exit code; short paths
  (`C:\t\`); bare filenames with cwd set.
- SIDM2 tools run with cwd = SIDM2 root.
- RetroDebugger: stop/start does not reset; hand-assemble via memory
  writes; it honours CIA timing (siddump does not).
- csdb.dk 503s automated fetches.
</attempted_approaches>

<critical_context>

## Invariants

- **`Commando.sng` byte-exact (15193 B).** Every output-changing option is
  opt-in; `--max-rows` 94 and `--format` gts2 stay the defaults.
- **Bump the version every commit** (`python python/bump_version.py "…"`);
  regenerate `SURVEY.md` (with `--legal-restart --gt2reloc`),
  `presets.json`, and `FIDELITY.md` on every conversion-changing commit,
  from `python/`, only on a settled tree.
- **Never ship a fake success**; a correct fix that is net-negative on the
  corpus gets recorded, not shipped (bit-6 status byte).
- Every orderlist-structure change needs the playback-equivalence check
  (`test_pack_repeats.py` harness).
- Stage `hubbard/` paths only, by pathspec — the repo also contains
  unrelated sibling projects (`siddetector2/`, `SIDM2`).

## Verified Goattracker facts (from source)

```
MAX_PATT 208  MAX_PATTROWS 128  MAX_SONGLEN 254  MAX_INSTR 64
FIRSTNOTE $60 LASTNOTE $BC  REST $BD (no-op)  KEYOFF $BE  KEYON $BF
REPEAT $D0    TRANSDOWN $E0  TRANSUP $F0  LOOPSONG $FF
```
- Transpose $E0..$FE → −16..+14; +15 unrepresentable.
- Tempo 0/1 = funktempo; fastest steady row = tempo 2 = 3 calls.
- CMD_SETTEMPO value & $7F, ≥$80 = this channel only (gplay.c:494).
- GTS3+ portamento data = 1-based speed-table index (gplay.c:740); GTS2
  loader converts on read (gsong.c:311-321).
- greloc.c: restart ≥ songlen rejected (:244); zero-length voice = subtune
  stub + tail truncation (:200-255, :653, :701-706); `-S` sets a CIA stub
  (:1595) **and** DEFAULTTEMPO = 6×multiplier−1 (:1143); instrument 63's AD
  can override DEFAULTTEMPO (:1141).
- siddump calls play seconds×50 times regardless of PSID speed — blind to
  the multiplier.
- Effective instrument ceiling 51, clamped at 50.

## Key paths

| | |
|---|---|
| Corpus (95 files) | `C:\Users\mit\claude\c64server\SIDM2\SID\Hubbard_Rob` |
| GoatTracker 2.77 + source | `C:\Users\mit\Downloads\GoatTracker_2.77` |
| `gt2reloc.exe` / `siddump.exe` | `…\GoatTracker_2.77\win32\`, `SIDM2\tools\` |
| Short scratch for gt2reloc | `C:\t\` |
| SIDM2 accuracy tools | `SIDM2\pyscript\audio_tightness_tool.py`, `SIDM2\scripts\validate_sid_accuracy.py` |

## Non-obvious behaviours

- `command_floor(version)`: $FF for 0/1/3/4/5, $F0 for 2/6/7/8, $FE for 9;
  version 10 shares version 0's floor.
- `presets.json` `always` = gts5, tempo auto, legal_restart, slides,
  effects, gt2reloc — what makes a preset reproduce its recorded bytes.
- `Detection.frames_per_row` ≠ 1 only in the cmdtable dialect.
- Opening output in GoatTracker requires gts5 (GTS2 importer overrun).
- The dialect registry: 0/1/3 Warhawk-family, 2 AWM (two-byte transpose
  sub-variant), 4 ACE 2, 5 BoB, 6 Mega Apocalypse, 7 IK+, 8 digi,
  9 Chain Reaction, 10 Delta, plus the cmdtable pattern grammar.
</critical_context>

<current_state>

## Status: all work committed; tree clean

- **HEAD `2345c30` (v0.5.60)** on
  `https://github.com/MichaelTroelsen/SIDDetector2.git` (private).
- **326 tests pass, 2 skipped** (from `python/`). `Commando.sng` byte-exact.
- `SURVEY.md`, `presets.json`, `FIDELITY.md` are current as of **v0.5.58**.
  v0.5.59 is inventory-only (190 corpus conversions byte-identical) and
  v0.5.60 changes no `.sng` bytes, so they are not stale -- but the first
  wavetable Phase 2 commit will change conversion, and one regeneration
  after it is the honest one.
- `presets.json`'s `always` block: gts5, tempo auto, legal_restart, slides,
  effects, status_bit6, reject_phantoms, gt2reloc. Per-song `multiplier` is
  now consumed by all three packing paths.

## Open decisions

1. **The +14 transpose clamp** (§1) — the largest known fidelity defect and
   the one with a named root cause. Needs a design call on pattern variants
   against the 208-pattern limit.
2. **Wavetable Phase 2** (§2) — re-scoped by the census; the arpeggio is the
   larger invention and the drum needs deepening as well as gating.
3. **Listen** (§3) — eleven conversion-changing versions have shipped unheard.
4. The three residuals (§5) — the +1 semitone, the version-7 voice 2, and
   the 0.66x rate error.

## The gap, restated

At v0.5.43 the corpus converted and nobody knew whether it played the right
music. At v0.5.60 there are two independent measures, ten player-semantics
defects are fixed with the 6502 as ground truth, the harness states its own
blind spots inside the report it generates, and the sub-50% bucket has been
partitioned into named causes rather than left as a list.

The sharpest way to put the remaining work: **the two largest known fidelity
defects are both ours, not the format's** -- a transpose clamp that detunes
five files by up to 34 semitones, and a wavetable that invents an arpeggio
for 467 instrument records whose players have no arpeggio routine. Both were
invisible until a metric was built that could see them. And in eighteen
versions of fidelity work, exactly one file has ever been listened to.
</current_state>
