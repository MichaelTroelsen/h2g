"""Importing h2g.tracks first must not hit the tracks -> patterns -> goatwriter -> patterns cycle.

Each module is imported in a fresh interpreter, so import order is the only variable.
"""
from __future__ import annotations

import subprocess
import sys
from pathlib import Path

import pytest

PYTHON_DIR = Path(__file__).resolve().parents[1]


@pytest.mark.parametrize("module", ["h2g.tracks", "h2g.patterns", "h2g.goatwriter.counter_fall", "h2g.convert"])
def test_module_imports_in_fresh_interpreter(module: str) -> None:
    proc = subprocess.run(
        [sys.executable, "-c", f"import {module}"],
        cwd=PYTHON_DIR, capture_output=True, text=True, timeout=120,
    )
    assert proc.returncode == 0, proc.stderr
