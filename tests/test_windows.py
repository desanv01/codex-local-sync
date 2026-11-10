"""Process safety checks with fabricated tasklist output only."""

from types import SimpleNamespace
import hashlib
import json
import unittest
from unittest.mock import patch

from codex_local_sync import windows
from codex_local_sync.errors import BusyError, ValidationError
from tests.support import SyntheticHome


class ProcessDetectionTests(unittest.TestCase):
    def enumerate(self, output, returncode=0):
        with patch.object(windows, "_require_windows"), \
             patch.object(windows.subprocess, "CREATE_NO_WINDOW", 0, create=True), \
             patch.object(windows.subprocess, "run", return_value=SimpleNamespace(
                 stdout=output, returncode=returncode)):
            return windows.app_running()

    def test_desktop_blocks_and_unrelated_process_does_not(self):
        self.assertTrue(self.enumerate('"ChatGPT.exe","123","Console","1","9 K"'))
        self.assertTrue(self.enumerate('"CODEX-APP.EXE","123","Console","1","9 K"'))
        self.assertTrue(self.enumerate('"CODEX DESKTOP.EXE","123","Console","1","9 K"'))
        self.assertFalse(self.enumerate('"example.exe","123","Console","1","9 K"'))

    def test_uncertain_enumeration_fails_closed(self):
        for output, code in [("", 0), ("unparseable", 0), ("", 1)]:
            with self.subTest(output=output, code=code), self.assertRaises(BusyError):
                self.enumerate(output, code)

    def test_codex_backend_requires_positive_inspection_and_uncertainty_blocks(self):
        tasklist = SimpleNamespace(stdout='"codex.exe","123","Console","1","9 K"', returncode=0)
        for payload, code, outcome in [
                ({"running": False, "uncertain": False}, 0, False),
                ({"running": True, "uncertain": False}, 0, True),
                ({"running": False, "uncertain": True}, 0, None),
                ({"running": False, "uncertain": False}, 1, None),
                ([], 0, None), ({"running": "false", "uncertain": False}, 0, None)]:
            with self.subTest(payload=payload, code=code), \
                 patch.object(windows, "_require_windows"), \
                 patch.object(windows.subprocess, "CREATE_NO_WINDOW", 0, create=True), \
                 patch.object(windows.subprocess, "run", side_effect=[tasklist,
                     SimpleNamespace(stdout=json.dumps(payload), returncode=code)]):
                if outcome is None:
                    with self.assertRaises(BusyError):
                        windows.app_running()
                else:
                    self.assertIs(outcome, windows.app_running())


class StartupOwnershipTests(SyntheticHome):
    """Read-only ownership/preflight checks on ordinary synthetic text files."""

    def test_malformed_or_tampered_receipt_refuses_and_preserves_files(self):
        self.data.mkdir()
        entry = self.root / "synthetic-entry.txt"
        entry.write_bytes(b"synthetic owned content")
        receipt = {"schema_version": 1, "path": str(entry),
                   "sha256": hashlib.sha256(entry.read_bytes()).hexdigest()}
        for value in ([], {**receipt, "sha256": "wrong"}, {**receipt, "path": "wrong"}):
            with self.subTest(receipt=value):
                (self.data / "startup.json").write_text(json.dumps(value), encoding="utf-8")
                before = self.files()
                with self.assertRaises(ValidationError):
                    windows._owned_startup(self.data, entry)
                self.assertEqual(before, self.files())
        (self.data / "startup.json").write_text(json.dumps(receipt), encoding="utf-8")
        before = self.files()
        windows._owned_startup(self.data, entry)
        self.assertEqual(before, self.files())

    def test_preflight_detects_other_helper_without_writing(self):
        directory = self.root / "synthetic-entries"
        directory.mkdir()
        (directory / "codex-old-sync.txt").write_text("unrelated synthetic entry", encoding="utf-8")
        before = self.files()
        with patch.object(windows, "_startup_path", return_value=directory / "selected.txt"), \
             patch.object(windows, "legacy_watcher_running", return_value=False):
            with self.assertRaises(BusyError):
                windows.check_startup(self.data, self.home)
        self.assertEqual(before, self.files())
