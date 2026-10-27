"""Compatibility alias for ``aced.opencode``; retain one set of runtime types."""

import sys
from importlib import import_module

from aced.opencode import *  # noqa: F403

sys.modules[__name__] = import_module("aced.opencode")
