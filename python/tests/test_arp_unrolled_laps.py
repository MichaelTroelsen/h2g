"""The per-note arp phase split spells every lap the counter needs, not the first.

The fixed arp's octave is chosen on a global counter that steps once per
passing call (`fixed_arp_note_residues`). The song loops, and a loop body of
`R` rows of `frames` calls starts its next lap `(R * frames) % period`
residues further on, so a pattern played every lap attacks on different
residues each time round. Through v0.5.519 the plan walked one lap and
renamed for that one for ever.

Game_Killer voice 2 is the case: one 18-row pattern, `frames` 2 at `-S9`, 36
calls a lap, a shift of 4 in a period of 8. The original alternates two
spellings of the pattern a lap apiece (80 frames, 12 notes, the joint cycle
of the counter and the gate's skipped frame) and we played the first one
twice. Octave state (base or an octave up) frame by frame against the
original, 60 s, packed under presets, lag 4:

    before   260 of 1649 frames disagree (1389 agree)
    after    149 of 1612 frames disagree (1463 agree)    -- 180 s: 785 -> 449

`fixed_arp_unrolled_tracks` writes the body out `period / gcd(shift, period)`
times and `_note_phase_split` spells each copy. What is left is not the
residue: all 149 sit in 7-frame notes (the ones that span the gate's skipped
frame), at offsets 1, 5 and 6, and the 337 compared frames of the 6-frame
notes are exact. Which frame the skip falls on in a note is a second axis
(residue x skip phase, 8 x 9 = 72 pairings, 12 on this voice) that a clone
keyed on the residue alone cannot say, and a clone per pair does not fit a
wavetable already at 232 of 255 entries (gated-duty-step-rounding).

Corpus byte-hash under presets, 95 files (89 converted, 6 refused): exactly
Game_Killer moves. Zoids also moved on the first build -- its unrolled lap
spelled what the first lap spells, 42 bytes of orderlist for the same sound,
identical at 180 s on every column -- so a track whose copies all want what
their first lap wants goes back to its own orderlist.
"""
import json
import pathlib
import sys
from types import SimpleNamespace

import pytest

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[1]))

import fidelity                                              # noqa: E402
import songview                                              # noqa: E402
from corpus import CORPUS, needs_corpus                      # noqa: E402
from h2g.convert import convert                              # noqa: E402
from h2g.goatwriter import (ORDERLIST_MAX, apply_tempo_duty_edits,  # noqa: E402
                            fixed_arp_phase_split_plan,
                            fixed_arp_unrolled_tracks, SongSpeeds)

REPO_ROOT = pathlib.Path(__file__).resolve().parents[2]

needs_siddump = pytest.mark.skipif(
    not pathlib.Path(fidelity.SIDDUMP).exists(),
    reason="no siddump on this machine (tools/siddump-rt, see its README)")
needs_gt2reloc = pytest.mark.skipif(
    not pathlib.Path(fidelity.GT2RELOC).exists(),
    reason="no gt2reloc on this machine")


def _fake(monkeypatch, tracks, frames=3):
    """A one-subtune parity-mask file (period 2), rows of `frames` calls, one
    fixed-arp record (GT 1, lead 0). Pattern 0: three notes, instrument 1
    named on row 0. Pattern 1: one note on instrument 5, which is no arp
    record. Pattern 2: a rest."""
    import h2g.goatwriter as G
    monkeypatch.setattr(G.primitives, "fixed_arp_mask",
                        lambda sid, det: (0x01, 0xF0))
    monkeypatch.setattr(G.arpeggio, "fixed_arp_counter_base",
                        lambda sid, det: 0)
    monkeypatch.setattr(G.arpeggio, "fixed_arp_first_fetch",
                        lambda sid, det: 0)
    monkeypatch.setattr(G.tempo, "find_song_speeds",
                        lambda sid, det: SongSpeeds((frames,), 0, None))
    det = SimpleNamespace(arp_fixed_up=0x0C, effect_arp=True,
                          instr_start=0, instr_stride=8)
    sid = SimpleNamespace(data=bytes([0, 0, 0x41, 0, 0, 0, 0, 0x04]),
                          subtunes=1)
    end = [0xFF, 0, 0, 0]
    patterns = [[0x70, 1, 0, 0, 0x72, 0, 0, 0, 0x74, 0, 0, 0] + end,
                [0x70, 5, 0, 0] + end,
                [0xBD, 0, 0, 0] + end]
    return list(tracks), patterns, (sid, det)


def test_a_loop_whose_lap_shifts_the_residue_is_written_out(monkeypatch):
    """Pattern 0 is 3 rows of 3 calls: 9 calls a lap, residue shift 1 in a
    period of 2, so two laps make a whole cycle."""
    tracks, patterns, (sid, det) = _fake(
        monkeypatch, [[0, 0xFF, 0], [2, 0xFF, 0], [2, 0xFF, 0]])
    out, folds = fixed_arp_unrolled_tracks(sid, det, tracks, patterns)
    assert out[0] == [0, 0, 0xFF, 0]
    assert folds[0] == (0, 1, 1)
    # A rest row is 3 calls too: written out all the same -- whether a copy
    # is kept is the plan's call (`test_laps_that_want_the_same_bytes...`).
    assert out[1] == [2, 2, 0xFF, 0]
    assert folds[1] == (0, 1, 1)


def test_the_restart_target_is_where_the_body_starts(monkeypatch):
    """`[1, 0, 0xFF, 1]` loops back to position 1: only entry 1 repeats."""
    tracks, patterns, (sid, det) = _fake(
        monkeypatch, [[1, 0, 0xFF, 1], [2, 0xFF, 0], [2, 0xFF, 0]])
    out, folds = fixed_arp_unrolled_tracks(sid, det, tracks, patterns)
    # Entry 0 is a 1-row prefix; the body is entry 1 (3 rows, 9 calls).
    assert out[0] == [1, 0, 0, 0xFF, 1]
    assert folds[0] == (1, 2, 1)


def test_an_even_lap_needs_no_copy(monkeypatch):
    """Rows of 2 calls: 6 a lap, a whole number of periods."""
    tracks, patterns, (sid, det) = _fake(
        monkeypatch, [[0, 0xFF, 0], [2, 0xFF, 0], [2, 0xFF, 0]], frames=2)
    out, folds = fixed_arp_unrolled_tracks(sid, det, tracks, patterns)
    assert out is tracks
    assert folds == [None, None, None]


def test_declined_where_the_first_lap_is_not_the_others(monkeypatch):
    """No restart byte; a restart target after a `$Dn` repeat (the repeat
    holds on the first pass only); a copy that would pass the orderlist."""
    tracks, patterns, (sid, det) = _fake(
        monkeypatch, [[0], [0xD1, 0, 0xFF, 1], [0xFF, 0]])
    out, _ = fixed_arp_unrolled_tracks(sid, det, tracks, patterns)
    assert out is tracks
    long_body = [0] * (ORDERLIST_MAX // 2)        # odd: 9 calls a lap each
    tracks, patterns, (sid, det) = _fake(
        monkeypatch, [long_body + [0xFF, 0], [2, 0xFF, 0], [2, 0xFF, 0]])
    out, _ = fixed_arp_unrolled_tracks(sid, det, tracks, patterns)
    assert out[0] == tracks[0]
    assert len(long_body) % 2 == 1 and len(long_body) * 2 + 2 > ORDERLIST_MAX


def test_each_lap_names_its_own_instruments(monkeypatch):
    """One orderlist entry looped: residues 0, 1, 0 the first lap and 1, 0, 1
    the second. The one-lap plan renamed for the first alone; the plan now
    spells both, the second as a copy -- the same bytes the two-entry
    orderlist `[0, 0, 0xFF, 0]` gets (`test_arp_octave`)."""
    tracks, patterns, (sid, det) = _fake(
        monkeypatch, [[0, 0xFF, 0], [2, 0xFF, 0], [2, 0xFF, 0]])
    split = fixed_arp_phase_split_plan(sid, det, tracks, patterns, True, 0,
                                       1, 2)
    assert split is not None
    assert split.clones == [(1, 2, 1)]
    assert split.tracks[0] == [0, 3, 0xFF, 0]
    assert split.edits == {0: {1: (0, 2), 2: (0, 1)},
                           3: {0: (1, 2), 1: (0, 1), 2: (0, 2)}}
    out = apply_tempo_duty_edits(split.patterns, split)
    assert [out[0][1], out[0][5], out[0][9]] == [1, 2, 1]
    assert [out[3][1], out[3][5], out[3][9]] == [2, 1, 2]


def test_laps_that_want_the_same_bytes_stay_one_lap(monkeypatch):
    """Voice 1 loops a single note on a record that is no arp record: its
    residue flips every lap and nothing is renamed, so its orderlist is not
    written out (Zoids moved +42 bytes of orderlist before this)."""
    tracks, patterns, (sid, det) = _fake(
        monkeypatch, [[0, 0xFF, 0], [1, 0xFF, 0], [2, 0xFF, 0]])
    out, folds = fixed_arp_unrolled_tracks(sid, det, tracks, patterns)
    assert out[1] == [1, 1, 0xFF, 0]          # the helper writes it out ...
    split = fixed_arp_phase_split_plan(sid, det, tracks, patterns, True, 0,
                                       1, 2)
    assert split.tracks[1] == [1, 0xFF, 0]    # ... the plan puts it back
    assert split.tracks[0] == [0, 3, 0xFF, 0]


# --- the corpus --------------------------------------------------------------

def _presets() -> dict:
    return json.loads((REPO_ROOT / "presets.json").read_text(encoding="utf-8"))


def _convert(name):
    return convert(str(CORPUS / name), log=lambda x: None,
                   **fidelity._preset_opts(_presets(), name))


@needs_corpus
def test_game_killers_voice_two_alternates_two_spellings():
    s = songview.parse_sng(_convert("Game_Killer.sid"))
    a, b, ff, restart = s.tracks[2]
    assert (ff, restart) == (0xFF, 0)
    rows_a = [s.patterns[a][i] for i in range(1, len(s.patterns[a]) - 3, 4)]
    rows_b = [s.patterns[b][i] for i in range(1, len(s.patterns[b]) - 3, 4)]
    assert a != b and rows_a != rows_b
    # The other voices' orderlists are as long as they were.
    assert [len(t) for t in s.tracks[:2]] == [61, 100]


@needs_corpus
def test_zoids_is_what_it_was_without_the_unrolled_laps(monkeypatch):
    """Zoids' lap shifts the residue and its later laps want what the first
    wants: with the unrolling switched off the conversion is the same bytes
    (and Game_Killer's is not)."""
    from h2g.goatwriter import arpeggio
    zoids, killer = _convert("Zoids.sid"), _convert("Game_Killer.sid")
    monkeypatch.setattr(arpeggio, "fixed_arp_unrolled_tracks",
                        lambda sid, det, tracks, patterns:
                        (tracks, [None] * len(tracks)))
    assert _convert("Zoids.sid") == zoids
    assert _convert("Game_Killer.sid") != killer


def _octave_states(tracks, voice, frames, shift):
    v = tracks[voice]
    fr = fidelity.register_timeline(v.freq_events, frames + 40)
    attacks = set(v.attack_frames)
    out, base = {}, None
    for k in range(len(fr)):
        if k in attacks:
            base = fr[k]
        if base:
            out[k - shift] = ("u" if abs(fr[k] - 2 * base) <= 2
                              else "b" if fr[k] == base else ".")
    return out, sorted(a - shift for a in attacks)


@needs_corpus
@needs_siddump
@needs_gt2reloc
def test_game_killers_voice_two_octave_frames_agree_beyond_the_first_lap(
        tmp_path):
    name = "Game_Killer.sid"
    m = _presets()["songs"][name]["multiplier"]
    packed = fidelity.pack_sid(_convert(name), tmp_path, fidelity.GT2RELOC, m)
    assert packed is not None and packed.exists()
    orig = fidelity.run_siddump(CORPUS / name, 60, 0, calls=1)
    ours = fidelity.run_siddump(packed, 60, 0, calls=m)
    lag, _ = fidelity.startup_lag(orig, ours)
    so, ao = _octave_states(orig, 2, 3000, 0)
    su, au = _octave_states(ours, 2, 3000 + lag, lag)
    assert ao == au[:len(ao)]            # every onset exact (call_phase)
    keys = [f for f in so if f in su and so[f] in "bu" and su[f] in "bu"
            and "u" in (so[f], su[f])]
    bad = [f for f in keys if so[f] != su[f]]
    assert len(keys) > 1500
    # 260 before the unrolled laps (1389 of 1649 agreeing), 149 after.
    assert len(bad) < 200, (len(bad), len(keys))
    # The remainder is the skip phase inside a 7-frame note: a 6-frame note
    # (no skipped frame in it) is exact.
    ends = ao[1:] + [ao[-1] + 40]
    seven = {a for a, e in zip(ao, ends) if e - a == 7}
    for f in bad:
        a = max(x for x in ao if x <= f)
        assert a in seven, (f, a)
