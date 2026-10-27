"""Compatibility alias for ``aced.manager.demo``; retain one set of runtime types."""

import sys
from importlib import import_module

from aced.manager.demo import *  # noqa: F403

if __name__ == "__main__":
    from aced.manager.demo import main

    main()
else:
    sys.modules[__name__] = import_module("aced.manager.demo")
