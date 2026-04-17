import json
import socket
import ssl

HOST = "127.0.0.1"   # change to the server IP
PORT = 8443
SERVER_CERT = "server.crt"


def send_json(conn, obj):
    data = (json.dumps(obj) + "\n").encode("utf-8")
    conn.sendall(data)


def recv_json(conn_file):
    line = conn_file.readline()
    if not line:
        return None
    return json.loads(line.decode("utf-8"))


def main():
    context = ssl.create_default_context(ssl.Purpose.SERVER_AUTH)
    context.load_verify_locations(cafile=SERVER_CERT)
    context.check_hostname = False
    context.verify_mode = ssl.CERT_REQUIRED

    with socket.create_connection((HOST, PORT)) as sock:
        with context.wrap_socket(sock, server_hostname="exam-server") as ssock:
            print("[+] TLS connected")
            print("[+] Cipher:", ssock.cipher())

            conn_file = ssock.makefile("rb")

            send_json(ssock, {
                "type": "login",
                "username": "student1",
                "password": "1234"
            })

            reply = recv_json(conn_file)
            print("LOGIN REPLY:", reply)

            if not reply or not reply.get("ok"):
                return

            session_token = reply["session_token"]

            send_json(ssock, {
                "type": "ping",
                "session_token": session_token
            })

            reply = recv_json(conn_file)
            print("PING REPLY:", reply)


if __name__ == "__main__":
    main()
