# Improvements to the fidelity tool

What `python/fidelity.py` should do next, and why — written at **v0.5.72**,
against the code as it stands at `cc6fce5`.

This is a design note, not a report. `FIDELITY.md` is the report; it is
generated. Nothing here is generated, so if the tool changes and this file
stops being true, fix it or delete it.

Everything below is ranked by how much it would change what the project can
*know*, not by how hard it is. Line numbers are `python/fidelity.py` unless
another file is named.

---

## 0. A live defect, not an improvement: `--filter` reaches nothing — **fixed, v0.5.74**

Kept because the fix is the interesting part, not the defect. `_preset_opts` now derives its keys from `inspect.signature(convert)` and `presets.FIXED` carries `filters`; `tests/test_preset_passthrough.py` fails if any option escapes, with `presets.EXCLUDED_FROM_ALWAYS` naming the deliberate omissions. The paragraphs below are the reasoning that produced that, and they are why a hand-maintained list is not an option here.

v0.5.72 added the filter reader. `convert()` accepts it (`convert.py:117`,
`filters: bool = False`), README documents it (`README.md:537`), and
`goatwriter` writes a real filter table instead of the hard-coded empty one.
But:

- `_preset_opts` (`fidelity.py:568-586`) does not pass `filters`.
- `presets.py`'s `FIXED` block (`presets.py:64`) does not contain it.

So the option is inert everywhere it matters. Every measurement runs with the
filter off, and the next `presets.json` will carry an `always` block without
it — meaning the shipped presets convert without a filter too.

This is the same failure the repo already recorded once: `--slides` was a
no-op for four versions because the portamento data byte was never written to
the speed table (v0.5.50, and `AUDIT.md`'s first verified defect). The shape
repeats because **the passthrough list is hand-maintained**. `convert()` takes
thirteen keyword options; `_preset_opts` builds fourteen keys by hand and
`fidelity.py`'s CLI passes three of them (`--slides`, `--effects`,
`--fold-transpose`, at `:988-996`).

**The fix that stops it recurring** is not "add `filters`". It is to derive the
option set from `convert()`'s own signature — `inspect.signature(convert)` —
so a new conversion option is wired into the harness and the presets by
existing, or is a deliberate, visible exclusion. A test that asserts every
boolean parameter of `convert()` appears in `_preset_opts` costs four lines
and would have caught both this and the `--slides` no-op.

---

## 1. Stop discarding four fifths of what siddump already prints

**Landed in v0.5.76.** `parse_dump` now reads every field siddump prints:
`Voice.adsr_events` and `Voice.pulse_events` per voice, and a file-level
`Trace.filter` (`FilterState`, carrying cutoff, the `$D417` byte, passband and
volume). `wave_timeline` is now `register_timeline(events, nframes)`, taking
the event list rather than a `Voice`, because all six registers are written
sparsely by the same rule. No column of `FIDELITY.md` changed — the data is
available, and §2 is what spends it. The rest of this section is kept as the
argument for why.

**This is the single highest-leverage change in the file, and everything in
§2 is blocked on it.**

siddump prints five register groups per frame: three voice cells
(`Freq Note/Abs WF ADSR Pul`) and one global cell (`FCut RC Typ V`).
`parse_dump` (`:170-200`) reads `cells[2:5]`, and out of each voice cell keeps
the note field and the two waveform characters. It never reads `cells[5]` at
all.

So **ADSR, pulse width, filter cutoff, resonance, filter type and volume are
thrown away at parse time.** The `Voice` dataclass (`:144-157`) has no field
for any of them.

That single omission is why:

- v0.5.71 measured envelope agreement (54.2% → 66.2% across 83 files) with a
  **throwaway script written for the occasion**, and the number is not in the
  report.
- v0.5.72 shipped the filter and *every column of `FIDELITY.md` was
  unchanged*, so the report cannot distinguish that work from a no-op.
- The listening pass reported "the notes sound correct, the sounds are not"
  and the diagnosis had to be done in a scratch script outside the harness.

The change is small: widen `Voice` to carry `adsr_events`, `pulse_events` and
a file-level `filter_events`, parsed exactly as `wf_events` already is
(`:186-188`), and reuse `wave_timeline` (`:202-220`) — it is already a generic
"expand sparse register writes into a per-frame view" function and needs only
its name generalised.

Note the parse contract that makes this safe and is worth preserving in the
comment: siddump prints a register only on the frame it is written, so absence
means *held*, not *zero*. Every one of these dimensions needs the
carry-forward that `wave_timeline` does; comparing the sparse events directly
would score a side that writes the same value twice as different from one that
writes it once.

---

## 2. The three columns that should exist once §1 lands

**Landed in v0.5.78.** `FIDELITY.md` gained `adsr`, `pul`, `filt` and `cut`,
plus a *Filter* section carrying both sides' raw figures. With those four,
every SID register is read by some dimension of §3's registry. What follows is
the design as it was proposed, with what was built noted against each.

Each of these has already been measured once by hand, which is the evidence
they are worth having permanently.

**ADSR agreement.** Per-frame, per-voice, exactly as `wave` works. v0.5.71's
hand measurement is the baseline: 54.2% inherited, 66.2% after the sustain
and hard-restart fixes. Two known instrument-level defects were found the week
this was first measured; the report should not need a fork to see the third.
— *Built as `adsr_compare`, whole 16-bit pair, frames neither side has ever
written left out of the denominator. It lands within about a point and a half
of the hand figure; the residual is the denominator rule and the file set,
neither of which the hand script recorded.*

**Pulse-width agreement.** *In flight — a sibling fork is building this
now, so treat this paragraph as context, not a task.* The gap it is chasing:
Flash_Gordon's original changes pulse width 2823 times in 20 s and ours 5;
Deep_Strike 1820 against 3. `FIDELITY.md`'s own "What this does not say"
already names the `Pul` column as the fix for this, so the doc has been
carrying the TODO longer than the code has.
— *This paragraph was wrong: no fork built it. v0.5.73 shipped the pulse
**conversion** and measured it with a throwaway script, leaving the column to
this work. Built as `pulse_compare`, and deliberately a movement count rather
than an agreement percentage — two players sweeping the same duty cycle from
different phases share almost no frame values, so a per-frame equality score
would read near zero for a conversion that sounds right.*

**Filter agreement.** Global, not per voice: cutoff writes, resonance, and
passband type. Two distinct questions, and both matter, because v0.5.72's
first attempt got the second one wrong:

- *Do we filter where the original filters?* Powerplay Hockey gained five
  filtered instruments and 497 cutoff writes against an original that writes
  the cutoff once. A one-sided count, like the existing `noise` column, is
  what catches invention.
- *Does the cutoff move like the original's?* Deep_Strike 481 → 1515 is an
  overshoot, not an absence, and no count-based column distinguishes those.

Design the filter columns the way `noise` is designed — `ours/original`, with
a marker when we produce something the original never does. That format
already earned its keep: it is what flags `Kings_of_the_Beach_ingame` playing
138 noise frames against an original that plays none.

— *Built as two columns and one section, because the two questions are
different shapes. `filt` counts frames on which a voice is routed into the
filter **and** a passband is selected — both halves, because a routed voice
with no passband is not filtered but inaudible — in the one-sided
`ours/original` form with the `!` marker. `cut` is our summed frame-to-frame
cutoff movement over the original's, which separates a sweep taken in finer
steps (same travel, more writes) from one that runs further than the player's
counter allows. It is a column rather than only a section because §3's
registry made that the difference between `$D415/$D416` being read and being
named as a blind spot. The section carries both sides' raw frames, writes and
travel for the files where either side filters at all. Resonance is not scored
on its own: it shares the `$D417` byte with the routing and siddump never
separates them.*

---

## 3. Make blindness structural instead of remembered — **built, v0.5.77**

The repo's standing rule is: *a metric that cannot see a change is not
evidence the change did nothing — say so in the doc, beside the fix.* That
rule had been applied correctly at least seven times, and it was enforced
entirely by authors remembering it.

It is now enforced by the tool. Each dimension declares the SID registers it
is computed from (`fidelity.DIMENSIONS`), each row records which dimensions it
actually compared (`row["dimensions"]`), and every report ends with a
generated *What this run compared* section naming those registers and, under
them, the registers **no** dimension in that run reads. §4's `--baseline`
mode turns that into a verdict.

One thing this section did not anticipate, and which turned out to be the
whole of it: *no number moved* has two readings — the change is invisible to
everything measured, or the change reached nothing — and this repo has
shipped the second believing the first twice (`--slides`, `--filter`). Naming
the unread registers does not separate them. Hashing the converter's own
output per row does, so each row carries `output_sha` and the verdict says
which of the two it is. Without that half, §3 states a possibility rather
than a result.

---

## 4. A first-class A/B mode — **built, v0.5.77**

Every fork this session that changed conversion behaviour rebuilt the same
apparatus by hand: convert twice, pack twice, trace twice, diff per file,
attribute the delta. At least five did it, at least one did it against a
contaminated shared workdir, and at least one did it against a stale tree and
had to re-run.

`--baseline <json>` is built in: it takes a previous `--json` output, runs the
current tree, and emits a per-file delta table sorted by the largest movement
on any one dimension, plus a per-dimension summary. `--ab-output` writes it to
a file; the report itself still goes to `-o`.

Two properties the hand-rolled versions kept getting wrong:

- **Refuse to compare across different settings.** Built, but *split*, and
  this is where the paragraph it replaces was wrong. A baseline traced at
  other **measurement** settings (`-t`, subtune) is not a baseline and is
  refused with exit 2. A baseline converted with other **conversion options**
  is the opposite case: an option A/B is the commonest thing anyone wants this
  mode for — it is how the corpus figure below was produced — and refusing
  it would leave the apparatus being rebuilt by hand for exactly the change
  the mode exists to measure. So those are named at the head of the output as
  the change under test instead. The hazard the original text was guarding
  against — presets drifting between two runs unnoticed — is answered by
  printing it, which is what refusing would have achieved and nothing else
  did. A field missing from an older baseline is treated as old, not as a
  mismatch.
- **Record the tree, not just the version.** Built: `--label` defaults to
  `git rev-parse --short HEAD` plus `-dirty`, scoped to this project's files
  rather than the whole checkout (the repo carries unrelated siblings), and it
  is recorded in every row.

Measured on the corpus — the v0.5.71–73 options off against on, which is
the envelope, filter and pulse-width work of that release, 95 files at 10 s:
83 files convert to different bytes, **3** move any number at all, and the
mode reports that *80 of the 83 whose output changed moved no number*. That is
the release's honest result, and until now it was a flat table.

---

## 5. The window is fixed, and it is wrong for some files

`-t` is one number for the whole corpus, default 10 s. Consequences already
observed:

- `BMX_Kidz` opens with about 13 s of rest. At 10 s both sides are empty. It
  scored 0% for eighteen versions, and now scores `window empty` — better, but
  still not measured.
- `I_Ball` scores 43% at 10 s and **94% at 30 s**. Two very different
  statements about the same conversion, and the report only ever prints the
  first.

A per-file window in `presets.json`, or an auto-extend when the window is
empty or the attack count is under some floor, would fix both. The floor
matters more than it looks: the report already has to explain away four files
whose originals are near-silent in the window, and "the denominator was too
small" is not a fidelity result.

While here: the report's own caveat says it traces **only subtune 0** — that
is stale since v0.5.64, which traces each file's `startSong`. But the deeper
limitation stands: `Samantha_Fox_Strip_Poker` has 14 subtunes and
`Commodore_64_Music_Examples` has 15, and each is judged on one. A
`--all-subtunes` sweep would cost linear time and would say something the
current report simply cannot.

---

## 6. Rate: the dimension that cannot be measured here at all

33 of 82 measured files are scored below their real fidelity and no rerun
fixes it. siddump calls the play routine `seconds × 50` times regardless of
the PSID speed field (siddump.c:309/325), so `gt2reloc -S2` changes the packed
bytes and not the trace. The report states this at length and correctly.

Two things the tool could still do, neither of which needs siddump to change:

- **Detect the mismatch instead of only describing it.** The harness knows the
  multiplier (`_preset_multiplier`, `:589`). It could compare our attack-rate
  against the original's and flag a file whose ratio sits near `1/multiplier`
  — turning a paragraph of prose into a per-row marker. `Chain_Reaction`'s
  0.66× was found by hand and turned out to be a *different* defect (5.5 calls
  per row, inexpressible); a column would have separated the two classes
  immediately rather than after a fork's investigation.
- **Drive RetroDebugger for the flagged rows.** It honours CIA timing and has
  already confirmed two files at their correct rate. It does not need to run
  over the corpus — only over the 33.

Until one of those exists, the honest reading of the corpus mean is the
excluded-subset figure, and the report is right to print both.

---

## 7. Fold the diagnostics in — **built, v0.5.97**

Two analyses have now been re-derived from scratch by separate forks because
they live in nobody's file:

- **The constant-shift sweep.** A position-aligned modal delta proves a
  transposition when its share is high, but a *low* share proves nothing,
  because the alignment slips whenever either side drops notes — which is
  exactly the regime the low-scoring files are in. The robust form is to sweep
  a constant shift over ±24 semitones and take the difflib ratio at each: a
  transposed file peaks sharply away from zero, a scrambled one is flat. This
  is what reduced "genuinely scrambled" from four files to two, and it exists
  only in scratch trees.
- **Per-voice cause partitioning.** Whole-voice-absent, constant
  transposition, under-production-with-exact-pitches and genuinely-scrambled
  are four different defects that all present as a low melody score. The
  partition has been done by hand twice and is stale both times.

`fidelity.py --diagnose <file>` prints both, and a third thing that turned out
to matter more than either: **the subtune correspondence matrix**, melody % for
every one of the original's subtunes against every one of ours.

That third one is why the section was worth building. The two analyses above
both assume the two sides are the same piece of music, and for three of the
four files this section was written about they were not:

| file | on the diagonal | at its real counterpart |
|---|---:|---|
| Dragons_Lair_Part_II | 7% | **94%** (s0→o9), 98% (s1→o7), 97% (s9→o8) |
| Commodore_64_Music_Examples | 15% | **89%** (s1→o0) |
| Flash_Gordon | 30% | identity holds — but s0 is its *worst* subtune of nine (s7 99%, s8 100%) |
| Rasputin | 25% | no counterpart; voice 2 absent, voice 1 under-produced — a real defect |

Two of them are the `.sid`'s own init wrapper renumbering the subtune before
the player sees it (`Dragons_Lair_Part_II` at `$AF00`, `Rasputin` at `$CFB5`),
which `--search-subtunes` is structurally unable to find: it varies *our* index
and holds the original's fixed, and here it is the original's that moved.

The cost of not having had it is exactly what was predicted here — the same
analysis was spent repeatedly and its conclusions decayed into handoff prose
that turned out to be wrong. "Both peak at 18–25% at a different constant shift
per voice, therefore genuinely scrambled" was a reading of the constant-shift
sweep applied to two subtunes that are not the same music. The sweep was right;
the pairing it was run on was not.

---

## 8. Smaller, still worth doing

- **`wave` ignores the gate bit deliberately and correctly**, but that means a
  note held twice as long with the right waveform scores 100%. Gate-length
  agreement is a separate cheap column from data already parsed.
- **`--pair` skips conversion**, which makes it the right entry point for
  regression-testing the *packer* rather than the converter. It is
  undocumented in README and unused by any script.
- **The three optional SIDM2 stages** (`--register`, `--audio`, `:502-563`)
  are the only frame-exact comparison available and are run by nobody. Either
  wire them into the report for a sampled subset or say plainly that they are
  vestigial.
- **`listen.py` cannot render an RSID original** — `SID2WAV` is version 1.8
  (1997) and predates the format, so 18 of 95 corpus originals cannot be
  A/B'd, including `Skate_or_Die_intro` and all four NTSC files. Adjacent
  tool, but it blocks the only check that covers everything in §2. VICE 3.9's
  `vsid.exe` is on this machine and handles RSID; three attempts at
  `-sounddev wav` produced header-only output, so the invocation is unsolved,
  not the format.

---

## What not to do

Recorded so it is not proposed again. Each was tried and measured.

- **Do not trace our side for `seconds × multiplier`** to compensate for
  siddump's blindness. Measured: helps 2 files, hurts 1. The trace is
  multiplier-blind on *both* sides; scaling one side introduces an error
  rather than removing one.
- **Do not treat a flat report as evidence a change did nothing.** v0.5.46
  fixed a real defect that rewrote 66 rows of one file and moved the report by
  zero percent. This is the rule §3 exists to enforce.
- **Do not add a column that scores a file against a subtune stub.** Subtune 0
  is not always the tune; `startSong` is (v0.5.64). Any new per-file
  comparison must go through `resolve_subtune` (`:603`), not `0`.
- **Do not share a workdir.** The filenames inside are fixed (`a.sng`,
  `b.sid`, `o.sid`), so two concurrent runs silently measure each other's
  files. Fixed in v0.5.66 with a per-run default; do not reintroduce a
  constant path for convenience.

---

## The shape of the argument

The tool measures notes well. It measures **which notes, in what order, at
what pitch, with what waveform class** — and since §1 and §2 landed
(v0.5.76, v0.5.78) it also measures the envelope, the duty cycle and the
filter, which is the whole of what "the sounds are not correct" means. What
it measures there is registers, not sound: a movement count is not a judgement
of a sweep, and an envelope compared frame by frame still says nothing about
when it arrives.

What it will still not measure afterwards is **rate**, and rate is not a
gap in the tool but a property of siddump. That boundary should be stated
where the tool states its other limits, and §6's two mitigations are the most
that can be done inside this file.

The listening pass remains the only check that spans all of it. In this
project's history it has been run once, and it found two defects on its first
outing that nothing in the harness could report — one of them in the listening
harness itself. Any argument that a new column removes the need for it has the
evidence exactly backwards.
