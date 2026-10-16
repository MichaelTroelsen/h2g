"""A two-stage drum under a real firstwave: its first step cannot carry the note.

Auf_Wiedersehen_Monty's voice-3 drums (GT 1 and GT 4 under its preset) open,
in the original, on `[X][K]..[X]`: X is the record's `41` at the NOTE's pitch,
K one or two frames of `81` noise at an absolute pitch (`G-6`), then X again.
Under `real_firstwave_instruments` the table is `[K]..[X]` with no lead entry.
Task `wave-program-first-step-skips-note` (opened by `stale-init-frame-attack-
naming`) read frames 1606-1609 of the trace -- `D-3 stale, G-6 $81, E-2 at
1609` -- as the program delaying X by 2-3 frames. Measured at 7b18636, it does
not:

- K lands one frame after the attack and the closing X lands exactly as many
  frames after K as the original's (one K -> X on the next frame, two K -> X
  after a gap), in the real arm and in the gate-off arm alike;
- the 1606 event is GT 4, `[X][K][K][X]` (its ADSR `0AF9` is in the original
  at 1550 as well), so it is compared to the original's three-frame shape and
  not to GT 1's two-frame one;
- what differs is only the attack frame's PITCH. That frame is the note-init
  call, `player.s` `mt_newnoteinit` -> `jmp mt_loadregswaveonly` (or
  `mt_loadregs` under BUFFEREDWRITES): it writes `$D404`, and at most the
  register copies `mt_chnfreqlo/hi`, which only a wavetable or effect call
  updates. So the frequency on that frame is the previous note's, whatever the
  table holds -- 27 of the 46 Monty two-stage drum events name the previous pitch
  (the other 19 coincide: a repeated drum note), against 0 in the original.

The only table change that puts X's pitch on the voice is a lead entry `X`, and
that is the gate-off arm's layout (`gate_off_firstwave_instruments`): the init
call becomes a gate-clear frame, X and K and the closing X all land on the
original's offsets from the gate rise, and the stale count is 0. In the real
arm a lead entry would only push K one frame late behind the same stale frame.
So the arm is unable; the repair is the option swap, a per-song preset
decision (`firstwave-preset-decision`), not a layout change.

If `test_the_attack_frame_names_the_previous_pitch` starts failing, the real
arm has learned to write the pitch on its init call: update this file.

Own file, per the optimistic-merge rule.
"""
import json
import pathlib
import re
import subprocess
import sys
import warnings
from collections import Counter

import pytest

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[1]))

import fidelity                                              # noqa: E402
import songview                                              # noqa: E402
from corpus import CORPUS, needs_corpus                      # noqa: E402
from h2g.convert import convert                              # noqa: E402

REPO_ROOT = pathlib.Path(__file__).resolve().parents[2]
PRESETS = REPO_ROOT / "presets.json"
NAME = "Auf_Wiedersehen_Monty.sid"
EVERY = tuple(range(1, 64))
SECONDS = 36                  # the drums of interest start at frame ~1550

needs_siddump = pytest.mark.skipif(
    not pathlib.Path(fidelity.SIDDUMP).exists(),
    reason="no siddump on this machine (tools/siddump-rt, see its README)")
needs_gt2reloc = pytest.mark.skipif(
    not pathlib.Path(fidelity.GT2RELOC).exists(),
    reason="no gt2reloc on this machine")


def _opts() -> dict:
    if not PRESETS.exists():
        pytest.skip("presets.json not generated")
    doc = json.loads(PRESETS.read_text(encoding="utf-8"))
    assert doc["songs"][NAME].get("multiplier", 1) == 1
    with warnings.catch_warnings():
        warnings.simplefilter("ignore")
        return fidelity._preset_opts(doc, NAME)


def _arm(name: str) -> dict:
    opts = _opts()
    if name == "real":
        assert opts["real_firstwave_instruments"], "the preset moved"
        return opts
    return dict(opts, real_firstwave_instruments=(), no_test_restart=False,
                gate_off_firstwave_instruments=EVERY)


def _sng(arm: str) -> bytes:
    return convert(str(CORPUS / NAME), log=lambda m: None, **_arm(arm))


def _wave_rows(blob: bytes, instrument) -> list[tuple[int, int]]:
    """The instrument's wavetable rows from its pointer to the `FF` stop."""
    song = songview.parse_sng(blob)
    table = song.tables["WTBL"]
    rows, at = [], instrument.wave_ptr - 1
    while table[at][0] != 0xFF:
        rows.append(table[at])
        at += 1
    return rows


def _two_stage_drums(blob: bytes) -> dict[int, tuple[int, list]]:
    """GT number -> (K count, rows) for every record whose program is the
    noise step(s) `81 CF` then the record's pulse `41 00`, with or without a
    lead `41 00` in front."""
    song = songview.parse_sng(blob)
    out = {}
    for ins in song.instruments:
        if not ins.wave_ptr:
            continue
        rows = _wave_rows(blob, ins)
        lead = len(rows) > 1 and rows[0] == (0x41, 0x00) and rows[1][0] == 0x81
        body = rows[1:] if lead else rows
        n = 0
        while n < len(body) and body[n] == (0x81, 0xCF):
            n += 1
        if n and body[n:] == [(0x41, 0x00)]:
            out[ins.number] = (n, rows)
    return out


@needs_corpus
def test_the_real_arm_has_no_lead_entry_and_the_gate_off_arm_has_one():
    real, off = _sng("real"), _sng("off")
    drums_real, drums_off = _two_stage_drums(real), _two_stage_drums(off)
    assert set(drums_real) == set(drums_off) and len(drums_real) >= 2
    song_real = songview.parse_sng(real)
    song_off = songview.parse_sng(off)
    checked = 0
    for gt, (n, rows) in drums_real.items():
        # real: [K]*n then X -- the init call is frame 0 (the original's X
        # frame), call k is frame k, X is call n + 1 = frame n + 1.
        assert rows == [(0x81, 0xCF)] * n + [(0x41, 0x00)], (gt, rows)
        # A legato tie clone (gatetimer bit $40) writes no firstwave at all.
        whole = not song_real.instruments[gt - 1].gatetimer & 0x40
        checked += whole
        if whole:
            assert song_real.instruments[gt - 1].firstwave == 0x41, gt
        n_off, rows_off = drums_off[gt]
        # gate-off: the init call is a gate-clear frame BEFORE frame 0 and
        # the lead entry X is call 1 = frame 0; K starts frame 1, closing X
        # is call n + 2 = frame n + 1. Same frames as the real arm's, which is
        # why both line up with the original after `startup_lag`.
        assert n_off == n, (gt, n, n_off)
        assert rows_off == [(0x41, 0x00)] + [(0x81, 0xCF)] * n + [(0x41, 0x00)]
        if whole:
            assert song_off.instruments[gt - 1].firstwave == 0x40, gt
    assert checked >= 2, checked


def _drum_events(text: str, voice: int) -> Counter:
    """(has an attack frame before K, frames from K to the closing X,
    attack names the closing pitch) for every `G-6` `81` K frame."""
    rows = {}
    for ln in text.splitlines():
        m = re.match(r"\|\s+(\d+) \| (.*)", ln)
        if m:
            rows[int(m.group(1))] = m.group(2).split("|")[voice].split()

    def note(cells):
        for x in cells:
            m = re.match(r"\(?([A-G][-#]\d)", x)
            if m:
                return m.group(1)
        return None

    out = Counter()
    for f in sorted(rows):
        r = rows[f]
        if not (len(r) >= 3 and "G-6" in " ".join(r[:3]) and "81" in r):
            continue
        attack = rows.get(f - 1, [])
        if "41" not in attack:
            continue                  # a plain sfx drum, not a two-stage one
        gap = next((g - f for g in range(f + 1, f + 5)
                    if "41" in rows.get(g, []) and note(rows[g])), None)
        if gap is None:
            continue
        same = note(attack) == note(rows[f + gap])
        out[(gap, "same" if same else "stale")] += 1
    return out


def _trace(sid: pathlib.Path) -> str:
    return subprocess.run(
        [fidelity.SIDDUMP, str(sid), "-a0", f"-t{SECONDS}"],
        capture_output=True, text=True, check=True).stdout


@pytest.fixture(scope="module")
def traces(tmp_path_factory):
    if not (pathlib.Path(fidelity.SIDDUMP).exists()
            and pathlib.Path(fidelity.GT2RELOC).exists()):
        pytest.skip("needs siddump and gt2reloc")
    out = {"orig": _trace(CORPUS / NAME)}
    for arm in ("real", "off"):
        sng, _ = fidelity.legalise_restarts(_sng(arm))
        work = tmp_path_factory.mktemp(arm)
        packed = fidelity.pack_sid(bytes(sng), work)
        assert packed is not None and packed.exists(), arm
        out[arm] = _trace(packed)
    return out


@needs_corpus
@needs_siddump
@needs_gt2reloc
def test_k_to_closing_x_spacing_matches_the_original_in_both_arms(traces):
    orig = _drum_events(traces["orig"], 2)
    assert {g for g, _ in orig} == {1, 2}, orig
    for arm in ("real", "off"):
        got = _drum_events(traces[arm], 2)
        assert {g for g, _ in got} == {1, 2}, (arm, got)
        for gap in (1, 2):
            want = sum(n for (g, _), n in orig.items() if g == gap)
            have = sum(n for (g, _), n in got.items() if g == gap)
            # the traces start their notes a few frames apart, so the last
            # event can fall outside the window on one side
            assert abs(want - have) <= 2, (arm, gap, want, have)


@needs_corpus
@needs_siddump
@needs_gt2reloc
def test_the_attack_frame_names_the_previous_pitch(traces):
    """The only difference between the arms: the original and the gate-off arm
    never name the drum after the previous note; the real arm does on every
    event whose previous pitch is not the drum's own (27 of 46 at 7b18636)."""
    stale = {arm: sum(n for (_, k), n in _drum_events(traces[arm], 2).items()
                      if k == "stale") for arm in ("orig", "real", "off")}
    assert stale["orig"] == 0 and stale["off"] == 0, stale
    assert stale["real"] >= 10, stale
