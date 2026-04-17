import os
import aiohttp

async def fetch_exam_prep(base_url: str, session_uuid: str):
    """Fetches the exam configuration and files."""
    async with aiohttp.ClientSession() as session:
        # Get config
        async with session.get(f"{base_url}/exam/config") as resp:
            if resp.status == 200:
                config = await resp.json()
                mins = config.get("exam_duration_seconds", 0) // 60
                print(f"[EXAM] Config loaded: Exam duration is {mins} minutes.")
            else:
                print(f"[EXAM] Failed to load config: {resp.status}")

        # Get files if available
        async with session.get(f"{base_url}/exam/files") as resp:
            if resp.status == 200:
                print(f"[EXAM] Downloading exam files...")
                content = await resp.read()
                out_dir = os.path.join("data", "client", session_uuid, "exam_files")
                os.makedirs(out_dir, exist_ok=True)
                out_path = os.path.join(out_dir, "exam_materials.zip")
                with open(out_path, "wb") as f:
                    f.write(content)
                print(f"[EXAM] Exam files saved to {out_path}.")
            elif resp.status == 404:
                print("[EXAM] No exam files provided by server.")
            else:
                body = await resp.text()
                print(f"[EXAM] Failed to download exam files ({resp.status}): {body}")
