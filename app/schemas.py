"""Pydantic request/response models used at the HTTP boundary."""

from __future__ import annotations

from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator


OutputFormat = Literal["markdown", "json", "html"]


class ConversionOptions(BaseModel):
    model_config = ConfigDict(extra="forbid")

    output_format: OutputFormat = "markdown"
    mode: Literal["balanced", "fast"] | None = None
    use_llm: bool | None = None
    force_ocr: bool | None = None
    page_range: str | None = None
    processors: str | None = None
    disable_image_extraction: bool | None = None
    disable_multiprocessing: bool | None = None

    @field_validator("page_range", "processors")
    @classmethod
    def non_empty_string(cls, value: str | None) -> str | None:
        if value is not None and not value.strip():
            return None
        return value


class ErrorBody(BaseModel):
    code: str
    message: str
    details: dict[str, Any] | None = None


class ErrorResponse(BaseModel):
    error: ErrorBody


class HealthResponse(BaseModel):
    status: str
    service: str
    details: dict[str, Any] = Field(default_factory=dict)
