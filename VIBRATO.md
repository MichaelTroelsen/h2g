# Vibrato census

454 instrument(s) across 82 file(s) whose pitch oscillates on either side. `vib` is a whole-file ratio; this is the same count split by the instrument sounding it, so the rows add to that column rather than re-measuring it.

**Why this is asked before anything is tuned.** The balloon song read `vib` 0.17x and it was taken for a vibrato-rate defect. The one instrument carrying a vibrato byte was within 20% of the original; the missing 1812 reversals were an arpeggio on a global counter that no wavetable can hold (section 7.ttt). A rate that looks wrong may be a mechanism that is absent.

## Instruments reproducing under half the original's oscillation

| file | ADSR | GT | effect | cause | orig | ours |
|---|---|---:|---|---|---:|---:|
| Las_Vegas_Video_Poker.sid | `$0A0C` | - | - | unknown | 2698 | 0 |
| Nemesis_the_Warlock.sid | `$0C0A` | 3 | $2A | alt | 2195 | 134 |
| Kentilla.sid | `$0D5F` | - | - | unknown | 1894 | 0 |
| W_A_R_Preview.sid | `$4AAD` | 2 | $14 | arp | 1717 | 0 |
| IK_plus.sid | `$0A56` | 5 | $14 | arp | 1600 | 0 |
| Chimera.sid | `$0060` | 5 | $0D | plain | 1511 | 0 |
| W_A_R_Preview.sid | `$0900` | 1 | $0A | alt | 1332 | 0 |
| Tarzan.sid | `$7840` | 1 | $2A | alt | 1244 | 0 |
| Knucklebusters.sid | `$0F09` | 20 | $2B | alt | 1107 | 0 |
| Spellbound.sid | `$AFFF` | - | - | unknown | 981 | 0 |
| Flash_Gordon.sid | `$486F` | 4 | $0A | alt | 936 | 0 |
| Spellbound.sid | `$180A` | 8 | $25 | plain | 911 | 0 |
| Thrust.sid | `$9FFF` | - | - | unknown | 882 | 0 |
| Zoolook.sid | `$0F67` | 1 | $0B | alt | 840 | 0 |
| Crazy_Comets.sid | `$0FFF` | - | - | unknown | 827 | 0 |
| W_A_R.sid | `$0900` | 1 | $0A | alt | 821 | 0 |
| Dragons_Lair_Part_II.sid | `$8C00` | 19 | $2A | alt | 764 | 0 |
| Ricochet.sid | `$07E7` | 7 | $01 | plain | 762 | 0 |
| Thrust.sid | `$C08D` | - | - | unknown | 756 | 0 |
| Delta_Mix-E-Load_loader.sid | `$3A98` | 4 | $04 | plain | 742 | 0 |
| Warhawk.sid | `$8D9F` | - | - | unknown | 714 | 0 |
| Last_V8.sid | `$0409` | 2 | $05 | plain | 702 | 0 |
| Last_V8_C128_version.sid | `$0409` | 2 | $05 | plain | 702 | 0 |
| Zoolook.sid | `$0F09` | 2 | $0B | alt | 674 | 0 |
| Bump_Set_Spike.sid | `$0A09` | - | - | unknown | 661 | 0 |
| Chicken_Song.sid | `$0A00` | 6 | $01 | plain | 644 | 0 |
| Commodore_64_Music_Examples.sid | `$5C3A` | - | - | unknown | 623 | 0 |
| Battle_of_Britain.sid | `$0FFF` | - | - | unknown | 616 | 0 |
| One_Man_and_his_Droid.sid | `$077F` | - | - | unknown | 612 | 0 |
| One_Man_and_his_Droid.sid | `$088F` | - | - | unknown | 612 | 0 |
| Kings_of_the_Beach_intro.sid | `$0998` | 6 | $00 | plain | 599 | 0 |
| Deep_Strike.sid | `$0F07` | 8 | $0B | alt | 534 | 0 |
| Chain_Reaction.sid | `$6600` | 9 | $0A | alt | 525 | 0 |
| Zoolook.sid | `$6600` | 9 | $0A | alt | 525 | 0 |
| Bump_Set_Spike.sid | `$0F9E` | - | - | unknown | 518 | 0 |
| Knucklebusters.sid | `$0F0A` | 21 | $2B | alt | 507 | 0 |
| Las_Vegas_Video_Poker.sid | `$6B9A` | - | - | unknown | 498 | 0 |
| Human_Race.sid | `$3C9F` | - | - | unknown | 486 | 0 |
| Powerplay_Hockey_USA_vs_USSR.sid | `$0AC9` | 3 | $00 | plain | 486 | 0 |
| Kings_of_the_Beach_intro.sid | `$0999` | 5 | $10 | arp | 475 | 0 |
| International_Karate.sid | `$6D9F` | - | - | unknown | 443 | 0 |
| Hollywood_or_Bust.sid | `$7800` | 9 | $00 | plain | 441 | 0 |
| Zoids.sid | `$0CCD` | 3 | $0D | plain | 423 | 0 |
| Chimera.sid | `$0F0F` | - | - | unknown | 420 | 0 |
| Star_Paws.sid | `$08E7` | 2 | $01 | plain | 420 | 0 |
| Devils_Galop.sid | `$4A69` | - | - | unknown | 416 | 0 |
| Monty_on_the_Run.sid | `$4A69` | - | - | unknown | 416 | 0 |
| Devils_Galop.sid | `$0909` | 4 | $05 | plain | 411 | 0 |
| Monty_on_the_Run.sid | `$0909` | 4 | $05 | plain | 411 | 0 |
| Food_Feud.sid | `$0A0A` | 5 | $2B | alt | 401 | 0 |
| Proteus.sid | `$0D6D` | 5 | $25 | plain | 397 | 0 |
| Dragons_Lair_Part_II.sid | `$097A` | 2 | $00 | plain | 505 | 111 |
| Powerplay_Hockey_USA_vs_USSR.sid | `$0AA9` | 2 | $00 | plain | 393 | 0 |
| Chain_Reaction.sid | `$7900` | 8 | $0A | alt | 382 | 0 |
| Zoolook.sid | `$7900` | 8 | $0A | alt | 382 | 0 |
| Delta.sid | `$0F09` | 18 | $0B | alt | 375 | 0 |
| Star_Paws.sid | `$09E8` | 3 | $01 | plain | 364 | 0 |
| Sanxion.sid | `$0909` | 3 | $2B | alt | 356 | 0 |
| Deep_Strike.sid | `$0F09` | 4 | $0B | alt | 355 | 0 |
| Off_the_Cuff.sid | `$09C7` | 4 | $04 | plain | 433 | 95 |
| Powerplay_Hockey_USA_vs_USSR.sid | `$0A9B` | 8 | $00 | plain | 330 | 0 |
| Nineteen.sid | `$0797` | 7 | $01 | plain | 483 | 156 |
| Rock_Tells_the_Tale.sid | `$59C9` | 8 | $04 | plain | 326 | 0 |
| Bangkok_Knights.sid | `$0A08` | 3 | $30 | arp | 325 | 0 |
| Spellbound.sid | `$ABCF` | - | - | unknown | 319 | 0 |
| Thrust.sid | `$2FFD` | - | - | unknown | 314 | 0 |
| Zoids.sid | `$59AF` | - | - | unknown | 306 | 0 |
| Proteus.sid | `$0F08` | 8 | $95 | arp | 305 | 0 |
| Last_V8.sid | `$1B6F` | - | - | unknown | 304 | 0 |
| Samantha_Fox_Strip_Poker.sid | `$1A0F` | - | - | unknown | 298 | 0 |
| Last_V8_C128_version.sid | `$1B6F` | - | - | unknown | 296 | 0 |
| One_on_One_Jordan_vs_Bird.sid | `$09F8` | 3 | $01 | plain | 295 | 0 |
| Sanxion.sid | `$0B03` | 2 | $2B | alt | 286 | 0 |
| One_on_One_Jordan_vs_Bird.sid | `$06A6` | 2 | $44 | plain | 282 | 0 |
| Proteus.sid | `$090F` | 4 | $F5 | arp | 281 | 0 |
| Hunter_Patrol.sid | `$0AA0` | 5 | $02 | alt | 387 | 109 |
| Chain_Reaction.sid | `$00F8` | 3 | $10 | arp | 277 | 0 |
| Gremlins.sid | `$2968` | - | - | unknown | 273 | 0 |
| Warhawk.sid | `$0F08` | 8 | $95 | arp | 266 | 0 |
| Game_Killer.sid | `$0A9A` | - | - | unknown | 262 | 0 |
| Knucklebusters.sid | `$0AAD` | 25 | $44 | plain | 261 | 0 |
| Proteus.sid | `$8D9F` | - | - | unknown | 251 | 0 |
| Dragons_Lair_Part_II.sid | `$1979` | 26 | $04 | plain | 245 | 0 |
| Geoff_Capes_Strongman_Challenge.sid | `$195F` | - | - | unknown | 220 | 0 |
| Spellbound.sid | `$0FFA` | 4 | $C5 | plain | 219 | 0 |
| Monty_on_the_Run.sid | `$3FFF` | - | - | unknown | 218 | 0 |
| Phantoms_of_the_Asteroid.sid | `$0786` | 1 | $02 | alt | 335 | 121 |
| Warhawk.sid | `$090E` | 11 | $C5 | plain | 210 | 0 |
| Formula_1_Simulator.sid | `$2C8F` | - | - | unknown | 209 | 0 |
| Flash_Gordon.sid | `$0F07` | 3 | $0B | alt | 208 | 0 |
| Zoids.sid | `$0B0C` | 4 | $05 | plain | 208 | 0 |
| Kentilla.sid | `$096F` | - | - | unknown | 205 | 0 |
| Rasputin.sid | `$0A0A` | 7 | $05 | plain | 204 | 0 |
| Phantoms_of_the_Asteroid.sid | `$0A69` | 2 | $04 | plain | 196 | 0 |
| Warhawk.sid | `$090F` | 4 | $F5 | arp | 195 | 0 |
| Rock_Tells_the_Tale.sid | `$F96E` | 10 | $04 | plain | 190 | 0 |
| Las_Vegas_Video_Poker.sid | `$0B0C` | - | - | unknown | 189 | 0 |
| Ricochet.sid | `$09F9` | 3 | $01 | plain | 184 | 0 |
| One_on_One_Jordan_vs_Bird.sid | `$0ACA` | 4 | $00 | plain | 167 | 0 |
| Last_V8.sid | `$0A09` | 4 | $05 | plain | 163 | 0 |
| Last_V8_C128_version.sid | `$0A09` | 4 | $05 | plain | 162 | 0 |
| Bump_Set_Spike.sid | `$597F` | - | - | unknown | 161 | 0 |
| Commando.sid | `$295F` | - | - | unknown | 155 | 0 |
| Rock_Tells_the_Tale.sid | `$09B9` | 6 | $04 | plain | 172 | 21 |
| Thundercats.sid | `$09F9` | 3 | $01 | plain | 278 | 130 |
| Wiz.sid | `$0909` | 2 | $01 | plain | 144 | 0 |
| International_Karate.sid | `$0BB0` | 3 | $08 | plain | 277 | 136 |
| Last_V8.sid | `$040F` | 1 | $01 | plain | 141 | 0 |
| Last_V8_C128_version.sid | `$040F` | 1 | $01 | plain | 141 | 0 |
| Chimera.sid | `$6986` | - | - | unknown | 138 | 0 |
| Dragons_Lair_Part_II.sid | `$A8C9` | 15 | $04 | plain | 138 | 0 |
| Food_Feud.sid | `$29F9` | 3 | $34 | arp | 137 | 0 |
| After_8.sid | `$099A` | 7 | $00 | plain | 264 | 131 |
| Chimera.sid | `$0C00` | 2 | $04 | plain | 128 | 0 |
| Devils_Galop.sid | `$0FFF` | - | - | unknown | 127 | 0 |
| Kentilla.sid | `$086A` | - | - | unknown | 126 | 0 |
| Star_Paws.sid | `$08C7` | 7 | $01 | plain | 122 | 0 |
| One_Man_and_his_Droid.sid | `$0069` | - | - | unknown | 112 | 0 |
| One_Man_and_his_Droid.sid | `$0089` | - | - | unknown | 112 | 0 |
| Confuzion.sid | `$074F` | - | - | unknown | 110 | 0 |
| Samantha_Fox_Strip_Poker.sid | `$0C8F` | - | - | unknown | 110 | 0 |
| Samantha_Fox_Strip_Poker.sid | `$0909` | - | - | unknown | 101 | 0 |
| Spellbound.sid | `$0F0A` | 13 | $25 | plain | 100 | 0 |
| Chimera.sid | `$7989` | - | - | unknown | 98 | 0 |
| Master_of_Magic.sid | `$496C` | - | - | unknown | 98 | 0 |
| Battle_of_Britain.sid | `$5852` | - | - | unknown | 96 | 0 |
| Battle_of_Britain.sid | `$5862` | - | - | unknown | 96 | 0 |
| Proteus.sid | `$090E` | 11 | $C5 | plain | 96 | 0 |
| Trans-Atlantic_Balloon_Challenge.sid | `$0CD9` | 8 | $10 | arp | 139 | 45 |
| Warhawk.sid | `$080C` | 12 | $C5 | plain | 91 | 0 |
| Las_Vegas_Video_Poker.sid | `$090C` | - | - | unknown | 89 | 0 |
| Battle_of_Britain.sid | `$0C0A` | 4 | $05 | plain | 81 | 0 |
| Bump_Set_Spike.sid | `$6A9F` | - | - | unknown | 81 | 0 |
| Zoids.sid | `$070A` | 5 | $05 | plain | 81 | 0 |
| Spellbound.sid | `$0FFF` | - | - | unknown | 79 | 0 |
| Auf_Wiedersehen_Monty.sid | `$08F8` | 2 | $80 | plain | 144 | 67 |
| Formula_1_Simulator.sid | `$0A0A` | 1 | $55 | arp | 76 | 0 |
| Game_Killer.sid | `$0F0F` | 6 | $05 | plain | 75 | 0 |
| Spellbound.sid | `$299F` | - | - | unknown | 73 | 0 |
| Wiz.sid | `$0627` | 7 | $01 | plain | 72 | 0 |
| Chicken_Song.sid | `$0970` | 10 | $00 | plain | 116 | 48 |
| One_Man_and_his_Droid.sid | `$3FFF` | - | - | unknown | 68 | 0 |
| Master_of_Magic.sid | `$0B00` | 4 | $08 | plain | 66 | 0 |
| Chimera.sid | `$0F0A` | 4 | $05 | plain | 66 | 2 |
| Master_of_Magic.sid | `$0F0F` | 8 | $05 | plain | 63 | 0 |
| I_Ball.sid | `$0A03` | 1 | $A0 | plain | 62 | 0 |
| Auf_Wiedersehen_Monty.sid | `$0AF9` | 4 | $64 | plain | 60 | 0 |
| Thing_on_a_Spring.sid | `$1765` | - | - | unknown | 60 | 0 |
| International_Karate.sid | `$0FAD` | 11 | $F5 | arp | 58 | 0 |
| Kentilla.sid | `$090A` | - | - | unknown | 58 | 0 |
| Thing_on_a_Spring.sid | `$5687` | - | - | unknown | 54 | 0 |
| One_Man_and_his_Droid.sid | `$476F` | - | - | unknown | 49 | 0 |
| Samantha_Fox_Strip_Poker.sid | `$090A` | - | - | unknown | 46 | 0 |
| Game_Killer.sid | `$2963` | - | - | unknown | 45 | 0 |
| Zoids.sid | `$0A0C` | 8 | $05 | plain | 72 | 28 |
| BMX_Kidz.sid | `$0998` | 1 | $06 | alt | 40 | 0 |
| Master_of_Magic.sid | `$0A09` | 5 | $05 | plain | 35 | 0 |
| Confuzion.sid | `$09A9` | - | - | unknown | 32 | 0 |
| Proteus.sid | `$080C` | 12 | $C5 | plain | 32 | 0 |
| Pandora.sid | `$0C99` | 7 | $01 | plain | 31 | 0 |
| Auf_Wiedersehen_Monty.sid | `$09B9` | 1 | $64 | plain | 30 | 0 |
| Formula_1_Simulator.sid | `$0FFF` | - | - | unknown | 30 | 0 |
| Rasputin.sid | `$0F0F` | 10 | $01 | plain | 46 | 16 |
| IK_plus.sid | `$0505` | 4 | $08 | plain | 28 | 0 |
| Game_Killer.sid | `$096A` | 7 | $0D | plain | 24 | 0 |
| Proteus.sid | `$0F4F` | 9 | $C5 | plain | 24 | 0 |
| Gerry_the_Germ.sid | `$0986` | - | - | unknown | 20 | 0 |
| Proteus.sid | `$8C69` | - | - | unknown | 20 | 0 |
| Proteus.sid | `$0FDA` | 16 | $95 | arp | 18 | 0 |
| Thing_on_a_Spring.sid | `$4987` | - | - | unknown | 18 | 0 |
| Las_Vegas_Video_Poker.sid | `$0A89` | - | - | unknown | 17 | 0 |
| Warhawk.sid | `$0FDA` | 16 | $95 | arp | 16 | 0 |
| IK_plus.sid | `$09C8` | 2 | $A4 | plain | 15 | 0 |
| Master_of_Magic.sid | `$050A` | 17 | $05 | plain | 15 | 0 |
| Saboteur_II.sid | `$0888` | 5 | $01 | plain | 11 | 0 |
| Master_of_Magic.sid | `$596C` | - | - | unknown | 10 | 0 |
| Shockway_Rider.sid | `$0889` | 3 | $01 | plain | 10 | 0 |
| Knucklebusters.sid | `$00F8` | 12 | $44 | plain | 11 | 2 |
| Deep_Strike.sid | `$0FC9` | 3 | $44 | plain | 8 | 0 |
| Formula_1_Simulator.sid | `$0F0A` | 4 | $C5 | plain | 8 | 0 |
| Sanxion.sid | `$1909` | 5 | $44 | plain | 8 | 0 |
| Pandora.sid | `$4A59` | 5 | $00 | plain | 6 | 0 |
| Nemesis_the_Warlock.sid | `$0CC8` | 2 | $01 | plain | 5 | 0 |
| Mega_Apocalypse.sid | `$0CFC` | 17 | $22 | alt | 4 | 0 |
| Confuzion.sid | `$0A8F` | - | - | unknown | 3 | 0 |
| Pygmies_Revenge.sid | `$0000` | - | - | unknown | 3 | 0 |
| ACE_II.sid | `$0879` | 5 | $80 | plain | 2 | 0 |
| Food_Feud.sid | `$0FF9` | 1 | $44 | plain | 1 | 0 |

## By cause

`absent` is an instrument the original oscillates and we do not move at all; `slow` is one that moves too little. They have different fixes, so they are counted apart.

| cause | absent | slow | instruments | reversals missing |
|---|---:|---:|---:|---:|
| plain | 68 | 13 | 81 | 17839 |
| unknown | 67 | 0 | 67 | 21232 |
| alt | 22 | 3 | 25 | 15151 |
| arp | 14 | 1 | 15 | 5840 |

**171 of these 188 instruments emit no oscillation at all**, against 17 that merely run slow. That is the reading to take from this table: the shortfall is overwhelmingly a movement that never reached the file, not a rate to tune.

`plain` is an instrument whose effect byte is known and carries no oscillating bit, so its movement is the record's own vibrato byte. `unknown` is one whose byte could not be recovered -- `instrument_stamps` keys on the ADSR pair and two instruments can share one (section 7.zzzz) -- so no mechanism is claimed for it. `alt` and `arp` are mechanisms; `arp` runs on a global phase counter and a per-note wavetable cannot hold it at all (section 7.ttt).
