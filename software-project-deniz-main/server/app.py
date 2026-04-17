import asyncio
from aiohttp import web

from common.discovery import ServerAnnouncer
from common.runtime_logging import install_asyncio_exception_logging
from .state import state
from .shutdown import ServerShutdownRoutine
from .handlers import (
    client_artifact_upload,
    health,
    login_handler,
    exam_config,
    exam_files,
    exam_submission,
    websocket_handler,
)
from .tasks import time_broadcaster, console_reader

async def start_background_tasks(app: web.Application):
    install_asyncio_exception_logging(asyncio.get_running_loop())
    app["time_broadcaster"] = asyncio.create_task(time_broadcaster(app))
    app["console_reader"] = asyncio.create_task(console_reader(app))
    # Start UDP discovery announcer
    announcer = ServerAnnouncer(server_host=app["host"], server_port=app["port"],
                                server_id=app["server_id"],
                                interval=app["announce_interval"])
    await announcer.start()
    app["announcer"] = announcer


async def cleanup_background_tasks(app: web.Application):
    await app["shutdown_routine"].run()

    for task_name in ("time_broadcaster", "console_reader"):
        app[task_name].cancel()
        try:
            await app[task_name]
        except asyncio.CancelledError:
            pass

    await app["announcer"].stop()
    
    if state.gui_process and state.gui_process.poll() is None:
        state.gui_process.kill()


def create_app(args) -> web.Application:
    state.load_users()
    app = web.Application(client_max_size=512 * 1024 * 1024)
    app["server_id"] = args.id
    app["host"] = args.host
    app["port"] = args.port
    app["broadcast_interval"] = args.interval
    app["announce_interval"] = args.announce
    app["exam_duration"] = args.exam_duration
    app["exam_files"] = args.exam_files
    app["exam_phase"] = "waiting"
    app["exam_start_enabled"] = False
    app["shutdown_grace_seconds"] = 2.0
    app["max_submission_bytes"] = 512 * 1024 * 1024
    app["max_artifact_bytes"] = 512 * 1024 * 1024
    app["shutdown_routine"] = ServerShutdownRoutine(app)
    app["gui_path"] = getattr(args, "gui_path", None)
    app["python_executable"] = getattr(args, "python_executable", None)
    
    app.router.add_get("/health", health)
    app.router.add_post("/login", login_handler)
    app.router.add_get("/exam/config", exam_config)
    app.router.add_get("/exam/files", exam_files)
    app.router.add_post("/exam/submission", exam_submission)
    app.router.add_post("/client/artifact", client_artifact_upload)
    app.router.add_get("/ws", websocket_handler)
    app.on_startup.append(start_background_tasks)
    app.on_cleanup.append(cleanup_background_tasks)
    return app
