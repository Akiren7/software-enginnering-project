import aiohttp

async def perform_login(base_url: str, login_id: str, password: str) -> str:
    """Logs in and returns the session UUID. Raises on failure."""
    async with aiohttp.ClientSession() as session:
        async with session.post(f"{base_url}/login", json={"login_id": login_id, "password": password}) as resp:
            if resp.status == 200:
                data = await resp.json()
                return data["uuid"]
            else:
                body = await resp.text()
                raise ValueError(f"Login failed ({resp.status}): {body}")

async def check_health(base_url: str):
    """Quick HTTP health check."""
    async with aiohttp.ClientSession() as session:
        async with session.get(f"{base_url}/health") as resp:
            data = await resp.json()
            print(f"[HTTP] Health: {data}")
