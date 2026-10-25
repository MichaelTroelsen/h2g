# Subtune fidelity (`--all-subtunes`)

Traced at `-t 60`, version 0.5.603, -t 60, not the main report's 180: the sweep re-converts, re-packs, traces and renders every subtune with no --jobs path, so it was run as 8 hand-made shards of the corpus at b60aae2 and merged; a figure here is comparable only to another -t 60 sweep. Separate from `docs/FIDELITY.md`, which scores one subtune per file; nothing here changes that report or `build/fidelity.json`.

Every subtune of OURS is paired to an original subtune through `SUBTUNE_COUNTERPART` or the `--diagnose` melody matrix. A pair the matrix does not support, and a stub, is `unpaired` and carries no score; a subtune that does not reach the packed .sid is `dropped`, with convert's reason.

Rows: 284 dropped, 227 measured, 6 not converted, 8 unpaired

| file | orig | ours | status | melody | aud | vs default | note |
|---|---:|---:|---|---:|---:|---:|---|
| 5_Title_Tunes.sid | s0 | o0 | measured | 100 | 94 |  | default pair |
| 5_Title_Tunes.sid | s1 | o1 | measured | 100 | 93 | melody +0, aud -0 |  |
| 5_Title_Tunes.sid | s2 | o2 | measured | 100 | 92 | melody +0, aud -1 |  |
| 5_Title_Tunes.sid | s3 | o3 | measured | 100 | 93 | melody +0, aud -1 |  |
| 5_Title_Tunes.sid | s4 | o4 | measured | 100 | 93 | melody +0, aud -0 |  |
| ACE_II.sid | s0 | o0 | measured | 100 | 94 |  | default pair |
| Action_Biker.sid | s0 | o0 | measured | 100 | 94 | melody +0, aud -3 |  |
| Action_Biker.sid | s1 | o1 | measured | 100 | 97 |  | default pair |
| Action_Biker.sid | s2 | o2 | measured | 100 | 97 | melody +0, aud +0 |  |
| Auf_Wiedersehen_Monty.sid | s0 | o0 | measured | 99 | 95 |  | default pair |
| Auf_Wiedersehen_Monty.sid | s1 | o1 | measured | 95 | 92 | melody -4, aud -3 |  |
| Auf_Wiedersehen_Monty.sid | s2 | o2 | measured | 89 | 84 | melody -10, aud -12 |  |
| Auf_Wiedersehen_Monty.sid | s3 | o3 | measured | 94 | 96 | melody -5, aud +0 |  |
| Auf_Wiedersehen_Monty.sid | s4 | o4 | measured | 100 | 96 | melody +1, aud +1 |  |
| Auf_Wiedersehen_Monty.sid | s5 | o5 | measured | 98 | 89 | melody -1, aud -6 |  |
| Auf_Wiedersehen_Monty.sid | s6 | o6 | measured | 74 | 88 | melody -24, aud -7 |  |
| Auf_Wiedersehen_Monty.sid | s7 | o7 | measured | 93 | 88 | melody -6, aud -7 |  |
| Auf_Wiedersehen_Monty.sid | s8 | o8 | measured | 100 | 97 | melody +1, aud +1 |  |
| Auf_Wiedersehen_Monty.sid | s9 | o9 | measured | 93 | 86 | melody -6, aud -10 |  |
| Auf_Wiedersehen_Monty.sid | s10 | o10 | measured | 94 | 72 | melody -5, aud -24 |  |
| Auf_Wiedersehen_Monty.sid | s11 | o11 | measured | 94 | 86 | melody -5, aud -10 |  |
| Auf_Wiedersehen_Monty.sid | s12 | o12 | measured | 99 | 92 | melody +0, aud -4 |  |
| Bangkok_Knights.sid | s0 | o0 | measured | 98 | 81 |  | default pair |
| Battle_of_Britain.sid | s0 | o0 | measured | 100 | 92 |  | default pair |
| Bump_Set_Spike.sid | s0 | o0 | measured | 100 | 93 |  | default pair |
| Bump_Set_Spike.sid | s1 | o1 | measured | 100 | 92 | melody +0, aud -1 |  |
| Casio_Extended.sid | - | - | not converted | - | - |  | UnsupportedSidError: NO HUBBARD PLAYER DETECTED, CAN'T CONVERT |
| Chain_Reaction.sid | s0 | o0 | measured | 100 | 92 |  | default pair |
| Chicken_Song.sid | s0 | o0 | measured | 100 | 88 |  | default pair |
| Chimera.sid | s0 | o0 | measured | 100 | 94 |  | default pair |
| Chimera.sid | s1 | o1 | measured | 100 | 93 | melody +0, aud -0 |  |
| Chimera.sid | s2 | - | dropped | - | - |  | Header claims $4 subtune(s); the track table runs into another table after $2 |
| Chimera.sid | s3 | - | dropped | - | - |  | Header claims $4 subtune(s); the track table runs into another table after $2 |
| Commando.sid | s0 | o0 | measured | 92 | 94 |  | default pair |
| Commando.sid | s1 | o1 | measured | 100 | 92 | melody +7, aud -1 |  |
| Commando.sid | s2 | o2 | measured | 100 | 92 | melody +8, aud -1 |  |
| Commando.sid | s3 | - | dropped | - | - |  | Header claims $13 subtune(s); the track table runs into another table after $3 |
| Commando.sid | s4 | - | dropped | - | - |  | Header claims $13 subtune(s); the track table runs into another table after $3 |
| Commando.sid | s5 | - | dropped | - | - |  | Header claims $13 subtune(s); the track table runs into another table after $3 |
| Commando.sid | s6 | - | dropped | - | - |  | Header claims $13 subtune(s); the track table runs into another table after $3 |
| Commando.sid | s7 | - | dropped | - | - |  | Header claims $13 subtune(s); the track table runs into another table after $3 |
| Commando.sid | s8 | - | dropped | - | - |  | Header claims $13 subtune(s); the track table runs into another table after $3 |
| Commando.sid | s9 | - | dropped | - | - |  | Header claims $13 subtune(s); the track table runs into another table after $3 |
| Commando.sid | s10 | - | dropped | - | - |  | Header claims $13 subtune(s); the track table runs into another table after $3 |
| Commando.sid | s11 | - | dropped | - | - |  | Header claims $13 subtune(s); the track table runs into another table after $3 |
| Commando.sid | s12 | - | dropped | - | - |  | Header claims $13 subtune(s); the track table runs into another table after $3 |
| Commando.sid | s13 | - | dropped | - | - |  | Header claims $13 subtune(s); the track table runs into another table after $3 |
| Commando.sid | s14 | - | dropped | - | - |  | Header claims $13 subtune(s); the track table runs into another table after $3 |
| Commando.sid | s15 | - | dropped | - | - |  | Header claims $13 subtune(s); the track table runs into another table after $3 |
| Commando.sid | s16 | - | dropped | - | - |  | Header claims $13 subtune(s); the track table runs into another table after $3 |
| Commando.sid | s17 | - | dropped | - | - |  | Header claims $13 subtune(s); the track table runs into another table after $3 |
| Commando.sid | s18 | - | dropped | - | - |  | Header claims $13 subtune(s); the track table runs into another table after $3 |
| Commodore_64_Music_Examples.sid | s1 | o0 | measured | 100 | 94 |  | default pair |
| Commodore_64_Music_Examples.sid | s2 | - | dropped | - | - |  | Header claims $F subtune(s); the track table runs into another table after $1 |
| Commodore_64_Music_Examples.sid | s3 | - | dropped | - | - |  | Header claims $F subtune(s); the track table runs into another table after $1 |
| Commodore_64_Music_Examples.sid | s4 | - | dropped | - | - |  | Header claims $F subtune(s); the track table runs into another table after $1 |
| Commodore_64_Music_Examples.sid | s5 | - | dropped | - | - |  | Header claims $F subtune(s); the track table runs into another table after $1 |
| Commodore_64_Music_Examples.sid | s6 | - | dropped | - | - |  | Header claims $F subtune(s); the track table runs into another table after $1 |
| Commodore_64_Music_Examples.sid | s7 | - | dropped | - | - |  | Header claims $F subtune(s); the track table runs into another table after $1 |
| Commodore_64_Music_Examples.sid | s8 | - | dropped | - | - |  | Header claims $F subtune(s); the track table runs into another table after $1 |
| Commodore_64_Music_Examples.sid | s9 | - | dropped | - | - |  | Header claims $F subtune(s); the track table runs into another table after $1 |
| Commodore_64_Music_Examples.sid | s10 | - | dropped | - | - |  | Header claims $F subtune(s); the track table runs into another table after $1 |
| Commodore_64_Music_Examples.sid | s11 | - | dropped | - | - |  | Header claims $F subtune(s); the track table runs into another table after $1 |
| Commodore_64_Music_Examples.sid | s12 | - | dropped | - | - |  | Header claims $F subtune(s); the track table runs into another table after $1 |
| Commodore_64_Music_Examples.sid | s13 | - | dropped | - | - |  | Header claims $F subtune(s); the track table runs into another table after $1 |
| Commodore_64_Music_Examples.sid | s14 | - | dropped | - | - |  | Header claims $F subtune(s); the track table runs into another table after $1 |
| Confuzion.sid | s0 | o0 | measured | 100 | 80 |  | default pair |
| Crazy_Comets.sid | s0 | o0 | measured | 100 | 92 |  | default pair |
| Crazy_Comets.sid | s1 | o1 | measured | 100 | 91 | melody +0, aud -1 |  |
| Crazy_Comets.sid | s2 | - | dropped | - | - |  | Header claims $11 subtune(s); the player's init dispatch says $2 are music and the rest are sound effects |
| Crazy_Comets.sid | s3 | - | dropped | - | - |  | Header claims $11 subtune(s); the player's init dispatch says $2 are music and the rest are sound effects |
| Crazy_Comets.sid | s4 | - | dropped | - | - |  | Header claims $11 subtune(s); the player's init dispatch says $2 are music and the rest are sound effects |
| Crazy_Comets.sid | s5 | - | dropped | - | - |  | Header claims $11 subtune(s); the player's init dispatch says $2 are music and the rest are sound effects |
| Crazy_Comets.sid | s6 | - | dropped | - | - |  | Header claims $11 subtune(s); the player's init dispatch says $2 are music and the rest are sound effects |
| Crazy_Comets.sid | s7 | - | dropped | - | - |  | Header claims $11 subtune(s); the player's init dispatch says $2 are music and the rest are sound effects |
| Crazy_Comets.sid | s8 | - | dropped | - | - |  | Header claims $11 subtune(s); the player's init dispatch says $2 are music and the rest are sound effects |
| Crazy_Comets.sid | s9 | - | dropped | - | - |  | Header claims $11 subtune(s); the player's init dispatch says $2 are music and the rest are sound effects |
| Crazy_Comets.sid | s10 | - | dropped | - | - |  | Header claims $11 subtune(s); the player's init dispatch says $2 are music and the rest are sound effects |
| Crazy_Comets.sid | s11 | - | dropped | - | - |  | Header claims $11 subtune(s); the player's init dispatch says $2 are music and the rest are sound effects |
| Crazy_Comets.sid | s12 | - | dropped | - | - |  | Header claims $11 subtune(s); the player's init dispatch says $2 are music and the rest are sound effects |
| Crazy_Comets.sid | s13 | - | dropped | - | - |  | Header claims $11 subtune(s); the player's init dispatch says $2 are music and the rest are sound effects |
| Crazy_Comets.sid | s14 | - | dropped | - | - |  | Header claims $11 subtune(s); the player's init dispatch says $2 are music and the rest are sound effects |
| Crazy_Comets.sid | s15 | - | dropped | - | - |  | Header claims $11 subtune(s); the player's init dispatch says $2 are music and the rest are sound effects |
| Crazy_Comets.sid | s16 | - | dropped | - | - |  | Header claims $11 subtune(s); the player's init dispatch says $2 are music and the rest are sound effects |
| Deep_Strike.sid | s0 | o0 | measured | 100 | 93 |  | default pair |
| Delta.sid | s0 | o0 | measured | 100 | 87 | melody -0, aud -8 |  |
| Delta.sid | s1 | o1 | measured | 100 | 9 | melody +0, aud -86 |  |
| Delta.sid | s2 | o2 | measured | 100 | 91 | melody +0, aud -4 |  |
| Delta.sid | s3 | o3 | measured | 100 | 96 | melody +0, aud +1 |  |
| Delta.sid | s4 | o4 | measured | 100 | 96 | melody +0, aud +1 |  |
| Delta.sid | s5 | o5 | measured | 100 | 95 | melody +0, aud -0 |  |
| Delta.sid | s6 | o6 | measured | 100 | 95 | melody +0, aud -1 |  |
| Delta.sid | s7 | o7 | measured | 100 | 96 | melody +0, aud +1 |  |
| Delta.sid | s8 | o8 | measured | 100 | 95 | melody +0, aud +0 |  |
| Delta.sid | s9 | o9 | measured | 100 | 95 | melody +0, aud +0 |  |
| Delta.sid | s10 | o10 | measured | 97 | 77 | melody -3, aud -18 |  |
| Delta.sid | s11 | o11 | measured | 100 | 95 |  | default pair |
| Delta.sid | s12 | o12 | measured | 100 | 94 | melody -0, aud -1 |  |
| Delta_Mix-E-Load_loader.sid | s0 | o0 | measured | 100 | 93 |  | default pair |
| Delta_Mix-E-Load_loader.sid | s1 | - | dropped | - | - |  | Header claims $10 subtune(s); the track table runs into another table after $1 |
| Delta_Mix-E-Load_loader.sid | s2 | - | dropped | - | - |  | Header claims $10 subtune(s); the track table runs into another table after $1 |
| Delta_Mix-E-Load_loader.sid | s3 | - | dropped | - | - |  | Header claims $10 subtune(s); the track table runs into another table after $1 |
| Delta_Mix-E-Load_loader.sid | s4 | - | dropped | - | - |  | Header claims $10 subtune(s); the track table runs into another table after $1 |
| Delta_Mix-E-Load_loader.sid | s5 | - | dropped | - | - |  | Header claims $10 subtune(s); the track table runs into another table after $1 |
| Delta_Mix-E-Load_loader.sid | s6 | - | dropped | - | - |  | Header claims $10 subtune(s); the track table runs into another table after $1 |
| Delta_Mix-E-Load_loader.sid | s7 | - | dropped | - | - |  | Header claims $10 subtune(s); the track table runs into another table after $1 |
| Delta_Mix-E-Load_loader.sid | s8 | - | dropped | - | - |  | Header claims $10 subtune(s); the track table runs into another table after $1 |
| Delta_Mix-E-Load_loader.sid | s9 | - | dropped | - | - |  | Header claims $10 subtune(s); the track table runs into another table after $1 |
| Delta_Mix-E-Load_loader.sid | s10 | - | dropped | - | - |  | Header claims $10 subtune(s); the track table runs into another table after $1 |
| Delta_Mix-E-Load_loader.sid | s11 | - | dropped | - | - |  | Header claims $10 subtune(s); the track table runs into another table after $1 |
| Delta_Mix-E-Load_loader.sid | s12 | - | dropped | - | - |  | Header claims $10 subtune(s); the track table runs into another table after $1 |
| Delta_Mix-E-Load_loader.sid | s13 | - | dropped | - | - |  | Header claims $10 subtune(s); the track table runs into another table after $1 |
| Delta_Mix-E-Load_loader.sid | s14 | - | dropped | - | - |  | Header claims $10 subtune(s); the track table runs into another table after $1 |
| Delta_Mix-E-Load_loader.sid | s15 | - | dropped | - | - |  | Header claims $10 subtune(s); the track table runs into another table after $1 |
| Devils_Galop.sid | s0 | o0 | measured | 100 | 93 |  | default pair |
| Dont_Step_on_My_Wire.sid | - | - | not converted | - | - |  | UnsupportedSidError: NO HUBBARD PLAYER DETECTED, CAN'T CONVERT |
| Dragons_Lair_Part_II.sid | s5 | o0 | unpaired | - | - |  | matrix does not support a pairing: best original s5 matches at 42%, under the 50% a pairing needs |
| Dragons_Lair_Part_II.sid | s5 | o1 | unpaired | - | - |  | matrix does not support a pairing: best original s5 matches at 36%, under the 50% a pairing needs |
| Dragons_Lair_Part_II.sid | s5 | o2 | measured | 95 | 90 | melody +1, aud +2 |  |
| Dragons_Lair_Part_II.sid | s5 | o3 | unpaired | - | - |  | matrix does not support a pairing: best original s5 matches at 26%, under the 50% a pairing needs |
| Dragons_Lair_Part_II.sid | s5 | o4 | unpaired | - | - |  | matrix does not support a pairing: best original s5 matches at 37%, under the 50% a pairing needs |
| Dragons_Lair_Part_II.sid | s5 | o5 | measured | 72 | 88 | melody -21, aud +0 |  |
| Dragons_Lair_Part_II.sid | s5 | o6 | measured | 68 | 88 | melody -25, aud +0 |  |
| Dragons_Lair_Part_II.sid | s1 | o7 | measured | 100 | 94 | melody +6, aud +6 |  |
| Dragons_Lair_Part_II.sid | s9 | o8 | measured | 97 | 89 | melody +3, aud +2 |  |
| Dragons_Lair_Part_II.sid | s0 | o9 | measured | 94 | 88 |  | default pair |
| Era_of_Eidolon.sid | - | - | not converted | - | - |  | UnsupportedSidError: NO HUBBARD PLAYER DETECTED, CAN'T CONVERT |
| Flash_Gordon.sid | s0 | o0 | measured | 100 | 92 |  | default pair |
| Flash_Gordon.sid | s1 | o1 | measured | 100 | 10 | melody +0, aud -82 |  |
| Flash_Gordon.sid | s2 | o2 | measured | 100 | 79 | melody +0, aud -13 |  |
| Flash_Gordon.sid | s3 | o3 | measured | 100 | 83 | melody +0, aud -9 |  |
| Flash_Gordon.sid | s4 | o4 | measured | 100 | 80 | melody +0, aud -13 |  |
| Flash_Gordon.sid | s5 | o5 | measured | 99 | 87 | melody -1, aud -5 |  |
| Flash_Gordon.sid | s6 | o6 | measured | 100 | 83 | melody +0, aud -10 |  |
| Flash_Gordon.sid | s7 | o7 | measured | 76 | 81 | melody -23, aud -11 |  |
| Flash_Gordon.sid | s8 | o8 | measured | 100 | 88 | melody +0, aud -4 |  |
| Food_Feud.sid | s0 | o0 | measured | 100 | 94 |  | default pair |
| Formula_1_Simulator.sid | s0 | o0 | measured | 100 | 93 |  | default pair |
| Formula_1_Simulator.sid | s1 | - | dropped | - | - |  | Header claims $2 subtune(s); the track table runs into another table after $1 |
| Game_Killer.sid | s0 | o0 | measured | 100 | 92 |  | default pair |
| Geoff_Capes_Strongman_Challenge.sid | s0 | o0 | measured | 100 | 93 |  | default pair |
| Geoff_Capes_Strongman_Challenge.sid | s1 | o1 | measured | 100 | 92 | melody +0, aud -1 |  |
| Geoff_Capes_Strongman_Challenge.sid | s2 | o2 | measured | 91 | 93 | melody -9, aud -1 |  |
| Geoff_Capes_Strongman_Challenge.sid | s3 | o3 | measured | 100 | 94 | melody +0, aud +1 |  |
| Geoff_Capes_Strongman_Challenge.sid | s4 | o4 | measured | 82 | 91 | melody -18, aud -2 |  |
| Geoff_Capes_Strongman_Challenge.sid | s5 | o5 | measured | 100 | 93 | melody +0, aud +0 |  |
| Geoff_Capes_Strongman_Challenge.sid | s6 | o6 | measured | 100 | 2 | melody +0, aud -91 |  |
| Geoff_Capes_Strongman_Challenge.sid | s7 | o7 | measured | 100 | 2 | melody +0, aud -91 |  |
| Geoff_Capes_Strongman_Challenge.sid | s8 | - | dropped | - | - |  | Header claims $18 subtune(s); the player's init dispatch says $8 are music and the rest are sound effects |
| Geoff_Capes_Strongman_Challenge.sid | s9 | - | dropped | - | - |  | Header claims $18 subtune(s); the player's init dispatch says $8 are music and the rest are sound effects |
| Geoff_Capes_Strongman_Challenge.sid | s10 | - | dropped | - | - |  | Header claims $18 subtune(s); the player's init dispatch says $8 are music and the rest are sound effects |
| Geoff_Capes_Strongman_Challenge.sid | s11 | - | dropped | - | - |  | Header claims $18 subtune(s); the player's init dispatch says $8 are music and the rest are sound effects |
| Geoff_Capes_Strongman_Challenge.sid | s12 | - | dropped | - | - |  | Header claims $18 subtune(s); the player's init dispatch says $8 are music and the rest are sound effects |
| Geoff_Capes_Strongman_Challenge.sid | s13 | - | dropped | - | - |  | Header claims $18 subtune(s); the player's init dispatch says $8 are music and the rest are sound effects |
| Geoff_Capes_Strongman_Challenge.sid | s14 | - | dropped | - | - |  | Header claims $18 subtune(s); the player's init dispatch says $8 are music and the rest are sound effects |
| Geoff_Capes_Strongman_Challenge.sid | s15 | - | dropped | - | - |  | Header claims $18 subtune(s); the player's init dispatch says $8 are music and the rest are sound effects |
| Geoff_Capes_Strongman_Challenge.sid | s16 | - | dropped | - | - |  | Header claims $18 subtune(s); the player's init dispatch says $8 are music and the rest are sound effects |
| Geoff_Capes_Strongman_Challenge.sid | s17 | - | dropped | - | - |  | Header claims $18 subtune(s); the player's init dispatch says $8 are music and the rest are sound effects |
| Geoff_Capes_Strongman_Challenge.sid | s18 | - | dropped | - | - |  | Header claims $18 subtune(s); the player's init dispatch says $8 are music and the rest are sound effects |
| Geoff_Capes_Strongman_Challenge.sid | s19 | - | dropped | - | - |  | Header claims $18 subtune(s); the player's init dispatch says $8 are music and the rest are sound effects |
| Geoff_Capes_Strongman_Challenge.sid | s20 | - | dropped | - | - |  | Header claims $18 subtune(s); the player's init dispatch says $8 are music and the rest are sound effects |
| Geoff_Capes_Strongman_Challenge.sid | s21 | - | dropped | - | - |  | Header claims $18 subtune(s); the player's init dispatch says $8 are music and the rest are sound effects |
| Geoff_Capes_Strongman_Challenge.sid | s22 | - | dropped | - | - |  | Header claims $18 subtune(s); the player's init dispatch says $8 are music and the rest are sound effects |
| Geoff_Capes_Strongman_Challenge.sid | s23 | - | dropped | - | - |  | Header claims $18 subtune(s); the player's init dispatch says $8 are music and the rest are sound effects |
| Gerry_the_Germ.sid | s0 | o0 | measured | 100 | 93 | melody -0, aud -1 |  |
| Gerry_the_Germ.sid | s1 | o1 | measured | 100 | 94 | melody -0, aud +0 |  |
| Gerry_the_Germ.sid | s2 | o2 | measured | 100 | 93 | melody +0, aud +0 |  |
| Gerry_the_Germ.sid | s3 | o3 | measured | 100 | 93 | melody +0, aud -0 |  |
| Gerry_the_Germ.sid | s4 | o4 | measured | 100 | 94 | melody -0, aud +1 |  |
| Gerry_the_Germ.sid | s5 | o5 | measured | 100 | 91 | melody -0, aud -2 |  |
| Gerry_the_Germ.sid | s6 | o6 | measured | 100 | 93 |  | default pair |
| Gerry_the_Germ.sid | s7 | - | dropped | - | - |  | Header claims $17 subtune(s); the player's init dispatch says $7 are music and the rest are sound effects |
| Gerry_the_Germ.sid | s8 | - | dropped | - | - |  | Header claims $17 subtune(s); the player's init dispatch says $7 are music and the rest are sound effects |
| Gerry_the_Germ.sid | s9 | - | dropped | - | - |  | Header claims $17 subtune(s); the player's init dispatch says $7 are music and the rest are sound effects |
| Gerry_the_Germ.sid | s10 | - | dropped | - | - |  | Header claims $17 subtune(s); the player's init dispatch says $7 are music and the rest are sound effects |
| Gerry_the_Germ.sid | s11 | - | dropped | - | - |  | Header claims $17 subtune(s); the player's init dispatch says $7 are music and the rest are sound effects |
| Gerry_the_Germ.sid | s12 | - | dropped | - | - |  | Header claims $17 subtune(s); the player's init dispatch says $7 are music and the rest are sound effects |
| Gerry_the_Germ.sid | s13 | - | dropped | - | - |  | Header claims $17 subtune(s); the player's init dispatch says $7 are music and the rest are sound effects |
| Gerry_the_Germ.sid | s14 | - | dropped | - | - |  | Header claims $17 subtune(s); the player's init dispatch says $7 are music and the rest are sound effects |
| Gerry_the_Germ.sid | s15 | - | dropped | - | - |  | Header claims $17 subtune(s); the player's init dispatch says $7 are music and the rest are sound effects |
| Gerry_the_Germ.sid | s16 | - | dropped | - | - |  | Header claims $17 subtune(s); the player's init dispatch says $7 are music and the rest are sound effects |
| Gerry_the_Germ.sid | s17 | - | dropped | - | - |  | Header claims $17 subtune(s); the player's init dispatch says $7 are music and the rest are sound effects |
| Gerry_the_Germ.sid | s18 | - | dropped | - | - |  | Header claims $17 subtune(s); the player's init dispatch says $7 are music and the rest are sound effects |
| Gerry_the_Germ.sid | s19 | - | dropped | - | - |  | Header claims $17 subtune(s); the player's init dispatch says $7 are music and the rest are sound effects |
| Gerry_the_Germ.sid | s20 | - | dropped | - | - |  | Header claims $17 subtune(s); the player's init dispatch says $7 are music and the rest are sound effects |
| Gerry_the_Germ.sid | s21 | - | dropped | - | - |  | Header claims $17 subtune(s); the player's init dispatch says $7 are music and the rest are sound effects |
| Gerry_the_Germ.sid | s22 | - | dropped | - | - |  | Header claims $17 subtune(s); the player's init dispatch says $7 are music and the rest are sound effects |
| Go_Go_Dash.sid | s0 | o0 | measured | 100 | 92 |  | default pair |
| Gremlins.sid | s0 | o0 | measured | 100 | 93 |  | default pair |
| Gremlins.sid | s1 | o1 | measured | 100 | 90 | melody +0, aud -3 |  |
| Gremlins.sid | s2 | o2 | measured | 100 | 93 | melody -0, aud +0 |  |
| Gremlins.sid | s3 | o3 | measured | 100 | 93 | melody +0, aud -0 |  |
| Gremlins.sid | s4 | o4 | measured | 100 | 95 | melody +0, aud +2 |  |
| Gremlins.sid | s5 | o5 | measured | 100 | 93 | melody -0, aud -0 |  |
| Gremlins.sid | s6 | o6 | measured | 100 | 93 | melody +0, aud -0 |  |
| Gremlins.sid | s7 | - | dropped | - | - |  | Header claims $1A subtune(s); the track table runs into another table after $7 |
| Gremlins.sid | s8 | - | dropped | - | - |  | Header claims $1A subtune(s); the track table runs into another table after $7 |
| Gremlins.sid | s9 | - | dropped | - | - |  | Header claims $1A subtune(s); the track table runs into another table after $7 |
| Gremlins.sid | s10 | - | dropped | - | - |  | Header claims $1A subtune(s); the track table runs into another table after $7 |
| Gremlins.sid | s11 | - | dropped | - | - |  | Header claims $1A subtune(s); the track table runs into another table after $7 |
| Gremlins.sid | s12 | - | dropped | - | - |  | Header claims $1A subtune(s); the track table runs into another table after $7 |
| Gremlins.sid | s13 | - | dropped | - | - |  | Header claims $1A subtune(s); the track table runs into another table after $7 |
| Gremlins.sid | s14 | - | dropped | - | - |  | Header claims $1A subtune(s); the track table runs into another table after $7 |
| Gremlins.sid | s15 | - | dropped | - | - |  | Header claims $1A subtune(s); the track table runs into another table after $7 |
| Gremlins.sid | s16 | - | dropped | - | - |  | Header claims $1A subtune(s); the track table runs into another table after $7 |
| Gremlins.sid | s17 | - | dropped | - | - |  | Header claims $1A subtune(s); the track table runs into another table after $7 |
| Gremlins.sid | s18 | - | dropped | - | - |  | Header claims $1A subtune(s); the track table runs into another table after $7 |
| Gremlins.sid | s19 | - | dropped | - | - |  | Header claims $1A subtune(s); the track table runs into another table after $7 |
| Gremlins.sid | s20 | - | dropped | - | - |  | Header claims $1A subtune(s); the track table runs into another table after $7 |
| Gremlins.sid | s21 | - | dropped | - | - |  | Header claims $1A subtune(s); the track table runs into another table after $7 |
| Gremlins.sid | s22 | - | dropped | - | - |  | Header claims $1A subtune(s); the track table runs into another table after $7 |
| Gremlins.sid | s23 | - | dropped | - | - |  | Header claims $1A subtune(s); the track table runs into another table after $7 |
| Gremlins.sid | s24 | - | dropped | - | - |  | Header claims $1A subtune(s); the track table runs into another table after $7 |
| Gremlins.sid | s25 | - | dropped | - | - |  | Header claims $1A subtune(s); the track table runs into another table after $7 |
| Hollywood_or_Bust.sid | s0 | o0 | measured | 54 | 93 | melody -30, aud +0 |  |
| Hollywood_or_Bust.sid | s1 | o1 | measured | 65 | 91 | melody -20, aud -2 |  |
| Hollywood_or_Bust.sid | s2 | o2 | measured | 84 | 92 |  | default pair |
| Hollywood_or_Bust.sid | s3 | - | dropped | - | - |  | Header claims $A subtune(s); the player's init dispatch says $3 are music and the rest are sound effects |
| Hollywood_or_Bust.sid | s4 | - | dropped | - | - |  | Header claims $A subtune(s); the player's init dispatch says $3 are music and the rest are sound effects |
| Hollywood_or_Bust.sid | s5 | - | dropped | - | - |  | Header claims $A subtune(s); the player's init dispatch says $3 are music and the rest are sound effects |
| Hollywood_or_Bust.sid | s6 | - | dropped | - | - |  | Header claims $A subtune(s); the player's init dispatch says $3 are music and the rest are sound effects |
| Hollywood_or_Bust.sid | s7 | - | dropped | - | - |  | Header claims $A subtune(s); the player's init dispatch says $3 are music and the rest are sound effects |
| Hollywood_or_Bust.sid | s8 | - | dropped | - | - |  | Header claims $A subtune(s); the player's init dispatch says $3 are music and the rest are sound effects |
| Hollywood_or_Bust.sid | s9 | - | dropped | - | - |  | Header claims $A subtune(s); the player's init dispatch says $3 are music and the rest are sound effects |
| Human_Race.sid | s0 | o0 | measured | 100 | 93 |  | default pair |
| Human_Race.sid | s1 | o1 | measured | 100 | 90 | melody -0, aud -3 |  |
| Human_Race.sid | s2 | o2 | measured | 100 | 87 | melody +0, aud -6 |  |
| Human_Race.sid | s3 | o3 | measured | 100 | 91 | melody -0, aud -2 |  |
| Human_Race.sid | s4 | o4 | measured | 100 | 90 | melody -0, aud -4 |  |
| Hunter_Patrol.sid | s0 | o0 | measured | 100 | 94 |  | default pair |
| IK_plus.sid | s0 | o0 | measured | 100 | 84 |  | default pair |
| IK_plus.sid | s1 | - | dropped | - | - |  | Header claims $3 subtune(s); the track table runs into another table after $1 |
| IK_plus.sid | s2 | - | dropped | - | - |  | Header claims $3 subtune(s); the track table runs into another table after $1 |
| I_Ball.sid | s0 | o0 | measured | 97 | 86 |  | default pair |
| I_Ball.sid | s1 | - | dropped | - | - |  | Header claims $4 subtune(s); the track table runs into another table after $1 |
| I_Ball.sid | s2 | - | dropped | - | - |  | Header claims $4 subtune(s); the track table runs into another table after $1 |
| I_Ball.sid | s3 | - | dropped | - | - |  | Header claims $4 subtune(s); the track table runs into another table after $1 |
| International_Karate.sid | s0 | o0 | measured | 100 | 90 |  | default pair |
| Kentilla.sid | s0 | o0 | measured | 100 | 92 |  | default pair |
| Kings_of_the_Beach_ingame.sid | s0 | o0 | measured | 93 | 68 | melody -7, aud +2 |  |
| Kings_of_the_Beach_ingame.sid | s1 | o1 | measured | 100 | 77 | melody +0, aud +11 |  |
| Kings_of_the_Beach_ingame.sid | s2 | o2 | measured | 100 | 66 | melody +0, aud +0 |  |
| Kings_of_the_Beach_ingame.sid | s3 | o3 | measured | 94 | 73 | melody -6, aud +7 |  |
| Kings_of_the_Beach_ingame.sid | s4 | o4 | measured | 100 | 66 |  | default pair |
| Kings_of_the_Beach_ingame.sid | s5 | o5 | measured | 93 | 68 | melody -7, aud +2 |  |
| Kings_of_the_Beach_ingame.sid | s6 | o6 | measured | 100 | 70 | melody +0, aud +4 |  |
| Knucklebusters.sid | s0 | o0 | measured | 100 | 88 | melody +0, aud -6 |  |
| Knucklebusters.sid | s1 | o1 | measured | 100 | 93 |  | default pair |
| Knucklebusters.sid | s2 | o2 | measured | 100 | 90 | melody +0, aud -4 |  |
| Knucklebusters.sid | s3 | - | dropped | - | - |  | Header claims $B subtune(s); the player's init dispatch says $3 are music and the rest are sound effects |
| Knucklebusters.sid | s4 | - | dropped | - | - |  | Header claims $B subtune(s); the player's init dispatch says $3 are music and the rest are sound effects |
| Knucklebusters.sid | s5 | - | dropped | - | - |  | Header claims $B subtune(s); the player's init dispatch says $3 are music and the rest are sound effects |
| Knucklebusters.sid | s6 | - | dropped | - | - |  | Header claims $B subtune(s); the player's init dispatch says $3 are music and the rest are sound effects |
| Knucklebusters.sid | s7 | - | dropped | - | - |  | Header claims $B subtune(s); the player's init dispatch says $3 are music and the rest are sound effects |
| Knucklebusters.sid | s8 | - | dropped | - | - |  | Header claims $B subtune(s); the player's init dispatch says $3 are music and the rest are sound effects |
| Knucklebusters.sid | s9 | - | dropped | - | - |  | Header claims $B subtune(s); the player's init dispatch says $3 are music and the rest are sound effects |
| Knucklebusters.sid | s10 | - | dropped | - | - |  | Header claims $B subtune(s); the player's init dispatch says $3 are music and the rest are sound effects |
| Lakers_vs_Celtics.sid | s0 | o0 | measured | 92 | 93 |  | default pair |
| Las_Vegas_Video_Poker.sid | s0 | o0 | measured | 100 | 91 |  | default pair |
| Las_Vegas_Video_Poker.sid | s1 | o1 | measured | 100 | 5 | melody +0, aud -86 |  |
| Las_Vegas_Video_Poker.sid | s2 | o2 | measured | 100 | 5 | melody +0, aud -86 |  |
| Las_Vegas_Video_Poker.sid | s3 | o3 | measured | 100 | 5 | melody +0, aud -86 |  |
| Las_Vegas_Video_Poker.sid | s4 | o4 | measured | 100 | 5 | melody +0, aud -86 |  |
| Las_Vegas_Video_Poker.sid | s5 | o5 | measured | 100 | 5 | melody +0, aud -86 |  |
| Las_Vegas_Video_Poker.sid | s6 | o6 | measured | 100 | 7 | melody +0, aud -83 |  |
| Las_Vegas_Video_Poker.sid | s7 | o7 | unpaired | - | - |  | matrix does not support a pairing: best original s7 matches at 33%, under the 50% a pairing needs |
| Las_Vegas_Video_Poker.sid | s8 | o8 | measured | 100 | 8 | melody +0, aud -83 |  |
| Las_Vegas_Video_Poker.sid | s9 | o9 | measured | 100 | 6 | melody +0, aud -84 |  |
| Las_Vegas_Video_Poker.sid | s10 | o10 | measured | 100 | 7 | melody +0, aud -84 |  |
| Las_Vegas_Video_Poker.sid | s11 | o11 | measured | 100 | 6 | melody +0, aud -85 |  |
| Las_Vegas_Video_Poker.sid | s12 | o12 | measured | 100 | 6 | melody +0, aud -84 |  |
| Las_Vegas_Video_Poker.sid | s13 | o13 | measured | 100 | 7 | melody +0, aud -83 |  |
| Las_Vegas_Video_Poker.sid | s14 | o14 | measured | 100 | 3 | melody +0, aud -87 |  |
| Las_Vegas_Video_Poker.sid | s15 | o15 | measured | 67 | 4 | melody -33, aud -87 |  |
| Last_V8.sid | s0 | o0 | measured | 100 | 93 |  | default pair |
| Last_V8.sid | s1 | o1 | measured | 100 | 93 | melody +0, aud -1 |  |
| Last_V8.sid | s2 | o2 | measured | 100 | 92 | melody +0, aud -2 |  |
| Last_V8.sid | s3 | - | dropped | - | - |  | Header claims $11 subtune(s); the track table runs into another table after $3 |
| Last_V8.sid | s4 | - | dropped | - | - |  | Header claims $11 subtune(s); the track table runs into another table after $3 |
| Last_V8.sid | s5 | - | dropped | - | - |  | Header claims $11 subtune(s); the track table runs into another table after $3 |
| Last_V8.sid | s6 | - | dropped | - | - |  | Header claims $11 subtune(s); the track table runs into another table after $3 |
| Last_V8.sid | s7 | - | dropped | - | - |  | Header claims $11 subtune(s); the track table runs into another table after $3 |
| Last_V8.sid | s8 | - | dropped | - | - |  | Header claims $11 subtune(s); the track table runs into another table after $3 |
| Last_V8.sid | s9 | - | dropped | - | - |  | Header claims $11 subtune(s); the track table runs into another table after $3 |
| Last_V8.sid | s10 | - | dropped | - | - |  | Header claims $11 subtune(s); the track table runs into another table after $3 |
| Last_V8.sid | s11 | - | dropped | - | - |  | Header claims $11 subtune(s); the track table runs into another table after $3 |
| Last_V8.sid | s12 | - | dropped | - | - |  | Header claims $11 subtune(s); the track table runs into another table after $3 |
| Last_V8.sid | s13 | - | dropped | - | - |  | Header claims $11 subtune(s); the track table runs into another table after $3 |
| Last_V8.sid | s14 | - | dropped | - | - |  | Header claims $11 subtune(s); the track table runs into another table after $3 |
| Last_V8.sid | s15 | - | dropped | - | - |  | Header claims $11 subtune(s); the track table runs into another table after $3 |
| Last_V8.sid | s16 | - | dropped | - | - |  | Header claims $11 subtune(s); the track table runs into another table after $3 |
| Last_V8_C128_version.sid | s0 | o0 | measured | 100 | 93 |  | default pair |
| Last_V8_C128_version.sid | s1 | o1 | measured | 100 | 93 | melody +0, aud -1 |  |
| Last_V8_C128_version.sid | s2 | o2 | measured | 100 | 92 | melody +0, aud -1 |  |
| Last_V8_C128_version.sid | s3 | - | dropped | - | - |  | Header claims $12 subtune(s); the track table runs into another table after $3 |
| Last_V8_C128_version.sid | s4 | - | dropped | - | - |  | Header claims $12 subtune(s); the track table runs into another table after $3 |
| Last_V8_C128_version.sid | s5 | - | dropped | - | - |  | Header claims $12 subtune(s); the track table runs into another table after $3 |
| Last_V8_C128_version.sid | s6 | - | dropped | - | - |  | Header claims $12 subtune(s); the track table runs into another table after $3 |
| Last_V8_C128_version.sid | s7 | - | dropped | - | - |  | Header claims $12 subtune(s); the track table runs into another table after $3 |
| Last_V8_C128_version.sid | s8 | - | dropped | - | - |  | Header claims $12 subtune(s); the track table runs into another table after $3 |
| Last_V8_C128_version.sid | s9 | - | dropped | - | - |  | Header claims $12 subtune(s); the track table runs into another table after $3 |
| Last_V8_C128_version.sid | s10 | - | dropped | - | - |  | Header claims $12 subtune(s); the track table runs into another table after $3 |
| Last_V8_C128_version.sid | s11 | - | dropped | - | - |  | Header claims $12 subtune(s); the track table runs into another table after $3 |
| Last_V8_C128_version.sid | s12 | - | dropped | - | - |  | Header claims $12 subtune(s); the track table runs into another table after $3 |
| Last_V8_C128_version.sid | s13 | - | dropped | - | - |  | Header claims $12 subtune(s); the track table runs into another table after $3 |
| Last_V8_C128_version.sid | s14 | - | dropped | - | - |  | Header claims $12 subtune(s); the track table runs into another table after $3 |
| Last_V8_C128_version.sid | s15 | - | dropped | - | - |  | Header claims $12 subtune(s); the track table runs into another table after $3 |
| Last_V8_C128_version.sid | s16 | - | dropped | - | - |  | Header claims $12 subtune(s); the track table runs into another table after $3 |
| Last_V8_C128_version.sid | s17 | - | dropped | - | - |  | Header claims $12 subtune(s); the track table runs into another table after $3 |
| Lightforce.sid | s0 | o0 | measured | 100 | 94 |  | default pair |
| Lion_Heart.sid | s0 | o0 | measured | 93 | 91 |  | default pair |
| Master_of_Magic.sid | s0 | o0 | measured | 100 | 94 |  | default pair |
| Master_of_Magic.sid | s1 | o1 | measured | 99 | 81 | melody -1, aud -12 |  |
| Master_of_Magic.sid | s2 | o2 | measured | 100 | 88 | melody +0, aud -5 |  |
| Mega_Apocalypse.sid | s0 | o0 | measured | 100 | 84 |  | default pair |
| Mega_Apocalypse.sid | s1 | - | dropped | - | - |  | Header claims $B subtune(s); the track table runs into another table after $1 |
| Mega_Apocalypse.sid | s2 | - | dropped | - | - |  | Header claims $B subtune(s); the track table runs into another table after $1 |
| Mega_Apocalypse.sid | s3 | - | dropped | - | - |  | Header claims $B subtune(s); the track table runs into another table after $1 |
| Mega_Apocalypse.sid | s4 | - | dropped | - | - |  | Header claims $B subtune(s); the track table runs into another table after $1 |
| Mega_Apocalypse.sid | s5 | - | dropped | - | - |  | Header claims $B subtune(s); the track table runs into another table after $1 |
| Mega_Apocalypse.sid | s6 | - | dropped | - | - |  | Header claims $B subtune(s); the track table runs into another table after $1 |
| Mega_Apocalypse.sid | s7 | - | dropped | - | - |  | Header claims $B subtune(s); the track table runs into another table after $1 |
| Mega_Apocalypse.sid | s8 | - | dropped | - | - |  | Header claims $B subtune(s); the track table runs into another table after $1 |
| Mega_Apocalypse.sid | s9 | - | dropped | - | - |  | Header claims $B subtune(s); the track table runs into another table after $1 |
| Mega_Apocalypse.sid | s10 | - | dropped | - | - |  | Header claims $B subtune(s); the track table runs into another table after $1 |
| Monty_on_the_Run.sid | s0 | o0 | measured | 100 | 93 |  | default pair |
| Monty_on_the_Run.sid | s1 | o1 | measured | 100 | 97 | melody +0, aud +4 |  |
| Monty_on_the_Run.sid | s2 | o2 | measured | 100 | 95 | melody +0, aud +2 |  |
| Monty_on_the_Run.sid | s3 | - | dropped | - | - |  | Header claims $13 subtune(s); the track table runs into another table after $3 |
| Monty_on_the_Run.sid | s4 | - | dropped | - | - |  | Header claims $13 subtune(s); the track table runs into another table after $3 |
| Monty_on_the_Run.sid | s5 | - | dropped | - | - |  | Header claims $13 subtune(s); the track table runs into another table after $3 |
| Monty_on_the_Run.sid | s6 | - | dropped | - | - |  | Header claims $13 subtune(s); the track table runs into another table after $3 |
| Monty_on_the_Run.sid | s7 | - | dropped | - | - |  | Header claims $13 subtune(s); the track table runs into another table after $3 |
| Monty_on_the_Run.sid | s8 | - | dropped | - | - |  | Header claims $13 subtune(s); the track table runs into another table after $3 |
| Monty_on_the_Run.sid | s9 | - | dropped | - | - |  | Header claims $13 subtune(s); the track table runs into another table after $3 |
| Monty_on_the_Run.sid | s10 | - | dropped | - | - |  | Header claims $13 subtune(s); the track table runs into another table after $3 |
| Monty_on_the_Run.sid | s11 | - | dropped | - | - |  | Header claims $13 subtune(s); the track table runs into another table after $3 |
| Monty_on_the_Run.sid | s12 | - | dropped | - | - |  | Header claims $13 subtune(s); the track table runs into another table after $3 |
| Monty_on_the_Run.sid | s13 | - | dropped | - | - |  | Header claims $13 subtune(s); the track table runs into another table after $3 |
| Monty_on_the_Run.sid | s14 | - | dropped | - | - |  | Header claims $13 subtune(s); the track table runs into another table after $3 |
| Monty_on_the_Run.sid | s15 | - | dropped | - | - |  | Header claims $13 subtune(s); the track table runs into another table after $3 |
| Monty_on_the_Run.sid | s16 | - | dropped | - | - |  | Header claims $13 subtune(s); the track table runs into another table after $3 |
| Monty_on_the_Run.sid | s17 | - | dropped | - | - |  | Header claims $13 subtune(s); the track table runs into another table after $3 |
| Monty_on_the_Run.sid | s18 | - | dropped | - | - |  | Header claims $13 subtune(s); the track table runs into another table after $3 |
| Mozart.sid | s0 | o0 | measured | 100 | 92 |  | default pair |
| Nemesis_the_Warlock.sid | s0 | o0 | measured | 100 | 95 |  | default pair |
| Nemesis_the_Warlock.sid | s1 | - | dropped | - | - |  | Header claims $F subtune(s); the track table runs into another table after $1 |
| Nemesis_the_Warlock.sid | s2 | - | dropped | - | - |  | Header claims $F subtune(s); the track table runs into another table after $1 |
| Nemesis_the_Warlock.sid | s3 | - | dropped | - | - |  | Header claims $F subtune(s); the track table runs into another table after $1 |
| Nemesis_the_Warlock.sid | s4 | - | dropped | - | - |  | Header claims $F subtune(s); the track table runs into another table after $1 |
| Nemesis_the_Warlock.sid | s5 | - | dropped | - | - |  | Header claims $F subtune(s); the track table runs into another table after $1 |
| Nemesis_the_Warlock.sid | s6 | - | dropped | - | - |  | Header claims $F subtune(s); the track table runs into another table after $1 |
| Nemesis_the_Warlock.sid | s7 | - | dropped | - | - |  | Header claims $F subtune(s); the track table runs into another table after $1 |
| Nemesis_the_Warlock.sid | s8 | - | dropped | - | - |  | Header claims $F subtune(s); the track table runs into another table after $1 |
| Nemesis_the_Warlock.sid | s9 | - | dropped | - | - |  | Header claims $F subtune(s); the track table runs into another table after $1 |
| Nemesis_the_Warlock.sid | s10 | - | dropped | - | - |  | Header claims $F subtune(s); the track table runs into another table after $1 |
| Nemesis_the_Warlock.sid | s11 | - | dropped | - | - |  | Header claims $F subtune(s); the track table runs into another table after $1 |
| Nemesis_the_Warlock.sid | s12 | - | dropped | - | - |  | Header claims $F subtune(s); the track table runs into another table after $1 |
| Nemesis_the_Warlock.sid | s13 | - | dropped | - | - |  | Header claims $F subtune(s); the track table runs into another table after $1 |
| Nemesis_the_Warlock.sid | s14 | - | dropped | - | - |  | Header claims $F subtune(s); the track table runs into another table after $1 |
| Nineteen.sid | s0 | o0 | measured | 99 | 89 |  | default pair |
| Ninja.sid | s0 | o0 | measured | 100 | 84 |  | default pair |
| One_Man_and_his_Droid.sid | s0 | o0 | measured | 100 | 94 |  | default pair |
| One_Man_and_his_Droid.sid | s1 | - | dropped | - | - |  | Header claims $E subtune(s); the track table runs into another table after $1 |
| One_Man_and_his_Droid.sid | s2 | - | dropped | - | - |  | Header claims $E subtune(s); the track table runs into another table after $1 |
| One_Man_and_his_Droid.sid | s3 | - | dropped | - | - |  | Header claims $E subtune(s); the track table runs into another table after $1 |
| One_Man_and_his_Droid.sid | s4 | - | dropped | - | - |  | Header claims $E subtune(s); the track table runs into another table after $1 |
| One_Man_and_his_Droid.sid | s5 | - | dropped | - | - |  | Header claims $E subtune(s); the track table runs into another table after $1 |
| One_Man_and_his_Droid.sid | s6 | - | dropped | - | - |  | Header claims $E subtune(s); the track table runs into another table after $1 |
| One_Man_and_his_Droid.sid | s7 | - | dropped | - | - |  | Header claims $E subtune(s); the track table runs into another table after $1 |
| One_Man_and_his_Droid.sid | s8 | - | dropped | - | - |  | Header claims $E subtune(s); the track table runs into another table after $1 |
| One_Man_and_his_Droid.sid | s9 | - | dropped | - | - |  | Header claims $E subtune(s); the track table runs into another table after $1 |
| One_Man_and_his_Droid.sid | s10 | - | dropped | - | - |  | Header claims $E subtune(s); the track table runs into another table after $1 |
| One_Man_and_his_Droid.sid | s11 | - | dropped | - | - |  | Header claims $E subtune(s); the track table runs into another table after $1 |
| One_Man_and_his_Droid.sid | s12 | - | dropped | - | - |  | Header claims $E subtune(s); the track table runs into another table after $1 |
| One_Man_and_his_Droid.sid | s13 | - | dropped | - | - |  | Header claims $E subtune(s); the track table runs into another table after $1 |
| Pacific_Coast.sid | s0 | o0 | measured | 98 | 90 |  | default pair |
| Pandora.sid | s0 | o0 | measured | 100 | 92 |  | default pair |
| Phantoms_of_the_Asteroid.sid | s0 | o0 | measured | 100 | 93 |  | default pair |
| Phantoms_of_the_Asteroid.sid | s1 | o1 | measured | 100 | 92 | melody +0, aud -1 |  |
| Phantoms_of_the_Asteroid.sid | s2 | o2 | measured | 97 | 88 | melody -3, aud -5 |  |
| Phantoms_of_the_Asteroid.sid | s2 | o3 | unpaired | - | - |  | matrix does not support a pairing: best original s2 matches at 1%, under the 50% a pairing needs |
| Proteus.sid | s0 | o0 | measured | 100 | 93 |  | default pair |
| Pygmies_Revenge.sid | s0 | o0 | measured | 97 | 92 |  | default pair |
| Radio_ACE.sid | s0 | o0 | measured | 97 | 91 |  | default pair |
| Rasputin.sid | s0 | o0 | measured | 100 | 93 |  | default pair |
| Rasputin.sid | s1 | o1 | measured | 100 | 92 | melody +0, aud -1 |  |
| Rasputin.sid | s2 | - | dropped | - | - |  | Header claims $12 subtune(s); the track table runs into another table after $2 |
| Rasputin.sid | s3 | - | dropped | - | - |  | Header claims $12 subtune(s); the track table runs into another table after $2 |
| Rasputin.sid | s4 | - | dropped | - | - |  | Header claims $12 subtune(s); the track table runs into another table after $2 |
| Rasputin.sid | s5 | - | dropped | - | - |  | Header claims $12 subtune(s); the track table runs into another table after $2 |
| Rasputin.sid | s6 | - | dropped | - | - |  | Header claims $12 subtune(s); the track table runs into another table after $2 |
| Rasputin.sid | s7 | - | dropped | - | - |  | Header claims $12 subtune(s); the track table runs into another table after $2 |
| Rasputin.sid | s8 | - | dropped | - | - |  | Header claims $12 subtune(s); the track table runs into another table after $2 |
| Rasputin.sid | s9 | - | dropped | - | - |  | Header claims $12 subtune(s); the track table runs into another table after $2 |
| Rasputin.sid | s10 | - | dropped | - | - |  | Header claims $12 subtune(s); the track table runs into another table after $2 |
| Rasputin.sid | s11 | - | dropped | - | - |  | Header claims $12 subtune(s); the track table runs into another table after $2 |
| Rasputin.sid | s12 | - | dropped | - | - |  | Header claims $12 subtune(s); the track table runs into another table after $2 |
| Rasputin.sid | s13 | - | dropped | - | - |  | Header claims $12 subtune(s); the track table runs into another table after $2 |
| Rasputin.sid | s14 | - | dropped | - | - |  | Header claims $12 subtune(s); the track table runs into another table after $2 |
| Rasputin.sid | s15 | - | dropped | - | - |  | Header claims $12 subtune(s); the track table runs into another table after $2 |
| Rasputin.sid | s16 | - | dropped | - | - |  | Header claims $12 subtune(s); the track table runs into another table after $2 |
| Rasputin.sid | s17 | - | dropped | - | - |  | Header claims $12 subtune(s); the track table runs into another table after $2 |
| Robs_Life.sid | - | - | not converted | - | - |  | UnsupportedSidError: NO HUBBARD PLAYER DETECTED, CAN'T CONVERT |
| Saboteur_II.sid | s0 | o0 | measured | 100 | 94 |  | default pair |
| Samantha_Fox_Strip_Poker.sid | s0 | o0 | measured | 100 | 4 | melody +0, aud -88 |  |
| Samantha_Fox_Strip_Poker.sid | s1 | o1 | measured | 100 | 4 | melody +0, aud -88 |  |
| Samantha_Fox_Strip_Poker.sid | s2 | o2 | measured | 100 | 4 | melody +0, aud -88 |  |
| Samantha_Fox_Strip_Poker.sid | s3 | o3 | measured | 100 | 4 | melody +0, aud -88 |  |
| Samantha_Fox_Strip_Poker.sid | s4 | o4 | measured | 100 | 4 | melody +0, aud -88 |  |
| Samantha_Fox_Strip_Poker.sid | s5 | o5 | measured | 100 | 4 | melody +0, aud -88 |  |
| Samantha_Fox_Strip_Poker.sid | s6 | o6 | measured | 100 | 4 | melody +0, aud -88 |  |
| Samantha_Fox_Strip_Poker.sid | s7 | o7 | measured | 100 | 4 | melody +0, aud -88 |  |
| Samantha_Fox_Strip_Poker.sid | s8 | o8 | measured | 100 | 92 | melody +0, aud +1 |  |
| Samantha_Fox_Strip_Poker.sid | s9 | o9 | measured | 100 | 92 |  | default pair |
| Samantha_Fox_Strip_Poker.sid | s10 | o10 | measured | 100 | 82 | melody +0, aud -9 |  |
| Samantha_Fox_Strip_Poker.sid | s11 | o11 | measured | 100 | 74 | melody +0, aud -17 |  |
| Samantha_Fox_Strip_Poker.sid | s12 | o12 | measured | 100 | 73 | melody +0, aud -19 |  |
| Samantha_Fox_Strip_Poker.sid | s11 | o13 | unpaired | - | - |  | matrix does not support a pairing: best original s11 matches at 4%, under the 50% a pairing needs |
| Sanxion.sid | s0 | o0 | measured | 100 | 87 |  | default pair |
| Sanxion.sid | s1 | - | dropped | - | - |  | Header claims $2 subtune(s); the track table runs into another table after $1 |
| Shockway_Rider.sid | s0 | o0 | measured | 100 | 94 |  | default pair |
| Sigma_Seven.sid | s0 | o0 | measured | 99 | 94 |  | default pair |
| Spellbound.sid | s0 | o0 | measured | 100 | 94 |  | default pair |
| Spellbound.sid | s1 | o1 | measured | 100 | 93 | melody +0, aud -0 |  |
| Spellbound.sid | s2 | o2 | measured | 100 | 90 | melody +0, aud -4 |  |
| Spellbound.sid | s3 | - | dropped | - | - |  | Header claims $D subtune(s); the player's init dispatch says $3 are music and the rest are sound effects |
| Spellbound.sid | s4 | - | dropped | - | - |  | Header claims $D subtune(s); the player's init dispatch says $3 are music and the rest are sound effects |
| Spellbound.sid | s5 | - | dropped | - | - |  | Header claims $D subtune(s); the player's init dispatch says $3 are music and the rest are sound effects |
| Spellbound.sid | s6 | - | dropped | - | - |  | Header claims $D subtune(s); the player's init dispatch says $3 are music and the rest are sound effects |
| Spellbound.sid | s7 | - | dropped | - | - |  | Header claims $D subtune(s); the player's init dispatch says $3 are music and the rest are sound effects |
| Spellbound.sid | s8 | - | dropped | - | - |  | Header claims $D subtune(s); the player's init dispatch says $3 are music and the rest are sound effects |
| Spellbound.sid | s9 | - | dropped | - | - |  | Header claims $D subtune(s); the player's init dispatch says $3 are music and the rest are sound effects |
| Spellbound.sid | s10 | - | dropped | - | - |  | Header claims $D subtune(s); the player's init dispatch says $3 are music and the rest are sound effects |
| Spellbound.sid | s11 | - | dropped | - | - |  | Header claims $D subtune(s); the player's init dispatch says $3 are music and the rest are sound effects |
| Spellbound.sid | s12 | - | dropped | - | - |  | Header claims $D subtune(s); the player's init dispatch says $3 are music and the rest are sound effects |
| Star_Paws.sid | s0 | o0 | measured | 100 | 94 |  | default pair |
| Star_Paws.sid | s1 | o1 | measured | 94 | 89 | melody -6, aud -5 |  |
| Star_Paws.sid | s2 | o2 | measured | 99 | 85 | melody -1, aud -10 |  |
| Sun_Never_Shines.sid | s0 | o0 | measured | 91 | 89 |  | default pair |
| Tarzan.sid | s0 | o0 | measured | 100 | 94 |  | default pair |
| Tarzan.sid | s1 | o1 | measured | 93 | 77 | melody -7, aud -17 |  |
| Tarzan.sid | s2 | o2 | unpaired | - | - |  | matrix does not support a pairing: best original s2 matches at 23%, under the 50% a pairing needs |
| Tarzan.sid | s3 | o3 | measured | 94 | 80 | melody -6, aud -14 |  |
| Tarzan.sid | s4 | o4 | measured | 100 | 97 | melody +0, aud +3 |  |
| Tarzan.sid | s5 | o5 | measured | 91 | 80 | melody -8, aud -14 |  |
| Tarzan.sid | s6 | o6 | measured | 96 | 87 | melody -4, aud -7 |  |
| Tarzan.sid | s7 | o7 | measured | 100 | 96 | melody +0, aud +2 |  |
| Tarzan.sid | s8 | o8 | measured | 96 | 80 | melody -4, aud -14 |  |
| Tarzan.sid | s9 | o9 | measured | 95 | 90 | melody -5, aud -4 |  |
| Tarzan.sid | s10 | o10 | measured | 100 | 88 | melody +0, aud -6 |  |
| Tarzan.sid | s11 | - | dropped | - | - |  | Header claims $C subtune(s); the track table runs into another table after $B |
| Task_Force.sid | - | - | not converted | - | - |  | UnsupportedSidError: NO HUBBARD PLAYER DETECTED, CAN'T CONVERT |
| Thanatos.sid | s0 | o0 | measured | 100 | 95 |  | default pair |
| Thing_on_a_Spring.sid | s0 | o0 | measured | 99 | 93 |  | default pair |
| Thing_on_a_Spring.sid | s1 | - | dropped | - | - |  | Header claims $11 subtune(s); the player's init dispatch says $1 are music and the rest are sound effects |
| Thing_on_a_Spring.sid | s2 | - | dropped | - | - |  | Header claims $11 subtune(s); the player's init dispatch says $1 are music and the rest are sound effects |
| Thing_on_a_Spring.sid | s3 | - | dropped | - | - |  | Header claims $11 subtune(s); the player's init dispatch says $1 are music and the rest are sound effects |
| Thing_on_a_Spring.sid | s4 | - | dropped | - | - |  | Header claims $11 subtune(s); the player's init dispatch says $1 are music and the rest are sound effects |
| Thing_on_a_Spring.sid | s5 | - | dropped | - | - |  | Header claims $11 subtune(s); the player's init dispatch says $1 are music and the rest are sound effects |
| Thing_on_a_Spring.sid | s6 | - | dropped | - | - |  | Header claims $11 subtune(s); the player's init dispatch says $1 are music and the rest are sound effects |
| Thing_on_a_Spring.sid | s7 | - | dropped | - | - |  | Header claims $11 subtune(s); the player's init dispatch says $1 are music and the rest are sound effects |
| Thing_on_a_Spring.sid | s8 | - | dropped | - | - |  | Header claims $11 subtune(s); the player's init dispatch says $1 are music and the rest are sound effects |
| Thing_on_a_Spring.sid | s9 | - | dropped | - | - |  | Header claims $11 subtune(s); the player's init dispatch says $1 are music and the rest are sound effects |
| Thing_on_a_Spring.sid | s10 | - | dropped | - | - |  | Header claims $11 subtune(s); the player's init dispatch says $1 are music and the rest are sound effects |
| Thing_on_a_Spring.sid | s11 | - | dropped | - | - |  | Header claims $11 subtune(s); the player's init dispatch says $1 are music and the rest are sound effects |
| Thing_on_a_Spring.sid | s12 | - | dropped | - | - |  | Header claims $11 subtune(s); the player's init dispatch says $1 are music and the rest are sound effects |
| Thing_on_a_Spring.sid | s13 | - | dropped | - | - |  | Header claims $11 subtune(s); the player's init dispatch says $1 are music and the rest are sound effects |
| Thing_on_a_Spring.sid | s14 | - | dropped | - | - |  | Header claims $11 subtune(s); the player's init dispatch says $1 are music and the rest are sound effects |
| Thing_on_a_Spring.sid | s15 | - | dropped | - | - |  | Header claims $11 subtune(s); the player's init dispatch says $1 are music and the rest are sound effects |
| Thing_on_a_Spring.sid | s16 | - | dropped | - | - |  | Header claims $11 subtune(s); the player's init dispatch says $1 are music and the rest are sound effects |
| Thrust.sid | s0 | o0 | measured | 100 | 91 |  | default pair |
| Thundercats.sid | s0 | o0 | measured | 77 | 93 |  | default pair |
| Thundercats.sid | s1 | - | dropped | - | - |  | Header claims $10 subtune(s); the track table runs into another table after $1 |
| Thundercats.sid | s2 | - | dropped | - | - |  | Header claims $10 subtune(s); the track table runs into another table after $1 |
| Thundercats.sid | s3 | - | dropped | - | - |  | Header claims $10 subtune(s); the track table runs into another table after $1 |
| Thundercats.sid | s4 | - | dropped | - | - |  | Header claims $10 subtune(s); the track table runs into another table after $1 |
| Thundercats.sid | s5 | - | dropped | - | - |  | Header claims $10 subtune(s); the track table runs into another table after $1 |
| Thundercats.sid | s6 | - | dropped | - | - |  | Header claims $10 subtune(s); the track table runs into another table after $1 |
| Thundercats.sid | s7 | - | dropped | - | - |  | Header claims $10 subtune(s); the track table runs into another table after $1 |
| Thundercats.sid | s8 | - | dropped | - | - |  | Header claims $10 subtune(s); the track table runs into another table after $1 |
| Thundercats.sid | s9 | - | dropped | - | - |  | Header claims $10 subtune(s); the track table runs into another table after $1 |
| Thundercats.sid | s10 | - | dropped | - | - |  | Header claims $10 subtune(s); the track table runs into another table after $1 |
| Thundercats.sid | s11 | - | dropped | - | - |  | Header claims $10 subtune(s); the track table runs into another table after $1 |
| Thundercats.sid | s12 | - | dropped | - | - |  | Header claims $10 subtune(s); the track table runs into another table after $1 |
| Thundercats.sid | s13 | - | dropped | - | - |  | Header claims $10 subtune(s); the track table runs into another table after $1 |
| Thundercats.sid | s14 | - | dropped | - | - |  | Header claims $10 subtune(s); the track table runs into another table after $1 |
| Thundercats.sid | s15 | - | dropped | - | - |  | Header claims $10 subtune(s); the track table runs into another table after $1 |
| Trans-Atlantic_Balloon_Challenge.sid | s0 | o0 | measured | 100 | 92 |  | default pair |
| Up_up_and_Away.sid | - | - | not converted | - | - |  | UnsupportedSidError: NO HUBBARD PLAYER DETECTED, CAN'T CONVERT |
| W_A_R.sid | s0 | o0 | measured | 100 | 93 |  | default pair |
| W_A_R.sid | s1 | o1 | measured | 100 | 77 | melody +0, aud -16 |  |
| W_A_R.sid | s2 | o2 | measured | 100 | 7 | melody +0, aud -86 |  |
| W_A_R.sid | s3 | o3 | measured | 100 | 11 | melody +0, aud -82 |  |
| W_A_R.sid | s4 | o4 | measured | 75 | 88 | melody -25, aud -5 |  |
| W_A_R.sid | s5 | o5 | measured | 100 | 9 | melody +0, aud -84 |  |
| W_A_R.sid | s6 | o6 | measured | 100 | 42 | melody +0, aud -52 |  |
| W_A_R.sid | s7 | o7 | measured | 89 | 92 | melody -11, aud -2 |  |
| W_A_R.sid | s8 | - | dropped | - | - |  | Header claims $9 subtune(s); the track table runs into another table after $8 |
| W_A_R_Preview.sid | s0 | o0 | measured | 100 | 93 |  | default pair |
| Warhawk.sid | s0 | o0 | measured | 100 | 92 |  | default pair |
| Warhawk.sid | s1 | o1 | measured | 100 | 10 | melody +0, aud -82 |  |
| Warhawk.sid | s2 | o2 | measured | 100 | 90 | melody +0, aud -2 |  |
| Warhawk.sid | s3 | o3 | measured | 100 | 52 | melody +0, aud -39 |  |
| Warhawk.sid | s4 | o4 | measured | 100 | 38 | melody +0, aud -54 |  |
| Warhawk.sid | s5 | o5 | measured | 67 | 20 | melody -33, aud -72 |  |
| Warhawk.sid | s6 | o6 | measured | 100 | 2 | melody +0, aud -90 |  |
| Warhawk.sid | s7 | o7 | measured | 100 | 77 | melody +0, aud -15 |  |
| Warhawk.sid | s8 | o8 | measured | 100 | 28 | melody +0, aud -64 |  |
| Warhawk.sid | s9 | - | dropped | - | - |  | Header claims $12 subtune(s); the player's init dispatch says $9 are music and the rest are sound effects |
| Warhawk.sid | s10 | - | dropped | - | - |  | Header claims $12 subtune(s); the player's init dispatch says $9 are music and the rest are sound effects |
| Warhawk.sid | s11 | - | dropped | - | - |  | Header claims $12 subtune(s); the player's init dispatch says $9 are music and the rest are sound effects |
| Warhawk.sid | s12 | - | dropped | - | - |  | Header claims $12 subtune(s); the player's init dispatch says $9 are music and the rest are sound effects |
| Warhawk.sid | s13 | - | dropped | - | - |  | Header claims $12 subtune(s); the player's init dispatch says $9 are music and the rest are sound effects |
| Warhawk.sid | s14 | - | dropped | - | - |  | Header claims $12 subtune(s); the player's init dispatch says $9 are music and the rest are sound effects |
| Warhawk.sid | s15 | - | dropped | - | - |  | Header claims $12 subtune(s); the player's init dispatch says $9 are music and the rest are sound effects |
| Warhawk.sid | s16 | - | dropped | - | - |  | Header claims $12 subtune(s); the player's init dispatch says $9 are music and the rest are sound effects |
| Warhawk.sid | s17 | - | dropped | - | - |  | Header claims $12 subtune(s); the player's init dispatch says $9 are music and the rest are sound effects |
| Wiz.sid | s0 | o0 | measured | 100 | 92 |  | default pair |
| Wiz.sid | s1 | o1 | measured | 94 | 74 | melody -6, aud -18 |  |
| Wiz.sid | s2 | o2 | measured | 58 | 74 | melody -41, aud -18 |  |
| Zoids.sid | s0 | o0 | measured | 100 | 94 |  | default pair |
| Zoids.sid | s1 | o1 | measured | 100 | 95 | melody +0, aud +1 |  |
| Zoids.sid | s2 | o2 | measured | 100 | 94 | melody +0, aud -1 |  |
| Zoolook.sid | s0 | o0 | measured | 100 | 92 |  | default pair |

## Measured subtunes 10 or more points below their file's default

- Auf_Wiedersehen_Monty.sid o2: aud -12
- Auf_Wiedersehen_Monty.sid o6: melody -24
- Auf_Wiedersehen_Monty.sid o10: aud -24
- Delta.sid o1: aud -86
- Delta.sid o10: aud -18
- Dragons_Lair_Part_II.sid o5: melody -21
- Dragons_Lair_Part_II.sid o6: melody -25
- Flash_Gordon.sid o1: aud -82
- Flash_Gordon.sid o2: aud -13
- Flash_Gordon.sid o4: aud -13
- Flash_Gordon.sid o7: melody -23
- Flash_Gordon.sid o7: aud -11
- Geoff_Capes_Strongman_Challenge.sid o4: melody -18
- Geoff_Capes_Strongman_Challenge.sid o6: aud -91
- Geoff_Capes_Strongman_Challenge.sid o7: aud -91
- Hollywood_or_Bust.sid o0: melody -30
- Hollywood_or_Bust.sid o1: melody -20
- Las_Vegas_Video_Poker.sid o1: aud -86
- Las_Vegas_Video_Poker.sid o2: aud -86
- Las_Vegas_Video_Poker.sid o3: aud -86
- Las_Vegas_Video_Poker.sid o4: aud -86
- Las_Vegas_Video_Poker.sid o5: aud -86
- Las_Vegas_Video_Poker.sid o6: aud -83
- Las_Vegas_Video_Poker.sid o8: aud -83
- Las_Vegas_Video_Poker.sid o9: aud -84
- Las_Vegas_Video_Poker.sid o10: aud -84
- Las_Vegas_Video_Poker.sid o11: aud -85
- Las_Vegas_Video_Poker.sid o12: aud -84
- Las_Vegas_Video_Poker.sid o13: aud -83
- Las_Vegas_Video_Poker.sid o14: aud -87
- Las_Vegas_Video_Poker.sid o15: melody -33
- Las_Vegas_Video_Poker.sid o15: aud -87
- Master_of_Magic.sid o1: aud -12
- Samantha_Fox_Strip_Poker.sid o0: aud -88
- Samantha_Fox_Strip_Poker.sid o1: aud -88
- Samantha_Fox_Strip_Poker.sid o2: aud -88
- Samantha_Fox_Strip_Poker.sid o3: aud -88
- Samantha_Fox_Strip_Poker.sid o4: aud -88
- Samantha_Fox_Strip_Poker.sid o5: aud -88
- Samantha_Fox_Strip_Poker.sid o6: aud -88
- Samantha_Fox_Strip_Poker.sid o7: aud -88
- Samantha_Fox_Strip_Poker.sid o11: aud -17
- Samantha_Fox_Strip_Poker.sid o12: aud -19
- Tarzan.sid o1: aud -17
- Tarzan.sid o3: aud -14
- Tarzan.sid o5: aud -14
- Tarzan.sid o8: aud -14
- W_A_R.sid o1: aud -16
- W_A_R.sid o2: aud -86
- W_A_R.sid o3: aud -82
- W_A_R.sid o4: melody -25
- W_A_R.sid o5: aud -84
- W_A_R.sid o6: aud -52
- W_A_R.sid o7: melody -11
- Warhawk.sid o1: aud -82
- Warhawk.sid o3: aud -39
- Warhawk.sid o4: aud -54
- Warhawk.sid o5: melody -33
- Warhawk.sid o5: aud -72
- Warhawk.sid o6: aud -90
- Warhawk.sid o7: aud -15
- Warhawk.sid o8: aud -64
- Wiz.sid o1: aud -18
- Wiz.sid o2: melody -41
- Wiz.sid o2: aud -18


## On hold: DIGI (measured with everything else, never worked)

## Measured subtunes 10 or more points below their file's default

- none
