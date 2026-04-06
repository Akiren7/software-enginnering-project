"""
activity_monitor.py

Detect active window, running processes, and user idle time 
across Windows, Linux, and macOS.

This module has NO network code and NO exam control logic.
It only reads OS-level activity data and returns it.

"""

import platform # identifying the platform
import subprocess
import time
import psutil # process utility

SYSTEM = platform.system()   # "Windows" | "Linux" | "Darwin"


class ActivityMonitor:
    """
    Detects:
      - Title of the currently focused window
      - All running process names
      - Seconds since last keyboard / mouse input  (idle time)

    Usage:
        monitor = ActivityMonitor()
        print(monitor.get_active_window())    # "Google Chrome", "Gmail" etc.
        print(monitor.get_open_processes())   # ["chrome", "examapp", ...]
        print(monitor.get_idle_seconds())     # 30
    """

    # ── Public API ─────────────────────────────────────────────────────────

    def get_active_window(self) -> str: # self -> this function in a class
        """
        Returns the title of the window currently in focus.
        Returns "Unknown" if detection fails for any reason.
        """
        try: #if os couldn't recognized, it throws an error
            if SYSTEM == "Windows":
                return self._windows_active_window()
            if SYSTEM == "Linux":
                return self._linux_active_window()
            if SYSTEM == "Darwin":
                return self._macos_active_window()
        except Exception as exc:
            return f"DetectionError({exc})"
        return "Unknown"

    def get_open_processes(self) -> list:
        """
        Returns a sorted list of running process names, no duplications.

        - .exe suffix is stripped on Windows for consistency
        - Includes all user-visible processes 
        - PayloadBuilder is responsible for filtering banned ones.

        Returns e.g. ["calculator", "chrome", "examapp", "telegram"]
        """
        seen   = set() # it's easier to search in a set than a list
        result = []

        for proc in psutil.process_iter(["name"]): #get tha names of the current processes that are running
            try:
                raw = proc.info["name"]
                if not raw:
                    continue
                clean = raw.lower().strip() # get the clean name by converting all into lower case and removing the spaces
                if SYSTEM == "Windows":
                    clean = clean.replace(".exe", "")
                if clean and clean not in seen:
                    seen.add(clean)
                    result.append(clean)
            except (psutil.NoSuchProcess, psutil.AccessDenied): # if the process got shut down or prohibited to access
                pass   # process may have died during iteration

        return sorted(result)

    def get_idle_seconds(self) -> float:
        """
        Returns seconds since the last keyboard or mouse input.

        Returns -1.0 if the platform is unsupported or detection fails. (for macOS)
        Use case: alert instructor when student leaves their seat.
        """
        try:
            if SYSTEM == "Windows":
                return self._windows_idle_seconds()
            if SYSTEM == "Linux":
                return self._linux_idle_seconds()
        except Exception:
            pass
        return -1.0 # there is no idle second methods for macOS so we will return -1 as a result

    def snapshot(self) -> dict:
        """
        Captures all three metrics in a single call.
        This is the primary method called by PayloadBuilder.

        """
        return {
            "active_window":  self.get_active_window(),
            "open_processes": self.get_open_processes(),
            "idle_seconds":   self.get_idle_seconds(),
            "captured_at":    time.time(),
        }

    # ── Windows methods

    def _windows_active_window(self) -> str:
        import win32gui                                  # pip install pywin32
        hwnd  = win32gui.GetForegroundWindow() #unique id 
        title = win32gui.GetWindowText(hwnd) #title
        return title or "Unknown"

    def _windows_idle_seconds(self) -> float:
        import ctypes # allows python to directly call windows functions

        class LASTINPUTINFO(ctypes.Structure):
            _fields_ = [("cbSize", ctypes.c_uint),
                        ("dwTime", ctypes.c_uint)]

        info          = LASTINPUTINFO()
        info.cbSize   = ctypes.sizeof(LASTINPUTINFO)
        ctypes.windll.user32.GetLastInputInfo(ctypes.byref(info))
        elapsed_ms    = ctypes.windll.kernel32.GetTickCount() - info.dwTime 
        return elapsed_ms / 1000.0 # when was the last input

    # ── Linux methods

    def _linux_active_window(self) -> str:
        # xdotool queries the X11 window manager for the focused window title
        out = subprocess.check_output(
            ["xdotool", "getactivewindow", "getwindowname"],
            stderr=subprocess.DEVNULL, timeout=2
        )
        return out.decode().strip()

    def _linux_idle_seconds(self) -> float:
        # xprintidle returns milliseconds since last X11 input event
        out = subprocess.check_output(
            ["xprintidle"], stderr=subprocess.DEVNULL, timeout=2
        )
        return int(out.strip()) / 1000.0

    # ── macOS ──────────────────────────────────────────────────────────────

    def _macos_active_window(self) -> str:
        script = ('tell application "System Events" to get name of '
                  'first application process whose frontmost is true')
        out = subprocess.check_output(
            ["osascript", "-e", script], stderr=subprocess.DEVNULL, timeout=2
        )
        return out.decode().strip()


# ── Quick manual test ──────────────────────────────────────────────────────
if __name__ == "__main__":
    print(f"Platform : {SYSTEM}\n")
    m    = ActivityMonitor()
    snap = m.snapshot()
    print(f"Active window  : {snap['active_window']}")
    print(f"Idle seconds   : {snap['idle_seconds']:.1f}")
    print(f"Open processes : {snap['open_processes']}")