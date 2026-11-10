# Release process

The public repository is [desanv01/codex-local-sync](https://github.com/desanv01/codex-local-sync). The initial beta is published through a reviewed pull request after local checks and Windows CI. This document describes artifact generation and the publication gates.

## Repository metadata

| Field | Value |
| --- | --- |
| Owner / repository | `desanv01/codex-local-sync` |
| Visibility | Public |
| Description | Windows-first local Codex organization sync between two selected profiles, with preview, backups and recovery. |
| Topics | `codex`, `windows`, `python`, `local-first`, `cli`, `backup`, `sync`, `mit-license` |
| License | MIT, copyright 2026 Desan Vasu |
| Package version | `0.1.0b1` |
| Git tag | `v0.1.0-beta.1` |
| Website | Leave unset until a real project page exists |

The README follows the author's existing project style: centered summary, truthful badges, navigation, scope and evidence. No fabricated demo, screenshots, CI badge or download link is needed for local preparation.

## Local artifact build

From a reviewed checkout:

```powershell
python scripts/build_release.py
```

The stdlib builder creates `dist/codex-local-sync-0.1.0b1-source.zip` and `dist/SHA256SUMS`. `--output-dir PATH` selects another subdirectory of the checkout. Version is read from the package's `__init__.py`; a malformed version stops the build.

Archive members come from named top-level files (including `pyproject.toml` and `MANIFEST.in`), named package modules, named documentation and GitHub configuration, the release script, and Python source under `tests/`. Test data must be generated synthetically. Arbitrary fixtures, settings, logs, backups, `.coordination/`, Git history, environments and output directories are excluded. Source links are rejected. New release files need an intentional allowlist update.

Sorted entries, fixed timestamps, fixed Unix file modes and uncompressed ZIP storage make the same input bytes produce the same ZIP bytes without depending on a compression-library version. The script reopens the result and checks exact membership, CRC, timestamps and payload bytes before publishing it locally. This structural audit does not detect a secret embedded in an otherwise permitted source file; review the source contents too.

`SHA256SUMS` covers the source ZIP only. Wheel and sdist are built separately using the phase-1-owned `pyproject.toml`, for example with the pinned build tools selected in CI. Main must inspect their membership independently and compute checksums for the complete selected release asset set. Do not present the ZIP checksum file as coverage for wheel/sdist.

## Publication gate

1. Finish implementation across all phases, then run the single focused testing/fixes wave.
2. Record actual results and limits in [compatibility](compatibility.md); do not convert the older personal helper's behavior into packaged-beta evidence.
3. Verify a clean source install, command entry point, regression suite, source ZIP, wheel and sdist. Rebuild the ZIP twice from unchanged bytes if checking reproducibility.
4. Inspect the exact staged source, Git history and every artifact for private data, copied app code and unexpected files. Confirm all fixtures are synthetic.
5. Confirm the installed personal helper, live settings and startup entries remain unchanged by development.
6. Main integrates locally, then performs the authorized GitHub publication step. Confirm repository metadata, license, least-privilege CI and private vulnerability reporting settings where available.
7. Observe hosted CI before claiming it passes. Publish the beta with actual test evidence, compatibility limits, recovery instructions, selected assets and corresponding checksums.

No public repository creation, push, pull request, release or startup installation is part of the local build command.

## Beta release-note outline

Lead with two-profile local organization sync on Windows. List preview, conflict pauses, additive defaults, backup/recovery and optional watcher/startup. State Python 3.11+, the exact tests performed and desktop-build evidence available. Link installation and recovery instructions. Explicitly retain the limits: private observed schema, no message/cloud sync, no guaranteed sidebar recovery and no certification of untested desktop builds.
