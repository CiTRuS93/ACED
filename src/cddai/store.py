"""Compatibility alias for ``aced.store``; retain one set of runtime types."""

import sys
from importlib import import_module

from aced.store import *  # noqa: F403

sys.modules[__name__] = import_module("aced.store")
