"""Compatibility alias for ``aced._codex_job``; retain one set of runtime types."""

import sys
from importlib import import_module

from aced._codex_job import *  # noqa: F403

if __name__ == "__main__":
    from pathlib import Path

    from aced._cli_job import record

    record(Path(sys.argv[1]))
else:
    sys.modules[__name__] = import_module("aced._codex_job")
