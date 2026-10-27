"""Compatibility alias for ``aced.manager.contracts``; retain one set of runtime types."""

import sys
from importlib import import_module

from aced.manager.contracts import *  # noqa: F403

sys.modules[__name__] = import_module("aced.manager.contracts")
