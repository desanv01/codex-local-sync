<h1 align="center">codex-local-sync</h1>

<p align="center">
  <a href="https://github.com/desanv01/codex-local-sync/actions/workflows/ci.yml"><img src="https://github.com/desanv01/codex-local-sync/actions/workflows/ci.yml/badge.svg?branch=main" alt="Windows Python 3.11 and 3.13 checks" /></a>
  <strong>Switch accounts. Keep local organization in step.</strong><br />
  Preview changes, preserve recovery backups and synchronize two selected profiles after Codex closes.
</p>

<p align="center">Windows-first local utility · By Desan Vasu · Independent community beta</p>

<p align="center">
  <img src="https://img.shields.io/badge/Python-3.11%2B-087c79" alt="Python 3.11 or newer" />
  <img src="https://img.shields.io/badge/Live_sync-Windows-087c79" alt="Live sync on Windows" />
  <img src="https://img.shields.io/badge/Status-beta-orange" alt="Beta status" />
  <a href="LICENSE"><img src="https://img.shields.io/badge/License-MIT-087c79" alt="MIT license" /></a>
</p>

<p align="center">
  <a href="#get-started">Get started</a> · <a href="#scope">Scope</a> ·
  <a href="#commands">Commands</a> · <a href="docs/recovery.md">Recovery</a> ·
  <a href="docs/compatibility.md">Compatibility</a> · <a href="CONTRIBUTING.md">Contributing</a>
</p>

## Why this exists

Switching accounts can expose different saved project organization on the same computer. This utility reconciles supported local organization fields between two explicitly selected profile snapshots. It is an independent community utility, with no OpenAI affiliation or endorsement.

The beta works against an observed local settings schema. It does not establish how widespread an account-switching issue is or which desktop release introduced it. Local synthetic checks do not establish compatibility with every desktop build; see the [compatibility record](docs/compatibility.md).

## Scope

| Area | Beta behavior |
| --- | --- |
| Profiles | Exactly two existing profiles, selected explicitly |
| Projects | Supported local registrations, names, folder references and ordering |
| Chat organization | Supported local project assignments, pins and ordering, conservatively classified |
| Messages and files | No transcript, database or project-file copying |
| Account data | Credentials, identity, permissions, remote and cloud data remain scoped |
| Apply timing | Windows only; desktop processes must be closed |
| Conflicts | Pause for review; competing edits are not silently resolved |
| Removals | Off by default; explicit setup opt-in is required |
| Recovery | Backups, a transaction journal and checked restore |

Selecting two profiles intentionally shares supported local organization between them. Review that choice before connecting personal and employer profiles. Local backups can contain private settings; keep them private.

## Get started

Download the [beta release](https://github.com/desanv01/codex-local-sync/releases/tag/v0.1.0-beta.1) source ZIP or clone this repository. Release assets include a wheel, source distribution, source ZIP and SHA-256 checksums.

Requires **Python 3.11+**. From a reviewed source checkout or extracted source release, open PowerShell in its directory:

```powershell
py -3 -m venv .venv
.\.venv\Scripts\python.exe -m pip install .
.\.venv\Scripts\codex-local-sync.exe doctor
```

Open each intended account in Codex at least once so both profile snapshots exist. Then configure and inspect the result:

```powershell
.\.venv\Scripts\codex-local-sync.exe setup
.\.venv\Scripts\codex-local-sync.exe preview
```

Setup asks for exactly two profiles and a seed profile. The seed resolves initial competing values; independent additions can still be combined. Later competing edits pause synchronization. Setup writes helper configuration; preview is read-only.

Fully quit Codex, including remaining desktop processes. Apply once, then reopen Codex and inspect the organization:

```powershell
.\.venv\Scripts\codex-local-sync.exe sync
.\.venv\Scripts\codex-local-sync.exe status
```

Automatic backup and transaction preparation precede changes. Keep the first preview and restart deliberate. After verifying the result, optionally start the background helper:

```powershell
.\.venv\Scripts\codex-local-sync.exe start
# Optional: also register this helper for the current Windows user's login.
.\.venv\Scripts\codex-local-sync.exe start --startup
```

For everyday switching, switch accounts, fully quit the desktop app, check `status` for completion, then reopen. A fixed wait is not a substitute for checking status. The watcher waits for stable state after closure; it never forces Codex to close.

Read the [installation guide](docs/installation.md) for explicit paths, configuration and lifecycle details.

## Commands

| Command | Purpose |
| --- | --- |
| `doctor` | Inspect compatibility and environment without writing helper or app state |
| `setup` | Select two profiles, seed and optional aliases; save helper configuration |
| `preview` | Inspect proposed changes and conflicts without writing state |
| `sync` | Apply one sync while the desktop app is closed |
| `start` | Launch a Windows background watcher; `--startup` opts into login startup |
| `watch` | Run the watcher in the foreground |
| `status` | Inspect helper liveness, progress and reported errors |
| `stop` | Request a graceful watcher stop |
| `backup` | Create a recovery backup while the desktop app is closed |
| `restore BACKUP --yes` | Restore a selected backup after validation |
| `uninstall --yes` | Stop the helper and remove its owned startup entry; preserve data |

Global options: `--codex-home PATH`, `--data-dir PATH`, `--json`. Use `--help` on any command for its full interface. `preview --details` can reveal identifiers and paths; inspect it locally before sharing.

`--codex-home` takes precedence over `CODEX_HOME`, then the default `~/.codex`. Helper data defaults to a per-user directory outside the checkout (`%LOCALAPPDATA%\codex-local-sync` on Windows). Use explicit paths consistently for every command when managing a custom target.

## How it works

The schema adapter reads selected profile snapshots from `.codex-global-state.json`. A merge engine compares each profile with its previous baseline, prepares a canonical local view and identifies conflicts. Storage applies a validated plan under a target-specific cross-process lock shared with backup, restore and watcher operations. The watcher can observe account changes while Codex is open, then apply only after the desktop closes and settings settle.

Settings, their fallback backup and the helper journal form a recoverable transaction. Pending transaction intent is checked before ordinary mutation; changed inputs or an uncertain desktop-process check stop the operation. See [architecture](docs/architecture.md) and [recovery](docs/recovery.md).

## Limits and status

This is a **0.1.0b1 beta**. Unknown schemas, incomplete snapshots and unresolved conflicts stop synchronization. It cannot recover missing message content, guarantee desktop sidebar visibility, or prevent every race with a rapidly reopening app. Synthetic cross-platform workflows are supported; real writes and Windows startup require the Windows adapter.

No telemetry or network synchronization is part of the runtime. Local configuration, journals and full-state backups can still contain private identifiers and paths. Do not upload them to issues. See [security](SECURITY.md) and [troubleshooting](docs/troubleshooting.md).

## Development

```powershell
py -3 -m pip install -e .
py -3 -m unittest discover -s tests
py -3 scripts/build_release.py
```

Use synthetic homes inside the checkout for development. Never run development lifecycle commands against your installed helper or live settings. See [contribution rules](CONTRIBUTING.md), [release preparation](docs/release.md) and the [changelog](CHANGELOG.md).

## License

[MIT](LICENSE) · Copyright © 2026 Desan Vasu.
