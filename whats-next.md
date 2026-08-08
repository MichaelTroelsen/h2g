<original_task>
Continuation of work on **H2G**, a converter from Rob Hubbard `.sid` files to
GoatTracker `.sng`. The session opened with `read what next` against the
previous handoff (then at v0.5.128, in `C:\Users\mit\claude\h2g`) and was
driven as a sequence of single-item directives, each answered before the
next was given:

1. `read what next` → summarised the open items and recommended the vibrato
   half-period fix
2. `do the vibrato fix` → §7.ee's derivation had a real error; found and
   fixed it
3. `push it`
4. `what next` → recommended the wavetable-body scaling fix
5. `do the wavetable scaling fix next` → turned out to be a different pair
   of defects than the note described
6. `push it`
7. `do the vicetrace wiring next`
8. `push it`
9. `check progress` (×3, across a long-running corpus `--vice` job)
10. `what next` → the corpus run landed with a result that contradicted its
    own premise; reported that
11. `push it`
12. `please continue` → found and fixed a bug in the *previous* commit's own
    code
13. `push it`
14. `do the drum sweep next` → implemented, verified, then reverted on
    finding a real correctness risk
15. `push it`
16. `play the wavs and report back` → no audio playback exists in this
    environment; explained why, several times, as the user probed *why not*
    and *how could that be fixed*
17. `[/subtask use model fable] create a plan for the three suggestions` →
    a forked agent produced a plan (native audio: not actionable; a real
    listening tool via an external API: possible, gated on cost/privacy
    consent; spectrograms via Read: buildable immediately)
18. `build spectrograms now, decide on the AI listener after` (via
    AskUserQuestion)
19. `stage the drum-effect files instead` → re-staged the listening pass
    for Bump_Set_Spike/Commando/Warhawk/Gerry_the_Germ
20. (spectrograms built and read) → found real issues, one on the project's
    own byte-exact fixture
21. `yes, dig into Commando's rest-section first`
22. `check how many other corpus files hit this pattern first`
23. `do the stratified sample`
24. `write it up in the method doc`
25. `push it`
26. `write the whats-next.md handoff` → this document

Standing rules from `CLAUDE.md` that shaped every commit: bump the version on
every commit; regenerate `SURVEY.md`/`presets.json`/`FIDELITY.md` on a settled
tree, once, only when converter behaviour changed; never ship a fake success;
keep `Commando.sng` byte-exact; stage only project paths by pathspec.
</original_task>

<work_completed>

## Headline

| | start (v0.5.128) | now (v0.5.135) |
|---|---:|---:|
| tests | 666 pass / 2 skip | **665 pass / 3 skip** (the +1 skip is a version-gate on `presets.json`, not a regression — see *Current state*) |
| corpus mean melody (siddump, `-t10`) | 76.7% | **76.7%** (unchanged — see why below) |
| register dimensions | siddump only, once/frame | **`--vice`**, 312 samples/frame, both sides |
| listening pass | never performed | **performed** (via spectrograms, not audio — see below) |

`Commando.sid` → `Commando.sng` **byte-exact** throughout. Seven commits,
`0d24318`→`c0da211` (v0.5.128 was the tip at session start, already
committed; this session's own commits start at v0.5.129).

## v0.5.129 — the vibrato half-period, corrected

`_classic_vibrato_entry`'s `cmp` was `2 × bound × multiplier`, derived from
reading Goattracker's half-period as `cmp / 2` calls. Simulating
`gplay.c:795-801` rather than reading its constants gives `cmp + 2` calls —
the shipped mapping ran the oscillation at roughly **half** the player's
rate, for all 49 files whose vibrato-byte addressing the reader recognises.

Corrected: `cmp = bound × multiplier − VIBRATO_CMP_BIAS`. **`rshift` is
deliberately unchanged** — the old derivation equated the player's
peak-to-peak (`(bound>>1)×depth`; the apply loop only ever subtracts) with a
Goattracker *amplitude*, and that error happened to cancel the doubled
period exactly. Correcting both, as the standing note in the code proposed,
would have doubled every file's depth.

**No dimension in `FIDELITY.md` measures an oscillation rate**, so the
report could not adjudicate this. It moved `slides`/`bend` on 30 files — 15
toward the original, 15 away, mean melody unchanged — and even that
movement is second-order: the old, too-slow oscillation drifted past a
semitone before reversing, so siddump re-read it as a *note change* rather
than a bend, dropping those frames from both counts (One_on_One frame 102).
`--baseline` byte-hashing settled reach (49 files) where the printed report
couldn't.

## v0.5.130 — the wavetable's own clock: two defects, not the one the note named

The handoff's carried-forward note said "the wavetable body is unscaled."
Reading the shapes against `gplay.c` found something narrower and different:

1. **The attack transient was a call too long, in all 37 multispeed
   files.** A wavetable delay entry is current for `value + 1` calls, not
   `value` (`gplay.c:697-704` advances on the call where `wavetime ==
   value`, having incremented it on each call before). `_wave_delay`
   returned `m − 1` since v0.5.82; the attack ran `m + 1` calls — 1.5 frames
   at `-S2`, where 22 of the 37 multispeed files sit. Renamed
   `_wave_hold_byte`; one extra call is now the attack waveform written
   again (`$00` is the editor's empty marker, not a delay of zero).
2. **The arpeggio alternated once per call, not once per frame.** The
   five-entry-per-instrument layout was recorded as having no room for a
   delay beside each half. A jump costs no call and can target entry 0, so
   the attack entry now doubles as the note half's first call — `2m` calls a
   cycle at every multiplier. Safe only where `tail == wave`, checked (holds
   in all 45 corpus records reaching the branch).

Also found: a delay entry's right side **is** read, on its final call, so a
hold placed after a relative note must carry `$80` or it drags the note
back.

**Neither instrument can see the attack fix, for opposite reasons** — the
first time this session's own new tooling became the subject rather than
the tool: siddump samples once per frame and the removed call is a frame's
*interior* call (`wave` moved on 0 of 82 files); `--equal-calls` resamples
per call but drops the frame-aligned dimensions entirely, comparing `wave`
on 45 files of which none has multiplier > 1. This is the argument that
motivated v0.5.131.

## v0.5.131 — `--vice`: the register dimensions at 312 samples a frame

`vicetrace.py` (built the *previous* session) had never been wired into
`fidelity.py`. It is now, via `--vice` / `--vice-reduce` / `--vice-exe`.

**The reduction had to be measured, and the result was a surprise.** The two
sides write at different rasterlines within the frame (Warhawk's player near
line 8-19; our `-S2` conversion at 119-126 and 274-284), so a
rasterline-against-rasterline comparison is impossible — it would report the
offset, not the music. Shifting one side by an inaudible 0-48 rasterlines
and re-scoring four candidate rules:

| rule | mean sd | worst range | |
|---|---:|---:|---|
| `last` (what siddump reports) | 0.18 | **2.64 pp** | samples one instant — the *least* stable |
| `any` | 0.09 | 1.67 pp | disqualified: saturates (98.8% on Deep_Strike vs ~75% everywhere else) |
| `majority` | 0.02 | 0.09 pp | stable, hard vote |
| **`overlap`** | **0.02** | **0.13 pp** | stable and graded — **default** |

The rule the report has always used turned out to be the *least* phase-stable
of the four — the opposite of the expectation going in.

## v0.5.132 → v0.5.133 — a corpus run, and a bug found in the tool that ran it

The corpus `--vice` pass reported ~10.1pp mean absolute resolution effect,
concentrated (unexpectedly, since `--vice` was motivated by multispeed
undersampling) at **`-S1`** files. Investigating that anomaly — rather than
confirming a real harness-vs-converter gap — found a defect in `--vice`
itself, shipped one commit earlier: `wave_compare`'s "drop a frame silent on
both sides" rule was translated as "drop only if the whole 312-line
histogram is silent," so a frame where one side flickered briefly and both
were silent *at the boundary* scored as a **full agreement** instead of
being dropped. Fixed as the graded form of the same rule
(`_graded_agreement`, `min(share_a(0), share_b(0))` leaves both numerator
and denominator). Corrected corpus figures: resolution **6.9pp** (not
10.1), denominator defect **3.2pp** (pure inflation), rule **2.1pp**.
Two of the six files in the original six-file sample owed their entire
"resolution" reading to this bug; the true effect on them was zero.

`--vice-reduce last` (the non-graded path, which reproduces siddump's own
arithmetic exactly) is what made this separable at all — run the new
instrument under the old instrument's rule before trusting a difference is
real.

## v0.5.134 — the drum sweep: investigated, implemented, reverted

§7.ii's under-render (one static step where the player takes `W − 1`) had
an obvious next move: loop `WAVECMD_PORTADOWN` back onto itself, the same
jump-target trick that gave the arpeggio its missing slot in v0.5.130.
Implemented, differential-hashed to exactly the 44 files that reach
`_drum_entries`, and directly verified on Bump_Set_Spike — VICE traces
showed genuine, repeated, self-terminating falls matching the player's
rate.

**Reverted before commit.** `CMD_PORTADOWN` has no floor
(`gplay.c:557-572` is `cptr->freq -= speed` on an unsigned 16-bit value,
nothing clamps it), where the player's own guard freezes at zero. A
corpus-wide underflow scan with `--vice` (921 hits on 20 of 44 files, after
one methodology bug — see *Tooling failures* — was caught and fixed) found
it on **Commando**, the project's byte-exact fixture: an ordinary,
mid-range, three-second-held note wrapped through zero after 175
consecutive falling frames. Goattracker's own frequency table bottoms out
at 279; the drum step is 256 — **one step is the largest number of
repetitions provably safe for any note**, which is exactly what already
ships. Documented as a negative result, §7.oo, so the idea (which looks
structurally identical to the arpeggio fix that *did* ship) is not
re-attempted blind: the arpeggio's relative-note entry resets `cptr->freq`
from the table every visit and never drifts; `CMD_PORTADOWN` never resets
anything.

## v0.5.135 — the listening pass, performed without ears, and a real defect found

**I have no audio playback in this environment** — established firmly this
session after several rounds of the user probing why, and whether it could
be fixed (VB-Cable, a live Claude-voice bridge — neither gets audio *into*
this session; see *Attempted approaches*). What was actually buildable:
real spectrograms (`numpy` STFT + `PIL`, no new project dependency — a
one-off scratch script, not committed) read via the `Read` tool, which does
give genuine visual perception.

Staged the four files whose drum block is byte-identical per §7.ii
(Bump_Set_Spike, Commando, Warhawk, Gerry_the_Germ) and looked at them:

- **Bump_Set_Spike / Gerry_the_Germ**: visually confirmed dynamic-range
  compression already suspected from a numeric envelope check (σ 26.7→8.5dB
  and 19.0→8.3dB) — the low band fills in continuously where the original
  shows sharp, separated strikes.
- **Gerry_the_Germ**: the original's opening ~4s shows four clear diagonal
  rising-pitch sweeps; h2g's opening shows none. Consistent with (not
  proven — not checked further) the documented drum+rise conflict, where a
  record setting both bits sacrifices the rise entirely.
- **Warhawk**: a multi-second total-silence block, roughly where the
  original has a sustained section after its vibrato-heavy opening.
- **Commando**: investigated in full — see next section. The most
  significant finding of the four, on the project's own reference fixture.

## Commando's rest section — investigated, confirmed, and correctly scoped down

Full writeup: **H2G-CONVERSION-METHOD.md §7.pp.**

**Confirmed at three independent levels**: register-level (all three voices
pause in near-lockstep at 7.8-7.9s, recurring every ~5.2s; a 250/250 exact
match one cycle apart), structural (subtune 0's orderlist is 64/63/123
entries, ending on Hubbard's own `$FF` "tune ended" byte, which
`--legal-restart` correctly loops per its documented behaviour), and ruled
out the project's most common false-alarm class (`--diagnose` shows an
89-100% clean diagonal — not a scrambled subtune).

**A wrong turn is in the record on purpose**: an early riff match (h2g's
first ~8s matches the original's own restated riff) was first read as "not
a bug." Extending the same comparison to 15-22s reversed that — the
original introduces notes never in the early riff, while h2g just keeps
looping it. The lesson stated in the doc: a note-sequence match over one
window is evidence about that window, not what follows it.

**What is *not* confirmed**: the exact 6502 mechanism the real player uses
when it hits `$FF`. `track_selector: True` is detected for Commando but
shown (by reading `detect.py:634-660`) to be a subtune→track-table lookup
indirection, not a chaining primitive — it explains how the *right* table
is found, not what happens when it runs out. This needs disassembly-level
reading, not undertaken.

**The corpus-wide screen — and why its headline number doesn't survive
verification**: a structural check (does any subtune-0 voice end in a
restart under ~150 entries) flagged **55 of 95 files (58%)**. Five,
stratified across the range, were checked by hand the same way Commando
was. **Zero repeated Commando's failure.** Two were caught by the
screening heuristic's *own* blind spots — BMX_Kidz's documented ~13s intro
silence and Human_Race's natural four-chord cycle length both produce the
same "new pitches after a fixed split" signature as a genuine truncation,
for reasons unrelated to any defect. `track_selector` was checked as a
candidate explanation for the pattern and refuted (49% of candidates have
it vs a 39% corpus base rate — too weak to be the mechanism).

**Net scope**: this reads as Commando-specific, not a corpus-wide defect
worth a fix campaign — though five of fifty-five is not enough to clear the
rest, only to lower the prior substantially.

</work_completed>

<work_remaining>

## 1. Commando's rest section — the mechanism, not just the symptom

What's confirmed (§7.pp) is *that* the conversion diverges and *why the
converter's own reading is correct* (the source orderlist really is short
and really does end on `$FF`). What's still open is what the **real
player** does instead of looping when it hits that marker — chain to
another orderlist via some mechanism `track_selector` doesn't cover, jump
via a different table, or something else entirely. Needs 6502 disassembly
around the point the version-0/1/3 track reader consumes `$FF`
(`tracks.py:222-228` names the byte; the *player's* handling of it, not
h2g's, is what's missing). Warhawk's own spectrogram silence gap is a
plausible second instance worth checking once the mechanism is understood.

## 2. The drum sweep under-render is still open, and the obvious fix is now known-unsafe

§7.ii's `W − 1` vs `1` gap stands. The looping fix is closed off (§7.oo) —
not because it's hard, but because `CMD_PORTADOWN` has no floor and one
step is provably the safe ceiling. A real fix needs either per-note
information threaded into the wavetable build (which `_wavetable_entries`
structurally doesn't have — one wavetable is shared across every pitch and
duration the instrument is used at) or a pattern-level `CMD_TONEPORTA`
encoding (which does clamp, but is reachable only from a pattern's own
effect column, not the wavetable's one-shot command dispatch — a
materially bigger change touching `patterns.py`, not just
`goatwriter.py`).

## 3. Gerry_the_Germ's apparent missing rise effect — flagged, not verified

The spectrogram showed no rising-sweep shape in h2g's opening where the
original has four clear ones. Plausible mechanism named (drum+rise
conflict) but not checked against this file's actual detected bits, and not
fixed either way.

## 4. Bump_Set_Spike / Gerry_the_Germ's compressed dynamics — flagged, not diagnosed

Visually and numerically confirmed (σ dB collapse), root cause not
investigated. Candidates: an ADSR release/sustain difference, a gate-hold
difference, or a legato/note-length effect the register dimensions are
documented as unable to see (`wave` ignores the gate bit; `NOT_MEASURED`
names note length explicitly).

## 5. The listening pass tooling built this session is scratch, not shipped

The spectrogram script (`numpy` STFT + hand-rolled colormap + `PIL`) lives
in the session's temp scratchpad directory, which does **not** persist
across sessions. If spectrograms are wanted as an ongoing check, they need
to be written into the actual repo (a `python/spectrogram.py` alongside
`listen.py`, or folded into `listen.py` itself) — nothing here survives to
next session on its own.

## 6. A real listening tool was planned, not built

A forked "fable" agent produced a plan for an actual audio-capable second
opinion: `OPENAI_API_KEY` is already set in this environment, and a
standalone script sending the staged WAV pairs to an audio-capable OpenAI
model would give a genuine second ear, not a proxy. **Gated on explicit
user consent** — it installs a new dependency, sends audio files to a
third party, and costs money per call — none of which happened this
session (the user chose spectrograms first). Live option if wanted.

## 7. The ~50 unverified restart-screen candidates

Zero of five verified as real defects. Not proof the rest are clean — just
grounds to expect a low yield. Full list is in the session's log output,
not currently saved anywhere in the repo (see *Where things are* if
re-deriving it).

## 8. Carried forward, untouched this session

- **`_rate_shift` is exact only for powers of two.** Now matters more:
  §8 (prior session) means 15 files pack at multiplier 3/4/5/6, not just
  1/2.
- **Widen `OUTER_GATE`** to the zero-page, `STY/RTS` and `BMI` dialects.
  Known test cases: Warhawk period 8, Spellbound 11, Las_Vegas 5.
- **Encode the two per-instrument wave programs** (ACE II `$E357`, Auf
  Wiedersehen Monty `$E743`) — read by `detect`, encoded by nothing.
- **Spellbound's `--pace` residual** — reads 1.333 where 1.82 follows,
  passing every confidence gate. Still the only known case of a
  fully-gated figure being wrong.

</work_remaining>

<attempted_approaches>

## Refuted this session — do not resurrect

1. **Looping the drum sweep via jump-to-self (v0.5.134).** Structurally
   sound, reach- and trajectory-verified, and still wrong: `CMD_PORTADOWN`
   has no floor, and Commando's own ordinary content underflowed it. See
   §7.oo for the full case, including the exact number (279 vs 256) that
   makes one step the provable ceiling.
2. **"Commando's riff match means there's no bug."** Reversed by extending
   the same comparison window from ~8s to ~22s. A partial-window match is
   evidence about that window only.
3. **A naive signal-processing periodicity detector** for the corpus-wide
   loop scan (autocorrelation over a fixed formula-derived window). Kept
   returning noise-floor values (50-70 frames) instead of Commando's
   confirmed 260-frame period; validating it against the one *known* case
   before trusting it on 95 files is what caught this. Pivoted to reading
   the converted track data structurally instead — deterministic, fast,
   and directly grounded in the confirmed mechanism.
4. **The "new pitches after a fixed split" acoustic heuristic**, and by
   extension the raw 55/95 corpus screen number. Both produce false
   positives from ordinary properties of the music (an intro silence, a
   chord-cycle length exceeding the split point) that have nothing to do
   with a truncated track. Treat the 55 as *candidates needing the
   Commando-style by-hand check*, never as a defect count.
5. **`track_selector` as the mechanism** behind either Commando's specific
   failure or the corpus-wide restart pattern. Checked directly by reading
   `detect.py` (it's a lookup indirection, not a chaining primitive) and
   by correlation (49% of screen candidates have it vs 39% corpus-wide —
   too weak).
6. **VB-Audio Cable, or any OS-level audio routing, as a fix for "give
   Claude ears."** It moves audio between applications that already have
   audio I/O; it does not create a channel into this session's perception.
   The bottleneck was never *getting* audio data (the WAV files already
   have sample-accurate PCM) — it's that no tool here decodes audio into
   something readable. A separate Claude endpoint with live voice/audio
   input might genuinely hear a file routed to it, but that's a different
   conversation entirely; nothing relays back into this one automatically.

## Tooling failures to avoid repeating

- **Rasterline-level vs frame-level confusion, again** — the first
  wraparound-detection script for the drum-sweep investigation compared
  raw consecutive VICE *rasterlines* instead of reducing to one value per
  frame first, producing 10486 spurious "wraparound" hits (a normal
  once-per-frame register write, straddling a sample boundary, looks like
  a huge one-sample jump at 312-samples-a-frame resolution). Fixed by
  reducing through `vicetrace.frame_cells` first, the same discipline
  §7.nn had already established.
- **A killed background command can leave a `git stash` unpaired.** A
  `git stash -q && <long job> ; git stash pop -q` command was stopped via
  `TaskStop` before reaching the `pop` — the stash sat live while
  `git status` showed a clean tree. No tool surfaced this; only checking
  `git status`/`git stash list` before trusting "clean" caught it. **Never
  chain a stash-pop after a command you might kill mid-run**; stash,
  run the job as a separate step, pop as a separate step.
- **`../build/listen` resolves relative to `python/`, landing at
  repo-root `build/listen/`, not `python/build/listen/`.** Checked the
  wrong absolute path twice this session and raised a false "the whole
  build/ directory vanished" alarm before finding the actual off-by-one
  path bug (an extra `python\` segment in a scratch script).
- **Python fully buffers stdout when piped to a file** (not
  line-buffered, as it would be to a terminal). Background job progress
  looked stalled twice this session for this reason alone; fixed with
  `python -u` and explicit `flush=True` on every progress print.
- **`listen.py --files` is `nargs='+'`, greedy.** Passing the positional
  `sid_dir` *after* `--files <name> <name>...` makes argparse swallow the
  directory path as another filename. `sid_dir` must come first.
- **A workdir/output-path reused sequentially across a loop of many files
  risks stale-file contamination even without concurrency** — a lesson
  this repo already had (CLAUDE.md's own history), re-triggered when a
  manual one-off check collided with a still-running background scan
  sharing the same `C:\t\...` path. Rewriting the scan to give every file
  its own subdirectory (`root / stem`) was the fix, at the cost of not
  being able to trivially re-inspect one file's trace without re-running
  it — traded off deliberately since correctness mattered more here.

</attempted_approaches>

<critical_context>

## Where things are

| | |
|---|---|
| **Repo (work here)** | `C:\Users\mit\claude\h2g` → github.com/MichaelTroelsen/h2g |
| Corpus (95 files) | `C:\Users\mit\claude\c64server\SIDM2\SID\Hubbard_Rob`, or `H2G_CORPUS` |
| `gt2reloc.exe` | `C:\Users\mit\Downloads\GoatTracker_2.77\win32\`, or `H2G_GT2RELOC` |
| GoatTracker source | `C:\Users\mit\Downloads\GoatTracker_2.77\src\` (`gplay.c`, `greloc.c`) |
| VICE 3.9 (`vsid`) | `C:\Users\mit\Downloads\GTK3VICE-3.9-win64\GTK3VICE-3.9-win64\bin\`, or **`H2G_VSID`** (wired this session) |
| `siddump-rt` | `python/tools/siddump-rt/` — must be built, `make` with w64devkit gcc |
| Short scratch | `C:\t\` (gt2reloc's 60-byte filename buffer) |
| gcc | `C:\Users\mit\Downloads\w64devkit\bin\` |
| Session scratchpad (does **not** persist) | `C:\Users\mit\AppData\Local\Temp\claude\...\scratchpad` — this session's spectrogram/scan scripts live only here |

## Invariants

- **`Commando.sng` byte-exact.** `--max-rows` 94 and `--format` gts2 stay
  the defaults.
- **Bump the version every commit**; regenerate all three artefacts on a
  **settled** tree, once, in the order survey → presets → fidelity —
  **only when converter behaviour actually changed**. v0.5.134 and
  v0.5.135 are doc/investigation-only and correctly did not regenerate;
  don't regenerate reflexively.
- A new `convert()` option is inert until it is in **four** places: the
  signature, `presets.FIXED`, the hand-written `always` dict, and (if it
  moves the rate) `pack_multiplier`.
- **Validate any new automated check against a case you already understand
  before trusting it on the rest of the corpus** — this session's own
  central, twice-repeated lesson (the periodicity detector, the acoustic
  heuristic, and last session's `--vice` denominator).

## Instrument limits — extended this session

- **`--vice` exists now, but is still not the default** (two emulator runs
  a row, ~1.3x real time each). It sees within-frame register changes
  neither siddump nor `--equal-calls` can. Use it for any change that
  moves a register *within* a frame, not just across one.
- **`--vice`'s own reduction rule matters and was measured, not assumed**:
  `overlap` (duration-weighted share agreement) is both the most stable
  *and* the most graded of four candidates. `last` — what siddump
  effectively does — is the least phase-stable, which was the opposite of
  the going-in expectation.
- **Shared silence must leave both numerator and denominator, gradedly,
  not as an all-or-nothing frame-level skip** — v0.5.131's own bug, fixed
  in v0.5.133. `_graded_agreement` is the reference implementation.
- **Orderlist entry count is not a real-time duration**, and treating it
  as one overcounts badly (55/95 → 0/5 confirmed). Pattern length varies
  enormously across the corpus; the same entry count can span 5 seconds
  or well over 30 depending on the file.
- **A fixed time-split acoustic heuristic ("new content after t seconds")
  is blind to a piece's own natural structure** (an intro silence, a
  chord-cycle length) and will flag both as if they were a truncation
  defect. There is no known way to fix this cheaply; it needs the full
  by-hand attack-sequence comparison every time.
- **This environment has no audio perception, and no known way to add one
  from inside a session.** `Read` gives genuine visual perception
  (spectrograms are a real, if partial, substitute); nothing gives
  auditory perception. An external audio-capable API is the only
  identified path to a *real* second opinion, and it needs explicit
  consent (third-party data, cost) every time.

## Verified facts (new this session)

- `gplay.c:697-704`: a wavetable delay entry is current for `value + 1`
  calls, not `value`.
- `gplay.c:9-21`: Goattracker's own frequency table's lowest legal note is
  `0x0117` = 279.
- `gplay.c:557-572`: `CMD_PORTADOWN`/`CMD_PORTAUP` (the wavetable's
  one-shot command form) have no floor or ceiling — `cptr->freq -= speed`
  on a bare unsigned 16-bit value.
- `gplay.c:795-801`, simulated: vibrato half-period is `cmp + 2` calls.
- `tracks.py:222-228`: version 0/1/3's track reader treats both `$FE` →
  `[0xFF, 0xFD]` and `$FF` → `[0xFF, 0x00]` as "restart this track" —
  different codes, same practical effect once `--legal-restart` runs.
- `detect.py:634-660`: `track_selector` rewrites `track_lo`/`track_hi` to
  a lookup table's address; it is *not* a chaining mechanism between
  subtunes.
- Commando subtune 0 (the header's own default, confirmed via
  `--diagnose` at 89-100% clean correspondence): voice 0/1/2 orderlists
  are 64/63/123 entries.

## Commands

```sh
cd python
python -m pytest tests/ -q                                    # 665 pass, 3 skip
python fidelity.py <corpus> -t 10 --presets ../presets.json -o ../FIDELITY.md
python fidelity.py <file> --vice --vice-reduce overlap|majority|last|any
python fidelity.py <corpus> --baseline old.json --ab-output ab.md --json new.json
python listen.py <sid_dir> --files A.sid B.sid -o ../build/listen   # sid_dir FIRST
python survey.py <corpus> -o ../SURVEY.md --legal-restart --gt2reloc
python presets.py <corpus> -o ../presets.json
cd tools/siddump-rt && make                                   # needs w64devkit gcc
```

</work_completed>

<current_state>

## Everything is committed and pushed; tree clean

- **`h2g` `master` = `c0da211`, v0.5.135**, public, pushed. Working tree
  clean.
- **665 tests pass, 3 skipped.** `Commando.sng` byte-exact. The third skip
  (`test_preset_passthrough`) is a version-gate, not a regression:
  `presets.json` is still correct for the running converter's actual
  behaviour (v0.5.134/v0.5.135 changed no converter byte), it just
  predates the version string. Will clear itself the next time artefacts
  are regenerated for a real reason.
- `SURVEY.md`/`presets.json`/`FIDELITY.md` are current as of **v0.5.133**
  (the last commit that changed converter behaviour) — not v0.5.135.
- No scratch/investigation files leaked into the repo tree; everything
  from the drum-sweep and Commando investigations stayed in the session
  scratchpad and is gone now (see *work_remaining* §5 if any of it is
  wanted as a permanent tool).

## Two things a fresh session must know first

1. **This environment cannot play or hear audio, at all, and there is no
   known way to add that from inside a session.** If a "do the listening
   pass" request comes in again, the honest options are: (a) build fresh
   spectrograms (the scratchpad ones are gone), (b) the OpenAI-pilot plan
   from this session (needs explicit consent — third-party data, cost),
   or (c) hand it to the user directly. Don't rediscover this the slow
   way; it was established firmly and at some length this session.
2. **A corpus-wide screening result is not a defect count until verified
   against ground truth on a sample.** This session's 55/95 → 0/5 is the
   concrete cautionary example; cite it rather than re-deriving the
   lesson from scratch if a similar situation comes up.

## Open questions carried forward

- What does Commando's real player do at the `$FF` boundary, if not loop?
  (work_remaining §1 — needs 6502 disassembly)
- Is Warhawk's silence gap the same mechanism as Commando's? (untested)
- Does Gerry_the_Germ's missing rise effect trace to the documented
  drum+rise conflict, or something else? (untested)
- What's actually behind Bump_Set_Spike/Gerry_the_Germ's dynamic-range
  compression? (undiagnosed)
- Is the drum sweep's `W − 1` gap closable at all within Goattracker's
  primitives, given the floor problem rules out the obvious fix?
  (work_remaining §2 — two harder alternatives named, neither attempted)

</current_state>
