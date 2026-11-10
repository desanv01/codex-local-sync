"""Transactions against synthetic JSON files, with process checks injected."""

from pathlib import Path
import json
import os
import subprocess
import sys
from unittest.mock import patch

from codex_local_sync import storage
from codex_local_sync.errors import BusyError, SyncError
from tests.support import ROOT, SyntheticHome
from tests.fixtures import A, B, P, config, state
from codex_local_sync.state import apply_views, snapshot_profiles


class StorageTests(SyntheticHome):
    def setUp(self):
        super().setUp()
        self.settings = self.write_state(state())
        self.config = config()

    def test_preview_does_not_create_data_dir_or_change_files(self):
        before = self.files()
        plan = storage.preview_sync(self.home, self.data, config=self.config)
        self.assertTrue(plan["changed"])
        self.assertEqual(before, self.files())
        self.assertFalse(self.data.exists())

    def test_app_alive_and_closing_race_reject_settings_write(self):
        before = self.settings.read_bytes()
        with self.assertRaises(BusyError):
            storage.sync_once(self.home, self.data, config=self.config,
                              is_app_running=lambda: True)
        self.assertEqual(before, self.settings.read_bytes())
        checks = iter([False, True])
        with self.assertRaises(BusyError):
            storage.sync_once(self.home, self.data, config=self.config,
                              is_app_running=lambda: next(checks, True))
        self.assertEqual(before, self.settings.read_bytes())

    def test_sync_backup_restore_preserves_raw_backup_and_safe_fallback(self):
        storage.save_config(self.data, self.config)
        original = self.settings.read_bytes()
        bak = self.home / ".codex-global-state.json.bak"
        bak.write_bytes(b"synthetic previous raw backup\n")
        backup = storage.create_backup(self.home, self.data, is_app_running=lambda: False)
        self.assertEqual(original, (backup / "state.json").read_bytes())
        self.assertEqual(b"synthetic previous raw backup\n", (backup / "state.bak").read_bytes())
        result = storage.sync_once(self.home, self.data, config=self.config,
                                   is_app_running=lambda: False)
        self.assertTrue(result["changed"])
        self.assertNotEqual(original, self.settings.read_bytes())
        self.assertEqual(self.settings.read_bytes(), bak.read_bytes())
        bak.write_bytes(b"synthetic later backup\n")
        storage.restore_backup(self.home, self.data, backup, is_app_running=lambda: False)
        self.assertEqual(original, self.settings.read_bytes())
        self.assertEqual(original, bak.read_bytes())

    def test_partial_state_commit_recovers_before_next_sync(self):
        self.recover_after_failure(self.home / ".codex-global-state.json.bak")

    def test_partial_fallback_commit_recovers_before_next_sync(self):
        self.recover_after_failure(self.data / "journal.json")

    def recover_after_failure(self, failure_path):
        planned = storage.preview_sync(self.home, self.data, config=self.config)
        atomic_write = storage._atomic_write
        interrupted = False

        def fail_journal_once(path, data):
            nonlocal interrupted
            if Path(path) == failure_path and not interrupted:
                interrupted = True
                raise OSError("synthetic crash between transaction replacements")
            return atomic_write(path, data)

        with patch.object(storage, "_atomic_write", side_effect=fail_journal_once):
            with self.assertRaises((OSError, SyncError)):
                storage.sync_once(self.home, self.data, config=self.config,
                                  is_app_running=lambda: False)
        self.assertTrue(interrupted)
        before = self.files()
        with self.assertRaises(BusyError):
            storage.preview_sync(self.home, self.data, config=self.config)
        self.assertEqual(before, self.files())
        recovered = storage.sync_once(self.home, self.data, config=self.config,
                                      is_app_running=lambda: False)
        self.assertTrue(recovered["recovered"])
        self.assertEqual(planned["state"], storage.read_state(self.home))
        self.assertEqual(self.settings.read_bytes(),
                         (self.home / ".codex-global-state.json.bak").read_bytes())
        self.assertIsNotNone(storage.read_journal(self.data))
        # A recovered transaction must be stable on the following operation.
        before = self.settings.read_bytes()
        result = storage.sync_once(self.home, self.data, config=self.config,
                                   is_app_running=lambda: False)
        self.assertFalse(result["changed"])
        self.assertEqual(before, self.settings.read_bytes())

    def test_existing_journal_preview_and_conflicted_sync_do_not_write(self):
        storage.sync_once(self.home, self.data, config=self.config, is_app_running=lambda: False)
        before = self.files()
        storage.preview_sync(self.home, self.data, config=self.config)
        self.assertEqual(before, self.files())
        current = storage.read_state(self.home)
        views = snapshot_profiles(current, [A, B])
        views[A]["projects"][P]["name"] = "Left edit"
        views[B]["projects"][P]["name"] = "Right edit"
        self.write_state(apply_views(current, views))
        before = self.files()
        result = storage.sync_once(self.home, self.data, config=self.config,
                                   is_app_running=lambda: False)
        self.assertTrue(result["conflicts"])
        self.assertEqual(before, self.files())

    def test_chronological_capture_does_not_replay_stale_other_snapshot(self):
        storage.sync_once(self.home, self.data, config=self.config, is_app_running=lambda: False)
        for profile, name in ((A, "First observed edit"), (B, "Later observed edit")):
            current = storage.read_state(self.home)
            views = snapshot_profiles(current, [A, B])
            views[profile]["projects"][P]["name"] = name
            self.write_state(apply_views(current, views))
            raw = self.settings.read_bytes()
            result = storage.observe_once(self.home, self.data, config=self.config)
            self.assertFalse(result["conflicts"])
            self.assertEqual(raw, self.settings.read_bytes())
        result = storage.sync_once(self.home, self.data, config=self.config,
                                   is_app_running=lambda: False)
        self.assertFalse(result["conflicts"])
        for view in snapshot_profiles(storage.read_state(self.home), [A, B]).values():
            self.assertEqual("Later observed edit", view["projects"][P]["name"])

    def test_common_lock_rejects_other_process_even_with_other_data_dir(self):
        code = (
            "from pathlib import Path; from codex_local_sync.storage import target_lock; "
            "from codex_local_sync.errors import BusyError; import sys\n"
            "try:\n"
            "    with target_lock(Path(sys.argv[1]), Path(sys.argv[2])): pass\n"
            "except BusyError: sys.exit(23)\n"
        )
        env = dict(os.environ, PYTHONPATH=str(ROOT / "src"))
        before = self.settings.read_bytes()
        with storage.target_lock(self.home, self.data):
            child = subprocess.run([sys.executable, "-c", code, str(self.home),
                                    str(self.root / "other-helper-data")], env=env,
                                   capture_output=True, text=True, timeout=15)
        self.assertEqual(23, child.returncode, child.stderr)
        self.assertEqual(before, self.settings.read_bytes())

    def test_codex_home_explicit_override_precedes_environment(self):
        self.assertEqual(self.home.resolve(), storage.resolve_codex_home())
        explicit = self.root / "explicit-codex-home"
        self.assertEqual(explicit.resolve(), storage.resolve_codex_home(str(explicit)))

    def test_unchanged_source_cannot_bypass_corrupt_journal_guards(self):
        storage.sync_once(self.home, self.data, config=self.config, is_app_running=lambda: False)
        valid = storage.read_journal(self.data)
        for replacement in ({"schema_version": 99}, {"seen": 42}):
            with self.subTest(replacement=replacement):
                invalid = {**valid, **replacement}
                (self.data / "journal.json").write_text(json.dumps(invalid), encoding="utf-8")
                before = self.files()
                with self.assertRaises(SyncError):
                    storage.observe_once(self.home, self.data, config=self.config)
                self.assertEqual(before, self.files())

    def test_observation_rejects_snapshot_replaced_after_watcher_quiet_period(self):
        storage.sync_once(self.home, self.data, config=self.config, is_app_running=lambda: False)
        before = self.files()
        operations = (
            lambda: storage.observe_once(self.home, self.data, config=self.config,
                                         expected_fingerprint="0" * 64),
            lambda: storage.sync_once(self.home, self.data, config=self.config,
                                      is_app_running=lambda: False, expected_fingerprint="0" * 64),
        )
        for operation in operations:
            with self.assertRaises(BusyError):
                operation()
            self.assertEqual(before, self.files())
