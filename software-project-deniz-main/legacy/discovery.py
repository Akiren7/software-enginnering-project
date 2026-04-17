"""
discovery.py -- UDP discovery for LAN and overlay networks.

The server periodically sends a small beacon packet so clients can find it
automatically. Plain global broadcast (255.255.255.255) often does not work on
VPN / overlay adapters such as ZeroTier, so this module sends discovery packets
to multiple targets:

- global broadcast
- subnet-directed broadcast derived from the local IP
- optional multicast group
- optional explicit targets passed by the caller
"""

import asyncio
import json
import socket
import struct
from typing import Iterable, List, Optional, Sequence, Tuple


DISCOVERY_PORT = 5354
BROADCAST_ADDR = "255.255.255.255"
MULTICAST_GROUP = "239.255.42.99"
BEACON_MAGIC = "6064-SERVER"  # simple identifier so we ignore unrelated traffic


def _unique_preserve_order(items: Iterable[str]) -> List[str]:
    seen = set()
    result = []
    for item in items:
        if not item or item in seen:
            continue
        seen.add(item)
        result.append(item)
    return result


class ServerAnnouncer:
    """Sends a beacon every `interval` seconds so clients can find us."""

    def __init__(
        self,
        server_host: str,
        server_port: int,
        server_id: str = "default",
        interval: float = 3.0,
        extra_targets: Optional[Sequence[str]] = None,
        use_multicast: bool = True,
    ):
        self.server_host = server_host
        self.server_port = server_port
        self.server_id = server_id
        self.interval = interval
        self.extra_targets = list(extra_targets or [])
        self.use_multicast = use_multicast
        self._sock = None
        self._task = None

    def _make_beacon(self) -> bytes:
        ip = self._get_local_ip()
        payload = json.dumps(
            {
                "magic": BEACON_MAGIC,
                "server_id": self.server_id,
                "host": ip,
                "port": self.server_port,
            }
        )
        return payload.encode("ascii")

    @staticmethod
    def _get_local_ip() -> str:
        """Best-effort local IP detection."""
        try:
            s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
            s.connect(("8.8.8.8", 80))
            ip = s.getsockname()[0]
            s.close()
            return ip
        except Exception:
            return "127.0.0.1"

    @staticmethod
    def _directed_broadcast_for_ip(ip: str) -> Optional[str]:
        """Best-effort /24 directed broadcast, useful on some overlay nets."""
        parts = ip.split(".")
        if len(parts) != 4:
            return None
        return ".".join(parts[:3] + ["255"])

    def _build_targets(self) -> List[str]:
        ip = self._get_local_ip()
        targets = [BROADCAST_ADDR]

        directed = self._directed_broadcast_for_ip(ip)
        if directed:
            targets.append(directed)

        if self.use_multicast:
            targets.append(MULTICAST_GROUP)

        targets.extend(self.extra_targets)
        return _unique_preserve_order(targets)

    async def start(self):
        self._sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        self._sock.setsockopt(socket.SOL_SOCKET, socket.SO_BROADCAST, 1)
        try:
            ttl = struct.pack("b", 1)
            self._sock.setsockopt(socket.IPPROTO_IP, socket.IP_MULTICAST_TTL, ttl)
        except OSError:
            pass
        self._sock.setblocking(False)
        self._task = asyncio.create_task(self._loop())
        print(
            f"[DISCOVERY] Announcing '{self.server_id}' on UDP port {DISCOVERY_PORT} "
            f"every {self.interval}s"
        )

    async def _loop(self):
        try:
            while True:
                beacon = self._make_beacon()
                for target in self._build_targets():
                    try:
                        self._sock.sendto(beacon, (target, DISCOVERY_PORT))
                    except OSError as e:
                        if target == BROADCAST_ADDR and getattr(e, "errno", None) in (49, 51, 65):
                            pass
                        else:
                            print(f"[DISCOVERY] sendto({target}) failed: {e}")
                await asyncio.sleep(self.interval)
        except asyncio.CancelledError:
            pass
        finally:
            self._sock.close()

    async def stop(self):
        if self._task:
            self._task.cancel()
            await self._task


def _create_listen_socket(bind_host: str = "") -> socket.socket:
    sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
    if hasattr(socket, "SO_REUSEPORT"):
        try:
            sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEPORT, 1)
        except OSError:
            pass
    sock.bind((bind_host, DISCOVERY_PORT))
    sock.setblocking(False)
    return sock


def _join_multicast(sock: socket.socket, group: str = MULTICAST_GROUP):
    try:
        mreq = socket.inet_aton(group) + socket.inet_aton("0.0.0.0")
        sock.setsockopt(socket.IPPROTO_IP, socket.IP_ADD_MEMBERSHIP, mreq)
    except OSError as e:
        print(f"[DISCOVERY] Multicast join failed for {group}: {e}")


async def discover_server(
    server_id: str = "default",
    timeout: float = 10.0,
    listen_multicast: bool = True,
    bind_host: str = "",
):
    """
    Listen for a server beacon.
    Only matches servers with the given server_id.
    Returns (host, port) of the first matching server, or None on timeout.
    """
    print(f"[DISCOVERY] Searching for server '{server_id}' (timeout {timeout}s)...")

    try:
        sock = _create_listen_socket(bind_host=bind_host)
        if listen_multicast:
            _join_multicast(sock)
    except OSError as e:
        print(f"[DISCOVERY] ERROR: Could not bind to UDP port {DISCOVERY_PORT}: {e}")
        return None

    loop = asyncio.get_event_loop()

    try:
        end_time = loop.time() + timeout
        while loop.time() < end_time:
            remaining = end_time - loop.time()
            try:
                data, addr = await asyncio.wait_for(
                    loop.sock_recvfrom(sock, 1024),
                    timeout=min(remaining, 1.0),
                )
                msg = json.loads(data.decode("ascii"))
                if msg.get("magic") == BEACON_MAGIC and msg.get("server_id") == server_id:
                    host = msg.get("host") or addr[0]
                    port = msg["port"]
                    print(f"[DISCOVERY] Found server '{server_id}' at {host}:{port}")
                    return host, port
            except asyncio.TimeoutError:
                continue
            except (json.JSONDecodeError, KeyError):
                continue
    finally:
        sock.close()

    print("[DISCOVERY] No server found.")
    return None


async def check_duplicate_server(
    server_id: str,
    timeout: float = 5.0,
    listen_multicast: bool = True,
    bind_host: str = "",
):
    """
    Listen briefly for beacons. If we hear another server with the same ID,
    return its (host, port). Otherwise return None.
    """
    print(f"[CHECK] Checking for existing server '{server_id}' on the network...")

    try:
        sock = _create_listen_socket(bind_host=bind_host)
        if listen_multicast:
            _join_multicast(sock)
    except OSError as e:
        print(f"[CHECK] WARNING: Could not bind UDP port {DISCOVERY_PORT}: {e}")
        print("[CHECK] Skipping duplicate check, proceeding anyway.")
        return None

    loop = asyncio.get_event_loop()

    try:
        end_time = loop.time() + timeout
        while loop.time() < end_time:
            remaining = end_time - loop.time()
            try:
                data, addr = await asyncio.wait_for(
                    loop.sock_recvfrom(sock, 1024),
                    timeout=min(remaining, 1.0),
                )
                msg = json.loads(data.decode("ascii"))
                if msg.get("magic") == BEACON_MAGIC and msg.get("server_id") == server_id:
                    host = msg.get("host") or addr[0]
                    port = msg["port"]
                    return host, port
            except asyncio.TimeoutError:
                continue
            except (json.JSONDecodeError, KeyError):
                continue
    finally:
        sock.close()

    return None
