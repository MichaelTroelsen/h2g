import os, pathlib, subprocess, sys, json
HOOK = pathlib.Path(__file__).resolve().parent / "bold_parity_gate.py"
TOOL = HOOK.parents[2] / "python/tools/bold_parity.py"

def test_tool_writes_utf8_on_cp1252_pipe(tmp_path):
    f = tmp_path / "a.md"
    f.write_text("odd **bold \u2192 \u03c0 \u4e2d\n", encoding="utf-8")
    env = dict(os.environ, PYTHONIOENCODING="cp1252", PYTHONUTF8="0")
    r = subprocess.run([sys.executable, str(TOOL), str(f)], capture_output=True, env=env)
    assert r.returncode == 1, r.stderr
    assert "\u2192".encode("utf-8") in r.stdout or b"\u2192" in r.stdout

def test_hook_logs_bad_input_to_stderr():
    r = subprocess.run([sys.executable, str(HOOK)], input="not json",
                       capture_output=True, text=True)
    assert r.returncode == 0 and "BOLD PARITY" in r.stderr
