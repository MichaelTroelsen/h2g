# Vibrato census

398 instrument(s) across 82 file(s) whose pitch oscillates on either side. `vib` is a whole-file ratio; this is the same count split by the instrument sounding it, so the rows add to that column rather than re-measuring it.

**Why this is asked before anything is tuned.** The balloon song read `vib` 0.17x and it was taken for a vibrato-rate defect. The one instrument carrying a vibrato byte was within 20% of the original; the missing 1812 reversals were an arpeggio on a global counter that no wavetable can hold (section 7.ttt). A rate that looks wrong may be a mechanism that is absent.

## Instruments reproducing under half the original's oscillation

| file | ADSR | GT | effect | cause | orig | ours |
|---|---|---:|---|---|---:|---:|
| W_A_R_Preview.sid | `$4AAD` | 2 | $14 | pitchseq | 1717 | 0 |
| International_Karate.sid | `$090A` | 2 | $55 | pitchseq | 1625 | 0 |
| IK_plus.sid | `$0A56` | 5 | $14 | pitchseq | 1600 | 0 |
| Tarzan.sid | `$7840` | 1 | $2A | plain | 1244 | 0 |
| Spellbound.sid | `$180A` | 8 | $25 | arp | 911 | 0 |
| Dragons_Lair_Part_II.sid | `$8C00` | 19 | $2A | plain | 764 | 0 |
| Delta_Mix-E-Load_loader.sid | `$3A98` | 4 | $04 | plain | 742 | 0 |
| Last_V8.sid | `$0409` | 2 | $05 | arp | 702 | 0 |
| Last_V8_C128_version.sid | `$0409` | 2 | $05 | arp | 702 | 0 |
| Chicken_Song.sid | `$0A00` | 6 | $01 | drum | 644 | 0 |
| International_Karate.sid | `$0A0A` | 1 | $55 | pitchseq | 630 | 0 |
| Commodore_64_Music_Examples.sid | `$5C3A` | - | - | unknown | 623 | 0 |
| Battle_of_Britain.sid | `$0FFF` | 5 | $02 | plain | 616 | 0 |
| Kings_of_the_Beach_intro.sid | `$0998` | 6 | $00 | plain | 599 | 0 |
| Crazy_Comets.sid | `$0FFF` | 11 | $02 | plain | 827 | 233 |
| Kings_of_the_Beach_intro.sid | `$0999` | 5 | $10 | pitchseq | 475 | 0 |
| Hollywood_or_Bust.sid | `$7800` | 9 | $00 | plain | 441 | 0 |
| Chimera.sid | `$0F0F` | 4 | $05 | arp | 420 | 0 |
| Devils_Galop.sid | `$0909` | 4 | $05 | arp | 411 | 0 |
| Monty_on_the_Run.sid | `$0909` | 4 | $05 | arp | 411 | 0 |
| Dragons_Lair_Part_II.sid | `$097A` | 2 | $00 | plain | 505 | 111 |
| One_Man_and_his_Droid.sid | `$077F` | 1 | $0A | plain | 612 | 256 |
| One_Man_and_his_Droid.sid | `$088F` | 2 | $0A | plain | 612 | 256 |
| Off_the_Cuff.sid | `$09C7` | 4 | $04 | plain | 433 | 95 |
| Rock_Tells_the_Tale.sid | `$59C9` | 8 | $04 | plain | 326 | 0 |
| Bangkok_Knights.sid | `$0A08` | 3 | $30 | pitchseq | 325 | 0 |
| One_on_One_Jordan_vs_Bird.sid | `$09F8` | 3 | $01 | program | 295 | 0 |
| One_on_One_Jordan_vs_Bird.sid | `$06A6` | 2 | $44 | atkpitch | 282 | 0 |
| International_Karate.sid | `$0BB0` | 3 | $08 | plain | 277 | 0 |
| Nineteen.sid | `$0797` | 7 | $01 | program | 483 | 208 |
| Hunter_Patrol.sid | `$0AA0` | 5 | $02 | plain | 387 | 114 |
| Dragons_Lair_Part_II.sid | `$1979` | 26 | $04 | plain | 245 | 0 |
| Spellbound.sid | `$0FFA` | 4 | $C5 | arp | 219 | 0 |
| Phantoms_of_the_Asteroid.sid | `$0786` | 1 | $02 | plain | 335 | 125 |
| Rasputin.sid | `$0A0A` | 7 | $05 | arp | 204 | 0 |
| Rock_Tells_the_Tale.sid | `$F96E` | 10 | $04 | plain | 190 | 0 |
| Game_Killer.sid | `$0A9A` | 2 | $0A | plain | 262 | 78 |
| Knucklebusters.sid | `$0AAD` | 25 | $44 | atkpitch | 261 | 90 |
| One_on_One_Jordan_vs_Bird.sid | `$0ACA` | 4 | $00 | plain | 167 | 0 |
| Last_V8.sid | `$0A09` | 4 | $05 | arp | 163 | 0 |
| Last_V8_C128_version.sid | `$0A09` | 4 | $05 | arp | 162 | 0 |
| Rock_Tells_the_Tale.sid | `$09B9` | 6 | $04 | plain | 172 | 21 |
| International_Karate.sid | `$0F0B` | 4 | $C5 | arp | 148 | 0 |
| Wiz.sid | `$0909` | 2 | $01 | program | 144 | 0 |
| Last_V8.sid | `$040F` | 1 | $01 | drum | 141 | 0 |
| Last_V8_C128_version.sid | `$040F` | 1 | $01 | drum | 141 | 0 |
| Dragons_Lair_Part_II.sid | `$A8C9` | 15 | $04 | plain | 138 | 0 |
| Food_Feud.sid | `$29F9` | 3 | $34 | pitchseq | 137 | 0 |
| After_8.sid | `$099A` | 7 | $00 | plain | 264 | 131 |
| Monty_on_the_Run.sid | `$3FFF` | 13 | $02 | plain | 218 | 106 |
| International_Karate.sid | `$0A08` | 5 | $C5 | arp | 103 | 0 |
| Samantha_Fox_Strip_Poker.sid | `$0909` | 2 | $C4 | arp | 101 | 0 |
| Spellbound.sid | `$0F0A` | 13 | $25 | arp | 100 | 0 |
| Battle_of_Britain.sid | `$0C0A` | 4 | $05 | arp | 81 | 0 |
| Formula_1_Simulator.sid | `$0A0A` | 1 | $55 | pitchseq | 76 | 0 |
| Wiz.sid | `$0627` | 7 | $01 | program | 72 | 0 |
| Chicken_Song.sid | `$0970` | 10 | $00 | plain | 116 | 48 |
| Master_of_Magic.sid | `$0F0F` | 8 | $05 | arp | 63 | 0 |
| I_Ball.sid | `$0A03` | 1 | $A0 | plain | 62 | 0 |
| Auf_Wiedersehen_Monty.sid | `$0AF9` | 4 | $64 | plain | 60 | 0 |
| Samantha_Fox_Strip_Poker.sid | `$090A` | 2 | $C4 | arp | 46 | 0 |
| BMX_Kidz.sid | `$0998` | 1 | $06 | plain | 40 | 0 |
| Master_of_Magic.sid | `$0A09` | 5 | $05 | arp | 35 | 0 |
| Pandora.sid | `$0C99` | 7 | $01 | program | 31 | 0 |
| Auf_Wiedersehen_Monty.sid | `$09B9` | 1 | $64 | plain | 30 | 0 |
| IK_plus.sid | `$0505` | 4 | $08 | program | 28 | 0 |
| IK_plus.sid | `$09C8` | 2 | $A4 | bit80 | 15 | 0 |
| Master_of_Magic.sid | `$050A` | 17 | $05 | arp | 15 | 0 |
| Saboteur_II.sid | `$0888` | 5 | $01 | program | 11 | 0 |
| Shockway_Rider.sid | `$0889` | 3 | $01 | program | 10 | 0 |
| Deep_Strike.sid | `$0FC9` | 3 | $44 | atkpitch | 8 | 0 |
| Formula_1_Simulator.sid | `$0F0A` | 4 | $C5 | arp | 8 | 0 |
| Knucklebusters.sid | `$00F8` | 12 | $44 | atkpitch | 11 | 3 |
| Sanxion.sid | `$1909` | 5 | $44 | atkpitch | 8 | 0 |
| Pandora.sid | `$4A59` | 5 | $00 | plain | 6 | 0 |
| Nemesis_the_Warlock.sid | `$0CC8` | 2 | $01 | program | 5 | 0 |
| Mega_Apocalypse.sid | `$0CFC` | 17 | $22 | plain | 4 | 0 |
| Pygmies_Revenge.sid | `$0000` | - | - | unknown | 3 | 0 |
| ACE_II.sid | `$0879` | 5 | $80 | bit80 | 2 | 0 |
| Food_Feud.sid | `$0FF9` | 1 | $44 | atkpitch | 1 | 0 |

## By cause

`absent` is an instrument the original oscillates and we do not move at all; `slow` is one that moves too little. They have different fixes, so they are counted apart.

| cause | absent | slow | instruments | reversals missing |
|---|---:|---:|---:|---:|
| plain | 18 | 12 | 30 | 9120 |
| arp | 20 | 0 | 20 | 5005 |
| program | 8 | 1 | 9 | 871 |
| pitchseq | 8 | 0 | 8 | 6585 |
| atkpitch | 4 | 2 | 6 | 478 |
| drum | 3 | 0 | 3 | 926 |
| bit80 | 2 | 0 | 2 | 17 |
| unknown | 2 | 0 | 2 | 626 |

**65 of these 80 instruments emit no oscillation at all**, against 15 that merely run slow. That is the reading to take from this table: the shortfall is overwhelmingly a movement that never reached the file, not a rate to tune.

`plain` is an instrument whose effect byte is known and carries no oscillating bit, so its movement is the record's own vibrato byte. `unknown` is one whose byte could not be recovered -- `instrument_stamps` keys on the ADSR pair and two instruments can share one (section 7.zzzz) -- so no mechanism is claimed for it. `alt` and `arp` are mechanisms; `arp` runs on a global phase counter and a per-note wavetable cannot hold it at all (section 7.ttt).
