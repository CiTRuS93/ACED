"""Compatibility alias for ``aced._cli_output``; retain one set of runtime types."""

import sys
from importlib import import_module

from aced._cli_output import *  # noqa: F403

sys.modules[__name__] = import_module("aced._cli_output")
