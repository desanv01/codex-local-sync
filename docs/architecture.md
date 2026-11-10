# Architecture and merge behavior

## Components

| Module | Responsibility |
| --- | --- |
| `state.py` | Validate the observed schema, discover profiles, normalize supported local fields and apply views while preserving unrelated data |
| `engine.py` | Pure merge planning, baseline comparisons, conflict and removal decisions |
| `storage.py` | Home resolution, target lock, backups, journal and recoverable settings transactions |
| `windows.py` | Conservative desktop-process detection and owned Windows startup/background adapter |
| `cli.py` | Configuration, inspection, commands and watcher lifecycle |

The settings target is `.codex-global-state.json` in the resolved Codex home. SQLite databases, authentication files, transcripts and project files are not merge targets. Profile discovery requires recognizable complete account snapshots; it does not create a missing profile.

## Merge policy

Setup selects exactly two profile IDs and a seed. Bootstrap combines supported additions and uses the explicitly selected seed for initial competing values. Subsequent plans compare each snapshot against its stored baseline. Independent changes can merge; competing edits pause the operation and require review.

Removals default off. Explicit opt-in enables deletion tracking, but validation and snapshot guards still apply. Empty or incomplete snapshots are not accepted as automatic mass deletions. Dependent references must remain consistent: a removed project cannot leave a dangling project assignment or order reference. Conservative normalization may unassign an affected chat rather than remove message content.

Local classification requires sufficient metadata. Unknown, remote or cloud entries do not become local merely because host information is absent. Account identity, credentials and permissions remain scoped, and unknown/unscoped fields are preserved rather than reconstructed from a narrow export.

The beta's project allowlist covers `id`, `name`, `rootPaths`, `createdAt` and `updatedAt`; assignments use `projectKind` and `projectId`, and thread orders use `threadIds`. Recognized flat sidebar preferences are `mode`, `chatSortMode`, `projectSortMode` and `initialized`. Project appearance data remains account-scoped because its raw schema has not been established. Unknown fields stay local.

## Mutation boundary

Preview is a plan only. A mutating operation acquires the lock for its settings target, checks desktop-process state and source fingerprints, validates inputs and prepares backups plus transaction intent. Settings and helper journal changes can then be recovered after interruption. A stale or conflicting input fails the operation instead of replaying an old plan.

The watcher shares this storage boundary with one-time sync, backup and restore. Observations while the desktop is open inform the journal; application waits for closure and stable input. The process adapter does not close Codex or grant a bypass for uncertain state.

The lock only coordinates cooperating utility processes. Desktop processes and other tools do not honor it. Process checks reduce risk but cannot eliminate the interval in which the app could reopen between a check and file replacement. Keep Codex closed until the operation reports completion.
