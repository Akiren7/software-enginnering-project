import json
import subprocess


USB_PROFILER_TIMEOUT_SECONDS = 5


def enrich_snapshot_for_macos(snapshot: dict) -> dict:
    enriched = dict(snapshot)
    enriched["usb_devices"] = collect_usb_devices_for_macos()
    return enriched


def collect_usb_devices_for_macos() -> list[dict]:
    try:
        result = subprocess.run(
            ["system_profiler", "SPUSBDataType", "-json"],
            capture_output=True,
            text=True,
            timeout=USB_PROFILER_TIMEOUT_SECONDS,
        )
    except Exception as exc:
        print(f"[HARDWARE] macOS USB scan failed: {exc}")
        return []

    if result.returncode != 0:
        stderr_text = (result.stderr or "").strip()
        if stderr_text:
            print(f"[HARDWARE] macOS USB scan failed: {stderr_text}")
        return []

    try:
        payload = json.loads(result.stdout or "{}")
    except json.JSONDecodeError as exc:
        print(f"[HARDWARE] macOS USB scan returned invalid JSON: {exc}")
        return []

    devices = []
    for root_item in payload.get("SPUSBDataType", []):
        _collect_usb_items(root_item, devices)
    return sorted(devices, key=_usb_sort_key)


def _collect_usb_items(item: dict, devices: list[dict]):
    child_items = item.get("_items") or []

    if _looks_like_usb_device(item):
        devices.append(
            {
                "name": item.get("_name", "") or "",
                "manufacturer": item.get("manufacturer", "") or "",
                "serial_number": item.get("serial_num", "") or "",
                "vendor_id": item.get("vendor_id", "") or "",
                "product_id": item.get("product_id", "") or "",
                "location_id": item.get("location_id", "") or "",
                "speed": item.get("speed", "") or "",
            }
        )

    for child_item in child_items:
        _collect_usb_items(child_item, devices)


def _looks_like_usb_device(item: dict) -> bool:
    device_keys = {"vendor_id", "product_id", "serial_num", "manufacturer", "location_id"}
    return any(item.get(key) for key in device_keys)


def _usb_sort_key(item: dict) -> tuple[str, str, str]:
    return (
        str(item.get("name", "")).lower(),
        str(item.get("location_id", "")).lower(),
        str(item.get("serial_number", "")).lower(),
    )
