import sys
import types

from app.config import Settings
from app.marker_runtime import MarkerRuntime


def test_runtime_forces_llamacpp_backend(monkeypatch):
    calls = {}
    marker_module = types.ModuleType("marker")
    models_module = types.ModuleType("marker.models")

    def create_model_dict(**kwargs):
        calls.update(kwargs)
        return {"inference_manager": object()}

    models_module.create_model_dict = create_model_dict
    marker_module.models = models_module
    monkeypatch.setitem(sys.modules, "marker", marker_module)
    monkeypatch.setitem(sys.modules, "marker.models", models_module)

    runtime = MarkerRuntime(
        Settings(llama_server_bin=r"D:\llamacpp\llama-server.exe")
    )
    runtime.initialize()

    assert calls == {"inference_backend": "llamacpp"}
    assert runtime.is_ready()
    assert runtime.initialization_error is None
    assert __import__("os").environ["SURYA_INFERENCE_BACKEND"] == "llamacpp"
    assert __import__("os").environ["LLAMA_CPP_BINARY"] == r"D:\llamacpp\llama-server.exe"
