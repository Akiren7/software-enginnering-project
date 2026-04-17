import platform
import socket

import psutil


def collect_hardware_snapshot() -> dict:
    snapshot = {
        "platform": platform.system().lower(),
        "computer_name": _computer_name(),
        "system": _collect_system_summary(),
        "disks": _collect_disk_entries(),
        "network_interfaces": _collect_network_interfaces(),
        "battery": _collect_battery_summary(),
    }
    return snapshot


def _computer_name() -> str:
    try:
        return socket.gethostname()
    except Exception:
        return "unknown"


def _collect_system_summary() -> dict:
    virtual_memory = _safe_virtual_memory()
    return {
        "machine": platform.machine() or "",
        "processor": platform.processor() or "",
        "architecture": platform.architecture()[0],
        "cpu_logical": int(psutil.cpu_count() or 0),
        "cpu_physical": int(psutil.cpu_count(logical=False) or 0),
        "memory_total_bytes": int(getattr(virtual_memory, "total", 0)),
        "boot_time": _safe_boot_time(),
    }


def _safe_virtual_memory():
    try:
        return psutil.virtual_memory()
    except Exception:
        return type("MemoryInfo", (), {"total": 0})()


def _safe_boot_time() -> int:
    try:
        return int(psutil.boot_time() or 0)
    except Exception:
        return 0


def _collect_disk_entries() -> list[dict]:
    entries = []
    for partition in _safe_disk_partitions():
        usage = _safe_disk_usage(partition.mountpoint)
        entries.append(
            {
                "device": partition.device or "",
                "mountpoint": partition.mountpoint or "",
                "fstype": partition.fstype or "",
                "opts": partition.opts or "",
                "total_bytes": int(getattr(usage, "total", 0)),
            }
        )

    return sorted(entries, key=lambda entry: (entry["device"], entry["mountpoint"]))


def _safe_disk_partitions():
    try:
        return psutil.disk_partitions(all=True)
    except Exception:
        return []


def _safe_disk_usage(mountpoint: str):
    try:
        return psutil.disk_usage(mountpoint)
    except Exception:
        return type("DiskUsage", (), {"total": 0})()


def _collect_network_interfaces() -> list[dict]:
    interface_stats = _safe_net_if_stats()
    interface_addresses = _safe_net_if_addrs()
    entries = []

    for interface_name in sorted(interface_addresses):
        entries.append(
            {
                "name": interface_name,
                "is_up": bool(getattr(interface_stats.get(interface_name), "isup", False)),
                "mtu": int(getattr(interface_stats.get(interface_name), "mtu", 0) or 0),
                "mac": _mac_address(interface_addresses[interface_name]),
                "ipv4": _ip_addresses(interface_addresses[interface_name], family_names={"AF_INET", "AddressFamily.AF_INET"}),
                "ipv6": _ip_addresses(interface_addresses[interface_name], family_names={"AF_INET6", "AddressFamily.AF_INET6"}),
            }
        )

    return entries


def _safe_net_if_stats():
    try:
        return psutil.net_if_stats()
    except Exception:
        return {}


def _safe_net_if_addrs():
    try:
        return psutil.net_if_addrs()
    except Exception:
        return {}


def _mac_address(addresses) -> str:
    for address in addresses:
        family_name = str(address.family)
        if family_name in {"AF_LINK", "AddressFamily.AF_LINK", "AF_PACKET", "AddressFamily.AF_PACKET"}:
            return address.address or ""
    return ""


def _ip_addresses(addresses, *, family_names: set[str]) -> list[str]:
    results = []
    for address in addresses:
        if str(address.family) not in family_names:
            continue
        if address.address:
            results.append(address.address)
    return sorted(results)


def _collect_battery_summary() -> dict | None:
    try:
        battery = psutil.sensors_battery()
    except Exception:
        return None

    if battery is None:
        return None

    return {
        "percent": float(getattr(battery, "percent", 0.0) or 0.0),
        "power_plugged": bool(getattr(battery, "power_plugged", False)),
    }
