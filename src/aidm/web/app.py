from pathlib import Path

from fastapi import FastAPI
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates

from aidm.config.settings import Settings
from aidm.web.routes import dev

_WEB = Path(__file__).parent


def create_app(settings: Settings) -> FastAPI:
    app = FastAPI(title="AI Game Master")
    app.state.settings = settings
    app.state.templates = Jinja2Templates(directory=_WEB / "templates")
    app.mount("/static", StaticFiles(directory=_WEB / "static"), name="static")
    if settings.dev_page:
        app.include_router(dev.router)
    return app
