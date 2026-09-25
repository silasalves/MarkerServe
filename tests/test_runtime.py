import sys
import types
from pathlib import Path

from app.config import Settings
from app.marker_runtime import MarkerRuntime
from app.schemas import ConversionOptions


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


def test_both_output_builds_once_and_runs_both_renderers(monkeypatch, tmp_path):
    calls = {"build": 0, "json": 0, "markdown": 0}

    class FakeParser:
        def __init__(self, config):
            calls["output_format"] = config["output_format"]
            self.config = config

        def get_converter_cls(self):
            return FakeConverter

        def get_llm_service(self):
            return None

        def generate_config_dict(self):
            return self.config

        def get_processors(self):
            return None

        def get_renderer(self):
            return "json"

    class FakeConverter:
        def __init__(self, **kwargs):
            pass

        def build_document(self, filepath):
            calls["build"] += 1
            return object()

        def resolve_dependencies(self, renderer_cls):
            return renderer_cls()

    class FakeJSONRenderer:
        def __call__(self, document):
            calls["json"] += 1
            return "json-rendered"

    class FakeMarkdownRenderer:
        def __call__(self, document):
            calls["markdown"] += 1
            return "markdown-rendered"

    def fake_text_from_rendered(rendered):
        if rendered == "json-rendered":
            return '{"children": [], "block_type": "Document"}', "json", {}
        return "# Test output", "md", {}

    modules = {
        "marker.config": types.ModuleType("marker.config"),
        "marker.config.parser": types.ModuleType("marker.config.parser"),
        "marker.converters": types.ModuleType("marker.converters"),
        "marker.converters.pdf": types.ModuleType("marker.converters.pdf"),
        "marker.output": types.ModuleType("marker.output"),
        "marker.renderers": types.ModuleType("marker.renderers"),
        "marker.renderers.json": types.ModuleType("marker.renderers.json"),
        "marker.renderers.markdown": types.ModuleType("marker.renderers.markdown"),
    }
    modules["marker.config.parser"].ConfigParser = FakeParser
    modules["marker.converters.pdf"].PdfConverter = FakeConverter
    modules["marker.output"].text_from_rendered = fake_text_from_rendered
    modules["marker.renderers.json"].JSONRenderer = FakeJSONRenderer
    modules["marker.renderers.markdown"].MarkdownRenderer = FakeMarkdownRenderer
    for name, module in modules.items():
        monkeypatch.setitem(sys.modules, name, module)

    runtime = MarkerRuntime(Settings(marker_use_llm=False))
    runtime.artifact_dict = {}
    result = runtime.convert(
        tmp_path / "input.pdf", ConversionOptions(output_format="both")
    )

    assert calls == {"build": 1, "json": 1, "markdown": 1, "output_format": "json"}
    assert result.output_format == "both"
    assert result.media_type == "application/json"
    assert result.content == '{"children": [], "block_type": "Document"}'
    assert result.markdown_content == "# Test output"
