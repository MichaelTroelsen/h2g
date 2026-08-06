<original_task>
Continuation of work on `C:\Users\mit\claude\c64server\hubbard` — **H2G**, a
converter from Rob Hubbard `.sid` files to Goattracker `.sng`. The current
session began from a handoff at **v0.5.43** (75/95 converting, 177 tests, one
open claim about re-triggering that turned out to be a miscount) and ran to
**v0.5.58** through three waves of concurrent `/subtask` forks.

The user's requests, in order: read the handoff; a first wave of forks
(gplay.c read, illegal restart, fidelity harness, coverage tail, digi note
path); commit and push; update this file; a second wave (vibrato mapping →
became the slides/speed-table work, Delta/Chicken_Song investigation, tail
truncation, speed multiplier, +7 effect byte, a project audit); "retrodebugger
MCP is also available"; a serialisation pass; then a third wave (per-file
tempo, phantom pattern entries, wavetable Phase 0, Devils_Galop, the digi
tie-flag census) and a second serialisation pass.

The serialisation discipline that emerged over both waves: forks work in
scratchpad copies or stage reconstructed HEAD+own-hunks blobs; the main
thread lands their work in dependency order, one version bump per commit,
artefacts regenerated only on a settled tree, everything staged by pathspec.
</original_task>

<work_completed>

## Headline result

| | session start (v0.5.43) | now (v0.5.58) |
|---|---:|---:|
| corpus at defaults | 75/95 | **80/95** (80/83 in reach = 96%) |
| best per-song options | 78/95 | **83/95** |
| mean melody similarity | unknown | **68%** (71% excluding the 33 files the harness mis-scores — see work_remaining §1) |
| mean waveform agreement | not measured | **61%** |
| plays the same music (95–100%) | unknown | **19 files** |
| plays something else (<50%) | unknown | **18 files** |
| packs back to `.sid` | 50/78 | all converted files |
| tests | 177 | **325** (+2 skipped) |

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

## 1. Wire `-S` into the packing step — highest value, smallest job

Per-file tempo landed in v0.5.57, but **nothing passes `-S` to gt2reloc**.
30 files whose players advance one row every 2 frames now carry a
`multiplier` in `presets.json` and are packed at 1x anyway, so they play
uniformly 2x slow and **33 of 83 measured files score below their real
fidelity**. The corpus mean reads 68%; excluding them it is 71%, and every
file the harness *can* measure improved or held (multiplier 1: mean +1.7,
7 up, 0 down; multiplier 2: mean -9.3, 28 down).

The work is plumbing, not research: read `multiplier` in `fidelity.py`'s
pack step, `convert.ps1` and `play.ps1`, and pass `-S{m}`. The mechanism is
already validated in RetroDebugger. **Do this before judging any other
fidelity number** — a third of the corpus is currently mis-scored.

Caveat that survives the fix: siddump still cannot see `-S`, so those files
need a cycle-accurate emulator to measure even once packed correctly.
RetroDebugger is that tool and the driver pattern is recorded below.

## 2. The wavetable — Phase 0 done, and it refuted its own premise

`FIDELITY.md` now carries a **wave** column (per-frame waveform-class
agreement) and noise counts. Corpus mean **61%**, median 65.5%.

The prediction was that the fabricated wavetable invents noise on the ~70
files whose players have no drum routine. Measured: **zero** files invent
noise, 16 files where the original drums get none from us, and corpus noise
is 5710 ours against 11641 original. The error is **under-production and
misplaced class per frame**, not invention — so the queued Phase 2 ("stop
fabricating where nothing is detected") is aimed the wrong way and should be
re-scoped from Phase 1's census output.

`Nineteen` is the case to hold on to: melody 100%, wave 21%. Right notes,
wrong instrument, every frame — invisible to every metric this project had
before v0.5.56.

Phase 1 (inventory every `+7` consumer from the players' code, emit the
census into `H2G-CONVERSION-METHOD.md`) is unchanged and still the next step.
Phases 1-3 touch `detect.py`.

## 3. The listening pass — never performed, and now overdue

`build/listen/` holds verified-real WAVs but they predate v0.5.49. Eight
conversion-changing versions have landed since, every one validated against
the 6502 and none of them audible to anyone. Regenerate with `listen.py`
and play four files. This gates any claim of success on items 1 and 2, and
it is the only check that can catch an error shared by both the disassembly
reading and the metric.

## 4. Why 18 files still play something else

Ruled out across the session: subtune misalignment, measurement error, the
slide gap, three dialect misreadings (now fixed), and phantom pattern
entries (now gated). The remaining `<50%` bucket is 18 files; some are in
the `-S2` group and will move on item 1 alone, so **re-read this list after
the multiplier wiring lands** rather than starting from the current one.

Known individual: `Delta_Mix-E-Load_loader` — the player patches voice 0's
orderlist byte `$18` -> `$1D` at runtime; we emit the on-disk `18 FF` and
loop `$18` forever.

## 5. The digi tie flag — folded into the wavetable work, not standalone

**The `gatetimer` framing in the previous handoff was wrong.** It is not a
note-length field: `cptr->tick` counts down and reloads to `cptr->tempo` at
the row boundary (`gplay.c:318`, `:322-330`), and `gatetimer` is only a
compare value against that countdown (`:854`, `:905`) -- "release this many
ticks *before the row ends*", bounded by `gatetimer <= tempo` (`:334` calls
`stopsong()` otherwise). It cannot hold a 1-32 frame per-note duration, so
per-duration instrument variants, modal gatetimer, and the hybrid are all
void.

Bits 6/7 *do* map (6 = no gate-off = tie, 7 = no ADSR reset = the `$11A9`
skip), so the tie half translates; the numeric half has nowhere to go
except the **wavetable**, since `sidreg[0x4] = cptr->wave & cptr->gate`
(`:951`) and `cptr->wave` advances per frame. That is per-instrument, so it
inherits the ceiling the census measured: 4 of 9 digi files need more than
50 `(instrument, duration)` variants. The question therefore belongs to
item 2, not to itself.

Census, for whoever picks it up: 1079 tied of 10509 notes (**10.3%**, not
the 93%-clear figure quoted earlier), 21 distinct waits concentrated on
wait 3 (4403 notes) and wait 1 (3358).

Also corrected: the 102 -> 4 attack collapse was **not** GT's gate mask
being sticky -- `firstwave = 0x09` makes `gplay.c:356-363` set
`cptr->gate = 0xff` on every new note, so a `$BE` row cannot wedge it shut.
The live hypothesis is row budget (One_on_One is 64% notes of <=2 frames,
Rock_Tells_the_Tale 71%, and a keyoff needs a row to live in). **Unconfirmed
-- the experiment was not re-run.**

## 6. Three prescaler players have no expressible rate

Mozart, Ninja and Mega Apocalypse run the player v of every v+1 calls
(effective 1.5x, 4x-with-jitter, unknown). No steady Goattracker tempo
expresses them; they keep the constant. Needs a design idea, not a fix.

## 7. Smaller items

- **Presets record `multiplier` but nothing consumes it** — same root as
  item 1.
- Per-subtune tempo applies only while group numbering matches the PSID
  header; a split subtune falls back to subtune 0's timebase.
- `find_init_writes` steps over `JSR`s, so a helper's writes are missed.
  An under-read: it can fail to rescue a file, never invent a rescue.
- Pulse-width tracking (siddump's `Pul` column) is the obvious next
  fidelity dimension after wave; noted in `fidelity.py`, not built.
- 3 files still fail at survey defaults (`Delta`, `Dragons_Lair_Part_II`,
  `W_A_R` — all `TOO MANY NEW PATTERN CREATED`) but convert under presets.
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

- **HEAD `11c32af` (v0.5.58)** on
  `https://github.com/MichaelTroelsen/SIDDetector2.git` (private).
- **325 tests pass, 2 skipped** (from `python/`). `Commando.sng` byte-exact,
  with `--status-bit6` on as well as off.
- `SURVEY.md`, `presets.json`, `FIDELITY.md` regenerated once on the settled
  tree at v0.5.58: **80/95** converted, **83/95** with presets, mean melody
  **68%** (71% excluding the mis-scored `-S2` group), mean wave **61%**,
  buckets 19 / 15 / 31 / 18.
- `presets.json`'s `always` block now carries `status_bit6` and
  `reject_phantoms` alongside gts5 / tempo auto / legal_restart / slides /
  effects / gt2reloc.

## Open decisions

1. **Wire `-S` into packing** (item 1) — plumbing, unblocks a third of the
   corpus's fidelity numbers. Nothing else should be judged before it.
2. **Wavetable Phase 1 census**, then re-scope Phase 2 from its output
   (item 2) — the original Phase 2 aim is refuted.
3. **Listen** (item 3) — eight conversion-changing versions have shipped
   unheard.
4. Prescaler players (item 6) — needs an idea, not an implementation.

## The gap, restated

At v0.5.43 the corpus converted and nobody knew whether it played the right
music. At v0.5.58 there are two independent measures — attacks and waveform
class — eight player-semantics defects are fixed with the 6502 as ground
truth, and the harness states its own blind spots inside the report it
generates. The honest summary is narrower than the numbers look: **a third
of the corpus is currently measured at the wrong speed**, and the fix for
that is an afternoon of plumbing rather than research. After it, the
remaining unknowns are the wavetable, the ~18 genuinely wrong files, and
the fact that in fifteen versions of fidelity work **exactly one file has
ever been listened to**.
</current_state>
