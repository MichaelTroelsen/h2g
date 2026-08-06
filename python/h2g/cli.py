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
        "--effects", action="store_true",
        help="decode the two bits of the instrument effect byte (+7) that the "
             "original mis-read. Bit $02 raises the note a semitone every four "
             "frames for as long as it is held (252 instrument records across "
             "59 corpus files); it was ignored entirely, and is written here as "
             "a note-relative portamento in the wavetable, which needs "
             "--format gts5. Bit $04's arpeggio with a zero interval nibble is "
             "silent in the player, but the original substituted an octave-up "
             "arpeggio for it -- half of every arpeggio instrument in the "
             "corpus. Off by default: it changes the output bytes")
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
        for flag, key in (("--slides", "slides"), ("--effects", "effects"),
                          ("--status-bit6", "status_bit6"),
                          ("--reject-phantoms", "reject_phantoms"),
                          ("--fold-transpose", "fold_transpose")):
            if not _given(flag) and always.get(key):
                setattr(args, key, True)
        entry = doc.get("songs", {}).get(os.path.basename(args.sid_file))
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
                      slides=args.slides,
                      effects=args.effects,
                      status_bit6=args.status_bit6,
                      reject_phantoms=args.reject_phantoms,
                      fold_transpose=args.fold_transpose)
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
