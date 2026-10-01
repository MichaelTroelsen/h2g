"""Tunes the user has put ON HOLD: no work, no staging, no listening verdict.

One place, so the listening index, the rule in CLAUDE.md and any task filter
read the same set. Keyed on the corpus filename with its `.sid` extension, the
spelling `presets.json` uses; `held()` also accepts a bare stem, which is what
`abpage.py` names its pages by.

THE DIGI HOLD (user, 2026-09-30, at v0.5.493): every corpus file SIDId tags
`(Rob_Hubbard_Digi)` -- twelve files. `tests/test_hold.py` re-derives that set
from the corpus. Two reasons, kept apart only for the tooltip:

- `FOURTH_VOICE`: the player drives a fourth, sampled voice (detection's
  `track_voices > 3`, survey's "digi channel dropped"), which Goattracker
  cannot carry.
- `NAMED`: digi-tagged files without a fourth voice, which the user named.

`RELEASED`: Pygmies_Revenge drives a fourth voice but SIDId tags it plain
Rob_Hubbard, and the user put it back on the main list (2026-09-30). The
fourth-voice test counts it as released rather than missing.
"""

DIGI_REASON = "DIGI: the player drives a fourth, sampled voice"
NAMED_REASON = "DIGI: SIDId-tagged Rob_Hubbard_Digi, held by the user by name"

FOURTH_VOICE: dict[str, str] = {
    "After_8.sid": DIGI_REASON,
    "Kings_of_the_Beach_intro.sid": DIGI_REASON,
    "Mr_Meaner.sid": DIGI_REASON,
    "Off_the_Cuff.sid": DIGI_REASON,
    "One_on_One_Jordan_vs_Bird.sid": DIGI_REASON,
    "Powerplay_Hockey_USA_vs_USSR.sid": DIGI_REASON,
    "Rikky.sid": DIGI_REASON,
    "Rock_Tells_the_Tale.sid": DIGI_REASON,
}

NAMED: dict[str, str] = {
    "Arcade_Classics.sid": NAMED_REASON,      # user, 2026-09-30
    "Skate_or_Die_intro.sid": NAMED_REASON,   # user, 2026-09-30
    "Ricochet.sid": NAMED_REASON,             # user, 2026-09-30
    "BMX_Kidz.sid": NAMED_REASON,             # user, 2026-09-30 (also tagged Sidplayer)
}

RELEASED: dict[str, str] = {
    "Pygmies_Revenge.sid": "fourth voice, but not SIDId-digi; back on the main list (user, 2026-09-30)",
}

ON_HOLD: dict[str, str] = {**FOURTH_VOICE, **NAMED}


def held(name: str) -> str | None:
    """The hold reason for a tune named by filename or stem, else None."""
    key = name if name.lower().endswith(".sid") else name + ".sid"
    return ON_HOLD.get(key)
