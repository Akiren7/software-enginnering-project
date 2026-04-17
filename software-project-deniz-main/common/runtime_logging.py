import asyncio
import hashlib
import json
import re
import sys
import threading
import traceback
from datetime import datetime
from pathlib import Path


TAG_PATTERN = re.compile(r"^\[([^\]]+)\]\s*")


def _timestamp() -> str:
    return datetime.now().astimezone().isoformat()


def _checksum_for_entry(process_name: str, stream_name: str, message: str) -> str:
    payload = json.dumps(
        {
            "process": process_name,
            "stream": stream_name,
            "message": message,
        },
        sort_keys=True,
        separators=(",", ":"),
    ).encode("utf-8")
    return hashlib.sha256(payload).hexdigest()


def _normalize_token(value: str) -> str:
    normalized = re.sub(r"[^a-z0-9]+", "_", value.lower()).strip("_")
    return normalized or "message"


def _normalize_optional_tag(tag: str | None) -> str | None:
    if not tag:
        return None
    normalized = re.sub(r"[^a-z0-9]+", "_", tag.lower()).strip("_")
    return normalized or None


def _extract_tag(message: str) -> tuple[str | None, str]:
    match = TAG_PATTERN.match(message)
    if not match:
        return None, message
    return match.group(1).strip(), message[match.end():].strip()


def _level_for_entry(stream_name: str, tag: str | None, content: str) -> str:
    lowered = content.lower()
    normalized_tag = _normalize_token(tag or "")

    if normalized_tag in {"error", "fatal", "exception", "asyncio"}:
        return "error"
    if normalized_tag in {"warn", "warning"}:
        return "warning"
    if "traceback" in lowered:
        return "error"
    if stream_name == "stderr":
        return "error"
    return "info"


def _component_for_entry(process_name: str, tag: str | None, content: str) -> str:
    component_map = {
        "asyncio": "asyncio",
        "check": "startup",
        "direct": "network",
        "discovery": "discovery",
        "error": "runtime",
        "exam": "exam",
        "exception": "runtime",
        "fatal": "runtime",
        "gui": "gui",
        "log": "runtime_logging",
        "login": "auth",
        "ping": "websocket",
        "process": "process_monitor",
        "recorder": "replay_recorder",
        "reset": "server_state",
        "submission": "submission",
        "artifact": "artifact_upload",
        "ws": "websocket",
    }

    normalized_tag = _normalize_token(tag or "")
    if normalized_tag in component_map:
        return component_map[normalized_tag]

    lowered = content.lower()
    if "traceback" in lowered or "exception" in lowered:
        return "runtime"
    return process_name


def _event_type_for_entry(tag: str | None, content: str, level: str) -> str:
    normalized_tag = _normalize_token(tag or "")
    if normalized_tag:
        tag_event_map = {
            "artifact": "artifact_upload",
            "asyncio": "asyncio_exception",
            "check": "startup_check",
            "direct": "direct_connect",
            "discovery": "discovery",
            "error": "error",
            "exam": "exam_state",
            "exception": "exception",
            "fatal": "fatal_error",
            "gui": "gui_action",
            "log": "logging_started",
            "login": "login",
            "ping": "ping",
            "process": "process_monitor",
            "recorder": "replay",
            "reset": "reset",
            "submission": "submission",
            "ws": "websocket",
        }
        if normalized_tag in tag_event_map:
            base_event = tag_event_map[normalized_tag]
            keyword_event = _keyword_event_type(content)
            if keyword_event != "message":
                return f"{base_event}_{keyword_event}"
            return base_event

    lowered = content.lower()
    if "traceback" in lowered:
        return "traceback"
    if level == "error":
        return "error"
    return _keyword_event_type(content)


def _keyword_event_type(content: str) -> str:
    lowered = content.lower()
    keyword_map = [
        ("checksum", "checksum"),
        ("reconnect", "reconnect"),
        ("retry", "retry"),
        ("connected", "connect"),
        ("disconnected", "disconnect"),
        ("upload", "upload"),
        ("submission", "submission"),
        ("start", "start"),
        ("finish", "finish"),
        ("save", "save"),
        ("saved", "save"),
        ("sync", "sync"),
        ("discover", "discover"),
        ("login", "login"),
        ("banned", "ban"),
        ("kicked", "kick"),
    ]
    for keyword, event_type in keyword_map:
        if keyword in lowered:
            return event_type
    return "message"


def _build_log_entry(process_name: str, stream_name: str, message: str) -> dict:
    tag, content = _extract_tag(message)
    level = _level_for_entry(stream_name, tag, content)
    normalized_tag = _normalize_optional_tag(tag)
    return {
        "timestamp": _timestamp(),
        "process": process_name,
        "stream": stream_name,
        "level": level,
        "component": _component_for_entry(process_name, tag, content),
        "event_type": _event_type_for_entry(tag, content, level),
        "tag": normalized_tag,
        "message": message,
        "checksum": _checksum_for_entry(process_name, stream_name, message),
    }


class JsonLineLogWriter:
    def __init__(self, log_path: Path, process_name: str):
        self.log_path = log_path
        self.process_name = process_name
        self._stream = log_path.open("a", buffering=1, encoding="utf-8")

    def write_entry(self, stream_name: str, message: str):
        entry = _build_log_entry(self.process_name, stream_name, message)
        self._stream.write(json.dumps(entry, ensure_ascii=True) + "\n")

    def flush(self):
        self._stream.flush()


class TeeStream:
    def __init__(self, original_stream, log_writer: JsonLineLogWriter, stream_name: str):
        self.original_stream = original_stream
        self.log_writer = log_writer
        self.stream_name = stream_name
        self.encoding = getattr(original_stream, "encoding", "utf-8")
        self._line_buffer = ""

    def write(self, data):
        if not data:
            return 0
        self.original_stream.write(data)
        self._line_buffer += data
        self._flush_complete_lines()
        return len(data)

    def flush(self):
        self._flush_remainder()
        self.original_stream.flush()
        self.log_writer.flush()

    def isatty(self):
        return getattr(self.original_stream, "isatty", lambda: False)()

    def fileno(self):
        return self.original_stream.fileno()

    def _flush_complete_lines(self):
        while True:
            newline_index = self._line_buffer.find("\n")
            if newline_index < 0:
                return

            line = self._line_buffer[:newline_index]
            self._line_buffer = self._line_buffer[newline_index + 1 :]
            self.log_writer.write_entry(self.stream_name, line)

    def _flush_remainder(self):
        if not self._line_buffer:
            return
        self.log_writer.write_entry(self.stream_name, self._line_buffer)
        self._line_buffer = ""


def _log_exception(prefix: str, exc_type, exc_value, exc_traceback):
    print(prefix, file=sys.stderr)
    traceback.print_exception(exc_type, exc_value, exc_traceback, file=sys.stderr)


def setup_runtime_logging(
    process_name: str,
    log_dir: Path,
    *,
    capture_stdout: bool = True,
    capture_stderr: bool = True,
) -> Path:
    log_dir.mkdir(parents=True, exist_ok=True)
    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    log_path = log_dir / f"{process_name}_{timestamp}.jsonl"
    log_writer = JsonLineLogWriter(log_path, process_name)

    if capture_stdout:
        sys.stdout = TeeStream(sys.stdout, log_writer, "stdout")
    if capture_stderr:
        sys.stderr = TeeStream(sys.stderr, log_writer, "stderr")

    def excepthook(exc_type, exc_value, exc_traceback):
        if issubclass(exc_type, KeyboardInterrupt):
            return
        _log_exception("[EXCEPTION] Unhandled exception", exc_type, exc_value, exc_traceback)

    def thread_excepthook(args):
        _log_exception(
            f"[EXCEPTION] Unhandled thread exception in {args.thread.name}",
            args.exc_type,
            args.exc_value,
            args.exc_traceback,
        )

    sys.excepthook = excepthook
    threading.excepthook = thread_excepthook

    target_stream = sys.stdout if capture_stdout else sys.stderr
    print(f"[LOG] Writing runtime log to {log_path}", file=target_stream)
    return log_path


def install_asyncio_exception_logging(loop: asyncio.AbstractEventLoop):
    def handler(_loop, context):
        message = context.get("message", "Unhandled asyncio exception")
        print(f"[ASYNCIO] {message}", file=sys.stderr)

        exception = context.get("exception")
        if exception:
            traceback.print_exception(
                type(exception),
                exception,
                exception.__traceback__,
                file=sys.stderr,
            )

    loop.set_exception_handler(handler)
