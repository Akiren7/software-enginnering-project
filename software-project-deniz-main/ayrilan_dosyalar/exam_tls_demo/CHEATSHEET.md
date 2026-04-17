# Simple TLS + Login + Session Token Cheatsheet

## What each file does
- `generate_cert.py`: creates `server.crt` and `server.key`
- `server.py`: runs the TLS server and issues session tokens after login
- `client.py`: verifies the server certificate, logs in, then uses the session token

## Install requirement
```bash
pip install cryptography
```

## Step 1: Generate a short-lived certificate
Example: 6-hour certificate for local testing
```bash
python generate_cert.py --cn exam-server --hours 6 --ip 127.0.0.1 --dns exam-server
```

This creates:
- `server.key` -> private key, keep on the server only
- `server.crt` -> public certificate, copy to the client side

## Step 2: Start the server
```bash
python server.py
```

Expected message:
```text
TLS server listening on 0.0.0.0:8443
```

## Step 3: Run the client
Make sure `server.crt` is in the same folder as `client.py`.

```bash
python client.py
```

## Flow
1. Client discovers or knows the server IP
2. Client connects with TLS
3. Client verifies `server.crt`
4. Student logs in with ID/password
5. Server gives back a short-lived session token
6. Client uses that token in later requests

## Important rules
- Keep `server.key` only on the server
- Never embed the private key in the client
- It is okay to ship `server.crt` with the client
- Use the session token as a temporary login/session credential, not as the TLS key

## Quick customization
### Change server IP in `client.py`
```python
HOST = "192.168.1.50"
```

### Change server port in both files
```python
PORT = 8443
```

### Change demo users in `server.py`
```python
USERS = {
    "student1": {"password": "1234", "role": "student"},
    "proctor1": {"password": "abcd", "role": "proctor"},
}
```

## For your real project later
- hash passwords instead of storing plain text
- make token expiry match the exam duration
- add exam ID / role checks
- add discovery broadcast separately
- prefer proper SAN names/IPs instead of disabling hostname checks
