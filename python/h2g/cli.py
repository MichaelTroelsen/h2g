from __future__ import annotations

import argparse
import os
import sys

from . import __version__
from .convert import UnsupportedSidError, convert
from .goatwriter import DEFAULT_FORMAT, FORMATS, GT_MIN_TEMPO
from .patterns import GT_DEFAULT_ROWS, GT_MAX_ROWS, ConversionAbort
from .sidfile import SidFormatError


def _default_output(sid_path: str) -> str:
    base, _ = os.path.splitext(sid_path)
    return base + ".sng"


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(
        prog="h2g",
        description="Convert a Rob Hubbard .SID file to Goattracker (.sng) format.",
    )
    parser.add_argument("--version", action="version", version=f"h2g {__version__}")
    parser.add_argument("sid_file", help="input .sid file")
    parser.add_argument("-o", "--output", help="output .sng file (default: <input>.sng)")
    parser.add_argument("-q", "--quiet", action="store_true", help="suppress progress log")
    parser.add_argument(
        "--max-rows", type=int, default=GT_DEFAULT_ROWS, metavar="N",
        help=f"pattern-slicing length, 1..{GT_MAX_ROWS} (default: {GT_DEFAULT_ROWS}, "
             f"matching the original tool; {GT_MAX_ROWS} is Goattracker's real limit "
             "since v2.32 and fits some tunes that otherwise exceed its capacity)")
    parser.add_argument(
        "--terminate-patterns", action="store_true",
        help="append an explicit ENDPATT row to every pattern slice, as "
             "Goattracker's own saver does. Off by default because it changes "
             "the output bytes; without it, sliced patterns rely on the "
             "loader pre-filling rows with ENDPATT")
    parser.add_argument(
        "--format", choices=FORMATS, default=DEFAULT_FORMAT,
        help="output .sng format (default: %(default)s). gts2 is what the "
             "original tool wrote; gts5 is the modern 4-table format and avoids "
             "a buffer overrun in Goattracker's legacy gts2 importer, so prefer "
             "it for files you will actually open in Goattracker")
    parser.add_argument(
        "--tempo", metavar="N|auto", default=None,
        help="write a startup tempo (calls per pattern row, 2..127) as a "
             "CMD_SETTEMPO on each subtune's first pattern row. 'auto' "
             "derives it per subtune from the player's own speed gate -- "
             "the counter that makes a duration unit last reload+1 frames "
             "-- and falls back to 3 where no gate is found. Omitted by "
             "default, which leaves Goattracker's startup default of 6 "
             "calls/row -- too slow, since this converter emits one row per "
             "player tick. Tunes ticking every 1-2 frames also need the "
             "packed player's call rate raised: convert logs the gt2reloc "
             "-S value, and presets.json records it per song")
    parser.add_argument(
        "--dedup-patterns", action="store_true",
        help="share one pattern between byte-identical slices. Hubbard tunes repeat heavily, so this typically removes 10-20%% of patterns and brings some tunes under Goattracker's 208-pattern limit. Off by default because it changes the output bytes. Does not shorten orderlists")
    parser.add_argument(
        "--prune-patterns", action="store_true",
        help="drop patterns that no track's orderlist references. The pattern "
             "table is sized from the gap between the SID's LO/HI address "
             "tables, so it routinely holds entries the song never plays "
             "(Dragon's Lair II: 131 of 202). Unlike the other options this "
             "cannot change playback -- an unreferenced pattern is "
             "unreachable -- but it renumbers the rest, so it is off by "
             "default. Can bring a tune under the 208-pattern limit")
    parser.add_argument(
        "--pack-repeats", action="store_true",
        help="collapse runs of one repeated pattern into Goattracker REPEAT "
             "commands ($D0-$DF, 'play the next pattern n+1 times'). A run of "
             "L costs ceil(L/16)*2 bytes instead of L. This is the only option "
             "that shortens an orderlist rather than the pattern data, so it "
             "is the only one that can bring a tune under the 254-byte "
             "orderlist limit. Off by default: it changes the output bytes")
    parser.add_argument(
        "--legal-restart", action="store_true",
        help="rewrite the out-of-range restart position that stands in for "
             "Hubbard's 'tune ended' marker. Goattracker's player treats it as "
             "a stop, but its exporter (greloc.c:244) refuses the song, so "
             "gt2reloc silently writes no .sid -- and reports nothing when it "
             "does. With this the tune loops from the top instead of ending, "
             "which loses the composer's intent but is what makes a packed "
             ".sid possible at all. Off by default: it changes the output bytes")
    parser.add_argument(
        "--vibrato", action="store_true",
        help="give each instrument the vibrato its player runs. 56 of 95 "
             "corpus players carry it in one record byte (bits 3-6 an "
             "amplitude bound, bits 0-2 a depth shift applied to the semitone "
             "interval at the current note), and Goattracker expresses the "
             "same thing natively -- but this writer has always left the two "
             "record bytes that drive it at zero, so no file it produced has "
             "ever vibrated. Needs --format gts5. Off by default: it changes "
             "the output bytes")
    parser.add_argument(
        "--slides", action="store_true",
        help="read the second operand byte of a pitch-slide command in the "
             "players that have one. Those players hold the slide step as a "
             "16-bit value split across two pattern bytes; this converter read "
             "only the first, so the second was played as a note and every "
             "byte after it in that pattern was read one position out. Applies "
             "only where detection finds that fetch (41 of 95 corpus files), "
             "and is a no-op for the rest. Off by default: it changes the "
             "output bytes of the files it does reach")
    parser.add_argument(
        "--filter", dest="filters", action="store_true",
        help="emit the player's filter instead of an empty filter table. "
             "Hubbard keeps a resonance/routing byte and a signed per-frame "
             "cutoff step per instrument, in a two-byte array parallel to the "
             "instrument table; 32 of the 95 corpus files drive the filter and "
             "every one of them has always been written with the filter "
             "switched off. Applied only where the routine, its passband and "
             "the cutoff each note starts from can all be read (16 files), and "
             "only to instruments whose routing byte actually routes a voice. "
             "Off by default: it changes the output bytes of the files it "
             "does reach")
    parser.add_argument(
        "--effects", action="store_true",
        help="read the instrument effect byte (+7) as each player really "
             "reads it, instead of as Warhawk's bit-field for every file. Bit "
             "$02 raises the note a semitone every four frames while it is "
             "held (252 records across 59 corpus files); it was ignored "
             "entirely, and is written here as a note-relative portamento in "
             "the wavetable, which needs --format gts5. Bit $04's arpeggio is "
             "silent in the player when its interval nibble is zero, and bits "
             "$01 and $04 mean nothing at all in a player with no such "
             "routine -- 159 of 450 drum records and 544 of 683 arpeggio "
             "records corpus-wide, all of which the original synthesized. "
             "Where the drum routine is present the gesture is also written "
             "the way the player plays it: waveform with the gate released, a "
             "downward frequency sweep, then noise. Off by default: it "
             "changes the output bytes")
    parser.add_argument(
        "--compact-instruments", action="store_true",
        help="drop the empty \"Clear Voice\" slot the VB6 original reserved at "
             "instrument 1 and put the player's record 0 there instead. "
             "Goattracker reserves nothing -- its format stores instruments "
             "from 1 and a pattern column of 0 already means \"no change\" -- so "
             "the placeholder costs an instrument slot, five wavetable entries, "
             "and offsets every instrument number by one against the player's "
             "own numbering. Off by default: it renumbers every instrument in "
             "every file, the byte-exact Commando fixture included")
    parser.add_argument(
        "--rest-instrument", action="store_true",
        help="carry an instrument change that lands on a rest with the rest "
             "itself. Goattracker latches the instrument column whenever it is "
             "non-zero, before and independently of the note test "
             "(gplay.c:912-914), so a rest row can carry the change and sound "
             "nothing. The original tool emitted a C-0 on instrument 1 instead "
             "-- the Clear Voice, all-zero ADSR with the testbit set, i.e. a "
             "click and a retrigger of whatever was sounding: 1422 rows across "
             "64 corpus files. Off by default because it changes the output "
             "bytes, the byte-exact Commando fixture among them")
    parser.add_argument(
        "--status-bit6", action="store_true",
        help="honour the player's bit-6-first status test (BIT/BVS): a "
             "$C0-$FE status byte consumes only itself, instead of also an "
             "operand and a note the player never reads -- which kept the "
             "rest of the pattern in step. Applies only where detection "
             "finds that shape (61 of 95 corpus files) and is a no-op for "
             "the rest. Off by default: it changes the output bytes of the "
             "files it reaches")
    parser.add_argument(
        "--reject-phantoms", action="store_true",
        help="validate the inferred pattern table: an entry whose decode "
             "runs off the file, or whose bytes overlap the pointer tables "
             "or signature-matched player code, is provably not pattern "
             "data (the hi-lo-1 entry count over-counts) and is replaced "
             "by a one-rest placeholder instead of being decoded as music. "
             "Off by default: it changes the output bytes of the files it "
             "reaches")
    parser.add_argument(
        "--skip-gate", action="store_true",
        help="derive the row length from the counter ABOVE the speed gate as "
             "well as the gate itself. Most Hubbard players decrement the "
             "speed gate only on some frames -- a second counter jumps past "
             "it, or returns from the play call outright -- so a row lasts "
             "(reload + 1) x (O + 1) / O frames rather than reload + 1. "
             "Applied only where that comes out a whole number, which is all "
             "Goattracker can express. It fixes the timing (Tarzan 0.67 -> "
             "1.00 against the original, melody 73%% -> 96%%). It also moves "
             "the -S multiplier, so anything packing the result must pack it "
             "at the new one. On by default via presets.json")
    parser.add_argument(
        "--fold-transpose", action="store_true",
        help="recover the orderlist transposes that do not fit Goattracker's "
             "+14 ceiling. Hubbard's players carry transposes of 24, 36 and "
             "48 semitones; the ceiling exists because $FF is LOOPSONG, so "
             "those steps were clamped and played up to 34 semitones flat. "
             "This keeps the remainder in the orderlist and folds the whole "
             "octaves into a copy of each pattern the step plays, which costs "
             "one pattern-table entry per distinct (pattern, octaves) pair. A "
             "step whose notes have no room to rise is left clamped rather "
             "than partly folded. Off by default: it changes the output bytes "
             "of the 17 corpus files it reaches")
    parser.add_argument(
        "--initial-instrument", action="store_true",
        help="give each voice the instrument the player starts it on. Hubbard "
             "keeps a per-voice instrument index and writes it only when a "
             "pattern carries an instrument byte, so a voice whose first note "
             "arrives before any pattern names one sounds the index array's "
             "loaded value. Goattracker instead starts every channel on "
             "instrument 1, which this writer emits as an empty record, so "
             "those voices came out silent -- Delta Mix-E-Load loses two of "
             "its three. Costs one pattern-table entry per distinct "
             "(pattern, instrument) pair. Off by default: it changes the "
             "output bytes of the 9 corpus files it reaches")
    parser.add_argument(
        "--sustain-exact", action="store_true",
        help="read the instrument's sustain nibble as the SID does. The VB6 "
             "original masked bit $10 out of any sustain/release byte >= $F0, "
             "on the belief that the field was three bits of sustain plus one "
             "spare (h2g.frm:578-579); SID register 6 is four bits of sustain "
             "and four of release, so the mask lowered a full sustain of F to "
             "E on every instrument that asked for one -- the level the note "
             "holds at for its whole length. Off by default: it changes the "
             "output bytes of the 64 corpus files it reaches, including the "
             "Commando fixture")
    parser.add_argument(
        "--no-hard-restart", action="store_true",
        help="stop Goattracker resetting the envelope before every note. "
             "Goattracker writes its hard-restart value (default $0F00) into "
             "$D405/$D406 for one frame ahead of each note unless the "
             "instrument sets gatetimer bit $80; Hubbard's players never do "
             "this, and $0F00 occurs in no corpus original while being the "
             "most common ADSR value in every conversion without the flag. "
             "Off by default: it changes the output bytes of every file, and "
             "costs Confuzion 4 points of melody similarity -- hard restart "
             "exists to make notes retrigger reliably")
    parser.add_argument(
        "--pitch-seq", action="store_true",
        help="emit the effect byte's bit-$10 arpeggio: a three-step semitone "
             "sequence the player steps with a GLOBAL phase counter (34 corpus "
             "files). Off by default and not searched per song, because the "
             "phase is the problem: a wavetable restarts at every note and the "
             "player's counter does not, so which step a note begins on cannot "
             "be reproduced. Over 26 files it takes the median vib ratio 0.22x "
             "-> 0.58x and costs 5 points of mean melody, 7 files losing. Worth "
             "trying per song by ear -- Trans-Atlantic goes 0.17x -> 0.61x with "
             "melody unchanged"),
    parser.add_argument(
        "--tie", action="store_true",
        help="honour the classic players' tie flag: status bit 5 tells the "
             "player not to close the gate at that note's end, so the note "
             "that follows arrives with the gate open and only changes "
             "frequency -- no attack. Emitted as CMD_TONEPORTA with parameter "
             "0 on the landing row, which gplay.c makes an instant pitch jump "
             "(:811) while skipping both the hard-restart gate-off (:930) and "
             "the firstwave testbit (:355). 64 classic files carry tied "
             "events; median retrigger ratio 1.008 -> 0.999 and mean melody "
             "82.3%% -> 84.1%%, with Delta_Mix-E-Load_loader going 6%% -> 100%%"),
    parser.add_argument(
        "--cut-release", action="store_true",
        help="drop the release nibble on players that kill the envelope when a "
             "note ends (33 corpus files). Those players gate off and write 0 "
             "to both $D405 and $D406 for any untied note, so the record's "
             "release never sounds -- but copying it into a Goattracker "
             "instrument makes it audible, and Goattracker gates off on the "
             "same frame, so the note rings through a gap that should be "
             "silence. Commando's lead carries $5F and turns a staccato figure "
             "legato. Measured over 30 files the `tail` column goes 27.6%% to "
             "99.2%%, better on 27 and worse on none, with melody unchanged")
    parser.add_argument(
        "--vibrato-command", action="store_true",
        help="express the global-triangle player's vibrato as a per-note "
             "pattern command instead of an instrument setting (25 corpus "
             "files, --format gts5, needs --vibrato). That player gates "
             "vibrato on the note's own duration -- `AND #$1F / CMP #$08`, no "
             "vibrato below 8 -- which a Goattracker instrument cannot say, "
             "because vibdelay is per instrument. gplay.c keeps the vibdelay "
             "countdown inside `case CMD_DONOTHING`, so a row carrying "
             "CMD_VIBRATO oscillates from the note's first call; zeroing the "
             "instrument's speed-table pointer then silences the notes that "
             "carry no command. Without it, vibdelay 8 stands in for the gate "
             "and starts every long note 10 frames late")
    parser.add_argument(
        "--wave-program", action="store_true",
        help="run the player's per-instrument byte-code wave program. 29 corpus "
             "files carry an interpreter with three opcodes -- $85 holds, a byte "
             ">= $80 sets a waveform and an absolute frequency, a byte < $80 "
             "sets a waveform and subtracts a 16-bit pitch step. It is what "
             "carries Trans-Atlantic's snare (`81 30`: noise at $30xx, 43 "
             "notes). Needs --format gts5. The player advances an opcode per "
             "frame where a wavetable advances an entry per call, so each "
             "opcode takes a hold entry and the program runs at the player's "
             "rate at every -S; until v0.5.235 this refused a multiplier above "
             "1 outright and so emitted nothing for seven of the nine files the "
             "onset census wanted it for. Off by default; presets.py "
             "--fidelity selects it per song")
    parser.add_argument(
        "--sfx-drum", action="store_true",
        help="write the fixed-pitch noise hit the effect byte's bit $80 fires. "
             "Seven corpus files carry it and it was left unconverted while it "
             "was believed to be the game's own sound effect; it is gated on "
             "the playing instrument's own +7 and fires on the beat "
             "(detect._find_sfx_drum). Needs --format gts5. Off by default "
             "until measured; presets.py --fidelity selects it per song")
    parser.add_argument(
        "--two-stage", action="store_true",
        help="write the attack waveform this player's effect bit $04 selects. "
             "In 44 corpus files bit $04 is not an arpeggio but a second "
             "waveform held for a per-instrument number of frames before the "
             "record's own +2 (detect._find_two_stage). Detection has read it "
             "since v0.5.66 and the writer ignored it, so those files played "
             "the second stage from frame one -- and a record whose +2 is $00 "
             "was silent altogether. Off by default: measured over the corpus "
             "it costs 0.6 points of mean wave agreement, and it is right only "
             "where the original sounds noise the conversion has none of. "
             "presets.py --fidelity selects it per song")
    parser.add_argument(
        "--voice-two-stage", action="store_true",
        help="write the attack waveform effect bit $02 selects where that "
             "player keeps its parameters per VOICE. One corpus file (Ninja) "
             "reads bit $02 as a two-stage attack whose waveform and duration "
             "come from two static three-byte tables indexed by the voice "
             "being serviced, not by the instrument "
             "(detect._find_voice_two_stage). A Goattracker wavetable is per "
             "instrument, so this is emitted only for an instrument the "
             "orderlists play on exactly one voice (tracks.instrument_voices); "
             "an instrument shared between voices is left alone. Needs "
             "--effects. Off by default; presets.py --fidelity selects it per "
             "song")
    parser.add_argument(
        "--rest-keyoff", action="store_true",
        help="end a note where the player's own rest ends it. A status byte "
             "with bit 6 set is a rest in the 61 files with the BIT/BVS "
             "shape, and in 21 of them the branch it takes *silences* the "
             "voice -- the testbit written into the stored waveform (IK+ "
             "$E138) or the envelope pair zeroed (Ricochet $914A). This "
             "writer emitted a hold row for it, which sustains the note the "
             "original cut: IK+'s $08D8 plays its wave program for 6 or 12 "
             "frames of an 18-frame slot and rests for the rest. Emits "
             "Goattracker's KEYOFF instead, gated on "
             "detect._find_rest_silences so the 40 players that really do "
             "hold are untouched")
    parser.add_argument(
        "--no-test-restart", action="store_true",
        help="stop silencing the oscillator on every note's first frame. Each "
             "instrument's first-frame waveform has always been $09 -- testbit "
             "plus gate -- and the testbit holds the phase accumulator and the "
             "noise LFSR at zero, so that frame produces no sound. Hubbard's "
             "players spend 4273 such frames across 12 of 83 corpus files; "
             "conversions spend 9179 across 79. This writes $FF instead, which "
             "gplay.c:355-363 reads as a gate value rather than a waveform: the "
             "note still attacks and the frame keeps the waveform already "
             "there. Off by default because it changes the output bytes of "
             "every file, including the Commando fixture")
    parser.add_argument(
        "--pulse", action="store_true",
        help="write the player's pulse-width sweep instead of a frozen duty "
             "cycle. Hubbard's players step a 12-bit pulse accumulator every "
             "frame and turn it around at two bounds held in one byte, which "
             "is the movement under a lead sound; H2G wrote the starting "
             "width and stopped, so 414 records across 43 corpus files played "
             "a static timbre under otherwise correct notes. No metric in the "
             "repo can see it -- `wave` compares the waveform class, and "
             "pulse is pulse whatever its width. Off by default: it changes "
             "the output bytes of the 43 corpus files it reaches")
    parser.add_argument(
        "--presets", metavar="FILE",
        help="JSON file of per-song options (see presets.py). The entry "
             "matching this .sid's filename supplies --max-rows, "
             "--pack-repeats, --prune-patterns and --dedup-patterns; options "
             "given explicitly on the command line still win. A song with no "
             "entry converts at the defaults")
    args = parser.parse_args(argv)

    if args.presets:
        import json
        try:
            doc = json.loads(open(args.presets, encoding="utf-8").read())
        except OSError as exc:
            parser.error(f"--presets: {exc}")
        except ValueError as exc:
            parser.error(f"--presets is not valid JSON: {exc}")
        # `always` carries the settings that are right for every song rather
        # than searched per song -- gts5 because Goattracker's legacy GTS2
        # importer overruns on the commands this converter emits, and a tempo
        # because an untempo'd file plays at the wrong speed. Applying them is
        # what makes a preset reproduce the size it records.
        always = doc.get("always", {})
        # Argparse also accepts a flag and its value as one `--flag=value`
        # token, so plain set membership on argv would miss an explicit
        # `--format=gts5` and let the preset silently override it.
        tokens = argv if argv is not None else sys.argv[1:]

        def _given(flag: str) -> bool:
            return any(a == flag or a.startswith(flag + "=") for a in tokens)

        if not _given("--format") and always.get("format") in FORMATS:
            args.format = always["format"]
        if not _given("--tempo") and always.get("tempo") is not None:
            args.tempo = always["tempo"]
        if not _given("--legal-restart") and always.get("legal_restart"):
            args.legal_restart = True
        entry = doc.get("songs", {}).get(os.path.basename(args.sid_file)) or {}
        for flag, key in (("--slides", "slides"), ("--vibrato", "vibrato"),
                          ("--effects", "effects"),
                          ("--status-bit6", "status_bit6"),
                          ("--rest-instrument", "rest_instrument"),
                          ("--compact-instruments", "compact_instruments"),
                          ("--reject-phantoms", "reject_phantoms"),
                          ("--skip-gate", "skip_gate"),
                          ("--fold-transpose", "fold_transpose"),
                          ("--initial-instrument", "initial_instrument"),
                          ("--sustain-exact", "sustain_exact"),
                          ("--no-hard-restart", "no_hard_restart"),
                          ("--no-test-restart", "no_test_restart"),
                          ("--rest-keyoff", "rest_keyoff"),
                          ("--two-stage", "two_stage"),
                          ("--voice-two-stage", "voice_two_stage"),
                          ("--sfx-drum", "sfx_drum"),
                          ("--wave-program", "wave_program"),
                          ("--vibrato-command", "vibrato_command"),
                          ("--cut-release", "cut_release"),
                          ("--tie", "tie"),
                          ("--pitch-seq", "pitch_seq"),
                          ("--filter", "filters"),
                          ("--pulse", "pulse")):
            if _given(flag):
                continue
            # A song entry beats `always`, which is what lets an option that is
            # right for a few files and wrong corpus-wide be recorded per song
            # (presets.py --fidelity). Without this the key would be read by
            # nothing -- the shape in which --slides and --filter shipped dead.
            if key in entry:
                setattr(args, key, bool(entry[key]))
            elif always.get(key):
                setattr(args, key, True)
        if entry:
            # Only fill in what the user did not ask for, so an explicit flag
            # always beats the stored preset.
            if not _given("--max-rows"):
                args.max_rows = entry.get("max_rows", args.max_rows)
            for flag, key in (("--pack-repeats", "pack"),
                              ("--prune-patterns", "prune"),
                              ("--dedup-patterns", "dedup")):
                if not _given(flag):
                    setattr(args, flag[2:].replace("-", "_"), bool(entry.get(key)))
            if not args.quiet:
                print(f"presets: {args.presets} -> max-rows {args.max_rows}, "
                      f"pack={args.pack_repeats}, prune={args.prune_patterns}, "
                      f"dedup={args.dedup_patterns}", file=sys.stderr)

    tempo = args.tempo
    if tempo is not None and tempo != "auto":
        try:
            tempo = int(tempo)
        except ValueError:
            parser.error("--tempo must be an integer or 'auto'")
        if not GT_MIN_TEMPO <= tempo <= 0x7F:
            parser.error(f"--tempo must be {GT_MIN_TEMPO}..127 or 'auto' "
                         "(Goattracker reads 0 and 1 as funktempo, and masks "
                         "the value with $7F -- gplay.c:494 -- so higher "
                         "values cannot mean a faster tempo)")

    if not 1 <= args.max_rows <= GT_MAX_ROWS:
        parser.error(f"--max-rows must be between 1 and {GT_MAX_ROWS}")

    log = (lambda msg: None) if args.quiet else (lambda msg: print(msg, file=sys.stderr))

    try:
        sng = convert(args.sid_file, log=log, max_rows=args.max_rows,
                      terminate_patterns=args.terminate_patterns,
                      fmt=args.format, tempo=tempo,
                      dedup=args.dedup_patterns,
                      prune=args.prune_patterns,
                      pack=args.pack_repeats,
                      legal_restart=args.legal_restart,
                      slides=args.slides, vibrato=args.vibrato,
                      effects=args.effects,
                      status_bit6=args.status_bit6,
                      rest_instrument=args.rest_instrument,
                      compact_instruments=args.compact_instruments,
                      reject_phantoms=args.reject_phantoms,
                      fold_transpose=args.fold_transpose,
                      initial_instrument=args.initial_instrument,
                      sustain_exact=args.sustain_exact,
                      no_hard_restart=args.no_hard_restart,
                      no_test_restart=args.no_test_restart,
                      rest_keyoff=args.rest_keyoff,
                      two_stage=args.two_stage,
                      voice_two_stage=args.voice_two_stage,
                      sfx_drum=args.sfx_drum,
                      wave_program=args.wave_program,
                      vibrato_command=args.vibrato_command,
                      cut_release=args.cut_release,
                      tie=args.tie,
                      pitch_seq=args.pitch_seq,
                      filters=args.filters,
                      pulse=args.pulse)
    except (SidFormatError, UnsupportedSidError, ConversionAbort) as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 1

    out_path = args.output or _default_output(args.sid_file)
    with open(out_path, "wb") as f:
        f.write(sng)

    print(f"Wrote {out_path} ({len(sng)} bytes)", file=sys.stderr)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
