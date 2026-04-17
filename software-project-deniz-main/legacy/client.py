"""
Client -- connects to the server via WebSocket.

  - Receives a unique ID from the server on connect
  - Sends a "ping" and prints the echoed response
  - Listens for the server's time broadcasts
  - Type messages to send more pings, or Ctrl+C to quit
"""

import argparse
import asyncio
import sys
import uuid
import json
import os
import subprocess

import aiohttp

import shared
import events
from threading import Thread
from discovery import discover_server
from custommodules.replay_recorder import ReplayRecorder
from custommodules.process_monitor import ProcessMonitor

async def perform_login(base_url: str, login_id: str, password: str) -> str:
    """Logs in and returns the session UUID. Raises on failure."""
    async with aiohttp.ClientSession() as session:
        async with session.post(f"{base_url}/login", json={"login_id": login_id, "password": password}) as resp:
            if resp.status == 200:
                data = await resp.json()
                return data["uuid"]
            else:
                body = await resp.text()
                raise ValueError(f"Login failed ({resp.status}): {body}")

async def fetch_exam_prep(base_url: str, session_uuid: str):
    """Fetches the exam configuration and files."""
    async with aiohttp.ClientSession() as session:
        # Get config
        async with session.get(f"{base_url}/exam/config") as resp:
            if resp.status == 200:
                config = await resp.json()
                mins = config.get("exam_duration_seconds", 0) // 60
                print(f"[EXAM] Config loaded: Exam duration is {mins} minutes.")
            else:
                print(f"[EXAM] Failed to load config: {resp.status}")

        # Get files if available
        async with session.get(f"{base_url}/exam/files") as resp:
            if resp.status == 200:
                print(f"[EXAM] Downloading exam files...")
                content = await resp.read()
                out_dir = os.path.join("data", "client", session_uuid, "exam_files")
                os.makedirs(out_dir, exist_ok=True)
                out_path = os.path.join(out_dir, "exam_materials.zip")
                with open(out_path, "wb") as f:
                    f.write(content)
                print(f"[EXAM] Exam files saved to {out_path}.")
            elif resp.status == 404:
                print("[EXAM] No exam files provided by server.")
            else:
                body = await resp.text()
                print(f"[EXAM] Failed to download exam files ({resp.status}): {body}")

async def prompt_start_exam(ws: aiohttp.ClientWebSocketResponse, start_event: asyncio.Event):
    """Wait for the user to type 'start' or a GUI signal to begin the exam."""
    print("\n--- PRE-EXAM PREPARATION ---")
    print("When you are ready, type 'start' or click the button in the GUI to begin the exam.")
    loop = asyncio.get_event_loop()
    
    while not start_event.is_set():
        # This is a bit tricky because run_in_executor(sys.stdin.readline) blocks.
        # We'll use a short timeout or just check the event.
        # Since we use FIRST_COMPLETED below, we can just wait for both.
        
        # We'll run a helper to wait for 'start' in a thread
        def wait_for_start():
            while not start_event.is_set():
                line = sys.stdin.readline()
                if line.strip().lower() == "start":
                    return True
            return False

        cli_task = loop.run_in_executor(None, wait_for_start)
        done, pending = await asyncio.wait(
            [asyncio.ensure_future(cli_task), asyncio.ensure_future(start_event.wait())],
            return_when=asyncio.FIRST_COMPLETED
        )
        
        # If either task finished, we check if we should start
        if start_event.is_set() or (cli_task.done() and cli_task.result()):
            await ws.send_str(events.start_exam())
            print("[EXAM] Started. Good luck!\n")
            start_event.set()
            return
            
        if not start_event.is_set():
            print("Type 'start' or use the GUI to begin.")





async def check_health(base_url: str):
    """Quick HTTP health check."""
    async with aiohttp.ClientSession() as session:
        async with session.get(f"{base_url}/health") as resp:
            data = await resp.json()
            print(f"[HTTP] Health: {data}")


async def run_ws(ws_url: str, recorder: ReplayRecorder):
    """Connect via WebSocket, handle exam flow and pings."""
    async with aiohttp.ClientSession() as session:
        async with session.ws_connect(ws_url) as ws:
            disconnected = asyncio.Event()
            exam_active = True
            gui_process = None
            
            # Extract UUID for passing to child tasks
            client_uuid = shared.extract_client_uuid(ws_url)

            # Initialize and start Process Monitor immediately
            out_dir = os.path.join("data", "client", client_uuid)
            pm_ref = {"monitor": ProcessMonitor(out_dir)}
            pm_ref["monitor"].start()
            
            start_event = asyncio.Event()

            def start_gui():
                nonlocal gui_process
                if gui_process is None:
                    script_dir = os.path.dirname(os.path.abspath(__file__))
                    gui_path = os.path.join(script_dir, "client_gui.py")
                    # We need to read stdout from the GUI
                    gui_process = subprocess.Popen(
                        [sys.executable, gui_path], 
                        stdin=subprocess.PIPE, 
                        stdout=subprocess.PIPE, 
                        text=True,
                        bufsize=1
                    )
                    
                    def gui_stdout_reader():
                        for line in iter(gui_process.stdout.readline, ''):
                            if "ACTION:START" in line:
                                print("[GUI] Start button pressed.")
                                loop = asyncio.get_event_loop()
                                loop.call_soon_threadsafe(start_event.set)
                        gui_process.stdout.close()

                    Thread(target=gui_stdout_reader, daemon=True).start()

            # -- Listener task: prints everything the server sends --------
            async def listener():
                nonlocal exam_active, gui_process
                try:
                    async for msg in ws:
                        if msg.type == aiohttp.WSMsgType.TEXT:
                            event, data = shared.decode(msg.data)
                            
                            if event == events.WELCOME:
                                print(f"[WS] Connected! Server assigned ID: {data['id']}")
                                start_gui()
                            elif event == events.ECHO:
                                print(f"[WS] Echo: {data}")
                            elif event == events.TIME:
                                # Hide time broadcast noise 
                                pass
                            elif event == events.SYNC_TIME:
                                rem = data.get("remaining_seconds", 0)
                                if pm_ref["monitor"]:
                                    pm_ref["monitor"].update_time(rem)
                                
                                start_gui() # Ensure GUI is open if it wasn't
                                
                                if gui_process and gui_process.poll() is None:
                                    try:
                                        gui_process.stdin.write(f"SYNC:{rem}\n")
                                        gui_process.stdin.flush()
                                    except Exception:
                                        pass

                                # Still print locally occasionally, or let the GUI handle it
                                if rem % 10 == 0:
                                    m, s = divmod(rem, 60)
                                    print(f"[EXAM] Time remaining: {m}m {s}s")
                                    
                            elif event == events.EXAM_END:
                                print("\n===============================")
                                print("       EXAM TIME IS UP!        ")
                                print("===============================")
                                exam_active = False
                                
                                if gui_process and gui_process.poll() is None:
                                    try:
                                        gui_process.stdin.write("END:-1\n")
                                        gui_process.stdin.flush()
                                    except Exception:
                                        pass
                                
                                disconnected.set()
                            elif event == events.SAVESCREEN:
                                print("[WS] [SAVESCREEN] Server requested replay save.")
                                loop = asyncio.get_event_loop()
                                await loop.run_in_executor(None, recorder.save_replay)
                            elif event == events.GET_PROCESSES:
                                print("[WS] [GET_PROCESSES] Server requested a manual process report.")
                                if pm_ref["monitor"]:
                                    pm_ref["monitor"].trigger_full_report()
                                else:
                                    print("[WS] Process monitor not running yet.")
                            else:
                                print(f"[WS] {event}: {data}")

                        elif msg.type in (aiohttp.WSMsgType.CLOSED, aiohttp.WSMsgType.ERROR):
                            break
                except Exception as e:
                    print(f"[WS] Listener error: {e}")
                finally:
                    # WS loop ended -- server is gone
                    disconnected.set()

            # -- Sender: reads stdin and sends pings ----------------------
            async def sender():
                await prompt_start_exam(ws, start_event)
                
                print("Type anything and press Enter to ping the server (Ctrl+C to quit):\n")
                loop = asyncio.get_event_loop()
                while not disconnected.is_set() and exam_active:
                    # Check for disconnect between each line read
                    read_future = loop.run_in_executor(None, sys.stdin.readline)
                    # Wait for either stdin input or disconnect
                    done, _ = await asyncio.wait(
                        [asyncio.ensure_future(read_future),
                         asyncio.ensure_future(disconnected.wait())],
                        return_when=asyncio.FIRST_COMPLETED,
                    )
                    if disconnected.is_set():
                        break
                    for task in done:
                        line = task.result()
                        if not line:
                            return
                        text = line.strip()
                        if text:
                            await ws.send_str(events.ping(text))

            listen_task = asyncio.create_task(listener())
            try:
                await sender()
            except (KeyboardInterrupt, asyncio.CancelledError):
                pass
            finally:
                listen_task.cancel()
                if gui_process and gui_process.poll() is None:
                    gui_process.kill()
                if pm_ref["monitor"]:
                    pm_ref["monitor"].stop()

            if disconnected.is_set():
                raise ConnectionError("Server disconnected")



async def discover_loop(server_id: str, timeout: float):
    """Keep searching until we find a server."""
    result = None
    while result is None:
        result = await discover_server(server_id=server_id, timeout=timeout)
        if result is None:
            print("No server found yet, retrying...")
    return result


async def main(args):
    session_uuid = None
    recorder = None
    
    print(f"=== Client [{args.login_id}] (awaiting session assignment) ===\n")

    try:
        while True:
            # 1. Discover or use explicit host/port
            if args.host:
                host, port = args.host, args.port
                print(f"[DIRECT] Connecting to {host}:{port}")
            else:
                if getattr(args, 'check_login', False):
                    # Don't loop forever during a quick check
                    server_info = await discover_server(args.id, args.timeout)
                    if not server_info:
                        print(f"\n[FATAL] Could not discover server '{args.id}' on the local network.")
                        sys.exit(1)
                    host, port = server_info
                else:
                    host, port = await discover_loop(args.id, args.timeout)

            base_url = f"http://{host}:{port}"
            
            try:
                # 2. Login to get/verify UUID
                new_uuid = await perform_login(base_url, args.login_id, args.password)
                
                if getattr(args, 'check_login', False):
                    print("[+] Credentials verified successfully.")
                    sys.exit(0)
                
                if not session_uuid:
                    session_uuid = new_uuid
                    print(f"[LOGIN] Assigned session UUID: {session_uuid}")
                    
                    recorder = ReplayRecorder(session_uuid=session_uuid)
                    if args.record:
                        loop = asyncio.get_event_loop()
                        await loop.run_in_executor(None, recorder.start)
                elif session_uuid != new_uuid:
                    print(f"[!] Server returned a different UUID ({new_uuid}) than active ({session_uuid}). Resyncing.")
                    session_uuid = new_uuid
                    
                    if recorder:
                        if args.record:
                            loop = asyncio.get_event_loop()
                            await loop.run_in_executor(None, recorder.stop)
                            
                        recorder = ReplayRecorder(session_uuid=session_uuid)
                        if args.record:
                            loop = asyncio.get_event_loop()
                            await loop.run_in_executor(None, recorder.start)

                ws_url = f"ws://{host}:{port}/ws?id={session_uuid}"

                # 3. Fetch Exam Configuration and Files
                await fetch_exam_prep(base_url, session_uuid)

                # 4. HTTP health check
                await check_health(base_url)

                # 5. WebSocket session
                print()
                await run_ws(ws_url, recorder)
            except ValueError as e:
                # Fatal login error (e.g., wrong password), we should probably exit
                print(f"\n[FATAL] {e}")
                sys.exit(1)
            except (aiohttp.ClientError, ConnectionError, OSError) as e:
                print(f"\n[!] Connection lost: {e}")

            # If we get here, server died or connection dropped
            print(f"[!] Reconnecting in {args.reconnect} seconds...\n")
            await asyncio.sleep(args.reconnect)
    finally:
        if args.record and recorder:
            loop = asyncio.get_event_loop()
            await loop.run_in_executor(None, recorder.stop)

# -- Validation ------------------------------------------------------------
def validate_args(args):
    errors = []
    if not 1 <= args.port <= 65535:
        errors.append(f"--port must be 1-65535, got {args.port}")
    if args.timeout <= 0:
        errors.append(f"--timeout must be > 0, got {args.timeout}")
    if args.reconnect < 0:
        errors.append(f"--reconnect must be >= 0, got {args.reconnect}")
    if not args.id.strip():
        errors.append("--id cannot be empty")
    if errors:
        for e in errors:
            print(f"[ERROR] {e}")
        sys.exit(1)


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Client")
    parser.add_argument("--login-id",  required=True, help="Client login ID")
    parser.add_argument("--password",  required=True, help="Client password")
    parser.add_argument("--id",        default="default", help="Server ID to connect to (default: default)")
    parser.add_argument("--host",      default=None,      help="Server host (skip discovery, connect directly)")
    parser.add_argument("--port",      default=8080, type=int, help="Server port (default: 8080)")
    parser.add_argument("--timeout",   default=15, type=float, help="Discovery timeout in seconds (default: 15)")
    parser.add_argument("--reconnect", default=3, type=float, help="Seconds to wait before reconnecting (default: 3)")
    parser.add_argument("--no-record", dest="record", action="store_false", help="Disable screen replay recorder")
    parser.add_argument("--check-login", action="store_true", help="Only validate server connection and login credentials, then exit.")
    parser.set_defaults(record=True)
    args = parser.parse_args()

    validate_args(args)

    try:
        asyncio.run(main(args))
    except KeyboardInterrupt:
        print("\nBye!")


