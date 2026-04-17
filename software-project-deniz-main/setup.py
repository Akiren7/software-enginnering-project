#!/usr/bin/env python3
"""
setup.py -- Cross-platform setup script.

Checks for and installs:
  1. Python packages from requirements.txt (via pip)
  2. FFmpeg (via brew / choco / apt)

Run:  python3 setup.py
"""

import subprocess
import sys
import os
import shutil
import platform


# -- Styling ---------------------------------------------------------------

class Color:
    """ANSI colors, disabled automatically on Windows without VT support."""
    ENABLED = sys.stdout.isatty() and os.name != "nt"

    @staticmethod
    def green(s):
        if Color.ENABLED:
            return f"\033[92m{s}\033[0m"
        return s

    @staticmethod
    def yellow(s):
        if Color.ENABLED:
            return f"\033[93m{s}\033[0m"
        return s

    @staticmethod
    def red(s):
        if Color.ENABLED:
            return f"\033[91m{s}\033[0m"
        return s

    @staticmethod
    def cyan(s):
        if Color.ENABLED:
            return f"\033[96m{s}\033[0m"
        return s

    @staticmethod
    def bold(s):
        if Color.ENABLED:
            return f"\033[1m{s}\033[0m"
        return s


OK   = Color.green("[OK]")
WARN = Color.yellow("[!!]")
FAIL = Color.red("[FAIL]")
INFO = Color.cyan("[>>]")


# -- Helpers ---------------------------------------------------------------

def run(cmd, capture=True):
    """Run a command and return (success, stdout)."""
    try:
        result = subprocess.run(
            cmd, capture_output=capture, text=True, timeout=60
        )
        return result.returncode == 0, result.stdout.strip()
    except (FileNotFoundError, subprocess.TimeoutExpired):
        return False, ""


def get_version(binary):
    """Try to get a version string from a binary."""
    for flag in ["--version", "-version"]:
        ok, out = run([binary, flag])
        if ok and out:
            return out.splitlines()[0]
    return None


def detect_package_manager():
    """Return the system package manager name and install command prefix."""
    system = platform.system()

    if system == "Darwin":
        if shutil.which("brew"):
            return "brew", ["brew", "install"]
        return None, None

    elif system == "Windows":
        if shutil.which("winget"):
            return "winget", ["winget", "install", "--accept-source-agreements",
                              "--accept-package-agreements"]
        return None, None

    # Linux and others: skip automatic install
    return None, None


# -- Checks ----------------------------------------------------------------

def check_python():
    """Verify Python version."""
    v = sys.version_info
    version_str = f"{v.major}.{v.minor}.{v.micro}"
    if v >= (3, 10):
        print(f"  {OK} Python {version_str}")
        return True
    else:
        print(f"  {WARN} Python {version_str} (3.10+ recommended)")
        return True  # still usable, just warn


def check_pip_packages():
    """Check and install packages from requirements.txt."""
    req_path = os.path.join(os.path.dirname(__file__) or ".", "requirements.txt")

    if not os.path.exists(req_path):
        print(f"  {FAIL} requirements.txt not found")
        return False

    with open(req_path) as f:
        packages = [line.strip() for line in f
                    if line.strip() and not line.startswith("#")]

    if not packages:
        print(f"  {OK} No Python packages required")
        return True

    all_installed = True
    missing = []

    for pkg in packages:
        # Extract package name (without version specifiers)
        name = pkg.split(">=")[0].split("==")[0].split("<")[0].split(">")[0].strip()
        ok, out = run([sys.executable, "-m", "pip", "show", name])
        if ok:
            # Get version from pip show output
            version = ""
            for line in out.splitlines():
                if line.startswith("Version:"):
                    version = line.split(":", 1)[1].strip()
                    break
            print(f"  {OK} {name} {version}")
        else:
            print(f"  {FAIL} {name} — not installed")
            missing.append(pkg)
            all_installed = False

    if missing:
        print(f"\n  {INFO} Installing missing packages: {', '.join(missing)}")
        ok, _ = run(
            [sys.executable, "-m", "pip", "install", *missing],
            capture=False
        )
        if ok:
            print(f"  {OK} Packages installed successfully")
            return True
        else:
            print(f"  {FAIL} pip install failed")
            return False

    return all_installed


def check_ffmpeg():
    """Check for FFmpeg and offer to install if missing."""
    ffmpeg_path = shutil.which("ffmpeg")

    if ffmpeg_path:
        version = get_version("ffmpeg")
        print(f"  {OK} FFmpeg found: {ffmpeg_path}")
        if version:
            print(f"     {version}")
        return True

    print(f"  {FAIL} FFmpeg — not found in PATH")

    # Try to install
    mgr_name, install_cmd = detect_package_manager()

    if not install_cmd:
        system = platform.system()
        print(f"\n  {WARN} No supported package manager found.")
        if system == "Darwin":
            print(f"     Install Homebrew first:  /bin/bash -c \"$(curl -fsSL https://raw.githubusercontent.com/Homebrew/install/HEAD/install.sh)\"")
            print(f"     Then re-run this script.")
        elif system == "Windows":
            print(f"     Install Chocolatey (https://chocolatey.org) or winget, then re-run.")
            print(f"     Or download FFmpeg manually: https://ffmpeg.org/download.html")
        else:
            print(f"     Download FFmpeg manually: https://ffmpeg.org/download.html")
        return False

    # Map package names (some managers use different names)
    ffmpeg_pkg = "ffmpeg"
    if mgr_name == "winget":
        ffmpeg_pkg = "Gyan.FFmpeg"

    print(f"\n  {INFO} Installing FFmpeg via {mgr_name}...")
    cmd = [*install_cmd, ffmpeg_pkg]
    ok, _ = run(cmd, capture=False)

    if ok and shutil.which("ffmpeg"):
        version = get_version("ffmpeg")
        print(f"  {OK} FFmpeg installed successfully")
        if version:
            print(f"     {version}")
        return True
    else:
        print(f"  {FAIL} FFmpeg installation failed. Please install manually.")
        return False


# -- Main ------------------------------------------------------------------

def main():
    system = platform.system()
    arch = platform.machine()
    print(Color.bold(f"\n  Setup — {system} {arch}\n"))
    print(Color.bold("  Python"))
    check_python()

    print(Color.bold("\n  Python Packages"))
    pip_ok = check_pip_packages()

    print(Color.bold("\n  FFmpeg"))
    ffmpeg_ok = check_ffmpeg()

    privacy_ok = True
    if system == "Darwin":
        print(Color.bold("\n  macOS Privacy Permissions"))
        try:
            import macos_privacy
            privacy_ok = macos_privacy.check_and_request_permission()
        except ImportError:
            print(f"  {WARN} macos_privacy.py not found.")

    # Summary
    print(Color.bold("\n  Summary"))
    if pip_ok and ffmpeg_ok and privacy_ok:
        print(f"  {OK} Everything is set up. You're ready to go!\n")
        return 0
    else:
        if not pip_ok:
            print(f"  {FAIL} Some Python packages could not be installed.")
        if not ffmpeg_ok:
            print(f"  {FAIL} FFmpeg is not available.")
        if not privacy_ok:
            print(f"  {FAIL} Missing Screen Recording permissions (must restart terminal once granted).")
        print(f"\n  Fix the issues above and run this script again.\n")
        return 1


if __name__ == "__main__":
    sys.exit(main())
