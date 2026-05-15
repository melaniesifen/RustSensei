from __future__ import annotations

import shutil
import sys
import tempfile
from pathlib import Path


class EnvironmentProbe:
    def __init__(self, state_dir: Path) -> None:
        self._state_dir = state_dir

    def python_version(self) -> tuple[int, int, int]:
        return sys.version_info.major, sys.version_info.minor, sys.version_info.micro

    def cargo_path(self) -> str | None:
        return shutil.which("cargo")

    def rustc_path(self) -> str | None:
        return shutil.which("rustc")

    def state_dir_writable(self) -> bool:
        try:
            self._state_dir.mkdir(parents=True, exist_ok=True)
            with tempfile.NamedTemporaryFile(dir=self._state_dir, delete=True):
                return True
        except OSError:
            return False
