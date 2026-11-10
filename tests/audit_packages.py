"""Audit built wheel/sdist contents; invoked explicitly after package build."""

from __future__ import annotations

from email.parser import Parser
from pathlib import Path, PurePosixPath
import sys
import tarfile
import zipfile


ROOT = Path(__file__).resolve().parents[1]
FORBIDDEN = {".coordination", "work", "runtime", "backups", ".git", ".venv",
             "__pycache__", ".env", "auth.json", "config.json", "journal.json",
             "transaction.json", "status.json", "watcher.json", "installation.json"}


def safe_member(name):
    path = PurePosixPath(name)
    assert not path.is_absolute() and ".." not in path.parts, name
    assert not (set(path.parts) & FORBIDDEN), name
    assert not any(part.startswith(".codex-global-state.json") for part in path.parts), name
    assert not name.endswith((".pyc", ".log", ".sqlite", ".db", ".bak")), name


def audit(directory):
    directory = Path(directory)
    wheels = list(directory.glob("codex_local_sync-*.whl"))
    sdists = list(directory.glob("codex_local_sync-*.tar.gz"))
    assert len(wheels) == len(sdists) == 1, "Build into a clean dist directory."
    expected = {p.relative_to(ROOT / "src").as_posix()
                for p in (ROOT / "src" / "codex_local_sync").rglob("*.py")}
    assert expected, "No package source found."
    with zipfile.ZipFile(wheels[0]) as wheel:
        names = wheel.namelist()
        assert len(names) == len(set(names)), "Duplicate wheel members."
        for name in names:
            safe_member(name)
            assert name.startswith("codex_local_sync/") or ".dist-info/" in name, name
        actual = {name for name in names if name.startswith("codex_local_sync/")}
        assert actual == expected, (actual, expected)
        for name in expected:
            assert wheel.read(name) == (ROOT / "src" / name).read_bytes(), name
        metadata_name = next(name for name in names if name.endswith(".dist-info/METADATA"))
        metadata = Parser().parsestr(wheel.read(metadata_name).decode())
        assert metadata["Name"] == "codex-local-sync"
        assert not metadata.get_all("Requires-Dist"), "Runtime must remain standard-library only."
        entry = next(name for name in names if name.endswith(".dist-info/entry_points.txt"))
        assert "codex-local-sync = codex_local_sync.cli:main" in wheel.read(entry).decode()
        assert any(name.endswith("/LICENSE") for name in names), "MIT license absent from wheel."
    with tarfile.open(sdists[0], "r:gz") as sdist:
        source = {}
        members = sdist.getmembers()
        names = [member.name for member in members]
        assert len(names) == len(set(names)), "Duplicate sdist members."
        for member in members:
            safe_member(member.name)
            assert not member.issym() and not member.islnk(), member.name
            relative = PurePosixPath(member.name).parts[1:]
            if not relative or member.isdir():
                continue
            name = "/".join(relative)
            assert name in {"LICENSE", "README.md", "MANIFEST.in", "pyproject.toml", "PKG-INFO", "setup.cfg"} \
                or name.startswith(("src/codex_local_sync/", "src/codex_local_sync.egg-info/", "tests/")), name
            if name.startswith("src/codex_local_sync/"):
                assert member.isfile(), name
                source[name[4:]] = sdist.extractfile(member).read()
        assert set(source) == expected, (set(source), expected)
        for name, contents in source.items():
            assert contents == (ROOT / "src" / name).read_bytes(), name
        expected_tests = {p.relative_to(ROOT).as_posix() for p in (ROOT / "tests").rglob("*.py")}
        actual_tests = {"/".join(PurePosixPath(member.name).parts[1:]) for member in members
                        if member.isfile() and "/".join(PurePosixPath(member.name).parts[1:]).startswith("tests/")}
        assert actual_tests == expected_tests, "Source distribution must include test helpers and fixtures."
    print("Wheel and sdist contents, package bytes, metadata, and entry point passed audit.")


if __name__ == "__main__":
    audit(Path(sys.argv[1]) if len(sys.argv) > 1 else ROOT / "dist")
