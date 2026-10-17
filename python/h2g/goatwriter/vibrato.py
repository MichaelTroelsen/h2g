"""Classic, triangle and table vibrato entries and layout (split out of goatwriter.py, text moved unchanged)."""
from __future__ import annotations

import math
from typing import (List, Optional)

from ..detect import (Detection, TRIANGLE_VIBRATO_GATE,
                      TRIANGLE_VIBRATO_MAX_SHIFT, TRIANGLE_VIBRATO_PEAK,
                      TRIANGLE_VIBRATO_PERIOD,
                      VIBRATO_BOUND_MASK, VIBRATO_BOUND_SHIFT,
                      VIBRATO_SHIFT_MASK)
from ..sidfile import (SidFile)
from .constants import (FIXED_ARP_PARITY_MASK, FORMAT_GTS5, GT_MAX_VIB_SHIFT,
                        GT_WAVE_FIRST_CMD, GT_WAVE_JUMP, GT_WAVE_LAST_CMD,
                        GT_WAVE_LAST_DELAY, GT_WAVE_NO_NOTE,
                        SPEED_NOTE_RELATIVE, VIBRATO_CMP_BIAS, VIBRATO_DELAY)
from .primitives import (_counter_gate_call, _rate_shift, _record_row_calls)
from . import constants as _gw_constants
from . import primitives as _gw_primitives

# Classic-vibrato entries whose period is given up for depth, by file:
# {(PSID title, instrument record index): calls to take off the entry's `cmp`}.
# User decision 2026-10-09 (`classic-vibrato-balance-rate-and-depth`, task
# `las-vegas-classic-vibrato-original-depth`): Las_Vegas_Video_Poker keeps the
# original's DEPTH on `$6B9A` (record 6). Its vibrato byte `$1A` (bound 3,
# shift 2) is shared with `$0AA0` (record 11), and the shipped entry `($8C, 4)`
# swings 3.46 depths on `$6B9A` against the original's 2.99. Record 6 alone
# gets `($8B, 4)`; record 11 keeps `($8C, 4)` byte for byte, because trimming
# it too reads mixed (voice-0 bend -1.7% -> -11.4% against reversals +29% ->
# -14%; see "DECIDED" in `_classic_vibrato_entry`). Keyed by name and record,
# as `stored_wave.HELD` keys by name, so no other file's bytes move and the
# entry formula is untouched. Pinned in tests/test_lvvp_depth_trim.py.
CLASSIC_DEPTH_CMP_TRIM = {("Las Vegas Video Poker", 6): 1}


def _depth_trimmed(name: str, record: int, entry: Optional[tuple]
                   ) -> Optional[tuple]:
    """`entry` with `CLASSIC_DEPTH_CMP_TRIM`'s calls taken off its `cmp`."""
    trim = CLASSIC_DEPTH_CMP_TRIM.get((name, record), 0)
    if entry is None or not trim:
        return entry
    cmp_value = max(0, (entry[0] & 0x7F) - trim)
    return (SPEED_NOTE_RELATIVE | cmp_value, entry[1])


def _classic_vibrato_entry(byte: int, multiplier: int,
                           row_calls: int = 0,
                           gate_skip: Optional[int] = None,
                           dwell: bool = False,
                           depth_extra: int = 0) -> Optional[tuple]:
    """Speed-table entry for one instrument byte in the $78/$07 format.

    The mapping is close to literal because both sides express the depth the
    same way. The player computes `(freq(note) - freq(note-1)) >> shift` and
    oscillates a counter between 0 and `bound`; Goattracker's note-relative
    speed (`ltable >= $80`) computes the interval at the current note shifted
    right by `rtable`, and flips direction when its own counter passes
    `ltable & $7f`. So:

        entry = ($80 | cmp, rshift)

    with the two derived from the half-period and the excursion, both taken
    from the *simulated* gplay.c semantics (see VIBRATO_CMP_BIAS) rather than
    from its constants:

    * **Period.** The player's counter steps by one per frame between 0 and
      `bound` (Warhawk $11FE-$121E: `DEC ctr,X / BNE out` walking down,
      `INC ctr,X / LDA bound,X / CMP ctr,X / BCS out` walking up), so its
      half-period is `bound` frames. Goattracker's is `cmp + 2` *calls*, which
      is `(cmp + 2) / multiplier` frames. Hence

          cmp = bound * multiplier - VIBRATO_CMP_BIAS

    * **Excursion.** The apply loop subtracts AND adds. It first takes
      `bound >> 1` depths off the note, then adds `ctr` depths back:

          LVVP $522A  LDA bound,X / LSR / TAY / DEY / BMI / freq -= depth
          LVVP $5251  LDY ctr,X   /             DEY / BMI / freq += depth
          (Warhawk: the same two loops at $1251 and $1278)

      so the frequency is `note + (ctr - (bound >> 1)) * depth` with `ctr`
      walking 0..bound, and the **peak-to-peak is `bound * depth`**.
      Goattracker's is `(cmp + 2) * speed`; with `cmp + 2 = bound *
      multiplier` from the period, `speed = depth / multiplier`, i.e.

          rshift = shift + _rate_shift(multiplier)

      which is exactly what is emitted. RETRACTED (lvvp-vibrato-phase,
      2026-10-05): this bullet used to read "The player's apply loop only
      ever subtracts (Warhawk $1245: `LDA ctr,X / LSR / TAY / DEY / BMI out /
      freq -= depth`), so the note is the top of the swing and `(bound >> 1)
      * depth` is a **peak-to-peak**" and derived `shift + 1 +
      log2(multiplier)` from it. The loop it quoted loads the BOUND cell
      (Warhawk's split stores `bound` to $15C3, the operand there), and it
      missed the add loop after it. The `+ 1` dropped at v0.5.369 (3ec87b1,
      "the vibrato depth doubles", because the derived depth measured too
      shallow) is that derivation's error removed, not a fit against it.
      Census over the 61 corpus files `VIBRATO_SHAPES` matches
      (C:/t/lvvp-vibrato-phase/census.py): all 61 carry the subtract loop;
      59 carry the add loop as `LDY ctr,X / DEY / BMI / CLC` on the counter
      the update steps. The other two were resolved by
      classic-vibrato-census-unresolved (disassembly census and an emulator
      that agrees with siddump on every frame compared; pinned in
      tests/test_classic_vibrato_census.py): **Tarzan** is the same
      mechanism with mixed addressing (ctr `$49,X` and bound `$4C,X` zero
      page, dir `$5500,X` absolute), which the byte search did not know.
      **Mozart is not the same on voices 1 and 2**: its update steps
      `$0C24,X`, but its add loop is `LDY $0C24` (`AC`, absolute, no `,X`),
      so every voice adds VOICE 0's counter. Voice 2 (bound 5) and voice 1
      (bound 2) follow voice 0's counter 0..3 at period 7 ticks, so their
      swing is -2..+1 and -1..+2 depths where their own bounds ask for
      -2..+3 and -1..+1. The emitter models each voice with its own bound;
      that mismatch is open (opened as `mozart-vibrato-voice-zero-counter`).
      The counter's period is `2 * bound` in 54 of the 61 files and
      `2 * bound + 1` in seven (Mozart and the `$1003` family: Go_Go_Dash,
      Lakers_vs_Celtics, Lion_Heart, Pacific_Coast, Radio_ACE,
      Sun_Never_Shines), whose update holds the bound for two updates;
      `half = bound * multiplier` below takes the first for all of them,
      except where `dwell` is set (`Detection.vibrato_dwell`, which all
      seven read: the six `$1003` files resolve their vibrato byte through
      `detect._patched_split_record_offset` since classic-vibrato-period-
      dwell-family, their split reading a patched `LDA #imm` fed from record
      +5, not the record itself; the pattern command `$86 nn`, which
      overrides the byte for one event, is not emitted).

      **The update does not run once a frame in a player whose outer gate
      stops the whole play routine** (mozart-classic-vibrato-file-wide-rate,
      v0.5.517; figures historical). Mozart's `$0829 DEC $0C33 / BPL /
      LDA #$02 / STA $0C33 / RTS` runs the update on two calls in three, so
      an update lasts 3/2 frames, and with the two-update dwell its half-
      period is `(bound + 1/2) * 3/2` frames. The entry said `bound`: voice
      0's bound-3 records read a 3-frame half-period against the original's
      5.0 (401 cycles in 180 s against 128). `gate_skip` (the gate's reload
      `O`, for a player `call_phase.entry_gate` accepts) stretches `half` by
      `(O + 1) / O` and `dwell` by `(2 * bound + 1) / (2 * bound)`; the
      shift takes `log2` of the whole call rate, as it always did for the
      multiplier. Ablated one cause at a time on those records (half-period
      frames ours, original 5.0): neither 3.0, skip alone 5.0, dwell alone
      4.0, both 5.0; cycles 401 / 144 / 188 / 127. A gate that guards only
      the pattern clock (the JMP spelling) leaves the update running every
      frame and is not this: seven classic-vibrato files qualify
      (International_Karate, Kentilla, Las_Vegas_Video_Poker, Mozart,
      Proteus, Thrust, Warhawk); the other 48 are unchanged byte for byte.
      (Bump_Set_Spike joined them when the gate read became the one its play
      address enters, `tempo.outer_gate_match`.)

      **Mozart's depth loop shifts `shift + 1` times** (`LSR / ROR / DEC
      cnt / BPL` tests its count last, where Las_Vegas' `DEC cnt / BMI /
      LSR / ROR / JMP` tests it first), so its depth is `interval >> (shift
      + 1)` and its swing `bound` of those. `depth_extra` (1 for that loop,
      `Detection.vibrato_shift_extra`) puts the shift on the emitted `cmp`
      instead of on the multiplier: `rshift = shift + depth_extra +
      round(log2((cmp + 2) / bound))`, the swing `(cmp + 2) * speed` matched
      to `bound` depths in log space. Mozart's file `depth` 1.42 -> 1.10,
      `bend` 1.48 -> 0.79, `vib` 2.26 -> 1.62 at -t 180; melody, sequence,
      wave, ADSR and gate flat. What remains of `vib` is not this entry's
      rate: voices 1 and 2 add voice 0's counter (above; voice 2's $4820,
      339 notes, now reads 115 cycles against 317 where its own bound 5 had
      matched the count by accident), and voice 1's $3800 swings 23 depths,
      which is no bound/shift vibrato (491 cycles against 207).

    * **Phase and centre, which Goattracker cannot carry.** Two properties
      of that loop have no speed-table encoding. Both are measured, not
      emitted:

      - **Centre.** The swing spans `-(bound >> 1) .. bound - (bound >> 1)`
        depths around the note. An odd bound is lopsided: bound 3 swings
        -1..+2, centred half a depth above the note. Goattracker's
        oscillation is centred on the note, and it has no sub-note detune
        to move the centre.
      - **Phase.** `ctr` and its direction are per voice and nothing resets
        them at a note. In Las_Vegas_Video_Poker, $54DD,X and $54FD,X are
        written only by the update at $51DC-$51F7. The update runs every
        frame a vibrato record is current, so each note picks the
        oscillator up wherever the last one left it. Goattracker zeroes
        `vibtime` on every wavetable note step (gplay.c:723, player.s
        `mt_wavenote` "Reset vibrato phase"), so each note starts at the
        centre, moving up. The census found 55 of 61 counters with no
        writer outside the update. Shockway_Rider, W_A_R and Spellbound
        add only an init-time clear, Star_Paws' longer update is its own
        DEC, and Mega_Apocalypse's zero-page hits were byte-search false
        positives: its one real writer is the init-time clear at `$580F`
        (`LDX #$44 / LDA #$00 / STA $B0,X / DEX / BPL`, entered by `JMP
        $580F` at `$4AA0`). Re-read over decoded, reachable code for all
        61 files: 57 have no store to the counter or direction cell outside
        the update, and the other four (Mega_Apocalypse, Shockway_Rider,
        Spellbound, W_A_R) store zero in an init-time clear. Run in an
        emulator for 3000 frames of subtune 0 (all 61 files, C:/t/classic-
        vibrato-census-unresolved/dyn_census.py), no store to those cells
        outside the update ever executed after init. Six files store during
        init: those four, plus Samantha_Fox_Strip_Poker (`STA $00,X` over
        `$A0..$EF` at `$7D65`) and I_Ball (its relocation copy, `STA ($FD),Y`
        at `$C220`), which a scan keyed on the cell's base address cannot
        see. The add loop ran in 53 of the 61 files in that window (8 never
        reached a vibrato record on subtune 0, so they are static-only).

      Measured at -t 120 s, subtune 0, on Las_Vegas_Video_Poker's bound-3
      records (vibrato byte $1A). The original is traced at -m1, ours under
      presets and packed at -S4 (C:/t/lvvp-vibrato-phase/phase.py, base.txt).
      Offsets are in the original's depth units, `(f(n) - f(n-1)) >> 2` from
      the player's table at $53F9. The start phase is (the offset at frame
      1, the direction of the first move), over notes of 8+ frames:

          record          side  notes  start phases               swing
          $6B9A (instr 6) orig  305    -1u 52  0d 49  0u 49        -1..+2: 303
                                       +1d 52 +1u 53 +2d 50
                          ours  305    0u 305                      -1..+1: 280
          $0AA0 (instr B) orig   80    -1u 22  0d 4  0u 4          -1..+2: 56
                                       +1d 22 +1u 22 +2d 6
                          ours   84    0u 84                   -1.5..+1.5: 82

      Against six equally frequent phases, every fixed start phase is the
      same distance from the original on average: the distribution does not
      change when the cycle is shifted. So no choice of Goattracker's start
      phase can beat another. Only a free-running phase would, and the
      phase reset above rules that out. FIDELITY.md's `depth` is a
      peak-to-peak, so it reads the swing's size and not its centre. Both
      records carry vibrato byte $1A and so share one speed entry, yet at
      8586101 ours swung 2 depths on $6B9A (voice 2, low notes) and 3 on
      $0AA0.

      **That gap has closed from the other side (lvvp-6b9a-vibrato-depth,
      39b5de2 + the cycle-2 merge; figures historical, one sample per frame
      at -t 180 under presets).** The swing a note gets is `(cmp + 2) * (I
      >> rshift)`, `I` being Goattracker's interval from the note UP
      (gplay.c:790-793), against the original's `bound * u` with `u = (f(n)
      - f(n-1)) >> shift`. At the shipped entry that expression predicts
      the measured peak-to-peak of each of $6B9A's 305 notes to a mean 0.02
      depth (3.48 predicted, 3.46 measured; the original 2.99). The "2 depths"
      was reproduced exactly by switching `gate_skip` off (the pre-v0.5.517
      entry `($89, 4)`: 280 of 305 notes span 2.0, 0AA0 82 of 84 span 3.0),
      so it was the missing gate stretch -- `cmp + 2` = 11 calls where the
      original's half-period asks 15 -- and not the low notes. v0.5.517
      stretched it to `($8C, 4)`, 14 calls after the tick-0 compensation, and
      $6B9A now swings 3.46 depths (span 3.0 on 64 notes, 3.5 on 125, 4.0 on
      116): past the original's 3.0 by 16%. The rest of the 16% is the
      integer `rshift`: the amplitude is `(cmp + 2) / (bound * 2^(rshift -
      shift))` of the original's, 14/12 here, and `rshift` 5 would be 14/24.
      Not explained, and not chased: at `($89, 4)` the formula gave 2.73 and
      the trace 2.04 on $6B9A (the plateaus: two equal frames at each peak)
      while $0AA0 read 2.87 against 2.88.

      Shortening `cmp` buys depth with rate. Same run, LVVP rows (original
      bend 216015, travel 159896, reversals 6272; direction reversals in a
      note's first 40 frames: original 7.54):

          entry                  $6B9A depths  bend   travel  reversals  rev/40f
          ($89, 4) no gate_skip  2.04          0.809  0.798   1.035      9.31
          ($8A, 4) cmp 10        2.72          0.888  0.959   1.047      8.31
          ($8B, 4) cmp 11        2.73          0.912  0.982   1.045      8.23
          ($8C, 4) shipped       3.46          1.027  1.083   1.057      7.23

      The shared entry is a compromise: voice 0 (the $0AA0 record, bend
      110792 shipped, 95104 at cmp 10, original 112719) and voice 2 ($6B9A,
      111040 shipped, 96628 at cmp 10, original 103296) are 2% shallow and 7%
      deep, and no file column moves clearly closer: bend leaves 1.027 for
      0.888 while travel goes 1.083 -> 0.959. Whether to give up the
      original's period for its depth was the user's call (opened as
      `classic-vibrato-balance-rate-and-depth`). Pinned in
      tests/test_lvvp_vibrato_depth.py.

      **DECIDED (user, 2026-10-09): keep the original's depth, Las_Vegas
      only** (`las-vegas-classic-vibrato-original-depth`;
      `CLASSIC_DEPTH_CMP_TRIM`, applied in `_vibrato_layout`; figures
      historical, v0.5.521 base, 107 s window = the file's own, original at
      -m1, ours under presets packed at -S4, one sample per frame). The
      entry formula is NOT touched -- the seven gate-stretch files read it
      -- so the trade is a per-record `cmp - 1` on record 6, `($8B, 4)`.
      `$6B9A` and `$0AA0` play on different voices and so are separable;
      each arm below is a full conversion with the trim on the named
      record(s):

          arm        $6B9A depths  v2 bend  v2 travel  $0AA0 depths  v0 bend  v0 travel  rev 6B9A  rev 0AA0
          original   2.99          103296   85900      2.70          112719   73996      854       185
          neither    3.46          111040   94741      3.18          110792   78371      976       239
          record 6   2.73          97034    85043      3.18          110792   78371      978       239
          record 11  3.46          111040   94741      2.88          99900    72027      976       159
          both       2.73          97034    85043      2.88          99900    72027      978       159

      Record 6 takes its depth from +16% to -9% of the original's, its
      voice's bend from +7.5% to -6.1% and travel from +10.3% to -1.0%; its
      reversals do not move (978 against 854). Record 11 is mixed (bend
      worse; travel, depths and reversals better), so it is left alone and
      `$0AA0` stays byte-identical -- opened as a question for the user.
      No integer `cmp` reaches 2.99: $6B9A reads 2.04 / 2.72 / 2.73 / 3.46 /
      3.46 at cmp 9..13, because the swing is sampled once a frame against
      four calls a frame. cmp 11 is the nearest and keeps the most period
      (13 calls, 3.25 frames, against the original's 3.75). The file's row
      at -t 180 (shipped arm): bend 1.027 -> 0.962, travel 1.083 -> 1.022,
      reversals 1.057 -> 1.058, depth 1.000 -> 0.999; melody, wave, gate and
      adsr flat. Corpus byte-hash under presets: the only mover is
      Las_Vegas_Video_Poker (89 converted, 6 refused, Commando same).

    * `multiplier` is in both because Goattracker's counter advances per play
      call and the player's per frame -- the same per-frame/per-call division
      every other rate in this file takes (see _drum_speed).

    * **The packed player does not run the vibrato on tick 0 of a row.**
      `player.s:982-987` is `REALTIMEOPTIMIZATION`, default-on in `gt2reloc`
      (`-R0` turns it off): `lda mt_chncounter,x / beq mt_done`, commented "No
      continuous effects on tick0", and `mt_chnvibtime` is only touched below
      that branch. So a row of `row_calls` calls advances the counter on
      `row_calls - 1` of them and a half-period encoded at face value lasts
      `row_calls / (row_calls - 1)` calls of real time. This is the *same*
      dropped call `patterns._scaled_step` already compensates for the
      portamento, in the other direction -- there the step is scaled **up**,
      here the comparison threshold is scaled **down**:

          cmp = bound * multiplier * (row_calls - 1) / row_calls - BIAS

      Powerplay Hockey is the file that made this measurable: it is the first
      corpus file whose classic-vibrato instruments emit *anything* (its
      instrument table was wrong until § 7.iiiii), and all three read
      0.648/0.669/0.656 of the original's reversal count against a predicted
      `(3 - 1) / 3 = 0.667` at its `row_calls` of 3. **Confirmed by turning
      the proposed cause off rather than by argument**, which is the check
      § 7.ppppp exists to demand: packing the same `.sng` with `-R0` takes the
      file's `vib` **0.658 -> 1.015** with `melody` unmoved at 0.993, and over
      all 55 files carrying this engine it takes mean `|log2(vib)|`
      **0.476 -> 0.411**. Compensating here instead reaches 0.428 -- the
      emitter reproduces removing the cause, on the rate axis, to within 0.017.

      `-R0` is not itself the fix, and this run reproduces why: it takes the
      median slide ratio **0.994 -> 1.118** over the same 55, because
      `patterns._scaled_step` already compensates the same dropped call for
      the portamento and disabling the skip double-corrects it (the corpus
      figure recorded in CLAUDE.md, re-measured on this population).

      **What it costs, measured rather than predicted.** Goattracker
      *integrates* a step, so the excursion is `(cmp + 2) * speed`:
      shortening `cmp` shortens the swing by the same
      `(row_calls - 1) / row_calls`. `bend` sees exactly that and moves the
      wrong way -- mean `|log2(bend)|` **1.221 -> 1.264** (closer on 11 of 48,
      further on 25) where `-R0`, which fixes the rate without paying for it,
      reaches 1.079. **Everything else is flat**: `melody`, `sequence`,
      `wave`, `adsr`, `onset`, `gate` and the attack counts are identical on
      all 55 files, so what moves here is pitch oscillation and nothing else.

      The obvious repair is to take the depth back in `rshift`, and it was
      built and measured before being rejected. `rshift` is an integer shift
      and the factor wanted at `row_calls == 3` is `log2(3/2) = 0.585`, so the
      nearest whole shift over-corrects: decrementing it lands `bend` at 1.096
      -- close to `-R0`'s 1.079, as intended -- and costs **melody on
      Powerplay 0.993 -> 0.922 and Sigma Seven 0.990 -> 0.972**, the swing
      being deep enough to rename attacks. `vib` is identical either way
      (0.4282), which is the signature of a change to depth alone. So `rshift`
      stays where v0.5.129 left it, for a second reason now: not only did its
      two old errors cancel, there is no integer that pays this one back
      without a melody regression on the file the correction was derived from.

    Until v0.5.129 `cmp` was `2 * bound * multiplier`, from reading
    Goattracker's half-period as `cmp / 2` calls instead of `cmp + 2`. That
    made the emitted oscillation run at close to **half** the player's rate for
    all 56 files carrying this format. `rshift` is unchanged by the correction
    and that is not a coincidence: the old derivation equated the player's
    peak-to-peak with a Goattracker *amplitude*, and the two errors -- a period
    twice too long and an excursion convention off by two -- cancelled in the
    shift exactly. Only `cmp` was ever wrong. (The "player's peak-to-peak"
    in that account is the `(bound >> 1) * depth` retracted under
    Excursion above. The real one is `bound * depth`, so `rshift` was one
    too large until v0.5.369 dropped the `+ 1`.)

    Two deliberate approximations besides, neither hidden: the player applies
    its counter as a *position* (an absolute offset from the note) where
    Goattracker integrates a step, which is the same triangle reached
    differently; and Goattracker takes the interval *above* the note where the
    player takes the one below, about 6% of a semitone.
    """
    bound = (byte & VIBRATO_BOUND_MASK) >> VIBRATO_BOUND_SHIFT
    if not byte or not bound:
        # The player's own test: `LDA record+5,Y / BNE` at Warhawk $11EA. A
        # bound of zero is an oscillation with no excursion, which is the same
        # silence reached one step later.
        return None
    shift = byte & VIBRATO_SHIFT_MASK
    half = bound * multiplier
    # How many of OUR calls one of the player's updates lasts, beyond
    # `multiplier`. Both factors are 1 in every file but the ones that read
    # them, so every other entry is the byte it always was.
    stretch = 1.0
    if dwell:
        # The counter sits on the bound for two updates: a period of
        # `2 * bound + 1`, so the mean half-period is `bound + 1/2`.
        stretch *= (2 * bound + 1) / (2 * bound)
    if gate_skip:
        # The outer gate returns without running the update on one call in
        # `O + 1`, so an update lasts (O + 1) / O frames.
        stretch *= (gate_skip + 1) / gate_skip
    if stretch != 1.0:
        half = half * stretch
    # `row_calls` is what `build_sng` receives, which `convert` passes as
    # `short_row_calls` -- the file's *shortest* row, not `_scaled_step`'s
    # longest. Exact on the 44 of these 55 files that write one row length,
    # and an over-correction on the 11 that vary, worst at Warhawk (8 against
    # 40) -- which is one of the files whose `vib` moves away from 1 here. The
    # quantity actually wanted is the mean row over the calls the vibrato
    # runs for; neither end is that, and reaching it means a new argument
    # through `convert`.
    # Zero means "do not compensate", and so does 1 -- the same convention as
    # `patterns._scaled_step`, which since the CMD_FUNKTEMPO 2-call row
    # (goatwriter.constants.CMD_FUNKTEMPO) counts 2 as a row: one call of two
    # runs effects.
    if row_calls >= 2:
        half = half * (row_calls - 1) / row_calls
    # bound 1 at -S1 asks for a half-period of one frame; Goattracker's
    # shortest is two calls (cmp 0), which is what the clamp gives.
    cmp_value = min(0x7F, max(0, round(half) - VIBRATO_CMP_BIAS))
    if depth_extra:
        # The depth loop shifts `shift + 1` times, so the player's depth is
        # `interval >> (shift + 1)` and its swing `bound` of those. Ours is
        # `(cmp + 2) * (interval >> rshift)`, so the shift that matches the
        # two is read off the cmp ACTUALLY emitted -- which already carries
        # the stretch and the tick-0 compensation -- and rounded in log space.
        calls = cmp_value + VIBRATO_CMP_BIAS
        rshift = shift + depth_extra + round(math.log2(calls / bound))
    else:
        # The depth is the same quantity per update, so a longer half-period
        # must be paid for in the shift or the swing grows by the stretch.
        # `_rate_shift` rounds log2 of the whole call rate, the way it always
        # has for the multiplier alone.
        rshift = shift + _rate_shift(multiplier * stretch)
    rshift = min(max(rshift, 0), GT_MAX_VIB_SHIFT)
    return (SPEED_NOTE_RELATIVE | cmp_value, rshift)


def _effect_calls(entries: Optional[List[tuple]], ptr: int, calls: int,
                  row_calls: int = 0) -> int:
    """How many of a note's calls 1..`calls - 1` run continuous effects.

    That is the count `vibdelay` is spent against, and two things withhold a
    call from it (player.s `mt_wavedone`, gplay.c TICKNEFFECTS):

    * **tick 0.** `REALTIMEOPTIMIZATION` is on in every pack (gt2reloc.c:55)
      and skips continuous effects whenever the channel counter is 0 -- the
      first call of every row, `row_calls` apart from the note's own call 0.
      The `row_calls >= 2` convention of `_classic_vibrato_entry` applies:
      a 2-call CMD_FUNKTEMPO row withholds every second call; 0 and 1
      withhold nothing.
    * **a wavetable step that writes a frequency.** A step whose right column
      is not $80 (editor encoding; greloc inverts the high bit) takes the
      `mt_wavefreq` / `goto PULSEEXEC` path, and so does a wavetable command
      ($F0-$FE); only a delay tick, a no-note step or a finished program
      falls through to the effects. The note's own call 0 runs no wavetable
      at all (`mt_newnoteinit` ends in `jmp mt_loadregs`), so step 1 is on
      call 1. Pandora's `41/00 41/00 41/00 FF/00` withholds calls 1-3.

    `entries` is the finished wavetable and `ptr` the record's 1-based
    pointer into it; None or 0 is "no program", which withholds nothing.
    """
    return len(_effect_call_list(entries, ptr, calls, row_calls))


def _effect_call_list(entries: Optional[List[tuple]], ptr: int, calls: int,
                      row_calls: int = 0) -> List[int]:
    """The calls among 1..`calls - 1` that run continuous effects, in order
    -- `_effect_calls`' list, for a caller that needs to know WHERE they are.
    """
    out: List[int] = []
    wavetime = 0
    for c in range(1, calls):
        effects = True
        if entries and 0 < ptr <= len(entries):
            wave, note = entries[ptr - 1]
            if wave <= GT_WAVE_LAST_DELAY and wavetime != wave:
                wavetime += 1                   # a delay tick: effects run
            else:
                wavetime = 0
                ptr += 1
                if ptr <= len(entries) and entries[ptr - 1][0] == GT_WAVE_JUMP:
                    ptr = entries[ptr - 1][1]
                if (GT_WAVE_FIRST_CMD <= wave <= GT_WAVE_LAST_CMD
                        or note != GT_WAVE_NO_NOTE):
                    effects = False
        if row_calls >= 2 and c % row_calls == 0:
            effects = False
        if effects:
            out.append(c)
    return out


def _gate_target_call(det: Detection, multiplier: int, attack_call: int,
                      record: Optional[int] = None,
                      duration_onset: bool = False) -> Optional[int]:
    """The call the oscillator should first run on: the counter gate's
    (`_counter_gate_call`), or -- with `duration_onset`, for a DURATION gate
    (dialect B) -- the original's frame 1, `multiplier + attack_call`.

    A duration gate is a threshold on the note's stored length, decided at
    the fetch: a note that qualifies runs the update from the frame after
    its fetch frame. Formula_1_Simulator `$C247 LDA $C4C9,X / AND #$1F /
    CMP #$03 / BCC $C27B` sits after the counter update at `$C1D6-$C1F6`,
    which the fetch frame never reaches (`$C077 DEC $C4C6,X / BMI` fetches
    and leaves by `$C187 JMP $C3F5`), so the first frame the frequency moves
    is frame 1 -- measured (v0.5.583, 60 s of subtune 0, notes of 10+
    frames): 22 of 28 vibrato notes move on frame 1, 6 on frame 2 (the
    free-running counter on the swing's centre at frame 1). The
    plain program `[41/00 41/00 41/00 FF/00]` withheld calls 1-3 and the
    frame-1 floor put the oscillator on frame 3."""
    target = _counter_gate_call(det, multiplier, attack_call, record)
    if target is not None or not _onset_engine(det, duration_onset):
        return target
    return multiplier + attack_call


def _onset_engine(det: Detection, duration_onset: bool) -> bool:
    """Whether `duration_onset` puts this player's oscillator on frame 1: a
    classic player whose gate is a DURATION threshold, or the LFO-table
    player, which gates nothing and walks its table on every frame after
    the fetch (Hollywood_or_Bust, same census: all 120 matched vibrato
    notes move on frame 1, ours on 19 of them before the option)."""
    if not duration_onset:
        return False
    vg = det.vibrato_gate
    if det.vibrato_offset is not None:
        return vg is not None and vg.form == "duration"
    return det.table_vibrato is not None


def _gate_reachable(det: Detection, duration_onset: bool) -> bool:
    """Whether any record can have a `_gate_target_call`: a counter gate
    that was read, or an `_onset_engine`."""
    vg = det.vibrato_gate
    if (vg is not None and vg.form == "counter"
            and (vg.gate is not None or vg.table is not None)):
        return True
    return _onset_engine(det, duration_onset)


def _classic_gate_delay(det: Detection, multiplier: int, row_calls: int = 0,
                        entries: Optional[List[tuple]] = None,
                        ptr: int = 0, attack_call: int = 1,
                        record: Optional[int] = None,
                        duration_onset: bool = False) -> Optional[int]:
    """`vibdelay` the classic loop's own gate asks for, or None.

    detect._find_vibrato_gate reads the compare in front of the store. Its
    operand is a count of the PLAYER's frames and `vibdelay` counts our
    calls, so the target is `gate x multiplier` calls after the note:

    * "counter" (dialect A): frames since the note fetch; the store is
      skipped while the age is below the operand, so the oscillator is
      silent for exactly that many frames and runs from frame `gate` -- a
      delay, which is what `vibdelay` is. It is spent one per effect call
      (`_effect_calls`) and greloc stores it less one (greloc.c:780), so the
      oscillator first runs on effect call number `vibdelay`: the delay is
      the effect calls before the target, plus one. Without the wavetable
      this is the tick-0 count alone, an upper bound; `build_sng` refines it
      per record once the wavetable is laid out (`_classic_gate_refine`).

      **The target is counted from the call the attack is SEEN on**, which
      is what the original's gate is counted from (its fetch frame). With
      the default test-bit firstwave that is call 1, not the init call:
      Pandora's trace shows `0DD1/09` on the init frame and the note's own
      `/41` a frame later, where siddump names the attack. So the target is
      call `gate x multiplier + attack_call`, `attack_call` 1 for
      FIRSTWAVE_TESTBIT and 0 for a record writing its real waveform
      (`--no-test-restart`, `real_firstwave_instruments`). Measured
      (C:/t/classic-vibrato-gate/fb, first move after the attack): Food_Feud
      536 notes at frame 9 against the original's 398 at 9 and 99 at 10;
      ACE_II 374 at 4, 58 at 5 against 317 and 93; Star_Paws 308 at 15
      against 13 at 15. Counting from the init call instead put a third of
      Food_Feud's notes a frame early (176 at 8).
    * "duration" (dialect B): the note's stored length; a note shorter than
      the operand never vibrates, and one that qualifies vibrates from its
      first frames. That is a THRESHOLD, not a delay, and it returns None
      here: a delay of the operand's length was tried (the triangle engine's
      approximation) and moved the wrong notes -- Sanxion (gate 3, -S1)
      `vib` 0.887 -> 0.872, away from 1, its 53 late-onset notes pushed from
      frame 4 to frame 6 where the original has 2 notes starting at 6, and
      Tarzan (gate 3) flat (C:/t/classic-vibrato-gate/fb, 2026-09-30).
      The reading stays on Detection for the per-note form
      (`_vibrato_command_pass`'s shape) that can say "only notes this long".

    None -- keep the frame-1 floor -- where nothing was read: no compare
    (Sigma_Seven, whose load is dead), or an operand detect leaves UNREAD
    (0, 240, 254: Ricochet, Skate_or_Die_intro, Thundercats). Those are not a
    gate of 0 and not a default, and must not become either until the
    players are disassembled past the compare.

    **Per record where the player rewrites the operand** (detect's
    VIBRATO_GATE_STORE_SHAPE: Thundercats, Mega_Apocalypse, Star_Paws, and
    the held Arcade_Classics, BMX_Kidz, Ricochet, Skate_or_Die_intro): the
    gate is `vg.gate_for(record)`, record `i` counted from instr_start, and
    None without a record. **A per-record gate of 0 is a gate of 1**: the
    age the compare sees was never below 1 in the trace, so `CMP #0` and
    `CMP #1` skip the same frames -- on Star_Paws record 10 (gate 0) every
    compare passes and the lowest age among them is 1, the same first age
    as record 4 (gate 1) (C:/t/selfmod-vibrato-gate/runtime_trace.txt).
    No static operand is 0 (detect reads it as UNREAD), so this reaches
    only the stored table.
    """
    target = _gate_target_call(det, multiplier, attack_call, record,
                               duration_onset)
    if target is None:
        return None
    # **Nearest effect call, not the next one.** vibdelay can only start the
    # oscillator ON an effect call, and a program that holds the frequency
    # over the target (a wavetable step, a tick 0) leaves no call there. The
    # next one can be two frames late: Pygmies_Revenge's `21/00 02/80 41/00`
    # at -S1 withholds calls 4 (tick 0) and 5 (the `41/00`), so "first effect
    # call at or after 4" is call 6, where call 3 is one early. Ties go late,
    # so the oscillator never starts further before the original's than
    # after it.
    calls = _effect_call_list(entries, ptr, target + 0x100, row_calls)
    before = [c for c in calls if c < target]
    after = next((c for c in calls if c >= target), None)
    delay = len(before) + 1
    if before and (after is None or target - before[-1] < after - target):
        delay = len(before)
    return min(0xFF, max(1, delay))


def _classic_gate_refine(det: Detection, vib_ptrs: dict,
                         entries: List[tuple], wave_starts: List[int],
                         multiplier: int, row_calls: int,
                         instr_row_calls: Optional[dict] = None,
                         lead: int = 1, no_test_restart: bool = False,
                         real_firstwave_instruments: tuple = (),
                         duration_onset: bool = False) -> dict:
    """`vib_ptrs` with each record's counter-gate delay taken against its own
    wavetable program -- the half `_vibrato_layout` cannot know, because the
    wavetable is laid out after it. Unchanged where no counter gate was read.

    No frame-1 floor here: the target is frame `gate`, which is past frame 0
    by construction for every operand read (3..19 static; 1 and up from a
    per-instrument table, its 0 read as 1), so the floor's reason --
    keep the oscillator off the attack frame -- is already met, and applying
    it on top would postpone a record whose program withholds the calls.
    """
    mult = max(1, multiplier)
    if not vib_ptrs or not _gate_reachable(det, duration_onset):
        return vib_ptrs
    out = {}
    for i, (idx, delay) in vib_ptrs.items():
        ptr = (wave_starts[i + lead]
               if wave_starts is not None and i + lead < len(wave_starts) else 0)
        # Goattracker number, as `_write_instruments` keys it (i + lead + 1).
        own = (instr_row_calls or {}).get(i + lead + 1, row_calls)
        # Same test as `_write_instruments`' firstwave byte.
        real = no_test_restart or (i + lead + 1) in real_firstwave_instruments
        attack = 0 if real else 1
        got = _classic_gate_delay(det, mult, own, entries, ptr,
                                  attack_call=attack, record=i,
                                  duration_onset=duration_onset)
        if (got is not None
                and _counter_gate_call(det, mult, attack, i) is None):
            # An onset target (`_onset_engine`), not a gate: worth taking
            # only where nothing re-pitches the note after the oscillator
            # starts. A program that writes the frequency on a later step
            # (a waveform-changing one, Deep_Strike's `41/00 01/80 11/00
            # 01/80 41/00`) zeroes `vibtime` there, so an earlier start
            # sounds one blip and then restarts from the note.
            target = _gate_target_call(det, mult, attack, i, duration_onset)
            calls = _effect_call_list(entries, ptr, target + 0x100, own)
            start = calls[got - 1] if 0 < got <= len(calls) else None
            if start is None or _repitch_after(entries, ptr, start,
                                               target + 0x100):
                got = None
        out[i] = (idx, delay if got is None else max(1, got))
    return out


def _repitch_after(entries: Optional[List[tuple]], ptr: int, start: int,
                   calls: int) -> bool:
    """Whether a wavetable step from `ptr` writes the frequency on a call
    after `start` (and before `calls`), walked as `_effect_call_list`
    walks it."""
    wavetime = 0
    for c in range(1, calls):
        if not entries or not 0 < ptr <= len(entries):
            return False
        wave, note = entries[ptr - 1]
        if wave <= GT_WAVE_LAST_DELAY and wavetime != wave:
            wavetime += 1
            continue
        wavetime = 0
        ptr += 1
        if ptr <= len(entries) and entries[ptr - 1][0] == GT_WAVE_JUMP:
            ptr = entries[ptr - 1][1]
        if (c > start and note != GT_WAVE_NO_NOTE
                and not GT_WAVE_FIRST_CMD <= wave <= GT_WAVE_LAST_CMD):
            return True
    return False


def _step_calls(entries: List[tuple], ptr: int, calls: int) -> dict:
    """`{entry index (0-based): the call its right side is read on}` for a
    program from `ptr` (1-based) over calls 1..`calls - 1`, walked exactly
    as `_effect_call_list` walks it: a delay step is read on its last call,
    and the note's call 0 runs no wavetable."""
    out: dict = {}
    wavetime = 0
    for c in range(1, calls):
        if not 0 < ptr <= len(entries):
            break
        wave = entries[ptr - 1][0]
        if wave <= GT_WAVE_LAST_DELAY and wavetime != wave:
            wavetime += 1
            continue
        wavetime = 0
        out.setdefault(ptr - 1, c)
        ptr += 1
        if ptr <= len(entries) and entries[ptr - 1][0] == GT_WAVE_JUMP:
            ptr = entries[ptr - 1][1]
    return out


def _gate_start_call(calls: List[int], target: int) -> Optional[int]:
    """The effect call `_classic_gate_delay` starts the oscillator on for
    `target`: the nearest of `calls`, ties going late. None with no calls."""
    before = [c for c in calls if c < target]
    after = next((c for c in calls if c >= target), None)
    if before and (after is None or target - before[-1] < after - target):
        return before[-1]
    return after


def _free_gate_calls(det: Detection, vib_ptrs: dict,
                     entries: List[tuple], blocks: List[tuple],
                     multiplier: int, row_calls: int,
                     instr_row_calls: Optional[dict] = None,
                     lead: int = 1, no_test_restart: bool = False,
                     real_firstwave_instruments: tuple = (),
                     swelling=(), log=None,
                     duration_onset: bool = False) -> tuple:
    """`(entries, freed)`: the wavetable with each counter-gated record's
    plain program giving its re-pitching steps back to the effects, where
    the program would otherwise hold the frequency over the gate's call.

    **The plain program withholds the first three calls of every note.**
    `[wave/00, tail/00, tail/00, FF/00]` (`_wavetable_entries`' fall-through
    shape, five entries with the stop padding): each `/00` step writes the
    note's frequency and skips the continuous effects (player.s `bne
    mt_wavefreq` past `mt_wavedone`; gplay.c `goto PULSEEXEC`), so the
    instrument vibrato can start no earlier than call 4 -- frame 3 after the
    attack siddump names -- whatever `vibdelay` says. Only the FIRST step
    has to set the pitch; the other two re-write the same note. Where the
    record's gate (`_counter_gate_call`) asks for a call the program
    withholds, those later steps are respelled `/80` ("no frequency
    change", the right side `_effect_call_list` already reads), the
    waveform writes stay, and `_classic_gate_refine` then places
    `vibdelay` on the gate's call against the freed program. Mega_Apocalypse
    records 12 and 15 (stored gate 0, read as 1): the original moves at age
    1-2, ours at 3 on every note.

    Only a program of delay steps and ONE waveform (the gate bit aside),
    every right side `$00` or `$80`, ending in a stop (`FF/00`) is
    touched: a jump loops, any other right side is a note of its own, and
    a program changing waveform is a byte-code interpreter's, which
    writes `$D401` itself (`_wave_program_entries`; ACE_II record 9's
    `41/00 01/80 43/00 07/80 41/00`) -- and only where freeing moves
    the oscillator's start strictly nearer the target; a record whose gate
    already falls past the program (records 3 and 10, gates 6 and 12)
    keeps its bytes. `blocks` is `(record, ptr)` per program to consider,
    `ptr` 1-based; `freed` is the records whose program changed.

    **A swelling record keeps the step on its first hold row's call.**
    `swelling` names the records `_expanding_vibrato_pass` commands hold
    rows for (`_expanding_vibrato_records`), and a `4xy` changes the speed
    entry without resetting the oscillator's phase (player.s
    `mt_tick0_34` stores the parameter only; `mt_tick0_12`, the
    portamentos, is what clears `mt_chnvibtime`). Freed all the way, the
    instrument's shallow level ran two calls into its triangle before the
    first hold row's deeper one took over, and the swing ran off-centre:
    Mega_Apocalypse `$0B08` (record 15) from the attack `0 472 472 -472
    -1416 -1416 -2360 -1416`, a semitone flat on average, against the
    original's `0 295 590 423 0 -551 -1102`. The program's own re-pitch on
    that call (a `/00` step writes the frequency AND zeroes `vibtime`) is
    the reset the level change needs, so for these the program's LAST
    step, and every step from the first hold row's call on, stays `/00`;
    only the steps before it inside the note's row are freed: `0 472 0
    944 0 0 -944`, the onset on the original's frame and the swell from
    there exactly as before. (At -S2's 4-call rows -- Ricochet, Skate or
    Die -- the whole program is inside the note's row, and the last step
    is the latest reset the program has.)
    """
    mult = max(1, multiplier)
    if not vib_ptrs or not _gate_reachable(det, duration_onset):
        return entries, []
    out = list(entries)
    freed: List[int] = []
    for i, ptr in blocks:
        if i not in vib_ptrs or not vib_ptrs[i][0] or not 0 < ptr <= len(out):
            continue
        gt_number = i + lead + 1
        real = no_test_restart or gt_number in real_firstwave_instruments
        target = _gate_target_call(det, mult, 0 if real else 1, i,
                                   duration_onset)
        if target is None:
            continue
        span = []
        k = ptr - 1
        while k < len(out) and out[k][0] != GT_WAVE_JUMP:
            span.append(k)
            k += 1
        if (not span or k >= len(out) or out[k][1] != 0
                or out[span[0]][0] <= GT_WAVE_LAST_DELAY
                or out[span[0]][1] != 0x00
                or any(out[j][0] >= GT_WAVE_FIRST_CMD
                       or out[j][1] not in (0x00, GT_WAVE_NO_NOTE)
                       or (out[j][0] > GT_WAVE_LAST_DELAY
                           and (out[j][0] ^ out[span[0]][0]) & 0xFE)
                       for j in span)):
            continue
        own = (instr_row_calls or {}).get(gt_number, row_calls)
        on_call = _step_calls(out, ptr, len(span) * 0x10 + 2)
        trial = list(out)
        for j in span[1:]:
            if i in swelling and (j == span[-1]
                                  or on_call.get(j, own) >= own):
                continue                 # the reset before the hold rows
            trial[j] = (trial[j][0], GT_WAVE_NO_NOTE)
        if trial == out:
            continue
        horizon = target + 0x100
        was = _gate_start_call(_effect_call_list(out, ptr, horizon, own),
                               target)
        now = _gate_start_call(_effect_call_list(trial, ptr, horizon, own),
                               target)
        if now is None or (was is not None
                           and abs(now - target) >= abs(was - target)):
            continue
        out = trial
        freed.append(i)
    if log and freed:
        log(f"Gate calls freed........: record(s) "
            f"{', '.join(f'${r:02X}' for r in sorted(set(freed)))} -- the "
            "program's re-pitching steps no longer hold the vibrato past "
            "its gate")
    return out, freed


def _vibrato_delay(det: Detection, multiplier: int,
                   commanded: bool = False, row_calls: int = 0,
                   record: Optional[int] = None) -> int:
    """Goattracker `vibdelay` for this player's vibrato, in play calls.

    `vibdelay` is a countdown, not a flag: gplay.c:769-776 is a fallthrough
    from `CMD_DONOTHING`, breaking while `vibdelay > 1` and decrementing once
    per call, so the oscillator first runs on the `vibdelay`-th call after the
    note. 1 means "from the first call" and 0 means "never".

    The LFO-table player gates nothing, so it keeps `VIBRATO_DELAY`. **The
    classic players do gate** -- this sentence said they did not until the
    gate was read (detect._find_vibrato_gate): 54 of the 55 corpus files the
    classic split resolves in carry a compare after the centring subtraction,
    in two forms, and `_classic_gate_delay` says which one a delay can
    express. **The global-triangle player does gate, but not with a
    delay** -- and the difference is worth stating precisely, because a delay
    is what it looks like:

        BD EF 14  LDA $14EF,X    ; the note's raw pattern status byte
        29 1F     AND #$1F       ; ...its duration field
        C9 08     CMP #$08
        90 1C     BCC out        ; duration < 8 -> no vibrato on this note

    `$14EF,X` is written once per note (`LDA ($FD),Y / STA $14EF,X` at $10A2)
    and never incremented or decremented anywhere in the player, so this is a
    *per-note length threshold* decided before the note sounds, not a counter
    running during it. Nothing in a Goattracker instrument can express "only
    notes at least this long", because `vibdelay` is per instrument.

    What `vibdelay` reproduces exactly is the half that matters here: a note
    shorter than the delay **ends before the oscillator ever starts**, so
    setting the delay to the threshold suppresses vibrato on exactly the notes
    the player suppresses it on. The threshold is 8 of the player's frames and
    `vibdelay` counts our calls, so it scales by `multiplier` like every other
    rate in this file (see _drum_speed).

    The half it does not reproduce: on a note long enough to qualify, the
    player oscillates from its first frame where this starts at frame 8. So
    long notes are under-vibratoed at the head. That is the opposite error from
    applying the effect to every note regardless of length, and much the
    smaller one -- before this, a corpus where most notes are shorter than the
    threshold got vibrato on all of them.

    **This is the fallback, not the mechanism, since v0.5.199** -- see
    `_vibrato_command_pass`, which expresses the gate per note and reaches both
    halves. What stays here is the approximation for the notes it cannot reach,
    and the gate it uses depends on which of the two is running:

    * On its own, `TRIANGLE_VIBRATO_GATE` (8), even in the five files whose
      player compares against something else. A delay is doing two jobs at once
      -- suppressing short notes and postponing long ones -- and the file's own
      threshold is the right number only for the first. Substituting it here
      drops corpus agreement from 85.5% to **78.9%**, more than doubling the
      spurious vibratos (207 to 417): a lower threshold gives up the
      suppression without buying a correct onset.
    * Behind the command pass, **no delay at all** (v0.5.294). v0.5.198
      compared the file's own threshold against the constant 8 here -- two
      ways of delaying -- and chose between them at 92.1% against 90.3%.
      Neither is right. The commands already write CMD_VIBRATO on the notes
      that qualify and a suppressing 0 on the rest, so any delay postpones the
      notes they just enabled: Chimera's GT 6 has eight commanded-on notes, no
      uncommanded ones, and traced zero reversals against the original's 98,
      because the oscillator's half-period is `cmp + 2` = 4 calls and the delay
      was 8. Measured over the 25 files of this dialect, `vib` moves on 20 and
      **19 of them closer to 1.0**, median distance in log space 0.795 ->
      0.668, with no other column moving.

    The constant is therefore right as a plain delay and has no role behind
    the commands, which is why `commanded` is a parameter and not a
    convenience.

    v0.5.198 measured that last sentence rather than asserting it, across the
    25 corpus files this gate reaches, over 2487 notes of instruments whose
    only pitch movement is the vibrato (no drum or arpeggio bit). The original
    moves 435 of them. Two axes, and they oppose each other:

        gate   moves/still agrees   still notes we wobble   onset late (median)
           1                65.9%              826 of 2052                   +0
           8                85.5%                      207                  +10
          12                88.6%                      114                  +15

    So `vibdelay 1` catches 413 of the 435 but wobbles 40% of the notes that
    should be still, and 8 catches 282 and is 10 frames late on them. The
    pervasive spurious wobble is the more audible error, which is what makes 8
    the closer -- not that it scores highest. **12 scores highest and is not
    shipped**: the moves/still axis cannot see the 5 extra frames of lateness
    it costs, it plateaus at 14 because it saturates rather than peaks, and
    late onset is the defect a listener actually reported. Do not raise this
    constant on the strength of that column alone. 8 is also the player's own
    threshold, so it is the one value here that is read rather than fitted.

    Getting both halves needs the gate expressed per *note*, which means a
    pattern-level vibrato command on qualifying notes with `vibdelay 1`. That
    is what `_vibrato_command_pass` does, and this function stopped fighting
    it in v0.5.294 -- the sentence had been here since v0.5.199 while the code
    below still delayed.
    """
    if det.triangle_vibrato is None:
        # **The classic engine delays past frame 0; the LFO table does not.**
        # Halving `rshift` doubles the swing, and on its own that renames the
        # attack -- siddump names a note from the frequency on the frame the
        # gate rises, and a swing near a semitone has already moved it by then.
        # That route was refuted twice (v0.5.129, v0.5.367) at a cost of
        # melody 0.986 -> 0.299 on One_on_One_Jordan_vs_Bird alone. Delaying
        # the oscillator until frame 0 is over removes the CAUSE: the attack
        # keeps the note's own pitch, so the deeper swing is free. `multiplier`
        # calls are frame 0, so `multiplier + 1` is its first call of frame 1.
        #
        # Scoped to the classic engine because that is the population the
        # depth deficit was measured on, and because the LFO table's entry is
        # documented as starting ON the note
        # (tests/test_table_vibrato.py::test_the_entry_is_note_relative_and_starts_on_the_note).
        if det.vibrato_offset is not None:
            floor = max(VIBRATO_DELAY, multiplier + 1)
            gate = _classic_gate_delay(det, multiplier, row_calls,
                                       record=record)
            return floor if gate is None else min(0xFF, max(floor, gate))
        return VIBRATO_DELAY
    if commanded:
        # **The commands express the gate; the delay must not express it
        # again.** `_vibrato_command_pass` writes CMD_VIBRATO on the notes
        # that qualify and a suppressing 0 on the rest -- on Chimera 264
        # enables against 1864 suppressions, and its GT 6 has *no*
        # uncommanded note at all. Leaving `vibdelay` at the threshold then
        # postpones the enabled notes too: the oscillator's half-period here
        # is `cmp + 2` = 4 calls, so 8 calls of delay costs a note its whole
        # first swing, and that instrument traces zero reversals against the
        # original's 98.
        #
        # This is what the docstring above has always said the design needs
        # ("with `vibdelay 1`"). The 92.1%-against-90.3% measurement it cites
        # compared the file's own threshold against the constant 8 -- two
        # ways of delaying -- and never asked what not delaying scores.
        return VIBRATO_DELAY
    return min(0xFF, max(1, TRIANGLE_VIBRATO_GATE * multiplier))


def _triangle_vibrato_entry(byte: int, multiplier: int,
                            row_calls: int = 0) -> Optional[tuple]:
    """Speed-table entry for the global-triangle dialect's shift-count byte.

    The player (detect._find_triangle_vibrato, 25 corpus files) does

        frequency = note + phase x (interval_at_note >> (byte + 1))

    with `phase` the folded triangle `0,1,2,3,3,2,1,0` off a counter stepped
    once per play call. Both halves of the mapping come from *simulating*
    gplay.c:795-801 rather than reading its constants, which is the discipline
    § 7.ll exists to enforce. Simulated, Goattracker's oscillator obeys two
    exact laws:

        period       = 2 * cmp + 4   play calls
        peak-to-peak = (cmp + 2)     * speed

    (the first restates the documented `cmp + 2` half-period, which is what
    makes the simulation trustworthy rather than novel.)

    * **Period.** The player's counter steps once per *frame* and eight steps
      make a cycle, so its half-period is `TRIANGLE_VIBRATO_PERIOD / 2` = 4
      frames. Goattracker's is `cmp + 2` *calls*, i.e. `(cmp + 2) / multiplier`
      frames. Hence

          cmp = (PERIOD / 2) * multiplier - VIBRATO_CMP_BIAS

      which is the classic mapping's own formula at a fixed bound of 4 -- this
      dialect simply has no per-instrument period to read.

    * **Excursion.** The player's phase runs `0..PEAK`, so its peak-to-peak is
      `PEAK * (interval >> (byte + 1))`; it is one-sided, the note sitting at
      the bottom of the swing rather than the middle, exactly as the classic
      player's is one-sided the other way. Equating peak-to-peak with
      `(cmp + 2) * speed = PERIOD/2 * multiplier * speed` and
      `speed = interval >> rshift`:

          rshift = byte + 1 + log2(multiplier) + log2((PERIOD / 2) / PEAK)

      `log2(4/3)` is 0.415, and `round(k + 0.415) == k` for any integer k, so
      for a power-of-two multiplier the emitted shift is `byte + 1 +
      log2(multiplier)` -- coincidentally the classic mapping's expression,
      reached from different quantities.

    **That coincidence holds ONLY at 1, 2, 4, 8 ... and the code used to
      round the wrong quantity** (`game-killer-triangle-depth`, 2026-10-09;
      figures historical). The shift was `byte + 1 + round(log2(multiplier))`:
      the 0.415 was dropped before rounding, not after. At `-S9`
      (Game_Killer, the one corpus file whose multiplier it changes: 1, 2
      everywhere else) `log2(9) = 3.17` rounded to 3, a division by 8 where
      the derivation wants 12 (`9 * 4/3`), so the swing was `36/8 = 4.5`
      depths against the player's 3: **1.50x**. Rounding the whole quantity,
      `round(log2(multiplier * (PERIOD / 2) / PEAK))` = `round(3.585)` = 4,
      gives `36/16 = 2.25` depths, **0.75x**, the nearer of the two in log
      space (0.415 against 0.585). The 1.50x was measured, not only
      predicted: `fidelity.py --vice` (a per-call trace, which the siddump
      depth column is not -- it keeps one call in nine at `-S9`) reads
      Game_Killer's vibrato record 8 at 0.0323 of the pitch against the
      original's 0.0217, 1.49x. The siddump column read 1.27x for the same
      record and so under-read the defect.

    **The residual is a systematic error in depth, and it is the format's, not
    a slip.** Goattracker's note-relative speed can only be `interval >> k`,
    a power of two; the player wants three of them (times the multiplier).
    The nearest expressible ratio is at most 2^0.5 off in either direction --
    4/3 at a power-of-two multiplier, where it is too deep; 3/4 at `-S9`,
    where it is too shallow. Correcting it would need the absolute speed form,
    which does not track pitch the way this player does, so the depth is
    traded for the pitch-tracking. The period is NOT traded: `cmp` keeps the
    original's rate exactly, as above.

    **Tick 0.** The packed player runs no continuous effect on the first call
    of a row (`REALTIMEOPTIMIZATION`, player.s `mt_wavedone`: `lda
    mt_chncounter,x / beq`), so of a `row_calls`-call row only `row_calls - 1`
    calls step the counter -- on a 2-call CMD_FUNKTEMPO row, one in two. The
    original's counter steps every frame. Uncorrected, a half-period of
    `cmp + 2` EFFECT calls lasts `row_calls / (row_calls - 1)` times longer in
    real time: 5_Title_Tunes subtune 1 (2-call rows, -S1) ran its triangle
    at half the original's rate, and since Goattracker's excursion is fixed by
    `cmp` and `speed` alone, its travel per frame halved too (`bend` 0.68).
    So `half` is scaled by `(row_calls - 1) / row_calls` -- the classic
    mapping's correction, `_classic_vibrato_entry` -- and the shift is then
    taken from the excursion law with the `cmp` actually emitted, in one
    rounding,

        rshift = byte + 1 + round(log2((cmp + 2) / PEAK))

    which is `_triangle_rate_shift` wherever `cmp + 2 == 4 * multiplier`, and
    otherwise pays back the depth the shorter half-period took. Paying it
    back on top of the uncorrected shift instead rounds twice and is worse
    wherever the two differ: -S2 3-call rows get 5/3 of the excursion where
    this form gives 5/6. At 2-call rows, -S1, that is `cmp` 0 and the shift
    one less: the period is the original's and the excursion keeps the
    format's 4/3. At 3-call rows (-S1) `cmp + 2` is 3 and the excursion is
    the player's exactly; at -S2's 4-call rows it is 6, and both period and
    excursion are the player's exactly. The held calls themselves cannot be
    given back: on tick 0 the frequency does not move, so ours steps on
    effect calls only, in steps `row_calls / (row_calls - 1)` times larger.

    `row_calls` follows `_classic_vibrato_entry`'s convention -- 0 and 1 do
    not compensate, and the result is then byte-identical to the uncorrected
    mapping. `_vibrato_layout` passes the record's own row where it is
    attributed (`primitives._record_row_calls`: the START subtune's, else the
    shortest -- see there for why not the minimum alone), else the file's.
    """
    if not byte or byte >= TRIANGLE_VIBRATO_MAX_SHIFT:
        # The player's own `BEQ past`, and its own way of switching a record
        # off: a shift this large leaves nothing of the 16-bit interval. No
        # player in the family masks the byte -- Last_V8 stores 81.
        return None
    half = TRIANGLE_VIBRATO_PERIOD // 2 * multiplier
    if row_calls < 2:
        cmp_value = min(0x7F, max(0, half - VIBRATO_CMP_BIAS))
        rshift = min(byte + 1 + _triangle_rate_shift(multiplier),
                     GT_MAX_VIB_SHIFT)
        return (SPEED_NOTE_RELATIVE | cmp_value, rshift)
    half = half * (row_calls - 1) / row_calls
    cmp_value = min(0x7F, max(0, round(half) - VIBRATO_CMP_BIAS))
    depth = round(math.log2((cmp_value + VIBRATO_CMP_BIAS)
                            / TRIANGLE_VIBRATO_PEAK))
    rshift = min(max(byte + 1 + depth, 0), GT_MAX_VIB_SHIFT)
    return (SPEED_NOTE_RELATIVE | cmp_value, rshift)


def _triangle_rate_shift(multiplier: int = 1) -> int:
    """Shift that turns `PEAK * (interval >> (byte + 1))` per frame into the
    entry's `(cmp + 2) * speed` per call: `round(log2(multiplier * (PERIOD / 2)
    / PEAK))`, the whole ratio rounded once. Equal to `_rate_shift` at 1, 2, 3,
    4, 6, 7, 8 and 12; one more at 5, 9, 10 and 11."""
    m = max(1, multiplier)
    return max(0, round(math.log2(m * (TRIANGLE_VIBRATO_PERIOD // 2)
                                  / TRIANGLE_VIBRATO_PEAK)))


def _table_vibrato_entry(byte: int, tv, multiplier: int,
                         row_calls: int = 0,
                         table_span: bool = False) -> Optional[tuple]:
    """Speed-table entry for one instrument byte in the LFO-table format.

    The command-table engine's vibrato is a table walked one entry per frame,
    the offset in frame `i` being `table[i] * count * (interval >> unit)` with
    `count` the parameter byte's low nibble and the table its high one; see
    detect._find_table_vibrato for the routine. All four tables in both corpus
    files are triangles, which is the only reason a fixed triangle can stand
    in for them at all -- an arbitrary shape could not be approximated, and
    this returns None for a table that is not one (peak or length unreadable).

    The table's LENGTH is the whole period in frames, against Goattracker's
    `2 * (cmp + 2)` calls, so matching the period gives

        cmp = length * multiplier / 2 - 2

    and matching the excursion equates the two amplitudes,

        (cmp + 2) / 2 * (interval >> rshift)
            == peak * count * (interval >> unit)

    which the interval cancels out of entirely, leaving

        rshift = log2((cmp + 2) * 2**unit / (2 * peak * count))

    rounded to the nearest integer -- Goattracker's depth is a shift, so only
    powers of two are reachable and the rounding is in log space, where the
    error is multiplicative and symmetric. Hollywood or Bust's seven vibrato
    records ask for ratios of 4, 4, 3, 5.33, 4, 8 and 4 -- five land on a
    power of two exactly and two round, the worst of them by a third.

    Both numbers come from the *simulated* gplay.c semantics (see
    VIBRATO_CMP_BIAS), not from the reading _classic_vibrato_entry above was
    built on. A `cmp` of 0 is a legal entry, not an empty one: `$80` still
    selects the note-relative speed and `cmpvalue & 0x7f` is then 0, which is
    the fastest oscillation Goattracker has -- 4 calls -- and exactly what the
    shortest of the four tables asks for.

    `row_calls` >= 2 scales the half-period by `(row_calls - 1) / row_calls`
    for the packed player's tick-0 effect skip, exactly as
    `_classic_vibrato_entry` does; 0 and 1 leave the entry unchanged.

    One approximation the classic mapping has and this does not: the player
    takes the interval *above* the note here (`freq(note+1) - freq(note)`),
    which is the one Goattracker computes. What remains is the shape: the
    player's table is a position sequence sampled per frame where Goattracker
    integrates a step per call, so the two triangles agree in period and
    excursion and differ in how they get there whenever the table is not
    symmetric -- table 1 (`0 1 2 1 0 -1`) spends four of its six frames above
    zero.
    """
    count = byte & 0x0F
    index = (byte & 0xF0) >> 4
    if not byte or not count or index >= len(tv.shapes):
        # The player's own test is on the whole byte (`LDA record+5,Y / BNE`
        # at Hollywood or Bust $05D1); a count of zero multiplies the unit by
        # nothing, which is the same silence reached one step later.
        return None
    length, peak = tv.shapes[index]
    if not length or not peak:
        return None
    half = length * multiplier / 2.0
    if row_calls >= 2:
        # The packed player runs no continuous effect on tick 0 of a row
        # (REALTIMEOPTIMIZATION, see _classic_vibrato_entry), so the counter
        # steps on `row_calls - 1` calls in `row_calls`. Same correction,
        # same 0/1 = "do not compensate" convention. The excursion needs no
        # separate term: `ratio` below reads the cmp actually emitted.
        half = half * (row_calls - 1) / row_calls
    half = max(1, round(half))
    cmp_value = min(0x7F, max(0, half - VIBRATO_CMP_BIAS))
    # Goattracker's peak-to-peak is `(cmp + 2) * speed` (the even and the
    # odd `cmp` alike); the player's is the table's span in units. `2 *
    # peak` is that span only for a symmetric table: with `table_span` the
    # span read off the table is matched instead (`TableVibrato.spans`).
    span = 2.0 * peak
    spans = getattr(tv, "spans", ()) or ()
    if table_span and index < len(spans) and spans[index]:
        span = float(spans[index])
    ratio = ((cmp_value + VIBRATO_CMP_BIAS) * (1 << tv.unit_shift)
             / (span * count))
    rshift = min(max(round(math.log2(ratio)), 0), GT_MAX_VIB_SHIFT)
    return (SPEED_NOTE_RELATIVE | cmp_value, rshift)


def _vibrato_layout(sid: SidFile, det: Detection, instr_used: int,
                    vibrato: bool, fmt: str, multiplier: int,
                    speed_table: List[tuple], log=None,
                    lead: int = 1, vibrato_command: bool = False,
                    row_calls: int = 0, effects: bool = False,
                    gate_skip: Optional[int] = None,
                    instr_row_calls: Optional[dict] = None,
                    table_span: bool = False) -> dict:
    """{instrument index: (speed-table index, vibdelay)} for `--vibrato`.

    `gate_skip` is the reload `O` of an outer gate that is the play routine's
    first instruction with nothing else on its underflow call -- `build_sng`
    passes `outer_gate_skip(sid)` for a player `call_phase.entry_gate`
    accepts with `dispatch=True` (through a subtune dispatch in front of
    the gate: Formula_1_Simulator, task formula-1-lead-vibrato), None for
    every other.

    `table_span` matches the LFO table's own peak-to-peak
    (`TableVibrato.spans`) rather than `2 * peak` (`_table_vibrato_entry`). Such a player runs the classic update on
    `O` calls in `O + 1`, so one update lasts `(O + 1) / O` frames
    (`_classic_vibrato_entry`). A gate that guards only the pattern clock
    leaves the update running every frame, which is why the reload alone is
    not the question.

    **A fixed-interval arpeggio record gets no vibrato where its mask is a
    duty cycle.** The player's octave block writes the frequency from the
    note table on every call, after the vibrato has moved it, so an
    arpeggiating note never sounds a vibrato in the original: MEASURED at
    v0.5.489 on a 30 s siddump, 0 frames off the base or octave pitch in
    3278 arp-note frames (Zoids) and 1581 (Master_of_Magic). Goattracker
    runs the instrument vibrato and `CMD_VIBRATO` on every call the
    wavetable does not write a note on (gplay.c, a note entry `goto
    PULSEEXEC`s past TICKNEFFECTS and zeroes `vibtime`; a delay entry `goto
    TICKNEFFECTS`). The parity mask's shapes write a note on every call and
    silence it that way; `fixed_arp_duty_entries` holds its runs on delay
    entries, and with the vibrato left in the first cut put 600 vibrato
    frames on Zoids' arp notes against the original's 0 (`bend` 0.91 ->
    8.13). So such a record is skipped here, which also keeps it out of
    `_vibrato_command_pass` and `_expanding_vibrato_pass`, both of which
    read this dict. Gated on `effects` like every other read of the +7
    byte, and on the duty mask, so the parity files' bytes do not move.

    Goattracker runs a per-instrument vibrato with no pattern command at all:
    on every new note `gplay.c:352-354` loads `cptr->vibdelay = iptr->vibdelay`
    and `cptr->cmddata = iptr->ptr[STBL]`, and a channel whose command is
    CMD_DONOTHING falls through into CMD_VIBRATO once the delay expires
    (gplay.c:769-780). Those are instrument-record bytes 5 and 6, and this
    writer has always written `0x00, 0x00` there -- which is why no file it has
    ever produced vibrates, and why a third of the corpus moves the pitch not
    at all where the original does.

    Two player engines reach this, and they share no byte format: the classic
    $78-bound/$07-shift pair (56 corpus files, _classic_vibrato_entry) and the
    command-table engine's LFO table (2 files, _table_vibrato_entry). Both end
    at the same place -- a note-relative speed-table entry and a vibdelay --
    and the derivation of each is in its own function.

    `row_calls` is passed to all three engines. The packed player's tick-0
    effect skip (see _classic_vibrato_entry) applies to *every* vibrato it
    runs. The global-triangle entry takes the record's own row,
    `instr_row_calls` keyed by Goattracker number (`i + lead + 1`, as
    `_write_instruments` keys it), falling back to `row_calls`. **Which row is
    the start subtune's where it plays the record, not the minimum**: the
    entry is a function of the row, not a safety bound, and the minimum
    over-corrected a record the tune plays at 4-call rows and a funk subtune
    at 2 (Human_Race instrument 1, `vib` 1.251 against 1.004); see
    _triangle_vibrato_entry.

    GTS5 only. A GTS2 file stores no speed table -- its loader packs the
    vibrato into a single instrument byte and calls makespeedtable itself
    (gsong.c:285), and it reads bytes 5 and 6 the other way round
    (vibdelay first, gsong.c:284) -- so the same numbers would need a
    different encoding, and the byte-exact fixture is a GTS2 file.
    """
    if not vibrato or fmt != FORMAT_GTS5:
        return {}
    mult = max(1, multiplier)
    if det.vibrato_offset is not None:
        offset = det.vibrato_offset
        entry_of = lambda b, i: _classic_vibrato_entry(
            b, mult, row_calls, gate_skip=gate_skip, dwell=det.vibrato_dwell,
            depth_extra=det.vibrato_shift_extra)
        engine = "bound/shift"
    elif det.table_vibrato is not None:
        offset = det.table_vibrato.offset
        entry_of = lambda b, i: _table_vibrato_entry(
            b, det.table_vibrato, mult, row_calls, table_span=table_span)
        engine = "LFO table"
    elif det.triangle_vibrato is not None:
        offset = det.triangle_vibrato
        entry_of = lambda b, i: _triangle_vibrato_entry(
            b, mult, _record_row_calls(instr_row_calls, i + lead + 1,
                                       row_calls))
        engine = "global triangle"
    else:
        return {}
    delay = _vibrato_delay(det, mult, commanded=vibrato_command,
                           row_calls=row_calls)
    # A gate the player stores per instrument (detect.VibratoGate.table) is
    # a delay per record; every other file has one delay for all of them.
    per_record = (det.vibrato_gate is not None
                  and det.vibrato_gate.table is not None)
    data = sid.data
    duty_mask = (_gw_primitives.fixed_arp_mask(sid, det)
                 if effects and det.arp_fixed_up and det.effect_arp else None)
    if duty_mask is not None and duty_mask[0] == FIXED_ARP_PARITY_MASK:
        duty_mask = None
    out: dict = {}
    overwritten = 0
    for i in range(max(instr_used - lead, 0)):
        base = det.instr_start + i * det.instr_stride + offset
        if base >= len(data):
            continue
        effect = det.instr_start + i * det.instr_stride + 7
        if (duty_mask is not None and effect < len(data)
                and data[effect] & 0x04):
            overwritten += 1
            continue
        entry = entry_of(data[base], i)
        if engine == "bound/shift":
            entry = _depth_trimmed(getattr(sid, "name", ""), i, entry)
        if entry is None:
            continue
        if entry not in speed_table:
            if len(speed_table) >= _gw_constants.GT_MAX_TABLELEN:
                continue
            speed_table.append(entry)
        out[i] = (speed_table.index(entry) + 1,
                  _vibrato_delay(det, mult, commanded=vibrato_command,
                                 row_calls=row_calls, record=i)
                  if per_record else delay)
    if log and out:
        log(f"Instrument vibrato......: {len(out)} of "
            f"{max(instr_used - lead, 0)} record(s), "
            f"{len({v[0] for v in out.values()})} speed-table entry(ies) "
            f"({engine})"
            + (f", {overwritten} arpeggio record(s) the octave block "
               f"overwrites" if overwritten else ""))
    return out
