"""Conservative Windows process and current-user startup adapters."""
from __future__ import annotations

import csv
import ctypes
import hashlib
import io
import json
import os
from pathlib import Path
import subprocess
import sys
import time
import uuid

from .errors import BusyError, CompatibilityError, ValidationError


def _require_windows() -> None:
    if os.name != "nt":
        raise CompatibilityError("Live writes and watcher lifecycle require Windows.")


def app_running() -> bool:
    """Fail closed if process enumeration is unavailable or ambiguous."""
    _require_windows()
    try:
        result = subprocess.run(["tasklist.exe", "/FO", "CSV", "/NH"],
                                capture_output=True, text=True, timeout=10,
                                creationflags=subprocess.CREATE_NO_WINDOW)
        if result.returncode:
            raise BusyError("Cannot establish whether Codex desktop is closed.")
        rows = list(csv.reader(io.StringIO(result.stdout)))
        if not rows or any(len(row) != 5 or not row[1].isdigit() for row in rows):
            raise BusyError("Process enumeration returned an uncertain result.")
        names = {row[0].casefold() for row in rows}
        if names & {"chatgpt.exe", "codex-app.exe", "codex desktop.exe"}:
            return True
        if "codex.exe" not in names:
            return False
        # A resources/codex.exe app-server may outlive the desktop. Only this
        # positively identified backend is ignored; all other Codex images block.
        script = ("$ErrorActionPreference='Stop'; $blocked=$false; $uncertain=$false; "
                  "Get-CimInstance Win32_Process -Filter \"Name='codex.exe'\" | ForEach-Object { "
                  "if (-not $_.ExecutablePath -or -not $_.CommandLine) { $uncertain=$true } "
                  "elseif ($_.ExecutablePath -notmatch '(?i)[\\\\/]resources[\\\\/]codex\\.exe$' "
                  "-or $_.CommandLine -notmatch '(?i)(^|\\s)app-server(\\s|$)') { $blocked=$true } }; "
                  "@{running=$blocked;uncertain=$uncertain}|ConvertTo-Json -Compress")
        inspection = subprocess.run(["powershell.exe", "-NoProfile", "-NonInteractive", "-Command", script],
                                    capture_output=True, text=True, timeout=15,
                                    creationflags=subprocess.CREATE_NO_WINDOW)
        try:
            checked = json.loads(inspection.stdout)
        except ValueError as exc:
            raise BusyError("Cannot distinguish desktop and backend processes.") from exc
        if (inspection.returncode or not isinstance(checked, dict)
                or type(checked.get("running")) is not bool or checked.get("uncertain") is not False):
            raise BusyError("Cannot distinguish desktop and backend processes.")
        return checked["running"]
    except (OSError, subprocess.SubprocessError, csv.Error) as exc:
        raise BusyError("Cannot establish whether Codex desktop is closed.") from exc


def process_identity(pid: int) -> str | None:
    """Creation time protects lifecycle operations against PID reuse."""
    if type(pid) is not int or pid <= 0:
        return None
    if os.name != "nt":
        return None
    from ctypes import wintypes
    kernel = ctypes.WinDLL("kernel32", use_last_error=True)
    kernel.OpenProcess.argtypes = [wintypes.DWORD, wintypes.BOOL, wintypes.DWORD]
    kernel.OpenProcess.restype = wintypes.HANDLE
    kernel.GetProcessTimes.argtypes = [wintypes.HANDLE] + [ctypes.POINTER(wintypes.FILETIME)] * 4
    kernel.GetExitCodeProcess.argtypes = [wintypes.HANDLE, ctypes.POINTER(wintypes.DWORD)]
    kernel.CloseHandle.argtypes = [wintypes.HANDLE]
    handle = kernel.OpenProcess(0x1000, False, pid)
    if not handle:
        if ctypes.get_last_error() == 87:  # ERROR_INVALID_PARAMETER: PID no longer exists.
            return None
        raise BusyError("Watcher process identity is inaccessible or uncertain.")
    try:
        exit_code = wintypes.DWORD()
        times = [wintypes.FILETIME() for _ in range(4)]
        if not kernel.GetExitCodeProcess(handle, ctypes.byref(exit_code)):
            raise BusyError("Cannot query watcher process liveness.")
        if exit_code.value != 259:
            return None
        if not kernel.GetProcessTimes(handle, *(ctypes.byref(t) for t in times)):
            raise BusyError("Cannot query watcher process creation identity.")
        return str((times[0].dwHighDateTime << 32) | times[0].dwLowDateTime)
    finally:
        kernel.CloseHandle(handle)


def process_alive(pid: int) -> bool:
    return process_identity(pid) is not None


def legacy_watcher_running() -> bool:
    """Heuristic coexistence check; return no personal command lines to callers."""
    _require_windows()
    script = ("$ErrorActionPreference='Stop'; $n=@(Get-CimInstance Win32_Process | "
              "Where-Object { $_.ProcessId -ne $PID -and "
              "$_.Name -match '^(pythonw?|wscript|cscript|powershell|pwsh)(\\.exe)?$' -and "
              "$_.CommandLine -match '(?i)codex.*(sync|mirror)|(sync|mirror).*codex' -and "
              "$_.CommandLine -notmatch '(?i)(^|\\s)-m\\s+codex_local_sync(\\s|$)' }); $n.Count")
    try:
        result = subprocess.run(["powershell.exe", "-NoProfile", "-NonInteractive", "-Command", script],
                                capture_output=True, text=True, timeout=15,
                                creationflags=subprocess.CREATE_NO_WINDOW)
        if result.returncode or not result.stdout.strip().isdigit():
            raise BusyError("Cannot check for legacy helper coexistence.")
        return int(result.stdout.strip()) > 0
    except (OSError, subprocess.SubprocessError) as exc:
        raise BusyError("Cannot check for legacy helper coexistence.") from exc


def _watch_command(data_dir: Path, codex_home: Path) -> list[str]:
    executable = Path(sys.executable)
    windowless = executable.with_name("pythonw.exe")
    if windowless.is_file():
        executable = windowless
    command = [str(executable), "-m", "codex_local_sync", "--data-dir", str(data_dir.resolve()),
               "--codex-home", str(codex_home.resolve()), "watch"]
    if any(any(character in argument for character in "\r\n\0") for argument in command):
        raise ValidationError("Watcher paths cannot contain control characters.")
    return command


def launch_watcher(data_dir: Path, codex_home: Path) -> dict:
    _require_windows()
    if legacy_watcher_running():
        raise BusyError("A possible legacy Codex sync helper is running; stop or migrate it explicitly before starting this helper.")
    data_dir.mkdir(parents=True, exist_ok=True)
    launch_token = uuid.uuid4().hex
    with (data_dir / "watcher.log").open("ab") as log:
        child = subprocess.Popen(_watch_command(data_dir, codex_home) + ["--launch-token", launch_token], stdin=subprocess.DEVNULL,
                                 stdout=log, stderr=log, close_fds=True,
                                 creationflags=(subprocess.DETACHED_PROCESS | subprocess.CREATE_NO_WINDOW))
    deadline = time.monotonic() + 8
    while time.monotonic() < deadline:
        try:
            status = json.loads((data_dir / "watcher.json").read_text(encoding="utf-8"))
            if (isinstance(status, dict) and status.get("launch_token") == launch_token
                    and status.get("state") != "stopped" and status.get("identity")
                    and status.get("identity") == process_identity(status.get("pid"))):
                return {"started": True, "pid": status["pid"]}
        except (OSError, ValueError):
            pass
        if child.poll() is not None:
            raise BusyError("Watcher exited before ready; inspect watcher.log.")
        time.sleep(0.1)
    raise BusyError("Watcher readiness is uncertain; use status before retrying.")


def _startup_path(data_dir: Path) -> Path:
    _require_windows()
    appdata = os.environ.get("APPDATA")
    if not appdata:
        raise CompatibilityError("APPDATA is required for current-user startup.")
    suffix = hashlib.sha256(str(data_dir.resolve()).casefold().encode()).hexdigest()[:16]
    return Path(appdata) / "Microsoft/Windows/Start Menu/Programs/Startup" / f"codex-local-sync-{suffix}.vbs"


def check_startup(data_dir: Path, codex_home: Path) -> None:
    """Read-only preflight, also called before a --startup background launch."""
    path = _startup_path(data_dir)
    if legacy_watcher_running():
        raise BusyError("A possible legacy Codex sync helper is running; explicit migration is required.")
    if path.parent.exists():
        for entry in path.parent.iterdir():
            name = entry.name.casefold()
            if entry != path and "codex" in name and ("sync" in name or "mirror" in name):
                raise BusyError("Another Codex sync startup entry exists; explicit migration is required.")
    if path.exists():
        _owned_startup(data_dir, path)
    command = subprocess.list2cmdline(_watch_command(data_dir, codex_home))
    if "%" in command:
        raise ValidationError("Startup paths cannot contain percent signs because Windows expands environment variables.")


def _atomic_bytes(path: Path, content: bytes) -> None:
    temporary = path.with_name(path.name + "." + uuid.uuid4().hex + ".tmp")
    try:
        with temporary.open("xb") as stream:
            stream.write(content)
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(temporary, path)
    finally:
        temporary.unlink(missing_ok=True)


def install_startup(data_dir: Path, codex_home: Path) -> dict:
    check_startup(data_dir, codex_home)
    path = _startup_path(data_dir)
    command = subprocess.list2cmdline(_watch_command(data_dir, codex_home))
    content = ('\' Managed by codex-local-sync\r\nCreateObject("WScript.Shell").Run "'
               + command.replace('"', '""') + '", 0, False\r\n').encode("utf-16")
    manifest = data_dir / "startup.json"
    old_content = path.read_bytes() if path.exists() else None
    data_dir.mkdir(parents=True, exist_ok=True)
    path.parent.mkdir(parents=True, exist_ok=True)
    # Write ownership receipt first: interrupted installation remains removable.
    receipt = {"schema_version": 1, "path": str(path), "sha256": hashlib.sha256(content).hexdigest()}
    if old_content is not None:
        receipt["previous_sha256"] = hashlib.sha256(old_content).hexdigest()
    _atomic_bytes(manifest, json.dumps(receipt).encode("utf-8"))
    if old_content is None:
        # Exclusive creation refuses a concurrently introduced unrelated entry.
        with path.open("xb") as stream:
            stream.write(content)
            stream.flush()
            os.fsync(stream.fileno())
    else:
        _owned_startup(data_dir, path)
        _atomic_bytes(path, content)
    return {"startup": True}


def _owned_startup(data_dir: Path, path: Path) -> None:
    try:
        receipt = json.loads((data_dir / "startup.json").read_text(encoding="utf-8"))
        valid = (isinstance(receipt, dict) and receipt.get("schema_version") == 1
                 and receipt.get("path") == str(path)
                 and hashlib.sha256(path.read_bytes()).hexdigest() in
                 (receipt.get("sha256"), receipt.get("previous_sha256")))
    except (OSError, ValueError):
        valid = False
    if not valid:
        raise ValidationError("Startup entry ownership cannot be verified; left unchanged.")


def remove_startup(data_dir: Path) -> None:
    path = _startup_path(data_dir)
    if path.exists():
        _owned_startup(data_dir, path)
        path.unlink()
    (data_dir / "startup.json").unlink(missing_ok=True)
