"""In-process CLI flow with fabricated state and process adapter stubs."""

from contextlib import redirect_stderr, redirect_stdout
import io
import json
import os
import subprocess
import sys
from unittest.mock import patch

from codex_local_sync import cli
from tests.fixtures import A, B, state
from tests.support import ROOT, SyntheticHome


class CliTests(SyntheticHome):
    def setUp(self):
        super().setUp()
        self.settings = self.write_state(state())

    def invoke(self, *arguments):
        out, err = io.StringIO(), io.StringIO()
        with redirect_stdout(out), redirect_stderr(err), \
             patch.object(cli.windows, "app_running", return_value=False), \
             patch.object(cli.windows, "legacy_watcher_running", return_value=False):
            code = cli.main(["--codex-home", str(self.home), "--data-dir", str(self.data),
                             "--json", *arguments])
        return code, out.getvalue(), err.getvalue()

    def setup_pair(self):
        code, out, err = self.invoke("setup", "--profiles", A, B, "--seed", A, "--yes")
        self.assertEqual(0, code, err)
        self.assertFalse(json.loads(out)["settings_written"])

    def test_synthetic_setup_preview_sync_backup_restore(self):
        original = self.settings.read_bytes()
        self.setup_pair()
        self.assertEqual(original, self.settings.read_bytes())
        before = self.files()
        code, out, err = self.invoke("preview")
        self.assertEqual(0, code, err)
        self.assertTrue(json.loads(out)["changed"])
        self.assertEqual(before, self.files())
        for private in (A, B, "C:/synthetic", str(self.home)):
            self.assertNotIn(private, out)
        code, out, err = self.invoke("backup")
        self.assertEqual(0, code, err)
        backup = json.loads(out)["backup"]
        code, out, err = self.invoke("sync")
        self.assertEqual(0, code, err)
        self.assertTrue(json.loads(out)["changed"])
        self.assertNotEqual(original, self.settings.read_bytes())
        code, out, err = self.invoke("restore", backup, "--yes")
        self.assertEqual(0, code, err)
        self.assertTrue(json.loads(out)["restored"])
        self.assertEqual(original, self.settings.read_bytes())

    def test_doctor_and_status_are_read_only(self):
        before = self.files()
        for command in ("doctor", "status"):
            code, out, err = self.invoke(command)
            self.assertEqual(0, code, err)
            self.assertIsInstance(json.loads(out), dict)
        self.assertEqual(before, self.files())
        self.assertFalse(self.data.exists())

    def test_setup_requires_explicit_seed_and_restore_requires_confirmation(self):
        before = self.files()
        with patch.object(cli.sys.stdin, "isatty", return_value=False):
            code, _, err = self.invoke("setup", "--profiles", A, B, "--yes")
        self.assertEqual(1, code)
        self.assertIn("seed", err)
        self.assertEqual(before, self.files())
        self.setup_pair()
        before = self.files()
        with patch.object(cli.sys.stdin, "isatty", return_value=False):
            code, _, err = self.invoke("restore", str(self.root / "unselected-backup"))
        self.assertEqual(1, code)
        self.assertIn("confirmation", err)
        self.assertEqual(before, self.files())

    def test_watcher_lifetime_target_lock_blocks_other_data_directory(self):
        code = (
            "from pathlib import Path; from codex_local_sync.cli import _lifecycle_lock; "
            "from codex_local_sync.errors import BusyError; import sys\n"
            "try:\n"
            "    with _lifecycle_lock(Path(sys.argv[2])), "
            "_lifecycle_lock(Path(sys.argv[1]), '.codex-local-sync-watcher.lock'): pass\n"
            "except BusyError: sys.exit(23)\n"
        )
        env = dict(os.environ, PYTHONPATH=str(ROOT / "src"))
        with cli._lifecycle_lock(self.home, ".codex-local-sync-watcher.lock"):
            child = subprocess.run([sys.executable, "-c", code, str(self.home),
                                    str(self.root / "other-helper-data")], env=env,
                                   capture_output=True, text=True, timeout=15)
        self.assertEqual(23, child.returncode, child.stderr)
