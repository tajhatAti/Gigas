"""main.py - chalu korar file. Eta ke CodeNest e main file hishebe dao."""
import asyncio

from aiohttp import web

from core import PORT, SESSION, SESSION_FILE, hub
from webapp import make_app


async def on_startup(app):
    hub.load_plugins()
    hub.start_background()
    session = SESSION.strip()
    if not session:
        try:
            with open(SESSION_FILE) as f:
                session = f.read().strip()
        except Exception:
            session = ""
    if session:
        asyncio.create_task(hub.connect(session))


if __name__ == "__main__":
    app = make_app()
    app.on_startup.append(on_startup)
    web.run_app(app, host="0.0.0.0", port=PORT)
