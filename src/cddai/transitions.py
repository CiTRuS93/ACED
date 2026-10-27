"""Compatibility alias for ``aced.transitions``; retain one set of runtime types."""

import sys
from importlib import import_module

from aced.transitions import *  # noqa: F403

sys.modules[__name__] = import_module("aced.transitions")
