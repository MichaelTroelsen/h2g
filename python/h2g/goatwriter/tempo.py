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
                        TEMPO_FASTEST_STEADY, _X_RELOADERS,
                        CMD_FUNKTEMPO, CMD_SETTEMPO, FUNK_ROW_CALLS,
                        FUNK_SPEED_ENTRY, GT_MAX_TABLELEN)
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
    # Per PSID subtune, the player song its INIT actually starts, where that
    # is not the subtune's own number (`init_song_remap`). Empty for every
    # player whose init passes the subtune straight through.
    song_of: Tuple[Optional[int], ...] = ()

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


# How many `JMP`s to follow from the PSID play address to the routine's first
# instruction (Kentilla's play address is the gate itself; a jump table in
# front of it is followed, never searched past).
PLAY_ENTRY_JMPS = 4


def play_entry(sid: SidFile) -> Optional[int]:
    """Image offset of the first instruction the play routine runs, or None.

    Follows a chain of `JMP`s from the PSID play address. None where the
    header names no play routine (the tune installs its own IRQ), or the chain
    leaves the image.
    """
    if not sid.play_addr:
        return None
    at = sid.to_offset(sid.play_addr)
    for _ in range(PLAY_ENTRY_JMPS + 1):
        if not 0 <= at < len(sid.data) - 2:
            return None
        if sid.data[at] != 0x4C:            # JMP abs
            return at
        at = sid.to_offset(sid.data[at + 1] | sid.data[at + 2] << 8)
    return None


def outer_gate_match(sid: SidFile):
    """The outer-gate match every reader of the gate takes, or None.

    The first `OUTER_GATE`, then the first `OUTER_GATE_RTS`, in the file --
    **except that a gate the play routine itself ENTERS wins** when it is the
    `RTS` spelling: the gate the PSID play address reaches is the one that
    runs on every frame the player is called. Bump_Set_Spike carries two of
    them back to back, the NTSC compensator's first and the PAL one the play
    address names:

        B006  LDA $02A6 / BNE $B016      ; PAL -> skip the NTSC gate
        B00B  DEC $B4F5 / BPL $B016 / LDA #$05 / STA $B4F5 / RTS    (NTSC)
                                         ; (BPL lands on the PAL gate)
        B016  DEC $B4F4 / BPL $B021 / LDA #$09 / STA $B4F4 / RTS    (play)

    `search` returned the NTSC one at `$B00B` -- reload 5, the other
    territory's -- so a PAL conversion ran a skip of 6 calls where the
    original skips every 10th: 3/214, 2/257 and 1/197 onsets exact over 60 s,
    the offset growing every row. A file whose play entry is not an `RTS`
    gate keeps the first match, so this moves only a file with two or more
    gates ahead of the play address's own.
    """
    data = sid.data
    first = OUTER_GATE.search(data) or OUTER_GATE_RTS.search(data)
    at = play_entry(sid)
    if at is not None and (first is None or first.start() != at):
        entered = OUTER_GATE_RTS.match(data, at)
        if entered is not None:
            return entered
    return first


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
    m = outer_gate_match(sid)
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


def init_song_remap(sid: SidFile, speeds: SongSpeeds) -> Tuple[Optional[int], ...]:
    """Per PSID subtune, the player song its init starts when that is another
    song than the subtune's own number, else None; empty where nothing differs.

    Only a PRIMED player is read (the init loads the subtune's outer skip
    from a table and stores it into the outer cell and the gate's reload,
    `arpeggio._init_primes_outer`): there the init run (`arpeggio._init_cells`)
    leaves the clock the subtune really runs at, as the speed cell's value and
    the outer cell, and that pair names the song when exactly one table entry
    carries it. Dragons_Lair_Part_II is the corpus case: its init sends PSID 0
    to song 9, whose row is 2 frames x 4/3 = 8/3, while subtune 0's own table
    entries read 5/2. `pack_subtune` asked for the table's subtune 0, so the
    file was packed at -S2 for a 5/2 row and the tune everyone hears (the
    header's startSong) ran 6.25% fast.

    A subtune whose own entry already matches the init run keeps its number;
    an ambiguous or absent match declines (None) rather than guess.
    """
    from . import arpeggio as _arp      # arpeggio imports this module
    m = outer_gate_match(sid)
    if m is None or speeds.reload_addr < 0 or not speeds.skip:
        return ()
    outer = m.group(1)
    imm_addr = sid.to_address(m.start() + 6)
    if _arp._init_primes_outer(sid, outer, imm_addr) is None:
        return ()
    cell = outer[0] | outer[1] << 8
    out: List[Optional[int]] = []
    for g in range(max(sid.subtunes, 1)):
        ran = _arp._init_cells(sid, g)
        song = None
        if ran is not None:
            _, read = ran
            try:
                skip, imm = read(cell), read(imm_addr)
                if skip == imm and skip:
                    want = (read(speeds.reload_addr) + 1, skip)
                    own = (speeds.frames_for(g), speeds.skip_for(g))
                    if own != want:
                        hits = [k for k in range(len(speeds.frames))
                                if (speeds.frames_for(k), speeds.skip_for(k))
                                == want]
                        if len(hits) == 1:
                            song = hits[0]
            except LookupError:
                pass
        out.append(song)
    return tuple(out) if any(v is not None for v in out) else ()


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
    candidates = [(pos, replace(sp, song_of=init_song_remap(sid, sp)))
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
    needs a file per subtune, which is a different feature. ONE case of it is
    now fixed inside the file: a subtune whose row is exactly 2 calls at the
    file's factor plays it through CMD_FUNKTEMPO (`write_funktempo`) instead
    of clamping to 3 -- 5_Title_Tunes 1 and 4, Auf_Wiedersehen_Monty 12,
    Gerry_the_Germ 2, Human_Race 4 at v0.5.509.

    Clamped to the speeds table, which every caller derives from the same
    `find_song_speeds`, because ALL FIVE call sites must agree: a `.sng`
    written for one rate and packed at another is the Las Vegas failure --
    silence, with `melody` still reading 100%.
    """
    s = max(0, start_song - 1)
    if (speeds is not None and s < len(speeds.song_of)
            and speeds.song_of[s] is not None):
        return speeds.song_of[s]
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
    right and the 2-call row is CMD_FUNKTEMPO (`write_funktempo`; it clamped
    to 3 calls, 1.5x slow, before). Packing the whole compilation at `-S2`
    was measured instead and lost player 4 to the pulse-table cap. Every call
    site that chose the
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
                        multiplier: int = 1, skip_gate: bool = False,
                        funk: bool = False) -> int:
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

    `funk` lets a row of EXACTLY two calls through as `FUNK_ROW_CALLS`, which
    is not a CMD_SETTEMPO value (2 plays as 3 calls, gplay.c:494) but a
    placeholder `write_funktempo` turns into CMD_FUNKTEMPO + `02 02` once the
    speed table exists. Until then every reader of the value -- row_calls,
    the per-instrument hard-restart bound, the pulse-phase walk, the arp
    phases -- sees the row the file really plays. The caller passes it only
    for a GTS5 file (a GTS2 file has no speed table). 5_Title_Tunes' players 1
    and 4 are the case: 2-frame rows inside a file packed at player 0's -S1,
    clamped to 3 calls (1.5x slow, melody 80.6 / 81.7) without it.
    """
    if speeds is None:
        speeds = find_song_speeds(sid)
    f = effective_frames(speeds, subtune, skip_gate)
    if funk and f is not None and f * multiplier == FUNK_ROW_CALLS:
        return FUNK_ROW_CALLS
    if f is None:
        # The old constant, scaled to the caller's timebase: 3 calls at 1x is
        # 3*m calls at m-times the call rate.
        return min(TEMPO_FASTEST_STEADY * multiplier, 0x7F)
    # The floor is not only the funktempo boundary: every instrument this
    # writer emits carries gatetimer 2 (_write_instruments), and gplay.c:334
    # stops the song outright when gatetimer exceeds the channel's tick. A
    # command value of 3 lands as effective tempo 2 -- exactly at that
    # boundary -- so nothing below 3 may ever be emitted as CMD_SETTEMPO. The
    # `funk` placeholder above is the one exception, and its instruments are
    # bounded to gatetimer 1 by row_calls 2.
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

    The rounding is per CHANGE, and what it leaves over is no longer lost:
    `orderlist_tempo_calls` keeps the exact quotient, and
    `patterns._compensate_fractional_rows` spends the remainder inside the
    patterns of each segment.
    """
    return [{at: min(max(int(round(c)), TEMPO_FASTEST_STEADY), 0x7F)
             for at, c in m.items()}
            for m in orderlist_tempo_calls(sid, det, reloads, tempo,
                                           skip_gate)]


def orderlist_tempo_calls(sid: SidFile, det: Detection,
                          reloads: List[dict],
                          tempo: int | str | None = None,
                          skip_gate: bool = False) -> List[dict]:
    """Each orderlist tempo command's row length in OUR play calls, unrounded.

    The quantity `orderlist_tempo_values` rounds into a `CMD_SETTEMPO` value,
    on the same timebase (same `frames_for`, same multiplier), so the two
    cannot disagree about which number was rounded. Rasputin subtune 0 at
    `-S2`: `2 * (R+1)/R * 2` calls, i.e. R 3 -> 5.333, R 5 -> 4.8, R 10 ->
    4.4, R 60 -> 4.067, R 120 -> 4.033, R 6 -> 4.667, R 2 -> 6.

    That is the segment's AVERAGE row. Where the change also restarts the
    gate's count (`Detection.track_fe_restarts_gate`, Rasputin), each
    segment is `restarted_gate_calls` long instead -- up to one frame
    shorter -- and `orderlist_tempo_clocks` says so.
    """
    out: List[dict] = []
    for m in _orderlist_tempo_terms(sid, det, reloads, tempo, skip_gate):
        row = {}
        for at, (base, r, mult) in m.items():
            if base is None:
                base = TEMPO_FASTEST_STEADY
            row[at] = (base * (r + 1) / r if r else base) * mult
        out.append(row)
    return out


def _orderlist_tempo_terms(sid: SidFile, det: Detection,
                           reloads: List[dict],
                           tempo: int | str | None = None,
                           skip_gate: bool = False) -> List[dict]:
    """{at: (frames a row works, the gate's reload R, multiplier)} per track.

    The three numbers both `orderlist_tempo_calls` and
    `orderlist_tempo_clocks` are made of, read once so they cannot disagree.
    `frames` is None where the player's speed gate could not be read.
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
        row = {}
        for at, r in m.items():
            if isinstance(r, tuple):
                # `$FD a b` (Knucklebusters, `Detection.track_fd_tempo`): BOTH
                # gates change, so the row is `(a + 1) * (b + 1) / b` frames
                # with nothing left over from the subtune's own opening. Read
                # only where the cell `a` is stored to IS the speed gate's
                # reload, so a command that writes some other cell declines.
                # The outer factor is taken only under `skip_gate`, which is
                # when `effective_frames` puts it into the opening row too;
                # without it the opening is the bare `A + 1` and so is this.
                a, b = r
                if (speeds is None or speeds.reload_addr != det.track_fd_tempo
                        or not 0 <= a < 0x80 or not 0 < b < 0x80):
                    continue
                row[at] = (a + 1, b if skip_gate else None, mult)
            elif r:
                row[at] = (base, r, mult)
        out.append(row)
    return out


def restarted_gate_calls(frames: int, reload: int, mult: int,
                         rows: int) -> int:
    """Our calls from a gate-restarting `$FE nn` to the start of row `rows`.

    Rasputin's handler stores the operand into the outer gate's counter as
    well as its reload (`detect._find_fe_gate_restart`). The change is read
    on a fetch call -- the first working call of the segment's row 0 -- and
    leaves the counter at R, so the next R calls work and the one after is
    skipped: the k-th skip follows working call k*R. Row `rows` starts on
    working call `w = frames * rows`, after `(w - 1) // R` skips (none before
    row 1). Per row that averages `frames * (R + 1) / R`, but every segment
    is `W / R - (W - 1) // R` frames SHORTER than the average says -- the
    skip the old cycle was working towards is dropped at the change, never
    made: 1 frame on an even segment at R = 2 (rows of 2, 3, 3, 3 ...
    frames, which is the original's opening gap of 11 frames against our
    12), 0.4 to 0.93 on Rasputin's other segments.
    """
    w = frames * rows
    return mult * (w + max(0, (w - 1) // reload))


def orderlist_tempo_clocks(sid: SidFile, det: Detection,
                           reloads: List[dict],
                           tempo: int | str | None = None,
                           skip_gate: bool = False) -> List[dict]:
    """{at: (frames, R, mult)} per track for `restarted_gate_calls`, or {}.

    Empty maps unless the `$FE nn` handler restarts the gate it reloads
    (`Detection.track_fe_restarts_gate`); where the speed gate was not read
    the row's working frames are not known either, so those changes keep
    the average row (`orderlist_tempo_calls`) alone. So does an operand of
    `$80` or more, which `BPL` reads as negative -- not the count
    `restarted_gate_calls` models (Rasputin's largest is `$78`).
    """
    terms = _orderlist_tempo_terms(sid, det, reloads, tempo, skip_gate)
    if not getattr(det, "track_fe_restarts_gate", False):
        return [{} for _m in terms]
    return [{at: t for at, t in m.items()
             if t[0] is not None and t[1] is not None and t[1] < 0x80}
            for m in terms]


def derived_group_tempos(sid: SidFile, det: Detection, groups: int,
                         skip_gate: bool = False,
                         funk: bool = False) -> Tuple[List[int], int, str]:
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
    values = [tempo_command_value(sid, s, speeds, mult, skip_gate, funk)
              for s in range(groups)]
    note = speeds.source if speeds is not None else \
        "no speed gate found, keeping the constant"
    return values, mult, note


def write_funktempo(patterns: List[List[int]], speed_table: List[tuple],
                    log=None) -> int:
    """Turn each `CMD_SETTEMPO FUNK_ROW_CALLS` placeholder into CMD_FUNKTEMPO.

    The placeholder is what `tempo_command_value(funk=True)` returns for a
    2-call row and `apply_tempos` writes like any other value. Here, after
    `build_speed_table` has numbered the slides, it becomes CMD_FUNKTEMPO
    pointing at one shared `02 02` entry (constants.CMD_FUNKTEMPO). Where the
    table is full the row falls back to the steady floor, TEMPO_FASTEST_STEADY
    -- the clamp every 2-call row had before -- and says so. Returns how many
    rows became CMD_FUNKTEMPO.
    """
    rows = [(p, r) for p in patterns for r in range(0, len(p) - 3, 4)
            if p[r + 2] == CMD_SETTEMPO and p[r + 3] == FUNK_ROW_CALLS]
    if not rows:
        return 0
    if (FUNK_SPEED_ENTRY not in speed_table
            and len(speed_table) >= GT_MAX_TABLELEN):
        for p, r in rows:
            p[r + 3] = TEMPO_FASTEST_STEADY
        if log:
            log(f"*** NO SPEED-TABLE ROW FOR FUNKTEMPO 02 02: {len(rows)} "
                f"2-call row tempo(s) clamped to {TEMPO_FASTEST_STEADY} calls ***")
        return 0
    if FUNK_SPEED_ENTRY not in speed_table:
        speed_table.append(FUNK_SPEED_ENTRY)
    index = speed_table.index(FUNK_SPEED_ENTRY) + 1
    for p, r in rows:
        p[r + 2], p[r + 3] = CMD_FUNKTEMPO, index
    if log:
        log(f"Funktempo...............: {len(rows)} 2-call row tempo(s) as "
            f"CMD_FUNKTEMPO -> speed table row {index} (02 02)")
    return len(rows)


# Instructions that leave A alone and are three bytes long: STA abs / abs,X /
# abs,Y and LDY abs,X. The set-up stage clears its cells with a run of these
# behind one `LDA #$00` (Monty `$E419`).
_A_KEEPING_3 = (0x8D, 0x9D, 0x99, 0xBC)


def _stage_clears(sid: SidFile, ctr: bytes) -> bool:
    """True when some `STA ctr` stores the A that `LDA #$00` loaded.

    Walks back from each `8D lo hi` naming the counter over A-preserving
    three-byte instructions to an `A9 00`. Straight-line bytes only: a branch
    target in between is not seen, which is why this reads a cleared cell and
    nothing else (a reload `LDA #$7F / STA ctr` is not zero and never matches).
    """
    data = sid.data
    sta = b"\x8d" + ctr
    at = data.find(sta)
    while at >= 0:
        i = at
        while i >= 3 and data[i - 3] in _A_KEEPING_3:
            i -= 3
        if i >= 2 and data[i - 2] == 0xA9 and data[i - 1] == 0x00:
            return True
        at = data.find(sta, at + 1)
    return False


def step_durations(sid: SidFile, rows: int) -> Optional[List[int]]:
    """Frames each of the song's first `rows` rows lasts in the ORIGINAL, or None.

    **THE ORIGINAL'S EXTRA FRAME IS A FREE-RUNNING COUNTER, so WHICH row takes
    it is known exactly -- and a pattern-global schedule cannot reproduce it.**
    IK+'s play routine (`$E056`) runs two counters per call:

        DEC $E696 / BPL +  / LDA #$70 / STA $E696 / JMP $E071   ; outer, 113 calls
        DEC $E694 / BPL $E071 / LDA $E695 / STA $E694           ; inner, reload 2
        $E071: ... LDA $E696 / BEQ nostep / LDA $E694 / CMP $E695 / BNE nostep

    the inner counter is skipped on the outer's underflow call and a row steps
    only on a call where the inner counter sits at its reload AND the outer is
    not 0. That is a row of 3 calls that lasts 4 whenever an outer underflow
    falls inside it: 80 such rows in the first 9000 frames, at frames fixed by
    the two counters' power-on values.

    Emulated from the file image's counters (both 0) after the first play call,
    which is the player's own set-up stage (`BIT $E699`, left at `$40` by the
    init), the steps land on **539 of 539 voice-0 attacks, 975 of 975 voice-1
    attacks and 1474 of 1487 voice-2 drum ticks** of a 180 s siddump of the
    original (`C:/t/ik-plus-sub99-priority/model7.py`), frame for frame.

    Returned only for exactly that shape: the `OUTER_GATE` jump spelling whose
    target is the inner gate's fall-through, the step test above reading both
    counters, and the staged play entry. Anything else is None -- a schedule
    for a player this was not read from would be a guess dressed as a reading.

    **44 of the 89 corpus files read this shape and ONE (IK_plus) has been
    checked against a trace.** The other 43 take the file's FIRST outer and
    inner gate (`find_song_speeds` chooses between several; this does not), a
    song 0 start, and a single set-up call; a file where any of those is
    wrong gets a schedule that is wrong by a constant phase, and
    `regrid_phase` is per song and measured for exactly that reason.
    """
    outer = OUTER_GATE.search(sid.data)
    inner = next(iter(SPEED_GATE.finditer(sid.data)), None)
    if outer is None or inner is None or rows <= 0:
        return None
    o_ctr, o_top, o_ctr2, o_jmp = (outer.group(1), outer.group(2)[0],
                                   outer.group(3), outer.group(4))
    i_ctr, i_rel, i_ctr2 = inner.group(1), inner.group(2), inner.group(3)
    if o_ctr != o_ctr2 or i_ctr != i_ctr2:
        return None
    # The outer gate hands over to the inner gate's fall-through.
    after_inner = sid.to_address(inner.end())
    if (o_jmp[0] | o_jmp[1] << 8) != after_inner:
        return None
    # The step test names both counters and the inner's reload.
    at = sid.to_offset(after_inner)
    window = sid.data[at:at + 24]
    test = re.search(b"\xad" + re.escape(o_ctr) + b"\xf0.\xad" + re.escape(i_ctr)
                     + b"\xcd" + re.escape(i_rel) + b"\xd0", window, re.DOTALL)
    if test is None:
        return None
    # The staged play routine: `BIT stage / BMI / BVC`, with the init leaving
    # `$40` in `stage` (V set), so the first call only sets the voices up.
    if not any((b"\xa9\x40\x8d" + m.group(1)) in sid.data
               for m in re.finditer(b"\x2c(..)\x30.\x50.", sid.data, re.DOTALL)):
        return None
    out_at = sid.to_offset(o_ctr[0] | o_ctr[1] << 8)
    in_at = sid.to_offset(i_ctr[0] | i_ctr[1] << 8)
    rel_at = sid.to_offset(i_rel[0] | i_rel[1] << 8)
    if not all(0 <= x < len(sid.data) for x in (out_at, in_at, rel_at)):
        return None
    reload_ = sid.data[rel_at]
    # A counter the set-up stage clears starts at 0 whatever the file image
    # holds: Auf_Wiedersehen_Monty's image has $19 at $EA46 and its stage
    # (`LDA #0 ... STA $EA46`, `$E419`) zeroes it, so its first underflow is
    # call 1, not call 26, and the schedule read from the image was 25 calls
    # late (rows 16-29 frames after the original's, constant).
    outer_n = 0 if _stage_clears(sid, o_ctr) else sid.data[out_at]
    inner_n = 0 if _stage_clears(sid, i_ctr) else sid.data[in_at]
    steps: List[int] = []
    frame = 1                       # call 0 is the set-up stage
    while len(steps) <= rows:
        outer_n -= 1
        if outer_n < 0:
            outer_n = o_top
        else:
            inner_n -= 1
            if inner_n < 0:
                inner_n = reload_
        if outer_n != 0 and inner_n == reload_:
            steps.append(frame)
        frame += 1
        if frame > 64 * (rows + 8):
            return None             # a gate that never steps
    return [steps[i + 1] - steps[i] for i in range(rows)]
