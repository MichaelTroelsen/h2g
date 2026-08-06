#!/usr/bin/env python3
"""Measure how closely a conversion plays like the .sid it came from.

Everything else in this repo checks *structure* -- that a .sng parses, that
patterns fit Goattracker's limits, that a fixture reproduces byte for byte.
None of that says the music survived. This does: it packs our .sng back to a
.sid with gt2reloc, traces both files with siddump, and compares what the two
players actually tell the SID chip to do.

    python fidelity.py <sid-or-dir> [-o ../FIDELITY.md]
    python fidelity.py --pair original.sid converted.sid

Three comparisons are possible; they answer different questions and are worth
running in this order (the reasoning is in SIDM2-FIDELITY-TESTER.md):

 1. **Note sequence** -- what this script does by default. Compares the order
    of note attacks with timing discarded, so it is immune to the tempo
    mismatch that currently makes every frame differ. Needs nothing but
    siddump, and it is the comparison that found the re-trigger defect.
 2. **Audio onsets** (`--audio`) -- SIDM2's audio_tightness_tool.py. Renders
    both to WAV, aligns onsets, reports timing and attack-shape divergence.
    Tolerates a constant offset, so it is meaningful before tempo is fixed.
 3. **Register frames** (`--register`) -- SIDM2's validate_sid_accuracy.py.
    The strictest measure and the eventual goal, but while our tempo differs
    it reports the offset rather than the fidelity, so it is off by default.

2 and 3 shell out to SIDM2 and inherit its dependencies; 1 is stdlib only.

What a "note attack" is, exactly
--------------------------------
siddump prints a bare note (`E-7 D8`) only when it has seen a gate rising
edge -- `siddump.c:376-380` sets `prevchn[c].note = -1` on keyoff->keyon, and
`:409` prints the bare form only when that flag is set. A note printed in
parentheses (`(F#1 92)`) is the same voice moving to another pitch *without*
re-triggering, and `(+ 0002)` is a slide. So bare notes are attacks and
nothing else is, which is the event a listener hears as a struck note.

Two numbers come out of that:

 * **retrigger ratio** -- our attacks over the original's. A tune that holds a
   note where we re-strike it eight times shows up here as 8x, and nowhere in
   any structural check.
 * **melody similarity** -- difflib ratio over the attack-note sequence with
   consecutive duplicates collapsed, which removes exactly the re-trigger
   noise and leaves the question "are these the same notes in the same
   order". Reported alongside the uncollapsed ratio.

Separately from note attacks, the **wave** metric compares the waveform
register ($D404) frame by frame: siddump's WF column, carried forward across
the frames it is not reprinted, reduced to its waveform-class nibble (see
wave_compare). It exists to measure the fabricated wavetable -- goatwriter
writes a noise-tick/arpeggio wavetable for every instrument whether or not
the source player had those semantics, and no attack-based metric can see
the difference between a pulse note and the same note opening on a frame of
noise.
"""
from __future__ import annotations

import argparse
import difflib
import json
import os
import re
import shutil
import subprocess
import sys
import tempfile
from dataclasses import dataclass, field
from pathlib import Path

from h2g import __version__
from h2g.convert import convert
from h2g.goatwriter import FORMAT_GTS5
from h2g.sidfile import find_freq_table, load_sid

# Defaults are the tools as they sit on this machine; every one is overridable
# so the harness is not pinned to one install.
SIDDUMP = os.environ.get(
    "H2G_SIDDUMP", r"C:\Users\mit\claude\c64server\SIDM2\tools\siddump.exe")
GT2RELOC = os.environ.get(
    "H2G_GT2RELOC", r"C:\Users\mit\Downloads\GoatTracker_2.77\win32\gt2reloc.exe")
SIDM2_ROOT = os.environ.get(
    "H2G_SIDM2", r"C:\Users\mit\claude\c64server\SIDM2")

# gt2reloc strcpy()s argv[1] into a 60-byte MAX_FILENAME buffer without
# reducing it to a basename, so it is run with short names and a short cwd.
WORKDIR = os.environ.get("H2G_FIDELITY_WORK", r"C:\t\h2gfid")

DEFAULT_SECONDS = 8


# --------------------------------------------------------------------------
# siddump output
# --------------------------------------------------------------------------
# One voice cell, after splitting a row on '|', is a 4-hex frequency (or
# '....') then a 9-character note field written by one of exactly four
# sprintf formats in siddump.c:409-429, then the 2-hex waveform register
# (or '..' when the register was not written this frame).
_ATTACK = re.compile(r" ([A-G][-#]\d) ([0-9A-F]{2})  ")
_TIE = re.compile(r"\(([A-G][-#]\d) ([0-9A-F]{2})\) ")
_SLIDE = re.compile(r"\(([+-]) ([0-9A-F]{4})\) ")
_WF = re.compile(r"[0-9A-F]{2}$")

# $D404 waveform-register bits. The upper nibble selects the waveform(s);
# the lower nibble is gate/sync/ring/test, none of which is a timbre.
WF_GATE = 0x01
WF_NOISE = 0x80


@dataclass
class Voice:
    attacks: list[str] = field(default_factory=list)   # note names, in order
    attack_frames: list[int] = field(default_factory=list)
    ties: int = 0
    slides: int = 0
    # (frame, value) for every frame siddump shows the waveform register
    # written. siddump prints a row only when something changed, so between
    # events the register holds its last value -- wave_timeline() expands
    # these into a per-frame view.
    wf_events: list[tuple[int, int]] = field(default_factory=list)

    @property
    def collapsed(self) -> list[str]:
        """Attack sequence with consecutive repeats merged.

        A held note that we re-strike appears here once, as it does in the
        original, so this isolates "the right notes in the right order" from
        "the right number of strikes".
        """
        out: list[str] = []
        for n in self.attacks:
            if not out or out[-1] != n:
                out.append(n)
        return out


def parse_dump(text: str) -> list[Voice]:
    """Three Voices out of siddump's table."""
    voices = [Voice(), Voice(), Voice()]
    for line in text.splitlines():
        if not line.startswith("|"):
            continue
        cells = line.split("|")
        if len(cells) < 6:
            continue
        try:
            frame = int(cells[1].strip())
        except ValueError:
            continue  # header/rule row
        for v, cell in enumerate(cells[2:5]):
            rest = cell[6:]  # past ' FREQ ' (or ' .... ')
            # The waveform register is the 2 characters after the 9-char
            # note field, in every one of the four note formats.
            if _WF.match(rest[9:11]):
                voices[v].wf_events.append((frame, int(rest[9:11], 16)))
            m = _ATTACK.match(rest)
            if m:
                voices[v].attacks.append(m.group(1))
                voices[v].attack_frames.append(frame)
                continue
            if _TIE.match(rest):
                voices[v].ties += 1
                continue
            if _SLIDE.match(rest):
                voices[v].slides += 1
    return voices


def wave_timeline(voice: Voice, nframes: int) -> list[int]:
    """The waveform register's value on every frame 0..nframes-1.

    siddump prints the register only on the frame it is written; on every
    other frame the chip keeps playing whatever was latched, so the value
    carries forward. Before the first write (siddump always prints frame 0 in
    full, so in practice never) the value is 0.
    """
    out: list[int] = []
    cur, idx, ev = 0, 0, voice.wf_events
    for f in range(nframes):
        while idx < len(ev) and ev[idx][0] <= f:
            cur = ev[idx][1]
            idx += 1
        out.append(cur)
    return out


# siddump's own middle C, the register value it names `C-4` unless -c says
# otherwise (siddump.c prints it as "Middle C frequency is $1168").
SIDDUMP_MIDDLE_C = 0x1168


def calibration(detune: float) -> int:
    """siddump -c value for a player whose table is `detune` semitones flat.

    Note names come out of a register value, so a file whose frequency table
    was computed for another clock is named in another key: the four NTSC
    tables in the corpus sit 0.65 semitones below the PAL ones, which siddump
    rounds to a whole semitone and reports as a tune playing the wrong notes.
    Recalibrating the *original's* dump to its own table puts both sides on one
    tuning, so what is left in the comparison is the conversion.
    """
    return round(SIDDUMP_MIDDLE_C * 2 ** (detune / 12))


def run_siddump(sid: Path, seconds: int, subtune: int,
                exe: str = SIDDUMP, calibrate: int = 0) -> list[Voice]:
    cmd = [exe, str(sid), f"-a{subtune}", f"-t{seconds}"]
    if calibrate:
        cmd.append(f"-c{calibrate:X}")
    proc = subprocess.run(cmd, capture_output=True, text=True, timeout=180,
                          stdin=subprocess.DEVNULL)
    return parse_dump(proc.stdout)


# --------------------------------------------------------------------------
# .sng -> .sid
# --------------------------------------------------------------------------
def legalise_restarts(blob: bytes) -> tuple[bytes, int]:
    """Rewrite out-of-range song restart positions to 0.

    tracks.py emits [$FF, $FD] for a version 0/1/2/3 `$FE` track byte, meaning
    "stop rather than loop". greloc.c:244 rejects any restart >= the track's
    length and writes no file at all, so a file carrying one cannot be packed
    -- see SNG2SID-FIDELITY.md. Patching it here keeps the harness usable
    whether or not the converter itself is changed, and reports how many it
    touched so the report can say which files were measured on patched bytes.
    """
    buf = bytearray(blob)
    pos = 4 + 32 * 3
    subtunes = buf[pos]
    pos += 1
    fixed = 0
    for _ in range(subtunes * 3):
        songlen = buf[pos]
        pos += 1
        end = pos + songlen + 1
        if buf[end - 1] >= songlen:
            buf[end - 1] = 0
            fixed += 1
        pos = end
    return bytes(buf), fixed


def song_lengths(blob: bytes) -> list[tuple[int, int, int]]:
    """greloc's `songlen` for each subtune's three voices, read from a .sng.

    gsong.c:1338-1349 counts orderlist bytes up to the first byte >= LOOPSONG,
    so a voice whose orderlist is only the marker `[$FF, restart]` has length
    **0**. The .sng stores `len(track) - 1` (goatwriter.build_sng), i.e. the
    orderlist including its `$FF` but not the restart operand, so greloc's
    length is the stored byte minus one.
    """
    pos = 4 + 32 * 3
    subtunes = blob[pos]
    pos += 1
    out: list[tuple[int, int, int]] = []
    for _ in range(subtunes):
        voices = []
        for _ in range(3):
            stored = blob[pos]
            pos += 1
            voices.append(stored - 1)
            pos += stored + 1
        out.append((voices[0], voices[1], voices[2]))
    return out


def greloc_export(lengths: list[tuple[int, int, int]]) -> dict:
    """Which of our subtunes gt2reloc will export, and as what.

    `greloc.c:200-255` counts `songs` = the subtunes whose three voices all
    have nonzero length. The writing loop at `:653` then runs `c < songs` over
    the **original** indices and re-tests validity, so the effect is *not* a
    compaction and nothing is renumbered:

      * a subtune with a zero-length voice keeps its index but is written with
        `songsize 0` (`:701-706`) -- an entry that exists and plays nothing;
      * every subtune whose index is >= `songs` is never written at all,
        valid or not. `NUMSONGS` is `songs` (`:1131`, `:1644`).

    Verified on Rasputin: 17 subtunes in, PSID reports 15 out; ours 0 and 1
    (each with an empty third voice) come back silent in place, and ours 15
    and 16 -- carrying 309 and 621 sounding rows -- do not come back at all.

    This matters to every number in this report: a comparison against a stub
    measures our converter against silence, and one against a shifted subtune
    would measure two different pieces of music. Only the first can happen.
    """
    valid = [all(v) for v in lengths]
    songs = sum(valid)
    return {
        "subtunes": len(lengths),
        "exported": songs,
        "stub": [i for i in range(min(songs, len(lengths))) if not valid[i]],
        "lost": [i for i in range(songs, len(lengths)) if valid[i]],
    }


def pack_sid(sng: bytes, workdir: Path, exe: str = GT2RELOC,
             multiplier: int = 1) -> Path | None:
    """Run gt2reloc, the standalone form of Goattracker's F9 packer.

    Returns the packed .sid, or None if gt2reloc refused. Its exit code is
    never the signal: fatal errors go to fopen("CON") and to screen routines
    that do nothing headless, so a refusal is exit 0 with no output and no
    file. The written file is the only thing worth testing.

    `multiplier` becomes gt2reloc's -S, which prepends a CIA stub reprogramming
    timer A so the play routine is called that many times per frame -- the only
    way Goattracker reaches a row rate faster than three calls. It changes the
    packed bytes (speed field $FFFFFFFF, ten bytes at playeradr-10) and it is
    what makes the tune play at its real rate on hardware.

    It does **not** change what this harness measures. siddump calls the play
    routine `seconds * 50` times whatever the PSID speed field says
    (siddump.c:309/325), so the trace is identical with and without -S --
    verified on Chain_Reaction: same melody, sequence, retrigger ratio and
    attack counts either way. It is passed anyway so the file the harness packs
    is the file that would ship; the measurement gap is a siddump limitation
    and is reported as such in the summary.

    Options must follow both filenames. gt2reloc reads argv[1] and argv[2]
    positionally, so a leading `-S2` is taken as the input filename and the run
    writes nothing -- silently, indistinguishable from any other refusal.
    """
    src, dst = workdir / "a.sng", workdir / "b.sid"
    dst.unlink(missing_ok=True)
    src.write_bytes(sng)
    args = [exe, "a.sng", "b.sid"]
    if multiplier > 1:
        args.append(f"-S{multiplier}")
    try:
        subprocess.run(args, cwd=str(workdir), timeout=120,
                       capture_output=True, stdin=subprocess.DEVNULL)
    except subprocess.TimeoutExpired:
        return None
    return dst if dst.exists() else None


# --------------------------------------------------------------------------
# comparison
# --------------------------------------------------------------------------
def _ratio(a: list[str], b: list[str]) -> float:
    if not a and not b:
        return 1.0
    if not a or not b:
        return 0.0
    return difflib.SequenceMatcher(None, a, b, autojunk=False).ratio()


def compare(orig: list[Voice], ours: list[Voice]) -> dict:
    """Per-voice and whole-file note-sequence metrics.

    The file-level similarities are weighted by the original's attack count so
    that a voice carrying the tune counts for more than one playing two notes,
    and a voice silent in both does not dilute the score.
    """
    per_voice = []
    for a, b in zip(orig, ours):
        per_voice.append({
            "orig_attacks": len(a.attacks),
            "our_attacks": len(b.attacks),
            "orig_notes": len(a.collapsed),
            "our_notes": len(b.collapsed),
            "sequence": _ratio(a.attacks, b.attacks),
            "melody": _ratio(a.collapsed, b.collapsed),
            "orig_pitches": sorted(set(a.attacks)),
            "our_pitches": sorted(set(b.attacks)),
        })

    weights = [max(v["orig_attacks"], 1) if (v["orig_attacks"] or v["our_attacks"])
               else 0 for v in per_voice]
    total_w = sum(weights) or 1

    def weighted(key: str) -> float:
        return sum(v[key] * w for v, w in zip(per_voice, weights)) / total_w

    oa = sum(v["orig_attacks"] for v in per_voice)
    ua = sum(v["our_attacks"] for v in per_voice)
    op = set().union(*(set(v["orig_pitches"]) for v in per_voice)) if per_voice else set()
    up = set().union(*(set(v["our_pitches"]) for v in per_voice)) if per_voice else set()
    return {
        "orig_attacks": oa,
        "our_attacks": ua,
        "retrigger_ratio": (ua / oa) if oa else None,
        "melody": weighted("melody"),
        "sequence": weighted("sequence"),
        "pitch_jaccard": (len(op & up) / len(op | up)) if (op | up) else 1.0,
        # Frames on which the player moved a voice's frequency without
        # retriggering it -- vibrato, portamento, any pitch bend. None of the
        # metrics above can see them: an attack-based comparison is blind to
        # everything that happens *within* a note, so a change that only adds
        # or removes pitch movement leaves melody, sequence and retrigger
        # identical. Reported so that class of work is measurable at all.
        "orig_slides": sum(v.slides for v in orig),
        "our_slides": sum(v.slides for v in ours),
        "voices": per_voice,
    }


def wave_compare(orig: list[Voice], ours: list[Voice],
                 nframes: int | None = None) -> dict:
    """Per-frame waveform-CLASS agreement, and noise-frame counts per side.

    The class of a frame is the waveform-select nibble of $D404 -- `wf & $F0`
    -- so triangle ($1x), sawtooth ($2x), pulse ($4x) and noise ($8x) are the
    four pure classes, a combined waveform ($5x tri+pulse, ...) is its own
    class distinct from either component, and $0x (no waveform selected) is
    "silent". The gate bit and the other control bits (sync, ring, test) are
    deliberately ignored: gating is what the attack metrics already measure,
    and a gate-off voice keeps its waveform latched, so folding the gate in
    would double-count every note length disagreement as a timbre one.

    Frames where *both* sides are class 0 are left out of the denominator,
    mirroring how compare() refuses to let a voice silent in both inflate the
    score; a frame where one side selects a waveform and the other selects
    none counts as a disagreement.

    Noise frames are counted on bit 7 alone (any class containing noise),
    over **all** frames per side, because the question they answer --
    "did we invent drum ticks the player never had?" -- is one-sided.

    `nframes` should be the full trace length (siddump plays seconds*50
    frames regardless of the PSID speed field); when None it is derived from
    the last waveform write seen on either side, which is exact for
    synthetic fixtures and merely truncates a constant tail otherwise.
    """
    if nframes is None:
        last = max((f for v in orig + ours for f, _ in v.wf_events), default=-1)
        nframes = last + 1
    agree = total = o_noise = u_noise = 0
    per_voice = []
    for a, b in zip(orig, ours):
        ta, tb = wave_timeline(a, nframes), wave_timeline(b, nframes)
        va = vt = vo_n = vu_n = 0
        for x, y in zip(ta, tb):
            if x & WF_NOISE:
                vo_n += 1
            if y & WF_NOISE:
                vu_n += 1
            cx, cy = x & 0xF0, y & 0xF0
            if cx == 0 and cy == 0:
                continue
            vt += 1
            if cx == cy:
                va += 1
        per_voice.append({
            "wave": (va / vt) if vt else None,
            "frames": vt,
            "orig_noise_frames": vo_n,
            "our_noise_frames": vu_n,
        })
        agree += va
        total += vt
        o_noise += vo_n
        u_noise += vu_n
    return {
        "wave": (agree / total) if total else None,
        "wave_frames": total,
        "orig_noise_frames": o_noise,
        "our_noise_frames": u_noise,
        "wave_voices": per_voice,
    }


# --------------------------------------------------------------------------
# optional SIDM2 stages
# --------------------------------------------------------------------------
def sidm2_register(orig: Path, ours: Path, seconds: int,
                   root: str = SIDM2_ROOT) -> dict:
    """validate_sid_accuracy.py -- frame-exact register comparison.

    Run with SIDM2's root as the working directory: it resolves
    tools/siddump.exe relatively, and writes its HTML report into the cwd.
    """
    script = Path(root) / "scripts" / "validate_sid_accuracy.py"
    if not script.exists():
        return {"error": f"not found: {script}"}
    proc = subprocess.run(
        [sys.executable, "scripts/validate_sid_accuracy.py", str(orig), str(ours),
         "--duration", str(seconds)],
        cwd=root, capture_output=True, text=True, timeout=600,
        stdin=subprocess.DEVNULL)
    out = proc.stdout + proc.stderr
    got = {}
    for label, key in (("Overall Accuracy", "overall"),
                       ("Per-Frame Accuracy", "per_frame"),
                       ("Filter Accuracy", "filter")):
        m = re.search(rf"{label}:\s+([\d.]+)%", out)
        if m:
            got[key] = float(m.group(1))
    if not got:
        got["error"] = out.strip().splitlines()[-1] if out.strip() else "no output"
    return got


def sidm2_audio(orig: Path, ours: Path, seconds: int,
                root: str = SIDM2_ROOT) -> dict:
    """audio_tightness_tool.py -- onset-aligned audio comparison."""
    script = Path(root) / "pyscript" / "audio_tightness_tool.py"
    if not script.exists():
        return {"error": f"not found: {script}"}
    proc = subprocess.run(
        [sys.executable, "pyscript/audio_tightness_tool.py", str(orig), str(ours),
         "--seconds", str(seconds), "--no-html"],
        cwd=root, capture_output=True, text=True, timeout=900,
        stdin=subprocess.DEVNULL)
    out = proc.stdout + proc.stderr
    got = {}
    # Take the tool's *jitter* block, not its raw delta block: it says so
    # itself ("offset removed; THIS is the tightness measure"). A constant
    # offset is expected here -- our tempo is knowingly wrong -- so the raw
    # delta would report that and nothing else.
    for pat, key in ((r"Orig onsets:\s+(\d+)", "orig_onsets"),
                     (r"Driver onsets:\s+(\d+)", "our_onsets"),
                     (r"Matched:\s+(\d+)", "matched_onsets"),
                     (r"SYSTEMATIC OFFSET \(median delta\):\s*([+-]?[\d.]+)",
                      "systematic_offset_ms"),
                     (r"jitter \(ms\):\s*mean\s*([+-]?[\d.]+)", "jitter_mean_ms"),
                     (r"jitter \(ms\):\s*mean\s*[+-]?[\d.]+\s+median\s*([+-]?[\d.]+)",
                      "jitter_median_ms"),
                     (r"Loose \(\|jitter\|[^)]*\):\s*(\d+)", "loose_onsets")):
        m = re.search(pat, out)
        if m:
            got[key] = float(m.group(1))
    if not got:
        tail = out.strip().splitlines()
        got["error"] = tail[-1] if tail else "no output"
    return got


# --------------------------------------------------------------------------
# driver
# --------------------------------------------------------------------------
def _preset_opts(doc: dict, name: str) -> dict:
    entry = (doc.get("songs") or {}).get(name, {})
    always = doc.get("always", {})
    return {
        "max_rows": entry.get("max_rows", 94),
        "pack": bool(entry.get("pack")),
        "prune": bool(entry.get("prune")),
        "dedup": bool(entry.get("dedup")),
        "fmt": always.get("format", FORMAT_GTS5),
        "tempo": always.get("tempo", "auto"),
        "slides": bool(always.get("slides")),
        "effects": bool(always.get("effects")),
        "status_bit6": bool(always.get("status_bit6")),
        "reject_phantoms": bool(always.get("reject_phantoms")),
        "fold_transpose": bool(always.get("fold_transpose")),
    }


def _preset_multiplier(doc: dict, name: str) -> int:
    """The gt2reloc -S value this song's player needs, 1 if none.

    Not an option -- a property of the player's own speed gate, recorded by
    presets.py. Kept out of _preset_opts because convert() takes no such
    keyword: it belongs to the packing step, not the conversion.
    """
    entry = (doc.get("songs") or {}).get(name, {})
    try:
        return max(1, int(entry.get("multiplier", 1)))
    except (TypeError, ValueError):
        return 1


def resolve_subtune(sid: Path, requested) -> int:
    """Which subtune of the original to trace.

    `requested` is an int to force one, or "auto" (the default) to take the
    PSID header's own `startSong` -- the subtune a player selects when the user
    selects none, and therefore the one that is *the tune*. Seven corpus files
    set it past 1 and tracing 0 measured them against the wrong music:
    Samantha Fox Strip Poker's subtune 0 is a one-note stub against which a
    correct conversion scored 5%, and at its real startSong it scores 89%.

    Falls back to 0 for anything unreadable -- a header this harness cannot
    parse is not a reason to skip the file.
    """
    if requested != "auto":
        return int(requested)
    try:
        return max(0, load_sid(str(sid)).start_song - 1)
    except Exception:  # noqa: BLE001 -- an unparseable header is not fatal here
        return 0


def measure(sid: Path, workdir: Path, opts: dict, args,
            multiplier: int = 1) -> dict:
    """One file, end to end: convert -> pack -> trace both -> compare.

    `multiplier` is the song's gt2reloc -S value, a property of its player
    rather than a conversion option, so it rides beside `opts` instead of in
    it -- convert() takes no such keyword. It reaches the packing step only;
    siddump cannot honour it (see pack_sid).
    """
    sub = resolve_subtune(sid, args.subtune)
    row: dict = {"file": sid.name, "options": opts, "multiplier": multiplier,
                 "subtune": sub}
    try:
        sng = convert(str(sid), log=lambda m: None, **opts)
    except Exception as exc:  # noqa: BLE001 -- a file that will not convert is a result
        row["status"] = "not converted"
        row["detail"] = f"{type(exc).__name__}: {exc}"
        return row

    sng, patched = legalise_restarts(sng)
    row["restarts_patched"] = patched

    # Read what gt2reloc will keep *before* running it, so a row can say
    # whether its own number is trustworthy rather than leaving a stub to be
    # scored as a failed conversion.
    try:
        exp = greloc_export(song_lengths(sng))
    except IndexError:      # malformed .sng: let the pack attempt report it
        exp = None
    if exp and (exp["stub"] or exp["lost"]):
        row["export"] = exp
        if sub in exp["stub"]:
            row["traced_subtune_dropped"] = True

    packed = pack_sid(sng, workdir, args.gt2reloc, multiplier)
    if packed is None:
        row["status"] = "not packed"
        row["detail"] = "gt2reloc wrote no .sid"
        return row

    local_orig = workdir / "o.sid"
    shutil.copyfile(sid, local_orig)
    # The original is traced on its own tuning; ours is always Goattracker's.
    # Only a table that is off the semitone grid needs this -- a shifted one is
    # a converter defect and gets no allowance (see sidfile.find_freq_table).
    ft = find_freq_table(load_sid(str(sid)))
    cal = calibration(ft.detune) if ft and abs(ft.detune) > 0.2 else 0
    if cal:
        row["calibration"] = {"detune": round(ft.detune, 3), "c": cal}
    a = run_siddump(local_orig, args.seconds, sub, args.siddump, cal)
    b = run_siddump(packed, args.seconds, sub, args.siddump)
    row["status"] = "measured"
    row.update(compare(a, b))
    best_dump = b
    if args.search_subtunes > 1:
        # Our subtune numbering does not have to line up with the original's:
        # a subtune whose orderlist exceeds Goattracker's limit costs itself,
        # and every later one shifts down. Trying each of ours against the
        # original's finds the real counterpart instead of scoring a
        # comparison of two different pieces of music. The window is centred on
        # the traced subtune, not on 0, because a drop shifts the counterpart
        # by one or two either way and `sub` is now rarely 0.
        best, best_at = row["melody"], sub
        half = args.search_subtunes // 2
        for st in range(max(0, sub - half), sub + args.search_subtunes - half):
            if st == sub:
                continue
            cand_dump = run_siddump(packed, args.seconds, st, args.siddump)
            cand = compare(a, cand_dump)
            if cand["melody"] > best:
                best, best_at, row = cand["melody"], st, {**row, **cand}
                best_dump = cand_dump
        row["matched_subtune"] = best_at
    row.update(wave_compare(a, best_dump, nframes=args.seconds * 50))
    if row["our_attacks"] == 0:
        # A conversion that plays nothing is a defect; a *window* in which
        # neither side plays anything is not, and calling both "silent" put
        # BMX_Kidz -- which opens with about thirteen seconds of rest and then
        # matches at 95% -- in the bucket labelled "plays something else" for
        # eighteen versions.
        row["status"] = "window empty" if row["orig_attacks"] == 0 else "silent"
    if args.register:
        row["register"] = sidm2_register(local_orig, packed, args.seconds)
    if args.audio:
        row["audio"] = sidm2_audio(local_orig, packed, args.seconds)
    return row


def _fmt_pct(x) -> str:
    return "-" if x is None else f"{100 * x:.0f}%"


def report(rows: list[dict], args) -> str:
    # A row whose traced subtune came back as an empty stub is a measurement
    # of gt2reloc, not of the converter. It stays in the table, marked, but
    # averaging it in would put a known-meaningless number into the headline.
    # "window empty" is excluded for the same reason: nothing played on either
    # side, so the 0% it would contribute measures the window, not the file.
    measured = [r for r in rows if r["status"] in ("measured", "silent")
                and not r.get("traced_subtune_dropped")]
    excluded = [r for r in rows if r.get("traced_subtune_dropped")]
    out = [
        f"# Fidelity report",
        "",
        f"Generated by `python/fidelity.py` (h2g {__version__}"
        f"{', ' + args.label if args.label else ''}), "
        f"{args.seconds} s of "
        + ("each file's default subtune (PSID `startSong`)"
           if args.subtune == "auto" else f"subtune {args.subtune}")
        + f", {len(rows)} file(s).",
        "",
        "Each row converts the .sid with its preset options, packs the result "
        "back to a .sid with `gt2reloc`, traces both with `siddump`, and "
        "compares the **note attacks** -- the notes siddump prints bare, which "
        "are the ones the player gate-retriggers.",
        "",
        "* **melody** -- similarity of the attack sequence with consecutive "
        "repeats collapsed: the right notes in the right order.",
        "* **seq** -- the same without collapsing, so a note struck eight times "
        "where the original struck it once counts against it.",
        "* **retrig** -- our attacks over the original's. 1.0 is right; higher "
        "means we re-strike held notes.",
        "* **pitch** -- Jaccard overlap of the distinct pitches played.",
        "* **slides** -- frames on which a voice's frequency moved without "
        "being retriggered (vibrato, portamento, any bend), ours over the "
        "original's. Every other column is blind to these: they happen "
        "*within* a note, so a change that only adds or removes pitch "
        "movement leaves melody, seq and retrig identical.",
        "* **wave** -- per-frame agreement of the waveform *class* (the "
        "waveform-select nibble of $D404: triangle/saw/pulse/noise, with a "
        "combined waveform its own class and the gate/sync/ring/test bits "
        "ignored), carried forward between register writes. Frames where "
        "both sides select no waveform are not counted.",
        "* **noise** -- frames on which the voice's waveform included noise "
        "(bit 7), ours over the original's. A nonzero left of a zero right "
        "is a drum tick the conversion invented.",
        "",
        "| File | orig | ours | retrig | melody | seq | pitch | slides | wave | noise | status |",
        "|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|---|",
    ]
    for r in sorted(rows, key=lambda r: r["file"].lower()):
        if r["status"] not in ("measured", "silent", "window empty"):
            out.append(
                f"| {r['file']} | - | - | - | - | - | - | - | - | - | {r['status']} |")
            continue
        rr = r["retrigger_ratio"]
        status = r["status"]
        if r.get("traced_subtune_dropped"):
            status += " -- **not comparable**"
        noise = f"{r.get('our_noise_frames', 0)}/{r.get('orig_noise_frames', 0)}"
        if r.get("our_noise_frames") and not r.get("orig_noise_frames"):
            noise += " !"
        out.append(
            f"| {r['file']} | {r['orig_attacks']} | {r['our_attacks']} | "
            f"{'-' if rr is None else f'{rr:.2f}'} | {_fmt_pct(r['melody'])} | "
            f"{_fmt_pct(r['sequence'])} | {_fmt_pct(r['pitch_jaccard'])} | "
            f"{r.get('our_slides', 0)}/{r.get('orig_slides', 0)} | "
            f"{_fmt_pct(r.get('wave'))} | {noise} | "
            f"{status} |")

    if measured:
        n = len(measured)
        out += [
            "",
            "## Summary",
            "",
            f"- measured: **{n}** of {len(rows)}"
            + (f" ({len(excluded)} further file(s) packed, but the traced "
               "subtune came back as an empty stub -- see below -- so they are "
               "in the table and out of these averages)" if excluded else ""),
            f"- mean melody similarity: **{_fmt_pct(sum(r['melody'] for r in measured) / n)}**",
            f"- mean sequence similarity: **{_fmt_pct(sum(r['sequence'] for r in measured) / n)}**",
            f"- mean pitch overlap: **{_fmt_pct(sum(r['pitch_jaccard'] for r in measured) / n)}**",
        ]
        waved = [r for r in measured if r.get("wave") is not None]
        if waved:
            o_noise = sum(r.get("orig_noise_frames", 0) for r in waved)
            u_noise = sum(r.get("our_noise_frames", 0) for r in waved)
            invented = [r for r in waved
                        if r.get("our_noise_frames") and not r.get("orig_noise_frames")]
            out += [
                f"- mean wave agreement: **{_fmt_pct(sum(r['wave'] for r in waved) / len(waved))}**"
                f" ({len(waved)} file(s))",
                f"- noise frames, ours/original: **{u_noise}/{o_noise}**"
                + (f"; **{len(invented)}** file(s) play noise where the "
                   "original never does (marked `!` above)" if invented else ""),
            ]
        ratios = [r["retrigger_ratio"] for r in measured if r["retrigger_ratio"]]
        if ratios:
            out.append(f"- median retrigger ratio: **{sorted(ratios)[len(ratios) // 2]:.2f}**")
        slowed = [r for r in measured if r.get("multiplier", 1) > 1]
        if slowed:
            mean_ok = sum(r["melody"] for r in measured if r.get("multiplier", 1) == 1)
            n_ok = n - len(slowed)
            out += [
                f"- **{len(slowed)} of these {n} files score below their real "
                "fidelity, and no rerun will fix it.** Their player advances "
                "one row every 2 frames, which Goattracker reaches only by "
                "being called twice a frame. They are packed here with "
                "`gt2reloc -S2` and the packed `.sid` is correct -- it carries "
                "the CIA stub that reprograms timer A to 100.25 Hz -- but "
                "siddump ignores the PSID speed field entirely, calling the "
                "play routine `seconds x 50` times regardless "
                "(siddump.c:309/325). Applying `-S` therefore changes the "
                "bytes and not the trace: measured A/B on one of these files, "
                "melody, sequence, retrigger ratio and attack counts are "
                "identical with and without it. So these rows are traced at "
                "half their true row rate and lose roughly half their notes "
                "inside the window. Only a cycle-accurate emulator can score "
                "them; RetroDebugger has confirmed two at their correct rate."
                + (f" Excluding them, mean melody similarity is "
                   f"**{_fmt_pct(mean_ok / n_ok)}** over {n_ok} file(s)."
                   if n_ok else ""),
            ]
        off0 = sorted(r["file"] for r in rows if r.get("subtune"))
        if off0:
            out.append(
                f"- {len(off0)} file(s) are traced at a subtune other than 0, "
                "because their PSID header names another one as the default. "
                "Subtune 0 is not always the tune: Samantha Fox Strip Poker's "
                "is a one-note stub, and comparing a correct conversion "
                "against it scored 5% where its real startSong scores 89%. "
                f"({', '.join(off0)})")
        shifted = sorted(
            f"{r['file']} ({r['subtune']}->{r['matched_subtune']})"
            for r in rows
            if r.get("matched_subtune") is not None
            and r["matched_subtune"] != r.get("subtune"))
        if shifted:
            out.append(
                f"- {len(shifted)} file(s) are scored against a subtune of "
                "*ours* other than the one traced in the original, because our "
                "numbering shifts when a subtune is dropped. The window is one "
                "either side; widening it moves no other file, so this is "
                "identifying the counterpart rather than picking the "
                f"flattering one. ({', '.join(shifted)})")
        patched = sum(1 for r in rows if r.get("restarts_patched"))
        if patched:
            out.append(
                f"- {patched} file(s) needed their song restart position "
                "legalised before gt2reloc would pack them (SNG2SID-FIDELITY.md §2)")

        cal = [r for r in rows if r.get("calibration")]
        if cal:
            names = ", ".join(sorted(r["file"] for r in cal))
            out.append(
                f"- {len(cal)} file(s) carry a frequency table tuned away from "
                "Goattracker's, so siddump was recalibrated to each one before "
                "naming the original's notes -- otherwise the same music comes "
                "out named in another key and scores 0%. The tuning itself is "
                "not corrected and cannot be: it is what the file plays. "
                f"({names})")

        # The mean hides the shape, and the shape is the finding: this is not
        # a corpus that is uniformly 2/3 right, it is one where most files are
        # close and a minority play something else entirely.
        bands = [("plays the same music", 0.95, 1.01),
                 ("close", 0.80, 0.95),
                 ("recognisable", 0.50, 0.80),
                 ("plays something else", -0.01, 0.50)]
        out += ["", "## Distribution", "",
                "| melody similarity | files | |", "|---|---:|---|"]
        for label, lo, hi in bands:
            got = [r for r in measured if lo <= r["melody"] < hi]
            names = ", ".join(sorted(r["file"].replace(".sid", "") for r in got))
            out.append(f"| {label} ({100 * max(lo, 0):.0f}-{100 * min(hi, 1):.0f}%) "
                       f"| {len(got)} | {names if len(got) <= 25 else ''} |")

    dropped = [r for r in rows if r.get("export")]
    if dropped:
        out += [
            "",
            "## Subtunes `gt2reloc` does not export",
            "",
            "`greloc.c:200-255` counts only the subtunes whose three voices all "
            "have nonzero length, and the writing loop at `:653` then runs over "
            "the *original* indices `c < songs`. Nothing is renumbered. Two "
            "things happen instead:",
            "",
            "* **stub** -- a subtune with an empty voice keeps its index and is "
            "written with `songsize 0` (`:701-706`): it exists in the packed "
            "`.sid` and plays nothing. Comparing against one measures our "
            "converter against silence, so those rows are marked "
            "*not comparable* above rather than scored.",
            "* **lost** -- every subtune whose index is >= the exported count is "
            "never written, valid or not. This is silent data loss in the "
            "packed `.sid`; it does not affect the measurement of subtune 0, "
            "but it does affect anyone playing the file.",
            "",
            "| File | ours | exported | stub | lost |",
            "|---|---:|---:|---|---|",
        ]
        for r in sorted(dropped, key=lambda r: r["file"].lower()):
            e = r["export"]
            fmt = lambda xs: ", ".join(str(x) for x in xs) if xs else "-"  # noqa: E731
            out.append(f"| {r['file']} | {e['subtunes']} | {e['exported']} | "
                       f"{fmt(e['stub'])} | {fmt(e['lost'])} |")

    if getattr(args, "pair", None):
        for r in rows:
            if not r.get("wave_voices"):
                continue
            out += ["", "## Wave detail (per voice)", "",
                    "| voice | wave | frames counted | noise ours/orig |",
                    "|---|---:|---:|---:|"]
            for i, v in enumerate(r["wave_voices"]):
                out.append(f"| {i} | {_fmt_pct(v['wave'])} | {v['frames']} | "
                           f"{v['our_noise_frames']}/{v['orig_noise_frames']} |")

    out += [
        "",
        "## What this does not say",
        "",
        "- Only **one subtune per file** -- the PSID header's own `startSong`, "
        "which is the subtune a player selects when the user selects none -- "
        f"and only its first {args.seconds} seconds. A tune whose subtunes "
        "shift when one is dropped can still be compared against the wrong "
        "piece of music; `--search-subtunes N` tries a window of ours around "
        "it and keeps the best match. **A short window is its own hazard**: "
        "`BMX_Kidz.sid` opens with about thirteen seconds of silence, so at "
        "10 s both sides are empty and it scores 0%; at 60 s it scores 95%.",
        "- *not converted* is the converter refusing the file, which "
        "`SURVEY.md` explains per file; *not packed* is `gt2reloc` refusing "
        "the `.sng`; *silent* is a conversion that packs and plays nothing; "
        "*window empty* is a file where **neither side** played a note in the "
        "traced seconds, which says nothing about the conversion and is left "
        "out of the averages rather than scored 0%.",
        "- The harness legalises song restart positions before packing "
        "(SNG2SID-FIDELITY.md §2), so a file counted here may still be "
        "unpackable as the converter writes it.",
        "- Timing is not measured at all. Two files can agree on every note "
        "and play at different speeds; that is what `--audio` and `--register` "
        "are for.",
        "- **wave** compares the waveform class only. It cannot see pitch, "
        "so a noise class agreeing on both sides says nothing about which "
        "notes are under it; pulse-width differences within the pulse class "
        "are invisible (tracking siddump's Pul column would fix that -- "
        "future work, not built); ADSR and volume are not compared; and "
        "because it ignores the gate bit, a note held twice as long with the "
        "right waveform still scores 100% here. A gated-off voice keeps its "
        "last waveform latched, so silence between notes inherits the "
        "previous note's class on both sides.",
    ]
    out.append("")
    return "\n".join(out)


def main(argv=None) -> int:
    p = argparse.ArgumentParser(prog="fidelity", description=__doc__.splitlines()[0])
    p.add_argument("target", nargs="?", help=".sid file or directory of them")
    p.add_argument("--pair", nargs=2, metavar=("A.sid", "B.sid"),
                   help="compare two existing .sid files, skipping conversion")
    p.add_argument("-o", "--output", help="write a Markdown report here")
    p.add_argument("--json", help="write the raw measurements here")
    p.add_argument("--label", help="provenance note for the report header, e.g. "
                                   "the commit the measurement was taken from")
    p.add_argument("--presets", default=str(Path(__file__).resolve().parent.parent
                                            / "presets.json"))
    p.add_argument("-t", "--seconds", type=int, default=DEFAULT_SECONDS)
    p.add_argument("-a", "--subtune", default="auto",
                   help="which subtune of the original to trace: a number, or "
                        "'auto' (the default) for the PSID header's own "
                        "startSong -- the subtune a player picks when the user "
                        "picks none, which is not 0 in seven corpus files")
    p.add_argument("--slides", action="store_true",
                   help="convert with --slides (the two-byte pitch-slide "
                        "operand) regardless of what the presets say, so the "
                        "option can be measured before it is stored in one")
    p.add_argument("--effects", action="store_true",
                   help="convert with --effects (the instrument effect byte's "
                        "chromatic rise, and no fabricated octave arpeggio) "
                        "regardless of what the presets say")
    p.add_argument("--fold-transpose", action="store_true",
                   help="convert with --fold-transpose (orderlist transposes "
                        "over Goattracker's +14 folded into the notes) "
                        "regardless of what the presets say")
    p.add_argument("--search-subtunes", type=int, default=3, metavar="N",
                   help="try a window of N of our subtunes centred on the "
                        "traced one and keep the best match; our numbering "
                        "shifts when a subtune is dropped. Default 3, i.e. one "
                        "either side -- enough to find a counterpart displaced "
                        "by a dropped subtune, and measured to move exactly "
                        "the two corpus files that are displaced. 1 disables it")
    p.add_argument("--workdir", default=WORKDIR,
                   help="short scratch path; gt2reloc's filename buffer is 60 bytes")
    p.add_argument("--siddump", default=SIDDUMP)
    p.add_argument("--gt2reloc", default=GT2RELOC)
    p.add_argument("--register", action="store_true",
                   help="also run SIDM2's frame-exact register comparison")
    p.add_argument("--audio", action="store_true",
                   help="also run SIDM2's onset-aligned audio comparison")
    args = p.parse_args(argv)

    if not Path(args.siddump).exists():
        print(f"error: siddump not found: {args.siddump}", file=sys.stderr)
        return 1

    workdir = Path(args.workdir)
    try:
        workdir.mkdir(parents=True, exist_ok=True)
    except OSError:
        workdir = Path(tempfile.mkdtemp(prefix="h2gfid"))

    if args.pair:
        a, b = (Path(x) for x in args.pair)
        sub = resolve_subtune(a, args.subtune)
        row = {"file": f"{a.name} vs {b.name}", "status": "measured",
               "subtune": sub}
        da = run_siddump(a, args.seconds, sub, args.siddump)
        db = run_siddump(b, args.seconds, sub, args.siddump)
        row.update(compare(da, db))
        row.update(wave_compare(da, db, nframes=args.seconds * 50))
        if args.register:
            row["register"] = sidm2_register(a, b, args.seconds)
        if args.audio:
            row["audio"] = sidm2_audio(a, b, args.seconds)
        rows = [row]
    else:
        if not args.target:
            p.error("give a .sid, a directory, or --pair")
        if not Path(args.gt2reloc).exists():
            print(f"error: gt2reloc not found: {args.gt2reloc}", file=sys.stderr)
            return 1
        try:
            doc = json.loads(Path(args.presets).read_text(encoding="utf-8"))
        except OSError:
            doc = {}
        target = Path(args.target)
        sids = sorted(target.rglob("*.sid"), key=lambda q: q.name.lower()) \
            if target.is_dir() else [target]
        rows = []
        for sid in sids:
            opts = _preset_opts(doc, sid.name)
            if args.slides:
                opts["slides"] = True
            if args.effects:
                opts["effects"] = True
            if args.fold_transpose:
                opts["fold_transpose"] = True
            # Applied to the packing step, not to the trace: gt2reloc's -S
            # changes the packed bytes so the tune plays at its real rate,
            # but siddump calls the play routine seconds x 50 times whatever
            # the PSID speed field says, so a file needing -S2 still traces
            # at half its real row rate here and its scores understate.
            row = measure(sid, workdir, opts, args,
                          _preset_multiplier(doc, sid.name))
            rows.append(row)
            note = (f"melody {_fmt_pct(row['melody'])} retrig "
                    f"{row['retrigger_ratio']:.2f} wave {_fmt_pct(row.get('wave'))}"
                    if row["status"] in ("measured", "silent")
                    and row["retrigger_ratio"] else row["status"])
            print(f"  {sid.name:44} {note}", file=sys.stderr)

    text = report(rows, args)
    if args.output:
        Path(args.output).write_text(text, encoding="utf-8")
        print(f"wrote {args.output}", file=sys.stderr)
    else:
        print(text)
    if args.json:
        Path(args.json).write_text(json.dumps(rows, indent=2) + "\n", encoding="utf-8")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
