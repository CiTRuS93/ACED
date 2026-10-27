"""Compatibility alias for ``aced.manager.app``; retain one set of runtime types."""

import sys
from importlib import import_module

from aced.manager.app import *  # noqa: F403

sys.modules[__name__] = import_module("aced.manager.app")
