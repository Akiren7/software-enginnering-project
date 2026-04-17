"""
Shared protocol helpers for JSON message encoding/decoding.

Every message between server and client is a JSON object with:
  - "event": str   (e.g. "ping", "echo", "time", "welcome")
  - "data":  dict  (payload, varies per event)
"""

import json
import urllib.parse
from datetime import datetime, timezone


def encode(event: str, data: dict | None = None) -> str:
    """Encode an event + data dict into a JSON string."""
    return json.dumps({"event": event, "data": data or {}})


def decode(raw: str) -> tuple[str, dict]:
    """Decode a JSON string into (event, data). Returns ("error", {}) on failure."""
    try:
        msg = json.loads(raw)
        return msg["event"], msg.get("data", {})
    except (json.JSONDecodeError, KeyError):
        return "error", {"reason": "malformed message"}


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
