"""Build and verify a deterministic, allowlisted source ZIP using only stdlib.

Run from any directory: python scripts/build_release.py [--output-dir dist]
No settings, coordination files, arbitrary fixtures or runtime data are included.
"""

from __future__ import annotations

import argparse
import hashlib
import re
import tempfile
from pathlib import Path
from zipfile import ZIP_STORED, ZipFile, ZipInfo


ROOT = Path(__file__).resolve().parents[1]
TOP_LEVEL = (
    "README.md", "LICENSE", "CHANGELOG.md", "CONTRIBUTING.md", "SECURITY.md",
    "AGENTS.md", ".gitignore", ".gitattributes", "pyproject.toml", "MANIFEST.in",
)
MODULES = (
    "__init__.py", "__main__.py", "errors.py", "state.py", "engine.py",
    "storage.py", "windows.py", "cli.py",
)
DOCS = (
    "installation.md", "architecture.md", "recovery.md", "compatibility.md",
    "troubleshooting.md", "release.md",
)
ISSUES = ("bug_report.yml", "feature_request.yml", "config.yml")


def _read_source(relative: str) -> bytes:
    path = ROOT / relative
    # Reject directory links as well as file links. Resolve before reading.
    for component in (path, *path.parents):
        if component == ROOT:
            break
        if component.is_symlink() or getattr(component, "is_junction", lambda: False)():
            raise ValueError(f"Linked release input rejected: {relative}")
    if not path.resolve().is_relative_to(ROOT):
        raise ValueError(f"Release input escapes source root: {relative}")
    if not path.is_file():
        raise ValueError(f"Missing required release input: {relative}")
    return path.read_bytes()


def source_files() -> dict[str, bytes]:
    """Read only explicit project files and Python tests; never copy a tree."""
    names = list(TOP_LEVEL)
    names.extend(f"src/codex_local_sync/{name}" for name in MODULES)
    names.extend(f"docs/{name}" for name in DOCS)
    names.extend(f".github/ISSUE_TEMPLATE/{name}" for name in ISSUES)
    names.extend((".github/workflows/ci.yml", "scripts/build_release.py"))
    # Tests generate their own synthetic state. No JSON/settings fixture is
    # implicitly included, even if accidentally placed under tests/.
    for path in sorted((ROOT / "tests").rglob("*.py")):
        relative = path.relative_to(ROOT).as_posix()
        if any(part.startswith(".") or part == "__pycache__" for part in path.relative_to(ROOT).parts):
            raise ValueError(f"Hidden test input rejected: {relative}")
        names.append(relative)
    return {name: _read_source(name) for name in sorted(set(names))}


def audit_archive(archive: Path, files: dict[str, bytes], prefix: str) -> None:
    """Check exact membership, metadata and every payload before publication."""
    expected = {f"{prefix}/{name}": value for name, value in files.items()}
    with ZipFile(archive) as package:
        if package.namelist() != sorted(expected):
            raise ValueError("Source archive membership differs from allowlist")
        if package.testzip() is not None:
            raise ValueError("Source archive CRC check failed")
        for entry in package.infolist():
            if entry.date_time != (1980, 1, 1, 0, 0, 0):
                raise ValueError("Non-deterministic archive timestamp")
            if entry.compress_type != ZIP_STORED or entry.extra or entry.comment:
                raise ValueError("Unexpected archive metadata")
            if package.read(entry) != expected[entry.filename]:
                raise ValueError("Source archive payload differs from input")


def build(output_dir: Path) -> tuple[Path, Path]:
    output_dir = output_dir.resolve()
    if not output_dir.is_relative_to(ROOT) or output_dir == ROOT:
        raise ValueError("Output directory must be a subdirectory of this checkout")
    files = source_files()
    version_text = files["src/codex_local_sync/__init__.py"].decode("utf-8-sig")
    match = re.search(r'^__version__\s*=\s*[\'"]([0-9][A-Za-z0-9.]*?)[\'"]\s*$', version_text, re.MULTILINE)
    if match is None:
        raise ValueError("Cannot read safe package version from __init__.py")
    prefix = f"codex-local-sync-{match.group(1)}"
    # All input reads and validations precede creation of any build output.
    output_dir.mkdir(parents=True, exist_ok=True)
    archive = output_dir / f"{prefix}-source.zip"
    checksums = output_dir / "SHA256SUMS"
    with tempfile.TemporaryDirectory(prefix="source-build-", dir=output_dir) as temp:
        staged = Path(temp) / archive.name
        with ZipFile(staged, "w", compression=ZIP_STORED) as package:
            for name, payload in sorted(files.items()):
                entry = ZipInfo(f"{prefix}/{name}", date_time=(1980, 1, 1, 0, 0, 0))
                entry.create_system = 3
                entry.external_attr = 0o100644 << 16
                entry.compress_type = ZIP_STORED
                package.writestr(entry, payload)
        audit_archive(staged, files, prefix)
        digest = hashlib.sha256(staged.read_bytes()).hexdigest()
        staged_checksums = Path(temp) / checksums.name
        staged_checksums.write_text(f"{digest}  {archive.name}\n", encoding="ascii", newline="\n")
        staged.replace(archive)
        staged_checksums.replace(checksums)
    return archive, checksums


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output-dir", type=Path, default=ROOT / "dist")
    args = parser.parse_args()
    try:
        archive, checksums = build(args.output_dir)
    except (OSError, ValueError) as exc:
        parser.exit(1, f"Release build failed: {exc}\n")
    print(f"Built and audited {archive.name}")
    print(f"Wrote {checksums.name} (source ZIP only)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
