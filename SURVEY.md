# H2G conversion survey — Rob Hubbard SID corpus

- Converter: `h2g` **0.5.20**
- Corpus: `C:\Users\mit\claude\c64server\SIDM2\SID\Hubbard_Rob`
- Files tested: **95**
- Pattern slicing: **94 rows** (original VB6 behaviour)
- Output format: **GTS2** (of GTS2/GTS5) (3-table, original VB6 behaviour; note Goattracker's legacy GTS2 importer overruns its pattern array on the portamento commands this converter emits — prefer `--format gts5` for files you will open in Goattracker)
- Converted: **62** (65%) — Failed: **33**

> "Converted" means the converter produced a `.sng` without erroring. It does **not** mean the output is musically correct. Only the repo's own `Commando.sid` is verified byte-exact against the original VB6 tool; note that the corpus copy of `Commando.sid` is a *different rip* (4165 B / 19 subtunes vs the repo's 4222 B / 3 subtunes), so its row here is not comparable to that fixture.

Regenerate with: `python survey.py "C:\Users\mit\claude\c64server\SIDM2\SID\Hubbard_Rob" -o SURVEY.md`

## Failure breakdown by stage

| Stage | Files | Meaning |
|---|---:|---|
| detect | 21 | no known player fingerprint matched |
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
| 7 | IK+ | 12 |

## Findings

- **62/95 produced output.** The ceiling is structural: detection only recognises 16 hard-coded game fingerprints, so anything outside that set is unconvertible by construction.
- **11 failures are capacity, not comprehension.** These files detect cleanly (all four passes green) and fail only because the tune exceeds a Goattracker limit — 208 patterns or a 255-byte orderlist. They are the most recoverable group: splitting the orderlist across subtunes would convert them.
- **6 tunes carry more than 50 instruments and lose the excess** (`Bangkok_Knights.sid`, `Nineteen.sid`, `Sanxion.sid`, `Thundercats.sid`, `W_A_R_Preview.sid`, `Zoolook.sid`) — 53 real instruments dropped in total. These tables are genuine, not a detection artefact: the records are mostly distinct, and a set of them recurs byte-identically across these files, i.e. a shared Hubbard instrument bank appended to the player. The limit is Goattracker's: each instrument costs 5 wavetable entries against a 255-entry table addressed by a single length byte, so at most 51 are representable. Patterns referencing a dropped slot play with an undefined instrument — see the flag in the table below.

## Converted (62)

| File | Title | Source | Player | Ver | Subtunes | Instr | Patterns | .sng bytes | Flag |
|---|---|---|---|---:|---|---:|---:|---:|---|
| `5_Title_Tunes.sid` | 5 Title Tunes | PSID v2 | Battle of Britain | 5 | 1 (hdr 5) | 17 | 38 | 8932 |  |
| `ACE_II.sid` | ACE II | PSID v2 | ACE 2 | 4 | 1 | 13 | 58 | 15596 |  |
| `Action_Biker.sid` | Action Biker | PSID v2 | Warhawk | 0 | 3 | 13 | 73 | 18323 |  |
| `Arcade_Classics.sid` | Arcade Classics | RSID v2 | IK+ | 7 | 1 | 24 | 110 | 33357 |  |
| `Auf_Wiedersehen_Monty.sid` | Auf Wiedersehen Monty | PSID v2 | Auf Wiedersehen Monty | 2 | 13 | 17 | 169 | 42861 |  |
| `Bangkok_Knights.sid` | Bangkok Knights | PSID v2 | IK+ | 7 | 1 | 59 | 52 | 14845 | 9 instr dropped |
| `Battle_of_Britain.sid` | Battle of Britain | PSID v2 | Battle of Britain | 5 | 1 | 20 | 110 | 36024 |  |
| `BMX_Kidz.sid` | BMX Kidz | RSID v2 | Auf Wiedersehen Monty | 2 | 1 (hdr 4) | 23 | 93 | 30998 |  |
| `Bump_Set_Spike.sid` | Bump Set Spike | PSID v2 | Warhawk | 0 | 2 | 26 | 78 | 19770 |  |
| `Chimera.sid` | Chimera | RSID v2 | Last V8 | 1 | 2 (hdr 4) | 9 | 65 | 13878 |  |
| `Commando.sid` | Commando | PSID v2 | Warhawk | 0 | 18 (hdr 19) | 14 | 65 | 15792 |  |
| `Confuzion.sid` | Confuzion | PSID v2 | Battle of Britain | 5 | 1 | 12 | 56 | 15599 |  |
| `Crazy_Comets.sid` | Crazy Comets | PSID v2 | Last V8 | 1 | 17 | 24 | 80 | 20315 |  |
| `Deep_Strike.sid` | Deep Strike | PSID v2 | IK+ | 7 | 1 | 25 | 56 | 13808 |  |
| `Devils_Galop.sid` | Devils Galop | PSID v2 | Battle of Britain | 5 | 1 | 16 | 1 | 755 |  |
| `Flash_Gordon.sid` | Flash Gordon | PSID v2 | Warhawk | 0 | 9 | 37 | 147 | 47099 |  |
| `Food_Feud.sid` | Food Feud | PSID v2 | Warhawk | 0 | 1 | 29 | 57 | 15999 |  |
| `Formula_1_Simulator.sid` | Formula 1 Simulator | PSID v2 | Warhawk | 0 | 1 (hdr 2) | 16 | 37 | 10750 |  |
| `Game_Killer.sid` | Game Killer | PSID v2 | Last V8 | 1 | 1 | 12 | 38 | 9400 |  |
| `Geoff_Capes_Strongman_Challenge.sid` | Geoff Capes Strongman Challenge | PSID v2 | Warhawk | 0 | 21 (hdr 24) | 22 | 55 | 11253 |  |
| `Gerry_the_Germ.sid` | Gerry the Germ | PSID v2 | Warhawk | 0 | 7 (hdr 23) | 28 | 171 | 42153 |  |
| `Hollywood_or_Bust.sid` | Hollywood or Bust | PSID v2 | Warhawk | 0 | 3 (hdr 10) | 21 | 84 | 23105 |  |
| `Human_Race.sid` | The Human Race | PSID v2 | Last V8 | 1 | 5 | 25 | 102 | 23230 |  |
| `Hunter_Patrol.sid` | Hunter Patrol | PSID v2 | Battle of Britain | 5 | 1 | 33 | 78 | 21844 |  |
| `IK_plus.sid` | IK+ | PSID v2 | IK+ | 7 | 1 (hdr 3) | 31 | 51 | 13302 |  |
| `Kings_of_the_Beach_ingame.sid` | Kings of the Beach (ingame) | PSID v2 | Auf Wiedersehen Monty | 2 | 7 | 11 | 106 | 35733 |  |
| `Las_Vegas_Video_Poker.sid` | Las Vegas Video Poker | PSID v2 | Warhawk | 0 | 16 | 26 | 81 | 12483 |  |
| `Last_V8.sid` | The Last V8 | RSID v2 | Last V8 | 1 | 12 (hdr 17) | 34 | 66 | 21272 |  |
| `Last_V8_C128_version.sid` | The Last V8 (C128 version) | RSID v2 | Last V8 | 1 | 12 (hdr 18) | 34 | 56 | 17432 |  |
| `Lightforce.sid` | Lightforce | PSID v2 | Warhawk | 0 | 1 | 45 | 64 | 20663 |  |
| `Master_of_Magic.sid` | The Master of Magic | PSID v2 | Warhawk | 0 | 3 | 18 | 85 | 22346 |  |
| `Mega_Apocalypse.sid` | Mega Apocalypse | RSID v2 | Mega Apocalypse | 6 | 11 | 43 | 60 | 18127 |  |
| `Mozart.sid` | Mozart | PSID v2 | Warhawk | 0 | 1 | 20 | 118 | 36219 |  |
| `Nemesis_the_Warlock.sid` | Nemesis the Warlock | PSID v2 | IK+ | 7 | 15 | 33 | 74 | 17564 |  |
| `Nineteen.sid` | Nineteen | PSID v2 | IK+ | 7 | 1 | 59 | 46 | 12596 | 9 instr dropped |
| `Ninja.sid` | Ninja | PSID v2 | Last V8 | 1 | 1 | 14 | 26 | 6076 |  |
| `One_Man_and_his_Droid.sid` | One Man and his Droid | PSID v2 | Battle of Britain | 5 | 13 (hdr 14) | 16 | 74 | 21839 |  |
| `Pandora.sid` | Pandora | PSID v2 | IK+ | 7 | 1 | 33 | 67 | 19072 |  |
| `Phantoms_of_the_Asteroid.sid` | Phantoms of the Asteroid | PSID v2 | Last V8 | 1 | 4 | 0 | 96 | 26029 |  |
| `Powerplay_Hockey_USA_vs_USSR.sid` | Powerplay Hockey: USA vs USSR | RSID v2 | Auf Wiedersehen Monty | 2 | 9 (hdr 10) | 25 | 57 | 16149 |  |
| `Proteus.sid` | Proteus | PSID v2 | Warhawk | 0 | 1 | 18 | 46 | 12143 |  |
| `Rasputin.sid` | Rasputin | PSID v2 | Warhawk | 0 | 17 (hdr 18) | 15 | 65 | 15997 |  |
| `Ricochet.sid` | Ricochet | RSID v2 | IK+ | 7 | 1 | 33 | 138 | 46266 |  |
| `Saboteur_II.sid` | Saboteur II | PSID v2 | Auf Wiedersehen Monty | 2 | 1 | 17 | 54 | 13804 |  |
| `Samantha_Fox_Strip_Poker.sid` | Samantha Fox Strip Poker | PSID v2 | Samantha Fox | 3 | 14 | 25 | 83 | 15330 |  |
| `Sanxion.sid` | Sanxion | PSID v2 | Warhawk | 0 | 1 (hdr 2) | 60 | 69 | 22773 | 10 instr dropped |
| `Shockway_Rider.sid` | Shockway Rider | PSID v2 | IK+ | 7 | 1 | 27 | 76 | 20929 |  |
| `Sigma_Seven.sid` | Sigma Seven | PSID v2 | Warhawk | 0 | 1 | 17 | 25 | 6798 |  |
| `Skate_or_Die_intro.sid` | Skate or Die (intro) | RSID v2 | IK+ | 7 | 1 | 17 | 53 | 14015 |  |
| `Spellbound.sid` | Spellbound | PSID v2 | Warhawk | 0 | 13 | 26 | 111 | 36687 |  |
| `Star_Paws.sid` | Star Paws | PSID v2 | IK+ | 7 | 3 | 41 | 53 | 14304 |  |
| `Tarzan.sid` | Tarzan | RSID v2 | Warhawk | 0 | 11 (hdr 12) | 40 | 53 | 13276 |  |
| `Thanatos.sid` | Thanatos | PSID v2 | Warhawk | 0 | 1 | 20 | 25 | 8744 |  |
| `Thing_on_a_Spring.sid` | Thing on a Spring | PSID v2 | Battle of Britain | 5 | 13 (hdr 17) | 16 | 66 | 19570 |  |
| `Thrust.sid` | Thrust | PSID v2 | Warhawk | 0 | 1 | 29 | 63 | 17613 |  |
| `Thundercats.sid` | Thundercats | PSID v2 | IK+ | 7 | 11 (hdr 16) | 59 | 41 | 12784 | 9 instr dropped |
| `Trans-Atlantic_Balloon_Challenge.sid` | Trans-Atlantic Balloon Challenge | PSID v2 | Auf Wiedersehen Monty | 2 | 1 | 20 | 56 | 13537 |  |
| `W_A_R_Preview.sid` | W.A.R. Preview | PSID v2 | Warhawk | 0 | 1 | 57 | 68 | 20702 | 7 instr dropped |
| `Warhawk.sid` | Warhawk | PSID v2 | Warhawk | 0 | 18 | 29 | 70 | 17666 |  |
| `Wiz.sid` | Wiz | PSID v2 | Auf Wiedersehen Monty | 2 | 3 | 41 | 75 | 17003 |  |
| `Zoids.sid` | Zoids | PSID v2 | Warhawk | 0 | 3 | 16 | 59 | 19129 |  |
| `Zoolook.sid` | Zoolook | PSID v2 | Warhawk | 0 | 1 | 59 | 37 | 11549 | 9 instr dropped |

`Source` is the input file's own header version — the original player-file format, distinct from both the Hubbard engine variant and the Goattracker output format. `Player`/`Ver` are the detected Hubbard player-engine variant and its track-read version number. `Subtunes` is how many actually reach the `.sng`; where that differs from the PSID header's claim the header value follows in brackets, and the gap is subtunes whose orderlist pointers resolve outside the file (the track table has no length field, so the header routinely over-claims).

## Not converted (33)

| File | Title | Source | Stage | Player | Sub (hdr) | Instr? | Trk? | Pat? | Reason |
|---|---|---|---|---|---:|:-:|:-:|:-:|---|
| `After_8.sid` | After 8 | RSID v2 | detect | Auf Wiedersehen Monty | 1 | y | - | - | no player detected (missing: tracks, patterns) |
| `Casio_Extended.sid` | Casio (Extended) | PSID v2 | detect | - | 1 | - | - | - | no player detected (missing: tracks, patterns) |
| `Delta_Mix-E-Load_loader.sid` | Delta Mix-E-Load (loader) | PSID v2 | detect | Warhawk | 16 | y | y | - | no player detected (missing: patterns) |
| `Dont_Step_on_My_Wire.sid` | Don't Step on My Wire | PSID v2 | detect | - | 1 | - | - | - | no player detected (missing: tracks, patterns) |
| `Era_of_Eidolon.sid` | Era of Eidolon | PSID v2 | detect | - | 1 | - | - | - | no player detected (missing: tracks, patterns) |
| `Go_Go_Dash.sid` | Go Go Dash | PSID v2 | detect | - | 1 | y | - | - | no player detected (missing: tracks, patterns) |
| `I_Ball.sid` | I, Ball | RSID v2 | detect | IK+ | 4 | - | - | - | no player detected (missing: tracks, patterns) |
| `Kings_of_the_Beach_intro.sid` | Kings of the Beach (intro) | RSID v2 | detect | IK+ | 1 | y | - | - | no player detected (missing: tracks, patterns) |
| `Lakers_vs_Celtics.sid` | Lakers vs Celtics | PSID v2 | detect | - | 1 | y | - | - | no player detected (missing: tracks, patterns) |
| `Lion_Heart.sid` | The Lion Heart | PSID v2 | detect | - | 1 | y | - | - | no player detected (missing: tracks, patterns) |
| `Mr_Meaner.sid` | Mr Meaner | RSID v2 | detect | Auf Wiedersehen Monty | 1 | y | - | - | no player detected (missing: tracks, patterns) |
| `Off_the_Cuff.sid` | Off the Cuff | RSID v2 | detect | Auf Wiedersehen Monty | 1 | y | - | - | no player detected (missing: tracks, patterns) |
| `Pacific_Coast.sid` | Pacific Coast | PSID v2 | detect | - | 1 | y | - | - | no player detected (missing: tracks, patterns) |
| `Pygmies_Revenge.sid` | Pygmies Revenge | PSID v2 | detect | Auf Wiedersehen Monty | 1 | y | - | - | no player detected (missing: tracks, patterns) |
| `Radio_ACE.sid` | Radio ACE | PSID v2 | detect | - | 1 | y | - | - | no player detected (missing: tracks, patterns) |
| `Rikky.sid` | Rikky | RSID v2 | detect | Auf Wiedersehen Monty | 1 | y | - | - | no player detected (missing: tracks, patterns) |
| `Robs_Life.sid` | Rob's Life | PSID v2 | detect | - | 3 | - | - | - | no player detected (missing: tracks, patterns) |
| `Rock_Tells_the_Tale.sid` | The Rock Tells the Tale | RSID v2 | detect | Auf Wiedersehen Monty | 1 | y | - | - | no player detected (missing: tracks, patterns) |
| `Sun_Never_Shines.sid` | Sun Never Shines | PSID v2 | detect | - | 1 | y | - | - | no player detected (missing: tracks, patterns) |
| `Task_Force.sid` | Task Force | PSID v2 | detect | - | 1 | - | - | - | no player detected (missing: tracks, patterns) |
| `Up_up_and_Away.sid` | Up, up & Away! | PSID v2 | detect | - | 5 | - | - | - | no player detected (missing: tracks, patterns) |
| `Chicken_Song.sid` | The Chicken Song | PSID v2 | patterns | Warhawk | 1 | y | y | y | TRACKLIST TOO LONG, CAN'T EXPORT TO GOATTRACKER |
| `Commodore_64_Music_Examples.sid` | Commodore 64 Music Examples | PSID v2 | patterns | Battle of Britain | 15 | y | y | y | TRACKLIST TOO LONG, CAN'T EXPORT TO GOATTRACKER |
| `Delta.sid` | Delta | PSID v2 | patterns | Warhawk | 13 | y | y | y | TOO MANY NEW PATTERN CREATED, CAN'T EXPORT TO GOATTRACKER |
| `Dragons_Lair_Part_II.sid` | Dragon's Lair Part II | PSID v2 | patterns | Warhawk | 10 | y | y | y | TOO MANY NEW PATTERN CREATED, CAN'T EXPORT TO GOATTRACKER |
| `Gremlins.sid` | Gremlins | PSID v2 | patterns | Battle of Britain | 26 | y | y | y | TRACKLIST TOO LONG, CAN'T EXPORT TO GOATTRACKER |
| `International_Karate.sid` | International Karate | PSID v2 | patterns | Warhawk | 1 | y | y | y | TRACKLIST TOO LONG, CAN'T EXPORT TO GOATTRACKER |
| `Kentilla.sid` | Kentilla | PSID v2 | patterns | Warhawk | 1 | y | y | y | TRACKLIST TOO LONG, CAN'T EXPORT TO GOATTRACKER |
| `Knucklebusters.sid` | Knucklebusters | PSID v2 | patterns | Warhawk | 11 | y | y | y | TRACKLIST TOO LONG, CAN'T EXPORT TO GOATTRACKER |
| `Monty_on_the_Run.sid` | Monty on the Run | PSID v2 | patterns | Warhawk | 19 | y | y | y | TRACKLIST TOO LONG, CAN'T EXPORT TO GOATTRACKER |
| `One_on_One_Jordan_vs_Bird.sid` | One on One: Jordan vs Bird | RSID v2 | patterns | Auf Wiedersehen Monty | 4 | y | y | y | TOO MANY NEW PATTERN CREATED, CAN'T EXPORT TO GOATTRACKER |
| `W_A_R.sid` | W.A.R. | PSID v2 | patterns | Warhawk | 9 | y | y | y | TOO MANY NEW PATTERN CREATED, CAN'T EXPORT TO GOATTRACKER |
| `Chain_Reaction.sid` | Chain Reaction | PSID v2 | tracks | - | 1 | y | y | y | ValueError: unsupported/undetected Hubbard player track-read version: $FF |

`Source` is the input file's own header version; `-` means the header was rejected before it could be read. `Player` is the detected player variant, or `-` when the player-version pass found nothing. `Sub (hdr)` is the PSID header's subtune claim — these files produce no `.sng`, so there is no emitted count to compare it against.

Columns `Instr?`/`Trk?`/`Pat?` show which of the three table-locating detection passes found their target. A file with tables found but no `Player` has a recognisable data layout and an unrecognised player loop.
