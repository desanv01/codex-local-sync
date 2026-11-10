# Compatibility and evidence

## Declared beta scope

| Area | Scope |
| --- | --- |
| Python | 3.11 and newer |
| Runtime dependencies | Python standard library |
| Live settings mutation | Windows, through conservative process checks |
| Background/startup integration | Windows current user |
| Portable use | Pure merge/validation and synthetic CLI inspection workflows |
| Selected profiles | Exactly two |
| Settings | Recognized complete local profile schema only |

The adapter recognizes observed keys including `electron-account-renderer-state-v1` and `electron-persisted-atom-state`. Their existence is not a public compatibility guarantee from OpenAI. Unknown schema shapes pause operation.

## Evidence record

| Verification | Current record |
| --- | --- |
| Synthetic regression suite | 32 tests passed locally on Windows / Python 3.11, including a complete run against the installed wheel. Covers merge, scope preservation, signed-out snapshots, conflicts, recovery, locking, CLI and mocked lifecycle checks. |
| Windows Python 3.11 / 3.13 CI | Both hosted jobs passed tests, wheel/sdist audits, installed entry points and source ZIP checks on November 10, 2026. [Implementation CI evidence](https://github.com/desanv01/codex-local-sync/actions/runs/42734238857). |
| Source ZIP | Local allowlist/payload audit and privacy-pattern scan passed; two builds from identical frozen input bytes matched |
| Wheel / sdist | Built locally and passed source-byte, membership, metadata, complete synthetic-test-source and entry-point audits. The wheel installed into a project-local virtual environment successfully. |
| Real desktop account switching with this packaged beta | Not performed during development; live settings and installed helper are protected |
| Specific desktop build compatibility | No packaged-beta build is certified yet |
| macOS/Linux live writes | Unsupported |

The previous personal helper's successful use is background motivation, not evidence that this packaged beta has passed the same live workflow. Publish exact tested versions and scope only after retaining the corresponding result. A synthetic pass verifies the modeled schema and failure behavior; it cannot establish sidebar visibility or every app startup/process race.
