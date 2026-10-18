"""Bit $02's counter-started fall (`detect._find_counter_fall`), emitted as
per-row CMD_SETWAVEPTR programs for the records without a vibrato byte
(`goatwriter.counter_fall`).

Mega_Apocalypse `$4DBF`: when the voice's frame counter `$BC,X` (zeroed by
every note whose byte lacks bit 7, a byte, so it wraps at 256) is at or
above the record's own threshold (`$54A7,Y`) and odd, the voice's frequency
high byte is stored from savehi (`$53AF,X`, the note's own) and savehi is
decremented -- with no stop at zero. Record 16 (GT 17, `$0CFC`, threshold
114, no vibrato byte) falls that way for the 672 frames after its second
note and the 288 after the next, measured on the original: 0 of 671 and 0
of 287 frames differ from the model, 165 and 71 stores. Record 9 (GT 10,
`$09F9`, threshold 31, vibrato byte `$2D`) alternates the fall with the
vibrato: 0 of 114 store frames differ (it is emitted as wavetable loops of
a few dip sizes, `test_counter_fall_alternation.py`).
"""
import json
import pathlib
import sys

import pytest

from corpus import CORPUS, needs_corpus

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[1]))

import fidelity                                              # noqa: E402
from h2g.detect import CounterFall, detect                   # noqa: E402
from h2g.goatwriter import counter_fall as C                 # noqa: E402
from h2g.goatwriter import skydive as S                      # noqa: E402
from h2g.goatwriter.constants import (CMD_SETWAVEPTR,        # noqa: E402
                                      WAVECMD_PORTADOWN,
                                      WAVECMD_PORTAUP)
from h2g.sidfile import load_sid                             # noqa: E402

PYTHON_ROOT = pathlib.Path(__file__).resolve().parents[1]

needs_siddump = pytest.mark.skipif(
    not pathlib.Path(fidelity.SIDDUMP).exists(),
    reason="no siddump on this machine (tools/siddump-rt, see its README)")
needs_gt2reloc = pytest.mark.skipif(
    not pathlib.Path(fidelity.GT2RELOC).exists(),
    reason="no gt2reloc on this machine")

MEGA = CORPUS / "Mega_Apocalypse.sid"


def _det(name):
    sid = load_sid(str(CORPUS / f"{name}.sid"))
    return sid, detect(sid, lambda *a, **k: None)


def _converted(name="Mega_Apocalypse", **extra):
    import h2g.convert as Cv
    doc = json.loads((PYTHON_ROOT.parent / "presets.json").read_text())
    lines = []
    opts = fidelity._preset_opts(doc, f"{name}.sid")
    opts.update(extra)
    sng = Cv.convert(str(CORPUS / f"{name}.sid"), log=lines.append, **opts)
    return sng, lines


# --- detection ---------------------------------------------------------------

@needs_corpus
def test_the_block_is_read_in_exactly_one_corpus_file():
    found = {}
    for path in sorted(CORPUS.glob("*.sid")):
        sid = load_sid(str(path))
        try:
            det = detect(sid, lambda *a, **k: None)
        except Exception:
            continue                      # a file detect refuses has no block
        if det.counter_fall is not None:
            assert (det.skydive is None and det.note_rise is None
                    and not det.effect_rise and det.wave_eor is None), \
                path.name
            found[path.stem] = det.counter_fall
    assert found == {"Mega_Apocalypse": CounterFall(
        counter=0xBC, threshold=0x54A7, step=-1)}


@needs_corpus
def test_mega_apocalypses_thresholds_are_read_per_record():
    sid, det = _det("Mega_Apocalypse")
    assert C.record_threshold(sid, det, 9) == 31
    assert C.record_threshold(sid, det, 12) == 12
    assert C.record_threshold(sid, det, 16) == 114
    records = C.counter_fall_records(sid, det, det.instr_used)
    # record 16 has no vibrato byte (holds between stores); 9 and 12 have
    assert records[16] is False and records[9] is True and records[12] is True


# --- the schedule ------------------------------------------------------------

def test_stores_are_on_the_odd_frames_from_the_threshold():
    assert C.fall_stores(40, 31) == [31, 33, 35, 37, 39]
    assert C.fall_stores(8, 0) == [1, 3, 5, 7]
    assert C.fall_stores(2, 0) == [1]
    assert C.fall_stores(31, 31) == []


def test_the_counter_is_a_byte_and_the_stores_stop_when_it_wraps():
    got = C.fall_stores(520, 114)
    assert 255 in got and 257 not in got and 369 not in got
    assert 371 in got and 511 in got and 513 not in got
    assert [j for j in got if 256 <= j < 371] == []
    assert len([j for j in got if j < 256]) == 71


def test_a_frame_that_fetches_an_event_stores_nothing():
    assert C.fall_stores(40, 31, {33}) == [31, 35, 37, 39]
    assert C.fall_stores(40, 31, {32}) == [31, 33, 35, 37, 39]


def test_a_step_is_modulo_256_and_128_is_unrepresentable():
    assert C.step_command(1) == (WAVECMD_PORTADOWN, 1)
    assert C.step_command(127) == (WAVECMD_PORTADOWN, 127)
    assert C.step_command(128) is None
    assert C.step_command(129) == (WAVECMD_PORTAUP, 127)
    assert C.step_command(255) == (WAVECMD_PORTAUP, 1)
    assert C.step_command(256) is None and C.step_command(0) is None
    assert C.step_command(257) == (WAVECMD_PORTADOWN, 1)


# --- what each row owes -----------------------------------------------------

def _events(stores, resets=()):
    return sorted([(c, 0, n) for n, c in enumerate(stores)]
                  + [(c, -1, 0) for c in resets])


def test_store_zero_moves_nothing_and_each_next_one_is_a_step_of_one():
    got = C.row_falls(_events([4, 6, 8]), 3, lambda e: True)
    assert got == {2: {0: 1, 2: 1}}          # store 0 (call 4) owes nothing


def test_a_row_that_cannot_take_its_store_leaves_it_to_the_next_that_can():
    got = C.row_falls(_events([4, 6, 8, 10, 12]), 3, lambda e: e != 2)
    # stores 1 and 2 are on row 2; store 3 (call 10, row 3 tick 1) makes up
    # all three, store 4 (call 12, row 4) is one more
    assert got == {3: {1: 3}, 4: {0: 1}}


def test_a_legato_note_puts_the_voice_back_on_its_pitch_and_starts_over():
    got = C.row_falls(_events([4, 6, 8, 14, 16], resets=[10]), 3,
                      lambda e: True)
    # stores 0..2 as before; the reset at call 10 forgets them; store 3
    # (call 14) is then 3 behind, store 4 one more
    assert got == {2: {0: 1, 2: 1}, 4: {2: 3}, 5: {1: 1}}


def test_a_step_of_exactly_128_is_skipped_and_the_count_carries_on():
    stores = [3 * i for i in range(130)]
    got = C.row_falls(_events(stores), 3, lambda e: e in (0, 129))
    # the first usable store after store 0 is 129: 129 behind, kept (F1 127)
    assert got == {129: {0: 129}}
    got = C.row_falls(_events(stores[:129]), 3, lambda e: e in (0, 128))
    assert got == {}                         # 128 behind: no speed row says it


# --- a row's program ---------------------------------------------------------

def _run(entries, start, calls):
    """The program at `start` (1-based) call by call, as gplay.c WAVEEXEC
    reads it: {call: (command, speed)} for the calls that do something."""
    out, at, call = {}, start, 0
    while call < calls:
        left, right = entries[at - 1]
        if left == 0xFF:
            return out
        if left <= 0x0F:
            call += left
        else:
            out[call] = (left, right)
        call += 1
        at += 1
    return out


@pytest.mark.parametrize("key,want", [
    ((None, 1, None), {1: (WAVECMD_PORTADOWN, 1)}),
    ((1, None, 1), {0: (WAVECMD_PORTADOWN, 1), 2: (WAVECMD_PORTADOWN, 1)}),
    ((None, None, 3), {2: (WAVECMD_PORTADOWN, 3)}),
    ((40, None, None), {0: (WAVECMD_PORTADOWN, 40)}),
    ((None, 129, None), {1: (WAVECMD_PORTAUP, 127)}),
])
def test_a_rows_program_puts_each_fall_on_its_call_and_stops(key, want):
    speeds = []

    def speed_index(high):
        if (high, 0) not in speeds:
            speeds.append((high, 0))
        return speeds.index((high, 0)) + 1
    entries = C.counter_fall_entries(key, speed_index)
    assert entries[-1] == (0xFF, 0x00)
    got = _run(entries, 1, len(key))
    assert {c: (cmd, speeds[i - 1][0]) for c, (cmd, i) in got.items()} == want
    # nothing after the last fall: the calls after it are the row's own
    assert all(left >= 0xF0 or left <= 0x0F for left, _ in entries)
    assert len(entries) <= len(key) + 2


# --- the orderlist -----------------------------------------------------------

def test_unrolling_a_repeat_moves_the_restart_to_where_it_was():
    track = [3, 0xD2, 5, 7, 0xFF, 2]            # restart at the repeated 5
    assert C.unroll_repeats(track, {2}, 20) == [3, 5, 5, 5, 7, 0xFF, 1]
    track = [3, 0xD2, 5, 7, 0xFF, 3]            # restart after it
    assert C.unroll_repeats(track, {2}, 20) == [3, 5, 5, 5, 7, 0xFF, 4]
    track = [3, 0xD2, 5, 7, 0xFF, 1]            # restart on the $Dx itself
    assert C.unroll_repeats(track, {2}, 20) == [3, 5, 5, 5, 7, 0xFF, 1]


def test_a_position_not_asked_for_keeps_its_repeat():
    track = [0xD1, 4, 0xD2, 5, 0xFF, 0]
    assert C.unroll_repeats(track, {3}, 20) == [0xD1, 4, 5, 5, 5, 0xFF, 0]
    assert C.unroll_repeats(track, set(), 20) == track


def test_a_transpose_between_the_repeat_and_its_pattern_stays_in_front():
    track = [0xD1, 0xF3, 5, 7, 0xFF, 0]
    assert C.unroll_repeats(track, {2}, 20) == [0xF3, 5, 5, 7, 0xFF, 0]


class _Speeds:
    def frames_for(self, _subtune):
        return 3


def test_a_notes_segment_runs_through_its_rests_to_the_next_note_and_a_legato_note_carries_on():
    """One voice: a note (record 5), a rest, a legato note (bit 7), a rest, a
    KEYOFF carrying a tempo command, rests, then a plain note. The counter
    is the first note's until the plain note; the legato note and the KEYOFF
    are fetch frames of it, the legato one a reset; a rest is free to take a
    pointer where its command persists the row before's."""
    rest, off = 0xBD, 0xBE
    rows = [(0x70, 5, 0, 0), (rest, 0, 0, 0), (rest, 0, 0, 0),
            (0x70, 0, 0, 0), (rest, 0, 0, 0), (off, 0, 15, 3),
            (rest, 0, 0, 0), (rest, 0, 0, 0), (0x72, 0, 0, 0),
            (rest, 0, 0, 0), (0xFF, 0, 0, 0)]
    pattern = [b for row in rows for b in row]
    rows_, segs, visits, free, declined = C._walk(
        [[0, 0xFF, 0]], [pattern], {0: frozenset({3})}, {5: False}, _Speeds(),
        False, ())
    assert declined == {} and visits == {(0, 0): 1}
    assert len(rows_[0]) == 10
    first, second = segs
    assert (first.start, first.end, first.number, first.frames, first.lag) \
        == (0, 8, 5, 3, 1)
    assert first.fetches == {9, 15} and first.resets == [3] and first.ok == ""
    assert (second.start, second.end) == (8, 10)
    assert [r for r in range(10) if free[(0, 0, r)]] == [1, 2, 4, 7, 9]


def test_a_legato_note_of_another_pitch_or_an_unknown_bit_is_declined():
    rest = 0xBD
    pat = lambda second: [0x70, 5, 0, 0, rest, 0, 0, 0, second, 0, 0, 0,
                          0xFF, 0, 0, 0]
    args = ([[0, 0xFF, 0]],)
    _r, segs, *_ = C._walk(*args, [pat(0x71)], {0: frozenset({2})}, {5: False},
                           _Speeds(), False, ())
    assert segs[0].ok == "legato note changes pitch"
    _r, segs, _v, _f, declined = C._walk(*args, [pat(0x70)], {0: None},
                                         {5: False}, _Speeds(), False, ())
    assert declined == {"bit 7 of a note unknown": 2}          # both notes
    _r, segs, *_ = C._walk(*args, [pat(0x70)], {0: frozenset({2})}, {5: False},
                           _Speeds(), True, ())
    assert segs[0].lag == 0


@needs_corpus
def test_the_decoder_reads_bit_7_of_megas_two_legato_notes():
    """(Entry 21 joined them when its slide fetch was read: raw row 8, the
    `97 98 46 95` event.) Entries 25 (record 9) and 39 (record 16) each carry one note with bit 7
    at raw row 32 -- two events of 32 rows, the second the first's legato
    continuation -- and no other entry carries any. The player skips its
    instrument start, and the counter's reset with it ($4BB3 BMI), on them;
    `note_flag` is False here (the store is zero-page) so this is the
    `legato_bit7` side channel."""
    from h2g import patterns as P
    sid, det = _det("Mega_Apocalypse")
    assert not det.note_flag
    found = {}
    for i in range(det.pattern_used + 1):
        fr = []
        P.decode_entry(sid, det, i, True, True, None, True, 2, tie=True,
                       rest_keyoff=True, free_rows=fr)
        if fr:
            found[i] = fr
    assert found == {21: [8], 25: [32], 39: [32]}


# --- Mega_Apocalypse, end to end ---------------------------------------------

@needs_corpus
def test_the_plumbing_alone_moves_no_byte(monkeypatch):
    """Reading bit 7 of the notes and unrolling are bookkeeping: with the
    plan switched off the conversion is the one it was (3d8e9b92c7e9 at
    81a766c, the base of this change; 07b74cc424ed since the swell's
    pattern split, `expanding_vibrato_split`, copied 13 patterns of the
    plan-free file and commanded their hold rows; 6aa0447e2cf5 since the
    loops' sharing, `_expanding_vibrato_loop_share`, gave the rows the
    split had left on their `4xy` a neighbour's loop; f68b08b44061 since
    a remainder's block jumps onto the speed's F4 entry,
    `_expanding_vibrato_loop_cost`; 8c3819931350 since the zero-page slide
    fetch ($4B63 STA $D3,X) was read, which put every pattern holding a
    slide back in step: `SLIDE_OPERAND_ZP_SHAPE`)."""
    import hashlib
    import h2g.goatwriter.build as B
    import h2g.goatwriter.dead_blocks as DB
    # The pin was taken before `goatwriter.dead_blocks` dropped the blocks of
    # the records no pattern names.
    monkeypatch.setattr(DB, "plan_dead_blocks", lambda *a, **k: None)
    # Mega's tied landings are legato clones since ca85ac7's
    # tie-restart-mega-phantoms-note-start; this pin is the arm without them.
    monkeypatch.setattr(B._gw_note_passes, "legato_tie_family", lambda sid, det: False)
    monkeypatch.setattr(B._gw_counter_fall, "counter_fall_plan",
                        lambda *a, **k: None)
    monkeypatch.setattr(B._gw_counter_fall, "unroll_fall_repeats",
                        lambda sid, det, tracks, *a, **k: tracks)
    # The arm without the swell's phase plan (`goatwriter.swell_phase`) and
    # the zero-page `BIT $EC` reading of effect bit $40: either moves this
    # sha, and with both off it is the pinned one.
    import h2g.goatwriter.note_passes as _NP
    import h2g.detect as _D
    monkeypatch.setattr(_NP, "_swell_phase_model", lambda *a, **k: None)
    monkeypatch.setattr(_D, "_find_effect_bit40", lambda sid: False)
    sng, _ = _converted(gate_off_firstwave_instruments=())
    # Re-pinned by the -S1 slide frames (wave-program-slide-frames-0797-family):
    # Mega's $09F9/$07E7 slide frames are now semitone counts; with
    # note_pitches=None in convert() the old sha comes back.
    # Re-pinned (edd694616855) by the drop of the pulse and filter rows only a
    # dropped record reaches (instrument_drop._drop_dead_blocks): same music,
    # fewer table rows.
    assert hashlib.sha1(sng).hexdigest()[:12] == "edd694616855"


@needs_corpus
def test_the_plan_writes_record_16s_rows_and_counts_record_9s():
    sng, lines = _converted()
    said = [m for m in lines if m.startswith("Counter fall (bit $02)..:")
            and "row(s)" in m]
    assert len(said) == 1, lines
    msg = said[0]
    assert "on instrument(s) [17]" in msg
    assert "alternating note(s) on instrument(s) [10, 13]" in msg
    import songview
    song = songview.parse_sng(sng)
    wt = song.tables["WTBL"]
    assert len(wt) <= 255
    pointers = set()
    for track in song.tracks:
        for p, r, _t in S._lap_rows(track, song.patterns):
            n, i, cmd, dat = song.patterns[p][4 * r:4 * r + 4]
            if cmd == CMD_SETWAVEPTR and dat:
                pointers.add(dat)
    # every program the plan wrote is reachable and ends in a stop
    fall = [d for d in pointers
            if wt[d - 1][0] in (WAVECMD_PORTADOWN, 0x00, 0x01, 0x02)
            and any(wt[k][0] == WAVECMD_PORTADOWN
                    for k in range(d - 1, min(d + 3, len(wt))))]
    assert fall, "no row points at a fall program"


@needs_corpus
@pytest.mark.parametrize("pulse", [True, False])
def test_the_orderlists_written_are_the_ones_the_plan_repointed(monkeypatch,
                                                               pulse):
    """The plan's pattern copies are only played if the orderlists already
    written are written over. With `pulse` on a later pass happens to
    rewrite every orderlist, with it off nothing else does."""
    import h2g.goatwriter.build as B
    import songview
    seen = []
    real = B._gw_counter_fall.counter_fall_plan

    def spy(*a, **k):
        got = real(*a, **k)
        seen.append(got)
        return got
    monkeypatch.setattr(B._gw_counter_fall, "counter_fall_plan", spy)
    sng, _ = _converted(pulse=pulse)
    (plan,) = seen
    assert plan is not None and len(plan.patterns) > 69
    song = songview.parse_sng(sng)
    # The swell's pattern split (`expanding_vibrato_split`) runs after the
    # plan and may repoint a position at a copy of its own, numbered past
    # every pattern the plan had; every other position is the plan's.
    later = len(plan.patterns)
    assert len(song.tracks) == len(plan.tracks)
    for got, want in zip(song.tracks, plan.tracks):
        assert len(got) == len(want)
        assert all(g == w or later <= g < 0xD0 for g, w in zip(got, want))
    played = {b for t in song.tracks for b in t[:t.index(0xFF)] if b < 0xD0}
    assert any(b >= 69 for b in played)


@needs_corpus
def test_without_tie_the_notes_bit_7_is_unread_and_the_plan_declines():
    _sng, lines = _converted(tie=False)
    assert any("Counter fall (bit $02)..:" in m and "needs --tie" in m
               for m in lines), lines


@needs_corpus
def test_gts2_stores_no_speed_table_so_the_plan_declines():
    _sng, lines = _converted(fmt="gts2")
    assert any("Counter fall (bit $02)..:" in m and "GTS2" in m
               for m in lines), lines


def _hi_timeline(trace, voice, nframes):
    fq = fidelity.register_timeline(trace[voice].freq_events, nframes)
    return [f >> 8 for f in fq]


@needs_corpus
@needs_siddump
def test_the_model_reproduces_every_frame_of_the_originals_two_falls():
    """The block's schedule (`fall_stores`) against the ORIGINAL's trace:
    voice 3's note at frame 289 (record 16, three tied rests after it:
    fetches every 96 frames) and the one at 1057. Its high byte on frame `j`
    is the note's own minus one less than the stores up to and including
    `j`; no frame of either segment differs."""
    orig = fidelity.run_siddump(MEGA, 30, 0)
    n = 1500
    hi = _hi_timeline(orig, 2, n)
    for start, length, fetches in (
            (289, 672, {96, 192, 288, 384, 480, 576}), (1057, 288, {96, 192})):
        js = C.fall_stores(length, 114, fetches)
        hi0 = hi[start]
        for j in range(1, min(length, n - start)):
            k = sum(1 for x in js if x <= j)
            assert hi[start + j] == (hi0 - max(k - 1, 0)) & 0xFF, (start, j)
        assert len(js) in (165, 71)


@needs_corpus
@needs_siddump
def test_the_model_reproduces_every_store_of_the_alternating_record_too():
    """Record 9 (threshold 31, vibrato byte): the odd frames from 31 read the
    note's high byte minus the stores so far (the even frames are its
    vibrato), through the wrap at 256 -- 114 stores on voice 1's note at
    frame 3745, every one as the model says."""
    orig = fidelity.run_siddump(MEGA, 90, 0)
    n = 4500
    hi = _hi_timeline(orig, 0, n)
    js = C.fall_stores(288, 31, {96, 192})
    assert len(js) == 114
    hi0 = hi[3745]
    for j in js:
        k = sum(1 for x in js if x <= j)
        assert hi[3745 + j] == (hi0 - (k - 1)) & 0xFF, j


def _agreement(sng, tmp_path, seconds, tag):
    work = tmp_path / tag
    work.mkdir()
    packed = fidelity.pack_sid(sng, work)
    assert packed is not None and packed.exists(), tag
    ours = fidelity.run_siddump(packed, seconds + 2, 0)
    orig = fidelity.run_siddump(MEGA, seconds, 0)
    lag = fidelity.startup_lag(orig, ours)[0]
    n = seconds * 50
    fo = fidelity.register_timeline(orig[2].freq_events, n)
    fu = fidelity.register_timeline(ours[2].freq_events, n + lag + 1)
    frames = range(320, 1330)        # the two falls and the rests between
    return sum(1 for f in frames if fo[f] >> 8 == fu[f + lag] >> 8), \
        len(frames)


@needs_corpus
@needs_siddump
@needs_gt2reloc
def test_packed_the_fall_lands_on_the_originals_high_byte(tmp_path,
                                                          monkeypatch):
    """Through gt2reloc and siddump, 30 s: of the 1010 frames from 320 to
    1329 on voice 3 (record 16's two falls and the rests between them),
    ours reads the original's high byte at the startup lag on over 95%
    (985 of 1010 measured; the rest are the frames round the events whose
    rows carry a tempo command, where the store is made up a row later) --
    and on under 60% without the plan, which holds the note (299)."""
    sng, _ = _converted()
    same, total = _agreement(sng, tmp_path, 30, "emitted")
    assert same >= 0.95 * total, (same, total)
    import h2g.goatwriter.build as B
    monkeypatch.setattr(B._gw_counter_fall, "counter_fall_plan",
                        lambda *a, **k: None)
    sng, _ = _converted()
    held, total = _agreement(sng, tmp_path, 30, "held")
    assert held <= 0.6 * total, (held, total)
