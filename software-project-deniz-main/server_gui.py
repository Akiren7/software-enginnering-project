import json
import sys
import tkinter as tk
from datetime import datetime
from pathlib import Path
from threading import Thread
from tkinter import messagebox, ttk

from common.manager_support import install_close_guard
from common.runtime_logging import setup_runtime_logging


def _format_bytes(size_bytes: int) -> str:
    size = float(max(0, size_bytes))
    units = ["B", "KB", "MB", "GB"]
    unit_index = 0
    while size >= 1024 and unit_index < len(units) - 1:
        size /= 1024
        unit_index += 1
    if unit_index == 0:
        return f"{int(size)} {units[unit_index]}"
    return f"{size:.1f} {units[unit_index]}"


def _format_remaining(seconds: int) -> str:
    minutes, remaining_seconds = divmod(seconds, 60)
    return f"{minutes:02d}:{remaining_seconds:02d}"


def _detail_lines(client_id: str, data: dict) -> list[str]:
    time_spent = int(data.get("time_spent_seconds", 0))
    extra_time = int(data.get("extra_time_seconds", 0))
    minutes_spent, seconds_spent = divmod(time_spent, 60)
    extra_minutes, extra_seconds = divmod(extra_time, 60)
    return [
        f"Login ID: {data.get('login_id', 'Unknown')}",
        f"UUID: {client_id}",
        f"Computer Name: {data.get('computer_name') or '-'}",
        f"Short ID: {data.get('short_id') or '-'}",
        f"Connection: {data.get('connection_status', 'Unknown')}",
        f"Exam State: {data.get('exam_state', 'Unknown')}",
        f"Banned: {'Yes' if data.get('banned') else 'No'}",
        f"Remaining: {_format_remaining(data.get('remaining', 0))}",
        f"Time Spent: {minutes_spent:02d}:{seconds_spent:02d}",
        f"Extra Time: {extra_minutes:02d}:{extra_seconds:02d}",
        f"Kick Count: {data.get('kick_count', 0)}",
        f"Blacklist Catches: {data.get('blacklist_catch_count', 0)}",
        f"Last Blacklist Match: {', '.join(data.get('last_blacklist_match', [])) or '-'}",
        f"Last Action: {data.get('last_action') or '-'}",
        f"IP Address: {data.get('ip') or '-'}",
        f"Submission: {data.get('submission_name') or '-'}",
        f"Submission Size: {_format_bytes(int(data.get('submission_size_bytes', 0)))}",
        f"Submitted At: {data.get('submitted_at') or '-'}",
        f"Submission Path: {data.get('submission_path') or '-'}",
    ]


class ServerGUI(tk.Tk):
    def __init__(self):
        super().__init__()
        self.clients_data = {}
        self.tree_items = {}
        self.open_windows = {}
        self.server_info = {}

        self.title("Server Monitor Dashboard")
        self.geometry("800x400")
        install_close_guard(self, self.on_close_request, bind_all=True)

        self._build_layout()
        self.after(1000, self.update_timers)

    def _build_layout(self):
        content = ttk.Frame(self)
        content.pack(fill=tk.BOTH, expand=True, padx=10, pady=10)

        left_panel = ttk.Frame(content)
        left_panel.pack(side=tk.LEFT, fill=tk.BOTH, expand=True)

        self._build_server_info_panel(left_panel)
        self._build_tree_area(left_panel)
        self._build_log_area(left_panel)
        self._build_command_bar()
        self._build_stats_bar()
        self._build_action_panel(content)

    def _build_server_info_panel(self, parent):
        info_frame = ttk.LabelFrame(parent, text="Server Info")
        info_frame.pack(side=tk.TOP, fill=tk.X, pady=(0, 10))

        action_frame = ttk.Frame(info_frame, padding=(8, 8, 8, 0))
        action_frame.pack(fill=tk.X)

        self.start_exam_button = ttk.Button(
            action_frame,
            text="Start Exam",
            command=self.start_exam_globally,
        )
        self.start_exam_button.pack(side=tk.LEFT)

        self.finish_exam_button = ttk.Button(
            action_frame,
            text="Finish Exam",
            command=self.finish_exam_globally,
        )
        self.finish_exam_button.pack(side=tk.LEFT, padx=(8, 0))

        blacklist_frame = ttk.Frame(info_frame, padding=(8, 6, 8, 0))
        blacklist_frame.pack(fill=tk.X)

        self.edit_blacklist_button = ttk.Button(
            blacklist_frame,
            text="Edit Blacklist",
            command=self.edit_blacklist,
        )
        self.edit_blacklist_button.pack(side=tk.LEFT)

        self.apply_blacklist_button = ttk.Button(
            blacklist_frame,
            text="Apply Blacklist",
            command=self.apply_blacklist,
        )
        self.apply_blacklist_button.pack(side=tk.LEFT, padx=(8, 0))

        self.server_info_var = tk.StringVar(value="Waiting for server state...")
        info_label = ttk.Label(
            info_frame,
            textvariable=self.server_info_var,
            justify=tk.LEFT,
            padding=8,
        )
        info_label.pack(fill=tk.X)

    def _build_tree_area(self, parent):
        tree_frame = ttk.Frame(parent)
        tree_frame.pack(side=tk.TOP, fill=tk.BOTH, expand=True)

        columns = ("login_id", "status", "remaining", "uuid")
        self.tree = ttk.Treeview(
            tree_frame,
            columns=columns,
            show="headings",
            selectmode="browse",
        )
        self.tree.heading("login_id", text="Login ID", anchor=tk.W)
        self.tree.heading("status", text="Status", anchor=tk.CENTER)
        self.tree.heading("remaining", text="Remaining Time", anchor=tk.CENTER)
        self.tree.heading("uuid", text="UUID", anchor=tk.W)

        self.tree.column("login_id", width=150)
        self.tree.column("status", width=100, anchor=tk.CENTER)
        self.tree.column("remaining", width=120, anchor=tk.CENTER)
        self.tree.column("uuid", width=250)

        y_scroll = ttk.Scrollbar(tree_frame, orient=tk.VERTICAL, command=self.tree.yview)
        self.tree.configure(yscrollcommand=y_scroll.set)

        self.tree.pack(side=tk.LEFT, fill=tk.BOTH, expand=True)
        y_scroll.pack(side=tk.RIGHT, fill=tk.Y)

    def _build_log_area(self, parent):
        log_frame = ttk.LabelFrame(parent, text="Live Client Message Log")
        log_frame.pack(side=tk.BOTTOM, fill=tk.BOTH, expand=True, pady=(10, 0))

        self.log_text = tk.Text(log_frame, height=6, state=tk.DISABLED, wrap=tk.WORD)
        log_scroll = ttk.Scrollbar(log_frame, orient=tk.VERTICAL, command=self.log_text.yview)
        self.log_text.configure(yscrollcommand=log_scroll.set)

        self.log_text.pack(side=tk.LEFT, fill=tk.BOTH, expand=True)
        log_scroll.pack(side=tk.RIGHT, fill=tk.Y)

    def _build_command_bar(self):
        cmd_frame = ttk.Frame(self, padding=5)
        cmd_frame.pack(side=tk.BOTTOM, fill=tk.X)

        ttk.Label(cmd_frame, text="Admin Command:").pack(side=tk.LEFT, padx=5)
        self.cmd_entry = ttk.Entry(cmd_frame)
        self.cmd_entry.pack(side=tk.LEFT, fill=tk.X, expand=True, padx=5)
        self.cmd_entry.bind("<Return>", lambda _: self.send_console_command())

        ttk.Button(cmd_frame, text="Execute", command=self.send_console_command).pack(
            side=tk.RIGHT,
            padx=5,
        )

    def _build_stats_bar(self):
        self.stats_var = tk.StringVar(value="Connections Managed: 0 | Active: 0 | Disconnected: 0")
        stats_label = ttk.Label(self, textvariable=self.stats_var, relief=tk.SUNKEN, padding=5)
        stats_label.pack(side=tk.BOTTOM, fill=tk.X)

    def _build_action_panel(self, parent):
        action_frame = ttk.Frame(parent)
        action_frame.pack(side=tk.RIGHT, fill=tk.Y, padx=(10, 0))

        ttk.Button(action_frame, text="Show Info", command=self.show_info).pack(fill=tk.X, pady=5)
        ttk.Button(action_frame, text="Options", command=self.show_options).pack(fill=tk.X, pady=5)

    def _selected_client_id(self):
        selected = self.tree.selection()
        if not selected:
            return None

        item_id = selected[0]
        values = self.tree.item(item_id, "values")
        return values[3] if values else None

    def _selected_client_data(self):
        client_id = self._selected_client_id()
        if not client_id:
            return None, None
        return client_id, self.clients_data.get(client_id)

    def update_timers(self):
        for client_id, data in self.clients_data.items():
            if data.get("exam_state") != "Running":
                continue
            if data.get("remaining", 0) <= 0:
                continue

            data["remaining"] -= 1
            self._upsert_tree_item(client_id, data)

        self.after(1000, self.update_timers)

    def show_info(self):
        client_id, data = self._selected_client_data()
        if not client_id:
            messagebox.showinfo("Info", "Select a client first.")
            return
        data = data or {}
        window_key = ("info", client_id)
        if self._focus_existing_window(window_key):
            return

        self._open_detail_window(
            window_key=window_key,
            title=f"Info: {data.get('login_id', 'Unknown')}",
            lines=_detail_lines(client_id, data),
        )

    def show_options(self):
        client_id, data = self._selected_client_data()
        if not client_id:
            messagebox.showinfo("Options", "Select a client first.")
            return
        data = data or {}

        window_key = ("options", client_id)
        if self._focus_existing_window(window_key):
            return

        top = tk.Toplevel(self)
        top.title(f"Options: {data.get('login_id', 'Unknown')}")
        top.geometry("340x360")
        self._register_window(window_key, top)

        ttk.Label(top, text="User Actions:").pack(pady=10)
        ttk.Button(
            top,
            text="Kick Client",
            command=lambda: self._send_window_command(top, "kick", client_id),
            state=tk.NORMAL if data.get("connection_status") == "Connected" else tk.DISABLED,
        ).pack(fill=tk.X, padx=20, pady=5)
        ttk.Button(
            top,
            text="Ban User",
            command=lambda: self._send_window_command(top, "ban", client_id),
        ).pack(fill=tk.X, padx=20, pady=5)
        ttk.Button(
            top,
            text="Unban User",
            command=lambda: self._send_window_command(top, "unban", client_id),
        ).pack(fill=tk.X, padx=20, pady=5)

        ttk.Separator(top, orient=tk.HORIZONTAL).pack(fill=tk.X, padx=20, pady=8)

        ttk.Label(top, text="Connected Client Commands:").pack(pady=4)
        ttk.Button(
            top,
            text="Request Save Screen",
            command=lambda: self._send_client_command(top, "savescreen", client_id),
            state=tk.NORMAL if data.get("connection_status") == "Connected" else tk.DISABLED,
        ).pack(fill=tk.X, padx=20, pady=5)
        ttk.Button(
            top,
            text="Request Process Report",
            command=lambda: self._send_client_command(top, "get_processes", client_id),
            state=tk.NORMAL if data.get("connection_status") == "Connected" else tk.DISABLED,
        ).pack(fill=tk.X, padx=20, pady=5)

        add_time_frame = ttk.Frame(top, padding=(20, 10))
        add_time_frame.pack(fill=tk.X)

        ttk.Label(add_time_frame, text="Add Minutes:").pack(side=tk.LEFT)
        minutes_entry = ttk.Entry(add_time_frame, width=8)
        minutes_entry.pack(side=tk.LEFT, padx=8)
        ttk.Button(
            add_time_frame,
            text="Apply",
            command=lambda: self._send_add_time(top, client_id, minutes_entry.get()),
        ).pack(side=tk.LEFT)

    def _send_client_command(self, window, command: str, client_id: str):
        print(json.dumps({"cmd": command, "uuid": client_id}), flush=True)
        window.destroy()
        self._append_log(f"[ADMIN] Sent {command} to {client_id}")

    def _send_window_command(self, window, command: str, client_id: str):
        print(json.dumps({"cmd": command, "uuid": client_id}), flush=True)
        window.destroy()
        self._append_log(f"[ADMIN] Sent {command} to {client_id}")

    def _send_add_time(self, window, client_id: str, minutes_text: str):
        minutes_text = minutes_text.strip()
        if not minutes_text:
            messagebox.showwarning("Add Time", "Enter a number of minutes first.")
            return

        print(
            json.dumps({"type": "console_command", "command": f"/addtime {client_id} {minutes_text}"}),
            flush=True,
        )
        window.destroy()
        self._append_log(f"[ADMIN] Added {minutes_text} minute(s) to {client_id}")

    def start_exam_globally(self):
        print(json.dumps({"cmd": "start_exam_global"}), flush=True)
        self._append_log("[ADMIN] Enabled exam start globally")

    def finish_exam_globally(self):
        print(json.dumps({"cmd": "finish_exam_global"}), flush=True)
        self._append_log("[ADMIN] Requested global exam finish")

    def edit_blacklist(self):
        print(json.dumps({"cmd": "edit_blacklist"}), flush=True)
        self._append_log("[ADMIN] Opening process blacklist file")

    def apply_blacklist(self):
        print(json.dumps({"cmd": "apply_blacklist"}), flush=True)
        self._append_log("[ADMIN] Applying process blacklist")

    def _open_detail_window(self, window_key, title: str, lines: list[str]):
        top = tk.Toplevel(self)
        top.title(title)
        top.geometry("460x360")
        self._register_window(window_key, top)

        frame = ttk.Frame(top, padding=12)
        frame.pack(fill=tk.BOTH, expand=True)

        details = tk.Text(frame, wrap=tk.WORD, height=12)
        details.pack(fill=tk.BOTH, expand=True)
        details.insert(tk.END, "\n".join(lines))
        details.config(state=tk.DISABLED)

    def _register_window(self, window_key, window):
        self.open_windows[window_key] = window
        window.bind("<Destroy>", lambda _event: self._forget_window(window_key, window))

    def _forget_window(self, window_key, window):
        existing = self.open_windows.get(window_key)
        if existing is window:
            self.open_windows.pop(window_key, None)

    def _focus_existing_window(self, window_key) -> bool:
        window = self.open_windows.get(window_key)
        if not window or not window.winfo_exists():
            self.open_windows.pop(window_key, None)
            return False

        window.lift()
        window.focus_force()
        return True

    def send_console_command(self):
        command = self.cmd_entry.get().strip()
        if not command:
            return

        if not command.startswith("/"):
            command = "/" + command

        print(json.dumps({"type": "console_command", "command": command}), flush=True)
        self.cmd_entry.delete(0, tk.END)
        self._append_log(f"[ADMIN] Executing: {command}")

    def _append_log(self, line: str):
        self.log_text.config(state=tk.NORMAL)
        self.log_text.insert(tk.END, line + "\n")
        self.log_text.see(tk.END)
        self.log_text.config(state=tk.DISABLED)

    def on_close_request(self):
        messagebox.showwarning(
            "Dashboard Protected",
            "The monitoring dashboard is protected while the server session is active.\n\n"
            "Use the Server Manager or server commands to control the session instead of OS close shortcuts.",
        )

    def log_message(self, client_id, message):
        data = self.clients_data.get(client_id, {})
        display_name = data.get("login_id", client_id[:8])
        timestamp = datetime.now().strftime("%H:%M:%S")
        self._append_log(f"[{timestamp}] {display_name}: {message}")

    def process_state_update(self, payload):
        self.server_info = payload.get("server", {})
        self._update_server_info_panel()

        clients = payload.get("clients", [])
        active_count = 0

        for client in clients:
            client_id = client["uuid"]
            self.clients_data[client_id] = {
                **client,
                "remaining": int(float(client.get("remaining", 0))),
            }
            if client.get("connection_status") == "Connected":
                active_count += 1
            self._upsert_tree_item(client_id, self.clients_data[client_id])

        total_count = len(clients)
        disconnected_count = total_count - active_count
        self.stats_var.set(
            f"Connections Managed: {total_count} | Active: {active_count} | "
            f"Disconnected: {disconnected_count}"
        )

    def _update_server_info_panel(self):
        info = self.server_info
        if not info:
            self.server_info_var.set("Waiting for server state...")
            return

        exam_files_path = info.get("exam_files_path") or "-"
        has_exam_files = "Yes" if info.get("has_exam_files") else "No"
        exam_phase = str(info.get("exam_phase", "waiting")).title()
        start_enabled = "Open" if info.get("exam_start_enabled") else "Locked"
        self.start_exam_button.config(
            state=tk.DISABLED if info.get("exam_phase") != "waiting" else tk.NORMAL
        )
        self.finish_exam_button.config(
            state=tk.NORMAL if info.get("exam_phase") == "running" else tk.DISABLED
        )
        text = (
            f"ID: {info.get('server_id', '-')}"
            f"    Host: {info.get('host', '-')}"
            f"    Port: {info.get('port', '-')}\n"
            f"Exam Phase: {exam_phase}"
            f"    Exam Start: {start_enabled}"
            f"    Broadcast: {info.get('broadcast_interval', '-')}s"
            f"    Announce: {info.get('announce_interval', '-')}s\n"
            f"Exam Duration: {info.get('exam_duration_minutes', '-')} min    "
            f"Exam Files: {has_exam_files}"
            f"    Path: {exam_files_path}\n"
            f"Blacklist Entries: {info.get('process_blacklist_count', 0)}"
            f"    Version: {info.get('process_blacklist_version', '-')}"
            f"    File: {info.get('process_blacklist_file', '-')}"
        )
        self.server_info_var.set(text)

    def _upsert_tree_item(self, client_id: str, data: dict):
        values = (
            data["login_id"],
            data.get("status_label", "Unknown"),
            _format_remaining(data.get("remaining", 0)),
            client_id,
        )

        item_id = self.tree_items.get(client_id)
        if item_id and self.tree.exists(item_id):
            self.tree.item(item_id, values=values)
            return

        self.tree_items[client_id] = self.tree.insert("", tk.END, values=values)


def ipc_reader(app: ServerGUI):
    """Read lines from stdin (JSON objects sent by the server process)."""
    for line in iter(sys.stdin.readline, ""):
        line = line.strip()
        if not line:
            continue

        try:
            msg = json.loads(line)
        except json.JSONDecodeError as e:
            print(f"[DEBUG] GUI IPC Error: {e}", file=sys.stderr)
            continue

        message_type = msg.get("type")
        if message_type == "state_update":
            app.after(0, app.process_state_update, msg)
        elif message_type == "client_message":
            app.after(0, app.log_message, msg.get("uuid"), msg.get("text"))


if __name__ == "__main__":
    setup_runtime_logging(
        "server_gui",
        Path(__file__).resolve().parent / "data" / "logs" / "server",
    )
    app = ServerGUI()
    reader_thread = Thread(target=ipc_reader, args=(app,), daemon=True)
    reader_thread.start()
    app.mainloop()
