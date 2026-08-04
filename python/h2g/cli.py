from __future__ import annotations

import argparse
import os
import sys

from . import __version__
from .convert import UnsupportedSidError, convert
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
    args = parser.parse_args(argv)

    if not 1 <= args.max_rows <= GT_MAX_ROWS:
        parser.error(f"--max-rows must be between 1 and {GT_MAX_ROWS}")

    log = (lambda msg: None) if args.quiet else (lambda msg: print(msg, file=sys.stderr))

    try:
        sng = convert(args.sid_file, log=log, max_rows=args.max_rows,
                      terminate_patterns=args.terminate_patterns)
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
