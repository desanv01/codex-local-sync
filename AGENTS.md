# codex-local-sync

Build a Windows-first, MIT-licensed local Codex organization sync utility.

## Authority and safety

The human requests a main coordinator and one persistent GPT-6.1 Sol medium
worker chat per phase. Workers may communicate with Main and each other using
supported chat tools. Main handles Git integration and publication.

Work only within this repository. The installed personal helper and live Codex
settings are external production data. Never install, start a real watcher,
modify startup entries, or write to actual Codex settings during development.
Use synthetic temporary homes under this repository for all verification.
Never copy real profile identifiers, histories, snapshots, paths, or app bundle
code into tracked files. The prior authored helper may be read for reference.

## Execution order

Complete all implementation before running the single focused testing/fixes
wave. Workers can author meaningful regression tests, but do not run tests or
start review loops before Main announces the wave. Minimal syntax checks are
allowed when necessary to finish implementation. No unrelated changes.

Main owns Git commits, branch operations, integration and releases. Workers do
not switch branches, commit, push, create remote repositories or open PRs.
Use disjoint file ownership and communicate interface questions promptly.
No outbound publication until local implementation and checks pass.

## Technical target

Python 3.11+, standard library runtime, Windows-first process/startup adapter.
Pure merge/validation and synthetic CLI workflows must run on other platforms.
Respect custom CODEX_HOME with an explicit --codex-home override.
Runtime config/journal/backups live outside the source checkout by default.
Exactly two explicitly selected profile IDs for the first beta.

Commands: doctor, setup, preview, sync, start, watch, status, stop, backup,
restore, uninstall. Inspection/preview must not write helper or app state.
One-time sync and watchers share a cross-process lock for a settings target.
Pause on unknown schemas, incomplete account snapshots and unresolved conflicts.
No writes while desktop processes are alive. Recover partial transactions.
Removals default off and require explicit enablement plus safe change handling.
Keep account identity, credentials, cloud, remote and permission data scoped.

See .coordination/CONTRACT.md for shared module interfaces and ownership.
