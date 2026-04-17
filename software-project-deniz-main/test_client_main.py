import unittest
from unittest.mock import AsyncMock, patch

from common.discovery import discover_server_with_local_fallback


class ClientMainTests(unittest.IsolatedAsyncioTestCase):
    async def test_discovery_prefers_udp_result_when_available(self):
        with (
            patch("common.discovery.discover_server", new=AsyncMock(return_value=("192.168.1.50", 8080))),
            patch("common.discovery._probe_local_server", new=AsyncMock(return_value=("127.0.0.1", 8080))) as probe_mock,
        ):
            result = await discover_server_with_local_fallback("default", 5.0, local_port=8080)

        self.assertEqual(result, ("192.168.1.50", 8080))
        probe_mock.assert_not_awaited()

    async def test_discovery_uses_localhost_fallback_when_udp_lookup_fails(self):
        with (
            patch("common.discovery.discover_server", new=AsyncMock(return_value=None)),
            patch("common.discovery._probe_local_server", new=AsyncMock(return_value=("127.0.0.1", 8080))) as probe_mock,
        ):
            result = await discover_server_with_local_fallback("default", 5.0, local_port=8080)

        self.assertEqual(result, ("127.0.0.1", 8080))
        probe_mock.assert_awaited_once_with("default", 8080, log_prefix="[DISCOVERY]")


if __name__ == "__main__":
    unittest.main()
