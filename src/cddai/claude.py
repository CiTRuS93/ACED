"""Compatibility alias for ``aced.claude``; retain one set of runtime types."""

import sys
from importlib import import_module

from aced.claude import *  # noqa: F403

sys.modules[__name__] = import_module("aced.claude")
