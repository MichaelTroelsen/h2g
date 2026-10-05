# Vibrato census

650 instrument(s) across 88 file(s) whose pitch oscillates on either side. `vib` is a whole-file ratio; this is the same count split by the instrument sounding it, so the rows add to that column rather than re-measuring it.

**Why this is asked before anything is tuned.** The balloon song read `vib` 0.17x and it was taken for a vibrato-rate defect. The one instrument carrying a vibrato byte was within 20% of the original; the missing 1812 reversals were an arpeggio on a global counter that no wavetable can hold (section 7.ttt). A rate that looks wrong may be a mechanism that is absent.

## Instruments reproducing under half the original's oscillation

| file | ADSR | GT | effect | cause | orig | ours |
|---|---|---:|---|---|---:|---:|
| Sun_Never_Shines.sid | `$0047` | 6 | $64 | atkpitch | 3871 | 2 |
| IK_plus.sid | `$0A56` | 5 | $14 | pitchseq | 3393 | 0 |
| Pacific_Coast.sid | `$04D5` | 2 | $01 | plain | 3285 | 0 |
| Pacific_Coast.sid | `$04F9` | 1 | $01 | plain | 2210 | 0 |
| Go_Go_Dash.sid | `$04AA` | 1 | $01 | plain | 1982 | 0 |
| Flash_Gordon.sid | `$366C` | 10 | $00 | plain | 2796 | 1036 |
| Kings_of_the_Beach_intro.sid | `$0999` | 5 | $10 | plain | 1730 | 0 |
| Bangkok_Knights.sid | `$0999` | 7 | $30 | pitchseq | 1480 | 0 |
| Chicken_Song.sid | `$0A00` | 6 | $01 | plain | 1440 | 0 |
| Go_Go_Dash.sid | `$0286` | 2 | $44 | atkpitch | 1382 | 0 |
| Hollywood_or_Bust.sid | `$7800` | 9 | $00 | plain | 1313 | 0 |
| Lion_Heart.sid | `$0AC4` | 4 | $20 | plain | 1298 | 0 |
| International_Karate.sid | `$0BB0` | 3 | $08 | plain | 1261 | 0 |
| Crazy_Comets.sid | `$0FFF` | 11 | $02 | plain | 1717 | 492 |
| I_Ball.sid | `$0906` | 4 | $10 | pitchseq | 1180 | 0 |
| Game_Killer.sid | `$0A9A` | 2 | $0A | plain | 1652 | 479 |
| Lakers_vs_Celtics.sid | `$08C7` | 1 | $01 | plain | 1056 | 0 |
| Radio_ACE.sid | `$0BA9` | 6 | $44 | atkpitch | 974 | 0 |
| Radio_ACE.sid | `$00FA` | 3 | $01 | plain | 965 | 0 |
| Radio_ACE.sid | `$0558` | 5 | $04 | plain | 960 | 0 |
| Lakers_vs_Celtics.sid | `$02A9` | 12 | $44 | atkpitch | 828 | 0 |
| Lakers_vs_Celtics.sid | `$0FC7` | 3 | $01 | plain | 779 | 0 |
| Lakers_vs_Celtics.sid | `$086A` | 9 | $44 | atkpitch | 762 | 0 |
| Sun_Never_Shines.sid | `$0679` | 8 | $00 | plain | 740 | 0 |
| Mega_Apocalypse.sid | `$0A06` | 5 | $30 | pitchseq | 716 | 0 |
| Pygmies_Revenge.sid | `$00A9` | 9 | $10 | pitchseq | 937 | 258 |
| I_Ball.sid | `$0909` | 8 | $14 | pitchseq | 660 | 0 |
| Radio_ACE.sid | `$0A99` | 4 | $04 | plain | 653 | 0 |
| Bangkok_Knights.sid | `$0A08` | 3 | $30 | pitchseq | 648 | 0 |
| I_Ball.sid | `$0B88` | 3 | $10 | pitchseq | 647 | 0 |
| Lakers_vs_Celtics.sid | `$0379` | 14 | $04 | plain | 643 | 0 |
| Battle_of_Britain.sid | `$0FFF` | 5 | $02 | plain | 616 | 0 |
| Chimera.sid | `$0F0F` | 19 | $05 | arp | 785 | 190 |
| Hollywood_or_Bust.sid | `$0900` | 14 | $00 | plain | 566 | 0 |
| I_Ball.sid | `$0707` | 5 | $10 | pitchseq | 561 | 0 |
| Chicken_Song.sid | `$6500` | 8 | $00 | plain | 560 | 0 |
| Sun_Never_Shines.sid | `$354B` | 10 | $00 | plain | 552 | 0 |
| Go_Go_Dash.sid | `$018A` | 9 | $64 | atkpitch | 542 | 0 |
| Lakers_vs_Celtics.sid | `$09CA` | 8 | $44 | atkpitch | 548 | 6 |
| One_Man_and_his_Droid.sid | `$077F` | 1 | $0A | plain | 918 | 384 |
| One_Man_and_his_Droid.sid | `$088F` | 2 | $0A | plain | 918 | 384 |
| Phantoms_of_the_Asteroid.sid | `$0786` | 1 | $02 | plain | 850 | 328 |
| Lakers_vs_Celtics.sid | `$0B9D` | 6 | $00 | plain | 512 | 0 |
| Master_of_Magic.sid | `$0C20` | 12 | $0A | plain | 736 | 256 |
| Pacific_Coast.sid | `$0678` | 11 | $04 | plain | 472 | 0 |
| Lakers_vs_Celtics.sid | `$0875` | 7 | $44 | atkpitch | 448 | 0 |
| Radio_ACE.sid | `$0647` | 9 | $24 | plain | 448 | 0 |
| Hunter_Patrol.sid | `$0AA0` | 5 | $02 | plain | 639 | 196 |
| Rock_Tells_the_Tale.sid | `$09B9` | 5 | $04 | plain | 686 | 245 |
| Last_V8.sid | `$040F` | 1 | $01 | drum | 422 | 0 |
| Last_V8_C128_version.sid | `$040F` | 1 | $01 | drum | 422 | 0 |
| Go_Go_Dash.sid | `$0669` | 14 | $04 | plain | 436 | 24 |
| Lakers_vs_Celtics.sid | `$17BA` | 10 | $04 | plain | 412 | 1 |
| Sun_Never_Shines.sid | `$008A` | 7 | $00 | plain | 393 | 0 |
| Lion_Heart.sid | `$0AF9` | 7 | $04 | plain | 414 | 23 |
| Chimera.sid | `$7989` | 6 | $00 | plain | 609 | 252 |
| Food_Feud.sid | `$29F9` | 3 | $34 | pitchseq | 341 | 0 |
| Ninja.sid | `$4900` | 5 | $05 | plain | 320 | 0 |
| Go_Go_Dash.sid | `$02B8` | 10 | $00 | plain | 292 | 0 |
| Wiz.sid | `$0909` | 2 | $01 | program | 288 | 0 |
| Knucklebusters.sid | `$0C0A` | 26 | $10 | pitchseq | 272 | 0 |
| Ninja.sid | `$3800` | 3 | $04 | plain | 270 | 0 |
| Sun_Never_Shines.sid | `$606A` | 5 | $00 | plain | 261 | 0 |
| Pacific_Coast.sid | `$0AA9` | 10 | $04 | plain | 272 | 12 |
| Go_Go_Dash.sid | `$00BA` | 13 | $04 | plain | 312 | 56 |
| Rock_Tells_the_Tale.sid | `$59C9` | 7 | $04 | plain | 497 | 243 |
| Ninja.sid | `$190A` | 6 | $04 | plain | 246 | 0 |
| Radio_ACE.sid | `$069A` | 12 | $44 | atkpitch | 246 | 0 |
| Trans-Atlantic_Balloon_Challenge.sid | `$0CD9` | 7 | $10 | pitchseq | 370 | 136 |
| Go_Go_Dash.sid | `$0629` | 4 | $00 | plain | 221 | 0 |
| Pacific_Coast.sid | `$04BA` | 4 | $04 | plain | 220 | 0 |
| Go_Go_Dash.sid | `$08C7` | 7 | $01 | plain | 216 | 0 |
| International_Karate.sid | `$0FAD` | 11 | $F5 | arp | 340 | 144 |
| Lion_Heart.sid | `$0658` | 11 | $44 | atkpitch | 189 | 0 |
| Last_V8.sid | `$0FF0` | 12 | $00 | plain | 232 | 46 |
| Last_V8_C128_version.sid | `$0FF0` | 12 | $00 | plain | 232 | 46 |
| Rock_Tells_the_Tale.sid | `$0A89` | 3 | $04 | plain | 223 | 38 |
| IK_plus.sid | `$0505` | 4 | $08 | program | 181 | 0 |
| Sun_Never_Shines.sid | `$035D` | 4 | $00 | plain | 172 | 0 |
| Spellbound.sid | `$0FFF` | - | - | unknown | 172 | 5 |
| Radio_ACE.sid | `$00A9` | 14 | $00 | plain | 158 | 0 |
| Go_Go_Dash.sid | `$0499` | 8 | $44 | atkpitch | 157 | 0 |
| Radio_ACE.sid | `$08C7` | 1 | $01 | plain | 157 | 0 |
| Lion_Heart.sid | `$08C7` | 1 | $01 | plain | 149 | 0 |
| Wiz.sid | `$0627` | 6 | $01 | program | 144 | 0 |
| Kentilla.sid | `$3709` | 6 | $03 | drum | 137 | 0 |
| Gerry_the_Germ.sid | `$0D5F` | 8 | $02 | plain | 154 | 27 |
| Monty_on_the_Run.sid | `$3FFF` | 12 | $02 | plain | 218 | 95 |
| Lakers_vs_Celtics.sid | `$09CB` | 11 | $00 | plain | 117 | 0 |
| Pandora.sid | `$0C99` | 7 | $01 | program | 131 | 18 |
| Chicken_Song.sid | `$0FFF` | 12 | $00 | plain | 200 | 94 |
| Radio_ACE.sid | `$006F` | 13 | $00 | plain | 103 | 0 |
| Samantha_Fox_Strip_Poker.sid | `$0909` | 2 | $C4 | arp | 102 | 0 |
| One_Man_and_his_Droid.sid | `$476F` | 9 | $0A | plain | 194 | 94 |
| Radio_ACE.sid | `$07BA` | 10 | $00 | plain | 98 | 0 |
| Zoids.sid | `$6C0A` | 9 | $02 | plain | 159 | 76 |
| IK_plus.sid | `$09C8` | 2 | $A4 | bit80 | 77 | 0 |
| BMX_Kidz.sid | `$0998` | 1 | $06 | plain | 62 | 0 |
| Thrust.sid | `$0FFF` | 20 | $03 | drum | 60 | 0 |
| Lion_Heart.sid | `$0D47` | 2 | $01 | plain | 50 | 0 |
| Radio_ACE.sid | `$086D` | 15 | $00 | plain | 50 | 0 |
| Samantha_Fox_Strip_Poker.sid | `$090A` | 2 | $C4 | arp | 46 | 0 |
| Lakers_vs_Celtics.sid | `$0367` | 4 | $44 | atkpitch | 40 | 0 |
| Rasputin.sid | `$0F0F` | 10 | $01 | drum | 76 | 36 |
| Go_Go_Dash.sid | `$048C` | 5 | $04 | plain | 61 | 22 |
| Knucklebusters.sid | `$00F8` | 12 | $44 | atkpitch | 43 | 5 |
| Lion_Heart.sid | `$00B7` | 13 | $00 | plain | 40 | 2 |
| Lion_Heart.sid | `$09E7` | 8 | $04 | plain | 35 | 0 |
| Chicken_Song.sid | `$0A07` | 4 | $03 | plain | 32 | 0 |
| Gerry_the_Germ.sid | `$090F` | 24 | $01 | drum | 32 | 0 |
| Go_Go_Dash.sid | `$0FDD` | 3 | $01 | plain | 30 | 0 |
| Pacific_Coast.sid | `$057C` | 7 | $00 | plain | 30 | 0 |
| Sanxion.sid | `$0FF9` | 1 | $44 | atkpitch | 41 | 11 |
| Radio_ACE.sid | `$01CA` | 7 | $44 | atkpitch | 29 | 0 |
| Pacific_Coast.sid | `$02C8` | 9 | $00 | plain | 27 | 0 |
| Off_the_Cuff.sid | `$0A59` | 8 | $10 | pitchseq | 37 | 12 |
| Radio_ACE.sid | `$0FA9` | 11 | $04 | plain | 27 | 2 |
| Rock_Tells_the_Tale.sid | `$0AE8` | 4 | $04 | plain | 25 | 0 |
| Lion_Heart.sid | `$0DC9` | 6 | $00 | plain | 21 | 0 |
| Sanxion.sid | `$1909` | 5 | $44 | atkpitch | 20 | 0 |
| Deep_Strike.sid | `$0FC9` | 3 | $44 | atkpitch | 18 | 0 |
| Lakers_vs_Celtics.sid | `$00E9` | 2 | $01 | plain | 18 | 0 |
| Shockway_Rider.sid | `$0889` | 3 | $01 | program | 31 | 13 |
| Pacific_Coast.sid | `$056A` | 8 | $44 | atkpitch | 15 | 0 |
| Sun_Never_Shines.sid | `$01E9` | 2 | $01 | plain | 14 | 0 |
| Sigma_Seven.sid | `$0FFD` | 3 | $44 | atkpitch | 13 | 0 |
| Bump_Set_Spike.sid | `$0FFA` | 14 | $00 | plain | 10 | 0 |
| Tarzan.sid | `$0507` | 8 | $45 | atkpitch | 10 | 0 |
| Ninja.sid | `$3980` | 7 | $00 | plain | 12 | 4 |
| Ninja.sid | `$3A5A` | 8 | $00 | plain | 8 | 0 |
| Ninja.sid | `$7900` | 2 | $01 | plain | 8 | 0 |
| Go_Go_Dash.sid | `$0559` | 11 | $00 | plain | 6 | 0 |
| Food_Feud.sid | `$0FF9` | 1 | $44 | atkpitch | 5 | 0 |
| Nemesis_the_Warlock.sid | `$0CC8` | 2 | $01 | program | 5 | 0 |
| Mega_Apocalypse.sid | `$0CFC` | 17 | $22 | plain | 4 | 0 |
| Off_the_Cuff.sid | `$0979` | 2 | $01 | program | 4 | 0 |
| Lion_Heart.sid | `$0407` | 9 | $00 | plain | 3 | 0 |
| Pygmies_Revenge.sid | `$0000` | - | - | unknown | 3 | 0 |
| Radio_ACE.sid | `$0F29` | 2 | $01 | plain | 3 | 0 |
| I_Ball.sid | `$0000` | - | - | unknown | 2 | 0 |
| Lakers_vs_Celtics.sid | `$009E` | 13 | $00 | plain | 2 | 0 |
| Last_V8.sid | `$0FF8` | - | - | unknown | 2 | 0 |
| Last_V8_C128_version.sid | `$0FF8` | - | - | unknown | 2 | 0 |
| Lion_Heart.sid | `$0547` | 10 | $00 | plain | 2 | 0 |
| Nineteen.sid | `$0868` | 6 | $00 | plain | 2 | 0 |
| Nineteen.sid | `$0000` | 19 | $00 | plain | 1 | 0 |

## By cause

`absent` is an instrument the original oscillates and we do not move at all; `slow` is one that moves too little. They have different fixes, so they are counted apart.

| cause | absent | slow | instruments | reversals missing |
|---|---:|---:|---:|---:|
| plain | 61 | 28 | 89 | 38536 |
| atkpitch | 17 | 4 | 21 | 10157 |
| pitchseq | 10 | 3 | 13 | 10836 |
| program | 5 | 2 | 7 | 753 |
| drum | 5 | 1 | 6 | 1113 |
| unknown | 4 | 1 | 5 | 176 |
| arp | 2 | 2 | 4 | 939 |
| bit80 | 1 | 0 | 1 | 77 |

**105 of these 146 instruments emit no oscillation at all**, against 41 that merely run slow. That is the reading to take from this table: the shortfall is overwhelmingly a movement that never reached the file, not a rate to tune.

`plain` is an instrument whose effect byte is known and carries no oscillating bit, so its movement is the record's own vibrato byte. `unknown` is one whose byte could not be recovered -- `instrument_stamps` keys on the ADSR pair and two instruments can share one (section 7.zzzz) -- so no mechanism is claimed for it. `alt` and `arp` are mechanisms; `arp` runs on a global phase counter and a per-note wavetable cannot hold it at all (section 7.ttt).
