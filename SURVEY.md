# H2G conversion survey — Rob Hubbard SID corpus

- Converter: `h2g` **0.5.176**
- Corpus: `C:\Users\mit\claude\c64server\SIDM2\SID\Hubbard_Rob`
- Files tested: **95**
- Pattern slicing: **94 rows** (original VB6 behaviour)
- Output format: **GTS2** (of GTS2/GTS5) (3-table, original VB6 behaviour; note Goattracker's legacy GTS2 importer overruns its pattern array on the portamento commands this converter emits — prefer `--format gts5` for files you will open in Goattracker)
- Restart position: **legalised** (`--legal-restart`) — a tune ending on Hubbard's `$FE` marker loops from the top instead of stopping, which is what lets `gt2reloc` export it at all
- Converted: **80** of 83 in reach (96%) — Failed: **3** — Out of scope: **12** (not a Hubbard player)

> "Converted" means the converter produced a `.sng` without erroring. It does **not** mean the output is musically correct. Only the repo's own `Commando.sid` is verified byte-exact against the original VB6 tool; note that the corpus copy of `Commando.sid` is a *different rip* (4165 B / 19 subtunes vs the repo's 4222 B / 3 subtunes), so its row here is not comparable to that fixture.

Regenerate with: `python survey.py "C:\Users\mit\claude\c64server\SIDM2\SID\Hubbard_Rob" -o SURVEY.md --legal-restart`

## Failure breakdown by stage

| Stage | Files | Meaning |
|---|---:|---|
| patterns | 3 | pattern decode/slicing hit a Goattracker limit |

## Detected player variant (successful conversions)

| Version | Player family | Files |
|---:|---|---:|
| 0 | Warhawk | 31 |
| 1 | Last V8 | 8 |
| 2 | Auf Wiedersehen Monty | 14 |
| 3 | Samantha Fox | 1 |
| 4 | ACE 2 | 1 |
| 5 | Battle of Britain | 9 |
| 6 | Mega Apocalypse | 1 |
| 7 | IK+ | 14 |
| 9 | Chain Reaction | 1 |

## SIDId player identification

| SIDId signature | Converted | Not converted | Total | Rate |
|---|---:|---:|---:|---:|
| `Rob_Hubbard` | 63 | 3 | 66 | 95% |
| `Rob_Hubbard, (Rob_Hubbard_Digi)` | 11 | 0 | 11 | 100% |
| `Jason_Page/RobTracker` * | 0 | 6 | 6 | 0% |
| `SidTracker64` * | 0 | 5 | 5 | 0% |
| `Rob_Hubbard, Voicemaster_Covox` | 4 | 0 | 4 | 100% |
| `Companion` * | 0 | 1 | 1 | 0% |
| `Companion, Rob_Hubbard` | 1 | 0 | 1 | 100% |
| `Rob_Hubbard, (Rob_Hubbard_Digi), Sidplayer` | 1 | 0 | 1 | 100% |

`*` marks a player routine that is **not** a Rob Hubbard engine. Those files are in the corpus because Hubbard wrote the music, not the player, so no Hubbard fingerprint can match them.

## Findings

- **80/95 produced output.** The ceiling is structural: detection only recognises 17 hard-coded game fingerprints, so anything outside that set is unconvertible by construction.
- **12 files are not Hubbard-player tunes at all** and are listed separately below. SIDId identifies their player as Companion, Jason_Page/RobTracker, SidTracker64 — Hubbard wrote the music, someone else wrote the routine, so no Hubbard fingerprint can match and no new signature would bring them in. Excluding them, coverage is **80/83 = 96%** rather than 80/95 = 84%.
- **9 tunes drive a fourth, sampled voice that is not converted.** Their player runs four channels; the extra one plays digi samples, which is what the `(Rob_Hubbard_Digi)` SIDId signature marks. Goattracker has three voices and no way to carry sampled playback, so that channel is dropped — the three SID voices convert in full. Affected: `After_8.sid`, `Kings_of_the_Beach_intro.sid`, `Mr_Meaner.sid`, `Off_the_Cuff.sid`, `One_on_One_Jordan_vs_Bird.sid`, `Powerplay_Hockey_USA_vs_USSR.sid`, `Pygmies_Revenge.sid`, `Rikky.sid`, `Rock_Tells_the_Tale.sid`.
- **2 files lose a subtune to Goattracker's 254-byte orderlist limit.** The rest of the tune converts: one over-long subtune used to abort the whole file, discarding every good subtune with it. The subtune is dropped rather than truncated, because cutting one voice short while its neighbours play on makes it loop early and drift — a subtune that sounds wrong is worse than one plainly absent. Affected: `Chicken_Song.sid` (1), `Knucklebusters.sid` (1).
- **80 of 80 converted files pack back to a `.sid`** with `gt2reloc`, the standalone form of Goattracker's F9 packer. That is what makes a fidelity test possible: the packed `.sid` can be `siddump`ed against the file it was converted from. A failure here is not a conversion failure — the `.sng` is fine in the editor — but it blocks that comparison. See [`SNG2SID-FIDELITY.md`](SNG2SID-FIDELITY.md). These numbers are with `--legal-restart`; without it `greloc.c:244` rejects every tune that ends on Hubbard's `$FE` marker, because the stop it maps to is an out-of-range restart position.
- **3 failures are capacity, not comprehension.** These files detect cleanly (all four passes green) and fail only because the tune exceeds a Goattracker limit — 208 patterns or a 255-byte orderlist. They are the most recoverable group: splitting the orderlist across subtunes would convert them.
- **19 converted files contain orderlist entries that point at patterns the file does not have.** `reindex_tracks` drops those references silently, so the tune plays with material missing rather than failing. There are two distinct causes, separated by whether subtune 0 — always a real subtune — is affected.
  - **1 are a decode fault** (dangling refs in subtune 0). Most are version-2 players, where a byte with the high bit set is a per-voice **transpose command**, not a pattern number: the player branches `BPL` past the $FF/$FE checks, then `AND #$7F` / `STA transpose,X`, and the stored value is read back as `CLC` / `ADC transpose,X` on the note before the frequency-table lookup. The track reader groups version 2 with versions 0/1/3, which have no such branch, so it emits those command bytes as pattern numbers $80-$FD. Affected: .
  - **18 are phantom subtunes** (subtune 0 clean, later subtunes dangling). The track table has no length field and the PSID header routinely over-claims, so a pointer that happens to land inside the file is read as an orderlist. Only pointers resolving *outside* the file, and subtunes that play no existing pattern at all, are rejected -- a threshold on the rest would also discard real subtunes, which run as low as one bad reference in a hundred good ones.

## Converted (80)

| File | Title | Source | SIDId | Player | Ver | Subtunes | Instr | Patterns | Dangling | .sng bytes | gt2reloc | Flag |
|---|---|---|---|---|---:|---|---:|---:|---|---:|:-:|---|
| `5_Title_Tunes.sid` | 5 Title Tunes | PSID v2 | Rob_Hubbard | Battle of Britain | 5 | 1 (hdr 5) | 17 | 38 | - | 8932 | y |  |
| `ACE_II.sid` | ACE II | PSID v2 | Rob_Hubbard | ACE 2 | 4 | 1 | 13 | 58 | - | 16014 | y |  |
| `Action_Biker.sid` | Action Biker | PSID v2 | Rob_Hubbard | Warhawk | 0 | 3 | 13 | 73 | - | 18323 | y |  |
| `After_8.sid` | After 8 | RSID v2 | Rob_Hubbard, (Rob_Hubbard_Digi) | Auf Wiedersehen Monty | 2 | 1 | 18 | 182 | - | 61666 | y | digi channel dropped |
| `Arcade_Classics.sid` | Arcade Classics | RSID v2 | Rob_Hubbard, (Rob_Hubbard_Digi) | IK+ | 7 | 1 | 12 | 110 | - | 32889 | y |  |
| `Auf_Wiedersehen_Monty.sid` | Auf Wiedersehen Monty | PSID v2 | Rob_Hubbard | Auf Wiedersehen Monty | 2 | 13 | 17 | 169 | - | 42861 | y |  |
| `Bangkok_Knights.sid` | Bangkok Knights | PSID v2 | Rob_Hubbard | IK+ | 7 | 1 | 30 | 52 | - | 14068 | y |  |
| `Battle_of_Britain.sid` | Battle of Britain | PSID v2 | Rob_Hubbard | Battle of Britain | 5 | 1 | 20 | 110 | - | 36024 | y |  |
| `BMX_Kidz.sid` | BMX Kidz | RSID v2 | Rob_Hubbard, (Rob_Hubbard_Digi), Sidplayer | Auf Wiedersehen Monty | 2 | 1 (hdr 4) | 12 | 93 | - | 30580 | y |  |
| `Bump_Set_Spike.sid` | Bump Set Spike | PSID v2 | Rob_Hubbard | Warhawk | 0 | 2 | 26 | 78 | - | 19770 | y |  |
| `Chain_Reaction.sid` | Chain Reaction | PSID v2 | Rob_Hubbard | Chain Reaction | 9 | 1 | 30 | 37 | - | 10769 | y |  |
| `Chicken_Song.sid` | The Chicken Song | PSID v2 | Rob_Hubbard | Warhawk | 0 | 1 | 26 | 120 | - | 34060 | y | 1 subtune(s) too long |
| `Chimera.sid` | Chimera | RSID v2 | Rob_Hubbard, Voicemaster_Covox | Last V8 | 1 | 2 (hdr 4) | 9 | 65 | - | 13878 | y |  |
| `Commando.sid` | Commando | PSID v2 | Rob_Hubbard | Warhawk | 0 | 18 (hdr 19) | 14 | 65 | 59 | 15781 | y |  |
| `Commodore_64_Music_Examples.sid` | Commodore 64 Music Examples | PSID v2 | Companion, Rob_Hubbard | Battle of Britain | 5 | 15 | 14 | 145 | 75 | 11149 | y |  |
| `Confuzion.sid` | Confuzion | PSID v2 | Rob_Hubbard | Battle of Britain | 5 | 1 | 12 | 56 | - | 15599 | y |  |
| `Crazy_Comets.sid` | Crazy Comets | PSID v2 | Rob_Hubbard | Last V8 | 1 | 17 | 24 | 80 | 16 | 20315 | y |  |
| `Deep_Strike.sid` | Deep Strike | PSID v2 | Rob_Hubbard | IK+ | 7 | 1 | 13 | 56 | - | 13342 | y |  |
| `Delta_Mix-E-Load_loader.sid` | Delta Mix-E-Load (loader) | PSID v2 | Rob_Hubbard | Warhawk | 0 | 14 (hdr 16) | 30 | 40 | 66 | 11619 | y |  |
| `Devils_Galop.sid` | Devils Galop | PSID v2 | Rob_Hubbard | Battle of Britain | 5 | 1 | 16 | 83 | - | 24046 | y |  |
| `Flash_Gordon.sid` | Flash Gordon | PSID v2 | Rob_Hubbard | Warhawk | 0 | 9 | 19 | 147 | - | 46397 | y |  |
| `Food_Feud.sid` | Food Feud | PSID v2 | Rob_Hubbard | Warhawk | 0 | 1 | 15 | 57 | - | 15453 | y |  |
| `Formula_1_Simulator.sid` | Formula 1 Simulator | PSID v2 | Rob_Hubbard | Warhawk | 0 | 1 (hdr 2) | 16 | 37 | - | 10750 | y |  |
| `Game_Killer.sid` | Game Killer | PSID v2 | Rob_Hubbard | Last V8 | 1 | 1 | 12 | 38 | - | 9400 | y |  |
| `Geoff_Capes_Strongman_Challenge.sid` | Geoff Capes Strongman Challenge | PSID v2 | Rob_Hubbard | Warhawk | 0 | 21 (hdr 24) | 22 | 55 | 110 | 11223 | y |  |
| `Gerry_the_Germ.sid` | Gerry the Germ | PSID v2 | Rob_Hubbard | Warhawk | 0 | 7 (hdr 23) | 28 | 171 | - | 42153 | y |  |
| `Gremlins.sid` | Gremlins | PSID v2 | Rob_Hubbard | Battle of Britain | 5 | 26 | 33 | 208 | 41 | 55809 | y |  |
| `Hollywood_or_Bust.sid` | Hollywood or Bust | PSID v2 | Rob_Hubbard | Warhawk | 0 | 3 (hdr 10) | 21 | 136 | - | 38958 | y |  |
| `Human_Race.sid` | The Human Race | PSID v2 | Rob_Hubbard | Last V8 | 1 | 5 | 25 | 102 | - | 23230 | y |  |
| `Hunter_Patrol.sid` | Hunter Patrol | PSID v2 | Rob_Hubbard | Battle of Britain | 5 | 1 | 33 | 78 | - | 21844 | y |  |
| `I_Ball.sid` | I, Ball | RSID v2 | Rob_Hubbard | IK+ | 7 | 1 (hdr 4) | 19 | 51 | - | 12957 | y |  |
| `IK_plus.sid` | IK+ | PSID v2 | Rob_Hubbard | IK+ | 7 | 1 (hdr 3) | 16 | 51 | - | 12718 | y |  |
| `International_Karate.sid` | International Karate | PSID v2 | Rob_Hubbard | Warhawk | 0 | 1 | 22 | 97 | - | 26128 | y |  |
| `Kentilla.sid` | Kentilla | PSID v2 | Rob_Hubbard | Warhawk | 0 | 1 | 28 | 161 | - | 38271 | y |  |
| `Kings_of_the_Beach_ingame.sid` | Kings of the Beach (ingame) | PSID v2 | Rob_Hubbard | Auf Wiedersehen Monty | 2 | 7 | 6 | 106 | - | 35541 | y |  |
| `Kings_of_the_Beach_intro.sid` | Kings of the Beach (intro) | RSID v2 | Rob_Hubbard, (Rob_Hubbard_Digi) | IK+ | 7 | 1 | 15 | 47 | - | 12338 | y | digi channel dropped |
| `Knucklebusters.sid` | Knucklebusters | PSID v2 | Rob_Hubbard | Warhawk | 0 | 3 (hdr 11) | 30 | 192 | **1** (sub0 1) | 55992 | y | 1 subtune(s) too long |
| `Las_Vegas_Video_Poker.sid` | Las Vegas Video Poker | PSID v2 | Rob_Hubbard | Warhawk | 0 | 16 | 26 | 81 | - | 12483 | y |  |
| `Last_V8.sid` | The Last V8 | RSID v2 | Rob_Hubbard, Voicemaster_Covox | Last V8 | 1 | 12 (hdr 17) | 34 | 66 | 113 | 21248 | y |  |
| `Last_V8_C128_version.sid` | The Last V8 (C128 version) | RSID v2 | Rob_Hubbard, Voicemaster_Covox | Last V8 | 1 | 12 (hdr 18) | 34 | 56 | 154 | 17385 | y |  |
| `Lightforce.sid` | Lightforce | PSID v2 | Rob_Hubbard | Warhawk | 0 | 1 | 23 | 64 | - | 19805 | y |  |
| `Master_of_Magic.sid` | The Master of Magic | PSID v2 | Rob_Hubbard | Warhawk | 0 | 3 | 18 | 85 | - | 22346 | y |  |
| `Mega_Apocalypse.sid` | Mega Apocalypse | RSID v2 | Rob_Hubbard | Mega Apocalypse | 6 | 11 | 43 | 60 | 85 | 18102 | y |  |
| `Monty_on_the_Run.sid` | Monty on the Run | PSID v2 | Rob_Hubbard | Warhawk | 0 | 19 | 21 | 164 | 14 | 48660 | y |  |
| `Mozart.sid` | Mozart | PSID v2 | Rob_Hubbard | Warhawk | 0 | 1 | 20 | 118 | - | 36219 | y |  |
| `Mr_Meaner.sid` | Mr Meaner | RSID v2 | Rob_Hubbard, (Rob_Hubbard_Digi) | Auf Wiedersehen Monty | 2 | 1 | 18 | 83 | - | 23901 | y | digi channel dropped |
| `Nemesis_the_Warlock.sid` | Nemesis the Warlock | PSID v2 | Rob_Hubbard | IK+ | 7 | 15 | 17 | 74 | 23 | 16951 | y |  |
| `Nineteen.sid` | Nineteen | PSID v2 | Rob_Hubbard | IK+ | 7 | 1 | 30 | 46 | - | 11816 | y |  |
| `Ninja.sid` | Ninja | PSID v2 | Rob_Hubbard | Last V8 | 1 | 1 | 14 | 26 | - | 6076 | y |  |
| `Off_the_Cuff.sid` | Off the Cuff | RSID v2 | Rob_Hubbard, (Rob_Hubbard_Digi) | Auf Wiedersehen Monty | 2 | 1 | 18 | 106 | - | 37174 | y | digi channel dropped |
| `One_Man_and_his_Droid.sid` | One Man and his Droid | PSID v2 | Rob_Hubbard | Battle of Britain | 5 | 13 (hdr 14) | 16 | 74 | 33 | 21835 | y |  |
| `One_on_One_Jordan_vs_Bird.sid` | One on One: Jordan vs Bird | RSID v2 | Rob_Hubbard, (Rob_Hubbard_Digi) | Auf Wiedersehen Monty | 2 | 1 (hdr 4) | 21 | 74 | - | 11357 | y | digi channel dropped |
| `Pandora.sid` | Pandora | PSID v2 | Rob_Hubbard | IK+ | 7 | 1 | 17 | 67 | - | 18448 | y |  |
| `Phantoms_of_the_Asteroid.sid` | Phantoms of the Asteroid | PSID v2 | Rob_Hubbard | Last V8 | 1 | 4 | 26 | 96 | - | 27004 | y |  |
| `Powerplay_Hockey_USA_vs_USSR.sid` | Powerplay Hockey: USA vs USSR | RSID v2 | Rob_Hubbard, (Rob_Hubbard_Digi) | Auf Wiedersehen Monty | 2 | 1 (hdr 10) | 13 | 67 | - | 15817 | y | digi channel dropped |
| `Proteus.sid` | Proteus | PSID v2 | Rob_Hubbard | Warhawk | 0 | 1 | 18 | 46 | - | 12143 | y |  |
| `Pygmies_Revenge.sid` | Pygmies Revenge | PSID v2 | Rob_Hubbard | Auf Wiedersehen Monty | 2 | 1 | 18 | 114 | - | 35289 | y | digi channel dropped |
| `Rasputin.sid` | Rasputin | PSID v2 | Rob_Hubbard | Warhawk | 0 | 17 (hdr 18) | 15 | 65 | 23 | 15994 | y |  |
| `Ricochet.sid` | Ricochet | RSID v2 | Rob_Hubbard, (Rob_Hubbard_Digi) | IK+ | 7 | 1 | 17 | 138 | - | 45642 | y |  |
| `Rikky.sid` | Rikky | RSID v2 | Rob_Hubbard, (Rob_Hubbard_Digi) | Auf Wiedersehen Monty | 2 | 1 | 18 | 130 | - | 43269 | y | digi channel dropped |
| `Rock_Tells_the_Tale.sid` | The Rock Tells the Tale | RSID v2 | Rob_Hubbard, (Rob_Hubbard_Digi) | Auf Wiedersehen Monty | 2 | 1 | 18 | 89 | - | 25163 | y | digi channel dropped |
| `Saboteur_II.sid` | Saboteur II | PSID v2 | Rob_Hubbard | Auf Wiedersehen Monty | 2 | 1 | 17 | 54 | - | 13888 | y |  |
| `Samantha_Fox_Strip_Poker.sid` | Samantha Fox Strip Poker | PSID v2 | Rob_Hubbard | Samantha Fox | 3 | 14 | 25 | 83 | - | 15330 | y |  |
| `Sanxion.sid` | Sanxion | PSID v2 | Rob_Hubbard | Warhawk | 0 | 1 (hdr 2) | 30 | 69 | - | 21993 | y |  |
| `Shockway_Rider.sid` | Shockway Rider | PSID v2 | Rob_Hubbard | IK+ | 7 | 1 | 14 | 76 | - | 20425 | y |  |
| `Sigma_Seven.sid` | Sigma Seven | PSID v2 | Rob_Hubbard | Warhawk | 0 | 1 | 9 | 25 | - | 6486 | y |  |
| `Skate_or_Die_intro.sid` | Skate or Die (intro) | RSID v2 | Rob_Hubbard, (Rob_Hubbard_Digi) | IK+ | 7 | 1 | 9 | 53 | - | 13703 | y |  |
| `Spellbound.sid` | Spellbound | PSID v2 | Rob_Hubbard | Warhawk | 0 | 13 | 26 | 111 | 25 | 36687 | y |  |
| `Star_Paws.sid` | Star Paws | PSID v2 | Rob_Hubbard | IK+ | 7 | 3 | 21 | 53 | - | 13534 | y |  |
| `Tarzan.sid` | Tarzan | RSID v2 | Rob_Hubbard, Voicemaster_Covox | Warhawk | 0 | 11 (hdr 12) | 20 | 53 | 2 | 12488 | y |  |
| `Thanatos.sid` | Thanatos | PSID v2 | Rob_Hubbard | Warhawk | 0 | 1 | 6 | 25 | - | 8198 | y |  |
| `Thing_on_a_Spring.sid` | Thing on a Spring | PSID v2 | Rob_Hubbard | Battle of Britain | 5 | 13 (hdr 17) | 16 | 66 | 30 | 19549 | y |  |
| `Thrust.sid` | Thrust | PSID v2 | Rob_Hubbard | Warhawk | 0 | 1 | 29 | 63 | - | 17613 | y |  |
| `Thundercats.sid` | Thundercats | PSID v2 | Rob_Hubbard | IK+ | 7 | 11 (hdr 16) | 30 | 41 | 48 | 12022 | y |  |
| `Trans-Atlantic_Balloon_Challenge.sid` | Trans-Atlantic Balloon Challenge | PSID v2 | Rob_Hubbard | Auf Wiedersehen Monty | 2 | 1 | 20 | 56 | - | 13575 | y |  |
| `W_A_R_Preview.sid` | W.A.R. Preview | PSID v2 | Rob_Hubbard | Warhawk | 0 | 1 | 29 | 68 | - | 19883 | y |  |
| `Warhawk.sid` | Warhawk | PSID v2 | Rob_Hubbard | Warhawk | 0 | 18 | 29 | 70 | 46 | 17646 | y |  |
| `Wiz.sid` | Wiz | PSID v2 | Rob_Hubbard | Auf Wiedersehen Monty | 2 | 3 | 21 | 75 | - | 16356 | y |  |
| `Zoids.sid` | Zoids | PSID v2 | Rob_Hubbard | Warhawk | 0 | 3 | 16 | 59 | - | 19129 | y |  |
| `Zoolook.sid` | Zoolook | PSID v2 | Rob_Hubbard | Warhawk | 0 | 1 | 30 | 37 | - | 10769 | y |  |

`Source` is the input file's own header version — the original player-file format, distinct from both the Hubbard engine variant and the Goattracker output format. `Player`/`Ver` are the detected Hubbard player-engine variant and its track-read version number. `Subtunes` is how many actually reach the `.sng`; where that differs from the PSID header's claim the header value follows in brackets, and the gap is subtunes whose orderlist pointers resolve outside the file (the track table has no length field, so the header routinely over-claims). `Dangling` counts distinct orderlist entries naming a pattern the file does not have; those references are dropped, so the affected voice plays with material missing. **Bold** marks a count that includes subtune 0 — a decode fault rather than a phantom subtune (see Findings).

## Not converted (3)

| File | Title | Source | SIDId | Stage | Player | Sub (hdr) | Instr? | Trk? | Pat? | Reason |
|---|---|---|---|---|---|---:|:-:|:-:|:-:|---|
| `Delta.sid` | Delta | PSID v2 | Rob_Hubbard | patterns | - | 13 | y | y | y | TOO MANY NEW PATTERN CREATED, CAN'T EXPORT TO GOATTRACKER |
| `Dragons_Lair_Part_II.sid` | Dragon's Lair Part II | PSID v2 | Rob_Hubbard | patterns | Warhawk | 10 | y | y | y | TOO MANY NEW PATTERN CREATED, CAN'T EXPORT TO GOATTRACKER |
| `W_A_R.sid` | W.A.R. | PSID v2 | Rob_Hubbard | patterns | Warhawk | 9 | y | y | y | TOO MANY NEW PATTERN CREATED, CAN'T EXPORT TO GOATTRACKER |

`Source` is the input file's own header version; `-` means the header was rejected before it could be read. `Player` is the detected player variant, or `-` when the player-version pass found nothing. `Sub (hdr)` is the PSID header's subtune claim — these files produce no `.sng`, so there is no emitted count to compare it against.

Columns `Instr?`/`Trk?`/`Pat?` show which of the three table-locating detection passes found their target. A file with tables found but no `Player` has a recognisable data layout and an unrecognised player loop.

## Out of scope — not a Hubbard player (12)

Rob Hubbard wrote the **music** in these files; someone else wrote the **player routine**. H2G rips Hubbard player engines by fingerprinting their code, so there is nothing here for it to recognise — these are not failures to fix, and no new signature would bring them in. They are listed apart from the failures for that reason, and excluded from the rate above.

| File | Title | Source | SIDId | Sub (hdr) |
|---|---|---|---|---:|
| `Up_up_and_Away.sid` | Up, up & Away! | PSID v2 | Companion | 5 |
| `Go_Go_Dash.sid` | Go Go Dash | PSID v2 | Jason_Page/RobTracker | 1 |
| `Lakers_vs_Celtics.sid` | Lakers vs Celtics | PSID v2 | Jason_Page/RobTracker | 1 |
| `Lion_Heart.sid` | The Lion Heart | PSID v2 | Jason_Page/RobTracker | 1 |
| `Pacific_Coast.sid` | Pacific Coast | PSID v2 | Jason_Page/RobTracker | 1 |
| `Radio_ACE.sid` | Radio ACE | PSID v2 | Jason_Page/RobTracker | 1 |
| `Sun_Never_Shines.sid` | Sun Never Shines | PSID v2 | Jason_Page/RobTracker | 1 |
| `Casio_Extended.sid` | Casio (Extended) | PSID v2 | SidTracker64 | 1 |
| `Dont_Step_on_My_Wire.sid` | Don't Step on My Wire | PSID v2 | SidTracker64 | 1 |
| `Era_of_Eidolon.sid` | Era of Eidolon | PSID v2 | SidTracker64 | 1 |
| `Robs_Life.sid` | Rob's Life | PSID v2 | SidTracker64 | 3 |
| `Task_Force.sid` | Task Force | PSID v2 | SidTracker64 | 1 |

Converting these would mean a different tool: a ripper for each of those editors, or the emulate-and-capture approach that needs no player knowledge at all.
