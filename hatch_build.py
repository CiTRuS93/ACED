"""Build manager assets from pinned frontend sources unless already built locally."""

import subprocess
from pathlib import Path

from hatchling.builders.hooks.plugin.interface import BuildHookInterface


class CustomBuildHook(BuildHookInterface):
    def initialize(self, version, build_data):
        if self.target_name != "wheel" or version == "editable":
            return
        root = Path(self.root)
        if not (root / "src/aced/manager/static/index.html").is_file():
            subprocess.run(["npm", "ci"], cwd=root / "frontend", check=True)
            subprocess.run(["npm", "run", "build"], cwd=root / "frontend", check=True)
        build_data["force_include"][str(root / "src/aced/manager/static")] = "aced/manager/static"
