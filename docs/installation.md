# Installation and everyday use

The beta requires Python 3.11+ and Windows for live synchronization and watcher startup. macOS/Linux can exercise the pure merge engine and synthetic inspection flows. No administrator account is required for current-user startup.

## Install from reviewed source

Download and extract a reviewed source archive, or use a reviewed checkout. If a release includes `SHA256SUMS`, compare its archive digest before extraction:

```powershell
Get-FileHash .\codex-local-sync-0.1.0b1-source.zip -Algorithm SHA256
```

The checksum detects accidental changes; it is not a signature proving publisher identity. Install into a stable directory because background startup refers to the installed Python environment:

```powershell
py -3 -m venv .venv
.\.venv\Scripts\python.exe -m pip install .
.\.venv\Scripts\codex-local-sync.exe doctor
```

Package build tooling may download dependencies during installation. The installed utility's runtime uses Python's standard library and performs no network sync.

## Select profiles

Open both intended accounts in Codex at least once. Run `setup` interactively to select exactly two discovered profiles and an initial seed. Review the displayed aliases and counts locally. You can also configure explicitly, replacing the synthetic IDs below with discovered IDs:

```powershell
codex-local-sync setup --profiles profile-alpha profile-beta --seed profile-alpha --alias profile-alpha=Main --alias profile-beta=Secondary --yes
codex-local-sync preview
```

The names above are synthetic examples. `--yes` acknowledges the selected configuration; it does not bypass compatibility, process or conflict checks. `--allow-removals` is a separate setup option. Leave it off until you understand the merge and recovery workflow. Never treat a missing or incomplete snapshot as consent to erase organization.

For a custom target, pass both explicit paths consistently:

```powershell
codex-local-sync --codex-home "D:\Example Codex Home" --data-dir "D:\Example Sync Data" doctor
codex-local-sync --codex-home "D:\Example Codex Home" --data-dir "D:\Example Sync Data" setup
codex-local-sync --codex-home "D:\Example Codex Home" --data-dir "D:\Example Sync Data" preview
```

`--codex-home` overrides `CODEX_HOME`, which overrides the default `~/.codex`. A separate helper data directory is required for independent configurations. The normal Windows data directory is `%LOCALAPPDATA%\codex-local-sync`; it is outside the source checkout.

## First application

Review `preview`, fully quit Codex and run `sync`. Check `status`, reopen Codex and verify the selected local projects and organization. Do not delete old backups during initial verification. A blocked preview or sync needs investigation; repeatedly running it does not resolve a conflict.

## Background operation

`start` launches a background watcher. `start --startup` also opts into login startup for the current Windows user. `watch --interval 1` runs in the foreground. Background observation tracks supported account changes while Codex is open; settings writes wait for closure and a stable observation window of at least three seconds.

Startup integration supports Unicode paths but rejects percent signs and control characters in paths because Windows Script Host can expand environment references. Choose a stable installation and data path without those characters. Startup ownership and coexistence are checked before launch. Only one watcher may own a Codex home at a time, even when another data directory is selected.

Use `status` to distinguish process liveness, pending work and errors. After switching accounts, fully quit, wait for successful sync status and reopen. `stop --timeout 10` requests graceful shutdown; it does not terminate arbitrary processes.

## Updating and removing

Stop the watcher before updating the same environment. Retain helper data and backups, install the reviewed new package, run `doctor` and `preview`, and restart only after inspection. If the installation path changes, recreate owned startup integration using the new environment.

`uninstall --yes` stops the helper and removes its owned startup entry. It preserves configuration, journals and backups. Remove the Python environment separately only after shutdown, and remove retained private data manually only when recovery is no longer needed. This utility must not overwrite an unrelated older helper's startup entry; stop and resolve that ownership conflict deliberately.
