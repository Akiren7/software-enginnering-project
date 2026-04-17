import os


WINDOWS_DRIVE_TYPES = {
    0: "unknown",
    1: "no_root_dir",
    2: "removable",
    3: "fixed",
    4: "remote",
    5: "cdrom",
    6: "ramdisk",
}


def enrich_snapshot_for_windows(snapshot: dict) -> dict:
    enriched = dict(snapshot)
    enriched["disks"] = _enrich_disks(snapshot.get("disks", []))
    return enriched


def _enrich_disks(disks: list[dict]) -> list[dict]:
    enriched = []
    for disk in disks:
        drive_type = _drive_type_for_path(disk.get("mountpoint", ""))
        enriched_disk = dict(disk)
        enriched_disk["drive_type"] = drive_type
        enriched_disk["is_removable"] = drive_type == "removable"
        enriched.append(enriched_disk)
    return enriched


def _drive_type_for_path(path: str) -> str:
    try:
        import ctypes
    except Exception:
        return "unknown"

    drive_root = _drive_root(path)
    if not drive_root:
        return "unknown"

    try:
        drive_type = int(ctypes.windll.kernel32.GetDriveTypeW(drive_root))
    except Exception:
        return "unknown"
    return WINDOWS_DRIVE_TYPES.get(drive_type, "unknown")


def _drive_root(path: str) -> str:
    if not path:
        return ""
    drive, _ = os.path.splitdrive(path)
    if not drive:
        return ""
    return drive + "\\"
