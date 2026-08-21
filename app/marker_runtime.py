"""Lazy, upstream-only integration with marker-pdf."""

from __future__ import annotations

import importlib.metadata
import logging
import os
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from .config import Settings
from .schemas import ConversionOptions

logger = logging.getLogger(__name__)


class MarkerUnavailableError(RuntimeError):
    """Marker models/runtime could not be initialized."""


class MarkerConversionError(RuntimeError):
    """Marker failed to convert an input document."""


@dataclass(frozen=True, slots=True)
class ConversionResult:
    output_format: str
    content: str
    media_type: str
    duration_seconds: float


class MarkerRuntime:
    """Owns one initialized Marker model dictionary for serialized conversions."""

    def __init__(self, settings: Settings):
        self.settings = settings
        self.artifact_dict: dict[str, Any] | None = None
        self.initialization_error: str | None = None

    @property
    def marker_version(self) -> str | None:
        try:
            return importlib.metadata.version("marker-pdf")
        except importlib.metadata.PackageNotFoundError:
            return None

    def initialize(self) -> None:
        if self.artifact_dict is not None:
            return
        try:
            # marker-pdf 2.0 delegates Surya VLM inference to a backend that
            # auto-selects vLLM on NVIDIA hosts. Make the configured choice
            # explicit before importing Surya's settings singleton and pass it
            # through to Marker too.
            os.environ["SURYA_INFERENCE_BACKEND"] = self.settings.surya_inference_backend
            if self.settings.llama_server_bin:
                os.environ["LLAMA_CPP_BINARY"] = self.settings.llama_server_bin
            elif not os.getenv("LLAMA_CPP_BINARY"):
                default_binary = Path(r"D:\llamacpp\llama-server.exe")
                if default_binary.is_file():
                    os.environ["LLAMA_CPP_BINARY"] = str(default_binary)

            from marker.models import create_model_dict

            logger.info("initializing Marker models")
            self.artifact_dict = create_model_dict(
                inference_backend=self.settings.surya_inference_backend
            )
            self.initialization_error = None
            logger.info("Marker models initialized")
        except Exception as exc:  # model loading errors should make readiness fail, not liveness
            self.initialization_error = f"{type(exc).__name__}: {exc}"
            logger.exception("Marker initialization failed")

    def shutdown(self) -> None:
        """Stop any Surya backend spawned by Marker during this process."""

        if self.artifact_dict is None:
            return
        try:
            from marker.models import shutdown_models

            shutdown_models(self.artifact_dict)
        except Exception:
            logger.exception("Marker shutdown failed")
        finally:
            self.artifact_dict = None

    def is_ready(self) -> bool:
        return self.artifact_dict is not None

    def convert(self, filepath: Path, options: ConversionOptions) -> ConversionResult:
        if self.artifact_dict is None:
            raise MarkerUnavailableError(self.initialization_error or "Marker is not initialized")

        started = time.perf_counter()
        try:
            from marker.config.parser import ConfigParser
            from marker.converters.pdf import PdfConverter
            from marker.output import text_from_rendered

            overrides = options.model_dump(exclude_none=True)
            config = self.settings.marker_config(overrides)
            parser = ConfigParser(config)
            converter_cls = parser.get_converter_cls() if hasattr(parser, "get_converter_cls") else PdfConverter
            llm_service = (
                parser.get_llm_service()
                if hasattr(parser, "get_llm_service")
                else config.get("llm_service")
            )
            converter = converter_cls(
                config=parser.generate_config_dict(),
                artifact_dict=self.artifact_dict,
                processor_list=parser.get_processors(),
                renderer=parser.get_renderer(),
                llm_service=llm_service,
            )
            rendered = converter(str(filepath))
            content, _, _ = text_from_rendered(rendered)
        except Exception as exc:
            raise MarkerConversionError(f"{type(exc).__name__}: {exc}") from exc

        output_format = options.output_format
        media_type = {
            "markdown": "text/markdown; charset=utf-8",
            "html": "text/html; charset=utf-8",
            "json": "application/json",
        }[output_format]
        duration = time.perf_counter() - started
        logger.info(
            "conversion complete format=%s duration_seconds=%.3f",
            output_format,
            duration,
        )
        return ConversionResult(output_format, content, media_type, duration)
