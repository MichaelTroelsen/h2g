"""Hard-restart gatetimer schedule (split out of goatwriter.py, text moved unchanged)."""
from __future__ import annotations

from . import constants as _gw_constants
def _hard_restart_ticks(multiplier: int, row_calls: int,
                        wide: bool = False, full: bool = False,
                        frames: int | None = None) -> int:
    """Calls to hold the gate off before a note, bounded by the row.

    **gplay.c:334 stops the song outright** when the gatetimer exceeds the
    channel's tick, so this can never reach the row length -- and the failure
    is total, not graceful: swept past the bound, Commando drops from 716
    attacks to 3 and Sanxion from 956 to 1. `row_calls` is the shortest row
    the INSTRUMENT is played at -- `tracks.instrument_row_calls`, the minimum
    over the subtunes its orderlists reach, because a pattern shared between
    two tempos is short in the faster one. It falls back to the file-wide
    `short_row_calls` wherever that attribution is unsafe (one tempo, or a
    split that shifted the numbering), which is what it was for every
    instrument until v0.5.396.

    That change moves 7 corpus files and is worth stating narrowly: five of
    them move bytes and no column, Warhawk gains `gate` 84.1 -> 88.5 and
    Bump Set Spike loses 0.2pp of it. **It does nothing for Auf Wiedersehen
    Monty**, the file it was opened for -- its tempos are [3, 4, 5] and all
    sixteen of its instruments sound in the tempo-3 subtune, so every one of
    them is bounded at 3 either way. The per-song `gate` lever really is
    exhausted there.

    **At most half the row**, which is a claim about the music rather than
    about the player: a note that spends more of its slot released than
    sounding is not the note. Bounded only by `row_calls - 1` -- the
    player's own limit -- Saboteur II gets 6 calls of an 8-call row and
    melody falls 98% -> 62% with `retrig` 1.00 -> 0.81, while every other
    file that moved gained. Half of its row is 4, and the same sweep that
    found the collapse shows the gain surviving it.

    **`wide` raises that bound to `2 * row // 3`**, worth 1.6pp of mean gate
    over the corpus in v0.5.276's sweep and the value at which Saboteur II
    starts to break (melody 98% -> 67%). Half the row is the *safe* bound and
    two thirds is the *better* one everywhere else, which is a per-song
    question rather than a constant -- so it rides `--wide-hard-restart` and
    `fidelity_better` decides it, with `keeps_notes` as the guard that is
    meant to refuse it on files of Saboteur II's shape. At v0.5.302 it did
    exactly that: 9 of the 19 files it reaches took it and Saboteur II did
    not.

    **`full` raises that bound to `row_calls - 1`, the player's own limit**,
    3.3pp of mean gate in the same sweep and 98% -> 62% on the same file. It is
    offered on the strength of `keeps_notes` having demonstrably refused the
    gentler value where it hurts -- a guard that has caught the case once is
    evidence, where at v0.5.276 it was a hope. `full` outranks `wide`; see the
    comment at the branch.

    **BOTH RAISE THE BOUND AND NEITHER RAISES `want`, so both are INERT AT
    MULTIPLIER 1** -- and that sentence used to read "`full` *goes to*
    `row_calls - 1`", which is true only where `want` already exceeds the
    bound. `ticks = min(want, bound)` and `want` is `HARD_RESTART_FRAMES *
    multiplier` = 2 at single speed, so at multiplier 1 `full` returns 2 for a
    row of 4, of 8 and of 12 alike, where its own bound would allow 3, 7 and
    11. The corpus shows the consequence rather than merely admitting it: 17
    songs carry `max_hard_restart` and **not one of them is multiplier 1**,
    because on a single-speed file the toggle changes no byte and the preset
    search cannot select what does nothing.

    **What that costs, measured on 5_Title_Tunes (multiplier 1, row 4 calls).**
    Its original gates off for a uniform 4 frames per note against our 2, and
    the gate column reads 0.4996 with `gate_ours_ringing` 1873. The constant is
    NOT the lever -- converting at `HARD_RESTART_FRAMES` 2, 3, 4 and 5 gives a
    byte-identical `.sng` every time (sha b49462e6553e), because `bound =
    row_calls // 2` = 2 caps it before `want` is ever consulted. Raising `want`
    to 4 *and* setting `full` reaches ticks 3, the row's ceiling, and that
    measures gate **0.4996 -> 0.7494** with `gate_ours_ringing` 1873 -> 938 and
    melody, seq, pitch and wave every one unchanged to four decimals. Ticks 4
    would match the original exactly and is unreachable: `gplay.c:334` stops the
    song when the gatetimer exceeds the channel's tick, so a 4-call row can
    never gate off for 4.

    **And `adsr` does NOT follow the gate, which was predicted and is wrong.**
    At ticks 3 it stays 0.5831 to four decimals. The frame merely moves from
    "we are gated on while the original is off" to "both gated off"; the AD
    byte we hold there is the instrument's and the original's is $0000, so it
    disagrees in either state. The two columns share a population and not a
    fix.

    **Floored at 2**, the value this writer wrote for its whole life, so no
    single-speed file moves: Commando's row is 3 calls, half of which is 1,
    and dropping to 1 would rewrite every `-S1` conversion in the corpus to
    fix a defect the multispeed files have.

    **THAT LAST CLAUSE IS WRONG AND THE PRICE OF BOTH ALTERNATIVES IS NOW
    MEASURED (v0.5.461).** Dropping the floor fixes NOTHING, and zero -- the
    only value that does fix it -- costs the schedule. The deficit in question
    is `hold`'s `fetch` kind: Goattracker fetches the next note
    `gatetimer & $3f` calls early, so the note before it loses that many
    calls. **At `-S1` one call IS one frame**, so the deficit is one frame for
    every non-zero gatetimer this function can return, and no choice between 1
    and 2 can close it.

    * **FLOOR REMOVED (gatetimer 1 where the row allows).** Byte-hash over the
      corpus through `fidelity._preset_opts`: **30 of 86 files move** -- not
      "no single-speed file", because the bound bites wherever `row_calls <= 3`
      at any multiplier. `--hold-census` is UNCHANGED: Action_Biker stays
      `fetch` 4 of 4 and Commando `fetch` 9 of 9. Every report column is
      identical to the shipped arm on all four files traced at `-t 180` except
      **`gate`, which falls**: Action_Biker 72 -> 57%, Commando 41 -> 28%,
      Crazy_Comets 57 -> 49%, Sigma_Seven 24 -> 25%. It buys nothing and sells
      the release.
    * **ZERO IS NOT AVAILABLE, AND THIS IS WHAT IT COSTS.** Forcing the
      gatetimer to 0 does close the kind -- Action_Biker `fetch` 4 of 4 -> 0 --
      but it reclassifies to `slot` 4 of 4 and **`hold` itself does not move,
      0% either way**: the miss is relabelled, not removed. What moves is
      everything else, on all four files: melody 100 -> 95, 97 -> 85, 100 -> 86
      and 99 -> 91%; `retrig` 1.00 -> 0.89, 0.80, 0.78 and 0.89; `drift`
      +0.0 -> +187.5, +261.1 and +248.6; `gate` 72 -> 13, 41 -> 24, 57 -> 35
      and 24 -> 9%; and Action_Biker's attack count 291 -> 260 with `len`
      +0.1 -> **+11.3 s**. A zero gatetimer does not merely stop the early
      fetch, it stops the note fetch being early enough to keep the schedule.

    So `fidelity.py`'s standing sentence -- "there is no row length or
    gatetimer that returns it" (`fidelity.py:2765`) -- is CONFIRMED rather than
    merely asserted, and the deficit stays a priced property of the target
    player. The lever that does remove it is `--no-test-restart`, per song,
    which is what the search already walks.

    **AND "ZERO IS UNREACHABLE" IS SWEPT NOW, NOT ARGUED (v0.5.466).** The
    block above derives it from this function's floor and bound, which is a
    claim about code read by eye. Enumerated instead over every combination of
    `multiplier` 1-5, `row_calls` 1-32 and all three flags -- **3840 calls, and
    the minimum returned is 1**. So the one value that would close the `fetch`
    kind is outside the range of this function for every input it can be given,
    and the refutation does not depend on having read the branches correctly.

    **AND THE PACKED PLAYER'S OWN BYTES SAY SO (2026-10-03).** The bound is
    `player.s:1090-1098`: on the call where `mt_chncounter` equals the
    channel's gatetimer the player branches to `mt_getnewnote` -- the gate-off
    and the next note's fetch -- so a note loses `gatetimer & $3f` calls
    before the next row's tick 0. Action_Biker under presets packs at `-S1`
    with all 12 instruments on gatetimer `$82`, so greloc takes its
    fixed-params path (`greloc.c:800-815`, `GATETIMERPARAM` at 1149) and the
    packed image carries it as an immediate: `$12AA BD A5 13 / C9 02 / F0 03`
    -- `LDA mt_chncounter,X / CMP #$02 / BEQ mt_getnewnote`. Its operand is
    this function's return, never 0 (the sweep above), so the early fetch is
    in every packed conversion; `tests/test_hard_restart.py::
    test_the_packed_player_compares_the_counter_with_this_gatetimer` reads the
    immediate back out of a packed Action_Biker.

    Falls back to that constant where the row is unknown, which is what a
    caller building instruments without a tempo pass has.
    """
    # `frames` is the per-song override (`--hard-restart-frames`). It replaces
    # the constant in `want` and nothing else, so the row bound still applies
    # and gplay.c:334's limit is still respected -- a song cannot ask its way
    # past the tick that stops the player.
    # `not frames` rather than `frames is None`: `_preset_opts` passes False
    # for every option a song's entry does not carry, so an `is None` test
    # reads absent-as-zero and silently drops `want` from 2 to 1. That moved
    # 24 corpus files on a change advertised as inert, and the byte-hash is
    # what caught it.
    base = max(1, int(frames)) if frames else _gw_constants.HARD_RESTART_FRAMES
    want = max(1, base * max(1, multiplier))
    if not row_calls or row_calls <= 1:
        return min(want, 2)
    # Ordered, not exclusive: the search tries every combination of its
    # toggles, so `full` and `wide` can arrive together and the wider of the
    # two has to win rather than the later-tested one. A song selecting both
    # has `wide` removed by `presets.prune_inert`, which drops any flag whose
    # removal leaves the bytes identical.
    if full:
        bound = row_calls - 1
    elif wide:
        bound = 2 * row_calls // 3
    else:
        bound = row_calls // 2
    ticks = min(want, max(1, bound))
    ticks = max(ticks, min(2, row_calls - 1))
    return min(ticks, row_calls - 1)
