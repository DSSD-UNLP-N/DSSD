from fastapi import FastAPI

from app.core.config import get_settings
from app.routers import api

settings = get_settings()

app = FastAPI(title=settings.app_name)
app.include_router(api.router)
app.include_router(api.national_auth_router)
