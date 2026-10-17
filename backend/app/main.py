from fastapi import FastAPI
from starlette.middleware.sessions import SessionMiddleware

from app.core.config import get_settings
from app.routers import api, bonita

settings = get_settings()

app = FastAPI(title=settings.app_name)
app.add_middleware(
    SessionMiddleware, secret_key=settings.session_secret, same_site="lax", max_age=8 * 3600
)
app.include_router(api.router)
app.include_router(bonita.router)
