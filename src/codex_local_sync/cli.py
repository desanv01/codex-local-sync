"""Command line entry point and cooperative background watcher."""
from __future__ import annotations

import argparse
from collections import Counter
from contextlib import contextmanager
from datetime import datetime, timezone
import hashlib
import json
import math
import os
from pathlib import Path
import signal
import sys
import time
import uuid

from . import __version__, storage, windows
from .errors import BusyError, SyncError, ValidationError
from .state import discover_profiles, snapshot_profiles


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _read_json(path: Path) -> dict:
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except FileNotFoundError:
        return {}
    except (ValueError, OSError) as exc:
        raise ValidationError(f"Cannot read helper metadata: {path.name}") from exc
    if not isinstance(value, dict):
        raise ValidationError(f"Invalid helper metadata: {path.name}")
    return value


def _write_json(path: Path, value: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(path.name + "." + uuid.uuid4().hex + ".tmp")
    try:
        with temporary.open("x", encoding="utf-8") as stream:
            json.dump(value, stream, ensure_ascii=False, indent=2)
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(temporary, path)
    finally:
        temporary.unlink(missing_ok=True)


@contextmanager
def _lifecycle_lock(data_dir: Path, filename: str = "watcher.lock"):
    """Held for the watcher lifetime; never unlink a locked inode."""
    data_dir.mkdir(parents=True, exist_ok=True)
    stream = (data_dir / filename).open("a+b")
    try:
        stream.seek(0, 2)
        if stream.tell() == 0:
            stream.write(b"\0")
            stream.flush()
        stream.seek(0)
        try:
            if os.name == "nt":
                import msvcrt
                msvcrt.locking(stream.fileno(), msvcrt.LK_NBLCK, 1)
            else:
                import fcntl
                fcntl.flock(stream, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except OSError as exc:
            raise BusyError("Another watcher or lifecycle operation owns this target.") from exc
        try:
            yield
        finally:
            stream.seek(0)
            if os.name == "nt":
                msvcrt.locking(stream.fileno(), msvcrt.LK_UNLCK, 1)
            else:
                fcntl.flock(stream, fcntl.LOCK_UN)
    finally:
        stream.close()


def _target(home: Path) -> str:
    return hashlib.sha256(os.path.normcase(str(home.resolve())).encode()).hexdigest()


def _status(data_dir: Path, home: Path, *, include_journal: bool = True) -> dict:
    status = _read_json(data_dir / "watcher.json")
    journal = (storage.read_journal(data_dir) or {}) if include_journal else {}
    if status and (status.get("schema_version") != 1 or type(status.get("pid")) is not int
                   or status["pid"] <= 0 or not isinstance(status.get("token"), str)
                   or not status["token"]):
        raise ValidationError("Unsupported or incomplete watcher metadata; lifecycle operation paused.")
    if journal.get("target") is not None and not isinstance(journal["target"], str):
        raise ValidationError("Invalid journal settings target.")
    if journal.get("target") and Path(journal["target"]).resolve() != home.resolve():
        raise ValidationError("Journal belongs to another settings target.")
    if not status:
        return {"running": False, "state": "not_started", "last_success": journal.get("last_success"),
                "pending": bool(journal.get("pending", False)), "error": None}
    if status.get("target") != _target(home):
        raise ValidationError("Data directory belongs to another settings target.")
    pid = status.get("pid")
    identity = windows.process_identity(pid) if type(pid) is int else None
    alive = bool(identity and identity == status.get("identity") and status.get("state") != "stopped")
    successes = [s for s in (status.get("last_success"), journal.get("last_success")) if isinstance(s, str)]
    return {**status, "running": alive, "state": status.get("state") if alive else "stopped",
            "last_success": max(successes) if successes else None,
            "pending": bool(status.get("pending") or journal.get("pending"))}


def _check_target(config: dict, home: Path) -> None:
    configured = config.get("codex_home")
    if configured and Path(configured).resolve() != home.resolve():
        raise ValidationError("Configuration belongs to a different Codex home; select its data directory.")


def _summary(plan: dict, details: bool = False) -> dict:
    changes = plan.get("changes", [])
    categories = Counter(str(c.get("category", c.get("field", c.get("kind", "organization"))))
                         for c in changes)
    result = {"changed": bool(plan.get("changed")), "change_count": len(changes),
              "categories": dict(categories), "conflict_count": len(plan.get("conflicts", [])),
              "warning_count": len(plan.get("warnings", []))}
    if details:
        result.update(changes=changes, conflicts=plan.get("conflicts", []), warnings=plan.get("warnings", []))
    return result


def _confirm(args, message: str) -> None:
    if args.yes:
        return
    if not sys.stdin.isatty() or input(message + " [y/N] ").strip().casefold() not in {"y", "yes"}:
        raise ValidationError("Explicit confirmation required; review options and use --yes.")


def _setup(args, home: Path, data_dir: Path) -> dict:
    state = storage.read_state(home)
    profiles = discover_profiles(state)
    available = {p["id"]: p for p in profiles}
    selected = args.profiles
    if not selected:
        if not sys.stdin.isatty():
            raise ValidationError("Select exactly two accounts using --profiles ID ID and an explicit --seed ID.")
        for index, profile in enumerate(profiles, 1):
            print(f"{index}: projects={profile['project_count']}, assignments={profile['assignment_count']}, active={profile['active']}")
        try:
            indexes = [int(s) - 1 for s in input("Select two account numbers separated by a space: ").split()]
            if len(indexes) != 2 or any(i < 0 or i >= len(profiles) for i in indexes):
                raise ValueError
            selected = [profiles[i]["id"] for i in indexes]
        except (ValueError, IndexError) as exc:
            raise ValidationError("Select exactly two listed accounts.") from exc
    if len(selected) != 2 or len(set(selected)) != 2 or any(p not in available for p in selected):
        raise ValidationError("Select exactly two distinct complete account snapshots.")
    snapshot_profiles(state, selected)
    seed = args.seed
    if seed is None and sys.stdin.isatty():
        choice = input("Initial conflict seed account number (1 or 2, in selected order): ").strip()
        if choice in {"1", "2"}:
            seed = selected[int(choice) - 1]
    if seed not in selected:
        raise ValidationError("An explicit --seed must name one of the two selected accounts.")
    aliases = {}
    for alias in args.alias:
        key, separator, label = alias.partition("=")
        if not separator or key not in selected or not label.strip() or len(label) > 80:
            raise ValidationError("Aliases must use selected ID=NAME, with a name of 1 to 80 characters.")
        aliases[key] = label.strip()
    if sys.stdin.isatty() and not args.yes:
        for index, key in enumerate(selected, 1):
            if key not in aliases:
                label = input(f"Optional display alias for account {index}: ").strip()
                if len(label) > 80:
                    raise ValidationError("Alias is longer than 80 characters.")
                if label:
                    aliases[key] = label
    existing = storage.load_config(data_dir) if (data_dir / "config.json").exists() else None
    config = {"schema_version": 1, "profile_ids": selected, "seed_profile": seed,
              "allow_removals": bool(args.allow_removals), "aliases": aliases, "codex_home": str(home)}
    if existing:
        _check_target(existing, home)
        if existing.get("profile_ids") != selected or existing.get("seed_profile") != seed:
            raise ValidationError("Existing journal pairing/seed cannot be replaced; use a new data directory.")
    status = _status(data_dir, home)
    if status["running"]:
        raise BusyError("Stop the watcher before changing configuration.")
    message = "Save this two-account configuration"
    if args.allow_removals:
        message += " with explicit removal propagation enabled"
    _confirm(args, message + "?")
    with _lifecycle_lock(data_dir):
        storage.save_config(data_dir, config)
    return {"configured": True, "profile_count": 2, "allow_removals": config["allow_removals"],
            "settings_written": False}


def _fingerprint(home: Path) -> str:
    return hashlib.sha256((home / ".codex-global-state.json").read_bytes()).hexdigest()


def watch(home: Path, data_dir: Path, *, interval: float = 1.0, launch_token: str | None = None) -> dict:
    """Observe stable live snapshots; commit only after closed + stable >=3s."""
    if not math.isfinite(interval) or interval < 0.25:
        raise ValidationError("Watcher interval must be finite and at least 0.25 seconds.")
    config = storage.load_config(data_dir)
    _check_target(config, home)
    # Unsupported platforms fail before writing lifecycle metadata.
    windows.app_running()
    if windows.legacy_watcher_running():
        raise BusyError("A possible legacy Codex sync helper is running; stop or migrate it explicitly first.")
    quitting = False

    def request_stop(_signum, _frame):
        nonlocal quitting
        quitting = True

    previous_handlers = {}
    for sig in (signal.SIGINT, signal.SIGTERM):
        previous_handlers[sig] = signal.signal(sig, request_stop)
    try:
        with _lifecycle_lock(data_dir), _lifecycle_lock(home, ".codex-local-sync-watcher.lock"):
            old = _status(data_dir, home)
            token = uuid.uuid4().hex
            status = {"schema_version": 1, "pid": os.getpid(), "identity": windows.process_identity(os.getpid()),
                      "token": token, "launch_token": launch_token, "target": _target(home), "state": "starting", "started_at": _now(),
                      "last_success": old.get("last_success"), "pending": False, "error": None}
            _write_json(data_dir / "watcher.json", status)
            fingerprint = None
            stable_since = time.monotonic()
            closed_since = None
            processed = None
            try:
                while not quitting:
                    marker = _read_json(data_dir / "stop.json")
                    if marker.get("token") == token:
                        break
                    try:
                        running = windows.app_running()
                        current = _fingerprint(home)
                        now = time.monotonic()
                        if current != fingerprint:
                            fingerprint, stable_since = current, now
                            status["pending"] = True
                        closed_since = None if running else (closed_since if closed_since is not None else now)
                        status.update(state="observing" if running else "waiting_for_quiet", error=None)
                        if now - stable_since >= 3:
                            if running and processed != (current, True):
                                result = storage.observe_once(home, data_dir, config=config, expected_fingerprint=current)
                                if result.get("conflicts"):
                                    raise ValidationError("Conflicting account edits require review with preview.")
                                processed = (current, True)
                                status["pending"] = bool(result.get("journal", {}).get("pending", result.get("changed", True)))
                            elif not running and now - closed_since >= 3 and processed != (current, False):
                                result = storage.sync_once(home, data_dir, is_app_running=windows.app_running,
                                                           config=config, expected_fingerprint=current)
                                if result.get("conflicts"):
                                    raise ValidationError("Conflicting account edits require review with preview.")
                                status.update(last_success=_now(), pending=False, state="idle")
                                fingerprint = _fingerprint(home)
                                stable_since = time.monotonic()
                                processed = (fingerprint, False)
                            elif not running and now - closed_since >= 3 and processed == (current, False):
                                status.update(state="idle", pending=False)
                    except (SyncError, OSError, ValueError) as exc:
                        # Never record account data or exception paths in persistent status.
                        status.update(state="paused", pending=True, error=type(exc).__name__)
                        closed_since = None
                        stable_since = time.monotonic()
                    status["heartbeat"] = _now()
                    _write_json(data_dir / "watcher.json", status)
                    # Bounded cooperative wait, also for slow configured polling.
                    deadline = time.monotonic() + interval
                    while not quitting and time.monotonic() < deadline:
                        if _read_json(data_dir / "stop.json").get("token") == token:
                            quitting = True
                            break
                        time.sleep(min(0.25, max(0, deadline - time.monotonic())))
            finally:
                status.update(state="stopped", stopped_at=_now(), heartbeat=_now())
                _write_json(data_dir / "watcher.json", status)
                if _read_json(data_dir / "stop.json").get("token") == token:
                    (data_dir / "stop.json").unlink(missing_ok=True)
    finally:
        for sig, handler in previous_handlers.items():
            signal.signal(sig, handler)
    return {"stopped": True}


def _stop(home: Path, data_dir: Path, timeout: float) -> dict:
    if not math.isfinite(timeout) or timeout < 0:
        raise ValidationError("Stop timeout must be a finite nonnegative number.")
    status = _status(data_dir, home, include_journal=False)
    if not status["running"]:
        return {"stopped": True, "was_running": False}
    if not isinstance(status.get("token"), str):
        raise ValidationError("Watcher ownership token is missing; no stop request written.")
    _write_json(data_dir / "stop.json", {"token": status["token"]})
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        if not _status(data_dir, home, include_journal=False)["running"]:
            return {"stopped": True, "was_running": True}
        time.sleep(0.1)
    raise BusyError("Graceful stop requested but not yet acknowledged; check status.")


def build_parser() -> argparse.ArgumentParser:
    common = argparse.ArgumentParser(add_help=False)
    common.add_argument("--codex-home", metavar="PATH", default=argparse.SUPPRESS)
    common.add_argument("--data-dir", metavar="PATH", default=argparse.SUPPRESS)
    common.add_argument("--json", action="store_true", default=argparse.SUPPRESS)
    parser = argparse.ArgumentParser(prog="codex-local-sync", parents=[common],
                                     description="Local two-account Codex organization sync (beta).")
    parser.add_argument("--version", action="version", version=__version__)
    commands = parser.add_subparsers(dest="command", required=True)
    for name in ("doctor", "setup", "preview", "sync", "start", "watch", "status", "stop", "backup", "restore", "uninstall"):
        command = commands.add_parser(name, parents=[common])
        if name == "setup":
            command.add_argument("--profiles", nargs=2, metavar="ID")
            command.add_argument("--seed", metavar="ID")
            command.add_argument("--alias", action="append", default=[], metavar="ID=NAME")
            command.add_argument("--allow-removals", action="store_true")
        if name in {"setup", "restore", "uninstall"}:
            command.add_argument("--yes", action="store_true", help="Confirm the explicitly selected operation")
        if name == "preview":
            command.add_argument("--details", action="store_true", help="Include identifiers, paths and detailed changes")
        if name == "start":
            command.add_argument("--startup", action="store_true", help="Opt in to current-user Windows logon startup")
        if name == "watch":
            command.add_argument("--interval", type=float, default=1.0, metavar="SECONDS")
            command.add_argument("--launch-token", help=argparse.SUPPRESS)
        if name == "stop":
            command.add_argument("--timeout", type=float, default=10.0, metavar="SECONDS")
        if name == "restore":
            command.add_argument("backup", type=Path, metavar="BACKUP")
    return parser


def _execute(args, home: Path, data_dir: Path) -> dict:
    command = args.command
    if command == "doctor":
        profiles = discover_profiles(storage.read_state(home))
        result = {"version": __version__, "schema_supported": True, "profile_count": len(profiles),
                  "live_writes_supported": os.name == "nt", "configured": (data_dir / "config.json").exists()}
        if result["configured"]:
            _check_target(storage.load_config(data_dir), home)
        if os.name == "nt":
            result["desktop_running"] = windows.app_running()
            result["legacy_helper_warning"] = windows.legacy_watcher_running()
        return result
    if command == "setup":
        return _setup(args, home, data_dir)
    if command == "status":
        status = _status(data_dir, home)
        return {key: status.get(key) for key in ("running", "state", "last_success", "pending", "error", "heartbeat")}
    if command == "stop":
        return _stop(home, data_dir, args.timeout)
    if command == "uninstall":
        _confirm(args, "Stop the watcher and remove its owned current-user startup entry, preserving all data?")
        _stop(home, data_dir, 10)
        if os.name == "nt":
            windows.remove_startup(data_dir)
        return {"uninstalled": True, "data_preserved": True}
    config = storage.load_config(data_dir)
    _check_target(config, home)
    if command == "preview":
        return _summary(storage.preview_sync(home, data_dir, config=config), args.details)
    if command == "sync":
        return _summary(storage.sync_once(home, data_dir, is_app_running=windows.app_running, config=config))
    if command == "backup":
        backup = storage.create_backup(home, data_dir, is_app_running=windows.app_running)
        return {"backup": str(backup)}
    if command == "restore":
        _confirm(args, "Restore the selected backup after closing Codex desktop?")
        result = storage.restore_backup(home, data_dir, args.backup.resolve(), is_app_running=windows.app_running)
        return {"restored": True, **_summary(result)}
    if command == "watch":
        return watch(home, data_dir, interval=args.interval, launch_token=args.launch_token)
    if command == "start":
        status = _status(data_dir, home)
        if args.startup:
            windows.check_startup(data_dir, home)
        result = {"started": False, "already_running": True} if status["running"] else windows.launch_watcher(data_dir, home)
        if args.startup:
            result.update(windows.install_startup(data_dir, home))
        return result
    raise ValidationError("Unknown command.")


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    try:
        home = storage.resolve_codex_home(getattr(args, "codex_home", None)).resolve()
        data_dir = Path(args.data_dir).expanduser().resolve() if hasattr(args, "data_dir") else storage.default_data_dir().resolve()
        result = _execute(args, home, data_dir)
        if getattr(args, "json", False):
            print(json.dumps(result, ensure_ascii=False, sort_keys=True))
        else:
            for key, value in result.items():
                print(f"{key}: {json.dumps(value, ensure_ascii=False) if isinstance(value, (dict, list)) else value}")
        return 2 if result.get("conflict_count", 0) else 0
    except (SyncError, OSError, ValueError) as exc:
        # Filesystem exceptions can contain sensitive full paths.
        message = str(exc) if isinstance(exc, SyncError) else "Cannot complete operation; check selected files and permissions."
        if getattr(args, "json", False):
            print(json.dumps({"error": type(exc).__name__, "message": message}), file=sys.stderr)
        else:
            print(f"{type(exc).__name__}: {message}", file=sys.stderr)
        return 1
    except (EOFError, KeyboardInterrupt):
        print("Operation cancelled.", file=sys.stderr)
        return 130
