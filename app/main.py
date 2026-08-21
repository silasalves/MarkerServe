"""MarkerServe FastAPI application factory and ASGI entry point."""

from __future__ import annotations

import asyncio
import logging
import logging.config
from contextlib import asynccontextmanager
from typing import AsyncIterator

from fastapi import FastAPI
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse

from .api import build_router
from .config import Settings
from .health import VlmHealthChecker
from .marker_runtime import MarkerRuntime
from .version import __version__


def configure_logging(level: str) -> None:
    logging.basicConfig(
        level=getattr(logging, level.upper(), logging.INFO),
        format="%(asctime)s %(levelname)s %(name)s %(message)s",
    )


def create_app(
    settings: Settings | None = None,
    runtime: MarkerRuntime | None = None,
    vlm_checker: VlmHealthChecker | None = None,
) -> FastAPI:
    settings = settings or Settings.from_env()
    runtime = runtime or MarkerRuntime(settings)
    vlm_checker = vlm_checker or VlmHealthChecker()
    semaphore = asyncio.Semaphore(1)

    @asynccontextmanager
    async def lifespan(_: FastAPI) -> AsyncIterator[None]:
        configure_logging(settings.log_level)
        logging.getLogger(__name__).info(
            "starting MarkerServe version=%s marker_version=%s vlm_mode=%s vlm_url=%s",
            __version__,
            runtime.marker_version,
            settings.vlm_mode,
            settings.vlm_base_url,
        )
        await asyncio.to_thread(runtime.initialize)
        try:
            yield
        finally:
            shutdown = getattr(runtime, "shutdown", None)
            if shutdown is not None:
                await asyncio.to_thread(shutdown)

    app = FastAPI(title="MarkerServe", description="Production-oriented HTTP service for Marker OCR", version=__version__, lifespan=lifespan)
    app.include_router(build_router(settings, runtime, vlm_checker, semaphore))

    @app.exception_handler(RequestValidationError)
    async def request_validation_handler(_, exc: RequestValidationError) -> JSONResponse:
        return JSONResponse(
            status_code=422,
            content={"error": {"code": "request_validation_error", "message": "Invalid request", "details": {"errors": exc.errors()}}},
        )

    return app


app = create_app()
