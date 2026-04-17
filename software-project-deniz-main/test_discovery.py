import json
import socket
import unittest
from types import SimpleNamespace
from unittest.mock import AsyncMock, patch

from common.discovery import (
    BEACON_MAGIC,
    BROADCAST_ADDR,
    ServerAnnouncer,
    _candidate_ipv4_hosts,
    _iter_ipv4_interfaces,
    _parse_server_beacon,
    check_duplicate_server,
)


def _ifstat(isup: bool = True):
    return SimpleNamespace(isup=isup)


def _ipv4(address: str, broadcast: str | None = None):
    return SimpleNamespace(
        family=socket.AF_INET,
        address=address,
        broadcast=broadcast,
    )


class DiscoveryTests(unittest.TestCase):
    def test_iter_ipv4_interfaces_skips_loopback_and_down_interfaces(self):
        with (
            patch(
                "common.discovery._safe_net_if_stats",
                return_value={
                    "en0": _ifstat(isup=True),
                    "utun4": _ifstat(isup=True),
                    "lo0": _ifstat(isup=True),
                    "en9": _ifstat(isup=False),
                },
            ),
            patch(
                "common.discovery._safe_net_if_addrs",
                return_value={
                    "en0": [_ipv4("192.168.1.50", "192.168.1.255")],
                    "utun4": [_ipv4("10.7.0.9")],
                    "lo0": [_ipv4("127.0.0.1")],
                    "en9": [_ipv4("192.168.55.10", "192.168.55.255")],
                },
            ),
        ):
            interfaces = _iter_ipv4_interfaces()

        self.assertEqual(
            interfaces,
            [
                {
                    "name": "en0",
                    "ip": "192.168.1.50",
                    "broadcast": "192.168.1.255",
                    "looks_like_vpn": False,
                },
                {
                    "name": "utun4",
                    "ip": "10.7.0.9",
                    "broadcast": None,
                    "looks_like_vpn": True,
                },
            ],
        )

    def test_candidate_ipv4_hosts_prefers_broadcast_capable_lan_over_vpn_route(self):
        with (
            patch(
                "common.discovery._iter_ipv4_interfaces",
                return_value=[
                    {
                        "name": "utun4",
                        "ip": "10.7.0.9",
                        "broadcast": None,
                        "looks_like_vpn": True,
                    },
                    {
                        "name": "en0",
                        "ip": "192.168.1.50",
                        "broadcast": "192.168.1.255",
                        "looks_like_vpn": False,
                    },
                ],
            ),
            patch("common.discovery._default_route_ip", return_value="10.7.0.9"),
        ):
            hosts = _candidate_ipv4_hosts()

        self.assertEqual(hosts[0], "192.168.1.50")
        self.assertEqual(hosts[:3], ["192.168.1.50", "10.7.0.9", "127.0.0.1"])

    def test_broadcast_targets_include_each_active_ipv4_network(self):
        announcer = ServerAnnouncer(server_host="0.0.0.0", server_port=8080)

        with patch(
            "common.discovery._iter_ipv4_interfaces",
            return_value=[
                {
                    "name": "en0",
                    "ip": "192.168.1.50",
                    "broadcast": "192.168.1.255",
                    "looks_like_vpn": False,
                },
                {
                    "name": "utun4",
                    "ip": "10.7.0.9",
                    "broadcast": None,
                    "looks_like_vpn": True,
                },
            ],
        ):
            targets = announcer._broadcast_targets()

        self.assertEqual(
            targets,
            [
                BROADCAST_ADDR,
                "192.168.1.255",
                "10.7.0.255",
            ],
        )

    def test_parse_server_beacon_prefers_packet_source_for_auto_detected_host(self):
        beacon = json.dumps(
            {
                "magic": BEACON_MAGIC,
                "server_id": "default",
                "host": "10.7.0.9",
                "host_is_explicit": False,
                "port": 8080,
            }
        ).encode("ascii")

        host, port = _parse_server_beacon(beacon, ("192.168.1.50", 5354), "default")

        self.assertEqual((host, port), ("192.168.1.50", 8080))

    def test_parse_server_beacon_honors_explicit_host_binding(self):
        beacon = json.dumps(
            {
                "magic": BEACON_MAGIC,
                "server_id": "default",
                "host": "127.0.0.1",
                "host_is_explicit": True,
                "port": 8080,
            }
        ).encode("ascii")

        host, port = _parse_server_beacon(beacon, ("192.168.1.50", 5354), "default")

        self.assertEqual((host, port), ("127.0.0.1", 8080))


class DiscoveryAsyncTests(unittest.IsolatedAsyncioTestCase):
    async def test_duplicate_check_uses_local_probe_when_udp_lookup_fails(self):
        with (
            patch("common.discovery._listen_for_server", new=AsyncMock(return_value=None)),
            patch(
                "common.discovery._probe_local_server",
                new=AsyncMock(return_value=("127.0.0.1", 8080)),
            ) as probe_mock,
        ):
            result = await check_duplicate_server("default", timeout=5.0, local_port=8080)

        self.assertEqual(result, ("127.0.0.1", 8080))
        probe_mock.assert_awaited_once_with("default", 8080, log_prefix="[CHECK]")


if __name__ == "__main__":
    unittest.main()
