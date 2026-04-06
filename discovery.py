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
import ipaddress
import json
import socket
import struct
from typing import Iterable, List, Optional, Sequence, Tuple

import aiohttp
import psutil


DISCOVERY_PORT = 5354
BROADCAST_ADDR = "255.255.255.255"
MULTICAST_GROUP = "239.255.42.99"
BEACON_MAGIC = "6064-SERVER"  # simple identifier so we ignore unrelated traffic
VPN_INTERFACE_HINTS = (
    "vpn",
    "tun",
    "tap",
    "utun",
    "ppp",
    "ipsec",
    "wireguard",
    "wg",
    "zerotier",
    "tailscale",
)


def _unique_preserve_order(items: Iterable[str]) -> List[str]:
    seen = set()
    result = []
    for item in items:
        if not item or item in seen:
            continue
        seen.add(item)
        result.append(item)
    return result


def _normalize_ipv4(value: Optional[str]) -> Optional[str]:
    if not value:
        return None
    try:
        return str(ipaddress.IPv4Address(value))
    except ipaddress.AddressValueError:
        return None


def _is_routable_ipv4(ip: Optional[str]) -> bool:
    if not ip:
        return False
    try:
        address = ipaddress.IPv4Address(ip)
    except ipaddress.AddressValueError:
        return False
    return not (
        address.is_loopback
        or address.is_unspecified
        or address.is_link_local
        or address.is_multicast
    )


def _safe_net_if_stats():
    try:
        return psutil.net_if_stats()
    except Exception:
        return {}


def _safe_net_if_addrs():
    try:
        return psutil.net_if_addrs()
    except Exception:
        return {}


def _looks_like_vpn_interface(interface_name: str) -> bool:
    lowered = interface_name.lower()
    return any(token in lowered for token in VPN_INTERFACE_HINTS)


def _iter_ipv4_interfaces() -> List[dict]:
    entries = []
    interface_stats = _safe_net_if_stats()
    interface_addresses = _safe_net_if_addrs()

    for interface_name in sorted(interface_addresses):
        interface_stat = interface_stats.get(interface_name)
        if interface_stat is not None and not bool(getattr(interface_stat, "isup", False)):
            continue

        for address in interface_addresses[interface_name]:
            family_name = str(getattr(address, "family", ""))
            if getattr(address, "family", None) != socket.AF_INET and family_name not in {
                "AF_INET",
                "AddressFamily.AF_INET",
            }:
                continue

            ip = _normalize_ipv4(getattr(address, "address", None))
            if not _is_routable_ipv4(ip):
                continue

            entries.append(
                {
                    "name": interface_name,
                    "ip": ip,
                    "broadcast": _normalize_ipv4(getattr(address, "broadcast", None)),
                    "looks_like_vpn": _looks_like_vpn_interface(interface_name),
                }
            )

    return entries


def _preferred_interface_sort_key(entry: dict) -> tuple:
    address = ipaddress.IPv4Address(entry["ip"])
    return (
        0 if entry.get("broadcast") else 1,
        0 if address.is_private else 1,
        1 if entry.get("looks_like_vpn") else 0,
        entry["name"],
        entry["ip"],
    )


def _default_route_ip() -> Optional[str]:
    try:
        sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        sock.connect(("8.8.8.8", 80))
        ip = sock.getsockname()[0]
        sock.close()
        return _normalize_ipv4(ip)
    except Exception:
        return None


def _candidate_ipv4_hosts() -> List[str]:
    interface_hosts = [
        entry["ip"]
        for entry in sorted(_iter_ipv4_interfaces(), key=_preferred_interface_sort_key)
    ]
    default_ip = _default_route_ip()
    return _unique_preserve_order([*interface_hosts, default_ip, "127.0.0.1"])


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
        host, host_is_explicit = self._get_advertised_host()
        payload = json.dumps(
            {
                "magic": BEACON_MAGIC,
                "server_id": self.server_id,
                "host": host,
                "host_is_explicit": host_is_explicit,
                "port": self.server_port,
            }
        )
        return payload.encode("ascii")

    @staticmethod
    def _get_local_ip() -> str:
        """Best-effort local IPv4 detection, preferring broadcast-capable LANs."""
        return _candidate_ipv4_hosts()[0]

    @staticmethod
    def _directed_broadcast_for_ip(ip: str) -> Optional[str]:
        """Best-effort /24 directed broadcast, useful on some overlay nets."""
        parts = ip.split(".")
        if len(parts) != 4:
            return None
        return ".".join(parts[:3] + ["255"])

    def _get_advertised_host(self) -> Tuple[str, bool]:
        explicit_host = _normalize_ipv4(self.server_host)
        if explicit_host and explicit_host not in {"0.0.0.0"}:
            return explicit_host, True
        return self._get_local_ip(), False

    def _broadcast_targets(self) -> List[str]:
        targets = [BROADCAST_ADDR]
        interface_entries = _iter_ipv4_interfaces()

        directed_targets = []
        for entry in interface_entries:
            directed = entry.get("broadcast") or self._directed_broadcast_for_ip(entry["ip"])
            if directed and directed != BROADCAST_ADDR:
                directed_targets.append(directed)

        if not directed_targets:
            fallback_ip = _default_route_ip()
            if fallback_ip:
                directed = self._directed_broadcast_for_ip(fallback_ip)
                if directed and directed != BROADCAST_ADDR:
                    directed_targets.append(directed)

        targets.extend(directed_targets)
        return _unique_preserve_order(targets)

    def _build_targets(self) -> List[str]:
        targets = self._broadcast_targets()

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
                broadcast_targets = set(self._broadcast_targets())
                for target in self._build_targets():
                    try:
                        self._sock.sendto(beacon, (target, DISCOVERY_PORT))
                    except OSError as e:
                        # Ignore common broadcast errors on some OSes
                        is_broadcast = target in broadcast_targets
                        err_code = getattr(e, "errno", None)
                        if is_broadcast and err_code in (49, 51, 65):
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


async def _listen_for_server(
    server_id: str,
    timeout: float,
    listen_multicast: bool,
    bind_host: str,
    *,
    error_prefix: str,
    bind_failure_result,
    on_bind_failure=None,
    on_timeout=None,
):
    try:
        sock = _create_listen_socket(bind_host=bind_host)
        if listen_multicast:
            _join_multicast(sock)
    except OSError as e:
        print(f"{error_prefix} {e}")
        if on_bind_failure:
            on_bind_failure()
        return bind_failure_result

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
            except asyncio.TimeoutError:
                continue

            server_info = _parse_server_beacon(data, addr, server_id)
            if server_info is not None:
                return server_info
    finally:
        sock.close()

    if on_timeout:
        on_timeout()
    return None


def _parse_server_beacon(data: bytes, addr: Tuple[str, int], server_id: str):
    try:
        msg = json.loads(data.decode("ascii"))
    except (json.JSONDecodeError, UnicodeDecodeError):
        return None

    if msg.get("magic") != BEACON_MAGIC or msg.get("server_id") != server_id:
        return None

    advertised_host = _normalize_ipv4(msg.get("host"))
    source_host = _normalize_ipv4(addr[0])
    if msg.get("host_is_explicit") and advertised_host:
        host = advertised_host
    else:
        host = source_host or advertised_host
    port = msg.get("port")
    if port is None:
        return None
    return host, port


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
    result = await _listen_for_server(
        server_id,
        timeout,
        listen_multicast,
        bind_host,
        error_prefix=f"[DISCOVERY] ERROR: Could not bind to UDP port {DISCOVERY_PORT}:",
        bind_failure_result=None,
        on_timeout=lambda: print("[DISCOVERY] No server found."),
    )
    if result is not None:
        host, port = result
        print(f"[DISCOVERY] Found server '{server_id}' at {host}:{port}")
    return result


async def _probe_local_server(
    server_id: str,
    port: int,
    *,
    log_prefix: str,
) -> Optional[Tuple[str, int]]:
    timeout = aiohttp.ClientTimeout(total=1.5)
    try:
        async with aiohttp.ClientSession(timeout=timeout) as session:
            async with session.get(f"http://127.0.0.1:{port}/health") as resp:
                if resp.status != 200:
                    return None
                data = await resp.json()
    except (aiohttp.ClientError, asyncio.TimeoutError, OSError, ValueError):
        return None

    if data.get("server_id") != server_id:
        return None

    print(f"{log_prefix} Falling back to local server at 127.0.0.1:{port}")
    return "127.0.0.1", port


async def discover_server_with_local_fallback(
    server_id: str = "default",
    timeout: float = 10.0,
    listen_multicast: bool = True,
    bind_host: str = "",
    *,
    local_port: int = 8080,
):
    result = await discover_server(
        server_id=server_id,
        timeout=timeout,
        listen_multicast=listen_multicast,
        bind_host=bind_host,
    )
    if result is not None:
        return result
    return await _probe_local_server(server_id, local_port, log_prefix="[DISCOVERY]")


async def check_duplicate_server(
    server_id: str,
    timeout: float = 5.0,
    listen_multicast: bool = True,
    bind_host: str = "",
    *,
    local_port: Optional[int] = None,
):
    """
    Listen briefly for beacons. If we hear another server with the same ID,
    return its (host, port). Otherwise return None.
    """
    print(f"[CHECK] Checking for existing server '{server_id}' on the network...")
    result = await _listen_for_server(
        server_id,
        timeout,
        listen_multicast,
        bind_host,
        error_prefix=f"[CHECK] WARNING: Could not bind UDP port {DISCOVERY_PORT}:",
        bind_failure_result=None,
        on_bind_failure=lambda: print("[CHECK] Skipping duplicate check, proceeding anyway."),
        on_timeout=None,
    )
    if result is not None or local_port is None:
        return result
    return await _probe_local_server(server_id, local_port, log_prefix="[CHECK]")
