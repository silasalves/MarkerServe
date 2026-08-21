"""Readiness checks for the MarkerServe process and external VLM."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

import httpx

from .config import Settings


@dataclass(frozen=True, slots=True)
class VlmCheck:
    healthy: bool
    details: dict[str, Any]


class VlmHealthChecker:
    """Check the OpenAI-compatible endpoint without logging credentials."""

    async def check(self, settings: Settings) -> VlmCheck:
        if not settings.requires_vlm:
            return VlmCheck(True, {"required": False, "reason": "Marker LLM disabled"})

        base_url = settings.vlm_base_url.rstrip("/")
        models_url = f"{base_url}/models"
        health_url = f"{base_url.removesuffix('/v1')}/health"
        try:
            async with httpx.AsyncClient(timeout=settings.vlm_health_timeout_seconds) as client:
                response = await client.get(models_url)
                if response.status_code == 200:
                    payload = response.json()
                    models = payload.get("data", []) if isinstance(payload, dict) else []
                    model_ids = [str(item.get("id")) for item in models if isinstance(item, dict)]
                    configured_model = settings.marker_openai_model
                    model_available = not model_ids or configured_model in model_ids
                    if not model_available:
                        return VlmCheck(
                            False,
                            {
                                "required": True,
                                "endpoint": base_url,
                                "reason": "configured model is not advertised",
                                "configured_model": configured_model,
                                "available_models": model_ids[:20],
                            },
                        )
                    return VlmCheck(
                        True,
                        {
                            "required": True,
                            "endpoint": base_url,
                            "model": configured_model,
                        },
                    )

                # Some compatible servers expose /health but not /v1/models.
                health_response = await client.get(health_url)
                if health_response.status_code == 200:
                    return VlmCheck(
                        True,
                        {"required": True, "endpoint": base_url, "model_check": "not advertised"},
                    )
                return VlmCheck(
                    False,
                    {
                        "required": True,
                        "endpoint": base_url,
                        "reason": f"HTTP {response.status_code} from /models and HTTP {health_response.status_code} from /health",
                    },
                )
        except (httpx.HTTPError, ValueError) as exc:
            return VlmCheck(
                False,
                {"required": True, "endpoint": base_url, "reason": type(exc).__name__},
            )
