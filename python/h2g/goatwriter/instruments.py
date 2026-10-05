"""Header, instrument records and their field bytes (split out of goatwriter.py, text moved unchanged)."""
from __future__ import annotations

from typing import (List, Optional)

from ..detect import (Detection)
from ..sidfile import (SidFile)
from .constants import (DEFAULT_FORMAT, EFFECT_PER_FRAME, FIELD_LEN,
                        FIRSTWAVE_GATE_ONLY, FIRSTWAVE_TESTBIT, FORMAT_GTS2,
                        HEADER_LEN, MAX_INSTRUMENTS, WAVE_ENTRIES_PER_INSTR)
from . import constants as _gw_constants
from . import hard_restart as _gw_hard_restart
def _table_length_byte(entries: int, what: str) -> int:
    """Length byte for a wave/pulse table, refusing to silently wrap.

    The original masked with & 0xFF, which turns an over-long table into a
    plausible-looking short one -- Goattracker then reads the remainder as
    whatever section follows. Fail loudly instead.
    """
    if not 0 <= entries <= _gw_constants.GT_MAX_TABLELEN:
        raise ValueError(
            f"{what} table needs {entries} entries, exceeding Goattracker's "
            f"MAX_TABLELEN ({_gw_constants.GT_MAX_TABLELEN})"
        )
    return entries


def _padded_name_bytes(name: str, width: int = 16) -> bytes:
    raw = name.encode("latin-1", errors="replace")[:width]
    return raw + bytes(width - len(raw))


def _field_bytes(text: str) -> bytes:
    raw = text.encode("latin-1", errors="replace")[:FIELD_LEN]
    return raw.ljust(FIELD_LEN, b"\x00")


def _build_header(sid: SidFile, fmt: str = DEFAULT_FORMAT) -> bytearray:
    header = bytearray(HEADER_LEN)
    header[0:4] = b"GTS2" if fmt == FORMAT_GTS2 else b"GTS5"
    header[0x04:0x04 + FIELD_LEN] = _field_bytes(sid.name)
    header[0x24:0x24 + FIELD_LEN] = _field_bytes(sid.author)
    header[0x44:0x44 + FIELD_LEN] = _field_bytes(sid.released)
    return header


def _instruments_used(det: Detection, log=None, lead: int = 1) -> int:
    """How many instrument slots the file will carry, `lead` placeholders included.

    `lead` is 1 for the inherited layout, whose instrument 1 is a hardcoded
    empty "Clear Voice" so the player's record 0 becomes instrument 2, and 0
    for --compact-instruments, which puts record 0 at instrument 1. Goattracker
    reserves no slot of its own: its format stores instruments from 1 and
    treats 0 as "no change" in a pattern column (readme:613, 1386), so the
    placeholder is the VB6 original's convention, not the format's.
    """
    available = det.instr_used + lead
    instr_used = min(available, MAX_INSTRUMENTS)
    if log and available > instr_used:
        # The count itself is bounded at the records (see detect's
        # `_bound_instruments`); what remains here is Goattracker's own
        # ceiling, which the wavetable's one-byte length imposes.
        log(f"*** INSTRUMENT TABLE HAS {available} ENTRIES, ONLY {instr_used} FIT "
            f"(GOATTRACKER WAVETABLE LIMIT) -- {available - instr_used} DROPPED ***")
    return instr_used


def record_envelope(data: bytes, det: Detection, i: int,
                    sustain_exact: bool = False,
                    cut_release: bool = False) -> tuple:
    """The `(ad, sr)` pair instrument slot `i` (0-based record) is written with.

    Factored out of `_write_instruments` so that a pattern row which must
    write the pair itself -- `_tied_instrument_envelopes`, a tied note that
    changes instrument, which Goattracker's TONEPORTA never re-loads -- puts
    the SAME bytes in `CMD_SETAD`/`CMD_SETSR` that the instrument record
    carries, `--sustain-exact` and `--cut-release` included. Two copies of
    this derivation would drift the moment one of them learned something.
    """
    base = det.instr_start + i * det.instr_stride
    ad = data[base + 3]
    sr = data[base + 4]
    if not sustain_exact and sr >= 0xF0:
        # Inherited from the VB6 original (h2g.frm:578-579), whose comment
        # reads "&SSSXRRRR (S=Sustain, R=Release, X=Cut this bit out)".
        # There is no X bit: SID register 6 is SSSS RRRR, four bits of
        # sustain and four of release (6581 datasheet). Clearing $10 lowers
        # a sustain of F to E on every instrument that asked for full
        # sustain -- the level the note holds at for its whole duration.
        # Kept as the default only because the byte-exact Commando fixture
        # encodes it; --sustain-exact reads the register as the SID does.
        sr &= 0xEF
    if (cut_release and det.envelope_cut
            and not data[base + 7] & EFFECT_PER_FRAME):
        # This player ends an untied note by writing 0 to both envelope
        # registers (detect.ENVELOPE_CUT_SHAPES), so the note stops dead
        # and the release nibble in the record is never heard. Copying it
        # into a Goattracker instrument makes it audible, and Goattracker
        # gates off on the same frame the player does -- so the note rings
        # through a gap that should be silence. Measured on Commando, the
        # original's release is 0 on all 7 instruments at every note end
        # while ours carries B, A, F, 9, B, 4 and F.
        #
        # The sustain is left alone: it governs the note while it plays,
        # which is not what the cut destroys.
        #
        # **THE REST OF THE KILL IS NOT EMITTED, AND THAT IS A DECISION,
        # NOT A GAP** (v0.5.480). The player writes $0000 to BOTH registers
        # at the note end, and holds it until the next note; we hold the
        # record's AD and sustain with the release zeroed. Once the gate
        # is off only the release nibble governs the envelope, so the
        # two are the same sound -- and the register difference is what
        # `adsr` scores. Samantha Fox, traced beside the harness's own
        # packed .sid over its 92 s window: of 7200 disagreeing envelope
        # frames, 3492 are both-gates-off with only AD/S differing
        # (inaudible) and 2499 are gate-on with only the release
        # differing (inaudible until the gate drops, which this cut makes
        # silent on both sides); 627 are gate-state disagreements that
        # belong to `gate`; the audible remainder is 582 frames, and
        # `adsr_gated_off_audible` in the row (202) is the harness's own
        # count of the gated-off part of it -- its 3694 gated-off frames
        # are exactly the 3492 + 202 above. The
        # column reads 48% on a file whose envelopes SOUND right.
        # Writing the pair to zero would take a `CMD_SETAD`/`CMD_SETSR`
        # on the row after every note end -- two command slots the row 0
        # clock and every slide already compete for, and two packed bytes
        # per row against greloc.c's 256-byte pattern limit -- for a
        # difference nothing can hear. If that trade is ever wanted, the
        # measurement above is the one to beat.
        #
        # **Per instrument, not per file** (v0.5.201). An instrument
        # whose effect routine runs every frame re-writes the envelope
        # after the cut, so its release survives and is heard. On
        # Commando only records 0, 2, 6 and 8 are cut; the ones
        # carrying the drum bit hold their value across the whole gap,
        # and zeroing their release destroyed the drums -- reported by
        # a listener, and visible in the trace all along. See
        # EFFECT_PER_FRAME.
        sr &= 0xF0
    return ad, sr


def _write_instruments(out: bytearray, sid: SidFile, det: Detection,
                       instr_used: int, pulse_starts: List[int],
                       sustain_exact: bool = False,
                       no_hard_restart: bool = False,
                       filter_ptrs: dict | None = None,
                       vib_ptrs: dict | None = None,
                       lead: int = 1,
                       wave_starts: Optional[List[int]] = None,
                       no_test_restart: bool = False,
                       cut_release: bool = False,
                       multiplier: int = 1,
                       row_calls: int = 0,
                       wide_hard_restart: bool = False,
                       max_hard_restart: bool = False,
                       hard_restart_frames: int | None = None,
                       real_firstwave_instruments: tuple = (),
                       instr_row_calls: dict | None = None) -> int:
    out.append(instr_used)
    # **THIS ONE BYTE COSTS EVERY NOISE RUN ITS FIRST FRAME, and Action Biker
    # is where that was finally measured** (v0.5.453). `FIRSTWAVE_TESTBIT` is
    # $09 -- below $10, so it selects no waveform -- and it occupies the note's
    # FIRST frame. Anything the instrument then does starts on frame 1, so a
    # noise run the player holds for 12 frames reaches the chip as 11.
    #
    # The arithmetic is exact rather than suggestive. Action Biker: 62 runs of
    # 11 against the original's 12, delta -1 on ALL 62, and
    # `our_noise_frames` 682 against 744 -- a deficit of **exactly 62**, one
    # frame per run. Setting `no_test_restart` (so `first` becomes
    # `FIRSTWAVE_GATE_ONLY`) takes `noise_run_agreement` 0.0 -> **1.0000**,
    # `our_noise_frames` 682 -> **744**, i.e. the original's count to the
    # frame, and `wave` 0.9679 -> **1.0000**.
    #
    # **SO `our_noise_frames` < `orig_noise_frames` IS THIS FRAME, NOT AN
    # EMISSION DEFECT -- read the column's deficit as a note count.** Where the
    # original LATCHES its noise select across notes and only toggles the gate
    # (Confuzion's lead), our `$09` breaks the latch for one frame per note,
    # and the column (bit 7 alone, over all frames) charges each one.
    # Re-measured on the tree as found (HEAD 1dde44a, dirty), under presets,
    # through `fidelity.measure()` in-process, against a `no_test_restart`
    # control arm (`C:/t/the-noise-frames-column-char/probe_nf.py`):
    #
    #   file (window)            ours/orig     deficit  = `$09` frames + rest
    #   Confuzion (180 s, -t
    #     --no-window-floor)     8507/8998       491    = 486 + 5 startup
    #   Confuzion (307 s, the
    #     default floor)        13495/14388      893    = 888 + 5 startup
    #   Geoff_Capes (17 s)        284/308         24    =  24 + 0
    #   Rasputin (180 s, -S2)    4864/5454       590    ~ 608 after-noise `$09`
    #
    # Confuzion's 5 is pure startup: the original's noise opens at frame 2,
    # ours' first `$09` at 7 and its noise at 8; with `no_test_restart` the
    # deficit is 5 exactly (14388/14383) and Geoff_Capes' 0 (308/308).
    # Every one of the deficit's frames, lag-aligned, is a frame where ours
    # reads `$09`. **Rasputin is the exception to "exactly":** its COUNT gap
    # closes with `no_test_restart` (5454/5472, -18) but its noise is placed
    # differently frame by frame on both arms (~2900 lag-aligned frames
    # orig-only/ours-only either way), so there the count deficit is the
    # firstwave frame and the PLACEMENT disagreement is a separate question.
    # `no_test_restart` closes the count because `FIRSTWAVE_GATE_ONLY` ($FF)
    # carries bit 7 and the column counts it as noise -- it is no more
    # audible than `$09`. Pinned as arithmetic by
    # `test_the_noise_frame_deficit_is_one_firstwave_frame_per_note_plus_startup`.
    #
    # **AND THE HARD RESTART IS NOT A SUBSTITUTE, refuted twice on this file.**
    # The standing hypothesis was that the twelfth frame is the hard restart
    # written before the next note, i.e. a `HARD_RESTART_FRAMES` question.
    # Measured: enabling the hard restart alone moves the BYTES (sha 51256f22
    # -> 11b0dc90) and not one column -- noise runs, frames, melody, wave,
    # gate all identical. Combined with `no_test_restart` it does not recover
    # melody either (0.4960 in both). A hard restart clears the GATE and
    # leaves the waveform latched at or above $10, so it never gives siddump
    # the sub-$10 frame it needs; that is a different quantity from the test
    # bit and cannot stand in for it.
    #
    # SO THE COST OF REMOVING IT IS A BLINDNESS, NOT A DEFECT: `melody`
    # 1.0000 -> 0.4960 and `sequence` 1.0000 -> 0.4845 while `our_attacks`
    # stays at **291 in every arm**. The notes are all still struck; siddump
    # simply cannot NAME them without a frame below $10 (siddump.c:434-437).
    #
    # **AND THE TWO FIRSTWAVE VALUES SOUND THE SAME -- they differ only in
    # what the INSTRUMENT can see, which is the sharpest way to put the
    # trade.** $09 is gate plus test with a zero waveform nibble; $FF is all
    # four select bits plus test. Both are silent on a real chip, because the
    # test bit holds the oscillator in reset and the select bits AND to
    # silence. But $09 is BELOW $10 and $FF is not, so only the first gives
    # siddump a note boundary. Pinned by
    # `test_the_first_frame_of_every_run_is_spent_on_a_waveform_below_ten`,
    # which asserts the inequality in BOTH directions -- a first version
    # asserted $FF < $10 on my own assumption and failed, which is how this
    # paragraph came to be right.
    # That is why no column can adjudicate this: `nrun` and `wave` say adopt,
    # `melody` says refuse, and `melody`'s refusal is known to be an artefact
    # of the instrument. It wants an ear -- see
    # `action-biker-noise-runs-want-a-listen-because-the-columns-disagree`.
    first = FIRSTWAVE_GATE_ONLY if no_test_restart else FIRSTWAVE_TESTBIT

    if lead:
        # Instrument 1: always the empty "Clear Voice" slot. A voice opening
        # on rests runs under it, so on a 2-call CMD_FUNKTEMPO row (the only
        # source of `row_calls` 2, goatwriter.constants.CMD_FUNKTEMPO) its
        # gatetimer 2 would never be reached by the counter and the voice
        # would never fetch its first note (player.s:1090-1098) --
        # Gerry_the_Germ subtune 2 voice 1 and Auf_Wiedersehen_Monty subtune
        # 12 voice 2 played nothing. 2 everywhere else, as always.
        clear_gate = 0x02 if not row_calls or row_calls > 2 else 0x01
        out += bytes([0x00, 0x00, 0x01, 0x01, 0x00, 0x00, 0x00, clear_gate,
                      first])
        out += _padded_name_bytes("Clear Voice")

    # The digi engine's records are 16 bytes rather than 8. The fields read
    # here -- pulse +0/+1, waveform +2, attack/decay +3, sustain/release +4 --
    # sit at the same offsets in both layouts, so only the stride differs.
    wtable_start = lead * WAVE_ENTRIES_PER_INSTR + 1
    data = sid.data
    n = max(instr_used - lead, 0)  # number of real (non-empty) instruments

    for i in range(n):
        base = det.instr_start + i * det.instr_stride
        ad, sr = record_envelope(data, det, i, sustain_exact, cut_release)
        # From the laid-out table, not from the index: a record before this
        # one may be longer than WAVE_ENTRIES_PER_INSTR (a deep drum sweep),
        # and then the arithmetic is simply wrong. Falls back to the stride
        # for callers that pass no layout.
        wave_ptr = ((wave_starts[i + lead]
                     if wave_starts is not None and i + lead < len(wave_starts)
                     else i * 5 + wtable_start) & 0xFF)
        # Not a stride: a swept instrument's pulse program is longer than a
        # static one's, so the start positions come from the built table.
        pulse_ptr = (pulse_starts[i + lead]
                     if i + lead < len(pulse_starts) else 0) & 0xFF
        # gatetimer bit $80 is Goattracker's "no hard restart" flag
        # (gsong.c:381). Without it, gplay.c:930-937 writes `adparam` -- the
        # editor's HR value, default $0F00 (goattrk2.c:49), baked into the
        # packed player as ADPARAM/SRPARAM (greloc.c:1138) -- into $D405/$D406
        # for one frame before every note. Hubbard's players never do that:
        # $0F00 appears in none of the corpus originals and is the most common
        # ADSR value in every conversion without this flag.
        # The bound is per instrument where the orderlists say so: `row_calls`
        # is the shortest row ANY subtune writes, and an instrument that never
        # sounds in the fast subtune is charged for it anyway. See
        # tracks.instrument_row_calls -- it returns no entry rather than a
        # default wherever the attribution is unsafe, so the file-wide value
        # is what stands in, and a file with one tempo is unchanged.
        # Keyed by the Goattracker number the patterns name, which is
        # `gt_number` below (i + lead + 1). It read `i + lead` -- the slot
        # BEFORE this one -- until the CMD_FUNKTEMPO 2-call row made the
        # slip fatal: an instrument charged its neighbour's 3-call bound
        # keeps gatetimer 2, and a 2-call row's counter never reaches 2
        # (player.s:1090-1098), so its next note is never fetched
        # (Gerry_the_Germ subtune 2: melody 79.6 -> 7.9 before this fix).
        own_row_calls = (instr_row_calls or {}).get(i + lead + 1, row_calls)
        gatetimer = ((0x80 if no_hard_restart else 0)
                     | (_gw_hard_restart._hard_restart_ticks(multiplier, own_row_calls,
                                            wide_hard_restart,
                                            max_hard_restart,
                                            hard_restart_frames) & 0x3F))
        filt_ptr = (filter_ptrs or {}).get(i, 0x00)
        # Bytes 5 and 6 are ptr[STBL] and vibdelay in a GTS5 file
        # (gsong.c:224-225) and the same pair the other way round, packed, in a
        # GTS2 one (gsong.c:284-285) -- which is why they stay 0,0 unless
        # _vibrato_layout produced something, and it only does for GTS5.
        stbl_ptr, vib_delay = (vib_ptrs or {}).get(i, (0x00, 0x00))
        # The player's own first frame is the record's waveform with the gate
        # on -- Commando's noise record traces `81 80 80 80 80` -- so that is
        # what `--no-test-restart` writes here. Anything below $FE is assigned
        # to the waveform and forces the gate on (gplay.c:355-363), which is
        # both halves of what a note needs: a real attack and no silent frame.
        #
        # `--no-test-restart` makes this decision for every instrument in the
        # file at once, and that is too blunt: on ACE_II it recovers the drum
        # (voice 2, instrument 1 alone) from melody 100% -> 37% back to 99.6%,
        # but the SAME flag also breaks voice 1 (100% -> 14%, a different
        # mechanism entirely -- see the wavetable-entries `written=` plumbing,
        # not this byte). `real_firstwave_instruments` isolates just the
        # firstwave half of the trade, by GT instrument NUMBER (1-based,
        # matching what a pattern row's instrument column and songview.py
        # both show -- `gt_number = i + lead + 1`), so a per-song preset entry
        # can name the one instrument that needs it without forcing every
        # other instrument in the file through the same byte. Isolated and
        # measured on ACE_II (v0.5.357+): reverting only this byte for the
        # rest of the file, while instrument 1 keeps the real-waveform byte,
        # holds voice 0 and voice 2 at their un-flagged fidelity while voice 2
        # gains the fix -- confirming the corruption lives in this byte alone
        # for that instrument, not in `no_test_restart`'s other effects.
        #
        # **CONFUZION: THE PER-INSTRUMENT FORM KEEPS MELODY, AND NEITHER FORM
        # IS RIGHT ABOUT THE NOISE RUNS.** Its noise is records `$0300` and
        # `$0900` -- GT 2 and 4 under its preset (`lead` 0), voice 2 alone --
        # and naming every instrument there is the file-wide flag byte for
        # byte (`tests/test_confuzion_firstwave.py`). HISTORICAL, HEAD 1dde44a
        # (dirty), under presets, `fidelity.measure()` in-process,
        # `C:/t/check-whether-real-firstwave/probe.py`; window 307 s (the
        # default floor), 180 s (`--no-window-floor`) in brackets:
        #
        #   arm             melody          sequence        wave            noise frames    nrun
        #   presets         1.0000 (1.0000) 1.0000 (1.0000) .9556 (.9609)   13495 (8507)    1.0 (1.0)
        #   no_test_restart .9284 (.9308)   .9563 (.9423)   .9992 (.9987)   14383 (8993)    0.0 (0.0)
        #   rfw (2, 4)      .9671 (.9990)   .9756 (.9990)   .9748 (.9788)   14383 (8993)    0.0 (0.0)
        #   rfw (2, 3, 4)   .9937 (.9902)   .9970 (.9941)   .9869 (.9908)   14383 (8993)    0.0 (0.0)
        #
        # (original 14388 (8998) noise frames; voices 1-based.) The flag's
        # melody cost is voice 1 (.6805 at 307 s), which carries no noise;
        # naming 2 and 4 leaves voice 1 at 1.0000 but costs voice 2 .9293
        # past 180 s, where GT 3 (`$0830`, on voices 2 and 3) shares voice 2
        # with the noise -- naming 3 too restores voice 2 (.9980) and costs
        # voice 3 .9837. Naming 2 alone costs voice 2 sequence .1749, 4 alone
        # melody .0082 (180 s): the pair stands or falls together.
        #
        # **AND `nrun` FALLS 1.0 -> 0.0 IN EVERY REAL-FIRSTWAVE ARM, because
        # it is right.** Lag-aligned, the original's voice 2 note is 21 frames
        # of `$81` then 3 of `$80`; presets gives `$09` + 21 x `$81` + 2 x `$80`,
        # and every real-firstwave arm 22 x `$81` + 2 x `$80`. The gated noise
        # run is EXACT under presets (642 runs / 8370 frames against 642 /
        # 8370 at 307 s) and one frame too long in every other arm (9012 =
        # 8370 + 642). The frame-count gap the firstwave closes is the
        # original's third gate-OFF frame, which the noise-frame count (bit 7
        # alone) credits as noise. The disagreement is where the gate opens,
        # not the firstwave. `$FE` (gate stays off, waveform latched,
        # gplay.c:357) is not the fix: the wavetable never opens the gate, and
        # voice 2 reads 0 attacks.
        # **CORRECTED (81da71d, v0.5.509): "where the gate opens, not the
        # firstwave" is half wrong. The gate opens early BECAUSE of the
        # firstwave.** Lag-aligned at 180 s under presets, on every voice,
        # the note-row time and the gatetimer are already on the original's
        # frames. Every gate fall lands on its frame (v1 485/485, v2 343/343,
        # v0 183/191) and so does every waveform onset (192/192, 486/486,
        # 344/344). Every gate RISE is one frame early (192/192, 486/486,
        # 344/344). That frame is the note-init call, which writes only
        # `$D404` = the firstwave, and `$09` carries the gate in bit 0.
        # Clearing bit 0 (`$08`) puts every rise on the original's frame and
        # takes `gate` .7656 -> .9946, with melody, sequence, wave, nrun and
        # adsr unchanged. The record waveform & $FE also brings voice 2 to 1
        # differing frame of 8994 (wave .9609 -> .9980). That is the gate-off
        # firstwave that task `gate-off-firstwave-option` adds as an option.
        # (`C:/t/confuzion-gate-opens-one-frame-early/edges.py`; pinned by
        # `tests/test_firstwave_gate_edge.py`.)
        # REACH, MEASURED (runs.jsonl firstwave-set-across-the-hold-zero-files,
        # 826dec8, three corpus byte-hash arms): `real_firstwave_instruments`
        # moves 2 files as shipped (5_Title_Tunes, Auf_Wiedersehen_Monty) and
        # 78 of 89 when forced on every instrument. The 11 it cannot move are
        # exactly the songs whose presets carry `no_test_restart`, with no
        # exception either way: the `or` below makes the per-instrument list a
        # no-op once the file-wide flag writes every record's waveform
        # (tests/test_first_wave.py pins that subsumption). It is never chosen
        # by `--fidelity` because its value is a TUPLE of instrument numbers and
        # the search walks booleans -- a structural limit of the search, not a
        # guard; both adoptions are hand-recorded. The gate-off firstwave
        # (record waveform & $FE) measured at 77 movers in
        # corpus-firstwave-class-zero-frame is a third choice beside these two.
        gt_number = i + lead + 1
        use_real_firstwave = no_test_restart or gt_number in real_firstwave_instruments
        out += bytes([ad, sr, wave_ptr, pulse_ptr, filt_ptr, stbl_ptr,
                      vib_delay, gatetimer,
                      ((data[base + 2] | 0x01) & 0xFF) if use_real_firstwave
                      else FIRSTWAVE_TESTBIT])

        b5, b6, b7 = data[base + 5], data[base + 6], data[base + 7]
        name = f"{i + 2:02X}:{b5:02X}-{b6:02X}-{b7:02X}"
        out += _padded_name_bytes(name)

    return instr_used
