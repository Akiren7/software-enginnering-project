import asyncio
import hashlib
import json
import os
import time
import zipfile
from pathlib import Path

import aiohttp


UPLOAD_ATTEMPTS = 2
CLIENT_LOGS_DIR = Path("data") / "logs" / "client"


def build_submission_bundle(
    session_uuid: str,
    student_file_path: str,
    process_report_path: str | None,
    replay_path: str | None,
    hardware_report_path: str | None,
) -> str:
    student_file = Path(student_file_path).expanduser().resolve()
    bundle_dir = Path("data") / "client" / session_uuid / "submission_bundle"
    bundle_dir.mkdir(parents=True, exist_ok=True)

    timestamp = time.strftime("%Y%m%d_%H%M%S")
    bundle_path = bundle_dir / f"submission_bundle_{timestamp}.zip"
    runtime_files = _collect_runtime_bundle_files(
        session_uuid,
        process_report_path,
        replay_path,
        hardware_report_path,
    )
    manifest = _build_bundle_manifest(student_file, runtime_files)

    with zipfile.ZipFile(bundle_path, "w", compression=zipfile.ZIP_DEFLATED) as archive:
        archive.write(student_file, arcname=f"student_submission/{student_file.name}")
        _write_manifest(archive, manifest)
        _add_runtime_files(archive, runtime_files)

    return str(bundle_path)


async def upload_runtime_artifact(
    base_url: str,
    session_uuid: str,
    artifact_path: str,
    artifact_kind: str,
    metadata: dict | None = None,
) -> dict:
    return await _upload_file(
        url=f"{base_url}/client/artifact",
        session_uuid=session_uuid,
        file_path=artifact_path,
        file_field_name="artifact",
        extra_fields={
            "kind": artifact_kind,
            "metadata": json.dumps(metadata or {}),
        },
    )


async def upload_submission_bundle(
    base_url: str,
    session_uuid: str,
    bundle_path: str,
) -> dict:
    return await _upload_file(
        url=f"{base_url}/exam/submission",
        session_uuid=session_uuid,
        file_path=bundle_path,
        file_field_name="archive",
    )


def file_sha256(file_path: str | Path) -> str:
    digest = hashlib.sha256()
    with Path(file_path).expanduser().resolve().open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


async def _upload_file(
    *,
    url: str,
    session_uuid: str,
    file_path: str,
    file_field_name: str,
    extra_fields: dict[str, str] | None = None,
) -> dict:
    target_file = Path(file_path).expanduser().resolve()
    if not target_file.exists() or not target_file.is_file():
        raise ValueError(f"Upload file does not exist: {target_file}")

    last_error: Exception | None = None
    for attempt in range(1, UPLOAD_ATTEMPTS + 1):
        try:
            return await _post_file(
                url=url,
                session_uuid=session_uuid,
                target_file=target_file,
                file_field_name=file_field_name,
                extra_fields=extra_fields or {},
            )
        except (aiohttp.ClientError, OSError, asyncio.TimeoutError) as exc:
            last_error = exc
            if attempt >= UPLOAD_ATTEMPTS:
                break
            await asyncio.sleep(0.5 * attempt)

    raise ValueError(f"Upload failed after {UPLOAD_ATTEMPTS} attempt(s): {last_error}")


async def _post_file(
    *,
    url: str,
    session_uuid: str,
    target_file: Path,
    file_field_name: str,
    extra_fields: dict[str, str],
) -> dict:
    checksum = file_sha256(target_file)
    timeout = aiohttp.ClientTimeout(total=120)

    async with aiohttp.ClientSession(timeout=timeout) as session:
        with target_file.open("rb") as file_handle:
            form = aiohttp.FormData()
            form.add_field(
                file_field_name,
                file_handle,
                filename=target_file.name,
                content_type="application/octet-stream",
            )
            form.add_field("sha256", checksum)
            for key, value in extra_fields.items():
                form.add_field(key, value)

            async with session.post(
                url,
                params={"id": session_uuid},
                data=form,
            ) as response:
                if response.status != 200:
                    body = await response.text()
                    raise ValueError(f"Upload failed ({response.status}): {body}")
                return await response.json()


def _build_bundle_manifest(
    student_file: Path,
    runtime_files: list[dict],
) -> dict:
    entries = [
        {
            "role": "student_submission",
            "name": student_file.name,
            "archive_path": f"student_submission/{student_file.name}",
            "size_bytes": student_file.stat().st_size,
            "sha256": file_sha256(student_file),
        }
    ]
    entries.extend(_manifest_entries_for_runtime_files(runtime_files))

    return {
        "created_at": time.strftime("%Y-%m-%d %H:%M:%S"),
        "entries": entries,
    }


def _write_manifest(archive: zipfile.ZipFile, manifest: dict):
    archive.writestr("manifest.json", json.dumps(manifest, indent=2))


def _collect_runtime_bundle_files(
    session_uuid: str,
    process_report_path: str | None,
    replay_path: str | None,
    hardware_report_path: str | None,
) -> list[dict]:
    runtime_files: list[dict] = []
    _append_runtime_file(
        runtime_files,
        role="requested_process_report",
        file_path=process_report_path,
        arcname="runtime/process_report_requested.json",
    )
    _append_runtime_file(
        runtime_files,
        role="continuous_process_log",
        file_path=_process_log_path(session_uuid),
        arcname="runtime/processes.jsonl",
    )
    _append_runtime_file(
        runtime_files,
        role="final_replay",
        file_path=replay_path,
        arcname=_runtime_replay_name(replay_path),
    )
    _append_runtime_file(
        runtime_files,
        role="hardware_snapshot",
        file_path=hardware_report_path,
        arcname="runtime/hardware_snapshot.json",
    )
    _append_runtime_file(
        runtime_files,
        role="hardware_change_log",
        file_path=_hardware_log_path(session_uuid),
        arcname="runtime/hardware_changes.jsonl",
    )
    _append_runtime_file(
        runtime_files,
        role="client_cli_log",
        file_path=_latest_client_log("client_cli_"),
        arcname="runtime/logs/client_cli.jsonl",
    )
    _append_runtime_file(
        runtime_files,
        role="client_gui_log",
        file_path=_latest_client_log("client_gui_"),
        arcname="runtime/logs/client_gui.jsonl",
    )
    return runtime_files


def _append_runtime_file(
    runtime_files: list[dict],
    *,
    role: str,
    file_path: str | Path | None,
    arcname: str | None,
):
    if not file_path or not arcname:
        return

    source = Path(file_path)
    if not source.exists() or not source.is_file():
        return

    runtime_files.append(
        {
            "role": role,
            "path": source,
            "arcname": arcname,
        }
    )


def _add_runtime_files(archive: zipfile.ZipFile, runtime_files: list[dict]):
    for runtime_file in runtime_files:
        archive.write(runtime_file["path"], arcname=runtime_file["arcname"])


def _manifest_entries_for_runtime_files(runtime_files: list[dict]) -> list[dict]:
    entries = []
    for runtime_file in runtime_files:
        source = runtime_file["path"]
        entries.append(
            {
                "role": runtime_file["role"],
                "name": source.name,
                "archive_path": runtime_file["arcname"],
                "size_bytes": source.stat().st_size,
                "sha256": file_sha256(source),
            }
        )
    return entries


def _process_log_path(session_uuid: str) -> Path:
    return Path("data") / "client" / session_uuid / "processes.jsonl"


def _hardware_log_path(session_uuid: str) -> Path:
    return Path("data") / "client" / session_uuid / "hardware_changes.jsonl"


def _latest_client_log(prefix: str) -> Path | None:
    if not CLIENT_LOGS_DIR.exists():
        return None

    candidates = sorted(
        CLIENT_LOGS_DIR.glob(f"{prefix}*"),
        key=lambda path: path.stat().st_mtime,
        reverse=True,
    )
    if not candidates:
        return None
    return candidates[0]


def _runtime_replay_name(replay_path: str | None) -> str | None:
    if not replay_path:
        return None
    replay_file = Path(replay_path)
    return f"runtime/{replay_file.name}"
