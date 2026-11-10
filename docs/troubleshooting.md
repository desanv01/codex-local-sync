# Troubleshooting

Run commands with the same `--codex-home` and `--data-dir` used for setup. Start with `doctor`, `status` and a read-only `preview`. Default output limits identifiers and paths; inspect any report before sharing it.

| Symptom | Next action |
| --- | --- |
| Only one profile discovered | Open each intended account at least once; confirm the selected Codex home and complete snapshots |
| Unsupported schema | Stop writes; record helper/app versions and a sanitized error category; reproduce with synthetic data |
| Desktop still running | Fully quit all desktop processes; the helper will not force them closed |
| Cannot establish process state | Resolve Windows process inspection failure; do not bypass it |
| Conflicting edits | Inspect preview locally and reconcile the intended organization; avoid deleting the journal |
| Empty or incomplete snapshot guard | Let the intended account establish complete state, then close and preview again |
| Lock busy | Check helper status and allow the current operation to finish; do not delete locks during active work |
| Pending recovery | Keep recovery files intact; follow [recovery](recovery.md) |
| Watcher exited or status reports error | Inspect the error category, resolve it, then start again; liveness alone is not sync success |
| Startup ownership conflict | Preserve the existing entry and resolve which installed helper should run |
| Projects exist but sidebar differs | This utility handles supported organization fields; it cannot guarantee app rendering or recover message content |

For an issue, include helper/Python/Windows/app versions, command name, error category and a synthetic reproduction. Never post real IDs, `preview --details`, full settings, journals, backups, transcripts or databases. See [SECURITY.md](../SECURITY.md) for sensitive reports.
