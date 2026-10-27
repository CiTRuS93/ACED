"""Compatibility entry point for Codex recorder jobs launched by earlier previews."""

import sys
from pathlib import Path

from aced._cli_job import record as record

if __name__ == "__main__":
    record(Path(sys.argv[1]))
