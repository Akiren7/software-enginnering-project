"""
Shared protocol helpers for JSON message encoding/decoding.

Every message between server and client is a JSON object with:
  - "event": str   (e.g. "ping", "echo", "time", "welcome")
  - "data":  dict  (payload, varies per event)
"""

import hashlib
import json
import urllib.parse
from datetime import datetime, timezone


DECODE_ERROR = "__decode_error__"
INTEGRITY_FIELDS = {"seq", "session_id", "buffered", "queued_at"}


def _canonical_message(event: str, data: dict) -> str:
    return json.dumps(
        {"event": event, "data": data},
        sort_keys=True,
        separators=(",", ":"),
    )


def _message_checksum(event: str, data: dict) -> str:
    payload = _canonical_message(event, data).encode("utf-8")
    return hashlib.sha256(payload).hexdigest()


def _without_integrity_fields(data: dict) -> dict:
    """Return payload data without transport reliability metadata."""
    return {key: value for key, value in data.items() if key not in INTEGRITY_FIELDS}


def _merge_top_level_integrity(msg: dict, data: dict) -> dict:
    """Preserve known top-level reliability fields for downstream handlers."""
    merged = dict(data)
    for key in INTEGRITY_FIELDS:
        if key in msg and key not in merged:
            merged[key] = msg[key]
    return merged


def encode(event: str, data: dict | None = None) -> str:
    """Encode an event + data dict into a JSON string."""
    payload = data or {}
    return json.dumps(
        {
            "event": event,
            "data": payload,
            "checksum": _message_checksum(event, payload),
        }
    )


def decode(raw: str) -> tuple[str, dict]:
    """Decode a JSON string into (event, data)."""
    try:
        msg = json.loads(raw)
        event = msg["event"]
        data = msg.get("data", {})
        checksum = msg.get("checksum")
    except (json.JSONDecodeError, KeyError):
        return DECODE_ERROR, {"reason": "malformed message"}

    if not isinstance(data, dict):
        return DECODE_ERROR, {"reason": "message data must be a JSON object"}

    if not checksum:
        return DECODE_ERROR, {"reason": "missing message checksum"}

    expected_checksum = _message_checksum(event, data)
    if checksum == expected_checksum:
        return event, _merge_top_level_integrity(msg, data)

    stripped_data = _without_integrity_fields(data)
    if stripped_data != data and checksum == _message_checksum(event, stripped_data):
        return event, _merge_top_level_integrity(msg, data)

    return DECODE_ERROR, {"reason": "message checksum mismatch"}


def now_iso() -> str:
    """Current UTC time as ISO string."""
    return datetime.now(timezone.utc).isoformat()


def extract_client_uuid(ws_url: str) -> str:
    """Extracts the client UUID from the WebSocket URL."""
    try:
        parsed_url = urllib.parse.urlparse(ws_url)
        params = urllib.parse.parse_qs(parsed_url.query)
        # return the first 'id' value, or 'unknown'
        return params.get("id", ["unknown"])[0]
    except Exception:
        return "unknown"
