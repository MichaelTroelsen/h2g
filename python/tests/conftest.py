"""Suite-wide fixtures. Only one so far: renders shared between xdist workers.

`sound.render_cached` writes its WAV straight to the cache path
(`build/audio/<tag>.<key>.s<sub>.t<sec>.wav`), with no temp-and-rename. Run
serially that is safe; under `pytest -n N` two workers that need the same
original render the same file at once, and the second can read the first's
half-written WAV as a cache hit. Every worker therefore takes one lock file in
the cache directory around each `render_cached` call. The function itself runs
unchanged, so a cache hit, a miss and a failed render behave exactly as they
do serially; the lock only orders them. A serial run (no PYTEST_XDIST_WORKER)
is not touched at all.
"""
import os
import pathlib
import sys
import time

import pytest

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[1]))

# A render takes seconds; a lock held this long belongs to a worker that died.
STALE_LOCK_S = 600


class _CacheLock:
    def __init__(self, cache: pathlib.Path):
        self.path = pathlib.Path(cache) / ".render.lock"

    def __enter__(self):
        self.path.parent.mkdir(parents=True, exist_ok=True)
        while True:
            try:
                fd = os.open(self.path, os.O_CREAT | os.O_EXCL | os.O_WRONLY)
                os.write(fd, os.environ.get("PYTEST_XDIST_WORKER", "").encode())
                os.close(fd)
                return self
            except FileExistsError:
                try:
                    if time.time() - self.path.stat().st_mtime > STALE_LOCK_S:
                        self.path.unlink(missing_ok=True)
                        continue
                except FileNotFoundError:
                    continue
                time.sleep(0.05)

    def __exit__(self, *exc):
        self.path.unlink(missing_ok=True)


@pytest.fixture(autouse=True, scope="session")
def _serialise_shared_renders():
    if not os.environ.get("PYTEST_XDIST_WORKER"):
        yield
        return
    import sound
    real = sound.render_cached
    default_cache = sound.AUDIO_DIR

    def locked(sid, seconds, subtune, tag, cache=default_cache, *rest, **kw):
        with _CacheLock(cache):
            return real(sid, seconds, subtune, tag, cache, *rest, **kw)

    locked.__wrapped__ = real
    sound.render_cached = locked
    try:
        yield
    finally:
        sound.render_cached = real
