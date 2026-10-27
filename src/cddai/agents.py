"""Compatibility alias for ``aced.agents``; retain one set of runtime types."""

import sys
from importlib import import_module

from aced.agents import *  # noqa: F403

sys.modules[__name__] = import_module("aced.agents")
