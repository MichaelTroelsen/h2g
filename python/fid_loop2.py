"""fidelity.py with every ticked arpeggio shape disabled -- the "disabled" side
of an osplit A/B (osplit-corpus-vice-sweep).

    python fid_loop2.py <target> [fidelity options] [--allow-noop]

Disabling `ticked_arp_entries` alone stopped being a disable: a nibble-dialect
ticked record is shaped by `ticked_nibble_arp_entries`, which is tried first.
Measured at d52a1bf (v0.5.495) under presets.json: Spellbound, Proteus,
Formula_1_Simulator, International_Karate, Thrust and Warhawk convert
byte-identically with only `ticked_arp_entries` off (the 1dde44a sweep saw the
first four react to it), so a "disabled" column taken that way is the shipped
column again.

So this wrapper does not trust its own patch list. Before handing over to
fidelity.main it converts every target with and without the patch and refuses
(exit 2) where the patch moved no byte: a named .sid that does not move, or a
directory in which nothing moves. The next shape added beside these two then
fails here instead of reading as "osplit 0 disabled". `--allow-noop` reports
and proceeds.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import sys
from contextlib import contextmanager
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))

from h2g import goatwriter  # noqa: E402
import fidelity  # noqa: E402

# Every emitter returning a ticked arp shape. A shape added beside them must
# be named here; `noop_report` is what notices when it is not.
DISABLED = ("ticked_arp_entries", "ticked_nibble_arp_entries")


def _declined(*_a, **_k):
    return None


@contextmanager
def disabled(names=None):
    names = DISABLED if names is None else names
    saved = {n: getattr(goatwriter, n) for n in names}
    try:
        for n in names:
            setattr(goatwriter, n, _declined)
        yield
    finally:
        for n, f in saved.items():
            setattr(goatwriter, n, f)


def _sha(sid: Path, doc: dict) -> str:
    sng = fidelity.convert(str(sid), log=lambda m: None,
                           **fidelity._preset_opts(doc, sid.name))
    return hashlib.sha256(sng).hexdigest()


def moved(sid: Path, doc: dict, names=None) -> bool:
    """True if converting `sid` under its presets changes with `names` off."""
    shipped = _sha(sid, doc)
    with disabled(names):
        return _sha(sid, doc) != shipped


def noop_report(target: Path, doc: dict, names=None) -> tuple[list, list]:
    """(moved, unmoved) file names; a file that does not convert is unmoved."""
    sids = ([target] if target.is_file()
            else sorted(target.rglob("*.sid"), key=lambda q: q.name.lower()))
    yes, no = [], []
    for sid in sids:
        try:
            (yes if moved(sid, doc, names) else no).append(sid.name)
        except Exception:  # noqa: BLE001 -- refused either way; fidelity reports it
            no.append(sid.name)
    return yes, no


class _Parsed(Exception):
    pass


def _fidelity_args(argv: list):
    """fidelity.main's own namespace for `argv`, taken from its parser and
    abandoned before anything runs (main does nothing ahead of parse_args)."""
    orig = argparse.ArgumentParser.parse_args

    def grab(self, *a, **k):
        raise _Parsed(orig(self, *a, **k))
    argparse.ArgumentParser.parse_args = grab
    try:
        fidelity.main(argv)
    except _Parsed as got:
        return got.args[0]
    finally:
        argparse.ArgumentParser.parse_args = orig
    raise RuntimeError("fidelity.main returned without parsing its arguments")


def main(argv=None) -> int:
    argv = list(sys.argv[1:] if argv is None else argv)
    allow = "--allow-noop" in argv
    argv = [a for a in argv if a != "--allow-noop"]
    args = _fidelity_args(argv)
    if args.target and not args.pair and not args.ticks:
        target = Path(args.target)
        presets = (Path(args.presets) if args.presets is not None
                   else HERE.parent / "presets.json")
        doc = json.loads(presets.read_text(encoding="utf-8"))
        yes, no = noop_report(target, doc)
        print(f"fid_loop2: disabling {', '.join(DISABLED)} moves "
              f"{len(yes)} of {len(yes) + len(no)} file(s): "
              f"{', '.join(yes) or '-'}", file=sys.stderr)
        stale = no if target.is_file() else ([] if yes else no)
        if stale and not allow:
            print(f"fid_loop2: REFUSED -- the disable is a no-op on "
                  f"{', '.join(stale)}; its ticked records reach a shape not "
                  f"in DISABLED (or it has none). --allow-noop to proceed.",
                  file=sys.stderr)
            return 2
    return _run(argv)


def _run(argv: list) -> int:
    with disabled():
        return fidelity.main(argv)


if __name__ == "__main__":
    sys.exit(main())
