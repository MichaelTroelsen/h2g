"""Track-list conversion (port of GoatConvertTracks, h2g.frm:1100-1231).

Each Goattracker track is represented as a plain list[int] of the track's
data bytes (excluding the leading Goattracker track-length byte, which
GoatSave derives as len(track) - 1).
"""
from __future__ import annotations

from typing import List

from .detect import Detection
from .patterns import DEFAULT_TRACK, command_floor, pattern_references
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
                 transpose_operand: bool = False) -> List[int]:
    track: List[int] = []
    i2 = 0
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
            if b1 >= 0x80:
                track += [0xFF, 0x00]
                break

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
                # transpose like any other high byte.
                track += [0xFF, 0xFD]  # illegal repeat position -> stop
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
            else:
                track.append(b1)

        elif version in (0, 1, 3):  # Warhawk / Last V8 / Samantha Fox
            if b1 == 0xFE:
                track += [0xFF, 0xFD]  # illegal repeat position -> stop
                break
            if b1 == 0xFF:
                track += [0xFF, 0x00]
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


def convert_tracks(sid: SidFile, det: Detection, log) -> List[List[int]]:
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
    addr_ok: List[List[bool]] = []
    subtunes = sid.subtunes
    if det.subtunes_available:
        subtunes = min(subtunes, det.subtunes_available)
        if subtunes < sid.subtunes:
            log(f"Header claims ${sid.subtunes:X} subtune(s); the track table holds "
                f"${subtunes:X}")
    for i in range(subtunes):
        voices: List[List[int]] = []
        flags: List[bool] = []
        for voice in range(3):
            addr = None if voice >= det.track_voices else _voice_addr(sid, det, i, voice)
            flags.append(addr is not None)
            voices.append(list(DEFAULT_TRACK) if addr is None else
                          _build_track(data, addr, det.read_track_version, None,
                                       det.transpose_operand))
        built.append(voices)
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
    for i, (ok, play) in enumerate(zip(usable, playable)):
        if ok and not play:
            log(f"*** SUBTUNE ${i:X} PLAYS NO EXISTING PATTERN, DROPPED ***")
            built[i] = [list(DEFAULT_TRACK) for _ in range(3)]

    keep = max((i + 1 for i, ok in enumerate(playable) if ok), default=0)
    if keep < subtunes:
        log(f"Header claims ${subtunes:X} subtune(s); last usable is "
            f"${keep - 1:X}, dropping {subtunes - keep} phantom")

    for i in range(keep):
        for voice in range(3):
            if voice < det.track_voices and not addr_ok[i][voice]:
                log(f"*** SUBTUNE ${i:X} (VOICE {voice:X}) ADDRESS OUT OF RANGE, CAN'T CONVERT ***")
            tracks.append(built[i][voice])

    # No fabricated placeholder subtune when nothing survived. Returning one
    # kept the .sng structurally valid, but it also referenced pattern 0, which
    # made a file with no playable subtune look sound to every check downstream
    # -- ACE 2 reported 15599 bytes of nothing. An empty list is the honest
    # answer; convert() turns it into a refusal.

    return tracks
