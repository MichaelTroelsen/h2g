#!/usr/bin/env python3
"""Find the best conversion options for every .sid in a directory.

The converter's output-shaping options are all opt-in, and the right setting is
not the same for every tune: `--max-rows 128` fits some files that 94 cannot,
`--pack-repeats` rescues others from the orderlist limit, and `--prune-patterns`
and `--dedup-patterns` only ever shrink. Rather than pick one compromise for the
whole corpus, this searches the combinations per song and records the winner.

Usage:
    python presets.py <sid_dir> [-o presets.json]

The result feeds back into the converter:
    python -m h2g song.sid --presets presets.json

What "best" means, in priority order:

 1. **Most subtunes that actually play.** An orderlist over Goattracker's
    254-byte limit costs its subtune (see reindex_tracks), and how many are
    lost depends on the options -- so this dominates. A setting that keeps the
    music beats one that saves bytes.
 2. **Most rows actually played.** Rows reached by walking the orderlists, not
    rows stored -- counting storage would punish --prune-patterns for removing
    patterns nothing can reach, and --dedup-patterns for making identical ones
    share.
 3. **Smallest file.** Since (2) is playback, this is a straight tie-break
    between settings carrying identical music, which is what prune and dedup
    are.

Those three criteria are all **structural**, and some options change no
structure at all -- same subtunes, same rows, same byte count -- so `_score`
cannot see them and putting them in TOGGLES would tie every time and silently
pick the default. `--fidelity` searches those by *playing* both settings and
comparing against the original, which needs siddump and gt2reloc. It is off by
default because the structural search is what every commit re-runs; a plain run
carries any setting already recorded forward rather than dropping it (see
FIDELITY_TOGGLES and `--no-carry`).

Format, tempo, the restart position, slides and effects are not searched:
gts5, `--tempo auto`, `--legal-restart`, `--slides` and `--effects` are simply
correct for anything you intend to open in Goattracker or pack back to a .sid
(the legacy GTS2 importer overruns its pattern array on the portamento
commands this converter emits; an untempo'd file plays at the wrong speed;
greloc.c:244 refuses to export a song whose restart position is out of range,
which is what Hubbard's "tune ended" marker becomes; and `--slides` /
`--effects` fix mis-reads that are gated on detection finding the relevant
routine in the player, a no-op elsewhere). None of them affects whether a
tune converts.
"""
from __future__ import annotations

import argparse
import itertools
import json
import sys
from pathlib import Path

from h2g import __version__
from h2g.convert import _detect_tables, convert
from h2g.goatwriter import (FORMAT_GTS5, find_song_speeds,
                            recommended_multiplier)
from h2g.patterns import DEFAULT_TRACK
from h2g.sidfile import load_sid

# Searched per song. Order is irrelevant -- every combination is tried.
MAX_ROWS = (94, 128)
TOGGLES = ("pack", "prune", "dedup")

# Not searched; see the module docstring.
FIXED = {"fmt": FORMAT_GTS5, "tempo": "auto", "legal_restart": True,
         "skip_gate": True,
         "slides": True, "effects": True, "status_bit6": True,
         "reject_phantoms": True, "fold_transpose": True,
         "sustain_exact": True, "no_hard_restart": True,
         "filters": True, "pulse": True, "vibrato": True,
         "rest_instrument": True, "compact_instruments": True}

# convert() options deliberately NOT in the `always` block, and why. Every
# other option must appear there: one left out silently measures as doing
# nothing, which is how --slides and --filter each shipped dead.
# test_preset_passthrough.py checks this set covers the difference.
EXCLUDED_FROM_ALWAYS = {
    # Changes the bytes of every file and the byte-exact Commando fixture
    # encodes the original tool's unterminated patterns.
    "terminate_patterns",
    # Correct only for a rip of a single tune: the per-voice instrument
    # array is mutable player state, and a snapshot of a multi-subtune file
    # caught it mid-tune (Commodore 64 Music Examples, wave 29% -> 0%).
    "initial_instrument",
    # Measured and rejected as a default. Removing the testbit frame from every
    # note's first frame deletes a register write the originals do not make
    # (9179 frames of ours against their 4273, in 79 files against 12) and
    # `wave` rises 69.8% -> 73.9% for it -- but the frame is what makes a
    # re-struck note retrigger, and melody falls 79.6% -> 63.9% across the
    # corpus, Zoids by 89 points and Thrust by 87. Three files gain 16-17
    # (Last_V8 both rips, Trans-Atlantic_Balloon_Challenge), which is why the
    # option exists rather than the finding being a comment.
    "no_test_restart",
    # Also measured and rejected as a default, twice: the first attempt (before
    # v0.5.66's variable-length wavetable) cost 82 points of wave agreement
    # across 18 files, and re-measuring under v0.5.175's aligned harness -- the
    # obvious suspect, since a 1-4 frame transient is exactly what a 3-8 frame
    # misalignment destroys -- reproduced it at -0.6pp mean, Tarzan -14. But it
    # is the only thing that puts the drums back in the files whose effect byte
    # uses this dialect: Trans-Atlantic sounds 0 noise frames against the
    # original's 1089 without it and 928 with it, at exactly the original's
    # onset counts. Per song, on the noise criterion in fidelity_better.
    "two_stage",
    # The bit-$80 drum. Only seven files carry the block at all, and it seizes
    # a voice's pitch for two frames in every period, so it is per song for the
    # same reason as the two above rather than because it measures badly --
    # Trans-Atlantic keeps melody at 94.7%, gains a point of wave and moves its
    # noise from an inaudible $0685 to $3744 against the original's $302B.
    "sfx_drum",
}


def _parse(blob: bytes, ntables: int = 4):
    """Tracks and patterns out of a .sng, for scoring."""
    pos = 4 + 32 * 3
    subtunes = blob[pos]; pos += 1
    tracks = []
    for _ in range(subtunes * 3):
        n = blob[pos]; pos += 1
        tracks.append(list(blob[pos:pos + n + 1])); pos += n + 1
    ninstr = blob[pos]; pos += 1
    pos += ninstr * 25
    for _ in range(ntables):
        t = blob[pos]; pos += 1; pos += 2 * t
    npatt = blob[pos]; pos += 1
    patterns = []
    for _ in range(npatt):
        rows = blob[pos]; pos += 1
        patterns.append(blob[pos:pos + rows * 4]); pos += rows * 4
    return tracks, patterns


REPEAT, TRANSDOWN, LOOPSONG = 0xD0, 0xE0, 0xFF


def _played_rows(order: list[int], patterns: list[bytes], limit: int = 200000) -> int:
    """Rows an orderlist actually plays, following gplay.c:977-992.

    Counting *stored* rows instead would punish exactly the options that cost
    nothing: --prune-patterns removes patterns no orderlist can reach, and
    --dedup-patterns makes identical ones share, so both shrink the pattern
    table while playing the same music. Measuring playback makes them free,
    which lets the size tie-break pick them up.
    """
    total, ptr, repeat = 0, 0, 0
    while ptr < len(order) and total < limit:
        if order[ptr] == LOOPSONG:
            break
        if TRANSDOWN <= order[ptr] < LOOPSONG:
            ptr += 1
            if ptr >= len(order):
                break
        if REPEAT <= order[ptr] < TRANSDOWN:
            repeat = order[ptr] - REPEAT
            ptr += 1
            if ptr >= len(order):
                break
        num = order[ptr]
        if num < len(patterns):
            total += len(patterns[num]) // 4
        if repeat:
            repeat -= 1
        else:
            ptr += 1
    return total


def _score(blob: bytes) -> tuple[int, int, int]:
    """(playable subtunes, rows played, -bytes) -- bigger is better."""
    tracks, patterns = _parse(blob)
    playable = sum(1 for k in range(0, len(tracks), 3)
                   if any(t != DEFAULT_TRACK for t in tracks[k:k + 3]))
    rows = sum(_played_rows(t, patterns) for t in tracks)
    return playable, rows, -len(blob)


def pack_multiplier(sid_path: Path) -> int:
    """The gt2reloc -S value this song's .sng is tempo'd for.

    Not searched and not an option of convert(): it is a property of the
    tune's player, read from its speed gate (goatwriter.find_song_speeds). A
    tune whose sequencer ticks every frame or every other frame cannot play
    at speed in a 1x Goattracker -- the fastest steady row is three calls --
    so `--tempo auto` writes frames*multiplier calls per row and the packing
    step must raise the call rate to match. 1 means pack plainly; siddump
    cannot check this (it ignores the PSID speed field), only a
    cycle-counting emulator can.
    """
    try:
        sid = load_sid(str(sid_path))
        sid, det = _detect_tables(sid, lambda m: None)
        speeds = find_song_speeds(sid, det if det.can_convert else None)
        return recommended_multiplier(speeds, 0,
                                      FIXED.get("skip_gate", False))
    except Exception:  # noqa: BLE001 - an unreadable song just packs plainly
        return 1


def best_options(sid_path: Path) -> dict | None:
    """Search every combination for one file; None if it never converts."""
    best = None
    for rows in MAX_ROWS:
        for flags in itertools.product((False, True), repeat=len(TOGGLES)):
            opts = dict(zip(TOGGLES, flags), max_rows=rows)
            try:
                blob = convert(str(sid_path), log=lambda m: None, **opts, **FIXED)
            except Exception:  # noqa: BLE001 - a failed combination is just a miss
                continue
            score = _score(blob)
            if best is None or score > best[0]:
                best = (score, opts, len(blob))
    if best is None:
        return None
    score, opts, size = best
    return {
        **{k: opts[k] for k in ("max_rows", *TOGGLES)},
        "bytes": size,
        "subtunes": score[0],
        "rows": score[1],
    }


# Options that change no *structure* -- same subtunes, same rows, same byte
# count -- so `_score` above cannot see them at all and adding them to TOGGLES
# would tie every time and silently pick the default. They can only be chosen by
# playing both settings, which needs siddump and gt2reloc, so they live behind
# `--fidelity` rather than in the search every commit re-runs.
FIDELITY_TOGGLES = ("no_test_restart", "two_stage", "sfx_drum")

# How much better a setting must play before it is recorded. `melody` is a
# difflib ratio, so small differences are noise; 2 points is well inside the
# 16-17 the three files that want --no-test-restart gain, and well outside
# anything seen from re-tracing an unchanged conversion.
FIDELITY_MARGIN = 0.02


def _noise_pitch(trace, nframes: int) -> int:
    """Median $D400/$D401 across the frames a side spends on noise, 0 if none.

    The SID's noise is a shift register clocked by the frequency, so this is
    what decides whether a noise frame is a drum or nothing at all -- see
    `fidelity_better`.
    """
    import fidelity as F                            # noqa: PLC0415
    vals = []
    for v in trace:
        wf = F.register_timeline(v.wf_events, nframes)
        fq = F.register_timeline(v.freq_events, nframes)
        vals += [fq[f] for f in range(nframes) if wf[f] & 0x80]
    return sorted(vals)[len(vals) // 2] if vals else 0


def fidelity_better(cand: tuple, ref: tuple,
                    margin: float = FIDELITY_MARGIN) -> bool:
    """Is `cand` a better-playing (melody, sequence, attacks, noise) than `ref`?

    Two ways to win, and both are one-sided questions rather than agreement
    percentages.

    **Plays more of the tune.** A gain on `melody` of at least `margin`, with
    `sequence` and the raw attack count not falling. The last two are the lesson
    of section 7.eee rather than belt and braces: the candidate this search was
    first built for reached `wave` 99.5% on Commando by deleting 79 notes,
    because a per-frame agreement rewards losing the events it scores, and
    `melody` collapses consecutive repeats so it cannot see a re-struck note
    lost either.

    **Sounds a register the original sounds and we do not.** `noise` is
    (ours, theirs) frames of noise. A conversion with *none* where the original
    has some is missing its drums outright -- Trans-Atlantic sounds 0 frames
    against 1089 -- and no agreement percentage can say that, because there is
    nothing on our side to disagree with. Restoring it must still not cost
    notes, so the melody and sequence guards apply unchanged; it simply does not
    have to *gain* on them.

    Deliberately not scored on `wave`. Restoring a 1-4 frame transient moves it
    the wrong way even when the transient is right -- section 7.eee again, and
    measured: the two-stage attack gives Trans-Atlantic its 250 missing noise
    onsets at exactly the original's counts and takes `wave` from 71% to 65%.
    """
    plays_more = cand[0] >= ref[0] + margin
    keeps_notes = (cand[1] >= ref[1] - margin
                   and cand[2] >= ref[2]
                   and cand[0] >= ref[0] - margin)
    # "Closer to the original than none at all", which is what restoring a
    # register has to mean: |ours - theirs| < |0 - theirs|. Not a fitted
    # threshold -- it is the statement that the quantity moved towards the
    # target rather than merely away from zero. Without it the criterion had no
    # upper bound and took Sigma Seven, whose two-stage attack sounds 82 noise
    # frames where the original sounds 41: drums invented at twice the rate are
    # not an improvement on drums missing.
    ours, theirs, our_hz, their_hz = cand[3]

    def audible(state) -> bool:
        """Noise a listener would hear: some frames, within an octave of the
        original's pitch.

        Applied to the *reference* as well as the candidate, which is what lets
        an audible setting beat an inaudible one. Judged on frame count alone,
        `--two-stage`'s silent noise counted as "we have drums now" and blocked
        `--sfx-drum` from ever being reached on the one file that needs both.
        """
        frames, _, our_pitch, their_pitch = state
        return bool(frames) and our_pitch * 2 >= their_pitch

    finds_noise = (theirs and not audible(ref[3]) and audible(cand[3])
                   and abs(ours - theirs) < theirs
                   # ...and the noise has to be audible. The SID's noise is an
                   # LFSR clocked by the frequency register, so a noise frame at
                   # a low frequency barely clocks it and makes no sound. The
                   # first version of this criterion counted frames and not
                   # sound, and selected four files whose restored "drums" a
                   # listener could not hear at all: the attack in this dialect
                   # carries a *pitch* as well as a waveform (Trans-Atlantic
                   # writes $38 over the note's frequency high byte) and only
                   # the waveform is read, so the noise plays at the note's own
                   # $05xx and is inaudible. Within an octave is the test --
                   # a musical unit, not a fitted threshold.
                   )
    return keeps_notes and bool(plays_more or finds_noise)


def tune_by_fidelity(sid_path: Path, base: dict, multiplier: int,
                     siddump: str, gt2reloc: str, seconds: int,
                     log=lambda m: None) -> dict:
    """The FIDELITY_TOGGLES settings that play this song best, or {}.

    Scored by `fidelity_better`, which is where the criteria are explained.

    Returns only settings that differ from the default, so a song that gains
    nothing adds nothing to the JSON -- an entry recording `False` would look
    like a measured decision when it is the absence of one.
    """
    import shutil                                   # noqa: PLC0415
    import fidelity as F                            # noqa: PLC0415

    workdir, _ = F.make_workdir()
    workdir = Path(workdir)
    local = workdir / "o.sid"
    shutil.copyfile(sid_path, local)
    sub = F.resolve_subtune(sid_path, "auto")
    orig = F.run_siddump(local, seconds, sub, siddump, 0)

    def play(extra: dict):
        blob = convert(str(sid_path), log=lambda m: None,
                       **base, **FIXED, **extra)
        blob, _ = F.legalise_restarts(blob)
        packed = F.pack_sid(blob, workdir, gt2reloc, multiplier)
        if packed is None:
            return None
        dump = F.run_siddump(packed, seconds, sub, siddump, calls=multiplier)
        got = F.compare(orig, dump)
        if got["melody"] is None or got["sequence"] is None:
            return None
        nf = seconds * 50
        wv = F.wave_compare(orig, dump, nframes=nf,
                            lag=F.startup_lag(orig, dump)[0])
        return (got["melody"], got["sequence"],
                sum(len(v.attacks) for v in dump),
                (wv["our_noise_frames"], wv["orig_noise_frames"],
                 _noise_pitch(dump, nf), _noise_pitch(orig, nf)))

    ref = play({})
    if ref is None:
        return {}
    out: dict = {}
    for flags in itertools.product((False, True), repeat=len(FIDELITY_TOGGLES)):
        if not any(flags):
            continue
        extra = dict(zip(FIDELITY_TOGGLES, flags))
        cand = play(extra)
        if cand is None:
            continue
        if fidelity_better(cand, ref):
            ref, out = cand, {k: v for k, v in extra.items() if v}
    if out:
        log(f"    {sid_path.name}: {' '.join(sorted(out))} "
            f"(melody {ref[0]:.0%})")
    return out


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(prog="presets")
    parser.add_argument("sid_dir", help="directory of .sid files (searched recursively)")
    parser.add_argument("-o", "--output", default="presets.json")
    parser.add_argument(
        "--fidelity", action="store_true",
        help="also search the options that change no structure, by playing "
             f"both settings and comparing: {', '.join(FIDELITY_TOGGLES)}. "
             "Needs siddump and gt2reloc, and traces two emulations per "
             "setting per song, so it is off by default -- the structural "
             "search is what every commit re-runs")
    parser.add_argument("-t", "--seconds", type=int, default=10,
                        help="trace length for --fidelity (default 10)")
    parser.add_argument(
        "--no-carry", action="store_true",
        help="do not carry forward the --fidelity settings already recorded in "
             "the output file. Without --fidelity they are carried by default, "
             "because the structural search cannot see them and dropping them "
             "silently would turn a measured decision into an absent one on "
             "the next routine regeneration")
    parser.add_argument("--siddump", default=None)
    parser.add_argument("--gt2reloc", default=None)
    args = parser.parse_args(argv)

    sid_dir = Path(args.sid_dir)
    if not sid_dir.is_dir():
        print(f"error: not a directory: {sid_dir}", file=sys.stderr)
        return 1

    if args.fidelity:
        import fidelity as F                         # noqa: PLC0415
        siddump = args.siddump or F.SIDDUMP
        gt2reloc = args.gt2reloc or F.GT2RELOC

    # The structural search cannot see FIDELITY_TOGGLES at all, so a run without
    # --fidelity has nothing to say about them -- and a regeneration that
    # dropped them would leave three measured files silently back on the
    # default. Carried forward instead, and counted out loud.
    carried: dict[str, dict] = {}
    if not args.fidelity and not args.no_carry:
        try:
            prev = json.loads(Path(args.output).read_text(encoding="utf-8"))
            for name, e in (prev.get("songs") or {}).items():
                keep = {k: e[k] for k in FIDELITY_TOGGLES if e.get(k)}
                if keep:
                    carried[name] = keep
        except (OSError, ValueError):
            pass

    songs: dict[str, dict] = {}
    paths = sorted(sid_dir.rglob("*.sid"), key=lambda p: p.name.lower())
    for path in paths:
        found = best_options(path)
        if found:
            found["multiplier"] = pack_multiplier(path)
            if args.fidelity:
                base = {k: found[k] for k in ("max_rows", *TOGGLES)}
                try:
                    found.update(tune_by_fidelity(
                        path, base, found["multiplier"], siddump, gt2reloc,
                        args.seconds,
                        log=lambda m: print(m, file=sys.stderr)))
                except Exception as exc:             # noqa: BLE001
                    # A song the tools cannot play keeps its structural
                    # result. Silently dropping to the default would be
                    # indistinguishable from a measured decision.
                    print(f"    {path.name}: fidelity search failed "
                          f"({type(exc).__name__}), keeping defaults",
                          file=sys.stderr)
            elif path.name in carried:
                found.update(carried[path.name])
            songs[path.name] = found
        print(f"  {path.name:44} {'-' if not found else found['max_rows']}",
              file=sys.stderr)

    doc = {
        "generator": f"h2g {__version__} presets.py",
        "corpus": str(sid_dir),
        "always": {"format": FIXED["fmt"], "tempo": FIXED["tempo"],
                   # Without this gt2reloc refuses 28 of the 78 outright, so
                   # it belongs with the packing step rather than beside the
                   # searched options.
                   "legal_restart": FIXED["legal_restart"],
                   # The second operand byte of a pitch slide, in the players
                   # that have one; a no-op everywhere else. Correct wherever
                   # it applies, so fixed rather than searched — and emitted
                   # here because fidelity.py reads `always.slides`.
                   "slides": FIXED["slides"],
                   # Same footing as slides: the instrument effect byte's two
                   # decoded bits are gated on detection finding the routine
                   # that reads them, a no-op elsewhere. fidelity.py reads
                   # `always.effects` too.
                   "effects": FIXED["effects"],
                   # A $C0-$FE status byte consumes only itself, per the
                   # player's own `BIT status / BVS`. Gated on that shape,
                   # so a no-op in the 34 files that lack it. Measured
                   # delta is zero across every file whose bytes it moves:
                   # taken for faithfulness, not for score.
                   "status_bit6": FIXED["status_bit6"],
                   # An instrument change on a rest is carried by the rest,
                   # per gplay.c:912-914's latch, instead of a C-0 on the
                   # Clear Voice -- which is a click and a retrigger. 1422
                   # rows across 64 files. Found by ear; no dimension of
                   # FIDELITY.md reports it.
                   "rest_instrument": FIXED["rest_instrument"],
                   # The VB6 original burned instrument 1 on an empty
                   # placeholder; Goattracker reserves no slot of its own.
                   # Frees a slot and five wavetable entries, and lines the
                   # numbering up with the player's own records.
                   "compact_instruments": FIXED["compact_instruments"],
                   # Its companion, and not optional beside it: a phantom
                   # pattern entry decoded under the bit-6 grammar emits
                   # garbage portamento, and gt2reloc re-encodes the speed
                   # table file-wide, so one junk subtune's phantom
                   # corrupts every other subtune's pitches.
                   "reject_phantoms": FIXED["reject_phantoms"],
                   # Hubbard's transposes of 24, 36 and 48 semitones do not
                   # fit Goattracker's +14 orderlist ceiling and were
                   # clamped, playing four files up to 21 semitones flat.
                   # Fixed rather than searched for the same reason as the
                   # rest of this block: it is the player's own arithmetic
                   # where it applies, and a no-op in the 79 files it does
                   # not reach.
                   "fold_transpose": FIXED["fold_transpose"],
                   # Both read the instrument's envelope as the player means
                   # it. --sustain-exact undoes a VB6 misreading of SID
                   # register 6 that lowered a full sustain to E in 64 files;
                   # --no-hard-restart stops Goattracker writing $0F00 over
                   # $D405/$D406 before every note, which no Hubbard player
                   # does. Together they take per-frame ADSR agreement from
                   # 54.2% to 66.2% corpus-wide. Fixed rather than searched:
                   # neither is a per-song taste, both are what the register
                   # holds. The cost is recorded -- no-hard-restart takes
                   # Confuzion from 82% to 78% melody, because hard restart is
                   # what makes a re-struck note retrigger reliably.
                   "sustain_exact": FIXED["sustain_exact"],
                   "no_hard_restart": FIXED["no_hard_restart"],
                   # Most Hubbard players decrement the speed gate on only
                   # some frames -- a counter above it jumps past the gate, or
                   # returns from the play call outright -- so a row lasts
                   # (reload + 1) x (O + 1) / O frames. Applied only where
                   # that is a whole number, which Goattracker can express;
                   # the fractional majority is untouched. Nine files move,
                   # Tarzan's timing from 0.667 to 1.000 against the original
                   # (melody 73% -> 96%) and Pygmies_Revenge 0.750 -> 1.000
                   # (80% -> 93%), none worse. It also changes the -S factor,
                   # so `multiplier` below moves with it -- pack_multiplier
                   # passes skip_gate for exactly that reason.
                   "skip_gate": FIXED["skip_gate"],
                   # The player sweeps the pulse width every frame in
                   # 43 files; the tool wrote the starting width and
                   # stopped, so those leads played a static duty
                   # cycle. Gated on finding the routine, so a no-op
                   # in the other 52, and on a zero rate within a file
                   # that has it. Fixed rather than searched: it is the
                   # player's own arithmetic, not a per-song taste.
                   # Takes siddump's Pul column from 1% of the
                   # original's movement to 60%; every column in
                   # FIDELITY.md is unchanged to the decimal.
                   # v0.5.72 read the filter and wired it into convert()
                   # and README, but not into this block or into
                   # fidelity._preset_opts -- so every measurement ran
                   # with it off and a regeneration would have shipped
                   # the feature dead, exactly as --slides once was
                   # (AUDIT.md, first verified defect).
                   "filters": FIXED["filters"],
                   "pulse": FIXED["pulse"],
                   # 56 of 95 players run a per-instrument vibrato out of one
                   # record byte, and this writer left the two Goattracker
                   # bytes that drive it at zero -- so nothing it produced ever
                   # vibrated and a third of the corpus moved the pitch not at
                   # all where the original does. Gated on finding the routine
                   # and on a nonzero parameter, so a no-op in the other 39.
                   # Fixed rather than searched, like the rest of this block:
                   # it is the player's own parameter, not a per-song taste.
                   # Takes the corpus median `bend` from 0.06x to 0.33x and the
                   # files bending nothing from 33 to 11, moving 29 of the 35
                   # files it touches toward the original and 6 away -- all six
                   # already overshooting for another reason.
                   "vibrato": FIXED["vibrato"],
                   # The packing step of the conversion. Recorded here rather
                   # than searched: it takes no per-song decision, it just
                   # turns the .sng into something a SID player can play.
                   "gt2reloc": True},
        "criteria": "most playable subtunes, then most rows, then smallest file",
        "songs": songs,
    }
    Path(args.output).write_text(json.dumps(doc, indent=2) + "\n", encoding="utf-8")
    print(f"{len(songs)}/{len(paths)} convertible -> {args.output}", file=sys.stderr)
    kept = sum(1 for n in carried if n in songs)
    if kept:
        print(f"carried {kept} --fidelity setting(s) forward from "
              f"{args.output}; re-run with --fidelity to re-measure them",
              file=sys.stderr)
    if args.fidelity:
        n = sum(1 for e in songs.values()
                if any(e.get(k) for k in FIDELITY_TOGGLES))
        print(f"--fidelity searched {', '.join(FIDELITY_TOGGLES)} over "
              f"{len(songs)} song(s) at {args.seconds}s: {n} took a non-default "
              "setting", file=sys.stderr)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
