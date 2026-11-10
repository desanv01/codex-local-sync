"""Synthetic-only helpers. Temporary homes always stay under this checkout."""

from __future__ import annotations

import json
import os
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch


ROOT = Path(__file__).resolve().parents[1]


class SyntheticHome(unittest.TestCase):
    def setUp(self):
        scratch = ROOT / "work" / "tests"
        scratch.mkdir(parents=True, exist_ok=True)
        self.temporary = tempfile.TemporaryDirectory(prefix="case-", dir=scratch)
        self.addCleanup(self.temporary.cleanup)
        self.root = Path(self.temporary.name)
        self.home = self.root / "codex-home"
        self.home.mkdir()
        self.data = self.root / "helper-data"
        # A missed explicit override must still never resolve to a real home.
        self.environment = patch.dict(os.environ, {
            "CODEX_HOME": str(self.home),
            "HOME": str(self.root),
            "USERPROFILE": str(self.root),
            "LOCALAPPDATA": str(self.root / "local-app-data"),
            "APPDATA": str(self.root / "app-data"),
        })
        self.environment.start()
        self.addCleanup(self.environment.stop)

    def write_state(self, state):
        path = self.home / ".codex-global-state.json"
        path.write_text(json.dumps(state), encoding="utf-8")
        return path

    def files(self):
        return {
            path.relative_to(self.root).as_posix(): path.read_bytes()
            for path in self.root.rglob("*") if path.is_file()
        }
