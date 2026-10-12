"""The sfx drum's one frame of bandpass, carried in the drum record's filter program.

Nineteen `$948A`: the drum's fire block writes `$60 -> $D416` and `$2F -> $D418`
beside its noise, and the next frame's `LDY #$1F / STY $D418` takes the
passband back. On the six sfx-drum files that filter, 1109-1487 routed frames a
file are that bandpass (-t 180, v0.5.516) and `--sfx-drum` emitted none of them.

`--sfx-drum-bandpass` (off by default; `goatwriter.sfx_bandpass_plan`) writes
the blip into the filter program of each drum record that also filters, as a
loop [set][blip][restore][sweep][jump] on the drum's own period. Goattracker
has ONE filter pointer for the tune, so a wavetable `CMD_SETFILTERPTR` from the
drum would abandon whatever sweep was running and could not return to it;
the record's own program loses nothing.

What it does NOT carry is the drum's `$D416` cutoff write: restoring the
cutoff after it needs an absolute `FILT_SET_CUTOFF` whose value differs at
every hit of a ~20-hit note (`test_the_unrolled_cutoff_restore_does_not_fit`).

Measured (-t 180 under presets, 5 movers, historical): the blip lands on OUR
noise frame exactly, and per note it sits where the original's does, but the
lag-aligned `band` column falls on all five because our drum's note onsets are
not on the original's frames. See `presets.EXCLUDED_FROM_ALWAYS`.
"""
import json
import pathlib
import sys
from collections import Counter
from types import SimpleNamespace

import pytest

PYTHON_ROOT = pathlib.Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PYTHON_ROOT))

import fidelity                                              # noqa: E402
from corpus import CORPUS, needs_corpus                      # noqa: E402
from h2g.convert import _detect_tables, convert              # noqa: E402
from h2g.detect import (SFX_DRUM_SHAPE, find_sfx_drum_bandpass)  # noqa: E402
from h2g.goatwriter import (FILT_SET_CUTOFF, FILT_SET_PARAMS,  # noqa: E402
                            FILT_STOP, GT_MAX_FILT, _filter_entries,
                            _sfx_bandpass_block, _sfx_drum_entries,
                            sfx_drum_hit_lattice)
from h2g.goatwriter import filters as _filters               # noqa: E402
from h2g.sidfile import load_sid                             # noqa: E402
from songview import parse_sng                               # noqa: E402

REPO = PYTHON_ROOT.parent
PRESETS = REPO / "presets.json"

needs_siddump = pytest.mark.skipif(
    not pathlib.Path(fidelity.SIDDUMP).exists(),
    reason="no siddump on this machine (tools/siddump-rt, see its README)")
needs_gt2reloc = pytest.mark.skipif(
    not pathlib.Path(fidelity.GT2RELOC).exists(),
    reason="no gt2reloc on this machine")
needs_presets = pytest.mark.skipif(not PRESETS.exists(),
                                   reason="presets.json not generated")

LP, BP = 0x10, 0x20
RES = 0xF4
MOVERS = {"I_Ball", "Nineteen", "Pandora", "Thundercats",
          "Trans-Atlantic_Balloon_Challenge"}
SFX_FILES = ["Bangkok_Knights", "I_Ball", "Mega_Apocalypse", "Nineteen",
             "Pandora", "Star_Paws", "Thundercats",
             "Trans-Atlantic_Balloon_Challenge"]


# --- Goattracker's filter step, transcribed ---------------------------------

def run_filter(entries, start, calls):
    """gplay.c:253-300, one play call at a time: (passband bits, cutoff, ctrl).

    A transcription rather than an import, which is the point: it is a second
    reader of the same table, as `test_call_rate` is of the wavetable.
    """
    left = [e[0] for e in entries] + [0] * 8
    right = [e[1] for e in entries] + [0] * 8
    ptr, time, cutoff, ctrl, ftype = start, 0, 0, 0, 0
    seen = []
    for _ in range(calls):
        stopped = False
        if ptr:
            if left[ptr - 1] == 0xFF:
                ptr = right[ptr - 1]
                stopped = not ptr
            if not stopped:
                if not time:
                    if left[ptr - 1] >= 0x80:
                        ftype = left[ptr - 1] & 0x70
                        ctrl = right[ptr - 1]
                        ptr += 1
                        if left[ptr - 1] == 0x00:
                            cutoff = right[ptr - 1]
                            ptr += 1
                    elif left[ptr - 1]:
                        time = left[ptr - 1]
                    else:
                        cutoff = right[ptr - 1]
                        ptr += 1
                if time:
                    cutoff = (cutoff + right[ptr - 1]) & 0xFF
                    time -= 1
                    if not time:
                        ptr += 1
        seen.append((ftype, cutoff, ctrl))
    return seen


def block(step, m=1, period=6, first_hit=None, cutoff=0x40, at=1):
    return _sfx_bandpass_block(LP, BP, RES, cutoff, step, m, period,
                               m if first_hit is None else first_hit, at)


# --- the reading -------------------------------------------------------------

DRUM = "A9 48 8D 0F D4 A9 81 8D 12 D4"
TAIL = "A9 60 8D 16 D4 A9 2F 8D 18 D4"


def _sid(*parts):
    return SimpleNamespace(
        data=bytes.fromhex(" ".join(("EA",) * 8 + parts + ("60",) + ("EA",) * 8)))


def test_the_tail_behind_the_drum_pair_is_read():
    """SABOTAGE TARGET: `find_sfx_drum_bandpass` -- change the `$D418`
    immediate's mask or the tail's offset and the passband is lost."""
    assert find_sfx_drum_bandpass(_sid(DRUM, TAIL)) == (BP, 0x60)


def test_a_tail_that_is_not_behind_the_drum_pair_is_refused():
    """SABOTAGE TARGET: the anchoring. A bare `LDA #imm / STA $D416 / LDA #imm /
    STA $D418` also spells an ordinary filter set-up."""
    assert find_sfx_drum_bandpass(_sid(TAIL)) == (-1, -1)
    assert find_sfx_drum_bandpass(_sid(DRUM, "EA EA", TAIL)) == (-1, -1)


def test_a_mode_write_with_no_passband_is_a_volume_write():
    assert find_sfx_drum_bandpass(
        _sid(DRUM, "A9 60 8D 16 D4 A9 0F 8D 18 D4")) == (-1, -1)


def test_the_drum_shape_alone_has_no_bandpass():
    assert find_sfx_drum_bandpass(_sid(DRUM)) == (-1, -1)


# --- where the noise lands ---------------------------------------------------

def _loop(m, period=6, second=None):
    hit = _sfx_drum_entries(0x41, 0x48, period, m, second_note=second)
    left, right, loop = hit
    return list(zip(left + [0xFF], right + [1 + loop]))


@pytest.mark.parametrize("m", [1, 2, 3])
def test_the_plain_loop_opens_its_first_hit_one_frame_in(m):
    assert sfx_drum_hit_lattice(_loop(m), 1, m, 6) == (m, 6 * m)


def test_the_second_note_prologue_puts_its_first_hit_one_call_in():
    assert sfx_drum_hit_lattice(_loop(1, 6, second=0x95), 1, 1, 6) == (1, 6)


def test_a_loop_off_the_period_is_not_a_lattice():
    """SABOTAGE TARGET: the spacing test. The second-note prologue at -S3 sits
    its loop `(period - 2) * 3 + 3` calls after the burst, not `period * 3`."""
    assert sfx_drum_hit_lattice(_loop(3, 6, second=0x95), 1, 3, 6) is None
    assert sfx_drum_hit_lattice(_loop(1), 1, 1, 7) is None


def test_a_table_that_stops_has_no_lattice():
    entries = [(0x41, 0x00), (0x81, 0xC9), (0x41, 0x00), (0xFF, 0x00)]
    assert sfx_drum_hit_lattice(entries, 1, 1, 6) is None


def test_a_noise_waveform_that_is_the_records_own_is_not_a_hit():
    """`held` is `$81` on a noise record, with a RELATIVE note: not a hit."""
    entries = [(0x81, 0x00), (0x03, 0x80), (0xFF, 1)]
    assert sfx_drum_hit_lattice(entries, 1, 1, 4) is None


# --- the program -------------------------------------------------------------

STEPS = [0xFC, 0xFD, 0x03, 0x60, 0x00, 0xED, 0x01]
SHAPES = [(1, 6), (1, 8), (2, 6), (3, 6), (2, 8)]


@pytest.mark.parametrize("step", STEPS)
@pytest.mark.parametrize("m,period", SHAPES)
def test_the_blip_is_bandpass_for_one_frame_on_the_lattice(m, period, step):
    """SABOTAGE TARGET: `n_bp`, the restore row, the loop's jump target."""
    calls = period * m
    rows = block(step, m, period)
    run = run_filter(rows, 1, m + calls * 5 + 4)
    bp_calls = {j for j, (t, _, _) in enumerate(run) if t == BP}
    want = {m + k * calls + c for k in range(5) for c in range(m)}
    assert {j for j in bp_calls if j < m + calls * 5} == want
    assert all(t in (LP, BP) for t, _, _ in run)
    assert all(c == RES for _, _, c in run)


@pytest.mark.parametrize("step", STEPS)
@pytest.mark.parametrize("m,period", SHAPES)
def test_each_period_ends_where_the_players_sweep_does(m, period, step):
    """SABOTAGE TARGET: the compensation. The two params calls do not
    modulate, so without spreading `period * step` over the other
    `period * m - 2` calls every period falls two steps short."""
    calls = period * m
    signed = step - 256 if step >= 0x80 else step
    run = run_filter(block(step, m, period), 1, m + calls * 6)
    at = [run[m + k * calls - 1][1] for k in range(6)]
    for k in range(1, 6):
        assert (at[k] - at[k - 1]) & 0xFF == (period * signed) & 0xFF, \
            (m, period, step, at)


def test_the_cutoff_is_not_written_by_the_blip():
    """The drum's own `$60` is not carried: no params row of the loop is
    followed by a set-cutoff row."""
    rows = block(0xFC)
    for i, (left, _) in enumerate(rows[:-1]):
        if left >= 0x80 and i >= 2:
            assert rows[i + 1][0] != FILT_SET_CUTOFF, rows


def test_the_loop_jumps_to_the_blip_row():
    rows = block(0xFC, 2, 6, at=9)
    left, right = rows[-1]
    assert left == FILT_STOP and right
    assert rows[right - 9] == (FILT_SET_PARAMS | BP, RES)


def test_the_run_before_the_first_hit_uses_the_tables_per_call_step():
    rows = block(0xFC, 3, 6)
    assert rows[2] == (2, _filters._filter_step_per_call(0xFC, 3))


def test_a_blip_block_costs_a_handful_of_rows():
    """[set params][set cutoff] [blip][modulate*][restore][modulate*] [jump]:
    6 rows at -S1 with a whole-number step, 12 at the widest shape here."""
    assert len(block(0xFC)) == 6
    assert len(block(0xFD)) == 7                 # -3 * 6 over 4 calls: two runs
    assert max(len(block(s, m, p)) for s in STEPS for m, p in SHAPES) <= 12


# --- the table ---------------------------------------------------------------

def _read(stem):
    return _detect_tables(load_sid(str(CORPUS / f"{stem}.sid")), lambda m: None)


@needs_corpus
def test_blips_that_do_not_fit_leave_the_plain_program(monkeypatch):
    """SABOTAGE TARGET: the budget fallback in `_filter_entries`. A blip block
    that overruns `GT_MAX_FILT` must keep the sweep, not stop the table."""
    sid, det = _read("Nineteen")
    plain, plain_ptrs = _filter_entries(sid, det, det.instr_used, 1, 1, set())
    plan = {i: (BP, 1) for i in plain_ptrs
            if sid.data[det.instr_start + i * det.instr_stride + 7] & 0x80}
    assert plan
    # Room for the first plain block (4 rows) and not for its blip block (6+).
    monkeypatch.setattr(_filters, "GT_MAX_FILT", 5)
    capped, capped_ptrs = _filter_entries(sid, det, det.instr_used, 1, 1, set())
    again, again_ptrs = _filter_entries(sid, det, det.instr_used, 1, 1, set(),
                                        sfx_blips=plan)
    assert capped and again == capped and again_ptrs == capped_ptrs


@needs_corpus
def test_a_blip_plan_leaves_the_other_records_blocks_alone():
    sid, det = _read("Thundercats")
    plain, plain_ptrs = _filter_entries(sid, det, det.instr_used, 1, 3, set())
    drum = [i for i in plain_ptrs
            if sid.data[det.instr_start + i * det.instr_stride + 7] & 0x80]
    assert drum == [12]
    rows, ptrs = _filter_entries(sid, det, det.instr_used, 1, 3, set(),
                                 sfx_blips={12: (BP, 3)})
    assert set(ptrs) == set(plain_ptrs)
    first = plain_ptrs[12]
    assert rows[:first - 1] == plain[:first - 1]
    assert len(rows) > len(plain)


# --- the corpus --------------------------------------------------------------

@needs_corpus
def test_the_drum_blocks_that_set_a_passband_are_these_files():
    """Which corpus files' drum fire block ends `$D416` / `$D418` stores, and
    what they write (`$60`/`$50`/... and `$2F` bandpass)."""
    found = {}
    for p in sorted(CORPUS.glob("*.sid")):
        try:
            sid, _det = _read(p.stem)
        except Exception:                                   # noqa: BLE001
            continue
        got = find_sfx_drum_bandpass(sid)
        if got != (-1, -1):
            found[p.stem] = got
    assert set(found) == {"After_8", "I_Ball", "Mr_Meaner", "Nineteen",
                          "Off_the_Cuff", "Pandora", "Pygmies_Revenge",
                          "Rikky", "Rock_Tells_the_Tale", "Star_Paws",
                          "Thundercats",
                          "Trans-Atlantic_Balloon_Challenge"}, found
    assert {v[0] for v in found.values()} == {BP}, found
    assert found["Trans-Atlantic_Balloon_Challenge"][1] == 0x50
    assert {v[1] for k, v in found.items()
            if k != "Trans-Atlantic_Balloon_Challenge"} == {0x60}, found


def _opts(stem):
    doc = json.loads(PRESETS.read_text("utf-8"))
    return fidelity._preset_opts(doc, f"{stem}.sid")


@needs_corpus
@needs_presets
@pytest.mark.parametrize("stem", SFX_FILES)
def test_the_option_is_inert_unless_asked_for(stem):
    opts = _opts(stem)
    assert "sfx_drum_bandpass" in opts
    assert not opts["sfx_drum_bandpass"]
    path = str(CORPUS / f"{stem}.sid")
    assert convert(path, log=lambda m: None, **opts) == convert(
        path, log=lambda m: None, **{**opts, "sfx_drum_bandpass": False})


@needs_corpus
@needs_presets
@pytest.mark.parametrize("stem", SFX_FILES)
def test_forced_on_it_moves_exactly_the_filtering_drum_files(stem):
    """SABOTAGE TARGET: `sfx_bandpass_plan`'s record test (`eff & 0x80`) and
    the lattice read. Bangkok_Knights' filter is refused (two voices), Mega
    has none, and Star_Paws' drum record is not a filtered one."""
    opts = _opts(stem)
    path = str(CORPUS / f"{stem}.sid")
    off = convert(path, log=lambda m: None, **opts)
    on = convert(path, log=lambda m: None, **{**opts, "sfx_drum_bandpass": True})
    assert (on != off) == (stem in MOVERS), stem


@needs_corpus
@needs_presets
def test_without_sfx_drum_the_option_does_nothing():
    opts = {**_opts("Nineteen"), "sfx_drum": False}
    path = str(CORPUS / "Nineteen.sid")
    assert convert(path, log=lambda m: None, **opts) == convert(
        path, log=lambda m: None, **{**opts, "sfx_drum_bandpass": True})


def _on_ftbl(stem):
    opts = {**_opts(stem), "sfx_drum_bandpass": True}
    return parse_sng(convert(str(CORPUS / f"{stem}.sid"), log=lambda m: None,
                             **opts)).tables["FTBL"]


@needs_corpus
@needs_presets
def test_a_clearing_record_gets_no_blip():
    """SABOTAGE TARGET: the `resctl & 0x0F` test in `_filter_entries`. Nineteen's
    record 14 is a drum that routes NO voice (its `$D417` write is a clear), so
    the bandpass would be inaudible: it keeps `[params $00][cutoff][stop]`."""
    rows = _on_ftbl("Nineteen")
    assert (FILT_SET_PARAMS | LP, 0x00) in rows
    assert (FILT_SET_PARAMS | BP, 0x00) not in rows
    at = rows.index((FILT_SET_PARAMS | LP, 0x00))
    assert rows[at + 2] == (FILT_STOP, 0x00)


@needs_corpus
@needs_presets
def test_thundercats_first_hit_is_a_frame_in_at_s3():
    """SABOTAGE TARGET: `sfx_bandpass_plan` handing the lattice's first hit on.
    Thundercats is `-S3`: its plain drum loop opens on a whole frame of the
    record's own note, so the blip is call 3, two modulation calls after the
    set-cutoff row."""
    rows = _on_ftbl("Thundercats")
    at = rows.index((FILT_SET_PARAMS | BP, 0xF1))
    assert rows[at - 1] == (2, 0xFF), rows[at - 3:at + 1]
    assert rows[at - 2][0] == FILT_SET_CUTOFF


@needs_corpus
@needs_presets
@pytest.mark.parametrize("stem", sorted(MOVERS))
def test_only_the_drum_records_programs_change(stem):
    """Every filter program but the drum records' is the one the table had."""
    opts = _opts(stem)
    path = str(CORPUS / f"{stem}.sid")
    off = parse_sng(convert(path, log=lambda m: None, **opts))
    on = parse_sng(convert(path, log=lambda m: None,
                           **{**opts, "sfx_drum_bandpass": True}))
    assert on.tables["WTBL"] == off.tables["WTBL"]
    assert on.tables["PTBL"] == off.tables["PTBL"]
    # Not `len(on) > len(off)` since the classic sweeps are sized to the note
    # (test_classic_sweep_length): a drum record's plain sweep can now be
    # longer than its blip block (Thundercats 40 rows off, 37 on).
    assert on.tables["FTBL"] != off.tables["FTBL"]
    assert len(on.tables["FTBL"]) <= GT_MAX_FILT
    assert any(l == FILT_STOP and r for l, r in on.tables["FTBL"])


# --- against the real player -------------------------------------------------

SECONDS = 40
FRAMES = SECONDS * 50


def _trace(stem, on, workdir):
    opts = _opts(stem)
    if on:
        opts["sfx_drum_bandpass"] = True
    doc = json.loads(PRESETS.read_text("utf-8"))
    mult = fidelity._preset_multiplier(doc, f"{stem}.sid")
    sng = convert(str(CORPUS / f"{stem}.sid"), log=lambda m: None, **opts)
    sng, _ = fidelity.legalise_restarts(sng)
    workdir.mkdir(parents=True, exist_ok=True)
    packed = fidelity.pack_sid(sng, workdir, fidelity.GT2RELOC, mult)
    assert packed is not None
    sub, our_sub, _ = fidelity.resolve_pair(CORPUS / f"{stem}.sid", "auto")
    local = workdir / "o.sid"
    local.write_bytes((CORPUS / f"{stem}.sid").read_bytes())
    cal, _ft = fidelity.table_calibration(CORPUS / f"{stem}.sid", opts)
    orig = fidelity.run_siddump(local, SECONDS, sub, fidelity.SIDDUMP, cal)
    ours = fidelity.run_siddump(packed, SECONDS, our_sub, fidelity.SIDDUMP,
                                calls=mult)
    return orig, ours


def _bp_frames(tr):
    band = fidelity.register_timeline(tr.filter.passband_events, FRAMES)
    return [i for i, b in enumerate(band) if b == 2]


def _noise_frames(tr):
    """Frames some voice shows the drum's waveform byte, `$81`: noise with the
    gate on, which is what the hit writes. Any voice, because a drum record is
    played on voice 1 and 3 as well (Nineteen frames 952-970 are voice 1's). A
    record whose OWN waveform has the noise bit (`$E1`) makes an 'onset' test
    miss the hit, which is why this reads the whole byte."""
    out = set()
    for voice in tr:
        wf = fidelity.register_timeline(voice.wf_events, FRAMES)
        out |= {i for i in range(FRAMES) if wf[i] == 0x81}
    return out


def _since_attack(frames, attacks):
    import bisect
    atk = sorted(attacks)
    out = Counter()
    for f in frames:
        k = bisect.bisect_right(atk, f) - 1
        out[f - atk[k] if k >= 0 else None] += 1
    return out


@needs_corpus
@needs_presets
@needs_siddump
@needs_gt2reloc
@pytest.mark.parametrize("stem", ["Nineteen", "Pandora",
                                  "Trans-Atlantic_Balloon_Challenge"])
def test_the_blip_is_on_our_noise_frame_and_off_without_the_option(
        stem, tmp_path):
    """SABOTAGE TARGET: the lattice's first-hit call. Our BP frames ARE our
    noise onsets on voice 3, one for one; and with the option off there is no
    bandpass at all."""
    _orig, off = _trace(stem, False, tmp_path / "off")
    assert _bp_frames(off) == []
    _orig, on = _trace(stem, True, tmp_path / "on")
    bp = _bp_frames(on)
    assert len(bp) > 100
    stray = [f for f in bp if f not in _noise_frames(on)]
    # **NOT ZERO, AND KNOWN.** The program loops until the next filtered note
    # loads its pointer, while a rest silences the drum's wavetable first
    # (`rest_instrument`): Nineteen at -t 40 has 2 of 235 BP frames on voice
    # rests (964, 970), Pandora 7 more than the original's 364 over 60 s.
    assert len(stray) <= len(bp) // 20, (stem, stray)


@needs_corpus
@needs_presets
@needs_siddump
@needs_gt2reloc
@pytest.mark.parametrize("stem", ["Pandora",
                                  "Trans-Atlantic_Balloon_Challenge"])
def test_the_blip_sits_where_the_originals_does_within_its_note(stem, tmp_path):
    """The original's BP, counted in frames since the voice's last attack, and
    ours: the same histogram bin for bin on these two files (Trans-Atlantic
    `{1: 226, 7: 226}` at -t 60). This is the evidence the emission is right
    that the lag-aligned `band` column cannot give: it is the note's onset that
    is off, not the blip."""
    orig, on = _trace(stem, True, tmp_path)
    a = _since_attack(_bp_frames(orig), orig[2].attack_frames)
    b = _since_attack(_bp_frames(on), on[2].attack_frames)
    keys = sorted(k for k in a if a[k] > 5)
    assert keys
    for k in keys:
        assert abs(a[k] - b.get(k, 0)) <= max(1, a[k] // 20), (k, a, b)


@needs_corpus
@needs_siddump
def test_the_unrolled_cutoff_restore_does_not_fit(tmp_path):
    """Why the drum's `$60` cutoff is not carried. Restoring the cutoff after
    the spike takes an absolute `FILT_SET_CUTOFF`, a different number at every
    hit, so the exact program is unrolled: a params row and a cutoff row for
    the blip, the same two for the restore, and one modulation row, five rows a
    hit. A note sustains up to ~20 hits (Nineteen, -t 180: chains of 19-20 at
    exactly `period` frames), so one record would need 100 rows against a
    table of 64 that already holds 15-25."""
    stem, period = "Nineteen", 6
    sub, _our, _p = fidelity.resolve_pair(CORPUS / f"{stem}.sid", "auto")
    local = tmp_path / "o.sid"
    local.write_bytes((CORPUS / f"{stem}.sid").read_bytes())
    tr = fidelity.run_siddump(local, 60, sub, fidelity.SIDDUMP)
    band = fidelity.register_timeline(tr.filter.passband_events, 3000)
    bp = [i for i, b in enumerate(band) if b == 2]
    chain, longest = 1, 1
    for a, b in zip(bp, bp[1:]):
        chain = chain + 1 if b - a == period else 1
        longest = max(longest, chain)
    assert longest >= 12, longest
    rows_per_hit = 5
    assert 2 + rows_per_hit * longest > GT_MAX_FILT
