import argparse
import asyncio
import sys
from pathlib import Path

import aiohttp

from common.discovery import discover_server_with_local_fallback
from common.runtime_logging import install_asyncio_exception_logging, setup_runtime_logging
from custommodules.replay_recorder import ReplayRecorder
from .auth import check_health, perform_login
from .exam import fetch_exam_prep
from .ws_client import run_ws


def _run_blocking(loop: asyncio.AbstractEventLoop, func):
    return loop.run_in_executor(None, func)


class RecorderManager:
    def __init__(self, record_enabled: bool):
        self.record_enabled = record_enabled
        self.recorder = None
        self.session_uuid = None

    async def sync_session(self, session_uuid: str):
        if self.session_uuid == session_uuid and self.recorder is not None:
            return self.recorder

        loop = asyncio.get_running_loop()
        await self.stop()

        self.session_uuid = session_uuid
        self.recorder = ReplayRecorder(session_uuid=session_uuid)
        if self.record_enabled:
            await _run_blocking(loop, self.recorder.start)
        return self.recorder

    async def stop(self):
        if not self.record_enabled or not self.recorder:
            return

        loop = asyncio.get_running_loop()
        await _run_blocking(loop, self.recorder.stop)
        self.recorder = None


async def discover_loop(server_id: str, timeout: float, port: int):
    """Keep searching until we find a server."""
    while True:
        result = await discover_server_with_local_fallback(
            server_id=server_id,
            timeout=timeout,
            local_port=port,
        )
        if result is not None:
            return result
        print("No server found yet, retrying...")


async def resolve_server_target(args) -> tuple[str, int]:
    if args.host:
        print(f"[DIRECT] Connecting to {args.host}:{args.port}")
        return args.host, args.port

    if getattr(args, "check_login", False):
        server_info = await discover_server_with_local_fallback(
            args.id,
            args.timeout,
            local_port=args.port,
        )
        if not server_info:
            print(f"\n[FATAL] Could not discover server '{args.id}' on the local network.")
            sys.exit(1)
        return server_info

    return await discover_loop(args.id, args.timeout, args.port)


async def establish_session(base_url: str, args, recorder_manager: RecorderManager) -> str:
    session_uuid = await perform_login(base_url, args.login_id, args.password)

    if getattr(args, "check_login", False):
        print("[+] Credentials verified successfully.")
        sys.exit(0)

    await recorder_manager.sync_session(session_uuid)
    print(f"[LOGIN] Assigned session UUID: {session_uuid}")
    return session_uuid


async def prepare_client(base_url: str, session_uuid: str):
    await fetch_exam_prep(base_url, session_uuid)
    await check_health(base_url)


def build_base_url(host: str, port: int) -> str:
    return f"http://{host}:{port}"


def build_ws_url(host: str, port: int, session_uuid: str) -> str:
    return f"ws://{host}:{port}/ws?id={session_uuid}"


async def main_loop(args):
    install_asyncio_exception_logging(asyncio.get_running_loop())
    recorder_manager = RecorderManager(record_enabled=args.record)
    active_session_uuid = None

    print(f"=== Client [{args.login_id}] (awaiting session assignment) ===\n")

    try:
        while True:
            host, port = await resolve_server_target(args)
            base_url = build_base_url(host, port)

            try:
                session_uuid = await establish_session(base_url, args, recorder_manager)
                if active_session_uuid and active_session_uuid != session_uuid:
                    print(
                        f"[!] Server returned a different UUID ({session_uuid}) "
                        f"than active ({active_session_uuid}). Resyncing."
                    )
                active_session_uuid = session_uuid

                await prepare_client(base_url, session_uuid)

                print()
                submission_completed = await run_ws(
                    build_ws_url(host, port, session_uuid),
                    base_url,
                    session_uuid,
                    recorder_manager.recorder,
                )
                if submission_completed:
                    print("[EXAM] Submission complete. Exiting client.")
                    return
            except ValueError as e:
                print(f"\n[FATAL] {e}")
                sys.exit(1)
            except (aiohttp.ClientError, ConnectionError, OSError) as e:
                print(f"\n[!] Connection lost: {e}")

            print(f"[!] Reconnecting in {args.reconnect} seconds...\n")
            await asyncio.sleep(args.reconnect)
    finally:
        await recorder_manager.stop()


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
        for error in errors:
            print(f"[ERROR] {error}")
        sys.exit(1)


def main():
    setup_runtime_logging(
        "client_cli",
        Path(__file__).resolve().parent.parent / "data" / "logs" / "client",
    )

    parser = argparse.ArgumentParser(description="Client")
    parser.add_argument("--login-id", required=True, help="Client login ID")
    parser.add_argument("--password", required=True, help="Client password")
    parser.add_argument("--id", default="default", help="Server ID to connect to (default: default)")
    parser.add_argument("--host", default=None, help="Server host (skip discovery, connect directly)")
    parser.add_argument("--port", default=8080, type=int, help="Server port (default: 8080)")
    parser.add_argument("--timeout", default=15, type=float, help="Discovery timeout in seconds (default: 15)")
    parser.add_argument("--reconnect", default=3, type=float, help="Seconds to wait before reconnecting (default: 3)")
    parser.add_argument("--no-record", dest="record", action="store_false", help="Disable screen replay recorder")
    parser.add_argument("--check-login", action="store_true", help="Only validate server connection and login credentials, then exit.")
    parser.set_defaults(record=True)
    args = parser.parse_args()

    validate_args(args)

    try:
        asyncio.run(main_loop(args))
    except KeyboardInterrupt:
        print("\nBye!")


if __name__ == "__main__":
    main()
