from datetime import datetime
from pathlib import Path


ARTIFACTS_ROOT = Path("data/server/artifacts")
SUBMISSIONS_ROOT = Path("data/server/submissions")


def ensure_submission_directory(client_id: str) -> Path:
    destination = SUBMISSIONS_ROOT / client_id
    destination.mkdir(parents=True, exist_ok=True)
    return destination


def build_submission_path(client_id: str, original_name: str) -> Path:
    safe_name = _safe_filename(original_name)
    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    return ensure_submission_directory(client_id) / f"{timestamp}_{safe_name}"


def ensure_artifact_directory(client_id: str, artifact_kind: str) -> Path:
    destination = ARTIFACTS_ROOT / client_id / _safe_artifact_kind(artifact_kind)
    destination.mkdir(parents=True, exist_ok=True)
    return destination


def build_artifact_path(client_id: str, artifact_kind: str, original_name: str) -> Path:
    safe_name = _safe_filename(original_name)
    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    return ensure_artifact_directory(client_id, artifact_kind) / f"{timestamp}_{safe_name}"


def safe_relative_path(path: Path) -> str:
    try:
        return str(path.relative_to(Path.cwd()))
    except ValueError:
        return str(path)


def _safe_filename(name: str) -> str:
    candidate = Path(name).name.strip()
    if not candidate:
        return "submission.bin"
    return candidate


def _safe_artifact_kind(kind: str) -> str:
    cleaned = "".join(character if character.isalnum() or character in {"_", "-"} else "_" for character in kind.strip().lower())
    return cleaned or "artifact"
