"""Filter steps, ILV filter routing and classic clearing (split out of goatwriter.py, text moved unchanged)."""
from __future__ import annotations

from collections import (Counter)
from dataclasses import (dataclass)
from typing import (List, Optional)

from ..detect import (Detection, FILTER_ENABLE_BIT,
                      find_sfx_drum_bandpass)
from ..sidfile import (SidFile)
from .constants import (CMD_SETFILTERCTRL, CMD_SETFILTERCUTOFF,
                        CMD_SETFILTERPTR, CMD_TONEPORTA, _SONG_MAX_PATTERNS,
                        FILT_MODULATE, FILT_SET_CUTOFF, FILT_SET_PARAMS,
                        FILT_STOP, GT_MAX_FILT, ILV_EMPTY_UNION,
                        ILV_FILTER_ROUTING, ILV_ROUTE_NOTHING,
                        PACKED_PATTERN_LIMIT, WAVE_JUMP, WAVE_MAX_DELAY,
                        WAVE_NOISE_GATEOFF, WAVE_NOTE_KEEP)
from ..detect import FILTER_SHAPE
from ..search import search_file
from .constants import GT_FIRST_NOTE, GT_KEYOFF, GT_LAST_NOTE, GT_REST
from .pulse import (packed_pattern_size, pattern_rows)


def _filter_step_per_call(step: int, multiplier: int) -> int:
    """The player's per-FRAME cutoff step as a per-CALL one, signed.

    The filter table's right side is "speed, signed 8-bit" and Goattracker
    applies it once per play CALL (readme 3.4.3); the player adds its record
    byte once per FRAME. They coincide only at `-S1`, and above it the sweep
    runs `multiplier` times too far -- ACE II's original steps the cutoff by
    768 a frame and ours stepped 2304, which is 768x3 at its `-S3`, measured
    as `cut` 2.39x over 30 s.

    This is the rule CLAUDE.md already states -- a rate read out of the player
    is per frame and every table applies it per call -- and the list of
    emitters that obey it (`build_speed_table`, `_drum_speed`,
    `_rise_speed_index`, `_wave_hold_byte`, the pulse programs,
    `_wave_program_entries`) did not include this one.

    Rounded to NEAREST rather than truncated, and floored at a magnitude of 1
    so a sweep never becomes static: `3 // 4` is 0, and a filter that stops
    moving is a worse error than one moving slightly too fast, because it is
    inaudible as a sweep at all rather than merely mistimed.
    """
    if not step:
        return 0
    signed = step - 256 if step >= 0x80 else step
    scaled = round(signed / multiplier)
    if scaled == 0:                       # never round a live sweep to nothing
        scaled = 1 if signed > 0 else -1
    scaled = max(-128, min(127, scaled))
    return scaled & 0xFF


def _ilv_programs(sid: SidFile, det: Detection, instr_used: int,
                  multiplier: int = 1) -> dict:
    """record -> (passband, resonance, cutoff, per-call step) for every
    interleaved record that gets a filter program, in record order.

    The one reading both `_ilv_filter_entries` and `ilv_filter_routing_plan`
    emit from, so the two spellings of the table cannot drift apart.
    """
    filt = det.ilv_filter
    if filt is None:
        return {}
    data = sid.data
    out: dict = {}
    for i in range(max(instr_used - 1, 0)):
        rec = det.instr_start + i * det.instr_stride
        if rec + filt.program_off >= len(data):
            break
        # The player's own switch, the same `$20` the classic engine tests and
        # at the same record offset -- only the table behind it differs.
        if not data[rec + filt.enable_off] & FILTER_ENABLE_BIT:
            continue
        base = filt.table + data[rec + filt.program_off] * filt.stride
        if base + 7 >= len(data):
            continue
        prog = data[base:base + 8]
        passband = (prog[6] & 0x07) << 4
        if not passband:
            continue  # switched off at the mode register: nothing to say
        # `+6` bit 7 SET is up: the player stores 0 for up and $FF for down and
        # branches `BNE` to its subtract path, so the sense inverts twice.
        step = (prog[2] << 8 | prog[3]) + 128 >> 8
        if not prog[6] & 0x80:
            step = -step
        out[i] = (passband, prog[7] & 0xF0, prog[0],
                  _filter_step_per_call(step, multiplier))
    return out


def _ilv_filter_entries(sid: SidFile, det: Detection, instr_used: int,
                        multiplier: int = 1,
                        clearing_instruments: set | None = None):
    """(entries, pointers) for the interleaved dialect's filter table.

    The same four rows the classic path emits -- set params, set cutoff,
    modulate, stop -- from a differently shaped source: a stride-8 record per
    filter PROGRAM, indexed by a number held in the instrument's own byte +12,
    where the classic engine indexes an array by the instrument itself.

    Three things are worth stating, because they are where this could go wrong
    quietly.

    **The step is 16-bit here and Goattracker's is 8.** The player adds
    `(hi, lo)` to a 16-bit accumulator whose HIGH byte is what reaches $D416,
    so the cutoff byte moves `step / 256` per frame -- 13.8 for Sun Never
    Shines' `$0DC8`, not 13. Rounding the whole 16-bit quantity rather than
    taking `hi` is what keeps a slow sweep from becoming static: that file's
    program 8 steps `$00AE`, whose high byte is zero.

    **The sweep is a bidirectional ping-pong and a Goattracker filter program
    is not.** `FILT_MODULATE` runs one direction until `FILT_STOP`, so what is
    emitted is the FIRST leg, in the direction the record starts in. The
    reversal at the limits is not expressible and is deliberately not
    approximated.

    **The routing nibble is the player's LIVE per-voice accumulator**, not the
    per-instrument constant the classic engine keeps: it ORs a voice's bit in
    at note start and masks it out again. Nothing static names the voice an
    instrument will play on, so every routed program takes all three. That
    over-routes whenever one voice filters and another does not, and it is the
    one approximation here rather than a reading.
    """
    if det.ilv_filter is None:
        return [], {}
    entries: List[tuple] = []
    pointers: dict = {}
    for i, (passband, res, cutoff, per_call) in _ilv_programs(
            sid, det, instr_used, multiplier).items():
        block = [(FILT_SET_PARAMS | passband, res | ILV_FILTER_ROUTING),
                 (FILT_SET_CUTOFF, cutoff)]
        if per_call:
            block.append((FILT_MODULATE, per_call))
        block.append((FILT_STOP, 0x00))
        if len(entries) + len(block) > GT_MAX_FILT:
            break
        pointers[i] = len(entries) + 1  # table steps are 1-based
        entries += block

    # **THE PLAYER TAKES A VOICE OUT OF THE FILTER WHEN IT PLAYS AN UNFILTERED
    # RECORD, AND GOATTRACKER CANNOT SAY THAT PER VOICE** -- there is one
    # $D417 and `FILT_STOP` ends the table rather than the routing, so without
    # a clear one filtered note holds the circuit for the rest of the song.
    # See ILV_FILTER_ROUTING for the disassembly and for the two arms that
    # were measured and rejected before this one.
    if entries and clearing_instruments and len(entries) + 2 <= GT_MAX_FILT:
        clear = len(entries) + 1
        entries += [(FILT_SET_PARAMS | _ilv_filter_passband(sid, det), 0x00),
                    (FILT_STOP, 0x00)]
        for i in sorted(clearing_instruments):
            if i not in pointers:
                pointers[i] = clear
    return entries, pointers


def _ilv_filter_passband(sid: SidFile, det: Detection) -> int:
    """The passband the clear entry keeps.

    The player's own clear touches $D417 alone, so the passband it leaves
    standing is whatever the last filtered record set. The first filtered
    program's is the closest a single shared entry can come, and five of the
    six files have only one.
    """
    filt = det.ilv_filter
    data = sid.data
    if filt is None:
        return 0
    for i in range(max(det.instr_used - 1, 0)):
        rec = det.instr_start + i * det.instr_stride
        if rec + max(filt.program_off, filt.enable_off) >= len(data):
            break
        if not data[rec + filt.enable_off] & FILTER_ENABLE_BIT:
            continue
        base = filt.table + data[rec + filt.program_off] * filt.stride
        if base + 7 < len(data):
            return (data[base + 6] & 0x07) << 4
    return 0


def _instruments_named_per_voice(tracks: List[List[int]],
                                 patterns: List[List[int]],
                                 instr_base: int) -> list:
    """The raw record indices each voice NAMES, walking its orderlists.

    `instr 00` is inheritance, so naming is the quantity (CLAUDE.md). Shared
    by both dialects' clearing gates, which ask the same question of the
    orderlists and differ only in which records may carry a clear.
    """
    per_voice: list = [set() for _ in range(3)]
    for ti, track in enumerate(tracks):
        voice = ti % 3
        for b in track:
            if b >= len(patterns):      # a repeat/transpose byte, or a gap
                continue
            pat = patterns[b]
            for r in range(0, len(pat), 4):
                if pat[r] == 0xFF:      # ENDPATT, patterns.GT_END_PATTERN
                    break
                if pat[r + 1]:
                    per_voice[voice].add(pat[r + 1] - instr_base)
    return per_voice


def _ilv_clearing_instruments(sid: SidFile, det: Detection,
                              tracks: List[List[int]],
                              patterns: List[List[int]],
                              instr_base: int) -> set:
    """Unfiltered records that may write the routing clear.

    **ONLY THOSE PLAYED EXCLUSIVELY ON VOICES THAT ALSO PLAY A FILTERED
    RECORD**, which is the narrowest rule that reproduces the player and the
    third of three that was measured. A Goattracker filter pointer belongs to
    the INSTRUMENT, so it fires on every voice that plays it; the player's
    mask belongs to the VOICE. An instrument shared between a filtering voice
    and a non-filtering one therefore cannot carry the clear without stamping
    out a filter the player would have left standing.

    Measured at v0.5.461 -- per-frame record occupancy of the ORIGINALS, keyed
    by the ADSR pair the `onset`/`hold` columns already key on, over frames
    with a waveform selected:

        Radio_ACE          voice 2  2688 frames on filtered records, and the
                                    original routes 2688 -- exact
        Lion_Heart         voice 2  8391 of 8998 (93.3%), 43 unfiltered
        Sun_Never_Shines   voice 0  7532, voice 2 6204
        Pacific_Coast      voice 1  6 frames, and no passband, so 0 routed

    Lion_Heart's 8954-of-9000 needed no special mechanism: its filtered pair
    simply occupies almost all of voice 2. The earlier census that made it
    look like a puzzle counted instruments NAMED, not frames occupied.
    """
    filt = det.ilv_filter
    if filt is None or not tracks:
        return set()
    data = sid.data
    filtered = {i for i in range(max(det.instr_used - 1, 0))
                if det.instr_start + i * det.instr_stride + filt.enable_off
                < len(data)
                and data[det.instr_start + i * det.instr_stride
                         + filt.enable_off] & FILTER_ENABLE_BIT}
    if not filtered:
        return set()
    per_voice = _instruments_named_per_voice(tracks, patterns, instr_base)
    filtering = {v for v in range(3) if per_voice[v] & filtered}
    if not filtering:
        return set()
    # **EXACTLY ONE FILTERING VOICE, WHICH IS THE HALF ARM 3 LACKED.**
    # Goattracker has one $D417 and one filter pointer per INSTRUMENT, so a
    # clear written by voice A stamps out a circuit voice B may still be
    # holding. Where two voices filter, the player never does that and we
    # would. Measured at v0.5.467 over the six interleaved files -- Radio_ACE,
    # Lion_Heart and Pacific_Coast filter on ONE voice (2, 2 and 1);
    # Go_Go_Dash and Sun_Never_Shines on TWO (0 and 2 each); Lakers enables
    # no record at all. Without this gate arm 3 took Sun_Never_Shines from
    # 8992 filtered frames against its original's 8997 -- essentially exact --
    # down to 4370, which is the one file the clear must not touch.
    if len(filtering) != 1:
        return set()
    out = set()
    for i in set().union(*per_voice) - filtered:
        played_on = {v for v in range(3) if i in per_voice[v]}
        if played_on and played_on <= filtering:
            out.add(i)
    return out


@dataclass
class IlvRouting:
    """`ilv_filter_routing_plan`'s result: the edited lists, the filter table
    to write instead of `_ilv_filter_entries`', and the counts it logs."""
    tracks: List[List[int]]
    patterns: List[List[int]]
    entries: List[tuple]
    pointers: dict
    mode: str
    changes: int = 0        # rows where the wanted $D417 byte changes
    placed: int = 0         # CMD_SETFILTERCTRL written
    inits: int = 0          # CMD_SETFILTERPTR written ("shared" only)
    unplaceable: int = 0    # changes with no free column on their own row
    lagged: int = 0         # notes whose params row overwrote the union
    late_rows: int = 0      # rows ending with the routing wrong
    clones: int = 0         # pattern copies added
    dropped: int = 0        # commands lost to MAX_PATTERNS / packed size
    restores: int = 0       # passband-restore CMD_SETFILTERPTR ("restore")
    restore_unplaceable: int = 0  # majority notes wanting one, no free cell
    late_restores: int = 0  # of `restores`, placed on a row after the note
    passband_late: int = 0  # rows ending on the wrong passband
    stopped_live: int = 0   # replayed `B $00` on a row with a voice routed


def _ilv_routed_records(sid: SidFile, det: Detection, instr_used: int) -> set:
    """The records whose note start ARMS the voice's routing bit: the
    player's `AND #$20` at $15B1, whatever its program says. A record whose
    program has no passband still routes (Sun_Never_Shines' records 5 and 14
    are such, and its original routes the voice they play on)."""
    filt = det.ilv_filter
    data = sid.data
    out = set()
    for i in range(max(instr_used - 1, 0)):
        at = det.instr_start + i * det.instr_stride + filt.enable_off
        if at >= len(data):
            break
        if data[at] & FILTER_ENABLE_BIT:
            out.add(i)
    return out


def _ilv_voice_rows(track: List[int], patterns: List[List[int]],
                    horizon: Optional[int] = None) -> list:
    """(position, play, pattern, row) for each row one orderlist plays.

    `position` is the orderlist index of the pattern byte -- the key a
    per-occurrence copy is substituted at -- and `play` numbers the pattern
    plays in time order, so a REPEAT's second play and the loop's replay are
    distinguishable from the first. Without `horizon`, one pass to the `$FF`;
    with it, the list continues from the restart position until it has that
    many rows (or the loop plays nothing).
    """
    from ..patterns import GT_ORDER_RESTART, GT_REPEAT, MAX_PATTERNS
    plays: List[tuple] = []
    rep, restart, i = 1, None, 0
    while i < len(track):
        b = track[i]
        if b == GT_ORDER_RESTART:
            restart = track[i + 1] if i + 1 < len(track) else None
            break
        if GT_REPEAT <= b < GT_REPEAT + 16:
            rep = b - GT_REPEAT + 1
        elif b < MAX_PATTERNS:
            plays += [(i, b)] * rep
            rep = 1
        i += 1
    lengths = {p: len(pattern_rows(patterns[p])) if p < len(patterns) else 0
               for _, p in plays}
    loop = ([k for k, (pos, _) in enumerate(plays) if pos >= restart]
            if restart is not None else [])
    rows: list = []
    seq = list(range(len(plays)))
    n = 0
    while True:
        for k in seq:
            pos, p = plays[k]
            for r in range(lengths[p]):
                if horizon is not None and len(rows) >= horizon:
                    return rows
                rows.append((pos, n, p, r))
            n += 1
        if (horizon is None or len(rows) >= horizon or not loop
                or not any(lengths[plays[k][1]] for k in loop)):
            return rows
        seq = loop


def _ilv_routing_walk(groups: list, patterns: List[List[int]],
                      instr_base: int, routed: set, programs: dict,
                      mode: str, params: dict, init_row: dict,
                      restore: Optional[dict] = None) -> tuple:
    """One walk of every subtune on Goattracker's row clock.

    Returns (plan, stats): plan maps (track index, orderlist position) to
    {pattern row: (command, value)}, stats the counts `IlvRouting` carries.
    `params` is each program's params-row value ("params" and "restore"
    modes, else ignored); `init_row` maps a subtune to the (track,
    position, row) its `CMD_SETFILTERPTR` takes ("shared" mode; placed by
    the caller). `restore` ("restore" mode only) is the passband-restore
    bookkeeping `ilv_filter_routing_plan` lays the table out from: the
    majority passband `pb`, its programs `majority`, the 1-based table
    index the first restore block may take (`next`), each majority
    program's block length (`len`), and `blocks`, (program, $D417 value) ->
    index, which this walk fills in first-use order.
    """
    from ..patterns import GT_FIRSTNOTE, GT_LASTNOTE
    plan: dict = {}
    stats = Counter()
    if mode == "restore":
        majority = restore["majority"]
        # What a restore block's params row writes, by table index.
        a_info: dict = {idx: key for key, idx in restore["blocks"].items()}
    for g, (horizon, timeline) in enumerate(groups):
        if g in init_row:
            key, r, value = init_row[g]
            plan.setdefault(key, {})[r] = (CMD_SETFILTERPTR, value)
            stats["inits"] += 1
        live = [0, 0, 0]
        bits = [False, False, False]
        res = 0
        have = 0                    # gplay.c:174 / player.s: filterctrl = 0
        pb_have = 0                 # gplay.c:39 / player.s: filttype = 0
        pb_want = None              # the passband the last program set
        pending = None              # a majority program awaiting its restore
        first_play: dict = {}
        prev_want, prev_wrong = None, False
        for t in range(horizon):
            cells = []
            noted = []
            started = None          # the program the table runs from here
            executed = None
            stops = False           # a replayed `B $00` ran this row
            # "restore": what loads the filter pointer last this row, in
            # channel order -- a note's instrument, or a replayed `A`, which
            # tick 0 runs AFTER the note init (player.s "Execute tick 0 FX
            # after newnote init"; gplay.c:388 before :459).
            ptr = None
            for v in range(3):
                if t >= len(timeline[v]):
                    continue
                pos, n, p, r = timeline[v][t]
                key = (3 * g + v, pos)
                first = first_play.setdefault(key, n) == n
                note, ins, cmd, dat = patterns[p][4 * r:4 * r + 4]
                mine = plan.get(key, {}).get(r)
                if ins:
                    live[v] = ins
                if GT_FIRSTNOTE <= note <= GT_LASTNOTE and cmd != CMD_TONEPORTA:
                    rec = live[v] - instr_base
                    bits[v] = rec in routed
                    noted.append(v)
                    if rec in programs:
                        # The pointer is loaded in channel order, so the
                        # last channel's program is the one that runs.
                        started = rec
                        res = programs[rec][1]
                        ptr = ("prog", rec, v)
                if mine is not None and not first:
                    # A replayed occurrence's own command: a `B` writes its
                    # value; the init's `A` runs a params row writing $00.
                    if mine[0] == CMD_SETFILTERCTRL:
                        executed = mine[1]
                        stops = stops or mine[1] == ILV_ROUTE_NOTHING
                    elif mode == "restore":
                        ptr = ("A", mine[1], v)
                    else:
                        executed = 0
                cells.append((v, key, r, first, cmd, dat, mine))
            if executed is not None:
                have = executed
            if started is not None:
                pb_want = programs[started][0]
            params_hit = mode == "params" and started is not None
            if params_hit:
                have = params[started]
                pb_have = pb_want
            elif mode == "shared":
                pb_have = pb_want   # its one block runs before any program
            elif mode == "restore" and ptr is not None:
                if ptr[0] == "A":
                    pb_have, have = a_info[ptr[1]][2], a_info[ptr[1]][1]
                    params_hit = True
                elif ptr[1] not in majority:
                    pb_have, have = programs[ptr[1]][0], params[ptr[1]]
                    params_hit = True
            mask = sum(1 << v for v in range(3) if bits[v])
            want = (res | mask) if mask else None
            if stops and want is not None:
                # A replay's `B $00` also stopped whatever program runs.
                stats["stopped_live"] += 1
            target = None
            if mode == "restore":
                if (ptr is not None and ptr[0] == "prog"
                        and ptr[1] in majority and pb_have != restore["pb"]):
                    # A majority note on a passband other than its own: its
                    # own command column takes an `A` to a copy of its
                    # program that opens with [PARAMS majority, want], so
                    # the passband and this row's union land together.
                    target = (ptr[1], [ptr[2]], True)
                elif (ptr is None and pending is not None
                        and pb_have != restore["pb"]):
                    # Its own column was taken: the copy runs from the first
                    # free column of a later row while that program is still
                    # the one running -- the program restarted that late,
                    # which is counted (`late_restores`), not hidden.
                    target = (pending, noted + [v for v in range(3)
                                                if v not in noted], False)
                if ptr is not None:
                    pending = None
            if target is not None:
                rec, order, at_note = target
                value = want if want is not None else (res or ILV_EMPTY_UNION)
                free = [c for v in order for c in cells if c[0] == v
                        and c[3] and c[2] and not c[4] and not c[5]
                        and c[6] is None]
                idx = restore["blocks"].get((rec, value))
                if (idx is None and free and restore["next"]
                        + restore["len"][rec] - 1 <= GT_MAX_FILT):
                    idx = restore["next"]
                    restore["blocks"][(rec, value)] = idx
                    a_info[idx] = (rec, value, restore["pb"])
                    restore["next"] += restore["len"][rec]
                if idx is not None and free:
                    _, key, r, *_rest = free[0]
                    plan.setdefault(key, {})[r] = (CMD_SETFILTERPTR, idx)
                    pb_have, have = restore["pb"], value
                    params_hit = True
                    stats["restores"] += 1
                    stats["late_restores"] += not at_note
                    pending = None
                elif at_note:
                    stats["restore_unplaceable"] += 1
                    pending = rec
            if pb_want is not None and pb_have != pb_want:
                stats["passband_late"] += 1
            if want != prev_want:
                stats["changes"] += 1
            wrong = (have & 0x0F) != 0 if want is None else have != want
            if wrong and params_hit:
                stats["lagged"] += 1
            elif wrong:
                # An empty union stops the program too: the original's
                # cutoff never moves while nothing is routed.
                value = want if want is not None else ILV_ROUTE_NOTHING
                order = noted + [v for v in range(3) if v not in noted]
                for v in order:
                    cell = next((c for c in cells if c[0] == v), None)
                    if cell is None:
                        continue
                    _, key, r, first, cmd, dat, mine = cell
                    # "restore" also takes a pattern's row 0 where its command
                    # column is empty: the tempo is written before this plan,
                    # so an empty cell is one no subtune's clock needs.
                    if (first and (r or mode == "restore") and not cmd
                            and not dat and mine is None):
                        plan.setdefault(key, {})[r] = (CMD_SETFILTERCTRL,
                                                       value)
                        have = value
                        stats["placed"] += 1
                        wrong = False
                        break
                if wrong and (want != prev_want or not prev_wrong):
                    stats["unplaceable"] += 1
            if wrong:
                stats["late_rows"] += 1
            prev_want, prev_wrong = want, wrong
    return plan, stats


def ilv_filter_routing_plan(sid: SidFile, det: Detection,
                            tracks: List[List[int]],
                            patterns: List[List[int]], instr_used: int,
                            multiplier: int, instr_base: int,
                            log=None) -> Optional[IlvRouting]:
    """The interleaved dialect's routing as `B` commands, or None.

    None -- and the caller keeps `_ilv_filter_entries` -- where the file has
    no interleaved filter, no record with a program, or no orderlist. See the
    block comment above `CMD_SETFILTERPTR` for the model and its two
    spellings; both are walked and the one leaving fewer rows wrong is kept
    (ties to "params", which writes no `CMD_SETFILTERPTR`).
    """
    from ..patterns import MAX_PATTERNS, GT_FIRSTNOTE, GT_LASTNOTE
    if det.ilv_filter is None or len(tracks) < 3:
        return None
    programs = _ilv_programs(sid, det, instr_used, multiplier)
    if not programs:
        return None
    routed = _ilv_routed_records(sid, det, instr_used)
    groups = []
    for g in range(len(tracks) // 3):
        firsts = [_ilv_voice_rows(tracks[3 * g + v], patterns)
                  for v in range(3)]
        horizon = max(len(f) for f in firsts)
        groups.append((horizon, [_ilv_voice_rows(tracks[3 * g + v], patterns,
                                                 horizon) for v in range(3)]))

    # "params": each program's params row carries the union its notes most
    # often open on -- the static value that leaves the fewest lagged notes.
    opened: dict = {}
    for horizon, timeline in groups:
        live, bits = [0, 0, 0], [False, False, False]
        for t in range(horizon):
            started = None
            for v in range(3):
                if t >= len(timeline[v]):
                    continue
                _pos, _n, p, r = timeline[v][t]
                note, ins, cmd, _dat = patterns[p][4 * r:4 * r + 4]
                if ins:
                    live[v] = ins
                if GT_FIRSTNOTE <= note <= GT_LASTNOTE and cmd != CMD_TONEPORTA:
                    rec = live[v] - instr_base
                    bits[v] = rec in routed
                    if rec in programs:
                        started = rec
            if started is not None:
                mask = sum(1 << v for v in range(3) if bits[v])
                opened.setdefault(started, Counter())[
                    programs[started][1] | mask] += 1
    params = {i: (opened[i].most_common(1)[0][0] if i in opened
                  else res | ILV_FILTER_ROUTING)
              for i, (_pb, res, _c, _s) in programs.items()}
    candidates = [("params", _ilv_routing_walk(
        groups, patterns, instr_base, routed, programs, "params", params,
        {}))]

    # "shared": one passband for every program, set once per subtune by a
    # CMD_SETFILTERPTR on the last free non-zero row before its first routed
    # note. A subtune with no such row makes the spelling unavailable.
    passbands = {pb for pb, _r, _c, _s in programs.values()}
    # Programs open at CUTOFF here: cutoff, [modulate,] stop.
    init_index = sum(2 + bool(s) for *_x, s in programs.values()) + 1
    if len(passbands) == 1 and init_index + 1 <= GT_MAX_FILT:
        init_row: dict = {}
        feasible = True
        for g, (horizon, timeline) in enumerate(groups):
            live = [0, 0, 0]
            free = None
            first_play: dict = {}
            for t in range(horizon):
                hit = False
                row_free = None
                for v in range(3):
                    if t >= len(timeline[v]):
                        continue
                    pos, n, p, r = timeline[v][t]
                    key = (3 * g + v, pos)
                    first = first_play.setdefault(key, n) == n
                    note, ins, cmd, dat = patterns[p][4 * r:4 * r + 4]
                    if ins:
                        live[v] = ins
                    if (GT_FIRSTNOTE <= note <= GT_LASTNOTE
                            and cmd != CMD_TONEPORTA
                            and live[v] - instr_base in routed):
                        hit = True
                    if first and r and not cmd and not dat and row_free is None:
                        row_free = (key, r)
                if hit:
                    if free is None:
                        feasible = False
                    else:
                        init_row[g] = (free[0], free[1], init_index)
                    break
                if row_free is not None:
                    free = row_free
            if not feasible:
                break
        if feasible:
            candidates.append(("shared", _ilv_routing_walk(
                groups, patterns, instr_base, routed, programs, "shared", {},
                init_row)))
    # "restore": where the programs need different passbands, the MAJORITY
    # passband's programs open at CUTOFF -- so a `B` on their note rows is
    # never overwritten -- and keep the minority's params rows. A majority
    # note finding a passband other than its own (power-on's 0, or one a
    # minority program set) takes a CMD_SETFILTERPTR on its own command
    # column to a copy of its program opening [PARAMS majority, union]; the
    # `A` runs after the note's own pointer load, so the copy is what runs.
    restore = None
    if len(passbands) > 1:
        notes_by_pb = Counter()
        for i, seen in opened.items():
            notes_by_pb[programs[i][0]] += sum(seen.values())
        pb = max(sorted(notes_by_pb), key=lambda b: notes_by_pb[b])
        majority = frozenset(i for i, prog in programs.items()
                             if prog[0] == pb)
        base_len = sum(2 + bool(s) + (i not in majority)
                       for i, (_pb, _r, _c, s) in programs.items())
        if base_len <= GT_MAX_FILT:
            restore = {"pb": pb, "majority": majority, "next": base_len + 1,
                       "len": {i: 3 + bool(programs[i][3]) for i in majority},
                       "blocks": {}}
            candidates.append(("restore", _ilv_routing_walk(
                groups, patterns, instr_base, routed, programs, "restore",
                params, {}, restore)))
    mode, (plan, stats) = min(
        candidates, key=lambda c: (c[1][1]["late_rows"]
                                   + c[1][1]["passband_late"],
                                   c[1][1]["placed"] + c[1][1]["inits"]
                                   + c[1][1]["restores"]))

    entries: List[tuple] = []
    pointers: dict = {}
    for i, (passband, res, cutoff, per_call) in programs.items():
        block = ([] if mode == "shared"
                 or (mode == "restore" and i in restore["majority"])
                 else [(FILT_SET_PARAMS | passband, params[i])])
        block.append((FILT_SET_CUTOFF, cutoff))
        if per_call:
            block.append((FILT_MODULATE, per_call))
        block.append((FILT_STOP, 0x00))
        if len(entries) + len(block) > GT_MAX_FILT:
            break
        pointers[i] = len(entries) + 1  # table steps are 1-based
        entries += block
    if mode == "shared":
        assert len(entries) + 1 == init_index, (len(entries), init_index)
        entries += [(FILT_SET_PARAMS | passbands.pop(), 0x00),
                    (FILT_STOP, 0x00)]
    if mode == "restore":
        assert len(entries) + 1 == min(restore["blocks"].values(),
                                       default=len(entries) + 1), entries
        for (i, value), idx in sorted(restore["blocks"].items(),
                                      key=lambda kv: kv[1]):
            _pb, _res, cutoff, per_call = programs[i]
            assert idx == len(entries) + 1, (idx, len(entries))
            entries.append((FILT_SET_PARAMS | restore["pb"], value))
            entries.append((FILT_SET_CUTOFF, cutoff))
            if per_call:
                entries.append((FILT_MODULATE, per_call))
            entries.append((FILT_STOP, 0x00))

    # Each pattern's occurrences, keyed as the walk keyed them; one copy per
    # distinct command set, and the unedited pattern kept for occurrences
    # wanting none.
    occurrences: dict = {}
    for ti, track in enumerate(tracks):
        for pos, b in enumerate(track):
            if b == 0xFF:           # patterns.GT_ORDER_RESTART: operand next
                break
            if b < MAX_PATTERNS and b < len(patterns):
                occurrences.setdefault(b, []).append((ti, pos))
    new_tracks = [list(t) for t in tracks]
    new_patterns = list(patterns)
    clones = dropped = 0
    for p, occs in occurrences.items():
        sigs = {occ: tuple(sorted(plan.get(occ, {}).items())) for occ in occs}
        distinct = list(dict.fromkeys(sigs.values()))
        if distinct == [()]:
            continue
        keeper = (() if () in distinct
                  else Counter(sigs.values()).most_common(1)[0][0])
        number = {(): p}
        for sig in distinct:
            if not sig:
                continue
            edited = list(patterns[p])
            for r, (cmd, value) in sig:
                edited[4 * r + 2], edited[4 * r + 3] = cmd, value
            if packed_pattern_size(pattern_rows(edited)) > PACKED_PATTERN_LIMIT:
                dropped += len(sig)
                number[sig] = p
            elif sig == keeper:
                new_patterns[p] = edited
                number[sig] = p
            elif len(new_patterns) >= MAX_PATTERNS:
                dropped += len(sig)
                number[sig] = p
            else:
                number[sig] = len(new_patterns)
                new_patterns.append(edited)
                clones += 1
        for ti, pos in occs:
            new_tracks[ti][pos] = number[sigs[(ti, pos)]]

    result = IlvRouting(new_tracks, new_patterns, entries, pointers, mode,
                        clones=clones, dropped=dropped,
                        **{k: stats[k] for k in ("changes", "placed", "inits",
                                                 "unplaceable", "lagged",
                                                 "late_rows", "restores",
                                                 "restore_unplaceable",
                                                 "late_restores",
                                                 "passband_late",
                                                 "stopped_live")})
    if log:
        log(f"ILV filter routing......: {mode}, {result.changes} change(s), "
            f"{result.placed} CMD_SETFILTERCTRL + {result.inits} "
            f"CMD_SETFILTERPTR, {result.unplaceable} unplaceable, "
            f"{result.lagged} lagged, {result.late_rows} row(s) late, "
            f"{clones} pattern copy(ies)"
            + (f", {result.restores} passband restore(s), "
               f"{result.late_restores} late, "
               f"{result.restore_unplaceable} unplaceable at the note, "
               f"{result.passband_late} row(s) on the wrong passband"
               if mode == "restore" else "")
            + (f", {result.stopped_live} live program(s) stopped by a "
               f"replayed B $00" if result.stopped_live else "")
            + (f", {dropped} DROPPED" if dropped else ""))
    return result


def _classic_clearing_instruments(sid: SidFile, det: Detection,
                                  tracks: List[List[int]],
                                  patterns: List[List[int]],
                                  instr_base: int) -> set:
    """The classic dialect's own clear records that a Goattracker clear may carry.

    **THE CLASSIC PLAYER CLEARS THE FILTER WITH A RECORD, NOT WITH A VOICE
    MASK.** Its filter block (`FILTER_SHAPE`) runs every frame for a voice
    whose record has `FILTER_ENABLE_BIT` set and ends `LDA resctl,Y / STA
    $D417` -- so an enabled record whose resctl low nibble is 0 writes "route
    nothing" on every frame it plays. That is the mechanism behind Sanxion's
    original routing 0 for 12 of every 48 frames (107 writes of $00 against
    106 of $F2 over 9000 frames) and I_Ball's 270 unfiltered frames.
    `_filter_entries` used to skip those records as "nothing to hear"; they
    are the clear, and the ONLY records the player ever clears with -- an
    unfiltered record (bit $20 clear) skips the block and leaves $D417
    standing, so the interleaved rule of clearing on every exclusive
    unfiltered record over-fires here: on Sanxion it named records 3 and 10
    beside the player's 2, on Nemesis_the_Warlock records 6 and 13 where the
    player clears on none in the first 180 s.

    **THE ROUTING MASK IS THE RECORD'S, SO THE GATE READS THE MASK.** The
    same `LDA resctl,Y / STA $D417` that makes the clear a record makes the
    routing one: which voice the filter hears is the resctl low nibble of
    whatever record is playing, not the voice that plays it. The gate is
    therefore (a) the union of the routed records' low nibbles (bits 0-2)
    names exactly ONE voice, and (b) a clearing record is named on any voice
    at all. Both halves replaced a voice-naming gate copied from
    `_ilv_clearing_instruments` (one voice NAMES a routed record; the clear
    is played on no other voice), which is right for the interleaved
    dialect, whose mask belongs to the voice, and wrong here: Deep_Strike's
    routed record 5 is named on voices 0 and 1 and both route voice 0
    ($F1); Nemesis_the_Warlock's clear 9 is played on voice 2 while voice 1
    routes, and the ORIGINAL clears there too -- $D417 goes $F2 -> $00 at
    frame 13162 of a 900 s trace, past the 180 s window, and the new gate's
    conversion does it at 13169 (filtered frames over 900 s: original
    31064, old gate 44992, new 31070). The single-voice half of (a) is kept
    from the old gate, not re-derived: a two-voice union is the cross-voice
    race `CMD_SETFILTERCTRL` would have to model.

    Measured at v0.5.508 under presets at `-t 180` (filtered frames ours /
    original): Deep_Strike 8823 -> 2048 / 2048, Food_Feud 12344 -> 10126 /
    9956, Nineteen 8416 -> 8018 / 8016; I_Ball {7}, Sanxion {2} and
    Saboteur_II {5} unchanged (8725/8730, 7132/7133, 4696/4699 at v0.5.487).
    Auf_Wiedersehen_Monty's clear 14 and Nemesis' 9 change bytes and no
    register in the window: 14 is never struck in 900 s on either side, 9
    first at frame 13162. Refused: Lightforce ($7), Knucklebusters ($6),
    Dragons_Lair_Part_II and Delta_Mix-E-Load_loader ($3) and
    Bangkok_Knights ($5) route more than one voice; Pandora's,
    Thundercats' and Bangkok_Knights' 14 and Delta_Mix's 23 are never named.
    `tests/test_classic_clear_mask.py` pins the corpus sets.
    """
    filt = det.filter
    if filt is None or not tracks:
        return set()
    data = sid.data
    routed, unrouted = set(), set()
    for i in range(max(det.instr_used - 1, 0)):
        base = filt.offset + i * det.instr_stride
        status = filt.status + i * det.instr_stride
        if base + 1 >= len(data) or status >= len(data):
            break
        if not data[status] & FILTER_ENABLE_BIT:
            continue
        (routed if data[base] & 0x0F else unrouted).add(i)
    if not routed or not unrouted:
        return set()
    mask = 0
    for i in routed:
        mask |= data[filt.offset + i * det.instr_stride] & 0x07
    if mask not in (0x01, 0x02, 0x04):
        return set()
    per_voice = _instruments_named_per_voice(tracks, patterns, instr_base)
    return {i for i in unrouted if any(i in per_voice[v] for v in range(3))}


def _clamp_frames(start: int, step: int) -> int:
    """Frames the player accumulates before `cutoff,X` first reads >= $80.

    FILTER_SHAPE_CLAMP's `BMI` tests the value LOADED, before the add, so the
    frame that carries it to $80 or over still adds and writes; the next one
    skips both. 0 when the note starts negative (the block never writes
    $D416 at all), and capped at 256 -- a step of 0 never gets there."""
    c, n = start & 0xFF, 0
    while not c & 0x80 and n < 256:
        c = (c + step) & 0xFF
        n += 1
    return n


def _clamped_block(passband: int, resctl: int, start: int, step: int,
                   per_call: int) -> List[tuple]:
    """Set params, set cutoff, modulate to the player's hold value, stop.

    **THE ENDPOINT IS KEPT, NOT THE CLOCK.** The player travels
    `frames * step` and then holds; a per-call step is `step / multiplier`
    rounded (`_filter_step_per_call`), so running it `frames * multiplier`
    calls lands somewhere the player never goes and HOLDS there for the rest
    of the note. Thanatos' record 3 at `-S4` steps 3 a frame from $20 to $80
    in 32 frames: 128 calls of +1 would hold $A0, 96 calls hold $80 and get
    there 8 frames early. The duration is the travel over the per-call step,
    split into $7F-call modulation rows."""
    block = [(FILT_SET_PARAMS | passband, resctl), (FILT_SET_CUTOFF, start)]
    frames = _clamp_frames(start, step)
    if not frames:
        # Already negative at note start: the player writes the start value to
        # its accumulator and never to $D416, so no cutoff can be said.
        return [block[0], (FILT_STOP, 0x00)]
    if per_call:
        signed = step - 256 if step >= 0x80 else step
        p = per_call - 256 if per_call >= 0x80 else per_call
        calls = max(1, round(frames * signed / p))
        while calls:
            n = min(calls, FILT_MODULATE)
            block.append((n, per_call))
            calls -= n
    block.append((FILT_STOP, 0x00))
    return block


def _sweep_rows(per_call: int, calls: Optional[int]) -> List[tuple]:
    """The classic sweep's modulation rows and the `FILT_STOP` that ends them.

    **THE PLAYER ADDS ITS STEP EVERY FRAME THE VOICE'S RECORD IS CURRENT, AND
    A $7F-CALL ROW IS NOT THAT LONG.** The accumulator is 8 bits and wraps, so
    a note longer than 127 calls keeps sweeping (Tarzan's record at frame
    3495: the original runs $22..$99, wraps, and runs on; ours held $79 for 65
    frames after its one row ran out). `calls` is `classic_sweep_calls`'
    length for the record, split into $7F rows exactly as `_clamped_block`
    splits a clamp; None is the single row every earlier version wrote.
    """
    if not calls:
        return [(FILT_MODULATE, per_call), (FILT_STOP, 0x00)]
    rows: List[tuple] = []
    while calls > 0:
        n = min(calls, FILT_MODULATE)
        rows.append((n, per_call))
        calls -= n
    rows.append((FILT_STOP, 0x00))
    return rows


def _best_sweep_length(gaps: List[tuple]) -> Optional[int]:
    """The length in calls that errs least over a record's occurrences.

    `gaps` is (calls to the voice's next note, whether that note's record
    leaves the filter alone). Running short of a gap holds the cutoff where
    the player kept sweeping; running past it is an error only where the next
    note does not restart or replace the program -- an unfiltered record, or
    the end of the orderlist. The sum of both errors is convex and piecewise
    linear with its knots at the gaps, so the minimum is at one of them
    (the smaller on a tie)."""
    best = None
    for length in sorted({g for g, _ in gaps}):
        cost = sum(max(g - length, 0) + (max(length - g, 0) if stop else 0)
                   for g, stop in gaps)
        if best is None or cost < best[0]:
            best = (cost, length)
    return best[1] if best else None


def classic_sweep_calls(tracks: List[List[int]], patterns: List[List[int]],
                        filtered: set, instr_base: int, row_calls: int,
                        instr_row_calls: Optional[dict] = None) -> dict:
    """{record: calls its sweep should run} from the orderlists' own notes.

    A record's sweep lasts from the note that strikes it to the next note on
    the same voice, whatever that note is: the same record restarts it
    (`filt.cutoff` is loaded at every fetch), another filtered record's
    program replaces it, and an unfiltered record leaves the cutoff where it
    stood -- which Goattracker's single global program cannot do, so the
    length is a compromise (`_best_sweep_length`). A tie (`CMD_TONEPORTA`)
    strikes nothing. A voice's last note in the pass has no next note and is
    left out, as is a record no row names (it keeps the one $7F row).

    The gap is in rows, times the record's row length in calls: the START
    subtune's (`InstrumentRowCalls.start_rows`, the drum sweep's choice and for
    the same reason -- one table serves every subtune), else the shortest it
    is ever played at, else the file's `row_calls`. `filtered` is the records
    `_filter_entries` gave a pointer.
    """
    from ..patterns import GT_FIRSTNOTE, GT_LASTNOTE
    per_record: dict = {}
    start = getattr(instr_row_calls, "start_rows", None) or {}
    for track in tracks:
        live = 1                    # player.s: every voice starts on instr 1
        events: List[tuple] = []    # (row index, record or None, calls/row)
        for t, (_pos, _n, p, r) in enumerate(_ilv_voice_rows(track, patterns)):
            note, ins, cmd, _dat = patterns[p][4 * r:4 * r + 4]
            if ins:
                live = ins
            if GT_FIRSTNOTE <= note <= GT_LASTNOTE and cmd != CMD_TONEPORTA:
                rc = (start.get(live) or (instr_row_calls or {}).get(live)
                      or row_calls or 1)
                events.append((t, live - instr_base, rc))
        for (t0, rec, rc), (t1, nxt, _rc) in zip(events, events[1:]):
            if rec in filtered:
                per_record.setdefault(rec, []).append(
                    ((t1 - t0) * rc, nxt not in filtered))
    out = {}
    for rec, gaps in per_record.items():
        length = _best_sweep_length(gaps)
        if length:
            out[rec] = length
    return out


def _free_running_block(passband: int, resctl: int, per_call: int,
                        at: int) -> List[tuple]:
    """Set params, then modulate forever; no set-cutoff row at all.

    For an accumulator nothing resets (`FilterInfo.free_running`): every note
    of a filtered record continues the sweep from where the last left it, so
    a SET_CUTOFF row would reset it on every note, which the player never
    does. player.s `mt_nextfiltstep` takes a $FF row's jump on the same call
    the modulation row runs out, so `[7F step][FF back]` adds `step` on every
    call with no gap, wrapping at 8 bits as the player's `ADC` does. `at` is
    the 1-based table step this block starts on."""
    block = [(FILT_SET_PARAMS | passband, resctl)]
    if per_call:
        block += [(FILT_MODULATE, per_call), (FILT_STOP, at + 1)]
    else:
        block.append((FILT_STOP, 0x00))
    return block


def sfx_drum_hit_lattice(entries: List[tuple], start: int, multiplier: int,
                         period: int) -> Optional[tuple]:
    """(call of the first hit, calls between hits) of the drum loop at `start`.

    Read off the LAID-OUT wavetable rather than derived from the options that
    wrote it, because the hit's first call is not one formula: the plain loop
    opens with a whole frame of the record's own note (`multiplier` calls) and
    the second-note prologue opens on the noise itself, and what the filter
    program has to line up with is where the noise actually lands. Calls are
    counted from the record's first wavetable row, which is also the first
    call its filter program runs (the instrument loads both pointers on the
    note's tick 0, and neither table steps until the next call; gplay.c:388-389
    and :519-522).

    None unless three bursts of noise are seen at an even spacing of exactly
    `period * multiplier` calls: a record whose hits do not sit on that lattice
    (a prologue longer than one period, a table cut short by its budget) is
    one the filter program must not guess about.
    """
    wanted = period * multiplier
    if wanted <= 0 or not 1 <= start <= len(entries):
        return None
    idx, call, hit_before, starts = start, 0, False, []
    for _ in range(8 * (len(entries) + 8) + 64):
        if not 1 <= idx <= len(entries):
            return None
        left, right = entries[idx - 1]
        if left == WAVE_JUMP:
            if not right:
                break
            idx = right
            continue
        delay = 1 <= left <= WAVE_MAX_DELAY
        hit = left == (WAVE_NOISE_GATEOFF | 0x01) and right > WAVE_NOTE_KEEP
        if hit and not hit_before:
            starts.append(call)
        if not delay:           # a delay holds the waveform it follows
            hit_before = hit
        call += left + 1 if delay else 1
        idx += 1
        if len(starts) >= 3:
            break
    if len(starts) < 3 or starts[0] < 1:
        return None
    if starts[1] - starts[0] != wanted or starts[2] - starts[1] != wanted:
        return None
    return starts[0], wanted


def _run_length_rows(steps: List[int]) -> List[tuple]:
    """Modulation rows for per-call steps: one row per run, at most $7F calls."""
    rows: List[tuple] = []
    for step in steps:
        step &= 0xFF
        if rows and rows[-1][1] == step and rows[-1][0] < FILT_MODULATE:
            rows[-1] = (rows[-1][0] + 1, step)
        else:
            rows.append((1, step))
    return rows


def _sfx_bandpass_block(passband: int, blip: int, resctl: int, cutoff: int,
                        step: int, multiplier: int, period: int,
                        first_hit: int, at: int) -> List[tuple]:
    """A drum record's filter program with the drum's one-frame blip in it.

    **THE BLIP LIVES IN THE RECORD'S OWN PROGRAM, NOT BEHIND A WAVETABLE
    `CMD_SETFILTERPTR`.** Goattracker has one filter pointer for the whole
    tune, so a pointer jump from the drum would abandon whatever sweep the
    program was running (and a sweep on another voice with it) and could not
    come back to it: nothing records where the accumulator stood. A program
    that carries the blip itself loses nothing. It is a loop, because the
    player's drum is -- one hit every `period` frames from the note's start,
    on a counter zeroed there -- and because the original's sweep does not stop
    after the table's longest modulation step: `[set][blip][restore][sweep]
    [jump]`, the jump taking no call (gplay.c:256-260).

    The blip is `FILT_SET_PARAMS | blip` for `multiplier` calls (one frame),
    then the record's own passband back. A params row with no cutoff row
    beside it leaves the cutoff alone (gplay.c:265-275), so the sweep's value
    runs through the blip; **the drum's own `$D416` write (the `$60` in
    Nineteen) is NOT carried.** Restoring the cutoff after it takes an
    ABSOLUTE `FILT_SET_CUTOFF` whose value differs at every hit of a note, and
    a looped restore can only be one constant. See
    `tests/test_sfx_drum_bandpass.py` for the row count of the unrolled
    alternative against the table's `GT_MAX_FILT`.

    The two calls the params rows take do not modulate, so the sweep would fall
    two steps short every period. The period's whole travel (`period * step`,
    mod 256) is therefore spread over the `period * multiplier - 2` calls that
    do, the remainder going on the LAST calls so each period ends exactly where
    the player's would; the run before the first hit keeps the table's usual
    per-call step.
    """
    m = max(1, multiplier)
    calls = period * m
    n_bp = m - 1                    # rest of the hit frame, still bandpass
    n_tail = calls - m - 1          # the rest of the period, restored
    signed = step - 256 if step >= 0x80 else step
    total = period * signed
    n_mod = n_bp + n_tail
    q, r = divmod(total, n_mod)
    each = [q] * (n_mod - r) + [q + 1] * r
    per_call = _filter_step_per_call(step, m)
    block: List[tuple] = [(FILT_SET_PARAMS | passband, resctl),
                          (FILT_SET_CUTOFF, cutoff)]
    block += _run_length_rows([per_call] * (first_hit - 1))
    loop_at = at + len(block)
    block.append((FILT_SET_PARAMS | blip, resctl))
    block += _run_length_rows(each[:n_bp])
    block.append((FILT_SET_PARAMS | passband, resctl))
    block += _run_length_rows(each[n_bp:])
    block.append((FILT_STOP, loop_at))
    return block


def sfx_bandpass_plan(sid: SidFile, det: Detection, filter_ptrs: dict,
                      wave_entries: List[tuple], wave_starts: List[int],
                      lead: int, multiplier: int) -> dict:
    """{record index: (blip passband, first hit call)} for the drum records.

    A record qualifies when all of: the file's drum block sets a passband for
    its frame (`find_sfx_drum_bandpass`) that differs from the filter's own;
    the filter is the plain set-cutoff-then-sweep block (not the clamped or
    free-running one, whose programs are not a single sweep to put a loop
    around); the record carries effect bit `$80`; it has a filter program of
    its own (`filter_ptrs`, which already excludes records routing no voice);
    and the wavetable laid out for it really is a regular drum loop
    (`sfx_drum_hit_lattice`). Everything else keeps the program it had.
    """
    filt = det.filter
    if (filt is None or filt.free_running or filt.clamp or not filter_ptrs
            or det.sfx_pitch < 0 or det.sfx_period <= 0
            or det.instr_stride <= 0):
        return {}
    blip, _cutoff = find_sfx_drum_bandpass(sid)
    if blip < 0 or blip == filt.passband:
        return {}
    data = sid.data
    plan: dict = {}
    for i in sorted(filter_ptrs):
        eff_at = det.instr_start + i * det.instr_stride + 7
        if eff_at >= len(data) or not data[eff_at] & 0x80:
            continue
        if i + lead >= len(wave_starts):
            continue
        lattice = sfx_drum_hit_lattice(wave_entries, wave_starts[i + lead],
                                       multiplier, det.sfx_period)
        if lattice is None:
            continue
        plan[i] = (blip, lattice[0])
    return plan


def free_running_start(tracks: List[List[int]], patterns: List[List[int]],
                       start: int, log=None):
    """Seed Goattracker's cutoff with the free-running accumulator's file byte.

    `_free_running_block` has no set-cutoff row, because a row there would
    reset the sweep on every note; the player's accumulator is initialised
    once, by the file (`FilterInfo.cutoff`, Sigma_Seven's `$84A1` = $08),
    and Goattracker's `filtercutoff` powers on at 0. Measured on Sigma_Seven
    (presets, -t 180): the original's first cutoff write is $0A (the file's
    $08 + one step), ours was $02, and the whole sweep ran 8 behind the
    original's for the first 400 frames.

    A `CMD_SETFILTERCUTOFF` on row 0 of each subtune's entry pattern is the
    once-only spelling: gplay.c runs the filter step BEFORE the channels, so
    the call that fetches row 0 writes the old 0, the command then sets
    `start`, and the next call's first sweep step writes `start + step`.

    Row 0 only, never over an occupied command column (the subtune's
    `CMD_SETTEMPO` owns it, CLAUDE.md) and only on a pattern played once at
    its position (no repeat prefix). A pattern the song enters elsewhere is
    CLONED, so the command cannot fire mid-song; past `_SONG_MAX_PATTERNS`
    the subtune is left unseeded and counted. Returns (patterns, tracks,
    placed, skipped), new lists.
    """
    patterns = [list(p) for p in patterns]
    tracks = [list(t) for t in tracks]
    placed = skipped = 0
    uses = Counter(b for t in tracks for b in _pattern_bytes(t))
    for s in range(len(tracks) // 3):
        done = False
        for v in range(3):
            tr = tracks[3 * s + v]
            at = _entry_position(tr)
            if at is None:
                continue
            number = tr[at]
            if number >= len(patterns) or len(patterns[number]) < 4:
                continue
            if patterns[number][2] != 0:
                continue                      # the tempo's (or another) column
            if uses[number] > 1:
                if len(patterns) >= _SONG_MAX_PATTERNS:
                    continue
                patterns.append(list(patterns[number]))
                uses[number] -= 1
                number = len(patterns) - 1
                uses[number] = 1
                tr[at] = number
            patterns[number][2] = CMD_SETFILTERCUTOFF
            patterns[number][3] = start & 0xFF
            placed += 1
            done = True
            break
        if not done:
            skipped += 1
    if log and (placed or skipped):
        log(f"Free-running filter start: cutoff ${start:02X} on {placed} "
            f"subtune(s) via CMD_SETFILTERCUTOFF"
            + (f"; {skipped} left unseeded (no free row-0 command column)"
               if skipped else ""))
    return patterns, tracks, placed, skipped


def _pattern_bytes(track: List[int]):
    """Pattern numbers an orderlist names (operands of $FF excluded)."""
    skip = False
    for b in track:
        if skip:
            skip = False
        elif b == 0xFF:
            skip = True
        elif b < 0xD0:
            yield b


def _entry_position(track: List[int]):
    """Index of the first pattern byte, or None when a repeat prefix ($D1-$DF,
    which plays it more than once) or a restart comes first."""
    for i, b in enumerate(track):
        if b == 0xD0 or 0xE0 <= b < 0xFF:
            continue                           # no-op repeat / transpose
        return i if b < 0xD0 else None
    return None


# `STA`-free fetch tail of the classic player: the end of the note-fetch path
# (instrument byte list exhausted -> advance the track position), whose JMP is
# the fetch frame's only way out (`tests/test_filter_fetch_hold.py`).
_FETCH_TAIL = "C9 FF D0 08 A9 00 9D ?? ?? FE ?? ?? 4C ?? ??"
_FETCH_TAIL_JMP = 12            # offset of the 4C within _FETCH_TAIL
_FILTER_BLOCK_LEN = 26          # FILTER_SHAPE's length, up to `STA $D417`
# `INC counter,X / DEX / BMI +3 / JMP loop`: the voice loop counts X DOWN, so
# voice 0 runs last and its `STA $D416` is the one the chip keeps.
_VOICE_LOOP_DOWN = "FE ?? ?? CA 30 03 4C ?? ??"
# How many rows before its event a hold may be written when the event's own
# command column is taken (a tie's is `CMD_TONEPORTA 00`).
FETCH_HOLD_BACK = 3


def free_running_fetch_hold_voice(sid: SidFile) -> Optional[int]:
    """The voice whose note FETCH frame skips the free-running filter block,
    or None when the player is not read that way.

    Sigma_Seven's fetch path ends `JMP $8347` (`$8197`), past the filter
    block at `$8304-$831E`, so on the frame a voice fetches an event it does
    not step the cutoff. The voices run X = 2, 1, 0 (`DEX / BMI`), so voice
    0's `STA $D416` is the one that stays, and voice 0's fetch frames are
    the cutoff's holds. Read from the bytes: the block, a fetch tail lying
    before it whose every JMP lands past it, and the descending voice loop
    after it. Anything else (After_8, Rikky and Mr_Meaner carry no fetch tail
    of this spelling) returns None and gets no hold.
    """
    data = sid.data
    at = search_file(data, FILTER_SHAPE)
    if at <= -1:
        return None
    end = at + _FILTER_BLOCK_LEN
    tails, j = [], 0
    while True:
        k = search_file(data[j:], _FETCH_TAIL)
        if k <= -1:
            break
        k += j
        if k >= at:
            break
        tails.append(data[k + _FETCH_TAIL_JMP + 1]
                     | data[k + _FETCH_TAIL_JMP + 2] << 8)
        j = k + 1
    if not tails or any(t < sid.to_address(end) for t in tails):
        return None
    if search_file(data[end:], _VOICE_LOOP_DOWN) <= -1:
        return None
    return 0


def _fetch_hold_pattern(pattern: List[int], instr: int, running: int,
                        ptr_of: dict, back: int) -> tuple:
    """One pass of one pattern from one entry state: (writes, skips, instr,
    running). `writes` is the frozenset of (row, filter pointer) wanted, a
    `CMD_SETFILTERPTR` to the params row of the instrument the event plays;
    `skips` the (row, reason) owed a hold and not given one.

    An event is a row the player FETCHES: a tie or a KEYOFF. A new note
    already holds, because its instrument loads the filter pointer and the
    next call runs the table's params row, which steps nothing
    (gplay.c:265-275); a tie skips the instrument load (gplay.c:354) and a
    KEYOFF has none, so neither does. The hold goes on the event's own row
    where its command column is free, else on the nearest free row within
    `back` rows before it, never before the previous event (it would be that
    event's). Row 0 is allowed: the subtune's clock was written before this
    pass runs and an occupied column is never taken. A one-shot leaves the
    channel's running command as it was, so only a row entered with no
    running command takes one."""
    n = 0
    while 4 * n + 3 < len(pattern) and pattern[4 * n] != 0xFF:
        n += 1
    rows = []
    for r in range(n):
        note, named, cmd, data = pattern[4 * r:4 * r + 4]
        if named:
            instr = named
        rows.append((note, cmd, data, running, instr))
        if GT_FIRST_NOTE <= note <= GT_LAST_NOTE:
            running = cmd if cmd <= 4 else 0      # a new note resets it
        elif cmd <= 4:
            running = cmd
    writes, skips = set(), set()
    last_event = -1
    for r, (note, cmd, data, _run, eff) in enumerate(rows):
        tie = (GT_FIRST_NOTE <= note <= GT_LAST_NOTE
               and cmd == CMD_TONEPORTA and data == 0)
        if note == GT_KEYOFF or tie:
            ptr = ptr_of.get(eff, 0)
            if ptr:
                for c in range(r, max(r - back, last_event + 1, 0) - 1, -1):
                    if rows[c][1] == 0 and rows[c][3] == 0:
                        writes.add((c, ptr))
                        break
                else:
                    skips.add((r, "no free row"))
        if note != GT_REST:
            last_event = r
    return frozenset(writes), frozenset(skips), instr, running


def _fetch_hold_plan(tracks: List[List[int]], patterns: List[List[int]],
                     ptr_of: dict, voice: int, back: int) -> tuple:
    """(plan, skipped): `plan` maps (track index, orderlist position) to the
    (row, pointer) writes every visit of that position agrees on, for the
    tracks of `voice` only; `skipped` counts the (position, row) pairs owed
    a hold that got none, by reason. Walked as `_rest_reseed_plan` walks
    (instrument 1 and no running command before any row, transposes
    skipped, a repeat is that many visits, the restart lapped once)."""
    plan: dict = {}
    missed: set = set()
    for ti, track in enumerate(tracks):
        if ti % 3 != voice:
            continue
        end = track.index(0xFF) if 0xFF in track else len(track)
        restart = track[end + 1] if end + 1 < len(track) else None
        laps = [range(0, end)]
        if restart is not None and restart < end:
            laps.append(range(restart, end))
        instr, running = 1, 0
        for lap in laps:
            repeat = 1
            for pos in lap:
                b = track[pos]
                if 0xE0 <= b < 0xFF:
                    continue
                if 0xD0 <= b < 0xE0:
                    repeat = b - 0xD0 + 1
                    continue
                if b >= len(patterns):
                    repeat = 1
                    continue
                for _ in range(repeat):
                    want, skips, instr, running = _fetch_hold_pattern(
                        patterns[b], instr, running, ptr_of, back)
                    key = (ti, pos)
                    missed |= {(key, row, why) for row, why in skips}
                    if key in plan and plan[key] != want:
                        missed |= {(key, row, "disagree")
                                   for row, _ in plan[key] ^ want}
                        want = plan[key] & want
                    plan[key] = want
                repeat = 1
    skipped: dict = {}
    for _key, _row, why in missed:
        skipped[why] = skipped.get(why, 0) + 1
    return plan, skipped


def free_running_fetch_holds(tracks: List[List[int]],
                             patterns: List[List[int]], ptr_of: dict,
                             voice: int = 0, back: int = FETCH_HOLD_BACK,
                             log=None) -> tuple:
    """(patterns, tracks, written): a `CMD_SETFILTERPTR` to the params row of
    the instrument's own block on every tie and KEYOFF `voice` plays, so the
    free-running cutoff holds for one call at each of the voice's events.

    The player does not step the accumulator on a fetch frame, and the
    original's is the only sweep nothing resets: a missed hold is a step
    the conversion takes that the original does not, 2 on the cutoff for
    ever (`FilterInfo.free_running`; Sigma_Seven held on 128 of its first
    3563 frames, the conversion's new notes on 80). `ptr_of` maps an
    instrument number to its 1-based filter pointer, 0 for none. Changed
    patterns and tracks are COPIES; a pattern shared with another voice, or
    wanted differently at another position, is cloned and only the
    `voice`'s positions repointed (same length, same place). Past
    `_SONG_MAX_PATTERNS` or `PACKED_PATTERN_LIMIT` a position keeps its old
    rows, counted."""
    plan, skipped = _fetch_hold_plan(tracks, patterns, ptr_of, voice, back)
    occurrences: dict = {}
    for ti, track in enumerate(tracks):
        for pos, b in enumerate(track):
            if b == 0xFF:               # patterns.GT_ORDER_RESTART: operand next
                break
            if b < _SONG_MAX_PATTERNS and b < len(patterns):
                occurrences.setdefault(b, []).append((ti, pos))
    new_tracks = [list(t) for t in tracks]
    new_patterns = list(patterns)
    written = clones = dropped = 0
    for p, occs in occurrences.items():
        sigs = {occ: tuple(sorted(plan.get(occ, frozenset()))) for occ in occs}
        distinct = list(dict.fromkeys(sigs.values()))
        if distinct == [()]:
            continue
        keeper = (() if () in distinct
                  else Counter(sigs.values()).most_common(1)[0][0])
        number = {(): p}
        for sig in distinct:
            if not sig:
                continue
            edited = list(patterns[p])
            for r, value in sig:
                edited[4 * r + 2], edited[4 * r + 3] = CMD_SETFILTERPTR, value
            if packed_pattern_size(pattern_rows(edited)) > PACKED_PATTERN_LIMIT:
                dropped += len(sig)
                number[sig] = p
            elif sig == keeper:
                new_patterns[p] = edited
                number[sig] = p
                written += len(sig)
            elif len(new_patterns) >= _SONG_MAX_PATTERNS:
                dropped += len(sig)
                number[sig] = p
            else:
                number[sig] = len(new_patterns)
                new_patterns.append(edited)
                clones += 1
                written += len(sig)
        for ti, pos in occs:
            new_tracks[ti][pos] = number[sigs[(ti, pos)]]
    if log and (written or skipped or dropped):
        log(f"Filter fetch hold.......: CMD_SETFILTERPTR on {written} "
            f"row(s), {clones} pattern copy(ies)"
            + "".join(f", {n} {why}" for why, n in sorted(skipped.items()))
            + (f", {dropped} DROPPED (pattern table / packed size)"
               if dropped else ""))
    return new_patterns, new_tracks, written


def _filter_entries(sid: SidFile, det: Detection, instr_used: int,
                    lead: int = 1, multiplier: int = 1,
                    clearing_instruments: set | None = None,
                    sfx_blips: dict | None = None,
                    sweep_calls: dict | None = None):
    """(entries, pointers) for the filter table, or ([], {}) when unreadable.

    `sweep_calls` (`classic_sweep_calls`) sizes the classic sweep: see
    `_sweep_rows`. A table too small for the sized sweeps is built again
    without them, which is the table every earlier version wrote.
    """
    entries, pointers, overflowed = _filter_entries_once(
        sid, det, instr_used, lead, multiplier, clearing_instruments,
        sfx_blips, sweep_calls)
    if overflowed and sweep_calls:
        entries, pointers, _ = _filter_entries_once(
            sid, det, instr_used, lead, multiplier, clearing_instruments,
            sfx_blips, None)
    return entries, pointers


def _filter_entries_once(sid: SidFile, det: Detection, instr_used: int,
                         lead: int, multiplier: int,
                         clearing_instruments: set | None,
                         sfx_blips: dict | None,
                         sweep_calls: dict | None):
    """(entries, pointers, overflowed): `_filter_entries`' one build.

    `sfx_blips` (`sfx_bandpass_plan`) names the drum records whose program
    carries the drum's one-frame bandpass; the others are written as ever.


    The player adds a per-instrument step to a per-voice cutoff accumulator
    every frame and writes the result to $D416; Goattracker's filter table
    expresses exactly that as "set params, set cutoff, modulate". What it
    cannot express is the accumulator being *per voice* -- Goattracker has one
    filter and one cutoff for the whole tune, as the SID chip does, so two
    voices sweeping at once come out as whichever instrument was struck last.
    That is the chip's limit, not the format's: the original has the same
    single filter and the same last-writer-wins race.
    """
    filt = det.filter
    if filt is None:
        return [], {}, False
    data = sid.data
    entries: List[tuple] = []
    pointers: dict = {}
    overflowed = False
    for i in range(max(instr_used - 1, 0)):
        base = filt.offset + i * det.instr_stride
        if base + 1 >= len(data):
            break
        status = filt.status + i * det.instr_stride
        if status >= len(data):
            break
        # The player's own switch, not ours: it runs the whole filter block
        # only for an instrument whose status byte has bit $20 set. Reading the
        # array without this test gives a plausible resonance byte for every
        # instrument in every file that merely *contains* the routine.
        if not data[status] & FILTER_ENABLE_BIT:
            continue
        resctl, step = data[base], data[base + 1]
        if not resctl & 0x0F and i not in (clearing_instruments or ()):
            # Routes no voice through the filter. The player writes that $00
            # to $D417 every frame the record plays -- it is its clear -- and
            # `_classic_clearing_instruments` names the records where a
            # Goattracker clear can say the same thing; elsewhere it stays
            # unsaid rather than stamping out another voice's circuit.
            continue
        per_call = _filter_step_per_call(step, multiplier)
        block = None
        if sfx_blips and i in sfx_blips and resctl & 0x0F:
            blip, first_hit = sfx_blips[i]
            block = _sfx_bandpass_block(
                filt.passband, blip, resctl, filt.cutoff, step, multiplier,
                det.sfx_period, first_hit, len(entries) + 1)
            if len(entries) + len(block) > GT_MAX_FILT:
                block = None        # the blip does not fit: keep the sweep
        if block is not None:
            pass
        elif filt.free_running:
            block = _free_running_block(filt.passband, resctl, per_call,
                                        len(entries) + 1)
        elif filt.clamp:
            block = _clamped_block(filt.passband, resctl, filt.cutoff, step,
                                   per_call)
        else:
            block = [(FILT_SET_PARAMS | filt.passband, resctl),
                     (FILT_SET_CUTOFF, filt.cutoff)]
            if per_call:
                block += _sweep_rows(per_call, (sweep_calls or {}).get(i))
            else:
                block.append((FILT_STOP, 0x00))
        if len(entries) + len(block) > GT_MAX_FILT:
            overflowed = True
            break
        pointers[i] = len(entries) + 1  # table steps are 1-based
        entries += block
    return entries, pointers, overflowed


def _write_filtertable(out: bytearray, entries: List[tuple]) -> None:
    if not entries:
        out += bytes([0x02, 0x11, 0xFF, 0x22, 0x01])  # empty filter table
        return
    out.append(len(entries))
    out += bytes(left for left, _ in entries)
    out += bytes(right for _, right in entries)


def _highest_instrument_referenced(patterns: List[List[int]]) -> int:
    """Largest instrument number any pattern row selects (column 1 of 4)."""
    highest = 0
    for pattern in patterns:
        for k in range(1, len(pattern), 4):
            if pattern[k] > highest:
                highest = pattern[k]
    return highest
