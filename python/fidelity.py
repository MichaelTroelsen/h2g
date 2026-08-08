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
from dataclasses import dataclass, field
from pathlib import Path

from h2g import __version__
from h2g.convert import convert
from h2g.goatwriter import FORMAT_GTS5, find_song_speeds
from h2g.sidfile import find_freq_table, load_sid

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
                video=_USE_DEFAULT) -> Trace:
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

Stock siddump cannot see it. It calls the play routine `seconds * 50`
    times whatever the PSID speed field says (siddump.c:309/325), so the trace
    is identical with and without -S -- which is why every multiplier-2 song
    was measured at half speed until v0.5.96. `run_siddump(calls=multiplier)`
    against the tools/siddump-rt build closes that; the packed bytes here are
    unchanged either way.

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
        ta = register_timeline(a.wf_events, nframes)
        tb = register_timeline(b.wf_events, nframes)
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


def adsr_compare(orig: list[Voice], ours: list[Voice],
                 nframes: int) -> dict:
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

    Gating is deliberately not consulted. The register holds its value while
    the voice is released, so the envelope of a silent frame is still the
    envelope the next note will open with, and folding the gate in here would
    re-measure the note lengths the attack columns already measure.

    Baseline: v0.5.71 measured this by hand at 54.2% before its sustain-nibble
    and hard-restart fixes and 66.2% after, over the 83 convertible files.
    Both fixes are shipped and in `presets.json`'s `always` block, so this
    column reproducing the post-fix figure is the check that it measures the
    same thing.
    """
    agree = total = 0
    per_voice = []
    for a, b in zip(orig, ours):
        ta = register_timeline(a.adsr_events, nframes)
        tb = register_timeline(b.adsr_events, nframes)
        va = vt = 0
        for x, y in zip(ta, tb):
            if x == 0 and y == 0:
                continue
            vt += 1
            if x == y:
                va += 1
        per_voice.append({"adsr": (va / vt) if vt else None, "frames": vt})
        agree += va
        total += vt
    return {
        "adsr": (agree / total) if total else None,
        "adsr_frames": total,
        "adsr_voices": per_voice,
    }


def _changes(timeline: list[int]) -> int:
    """How many times a register's value moved across a per-frame timeline.

    Counted from the expanded timeline rather than from the event list so it
    means the same thing on both sides: siddump prints a register on the frame
    it is *written*, and a player that rewrites the same value every frame
    would otherwise be scored as sweeping it.
    """
    return sum(1 for i in range(1, len(timeline)) if timeline[i] != timeline[i - 1])


def pulse_compare(orig: list[Voice], ours: list[Voice], nframes: int) -> dict:
    """How often each side moves the duty cycle, per voice and in total.

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
    per_voice = []
    for a, b in zip(orig, ours):
        vo = _changes(register_timeline(a.pulse_events, nframes))
        vu = _changes(register_timeline(b.pulse_events, nframes))
        per_voice.append({"orig_pulse_changes": vo, "our_pulse_changes": vu})
        o_ch += vo
        u_ch += vu
    return {
        "orig_pulse_changes": o_ch,
        "our_pulse_changes": u_ch,
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
    "**note length** -- `$D404`'s gate bit is read as an *edge* (which is what "
    "makes an attack an attack) and never as a duration, so a note held twice "
    "as long with the right waveform scores the same",
    "**tempo and row rate** -- no column here scores how long a row "
    "lasts. `--pace` is the mode that does, and on this corpus it finds "
    "row-length errors of 10-33% that every column below is blind to. "
    "What "
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

DIMENSIONS = (
    Dimension("melody", "melody", _PITCH_REGS, "fraction",
              "the attack-note sequence with consecutive repeats collapsed"),
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
    Dimension("pulse", "pul", ("$D402/$D403",), "count",
              "frames on which the duty cycle moved",
              source="our_pulse_changes"),
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
_PER_SONG_OPTS = ("max_rows", "pack", "prune", "dedup")
_RENAMED_OPTS = {"fmt": "format"}
_NOT_CONVERT_OPTS = ("gt2reloc", "multiplier")


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
    }
    for opt in _convert_options():
        if opt in opts or opt in _PER_SONG_OPTS:
            continue
        key = _RENAMED_OPTS.get(opt, opt)
        opts[opt] = bool(always.get(key))
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
    row["output_sha"] = hashlib.sha1(sng).hexdigest()[:12]

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
    # The original is a 50Hz VBI tune; ours ticks at `multiplier` x 50 because
    # that is the rate its tempo values were written for. Tracing each at its
    # own rate is what puts both on one time axis -- see run_siddump.
    b = run_siddump(packed, args.seconds, sub, args.siddump,
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
                packed, args.seconds, sub, args.siddump, calls=1))["melody"]
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
            cand_dump = run_siddump(packed, args.seconds, st, args.siddump,
                                    calls=getattr(args, "calls_per_frame", None) or multiplier)
            cand = compare(a, cand_dump)
            if cand["melody"] > best:
                best, best_at, row = cand["melody"], st, {**row, **cand}
                best_dump = cand_dump
        row["matched_subtune"] = best_at
    nframes = args.seconds * 50
    row.update(wave_compare(a, best_dump, nframes=nframes))
    row.update(adsr_compare(a, best_dump, nframes))
    row.update(pulse_compare(a, best_dump, nframes))
    row.update(filter_compare(a.filter, best_dump.filter, nframes))
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


def _fmt_sweep(row: dict) -> str:
    """The cutoff-travel ratio, or `-` where the original never moves it.

    A ratio and not a count, because the filter's two questions are different
    shapes: `filt` is one-sided (did we invent a filter, did we drop one) and
    this is comparative (having filtered, did the cutoff go as far).
    """
    v = row.get("cutoff_sweep")
    return "-" if v is None else f"{v:.2f}x"


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
        "| File | orig | ours | retrig | melody | seq | pitch | slides | bend | wave | noise | adsr | pul | filt | cut | status |",
        "|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---|",
    ]
    for r in sorted(rows, key=lambda r: r["file"].lower()):
        if r["status"] not in ("measured", "silent", "window empty"):
            out.append(
                f"| {r['file']} |" + " - |" * 13 + f" {r['status']} |")
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
            f"{_fmt_pct(r.get('wave'))} | {noise} | "
            f"{_fmt_pct(r.get('adsr'))} | {_one_sided(r, 'pulse_changes')} | "
            f"{_one_sided(r, 'filtered_frames')} | {_fmt_sweep(r)} | "
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
        adsred = [r for r in measured if r.get("adsr") is not None]
        if adsred:
            out.append(
                f"- mean ADSR agreement: "
                f"**{_fmt_pct(sum(r['adsr'] for r in adsred) / len(adsred))}**"
                f" ({len(adsred)} file(s))")
        out += _register_summary(measured)
        ratios = [r["retrigger_ratio"] for r in measured if r["retrigger_ratio"]]
        if ratios:
            out.append(f"- median retrigger ratio: **{sorted(ratios)[len(ratios) // 2]:.2f}**")
        slowed = [r for r in measured if r.get("multiplier", 1) > 1]
        if slowed:
            mean_ok = sum(r["melody"] for r in measured if r.get("multiplier", 1) == 1)
            n_ok = n - len(slowed)
            traced = sorted({r.get("traced_calls_per_frame", 1) for r in slowed})
            out.append(
                f"- **{len(slowed)} of these {n} files are played faster than "
                "50Hz and are traced that way.** Their player advances a row "
                "every 2 frames, which Goattracker reaches only by being "
                "called twice a frame, so they are packed with `gt2reloc -S2` "
                "-- a CIA stub at the init address that reprograms timer A to "
                "50.125x2 Hz (greloc.c:140, :1616). Stock siddump cannot see "
                "that: it calls the play routine `seconds x 50` times whatever "
                "the PSID speed field says (siddump.c:309/325), which traced "
                "every one of these files at half speed until v0.5.99. The "
                "`tools/siddump-rt` build takes `-m` and this run passed "
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
        "- Timing is not measured at all. Two files can agree on every note "
        "and play at different speeds; that is what `--audio` and `--register` "
        "are for.",
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
        "late; `pul` counts duty-cycle movement and says nothing about the "
        "width, the direction or the phase of the sweep -- a pulse swept the "
        "wrong way at the right rate scores the same as one swept correctly; "
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
                "traced window (see the report's *What this run compared*). "
                "Judge it by ear or by a dimension this harness does not have "
                "-- `listen.py` is the only check that spans the rest.",
            ]
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
            ]

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
MAX_PACE_IQR = 0.10
# ...and the matched notes must cover enough of the original to be a sample of
# it rather than of whichever fragment happened to survive the conversion.
MIN_PACE_COVERAGE = 0.30


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
    if out["coverage"] < MIN_PACE_COVERAGE:
        out["unreliable"] = (f"only {out['coverage']:.0%} of the original's "
                             f"notes were matched -- too little of the tune "
                             f"to time")
    # A wide IQR means the matched notes do not agree with each other about
    # the ratio, so their median is not a row length whatever its value.
    if median and (q3 - q1) / median > MAX_PACE_IQR:
        out["unreliable"] = (f"IQR spans {(q3 - q1) / median:.0%} of the "
                             f"median -- the matched notes disagree")
    return out


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
    ft = find_freq_table(load_sid(str(sid)))
    cal = calibration(ft.detune) if ft and abs(ft.detune) > 0.2 else 0
    a = run_siddump(local, args.seconds, traced, args.siddump, cal)

    speeds = find_song_speeds(load_sid(str(sid)))
    read = speeds.frames_for(traced) if speeds is not None else None
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
                   norig: int, nours: int):
    """melody[i][j] for the original's subtune i against ours j.

    The whole point is that the diagonal is not the answer. A file whose best
    match per row sits off the diagonal is a numbering question, and until that
    is settled every other number about the file compares two different pieces
    of music.
    """
    ni, nj = min(norig, MATRIX_CAP), min(nours, MATRIX_CAP)
    ours = [run_siddump(packed, args.seconds, j, args.siddump) for j in range(nj)]
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
    ft = find_freq_table(hdr)
    cal = calibration(ft.detune) if ft and abs(ft.detune) > 0.2 else 0

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
                                  hdr.subtunes, len(lengths))
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
        out.append(f"     Every other number for this .sid is taken at s{traced}"
                   f" against o{traced}, so it compares two different pieces of"
                   " music until this is accounted for.")
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
        a = run_siddump(local, args.seconds, i, args.siddump, cal)
        b = run_siddump(packed, args.seconds, j, args.siddump)
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
                        "by a dropped subtune, and measured to move exactly "
                        "the two corpus files that are displaced. 1 disables it")
    p.add_argument("--workdir", default=WORKDIR,
                   help="scratch path, kept short because gt2reloc's filename "
                        "buffer is 60 bytes. Default is a private directory "
                        "per run: the files in it have fixed names, so two "
                        "harnesses sharing one directory silently measure each "
                        "other's files. Name one only to keep the intermediates")
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
                print(pace_report(sid, workdir, opts, args,
                                  _preset_multiplier(doc, sid.name)))
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
                print(diagnose(sid, workdir, opts, args,
                               _preset_multiplier(doc, sid.name)))
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
