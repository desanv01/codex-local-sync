# Security and privacy

codex-local-sync is an independent local utility. It handles organization metadata and backs up full local settings. Those backups may include account-scoped data even though the merge leaves that data scoped. Treat configuration, journals and backups as private files.

## Reporting a vulnerability

Do not attach real settings, logs, profile IDs, paths, tokens, databases or chat content to a public issue. Use GitHub's private vulnerability reporting feature on the project repository if the maintainer has enabled it. If no private channel is available, open a minimal issue asking for one without disclosing the vulnerability or private data. No response-time or support guarantee is offered for this beta.

For ordinary bugs, provide versions, the command, a short sanitized error category and a synthetic reproduction. Review `--json` output before sharing; machine-readable does not mean anonymous. `preview --details` is intended for local inspection.

## Boundaries

- Runtime performs local file/process operations and has no telemetry or network sync.
- Two profiles are explicitly selected. Identity, credentials, cloud/remote data and permission settings are outside the merge scope.
- Desktop process checks and target-specific locks reduce concurrent-write risk. A different program need not honor the helper's lock, and a rapid desktop restart remains a race limitation.
- Unknown schemas, incomplete snapshots and unresolved conflicts pause synchronization.
- Startup is opt-in, current-user and ownership-checked. Uninstall preserves private recovery data.

Keep backups on storage you trust, with access limited to your user account. Apply your own retention policy after verifying recovery. The helper is not an access-control boundary between people who already have access to the same Windows user account.
