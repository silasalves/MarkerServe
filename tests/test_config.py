from app.config import Settings


def test_marker_config_preserves_marker_names(monkeypatch):
    monkeypatch.setenv("VLM_BASE_URL", "http://localhost:8080/v1")
    monkeypatch.setenv("MARKER_OPENAI_MODEL", "qwen3.5-9b")
    settings = Settings.from_env()

    config = settings.marker_config({"output_format": "json", "use_llm": False})

    assert config["openai_base_url"] == "http://localhost:8080/v1"
    assert config["openai_model"] == "qwen3.5-9b"
    assert config["output_format"] == "json"
    assert config["use_llm"] is False


def test_managed_mode_does_not_change_app_vlm_url(monkeypatch):
    monkeypatch.setenv("VLM_MODE", "managed")
    settings = Settings.from_env()
    assert settings.vlm_mode == "managed"
    assert settings.vlm_base_url == "http://127.0.0.1:8080/v1"


def test_vllm_surya_backend_is_allowed(monkeypatch):
    monkeypatch.setenv("SURYA_INFERENCE_BACKEND", "vllm")
    settings = Settings.from_env()
    assert settings.surya_inference_backend == "vllm"


def test_unknown_surya_backend_is_rejected(monkeypatch):
    monkeypatch.setenv("SURYA_INFERENCE_BACKEND", "unknown")
    try:
        Settings.from_env()
    except ValueError as exc:
        assert "llamacpp" in str(exc)
        assert "vllm" in str(exc)
    else:
        raise AssertionError("unknown Surya backend should be rejected")
