import pytest

from app.config import Settings
from app.health import VlmHealthChecker


@pytest.mark.asyncio
async def test_health_check_skips_vlm_when_not_required(monkeypatch):
    monkeypatch.setenv("MARKER_USE_LLM", "false")
    settings = Settings.from_env()
    result = await VlmHealthChecker().check(settings)
    assert result.healthy is True
    assert result.details["required"] is False
