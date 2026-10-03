"""Tempo, the player's song speed, outer gate and pack multiplier (split out of goatwriter.py, text moved unchanged)."""
from __future__ import annotations

import re
from dataclasses import (dataclass, replace)
from fractions import (Fraction)
from typing import (List, Optional, Tuple)

from ..detect import (Detection)
from ..sidfile import (SidFile)
from .constants import (_ABS_X_LOAD, _ADJACENT_TABLE_WINDOW, GT_MIN_TEMPO,
                        MAX_ROW_DENOMINATOR, MAX_SANE_SPEED_RELOAD, OUTER_GATE,
                        OUTER_GATE_PAL, OUTER_GATE_RTS, OUTER_GATE_RTS_ZP,
                        PAL_NTSC_ENTRY, PAL_NTSC_FLAG_LDX, PAL_NTSC_WINDOW,
                        SPEED_GATE, SPEED_GATE_IMM, SPEED_GATE_ZP,
                        SPEED_RELOAD_STORE, SPEED_TABLE_LOAD,
                        TEMPO_FASTEST_STEADY, _X_RELOADERS)
@dataclass(frozen=True)
class SongSpeeds:
    """Frames per duration unit, per subtune, read from the player.

    `frames[s]` is reload+1 for subtune `s`, or None where the table byte is
    not a sane speed (over-counted subtunes read past the real table).
    """
    frames: Tuple[Optional[int], ...]
    reload_addr: int
    table_addr: Optional[int]    # None = static reload byte, one speed for all
    # Reload of the outer counter that skips the gate, per subtune. Empty when
    # the player has no such counter -- which is most of the corpus.
    skip: Tuple[Optional[int], ...] = ()
    skip_table_addr: Optional[int] = None

    def frames_for(self, subtune: int) -> Optional[int]:
        if 0 <= subtune < len(self.frames):
            return self.frames[subtune]
        return None

    def skip_for(self, subtune: int) -> Optional[int]:
        if 0 <= subtune < len(self.skip):
            return self.skip[subtune]
        return None

    def exact_row(self, subtune: int = 0):
        """The corrected row as an exact Fraction of frames, or None.

        `(reload + 1) * (O + 1) / O` is rational, and a row of p/q frames is
        expressible exactly by packing at `-Sq` with a tempo of p: a row lasts
        tempo/multiplier frames. That is what MAX_ROW_DENOMINATOR bounds --
        the multiplier is a real call rate on real hardware, and q of 127
        would ask the player to run 6350 times a second.
        """
        f = self.frames_for(subtune)
        o = self.skip_for(subtune)
        if f is None:
            return None
        return Fraction(f * (o + 1), o) if o else Fraction(f)

    def encodable_frames(self, subtune: int = 0) -> Optional[int]:
        """`true_frames` when Goattracker can express it exactly, else None.

        A row is a whole number of play calls, so a corrected row of 2.67 --
        the player skipping one frame in four -- has no tempo. Rounding it
        would trade a known 25% error for an unknown one, and the honest
        encoding of a fractional row is §8's re-gridding, not a round(). Only
        the whole-number cases are returned, which on this corpus is six
        files against forty-two fractional ones.
        """
        t = self.true_frames(subtune)
        if t is None:
            return None
        return int(round(t)) if abs(t - round(t)) < 0.02 else None

    def true_frames(self, subtune: int = 0) -> Optional[float]:
        """Frames per duration unit *including* the outer counter's skips.

        Non-integer by nature: a gate of 2 frames skipping one frame in four
        gives rows of 3, 3 and 2 frames, an average of 2.67. Nothing in
        Goattracker can express that, which is why this is reported rather
        than encoded -- `frames_for` is still what the writer uses. See
        whats-next.md 7b and 8.
        """
        f = self.frames_for(subtune)
        o = self.skip_for(subtune)
        if f is None:
            return None
        if not o:
            return float(f)
        return f * (o + 1) / o

    @property
    def source(self) -> str:
        if self.table_addr is not None:
            return f"per-subtune table at ${self.table_addr:04X}"
        return f"static reload byte at ${self.reload_addr:04X}"


def _gate_hits(sid: SidFile):
    """(match offset, reload address) for every speed-gate shape in the file.

    The immediate-reload spelling is a *fallback*: it is consulted only where
    the absolute one matched nothing, because 33 of the 35 corpus files
    carrying it also carry the absolute form, and reading both would hand two
    candidates to a chooser with no way to tell them apart. It rescues Ninja
    and Mega Apocalypse, whose players have only this one.

    For that spelling the "reload address" is the address of the *immediate's
    own operand byte*, which is what makes `_speeds_for_reload` work
    unchanged: a per-subtune table is written into that operand by the init
    (`LDA table,X / STA <the immediate>`, the self-modifying idiom
    `_find_outer_gate` reads for the same reason), and where no init writes it
    the byte sitting there is the value.
    """
    data = sid.data
    hits = []
    for m in SPEED_GATE.finditer(data):
        ctr, rel, ctr2 = m.group(1), m.group(2), m.group(3)
        if ctr != ctr2:
            continue
        hits.append((m.start(), rel[0] | rel[1] << 8))
    if hits:
        return hits
    for m in SPEED_GATE_IMM.finditer(data):
        if m.group(1) != m.group(3):
            continue
        hits.append((m.start(), sid.to_address(m.start() + 6)))
    if hits:
        return hits
    # Last, and only for a file neither spelling above could read: the
    # zero-page counter. Its reload is still an absolute table address,
    # so `_speeds_for_reload` needs nothing new.
    for m in SPEED_GATE_ZP.finditer(data):
        if m.group(1) != m.group(3):
            continue
        rel = m.group(2)
        hits.append((m.start(), rel[0] | rel[1] << 8))
    return hits


def _pal_ntsc_indexed(data: bytes, load_pos: int) -> bool:
    """Whether the `LDA table,X` at `load_pos` indexes by TERRITORY, not subtune.

    Both gate readers assume X holds the subtune number, because in 82 of the
    83 convertible files it does. Skate or Die intro is the exception, and it
    is the one this repo had already guessed at: CLAUDE.md carried "one gate
    picks its reload from the PAL/NTSC flag" as a standing hypothesis for this
    very file, found real in Las Vegas first. Its init is

        $3FE0  LDX $02A6        ; 0 = NTSC
        $3FE3  LDA $3FDA,X      ; 7F 04   -- the OUTER gate's skip
        $3FE6  STA $45DD
        $3FE9  STA $4B14
        $3FEC  LDA $3FDC,X
        $3FEF  STA $4801
        $3FF2  LDA $3FDE,X      ; 02 01   -- the inner gate's reload
        $3FF5  STA $4B13

    -- two of the three tables the gate readers already locate, indexed by
    territory. Reading entry 0 gave NTSC's 127 and 2, so the row came out
    384/127 = 3.024 frames; MAX_ROW_DENOMINATOR refuses 127 and it fell back
    to a flat 3, which `--pace` measured as a ratio of exactly 1.200 with an
    IQR of 1.200-1.200 over 826 gaps -- a wrong constant, not a mechanism.
    PAL's entries are 4 and 1, so the row is 2 x 5/4 = **5/2 = 2.50 frames**,
    which packs exactly as tempo 5 at `-S2`.

    Note what makes this file need its own reading at all: it installs its own
    IRQ, so its PSID header names NO play routine, and `_find_outer_gate`'s
    rescue spellings are anchored at the play address and correctly decline.
    Nothing anchored there could ever have reached it.

    Scoped by construction to a load whose index register was last set from
    `$02A6`: censused over the corpus this matches EXACTLY ONE FILE, and the
    `LDY $02A6` spelling occurs in none, so only the X form is read.
    """
    lo = max(0, load_pos - PAL_NTSC_WINDOW)
    seg = data[lo:load_pos]
    i = seg.rfind(PAL_NTSC_FLAG_LDX)
    if i < 0:
        return False
    return not any(b in _X_RELOADERS for b in seg[i + 3:])


def _speeds_for_reload(sid: SidFile, rel_addr: int) -> Optional[SongSpeeds]:
    """SongSpeeds for one gate, from its init table or its static byte."""
    data = sid.data
    rel_bytes = bytes([rel_addr & 0xFF, rel_addr >> 8])
    load = re.escape(SPEED_TABLE_LOAD) + b"(..)" + \
        re.escape(SPEED_RELOAD_STORE + rel_bytes)
    n = max(sid.subtunes, 1)
    for m in re.finditer(load, data, re.DOTALL):
        t = m.group(1)
        table_addr = t[0] | t[1] << 8
        off = sid.to_offset(table_addr)
        if not 0 <= off < len(data):
            continue
        if _pal_ntsc_indexed(data, m.start()):
            # Territory-indexed: one value for every subtune, not one each.
            vals = data[off + PAL_NTSC_ENTRY:off + PAL_NTSC_ENTRY + 1] * n
        else:
            vals = data[off:off + n]
        frames = tuple(v + 1 if v <= MAX_SANE_SPEED_RELOAD else None
                       for v in vals)
        if frames and frames[0] is not None:
            return SongSpeeds(frames, rel_addr, table_addr)
    off = sid.to_offset(rel_addr)
    if 0 <= off < len(data) and data[off] <= MAX_SANE_SPEED_RELOAD:
        return SongSpeeds((data[off] + 1,) * n, rel_addr, None)
    return None


def _adjacent_table_bound(sid: SidFile, bd_pos: int,
                          table_addr: int) -> Optional[int]:
    """Distance to the nearest *other* per-subtune table read the same way.

    `_speeds_for_reload`'s table can be over-read when a file's header
    over-counts its subtunes, and it guards against that with
    MAX_SANE_SPEED_RELOAD -- a magnitude bound that works because the bytes
    past a frames table's real end are usually code. That bound is wrong for
    the outer gate's own values: 16 corpus files carry a genuine skip
    reload above it (Ricochet's 127 is `outer_gate_skip`'s own worked
    example of "almost no skip, and correct for a reason"), so nulling
    anything over MAX_SANE_SPEED_RELOAD here would falsely null real data on
    16 files to fix one.

    What actually bounds Knucklebusters' table is structural, not a value:
    its init reads three 8-byte per-subtune tables back to back (`LDA
    $0978,X`, `LDA $0968,X`, `LDA $0970,X`), so $0970's table is exactly 8
    bytes before $0978's begins -- and a header that claims 11 subtunes
    reads 3 bytes into the next table, at values ($02) too small for any
    magnitude guard to catch. W_A_R (also a Warhawk-engine file) carries the
    identical shape at $E90F/$E917. Searching nearby code for another `LDA
    table,X` whose address sits just past this one's finds that boundary
    directly, for both.
    """
    lo = max(0, bd_pos - _ADJACENT_TABLE_WINDOW)
    hi = min(len(sid.data), bd_pos + _ADJACENT_TABLE_WINDOW)
    best = None
    for m in _ABS_X_LOAD.finditer(sid.data, lo, hi):
        addr = m.group(1)[0] | (m.group(1)[1] << 8)
        if addr <= table_addr:
            continue
        gap = addr - table_addr
        if best is None or gap < best:
            best = gap
    return best


def _find_outer_gate(sid: SidFile, subtunes: int):
    """(per-subtune reloads, table address) for the counter above the gate.

    The reload is an *immediate*, so the byte sitting in the file image is
    whatever the last init left there -- Tarzan's reads 11 while its subtune 0
    actually runs 2. Where the init writes that operand from a table
    (`LDA table,X / STA <the immediate's own address>`, the same self-modifying
    idiom the players use elsewhere) the table is the answer and the image byte
    is a decoy. v0.5.102 read the image byte and concluded the value was a
    per-player constant; it is per subtune in 32 of the 51 files that have it.
    """
    m = OUTER_GATE.search(sid.data) or OUTER_GATE_RTS.search(sid.data)
    if not m:
        # The two rescue spellings, in the order that keeps them
        # harmless: only a file the pair above could not read reaches
        # here. Both carry a LITERAL reload rather than a per-subtune
        # table, so there is no init write to chase -- the immediate IS
        # the answer for every subtune.
        # ANCHORED AT THE PSID PLAY ADDRESS, not searched file-wide.
        # An outer gate is the first thing the frame routine does, so it
        # sits exactly there -- Samantha Fox $7006, Las Vegas $5006,
        # Spellbound $E012, all three the header's own playAddress. The
        # zero-page shape is otherwise common enough that a file-wide
        # search matched ordinary code in Spellbound and took its melody
        # from 93% to 38%; the byte offset is what makes these safe.
        # A file whose header names no play routine (it installs its own
        # IRQ) anchors nothing and declines, which is the right answer
        # rather than a fallback to guessing.
        at = sid.to_offset(sid.play_addr) if sid.play_addr else None
        if at is None or not 0 <= at < len(sid.data):
            return (), None
        mz = OUTER_GATE_RTS_ZP.match(sid.data, at)
        if mz is not None and mz.group(1) == mz.group(3):
            return (mz.group(2)[0] or None,) * max(subtunes, 1), None
        mp = OUTER_GATE_PAL.match(sid.data, at)
        if mp is not None and mp.group(1) == mp.group(3):
            # group(2) is the PAL immediate -- the second LDY, taken
            # when $02A6 is non-zero. The NTSC one is deliberately not
            # read: this corpus is PAL and every measurement here
            # compares against a 50Hz trace.
            return (mp.group(2)[0] or None,) * max(subtunes, 1), None
        return (), None
    ctr = m.group(1)[0] | (m.group(1)[1] << 8)
    if ctr != (m.group(3)[0] | (m.group(3)[1] << 8)):
        return (), None                     # decrements one cell, reloads another
    imm_off = m.start() + 6
    imm_addr = sid.to_address(imm_off)
    store = bytes([0x8D, imm_addr & 0xFF, imm_addr >> 8])
    i = sid.data.find(store)
    while i >= 0:
        if i >= 3 and sid.data[i - 3] == SPEED_TABLE_LOAD[0]:
            table = sid.data[i - 2] | (sid.data[i - 1] << 8)
            off = sid.to_offset(table)
            if 0 <= off < len(sid.data):
                n = max(subtunes, 1)
                if _pal_ntsc_indexed(sid.data, i - 3):
                    # Territory-indexed, so neither the subtune count nor the
                    # adjacent-table bound applies -- there is one value.
                    vals = sid.data[off + PAL_NTSC_ENTRY:
                                    off + PAL_NTSC_ENTRY + 1] * n
                    return tuple(v or None for v in vals), table
                bound = _adjacent_table_bound(sid, i - 3, table)
                if bound is not None and bound < n:
                    n = bound
                vals = sid.data[off:off + n]
                return tuple(v or None for v in vals), table
        i = sid.data.find(store, i + 1)
    return (sid.data[imm_off] or None,) * max(subtunes, 1), None


def outer_gate_skip(sid: SidFile, subtune: int = 0) -> Optional[int]:
    """The reload of the counter above the player's gate, or None.

    `find_song_speeds` already carries this as `SongSpeeds.skip`, but only for
    a player whose *inner* speed gate it also found -- and the two are
    independent readings. Anything that needs the counter alone should ask
    here rather than through a `SongSpeeds` that may be None for a reason
    having nothing to do with the counter.

    **The file this was written for no longer needs it.** Ninja had the outer
    counter and no readable inner gate until v0.5.267 read its immediate
    reload spelling (`SPEED_GATE_IMM`), and `find_song_speeds` answers for it
    now. The separation still holds -- a player can have either counter
    without the other -- so this stays, with its justification re-stated
    rather than its example.
    """
    vals, _ = _find_outer_gate(sid, max(sid.subtunes, 1))
    if 0 <= subtune < len(vals):
        return vals[subtune]
    return None


def find_song_speeds(sid: SidFile,
                     det: Detection | None = None) -> Optional[SongSpeeds]:
    """The tune's frames-per-duration-unit, or None where it cannot be read.

    A file can hold several gate shapes (5 Title Tunes carries five separate
    players; One on One's sample data happens to contain the byte sequence).
    With a detection to hand, the gate nearest the detected instrument table is
    the detected player's own. Without one, agreement across all hits is
    required -- disagreeing hits mean the wrong one may be chosen, and a wrong
    tempo is worse than the old constant.
    """
    candidates = []
    for pos, rel_addr in _gate_hits(sid):
        speeds = _speeds_for_reload(sid, rel_addr)
        if speeds is not None:
            candidates.append((pos, speeds))
    if not candidates:
        # **No inner gate is a reading, not a refusal -- if there is an outer
        # one.** The two counters are independent (`outer_gate_skip` says so
        # in as many words), and a player with only the outer one advances its
        # pattern exactly once per working call: the row *is* one tick, and
        # the skip is the whole of the timing.
        #
        # Mozart is the one corpus file shaped that way, and returning None
        # for it cost a factor of two. Its play entry point at $0829 is the
        # gate itself, in the inverted spelling `OUTER_GATE_RTS` matches:
        #
        #     0829  DEC $0C33
        #     082C  BPL $0834        ; >= 0 -> do the update
        #     082E  LDA #$02 / STA $0C33
        #     0833  RTS              ; underflow -> reload and skip this call
        #
        # Two updates every three calls, so a tick is 1.5 frames. Its waits
        # are 3 and 7, giving 4 and 8 updates, and the original's note gaps
        # are 6 and 12 frames exactly. With no speeds the tempo fell back to
        # the constant 3 at `-S1` -- 3 frames a row against the player's 1.5,
        # which `drift` reported as **+1000.0 per 1000 with a scatter of
        # 0.0**, a conversion running at precisely half speed. As `frames=1`
        # with `skip=2` the row is 3/2 frames, which packs exactly as tempo 3
        # at `-S2`.
        #
        # Scoped by construction to a file that has an outer gate and no inner
        # one: 10 corpus files lack the inner gate and 9 of them lack both, so
        # they are untouched and keep the fallback constant.
        skip, skip_table = _find_outer_gate(sid, max(sid.subtunes, 1))
        if skip and skip[0]:
            n = max(sid.subtunes, 1)
            return SongSpeeds((1,) * n, -1, None,
                              skip=skip, skip_table_addr=skip_table)
        return None
    skip, skip_table = _find_outer_gate(sid, max(sid.subtunes, 1))
    candidates = [(pos, replace(sp, skip=skip, skip_table_addr=skip_table))
                  for pos, sp in candidates]
    if len(candidates) == 1:
        return candidates[0][1]
    if det is not None and det.instr_start >= 0:
        return min(candidates, key=lambda c: abs(c[0] - det.instr_start))[1]
    first = candidates[0][1]
    if all(c[1].frames == first.frames for c in candidates):
        return first
    return None


def effective_frames(speeds: Optional[SongSpeeds], subtune: int = 0,
                     skip_gate: bool = False):
    """Frames per unit as the tempo should encode it.

    Without `skip_gate` this is the speed gate's own reload+1, which is what
    every version before v0.5.119 used. With it, the counter above the gate is
    taken into account wherever the corrected row is a whole number -- see
    SongSpeeds.encodable_frames and whats-next.md §7b.
    """
    if speeds is None:
        return None
    if skip_gate:
        got = speeds.encodable_frames(subtune)
        if got is not None:
            return got
        exact = speeds.exact_row(subtune)
        if exact is not None and exact.denominator <= MAX_ROW_DENOMINATOR:
            return exact
    return speeds.frames_for(subtune)


def pack_subtune(speeds: Optional[SongSpeeds], start_song: int) -> int:
    """The subtune whose clock the packed `.sid`'s `-S` factor must serve.

    A packed file has ONE call rate and its subtunes disagree about what they
    want. Until v0.5.410 the rate was taken from subtune 0, with
    `derived_group_tempos` calling it "the canonical tune, and what a packed
    .sid plays by default". The second half of that is simply false: what a
    packed `.sid` plays by default is the PSID header's `startSong`, which is
    `fidelity.resolve_subtune`'s rule and the reason it exists -- "the subtune
    a player selects when the user selects none, and therefore the one that is
    *the tune*". Six corpus files set it past subtune 0.

    Measured over the corpus at v0.5.409, 12 files have SOME subtune wanting a
    higher multiplier than subtune 0 -- but only TWO have a *start* subtune
    that does, and those two are the whole of this rule's reach:

        Kings_of_the_Beach_ingame  start 4   8/3 frames  -S1 -> -S3
        Knucklebusters             start 1   7/3 frames  -S1 -> -S3

    **Serving every subtune is not the alternative it looks like.** A row of
    p/q frames is exact at any multiple of q, so a rate exact for all of them
    is the LCM of their denominators: 24 for Monty and Knucklebusters, 40 for
    Delta and Wiz, and **140 for Flash Gordon**. MAX_ROW_DENOMINATOR is 10 and
    its comment sizes that at about three quarters of a PAL frame's 19656
    cycles, with 127 "not a call rate at all" -- so the exact rule is
    unreachable for half this population, and `max()` over the subtunes is not
    a weaker version of it but a different, inexact compromise that ALSO costs
    the subtune everyone actually hears: every per-call rate this writer emits
    is divided by the multiplier at the point it is encoded, and CLAUDE.md
    records that a file packed above `-S4` cannot be judged on a normal trace.
    Delta would go to `-S10` to serve its subtune 10.

    So the other ten files keep a rate that is wrong for one of their
    non-starting subtunes, and that is a real and UNFIXED defect -- it is just
    not one a single packed file can fix. Anything wanting per-subtune rates
    needs a file per subtune, which is a different feature.

    Clamped to the speeds table, which every caller derives from the same
    `find_song_speeds`, because ALL FIVE call sites must agree: a `.sng`
    written for one rate and packed at another is the Las Vegas failure --
    silence, with `melody` still reading 100%.
    """
    s = max(0, start_song - 1)
    if speeds is not None and s >= len(speeds.frames):
        return 0
    return s


def recommended_multiplier(speeds: Optional[SongSpeeds],
                           subtune: int = 0, skip_gate: bool = False) -> int:
    """gt2reloc -S value under which this tune's tempo is expressible.

    A row must last `frames` player calls scaled by the multiplier, and
    Goattracker's fastest steady row is three calls (values 2 and 3 both give
    tempo 2; below that is funktempo). So frames >= 3 works at 1x, frames == 2
    needs the play routine called twice per frame, and frames == 1 three
    times. greloc.c:1595 arms a CIA stub for exactly this.
    """
    f = effective_frames(speeds, subtune, skip_gate)
    if f is None:
        return 1
    q = getattr(f, "denominator", 1)
    if q > 1:
        # A row of p/q frames is exact at -Sq, and stays exact at any multiple
        # of q -- so clear the denominator first, then raise it further if the
        # row is still too short to express.
        return q * max(1, -(-(GT_MIN_TEMPO + 1) // int(f * q // 1 or 1)) if
                       f * q < GT_MIN_TEMPO + 1 else 1)
    if f >= GT_MIN_TEMPO + 1:
        return 1
    return -(-(GT_MIN_TEMPO + 1) // int(f))


def file_multiplier(sid: SidFile, speeds: Optional[SongSpeeds],
                    skip_gate: bool = False) -> int:
    """The `gt2reloc -S` factor the whole file is packed at.

    `recommended_multiplier` at the start subtune (`pack_subtune`) -- except
    for one player of a compilation (`detect.PlayerView`), which is packed
    inside the compilation and so at ITS factor, carried on the view as
    `pack_multiplier`. 5_Title_Tunes' players 1 and 4 read rows of 2 frames
    (`-S2` on their own) inside a file that starts on player 0's 4-frame rows
    (`-S1`): converted at their own factor they would be packed at half the
    call rate they were written for; at the file's, every per-call rate is
    right and only the row clamps to the fastest steady tempo, as any
    non-starting subtune's already does. Every call site that chose the
    factor (`derived_group_tempos`, `orderlist_tempo_values`,
    `convert._derived_multiplier`) goes through here, so they cannot disagree.
    """
    forced = getattr(sid, "pack_multiplier", 0)
    if forced:
        return forced
    return recommended_multiplier(speeds, pack_subtune(speeds, sid.start_song),
                                  skip_gate)


def tempo_command_value(sid: SidFile, subtune: int = 0,
                        speeds: Optional[SongSpeeds] = None,
                        multiplier: int = 1, skip_gate: bool = False) -> int:
    """CMD_SETTEMPO value for this subtune: its player's frames per unit.

    One converted row is one duration unit, and the player's speed gate says a
    unit lasts `frames` frames -- so a row must last `frames` play calls, and
    the command value for any count >= 3 *is* the count (gplay.c:494
    decrements values >= 3, :325 makes a row last tempo+1 calls).

    `multiplier` is the gt2reloc -S factor the caller intends to pack with:
    at 50*m Hz a row of the same real length needs frames*m calls. Where the
    speed cannot be read (no gate shape, a prescaler player, an over-counted
    subtune) the old constant stands, scaled the same way, so a file keeps one
    consistent timebase.
    """
    if speeds is None:
        speeds = find_song_speeds(sid)
    f = effective_frames(speeds, subtune, skip_gate)
    if f is None:
        # The old constant, scaled to the caller's timebase: 3 calls at 1x is
        # 3*m calls at m-times the call rate.
        return min(TEMPO_FASTEST_STEADY * multiplier, 0x7F)
    # The floor is not only the funktempo boundary: every instrument this
    # writer emits carries gatetimer 2 (_write_instruments), and gplay.c:334
    # stops the song outright when gatetimer exceeds the channel's tick. A
    # command value of 3 lands as effective tempo 2 -- exactly at that
    # boundary -- so nothing below 3 may ever be emitted here.
    return min(max(int(f * multiplier), TEMPO_FASTEST_STEADY), 0x7F)


def orderlist_tempo_values(sid: SidFile, det: Detection,
                           reloads: List[dict],
                           tempo: int | str | None = None,
                           skip_gate: bool = False) -> List[dict]:
    """Each orderlist tempo command's operand, as a CMD_SETTEMPO value.

    One map per track, keyed by orderlist position, exactly as
    `tracks.convert_tracks` filled them. The track index says which subtune a
    map belongs to (three tracks each, in order), because the operand is only
    half of the answer -- the other half is that subtune's own row length.

    **The operand is the OUTER counter's reload, not a row length.** Rasputin
    `$C012` is

        DEC $C53A / BPL work / LDA $C539 / STA $C53A / JMP exit

    -- the shape § 7.rrrr calls the outer gate, spelled with a *cell* reload
    where `OUTER_GATE` expects an immediate, which is why `find_song_speeds`
    reports no `skip` for this file. It works on `R` calls in every `R + 1`,
    so a row of `frames` working calls lasts `frames * (R + 1) / R` real
    frames: exactly `SongSpeeds.exact_row`'s factor, with `R` changing
    mid-song. The inner gate, and so `frames`, is `$C062` and does not move.

    Read as a row length instead, Rasputin's `$FE 78` would be 121 frames a
    row against its neighbours' 3 -- ten seconds on a pattern the same list
    plays at speed twenty entries earlier. That implausibility is what sent
    this back to the disassembler; the ratio form gives 2.017 frames against
    2.033, which is the accelerando it sounds like.

    Rounded, because the product rarely lands on a whole number of calls and
    Goattracker has no fractional tempo: 2.667 frames at `-S2` is 5.33 calls
    and is written as 5. The alternative to a rounded change is the *absent*
    one, which is what this file had -- every row 4 calls where the truth
    ranges from 4.03 to 6.
    """
    speeds = find_song_speeds(sid, det)
    mult = 1
    if tempo == "auto" and det.frames_per_row <= 1:
        # The same pack factor `derived_group_tempos` picks, from the same
        # subtune -- these two write operands onto one timebase.
        mult = file_multiplier(sid, speeds, skip_gate)
    out: List[dict] = []
    for ti, m in enumerate(reloads):
        # `frames_for`, not `effective_frames`: the outer counter's factor is
        # what the operand *is*, so taking a correction for it out of the file
        # image as well would apply it twice.
        base = None if speeds is None else speeds.frames_for(ti // 3)
        if base is None:
            base = TEMPO_FASTEST_STEADY
        out.append({at: min(max(int(round(base * (r + 1) / r * mult)),
                                TEMPO_FASTEST_STEADY), 0x7F)
                    for at, r in m.items() if r})
    return out


def derived_group_tempos(sid: SidFile, det: Detection, groups: int,
                         skip_gate: bool = False) -> Tuple[List[int], int, str]:
    """Per-subtune CMD_SETTEMPO values, the -S multiplier, and a source note.

    `groups` is how many 3-track groups the caller has, which equals the
    header subtune numbering as long as no subtune has been split (the caller
    checks that). The multiplier is chosen from the subtune the file STARTS on
    (`pack_subtune`) and every subtune's value is scaled by it, so the whole
    file shares one timebase. It used to be chosen from subtune 0 on the
    reasoning that this is "what a packed .sid plays by default"; a packed
    .sid plays its header's `startSong`, and two corpus files were packed for
    a subtune they do not open on.
    """
    speeds = find_song_speeds(sid, det)
    mult = file_multiplier(sid, speeds, skip_gate)
    values = [tempo_command_value(sid, s, speeds, mult, skip_gate)
              for s in range(groups)]
    note = speeds.source if speeds is not None else \
        "no speed gate found, keeping the constant"
    return values, mult, note
