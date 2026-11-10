# Contributing

Keep changes focused on local organization sync. Read `AGENTS.md` before working in this checkout; its phase ownership and verification order apply during coordinated development.

## Local development

Use Python 3.11 or newer and a virtual environment. Runtime code uses the standard library. Install with `python -m pip install -e .` and use `python -m unittest discover -s tests` for the focused regression suite when the coordinated testing wave is open.

All fixtures must be synthetic. Keep temporary homes and helper data inside the checkout under ignored directories, for example `work/example-home` and `work/example-data`. Never point development commands at a real `CODEX_HOME`, installed watcher or startup entry. Pass explicit paths; do not rely on the developer's environment.

Do not commit profile identifiers, settings snapshots, transcripts, journals, databases, personal paths, credentials, proprietary app code or screenshots containing private data. A redacted real snapshot is not a substitute for a generated fixture.

## Changes and review

- Preserve unknown and account-scoped data. Fail closed for unsupported schemas and uncertain process state.
- Keep preview and diagnostics read-only. Share the target lock across every mutating path.
- Add a focused regression for a meaningful behavior change, using generated data and injected process adapters.
- Explain the trigger, resulting behavior and verification in the change description.
- Update command documentation when options or recovery behavior change.

Do not publish a repository, push, open a pull request or create a release during the local preparation phase. Main owns Git integration and publication for this coordinated project.

For a normal public contribution, open an issue with the problem and a synthetic reproduction before a broad redesign. Use the bug template and inspect anything you attach. For a security concern, follow [SECURITY.md](SECURITY.md).
