"""Why `gate_off_firstwave_instruments` lowers `gate` on some multispeed files
and raises it on others: the call phase of the note-init call, not the
instrument.

Forced on every instrument at -t 180 under presets (39b5de2, v0.5.516) the
option moves 77 files and lowers `gate` on 16 (ACE_II, Chain_Reaction,
Deep_Strike, Food_Feud, Go_Go_Dash, Kings_of_the_Beach_intro, Lion_Heart,
Mr_Meaner, Off_the_Cuff, Rock_Tells_the_Tale, Saboteur_II,
Samantha_Fox_Strip_Poker, Spellbound, Thundercats, W_A_R, Zoolook). All 16
pack above -S1. Named one instrument at a time, each of the 181 instruments
that sound in the window lowers `gate` and none raises it (the other 72 move
no column), and the singletons' extra gate-off frames add up exactly to the
forced arm's on every file. So no subset of instruments keeps `gate`.

The mechanism, in two halves:

1. **Which notes the option can change at all.** siddump samples the
   registers once, after the frame's last call (siddump.c:383-408). GT's
   note-init call writes `$D404` alone, the firstwave (`player.s`
   mt_newnoteinit), and call 1 writes the waveform. At -S m, an init call
   that is not the frame's last call is overwritten inside its own frame, so
   the firstwave byte reaches the trace only when the init call has phase
   m-1. Food_Feud at 60 s: 771 init calls, phases 256/259/256, and the 256
   at phase 2 are exactly the frames that read `$09`. Those frames, and no
   others, are what the option changes in the trace.

2. **Which way it goes.** It depends on where that last call lies against
   the ORIGINAL's onset frame (harness-aligned by `startup_lag`). Measured
   as delta = init call - m * (orig onset frame + lag): on the 16 files
   the window of deltas starts at or after 0 (Food_Feud {0,1,2}), so the
   phase-(m-1) init lies INSIDE the original's onset frame. There the
   original already reads gate ON with its waveform, our call 1 falls in the
   next frame, and our onset is one frame late. `$09`'s gate bit happened
   to match the original's gate there; the gate-off firstwave clears it,
   and `gate` charges a frame. Every one of the 1158 frames Food_Feud
   changes is such a frame. On Thrust, Proteus and Warhawk (-S3/-S7) the
   window is {-1, ...}, the visible init lies in the frame BEFORE the
   original's onset, the original's gate is still off there, and the same
   byte is a gain. On -S1 every init is visible and the delta is -1
   (5_Title_Tunes).

So the loss marks notes that are already a frame late in the frame trace.
The firstwave does not make them late; `$09` was hiding it from `gate`
(`onset_frame_agreement` cannot see it either: it compares each side's shape
from its own attack). The lever is the converted song's call phase, not the
firstwave byte.

Measured in C:/t/gate-off-firstwave-gate-loss/ (probe.py, attrib.py,
frames.py, edges2.py, phase.py, delta.py). This test is the same
measurement on Go_Go_Dash (loss) and Thrust (gain), shortened to 60 s.

**The lever was pulled for the JMP-form gate
(`call_phase.jmp_gate`).** Twelve of the sixteen files above now start on the
phase that puts their onsets on the original's frames, and Food_Feud (window
{0, 1, 2} above, 1158 changed frames at 60 s) moved to the gain class: window
{-1, 0, 1}, the original's gate off on all 256 frames the option changes, as
Thrust. So did Chain_Reaction (window {-1, 0, 1}, 223 frames).

**Fourteen of the sixteen are phased now** (multispeed-call-phase-one-call-
earlier): Go_Go_Dash (the JMP form with a prescaler block above its gate,
`call_phase._prescaled_new_song_test`; its rows ARE exact, 15 calls at -S4 --
the earlier "rows are not exact" was wrong) moved from window {1, 3} to
{0, 2}, and Spellbound (a zero-page entry gate, `call_phase.zp_entry_gate`)
from {1..5} to {-1..3}. Two keep the loss class. Lion_Heart's default row is
already exact on every row that carries a note (window {0, 1, 2}, 9 of 575
inits on the visible phase), and stands for it here; Samantha_Fox reads no
first fetch of the speed counter, so no clock.
"""
import json
import pathlib
import sys

import pytest

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[1]))

import fidelity                                              # noqa: E402
from corpus import CORPUS, needs_corpus                      # noqa: E402

REPO_ROOT = pathlib.Path(__file__).resolve().parents[2]
SECONDS = 60
EVERY = tuple(range(1, 64))

needs_siddump = pytest.mark.skipif(
    not pathlib.Path(fidelity.SIDDUMP).exists(),
    reason="no siddump on this machine (tools/siddump-rt, see its README)")
needs_gt2reloc = pytest.mark.skipif(
    not pathlib.Path(fidelity.GT2RELOC).exists(),
    reason="no gt2reloc on this machine")


def _arms(name: str, tmp_path: pathlib.Path):
    from h2g.convert import convert
    from h2g.goatwriter import call_phase
    doc = json.loads((REPO_ROOT / "presets.json").read_text(encoding="utf-8"))
    mult = fidelity._preset_multiplier(doc, name)
    out = {}
    for arm, instrs in (("off", ()), ("gate_off", EVERY)):
        opts = fidelity._preset_opts(doc, name)
        opts["gate_off_firstwave_instruments"] = instrs
        # A song the startup record phases takes this byte on every
        # instrument by itself (`convert`); the 'off' arm is the song without
        # it, so the seam is turned off for the build.
        saved = call_phase.GATE_OFF_FIRSTWAVE
        call_phase.GATE_OFF_FIRSTWAVE = arm == "gate_off"
        try:
            blob = convert(str(CORPUS / name), log=lambda m: None, **opts)
        finally:
            call_phase.GATE_OFF_FIRSTWAVE = saved
        sng, _ = fidelity.legalise_restarts(blob)
        work = tmp_path / arm
        work.mkdir()
        packed = fidelity.pack_sid(sng, work, multiplier=mult)
        assert packed is not None and packed.exists(), (name, arm)
        out[arm] = packed
    return mult, out


def _wf(trace, v: int, n: int) -> list[int]:
    return fidelity.register_timeline(trace[v].wf_events, n)


def _changed_and_visible(name: str, tmp_path: pathlib.Path):
    mult, packed = _arms(name, tmp_path)
    assert mult > 1, name
    nfr, ncalls = SECONDS * 50, SECONDS * 50 * mult
    frames = {a: fidelity.run_siddump(p, SECONDS, 0, calls=mult)
              for a, p in packed.items()}
    calls = fidelity.run_siddump(packed["off"], SECONDS * mult, 0, calls=1)
    per_voice = []
    for v in range(3):
        t_off, t_on = _wf(frames["off"], v, nfr), _wf(frames["gate_off"], v, nfr)
        tc = _wf(calls, v, ncalls)
        inits = [c for c in range(1, ncalls)
                 if tc[c] == fidelity_testbit() and tc[c - 1] != tc[c]]
        changed = {f for f in range(nfr) if t_off[f] != t_on[f]}
        visible = {c // mult for c in inits if c % mult == mult - 1}
        per_voice.append({"inits": inits, "changed": changed,
                          "visible": visible, "t_off": t_off, "t_on": t_on})
    return mult, frames, per_voice


def fidelity_testbit() -> int:
    from h2g.goatwriter.constants import FIRSTWAVE_TESTBIT
    return FIRSTWAVE_TESTBIT


@needs_corpus
@needs_siddump
@needs_gt2reloc
@pytest.mark.parametrize("name", ["Food_Feud.sid", "Thrust.sid"])
def test_the_option_changes_only_frames_whose_last_call_is_a_note_init(
        name, tmp_path):
    mult, _, voices = _changed_and_visible(name, tmp_path)
    for v, d in enumerate(voices):
        where = (name, v, len(d["inits"]), len(d["changed"]), len(d["visible"]))
        # Inits land on every phase; only the last one reaches the trace.
        assert len({c % mult for c in d["inits"]}) == mult, where
        assert d["visible"], where
        assert d["changed"] == d["visible"], where
        for f in d["changed"]:
            # $09 on our side, the record's waveform with the gate clear on
            # the option's -- one byte, one frame per visible init.
            assert d["t_off"][f] == fidelity_testbit(), (where, f)
            assert d["t_on"][f] >= 0x10 and not d["t_on"][f] & 1, (where, f)
    assert sum(len(d["visible"]) for d in voices) > 20, name


@needs_corpus
@needs_siddump
@needs_gt2reloc
@pytest.mark.parametrize("name, orig_gate_on, window", [
    ("Lion_Heart.sid", True, {0, 1, 2}),
    ("Food_Feud.sid", False, {-1, 0, 1}),
    ("Thrust.sid", False, {-1, 0, 1}),
])
def test_the_sign_is_where_the_visible_init_lies_against_the_original_onset(
        name, orig_gate_on, window, tmp_path):
    mult, frames, voices = _changed_and_visible(name, tmp_path)
    nfr = SECONDS * 50
    orig = fidelity.run_siddump(CORPUS / name, SECONDS, 0)
    lag, raw = fidelity.startup_lag(orig, frames["off"])
    assert lag == raw, (lag, raw)
    deltas = set()
    for v, d in enumerate(voices):
        ta = fidelity.register_timeline(orig[v].wf_events, nfr)
        onsets = [g for g in range(1, nfr) if ta[g] & 1 and ta[g] >= 0x10
                  and (not ta[g - 1] & 1 or ta[g - 1] < 0x10)]
        for g in onsets:
            target = mult * (g + lag)
            near = min(d["inits"], key=lambda c: abs(c - target), default=None)
            if near is not None and abs(near - target) <= 2 * mult:
                deltas.add(near - target)
        # Every frame the option changes, read on the original (our frame f
        # is the original's f - lag): gate on with a waveform on the loss
        # file, gate off on the gain file -- with no exception either way.
        for f in d["changed"]:
            x = ta[f - lag]
            assert bool(x & 1) == orig_gate_on, (name, v, f, hex(x))
            if orig_gate_on:
                assert x >= 0x10, (name, v, f, hex(x))
    assert deltas == window, (name, sorted(deltas))
