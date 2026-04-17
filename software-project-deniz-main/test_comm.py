import subprocess
import sys
import time


HOST = "127.0.0.1"
PORT = "8097"
SERVER_ID = "qt-test"


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
            "--exam-duration",
            "5",
            "--reset",
        ],
        stdin=subprocess.PIPE,
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        text=True,
    )


def _start_client() -> subprocess.Popen:
    return subprocess.Popen(
        [
            sys.executable,
            "-m",
            "client.main",
            "--host",
            HOST,
            "--port",
            PORT,
            "--login-id",
            "student1",
            "--password",
            "secret1",
            "--no-record",
        ],
        stdin=subprocess.PIPE,
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        text=True,
    )


def _send_line(process: subprocess.Popen, text: str):
    if process.stdin is None:
        return
    process.stdin.write(text + "\n")
    process.stdin.flush()


def main():
    print("--- Starting Server ---")
    server = _start_server()
    time.sleep(2)

    print("--- Starting Client ---")
    client = _start_client()

    time.sleep(2)
    print("--- Opening exam globally ---")
    _send_line(server, "/startexam")

    time.sleep(1)
    print("--- Starting client exam ---")
    _send_line(client, "start")

    time.sleep(2)
    print("--- Sending sample message ---")
    _send_line(client, "hello from test_comm")

    time.sleep(2)

    print("--- Stopping Processes ---")
    client.terminate()
    server.terminate()

    print("\n\n=== SERVER LOGS ===")
    try:
        outs, _ = server.communicate(timeout=2)
        print(outs)
    except Exception:
        pass

    print("\n\n=== CLIENT LOGS ===")
    try:
        outc, _ = client.communicate(timeout=2)
        print(outc)
    except Exception:
        pass


if __name__ == "__main__":
    main()
