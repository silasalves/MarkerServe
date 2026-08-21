"""FastAPI routes for MarkerServe."""

from __future__ import annotations

import asyncio
import json
import logging
import tempfile
import time
from pathlib import Path
from typing import Callable

from fastapi import APIRouter, File, Form, Request, UploadFile
from fastapi.responses import HTMLResponse, JSONResponse, PlainTextResponse, Response
from pydantic import ValidationError
from starlette.concurrency import run_in_threadpool

from .config import Settings
from .health import VlmHealthChecker
from .marker_runtime import MarkerConversionError, MarkerRuntime, MarkerUnavailableError
from .schemas import ConversionOptions
from .version import __version__

logger = logging.getLogger(__name__)


def error_response(status_code: int, code: str, message: str, details: dict | None = None) -> JSONResponse:
    return JSONResponse(
        status_code=status_code,
        content={"error": {"code": code, "message": message, "details": details}},
    )


def _bool_form(value: bool | None) -> bool | None:
    return value


def build_router(
    settings: Settings,
    runtime: MarkerRuntime,
    vlm_checker: VlmHealthChecker,
    semaphore: asyncio.Semaphore,
) -> APIRouter:
    router = APIRouter()

    @router.get("/health/live")
    async def live() -> dict:
        return {"status": "ok", "service": settings.app_name}

    @router.get("/health/ready")
    async def ready() -> Response:
        details = {"marker_initialized": runtime.is_ready()}
        if runtime.initialization_error:
            details["marker_error"] = runtime.initialization_error
        if not runtime.is_ready():
            return JSONResponse(status_code=503, content={"status": "not_ready", "service": settings.app_name, "details": details})

        vlm_check = await vlm_checker.check(settings)
        details["vlm"] = vlm_check.details
        if not vlm_check.healthy:
            return JSONResponse(status_code=503, content={"status": "not_ready", "service": settings.app_name, "details": details})
        return {"status": "ready", "service": settings.app_name, "details": details}

    @router.get("/version")
    async def version() -> dict:
        return {
            "markerserve_version": __version__,
            "marker_pdf_version": runtime.marker_version,
            "python_version": __import__("platform").python_version(),
            "vlm_mode": settings.vlm_mode,
            "vlm_base_url": settings.vlm_base_url,
            "marker_use_llm": settings.marker_use_llm,
            "marker_mode": settings.marker_mode,
        }

    @router.post("/v1/convert")
    async def convert(
        request: Request,
        file: UploadFile = File(...),
        output_format: str | None = Form(None),
        mode: str | None = Form(None),
        use_llm: bool | None = Form(None),
        force_ocr: bool | None = Form(None),
        page_range: str | None = Form(None),
        processors: str | None = Form(None),
        disable_image_extraction: bool | None = Form(None),
        disable_multiprocessing: bool | None = Form(None),
    ) -> Response:
        try:
            options = ConversionOptions(
                output_format=output_format or settings.marker_output_format,
                mode=mode,
                use_llm=_bool_form(use_llm),
                force_ocr=_bool_form(force_ocr),
                page_range=page_range,
                processors=processors,
                disable_image_extraction=_bool_form(disable_image_extraction),
                disable_multiprocessing=_bool_form(disable_multiprocessing),
            )
        except ValidationError as exc:
            return error_response(422, "invalid_conversion_options", "Invalid conversion options", {"errors": exc.errors()})

        if settings.conversion_queue_timeout_seconds <= 0:
            # A zero timeout means "do not wait", but the first request must
            # still be able to acquire the free slot.
            if semaphore.locked():
                return error_response(429, "conversion_busy", "Another conversion is already running")
            await semaphore.acquire()
        else:
            try:
                await asyncio.wait_for(
                    semaphore.acquire(), timeout=settings.conversion_queue_timeout_seconds
                )
            except TimeoutError:
                return error_response(429, "conversion_busy", "Another conversion is already running")

        temporary_path: Path | None = None
        started = time.perf_counter()
        try:
            if not file.filename:
                return error_response(422, "invalid_file", "A filename is required")
            if not file.filename.lower().endswith(".pdf"):
                return error_response(415, "unsupported_file", "Only PDF uploads are supported")

            with tempfile.NamedTemporaryFile(prefix="markerserve-", suffix=".pdf", delete=False) as handle:
                temporary_path = Path(handle.name)
                total = 0
                while chunk := await file.read(1024 * 1024):
                    total += len(chunk)
                    if total > settings.max_upload_bytes:
                        return error_response(413, "file_too_large", "The uploaded PDF exceeds the configured size limit")
                    handle.write(chunk)

            if total == 0:
                return error_response(422, "invalid_file", "The uploaded PDF is empty")
            with temporary_path.open("rb") as pdf:
                if pdf.read(5) != b"%PDF-":
                    return error_response(415, "invalid_pdf", "The uploaded file does not have a PDF signature")

            if not runtime.is_ready():
                return error_response(503, "marker_unavailable", "Marker is not ready")
            result = await run_in_threadpool(runtime.convert, temporary_path, options)
            headers = {
                "X-MarkerServe-Output-Format": result.output_format,
                "X-MarkerServe-Duration-Seconds": f"{result.duration_seconds:.3f}",
            }
            if result.output_format == "json":
                try:
                    return JSONResponse(content=json.loads(result.content), headers=headers)
                except json.JSONDecodeError:
                    return PlainTextResponse(result.content, media_type=result.media_type, headers=headers)
            if result.output_format == "html":
                return HTMLResponse(result.content, headers=headers)
            return PlainTextResponse(result.content, media_type=result.media_type, headers=headers)
        except MarkerUnavailableError as exc:
            return error_response(503, "marker_unavailable", str(exc))
        except MarkerConversionError:
            logger.exception("conversion failed after %.3f seconds", time.perf_counter() - started)
            return error_response(500, "conversion_failed", "Marker failed to convert the PDF")
        finally:
            await file.close()
            if temporary_path is not None:
                temporary_path.unlink(missing_ok=True)
            semaphore.release()

    return router
