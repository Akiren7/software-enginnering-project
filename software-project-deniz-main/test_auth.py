import os
import signal
import subprocess
import sys
import time


HOST = "127.0.0.1"
PORT = "8098"
SERVER_ID = "test-server"


def _start_server() -> subprocess.Popen:
    return subprocess.Popen(
        [
            sys.executable,
            "-m",
            "server.main",
            "--id",
            SERVER_ID,
            "--host",
            HOST,
            "--port",
            PORT,
            "--reset",
        ],
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
    )


def _run_login_check(login_id: str, password: str) -> subprocess.CompletedProcess:
    return subprocess.run(
        [
            sys.executable,
            "-m",
            "client.main",
            "--host",
            HOST,
            "--port",
            PORT,
            "--login-id",
            login_id,
            "--password",
            password,
            "--no-record",
            "--check-login",
        ],
        capture_output=True,
        text=True,
    )


def _print_result(label: str, result: subprocess.CompletedProcess):
    print(f"{label}: returncode={result.returncode}")
    output = (result.stdout + "\n" + result.stderr).strip()
    if not output:
        print("  (no output)")
        return
    for line in output.splitlines()[:8]:
        print(f"  {line}")


def main():
    print("--- Starting server ---")
    server = _start_server()
    time.sleep(2)

    print("--- Checking valid credentials ---")
    valid_result = _run_login_check("student1", "secret1")
    _print_result("valid login", valid_result)

    print("--- Checking invalid credentials ---")
    invalid_result = _run_login_check("student1", "wrong-password")
    _print_result("invalid login", invalid_result)

    print("--- Stopping server ---")
    server.send_signal(signal.SIGINT)
    server.wait()

    print("--- Verifying data ---")
    os.system("find data -type f")


if __name__ == "__main__":
    main()
