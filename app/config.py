"""Environment-backed MarkerServe configuration.

The application deliberately keeps its configuration vocabulary close to
Marker's own CLI/configuration names. Marker-specific values are assembled
into a ConfigParser input only at conversion time.
"""

from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path
from typing import Literal

from dotenv import load_dotenv


VlmMode = Literal["external", "managed"]
SuryaInferenceBackend = Literal["llamacpp", "vllm"]


def _env(name: str, default: str) -> str:
    value = os.getenv(name)
    return default if value is None or value == "" else value


def _bool_env(name: str, default: bool) -> bool:
    value = os.getenv(name)
    if value is None or value == "":
        return default
    normalized = value.strip().lower()
    if normalized in {"1", "true", "yes", "on"}:
        return True
    if normalized in {"0", "false", "no", "off"}:
        return False
    raise ValueError(f"{name} must be a boolean, got {value!r}")


def _int_env(name: str, default: int) -> int:
    value = os.getenv(name)
    if value is None or value == "":
        return default
    try:
        return int(value)
    except ValueError as exc:
        raise ValueError(f"{name} must be an integer, got {value!r}") from exc


@dataclass(frozen=True, slots=True)
class Settings:
    """Runtime settings loaded from environment variables."""

    app_name: str = "MarkerServe"
    host: str = "127.0.0.1"
    port: int = 8000
    log_level: str = "INFO"
    vlm_mode: VlmMode = "external"
    vlm_base_url: str = "http://127.0.0.1:8080/v1"
    vlm_health_timeout_seconds: float = 3.0
    vlm_required: bool = True
    marker_use_llm: bool = True
    marker_mode: str | None = "balanced"
    marker_output_format: str = "markdown"
    marker_llm_service: str = "marker.services.openai.OpenAIService"
    marker_openai_model: str = "qwen3.5-9b"
    marker_openai_api_key: str = "local"
    marker_openai_image_format: str = "png"
    marker_force_ocr: bool = True
    marker_disable_image_extraction: bool = True
    marker_timeout_seconds: int = 600
    marker_pdftext_workers: int = 1
    max_upload_bytes: int = 50 * 1024 * 1024
    conversion_queue_timeout_seconds: float = 0.0
    llama_server_bin: str | None = None
    llama_host: str = "127.0.0.1"
    llama_port: int = 8080
    llama_models_preset: str = "config/models.ini"
    surya_inference_backend: SuryaInferenceBackend = "llamacpp"

    @classmethod
    def from_env(cls) -> "Settings":
        load_dotenv()

        mode = _env("VLM_MODE", "external").lower()
        if mode not in {"external", "managed"}:
            raise ValueError("VLM_MODE must be 'external' or 'managed'")

        surya_backend = _env("SURYA_INFERENCE_BACKEND", "llamacpp").lower()
        if surya_backend not in {"llamacpp", "vllm"}:
            raise ValueError(
                "SURYA_INFERENCE_BACKEND must be 'llamacpp' or 'vllm'"
            )

        marker_mode = os.getenv("MARKER_MODE")
        if marker_mode == "":
            marker_mode = None
        elif marker_mode is None:
            marker_mode = "balanced"

        llama_bin = os.getenv("LLAMA_SERVER_BIN") or None
        return cls(
            host=_env("MARKERSERVE_HOST", "127.0.0.1"),
            port=_int_env("MARKERSERVE_PORT", 8000),
            log_level=_env("LOG_LEVEL", "INFO").upper(),
            vlm_mode=mode,  # type: ignore[arg-type]
            vlm_base_url=_env("VLM_BASE_URL", "http://127.0.0.1:8080/v1").rstrip("/"),
            vlm_health_timeout_seconds=float(_env("VLM_HEALTH_TIMEOUT_SECONDS", "3")),
            vlm_required=_bool_env("VLM_REQUIRED", True),
            marker_use_llm=_bool_env("MARKER_USE_LLM", True),
            marker_mode=marker_mode,
            marker_output_format=_env("MARKER_OUTPUT_FORMAT", "markdown"),
            marker_llm_service=_env(
                "MARKER_LLM_SERVICE", "marker.services.openai.OpenAIService"
            ),
            marker_openai_model=_env("MARKER_OPENAI_MODEL", "qwen3.5-9b"),
            marker_openai_api_key=_env("MARKER_OPENAI_API_KEY", "local"),
            marker_openai_image_format=_env("MARKER_OPENAI_IMAGE_FORMAT", "png"),
            marker_force_ocr=_bool_env("MARKER_FORCE_OCR", True),
            marker_disable_image_extraction=_bool_env(
                "MARKER_DISABLE_IMAGE_EXTRACTION", True
            ),
            marker_timeout_seconds=_int_env("MARKER_TIMEOUT_SECONDS", 600),
            marker_pdftext_workers=_int_env("MARKER_PDFTEXT_WORKERS", 1),
            max_upload_bytes=_int_env("MAX_UPLOAD_BYTES", 50 * 1024 * 1024),
            conversion_queue_timeout_seconds=float(
                _env("CONVERSION_QUEUE_TIMEOUT_SECONDS", "0")
            ),
            llama_server_bin=llama_bin,
            llama_host=_env("LLAMA_HOST", "127.0.0.1"),
            llama_port=_int_env("LLAMA_PORT", 8080),
            llama_models_preset=_env("LLAMA_MODELS_PRESET", "config/models.ini"),
            surya_inference_backend=surya_backend,  # type: ignore[arg-type]
        )

    @property
    def requires_vlm(self) -> bool:
        return self.vlm_required and self.marker_use_llm

    def marker_config(self, overrides: dict[str, object] | None = None) -> dict[str, object]:
        """Build the options passed to Marker ConfigParser."""

        config: dict[str, object] = {
            "output_format": self.marker_output_format,
            "use_llm": self.marker_use_llm,
            "llm_service": self.marker_llm_service,
            "openai_base_url": self.vlm_base_url,
            "openai_model": self.marker_openai_model,
            "openai_api_key": self.marker_openai_api_key,
            "openai_image_format": self.marker_openai_image_format,
            "force_ocr": self.marker_force_ocr,
            "extract_images": not self.marker_disable_image_extraction,
            "timeout": self.marker_timeout_seconds,
            "pdftext_workers": self.marker_pdftext_workers,
        }
        if self.marker_mode is not None:
            config["mode"] = self.marker_mode
        if overrides:
            config.update({key: value for key, value in overrides.items() if value is not None})
            if "disable_image_extraction" in overrides:
                config["extract_images"] = not bool(overrides["disable_image_extraction"])
        return config

    def models_preset_path(self, project_root: Path) -> Path:
        path = Path(self.llama_models_preset)
        return path if path.is_absolute() else project_root / path
