# Documentation audit — hubbard/

- **Tree state:** `98f1271` at audit start. **Working tree was dirty and changing
  during the audit** — a concurrent task was editing `goatwriter.py`, `cli.py`,
  `convert.py`, `sidfile.py`, `survey.py` and `README.md` to add a `--tempo`
  feature. Findings describe the tree as read; two files moved under me mid-audit
  (noted per-finding).
- **Ground truth established before reading prose:** version `0.5.15`
  (`python/h2g/__init__.py`), 48 tests passing, CLI flags read from `--help`,
  Goattracker limits read from `GoatTracker_2.77/src/gcommon.h`.
- **Scope:** `README.md`, `CLAUDE.md`, `H2G-CONVERSION-METHOD.md`, `CHANGELOG.md`
  (latest entry only), `SURVEY.md`. All read in full. No delegation, no sampling.

---

## Findings

### P1 — actively misleading

Each of these would cause a reader to take a wrong action: re-introduce a fixed
bug, re-investigate a settled question, or ship output that crashes the target.

**1. `wait == 0` documented as an open question and a dropped event** — FIXED
`H2G-CONVERSION-METHOD.md` §5 claimed *"`wait == 0` emits nothing at all … Not
resolved here"*, and §10 listed *"`wait == 0` events dropped"* as a live failure
mode.
*Verification:* `grep -n "wait" python/h2g/patterns.py` → line 109,
`"An event lasts wait+1 frames, so it always emits at least its own row."`, with
the `DEC`/`BMI` disassembly cited in-code.
*Confidence:* HIGH. Replaced with the resolved semantics and the disassembly.

**2. The `end_marker` latch described as a live bug, with a "fix it" advisory** — FIXED
§8 carried a full subsection *"…but the latch is a real bug for transposing
players"* plus a boxed instruction to fix it when porting.
*Verification:* `grep -n "end_marker\|expect_operand" python/h2g/patterns.py` →
no `end_marker`; `expect_operand` at 225–234.
*Confidence:* HIGH. Rewritten as history, retaining the transferable lesson.

**3. "*(No validation exists.)*"** — FIXED
§10 item 1 asserted no address validation existed.
*Verification:* `python/h2g/detect.py:64` logs
`*** … ADDRESS OUT OF RANGE (offset …, file … bytes) ***`;
`python/tests/test_address_validation.py` exists.
*Confidence:* HIGH. §10 restructured into "still open" vs "closed since written".

**4. No mention of GTS5 or the GTS2 importer overrun** — FIXED
*Verification:* `grep -c "GTS5" H2G-CONVERSION-METHOD.md` → **0** before the fix.
The document teaches a method whose output, followed literally, produces GTS2
files that crash GoatTracker on play. This is the project's most consequential
finding and it was absent from its own learning document.
*Confidence:* HIGH. New §9 subsection added with the `gsong.c` loop quoted.

### P2 — wrong but lower consequence

**5. Goattracker limits table had 2 of 3 values wrong** — FIXED
§8 gave *"Max rows per pattern 94"* and *"Max orderlist length `0xFF` = 255"*,
presenting H2G's own slice length as a Goattracker constraint.
*Verification:* `gcommon.h:34` `MAX_PATTROWS 128`, `:35` `MAX_SONGLEN 254`,
`:30` `MAX_PATT 208`.
*Confidence:* HIGH. Table now separates the format's limit from H2G's choice.

**6. "large instrument count = over-read" was unqualified** — FIXED
§4.1's caveat is fair in principle, but the surrounding material invited reading
56–59-record tables as runaway terminators.
*Verification (independent, not inherited):* dumped instrument records for four
corpus tunes — Bangkok Knights ∩ Thundercats share **29 byte-identical 8-byte
records**; `00 81 81 05 63 fd 00 00` recurs across three tunes; 2 of 58 records
all-zero. A shared Hubbard instrument bank, not padding.
*Confidence:* HIGH. Note added, including that the binding limit is 51
(wavetable entries), not `MAX_INSTR` 64.

**7. Testing section understated coverage and overstated its meaning** — FIXED
`README.md` named 2 test files; 8 exist. It also implied byte-exactness was
sufficient evidence of correctness.
*Verification:* `ls python/tests/*.py` → 8 files; `pytest -q` → `48 passed`.
*Confidence:* HIGH. Rewritten as three layers, with an explicit note that none
of them prove a song plays.

**8. `README.md` layout table omitted `convert.ps1`, `play.ps1`, `build/`** — FIXED
*Verification:* `ls *.ps1` → both exist; `.gitignore:3` → `build/`.
*Confidence:* HIGH.

**9. `CLAUDE.md` never mentioned that GoatTracker needs `--format gts5`** — FIXED
An agent following `CLAUDE.md` alone would produce crashing files.
*Confidence:* HIGH. Bullet added.

### Root cause — duplicated truth

**10. CLI flag lists were restated in three documents** — FIXED by canonicalising
`README.md`, `CLAUDE.md` and `H2G-CONVERSION-METHOD.md` each enumerated flags.
This drifted twice *during this audit*: `--format` landed before I started and
`--tempo` landed while I was editing.
*Fix applied:* prose now points at `--help` as authoritative instead of copying
the list. `README.md` keeps the per-flag explanatory sections — those carry
reasoning, not an inventory.

---

## Not fixed — deliberately

**`python/survey.py` still generates over-read prose.** Lines 223–225 and 243
emit *"the waveform-sniffing table-end heuristic is over-reading past the real
instrument table"* and an `instr over-read` column flag, both contradicted by
finding 6. `SURVEY.md` currently shows 6 such rows.
*Not fixed because:* it is generator code, and a concurrent task was editing
adjacent files. The equivalent message in `goatwriter.py` has already been
corrected by that task. Left for whoever owns `survey.py` next.

**`SURVEY.md` reports version 0.5.14; canonical is 0.5.15.** Regenerating it now
would bake a mid-flight working tree into a committed report. Regenerate once the
`--tempo` work lands.

**`whats-next.md`** — a 46 KB session-1 handoff whose claims ("nothing has been
committed", "the one test currently in place") are all false. Already staged for
deletion (`D hubbard/whats-next.md`) by a concurrent task; no action taken.

---

## Checked and clean

- `CHANGELOG.md` latest entry (`0.5.15`) matches the canonical version, and no
  duplicate version headings exist (`grep -E "^## " | uniq -d` → empty).
- No secrets in the audited documents.
- `README.md`'s corpus-figure policy ("do not restate those figures here") is
  correctly observed — no conversion rates are duplicated outside `SURVEY.md`.
- The `--max-rows` default-of-94 rationale is consistent across `README.md`,
  `CLAUDE.md` and `patterns.py`.
- Every internal doc link target exists.

---

## Learnings

| Observation | Consequence |
|---|---|
| I wrote `GT_ORDER_COMMAND` into a corrected code snippet. **That constant does not exist** — the real code tests `b >= MAX_PATTERNS`, and its branch order differs from what I wrote. Caught only by grepping my own citation before finalising. | The skill's "never invent an interface" rule fires hardest when *fixing* a doc, not when auditing one: writing a replacement snippet is generative, and a plausible-looking constant name is exactly the shape the model reaches for. Verify citations you author, not just ones you audit. |
| Two audited files were rewritten by a concurrent task mid-audit; one target (`whats-next.md`) was deleted between inventory and verification. | Re-read before every edit in a live tree, and re-check inventory assumptions at use time rather than trusting the opening `ls`. Header must disclose the dirty tree. |
| The CLI flag list drifted *twice during a single audit*. | Enumerated inventories in prose are not fixable by correcting them — only by removing the duplication. Fixing the values would have produced a third stale copy within the hour. |
| A subagent's prior conclusion ("no over-read") was available and correct, but I re-derived it from the corpus. | Cost ~1 command; converted an inherited claim into HIGH-confidence evidence. Worth it every time for a claim that will be written into a learning document. |
