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

Every note in both is a **B** — the pitch content agrees, which is the good
news, and the tune is a B-rooted arpeggio figure. But we re-trigger roughly
seven times too often.

The likely cause is in our own encoding. `patterns.py` fills hold rows with
`GT_NO_NOTE = 0xBD`, and `gcommon.h:50` says:

```c
#define FIRSTNOTE 0x60
#define LASTNOTE  0xbc
#define REST      0xbd      // <- what we write on every held row
#define KEYOFF    0xbe
```

`0xBD` is **REST**, not "no note". If Goattracker gates off on each held row and
re-attacks at the next note, a note held for eight rows becomes eight staccato
notes — which matches the ratio observed.

This is inherited from the VB6 original rather than introduced by the port, and
changing it would alter every file and break the byte-exact `Commando.sng`
fixture, so it is recorded here rather than fixed. **It should be confirmed
against `gplay.c`'s note-column handling before anyone acts on it** — the
evidence here is a note count, not a reading of the player.

That a single 8-second run surfaced a candidate corpus-wide defect is the
argument for wiring this up properly.

## 5. Conclusion

- SIDM2's fidelity tooling is **directly reusable** — no porting, no adaptation.
  The missing piece was a `.sid` to compare against, and `gt2reloc` supplies it.
- Use **both** comparisons: audio (`audio-tightness`, onset-aligned) for how it
  sounds, register (`validate-accuracy`) for how exact it is.
- **Do not lead with the frame-exact number** while the tempo mismatch stands;
  it reports the offset, not the fidelity.
- The blockers to a corpus-wide harness are the two already documented in
  [`SNG2SID-FIDELITY.md`](SNG2SID-FIDELITY.md): the restart position
  `greloc.c:244` rejects, which stops 25 of 75 files packing at all, and the
  tempo reconciliation.
