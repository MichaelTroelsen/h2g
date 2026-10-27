"""Extra listening pages: a second page for a different subtune of a corpus file.

The listening set has one page per corpus file, at the subtune fidelity matched.
An entry here adds a page of its own, named by the key, that plays `subtune`
(0-based index; PSID song N is index N-1) of `source` instead. `listen.py`
(--all, and --files by page name) and `abpage.py` (conversion shas, stale-audio
guard, original lookup) both resolve the key to `source`, so the page converts
the source file with the source file's presets. `approved.json` keys verdicts by
the page name, like any other tune.

`ours` is the subtune index in OUR packed file when gt2reloc shifted it; omit it
when nothing ahead of it was dropped.
"""
from __future__ import annotations

EXTRA_PAGES: dict[str, dict] = {
    # Delta.sid has 13 subtunes and start song 12 (index 11), which is the page
    # "Delta". Song 13 is index 12.
    "Delta_13": {"source": "Delta.sid", "subtune": 12},
    # Knucklebusters.sid has 11 header songs; init sends 3 to the music player
    # (the rest are sound effects) and start song 2 (index 1) is the page
    # "Knucklebusters". Songs 1 and 3 are indices 0 and 2; under its presets
    # all three convert and gt2reloc exports all three, so ours keeps the index.
    "Knucklebusters_1": {"source": "Knucklebusters.sid", "subtune": 0},
    "Knucklebusters_3": {"source": "Knucklebusters.sid", "subtune": 2},
    # Commando.sid starts at song 1 (index 0), the page "Commando"; song 2 is
    # index 1, and all three of our subtunes are exported.
    "Commando_2": {"source": "Commando.sid", "subtune": 1},
}


def page_stem(name: str) -> str:
    return name[:-4] if name.lower().endswith(".sid") else name


def extra_for(name: str) -> dict | None:
    """The EXTRA_PAGES entry for a page name (with or without `.sid`), or None."""
    return EXTRA_PAGES.get(page_stem(name))
