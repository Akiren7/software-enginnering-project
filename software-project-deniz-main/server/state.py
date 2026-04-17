import json
import os
from typing import Iterable

USERS_FILE = "data/server/server_users.json"
ALLOWED_USERS_FILE = "allowed_users.json"
PROCESS_BLACKLIST_FILE = "data/server/process_blacklist.txt"

class ServerState:
    def __init__(self):
        self.clients: dict[str, dict] = {}
        self.users_db: dict[str, dict] = {}
        self.allowed_users: dict[str, str] = {}
        self.process_blacklist: list[str] = []
        self.process_blacklist_version: str = ""
        self.gui_process = None

    def load_users(self):
        if os.path.exists(USERS_FILE):
            try:
                with open(USERS_FILE, "r") as f:
                    self.users_db = json.load(f)
                for user in self.users_db.values():
                    self.ensure_user_defaults(user)
            except Exception as e:
                print(f"[!] Failed to load {USERS_FILE}: {e}")
                self.users_db = {}
                
        if os.path.exists(ALLOWED_USERS_FILE):
            try:
                with open(ALLOWED_USERS_FILE, "r") as f:
                    self.allowed_users = json.load(f)
            except Exception as e:
                print(f"[!] Failed to load {ALLOWED_USERS_FILE}: {e}")
                self.allowed_users = {}

        self.load_process_blacklist()

    def save_users(self):
        os.makedirs(os.path.dirname(USERS_FILE), exist_ok=True)
        try:
            with open(USERS_FILE, "w") as f:
                json.dump(self.users_db, f, indent=2)
        except Exception as e:
            print(f"[!] Failed to save {USERS_FILE}: {e}")

    def load_process_blacklist(self):
        self.ensure_process_blacklist_file()
        try:
            with open(PROCESS_BLACKLIST_FILE, "r", encoding="utf-8") as blacklist_file:
                self.process_blacklist = self._parse_process_blacklist_lines(blacklist_file)
            self.process_blacklist_version = self._blacklist_version_stamp()
        except Exception as e:
            print(f"[!] Failed to load {PROCESS_BLACKLIST_FILE}: {e}")
            self.process_blacklist = []
            self.process_blacklist_version = self._blacklist_version_stamp()

    def ensure_process_blacklist_file(self):
        os.makedirs(os.path.dirname(PROCESS_BLACKLIST_FILE), exist_ok=True)
        if os.path.exists(PROCESS_BLACKLIST_FILE):
            return

        default_lines = [
            "# One process name per line.",
            "# Matching is case-insensitive and checks the process name/basename.",
            "# Example:",
            "# discord.exe",
            "# steam.exe",
            "",
        ]
        try:
            with open(PROCESS_BLACKLIST_FILE, "w", encoding="utf-8") as blacklist_file:
                blacklist_file.write("\n".join(default_lines))
        except Exception as e:
            print(f"[!] Failed to initialize {PROCESS_BLACKLIST_FILE}: {e}")

    def ensure_user_defaults(self, user: dict):
        user.setdefault("time_spent_seconds", 0)
        user.setdefault("exam_started", False)
        user.setdefault("exam_finished", False)
        user.setdefault("extra_time_seconds", 0)
        user.setdefault("banned", False)
        user.setdefault("kick_count", 0)
        user.setdefault("last_action", "")
        user.setdefault("computer_name", "")
        user.setdefault("submitted_at", "")
        user.setdefault("submission_name", "")
        user.setdefault("submission_path", "")
        user.setdefault("submission_size_bytes", 0)
        user.setdefault("blacklist_catch_count", 0)
        user.setdefault("last_blacklist_match", [])

    def is_valid_session_uuid(self, client_id: str) -> bool:
        return any(user.get("uuid") == client_id for user in self.users_db.values())

    def find_user_by_uuid(self, client_id: str):
        for login_id, user in self.users_db.items():
            if user.get("uuid") == client_id:
                return login_id, user
        return None, None

    def get_gui_process(self):
        process = self.gui_process
        if process and process.poll() is None:
            return process
        return None

    def resolve_user(self, target: str):
        if target in self.users_db:
            return target, self.users_db[target]

        login_id, user = self.find_user_by_uuid(target)
        if user:
            return login_id, user

        client_id, _ = self.resolve_client(target)
        if client_id:
            return self.find_user_by_uuid(client_id)

        return None, None

    def resolve_client(self, target: str):
        """
        Find a client by:
        1. Full UUID
        2. Short ID (first 8 chars)
        3. IP Address
        Returns (full_id, client_data) or (None, None)
        """
        # 1. Check Full ID
        if target in self.clients:
            return target, self.clients[target]

        # 2. Check Short ID and IP
        for cid, data in self.clients.items():
            if data["short_id"] == target or data["ip"] == target:
                return cid, data

        return None, None

    def blacklist_payload(self) -> dict:
        return {
            "entries": list(self.process_blacklist),
            "version": self.process_blacklist_version,
        }

    def _parse_process_blacklist_lines(self, lines: Iterable[str]) -> list[str]:
        entries = []
        seen = set()
        for raw_line in lines:
            entry = raw_line.strip()
            if not entry or entry.startswith("#"):
                continue
            normalized = entry.lower()
            if normalized in seen:
                continue
            seen.add(normalized)
            entries.append(entry)
        return entries

    def _blacklist_version_stamp(self) -> str:
        try:
            return str(os.stat(PROCESS_BLACKLIST_FILE).st_mtime_ns)
        except OSError:
            return "0"

state = ServerState()
