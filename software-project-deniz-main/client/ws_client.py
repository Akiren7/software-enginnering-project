import asyncio
import json
import os
import socket
import subprocess
import sys
from dataclasses import dataclass
from threading import Thread

import aiohttp

from common import events, protocol
from .submission import validate_submission_file
from .transfers import (
    build_submission_bundle,
    upload_runtime_artifact,
    upload_submission_bundle,
)
from custommodules.hardware_monitor import HardwareMonitor
from custommodules.process_monitor import ProcessMonitor
from custommodules.replay_recorder import ReplayRecorder


def _run_in_background(loop: asyncio.AbstractEventLoop, callback, *args):
    loop.call_soon_threadsafe(callback, *args)


def _client_gui_path() -> str:
    script_dir = os.path.dirname(os.path.abspath(__file__))
    return os.path.join(os.path.dirname(script_dir), "client_gui.py")


def _time_text(seconds: int) -> str:
    minutes, remaining_seconds = divmod(seconds, 60)
    return f"{minutes}m {remaining_seconds}s"


def _computer_name() -> str:
    try:
        return socket.gethostname()
    except Exception:
        return "unknown"


def _extract_finish_path(text: str) -> str | None:
    stripped = text.strip()
    if not stripped:
        return None

    lowered = stripped.lower()
    prefixes = ("finish ", "/finish ")
    for prefix in prefixes:
        if lowered.startswith(prefix):
            return stripped[len(prefix):].strip() or None

    return None


async def _wait_for_queue_or_event(
    input_queue: asyncio.Queue,
    event: asyncio.Event,
) -> tuple[object | None, bool]:
    queue_task = asyncio.create_task(input_queue.get())
    event_task = asyncio.create_task(event.wait())

    done, pending = await asyncio.wait(
        [queue_task, event_task],
        return_when=asyncio.FIRST_COMPLETED,
    )

    for task in pending:
        task.cancel()

    if event_task in done and event.is_set():
        return None, True

    return queue_task.result(), False


class StdinBridge:
    def __init__(self, loop: asyncio.AbstractEventLoop):
        self.loop = loop
        self.queue = asyncio.Queue()
        self.thread = Thread(target=self._reader, daemon=True)
        self.thread.start()

    def _reader(self):
        for line in sys.stdin:
            _run_in_background(self.loop, self.queue.put_nowait, UserCommand("stdin", line))


@dataclass
class UserCommand:
    action: str
    value: str = ""


class ClientGUIBridge:
    def __init__(self, loop: asyncio.AbstractEventLoop, input_queue: asyncio.Queue):
        self.loop = loop
        self.input_queue = input_queue
        self.process = None

    def ensure_started(self):
        if self.process is not None and self.process.poll() is None:
            return

        self.process = subprocess.Popen(
            [sys.executable, _client_gui_path()],
            stdin=subprocess.PIPE,
            stdout=subprocess.PIPE,
            text=True,
            bufsize=1,
        )
        Thread(target=self._stdout_reader, daemon=True).start()

    def _stdout_reader(self):
        process = self.process
        if process is None or process.stdout is None:
            return

        for line in iter(process.stdout.readline, ""):
            command = self._parse_gui_command(line)
            if command is None:
                continue
            _run_in_background(self.loop, self.input_queue.put_nowait, command)
        try:
            process.stdout.close()
        except Exception:
            pass

    def send_sync(self, remaining_seconds: int):
        self._write(f"SYNC:{remaining_seconds}\n")

    def send_end(self):
        self._write("END:-1\n")

    def send_reset(self):
        self._write("RESET:1\n")

    def send_error(self, message: str):
        self._write(f"ERROR:{message}\n")

    def send_open_finish(self, message: str):
        self._write(f"OPEN_FINISH:{message}\n")

    def send_upload_success(self, message: str):
        self._write(f"UPLOAD_OK:{message}\n")

    def send_upload_error(self, message: str):
        self._write(f"UPLOAD_ERROR:{message}\n")

    def close(self):
        process = self.process
        self.process = None
        if process and process.poll() is None:
            process.kill()

    def _parse_gui_command(self, line: str) -> UserCommand | None:
        text = line.strip()
        if not text:
            return None

        if "ACTION:START" in text:
            print("[GUI] Start button pressed.")
            return UserCommand("start")

        try:
            payload = json.loads(text)
        except json.JSONDecodeError:
            return None

        command = payload.get("cmd")
        if command == "start_exam":
            print("[GUI] Start button pressed.")
            return UserCommand("start")
        if command == "finish_exam":
            selected_file = str(payload.get("archive_path", "")).strip()
            if not selected_file:
                return None
            print(f"[GUI] Finish button pressed with file: {selected_file}")
            return UserCommand("finish", selected_file)
        return None

    def _write(self, message: str):
        if not self.process or self.process.poll() is not None:
            return

        try:
            self.process.stdin.write(message)
            self.process.stdin.flush()
        except Exception:
            pass


@dataclass
class SessionState:
    disconnected: asyncio.Event
    start_event: asyncio.Event
    exam_active: bool = True
    last_printed_remaining: int | None = None
    start_request_pending: bool = False
    finish_request_pending: bool = False
    submission_only: bool = False
    submission_completed: bool = False
    intentional_shutdown: bool = False


class WebSocketSession:
    def __init__(
        self,
        ws_url: str,
        base_url: str,
        session_uuid: str,
        ws,
        recorder: ReplayRecorder | None,
    ):
        self.ws_url = ws_url
        self.base_url = base_url
        self.session_uuid = session_uuid
        self.ws = ws
        self.recorder = recorder
        self.loop = asyncio.get_running_loop()
        self.state = SessionState(
            disconnected=asyncio.Event(),
            start_event=asyncio.Event(),
        )
        self.stdin = StdinBridge(self.loop)
        self.gui = ClientGUIBridge(self.loop, self.stdin.queue)
        self.process_monitor = self._create_process_monitor()
        self.hardware_monitor = self._create_hardware_monitor()

    def _create_process_monitor(self):
        client_uuid = protocol.extract_client_uuid(self.ws_url)
        out_dir = os.path.join("data", "client", client_uuid)
        monitor = ProcessMonitor(
            out_dir,
            catch_callback=self._queue_process_catch_report,
        )
        monitor.start()
        return monitor

    def _create_hardware_monitor(self):
        client_uuid = protocol.extract_client_uuid(self.ws_url)
        out_dir = os.path.join("data", "client", client_uuid)
        monitor = HardwareMonitor(out_dir)
        monitor.start()
        return monitor

    async def run(self):
        listener_task = asyncio.create_task(self.listener())
        try:
            await self.sender()
        except (KeyboardInterrupt, asyncio.CancelledError):
            pass
        finally:
            listener_task.cancel()
            self.gui.close()
            self.process_monitor.stop()
            self.hardware_monitor.stop()

        if self.state.disconnected.is_set() and not self.state.intentional_shutdown:
            raise ConnectionError("Server disconnected")
        return self.state.intentional_shutdown

    async def prompt_start_exam(self):
        print("\n--- PRE-EXAM PREPARATION ---")
        print("When you are ready, type 'start' or click the button in the GUI.")
        print("If the server has not started the exam yet, you will be asked to try again.")

        while not self.state.start_event.is_set():
            command, event_triggered = await _wait_for_queue_or_event(
                self.stdin.queue,
                self.state.start_event,
            )
            if event_triggered:
                break

            if not isinstance(command, UserCommand):
                continue

            if command.action == "start":
                await self.request_exam_start()
                continue

            if command.action == "stdin":
                text = command.value.strip().lower()
                if text in {"start", "/start"}:
                    await self.request_exam_start()
                    continue

            print("Type 'start' or use the GUI when you are ready.")

        if self.state.submission_only:
            print("[EXAM] Submission is required. Use the finish window to upload your file.\n")
            return

        print("[EXAM] Started. Good luck!\n")

    async def request_exam_start(self):
        if self.state.start_request_pending:
            print("[EXAM] Start request already in progress...")
            return

        self.state.start_request_pending = True
        await self.ws.send_str(events.start_exam())
        print("[EXAM] Start request sent...")

    async def sender(self):
        await self.prompt_start_exam()
        if self.state.submission_only:
            print("Use the finish window to upload your file, or type 'finish <file_path>'.\n")
        else:
            print("Type anything and press Enter to ping the server (Ctrl+C to quit):\n")

        while not self.state.disconnected.is_set() and self.state.exam_active:
            command, disconnected = await _wait_for_queue_or_event(
                self.stdin.queue,
                self.state.disconnected,
            )
            if disconnected:
                break

            if not isinstance(command, UserCommand):
                continue

            if command.action == "finish":
                await self.finish_exam(command.value)
                continue

            if command.action != "stdin":
                continue

            text = command.value.strip()
            finish_path = _extract_finish_path(text)
            if finish_path:
                await self.finish_exam(finish_path)
                continue

            if self.state.submission_only:
                print("Submission is still required. Use the finish window or type 'finish <file_path>'.")
                continue

            if text:
                await self.ws.send_str(events.ping(text))

    async def listener(self):
        try:
            async for msg in self.ws:
                if msg.type == aiohttp.WSMsgType.TEXT:
                    await self.handle_text_message(msg.data)
                elif msg.type in (aiohttp.WSMsgType.CLOSED, aiohttp.WSMsgType.ERROR):
                    break
        except Exception as e:
            print(f"[WS] Listener error: {e}")
        finally:
            self.state.disconnected.set()

    async def handle_text_message(self, raw_message: str):
        event, data = protocol.decode(raw_message)
        if event == protocol.DECODE_ERROR:
            print(f"[WS] Protocol error: {data.get('reason', 'decode failed')}")
            return

        if event == events.WELCOME:
            print(f"[WS] Connected! Server assigned ID: {data['id']}")
            self.gui.ensure_started()
            await self.ws.send_str(events.client_info(_computer_name()))
            return

        if event == events.ECHO:
            print(f"[WS] Echo: {data}")
            return

        if event == events.TIME:
            return

        if event == events.SYNC_TIME:
            self.handle_sync_time(data)
            return

        if event == events.ERROR:
            self.handle_server_error(data)
            return

        if event == events.EXAM_END:
            self.handle_exam_end()
            return

        if event == events.FINISH_EXAM:
            self.handle_finish_request(data)
            return

        if event == events.SAVESCREEN:
            print("[WS] [SAVESCREEN] Server requested replay save.")
            if self.recorder:
                replay_path = await self.loop.run_in_executor(None, self.recorder.save_replay)
                if replay_path:
                    await self._upload_runtime_artifact(
                        replay_path,
                        artifact_kind="requested_replay",
                        metadata={"source": "server_request"},
                    )
            return

        if event == events.GET_PROCESSES:
            print("[WS] [GET_PROCESSES] Server requested a manual process report.")
            report_path = self.process_monitor.export_requested_report()
            if report_path:
                await self._upload_runtime_artifact(
                    report_path,
                    artifact_kind="requested_process_report",
                    metadata={"source": "server_request"},
                )
            return

        if event == events.PROCESS_BLACKLIST:
            self.handle_process_blacklist(data)
            return

        print(f"[WS] {event}: {data}")

    def handle_sync_time(self, data: dict):
        remaining = data.get("remaining_seconds", 0)
        self.process_monitor.update_time(remaining)
        self.gui.ensure_started()
        self.state.start_request_pending = False

        if not self.state.start_event.is_set():
            print("[WS] Exam is already running on the server. Joining automatically...")
            self.state.start_event.set()

        self.gui.send_sync(remaining)
        self._print_remaining_time(remaining)

    def handle_server_error(self, data: dict):
        reason = data.get("reason", "Unknown server error.")
        self.state.start_request_pending = False
        print(f"[WS] Error: {reason}")
        self.gui.ensure_started()
        if not self.state.submission_only:
            self.gui.send_reset()
        if reason in {"Exam is not started yet.", "Exam has already finished."}:
            self.gui.send_error(reason)

    def handle_process_blacklist(self, data: dict):
        entries = [str(entry).strip() for entry in data.get("entries", []) if str(entry).strip()]
        version = str(data.get("version", "0"))
        self.process_monitor.set_blacklist(entries, version)
        print(
            f"[PROCESS] Received blacklist update version {version} "
            f"with {len(entries)} entrie(s)."
        )

    def handle_finish_request(self, data: dict):
        if self.state.submission_completed:
            return

        reason = data.get("reason", "The exam has been finished by the server.")
        self.state.submission_only = True
        self.state.start_event.set()
        print(f"[EXAM] {reason}")
        self.gui.ensure_started()
        self.gui.send_open_finish(reason)

    def handle_exam_end(self):
        print("\n===============================")
        print("       EXAM TIME IS UP!        ")
        print("===============================")
        self.state.exam_active = False
        self.gui.send_end()
        self.state.disconnected.set()

    async def finish_exam(self, archive_path: str):
        if self.state.submission_completed:
            print("[EXAM] Submission has already been completed.")
            return

        if self.state.finish_request_pending:
            print("[EXAM] Submission upload is already in progress.")
            return

        archive_path = archive_path.strip()
        if not archive_path:
            error_message = "Choose a file before finishing the exam."
            print(f"[EXAM] {error_message}")
            self.gui.send_upload_error(error_message)
            return

        try:
            validate_submission_file(archive_path)
        except Exception as exc:
            error_message = str(exc)
            print(f"[EXAM] Submission validation failed: {error_message}")
            self.gui.send_upload_error(error_message)
            return

        self.state.finish_request_pending = True
        self.state.submission_only = True
        print(f"[EXAM] Uploading file: {archive_path}")
        try:
            process_report_path = self.process_monitor.export_requested_report()
            hardware_report_path = self.hardware_monitor.export_current_snapshot()
            replay_path = None
            if self.recorder:
                replay_path = await self.loop.run_in_executor(None, self.recorder.save_replay)

            bundle_path = build_submission_bundle(
                self.session_uuid,
                archive_path,
                process_report_path,
                replay_path,
                hardware_report_path,
            )
            response = await upload_submission_bundle(
                self.base_url,
                self.session_uuid,
                bundle_path,
            )
        except Exception as exc:
            self.state.finish_request_pending = False
            error_message = str(exc)
            print(f"[EXAM] Submission failed: {error_message}")
            self.gui.send_upload_error(error_message)
            return

        self.state.submission_completed = True
        self.state.intentional_shutdown = True
        self.state.exam_active = False
        self.gui.send_upload_success(response.get("message", "Submission uploaded successfully."))
        await self.ws.close(message=b"submission complete")
        self.state.disconnected.set()

    async def _upload_runtime_artifact(
        self,
        artifact_path: str,
        *,
        artifact_kind: str,
        metadata: dict | None = None,
    ):
        try:
            response = await upload_runtime_artifact(
                self.base_url,
                self.session_uuid,
                artifact_path,
                artifact_kind,
                metadata,
            )
            print(f"[UPLOAD] {artifact_kind} uploaded to {response.get('path', 'server storage')}")
        except Exception as exc:
            print(f"[UPLOAD] Failed to upload {artifact_kind}: {exc}")

    def _queue_process_catch_report(self, matches: list[dict], blacklist_version: str):
        asyncio.create_task(self._send_process_catch_report(matches, blacklist_version))

    async def _send_process_catch_report(self, matches: list[dict], blacklist_version: str):
        if not matches:
            return
        try:
            await self.ws.send_str(events.process_catch(matches, blacklist_version))
        except Exception as exc:
            print(f"[PROCESS] Failed to send blacklist catch report: {exc}")

    def _print_remaining_time(self, remaining: int):
        last_remaining = self.state.last_printed_remaining
        if last_remaining is None or remaining <= last_remaining - 10:
            self.state.last_printed_remaining = remaining
            print(f"[EXAM] Time remaining: {_time_text(remaining)}")


async def run_ws(
    ws_url: str,
    base_url: str,
    session_uuid: str,
    recorder: ReplayRecorder | None,
):
    """Connect via WebSocket, handle exam flow and pings."""
    async with aiohttp.ClientSession() as session:
        async with session.ws_connect(ws_url) as ws:
            return await WebSocketSession(ws_url, base_url, session_uuid, ws, recorder).run()
