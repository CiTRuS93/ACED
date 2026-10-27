"""Compatibility alias for ``aced.runtime``; retain one set of runtime types."""

import sys
from importlib import import_module

from aced.runtime import *  # noqa: F403

sys.modules[__name__] = import_module("aced.runtime")
