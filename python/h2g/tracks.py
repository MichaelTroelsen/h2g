"""Track-list conversion (port of GoatConvertTracks, h2g.frm:1100-1231).

Each Goattracker track is represented as a plain list[int] of the track's
data bytes (excluding the leading Goattracker track-length byte, which
GoatSave derives as len(track) - 1).
"""
from __future__ import annotations

from typing import Dict, List, Optional, Tuple

from .detect import Detection
from .patterns import (DEFAULT_TRACK, GT_LASTNOTE, GT_ORDER_RESTART,
                       MAX_PATTERNS, command_floor, decode_entry,
                       pattern_references, pattern_top_note)
from .sidfile import SidFile

# Goattracker orderlist transpose, from gcommon.h: TRANSDOWN $E0, TRANSUP $F0,
# LOOPSONG $FF. gplay.c:977 accepts $E0..$FE (`>= TRANSDOWN && < LOOPSONG`) and
# assigns `trans = value - TRANSUP`, i.e. -16..+14, applied at gplay.c:927 as
# `newnote + trans`. $FF is unavailable because it is the song-loop marker --
# gorder.c:70 rewrites a typed $FF back to $FE for exactly that reason -- so the
# largest transpose the format can express is **+14**, not +15.
GT_TRANSUP = 0xF0
GT_MAX_TRANSPOSE = 0x0E


def _transpose_byte(semitones: int) -> int:
    """Goattracker orderlist byte for a Hubbard transpose, clamped to +14.

    Hubbard's version-2 players hold the transpose in a per-voice byte that is
    added to the note before the frequency lookup (`AND #$7F` / `CLC` /
    `ADC transpose,X`), and the orderlist command *assigns* it -- the same
    absolute, per-voice semantics as Goattracker's `cptr->trans`, so values in
    range map exactly. Values above the format's ceiling are clamped rather
    than dropped: a clamped transpose is wrong by a known number of semitones,
    whereas dropping one leaves the voice at the *previous* transpose for the
    rest of the track.
    """
    return GT_TRANSUP + min(semitones, GT_MAX_TRANSPOSE)


def _build_track(data: bytes, addr: int, version: int, log=None,
                 transpose_operand: bool = False,
                 transposes: Optional[Dict[int, int]] = None,
                 fd_ends: bool = False,
                 fe_command: bool = False,
                 tempos: Optional[Dict[int, int]] = None) -> List[int]:
    """One voice's orderlist. `transposes` records what was clamped away.

    The emitted byte cannot say whether it is a real +14 or a clamped +48, so
    a caller that wants to undo the clamp (fold_transposes) needs the value
    the player actually stores. Keyed by position in the returned list, and
    filled only by the dialects that have a transpose command at all.

    `tempos` is the same shape for the other command this reader can drop:
    `$FE nn`'s operand, keyed by the orderlist position it takes effect at --
    which is the position of the *next* entry, since the command itself
    occupies no step. Goattracker's orderlist has no tempo command, so
    expressing it means a `CMD_SETTEMPO` in the pattern played there; see
    `patterns.reindex_tracks`.
    """
    track: List[int] = []
    i2 = 0
    _delta_repeat = 1        # version 10 only; see that branch
    while True:
        # The track byte stream is only terminated by a marker byte, so a bad
        # start address (or a stream with no terminator before EOF) walks off
        # the end. `_build_raw_pattern` guards this; this function did not, and
        # crashed with IndexError. Terminate the track cleanly instead -- the VB
        # original read past its fixed-size array here and died with a runtime
        # error, so there is no original behavior worth reproducing.
        if addr + i2 < 0 or addr + i2 >= len(data):
            if log:
                log("*** TRACK DATA RUNS PAST END OF FILE, TRUNCATED ***")
            track += [0xFF, 0x00]
            break

        count = len(track) + 1
        b1 = data[addr + i2]
        if count >= 254:
            b1 = 0xFF
        i2 += 1

        if version == 4:  # ACE 2
            # The player at $E0CF is a plain BPL split:
            #     LDY $E550,X / LDA ($FC),Y / BPL pattern_number
            #     ... LDA #$00 / STA the three indices / JMP $E0CF
            # so < $80 is a pattern number and >= $80 ends the track and
            # restarts it at 0. ACE 2's orderlists are 67/184/118 entries
            # terminated $84/$86/$89, with a top pattern number of $25 against
            # pattern_used $25 -- every byte accounted for.
            #
            # The append below was missing until v0.5.48, so every version-4
            # orderlist came out empty and the file failed with NO PLAYABLE
            # SUBTUNE. That is inherited, not introduced: h2g.frm:1152 `Case 4`
            # is this same do-nothing branch, and the later `Case 0, 1, 2, 3, 4`
            # at :1199 that would have appended is unreachable for 4 because
            # VB's Select Case takes the first match. ACE 2 is the corpus's only
            # version-4 file, so nothing else ever showed the fault.
            if b1 >= 0x80:
                track += [0xFF, 0x00]
                break
            track.append(b1)

        elif version == 5:  # Battle of Britain / Gremlins / Thing on a Spring
            # No command path at all. The fingerprint is its own proof:
            #     LDY index,X / LDA (track),Y / CMP #$FF / BNE pattern_number
            # -- no BPL, and no AND #$7F anywhere in these players' code. Every
            # byte but $FF is a pattern number, and unlike versions 0/1/3 this
            # one does not test $FE either.
            #
            # The VB6 original lumped version 5 in with Mega Apocalypse, so it
            # read $80-$8F and $EF-$FE as transposes and discarded $90-$EE.
            # Harmless in practice -- of the nine version-5 corpus files, only
            # the Commodore 64 Music Examples compilation has any byte >= $80
            # in a real subtune -- but it was decoding a command set the player
            # does not have.
            if b1 == 0xFF:
                track += [0xFF, 0x00]
                break
            track.append(b1)

        elif version in (2, 6, 7, 8):  # AWM / Saboteur II / Mega Apocalypse / IK+
            # These players check the high bit before anything else:
            #     LDA (track),Y / BPL pattern_number / CMP #$FF [/ CMP #$FE]
            # so $80-$FD are transpose commands, not pattern numbers, and the
            # value is the low 7 bits (`AND #$7F` / `STA transpose,X`), read
            # back as `CLC` / `ADC transpose,X` on the note before the
            # frequency-table lookup. Verified in Saboteur II ($F097/$F125),
            # Auf Wiedersehen Monty ($E49A/$E52C), Mega Apocalypse
            # ($4B15/$4B7D) and IK+ ($E09B/$E11E) -- one idiom, four games.
            #
            # The VB6 original grouped version 2 with 0/1/3, which have no such
            # branch, and gave 6/7 a mapping matching none of them: $80-$8F
            # scaled to $F0-$FF (so a transpose of +15 became $FF, LOOPSONG --
            # a spurious song loop where a transposed pattern belongs),
            # $90-$EE discarded, and $EF-$FE read as *negative* transposes
            # though the player has no negative form.
            if b1 == 0xFF:
                track += [0xFF, 0x00]
                break
            if version == 2 and b1 == 0xFE:
                # Only version 2 tests $FE; 6/7 fall through and treat it as a
                # transpose like any other high byte. $FE is "tune ended", and
                # Goattracker has no stop -- see legalise_restarts.
                track += [0xFF, 0xFD]
                break
            if b1 >= 0x80:
                if transpose_operand:   # version 2's two-byte sub-variant only
                    if addr + i2 >= len(data):
                        if log:
                            log("*** TRACK DATA RUNS PAST END OF FILE, TRUNCATED ***")
                        track += [0xFF, 0x00]
                        break
                    semitones = data[addr + i2]
                    i2 += 1
                else:
                    semitones = b1 & 0x7F
                # Consecutive transposes are legal in the player (it loops back
                # to read the next byte) but not in Goattracker, which tests
                # for one transpose per orderlist step. Since both assign
                # rather than accumulate, keeping only the last is equivalent.
                if track and GT_TRANSUP <= track[-1] < 0xFF:
                    track[-1] = _transpose_byte(semitones)
                else:
                    track.append(_transpose_byte(semitones))
                if transposes is not None:
                    transposes[len(track) - 1] = semitones
            else:
                track.append(b1)

        elif version == 9:  # Chain Reaction
            # A version-0 shape with one terminator instead of two. The player
            # at $089A reads $FE and jumps straight to the zero-the-indices /
            # JMP $089A restart:
            #     LDY $0CFA,X / LDA ($FC),Y / CMP #$FE / BEQ $08AD
            # The CMP #$FE at $08A3 on the fall-through path is dead code -- the
            # first test already took every $FE -- so there is no stop marker at
            # all, only loop-to-start. Version 0 expects `C9 FF F0 ?? C9 FE`;
            # this file is `C9 FE F0 ?? C9 FE`, matched nothing, and fell
            # through to version $FF. Its orderlists are 47/66/80 entries, all
            # $FE-terminated, top pattern $19 against pattern_used 25, with no
            # $FF and no command byte anywhere.
            if b1 == 0xFE:
                track += [0xFF, 0x00]
                break
            if b1 <= 0xFD:
                track.append(b1)

        elif version == 10:  # Delta
            # A version-0 orderlist read with a repeat counter woven through
            # it. The pattern-end path at $BF85 decrements $C354,X and only
            # when it reaches zero steps the orderlist -- twice, because the
            # byte it lands on is the *next* pattern's repeat count:
            #     DEC $C354,X / BNE      ; replay the same pattern
            #     INC $C2EC,X            ; step to the repeat byte
            #     LDA (track),Y / BMI    ; $FE/$FF: a marker, leave it alone
            #     STA $C354,X            ; else it is a repeat count
            #     INC $C2EC,X            ; step to the pattern number
            # $BE8C seeds the counter with 1, so the byte at position 0 plays
            # once and the layout is  P0, r1, P1, r2, P2, ... , marker.
            #
            # Reading it flat -- what version 0 does, and what this file got
            # until now -- plays every repeat count as a pattern number.
            # Proof that this is the right reading and not the equally
            # plausible (pattern, repeat) pairing: decoding all 13 subtunes
            # both ways, this one makes the three voices come out exactly
            # equal in frames every time (subtune 0 is 13632 frames in all
            # three), while the pairing disagrees by up to 12x.
            if b1 in (0xFE, 0xFF):
                track += [0xFF, 0xFD if b1 == 0xFE else 0x00]
                break
            repeat = 1 if not track else _delta_repeat
            # Clamp the expansion itself, not just the next iteration: a
            # stored count of 0 is 256 plays, which alone overflows the
            # 254-byte orderlist if appended before checking.
            room = 252 - len(track)
            track += [b1] * min(repeat, room)
            if repeat >= room:
                track += [0xFF, 0x00]
                break
            if addr + i2 >= len(data):
                continue                     # bounds check runs at the top
            nxt = data[addr + i2]
            if nxt >= 0x80:
                continue                     # marker: read it as one next time
            # A stored 0 counts 256 times, not none: the player's DEC wraps
            # $00 to $FF and the BNE keeps replaying.
            _delta_repeat = nxt or 256
            i2 += 1

        elif version in (0, 1, 3):  # Warhawk / Last V8 / Samantha Fox
            # **`$FD` ends a voice's list in the three players that test it.**
            # Rasputin `$C094`, and the same shape in Knucklebusters and
            # Tarzan:
            #
            #     C094  LDY index,X / LDA (ptr),Y / CMP #$FF / BEQ stop
            #     C09D  CMP #$FE / BNE +
            #     C0A1    INC index,X / INY / LDA (ptr),Y     ; the operand
            #     C0A7    STA $C539 / STA $C53A               ; a gate's reload
            #     C0AD    INC index,X / JMP $C094             ; keep reading
            #     C0B3  + CMP #$FD / BNE + ; JSR .. ; this voice is done
            #
            # Read as a pattern number, `$FD` let a voice run straight on into
            # the next voice's data: Rasputin's three voices index **one shared
            # stream** at different offsets, and voice 0 emitted 106 bytes for
            # a ten-entry list. Knucklebusters shows the audible end of it --
            # `$00F8` sounds 959 frames over 2 notes where the original sounds
            # 9 over 94, because the voice never reaches a retrigger
            # (section 7.uuuu, found from the `hold` column).
            #
            # **Gated on the player, not on the version.** `$FE` really is
            # "tune ended" in the other version-0 players -- that is what
            # `legalise_restarts` exists for -- and Rasputin alone reads
            # `$FE nn` as a two-byte tempo command that *continues* the list.
            # Applying its reading to all of version 0 rewrote 23 files and
            # broke the byte-exact fixture; these two flags are read from each
            # player's own reader (`detect._find_track_terminators`).
            if b1 == 0xFE and fe_command:
                # The operand is a tempo, not a pattern. It reloads the gate
                # at `$C539`/`$C53A` -- so a row lasts `nn + 1` frames from
                # here on, and the list continues at the next byte.
                if tempos is not None and addr + i2 < len(data):
                    tempos[len(track)] = data[addr + i2]
                i2 += 1
                continue
            if b1 == 0xFE:
                track += [0xFF, 0xFD]  # tune ended; see legalise_restarts
                break
            if b1 == 0xFF:
                track += [0xFF, 0x00]
                break
            if b1 == 0xFD and fd_ends:
                track += [0xFF, 0xFD]
                break
            if b1 <= 0xFD:
                track.append(b1)

        else:
            raise ValueError(
                f"unsupported/undetected Hubbard player track-read version: ${version:X}"
            )
    return track


def _voice_addr(sid: SidFile, det: Detection, i: int, voice: int):
    """File offset of one subtune/voice orderlist, or None if unusable.

    Returns None both when the *table index* falls outside the file (the track
    table itself is unbounded -- nothing records its length) and when the
    16-bit address it holds resolves outside the file.
    """
    data = sid.data
    # Classic players keep a LO table and a HI table, each with one byte per
    # (subtune, voice); the digi engine interleaves them, so consecutive
    # entries are two bytes apart and the HI byte is the LO byte's neighbour.
    if det.table_stride == 2:
        so = (voice + i * det.track_voices) * 2
    else:
        so = voice + i * (det.track_voices * 2)
    lo_i, hi_i = det.track_lo + so, det.track_hi + so
    if min(lo_i, hi_i) < 0 or max(lo_i, hi_i) >= len(data):
        return None
    addr = sid.to_offset(data[hi_i] * 256 + data[lo_i])
    if addr <= 1 or addr >= len(data):
        return None
    return addr


def _track_cells(det: Detection, i: int) -> List[int]:
    """The table byte indices subtune `i` reads its three pointers from."""
    cells: List[int] = []
    for voice in range(det.track_voices):
        if det.table_stride == 2:
            so = (voice + i * det.track_voices) * 2
        else:
            so = voice + i * (det.track_voices * 2)
        cells += [det.track_lo + so, det.track_hi + so]
    return cells


def track_table_extent(sid: SidFile, det: Detection) -> Optional[int]:
    """How many subtunes the track table has room for, on the player's layout.

    The track table has no length field either -- the same hole
    `patterns.phantom_patterns` closes for the *pattern* table, and the same
    fix. Detection derives the pattern table's entry count from the distance
    between its LO and HI arrays; those two arrays are therefore known extents
    of bytes that are **not** track-table cells, and neither is a run of bytes
    a player signature matched (`det.code_spans`, the identical vocabulary
    phantom_patterns uses). A subtune whose pointer cells land in one of them
    is not a subtune the player can ever have dispatched: the bytes it reads
    belong to another structure.

    This is a claim about the file's layout, never a statistical one, and it
    is exactly the bound `Detection.subtunes_available` already carries for
    the digi engine -- there the orderlist table is capped by the pattern
    table that follows it, and that is the general case rather than a quirk of
    that one engine. Commodore 64 Music Examples is the extreme: its track LO
    array sits at $1436 and the pattern LO array begins six bytes later at
    $143C, so the table holds **one** subtune, while its PSID header claims
    fifteen. Subtune 14 read its "pointers" out of pattern LO entries 78 and
    81, which happen to compose $08F2 -- inside the init dispatch's LO table
    at $08EC (`$08CB: LDA $08EC,X / STA $0878`, self-modifying the JSR operand
    at $0877) -- and decoded 277 pattern references out of a table of routine
    addresses. It passed every earlier test: three voices resolved, the refs
    were plentiful, and being the *last* declared subtune it set `keep` to 15
    single-handed, so the twelve placeholders behind it were emitted too.

    Returns None when nothing bounds the table (no pattern table located and
    no signature spans), otherwise the count. Never looks past
    `sid.subtunes` -- the header is still the other bound, and the answer
    above it is not needed.
    """
    n = det.pattern_used + 1
    stride = det.table_stride
    not_track: List[Tuple[int, int]] = []
    if det.pattern_lo >= 0 and det.pattern_hi >= 0 and n > 0:
        not_track.append((det.pattern_lo, n * stride))
        not_track.append((det.pattern_hi, n * stride))
    not_track += list(det.code_spans)
    if not not_track:
        return None
    for i in range(sid.subtunes):
        cells = _track_cells(det, i)
        if any(s <= c < s + length for c in cells for s, length in not_track):
            return i
    return sid.subtunes


def convert_tracks(sid: SidFile, det: Detection, log,
                   transposes: Optional[List[Dict[int, int]]] = None,
                   tempos: Optional[List[Dict[int, int]]] = None,
                   census: Optional[List[Dict]] = None
                   ) -> List[List[int]]:
    """Every subtune's three orderlists, in voice order.

    `transposes`, when given a list, receives one {position: semitones} map
    per emitted track -- the true transpose behind each clamped command byte,
    for fold_transposes. Filled here rather than re-derived later because the
    passes that follow (reindexing, packing, merging, splitting) all move
    orderlist positions around.

    `tempos` receives one {position: gate reload} map per track on the same
    terms, for the one dialect whose orderlist carries a tempo command.

    `census` receives one record per subtune the header declares, saying what
    became of it and why. It is an out-parameter for the same reason the other
    two are: the answer is a by-product of decisions taken here, and the
    alternative -- a second pass re-deriving `_voice_addr`, `command_floor`
    and `pattern_references` from a `Detection` -- would be a re-derivation
    that has to get every input right where this one cannot be wrong without
    the conversion being wrong too. Keys:

        subtune   index as the PSID header numbers it
        fate      "emitted" | "placeholder" | "trimmed" | "beyond_table"
                  | "sfx"
        why       the single reason, for grouping
        voices_ok how many of the three pointers resolved inside the file
        refs      pattern numbers named across the three voices
        dangling  how many of those name a pattern that does not exist

    "placeholder" is an interior subtune that is emitted but plays nothing --
    it still occupies a slot in the .sng, which is why it is not "trimmed".
    """
    data = sid.data
    tracks: List[List[int]] = []

    # The track table has no length field, and the PSID header's song count is
    # frequently larger than the table really is (Knucklebusters claims 11
    # subtunes but has room for 3). Reading past the end yields garbage pointers
    # -- offsets that are negative or far beyond EOF -- which used to be emitted
    # as empty placeholder tracks, padding the .sng with phantom subtunes.
    #
    # Only the *trailing* run of unusable subtunes is dropped. Trimming at the
    # first unusable one is tempting but wrong: across the corpus the valid/
    # invalid map is interleaved (Commando is "...XXXXXXX........X"), so valid
    # subtunes routinely follow a gap and stopping early would discard real
    # music. Interior gaps keep their placeholder tracks, exactly as before.
    # Every subtune is built before any is trimmed, because whether one is real
    # cannot be decided from its pointers alone -- see the playability test
    # below. Diagnostics are therefore withheld until the emit loop, so a
    # subtune that gets dropped does not log about itself on the way out.
    # The digi engine drives a fourth voice: the sample channel these tunes are
    # named for. Goattracker has three, and a sampled channel is not something
    # a tracker orderlist can carry anyway, so it is dropped -- but never
    # silently, or the output looks like the whole tune.
    if det.track_voices > 3:
        log(f"*** VOICE {det.track_voices} IS THE SAMPLE (DIGI) CHANNEL, "
            "NOT CONVERTED -- GOATTRACKER HAS 3 VOICES ***")
    n_voices = min(3, det.track_voices)
    built: List[List[List[int]]] = []   # per subtune, per voice
    tmaps: List[List[Dict[int, int]]] = []
    smaps: List[List[Dict[int, int]]] = []
    addr_ok: List[List[bool]] = []
    subtunes = sid.subtunes
    beyond_why = "track table is shorter than the header"
    # The player's own answer, where it has one, comes first: `find_music_
    # subtunes` reads a `CMP #imm / BCS / JMP` dispatch at the init entry, and
    # everything at or above the immediate is a game sound effect with its own
    # routine and no orderlist here at all. That is a statement about the file
    # rather than an inference from whether a pointer resolves -- which is the
    # test the trailing-run trim below applies, and which SUBTUNES.md's
    # headline finding says is not evidence of music either way.
    sfx_from = sid.subtunes
    if det.music_subtunes is not None and det.music_subtunes < subtunes:
        sfx_from = subtunes = det.music_subtunes
        log(f"Header claims ${sid.subtunes:X} subtune(s); the player's init "
            f"dispatch says ${subtunes:X} are music and the rest are sound "
            "effects")
    if det.subtunes_available:
        subtunes = min(subtunes, det.subtunes_available)
        if subtunes < sfx_from:
            log(f"Header claims ${sid.subtunes:X} subtune(s); the track table holds "
                f"${subtunes:X}")
    # And the same bound for every other engine, read off the file's layout --
    # see track_table_extent. Applied after the digi bound rather than instead
    # of it: both are upper limits and the tighter one wins.
    extent = track_table_extent(sid, det)
    if extent is not None and extent < subtunes:
        log(f"Header claims ${sid.subtunes:X} subtune(s); the track table runs "
            f"into another table after ${extent:X}")
        subtunes = extent
        beyond_why = "track table cells belong to another table"
    if census is not None:
        for i in range(subtunes, sid.subtunes):
            # Three bounds now cap the count, and a dropped subtune is
            # attributed to the one that actually dropped it. `sfx_from` is
            # the player's own dispatch, so anything at or above it is a
            # sound effect whatever the layout says; below it the drop came
            # from a table bound, and `beyond_why` says which.
            sfx = i >= sfx_from
            why = ("the player's init dispatches it to the sound-effect "
                   "routine" if sfx else beyond_why)
            census.append({"subtune": i,
                           "fate": "sfx" if sfx else "beyond_table",
                           "why": why,
                           "voices_ok": 0, "refs": 0, "dangling": 0})
    for i in range(subtunes):
        voices: List[List[int]] = []
        maps: List[Dict[int, int]] = []
        speeds: List[Dict[int, int]] = []
        flags: List[bool] = []
        for voice in range(3):
            addr = None if voice >= det.track_voices else _voice_addr(sid, det, i, voice)
            flags.append(addr is not None)
            tmap: Dict[int, int] = {}
            maps.append(tmap)
            smap: Dict[int, int] = {}
            speeds.append(smap)
            voices.append(list(DEFAULT_TRACK) if addr is None else
                          _build_track(data, addr, det.read_track_version, None,
                                       det.transpose_operand, tmap,
                                       fd_ends=det.track_fd_ends,
                                       fe_command=det.track_fe_command,
                                       tempos=smap))
        built.append(voices)
        tmaps.append(maps)
        smaps.append(speeds)
        addr_ok.append(flags)

    usable = [all(flags[:n_voices]) for flags in addr_ok]

    # A subtune whose pointers resolve can still be nonsense: a pointer landing
    # anywhere inside the file passes the range check and is then read as an
    # orderlist. Reject the ones that name no existing pattern in any voice --
    # they can play nothing, whatever else they contain.
    #
    # Deliberately conservative. Half the corpus's dirty subtunes are 30-60%
    # dangling, but a real tail sits at 1-16 bad references out of 100-340 good
    # ones (Gremlins subtune 11 is 1/100), and those are real music with a byte
    # this converter still mis-decodes. Any threshold that catches the garbage
    # would discard them too.
    floor = command_floor(det.read_track_version)
    playable = [
        ok and any(r <= det.pattern_used for r in pattern_references(voices, floor))
        for ok, voices in zip(usable, built)
    ]
    # Taken before the reset below, which replaces a dropped subtune's
    # orderlists with DEFAULT_TRACK: reading `built` afterwards reports that
    # placeholder's three bytes as the subtune's own references, which is how
    # the first run of this census showed Commando's subtune 14 as "3 voices,
    # 3 refs, 0 dangling" -- a row that cannot exist, since such a subtune
    # would have been emitted.
    stats = []
    if census is not None:
        for i in range(subtunes):
            live = [v for v, ok in zip(built[i], addr_ok[i]) if ok]
            refs = list(pattern_references(live, floor)) if live else []
            # The raw 16-bit pointers as the table holds them. Recorded
            # because the *count* of resolving voices cannot tell a partly
            # readable subtune from one past the end of the table whose stray
            # bytes happen to form an in-range address, and the pointers can:
            # a real row is ordered and close to its neighbours (Warhawk's
            # subtunes 0-8 run $1847..$1A14) and a false one is not ($6C16,
            # $984F, $63B1).
            ptrs = []
            for v in range(3):
                so = ((v + i * det.track_voices) * 2 if det.table_stride == 2
                      else v + i * (det.track_voices * 2))
                lo_i, hi_i = det.track_lo + so, det.track_hi + so
                ptrs.append(data[hi_i] << 8 | data[lo_i]
                            if 0 <= min(lo_i, hi_i) and
                            max(lo_i, hi_i) < len(data) else None)
            stats.append((sum(addr_ok[i][:n_voices]), len(refs),
                          sum(1 for r in refs if r > det.pattern_used), ptrs))

    for i, (ok, play) in enumerate(zip(usable, playable)):
        if ok and not play:
            log(f"*** SUBTUNE ${i:X} PLAYS NO EXISTING PATTERN, DROPPED ***")
            built[i] = [list(DEFAULT_TRACK) for _ in range(3)]
            tmaps[i] = [{} for _ in range(3)]
            smaps[i] = [{} for _ in range(3)]

    keep = max((i + 1 for i, ok in enumerate(playable) if ok), default=0)
    if census is not None:
        for i in range(subtunes):
            # Only the voices that resolved: an unusable one holds
            # DEFAULT_TRACK, whose bytes would otherwise be counted as this
            # subtune naming patterns it never named.
            n_ok, n_refs, bad, ptrs = stats[i]
            if n_ok == 0:
                why = "no voice pointer resolves inside the file"
            elif n_ok < n_voices:
                why = f"only {n_ok} of {n_voices} voice pointers resolve"
            else:
                why = "names no pattern that exists"
            if i >= keep:
                fate = "trimmed"
            elif not playable[i]:
                fate = "placeholder"
            else:
                fate, why = "emitted", ""
            census.append({"subtune": i, "fate": fate, "why": why,
                           "voices_ok": n_ok, "refs": n_refs,
                           "dangling": bad, "pointers": ptrs,
                           "resolved": list(addr_ok[i][:3])})
        census.sort(key=lambda r: r["subtune"])
    if keep < subtunes:
        log(f"Header claims ${subtunes:X} subtune(s); last usable is "
            f"${keep - 1:X}, dropping {subtunes - keep} phantom")

    for i in range(keep):
        for voice in range(3):
            if voice < det.track_voices and not addr_ok[i][voice]:
                log(f"*** SUBTUNE ${i:X} (VOICE {voice:X}) ADDRESS OUT OF RANGE, CAN'T CONVERT ***")
            tracks.append(built[i][voice])
            if transposes is not None:
                transposes.append(tmaps[i][voice])
            if tempos is not None:
                tempos.append(smaps[i][voice])

    # No fabricated placeholder subtune when nothing survived. Returning one
    # kept the .sng structurally valid, but it also referenced pattern 0, which
    # made a file with no playable subtune look sound to every check downstream
    # -- ACE 2 reported 15599 bytes of nothing. An empty list is the honest
    # answer; convert() turns it into a refusal.

    return tracks


SEMITONES_PER_OCTAVE = 12


def fold_transposes(sid: SidFile, det: Detection, tracks: List[List[int]],
                    transposes: List[Dict[int, int]], log=None,
                    slides: bool = False,
                    status_bit6: bool = False) -> List[Tuple[int, int]]:
    """Undo the +14 clamp by moving whole octaves into the notes, in place.

    Hubbard's orderlists carry transposes of 24, 36 and 48 -- two, three and
    four octaves -- and Goattracker's orderlist transpose stops at +14,
    because $FF is LOOPSONG and gorder.c:70 rewrites a typed $FF back to $FE
    for exactly that reason. `_transpose_byte` therefore clamped, and every
    note under such a step played 10 to 34 semitones flat. That is measurable
    in the fidelity report as a constant, 100%-consistent negative interval on
    five files, against controls that return +0 at 100%.

    The transpose is a pitch offset and nothing else -- the player adds it to
    the note before the frequency lookup (`CLC / ADC transpose,X`), and
    Goattracker adds `cptr->trans` at gplay.c:927 -- so `T` and
    `(T mod 12) + 12k` are the same interval whichever side of the lookup the
    `12k` is applied on. The remainder is always 0..11, comfortably inside the
    format, and the octaves go into a copy of each pattern the step plays.
    The note column has room: pitches span $60-$BC, and a decoded Hubbard note
    tops out wherever the tune's own melody does.

    Where it does *not* have room the step is left exactly as it was. A
    partial fold would only be a different wrong pitch, and for a transpose
    like 24 (remainder 0) a partial fold is worse than the clamp it replaces
    -- the note would come out 24 semitones flat rather than 10. So each step
    is either transposed exactly right or untouched, which is also what makes
    the change safe to reason about file by file. The corpus's unfoldable
    steps are almost entirely phantom subtunes carrying transposes of 96 and
    more, which no frequency table this side of the player has entries for.

    Costs one pattern-table entry per distinct (pattern, octaves) pair, against
    Goattracker's 208. Variants are numbered from `det.pattern_used + 1` --
    they extend the table rather than displacing anything -- and stop at the
    dialect's command floor, since an orderlist byte at or above it would be
    read as a command rather than a pattern.

    Returns the `(source entry, octaves)` list convert_patterns needs, in
    variant order.
    """
    floor = command_floor(det.read_track_version)
    first = det.pattern_used + 1
    variants: List[Tuple[int, int]] = []
    index: Dict[Tuple[int, int], int] = {}
    tops: Dict[int, int] = {}

    def headroom(entry: int) -> int:
        """Octaves this pattern's highest note can rise by and stay a note."""
        if entry not in tops:
            events = decode_entry(sid, det, entry, slides, status_bit6)
            tops[entry] = pattern_top_note(events) if events else 0
        top = tops[entry]
        # No note at all: nothing to shift, so no ceiling and no variant.
        return 0x7F if not top else (GT_LASTNOTE - top) // SEMITONES_PER_OCTAVE

    folded = steps = 0
    worst_kept = 0
    for track, tmap in zip(tracks, transposes):
        if not any(v > GT_MAX_TRANSPOSE for v in tmap.values()):
            continue
        # Group each over-range transpose with the pattern references it
        # governs. A transpose is assigned, not accumulated, and holds until
        # the next one -- the same semantics on both sides -- so the run is
        # every reference from the command to the following command.
        runs: Dict[int, List[int]] = {}
        cur = None
        i = 0
        while i < len(track):
            b = track[i]
            if b == GT_ORDER_RESTART:
                break              # the restart position is not a reference
            if b >= floor:
                cur = i
            elif cur is not None and tmap.get(cur, 0) > GT_MAX_TRANSPOSE:
                runs.setdefault(cur, []).append(i)
            i += 1

        for at, positions in runs.items():
            steps += 1
            semitones = tmap[at]
            octaves = semitones // SEMITONES_PER_OCTAVE
            # Sorted, so the variant numbering depends only on the file.
            entries = sorted({track[p] for p in positions})
            if any(headroom(e) < octaves for e in entries):
                worst_kept = max(worst_kept, semitones)
                continue
            need = [e for e in entries
                    if tops.get(e) and (e, octaves) not in index]
            if first + len(variants) + len(need) > floor:
                worst_kept = max(worst_kept, semitones)
                continue
            for e in need:
                index[(e, octaves)] = first + len(variants)
                variants.append((e, octaves))
            track[at] = _transpose_byte(semitones % SEMITONES_PER_OCTAVE)
            for p in positions:
                # A pattern that sounds no note is its own transposition.
                new = index.get((track[p], octaves))
                if new is not None:
                    track[p] = new
            folded += 1

    if log and steps:
        if folded:
            log(f"Transposes..............: folded {folded} of {steps} orderlist "
                f"step(s) over Goattracker's +14 into {len(variants)} "
                f"octave-shifted pattern(s)")
        if folded < steps:
            log(f"*** {steps - folded} ORDERLIST STEP(S) TRANSPOSE UP TO "
                f"+{worst_kept} AND DO NOT FIT THE NOTE RANGE, LEFT CLAMPED "
                f"AT +{GT_MAX_TRANSPOSE} ***")
    return variants


def apply_initial_instruments(tracks: List[List[int]],
                              patterns: List[List[int]],
                              det: Detection, log=None) -> int:
    """Give each voice the instrument it starts on, where a pattern names none.

    Hubbard's player keeps a per-voice instrument *index* and writes it only
    when a pattern carries an instrument byte; until then the voice sounds
    whatever the index array held when the file was loaded
    (`Detection.initial_instruments`). Goattracker has the same carry-forward
    rule -- `gplay.c:914` assigns `cptr->instr` only when the row's instrument
    column is non-zero -- but a different starting point: `gplay.c:223` sets
    every channel to instrument 1, which this writer emits as the empty
    "Clear Voice" record. A voice whose first note is reached before any
    pattern selects an instrument therefore plays with attack/decay 0 and
    sustain/release 0, which is silence.

    That is Delta Mix-E-Load's two dead voices exactly: its orderlists are one
    pattern each, patterns $18 and $17 carry no instrument byte, and the array
    at $C535 reads `03 09 00` -- the three instruments siddump shows the
    original playing. It is 41 of the corpus's 821 voice orderlists in nine
    files.

    Applied by copying the pattern and pointing that one orderlist step at the
    copy, never by patching in place: the same pattern is played again later
    in half these files, and there the voice's instrument is whatever earlier
    patterns set, so an instrument column written into the shared copy would
    fire every time round. Costs one pattern entry per distinct
    (pattern, instrument) pair against Goattracker's 208.

    Returns the number of orderlist steps repointed.
    """
    if not det.initial_instruments:
        return 0
    # goatwriter drops instruments past MAX_INSTRUMENTS, so an initial index
    # beyond what will be written names a record the .sng does not contain.
    ceiling = min(det.instr_used + 1, 50)
    copies: Dict[Tuple[int, int], int] = {}
    fixed = 0
    for ti, track in enumerate(tracks):
        instr = _initial_for(det, ti % 3)
        if instr is None or not 2 <= instr <= ceiling:
            continue
        for pos, entry in enumerate(track):
            if entry == GT_ORDER_RESTART:
                break
            if entry >= MAX_PATTERNS or entry >= len(patterns):
                continue
            row = _first_sounding_row(patterns[entry])
            if row is None:         # an instrument is set before any note
                break
            if row < 0:             # no note in this pattern; try the next
                continue
            key = (entry, instr)
            if key not in copies:
                if len(patterns) >= MAX_PATTERNS:
                    if log:
                        log("*** NO ROOM FOR AN INITIAL-INSTRUMENT PATTERN "
                            f"COPY (AT GOATTRACKER'S {MAX_PATTERNS} LIMIT) ***")
                    break
                copy = list(patterns[entry])
                copy[row * 4 + 1] = instr
                copies[key] = len(patterns)
                patterns.append(copy)
            track[pos] = copies[key]
            fixed += 1
            break
    if fixed and log:
        log(f"Initial instruments.....: {fixed} voice orderlist(s) began on a "
            f"note no pattern gave an instrument; {len(copies)} pattern "
            "copy/copies added")
    return fixed


def instrument_voices(tracks: List[List[int]],
                      patterns: List[List[int]]) -> Dict[int, Dict[int, int]]:
    """{Goattracker instrument: {voice: rows}} over the finished song.

    Read from the converted orderlists and patterns rather than from the
    player, because that is where the answer is: a Hubbard record says nothing
    about which voice plays it, and the tune's own orderlists say it exactly.
    Every voice a pattern is played on counts, and the row count is weighted by
    how often the orderlists play that pattern -- an instrument named in a
    pattern played sixteen times is not one occurrence, the same weighting
    `goatwriter._drum_max_steps` takes over note durations.

    The carry-forward rule does not leak across voices, which is what makes a
    single-voice answer trustworthy: Goattracker holds the last non-zero
    instrument column until another row sets one (gplay.c:914), but that
    column can only have been set by a pattern *this* voice played, so an
    instrument sounding on a voice always has a set-site on it.

    Written for the one mechanism whose parameters are per voice
    (`detect._find_voice_two_stage`), and general because the next one will
    want it too: a wavetable is per instrument, so an instrument played on two
    voices cannot carry a per-voice effect at all.
    """
    plays: Dict[int, Dict[int, int]] = {}
    for ti, track in enumerate(tracks):
        voice = ti % 3
        operand = False
        for entry in track:
            if operand:                 # $FF's restart position, not a pattern
                operand = False
            elif entry == GT_ORDER_RESTART:
                operand = True
            elif entry < MAX_PATTERNS:
                plays.setdefault(entry, {})[voice] = \
                    plays.setdefault(entry, {}).get(voice, 0) + 1
    out: Dict[int, Dict[int, int]] = {}
    for pattern, voices in plays.items():
        if pattern >= len(patterns):
            continue
        rows = patterns[pattern]
        counts: Dict[int, int] = {}
        for k in range(1, len(rows), 4):
            if rows[k]:
                counts[rows[k]] = counts.get(rows[k], 0) + 1
        for instr, n in counts.items():
            per = out.setdefault(instr, {})
            for voice, times in voices.items():
                per[voice] = per.get(voice, 0) + n * times
    return out


def _initial_for(det: Detection, voice: int) -> Optional[int]:
    """The Goattracker instrument number `voice` starts on, or None.

    Hubbard index k is written as Goattracker instrument k + 2 -- slot 1 is
    the "Clear Voice" record goatwriter always emits -- matching the `+ 2` in
    patterns.decode_entry.
    """
    if voice >= len(det.initial_instruments):
        return None
    return det.initial_instruments[voice] + 2


def _first_sounding_row(events: List[int]) -> Optional[int]:
    """Row index of the first note played with no instrument column set.

    None when a row sets an instrument before any note is reached -- the
    player would have been given one by then, so nothing needs adding -- and
    -1 when the pattern holds no note at all, which leaves the question to
    the next pattern in the orderlist.
    """
    for row in range(len(events) // 4):
        note, instr = events[row * 4], events[row * 4 + 1]
        if instr:
            return None
        if note <= GT_LASTNOTE:
            return row
    return -1


def ensure_playable_orderlists(tracks: List[List[int]], log=None) -> int:
    """Replace any voice orderlist that is nothing but an end marker, in place.

    `gsong.c:1338-1349` derives `songlen` by scanning for the first byte
    `>= LOOPSONG`, so a track whose first byte is already `$FF` has
    `songlen == 0`. That is not merely an empty voice -- it invalidates the
    whole subtune:

        greloc.c:200-255   counts `songs` as the subtunes whose *three* voices
                           all have nonzero length
        greloc.c:653       writes `for (c = 0; c < songs; c++)`, over the
                           ORIGINAL indices, re-testing validity as it goes

    So an invalid subtune keeps its slot and is written as a zero-length stub
    (`:701-706`) -- present in the packed `.sid`, playing nothing -- while every
    subtune at or past the count is never written at all. Rasputin is the worst
    case in the corpus: subtunes 0 and 1 are invalid, so `songs` is 15 of 17,
    and subtunes 15 and 16 -- carrying 309 and 621 sounding rows -- are dropped
    from the `.sid` with nothing anywhere reporting it.

    Note what this is *not*: nothing is renumbered and the list is not
    compacted. An earlier description of this bug in three of the repo's docs
    said it was, and that was wrong.

    Seven corpus files are affected (Rasputin, both Last V8s, One Man and his
    Droid, Dragon's Lair II, Mega Apocalypse, Monty on the Run). The repair is
    the placeholder every other unrepresentable subtune already gets, which
    costs one orderlist step and makes the subtune valid.

    This runs unconditionally. The same repair used to happen only as a side
    effect of `--legal-restart`, which meant the default conversion silently
    dropped subtunes from its packed `.sid`; a zero-length voice is a problem
    regardless of whether any restart position is legal.

    Making a subtune valid also exposes it to a check it was previously skipped
    by. `greloc.c:244` rejects a restart position `>= songlen`, and it runs only
    inside the `songlen[c][0] && [1] && [2]` guard -- so an invalid subtune's
    illegal restart was never looked at. Repairing the empty voice alone turns
    Rasputin from "packs 15 of 17 subtunes" into "packs nothing", because
    subtune 0's *other* two voices end on Hubbard's `$FE` stop marker. The two
    repairs are therefore one repair, applied together and only to the subtunes
    this function revives: their alternative is not a stop, it is not being
    exported at all. Subtunes that were already valid keep their stop markers
    and remain `--legal-restart`'s business.

    Tracks are grouped three per subtune, in voice order, as convert_tracks
    emits them.

    Returns the number of subtunes revived.
    """
    revived = 0
    voices_fixed = 0
    for base in range(0, len(tracks) - 2, 3):
        group = tracks[base:base + 3]
        if not any(t and t[0] == GT_ORDER_RESTART for t in group):
            continue
        revived += 1
        for track in group:
            if track and track[0] == GT_ORDER_RESTART:
                track[:] = list(DEFAULT_TRACK)
                voices_fixed += 1
                continue
            # Same walk as legalise_restarts: the first $FF is the marker, and
            # the byte after it is the restart position (gsong.c:1344).
            songlen = next((i for i, b in enumerate(track)
                            if b == GT_ORDER_RESTART), None)
            if (songlen is not None and songlen + 1 < len(track)
                    and track[songlen + 1] >= songlen):
                track[songlen + 1] = 0
    if log and revived:
        log(f"Empty voices............: {voices_fixed} voice orderlist(s) held "
            f"nothing but an end marker; gave them a placeholder step and made "
            f"{revived} subtune(s) exportable")
    return revived


def legalise_restarts(tracks: List[List[int]], log=None) -> int:
    """Replace restart positions Goattracker's exporter refuses, in place.

    Hubbard's `$FE` track marker means *this tune has ended*. Every dialect
    encodes it the same way: it calls the player's jump-table entry +3, which
    is `LDA #$C0 / STA flag / RTS`, and the play routine's `BIT flag / BMI` at
    the top then branches away and stops fetching notes. Verified in Warhawk
    (`$109F` -> `JSR $1003` -> `JMP $1F30`), Last V8 (`$809B` -> `JMP $8013` ->
    `JMP $8C71`) and Saboteur II (`$F0A2` -> `JSR $F00C` -> `JMP $F589`) --
    three dialects, one idiom.

    Goattracker's orderlist has no "stop", so the VB6 original wrote `$FF $FD`
    (`'make repeat illegal, so goattracker stops`, h2g.frm:1206): a LOOPSONG
    whose restart position is out of range, which makes gplay.c:969 call
    stopsong(). That is right in the editor and wrong everywhere else --
    greloc.c:244 refuses to export a song whose restart position is
    `>= songlen`, so gt2reloc writes no .sid at all. It reports nothing when it
    does so, because its error path prints to a console that does not exist
    headless, so the failure looks like success with a missing file.

    A track whose first byte is already `$FF` has `songlen == 0`, so even
    position 0 is out of range -- but that is a different failure with a
    different consequence (the subtune is excluded from the export rather than
    failing it), and `ensure_playable_orderlists` repairs it unconditionally
    before this runs.

    Restart position 0 is the only value that is legal without knowing the
    finished orderlist -- every other candidate depends on a length that
    slicing, packing, merging and splitting all change after this data is
    built. So the tune loops from the top instead of ending. That is a real
    loss of the composer's intent, which is why this is opt-in and why it is
    logged; it is also the difference between a packed .sid and no file.

    Returns the number of tracks changed.
    """
    fixed = 0
    for track in tracks:
        # Walk to the LOOPSONG rather than scanning for the first small byte.
        # In a reindexed orderlist nothing but LOOPSONG can be $FF -- pattern
        # numbers are < $D0, repeats $D0-$DF, transposes clamped to $FE -- but
        # the restart operand that *follows* it is an ordinary number, so the
        # first $FF is the marker, exactly as gsong.c:1344 finds it.
        songlen = next((i for i, b in enumerate(track) if b == GT_ORDER_RESTART),
                       None)
        if songlen is None or songlen + 1 >= len(track):
            continue                       # no marker, or no operand to judge
        if track[songlen + 1] < songlen:
            continue                       # already legal
        if songlen == 0:
            # No position to restart at, and nothing this function can do about
            # it. ensure_playable_orderlists owns that repair and convert()
            # runs it first, unconditionally -- a zero-length voice invalidates
            # its whole subtune whether or not the restart position is legal,
            # so it must not depend on this opt-in flag.
            continue
        track[songlen + 1] = 0
        fixed += 1
    if log and fixed:
        log(f"Restart positions.......: {fixed} track(s) ended on Hubbard's $FE "
            "stop marker; restarted at 0 so the song can be relocated")
    return fixed
