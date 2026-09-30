"""Single-process entrypoint: the chat UI at / and the API, unchanged, under /api.

Used where one service has to serve both (e.g. Render):

    uvicorn frontend.asgi:site --host 0.0.0.0 --port $PORT
"""

from pathlib import Path

from starlette.applications import Starlette
from starlette.routing import Mount
from starlette.staticfiles import StaticFiles

from app.main import app as api

PUBLIC_DIR = Path(__file__).parent / "public"

site = Starlette(
    routes=[
        Mount("/api", app=api),
        Mount("/", app=StaticFiles(directory=PUBLIC_DIR, html=True)),
    ],
    # Starlette doesn't run a mounted app's lifespan, and the API builds its agent, cache
    # and security pipeline there
    lifespan=lambda _: api.router.lifespan_context(api),
)
