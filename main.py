"""Production entry point for the Adapt Exporter backend."""

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from database.settings import settings
from utils.routes import router


def create_app() -> FastAPI:
    app = FastAPI(title="Adapt Exporter API", version="1.0.0")
    app.add_middleware(
        CORSMiddleware,
        allow_origins=settings.cors_origins,
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
    )
    app.include_router(router)
    return app


app = create_app()
