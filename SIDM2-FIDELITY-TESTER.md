# Can SIDM2's fidelity tester be used here?

**Question:** SIDM2 has accuracy tooling for its own SID→SF2→SID pipeline. Can
H2G reuse it to compare an original `.sid` against our conversion?

**Answer: yes, unmodified, today.** SIDM2's validators take **two `.sid` files**,
and since [`SNG2SID-FIDELITY.md`](SNG2SID-FIDELITY.md) we can produce the second
one — `gt2reloc` packs our `.sng` back to `.sid`. I ran it end to end; results
below.

The short recommendation: **use both comparisons, for different questions, and
in this order** — note-sequence first, audio-onset second, frame-exact last.
Reasons in §3.

---

## 1. What SIDM2 provides

| Tool | Invocation | What it does |
|---|---|---|
| `validate-accuracy.bat` | `original.sid converted.sid` | Frame-by-frame SID register comparison via `siddump`, accuracy %, HTML report |
| `trace-compare.bat` | `a.sid b.sid [--frames N]` | Frame-by-frame trace diff, interactive HTML |
| `audio-tightness.bat` | `a.sid b.sid` or `a.wav b.wav` | Renders to WAV, detects onsets by spectral flux, **aligns them**, reports timing and attack-shape divergence |

The first two are `sid2sid`; the third is `wav2wav` (and accepts `.sid` directly,
rendering for you). All three are already built and working in that repo.

## 2. It runs against our output as-is

```
cd SIDM2
python scripts/validate_sid_accuracy.py \
    "SID/Hubbard_Rob/Off_the_Cuff.sid" h2g_offthecuff.sid --duration 10
```

against `Off_the_Cuff.sid` converted with
`--max-rows 128 --pack-repeats --format gts5 --tempo auto` and packed by
`gt2reloc`:

```
Overall Accuracy:      22.91%
Per-Frame Accuracy:     1.68%
Exact Frame Matches:    0/500  (0.00%)
Filter Accuracy:       99.70%
Voice 3 Waveform:     100.00%
```

No integration work was needed. Two practical notes: it resolves
`tools/siddump.exe` **relative to the SIDM2 root**, so run it with that as the
working directory; and it writes its HTML report into the current directory.

## 3. sid2sid or wav2wav?

**Both, but they answer different questions, and frame-exact is the wrong one to
start with.**

A frame-aligned register comparison assumes both files are at the same tempo.
Ours is not, and knowingly so: this converter emits one row per player tick,
while the fastest steady row Goattracker can express is three play-routine calls
(`gplay.c:325` — tempo 0 and 1 are funktempo, not a rate). Until that is
reconciled, *every* frame differs and the headline number measures the tempo
offset rather than the music. `0/500 exact frame matches` above is exactly that
artefact, not 500 wrong frames.

`audio-tightness` is the one built for this: it **aligns onsets before
comparing**, so a constant offset does not swamp the result. That makes it the
right tool for "does this sound like the original", and it is the only one of
the three that tolerates our current timing state.

Cheapest and most diagnostic of all, though, is neither: compare the **note
sequences** with timing discarded. That isolates "are the right notes played in
the right order" from "are they played at the right moment", and it needs no new
tooling:

```sh
siddump orig.sid -a0 -t8 | grep -oE "[A-G]#?-[0-9]" > a.notes
siddump ours.sid -a0 -t8 | grep -oE "[A-G]#?-[0-9]" > b.notes
```

Suggested order:

1. **Note sequence** — catches wrong notes, wrong order, dropped events. Immune
   to the tempo problem.
2. **`audio-tightness`** — catches timing tightness and envelope shape, with
   onset alignment doing the heavy lifting.
3. **`validate-accuracy` / `trace-compare`** — the strictest measure, and worth
   having as the end goal, but only meaningful once tempo is right.

## 4. What the first run already found

Running step 1 on `Off_the_Cuff` over 8 seconds:

```
original: 68 note events
ours:    498 note events
```

> **Corrected below.** Those counts are real and still reproduce, but they do
> not mean what this section first concluded. The `grep` counts every note
> siddump prints, and siddump prints a note in three different situations. Once
> they are told apart — which is what `python/fidelity.py` now does — the
> **7× re-trigger disappears**: `Off_the_Cuff` strikes *fewer* notes than the
> original, not more. See §4b.

Every note in both is a **B** — the pitch content agrees, which is the good
news, and the tune is a B-rooted arpeggio figure.

## 4b. What the counts actually were

`siddump.c:409` prints a bare note (`B-4 9B`) only when `prevchn[c].note == -1`,
which `:376-380` sets on a **keyoff→keyon transition**. A note in parentheses
(`(B-6 A3)`) is the same voice moving to another pitch *without* re-triggering,
and `(+ 0034)` is a frequency delta inside one note. Only the bare form is a
struck note. Separating them, over the same 8 seconds:

| | attacks | note changes without retrigger | slides |
|---|---:|---:|---:|
| original | 82 | 0 | 349 |
| ours | 64 | 530 | 0 |

So we do not re-strike held notes here — we play **0.78** attacks per original
attack, and the melodic sequence agrees to 89%. What the raw count was picking
up is a different defect: the original bends the pitch *within* a note
(vibrato — siddump prints deltas, the note number never changes), where ours
jumps far enough to land on other note numbers entirely, including an octave
the original never plays. That is worth its own investigation, and it is not
the one this section originally named.

The `0xBD`/REST hypothesis is therefore **unsupported by this evidence**. It may
still be a real defect — `patterns.py` does fill hold rows with `0xBD`, and
`gcommon.h:50` does define that as `REST` — but the note count was never
evidence for it, and across the corpus the median retrigger ratio is **0.98**
(`FIDELITY.md`), which is not the signature of a corpus-wide gate-off defect.
Confirming or refuting it needs `gplay.c`'s note-column handling read directly.

That a single 8-second run produced a confident wrong conclusion, and that
separating the event types overturned it, is the argument for wiring this up
properly rather than grepping.

## 5. Conclusion

- SIDM2's fidelity tooling is **directly reusable** — no porting, no adaptation.
  The missing piece was a `.sid` to compare against, and `gt2reloc` supplies it.
- Step 1 is now implemented as `python/fidelity.py`, which runs the whole
  pipeline (convert → legalise restart → pack → trace both → compare) over a
  file or a corpus and writes [`FIDELITY.md`](FIDELITY.md). Steps 2 and 3 are
  wired to it behind `--audio` and `--register`.
- Use **both** comparisons: audio (`audio-tightness`, onset-aligned) for how it
  sounds, register (`validate-accuracy`) for how exact it is.
- **Do not lead with the frame-exact number** while the tempo mismatch stands;
  it reports the offset, not the fidelity.
- The blockers to a corpus-wide harness are the two already documented in
  [`SNG2SID-FIDELITY.md`](SNG2SID-FIDELITY.md): the restart position
  `greloc.c:244` rejects, which stops 25 of 75 files packing at all, and the
  tempo reconciliation.
