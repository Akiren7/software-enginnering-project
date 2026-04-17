import json
import secrets
import socket
import ssl
import threading
from datetime import datetime, timedelta

HOST = "0.0.0.0"
PORT = 8443

CERT_FILE = "server.crt"
KEY_FILE = "server.key"

# Demo only. Replace with hashed passwords in a real system.
USERS = {
    "student1": {"password": "1234", "role": "student"},
    "proctor1": {"password": "abcd", "role": "proctor"},
}

SESSIONS = {}


def send_json(conn, obj):
    data = (json.dumps(obj) + "\n").encode("utf-8")
    conn.sendall(data)


def recv_json(conn_file):
    line = conn_file.readline()
    if not line:
        return None
    return json.loads(line.decode("utf-8"))


def handle_client(connstream, addr):
    print(f"[+] Connected: {addr}")
    conn_file = connstream.makefile("rb")

    try:
        msg = recv_json(conn_file)
        if not msg or msg.get("type") != "login":
            send_json(connstream, {"ok": False, "error": "expected login"})
            return

        username = msg.get("username", "")
        password = msg.get("password", "")

        user = USERS.get(username)
        if not user or user["password"] != password:
            send_json(connstream, {"ok": False, "error": "invalid credentials"})
            return

        token = secrets.token_urlsafe(32)
        expires_at = datetime.utcnow() + timedelta(minutes=30)

        SESSIONS[token] = {
            "username": username,
            "role": user["role"],
            "expires_at": expires_at,
        }

        send_json(connstream, {
            "ok": True,
            "type": "login_ok",
            "session_token": token,
            "expires_at_utc": expires_at.isoformat() + "Z"
        })

        while True:
            msg = recv_json(conn_file)
            if msg is None:
                break

            token = msg.get("session_token")
            session = SESSIONS.get(token)

            if not session:
                send_json(connstream, {"ok": False, "error": "invalid session"})
                continue

            if datetime.utcnow() > session["expires_at"]:
                del SESSIONS[token]
                send_json(connstream, {"ok": False, "error": "session expired"})
                continue

            if msg.get("type") == "ping":
                send_json(connstream, {
                    "ok": True,
                    "type": "pong",
                    "user": session["username"],
                    "role": session["role"]
                })
            else:
                send_json(connstream, {"ok": False, "error": "unknown request"})

    except Exception as e:
        print(f"[!] Error with {addr}: {e}")
    finally:
        try:
            connstream.shutdown(socket.SHUT_RDWR)
        except Exception:
            pass
        connstream.close()
        print(f"[-] Disconnected: {addr}")


def main():
    context = ssl.SSLContext(ssl.PROTOCOL_TLS_SERVER)
    context.load_cert_chain(certfile=CERT_FILE, keyfile=KEY_FILE)

    with socket.socket(socket.AF_INET, socket.SOCK_STREAM, 0) as sock:
        sock.bind((HOST, PORT))
        sock.listen(5)
        print(f"TLS server listening on {HOST}:{PORT}")

        while True:
            client_sock, addr = sock.accept()
            try:
                connstream = context.wrap_socket(client_sock, server_side=True)
                threading.Thread(target=handle_client, args=(connstream, addr), daemon=True).start()
            except Exception as e:
                print(f"[!] TLS handshake failed from {addr}: {e}")
                client_sock.close()


if __name__ == "__main__":
    main()
