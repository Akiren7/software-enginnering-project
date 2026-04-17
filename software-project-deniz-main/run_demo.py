#!/usr/bin/env python3
"""
Cross-platform demo launcher.

Starts one server and three clients, each in a separate terminal window
(matching the behavior of the original run_demo.bat).

Works on Windows (cmd), macOS (Terminal.app), and Linux (gnome-terminal, xterm, etc).
"""

import argparse
import os
import platform
import shlex
import subprocess
import sys
import time

from common.discovery import ServerAnnouncer

SERVER_ID = "my-server"
DEFAULT_PORT = 8080
CLIENT_COUNT = 3

def spawn_terminal(title: str, command: str):
    """Launch a new terminal window to run the given command."""
    system = platform.system()
    
    if system == "Windows":
        subprocess.Popen(
            ["cmd.exe", "/c", "start", title, "cmd.exe", "/k", command]
        )
        
    elif system == "Darwin":
        # macOS: Use AppleScript to tell Terminal.app to open a new window and run the command
        # The command needs to be properly escaped
        escaped_cmd = command.replace("\\", "\\\\").replace('"', '\\"')
        script = f'''
        tell application "Terminal"
            activate
            do script "{escaped_cmd}"
        end tell
        '''
        subprocess.Popen(["osascript", "-e", script])
        
    elif system == "Linux":
        # Try common Linux terminal emulators
        terminals = [
            ["gnome-terminal", "--title", title, "--", "bash", "-c", f"{command}; exec bash"],
            ["konsole", "-e", "bash", "-c", f"{command}; exec bash"],
            ["xfce4-terminal", "-T", title, "-e", f"bash -c '{command}; exec bash'"],
            ["xterm", "-title", title, "-e", f"bash -c '{command}; exec bash'"]
        ]
        
        success = False
        for term_cmd in terminals:
            try:
                subprocess.Popen(term_cmd)
                success = True
                break
            except FileNotFoundError:
                continue
                
        if not success:
            print(f"[ERROR] Could not find a suitable terminal emulator on Linux to launch '{title}'.")
            print(f"        Tried: {[t[0] for t in terminals]}")

def parse_args():
    parser = argparse.ArgumentParser(description="Launch the demo server and clients in separate terminals.")
    parser.add_argument(
        "--manual-ip-connect",
        action="store_true",
        help="Launch clients with an explicit --host/--port instead of UDP discovery.",
    )
    parser.add_argument(
        "--connect-host",
        default=None,
        help=(
            "Manual server host/IP for direct client connections. "
            "Implies --manual-ip-connect. If omitted, the launcher auto-detects the local IP."
        ),
    )
    parser.add_argument(
        "--port",
        default=DEFAULT_PORT,
        type=int,
        help=f"Server port to use for the demo (default: {DEFAULT_PORT}).",
    )
    return parser.parse_args()


def validate_args(args):
    if not 1 <= args.port <= 65535:
        raise SystemExit(f"[ERROR] --port must be 1-65535, got {args.port}")


def build_terminal_command(script_dir: str, python_cmd: str, python_args: list[str]) -> str:
    if platform.system() == "Windows":
        quoted_args = subprocess.list2cmdline([python_cmd, *python_args])
        return f'cd /d "{script_dir}" && {quoted_args}'

    quoted_args = " ".join(shlex.quote(part) for part in [python_cmd, *python_args])
    return f"cd {shlex.quote(script_dir)} && {quoted_args}"


def resolve_connect_host(args):
    connect_host = args.connect_host.strip() if args.connect_host else None
    if not (args.manual_ip_connect or connect_host):
        return None
    return connect_host or ServerAnnouncer._get_local_ip()


def main():
    args = parse_args()
    validate_args(args)

    # Ensure commands run in the script's directory
    script_dir = os.path.dirname(os.path.abspath(__file__))
    python_cmd = sys.executable
    connect_host = resolve_connect_host(args)
    manual_ip_connect = connect_host is not None

    print(f"[LAUNCHER] Spawning UI terminals... (OS: {platform.system()})\n")
    if manual_ip_connect:
        print(f"[LAUNCHER] Client mode: direct IP connect to {connect_host}:{args.port}")
    else:
        print(f"[LAUNCHER] Client mode: discovery (server port {args.port})")
    print()

    # 1. Start Server
    print(f"-> Starting Server ({SERVER_ID})")
    server_cmd = build_terminal_command(
        script_dir,
        python_cmd,
        ["-m", "server.main", "--id", SERVER_ID, "--reset", "--gui", "--port", str(args.port)],
    )
    spawn_terminal("Server", server_cmd)

    # Give server a moment to start
    time.sleep(1.5)

    # 2. Start Clients
    for i in range(1, CLIENT_COUNT + 1):
        print(f"-> Starting Client {i}")
        client_args = [
            "-m",
            "client.main",
            "--id",
            SERVER_ID,
            "--login-id",
            f"student{i}",
            "--password",
            f"secret{i}",
            "--no-record",
        ]
        if manual_ip_connect:
            client_args.extend(["--host", connect_host, "--port", str(args.port)])
        client_cmd = build_terminal_command(script_dir, python_cmd, client_args)
        spawn_terminal(f"Client {i}", client_cmd)
        time.sleep(0.5)

    print("\n[LAUNCHER] All windows spawned. You can close this window now.")

if __name__ == "__main__":
    main()
