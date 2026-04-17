import json
import hashlib
import os
import tarfile
import uuid
import zipfile
from pathlib import Path
from aiohttp import web, WSMsgType

from common import protocol, events
from .state import state
from .submissions import build_artifact_path, build_submission_path, safe_relative_path


def _json_error(message: str, status: int) -> web.Response:
    return web.json_response({"error": message}, status=status)


def _validate_login_payload(data: dict) -> tuple[str | None, str | None]:
    login_id = data.get("login_id")
    password = data.get("password")
    return login_id, password


def _relay_client_message_to_gui(client_id: str, message: dict):
    gui_process = state.get_gui_process()
    if not gui_process:
        return

    try:
        payload = json.dumps(
            {"type": "client_message", "uuid": client_id, "text": message}
        )
        gui_process.stdin.write(payload + "\n")
        gui_process.stdin.flush()
    except Exception:
        pass


def _relay_text_to_gui(client_id: str, text: str):
    _relay_client_message_to_gui(client_id, text)


def _register_new_user(login_id: str, password: str) -> web.Response:
    new_uuid = str(uuid.uuid4())
    state.users_db[login_id] = {
        "password": password,
        "uuid": new_uuid,
        "time_spent_seconds": 0,
        "exam_started": False,
        "exam_finished": False,
        "extra_time_seconds": 0,
        "banned": False,
        "kick_count": 0,
        "last_action": "",
    }
    state.ensure_user_defaults(state.users_db[login_id])
    state.save_users()
    print(f"[+] New valid user registered: {login_id} -> {new_uuid}")
    return web.json_response({"status": "ok", "uuid": new_uuid})


def _remaining_seconds(request: web.Request, user: dict) -> int:
    exam_duration_sec = request.app["exam_duration"] * 60
    extra_time_sec = int(user.get("extra_time_seconds", 0))
    time_spent_seconds = user.get("time_spent_seconds", 0)
    return max(0, exam_duration_sec + extra_time_sec - int(time_spent_seconds))


def _client_ip(request: web.Request) -> str:
    forwarded_for = request.headers.get("X-Forwarded-For")
    if forwarded_for:
        return forwarded_for.split(",")[0].strip()

    transport = request.transport
    if transport:
        peername = transport.get_extra_info("peername")
        if isinstance(peername, (tuple, list)) and peername:
            return str(peername[0])

    return request.remote or "unknown"


def _user_has_submission(user: dict) -> bool:
    return bool(user.get("submitted_at"))


def _user_needs_submission(user: dict) -> bool:
    return (
        user.get("exam_started", False)
        and user.get("exam_finished", False)
        and not _user_has_submission(user)
    )


def _login_block_reason(request: web.Request, user: dict | None) -> str | None:
    if user and _user_has_submission(user):
        return "Submission already received for this user."

    if request.app.get("exam_phase") != "finished":
        return None

    if not user:
        return "Exam has already finished."
    if not user.get("exam_started", False):
        return "Exam has already finished."
    return None


def _is_supported_archive(archive_path: Path) -> bool:
    return zipfile.is_zipfile(archive_path) or tarfile.is_tarfile(archive_path)


def _remove_file_if_present(path: Path):
    try:
        if path.exists():
            path.unlink()
    except Exception:
        pass


def _file_sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as file_handle:
        for chunk in iter(lambda: file_handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _checksum_matches(expected_checksum: str | None, path: Path) -> bool:
    if not expected_checksum:
        return False
    return _file_sha256(path) == expected_checksum


async def _save_multipart_file(
    file_part,
    destination: Path,
    *,
    max_bytes: int,
) -> tuple[int, Exception | None]:
    bytes_written = 0
    try:
        with destination.open("wb") as output:
            while True:
                chunk = await file_part.read_chunk()
                if not chunk:
                    break
                bytes_written += len(chunk)
                if bytes_written > max_bytes:
                    raise ValueError(f"upload exceeds limit of {max_bytes} bytes")
                output.write(chunk)
        return bytes_written, None
    except Exception as exc:
        _remove_file_if_present(destination)
        return 0, exc


async def _read_optional_field(reader, expected_name: str) -> str:
    part = await reader.next()
    if part is None or part.name != expected_name:
        return ""
    return await part.text()


async def _handle_ping_event(ws: web.WebSocketResponse, client_id: str, data: dict):
    await ws.send_str(events.echo(data, protocol.now_iso()))
    short_id = client_id[:8]
    print(f"[{short_id}] PING: {data}")
    _relay_client_message_to_gui(client_id, data)


def _handle_client_info(client_id: str, data: dict):
    computer_name = str(data.get("computer_name", "")).strip()
    if not computer_name:
        return

    client_data = state.clients.get(client_id)
    if client_data is not None:
        client_data["computer_name"] = computer_name

    _, user = state.find_user_by_uuid(client_id)
    if user is not None:
        user["computer_name"] = computer_name
        state.save_users()


async def _handle_process_catch_event(
    ws: web.WebSocketResponse,
    client_id: str,
    data: dict,
):
    matches = data.get("matches", [])
    if not isinstance(matches, list):
        await ws.send_str(events.error("Invalid process catch payload."))
        return

    login_id, user = state.find_user_by_uuid(client_id)
    if not user:
        return

    blacklist_names = {entry.lower() for entry in state.process_blacklist}
    cleaned_matches = []
    seen_match_keys = set()
    for match in matches:
        if not isinstance(match, dict):
            continue
        pid = int(match.get("pid", 0) or 0)
        name = str(match.get("name", "")).strip()
        if not name:
            continue
        normalized_name = Path(name).name.lower()
        if normalized_name not in blacklist_names:
            continue
        match_key = (pid, normalized_name)
        if match_key in seen_match_keys:
            continue
        seen_match_keys.add(match_key)
        cleaned_matches.append({"pid": pid, "name": name})
        if len(cleaned_matches) >= 50:
            break

    if not cleaned_matches:
        return

    user["blacklist_catch_count"] = int(user.get("blacklist_catch_count", 0)) + len(cleaned_matches)
    user["last_blacklist_match"] = [match["name"] for match in cleaned_matches]
    user["last_action"] = "Blacklist catch"
    state.save_users()

    match_text = ", ".join(f"{match['name']} (pid {match['pid']})" for match in cleaned_matches)
    version = str(data.get("blacklist_version", "0"))
    print(f"[PROCESS] Blacklist catch from {login_id} ({client_id}): {match_text} [v{version}]")
    _relay_text_to_gui(client_id, f"[BLACKLIST] {match_text} [v{version}]")


async def _handle_start_exam(
    ws: web.WebSocketResponse,
    request: web.Request,
    client_id: str,
):
    _, user = state.find_user_by_uuid(client_id)
    if not user:
        return
    if _user_has_submission(user):
        await ws.send_str(events.error("Submission already received for this user."))
        return
    if user.get("exam_finished", False):
        await ws.send_str(events.error("Exam has already finished."))
        return
    if user.get("exam_started", False):
        await ws.send_str(events.sync_time(_remaining_seconds(request, user)))
        return

    exam_phase = request.app.get("exam_phase", "waiting")
    if exam_phase != "running":
        if exam_phase == "finished":
            await ws.send_str(events.error("Exam has already finished."))
        else:
            await ws.send_str(events.error("Exam is not started yet."))
        return

    user["exam_started"] = True
    user["last_action"] = "Started"
    state.save_users()
    print(f"[EXAM] Client {client_id} started their exam.")
    await ws.send_str(events.sync_time(_remaining_seconds(request, user)))


# -- HTTP Routes -----------------------------------------------------------
async def health(request: web.Request) -> web.Response:
    return web.json_response({
        "status": "ok",
        "server_id": request.app["server_id"],
        "clients_connected": len(state.clients),
    })

async def login_handler(request: web.Request) -> web.Response:
    try:
        data = await request.json()
    except json.JSONDecodeError:
        return _json_error("Invalid JSON", 400)

    login_id, password = _validate_login_payload(data)
    if not login_id or not password:
        return _json_error("login_id and password required", 400)

    if login_id not in state.allowed_users:
        return _json_error("User is not allowed to take this exam.", 403)

    if state.allowed_users[login_id] != password:
        return _json_error("Invalid credentials provided.", 401)

    user = state.users_db.get(login_id)
    block_reason = _login_block_reason(request, user)
    if block_reason:
        return _json_error(block_reason, 403 if "finished" in block_reason.lower() else 409)

    if not user:
        return _register_new_user(login_id, password)
    state.ensure_user_defaults(user)
    if user.get("banned", False):
        return _json_error("This user is banned.", 403)

    if user["password"] != password:
        return _json_error("Invalid stored credentials", 401)

    if user["uuid"] in state.clients:
        return _json_error("This login is already active on another client.", 409)

    return web.json_response({"status": "ok", "uuid": user["uuid"]})


async def exam_config(request: web.Request) -> web.Response:
    app = request.app
    return web.json_response({
        "exam_duration_seconds": app["exam_duration"] * 60,
        "has_files": app["exam_files"] is not None
    })

async def exam_files(request: web.Request) -> web.Response:
    app = request.app
    path = app["exam_files"]
    if not path or not os.path.exists(path):
        return web.Response(status=404, text="No exam files available")
    
    if os.path.isdir(path):
        return web.Response(status=400, text="Directory serving not implemented, please provide a .zip file")
        
    return web.FileResponse(path)


async def exam_submission(request: web.Request) -> web.Response:
    client_id = request.query.get("id", "").strip()
    if not client_id or not state.is_valid_session_uuid(client_id):
        return web.json_response({"error": "Invalid or missing session ID."}, status=401)

    login_id, user = state.find_user_by_uuid(client_id)
    if not user:
        return web.json_response({"error": "Unknown client."}, status=404)

    state.ensure_user_defaults(user)
    if user.get("banned", False):
        return web.json_response({"error": "This user is banned."}, status=403)
    if not user.get("exam_started", False):
        return web.json_response({"error": "Exam has not started for this client."}, status=409)
    if _user_has_submission(user):
        return web.json_response({"error": "Submission already received for this user."}, status=409)

    reader = await request.multipart()
    file_part = await reader.next()
    if file_part is None or file_part.name != "archive" or not file_part.filename:
        return web.json_response({"error": "A multipart field named 'archive' is required."}, status=400)
    destination = build_submission_path(client_id, file_part.filename)
    bytes_written, error = await _save_multipart_file(
        file_part,
        destination,
        max_bytes=int(request.app["max_submission_bytes"]),
    )
    if error:
        return web.json_response({"error": f"Failed to save submission: {error}"}, status=500)
    expected_checksum = await _read_optional_field(reader, "sha256")

    if bytes_written <= 0:
        _remove_file_if_present(destination)
        return web.json_response({"error": "Uploaded submission bundle is empty."}, status=400)

    if not _is_supported_archive(destination):
        _remove_file_if_present(destination)
        return web.json_response({"error": "Uploaded file is not a supported ZIP or TAR archive."}, status=400)

    if not _checksum_matches(expected_checksum, destination):
        _remove_file_if_present(destination)
        return web.json_response({"error": "Uploaded submission checksum mismatch."}, status=400)

    user["exam_finished"] = True
    user["submitted_at"] = protocol.now_iso()
    user["submission_name"] = Path(file_part.filename).name
    user["submission_path"] = safe_relative_path(destination)
    user["submission_size_bytes"] = bytes_written
    user["last_action"] = "Submitted file"
    state.save_users()

    print(
        f"[SUBMISSION] {login_id} ({client_id}) uploaded "
        f"{user['submission_name']} -> {user['submission_path']}"
    )
    return web.json_response(
        {
            "status": "ok",
            "message": "Submission uploaded successfully.",
            "path": user["submission_path"],
            "size_bytes": bytes_written,
        }
    )


async def client_artifact_upload(request: web.Request) -> web.Response:
    client_id = request.query.get("id", "").strip()
    if not client_id or not state.is_valid_session_uuid(client_id):
        return web.json_response({"error": "Invalid or missing session ID."}, status=401)

    login_id, user = state.find_user_by_uuid(client_id)
    if not user:
        return web.json_response({"error": "Unknown client."}, status=404)

    state.ensure_user_defaults(user)
    if user.get("banned", False):
        return web.json_response({"error": "This user is banned."}, status=403)

    reader = await request.multipart()
    file_part = await reader.next()
    if file_part is None or file_part.name != "artifact" or not file_part.filename:
        return web.json_response({"error": "A multipart field named 'artifact' is required."}, status=400)

    destination = build_artifact_path(client_id, "artifact", file_part.filename)
    bytes_written, error = await _save_multipart_file(
        file_part,
        destination,
        max_bytes=int(request.app["max_artifact_bytes"]),
    )
    if error:
        return web.json_response({"error": f"Failed to save artifact: {error}"}, status=500)
    expected_checksum = await _read_optional_field(reader, "sha256")
    artifact_kind = await _read_optional_field(reader, "kind")
    metadata_text = await _read_optional_field(reader, "metadata")
    artifact_kind = artifact_kind.strip() or "artifact"

    if bytes_written <= 0:
        _remove_file_if_present(destination)
        return web.json_response({"error": "Uploaded artifact is empty."}, status=400)

    if not _checksum_matches(expected_checksum, destination):
        _remove_file_if_present(destination)
        return web.json_response({"error": "Uploaded artifact checksum mismatch."}, status=400)

    final_destination = build_artifact_path(client_id, artifact_kind, file_part.filename)
    final_destination.parent.mkdir(parents=True, exist_ok=True)
    if final_destination != destination:
        final_destination = destination.replace(final_destination)
    else:
        final_destination = destination

    metadata = {}
    if metadata_text:
        try:
            metadata = json.loads(metadata_text)
        except json.JSONDecodeError:
            metadata = {"raw_metadata": metadata_text}

    metadata_path = final_destination.with_suffix(final_destination.suffix + ".json")
    metadata_path.write_text(
        json.dumps(
            {
                "client_id": client_id,
                "login_id": login_id,
                "kind": artifact_kind,
                "saved_at": protocol.now_iso(),
                "path": safe_relative_path(final_destination),
                "size_bytes": bytes_written,
                "sha256": expected_checksum,
                "metadata": metadata,
            },
            indent=2,
        )
    )

    print(
        f"[ARTIFACT] {login_id} ({client_id}) uploaded {artifact_kind} -> "
        f"{safe_relative_path(final_destination)}"
    )
    return web.json_response(
        {
            "status": "ok",
            "message": "Artifact uploaded successfully.",
            "path": safe_relative_path(final_destination),
            "size_bytes": bytes_written,
        }
    )

# -- WebSocket Handler -----------------------------------------------------
async def websocket_handler(request: web.Request) -> web.WebSocketResponse:
    client_id = request.query.get("id")

    if not client_id or not state.is_valid_session_uuid(client_id):
        return web.Response(status=401, text="Unauthorized: invalid or missing session ID")

    _, user = state.find_user_by_uuid(client_id)
    if user and user.get("banned", False):
        return web.Response(status=403, text="This user is banned.")
    if user:
        state.ensure_user_defaults(user)
        if _user_has_submission(user):
            return web.Response(status=409, text="Submission already received for this user.")
        if request.app.get("exam_phase") == "finished" and not user.get("exam_started", False):
            return web.Response(status=403, text="Exam has already finished.")

    if client_id in state.clients:
        return web.Response(status=409, text="A client is already connected with this login.")

    ws = web.WebSocketResponse()
    await ws.prepare(request)

    short_id = client_id[:8]
    ip = _client_ip(request)

    state.clients[client_id] = {
        "ws": ws,
        "short_id": short_id,
        "ip": ip,
        "computer_name": user.get("computer_name", "") if user else "",
    }
    print(f"[+] Client connected: {client_id} (short: {short_id}, ip: {ip})")

    # Send welcome with their ID
    await ws.send_str(events.welcome(client_id, request.app["server_id"]))
    await ws.send_str(
        events.process_blacklist(
            state.process_blacklist,
            state.process_blacklist_version,
        )
    )
    if user:
        user["last_action"] = "Awaiting submission" if _user_needs_submission(user) else "Connected"
        state.save_users()
        if _user_needs_submission(user):
            await ws.send_str(events.finish_exam("Your exam has ended. Please upload your file."))

    try:
        async for msg in ws:
            if msg.type == WSMsgType.TEXT:
                event, data = protocol.decode(msg.data)
                if event == protocol.DECODE_ERROR:
                    await ws.send_str(events.error(data.get("reason", "protocol decode failed")))
                    continue

                if event == events.PING:
                    await _handle_ping_event(ws, client_id, data)
                elif event == events.CLIENT_INFO:
                    _handle_client_info(client_id, data)
                elif event == events.START_EXAM:
                    await _handle_start_exam(ws, request, client_id)
                elif event == events.PROCESS_CATCH:
                    await _handle_process_catch_event(ws, client_id, data)
                else:
                    await ws.send_str(events.error(f"unknown event: {event}"))

            elif msg.type == WSMsgType.ERROR:
                print(f"[!] Client {client_id} error: {ws.exception()}")
    finally:
        # Unregister on disconnect
        state.clients.pop(client_id, None)
        if user and user.get("last_action") == "Connected":
            user["last_action"] = "Disconnected"
            state.save_users()
        print(f"[-] Client {client_id} disconnected  ({len(state.clients)} total)")

    return ws
