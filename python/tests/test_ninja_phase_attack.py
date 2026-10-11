"""Ninja under forced `pulse_phase`: why 176 of 196 commanded phases read wrong
at the packed attack (task ninja-phase-attack-after-set-row).

THE READING WAS WRONG, NOT THE OUTPUT. `test_triangle_lockstep._reach`'s rule
(RETRACTED for a file whose finished firstwave is a real waveform): "the
packed width at the attack is the planned (w, d) plus k table steps", pairing
a finished note with the packed attack of the SAME NAME. Ninja carries
`--no-test-restart` (its preset), so every instrument's firstwave is the
record's own waveform and the packed player's first call on a note
(player.s `jmp mt_loadregswaveonly`, the note-init path; docs/OPTIONS.md
§ `--no-test-restart`) writes the gate, the waveform and AD/SR and RETURNS.
The wavetable entry 0 (frequency) and the pulse table (the set entry the
note's CMD_SETPULSEPTR points at) run on the NEXT call:

    frame T    wf 41  adsr 0B00  frq <PREVIOUS note>    <- siddump's ATTACK
    frame T+1  pul A40            frq <this note>

Two things followed from reading at T:

* the width at T is the PREVIOUS note's last width (stale), never the planned
  one -- the "2-4 steps along" of docs § 7.qqqqqqq was that, not a lag;
* siddump names the attack from the frequency it sees at T, which is the
  previous note's, so the same-name pairing aligned every finished note with
  the NEXT note's attack (`_NAME_SHIFT`).

Read at T + 1 with the name taken from the next attack, Ninja's output is exact
on every phase that has a command: 66/93, 28/28 and 102/102. The 27 that do
not are all record 13, which the full pulse table dropped ("*** PULSE TABLE
FULL UNDER --pulse-phase -- 1 INSTRUMENT(S) LOSE THEIR PHASE ENTRIES ***"): a
capacity loss, a different task (pulse-phase-capacity-in-subtune-order).

The A/B that fixes the cause: with `no_test_restart` off (firstwave `$09`, test
bit + gate, no real waveform on frame 0) siddump's attack is the wavetable's
first entry, on T, together with the frequency and the pulse; the SAME
unshifted reading at T then reaches the same 196. There is no converter fix:
the packed player has no way to write the pulse on a note's first call (tick-0
effects set the pulse POINTER, `mt_tick0_9`, never the register), so a file
that wants a real waveform on frame 0 gets its pulse a frame behind the gate,
as it gets its pitch. No shipped preset carries both flags (checked below).

MEASURED at 0d0f6ec, presets with `pulse_phase` forced, 180 s, -S1, group 0
traced as subtune 0 (reached / paired planned notes with a command):
    --no-test-restart, read at T, same-name pairing   11/93   9/28    0/102
    --no-test-restart, read at T, name shifted         9/93   0/28    9/102
    --no-test-restart, read at T+1, same-name pairing  0/93   0/28    0/102
    --no-test-restart, read at T+1, name shifted      66/93  28/28  102/102
    test-bit first frame, read at T, same-name        66/93  28/28  102/102
"""
from __future__ import annotations

import difflib
import functools
import shutil
import sys
import tempfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from test_pulse_phase import _corpus_and_presets  # noqa: E402

_NAME = "Ninja.sid"
_SECONDS = 180
_NOTE_NAMES = ["C-", "C#", "D-", "D#", "E-", "F-", "F#", "G-", "G#", "A-",
               "A#", "B-"]


@functools.lru_cache(maxsize=None)
def _packed_run(no_test_restart: bool):
    """Convert Ninja (presets, `pulse_phase` forced, `no_test_restart` as
    given), pack it, trace it, and keep what the readings need."""
    import fidelity as F
    from h2g import convert as C
    from h2g import patterns as P
    from songview import parse_sng
    corpus, doc = _corpus_and_presets()
    if not Path(F.SIDDUMP).exists() or not Path(F.GT2RELOC).exists():
        import pytest
        pytest.skip("siddump or gt2reloc not available here")
    kwargs = F._preset_opts(doc, _NAME)
    kwargs["pulse_phase"] = True
    kwargs["no_test_restart"] = no_test_restart
    mult = doc["songs"][_NAME].get("multiplier", 1)
    cap: dict = {}
    real_walk, real_table = C.collect_pulse_phases, C.build_pulse_phase_table

    def walk(pats, tracks, *a, **kw):
        r = real_walk(pats, tracks, *a, **kw)
        if "plan" not in cap:
            cap.update(pats=[list(p) for p in pats],
                       tracks=[list(t) for t in tracks], plan=r)
        return r

    def table(*a, **kw):
        r = real_table(*a, **kw)
        cap.setdefault("table", r)
        return r
    log: list = []
    C.collect_pulse_phases, C.build_pulse_phase_table = walk, table
    try:
        sng = C.convert(str(corpus / _NAME), log=log.append, **kwargs)
    finally:
        C.collect_pulse_phases, C.build_pulse_phase_table = real_walk, real_table
    assert cap.get("plan") and cap.get("table"), "no plan shipped"
    song = parse_sng(sng)
    wd = Path(tempfile.mkdtemp(prefix="ninja_attack_"))
    try:
        packed = F.pack_sid(sng, wd, multiplier=mult)
        assert packed is not None, "gt2reloc wrote no .sid"
        trace = F.run_siddump(packed, _SECONDS, 0, F.SIDDUMP, calls=mult)
    finally:
        shutil.rmtree(wd, ignore_errors=True)
    return dict(cap=cap, song=song, trace=trace, log=log, P=P, F=F, mult=mult)


def _reading(run: dict, lag: int, shift: int):
    """{voice: (reached, paired)} and the instruments of the paired planned
    notes that carry no command, for a pulse read `lag` frames after the
    attack and an attack named by the one `shift` places later."""
    P, F, cap, song = run["P"], run["F"], run["cap"], run["song"]
    entries, _, index = cap["table"]
    planned = {(ti, pos, r): ph for ti, pos, rows in cap["plan"][1]
               for r, ph in rows.items()}

    def nm(note: int) -> str:
        n = note - P.GT_FIRSTNOTE
        return f"{_NOTE_NAMES[n % 12]}{n // 12}"

    def walk_notes(ti: int) -> list:
        out, live = [], 0
        for pos, b in enumerate(cap["tracks"][ti]):
            if b == P.GT_ORDER_RESTART:
                break
            if b >= P.MAX_PATTERNS or b >= len(cap["pats"]):
                continue
            pat = cap["pats"][b]
            for r, kind, instr in P._phase_note_rows(pat, live, {}):
                if instr:
                    live = instr
                if kind == "note" and pat[4 * r + 2] != P.CMD_TONEPORTA:
                    out.append((nm(pat[4 * r]), planned.get((ti, pos, r))))
        return out

    def final_notes(ti: int) -> list:
        track, out, i = song.tracks[ti], [], 0
        while i < len(track) and track[i] != P.GT_ORDER_RESTART:
            b, plays = track[i], 1
            if P.GT_REPEAT <= b < P.GT_REPEAT + 16 and i + 1 < len(track):
                plays, b = b - P.GT_REPEAT + 1, track[i + 1]
                i += 1
            i += 1
            if b >= P.MAX_PATTERNS or b >= len(song.patterns):
                continue
            pat = song.patterns[b]
            for _ in range(plays):
                for r in range(len(pat) // 4):
                    note = pat[4 * r]
                    if note == P.GT_END_PATTERN:
                        break
                    if (P.GT_FIRSTNOTE <= note <= P.GT_LASTNOTE
                            and pat[4 * r + 2] != P.CMD_TONEPORTA):
                        out.append((nm(note), pat[4 * r + 3]
                                    if pat[4 * r + 2] == P.CMD_SETPULSEPTR
                                    else None))
        return out

    def pair(a: list, b: list) -> dict:
        sm = difflib.SequenceMatcher(None, [x[0] for x in a],
                                     [x[0] for x in b], autojunk=False)
        return {m.a + k: m.b + k for m in sm.get_matching_blocks()
                if m.size >= 8 for k in range(m.size)}

    nf = _SECONDS * 50
    out, uncommanded = {}, set()
    for v in range(3):
        wn = walk_notes(v)
        if not any(ph for _, ph in wn):
            continue
        fn = final_notes(v)
        tr = run["trace"][v]
        t = F.register_timeline(tr.pulse_events, nf)
        att = [(tr.attacks[min(k + shift, len(tr.attacks) - 1)],
                t[min(f + lag, nf - 1)])
               for k, f in enumerate(tr.attack_frames) if f < nf]
        w2f, f2a = pair(wn, fn), pair(fn, att)
        ok = n = 0
        for i, (_, ph) in enumerate(wn):
            if not ph or w2f.get(i) not in f2a:
                continue
            n += 1
            instr, (w, d) = ph
            at = index.get((instr, w, d))
            if at is None or fn[w2f[i]][1] != at:
                uncommanded.add(instr)
                continue
            spd = entries[at][1] if entries[at][0] < 0x80 else 0
            spd = spd if spd < 0x80 else 0x100 - spd
            got = att[f2a[w2f[i]]][1] >> 4
            ok += any(((w + j * spd * d) & 0xFFF) >> 4 == got
                      for j in range(run["mult"] + 1))
        out[v] = (ok, n)
    return out, uncommanded


_FULL = {0: (66, 93), 1: (28, 28), 2: (102, 102)}


def test_no_shipped_preset_carries_both_flags():
    """The lag is a property of `no_test_restart` + `pulse_phase` together, and
    only a forced flag brings them together: no `presets.json` song has both."""
    _, doc = _corpus_and_presets()
    both = [n for n, o in doc["songs"].items()
            if o.get("pulse_phase") and o.get("no_test_restart")]
    assert both == []
    assert doc["songs"][_NAME].get("no_test_restart") is True
    assert not doc["songs"][_NAME].get("pulse_phase")


def test_ninjas_firstwave_is_the_real_waveform_and_the_testbit_without_the_flag():
    """The premise: with the preset every instrument's firstwave is a real
    waveform (>= $10, written on the note's first call); without
    `no_test_restart` it is the test bit `$09`."""
    on = [i.firstwave for i in _packed_run(True)["song"].instruments]
    off = [i.firstwave for i in _packed_run(False)["song"].instruments]
    assert on and all(fw >= 0x10 for fw in on), on
    assert 0x09 in off and not any(fw >= 0x10 for fw in off), off


def test_the_pulse_set_lands_the_call_after_the_gate_and_every_command_is_exact():
    """Read where the player puts it: T + 1, naming the attack from the next
    one. Every planned note that has a command shows its planned width."""
    got, _ = _reading(_packed_run(True), lag=1, shift=1)
    assert got == _FULL, got


def test_reading_at_the_gate_frame_misreads_the_same_output():
    """RETRACTED reading (`_reach`'s rule on a real-firstwave file): the width
    at the attack frame, the attack paired by name. Pinned so the number
    cannot be rediscovered as a defect: 20 of 223 reached, on bytes that are
    exact."""
    run = _packed_run(True)
    at_gate, _ = _reading(run, lag=0, shift=0)
    assert at_gate == {0: (11, 93), 1: (9, 28), 2: (0, 102)}, at_gate
    # Each half of the misreading alone is as bad: the stale width at T with
    # the name shifted, and the right frame with the name unshifted.
    assert _reading(run, lag=0, shift=1)[0] == {0: (9, 93), 1: (0, 28), 2: (9, 102)}
    assert _reading(run, lag=1, shift=0)[0] == {0: (0, 93), 1: (0, 28), 2: (0, 102)}


def test_with_the_testbit_first_frame_the_unshifted_gate_reading_is_exact():
    """The A/B that names the cause: `no_test_restart` off puts the attack on
    the wavetable's first entry, the frame the frequency and the pulse are
    written, and the old reading then reaches the same 196."""
    got, _ = _reading(_packed_run(False), lag=0, shift=0)
    assert got == _FULL, got


def test_the_uncommanded_phases_are_record_13_the_full_table_dropped():
    """93 - 66 = 27 paired planned notes carry no command, and they are one
    record's: the pulse table was full and record 13 lost its entries."""
    run = _packed_run(True)
    _, uncommanded = _reading(run, lag=1, shift=1)
    assert uncommanded == {13}, uncommanded
    assert any("PULSE TABLE FULL UNDER --pulse-phase" in m for m in run["log"])
