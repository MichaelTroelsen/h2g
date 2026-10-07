"""Three spellings of the classic filter routine that `find_filter` refused.

Thanatos, Tarzan and Sigma_Seven filter on 3296-8996 of their original's
frames (`-t 180`, presets) and on 0 of ours until each was read
(`detect.FILTER_SHAPE_CLAMP`, `FILTER_MODE_ENTRY_SHAPE`, and
`FilterInfo.free_running`; the disassembly is beside those names). Measured
(orig / ours, base -> this change): Thanatos 8996 / 0 -> 8994, Tarzan
8637 / 0 -> 8632, Sigma_Seven 3296 / 0 -> 3292.

Mr_Meaner, the fourth file of the census that opened this, is on the DIGI hold
and no work here is aimed at it. Its per-instrument routine now reads too
(free-running), but no record enables it, so its bytes do not move; what it
filters with is a different routine altogether (see the corpus-set test).

Every rescue is consulted only where the primary reading found nothing, so
the files the primary path reads cannot move -- the corpus sets below pin
exactly which files each one reaches.
"""
import json
from pathlib import Path

import pytest

from corpus import CORPUS, needs_corpus
from h2g.convert import convert
from h2g.detect import (detect, FILTER_MODE_SHAPE, FILTER_SHAPE,
                        FILTER_SHAPE_CLAMP)
from h2g.goatwriter import (FILT_MODULATE, FILT_SET_CUTOFF, FILT_SET_PARAMS,
                            FILT_STOP, MAX_INSTRUMENTS, _clamp_frames,
                            _clamped_block, _filter_entries,
                            _filter_step_per_call, _free_running_block)
from h2g.search import search_file
from h2g.sidfile import load_sid

REPO = Path(__file__).resolve().parents[2]


def _det(stem):
    sid = load_sid(str(CORPUS / f"{stem}.sid"))
    return sid, detect(sid, lambda m: None)


def gt_filter_calls(entries, start, calls, cutoff=0):
    """The cutoff after each play call, transcribed from player.s
    `mt_filtstep` .. `mt_storecutoff` (GoatTracker 2.77). `start` is the
    1-based step an instrument's filter pointer loads; time starts at 0."""
    left = [a for a, _ in entries] + [0]
    right = [b for _, b in entries] + [0]
    step, time, out = start, 0, []

    def next_step(k):                       # mt_nextfiltstep(2)
        return right[k] if left[k] == FILT_STOP else k + 1

    for _ in range(calls):
        if step:
            if time:                        # mt_filtmod
                cutoff = (cutoff + right[step - 1]) & 0xFF
                time -= 1
                if not time:
                    step = next_step(step)
            else:
                lf = left[step - 1]
                if lf == FILT_SET_CUTOFF:   # mt_setcutoff
                    cutoff = right[step - 1]
                    step = next_step(step)
                elif lf < 0x80:             # mt_newfiltmod
                    time = lf
                    cutoff = (cutoff + right[step - 1]) & 0xFF
                    time -= 1
                    if not time:
                        step = next_step(step)
                else:                       # mt_setfilt
                    if left[step] != FILT_SET_CUTOFF:
                        step = next_step(step)
                    else:                   # set cutoff on the same call
                        step += 1
                        cutoff = right[step - 1]
                        step = next_step(step)
        out.append(cutoff)
    return out


# --- detection: which files each rescue reaches -----------------------------

@needs_corpus
def test_each_rescue_reaches_exactly_these_files():
    """SABOTAGE TARGET: drop any of the three rescues from `find_filter` and
    its set here comes back without its file.

    `free_running` also reaches After_8, Mr_Meaner and Rikky -- three DIGI
    held files, read by the corpus-wide rule, not aimed at -- and no record
    of any of them sets `FILTER_ENABLE_BIT`, so none of them moves a byte.
    Mr_Meaner's audible filter is not this routine: it is a global sweep at
    $14AD, every third frame `LDA #$F2 / STA $D417 / LDA #imm / STA $D416`
    with the immediate rewritten `(x + 1) | $14`, outside any instrument."""
    clamp, entry, free = set(), set(), set()
    for p in sorted(CORPUS.glob("*.sid")):
        try:
            sid, det = _det(p.stem)
        except Exception:                                   # noqa: BLE001
            continue
        f = det.filter
        if f is None:
            continue
        if f.clamp:
            clamp.add(p.stem)
        if f.free_running:
            free.add(p.stem)
        j = search_file(sid.data, FILTER_MODE_SHAPE)
        if not sid.data[j + 1] & 0x70:
            entry.add(p.stem)
    assert clamp == {"Thanatos"}, clamp
    assert entry == {"Tarzan"}, entry
    assert free == {"Sigma_Seven", "After_8", "Mr_Meaner", "Rikky"}, free


def test_the_clamp_must_branch_onto_the_resctl_load():
    """SABOTAGE TARGET: wildcard the BMI's offset and a branch that lands
    anywhere but `LDA resctl,Y` reads as the clamp. Thanatos' is the only
    BMI spelling in the corpus, so only a synthetic routine can say this."""
    body = ("AD 6B C4 29 20 F0 15 BD 7B C4 30 {:02X} 18 79 AD C4 9D 7B C4 "
            "8D 16 D4 B9 AC C4 8D 17 D4")
    blob = lambda off: bytes.fromhex("EA " * 4 + body.format(off))  # noqa: E731
    assert search_file(blob(0x0A), FILTER_SHAPE_CLAMP) == 4
    assert search_file(blob(0x07), FILTER_SHAPE_CLAMP) <= -1


@needs_corpus
def test_the_clamp_spelling_is_disjoint_from_the_primary():
    for p in sorted(CORPUS.glob("*.sid")):
        data = load_sid(str(p)).data
        if search_file(data, FILTER_SHAPE_CLAMP) > -1:
            assert search_file(data, FILTER_SHAPE) <= -1, p.stem


@needs_corpus
@pytest.mark.parametrize("stem,cutoff,passband,clamp,free", [
    ("Thanatos", 0x20, 0x10, True, False),     # $C0D3 LDA #$20 / STA $C47B,X
    ("Tarzan", 0x00, 0x10, False, False),      # $550C LDA #$1F / STA $D418
    ("Sigma_Seven", 0x08, 0x10, False, True),  # $84A1's file byte
])
def test_the_reading(stem, cutoff, passband, clamp, free):
    _sid, det = _det(stem)
    f = det.filter
    assert f is not None and det.ilv_filter is None
    assert (f.cutoff, f.passband, f.clamp, f.free_running) == (
        cutoff, passband, clamp, free)


# --- emission ----------------------------------------------------------------

@pytest.mark.parametrize("start,step,mult", [
    (0x20, 0x03, 4), (0x20, 0x03, 1), (0x20, 0x07, 3), (0x10, 0x05, 2),
    (0x20, 0xFE, 4), (0x00, 0x01, 5), (0x40, 0x7F, 1)])
def test_a_clamped_sweep_holds_the_players_value(start, step, mult):
    """SABOTAGE TARGET: run the modulation `frames` calls (the player's frame
    count, forgetting that a row's time is in CALLS) and Thanatos' own case,
    $20 + 3/frame at -S4 with +1 per call, holds $40 where the player holds
    $80. Its clock-exact alternative, 128 calls, would hold $A0."""
    c = start
    for _ in range(_clamp_frames(start, step)):
        c = (c + step) & 0xFF
    assert c & 0x80                                   # the player's hold
    per_call = _filter_step_per_call(step, mult)
    block = _clamped_block(0x10, 0xF4, start, step, per_call)
    assert block[0] == (FILT_SET_PARAMS | 0x10, 0xF4)
    assert block[1] == (FILT_SET_CUTOFF, start)
    assert block[-1] == (FILT_STOP, 0x00)
    assert all(0 < left <= FILT_MODULATE for left, _ in block[2:-1])
    got = gt_filter_calls(block, 1, 2000)
    p = per_call - 256 if per_call >= 0x80 else per_call
    tol = abs(p) // 2 if (step - 256 if step >= 0x80 else step) % p else 0
    assert abs(((got[-1] - c + 128) & 0xFF) - 128) <= tol, (got[-1], c)


def test_a_note_starting_negative_writes_no_cutoff():
    assert _clamp_frames(0x90, 0x03) == 0
    assert _clamped_block(0x10, 0xF4, 0x90, 0x03, 1) == [
        (FILT_SET_PARAMS | 0x10, 0xF4), (FILT_STOP, 0x00)]


@pytest.mark.parametrize("at,per_call", [(1, 0x02), (7, 0x02), (4, 0xFD)])
def test_a_free_running_sweep_never_resets_and_never_pauses(at, per_call):
    """SABOTAGE TARGET: give the block a SET_CUTOFF row, or jump back to the
    params row instead of the modulation row, and the cutoff either resets
    or skips a call every $7F."""
    block = _free_running_block(0x10, 0xF4, per_call, at)
    assert all(left != FILT_SET_CUTOFF for left, _ in block)
    table = [(0x90, 0x00)] * (at - 1) + block
    got = gt_filter_calls(table, at, 600, cutoff=0x37)
    assert got[0] == 0x37                     # the params call, no reset
    for a, b in zip(got[1:], got[2:]):
        assert (b - a) & 0xFF == per_call, (a, b)


def test_a_static_free_running_record_stops():
    assert _free_running_block(0x10, 0xF4, 0, 1) == [
        (FILT_SET_PARAMS | 0x10, 0xF4), (FILT_STOP, 0x00)]


@needs_corpus
@pytest.mark.parametrize("stem,mult,want", [
    ("Thanatos", 4, [(0x90, 0xF4), (0x00, 0x20), (0x60, 0x01), (0xFF, 0x00)]),
    ("Sigma_Seven", 1, [(0x90, 0xF4), (0x7F, 0x02), (0xFF, 0x02),
                        (0x90, 0xF4), (0x7F, 0x02), (0xFF, 0x05),
                        (0x90, 0xF4), (0x7F, 0x02), (0xFF, 0x08)]),
])
def test_the_files_tables(stem, mult, want):
    sid, det = _det(stem)
    entries, _ = _filter_entries(sid, det,
                                 min(det.instr_used + 1, MAX_INSTRUMENTS),
                                 multiplier=mult)
    assert entries == want, entries


@needs_corpus
@pytest.mark.parametrize("stem", ["Thanatos", "Tarzan", "Sigma_Seven"])
def test_the_conversion_carries_a_filter_table(stem):
    """At the seam: the shipped presets (`filters` is in their `always`
    block) put a routed SET_PARAMS row into the converted file's FTBL."""
    import fidelity as F
    from songview import parse_sng
    doc = json.loads((REPO / "presets.json").read_text("utf-8"))
    blob = convert(str(CORPUS / f"{stem}.sid"), log=lambda m: None,
                   **F._preset_opts(doc, f"{stem}.sid"))
    ftbl = parse_sng(blob).tables["FTBL"]
    assert any(FILT_SET_PARAMS <= left < FILT_STOP and right & 0x07
               for left, right in ftbl), ftbl


def test_commando_is_untouched():
    ref = (REPO / "Commando.sng").read_bytes()
    assert convert(str(REPO / "Commando.sid"), log=lambda m: None,
                   filters=True) == ref
