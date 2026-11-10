# Backup and recovery

Keep Codex fully closed during backup, restore and sync. Keep full-state backups private: they can contain unrelated account settings as well as organization metadata.

## Before a change

`sync` prepares automatic backup data before applying settings changes. For a separate recovery point, use `codex-local-sync backup` and retain the returned backup-directory path privately. Backup operations participate in the same target lock as synchronization and restore.

## Restore a selected backup

1. Run `stop` for the relevant configuration and confirm watcher shutdown with `status`.
2. Fully quit Codex and check that no desktop process remains.
3. Identify the intended backup from your private helper data; do not assume the newest backup is the right baseline.
4. Run `codex-local-sync restore "PATH_TO_SELECTED_BACKUP" --yes`, passing the same `--codex-home` and `--data-dir` used for setup.
5. Inspect the result, reopen Codex and verify organization before restarting background sync.

`PATH_TO_SELECTED_BACKUP` is a placeholder for the backup directory containing its manifest, not an individual settings file. Restore validates the selected backup, uses the common lock and refuses an active/uncertain desktop process state. It restores local settings, not missing transcripts, cloud records or project files. The helper reconstructs a journal baseline for the restored snapshot so historical pending observations are not replayed over it.

Sync and restore make the desktop's fallback `.bak` consistent with the desired main settings. The original fallback bytes remain in the safety backup; restore does not reactivate an older fallback beside newer main settings.

## Interrupted transactions

Settings, the fallback `.bak` and the helper journal may be interrupted between replacements. Transaction intent and recovery copies allow the next sync or restore to reconcile partial work. Preview and backup can instead report that recovery is required. Do not edit or delete a pending transaction or substitute a different journal; that can destroy the evidence needed for recovery.

If recovery refuses to proceed, leave the files intact, stop the watcher and keep Codex closed. Retain a private copy of the helper data and target settings before any manual investigation. Use a synthetic reproduction in a public report; do not upload the affected recovery directory.

## Conflicts and unexpected empty profiles

A paused conflict or snapshot guard is not a successful sync. Review the reported categories and selected profiles. Reopen the intended account to establish a complete snapshot if needed, then close the app and inspect a fresh preview. Do not reset the helper journal merely to silence a conflict: it is the baseline that distinguishes new edits from stale values.

There is no blanket force flag for unknown schemas, active desktop processes or unresolved conflicts. Escalate a schema/merge problem with sanitized diagnostics and a synthetic fixture.
