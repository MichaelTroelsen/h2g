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

`--rest-keyoff` is fixed on the same terms, and it is the one option here
whose evidence is a dimension built for it: v0.5.270 added `gate`, the $D404
bit every other column ignores, precisely because the option moved 19 files'
bytes and one number. Scored on it, 12 files move and all 12 improve. A
mechanism that cannot be measured is not the same as one that does not work,
and the fix for the first is an instrument.

`--voice-two-stage` is fixed on the same terms and for the same reason, not
because it was measured corpus-wide: its signature matches **one** corpus file
(Ninja), forcing it on every file moves that file's bytes and nobody else's,
and there it takes `onset` 40% -> 80% with `melody`, `seq`, `noise` and the
rest unmoved.

This used to carry a second reason -- that a sixth `--fidelity` toggle "would
double a four-hour search". **That cost was never timed and is wrong.** A
corpus search is 8 minutes (v0.5.300, timed twice), so doubling it buys a
one-file question for 8 minutes, which is not a reason to refuse anything. The
decision stands on the first reason alone: a toggle whose signature reaches one
file is a fixed option, not a search dimension, because a search would spend 82
songs proving it changes nothing. Anyone reopening this should reopen it on
that argument, not on the clock.
"""
from __future__ import annotations

import argparse
import itertools
import math
import json
import sys
from pathlib import Path

from h2g import __version__
from h2g.convert import _detect_tables, convert
from h2g.goatwriter import (FORMAT_GTS5, find_song_speeds,
                            pack_subtune, recommended_multiplier)
from h2g.patterns import DEFAULT_TRACK
from h2g.sidfile import find_freq_table, load_sid

# Searched per song. Order is irrelevant -- every combination is tried.
MAX_ROWS = (94, 128)
TOGGLES = ("pack", "prune", "dedup")

# Not searched; see the module docstring.
FIXED = {"fmt": FORMAT_GTS5, "tempo": "auto", "legal_restart": True,
         # Rides with legal_restart because it decides the same byte.
         # In FIXED rather than FIDELITY_TOGGLES because the search
         # CANNOT select it: measured over all 29 files it moves,
         # 28 are flat on melody, sequence and pitch and one improves,
         # so `fidelity_better` sees nothing to prefer. What it fixes
         # is the length rule, which only `len` measures -- Action
         # Biker goes from 856 attacks in 180s to the original's 291.
         "silent_park": True,
         "skip_gate": True,
         "slides": True, "effects": True, "status_bit6": True,
         "reject_phantoms": True, "fold_transpose": True,
         "sustain_exact": True, "no_hard_restart": True,
         "filters": True, "pulse": True, "vibrato": True,
         "vibrato_command": True, "cut_release": True, "tie": True,
         "rest_instrument": True, "compact_instruments": True,
         "voice_two_stage": True, "rest_keyoff": True}

# convert() options deliberately NOT in the `always` block, and why. Every
# other option must appear there: one left out silently measures as doing
# nothing, which is how --slides and --filter each shipped dead.
# test_preset_passthrough.py checks this set covers the difference.
EXCLUDED_FROM_ALWAYS = {
    # An integer, not a toggle, and a property of the PLAYER being ripped
    # rather than a setting that could be right for everyone: how many frames
    # that player holds the gate off before a note. There is no value that
    # suits the corpus, so there is nothing to put in `always`. It is also not
    # searchable by `--fidelity`, whose walk is over booleans -- a song gets it
    # from a measurement written into its own entry. 5_Title_Tunes is the first:
    # its player releases for a uniform 4 frames where the built-in constant
    # asks for 2, and at 4 (with --max-hard-restart to lift the row bound off
    # half the row) its gate goes 0.4996 -> 0.7494 with melody, seq, pitch and
    # wave every one unchanged. Unset it changes no byte anywhere.
    "hard_restart_frames",
    # Per song and never a default, because SAFETY here is a property of the
    # tune rather than of the option. `--force-park` parks every voice on the
    # silent pattern even where the restart is already legal, which is the
    # only way to end a tune whose data never says it ended -- Confuzion has
    # no `$FE` anywhere in its six-byte track region and runs ~295 s past a
    # 305 s original, the corpus's only measured failure of the +-5 s length
    # rule. It is correct there because that file's three voices end TOGETHER
    # (all exactly 5216 rows, measured on the final .sng through songview),
    # and it would TRUNCATE a tune whose voices do not. Nothing checks that,
    # so it cannot be a blanket setting. Invisible to `fidelity_better` for
    # the same reason `silent_park` and `regrid` are: every column compares
    # WHAT is played, and a tune playing the right music forever scores
    # perfectly. `len` is the only instrument that reads it.
    "force_park",
    # Per song, like hard_restart_frames, and for a structural reason as well
    # as a search one: the phase plan costs pattern copies and pulse-table
    # rows, both bounded, and a file where either budget overflows silently
    # keeps its old sweep -- a per-song entry records a measured adoption
    # where a blanket default would record an assumption. It is also
    # invisible to `fidelity_better` for the same reason silent_park is:
    # melody, onset and noise cannot see a duty cycle's phase; `pspan` and
    # `pphase` can, and neither is a search criterion.
    #
    # **DECIDED AT 64c795b: IT STAYS HERE RATHER THAN JOINING
    # FIDELITY_TOGGLES, AND THE REASON IS NOT COST.** Every leg of that is
    # measured rather than reasoned.
    #
    # * **The criterion's entire input has no pulse term.** `tune_by_fidelity`'s
    #   `play()` returns nine things -- melody, sequence, our attacks, a
    #   (noise frames, theirs, our pitch, their pitch) tuple, `reversal_ratio`,
    #   `onset_frame_agreement`, `sound_run_agreement`, `gate` and the
    #   ORIGINAL's attack count. Not one reads $D402/$D403. (The sentence
    #   above named three of those nine; it is nine now, and the conclusion is
    #   unchanged.)
    # * **So the search says no, and that is measured through the real
    #   criterion rather than inferred from its terms.** With FIDELITY_TOGGLES
    #   monkeypatched to `("pulse_phase",)` and the search run over the six
    #   files the option reaches (5_Title_Tunes, Commando, Confuzion,
    #   Geoff_Capes, Gerry_the_Germ, Zoids): **0 of 6 took it**. Run again
    #   with the shipped seven PLUS pulse_phase: **0 of 6** again.
    # * **AND IT WOULD DESTROY FOUR MEASURED ADOPTIONS.** `main()` carries a
    #   previous entry's per-song decisions across a `--fidelity` run only
    #   `if k not in FIDELITY_TOGGLES` -- membership is what makes the search
    #   AUTHORITATIVE for a key. `pulse_phase` is adopted by hand on four of
    #   the six (5_Title_Tunes, Commando, Gerry_the_Germ, Zoids), so promoting
    #   it would replace four yeses with a no on the next regeneration. That
    #   is the same failure this file records four times already, one line
    #   down in the `regrid` entry and again in `carried_entry`.
    # * **THE COST ARGUMENT IS REFUTED, so do not reach for it.** An eighth
    #   toggle nominally doubles the walk (127 -> 255 combinations), but
    #   `_redundant_combination` prunes every combination whose bytes are
    #   already walked, so the real cost tracks the number of LIVE options per
    #   song. Timed over the same six files: seven toggles **161.0 s**, eight
    #   toggles **159.8 s** -- indistinguishable. (For scale, one toggle over
    #   those six is 12 s, and 27 s a song puts a 7-toggle corpus search near
    #   40 minutes for 89 songs, against the "about a minute a song / 80
    #   minutes" in this file's own `--shard` help. That help is roughly 2x
    #   pessimistic and CLAUDE.md's "8 minutes" is a FIVE-toggle figure.)
    #
    # If anyone does want it searchable, `FIDELITY_CONFIRMED` is the escape
    # hatch -- but it would need all four files listed there, which is
    # hand-recording with extra steps and strictly worse than this.
    "pulse_phase",
    # Per song, and the reason is that NOTHING `fidelity_better` scores can
    # see what it fixes. `--regrid` spends the fractional part of a row the
    # tempo cannot express (Monty's is 384/127 = 3.0236 frames against the 3
    # we emit), and the defect it removes is CUMULATIVE DRIFT -- which melody
    # is blind to by construction: it is a difflib ratio over a note sequence
    # and is satisfied by a tune playing the right music 0.78% fast forever.
    # Corpus: it reaches 18 files, drift improves on 14 of them and five land
    # on exactly 0.00 -- but melody COLLAPSES on two (One_on_One -37.0pp,
    # Sanxion -19.9pp), which is why it can never be a default.
    #
    # WHY IT IS UNSEARCHABLE -- DECIDED AT v0.5.411, AND NOT FOR THE REASON
    # THIS COMMENT USED TO GIVE. It said "`--pace`'s drift line is the only
    # instrument that reads it and it is not a report column". Both halves are
    # wrong. `fidelity.drift(orig, ours)` takes the SAME TWO TRACES `play()`
    # already holds, and `drift_per_1000` IS a registered `Dimension` in the
    # report (checked, beside `melody`; CLAUDE.md records its coverage as 80 of
    # 83 rows at v0.5.407, which is that commit's figure and not re-measured
    # here). So growing a drift term is roughly two lines, and the exclusion is
    # not forced by any measurement gap.
    #
    # It would also not help, and that is the finding. `fidelity_better`'s
    # `keeps_notes` requires `cand[2] >= ref[2]` -- OUR raw attack count, with
    # no margin -- and it gates every acceptance term in the function. But the
    # whole benefit of `--regrid` includes REMOVING SURPLUS ATTACKS, measured
    # at v0.5.411 on the four eligible files that take it well:
    #
    #     Arcade_Classics   375 -> 372   original 372   exact
    #     Sigma_Seven       417 -> 414   original 414   exact
    #     Wiz               446 -> 437   original 437   exact
    #     Rikky             201 -> 196   original 197   within one
    #
    # Every one is a strict improvement that the guard reads as a loss, so all
    # four are refused before any term is consulted -- with or without a drift
    # term. The guard compares OURS TO OURS and the original's count never
    # enters the tuple, so it cannot tell "deleted three real notes" from
    # "stopped inventing three". That is the same trap CLAUDE.md states for
    # register agreements ("read any register agreement next to both sides'
    # note counts"), in the one place here that already has both counts to
    # hand and uses only one.
    #
    # The guard is load-bearing and deliberate -- the comment in
    # `fidelity_better` calls it the anti-gaming clause that "has protected
    # every term here since the first", because a conversion with fewer notes
    # scores better on `wave` and `gate` for having fewer events to disagree
    # about. So the change is NOT to relax it but to make it TWO-SIDED against
    # `orig_attacks`: a reduction that moves toward the original's count is an
    # improvement, a reduction past it is the gaming the guard exists to stop.
    #
    # NOT IMPLEMENTED HERE, deliberately. Widening this function's criterion is
    # exactly the change that cost seven measured settings and gained one (see
    # `gave_back` below), so it wants a corpus `--fidelity` A/B against the
    # shipped presets before it lands, not a plausible argument. The decision
    # recorded is: the exclusion list should NOT keep growing, and the term to
    # add is not `drift` but the original's attack count in `keeps_notes`.
    "regrid",
    # A LIST of instrument numbers, not a toggle, so the boolean --fidelity
    # walk cannot search it and there is no single value for `always`. It
    # names the instruments whose first frame should carry the record's own
    # waveform rather than the testbit -- right for some records in a file and
    # poison for others (5 Title Tunes' instrument 7), which is exactly why it
    # is a set and not a flag.
    #
    # IT WAS NOT IN THIS REGISTRY UNTIL v0.5.398 AND THE v0.5.397 REGENERATION
    # DELETED IT. Both songs that carried it lost it -- 5_Title_Tunes, whose
    # set is HUMAN-APPROVED and worth wave 90 -> 99% and hold 0 -> 86%, and
    # Auf Wiedersehen Monty (hold 0 -> 75%). That is the fourth time an
    # artefact regeneration has silently destroyed a measured decision here
    # (hard_restart_frames at v0.5.389, five rest_envelope_silence entries
    # lost for 25 versions, and this). The rule the repeats point at: an
    # option that is not a boolean cannot be re-derived by the search, so the
    # ONLY copy of the decision is the file -- adding it here is not
    # bookkeeping, it is the whole record.
    "real_firstwave_instruments",
    # Not a setting for a song: it selects a DIFFERENT song out of the same
    # file. `--engine 1` rips the second player a .sid carries, where it
    # carries one -- Powerplay Hockey's nine game cues against the tune its
    # PSID header starts on (section 7.kkkkk). A preset records the best way
    # to convert *the* tune, and there is no sense in which the cues are a
    # better conversion of it, so this belongs on a command line. Nothing in
    # SURVEY.md, presets.json or FIDELITY.md is generated with it.
    "engine",
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
    # The bit-6 rest's parked waveform. Off by default and not shippable:
    # v0.5.284 measured melody -43pp over 8 files for it, and the cause is
    # still unknown -- the TONEPORTA explanation was refuted at v0.5.285, the
    # emission defect behind that A/B fixed at v0.5.286, and the wavetable
    # clobbering it at v0.5.311. The option exists so the measurement can be
    # re-run against an emitter that does what it says.
    #
    # **AND IT WAS RE-RUN, AT v0.5.459, THE ONLY WAY THAT SETTLES IT: BY MAKING
    # THE SEARCH ITSELF WALK THE OPTION. It was selected on ZERO of 17.**
    # The premise this was queued under -- "`fidelity_better` has no term that
    # can see a rest-parked waveform" -- is FALSE, and measuring it was the
    # first thing that had to happen. Forced on over its whole population (the
    # 17 songs whose `det.rest_silence_kind` is `testbit`; it is inert
    # everywhere else), 15 of 17 move bytes and the columns move plainly:
    # `wave` on 12 files, `adsr` on 8, `gate` and `drift_per_1000` on 5,
    # `our_noise_frames` on 4, and `melody`, `sequence` and `our_attacks` on 3
    # each -- four of those being terms `fidelity_better` reads directly.
    #
    # The real reason it was adopted on zero songs is that it was never a
    # candidate: it is not in FIDELITY_TOGGLES. So it was ADDED, and the search
    # run over all 17 at `-t 180` with `--carry-from` the shipped file. **It
    # chose the option on none of them**, while reproducing the shipped
    # selection on 15 of the 17. Since those 17 are the entire population, that
    # is zero out of everywhere it could ever be chosen: a refusal on the
    # merits by a criterion that can see it, not a blind spot.
    #
    # It is therefore NOT in FIDELITY_TOGGLES, deliberately, and the cost is
    # the second reason. Eight toggles is 255 combinations against 127, TIMED
    # here at **19m34s for 17 songs = 69 s a song at 180 s**, against ~50 s a
    # song for seven (CLAUDE.md's 75-minute serial corpus figure over 89
    # songs). Read that 1.4x as the WORST case rather than the corpus's: these
    # 17 are the files where the new toggle is live, so `_redundant_combination`
    # prunes it on none of them and on the other 72 it should prune it away
    # entirely. Nobody should pay even that for an option the criterion has now
    # refused everywhere it applies -- and nobody should re-run the experiment,
    # which is why the numbers are here rather than in a run record.
    "rest_wave_silence",
    # The bit-6 rest's zeroed ENVELOPE pair -- a different write in the same
    # branch, and a mechanism read off the 6502 rather than guessed: all 21
    # players that silence on a rest do `LDA #$00 / STA SR,Y / STA AD,Y`
    # there (detect._find_rest_silence_envelope). Ours rings the record's
    # release nibble through that gap instead. Off by default because the
    # corpus A/B splits: over the 19 files it reaches, `adsr` is **9 up and 7
    # down**, mean +2.5pp, with every other column -- melody, seq, retrig,
    # wave, gate, noise, hold, onset, tail -- flat on every file. Counted on
    # the frames themselves rather than on the column, 9229 moved TO the
    # original's value and 3428 away. It is unambiguous where our rest rows
    # line up with the original's (ACE_II 208 frames toward and 0 away, its
    # 575-frame voice-1 ring-out gone, `adsr` 93 -> 96%; Thundercats 218/0;
    # Shockway Rider 986/15) and loses where they do not -- Arcade Classics
    # and Trans-Atlantic flip sign between the trace's two halves, which is
    # drift, while Bangkok Knights, Skate or Die, I, Ball and Ricochet lose in
    # both halves for a reason not yet identified.
    #
    # **And the search cannot pick it up**: `fidelity_better` scores melody,
    # sequence, attacks, noise, oscillation, noise pitch, onset and hold, and
    # this change moves none of them -- `adsr` is not a term. So this is not
    # "searched per song" like the entries around it; it is an option waiting
    # on a criterion that can see it. Written down here rather than left as a
    # per-song hope, because an option offered and never chosen is the trap
    # CLAUDE.md names.
    "rest_envelope_silence",
    "no_test_restart",
    # The hard restart's row bound raised from `row // 2` to `2 * row // 3`.
    # Per song rather than always, because the sweep that measured it
    # (v0.5.276) found a corpus gain of 1.6pp of mean gate AND one file --
    # Saboteur II, whose 8-call row gives it 5 -- where melody falls 98% to
    # 67% at the same value. A bound whose ceiling is set by a single file is
    # the definition of a per-song question. Searched, not fixed.
    "wide_hard_restart",
    # The same bound taken to the player's own limit, `row - 1`. Twice the
    # corpus gain of `wide` in v0.5.276's sweep (3.3pp of mean gate against
    # 1.6) and twice the damage on the one file that breaks (Saboteur II
    # melody 98% -> 62% against 67%). Offered because `keeps_notes` has now
    # been *seen* to refuse the gentler value on exactly that file rather than
    # merely being expected to -- a guard with a demonstrated catch is
    # evidence for offering the next value along, which a guard on paper is
    # not.
    "max_hard_restart",
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
    # The byte-code wave program: 29 files carry the interpreter, and it is what
    # carries Trans-Atlantic's snare -- all 43 notes now sound noise in their
    # first frames, at $31xx against the original's $30xx. Per song because it
    # takes over the instrument's pitch entirely, and because each `< $80` opcode
    # costs two wavetable entries where the player spends one, so the slides
    # land a frame late.
    "wave_program",
    # Effect bit $10's arpeggio -- per song, never in `always`. The player steps the sequence with a *global* phase counter; a
    # wavetable restarts at every note, so which step a note opens on cannot be
    # reproduced at all. Over the 26 files that use it that trade is median vib
    # 0.22x -> 0.58x against 5 points of mean melody, 7 files losing and After_8
    # 92% -> 52%. `fidelity_better` selects on a melody *gain*, so it would
    # never pick this up even where it helps (Trans-Atlantic: vib 0.17x -> 0.61x
    # with melody unchanged) -- deciding it needs a scorer that weighs
    # oscillation, which is the same gap the noise-pitch case has.
    "pitch_seq",
    # The interleaved engine's OWN arpeggio ($83, patterns.ILV_ARP), and it is
    # in this set for a different reason from `pitch_seq` immediately above --
    # not because the mechanism cannot be reproduced, but because reproducing
    # it exactly is a TRADE the report cannot adjudicate.
    #
    # Reproducing it is not in doubt. Unlike bit $10's, this counter is cleared
    # at every note start ($1397, inside the note-start block at $1388) and the
    # arm flag is cleared once per event ($1155), so a Goattracker wavetable
    # says it exactly -- there is no phase to lose. The cycle, rate and scope
    # are all read from the player's bytes.
    #
    # What the corpus A/B says (v0.5.457, -t 60, the five files it moves):
    # `vib` comes off **0.00** on four of them -- Lion_Heart 0.00 -> 0.56,
    # Radio_ACE 0.00 -> 0.17, Go_Go_Dash 0.00 -> 0.11, Lakers 0.00 -> 0.04 --
    # which is the mechanism arriving where the conversion previously produced
    # no pitch movement at all. It costs `melody` on three: Radio_ACE
    # 97 -> 89%, `seq` 97 -> 83%, `pitch` 97 -> 92%, with Go_Go_Dash and
    # Lakers each losing a point. Every other dimension is flat on every file.
    #
    # So it is the `pitch_seq` shape after all: a gain on an oscillation
    # measure paid for in melody, and `fidelity_better` scores a melody gain
    # and cannot select it. Adopting it per song wants an ear, not another
    # column -- the six interleaved-classic files have never been listened to
    # (`the-six-interleaved-classic-files-have-never-been-listened-to`).
    #
    # `--arpeggio` changes NO byte on any other file: 0 of 89 move with it off
    # and exactly 5 with it on, corpus byte-hashed at v0.5.457.
    "arpeggio",
}


# Settings a *listening test* rejected, whatever the search measured, or a
# setting the search picked from a measurement now known to be invalid (wrong
# subtune traced, wrong window, etc). Keyed per file because that is how they
# are found, and kept here rather than hand-edited into presets.json, which is
# generated and would lose the edit -- along with the reason -- on every
# regeneration, including a plain carry-forward run.
FIDELITY_VETOED: dict[str, set[str]] = {
    # ACE_II's frame pair, withheld because it INVALIDATES A HUMAN APPROVAL.
    # The 0.5.406 search selects `hard_restart_frames: 3` with
    # `max_hard_restart`, and it is a real gain -- measured at 60s with
    # everything else held:
    #
    #   approved bytes   gate 78.3%   mel 99.7  seq 99.8  pit 100  wav 87.3  ads 93.3  hld 42.9
    #   search's choice  gate 93.4%   ... every other column IDENTICAL
    #
    # +15.1 points of gate and nothing worse. But approved.json pins the sha256
    # of the .sng a listener signed off, and adopting this changes it -- so the
    # trade is the listener's to make, not a search's and not this commit's.
    # Exactly the call v0.5.394 made on the same file for
    # `rest_envelope_silence` (+3 adsr, also withheld, also still owed).
    #
    # Lift it by getting the verdict, not by re-reading the number: if the
    # listener prefers the new build, delete this entry and re-approve.
    # ONLY the frame count: `max_hard_restart` was already in the
    # approved bytes, and vetoing it would change the .sng this entry
    # exists to protect -- which it briefly did, caught by the approval
    # check rather than by reading the diff.
    "ACE_II.sid": {"hard_restart_frames"},

    "Dragons_Lair_Part_II.sid": {"pitch_seq"},
    # The v0.5.208+ --fidelity run traced this file's subtune 0 (its PSID
    # startSong) and scored a default-config melody of 9%, low enough for
    # pitch_seq's 14% to read as an improvement. `fidelity.py --diagnose`
    # shows why: the file's own init routine remaps subtunes, and subtune 0
    # of the original corresponds to *our* subtune 9 (89% match there), not
    # our subtune 0 -- the same class of bug CLAUDE.md already documents for
    # this file. The search compared two different pieces of music the whole
    # way through, so neither the veto here nor a future re-run of the search
    # (which will reproduce the same wrong pairing) can be trusted for this
    # file until `resolve_subtune`/`tune_by_fidelity` account for the remap.

    # Empty otherwise, and the entry that was here is worth keeping as a record.
    # Trans-Atlantic's --sfx-drum was vetoed in v0.5.1xx as "a beep and not a
    # drum", on a build with no snare at all and a drum that sounded one pitch
    # for every frame of its burst. Both are fixed: v0.5.203 emits the byte-code
    # snare (387 noise frames against 387) and v0.5.206 gives the burst its two
    # pitches, the drum's own then bit $40's. Asked to A/B the two builds the
    # same listener reported no audible difference at all, which retires the
    # verdict rather than reversing it -- and v0.5.208's oscillation scorer now
    # selects the setting on its own. Lifting a listening veto needs the ear to
    # stop objecting, not a better number; here it did both.
}

# The mirror of the veto: settings recorded by hand because the search as run
# does not carry them -- either it scores them worse, or the run that would pick
# them up has not happened. Each entry says which. Same reason for living here rather than in the
# generated presets.json -- the file would lose both the edit and the reason.
FIDELITY_CONFIRMED: dict[str, set[str]] = {
    # THREE FILES WHOSE `no_test_restart` THE 0.5.406 SEARCH DROPS, and the
    # measurement that says keep it. The joint frame pass shifted the greedy
    # path, and on these the walk now prefers a combination without it:
    #
    #                    melody      pitch       hold        wave
    #   Arcade Classics  98.5->100   92.9->100   75.0->0.0   68.1->66.2
    #   Powerplay        99.3=99.3   97.3->100   75.0->0.0   95.5->91.8
    #   Pygmies Revenge  97.0=97.4   97.5->100   83.3->0.0   61.0->56.0
    #
    # The melody and pitch gains are the ARTEFACT and the hold loss is the
    # real change, which is this option's documented shape read backwards:
    # `--no-test-restart` deletes the testbit frame, the only frame our
    # conversions spend below $10, and siddump needs one to name an attack at
    # all (siddump.c:434-437). So without the option siddump sees our attacks
    # and `melody`/`pitch` read higher -- while `hold`, which measures note
    # LENGTH from sound runs, loses everything it had.
    #
    # `fidelity_better` has a `holds_right` term and still prefers the swap,
    # because its questions are one-sided: a melody gain is enough to accept
    # regardless of what hold does, and only `keeps_notes` and `gave_back` can
    # veto. Neither reads hold. That is the "any one improving is a sound
    # acceptance rule and an unsound replacement rule" case, and it is why
    # these are pinned rather than argued.
    #
    # Dragons_Lair_Part_II drops the same option and is NOT pinned: its hold
    # is 0.0 either way, so the option buys it nothing, and its row is a known
    # harness artefact (melody 14%, the subtune correspondence).
    "Arcade_Classics.sid": {"no_test_restart"},
    "Powerplay_Hockey_USA_vs_USSR.sid": {"no_test_restart"},
    "Pygmies_Revenge.sid": {"no_test_restart"},

    # The snare FIDELITY_VETOED's entry above names as the real one. With
    # v0.5.203's two fixes -- one wavetable entry per opcode, and the record's
    # own waveform restored before the program stops -- its noise runs are
    # *identical* to the original's: `{1: 43, 8: 43}` on both sides, 387 noise
    # frames against 387, where without the program voice 2 sounds none at all
    # against the original's 387.
    #
    # `fidelity_better` still scores it as worse, and the reason is structural
    # rather than a margin: its `finds_noise` criterion requires the reference
    # to have *no* audible noise, and this file already has plenty from another
    # instrument. The test is per file where the defect is per instrument, so a
    # missing snare is masked by a present hi-hat. `melody` meanwhile falls
    # 95% -> 85%, because siddump reads noise onsets as notes and the sequence
    # it compares gains 43 of them -- the same blind spot section 7.eee
    # describes. Fixing the criterion properly means scoring per instrument off
    # `fidelity.noise_runs`, which would re-decide every file's toggles and so
    # wants its own commit and its own corpus run.
    #
    # `pitch_seq` joined it on the same footing for the same reason: the
    # --fidelity run that would apply the new oscillation term had not
    # happened yet. It has now (the corpus run behind v0.5.209) -- the search
    # selects `pitch_seq` and `sfx_drum` for this file on its own, so both are
    # dropped from here. `wave_program` stays: the search still does not pick
    # it up on its own (see the `finds_noise`/per-instrument gap above, which
    # applies to it too), so it remains a hand-recorded measurement.
    "Trans-Atlantic_Balloon_Challenge.sid": {"wave_program"},
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
        return recommended_multiplier(speeds,
                                      pack_subtune(speeds, sid.start_song),
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
# Everything a regeneration must carry rather than re-derive. The toggles
# are one half; the other is the options a search CANNOT express -- ints,
# and anything measured by hand into a song's own entry. Keyed on
# EXCLUDED_FROM_ALWAYS so a future per-song option joins by being
# declared there, rather than by being remembered here.
# `fmt` is spelled `format` in the artefact and nowhere else; every other
# FIXED key keeps its name. One entry rather than a rule, because one
# rename is a fact and not a convention.
_ALWAYS_NAME = {"fmt": "format"}

# **EVERY MEMBER MUST BE BOOLEAN-VALUED, and that is a property of the WALK
# rather than a style rule.** `tune_by_fidelity` enumerates
# `itertools.product((False, True), repeat=len(FIDELITY_TOGGLES))`, so this
# tuple can express exactly two values per option. An option whose `convert()`
# parameter is not a bool would be handed `True` where it expects something
# else, and the search would score a conversion nobody asked for -- silently,
# because a candidate that converts is a candidate that gets scored.
#
# That is why `--real-firstwave-instruments` is never chosen: its value is a
# TUPLE OF INSTRUMENT NUMBERS, so no boolean enumeration can produce it, and
# its adoptions are hand-recorded exactly as `--regrid`'s are. `engine` (int)
# and `hard_restart_frames` (None) have the same shape. This is a structural
# limit of the search, NOT a criterion declining a population -- a distinction
# worth keeping, because "the search never picks it" reads like a scoring bug.
# `tests/test_presets.py` derives the check from `inspect.signature(convert)`,
# so adding a non-boolean here fails there rather than in a search result.
FIDELITY_TOGGLES = ("no_test_restart", "two_stage", "sfx_drum",
                    "wave_program", "pitch_seq", "wide_hard_restart",
                    "max_hard_restart")


def _redundant_combination(extra: dict) -> bool:
    """True where this combination is byte-identical to one already walked.

    Skipping such a combination cannot change what the search selects: the
    conversion it would score is the same file, so `fidelity_better` would see
    the same numbers, and the surviving twin is still visited.

    ONE PAIR QUALIFIES, and it is measured rather than reasoned from the
    option names. `--wide-hard-restart` widens the gate-off window from half
    the row to two thirds; `--max-hard-restart` takes the player's own limit
    instead, which supersedes the width outright. Byte-hashed at v0.5.429 with
    `max_hard_restart` FORCED ON across the corpus, `wide_hard_restart`
    changes the conversion on **0 of 83** files -- and with max forced OFF it
    changes **36 of 83**, which is what says the toggle is worth having at all
    and this prune is not merely deleting a dead option.

    Worth a quarter of the walk: seven booleans are 127 combinations, and half
    of those set `max_hard_restart`, half of which also set
    `wide_hard_restart`. That is 32 conversions, packs and traces a song that
    cannot affect the outcome.

    **This is the only safe shape for a prune here.** A combination may be
    skipped when a combination the walk still visits produces the SAME BYTES;
    it may never be skipped because an option looks unlikely to help, because
    `fidelity_better` is not a total order and the greedy path's outcome
    depends on what it sees. A prune justified on plausibility rather than on
    byte-identity is a silent change to the search result -- see the v0.5.426
    claim that the hard-restart axes are dead under `no_hard_restart`, which
    was generalised from one file and is false on 15 and 14 of them.
    """
    return bool(extra.get("max_hard_restart") and extra.get("wide_hard_restart"))
# `hard_restart_frames` is an INT and cannot join the product above: adding one
# more boolean doubles 127 combinations, and adding a four-valued axis would
# quadruple it. So it is searched in a SECOND PASS over whichever combination
# the boolean walk selected -- four extra candidates a song rather than four
# times as many, which is the difference between minutes and hours.
#
# The values are the ones a player can plausibly hold the gate off for. 2 is
# the built-in default and is the reference the pass measures against, so it is
# not in the list. The upper end is bounded for free: `_hard_restart_ticks`
# clamps the emitted gatetimer by the row length (half the row, or two thirds
# under `--wide-hard-restart`), because gplay.c:334 STOPS THE SONG when the
# gatetimer reaches the channel's tick. So a value too large for a file is
# clamped rather than fatal, and the search cannot break a song by trying one.
#
# It is searched at all because 5_Title_Tunes measured 4 by hand -- its player
# releases for a uniform 4 frames where the constant asks for 2 -- and took
# `gate` 0.4996 -> 0.7494 with melody, seq, pitch and wave every one unchanged.
# That was a hand measurement written into presets.json because nothing could
# find it; this is what finds it.
HARD_RESTART_SEARCH = (3, 4, 5)
# The toggles that raise the bound the frame count is capped by. Kept
# beside the values because the pair is the unit that means anything:
# `_hard_restart_ticks` computes `min(want, bound)`, so a larger `want`
# with the default bound is exactly the same emitted gatetimer.
HARD_RESTART_ENABLERS = ("max_hard_restart", "wide_hard_restart")

CARRIED_PER_SONG = tuple(FIDELITY_TOGGLES) + tuple(
    k for k in sorted(EXCLUDED_FROM_ALWAYS) if k not in FIDELITY_TOGGLES)
# Seven toggles is 127 combinations a song, each a convert, a pack and two
# traces -- about 30 minutes over the corpus, measured.
# `wide_hard_restart` was refused at v0.5.276 as a sixth toggle that "would
# double a four-hour search"; the search is 8 minutes (timed twice, v0.5.301),
# so the cost argument was never real. It raises the hard restart's row bound
# from `row // 2` to `2 * row // 3` -- worth 1.6pp of mean gate over the corpus
# and the value at which Saboteur II's melody falls 98% -> 67%, which is a
# per-song question by construction and the reason `keeps_notes` guards it.
# `pitch_seq` earned its place by being invisible to every other criterion here:
# it strikes no new notes and sounds no new register, so only the oscillation
# term can recommend it. See fidelity_better.
#
# Two files that DETECT it were measured and refused, and the refusals have
# different shapes -- see `food-feud-and-mega-apocalypse-now-detect-pitch-seq-
# and-nobody-has-measured-enabling-it` at runs.jsonl line 322 for the full
# trace. Re-taken over presets.json's 89 songs (0 conversion errors),
# `pitch_seq` is DETECTED on 36, moves the bytes of 29 when forced, and is
# ADOPTED on 12.
#
# **Food_Feud refuses on `vib` (`reversal_ratio`) -- the only column that
# moves, at either window, and it moves AWAY from 1 in log space** (compare a
# ratio in log space, per the rule above): at `-t 60` 1.1535 -> 2.3201
# (|log| 0.1428 -> 0.8416), at `-t 180` 1.2336 -> 2.0054 (|log| 0.2100 ->
# 0.6959). The mechanism: our reversals roughly DOUBLE (962 -> 1935 at 60 s,
# 2957 -> 4807 at 180 s) against an original making ~834 and ~2397 -- the file
# was already over-reversing and `pitch_seq` doubles the surplus. Melody is
# exact either way (2524 attacks against the original's 2524), so nothing is
# gained anywhere.
#
# **Mega_Apocalypse refuses on `melody`, `sequence` and `pitch`, and the
# report's own 60 s window cannot see the trade at all.** At `-t 60` every
# numeric column is identical between arms while `output_sha` differs
# (bd7f58a303c4 -> b66d310d6b6f) -- the change reaches the file and nothing
# registers it. At `-t 180` it is not flat: `vib` goes 0.8132 -> 0.9984
# (|log| 0.2069 -> 0.0016, near-exact -- our reversals 3626 -> 4452 against
# the original's ~4459), bought with `melody` 91.46 -> 87.02%, `sequence`
# 92.23 -> 88.10% and `pitch_jaccard` 77.55 -> 64.81%. The file emits one
# subtune, so the change living in an untraced subtune is excluded by
# construction -- this is the window alone. `fidelity_better` refuses it with
# all seven toggles free regardless of window (at 60 s because nothing
# improves, at 180 s because melody falls), which is the per-song trade this
# file's docstring elsewhere says the search cannot select.

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


def carried_entry(entry: dict) -> dict:
    """What a regeneration must carry forward from a song's previous entry.

    Membership, NOT truthiness. This read `if entry.get(k)` until v0.5.413,
    which silently dropped an explicit `false` -- so an option could be
    ADOPTED in the artefact and never REFUSED in it, and "measured and
    rejected" was byte-identical to "never tried" for all sixteen
    CARRIED_PER_SONG options.

    That is not a cosmetic gap. `--regrid` is hand-adopted on twelve files
    because `fidelity_better` cannot select it (see the `regrid` entry in
    EXCLUDED_FROM_ALWAYS), so the artefact is the only record of any decision
    about it -- and it could only ever record the yeses. Powerplay Hockey was
    measured at v0.5.412 (melody -2.87pp against drift -7.90 -> +1.12) and
    DECIDED against, and that decision had nowhere to live: writing
    `regrid: false` would have survived exactly one commit and then vanished
    on the next regeneration, which is worse than leaving it absent because it
    reads as measured while it lasts.

    Safe to widen because nothing currently relies on the drop: checked at
    v0.5.413, ZERO of the CARRIED_PER_SONG keys present in presets.json carry
    a falsy value (two_stage 38, max_hard_restart 26, wave_program 21,
    hard_restart_frames 17, no_test_restart 12, pitch_seq 12, regrid 12,
    rest_envelope_silence 4, real_firstwave_instruments 2, pulse_phase 1, all
    truthy), so the change carries nothing new today and only becomes visible
    the first time somebody records a refusal.

    An explicit `false` is also inert in conversion: `_preset_opts` already
    passes False for an absent key, so `regrid: false` and no `regrid` produce
    the same bytes. Proven by corpus byte-hash rather than assumed.
    """
    return {k: entry[k] for k in CARRIED_PER_SONG if k in entry}


def fidelity_better(cand: tuple, ref: tuple,
                    margin: float = FIDELITY_MARGIN) -> bool:
    """Is `cand` a better-playing (melody, sequence, attacks, noise) than `ref`?

    Seven one-sided questions and two vetoes. Any one question is enough to
    accept, which is a sound acceptance rule and an unsound *replacement*
    rule -- see `gave_back`, and CLAUDE.md.

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

    # **The attack guard is two-sided against the ORIGINAL's count** (v0.5.413).
    # It read `cand[2] >= ref[2]` -- ours against ours, no margin -- and gated
    # every acceptance term below. That is the anti-gaming clause and it has to
    # stay: a conversion with fewer notes scores better on `wave` and `gate` for
    # having fewer events to disagree about (section 7.eee). But ours-against-
    # ours cannot tell "deleted three real notes" from "stopped inventing
    # three", and the second is an improvement it was refusing outright.
    # Measured on the files `--regrid` helps: Arcade_Classics 375 -> 372 against
    # the original's 372, Sigma_Seven 417 -> 414/414, Wiz 446 -> 437/437,
    # Rikky 201 -> 196/197.
    #
    # The rule is CLOSER, not `>= orig`: Rikky's 196 undershoots 197 by one and
    # a `>=` form would refuse it while accepting the other three, which is a
    # threshold masquerading as a principle. Distance to the original's count is
    # the same shape as `_closer` above -- a statement that the quantity moved
    # toward its target, with no fitted number in it.
    #
    # A state built before this term existed carries no original count, and then
    # the old one-sided rule stands: an absent dimension must not recommend
    # anything, the same convention `osc`, `opens`, `holds` and `gates` use.
    def orig_attacks(state):
        return state[8] if len(state) > 8 else None

    oa = orig_attacks(cand)
    if oa is None:
        oa = orig_attacks(ref)
    if cand[2] >= ref[2]:
        attacks_ok = True                      # never fewer: unchanged
    elif oa is None:
        attacks_ok = False                     # no original to judge against
    else:
        attacks_ok = abs(cand[2] - oa) < abs(ref[2] - oa)

    keeps_notes = (cand[1] >= ref[1] - margin
                   and attacks_ok
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
    # **Moves the pitch oscillating at the original's rate.** `reversal_ratio` is
    # ours over theirs, so 1.0 is right and the distance to it is symmetric only
    # in log space -- 2.0x and 0.5x are the same size of wrong. Effect bit $10's
    # arpeggio takes the balloon song 0.17x -> 0.61x, and nothing else in this
    # function could see it: it strikes no new notes, sounds no new register and
    # leaves melody untouched. Guarded by `keeps_notes` like everything else,
    # which is what rejects it on the seven files where it costs melody.
    def osc(state):
        # A state built before this term existed carries no oscillation, and an
        # absent dimension must not recommend anything -- `_closer` reads None
        # as "not measurable".
        return state[4] if len(state) > 4 else None
    moves_oscillation = _closer(osc(cand), osc(ref), 1.0, margin)
    # **Moves the noise to the pitch the original sounds it at.** The frames may
    # already be there and be inaudible or wrong-coloured: the drum composition
    # of section 7.sss puts Pandora's 35 attack-pitch frames exactly where the
    # original's are, changing no count and no waveform. Medians, in log space,
    # for the same reason as above.
    moves_noise_pitch = _closer(cand[3][2] and cand[3][3] and
                                cand[3][2] / cand[3][3],
                                ref[3][2] and ref[3][3] and
                                ref[3][2] / ref[3][3], 1.0, margin)
    # **Opens its notes on the waveforms the original opens them on.** The
    # docstring above records that this function is deliberately not scored on
    # `wave`, because restoring a 1-4 frame transient moves `wave` the wrong
    # way even when the transient is right. That reasoning is sound and it left
    # `--two-stage` unselectable: the attack it restores strikes no new note,
    # sounds no new register and leaves `melody` untouched, so not one term
    # above could see it. 45 corpus files sound an attack transient at 109
    # instruments -- some 13,700 notes -- that the conversion holds flat, and
    # 42 of them have the option off.
    #
    # Graded per frame rather than per instrument (`onset_frame_agreement`, not
    # `onset_agreement`): Sigma Seven's $0FFD goes from no transient at all to
    # one a frame too long, which whole-shape equality scores as no change.
    # Guarded by `keeps_notes` like every other term.
    def opens(state):
        return state[5] if len(state) > 5 else None
    a, b = opens(cand), opens(ref)
    opens_right = a is not None and b is not None and a > b + margin

    # **Holds the note for as long as the original does.** `hold`
    # (fidelity.sound_run_agreement, v0.5.244) is the first term here that can
    # see note *length*, and it exists because nothing else could: the modal
    # per-file delta is -1 frame on 50 of 81 files, from GoatTracker fetching
    # the next note `gatetimer & $3f` ticks early and writing `firstwave` over
    # the previous note's last frame.
    #
    # It is an acceptance term and **not** a veto, and that asymmetry is the
    # measurement rather than caution. Forced on corpus-wide,
    # `--no-test-restart` -- the option this term can see -- gains 49 points of
    # `hold` and costs **21 points of melody on 68 files with none improving**,
    # because `firstwave` then puts a waveform on the attack frame and siddump
    # names the note by it. `keeps_notes` already refuses all 68. What is left
    # is the five files where `hold` rises and melody does not move at all --
    # Chicken Song, Delta, Tarzan, Wiz, Sanxion -- which the search declines
    # today only because nothing it scores can see the gain.
    #
    # Not added to `gave_back` for the reason that clause states about itself:
    # a new veto cost seven measured settings the last time one was widened,
    # and the conservative half of an asymmetric rule is the half that cannot
    # lose a setting already measured as better.
    def holds(state):
        return state[6] if len(state) > 6 else None

    # **And it may not be bought with the oscillation.** After_8 swapped
    # `pitch_seq` for `no_test_restart` on this term, gaining hold 0 -> 50% and
    # giving up an arpeggio ratio of 0.93 for 0.29 -- a near-perfect
    # oscillation for half a hold. `gave_back` deliberately does not watch that
    # ratio, for the reason stated above it, so `hold` has to decline the trade
    # itself.
    #
    # Mega_Apocalypse is this same trade from the other side, on `pitch_seq`
    # rather than `no_test_restart`, and it is refused there by name (`melody`,
    # `sequence`, `pitch`) rather than by a term that does not watch the ratio
    # -- see the `pitch_seq` note above `FIDELITY_MARGIN`.
    #
    # **The veto is sized, and the second attempt got that wrong too.**
    # `_closer`'s margin is a fraction of the *remaining* gap, so on a ratio
    # already far from 1 a small wobble clears it: Chicken Song's 0.32 -> 0.29
    # is 8.7% of a gap of 1.14 in log space and blocked a hold gain of
    # 0 -> 100%, where After_8's 0.93 -> 0.29 is the same absolute move against
    # a gap of 0.07. Both "worse"; only one is a change of *rate*.
    # `_oscillation_lost` asks whether the candidate ends up more than twice as
    # far from the original's rate as the reference was -- After_8 17x, Chicken
    # Song 1.09x -- which is a statement about audibility rather than a
    # threshold fitted to the corpus.
    #
    # **Melody is left to `keeps_notes`, and the first attempt got that wrong.**
    # Requiring melody not to fall *at all* blocked seven of the eight files
    # this term reaches, because their moves are thousandths -- Delta 1.000 ->
    # 0.996, Tarzan 0.988 -> 0.985, Sanxion 0.968 -> 0.966 -- against a hold
    # gain of 0 -> 100%. That is the noise floor of a difflib ratio, not a
    # cost, and a guard tuned to it measures the wrong thing.
    h_c, h_r = holds(cand), holds(ref)
    holds_right = (h_c is not None and h_r is not None and h_c > h_r + margin
                   and not _oscillation_lost(osc(cand), osc(ref)))
    # **And it must not give back what a previous winner gained.** The five
    # terms above are one-sided questions, so any of them is enough to accept;
    # the search then makes the accepted candidate the new reference and walks
    # on. That is a greedy path through 31 combinations and not a maximum, and
    # without this clause the path can walk *downhill*: IK+ accepted
    # `--wave-program` (noise 140 -> 1170 of the original's 1517, onset 0.45 ->
    # 0.75, melody unchanged) and then replaced it, sixteen combinations later,
    # with `--no-test-restart` -- which moves noise to 168, leaves onset at
    # 0.45, and wins only because 168 frames of noise happen to sit at a pitch
    # closer to the original's than 1170 do. The better setting was measured,
    # accepted, and thrown away.
    #
    # So a candidate must be no *worse* than the reference on the terms where
    # "worse" means the same thing at both sample sizes. That makes the
    # accepted chain monotone in those, which is what stops it running
    # downhill. It imposes no total order on the five -- a candidate that
    # trades one for another is simply not accepted, which is the honest
    # answer when the measurements disagree.
    #
    # **Two terms, not five, and the three left out are left out for a
    # measured reason.** The oscillation ratio and the noise *pitch* are both
    # estimated over the frames the setting itself creates: IK+ sounds 140
    # noise frames without `--wave-program` and 1170 with it, and the pitch of
    # 140 frames is not the same quantity as the pitch of 1170. Vetoing on
    # them rejected the very candidate this clause was written to protect --
    # better on noise, oscillation *and* onset, blocked by a pitch estimate
    # taken over a tenth of the sample -- and cost seven measured settings
    # across the corpus. It is the veto form of the trap CLAUDE.md states for
    # register agreements: a change that resizes the events a term scores
    # cannot be judged by that term alone.
    #
    # `onset` survives it because each side is read at its *own* attack frames
    # and scored per instrument, so it does not grow with the frames a setting
    # adds; and losing the noise outright is a fact, not an estimate.
    # **Ends the note where the original ends it.** `gate` (v0.5.270) is the
    # only column that reads $D404's gate bit: `wave` excludes it by
    # construction, `hold` counts frames with a waveform *selected*, `adsr`
    # and `tail` read the envelope pair. Until it existed, an option that only
    # opened and closed the gate was invisible to this whole function --
    # `--rest-keyoff` moved 19 files' bytes and one number on one file, and
    # had to be shipped on a hand-rolled probe.
    #
    # **The gaming vector is real and `keeps_notes` already closes it.** A
    # conversion with fewer notes has more gate-off frames and scores higher
    # for it, exactly as `wave` rises when attacks are deleted (section
    # 7.eee). The raw attack count in `keeps_notes` is what refuses that, and
    # it is the same guard that has protected every term here since the first.
    #
    # **Acceptance only, never a veto**, for the reason the clause below
    # states about the oscillation and the noise pitch: `gate` is scored over
    # the frames *either side* has the voice released, so a setting that adds
    # releases changes the denominator it is judged by. A term whose sample a
    # setting resizes cannot also be the thing that rejects it.
    def gates(state):
        return state[7] if len(state) > 7 else None

    g_c, g_r = gates(cand), gates(ref)
    gates_right = (g_c is not None and g_r is not None
                   and g_c > g_r + margin
                   and not _oscillation_lost(osc(cand), osc(ref)))

    # **Opens its notes on the spread of duty cycles the original opens them
    # on.** `pulse_phase` is ours over theirs and 1.0 is right, so the
    # distance to it is `_closer`'s log-space one, exactly as for the
    # oscillation ratio above. This is the first term in this function that
    # reads $D402/$D403 at all: the note at `pulse_phase` in `FIXED` records
    # that the criterion's whole input had no pulse term, measured at 64c795b,
    # and that this is why the search takes that option on 0 of the 6 files it
    # reaches. Guarded by `keeps_notes` like every other term, and acceptance
    # only -- never a veto -- for the reason the oscillation and noise-pitch
    # clauses give: a setting that changes WHICH notes sound changes the
    # attack frames this is sampled at, so a term whose sample the setting
    # resizes must not be the thing that rejects it.
    def phases(state):
        # An older saved state has nine elements and no phase; an absent
        # dimension must not recommend anything, the same convention `osc`,
        # `opens`, `holds` and `gates` use.
        return state[9] if len(state) > 9 else None
    moves_pulse_phase = _closer(phases(cand), phases(ref), 1.0, margin)

    def worse(c, r) -> bool:
        return c is not None and r is not None and c < r - margin

    gave_back = (worse(a, b)                                   # onset
                 # Losing the noise outright is the one regression a *ratio*
                 # cannot state: `_closer` reads 0 frames as "not measurable"
                 # and declines to compare it, so silencing a drum would slip
                 # through while winning on some other term.
                 or bool(ref[3][0] and not cand[3][0]))
    return keeps_notes and not gave_back and bool(
        plays_more or finds_noise or moves_oscillation
        or moves_noise_pitch or opens_right or holds_right or gates_right
        or moves_pulse_phase)


def _oscillation_lost(cand: float | None, ref: float | None,
                      factor: float = 2.0) -> bool:
    """Whether `cand`'s oscillation rate is a different rate from `ref`'s.

    Distance from 1 in log space, because a ratio is only symmetric there. The
    question is not "is it worse" -- every estimate wobbles -- but "is it
    *more than `factor` times* as far from the original's rate", which is a
    claim about what a listener would hear rather than a threshold fitted to
    the corpus. A reversal ratio of 0.93 becoming 0.29 is a different rate; one
    of 0.32 becoming 0.29 is the same absence of one, measured twice.

    Either side unmeasurable means no objection: a dimension that was not
    computed cannot veto a setting.
    """
    if not cand or not ref or cand <= 0 or ref <= 0:
        return False
    return abs(math.log(cand)) > factor * abs(math.log(ref))


def _closer(cand: float | None, ref: float | None, target: float,
            margin: float) -> bool:
    """Whether `cand` sits nearer `target` than `ref` does, in log space.

    A ratio's distance from 1 is only symmetric logarithmically -- 2.0 and 0.5
    are equally wrong, where `abs(r - 1)` calls one twice the other. `margin` is
    read as a fraction, so the move has to be worth at least that much of the
    remaining gap rather than any move at all.

    None on either side means the dimension was not measurable on that run, and
    an unmeasurable dimension cannot recommend a setting.
    """
    if not cand or not ref or cand <= 0 or ref <= 0 or target <= 0:
        return False
    want = math.log(target)
    return abs(math.log(cand) - want) < abs(math.log(ref) - want) - margin


def _inert_frames(sid_path, base: dict, out: dict) -> bool:
    """True when dropping `hard_restart_frames` changes not one byte.

    The same test `prune_inert` applies to the booleans, in the same currency:
    a setting whose removal leaves the conversion identical cannot have been
    what a measurement preferred. It happens here rather than inside
    `prune_inert` because that function walks a dict of flags it can toggle to
    False, and an int has no False.
    """
    import hashlib

    without = {k: v for k, v in out.items() if k != "hard_restart_frames"}
    try:
        a = convert(str(sid_path), log=lambda m: None, **base, **FIXED, **out)
        b = convert(str(sid_path), log=lambda m: None, **base, **FIXED, **without)
    except Exception:                                # noqa: BLE001
        return False                                 # cannot prove it inert
    return hashlib.sha1(a).hexdigest() == hashlib.sha1(b).hexdigest()


def prune_inert(sid_path: Path, base: dict, chosen: dict) -> dict:
    """`chosen` without the flags that change none of the converted bytes.

    A preset entry is a record of a measured decision, and a flag that alters
    nothing was not one -- no measurement can have preferred it, because both
    settings produced the identical file. See `tune_by_fidelity` for how one
    gets in.

    Order-dependent only where two flags are individually redundant because
    the other is present (an OR of two paths onto one emission): the first is
    dropped and the second kept, which records one decision rather than two.
    """
    if not chosen:
        return chosen
    out = dict(chosen)
    full = convert(str(sid_path), log=lambda m: None, **base, **FIXED, **out)
    for k in sorted(out):
        without = dict(out, **{k: False})
        if convert(str(sid_path), log=lambda m: None,
                   **base, **FIXED, **without) == full:
            del out[k]
    return out


def _hard_restart_grid_inert(sid_path, base: dict, out: dict) -> bool:
    """True when NO point of the nine-point hard-restart grid moves a byte.

    The pass below costs one convert + one gt2reloc pack + one siddump trace
    per point, nine points a song, run after the 127-combination walk. This
    costs nine CONVERSIONS and no emulation at all, and where it returns True
    the pass provably cannot change the outcome: `fidelity_better` scores
    traces, a trace is a function of the packed bytes, and the packed bytes
    are a function of the converted ones -- so nine conversions identical to
    the reference score identically to it, and an acceptance rule that
    requires a strict improvement accepts none of them.

    That is the whole argument for skipping, and it is why the check is on
    BYTES rather than on scores: two settings that convert identically cannot
    be told apart by any measurement downstream, which is the same reasoning
    `_inert_frames` and `prune_inert` already use in the other direction.

    Measured over the corpus at v0.5.451: this skips the pass on **26 of the
    89** converting files -- 234 of the 801 grid points the search would
    otherwise convert, pack and trace. Of the six files that joined the corpus
    at v0.5.450, three are inert (Lakers_vs_Celtics, Pacific_Coast, Radio_ACE)
    and three are live.

    **THAT IS NOT THE 36-OF-83 THE TASK CARRIED, AND THE GAP IS THE BASE.**
    The v0.5.435 census asked whether the grid moves a file against its
    SHIPPED PRESET; this asks whether it moves a file against `out`, the
    boolean winner the walk has just selected, which is what the pass it
    guards actually runs from. Those are different questions and the stricter
    one is the one that licenses a skip -- a grid that is inert against the
    defaults may still be live against a winner carrying `two_stage` or
    `max_hard_restart`. So 26 is not a shrunken 36; it is a different
    measurement, and the corpus growing from 83 to 89 is not what moved it.

    Returns False on any exception, which is the honest answer: a file whose
    conversion raises somewhere in the grid has not been proven inert, and the
    pass must run so that `play()` can decline the combination itself.
    """
    import hashlib                                    # noqa: PLC0415

    def sha(extra: dict) -> str:
        blob = convert(str(sid_path), log=lambda m: None,
                       **base, **FIXED, **extra)
        return hashlib.sha1(blob).hexdigest()

    try:
        ref = sha(out)
        for frames in HARD_RESTART_SEARCH:
            for enabler in (None, *HARD_RESTART_ENABLERS):
                extra = dict(out, hard_restart_frames=frames)
                if enabler is not None:
                    extra[enabler] = True
                if sha(extra) != ref:
                    return False
    except Exception:                                 # noqa: BLE001
        return False
    return True


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
    # **The original's own tuning, as `fidelity._measure` traces it.** Four
    # corpus files carry a frequency table tuned off the semitone grid, and
    # siddump names their notes against its own table unless told otherwise --
    # so tracing them at 0 renames every note and collapses `melody`. This
    # hardcoded a 0 until v0.5.223, which is why the search selected a setting
    # for One_on_One_Jordan_vs_Bird "at melody 5%": the 5% was the harness.
    ft = find_freq_table(load_sid(str(sid_path)))
    cal = F.calibration(ft.detune) if ft and abs(ft.detune) > 0.2 else 0
    orig = F.run_siddump(local, seconds, sub, siddump, cal)
    # **And our subtune numbering need not match the original's.** A subtune
    # whose orderlist exceeds Goattracker's limit costs itself and every later
    # one shifts down, so the original's subtune N can be our N-1. `_measure`
    # searches a window of ours and keeps the best match (`--search-subtunes`,
    # default 3); this compared N against N and scored two different pieces of
    # music -- Action_Biker reads 6% here and 100% there.
    #
    # Found **once**, on the reference conversion, and reused for every
    # candidate: the alternative is three traces per candidate rather than
    # one, and the toggles this searches change no orderlist length. That is
    # an assumption, and it is the reason the window is re-derived per file
    # rather than cached across the corpus.
    ours_sub = sub

    def _dump(packed, st):
        return F.run_siddump(packed, seconds, st, siddump, calls=multiplier)

    def play(extra: dict):
        # **A combination that will not convert is one unplayable candidate,
        # not a failed song.** Letting the exception out abandoned the whole
        # 31-combination walk and fell back to the structural defaults, which
        # silently *dropped* a setting the previous search had measured:
        # W_A_R lost `two_stage` that way, because 4 of its combinations
        # overflow Goattracker's 255-entry wavetable at `-S4` (a drum record
        # occupies six entries above `-S1` and only the sweep is checked
        # against the budget -- a separate defect, recorded rather than fixed
        # here because the fix relays out every multispeed file's table).
        # `pack_sid` returning None is already treated exactly this way.
        try:
            blob = convert(str(sid_path), log=lambda m: None,
                           **base, **FIXED, **extra)
        except Exception as exc:                     # noqa: BLE001
            on = ' '.join(sorted(k for k, v in extra.items() if v))
            log(f"    {sid_path.name}: {on or 'default'} will not convert "
                f"({type(exc).__name__}), skipped")
            return None
        blob, _ = F.legalise_restarts(blob)
        packed = F.pack_sid(blob, workdir, gt2reloc, multiplier)
        if packed is None:
            return None
        dump = _dump(packed, ours_sub)
        got = F.compare(orig, dump)
        if got["melody"] is None or got["sequence"] is None:
            return None
        nf = seconds * 50
        wv = F.wave_compare(orig, dump, nframes=nf,
                            lag=F.startup_lag(orig, dump)[0])
        pm = F.pitch_motion_compare(orig, dump, nf)
        return (got["melody"], got["sequence"],
                sum(len(v.attacks) for v in dump),
                (wv["our_noise_frames"], wv["orig_noise_frames"],
                 _noise_pitch(dump, nf), _noise_pitch(orig, nf)),
                pm.get("reversal_ratio"),
                F.onset_agreement(orig, dump, nf)["onset_frame_agreement"],
                F.sound_run_agreement(orig, dump, nf)["sound_run_agreement"],
                F.gate_compare(orig, dump, nf,
                               lag=F.startup_lag(orig, dump)[0])["gate"],
                # The ORIGINAL's attack count, so `keeps_notes` can tell a
                # deletion from a correction. It was always to hand here and
                # never passed; see that guard for what its absence cost.
                sum(len(v.attacks) for v in orig),
                # **The tenth: a PULSE register, which nothing above reads.**
                # Elements 0-8 are melody, sequence, our attacks, the noise
                # 4-tuple, `reversal_ratio`, `onset_frame_agreement`,
                # `sound_run_agreement`, `gate` and the original's attacks --
                # and not one touches $D402/$D403, which is why every
                # pulse-shaping option has had to be adopted by hand. `pphase`
                # rather than `pspan`: `pspan` is the WIDTH of the band a
                # sweep covers and two sweeps entered at different points
                # score alike, while `pphase` is how many distinct duty cycles
                # a note OPENS on, which is the deficit `_pulse_tri_program`
                # documents and the one `pulse_phase` exists to fix.
                F.pulse_compare(orig, dump, nf).get("pulse_phase"))

    # Fix `ours_sub` before any scoring, on the default conversion, by the same
    # rule `_measure` uses: the window is the traced subtune and one either
    # side, and the best `melody` wins. Ties keep `sub`, so a file whose
    # numbering does line up is untouched.
    probe = convert(str(sid_path), log=lambda m: None, **base, **FIXED)
    probe, _ = F.legalise_restarts(probe)
    packed = F.pack_sid(probe, workdir, gt2reloc, multiplier)
    if packed is not None:
        best = None
        for st in (sub, sub - 1, sub + 1):
            if st < 0:
                continue
            got = F.compare(orig, _dump(packed, st))
            if got["melody"] is not None and (best is None or got["melody"] > best):
                best, ours_sub = got["melody"], st

    ref = play({})
    if ref is None:
        return {}
    out: dict = {}
    for flags in itertools.product((False, True), repeat=len(FIDELITY_TOGGLES)):
        if not any(flags):
            continue
        extra = dict(zip(FIDELITY_TOGGLES, flags))
        if _redundant_combination(extra):
            continue
        cand = play(extra)
        if cand is None:
            continue
        if fidelity_better(cand, ref):
            ref, out = cand, {k: v for k, v in extra.items() if v}
    # **Drop any flag the winning combination did not actually use.**
    # `fidelity_better` is not a total order -- each of its terms can improve
    # while another degrades -- so this walk is a greedy path through the 31
    # combinations rather than a maximum, and where it stops depends on the
    # iteration order. That is a property of scoring several dimensions at
    # once and is not fixed here. What *is* fixed is the consequence: a
    # combination can win carrying a flag that changes nothing, and the entry
    # then records a decision that was never measured. Mega Apocalypse
    # selected `two_stage sfx_drum wave_program` and produced byte-identical
    # output without `two_stage`, so the flag was dropped.
    #
    # **That example expired in v0.5.253, and it is worth saying why.** The
    # flag was inert because detection missed the block -- this player spells
    # it with its per-voice cells in zero page -- not because the walk had
    # picked up a passenger. Read the right way round, `prune_inert` was
    # reporting a detection gap: a flag the search keeps selecting and the
    # bytes cannot tell from its default is either noise or something unread,
    # and it is worth checking which before assuming the first.
    #
    # Tested by the bytes rather than by re-scoring: a flag whose removal
    # leaves the conversion identical cannot have been what any measurement
    # preferred. One conversion per selected flag, no traces.
    out = prune_inert(sid_path, base, out)

    # THE INTEGER PASS. Run against the boolean winner rather than against the
    # default, because the two interact: `hard_restart_frames` raises `want`
    # and `--wide-hard-restart`/`--max-hard-restart` raise the BOUND that caps
    # it, so a frame count is worth nothing on a file whose bound is already
    # the binding constraint. Measuring it after the toggles have settled is
    # what lets `fidelity_better` see the pair.
    #
    # `ref` is already the winning candidate, so an accepted value has beaten
    # the same combination at the default 2 -- not merely beaten the defaults.
    # SEARCHED JOINTLY WITH THE TOGGLES THAT RAISE ITS BOUND, because each is
    # worthless without the other and a greedy any-one-improving walk cannot
    # reach a pair.
    #
    # `hard_restart_frames` raises `want`; `--max-hard-restart` and
    # `--wide-hard-restart` raise the BOUND that caps it. On 5_Title_Tunes
    # neither alone changes ONE BYTE -- `max_hard_restart` on its own scores an
    # identical tuple, so the boolean walk never accepts it, and the frame
    # count against a selection without it is clamped straight back. Together
    # they are worth `gate` 50.0% -> 74.9% with melody, sequence and the attack
    # count unmoved. That value had to be hand-measured into presets.json
    # because nothing here could find it, and the reason was never the
    # criterion: `gates_right` has read this since v0.5.271.
    #
    # And `prune_inert` would finish the job if the pair ever were selected by
    # accident: it drops a flag whose removal leaves the bytes identical, which
    # is right for a passenger and wrong for an ENABLER. It is safe here only
    # because it re-converts against the whole selection -- with the frame
    # count present, removing the bound-raiser does move bytes, so it is kept.
    #
    # The cost is `len(HARD_RESTART_SEARCH) * (1 + len(HARD_RESTART_ENABLERS))`
    # conversions a song, run once after the 127-combination walk rather than
    # inside it.
    # SKIP THE WHOLE GRID where not one of its nine points moves a byte. The
    # axis is live corpus-wide -- 47 of 83 files responded to it when it was
    # censused -- but it is dead on about half of them individually, and on
    # those the nine traces below can only reproduce the reference. See
    # `_hard_restart_grid_inert` for why identical bytes make the pass
    # provably unable to choose.
    #
    # Spelled as an empty GRID rather than an `else:` around the loop, so that
    # every line of the pass below keeps the indentation it had -- a wrapper
    # that re-indents forty lines makes the diff unreadable and hides whether
    # anything else changed with it.
    grid = () if _hard_restart_grid_inert(sid_path, base, out) else HARD_RESTART_SEARCH
    if not grid:
        log(f"    {sid_path.name}: hard-restart grid inert, sub-search skipped")
    for frames in grid:
        for enabler in (None, *HARD_RESTART_ENABLERS):
            extra = dict(out, hard_restart_frames=frames)
            if enabler is not None:
                extra[enabler] = True
            cand = play(extra)
            if cand is None:
                continue
            if fidelity_better(cand, ref):
                ref, out = cand, extra
    # `prune_inert` walks the booleans it was given and would not know what to
    # do with an int, so the frame count is checked here in the same currency:
    # a value whose removal leaves the conversion byte-identical was never what
    # any measurement preferred, and recording it would put an unmeasured
    # decision in the artefact.
    if out.get("hard_restart_frames") and _inert_frames(sid_path, base, out):
        out.pop("hard_restart_frames")

    if out:
        log(f"    {sid_path.name}: {' '.join(sorted(out))} "
            f"(melody {ref[0]:.0%})")
    return out


def build_parser() -> argparse.ArgumentParser:
    """The CLI, separately so a test can read its defaults.

    `-t` is one of them: the search's window has to be the window the report is
    published at, and it silently was not for forty versions.
    """
    parser = argparse.ArgumentParser(prog="presets")
    parser.add_argument("sid_dir", nargs="?",
                        help="directory of .sid files (searched recursively); "
                             "omitted only with --merge")
    parser.add_argument("-o", "--output", default="presets.json")
    parser.add_argument(
        "--fidelity", action="store_true",
        help="also search the options that change no structure, by playing "
             f"both settings and comparing: {', '.join(FIDELITY_TOGGLES)}. "
             "Needs siddump and gt2reloc, and traces two emulations per "
             "setting per song, so it is off by default -- the structural "
             "search is what every commit re-runs")
    parser.add_argument(
        "-t", "--seconds", type=int, default=180,
        help="trace length for --fidelity (default 180 since v0.5.459, the "
             "window FIDELITY.md is generated at). It was 60 until the "
             "decision was measured rather than argued: the same seven-toggle "
             "search at 60 s and at 180 s DECIDES 17 of 89 songs differently, "
             "so the short window was not merely reporting less, it was "
             "choosing differently. See CLAUDE.md")
    parser.add_argument(
        "--no-carry", action="store_true",
        help="do not carry forward the --fidelity settings already recorded in "
             "the output file. Without --fidelity they are carried by default, "
             "because the structural search cannot see them and dropping them "
             "silently would turn a measured decision into an absent one on "
             "the next routine regeneration")
    parser.add_argument(
        "--carry-from", default=None, metavar="FILE",
        help="carry the per-song decisions this run cannot re-derive from FILE "
             "rather than from the output file. A SHARDED run needs this: its "
             "output file does not exist yet, so there is nothing to carry "
             "from, and six shards merged at v0.5.457 dropped 30 measured "
             "settings -- every --regrid adoption among them -- while looking "
             "complete. Pass the shipped presets.json"),
    parser.add_argument(
        "--shard", default=None, metavar="I/N",
        help="search only every Nth song, starting at I (0-based), so a "
             "corpus search can be split across processes. Each song's walk "
             "is independent of every other's, which is what makes this "
             "sound; the shards are disjoint by construction and --merge "
             "refuses overlapping ones. TIMED at v0.5.455 with a stopwatch "
             "rather than extrapolated: the 7-toggle (127-combination) corpus "
             "search is 1521 s -- 25m21s over 89 songs, 17.1 s a song -- so "
             "six shards is the difference between about 25 minutes and about "
             "5. The figure here used to read 'about a minute a song ... 80 "
             "minutes', which is 3.2x the truth")
    parser.add_argument(
        "--merge", nargs="+", metavar="FILE",
        help="combine sharded runs into one presets file: reads each FILE, "
             "checks they agree on `always` and `criteria`, and writes the "
             "union of their songs to -o. Refuses if two shards claim the "
             "same song, which is the only way a split can go wrong quietly")
    parser.add_argument("--siddump", default=None)
    parser.add_argument("--gt2reloc", default=None)
    return parser


def merge_shards(paths, out_path) -> int:
    """Union the `songs` of several sharded runs into one presets file."""
    docs = []
    for path in paths:
        with open(path, encoding="utf-8") as fh:
            docs.append(json.load(fh))
    if not docs:
        print("--merge: nothing to merge", file=sys.stderr)
        return 2
    head = docs[0]
    for other in docs[1:]:
        for key in ("always", "criteria"):
            if other.get(key) != head.get(key):
                print(f"--merge: shards disagree on `{key}` -- they were not "
                      f"produced by one version", file=sys.stderr)
                return 2
    songs: dict[str, dict] = {}
    for path, doc in zip(paths, docs):
        for name, entry in doc.get("songs", {}).items():
            if name in songs:
                print(f"--merge: {name} appears in two shards ({path}) -- "
                      f"the split was not disjoint", file=sys.stderr)
                return 2
            songs[name] = entry
    out = dict(head)
    out["songs"] = dict(sorted(songs.items(), key=lambda kv: kv[0].lower()))
    with open(out_path, "w", encoding="utf-8") as fh:
        json.dump(out, fh, indent=2)
        fh.write("\n")
    print(f"merged {len(paths)} shard(s), {len(songs)} song(s) -> {out_path}")
    return 0


def main(argv=None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)

    if args.merge:
        return merge_shards(args.merge, args.output)
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
    # Whether -o actually named a readable previous file. Distinct from
    # `carried` being empty: a real previous file can legitimately carry
    # nothing (no song had a per-song decision to keep), where a MISSING
    # or unreadable one means there was never anything to carry FROM at
    # all -- and those two silences must not print the same way. See the
    # warning below, near `kept`.
    carry_source_readable = False
    # Read whatever the output file already records, whether or not this run
    # searches: without --fidelity it is what gets carried forward, and *with*
    # it, it is what a song whose search fails falls back to. Falling back to
    # the structural defaults instead is indistinguishable from a measured
    # decision to use them -- the same reasoning that put the carry here.
    carry_source = args.carry_from or args.output
    if not args.no_carry:
        try:
            prev = json.loads(Path(carry_source).read_text(encoding="utf-8"))
            carry_source_readable = True
            for name, e in (prev.get("songs") or {}).items():
                # FIDELITY_TOGGLES is not the whole set of per-song
                # decisions. `hard_restart_frames` is an INT measured by
                # hand -- the search walks booleans and cannot express
                # it -- so carrying only the toggles dropped
                # 5_Title_Tunes' measured 4 on every regeneration,
                # silently returning it to the built-in 2 and its gate
                # to 50%. Anything the artefact already records that
                # this run cannot re-derive is carried.
                keep = carried_entry(e)
                if keep:
                    carried[name] = keep
        except (OSError, ValueError):
            pass

    # A SHARDED run whose carry source is unreadable would write a shard
    # that looks complete and is not -- the failure this flag was added for.
    # Refused rather than warned, because `--merge` cannot tell afterwards:
    # a dropped setting and a setting that was never measured are the same
    # absence in the merged file.
    if args.shard and not args.no_carry and not carry_source_readable:
        print(f"--shard with no readable carry source ({carry_source}): a "
              "shard's output file does not exist yet, so every per-song "
              "decision this run cannot re-derive would be DROPPED from the "
              "merged file -- all --regrid adoptions, rest_envelope_silence, "
              "pulse_phase, real_firstwave_instruments, force_park and "
              "initial_instrument. Pass --carry-from <shipped presets.json>, "
              "or --no-carry if you really mean to re-decide from nothing.",
              file=sys.stderr)
        return 2

    songs: dict[str, dict] = {}
    paths = sorted(sid_dir.rglob("*.sid"), key=lambda p: p.name.lower())
    if args.shard:
        index, count = (int(x) for x in args.shard.split("/"))
        if not 0 <= index < count:
            print(f"--shard {args.shard}: I must be in 0..N-1", file=sys.stderr)
            return 2
        # Sliced off the same sorted list every shard builds, so the union of
        # 0/N .. N-1/N is exactly the unsharded corpus and no two overlap.
        paths = paths[index::count]
        print(f"shard {index}/{count}: {len(paths)} song(s)", file=sys.stderr)
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
                    # A song the tools cannot play keeps whatever the last
                    # search measured for it, and says so. Dropping to the
                    # structural defaults is indistinguishable from a measured
                    # decision to use them, and it is a *loss* of one: W_A_R
                    # shed `two_stage` to a crash in one combination.
                    keep = carried.get(path.name)
                    if keep:
                        found.update(keep)
                    print(f"    {path.name}: fidelity search failed "
                          f"({type(exc).__name__}), "
                          + (f"keeping {' '.join(sorted(keep))} from the "
                             "previous run" if keep else "no previous setting "
                             "to keep"),
                          file=sys.stderr)
            elif path.name in carried:
                found.update(carried[path.name])
            # AND WITH --fidelity TOO, for the options the search CANNOT
            # re-derive. The `elif` above carries only on the no-search path,
            # so a SUCCESSFUL search silently dropped every per-song decision
            # outside FIDELITY_TOGGLES: measured over the corpus, 19 of them --
            # `regrid` on all 12 files that carry it, `rest_envelope_silence`
            # on 4, `real_firstwave_instruments` on 2 (one of them
            # human-approved) and `pulse_phase` on 1.
            #
            # This is the FOURTH sighting of a regeneration deleting a measured
            # decision -- hard_restart_frames at v0.5.389, five
            # rest_envelope_silence entries lost for 25 versions,
            # real_firstwave_instruments at v0.5.398, and now the whole
            # non-searchable set whenever anyone runs --fidelity. Each earlier
            # fix widened what is CARRIED; none noticed that the carry is
            # skipped entirely on the path that re-decides the most.
            #
            # The rule, stated so the next option does not need a fifth fix:
            # carry anything the run cannot RE-DERIVE, on every path. The
            # search derives FIDELITY_TOGGLES and, since the frame pass,
            # `hard_restart_frames`; everything else in CARRIED_PER_SONG is a
            # hand measurement and the artefact is its only copy.
            if args.fidelity:
                keep = {k: v for k, v in (carried.get(path.name) or {}).items()
                        if k not in FIDELITY_TOGGLES
                        and k != "hard_restart_frames"}
                if keep:
                    found.update(keep)
            for key in FIDELITY_VETOED.get(path.name, ()):
                if found.pop(key, None):
                    print(f"    {path.name}: {key} vetoed (see FIDELITY_VETOED)",
                          file=sys.stderr)
            for key in FIDELITY_CONFIRMED.get(path.name, ()):
                if found is not None and not found.get(key):
                    found[key] = True
                    print(f"    {path.name}: {key} from "
                          "FIDELITY_CONFIRMED", file=sys.stderr)
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
                   # The global-triangle player's per-note length gate, as a
                   # pattern command instead of a vibdelay -- the only form
                   # that expresses it, since vibdelay is per instrument. A
                   # no-op outside that dialect (25 files) and outside gts5.
                   # Fixed rather than searched: measured over 2487 notes it
                   # beats the instrument setting on both axes at once, 92.1%
                   # against 85.7% note agreement with the vibrato onset
                   # median exact instead of 10 frames late, and no dimension
                   # of FIDELITY.md scores an oscillation onset.
                   "vibrato_command": FIXED["vibrato_command"],
                   # Players that end a note by zeroing both envelope
                   # registers never let the record's release nibble sound,
                   # so copying it into the instrument makes audible what the
                   # original silences. Gated on the routine being found (33
                   # files), a no-op elsewhere. Fixed rather than searched:
                   # the `tail` column goes 27.6% to 99.2% over the 30
                   # measurable files, better on 27 and worse on none, with
                   # melody unchanged.
                   "cut_release": FIXED["cut_release"],
                   # Status bit 5 is the players' tie flag: the gate is not
                   # closed at that note's end, so the next note is legato.
                   # Emitted as CMD_TONEPORTA 0 on the landing row. 64 classic
                   # files carry tied events. Fixed rather than searched:
                   # median retrigger ratio 1.008 -> 0.999 and mean melody
                   # 82.3% -> 84.1%, 19 files better and 5 worse.
                   "tie": FIXED["tie"],
                   # Bit $02's per-voice attack. Fixed on the same terms as
                   # `effects` above rather than because it was measured
                   # corpus-wide: its signature matches one file, forcing it
                   # on every file moves that file's bytes and nobody else's,
                   # and there it takes `onset` 40% -> 80% with melody, seq,
                   # noise and the rest unmoved. A search would spend 82 songs
                   # proving it changes nothing. (This used to cite the cost of
                   # a sixth --fidelity toggle instead; that cost was never
                   # timed and is 8 minutes, not four hours -- see the module
                   # docstring.)
                   "voice_two_stage": FIXED["voice_two_stage"],
                   # The bit-6 rest, in the 21 players that silence on it
                   # rather than holding. Fixed rather than searched, on the
                   # dimension built to see it: `gate` moves on 12 files and
                   # **upward on all 12** -- BMX Kidz 4% -> 85%, Auf
                   # Wiedersehen Monty 18% -> 45%, Shockway Rider 52% -> 75%
                   # -- with every other column flat but 3 points of `pitch`
                   # on Auf Wiedersehen Monty. Gated on the player's own
                   # branch, so a no-op in the 40 that hold.
                   "rest_keyoff": FIXED["rest_keyoff"],
                   # The packing step of the conversion. Recorded here rather
                   # than searched: it takes no per-song decision, it just
                   # turns the .sng into something a SID player can play.
                   "gt2reloc": True},
        "criteria": "most playable subtunes, then most rows, then smallest file",
        "songs": songs,
    }
    # THE BLOCK ABOVE IS HAND-LISTED AND THIS IS WHY IT CANNOT STAY THAT WAY.
    # `presets.py` CONVERTS with FIXED but writes the `always` block key by
    # key, so an option added to FIXED changed every recorded `bytes` and
    # `rows` while never reaching the block `fidelity._preset_opts` reads.
    # `silent_park` did exactly that: the artefact described a conversion its
    # own options could not reproduce. Anything in FIXED and not deliberately
    # excluded is added here, so the two cannot drift again. The hand-written
    # entries keep their comments, which are the reasoning for each.
    for _key, _value in FIXED.items():
        if _key in EXCLUDED_FROM_ALWAYS:
            continue
        doc["always"].setdefault(_ALWAYS_NAME.get(_key, _key), _value)
    Path(args.output).write_text(json.dumps(doc, indent=2) + "\n", encoding="utf-8")
    print(f"{len(songs)}/{len(paths)} convertible -> {args.output}", file=sys.stderr)
    # Only a run that did *not* search carries wholesale; a --fidelity run
    # reads the same file so a song whose search fails can keep its previous
    # answer, and saying "carried 38" there would describe the opposite of
    # what happened -- 38 settings re-measured, not preserved.
    kept = 0 if args.fidelity else sum(1 for n in carried if n in songs)
    if kept:
        print(f"carried {kept} --fidelity setting(s) forward from "
              f"{args.output}; re-run with --fidelity to re-measure them",
              file=sys.stderr)
    elif not args.no_carry and not carry_source_readable:
        # THE DEFECT THIS GUARDS: with no previous file, `carried` is empty
        # by construction (there was nothing to read), so `kept` is 0 and the
        # branch above stays silent -- indistinguishable, from the output
        # alone, from a run that read a real presets.json and found nothing
        # worth carrying. A search written to a fresh -o path (the sharding
        # case, or just a scratch path) then diffs against a shipped
        # presets.json as though every carried setting had been destroyed,
        # when none was ever carried in the first place. Cost a whole
        # session at f0fd20c: 23 settings read as "destroyed" that were
        # simply never carried, over `-o C:/t/hr1_candidate.json`. This
        # cannot NAME the count that would have carried -- there is nothing
        # to compare against -- so it says only what is true: none were.
        print(f"warning: {args.output} has no previous file to carry "
              "--fidelity settings from, so 0 were carried -- do not diff "
              "this run's songs against another presets.json and read the "
              "difference as settings this run destroyed", file=sys.stderr)
    if args.fidelity:
        n = sum(1 for e in songs.values()
                if any(e.get(k) for k in FIDELITY_TOGGLES))
        print(f"--fidelity searched {', '.join(FIDELITY_TOGGLES)} over "
              f"{len(songs)} song(s) at {args.seconds}s: {n} took a non-default "
              "setting", file=sys.stderr)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
