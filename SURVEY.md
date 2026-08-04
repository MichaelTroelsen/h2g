# H2G conversion survey — Rob Hubbard SID corpus

- Converter: `h2g` **0.5.4**
- Corpus: `C:\Users\mit\claude\c64server\SIDM2\SID\Hubbard_Rob`
- Files tested: **95**
- Pattern slicing: **94 rows** (original VB6 behaviour)
- Converted: **63** (66%) — Failed: **32**

> "Converted" means the converter produced a `.sng` without erroring. It does **not** mean the output is musically correct. Only the repo's own `Commando.sid` is verified byte-exact against the original VB6 tool; note that the corpus copy of `Commando.sid` is a *different rip* (4165 B / 19 subtunes vs the repo's 4222 B / 3 subtunes), so its row here is not comparable to that fixture.

Regenerate with: `python survey.py "C:\Users\mit\claude\c64server\SIDM2\SID\Hubbard_Rob" -o SURVEY.md`

## Failure breakdown by stage

| Stage | Files | Meaning |
|---|---:|---|
| detect | 20 | no known player fingerprint matched |
| patterns | 11 | pattern decode/slicing hit a Goattracker limit |
| tracks | 1 | orderlist decode failed (usually unknown track-read version) |

## Detected player variant (successful conversions)

| Version | Player family | Files |
|---:|---|---:|
| 0 | Warhawk | 25 |
| 1 | Last V8 | 8 |
| 2 | Auf Wiedersehen Monty | 7 |
| 3 | Samantha Fox | 1 |
| 4 | ACE 2 | 1 |
| 5 | Battle of Britain | 7 |
| 6 | Mega Apocalypse | 1 |
| 7 | IK+ | 13 |

## Findings

- **63/95 produced output.** The ceiling is structural: detection only recognises 16 hard-coded game fingerprints, so anything outside that set is unconvertible by construction.
- **11 failures are capacity, not comprehension.** These files detect cleanly (all four passes green) and fail only because the tune exceeds a Goattracker limit — 208 patterns or a 255-byte orderlist. They are the most recoverable group: splitting the orderlist across subtunes would convert them.
- **6 conversions report more than 50 instruments** (`Bangkok_Knights.sid`, `Nineteen.sid`, `Sanxion.sid`, `Thundercats.sid`, `W_A_R_Preview.sid`, `Zoolook.sid`), which the writer then clamps. Hubbard tunes do not plausibly use that many, so the waveform-sniffing table-end heuristic is over-reading past the real instrument table. Output is written but the instrument set should be treated as unreliable — see the flag in the table below.

## Converted (63)

| File | Title | Subtunes | Instr | Patterns | Ver | .sng bytes | Flag |
|---|---|---:|---:|---:|---:|---:|---|
| `5_Title_Tunes.sid` | 5 Title Tunes | 5 | 17 | 38 | 5 | 8932 |  |
| `ACE_II.sid` | ACE II | 1 | 13 | 58 | 4 | 15504 |  |
| `Action_Biker.sid` | Action Biker | 3 | 13 | 73 | 0 | 18319 |  |
| `Arcade_Classics.sid` | Arcade Classics | 1 | 24 | 110 | 7 | 32913 |  |
| `Auf_Wiedersehen_Monty.sid` | Auf Wiedersehen Monty | 13 | 17 | 169 | 2 | 42841 |  |
| `Bangkok_Knights.sid` | Bangkok Knights | 1 | 59 | 52 | 7 | 14797 | instr over-read |
| `Battle_of_Britain.sid` | Battle of Britain | 1 | 20 | 110 | 5 | 36024 |  |
| `BMX_Kidz.sid` | BMX Kidz | 4 | 23 | 90 | 2 | 29783 |  |
| `Bump_Set_Spike.sid` | Bump Set Spike | 2 | 26 | 78 | 0 | 19770 |  |
| `Chimera.sid` | Chimera | 4 | 9 | 63 | 1 | 12468 |  |
| `Commando.sid` | Commando | 19 | 14 | 65 | 0 | 15792 |  |
| `Confuzion.sid` | Confuzion | 1 | 12 | 56 | 5 | 15499 |  |
| `Crazy_Comets.sid` | Crazy Comets | 17 | 24 | 80 | 1 | 20315 |  |
| `Deep_Strike.sid` | Deep Strike | 1 | 25 | 56 | 7 | 13788 |  |
| `Devils_Galop.sid` | Devils Galop | 1 | 16 | 1 | 5 | 755 |  |
| `Flash_Gordon.sid` | Flash Gordon | 9 | 37 | 147 | 0 | 47099 |  |
| `Food_Feud.sid` | Food Feud | 1 | 29 | 57 | 0 | 15807 |  |
| `Formula_1_Simulator.sid` | Formula 1 Simulator | 2 | 16 | 37 | 0 | 10750 |  |
| `Game_Killer.sid` | Game Killer | 1 | 12 | 38 | 1 | 9400 |  |
| `Geoff_Capes_Strongman_Challenge.sid` | Geoff Capes Strongman Challenge | 24 | 22 | 55 | 0 | 11237 |  |
| `Gerry_the_Germ.sid` | Gerry the Germ | 23 | 28 | 171 | 0 | 42085 |  |
| `Hollywood_or_Bust.sid` | Hollywood or Bust | 10 | 21 | 84 | 0 | 22737 |  |
| `Human_Race.sid` | The Human Race | 5 | 25 | 102 | 1 | 22598 |  |
| `Hunter_Patrol.sid` | Hunter Patrol | 1 | 33 | 78 | 5 | 21844 |  |
| `I_Ball.sid` | I, Ball | 4 | 1 | 35 | 7 | 476 |  |
| `IK_plus.sid` | IK+ | 3 | 31 | 51 | 7 | 13290 |  |
| `Kings_of_the_Beach_ingame.sid` | Kings of the Beach (ingame) | 7 | 11 | 106 | 2 | 35477 |  |
| `Las_Vegas_Video_Poker.sid` | Las Vegas Video Poker | 16 | 26 | 81 | 0 | 12435 |  |
| `Last_V8.sid` | The Last V8 | 17 | 34 | 66 | 1 | 21204 |  |
| `Last_V8_C128_version.sid` | The Last V8 (C128 version) | 18 | 34 | 56 | 1 | 17432 |  |
| `Lightforce.sid` | Lightforce | 1 | 45 | 64 | 0 | 20663 |  |
| `Master_of_Magic.sid` | The Master of Magic | 3 | 18 | 85 | 0 | 22346 |  |
| `Mega_Apocalypse.sid` | Mega Apocalypse | 11 | 43 | 60 | 6 | 18127 |  |
| `Mozart.sid` | Mozart | 1 | 20 | 118 | 0 | 36219 |  |
| `Nemesis_the_Warlock.sid` | Nemesis the Warlock | 15 | 33 | 74 | 7 | 17564 |  |
| `Nineteen.sid` | Nineteen | 1 | 59 | 46 | 7 | 12500 | instr over-read |
| `Ninja.sid` | Ninja | 1 | 14 | 26 | 1 | 6076 |  |
| `One_Man_and_his_Droid.sid` | One Man and his Droid | 14 | 16 | 74 | 5 | 21839 |  |
| `Pandora.sid` | Pandora | 1 | 33 | 67 | 7 | 18636 |  |
| `Phantoms_of_the_Asteroid.sid` | Phantoms of the Asteroid | 4 | 0 | 96 | 1 | 26029 |  |
| `Powerplay_Hockey_USA_vs_USSR.sid` | Powerplay Hockey: USA vs USSR | 10 | 25 | 57 | 2 | 16149 |  |
| `Proteus.sid` | Proteus | 1 | 18 | 46 | 0 | 12143 |  |
| `Rasputin.sid` | Rasputin | 18 | 15 | 65 | 0 | 15933 |  |
| `Ricochet.sid` | Ricochet | 1 | 33 | 136 | 7 | 45656 |  |
| `Saboteur_II.sid` | Saboteur II | 1 | 17 | 54 | 2 | 13548 |  |
| `Samantha_Fox_Strip_Poker.sid` | Samantha Fox Strip Poker | 14 | 25 | 83 | 3 | 15322 |  |
| `Sanxion.sid` | Sanxion | 2 | 60 | 69 | 0 | 22773 | instr over-read |
| `Shockway_Rider.sid` | Shockway Rider | 1 | 27 | 76 | 7 | 20853 |  |
| `Sigma_Seven.sid` | Sigma Seven | 1 | 17 | 25 | 0 | 6798 |  |
| `Skate_or_Die_intro.sid` | Skate or Die (intro) | 1 | 17 | 53 | 7 | 13683 |  |
| `Spellbound.sid` | Spellbound | 13 | 26 | 111 | 0 | 36575 |  |
| `Star_Paws.sid` | Star Paws | 3 | 41 | 53 | 7 | 14032 |  |
| `Tarzan.sid` | Tarzan | 12 | 40 | 53 | 0 | 13276 |  |
| `Thanatos.sid` | Thanatos | 1 | 20 | 25 | 0 | 8736 |  |
| `Thing_on_a_Spring.sid` | Thing on a Spring | 17 | 16 | 66 | 5 | 19570 |  |
| `Thrust.sid` | Thrust | 1 | 29 | 63 | 0 | 17613 |  |
| `Thundercats.sid` | Thundercats | 16 | 59 | 41 | 7 | 12784 | instr over-read |
| `Trans-Atlantic_Balloon_Challenge.sid` | Trans-Atlantic Balloon Challenge | 1 | 20 | 55 | 2 | 13114 |  |
| `W_A_R_Preview.sid` | W.A.R. Preview | 1 | 57 | 68 | 0 | 20702 | instr over-read |
| `Warhawk.sid` | Warhawk | 18 | 29 | 70 | 0 | 17582 |  |
| `Wiz.sid` | Wiz | 3 | 41 | 75 | 2 | 16979 |  |
| `Zoids.sid` | Zoids | 3 | 16 | 59 | 0 | 19129 |  |
| `Zoolook.sid` | Zoolook | 1 | 59 | 37 | 0 | 11549 | instr over-read |

## Not converted (32)

| File | Title | Stage | Instr? | Trk? | Pat? | Ver? | Reason |
|---|---|---|:-:|:-:|:-:|:-:|---|
| `After_8.sid` | After 8 | detect | y | - | - | y | no player detected (missing: tracks, patterns) |
| `Casio_Extended.sid` | Casio (Extended) | detect | - | - | - | - | no player detected (missing: tracks, patterns) |
| `Delta_Mix-E-Load_loader.sid` | Delta Mix-E-Load (loader) | detect | y | y | - | y | no player detected (missing: patterns) |
| `Dont_Step_on_My_Wire.sid` | Don't Step on My Wire | detect | - | - | - | - | no player detected (missing: tracks, patterns) |
| `Era_of_Eidolon.sid` | Era of Eidolon | detect | - | - | - | - | no player detected (missing: tracks, patterns) |
| `Go_Go_Dash.sid` | Go Go Dash | detect | y | - | - | - | no player detected (missing: tracks, patterns) |
| `Kings_of_the_Beach_intro.sid` | Kings of the Beach (intro) | detect | y | - | - | y | no player detected (missing: tracks, patterns) |
| `Lakers_vs_Celtics.sid` | Lakers vs Celtics | detect | y | - | - | - | no player detected (missing: tracks, patterns) |
| `Lion_Heart.sid` | The Lion Heart | detect | y | - | - | - | no player detected (missing: tracks, patterns) |
| `Mr_Meaner.sid` | Mr Meaner | detect | y | - | - | y | no player detected (missing: tracks, patterns) |
| `Off_the_Cuff.sid` | Off the Cuff | detect | y | - | - | y | no player detected (missing: tracks, patterns) |
| `Pacific_Coast.sid` | Pacific Coast | detect | y | - | - | - | no player detected (missing: tracks, patterns) |
| `Pygmies_Revenge.sid` | Pygmies Revenge | detect | y | - | - | y | no player detected (missing: tracks, patterns) |
| `Radio_ACE.sid` | Radio ACE | detect | y | - | - | - | no player detected (missing: tracks, patterns) |
| `Rikky.sid` | Rikky | detect | y | - | - | y | no player detected (missing: tracks, patterns) |
| `Robs_Life.sid` | Rob's Life | detect | - | - | - | - | no player detected (missing: tracks, patterns) |
| `Rock_Tells_the_Tale.sid` | The Rock Tells the Tale | detect | y | - | - | y | no player detected (missing: tracks, patterns) |
| `Sun_Never_Shines.sid` | Sun Never Shines | detect | y | - | - | - | no player detected (missing: tracks, patterns) |
| `Task_Force.sid` | Task Force | detect | - | - | - | - | no player detected (missing: tracks, patterns) |
| `Up_up_and_Away.sid` | Up, up & Away! | detect | - | - | - | - | no player detected (missing: tracks, patterns) |
| `Chicken_Song.sid` | The Chicken Song | patterns | y | y | y | y | TRACKLIST TOO LONG, CAN'T EXPORT TO GOATTRACKER |
| `Commodore_64_Music_Examples.sid` | Commodore 64 Music Examples | patterns | y | y | y | y | TRACKLIST TOO LONG, CAN'T EXPORT TO GOATTRACKER |
| `Delta.sid` | Delta | patterns | y | y | y | y | TOO MANY NEW PATTERN CREATED, CAN'T EXPORT TO GOATTRACKER |
| `Dragons_Lair_Part_II.sid` | Dragon's Lair Part II | patterns | y | y | y | y | TOO MANY NEW PATTERN CREATED, CAN'T EXPORT TO GOATTRACKER |
| `Gremlins.sid` | Gremlins | patterns | y | y | y | y | TRACKLIST TOO LONG, CAN'T EXPORT TO GOATTRACKER |
| `International_Karate.sid` | International Karate | patterns | y | y | y | y | TRACKLIST TOO LONG, CAN'T EXPORT TO GOATTRACKER |
| `Kentilla.sid` | Kentilla | patterns | y | y | y | y | TRACKLIST TOO LONG, CAN'T EXPORT TO GOATTRACKER |
| `Knucklebusters.sid` | Knucklebusters | patterns | y | y | y | y | TRACKLIST TOO LONG, CAN'T EXPORT TO GOATTRACKER |
| `Monty_on_the_Run.sid` | Monty on the Run | patterns | y | y | y | y | TRACKLIST TOO LONG, CAN'T EXPORT TO GOATTRACKER |
| `One_on_One_Jordan_vs_Bird.sid` | One on One: Jordan vs Bird | patterns | y | y | y | y | TOO MANY NEW PATTERN CREATED, CAN'T EXPORT TO GOATTRACKER |
| `W_A_R.sid` | W.A.R. | patterns | y | y | y | y | TOO MANY NEW PATTERN CREATED, CAN'T EXPORT TO GOATTRACKER |
| `Chain_Reaction.sid` | Chain Reaction | tracks | y | y | y | - | ValueError: unsupported/undetected Hubbard player track-read version: $FF |

Columns `Instr?`/`Trk?`/`Pat?`/`Ver?` show which of the four detection passes found their target. A file with tables found but `Ver?` missing has a recognisable data layout and an unrecognised player loop.
