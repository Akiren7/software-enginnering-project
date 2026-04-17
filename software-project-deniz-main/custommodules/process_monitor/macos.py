import os
import subprocess

from .psutil_collector import get_processes_via_psutil


def get_processes_for_macos() -> set[tuple[int, str]]:
    processes = get_processes_via_psutil()
    if processes:
        return processes
    return _get_processes_via_ps()


def _get_processes_via_ps() -> set[tuple[int, str]]:
    try:
        result = subprocess.run(
            ["ps", "-axo", "pid=,comm="],
            capture_output=True,
            text=True,
            check=True,
        )
    except (FileNotFoundError, subprocess.SubprocessError, PermissionError, OSError) as e:
        print(f"[PROCESS] macOS fallback process listing failed: {e}")
        return set()

    processes = set()
    for line in result.stdout.splitlines():
        process_entry = _parse_ps_line(line)
        if process_entry:
            processes.add(process_entry)
    return processes


def _parse_ps_line(line: str) -> tuple[int, str] | None:
    stripped = line.strip()
    if not stripped:
        return None

    parts = stripped.split(None, 1)
    if len(parts) != 2:
        return None

    pid_text, command = parts
    try:
        pid = int(pid_text)
    except ValueError:
        return None

    process_name = os.path.basename(command.strip())
    if not process_name:
        return None

    return pid, process_name
