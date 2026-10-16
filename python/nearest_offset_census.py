"""Nearest-original-tick census of voice-3 noise ticks (constants.py legato-tie note).

usage (from python/): python nearest_offset_census.py [NAME.sid] [CORPUS_DIR]
Two arms under presets, sub 0, 60 s: `base` (legato_tie_family patched False,
the old tie spelling) and `tree` (as is). Reports ticks per arm, those common
to both, and how many of the common ticks sit N frames from the nearest
original tick, unshifted and at the best global shift.
"""
import json, sys, warnings
from collections import Counter
from pathlib import Path
warnings.simplefilter("ignore")
HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
import fidelity as F
from h2g.goatwriter import note_passes as NP
from h2g.convert import convert

NAME = sys.argv[1] if len(sys.argv) > 1 else "Auf_Wiedersehen_Monty.sid"
CORPUS = Path(sys.argv[2] if len(sys.argv) > 2 else
              r"C:/Users/mit/claude/c64server/SIDM2/SID/Hubbard_Rob")
EXE = str(HERE / "tools/siddump-rt/siddump.exe")
NF = 3000
doc = json.loads((HERE.parent / "presets.json").read_text())
opts = F._preset_opts(doc, NAME)
mult = F._preset_multiplier(doc, NAME)
SCRATCH = Path(r"C:/t/constants-nearest-offset-census-rederive")


def noise(tr):
    wf = F.register_timeline(tr[2].wf_events, NF)
    return sorted(f for f in range(NF) if wf[f] & 0x80)


def arm(label, work):
    # Patch the DEFINING module: build.py and note_passes.py call it through
    # note_passes, so a rebinding on the goatwriter package reaches neither.
    real = NP.legato_tie_family
    if label == "base":
        NP.legato_tie_family = lambda sid, det: False
    try:
        lines = []
        sng = convert(str(CORPUS / NAME), log=lines.append, **opts)
    finally:
        NP.legato_tie_family = real
    work.mkdir(parents=True, exist_ok=True)
    sid = F.pack_sid(sng, work, F.GT2RELOC, mult)
    assert sid, "pack refused"
    return noise(F.run_siddump(Path(sid), 60, 0, EXE, 0, calls=mult)), lines


def nearest(f, orig):
    return min(abs(f - o) for o in orig)


def main():
    orig = noise(F.run_siddump(CORPUS / NAME, 60, 0, EXE, 0, calls=1))
    base, _ = arm("base", SCRATCH / "work_base")
    tree, lines = arm("tree", SCRATCH / "work_tree")
    print(f"{NAME} mult {mult}; legato log: {[l for l in lines if 'egato' in l]}")
    print(f"orig {len(orig)} base {len(base)} tree {len(tree)} "
          f"common {len(set(base) & set(tree))} "
          f"exact(base) {len(set(orig) & set(base))} exact(tree) {len(set(orig) & set(tree))}")
    common = sorted(set(base) & set(tree))
    so = set(orig)
    best = max(range(-12, 13), key=lambda L: len(so & {f + L for f in common}))
    for lab, shift in (("unshifted", 0), (f"best shift {best:+d}", best)):
        h = Counter(nearest(f + shift, orig) for f in common)
        print(f"common ticks, nearest-original distance, {lab}: "
              f"{dict(sorted(h.items()))}; 4-6 frames: {sum(h[d] for d in (4, 5, 6))}")
    for lab, arr in (("base", base), ("tree", tree)):
        h = Counter(nearest(f + best, orig) for f in arr)
        print(f"{lab} all ticks at shift {best:+d}: {dict(sorted(h.items()))}; "
              f"4-6: {sum(h[d] for d in (4, 5, 6))}")


main()
