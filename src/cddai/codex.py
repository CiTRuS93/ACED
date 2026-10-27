"""Compatibility alias for ``aced.codex``; retain one set of runtime types."""

import sys
from importlib import import_module

from aced.codex import *  # noqa: F403

sys.modules[__name__] = import_module("aced.codex")
