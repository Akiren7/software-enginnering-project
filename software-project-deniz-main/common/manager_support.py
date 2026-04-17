import os
import signal
import subprocess
import threading
import tkinter as tk
from datetime import datetime
from pathlib import Path
from tkinter import messagebox, ttk


def apply_dpi_awareness():
    try:
        from ctypes import windll

        windll.shcore.SetProcessDpiAwareness(1)
    except Exception:
        pass


def _break_and_handle(_event, handler):
    handler()
    return "break"


def install_close_guard(
    window,
    handler,
    *,
    bind_all: bool = False,
    include_quit_shortcuts: bool = True,
):
    window.protocol("WM_DELETE_WINDOW", handler)

    bind = window.bind_all if bind_all else window.bind
    for sequence in ("<Alt-F4>", "<Command-w>", "<Command-W>"):
        bind(sequence, lambda event, _handler=handler: _break_and_handle(event, _handler), add="+")

    if include_quit_shortcuts:
        for sequence in ("<Command-q>", "<Command-Q>"):
            bind(sequence, lambda event, _handler=handler: _break_and_handle(event, _handler), add="+")

        try:
            window.createcommand("tk::mac::Quit", handler)
        except Exception:
            pass


def build_session_log_path(log_dir: Path, prefix: str) -> Path:
    log_dir.mkdir(parents=True, exist_ok=True)
    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    return log_dir / f"{prefix}_{timestamp}.log"


class ManagedProcessSession:
    def __init__(self, *, session_name: str, log_dir: Path):
        self.session_name = session_name
        self.log_dir = Path(log_dir)
        self.process = None
        self.log_path = None
        self.runtime_log_path = None
        self._reader_thread = None
        self._log_handle = None
        self._log_lock = threading.Lock()

    def is_running(self) -> bool:
        return self.process is not None and self.process.poll() is None

    def start(self, cmd: list[str], *, cwd: str, env: dict | None = None):
        if self.is_running():
            raise RuntimeError(f"{self.session_name} is already running")
        if self._reader_thread and self._reader_thread.is_alive():
            self._reader_thread.join(timeout=1.0)

        self._close_log_handle()
        self.log_path = build_session_log_path(self.log_dir, self.session_name)
        self.runtime_log_path = None
        self._log_handle = self.log_path.open("a", encoding="utf-8", buffering=1)

        launch_env = os.environ.copy()
        if env:
            launch_env.update(env)
        launch_env["PYTHONUNBUFFERED"] = "1"

        creationflags = getattr(subprocess, "CREATE_NO_WINDOW", 0) if os.name == "nt" else 0
        self.process = subprocess.Popen(
            cmd,
            cwd=cwd,
            env=launch_env,
            stdin=subprocess.PIPE,
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            text=True,
            bufsize=1,
            creationflags=creationflags,
        )
        self._write_log_text(
            f"[MANAGER] Started {self.session_name} process (pid {self.process.pid}).\n"
        )
        self._reader_thread = threading.Thread(
            target=self._capture_output,
            name=f"{self.session_name}_output_reader",
            daemon=True,
        )
        self._reader_thread.start()
        return self.process

    def _capture_output(self):
        process = self.process
        if process is None or process.stdout is None:
            return

        try:
            for line in process.stdout:
                self._capture_runtime_log_path(line)
                self._write_log_text(line)
        finally:
            try:
                process.stdout.close()
            except Exception:
                pass
            try:
                if process.stdin is not None:
                    process.stdin.close()
            except Exception:
                pass

            returncode = process.wait()
            self._write_log_text(
                f"[MANAGER] {self.session_name} process exited with code {returncode}.\n"
            )
            self._close_log_handle()

    def _capture_runtime_log_path(self, line: str):
        prefix = "[LOG] Writing runtime log to "
        if prefix not in line:
            return
        _, _, path = line.partition(prefix)
        runtime_log_path = path.strip()
        if runtime_log_path:
            self.runtime_log_path = runtime_log_path

    def _write_log_text(self, text: str):
        if self._log_handle is None:
            return
        with self._log_lock:
            self._log_handle.write(text)
            self._log_handle.flush()

    def _close_log_handle(self):
        with self._log_lock:
            if self._log_handle is None:
                return
            try:
                self._log_handle.flush()
                self._log_handle.close()
            except Exception:
                pass
            self._log_handle = None

    def send_line(self, text: str) -> bool:
        if not self.is_running() or self.process is None or self.process.stdin is None:
            return False

        message = text.rstrip("\n")
        self._write_log_text(f"[MANAGER] > {message}\n")
        try:
            self.process.stdin.write(message + "\n")
            self.process.stdin.flush()
            return True
        except Exception as exc:
            self._write_log_text(f"[MANAGER] Failed to write to stdin: {exc}\n")
            return False

    def stop(self, *, timeout: float = 5.0) -> bool:
        if not self.process:
            return False
        if self.process.poll() is not None:
            return False

        self._write_log_text(f"[MANAGER] Stop requested for {self.session_name}.\n")
        try:
            if os.name == "nt":
                self.process.terminate()
            else:
                self.process.send_signal(signal.SIGINT)
            self.process.wait(timeout=timeout)
            return True
        except subprocess.TimeoutExpired:
            self._write_log_text(
                f"[MANAGER] Force killing {self.session_name} after timeout.\n"
            )
            try:
                self.process.kill()
                self.process.wait(timeout=2.0)
            except Exception:
                pass
            return True
        except Exception as exc:
            self._write_log_text(f"[MANAGER] Stop failed: {exc}\n")
            return False

    def read_output_text(self) -> str:
        if not self.log_path or not self.log_path.exists():
            return ""
        try:
            return self.log_path.read_text(encoding="utf-8", errors="replace")
        except Exception:
            return ""


class ConsoleWindow(tk.Toplevel):
    def __init__(
        self,
        parent,
        *,
        title: str,
        get_log_path,
        get_runtime_log_path,
        is_process_running,
        send_command,
        empty_message: str,
    ):
        super().__init__(parent)
        self.get_log_path = get_log_path
        self.get_runtime_log_path = get_runtime_log_path
        self.is_process_running = is_process_running
        self.send_command = send_command
        self.empty_message = empty_message
        self._active_log_path = None
        self._read_offset = 0

        self.title(title)
        self.geometry("980x620")
        self.withdraw()
        install_close_guard(self, self._hide_window, include_quit_shortcuts=False)

        self.status_var = tk.StringVar(value="No active session.")
        self.path_var = tk.StringVar(value="Session output: -")
        self.runtime_log_var = tk.StringVar(value="Runtime JSONL: -")

        self._build_widgets()
        self.after(500, self._poll_output)

    def _build_widgets(self):
        frame = ttk.Frame(self, padding=10)
        frame.pack(fill=tk.BOTH, expand=True)

        ttk.Label(frame, textvariable=self.status_var).pack(anchor=tk.W)
        ttk.Label(frame, textvariable=self.path_var, wraplength=900).pack(anchor=tk.W, pady=(4, 0))
        ttk.Label(frame, textvariable=self.runtime_log_var, wraplength=900).pack(
            anchor=tk.W,
            pady=(2, 8),
        )

        text_frame = ttk.Frame(frame)
        text_frame.pack(fill=tk.BOTH, expand=True)

        self.output_text = tk.Text(
            text_frame,
            wrap=tk.WORD,
            state=tk.DISABLED,
            font=("TkFixedFont", 11),
        )
        scroll = ttk.Scrollbar(text_frame, orient=tk.VERTICAL, command=self.output_text.yview)
        self.output_text.configure(yscrollcommand=scroll.set)
        self.output_text.pack(side=tk.LEFT, fill=tk.BOTH, expand=True)
        scroll.pack(side=tk.RIGHT, fill=tk.Y)

        command_frame = ttk.Frame(frame, padding=(0, 8, 0, 0))
        command_frame.pack(fill=tk.X)

        ttk.Label(command_frame, text="Send Input:").pack(side=tk.LEFT)
        self.command_entry = ttk.Entry(command_frame)
        self.command_entry.pack(side=tk.LEFT, fill=tk.X, expand=True, padx=(8, 8))
        self.command_entry.bind("<Return>", lambda _event: self._send_command())
        self.send_button = ttk.Button(
            command_frame,
            text="Send",
            command=self._send_command,
            width=12,
        )
        self.send_button.pack(side=tk.LEFT)
        ttk.Button(
            command_frame,
            text="Hide Window",
            command=self._hide_window,
            width=12,
        ).pack(
            side=tk.LEFT,
            padx=(8, 0),
        )

    def show_window(self):
        self._refresh_full_output()
        self._update_labels()
        self.deiconify()
        self.lift()
        self.focus_force()

    def _hide_window(self):
        self.withdraw()

    def _send_command(self):
        command = self.command_entry.get().strip()
        if not command:
            return
        if self.send_command(command):
            self.command_entry.delete(0, tk.END)
            return
        messagebox.showwarning(
            "Command Unavailable",
            "The managed process is not running, so the command could not be sent.",
        )

    def _update_labels(self):
        log_path = self.get_log_path()
        runtime_log_path = self.get_runtime_log_path()
        running = self.is_process_running()
        state_label = "Running" if running else "Stopped"
        self.status_var.set(f"Process state: {state_label}")
        self.path_var.set(f"Session output: {log_path or '-'}")
        self.runtime_log_var.set(f"Runtime JSONL: {runtime_log_path or '-'}")
        self.send_button.config(state=tk.NORMAL if running else tk.DISABLED)
        self.command_entry.config(state=tk.NORMAL if running else tk.DISABLED)

    def _refresh_full_output(self):
        log_path = self.get_log_path()
        self._active_log_path = log_path
        self._read_offset = 0
        self._set_output_text("")

        if not log_path or not Path(log_path).exists():
            self._set_output_text(self.empty_message)
            return

        try:
            text = Path(log_path).read_text(encoding="utf-8", errors="replace")
        except Exception:
            text = self.empty_message

        self._set_output_text(text)
        try:
            self._read_offset = Path(log_path).stat().st_size
        except OSError:
            self._read_offset = 0

    def _poll_output(self):
        if self.winfo_exists():
            self._update_labels()
            if str(self.state()) != "withdrawn":
                current_log_path = self.get_log_path()
                if current_log_path != self._active_log_path:
                    self._refresh_full_output()
                else:
                    self._append_new_output()
            self.after(500, self._poll_output)

    def _append_new_output(self):
        log_path = self.get_log_path()
        if not log_path:
            return

        path = Path(log_path)
        if not path.exists():
            return

        try:
            with path.open("r", encoding="utf-8", errors="replace") as handle:
                handle.seek(self._read_offset)
                chunk = handle.read()
                self._read_offset = handle.tell()
        except Exception:
            return

        if not chunk:
            return

        self.output_text.config(state=tk.NORMAL)
        self.output_text.insert(tk.END, chunk)
        self.output_text.see(tk.END)
        self.output_text.config(state=tk.DISABLED)

    def _set_output_text(self, text: str):
        self.output_text.config(state=tk.NORMAL)
        self.output_text.delete("1.0", tk.END)
        self.output_text.insert("1.0", text)
        self.output_text.see(tk.END)
        self.output_text.config(state=tk.DISABLED)
