"""Render a Goattracker `.sng` as a browsable HTML page.

The repo has no shortage of *measurement* -- `FIDELITY.md` scores nineteen
register dimensions, `fidelity.py --diagnose` attributes a low score to a
voice, `instrmap.py` joins both sides' traces on ADSR. What it has had no way
to do is *look at the file*. Goattracker's editor can, but it shows a
wavetable as a narrow column of hex pairs and a pattern sixteen rows at a
time, so answering "which entry is instrument 3 opening on, and what does that
byte mean" costs a dozen keystrokes and a page of held state.

This decodes the whole file instead. It judges nothing and scores nothing --
which is the point. Every metric this project has added could be, and several
were, silently wrong in a way that changed a decision; a renderer of bytes
that are already on disk has no such failure mode.

Three things it does that the editor cannot:

* **Every pattern carries all three of its identities.** Goattracker numbers
  patterns in *hex*, the converter's intermediate index is post-dedup, and the
  orderlist transposes on top -- so a listener's "PATT.12" is pattern 18 is
  Hubbard's 15, and H2G-CONVERSION-METHOD.md records three separate debugging
  attempts lost to exactly that. Printing all three retires it.
* **Wavetable entries carry cumulative timing.** A delay entry is current for
  `value + 1` play calls (gplay.c:697-704), not `value`, and reading it the
  other way left every multispeed file's attack a call too long from v0.5.82
  to v0.5.130. Showing "covers calls 5-7" rather than `02 80` makes that
  arithmetic visible instead of remembered.
* **Instruments carry their provenance.** `_write_instruments` names each
  record `{n:02X}:{b5:02X}-{b6:02X}-{b7:02X}`, and byte 7 is the player's
  effect byte -- so the `.sng` alone says which effect bits the source record
  set, and this decodes them.

Usage:
    python songview.py song.sng -o out.html
    python songview.py song.sid -o out.html --presets ../presets.json
"""

from __future__ import annotations

import argparse
import html
import sys
from dataclasses import dataclass, field
from pathlib import Path
from typing import Dict, List, Optional, Tuple

sys.path.insert(0, str(Path(__file__).resolve().parent))

from h2g.goatwriter import (  # noqa: E402
    FIELD_LEN, GT_FIRST_NOTE, GT_LAST_NOTE, GT_REST, HEADER_LEN,
    WAVE_MAX_DELAY, WAVECMD_PORTADOWN, WAVECMD_PORTAUP,
)
from h2g.patterns import (  # noqa: E402
    GT_END_PATTERN, GT_ORDER_RESTART, GT_REPEAT, GT_TRANSPOSE_DOWN,
    GT_TRANSPOSE_UP,
)

# gcommon.h's command numbering, in order. Index is the pattern row's command
# column; the text is what gplay.c does with it.
COMMANDS = [
    ("---", "no command"),
    ("PORTAUP", "pitch up at speed-table entry {d}"),
    ("PORTADOWN", "pitch down at speed-table entry {d}"),
    ("TONEPORTA", "slide to the note at speed-table entry {d}"),
    ("VIBRATO", "vibrato at speed-table entry {d}"),
    ("SETAD", "attack/decay := ${d:02X}"),
    ("SETSR", "sustain/release := ${d:02X}"),
    ("SETWAVE", "waveform := ${d:02X}"),
    ("SETWAVEPTR", "wavetable pointer := ${d:02X}"),
    ("SETPULSEPTR", "pulse pointer := ${d:02X}"),
    ("SETFILTERPTR", "filter pointer := ${d:02X}"),
    ("SETFILTERCTRL", "filter control := ${d:02X}"),
    ("SETCUTOFF", "cutoff := ${d:02X}"),
    ("SETMASTERVOL", "master volume := ${d:02X}"),
    ("FUNKTEMPO", "funktempo, speed-table entry {d}"),
    ("SETTEMPO", "tempo := {d} play calls per row"),
]

NOTE_NAMES = ["C-", "C#", "D-", "D#", "E-", "F-", "F#", "G-", "G#", "A-",
              "A#", "B-"]

# The player's effect byte, as `_write_instruments` embeds it in the
# instrument name. Each bit is a mechanism section 7 of
# H2G-CONVERSION-METHOD.md reads out of the 6502.
EFFECT_BITS = [
    (0x01, "drum", "per-frame drum sweep"),
    (0x02, "$02", "unread"),
    (0x04, "two-stage", "attack waveform stage"),
    (0x08, "program", "byte-code wave program pointer"),
    (0x10, "arpeggio", "three-step pitch sequence"),
    (0x20, "filter", "filter cutoff sweep"),
    (0x40, "fixed-pitch", "fixed attack pitch from the note table"),
    (0x80, "sfx-drum", "fixed-pitch noise hit"),
]


def note_name(value: int) -> str:
    """A pattern note byte as a name, or a marker for the two special values."""
    if value == GT_END_PATTERN:
        return "END"
    if value == GT_REST:
        return "..."
    if GT_FIRST_NOTE <= value <= GT_LAST_NOTE:
        n = value - GT_FIRST_NOTE
        return f"{NOTE_NAMES[n % 12]}{n // 12}"
    return f"${value:02X}"


@dataclass
class Instrument:
    number: int
    ad: int
    sr: int
    wave_ptr: int
    pulse_ptr: int
    filt_ptr: int
    vib_ptr: int
    vib_delay: int
    gatetimer: int
    firstwave: int
    name: str

    @property
    def adsr(self) -> str:
        return f"${self.ad:02X}{self.sr:02X}"

    @property
    def effect_byte(self) -> Optional[int]:
        """The source record's `+7`, recovered from the generated name.

        `_write_instruments` writes `NN:b5-b6-b7`; anything else (the hardcoded
        "Clear Voice" placeholder, or a hand-edited file) yields None rather
        than a guess.
        """
        try:
            head, _, tail = self.name.partition(":")
            int(head, 16)
            parts = tail.split("-")
            if len(parts) != 3:
                return None
            return int(parts[2], 16)
        except ValueError:
            return None

    @property
    def effects(self) -> List[Tuple[str, str]]:
        eff = self.effect_byte
        if not eff:
            return []
        return [(n, why) for bit, n, why in EFFECT_BITS if eff & bit]


@dataclass
class Song:
    fmt: str
    name: str
    author: str
    released: str
    subtunes: int
    tracks: List[List[int]]
    instruments: List[Instrument]
    tables: Dict[str, List[Tuple[int, int]]]
    patterns: List[List[int]] = field(default_factory=list)


def parse_sng(blob: bytes) -> Song:
    """Every structure in a `.sng`, in the order `goatwriter.build_sng` writes.

    Deliberately a separate reader rather than a re-use of the writer's
    internals: a parser that shares code with the thing it checks cannot
    disagree with it, and disagreeing is the whole value.
    """
    fmt = blob[0:4].decode("ascii", "replace")
    if fmt not in ("GTS2", "GTS5"):
        raise ValueError(f"not a Goattracker song: magic {blob[0:4]!r}")

    def field_at(off: int) -> str:
        return blob[off:off + FIELD_LEN].split(b"\x00")[0].decode(
            "latin-1", "replace").strip()

    pos = HEADER_LEN
    subtunes = blob[pos]
    pos += 1
    tracks = []
    for _ in range(subtunes * 3):
        n = blob[pos]
        pos += 1
        tracks.append(list(blob[pos:pos + n + 1]))
        pos += n + 1

    ninstr = blob[pos]
    pos += 1
    instruments = []
    for i in range(ninstr):
        rec = blob[pos:pos + 25]
        pos += 25
        instruments.append(Instrument(
            number=i + 1, ad=rec[0], sr=rec[1], wave_ptr=rec[2],
            pulse_ptr=rec[3], filt_ptr=rec[4], vib_ptr=rec[5],
            vib_delay=rec[6], gatetimer=rec[7], firstwave=rec[8],
            name=rec[9:25].split(b"\x00")[0].decode("latin-1", "replace").strip(),
        ))

    names = ["WTBL", "PTBL", "FTBL"] + (["STBL"] if fmt == "GTS5" else [])
    tables: Dict[str, List[Tuple[int, int]]] = {}
    for tname in names:
        n = blob[pos]
        pos += 1
        left = blob[pos:pos + n]
        right = blob[pos + n:pos + 2 * n]
        pos += 2 * n
        tables[tname] = list(zip(left, right))

    npatt = blob[pos]
    pos += 1
    patterns = []
    for _ in range(npatt):
        rows = blob[pos]
        pos += 1
        patterns.append(list(blob[pos:pos + rows * 4]))
        pos += rows * 4

    return Song(fmt=fmt, name=field_at(0x04), author=field_at(0x24),
                released=field_at(0x44), subtunes=subtunes, tracks=tracks,
                instruments=instruments, tables=tables, patterns=patterns)


def decode_orderlist(track: List[int]) -> List[Tuple[str, str, str]]:
    """(kind, what, note) per orderlist byte, with transpose state carried."""
    out: List[Tuple[str, str, str]] = []
    trans, repeat, operand = 0, 1, False
    for b in track:
        if operand:
            out.append(("restart", f"${b:02X}", f"loop to position {b}"))
            operand = False
        elif b == GT_ORDER_RESTART:
            out.append(("restart", "RST", "restart position follows"))
            operand = True
        elif GT_TRANSPOSE_DOWN <= b < GT_ORDER_RESTART:
            trans = b - GT_TRANSPOSE_UP
            out.append(("transpose", f"{trans:+d}",
                        f"every following pattern transposed {trans:+d}"))
        elif GT_REPEAT <= b < GT_TRANSPOSE_DOWN:
            repeat = b - GT_REPEAT + 1
            out.append(("repeat", f"x{repeat}",
                        f"the next pattern plays {repeat} times"))
        else:
            note = f"pattern ${b:02X} ({b})"
            if trans:
                note += f", transposed {trans:+d}"
            if repeat > 1:
                note += f", played {repeat} times"
            out.append(("pattern", f"${b:02X}", note))
            repeat = 1
    return out


def decode_wave_entry(left: int, right: int) -> Tuple[str, str, int]:
    """(kind, meaning, calls this entry occupies) for one wavetable step.

    The call count is the thing worth having: a delay entry is current for
    `value + 1` play calls (gplay.c:697-704), every other entry for exactly
    one, and reading that off by one is a mistake this repo has shipped.
    """
    if left == 0xFF:
        return ("jump", f"jump to entry {right}" if right else "stop", 0)
    if left == 0xFE:
        return ("jump", "stop", 0)
    if 1 <= left <= WAVE_MAX_DELAY:
        return ("delay", f"hold for {left + 1} calls", left + 1)
    if left == WAVECMD_PORTAUP:
        return ("command", f"pitch up, speed-table entry {right}", 1)
    if left == WAVECMD_PORTADOWN:
        return ("command", f"pitch down, speed-table entry {right}", 1)
    if 0xF0 <= left <= 0xFD:
        return ("command", f"command ${left:02X}, operand ${right:02X}", 1)
    bits = []
    for bit, nm in ((0x80, "noise"), (0x40, "pulse"), (0x20, "saw"),
                    (0x10, "tri")):
        if left & bit:
            bits.append(nm)
    wave = "+".join(bits) or "none"
    gate = "gate on" if left & 0x01 else "gate off"
    if left & 0x08:
        gate += ", testbit"
    if right == 0x00:
        pitch = "the pattern's note"
    elif right < 0x60:
        pitch = f"note {right:+d} semitones"
    elif right < 0x80:
        pitch = f"note {right - 0x80:+d} semitones"
    else:
        pitch = f"absolute {note_name(right - 0x80 + GT_FIRST_NOTE)}"
    return ("wave", f"{wave}, {gate} - {pitch}", 1)


def wave_program(song: Song, start: int, limit: int = 64):
    """The wavetable entries an instrument runs, from its pointer to its stop.

    Returns (index, left, right, kind, meaning, first call, last call) with the
    call numbers accumulated, so an instrument's attack can be read against a
    trace without doing the arithmetic by hand. Stops at the jump, and bounds
    the walk so a malformed table cannot loop forever.
    """
    wtbl = song.tables.get("WTBL", [])
    out = []
    call = 0
    idx = start
    seen = set()
    while 1 <= idx <= len(wtbl) and len(out) < limit and idx not in seen:
        seen.add(idx)
        left, right = wtbl[idx - 1]
        kind, meaning, calls = decode_wave_entry(left, right)
        first = call + 1
        last = call + calls
        out.append((idx, left, right, kind, meaning, first, last))
        call += calls
        if kind == "jump":
            break
        idx += 1
    return out


CSS = """
:root{--bg:#fbfaf8;--fg:#22201d;--dim:#6b6560;--line:#e0dcd6;--panel:#fff;
--accent:#8a5a2b;--warn:#a3341f;--ok:#2f6b3a;--code:#f2efe9;}
:root:not([data-theme="light"]){@media (prefers-color-scheme:dark){
:root{--bg:#171614;--fg:#e8e4de;--dim:#9a938b;--line:#332f2a;--panel:#1e1d1a;
--accent:#d69a5c;--warn:#e0725a;--ok:#7db98a;--code:#232120;}}}
@media (prefers-color-scheme:dark){:root:not([data-theme="light"]){
--bg:#171614;--fg:#e8e4de;--dim:#9a938b;--line:#332f2a;--panel:#1e1d1a;
--accent:#d69a5c;--warn:#e0725a;--ok:#7db98a;--code:#232120;}}
:root[data-theme="dark"]{--bg:#171614;--fg:#e8e4de;--dim:#9a938b;
--line:#332f2a;--panel:#1e1d1a;--accent:#d69a5c;--warn:#e0725a;--ok:#7db98a;
--code:#232120;}
*{box-sizing:border-box;}
body{margin:0;background:var(--bg);color:var(--fg);
font:14px/1.5 ui-sans-serif,system-ui,-apple-system,"Segoe UI",sans-serif;}
.wrap{max-width:1180px;margin:0 auto;padding:28px 20px 80px;}
h1{font-size:23px;margin:0 0 2px;letter-spacing:-.01em;}
h2{font-size:17px;margin:38px 0 10px;padding-bottom:6px;
border-bottom:1px solid var(--line);letter-spacing:-.01em;}
h3{font-size:14px;margin:22px 0 8px;color:var(--accent);}
.sub{color:var(--dim);margin:0 0 18px;font-size:13px;}
code,.mono{font-family:ui-monospace,"SF Mono",Menlo,Consolas,monospace;
font-size:12.5px;}
table{border-collapse:collapse;width:100%;margin:6px 0 14px;}
.scroll{overflow-x:auto;}
th,td{text-align:left;padding:4px 9px;border-bottom:1px solid var(--line);
vertical-align:top;white-space:nowrap;}
th{color:var(--dim);font-weight:600;font-size:11.5px;text-transform:uppercase;
letter-spacing:.04em;}
tbody tr:hover{background:var(--code);}
.num{text-align:right;}
.dim{color:var(--dim);}
.warn{color:var(--warn);font-weight:600;}
.ok{color:var(--ok);}
/* A disagreeing row in the comparison. Sorting them first is the ordering;
   this is what makes one legible once the reader has scrolled. Border rather
   than a background so it survives both themes at the same weight. */
tr.flag td{border-left:0;box-shadow:inset 2px 0 0 var(--warn);}
tr.flag td:last-child{color:var(--warn);font-weight:600;}
.tag{display:inline-block;padding:1px 6px;margin:0 3px 2px 0;border-radius:9px;
background:var(--code);border:1px solid var(--line);font-size:11px;
color:var(--accent);}
.card{background:var(--panel);border:1px solid var(--line);border-radius:8px;
padding:12px 14px;margin:10px 0;}
.grid{display:grid;grid-template-columns:repeat(auto-fit,minmax(215px,1fr));
gap:10px;}
.kv{display:flex;justify-content:space-between;gap:12px;padding:2px 0;
border-bottom:1px solid var(--line);font-size:12.5px;}
.kv:last-child{border:0;}
.kv span:first-child{color:var(--dim);}
a{color:var(--accent);}
.note{color:var(--fg);font-weight:600;}
.rest{color:var(--dim);}
details{margin:8px 0;}
summary{cursor:pointer;color:var(--accent);font-size:13px;padding:3px 0;}
.pat{display:inline-block;vertical-align:top;margin:0 14px 14px 0;}
.pat table{width:auto;min-width:290px;}
.legend{font-size:12px;color:var(--dim);margin:4px 0 12px;}
"""


def pair_by_adsr(orig_keys, our_keys) -> List[Tuple[Optional[int], Optional[int], str]]:
    """`[(original key, our key, how)]`, pairing instruments across the sides.

    **The release nibble is in the key, and `--cut-release` changes it.** Those
    players kill the envelope at a note's end, so we emit 0 for a release that
    never acts -- and the same instrument then carries two ADSR values, the
    original's `$295F` against our `$2950`. Keyed on the whole pair it appears
    twice, once as "ours only" and once as "original only": two false flags for
    one instrument that agrees, which is what this page showed on Commando the
    first time it ran. `onset_agreement` compares only the *intersection* of
    the keys, so the column silently drops such a pair instead; for a page
    whose job is to show what happened, dropping is worse than pairing.

    So: exact ADSR first, then one pass over what is left matching on
    AD+sustain (`& $FFF0`), and **only where that is unambiguous on both
    sides** -- exactly one unmatched candidate each. Guessing which of two
    instruments a trace heard is the wrong-work-list-entry that
    `fidelity.instrument_stamps` refuses to make for the same reason. Rows
    paired that way are marked, because a pairing rule is a claim.

    This is the `tail` column's lesson in the other axis: an attribution key
    must not contain the quantity being attributed.
    """
    a, b = set(orig_keys), set(our_keys)
    pairs = [(k, k, "adsr") for k in sorted(a & b)]
    left_only, right_only = sorted(a - b), sorted(b - a)
    for k in list(left_only):
        cands = [j for j in right_only if (j & 0xFFF0) == (k & 0xFFF0)]
        mine = [j for j in left_only if (j & 0xFFF0) == (k & 0xFFF0)]
        if len(cands) == 1 and len(mine) == 1:
            pairs.append((k, cands[0], "ad+s"))
            left_only.remove(k)
            right_only.remove(cands[0])
    pairs += [(k, None, "adsr") for k in left_only]
    pairs += [(None, k, "adsr") for k in right_only]
    return sorted(pairs, key=lambda t: t[0] if t[0] is not None else t[1])


@dataclass
class InstrumentDelta:
    """One instrument as the original plays it and as we do.

    Keyed by the ADSR pair for `fidelity.onset_shapes`' reason: it is a verbatim
    per-instrument copy of the source record, so it identifies an instrument
    where a waveform cannot (several share one) and a pulse width cannot (a
    swept one has no single value).
    """
    number: Optional[int]
    adsr: int
    effect: Optional[int]
    declares: Optional[int]
    orig_shape: Optional[tuple]
    our_shape: Optional[tuple]
    orig_notes: int
    our_notes: int
    kind: str
    paired: str = "adsr"        # "adsr", or "ad+s" where the release differs

    @property
    def flagged(self) -> bool:
        return self.kind != "match"


def compare_sides(sid_path: Path, blob: bytes, *, seconds: int = 60,
                  multiplier: int = 1, subtune=None,
                  gt2reloc: Optional[str] = None,
                  siddump: Optional[str] = None) -> List[InstrumentDelta]:
    """Both sides' opening frames per instrument, for the overlay.

    **Built on `fidelity.onset_shapes` rather than beside it.** That function
    is what the `onset` column and the census both read, so a row here cannot
    quietly disagree with the number in `FIDELITY.md` about what an instrument
    opens on -- and `fidelity.classify_onset` supplies the same `match` /
    `phase` / `short` / `flat` / `invented` / `partial` / `wrong` vocabulary the
    census groups by. A second implementation would have been a second thing to
    be wrong.

    What it adds that neither has: the **declared** opening waveform, read out
    of the `.sng` we shipped. A row can therefore separate "the wavetable says
    the wrong thing" from "the wavetable is right and the player reaches it a
    frame late", which is the distinction section 7.www turned on and which no
    column can draw.

    An instrument the original sounds and we have no record for appears with
    `number` None rather than being dropped, the same rule `instrmap.py` uses.
    """
    import shutil                                    # noqa: PLC0415
    import fidelity as F                             # noqa: PLC0415
    from h2g.sidfile import find_freq_table, load_sid  # noqa: PLC0415

    workdir, owned = F.make_workdir()
    try:
        local = workdir / "o.sid"
        shutil.copyfile(sid_path, local)
        sub = F.resolve_subtune(sid_path, "auto") if subtune is None else subtune
        # The original is traced on its own tuning and ours always on
        # Goattracker's -- four corpus files carry a table off the semitone
        # grid, and tracing them at 0 renames every note.
        ft = find_freq_table(load_sid(str(sid_path)))
        cal = F.calibration(ft.detune) if ft and abs(ft.detune) > 0.2 else 0
        orig = F.run_siddump(local, seconds, sub, siddump or F.SIDDUMP, cal)

        packed_blob, _ = F.legalise_restarts(blob)
        packed = F.pack_sid(packed_blob, workdir, gt2reloc or F.GT2RELOC,
                            multiplier)
        if packed is None:
            raise RuntimeError("gt2reloc wrote no .sid for this song")
        ours = F.run_siddump(packed, seconds, sub, siddump or F.SIDDUMP,
                             calls=multiplier)

        nframes = seconds * 50
        a = F.onset_shapes(orig, nframes)
        b = F.onset_shapes(ours, nframes)
    finally:
        if owned:
            shutil.rmtree(workdir, ignore_errors=True)

    song = parse_sng(blob)
    by_adsr = {}
    for ins in song.instruments:
        by_adsr.setdefault((ins.ad << 8) | ins.sr, ins)

    pairs = pair_by_adsr(a, b)

    out: List[InstrumentDelta] = []
    for o_key, u_key, how in pairs:
        adsr = u_key if u_key is not None else o_key
        ins = by_adsr.get(adsr) or (by_adsr.get(o_key) if o_key else None)
        o = a[o_key].most_common(1)[0][0] if o_key is not None else None
        u = b[u_key].most_common(1)[0][0] if u_key is not None else None
        if o is not None and u is not None:
            kind = F.classify_onset(o, u)
        elif o is None:
            kind = "ours only"
        else:
            kind = "original only"
        declares = None
        if ins is not None:
            prog = wave_program(song, ins.wave_ptr)
            for _, left, _r, k, _m, _s, _e in prog:
                if k == "wave":
                    declares = left
                    break
        out.append(InstrumentDelta(
            number=ins.number if ins else None, adsr=adsr,
            effect=ins.effect_byte if ins else None, declares=declares,
            orig_shape=o, our_shape=u,
            orig_notes=sum(a[o_key].values()) if o_key is not None else 0,
            our_notes=sum(b[u_key].values()) if u_key is not None else 0,
            kind=kind, paired=how))
    # Flagged first, and within each group by instrument number: the reason to
    # open this page is the disagreements, and an alphabetical table buries
    # three of them under twenty that agree.
    out.sort(key=lambda d: (not d.flagged, d.number if d.number else 999))
    return out


def esc(s) -> str:
    return html.escape(str(s))


def _instrument_cards(song: Song) -> str:
    rows = []
    for ins in song.instruments:
        prog = wave_program(song, ins.wave_ptr)
        tags = "".join(
            f'<span class="tag" title="{esc(why)}">{esc(n)}</span>'
            for n, why in ins.effects)
        eff = ins.effect_byte
        effhex = f"${eff:02X}" if eff is not None else "-"
        wrows = "".join(
            f"<tr><td class='num mono'>{i}</td>"
            f"<td class='mono'>{l:02X} {r:02X}</td>"
            f"<td class='dim'>{esc(kind)}</td><td>{esc(meaning)}</td>"
            f"<td class='num mono dim'>{(str(a) if a == b else f'{a}-{b}') if kind != 'jump' else ''}</td></tr>"
            for i, l, r, kind, meaning, a, b in prog)
        used = "" if prog else "<tr><td colspan='5' class='dim'>no wavetable program</td></tr>"
        rows.append(f"""
<div class="card" id="ins{ins.number}">
  <h3>Instrument {ins.number} &mdash; <span class="mono">{esc(ins.name)}</span> {tags}</h3>
  <div class="grid">
    <div>
      <div class="kv"><span>ADSR</span><span class="mono">{ins.adsr}</span></div>
      <div class="kv"><span>attack/decay</span><span class="mono">${ins.ad:02X}</span></div>
      <div class="kv"><span>sustain/release</span><span class="mono">${ins.sr:02X}</span></div>
      <div class="kv"><span>effect byte (+7)</span><span class="mono">{effhex}</span></div>
    </div>
    <div>
      <div class="kv"><span>wave ptr</span><span class="mono">${ins.wave_ptr:02X}</span></div>
      <div class="kv"><span>pulse ptr</span><span class="mono">${ins.pulse_ptr:02X}</span></div>
      <div class="kv"><span>filter ptr</span><span class="mono">${ins.filt_ptr:02X}</span></div>
      <div class="kv"><span>speed/vib ptr</span><span class="mono">${ins.vib_ptr:02X}</span></div>
    </div>
    <div>
      <div class="kv"><span>vib delay</span><span class="mono">${ins.vib_delay:02X}</span></div>
      <div class="kv"><span>gate timer</span><span class="mono">${ins.gatetimer:02X}</span></div>
      <div class="kv"><span>first wave</span><span class="mono">${ins.firstwave:02X}</span></div>
      <div class="kv"><span>program length</span><span class="mono">{len(prog)}</span></div>
    </div>
  </div>
  <div class="scroll"><table>
    <thead><tr><th>#</th><th>bytes</th><th>kind</th><th>meaning</th><th>calls</th></tr></thead>
    <tbody>{wrows}{used}</tbody>
  </table></div>
</div>""")
    return "".join(rows)


def _comparison_section(deltas: List[InstrumentDelta]) -> str:
    import fidelity as F                             # noqa: PLC0415

    def shape(x):
        return f"<span class='mono'>{esc(F.shape_name(x))}</span>" if x else "&mdash;"

    rows = []
    for d in deltas:
        num = (f"<a href='#ins{d.number}'>{d.number}</a>" if d.number
               else "<span class='dim'>none</span>")
        eff = f"${d.effect:02X}" if d.effect is not None else "&mdash;"
        dec = (f"<span class='mono'>{esc(F.class_name(d.declares & 0xF0))}</span>"
               if d.declares is not None else "&mdash;")
        cls = " class='flag'" if d.flagged else ""
        rows.append(
            f"<tr{cls} id='cmp{d.number}'><td class='num'>{num}</td>"
            f"<td class='mono'>${d.adsr:04X}"
            + ("<span class='dim' title='paired on attack/decay and sustain: "
               "the release nibble differs, which is --cut-release'>*</span>"
               if d.paired == "ad+s" else "")
            + f"</td><td class='mono'>{eff}</td>"
            f"<td>{dec}</td><td>{shape(d.orig_shape)}</td>"
            f"<td>{shape(d.our_shape)}</td>"
            f"<td class='num dim mono'>{d.orig_notes}/{d.our_notes}</td>"
            f"<td>{esc(d.kind)}</td></tr>")
    flagged = sum(1 for d in deltas if d.flagged)
    return f"""
<h2>Original against ours</h2>
<p class="legend">Every instrument both sides sound, joined on the ADSR pair
&mdash; a verbatim copy of the source record, and so the one field that
identifies an instrument on both sides. <b>Original</b> and <b>ours</b> are the
waveform classes the first four frames of a note carry, read at each side's own
attack frames, so the packed player's startup latency cancels rather than
needing correcting. The verdict is <code>fidelity.classify_onset</code>, the
same vocabulary the onset census groups by, computed from the same function the
<code>onset</code> column scores &mdash; a row here cannot disagree with
<code>FIDELITY.md</code> about what an instrument opens on.
<b>Declares</b> is what our own wavetable says, which is the column neither the
census nor <code>instrmap.py</code> has: it separates &ldquo;the wavetable is
wrong&rdquo; from &ldquo;the wavetable is right and the player reaches it a
frame late&rdquo;.
{flagged} of {len(deltas)} disagree, and they are sorted first.</p>
<div class="scroll"><table>
<thead><tr><th>GT</th><th>ADSR</th><th>+7</th><th>declares</th>
<th>original opens</th><th>we open</th><th>notes o/u</th><th>verdict</th></tr></thead>
<tbody>{''.join(rows)}</tbody></table></div>
"""


def _pattern_blocks(song: Song, source_map: Optional[Dict[int, int]]) -> str:
    out = []
    for idx, pat in enumerate(song.patterns):
        rows = len(pat) // 4
        body = []
        for r in range(rows):
            n, i, c, d = pat[4 * r:4 * r + 4]
            if n == GT_END_PATTERN:
                body.append(
                    f"<tr><td class='num dim mono'>{r:02X}</td>"
                    f"<td class='dim' colspan='3'>end of pattern</td></tr>")
                break
            cls = "note" if n != GT_REST else "rest"
            cname, ctext = COMMANDS[c] if c < len(COMMANDS) else (f"${c:02X}", "")
            cmd = "" if c == 0 else f"{cname} <span class='dim'>${d:02X}</span>"
            body.append(
                f"<tr><td class='num dim mono'>{r:02X}</td>"
                f"<td class='mono {cls}'>{esc(note_name(n))}</td>"
                f"<td class='mono'>{('%02X' % i) if i else '<span class=dim>..</span>'}</td>"
                f"<td class='mono'>{cmd}</td></tr>")
        src = ""
        if source_map and idx in source_map:
            src = f" &middot; Hubbard {source_map[idx]}"
        out.append(f"""
<div class="pat">
  <h3>GT <span class="mono">${idx:02X}</span> <span class="dim">&middot; index {idx}{src}</span></h3>
  <table><thead><tr><th>row</th><th>note</th><th>ins</th><th>command</th></tr></thead>
  <tbody>{''.join(body)}</tbody></table>
</div>""")
    return "".join(out)


def _table_block(song: Song, key: str, title: str, describe) -> str:
    tbl = song.tables.get(key, [])
    if not tbl:
        return f"<h3>{esc(title)}</h3><p class='dim'>empty</p>"
    rows = "".join(
        f"<tr><td class='num mono'>{i + 1}</td>"
        f"<td class='mono'>{l:02X} {r:02X}</td><td>{esc(describe(l, r))}</td></tr>"
        for i, (l, r) in enumerate(tbl))
    return f"""<h3>{esc(title)} <span class="dim">({len(tbl)} entries)</span></h3>
<div class="scroll"><table>
<thead><tr><th>#</th><th>bytes</th><th>meaning</th></tr></thead>
<tbody>{rows}</tbody></table></div>"""


def _describe_pulse(l: int, r: int) -> str:
    if l == 0xFF:
        return f"jump to entry {r}" if r else "stop"
    if 1 <= l <= 0x7F:
        return f"hold {l + 1} calls at width ${r:02X}0"
    step = l - 0x100 if l >= 0x80 else l
    return f"step width by {step:+d} per call, for {r} calls"


def _describe_filter(l: int, r: int) -> str:
    if l == 0xFF:
        return f"jump to entry {r}" if r else "stop"
    if l == 0x00:
        return f"set cutoff ${r:02X}"
    if 0x80 <= l <= 0xF0:
        return f"set params: passband/resonance ${l:02X}, voices ${r:02X}"
    step = l - 0x100 if l >= 0x80 else l
    return f"modulate cutoff by {step:+d} for {r} calls"


def _describe_speed(l: int, r: int) -> str:
    return f"left ${l:02X}, right ${r:02X} (portamento/vibrato parameters)"


def render(song: Song, title: str,
           source_map: Optional[Dict[int, int]] = None,
           deltas: Optional[List[InstrumentDelta]] = None) -> str:
    used = sum(1 for i in song.instruments
               if i.wave_ptr or i.ad or i.sr)
    tracks = []
    for s in range(song.subtunes):
        for v in range(3):
            t = song.tracks[s * 3 + v]
            decoded = decode_orderlist(t)
            cells = "".join(
                f"<tr><td class='num dim mono'>{n}</td>"
                f"<td class='mono'>{esc(what)}</td>"
                f"<td class='dim'>{esc(kind)}</td><td>{esc(note)}</td></tr>"
                for n, (kind, what, note) in enumerate(decoded))
            tracks.append(f"""
<details{' open' if s == 0 else ''}>
<summary>Subtune {s}, voice {v + 1} &mdash; {len(t)} bytes</summary>
<div class="scroll"><table>
<thead><tr><th>pos</th><th>byte</th><th>kind</th><th>meaning</th></tr></thead>
<tbody>{cells}</tbody></table></div></details>""")

    return f"""<title>{esc(title)} &mdash; song view</title>
<style>{CSS}</style>
<div class="wrap">
<h1>{esc(song.name or title)}</h1>
<p class="sub">{esc(song.author)}{' &middot; ' if song.author and song.released else ''}{esc(song.released)}
&middot; <span class="mono">{song.fmt}</span>
&middot; {song.subtunes} subtune(s)
&middot; {len(song.instruments)} instruments ({used} in use)
&middot; {len(song.patterns)} patterns</p>

<h2>Orderlists</h2>
<p class="legend">Each voice's sequence of patterns, with transposes and repeats
resolved as the player applies them. A pattern's number here is the same hex
number Goattracker's editor shows.</p>
{''.join(tracks)}

{_comparison_section(deltas) if deltas else ''}
<h2>Instruments</h2>
<p class="legend">The name is the converter's own provenance stamp
&mdash; source record, then bytes 5, 6 and 7 of it. Byte 7 is the player's
effect byte, decoded into tags. <b>Calls</b> is cumulative: a delay entry is
current for <code>value + 1</code> play calls, so the numbers are what a trace
should show, not what the byte says.</p>
{_instrument_cards(song)}

<h2>Tables</h2>
{_table_block(song, 'PTBL', 'Pulse table', _describe_pulse)}
{_table_block(song, 'FTBL', 'Filter table', _describe_filter)}
{_table_block(song, 'STBL', 'Speed table', _describe_speed)}

<h2>Patterns</h2>
<p class="legend">Every pattern carries all the identities it is referred to
by: Goattracker's hex number (what the editor and a listener say), the
converter's own index, and &mdash; where known &mdash; the Hubbard pattern it
came from before dedup.</p>
{_pattern_blocks(song, source_map)}
</div>"""


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(prog="songview")
    ap.add_argument("target", help="a .sng, or a .sid to convert first")
    ap.add_argument("-o", "--output", required=True)
    ap.add_argument("--presets", help="presets.json, for per-song options "
                                      "when the target is a .sid")
    ap.add_argument("--compare", action="store_true",
                    help="also trace the original and this conversion and "
                         "render a per-instrument comparison. Needs a .sid "
                         "target, siddump and gt2reloc")
    ap.add_argument("-t", "--seconds", type=int, default=60,
                    help="trace length for --compare (default 60, the window "
                         "FIDELITY.md is published at)")
    ap.add_argument("--gt2reloc")
    ap.add_argument("--siddump")
    args = ap.parse_args(argv)

    path = Path(args.target)
    source_map = None
    if path.suffix.lower() == ".sid":
        from h2g.convert import convert          # noqa: PLC0415
        opts = {}
        if args.presets:
            import json                          # noqa: PLC0415
            import fidelity as F                 # noqa: PLC0415
            # fidelity's own mapper, not a second copy of it: an option this
            # file filtered by hand would silently diverge from what every
            # measurement in the repo is taken with -- which is the shape in
            # which `--slides` and `--filter` each shipped dead.
            doc = json.loads(Path(args.presets).read_text())
            opts = F._preset_opts(doc, path.name)
        blob = convert(str(path), log=lambda m: None, **opts)
    else:
        blob = path.read_bytes()

    deltas = None
    if args.compare:
        if path.suffix.lower() != ".sid":
            print("error: --compare needs a .sid target -- the original is "
                  "half of the comparison", file=sys.stderr)
            return 1
        mult = 1
        if args.presets:
            import json                          # noqa: PLC0415
            import fidelity as F                 # noqa: PLC0415
            mult = F._preset_multiplier(
                json.loads(Path(args.presets).read_text()), path.name)
        deltas = compare_sides(path, blob, seconds=args.seconds,
                               multiplier=mult, gt2reloc=args.gt2reloc,
                               siddump=args.siddump)

    song = parse_sng(blob)
    out = Path(args.output)
    out.write_text(render(song, path.stem, source_map, deltas),
                   encoding="utf-8")
    print(f"{path.name}: {len(song.patterns)} patterns, "
          f"{len(song.instruments)} instruments -> {out}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
