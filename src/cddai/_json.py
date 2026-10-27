"""Compatibility alias for ``aced._json``; retain one set of runtime types."""

import sys
from importlib import import_module

from aced._json import *  # noqa: F403

sys.modules[__name__] = import_module("aced._json")
