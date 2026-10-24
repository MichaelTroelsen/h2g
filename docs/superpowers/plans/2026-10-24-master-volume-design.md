# Master volume: emitting `D0v` for originals that hold a level below `$F`

Measured at 2043c3b (v0.5.598). No converter change is made here.

## The defect

`fidelity`'s `vol` column (v0.5.598) reads two non-held songs at vol 0.0. Their originals hold the
`$D418` low nibble at `$8` for the whole window, while ours plays GoatTracker's default `$F`
(`gplay.c:44 masterfader = 0x0f`, `player.s mt_masterfader: ora #$0f`):

| song | orig | ours | vol | vol_ratio | loud_ratio (60 s) |
|---|---|---|---:|---:|---:|
| Mega_Apocalypse | [8] | [15] | 0.000 | 1.875 | 1.921 |
| Pygmies_Revenge | [8] | [15] | 0.000 | 1.875 | 1.778 |

15/8 = 1.875, so the volume nibble alone accounts for nearly all of each song's loudness surplus.

## Where the level comes from: a read, not a measurement

`detect.FILTER_MODE_ENTRY_SHAPE` (`4C ?? ?? 4C ?? ?? A9 ?? 8D 18 D4`) is the play routine directly
behind the JMP table, which writes `$D418` from an immediate on every frame. `detect` already reads
its high nibble as the filter passband (`detect.py`, the `passband = data[e + 7] & 0x70` fallback).
Its **low nibble is the master volume**. Census over the 95 corpus files (`census.py`, against
the traced `orig_volume_values` of the fbs-vol-column run, C:/t/fbs-vol-column/corpus.json):

* every file where the shape matches and the trace holds one constant level: **23 agree, 0 disagree**;
* 13 of those sit below `$F`, and all 13 match exactly:
  * not held: Mega_Apocalypse `$08`, Pygmies_Revenge `$08`;
  * held, listed and **not worked**: Arcade_Classics, Kings_of_the_Beach_intro, Mr_Meaner (`$18`),
    Off_the_Cuff, One_on_One_Jordan_vs_Bird, Powerplay_Hockey_USA_vs_USSR, Rock_Tells_the_Tale (all
    level 8), and BMX_Kidz, Ricochet, Skate_or_Die_intro (level 10);
* the shape does not match on the other 7 informative files, and none of them is a constant level:
  * faders, where the original sweeps 0..15 through a clamped variable (`C9 0F 90 02 A9 0F 8D 18 D4`):
    Confuzion, Sanxion, Zoolook;
  * one-frame init blips, trace [0, 15]: Chain_Reaction, Master_of_Magic, Thing_on_a_Spring;
  * digi engines, held, end-of-frame blind ([0]): After_8, Rikky.

So the source is `Detection.master_volume: int | None` = `data[e + 7] & 0x0F` when
`FILTER_MODE_ENTRY_SHAPE` matches, and `None` when it does not match or the level is `$F`. It is a
primary-path read with no rescue, and it consults no trace.

## Where the command goes

GoatTracker's `CMD_SETMASTERVOL` (13, `DXY`; `gcommon.h:17`) sets the global `masterfader` when the
parameter is below `$10` (`gplay.c:478-481`, `689-691`; `player.s mt_tick0_d`). It acts on tick 0,
before that same call's `$D418` store (`player.s mt_masterfader`), so frame 0 already plays the
level. It persists until the next `D` command. gt2reloc includes the routine only when a pattern
uses it (`greloc.c:877-878` clears `nosetmastervol`), and no current output uses it.

**Placement:** emit one `D0v` per subtune on **row 0 of the entry pattern of the lowest voice ≥ 1**
whose row-0 command column is free **and** which is not any subtune's voice-0 entry pattern.
Measured on the shipped presets (`row0.py`):

| song | v0 entry row 0 | v1 entry row 0 | v2 entry row 0 |
|---|---|---|---|
| Mega_Apocalypse | pattern 00, `F03` (tempo) | pattern 01, **free** | pattern 00 (shared with v0) |
| Pygmies_Revenge | pattern 25, `F04` (tempo) | pattern 27, **free** | pattern 25 (shared with v0) |

Both songs place the command on voice 1, row 0. A pattern that other positions reuse re-applies
the same constant level on each playthrough, which is idempotent.

**Fallback:** if no row 0 qualifies, use row 1 of voice 1's entry pattern if it is free. That costs
one frame at `$F`, and the `vol` column's init-blip tolerance already reads one frame as ≈1.0.
Log it. Otherwise emit nothing and log the subtune by name. Never move or overwrite a command.

## How it coexists with the row-0 rule

The rule (CLAUDE.md, "Row 0's command column belongs to the subtune's clock"): `apply_tempos` skips
a pattern whose command column is occupied, so a row-0 command costs that subtune its
`CMD_SETTEMPO`, and a new row-0 command must declare itself in `patterns.TEMPO_OVERWRITABLE` as
well as `ONE_SHOT_COMMANDS`.

The volume command takes the precedent `patterns.py` already documents for
`CMD_SETFILTERCTRL`/`CMD_SETFILTERPTR` ("DELIBERATELY IN NEITHER SET"). It is written in
`build_sng`, **after** `apply_tempos` and after every pattern pass, so every tempo is already in
place before it is written. It never reaches the decoder's hold loop. It refuses any occupied row
and any pattern that is a voice-0 entry, so it cannot stand where `apply_tempo` writes, and
`apply_tempos`' multi-voice case has already run by then.

It therefore goes in **neither** set. Declaring it `TEMPO_OVERWRITABLE` would describe an
interaction that cannot happen. The exception must be written into `patterns.py`'s
"DELIBERATELY IN NEITHER SET" note and into CLAUDE.md's rule line, quoting the rule, and it is
pinned by a test (below).

## Option and wiring

`convert(..., master_volume: bool = False)`. Default off, so Commando.sng and every unadopted song
are byte-identical. The three places: the signature, `presets.py` `FIXED`, and `fidelity._preset_opts`
(auto-derived; `tests/test_preset_passthrough.py`). Adopt it per song in presets.json for
Mega_Apocalypse and Pygmies_Revenge only. Held files are not adopted, because the hold forbids
work aimed at them.

## The A/B that proves it

1. `fidelity.py <corpus> -t 180 --presets <copy with master_volume on the two songs> --sound` against
   build/fidelity.json, expecting:
   * both songs: `vol` 0.0 → ≥ 0.99, `vol_ratio` 1.875 → 1.0;
   * `loud_ratio` ≈ 1.92/1.875 = 1.02 and 1.78/1.875 = 0.95;
   * `aud` up, with no other scored column down by more than the noise floor.
2. Corpus byte-hash under presets: movers are exactly {Mega_Apocalypse, Pygmies_Revenge}, with
   Commando's default build unchanged (`tests/test_commando.py`).
3. Tests (new `tests/test_master_volume.py`):
   * `Detection.master_volume` equals the traced constant level on every file the census lists. The
     table is pinned by name, and held files are included as a read, not worked.
   * With the option on vs off, every subtune's `CMD_SETTEMPO` count and row are unchanged.
   * No `D` command sits on row 0 of any subtune's voice-0 entry pattern.
   * Exactly one `D0v` per subtune on the two songs.
   * SABOTAGE: write the command on voice 0 row 0 → the tempo test fails; drop the `& 0x0F` → the level
     test fails.

## Out of scope (separate tasks)

* Faders (Confuzion, Sanxion, Zoolook): the original moves the level through every value, so this
  needs per-frame `D` commands on the frames the fade lands on, a different mechanism.
  Confuzion's residual (+0.156, residual.md) makes it the strongest lead.
* The init blips (Chain_Reaction, Master_of_Magic, Thing_on_a_Spring) need nothing: one frame at
  `$0`.
