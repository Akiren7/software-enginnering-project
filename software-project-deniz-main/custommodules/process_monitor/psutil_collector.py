import psutil


PROCESS_FIELDS = ("pid", "name")


def get_processes_via_psutil() -> set[tuple[int, str]]:
    processes = set()
    try:
        iterator = psutil.process_iter(PROCESS_FIELDS)
        for process in iterator:
            try:
                pid = process.info.get("pid")
                name = process.info.get("name")
                if pid is None or not name:
                    continue
                processes.add((int(pid), str(name)))
            except (psutil.NoSuchProcess, psutil.AccessDenied, psutil.ZombieProcess):
                continue
    except (psutil.Error, PermissionError, OSError) as e:
        print(f"[PROCESS] psutil process listing failed: {e}")
    return processes
