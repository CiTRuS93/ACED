"""Compatibility alias for ``aced.cursor``; retain one set of runtime types."""

import sys
from importlib import import_module

from aced.cursor import *  # noqa: F403

sys.modules[__name__] = import_module("aced.cursor")
