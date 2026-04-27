# main.py - FastAPI entrypoint for the avatar tutor POC backend
from __future__ import annotations

from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles

from app.api.rest import router as rest_router
from app.api.websocket import router as websocket_router
from app.core.config import get_settings
from app.db.repository import PostgresRepository
from app.dependencies import build_services


@asynccontextmanager
async def lifespan(app: FastAPI):
    settings = get_settings()
    app.state.services = await build_services(settings)
    yield
    repository = app.state.services.repository
    if isinstance(repository, PostgresRepository):
        await repository.close()


def create_app() -> FastAPI:
    settings = get_settings()
    app = FastAPI(title=settings.app_name, lifespan=lifespan)
    app.add_middleware(
        CORSMiddleware,
        allow_origins=settings.cors_origins,
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
    )
    app.mount("/static", StaticFiles(directory="app/static"), name="static")
    app.include_router(rest_router)
    app.include_router(websocket_router)
    return app


app = create_app()

