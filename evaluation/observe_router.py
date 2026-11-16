"""Run the real router with local metadata instrumentation, never inference."""

import json
import os
from pathlib import Path
import subprocess
import sys
import time
from unittest.mock import patch

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
from claude_task_router import cli  # noqa: E402


def main():
    destination, *args = sys.argv[1:]
    original_classify = cli.classify
    original_spawn = subprocess.Popen
    counts = dict(classifications=0, classification_seconds=0.0, native_seconds=0.0)

    def classify(*args, **kwargs):
        start = time.monotonic()
        try:
            return original_classify(*args, **kwargs)
        finally:
            counts["classifications"] += 1
            counts["classification_seconds"] += time.monotonic() - start

    class ObservedChild(original_spawn):
        def __init__(self, *args, **kwargs):
            self.began = time.monotonic()
            self.measured = False
            super().__init__(*args, **kwargs)

        def wait(self, *args, **kwargs):
            result = super().wait(*args, **kwargs)
            if not self.measured:
                counts["native_seconds"] += time.monotonic() - self.began
                self.measured = True
            return result

    start = time.monotonic()
    try:
        with patch.object(cli, "classify", classify), patch.object(subprocess, "Popen", ObservedChild):
            return cli.main(args)
    finally:
        end = time.monotonic()
        # cli.main supervises one native child through exit. This includes
        # native hook time; local overhead excludes that child process.
        counts["router_seconds"] = max(0, end - start - counts["native_seconds"])
        fd = os.open(destination, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
        with os.fdopen(fd, "w") as stream:
            json.dump(counts, stream)


if __name__ == "__main__":
    raise SystemExit(main())
