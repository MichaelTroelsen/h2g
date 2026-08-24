#!/usr/bin/env python3
"""Build A/B listening pages for the tunes `listen.py` staged.

    python abpage.py                     # one page per tune + an index
    python abpage.py --serve             # ...and host them on 127.0.0.1
    python abpage.py --embed W_A_R       # one self-contained page, WAVs inlined

A page plays **both renders at once and swaps which one is audible**, so the
switch is gapless and position-matched. That is the whole reason for the tool:
two files in a media player cannot be compared that way, and a comparison that
loses its place between clicks is a comparison of two memories.

Two output modes, and the difference matters:

* **Local** (default) references `<name>.original.wav` beside the page, so a
  page is ~25 KB and carries a tune of any length. Open it from
  `build/listen/` -- but `--serve` is the better way, because the envelope
  overlay and the automatic sync read the two WAVs with `fetch()`, which no
  browser allows over `file://`. Audio playback works either way.
* **`--embed`** inlines both renders as data URIs, for publishing somewhere
  the WAVs cannot follow. That costs 4/3 of the audio: at 44.1 kHz mono a
  minute a side is about 14 MB, which is the practical ceiling.

The per-tune numbers come from `FIDELITY.md` and the per-tune prose from the
`LISTENING.md` that `listen.py` wrote, so a page cannot disagree with the
report it is quoting -- and a tune the report does not measure says so rather
than showing an empty rail.
"""
from __future__ import annotations

import argparse
import base64
import cmath
import hashlib
import json
import math
import os
import re
import struct
import sys
import wave
from datetime import datetime
from pathlib import Path

HERE = Path(__file__).resolve().parent
ROOT = HERE.parent
LISTEN = ROOT / "build" / "listen"


def _doc(name: str) -> Path:
    """A generated report, wherever it currently lives.

    The reports moved from the repo root into `docs/`. Both are checked, docs/
    first, so a stale checkout still reads rather than silently returning no
    rows. Falling back is safe: nothing writes both.

    Resolved against the CURRENT value of `ROOT` on every call, never against
    a module-level `DOCS` constant -- the tests redirect this module at a
    temporary directory with `monkeypatch.setattr(A, "ROOT", tmp_path)`, and a
    constant computed at import time ignores that and reads the real report.
    Which is exactly what happened: two tests began asserting against the live
    corpus instead of their own four-line fixture, and passed or failed on
    whatever the last regeneration produced.
    """
    a = ROOT / "docs" / name
    return a if a.exists() else ROOT / name

# The columns worth putting on a listening page, in reading order. `slides`,
# `pul` and the raw attack counts are left out: they are pair-of-counts cells
# that need their own explanation to mean anything.
CHIPS = ("melody", "seq", "retrig", "wave", "gate", "hold", "onset",
         "bend", "vib", "drift")


def fidelity_rows() -> dict[str, dict[str, str]]:
    path = _doc("FIDELITY.md")
    if not path.exists():
        return {}
    rows, header = {}, None
    for line in path.read_text(encoding="utf-8").splitlines():
        if not line.startswith("|"):
            continue
        cells = [c.strip() for c in line.strip().strip("|").split("|")]
        if header is None and cells and cells[0] == "File":
            header = cells
            continue
        if header and cells[0].endswith(".sid"):
            rows.setdefault(cells[0][:-4], dict(zip(header, cells)))
    return rows


def survey_rows() -> dict[str, dict[str, str]]:
    """The per-file row of SURVEY.md's *Converted* table, keyed by stem.

    Same shape as `fidelity_rows`, and for the same reason: the page quotes a
    generated report rather than re-running detection, so it cannot claim a
    player the survey does not.
    """
    path = _doc("SURVEY.md")
    if not path.exists():
        return {}
    rows, header = {}, None
    for line in path.read_text(encoding="utf-8").splitlines():
        if not line.startswith("|"):
            continue
        cells = [c.strip().strip("`") for c in line.strip().strip("|").split("|")]
        if cells and cells[0] == "File":
            header = cells
            continue
        if header and cells[0].endswith(".sid"):
            rows.setdefault(cells[0][:-4], dict(zip(header, cells)))
    return rows


def preset_rows() -> dict[str, dict]:
    """presets.json's per-song entry, keyed by stem, plus the `always` block."""
    path = ROOT / "presets.json"
    if not path.exists():
        return {}
    doc = json.loads(path.read_text(encoding="utf-8"))
    out = {}
    for name, entry in (doc.get("songs") or {}).items():
        if isinstance(entry, dict):
            out[name[:-4] if name.endswith(".sid") else name] = entry
    return out


def fidelity_json_rows() -> dict[str, dict]:
    """Per-file rows of `build/fidelity.json` (a `fidelity.py --json` run),
    keyed by stem the same way `fidelity_rows`/`preset_rows` key FIDELITY.md
    and presets.json.

    The file is a **list** of per-file dicts, not a dict keyed by name -- a
    probe elsewhere in this project's history got exactly this wrong and
    silently iterated zero rows (see CLAUDE.md's note on probes that wrap
    fidelity.py). Guard both shapes rather than assume.

    This is the only reader in the module that reaches per-*voice* data
    (`row["voices"]`, each with `orig_attacks`/`our_attacks` and the set of
    distinct pitches used) -- FIDELITY.md's own table only ever prints the
    sum across all three voices, so anything wanting a per-voice count has
    to come here.
    """
    path = ROOT / "build" / "fidelity.json"
    if not path.exists():
        return {}
    try:
        doc = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}
    if not isinstance(doc, list):
        return {}
    out: dict[str, dict] = {}
    for row in doc:
        if not isinstance(row, dict):
            continue
        name = row.get("file") or ""
        stem = name[:-4] if name.endswith(".sid") else name
        if stem:
            out.setdefault(stem, row)
    return out


def approvals() -> dict[str, dict]:
    """`approved.json` -- the HUMAN listening verdicts, keyed by tune name.

    The only input to these pages that is not derived from a measurement, and
    the only one no tool may write. Every other number here compares what is
    played; this records that a person listened and said yes, which is the one
    thing none of them can establish.

    Empty when the file is absent or unreadable: an unapproved tune and a
    missing file must look the same on the page, because they mean the same
    thing -- nobody has said yes.
    """
    path = ROOT / "approved.json"
    if not path.exists():
        return {}
    try:
        doc = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}
    tunes = doc.get("tunes")
    return tunes if isinstance(tunes, dict) else {}


def conversion_shas() -> dict[str, str]:
    """sha256 of each staged tune's .sng as it converts RIGHT NOW.

    What a listening verdict is actually about. Computed rather than stored:
    the approval records the sha it was given for, and this says what the sha
    is today, so the two can disagree and the page can say so.

    It answers a **second** question too, and that one is asked of every page
    rather than only the approved ones: `audio_provenance` compares this
    against the sha of the `.sng` sitting in `LISTEN` -- the one `listen.py`
    rendered the staged `.h2g.wav` from -- so a page can say that the audio it
    plays predates the converter that is shipping. It is therefore computed
    unconditionally now; it used to be skipped when `approved.json` was empty,
    which would have left every page silent about its own audio.

    Converting the whole staged set costs a few seconds (4.4 s over the 83
    staged tunes, measured at v0.5.373).
    """
    try:
        import fidelity as F
        from h2g.convert import convert
    except Exception:                                          # noqa: BLE001
        return {}
    ppath = ROOT / "presets.json"
    if not ppath.exists():
        return {}
    try:
        doc = json.loads(ppath.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}
    out: dict[str, str] = {}
    for name in (doc.get("songs") or {}):
        stem = name[:-4] if name.endswith(".sid") else name
        if not (LISTEN / ("%s.original.wav" % stem)).exists():
            continue
        for base in (ROOT / "arkiv" / "Hubbard_Rob", ROOT):
            sid = base / name
            if sid.exists():
                break
        else:
            continue
        try:
            blob = convert(str(sid), log=lambda m: None,
                           **F._preset_opts(doc, name))
            out[stem] = hashlib.sha256(blob).hexdigest()
        except Exception:                                      # noqa: BLE001
            continue
    return out


def approval_badge(name: str, appr: dict, version: str,
                   shas: dict | None = None) -> str:
    """The verdict as it appears at the top of a tune's page.

    Three states, and the third is the whole point: approved and STILL VALID,
    approved but the CONVERSION HAS CHANGED SINCE, and not approved. A stale
    approval shown as a current one is the worst of the three, because it is
    the only one that could stop someone re-listening.

    **Staleness keys on the .sng's sha256, never on the version.** Keying on
    the version was the first design and it was wrong within one commit:
    v0.5.370 and v0.5.371 touched only abpage.py, which cannot change a byte of
    audio, and both invalidated ACE_II's approval. That is the repo's own
    passthrough-guard lesson again -- key on the thing that would make the
    verdict lie, not on a proxy that moves more often. An approval with no
    recorded sha falls back to trusting itself rather than crying stale, the
    same backward-compatibility shape `output_sha` uses.
    """
    a = (appr or {}).get(name)
    if not a or not a.get("approved"):
        return ('<div class="approval none"><b>Not approved</b>'
                '<span>No human has signed off on this conversion.</span></div>')
    at, was = a.get("at", ""), str(a.get("version", ""))
    note = md(a.get("note", "")) if a.get("note") else ""
    want, now = a.get("sng_sha256"), (shas or {}).get(name)
    if want and now and want != now:
        return ('<div class="approval stale"><b>Approved &mdash; but the '
                'conversion has changed since</b><span>Signed off %s at %s, '
                'and the <code>.sng</code> no longer matches the one that was '
                'heard. The verdict does not cover what this page plays.%s'
                '</span></div>' % (at, was, (" " + note) if note else ""))
    return ('<div class="approval yes"><b>Human approved</b>'
            '<span>Signed off %s at %s.%s</span></div>'
            % (at, was or version.lstrip("v"), (" " + note) if note else ""))


def staged_sng_sha(name: str) -> str | None:
    """sha256 of the `.sng` the staged `.h2g.wav` was rendered FROM.

    `listen.py` writes `<stem>.h2g.sng` with the very bytes it then packs and
    renders (`listen.py:686-703`: one `convert(...)` call, `write_bytes`, then
    `pack_sid` on the same object), so this file IS the provenance of the
    audio. Nothing has to be recorded anywhere for that to hold, which is why
    the guard keys on it: a manifest can be written by one tool and believed by
    another after the fact, and this cannot.

    None when there is no staged `.sng` -- which is silence, not staleness.
    """
    try:
        return hashlib.sha256((LISTEN / ("%s.h2g.sng" % name)).read_bytes()).hexdigest()
    except OSError:
        return None


def audio_provenance(name: str, shas: dict | None = None) -> tuple[str, str, str]:
    """(state, sha the audio came from, sha the converter gives today).

    `state` is `"current"`, `"behind"` or `"unknown"`.

    **This keys on the conversion, never on `__version__` or a commit id.**
    That is not a stylistic preference: a version-keyed audio guard would cry
    stale on every commit -- the version moves on all of them, and v0.5.370,
    v0.5.371 and v0.5.373 touched only this file, which cannot alter one byte
    of audio. It is the repo's own passthrough-guard lesson (CLAUDE.md: *a skip
    condition must be keyed on the thing that would make the assertion lie,
    never on a proxy that moves more often*), and this session had already made
    that mistake once on the approval badge and undone it.

    `"unknown"` when either side is missing: no staged `.sng` (nothing to
    compare against), or no entry in `shas` (the tune is not in `presets.json`,
    its `.sid` was not found, or converting it raised). Absence of evidence
    prints nothing rather than an accusation -- the same fallback shape
    `approval_badge` and `output_sha` use.

    Note the two questions this and the approval badge ask are **different**,
    and ACE_II is the live case where they part company. The approval records
    the sha `conversion_shas()` gave when the verdict was written, so it can
    match today's conversion exactly -- while the `.h2g.wav` on the page came
    from a `.sng` staged hours earlier, before the change the note says it was
    approved after. "The verdict still holds" and "you are hearing what was
    approved" are not the same claim, and only this one is about the audio.
    """
    was = staged_sng_sha(name)
    now = (shas or {}).get(name)
    if not was or not now:
        return ("unknown", was or "", now or "")
    return ("current" if was == now else "behind", was, now)


def audio_banner(name: str, shas: dict | None = None) -> str:
    """The warning a page carries when its own audio is behind the converter.

    Rendered above the human verdict, because it outranks it: an approval that
    is still valid says nothing about a render made from a different `.sng`.

    Empty for `"current"` and for `"unknown"` alike -- a page that is up to
    date should not carry a badge saying so, and a page that cannot tell must
    not imply it can.
    """
    state, was, now = audio_provenance(name, shas)
    if state != "behind":
        return ""
    return ('<div class="staleaudio"><b>The audio on this page is an older '
            'conversion</b><span>The <code>%s.h2g.wav</code> played here was '
            'rendered from a <code>.sng</code> whose sha256 begins '
            '<code>%s</code>; converting this tune with today\'s code and '
            'presets gives <code>%s</code>. So the H2G side is not what the '
            'converter now produces, and nothing said on this page &mdash; a '
            'listening note, a human approval, an envelope, a spectrogram '
            '&mdash; describes the current conversion. The original '
            '<code>.sid</code> side is unaffected. Re-run <code>listen.py</code> '
            'for this tune before trusting the comparison.</span></div>'
            % (name, was[:12], now[:12]))


def instrmap_rows() -> tuple[dict[str, dict], int]:
    """(`build/instrmap.json` rows keyed by stem, the trace window in seconds).

    `instrmap.py --json` writes it. Empty and 0 when absent -- the file is
    expensive to produce (two emulations a song) and is deliberately NOT a
    per-commit artefact, so a page built without it must render fine rather
    than fail.

    Read from the JSON rather than from `instrmap`'s Markdown index for the
    reason the `--json` flag's help gives: a Markdown-table scraper degrades
    *silently* into reading nothing.
    """
    path = ROOT / "build" / "instrmap.json"
    if not path.exists():
        return {}, 0
    try:
        doc = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}, 0
    if not isinstance(doc, dict):
        return {}, 0
    seconds = doc.get("seconds") or 0
    out: dict[str, dict] = {}
    for row in doc.get("songs") or []:
        if not isinstance(row, dict):
            continue
        name = row.get("file") or ""
        stem = name[:-4] if name.endswith(".sid") else name
        if stem:
            out.setdefault(stem, row)
    return out, (seconds if isinstance(seconds, int) else 0)


# ---- spectrogram: both sides' FFT, precomputed at build time -------------
#
# A per-sample FFT in the browser over two two-minute WAVs cannot draw in
# under a second -- so the heavy pass runs exactly once, here, in Python, and
# the page ships two small fixed-size byte grids (bins x cols) that cost the
# same to paint regardless of how long the tune runs. Log-spaced frequency
# bins, because an octave low down and an octave up high are the same size
# to the ear and should be the same width on screen.
SPEC_COLS = 480          # ~250ms/column over a 120s tune
SPEC_BINS = 64
SPEC_WINDOW = 2048       # power of two; ~46ms per analysis frame at 44.1kHz
SPEC_FMIN = 40.0
SPEC_FMAX = 12000.0
SPEC_FLOOR_DB = -60.0

_TWIDDLE_CACHE: dict[int, list[complex]] = {}
_HANN_CACHE: dict[int, list[float]] = {}


def _twiddles(n: int) -> list[complex]:
    t = _TWIDDLE_CACHE.get(n)
    if t is None:
        t = [cmath.exp(-2j * math.pi * k / n) for k in range(n // 2)]
        _TWIDDLE_CACHE[n] = t
    return t


def _hann(n: int) -> list[float]:
    w = _HANN_CACHE.get(n)
    if w is None:
        w = [0.5 - 0.5 * math.cos(2 * math.pi * i / (n - 1)) for i in range(n)]
        _HANN_CACHE[n] = w
    return w


def _fft(a: list[complex]) -> list[complex]:
    """Iterative radix-2 Cooley-Tukey. `len(a)` must be a power of two.

    Pure stdlib (no numpy is used anywhere else in this project -- see
    CLAUDE.md's "no third-party runtime dependencies"), and called ~1000
    times per page build, so twiddle factors are cached across calls rather
    than recomputed per FFT.
    """
    n = len(a)
    a = a[:]
    j = 0
    for i in range(1, n):
        bit = n >> 1
        while j & bit:
            j ^= bit
            bit >>= 1
        j ^= bit
        if i < j:
            a[i], a[j] = a[j], a[i]
    length = 2
    while length <= n:
        half = length // 2
        tw = _twiddles(length)
        for start in range(0, n, length):
            for k in range(half):
                u = a[start + k]
                v = a[start + k + half] * tw[k]
                a[start + k] = u + v
                a[start + k + half] = u - v
        length <<= 1
    return a


def _read_wav_mono(path: Path) -> tuple[list[float], int] | None:
    """16-bit PCM samples as floats in [-1, 1], averaged to mono if needed.

    Returns None for anything that is not a readable 16-bit WAV -- including
    the truncated placeholder bytes a test fixture writes in place of real
    audio -- so a page build never crashes on bad or missing input.
    """
    try:
        with wave.open(str(path), "rb") as wf:
            n_channels = wf.getnchannels()
            sampwidth = wf.getsampwidth()
            framerate = wf.getframerate()
            raw = wf.readframes(wf.getnframes())
    except (wave.Error, EOFError, OSError):
        return None
    if sampwidth != 2 or framerate <= 0:
        return None
    usable = len(raw) - (len(raw) % 2)
    if usable <= 0:
        return None
    try:
        ints = struct.unpack("<%dh" % (usable // 2), raw[:usable])
    except struct.error:
        return None
    if n_channels <= 1:
        samples = [s / 32768.0 for s in ints]
    else:
        samples = [
            sum(ints[i:i + n_channels]) / n_channels / 32768.0
            for i in range(0, len(ints) - n_channels + 1, n_channels)
        ]
    if not samples:
        return None
    return samples, framerate


def _log_bin_lookup(framerate: int, window: int, fmin: float, fmax: float,
                    bins: int) -> list[int]:
    """For each rFFT bin `0..window//2`, the log-spaced bin (`0..bins-1`) its
    frequency falls in, or -1 outside `[fmin, min(fmax, nyquist))`."""
    hi = min(fmax, framerate / 2)
    if hi <= fmin:
        return [-1] * (window // 2 + 1)
    ratio = hi / fmin
    out = []
    for k in range(window // 2 + 1):
        f = k * framerate / window
        if f < fmin or f >= hi:
            out.append(-1)
            continue
        b = int(math.log(f / fmin) / math.log(ratio) * bins)
        out.append(min(bins - 1, max(0, b)))
    return out


def _spectrogram_grid(samples: list[float], framerate: int, cols: int,
                      bins: int, window: int = SPEC_WINDOW,
                      fmin: float = SPEC_FMIN,
                      fmax: float = SPEC_FMAX) -> list[list[float]] | None:
    """`bins` x `cols` grid of average power, one column per time slice.

    Each column's analysis frame is Hann-windowed and centred on that
    column's nominal position (clipped to stay in bounds); the frame is much
    shorter than a column's time span on a full-length tune, so this is a
    sampled overview rather than a full overlap-add STFT -- the tradeoff that
    keeps the whole build a fixed, small cost instead of one that scales with
    `window`/`hop`.
    """
    n = len(samples)
    if n < window:
        return None
    lookup = _log_bin_lookup(framerate, window, fmin, fmax, bins)
    hann = _hann(window)
    hop = n / cols
    grid = [[0.0] * cols for _ in range(bins)]
    for c in range(cols):
        centre = int((c + 0.5) * hop)
        start = max(0, min(n - window, centre - window // 2))
        frame = samples[start:start + window]
        windowed = [complex(frame[i] * hann[i], 0.0) for i in range(window)]
        spec = _fft(windowed)
        sums = [0.0] * bins
        counts = [0] * bins
        for k, b in enumerate(lookup):
            if b < 0:
                continue
            re_, im_ = spec[k].real, spec[k].imag
            sums[b] += re_ * re_ + im_ * im_
            counts[b] += 1
        col = [sums[b] / counts[b] if counts[b] else 0.0 for b in range(bins)]
        for b in range(bins):
            grid[b][c] = col[b]
    return grid


def _grids_to_bytes(grid_a: list[list[float]],
                    grid_b: list[list[float]]) -> tuple[bytes, bytes]:
    """Both grids to 0-255 dB-scaled bytes against ONE shared peak, so a
    quieter render draws visibly dimmer rather than being re-normalised up to
    match -- the loudness difference is part of what this overlay shows."""
    peak = 1e-12
    for g in (grid_a, grid_b):
        for row in g:
            m = max(row) if row else 0.0
            if m > peak:
                peak = m

    def to_bytes(g: list[list[float]]) -> bytes:
        out = bytearray()
        for row in g:
            for v in row:
                db = SPEC_FLOOR_DB if v <= 0 else max(
                    SPEC_FLOOR_DB, 10.0 * math.log10(v / peak))
                level = (db - SPEC_FLOOR_DB) / -SPEC_FLOOR_DB
                out.append(int(round(level * 255)))
        return bytes(out)

    return to_bytes(grid_a), to_bytes(grid_b)


def spectrogram_payload(name: str) -> dict | None:
    """Both sides' log-frequency magnitude grid, base64-encoded, or None if
    either WAV is missing or unreadable."""
    a = _read_wav_mono(LISTEN / ("%s.original.wav" % name))
    b = _read_wav_mono(LISTEN / ("%s.h2g.wav" % name))
    if a is None or b is None:
        return None
    grid_a = _spectrogram_grid(a[0], a[1], SPEC_COLS, SPEC_BINS)
    grid_b = _spectrogram_grid(b[0], b[1], SPEC_COLS, SPEC_BINS)
    if grid_a is None or grid_b is None:
        return None
    bytes_a, bytes_b = _grids_to_bytes(grid_a, grid_b)
    return {
        "cols": SPEC_COLS, "bins": SPEC_BINS,
        "fmin": SPEC_FMIN, "fmax": SPEC_FMAX,
        "a": base64.b64encode(bytes_a).decode("ascii"),
        "b": base64.b64encode(bytes_b).decode("ascii"),
    }


def spectrogram_card(spec: dict | None) -> str:
    """The frequency-overlay card, or "" when no spectrogram was built."""
    if not spec:
        return ""
    return (
        '<div class="card wave">\n  <h2>Both sides, by frequency</h2>\n'
        '  <canvas id="spectro"></canvas>\n'
        '  <div class="legend">\n'
        '    <span class="swatch orig"><i></i>original</span>\n'
        '    <span class="swatch ours"><i></i>H2G</span>\n'
        '    <span>brighter = louder at that frequency &middot; click to seek both</span>\n'
        '  </div>\n'
        '  <p class="caveat">Precomputed once at build time (log-spaced '
        '%d&ndash;%d&nbsp;Hz, %d time slices), so drawing it costs the same '
        'however long the tune runs. Colour is the two renders overlaid, not '
        'a difference &mdash; a wrong-pitch note shows as a bar lining up on '
        'one colour and not the other, and a quieter render draws visibly '
        'dimmer rather than being normalised up to match.</p>\n</div>\n'
        % (spec["fmin"], spec["fmax"], spec["cols"]))


# Which survey columns are worth a reader's attention, and what to call them.
SURVEY_FIELDS = (("Player", "player"), ("Ver", "engine ver"),
                 ("SIDId", "SIDId"), ("Source", "format"),
                 ("Subtunes", "subtunes"), ("Instr", "instruments"),
                 ("Patterns", "patterns"), ("Dangling", "dangling refs"),
                 (".sng bytes", ".sng bytes"), ("gt2reloc", "packs back"))

# Options that change what is HEARD, worth naming on a listening page. The
# structural always-on flags are left out: they are true of every tune here
# and a list that is the same on 83 pages tells a reader nothing.
NOTABLE = ("two_stage", "voice_two_stage", "wave_program", "sfx_drum",
           "pitch_seq", "no_test_restart", "wide_hard_restart",
           "max_hard_restart", "rest_wave_silence", "initial_instrument",
           "engine")


def listening_notes() -> dict[str, list[str]]:
    """The `- **bold** rest` bullets `listen.py` wrote, per tune."""
    path = LISTEN / "LISTENING.md"
    if not path.exists():
        return {}
    notes: dict[str, list[str]] = {}
    name = None
    for line in path.read_text(encoding="utf-8").splitlines():
        head = re.match(r"^## (.+?)(?: —.*)?$", line)
        if head:
            name = head.group(1).strip()
            if name.lower().startswith("what to write"):
                name = None
            elif name:
                notes[name] = []
            continue
        if name and line.startswith("- "):
            notes[name].append(line[2:].strip())
        elif name and line.startswith("Packed at"):
            notes[name].append(line.strip())
    return notes


def md(text: str) -> str:
    """The little Markdown listen.py emits: **bold**, `code`, *em*."""
    text = (text.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;"))
    text = re.sub(r"\*\*(.+?)\*\*", r"<strong>\1</strong>", text)
    text = re.sub(r"`(.+?)`", r"<code>\1</code>", text)
    text = re.sub(r"(?<!\*)\*([^*]+?)\*(?!\*)", r"<em>\1</em>", text)
    return text.replace("--", "&mdash;")


CSS = """
:root {
  --ground:#EEF1F4; --panel:#FFFFFF; --sunk:#E4E9ED;
  --ink:#0F171D; --muted:#5D6B77; --line:#D6DDE3;
  --a:#A8471C; --b:#17697F; --live:#2F7D52;
  --mono: ui-monospace, "Cascadia Mono", "SF Mono", Consolas, monospace;
  --sans: ui-sans-serif, -apple-system, "Segoe UI", Roboto, sans-serif;
}
@media (prefers-color-scheme: dark) {
  :root:not([data-theme="light"]) {
    --ground:#0E1418; --panel:#161E24; --sunk:#111A20;
    --ink:#E6EDF2; --muted:#8A9AA6; --line:#253039;
    --a:#E08A5C; --b:#5FBBD4; --live:#63C48D;
  }
}
:root[data-theme="dark"] {
  --ground:#0E1418; --panel:#161E24; --sunk:#111A20;
  --ink:#E6EDF2; --muted:#8A9AA6; --line:#253039;
  --a:#E08A5C; --b:#5FBBD4; --live:#63C48D;
}
* { box-sizing:border-box; }
body {
  margin:0; background:var(--ground); color:var(--ink);
  font-family:var(--sans); line-height:1.55;
  padding:clamp(16px,4vw,44px) clamp(14px,4vw,32px);
}
.wrap { max-width:62rem; margin:0 auto; display:flex; flex-direction:column; gap:22px; }
header { display:flex; flex-direction:column; gap:10px; }
.eyebrow { font-family:var(--mono); font-size:11.5px; letter-spacing:.13em;
  text-transform:uppercase; color:var(--muted); }
.eyebrow a { color:var(--muted); }
h1 { margin:0; font-size:clamp(28px,5vw,44px); letter-spacing:-.02em; text-wrap:balance; }
h1 small { display:block; font-size:15px; font-weight:400; color:var(--muted);
  letter-spacing:0; margin-top:6px; }
.rail { display:flex; flex-wrap:wrap; gap:7px; }
.chip { font-family:var(--mono); font-size:12px; padding:5px 9px;
  border:1px solid var(--line); border-radius:3px; background:var(--panel);
  display:flex; gap:7px; align-items:baseline; }
.chip b { font-weight:600; font-variant-numeric:tabular-nums; }
.chip span { color:var(--muted); }
.rig { background:var(--panel); border:1px solid var(--line); border-radius:5px;
  padding:clamp(16px,3vw,26px); display:flex; flex-direction:column; gap:20px; }
.sources { display:grid; grid-template-columns:1fr 1fr; gap:12px; }
.src { appearance:none; cursor:pointer; text-align:left; font-family:var(--mono);
  background:var(--sunk); color:var(--ink); border:1.5px solid var(--line);
  border-radius:4px; padding:14px 16px; display:flex; flex-direction:column; gap:3px;
  transition:border-color .12s, background .12s; }
.src:hover { border-color:var(--muted); }
.src:focus-visible { outline:2px solid var(--ink); outline-offset:2px; }
.src .key { font-size:11px; letter-spacing:.12em; color:var(--muted); text-transform:uppercase; }
.src .name { font-size:17px; font-weight:600; }
/* When this WAV was rendered. A stale pair is indistinguishable from a fresh
   one by ear until something sounds wrong, and then the first suspicion falls
   on the converter rather than on the file's age -- which has already cost
   this project one wrong diagnosis. Kept quiet: it is provenance, not a
   control. */
.src .rendered { font-family:var(--mono); font-size:10.5px; color:var(--muted);
  letter-spacing:.04em; opacity:.8; }
.blind .src .rendered { visibility:hidden; }
.src[data-side="a"][aria-pressed="true"] { border-color:var(--a);
  background:color-mix(in srgb, var(--a) 11%, var(--panel)); }
.src[data-side="b"][aria-pressed="true"] { border-color:var(--b);
  background:color-mix(in srgb, var(--b) 11%, var(--panel)); }
.src[data-side="a"][aria-pressed="true"] .name { color:var(--a); }
.src[data-side="b"][aria-pressed="true"] .name { color:var(--b); }
.blind .src .name { color:var(--ink) !important; }
.transport { display:flex; align-items:center; gap:14px; flex-wrap:wrap; }
.play { appearance:none; cursor:pointer; width:52px; height:52px; flex:none;
  border-radius:50%; border:1.5px solid var(--ink); background:transparent;
  color:var(--ink); font-size:17px; display:grid; place-items:center; }
.play:focus-visible { outline:2px solid var(--ink); outline-offset:3px; }
.scrub { flex:1 1 240px; display:flex; flex-direction:column; gap:6px; }
input[type="range"] { width:100%; accent-color:var(--ink); }
.time { font-family:var(--mono); font-size:12px; color:var(--muted);
  font-variant-numeric:tabular-nums; display:flex; justify-content:space-between; }
.loop { display:flex; gap:14px; align-items:center; flex-wrap:wrap;
  font-family:var(--mono); font-size:12.5px; color:var(--muted); }
.mode { display:flex; gap:14px; align-items:center; flex-wrap:wrap;
  border-top:1px solid var(--line); padding-top:16px; }
.toggle { display:flex; align-items:center; gap:8px; font-family:var(--mono);
  font-size:12.5px; cursor:pointer; color:var(--ink); }
.ghost { appearance:none; cursor:pointer; font-family:var(--mono); font-size:12.5px;
  background:transparent; color:var(--ink); border:1px solid var(--line);
  border-radius:3px; padding:6px 11px; }
.ghost:hover { border-color:var(--muted); }
.ghost:focus-visible { outline:2px solid var(--ink); outline-offset:2px; }
.tally { font-family:var(--mono); font-size:12.5px; color:var(--muted);
  margin-left:auto; font-variant-numeric:tabular-nums; }
.verdict { font-family:var(--mono); font-size:12.5px; min-height:1.2em; }
.verdict.right { color:var(--live); }
.verdict.wrong { color:var(--a); }
.card { background:var(--panel); border:1px solid var(--line); border-radius:5px;
  padding:18px 20px; }
.card h2 { margin:0 0 12px; font-size:12px; font-family:var(--mono); letter-spacing:.13em;
  text-transform:uppercase; color:var(--muted); font-weight:600; }
.card ul { margin:0; padding-left:1.1em; display:flex; flex-direction:column;
  gap:9px; font-size:14.5px; }
footer { color:var(--muted); font-size:12.5px; font-family:var(--mono);
  display:flex; flex-direction:column; gap:8px; }
footer a { color:var(--ink); }
kbd { font-family:var(--mono); font-size:11.5px; border:1px solid var(--line);
  border-bottom-width:2px; border-radius:3px; padding:1px 5px; }
table { width:100%; border-collapse:collapse; font-family:var(--mono); font-size:13px; }
th, td { text-align:left; padding:8px 10px; border-bottom:1px solid var(--line);
  font-variant-numeric:tabular-nums; }
th { color:var(--muted); font-weight:600; font-size:11.5px; letter-spacing:.1em;
  text-transform:uppercase; }
td a { color:var(--ink); font-weight:600; }
.scroll { overflow-x:auto; }
.sync { display:flex; gap:12px; align-items:center; flex-wrap:wrap;
  border-top:1px solid var(--line); padding-top:16px;
  font-family:var(--mono); font-size:12.5px; color:var(--muted); }
.sync input[type="range"] { flex:1 1 220px; }
.sync b { color:var(--ink); font-variant-numeric:tabular-nums; min-width:5.5em;
  display:inline-block; text-align:right; }
.sync .ghost { font-family:var(--mono); font-size:12px; }
/* The human verdict. Deliberately quiet rather than a green tick: it says who
   said yes and at which version, because an approval that outlives the
   conversion it was given for is worse than none. */
.approval { display:flex; flex-direction:column; gap:3px; padding:10px 14px;
  border-radius:6px; border:1px solid var(--line); margin:0 0 14px;
  font-size:12.5px; }
.approval b { font-size:13px; letter-spacing:.02em; }
.approval span { color:var(--muted); }
.approval.yes { border-color:color-mix(in srgb, var(--b) 55%, var(--line));
  background:color-mix(in srgb, var(--b) 9%, transparent); }
.approval.yes b { color:var(--b); }
.approval.stale { border-color:color-mix(in srgb, var(--a) 55%, var(--line));
  background:color-mix(in srgb, var(--a) 9%, transparent); }
.approval.stale b { color:var(--a); }
.approval.none b { color:var(--muted); font-weight:600; }
/* The audio's own provenance. Louder than the approval above it on purpose:
   an approval that no longer holds still describes this tune, where audio
   rendered from a different .sng means every picture and every number on the
   page is about something the converter no longer emits. */
.staleaudio { display:flex; flex-direction:column; gap:3px; padding:10px 14px;
  border-radius:6px; margin:0 0 14px; font-size:12.5px;
  border:1px solid var(--a);
  background:color-mix(in srgb, var(--a) 14%, transparent); }
.staleaudio b { font-size:13px; letter-spacing:.02em; color:var(--a); }
.staleaudio span { color:var(--muted); }
.staleaudio code { font-family:var(--mono); font-size:11.5px; }
td.aud .old { color:var(--a); font-weight:600; }
td.aud .cur { color:var(--muted); }
td.appr { white-space:nowrap; }
td.appr .y { color:var(--b); font-weight:600; }
td.appr .s { color:var(--a); font-weight:600; }
td.appr .n { color:var(--muted); }
.trk { display:grid; grid-template-columns:repeat(3,1fr); gap:10px; }
.trkcol { border:1px solid var(--line); border-radius:6px; overflow:hidden;
  background:var(--sunk); }
.trkcol h3 { margin:0; padding:6px 10px; font-family:var(--mono); font-size:12px;
  letter-spacing:.06em; background:var(--panel);
  border-bottom:1px solid var(--line); }
.trkbody { height:680px; overflow:hidden; position:relative;
  font-family:var(--mono); font-size:12.5px; line-height:1.45; }
.trkhead { display:flex; gap:8px; padding:4px 10px; white-space:pre;
  font-size:11px; letter-spacing:.06em; color:var(--muted); opacity:.75;
  border-bottom:1px solid var(--line); }
.trkrow { display:flex; gap:8px; padding:0 10px; white-space:pre;
  color:var(--muted); cursor:pointer; }
.trkrow:hover { background:color-mix(in srgb, var(--ink) 6%, transparent); }
.trkhead .ix, .trkrow .ix { display:inline-block; width:2.6em; }
.trkhead .n, .trkrow .n { display:inline-block; width:3em; }
.trkhead .instr, .trkrow .instr { display:inline-block; width:3.2em; }
.trkhead .cmd, .trkrow .cmd { display:inline-block; width:3.2em; }
.trkrow .n { color:var(--ink); }
.trkrow.note { color:var(--ink); }
.trkrow.cur { background:color-mix(in srgb, var(--live) 22%, transparent); }
.trkrow .ix { color:var(--muted); opacity:.65; }
.trkrow .instr { color:var(--b); font-weight:600; }
.trknote { margin:12px 0 0; font-size:.86rem; color:var(--muted); }
.vstrip { display:grid; gap:14px;
  grid-template-columns:repeat(auto-fit,minmax(280px,1fr)); }
.vstripcol { border:1px solid var(--line); border-radius:6px;
  padding:10px 12px; background:var(--sunk); }
.vstripcol h3 { margin:0 0 8px; font-size:12px; font-family:var(--mono);
  letter-spacing:.08em; text-transform:uppercase; color:var(--muted); }
.strow { display:flex; align-items:center; gap:8px; margin:5px 0; }
.strow .slab { font-family:var(--mono); font-size:11px; width:52px; flex:none;
  color:var(--muted); }
.strow .slab.o { color:var(--a); }
.strow .slab.u { color:var(--b); }
.strow .scount { font-family:var(--mono); font-size:11.5px; width:2.6em;
  flex:none; text-align:right; color:var(--ink); font-variant-numeric:tabular-nums; }
.strip { flex:1; display:flex; align-items:center; gap:1px;
  overflow-x:auto; white-space:nowrap; padding:3px 0; }
.nt { display:inline-block; width:3px; height:14px; border-radius:1px;
  flex:none; }
.nt.o { background:var(--a); }
.nt.u { background:var(--b); }
.stpitch { margin:8px 0 0; font-size:11.5px; color:var(--muted);
  line-height:1.5; }
.stpitch .k { display:block; font-family:var(--mono); font-size:10.5px;
  letter-spacing:.08em; text-transform:uppercase; color:var(--muted);
  margin-bottom:2px; }
.panel { display:grid; gap:14px;
  grid-template-columns:repeat(auto-fit,minmax(260px,1fr)); }
.vcol { border:1px solid var(--line); border-radius:6px; overflow:hidden; }
.vcol h3 { margin:0; padding:8px 12px; font-size:13px; font-family:var(--mono);
  letter-spacing:.08em; text-transform:uppercase; background:var(--sunk);
  border-bottom:1px solid var(--line); display:flex; gap:10px; }
.vcol h3 .hz { margin-left:auto; color:var(--muted); font-weight:400; }
.vrow { display:flex; align-items:center; gap:8px; padding:3px 12px;
  font-size:13px; color:var(--muted); }
.vrow.on { color:var(--ink); }
.vrow .lab { flex:1; }
.vrow .m { width:13px; height:13px; border-radius:3px; flex:none;
  border:1px solid var(--line); }
.vrow .m.o { background:transparent; }
.vrow.uo .m.o { background:var(--a); border-color:var(--a); }
.vrow.ub .m.b { background:var(--b); border-color:var(--b); }
.vrow .live { width:8px; height:8px; border-radius:50%; flex:none;
  background:transparent; }
.vrow.now .live { background:var(--live); }
.vrow .val { font-family:var(--mono); font-size:11.5px; min-width:4.5em;
  text-align:right; color:var(--muted); }
.panelkey { display:flex; gap:16px; flex-wrap:wrap; margin:12px 0 0;
  font-size:.82rem; color:var(--muted); align-items:center; }
.panelkey i { width:11px; height:11px; border-radius:3px; display:inline-block;
  vertical-align:-1px; margin-right:5px; }
.panelkey .oi { background:var(--a); }
.panelkey .bi { background:var(--b); }
.panelkey .li { background:var(--live); border-radius:50%; }
.facts { display:grid; gap:10px 22px;
  grid-template-columns:repeat(auto-fit,minmax(150px,1fr)); }
.facts div { display:flex; flex-direction:column; gap:2px; }
.facts dt, .facts .k { font-family:var(--mono); font-size:11px;
  letter-spacing:.1em; text-transform:uppercase; color:var(--muted); }
.facts .v { font-size:15px; font-variant-numeric:tabular-nums; }
.opts { margin-top:14px; font-size:.88rem; color:var(--muted); }
.opts code { font-family:var(--mono); font-size:.85rem; }
.voices { display:flex; gap:8px; align-items:center; flex-wrap:wrap;
  border-top:1px solid var(--line); padding-top:16px; }
.voices .lbl { font-family:var(--mono); font-size:12px; color:var(--muted);
  letter-spacing:.1em; text-transform:uppercase; }
.voices button {
  appearance:none; cursor:pointer; font-family:var(--mono); font-size:13px;
  padding:6px 12px; border-radius:4px; border:1.5px solid var(--line);
  background:var(--sunk); color:var(--ink); }
.voices button[aria-pressed="true"] { border-color:var(--ink); font-weight:600; }
.voices .note { font-family:var(--mono); font-size:12px; color:var(--muted); }
.wave { position:relative; }
.wave canvas {
  display:block; width:100%; height:auto; border-radius:10px;
  background:var(--sunk); border:1px solid var(--line); cursor:crosshair;
}
.wave .legend {
  display:flex; flex-wrap:wrap; gap:14px; align-items:center;
  margin:10px 0 0; font-size:.82rem; color:var(--muted);
}
.voicewave .vwrap { display:flex; flex-direction:column; gap:10px; }
.voicewave .vw { border:1px solid var(--line); border-radius:6px;
  background:var(--sunk); overflow:hidden; }
.voicewave .vwhead { display:flex; justify-content:space-between;
  align-items:baseline; padding:5px 10px; font-family:var(--mono);
  font-size:11.5px; color:var(--muted); border-bottom:1px solid var(--line); }
.voicewave .vwhead b { color:var(--ink); letter-spacing:.06em; }
/* 84 of bands + 22 of |difference| strip, matching the canvas set in JS. */
.voicewave canvas { display:block; width:100%; height:106px; cursor:pointer; }
.voicewave button.vwtoggle { appearance:none; background:none; border:0;
  padding:0; font:inherit; color:inherit; cursor:pointer; display:inline-flex;
  align-items:center; gap:7px; }
.voicewave button.vwtoggle:focus-visible { outline:2px solid var(--ink);
  outline-offset:3px; border-radius:3px; }
/* A caret that turns, so the collapsed state reads as collapsed rather than
   as a voice that failed to render. */
.voicewave .cx { width:0; height:0; border-left:5px solid currentColor;
  border-top:4px solid transparent; border-bottom:4px solid transparent;
  transform:rotate(90deg); transition:transform .12s; opacity:.65; }
.voicewave button.vwtoggle[aria-pressed="false"] .cx { transform:rotate(0deg); }
.voicewave button.vwtoggle[aria-pressed="false"] b { color:var(--muted); }
.voicewave .vw.off canvas { display:none; }
.voicewave .vw.off { background:transparent; }
.wave .swatch { display:inline-flex; align-items:center; gap:6px; }
/* The two bands sit on top of each other at 62% alpha, so where they agree
   they are one colour and neither is readable on its own. Hiding a key is
   how you read the other -- and hiding BOTH but the difference strip is how
   you see where they part company with nothing else on the canvas. */
button.swatch { appearance:none; background:none; border:0; padding:0;
  font:inherit; color:inherit; cursor:pointer; }
button.swatch:focus-visible { outline:2px solid var(--ink); outline-offset:3px;
  border-radius:3px; }
button.swatch[aria-pressed="false"] { opacity:.42; }
button.swatch[aria-pressed="false"] i { background:transparent !important;
  box-shadow:inset 0 0 0 1.5px var(--muted); }
button.swatch[aria-pressed="false"] { text-decoration:line-through; }
.wave .swatch i { width:11px; height:11px; border-radius:3px; display:inline-block; }
.wave .swatch.orig i { background:var(--a); }
.wave .swatch.ours i { background:var(--b); }
.wave .swatch.diff i { background:var(--ink); opacity:.45; }
.wave .stat { margin-left:auto; font-family:var(--mono); color:var(--ink); }
.wave .caveat { margin:12px 0 0; font-size:.86rem; color:var(--muted); }
.wave .msg {
  padding:26px 16px; text-align:center; color:var(--muted); font-size:.9rem;
  border:1px dashed var(--line); border-radius:10px; background:var(--sunk);
}
@media (prefers-reduced-motion:reduce) { * { transition:none !important; } }
@media (max-width:520px) { .sources { grid-template-columns:1fr; } }
"""

SCRIPT = r"""
(function () {
  var au = document.getElementById("au"), bu = document.getElementById("bu");
  var play = document.getElementById("play"), seek = document.getElementById("seek");
  var now = document.getElementById("now"), dur = document.getElementById("dur");
  var blind = document.getElementById("blind"), rig = document.getElementById("rig");
  var looping = document.getElementById("looping");
  var gA = document.getElementById("guessA"), gB = document.getElementById("guessB");
  var verdict = document.getElementById("verdict"), tally = document.getElementById("tally");
  var nameA = document.getElementById("nameA"), nameB = document.getElementById("nameB");
  var srcs = Array.prototype.slice.call(document.querySelectorAll(".src"));
  var syncr = document.getElementById("syncr"), syncv = document.getElementById("syncv");
  var syncauto = document.getElementById("syncauto"), synczero = document.getElementById("synczero");
  var syncwhy = document.getElementById("syncwhy");
  var side = "a", swapped = false, right = 0, total = 0;

  // Seconds to ADD to A's position to get B's. The two renders do not start
  // together: gt2reloc's packed player reaches its first note some 3-8 frames
  // after the original (FIDELITY.md calls it startup_lag, median 6 frames),
  // which is 60-160 ms -- comfortably audible as a flam when the sources are
  // swapped, and the whole point of this rig is that switching does not lose
  // your place. Positive means B's content is late and B must be run ahead.
  var sync = 0, autoSync = null;
  function bAt(t) {
    var d = bu.duration;
    var v = t + sync;
    if (v < 0) v = 0;
    if (d && isFinite(d) && v > d) v = d;
    return v;
  }
  function setSync(ms, why) {
    sync = ms / 1000;
    syncr.value = String(Math.round(ms));
    syncv.textContent = (ms > 0 ? "+" : "") + Math.round(ms) + " ms";
    if (why) syncwhy.innerHTML = why;
    if (!au.paused || au.currentTime) bu.currentTime = bAt(au.currentTime);
    if (window.__abRedraw) window.__abRedraw();
    if (window.__abSpectroRedraw) window.__abSpectroRedraw();
    if (window.__abVoiceRedraw) window.__abVoiceRedraw();
  }
  syncr.addEventListener("input", function () {
    setSync(Number(syncr.value), "&mdash; set by hand");
  });
  synczero.addEventListener("click", function () {
    setSync(0, "&mdash; no offset: the two renders as staged");
  });
  syncauto.addEventListener("click", function () {
    if (autoSync === null) {
      syncwhy.innerHTML = "&mdash; auto needs the envelopes, which need http (see below)";
      return;
    }
    setSync(autoSync, "&mdash; auto: our render's first note is "
            + Math.round(autoSync) + " ms (" + (autoSync / 20).toFixed(1)
            + " frames) later than the original's");
  });

  au.volume = 1; bu.volume = 0;

  function apply() {
    var leftEl = swapped ? bu : au, rightEl = swapped ? au : bu;
    leftEl.volume = side === "a" ? 1 : 0;
    rightEl.volume = side === "b" ? 1 : 0;
    srcs.forEach(function (b) {
      b.setAttribute("aria-pressed", String(b.dataset.side === side));
    });
  }
  function pick(s) { side = s; apply(); }
  srcs.forEach(function (b) {
    b.addEventListener("click", function () { pick(b.dataset.side); });
  });

  function fmt(t) {
    if (!isFinite(t)) return "0:00";
    var m = Math.floor(t / 60), s = Math.floor(t % 60);
    return m + ":" + (s < 10 ? "0" : "") + s;
  }
  function toggle() {
    if (au.paused) {
      bu.currentTime = bAt(au.currentTime);
      au.play(); bu.play();
      play.innerHTML = "&#10074;&#10074;"; play.setAttribute("aria-label", "Pause");
    } else {
      au.pause(); bu.pause();
      play.innerHTML = "&#9654;"; play.setAttribute("aria-label", "Play");
    }
  }
  play.addEventListener("click", toggle);
  looping.addEventListener("change", function () {
    au.loop = looping.checked; bu.loop = looping.checked;
  });

  au.addEventListener("loadedmetadata", function () { dur.textContent = fmt(au.duration); });
  au.addEventListener("timeupdate", function () {
    now.textContent = fmt(au.currentTime);
    if (au.duration) seek.value = String(Math.round(au.currentTime / au.duration * 1000));
    if (Math.abs(bu.currentTime - bAt(au.currentTime)) > 0.06) bu.currentTime = bAt(au.currentTime);
  });
  au.addEventListener("ended", function () {
    if (!au.loop) { play.innerHTML = "&#9654;"; play.setAttribute("aria-label", "Play"); }
  });
  seek.addEventListener("input", function () {
    var t = (Number(seek.value) / 1000) * (au.duration || 60);
    au.currentTime = t; bu.currentTime = bAt(t); now.textContent = fmt(t);
  });

  function setNames() {
    if (blind.checked) {
      nameA.textContent = "X"; nameB.textContent = "Y";
      rig.classList.add("blind"); gA.hidden = false; gB.hidden = false;
    } else {
      nameA.textContent = swapped ? "H2G conversion" : "Original .sid";
      nameB.textContent = swapped ? "Original .sid" : "H2G conversion";
      rig.classList.remove("blind"); gA.hidden = true; gB.hidden = true;
      verdict.textContent = "";
    }
  }
  blind.addEventListener("change", function () {
    swapped = blind.checked ? Math.random() < 0.5 : false;
    verdict.textContent = ""; apply(); setNames();
  });

  function guess(saidLeft) {
    var correct = saidLeft ? !swapped : swapped;
    total++; if (correct) right++;
    verdict.textContent = correct ? "Correct — that was the original."
                                  : "No — that was the conversion.";
    verdict.className = "verdict " + (correct ? "right" : "wrong");
    tally.textContent = right + " / " + total + " identified";
    swapped = Math.random() < 0.5; apply();
    nameA.textContent = "X"; nameB.textContent = "Y";
  }
  gA.addEventListener("click", function () { guess(true); });
  gB.addEventListener("click", function () { guess(false); });

  document.addEventListener("keydown", function (e) {
    if (e.target.tagName === "INPUT" && e.target.type !== "range") return;
    if (e.code === "Space") { e.preventDefault(); toggle(); }
    // 1-4 solo a voice, A/B pick the source. The digits USED to pick the
    // source, which spent the three keys that map onto the three voices the
    // ear is trying to separate -- and left soloing mouse-only, on the control
    // a listening pass reaches for most.
    else if (e.key === "1" || e.key === "2" || e.key === "3") {
      e.preventDefault(); if (window.__abSetVoice) window.__abSetVoice("v" + e.key);
    }
    else if (e.key === "4") {
      e.preventDefault(); if (window.__abSetVoice) window.__abSetVoice("all");
    }
    else if (e.key === "a" || e.key === "A" || e.key === "ArrowLeft") {
      e.preventDefault(); pick("a");
    }
    else if (e.key === "b" || e.key === "B" || e.key === "ArrowRight") {
      e.preventDefault(); pick("b");
    }
    // Restart. Driven through the seek slider rather than by setting
    // currentTime here: every follower (the tracker scroll, both drawings, the
    // register panel) already listens for its `input`, so one dispatch keeps
    // them in step instead of this needing to know all of them.
    else if (e.key === "r" || e.key === "R") {
      e.preventDefault();
      seek.value = "0";
      seek.dispatchEvent(new Event("input"));
      if (au.paused) toggle();
    }
    else if (e.key === "l" || e.key === "L") {
      looping.checked = !looping.checked; au.loop = bu.loop = looping.checked;
    }
  });
  // ---- amplitude overlay -------------------------------------------------
  // Both sides' peak envelopes on one canvas. It shows dropped notes, wrong
  // note lengths and tempo drift (the two traces shear apart); it cannot show
  // pitch, timbre or filter, which is why the caveat is printed beside it
  // rather than left for the reader to infer.
  // ---- shared zoom -------------------------------------------------------
  // ONE zoom for both drawings, not one each. The per-voice card's own caption
  // promises "same time axis and the same sync offset as the pair above", and
  // two independent zooms would quietly break that -- the whole reason to look
  // at them together is that a spike in one lines up with a shape in the other.
  //
  // `span` is the fraction of the tune on screen and `at` its left edge, both
  // in tune-fractions rather than seconds, so nothing here needs the duration
  // until it draws.
  //
  // The envelopes are computed at ZMAX times the display width (see
  // `envelope`), so zooming in reveals detail that was averaged away rather
  // than stretching the same buckets into blocks. Past ZMAX it would do the
  // latter, which is why the clamp is there and not higher: a zoom that stops
  // adding information should stop.
  var ZMAX = 32;
  var zoom = { span: 1, at: 0 };

  function zoomClamp() {
    zoom.span = Math.max(1 / ZMAX, Math.min(1, zoom.span));
    zoom.at = Math.max(0, Math.min(1 - zoom.span, zoom.at));
  }
  function zoomRedraw() {
    if (window.__abRedraw) window.__abRedraw();
    if (window.__abVoiceRedraw) window.__abVoiceRedraw();
    var t = document.getElementById("zoomstat");
    if (t) {
      t.textContent = zoom.span >= 1 ? "whole tune"
        : ("x" + (1 / zoom.span).toFixed(1) + " zoom");
    }
  }
  // Zoom about the cursor, so the thing under the pointer stays under it.
  function zoomWheel(e, box) {
    var r = box.getBoundingClientRect();
    var frac = Math.max(0, Math.min(1, (e.clientX - r.left) / r.width));
    var anchor = zoom.at + frac * zoom.span;
    var f = e.deltaY > 0 ? 1.25 : 1 / 1.25;
    var was = zoom.span;
    zoom.span *= f;
    zoomClamp();
    if (zoom.span === was) return false;   // already at a stop: let the page scroll
    zoom.at = anchor - frac * zoom.span;
    zoomClamp();
    zoomRedraw();
    return true;
  }
  function zoomBind(box) {
    box.addEventListener("wheel", function (e) {
      if (zoomWheel(e, box)) e.preventDefault();
    }, { passive: false });
    // Double-click restores the whole tune. It also seeks, because the click
    // handler fires too -- which is the behaviour you want anyway: zoom out
    // and land where you pointed.
    box.addEventListener("dblclick", function () {
      zoom.span = 1; zoom.at = 0; zoomRedraw();
    });
  }
  // Display column -> index into a ZMAX-oversampled envelope.
  function zsrc(i, cols, fine) {
    var f = zoom.at + (i / cols) * zoom.span;
    var k = Math.round(f * fine);
    return k < 0 ? 0 : (k >= fine ? fine - 1 : k);
  }

  var cv = document.getElementById("wave");
  if (cv) (function () {
    var msg = document.getElementById("wavemsg");
    var stat = document.getElementById("wavestat");
    var COLS = 1400, H = 200, DIFF = 46, PAD = 6;
    var FINE = COLS * ZMAX;
    var off = document.createElement("canvas");
    off.width = COLS; off.height = H + DIFF;
    cv.width = COLS; cv.height = H + DIFF;
    var ctx = cv.getContext("2d"), oc = off.getContext("2d");
    var envA = null, envB = null;

    function css(n) {
      return getComputedStyle(document.documentElement).getPropertyValue(n).trim();
    }
    // Sampled at ZMAX times the display width, so a zoom shows detail that was
    // averaged away rather than the same buckets stretched. It costs one array
    // of FINE floats a side (~180 KB) and no extra work: the loop is O(samples)
    // however many buckets it fills.
    function envelope(buf) {
      var ch = buf.getChannelData(0), n = ch.length;
      var out = new Float32Array(FINE), per = n / FINE;
      for (var i = 0; i < FINE; i++) {
        var s = Math.floor(i * per), e = Math.min(n, Math.floor((i + 1) * per));
        var pk = 0;
        for (var j = s; j < e; j++) { var v = ch[j] < 0 ? -ch[j] : ch[j]; if (v > pk) pk = v; }
        out[i] = pk;
      }
      return out;
    }
    // `by` is the sync offset in FINE units, applied as the envelope is read,
    // which is what lets the shift stay correct at every zoom -- shifting a
    // pre-sampled array would quantise the offset to the visible resolution.
    function at(env, i, by) {
      var k = zsrc(i, COLS, FINE) + by;
      return (k >= 0 && k < FINE) ? env[k] : 0;
    }
    function band(g, env, colour, alpha, by) {
      var mid = H / 2, half = mid - PAD;
      g.beginPath();
      for (var i = 0; i < COLS; i++) g.lineTo(i, mid - at(env, i, by) * half);
      for (var k = COLS - 1; k >= 0; k--) g.lineTo(k, mid + at(env, k, by) * half);
      g.closePath();
      g.globalAlpha = alpha; g.fillStyle = colour; g.fill(); g.globalAlpha = 1;
    }
    // B is drawn where it is *heard*, i.e. shifted by the sync offset, so the
    // picture never contradicts the ears.
    function shiftCols() {
      var d = au.duration;
      if (!d || !isFinite(d)) return 0;
      return Math.round(sync / d * FINE);
    }
    function paint() {
      var line = css("--line"), ink = css("--ink"), by = shiftCols();
      oc.clearRect(0, 0, COLS, H + DIFF);
      oc.strokeStyle = line; oc.lineWidth = 1;
      oc.beginPath(); oc.moveTo(0, H / 2 + 0.5); oc.lineTo(COLS, H / 2 + 0.5); oc.stroke();
      oc.beginPath(); oc.moveTo(0, H + 0.5); oc.lineTo(COLS, H + 0.5); oc.stroke();
      if (show.a) band(oc, envA, css("--a"), 0.62, 0);
      if (show.b) band(oc, envB, css("--b"), 0.62, by);
      // difference strip: |peak difference| per column, same time axis.
      if (show.d) {
        oc.globalAlpha = 0.45; oc.fillStyle = ink;
        for (var i = 0; i < COLS; i++) {
          var d = Math.abs(at(envA, i, 0) - at(envB, i, by));
          oc.fillRect(i, H + DIFF - d * (DIFF - 4), 1, d * (DIFF - 4));
        }
        oc.globalAlpha = 1;
      }
      // The mean is over the WHOLE tune at full resolution, never over what is
      // on screen. It is a property of the two renders, so neither hiding a
      // trace nor zooming may move it -- a figure that changed when you scrolled
      // would read as a measurement and be a description of the viewport.
      var sum = 0;
      for (var k = 0; k < FINE; k++) {
        var j = k + by;
        sum += Math.abs(envA[k] - ((j >= 0 && j < FINE) ? envB[j] : 0));
      }
      if (stat) stat.textContent = "mean |Δ| " + (100 * sum / FINE).toFixed(1) + "%";
      frame();
    }

    // Which traces are drawn. Hiding one does not recompute anything -- paint()
    // reads these and the envelopes are untouched, so toggling is free and
    // reversible.
    var show = { a: true, b: true, d: true };
    Array.prototype.forEach.call(
      cv.parentNode.querySelectorAll("button.swatch[data-trace]"),
      function (b) {
        b.addEventListener("click", function () {
          var k = b.dataset.trace;
          show[k] = !show[k];
          b.setAttribute("aria-pressed", String(show[k]));
          if (envA) paint();
        });
      });
    window.__abRedraw = function () { if (envA) paint(); };

    // --- automatic sync ---------------------------------------------------
    // The two renders do not start together. gt2reloc's packed player reaches
    // its first note some 3-8 frames after the original -- FIDELITY.md calls
    // it startup_lag and corrects for it before scoring any per-frame column.
    // Nothing corrected for it *here* until now, so every A/B was compared
    // with one side 120-150 ms late: audible as a flam on the switch, and
    // exactly the misalignment this control exists to remove.
    //
    // Measured as the difference between the two first onsets rather than by
    // cross-correlating the whole file. Correlation was tried first and is the
    // wrong instrument: over 60 s the two sides drift and often play different
    // numbers of notes (Knucklebusters: 156 against 404), so the correlation
    // comes out flat -- its top six lags were 41, -10, -28, 59, 52 and -17
    // columns, all within 3% of each other. A start offset is a property of
    // the start, and the first onset is where it lives.
    var ONSET_FRAC = 0.05, ONSET_LOOK = 20;
    function firstOnset(b) {
      var ch = b.getChannelData(0), rate = b.sampleRate;
      var n = Math.min(ch.length, Math.round(ONSET_LOOK * rate)), pk = 0;
      for (var i = 0; i < n; i++) { var v = ch[i] < 0 ? -ch[i] : ch[i]; if (v > pk) pk = v; }
      if (!pk) return null;
      var thr = pk * ONSET_FRAC;
      for (var j = 0; j < n; j++) { var w = ch[j] < 0 ? -ch[j] : ch[j]; if (w >= thr) return j / rate; }
      return null;
    }
    function startupLagMs(bufA, bufB) {
      var fa = firstOnset(bufA), fb = firstOnset(bufB);
      if (fa === null || fb === null) return null;
      var ms = (fb - fa) * 1000;
      if (ms < -500 || ms > 500) return null;   // not a startup lag
      return ms;
    }

    function frame() {
      ctx.clearRect(0, 0, COLS, H + DIFF);
      ctx.drawImage(off, 0, 0);
      var d = au.duration;
      if (d && isFinite(d)) {
        // Off-screen while zoomed in elsewhere: drawn anyway and simply clipped,
        // rather than hidden, so the line's absence always means "not playing"
        // and never "playing somewhere you cannot see".
        var f = (au.currentTime / d - zoom.at) / zoom.span;
        var x = Math.round(f * COLS) + 0.5;
        ctx.strokeStyle = css("--live"); ctx.lineWidth = 2;
        ctx.beginPath(); ctx.moveTo(x, 0); ctx.lineTo(x, H + DIFF); ctx.stroke();
      }
    }
    au.addEventListener("timeupdate", function () { if (envA) frame(); });
    seek.addEventListener("input", function () { if (envA) frame(); });

    cv.addEventListener("click", function (e) {
      var d = au.duration;
      if (!d || !isFinite(d)) return;
      var r = cv.getBoundingClientRect();
      var frac = Math.max(0, Math.min(1, (e.clientX - r.left) / r.width));
      var t = (zoom.at + frac * zoom.span) * d;
      au.currentTime = t; bu.currentTime = bAt(t);
      now.textContent = fmt(t);
      seek.value = String(Math.round(t / d * 1000));
      frame();
    });
    zoomBind(cv);

    var AC = window.AudioContext || window.webkitAudioContext;
    if (!AC) { if (msg) msg.textContent = "This browser has no Web Audio."; return; }
    var ac = new AC();
    function load(src) {
      return fetch(src).then(function (r) { return r.arrayBuffer(); })
        .then(function (ab) { return ac.decodeAudioData(ab); });
    }
    function loadPair(keepSync) {
    return Promise.all([load(au.src), load(bu.src)]).then(function (bufs) {
      envA = envelope(bufs[0]); envB = envelope(bufs[1]);
      if (msg) msg.hidden = true;
      cv.hidden = false;
      // A solo render's first onset is that voice's, not the song's, so the
      // startup lag is measured once from the full pair and carried across
      // voice switches rather than re-derived from a voice that may not play
      // at the start at all.
      var lag = keepSync ? null : startupLagMs(bufs[0], bufs[1]);
      if (lag !== null) {
        autoSync = lag;
        setSync(autoSync, "&mdash; auto: our render's first note is "
                + Math.round(lag) + " ms (" + (lag / 20).toFixed(1)
                + " frames) later than the original's; drag to taste");
      } else {
        syncwhy.innerHTML = "&mdash; no first onset found; drag to align by ear";
      }
      paint();
    }).catch(function () {
      // file:// blocks fetch of a sibling .wav in most browsers; the audio
      // elements themselves still play, so this is a missing picture and not
      // a broken page.
      cv.hidden = true;
      if (msg) msg.innerHTML =
        "The drawing and the automatic sync read both WAVs, which a browser "
        + "refuses over file://. Run <code>python abpage.py --serve</code> and "
        + "open the printed http:// address; playback and the sync slider "
        + "work here either way.";
    });
    }
    window.__abReload = loadPair;
    loadPair(false);
  })();

  // ---- per-voice amplitude -------------------------------------------------
  // Three overlays on one time axis, so "which voice is wrong" is a glance
  // rather than three rounds of soloing. Decoded once and kept as envelopes:
  // the six solo WAVs are the same bytes the voice buttons already swap in,
  // so this costs one extra decode pass and no extra staging.
  var vwrap = document.getElementById("vwrap");
  if (vwrap && window.__abVoices) (function () {
    var vmsg = document.getElementById("vwmsg");
    // DIFF is the |difference| strip under each voice's bands, the same third
    // trace the combined picture carries. Shallower here (22px against 46)
    // because there are three of them stacked and the strip is read for WHERE
    // it spikes, not for how tall the spike is.
    var COLS = 1400, H = 84, DIFF = 22, PAD = 3;
    var FINE = COLS * ZMAX;
    var AC = window.AudioContext || window.webkitAudioContext;
    if (!AC) { if (vmsg) vmsg.textContent = "This browser has no Web Audio."; return; }
    var ac = new AC(), strips = [];

    // Oversampled like the combined picture, for the same reason and at the
    // same factor -- six of these is about a megabyte, which is nothing beside
    // the WAVs they came from.
    function env(buf) {
      var ch = buf.getChannelData(0), n = ch.length;
      var out = new Float32Array(FINE), per = n / FINE;
      for (var i = 0; i < FINE; i++) {
        var s = Math.floor(i * per), e = Math.min(n, Math.floor((i + 1) * per)), pk = 0;
        for (var j = s; j < e; j++) { var v = ch[j] < 0 ? -ch[j] : ch[j]; if (v > pk) pk = v; }
        out[i] = pk;
      }
      return out;
    }
    function vat(e, i, by) {
      var k = zsrc(i, COLS, FINE) + by;
      return (k >= 0 && k < FINE) ? e[k] : 0;
    }
    function grab(src) {
      return fetch(src).then(function (r) { return r.arrayBuffer(); })
        .then(function (ab) { return ac.decodeAudioData(ab); });
    }
    function cssv(n) {
      return getComputedStyle(document.documentElement).getPropertyValue(n).trim();
    }
    // The SAME shift the combined picture uses. Derived from the full pair, not
    // from a solo voice -- a voice that is silent at the start has no first
    // onset of its own, and measuring one per strip would slide the quiet
    // voices against the loud ones for no musical reason.
    function shiftCols() {
      var d = au.duration;
      if (!d || !isFinite(d)) return 0;
      return Math.round(sync / d * FINE);
    }
    function paintStrip(s) {
      var g = s.ctx, by = shiftCols(), mid = H / 2, half = mid - PAD;
      g.clearRect(0, 0, COLS, H + DIFF);
      g.strokeStyle = cssv("--line"); g.lineWidth = 1;
      g.beginPath(); g.moveTo(0, mid + 0.5); g.lineTo(COLS, mid + 0.5); g.stroke();
      g.beginPath(); g.moveTo(0, H + 0.5); g.lineTo(COLS, H + 0.5); g.stroke();
      function band(e, colour, shifted) {
        var sh = shifted ? by : 0;
        g.beginPath();
        for (var i = 0; i < COLS; i++) g.lineTo(i, mid - vat(e, i, sh) * half);
        for (var k = COLS - 1; k >= 0; k--) g.lineTo(k, mid + vat(e, k, sh) * half);
        g.closePath(); g.globalAlpha = 0.62; g.fillStyle = colour; g.fill();
        g.globalAlpha = 1;
      }
      if (vshow.a) band(s.a, cssv("--a"), false);
      if (vshow.b) band(s.b, cssv("--b"), true);
      // |difference| per column, on the same time axis and the same shift as
      // the bands above it. This is the trace that answers "where do these two
      // part company" without the eye having to separate two overlapping
      // shapes -- on a voice where the renders agree it is a flat line, so a
      // spike is the thing to go and listen to.
      if (vshow.d) {
        g.globalAlpha = 0.45; g.fillStyle = cssv("--ink");
        for (var i = 0; i < COLS; i++) {
          var dv = Math.abs(vat(s.a, i, 0) - vat(s.b, i, by));
          g.fillRect(i, H + DIFF - dv * (DIFF - 3), 1, dv * (DIFF - 3));
        }
        g.globalAlpha = 1;
      }
      var d = au.duration;
      if (d && isFinite(d)) {
        var f = (au.currentTime / d - zoom.at) / zoom.span;
        var x = Math.round(f * COLS) + 0.5;
        g.strokeStyle = cssv("--live"); g.lineWidth = 2;
        g.beginPath(); g.moveTo(x, 0); g.lineTo(x, H + DIFF); g.stroke();
      }
    }
    function paintAll() { strips.forEach(paintStrip); }
    window.__abVoiceRedraw = paintAll;

    // Which side is drawn, across ALL THREE strips at once -- the same control
    // the combined picture has, and one switch rather than three, because the
    // question it answers ("where does our render put something the original
    // does not") is asked of the voices together.
    var vshow = { a: true, b: true, d: true };
    Array.prototype.forEach.call(
      document.querySelectorAll(".voicewave button.swatch[data-vtrace]"),
      function (b) {
        b.addEventListener("click", function () {
          var k = b.dataset.vtrace;
          vshow[k] = !vshow[k];
          b.setAttribute("aria-pressed", String(vshow[k]));
          paintAll();
        });
      });

    var jobs = [1, 2, 3].map(function (v) {
      var pair = window.__abVoices["v" + v];
      return Promise.all([grab(pair[0]), grab(pair[1])]).then(function (bufs) {
        var cv = document.getElementById("vwcv" + v);
        cv.width = COLS; cv.height = H + DIFF;
        var a = env(bufs[0]), b = env(bufs[1]), by = shiftCols(), sum = 0;
        // Over the whole tune at full resolution, never over the visible
        // window -- this number ranks the voices against each other and must
        // not move when one of them is zoomed.
        for (var i = 0; i < FINE; i++) {
          var j = i + by;
          sum += Math.abs(a[i] - ((j >= 0 && j < FINE) ? b[j] : 0));
        }
        var st = document.getElementById("vwstat" + v);
        if (st) st.textContent = "mean |Δ| " + (100 * sum / FINE).toFixed(1) + "%";
        cv.addEventListener("click", function (e) {
          var d = au.duration;
          if (!d || !isFinite(d)) return;
          var r = cv.getBoundingClientRect();
          var frac = Math.max(0, Math.min(1, (e.clientX - r.left) / r.width));
          var t = (zoom.at + frac * zoom.span) * d;
          au.currentTime = t; bu.currentTime = bAt(t);
          now.textContent = fmt(t);
          seek.value = String(Math.round(t / d * 1000));
        });
        zoomBind(cv);
        strips.push({ ctx: cv.getContext("2d"), a: a, b: b });
      });
    });
    // Collapse a voice. The strip keeps its mean |difference| visible while
    // collapsed -- that number is what ranks the voices, so hiding it with the
    // picture would defeat the point of collapsing the other two.
    Array.prototype.forEach.call(
      vwrap.querySelectorAll("button.vwtoggle"), function (b) {
        b.addEventListener("click", function () {
          var box = b.closest(".vw");
          var on = b.getAttribute("aria-pressed") !== "false";
          b.setAttribute("aria-pressed", String(!on));
          box.classList.toggle("off", on);
          if (!on) paintAll();      // re-shown: it was not painted while off
        });
      });

    Promise.all(jobs).then(function () {
      if (vmsg) vmsg.hidden = true;
      vwrap.hidden = false;
      paintAll();
    }).catch(function () {
      // Same file:// limitation as the combined picture, same wording.
      vwrap.hidden = true;
      if (vmsg) vmsg.innerHTML =
        "The per-voice drawing reads the six solo WAVs, which a browser "
        + "refuses over file://. Run <code>python abpage.py --serve</code>.";
    });
    au.addEventListener("timeupdate", paintAll);
    seek.addEventListener("input", paintAll);
  })();

  // ---- spectrogram overlay ------------------------------------------------
  // Both sides' log-frequency magnitude, precomputed once at build time (see
  // abpage.py's spectrogram_payload) -- a per-sample FFT here, over two
  // two-minute WAVs, could not draw in under a second. What ships is two
  // small fixed-size byte grids (bins x cols); painting them is a handful of
  // arithmetic per cell regardless of how long the tune runs, so every call
  // below -- including the one on every timeupdate during playback -- is
  // sub-millisecond.
  var scv = document.getElementById("spectro");
  if (scv && window.__abSpectrogram) (function () {
    var spec = window.__abSpectrogram, COLS = spec.cols, BINS = spec.bins;
    var W = 900, H = 220;
    scv.width = W; scv.height = H;
    var ctx = scv.getContext("2d");
    var off = document.createElement("canvas");
    off.width = COLS; off.height = BINS;
    var octx = off.getContext("2d");

    function decode(b64) {
      var bin = atob(b64), out = new Uint8Array(bin.length);
      for (var i = 0; i < bin.length; i++) out[i] = bin.charCodeAt(i);
      return out;
    }
    var gridA = decode(spec.a), gridB = decode(spec.b);

    function css(n) {
      return getComputedStyle(document.documentElement).getPropertyValue(n).trim();
    }
    function hexToRgb(hex) {
      hex = hex.trim().replace("#", "");
      if (hex.length === 3) hex = hex.split("").map(function (c) { return c + c; }).join("");
      var n = parseInt(hex, 16);
      return [(n >> 16) & 255, (n >> 8) & 255, n & 255];
    }
    // B is drawn where it is HEARD, same rule as the amplitude overlay above:
    // shifted by the sync offset so the picture never contradicts the ears.
    function shiftCols() {
      var d = au.duration;
      if (!d || !isFinite(d)) return 0;
      return Math.round(sync / d * COLS);
    }
    function paint() {
      var rgbA = hexToRgb(css("--a")), rgbB = hexToRgb(css("--b"));
      var img = octx.createImageData(COLS, BINS);
      var by = shiftCols();
      for (var b = 0; b < BINS; b++) {
        var row = BINS - 1 - b;                 // bin 0 (lowest freq) at the bottom
        for (var c = 0; c < COLS; c++) {
          var cc = c - by;
          var va = gridA[b * COLS + c] / 255;
          var vb = (cc >= 0 && cc < COLS) ? gridB[b * COLS + cc] / 255 : 0;
          var idx = (row * COLS + c) * 4;
          img.data[idx] = Math.min(255, rgbA[0] * va + rgbB[0] * vb);
          img.data[idx + 1] = Math.min(255, rgbA[1] * va + rgbB[1] * vb);
          img.data[idx + 2] = Math.min(255, rgbA[2] * va + rgbB[2] * vb);
          img.data[idx + 3] = 255;
        }
      }
      octx.putImageData(img, 0, 0);
      ctx.imageSmoothingEnabled = false;
      ctx.clearRect(0, 0, W, H);
      ctx.drawImage(off, 0, 0, COLS, BINS, 0, 0, W, H);
      var d = au.duration;
      if (d && isFinite(d)) {
        var x = Math.round(au.currentTime / d * W) + 0.5;
        ctx.strokeStyle = css("--live"); ctx.lineWidth = 2;
        ctx.beginPath(); ctx.moveTo(x, 0); ctx.lineTo(x, H); ctx.stroke();
      }
    }
    scv.addEventListener("click", function (e) {
      var d = au.duration;
      if (!d || !isFinite(d)) return;
      var r = scv.getBoundingClientRect();
      var t = Math.max(0, Math.min(1, (e.clientX - r.left) / r.width)) * d;
      au.currentTime = t; bu.currentTime = bAt(t);
      now.textContent = fmt(t);
      seek.value = String(Math.round(t / d * 1000));
      paint();
    });
    au.addEventListener("timeupdate", paint);
    au.addEventListener("loadedmetadata", paint);
    seek.addEventListener("input", paint);
    window.__abSpectroRedraw = paint;
    paint();
  })();

  // ---- voice selector ----------------------------------------------------
  // Each button swaps BOTH sources to the same voice, so the comparison stays
  // like-for-like. Position and play state are preserved across the swap, and
  // the sync offset is left alone -- it is a property of the two players'
  // startup, not of which voice is audible.
  var vrow = document.getElementById("voices");
  if (vrow && window.__abVoices) {
    var vbtns = Array.prototype.slice.call(vrow.querySelectorAll("button"));
    var vnote = document.getElementById("voicenote");
    function setVoice(key) {
      var pair = window.__abVoices[key];
      if (!pair) return;
      var t = au.currentTime, playing = !au.paused;
      au.src = pair[0]; bu.src = pair[1];
      au.load(); bu.load();
      au.currentTime = t; bu.currentTime = bAt(t);
      if (playing) { au.play(); bu.play(); }
      vbtns.forEach(function (b) {
        b.setAttribute("aria-pressed", String(b.dataset.voice === key));
      });
      if (vnote) {
        vnote.textContent = key === "all"
          ? "all three voices, as staged"
          : "voice " + key.slice(1) + " alone on both sides";
      }
      if (window.__abReload) window.__abReload(true);
    }
    vbtns.forEach(function (b) {
      b.addEventListener("click", function () { setVoice(b.dataset.voice); });
    });
    // The keydown handler is installed ABOVE this block and cannot see into
    // its closure, so the digits reach the selector through here.
    window.__abSetVoice = setVoice;
  }

  // ---- register panel ----------------------------------------------------
  var panel = document.querySelector(".panel");
  if (panel) (function () {
    var rows = Array.prototype.slice.call(panel.querySelectorAll(".vrow"));
    var trace = null;

    // siddump emits a register only when it changes, so the value at frame f
    // is the last event at or before f. Events are in frame order already.
    function valueAt(events, f) {
      var lo = 0, hi = events.length - 1, best = null;
      while (lo <= hi) {
        var mid = (lo + hi) >> 1;
        if (events[mid][0] <= f) { best = events[mid][1]; lo = mid + 1; }
        else hi = mid - 1;
      }
      return best;
    }
    function usedKeys(voice) {
      var out = {};
      for (var i = 0; i < voice.wf.length; i++) {
        var w = voice.wf[i][1];
        if (w & 0x08) out.test = 1;
        if (w & 0x02) out.sync = 1;
        if (w & 0x04) out.ring = 1;
        var cls = (w >> 4) & 0x0F;
        if (cls) out["w" + cls] = 1;
      }
      // "Repeatedly changes" in the reference tools means a handful of
      // distinct values, not one write. Four matches their note.
      var pv = {}, av = {};
      for (var j = 0; j < voice.pulse.length; j++) pv[voice.pulse[j][1]] = 1;
      for (var k = 0; k < voice.adsr.length; k++) av[voice.adsr[k][1]] = 1;
      if (Object.keys(pv).length >= 4) out.pulse = 1;
      if (Object.keys(av).length >= 4) out.adsr = 1;
      return out;
    }
    function mark() {
      var uo = [0, 1, 2].map(function (i) { return usedKeys(trace.orig.voices[i]); });
      var ub = [0, 1, 2].map(function (i) { return usedKeys(trace.ours.voices[i]); });
      rows.forEach(function (r) {
        var v = Number(r.dataset.v) - 1, k = r.dataset.k;
        r.classList.toggle("uo", !!uo[v][k]);
        r.classList.toggle("ub", !!ub[v][k]);
        if (uo[v][k] || ub[v][k]) r.classList.add("on");
      });
    }
    function live() {
      if (!trace) return;
      var f = Math.floor(au.currentTime * 50);
      rows.forEach(function (r) {
        var v = Number(r.dataset.v) - 1, k = r.dataset.k, on = false, val = "";
        var ov = trace.orig.voices[v], bv = trace.ours.voices[v];
        if (k.charAt(0) === "w" && k.length === 2) {
          var want = Number(k.charAt(1));
          var wo = valueAt(ov.wf, f), wb = valueAt(bv.wf, f);
          on = (((wo >> 4) & 15) === want) || (((wb >> 4) & 15) === want);
        } else if (k === "test" || k === "sync" || k === "ring") {
          var bit = k === "test" ? 8 : (k === "sync" ? 2 : 4);
          on = !!((valueAt(ov.wf, f) & bit) || (valueAt(bv.wf, f) & bit));
        } else if (k === "pulse") {
          var po = valueAt(ov.pulse, f), pb = valueAt(bv.pulse, f);
          val = (po === null ? "----" : hex3(po)) + " " + (pb === null ? "----" : hex3(pb));
        } else if (k === "adsr") {
          var ao = valueAt(ov.adsr, f), ab = valueAt(bv.adsr, f);
          val = (ao === null ? "----" : hex4(ao)) + " " + (ab === null ? "----" : hex4(ab));
        }
        r.classList.toggle("now", on);
        var cell = r.querySelector(".val");
        if (cell && val) cell.textContent = val;
      });
    }
    function hex3(n) { return ("00" + n.toString(16).toUpperCase()).slice(-3); }
    function hex4(n) { return ("000" + n.toString(16).toUpperCase()).slice(-4); }

    fetch(window.__abTrace).then(function (r) { return r.json(); })
      .then(function (t) { trace = t; mark(); live(); })
      .catch(function () {
        panel.insertAdjacentHTML("beforebegin",
          "<p class=\"opts\">The register panel reads a trace file, which a "
          + "browser refuses over file://. Run <code>python abpage.py "
          + "--serve</code>.</p>");
      });
    au.addEventListener("timeupdate", live);
    seek.addEventListener("input", live);
  })();

  // ---- tracker scroll ----------------------------------------------------
  // Follows OUR render's clock (bu), because the rows are our conversion's.
  // The frame of a row came from the tempo written in the file, so a drift
  // here against the audio is the row rate being wrong -- left visible on
  // purpose.
  if (window.__abRows) (function () {
    var cols = [0, 1, 2].map(function (v) { return document.getElementById("trk" + v); });
    if (cols.some(function (c) { return !c; })) return;
    var cur = [null, null, null];

    function rowAt(frames, f) {
      var lo = 0, hi = frames.length - 1, best = 0;
      while (lo <= hi) {
        var mid = (lo + hi) >> 1;
        if (frames[mid] <= f) { best = mid; lo = mid + 1; } else hi = mid - 1;
      }
      return best;
    }
    // A single scrollTop assignment per note (driven off "timeupdate", which
    // Chrome fires ~4x/sec) reads as a series of leaps rather than motion,
    // and CSS scroll-behavior:smooth made it worse: each leap restarted the
    // browser's own animation mid-flight, so the visible position overshot
    // and corrected on every row. Instead: while playing, a rAF loop moves
    // scrollTop continuously, interpolated between the current row's offset
    // and the next row's by how far the exact play position is between the
    // two rows' start frames -- one smooth motion instead of one jump per row.
    function updateRow(v, i) {
      if (i === cur[v]) return;
      cur[v] = i;
      var box = cols[v];
      var prev = box.querySelector(".trkrow.cur");
      if (prev) prev.classList.remove("cur");
      var el = box.children[i];
      if (el) el.classList.add("cur");
    }
    function scrollTick(instant) {
      var f = (bu.currentTime || au.currentTime) * 50;
      for (var v = 0; v < 3; v++) {
        var frames = window.__abRows[v];
        if (!frames || !frames.length) continue;
        var i = rowAt(frames, Math.floor(f));
        updateRow(v, i);
        var box = cols[v];
        var el = box.children[i];
        if (!el) continue;
        var nextEl = box.children[i + 1];
        var top = el.offsetTop;
        if (nextEl && i + 1 < frames.length) {
          var span = frames[i + 1] - frames[i];
          var frac = span > 0 ? Math.min(1, Math.max(0, (f - frames[i]) / span)) : 0;
          top += (nextEl.offsetTop - el.offsetTop) * frac;
        }
        box.scrollTop = top - box.clientHeight / 2 + el.offsetHeight / 2;
      }
    }
    function follow() { scrollTick(true); }

    var rafId = null;
    function frameLoop() { scrollTick(false); rafId = requestAnimationFrame(frameLoop); }
    function startScroll() { if (rafId === null) rafId = requestAnimationFrame(frameLoop); }
    function stopScroll() { if (rafId !== null) { cancelAnimationFrame(rafId); rafId = null; } follow(); }
    au.addEventListener("play", startScroll);
    au.addEventListener("pause", stopScroll);
    au.addEventListener("ended", stopScroll);
    seek.addEventListener("input", follow);
    follow();

    // Click a row to jump playback there and pause -- so a row that looks
    // wrong can be heard in isolation instead of waiting for the loop to
    // scroll back around to it. Guarded on readyState: setting .currentTime
    // before the browser has metadata (duration unknown) can block on a
    // 10+ MB WAV while it works out whether the position is even seekable --
    // silently doing nothing here is better than a hang.
    cols.forEach(function (box) {
      box.addEventListener("click", function (e) {
        var row = e.target.closest(".trkrow");
        if (!row || !box.contains(row)) return;
        if (au.readyState < 1 || bu.readyState < 1) return;
        var i = Number(row.dataset.i);
        var v = cols.indexOf(box);
        var frames = window.__abRows[v];
        if (!frames || !(i in frames)) return;
        var t = frames[i] / 50;
        au.pause(); bu.pause();
        play.innerHTML = "&#9654;"; play.setAttribute("aria-label", "Play");
        au.currentTime = t; bu.currentTime = bAt(t);
        now.textContent = fmt(t);
        if (au.duration) seek.value = String(Math.round(t / au.duration * 1000));
        follow();
      });
    });
  })();

  apply(); setNames();
})();
"""


def wav_rendered(path: Path) -> str:
    """"rendered 2026-08-23 14:07" for a staged WAV, or "" if it is absent.

    Local time, not UTC: the reader comparing this against "did I just re-run
    listen.py?" is looking at their own clock.

    This exists because a stale render is silent. `listen.py` overwrites its
    output in place and never announces an age, so a pair left from an earlier
    converter state plays perfectly and sounds subtly wrong -- and the first
    suspicion falls on the converter. That has already cost this project one
    wrong diagnosis, from a pair four days old. A timestamp on the face of the
    page turns "why does this sound off" into "this was rendered before the
    fix" without anyone having to think to check.
    """
    try:
        ts = path.stat().st_mtime
    except OSError:
        return ""
    return "rendered " + datetime.fromtimestamp(ts).strftime("%Y-%m-%d %H:%M")


def wav_uri(path: Path) -> str:
    return "data:audio/wav;base64," + base64.b64encode(path.read_bytes()).decode("ascii")


LAUNCHER = r"""# Listen.ps1 -- the A/B listening pass. Run Listen.cmd, not this file.
#
# Written by python/abpage.py; edits here are overwritten on the next build.
# It starts the little server abpage.py --serve provides and opens the index,
# because the envelope drawing and the automatic sync both read the WAVs with
# fetch(), which no browser allows over file://.
#
# DOUBLE-CLICKING A .ps1 DOES NOT RUN IT. Windows has no "run" default verb
# for the type -- Explorer opens it in an editor -- and even the right-click
# "Run with PowerShell" can be refused by the execution policy. That is why
# Listen.cmd sits beside this file: .cmd does run on double-click, and it
# invokes this script with -ExecutionPolicy Bypass. The instruction to
# double-click *this* file was wrong for as long as it was written here.
$ErrorActionPreference = "Stop"
$repo = "%(repo)s"
$port = %(port)d
$url  = "http://127.0.0.1:$port/index.html"

Write-Host "H2G listening pass" -ForegroundColor Cyan
Write-Host "  serving $repo\build\listen on $url"
Write-Host "  close this window to stop the server."

# `--serve` alone rebuilds every staged page (spectrogram included, ~3.4s a
# tune -- five minutes over 83) BEFORE it binds the port. A fixed sleep here
# therefore opened the browser on nothing (ERR_CONNECTION_REFUSED), and even
# with the poll below the window sat silent for minutes and read as hung.
# `--no-build` serves what is already staged, so the port binds at once; run
# `python abpage.py` when the pages actually need rebuilding. The poll stays:
# it costs nothing and still covers a slow start.
Start-Job -ArgumentList $port, $url -ScriptBlock {
  param($port, $url)
  $deadline = (Get-Date).AddMinutes(15)
  $up = $false
  while ((Get-Date) -lt $deadline) {
    $client = New-Object System.Net.Sockets.TcpClient
    try {
      $client.Connect("127.0.0.1", $port)
      $up = $client.Connected
    } catch {
      $up = $false
    } finally {
      $client.Close()
    }
    if ($up) { break }
    Start-Sleep -Milliseconds 500
  }
  if ($up) { Start-Process $url }
} | Out-Null

Push-Location "$repo\python"
try { python abpage.py --serve $port --no-build } finally { Pop-Location }
"""


# The thing a human can actually double-click. Explorer has no "run" verb for
# .ps1 (it opens an editor) and "Run with PowerShell" is subject to the
# execution policy, so the PowerShell script alone was unrunnable by the one
# gesture its own header told people to use. .cmd runs on double-click on every
# Windows box, and this one does nothing but call the script the documented way.
LAUNCHER_CMD = r"""@echo off
REM Listen.cmd -- double-click this to open the A/B listening pass.
REM Written by python/abpage.py; edits here are overwritten on the next build.
REM It only launches Listen.ps1: a .ps1 cannot be started by double-click, a
REM .cmd can. -ExecutionPolicy Bypass applies to this invocation alone and
REM changes no machine setting.
powershell -NoProfile -ExecutionPolicy Bypass -File "%~dp0Listen.ps1"
if errorlevel 1 (
  echo.
  echo Listen.ps1 exited with an error. The window is kept open so the
  echo message above stays readable.
  pause
)
"""


def write_launcher(port: int = 8730) -> tuple[Path, Path]:
    """Drop Listen.ps1 and its Listen.cmd shim beside the staged pairs.

    Returns both paths; the .cmd is the one to tell a human about.
    """
    ps1 = LISTEN / "Listen.ps1"
    ps1.write_text(LAUNCHER % {"repo": str(ROOT), "port": port},
                   encoding="utf-8")
    cmd = LISTEN / "Listen.cmd"
    # ASCII, CRLF: a .cmd is read by the legacy command processor, which does
    # not want a UTF-8 BOM and is happier with DOS line endings.
    #
    # `newline=""` and NOT `write_text(... .replace("\n", "\r\n"))`: text mode
    # translates on write, so a string that already carries \r\n is written as
    # \r\r\n. That is a real corruption, not a cosmetic one -- and it is
    # invisible to `read_text()`, which translates it back on the way in. Only
    # the raw bytes show it.
    with open(cmd, "w", encoding="ascii", newline="\r\n") as fh:
        fh.write(LAUNCHER_CMD)
    return ps1, cmd


def facts_card(name: str, sv: dict, pre: dict) -> str:
    """The "what this is" card: player, structure, packing, chosen options."""
    if not sv and not pre:
        return ""
    cells = []
    for key, label in SURVEY_FIELDS:
        val = (sv or {}).get(key, "")
        if not val or val == "-":
            continue
        if key == "gt2reloc":
            val = {"y": "yes", "n": "no"}.get(val, val)
        cells.append('<div><span class="k">%s</span>'
                     '<span class="v">%s</span></div>' % (label, val))
    mult = (pre or {}).get("multiplier")
    if mult:
        cells.append('<div><span class="k">packed at</span>'
                     '<span class="v">-S%d%s</span></div>'
                     % (mult, "" if mult == 1 else " (%d calls a frame)" % mult))
    rows_ = (pre or {}).get("rows")
    if rows_:
        cells.append('<div><span class="k">pattern rows</span>'
                     '<span class="v">%s</span></div>' % f"{rows_:,}")
    if not cells:
        return ""

    chosen = [k for k in NOTABLE if (pre or {}).get(k)]
    opts = ("<p class=\"opts\">Converted with %s &mdash; the settings "
            "<code>presets.py --fidelity</code> measured as best for this "
            "tune. Every other tune here shares the same always-on set.</p>"
            % ", ".join("<code>--%s</code>" % k.replace("_", "-")
                        for k in chosen)) if chosen else (
            "<p class=\"opts\">No per-song options: this tune is converted "
            "with the always-on settings alone.</p>")

    return ('<div class="card">\n  <h2>What this is</h2>\n'
            '  <div class="facts">%s</div>\n%s\n</div>\n' % ("".join(cells), opts))


# The rows of the register panel, in the reference tools' order: waveform
# classes first, then the control bits, then the two "repeatedly changes"
# counts. `test` is bit 3, `sync` bit 1, `ring` bit 2 of $D404.
PANEL_ROWS = [
    ("w1", "Uses $1x waveform (triangle)"),
    ("w2", "Uses $2x waveform (sawtooth)"),
    ("w3", "Uses $3x waveform (tri+saw)"),
    ("w4", "Uses $4x waveform (pulse)"),
    ("w5", "Uses $5x waveform (tri+pulse)"),
    ("w6", "Uses $6x waveform (saw+pulse)"),
    ("w7", "Uses $7x waveform (tri+saw+pulse)"),
    ("w8", "Uses $8x waveform (noise)"),
    ("test", "Uses the test bit"),
    ("sync", "Uses hard synchronization"),
    ("ring", "Uses ring modulation"),
    ("pulse", "Repeatedly changes pulse width"),
    ("adsr", "Repeatedly changes the ADSR"),
]


NOTE_NAMES = ("C-", "C#", "D-", "D#", "E-", "F-", "F#", "G-",
              "G#", "A-", "A#", "B-")
GT_FIRST_NOTE, GT_LAST_NOTE = 0x60, 0xBC
GT_REST, GT_KEYOFF, GT_KEYON, GT_ENDPATT = 0xBD, 0xBE, 0xBF, 0xFF
CMD_SETTEMPO_ = 0x0F


def _note_name(n: int) -> str:
    """GoatTracker's note byte as a tracker cell."""
    if n == GT_ENDPATT:
        return "==="
    if n == GT_REST:
        return "..."
    if n == GT_KEYOFF:
        return "---"
    if n == GT_KEYON:
        return "+++"
    if GT_FIRST_NOTE <= n <= GT_LAST_NOTE:
        i = n - GT_FIRST_NOTE
        return "%s%d" % (NOTE_NAMES[i % 12], i // 12)
    return "?%02X" % n


def row_schedule(sng_path: Path, subtune: int, multiplier: int,
                 frames: int) -> dict | None:
    """The played rows of one subtune, per voice, with a frame for each.

    Walks the orderlist rather than dumping patterns in file order, because
    what a listener hears is the orderlist -- a pattern played four times is
    four passes here, and a pattern the orderlist never reaches does not
    appear at all.
    """
    try:
        import sys
        sys.path.insert(0, str(HERE))
        from songview import parse_sng
        song = parse_sng(sng_path.read_bytes())
    except Exception:
        return None
    if subtune * 3 + 2 >= len(song.tracks):
        return None

    npat = len(song.patterns)

    # A CMD_SETTEMPO below $80 sets ALL THREE channels (gplay.c:494), and
    # apply_tempo writes it into voice 0's entry pattern only -- so a per-voice
    # walk that tracked its own tempo left voices 1 and 2 on the fallback and
    # drifted them to half speed. Find the song tempo once, globally, first.
    song_tempo = None
    for v in range(3):
        for entry in song.tracks[subtune * 3 + v]:
            if entry >= npat:
                continue
            pat = song.patterns[entry]
            for i in range(0, len(pat) - 3, 4):
                if pat[i] == GT_ENDPATT:
                    break
                if pat[i + 2] == CMD_SETTEMPO_ and 3 <= pat[i + 3] <= 0x7F:
                    song_tempo = song_tempo or pat[i + 3]
                    break
            if song_tempo:
                break
        if song_tempo:
            break

    out = []
    for v in range(3):
        order = song.tracks[subtune * 3 + v]
        rows, frame, tempo, transpose = [], 0.0, song_tempo, 0
        for entry in order:
            if entry >= npat:                    # transpose / repeat / restart
                continue
            pat = song.patterns[entry]
            for i in range(0, len(pat) - 3, 4):
                note, instr, cmd, data = pat[i:i + 4]
                if note == GT_ENDPATT:
                    break
                if cmd == CMD_SETTEMPO_ and 3 <= data <= 0x7F:
                    tempo = data
                rows.append([round(frame), _note_name(note), instr, cmd, data,
                             entry, i // 4])
                frame += (tempo or 6) / max(1, multiplier)
                if frame > frames:
                    break
            if frame > frames:
                break
        out.append(rows)
    return {"voices": out, "multiplier": multiplier}


def panel_card(name: str, embed: bool) -> str:
    """The per-voice register panel, or "" when no trace was staged."""
    if embed or not (LISTEN / ("%s.trace.json" % name)).exists():
        return ""
    cols = ""
    for v in (1, 2, 3):
        rows = "".join(
            '<div class="vrow" data-v="%d" data-k="%s">'
            '<span class="live"></span><span class="lab">%s</span>'
            '<span class="val"></span>'
            '<span class="m o" title="the original"></span>'
            '<span class="m b" title="our conversion"></span></div>'
            % (v, key, label) for key, label in PANEL_ROWS)
        cols += ('<div class="vcol"><h3>Voice %d<span class="hz" '
                 'id="hz%d"></span></h3>%s</div>' % (v, v, rows))
    return (
        '<div class="card">\n  <h2>What the two sides use</h2>\n'
        '  <div class="panel">%s</div>\n'
        '  <div class="panelkey"><span><i class="oi"></i>the original uses it</span>'
        '<span><i class="bi"></i>our conversion uses it</span>'
        '<span><i class="li"></i>active at the playhead</span>'
        '<span>a row lit on one side only is a capability one player reaches '
        'and the other does not</span></div>\n'
        '  <p class="opts"><b>Hard sync and ring modulation are read by no '
        'column in FIDELITY.md</b>, so for those two rows this panel is the '
        'only place in the repo the two sides are compared at all. Counts are '
        'register writes over the traced window, not a score.</p>\n</div>\n'
        % cols)


def tracker_card(name: str) -> str:
    """GoatTracker's own pattern view of the subtune the WAVs are of."""
    trace_path = LISTEN / ("%s.trace.json" % name)
    sng_path = LISTEN / ("%s.h2g.sng" % name)
    if not (trace_path.exists() and sng_path.exists()):
        return ""
    try:
        tr = json.loads(trace_path.read_text(encoding="utf-8"))
    except Exception:
        return ""
    sched = row_schedule(sng_path, tr.get("sub_ours", 0),
                         tr.get("ours", {}).get("mult", 1),
                         tr.get("frames", 3000))
    if not sched:
        return ""

    cols, frames_js = "", []
    for v in range(3):
        rows = sched["voices"][v]
        frames_js.append([r[0] for r in rows])
        body = "".join(
            '<div class="trkrow%s" data-i="%d"><span class="ix">%03d</span>'
            '<span class="n">%s</span><span class="instr">%02X</span>'
            '<span class="cmd">%X%02X</span></div>'
            % (" note" if r[1] not in ("...", "===") else "", i, i % 1000,
               r[1], r[2], r[3], r[4])
            for i, r in enumerate(rows))
        cols += ('<div class="trkcol"><h3>Channel %d</h3>'
                 '<div class="trkhead"><span class="ix">row</span>'
                 '<span class="n">note</span><span class="instr">instr</span>'
                 '<span class="cmd">cmd</span></div>'
                 '<div class="trkbody" id="trk%d">%s</div></div>'
                 % (v + 1, v, body))

    return (
        '<div class="card">\n  <h2>The pattern, as we play it</h2>\n'
        '  <div class="trk">%s</div>\n'
        '  <script>window.__abRows = %s;</script>\n'
        '  <p class="trknote">Our conversion\u2019s subtune %d, the one both '
        'renders are of: note, instrument, command. It follows <b>our</b> '
        'render\u2019s clock, and the row timing is <b>derived</b> from the '
        'tempo written into the file \u2014 so if the view drifts against '
        'what you hear, the row rate is wrong, which is a finding rather '
        'than a display fault. <b>Click a row</b> to jump playback there and '
        'pause, so a row that looks wrong can be heard on its own instead of '
        'waiting for the loop to scroll back to it \u2014 or press '
        '<kbd>Space</kbd> to pause/resume wherever it already is.</p>\n</div>\n'
        % (cols, json.dumps(frames_js, separators=(",", ":")),
           tr.get("sub_ours", 0)))


# Cap on how many tick marks one strip draws. build/fidelity.json's densest
# corpus voice is in the hundreds; this keeps a pathological file from
# emitting thousands of <i> elements while the printed *count* stays exact
# regardless -- the cap only ever trims the drawing, never the number.
STRIP_MAX_TICKS = 400


def notes_strip_card(name: str, fj: dict | None) -> str:
    """A strip of tick marks per voice, original against ours, built only
    from what `build/fidelity.json` actually carries.

    That file has no per-note pitch/time sequence -- each voice's entry is
    an `orig_attacks`/`our_attacks` *count* plus the alphabetised *set* of
    distinct pitch classes either side used (`orig_pitches`/`our_pitches`),
    never a timeline. So this draws a density strip, not a piano roll: one
    mark per attack, in no particular order, which is the only per-note
    quantity the JSON has to offer -- and is exactly what FIDELITY.md's own
    aggregate `orig`/`ours` column is the three-voice sum of. Drawing it per
    voice is new; the counts themselves are not.
    """
    voices = (fj or {}).get("voices")
    if not voices:
        return ""
    cols = []
    total_o = total_u = 0
    for i, v in enumerate(voices):
        oc = int(v.get("orig_attacks") or 0)
        uc = int(v.get("our_attacks") or 0)
        total_o += oc
        total_u += uc
        o_ticks = '<i class="nt o"></i>' * min(oc, STRIP_MAX_TICKS)
        u_ticks = '<i class="nt u"></i>' * min(uc, STRIP_MAX_TICKS)
        op = ", ".join(v.get("orig_pitches") or []) or "&mdash;"
        up = ", ".join(v.get("our_pitches") or []) or "&mdash;"
        cols.append(
            '<div class="vstripcol"><h3>Voice %d</h3>'
            '<div class="strow"><span class="slab o">original</span>'
            '<span class="scount">%d</span>'
            '<div class="strip">%s</div></div>'
            '<div class="strow"><span class="slab u">ours</span>'
            '<span class="scount">%d</span>'
            '<div class="strip">%s</div></div>'
            '<p class="stpitch"><span class="k">pitches used</span>'
            'orig: %s<br>ours: %s</p></div>'
            % (i + 1, oc, o_ticks, uc, u_ticks, op, up))
    return (
        '<div class="card">\n  <h2>Notes per voice</h2>\n'
        '  <div class="vstrip">%s</div>\n'
        '  <p class="opts">One mark per note attack (capped at %d a row so a '
        'dense voice cannot blow out the page &mdash; the printed counts are '
        'never capped). Not a timeline: <code>build/fidelity.json</code> '
        'carries each voice’s attack <em>count</em> and the set of '
        'distinct pitches it used, never a per-note sequence, so this strip '
        'cannot say <b>which</b> mark is which note or where in time it '
        'falls. %d original / %d ours summed across all three voices '
        '&mdash; the same two totals FIDELITY.md’s '
        '<code>orig</code>/<code>ours</code> columns report for this file, '
        'from this same measurement run.</p>\n</div>\n'
        % ("".join(cols), STRIP_MAX_TICKS, total_o, total_u))


def voicewave_card(voice_map: dict) -> str:
    """Three stacked amplitude overlays, one per voice, drawn at once.

    The main *Both sides, drawn* canvas already follows the voice selector, so
    a single voice could always be seen -- one at a time, by switching, and
    with nothing to compare it against but memory. The question that actually
    gets asked of these pages is "WHICH voice is wrong", and that is a
    comparison across voices, not within one. Three strips on one time axis
    answer it by looking; switching back and forth does not.

    Each strip carries its own mean |difference|, which is the number that
    ranks them. Empty unless `listen.py --voices` staged the six solo renders.
    """
    if not voice_map or not all("v%d" % v in voice_map for v in (1, 2, 3)):
        return ""
    strips = "".join(
        '<div class="vw" data-voice="%d">'
        '<div class="vwhead">'
        '<button type="button" class="vwtoggle" data-strip="%d" '
        'aria-pressed="true" aria-label="Show or hide voice %d">'
        '<span class="cx"></span><b>Voice %d</b></button>'
        '<span class="stat" id="vwstat%d"></span></div>'
        '<canvas id="vwcv%d"></canvas></div>' % (v, v, v, v, v, v)
        for v in (1, 2, 3))
    return (
        '<div class="card wave voicewave">\n  <h2>Each voice, drawn</h2>\n'
        '  <div class="msg" id="vwmsg">Reading the six solo renders&hellip;</div>\n'
        '  <div class="vwrap" id="vwrap" hidden>%s</div>\n'
        '  <div class="legend">\n'
        '    <button type="button" class="swatch orig" data-vtrace="a" '
        'aria-pressed="true"><i></i>original</button>\n'
        '    <button type="button" class="swatch ours" data-vtrace="b" '
        'aria-pressed="true"><i></i>H2G</button>\n'
        '    <button type="button" class="swatch diff" data-vtrace="d" '
        'aria-pressed="true"><i></i>|difference|, lower strip</button>\n'
        '    <span>click a key to hide it in all three &middot; click a voice '
        'name to collapse it &middot; <b>scroll to zoom</b>, shared with the '
        'picture above so the two stay on one time axis &middot; click a '
        'strip to seek</span>\n'
        '  </div>\n'
        '  <p class="caveat">The voice whose <code>mean&nbsp;|&Delta;|</code> '
        'is worst is the one to solo with the buttons at the top and listen '
        'to, and the <b>lower strip under each voice</b> says <i>where</i> in '
        'the tune to listen: it is the same <code>|difference|</code> the '
        'combined picture carries, per voice, so a spike is a moment to click '
        'rather than a whole tune to sit through. Its height is the gap '
        'between the two envelopes at that instant, not a score, and it keeps '
        'counting toward <code>mean&nbsp;|&Delta;|</code> even when hidden. '
        'Same caveat as the combined picture: this is amplitude, so it '
        'shows dropped notes, note lengths and silence, and says nothing about '
        'pitch or timbre &mdash; two different notes of the same loudness draw '
        'the same shape. A voice the original never plays draws a flat line on '
        'both sides and scores 0%%, which is agreement, not absence of '
        'evidence.</p>\n</div>\n' % strips)


def instrmap_card(name: str, im: dict | None, seconds: int) -> str:
    """The instrument map's per-song verdict, keyed to what the ear should check.

    `instrmap.py` asks the question no other check here asks. Everything else
    reads the player's instrument *table* and reasons about what it means;
    this reads what the SID registers actually hold on the frame each note
    begins, both sides, joined on ADSR. So its buckets say where to point the
    ear:

      only original   an instrument the tune sounds and we never do -- the
                      loudest kind of miss, and audible as something absent
      only ours       a signature the original never produces: we invented it
      waveform differs both sides sound the instrument, with different timbre

    Empty string when no map has been generated: the file costs two emulations
    a song and is not built per commit, so its absence is normal rather than
    an error.
    """
    if not im:
        return ""
    total = im.get("instruments") or 0
    if not total:
        return ""
    matched = im.get("matched") or 0
    buckets = [
        ("waveform differs", im.get("waveform_mismatch") or 0,
         "both sides sound it, with a different waveform class"),
        ("only original", im.get("only_original") or 0,
         "the tune sounds it and we never do"),
        ("only ours", im.get("only_ours") or 0,
         "we sound something the original never does"),
        ("unused", im.get("unused") or 0,
         "in the table, sounded by neither side"),
    ]
    cells = ['<div><span class="k">matched</span><span class="v">%d of %d</span></div>'
             % (matched, total)]
    cells += ['<div><span class="k">%s</span><span class="v">%d</span></div>'
              % (label, n) for label, n, _ in buckets if n]
    legend = "".join("<li><b>%s</b> &mdash; %s</li>" % (label, why)
                     for label, n, why in buckets if n)
    window = (" over the first %ds" % seconds) if seconds else ""
    return (
        '<div class="card">\n  <h2>Instrument map</h2>\n'
        '  <div class="facts">%s</div>\n'
        '  %s\n'
        '  <p class="caveat"><b>This is the trace\'s view, not the '
        'converter\'s.</b> Every other instrument check in this project reads '
        'the player\'s own instrument table and argues about what it means; '
        'this one reads what the SID registers actually hold on the frame each '
        'note begins%s, in the original and in the conversion, matched on the '
        'ADSR pair. Where the two disagree the trace wins &mdash; and where we '
        'produce a signature the original never produces, we invented it. It '
        'compares waveform <i>class</i>, bucketed pulse width and the envelope; '
        'it does not judge pitch, and a count here is not a score. %s</p>\n</div>\n'
        % ("".join(cells), "<ul>%s</ul>" % legend if legend else "",
           window, _instrmap_link(name)))


def _instrmap_link(name: str) -> str:
    """The sentence pointing at the full per-instrument report.

    Links the copy inside `build/listen` rather than `../instrmap/<name>.html`:
    `abpage.py --serve` serves `build/listen` AS THE ROOT, so a parent-relative
    href escapes the served tree and 404s. Falls back to naming the Markdown
    path when no HTML twin was staged, which is what happens on a build that
    reused an older `instrmap.json` without re-running the tool.
    """
    if (LISTEN / ("%s.instrmap.html" % name)).exists():
        return ('Generated by <code>instrmap.py</code> &mdash; '
                '<a href="%s.instrmap.html">read the full per-instrument '
                'report</a>, one row per instrument with the original\'s '
                'per-frame behaviour beside ours.' % name)
    return ('Generated by <code>instrmap.py</code>; the per-instrument rows '
            'are in <code>build/instrmap/%s.md</code>.' % name)


def page(name: str, row: dict, notes: list[str], version: str,
         embed: bool, index_link: bool,
         survey: dict | None = None, preset: dict | None = None,
         fidjson: dict | None = None,
         instrmap: dict | None = None, instrmap_seconds: int = 0,
         approval: dict | None = None,
         now_shas: dict | None = None) -> str:
    """One tune's page.

    `now_shas` is `conversion_shas()` -- the sha256 each staged tune converts
    to RIGHT NOW. Two independent things read it: the human verdict (does the
    approval still cover this conversion) and the audio banner (was the `.wav`
    on this page rendered from this conversion). It used to be named
    `appr_shas` for the first of those; the rename is because the second reader
    is asked on every page, approved or not.
    """
    pretty = name.replace("_", " ")
    chips = "".join(
        '<div class="chip"><span>%s</span><b>%s</b></div>' % (k, row[k])
        for k in CHIPS if row.get(k) and row[k] != "-")
    if not chips:
        chips = ('<div class="chip"><span>not in FIDELITY.md</span>'
                 '<b>no row</b></div>')

    bullets = "".join("<li>%s</li>" % md(n) for n in notes) or (
        "<li>No notes were staged for this tune. Anything heard here is "
        "something no check in the repo can see &mdash; which is the reason "
        "this pass exists.</li>")

    a_rendered = wav_rendered(LISTEN / ("%s.original.wav" % name))
    b_rendered = wav_rendered(LISTEN / ("%s.h2g.wav" % name))

    if embed:
        a_src = wav_uri(LISTEN / ("%s.original.wav" % name))
        b_src = wav_uri(LISTEN / ("%s.h2g.wav" % name))
        provenance = ("Both renders are inlined in this page. Uncompressed "
                      "44.1&nbsp;kHz mono, same emulator, same settings.")
    else:
        a_src = "%s.original.wav" % name
        b_src = "%s.h2g.wav" % name
        provenance = ("Plays <code>%s.original.wav</code> and "
                      "<code>%s.h2g.wav</code> from this directory. If the "
                      "browser refuses <code>file://</code> media, serve the "
                      "directory over http instead." % (name, name))

    # Per-voice pairs, if `listen.py --voices` staged them beside the pair.
    # Never under --embed: six more ~10 MB data URIs is not a page.
    voice_map, voice_row = {}, ""
    if not embed:
        have = all((LISTEN / ("%s.v%d.%s.wav" % (name, v, side))).exists()
                   for v in (1, 2, 3) for side in ("original", "h2g"))
        if have:
            voice_map = {"all": [a_src, b_src]}
            for v in (1, 2, 3):
                voice_map["v%d" % v] = ["%s.v%d.original.wav" % (name, v),
                                        "%s.v%d.h2g.wav" % (name, v)]
            buttons = ('<button data-voice="all" aria-pressed="true">'
                       'All <kbd>4</kbd></button>')
            buttons += "".join(
                '<button data-voice="v%d" aria-pressed="false">'
                'Voice %d <kbd>%d</kbd></button>'
                % (v, v, v) for v in (1, 2, 3))
            voice_row = (
                '<div class="voices" id="voices">'
                '<span class="lbl">Solo</span>%s'
                '<span class="note" id="voicenote">all three voices, as '
                'staged</span></div>' % buttons)

    spec = spectrogram_payload(name)

    back = ('<a href="index.html">&larr; all tunes</a> &middot; ' if index_link else "")

    return """<meta charset="utf-8">
<title>%(pretty)s A/B</title>
<style>%(css)s</style>
<div class="wrap">
<header>
  <div class="eyebrow">%(back)sH2G listening pass &middot; %(version)s</div>
  <h1>%(pretty)s<small>original <code>.sid</code> against the H2G conversion, switched in place</small></h1>
  <div class="rail">%(chips)s</div>
</header>

%(staleaudio)s
%(approval)s

<div class="rig" id="rig">
  <div class="sources">
    <button class="src" data-side="a" aria-pressed="true">
      <span class="key">Source A &middot; press <kbd>A</kbd></span>
      <span class="name" id="nameA">Original .sid</span>
      <span class="rendered">%(a_rendered)s</span>
    </button>
    <button class="src" data-side="b" aria-pressed="false">
      <span class="key">Source B &middot; press <kbd>B</kbd></span>
      <span class="name" id="nameB">H2G conversion</span>
      <span class="rendered">%(b_rendered)s</span>
    </button>
  </div>
  <div class="transport">
    <button class="play" id="play" aria-label="Play">&#9654;</button>
    <div class="scrub">
      <input type="range" id="seek" min="0" max="1000" value="0" step="1" aria-label="Position">
      <div class="time"><span id="now">0:00</span><span id="dur">&ndash;:&ndash;&ndash;</span></div>
    </div>
  </div>
  <div class="loop">
    <label class="toggle"><input type="checkbox" id="looping"> Loop</label>
    <span>&middot; a passage you cannot decide on is worth hearing four times, not once</span>
  </div>
  <div class="sync">
    <span>Sync</span>
    <input type="range" id="syncr" min="-500" max="500" value="0" step="1"
           aria-label="Sync offset in milliseconds">
    <b id="syncv">0 ms</b>
    <button class="ghost" id="syncauto">auto</button>
    <button class="ghost" id="synczero">0</button>
    <span id="syncwhy">&mdash; the packed player reaches its first note a few frames after the original</span>
  </div>
  <div class="mode">
    <label class="toggle"><input type="checkbox" id="blind"> Blind &mdash; hide which is which</label>
    <button class="ghost" id="guessA" hidden>Left is the original</button>
    <button class="ghost" id="guessB" hidden>Right is the original</button>
    <span class="verdict" id="verdict"></span>
    <span class="tally" id="tally"></span>
  </div>
  %(voice_row)s
</div>

%(facts)s
%(panel)s
%(tracker)s
%(notes_strip)s
<div class="card wave">
  <h2>Both sides, drawn</h2>
  <div class="msg" id="wavemsg">Reading both renders&hellip;</div>
  <canvas id="wave" hidden></canvas>
  <div class="legend">
    <button type="button" class="swatch orig" data-trace="a" aria-pressed="true"><i></i>original</button>
    <button type="button" class="swatch ours" data-trace="b" aria-pressed="true"><i></i>H2G</button>
    <button type="button" class="swatch diff" data-trace="d" aria-pressed="true"><i></i>|difference|, lower strip</button>
    <span>click a key to hide it &middot; click to seek &middot; <b>scroll to zoom</b>, double-click to fit</span>
    <span class="stat" id="zoomstat">whole tune</span>
    <span class="stat" id="wavestat"></span>
  </div>
  <p class="caveat"><b>This is amplitude, and amplitude is not fidelity.</b>
  It shows dropped or extra notes, note lengths, missing drums, silence, and
  tempo drift &mdash; the two traces shear apart as the clocks part company.
  It cannot show <b>pitch</b>, <b>timbre</b> or <b>filter</b>: two completely
  different notes of the same loudness draw the same shape. The
  <code>mean&nbsp;|&Delta;|</code> beside the legend is the average gap
  between the two envelopes, not a score &mdash; read it only as "how far
  apart these pictures are".</p>
</div>

%(voicewave)s
%(spectrogram)s
<div class="card">
  <h2>What to listen for</h2>
  <ul>%(bullets)s</ul>
</div>
%(instrmap)s
<footer>
  <div><kbd>Space</kbd> play &middot; <kbd>R</kbd> restart &middot; <kbd>A</kbd>/<kbd>B</kbd> or <kbd>&larr;</kbd>/<kbd>&rarr;</kbd> switch source &middot; <kbd>1</kbd><kbd>2</kbd><kbd>3</kbd> solo a voice, <kbd>4</kbd> all &middot; <kbd>L</kbd> loop &middot; both tracks run in sync, so switching never loses your place.</div>
  <div>%(provenance)s</div>
</footer>
</div>
<audio id="au" preload="auto" src="%(a_src)s"></audio>
<audio id="bu" preload="auto" src="%(b_src)s"></audio>
<script>window.__abVoices = %(voice_map)s;
window.__abTrace = "%(trace_src)s";
window.__abSpectrogram = %(spectrogram_json)s;</script>
<script>%(script)s</script>
""" % dict(pretty=pretty, css=CSS, back=back, version=version, chips=chips,
           bullets=bullets, provenance=provenance, a_src=a_src, b_src=b_src,
           a_rendered=a_rendered, b_rendered=b_rendered,
           voice_row=voice_row, voice_map=json.dumps(voice_map),
           facts=facts_card(name, survey or {}, preset or {}),
           panel=panel_card(name, embed),
           tracker=tracker_card(name),
           notes_strip=notes_strip_card(name, fidjson),
           voicewave=voicewave_card(voice_map),
           instrmap=instrmap_card(name, instrmap, instrmap_seconds),
           approval=approval_badge(name, approval or {}, version, now_shas),
           staleaudio=audio_banner(name, now_shas),
           spectrogram=spectrogram_card(spec),
           spectrogram_json=json.dumps(spec) if spec else "null",
           trace_src="%s.trace.json" % name,
           script=SCRIPT)


def index(names: list[str], rows: dict, version: str,
          appr: dict | None = None, shas: dict | None = None) -> str:
    appr = appr or {}
    shas = shas or {}

    def verdict(n):
        """The human column. Three states, and `stale` is the one that matters:
        an approval whose conversion has changed since no longer covers what
        the page plays, and showing it as a plain yes would stop someone
        re-listening.

        Keyed on the `.sng`'s sha256, never on the version -- v0.5.370 and
        v0.5.371 touched only this file, which cannot change a byte of audio,
        and a version-keyed check called ACE_II stale for both.
        """
        a = appr.get(n)
        if not a or not a.get("approved"):
            return '<span class="n">&mdash;</span>'
        want, now_sha = a.get("sng_sha256"), shas.get(n)
        if want and now_sha and want != now_sha:
            return '<span class="s">stale</span>'
        return '<span class="y">approved</span>'

    def audio(n):
        """Whether the staged `.wav` came from the conversion shipping now.

        A separate column from the human verdict rather than folded into it,
        because they can disagree: an approval keyed on the conversion stays
        valid while the audio beside it was rendered from an older `.sng`.
        Reading one as the other is how a reader concludes that a page they
        have not re-staged is signed off.
        """
        state, _was, _now = audio_provenance(n, shas)
        if state == "behind":
            return '<span class="old">behind</span>'
        if state == "current":
            return '<span class="cur">current</span>'
        return '<span class="cur">&mdash;</span>'

    body = ""
    for n in names:
        r = rows.get(n, {})
        body += ("<tr><td><a href=\"%s.html\">%s</a></td><td class=\"appr\">%s</td>"
                 "<td class=\"aud\">%s</td>"
                 "<td>%s</td><td>%s</td><td>%s</td><td>%s</td></tr>"
                 % (n, n.replace("_", " "), verdict(n), audio(n),
                    r.get("melody", "&mdash;"),
                    r.get("gate", "&mdash;"), r.get("wave", "&mdash;"),
                    r.get("hold", "&mdash;")))
    return """<meta charset="utf-8">
<title>H2G Listening Pass</title>
<style>%(css)s</style>
<div class="wrap">
<header>
  <div class="eyebrow">H2G &middot; %(version)s &middot; %(count)d tune(s)</div>
  <h1>Listening pass<small>Each page plays the original and the conversion together and swaps which one you hear, so a switch never loses your place.</small></h1>
</header>
<div class="card">
  <h2>Staged tunes</h2>
  <div class="scroll"><table>
    <thead><tr><th>tune</th><th>human</th><th>audio</th><th>melody</th><th>gate</th><th>wave</th><th>hold</th></tr></thead>
    <tbody>%(body)s</tbody>
  </table></div>
</div>
<footer>
  <div>Columns are from <code>FIDELITY.md</code> at %(version)s. They compare what is played, never how it sounds &mdash; which is what these pages are for.</div>
  <div><b>human</b> is the only column here that is not a measurement: it is read from <code>approved.json</code>, which a person writes by hand and no tool may rewrite. <code>stale</code> means someone approved an earlier version and the conversion has changed since &mdash; the verdict does not cover what the page now plays.</div>
  <div><b>audio</b> compares the sha256 of the <code>.sng</code> each staged <code>.h2g.wav</code> was rendered from against what the tune converts to now. <code>behind</code> means the page plays an older conversion, whatever its other columns say &mdash; re-run <code>listen.py</code> for it. It is keyed on the conversion, never on the version: a version-keyed check would report every tune behind after any commit, including the ones that only touch this file.</div>
  <div><code>gate</code> is the newest of them and the least validated: it was built at v0.5.270 because no other column could see the register it reads, and no listener has confirmed it corresponds to anything audible.</div>
</footer>
</div>
""" % dict(css=CSS, version=version, count=len(names), body=body)


def prune_stale_pages(names: list[str]) -> list[Path]:
    """Delete pages this build no longer produces, and return what it deleted.

    A page (`<name>.html` or `<name>.embed.html`) outlives the staged pair it
    was built from: `listen.py` never deletes its own output, and until this
    function existed neither did this script -- a WAV pair removed from
    `LISTEN` left its page behind, still reachable by URL and still, if it
    predated the current build, potentially linked from a stale copy of
    `index.html` a reader had open. `LISTEN` holds nothing else with a
    `.html` suffix (`listen.py` stages `.wav`/`.trace.json`/`.md`, `.sng` and
    `.sid`; `Listen.ps1` is not html), so pruning "every `.html` here whose
    name is not `index.html` and whose page-name is not in `names`" removes
    exactly the pages a rebuild stopped producing -- never a staged pair,
    which carries no `.html` suffix to match, and never `index.html` itself,
    which the caller rewrites unconditionally right after this runs.
    """
    keep = set(names)
    removed: list[Path] = []
    if not LISTEN.exists():
        return removed
    for f in sorted(LISTEN.glob("*.html")):
        if f.name == "index.html":
            continue
        stem = f.stem                                  # strips one ".html"
        # `<name>.embed.html` and `<name>.instrmap.html` both belong to
        # `<name>`; strip either suffix before deciding, or a staged tune's
        # instrument report is deleted on the very next build that does not
        # pass --instrmap, and the card silently falls back to naming a path.
        for suffix in (".embed", ".instrmap"):
            if stem.endswith(suffix):
                stem = stem[: -len(suffix)]
                break
        base = stem
        if base not in keep:
            f.unlink()
            removed.append(f)
    return removed


def run_instrmap(sid_dir: str, names: list[str]) -> int:
    """Regenerate `build/instrmap.json` for exactly the staged tunes. 0 on success.

    Scoped to `names` rather than to the directory: `instrmap.py` traces two
    emulations a song, so pointing it at the whole corpus would cost roughly
    ninety times what a listening build needs. The tunes staged in
    `build/listen` are the ones whose pages are about to be written, and they
    are the only ones whose card anyone can read.

    A tune staged from somewhere other than `sid_dir` is reported and skipped
    rather than silently dropped -- the resulting page would simply lack the
    card, which is indistinguishable from a tune that had nothing to report.
    """
    import subprocess

    src = Path(sid_dir)
    if not src.is_dir():
        print("--instrmap: %s is not a directory" % src)
        return 2
    targets, missing = [], []
    for n in names:
        p = src / ("%s.sid" % n)
        (targets if p.exists() else missing).append(p if p.exists() else n)
    if missing:
        print("--instrmap: no .sid in %s for: %s" % (src, ", ".join(missing)))
    if not targets:
        print("--instrmap: nothing to map")
        return 2
    out = ROOT / "build" / "instrmap"
    jpath = ROOT / "build" / "instrmap.json"
    print("instrument map: tracing %d staged tune(s) -- two emulations each"
          % len(targets))
    # One instrmap process per tune, because its `target` is a file or a whole
    # directory and we want a subset of one. It appends nothing, so the JSON
    # has to be merged here rather than left to the last run to overwrite.
    merged: list[dict] = []
    seconds = 60
    for p in targets:
        cmd = [sys.executable, str(HERE / "instrmap.py"), str(p),
               "-o", str(out), "-t", str(seconds),
               "--presets", str(ROOT / "presets.json"),
               "--json", str(jpath)]
        r = subprocess.run(cmd, capture_output=True, text=True)
        if r.returncode != 0:
            print("  %s: instrmap failed (%d)" % (p.name, r.returncode))
            if r.stderr.strip():
                print("    %s" % r.stderr.strip().splitlines()[-1])
            continue
        try:
            doc = json.loads(jpath.read_text(encoding="utf-8"))
            merged += [s for s in doc.get("songs") or [] if isinstance(s, dict)]
        except (OSError, ValueError):
            print("  %s: instrmap wrote no readable json" % p.name)
    if not merged:
        print("--instrmap: every tune failed; leaving the previous map alone")
        return 2
    jpath.write_text(json.dumps({"seconds": seconds, "songs": merged}, indent=1),
                     encoding="utf-8")
    # Copy each HTML report INTO the served tree. `--serve` roots at
    # build/listen, so a link to ../instrmap/ leaves the served directory and
    # 404s -- and it would work when opened as a file:// path, which is the
    # worst kind of difference: right on the developer's machine, broken for
    # anyone handed the URL.
    import shutil
    staged = 0
    for p in targets:
        src = out / ("%s.html" % p.stem)
        if src.exists():
            shutil.copyfile(src, LISTEN / ("%s.instrmap.html" % p.stem))
            staged += 1
    print("  wrote %s (%d song(s)), %d report(s) copied beside the pages"
          % (jpath, len(merged), staged))
    return 0


def main() -> int:
    ap = argparse.ArgumentParser(prog="abpage")
    ap.add_argument("--embed", metavar="TUNE",
                    help="build one self-contained page with the audio inlined")
    ap.add_argument("-o", "--output", default=None,
                    help="where to write (--embed only; default beside the WAVs)")
    ap.add_argument("--instrmap", metavar="SID_DIR",
                    help="regenerate the instrument map for the staged tunes "
                         "from the originals in SID_DIR, then build the pages "
                         "with it. Costs two emulations per staged tune, so it "
                         "is opt-in rather than automatic -- but it is scoped "
                         "to what is STAGED, not to the corpus, which is what "
                         "makes it affordable in a listening build at all. "
                         "Without the flag the pages reuse whatever "
                         "build/instrmap.json already holds, and omit the card "
                         "if there is none.")
    ap.add_argument("--no-build", action="store_true",
                    help="with --serve, skip rebuilding the pages and serve "
                         "what is already staged. The build takes ~3.4s a tune "
                         "and runs BEFORE the port binds, so on a full corpus "
                         "the server appears dead for five minutes; the "
                         "launcher uses this. Rebuild with a plain run when "
                         "the pages are actually stale.")
    ap.add_argument("--serve", nargs="?", type=int, const=8730, default=None,
                    metavar="PORT",
                    help="after building, serve build/listen over http on "
                         "127.0.0.1 (default port 8730) and print the URL. "
                         "The envelope overlay and its automatic sync read "
                         "both WAVs with fetch(), which browsers refuse over "
                         "file://, so this is how the drawing works at all.")
    args = ap.parse_args()

    try:
        from h2g import __version__
        version = "v%s" % __version__
    except Exception:                                    # noqa: BLE001
        version = "unversioned"

    if not LISTEN.exists():
        print("no %s -- run listen.py first" % LISTEN)
        return 2

    # Serve straight away, before any of the build work below. The pages are on
    # disk already; rebuilding them is what made the launcher look hung, since
    # the port cannot bind until the build finishes.
    if args.no_build:
        if args.serve is None:
            print("--no-build only means anything with --serve")
            return 2
        pages = len(list(LISTEN.glob("*.html")))
        if not pages:
            print("no pages in %s -- run `python abpage.py` first" % LISTEN)
            return 2
        print("serving %d existing page(s); not rebuilding" % pages)
        return serve(args.serve)

    # `listen.py --voices` stages <name>.v1.original.wav beside the pair, and
    # those are the same tune with two voices muted -- not tunes of their own.
    # Globbing them in gave three extra "songs" per staged file, each with no
    # FIDELITY row and a page nobody wants.
    names = sorted(p.name[: -len(".original.wav")]
                   for p in LISTEN.glob("*.original.wav")
                   if not re.search(r"\.v[123]$", p.name[: -len(".original.wav")]))
    if not names:
        print("no staged pairs in %s -- run listen.py first" % LISTEN)
        return 2
    if args.instrmap:
        rc = run_instrmap(args.instrmap, names)
        if rc:
            return rc

    rows, notes = fidelity_rows(), listening_notes()
    survey, presets = survey_rows(), preset_rows()
    fidjson = fidelity_json_rows()
    imrows, imseconds = instrmap_rows()
    appr = approvals()
    # Unconditional now. It was `if appr else {}` while the only reader was the
    # approval badge; the audio banner asks it of every page, so gating it on
    # approvals existing would have left an unapproved tune silent about its
    # own audio -- which is the majority of them.
    now_shas = conversion_shas()
    behind = [n for n in names if audio_provenance(n, now_shas)[0] == "behind"]
    if behind:
        print("audio predates the current converter for %d of %d tune(s): %s"
              % (len(behind), len(names), ", ".join(behind)))
    if imrows:
        print("instrument map: %d song(s) at %ds" % (len(imrows), imseconds))
        missing = [n for n in names if n not in imrows]
        if missing:
            # Named rather than silent: a page without the card looks the same
            # as a page whose tune had nothing to report, and those are very
            # different things to a reader deciding what to listen for.
            print("  no map for: %s" % ", ".join(missing))

    if args.embed:
        if args.embed not in names:
            print("%s is not staged; have: %s" % (args.embed, ", ".join(names)))
            return 2
        html = page(args.embed, rows.get(args.embed, {}),
                    notes.get(args.embed, []), version,
                    embed=True, index_link=False,
                    survey=survey.get(args.embed, {}),
                    preset=presets.get(args.embed, {}),
                    fidjson=fidjson.get(args.embed, {}),
                    instrmap=imrows.get(args.embed, {}),
                    instrmap_seconds=imseconds, approval=appr,
                    now_shas=now_shas)
        out = Path(args.output) if args.output else LISTEN / ("%s.embed.html" % args.embed)
        out.write_text(html, encoding="utf-8")
        print("%s  %.2f MB" % (out, len(html) / 1e6))
        return 0

    for n in names:
        html = page(n, rows.get(n, {}), notes.get(n, []), version,
                    embed=False, index_link=True,
                    survey=survey.get(n, {}), preset=presets.get(n, {}),
                    fidjson=fidjson.get(n, {}),
                    instrmap=imrows.get(n, {}), instrmap_seconds=imseconds,
                    approval=appr, now_shas=now_shas)
        (LISTEN / ("%s.html" % n)).write_text(html, encoding="utf-8")
    pruned = prune_stale_pages(names)
    (LISTEN / "index.html").write_text(index(names, rows, version, appr, now_shas), encoding="utf-8")
    missing = [n for n in names if n not in rows]
    print("%d page(s) + index -> %s" % (len(names), LISTEN))
    if pruned:
        print("pruned %d stale page(s) for tunes no longer staged: %s"
              % (len(pruned), ", ".join(p.name for p in pruned)))
    if missing:
        print("no FIDELITY.md row for: %s" % ", ".join(missing))
    if args.serve is not None:
        return serve(args.serve)
    _ps1, cmd = write_launcher()
    print("%s -- double-click to serve and open" % cmd)
    print("file:// hides the overlay -- `python abpage.py --serve` to draw it")
    return 0


import http.server as _http_server


class _RangeHandler(_http_server.SimpleHTTPRequestHandler):
    """A static handler that honours HTTP Range. The stock one does not.

    `SimpleHTTPRequestHandler` ignores the `Range` header entirely: it answers
    every request with `200 OK` and the WHOLE file, and advertises no
    `Accept-Ranges`. For HTML that is merely wasteful. For a 2.6 MB WAV driving
    an `<audio>` element it is a bug with an audible symptom -- the media
    pipeline requests a byte range to seek or to refill, is handed the file
    from byte 0 again, and replays the opening seconds. That is the "it loops
    every couple of seconds" this project chased twice and misdiagnosed both
    times as a stale render; the WAV on disk measured clean each time
    (autocorrelation peaked at 0.59, nowhere near the ~1.0 a real loop gives),
    because the file was never the problem.

    It is also why an automated browser's `readyState` sat at 0 forever
    earlier in this project's history, which was written off as an environment
    limitation. It was this.

    Two changes and no more: advertise and implement single-range requests,
    and speak HTTP/1.1 so a keep-alive connection is available. Multi-range
    (`bytes=0-99,200-299`) is not implemented -- no browser uses it for media
    -- and is answered as a normal 200 rather than wrongly.
    """

    protocol_version = "HTTP/1.1"

    def send_head(self):
        rng = self.headers.get("Range")
        if not rng:
            return super().send_head()
        path = self.translate_path(self.path)
        if os.path.isdir(path):
            return super().send_head()
        m = re.fullmatch(r"bytes=(\d*)-(\d*)", rng.strip())
        if not m or (not m.group(1) and not m.group(2)):
            return super().send_head()          # unsatisfiable shape: 200
        try:
            f = open(path, "rb")
        except OSError:
            self.send_error(404, "File not found")
            return None
        try:
            size = os.fstat(f.fileno()).st_size
            first, last = m.group(1), m.group(2)
            if first:
                start = int(first)
                end = int(last) if last else size - 1
            else:                                # "bytes=-N": the final N bytes
                start = max(0, size - int(last))
                end = size - 1
            end = min(end, size - 1)
            if start >= size or start > end:
                self.send_response(416)
                self.send_header("Content-Range", "bytes */%d" % size)
                self.send_header("Content-Length", "0")
                self.end_headers()
                f.close()
                return None
            self.send_response(206)
            self.send_header("Content-type", self.guess_type(path))
            self.send_header("Accept-Ranges", "bytes")
            self.send_header("Content-Range",
                             "bytes %d-%d/%d" % (start, end, size))
            self.send_header("Content-Length", str(end - start + 1))
            self.send_header("Last-Modified", self.date_time_string(
                os.fstat(f.fileno()).st_mtime))
            self.end_headers()
            f.seek(start)
            # copyfile() would send to EOF; hand back only the slice asked for.
            return _Slice(f, end - start + 1)
        except Exception:
            f.close()
            raise

    def send_response(self, code, message=None):
        # Advertise range support on every response EXCEPT the 206, which sets
        # the header itself -- a flag rather than scanning the header buffer,
        # which is a list of bytes and cannot be searched for a str.
        super().send_response(code, message)
        if code != 206:
            self.send_header("Accept-Ranges", "bytes")

    def log_message(self, fmt, *args):        # keep the console readable
        pass


class _Slice:
    """A read-only file view of exactly `remaining` bytes, for copyfile()."""

    def __init__(self, fh, remaining):
        self._fh, self._left = fh, remaining

    def read(self, n=-1):
        if self._left <= 0:
            return b""
        if n is None or n < 0 or n > self._left:
            n = self._left
        chunk = self._fh.read(n)
        self._left -= len(chunk)
        return chunk

    def close(self):
        self._fh.close()


def serve(port: int) -> int:
    """Serve build/listen on 127.0.0.1 until interrupted.

    A page opened as a file:// URL plays fine but cannot *draw*: the overlay
    and the automatic sync both read the two WAVs with fetch(), and browsers
    refuse those reads on file://. Rather than leave that as a message telling
    the reader to go and find a web server, the tool is the web server. Bound
    to the loopback interface, because nothing here is meant to leave the
    machine.
    """
    import functools
    import http.server

    handler = functools.partial(_RangeHandler, directory=str(LISTEN))
    try:
        httpd = http.server.ThreadingHTTPServer(("127.0.0.1", port), handler)
    except OSError as exc:
        print("cannot bind 127.0.0.1:%d -- %s" % (port, exc))
        return 2
    print("http://127.0.0.1:%d/index.html   (ctrl-c to stop)" % port)
    try:
        httpd.serve_forever()
    except KeyboardInterrupt:
        print()
        print("stopped")
    finally:
        httpd.server_close()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
