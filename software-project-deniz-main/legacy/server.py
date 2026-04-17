"""
Server -- HTTP + WebSocket on a single port.

Features:
  - GET /health            -> simple HTTP health check
  - WS  /ws                -> WebSocket endpoint
      - assigns each client a unique ID on connect ("welcome" event)
      - echoes back any "ping" event the client sends
      - broadcasts the current time to ALL clients every 10 seconds
"""

import argparse
import asyncio
import errno
import sys
import uuid
import json
import os
import subprocess
from threading import Thread

from aiohttp import web, WSMsgType

import shared
import events
from discovery import ServerAnnouncer, check_duplicate_server


# -- State -----------------------------------------------------------------
# clients: full_id -> { "ws": WebSocketResponse, "short_id": str, "ip": str }
clients: dict[str, dict] = {}

USERS_FILE = "data/server/server_users.json"
# users_db: login_id -> { "password": str, "uuid": str, "time_spent_seconds": int, "exam_started": bool }
users_db: dict[str, dict] = {}

ALLOWED_USERS_FILE = "allowed_users.json"
# allowed_users: login_id -> password
allowed_users: dict[str, str] = {}

# Global GUI process handle
gui_process = None

def load_users():
    global users_db, allowed_users
    
    if os.path.exists(USERS_FILE):
        try:
            with open(USERS_FILE, "r") as f:
                users_db = json.load(f)
        except Exception as e:
            print(f"[!] Failed to load {USERS_FILE}: {e}")
            users_db = {}
            
    if os.path.exists(ALLOWED_USERS_FILE):
        try:
            with open(ALLOWED_USERS_FILE, "r") as f:
                allowed_users = json.load(f)
        except Exception as e:
            print(f"[!] Failed to load {ALLOWED_USERS_FILE}: {e}")
            allowed_users = {}

def save_users():
    os.makedirs(os.path.dirname(USERS_FILE), exist_ok=True)
    try:
        with open(USERS_FILE, "w") as f:
            json.dump(users_db, f, indent=2)
    except Exception as e:
        print(f"[!] Failed to save {USERS_FILE}: {e}")


# -- HTTP Routes -----------------------------------------------------------
async def health(request: web.Request) -> web.Response:
    return web.json_response({
        "status": "ok",
        "server_id": request.app["server_id"],
        "clients_connected": len(clients),
    })

async def login_handler(request: web.Request) -> web.Response:
    try:
        data = await request.json()
    except json.JSONDecodeError:
        return web.json_response({"error": "Invalid JSON"}, status=400)
    
    login_id = data.get("login_id")
    password = data.get("password")
    
    if not login_id or not password:
        return web.json_response({"error": "login_id and password required"}, status=400)
        
    # Check if user is in the allowed list
    if login_id not in allowed_users:
        return web.json_response({"error": "User is not allowed to take this exam."}, status=403)
        
    if allowed_users[login_id] != password:
        return web.json_response({"error": "Invalid credentials provided."}, status=401)
        
    user = users_db.get(login_id)
    if user:
        if user["password"] != password:
            return web.json_response({"error": "Invalid stored credentials"}, status=401)
        # Valid login existing
        return web.json_response({"status": "ok", "uuid": user["uuid"]})
    else:
        # Create new user
        new_uuid = str(uuid.uuid4())
        users_db[login_id] = {
            "password": password,
            "uuid": new_uuid,
            "time_spent_seconds": 0,
            "exam_started": False
        }
        save_users()
        print(f"[+] New valid user registered: {login_id} -> {new_uuid}")
        return web.json_response({"status": "ok", "uuid": new_uuid})


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
    
    # Simple file serving, assumes it's a zip or single file
    # For a directory, a robust solution would zip it on the fly, 
    # but for this demo we'll assume the user provided a .zip file.
    if os.path.isdir(path):
        return web.Response(status=400, text="Directory serving not implemented, please provide a .zip file")
        
    return web.FileResponse(path)

# -- WebSocket Handler -----------------------------------------------------
async def websocket_handler(request: web.Request) -> web.WebSocketResponse:
    client_id = request.query.get("id")
    
    # Verify the UUID was issued by us
    valid_uuids = {u["uuid"] for u in users_db.values()}
    if not client_id or client_id not in valid_uuids:
        return web.Response(status=401, text="Unauthorized: invalid or missing session ID")

    ws = web.WebSocketResponse()
    await ws.prepare(request)

    short_id = client_id[:8]
    ip = request.remote

    clients[client_id] = {
        "ws": ws,
        "short_id": short_id,
        "ip": ip
    }
    print(f"[+] Client connected: {client_id} (short: {short_id}, ip: {ip})")

    # Send welcome with their ID
    await ws.send_str(events.welcome(client_id, request.app["server_id"]))

    try:
        async for msg in ws:
            if msg.type == WSMsgType.TEXT:
                event, data = shared.decode(msg.data)

                if event == events.PING:
                    # Echo back with the same data
                    await ws.send_str(events.echo(data, shared.now_iso()))
                elif event == events.START_EXAM:
                    # Find user in DB
                    for login_id, u in users_db.items():
                        if u["uuid"] == client_id:
                            if not u.get("exam_started", False):
                                u["exam_started"] = True
                                save_users()
                                print(f"[EXAM] Client {client_id} started their exam.")
                                
                                # Instantly sync the precise starting time so the client doesn't start at -10s
                                exam_duration_sec = request.app["exam_duration"] * 60
                                rem = max(0, exam_duration_sec - u.get("time_spent_seconds", 0))
                                await ws.send_str(events.sync_time(rem))
                            break
                else:
                    await ws.send_str(events.error(f"unknown event: {event}"))

            elif msg.type == WSMsgType.ERROR:
                print(f"[!] Client {client_id} error: {ws.exception()}")
    finally:
        # Unregister on disconnect
        clients.pop(client_id, None)
        print(f"[-] Client {client_id} disconnected  ({len(clients)} total)")

    return ws


# -- Background: broadcast time every N seconds ----------------------------
async def time_broadcaster(app: web.Application):
    """Background task that sends the current time to every connected client, and manages exam timers."""
    tick_interval = app["broadcast_interval"]
    exam_duration_sec = app["exam_duration"] * 60
    
    try:
        while True:
            await asyncio.sleep(tick_interval)
            
            # Map UUIDs back to login_ids to update the db
            uuid_to_login = {u["uuid"]: login_id for login_id, u in users_db.items()}
            
            if clients:
                payload = events.time_broadcast(shared.now_iso())
                dead = []
                for cid, data in clients.items():
                    ws = data["ws"]
                    try:
                        await ws.send_str(payload)
                        
                        # Handle EXAM TIMER
                        login_id = uuid_to_login.get(cid)
                        if login_id:
                            user = users_db[login_id]
                            # default to 0 and false if missing
                            num_spent = user.get("time_spent_seconds", 0)
                            has_started = user.get("exam_started", False)
                            
                            if has_started:
                                num_spent += tick_interval
                                user["time_spent_seconds"] = num_spent
                                
                                remaining = max(0, exam_duration_sec - num_spent)
                                await ws.send_str(events.sync_time(remaining))
                                
                                if remaining <= 0:
                                    print(f"[EXAM] Client {cid} ran out of time!")
                                    await ws.send_str(events.exam_end())
                                    
                    except ConnectionResetError:
                        dead.append(cid)
                for cid in dead:
                    clients.pop(cid, None)
                    
                save_users()
                
                # --- UI PIPELINE ---
                if gui_process and gui_process.poll() is None:
                    try:
                        # Construct UI State JSON
                        ui_clients = []
                        for login_id, u in users_db.items():
                            cid = u["uuid"]
                            status = "Connected" if cid in clients else "Disconnected"
                            rem = max(0, exam_duration_sec - u.get("time_spent_seconds", 0))
                            ui_clients.append({
                                "uuid": cid,
                                "login_id": login_id,
                                "status": status,
                                "remaining": rem
                            })
                        
                        payload = json.dumps({"type": "state_update", "clients": ui_clients})
                        gui_process.stdin.write(payload + "\n")
                        gui_process.stdin.flush()
                    except Exception as e:
                        print(f"[GUI IPC] Warning: Failed to write to GUI: {e}")
                # -------------------
    except asyncio.CancelledError:
        pass


# -- Server console: operator commands -------------------------------------
def resolve_client(target: str):
    """
    Find a client by:
    1. Full UUID
    2. Short ID (first 8 chars)
    3. IP Address
    Returns (full_id, client_data) or (None, None)
    """
    # 1. Check Full ID
    if target in clients:
        return target, clients[target]

    # 2. Check Short ID and IP
    for cid, data in clients.items():
        if data["short_id"] == target or data["ip"] == target:
            return cid, data

    return None, None


async def send_to_client(target: str, payload: str) -> bool:
    """Send a payload to a specific client (by UUID, short ID, or IP)."""
    cid, data = resolve_client(target)
    if not data:
        return False

    ws = data["ws"]
    try:
        await ws.send_str(payload)
        return True
    except (ConnectionResetError, RuntimeError):
        clients.pop(cid, None)
        return False


async def broadcast_to_all(payload: str) -> int:
    """Send a payload to every connected client. Returns count sent."""
    dead = []
    sent = 0
    for cid, data in clients.items():
        ws = data["ws"]
        try:
            await ws.send_str(payload)
            sent += 1
        except (ConnectionResetError, RuntimeError):
            dead.append(cid)
    for cid in dead:
        clients.pop(cid, None)
    return sent


def _gui_reader_thread(loop):
    """Reads stdout from the Tkinter GUI to pick up Options actions like sending savescreen."""
    global gui_process
    if not gui_process:
        return
        
    for line in iter(gui_process.stdout.readline, ''):
        line = line.strip()
        if not line: continue
        try:
            req = json.loads(line)
            cmd = req.get("cmd")
            uuid_val = req.get("uuid")
            
            if cmd == "savescreen" and uuid_val in clients:
                ws = clients[uuid_val]["ws"]
                asyncio.run_coroutine_threadsafe(ws.send_str(events.savescreen()), loop)
                print(f"\n[GUI->WS] Sent savescreen to {uuid_val}")
            
            elif cmd == "get_processes" and uuid_val in clients:
                ws = clients[uuid_val]["ws"]
                asyncio.run_coroutine_threadsafe(ws.send_str(events.get_processes()), loop)
                print(f"\n[GUI->WS] Sent get_processes to {uuid_val}")
                
        except Exception as e:
            pass

async def console_reader(app: web.Application):
    """Reads stdin for operator commands."""
    loop = asyncio.get_event_loop()
    
    # Start the GUI read thread if running
    if gui_process:
        t = Thread(target=_gui_reader_thread, args=(loop,), daemon=True)
        t.start()
        
    try:
        while True:
            line = await loop.run_in_executor(None, sys.stdin.readline)
            if not line:
                break
            parts = line.strip().split()
            if not parts:
                continue
            cmd = parts[0].lower()

            if cmd == "/clients":
                if clients:
                    print(f"[CMD] {len(clients)} client(s) connected:")
                    for cid, data in clients.items():
                        print(f"       - UUID:  {cid}")
                        print(f"         Short: {data['short_id']}")
                        print(f"         IP:    {data['ip']}")
                        print()
                else:
                    print("[CMD] No clients connected.")

            elif cmd == "/savescreen":
                if len(parts) < 2:
                    print("[CMD] Usage: /savescreen <client_id>  or  /savescreen all")
                elif parts[1].lower() == "all":
                    count = await broadcast_to_all(events.savescreen())
                    print(f"[CMD] Sent SAVESCREEN to {count} client(s)")
                else:
                    target = parts[1]
                    if await send_to_client(target, events.savescreen()):
                        print(f"[CMD] Sent SAVESCREEN to client {target}")
                    else:
                        print(f"[CMD] Client '{target}' not found (tried UUID, short ID, IP).")
                        print("      Type /clients to list available targets.")

            elif cmd == "/exam":
                exam_duration_sec = app["exam_duration"] * 60
                
                print("\n[CMD] --- LIVE EXAM STATUS ---")
                active_users = [
                    (cid, data, users_db.get(next((u for u, db in users_db.items() if db["uuid"] == cid), None)))
                    for cid, data in clients.items()
                ]
                
                if not active_users:
                    print("No clients connected.")
                else:
                    for cid, _, user_data in active_users:
                        if user_data:
                            login_id = next(login for login, data in users_db.items() if data["uuid"] == cid)
                            state = "Running" if user_data.get("exam_started") else "Waiting"
                            rem = max(0, exam_duration_sec - user_data.get("time_spent_seconds", 0))
                            m, s = divmod(rem, 60)
                            print(f"User: {login_id:12} | State: {state:7} | Remaining: {m:02d}m {s:02d}s")
                        else:
                            print(f"Unknown UUID: {cid}")
                print("------------------------------\n")
                
            elif cmd == "/help":
                print("  /clients              - List connected clients")
                print("  /savescreen <id>      - Save replay on a specific client")
                print("  /savescreen all       - Save replay on ALL clients")
                print("  /help                 - Show this help")
            else:
                print(f"[CMD] Unknown command: {cmd}  (type /help)")
    except asyncio.CancelledError:
        pass


async def start_background_tasks(app: web.Application):
    app["time_broadcaster"] = asyncio.create_task(time_broadcaster(app))
    app["console_reader"] = asyncio.create_task(console_reader(app))
    # Start UDP discovery announcer
    announcer = ServerAnnouncer(server_host=app["host"], server_port=app["port"],
                                server_id=app["server_id"],
                                interval=app["announce_interval"])
    await announcer.start()
    app["announcer"] = announcer


async def cleanup_background_tasks(app: web.Application):
    app["time_broadcaster"].cancel()
    await app["time_broadcaster"]
    app["console_reader"].cancel()
    await app["announcer"].stop()
    if gui_process and gui_process.poll() is None:
        gui_process.kill()


# -- App Setup -------------------------------------------------------------
def create_app(args) -> web.Application:
    load_users()
    app = web.Application()
    app["server_id"] = args.id
    app["host"] = args.host
    app["port"] = args.port
    app["broadcast_interval"] = args.interval
    app["announce_interval"] = args.announce
    app["exam_duration"] = args.exam_duration
    app["exam_files"] = args.exam_files
    
    app.router.add_get("/health", health)
    app.router.add_post("/login", login_handler)
    app.router.add_get("/exam/config", exam_config)
    app.router.add_get("/exam/files", exam_files)
    app.router.add_get("/ws", websocket_handler)
    app.on_startup.append(start_background_tasks)
    app.on_cleanup.append(cleanup_background_tasks)
    return app


# -- Validation ------------------------------------------------------------
def validate_args(args):
    errors = []
    if not 1 <= args.port <= 65535:
        errors.append(f"--port must be 1-65535, got {args.port}")
    if args.interval <= 0:
        errors.append(f"--interval must be > 0, got {args.interval}")
    if args.announce <= 0:
        errors.append(f"--announce must be > 0, got {args.announce}")
    if not args.id.strip():
        errors.append("--id cannot be empty")
    if errors:
        for e in errors:
            print(f"[ERROR] {e}")
        sys.exit(1)


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Server")
    parser.add_argument("--id",       default="default", help="Server identifier (clients must match)")
    parser.add_argument("--host",     default="0.0.0.0", help="Host to bind to (default: 0.0.0.0)")
    parser.add_argument("--port",     default=8080, type=int, help="Port to listen on (default: 8080)")
    parser.add_argument("--interval", default=10, type=float, help="Time broadcast/sync interval in seconds (default: 10)")
    parser.add_argument("--announce", default=3, type=float, help="Discovery beacon interval in seconds (default: 3)")
    parser.add_argument("--exam-duration", default=45, type=int, help="Exam duration in minutes (default: 45)")
    parser.add_argument("--exam-files", default=None, type=str, help="Path to a .zip file containing exam materials")
    parser.add_argument("--gui", action="store_true", help="Launch the server companion GUI monitor")
    args = parser.parse_args()

    validate_args(args)
    
    if args.gui:
        script_dir = os.path.dirname(os.path.abspath(__file__))
        gui_path = os.path.join(script_dir, "server_gui.py")
        print(f"[GUI] Launching Server Monitor UI...")
        try:
            gui_process = subprocess.Popen(
                [sys.executable, gui_path], 
                stdin=subprocess.PIPE, 
                stdout=subprocess.PIPE,
                text=True,
                bufsize=1  # Line buffered
            )
        except Exception as e:
            print(f"[GUI] Failed to launch gui: {e}")

    # Check for duplicate server with same ID
    dup = asyncio.run(check_duplicate_server(args.id, timeout=5.0))
    if dup:
        host, port = dup
        print(f"[ERROR] A server with id '{args.id}' is already running at {host}:{port}")
        print("[ERROR] Use a different --id or stop the other server first.")
        sys.exit(1)
    print(f"[CHECK] No duplicate found, safe to start.\n")

    print(f"Starting server '{args.id}' on http://{args.host}:{args.port}")
    print(f"  HTTP  ->  GET /health")
    print(f"  WS    ->  ws://{args.host}:{args.port}/ws")

    try:
        web.run_app(create_app(args), host=args.host, port=args.port)
    except OSError as e:
        if e.errno == errno.EADDRINUSE or "address already in use" in str(e).lower():
            print(f"\n[ERROR] Port {args.port} is already in use.")
            print(f"[ERROR] Use --port to pick a different port.")
        else:
            print(f"\n[ERROR] {e}")
        sys.exit(1)

