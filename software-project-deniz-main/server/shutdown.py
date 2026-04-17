import asyncio
import traceback
from dataclasses import dataclass
from typing import Awaitable, Callable

from common import events
from .state import state


SHUTDOWN_GRACE_SECONDS = 2.0


@dataclass
class ShutdownStep:
    name: str
    action: Callable[[], Awaitable[None]]


class ServerShutdownRoutine:
    def __init__(self, app):
        self.app = app
        self.steps: list[ShutdownStep] = []
        self._register_default_steps()

    def add_step(self, name: str, action: Callable[[], Awaitable[None]]):
        self.steps.append(ShutdownStep(name=name, action=action))

    def _register_default_steps(self):
        self.add_step("Request process reports", self._request_process_reports)
        self.add_step("Request screen saves", self._request_screen_saves)
        self.add_step("Wait for client flush", self._wait_for_clients)

    async def run(self):
        if not state.clients:
            print("[SHUTDOWN] No connected clients. Shutdown routine skipped.")
            return

        print("[SHUTDOWN] Running shutdown routine...")
        for step in self.steps:
            try:
                print(f"[SHUTDOWN] {step.name}")
                await step.action()
            except Exception:
                print(f"[SHUTDOWN] Step failed: {step.name}")
                traceback.print_exc()

        print("[SHUTDOWN] Shutdown routine complete.")

    async def _request_process_reports(self):
        count = await self._broadcast(events.get_processes())
        print(f"[SHUTDOWN] Requested process reports from {count} client(s).")

    async def _request_screen_saves(self):
        count = await self._broadcast(events.savescreen())
        print(f"[SHUTDOWN] Requested screen saves from {count} client(s).")

    async def _wait_for_clients(self):
        await asyncio.sleep(self.app.get("shutdown_grace_seconds", SHUTDOWN_GRACE_SECONDS))

    async def _broadcast(self, payload: str) -> int:
        sent = 0
        dead_clients = []

        for client_id, data in list(state.clients.items()):
            try:
                await data["ws"].send_str(payload)
                sent += 1
            except Exception:
                dead_clients.append(client_id)

        for client_id in dead_clients:
            state.clients.pop(client_id, None)

        return sent
