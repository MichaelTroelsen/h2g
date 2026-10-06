"""Note and pitch-sequence entry helpers (split out of goatwriter.py, text moved unchanged)."""
from __future__ import annotations

from collections import (Counter)
from typing import (List, Optional)

from ..detect import (Detection)
from ..sidfile import (SidFile)
from .constants import (DRUM_DEEPEN_MARGIN, _drum_speed, EFFECT_PITCH_SEQ_MASK,
                        WAVE_NOTE_BASE)
from .primitives import (_arp_relative, _note_freq)
def _drum_steps_safe(steps: int, min_note: Optional[int],
                     multiplier: int = 1) -> bool:
    """Can `steps` unconditional sweep steps never underflow this instrument?

    `CMD_PORTADOWN` is `cptr->freq -= speed` on an unsigned 16-bit value with
    no clamp anywhere (gplay.c:557-572), so a sweep deeper than the distance
    from the note to zero wraps to a very high frequency and screeches -- which
    is why section 7.oo reverted an unbounded jump-to-self loop after it did
    exactly that on Commando. The player itself cannot: its own `LDA freqhi,X /
    BEQ out` freezes at zero.

    Goattracker's lowest note is only 279 (`GT_FREQ0`), so *no* step count above
    one is safe for every note the format can express -- section 7.oo's reason
    for stopping at one. It is safe for every note an instrument is actually
    *played* at, though, and that is a property this converter can read off the
    finished patterns (`patterns.min_played_notes`). A missing bound means
    "unknown", so it declines rather than assuming.
    """
    if min_note is None:
        return False
    hi, lo = _drum_speed(multiplier)
    step = (hi << 8) | lo
    return _note_freq(min_note) - steps * step >= DRUM_DEEPEN_MARGIN


def _pitch_seq_notes(sid: SidFile, det: Detection,
                     i: int) -> Optional[List[int]]:
    """Right-side note bytes for effect bit $10's arpeggio, or None.

    One entry per step of the player's cycle, in the order a wavetable should
    play them. Split out of `_pitch_seq_entries` so the composed block that
    carries bit $04's attack waveform as well (`_two_stage_pitch_seq_entries`)
    derives its steps from the same place rather than from a second copy of the
    rotation rule -- there is one rule and it is measured, see below.

    Gated **per record**, on this record's own effect byte: `det.pitch_seq` says
    only that the player reads the bit.

    **REACH, MEASURED v0.5.469 BY CORPUS BYTE-HASH: 28 of the 89 convertible
    files.** Converted twice on each song's own preset options with `pitch_seq`
    forced False then True, 89 compared, the same 6 errors both arms (the six
    non-Hubbard files):

        After_8, BMX_Kidz, Bangkok_Knights, Chain_Reaction,
        Dragons_Lair_Part_II, Flash_Gordon, Food_Feud, IK_plus, I_Ball,
        Kings_of_the_Beach_ingame, Knucklebusters, Lightforce,
        Mega_Apocalypse, Mr_Meaner, Nineteen, Off_the_Cuff, Pandora,
        Pygmies_Revenge, Rikky, Rock_Tells_the_Tale, Saboteur_II,
        Shockway_Rider, Star_Paws, Thundercats,
        Trans-Atlantic_Balloon_Challenge, W_A_R, W_A_R_Preview, Zoolook.

    Reaching a file is not the same as being adopted on it: 17 of the 28 carry
    `pitch_seq` in `presets.json` and 11 do not.

    **THREE FILES ARE DELIBERATELY OUT OF REACH, AND ONLY ONE OF THEM IS THIS
    FILE'S PROBLEM.** The v0.5.446 shape work widened detection to four
    spellings and picked up Mega_Apocalypse and Food_Feud; the files it did NOT
    pick up were each unmatched for a stated reason rather than a gap:

    * **Kings_of_the_Beach_intro (475 reversals) -- THE ONE THAT IS OURS.** Its
      sequence is a STATIC GLOBAL TABLE with no per-instrument index or pair
      copy, so there is nothing for `det.pitch_seq`'s (index, pairs, base)
      triple to point at and widening detection cannot reach it. Emitting it
      needs a writer here, not a spelling there. `det.pitch_seq` is None on it
      today, correctly.
    * **International_Karate and Formula_1_Simulator** contain no `AND #$10` at
      all; their `$55` byte is bit $04's arpeggio DEPTH nibble. Nothing for
      this emitter to do -- the mis-attribution is in `fidelity.py`'s VIBRATO.md
      census, where `out[0x10] = 'pitchseq'` is set unconditionally while every
      other cause is gated on detection.

    **AND A CORRECTION TO THE RECORD THAT OPENED THAT WORK**: it wrote
    "International_Karate (x2)", treating the two IK files as one population.
    They are not. `IK_plus` IS detected -- `PitchSeq(index=2667, pairs=2422,
    base=2403, steps=3)` -- and pitch_seq reaches it; only
    `International_Karate` is None. Anyone carrying "IK+F1" forward as a pair
    needing the census fix should carry `International_Karate` + F1 instead.
    """
    steps = _pitch_seq_steps(sid, det, i)
    if steps is None:
        return None
    # **Rotated so the most common step follows the attack.** The player's phase
    # is global, so which step a note begins on is unknowable here; a wavetable
    # always starts at its first entry. Emitting the sequence as written puts
    # Trans-Atlantic's `+24` one frame into every note, where the player's
    # `(0, 24, 0)` gives 0 on two phases of three -- measured, that cost 4.2
    # points of mean melody across 26 files and took Chain Reaction and Zoolook
    # from 100% to 78%. Leading with the modal step is the likeliest value under
    # a uniform unknown phase, not a fit to the metric. (Where the phase IS
    # knowable -- a divided counter whose clock `_pitch_seq_clock` reads --
    # `pitch_seq_phases` carries it per instrument and the emitters index
    # `_pitch_seq_steps` by it instead of using this rotation.)
    # **Ties go to the zero step.** `most_common` breaks a tie by insertion
    # order, which is right for the pair form -- `seq[0]` is the 0 that nothing
    # writes and it is inserted first -- and wrong for a static table read in
    # play order: Kings of the Beach intro's (24, 12, 0) has no modal step,
    # and leading with 24 put two octaves on every attack frame at -S5,
    # melody 99.5% -> 91.7% and pitch 100% -> 69% in the A/B. The step that
    # leaves the note alone is the one the attack frame needs, whatever its
    # position in the table; `max` keeps first-inserted among equals exactly
    # as `most_common` did, so no pair-form file can move on this.
    counts = Counter(steps)
    modal = max(steps, key=lambda s: (counts[s], s == 0))
    # Index 1, not index 0: entry 0 is the attack frame and must sound the
    # pattern's own note, so the modal step goes on the frame after it.
    # `_pitch_seq_entries` then rotates further -- always once a step spans
    # two calls, and at one call a step wherever entry 0 is not the zero step
    # -- because entry 0 is the frame siddump names the attack from at both.
    turn = (steps.index(modal) - 1) % len(steps)
    steps = steps[turn:] + steps[:turn]
    return [_pitch_seq_note_byte(step) for step in steps]


def _pitch_seq_note_byte(step: int) -> int:
    """Wavetable right side for one bit-$10 step: a signed semitone offset."""
    return (_arp_relative(1, step) if step < 0x80
            else (0x80 - (0x100 - step)) & 0xFF)


def _pitch_seq_steps(sid: SidFile, det: Detection,
                     i: int) -> Optional[List[int]]:
    """Record `i`'s bit-$10 steps as raw bytes, or None.

    Pair form: indexed by the value of the player's phase cell -- `ADC base,Y`
    with `Y = phase`, so entry `k` is what the player adds while the cell
    reads `k`. Static form: in play order (see below). Unrotated; the
    rotation is `_pitch_seq_notes`' and the phase-carrying path does without
    it.
    """
    seq = det.pitch_seq
    if seq is None:
        return None
    data = sid.data
    rec = det.instr_start + i * det.instr_stride
    if rec + 7 >= len(data) or not data[rec + 7] & EFFECT_PITCH_SEQ_MASK:
        return None
    if seq.pairs < 0:
        # **The static form, and the writer Kings of the Beach intro needs.**
        # Its bit-$10 handler ($100E-$102A) has no per-instrument index and no
        # pair copy: `LDY phase / CLC / LDA note,X / ADC $126B,Y / ASL / TAY`,
        # one global table for every record carrying the bit. The table is
        # `00 0C 18` -- the note, an octave up, two octaves up -- and the phase
        # cell is stepped DOWN (`DEC $126E / BPL / LDA #2 / STA $126E` at
        # $107F), so the player's order is 24, 12, 0: siddump reads 559 frames
        # of -12 and 292 of +24 on voice 1 in 60 s, and never +12, +12, -24.
        # Direction is the whole difference between a falling arpeggio and a
        # rising one, so it is carried here rather than assumed.
        #
        # INTERIM ENCODING, until `detect.PitchSeq` grows `static` and
        # `descending` fields (detect.py was read-only when this was written):
        # `pairs < 0` says the table is global and sits at `base`; `steps` is
        # its length, NEGATIVE when the phase counter decrements, in which case
        # play order is the table read backwards. Nothing in detect.py emits
        # this form yet -- `det.pitch_seq` is still None on the file -- so the
        # shipped conversion is unchanged until a spelling for the block above
        # lands there; `tests/test_pitch_seq_shapes.py` pins what this branch
        # does with the form when it does.
        n = abs(seq.steps)
        if n < 2 or seq.base < 0 or seq.base + n > len(data):
            return None
        steps = list(data[seq.base:seq.base + n])
        if seq.steps < 0:
            steps.reverse()
    else:
        at = seq.index + i * det.instr_stride
        if at >= len(data):
            return None
        idx = data[at]
        pair = seq.pairs + 2 * idx
        if seq.base >= len(data) or pair + 1 >= len(data):
            return None
        steps = [data[seq.base]] + [data[pair], data[pair + 1]]
        steps = steps[:max(2, seq.steps)]
    if not any(steps):
        return None
    return steps


def _pitch_seq_entries(sid: SidFile, det: Detection, i: int,
                       wave: int, multiplier: int = 1) -> Optional[tuple]:
    """Wavetable entries for effect bit $10's arpeggio, or None.

    `detect.PitchSeq` reads the mechanism: `note = played note + seq[phase]` on a
    global three-step counter, in 34 of 95 corpus files. A wavetable says that
    directly -- one entry per step, the waveform held and the right side naming a
    relative note -- and loops for as long as the note is held, as the player's
    counter does.

    **The step is a rate, so it is divided by `multiplier` at the point it is
    encoded** -- which here means multiplied, because the quantity emitted is a
    number of table entries rather than a period: the player's phase counter
    advances once per *frame* of a 50 Hz original, a Goattracker wavetable steps
    once per *play call*, and one frame is `multiplier` calls, so each step holds
    `multiplier` entries. Without it a `-S3` file arpeggiates three times too
    fast. `_two_stage_pitch_seq_entries` has scaled its own copy of this cycle
    since it was written and flagged this path as not doing so ("consistent with
    this function only at multiplier 1"); the two now agree at every `-S`.

    Two honest limits. The player's phase is **global**, so it does not restart
    with the note; a wavetable always does, and the emitted arpeggio can sit up
    to `steps - 1` frames out of phase. On three frames that is inaudible. And a
    sequence of all zeroes is *no* arpeggio -- the instrument simply plays its
    note -- so it emits nothing rather than three identical entries.

    A record whose own `+2` waveform is zero is declined: every entry here puts
    `wave` on the left, and `$00`-`$0F` on a wavetable's left side is a *delay*,
    not a waveform, so such a block would say something else entirely. Bit $04
    gives such a record a waveform to hold -- see
    `_two_stage_pitch_seq_entries`, which is why that path does not repeat this
    guard.
    """
    if not wave & 0xF0:
        return None
    notes = _pitch_seq_notes(sid, det, i)
    if notes is None:
        return None
    # Spelled out rather than delayed: a delay entry's right side is applied
    # only on its last call (gplay.c:697-723), and the note this step names has
    # to be current from the first call of the frame it covers. The same reason
    # `_two_stage_pitch_seq_entries` spells every frame of its cycle out.
    #
    # **A step is `frames_per_step` frames, and a frame is `multiplier`
    # calls.** The player's phase counter is stepped once per FRAME in 35
    # corpus files and once per reload of a divider in Food_Feud
    # (`detect._pitch_seq_divider`: `DEC $955E / BPL / LDA #$03 / STA $955E`
    # in front of the phase's own `DEC`, so once every four frames). Holding
    # each step one frame there arpeggiates four times too fast -- voice 2
    # read 7837 ties against the original's 5139 with the option forced, and
    # 3907 once the divider is honoured. The two factors are one quantity,
    # calls per step, so they multiply here and nowhere else.
    hold = max(1, multiplier) * max(1, det.pitch_seq.frames_per_step)
    if hold > 1:
        # **The attack frame's last write is entry 0 once a step is a frame
        # long, so the step that leaves the note alone has to move there.**
        # The packed player runs the wavetable from the note's *second* call
        # (player.s:908-911), so entry k covers calls `k*hold+1 .. (k+1)*hold`.
        # At `hold == 1` entry 0 lands on frame 1 and frame 0 is the firstwave,
        # which writes no note. (RETRACTED: this comment went on "so the attack
        # keeps the pattern's own pitch whatever entry 0 says" -- false for
        # what siddump reads, see the `elif` below.) At `hold >= 2` entry 0
        # covers frame 0 instead, and a transposing step there renames every
        # note siddump reads: Shockway_Rider's melody 98.6% -> 83.6%, its
        # voice 2 dropping from an exact 4-pitch match to five wrong pitches.
        # Rotating one
        # further -- the modal step to index 0 -- is the *same* rule applied at
        # the multiplier, not a second one, and restores Shockway_Rider to
        # 98.6% and Star_Paws to 96.6% while keeping the scaled rate. It also
        # makes the option free where it was not: Chain_Reaction (-S3) forced
        # to `--pitch-seq` reads melody 77.6% unscaled, 78.6% scaled and
        # **99.8%** scaled-and-rotated, which is its score with the option off,
        # at 1039 reversals against 772. See H2G-CONVERSION-METHOD.md 7.ttt.
        notes = notes[1:] + notes[:1]
        #
        # **Keyed on CALLS PER STEP, not on the multiplier alone** (task
        # pitch-seq-divider-s1-rotation, on a v0.5.493 tree). The
        # multiplier-only key asked "does entry 0 land on frame 0?", and at
        # -S1 it does not -- but that
        # was the wrong question. Traced per call in VICE on a synthetic
        # record (sequence (0, 12, 24), `frames_per_step=4`, one C-4 every 96
        # calls, packed by gt2reloc): at -S1 the note's first call writes
        # only the `$09` firstwave and leaves the frequency stale, entry 0
        # lands on call 1 as the comment above says -- and call 1 is the
        # frame siddump names the attack from, because `$09` is below `$10`
        # (siddump.c:436). Multiplier-only emitted `24x4, 0x4, 12x4` at -S1
        # and siddump named every attack C-6; keyed on calls per step it
        # emits `0x4, 12x4, 24x4` and names them C-4, which is what the same
        # record reads at -S3 (`0x12, 12x12, 24x12`, attacks C-4) -- the
        # per-frame content then matches -S3's one frame later.
        # `C:/t/pitch-seq-divider-s1-rotation/synth/report.txt` and
        # `siddump_S1_A.txt` / `siddump_S1_B.txt` beside it. At
        # `frames_per_step == 1` and -S1 the key is unchanged (`hold == 1`),
        # so only a divider at -S1 moves, and no corpus file has one (Food_
        # Feud packs at -S3). That trace also CONTRADICTED "the attack keeps
        # the pattern's own pitch whatever entry 0 says": the same synthetic
        # record at -S1 with no divider emitted `24, 0, 12` and siddump named
        # every attack C-6 (`siddump_S1_fps1.txt`). The `hold == 1` case is
        # settled on its own measurement, in the `elif` below.
    elif notes[0] != WAVE_NOTE_BASE and WAVE_NOTE_BASE in notes:
        # **At `hold == 1` entry 0 is still the frame siddump names the attack
        # from**, so it must be the zero step too (task
        # pitch-seq-s1-entry0-attack-name). The firstwave call is `$09`,
        # below `$10` (siddump.c:436), so the name comes from call 1 -- entry
        # 0 -- and a non-zero entry there renames every note: the synthetic
        # `24, 0, 12` above read every C-4 attack as C-6. Rotated only where
        # entry 0 is non-zero, so a record already opening on zero (Trans-
        # Atlantic's and Pandora's `0, 0, 24`) keeps its bytes. A/B at -t 180
        # on each -S1 file with such a record, `pitch_seq` forced where the
        # preset lacks it (melody, before -> after; held BMX_Kidz and Rikky
        # not measured): Nineteen (shipped) 97.28% -> 98.05%, Bangkok_Knights
        # 83.73% -> 96.88%, IK_plus 88.06% -> 99.89%, I_Ball 93.38% -> 96.45%,
        # Mega_Apocalypse 88.83% -> 93.28%, Pygmies_Revenge 89.93% -> 91.74%.
        # Measured on a v0.5.494 tree carrying uncommitted goatwriter work. The
        # first four forced files now read exactly their option-off melody,
        # with reversals at 0.95-1.01 of the original against 0.29-0.79 off.
        # It costs pitch_jaccard on two: Nineteen 0.857 -> 0.821, Pygmies
        # 0.985 -> 0.971 -- the original's global phase does put a step on
        # some attacks, and those names leave our pitch set.
        # `C:/t/pitch-seq-s1-entry0/ab_table.txt` (arms A and Cc).
        turn = notes.index(WAVE_NOTE_BASE)
        notes = notes[turn:] + notes[:turn]
    left = [wave] * (len(notes) * hold)
    right = [n for n in notes for _ in range(hold)]
    return left, right


def _pitch_seq_phase_notes(sid: SidFile, det: Detection,
                           i: int) -> Optional[List[int]]:
    """Note bytes indexed by the player's phase-cell value, or None.

    The pair form only: there `Y = phase` indexes `base` directly, so entry
    `k` is what the player adds while the cell reads `k`. The static form's
    `_pitch_seq_steps` order is play order, not cell order, and nothing
    detects it yet, so it is declined rather than guessed.
    """
    if det.pitch_seq is None or det.pitch_seq.pairs < 0:
        return None
    steps = _pitch_seq_steps(sid, det, i)
    if steps is None:
        return None
    return [_pitch_seq_note_byte(s) for s in steps]


def _phase_note(notes: List[int], phases: tuple, frame: int) -> Optional[int]:
    """The note byte for `frame` frames after the attack (`frame >= 1`)."""
    k = phases[(frame - 1) % len(phases)]
    return notes[k] if 0 <= k < len(notes) else None


def _pitch_seq_phased_entries(notes: List[int], phases: tuple, wave: int,
                              multiplier: int, start: int,
                              budget: int) -> Optional[tuple]:
    """The standalone bit-$10 block with the player's phase carried, or None.

    `phases` is `pitch_seq_phases`' value for this instrument: the phase
    cell's reading on frames 1, 2, ... one whole counter period after the
    attack. The attack frame itself keeps the pattern's own note -- the
    original's does (Food_Feud voice 2 frame 1512 attacks C#6 with the cell
    reading 1, and the `-4` lands on 1513) -- and so does every call of it.

    Entry `e` covers call `e + 1` of the note (player.s:908-911, as
    `_pitch_seq_entries` reads it), which is frame `(e + 1) // multiplier`:
    `multiplier - 1` entries of frame 0, then the period, one frame being
    `multiplier` entries, looped onto its own first entry -- which is
    continuous because the period is the counter's whole cycle.

    **At -S1 frame 0 is entry 0, not the firstwave call.** The note's call
    0 writes only the `$09` firstwave, below `$10` (siddump.c:436), so the
    attack is named -- and first heard -- on call 1, entry 0: the same reason
    `_pitch_seq_entries` puts the zero step there at `hold == 1`. So one
    entry of the attack's own note leads, never fewer (task
    mega-0a06-frame-2-pitch-move: Mega_Apocalypse `$0A06`, the first -S1
    record on this path, read `0, 8, 3, 0` from its attack without it
    against the original's `0, 0, 8, 3` on all 110 notes). At -S2 and up
    `multiplier - 1` is already at least one.
    """
    m = max(1, multiplier)
    lead = max(1, m - 1)
    body: List[int] = []
    for f in range(1, len(phases) + 1):
        n = _phase_note(notes, phases, f)
        if n is None:
            return None
        body += [n] * m
    right = [WAVE_NOTE_BASE] * lead + body
    if len(right) + 1 > budget:
        return None
    left = [wave] * len(right) + [0xFF]
    return left, right + [start + lead]
