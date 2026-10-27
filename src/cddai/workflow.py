"""Compatibility alias for ``aced.workflow``; retain one set of runtime types."""

import sys
from importlib import import_module

from aced.workflow import *  # noqa: F403

sys.modules[__name__] = import_module("aced.workflow")
