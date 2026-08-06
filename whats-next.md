<original_task>
Continuation of work on `C:\Users\mit\claude\c64server\hubbard` — **H2G**, a
converter from Rob Hubbard `.sid` files to Goattracker `.sng`. The current
session began from a handoff at **v0.5.43** (75/95 converting, 177 tests, one
open claim about re-triggering that turned out to be a miscount) and ran to
**v0.5.53** through two waves of concurrent `/subtask` forks.

The user's requests, in order: read the handoff; a first wave of forks
(gplay.c read, illegal restart, fidelity harness, coverage tail, digi note
path); commit and push; update this file; a second wave (vibrato mapping →
became the slides/speed-table work, Delta/Chicken_Song investigation, tail
truncation, speed multiplier, +7 effect byte, a project audit); "retrodebugger
MCP is also available"; and a final serialisation pass landing everything.

The serialisation discipline that emerged over both waves: forks work in
scratchpad copies or stage reconstructed HEAD+own-hunks blobs; the main
thread lands their work in dependency order, one version bump per commit,
artefacts regenerated only on a settled tree, everything staged by pathspec.
</original_task>

<work_completed>

## Headline result

| | session start (v0.5.43) | now (v0.5.53) |
|---|---:|---:|
| corpus at defaults | 75/95 | **79/95** (79/83 in reach = 95%) |
| best per-song options | 78/95 | **82/95** |
| mean melody similarity | unknown | **71%** |
| plays the same music (95–100%) | unknown | **17 files** |
| plays something else (<50%) | unknown | **17 files** |
| packs back to `.sid` | 50/78 | all converted files |
| tests | 177 | **274** (+2 skipped) |

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
```

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

## 1. Per-file tempo — the mechanism is now fully understood, the code isn't

`tempo_command_value()` (`goatwriter.py:113-121`) returns a constant for
every file and ignores its `SidFile` argument (the help text was fixed in
v0.5.53; the function still wasn't). Measured across 74 packable files the
row rate is a **scatter**: 24 correct, 22 too fast, 24 too slow, 4 at 3×+.
Solved per file: 19 already exact, 11 fixable by tempo alone, 36 need a
multiplier (mostly `-S2`: Commando `-S2 tempo 3`), 8 probably estimator
noise. A global `-S3` would be actively harmful. The work: derive per-file
tempo in `tempo_command_value()`, emit a per-file `-S` recommendation into
`presets.json`, and validate with RetroDebugger — **siddump cannot see CIA
timing**.

## 2. Why 17 files still play something else

Ruled out: subtune misalignment, measurement error, the slide gap (no
correlation with melody score), and — for Delta/Chicken/HoB — three whole
dialect misreadings now fixed. Remaining <50% bucket: Action_Biker 13%,
BMX_Kidz 0% (silent), Commodore_64_Music_Examples 14%, Delta_Mix-E-Load 10%
(known: the player patches voice 0's orderlist byte $18→$1D at runtime),
Dragons_Lair_Part_II 8%, IK_plus 35%, Kings_of_the_Beach_intro 0%,
Knucklebusters 30%, One_on_One 0%, Phantoms_of_the_Asteroid 0%,
Powerplay_Hockey 18%, Rock_Tells_the_Tale 0% (retrig 6.62),
Saboteur_II 26%, Samantha_Fox 5%, Skate_or_Die_intro 5%, Hollywood_or_Bust
49%, I_Ball 43%. Several of the 0% files are digi-engine — the tie flag
(item 4) may be a common cause. RetroDebugger's memory breakpoints on the
orderlist fetch are the right tool now.

## 3. The bit-6 status byte — correct, verified, blocked on phantom entries

`BIT status / BVS` (Commando $50CF, Last V8 $80DC) skips operand and note
reads; $C0-$FE consumes only itself where the decoder consumes three bytes.
Shipping it takes Last_V8 71% → 3% because pattern entry `$1C` is a
**phantom** (points into the player's own track selector — an artefact of
the `hi - lo - 1` count heuristic) and the wrong decoding is luckier there.
Fix phantom detection first (an entry whose pointer lands in code, or that
no orderlist references), then land the status byte. Recorded in
H2G-CONVERSION-METHOD.md §4.2 and §5.

## 4. The digi tie flag — design decision still open

93% of digi notes should gate off at the end of their duration; they play
legato. Per-note $BE collapses attacks (One_on_One 102 → 4); GT's
`gatetimer` is the native form but per-instrument where the duration is
per-note. Likely shape: synthesise per-duration instrument variants. Worth
revisiting now that three of the digi files sit at 0%.

## 5. The fabricated wavetable — the last big unexamined area

~24,647 ties against the original's slides looked like the two-step
arpeggio wavetable standing in for pitch movement. v0.5.50/51 fixed the
slide and +7 halves; whether the wavetable fabrication itself is justified
per file (~70 files get one) has never been checked against the players.

## 6. Devils_Galop — the one genuine conversion failure left

Pattern fetch names `$1797,Y`/`$1798,Y`; the region is zeros on disk; an
init loop at `$18E7` copies 120 bytes in at runtime. Needs a table-copy
reader plus a "table of zeros is not a table" guard. (`find_relocation`
only consults relocations for addresses that resolve *nowhere*.)

## 7. The listening pass — still never performed

`build/listen/` holds verified-real WAVs (regenerate first — they predate
v0.5.49–53): Flash_Gordon, Star_Paws, 5_Title_Tunes, Wiz. Everything the
attack metric is blind to (slides, effects, gate lengths, tempo feel) has
only ever been validated by disassembly, never by ear. This gates
declaring victory on items 1, 4 and 5.
</work_remaining>

<attempted_approaches>

## Premises refuted this session — do not resurrect

1. **"~7× too many re-triggers"** — a grep counting three siddump event
   types alike. Real ratio 0.78/0.98 median; the 7× belongs to
   Rock_Tells_the_Tale alone.
2. **"`0xBD` hold rows re-trigger"** — $BD is a no-op in the note column
   (`gplay.c:908-941`); the editor writes it into blank rows itself.
3. **"The slide gap explains the low melody scores"** — no correlation
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

## Status: all work committed and pushed; tree clean

- **HEAD `<pending push>` — v0.5.53 plus the artefact/handoff commit**, on
  `https://github.com/MichaelTroelsen/SIDDetector2.git` (private).
- **274 tests pass, 2 skipped** (from `python/`). `Commando.sng` byte-exact.
- `SURVEY.md`, `presets.json`, `FIDELITY.md` regenerated at v0.5.53:
  79/95 converted, 82/95 with presets, mean melody **71%**, buckets
  17 / 26 / 22 / 17.

## Open decisions

1. Per-file tempo derivation + `-S` recommendations (item 1) — mechanism
   proven, implementation not started.
2. Phantom pattern entries, then the bit-6 status byte (item 3).
3. Digi tie flag encoding (item 4).
4. Whether the fabricated wavetable is justified per file (item 5).
5. **Listen to something** (item 7) — still the only unstarted validation.

## The gap, restated

At v0.5.43 the corpus converted but nobody knew if it played the right
music. At v0.5.53 fidelity is measured (71% mean, 17 files essentially
exact), five separate player-semantics defects are fixed with the 6502 as
ground truth, and the harness knows its own blind spots. What is left
splits cleanly: timing (item 1), the 17 wrong files (item 2), and the
things only ears can check (item 7).
</current_state>
