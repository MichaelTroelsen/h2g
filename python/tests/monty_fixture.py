"""Auf_Wiedersehen_Monty's preset as the real-firstwave tests were written for.

Since v0.5.644 presets.json ships Monty with `aligned_firstwave` instead of
`real_firstwave_instruments` 1..16 (melody .988 -> 1.000; user decision
2026-11-01). The tests that import this exercise mechanisms only the
real-firstwave spelling reaches -- cut-note programs, the funk gatetimer
split, the pitch lead, the legato clone's firstwave -- so they keep that
spelling as a fixture rather than following the shipped entry.
"""
from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import fidelity  # noqa: E402

MONTY = "Auf_Wiedersehen_Monty.sid"
REAL_FIRSTWAVE = list(range(1, 17))


def pinned_preset_opts(doc: dict, name: str) -> dict:
    """`fidelity._preset_opts`, with Monty held at its real-firstwave preset."""
    opts = fidelity._preset_opts(doc, name)
    if name == MONTY:
        opts = dict(opts, real_firstwave_instruments=REAL_FIRSTWAVE,
                    aligned_firstwave=False)
    return opts
