"""Filesystem boundary, target lock, raw backups and recoverable transactions.

Preview is read-only. Every settings/journal mutation holds a lock beside the
settings target, so using a second helper data directory cannot bypass it.
Replacement is atomic per file; a durable intent makes the main, fallback and
journal commit recoverable. Unexpected bytes always require human review.
"""
from __future__ import annotations

import base64
from contextlib import contextmanager
from copy import deepcopy
from datetime import datetime, timezone
import hashlib
import json
import os
from pathlib import Path
import tempfile
from typing import Callable
import uuid

from .engine import plan_sync, validate_config
from .errors import BusyError, CompatibilityError, ConflictError, ValidationError
from .state import snapshot_profiles, validate_view

STATE_FILE = ".codex-global-state.json"
CONFIG_FILE = "config.json"
JOURNAL_FILE = "journal.json"
INTENT_FILE = "transaction.json"
PENDING_FILE = ".codex-local-sync.pending.json"


def resolve_codex_home(value: str | None = None) -> Path:
    return Path(value or os.environ.get("CODEX_HOME") or Path.home() / ".codex").expanduser().resolve()


def default_data_dir() -> Path:
    if os.name == "nt":
        root = Path(os.environ.get("LOCALAPPDATA") or Path.home() / "AppData" / "Local")
    else:
        root = Path(os.environ.get("XDG_DATA_HOME") or Path.home() / ".local" / "share")
    return root / "codex-local-sync"


def _json_bytes(value: dict) -> bytes:
    return (json.dumps(value, ensure_ascii=False, sort_keys=True, indent=2, allow_nan=False) + "\n").encode("utf-8")


def _decode(data: bytes, label: str) -> dict:
    def unique_pairs(pairs):
        result = {}
        for key, value in pairs:
            if key in result:
                raise ValidationError(f"Duplicate key in {label}.")
            result[key] = value
        return result
    try:
        value = json.loads(data.decode("utf-8-sig"), object_pairs_hook=unique_pairs,
                           parse_constant=lambda _: (_ for _ in ()).throw(ValueError("nonfinite")))
    except (ValueError, UnicodeError) as exc:
        raise ValidationError(f"Invalid {label} JSON.") from exc
    if not isinstance(value, dict):
        raise ValidationError(f"{label} must contain a JSON object.")
    return value


def _read(path: Path, label: str, *, optional: bool = False) -> bytes | None:
    try:
        return path.read_bytes()
    except FileNotFoundError:
        if optional:
            return None
        raise ValidationError(f"{label} was not found.") from None
    except OSError as exc:
        raise ValidationError(f"Cannot read {label}.") from exc


def load_config(data_dir: Path) -> dict:
    config = _decode(_read(Path(data_dir) / CONFIG_FILE, "Configuration"), "Configuration")
    validate_config(config)
    return config


def _atomic_write(path: Path, data: bytes) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    descriptor, temporary = tempfile.mkstemp(prefix="." + path.name + "-", dir=path.parent)
    try:
        with os.fdopen(descriptor, "wb") as stream:
            stream.write(data)
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(temporary, path)
    finally:
        try:
            os.unlink(temporary)
        except FileNotFoundError:
            pass


def save_config(data_dir: Path, config: dict) -> None:
    validate_config(config)
    data = Path(data_dir).resolve()
    home = resolve_codex_home(config.get("codex_home"))
    with target_lock(home, data):
        _no_intent(data, home)
        journal = read_journal(data)
        _check_journal_target(journal, home)
        if journal is not None and journal.get("profile_ids", config["profile_ids"]) != config["profile_ids"]:
            raise ValidationError("Existing sync journal selects a different profile pair; review required.")
        _atomic_write(data / CONFIG_FILE, _json_bytes(config))


def read_state(codex_home: Path) -> dict:
    return _decode(_read(Path(codex_home) / STATE_FILE, "Desktop settings"), "Desktop settings")


def read_journal(data_dir: Path) -> dict | None:
    raw = _read(Path(data_dir) / JOURNAL_FILE, "Sync journal", optional=True)
    return None if raw is None else _decode(raw, "Sync journal")


@contextmanager
def target_lock(codex_home: Path, data_dir: Path | None = None):
    """Non-blocking OS lock; kernel releases it even if the process crashes."""
    home = Path(codex_home).resolve()
    if not home.is_dir():
        raise ValidationError("The selected Codex home does not exist.")
    try:
        stream = (home / ".codex-local-sync.lock").open("a+b")
    except OSError as exc:
        raise BusyError("Cannot open the settings target lock.") from exc
    acquired = False
    try:
        if os.name == "nt":
            import msvcrt
            stream.seek(0, os.SEEK_END)
            if stream.tell() == 0:
                stream.write(b"\0")
                stream.flush()
            stream.seek(0)
            try:
                msvcrt.locking(stream.fileno(), msvcrt.LK_NBLCK, 1)
            except OSError as exc:
                raise BusyError("Another operation holds the settings target lock.") from exc
        else:
            import fcntl
            try:
                fcntl.flock(stream.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
            except OSError as exc:
                raise BusyError("Another operation holds the settings target lock.") from exc
        acquired = True
        pending_raw = _read(home / PENDING_FILE, "Target recovery marker", optional=True)
        if pending_raw is not None and data_dir is not None:
            marker = _decode(pending_raw, "Target recovery marker")
            if marker.get("schema_version") != 1 or marker.get("data_dir") != str(Path(data_dir).resolve()):
                raise BusyError("This settings target has a pending transaction in another data directory.")
        yield
    finally:
        if acquired:
            if os.name == "nt":
                import msvcrt
                stream.seek(0)
                msvcrt.locking(stream.fileno(), msvcrt.LK_UNLCK, 1)
            else:
                import fcntl
                fcntl.flock(stream.fileno(), fcntl.LOCK_UN)
        stream.close()


def _hash(raw: bytes | None) -> str | None:
    return None if raw is None else hashlib.sha256(raw).hexdigest()


def _config(home: Path, data_dir: Path, config: dict | None) -> dict:
    result = deepcopy(config) if config is not None else load_config(data_dir)
    validate_config(result)
    if result.get("codex_home") is not None and Path(result["codex_home"]).expanduser().resolve() != home.resolve():
        raise ValidationError("Configuration belongs to a different Codex home.")
    return result


def _check_journal_target(journal: dict | None, home: Path) -> None:
    if journal is not None and journal.get("target") not in (None, str(home.resolve())):
        raise ValidationError("Sync journal belongs to a different Codex home.")


def _stable_state(home: Path) -> tuple[bytes, dict]:
    path = home / STATE_FILE
    first = _read(path, "Desktop settings")
    # The watcher adds a >=3 second quiet period; this also detects replacement
    # between acquisition and planning for one-time calls.
    second = _read(path, "Desktop settings")
    if first != second:
        raise BusyError("Desktop settings changed while being read; retry after the desktop closes.")
    return second, _decode(second, "Desktop settings")


def _closed(is_app_running: Callable[[], bool]) -> None:
    try:
        running = is_app_running()
    except Exception as exc:
        raise BusyError("Cannot establish that the desktop is closed.") from exc
    if running is not False:
        raise BusyError("Close the Codex desktop before modifying settings.")


def _no_intent(data_dir: Path, home: Path | None = None) -> None:
    if (data_dir / INTENT_FILE).exists() or home is not None and (home / PENDING_FILE).exists():
        raise BusyError("An interrupted settings transaction requires recovery with the desktop closed.")


def preview_sync(codex_home: Path, data_dir: Path, config: dict | None = None) -> dict:
    home, data = Path(codex_home).resolve(), Path(data_dir).resolve()
    cfg = _config(home, data, config)
    _no_intent(data, home)
    _, state = _stable_state(home)
    journal = read_journal(data)
    _check_journal_target(journal, home)
    return plan_sync(state, journal, cfg)


def _backup_locked(home: Path, data: Path, raw: bytes, journal_raw: bytes | None,
                   bak: bytes | None) -> Path:
    stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%S%fZ")
    folder = data / "backups" / (stamp + "-" + uuid.uuid4().hex[:8])
    folder.mkdir(parents=True, exist_ok=False)
    files = {"state.json": raw, "state.bak": bak, "journal.json": journal_raw}
    manifest = {"schema_version": 1, "target": str(home), "created_at": stamp,
                "files": {name: _hash(value) for name, value in files.items()}}
    for name, value in files.items():
        if value is not None:
            _atomic_write(folder / name, value)
    _atomic_write(folder / "manifest.json", _json_bytes(manifest))
    return folder


def create_backup(codex_home: Path, data_dir: Path, *, is_app_running: Callable[[], bool]) -> Path:
    home, data = Path(codex_home).resolve(), Path(data_dir).resolve()
    with target_lock(home, data):
        _closed(is_app_running)
        _no_intent(data, home)
        raw, _ = _stable_state(home)
        journal = _read(data / JOURNAL_FILE, "Sync journal", optional=True)
        _closed(is_app_running)
        if _read(home / STATE_FILE, "Desktop settings") != raw:
            raise BusyError("Desktop settings changed before backup.")
        bak = _read(home / (STATE_FILE + ".bak"), "Desktop settings backup", optional=True)
        return _backup_locked(home, data, raw, journal, bak)


def _packed(raw: bytes | None) -> str | None:
    return None if raw is None else base64.b64encode(raw).decode("ascii")


def _unpacked(value) -> bytes | None:
    if value is None:
        return None
    if not isinstance(value, str):
        raise ValidationError("Invalid transaction content.")
    try:
        return base64.b64decode(value, validate=True)
    except ValueError as exc:
        raise ValidationError("Invalid transaction content.") from exc


def _validate_pending(state_raw: bytes, journal_raw: bytes, config: dict) -> None:
    state = _decode(state_raw, "Pending settings")
    snapshot_profiles(state, config["profile_ids"])
    journal = _decode(journal_raw, "Pending sync journal")
    if (journal.get("schema_version") != 1 or not isinstance(journal.get("seen"), dict)
            or set(journal["seen"]) != set(config["profile_ids"])):
        raise ValidationError("Invalid pending sync journal.")
    if journal.get("profile_ids") != config["profile_ids"] or journal.get("source_fingerprint") != _hash(state_raw):
        raise ValidationError("Pending journal does not match the settings transaction.")
    validate_view(journal.get("canonical"))


def _recover_transaction(home: Path, data: Path, config: dict,
                         is_app_running: Callable[[], bool]) -> bool:
    raw_intent = _read(data / INTENT_FILE, "Transaction intent", optional=True)
    if raw_intent is None:
        if (home / PENDING_FILE).exists():
            _closed(is_app_running)
            (home / PENDING_FILE).unlink()
            return True
        return False
    _closed(is_app_running)
    intent = _decode(raw_intent, "Transaction intent")
    if intent.get("schema_version") != 1 or intent.get("target") != str(home):
        raise CompatibilityError("Unsupported or mismatched recovery intent; review required.")
    old_state = _unpacked(intent.get("state_before"))
    new_state = _unpacked(intent.get("state_after"))
    old_journal = _unpacked(intent.get("journal_before"))
    new_journal = _unpacked(intent.get("journal_after"))
    old_bak = _unpacked(intent.get("bak_before"))
    new_bak = _unpacked(intent.get("bak_after"))
    if old_state is None or new_state is None or new_journal is None:
        raise ValidationError("Recovery intent is incomplete.")
    if "bak_before" not in intent or new_bak != new_state:
        raise ValidationError("Recovery intent has an invalid desktop fallback.")
    _validate_pending(new_state, new_journal, config)
    _check_journal_target(_decode(new_journal, "Pending sync journal"), home)
    present_state = _read(home / STATE_FILE, "Desktop settings")
    present_journal = _read(data / JOURNAL_FILE, "Sync journal", optional=True)
    bak_path = home / (STATE_FILE + ".bak")
    present_bak = _read(bak_path, "Desktop settings backup", optional=True)
    if (present_state not in (old_state, new_state) or present_journal not in (old_journal, new_journal)
            or present_bak not in (old_bak, new_bak)):
        raise ConflictError("Settings or journal changed after an interrupted transaction; review required.")
    # Never overwrite unrelated bytes or infer which arbitrary state is newer.
    _closed(is_app_running)
    if present_state == old_state and old_state != new_state:
        if _read(home / STATE_FILE, "Desktop settings") != old_state:
            raise BusyError("Settings changed during recovery.")
        _atomic_write(home / STATE_FILE, new_state)
    _closed(is_app_running)
    if _read(home / STATE_FILE, "Desktop settings") != new_state:
        raise BusyError("Settings changed during recovery.")
    if _read(bak_path, "Desktop settings backup", optional=True) != present_bak:
        raise BusyError("Desktop fallback changed during recovery.")
    if present_bak != new_bak:
        _atomic_write(bak_path, new_bak)
    _closed(is_app_running)
    if (_read(home / STATE_FILE, "Desktop settings") != new_state
            or _read(bak_path, "Desktop settings backup", optional=True) != new_bak):
        raise BusyError("Desktop settings changed during recovery.")
    if _read(data / JOURNAL_FILE, "Sync journal", optional=True) != present_journal:
        raise BusyError("Sync journal changed during recovery.")
    _atomic_write(data / JOURNAL_FILE, new_journal)
    (data / INTENT_FILE).unlink()
    (home / PENDING_FILE).unlink(missing_ok=True)
    return True


def _commit_transaction(home: Path, data: Path, state_before: bytes, state_after: bytes,
                        journal_after: dict, *, is_app_running: Callable[[], bool]) -> Path | None:
    journal_before = _read(data / JOURNAL_FILE, "Sync journal", optional=True)
    bak_path = home / (STATE_FILE + ".bak")
    bak_before = _read(bak_path, "Desktop settings backup", optional=True)
    new_journal = _json_bytes(journal_after)
    _closed(is_app_running)
    if _read(home / STATE_FILE, "Desktop settings") != state_before:
        raise BusyError("Desktop settings changed before commit.")
    backup = (_backup_locked(home, data, state_before, journal_before, bak_before)
              if state_before != state_after or bak_before != state_after else None)
    intent = {"schema_version": 1, "target": str(home),
              "state_before": _packed(state_before), "state_after": _packed(state_after),
              "journal_before": _packed(journal_before), "journal_after": _packed(new_journal),
              "bak_before": _packed(bak_before), "bak_after": _packed(state_after)}
    _atomic_write(home / PENDING_FILE, _json_bytes({"schema_version": 1, "data_dir": str(data)}))
    _atomic_write(data / INTENT_FILE, _json_bytes(intent))
    _closed(is_app_running)
    if _read(home / STATE_FILE, "Desktop settings") != state_before:
        raise BusyError("Desktop settings changed immediately before commit; recovery required.")
    if _read(data / JOURNAL_FILE, "Sync journal", optional=True) != journal_before:
        raise BusyError("Sync journal changed immediately before commit; recovery required.")
    if _read(bak_path, "Desktop settings backup", optional=True) != bak_before:
        raise BusyError("Desktop fallback changed immediately before commit; recovery required.")
    if state_before != state_after:
        _atomic_write(home / STATE_FILE, state_after)
    _closed(is_app_running)
    if _read(home / STATE_FILE, "Desktop settings") != state_after:
        raise BusyError("Desktop settings changed during commit; recovery required.")
    if _read(bak_path, "Desktop settings backup", optional=True) != bak_before:
        raise BusyError("Desktop fallback changed during commit; recovery required.")
    if bak_before != state_after:
        _atomic_write(bak_path, state_after)
    _closed(is_app_running)
    if (_read(home / STATE_FILE, "Desktop settings") != state_after
            or _read(bak_path, "Desktop settings backup", optional=True) != state_after):
        raise BusyError("Desktop settings changed during commit; recovery required.")
    if _read(data / JOURNAL_FILE, "Sync journal", optional=True) != journal_before:
        raise BusyError("Sync journal changed during commit; recovery required.")
    _atomic_write(data / JOURNAL_FILE, new_journal)
    (data / INTENT_FILE).unlink()
    (home / PENDING_FILE).unlink(missing_ok=True)
    return backup


def sync_once(codex_home: Path, data_dir: Path, *, is_app_running: Callable[[], bool],
              config: dict | None = None, expected_fingerprint: str | None = None) -> dict:
    home, data = Path(codex_home).resolve(), Path(data_dir).resolve()
    cfg = _config(home, data, config)
    with target_lock(home, data):
        _closed(is_app_running)
        recovered = _recover_transaction(home, data, cfg, is_app_running)
        raw, state = _stable_state(home)
        if expected_fingerprint is not None and _hash(raw) != expected_fingerprint:
            raise BusyError("Desktop settings changed since the watcher's quiet-period observation.")
        journal = read_journal(data)
        _check_journal_target(journal, home)
        plan = plan_sync(state, journal, cfg)
        if plan["conflicts"]:
            return plan
        after = _json_bytes(plan["state"]) if plan["changed"] else raw
        planned_journal = plan["journal"]
        planned_journal["seen"] = snapshot_profiles(plan["state"], cfg["profile_ids"])
        planned_journal.update(target=str(home), source_fingerprint=_hash(after),
                               last_success=datetime.now(timezone.utc).isoformat(), pending=False)
        backup = _commit_transaction(home, data, raw, after, planned_journal,
                                     is_app_running=is_app_running)
        plan["backup"] = str(backup) if backup else None
        plan["recovered"] = recovered
        return plan


def observe_once(codex_home: Path, data_dir: Path, *, config: dict | None = None,
                  expected_fingerprint: str | None = None) -> dict:
    """Capture stable chronological edits in the journal, never settings bytes."""
    home, data = Path(codex_home).resolve(), Path(data_dir).resolve()
    cfg = _config(home, data, config)
    with target_lock(home, data):
        _no_intent(data, home)
        raw, state = _stable_state(home)
        if expected_fingerprint is not None and _hash(raw) != expected_fingerprint:
            raise BusyError("Desktop settings changed since the watcher's quiet-period observation.")
        journal = read_journal(data)
        _check_journal_target(journal, home)
        plan = plan_sync(state, journal, cfg)
        if plan["conflicts"]:
            return plan
        if journal is not None and journal.get("source_fingerprint") == _hash(raw):
            return {"state": state, "journal": journal, "changes": [], "conflicts": [],
                    "warnings": [], "changed": False, "observed": False}
        if _read(home / STATE_FILE, "Desktop settings") != raw:
            raise BusyError("Desktop settings changed before journal capture.")
        plan["journal"].update(target=str(home), source_fingerprint=_hash(raw),
                               last_observed=datetime.now(timezone.utc).isoformat(),
                               pending=plan["changed"])
        _atomic_write(data / JOURNAL_FILE, _json_bytes(plan["journal"]))
        plan["observed"] = True
        return plan


capture_snapshot = observe_once


def restore_backup(codex_home: Path, data_dir: Path, backup: Path, *,
                   is_app_running: Callable[[], bool]) -> dict:
    home, data, folder = Path(codex_home).resolve(), Path(data_dir).resolve(), Path(backup).resolve()
    cfg = _config(home, data, None)
    with target_lock(home, data):
        _closed(is_app_running)
        _recover_transaction(home, data, cfg, is_app_running)
        manifest = _decode(_read(folder / "manifest.json", "Backup manifest"), "Backup manifest")
        if manifest.get("schema_version") != 1 or manifest.get("target") != str(home):
            raise ValidationError("Backup target or schema does not match.")
        contents = {}
        for name in ("state.json", "state.bak", "journal.json"):
            if name not in manifest.get("files", {}):
                raise ValidationError("Backup manifest is incomplete.")
            raw = _read(folder / name, "Backup content", optional=True)
            if _hash(raw) != manifest["files"][name]:
                raise ValidationError("Backup content failed its integrity check.")
            contents[name] = raw
        if contents["state.json"] is None:
            raise ValidationError("Backup has no desktop settings.")
        desired = _decode(contents["state.json"], "Backup settings")
        # Reconstruct a journal for this exact snapshot. Historical journals may
        # have pending observations; never replay them over a restored snapshot.
        plan = plan_sync(desired, None, cfg)
        if plan["conflicts"]:
            raise ConflictError("Backup requires conflict review.")
        views = snapshot_profiles(desired, cfg["profile_ids"])
        plan["journal"]["seen"] = views
        plan["journal"].update(target=str(home), source_fingerprint=_hash(contents["state.json"]),
                               pending=False, restored_at=datetime.now(timezone.utc).isoformat())
        before, _ = _stable_state(home)
        safety_backup = _commit_transaction(home, data, before, contents["state.json"], plan["journal"],
                                            is_app_running=is_app_running)
        return {"restored": True, "backup": str(folder),
                "safety_backup": str(safety_backup) if safety_backup else None}
