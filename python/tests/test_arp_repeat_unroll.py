"""The fixed-arp phase split spells every play of a repeated orderlist entry.

`_note_phase_split` keeps the FIRST play's spelling for all plays of a
repeated entry (`$Dn pattern`), the right thing when the plays agree and
wrong when they do not. The fixed arp's counter steps once per passing call
and a pattern of `R` rows of `frames` calls shifts the next play by
`(R * frames) % period`, so the plays of a repeat attack on different
residues exactly when that shift is nonzero. `pitch_seq_phase_split_plan`
already unrolled such an entry (`_phase_divergent_repeats` /
`_expand_repeats`); `fixed_arp_phase_split_plan` did not.

Human_Race subtune 5 voice 1 is the case: `D3 45` plays an 18-row pattern
four times, 36 calls each, a shift of 4 in the counter's period of 8. The
original attacks the pattern's octave note as a 4-frame D-2/D-3/D-2/D-3
alternation on every second play and as a 2-frame one on the others, and the
converter sounded the first play's spelling four times. Frames of voice 1's
frequency column differing between the presets pack and the same song with
`pulse_phase` forced (whose pattern copies unroll the repeat and so spelled
it right), siddump -t180, subtune 5, lag-free (same packer both sides):

    before   473 frames (4-frame runs: 204 against the original's 109)
    after      0 frames (4-frame runs: 109)

Corpus byte-hash under presets, 95 files (89 converted, 6 refused): Human_Race
and Chimera move, nothing else. Chimera's voice 1 changes 16 frames in 180 s
(first at frame 5695); of the ten sampled against the original at its lag
of 6, nine now agree with it that disagreed before (the tenth, 5912, sounds
the octave in both, at a different pitch). Fidelity A/B -t 180 --presets
--sound: Human_Race moves aud/loud under the printed precision; Chimera
tie_agreement .7403 -> .7420 (ours-only ties 454 -> 440), tie_ratio .8553 ->
.8536 (a count ratio, further from 1 by 12 ties).
"""
import json
import pathlib
import subprocess
import sys
from types import SimpleNamespace

import pytest

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[1]))

import fidelity                                              # noqa: E402
import songview                                              # noqa: E402
from corpus import CORPUS, needs_corpus                      # noqa: E402
from h2g.convert import convert                              # noqa: E402
from h2g.goatwriter import (apply_tempo_duty_edits,          # noqa: E402
                            fixed_arp_phase_split_plan, SongSpeeds)

REPO_ROOT = pathlib.Path(__file__).resolve().parents[2]

needs_siddump = pytest.mark.skipif(
    not pathlib.Path(fidelity.SIDDUMP).exists(),
    reason="no siddump on this machine (tools/siddump-rt, see its README)")
needs_gt2reloc = pytest.mark.skipif(
    not pathlib.Path(fidelity.GT2RELOC).exists(),
    reason="no gt2reloc on this machine")


def _fake(monkeypatch, tracks, frames=3):
    """`test_arp_unrolled_laps._fake`: one subtune, parity-mask arp (period
    2), rows of `frames` calls, one arp record (GT 1). Pattern 0: three
    notes on instrument 1; pattern 1: a note on instrument 5 (no arp
    record); pattern 2: a rest."""
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


def test_the_plays_of_a_repeat_each_get_their_own_spelling(monkeypatch):
    """`D1 0` plays pattern 0 twice: 9 calls a play, so the second starts one
    residue on in a period of 2 and wants the other octave on every note.
    The one-spelling plan renamed both plays for the first's residues."""
    tracks, patterns, (sid, det) = _fake(
        monkeypatch, [[0xD1, 0], [2], [2]])
    split = fixed_arp_phase_split_plan(sid, det, tracks, patterns, True, 0,
                                       1, 2)
    assert split is not None
    assert split.clones == [(1, 2, 1)]
    # The repeat is gone: one entry per play, the second a copy.
    assert split.tracks[0] == [0, 3]
    assert split.tracks[1:] == [[2], [2]]
    out = apply_tempo_duty_edits(split.patterns, split)
    assert [out[0][1], out[0][5], out[0][9]] == [1, 2, 1]
    assert [out[3][1], out[3][5], out[3][9]] == [2, 1, 2]


def test_a_repeat_whose_plays_agree_stays_a_repeat(monkeypatch):
    """Rows of 2 calls: 6 a play, a whole number of periods, so every play
    attacks on the same residues and nothing is written out."""
    tracks, patterns, (sid, det) = _fake(
        monkeypatch, [[0xD1, 0], [2], [2]], frames=2)
    split = fixed_arp_phase_split_plan(sid, det, tracks, patterns, True, 0,
                                       1, 2)
    assert split is None or split.tracks[0] == [0xD1, 0]


def test_a_repeat_of_a_pattern_without_arp_notes_stays_a_repeat(monkeypatch):
    """Pattern 1 names no arp record: its plays' residues differ and nothing
    is renamed, so nothing is unrolled (Zoids moved bytes for that)."""
    tracks, patterns, (sid, det) = _fake(
        monkeypatch, [[0xD1, 1], [2], [2]])
    split = fixed_arp_phase_split_plan(sid, det, tracks, patterns, True, 0,
                                       1, 2)
    assert split is None or split.tracks[0] == [0xD1, 1]


# --- the corpus --------------------------------------------------------------

def _presets() -> dict:
    return json.loads((REPO_ROOT / "presets.json").read_text(encoding="utf-8"))


def _convert(name, **over):
    kw = fidelity._preset_opts(_presets(), name)
    kw.update(over)
    return convert(str(CORPUS / name), log=lambda x: None, **kw)


@needs_corpus
def test_human_race_subtune_5_voice_1_has_no_repeat_over_the_arp_pattern():
    s = songview.parse_sng(_convert("Human_Race.sid"))
    track = s.tracks[(5 - 1) * 3 + 1]
    # Entries outside 0xD0-0xDF are patterns; the old orderlist read
    # `... D3 45 D3 46 D3 45 ...`.
    assert not [b for b in track[:40] if 0xD0 <= b < 0xE0]


def _voice1_freq(sid_path, sub, seconds):
    out = subprocess.run(
        [fidelity.SIDDUMP, str(sid_path), f"-a{sub - 1}", f"-t{seconds}"],
        capture_output=True, text=True).stdout
    cur, rows = None, []
    for line in out.splitlines():
        if not (line.startswith("|") and line[2:7].strip().isdigit()):
            continue
        f = line.split("|")[3].split()
        if f and f[0] != "....":
            cur = f[0]
        rows.append(cur)
    return rows


@needs_corpus
@needs_siddump
@needs_gt2reloc
def test_human_race_presets_pack_agrees_with_the_pulse_phase_pack(tmp_path):
    """Forced `pulse_phase` copies the patterns (so the repeat is unrolled
    there), the presets build used to keep it: 473 frames of voice 1's
    frequency differed at -t180 in subtune 5."""
    packs = {}
    for mode, over in (("presets", {}), ("forced", {"pulse_phase": True})):
        wd = tmp_path / mode
        wd.mkdir()
        packs[mode] = pathlib.Path(
            fidelity.pack_sid(_convert("Human_Race.sid", **over), wd,
                              multiplier=1))
    a = _voice1_freq(packs["presets"], 5, 60)
    b = _voice1_freq(packs["forced"], 5, 60)
    assert len(a) == len(b) == 3000
    assert [i for i in range(3000) if a[i] != b[i]] == []
