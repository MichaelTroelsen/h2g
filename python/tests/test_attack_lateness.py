"""attack-lateness-fidelity-column: the rise-to-attack delay reading.

No other fidelity column reads what the envelope DID, so a conversion whose
every note starts ~200 rasterlines late scored the same as the original. The
reading (python/attack_lateness.py, `fidelity.py --attack-census`) is ENV3 off
VICE's per-rasterline dump, each voice swapped onto voice 3.

The reduction is tested on synthetic traces; the two swaps on real bytes; the
fidelity wiring with the VICE call stubbed; and one live VICE run on Commando
(skipped where vsid or gt2reloc is absent).
"""
import argparse
import pathlib
import sys

import pytest

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent.parent))
sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent))

import attack_lateness as A
import fidelity as F

REPO_ROOT = pathlib.Path(__file__).resolve().parents[2]
COMMANDO = REPO_ROOT / "Commando.sid"


# --------------------------------------------------------------------------
# synthetic traces
# --------------------------------------------------------------------------
def _trace(n=6000, notes=(), wave=0x41):
    """ctrl/env/adsr lists. A note is (rise_line, delay, gate_lines, attack,
    wave); ENV3 climbs by 1 a line from rise+delay."""
    ctrl = [0x40] * n
    env = [0] * n
    adsr = [0x0000] * n
    for rise, delay, glen, attack, w in notes:
        for k in range(rise, rise + glen):
            ctrl[k] = w
        for k in range(rise, n):
            adsr[k] = attack << 12
        for k in range(rise + delay, rise + glen):
            env[k] = min(255, k - (rise + delay) + 1)
        for k in range(rise + glen, min(n, rise + glen + 10)):
            env[k] = env[rise + glen - 1]
    return ctrl, env, adsr


def _read(notes, **kw):
    return A.summarise(A.find_rises(*_trace(notes=notes, **kw)))


def test_a_prompt_note_is_not_late_and_a_late_one_is():
    s = _read([(500, 1, 800, 0, 0x41), (1500, 205, 800, 0, 0x41)])
    assert (s.measured, s.late, s.delays) == (2, 1, [1, 205])
    assert s.median == 103


def test_the_threshold_is_100_lines_inclusive():
    s = _read([(500, 99, 800, 0, 0x41), (1500, 100, 800, 0, 0x41)])
    assert s.delays == [99, 100] and s.late == 1


def test_a_drum_is_counted_apart_from_the_tones():
    # noise ($81) begins 300 lines after the pulse-wave rise: the drum tick
    ctrl, env, adsr = _trace(notes=[(500, 1, 800, 0, 0x41)])
    for k in range(800, 1000):
        ctrl[k] = 0x81
    s = A.summarise(A.find_rises(ctrl, env, adsr))
    assert (s.rises, s.drums) == (0, 1)


def test_a_rise_that_starts_in_noise_is_not_a_tone():
    s = _read([(500, 1, 800, 0, 0x81)])
    assert s.rises == 0


def test_a_saturated_envelope_cannot_rise_and_is_not_scored():
    ctrl, env, adsr = _trace(notes=[(500, 1, 800, 0, 0x41)])
    env[499] = 255
    s = A.summarise(A.find_rises(ctrl, env, adsr))
    assert (s.rises, s.saturated, s.measured) == (1, 1, 0)


def test_a_gate_that_falls_before_the_envelope_moves_is_never_up():
    s = _read([(500, 900, 800, 0, 0x41)])
    assert (s.rises, s.never_up, s.measured) == (1, 1, 0)


def test_a_slow_attack_nibble_is_excluded_not_scored_late():
    # attack 13's own period is ~186 lines: 190 is on time for it
    s = _read([(500, 190, 800, 13, 0x41), (1500, 190, 800, 2, 0x41)])
    assert (s.slow, s.measured, s.late) == (1, 1, 1)


def test_startup_and_a_window_that_runs_off_the_end_are_not_read():
    s = _read([(100, 1, 800, 0, 0x41), (5000, 1, 700, 0, 0x41)])
    assert s.rises == 0


def test_a_gate_held_past_the_fall_window_is_not_read():
    s = _read([(500, 1, A.FALL_WINDOW + 50, 0, 0x41)], n=9000)
    assert s.rises == 0


def test_merge_pools_delays_rather_than_averaging():
    a = _read([(500, 1, 800, 0, 0x41)] * 1)
    b = _read([(500, 205, 800, 0, 0x41), (1500, 205, 800, 0, 0x41)])
    m = A.merge([a, b])
    assert (m.measured, m.late, m.median) == (3, 2, 205)


def test_delta_is_ours_minus_original_in_points_and_none_when_unread():
    prompt = _read([(500, 1, 800, 0, 0x41), (1500, 1, 800, 0, 0x41)])
    late = _read([(500, 205, 800, 0, 0x41), (1500, 1, 800, 0, 0x41)])
    assert A.lateness_delta(prompt, late) == 50.0
    assert A.lateness_delta(late, prompt) == -50.0
    assert A.lateness_delta(A.Stats(), late) is None


# --------------------------------------------------------------------------
# the two swaps
# --------------------------------------------------------------------------
def _sng(songs):
    """A header, then `songs` = [(orderlist0, orderlist1, orderlist2), ...]
    each `[length, entries..., 0xFF, restart]` (length counts the $FF), then a recognisable tail."""
    out = bytearray(b"GTS5" + bytes(96))
    out.append(len(songs))
    for lists in songs:
        for entries in lists:
            out += bytes([len(entries) + 1]) + bytes(entries) + b"\xff\x00"
    return bytes(out + b"TAIL")


def test_sng_swap_exchanges_voice_v_with_voice_3_in_every_subtune():
    sng = _sng([([1, 2], [3], [4, 5, 6]), ([7], [8, 9], [10])])
    assert A.swap_sng_voice(sng, 2) == sng
    assert A.swap_sng_voice(sng, 0) == _sng([([4, 5, 6], [3], [1, 2]),
                                             ([10], [8, 9], [7])])
    assert A.swap_sng_voice(sng, 1) == _sng([([1, 2], [4, 5, 6], [3]),
                                             ([7], [10], [8, 9])])


@pytest.mark.parametrize("v", [0, 1])
def test_sng_swap_is_its_own_inverse_and_keeps_the_length(v):
    sng = _sng([([1, 2], [3], [4, 5, 6])])
    once = A.swap_sng_voice(sng, v)
    assert once != sng and len(once) == len(sng)
    assert A.swap_sng_voice(once, v) == sng


def test_sng_swap_refuses_an_orderlist_that_does_not_end_in_ff():
    bad = bytearray(_sng([([1, 2], [3], [4])]))
    bad[bad.index(0xFF)] = 0x07
    with pytest.raises(ValueError):
        A.swap_sng_voice(bytes(bad), 0)


def test_sid_swap_patches_only_the_voice_table():
    raw = bytes([9, 9, 0x00, 0x07, 0x0E, 9, 9])
    assert A.swap_sid_voice(raw, 2) == raw
    assert A.swap_sid_voice(raw, 0) == bytes([9, 9, 0x0E, 0x07, 0x00, 9, 9])
    assert A.swap_sid_voice(raw, 1) == bytes([9, 9, 0x00, 0x0E, 0x07, 9, 9])


def test_sid_swap_picks_the_requested_table_and_raises_without_one():
    raw = bytes([0, 7, 14, 5, 0, 7, 14])
    assert A.voice_table_hits(raw) == [0, 4]
    assert A.swap_sid_voice(raw, 0, 1) == bytes([0, 7, 14, 5, 14, 7, 0])
    with pytest.raises(IndexError):
        A.swap_sid_voice(bytes(10), 0)


def test_every_commando_orderlist_swap_is_a_permutation_of_the_same_bytes():
    sng = F.convert(str(COMMANDO), log=lambda m: None)
    for v in (0, 1):
        sw = A.swap_sng_voice(sng, v)
        assert len(sw) == len(sng) and sw != sng
        assert sorted(sw) == sorted(sng)
        assert A.swap_sng_voice(sw, v) == sng


# --------------------------------------------------------------------------
# the swap check
# --------------------------------------------------------------------------
def _edges_trace(rises_by_voice):
    n = 4000
    ctrl = []
    for rs in rises_by_voice:
        c = [0x40] * n
        for r in rs:
            for k in range(r, r + 50):
                c[k] = 0x41
        ctrl.append(c)
    return A.Trace(ctrl=ctrl, adsr3=[0] * n, env3=[0] * n)


def test_a_swap_that_put_voice_v_on_voice_3_verifies():
    ident = _edges_trace([[500, 1000, 1500], [600], [700, 2000]])
    swapped = _edges_trace([[0], [0], [500, 1000, 1500]])
    assert A.swap_verified(ident, swapped, 0)


def test_a_swap_the_player_ignored_does_not_verify():
    ident = _edges_trace([[500, 1000, 1500, 2500, 3000], [600], [700, 2000]])
    ignored = _edges_trace([[0], [0], [700, 2000]])       # voice 3 still itself
    assert not A.swap_verified(ident, ignored, 0)


def test_read_side_drops_an_unverified_voice_and_names_it(monkeypatch, tmp_path):
    ident = _edges_trace([[500, 1000, 1500, 2500, 3000], [600], [700, 2000]])
    good = _edges_trace([[0], [0], [600]])
    traces = {"i": ident, "ok": good, "ignored": ident}
    monkeypatch.setattr(A, "trace", lambda p, *a, **k: traces[p.name])
    got = A.read_side({2: pathlib.Path("i"), 1: pathlib.Path("ok"),
                       0: pathlib.Path("ignored")}, 10, 0, tmp_path)
    assert got.unswapped == [0]
    assert set(got.voices) == {1, 2}


def test_read_side_falls_back_to_the_next_table_of_an_original(monkeypatch, tmp_path):
    ident = _edges_trace([[500, 1000, 1500, 2500, 3000], [600], [700, 2000]])
    good = _edges_trace([[0], [0], [500, 1000, 1500, 2500, 3000]])
    traces = {"i": ident, "h0": ident, "h1": good, "v1": _edges_trace([[0], [0], [600]])}
    monkeypatch.setattr(A, "trace", lambda p, *a, **k: traces[p.name])
    got = A.read_side({2: pathlib.Path("i"), 1: pathlib.Path("v1"),
                       0: pathlib.Path("h0")}, 10, 0, tmp_path,
                      alternatives={0: [pathlib.Path("h1")]})
    assert got.unswapped == [] and set(got.voices) == {0, 1, 2}


# --------------------------------------------------------------------------
# the report
# --------------------------------------------------------------------------
def _reading(name, orig, ours, bad=()):
    side = lambda s: A.SideReading(s, {}, list(bad))          # noqa: E731
    return A.FileReading(name, side(orig), side(ours))


def test_report_flags_a_defect_and_a_sid_inherent_lateness_differently():
    prompt = _read([(500, 1, 800, 0, 0x41)] * 1)
    late = _read([(500, 205, 800, 0, 0x41)])
    text = A.report([_reading("Defect.sid", prompt, late),
                     _reading("Inherent.sid", late, late)], 60)
    assert "| Defect.sid | 0/1 (1) | 1/1 (205) | +100 |" in text
    assert "| Inherent.sid | 1/1 (205) | 1/1 (205) | +0 |" in text
    assert "on 1: Defect.sid." in text


def test_report_lists_what_it_could_not_read_and_what_it_dropped():
    prompt = _read([(500, 1, 800, 0, 0x41)])
    bad = A.FileReading("Broken.sid", error="no 00 07 0E voice table")
    text = A.report([bad, _reading("Dropped.sid", prompt, prompt, bad=[0])], 60,
                    {"max_hard_restart": True})
    assert "- Broken.sid: no 00 07 0E voice table" in text
    assert "| Dropped.sid | 0/1 (1) | 0/1 (1) | +0 | [0] / [0] |" in text
    assert "`{'max_hard_restart': True}`" in text


# --------------------------------------------------------------------------
# the fidelity wiring, VICE stubbed
# --------------------------------------------------------------------------
def test_the_flag_is_on_the_command_line():
    import io
    from contextlib import redirect_stdout
    buf = io.StringIO()
    with redirect_stdout(buf), pytest.raises(SystemExit):
        F.main(["--help"])
    assert "--attack-census" in buf.getvalue()
    assert "--attack-opts" in buf.getvalue()


def test_the_row_swaps_both_sides_and_reads_both_with_the_same_reduction(
        monkeypatch, tmp_path):
    packed = []

    def fake_pack(sng, wd, exe, mult=1, **kw):
        packed.append(sng)
        out = wd / "b.sid"
        out.write_bytes(b"ours" + bytes([len(packed)]))
        return out

    seen = []

    def fake_read_side(variants, seconds, subtune, scratch, exe, alts=None, jobs=1):
        seen.append((variants, alts, subtune))
        s = A.Stats(rises=4, measured=4, late=len(seen) % 2 * 4, delays=[1] * 4)
        return A.SideReading(s, {}, [])

    monkeypatch.setattr(F, "pack_sid", fake_pack)
    monkeypatch.setattr(A, "read_side", fake_read_side)
    args = argparse.Namespace(subtune="auto", gt2reloc="x", seconds=7, vice_exe=None)
    rec = F.attack_census_row(COMMANDO, tmp_path, {}, args, 1)
    assert rec.error is None
    # three packs, voice 0/1 with orderlists exchanged, voice 2 as converted
    assert len(packed) == 3
    assert packed[2] != packed[0] != packed[1]
    assert A.swap_sng_voice(packed[0], 0) == packed[2]
    (ovars, oalts, _), (uvars, ualts, _) = seen
    raw = COMMANDO.read_bytes()
    assert ovars[2].read_bytes() == raw
    assert ovars[0].read_bytes() == A.swap_sid_voice(raw, 0)
    assert ovars[1].read_bytes() == A.swap_sid_voice(raw, 1)
    assert uvars[0].parent.name == "ours_v0"
    assert rec.delta == -100.0      # original 4/4 late, ours 0/4


def test_a_file_without_a_voice_table_is_reported_not_guessed(monkeypatch, tmp_path):
    sid = tmp_path / "NoTable.sid"
    sid.write_bytes(COMMANDO.read_bytes().replace(bytes([0, 7, 14]), bytes([1, 7, 14])))
    args = argparse.Namespace(subtune="auto", gt2reloc="x", seconds=7, vice_exe=None)
    monkeypatch.setattr(F, "convert", lambda *a, **k: COMMANDO.read_bytes())
    monkeypatch.setattr(F, "legalise_restarts", lambda b: (b, 0))
    rec = F.attack_census_row(sid, tmp_path / "w", {}, args, 1)
    assert rec.error and "voice table" in rec.error


# --------------------------------------------------------------------------
# live: one VICE run, the reading on real bytes
# --------------------------------------------------------------------------
needs_vice = pytest.mark.skipif(
    not pathlib.Path(A.vicetrace.VSID).exists()
    or not pathlib.Path(F.GT2RELOC).exists(),
    reason="no vsid or gt2reloc on this machine")


@needs_vice
def test_live_commando_original_is_prompt_and_every_swap_verifies(tmp_path):
    """Commando's original starts its tones on time (0 of 201 late over 60 s,
    adsr-attack-delay-fix-candidates); a short window must agree, and the
    voice-table patch must put each voice on voice 3."""
    args = argparse.Namespace(subtune="auto", gt2reloc=F.GT2RELOC, seconds=20,
                              vice_exe=None)
    rec = F.attack_census_row(COMMANDO, tmp_path, {}, args, 1)
    assert rec.error is None, rec.error
    assert rec.orig.unswapped == [] and rec.ours.unswapped == []
    assert set(rec.orig.voices) == {0, 1, 2}
    assert rec.orig.stats.measured > 20
    assert rec.orig.stats.late == 0
