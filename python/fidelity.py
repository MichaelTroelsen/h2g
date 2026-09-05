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
   order". Reported alongside the uncollapsed ratio (**sequence**, below).
   Because it is collapsed, melody cannot see a note that gets re-struck: a
   change that re-articulates an already-sounding note is invisible to it as
   a *wrong* note and shows up only as a *longer* sequence to align against
   -- read **retrigger ratio** and **sequence** for that, not melody.

Separately from note attacks, the **wave** metric compares the waveform
register ($D404) frame by frame: siddump's WF column, carried forward across
the frames it is not reprinted, reduced to its waveform-class nibble (see
wave_compare). It exists to measure the fabricated wavetable -- goatwriter
writes a noise-tick/arpeggio wavetable for every instrument whether or not
the source player had those semantics, and no attack-based metric can see
the difference between a pulse note and the same note opening on a frame of
noise.

What a run says about its own reach
-----------------------------------
Every dimension above declares the SID registers it is computed from (see
DIMENSIONS), every row records which of them it actually compared, and the
report prints both -- plus the registers no dimension reads, which is where a
change has to land to be invisible here. `--baseline old.json` turns that into
a verdict: it hashes the converter's output per row, so it can tell "no
dimension this report measures can see this change" apart from "this change
reaches nothing", which are the two readings of one flat table and this
project has shipped the second believing the first twice.
"""
from __future__ import annotations

import argparse
import dataclasses
import difflib
import functools
import hashlib
import inspect
import json
import os
import re
import shutil
import subprocess
import sys
import tempfile
import typing
from collections import Counter
from dataclasses import dataclass, field
from pathlib import Path

from h2g import __version__
from h2g.convert import _detect_tables, convert
from h2g.detect import detect
from h2g.goatwriter import (FORMAT_GTS5, HEADER_LEN, effective_frames,
                            find_song_speeds)
from h2g.patterns import GT_ORDER_RESTART, GT_REPEAT
from h2g.sidfile import find_freq_table, load_sid

import vicetrace

# Defaults are the tools as they sit on this machine; every one is overridable
# so the harness is not pinned to one install.
# tools/siddump-rt is siddump 1.08 plus -m (playroutine calls per frame); see
# its README. Preferred when built, because a tune packed at gt2reloc -S2 is
# traced at half speed without it. Stock siddump still works for everything at
# multiplier 1 -- and run_siddump refuses to pretend otherwise for the rest.
# $02A6 is the KERNAL's PAL/NTSC flag and siddump starts it at 0, which is
# NTSC. Three corpus players branch on it and skip a frame periodically to
# compensate for a 60Hz machine, so tracing without setting it measures
# behaviour a PAL C64 never has -- and Goattracker targets PAL. 1 is PAL;
# --ntsc sets this to None and reproduces every measurement taken before
# v0.5.110.
PAL_FLAG: int | None = 1

# A default argument is bound when the function is defined, so a parameter
# defaulting to PAL_FLAG would ignore --ntsc entirely -- which it did, silently,
# until the A/B printed identical columns.
_USE_DEFAULT = object()

SIDDUMP_RT = Path(__file__).resolve().parent / "tools" / "siddump-rt" / "siddump.exe"
SIDDUMP = os.environ.get(
    "H2G_SIDDUMP",
    str(SIDDUMP_RT) if SIDDUMP_RT.exists()
    else r"C:\Users\mit\claude\c64server\SIDM2\tools\siddump.exe")
GT2RELOC = os.environ.get(
    "H2G_GT2RELOC", r"C:\Users\mit\Downloads\GoatTracker_2.77\win32\gt2reloc.exe")
SIDM2_ROOT = os.environ.get(
    "H2G_SIDM2", r"C:\Users\mit\claude\c64server\SIDM2")

# gt2reloc strcpy()s argv[1] into a 60-byte MAX_FILENAME buffer without
# reducing it to a basename, so it is run with short names and a short cwd.
WORKDIR_ROOT = os.environ.get("H2G_FIDELITY_ROOT", r"C:\t")

# The scratch directory is per-run, and unset here on purpose. Every file in
# it has a fixed name -- a.sng, b.sid, o.sid -- so two harnesses sharing one
# directory overwrite each other's input between the write and the read, and
# each measures whichever file won the race. It fails silently: the numbers
# are plausible, just not about the file named beside them. That is not
# hypothetical, it has contaminated an A/B in this repo, and this project
# forks concurrent agents as a matter of course.
#
# H2G_FIDELITY_WORK pins it to one directory for debugging, which is only
# safe for one run at a time.
WORKDIR = os.environ.get("H2G_FIDELITY_WORK")

DEFAULT_SECONDS = 8


def make_workdir(explicit: str | None = None) -> tuple[Path, bool]:
    """Return (directory, owned). `owned` means this run created it.

    An explicit path is used as given and never removed -- it is the debugging
    route, and deleting a directory the caller named is not this script's
    business. Otherwise a private one is made under WORKDIR_ROOT, which is
    short because gt2reloc's cwd matters as much as its argv; if that root is
    unavailable the system temp directory is the fallback, which is longer but
    correct, and the filenames handed to gt2reloc are bare either way.
    """
    if explicit:
        d = Path(explicit)
        d.mkdir(parents=True, exist_ok=True)
        return d, False
    try:
        Path(WORKDIR_ROOT).mkdir(parents=True, exist_ok=True)
        return Path(tempfile.mkdtemp(prefix="fid", dir=WORKDIR_ROOT)), True
    except OSError:
        return Path(tempfile.mkdtemp(prefix="h2gfid")), True


# --------------------------------------------------------------------------
# siddump output
# --------------------------------------------------------------------------
# One voice cell, after splitting a row on '|', is a 4-hex frequency (or
# '....') then a 9-character note field written by one of exactly four
# sprintf formats in siddump.c:409-429, then the 2-hex waveform register
# (or '..' when the register was not written this frame), the 4-hex ADSR pair
# and the 3-hex pulse width (siddump.c:436-446). The trailing cell is global:
# 4-hex cutoff, the 2-hex $D417 byte, a 3-character passband name and the
# 1-hex master volume (siddump.c:451-467).
_ATTACK = re.compile(r" ([A-G][-#]\d) ([0-9A-F]{2})  ")
_TIE = re.compile(r"\(([A-G][-#]\d) ([0-9A-F]{2})\) ")
_SLIDE = re.compile(r"\(([+-]) ([0-9A-F]{4})\) ")
_HEX = re.compile(r"[0-9A-F]+\Z")

# $D404 waveform-register bits. The upper nibble selects the waveform(s);
# the lower nibble is gate/sync/ring/test, none of which is a timbre.
WF_GATE = 0x01
WF_NOISE = 0x80

# siddump.c:54-55, verbatim apart from the padding on "Hi ". The index is
# ($D418 >> 4) & 7, so the name is losslessly reversible into the passband
# bits and a timeline of them is a timeline of the register.
FILTER_PASSBAND = ("Off", "Low", "Bnd", "L+B", "Hi", "L+H", "B+H", "LBH")
_PASSBAND = {name: i for i, name in enumerate(FILTER_PASSBAND)}


def _hex_field(text: str, width: int) -> int | None:
    """One sparse register field, or None when siddump printed it as dots.

    siddump writes a register's value only on the frame it changed and dots of
    the same width otherwise (siddump.c:436-467), so "absent" here means *the
    chip is still holding the last value*, never zero. Returning None keeps
    that distinction; register_timeline() is what turns it back into a value.
    """
    if len(text) != width or not _HEX.match(text):
        return None
    return int(text, 16)


@dataclass
class Voice:
    attacks: list[str] = field(default_factory=list)   # note names, in order
    attack_frames: list[int] = field(default_factory=list)
    ties: int = 0
    # Frames on which siddump printed a *tie* -- a note change with no gate
    # retrigger.
    tie_frames: list[int] = field(default_factory=list)
    # Summed magnitude of every frequency move siddump printed as a bend.
    bend: int = 0
    slides: int = 0
    # (frame, value) for every frame siddump shows the register written.
    # siddump prints a value only when it changed, so between events the
    # register holds its last value -- register_timeline() expands any of
    # these into a per-frame view.
    #
    # Comparing these sparse lists directly would be wrong for all three:
    # a side that writes $0F00 on every frame and one that writes it once
    # sound identical and would score as opposites. Every consumer must go
    # through register_timeline() first.
    # The voice frequency ($D400/$D401), siddump's first per-voice field.
    # Parsed for `bend`: how far the pitch travels *within* notes, which is the
    # question a count of moved frames cannot answer -- see compare().
    freq_events: list[tuple[int, int]] = field(default_factory=list)
    wf_events: list[tuple[int, int]] = field(default_factory=list)
    adsr_events: list[tuple[int, int]] = field(default_factory=list)
    pulse_events: list[tuple[int, int]] = field(default_factory=list)

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


@dataclass
class FilterState:
    """The one global cell, which is not per voice: $D415-$D418.

    siddump prints these four fields on their own change conditions
    (siddump.c:451-467), each independent of the voices and of each other, so
    they are four sparse event lists exactly like a voice's -- and like a
    voice's they mean *held*, not zero, on the frames they are absent.

    `ctrl` is the whole $D417 byte as siddump's `RC` column prints it:
    resonance in the high nibble, filter routing (voices 1-3 and the external
    input) in the low one. siddump never separates them, so neither does this.
    `passband` is ($D418 >> 4) & 7, an index into FILTER_PASSBAND; `volume` is
    $D418 & $F.
    """
    cutoff_events: list[tuple[int, int]] = field(default_factory=list)
    ctrl_events: list[tuple[int, int]] = field(default_factory=list)
    passband_events: list[tuple[int, int]] = field(default_factory=list)
    volume_events: list[tuple[int, int]] = field(default_factory=list)


class Trace(list):
    """The three Voices, with the file-level FilterState attached.

    A list subclass so that every existing caller -- `a, b, c = parse_dump(t)`,
    `zip(orig, ours)`, `orig + ours` -- keeps working unchanged and keeps
    treating the voices as the payload. The filter is one object per dump, not
    per voice, so it cannot live on Voice; hanging it here is what lets a
    single pass over the table produce both.
    """

    def __init__(self, voices, filt: FilterState):
        super().__init__(voices)
        self.filter = filt


def parse_dump(text: str) -> Trace:
    """Three Voices and the global filter state out of siddump's table.

    Every register siddump prints is read here, and every one of them is
    sparse: a value appears on the frame it was written and dots thereafter.
    Absence means *held*, not zero, so nothing downstream may compare these
    event lists directly -- a side that rewrites the same value each frame and
    one that writes it once are the same sound and would score as opposites.
    register_timeline() is the carry-forward that makes them comparable, and
    it is the only correct way to read any of these fields.
    """
    voices = [Voice(), Voice(), Voice()]
    filt = FilterState()
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
            fval = _hex_field(cell[1:5], 4)
            if fval is not None:
                voices[v].freq_events.append((frame, fval))
            # Fixed offsets into the tail of the cell: the 9-char note field
            # is the same width in all four note formats, so the waveform,
            # ADSR and pulse fields that follow it always sit here.
            for text_slice, width, events in (
                    (rest[9:11], 2, voices[v].wf_events),
                    (rest[12:16], 4, voices[v].adsr_events),
                    (rest[17:20], 3, voices[v].pulse_events)):
                val = _hex_field(text_slice, width)
                if val is not None:
                    events.append((frame, val))
            m = _ATTACK.match(rest)
            if m:
                voices[v].attacks.append(m.group(1))
                voices[v].attack_frames.append(frame)
                continue
            if _TIE.match(rest):
                voices[v].ties += 1
                voices[v].tie_frames.append(frame)
                continue
            m = _SLIDE.match(rest)
            if m:
                voices[v].slides += 1
                # siddump has already decided this frame is pitch movement
                # rather than a note, and printed how far. Summing its own
                # number is what `bend` is; see _bend_travel.
                voices[v].bend += int(m.group(2), 16)

        glob = cells[5]  # ' FCut RC Typ V ', or dots for the unwritten fields
        for text_slice, width, events in (
                (glob[1:5], 4, filt.cutoff_events),
                (glob[6:8], 2, filt.ctrl_events),
                (glob[13:14], 1, filt.volume_events)):
            val = _hex_field(text_slice, width)
            if val is not None:
                events.append((frame, val))
        # The passband is the one field siddump prints as a name rather than
        # hex; '...' is its "unwritten" marker.
        band = _PASSBAND.get(glob[9:12].strip())
        if band is not None:
            filt.passband_events.append((frame, band))
    return Trace(voices, filt)


def register_timeline(events: list[tuple[int, int]], nframes: int) -> list[int]:
    """A sparse register's value on every frame 0..nframes-1.

    siddump prints a register only on the frame it is written; on every other
    frame the chip keeps whatever was latched, so the value carries forward.
    Before the first write (siddump always prints frame 0 in full, so in
    practice never) the value is 0.

    This is deliberately register-agnostic -- waveform, ADSR, pulse width,
    cutoff, $D417 and volume are all written sparsely by the same rule, so
    they all need exactly this expansion before they can be compared.
    """
    out: list[int] = []
    cur, idx = 0, 0
    for f in range(nframes):
        while idx < len(events) and events[idx][0] <= f:
            cur = events[idx][1]
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


def engine_freq_table(sid_path, opts: dict | None = None):
    """The frequency table of the player *this conversion* reads, or None.

    A file carrying two players carries two tables, and they need not be
    tuned alike: Powerplay Hockey's cue engine sits on the semitone grid and
    its tune engine 0.63 semitones below it, so which one names the original's
    notes decides whether a row reads 99% or 12%. `find_freq_table`'s own
    tie-break -- the longest validated run -- separates those two by one entry
    out of 96, which is not a choice. Pointing it at the player `opts` selects
    is (`--engine`; see sidfile.find_freq_table).

    The detection is re-run rather than threaded through from the conversion:
    it costs ~45 ms against a trace's seconds, and re-deriving the anchor by
    hand is the shape that has published three wrong readings here.
    """
    sid = load_sid(str(sid_path))
    near = None
    try:
        det = detect(sid, log=lambda m: None,
                     engine=int((opts or {}).get("engine") or 0))
    except Exception:                                          # noqa: BLE001
        det = None
    if det is not None:
        # The pattern pointers for preference -- the anchor `_nearest_table`
        # already uses -- with the instrument table as the fallback for a
        # detection that found one and not the other.
        for anchor in (det.pattern_lo, det.instr_start):
            if anchor and anchor > 0:
                near = anchor
                break
    return find_freq_table(sid, near=near)


def table_calibration(sid_path, opts: dict | None = None) -> tuple[int, object]:
    """(siddump -c value, the table it came from) for tracing the original.

    Only a table off the semitone grid needs this -- a shifted one is a
    converter defect and gets no allowance (see sidfile.find_freq_table).
    """
    ft = engine_freq_table(sid_path, opts)
    return (calibration(ft.detune) if ft and abs(ft.detune) > 0.2 else 0), ft


@functools.lru_cache(maxsize=None)
def _usage(exe: str) -> str:
    """siddump's own usage text, which it prints when given no filename."""
    try:
        proc = subprocess.run([exe], capture_output=True, text=True, timeout=30,
                              stdin=subprocess.DEVNULL)
    except (OSError, subprocess.SubprocessError):
        return ""
    return proc.stdout + proc.stderr


def supports_calls_per_frame(exe: str) -> bool:
    """Does this siddump build take -m (playroutine calls per frame)?

    Worth asking because siddump's option switch has no default case: an
    unknown letter is dropped without a word, so a stock binary handed -m2
    prints a trace that looks entirely normal and is half the tune. The usage
    text is the only thing that distinguishes the two builds.
    """
    return "-m<value>" in _usage(exe)


@functools.lru_cache(maxsize=None)
def reads_video_flag(sid: str) -> bool:
    """Does this file's code read $02A6, the KERNAL PAL/NTSC flag?

    Four of the 95 corpus files do, so demanding a -v-capable siddump for
    every trace would retire the stock binary for no gain. Demanding it for
    exactly these files removes the silent-NTSC hazard where it exists and
    nowhere else. Any absolute read counts: three of the four branch on the
    cell to skip frames, the fourth indexes tuning constants with it.
    """
    try:
        data = Path(sid).read_bytes()
    except OSError:
        return False
    FLAG_BYTES = bytes((0xA6, 0x02))
    reads = {0xAD, 0xAE, 0xAC, 0x2C, 0xCD, 0xEC, 0xCC,
             0x0D, 0x2D, 0x4D, 0x6D, 0xED}
    i = data.find(FLAG_BYTES)
    while i > 0:
        if data[i - 1] in reads:
            return True
        i = data.find(FLAG_BYTES, i + 1)
    return False


def supports_video_flag(exe: str) -> bool:
    """Does this build take -v (the value for $02A6, PAL/NTSC)?

    Same silent-drop hazard as -m and a worse failure: a dropped -v1 leaves
    the flag at 0, which is NTSC, and three corpus players branch on it to
    skip frames. The trace then looks entirely normal and is the wrong
    machine -- which is exactly how Phantoms_of_the_Asteroid was carried as a
    converter defect for several versions.
    """
    return "-v<value>" in _usage(exe)


def run_siddump(sid: Path, seconds: int, subtune: int,
                exe: str = SIDDUMP, calibrate: int = 0, calls: int = 1,
                video=_USE_DEFAULT, capture: list | None = None) -> Trace:
    """Trace `seconds` of real time, `calls` playroutine calls per frame.

    `calls` is the tune's call rate over 50Hz -- gt2reloc's -S multiplier for
    something this harness packed. A row is one PAL frame either way, so a
    multispeed trace lands on the same time axis as a single-speed one and the
    two stay comparable frame for frame. Without it siddump calls the play
    routine 50 times a second whatever the PSID speed field says
    (siddump.c:309/325), and a tune written to tick at 100Hz plays at half
    speed for the whole trace.
    """
    if video is _USE_DEFAULT:
        video = PAL_FLAG
    cmd = [exe, str(sid), f"-a{subtune}", f"-t{seconds}"]
    if calibrate:
        cmd.append(f"-c{calibrate:X}")
    if calls > 1:
        if not supports_calls_per_frame(exe):
            raise RuntimeError(
                f"{exe} does not support -m, so a tune at {calls} calls per "
                f"frame cannot be traced at its real rate. Build "
                f"python/tools/siddump-rt (see its README), or pass "
                f"--multiplier 1 to measure the whole corpus at 50Hz.")
        cmd.append(f"-m{calls}")
    if video is not None:
        if supports_video_flag(exe):
            cmd.append(f"-v{video}")
        elif reads_video_flag(str(sid)):
            # Only these files can be traced as the wrong machine, and for
            # them a silently dropped -v is a plausible, normal-looking,
            # wrong dump -- which is how Phantoms_of_the_Asteroid was carried
            # as a converter defect for several versions.
            raise RuntimeError(
                f"{Path(sid).name} reads $02A6 and {exe} does not support "
                f"-v, so the trace would be NTSC. Build "
                f"python/tools/siddump-rt (see its README), or pass --ntsc "
                f"to accept it.")
    proc = subprocess.run(cmd, capture_output=True, text=True, timeout=180,
                          stdin=subprocess.DEVNULL)
    if capture is not None:
        # The raw table, for callers that want to publish the evidence beside
        # the conclusion (instrmap.py) rather than only the parse of it.
        capture.append(" ".join(cmd))
        capture.append(proc.stdout)
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


def subtune_content_shas(blob: bytes) -> list[str] | None:
    """One sha1 per subtune: its own 3 orderlist tracks, plus the raw bytes of
    every pattern those tracks reach.

    `output_sha` (below) hashes the whole `.sng` and so cannot tell a change
    in one subtune's patterns from a change in another's -- exactly the gap
    that let a -38pp regression print "no dimension can see this change"
    (Star_Paws, boundary-tie-loop-around-restart-position): the differing
    bytes were in a subtune `--baseline` never traced. A pattern that
    several subtunes share is bytes those subtunes all fold into their own
    hash, so a change to it is correctly attributed to all of them, not just
    the one whose orderlist happens to name it first.

    Returns None on any malformed `.sng` -- a missing per-subtune diff must
    fall back to the file-wide reading, never be reported as "no change".
    """
    try:
        pos = HEADER_LEN
        n_subtunes = blob[pos]
        pos += 1
        tracks: list[bytes] = []
        for _ in range(n_subtunes * 3):
            n = blob[pos]
            pos += 1
            tracks.append(blob[pos:pos + n + 1])
            pos += n + 1

        n_instr = blob[pos]
        pos += 1 + n_instr * 25

        n_tables = 4 if blob[0:4] == b"GTS5" else 3
        for _ in range(n_tables):
            n = blob[pos]
            pos += 1 + 2 * n

        n_patt = blob[pos]
        pos += 1
        patterns: list[bytes] = []
        for _ in range(n_patt):
            rows = blob[pos]
            pos += 1
            patterns.append(blob[pos:pos + rows * 4])
            pos += rows * 4
    except IndexError:
        return None

    def referenced_patterns(track: bytes) -> set[int]:
        out: set[int] = set()
        operand = False
        for b in track:
            if operand:
                operand = False
            elif b == GT_ORDER_RESTART:
                operand = True
            elif b >= GT_REPEAT:
                continue  # repeat count (0xD0-0xDF) or transpose (0xE0-0xFE)
            else:
                out.add(b)
        return out

    shas = []
    for s in range(n_subtunes):
        voices = tracks[s * 3:s * 3 + 3]
        h = hashlib.sha1()
        for t in voices:
            h.update(t)
        refs: set[int] = set()
        for t in voices:
            refs |= referenced_patterns(t)
        for p in sorted(refs):
            if p < len(patterns):
                h.update(patterns[p])
        shas.append(h.hexdigest()[:12])
    return shas


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
             multiplier: int = 1, pulse_skip: bool = False) -> Path | None:
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

Stock siddump cannot see it. It calls the play routine `seconds * 50`
    times whatever the PSID speed field says (siddump.c:309/325), so the trace
    is identical with and without -S -- which is why every multiplier-2 song
    was measured at half speed until v0.5.96. `run_siddump(calls=multiplier)`
    against the tools/siddump-rt build closes that; the packed bytes here are
    unchanged either way.

    **`-O0` is passed unless `pulse_skip` says otherwise.** gt2reloc's
    pulse-optimization skipping is DEFAULT=on (readme:1225) and makes the packed
    player execute no pulse table on the note-fetch tick, so at tempo 3 the duty
    cycle advances on two calls in three where the player advances it every
    frame. Trans-Atlantic's lead covered 762 of the original's 1584 with it on
    and 1143 with it off. readme:1078-1081 already says to disable it for a fast
    tempo, and every row this converter emits is one player tick.

    Measured over the 74 files that pack: mean `pspan` 0.61x -> 0.65x, mean
    melody and mean `wave` unchanged to the decimal, no file losing melody --
    gains to +0.33 (Sanxion, Sigma Seven, Delta Mix-E-Load), worst loss -0.11
    (One Man and his Droid). It costs raster time on real hardware, which is
    what the optimization is for; `pulse_skip=True` restores it for an A/B.

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
    if not pulse_skip:
        args.append("-O0")
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


def _bend_travel(v: Voice) -> int:
    """How far this voice's frequency moves *within* notes, in SID units.

    The pitch counterpart of `cutoff_travel`, and it exists for the same
    reason: `slides` counts the frames on which the frequency moved and a count
    cannot judge a step size. Two conversions that bend the same note over the
    same frames score identically there whether each step is the player's or
    ten times it. `slides` counts siddump's bend lines; this sums them.

    **It is siddump's own number, not a difference of the frequency column,**
    and both earlier attempts to compute it here were wrong in the same
    direction:

    * differencing every frame counted a *tie* -- a note change with no
      re-gate -- as a bend, and reported Pygmies_Revenge (493 ties in ten
      seconds) as travelling 21.7 million units against about 12 thousand of
      real bending;
    * excluding attacks and ties still counted the **bare frequency writes** a
      note start makes on a frame of its own. A Goattracker wavetable entry
      whose right side is a relative note rewrites the frequency without
      touching the gate, and siddump prints that as a frequency with an empty
      note field -- so a jump between two notes was scored as a bend. That put
      Zoolook at 121,107 units where its printed bends total about 3,400.

    siddump prints `(+ xxxx)` / `(- xxxx)` exactly when the frequency moved and
    it judged the voice to be on the same note, which is the definition this
    dimension wants. Taking its number instead of re-deriving one removes both
    failures and the whole class they belong to.
    """
    return v.bend


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
            # .collapsed removes consecutive repeats -- see the module
            # docstring's "melody similarity" bullet. Read `.attacks`
            # (uncollapsed) here and this stops reproducing the report.
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
    ob = sum(_bend_travel(v) for v in orig)
    ub = sum(_bend_travel(v) for v in ours)
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
        # ... and how far that movement actually goes. siddump splits pitch
        # movement between two printed forms -- a bare delta and a parenthesised
        # note -- by whether the new frequency lands near a note in its table,
        # so a change in step *size* moves frames between the two buckets and
        # `slides` counts only one of them. v0.5.83's slide-dialect fix showed
        # exactly that: Flash_Gordon's slides fell 635 -> 266 while its ties
        # rose 181 -> 340 and its total pitch movement moved *toward* the
        # original. Travel is the measure that does not care which form
        # siddump chose.
        "orig_bend": ob,
        "our_bend": ub,
        "bend_ratio": (ub / ob) if ob else None,
        "voices": per_voice,
    }


def naming_split(orig: list[Voice], arm_a: list[Voice],
                 arm_b: list[Voice]) -> dict:
    """How much of a melody delta between two arms is RENAMING.

    A conversion option that moves `melody` can move it two ways, and they
    want opposite fixes: it can change WHICH notes are struck (a structural
    change), or it can leave the same notes and change what siddump CALLS
    them (a naming change, which may not be audible at all -- v0.5.427 found
    Powerplay's renamed attacks land on a pitch CLOSER to the original and
    score worse only because a quarter-tone crosses a naming boundary).

    The split is measured by REPAIR rather than by counting: align the two
    arms' attacks positionally, substitute arm A's names into arm B wherever
    an aligned pair disagrees, and re-score. Whatever the repair recovers was
    the naming half; whatever survives it was not.

    **`melody` comes from `compare()`, never from a reimplementation.** A
    hand-rolled per-voice weighting matched the harness on one arm BY LUCK and
    missed the other, which cost a run; the repaired arm is a `Voice` built
    with `dataclasses.replace`, whose `collapsed` is a property and so
    recomputes itself, and it goes back through `compare()` unchanged.

    **THE COUNT IS METHOD-DEPENDENT AND THE SHARE IS LESS SO.** How many
    renames you find depends entirely on how the two attack sequences are
    aligned -- the same file has been read as 3, 7 and 8 renames by three
    alignments, and on the FRAME axis rather than the sequence axis
    One_on_One reads 39% of its attacks renamed where difflib reads one
    (v0.5.436). `renames` below is therefore reported as the positional
    difflib count and must be quoted with that qualifier; `naming_share` is
    the number to reason with, because it is anchored on a re-score rather
    than on a tally.

    **AND THE THREE COUNTS ARE THREE COVERAGES OF ONE POPULATION, NOT THREE
    CRITERIA -- measured, not argued.** Powerplay's renames were censused
    independently by the `melody` Dimension at v0.5.434 as three pairs,
    `A#4->A-4` x4, `D-5->C#5` x2 and `G-5->F#5` x2: EIGHT attacks, and every
    pair exactly one semitone down. Read against that census:

        alignment                     pairs found            share
        ce27e41's positional difflib  A#4 x2, D-5 x1  = 3     67%
        this function (shipped)       A#4 x3, D-5 x2, G-5 x2 = 7   94%
        index-wise substitution       all 8                  100% by construction

    So 3, 7 and 8 are 3/8, 7/8 and 8/8 of ONE eight-attack population, and
    `rename_semitones` reads a single value, `-1`, on all of them. The 67%
    is therefore not a rival reading to reproduce -- it is the recovery of
    the alignment that paired the fewest of the same eight, and a target
    figure taken from it is a property of that alignment rather than of the
    file. **The 100% is the other end of the same artefact**: substituting by
    INDEX makes arm B equal arm A wherever the two overlap, so it recovers
    any loss whatever by construction and measures nothing.

    That is why this function reports `rename_pairs` and `rename_semitones`
    beside the share: the pairs make the population visible, and the
    distances say whether a substitution is the documented naming-boundary
    artefact (one semitone, a sub-semitone pitch shift crossing a note name)
    or a structural change this repair should never have credited to the
    naming half.
    """
    a_score = compare(orig, arm_a)["melody"]
    b_score = compare(orig, arm_b)["melody"]

    repaired: list[Voice] = []
    renames = 0
    pairs: dict[tuple[str, str], int] = {}
    for va, vb in zip(arm_a, arm_b):
        names = list(vb.attacks)
        sm = difflib.SequenceMatcher(a=va.attacks, b=vb.attacks,
                                     autojunk=False)
        for tag, i1, i2, j1, j2 in sm.get_opcodes():
            # Only equal-length replacements are RENAMES; an unequal span is
            # an insertion or a deletion wearing a replace opcode, and
            # substituting across it would repair a structural change and
            # credit it to the naming half.
            if tag != "replace" or (i2 - i1) != (j2 - j1):
                continue
            for k in range(i2 - i1):
                if names[j1 + k] != va.attacks[i1 + k]:
                    # Named in the direction the OPTION moved the pitch --
                    # arm A's name first -- so a row reads the way the melody
                    # Dimension's own census writes it (`A#4->A-4`).
                    key = (va.attacks[i1 + k], names[j1 + k])
                    pairs[key] = pairs.get(key, 0) + 1
                    names[j1 + k] = va.attacks[i1 + k]
                    renames += 1
        repaired.append(dataclasses.replace(vb, attacks=names))

    r_score = compare(orig, repaired)["melody"]
    loss = a_score - b_score
    recovered = r_score - b_score
    return {
        "melody_a": a_score,
        "melody_b": b_score,
        "melody_repaired": r_score,
        "loss": loss,
        "recovered": recovered,
        "renames": renames,
        # WHAT was substituted, not just how much. A share alone cannot say
        # whether a substitution is a naming-boundary artefact or a different
        # note, and the two want opposite fixes -- so report the pairs and how
        # far each moved. A gap of one semitone is the signature the melody
        # Dimension documents (a sub-semitone pitch shift crossing a naming
        # boundary); anything larger is structural and this repair should not
        # have credited it to the naming half.
        "rename_pairs": sorted(((a, b), n) for (a, b), n in pairs.items()),
        "rename_semitones": sorted(
            {_semitone(b) - _semitone(a) for a, b in pairs}),
        # None rather than a number when arm B did not lose: a share of a
        # non-loss is not meaningful, and returning 0.0 there would read as
        # "none of it was naming" rather than "there was nothing to split".
        "naming_share": (recovered / loss) if loss > 1e-12 else None,
    }


def naming_census_report(recs: list[dict]) -> str:
    """The naming/non-naming split, one row per file."""
    out = ["# Naming share of a melody delta", "",
           "Each row A/Bs one file's shipped preset against the same preset "
           "plus the forced option(s), and splits the `melody` difference "
           "into the half a RENAME repair recovers and the half it does not.",
           "",
           "`renames` is a POSITIONAL DIFFLIB count and is method-dependent -- "
           "the same file has been read as 3, 7 and 8 renames by three "
           "alignments, and on the frame axis One_on_One reads 39% of its "
           "attacks renamed where difflib reads one. Reason with "
           "`naming share`, which is anchored on a re-score rather than a "
           "tally.",
           "",
           "A substitution ONE SEMITONE wide is the artefact the `melody` "
           "Dimension documents -- a sub-semitone pitch shift crossing a "
           "note-naming boundary. A WIDER one is a different note, and "
           "crediting it to the naming half would be wrong, so `st` gives "
           "the distances and the pairs are listed under the table.",
           "",
           "| file | melody A | melody B | repaired | loss | recovered | "
           "naming share | renames | st |",
           "|---|---:|---:|---:|---:|---:|---:|---:|---:|"]
    for r in recs:
        if r.get("error"):
            out.append(f"| {r['file']} | {r['error']} | | | | | | | |")
            continue
        share = ("-" if r["naming_share"] is None
                 else f"{100 * r['naming_share']:.0f}%")
        out.append(
            f"| {r['file']} | {100 * r['melody_a']:.1f}% | "
            f"{100 * r['melody_b']:.1f}% | {100 * r['melody_repaired']:.1f}% | "
            f"{100 * r['loss']:+.2f}pp | {100 * r['recovered']:+.2f}pp | "
            f"{share} | {r['renames']} | "
            # `.get`, not `[]`: a record written before these fields
            # existed -- a hand-built rec, or a saved --json row -- must
            # still render rather than raise, the same fallback shape
            # `output_sha` and `subtune_shas` already use.
            f"{','.join(f'{v:+d}' for v in r.get('rename_semitones') or ()) or '-'} |")
    detail = [(r["file"], r["rename_pairs"]) for r in recs
              if r.get("rename_pairs")]        # absent on an older record
    if detail:
        out += ["", "## What was substituted", ""]
        for name, pairs in detail:
            listed = "  ".join(f"`{a}->{b}` x{n}" for (a, b), n in pairs)
            out.append(f"* **{name}** -- {listed}")
    return "\n".join(out) + "\n"


# Largest startup lag `startup_lag` will apply. A packed .sid takes a handful
# of frames to reach its first note that the original does not -- measured
# across the corpus the lag clusters at 3-8 frames and never legitimately
# exceeds ten. Chimera's raw lag is 438 (8.8 s), which is not a latency but an
# opening one side does not have; absorbing that into an alignment would hide a
# real defect and throw away a third of the window, so it is reported instead.
MAX_STARTUP_LAG = 25


def startup_lag(orig: list[Voice], ours: list[Voice]) -> tuple[int, int]:
    """(lag to apply, lag measured): frames our first note trails theirs by.

    Every per-frame agreement in this report walks the two traces frame against
    frame, and a packed `.sid` does not start where the original does: gt2reloc's
    player spends a few frames initialising before its first note. Commando's
    first attacks are at frame 8 where the original's are at frame 1, and that
    seven-frame constant was charged to the converter as disagreement -- `wave`
    read 65% for a file whose waveforms, once aligned, agree 92% of the time.
    It is why v0.5.174's drum fix looked like a 4.6pp regression while taking
    noise coverage from 49% to 92% of the original's frames.

    **Estimated, never fitted.** The lag is the difference between the two
    sides' first attack frames -- one number, from a defined signal. Searching
    the shift that maximises agreement would be a free parameter that can only
    raise the score, which is not evidence of anything. The estimator was
    validated against that search on 36 corpus files: it lands on the fitted
    optimum for 20 of them and gives a mean `wave` of 77.0% against the fit's
    77.1%, so the search buys a tenth of a point and costs the measure its
    meaning.

    Returns the applied lag clamped to +/-MAX_STARTUP_LAG and the raw one, so a
    row can say the two differ rather than quietly correcting by 438 frames.
    """
    fo = [min(v.attack_frames) for v in orig if v.attack_frames]
    fu = [min(v.attack_frames) for v in ours if v.attack_frames]
    if not fo or not fu:
        return 0, 0
    raw = min(fu) - min(fo)
    return max(-MAX_STARTUP_LAG, min(MAX_STARTUP_LAG, raw)), raw


def _aligned(ta: list[int], tb: list[int], lag: int) -> tuple[list, list]:
    """The two timelines with `lag` frames of our head (or theirs) dropped."""
    if lag > 0:
        return ta[:len(ta) - lag], tb[lag:]
    if lag < 0:
        return ta[-lag:], tb[:len(tb) + lag]
    return ta, tb


def _median_or_zero(vals: list[int]) -> int:
    """`presets._noise_pitch`'s reduction, spelled once.

    Not `statistics.median`: that averages the two middle values on an even
    count, and the value here is a REGISTER reading rather than a quantity to
    interpolate. The upper-middle element is what the search has always used,
    and `tests/test_fidelity.py` pins the two against each other -- a second
    copy of a reduction is exactly the hand-maintained duplicate this repo
    keeps being bitten by, so it is guarded rather than trusted.
    """
    return sorted(vals)[len(vals) // 2] if vals else 0


def wave_compare(orig: list[Voice], ours: list[Voice],
                 nframes: int | None = None, lag: int = 0) -> dict:
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
    # Pooled across voices and reduced ONCE at the end, never a median of
    # per-voice medians: `presets._noise_pitch` pools, and the whole point of
    # this field is that the two agree.
    o_pitch: list[int] = []
    u_pitch: list[int] = []
    per_voice = []
    for a, b in zip(orig, ours):
        # Noise is counted off the *unaligned* timelines: it is a one-sided
        # count of what each side does over its own window, and shifting one of
        # them would drop `lag` frames from that side's total only.
        ta = register_timeline(a.wf_events, nframes)
        tb = register_timeline(b.wf_events, nframes)
        vo_n = sum(1 for x in ta if x & WF_NOISE)
        vu_n = sum(1 for y in tb if y & WF_NOISE)
        # The noise PITCH, off the same UNALIGNED timelines and for the same
        # reason. Taken before the alignment below, which would drop `lag`
        # frames from one side only.
        fa = register_timeline(a.freq_events, nframes)
        fb = register_timeline(b.freq_events, nframes)
        o_pitch += [fa[f] for f in range(nframes) if ta[f] & WF_NOISE]
        u_pitch += [fb[f] for f in range(nframes) if tb[f] & WF_NOISE]
        ta, tb = _aligned(ta, tb, lag)
        va = vt = 0
        for x, y in zip(ta, tb):
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
        "wave_frames": round(total),
        "orig_noise_frames": o_noise,
        "our_noise_frames": u_noise,
        # 0 rather than None where a side sounds no noise at all, which is the
        # convention `presets._noise_pitch` already uses and which
        # `fidelity_better` reads as "nothing to compare" via its own
        # `cand[3][2] and cand[3][3]` guard.
        "orig_noise_pitch": _median_or_zero(o_pitch),
        "our_noise_pitch": _median_or_zero(u_pitch),
        "wave_voices": per_voice,
    }


def gate_compare(orig: list[Voice], ours: list[Voice],
                 nframes: int, lag: int = 0) -> dict:
    """Per-frame agreement of the GATE bit -- $D404 bit 0 -- and its direction.

    **The bit every other column here ignores.** `wave_compare` says so
    outright and gives a good reason: a gated-off voice keeps its waveform
    latched, so folding the gate into a timbre comparison would double-count
    every note-length disagreement as a wrong waveform. `hold` counts frames
    with a waveform *selected*, `adsr` reads the envelope registers, `tail`
    reads them after the gate closes. The consequence went unnoticed until
    v0.5.269: a change that only opens or closes the gate is invisible to the
    whole report, and `--rest-keyoff` -- 19 files' bytes -- moved one number
    on one file.

    **Scored over the frames that say anything.** Both sides hold the gate on
    for most of a tune, and counting those would put every file in the high
    nineties and move for nothing. This is the overlap of the *gate-off*
    frames -- `|both off| / |either off|`, the same Jaccard shape `pitch`
    uses -- so a conversion that never releases a note scores 0 and one that
    releases at the original's moments scores 1.

    **The direction is reported because the two errors have different fixes.**
    `gate_ours_ringing` is the original silent while we sustain, which is a
    missing note end (a rest we did not read, a release too long). Its
    opposite, `gate_ours_silent`, is a note we ended early or never played.

    Frames neither side has written at all are dropped, the rule
    `wave_compare` states for class 0: an idle voice reads `$00`, which is
    gate-off on both sides, and three silent voices would otherwise score a
    perfect trace.

    **What it can be gamed by**, stated here rather than found later: a
    conversion that plays *fewer notes* has more gate-off frames and can score
    higher for it, exactly as `wave` rises when attacks are deleted. Read it
    next to `retrig` and both sides' note counts, and never alone.

    Aligned by `lag` like the other per-frame columns, because a gate edge is
    an event in time and the packed player reaches its first note several
    frames after the original.
    """
    both = either = ringing = silent = 0
    per_voice = []
    for a, b in zip(orig, ours):
        ta = register_timeline(a.wf_events, nframes)
        tb = register_timeline(b.wf_events, nframes)
        ta, tb = _aligned(ta, tb, lag)
        vb = ve = vr = vs = 0
        for x, y in zip(ta, tb):
            # A voice neither side has ever written reads $00 on every frame,
            # which is "gate off" on both -- and would score as perfect
            # agreement for the whole trace. `wave_compare` drops the
            # equivalent frames for the same reason; without this a file with
            # one silent voice scored a third of its frames for free, and a
            # conversion that played nothing at all would have scored 1.00.
            if x == 0 and y == 0:
                continue
            ox, oy = not (x & 0x01), not (y & 0x01)
            if not (ox or oy):
                continue
            ve += 1
            if ox and oy:
                vb += 1
            elif ox:
                vr += 1                      # original silent, we sustain
            else:
                vs += 1                      # we are silent, original sounds
        per_voice.append({"gate": (vb / ve) if ve else None, "frames": ve,
                          "ringing": vr, "silent": vs})
        both += vb
        either += ve
        ringing += vr
        silent += vs
    return {
        "gate": (both / either) if either else None,
        "gate_frames": either,
        "gate_ours_ringing": ringing,
        "gate_ours_silent": silent,
        "gate_voices": per_voice,
    }


GATE_KINDS = ("retrigger", "matched", "short", "held")


def gate_runs(timeline: list[int]) -> list[tuple[int, int]]:
    """(start, length) of every stretch the voice is released.

    A frame the voice has never been written at all reads `$00`, which is
    gate-off and is not a release; `gate_compare` drops those for the same
    reason and so does this.
    """
    out, start = [], None
    for i, x in enumerate(timeline):
        released = x and not (x & 1)
        if released and start is None:
            start = i
        elif not released and start is not None:
            out.append((start, i - start))
            start = None
    if start is not None:
        out.append((start, len(timeline) - start))
    return out


def gate_census(orig: list[Voice], ours: list[Voice], nframes: int,
                lag: int = 0) -> list[dict]:
    """Every release the ORIGINAL makes, classified by what we did there.

    The `gate` column says the overlap is 39% corpus-wide; this says what the
    other 61% is, which is the difference between a number and a queue. One
    record per release the original makes, on the frames it makes it:

    * `retrigger` -- one frame long, the edge a player makes closing the gate
      at the end of an untied note where the next note follows immediately.
      **944 of the corpus's 46996, 2.0%**, and that share is a statement
      about the instrument rather than the players: siddump samples the
      registers once per frame, so a gate that falls and rises inside one
      frame leaves no edge at all, and only the edges that happen to span a
      frame boundary survive. `--vice` traces at 312 samples a frame and
      would fill this bucket properly. Two files I checked first read zero
      and I nearly wrote that down as the corpus figure.

      This bucket is also where a hand-rolled probe of mine put 170 of
      Zoolook's 210 releases, by tracing the *original* at `-m3` -- the
      multiplier belongs to our side only (`_measure` traces the original at
      `-m1`), and running a 50 Hz tune three times too fast manufactures
      exactly the short edges it then reported. Take the measurement from the
      tool.
    * `matched` -- longer than a frame, and we release for at least half of
      it. The rest is a rest on both sides.
    * `short` -- we release, but for less than half. A note whose end we place
      right and whose silence we cut short.
    * `held` -- we never release at all. This is the queue: the original rests
      and we sustain straight through it.

    Aligned by `lag`, like the column.
    """
    recs = []
    for v, (a, b) in enumerate(zip(orig, ours)):
        ta = register_timeline(a.wf_events, nframes)
        tb = register_timeline(b.wf_events, nframes)
        ta, tb = _aligned(ta, tb, lag)
        for start, length in gate_runs(ta):
            if start + length > len(tb):
                break                       # runs past the aligned window
            # `not (tb[i] & 1)` and **not** `tb[i] and not (tb[i] & 1)`:
            # a voice we have never written reads `$00`, which is no waveform
            # and no gate -- released, and silent. `gate_compare` scores that
            # as agreement, and the census has to say the same thing or it is
            # explaining a different number from the one printed. Copying the
            # nonzero guard from `gate_runs`, where it belongs (a voice the
            # *original* never plays is not a release it makes), put 8889
            # frames across 38 runs into `held` -- Pygmies Revenge's 1024,
            # Master of Magic's 768 -- every one of them a voice the original
            # had not entered and we had not either.
            ours_off = sum(1 for i in range(start, start + length)
                           if not (tb[i] & 1))
            if length == 1:
                kind = "retrigger"
            elif ours_off == 0:
                kind = "held"
            elif ours_off * 2 >= length:
                kind = "matched"
            else:
                kind = "short"
            recs.append({"voice": v + 1, "frame": start, "frames": length,
                         "ours_off": ours_off, "kind": kind})
    return recs


def gate_census_by_voice(recs: list[dict]) -> dict[int, dict[str, dict[str, int]]]:
    """Split census records the file-level table collapses -- by voice.

    Returns `{voice: {kind: {"runs": n, "frames": frames_we_ring}}}`, `voice`
    being the record's own 1-indexed field (already carried by every record
    since the census was written, and never read until now). Summing every
    voice's `frames` for a kind reproduces that kind's "frames we ring" total
    from the file-level table, because this is the same quantity
    (`frames - ours_off`) grouped one level finer rather than a different
    measurement.

    This is the fix for "a per-voice question can't be answered from the
    census": Auf Wiedersehen Monty's gate row reads voice 0 (`gate_voices`
    index) at 48.06%, voice 1 at 56.90%, voice 2 at only 15.08% -- and before
    this function existed, nothing could say *which* voice the file's 219
    `held` runs belonged to. Split, they are 67 / 46 / 106 (`voice` 1/2/3
    here, i.e. `gate_voices` index 0/1/2) -- voice 2 alone carries very nearly
    half of them, which is consistent with it being the one the gate column
    reads worst. Summed across all four kinds the three voices give
    336 + 473 + 455 = 1264 frames we ring, against that row's own
    `gate_ours_ringing` of 1266: the 2-frame gap is `gate_runs` dropping a
    release that starts inside the aligned window but extends past it
    (`# runs past the aligned window`, in `gate_census`) where `gate_compare`
    instead just stops at the shorter of the two zipped traces -- a boundary
    difference between the two reductions of the same signal, not a defect in
    the split.
    """
    out: dict[int, dict[str, dict[str, int]]] = {}
    for r in recs:
        by_kind = out.setdefault(r["voice"],
                                  {k: {"runs": 0, "frames": 0} for k in GATE_KINDS})
        cell = by_kind[r["kind"]]
        cell["runs"] += 1
        cell["frames"] += r["frames"] - r["ours_off"]
    return out


def gate_census_report(rows: list[dict]) -> str:
    """The gate census over a whole run -- a queue, not a measurement."""
    recs = [dict(r, file=row["file"]) for row in rows
            for r in row.get("gate_census") or []]
    files = sum(1 for r in rows if r.get("gate_census"))
    out = ["# Gate census", "",
           f"{len(recs)} release(s) the original makes, across {files} "
           "file(s), classified by what the conversion did on those frames. "
           "`retrigger` is the one-frame edge a player makes at the end of "
           "an untied note; it is a small share because siddump samples once "
           "a frame and an edge inside a frame leaves none. `short` is a "
           "release we make and cut off early; `held` is the queue -- the "
           "original rests and we sustain straight through it.", ""]
    if not recs:
        return "\n".join(out)
    counts = Counter(r["kind"] for r in recs)
    frames = Counter()
    for r in recs:
        frames[r["kind"]] += r["frames"] - r["ours_off"]
    out += ["| kind | runs | share | frames we ring |", "|---|---:|---:|---:|"]
    for k in GATE_KINDS:
        n = counts.get(k, 0)
        out.append(f"| {k} | {n} | {100 * n / len(recs):.1f}% | {frames[k]} |")
    out += ["", "## By voice", "",
            "A gate deficit is a per-voice question -- the table above sums "
            "over the whole file, and `gate`'s own per-voice split can read "
            "wildly different voices as one number (Auf Wiedersehen Monty: "
            "48.06% / 56.90% / 15.08%). Same reduction as the table above, "
            "one level finer; `voice` is 1-indexed (`gate_voices` index + 1).",
            "", "| voice | kind | runs | share | frames we ring |",
            "|---:|---|---:|---:|---:|"]
    by_voice = gate_census_by_voice(recs)
    for v in sorted(by_voice):
        v_total = sum(c["runs"] for c in by_voice[v].values())
        for k in GATE_KINDS:
            n = by_voice[v][k]["runs"]
            share = f"{100 * n / v_total:.1f}%" if v_total else "-"
            out.append(f"| {v} | {k} | {n} | {share} | "
                       f"{by_voice[v][k]['frames']} |")
    out += ["", "## Where the held ones are", "",
            "| file | voice | runs | frames | longest |",
            "|---|---:|---:|---:|---:|"]
    per = {}
    for r in recs:
        if r["kind"] != "held":
            continue
        e = per.setdefault((r["file"], r["voice"]), [0, 0, 0])
        e[0] += 1
        e[1] += r["frames"]
        e[2] = max(e[2], r["frames"])
    for (name, v), (n, f, longest) in sorted(per.items(), key=lambda kv: -kv[1][1]):
        out.append(f"| {name} | {v} | {n} | {f} | {longest} |")
    return "\n".join(out) + "\n"


# $D404 bit 0. Gate-off does not mean silent: it starts the release
# phase, which is still sounding -- see adsr_compare's census.
GATE_BIT = 0x01


def adsr_compare(orig: list[Voice], ours: list[Voice],
                 nframes: int, lag: int = 0) -> dict:
    """Per-frame, per-voice agreement of the envelope registers $D405/$D406.

    Built exactly like wave_compare: the ADSR pair is sparse, so each side's
    last written value is carried forward and the two per-frame views are
    compared value for value. The whole 16-bit pair is compared -- attack,
    decay, sustain and release are one envelope and a conversion that gets
    three of the four right is not playing the same sound.

    Frames where *both* sides read $0000 are left out of the denominator, the
    same rule wave_compare uses for class 0: a voice no player has ever given
    an envelope is not evidence either way. A frame where one side has an
    envelope and the other still reads zero counts as a disagreement.

    Gating is deliberately not consulted in the SCORE, and the reason first
    written here was wrong in a way worth keeping: it said the envelope of a
    silent frame "is still the envelope the next note will open with". It is
    not -- both players reload the pair from the instrument at the next
    gate-on (gplay.c:397-398, player.s:882-892), which is what
    `patterns.py:389-393` already says. The reason that survives is the second
    one: folding the gate in here would re-measure the note lengths the attack
    columns already measure.

    **A PROPOSAL TO DROP THE GATED-OFF FRAMES WAS REFUTED BY MEASURING IT, and
    the numbers are recorded because the proposal is a natural one to have
    again.** The argument was that AD governs nothing while the gate is off,
    so those frames are unhearable and flatter nothing by leaving. On
    5_Title_Tunes that happened to be true -- its differing register is AD,
    SR-only differs on 0 frames -- and generalising from it is the trap.
    Censused over all 83 convertible files, 243436 disagreeing frames:

        both sides gated off        71945   29.6% of the deficit
          release nibble the same   23281   32.4% of those -- inaudible
          release nibble DIFFERS    48664   67.6% of those -- AUDIBLE

    **Those figures are the harness's own, and a scratch probe got them
    wrong first** -- it read 78395/49000 because it traced a flat 60 s where
    `original_ended` shortens the window for Geoff Capes and Kings of the
    Beach, and Geoff Capes alone is 6915 gated-off frames of surplus loop.
    That is the standing rule about a probe re-deriving what the harness has
    already resolved, caught here by the shipped row disagreeing with the
    probe that motivated it. Take these from `adsr_gated_off` in the row.

    **A gate-off frame is not a silent frame**: gate-off begins the RELEASE
    phase, which is still sounding, and the release nibble is what governs it.
    Dropping all 71945 would discard 48664 frames of a real, audible
    difference -- the same shape as v0.5.200, where widening a window to a
    minimum "could not depend on which frame the player writes on" and
    silently scored every instrument as cut. Only 9.6% of the column's total
    deficit (23281 of 243436) is genuinely unhearable, and that is not enough
    to be worth a denominator that can only ever move the score upward.

    The split is REPORTED instead of acted on: `adsr_gated_off` and
    `adsr_gated_off_audible` ride in the row, so a reader can see how much of
    a given file's deficit is release-phase disagreement without trusting this
    paragraph. Battle of Britain is the case that decides it: 3717 of its
    gated-off frames carry 3030 that differ in release, and every one of them
    is a tail the two sides do not share.

    `lag` is the startup latency from `startup_lag`, applied for the reason
    given there: this walks the traces frame against frame, and a packed .sid
    reaches its first note a few frames after the original does.

    Baseline: v0.5.71 measured this by hand at 54.2% before its sustain-nibble
    and hard-restart fixes and 66.2% after, over the 83 convertible files.
    Both fixes are shipped and in `presets.json`'s `always` block, so this
    column reproducing the post-fix figure is the check that it measures the
    same thing. That baseline predates the alignment and so is not comparable
    to a figure taken with a nonzero lag.
    """
    agree = total = 0
    # Disagreeing frames where BOTH sides are gated off, and how many of those
    # differ in the release nibble. Counted rather than acted on -- see the
    # census above. The gate is $D404 bit 0, the bit gate_compare owns and
    # every other column here ignores.
    off = off_audible = 0
    per_voice = []
    for a, b in zip(orig, ours):
        ta, tb = _aligned(register_timeline(a.adsr_events, nframes),
                          register_timeline(b.adsr_events, nframes), lag)
        wa, wb = _aligned(register_timeline(a.wf_events, nframes),
                          register_timeline(b.wf_events, nframes), lag)
        va = vt = 0
        for x, y, ga, gb in zip(ta, tb, wa, wb):
            if x == 0 and y == 0:
                continue
            vt += 1
            if x == y:
                va += 1
            elif not ((ga or 0) & GATE_BIT) and not ((gb or 0) & GATE_BIT):
                off += 1
                if (x & 0x0F) != (y & 0x0F):
                    off_audible += 1
        per_voice.append({"adsr": (va / vt) if vt else None, "frames": vt})
        agree += va
        total += vt
    return {
        "adsr": (agree / total) if total else None,
        "adsr_frames": total,
        "adsr_voices": per_voice,
        "adsr_gated_off": off,
        "adsr_gated_off_audible": off_audible,
    }


# The ADSR bits an instrument key may be built from.
#
# `$D405/$D406` is a verbatim per-instrument copy of the record on the
# original's side and **not** on ours: `--cut-release` -- in `presets.json`'s
# `always` block -- zeroes the release nibble wherever the player ends a note
# by writing both envelope registers, and `--sustain-exact` off additionally
# clears the sustain's low bit. A key holding a field the conversion alters
# cannot match across the two sides, and the columns keyed this way were
# silently comparing a fraction of what they could: Las Vegas Video Poker
# joined **1** of the 6 envelope pairs its original sounds, so `onset` printed
# 100% and `hold` 0% from a single instrument.
#
# `release_tails` has masked from the start, because it *measures* the release
# and § 7.xxxx caught it that way. Three neighbours read that lesson,
# correctly concluded it did not apply to them -- they do not measure the
# release -- and kept a key the conversion rewrites underneath them. The rule
# is wider than the case that produced it: **a key must not contain a field
# the conversion alters, whether or not the column measures it.** Named here
# so there is one of it (§ 7.uuuuu).
INSTRUMENT_KEY_MASK = 0xFFF0


def instrument_key(adsr: int) -> int:
    """An ADSR pair reduced to the bits both sides are known to preserve."""
    return adsr & INSTRUMENT_KEY_MASK


def paired_keys(a: dict, b: dict) -> list[tuple[int, int]]:
    """(their key, our key) for every instrument the two sides share.

    **Exact first, masked only as a fallback, and only when unambiguous.**
    Keying both sides masked would recover the instruments `--cut-release`
    hides -- Las Vegas Video Poker joins 1 of 6 exactly and 6 of 6 masked --
    but it also merges instruments that genuinely differ only in their
    release: 126 of the corpus's 1323, 9.5%, with Thrust losing 6 of 22. That
    is trading one attribution error for another, and § 7.zzzz is what a
    merged key costs -- a modal shape taken over two instruments compares
    neither.

    So an exact match wins wherever there is one, and a masked match is taken
    only for keys left over on both sides and only where exactly one candidate
    remains. Instruments that really do differ only in release keep their own
    identity whenever the conversion preserved it.
    """
    pairs = [(k, k) for k in a if k in b]
    rest_a = [k for k in a if k not in b]
    rest_b = [k for k in b if k not in a]
    for ka in rest_a:
        hits = [kb for kb in rest_b
                if instrument_key(kb) == instrument_key(ka)]
        if len(hits) != 1:
            continue
        kb = hits[0]
        # ...and only if no *other* leftover of theirs wants the same one.
        if sum(1 for k in rest_a
               if instrument_key(k) == instrument_key(kb)) != 1:
            continue
        pairs.append((ka, kb))
    return pairs


def pitch_motion(voices: list[Voice], nframes: int) -> dict:
    """Pitch movement split into oscillation and travel, without a threshold.

    `slides` and `bend` lump every kind of pitch movement together, and on
    Commando *all* of it is vibrato: turning `--vibrato` off takes the slide
    count from 245 to zero, while `--slides` and `--effects` change it by nothing
    at all. So a corpus A/B that reads "slide count" is mostly ranking vibrato
    rates, which is not what it appears to be ranking -- the `-R0` decision in
    section 7.hhh was taken on exactly that confusion.

    The two are distinguishable without picking a threshold, because a vibrato
    *reverses* and a portamento does not:

        reversals   direction changes in the frame-to-frame pitch delta. An
                    oscillator's rate is proportional to this, so Goattracker's
                    realtime-effect skipping halves it.
        gross       total |delta| -- how far the pitch moves in all.
        net         |last - first| per note, summed -- how far it *gets*.

    `1 - net/gross` is then the share of movement that is back-and-forth: near 1
    for pure vibrato, near 0 for a clean slide. No cutoff anywhere.

    Frames within one of an attack are skipped. A note onset is a large pitch
    jump and would read as a reversal; unlike a fixed offset, though, dropping a
    frame here costs one sample of many rather than shifting the whole
    measurement (the mistake `noise_runs` exists to avoid).
    """
    reversals = gross = net = 0
    for v in voices:
        fq = register_timeline(v.freq_events, nframes)
        skip = set()
        for a in v.attack_frames:
            skip |= {a - 1, a, a + 1}
        atk = sorted(v.attack_frames)
        for j, a in enumerate(atk):
            nxt = atk[j + 1] if j + 1 < len(atk) else nframes
            seg = [fq[f] for f in range(a, min(nxt, nframes)) if f not in skip]
            if len(seg) < 2:
                continue
            deltas = [seg[k + 1] - seg[k] for k in range(len(seg) - 1)]
            gross += sum(abs(d) for d in deltas)
            net += abs(seg[-1] - seg[0])
            signs = [d > 0 for d in deltas if d]
            reversals += sum(1 for k in range(1, len(signs))
                             if signs[k] != signs[k - 1])
    return {"reversals": reversals, "gross": gross, "net": net,
            "oscillation": (1 - net / gross) if gross else None}


def pitch_motion_compare(orig: list[Voice], ours: list[Voice],
                         nframes: int) -> dict:
    """Our pitch oscillation *rate* over the original's, and both shares.

    The rate is the number that a call-skipping packer changes and that `slides`
    obscured: an oscillator dropped on one tick in three runs at two thirds
    speed, whatever its depth.
    """
    a, b = pitch_motion(orig, nframes), pitch_motion(ours, nframes)
    return {
        "orig_reversals": a["reversals"],
        "our_reversals": b["reversals"],
        "reversal_ratio": (b["reversals"] / a["reversals"]
                           if a["reversals"] else None),
        "orig_oscillation": a["oscillation"],
        "our_oscillation": b["oscillation"],
    }


def _median(values: list[float]) -> float | None:
    """Plain median, or None for an empty list.

    A median rather than a mean everywhere below, for `_drum_max_steps`'
    reason: one instrument's notes are a distribution, and a single note whose
    "oscillation" is really a portamento would drag a mean without bound.
    """
    if not values:
        return None
    s = sorted(values)
    n = len(s)
    return s[n // 2] if n % 2 else (s[n // 2 - 1] + s[n // 2]) / 2


def vibrato_records(sid_path) -> set[int] | None:
    """ADSR pairs of the records that carry a **non-zero vibrato byte**.

    The population `depth` is measured on, and the reason it is a separate
    function rather than an inline filter: a depth measured over *every*
    oscillating note is worthless, and that is not a hypothetical. A first
    pass without this restriction reported per-note "depths" of 273% and 397%
    of pitch -- those are portamento slides and drum sweeps, not vibrato --
    and its by-multiplier medians all sat at about 1.0, i.e. it announced that
    there is no problem. This is § "a discriminator is only meaningful on the
    population the behaviour occurs in", applied before the measurement rather
    than after it.

    The byte is read from the SID through `Detection`, not from our own
    output, so it is a fact about the *original* -- and one that survives our
    emitter declining a record. All three vibrato engines are covered, since
    they are mutually exclusive and each names one record offset:
    `vibrato_offset` ($78/$07 pair), `table_vibrato.offset` (LFO table) and
    `triangle_vibrato` (bare right-shift count).

    The key is `(record+3 << 8) | record+4`, the ADSR pair the player stores
    verbatim into $D405/$D406 -- the same join key every other census here
    uses, and the one the trace can be read back on. Two records sharing a
    pair are a known ambiguity (§ 7.zzzz); they widen the population by one
    instrument rather than mis-attributing a number, which is the safe
    direction for a filter.

    **A vibrato byte is necessary and not sufficient**, which is the second
    thing measurement said rather than argument. Restricting on the byte alone
    put Commando at an "orig depth" of 59% of pitch and Zoids at 67% -- eight
    semitones and an octave, which no vibrato is -- because a record may carry
    a vibrato byte *and* a drum or an arpeggio, and then the half-cycles
    measured are the other mechanism's. So a record whose `+7` sets any bit
    **this player** reads as a pitch mover (`pitch_effect_bits`, which is the
    same per-player table `vib_census` attributes with) is excluded too: on
    Commando that is 4 records of 7, and its depth falls to a figure a vibrato
    can actually be.

    Returns **None**, not an empty set, where the population cannot be
    established -- detection failed, or the player has no vibrato routine at
    all. `depth_compare` then declines rather than falling back to the
    unrestricted reading the first pass proved worthless.
    """
    try:
        sid, det = _detect_tables(load_sid(str(sid_path)), lambda *a, **k: None)
    except Exception:                                          # noqa: BLE001
        return None
    if det.vibrato_offset is not None:
        offset = det.vibrato_offset
    elif det.table_vibrato is not None:
        offset = det.table_vibrato.offset
    elif det.triangle_vibrato is not None:
        offset = det.triangle_vibrato
    else:
        return None
    if det.instr_start < 0 or det.instr_used <= 0:
        return None
    # The player's own reading of its effect byte, not a fixed table: `$01` is
    # a drum in one dialect and a wave-program selector in another, and `$04`
    # is an arpeggio in some players and a two-stage *waveform* in others --
    # ACE_II's three vibrato records all carry `$04` and none of them moves a
    # pitch with it.
    competing = 0
    for bit in pitch_effect_bits(sid_path, det):
        competing |= bit
    data = sid.data
    keys: set[int] = set()
    for i in range(det.instr_used):
        base = det.instr_start + i * det.instr_stride
        if base + max(offset, 7) >= len(data):
            continue
        if data[base + offset] and not data[base + 7] & competing:
            keys.add((data[base + 3] << 8) | data[base + 4])
    return keys or None


def vibrato_swings(seg: list[int]) -> list[tuple[float, float]]:
    """`(peak-to-peak swing, centre frequency)` for each full cycle in `seg`.

    The excursion an oscillator reaches -- the quantity `vib` cannot see,
    because `vib` counts the turning points and says nothing about how far
    apart they are.

    **Taken over three consecutive turning points, not two, so a slide under
    the vibrato cancels exactly.** For extremes `p`, `q`, `r` the reading is
    `|2q - p - r| / 2`. On a pure oscillation of peak-to-peak `A` that is `A`;
    add any *linear* drift `d` per half-cycle -- a portamento, a wave
    program's slide, a drum's sweep -- and `p, q, r` become `0, A + d, 2d`,
    where the same expression still gives `A`. The obvious two-point reading
    `|q - p|` gives `A + d` instead, and this project has already learnt once
    that a measure which cannot separate a vibrato from a portamento ends up
    ranking the wrong one (`slides`, section 7.hhh).

    **Only interior cycles count.** The stretch from the segment's start to
    its first turning point, and from its last to the end, are cut by the note
    boundary and understate the swing -- the same rule, for the same reason,
    as `noise_runs` dropping a run that touches the window edge. Requiring
    three extremes rather than two is the same rule applied once more.

    Zero deltas do not end a half-cycle: a frequency held for a frame is the
    same direction of travel resumed, and treating a flat frame as a reversal
    would halve every swing on a slow oscillator.
    """
    turns: list[int] = []
    last = 0
    for k in range(len(seg) - 1):
        d = seg[k + 1] - seg[k]
        if not d:
            continue
        s = 1 if d > 0 else -1
        if last and s != last:
            turns.append(k)          # seg[k] is the extreme itself
        last = s
    out = []
    for i in range(len(turns) - 2):
        p, q, r = (seg[turns[i]], seg[turns[i + 1]], seg[turns[i + 2]])
        out.append((abs(2 * q - p - r) / 2, (p + 2 * q + r) / 4))
    return out


def oscillation_depths(voices: list[Voice], nframes: int,
                       keys: set[int] | None = None) -> dict:
    """`{ADSR: median cycle swing, as a fraction of the pitch}`.

    **Segmented on gate rising edges** -- `Voice.attack_frames`, the frames
    siddump prints a bare note on (siddump.c:376-380) -- and never on note
    *names*. siddump names the frequency's nearest note, which flickers up and
    down while a vibrato runs, so segmenting on the printed name chops one
    note into fragments shorter than a half-cycle: the first attempt at this
    measurement found **one** measurable note in 3000 frames that way.

    Expressed as a fraction of the frequency the swing happens around, so an
    instrument's depth is comparable across the pitches it plays and across
    two tunings -- a raw unit count is a semitone at one octave and two at the
    next.

    The same attack-adjacent frame skip as `pitch_motion` and
    `reversals_by_instrument`: a note onset is a large jump and would read as
    a turning point. Sharing the skip is deliberate -- this reads the same
    segments the rate columns read, so a disagreement between `depth` and
    `vib` is about the two statistics and not about two different populations.

    `keys` restricts to the instruments that carry the mechanism (see
    `vibrato_records`); the mask is applied through `instrument_key` as well
    as exactly, because `--cut-release` rewrites the release nibble on our
    side and an exact-only filter would drop every instrument whose release
    the conversion changed.
    """
    masked = {instrument_key(k) for k in keys} if keys is not None else None
    pooled: dict = {}
    for v in voices:
        fq = register_timeline(v.freq_events, nframes)
        adsr = register_timeline(v.adsr_events, nframes)
        skip = set()
        for a in v.attack_frames:
            skip |= {a - 1, a, a + 1}
        atk = sorted(v.attack_frames)
        for j, a in enumerate(atk):
            key = adsr[a] if a < nframes else 0
            if keys is not None and key not in keys \
                    and instrument_key(key) not in masked:
                continue
            nxt = atk[j + 1] if j + 1 < len(atk) else nframes
            seg = [fq[f] for f in range(a, min(nxt, nframes)) if f not in skip]
            for swing, centre in vibrato_swings(seg):
                if centre > 0:
                    pooled.setdefault(key, []).append(swing / centre)
    return {k: m for k, vals in pooled.items()
            if (m := _median(vals)) is not None}


def depth_compare(orig: list[Voice], ours: list[Voice], nframes: int,
                  keys: set[int] | None = None) -> dict:
    """How deep our vibrato swings, over the original's.

    `vib` is a *count* of pitch reversals -- the rate -- and this project has
    a standing rule that a count cannot answer a question about a step
    **size** (`cut` exists beside `filt`, and `bend` beside `slides`, for
    exactly this). The vibrato was the last mechanism with no travel measure
    next to its count, and the gap was not academic: a listener reported ACE
    II's lead as under-vibratoed, `vib` read 1.09x for that file, and the
    swing measured 1.6% of pitch against the original's 5.6%.

    Per instrument first, then the median of the per-instrument ratios --
    **not** a ratio of pooled swings. Depth is a property of an instrument, so
    pooling would let whichever instrument plays the most notes speak for the
    file, and the corpus's vibrato instruments differ in depth by an order of
    magnitude within one tune.

    Read it in log space, as every `x`-suffixed column here is read: 0.42 and
    2.4 are the same size of wrong.

    **THIS FUNCTION HAS TWO REFUSALS AND THE REPORT CANNOT TELL THEM APART.**
    Both return `{}`, so both print `-`; they are completely different
    findings. Measured over `build/fidelity.json` at v0.5.467 -- **10 of 89
    measured rows are null**, and they split **7 / 3**:

    * **NO POPULATION (7): `vibrato_records` returns nothing**, so no record in
      the ORIGINAL carries a vibrato byte and there is nothing to measure. `-`
      is the correct and honest answer. All six interleaved-classic files are
      here -- Radio_ACE, Lion_Heart, Lakers_vs_Celtics, Pacific_Coast,
      Go_Go_Dash, Sun_Never_Shines -- plus Kings_of_the_Beach_ingame. For the
      ILV six this is a statement about the DIALECT: none of the three vibrato
      engines (`vibrato_offset`, `table_vibrato`, `triangle_vibrato`) matches
      it, so if the interleaved player oscillates at all, nothing here reads
      it.
    * **NO PAIRS (3): the population EXISTS and the comparison fails** --
      5_Title_Tunes (6 keys), Commodore_64_Music_Examples (9) and BMX_Kidz
      (2). Records carry the byte, but no instrument key survives
      `paired_keys` with a positive original depth. That is the same shape as
      Powerplay Hockey's `-` in `onset`/`nrun`/`hold`/`tail` (§ 7.iiiii): a
      dash meaning "no shared key", which was a real defect there.

    So only the second group is a candidate for work, and it is three files
    rather than ten. `tests/test_fidelity.py` pins the split so it cannot
    drift silently; a future ILV vibrato decode should move six rows out of
    the first group and will fail that test deliberately.
    """
    if not keys:
        # No population, no measurement. See vibrato_records. NOTE this is
        # NOT the same as the `not pairs` refusal below -- see the docstring.
        return {}
    a = oscillation_depths(orig, nframes, keys)
    b = oscillation_depths(ours, nframes, keys)
    pairs = [(o, u) for o, u in paired_keys(a, b) if a[o] > 0]
    if not pairs:
        return {}
    return {
        "depth_ratio": _median([b[u] / a[o] for o, u in pairs]),
        "orig_depth": _median([a[o] for o, _ in pairs]),
        "our_depth": _median([b[u] for _, u in pairs]),
        "depth_instruments": len(pairs),
    }


def depth_census(orig: list[Voice], ours: list[Voice], nframes: int,
                 keys: set[int] | None = None,
                 stamps: dict | None = None) -> list[dict]:
    """Per-instrument rows behind `depth`, on the same population and pairing.

    Same reduction the column scored, for `onset_census`' reason: a second
    pipeline could resolve a different subtune and then disagree with the
    report for a reason that has nothing to do with the conversion.
    """
    if not keys:
        return []
    a = oscillation_depths(orig, nframes, keys)
    b = oscillation_depths(ours, nframes, keys)
    out = []
    for o, u in paired_keys(a, b):
        rec = {"adsr": o, "orig_depth": a[o], "our_depth": b[u],
               "ratio": (b[u] / a[o]) if a[o] else None}
        rec.update(stamp_for(stamps, o))
        out.append(rec)
    return sorted(out, key=lambda r: r["adsr"])


def noise_runs(voices: list[Voice], nframes: int) -> dict:
    """Maximal runs of noise, keyed by the ADSR latched while each one played.

    **Position-independent, which is the whole point.** Every other reading of
    the drum in this project anchors on siddump's gate-edge attack and asks what
    the waveform is at `a + k`. That anchor moves when the run's *length*
    changes -- shortening a drum's noise tick shifts five corpus instruments'
    runs from `a+1` to `a+0` -- so two settings get measured on different
    populations and their agreement rates are not comparable. Four separate
    boundary errors in one session came from this: GT 4's "one frame short" (the
    next note's `$09`), the drum's frames 1-2 against the routine's "first vbl"
    (the init path writing `$D404` after it), and the tick comparison twice.

    A run's length does not depend on where the run begins. So this finds
    maximal stretches of `$D404 & $80` and records how long each is, with no
    note boundary involved at all.

    Two rules that keep it honest:

    * a run touching frame 0 or the last frame is **dropped** -- it is cut by
      the window, and its length is a fact about the window;
    * attribution is the ADSR at the run's *midpoint*, not its start. The ADSR
      pair is a verbatim per-instrument copy (see `instrmap.py`), and the
      midpoint is inside the note however the run sits within it.

    Returns `{adsr: Counter({run_length: count})}`.
    """
    out: dict = {}
    for v in voices:
        wf = register_timeline(v.wf_events, nframes)
        adsr = register_timeline(v.adsr_events, nframes)
        f = 0
        while f < nframes:
            if not wf[f] & WF_NOISE:
                f += 1
                continue
            start = f
            while f < nframes and wf[f] & WF_NOISE:
                f += 1
            if start == 0 or f >= nframes:
                continue                      # cut by the window
            key = adsr[(start + f - 1) // 2]
            out.setdefault(key, Counter())[f - start] += 1
    return out


def release_tails(voices: list[Voice], nframes: int) -> dict:
    """The release nibble in force after each note ends, keyed by instrument.

    What this exists for: Hubbard's classic player ends an untied note by
    gating off **and writing AD = 0, SR = 0** (Commando $517C, on status bit 5
    being clear -- 91% of 53308 notes across the 72 classic-dialect files). The
    envelope is killed, so the note stops dead and the record's release nibble
    is never audible. This writer copies that nibble into the Goattracker
    instrument, where it *is* audible: 1298 of 1723 records carry a non-zero
    one, and with `$5F` on Commando's lead every note of a staccato figure
    rings through the gap that should separate it from the next.

    No existing dimension can see this. `adsr` compares the pair while a note
    plays, which agrees -- both sides write `295F` at the attack. `wave` and
    `nrun` read $D404, and both sides gate off on the same frame. What differs
    is only what the envelope does *after* the gate closes, and the report has
    never had a column for it (CLAUDE.md: it cannot see note length).

    **Read on the gate-off frame, and v0.5.200 got this wrong.** The first
    version took the *minimum* over the whole gap to the next note, reasoning
    that a minimum cannot depend on which frame the player writes on. It cannot,
    but it also cannot tell this note's cut from the *next note's* preparation:
    on Commando, records 3 and 4 hold their release for two frames and only then
    see a zero that belongs to the following note, and records 1, 7 and 12 never
    zero within the gap at all yet reached 0 somewhere later in it. The gap
    reduction scored all seven instruments as cut, the writer zeroed all seven
    releases, and the drums lost their tails -- a listener heard it immediately.

    The cut is a single write on the gate-off frame itself, so that is the frame
    to read. This is not the fixed-offset-from-an-attack mistake `noise_runs`
    warns about: nothing here is a duration, and the frame is the edge itself
    rather than an offset from it. **Widening a window is not automatically the
    safer reduction** -- it can admit a different event entirely.

    Attribution is the ADSR at the preceding run's midpoint, as in
    `noise_runs`: the pair is a verbatim per-instrument copy (`instrmap.py`)
    and the midpoint is inside the note however the run sits in it. It has to
    be read there rather than in the gap, because in the gap it is exactly the
    thing being measured -- **and the release nibble is masked out of the key
    for the same reason.** The first version keyed on the whole pair, so
    emitting a zero release moved every one of our keys from `295F` to `2950`,
    no instrument was shared with the original, and the column reported
    "nothing to compare" for the change it exists to measure. An attribution
    key must not contain the quantity being attributed.

    Returns `{adsr: Counter({release_nibble: count})}`.
    """
    out: dict = {}
    for v in voices:
        wf = register_timeline(v.wf_events, nframes)
        adsr = register_timeline(v.adsr_events, nframes)
        runs = []
        f = 0
        while f < nframes:
            if not wf[f] & WF_GATE:
                f += 1
                continue
            start = f
            while f < nframes and wf[f] & WF_GATE:
                f += 1
            runs.append((start, f))
        for i, (start, end) in enumerate(runs):
            if start == 0 or end >= nframes:
                continue                      # cut by the window
            nxt = runs[i + 1][0] if i + 1 < len(runs) else nframes
            if nxt >= nframes:
                continue                      # the tail runs past the window
            key = instrument_key(adsr[(start + end - 1) // 2])
            out.setdefault(key, Counter())[adsr[end] & 0x0F] += 1
    return out


def release_tail_agreement(orig: list[Voice], ours: list[Voice],
                           nframes: int) -> dict:
    """Instruments whose notes end with the same release as the original's.

    Per instrument and only where both sides have note ends to compare, on the
    same footing as `noise_run_agreement`: an instrument we drop entirely is
    absent rather than counted wrong, because that is a different defect and
    `melody` already reports it.
    """
    a, b = release_tails(orig, nframes), release_tails(ours, nframes)
    shared = paired_keys(a, b)
    matched = sum(1 for ka, kb in shared
                  if a[ka].most_common(1)[0][0] == b[kb].most_common(1)[0][0])
    longer = sum(1 for ka, kb in shared
                 if b[kb].most_common(1)[0][0] > a[ka].most_common(1)[0][0])
    return {
        "release_tail_instruments": len(shared),
        "release_tail_matched": matched,
        "release_tail_agreement": (matched / len(shared)) if shared else None,
        "release_tail_ours_longer": longer,
    }


# How many frames of a note's opening the `onset` dimension compares. Short on
# purpose: the defect it exists for is a one-frame shift at the attack, and a
# longer window starts charging for note *length*, which is a different thing
# and one this window is the wrong instrument for -- `hold` is the column that
# measures it.
ONSET_FRAMES = 4


def _wave_class(wf: int) -> int:
    """A frame's waveform class, `wave_compare`'s definition exactly.

    The select nibble alone (`wf & $F0`), gate and the other control bits
    ignored -- deliberately the *same* reduction the `wave` column uses, so
    `onset` and `wave` cannot disagree about what a frame's timbre is and then
    be read against each other. A second notion of "class" here is how two
    columns start telling different stories about one register.
    """
    return wf & 0xF0


def onset_shapes(voices: list[Voice], nframes: int) -> dict:
    """The waveform classes a note opens on, keyed by the instrument playing it.

    **The gap this fills.** `wave` averages per-frame waveform agreement over
    the whole window, so a wrong opening frame on an instrument with 43 notes
    is a rounding error against 3000 frames. `nrun` compares the *lengths* of
    noise runs and is deliberately position-independent, so a run that is right
    but starts a frame early scores perfect. Neither can see a mechanism
    emitted one frame out of phase -- and two emitters were, for as long as
    they had existed: the player writes the record's own waveform on a note's
    first frame and reaches the effect only on the second, where
    `_wave_program_entries` and `_two_stage_entries` both opened on the effect.
    On Trans-Atlantic that put GT 3 at `noise tri pulse noise` against the
    original's `tri noise tri pulse`, with `wave` at 63% either way.

    Keyed by the ADSR pair latched one frame *after* the attack, which is
    `instrmap.py`'s rule and for its reason: the attack frame can still hold a
    hard restart's envelope, which belongs to the player's transition rather
    than to the instrument. The key is $D405/$D406 and the measured value is
    $D404, so the two cannot contaminate each other -- the trap `release_tails`
    fell into by keying a release measurement on the pair containing it.

    A note whose window runs past `nframes` is dropped: what that would measure
    is the distance to the end of the trace.

    **No startup-lag correction, and none is wanted.** Every per-frame column
    here compares frame k to frame k and so has to be shifted by the packed
    player's 3-8 frame latency first. This reads each side at its *own* attack
    frames, so that latency cancels by construction -- the same property that
    makes `noise_runs` position-independent. Passing a lag in would move our
    reads off our own attacks and manufacture the phase error it is meant to
    detect.

    Returns `{adsr: Counter({(class, ...): count})}`.
    """
    out: dict = {}
    for v in voices:
        wf = register_timeline(v.wf_events, nframes)
        adsr = register_timeline(v.adsr_events, nframes)
        for a in v.attack_frames:
            if a < 0 or a + ONSET_FRAMES > nframes:
                continue                      # cut by the window
            shape = tuple(_wave_class(wf[a + k]) for k in range(ONSET_FRAMES))
            out.setdefault(adsr[min(a + 1, nframes - 1)],
                           Counter())[shape] += 1
    return out


def onset_shift(orig: tuple, ours: tuple) -> str | None:
    """`"early"`, `"late"` or None: whether one frame of shift explains a shape.

    A shape that is the original's sequence one frame out is a phase error
    rather than a wrong waveform, and the two have completely different fixes:
    section 7.www moved two emitters by a frame and left the waveforms alone.

    **The direction is easy to write backwards, so read it off an example.**
    `ours == orig[1:]` means we never played the original's first frame -- we
    are a frame ahead of it, i.e. EARLY. Trans-Atlantic's GT 3 is exactly this:
    the original opens `tri noise tri pulse` and we open `noise tri pulse
    noise`, because the player writes the record's own waveform on the note's
    first frame and our wavetable opened on the effect instead.

    **A shift only counts where the unshifted reading does not already fit.**
    On a shape the original holds constant, `ours[:-1] == orig[1:]` is true of
    any shape agreeing in its first three frames, so a note of ours that simply
    *ends* inside the window -- `noi noi noi --` against `noi noi noi noi` --
    read as a one-frame phase error, and three of the corpus's six did. That is
    a note-length difference, which is a different defect in a different place
    and the one `hold` measures; `classify_onset` calls it `short`. The
    inequality is what distinguishes evidence of a shift from a shift that
    explains nothing.
    """
    if orig == ours:
        return None
    head = ONSET_FRAMES - 1
    if ours[:head] == orig[1:] != orig[:head]:
        return "early"
    if ours[1:] == orig[:head] != orig[1:]:
        return "late"
    return None


def onset_agreement(orig: list[Voice], ours: list[Voice],
                    nframes: int) -> dict:
    """Instruments whose notes open on the original's waveform sequence.

    Per instrument and only where both sides have onsets to compare, the same
    footing as `noise_run_agreement` and `release_tail_agreement`: an
    instrument we drop entirely is absent here rather than counted wrong,
    because `melody` already reports that and counting it twice would let one
    defect move two columns.

    `onset_first_matched` is reported beside the whole-shape figure because the
    two answer different questions -- "does the note start on the right
    waveform" and "does the whole opening line up" -- and a fix that corrects
    the first frame while leaving the rest shifted would move only the former.
    """
    a = onset_shapes(orig, nframes)
    b = onset_shapes(ours, nframes)
    shared = paired_keys(a, b)
    modal = {ka: (a[ka].most_common(1)[0][0], b[kb].most_common(1)[0][0])
             for ka, kb in shared}
    matched = sum(1 for k, _ in shared if modal[k][0] == modal[k][1])
    first = sum(1 for k, _ in shared if modal[k][0][0] == modal[k][1][0])
    early = sum(1 for k, _ in shared if onset_shift(*modal[k]) == "early")
    late = sum(1 for k, _ in shared if onset_shift(*modal[k]) == "late")
    # **Graded, and the ungraded form is not a substitute.** `onset_agreement`
    # demands the whole four-frame shape, which is the right thing for the
    # report -- it says "this instrument opens correctly" and nothing weaker.
    # It is the wrong thing for a *scorer*: Sigma Seven's $0FFD goes from no
    # attack transient at all to one a frame too long, a large real gain that
    # exact matching scores as zero, and `onset_first_matched` cannot see it
    # either because frame 0 already agreed both times. This counts frames.
    graded = sum(sum(1 for x, y in zip(*modal[k]) if x == y) / ONSET_FRAMES
                 for k, _ in shared)
    return {
        "onset_instruments": len(shared),
        "onset_matched": matched,
        "onset_agreement": (matched / len(shared)) if shared else None,
        "onset_frame_agreement": (graded / len(shared)) if shared else None,
        "onset_first_matched": first,
        "onset_ours_early": early,
        "onset_ours_late": late,
    }


# The kinds an onset disagreement can be. Ordered as the report prints them:
# the match first, then the two that name a fix, then the three that are
# emitter quality.
ONSET_KINDS = ("match", "phase", "short", "flat", "invented",
               "partial", "wrong")

_CLASS_NAMES = ((0x80, "noi"), (0x40, "pul"), (0x20, "saw"), (0x10, "tri"))


def class_name(w: int) -> str:
    """A waveform class as a name. `_wave_class`'s output, not a raw byte."""
    names = [n for bit, n in _CLASS_NAMES if w & bit]
    return "+".join(names) if names else "--"


def shape_name(shape) -> str:
    return " ".join(class_name(w) for w in shape)


def classify_onset(orig: tuple, ours: tuple) -> str:
    """Which *kind* of disagreement two modal onset shapes are.

    `onset` reports a rate, and a rate says how much is wrong without saying
    what to do about it. These kinds separate fixes that have nothing to do
    with each other:

    * `flat` -- our note holds one waveform where the original's moves. A
      mechanism we do not render at all, and the group to go and read the 6502
      for. Grouped by the record's effect byte, this is a work list: the
      grouping is what turned "18% disagree" into "$01 x19, $04 x11, $80 x6,
      $0A x6" and emptied the last of those within a session (v0.5.231).
    * `phase` -- the original's sequence, one frame out. The emitter exists and
      is misplaced; section 7.www is what that fix looks like. `onset_shift` is
      the test, shared with the report's own `onset_ours_early`/`_late` so that
      the two readings of one corpus cannot drift apart.
    * `short` -- our note stops selecting a waveform inside the window while
      the original still does. A note-*length* difference, not the
      missing-mechanism defect the others are. It was the one thing no column
      measured when this kind was written (v0.5.234); `sound_runs` and the
      `hold` column are that observation as a measurement (v0.5.196), and
      `--hold-census` classifies the same population by cause.
    * `invented`, `partial`, `wrong` -- we move where the original holds, or we
      move differently. Emitter quality rather than a missing mechanism.

    **Order matters and `phase` is first**, because a genuine one-frame shift
    can also satisfy a later definition -- and the shift is the more specific
    claim. `short` is tested next for the same reason: a note that ends inside
    the window otherwise reads as `invented`, which would send the reader
    looking for a mechanism we render and the original does not, when what is
    wrong is how long the note lasts.
    """
    if orig == ours:
        return "match"
    if onset_shift(orig, ours):
        return "phase"
    if any(u == 0 and o for o, u in zip(orig, ours)):
        return "short"
    if len(set(ours)) == 1 and len(set(orig)) > 1:
        return "flat"
    if len(set(orig)) == 1 and len(set(ours)) > 1:
        return "invented"
    if any(x == y for x, y in zip(orig, ours)):
        return "partial"
    return "wrong"


def instrument_stamps(sng: bytes) -> dict:
    """`{ADSR: {"gt": n, "effect": b7}}`, read back out of the file we shipped.

    An instrument's *name* in a converted `.sng` is the converter's own
    provenance stamp, `NN:b5-b6-b7`, so the source record's effect byte is
    recoverable from the output without re-running detection. Parsed by
    `songview.parse_sng` -- a second reader of the format, checked against
    `build_sng` by `tests/test_songview.py` -- and imported here rather than at
    module scope because songview imports this module.

    The join key is the ADSR pair, for `onset_shapes`' reason: it is a verbatim
    per-instrument copy of the record. Two instruments can still share one, and
    where they do the entry says so rather than silently naming the first --
    the effect byte would then be a guess about which of them the trace heard.
    """
    from songview import parse_sng
    out: dict = {}
    for ins in parse_sng(sng).instruments:
        key = (ins.ad << 8) | ins.sr
        if key in out:
            out[key]["ambiguous"] = True
            continue
        out[key] = {"gt": ins.number, "effect": ins.effect_byte}
    return out


def onset_census(orig: list[Voice], ours: list[Voice], nframes: int,
                 stamps: dict | None = None) -> list[dict]:
    """Every instrument `onset` compared, with the kind of its disagreement.

    Same population and same modal reduction as `onset_agreement` -- the
    instruments both sides sound -- so the counts here add up to that column's
    denominator and its `match` count is that column's numerator. It is a
    classification of the same comparison, not a second measurement of it.
    """
    a = onset_shapes(orig, nframes)
    b = onset_shapes(ours, nframes)
    out = []
    for adsr, ours_key in paired_keys(a, b):
        o = a[adsr].most_common(1)[0][0]
        u = b[ours_key].most_common(1)[0][0]
        rec = {"adsr": adsr, "kind": classify_onset(o, u),
               "orig": list(o), "ours": list(u),
               "orig_notes": sum(a[adsr].values()),
               "our_notes": sum(b[ours_key].values())}
        rec.update((stamps or {}).get(adsr, {}))
        out.append(rec)
    return out


def reversals_by_instrument(voices: list[Voice], nframes: int) -> dict:
    """`{ADSR: reversals}`, the same count `pitch_motion` totals.

    Split by the instrument sounding the note, on the key every other census
    here uses. Deliberately the *same* reduction as `pitch_motion` -- the same
    attack-adjacent frames skipped, the same sign-change test -- so the
    per-instrument numbers add to the column's own totals rather than being a
    second measurement of the same thing.
    """
    out: dict = {}
    for v in voices:
        fq = register_timeline(v.freq_events, nframes)
        adsr = register_timeline(v.adsr_events, nframes)
        skip = set()
        for a in v.attack_frames:
            skip |= {a - 1, a, a + 1}
        atk = sorted(v.attack_frames)
        for j, a in enumerate(atk):
            nxt = atk[j + 1] if j + 1 < len(atk) else nframes
            seg = [fq[f] for f in range(a, min(nxt, nframes)) if f not in skip]
            if len(seg) < 2:
                continue
            deltas = [seg[k + 1] - seg[k] for k in range(len(seg) - 1)]
            signs = [d > 0 for d in deltas if d]
            n = sum(1 for k in range(1, len(signs)) if signs[k] != signs[k - 1])
            key = adsr[a] if a < nframes else 0
            out[key] = out.get(key, 0) + n
    return out


def pitch_effect_bits(sid_path, det=None) -> dict:
    """`{bit: name}` for the pitch-moving effect bits *this player reads*.

    **A bit's meaning is a fact about a player, not about the format.** This
    project's whole detection layer exists because `$04` is an arpeggio in
    some players and a two-stage attack in others, and `$01` is a drum in one
    dialect and a wave-program selector in another. A census that hardcodes
    the meanings will mis-attribute exactly the files whose dialect differs --
    Chimera's largest missing instrument carries `$0D`, and its `$01` is the
    drum its player sweeps the frequency with, which a fixed table filed as
    "the record's own vibrato".

    So the bits come from `Detection`, which read them out of the player, and
    a bit is named only where the player is known to act on it. Bits `$04`
    (two-stage waveform) and `$08` (pulse width) are deliberately absent: they
    move a waveform and a duty cycle, not a pitch.

    `det` may be passed by a caller that has already detected the file --
    `vibrato_records` has -- so the two do not disagree about the player and
    the file is not read twice.
    """
    from h2g.convert import _detect_tables
    from h2g.sidfile import load_sid
    if det is None:
        try:
            _, det = _detect_tables(load_sid(str(sid_path)),
                                    lambda *a, **k: None)
        except Exception:                                      # noqa: BLE001
            return {}
    out = {}
    # **Every bit below is read from `Detection`'s own field comment**, not
    # from memory. Getting this table from anywhere else has now been wrong
    # three times: `$02` was listed as a pitch mover when it was a waveform
    # alternation (§ 7.xxxxx), then removed entirely when `effect_rise` makes
    # it one, and `effect_arp` was mapped to `$10` when detect.py:98 says it
    # is `$04`.
    #
    #   effect_drum      $01  "pitch sweep down, then noise"
    #   effect_rise      $02  "+1 semitone every 4 frames"
    #   effect_arp       $04  "alternate with note - (byte >> 4)"
    #   effect_pulse_lo  $08  "accumulate +6 into pulse width LO"   <- not pitch
    #
    # `$02` is the instructive one: it moves a pitch under `effect_rise` and a
    # waveform under `wave_alternate`, and no player has both.
    if det.effect_drum:
        out[0x01] = "drum"
    if det.effect_rise:
        out[0x02] = "rise"
    if det.effect_arp:
        out[0x04] = "arp"
    # Bit $10 has no detection flag: `goatwriter.EFFECT_PITCH_SEQ_MASK` is
    # applied to the record unconditionally, so the project already treats its
    # meaning as stable across the family.
    out[0x10] = "pitchseq"
    if det.effect_bit40:
        out[0x40] = "atkpitch"
    if det.effect_bit80:
        out[0x80] = "bit80"
    if det.wave_program >= 0 and det.wave_program_gate:
        out.setdefault(det.wave_program_gate, "program")
    return out


# Pitch-moving mechanisms in the order they dominate a record that carries
# several. An arpeggio restates the note every few frames, a drum sweeps it,
# a wave program slides it, and a fixed attack pitch moves it twice a note.
VIB_CAUSE_ORDER = (0x10, 0x04, 0x01, 0x02, 0x80, 0x40, 0x08)

# Fallback meanings, used only where detection could not be run. Kept so the
# census still classifies something on a file whose tables cannot be read, and
# ordered by how much of the corpus's movement each accounts for.
VIB_CAUSES = (
    (0x10, "arp", "bit $10, a pitch sequence on a **global** phase counter -- "
                  "a wavetable restarts at every note, so no rotation of it is "
                  "right more than 1/steps of the time (section 7.ttt)"),
    (0x02, "alt", "bit $02's alternating waveform, which moves the pitch as a "
                  "side effect"),
    # Both of these move the pitch and both were being filed as `plain` --
    # "the record's own vibrato" -- until the release-nibble join started
    # returning effect bytes at all. Las Vegas Video Poker's largest row, 2698
    # reversals, is `$44`.
    (0x80, "drum", "bit $80's drum, whose block sweeps the frequency down and "
                   "repeats -- the sweep is movement and the repeat reverses "
                   "it"),
    (0x40, "atkpitch", "bit $40's fixed attack pitch from the note table: the "
                       "voice is pulled to one pitch and returns, which is two "
                       "reversals a note"),
)


def stamp_for(stamps: dict | None, adsr: int) -> dict:
    """The provenance stamp for an ADSR pair, joined on the bits we keep.

    **The release nibble cannot be part of this key.** `instrument_stamps`
    reads our own `.sng`, and `--cut-release` -- in `presets.json`'s `always`
    block -- rewrites that nibble, so an exact join drops every instrument
    whose release the conversion changed. Las Vegas Video Poker matched 1 of
    the 6 envelope pairs its original sounds and Thrust 6 of 9; masking takes
    both to all of them, and the 67 unattributed rows of the corpus vibrato
    census were that and not an unread record.

    Same trap as `release_tails`, which keyed a release measurement on the
    pair containing it (§ 7.xxxx) -- except the rule is broader than that
    docstring states. A key must not contain a field the *conversion* alters,
    whether or not the column measures it.

    Masking can make two instruments collide that the full pair separated, so
    an exact hit is preferred and a masked one is taken only when it is
    unique.
    """
    if not stamps:
        return {}
    if adsr in stamps:
        return stamps[adsr]
    hits = [v for k, v in stamps.items()
            if instrument_key(k) == instrument_key(adsr)]
    return dict(hits[0], release_masked=True) if len(hits) == 1 else {}


def vib_census(orig: list[Voice], ours: list[Voice], nframes: int,
               stamps: dict | None = None, bits: dict | None = None
               ) -> list[dict]:
    """Every instrument both sides oscillate, and how much of it we reproduce.

    `vib` is a whole-file ratio, and a whole-file ratio cannot say *which*
    instrument is missing its movement -- which matters because the answer
    decides what to fix. The balloon song read 0.17x and was taken for a
    vibrato-rate defect; the one instrument that actually carries a vibrato
    byte was within 20% of the original, and the missing 1812 reversals
    belonged to an arpeggio never read at all (section 7.ttt). That is the
    mistake this exists to prevent: attribute the ratio before tuning the
    mechanism assumed to produce it.
    """
    a = reversals_by_instrument(orig, nframes)
    b = reversals_by_instrument(ours, nframes)
    # **Paired, not unioned.** `--cut-release` rewrites the release nibble, so
    # the original's `$0A0C` is our `$0A00`; a union counts them as two
    # instruments and reports the first as emitting nothing. Las Vegas Video
    # Poker's five arpeggio instruments each showed `ours 0` that way while
    # the conversion carried a correct alternation -- `note, note, note-4,
    # jump` -- in its wavetable. v0.5.292 routed the six column intersections
    # through `paired_keys` and left this census on the union it was written
    # with.
    pairs = dict(paired_keys(a, b))
    out = []
    for adsr in sorted(set(a) | (set(b) - set(pairs.values()))):
        o = a.get(adsr, 0)
        u = b.get(pairs.get(adsr, adsr), 0)
        if not o and not u:
            continue
        rec = {"adsr": adsr, "orig": o, "ours": u,
               "ratio": (u / o) if o else None}
        rec.update(stamp_for(stamps, adsr))
        eff = rec.get("effect")
        # `plain` asserts that no oscillating bit is set, which is a claim
        # about the record. Where the stamp could not be recovered -- two
        # instruments sharing an ADSR pair, the ambiguity of section 7.zzzz --
        # there is nothing to make that claim from, and calling it `plain`
        # would put 67 of the corpus's 148 into a bucket labelled "the
        # record's own vibrato" on no evidence.
        if eff is None:
            rec["cause"] = "unknown"
        elif bits:
            # Detection's own reading, in order of how much pitch each
            # mechanism moves -- **not** by bit value. A record carrying both
            # the drum and the arpeggio is named for whichever dominates, and
            # sorting numerically picked `$02` over `$01` on every `$2B`
            # record in the corpus.
            hit = [n for bit in VIB_CAUSE_ORDER
                   if (n := bits.get(bit)) and eff & bit]
            rec["cause"] = hit[0] if hit else "plain"
        else:
            rec["cause"] = next((n for bit, n, _ in VIB_CAUSES if eff & bit),
                                "plain")
        out.append(rec)
    return out


def vib_census_report(rows: list[dict]) -> str:
    """The vibrato census over a run: where the missing oscillation lives."""
    from collections import Counter
    recs = [dict(r, file=row["file"])
            for row in rows for r in row.get("vib_census") or []]
    short = [r for r in recs if r["orig"] and (r["ours"] / r["orig"]) < 0.5]
    out = ["# Vibrato census", "",
           f"{len(recs)} instrument(s) across "
           f"{len({r['file'] for r in recs})} file(s) whose pitch oscillates "
           "on either side. `vib` is a whole-file ratio; this is the same "
           "count split by the instrument sounding it, so the rows add to "
           "that column rather than re-measuring it.", "",
           "**Why this is asked before anything is tuned.** The balloon song "
           "read `vib` 0.17x and it was taken for a vibrato-rate defect. The "
           "one instrument carrying a vibrato byte was within 20% of the "
           "original; the missing 1812 reversals were an arpeggio on a global "
           "counter that no wavetable can hold (section 7.ttt). A rate that "
           "looks wrong may be a mechanism that is absent.", "",
           "## Instruments reproducing under half the original's oscillation",
           "", "| file | ADSR | GT | effect | cause | orig | ours |",
           "|---|---|---:|---|---|---:|---:|"]
    for r in sorted(short, key=lambda r: -(r["orig"] - r["ours"])):
        eff = r.get("effect")
        out.append(
            f"| {r['file']} | `${r['adsr']:04X}` | {r.get('gt', '-')} | "
            f"{('$%02X' % eff) if eff is not None else '-'} | {r['cause']} | "
            f"{r['orig']} | {r['ours']} |")
    # **Absent and slow are different defects and must not share a row.**
    # `plain` reads as "a vibrato-rate shortfall", and 135 of its 148
    # instruments emit *no* oscillation at all -- nothing to speed up. Tuning
    # a rate would move the 13 that are merely slow.
    out += ["", "## By cause", "",
            "`absent` is an instrument the original oscillates and we do not "
            "move at all; `slow` is one that moves too little. They have "
            "different fixes, so they are counted apart.", "",
            "| cause | absent | slow | instruments | reversals missing |",
            "|---|---:|---:|---:|---:|"]
    by = Counter()
    absent = Counter()
    lost = Counter()
    for r in short:
        by[r["cause"]] += 1
        absent[r["cause"]] += (r["ours"] == 0)
        lost[r["cause"]] += r["orig"] - r["ours"]
    for cause, n in by.most_common():
        out.append(f"| {cause} | {absent[cause]} | {n - absent[cause]} | "
                   f"{n} | {lost[cause]} |")
    # Derived from the rows rather than written down, so it cannot go stale
    # the way the first draft did -- it said "135 of 148" after `unknown` was
    # split out of `plain` and the numbers had become 68 of 81.
    n_absent = sum(absent.values())
    out += ["",
            f"**{n_absent} of these {len(short)} instruments emit no "
            f"oscillation at all**, against {len(short) - n_absent} that "
            "merely run slow. That is the reading to take from this table: "
            "the shortfall is overwhelmingly a movement that never reached "
            "the file, not a rate to tune.", "",
            "`plain` is an instrument whose effect byte is known and carries "
            "no oscillating bit, so its movement is the record's own vibrato "
            "byte. `unknown` is one whose byte could not be recovered -- "
            "`instrument_stamps` keys on the ADSR pair and two instruments "
            "can share one (section 7.zzzz) -- so no mechanism is claimed "
            "for it. `alt` and `arp` are mechanisms; `arp` runs on a global "
            "phase counter and a per-note wavetable cannot hold it at all "
            "(section 7.ttt).", ""]
    return "\n".join(out)


def census_report(rows: list[dict]) -> str:
    """The onset census over a whole run: what the misses are made of.

    Written as a separate document rather than a section of the report because
    it is a queue rather than a measurement -- the report says how the corpus
    scores, this says which files to open next and why.
    """
    recs = [dict(r, file=row["file"])
            for row in rows for r in row.get("onset_census") or []]
    out = ["# Onset census", "",
           f"{len(recs)} instrument(s) compared across "
           f"{sum(1 for r in rows if r.get('onset_census'))} file(s). Each is "
           "one instrument both sides sound, keyed by its ADSR pair and read "
           "at its own attack frames -- the population the `onset` column "
           "scores, classified by the *kind* of its disagreement.", ""]
    counts = Counter(r["kind"] for r in recs)
    out += ["| kind | n | share |", "|---|---:|---:|"]
    for k in ONSET_KINDS:
        n = counts.get(k, 0)
        out.append(f"| {k} | {n} | {100 * n / len(recs):.1f}% |"
                   if recs else f"| {k} | {n} | - |")
    out.append("")

    misses = [r for r in recs if r["kind"] != "match"]
    flat = [r for r in misses if r["kind"] == "flat"]
    if flat:
        by_eff = Counter(r.get("effect") for r in flat)
        out += ["## `flat` misses by the record's effect byte", "",
                "A mechanism the original runs and we hold flat, grouped by "
                "the source record's `+7`. This is the work list: a group "
                "whose bit is already implemented points at option selection, "
                "one whose bit is not points at the player.", "",
                "| effect | n | files |", "|---|---:|---:|---:|---|"]
        for eff, n in by_eff.most_common():
            files = sorted({r["file"] for r in flat if r.get("effect") == eff})
            name = "-" if eff is None else f"`${eff:02X}`"
            out.append(f"| {name} | {n} | {', '.join(files)} |")
        out.append("")

    if misses:
        out += ["## Every disagreement", "",
                "| file | GT | ADSR | effect | kind | original | ours | notes |",
                "|---|---:|---|---|---|---|---|---:|"]
        for r in sorted(misses, key=lambda r: (ONSET_KINDS.index(r["kind"]),
                                               r["file"], r["adsr"])):
            eff = r.get("effect")
            out.append(
                f"| {r['file']} | {r.get('gt', '-')} | `${r['adsr']:04X}` | "
                f"{'-' if eff is None else f'${eff:02X}'} | {r['kind']} | "
                f"`{shape_name(r['orig'])}` | `{shape_name(r['ours'])}` | "
                f"{r['orig_notes']}/{r['our_notes']} |")
        out.append("")
    return "\n".join(out)


def sound_note_runs(voices: list[Voice], nframes: int) -> dict:
    """`{adsr: [(held, slot), ...]}` -- per note, what `sound_runs` reduces.

    Split out of `sound_runs` in v0.5.254 so the census below can read the
    note's **slot** as well as the frames it sounds for. The two are different
    questions and the histogram of § 7.uuuu conflated them: a note can be short
    because we stop sounding inside a slot the same length as the original's
    (a hold defect) or because the slot itself is shorter (a *timing*
    difference, which `hold` was never meant to measure and cannot fix).

    `held` is frames with a waveform selected from the attack, `slot` is frames
    to the next attack on that voice, and `total` is frames sounding *anywhere*
    in the slot. `sound_runs` is `held` alone, unchanged.

    `total` exists because `held` stops at the first deselected frame, and a
    player that drops the waveform for one frame and resumes has not ended its
    note -- I_Ball's `$0909` sounds `41 41 41 40 40 40 08 40 40 ...`, which
    reads as a twelve-frame note against our twenty-three and is a
    twenty-three-frame note with a hole in it. That is a fact about the
    reduction, not about the conversion, and `classify_hold` calls it `gap`.
    """
    out: dict = {}
    for v in voices:
        wf = register_timeline(v.wf_events, nframes)
        adsr = register_timeline(v.adsr_events, nframes)
        attacks = sorted(a for a in v.attack_frames if 0 <= a < nframes)
        for i, a in enumerate(attacks):
            stop = attacks[i + 1] if i + 1 < len(attacks) else nframes
            if stop >= nframes:
                continue                      # cut by the window
            held = 0
            while a + held < stop and wf[a + held] & 0xF0:
                held += 1
            total = sum(1 for k in range(stop - a) if wf[a + k] & 0xF0)
            out.setdefault(adsr[min(a + 1, nframes - 1)],
                           []).append((held, stop - a, total))
    return out


def sound_runs(voices: list[Voice], nframes: int) -> dict:
    """How many frames each note keeps a waveform selected, by instrument.

    **The one thing no column measured.** CLAUDE.md has said for a long time
    that nothing here sees note *length*, and the `onset` census's `short` kind
    (v0.5.234) named five instruments where our note stops selecting a waveform
    inside the four-frame opening window while the original still does. This is
    that observation as a measurement.

    What the two sides do, Commando voice 0, twelve-frame notes:

        ORIGINAL  15 80 80 14 14 14 14 14 14 14 14 14 | next attack
        OURS      15 81 81 15 15 15 15 15 15 14 14 09 | next attack

    The original leaves its waveform latched to the last frame; ours spends
    that frame on `$09` -- the test bit and the gate, no waveform selected at
    all. Goattracker fetches the next note `gatetimer & $3f` ticks early
    (gplay.c:905) and writes the instrument's `firstwave` then, so the note
    before it loses its final frame. Every instrument of every corpus file is
    one frame short for that reason.

    **The deficit is a number of play calls, not of frames, and that is what
    makes the column's zeros ambiguous.** Re-measured at **v0.5.429** with
    `--hold-census`, which classifies each instrument by *why* its modal note
    length differs rather than by a raw offset -- 526 instruments across 82
    files, `fetch` counted against that rate's whole population:

        -S1   fetch 109 of 138        (no --no-test-restart)
        -S1   fetch   0 of  59        (with --no-test-restart)
        -S2   fetch 144 of 154
        -S3   fetch  12 of  66
        -S4   fetch   0 of  28
        -S5   fetch   0 of  34
        -S6   fetch   2 of   2
        -S7   fetch   0 of  21
        -S9   fetch   0 of   9

    The figures this block carried until v0.5.429 were an earlier statistic
    over 415 instruments (`-S1` 106 at -1, `-S4` 17 of 17 at 0). They were
    right in shape and stale in both counts; `--hold-census` superseded the
    offset reduction and the numbers had not followed it here.

    The next-note fetch is `gatetimer & $3f` **calls** early, so at `-S4` it
    costs a quarter of a frame and siddump -- which samples once per frame --
    cannot see it at all. **A zero at `-S4` or above therefore means "not
    visible", not "correct"**, and the same is true of half the `-S3` files.
    The option removes it outright at every rate, which is why the preset
    search takes it only on files below `-S4`: all nine that carry it are
    `-S1` but for Delta at `-S2`, and that is a prediction this made before
    the list was looked at.

    **THE DEFICIT IS REFUSED RATHER THAN EMITTED, AND THIS IS THE REASON.**
    `fetch` is the largest kind in the census -- 267 of 526 instruments,
    50.8% -- so the temptation to close it is real. It cannot be closed by
    lengthening a note: the frame is lost to *Goattracker's own* next-note
    fetch (gplay.c:905), not to anything this converter emits, so there is no
    row length or gatetimer that returns it. The one thing that does remove it
    is `--no-test-restart`, which deletes the frame our conversion spends on
    `$09` -- and that is already a searchable per-song option, selected on nine
    files. Forced corpus-wide it costs **melody -26.3pp over 68 files** and
    takes Delta Mix-E-Load to 0%, because siddump needs a frame below `$10` to
    name an attack at all and four columns collapse when the instrument can no
    longer see our note starts. So the deficit is a known, measured, priced
    limitation of the target player, not an open defect: closing it globally
    costs more than it buys, and closing it per song is what the search
    already does.

    The far tail is a different thing again and not note length at all: the
    six instruments beyond +50 frames are one held note apiece, or a voice
    whose orderlist we misread so it never retriggers (Knucklebusters `$00F8`
    sounds 959 frames over 2 notes against the original's 9 over 94 -- the
    version-0 dialect of § 7.qqqq), or Rasputin, whose subtunes the init
    remaps so the two sides are different music.

    **Capped at the next attack, and the cap is what makes it bounded.** A
    gated-off voice keeps its waveform latched, so "until the waveform is
    deselected" would run through the rest of the tune on the original side and
    be dropped as window-cut. The quantity here is therefore *frames sounding
    within this note's own slot*, which is what a listener hears as the note's
    length, and both sides are cut the same way. A note whose slot reaches the
    end of the window is dropped: its length would be a fact about the window.

    Keyed by the ADSR pair one frame after the attack -- `onset_shapes`' rule
    and for its reason. The key is $D405/$D406 and the measured quantity is a
    duration, so neither can contaminate the other.

    Returns `{adsr: Counter({frames: count})}`, reduced from
    `sound_note_runs` so the column and the census below cannot drift apart.
    """
    return {k: Counter(h for h, *_ in v)
            for k, v in sound_note_runs(voices, nframes).items()}


def sound_run_agreement(orig: list[Voice], ours: list[Voice],
                        nframes: int) -> dict:
    """Instruments whose notes sound for as long as the original's.

    Same footing as `noise_run_agreement`: instruments both sides play, modal
    length each, and an instrument only one side sounds is absent rather than
    counted wrong.

    `sound_run_delta` is the modal signed difference in frames and is the
    number to read while the agreement sits at zero -- it says *how* short
    rather than merely that nothing matches. As shipped it is `-1` on every
    file measured; forcing `--no-test-restart`, which writes the record's own
    waveform into `firstwave` instead of `$09`, takes Commando from 0 of 6
    instruments matching to 6 of 6 and the delta to 0.
    """
    a = sound_runs(orig, nframes)
    b = sound_runs(ours, nframes)
    shared = paired_keys(a, b)
    pairs = [(a[ka].most_common(1)[0][0], b[kb].most_common(1)[0][0])
             for ka, kb in shared]
    matched = sum(1 for x, y in pairs if x == y)
    deltas = Counter(y - x for x, y in pairs)
    return {
        "sound_run_instruments": len(shared),
        "sound_run_matched": matched,
        "sound_run_agreement": (matched / len(shared)) if shared else None,
        "sound_run_delta": (deltas.most_common(1)[0][0] if deltas else None),
    }


HOLD_KINDS = ("match", "fetch", "slot", "thin", "sparse", "gap",
              "short", "long")


def classify_hold(delta: int, slot_delta: int,
                  orig_notes: int, our_notes: int,
                  orig: tuple[int, int] = (0, 0),
                  ours: tuple[int, int] = (0, 0)) -> str:
    """Which of the four things a `hold` disagreement is.

    § 7.uuuu separated the column's tail into a call-rate artefact, a handful
    of other defects wearing a length costume, and an unattributed remainder of
    46 instruments at -2..-7 and ~38 at +5..+23. This is that remainder asked
    the question the histogram could not: **is the note shorter, or is its
    slot?**

    * `fetch`  -- one frame short with the slot unchanged: Goattracker's
      next-note fetch, `gatetimer & $3f` play calls early (gplay.c:905). The
      bulk of the column, removed outright by `--no-test-restart`.
    * `slot`   -- the length difference is the *slot's* difference, within a
      frame. The note is as long as the room it is given; what differs is when
      the next note arrives, which is a timing question `hold` does not measure
      and no wavetable edit can fix. Read `--pace` and `retrig`, not this.
    * `sparse` -- one side plays at least twice as many notes under this ADSR,
      so the two modes are taken over different music.
    * `thin`   -- fewer than four notes on one side. A mode over one note is
      that note; § 7.uuuu's far tail is mostly this, single held notes whose
      "length" is a fact about the window.
    * `gap`    -- one side sounds for as many frames as the other *in total*
      but drops the waveform for a frame in the middle, and `held` stops at
      the first hole. A limitation of the reduction, not a difference in the
      music.
    * `short` / `long` -- an equal slot, an equal population, an uninterrupted
      run, and we stop sounding early or keep sounding late. This is the
      residue that is actually about the note's length.

    `slot` outranks `fetch` where both fit -- a note one frame short in a slot
    one frame short is over-determined, and above `-S3` the fetch costs a
    fraction of a frame, so the slot is the reading that can be true at every
    rate.

    `orig` and `ours` are each `(held, total)`; they default to zeros so the
    four-argument form still classifies everything but `gap`.
    """
    if delta == 0:
        return "match"
    if slot_delta and abs(delta - slot_delta) <= 1:
        return "slot"
    if delta == -1:
        return "fetch"
    if min(orig_notes, our_notes) < 4:
        return "thin"
    if orig_notes >= 2 * our_notes or our_notes >= 2 * orig_notes:
        return "sparse"
    if ((orig[1] > orig[0] and abs(ours[0] - orig[1]) <= 1)
            or (ours[1] > ours[0] and abs(orig[0] - ours[1]) <= 1)):
        return "gap"
    return "short" if delta < 0 else "long"


def hold_census(orig: list[Voice], ours: list[Voice], nframes: int,
                stamps: dict | None = None) -> list[dict]:
    """Every instrument `hold` compared, with the kind of its disagreement.

    Same population and same modal reduction as `sound_run_agreement` -- the
    instruments both sides sound -- so the counts here add up to that column's
    denominator and `match` is its numerator, exactly as `onset_census` stands
    to `onset_agreement`. Computed from the traces the column just scored
    rather than from a second pipeline, for the reason given there.
    """
    def modal(notes):
        """The typical note's length, and *its own* slot.

        The held length is `sound_runs`' mode, unchanged, so `match` here stays
        the column's numerator. The slot is then the mode among the notes that
        length was taken from, rather than an independent mode over all of
        them -- two independent modes can report a note sounding for longer
        than its slot, which is not a thing a note can do.
        """
        h = Counter(x for x, _, _ in notes).most_common(1)[0][0]
        same = [(s, t) for x, s, t in notes if x == h]
        return (h, Counter(s for s, _ in same).most_common(1)[0][0],
                Counter(t for _, t in same).most_common(1)[0][0])

    a = sound_note_runs(orig, nframes)
    b = sound_note_runs(ours, nframes)
    out = []
    for adsr, ours_key in paired_keys(a, b):
        oh, os_, ot = modal(a[adsr])
        uh, us, ut = modal(b[ours_key])
        rec = {"adsr": adsr, "orig_held": oh, "our_held": uh,
               "delta": uh - oh, "orig_slot": os_, "our_slot": us,
               "slot_delta": us - os_,
               "orig_total": ot, "our_total": ut,
               "orig_notes": len(a[adsr]),
               "our_notes": len(b[ours_key])}
        rec["kind"] = classify_hold(rec["delta"], rec["slot_delta"],
                                    rec["orig_notes"], rec["our_notes"],
                                    (oh, ot), (uh, ut))
        rec.update((stamps or {}).get(adsr, {}))
        out.append(rec)
    return out


def hold_census_report(rows: list[dict]) -> str:
    """The hold census over a whole run: what the length misses are made of.

    A queue rather than a measurement, like `census_report`: the report says
    how the corpus scores, this says which instruments are still unexplained
    once timing and population are taken out of the histogram.
    """
    recs = [dict(r, file=row["file"], multiplier=row.get("multiplier", 1),
                 no_test_restart=bool((row.get("options") or {})
                                      .get("no_test_restart")))
            for row in rows for r in row.get("hold_census") or []]
    files = sum(1 for r in rows if r.get("hold_census"))
    out = ["# Hold census", "",
           f"{len(recs)} instrument(s) compared across {files} file(s). Each "
           "is one instrument both sides sound, keyed by its ADSR pair -- the "
           "population the `hold` column scores, classified by *why* its modal "
           "note length differs. `slot` and `sparse` are not length "
           "disagreements at all; `short` and `long` are the remainder.", ""]
    if not recs:
        return "\n".join(out)
    counts = Counter(r["kind"] for r in recs)
    out += ["| kind | n | share |", "|---|---:|---:|"]
    for k in HOLD_KINDS:
        n = counts.get(k, 0)
        out.append(f"| {k} | {n} | {100 * n / len(recs):.1f}% |")
    out.append("")

    by_mult: dict = {}
    for r in recs:
        by_mult.setdefault((r["multiplier"], r["no_test_restart"]),
                           Counter())[r["kind"]] += 1
    out += ["## By packed rate", "",
            "`fetch` is invisible above `-S3` -- siddump samples once a frame "
            "and the deficit is a number of play calls -- so a low count up "
            "there is the trace's resolution, not the converter's.", "",
            "| -S | --no-test-restart | " + " | ".join(HOLD_KINDS) + " |",
            "|---:|---|" + "---:|" * len(HOLD_KINDS)]
    for (m, opt), c in sorted(by_mult.items()):
        out.append(f"| {m} | {'yes' if opt else 'no'} | "
                   + " | ".join(str(c.get(k, 0)) for k in HOLD_KINDS) + " |")
    out.append("")

    rest = [r for r in recs if r["kind"] in ("short", "long")]
    if rest:
        by_eff = Counter(r.get("effect") for r in rest)
        out += ["## The remainder by the record's effect byte", "",
                "| effect | n | files |", "|---|---:|---|"]
        for eff, n in by_eff.most_common():
            fs = sorted({r["file"] for r in rest if r.get("effect") == eff})
            name = "-" if eff is None else f"`${eff:02X}`"
            out.append(f"| {name} | {n} | {', '.join(fs)} |")
        out.append("")
        out += ["## Every unexplained instrument", "",
                "`held` is frames to the first deselected one, `total` every "
                "sounding frame in the slot; where they differ the note has a "
                "hole in it.", "",
                "| file | -S | GT | ADSR | effect | kind | held | total | "
                "slot | notes |", "|---|---:|---:|---|---|---|---|---|---|---:|"]
        for r in sorted(rest, key=lambda r: (r["kind"], -abs(r["delta"]),
                                             r["file"])):
            eff = r.get("effect")
            out.append(
                f"| {r['file']} | {r['multiplier']} | {r.get('gt', '-')} | "
                f"`${r['adsr']:04X}` | {'-' if eff is None else f'${eff:02X}'} "
                f"| {r['kind']} | {r['orig_held']}/{r['our_held']} | "
                f"{r.get('orig_total', '-')}/{r.get('our_total', '-')} | "
                f"{r['orig_slot']}/{r['our_slot']} | "
                f"{r['orig_notes']}/{r['our_notes']} |")
        out.append("")
    return "\n".join(out)


def noise_run_agreement(orig: list[Voice], ours: list[Voice],
                        nframes: int) -> dict:
    """How many instruments sound noise for the same length on both sides.

    Compared per ADSR and only where both sides sound noise at all, so a
    conversion that drops an instrument's noise entirely is *absent* here rather
    than counted as a disagreement -- that is what the one-sided `noise` count
    is for. This answers the narrower question the count cannot: given that we
    sound it, do we sound it for as long?
    """
    a, b = noise_runs(orig, nframes), noise_runs(ours, nframes)
    shared = paired_keys(a, b)
    matched = sum(1 for ka, kb in shared
                  if a[ka].most_common(1)[0][0] == b[kb].most_common(1)[0][0])
    return {
        "noise_run_instruments": len(shared),
        "noise_run_matched": matched,
        "noise_run_agreement": (matched / len(shared)) if shared else None,
        "noise_run_orig_only": len(set(a) - set(b)),
        "noise_run_ours_only": len(set(b) - set(a)),
    }


def _changes(timeline: list[int]) -> int:
    """How many times a register's value moved across a per-frame timeline.

    Counted from the expanded timeline rather than from the event list so it
    means the same thing on both sides: siddump prints a register on the frame
    it is *written*, and a player that rewrites the same value every frame
    would otherwise be scored as sweeping it.
    """
    return sum(1 for i in range(1, len(timeline)) if timeline[i] != timeline[i - 1])


def _span(timeline: list[int]) -> int:
    """The width of the band a nonzero register covers -- max less min.

    The companion a count needs whenever the change under test is to a step
    *size*. `_changes` reads the same sweep taken in twice as many half-sized
    steps as twice the movement, which is exactly what a Goattracker pulse
    program does to a player's staircase: a signed-byte speed cannot move
    224 in one call, so it moves 127 twice, and the count doubles while the
    sound is the same. The band does not move under that substitution.

    **Zero is excluded, and the column is unusable without that.** Goattracker
    writes `$D402/$D403` on every frame of every voice from the first call
    (`gplay.c:945`) where the player writes them at its first note, so our
    timeline opens on a run of `$000` and the original's opens on a real width.
    Left in, that leading zero is a spurious `$000`-to-first-width jump on all
    three voices of every file, and it read as us covering 3.96x the band on
    Commando while our sweep in fact covers slightly *less*. A width of `$000`
    is 0% duty -- silence, not a timbre -- so nothing audible is lost by
    dropping it, and the rule is the same on both sides.
    """
    live = [v for v in timeline if v]
    return (max(live) - min(live)) if live else 0


# A duty cycle quantised for the phase count below. `instrmap.PULSE_BUCKET`
# is the same 0x100 and for the same reason: the register is 12 bits and the
# ear does not hear the bottom eight of them as a separate timbre, so counting
# raw values would report two notes a handful of units apart as two phases.
PULSE_PHASE_BUCKET = 0x100


def _onset_phases(v: Voice, timeline: list, nframes: int) -> set:
    """The distinct duty cycles this voice's notes START on.

    `pspan` says how WIDE a band the sweep covers and cannot say WHERE in it a
    note opens, so two sweeps of identical width entered from different points
    score the same. That is exactly the deficit `_pulse_tri_program` documents:
    the player's accumulator free-runs and is never reseeded, so its notes open
    all over the band, while a Goattracker pulse program reloads with the
    instrument and opens every note on the record's own width. On
    5_Title_Tunes' instrument 5 the original opens on five buckets and ours on
    one, with the per-note TRAVEL already correct (0.83x, from instrmap's own
    table) -- a phase error rather than a rate or depth error, and no column
    could see it.

    Read one frame AFTER the attack, matching `instrmap`'s "at onset", because
    the note's own instrument load writes the width on the attack frame itself
    and the frame after it is the first the program actually governs.

    **No startup-lag correction, for `onset`'s reason**: each side is read at
    its OWN attack frames, so the packed player's 3-8 frame latency cancels
    rather than needing to be subtracted. Passing a lag in here would
    manufacture the error this is built to detect.
    """
    out = set()
    for f in v.attack_frames:
        g = f + 1
        if 0 <= g < nframes and timeline[g]:
            out.add(timeline[g] // PULSE_PHASE_BUCKET)
    return out


def pulse_compare(orig: list[Voice], ours: list[Voice], nframes: int) -> dict:
    """How often each side moves the duty cycle, and how far it travels.

    Not an agreement percentage, and deliberately. Two players sweeping the
    same duty cycle at the same rate from different starting phases share
    almost no frame values, so a per-frame equality score would read as near
    zero for a conversion that sounds right; and the defect this exists to
    watch is not a wrong width but a **frozen** one. H2G wrote one pulse-table
    entry per instrument and stopped, which is right for the 328 corpus
    records whose sweep rate is zero and wrong for the 414 that sweep
    (v0.5.73). A one-sided movement count is what shows that, in the same
    ours/original form as `noise`.

    Calibration from v0.5.73's throwaway script, 37 files at 20 s with the
    filter off on both sides: the originals move the pulse width 60056 times,
    ours moved it 757 (1%) before that change and 35892 (60%) after. The
    report runs 10 s at the current `always` block, so the digits differ from
    those and the shape should not.
    """
    o_ch = u_ch = 0
    o_sp = u_sp = 0
    o_phases = u_phases = 0
    per_voice = []
    for a, b in zip(orig, ours):
        ta = register_timeline(a.pulse_events, nframes)
        tb = register_timeline(b.pulse_events, nframes)
        vo, vu = _changes(ta), _changes(tb)
        vo_sp, vu_sp = _span(ta), _span(tb)
        # Per voice as well as summed, so a row can name WHICH voice's sweep
        # is narrow. The file-level ratio alone said 0.47x on 5_Title_Tunes
        # and could not say that instrument 5 is the one at fault -- the same
        # gap `gate_census_by_voice` closed for the gate.
        o_ph, u_ph = (_onset_phases(a, ta, nframes),
                      _onset_phases(b, tb, nframes))
        per_voice.append({"orig_pulse_changes": vo, "our_pulse_changes": vu,
                          "orig_pulse_span": vo_sp, "our_pulse_span": vu_sp,
                          "pulse_span": (vu_sp / vo_sp) if vo_sp else None,
                          "orig_pulse_phases": len(o_ph),
                          "our_pulse_phases": len(u_ph)})
        o_ch += vo
        u_ch += vu
        o_sp += vo_sp
        u_sp += vu_sp
        # THE POPULATION IS THE VOICES WHOSE ORIGINAL ACTUALLY VARIES, which
        # is the rule "a discriminator is only meaningful on the population
        # the behaviour occurs in". A voice whose original opens every note on
        # one width has no phase to reproduce and ours reproduces it exactly,
        # so counting it would score a perfect 1/1 and dilute the files that
        # do sweep -- 4 of 5_Title_Tunes' 7 instruments are that case.
        if len(o_ph) > 1:
            o_phases += len(o_ph)
            u_phases += len(u_ph)
    return {
        "orig_pulse_changes": o_ch,
        "our_pulse_changes": u_ch,
        "orig_pulse_span": o_sp,
        "our_pulse_span": u_sp,
        "pulse_span": (u_sp / o_sp) if o_sp else None,
        "orig_pulse_phases": o_phases,
        "our_pulse_phases": u_phases,
        "pulse_phase": (u_phases / o_phases) if o_phases else None,
        "pulse_voices": per_voice,
    }


# $D417's low nibble routes voices into the filter: bits 0-2 are voices 1-3
# and bit 3 is the external input, which no SID file has. The high nibble is
# resonance, which siddump prints in the same byte and never separates.
FILTER_ROUTE = 0x07


def _filter_side(f: FilterState, nframes: int) -> dict:
    cut = register_timeline(f.cutoff_events, nframes)
    ctrl = register_timeline(f.ctrl_events, nframes)
    band = register_timeline(f.passband_events, nframes)
    # "Filtering" needs both halves: a voice routed into the filter with no
    # passband selected is not filtered, it is inaudible ($D418 bits 4-6 pick
    # which of the three outputs reaches the mixer, and Off picks none).
    circuit = sum(1 for r, p in zip(ctrl, band) if (r & FILTER_ROUTE) and p)
    return {
        "filtered_frames": circuit,
        "cutoff_changes": _changes(cut),
        # Total distance the cutoff actually travels, and the width of the
        # band it covers. Both are needed: a sweep taken in twice as many
        # steps doubles the travel without going anywhere new, and one taken
        # in two steps over the whole register covers the range without
        # sounding like a sweep.
        "cutoff_travel": sum(abs(cut[i] - cut[i - 1]) for i in range(1, len(cut))),
        "cutoff_range": (max(cut) - min(cut)) if cut else 0,
    }


def filter_compare(orig: FilterState, ours: FilterState, nframes: int) -> dict:
    """The global filter: whether we filter where the original does, and how far.

    Two questions, and a count answers only the first:

    * *Do we filter where the original filters?* One-sided, like `noise`:
      frames on which a voice is routed through the filter and a passband is
      selected, ours over the original's. A nonzero ours against a zero
      original is a filter the conversion invented -- the failure v0.5.72's
      first attempt shipped, where Powerplay Hockey gained 497 cutoff writes
      against an original that writes the cutoff once.
    * *Does the cutoff move like the original's?* Deep_Strike went 481 -> 1515
      and that is an overshoot, not an absence; no count tells the two apart
      from a side that simply does more. `sweep` is our cutoff travel over the
      original's -- the summed frame-to-frame movement -- so a sweep sampled
      more finely than the original's scores near 1.0 where its write count
      would read as three times too much, and a sweep that runs further than
      the player's own counter allows scores high whatever its write count.
      Goattracker's filter table steps for a fixed tick count where the
      player's sweep is bounded by its own counter, which is the shape of
      overshoot to expect.

    Volume ($D418's low nibble) is parsed and not compared here: it is a
    master level, one write per file in nearly every original, and nothing the
    converter emits can move it.
    """
    o = _filter_side(orig, nframes)
    u = _filter_side(ours, nframes)
    out = {f"orig_{k}": v for k, v in o.items()}
    out.update({f"our_{k}": v for k, v in u.items()})
    out["cutoff_sweep"] = (u["cutoff_travel"] / o["cutoff_travel"]
                           if o["cutoff_travel"] else None)
    return out


def _shared_silence(a, b, silent=0) -> float:
    """The share of a frame on which BOTH sides hold the silent value.

    `wave_compare` drops a frame where both sides select no waveform, so that
    a voice silent in both cannot inflate the score. At 312 samples a frame
    the same rule has to be graded rather than all-or-nothing: what leaves the
    denominator is the *overlapping silent share*, not the whole frame.

    Getting this wrong was a real defect in v0.5.131. The first version
    dropped a frame only when both whole histograms were silent, so a frame in
    which one side flickered for five rasterlines and both sides were silent
    at the boundary was scored as a full agreement. That is precisely the
    inflation `wave_compare`'s rule exists to prevent, and it lifted
    Bangkok_Knights from 2.3% to 14.8% -- most of what v0.5.132 first
    attributed to the finer trace.
    """
    na, nb = sum(a.values()), sum(b.values())
    if not na or not nb:
        return 0.0
    return min(a.get(silent, 0) / na, b.get(silent, 0) / nb)


def _graded_agreement(ha, hb, la, lb, mode: str, silent=0):
    """(numerator, weight) for one frame, with shared silence removed.

    Returns a weight of 0 for a frame both sides spend entirely silent, which
    is the graded form of `continue`. For the non-graded rules the weight is
    0 or 1 so that `--vice-reduce last` reproduces siddump's own arithmetic
    exactly -- which is what makes the resolution and the rule separable.
    """
    if mode != "overlap":
        if la == silent and lb == silent:
            return 0.0, 0.0
        cell_a = vicetrace.FrameCell(hist=ha, last=la)
        cell_b = vicetrace.FrameCell(hist=hb, last=lb)
        return vicetrace.agreement(cell_a, cell_b, mode), 1.0
    quiet = _shared_silence(ha, hb, silent)
    if quiet >= 1.0:
        return 0.0, 0.0
    na, nb = sum(ha.values()), sum(hb.values())
    total = sum(min(ha[v] / na, hb.get(v, 0) / nb) for v in ha)
    return total - quiet, 1.0 - quiet


def vice_register_compare(orig_samples: list, our_samples: list,
                          mode: str = "overlap") -> dict:
    """The register dimensions from two per-rasterline VICE traces.

    Same keys as wave_compare + adsr_compare + pulse_compare + filter_compare,
    so a row built here is a drop-in for one built from siddump and
    `--baseline` can A/B the two. What differs is the resolution underneath:
    siddump reports one sample a frame, so a value written and overwritten
    inside a frame is not in its trace at all, and on a multiplier-m file
    `m - 1` of every `m` play calls leave no mark.

    **The reduction to a frame is unavoidable, and it is measured rather than
    chosen.** The two sides write at different rasterlines within the frame --
    an original's player near the top of the screen, our packed conversion
    wherever gt2reloc's CIA stub lands -- so comparing rasterline against
    rasterline would report that offset. `vicetrace.agreement` implements four
    per-frame rules; shifting one side by an inaudible 0-48 rasterlines moves
    `last` by up to 2.64 points and `overlap` by 0.13, which is why `overlap`
    is the default and `last` -- what siddump gives -- is the one to distrust.
    See H2G-CONVERSION-METHOD.md section 7.nn.

    The counting dimensions cannot use a graded rule: a count needs a definite
    value per frame. They take `FrameCell.representative`, which is the
    duration-weighted majority -- stable under the same shift where `last`
    aliases.
    """
    wave_cells_o = vicetrace.frame_cells(orig_samples, lambda v: v.ctrl)
    wave_cells_u = vicetrace.frame_cells(our_samples, lambda v: v.ctrl)
    adsr_cells_o = vicetrace.frame_cells(orig_samples, lambda v: v.adsr)
    adsr_cells_u = vicetrace.frame_cells(our_samples, lambda v: v.adsr)
    puls_cells_o = vicetrace.frame_cells(orig_samples, lambda v: v.pulse)
    puls_cells_u = vicetrace.frame_cells(our_samples, lambda v: v.pulse)

    nframes = min(len(wave_cells_o), len(wave_cells_u))
    out: dict = {}

    # --- wave: class agreement, and noise frames per side -------------------
    agree, total = 0.0, 0.0
    o_noise = u_noise = 0
    wave_voices = []
    for vi in range(3):
        va, vt, vo_n, vu_n = 0.0, 0.0, 0, 0
        for f in range(nframes):
            a, b = wave_cells_o[f][vi], wave_cells_u[f][vi]
            # The class is the waveform-select nibble; the gate and the other
            # control bits are excluded here exactly as in wave_compare.
            ca = vicetrace.FrameCell(
                hist=_nibble_hist(a.hist), last=a.last & 0xF0)
            cb = vicetrace.FrameCell(
                hist=_nibble_hist(b.hist), last=b.last & 0xF0)
            if a.representative() & WF_NOISE:
                vo_n += 1
            if b.representative() & WF_NOISE:
                vu_n += 1
            num, w = _graded_agreement(ca.hist, cb.hist, ca.last, cb.last, mode)
            va += num
            vt += w
        wave_voices.append({
            "wave": (va / vt) if vt else None, "frames": round(vt),
            "orig_noise_frames": vo_n, "our_noise_frames": vu_n,
        })
        agree += va
        total += vt
        o_noise += vo_n
        u_noise += vu_n
    out.update({
        "wave": (agree / total) if total else None,
        "wave_frames": total,
        "orig_noise_frames": o_noise,
        "our_noise_frames": u_noise,
        "wave_voices": wave_voices,
    })

    # --- adsr: the envelope pair, compared whole ----------------------------
    agree, total = 0.0, 0.0
    adsr_voices = []
    for vi in range(3):
        va, vt = 0.0, 0.0
        for f in range(nframes):
            a, b = adsr_cells_o[f][vi], adsr_cells_u[f][vi]
            num, w = _graded_agreement(a.hist, b.hist, a.last, b.last, mode)
            va += num
            vt += w
        adsr_voices.append({"adsr": (va / vt) if vt else None,
                            "frames": round(vt)})
        agree += va
        total += vt
    out.update({
        "adsr": (agree / total) if total else None,
        "adsr_frames": round(total),
        "adsr_voices": adsr_voices,
    })

    # --- pulse: how often the duty cycle moves, per side --------------------
    o_ch = u_ch = 0
    o_sp = u_sp = 0
    pulse_voices = []
    for vi in range(3):
        ta = [puls_cells_o[f][vi].representative() for f in range(nframes)]
        tb = [puls_cells_u[f][vi].representative() for f in range(nframes)]
        a_ch, b_ch = _changes(ta), _changes(tb)
        pulse_voices.append({"orig_pulse_changes": a_ch,
                             "our_pulse_changes": b_ch})
        o_ch += a_ch
        u_ch += b_ch
        o_sp += _span(ta)
        u_sp += _span(tb)
    out.update({"orig_pulse_changes": o_ch, "our_pulse_changes": u_ch,
                "orig_pulse_span": o_sp, "our_pulse_span": u_sp,
                "pulse_span": (u_sp / o_sp) if o_sp else None,
                "pulse_voices": pulse_voices})

    # --- filter: the one global cell ----------------------------------------
    def side(samples):
        def col(pick, post=lambda v: v):
            cells = vicetrace.frame_cells_global(samples, pick)
            return [post(c.representative()) for c in cells][:nframes]
        cut = col(lambda s: s.cutoff)
        ctrl = col(lambda s: s.res)
        band = col(lambda s: s.modevol, lambda v: (v >> 4) & 0x07)
        return {
            "filtered_frames": sum(1 for r, b in zip(ctrl, band)
                                   if (r & FILTER_ROUTE) and b),
            "cutoff_changes": _changes(cut),
            "cutoff_travel": sum(abs(cut[i] - cut[i - 1])
                                 for i in range(1, len(cut))),
            "cutoff_range": (max(cut) - min(cut)) if cut else 0,
        }
    o, u = side(orig_samples), side(our_samples)
    out.update({f"orig_{k}": v for k, v in o.items()})
    out.update({f"our_{k}": v for k, v in u.items()})
    out["cutoff_sweep"] = (u["cutoff_travel"] / o["cutoff_travel"]
                           if o["cutoff_travel"] else None)
    out["vice_frames"] = nframes
    out["vice_reduce"] = mode
    return out


def _nibble_hist(hist):
    """A $D404 histogram folded to waveform classes.

    Two control bytes differing only in the gate bit are the same timbre, so
    they must collapse to one bin before the shares are compared -- otherwise
    a voice whose gate falls mid-frame would read as two disagreeing classes.
    """
    out = Counter()
    for value, lines in hist.items():
        out[value & 0xF0] += lines
    return out


# --------------------------------------------------------------------------
# what this run can see, and what it structurally cannot
# --------------------------------------------------------------------------
# The repo's standing rule is: *a metric that cannot see a change is not
# evidence the change did nothing -- say so beside the fix.* It has been
# applied correctly at least seven times and every one of them depended on an
# author remembering it. v0.5.71-74 shipped three separate correct fixes --
# envelope, filter, pulse width -- and moved no column of FIDELITY.md to the
# decimal, because not one dimension below reads a register any of them
# writes. A flat table read as a null result is the most repeated failure mode
# in this project's history.
#
# So each dimension declares the SID registers it is computed from, and the
# harness derives from that which registers nothing here reads. A run can then
# print its own blindness as a *result* instead of leaving it to be
# remembered.
#
# Adding a column means adding an entry here. A column missing from this table
# is invisible to --baseline and absent from the report's own account of what
# it compared, which is the failure the table exists to prevent;
# test_fidelity.py asserts the report header and this registry name the same
# columns.
SID_REGISTERS = (
    ("$D400/$D401", "voice frequency"),
    ("$D402/$D403", "pulse width"),
    ("$D404", "control: waveform select, gate, sync, ring, test"),
    ("$D405/$D406", "envelope: attack/decay, sustain/release"),
    ("$D415/$D416", "filter cutoff"),
    ("$D417", "filter resonance and per-voice routing"),
    ("$D418", "filter mode and master volume"),
)

# Blindness that is not a register: naming a register nobody reads is only
# half the account, and these three have each already been mistaken for a
# result.
NOT_MEASURED = (
    "**note length above `-S3`** -- since v0.5.196, `hold` "
    "(`sound_run_agreement`) reads `$D404` as a *duration*, not only an edge, "
    "scoring whether a note keeps its waveform selected as long as the "
    "original's. But the deficit it exists to catch is a fixed number of "
    "play *calls*, so at `-S4` and above it is a fraction of a frame and "
    "siddump -- one sample a frame -- reports zero: a `hold` of 100% there "
    "means \"not visible\", not \"correct\". Below that rate `--hold-census` "
    "shows most of what remains still is not a length defect: of 432 census "
    "rows, 211 are the next-note fetch and 117 the note's own *slot* "
    "differing rather than the note; the true short/long residue is nine",
    "**a conversion packed above `-S4`** -- siddump samples the SID registers "
    "once per frame whatever the call rate, so a multiplier-5 file has four "
    "calls in five discarded and every gate edge inside them with it. Those "
    "rows read far below the truth: Kings_of_the_Beach_intro scores 61% here "
    "and **96%** under `--equal-calls`, which traces the same play calls at "
    "the original's sampling; Off_the_Cuff 76% against **100%**. Corpus-wide "
    "the gap is about eight points, and it widens as the converter uses the "
    "multiplier more. Read `--equal-calls` for the sequence dimensions of any "
    "row whose multiplier exceeds 4, and `--vice` for the register ones -- it "
    "traces both sides at 312 samples a frame instead of one, so a value "
    "written and overwritten inside a frame is visible. Neither is the "
    "default: `--equal-calls` drops the frame-aligned dimensions, and "
    "`--vice` costs two emulator runs a row",
    "**tempo and row rate** -- no column here scores how long a row "
    "*lasts*, and `--pace` is the mode that does: on this corpus it "
    "finds row-length errors of 10-33%. What the table now does see "
    "is the *accumulated* consequence -- `drift` is the phase error "
    "between the two sides in frames per 1000, which is a different "
    "question from the row length and catches the errors too small to "
    "show up in one gap. A row wrong by a fraction of a frame is "
    "invisible to `--pace` by construction, since a Goattracker row "
    "is whole play calls and the error is zero on most gaps and one "
    "whole frame on the occasional one. What "
    "did change in v0.5.99 is that a conversion is now *played* at the rate "
    "it was packed for: stock siddump calls the play routine `seconds x 50` "
    "times whatever the PSID speed field says (siddump.c:309/325), so a tune "
    "packed at `gt2reloc -S2` used to be traced at half speed. The "
    "tools/siddump-rt build takes `-m` and the harness passes the song's "
    "multiplier, so the two sides now share a real-time axis -- but a row "
    "that is the right length is still not something any column measures -- see --pace",
    "**anything outside the traced window or subtune** -- one subtune per "
    "file, its first few seconds",
    "**master volume** -- `$D418`'s low nibble. The register is listed as "
    "read because `filt` reads the passband bits of the same byte, which is "
    "as fine as a per-register account can be; nothing compares the volume "
    "nibble, and nothing the converter emits can move it",
)


@dataclass(frozen=True)
class Dimension:
    """One number the report prints, and the registers it is derived from.

    `source` is the row key holding the value when it differs from `key` --
    the two count columns report our side only, because the original's count
    is a property of the original and cannot move between two runs.
    """
    key: str
    column: str
    reads: tuple[str, ...]
    kind: str            # fraction | ratio | count
    of: str              # what it compares, in prose
    source: str = ""

    def value(self, row: dict):
        return row.get(self.source or self.key)

    def fmt(self, v) -> str:
        """Exactly how the report prints it -- so `fmt(a) == fmt(b)` is the
        question "would the table have looked any different"."""
        if v is None:
            return "-"
        if self.kind == "fraction":
            return _fmt_pct(v)
        if self.kind == "ratio":
            return f"{v:.2f}"
        return str(int(v))

    def movement(self, a, b) -> float:
        """Magnitude used to rank files, comparable across kinds.

        Fractions and ratios move on their own scale; counts are relativised,
        because 5 pulse writes becoming 2823 and 0.94 becoming 0.95 are not
        the same size of finding.
        """
        if a is None or b is None:
            return 0.0 if a is None and b is None else 1.0
        if self.kind == "count":
            return abs(a - b) / max(abs(a), abs(b), 1)
        return abs(a - b)


_PITCH_REGS = ("$D400/$D401", "$D404")

# Not a SID register: the two columns below are computed from the WAV that
# `sidplayfp` renders, not from siddump. Declared as their `reads` so `What
# this run compared` can say "rendered audio" honestly, and kept OUT of
# SID_REGISTERS so `registers_unread` does not report a register that does
# not exist.
AUDIO = "rendered audio"

DIMENSIONS = (
    # **AND IT NAMES A THIRD OF ITS NOTES FROM A PITCH THAT IS STILL MOVING.**
    # siddump names a note from the frequency on the frame the gate RISES, so a
    # note glided into is named at a point on the ramp rather than at the note.
    # Censused over the corpus at v0.5.421, on the ORIGINAL side (the reference
    # every column scores against, so an attack ambiguous there is ambiguous for
    # both): an attack counts when the name at the attack frame differs from the
    # name four frames later, and **15130 of 47674 attacks -- 31.7% -- do**.
    # Median 24.3% a file, p90 60.3%, worst Nineteen at 74.5%; 64 of 83 files
    # are above 10% and only 9 are at zero.
    #
    # THAT IS A POPULATION AT RISK, NOT AN ERROR RATE, and the difference
    # matters: where both sides glide identically the names agree and nothing is
    # lost. It is the population in which a grid moved by one play call can
    # rename a note that did not change -- measured once, on One_on_One under
    # --regrid, at 29% of that file's melody loss (v0.5.420).
    #
    # NOT CORRECTED, DELIBERATELY. Re-timing the attack to a settled frame would
    # raise agreement, and a shift chosen to raise agreement can only raise
    # agreement -- the same trap `startup_lag` avoids by estimating from the
    # signal rather than fitting. Stated here instead, the way `hold` states the
    # rate at which it goes blind.
    #
    # **AND IT CAN SCORE A CONVERSION WORSE FOR A PITCH THAT MOVED CLOSER TO
    # THE ORIGINAL.** A note is named from the frequency at its attack frame,
    # so a pitch shifted by a fraction of a semitone can cross a note-naming
    # boundary and be renamed -- even when the shift is toward the original.
    # Measured live at v0.5.434, Powerplay_Hockey_USA_vs_USSR.sid voice 0, 60s,
    # subtune 0: --regrid costs melody 0.9930 -> 0.9643 (-2.88pp), and at every
    # attack it renames, the regrid arm's pitch sits CLOSER to the original
    # than the arm that shipped unrenamed --
    #     A#4->A-4  regrid +0.117st from original, no-regrid +0.380st (4 attacks)
    #     D-5->C#5  regrid +0.122st,                no-regrid +0.513st (2 attacks)
    #     G-5->F#5  regrid +0.125st,                no-regrid +0.774st (2 attacks)
    # three to six times closer, and scored 2.88pp worse. The tune's own
    # frequency table sits 0.696 semitones below the semitone grid (siddump
    # calibration -c10B8), which is why its notes sit near naming boundaries
    # at all.
    #
    # TWO QUALIFICATIONS. The improvement is LOCAL to the renamed attacks, not
    # a global pitch gain: over the whole voice the two arms agree on 6 of the
    # 8 notes they share, and the mean offset from the original is +0.467st
    # without --regrid against +0.484st with it -- --regrid does not make this
    # voice's pitch better overall. And the COUNT of renamed attacks is
    # method-dependent, not the property itself: strict positional difflib
    # pairing reads 3, an earlier v0.5.427 run read 7, grouping by note name
    # (the table above) reads 8 -- a handful, depending on how the two attack
    # sequences are aligned, not a fixed number.
    Dimension("melody", "melody", _PITCH_REGS, "fraction",
              "the attack-note sequence with consecutive repeats collapsed "
              "-- blind to a re-struck note, which reads as a longer "
              "sequence rather than a wrong one; and 31.7% of corpus attacks "
              "are named from a frame whose pitch is still gliding, so a grid "
              "moved by one play call can rename a note that did not change "
              "-- and by the same note-naming-boundary effect, a pitch that "
              "moved CLOSER to the original can be scored as a worse match; "
              "see the comment above"),
    Dimension("sequence", "seq", _PITCH_REGS, "fraction",
              "the same sequence uncollapsed"),
    Dimension("pitch_jaccard", "pitch", _PITCH_REGS, "fraction",
              "the set of distinct pitches struck"),
    Dimension("retrigger_ratio", "retrig", _PITCH_REGS, "ratio",
              "how many times as often we strike a note"),
    Dimension("slides", "slides", _PITCH_REGS, "count",
              "frames on which a voice's pitch moved without a retrigger",
              source="our_slides"),
    # The other half of the same question, and the half a count cannot answer
    # -- `cut` exists beside `filt` for exactly this reason.
    Dimension("bend_ratio", "bend", _PITCH_REGS, "ratio",
              "how far the pitch travels within notes, over the original's"),
    Dimension("wave", "wave", ("$D404",), "fraction",
              "per-frame agreement of the waveform-select nibble"),
    Dimension("noise", "noise", ("$D404",), "count",
              "frames whose waveform included noise", source="our_noise_frames"),
    Dimension("adsr", "adsr", ("$D405/$D406",), "fraction",
              "per-frame agreement of the envelope pair"),
    # $D404's bit 0, which `wave` excludes by construction and nothing else
    # read. That exclusion is right for a timbre column and it made a whole
    # class of change unscoreable: --rest-keyoff moves 19 files' bytes and one
    # number on one file. Scored over the gate-*off* frames only -- both sides
    # hold it on most of the time -- so it is the overlap of the silences.
    Dimension("gate", "gate", ("$D404",), "fraction",
              "overlap of the frames each side has the voice released -- "
              "**rises when notes are removed**, so read it next to `retrig` "
              "and both sides' note counts. **Not a note-length measure**, so "
              "do not read its sign against `hold`'s: this is $D404's gate "
              "BIT at the note's close, `hold` is the same register's waveform "
              "nibble at its open, and on Action Biker they read +1.4 frames "
              "long and -1 frame short at the same time while both are "
              "correct"),
    # The only column that can see how *long* a drum sounds. Every other
    # reading of the drum anchors on a gate-edge attack, and that anchor moves
    # when the run's length changes -- which made two corpus comparisons come
    # back flat and blamed the pitch sweep for it. See `noise_runs`.
    # The only column that measures an oscillation *rate*. `slides` counts
    # frames on which the pitch moved and `bend` sums how far -- neither can
    # tell a vibrato from a portamento, and on Commando every "slide" is
    # vibrato (`--vibrato` off takes the count from 245 to zero). A corpus A/B
    # read off `slides` is therefore ranking vibrato rates while appearing to
    # rank slides, which is how the -R0 question got answered twice, differently.
    # **`vib` IS NOT PROPORTIONAL TO THE RATE ERROR, and on short notes it is
    # not even close.** `reversals_by_instrument` counts sign changes per NOTE,
    # so a note of `L` frames oscillating at half-period `p` yields
    # `floor(L / p) - 1` reversals -- a STEP function, not `L / p`. The step is
    # invisible while `L / p` is large and dominates when it is small, because
    # a rate change only registers when it carries the note across a whole
    # half-cycle boundary.
    #
    # Measured, by feeding a synthetic triangle of known reversal count through
    # this very function. A rate change of x1.333 (Goattracker `cmp` 2 -> 1,
    # half-period 4 -> 3 calls) reads as:
    #
    #       note length   600 frames  ->  x1.336     (linear, as expected)
    #                     64          ->  x1.333
    #                     16          ->  x1.333
    #                     12          ->  x1.500
    #                     10          ->  x1.951
    #                      6          ->  x40.0
    #
    # That is what put One_on_One_Jordan_vs_Bird at x2.057 for a x1.333 change
    # at ebc9d1a: all six of its classic-vibrato entries move by at most
    # x1.333, and no weighting of factors that size can reach 2.057 -- the
    # remainder is whole half-cycles newly fitting inside its notes. Verified
    # in isolation with the compensation toggled on one tree: 574 -> 1181 of
    # the original's 756.
    #
    # THE COUNTER ITSELF IS SOUND: amplitude-independent down to one frequency
    # unit, and exact against a known count at every rate once the notes are
    # long. The non-linearity is the note, not the measure -- and NOT the
    # `{a - 1, a, a + 1}` attack skip, which was the obvious suspect and is
    # refuted (the sweep above holds with the skip in place).
    #
    # So: read `vib` as "does it oscillate at roughly the right rate", never as
    # "it is 1.56x too fast". Two files with the same true rate error score
    # differently if their notes differ in length, and a file whose notes are
    # a few half-periods long can swing wildly on a change that is small in
    # calls. See `test_reversal_step_function`.
    Dimension("reversal_ratio", "vib", ("$D400/$D401",), "ratio",
              "how fast the pitch oscillates, over the original's rate -- a "
              "STEP function of the rate on short notes, not proportional"),
    # The other half of `vib`, and the half a count is structurally incapable
    # of answering -- the same pairing as `cut` beside `filt` and `bend`
    # beside `slides`, and the last mechanism here that had only a count.
    #
    # WHAT IT READS. The frequency register between gate rising edges, reduced
    # to the median peak-to-peak swing over three consecutive turning points
    # (so a slide underneath cancels), as a fraction of the pitch it swings
    # around; then per instrument, then the median of the per-instrument
    # ratios. Restricted to the records carrying a non-zero vibrato byte and
    # no competing pitch bit (`vibrato_records`) -- unrestricted, the same
    # statistic reports 273% and 397% "depths" that are portamentos and drum
    # sweeps, and a corpus median of about 1.0.
    #
    # WHAT IT IS BLIND TO.
    # * **Whether an oscillation exists at all.** A half-cycle needs two
    #   turning points, so a side that emits no vibrato contributes no
    #   samples and the instrument simply leaves the pairing -- the column
    #   prints `-` where `vib` prints 0.00x. Read the two together.
    # * **Where the swing sits.** It is a peak-to-peak magnitude, so a
    #   vibrato centred a semitone off the note reads exactly the same as one
    #   centred on it. `melody` is what sees that.
    # * **The waveform of the oscillator.** A triangle and a square of equal
    #   excursion are one number here; the players' and Goattracker's LFOs are
    #   both triangles reached differently (_classic_vibrato_entry), and no
    #   column distinguishes them.
    # * **A slide under the vibrato.** A half-cycle carries whatever
    #   portamento runs beneath it. The median over half-cycles damps that
    #   rather than removing it, and a *pure* slide contributes nothing at all
    #   (no turning points).
    # * **Rate.** Deliberately: `vib` is the rate, and conflating them is what
    #   made this unmeasurable. Note that Goattracker *integrates* its speed,
    #   so an emitter that shortens `cmp` shortens the swing with it -- a
    #   change to the rate moves this column too, and the two must be read
    #   side by side before either is called a fix.
    Dimension("depth_ratio", "depth", ("$D400/$D401",), "ratio",
              "how far our vibrato swings, over the original's -- median over "
              "the instruments that carry a vibrato byte, **blind to whether "
              "an oscillation exists at all**, which is `vib`'s question"),
    Dimension("noise_run_agreement", "nrun", ("$D404",), "fraction",
              "instruments whose noise runs as long as the original's"),
    # Note *length*, which CLAUDE.md has recorded as unmeasured for most of
    # this project's life. `nrun` compares noise runs and is silent about a
    # pitched note; `tail` reads the envelope after the gate closes, not how
    # long the waveform stayed. This reads the frames a note keeps a waveform
    # selected within its own slot -- see `sound_runs`, and read
    # `sound_run_delta` beside it while the agreement is zero.
    # `--hold-census` says what the disagreements are made of, and the answer
    # is mostly not note length. **RE-CENSUSED AT `-t 180` AT v0.5.460 -- the
    # 432-instrument figures this comment used to carry (211 fetch, 117 slot,
    # residue nine) were taken at `-t 60` and are HISTORY.** Over **818
    # instruments in 88 files**:
    #
    #     match 280 (34.2%)   fetch 399 (48.8%)   slot 131 (16.0%)
    #     thin 2   sparse 1   gap 0   short 1   long 4
    #
    # So the residue that is ACTUALLY about note length is **five of 818**, and
    # `fetch` -- a real defect, and one this repo has an open task for -- is
    # nearly half.
    #
    # **WHAT THE COLUMN'S NUMBER DOES NOT MEAN, because the census invites the
    # misreading it exists to prevent.** `hold` reads 34.2% here, and that is
    # NOT "65.8% of instruments have a note-length defect". The column asks a
    # factual question -- do the notes sound for as many frames? -- and counts
    # exact matches; the census answers WHY NOT, and says of `slot`, `sparse`,
    # `thin` and `gap` that they are not length differences at all. Those four
    # are 134 of the 818, so a reader who takes every miss for a defect
    # over-counts by 16 points: the same number, re-based on matches plus
    # documented non-defects, is **50.6%**.
    #
    # **THE COLUMN IS NOT CHANGED TO EXCLUDE THEM, and that is deliberate.**
    # `sound_run_agreement` is element 6 of the state tuple `presets.play()`
    # builds, so it is one of `fidelity_better`'s acceptance terms: re-basing
    # it re-opens every per-song decision the search has made, and would need
    # the eight-toggle walk re-run and diffed before anything could be trusted.
    # `tests/test_hold_census.py` pins the pair on purpose --
    # `test_the_population_is_the_columns_denominator` and
    # `test_the_match_count_is_the_columns_numerator` -- so the census and the
    # column cannot drift apart. Attribution belongs in the census; the column
    # measures agreement. See `classify_hold` and section 7.xxxx.
    Dimension("sound_run_agreement", "hold", ("$D404",), "fraction",
              "instruments whose notes sound for as many frames as the "
              "original's -- **blind to the deficit it measures above `-S3`**, "
              "because that deficit is a fixed number of play *calls* and a "
              "call is a quarter-frame at `-S4`. The -1 it reads on every file "
              "is the `$09` firstwave frame sitting below $10 and breaking the "
              "run, not a short note; `gate` counts that same frame's gate bit "
              "as a surplus, which is why the two report opposite signs"),
    # The column that sees a mechanism emitted one frame out of phase. `wave`
    # averages 3000 frames, so a wrong opening on a 43-note instrument is a
    # rounding error in it; `nrun` compares run lengths and is position-
    # independent by design, so a run that is right but a frame early scores
    # perfect. Both read $D404 and neither could see that two emitters opened
    # on the effect where the player opens on the record's own waveform.
    Dimension("onset_agreement", "onset", ("$D404",), "fraction",
              "instruments whose notes open on the original's waveforms"),
    # What happens after the gate closes. `adsr` compares the pair while the
    # note plays and agrees; both sides also gate off on the same frame, so
    # $D404 says nothing either. See `release_tails`.
    Dimension("release_tail_agreement", "tail", ("$D405/$D406",), "fraction",
              "instruments whose notes end with the original's release"),
    Dimension("pulse", "pul", ("$D402/$D403",), "count",
              "frames on which the duty cycle moved",
              source="our_pulse_changes"),
    # `pspan` is to `pul` what `cut` is to `filt`, and for the identical
    # reason. A count says whether the duty cycle moves at all; it cannot say
    # whether it goes anywhere, and it reads a sweep taken in finer steps as
    # more movement. v0.5.174 is exactly that case -- a Goattracker pulse speed
    # is a signed byte, so a player step of 224 a frame comes out as 127 twice,
    # and `pul` went from 3/236 to 338/236 on 5_Title_Tunes for a sweep that
    # covers slightly *less* of the band than the original's.
    Dimension("pulse_span", "pspan", ("$D402/$D403",), "ratio",
              "how wide a band the duty cycle covers, over the original's"),
    # `pphase` is to `pspan` what `pspan` is to `pul`, one question further
    # out: a count says whether the duty cycle moves, a span says how far it
    # gets, and NEITHER says where in the band a note opens. The player's
    # accumulator free-runs and is never reseeded at a note, so its notes open
    # all over the sweep; Goattracker reloads the pulse pointer from the
    # instrument, so every one of ours opens on the record's own width. Both
    # sweeps can be the right SIZE and still sound unlike each other, and on
    # 5_Title_Tunes they are: instrument 5's per-note travel is 0.83x of the
    # original's (instrmap's own table) while it opens on 1 bucket against 5.
    # Restricted to the voices whose original opens on more than one bucket --
    # see pulse_compare -- because a voice with a fixed width has no phase to
    # reproduce and would score a free 1.00.
    Dimension("pulse_phase", "pphase", ("$D402/$D403",), "ratio",
              "distinct duty cycles a note opens on, over the original's"),
    # The filter is two dimensions because it is two questions, and one of
    # them is not a count: `filt` is whether we filter at all, `cut` is
    # whether the cutoff then moves as far as the original's. A count reads
    # the same for a sweep taken in finer steps and one that runs three times
    # too far, which is exactly the pair v0.5.72's first reader confused.
    Dimension("filtered", "filt", ("$D417", "$D418"), "count",
              "frames with a voice routed into the filter and a passband "
              "selected", source="our_filtered_frames"),
    Dimension("cutoff_sweep", "cut", ("$D415/$D416",), "ratio",
              "how far the cutoff travels, over the original's travel"),
    # **The first column here that measures *when* rather than *what*.** Every
    # dimension above compares content at aligned frames; none of them can see
    # two copies of the right music parting company, and this report said so
    # in its own "What this does not say" for the whole of its life.
    #
    # `--pace` was the answer to the tempo half of that and is structurally
    # blind to the rest: it averages gap ratios, a Goattracker row is a whole
    # number of play calls, so a row wrong by a *fraction* of a frame is zero
    # on most gaps and one whole frame on the occasional one -- an expected
    # ratio of exactly 1.000. Powerplay reads `median 1.000, IQR 0.980-1.000
    # over 348 gaps` while its notes arrive 24 frames early. Integrating sees
    # it; averaging cannot.
    #
    # Reads the pitch registers because its input is difflib-matched note
    # *onsets*, which is what `melody` is built from -- but it uses their
    # frame positions, which `melody` discards. A file can therefore score
    # 100% melody and drift badly, and 17 of them do.
    # The listener's rule, and the only column here that is about the
    # tune's LENGTH rather than its content. Every other dimension is
    # satisfied by a conversion that plays the right music at the right
    # speed forever -- Action Biker reads drift +0.0 and retrig 1.00 at
    # three times the original's length. `-` means the original does not
    # stop inside the window, so there is no ending to match, OR ours is
    # still playing with too little window left to prove a surplus. See
    # length_compare: not-measured is reported as not-measured.
    Dimension("length_delta", "len", _PITCH_REGS, "ratio",
              "seconds ours runs past the original's ending"),
    # **Beside `len` because it is the same measurement read the other way**:
    # `len` asks whether we stop where the original stops, and this asks how
    # much of the original the window saw at all. A row at 25% is describing
    # the first quarter of a tune, and every column above it should be read as
    # a statement about that quarter. A `-` means the length probe could not
    # place the original's ending either way. Where the original outlasts the
    # probe entirely the figure is an UPPER bound -- `window_coverage_bounded`
    # marks those rows -- because all that is known is that the tune runs past
    # `--length-probe` times the window.
    Dimension("window_coverage", "cov", _PITCH_REGS, "fraction",
              "share of the original's own length this window contained"),
    Dimension("drift_per_1000", "drift", _PITCH_REGS, "ratio",
              "frames of lead (negative) or lag we accumulate per 1000, from "
              "a Theil-Sen fit over matched onsets -- **the startup lag is "
              "the fit's intercept**, so unlike every column above it needs "
              "no lag correction"),
    # THE FIRST TWO COLUMNS IN THIS REGISTRY THAT ARE NOT COMPUTED FROM A SID
    # REGISTER AT ALL. Everything above reads siddump; these read the WAV
    # `sidplayfp` renders from each side, which is why their `reads` is the
    # AUDIO sentinel rather than an address. That also means the calibration
    # in docs/SOUND-CALIBRATION.md governs how much they can be trusted --
    # and at v0.5.453 it reports `pass: false`, so read the blind spot in the
    # `aud` description below as a live warning rather than boilerplate.
    Dimension("aud", "aud", (AUDIO,), "fraction",
              "per-frame agreement of the rendered sound's log-mel spectrum, "
              "level removed -- timbre, filter, envelope shape. Absent unless "
              "the run was taken with --sound; both-silent frames carry no "
              "weight; it rises when events are removed, so read it beside "
              "the attack counts. **A CORRECT FIX CAN READ WORSE HERE**: "
              "sound_calibrate.py's known-bad check scores all three "
              "documented fixes under its own noise floor and TWO of them in "
              "the wrong direction, because a per-frame agreement falls when "
              "a fix unmasks a defect the old behaviour hid (CLAUDE.md's "
              "Human_Race case, where the right clock cost melody 65 -> 56%)"),
    Dimension("loud", "loud", (AUDIO,), "fraction",
              "per-frame agreement of the rendered loudness envelope -- the "
              "first column that reads the master-volume nibble; `loud_ratio` "
              "in --json is our overall level over the original's"),
)


def dimensions_present(row: dict) -> list[str]:
    """The dimensions this row actually compared.

    Not every measured row compares every dimension: a file whose voices never
    select a waveform has `wave` None, and a row that did not convert compares
    nothing at all. Recorded per row so a run can say what it covered rather
    than what it intended to cover.
    """
    return [d.key for d in DIMENSIONS if d.value(row) is not None]


def registers_read(keys) -> set[str]:
    got = set(keys)
    return {r for d in DIMENSIONS if d.key in got for r in d.reads}


def registers_unread(keys) -> list[tuple[str, str]]:
    """The SID registers no dimension in `keys` is computed from.

    This is the list a change has to land in to be invisible here, and it is
    where v0.5.71's envelope fix, v0.5.72's filter and v0.5.73's pulse-width
    sweep all landed.
    """
    seen = registers_read(keys)
    return [(reg, what) for reg, what in SID_REGISTERS if reg not in seen]


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
# Options convert() takes that are not booleans read from the `always` block:
# three per-song shaping values, the two named differently in the JSON, and the
# packing factor, which belongs to gt2reloc rather than to the conversion.
_PER_SONG_OPTS = ("max_rows", "pack", "prune", "dedup",
                  "real_firstwave_instruments", "hard_restart_frames")
_RENAMED_OPTS = {"fmt": "format"}
_NOT_CONVERT_OPTS = ("gt2reloc", "multiplier")


def _wants_int(annotation) -> bool:
    """True if a convert() parameter's own annotation names int, not bool.

    bool is a subclass of int, so an isinstance check on a *value* cannot
    separate `hard_restart_frames: int | None` from `slides: bool` -- both
    would accept an int. The signature's annotation can: every bool option
    convert() takes is spelled exactly `bool`, never a union that also
    contains it, so "int appears, bool does not" reads the same distinction
    the signature already draws, for both a bare `int` and a `int | None`.
    """
    if annotation is int:
        return True
    args = typing.get_args(annotation)
    return int in args and bool not in args


def _convert_options() -> tuple:
    """Every keyword convert() accepts, minus the inputs that are not options.

    Derived rather than listed. The hand-maintained version shipped two
    features dead -- `--slides` (AUDIT.md's first verified defect) and
    `--filter`, which v0.5.72 wired into convert() and README while every
    measurement still ran with it off. A list in a third place is a third place
    to forget. test_preset_passthrough.py fails if this stops covering
    convert().
    """
    params = inspect.signature(convert).parameters
    return tuple(n for n in params if n not in ("sid_path", "log"))


def stopped_at(voices, seconds: int) -> float | None:
    """The second this side's music STOPS, or None if it is still playing.

    `original_ended` asks the same question of the original and answers with a
    comparison WINDOW; this answers with the second itself, and asks it of
    either side, so the two can be compared. The silence test is the same one
    and deliberately so -- a rest is not an ending, so the trailing quiet has
    to exceed twice the tune's own largest gap between attacks and five
    seconds outright before it counts as over.
    """
    frames = [f for v in voices for f in v.attack_frames]
    if not frames:
        return None
    window = seconds * 50
    last = max(frames)
    ordered = sorted(frames)
    gaps = [b - a for a, b in zip(ordered, ordered[1:])]
    biggest = max(gaps) if gaps else 0
    if window - last <= max(2 * biggest, 5 * 50):
        return None                 # still playing when the window ran out
    return last / 50.0


def length_compare(orig, ours, seconds: int) -> dict:
    """Does our conversion END where the original ends, within +-5 seconds?

    A listener's rule and a CLAUDE.md invariant, and until this NO column
    enforced it. `drift`, `retrig` and `--pace` all measure the rate of a ROW
    and are every one of them satisfied by a conversion that plays the right
    music at the right speed **forever**: Action Biker reads `drift +0.0` and
    `retrig 1.00` while running three times too long. The cause is a property
    of the target format -- Hubbard's `$FE` means *tune ended*, a Goattracker
    orderlist cannot say it, and `--legal-restart` turns it into a restart at
    position 0 -- so the surplus is real music the original never plays.

    **THE COLUMN'S BLINDNESS IS THE POINT OF ITS DESIGN.** Our side loops, so
    where it does not stop inside the window all we know is a LOWER BOUND on
    how long it runs: `seconds - orig`. That bound is only worth reporting when
    it already exceeds the tolerance. Action Biker is the case that forces
    this -- its original's last attack is at 59.54 s and the report's window is
    60 s, so the window ends where the tune does and the surplus is entirely
    outside it. Scoring that as a pass would be a lie of exactly the kind this
    repo keeps catching, so it reports `-` instead: not measured, rather than
    measured and fine.

    Returns `length_delta` in seconds, ours minus the original's, positive
    where we run long; `length_bounded` when our side never stopped, so the
    delta is a floor and the true figure is worse.
    """
    o = stopped_at(orig, seconds)
    if o is None:
        # The original does not stop inside the window, so there is no ending
        # for ours to match and the rule does not apply to this row.
        return {}
    u = stopped_at(ours, seconds)
    if u is not None:
        return {"orig_ends_at": round(o, 2), "ours_ends_at": round(u, 2),
                "length_delta": round(u - o, 2), "length_bounded": False}
    floor = seconds - o
    if floor <= LENGTH_TOLERANCE:
        # Still playing, but the window leaves no room to prove a surplus.
        return {"orig_ends_at": round(o, 2), "ours_ends_at": None,
                "length_delta": None, "length_bounded": True}
    return {"orig_ends_at": round(o, 2), "ours_ends_at": None,
            "length_delta": round(floor, 2), "length_bounded": True}


# The listener's rule, in seconds. "The original and the H2G should have the
# same length +- 5 seconds."
LENGTH_TOLERANCE = 5.0
# How much longer than the run's window to look when the original is still
# sounding at the edge. It was 3 until v0.5.416, chosen against Action Biker
# alone: its original ends at 59.54s and ours loops with a period of 61.44s, so
# anything above 2x separates them. That reasoning was sound and the number was
# too small, which a census over the whole corpus settled -- 83 originals traced
# at four windows and reduced with `stopped_at`, the same function the column
# uses:
#
#       window     originals that STOP
#         60 s       2
#        180 s       6      <- what the report reached at factor 3
#        600 s      14
#       1800 s      14      <- saturated; a wider window finds nothing more
#
# So 10 rather than 3, and 10 rather than 30 because the set SATURATES at 600s:
# tripling the window again adds not one file. The eight it buys are Confuzion
# (305.08s), Flash_Gordon (374.96), Food_Feud (245.40), Knucklebusters (195.44),
# Rock_Tells_the_Tale (380.84), Saboteur_II (249.18), Sanxion (336.98) and
# Zoolook (259.22).
#
# COST WAS NEVER THE CONSTRAINT and that is worth stating, because "probe
# further" reads expensive: a 600s siddump of one original takes 0.25s, and the
# whole 83-file four-window census above ran in 119 seconds. The probe also
# traces OUR side only when the original turns out to end, so the long second
# trace falls on 14 files rather than 83.
#
# **AND 14 IS THE CEILING, NOT A STAGING POST.** The other 69 originals do not
# stop within half an hour -- they loop, so there is no ending for ours to
# match and the rule is INAPPLICABLE to them rather than unmeasured. A file
# whose original outlasts the probe still reads `-`, which remains the column
# declining to score what it cannot see rather than passing it.
LENGTH_PROBE_FACTOR = 10


def original_ended(orig, seconds: int) -> int | None:
    """Seconds to compare, when the original's subtune ends inside the window.

    Hubbard's `$FE` track byte means *tune ended*. A Goattracker orderlist has
    no way to say that -- `--legal-restart` turns it into a restart at position
    0, which is what makes the file packable at all -- so where the original
    stops inside the traced window our conversion plays the tune again, and
    every sequence column is charged for the surplus. That is a property of the
    target format, not of the conversion: Geoff Capes reads `retrig` 3.21 and
    `melody` 49% over 60 s, and `retrig` 1.02 and `melody` 100% over the 17 s
    this rule gives it (its original's last attack is frame 768). Both it and
    Kings of the Beach ingame -- 7.82 and 23% against 1.04 and 98% over 8 s --
    sat in
    the report's *plays something else* bucket on that arithmetic.

    **The test is against the tune's own pacing, not a fixed fraction of the
    window**, because a rest is not an ending: a file that pauses for four
    seconds mid-tune must not be truncated at the pause. The trailing silence
    has to exceed twice the largest gap *between* the original's own attacks,
    and five seconds outright, before the tune counts as over. Human_Race's
    tail of 144 frames against its own gaps stays a full-length row; Geoff
    Capes' 2232 does not.

    Returns the window to use, in whole seconds, or None to leave it alone.
    Truncation can only *remove* our surplus, so it flatters every column it
    touches -- which is why it is gated on the original stopping rather than on
    the two sides disagreeing, and why the row records `original_ends` and the
    report names the files it applied to.
    """
    frames = [f for v in orig for f in v.attack_frames]
    if not frames:
        return None
    window = seconds * 50
    last = max(frames)
    tail = window - last
    ordered = sorted(frames)
    gaps = [b - a for a, b in zip(ordered, ordered[1:])]
    biggest = max(gaps) if gaps else 0
    if tail <= max(2 * biggest, 5 * 50):
        return None
    # One second past the last attack, so the note's own release is inside the
    # window, and never longer than the caller asked for.
    ended = min(seconds, last // 50 + 2)
    return ended if ended >= 5 else None


def shortening_fate(ended: list[dict]) -> str:
    """What became of the files whose comparison window the length rule cut.

    READ OFF THE DATA, NEVER ASSERTED. This clause used to say "the shipped
    `.sng` still plays forever" of every shortened row, which was true while
    the only repair was a restart at position 0 and went false the moment one
    was parked -- at v0.5.431 both shortened corpus rows carry
    `length_bounded` false, i.e. they END. `length_compare` sets that flag
    exactly when our side did not stop inside the long probe, so it is the
    thing to ask.

    A sentence a report asserts about every row is a sentence that can go
    false without anything failing, which is why this is a function with a
    test rather than a string.
    """
    forever = [r for r in ended if r.get("length_bounded")]
    stops = [r for r in ended if not r.get("length_bounded")]
    if forever and stops:
        return (f"**{len(forever)} of them still play forever** and "
                f"{len(stops)} now END, having been parked")
    if forever:
        return "**every one of them still plays forever**"
    return ("**every one of them now ENDS** -- each was parked on a silent "
            "pattern, so the shortening is a measurement necessity here and "
            "nothing more")


def length_rule_failures(rows: list[dict]) -> list[dict]:
    """Rows whose MEASURED length delta actually breaches LENGTH_TOLERANCE.

    `original_ends` marks every row whose comparison WINDOW was shortened by
    `original_ended` -- a different question from whether the rule was
    *broken*. That shortening fires whenever the original stops inside the
    window, whether or not our side also stops close to it: Geoff Capes and
    Kings of the Beach ingame are both in that set and both read `length_delta`
    of +0.16s and +0.92s (see `length_compare`, called before the window
    shrinks), nowhere near the +-5s tolerance. Counting the shortened set as
    failures reported two passing files as a defect queue.

    A row can appear here only if it is also in the shortened set: outside
    it `length_compare` is never called (see `_measure`) and `length_delta`
    is never populated at all -- which is the existing "the column is blind
    past the window edge" caveat, not something this function needs to
    re-derive.
    """
    return [r for r in rows
            if r.get("length_delta") is not None
            and abs(r["length_delta"]) > LENGTH_TOLERANCE]


def _preset_opts(doc: dict, name: str) -> dict:
    entry = (doc.get("songs") or {}).get(name, {})
    always = doc.get("always", {})
    opts: dict = {
        "max_rows": entry.get("max_rows", 94),
        "pack": bool(entry.get("pack")),
        "prune": bool(entry.get("prune")),
        "dedup": bool(entry.get("dedup")),
        "fmt": always.get("format", FORMAT_GTS5),
        "tempo": always.get("tempo", "auto"),
        # Per song, like the four above: which GT instrument numbers get the
        # real-waveform firstwave byte -- a decision only meaningful for a
        # specific instrument in a specific file (see convert()'s docstring),
        # never a bool the generic `always`/per-song loop below could carry.
        "real_firstwave_instruments": tuple(
            entry.get("real_firstwave_instruments") or ()),
        # Per song, and read with `entry.get(...) or None` rather than the
        # generic loop below: an explicit 0 here means "no override", the
        # same as unset, which is a per-option idiom the generic loop does
        # not know and should not guess at for every int option. It used to
        # also be the ONLY way to keep an int option out of the generic
        # loop's `bool()` coercion (a frame count of 4 arrived as True, then
        # 1) -- that reason is gone now that the loop below reads the
        # annotation, so a *future* int option does not need to be added
        # here just to survive it. Kept hand-listed anyway for the 0-vs-None
        # idiom above, which is genuinely per-option.
        "hard_restart_frames": entry.get("hard_restart_frames") or None,
    }
    hints = typing.get_type_hints(convert)
    params = inspect.signature(convert).parameters
    for opt in _convert_options():
        if opt in opts or opt in _PER_SONG_OPTS:
            continue
        key = _RENAMED_OPTS.get(opt, opt)
        # A song entry overrides `always`, so an option that is right for a few
        # files and wrong corpus-wide can be recorded per song. Without this a
        # per-song key would be read by nothing -- the shape in which `--slides`
        # and `--filter` each shipped dead (see _convert_options), and which
        # `presets.py --fidelity` would otherwise reproduce for
        # `no_test_restart`.
        raw = entry[key] if key in entry else always.get(key)
        if _wants_int(hints.get(opt)):
            # bool(4) is True, and convert() would then read the option as
            # 1 -- an int option must never go through bool(). An absent
            # value takes convert()'s own default rather than False, and a
            # bare True/False (bool is a subclass of int, so JSON `true`
            # would decode as one -- and this is also the shape a test
            # handing `_preset_opts` a stand-in value uses) passes through
            # unchanged rather than being renumbered by int().
            if raw is None:
                opts[opt] = params[opt].default
            elif isinstance(raw, bool):
                opts[opt] = raw
            else:
                opts[opt] = int(raw)
        else:
            opts[opt] = bool(raw)
    return opts


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


def git_label(root: Path | None = None) -> str | None:
    """`git rev-parse --short HEAD`, with `-dirty` when the tree is modified.

    The version alone does not identify a measurement: several commits share
    one version during a branch's life, and a dirty tree shares its version
    with the commit it is not. A run taken from a half-applied edit has cost
    this project two re-runs and the report had no way to say it happened.

    Scoped to the directory holding this project rather than the whole
    checkout: this repo carries unrelated siblings, and their edits say
    nothing about a conversion. Returns None wherever git does not answer --
    an unlabelled report is worse than this, but not by enough to fail a run.
    """
    root = root or Path(__file__).resolve().parent.parent
    try:
        head = subprocess.run(
            ["git", "-C", str(root), "rev-parse", "--short", "HEAD"],
            capture_output=True, text=True, timeout=15, stdin=subprocess.DEVNULL)
        rev = head.stdout.strip()
        if head.returncode != 0 or not rev:
            return None
        st = subprocess.run(
            ["git", "-C", str(root), "status", "--porcelain", "--", "."],
            capture_output=True, text=True, timeout=60, stdin=subprocess.DEVNULL)
        return rev + ("-dirty" if st.stdout.strip() else "")
    except (OSError, subprocess.SubprocessError):
        return None


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


def _drift_gate_skip_declined(sid: Path, subtune: int) -> bool:
    """Whether this file/subtune carries the outer gate's skip counter *and*
    `effective_frames` declines to correct for it -- the exact condition
    `drift`'s docstring names as producing `-1/(skip+1)` per frame. Re-detects
    the player rather than threading `Detection`/`SongSpeeds` through
    `_measure`, the same way
    `test_drift.test_the_drift_is_the_outer_gates_skipped_call` establishes
    the relation: `Delta.sid`/`Tarzan.sid`/`Thrust.sid` correct (skip < 100)
    and `IK_plus.sid`/`Ricochet.sid`/`Sanxion.sid` decline (skip > 100).

    Returns False both where the file has no such gate at all (most of the
    corpus) and where detection fails -- a row that does not carry this
    mechanism is not evidence either way, and the caller only wants a count
    of the ones that do.
    """
    try:
        det_sid, det = _detect_tables(load_sid(str(sid)), lambda *a, **k: None)
        sp = find_song_speeds(det_sid, det if det.can_convert else None)
    except Exception:  # noqa: BLE001 -- a file this fails on is not the mechanism
        return False
    skip = sp.skip_for(subtune) if sp else None
    if not skip:
        return False
    raw = sp.frames_for(subtune)
    if raw is None:
        return False
    return effective_frames(sp, subtune, skip_gate=True) == raw


def measure(sid: Path, workdir: Path, opts: dict, args,
            multiplier: int = 1) -> dict:
    """One file, end to end, plus the record of which dimensions it compared.

    The dimension list is stamped here rather than inside `_measure` because
    every one of that function's exits is a different amount of measurement --
    none at all for a file that would not convert, all but `wave` for one
    whose voices never select a waveform -- and a row that claims a dimension
    it did not compute is exactly the misreading this is here to stop.
    """
    row = _measure(sid, workdir, opts, args, multiplier)
    row["dimensions"] = dimensions_present(row)
    return row


def _measure(sid: Path, workdir: Path, opts: dict, args,
             multiplier: int = 1) -> dict:
    """One file, end to end: convert -> pack -> trace both -> compare.

    `multiplier` is the song's gt2reloc -S value, a property of its player
    rather than a conversion option, so it rides beside `opts` instead of in
    it -- convert() takes no such keyword. It reaches the packing step only;
    siddump cannot honour it (see pack_sid).
    """
    sub = resolve_subtune(sid, args.subtune)
    # Every row carries the settings it was taken at, so a saved run is
    # self-describing: --baseline refuses to compare two runs traced at
    # different seconds or subtunes, and it can only do that if the file says.
    row: dict = {"file": sid.name, "options": opts, "multiplier": multiplier,
                 "subtune": sub, "seconds": args.seconds,
                 "version": __version__, "label": getattr(args, "label", None)}
    try:
        sng = convert(str(sid), log=lambda m: None, **opts)
    except Exception as exc:  # noqa: BLE001 -- a file that will not convert is a result
        row["status"] = "not converted"
        row["detail"] = f"{type(exc).__name__}: {exc}"
        return row

    # The converter's own output, hashed before the harness touches it. This
    # is what separates "the change is invisible to every dimension measured"
    # from "the change reached nothing" -- two readings of the same flat
    # table, and the second one has shipped here twice (--slides for four
    # versions, --filter for two). Without it an A/B cannot tell them apart.
    #
    # **SHA-1, TRUNCATED TO 12 HEX CHARS, over the bytes `convert()` returns.**
    # Spelled out because getting it wrong costs a session rather than a
    # minute: a scratch probe hashed the same bytes with sha256, found its
    # digest differed from this column on ALL 83 corpus files, and filed that
    # as an unexplained divergence between the harness's conversion path and
    # `convert(**_preset_opts(doc, name))`. There is no such divergence --
    # `tests/test_output_sha.py` pins 83 of 83 agreement -- and a systematic
    # disagreement on *every* file is the signature of a different reduction,
    # never of a different input. Compare a sha against this column only after
    # checking you computed it the same way.
    row["output_sha"] = hashlib.sha1(sng).hexdigest()[:12]
    # Per-subtune, so an A/B can name WHICH subtune's bytes moved rather than
    # only that the file's did -- see subtune_content_shas.
    row["subtune_shas"] = subtune_content_shas(sng)

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
    # Read from the player `opts` selects, not from the file: a file with two
    # engines has two tables and they need not be tuned alike (Powerplay
    # Hockey). See engine_freq_table.
    cal, ft = table_calibration(sid, opts)
    if cal:
        row["calibration"] = {"detune": round(ft.detune, 3), "c": cal}
    seconds = args.seconds
    a = run_siddump(local_orig, seconds, sub, args.siddump, cal)
    # Where the original's subtune ends inside the window, compare over the
    # music it plays rather than over our restart of it. See original_ended.
    ended = original_ended(a, seconds)
    if ended is not None and ended < seconds:
        # `seconds` in the row stays the run's own `-t`, because
        # `_FATAL_SETTINGS` compares it between a baseline and the current
        # tree: a window this file shortened for itself is a fact about the
        # file, not a setting that differed between two runs, and writing it
        # here would make every `--baseline` across this change refuse with
        # `seconds 60 -> 17`. The shortening is reported as `original_ends`.
        # THE LENGTH RULE IS MEASURED HERE, BEFORE THE WINDOW SHRINKS, and it
        # has to be: after the shortening both sides are cut to the same
        # `seconds` and the delta is 0 by construction, which is the shim this
        # column exists to expose rather than to join. It costs one extra
        # trace of OUR side over the full window, and only on the files that
        # shorten -- which are exactly the files that can fail the rule, so
        # the cost falls where the finding is.
        row.update(length_compare(
            a,
            run_siddump(packed, seconds, sub, args.siddump,
                        calls=getattr(args, "calls_per_frame", None) or multiplier),
            seconds))
        row["original_ends"] = seconds = ended
        a = run_siddump(local_orig, seconds, sub, args.siddump, cal)
    elif ended is None:
        # THE COLUMN'S BLIND SPOT, and it is the interesting half. `ended` is
        # None when the original is still sounding at the window edge -- which
        # covers BOTH a tune that genuinely plays on AND a tune that stops
        # half a second before the trace does, and nothing inside this window
        # can tell those apart. Action Biker is the second kind: its last
        # attack is at 59.54s against a 60s window, so it read `-` here while
        # running three times too long at its real length.
        #
        # So probe: trace the ORIGINAL over a longer window and ask the same
        # question again. Only if it ends there is our side traced too, which
        # is what keeps this affordable -- the second trace falls on the files
        # that can actually fail the rule, exactly as the shortening branch
        # above does. The probe is skipped when the original has no attacks at
        # all, and when a caller has pinned the window (`--length-probe 1`).
        factor = getattr(args, "length_probe", None) or LENGTH_PROBE_FACTOR
        if factor > 1 and any(v.attack_frames for v in a):
            long_seconds = seconds * factor
            a_long = run_siddump(local_orig, long_seconds, sub, args.siddump, cal)
            if original_ended(a_long, long_seconds) is None:
                # The original does not end even here, so the rule cannot apply
                # to this file at all. Recorded rather than left silent: the
                # report's honest ceiling is a count of these, and without a
                # marker "not measured" and "cannot be measured" look the same
                # in the rows -- the distinction `compare_runs` had to learn
                # for subtunes, one column over.
                row["length_never_ends"] = True
                # The probe's own window, so `cov` can state the UPPER bound
                # it implies. Deliberately NOT `length_probe_seconds`: that
                # key means "a length delta was measured over this window"
                # and `compare_runs` selects probed rows by its presence, so
                # setting it here would put rows with no delta into that set.
                row["length_never_ends_seconds"] = long_seconds
            else:
                row.update(length_compare(
                    a_long,
                    run_siddump(packed, long_seconds, sub, args.siddump,
                                calls=getattr(args, "calls_per_frame", None)
                                or multiplier),
                    long_seconds))
                # Named so a reader can see the figure did not come from the
                # run's own `-t`: a delta measured over the probe's window is
                # not comparable to one measured over 60s, and the report says
                # which. Left in terms of the factor rather than a literal
                # 180s, which is what it said until the factor moved to 10.
                row["length_probe_seconds"] = long_seconds
    # **What SHARE of the tune this window actually scored** -- so a reader can
    # tell a scored whole tune from a scored prefix without re-running the
    # census. Only 2 of 89 corpus files are fully contained at `-t 60`, and
    # every other row is a prefix whose columns describe the opening of a tune
    # rather than the tune; until this there was nothing in the table saying
    # which was which.
    #
    # Derived entirely from what the length rule already measured, so it costs
    # no extra trace:
    #
    #   the original ENDED inside the window        -> 1.0, the whole tune
    #   it does not end even at `factor` x window   -> `seconds / long`, and
    #                                                  that is an UPPER BOUND
    #   otherwise the probe found its ending        -> seconds / orig_ends_at
    #
    # `row["seconds"]` rather than the local `seconds`, which the shortening
    # branch above reassigns: the numerator is the window the RUN asked for,
    # and a row the rule shortened has by definition covered its whole tune.
    asked = row.get("seconds") or seconds
    if row.get("original_ends") is not None:
        row["window_coverage"] = 1.0
    elif row.get("length_never_ends"):
        probe = row.get("length_never_ends_seconds")
        if probe:
            row["window_coverage"] = asked / probe
            row["window_coverage_bounded"] = True
    elif row.get("orig_ends_at"):
        row["window_coverage"] = min(1.0, asked / row["orig_ends_at"])
    # The original is a 50Hz VBI tune; ours ticks at `multiplier` x 50 because
    # that is the rate its tempo values were written for. Tracing each at its
    # own rate is what puts both on one time axis -- see run_siddump.
    # siddump samples the registers once per frame whatever the call rate, so
    # tracing a multiplier-m file at -m{m} throws away m-1 of every m calls.
    # A gate that rises and falls inside one frame leaves no edge, and the
    # attack count falls with m for reasons that have nothing to do with the
    # conversion: Kings_of_the_Beach_intro reads 52 attacks at -m5 and 87 at
    # -m1 over the identical 2500 calls (v0.5.124).
    #
    # --equal-calls trades the time axis for the resolution: one call per
    # frame over m times the window is the same music at the original's
    # sampling. Only the sequence dimensions survive it -- see below.
    equal = bool(getattr(args, "equal_calls", False)) and multiplier > 1
    if equal:
        b = run_siddump(packed, seconds * multiplier, sub, args.siddump,
                        calls=1)
        row["equal_calls"] = multiplier
    else:
        b = run_siddump(packed, seconds, sub, args.siddump,
                        calls=getattr(args, "calls_per_frame", None) or multiplier)
    if multiplier > 1:
        calls = getattr(args, "calls_per_frame", None) or multiplier
        row["traced_calls_per_frame"] = calls
        if calls != 1:
            # The same conversion scored at 50Hz, which is every rate this
            # harness could see before v0.5.99 and is still what a player
            # ignoring the speed field would produce. Carrying both is what
            # lets the summary say which rate a file actually plays right at
            # instead of asserting that the packed one must be it.
            row["melody_at_1x"] = compare(a, run_siddump(
                packed, seconds, sub, args.siddump, calls=1))["melody"]
    row["status"] = "measured"
    row.update(compare(a, b))
    if row.get("equal_calls"):
        # Our frames now cover `multiplier` times the real time the
        # original's do, so anything compared frame against frame is
        # meaningless here. Dropping them is what keeps the mode honest: the
        # row reports what it measured and `dimensions_present` reports the
        # rest as absent rather than as agreement.
        for k in ("bend_ratio", "slides_ratio", "our_slides", "orig_slides"):
            row.pop(k, None)
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
            cand_dump = run_siddump(packed, seconds, st, args.siddump,
                                    calls=getattr(args, "calls_per_frame", None) or multiplier)
            cand = compare(a, cand_dump)
            if cand["melody"] > best:
                best, best_at, row = cand["melody"], st, {**row, **cand}
                best_dump = cand_dump
        row["matched_subtune"] = best_at
    nframes = seconds * 50
    if not row.get("equal_calls"):
        # Every one of these walks the two traces frame against frame, so a
        # stretched time axis makes them compare our frame k to the original's
        # frame k when ours covers `multiplier` times the real time. They are
        # not approximated here, they are omitted -- dimensions_present then
        # reports them absent, which is the difference between "not measured"
        # and "measured as disagreeing".
        if getattr(args, "vice", False):
            # Both sides at 312 samples a frame. Tracing only ours would trade
            # one bias for another: the original reads more gate edges under
            # VICE than under siddump too, so a one-sided change would make
            # the two columns of every count incomparable.
            vo = vicetrace.run(local_orig, seconds, sub,
                               exe=args.vice_exe,
                               out=workdir / "vice_orig.txt")
            vu = vicetrace.run(packed, seconds,
                               row.get("matched_subtune", sub),
                               exe=args.vice_exe,
                               out=workdir / "vice_ours.txt")
            if vo and vu:
                row.update(vice_register_compare(vo, vu, args.vice_reduce))
            else:
                # Never silently fall back to the coarser trace under a flag
                # that promises the finer one -- the row would claim a
                # resolution it does not have.
                row["vice_failed"] = True
        else:
            # The per-frame agreements are aligned on the packed player's
            # startup latency; the counts and travels below are shift-invariant
            # one-sided measures and are not.
            lag, raw = startup_lag(a, best_dump)
            row["startup_lag"] = lag
            if raw != lag:
                row["startup_lag_raw"] = raw
            row.update(wave_compare(a, best_dump, nframes=nframes, lag=lag))
            row.update(adsr_compare(a, best_dump, nframes, lag=lag))
            row.update(gate_compare(a, best_dump, nframes, lag=lag))
            row.update(pulse_compare(a, best_dump, nframes))
            row.update(noise_run_agreement(a, best_dump, nframes))
            row.update(sound_run_agreement(a, best_dump, nframes))
            row.update(release_tail_agreement(a, best_dump, nframes))
            # No `lag`: each side is read at its *own* attack frames, so the
            # startup latency cancels rather than needing correcting. See
            # onset_shapes.
            row.update(onset_agreement(a, best_dump, nframes))
            # No `lag` here either, and for a stronger reason than onset's:
            # the fit's *intercept* is the startup lag, so it falls out of the
            # slope rather than needing to be estimated and subtracted. It is
            # also the by-product that caught two wrong estimators (§ 7.mmmmm).
            dr = drift(a, best_dump)
            # The diagnostics go in whether or not the fit was accepted: a
            # refused row prints `-` in the table, and a `-` that cannot say
            # why is the gap this project keeps warning about. `drift_per_1000`
            # stays absent, so `dimensions_present` correctly reports the
            # dimension as not compared for that row.
            if dr.get("span"):
                row["drift_mad"] = dr["mad"]
                row["drift_span"] = dr["span"]
                row["drift_voices"] = dr["voices"]
                row["drift_lag"] = dr["intercept"]
            if dr.get("unfitted"):
                row["drift_unfitted"] = dr["unfitted"]
            elif dr.get("per_1000") is not None:
                row["drift_per_1000"] = dr["per_1000"]
                row["drift_total"] = dr["total"]
                # **The halves and the knee, copied from a NAMED tuple rather
                # than by hand, because copying by hand is what went wrong.**
                # v0.5.456 added `half_early_per_1000`, `half_late_per_1000`
                # and `knee_per_1000` to `drift()`'s return, shipped them with
                # six passing tests and described them in a commit message --
                # and they reached NO row and NO artefact, because this block
                # copies named keys and nobody added them here. The tests were
                # not wrong: they test `drift()`, which was correct. They
                # simply cannot see the wiring. That is the blind spot
                # `test_preset_passthrough` exists to close for `convert()`
                # options, one level over -- see DRIFT_ROW_KEYS.
                for k in DRIFT_ROW_KEYS:
                    if dr.get(k) is not None:
                        row["drift_" + k] = dr[k]
                # Whether *this* file's drift is the outer gate's declined
                # skip correction -- see _drift_gate_skip_declined. Computed
                # only where a drift figure was actually reported, since it
                # is only meaningful next to one.
                row["drift_gate_skip"] = _drift_gate_skip_declined(sid, sub)
            # Read once and shared by the column and its census, so the two
            # cannot restrict to different populations.
            vib_keys = vibrato_records(sid)
            if getattr(args, "census", None):
                # The same two traces and the same modal reduction the column
                # just scored -- a second pipeline would risk resolving a
                # different subtune and then disagreeing with the report for a
                # reason that has nothing to do with the conversion.
                row["onset_census"] = onset_census(
                    a, best_dump, nframes, instrument_stamps(sng))
            if getattr(args, "vib_census", None):
                # Same two traces and the same reduction the column used.
                row["vib_census"] = vib_census(a, best_dump, nframes,
                                               instrument_stamps(sng),
                                               pitch_effect_bits(sid))
                row["depth_census"] = depth_census(a, best_dump, nframes,
                                                   vib_keys,
                                                   instrument_stamps(sng))
            if getattr(args, "gate_census", None):
                # Same two traces and the same alignment the column used.
                row["gate_census"] = gate_census(a, best_dump, nframes,
                                                 lag=lag)
            if getattr(args, "hold_census", None):
                # Same two traces, same modal reduction, same reason.
                row["hold_census"] = hold_census(
                    a, best_dump, nframes, instrument_stamps(sng))
            row.update(pitch_motion_compare(a, best_dump, nframes))
            # `depth` is `vib`'s other half and reads the same register, but
            # only on the records that carry a vibrato byte -- the population
            # restriction is the measurement, not a refinement of it (see
            # vibrato_records). A file whose player has no vibrato routine
            # contributes no row rather than a reading over its portamentos.
            row.update(depth_compare(a, best_dump, nframes, vib_keys))
            row.update(filter_compare(a.filter, best_dump.filter, nframes))
    if row["our_attacks"] == 0:
        # A conversion that plays nothing is a defect; a *window* in which
        # neither side plays anything is not, and calling both "silent" put
        # BMX_Kidz -- which opens with about thirteen seconds of rest and then
        # matches at 95% -- in the bucket labelled "plays something else" for
        # eighteen versions.
        row["status"] = "window empty" if row["orig_attacks"] == 0 else "silent"
    if getattr(args, "sound", False):
        # The rendered sound, both sides through one emulator. Prior for the
        # envelope alignment is the packed player's startup lag where the
        # trace measured one; the WAV alignment is still estimated from the
        # envelope inside a bounded window, never fitted to the score.
        #
        # THE IMPORT IS DELIBERATELY FUNCTION-LEVEL, AND NOT ONLY FOR NUMPY.
        # `sound` imports `listen`, and `listen` does `from fidelity import
        # _preset_opts, ...` -- so a module-scope `import sound` here would
        # close the cycle fidelity -> sound -> listen -> fidelity and raise on
        # a partially-initialised module. By the time _measure runs, fidelity
        # is fully loaded and the cycle cannot form. Measured at v0.5.453:
        # `import sound` pulls in fidelity plus nine h2g modules.
        import sound  # noqa: PLC0415 -- numpy, harness only; see above
        prior = 0.02 * row.get("startup_lag", 0)
        row.update(sound.compare_sids(
            local_orig, packed, seconds, sub,
            row.get("matched_subtune", sub), prior_s=prior))
    if args.register:
        row["register"] = sidm2_register(local_orig, packed, seconds)
    if args.audio:
        row["audio"] = sidm2_audio(local_orig, packed, seconds)
    return row


def _fmt_pct(x) -> str:
    return "-" if x is None else f"{100 * x:.0f}%"


def blindness_section(rows: list[dict]) -> list[str]:
    """What this run compared, and therefore what it cannot have seen.

    Derived from the rows themselves, not from intent: a dimension appears
    with the number of files it was actually computed on, and the register
    list underneath is whatever no computed dimension reads. So a run that
    loses `wave` on every file says so, and a change landing in a register
    named below is reported as unseeable rather than as unmoved.
    """
    computed: dict[str, int] = {}
    for r in rows:
        for key in r.get("dimensions", dimensions_present(r)):
            computed[key] = computed.get(key, 0) + 1
    live = [d for d in DIMENSIONS if computed.get(d.key)]
    out = [
        "",
        "## What this run compared",
        "",
        "Every number above comes from one of these, and each is computed "
        "from the SID registers named beside it. This section is generated "
        "from the rows, so it describes the run that happened rather than the "
        "one intended.",
        "",
        "| dimension | files | compares | from |",
        "|---|---:|---|---|",
    ]
    for d in DIMENSIONS:
        n = computed.get(d.key, 0)
        out.append(f"| **{d.column}** | {n} of {len(rows)} | {d.of} | "
                   f"{', '.join(d.reads)} |")
    unread = registers_unread(computed)
    out += ["", "**Registers no dimension above reads.** A change confined to "
            "these cannot move a single number in this report, whatever it "
            "does to the sound:", ""]
    if unread:
        out += [f"- `{reg}` -- {what}" for reg, what in unread]
        out += ["", "`parse_dump` reads all of these (v0.5.76); what is "
                "missing is a *comparison*, not the data. A register being "
                "parsed is not a register being scored, and only the second "
                "one can move a number here."]
    else:
        out.append("- none: every SID register is read by some dimension above.")
    out += ["", "Not registers, and equally unseen here:", ""]
    out += [f"- {item}" for item in NOT_MEASURED]
    out += [
        "",
        "This is not a caveat, it is the report's own account of its reach. "
        "v0.5.71's envelope fix, v0.5.72's filter and v0.5.73's pulse-width "
        "sweep each landed in a register no dimension then read, and each "
        "moved no column of the report to the decimal; `adsr`, `pul`, `filt` "
        "and `cut` (v0.5.78) are those three registers becoming dimensions. "
        "The list above is what the *next* such change would land in. "
        "`fidelity.py --baseline old.json` states that case as a result -- "
        "\"no dimension this report measures can see this change\" -- rather "
        "than leaving a flat table to be misread as a null result.",
    ]
    if live and len(live) < len(DIMENSIONS):
        missing = ", ".join(f"`{d.column}`" for d in DIMENSIONS
                            if not computed.get(d.key))
        out += ["", f"No row in this run computed {missing}, so it is blind "
                "on that too."]
    return out



def _fmt_coverage(row: dict) -> str:
    """The `cov` cell: what share of the original this row's window contained.

    `<n%` where the figure is an UPPER bound -- the original outlasts the
    length probe entirely, so all that is known is that the window saw less
    than `1 / --length-probe` of it. Printing a bare percentage there would
    state a measurement the run does not have, which is the distinction
    `length_never_ends` exists to keep and the one `compare_runs` had to learn
    for subtunes.
    """
    v = row.get("window_coverage")
    if v is None:
        return "-"
    return ("<" if row.get("window_coverage_bounded") else "") + _fmt_pct(v)

def _fmt_length(r: dict) -> str:
    """The `len` cell: how far past the original's ending ours runs.

    `-` where the rule could not be tested at all -- either the original does
    not stop inside the window, or ours is still going with less than the
    tolerance left to prove it. A `>` prefix marks a FLOOR: our side had not
    stopped when the trace ran out, so the true surplus is at least this and
    probably larger. `!` marks a breach of the +-5 s rule, the same way
    `_one_sided` marks a filter we invent.
    """
    d = r.get("length_delta")
    if d is None:
        return "-"
    lead = ">" if r.get("length_bounded") else ""
    bad = " !" if abs(d) > LENGTH_TOLERANCE else ""
    return f"{lead}{d:+.1f}s{bad}"


def _fmt_sweep(row: dict) -> str:
    """The cutoff-travel ratio, or `-` where the original never moves it.

    A ratio and not a count, because the filter's two questions are different
    shapes: `filt` is one-sided (did we invent a filter, did we drop one) and
    this is comparative (having filtered, did the cutoff go as far).
    """
    v = row.get("cutoff_sweep")
    return "-" if v is None else f"{v:.2f}x"


def _fmt_drift(row: dict) -> str:
    """`drift` as the table prints it: frames per 1000, signed.

    Negative is *early* -- we run ahead of the original -- which is the sign
    of every drifting file in this corpus, because the correction declined is
    always one the player makes and we do not. `0.00` and `-` mean different
    things and both occur: zero is a file measured and found exact (37 of
    them), `-` is one where too little matched to fit a line.
    """
    v = row.get("drift_per_1000")
    return "-" if v is None else f"{v:+.1f}"


def _one_sided(row: dict, key: str) -> str:
    """`ours/original`, with `!` for something the original never does.

    The format the `noise` column established, and the reason it earned its
    keep: `138/0 !` says a conversion invented drum ticks, which no agreement
    percentage can say because there is nothing on the other side to disagree
    with. Every count in this report that answers a one-sided question --
    noise frames, pulse-width movement, filtered frames -- is written this way
    so that invention reads the same wherever it appears.
    """
    o, u = row.get(f"orig_{key}", 0), row.get(f"our_{key}", 0)
    return f"{u}/{o}" + (" !" if u and not o else "")


def _register_summary(measured: list[dict]) -> list[str]:
    """Corpus totals for the two counted register columns, `pul` and `filt`.

    Both are one-sided counts, so both have two failure directions worth
    naming separately: a dimension the original moves and we do not (a frozen
    duty cycle, an unfiltered tune), and one we move and it never does
    (invention). A mean would hide both -- the totals are dominated by a few
    heavily swept files, and the files that matter are the ones on either
    edge.
    """
    out: list[str] = []
    pulsed = [r for r in measured if "our_pulse_changes" in r]
    if pulsed:
        frozen = [r for r in pulsed
                  if r["orig_pulse_changes"] and not r["our_pulse_changes"]]
        invented = [r for r in pulsed
                    if r["our_pulse_changes"] and not r["orig_pulse_changes"]]
        out.append(
            "- pulse-width changes, ours/original: "
            f"**{sum(r['our_pulse_changes'] for r in pulsed)}/"
            f"{sum(r['orig_pulse_changes'] for r in pulsed)}**"
            + (f"; **{len(frozen)}** file(s) hold the duty cycle still where "
               "the original sweeps it" if frozen else "")
            + (f"; **{len(invented)}** move it where the original never does "
               "(marked `!` above)" if invented else ""))
    filtered = [r for r in measured if "our_filtered_frames" in r]
    if filtered:
        invented = [r for r in filtered
                    if r["our_filtered_frames"] and not r["orig_filtered_frames"]]
        missing = [r for r in filtered
                   if r["orig_filtered_frames"] and not r["our_filtered_frames"]]
        out.append(
            "- filtered frames, ours/original: "
            f"**{sum(r['our_filtered_frames'] for r in filtered)}/"
            f"{sum(r['orig_filtered_frames'] for r in filtered)}**"
            + (f"; **{len(invented)}** file(s) filter where the original "
               "never does (marked `!` above)" if invented else "")
            + (f"; **{len(missing)}** play unfiltered where the original "
               "filters" if missing else ""))
    # The alignment is a property of the run, so it is stated in the run rather
    # than left in a docstring. A reader comparing `wave` or `adsr` against a
    # figure taken before v0.5.175 needs to know both that a shift was applied
    # and which files could not take one.
    lagged = [r for r in measured if "startup_lag" in r]
    if lagged:
        lags = sorted(r["startup_lag"] for r in lagged)
        over = [r for r in lagged if "startup_lag_raw" in r]
        out.append(
            "- startup lag applied to `wave` and `adsr` (the two per-frame "
            f"agreements): median **{lags[len(lags) // 2]}** frame(s), range "
            f"{lags[0]} to {lags[-1]}. It is the difference between the two "
            "sides' first attack frames -- estimated from that one signal, "
            "never fitted to maximise a score"
            + (f"; **{len(over)}** file(s) measured a lag too large to be a "
               "startup latency and were clamped rather than corrected ("
               + ", ".join(f"{r['file']} {r['startup_lag_raw']}"
                           for r in over[:6]) + ")" if over else ""))
    return out


def _filter_section(rows: list[dict]) -> list[str]:
    """The second filter question: not whether we filter, but how far.

    Kept out of the main table on purpose. It concerns only the files where
    one side or the other actually filters -- a minority -- and it needs two
    numbers rather than one, so as a column it would be mostly `-` and still
    unreadable where it was not. `filt` in the table answers the one-sided
    question for every file; this answers the shape question for the files it
    applies to.
    """
    got = [r for r in rows
           if r.get("our_filtered_frames") or r.get("orig_filtered_frames")
           or r.get("our_cutoff_changes") or r.get("orig_cutoff_changes")]
    if not got:
        return []
    out = [
        "",
        "## Filter: does the cutoff move like the original's?",
        "",
        "Both sides of the two filter columns, for the files where either "
        "side filters at all. `filt` is the one-sided question -- do we "
        "filter where the original filters -- and `cut` is the other one, "
        "which no count answers: Deep_Strike went 481 cutoff writes to 1515 "
        "under an earlier filter reader, an overshoot rather than an "
        "absence, and a write count reads the same whether we sweep the same "
        "band in finer steps or sweep three times as far.",
        "",
        "* **frames** -- a voice routed into the filter with a passband "
        "selected, ours/original (the `filt` column).",
        "* **writes** -- frames on which the cutoff value changed.",
        "* **travel** -- summed frame-to-frame movement of the cutoff: how "
        "far it actually goes, independent of how many steps it takes.",
        "* **sweep** -- our travel over the original's (the `cut` column). "
        "Near 1.0 is the "
        "right answer even when the write counts differ, because the same "
        "sweep sampled twice as finely is the same sweep. Well over 1.0 is "
        "the overshoot to expect from Goattracker's filter table, which "
        "steps for a fixed tick count where the player's sweep is bounded by "
        "its own counter.",
        "",
        "| File | frames | writes | travel | sweep |",
        "|---|---:|---:|---:|---:|",
    ]
    for r in sorted(got, key=lambda r: r["file"].lower()):
        sweep = r.get("cutoff_sweep")
        out.append(
            f"| {r['file']} | {_one_sided(r, 'filtered_frames')} | "
            f"{_one_sided(r, 'cutoff_changes')} | "
            f"{r.get('our_cutoff_travel', 0):,}/"
            f"{r.get('orig_cutoff_travel', 0):,} | "
            f"{'-' if sweep is None else f'{sweep:.2f}x'} |")
    return out


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
        "repeats collapsed: the right notes in the right order. Collapsed "
        "means it cannot see a re-struck note -- a re-articulation reads "
        "here only as the sequence getting longer, never as a wrong note.",
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
        "* **bend** -- our pitch *travel*: the summed magnitude of every "
        "frequency move siddump printed as a bend (`(+ xxxx)` / `(- xxxx)`, "
        "the frames **slides** counts) -- "
        "over the original's. The other half of **slides**, and the half a "
        "count cannot answer: a bend taken in steps ten times too large moves "
        "the same frames and goes ten times as far. It is also the half that "
        "does not care how siddump *printed* the movement, which matters "
        "because it prints a bare delta or a parenthesised note depending on "
        "where the new frequency lands, so a change in step size shifts "
        "frames between the two forms and **slides** counts only one of them. "
        "It is siddump's own number rather than a difference of the frequency "
        "column: differencing counted note changes as bends, both the tie form "
        "and the bare frequency write a note start makes on a frame of its own "
        "-- which put Zoolook at 121,107 units against about 3,400 of printed "
        "bending. `-` is an original whose pitch never moves within a note.",
        "* **wave** -- per-frame agreement of the waveform *class* (the "
        "waveform-select nibble of $D404: triangle/saw/pulse/noise, with a "
        "combined waveform its own class and the gate/sync/ring/test bits "
        "ignored), carried forward between register writes. Frames where "
        "both sides select no waveform are not counted.",
        "* **noise** -- frames on which the voice's waveform included noise "
        "(bit 7), ours over the original's. A nonzero left of a zero right "
        "is a drum tick the conversion invented.",
        "* **gate** -- overlap of the frames on which each side has the voice *released*: `|both off| / |either off|`. Every other register column here ignores $D404's gate bit, and **wave** says why -- a gated-off voice keeps its waveform latched, so folding the gate into a timbre score would count every note-length disagreement twice. The cost of that exclusion was invisible until a change that only opens and closes the gate (`--rest-keyoff`, 19 files) moved one number on one file. Scored over the gate-off frames alone because both sides hold it on most of the time. It **rises when notes are removed** -- fewer attacks, more silence -- so read it beside **retrig** and the two attack counts, never on its own.",
        "* **adsr** -- per-frame agreement of the envelope registers "
        "($D405/$D406, the whole 16-bit pair), carried forward between "
        "writes exactly as **wave** is. Frames where neither side has ever "
        "set an envelope are not counted.",
        "* **pul** -- how many times the duty cycle moved, ours over the "
        "original's. A count rather than an agreement: two players sweeping "
        "the same pulse from different phases share almost no frame values, "
        "and the defect this watches is a *frozen* width, not a wrong one.",
        "* **filt** -- frames on which a voice is routed into the filter "
        "*and* a passband is selected, ours over the original's. One-sided "
        "like **noise**: a nonzero left of a zero right is a filter the "
        "conversion invented.",
        "* **cut** -- our cutoff *travel* -- its summed frame-to-frame "
        "movement -- over the original's. The second filter question, and "
        "the one no count answers: the same sweep taken in finer steps "
        "doubles the write count and travels exactly as far, while a sweep "
        "that runs past the player's own counter travels further at the same "
        "count. `-` is an original that never moves it. Both sides' raw "
        "numbers are under *Filter*, below.",
        "",
        "* **depth** -- how far our vibrato *swings*, over the original's: "
        "the median peak-to-peak excursion of the frequency within a note, as "
        "a fraction of the pitch it swings around, taken per instrument and "
        "then across instruments. **vib** is the rate and this is the size of "
        "the step, the same pairing as **slides**/**bend** and "
        "**filt**/**cut** -- a count of reversals reads identically whether "
        "the oscillator moves a comma or a whole tone. Notes are cut at gate "
        "rising edges, never at siddump's printed note *name*, which flickers "
        "while a vibrato runs; each reading spans three consecutive turning "
        "points rather than two, so any slide underneath the oscillation "
        "cancels instead of being counted as depth. Measured **only on the "
        "records that carry a non-zero vibrato byte and no competing "
        "pitch-moving effect bit** in the player's own instrument table: over "
        "every oscillating note instead, the statistic picks up portamento "
        "slides and drum sweeps and reports 273% and 397% \"depths\", and "
        "over the vibrato byte alone it reads Commando at 59% of pitch (eight "
        "semitones) from records that also carry a drum. `-` is a file whose "
        "player has no vibrato routine, or one where no such instrument "
        "oscillates on both sides -- a side emitting *no* oscillation drops "
        "out of this column entirely, so read it beside **vib**, which is "
        "where a missing oscillation shows up.",
        "* **aud** -- per-frame agreement of the rendered sound's log-mel "
        "spectrum with the level removed: timbre, filter movement, envelope "
        "shape -- what no register column can see. Both sides are rendered "
        "by `sidplayfp` at identical settings and aligned on their loudness "
        "envelopes inside a bounded window. Frames both sides spend silent "
        "carry no weight, and so do mel bands both sides leave at the floor "
        "-- a sparse signal floors most of a 64-band spectrum, and counting "
        "those as agreement read two tones an octave apart at 0.90. It "
        "**rises when a change removes events**, exactly as **wave** does, so "
        "read it beside **retrig** and the two attack counts. `-` is a run "
        "taken without `--sound`, or a render that failed. **AND ITS OWN "
        "CALIBRATION CURRENTLY FAILS**: docs/SOUND-CALIBRATION.md reports "
        "`pass: false` -- a one-frame shift of either side moves this column "
        "by 0.034, while the three documented fixes it was tested against "
        "move it by 0.012, -0.019 and -0.005. Two of those are the WRONG "
        "SIGN, because a per-frame agreement falls when a fix unmasks a "
        "defect the old behaviour hid. Treat it as a coarse guard against "
        "gross breakage until that is resolved, never as a verdict.",
        "* **loud** -- per-frame agreement of the rendered loudness envelope; "
        "the only column that reads the master-volume nibble. `--json` also "
        "carries `loud_ratio`, our overall level over the original's.",
        "",
        "| File | orig | ours | retrig | melody | seq | pitch | slides | bend | vib | depth | drift | wave | onset | noise | nrun | hold | gate | tail | adsr | pul | pspan | pphase | filt | cut | len | cov | aud | loud | status |",
        "|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---|",
    ]
    # Derived from the header rather than hardcoded. It WAS hardcoded, at 21
    # against a header that wanted 23, so every `not converted` row had been
    # two cells short for as long as the count had drifted -- and adding
    # `pphase` widened the gap rather than causing it. A number that has to be
    # kept in step with a string is a number that will not be.
    _header = next(l for l in reversed(out) if l.startswith("| File |"))
    _dashes = len(_header.strip().strip("|").split("|")) - 2
    for r in sorted(rows, key=lambda r: r["file"].lower()):
        if r["status"] not in ("measured", "silent", "window empty"):
            out.append(
                f"| {r['file']} |" + " - |" * _dashes + f" {r['status']} |")
            continue
        rr = r["retrigger_ratio"]
        status = r["status"]
        if r.get("traced_subtune_dropped"):
            status += " -- **not comparable**"
        noise = _one_sided(r, "noise_frames")
        out.append(
            f"| {r['file']} | {r['orig_attacks']} | {r['our_attacks']} | "
            f"{'-' if rr is None else f'{rr:.2f}'} | {_fmt_pct(r['melody'])} | "
            f"{_fmt_pct(r['sequence'])} | {_fmt_pct(r['pitch_jaccard'])} | "
            f"{r.get('our_slides', 0)}/{r.get('orig_slides', 0)} | "
            f"{'-' if r.get('bend_ratio') is None else f'{r["bend_ratio"]:.2f}x'} | "
            f"{'-' if r.get('reversal_ratio') is None else f'{r["reversal_ratio"]:.2f}x'} | "
            f"{'-' if r.get('depth_ratio') is None else f'{r["depth_ratio"]:.2f}x'} | "
            f"{_fmt_drift(r)} | "
            f"{_fmt_pct(r.get('wave'))} | {_fmt_pct(r.get('onset_agreement'))} | "
            f"{noise} | "
            f"{_fmt_pct(r.get('noise_run_agreement'))} | "
            f"{_fmt_pct(r.get('sound_run_agreement'))} | "
            f"{_fmt_pct(r.get('gate'))} | "
            f"{_fmt_pct(r.get('release_tail_agreement'))} | "
            f"{_fmt_pct(r.get('adsr'))} | {_one_sided(r, 'pulse_changes')} | "
            f"{'-' if r.get('pulse_span') is None else f'{r["pulse_span"]:.2f}x'} | "
            f"{'-' if r.get('pulse_phase') is None else f'{r["pulse_phase"]:.2f}x'} | "
            f"{_one_sided(r, 'filtered_frames')} | {_fmt_sweep(r)} | "
            f"{_fmt_length(r)} | {_fmt_coverage(r)} | "
            f"{_fmt_pct(r.get('aud'))} | {_fmt_pct(r.get('loud'))} | "
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
        gated = [r for r in measured if r.get("gate") is not None]
        if gated:
            ringing = sum(r.get("gate_ours_ringing", 0) for r in gated)
            silent = sum(r.get("gate_ours_silent", 0) for r in gated)
            out.append(
                f"- mean gate overlap: "
                f"**{_fmt_pct(sum(r['gate'] for r in gated) / len(gated))}**"
                f" ({len(gated)} file(s)); **{ringing}** frame(s) sustaining a "
                f"voice the original released, **{silent}** the other way "
                "round")
        drifted = [r for r in measured
                   if r.get("drift_per_1000") is not None]
        if drifted:
            # A **median** of the magnitudes, not a mean: the distribution is
            # 37 exact zeros and a tail out to -298, so a mean reports the
            # tail and a median reports the corpus. Counted separately because
            # "how many files drift at all" is the useful number and an
            # average over mostly-zeros hides it.
            moving = [r for r in drifted if abs(r["drift_per_1000"]) >= 0.005]
            mags = sorted(abs(r["drift_per_1000"]) for r in moving)
            worst = max(drifted, key=lambda r: abs(r["drift_per_1000"]))
            med = mags[len(mags) // 2] if mags else 0.0
            # Counted, not asserted: `drift_gate_skip` is set per row by
            # `_drift_gate_skip_declined`, which re-detects the player and
            # asks `effective_frames` itself whether it corrected for the
            # outer gate's skip counter. A stale literal here (v0.5.288's
            # "17") is exactly what went wrong -- Human_Race's tempo fix at
            # v0.5.330 took its drift to 0.00 and moved it out of `moving`
            # without anyone re-counting the sentence that names the cause.
            skip_declined = sum(1 for r in moving if r.get("drift_gate_skip"))
            out.append(
                f"- drift: **{len(drifted) - len(moving)}** of {len(drifted)} "
                f"file(s) hold the original's timing exactly; the other "
                f"**{len(moving)}** part company at a median "
                f"**{med:.1f}** frame(s) per 1000, worst "
                f"**{worst['drift_per_1000']:+.1f}** "
                f"({worst['file']}, {abs(worst.get('drift_total', 0)):.0f} "
                f"frame(s) across the window). Negative is early."
                + (f" On **{skip_declined}** file(s) this is exactly "
                   "`-1/(skip+1)`, the outer gate's skipped call, which "
                   "`effective_frames` declines to correct when the "
                   "corrected row cannot be packed" if skip_declined else ""))
        adsred = [r for r in measured if r.get("adsr") is not None]
        if adsred:
            out.append(
                f"- mean ADSR agreement: "
                f"**{_fmt_pct(sum(r['adsr'] for r in adsred) / len(adsred))}**"
                f" ({len(adsred)} file(s))")
            cut = [r for r in adsred if r.get("release_tail_agreement")]
            if cut:
                out.append(
                    "  - **`adsr` reads lower on the files whose player kills "
                    "the envelope at a note's end** (`--cut-release`). Those "
                    "players write the record verbatim at the attack and zero "
                    "both envelope registers when an untied note ends, so the "
                    "release nibble they carry never acts; we emit 0 for it, "
                    "which sounds the same and reads as a mismatch here. "
                    "Attack, decay and sustain are unchanged, and only the "
                    "instruments whose effect routine does not overwrite the "
                    "cut are affected (goatwriter.EFFECT_PER_FRAME). `tail` is "
                    "the column that reflects what the envelope does.")
        out += _register_summary(measured)
        ratios = [r["retrigger_ratio"] for r in measured if r["retrigger_ratio"]]
        if ratios:
            out.append(f"- median retrigger ratio: **{sorted(ratios)[len(ratios) // 2]:.2f}**")
        slowed = [r for r in measured if r.get("multiplier", 1) > 1]
        if slowed:
            mean_ok = sum(r["melody"] for r in measured if r.get("multiplier", 1) == 1)
            n_ok = n - len(slowed)
            traced = sorted({r.get("traced_calls_per_frame", 1) for r in slowed})
            # "advances a row every 2 frames" / "-S2" used to be hardcoded
            # here, so a multiplier-3 file's paragraph named -S2 in one
            # clause and -m3 (correctly, via `traced`) two clauses later --
            # e.g. Saboteur_II. Name the actual multiplier(s) `slowed`
            # carries instead of assuming the commonest one.
            mults = sorted({r.get("multiplier", 1) for r in slowed})
            if len(mults) == 1:
                m = mults[0]
                mech = (
                    f"Their player advances a row every {m} frames, which "
                    f"Goattracker reaches only by being called {m} times a "
                    f"frame, so they are packed with `gt2reloc -S{m}` -- a "
                    f"CIA stub at the init address that reprograms timer A "
                    f"to 50.125x{m} Hz (greloc.c:140, :1616).")
            else:
                mech = (
                    "Each one's player advances a row every `multiplier` "
                    "frames, which Goattracker reaches only by being called "
                    "`multiplier` times a frame, so it is packed with "
                    "`gt2reloc -S<multiplier>` -- a CIA stub at the init "
                    "address that reprograms timer A to "
                    "50.125x`multiplier` Hz (greloc.c:140, :1616). This "
                    "run's multipliers: " + ", ".join(f"-S{m}" for m in mults)
                    + ".")
            out.append(
                f"- **{len(slowed)} of these {n} files are played faster than "
                "50Hz and are traced that way.** " + mech + " Stock siddump "
                "cannot see that: it calls the play routine `seconds x 50` "
                "times whatever the PSID speed field says "
                "(siddump.c:309/325), which traced every one of these files "
                "at half speed until v0.5.99. The `tools/siddump-rt` build "
                "takes `-m` and this run passed "
                + (f"`-m{traced[0]}`" if len(traced) == 1
                   else "each song its own multiplier")
                + ", so both sides now sit on one real-time axis."
                + (f" Excluding them, mean melody similarity is "
                   f"**{_fmt_pct(mean_ok / n_ok)}** over {n_ok} file(s)."
                   if n_ok else ""))
            both = [r for r in slowed if r.get("melody_at_1x") is not None]
            if both:
                faster = [r for r in both if r["melody"] > r["melody_at_1x"] + 0.02]
                slower = [r for r in both if r["melody_at_1x"] > r["melody"] + 0.02]
                out.append(
                    f"- Scoring the same conversion at 1 call per frame as "
                    f"well, **{len(faster)}** score better at the packed rate "
                    f"and **{len(slower)}** at 50Hz. **Do not read that as "
                    f"the second group wanting `-S1`** -- v0.5.99 did, and "
                    "`--pace` refuted it: timed against the original over "
                    "difflib-matched notes, 32 of the 33 are closer to the "
                    "original's speed at the rate they are packed for. "
                    "`melody` is a sequence ratio inside a fixed window, and "
                    "the two errors are not symmetric there -- a conversion "
                    "playing too fast reaches past the window and is charged "
                    "for the surplus, one playing too slow returns a prefix. "
                    "What those files really carry is a *row length* error of "
                    "10-33%, which is a different defect in a different place "
                    "(see `--pace`).")
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
                f"- **{len(shifted)} file(s) are scored against a subtune of "
                "*ours* other than the one traced in the original.** There are "
                "TWO causes and this line cannot tell them apart. The benign "
                "one is that our numbering shifts when `gt2reloc` drops a "
                "subtune whose orderlist exceeds Goattracker's limit. The "
                "other is a CONVERTER DEFECT: our `.sng` emitting its subtunes "
                "in the wrong order, which looks identical here because the "
                "search simply keeps whichever of ours matches best. That is "
                "not hypothetical -- until `f63caa1` Action Biker, Samantha Fox "
                "Strip Poker and Spellbound all read their track table six "
                "bytes early, at a scratch buffer, and shipped `.sng`s whose "
                "subtunes played in the wrong order for the life of the "
                "converter. Every column read fine throughout, because this "
                "search was finding the right counterpart and scoring it. **A "
                "non-empty list here is a lead to run `--diagnose` on, not a "
                "footnote.** "
                f"({', '.join(shifted)})")
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

        ended = [r for r in rows if r.get("original_ends")]
        if ended:
            names = ", ".join(
                f"{r['file'].replace('.sid', '')} {r['original_ends']}s"
                for r in sorted(ended, key=lambda r: r["file"].lower()))
            # WHETHER THE SHIPPED FILE ACTUALLY PLAYS ON IS A MEASUREMENT,
            # NOT A PROPERTY OF BEING SHORTENED. This bullet asserted
            # "the shipped `.sng` still plays forever" for every shortened
            # row, which was true when the only repair was a restart at 0 and
            # is false once one is parked: `length_compare` sets
            # `length_bounded` exactly when our side did NOT stop inside the
            # long probe, so the claim is read off that rather than restated.
            # Same principle as counting through a predicate instead of
            # hardcoding what it would return.
            fate = shortening_fate(ended)
            out.append(
                f"- {len(ended)} file(s) have their comparison WINDOW "
                "shortened by the length rule: these are the files whose "
                "original STOPS inside the window while ours plays on, so "
                "the harness compares over the music the original actually "
                "plays rather than over our restart of it. This is a note "
                "on method, not a defect queue by itself -- see the next "
                "bullet for which of them actually breach the rule. Read "
                f"the shortening for what it is: the score is protected, and "
                f"{fate}. Where a shortened file DOES play on it is the same "
                "shape as the `--search-subtunes` compensation corrected in "
                "v0.5.375 -- a shim that hides a defect from the score does "
                "not hide it from the file. Hubbard's `$FE` means *tune "
                "ended*, a Goattracker orderlist cannot say it, and "
                "`--legal-restart` turns it into a restart at position 0; "
                "the repair is a choice of restart TARGET, looping a silent "
                "pattern instead (`--silent-park`, or `--force-park` for a "
                "tune whose data never says it ended). The `len` column "
                f"carries the measured delta per file. ({names})")

        failed = length_rule_failures(rows)
        if failed:
            fnames = ", ".join(
                f"{r['file'].replace('.sid', '')} {r['length_delta']:+.1f}s"
                for r in sorted(failed, key=lambda r: r["file"].lower()))
            out.append(
                f"- **{len(failed)} file(s) FAIL the length rule**, and this "
                "list is a defect queue rather than a note on method. A "
                "conversion must end within +-5s of the original; these are "
                "the files whose MEASURED `len` -- taken over the window "
                "above, before it shrinks (see `length_compare`) -- exceeds "
                f"that. ({fnames})")
        elif ended:
            # Used to name "Geoff Capes and Kings of the Beach ingame" and
            # their deltas as bare English text -- an example baked into the
            # prose rather than read from `ended`, so a run whose corpus does
            # not carry those two files (or whose measured deltas for them
            # move) would keep citing numbers no row here backs. Derived from
            # `ended` instead, the same fix `skip_declined` got a few bullets
            # up for the identical reason: a stale literal in prose is
            # invisible to every test that only checks the row it came from.
            passing = sorted(ended, key=lambda r: r["file"].lower())
            examples = [r for r in passing if r.get("length_delta") is not None]
            if examples:
                enames = ", ".join(
                    f"{r['file'].replace('.sid', '')} {r['length_delta']:+.1f}s"
                    for r in examples[:2])
                out.append(
                    "- None of the window-shortened files above breach the "
                    f"+-{LENGTH_TOLERANCE:.0f}s length tolerance once "
                    f"measured against the original's own length -- e.g. "
                    f"{enames}, whose windows are shortened for the reason "
                    "above but whose `len` reads well inside it. The "
                    "shortening is a measurement necessity, not evidence of "
                    "a defect, for every file it currently applies to.")
            else:
                # Every `ended` row is still bounded (still playing with no
                # room left to prove a surplus): there is no measured delta
                # to cite, so say that rather than naming a file with one.
                out.append(
                    "- None of the window-shortened files above breach the "
                    f"+-{LENGTH_TOLERANCE:.0f}s length tolerance -- their "
                    "`len` is unmeasured rather than failing (still playing, "
                    "with less than the tolerance left inside the shortened "
                    "window to prove a surplus). The shortening is a "
                    "measurement necessity, not evidence of a defect, for "
                    "every file it currently applies to.")
        # Gated on whether the probe actually fired in THIS run
        # (`length_probe_seconds` present on some row), not on `ended` --
        # those are unrelated sets that only happened to co-occur on the
        # corpus this bullet was written against. Gating on `ended` let the
        # bullet assert "it is reached now" for a run where nothing was ever
        # probed (`--length-probe 1`, or a corpus with no still-at-the-edge
        # file), which is the exact failure this repo keeps finding: prose
        # describing what the mechanism does, not what this run's own rows
        # show it did. Action Biker stays as the illustrative history -- it
        # is not read from `rows`, so it cannot itself go stale -- but the
        # "reached now" claim is now backed by a count from this run.
        probed = [r for r in rows if r.get("length_probe_seconds") is not None]
        if probed:
            reached = sum(1 for r in probed if r.get("length_delta") is not None)
            out.append(
                "- **The length rule reaches past the window, but not "
                "forever.** Inside its own window a tune that stops half a "
                "second before the trace does looks exactly like one that "
                "plays on, so `len` used to print `-` for every such file --  "
                "Action Biker, whose original's last attack is at 59.54s of a "
                "60s trace, was the known case it could not reach. It is "
                "reached now: when the original is still sounding at the edge "
                "the harness re-asks over "
                f"{LENGTH_PROBE_FACTOR}x the window (`--length-probe`), and "
                "traces our side again only if the original turns out to end "
                f"there -- this run probed {len(probed)} file(s) this way and "
                f"measured {reached} of them, so the extra work falls on the "
                "files that can actually fail. A file whose original outlasts "
                "even that still reads `-`, which is the column declining to "
                "score what it cannot see rather than passing it, so the FAIL "
                "count remains a floor rather than a census -- just a much "
                "lower one. The probed rows carry `length_probe_seconds` in "
                "`--json`, because a delta measured over "
                f"{LENGTH_PROBE_FACTOR}x the window is not comparable to one "
                "measured inside it.")
        never = [r for r in rows if r.get("length_never_ends")]
        if never:
            out.append(
                "- **And the rule is INAPPLICABLE to most of the corpus, "
                "which is a fact about the tunes rather than a gap in the "
                f"harness.** {len(never)} of this run's {len(rows)} file(s) "
                f"have an original that never stops within {LENGTH_PROBE_FACTOR}x "
                "the window: it loops, so there is no ending for ours to match "
                "and `-` is the only honest reading. Widening the probe does "
                "not help them -- the corpus census that chose "
                f"{LENGTH_PROBE_FACTOR} found the measurable set SATURATED, "
                "with 14 files ending by 600s and tripling the window again "
                "adding none. So the number of rows this column can ever score "
                "is a property of the corpus, and the FAIL count should be "
                "read against that denominator rather than against the file "
                "count.")
        elif ended:
            out.append(
                "- **The length rule reaches past the window, but not "
                "forever -- and no file in this run needed the probe.** "
                "Inside its own window a tune that stops half a second "
                "before the trace does looks exactly like one that plays on, "
                "so `len` prints `-` for such a file unless a longer probe "
                "confirms where it ends (`--length-probe`, default "
                f"{LENGTH_PROBE_FACTOR}x the window) -- Action Biker is the "
                "known case that forced the mechanism to exist. None of "
                "this run's files were still sounding at the window edge in "
                "a way that needed it.")

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

    out += _filter_section(rows)

    if getattr(args, "pair", None):
        for r in rows:
            if not r.get("wave_voices"):
                continue
            out += ["", "## Per-voice detail", "",
                    "| voice | wave | frames counted | noise ours/orig "
                    "| adsr | pulse moves ours/orig |",
                    "|---|---:|---:|---:|---:|---:|"]
            adsr_v = r.get("adsr_voices") or [{}] * len(r["wave_voices"])
            pulse_v = r.get("pulse_voices") or [{}] * len(r["wave_voices"])
            for i, v in enumerate(r["wave_voices"]):
                p = pulse_v[i]
                out.append(f"| {i} | {_fmt_pct(v['wave'])} | {v['frames']} | "
                           f"{v['our_noise_frames']}/{v['orig_noise_frames']} | "
                           f"{_fmt_pct(adsr_v[i].get('adsr'))} | "
                           f"{p.get('our_pulse_changes', 0)}/"
                           f"{p.get('orig_pulse_changes', 0)} |")

    out += blindness_section(rows)

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
        "- Timing is measured in one respect only. `drift` is how far "
        "the two sides have parted company, in frames per 1000, and it "
        "is silent about *why*: a row a fraction too short and a row "
        "the right length played from the wrong place read alike. Two "
        "files can still agree on every note and every drift figure "
        "and play at different speeds -- `drift` is a rate of "
        "divergence, not a tempo. `--pace` scores the row length, and "
        "`--audio` and `--register` are what settle the rest.",
        "- **wave** compares the waveform class only. It cannot see pitch, "
        "so a noise class agreeing on both sides says nothing about which "
        "notes are under it; and because it ignores the gate bit, a note held "
        "twice as long with the right waveform still scores 100% here. A "
        "gated-off voice keeps its last waveform latched, so silence between "
        "notes inherits the previous note's class on both sides.",
        "- **bend** cannot compare a *stepped* sweep against a *glided* one. "
        "A player that raises a note by re-reading its frequency table lands "
        "on exact semitones, and siddump names every such frame rather than "
        "printing a bend; a conversion that renders the same sweep as a "
        "portamento lands between notes and siddump prints a bend on most "
        "frames. The dimension counts only the second kind, so the two read as "
        "wildly different however faithful the conversion. `Thrust.sid` is the "
        "extreme case -- its tune *is* that sweep, the original shows 443 tie "
        "lines against 25 bends and ours 125 against 89, and the ratio comes "
        "out 43x while both sides travel comparable distances over the same "
        "notes. Goattracker cannot step a note from the wavetable without one "
        "entry per semitone, so the glide is the only encoding available and "
        "the mismatch is structural.",
        "- **bend** cannot tell a pitch bend from a voice being used as a "
        "*sample channel*. The nine digi-engine files play their samples "
        "through a SID voice by rewriting its frequency every frame, and that "
        "movement is counted wherever siddump prints it as a bend rather than "
        "as a note. The affected rows are the files SURVEY.md marks as the "
        "digi dialect; taking siddump's own classification bounds the damage "
        "but does not remove it.",
        "- **adsr**, **pul**, **filt** and **cut** are register comparisons, "
        "not sound comparisons. `adsr` scores the envelope pair frame by "
        "frame, so it sees a wrong sustain or an invented hard restart, and "
        "it cannot see an envelope that is right but reached a few frames "
        "late. **Roughly a third of its deficit is on frames where BOTH "
        "sides are gated off** (71945 of 243436 corpus-wide), and dropping "
        "them was proposed and REFUTED: gate-off starts the release phase, "
        "which is still sounding, and 67.6% of those frames differ in the "
        "release nibble. Only 9.6% of the deficit is genuinely unhearable. "
        "The row carries `adsr_gated_off` and `adsr_gated_off_audible` so "
        "the split is readable per file; the score itself drops nothing. "
        "`pul` counts duty-cycle movement and says nothing about the width "
        "or the direction of the sweep -- a pulse swept the wrong way at the "
        "right rate scores the same as one swept correctly, though `pspan` "
        "now reads the width and `pphase` where in the band a note opens; "
        "`filt` counts frames in circuit and `cut` how far the cutoff "
        "travels, neither of which says the sweep runs in the same direction "
        "or at the same moment. Resonance is inside the same $D417 byte as "
        "the routing and siddump never separates them, so resonance is not "
        "scored on its own, and master volume ($D418's low nibble) is parsed "
        "and never compared even though `filt` reads the passband bits of "
        "that same byte.",
    ]
    out.append("")
    return "\n".join(out)


# --------------------------------------------------------------------------
# A/B against a previous run
# --------------------------------------------------------------------------
# Every fork in this repo that changed conversion behaviour rebuilt this by
# hand -- convert twice, pack twice, trace twice, diff per file. At least five
# did; one did it against a contaminated shared workdir and one against a
# stale tree and had to re-run.
#
# Two settings hazards, and they are not the same hazard:
#
#  * A baseline traced at other **measurement** settings is not a baseline. A
#    10 s run against a 30 s one, or two different subtunes, are numbers about
#    different music. That refuses, loudly.
#  * A baseline converted with other **conversion** options is the opposite
#    case. FIDELITY-TOOL-IMPROVEMENTS.md §4 asks for a hard failure on any
#    settings difference, including these -- but an option A/B (`filters` off
#    against `filters` on) is the commonest thing anyone wants this mode for,
#    and refusing it would leave the apparatus being rebuilt by hand for
#    exactly the change it exists to measure. So an option difference is named
#    at the head of the output as the change under test rather than treated as
#    contamination. The hazard §4 is really guarding against -- presets
#    drifting between two runs without anyone noticing -- is answered by
#    printing it, which refusing would also have done and nothing else does.
_FATAL_SETTINGS = ("seconds", "subtune")


def settings_mismatch(base: dict, new: dict) -> list[str]:
    """Measurement settings that differ between two runs, per file.

    A field absent on one side is not a mismatch: a baseline taken before the
    field was recorded is old, not wrong, and refusing it would make every
    saved run useless the first time a field is added.
    """
    bad = []
    for name in sorted(base):
        b, n = base[name], new.get(name)
        if n is None:
            continue
        for k in _FATAL_SETTINGS:
            bv, nv = b.get(k), n.get(k)
            if bv is not None and nv is not None and bv != nv:
                bad.append(f"{name}: {k} {bv!r} -> {nv!r}")
    return bad


def option_drift(base: dict, new: dict) -> list[str]:
    """Conversion settings that differ, aggregated over the files they differ on."""
    diffs: dict[tuple, set] = {}
    for name in base:
        n = new.get(name)
        if n is None:
            continue
        bo = base[name].get("options") or {}
        no = n.get("options") or {}
        for k in set(bo) | set(no):
            if bo.get(k) != no.get(k):
                diffs.setdefault((k, repr(bo.get(k)), repr(no.get(k))), set()).add(name)
        if base[name].get("multiplier") != n.get("multiplier"):
            diffs.setdefault(("multiplier", repr(base[name].get("multiplier")),
                              repr(n.get("multiplier"))), set()).add(name)
    return [f"`{k}` {a} -> {c} on {len(f)} file(s)"
            for (k, a, c), f in sorted(diffs.items())]


# --------------------------------------------------------------------------
# Sweeping one option (or comparing any set of arms) without a hand-picked
# column list
# --------------------------------------------------------------------------
# Twice now a per-song or per-instrument comparison has reported a SUBSET of
# the scored columns and had its conclusion corrected by re-running it:
# v0.5.352/353 shipped and retracted an adoption after reading six of
# fourteen columns (`fidelity-json-omits-retrig-hold-tail`), and a firstwave
# sweep on 5_Title_Tunes recommended a combination while never printing
# `pitch`, which falls 1.0000 -> 0.9836 on the exact combination it
# recommended. Both were scratch probes that named their own column list by
# hand, which is the same shape of mistake as `report()`'s hand-typed header
# (line ~4328) -- except `report()`'s hardcoded header is caught by
# test_every_printed_column_has_a_dimension_declaring_its_registers, and a
# throwaway probe has no such test watching it.
#
# `sweep_report` cannot make that mistake: its header and every cell are
# built by iterating `DIMENSIONS`, the same registry `compare_runs`' "What
# moved" table already trusts (see its `"| File | bytes | " + " | ".join(d
# .column for d in DIMENSIONS)`). Add a Dimension there and it appears in the
# next sweep with no edit to this function -- see
# test_sweep_report_prints_a_dimension_added_after_this_function_was_written.


def sweep_report(rows: list[dict]) -> str:
    """Every scored dimension, for a set of rows representing the arms of one
    comparison -- values of a single `convert()` option swept against one
    file, a set of instruments, or whatever the caller grouped by
    `row["file"]`. Prints ALL of `DIMENSIONS`, not the subset a reader
    happens to think is relevant to the change under test: that selection is
    exactly what has misled twice (see the module note above this function).

    Each row is expected to be the output of `measure()` (or the `_row()`
    test fixture shape) -- a dict keyed by the `Dimension.key`/`.source`
    names, plus `file` and `status`. A row missing a key prints `-` for it,
    the same convention `Dimension.fmt` uses everywhere else.
    """
    out = [
        "| arm | " + " | ".join(d.column for d in DIMENSIONS) + " | status |",
        "|---|" + "---|" * len(DIMENSIONS) + "---|",
    ]
    for r in rows:
        cells = [d.fmt(d.value(r)) for d in DIMENSIONS]
        out.append(f"| {r.get('file', '?')} | " + " | ".join(cells)
                   + f" | {r.get('status', '?')} |")
    return "\n".join(out) + "\n"


def sweep_option(sid: Path, workdir: Path, args, option: str, values,
                  base_opts: dict | None = None, multiplier: int = 1) -> str:
    """Convert and measure one file once per value of a single `convert()`
    option, and report every dimension `DIMENSIONS` scores for each arm via
    `sweep_report` -- so a change recommended from this can never again be
    missing the one column that would have overturned it.

    `values` is any iterable of option values (bools, ints, strings...);
    `base_opts` holds the rest of the options held fixed across every arm
    (e.g. the file's preset). `multiplier` is the song's gt2reloc `-S` value,
    passed through to `measure` exactly as `_run` passes it.
    """
    base = dict(base_opts or {})
    rows = []
    for v in values:
        opts = dict(base)
        opts[option] = v
        row = measure(sid, workdir, opts, args, multiplier)
        row["file"] = f"{option}={v!r}"
        rows.append(row)
    return sweep_report(rows)


def _subtune_diff_note(fname: str, base_row: dict, new_row: dict) -> str:
    """One bullet naming which subtune of `fname` actually differs, if we can
    tell -- the fix for a verdict that named a register that cannot see the
    change while staying silent about a change that landed somewhere the
    report never traced (see subtune_content_shas). Never asserts silence it
    has not earned: an unparsed or pre-upgrade row falls back to naming the
    traced subtune rather than the specific one that moved.
    """
    traced = new_row.get("subtune")
    b_shas, n_shas = base_row.get("subtune_shas"), new_row.get("subtune_shas")
    if b_shas is None or n_shas is None:
        return (f"- `{fname}`: traced subtune {traced} -- per-subtune diff "
                "unavailable (one of these two runs predates it)")
    if len(b_shas) != len(n_shas):
        return (f"- `{fname}`: traced subtune {traced} -- subtune COUNT "
                f"differs ({len(b_shas)} -> {len(n_shas)}); a per-subtune "
                "diff is not meaningful here, treat every subtune as suspect")
    differing = [i for i, (x, y) in enumerate(zip(b_shas, n_shas)) if x != y]
    if not differing:
        return (f"- `{fname}`: traced subtune {traced} -- no subtune's own "
                "content changed; the differing bytes are in the header, "
                "instrument or table region every subtune shares")
    where = ", ".join(str(i) for i in differing)
    if traced in differing:
        return (f"- `{fname}`: subtune(s) {where} differ, INCLUDING the "
                f"traced one ({traced})")
    return (f"- `{fname}`: subtune(s) {where} differ -- **NOT** the traced "
            f"subtune ({traced}). This verdict says nothing about those "
            "subtunes; re-run with `-a <n>` on each to measure them")


def _subtune_diff_notes(files: list[str], base: dict, new: dict, cap: int = 20) -> list[str]:
    lines = [_subtune_diff_note(f, base[f], new[f]) for f in files[:cap]]
    if len(files) > cap:
        lines.append(f"- ... and {len(files) - cap} more")
    return lines


def _run_label(rows: list[dict], fallback: str) -> str:
    for r in rows:
        bits = [b for b in (r.get("label"), r.get("version")) if b]
        if bits:
            return " / ".join(bits)
    return fallback


def compare_runs(base_rows: list[dict], new_rows: list[dict]) -> tuple[str, int]:
    """A/B two runs. Returns (markdown, exit code); 2 means it refused.

    The verdict is the point of the mode, and it needs both halves to be
    honest. "No number moved" alone has two readings -- the change is
    invisible to everything measured, or the change reached nothing -- and
    this project has shipped the second one twice believing the first
    (`--slides` dead for four versions, `--filter` for two). The converted
    bytes tell them apart, so a run records their hash and the verdict names
    which of the two it is.
    """
    base = {r["file"]: r for r in base_rows if r.get("file")}
    new = {r["file"]: r for r in new_rows if r.get("file")}
    both = [f for f in new if f in base]

    head = [
        "# Fidelity A/B",
        "",
        f"`{_run_label(base_rows, 'baseline')}` -> "
        f"`{_run_label(new_rows, 'current')}`, "
        f"{len(both)} file(s) measured in both runs.",
        "",
    ]

    mismatch = settings_mismatch(base, new)
    if mismatch:
        shown = mismatch[:10]
        return "\n".join(head + [
            "## Refused",
            "",
            f"These two runs were traced at different measurement settings on "
            f"{len(mismatch)} file(s), so their numbers are about different "
            "music and a delta between them means nothing:",
            "",
        ] + [f"- {m}" for m in shown]
            + ([f"- ... and {len(mismatch) - len(shown)} more"]
               if len(mismatch) > len(shown) else [])
            + ["", "Re-take the baseline at the settings you are measuring at.",
               ""]), 2

    if not both:
        return "\n".join(head + ["No file appears in both runs.", ""]), 2

    # What differs before any number is compared: the options, and whether the
    # converter's output moved at all.
    drift = option_drift(base, new)
    sha_pairs = [(f, base[f].get("output_sha"), new[f].get("output_sha"))
                 for f in both]
    hashed = [(f, a, b) for f, a, b in sha_pairs if a and b]
    bytes_changed = sorted(f for f, a, b in hashed if a != b)

    out = head + ["## The change under test", ""]
    out += ([f"- conversion settings that differ: {d}" for d in drift]
            or ["- conversion settings: identical on every file in both runs"])
    if not hashed:
        out.append("- converted bytes: **unknown** -- one of these runs "
                   "predates the per-row output hash, so this comparison "
                   "cannot say whether the change reached the converter's "
                   "output at all")
    elif bytes_changed:
        out.append(f"- converted bytes differ on **{len(bytes_changed)}** of "
                   f"{len(hashed)} file(s)")
    else:
        out.append(f"- converted bytes are **identical on all {len(hashed)} "
                   "file(s)**")

    # Movement, per file per dimension. Exact inequality, because two runs of
    # the same code produce the same floats; anything looser would hide the
    # case this mode exists to name.
    moved: dict[str, dict[str, tuple]] = {}
    status_changed = []
    for f in both:
        b, n = base[f], new[f]
        deltas = {}
        for d in DIMENSIONS:
            x, y = d.value(b), d.value(n)
            if x != y:
                deltas[d.key] = (x, y)
        if b.get("status") != n.get("status"):
            status_changed.append((f, b.get("status"), n.get("status")))
        if deltas:
            moved[f] = deltas
    printed = {f: {k: v for k, v in ds.items()
                   if _dim(k).fmt(v[0]) != _dim(k).fmt(v[1])}
               for f, ds in moved.items()}
    printed = {f: ds for f, ds in printed.items() if ds}

    out += ["", "## Verdict", ""]
    # Derived from what this run actually computed, not from the registry:
    # a run that lost `wave` on every file is blind to $D404 as well, and
    # saying otherwise would overstate the reach of the comparison.
    present = {k for r in new_rows
               for k in r.get("dimensions", dimensions_present(r))}
    unread = registers_unread(present)
    if not moved and not status_changed:
        if bytes_changed:
            out += [
                "**No dimension this report measures can see this change.**",
                "",
                f"The converter's output changed on {len(bytes_changed)} of "
                f"{len(hashed)} file(s) and not one number moved -- not by a "
                "rounding, by nothing. That is a result, not a null result: "
                "the change reached the output and every dimension here is "
                "structurally incapable of registering it. It can only have "
                "landed in:",
                "",
            ] + [f"- `{reg}` -- {what}" for reg, what in unread] + [
                "",
                "or in note length, tempo, or a part of the file outside the "
                "traced window. Judge it by ear or by a dimension this "
                "harness does not have -- `listen.py` is the only check "
                "that spans the rest.",
                "",
                "**Which subtune actually differs, per file** (a change "
                "outside the traced subtune is exactly how this verdict has "
                "stated the opposite of the truth before -- Star_Paws, "
                "boundary-tie-loop-around-restart-position):",
                "",
            ] + _subtune_diff_notes(bytes_changed, base, new)
        elif hashed:
            out += [
                "**This change reaches nothing.**",
                "",
                f"All {len(hashed)} file(s) convert to byte-identical output "
                "and no number moved. Either the change genuinely is a no-op, "
                "or it is wired up somewhere that never runs -- the shape of "
                "`--slides`, dead for four versions, and of `--filter`, which "
                "v0.5.72 wired into `convert()` and README and into neither "
                "the presets nor this harness. Check the option reaches "
                "`presets.py`'s `FIXED` and `_preset_opts` before concluding "
                "the first.",
            ]
        else:
            out += [
                "**No number moved**, and this comparison cannot say whether "
                "the converter's output did: one of the two runs predates the "
                "output hash. Re-take the baseline with this version to tell "
                "an invisible change from an inert one.",
            ]
    elif not printed and not status_changed:
        out += [
            "**Every movement here is below the precision the report prints.**",
            "",
            f"{len(moved)} file(s) moved on some dimension, and "
            "`FIDELITY.md` would have looked identical either way. A reader "
            "comparing the two tables would have called this a no-op; the "
            "raw deltas are below.",
        ]
    else:
        out += [
            f"**{len(printed)} of {len(both)} file(s) move the printed "
            f"report**"
            + (f", {len(moved) - len(printed)} more move only below its "
               "precision" if len(moved) > len(printed) else "")
            + (f", and {len(status_changed)} change status" if status_changed
               else "") + ".",
        ]
        # The partial case, and the one that actually occurs: most of the
        # corpus changed and said nothing. A verdict that reports only the
        # files that moved reproduces the misreading at a smaller scale --
        # "three files moved, so the report saw it" -- when what happened is
        # that eighty files could not.
        touched = set(f for f, _, _ in status_changed) | set(moved)
        blind = [f for f in bytes_changed if f not in touched]
        if blind:
            out += [
                "",
                f"**{len(blind)} of the {len(bytes_changed)} file(s) whose "
                "converted output changed moved no number at all.** On those "
                "this report cannot tell the change from a no-op: it can only "
                "have landed in "
                + ", ".join(f"`{reg}`" for reg, _ in unread)
                + ", in note length, in tempo, or outside the traced window.",
                "",
            ] + _subtune_diff_notes(blind, base, new)

    # The integrity check that falls out of having both halves: identical
    # bytes that measure differently is the harness moving, not the converter.
    if hashed:
        same_bytes_moved = sorted(set(moved) - set(bytes_changed))
        same_bytes_moved = [f for f in same_bytes_moved
                            if base[f].get("output_sha") and new[f].get("output_sha")]
        if same_bytes_moved:
            out += [
                "",
                f"**{len(same_bytes_moved)} file(s) convert to identical bytes "
                "and still moved.** The movement is in the harness or its "
                "tools, not in the conversion: "
                + ", ".join(same_bytes_moved[:8])
                + (", ..." if len(same_bytes_moved) > 8 else "") + ".",
            ]

    if status_changed:
        out += ["", "## Status changes", "", "| File | was | is |", "|---|---|---|"]
        out += [f"| {f} | {a} | {b} |" for f, a, b in sorted(status_changed)]

    if moved:
        ranked = sorted(
            moved,
            key=lambda f: max(_dim(k).movement(*moved[f][k]) for k in moved[f]),
            reverse=True)
        cap = 40
        out += [
            "",
            "## What moved",
            "",
            "Sorted by the largest movement on any one dimension, because the "
            "useful reading is nearly always *which files did this touch* "
            "rather than the mean. A `.` is a dimension that did not move; "
            "`!` marks a movement the printed report would not have shown.",
            "",
            "| File | bytes | " + " | ".join(d.column for d in DIMENSIONS) + " |",
            "|---|:-:|" + "---|" * len(DIMENSIONS),
        ]
        for f in ranked[:cap]:
            cells = []
            for d in DIMENSIONS:
                if d.key not in moved[f]:
                    cells.append(".")
                    continue
                x, y = moved[f][d.key]
                mark = "" if d.fmt(x) != d.fmt(y) else " !"
                cells.append(f"{d.fmt(x)} -> {d.fmt(y)}{mark}")
            sha_a, sha_b = base[f].get("output_sha"), new[f].get("output_sha")
            byt = "?" if not (sha_a and sha_b) else ("!=" if sha_a != sha_b else "==")
            out.append(f"| {f} | {byt} | " + " | ".join(cells) + " |")
        if len(ranked) > cap:
            out.append(f"| ... {len(ranked) - cap} more | | "
                       + " | ".join("" for _ in DIMENSIONS) + " |")

        out += ["", "### Per dimension", "",
                "| dimension | files moved | mean delta | largest |",
                "|---|---:|---:|---|"]
        for d in DIMENSIONS:
            hits = [moved[f][d.key] for f in moved if d.key in moved[f]]
            if not hits:
                out.append(f"| **{d.column}** | 0 | - | - |")
                continue
            reals = [(x, y) for x, y in hits if x is not None and y is not None]
            mean = (sum(y - x for x, y in reals) / len(reals)) if reals else None
            worst = max(hits, key=lambda p: d.movement(*p))
            wf = max((f for f in moved if moved[f].get(d.key) == worst), default="")
            mean_s = "-" if mean is None else (
                f"{100 * mean:+.1f} pp" if d.kind == "fraction"
                else f"{mean:+.2f}" if d.kind == "ratio" else f"{mean:+.1f}")
            out.append(f"| **{d.column}** | {len(hits)} | {mean_s} | "
                       f"{d.fmt(worst[0])} -> {d.fmt(worst[1])} ({wf}) |")

    only_new = sorted(set(new) - set(base))
    only_base = sorted(set(base) - set(new))
    if only_new or only_base:
        out += ["", "## Not in both runs", ""]
        if only_new:
            out.append(f"- only in the current run ({len(only_new)}): "
                       + ", ".join(only_new[:12])
                       + (", ..." if len(only_new) > 12 else ""))
        if only_base:
            out.append(f"- only in the baseline ({len(only_base)}): "
                       + ", ".join(only_base[:12])
                       + (", ..." if len(only_base) > 12 else ""))
    out.append("")
    return "\n".join(out), 0


def _dim(key: str) -> Dimension:
    return next(d for d in DIMENSIONS if d.key == key)


# --------------------------------------------------------------------------
# --ticks: the player's own sequencer period, read out of its cycle count
# --------------------------------------------------------------------------
# siddump -z prints the cycles the play routine burned on each frame
# (siddump.c:470-478). A Hubbard player does markedly more work on the frame
# its sequencer steps -- it fetches the next pattern byte, reloads durations
# and rewrites the SID -- than on a frame where it only runs its envelopes.
# So the frames on which the cycle count jumps *are* the tick frames, and the
# gaps between them are the tune's row period in frames.
#
# This measures the ORIGINAL alone. It needs no conversion, no gt2reloc and no
# note matching, which is what makes it a check on `find_song_speeds` rather
# than on the conversion: --pace can only say our row disagrees with theirs,
# and this says what theirs is. It also reaches the files --pace cannot time
# at all, the ones where the two sides share too little material.
CYCLE_COLUMN = re.compile(r"\|\s+(\d+)\s+[0-9A-F]{2}\s+[0-9A-F]{2}\s*\|\s*$")

# The first frames are the player's init settling: frame 0 runs no playroutine
# work worth comparing and the first real frame sets up every voice at once,
# which is a spike belonging to no period. Four is enough on this corpus and
# small enough to leave a 10s window 496 frames to work with.
TICK_SKIP = 4

# Share of gaps that must be a whole multiple of the modal gap before a period
# is reported at all. See tick_period for how this was calibrated.
TICK_MIN_REGULAR = 0.90


def cycle_series(sid: Path, seconds: int, subtune: int, exe: str = SIDDUMP,
                 calls: int = 1) -> list[int]:
    """Play-routine cycles per frame, from siddump -z."""
    cmd = [exe, str(sid), f"-a{subtune}", f"-t{seconds}", "-z"]
    if PAL_FLAG is not None and supports_video_flag(exe):
        cmd.append(f"-v{PAL_FLAG}")
    if calls > 1:
        if not supports_calls_per_frame(exe):
            raise RuntimeError(f"{exe} does not support -m")
        cmd.append(f"-m{calls}")
    proc = subprocess.run(cmd, capture_output=True, text=True, timeout=180,
                          stdin=subprocess.DEVNULL)
    out = []
    for line in proc.stdout.splitlines():
        m = CYCLE_COLUMN.search(line)
        if m:
            out.append(int(m.group(1)))
    return out


def otsu(values: list[int]) -> int:
    """Threshold splitting `values` into two classes, maximising the variance
    between them.

    Otsu's method, and it is here so that nothing in this file carries a
    hand-set cycle threshold: what counts as "more work" differs by an order
    of magnitude between a three-voice player and a digi engine, and a
    constant tuned on one file is exactly the sort of thing that reads
    plausibly on the rest.
    """
    lo, hi = min(values), max(values)
    if lo == hi:
        return lo
    best, best_var = lo, -1.0
    for t in range(lo, hi):
        under = [v for v in values if v <= t]
        over = [v for v in values if v > t]
        if not under or not over:
            continue
        w0, w1 = len(under) / len(values), len(over) / len(values)
        m0, m1 = sum(under) / len(under), sum(over) / len(over)
        var = w0 * w1 * (m0 - m1) ** 2
        if var > best_var:
            best, best_var = t, var
    return best


def local_ratio(cycles: list[int], half: int = 12) -> list[float]:
    """Each frame's cycles over the median of its neighbourhood.

    A global threshold cannot find the tick frames, because the baseline
    itself moves with the music: Deep_Strike spends its first seconds around
    700 cycles a frame and its later ones around 1300, and Otsu over the whole
    series splits those two *sections* and calls 328 consecutive frames busy.
    Dividing by a local median removes the section and leaves the spike.
    """
    out = []
    for i in range(len(cycles)):
        window = sorted(cycles[max(0, i - half):i + half + 1])
        med = window[len(window) // 2] or 1
        out.append(cycles[i] / med)
    return out


def tick_period(cycles: list[int], skip: int = TICK_SKIP) -> dict:
    """Frames between the play routine's busy frames.

    Returns `period` only when the busy frames are distinguishable and
    periodic. Both refusals matter: a player doing the same work every frame
    has no visible tick, and spikes that are a filter sweep rather than a
    sequencer step would give a number with no meaning.

    Missed detections are inferred rather than averaged over. A tick whose
    frame happens not to clear the threshold turns one gap of `b` into one of
    `2b`, and taking the mean of the gaps would then report a period half
    again too long -- Tarzan's gaps are 3 (x89) and 6 (x37), and its mean gap
    is 3.88 where its period is 3.0. Counting each gap as `round(gap / modal)`
    ticks recovers it, and it leaves a genuinely alternating player alone:
    Deep_Strike's 3, 3, 2 all round to one tick each, so its period comes out
    as the 2.67 it really is rather than being forced to an integer.
    """
    body = cycles[skip:]
    if len(body) < 32:
        return {"frames": len(body), "why": "too few frames"}
    ratio = local_ratio(body)
    scaled = [int(r * 1000) for r in ratio]
    t = otsu(scaled)
    busy = [i for i, v in enumerate(scaled) if v > t]
    quiet = [v for v in scaled if v <= t]
    if len(busy) < 8:
        return {"frames": len(body), "why": "fewer than 8 busy frames"}
    share = len(busy) / len(body)
    if share > 0.6:
        return {"frames": len(body), "share": share,
                "why": "no quiet class -- every frame does similar work"}
    hi = [scaled[i] for i in busy]
    lift = (sum(hi) / len(hi)) / (sum(quiet) / len(quiet)) if quiet else 0.0
    if lift < 1.05:
        return {"frames": len(body), "lift": lift,
                "why": "busy and quiet frames differ by under 5%"}
    gaps = [b - a for a, b in zip(busy, busy[1:])]
    modal = max(set(gaps), key=gaps.count)
    ticks = sum(max(1, round(g / modal)) for g in gaps)
    span = busy[-1] - busy[0]
    # An exact multiple, not a near one. A tolerance of +-1 frame sounds
    # harmless and is not: at a modal gap of 3 it accepts 2, 4, 5, 7 and 8 as
    # well, which is nearly every gap, and the field stops discriminating
    # exactly where it is needed.
    fit = sum(1 for g in gaps if g % modal == 0)
    regular = fit / len(gaps)
    common = {"frames": len(body), "busy": len(busy), "threshold": t / 1000,
              "lift": lift, "share": share, "modal": modal, "regular": regular}
    # Calibrated, not chosen: ungated this agrees with --pace on 53% of the
    # files both can measure, and gated on these two it agrees on 27 of 27.
    # `regular` is the field that carries the information -- when the gaps are
    # whole multiples of one base the busy frames really are the sequencer,
    # and when they are not, the spikes are something else with its own
    # rhythm (an envelope, a filter sweep, a digi channel) and the period
    # would be a confident wrong number. See tests/test_ticks.py.
    if modal < 2:
        return {**common, "why": "modal gap of 1 frame -- no period visible "
                                 "above the per-frame work"}
    if regular < TICK_MIN_REGULAR:
        return {**common,
                "why": f"only {regular:.0%} of gaps are a whole number of the "
                       f"modal {modal} -- the busy frames are not one period"}
    return {**common, "gaps": gaps,
            "period": span / ticks if ticks else None}


def ticks_report(sid: Path, args) -> str:
    """What `--ticks` prints for one file."""
    traced = resolve_subtune(sid, args.subtune)
    try:
        cyc = cycle_series(sid, args.seconds, traced, args.siddump)
    except (OSError, subprocess.SubprocessError) as exc:      # noqa: BLE001
        return f"{sid.name}: siddump failed -- {exc}\n"
    got = tick_period(cyc)
    try:
        hdr = load_sid(str(sid))
        speeds = find_song_speeds(hdr)
        read = speeds.frames_for(traced) if speeds is not None else None
    except Exception:                                          # noqa: BLE001
        read = None
    head = (f"{sid.name}: subtune {traced}, {args.seconds}s, "
            f"speed gate reads {read if read is not None else 'nothing'}")
    # A CIA-timed original is not called 50 times a second on hardware, and
    # siddump calls it 50 times a second regardless. The period below is then
    # per *call* and not per frame, so it cannot be compared with a row length
    # measured in real time -- Human_Race reads 4.00 here and 5.33 under
    # --pace for exactly this reason.
    try:
        cia = load_sid(str(sid)).is_cia_timed(traced)
    except Exception:                                          # noqa: BLE001
        cia = False
    if cia:
        head += ("\n  !! this subtune's PSID speed bit says CIA, so its real "
                 "call rate is not 50Hz and the period below is per call")
    if "period" not in got:
        return f"{head}\n  no tick period: {got['why']}\n"
    lines = [head,
             f"  {got['busy']} busy frames in {got['frames']}, "
             f"{got['lift']:.2f}x their neighbours; gaps modal "
             f"{got['modal']}, {got['regular']:.0%} of them a whole number "
             f"of those",
             f"  **player ticks every {got['period']:.2f} frames**"]
    if read:
        err = abs(got["period"] - read) / read
        lines.append(f"  the gate is {'right' if err <= 0.05 else 'wrong'}: "
                     f"read {read}, measured {got['period']:.2f} "
                     f"({err:.0%} out)")
    return "\n".join(lines) + "\n"


# --------------------------------------------------------------------------
# --pace: does the conversion play at the tune's speed?
# --------------------------------------------------------------------------
# Below this many matched gaps, or above this relative interquartile range,
# the ratio is not a measurement. Calibrated against the corpus: the files
# whose row length is independently confirmed carry 100-400 gaps at an IQR of
# 0-3%, while the two that produced §7c carried 7 and 19.
MIN_PACE_GAPS = 40
# **RE-DERIVED AT v0.5.417, and the bound sits in an EMPTY REGION.** It was 0.10,
# calibrated when the confirmed files carried "an IQR of 0-3%" -- true then, and
# false since the gate readings of v0.5.248/402/410 gave many files an exactly
# FRACTIONAL row, whose gaps legitimately alternate (8/3 frames is 3,3,2).
#
# Measured, not guessed, and NON-CIRCULARLY: take the 43 files whose pacing is
# confirmed by OTHER columns (melody >= 99%, drift 0.00, retrigger within 2% of
# 1.00) and look at the IQR they actually show. Median 0.000, p90 0.191, MAX
# **0.310** -- so 0.10 was refusing 8 of the 43 files it should have been
# vouching for. Every one of the 8 has a fractional row.
#
# The whole corpus's IQRs, sorted, around the decision region:
#
#     ... 0.133  0.152  0.191 x6  0.310  |  1.500  1.600  2.455  5.727
#
# There is NOTHING between 0.31 and 1.50, so any bound in [0.32, 1.49] gives
# identical behaviour and this is a threshold with a gap under it rather than a
# number fitted to the data. 0.35 is the conservative end of that range.
#
# The four that stay refused are the right four -- Dragons_Lair_Part_II (5.727,
# melody 14%), Commodore_64_Music_Examples (1.600, melody 14%), Chicken_Song
# (1.500) and Rikky (2.455). They are the separate "wildly spread ratio"
# population and must NOT be folded into this bound.
#
# THE COUNTERFACTUAL WAS CHECKED BEFORE THE CHANGE, because a loosened veto is
# only safe if what it admits is sound: the 10 newly-timed files return a median
# of exactly 1.000 in NINE cases (the tenth, Bump_Set_Spike, reads 1.077 and is
# a real measurement). Thundercats is the one worth naming -- melody 77% and a
# median of exactly 1.000, which is precisely the melody-is-not-a-clock
# distinction --pace exists to draw.
MAX_PACE_IQR = 0.35
# ...and the matched notes must cover enough of the original to be a sample of
# it rather than of whichever fragment happened to survive the conversion.
#
# LEFT ALONE AT v0.5.417, with the measurement written down rather than a change
# made: NONE of the 43 independently-confirmed files falls below 0.30 (their
# minimum coverage is 0.718), so there is no evidence to move it. The note that
# prompted the re-derivation -- "five of the six files refused for COVERAGE
# convert at 97-100% melody" -- is STALE: only TWO files are coverage-refused
# today, Commodore_64_Music_Examples (0.102) and Dragons_Lair_Part_II (0.081),
# and both convert at 14% melody, so both refusals are correct. The other four
# stopped being refused on their own as note matching improved.
MIN_PACE_COVERAGE = 0.30

# Two onsets close together say nothing about a drift of a frame per hundred:
# the difference of their offsets is quantised to whole frames, so a short
# baseline turns rounding into a slope of any size. Only pairs at least this
# far apart contribute to the Theil-Sen estimate.
MIN_DRIFT_BASELINE = 250

# A voice contributes only if difflib matched enough of it, and enough of what
# the original plays there, to be reading the same music. Both gates are the
# lesson of Powerplay's voice 1: 17 matched onsets is not few in absolute
# terms, but against 68 of the original's it is a quarter, and the offsets it
# reports are hundreds of frames.
MIN_DRIFT_ONSETS = 12
MIN_DRIFT_COVERAGE = 0.30

# How far the matched offsets may scatter about the fitted line, as a share of
# the traced window, before the line stops being a description of them.
DRIFT_MAX_SCATTER = 0.01


def matched_gaps(orig: Voice, ours: Voice,
                 floor: int = 4) -> list[tuple[int, int]]:
    """(their frames, our frames) for consecutive notes both sides play.

    Aligned with difflib rather than by index, because index alignment is
    only meaningful where the two note sequences agree -- which is never true
    of a file whose pace is in question. Gaps below `floor` frames are
    dropped: those are chord onsets and same-row retriggers, where the
    quantisation swamps the ratio being measured.
    """
    sm = difflib.SequenceMatcher(None, orig.attacks, ours.attacks,
                                 autojunk=False)
    pairs = []
    for i, j, n in sm.get_matching_blocks():
        for k in range(n):
            pairs.append((orig.attack_frames[i + k], ours.attack_frames[j + k]))
    out = []
    for (a0, b0), (a1, b1) in zip(pairs, pairs[1:]):
        if a1 - a0 >= floor:
            out.append((a1 - a0, b1 - b0))
    return out


def matched_onsets(orig: Voice, ours: Voice) -> list[tuple[int, int]]:
    """(their frame, our frame) for every note both sides play, absolute.

    `matched_gaps` differences these and throws the absolute positions away,
    which is right for a row-length ratio and wrong for anything cumulative.
    """
    sm = difflib.SequenceMatcher(None, orig.attacks, ours.attacks,
                                 autojunk=False)
    return [(orig.attack_frames[i + k], ours.attack_frames[j + k])
            for i, j, n in sm.get_matching_blocks() for k in range(n)]


# A knee this size is worth saying out loud. Not fitted to the corpus: it is
# two frames per second of divergence-rate difference between the halves, well
# clear of the 0.15-1.4 spread the 82 knee-free files show and well under
# Rasputin's 46. The corpus splits 4 above 5, 1 above 25, 0 above 50.
DRIFT_KNEE_PER_1000 = 5.0
# Below this many pairs a half is not a fit, it is a coincidence.
MIN_DRIFT_HALF = 4


def _theil_sen_per_1000(pairs) -> float | None:
    """The median pairwise slope of `pairs`, in frames per 1000.

    The same estimator `drift` uses on the whole window, factored out so a
    half cannot silently be fitted by a different rule than the whole -- which
    is the failure the `--vice` translation made (a new instrument scored
    under a new rule, and the difference read as a finding).
    """
    slopes = []
    for i in range(len(pairs)):
        ai, di = pairs[i][0], pairs[i][1] - pairs[i][0]
        for j in range(i + 1, len(pairs)):
            dx = pairs[j][0] - ai
            if dx >= MIN_DRIFT_BASELINE:
                slopes.append(((pairs[j][1] - pairs[j][0]) - di) / dx * 1000.0)
    if not slopes:
        return None
    slopes.sort()
    return slopes[len(slopes) // 2]


# Everything `drift()` reports that a ROW carries beyond the headline rate,
# named ONCE so `_measure` cannot fall behind `drift()` again. A key added to
# the estimator and not to this tuple reaches no artefact, which is exactly how
# the knee shipped inert at v0.5.456. `tests/test_drift_knee.py` asserts this
# tuple covers every extra key `drift()` can return, so the next field cannot
# repeat it silently.
DRIFT_ROW_KEYS = ("half_early_per_1000", "half_late_per_1000",
                  "knee_per_1000", "knee")


def drift(orig: Trace, ours: Trace) -> dict:
    """Accumulated phase error: frames gained or lost per 1000 frames.

    **`unfitted` IS A CORRECT ANSWER, NOT A GAP TO BE CLOSED, and One_on_One
    under `--regrid` is the case that establishes it** (measured v0.5.453).
    That file was carried for two sessions as "offsets wander so drift cannot
    be fitted", with a proposed fix of replacing `MIN_DRIFT_COVERAGE` -- "a
    COUNT gate where the problem is the SPREAD" -- with a spread gate. Three
    things are wrong with that framing and all three are measurable:

    * **The coverage gate is not what declines it.** At `-t 60` with regrid
      on, ALL THREE voices pass both gates (coverage 0.982 / 0.981 / 0.457).
      The refusal is the `unfitted` branch below, on `mad` 725 frames over a
      span of 2967 -- so **a spread gate already exists** and is exactly what
      fired. The proposal was to build something the code already had.
    * **Voice 2's scatter is the cause, proved by masking rather than
      inferred.** Mask voice 2 at `-t 60` and the remaining two fit at -38.0
      per 1000 with `mad` 21.9, against `mad` 725 and no rate with it in.
    * **The coverage gate is too PERMISSIVE at 60 s, not too strict**, which
      is the opposite of the diagnosis. At `-t 180` voice 2's coverage falls
      to 0.260, `MIN_DRIFT_COVERAGE` EXCLUDES it, and the file reports a rate
      of **-3.25** per 1000 off the remaining two. The gate is what rescues
      the longer window.

    **AND IT EXPLAINS WHY `test_one_wild_voice_does_not_poison_the_others`
    PASSES WHILE THIS FILE IS REFUSED, which is a fact about `mad` being a
    MEDIAN.** `mad` is the median absolute deviation of the pooled offsets
    about the fit, and the refusal is `mad > DRIFT_MAX_SCATTER * span`. A
    median is decided by whichever voice contributes most of the pairs:

    * That test's wild voice is a MINORITY (one of three, equal counts) with
      symmetric +/-700 scatter, so its residuals sit in the tails and never
      reach the median. The fit survives -- correctly.
    * One_on_One's voice 2 contributes **170 of 332 pooled pairs, a 51%
      majority**, and its own offsets are NON-LINEAR across the window
      (spanning 9 to 1596). Being the majority, its scatter IS the median, so
      `mad` reads 725 against a span of 2967 and the fit is refused --
      correctly again.

    So the two outcomes are the same rule applied to a minority and to a
    majority, not a robustness claim with a hole in it. What neither the test
    nor this docstring should say is that voice 2 "diverges monotonically": a
    straight divergence, however steep, is a DRIFT and gets fitted with a
    small `mad`. It is the wandering that is refused, which is exactly what
    the `unfitted` message says.

    **What `pace` cannot see, and why it is not a defect in `pace`.** That
    measure compares one gap to one gap, which is exactly right for a row of
    the wrong *length* -- such an error shows up in every gap and the median
    reports it. But a row that is a fraction of a frame wrong cannot appear in
    a gap at all: a Goattracker row is a whole number of play calls, so the
    error is zero on most gaps and one whole frame on the occasional one, and
    the median of those ratios is 1.000 exactly. Powerplay Hockey reads
    `median 1.000, IQR 0.980-1.000` over 348 gaps while its notes arrive four
    frames early by the tenth second, and both readings are correct.

    Integrating is what makes it visible. This regresses the *offset* between
    the two sides against elapsed time over difflib-matched onsets:

        ours[k] - orig[k]  =  intercept + slope * orig[k]

    `slope` is the drift and `intercept` is the startup lag, so the lag falls
    out rather than having to be estimated and subtracted -- which is worth
    saying plainly, because every per-frame column in this report *does* have
    to estimate it and one of them was charged for it until v0.5.175.

    Reported as `per_1000` (frames per 1000 frames, positive = we run late)
    and `total` (the offset accumulated across the traced window, which is
    what a listener would hear as the two copies parting company).

    **What it found, and it is not a new defect.** On this corpus the drift is
    the *outer gate's skipped call*, and the relation is exact:

        drift  =  -1 / (skip + 1)

        Sanxion   skip 108   true row 3.0278   emitted 3   -9.174 vs -9.17
        IK+       skip 112   true row 3.0268   emitted 3   -8.850 vs -8.85
        Ricochet  skip 127   true row 2.0157   emitted 2   -7.813 vs -7.81

    `effective_frames` corrects the row for that skip when the corrected value
    can be packed -- Delta's 5/2 at -S2, Thrust's 10/3 at -S3 -- and falls back
    to the raw gate when it cannot, because 3 x 113/112 wants 339 calls at
    -S112. Those files drift by exactly the correction that was declined:
    about 0.8-0.9%, some 25 frames -- half a second -- across a 60 s window.
    Files whose skip is small (Tarzan 2, Delta 4, Thrust 9) read 0.00.

    So this measures a *known* limitation rather than finding a new one; what
    it adds is that the limitation now has a number, per file. The honest fix
    is re-gridding the rows, not a tempo.

    Pools the qualifying voices' pairs for the offset statistics: they share
    one clock, and a voice resting through a section simply contributes no
    onsets rather than a long gap that would dominate a ratio.
    """
    # **Per voice, and only the voices difflib actually matched.** Pooling
    # all three was the first design and it is wrong twice over. Cross-voice
    # pairs are meaningless -- two voices' notes have no fixed relationship,
    # so the difference of their offsets is not a drift over any baseline --
    # and one badly matched voice destroys the estimate for the others.
    # Powerplay's voice 1 matches 17 of the original's 68 notes at offsets of
    # +845 and +1036 frames, which is difflib pairing unrelated notes; its
    # voice 2 matches 45 of 215 and reads a clean straight line from +4 to
    # -29. Pooled, the intercept came out +17.8 frames where the harness's own
    # `startup_lag` says 5 -- the disagreement being the signal that the
    # estimate was reporting the wrong voice.
    per_voice, pairs = [], []
    for v in range(3):
        got = matched_onsets(orig[v], ours[v])
        total = len(orig[v].attacks)
        if len(got) < MIN_DRIFT_ONSETS or not total:
            continue
        if len(got) / total < MIN_DRIFT_COVERAGE:
            continue
        got.sort()
        per_voice.append(got)
        pairs += got
    if not per_voice:
        return {"n": 0}
    n = len(pairs)
    pairs.sort()
    # **Theil-Sen, not least squares.** difflib matches notes over the whole
    # window, and once the two sides diverge -- a cue that ends where ours
    # loops, a section we drop -- the late pairs carry offsets of hundreds of
    # frames. A least-squares fit is not robust to those: on Powerplay it
    # returned -12.5 frames/1000 with a residual of 27 against a total of 37,
    # and an intercept of +38 frames where the harness's own `startup_lag`
    # estimator says 5. An estimator whose intercept contradicts a measured
    # quantity is reporting the outliers, not the drift.
    #
    # The median of pairwise slopes ignores them by construction, and the
    # spread of those slopes is the honest statement of how straight the
    # line is.
    slopes = []
    for got in per_voice:
        for i in range(len(got)):
            ai, di = got[i][0], got[i][1] - got[i][0]
            for j in range(i + 1, len(got)):
                dx = got[j][0] - ai
                if dx >= MIN_DRIFT_BASELINE:
                    slopes.append(((got[j][1] - got[j][0]) - di) / dx)
    if not slopes:
        return {"n": n}
    slopes.sort()
    slope = slopes[len(slopes) // 2]
    q1 = slopes[len(slopes) // 4]
    q3 = slopes[3 * len(slopes) // 4]
    span = pairs[-1][0] - pairs[0][0]
    # Offsets about the fitted line, median absolute deviation. Robust for the
    # same reason the slope is, and it is what says whether the offset is
    # accumulating (small) or wandering (large).
    offs = [(b - a) - slope * a for a, b in pairs]
    med = sorted(offs)[len(offs) // 2]
    mad = sorted(abs(o - med) for o in offs)[len(offs) // 2]
    out = {"n": n, "voices": len(per_voice),
           "per_1000": slope * 1000, "total": slope * span,
           "span": span, "mad": mad, "intercept": med,
           "q1_per_1000": q1 * 1000, "q3_per_1000": q3 * 1000}
    # **A rate of divergence is only a reading if the divergence is a line.**
    # `mad` was computed from the first version of this and then not used,
    # which let two rows into the report that describe nothing: Knucklebusters
    # printed the corpus-worst `+1151` from one voice at MAD 82 with melody
    # 50%, and Rock Tells the Tale printed `0.0` at MAD 93. Both are two
    # sides wandering, not parting company at a rate.
    #
    # The bound is the scatter as a share of the traced window, and 1% is a
    # musical claim rather than a constant fitted here: 30 frames in a
    # 3000-frame trace, about 0.6 s: past that the two copies are not in a
    # stable phase relationship at all. The corpus agrees without being asked
    # to -- 90% of files sit under 0.02%, the genuine large drifts (Rasputin
    # 0.33%, Spellbound 0.67%) well inside it, and the two artefacts at 3.1%
    # and 5.2%.
    #
    # Known weak spot, stated rather than gated on one file: Kings of the
    # Beach ingame matches onsets over only 320 frames of a 3000-frame window
    # and passes this, so its figure rests on a tenth of the trace.
    if mad > DRIFT_MAX_SCATTER * span:
        out["per_1000"] = None
        out["unfitted"] = (f"offsets scatter {mad:.0f} frame(s) about the fit "
                           f"over {span} -- the two sides wander rather than "
                           f"drift, so no rate describes them")
        return out
    # **A KNEE IS A THIRD SHAPE, AND `mad` CANNOT SEE IT.** The gate above
    # separates *drifting* from *wandering*. It does not separate a single
    # rate from TWO rates: an offset that runs at one slope for half the
    # window and another for the rest is still close to A line, so its `mad`
    # stays small and the fit is accepted -- while the single number it
    # reports describes neither half.
    #
    # Censused over the corpus at v0.5.455: **8 of the 89 measured files have
    # halves differing by 5 frames/1000 or more, 3 by 10, 2 by 25, none by
    # 50.** A rare shape rather than a class, which is why it is REPORTED
    # rather than refused -- declining the fit would cost 81 files a good
    # number in order to describe eight.
    #
    #   Rasputin        -8.16 ->  +41.16   (reported as a single -4.34)
    #   Lakers_vs_Celt -38.46 ->   +0.00
    #   Rikky           -1.93 ->  -24.39
    #   Bangkok_Knights -8.85 ->   +0.00
    #   Wiz             -0.76 ->   +7.30
    #   Powerplay      -16.39 ->   -8.43
    #   Monty           -9.69 ->   -3.18
    #   5_Title_Tunes   +0.00 ->   +6.21
    #
    # Rasputin is the sharpest: a SIGN REVERSAL at `mad` 5.8, comfortably
    # inside the scatter gate, so nothing here could see it before.
    #
    # **THE FIRST CENSUS OF THIS SAID 4, AND IT WAS WRONG FOR THE REASON THIS
    # FILE WARNS ABOUT.** The probe fitted the halves with its own copy of the
    # estimator that omitted `MIN_DRIFT_BASELINE`, so halves and whole were
    # scored under different rules and the difference read as a finding --
    # the `--vice` translation failure exactly. `_theil_sen_per_1000` exists
    # so that cannot recur: the halves and the whole now call one function.
    #
    # Split per voice and pooled the same way the fit itself pools, so a voice
    # resting through a section contributes to neither half rather than
    # straddling the midpoint of a window it is absent from.
    early, late = [], []
    for got in per_voice:
        mid = len(got) // 2
        if mid >= MIN_DRIFT_HALF and len(got) - mid >= MIN_DRIFT_HALF:
            early += got[:mid]
            late += got[mid:]
    if len(early) >= MIN_DRIFT_HALF and len(late) >= MIN_DRIFT_HALF:
        a1, a2 = _theil_sen_per_1000(early), _theil_sen_per_1000(late)
        if a1 is not None and a2 is not None:
            out["half_early_per_1000"] = a1
            out["half_late_per_1000"] = a2
            out["knee_per_1000"] = abs(a1 - a2)
            if abs(a1 - a2) >= DRIFT_KNEE_PER_1000:
                out["knee"] = (
                    f"the offset is not one rate: {a1:+.1f} per 1000 over the "
                    f"first half of the matched onsets and {a2:+.1f} over the "
                    f"second, so the reported {out['per_1000']:+.1f} describes "
                    f"neither half")
    return out


def pace(orig: Trace, ours: Trace) -> dict:
    """How long our row is against the original's, and how uniformly.

    `median` is the ratio to read: a few very long gaps -- a voice resting
    through a section -- dominate a least-squares fit, and on ACE_II the fit
    comes out 0.727 where the median of the same ratios is 1.509, disagreeing
    about which side is faster. `slope` is kept beside it because the two
    parting company is itself a signal that the material diverges.

    **What this measures is note-to-note timing, which is `rows per note` x
    `row length` -- and it cannot separate the two.** A conversion that gives
    every note 4 rows where the player gives it 3 units reads exactly like one
    whose rows are 4/3 too long, and the IQR is tight in both cases. Spellbound
    is the file where they diverge: `--pace` says 2.97 frames where the
    player's own cycle profile says 2.2, and the missing factor is rows per
    note. Where the two disagree, the cycle profile wins -- it measures the
    original alone and owes nothing to what we emitted.

    `spread` is the interquartile range of those ratios. A row of the wrong
    length compresses every gap by the same factor and reads tight; a spread
    one means the pacing is *irregular*, which is a gate whose interval
    alternates (ACE II runs 5 frames then 6) or material dropped often enough
    to move a quartile. It is deliberately not sensitive to a single omission:
    one dropped section leaves eleven gaps at 1.0 and one at 4, the quartiles
    do not move, and the median still correctly says the row length is right.
    """
    g = [x for v in range(3) for x in matched_gaps(orig[v], ours[v])]
    # 6 was far too low. A file the conversion largely misses leaves difflib a
    # handful of matched notes, and a ratio over 7 gaps with an interquartile
    # range spanning a factor of three was reported in bold as "their row is
    # 3.75 frames" -- which is what §7c was built on, and it was noise. The
    # files where this measure is worth anything carry hundreds of gaps
    # (Ricochet 359 at an IQR of zero, Tarzan 418 the same).
    if len(g) < MIN_PACE_GAPS:
        return {"n": len(g)}
    num = sum(a * b for a, b in g)
    den = sum(a * a for a, _ in g)
    ratios = sorted(b / a for a, b in g)
    q1, q3 = ratios[len(ratios) // 4], ratios[3 * len(ratios) // 4]
    median = ratios[len(ratios) // 2]
    # How much of the original the matched notes cover. This guards a real
    # hazard -- a tight IQR over many gaps is still a biased sample if
    # difflib matched a sliver of the tune -- but be clear about what it does
    # NOT do: on this corpus it rejects nothing the count gate did not already
    # reject, and it does not catch the one figure known to be wrong.
    # Spellbound's -m1 ratio passes all three gates (100 gaps, 5.9% IQR, 59%
    # coverage) and is still wrong; a direct count of its pattern data settled
    # that (v0.5.118), and no threshold here would have. Lowering the bar to
    # catch it would reject Warhawk, whose coverage is 58% and whose ratio is
    # right. A confidence gate cannot substitute for a measurement of a
    # different kind.
    total = sum(len(v.attacks) for v in orig)
    out = {"n": len(g), "slope": num / den if den else None,
           "median": median, "q1": q1, "q3": q3, "spread": q3 - q1,
           "coverage": (len(g) + 1) / total if total else 0.0}
    # BOTH refusals below say "this instrument cannot measure this file", and
    # NEITHER says "the conversion is wrong". The distinction is not pedantry:
    # censused at v0.5.411, 14 of the 83 converting files are refused here, and
    # of the six refused for coverage, FIVE convert at 97-100% melody --
    # Saboteur_II, Chain_Reaction, Kings_of_the_Beach_intro and Zoolook all at
    # 100% with every voice at ratio 1.00 and pitches 100% the same, and
    # Bump_Set_Spike at 97%. So a refusal here is overwhelmingly --pace's own
    # note matching failing, not a tune it declines to vouch for, and the old
    # wording ("too little of the tune to time") read as the second.
    if out["coverage"] < MIN_PACE_COVERAGE:
        out["unreliable"] = (f"--pace matched only {out['coverage']:.0%} of "
                             f"the original's notes, below the {MIN_PACE_COVERAGE:.0%} "
                             f"it needs to time anything -- a limit of THIS "
                             f"measurement, not a verdict on the conversion; "
                             f"read melody/--diagnose for that")
    # A wide IQR means the matched notes do not agree with each other about
    # the ratio, so their median is not a row length whatever its value.
    #
    # The bound was calibrated when "the files whose row length is
    # independently confirmed carry 100-400 gaps at an IQR of 0-3%" (above),
    # and the corpus has moved under it: the gate readings of v0.5.248,
    # v0.5.402 and v0.5.410 gave many files an exactly FRACTIONAL row, whose
    # gaps legitimately alternate (8/3 frames is 3,3,2), which spreads the
    # ratio without anything being wrong. Fractional-row files are refused
    # here 11 times in 35 against 3 in 48 for integer rows -- a five-fold
    # risk, though NOT a sufficient cause, since 24 fractional-row files pass
    # this gate. Re-calibrating it is a threshold change and wants the noise
    # floor measured first, so it is named rather than tuned.
    if median and (q3 - q1) / median > MAX_PACE_IQR:
        out["unreliable"] = (f"IQR spans {(q3 - q1) / median:.0%} of the "
                             f"median, over the {MAX_PACE_IQR:.0%} bound -- "
                             f"the matched notes disagree about the ratio, so "
                             f"their median is not a row length; again a limit "
                             f"of this measurement rather than of the tune")
    return out


def _skip_gate_multiplier(sid: Path) -> int | None:
    """recommended_multiplier with the skip counter taken into account."""
    try:
        from h2g.convert import _detect_tables
        from h2g.goatwriter import (find_song_speeds, pack_subtune,
                                    recommended_multiplier)
        s = load_sid(str(sid))
        # Captured BEFORE _detect_tables reassigns `s`, and off the loaded
        # file rather than off `sid`, which is a Path here and not a SidFile.
        start_song = s.start_song
        s, det = _detect_tables(s, lambda m: None)
        sp = find_song_speeds(s, det if det.can_convert else None)
        return recommended_multiplier(sp, pack_subtune(sp, start_song), True)
    except Exception:                                          # noqa: BLE001
        return None


def pace_report(sid: Path, workdir: Path, opts: dict, args,
                multiplier: int = 1) -> str:
    """What `--pace` prints for one file.

    The question it exists for: `melody` is a sequence ratio, and reading one
    as evidence about speed is an inference that has been wrong here before.
    A conversion playing too fast overruns the traced window and scores worse
    than one playing too slow, so `melody` can prefer the wrong call rate --
    it did for 17 files in v0.5.99, which were written up as "a factor of two
    out" when the real error was between 10% and 50%.
    """
    out: list[str] = []
    traced = resolve_subtune(sid, args.subtune)
    try:
        sng = convert(str(sid), log=lambda m: None, **opts)
    except Exception as exc:                                  # noqa: BLE001
        return f"{sid.name}: will not convert -- {type(exc).__name__}: {exc}\n"
    sng, _ = legalise_restarts(sng)
    packed = pack_sid(sng, workdir, args.gt2reloc, multiplier)
    if packed is None:
        return f"{sid.name}: converted, but gt2reloc wrote no .sid\n"
    local = workdir / "o.sid"
    shutil.copyfile(sid, local)
    cal, _ft = table_calibration(sid, opts)
    a = run_siddump(local, args.seconds, traced, args.siddump, cal)

    speeds = find_song_speeds(load_sid(str(sid)))
    # The row the conversion was actually written for, which is not the raw
    # gate when --skip-gate corrected it.
    read = effective_frames(speeds, traced, bool(opts.get("skip_gate")))
    tempo = None
    out.append(f"{sid.name}: subtune {traced}, {args.seconds}s, "
               f"packed -S{multiplier}; speed gate reads "
               f"{read if read is not None else 'nothing'} frame(s) per "
               f"duration unit")

    tempo = (read or 0) * multiplier          # calls per row, as emitted
    rates = sorted({1, multiplier})
    seen = []
    for m in rates:
        b = run_siddump(packed, args.seconds, traced, args.siddump, calls=m)
        got = pace(a, b)
        if got.get("slope") is None:
            out.append(f"  -m{m}: only {got['n']} matched gap(s) -- the two "
                       "sides share too little material to time")
            continue
        # Our row is `tempo` calls, which is tempo/m frames when the play
        # routine runs m times a frame. Dividing that by the slope gives the
        # original's row in frames -- the same number whichever rate it is
        # taken at, which is what makes it worth reporting over a slope.
        ours = tempo / m if tempo else None
        if got.get("unreliable"):
            out.append(f"       ({got['unreliable']})")
            continue
        seen.append((m, got, (ours / got["median"]) if ours else None))
        out.append(
            f"  -m{m}: our row {'' if ours is None else f'{ours:.2f} frames, '}"
            f"ours/theirs {got['median']:.3f}  (IQR {got['q1']:.3f}-"
            f"{got['q3']:.3f} over {got['n']} gaps; least-squares fit "
            f"{got['slope']:.3f})")
        # The cumulative reading of the same two traces. A row that is a
        # fraction of a frame wrong is invisible above -- Goattracker rows are
        # whole play calls, so the error lands as zero on most gaps and one
        # frame on the occasional one, and the median comes out 1.000 exactly.
        dr = drift(a, b)
        if dr.get("unfitted"):
            out.append(f"       drift: {dr['unfitted']}")
        elif dr.get("per_1000") is not None:
            sign = "late" if dr["total"] > 0 else "early"
            out.append(
                f"       drift {dr['per_1000']:+.2f} frames/1000 "
                f"(IQR {dr['q1_per_1000']:+.2f}..{dr['q3_per_1000']:+.2f}) -- "
                f"{abs(dr['total']):.1f} frames {sign} across "
                f"{dr['span']} frames; MAD {dr['mad']:.1f}, "
                f"lag {dr['intercept']:+.1f}")
    if seen:
        trues = [t for _, _, t in seen if t]
        spread = min(g["spread"] for _, g, _ in seen)
        if trues:
            out.append(
                f"  **their row is {sum(trues) / len(trues):.2f} frames**, "
                f"where the gate was read as {read}. "
                + ("Tight ratios: this is the row length, not irregular "
                   "pacing."
                   if spread < 0.12 else
                   "Spread ratios: the pacing is irregular, so the row "
                   "length above is an average over gaps that differ -- an "
                   "alternating gate, or material dropped throughout."))
        at_packed = next((g for m, g, _ in seen if m == multiplier), None)
        if at_packed:
            out.append(f"  at the rate it is packed for, "
                       f"{abs(1 - at_packed['median']):.0%} out")
    return "\n".join(out) + "\n"


# --------------------------------------------------------------------------
# --diagnose: why one file scores low
# --------------------------------------------------------------------------
# A low melody score names no cause. Four different defects present as one
# number -- a whole voice missing, a constant transposition, under-production
# with the pitches exact, and genuinely different music -- and a fifth, which
# turns out to be the commonest of them, is that the two sides are not the same
# piece of music at all because the subtunes do not correspond.
#
# That last one is invisible to every other mode here. `--search-subtunes`
# varies *our* index while holding the original's at its startSong, so it finds
# a counterpart displaced by a dropped subtune and nothing else. It cannot find
# a file whose .sid carries an init wrapper that renumbers the subtune before
# the player sees it, because there the original's own index has moved. Two
# corpus files do exactly that (SUBTUNE_REMAP below) and both sat in the
# report's "plays something else" bucket for as long as it has existed.
#
# The order below is the order the questions have to be asked in: a per-voice
# analysis of two different pieces of music is noise.

# How many subtunes a side may contribute to the matrix. One trace per row and
# per column, one comparison per cell, so it is quadratic in the claim -- and
# the claim is not always honest (Rasputin's header says 18 and 15 of them play
# two notes in forty-five seconds). Never capped silently: the header says what
# was left out.
MATRIX_CAP = 24

_NOTE_STEP = {"C": 0, "D": 2, "E": 4, "F": 5, "G": 7, "A": 9, "B": 11}


def _semitone(name: str) -> int:
    """siddump's note name ('C-4', 'F#3') as an absolute semitone number."""
    return _NOTE_STEP[name[0]] + (1 if name[1] == "#" else 0) + 12 * int(name[2])


def shift_sweep(orig: Voice, ours: Voice, span: int = 24):
    """(best shift, its ratio, the ratio at zero) over +/- `span` semitones.

    The shift is signed the way a reader wants to hear it: *ours* relative to
    the original, so -7 means we play the tune a fifth low. The sweep
    therefore subtracts the candidate from our notes rather than adding it --
    the other convention returns the correction rather than the defect, and
    reports a voice played seven semitones flat as "+7".

    A position-aligned modal delta proves a transposition when its share is
    high but proves nothing when it is low, because the alignment slips
    whenever either side drops notes -- which is the regime every low-scoring
    file is in. Sweeping a constant shift and taking the sequence ratio at each
    does not depend on the alignment surviving: a transposed file peaks sharply
    away from zero, a scrambled one is flat.
    """
    a = [_semitone(n) for n in orig.collapsed]
    b = [_semitone(n) for n in ours.collapsed]
    if not a or not b:
        return 0, 0.0, 0.0
    at_zero = difflib.SequenceMatcher(None, a, b, autojunk=False).ratio()
    best_k, best = 0, at_zero
    for k in range(-span, span + 1):
        if k == 0:
            continue
        r = difflib.SequenceMatcher(None, a, [x - k for x in b],
                                    autojunk=False).ratio()
        if r > best:
            best_k, best = k, r
    return best_k, best, at_zero


def classify_voice(orig: Voice, ours: Voice) -> str:
    """Which defect this voice's share of the score is.

    Ordered most-specific first, because each test is only meaningful once the
    earlier ones have been excluded -- a transposition sweep over a voice we
    never played reports a spurious peak off two or three notes.
    """
    oa, ua = len(orig.attacks), len(ours.attacks)
    if not oa and not ua:
        return "silent in both"
    if not oa:
        return f"invented: we play {ua} attacks where the original plays none"
    if not ua:
        return f"absent: the original plays {oa} attacks, we play none"
    k, best, at_zero = shift_sweep(orig, ours)
    op, up = set(orig.attacks), set(ours.attacks)
    exact = len(op & up) / len(op | up) if (op | up) else 0.0
    # Asked before any defect, because this function is also run at the *right*
    # counterpart -- and a voice that agrees must not be described as one of
    # the four ways of disagreeing.
    if at_zero >= 0.5 and best - at_zero < 0.15:
        return (f"matches: ratio {at_zero:.2f}, "
                f"pitches {exact:.0%} the same")
    # A peak has to beat zero by a real margin *and* be worth something in
    # absolute terms; any two sequences peak somewhere.
    if k and best >= 0.5 and best - at_zero >= 0.15:
        return (f"transposed {k:+d} semitones "
                f"(ratio {at_zero:.2f} at 0, {best:.2f} at {k:+d})")
    if ua < oa * 0.6 and exact >= 0.5:
        return (f"under-produced: {ua} attacks against {oa}, "
                f"pitches {exact:.0%} the same")
    if ua > oa * 1.6 and exact >= 0.5:
        return (f"over-produced: {ua} attacks against {oa}, "
                f"pitches {exact:.0%} the same")
    return (f"different music: no shift beats {at_zero:.2f} "
            f"(best {best:.2f} at {k:+d}), pitches {exact:.0%} the same")


# Files whose .sid init is a wrapper renumbering the subtune before the player
# sees it. Established by reading the init routine, not inferred from the
# matrix -- the matrix is only what made it worth reading. Recorded so the
# diagnosis prints the reason beside the evidence; the converter never consults
# it, because the remap is in the .sid's own glue code and not in the music.
SUBTUNE_REMAP = {
    "Dragons_Lair_Part_II.sid":
        "init $AF00 maps PSID 0 to song 9, 1 to song 7 and 9 to song 8, and "
        "sends 2..8 through a table at $AF88 while copying a 512-byte pattern "
        "bank into $BE00 that a static rip cannot see",
    "Rasputin.sid":
        "init $CFB5 sends PSID 0 and 1 to a different entry ($C000, with "
        "$C54C set to $FF) and maps PSID n>=2 to song n-2",
}


def subtune_matrix(orig: Path, packed: Path, args, cal: int,
                   norig: int, nours: int, multiplier: int = 1):
    """melody[i][j] for the original's subtune i against ours j.

    The whole point is that the diagonal is not the answer. A file whose best
    match per row sits off the diagonal is a numbering question, and until that
    is settled every other number about the file compares two different pieces
    of music.

    `multiplier` belongs to OUR side only, exactly as in `_measure`: the
    original is a 50 Hz VBI tune and the -S factor is a property of what
    gt2reloc packed. Passing it was missed when the matrix was written, so
    every cell of a multispeed file compared the original at speed against our
    conversion at 1/multiplier of it -- Spellbound's diagonal read 57% where
    the report's own row for the same pair reads 93%, and a reader had no way
    to tell that from a genuine mismatch. Same defect as the probe of
    § 7.ggggg, in the tool rather than in a scratch script.
    """
    ni, nj = min(norig, MATRIX_CAP), min(nours, MATRIX_CAP)
    ours = [run_siddump(packed, args.seconds, j, args.siddump,
                        calls=multiplier) for j in range(nj)]
    grid = []
    for i in range(ni):
        a = run_siddump(orig, args.seconds, i, args.siddump, cal)
        grid.append([compare(a, b)["melody"] for b in ours])
    return grid, ni, nj


def diagnose(sid: Path, workdir: Path, opts: dict, args,
             multiplier: int = 1) -> str:
    """What `--diagnose` prints for one file: correspondence, then cause."""
    out: list[str] = []
    hdr = load_sid(str(sid))
    traced = resolve_subtune(sid, args.subtune)
    try:
        sng = convert(str(sid), log=lambda m: None, **opts)
    except Exception as exc:                       # noqa: BLE001
        return f"{sid.name}: will not convert -- {type(exc).__name__}: {exc}\n"
    lengths = song_lengths(sng)
    sng, patched = legalise_restarts(sng)
    packed = pack_sid(sng, workdir, args.gt2reloc, multiplier)
    if packed is None:
        return f"{sid.name}: converted, but gt2reloc wrote no .sid\n"
    local = workdir / "o.sid"
    shutil.copyfile(sid, local)
    cal, _ft = table_calibration(sid, opts)

    on = " ".join(k for k, v in sorted(opts.items()) if v is True)
    out.append(f"{sid.name}: header claims {hdr.subtunes} subtune(s), "
               f"startSong {hdr.start_song} (traced as {traced}); "
               f"our .sng carries {len(lengths)}")
    out.append(f"  {args.seconds}s per trace, gt2reloc -S{multiplier}, "
               f"{patched} restart(s) legalised, calibration {cal or 'none'}")
    out.append(f"  options: {on or '(none)'}")
    remap = SUBTUNE_REMAP.get(sid.name)
    if remap:
        out.append(f"  known subtune remap: {remap}")
    out.append("")

    grid, ni, nj = subtune_matrix(local, packed, args, cal,
                                  hdr.subtunes, len(lengths), multiplier)
    if ni < hdr.subtunes or nj < len(lengths):
        out.append(f"  matrix capped at {MATRIX_CAP} a side: showing {ni} of "
                   f"{hdr.subtunes} original and {nj} of {len(lengths)} ours")
    out.append("  melody %, rows = the original's subtune, columns = ours:")
    out.append("       " + "".join(f"  o{j:<3}" for j in range(nj)))
    for i, row in enumerate(grid):
        mark = "*" if i == traced else " "
        out.append(f"  {mark}s{i:<3}" + "".join(f" {100 * m:4.0f}" for m in row))
    out.append("  (* is the subtune every other number for this file is taken at)")
    out.append("")

    # The correspondence, stated rather than left to be read off the grid.
    best_j = [max(range(nj), key=lambda j: row[j]) for row in grid]
    strong = [(i, j, grid[i][j]) for i, j in enumerate(best_j)
              if grid[i][j] >= 0.5]
    if strong:
        out.append("  matches at 50% or better: "
                   + ", ".join(f"s{i}->o{j} {100 * m:.0f}%" for i, j, m in strong))
    else:
        out.append("  no original subtune matches any of ours at 50% or better")
    off = [(i, j) for i, j, _ in strong if i != j]
    if off:
        out.append("  ** the correspondence is not the identity: "
                   + ", ".join(f"s{i} is our o{j}" for i, j in off))
        # Which of ours the REST of this file's numbers were actually taken
        # against. `_measure` runs a `--search-subtunes` window over our side
        # (default 3, so one either side of the traced index) and records the
        # winner as `matched_subtune`; this line asserted the diagonal and so
        # cried wolf on exactly the files the window already rescues.
        # Action Biker was one: s0<->o1 and s1<->o0 was a real converter
        # defect, and the shipped row for it read melody 100% throughout,
        # because the window had scored s1 against o0. A false alarm about the
        # report is as damaging as a missed one -- the correspondence claim
        # above is about the CONVERTER and stands either way; this sentence is
        # about the MEASUREMENT and has to know what the measurement does.
        search = int(getattr(args, "search_subtunes", 1) or 1)
        half = search // 2
        window = (range(max(0, traced - half), traced + search - half)
                  if search > 1 else [traced])
        counterpart = best_j[traced] if traced < len(best_j) else traced
        if counterpart != traced and counterpart in window:
            out.append(
                f"     Every other number for this .sid is taken at s{traced}"
                f" against o{counterpart}, not o{traced}:"
                f" --search-subtunes {search} finds the counterpart inside its"
                " window, so the row is already comparing the right music."
                " The numbering is still wrong in the .sng.")
        else:
            out.append(
                f"     Every other number for this .sid is taken at s{traced}"
                f" against o{traced}"
                + (f" (--search-subtunes {search} searched o{window[0]}.."
                   f"o{window[-1]} and o{counterpart} is outside it)"
                   if search > 1 and counterpart != traced else "")
                + ", so it compares two different pieces of music until this"
                  " is accounted for.")
    elif strong:
        out.append("  the correspondence is the identity where it is legible")
    out.append("")

    # Per-voice cause, at the traced subtune and again at its real counterpart.
    pairs = [("as measured", traced, traced)]
    if traced < len(best_j) and best_j[traced] != traced:
        pairs.append(("at the best counterpart", traced, best_j[traced]))
    for label, i, j in pairs:
        if i >= ni or j >= nj:
            continue
        # Our side at the rate it was packed for; the original at 50 Hz. Same
        # rule as the matrix above and as `_measure`.
        a = run_siddump(local, args.seconds, i, args.siddump, cal)
        b = run_siddump(packed, args.seconds, j, args.siddump, calls=multiplier)
        out.append(f"  s{i} against o{j} ({label}), melody "
                   f"{100 * compare(a, b)['melody']:.0f}%:")
        for v, (ov, nv) in enumerate(zip(a, b)):
            out.append(f"    voice {v}: {classify_voice(ov, nv)}")
    return "\n".join(out) + "\n"


def main(argv=None) -> int:
    p = argparse.ArgumentParser(prog="fidelity", description=__doc__.splitlines()[0])
    p.add_argument("target", nargs="?", help=".sid file or directory of them")
    p.add_argument("--pair", nargs=2, metavar=("A.sid", "B.sid"),
                   help="compare two existing .sid files, skipping conversion")
    p.add_argument("-o", "--output", help="write a Markdown report here")
    p.add_argument("--json", help="write the raw measurements here")
    p.add_argument("--label", help="provenance note for the report header. "
                                   "Defaults to `git rev-parse --short HEAD` "
                                   "plus `-dirty` if this project's files are "
                                   "modified -- a measurement from a "
                                   "half-applied tree has cost this repo two "
                                   "re-runs and had no way to say so. Pass an "
                                   "empty string to suppress it")
    p.add_argument("--baseline", metavar="OLD.json",
                   help="a previous --json run to A/B this one against. Emits "
                        "a per-file delta table, and states which dimensions "
                        "moved -- or that none of them can see the change, "
                        "which is a result rather than a flat table. Refuses "
                        "if the two runs were traced at different seconds or "
                        "subtunes; a difference in conversion options is "
                        "reported as the change under test, not refused")
    p.add_argument("--ab-output", metavar="PATH",
                   help="write the --baseline comparison here instead of "
                        "stdout (the report still goes to -o)")
    p.add_argument("--presets", default=str(Path(__file__).resolve().parent.parent
                                            / "presets.json"))
    p.add_argument("--length-probe", type=int, default=None, metavar="N",
                   help="when the original is still sounding at the window "
                        "edge, re-ask whether it ends over N x the window "
                        f"(default {LENGTH_PROBE_FACTOR}). Inside its own "
                        "window a tune that stops half a second early looks "
                        "exactly like one that plays on -- Action Biker's "
                        "original ends at 59.54s of a 60s trace -- so the "
                        "`len` column prints `-` for it without this. Pass 1 "
                        "to switch the probe off and pin the window; a file "
                        "whose original outlasts N x the window still reads "
                        "`-`, which is the column declining rather than "
                        "passing it")
    p.add_argument("--census", metavar="PATH",
                   help="classify every onset disagreement by kind "
                        "and write the work list here")
    p.add_argument("--hold-census", metavar="PATH",
                   help="classify every note-length disagreement by kind "
                        "(fetch / slot / sparse / short / long) and write the "
                        "work list here")
    p.add_argument("--vib-census", metavar="PATH",
                   help="split the `vib` ratio by the instrument sounding it "
                        "and classify each shortfall by the effect bit that "
                        "causes the movement, then write the work list here")
    p.add_argument("--gate-census", metavar="PATH",
                   help="classify every release the original makes by what "
                        "we did there (retrigger / matched / short / held) "
                        "and write the work list here")
    p.add_argument("--naming-census", metavar="PATH",
                   help="split each file's melody delta between the shipped "
                        "preset and the same preset plus the forced option "
                        "flag(s) into its naming and non-naming halves, and "
                        "write the work list here. Needs at least one forcing "
                        "flag (--regrid, --slides, ...), since without one "
                        "both arms are the same conversion")
    p.add_argument("-t", "--seconds", type=int, default=DEFAULT_SECONDS)
    p.add_argument("-a", "--subtune", default="auto",
                   help="which subtune of the original to trace: a number, or "
                        "'auto' (the default) for the PSID header's own "
                        "startSong -- the subtune a player picks when the user "
                        "picks none, which is not 0 in seven corpus files")
    p.add_argument("--regrid", action="store_true",
                   help="convert with --regrid (one row in N gets an extra "
                        "play call, and the next gives it back) regardless of "
                        "what the presets say. `fidelity_better` cannot select "
                        "this option, so every adoption is hand-measured and "
                        "this is how it gets measured")
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
    p.add_argument("--ticks", action="store_true",
                   help="the ORIGINAL alone, timed: the frames on which its "
                        "play routine does markedly more work are its "
                        "sequencer steps, so siddump -z gives its row period "
                        "directly. Checks goatwriter.find_song_speeds against "
                        "the player rather than against our conversion, and "
                        "unlike --pace needs no conversion at all. Prints "
                        "text; writes no report")
    p.add_argument("--pace", action="store_true",
                   help="one file, timed instead of scored: our row length "
                        "against the original's at each candidate call rate, "
                        "fitted over difflib-matched notes. `melody` is a "
                        "sequence ratio and cannot answer this -- a "
                        "conversion playing too fast overruns the window and "
                        "scores worse than one playing too slow. Prints "
                        "text; writes no report")
    p.add_argument("--diagnose", action="store_true",
                   help="one file, explained instead of scored: the subtune "
                        "correspondence matrix (the original's subtunes "
                        "against ours -- the question --search-subtunes "
                        "cannot ask, because it varies our index and not the "
                        "original's), then a per-voice cause for the low "
                        "score. Prints text; writes no report")
    p.add_argument("--search-subtunes", type=int, default=3, metavar="N",
                   help="try a window of N of our subtunes centred on the "
                        "traced one and keep the best match; our numbering "
                        "shifts when a subtune is dropped. Default 3, i.e. one "
                        "either side -- enough to find a counterpart displaced "
                        "by a dropped subtune. 1 disables it. KEPT at 3 "
                        "deliberately after f63caa1: a dropped subtune is a "
                        "real, non-defect reason our numbering differs, so "
                        "disabling this would charge those files for a "
                        "displacement they cannot avoid. But note what it "
                        "cannot do -- it finds the best counterpart without "
                        "asking WHY ours moved, so it scores a wrong-order "
                        "conversion exactly as well as a displaced one. The "
                        "guard against that is the report's `scored against a "
                        "subtune of ours` line, which names the files; read it "
                        "as a lead, and see that line's own text")
    p.add_argument("--workdir", default=WORKDIR,
                   help="scratch path, kept short because gt2reloc's filename "
                        "buffer is 60 bytes. Default is a private directory "
                        "per run: the files in it have fixed names, so two "
                        "harnesses sharing one directory silently measure each "
                        "other's files. Name one only to keep the intermediates")
    p.add_argument("--equal-calls", action="store_true",
                   help="trace our conversion at one call per frame over "
                        "`multiplier x seconds` instead of at its own call "
                        "rate over `seconds`. Same music, same number of play "
                        "calls, but sampled as finely as the original -- "
                        "siddump reads the registers once per frame whatever "
                        "the rate, so a multiplier-5 file loses four calls in "
                        "five and its gate edges with them. Note sequences "
                        "are time-independent so melody, sequence and pitch "
                        "survive; every frame-aligned dimension (wave, adsr, "
                        "pul, filt, cut, bend) does not and is dropped")
    p.add_argument("--vice", action="store_true",
                   help="compute the register dimensions (wave, adsr, pul, "
                        "filt, cut) from VICE per-rasterline traces of BOTH "
                        "sides -- 312 samples a frame against siddump's one, "
                        "so a value written and overwritten inside a frame is "
                        "visible. The sequence dimensions still come from "
                        "siddump. Slower: vsid runs at about 1.3x real time "
                        "and each row needs two traces")
    p.add_argument("--sound", action="store_true",
                   help="also render both sides with sidplayfp and score the "
                        "SOUND: aud (timbre) and loud (level). Cached under "
                        "build/audio/ by content, so a re-run of an unchanged "
                        "conversion re-renders nothing. Not --audio, which is "
                        "SIDM2's onset-jitter measure. Read "
                        "docs/SOUND-CALIBRATION.md before trusting either "
                        "column: its calibration currently reports pass: "
                        "false.")
    p.add_argument("--vice-reduce", default="overlap",
                   choices=list(vicetrace.AGREEMENT_MODES),
                   help="per-frame agreement rule for --vice. The two sides "
                        "write at different rasterlines within a frame, so "
                        "the reduction is unavoidable; these are measured "
                        "against an inaudible 0-48 rasterline shift, which "
                        "moves `last` by up to 2.64pp and `overlap` by 0.13. "
                        "`any` saturates. Default overlap")
    p.add_argument("--vice-exe", default=vicetrace.VSID,
                   help="path to vsid.exe (VICE), or set H2G_VSID")
    p.add_argument("--skip-gate", action="store_true",
                   help="convert with --skip-gate: take the counter above the "
                        "speed gate into account when deriving the row, "
                        "wherever the corrected row is a whole number "
                        "(whats-next.md 7b)")
    p.add_argument("--ntsc", action="store_true",
                   help="leave $02A6 at 0 when tracing, which is NTSC and is "
                        "what a bare emulated machine looks like. Three corpus "
                        "players branch on that cell and skip frames to "
                        "compensate for a 60Hz machine, so this measures "
                        "behaviour a PAL C64 never has -- it exists to "
                        "reproduce measurements taken before v0.5.110")
    p.add_argument("--calls-per-frame", type=int, metavar="N",
                   help="playroutine calls per frame when tracing our "
                        "conversion. Defaults to the song's gt2reloc -S "
                        "multiplier, which is the rate its tempo values "
                        "were written for; pass 1 to reproduce a "
                        "pre-v0.5.96 run.")
    p.add_argument("--siddump", default=SIDDUMP)
    p.add_argument("--gt2reloc", default=GT2RELOC)
    p.add_argument("--register", action="store_true",
                   help="also run SIDM2's frame-exact register comparison")
    p.add_argument("--audio", action="store_true",
                   help="also run SIDM2's onset-aligned audio comparison")
    args = p.parse_args(argv)
    if getattr(args, "ntsc", False):
        globals()["PAL_FLAG"] = None

    if not Path(args.siddump).exists():
        print(f"error: siddump not found: {args.siddump}", file=sys.stderr)
        return 1

    if args.label is None:
        args.label = git_label()

    workdir, owned = make_workdir(args.workdir)
    try:
        return _run(p, args, workdir)
    finally:
        if owned:
            shutil.rmtree(workdir, ignore_errors=True)


def _run(p, args, workdir: Path) -> int:
    if args.pair:
        a, b = (Path(x) for x in args.pair)
        sub = resolve_subtune(a, args.subtune)
        row = {"file": f"{a.name} vs {b.name}", "status": "measured",
               "subtune": sub, "seconds": args.seconds,
               "version": __version__, "label": args.label}
        da = run_siddump(a, args.seconds, sub, args.siddump)
        db = run_siddump(b, args.seconds, sub, args.siddump)
        row.update(compare(da, db))
        nframes = args.seconds * 50
        row.update(wave_compare(da, db, nframes=nframes))
        row.update(adsr_compare(da, db, nframes))
        row.update(pulse_compare(da, db, nframes))
        row.update(filter_compare(da.filter, db.filter, nframes))
        if args.register:
            row["register"] = sidm2_register(a, b, args.seconds)
        if args.audio:
            row["audio"] = sidm2_audio(a, b, args.seconds)
        # No conversion happened, so there is no converter output to hash: an
        # A/B of --pair runs can say what moved but not whether the change
        # reached the .sng.
        row["dimensions"] = dimensions_present(row)
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
        if args.ticks:
            # No conversion, no packing, no presets: this reads the original.
            for sid in sids:
                print(ticks_report(sid, args))
            return 0
        if args.pace:
            for sid in sids:
                opts = _preset_opts(doc, sid.name)
                mult = _preset_multiplier(doc, sid.name)
                if getattr(args, "skip_gate", False):
                    opts["skip_gate"] = True
                    # The tempo and the -S factor have to agree: correcting the
                    # row can change the multiplier (Tarzan 2 -> 1), and
                    # presets.json was generated without the option.
                    mult = _skip_gate_multiplier(sid) or mult
                print(pace_report(sid, workdir, opts, args, mult))
            return 0
        if args.diagnose:
            # Deliberately not a row: the output is an argument about one
            # file, and folding it into the report would put a paragraph in a
            # table cell. --baseline, -o and --json are all about the corpus
            # sweep and do not apply.
            for sid in sids:
                opts = _preset_opts(doc, sid.name)
                if args.slides:
                    opts["slides"] = True
                if args.effects:
                    opts["effects"] = True
                if args.fold_transpose:
                    opts["fold_transpose"] = True
                if args.regrid:
                    opts["regrid"] = True
                print(diagnose(sid, workdir, opts, args,
                               _preset_multiplier(doc, sid.name)))
            return 0

        if args.naming_census:
            # Two arms per file, so this cannot ride on the ordinary row
            # sweep the other censuses read: arm A is the shipped preset and
            # arm B is the same preset plus whatever forcing flags were given.
            forced = [k for k in ("regrid", "slides", "effects",
                                  "fold_transpose", "skip_gate")
                      if getattr(args, k, False)]
            if not forced:
                print("--naming-census needs a forcing flag (--regrid, "
                      "--slides, ...); without one both arms are the same "
                      "conversion and every delta is zero", file=sys.stderr)
                return 2
            recs = []
            for sid in sids:
                base = _preset_opts(doc, sid.name)
                forced_opts = dict(base)
                for k in forced:
                    forced_opts[k] = True
                rec = {"file": sid.name}
                try:
                    mult = _preset_multiplier(doc, sid.name)
                    sub = resolve_subtune(sid, args.subtune)
                    cal, _ft = table_calibration(sid, base)
                    local = workdir / "o.sid"
                    shutil.copyfile(sid, local)
                    orig = run_siddump(local, args.seconds, sub,
                                       args.siddump, cal)
                    arms = []
                    for o in (base, forced_opts):
                        blob, _n = legalise_restarts(
                            convert(str(sid), log=lambda m: None, **o))
                        packed = pack_sid(blob, workdir, args.gt2reloc, mult)
                        if packed is None:
                            raise RuntimeError("gt2reloc wrote no .sid")
                        arms.append(run_siddump(packed, args.seconds, sub,
                                                args.siddump, 0, calls=mult))
                    rec.update(naming_split(orig, arms[0], arms[1]))
                except Exception as exc:            # noqa: BLE001
                    rec["error"] = f"{type(exc).__name__}: {exc}"
                recs.append(rec)
            Path(args.naming_census).write_text(
                naming_census_report(recs), encoding="utf-8")
            print(f"wrote {args.naming_census} "
                  f"(forced: {', '.join(forced)})", file=sys.stderr)
            return 0
        rows = []
        for sid in sids:
            opts = _preset_opts(doc, sid.name)
            if args.slides:
                opts["slides"] = True
            if args.effects:
                opts["effects"] = True
            if args.fold_transpose:
                opts["fold_transpose"] = True
            if args.regrid:
                opts["regrid"] = True
            if getattr(args, "skip_gate", False):
                opts["skip_gate"] = True
            # Applied to the packing step, not to the trace: gt2reloc's -S
            # changes the packed bytes so the tune plays at its real rate,
            # but siddump calls the play routine seconds x 50 times whatever
            # the PSID speed field says, so a file needing -S2 still traces
            # at half its real row rate here and its scores understate.
            mult = _preset_multiplier(doc, sid.name)
            if opts.get("skip_gate"):
                # The tempo was written for a different -S factor, and packing
                # at the preset's would play the file at the wrong speed --
                # which is exactly what made --skip-gate look like a
                # regression in v0.5.119.
                mult = _skip_gate_multiplier(sid) or mult
            row = measure(sid, workdir, opts, args, mult)
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
    if args.census:
        Path(args.census).write_text(census_report(rows), encoding="utf-8")
        print(f"wrote {args.census}", file=sys.stderr)
    if getattr(args, "hold_census", None):
        Path(args.hold_census).write_text(hold_census_report(rows),
                                          encoding="utf-8")
        print(f"wrote {args.hold_census}", file=sys.stderr)
    if getattr(args, "gate_census", None):
        Path(args.gate_census).write_text(gate_census_report(rows),
                                          encoding="utf-8")
        print(f"wrote {args.gate_census}", file=sys.stderr)
    if getattr(args, "vib_census", None):
        Path(args.vib_census).write_text(vib_census_report(rows),
                                         encoding="utf-8")
        print(f"wrote {args.vib_census}", file=sys.stderr)

    if args.baseline:
        try:
            base = json.loads(Path(args.baseline).read_text(encoding="utf-8"))
        except OSError as exc:
            print(f"error: cannot read baseline: {exc}", file=sys.stderr)
            return 2
        if isinstance(base, dict):        # tolerate a wrapped form
            base = base.get("rows", [])
        ab, code = compare_runs(base, rows)
        if args.ab_output:
            Path(args.ab_output).write_text(ab, encoding="utf-8")
            print(f"wrote {args.ab_output}", file=sys.stderr)
        else:
            print(ab)
        return code
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
