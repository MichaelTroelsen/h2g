# Would an Audacity MCP server help H2G?

**Verdict: no, not for this project's current gaps.** It cannot do the one thing
that would help (give a spectrogram image, or hearing), it is redundant with what
`numpy`/`PIL` already did more precisely, and its transport is single-instance and
stateful — which conflicts directly with how this repo has to run the corpus.

Assessed at v0.5.146. This is an assessment *for H2G*, not of Audacity MCP in
general: for interactive audio production it looks genuinely useful.

## What it is

Every Audacity MCP server found is a wrapper over **`mod-script-pipe`**, the
scripting interface Audacity itself already exposes over a named pipe. None of
them add capability of their own — they expose Audacity's own command set as MCP
tools. So the ceiling is exactly the [Audacity scripting
reference](https://manual.audacityteam.org/man/scripting_reference.html), and any
claim about what an Audacity MCP "can do" reduces to what that reference lists.

Implementations vary widely in surface (one exposes ~3 tools — status, record,
play; another advertises 131 across effects/cleanup/mastering), but all sit on the
same pipe. Requirements are consistent: **Audacity 3.x running**, `mod-script-pipe`
enabled under *Preferences → Scripting/Remote Control*, and a restart.

## Capabilities, against what H2G would actually want

| H2G need | Available? | Detail |
|---|---|---|
| Hear a WAV and judge it | **No** | Nothing in the interface returns audio to the caller. The standing fact holds: this environment has no auditory perception, and an Audacity MCP does not add one. |
| Export a spectrogram **image** to `Read` | **No** | `PlotSpectrum` renders into a window and the reference lists **no export** for it. This is the specific thing I had guessed might work when the question first came up — it does not. `ContrastAnalyser` is the same shape: measures, displays, returns nothing. |
| Get numeric sample/level data back | **Yes** | `SampleDataExport` (Tools menu, built in) writes `Sample List (txt)`, `Indexed List (txt)`, `Time Indexed (txt)`, `Data (csv)` or `Web Page (html)`. Header levels `None`/`Minimal`/`Standard`/`All` can include **peak amplitude (linear and dB)**, **`Unweighted RMS level (dB)`** and DC offset. `Limit output to first <n> samples` defaults to 100, max 1,000,000. Stereo via `L-R on Same Line` / `Alternate Lines` / `L Channel First`. |
| Run arbitrary analysis | **Partly** | `NyquistPrompt` executes Nyquist. Whether its printed output is returned over the pipe I did **not** verify — see *Unverified* below. |
| Import/export audio | **Yes** | `ImportAudio`, `ImportRaw`, `ExportAudio`, `ExportLabels`, plus MIDI variants. |
| Apply effects | **Yes** | Most of the effect menu, though not all: the reference marks e.g. `NoiseReduction` "not currently available from scripting". |
| Query project structure | **No** | The reference lists **no `GetInfo`** — no tracks/clips/labels/envelopes readback in any format. (Some MCP wrappers may implement their own; the documented command set does not.) |

## Why that is the wrong fit here

**1. It cannot close the actual gap.** The two backlog items that are genuinely
about *audible* qualities — Gerry_the_Germ's missing rise sweeps, and
Bump_Set_Spike/Gerry's dynamic-range compression — need either ears or a picture.
Audacity MCP provides neither: no audio return, and no spectrogram export. What it
returns is numbers, and numbers are the thing this project is already best at.

**2. It is redundant, and less precise than what already worked.** A prior session
built spectrograms with a `numpy` STFT plus `PIL` and read them with the `Read`
tool — which *is* genuine visual perception, and found real issues (Commando's rest
section started there). `SampleDataExport`'s peak/RMS/dB is a per-selection summary;
getting a time-series envelope out of it means scripting one selection per window
through a GUI, to obtain something `numpy` computes in one pass. The repo already
has `listen.py` staging WAV pairs for exactly this.

**3. Its transport fights how this repo must run.** `mod-script-pipe` is a single
named pipe into a single running GUI instance, holding a mutable project as global
state. Corpus work here is 83–95 files and this repo has been bitten **twice** by
shared-mutable-path contamination — the rule that came out of it is that every run
gets its own isolated directory (`fidelity.py` and `listen.py` now do, since
v0.5.66). One Audacity instance is inherently serial and cannot be isolated per
file. A GUI in the loop also means a corpus run can be broken by a dialog, and the
repo already has a hard rule against blocking modal prompts.

**4. Minor, but real:** driving a live Audacity mutates whatever project the user
has open.

## What to do instead

The higher-value move is already on the backlog and needs no MCP server, no GUI,
and parallelises: **commit the spectrogram tooling into the repo** — a
`python/spectrogram.py` beside `listen.py`, or folded into it. That restores the
one instrument that has actually produced findings here (the scratch version lived
in a session scratchpad and is gone), keeps `numpy`/`PIL` dev-only as `pytest`
already is, and stays consistent with the isolated-workdir rule.

For register-level questions — including the drum sweep just shipped in §7.tt —
the right instruments remain `siddump`/`siddump-rt` and `--vice`, because they read
the SID registers symbolically at up to 312 samples a frame. Audacity would only
ever see the rendered result, more coarsely.

## Unverified

Stated explicitly rather than guessed:

- **Whether `NyquistPrompt`'s output is returned over `mod-script-pipe`.** If it
  is, Nyquist's FFT primitives could in principle emit spectral data as text,
  which would make the "numbers back" column stronger than the table above
  implies. I did not test it, and it is the one finding that could partly change
  the verdict — though not conclusions 2 and 3, which are about redundancy and
  concurrency rather than capability.
- **Individual MCP wrappers' own additions.** The 131-tool implementation may
  synthesise conveniences (a `GetInfo`-like readback, for instance) beyond the
  documented command set. The assessment above is of the documented ceiling.
- No Audacity MCP server is connected to this session, so nothing here was
  exercised against a live Audacity.

## Sources

- [Audacity Scripting Reference](https://manual.audacityteam.org/man/scripting_reference.html)
- [Audacity Sample Data Export](https://manual.audacityteam.org/man/sample_data_export.html)
- [An-3/an3-audacity-mcp](https://github.com/An-3/an3-audacity-mcp)
- [xDarkzx/Audacity-MCP](https://github.com/xDarkzx/Audacity-MCP)
- [Audacity forum: Audacity-mcp](https://forum.audacityteam.org/t/audacity-mcp-control-audacity-with-natural-language-w-claude/152456)
