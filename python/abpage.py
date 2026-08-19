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
import re
from pathlib import Path

HERE = Path(__file__).resolve().parent
ROOT = HERE.parent
LISTEN = ROOT / "build" / "listen"

# The columns worth putting on a listening page, in reading order. `slides`,
# `pul` and the raw attack counts are left out: they are pair-of-counts cells
# that need their own explanation to mean anything.
CHIPS = ("melody", "seq", "retrig", "wave", "gate", "hold", "onset",
         "bend", "vib", "drift")


def fidelity_rows() -> dict[str, dict[str, str]]:
    path = ROOT / "FIDELITY.md"
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
.wave { position:relative; }
.wave canvas {
  display:block; width:100%; height:auto; border-radius:10px;
  background:var(--sunk); border:1px solid var(--line); cursor:crosshair;
}
.wave .legend {
  display:flex; flex-wrap:wrap; gap:14px; align-items:center;
  margin:10px 0 0; font-size:.82rem; color:var(--muted);
}
.wave .swatch { display:inline-flex; align-items:center; gap:6px; }
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
    else if (e.key === "1" || e.key === "ArrowLeft") { e.preventDefault(); pick("a"); }
    else if (e.key === "2" || e.key === "ArrowRight") { e.preventDefault(); pick("b"); }
    else if (e.key === "l" || e.key === "L") {
      looping.checked = !looping.checked; au.loop = bu.loop = looping.checked;
    }
  });
  // ---- amplitude overlay -------------------------------------------------
  // Both sides' peak envelopes on one canvas. It shows dropped notes, wrong
  // note lengths and tempo drift (the two traces shear apart); it cannot show
  // pitch, timbre or filter, which is why the caveat is printed beside it
  // rather than left for the reader to infer.
  var cv = document.getElementById("wave");
  if (cv) (function () {
    var msg = document.getElementById("wavemsg");
    var stat = document.getElementById("wavestat");
    var COLS = 1400, H = 200, DIFF = 46, PAD = 6;
    var off = document.createElement("canvas");
    off.width = COLS; off.height = H + DIFF;
    cv.width = COLS; cv.height = H + DIFF;
    var ctx = cv.getContext("2d"), oc = off.getContext("2d");
    var envA = null, envB = null;

    function css(n) {
      return getComputedStyle(document.documentElement).getPropertyValue(n).trim();
    }
    function envelope(buf) {
      var ch = buf.getChannelData(0), n = ch.length;
      var out = new Float32Array(COLS), per = n / COLS;
      for (var i = 0; i < COLS; i++) {
        var s = Math.floor(i * per), e = Math.min(n, Math.floor((i + 1) * per));
        var pk = 0;
        for (var j = s; j < e; j++) { var v = ch[j] < 0 ? -ch[j] : ch[j]; if (v > pk) pk = v; }
        out[i] = pk;
      }
      return out;
    }
    function band(g, env, colour, alpha) {
      var mid = H / 2, half = mid - PAD;
      g.beginPath();
      for (var i = 0; i < COLS; i++) g.lineTo(i, mid - env[i] * half);
      for (var k = COLS - 1; k >= 0; k--) g.lineTo(k, mid + env[k] * half);
      g.closePath();
      g.globalAlpha = alpha; g.fillStyle = colour; g.fill(); g.globalAlpha = 1;
    }
    // B is drawn where it is *heard*, i.e. shifted by the sync offset, so the
    // picture never contradicts the ears.
    function shiftCols() {
      var d = au.duration;
      if (!d || !isFinite(d)) return 0;
      return Math.round(sync / d * COLS);
    }
    function shifted(env, by) {
      if (!by) return env;
      var out = new Float32Array(COLS);
      for (var i = 0; i < COLS; i++) {
        var j = i + by;
        out[i] = (j >= 0 && j < COLS) ? env[j] : 0;
      }
      return out;
    }
    function paint() {
      var line = css("--line"), ink = css("--ink");
      var envBs = shifted(envB, shiftCols());
      oc.clearRect(0, 0, COLS, H + DIFF);
      oc.strokeStyle = line; oc.lineWidth = 1;
      oc.beginPath(); oc.moveTo(0, H / 2 + 0.5); oc.lineTo(COLS, H / 2 + 0.5); oc.stroke();
      oc.beginPath(); oc.moveTo(0, H + 0.5); oc.lineTo(COLS, H + 0.5); oc.stroke();
      band(oc, envA, css("--a"), 0.62);
      band(oc, envBs, css("--b"), 0.62);
      // difference strip: |peak difference| per column, same time axis.
      var sum = 0;
      oc.globalAlpha = 0.45; oc.fillStyle = ink;
      for (var i = 0; i < COLS; i++) {
        var d = Math.abs(envA[i] - envBs[i]); sum += d;
        oc.fillRect(i, H + DIFF - d * (DIFF - 4), 1, d * (DIFF - 4));
      }
      oc.globalAlpha = 1;
      if (stat) stat.textContent = "mean |Δ| " + (100 * sum / COLS).toFixed(1) + "%";
      frame();
    }
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
        var x = Math.round(au.currentTime / d * COLS) + 0.5;
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
      var t = Math.max(0, Math.min(1, (e.clientX - r.left) / r.width)) * d;
      au.currentTime = t; bu.currentTime = bAt(t);
      now.textContent = fmt(t);
      seek.value = String(Math.round(t / d * 1000));
      frame();
    });

    var AC = window.AudioContext || window.webkitAudioContext;
    if (!AC) { if (msg) msg.textContent = "This browser has no Web Audio."; return; }
    var ac = new AC();
    function load(src) {
      return fetch(src).then(function (r) { return r.arrayBuffer(); })
        .then(function (ab) { return ac.decodeAudioData(ab); });
    }
    Promise.all([load(au.src), load(bu.src)]).then(function (bufs) {
      envA = envelope(bufs[0]); envB = envelope(bufs[1]);
      if (msg) msg.hidden = true;
      cv.hidden = false;
      var lag = startupLagMs(bufs[0], bufs[1]);
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
  })();

  apply(); setNames();
})();
"""


def wav_uri(path: Path) -> str:
    return "data:audio/wav;base64," + base64.b64encode(path.read_bytes()).decode("ascii")


def page(name: str, row: dict, notes: list[str], version: str,
         embed: bool, index_link: bool) -> str:
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

<div class="rig" id="rig">
  <div class="sources">
    <button class="src" data-side="a" aria-pressed="true">
      <span class="key">Source A &middot; press <kbd>1</kbd></span>
      <span class="name" id="nameA">Original .sid</span>
    </button>
    <button class="src" data-side="b" aria-pressed="false">
      <span class="key">Source B &middot; press <kbd>2</kbd></span>
      <span class="name" id="nameB">H2G conversion</span>
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
</div>

<div class="card wave">
  <h2>Both sides, drawn</h2>
  <div class="msg" id="wavemsg">Reading both renders&hellip;</div>
  <canvas id="wave" hidden></canvas>
  <div class="legend">
    <span class="swatch orig"><i></i>original</span>
    <span class="swatch ours"><i></i>H2G</span>
    <span class="swatch diff"><i></i>|difference|, lower strip</span>
    <span>click to seek both</span>
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

<div class="card">
  <h2>What to listen for</h2>
  <ul>%(bullets)s</ul>
</div>

<footer>
  <div><kbd>Space</kbd> play &middot; <kbd>1</kbd>/<kbd>2</kbd> or <kbd>&larr;</kbd>/<kbd>&rarr;</kbd> switch source &middot; <kbd>L</kbd> loop &middot; both tracks run in sync, so switching never loses your place.</div>
  <div>%(provenance)s</div>
</footer>
</div>
<audio id="au" preload="auto" src="%(a_src)s"></audio>
<audio id="bu" preload="auto" src="%(b_src)s"></audio>
<script>%(script)s</script>
""" % dict(pretty=pretty, css=CSS, back=back, version=version, chips=chips,
           bullets=bullets, provenance=provenance, a_src=a_src, b_src=b_src,
           script=SCRIPT)


def index(names: list[str], rows: dict, version: str) -> str:
    body = ""
    for n in names:
        r = rows.get(n, {})
        body += ("<tr><td><a href=\"%s.html\">%s</a></td><td>%s</td><td>%s</td>"
                 "<td>%s</td><td>%s</td></tr>"
                 % (n, n.replace("_", " "), r.get("melody", "&mdash;"),
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
    <thead><tr><th>tune</th><th>melody</th><th>gate</th><th>wave</th><th>hold</th></tr></thead>
    <tbody>%(body)s</tbody>
  </table></div>
</div>
<footer>
  <div>Columns are from <code>FIDELITY.md</code> at %(version)s. They compare what is played, never how it sounds &mdash; which is what these pages are for.</div>
  <div><code>gate</code> is the newest of them and the least validated: it was built at v0.5.270 because no other column could see the register it reads, and no listener has confirmed it corresponds to anything audible.</div>
</footer>
</div>
""" % dict(css=CSS, version=version, count=len(names), body=body)


def main() -> int:
    ap = argparse.ArgumentParser(prog="abpage")
    ap.add_argument("--embed", metavar="TUNE",
                    help="build one self-contained page with the audio inlined")
    ap.add_argument("-o", "--output", default=None,
                    help="where to write (--embed only; default beside the WAVs)")
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

    names = sorted(p.name[: -len(".original.wav")]
                   for p in LISTEN.glob("*.original.wav"))
    if not names:
        print("no staged pairs in %s -- run listen.py first" % LISTEN)
        return 2
    rows, notes = fidelity_rows(), listening_notes()

    if args.embed:
        if args.embed not in names:
            print("%s is not staged; have: %s" % (args.embed, ", ".join(names)))
            return 2
        html = page(args.embed, rows.get(args.embed, {}),
                    notes.get(args.embed, []), version,
                    embed=True, index_link=False)
        out = Path(args.output) if args.output else LISTEN / ("%s.embed.html" % args.embed)
        out.write_text(html, encoding="utf-8")
        print("%s  %.2f MB" % (out, len(html) / 1e6))
        return 0

    for n in names:
        html = page(n, rows.get(n, {}), notes.get(n, []), version,
                    embed=False, index_link=True)
        (LISTEN / ("%s.html" % n)).write_text(html, encoding="utf-8")
    (LISTEN / "index.html").write_text(index(names, rows, version), encoding="utf-8")
    missing = [n for n in names if n not in rows]
    print("%d page(s) + index -> %s" % (len(names), LISTEN))
    if missing:
        print("no FIDELITY.md row for: %s" % ", ".join(missing))
    if args.serve is not None:
        return serve(args.serve)
    print("file:// hides the overlay -- `python abpage.py --serve` to draw it")
    return 0


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

    handler = functools.partial(http.server.SimpleHTTPRequestHandler,
                                directory=str(LISTEN))
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
