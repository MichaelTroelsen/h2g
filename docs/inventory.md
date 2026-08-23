# Documentation inventory

What each file in `docs/` is, who writes it, and whether it is still current.

The distinction that matters most here is **generated vs written**. A generated
file is rewritten wholesale by a tool and any hand edit is lost on the next run;
a written one is maintained by hand and goes stale silently. Both kinds live in
this directory, and telling them apart is the difference between editing the
right thing and editing something that will be overwritten within the hour.

Three documents deliberately stay in the repo root and are **not** listed here:
`README.md` (the entry point), `CLAUDE.md` (agent instructions, loaded
automatically) and `whats-next.md` (the session handoff).

## Generated — do not hand-edit

Regenerate these; do not edit them. Each embeds the version and the corpus path
that produced it, so a stale one states something that is no longer true.

| file | written by | when to regenerate |
|---|---|---|
| [FIDELITY.md](FIDELITY.md) | `python fidelity.py <sid_dir> -t 60 --presets ../presets.json -o ../docs/FIDELITY.md` | after any commit that changes what the converter emits |
| [SURVEY.md](SURVEY.md) | `python survey.py <sid_dir> -o ../docs/SURVEY.md --legal-restart --gt2reloc` | every commit |
| [SUBTUNES.md](SUBTUNES.md) | `python survey.py --subtune-census` | with SURVEY.md |
| [CHANGELOG.md](CHANGELOG.md) | `python bump_version.py "<description>"` | every commit, automatically |

`FIDELITY.md` is the one to read first when asking whether a change helped, and
the one to distrust first when it says a change did nothing — see its own
*What this run compared* section, which names the registers nothing in the run
reads. `presets.json` is generated too but lives at the repo root, because
`--presets` is a path users type.

## Reference — stable, written once, still true

Facts about external systems. These go stale only when the external thing
changes, which for a 1987 SID player and a 2001 tracker is close to never.

| file | what it is |
|---|---|
| [H2G-CONVERSION-METHOD.md](H2G-CONVERSION-METHOD.md) | **The main technical document** (588K). How the ripping method works, section by section, with every mechanism decoded and every wrong turn recorded beside the fix. Used as reference material by a sibling project. |
| [HUBBARD-PLAYER-REFERENCE.md](HUBBARD-PLAYER-REFERENCE.md) | Rob Hubbard's player internals, from the *C=Hacking* issue 5 article by Anthony McSweeney. |
| [GOATTRACKER-REFERENCE.md](GOATTRACKER-REFERENCE.md) | The `.sng` format and player semantics, read out of GoatTracker 2.77's own `readme.txt` rather than inferred. |
| [GOATTRACKER.md](GOATTRACKER.md) | Findings from actually using GoatTracker 2.77 — behaviour the readme does not state. |
| [GOATTRACKER-FORKS.md](GOATTRACKER-FORKS.md) | Which GoatTracker build a `.sng` is opened in, and why it matters (the GTS2 importer overruns on this converter's portamento commands). |
| [SIDM2-HUBBARD-KNOWLEDGE.md](SIDM2-HUBBARD-KNOWLEDGE.md) | What the sibling SIDM2 project learned about the same players. |

## Investigations — a question, answered

Each of these answers one question and then stops. They are historical: the
answer is still valid, but nothing updates them.

| file | the question | the answer |
|---|---|---|
| [VIBRATO.md](VIBRATO.md) | Is `vib` 0.17x a vibrato-rate bug? | No — the missing reversals belonged to an arpeggio never read at all. Attribute a ratio per instrument before tuning the mechanism you assume produces it. |
| [SNG2SID-FIDELITY.md](SNG2SID-FIDELITY.md) | Can GoatTracker's **F9** pack be used for fidelity testing? | See the document. |
| [SIDM2-FIDELITY-TESTER.md](SIDM2-FIDELITY-TESTER.md) | Can SIDM2's accuracy tooling be reused here? | See the document. |
| [AUDACITY-MCP-ASSESSMENT.md](AUDACITY-MCP-ASSESSMENT.md) | Would an Audacity MCP help? | **No**, not for this project's current gaps. |

## Plans and audits — check the date before believing these

These were written against a specific version and describe work that may since
have been done, abandoned, or superseded. **Every one of them names the version
it was written at in its first line — read that first.** A plan is not a record
of the present.

| file | written at | status |
|---|---|---|
| [FIDELITY-TOOL-IMPROVEMENTS.md](FIDELITY-TOOL-IMPROVEMENTS.md) | v0.5.72 | What `fidelity.py` should do next. Much of it has since been built — check against the tool before acting. |
| [PER-SONG-PLAN.md](PER-SONG-PLAN.md) | v0.5.318 | A per-song working plan. |
| [AUDIT.md](AUDIT.md) | v0.5.50 (`d1866c2`) | A code audit at 252 tests. The suite is now far larger. |
| [DOC-AUDIT.md](DOC-AUDIT.md) | — | Documentation claims that would cause a reader to take a wrong action. |

## Keeping this file honest

`inventory.md` is written by hand and has the failure mode every hand-written
index has: a file is added to `docs/` and this list does not mention it, which
is invisible unless someone goes looking. When adding a document here, add its
row in the same commit — and if the new document is *generated*, put the exact
command in the table, because a generated file whose command is not written
down anywhere is one nobody will dare regenerate.
