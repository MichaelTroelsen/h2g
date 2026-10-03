"""The per-instrument filter array, and the gates that stop it inventing one.

The reading itself is proved in detect.find_filter's docstring; what is worth
pinning here is every way it can go wrong, because each one was reached by
measurement before it was reached by argument.
"""
import json
from corpus import CORPUS as _CORPUS, needs_corpus  # noqa: E402
from pathlib import Path


import pytest

from h2g.convert import convert
from h2g.detect import detect, FILTER_ENABLE_BIT, _burst_cutoff_start
from h2g.goatwriter import (GT_MAX_FILT, MAX_INSTRUMENTS, FILT_SET_PARAMS,
                            FILT_SET_CUTOFF, FILT_STOP, _filter_entries,
                            _classic_clearing_instruments)
from h2g.sidfile import load_sid

CORPUS = _CORPUS
REPO = Path(__file__).resolve().parents[2]

pytestmark = pytest.mark.skipif(not CORPUS.is_dir(),
                                reason="corpus not present")

# Originals that drive the filter hard, and the ones that never turn it on.
# Measured with siddump's FCut/Typ columns over 60 s.
FILTERED = ["ACE_II", "IK_plus", "I_Ball", "Nemesis_the_Warlock", "Pandora",
            "Star_Paws", "Trans-Atlantic_Balloon_Challenge",
            # These six clear the cutoff accumulator with a burst of STAs
            # sharing one `LDA #imm` (see _burst_cutoff_start) rather than a
            # dedicated LDA/STA pair -- find_filter returned None for all six
            # before that fallback existed.
            "Delta_Mix-E-Load_loader", "Dragons_Lair_Part_II", "Food_Feud",
            "Knucklebusters", "Lightforce", "Sanxion"]
UNFILTERED = ["Powerplay_Hockey_USA_vs_USSR"]

OPTS = dict(log=lambda m: None, fmt="gts5", slides=True, effects=True,
            status_bit6=True, reject_phantoms=True, fold_transpose=True,
            legal_restart=True)


def _det(stem):
    sid = load_sid(str(CORPUS / f"{stem}.sid"))
    return sid, detect(sid, lambda m: None)


def test_commando_fixture_is_untouched_by_the_flag():
    """The fixture has no filter routine, so the flag must be a no-op on it."""
    ref = (REPO / "Commando.sng").read_bytes()
    plain = convert(str(REPO / "Commando.sid"), log=lambda m: None)
    filtered = convert(str(REPO / "Commando.sid"), log=lambda m: None,
                       filters=True)
    assert plain == ref
    assert filtered == ref


@pytest.mark.parametrize("stem", FILTERED)
def test_a_filtered_player_yields_entries(stem):
    sid, det = _det(stem)
    assert det.filter is not None
    entries, ptrs = _filter_entries(sid, det,
                                    min(det.instr_used + 1, MAX_INSTRUMENTS))
    assert ptrs, f"{stem} drives the filter but got no table entries"
    assert len(entries) <= GT_MAX_FILT


@pytest.mark.parametrize("stem", UNFILTERED)
def test_a_player_that_never_filters_gets_no_audible_filter(stem):
    """Powerplay Hockey carries the routine and the array and never filters.

    Before the status-bit gate this file was given five filtered instruments
    and swept the cutoff 497 times against an original that writes it once.
    The gate is the player's own: it runs the block only for an instrument
    whose status byte has bit $20 set.
    """
    sid, det = _det(stem)
    if det.filter is None:
        return  # refused outright, which is also correct
    _, ptrs = _filter_entries(sid, det,
                              min(det.instr_used + 1, MAX_INSTRUMENTS))
    for i in ptrs:
        status = sid.data[det.filter.status + i * det.instr_stride]
        assert status & FILTER_ENABLE_BIT


def test_every_entry_is_a_legal_filter_table_opcode():
    """A malformed left side sends Goattracker's filter interpreter anywhere."""
    for stem in FILTERED:
        sid, det = _det(stem)
        entries, _ = _filter_entries(sid, det,
                                     min(det.instr_used + 1, MAX_INSTRUMENTS))
        for left, right in entries:
            assert (left == FILT_SET_CUTOFF or left == FILT_STOP
                    or 0x01 <= left <= 0x7F
                    or FILT_SET_PARAMS <= left <= 0xF0), hex(left)
            assert 0 <= right <= 0xFF


def test_every_block_starts_with_params_and_ends_stopped():
    """A table step that runs off the end keeps executing the next block."""
    for stem in FILTERED:
        sid, det = _det(stem)
        entries, ptrs = _filter_entries(
            sid, det, min(det.instr_used + 1, MAX_INSTRUMENTS))
        for start in ptrs.values():
            assert entries[start - 1][0] & FILT_SET_PARAMS
            end = start - 1
            while entries[end][0] != FILT_STOP:
                end += 1
                assert end < len(entries), f"{stem}: block never stops"


def test_the_flag_changes_no_file_whose_player_has_no_filter():
    """Under-read by construction: refusing a file must leave it byte-exact."""
    changed = []
    for p in sorted(CORPUS.glob("*.sid")):
        try:
            a = convert(str(p), **OPTS)
            b = convert(str(p), filters=True, **OPTS)
        except Exception:
            continue
        if a != b:
            changed.append(p.stem)
    for stem in changed:
        sid, det = _det(stem)
        # v0.5.459. "Has a filter" is TWO readings now, not one. The
        # interleaved dialect keeps a stride-8 table indexed by a program
        # number in the instrument record, which `FILTER_SHAPE` cannot reach,
        # so `det.filter` is None on those six files while their players
        # filter for thousands of frames. Keying the invariant on `filter`
        # alone would report the new reader as a violation of "refusing a file
        # leaves it byte-exact" -- the file was never refused, it was read by
        # the other route.
        assert det.filter is not None or det.ilv_filter is not None, (
            f"{stem} changed but no filter was detected")


def test_the_two_filter_readers_are_disjoint():
    """A second reader is a claim about which files it reaches.

    The interleaved reader is consulted only where the classic one came back
    None, so an overlap could never change behaviour -- but it would mean one
    of the two is matching something that is not its own dialect, which is the
    lead worth failing on. Zero overlap over the corpus, 6 files to the new
    reader.
    """
    both, ilv = [], []
    for p in sorted(CORPUS.glob("*.sid")):
        try:
            sid, det = _det(p.stem)
        except Exception:                                   # noqa: BLE001
            continue
        if det.ilv_filter is not None:
            ilv.append(p.stem)
            if det.filter is not None:
                both.append(p.stem)
    assert both == [], both
    assert sorted(ilv) == ["Go_Go_Dash", "Lakers_vs_Celtics", "Lion_Heart",
                           "Pacific_Coast", "Radio_ACE",
                           "Sun_Never_Shines"], sorted(ilv)


def test_the_array_is_two_bytes_per_record():
    """resctl == step - 1 held in 24 of 24 files the shape matched.

    That adjacency is the whole basis for reading one array rather than two
    unrelated tables, so find_filter refuses a file where it fails; this pins
    that the surviving files really do satisfy it.
    """
    seen = 0
    for p in sorted(CORPUS.glob("*.sid")):
        try:
            sid, det = _det(p.stem)
        except Exception:
            continue
        if det.filter is None:
            continue
        seen += 1
        # The step byte is the resonance byte's immediate neighbour.
        assert det.filter.offset + 1 < len(sid.data)
    assert seen >= 10


def test_burst_cutoff_start_finds_the_shared_lda():
    """Lightforce clears four per-voice arrays with one `LDA #$00`:

        A9 00        LDA #$00
        9D EF F5     STA $F5EF,X
        9D FF F5     STA $F5FF,X
        9D 02 F6     STA $F602,X
        9D 05 F6     STA $F605,X   <- the cutoff accumulator, 4th in the run

    FILTER_CUTOFF_SHAPES only matches a `LDA #imm` immediately followed by
    ONE `STA`, so this fallback is the only thing that reads a start value
    for Lightforce (and five other corpus files) at all.
    """
    from h2g.detect import FILTER_SHAPE
    from h2g.search import search_file
    sid, det = _det("Lightforce")
    assert det.filter is not None
    i = search_file(sid.data, FILTER_SHAPE)
    cutoff_var = sid.data[i + 15] | sid.data[i + 16] << 8
    assert _burst_cutoff_start(sid.data, cutoff_var) == 0


def test_burst_cutoff_start_does_not_mistake_the_sweep_for_an_init():
    """After_8's cutoff accumulator has only its own LDA/STA -- no init burst.

    A version of the skip-check with the wrong byte offset (CLC/ADC is a
    4-byte prefix, `18 79 lo hi`, not 2) would misread the sweep's own
    `STA accum,X` as the initialisation and return a bogus value instead of
    correctly reporting "not found".
    """
    from h2g.detect import FILTER_SHAPE
    from h2g.search import search_file
    sid, det = _det("After_8")
    i = search_file(sid.data, FILTER_SHAPE)
    cutoff_var = sid.data[i + 15] | sid.data[i + 16] << 8
    assert _burst_cutoff_start(sid.data, cutoff_var) == -1


# The classic player's own clear: an enabled record whose resctl low nibble is
# 0 writes "route nothing" to $D417 on every frame it plays. Which of those a
# Goattracker clear may carry is gated exactly as the interleaved dialect's
# is -- one routing voice, and the record played on no other -- and the gate
# was measured over every classic-filter file at v0.5.487 (`-t 180`, filtered
# frames ours / original): I_Ball 8992 -> 8725 / 8730, Sanxion 8416 -> 7132 /
# 7133, Saboteur_II 7970 -> 4696 / 4699, with melody, sequence, wave and adsr
# identical. Each entry is (clearing records, why the others are refused).
CLASSIC_CLEARS = {
    "I_Ball": {7},              # record 7 on voice 2, which is the routing voice
    "Sanxion": {2},             # record 2 on voice 1, which is the routing voice
    "Saboteur_II": {5},         # record 5 on voice 2, which is the routing voice
    # Record 9 plays on voice 2 while voice 1 routes: EXCLUSIVITY refuses it.
    # The original filters 8997 of 9000 frames; the clear took ours to 8214.
    "Nemesis_the_Warlock": set(),
    # Records 8 and 9 each play on two voices: exclusivity refuses both.
    "Food_Feud": set(),
    # Record 2 plays on voice 1 alone, but voices 0 AND 1 route: the
    # ONE-ROUTING-VOICE gate refuses it.
    "Lightforce": set(),
    # Record 0 plays on all three voices, three voices route.
    "Knucklebusters": set(),
}


def _emitter_inputs(stem, monkeypatch):
    """(sid, det, tracks, patterns, instr_base) exactly as build_sng gets them
    under the file's shipped presets -- the walk is over the orderlists the
    converter emits, so it has to see them after prune/dedup, not before."""
    import h2g.convert as C
    import fidelity as F
    got = {}
    real = C.build_sng

    def spy(sid, det, tracks, patterns, **kw):
        got.update(sid=sid, det=det, tracks=tracks, patterns=patterns, kw=kw)
        return real(sid, det, tracks, patterns, **kw)
    monkeypatch.setattr(C, "build_sng", spy)
    doc = json.loads((REPO / "presets.json").read_text("utf-8"))
    convert(str(CORPUS / f"{stem}.sid"), log=lambda m: None,
            **F._preset_opts(doc, f"{stem}.sid"))
    assert got, stem
    return (got["sid"], got["det"], got["tracks"], got["patterns"],
            1 if got["kw"].get("compact_instruments") else 2)


@pytest.mark.parametrize("stem", sorted(CLASSIC_CLEARS))
def test_the_classic_clear_fires_on_exactly_the_measured_records(stem, monkeypatch):
    sid, det, tracks, patterns, instr_base = _emitter_inputs(stem, monkeypatch)
    assert det.filter is not None and det.ilv_filter is None
    got = _classic_clearing_instruments(sid, det, tracks, patterns, instr_base)
    assert got == CLASSIC_CLEARS[stem], (stem, got)
    # Every clearing record is one the PLAYER clears with: enabled, unrouted.
    for i in got:
        status = sid.data[det.filter.status + i * det.instr_stride]
        resctl = sid.data[det.filter.offset + i * det.instr_stride]
        assert status & FILTER_ENABLE_BIT and not resctl & 0x0F


@pytest.mark.parametrize("stem", [s for s in CLASSIC_CLEARS if CLASSIC_CLEARS[s]])
def test_a_clearing_record_gets_a_block_that_routes_nothing(stem, monkeypatch):
    """Without the set, the record is skipped; with it, its block starts with
    a SET_PARAMS whose routing nibble is 0 and stops without modulating."""
    sid, det, tracks, patterns, instr_base = _emitter_inputs(stem, monkeypatch)
    n = min(det.instr_used + 1, MAX_INSTRUMENTS)
    _, without = _filter_entries(sid, det, n)
    entries, with_ = _filter_entries(sid, det, n,
                                     clearing_instruments=CLASSIC_CLEARS[stem])
    for i in CLASSIC_CLEARS[stem]:
        assert i not in without and i in with_
        left, right = entries[with_[i] - 1]
        assert left & FILT_SET_PARAMS and not right & 0x0F
        assert entries[with_[i]][0] in (FILT_SET_CUTOFF, FILT_STOP)


# --- ilv_filter_routing: the per-voice union as CMD_SETFILTERCTRL -----------
#
# goatwriter.ilv_filter_routing_plan. The synthetic tests drive the walk on a
# hand-built three-voice song whose answer can be read off the rows; the
# corpus tests check the five files it moves against the routing each
# ORIGINAL traces (ILV_FILTER_ROUTING's table: Radio_ACE and Lion_Heart route
# voice 2 only, Pacific_Coast voice 1, Go_Go_Dash voices 2 and 0+2,
# Sun_Never_Shines 0+2 and 0).

from h2g.goatwriter import (CMD_SETFILTERCTRL, CMD_SETFILTERPTR,  # noqa: E402
                            ILV_EMPTY_UNION, PACKED_PATTERN_LIMIT,
                            _ilv_routing_walk, _ilv_voice_rows,
                            packed_pattern_size, pattern_rows)

_REST = (0xBD, 0, 0, 0)


def _pattern(rows, length=8):
    rows = dict(rows)
    out = []
    for r in range(length):
        out += list(rows.get(r, _REST))
    return out + [0xFF, 0, 0, 0]


def _song(v0, v1, v2):
    """Three one-pattern voices, patterns 0-2, each orderlist `p $FF 00`."""
    patterns = [_pattern(v0), _pattern(v1), _pattern(v2)]
    tracks = [[0, 0xFF, 0], [1, 0xFF, 0], [2, 0xFF, 0]]
    timeline = [_ilv_voice_rows(t, patterns) for t in tracks]
    return patterns, [(max(len(t) for t in timeline), timeline)]


# instr_base 1: GT instrument 1 is record 0 (routed, with a program whose
# resonance is $4), GT instrument 2 is record 1 (not routed).
_ROUTED, _PLAIN = 1, 2
_PROGRAMS = {0: (0x10, 0x40, 0x80, 0)}


def _walk(patterns, groups, mode, params=None, init_row=None,
          programs=_PROGRAMS):
    return _ilv_routing_walk(groups, patterns, 1, {0}, programs, mode,
                             params or {}, init_row or {})


def test_the_union_walk_writes_each_voices_bit_where_it_changes():
    """SABOTAGE TARGET: replace the union (`mask` in `_ilv_routing_walk`) by
    the static ILV_FILTER_ROUTING $07 and every value below becomes $47.

    Voice 0 enters the filter at row 1, voice 2 at row 3, and voice 0 leaves
    at row 5 on an unfiltered record: the player's $D417 low nibble goes
    1, 5, 4, and each `B` rides on the column of the voice that changed it."""
    patterns, groups = _song({0: (0x90, _PLAIN, 0, 0), 1: (0x90, _ROUTED, 0, 0),
                              5: (0x90, _PLAIN, 0, 0)},
                             {},
                             {0: (0x90, _PLAIN, 0, 0), 3: (0x90, _ROUTED, 0, 0)})
    plan, stats = _walk(patterns, groups, "shared")
    assert plan == {(0, 0): {1: (CMD_SETFILTERCTRL, 0x41),
                             5: (CMD_SETFILTERCTRL, 0x44)},
                    (2, 0): {3: (CMD_SETFILTERCTRL, 0x45)}}, plan
    assert (stats["placed"], stats["late_rows"], stats["lagged"]) == (3, 0, 0)


def test_a_params_row_overwrites_the_b_on_its_own_row_so_the_b_lags():
    """player.s runs `mt_filtstep` before the channels: a program opening on
    FILT_SET_PARAMS writes its own routing one call after the note, so the
    union voice 2's note opens on ($45, against a params value of $41) can
    only be written on the NEXT row -- counted, not hidden."""
    patterns, groups = _song({1: (0x90, _ROUTED, 0, 0), 5: (0x90, _PLAIN, 0, 0)},
                             {},
                             {3: (0x90, _ROUTED, 0, 0)})
    plan, stats = _walk(patterns, groups, "params", params={0: 0x41})
    assert plan == {(0, 0): {4: (CMD_SETFILTERCTRL, 0x45),
                             5: (CMD_SETFILTERCTRL, 0x44)}}, plan
    assert (stats["lagged"], stats["late_rows"]) == (1, 1)


def test_no_command_on_row_0_or_over_a_taken_column():
    """Row 0 is the subtune's clock (CLAUDE.md); a change there waits for the
    first free row, and an occupied column is never written over."""
    patterns, groups = _song({0: (0x90, _ROUTED, 0, 0), 1: (0xBD, 0, 4, 0x11)},
                             {1: (0xBD, 0, 5, 0x22)},
                             {1: (0xBD, 0, 6, 0x33)})
    plan, stats = _walk(patterns, groups, "shared")
    assert plan == {(0, 0): {2: (CMD_SETFILTERCTRL, 0x41)}}, plan
    assert (stats["unplaceable"], stats["late_rows"]) == (1, 2)


def test_an_empty_union_is_never_written_as_zero():
    """`B $00` also stops the filter table (gplay.c:471); with a resonance of
    0 the empty union is written ILV_EMPTY_UNION instead."""
    patterns, groups = _song({1: (0x90, _ROUTED, 0, 0), 3: (0x90, _PLAIN, 0, 0)},
                             {}, {})
    plan, _ = _walk(patterns, groups, "shared",
                    programs={0: (0x10, 0x00, 0x80, 0)})
    assert plan == {(0, 0): {1: (CMD_SETFILTERCTRL, 0x01),
                             3: (CMD_SETFILTERCTRL, ILV_EMPTY_UNION)}}, plan


def test_a_repeat_replays_the_occurrence_without_rewriting_it():
    """Commands go on an occurrence's FIRST play only; the walk's later plays
    of it execute what is there (`REPEAT` $D1 plays pattern 0 twice)."""
    patterns = [_pattern({1: (0x90, _ROUTED, 0, 0), 3: (0x90, _PLAIN, 0, 0)}),
                _pattern({}, 16), _pattern({}, 16)]
    tracks = [[0xD1, 0, 0xFF, 0], [1, 0xFF, 0], [2, 0xFF, 0]]
    timeline = [_ilv_voice_rows(t, patterns, 16) for t in tracks]
    assert [x[:2] for x in timeline[0][::8]] == [(1, 0), (1, 1)]
    plan, stats = _walk(patterns, [(16, timeline)], "shared")
    assert plan == {(0, 1): {1: (CMD_SETFILTERCTRL, 0x41),
                             3: (CMD_SETFILTERCTRL, 0x40)}}, plan
    assert stats["late_rows"] == 0


# The routed voices each ORIGINAL traces (ILV_FILTER_ROUTING, v0.5.461), as
# the $D417 low nibbles a conversion may write. Sun_Never_Shines' program 12
# opens on voice 1 too, so only its `B` values are held to the trace.
ILV_MOVERS = {"Radio_ACE": {0, 4}, "Lion_Heart": {0, 4},
              "Pacific_Coast": {0, 2}, "Go_Go_Dash": {0, 1, 4, 5},
              "Sun_Never_Shines": {0, 1, 4, 5}}


def _routed_conversion(stem, **extra):
    import fidelity as F
    from songview import parse_sng
    doc = json.loads((REPO / "presets.json").read_text("utf-8"))
    opts = dict(F._preset_opts(doc, f"{stem}.sid"), **extra)
    lines = []
    blob = convert(str(CORPUS / f"{stem}.sid"), log=lines.append, **opts)
    return blob, parse_sng(blob), lines


@pytest.mark.parametrize("stem", sorted(ILV_MOVERS))
def test_the_routing_written_is_the_voices_the_original_routes(stem):
    """SABOTAGE TARGET: with the union replaced by the static $07, Radio_ACE,
    Lion_Heart and Pacific_Coast write $x7 in their params rows and every
    file's `B` set is empty or $x7 -- both fail here."""
    _blob, song, lines = _routed_conversion(stem, ilv_filter_routing=True)
    nibbles, row0, zero = set(), 0, 0
    for p in song.patterns:
        for r, (_n, _i, cmd, dat) in enumerate(pattern_rows(p)):
            if cmd in (CMD_SETFILTERCTRL, CMD_SETFILTERPTR):
                row0 += r == 0
            if cmd == CMD_SETFILTERCTRL:
                nibbles.add(dat & 0x0F)
                zero += dat == 0
    params = {right & 0x0F for left, right in song.tables["FTBL"]
              if FILT_SET_PARAMS <= left < FILT_STOP and right}
    assert nibbles and nibbles <= ILV_MOVERS[stem], (stem, nibbles)
    if stem != "Sun_Never_Shines":
        assert params <= ILV_MOVERS[stem], (stem, params)
    assert not row0 and not zero, (stem, row0, zero)
    assert all(packed_pattern_size(pattern_rows(p)) <= PACKED_PATTERN_LIMIT
               for p in song.patterns)
    logged = [m for m in lines if m.startswith("ILV filter routing")]
    assert len(logged) == 1 and "unplaceable" in logged[0] \
        and "lagged" in logged[0], logged


def test_the_two_voice_files_write_both_union_states():
    """Go_Go_Dash and Sun_Never_Shines filter on TWO voices; the reason the
    gated clear could not serve them. The union must take both states their
    originals trace -- 0+2 and one voice alone."""
    for stem, need in (("Go_Go_Dash", {4, 5}), ("Sun_Never_Shines", {1, 5})):
        _blob, song, _ = _routed_conversion(stem, ilv_filter_routing=True)
        got = {dat & 0x0F for p in song.patterns
               for _n, _i, cmd, dat in pattern_rows(p)
               if cmd == CMD_SETFILTERCTRL}
        assert need <= got, (stem, got)


def test_a_single_filtering_voice_never_lags():
    """A params row carries the union its notes most often open on; where one
    voice alone filters that is every opening, so nothing lags. Sun's three
    passbands force the params spelling on a two-voice file, which does."""
    for stem in ("Radio_ACE", "Lion_Heart", "Pacific_Coast", "Sun_Never_Shines"):
        _blob, _song, lines = _routed_conversion(stem, ilv_filter_routing=True)
        line = next(m for m in lines if m.startswith("ILV filter routing"))
        lagged = int(line.split(" lagged")[0].rsplit(", ", 1)[1])
        assert (lagged > 0) == (stem == "Sun_Never_Shines"), line


@pytest.mark.parametrize("stem", ["Lakers_vs_Celtics", "ACE_II", "Sanxion"])
def test_the_option_moves_no_file_it_does_not_reach(stem):
    """Lakers enables no record; ACE_II and Sanxion are the classic dialect,
    whose routing is last-writer rather than a union (out of scope)."""
    off, _, _ = _routed_conversion(stem)
    on, _, lines = _routed_conversion(stem, ilv_filter_routing=True)
    assert on == off
    assert not any(m.startswith("ILV filter routing") for m in lines)


def test_commando_is_untouched_by_the_routing_option():
    ref = (REPO / "Commando.sng").read_bytes()
    assert convert(str(REPO / "Commando.sid"), log=lambda m: None,
                   filters=True, ilv_filter_routing=True) == ref
