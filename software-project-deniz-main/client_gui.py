import json
import sys
import tkinter as tk
from pathlib import Path
from threading import Thread
from tkinter import filedialog, messagebox, ttk

from common.manager_support import install_close_guard
from client.submission import build_file_preview, format_bytes

from common.runtime_logging import setup_runtime_logging


def _emit_command(payload: dict):
    print(json.dumps(payload), flush=True)


def _parse_ipc_line(line: str):
    command, _, value = line.partition(":")
    return command, value


def _format_time(seconds: int) -> str:
    minutes, remaining_seconds = divmod(seconds, 60)
    return f"{minutes:02d}:{remaining_seconds:02d}"


class ExamTimerGUI:
    def __init__(self, root):
        self.root = root
        self.remaining = 0
        self.active = True
        self.started = False
        self.submission_window = None
        self.finish_in_progress = False

        self._configure_window()
        self._build_widgets()
        self.update_clock()

    def _configure_window(self):
        self.root.title("Exam Timer")
        self.root.geometry("400x200")
        self.root.attributes("-topmost", True)
        install_close_guard(self.root, self.on_closing, bind_all=True)

    def _build_widgets(self):
        self.main_frame = ttk.Frame(self.root, padding="20")
        self.main_frame.pack(expand=True, fill="both")

        self.label_var = tk.StringVar(value="Waiting to start...")
        self.label = ttk.Label(
            self.main_frame,
            textvariable=self.label_var,
            font=("Helvetica", 16),
        )
        self.label.pack(expand=True, pady=10)

        self.button_frame = ttk.Frame(self.main_frame)
        self.button_frame.pack(pady=10)

        self.start_btn = ttk.Button(
            self.button_frame,
            text="Request Start",
            command=self.on_start_click,
        )
        self.start_btn.pack()

        self.finish_btn = ttk.Button(
            self.button_frame,
            text="Finish Exam",
            command=self.open_finish_window,
            state=tk.DISABLED,
        )

    def on_start_click(self):
        _emit_command({"cmd": "start_exam"})
        self.start_btn.config(state=tk.DISABLED)
        self.label_var.set("Starting...")

    def update_clock(self):
        if self.active and self.started:
            if self.remaining > 0:
                self.label_var.set(_format_time(self.remaining))
                self.remaining -= 1
            elif self.remaining == 0:
                self.label_var.set("00:00")

        self.root.after(1000, self.update_clock)

    def set_remaining(self, seconds):
        if seconds < 0:
            self.root.destroy()
            return

        self.remaining = seconds
        if self.started:
            return

        self.started = True
        self.start_btn.pack_forget()
        self.finish_btn.pack()
        self.finish_btn.config(state=tk.NORMAL)
        self.label.config(font=("Helvetica", 32, "bold"))

    def reset_to_ready(self):
        if self.started:
            return
        self.start_btn.config(state=tk.NORMAL)
        self.label_var.set("Waiting to start...")

    def show_error_popup(self, message: str):
        self.reset_to_ready()
        title = "Exam Finished" if "finished" in message.lower() else "Exam Not Started"
        messagebox.showerror(title, message)

    def open_finish_window(self):
        if not self.started:
            return
        if self.finish_in_progress:
            return

        if self.submission_window and self.submission_window.winfo_exists():
            self.submission_window.lift()
            self.submission_window.focus_force()
            return

        self.submission_window = SubmissionWindow(
            parent=self.root,
            submit_callback=self.submit_file,
            close_callback=self._clear_submission_window,
        )

    def submit_file(self, selected_file: str):
        self.finish_in_progress = True
        self.finish_btn.config(state=tk.DISABLED)
        if self.submission_window:
            self.submission_window.set_uploading()
        _emit_command({"cmd": "finish_exam", "archive_path": selected_file})

    def prompt_finish_from_server(self, message: str):
        self.started = True
        self.start_btn.pack_forget()
        self.finish_btn.pack()
        self.finish_btn.config(state=tk.NORMAL if not self.finish_in_progress else tk.DISABLED)
        self.label_var.set("Upload your file to finish.")
        self.open_finish_window()
        if message:
            messagebox.showinfo("Finish Exam", message)

    def handle_upload_success(self, message: str):
        self.finish_in_progress = False
        if self.submission_window and self.submission_window.winfo_exists():
            self.submission_window.destroy()
        messagebox.showinfo("Submission Uploaded", message or "Submission uploaded successfully.")
        self.root.destroy()

    def handle_upload_error(self, message: str):
        self.finish_in_progress = False
        self.finish_btn.config(state=tk.NORMAL)
        if self.submission_window and self.submission_window.winfo_exists():
            self.submission_window.set_ready_after_error(message)
        messagebox.showerror("Upload Failed", message)

    def _clear_submission_window(self):
        self.submission_window = None
        if not self.finish_in_progress and self.started:
            self.finish_btn.config(state=tk.NORMAL)

    def on_closing(self):
        if self.finish_in_progress:
            self._focus_submission_window()
            messagebox.showwarning(
                "Upload In Progress",
                "A submission upload is currently in progress.\n\nWait for it to finish before trying to close anything.",
            )
            return

        if self.submission_window and self.submission_window.winfo_exists():
            self.submission_window.iconify()
        self.root.iconify()

    def _focus_submission_window(self):
        if not self.submission_window or not self.submission_window.winfo_exists():
            return
        self.submission_window.lift()
        self.submission_window.focus_force()

class SubmissionWindow(tk.Toplevel):
    def __init__(self, parent, submit_callback, close_callback):
        super().__init__(parent)
        self.submit_callback = submit_callback
        self.close_callback = close_callback
        self.selected_file = ""

        self.title("Finish Exam")
        self.geometry("760x500")
        install_close_guard(self, self._on_close_attempt, include_quit_shortcuts=False)

        self.path_var = tk.StringVar(value="No file selected.")
        self.status_var = tk.StringVar(value="Choose a file to preview and upload.")
        self.summary_var = tk.StringVar(value="")

        self._build_widgets()

    def _build_widgets(self):
        container = ttk.Frame(self, padding=12)
        container.pack(fill=tk.BOTH, expand=True)

        ttk.Label(
            container,
            text="Select a file to submit.",
            font=("Helvetica", 12, "bold"),
        ).pack(anchor=tk.W)

        ttk.Label(container, textvariable=self.path_var, wraplength=700).pack(
            anchor=tk.W,
            pady=(6, 8),
        )

        action_frame = ttk.Frame(container)
        action_frame.pack(fill=tk.X, pady=(0, 10))

        self.choose_button = ttk.Button(
            action_frame,
            text="Choose File",
            command=self.choose_file,
        )
        self.choose_button.pack(side=tk.LEFT)

        self.upload_button = ttk.Button(
            action_frame,
            text="Upload And Finish",
            command=self._submit_selected_file,
            state=tk.DISABLED,
        )
        self.upload_button.pack(side=tk.LEFT, padx=(8, 0))

        ttk.Label(container, textvariable=self.summary_var, foreground="#355070").pack(
            anchor=tk.W,
            pady=(0, 6),
        )
        ttk.Label(container, textvariable=self.status_var, foreground="#666666").pack(
            anchor=tk.W,
            pady=(0, 8),
        )

        preview_frame = ttk.LabelFrame(container, text="File Preview")
        preview_frame.pack(fill=tk.BOTH, expand=True)

        self.preview_frame = preview_frame
        columns = ("size", "modified")
        self.tree = ttk.Treeview(
            preview_frame,
            columns=columns,
            show="tree headings",
        )
        self.tree.heading("#0", text="Name", anchor=tk.W)
        self.tree.heading("size", text="Size", anchor=tk.E)
        self.tree.heading("modified", text="Last Modified", anchor=tk.W)
        self.tree.column("#0", width=360, anchor=tk.W)
        self.tree.column("size", width=110, anchor=tk.E)
        self.tree.column("modified", width=180, anchor=tk.W)

        scrollbar = ttk.Scrollbar(preview_frame, orient=tk.VERTICAL, command=self.tree.yview)
        self.tree.configure(yscrollcommand=scrollbar.set)
        self.tree_scrollbar = scrollbar

        self.text_preview = tk.Text(preview_frame, wrap=tk.WORD, state=tk.DISABLED)
        self.text_scrollbar = ttk.Scrollbar(
            preview_frame,
            orient=tk.VERTICAL,
            command=self.text_preview.yview,
        )
        self.text_preview.configure(yscrollcommand=self.text_scrollbar.set)

        self._show_tree_preview()

    def choose_file(self):
        selected_path = filedialog.askopenfilename(
            title="Choose file",
            filetypes=[
                ("All files", "*.*"),
                ("Archive files", "*.zip *.tar *.tgz *.tar.gz *.tbz2 *.tar.bz2 *.txz *.tar.xz"),
                ("Text files", "*.txt *.md *.py *.json *.csv *.log *.yaml *.yml *.xml *.html *.css *.js *.ts"),
                ("All files", "*.*"),
            ],
        )
        if not selected_path:
            return

        self.selected_file = selected_path
        self.path_var.set(selected_path)
        self._load_preview(selected_path)

    def _load_preview(self, selected_path: str):
        try:
            preview = build_file_preview(selected_path)
        except Exception as exc:
            self._clear_preview()
            self.summary_var.set("")
            self.status_var.set("Preview failed. Choose a valid file before uploading.")
            self.upload_button.config(state=tk.DISABLED)
            messagebox.showwarning("Preview Failed", str(exc))
            return

        self._populate_preview(preview)
        self.upload_button.config(state=tk.NORMAL)

    def _populate_preview(self, preview):
        self._clear_preview()
        self.summary_var.set(
            f"File: {preview.file_name}    "
            f"Size: {format_bytes(preview.file_size_bytes)}    "
            f"Modified: {preview.file_modified_at}"
        )
        self.status_var.set(preview.preview_message or "Preview loaded. Review it, then upload when ready.")

        if preview.preview_kind == "archive":
            self._show_tree_preview()
            root_id = self.tree.insert(
                "",
                tk.END,
                text=preview.file_name,
                values=(format_bytes(preview.file_size_bytes), preview.file_modified_at),
                open=True,
            )
            for entry in preview.entries:
                self._insert_preview_entry(root_id, entry)
            return

        if preview.preview_kind == "text":
            self._show_text_preview()
            self.text_preview.config(state=tk.NORMAL)
            self.text_preview.insert("1.0", preview.text_preview)
            self.text_preview.config(state=tk.DISABLED)
            return

        self._show_text_preview()
        self.text_preview.config(state=tk.NORMAL)
        self.text_preview.insert(
            "1.0",
            "Binary file selected.\n\n"
            f"Name: {preview.file_name}\n"
            f"Size: {format_bytes(preview.file_size_bytes)}\n"
            f"Modified: {preview.file_modified_at}\n",
        )
        self.text_preview.config(state=tk.DISABLED)

    def _insert_preview_entry(self, parent_id, entry):
        label = f"{entry.name}/" if entry.is_dir else entry.name
        item_id = self.tree.insert(
            parent_id,
            tk.END,
            text=label,
            values=(format_bytes(entry.size_bytes) if not entry.is_dir else "-", entry.modified_at),
            open=True,
        )
        for child in entry.children:
            self._insert_preview_entry(item_id, child)

    def _clear_preview(self):
        for item_id in self.tree.get_children():
            self.tree.delete(item_id)
        self.text_preview.config(state=tk.NORMAL)
        self.text_preview.delete("1.0", tk.END)
        self.text_preview.config(state=tk.DISABLED)

    def _submit_selected_file(self):
        if not self.selected_file:
            messagebox.showwarning("Finish Exam", "Choose a file first.")
            return
        self.submit_callback(self.selected_file)

    def set_uploading(self):
        self.choose_button.config(state=tk.DISABLED)
        self.upload_button.config(state=tk.DISABLED)
        self.status_var.set("Uploading file...")

    def set_ready_after_error(self, message: str):
        self.choose_button.config(state=tk.NORMAL)
        self.upload_button.config(state=tk.NORMAL)
        self.status_var.set(message)

    def _on_close_attempt(self):
        messagebox.showwarning(
            "Finish Exam",
            "This submission window stays protected while the client session is active.\n\n"
            "Choose a file and upload it from here, or return to the timer window.",
        )

    def _show_tree_preview(self):
        self.text_preview.pack_forget()
        self.text_scrollbar.pack_forget()
        self.tree.pack(side=tk.LEFT, fill=tk.BOTH, expand=True)
        self.tree_scrollbar.pack(side=tk.RIGHT, fill=tk.Y)

    def _show_text_preview(self):
        self.tree.pack_forget()
        self.tree_scrollbar.pack_forget()
        self.text_preview.pack(side=tk.LEFT, fill=tk.BOTH, expand=True)
        self.text_scrollbar.pack(side=tk.RIGHT, fill=tk.Y)


def ipc_reader(app: ExamTimerGUI):
    """Read remaining times from stdin."""
    for line in sys.stdin:
        command, value = _parse_ipc_line(line.strip())
        try:
            if command == "SYNC":
                app.root.after(0, app.set_remaining, int(value))
            elif command == "END":
                app.root.after(0, app.set_remaining, -1)
            elif command == "RESET":
                app.root.after(0, app.reset_to_ready)
            elif command == "ERROR":
                app.root.after(0, app.show_error_popup, value)
            elif command == "OPEN_FINISH":
                app.root.after(0, app.prompt_finish_from_server, value)
            elif command == "UPLOAD_OK":
                app.root.after(0, app.handle_upload_success, value)
            elif command == "UPLOAD_ERROR":
                app.root.after(0, app.handle_upload_error, value)
        except Exception:
            pass


if __name__ == "__main__":
    setup_runtime_logging(
        "client_gui",
        Path(__file__).resolve().parent / "data" / "logs" / "client",
    )
    root = tk.Tk()
    app = ExamTimerGUI(root)

    reader_thread = Thread(target=ipc_reader, args=(app,), daemon=True)
    reader_thread.start()

    root.mainloop()
