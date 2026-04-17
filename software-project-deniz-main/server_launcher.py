import socket
import os
import sys
import tkinter as tk
from pathlib import Path
from tkinter import filedialog, messagebox, ttk

from common.discovery import ServerAnnouncer
from common.manager_support import (
    ConsoleWindow,
    ManagedProcessSession,
    apply_dpi_awareness,
    install_close_guard,
)


class ServerManager(tk.Tk):
    def __init__(self):
        super().__init__()
        self.project_dir = Path(__file__).resolve().parent
        self.process_session = ManagedProcessSession(
            session_name="server_cli_session",
            log_dir=self.project_dir / "data" / "logs" / "server" / "sessions",
        )
        self.console_window = ConsoleWindow(
            self,
            title="Server CLI",
            get_log_path=self._current_log_path,
            get_runtime_log_path=self._current_runtime_log_path,
            is_process_running=self._server_running,
            send_command=self._send_server_command,
            empty_message="Start the server to begin capturing session output.",
        )
        self._last_known_returncode = None

        self.title("Exam Server Manager")
        self.geometry("920x760")
        self.resizable(False, False)
        install_close_guard(self, self.on_close_request, bind_all=True)

        style = ttk.Style(self)
        style.configure(".", font=("Helvetica", 14))
        style.configure("TButton", padding=(14, 8))
        style.configure("TLabelframe.Label", font=("Helvetica", 13, "bold"))

        self.columnconfigure(1, weight=1)
        self.local_ip = ServerAnnouncer._get_local_ip()
        self.local_port = self._get_free_port()

        self.status_var = tk.StringVar(value="Server stopped.")
        self.summary_var = tk.StringVar(value="Session Summary: -")
        self.pid_var = tk.StringVar(value="PID: -")
        self.session_log_var = tk.StringVar(value="Session Output: -")
        self.runtime_log_var = tk.StringVar(value="Runtime JSONL: -")

        self._build_layout()
        self._poll_process_state()

    def _build_layout(self):
        info_frame = ttk.LabelFrame(self, text="Network Target")
        info_frame.grid(row=0, column=0, columnspan=2, sticky=tk.EW, padx=10, pady=10)
        ttk.Label(
            info_frame,
            text=f"Preferred IP: {self.local_ip}",
            font=("TkDefaultFont", 10, "bold"),
        ).pack(anchor=tk.W, padx=10, pady=5)
        ttk.Label(
            info_frame,
            text=f"Suggested Port: {self.local_port}",
            font=("TkDefaultFont", 10, "bold"),
        ).pack(anchor=tk.W, padx=10, pady=(0, 5))
        ttk.Label(
            info_frame,
            text="The manager keeps the server alive and preserves CLI output even when the CLI window is hidden.",
            wraplength=860,
        ).pack(anchor=tk.W, padx=10, pady=(0, 10))

        ttk.Label(self, text="Server ID:").grid(row=1, column=0, sticky=tk.W, padx=10, pady=8)
        self.v_id = tk.StringVar(value="default")
        ttk.Entry(self, textvariable=self.v_id).grid(
            row=1,
            column=1,
            sticky=tk.EW,
            padx=10,
            pady=8,
        )

        ttk.Label(self, text="Exam Duration (m):").grid(
            row=2,
            column=0,
            sticky=tk.W,
            padx=10,
            pady=8,
        )
        self.v_dur = tk.IntVar(value=45)
        ttk.Entry(self, textvariable=self.v_dur).grid(
            row=2,
            column=1,
            sticky=tk.EW,
            padx=10,
            pady=8,
        )

        ttk.Label(self, text="Host:").grid(row=3, column=0, sticky=tk.W, padx=10, pady=8)
        self.v_host = tk.StringVar(value="0.0.0.0")
        ttk.Entry(self, textvariable=self.v_host).grid(
            row=3,
            column=1,
            sticky=tk.EW,
            padx=10,
            pady=8,
        )

        ttk.Label(self, text="Port:").grid(row=4, column=0, sticky=tk.W, padx=10, pady=8)
        self.v_port = tk.IntVar(value=self.local_port)
        ttk.Entry(self, textvariable=self.v_port).grid(
            row=4,
            column=1,
            sticky=tk.EW,
            padx=10,
            pady=8,
        )

        ttk.Label(self, text="Exam ZIP File:").grid(
            row=5,
            column=0,
            sticky=tk.W,
            padx=10,
            pady=8,
        )
        file_frame = ttk.Frame(self)
        file_frame.grid(row=5, column=1, sticky=tk.EW, padx=10, pady=8)
        file_frame.columnconfigure(0, weight=1)
        self.v_file = tk.StringVar(value="")
        ttk.Entry(file_frame, textvariable=self.v_file, state="readonly").grid(
            row=0,
            column=0,
            sticky=tk.EW,
        )
        ttk.Button(file_frame, text="Browse", command=self.browse_file).grid(
            row=0,
            column=1,
            padx=(8, 0),
        )

        self.v_reset = tk.BooleanVar(value=True)
        ttk.Checkbutton(
            self,
            text="Reset Runtime State On Start",
            variable=self.v_reset,
        ).grid(row=6, column=0, columnspan=2, sticky=tk.W, padx=10, pady=(8, 4))

        controls = ttk.LabelFrame(self, text="Controls")
        controls.grid(row=7, column=0, columnspan=2, sticky=tk.EW, padx=10, pady=10)
        for column in range(4):
            controls.columnconfigure(column, weight=1)
        self.start_button = ttk.Button(
            controls,
            text="Start Server",
            command=self.start_server,
            width=16,
        )
        self.start_button.grid(row=0, column=0, sticky=tk.EW, padx=8, pady=10)
        self.stop_button = ttk.Button(
            controls,
            text="Stop Server",
            command=self.stop_server,
            width=16,
        )
        self.stop_button.grid(row=0, column=1, sticky=tk.EW, padx=8, pady=10)
        self.cli_button = ttk.Button(
            controls,
            text="Open Session CLI",
            command=self.open_cli,
            width=16,
        )
        self.cli_button.grid(row=0, column=2, sticky=tk.EW, padx=8, pady=10)
        self.gui_button = ttk.Button(
            controls,
            text="Open Dashboard",
            command=self.open_dashboard,
            width=16,
        )
        self.gui_button.grid(row=0, column=3, sticky=tk.EW, padx=8, pady=10)

        status_frame = ttk.LabelFrame(self, text="Session State")
        status_frame.grid(row=8, column=0, columnspan=2, sticky=tk.EW, padx=10, pady=10)
        ttk.Label(status_frame, textvariable=self.summary_var, wraplength=860).pack(
            anchor=tk.W,
            padx=10,
            pady=(10, 4),
        )
        ttk.Label(status_frame, textvariable=self.status_var, wraplength=860).pack(
            anchor=tk.W,
            padx=10,
            pady=(10, 4),
        )
        ttk.Label(status_frame, textvariable=self.pid_var, wraplength=860).pack(
            anchor=tk.W,
            padx=10,
            pady=4,
        )
        ttk.Label(status_frame, textvariable=self.session_log_var, wraplength=860).pack(
            anchor=tk.W,
            padx=10,
            pady=4,
        )
        ttk.Label(status_frame, textvariable=self.runtime_log_var, wraplength=860).pack(
            anchor=tk.W,
            padx=10,
            pady=(4, 10),
        )

        ttk.Label(
            self,
            text=(
                "Window close shortcuts only show warnings here while the server is active. "
                "Use Stop Server from the manager when you really want to end the session."
            ),
            wraplength=860,
            foreground="#5c4d7d",
        ).grid(row=9, column=0, columnspan=2, sticky=tk.W, padx=10, pady=(0, 10))

    def _get_free_port(self):
        try:
            sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
            sock.bind(("", 8080))
            sock.close()
            return 8080
        except OSError:
            try:
                sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
                sock.bind(("", 0))
                port = sock.getsockname()[1]
                sock.close()
                return port
            except Exception:
                return 8080

    def browse_file(self):
        filename = filedialog.askopenfilename(
            title="Select Exam Materials",
            filetypes=[("Zip files", "*.zip"), ("All files", "*.*")],
        )
        if filename:
            self.v_file.set(filename)

    def _server_running(self) -> bool:
        return self.process_session.is_running()

    def _current_log_path(self):
        if not self.process_session.log_path:
            return None
        return str(self.process_session.log_path)

    def _current_runtime_log_path(self):
        return self.process_session.runtime_log_path

    def _build_server_command(self) -> list[str]:
        command = [
            sys.executable,
            "-u",
            "-m",
            "server.main",
            "--id",
            self.v_id.get().strip(),
            "--host",
            self.v_host.get().strip() or "0.0.0.0",
            "--port",
            str(self.v_port.get()),
            "--exam-duration",
            str(self.v_dur.get()),
        ]
        exam_file = self.v_file.get().strip()
        if exam_file:
            command.extend(["--exam-files", exam_file])
        if self.v_reset.get():
            command.append("--reset")
        return command

    def _session_summary_text(self) -> str:
        exam_file = self.v_file.get().strip() or "-"
        return (
            f"Session Summary: id={self.v_id.get().strip() or '-'}    "
            f"host={self.v_host.get().strip() or '0.0.0.0'}    "
            f"port={self.v_port.get()}    "
            f"duration={self.v_dur.get()} min    "
            f"exam_zip={exam_file}"
        )

    def _set_setup_visible(self, visible: bool):
        for widget in self.grid_slaves():
            row = int(widget.grid_info().get("row", -1))
            if row > 6:
                continue
            if visible:
                widget.grid()
            else:
                widget.grid_remove()

    def _validate_form(self) -> bool:
        if self._server_running():
            messagebox.showinfo("Server Running", "Stop the current server before starting a new one.")
            return False
        if not self.v_id.get().strip():
            messagebox.showerror("Validation Error", "Server ID cannot be empty.")
            return False
        if self.v_dur.get() <= 0:
            messagebox.showerror("Validation Error", "Exam duration must be greater than 0.")
            return False
        if not 1 <= self.v_port.get() <= 65535:
            messagebox.showerror("Validation Error", "Port must be between 1 and 65535.")
            return False
        return True

    def start_server(self):
        if not self._validate_form():
            return

        env = {
            "PYTHONPATH": str(self.project_dir)
            + os.pathsep
            + os.environ.get("PYTHONPATH", "")
        }
        try:
            self.process_session.start(
                self._build_server_command(),
                cwd=str(self.project_dir),
                env=env,
            )
        except Exception as exc:
            messagebox.showerror("Launch Error", str(exc))
            return

        self._last_known_returncode = None
        self.summary_var.set(self._session_summary_text())
        self.status_var.set("Server starting...")
        self._set_setup_visible(False)

    def stop_server(self):
        if not self._server_running():
            messagebox.showinfo("Server Stopped", "There is no active server session to stop.")
            return

        should_stop = messagebox.askyesno(
            "Stop Server",
            "Stop the running server session?",
            default=messagebox.NO,
        )
        if not should_stop:
            return

        self.process_session.stop()
        self.status_var.set("Stopping server...")

    def open_cli(self):
        self.console_window.show_window()

    def open_dashboard(self):
        if not self._server_running():
            messagebox.showwarning(
                "Dashboard Unavailable",
                "Start the server first, then open the dashboard.",
            )
            return
        if not self._send_server_command("/gui"):
            messagebox.showwarning(
                "Dashboard Unavailable",
                "The dashboard command could not be sent to the server process.",
            )

    def _send_server_command(self, command: str) -> bool:
        if not command.startswith("/"):
            command = "/" + command
        return self.process_session.send_line(command)

    def _poll_process_state(self):
        running = self._server_running()
        process = self.process_session.process
        returncode = None if process is None else process.poll()

        self.start_button.config(state=tk.DISABLED if running else tk.NORMAL)
        self.stop_button.config(state=tk.NORMAL if running else tk.DISABLED)
        self.gui_button.config(state=tk.NORMAL if running else tk.DISABLED)
        self.cli_button.config(
            state=tk.NORMAL if self.process_session.log_path is not None else tk.DISABLED
        )

        if running and process is not None:
            self.status_var.set("Server running under manager control.")
            self.pid_var.set(f"PID: {process.pid}")
        elif process is not None and returncode is not None:
            self.status_var.set(f"Server stopped. Exit code: {returncode}")
            self.pid_var.set(f"PID: {process.pid}")
        else:
            self.status_var.set("Server stopped.")
            self.pid_var.set("PID: -")

        if running:
            self.summary_var.set(self._session_summary_text())
            self._set_setup_visible(False)
        else:
            self.summary_var.set("Session Summary: -")
            self._set_setup_visible(True)

        session_output = self.process_session.log_path
        self.session_log_var.set(f"Session Output: {session_output or '-'}")
        self.runtime_log_var.set(
            f"Runtime JSONL: {self.process_session.runtime_log_path or '-'}"
        )

        if (
            self._last_known_returncode is None
            and returncode is not None
            and self.process_session.log_path is not None
        ):
            self._last_known_returncode = returncode

        self.after(500, self._poll_process_state)

    def on_close_request(self):
        if self._server_running():
            messagebox.showwarning(
                "Server Manager Locked",
                "The manager stays open while the server is running.\n\n"
                "Use Stop Server first, then close the manager.",
            )
            return

        should_close = messagebox.askyesno(
            "Close Server Manager",
            "Close the server manager?",
            default=messagebox.NO,
        )
        if should_close:
            self.destroy()


if __name__ == "__main__":
    apply_dpi_awareness()
    app = ServerManager()
    app.mainloop()
