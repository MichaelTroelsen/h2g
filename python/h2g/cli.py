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
        help="write a startup tempo (calls per pattern row) into the last "
             "instrument. 'auto' derives it from the PSID speed field. "
             "Omitted by default, which leaves Goattracker's startup "
             "default of 6 calls/row -- 6x too slow, since this converter "
             "emits one row per player tick. With a tempo written, play at "
             "Goattracker speed multiplier 2 for correct timing")
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
    args = parser.parse_args(argv)

    tempo = args.tempo
    if tempo is not None and tempo != "auto":
        try:
            tempo = int(tempo)
        except ValueError:
            parser.error("--tempo must be an integer or 'auto'")
        if not GT_MIN_TEMPO <= tempo <= 255:
            parser.error(f"--tempo must be {GT_MIN_TEMPO}..255 or 'auto' "
                         "(Goattracker reads 0 and 1 as funktempo)")

    if not 1 <= args.max_rows <= GT_MAX_ROWS:
        parser.error(f"--max-rows must be between 1 and {GT_MAX_ROWS}")

    log = (lambda msg: None) if args.quiet else (lambda msg: print(msg, file=sys.stderr))

    try:
        sng = convert(args.sid_file, log=log, max_rows=args.max_rows,
                      terminate_patterns=args.terminate_patterns,
                      fmt=args.format, tempo=tempo,
                      dedup=args.dedup_patterns,
                      prune=args.prune_patterns)
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
