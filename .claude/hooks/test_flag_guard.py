"""Exercise flag_guard.py from a data file.

The cases cannot live on a Bash command line: the hook inspects command lines,
so a test that puts `python survey.py ...` there triggers the very guard it is
testing. This runs them through the hook's stdin instead, which is how the hook
is actually invoked.
"""
import json
import pathlib
import subprocess
import sys

HOOK = str(pathlib.Path(__file__).with_name("flag_guard.py"))

# (expected_exit, command)
CASES = [
    # MENTIONS -- the false positive that shipped. Must pass.
    (0, 'grep -c skip python/fidelity.py && grep -o find CLAUDE.md'),
    (0, 'ls -la python/survey.py python/fidelity.py'),
    (0, 'git log --oneline -- python/fidelity.py'),
    (0, 'cat python/survey.py | head -20'),
    (0, 'sed -n "1,5p" python/sound_calibrate.py'),
    # INVOCATIONS missing a load-bearing flag. Must block.
    (2, 'python survey.py /c -o ../docs/SURVEY.md'),
    (2, 'python survey.py /c -o ../docs/SURVEY.md --legal-restart'),
    (2, 'python survey.py /c -o ../docs/SURVEY.md --gt2reloc'),
    (2, 'python sound_calibrate.py'),
    (2, 'cd python && python sound_calibrate.py'),
    (2, 'python fidelity.py /c -t 180 --json ../build/fidelity.json'),
    (2, 'python fidelity.py /c -o ../docs/FIDELITY.md'),
    # CORRECT invocations. Must pass.
    (0, 'python survey.py /c -o ../docs/SURVEY.md --legal-restart --gt2reloc'),
    (0, 'python sound_calibrate.py /corpus'),
    (0, 'python fidelity.py /c --json b.json --sound'),
    (0, 'python fidelity.py x.sid --pace'),
    (0, 'python fidelity.py --help'),
    (0, 'python fidelity_queue.py --from-json ../build/fidelity.json -o x.md'),
    # a generator invoked correctly BESIDE an unrelated -o
    (0, 'python survey.py /c -o s.md --legal-restart --gt2reloc && grep -o x y'),
]

bad = 0
for want, cmd in CASES:
    p = subprocess.run([sys.executable, HOOK],
                       input=json.dumps({"tool_name": "Bash",
                                         "tool_input": {"command": cmd}}),
                       capture_output=True, text=True)
    ok = p.returncode == want
    bad += not ok
    print("  %s want=%d got=%d  %s"
          % ("ok  " if ok else "FAIL", want, p.returncode, cmd[:62]))
print("\n%d case(s), %d failure(s)" % (len(CASES), bad))
sys.exit(1 if bad else 0)
